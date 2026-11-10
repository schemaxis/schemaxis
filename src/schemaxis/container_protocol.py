"""Bounded trusted-worker framing and regular-file-only evidence archives."""
import hashlib
import io
import os
import posixpath
import re
from pathlib import Path, PurePosixPath
import stat
import struct
import tarfile

from .storage import encoded, load
from .observations import fail

HEADER_LIMIT = 2 * 1024 * 1024


def archive_limit(disk_bytes, inodes):
    return disk_bytes + inodes * 2048 + 16384


def frame(header, archive=b''):
    data = encoded(header)
    if len(data) > HEADER_LIMIT:
        fail('ISOLATION_PROTOCOL_ERROR', 'worker control envelope exceeds its bound')
    return struct.pack('!QQ', len(data), len(archive)) + data + archive


def unframe(data, maximum):
    if len(data) < 16:
        fail('ISOLATION_PROTOCOL_ERROR', 'worker response is incomplete')
    header, payload = struct.unpack('!QQ', data[:16])
    if header > HEADER_LIMIT or payload > maximum or len(data) != 16 + header + payload:
        fail('ISOLATION_PROTOCOL_ERROR', 'worker envelope size differs or exceeds its bound')
    value = load(data[16:16+header].decode('utf-8'))
    if not isinstance(value, dict):
        fail('ISOLATION_PROTOCOL_ERROR', 'worker envelope must be an object')
    return value, data[16+header:]


def read_frame(stream, maximum):
    def exact(length):
        output = bytearray()
        while len(output) < length:
            chunk = stream.read(min(65536, length-len(output)))
            if not chunk:
                fail('ISOLATION_PROTOCOL_ERROR', 'worker input ended early')
            output.extend(chunk)
        return bytes(output)
    prefix = exact(16)
    header, payload = struct.unpack('!QQ', prefix)
    if header > HEADER_LIMIT or payload > maximum:
        fail('ISOLATION_PROTOCOL_ERROR', 'worker input exceeds its bound')
    return unframe(prefix + exact(header+payload), maximum)


def pack_tree(root, disk_bytes, inodes):
    root = Path(root)
    if not root.exists():
        return b'', {}
    records, total, count = {}, 0, 0
    manifests = []
    output = io.BytesIO()
    def paths():
        yield root
        stack = [os.scandir(root)]
        try:
            while stack:
                entry = next(stack[-1], None)
                if entry is None:
                    stack.pop().close()
                    continue
                path = Path(entry.path)
                yield path
                if entry.name == 'schema.snapshot.json' and entry.is_file(follow_symlinks=False):
                    manifests.append(path)
                if entry.is_dir(follow_symlinks=False):
                    if len(stack) >= 64:
                        fail('ISOLATION_EXPORT_REFUSED', 'evidence directory nesting exceeds its bound')
                    stack.append(os.scandir(path))
        finally:
            for iterator in stack:
                iterator.close()
    def evidence_paths():
        yield from paths()
        dependencies = set()
        from .schema_snapshots import read
        for manifest in manifests:
            metadata = load(manifest.read_text(encoding='utf-8'))
            if isinstance(metadata, dict) and metadata.get('version') == 'schemaxis.schema-snapshot/2':
                # Pure retained-byte validation; no adaptor/native hooks. Only
                # this owned job's parent may supply an external dependency.
                shared = manifest.parent / metadata.get('root', '')
                shared = shared.resolve()
                if shared != root.parent.resolve() and not shared.is_relative_to(root.resolve()):
                    fail('ISOLATION_EXPORT_REFUSED', 'schema dependency escaped its owned job')
                read(manifest)
                if shared == root.parent.resolve():
                    dependencies.add(shared / metadata['schema'])
        if dependencies:
            yield root.parent / 'schemas'
            yield from sorted(dependencies)

    with tarfile.open(fileobj=output, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for path in evidence_paths():
            count += 1
            info = path.lstat()
            if (count > inodes or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
                    or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)):
                fail('ISOLATION_EXPORT_REFUSED', 'evidence contains special files or too many entries')
            relative = path.relative_to(root.parent)
            entry = tarfile.TarInfo(relative.as_posix())
            entry.mode = 0o750 if stat.S_ISDIR(info.st_mode) else 0o640
            if stat.S_ISDIR(info.st_mode):
                entry.type = tarfile.DIRTYPE
                archive.addfile(entry)
            else:
                total += info.st_size
                if total > disk_bytes:
                    fail('ISOLATION_LIMIT_EXCEEDED', 'evidence exceeds disk byte bound', limit='disk')
                with path.open('rb') as stream:
                    data = stream.read(disk_bytes+1)
                if len(data) != info.st_size:
                    fail('ISOLATION_EXPORT_REFUSED', 'evidence changed during export')
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
                records[relative.as_posix()] = hashlib.sha256(data).hexdigest()
    data = output.getvalue()
    if len(data) > archive_limit(disk_bytes, inodes):
        fail('ISOLATION_LIMIT_EXCEEDED', 'evidence archive exceeds its bound', limit='archive')
    return data, records


def unpack_tree(data, parent, disk_bytes, inodes, *, validate_only=False):
    parent = Path(parent)
    if len(data) > archive_limit(disk_bytes, inodes):
        fail('ISOLATION_EXPORT_REFUSED', 'evidence archive exceeds its bound')
    # Validate the complete hostile archive before creating any host file.
    records, seen, total, manifests = {}, {}, 0, {}
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as archive:
        for entry in archive:
            parts = PurePosixPath(entry.name).parts
            if (not parts or len(parts) > 65 or parts[0] not in ('run', 'schemas') or PurePosixPath(entry.name).is_absolute()
                    or '..' in parts or '\\' in entry.name or '\x00' in entry.name
                    or entry.name.rstrip('/') != PurePosixPath(entry.name).as_posix()
                    or entry.name.rstrip('/') in seen or len(seen) >= inodes
                    or not (entry.isdir() or entry.isfile()) or entry.size < 0
                    or (entry.isdir() and entry.size != 0)):
                fail('ISOLATION_EXPORT_REFUSED', 'evidence archive has an unsafe member')
            if parts[0] == 'schemas' and not (
                    len(parts) == 1 and entry.isdir() or len(parts) == 2 and entry.isfile()
                    and re.fullmatch(r'[0-9a-f]{64}\.json', parts[1])):
                fail('ISOLATION_EXPORT_REFUSED', 'schema export is not an immutable content object')
            seen[entry.name.rstrip('/')] = entry.isdir()
            if entry.isdir():
                continue
            total += entry.size
            if total > disk_bytes:
                fail('ISOLATION_LIMIT_EXCEEDED', 'evidence exceeds disk byte bound', limit='disk')
            stream = archive.extractfile(entry)
            checksum = hashlib.sha256()
            remaining = entry.size
            manifest_bytes = bytearray() if parts[-1] == 'schema.snapshot.json' else None
            while remaining:
                block = stream.read(min(65536, remaining))
                if not block:
                    fail('ISOLATION_EXPORT_REFUSED', 'truncated evidence member')
                checksum.update(block)
                if manifest_bytes is not None:
                    manifest_bytes.extend(block)
                remaining -= len(block)
            if manifest_bytes is not None:
                manifests[entry.name] = load(bytes(manifest_bytes).decode('utf-8'))
            checksum = checksum.hexdigest()
            if parts[0] == 'schemas' and checksum != parts[1][:-5]:
                fail('ISOLATION_EXPORT_REFUSED', 'schema object digest differs from its name')
            records[PurePosixPath(*parts).as_posix()] = checksum
    dependencies = set()
    for name, metadata in manifests.items():
        if isinstance(metadata, dict) and metadata.get('version') == 'schemaxis.schema-snapshot/2':
            reference = metadata.get('root')
            identity = metadata.get('sha256')
            if (not isinstance(reference, str) or not re.fullmatch(r'\.|\.\.(?:/\.\.)*', reference)
                    or not isinstance(identity, str) or not re.fullmatch('[0-9a-f]{64}', identity)
                    or metadata.get('schema') != 'schemas/'+identity+'.json'):
                fail('ISOLATION_EXPORT_REFUSED', 'schema reference is malformed')
            shared = posixpath.normpath(posixpath.join(posixpath.dirname(name), reference))
            if shared == '.':
                dependencies.add('schemas/'+identity+'.json')
            elif shared != 'run' and not shared.startswith('run/'):
                fail('ISOLATION_EXPORT_REFUSED', 'schema reference escaped its owned job')
    exported = {name for name in seen if name.startswith('schemas/')}
    if exported != dependencies or bool(dependencies) != ('schemas' in seen):
        fail('ISOLATION_EXPORT_REFUSED', 'schema objects differ from the retained dependency closure')
    for name in seen:
        for ancestor in PurePosixPath(name).parents:
            if str(ancestor) == '.':
                break
            if seen.get(str(ancestor)) is not True:
                fail('ISOLATION_EXPORT_REFUSED', 'evidence archive omitted or conflicted with a directory ancestor')
    if data and seen.get('run') is not True:
        fail('ISOLATION_EXPORT_REFUSED', 'evidence archive omitted its run directory')
    if validate_only:
        return records
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as archive:
        for entry in archive:
            path = parent.joinpath(*PurePosixPath(entry.name).parts)
            if entry.isdir():
                path.mkdir(parents=True, exist_ok=True, mode=0o750)
            else:
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
                with path.open('xb') as target:
                    stream = archive.extractfile(entry)
                    while block := stream.read(65536):
                        target.write(block)
                path.chmod(0o640)
    return records
