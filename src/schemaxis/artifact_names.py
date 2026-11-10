"""Portable, readable artifact names and durable run-wide reservations.

Copyright (C) 2026 David L. F. Gaden.
SPDX-License-Identifier: Apache-2.0
"""
from contextlib import contextmanager
from contextvars import ContextVar
import math
import os
from pathlib import Path
import re

from .errors import fail

VERSION = 'schemaxis.artifact-name/1'
_ROOT = ContextVar('artifact_run_root', default=None)
_NUMBER = re.compile(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:e-?[0-9]+)?\Z')
_KEY = re.compile(r'[A-Za-z][A-Za-z0-9]*\Z')
MAX_STEM = 180  # Leaves room for format suffixes, companions and staging names.


@contextmanager
def run_scope(directory):
    """Nested operations and copied thread contexts share the outer run root."""
    token = _ROOT.set(_ROOT.get() or Path(directory).expanduser().absolute())
    try:
        yield
    finally:
        _ROOT.reset(token)


def run_root(directory):
    return _ROOT.get() or Path(directory).expanduser().absolute()


def scalar(value):
    if value is None:
        return 'null'
    if type(value) is bool:
        return 'true' if value else 'false'
    if type(value) in (int, float):
        if type(value) is float and not math.isfinite(value):
            fail('INVALID_ARTIFACT_NAME', 'filename numbers must be finite')
        return str(value).replace('e+', 'e')
    if not isinstance(value, str):
        fail('INVALID_ARTIFACT_NAME', 'filename values must be scalars or flat lists')
    encoded = ''.join(chr(b) if chr(b).isascii() and (chr(b).isalnum() or b == 45)
                      else f'.x{b:02X}.' for b in value.encode('utf-8'))
    if not encoded:
        return '.empty.'
    # Escape a first byte to preserve strings that otherwise look typed.
    if _NUMBER.fullmatch(encoded) or encoded in ('true', 'false', 'null', 'list'):
        encoded = f'.x{ord(encoded[0]):02X}.' + encoded[1:]
    return encoded


def stem(index, properties, *, worker=None):
    if type(index) is not int or not 0 <= index <= 999999:
        fail('OUTPUT_INDEX_EXHAUSTED', 'the six-digit output range is exhausted')
    prefix = f'{index:06d}'
    if worker is not None:
        if type(worker) is not int or worker < 0:
            fail('INVALID_ARTIFACT_NAME', 'worker must be a nonnegative integer')
        prefix += '.' + str(worker)
    fields = [prefix]
    for key, value in properties.items():
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            fail('INVALID_ARTIFACT_NAME', 'filename keys must be alphanumeric and start with a letter', key)
        if isinstance(value, list):
            value = 'list' + ''.join('_' + scalar(item) for item in value)
        else:
            value = scalar(value)
        fields.append(key + '_' + value)
    result = '__'.join(fields)
    if len(result) > MAX_STEM:
        fail('ARTIFACT_NAME_TOO_LONG', 'descriptive filename exceeds 180 characters; shorten scene or field names')
    return result


class OutputSequence:
    """Exclusive empty reservation files survive crashes; no lock can go stale.

    O_EXCL arbitrates processes/threads. A producer that falls behind retries
    occupied slots, so every successful reservation advances the global order.
    This requires a filesystem that honours exclusive creation, as publication does.
    """
    def __init__(self, root):
        self.root = Path(root)
        self.ledger = self.root / '.output-index'
        if self.ledger.is_symlink():
            fail('INVALID_OUTPUT_PATH', 'output index ledger must not be a symlink', str(self.ledger))
        created = not self.ledger.exists()
        self.ledger.mkdir(exist_ok=True)
        if created and os.name == 'posix':
            root_fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(root_fd)
            finally:
                os.close(root_fd)
        reserved = [int(p.name) for p in self.ledger.iterdir() if re.fullmatch(r'[0-9]{6}', p.name)]
        if not reserved:
            # Legacy resumes have no ledger. Advance beyond retained prefixes
            # without renaming their verified evidence.
            for path in self.root.rglob('*'):
                match = re.match(r'^([0-9]{6})(?:\.[0-9]+)?(?:__|-)', path.name)
                if match:
                    reserved.append(int(match[1]))
        self.next = max(reserved, default=-1) + 1

    def reserve(self):
        while self.next <= 999999:
            index = self.next
            self.next += 1
            try:
                fd = os.open(self.ledger / f'{index:06d}', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                continue
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            if os.name == 'posix':
                directory_fd = os.open(self.ledger, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            return index
        fail('OUTPUT_INDEX_EXHAUSTED', 'the six-digit output range is exhausted')

    def path(self, directory, properties, extension=''):
        # Validate before consuming a number; writing failures still leave a gap.
        stem(0, properties)
        result = Path(directory) / (stem(self.reserve(), properties) + extension)
        if result.exists() or result.is_symlink():
            fail('OUTPUT_EXISTS', 'an indexed artifact already exists', str(result))
        return result
