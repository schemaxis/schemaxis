# Copyright (C) 2026 David L F Gaden
"""Workspace-owned schema objects and portable run dependencies (host-only).

Content is canonical finite JSON. Provenance is descriptive, not part of content
identity. The index is repairable metadata, never an authority for safe deletion.
"""
from contextlib import contextmanager
import hashlib
from importlib.metadata import PackageNotFoundError, version as package_version
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time

from .errors import fail
from .storage import atomic
from .schema_snapshots import _document, _invalid, _publish

PROTOCOL = 'schemaxis.schema-snapshot/2'
INDEX_PROTOCOL = 'schemaxis.schema-index/1'
CANONICALISATION = 'python-json-sort-keys-utf8/1'
_HASH = re.compile(r'[0-9a-f]{64}')


def _json(payload, location):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key: ' + key)
            result[key] = value
        return result
    def constant(value):
        raise ValueError('non-finite JSON constant: ' + value)
    try:
        result = json.loads(payload, object_pairs_hook=pairs, parse_constant=constant)
        canonical(result)
        return result
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as error:
        _invalid('invalid finite JSON: ' + str(error), location)


def canonical(value):
    """Deterministic object-key order; arrays, numbers and annotations retained.

    This deliberately does not equate 1 with 1.0 or reorder schema arrays. It is
    not RFC 8785 and makes no cross-language floating-point canonicalisation claim.
    """
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                       separators=(',', ':')) + '\n').encode('utf-8')


def _standalone(schema, location):
    """Refuse unresolved external schema dependencies without reading annotations.

    Stored schemas are whole documents. Multi-file schemas use their existing
    explicit bundle format; silently retaining only one bundle file is unsafe.
    """
    maps = ('properties', '$defs', 'definitions', 'patternProperties', 'dependentSchemas')
    singles = ('items', 'additionalProperties', 'unevaluatedProperties', 'unevaluatedItems',
               'additionalItems', 'contains', 'propertyNames', 'not', 'if', 'then', 'else')
    arrays = ('oneOf', 'anyOf', 'allOf', 'prefixItems')
    def visit(node):
        if not isinstance(node, dict):
            return
        for keyword in ('$ref', '$dynamicRef', '$recursiveRef'):
            if keyword in node and (not isinstance(node[keyword], str) or not node[keyword].startswith('#')):
                _invalid('shared captures require standalone schemas with internal references; retain external bundles separately', location)
        for keyword in maps:
            value = node.get(keyword, {})
            if not isinstance(value, dict):
                _invalid('malformed schema map: ' + keyword, location)
            for child in value.values():
                visit(child)
        for keyword in singles:
            value = node.get(keyword)
            if isinstance(value, list):  # older JSON Schema tuple syntax
                for child in value:
                    visit(child)
            else:
                visit(value)
        for keyword in arrays:
            value = node.get(keyword, [])
            if not isinstance(value, list):
                _invalid('malformed schema array: ' + keyword, location)
            for child in value:
                visit(child)
        dependencies = node.get('dependencies', {})
        if not isinstance(dependencies, dict):
            _invalid('malformed schema dependencies', location)
        for child in dependencies.values():
            visit(child)
    try:
        visit(schema)
    except RecursionError:
        _invalid('schema keyword nesting exceeds the supported depth', location)


def _safe_path(path):
    path = Path(path).expanduser().absolute()
    # Reject every existing symlink component, including a missing leaf under a
    # symlinked directory. Relative evidence must never change owner this way.
    if any(part.is_symlink() for part in (path, *path.parents)):
        _invalid('schema storage paths must not traverse symlinks', path)
    return Path(os.path.abspath(path))


@contextmanager
def _locked(root):
    import fcntl
    root = _safe_path(root)
    directory = _safe_path(root/'schemas')
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = _safe_path(directory/'.lock')
    # O_NOFOLLOW closes the final-component symlink race on supported POSIX.
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(descriptor, 'a') as stream:
        deadline = time.monotonic() + 10
        while True:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    fail('SCHEMA_STORAGE_BUSY', 'another writer holds the shared schema store; retry later', str(root))
                time.sleep(0.01)
        try:
            yield directory
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _empty_index():
    return {'version': INDEX_PROTOCOL, 'canonicalisation': CANONICALISATION, 'objects': {}}


def _index(root):
    path = _safe_path(root/'schemas/index.json')
    if not path.exists():
        if any(path.parent.glob('[0-9a-f]' * 64 + '.json')):
            _invalid('schema index is missing; inspect dependencies then use rebuild_index', path)
        return _empty_index()
    value = _json(path.read_bytes(), path)
    if (not isinstance(value, dict) or set(value) != {'version', 'canonicalisation', 'objects'}
            or value['version'] != INDEX_PROTOCOL or value['canonicalisation'] != CANONICALISATION
            or not isinstance(value['objects'], dict)):
        _invalid('invalid schema index; inspect dependencies then use rebuild_index', path)
    for identity, record in value['objects'].items():
        if (not _HASH.fullmatch(identity) or not isinstance(record, dict)
                or set(record) != {'bytes', 'provenance'} or type(record['bytes']) is not int
                or record['bytes'] < 0 or not isinstance(record['provenance'], list)
                or any(not isinstance(item, dict) for item in record['provenance'])):
            _invalid('invalid schema index record; use rebuild_index', path)
    return value


def _record(index, manifest):
    record = index['objects'].setdefault(manifest['sha256'], {'bytes': manifest['bytes'], 'provenance': []})
    if record['bytes'] != manifest['bytes']:
        _invalid('index byte count conflicts with retained object; use rebuild_index', manifest['sha256'])
    provenance = {key: manifest[key] for key in ('provider', 'documentVersion', 'authored', 'provenance')}
    if provenance not in record['provenance']:
        record['provenance'].append(provenance)
        record['provenance'].sort(key=lambda item: canonical(item))


def store_shared(root, manifest_path, payload, *, provider, document_version, authored=True, provenance=None):
    """Publish immutable canonical schema and a workspace-relative run reference.

    root must be an ancestor of the manifest. The content object has no run owner.
    A failed publication may leave an unreferenced object; it never rewrites an
    earlier manifest or corrupt object. No automatic repair or deletion occurs.
    """
    root, manifest_path = _safe_path(root), _safe_path(manifest_path)
    if not manifest_path.is_relative_to(root) or manifest_path.is_relative_to(root/'schemas'):
        _invalid('manifest must live under its workspace root outside schemas/', manifest_path)
    if (not isinstance(provider, str) or not provider or not isinstance(document_version, str)
            or not document_version or type(authored) is not bool or not isinstance(payload, bytes)
            or provenance is not None and not isinstance(provenance, dict)):
        _invalid('provider, document version, authored flag, bytes and object provenance are required', manifest_path)
    schema = _json(payload, manifest_path)
    _standalone(schema, manifest_path)
    payload = canonical(schema)
    _document(payload, document_version, manifest_path)
    identity = hashlib.sha256(payload).hexdigest()
    try:
        provenance = _json(canonical(provenance or {}), manifest_path)
    except (TypeError, ValueError, UnicodeError, OverflowError) as error:
        _invalid('provenance must be finite JSON: ' + str(error), manifest_path)
    manifest = {'version': PROTOCOL, 'provider': provider, 'documentVersion': document_version,
                'authored': authored, 'root': os.path.relpath(root, manifest_path.parent).replace(os.sep, '/'),
                'schema': 'schemas/' + identity + '.json', 'sha256': identity, 'bytes': len(payload),
                'canonicalisation': CANONICALISATION, 'provenance': provenance}
    try:
        with _locked(root):
            index = _index(root)
            _publish(_safe_path(root/manifest['schema']), payload)
            # A published reference must never precede its object. Index may be
            # ahead of references after interruption; counts are not GC evidence.
            _record(index, manifest)
            atomic(root/'schemas/index.json', canonical(index))
            _publish(manifest_path, canonical(manifest))
    except OSError as error:
        fail('SCHEMA_STORAGE_ERROR', 'schema publication failed; inspect retained files before retrying: ' + str(error), str(manifest_path))
    return manifest_path


def _manifest(path):
    path = _safe_path(path)
    manifest = _json(path.read_bytes(), path)
    expected = {'version', 'provider', 'documentVersion', 'authored', 'root', 'schema',
                'sha256', 'bytes', 'canonicalisation', 'provenance'}
    if (not isinstance(manifest, dict) or set(manifest) != expected or manifest['version'] != PROTOCOL
            or manifest['canonicalisation'] != CANONICALISATION
            or not isinstance(manifest['sha256'], str) or not _HASH.fullmatch(manifest['sha256'])
            or manifest['schema'] != 'schemas/' + manifest['sha256'] + '.json'
            or type(manifest['bytes']) is not int or manifest['bytes'] < 0
            or type(manifest['authored']) is not bool or not isinstance(manifest['provenance'], dict)
            or any(not isinstance(manifest[key], str) or not manifest[key] for key in ('provider', 'documentVersion'))
            or not isinstance(manifest['root'], str) or not re.fullmatch(r'\.|\.\.(?:/\.\.)*', manifest['root'])):
        _invalid('malformed shared schema reference', path)
    root = _safe_path((path.parent/manifest['root']).resolve())
    if not path.is_relative_to(root) or path.is_relative_to(root/'schemas'):
        _invalid('schema reference does not identify an ancestor workspace', path)
    return manifest, root


def read_shared(path):
    try:
        manifest, root = _manifest(path)
        target = _safe_path(root/manifest['schema'])
        payload = target.read_bytes()
        if len(payload) != manifest['bytes'] or hashlib.sha256(payload).hexdigest() != manifest['sha256']:
            _invalid('schema content hash or byte count differs', path)
        schema = _json(payload, target)
        _standalone(schema, target)
        if canonical(schema) != payload:
            _invalid('shared schema does not use the declared canonicalisation', target)
        _document(payload, manifest['documentVersion'], path)
        return payload
    except OSError as error:
        _invalid('shared schema is missing or unreadable; restore the retained dependency: ' + str(error), path)


def _default_root(directory):
    """Sibling standalone outputs share their parent; nested runs share the outer owner.

    Authored workflow envelopes and common-study receipts identify enclosing outputs. This
    works across worker processes without a process-global environment override.
    Explicit root selection in capture_run takes precedence.
    """
    directory = _safe_path(directory)
    owner = directory
    for parent in directory.parents:
        authored, receipt = parent/'authored.json', parent/'result.json'
        if not authored.is_file() or authored.is_symlink():
            continue
        try:
            document = json.loads(authored.read_text(encoding='utf-8'))
            result = json.loads(receipt.read_text(encoding='utf-8')) if receipt.is_file() and not receipt.is_symlink() else {}
        except (OSError, ValueError, RecursionError):
            continue
        if (isinstance(document, dict) and document.get('version') == 'schemaxis.workflow/1'
                or isinstance(result, dict) and result.get('protocol') == 'schemaxis.adaptor-execution/1'):
            owner = parent
    return owner.parent


def capture_run(directory, document, *, workspace_root=None, schema_settings=None):
    """Capture the routed authored contract, without invoking a native application.

    Legacy unversioned documents have no exact document-schema discriminator;
    return None for them instead of manufacturing a misleading contract.
    schema_settings records explicitly supplied schema-generation configuration,
    not arbitrary case parameters or unverified application version claims.
    """
    if not isinstance(document, dict) or 'version' not in document:
        return None
    if schema_settings is not None and not isinstance(schema_settings, dict):
        _invalid('schema_settings must be an object describing generation configuration', directory)
    from .adaptors import registry
    from .schema import export_schema
    version = document['version']
    if version == 'schemaxis.workflow/1':
        provider, route, metadata = 'workflow', {}, {}
    else:
        provider, route = registry.resolve(document)
        if not route.get('schema'):
            # Legacy dynamic console providers may expose planning alone.
            return None
        metadata = registry.metadata(provider)
    schema = export_schema(None if provider == 'workflow' else provider, version=version, authored=True)
    try:
        generator_version = package_version('schemaxis')
    except PackageNotFoundError:
        generator_version = None
    provenance = {'generator': {'name': 'schemaxis.schema', 'version': generator_version},
                  'adaptor': {'source': metadata.get('source', 'builtin'), 'package': metadata.get('package'),
                              'schemaBinding': route.get('schema')},
                  'application': {'runtimeFamily': metadata.get('runtimeFamily'), 'actualVersion': None},
                  'schemaSettings': schema_settings or {}}
    directory = _safe_path(directory)
    root = _default_root(directory) if workspace_root is None else _safe_path(workspace_root)
    return store_shared(root, directory/'schema.snapshot.json', canonical(schema), provider=provider,
                        document_version=version, provenance=provenance)


def verify_run(directory):
    """Check a retained run dependency when present; accept older runs without one."""
    from .schema_snapshots import read
    path = Path(directory)/'schema.snapshot.json'
    if path.exists() or path.is_symlink():
        read(path)
        manifest = _json(path.read_bytes(), path)
        authored = Path(directory)/'authored.json'
        if authored.exists():
            document = _json(authored.read_bytes(), authored)
            if not isinstance(document, dict) or document.get('version') != manifest['documentVersion']:
                _invalid('retained input version differs from its schema reference', path)
            # Check identity if this host already loaded the registry. Missing
            # plugins remain readable offline; no schema is ever regenerated.
            registry = sys.modules.get('schemaxis.adaptors.registry')
            route = registry.routes().get(document['version']) if registry else None
            provider = 'workflow' if document['version'] == 'schemaxis.workflow/1' else route[0] if route else None
            if provider is not None and manifest['provider'] != provider:
                _invalid('retained schema provider differs from its registered input route', path)


def _references(root):
    # Do not follow symlink directories. Report them so callers cannot infer that
    # unseen external references are absent.
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs:
            path = Path(directory)/name
            if path.is_symlink():
                yield path, 'symlink'
        for name in files:
            if name.endswith('.snapshot.json'):
                yield Path(directory)/name, 'manifest'


def inspect(root):
    """Conservative bounded-root inventory. No record is labelled safe to delete."""
    from .schema_snapshots import read
    root = _safe_path(root)
    result = {'root': str(root), 'objects': [], 'references': [], 'faults': [],
              'protectedPaths': [str(root/'schemas')], 'usageComplete': False,
              'deletionPolicy': 'retain shared stores; this scan cannot prove absence of external references'}
    if not root.is_dir():
        _invalid('workspace root is missing or is not a directory', root)
    try:
        if (root/'schemas').is_dir() and not (root/'schemas/index.json').exists() and any((root/'schemas').glob('*.json')):
            _invalid('schema index is missing; reads remain available, use rebuild_index for metadata', root/'schemas/index.json')
        _index(root)
    except Exception as error:
        result['faults'].append({'path': 'schemas/index.json', 'message': str(error)})
    for path, kind in _references(root):
        relative = path.relative_to(root).as_posix()
        if kind == 'symlink':
            result['faults'].append({'path': relative, 'message': 'symlink subtree was not scanned'})
            continue
        try:
            payload = read(path)
            manifest = _json(path.read_bytes(), path)
            result['references'].append({'path': relative, 'sha256': manifest['sha256'], 'bytes': len(payload), 'status': 'verified'})
            if manifest['version'] == PROTOCOL:
                _, owner = _manifest(path)
            else:
                owner = path.parent
            protected = str(owner/'schemas')
            if protected not in result['protectedPaths']:
                result['protectedPaths'].append(protected)
        except Exception as error:
            result['faults'].append({'path': relative, 'message': str(error)})
    directory = root/'schemas'
    if directory.is_symlink():
        result['faults'].append({'path': 'schemas', 'message': 'symlink store was not scanned'})
    elif directory.is_dir():
        for path in sorted(directory.glob('*.json')):
            if path.name == 'index.json':
                continue
            try:
                if not _HASH.fullmatch(path.stem):
                    _invalid('unrecognised schema object name', path)
                _safe_path(path)
                payload = path.read_bytes()
                if hashlib.sha256(payload).hexdigest() != path.stem:
                    _invalid('schema object hash differs', path)
                _json(payload, path)
                result['objects'].append({'sha256': path.stem, 'bytes': len(payload), 'status': 'verified'})
            except Exception as error:
                result['faults'].append({'path': path.relative_to(root).as_posix(), 'message': str(error)})
    return result


def rebuild_index(root):
    """Explicit non-destructive repair; refuse corrupt objects/references.

    Unreferenced complete objects retain unknown provenance. The index is not a
    reference count and is never sufficient to authorise garbage collection.
    """
    from .schema_snapshots import read
    root = _safe_path(root)
    try:
        with _locked(root):
            index = _empty_index()
            for path in sorted((root/'schemas').glob('*.json')):
                if path.name == 'index.json':
                    continue
                _safe_path(path)
                payload = path.read_bytes()
                if not _HASH.fullmatch(path.stem) or hashlib.sha256(payload).hexdigest() != path.stem:
                    _invalid('cannot rebuild around a corrupt schema object', path)
                _json(payload, path)
                index['objects'][path.stem] = {'bytes': len(payload), 'provenance': []}
            for path, kind in _references(root):
                if kind == 'symlink':
                    _invalid('cannot rebuild across an uninspected symlink subtree', path)
                manifest = _json(path.read_bytes(), path)
                read(path)
                if isinstance(manifest, dict) and manifest.get('version') == PROTOCOL:
                    manifest, owner = _manifest(path)
                    if owner == root:
                        _record(index, manifest)
            atomic(root/'schemas/index.json', canonical(index))
            return index
    except OSError as error:
        fail('SCHEMA_STORAGE_ERROR', 'schema index rebuild failed: ' + str(error), str(root))


def export_run(source, destination):
    """Copy a run and all nested schema dependencies into an independent tree.

    Existing destinations and symlinks are refused. Failure leaves a visibly
    incomplete destination (.schema-export-incomplete) for inspection; source data
    is never modified or removed. The caller must verify application artifacts
    separately before any archive-and-remove operation.
    """
    from .schema_snapshots import read, store
    source, destination = _safe_path(source), _safe_path(destination)
    if not source.is_dir() or destination.exists() or destination.is_relative_to(source) or source.is_relative_to(destination):
        _invalid('export needs a source directory and a new destination outside it', destination)
    if (source/'.schema-export-incomplete').exists():
        _invalid('source is an incomplete export; recover it before re-exporting', source)
    dependencies = []
    payloads = {}
    for directory, dirs, files in os.walk(source, followlinks=False):
        for name in dirs + files:
            path = Path(directory)/name
            if path.is_symlink():
                _invalid('portable export refuses symlinks; select a self-contained run', path)
            if path.is_file() and name.endswith('.snapshot.json'):
                payload = read(path)
                manifest = _json(path.read_bytes(), path)
                _standalone(_json(payload, path), path)
                payload = payloads.setdefault(manifest['sha256'], payload)
                dependencies.append((path.relative_to(source), manifest, payload))
    try:
        destination.mkdir(parents=True, exist_ok=False)
        marker = destination/'.schema-export-incomplete'
        marker.write_text('Export in progress or failed; do not remove the source.\n', encoding='utf-8')
        # Manifests are republished only after dependency bytes are installed.
        for directory, dirs, files in os.walk(source, followlinks=False):
            relative = Path(directory).relative_to(source)
            target = destination/relative
            target.mkdir(parents=True, exist_ok=True)
            for name in files:
                if not name.endswith('.snapshot.json'):
                    shutil.copy2(Path(directory)/name, target/name)
                    from .run_paths import MANIFEST, export_manifest
                    if name == MANIFEST:
                        # Keep native receipts and their digest-bound provenance
                        # byte-identical. Only this shared companion maps their
                        # producing location into the selected exported tree.
                        atomic(target/name, canonical(export_manifest(directory)))
        if (any(manifest['version'] == PROTOCOL for _, manifest, _ in dependencies)
                and (destination/'schemas').is_dir() and not (destination/'schemas/index.json').exists()):
            rebuild_index(destination)
        for relative, manifest, payload in dependencies:
            target = destination/relative
            if manifest['version'] == PROTOCOL:
                store_shared(destination, target, payload, provider=manifest['provider'],
                             document_version=manifest['documentVersion'], authored=manifest['authored'],
                             provenance=manifest['provenance'])
            else:
                # Preserve v1 exact bytes and its original adjacent schemas/ layout.
                store(target.parent, target.name[:-len('.snapshot.json')], payload,
                      provider=manifest['provider'], document_version=manifest['documentVersion'], authored=manifest['authored'])
            read(target)
        marker.unlink()
        return {'source': str(source), 'destination': str(destination), 'manifests': len(dependencies),
                'schemas': len({manifest['sha256'] for _, manifest, _ in dependencies}),
                'bytes': sum(path.stat().st_size for path in destination.rglob('*') if path.is_file())}
    except OSError as error:
        fail('SCHEMA_STORAGE_ERROR', 'portable export incomplete; retain the source: ' + str(error), str(destination))
