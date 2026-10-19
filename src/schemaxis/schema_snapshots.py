"""Portable, immutable captures of standalone document schemas.

The manifest is an evidence reference, not a JSON Schema $ref. Schema bytes and
all their internal references are retained unchanged. No native app is loaded.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from .errors import fail

PROTOCOL = 'schemaxis.schema-snapshot/1'


def _invalid(message, location):
    fail('INVALID_SCHEMA_SNAPSHOT', message, str(location))


def _nonfinite(value):
    raise ValueError('non-finite constant ' + value)


def _document(payload, version, location):
    try:
        schema = json.loads(payload.decode('utf-8'), parse_constant=_nonfinite)
    except (UnicodeError, ValueError) as error:
        _invalid('schema is not finite UTF-8 JSON: ' + str(error), location)
    properties = schema.get('properties') if isinstance(schema, dict) else None
    selector = properties.get('version') if isinstance(properties, dict) else None
    if not isinstance(selector, dict) or selector.get('const') != version:
        _invalid('schema must declare its exact document version', location)
    return schema


def _publish(path, payload):
    """Publish complete bytes once; concurrent identical writers are idempotent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.' + path.name + '.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            # Linking within the same directory publishes atomically without
            # replacing earlier evidence. The temporary link is removed below.
            os.link(temporary, path)
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != payload:
                fail('SCHEMA_SNAPSHOT_EXISTS', 'existing evidence differs; choose a new capture name or repair the store', str(path))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def store(directory, name, payload, *, provider, document_version, authored):
    """Retain exact UTF-8 schema bytes once and publish a small named manifest.

    Copy the directory (manifests and schemas/) to move evidence. Names cannot
    replace a different earlier capture; content hashes identify schema versions.
    """
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name):
        _invalid('capture name must be a simple filename stem', 'name')
    if (not isinstance(provider, str) or not provider or not isinstance(document_version, str)
            or not document_version or type(authored) is not bool or not isinstance(payload, bytes)):
        _invalid('provider, document version, authored flag and schema bytes are required', name)
    _document(payload, document_version, name)
    directory = Path(directory)
    if (directory/'schemas').is_symlink():
        _invalid('schemas directory must belong to the portable store', directory)
    sha256 = hashlib.sha256(payload).hexdigest()
    reference = 'schemas/' + sha256 + '.json'
    manifest = {'version': PROTOCOL, 'provider': provider, 'documentVersion': document_version,
                'authored': authored, 'schema': reference, 'sha256': sha256, 'bytes': len(payload)}
    _publish(directory/reference, payload)
    path = directory/(name + '.snapshot.json')
    _publish(path, (json.dumps(manifest, indent=2, allow_nan=False) + '\n').encode('utf-8'))
    return path


def read(path):
    """Verify a manifest and return its exact schema bytes without regenerating."""
    path = Path(path)
    try:
        manifest = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(manifest, dict) and manifest.get('version') == 'schemaxis.schema-snapshot/2':
            from .schema_store import read_shared
            return read_shared(path)
        if (not isinstance(manifest, dict) or set(manifest) != {'version', 'provider', 'documentVersion', 'authored', 'schema', 'sha256', 'bytes'}
                or manifest['version'] != PROTOCOL or not isinstance(manifest['sha256'], str)
                or not re.fullmatch('[0-9a-f]{64}', manifest['sha256'])
                or manifest['schema'] != 'schemas/' + manifest['sha256'] + '.json'
                or type(manifest['authored']) is not bool or type(manifest['bytes']) is not int or manifest['bytes'] < 0
                or any(not isinstance(manifest[k], str) or not manifest[k] for k in ('provider', 'documentVersion'))):
            _invalid('malformed schema snapshot manifest', path)
        target = path.parent/manifest['schema']
        if target.is_symlink() or not target.resolve().is_relative_to(path.parent.resolve()):
            _invalid('schema reference escapes the portable store', path)
        payload = target.read_bytes()
    except (OSError, UnicodeError, ValueError) as error:
        _invalid('schema snapshot is missing or unreadable: ' + str(error), path)
    if len(payload) != manifest['bytes'] or hashlib.sha256(payload).hexdigest() != manifest['sha256']:
        _invalid('schema content hash or byte count differs', path)
    _document(payload, manifest['documentVersion'], path)
    return payload


def capture(directory, name, *, provider='paraview', version=None, authored=True):
    """Capture current declarations explicitly; extension/registry changes are fresh."""
    from .adaptors import registry
    from .schema import export_schema
    if version is None:
        version = registry.metadata(provider)['version']
    if version == 'schemaxis.workflow/1':
        provider = 'workflow'
    else:
        provider, _ = registry.resolve({'version': version})
    schema = export_schema(provider if provider != 'workflow' else None, version=version, authored=authored)
    payload = (json.dumps(schema, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n').encode('utf-8')
    return store(directory, name, payload, provider=provider, document_version=version, authored=authored)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    writer = commands.add_parser('capture', help='capture current declarations or exact bytes of an existing schema')
    writer.add_argument('directory', type=Path)
    writer.add_argument('--name', required=True)
    writer.add_argument('--provider', default='paraview')
    writer.add_argument('--version')
    writer.add_argument('--expanded', action='store_true')
    writer.add_argument('--input', type=Path, help='retain existing schema bytes; requires --version and an accurate flavour')
    reader = commands.add_parser('read', help='verify and emit retained schema bytes')
    reader.add_argument('manifest', type=Path)
    args = parser.parse_args(argv)
    if args.action == 'read':
        sys.stdout.buffer.write(read(args.manifest))
        return
    if args.input:
        if args.version is None:
            parser.error('--input requires --version')
        path = store(args.directory, args.name, args.input.read_bytes(), provider=args.provider,
                     document_version=args.version, authored=not args.expanded)
    else:
        path = capture(args.directory, args.name, provider=args.provider, version=args.version, authored=not args.expanded)
    print(path)


# Shared runtime storage extends the original exact-byte capture interface.
def capture_run(directory, document, *, workspace_root=None, schema_settings=None):
    from .schema_store import capture_run as shared_capture
    return shared_capture(directory, document, workspace_root=workspace_root, schema_settings=schema_settings)


def store_shared(root, manifest_path, payload, **metadata):
    from .schema_store import store_shared as shared_store
    return shared_store(root, manifest_path, payload, **metadata)


def verify_run(directory):
    from .schema_store import verify_run as shared_verify
    return shared_verify(directory)


def export_run(source, destination):
    from .schema_store import export_run as shared_export
    return shared_export(source, destination)


def inspect(root):
    from .schema_store import inspect as shared_inspect
    return shared_inspect(root)


def rebuild_index(root):
    from .schema_store import rebuild_index as shared_rebuild
    return shared_rebuild(root)


if __name__ == '__main__':
    main()
