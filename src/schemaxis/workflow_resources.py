"""Bounded, copied workflow inputs with portable constituent manifests.

This host-only foundation captures regular files; it does not infer dependencies
inside native projects, stop live writers or manage application working directories.
Writers must provide a stable checkpoint. Ordinary concurrent changes are detected
using file identities, metadata and a second inventory; this is not a sandbox
against an adversary concurrently replacing filesystem ancestors.
"""

import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat

from . import storage
from .errors import fail


VERSION = 'schemaxis.resource/1'
_KINDS = {'file', 'file-set', 'directory'}
_CHUNK = 1024 * 1024
_MANIFEST_LIMIT = 16 * 1024 * 1024


def _limits(max_files, max_bytes):
    if type(max_files) is not int or max_files < 1:
        fail('INVALID_RESOURCE', 'max_files must be a positive integer', 'max_files')
    if type(max_bytes) is not int or max_bytes < 0:
        fail('INVALID_RESOURCE', 'max_bytes must be a nonnegative integer', 'max_bytes')


def _path(value, location):
    try:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        if '\x00' in str(path):
            raise ValueError('NUL in path')
        if '..' in path.parts:
            fail('INVALID_RESOURCE', 'source and destination paths must not contain parent traversal', location)
    except (TypeError, ValueError, OSError) as error:
        fail('INVALID_RESOURCE', 'expected a filesystem path: ' + str(error), location)
    _no_links(path)
    # Check supplied ancestors before lexical normalisation. Parent traversal
    # is forbidden above, including nonexistent/../ aliases of existing paths.
    path = Path(os.path.abspath(path))
    _no_links(path)
    return path


def _no_links(path):
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            fail('INVALID_RESOURCE', 'symlinks and symlink ancestors are unsupported', str(part))


def _relative(value, location):
    if (not isinstance(value, str) or not value or len(value) > 4096
            or '\\' in value or '\x00' in value
            or re.match(r'^[A-Za-z]:', value)):
        fail('INVALID_RESOURCE', 'expected a portable relative member path', location)
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or path.as_posix() != value or value == '.':
        fail('INVALID_RESOURCE', 'member paths must be normalised without traversal', location)
    return value


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _regular(path):
    _no_links(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        fail('INVALID_RESOURCE', 'only regular files can be captured', str(path))
    return _signature(info)


def _inventory(source, kind, members, max_files, max_bytes):
    """Return signatures, including the source root for change detection only."""
    files, directories, total = {}, {}, 0

    def add_file(relative, path):
        nonlocal total
        _relative(relative, str(path))
        files[relative] = _regular(path)
        total += files[relative][3]
        if len(files) > max_files or total > max_bytes:
            fail('RESOURCE_LIMIT', 'resource exceeds the declared file or byte limit', str(source),
                 files=len(files), bytes=total, maxFiles=max_files, maxBytes=max_bytes)

    def add_directory(relative, path):
        if relative:
            _relative(relative, str(path))
        _no_links(path)
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode):
            fail('INVALID_RESOURCE', 'expected a directory', str(path))
        directories[relative] = _signature(info)
        # Bound empty directories too, independently of the regular-file count.
        if len(directories) - 1 > max_files:
            fail('RESOURCE_LIMIT', 'resource exceeds the declared directory limit', str(source),
                 maxDirectories=max_files)

    if kind == 'file':
        add_file(source.name, source)
    elif kind == 'file-set':
        add_directory('', source)
        for relative in members:
            for parent in reversed(PurePosixPath(relative).parents):
                if str(parent) != '.' and str(parent) not in directories:
                    add_directory(str(parent), source / str(parent))
            add_file(relative, source / relative)
    else:
        pending = [('', source)]
        while pending:
            relative, directory = pending.pop()
            add_directory(relative, directory)
            with os.scandir(directory) as entries:
                for entry in entries:
                    member = (relative + '/' if relative else '') + entry.name
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        pending.append((member, directory / entry.name))
                        # Avoid an unbounded queue of empty directories.
                        if len(pending) + len(directories) - 1 > max_files:
                            fail('RESOURCE_LIMIT', 'resource exceeds the declared directory limit', str(source))
                    else:
                        add_file(member, directory / entry.name)
    return files, directories


def _open_read(path):
    _no_links(path)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
                         | getattr(os, 'O_NONBLOCK', 0))
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        fail('INVALID_RESOURCE', 'expected a regular file', str(path))
    return os.fdopen(descriptor, 'rb')


def _read_file(source, expected, destination=None):
    """Hash/copy at most the declared size; never stream a growing file forever."""
    digest = hashlib.sha256()
    with _open_read(source) as incoming:
        if _signature(os.fstat(incoming.fileno())) != expected:
            fail('RESOURCE_CHANGED', 'resource changed before reading; capture a stable checkpoint', str(source))
        outgoing = None
        try:
            if destination is not None:
                outgoing = destination.open('xb')
            remaining = expected[3]
            while remaining:
                block = incoming.read(min(_CHUNK, remaining))
                if not block:
                    fail('RESOURCE_CHANGED', 'resource became shorter while reading', str(source))
                remaining -= len(block)
                digest.update(block)
                if outgoing is not None:
                    outgoing.write(block)
            if incoming.read(1) or _signature(os.fstat(incoming.fileno())) != expected:
                fail('RESOURCE_CHANGED', 'resource changed while reading; capture a stable checkpoint', str(source))
            if _signature(source.lstat()) != expected:
                fail('RESOURCE_CHANGED', 'resource was replaced while reading', str(source))
            if outgoing is not None:
                outgoing.flush()
                os.fsync(outgoing.fileno())
        finally:
            if outgoing is not None:
                outgoing.close()
    return digest.hexdigest()


def _sync_directory(path):
    _no_links(path)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0)
                         | getattr(os, 'O_NOFOLLOW', 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def capture(source, destination, *, kind='file', members=None,
            max_files=10000, max_bytes=1073741824):
    """Copy a stable file, explicit file set or directory into a fresh directory.

    ``file-set`` members are unique normalised paths relative to ``source``.
    Other kinds do not accept ``members``. ``max_files`` also independently
    limits subdirectories. A failed copy retains owned partial data but publishes
    no complete resource.json. Existing destinations, including empty ones, are
    never reused. Symlinks (including ancestors) and special files are rejected.
    """
    _limits(max_files, max_bytes)
    if not isinstance(kind, str) or kind not in _KINDS:
        fail('UNSUPPORTED_RESOURCE', 'supported resource kinds are file, file-set and directory', 'kind')
    if kind == 'file-set':
        if not isinstance(members, (list, tuple)) or not members:
            fail('INVALID_RESOURCE', 'file-set requires explicit relative member paths', 'members')
        if len(members) > max_files:
            fail('RESOURCE_LIMIT', 'file-set exceeds the declared file limit', 'members')
        members = [_relative(member, 'members') for member in members]
        if len(set(members)) != len(members):
            fail('INVALID_RESOURCE', 'file-set members must be unique', 'members')
    elif members is not None:
        fail('INVALID_RESOURCE', 'members is supported only for file-set', 'members')
    try:
        source, destination = _path(source, 'source'), _path(destination, 'destination')
        if source == destination or source in destination.parents:
            fail('INVALID_RESOURCE', 'destination must be outside the source', str(destination))
        if destination.exists():
            fail('OUTPUT_EXISTS', 'choose a destination that does not exist', str(destination))
        before = _inventory(source, kind, members, max_files, max_bytes)
        publication_parents = []
        for parent in destination.parents:
            publication_parents.append(parent)
            if parent.exists():
                break
        destination.parent.mkdir(parents=True, exist_ok=True)
        _no_links(destination.parent)
        try:
            destination.mkdir()
        except FileExistsError:
            fail('OUTPUT_EXISTS', 'destination was claimed; choose a fresh destination', str(destination))
        data = destination / 'data'
        data.mkdir()
        directories = sorted(relative for relative in before[1] if relative)
        for relative in directories:
            (data / relative).mkdir(parents=True, exist_ok=True)
        records = []
        for relative, signature in sorted(before[0].items()):
            original = source if kind == 'file' else source / relative
            hashed = _read_file(original, signature, data / relative)
            copied = data / relative
            if _read_file(copied, _regular(copied)) != hashed:
                fail('RESOURCE_MISMATCH', 'copied bytes differ from the input', str(copied))
            records.append({'path': relative, 'size': signature[3], 'sha256': hashed})
        if _inventory(source, kind, members, max_files, max_bytes) != before:
            fail('RESOURCE_CHANGED', 'resource changed during capture; use a stable checkpoint', str(source))
        manifest = {'version': VERSION, 'kind': kind, 'status': 'complete',
                    'files': records, 'directories': directories,
                    'totalBytes': sum(record['size'] for record in records)}
        manifest['digest'] = storage.digest(manifest)
        payload = storage.encoded(manifest)
        if len(payload) > _MANIFEST_LIMIT:
            fail('RESOURCE_LIMIT', 'resource manifest exceeds 16 MiB', str(destination))
        # A durable completion marker must not precede durable constituent
        # directory entries. Synchronise children before their owning parents.
        for relative in sorted(directories, key=lambda name: (-name.count('/'), name)):
            _sync_directory(data / relative)
        for directory in (data, destination, *publication_parents):
            _sync_directory(directory)
        storage.atomic(destination / 'resource.json', payload, exclusive=True)
        return manifest
    except storage.AtomicPublicationError as error:
        # This destination is exclusively owned by this capture. An uncertain
        # durability result must not leave a completion marker for a failed call.
        try:
            (destination / 'resource.json').unlink(missing_ok=True)
        except OSError as cleanup_error:
            fail('RESOURCE_IO', 'manifest publication and removal failed; completion is uncertain: '
                 + str(cleanup_error), str(destination), publicationUncertain=True)
        fail('RESOURCE_IO', 'manifest publication failed; completion marker removed: '
             + str(error), str(destination))
    except OSError as error:
        fail('RESOURCE_IO', 'cannot capture resource: ' + str(error), str(source))


def _manifest(value, max_files, max_bytes):
    expected = {'version', 'kind', 'status', 'files', 'directories', 'totalBytes', 'digest'}
    if not isinstance(value, dict) or set(value) != expected:
        fail('RESOURCE_MISMATCH', 'resource manifest has an invalid structure', 'resource.json')
    if (value['version'] != VERSION or value['status'] != 'complete'
            or not isinstance(value['kind'], str) or value['kind'] not in _KINDS):
        fail('RESOURCE_MISMATCH', 'unsupported or incomplete resource manifest', 'resource.json')
    files, directories = value['files'], value['directories']
    if not isinstance(files, list) or not isinstance(directories, list):
        fail('RESOURCE_MISMATCH', 'files and directories must be arrays', 'resource.json')
    if len(files) > max_files or len(directories) > max_files:
        fail('RESOURCE_LIMIT', 'manifest exceeds the declared file or directory limit', 'resource.json')
    names, total = [], 0
    for record in files:
        if not isinstance(record, dict) or set(record) != {'path', 'size', 'sha256'}:
            fail('RESOURCE_MISMATCH', 'invalid file record', 'resource.json/files')
        names.append(_relative(record['path'], 'resource.json/files/path'))
        if type(record['size']) is not int or record['size'] < 0:
            fail('RESOURCE_MISMATCH', 'file size must be a nonnegative integer', record['path'])
        if not isinstance(record['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', record['sha256']):
            fail('RESOURCE_MISMATCH', 'invalid SHA-256 digest', record['path'])
        total += record['size']
    for directory in directories:
        _relative(directory, 'resource.json/directories')
    if names != sorted(set(names)) or directories != sorted(set(directories)):
        fail('RESOURCE_MISMATCH', 'manifest members must be sorted and unique', 'resource.json')
    if set(names) & set(directories):
        fail('RESOURCE_MISMATCH', 'a member cannot be both file and directory', 'resource.json')
    parents = {str(parent) for name in names + directories
               for parent in PurePosixPath(name).parents if str(parent) != '.'}
    if not parents.issubset(directories):
        fail('RESOURCE_MISMATCH', 'manifest omits a parent directory', 'resource.json')
    if value['kind'] == 'file' and (len(files) != 1 or directories or '/' in names[0]):
        fail('RESOURCE_MISMATCH', 'file capture requires one top-level file', 'resource.json')
    if value['kind'] == 'file-set' and (not files or set(directories) != parents):
        fail('RESOURCE_MISMATCH', 'file-set must contain files and their parent directories', 'resource.json')
    if type(value['totalBytes']) is not int or value['totalBytes'] != total:
        fail('RESOURCE_MISMATCH', 'totalBytes does not match constituent sizes', 'resource.json')
    if total > max_bytes:
        fail('RESOURCE_LIMIT', 'manifest exceeds the declared byte limit', 'resource.json')
    unsigned = {key: item for key, item in value.items() if key != 'digest'}
    if value['digest'] != storage.digest(unsigned):
        fail('RESOURCE_MISMATCH', 'resource manifest digest does not match', 'resource.json/digest')
    return value


def verify(destination, *, max_files=10000, max_bytes=1073741824):
    """Verify an exact captured tree and return its manifest without source access.

    The digest detects accidental changes; it is not a signature or independent
    attestation. Callers must separately pin a trusted manifest digest when needed.
    """
    _limits(max_files, max_bytes)
    try:
        destination = _path(destination, 'destination')
        if not destination.is_dir():
            fail('RESOURCE_MISMATCH', 'capture directory is missing', str(destination))
        if {entry.name for entry in destination.iterdir()} != {'data', 'resource.json'}:
            fail('RESOURCE_MISMATCH', 'capture is incomplete or has unexpected members', str(destination))
        manifest_path = destination / 'resource.json'
        manifest_signature = _regular(manifest_path)
        if manifest_signature[3] > _MANIFEST_LIMIT:
            fail('RESOURCE_LIMIT', 'resource manifest exceeds 16 MiB', str(manifest_path))
        with _open_read(manifest_path) as incoming:
            payload = incoming.read(_MANIFEST_LIMIT + 1)
            if len(payload) > _MANIFEST_LIMIT:
                fail('RESOURCE_LIMIT', 'resource manifest exceeds 16 MiB', str(manifest_path))
            if _signature(os.fstat(incoming.fileno())) != manifest_signature:
                fail('RESOURCE_CHANGED', 'manifest changed while reading', str(manifest_path))
        try:
            manifest = _manifest(storage.load(payload.decode('utf-8')), max_files, max_bytes)
        except UnicodeError:
            fail('RESOURCE_MISMATCH', 'manifest must be UTF-8 JSON', str(manifest_path))
        except RecursionError:
            fail('RESOURCE_MISMATCH', 'manifest JSON exceeds supported nesting depth', str(manifest_path))
        data = destination / 'data'
        before = _inventory(data, 'directory', None, max_files, max_bytes)
        expected_files = {record['path']: record for record in manifest['files']}
        if set(before[0]) != set(expected_files) or sorted(name for name in before[1] if name) != manifest['directories']:
            fail('RESOURCE_MISMATCH', 'captured tree differs from its manifest', str(data))
        for name, signature in before[0].items():
            expected = expected_files[name]
            if signature[3] != expected['size'] or _read_file(data / name, signature) != expected['sha256']:
                fail('RESOURCE_MISMATCH', 'captured file differs from its manifest', str(data / name))
        if _inventory(data, 'directory', None, max_files, max_bytes) != before:
            fail('RESOURCE_CHANGED', 'captured tree changed during verification', str(data))
        if _regular(manifest_path) != manifest_signature:
            fail('RESOURCE_CHANGED', 'manifest changed during verification', str(manifest_path))
        if {entry.name for entry in destination.iterdir()} != {'data', 'resource.json'}:
            fail('RESOURCE_CHANGED', 'capture members changed during verification', str(destination))
        return manifest
    except OSError as error:
        fail('RESOURCE_IO', 'cannot verify resource: ' + str(error), str(destination))
