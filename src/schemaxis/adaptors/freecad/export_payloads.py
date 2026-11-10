"""Bind publications to trusted regenerated exports, without native imports.

STEP equality is lexical: only whitespace, comments and the calendar-valid
producer FILE_NAME timestamp may differ. Numbers, references, strings and every
other header field retain their exact spelling. STL equality covers every byte.
This is an export identity check, not a shape-equivalence or precision test.
"""
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import os
from pathlib import Path
import re
import stat
import struct

from schemaxis.errors import fail
from . import step_source
from .export_checks import MAX_FACETS

MAX_BYTES = 256 * 1024 * 1024
MAX_HEADER_BYTES = 64 * 1024
CHUNK_BYTES = 1024 * 1024
_TIMESTAMP = re.compile(r"'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}'\Z")


def checkpoint():
    step_source.checkpoint()


@dataclass(frozen=True)
class Payload:
    """One immutable, bounded byte snapshot; its digest is never caller supplied."""
    data: bytes = field(repr=False)
    sha256: str = field(init=False)
    size: int = field(init=False)

    def __post_init__(self):
        if not isinstance(self.data, bytes):
            fail('VERIFICATION_FAILED', 'export snapshot must contain immutable bytes')
        if len(self.data) > MAX_BYTES:
            fail('RESOURCE_LIMIT', 'export payload exceeds the byte bound', limit=MAX_BYTES)
        digest = hashlib.sha256()
        for start in range(0, len(self.data), CHUNK_BYTES):
            checkpoint()
            digest.update(self.data[start:start + CHUNK_BYTES])
        checkpoint()
        object.__setattr__(self, 'sha256', digest.hexdigest())
        object.__setattr__(self, 'size', len(self.data))


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _checked(payload, kind, location):
    if kind == 'stl':
        count = struct.unpack('<I', payload.data[80:84])[0] if payload.size >= 84 else 0
        if not 4 <= count <= MAX_FACETS or payload.size != 84 + 50 * count:
            fail('VERIFICATION_FAILED', 'export must be a bounded binary STL', location,
                 facets=count, limit=MAX_FACETS)
    return payload


def capture(value, *, kind=None, location='$'):
    """Capture bytes or a bounded regular file, rejecting symlinks and read races.

    Resolve the parent once, admitting ordinary symlinked project/TMPDIR paths.
    Walk that resolved directory by descriptor; the member itself must never be
    a symlink. A renamed parent cannot redirect an in-progress descriptor read.
    The returned bytes, rather than a later path read, are the comparison input.
    This does not claim protection against an adversary controlling this process.
    """
    checkpoint()
    if kind not in (None, 'step', 'stl'):
        fail('VERIFICATION_FAILED', 'unknown export snapshot kind', location)
    limit = min(MAX_BYTES, 84 + 50 * MAX_FACETS) if kind == 'stl' else MAX_BYTES
    if isinstance(value, Payload):
        if not isinstance(value.data, bytes):
            fail('VERIFICATION_FAILED', 'export snapshot must contain immutable bytes', location)
        if len(value.data) > limit:
            fail('RESOURCE_LIMIT', 'export snapshot exceeds its byte bound', location, limit=limit)
        checked = Payload(value.data)
        if checked.sha256 != value.sha256 or checked.size != value.size:
            fail('VERIFICATION_FAILED', 'export snapshot digest or size is inconsistent', location)
        return _checked(checked, kind, location)
    if isinstance(value, bytes):
        if len(value) > limit:
            fail('RESOURCE_LIMIT', 'export payload exceeds its byte bound', location, limit=limit)
        return _checked(Payload(value), kind, location)
    descriptors = []
    try:
        supplied = Path(value)
        if '..' in supplied.parts:
            fail('VERIFICATION_FAILED', 'export path must not contain parent traversal', location)
        absolute = Path(os.path.abspath(supplied))
        path = absolute.parent.resolve(strict=True)/absolute.name
        directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(directory)
        for component in path.parts[1:-1]:
            checkpoint()
            directory = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=directory)
            descriptors.append(directory)
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory)
        descriptors.append(descriptor)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            fail('VERIFICATION_FAILED', 'export must be a regular non-symlink file', location)
        if before.st_size > limit:
            fail('RESOURCE_LIMIT', 'export payload exceeds its byte bound', location, limit=limit)
        chunks, size = [], 0
        while True:
            checkpoint()
            chunk = os.read(descriptor, min(CHUNK_BYTES, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > limit:
                fail('RESOURCE_LIMIT', 'export grew beyond its byte bound', location, limit=limit)
        after = os.fstat(descriptor)
        named = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
        if _identity(before) != _identity(after) or _identity(after) != _identity(named) or size != after.st_size:
            fail('VERIFICATION_FAILED', 'export changed during capture', location)
        return _checked(Payload(b''.join(chunks)), kind, location)
    except (OSError, TypeError, ValueError) as error:
        fail('VERIFICATION_FAILED', 'cannot capture a regular export file', location,
             reason=str(error))
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


class _Tokens:
    """Use the existing STEP lexical vocabulary, retaining offsets and lexemes."""
    def __init__(self, data, location):
        try:
            self.text = data.decode('ascii')
        except UnicodeDecodeError:
            fail('VERIFICATION_FAILED', 'STEP export must be ASCII', location)
        self.position, self.location, self.header = 0, location, True
        self.records = 0

    def next(self):
        while self.position < len(self.text):
            if self.records % step_source.CHECK_EVERY == 0:
                checkpoint()
            self.records += 1
            # Restrict the regex search itself while parsing the bounded header.
            end = min(len(self.text), MAX_HEADER_BYTES) if self.header else len(self.text)
            if self.text.startswith('/*', self.position):
                # Comments may span many tokens, but each search remains bounded
                # and cancellation is observed between chunks (including overlap).
                scan = self.position + 2
                while True:
                    checkpoint()
                    stop = min(end, scan + CHUNK_BYTES)
                    close = self.text.find('*/', scan, stop)
                    if close >= 0:
                        self.position = close + 2
                        break
                    if stop == end:
                        fail('VERIFICATION_FAILED', 'unterminated or over-bound STEP comment', self.location)
                    scan = stop - 1
                continue
            # Bounded regex windows prevent oversized strings or tokens from
            # allocating an unbounded regex backtracking stack before refusal.
            first = self.text[self.position]
            literal = first in ('\'', '"')
            window = min(end, self.position + step_source.MAX_STRING + 1)
            match = step_source.TOKEN.match(self.text, self.position, window)
            if match is None:
                if literal and window < end:
                    fail('RESOURCE_LIMIT', 'STEP export literal exceeds its lexical window',
                         self.location, limit=step_source.MAX_STRING)
                fail('VERIFICATION_FAILED', 'malformed or over-bound STEP export token', self.location,
                     offset=self.position)
            self.position = match.end()
            kind, value = match.lastgroup, match.group(match.lastgroup)
            if kind in ('ws', 'comment'):
                continue
            limit = step_source.MAX_STRING if kind in ('string', 'binary') else step_source.MAX_TOKEN
            if len(value) > limit:
                fail('RESOURCE_LIMIT', 'STEP export token exceeds its bound', self.location, limit=limit)
            if literal and match.end() == window and window < end:
                fail('RESOURCE_LIMIT', 'STEP export literal reaches its lexical window',
                     self.location, limit=limit)
            if kind == 'keyword' and value.startswith('!'):
                fail('VERIFICATION_FAILED', 'user-defined STEP export entity is unsupported', self.location)
            return kind, value
        return None


def _step_tokens(payload, location):
    lexer = _Tokens(payload.data, location)
    header = []

    def take(kind, value=None):
        token = lexer.next()
        if token is None or token[0] != kind or (value is not None and token[1] != value):
            fail('VERIFICATION_FAILED', 'STEP export has a malformed producer header', location,
                 expected=value or kind, found=token)
        header.append(token)
        return token[1]

    def punct(value):
        take('punct', value)

    def strings():
        punct('(')
        take('string')
        while True:
            token = lexer.next()
            header.append(token)
            if token == ('punct', ')'):
                return
            if token != ('punct', ','):
                fail('VERIFICATION_FAILED', 'STEP header requires a nonempty string list', location)
            take('string')

    take('keyword', 'ISO-10303-21'); punct(';')
    take('keyword', 'HEADER'); punct(';')
    take('keyword', 'FILE_DESCRIPTION'); punct('(')
    strings(); punct(','); take('string'); punct(')'); punct(';')
    take('keyword', 'FILE_NAME'); punct('(')
    take('string'); punct(',')
    timestamp = take('string')
    if not _TIMESTAMP.fullmatch(timestamp):
        fail('VERIFICATION_FAILED', 'STEP producer timestamp must use YYYY-MM-DDTHH:MM:SS', location)
    try:
        datetime.strptime(timestamp[1:-1], '%Y-%m-%dT%H:%M:%S')
    except ValueError:
        fail('VERIFICATION_FAILED', 'STEP producer timestamp is not calendar-valid', location)
    header[-1] = ('timestamp', '<producer-time>')
    punct(','); strings(); punct(','); strings()
    for unused in range(3):
        punct(','); take('string')
    punct(')'); punct(';')
    take('keyword', 'FILE_SCHEMA'); punct('('); strings(); punct(')'); punct(';')
    take('keyword', 'ENDSEC'); punct(';')
    lexer.header = False
    yield from header
    # All DATA tokens retain exact lexemes. The trusted expected export supplies
    # entity semantics; this binder never converts numbers or renumbers IDs.
    for expected in (('keyword', 'DATA'), ('punct', ';')):
        token = lexer.next()
        if token != expected:
            fail('VERIFICATION_FAILED', 'STEP export requires one DATA section', location)
        yield token
    while True:
        token = lexer.next()
        if token is None:
            fail('VERIFICATION_FAILED', 'STEP export has no DATA terminator', location)
        yield token
        if token == ('keyword', 'ENDSEC'):
            break
    for expected in (('punct', ';'), ('keyword', 'END-ISO-10303-21'), ('punct', ';')):
        token = lexer.next()
        if token != expected:
            fail('VERIFICATION_FAILED', 'STEP export trailer is malformed', location)
        yield token
    if lexer.next() is not None:
        fail('VERIFICATION_FAILED', 'STEP export has trailing content', location)
    checkpoint()


def bind(step, stl, *, expected_step, expected_stl, location='$'):
    """Return submitted snapshots only when both match trusted generated exports.

    Expected exports must come from the trusted typed reconstruction. This
    function does not authenticate a caller-supplied expected file or receipt.
    Consumers should use the returned snapshots, or recheck their digests before
    opening a private copy; path stability after capture is not promised.
    """
    submitted = {'step': capture(step, kind='step', location=location + '.step'),
                 'stl': capture(stl, kind='stl', location=location + '.stl')}
    expected = {'step': capture(expected_step, kind='step', location=location + '.expectedStep'),
                'stl': capture(expected_stl, kind='stl', location=location + '.expectedStl')}
    left = _step_tokens(submitted['step'], location + '.step')
    right = _step_tokens(expected['step'], location + '.expectedStep')
    index = 0
    while True:
        if index % step_source.CHECK_EVERY == 0:
            checkpoint()
        a, b = next(left, None), next(right, None)
        if a != b:
            fail('VERIFICATION_FAILED', 'STEP export differs from the trusted regenerated payload',
                 location + '.step', token=index)
        if a is None:
            break
        index += 1
    if submitted['stl'].data != expected['stl'].data:
        fail('VERIFICATION_FAILED', 'STL export differs from the trusted regenerated payload', location + '.stl')
    checkpoint()
    return submitted
