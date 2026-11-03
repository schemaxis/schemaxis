# Copyright (C) 2026 David L F Gaden
"""Optional portable ParaView schemas grouped by native structural role.

Existing standalone exports remain unchanged. This explicit bundle uses relative
JSON Schema references; copy every member and its manifest when moving it.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from schemaxis.errors import fail
from schemaxis.schema import DRAFT, export_schema
from schemaxis.schema_authoring import _literal
from schemaxis.schema_snapshots import _publish
from schemaxis.studio_guidance import fields

PROTOCOL = 'schemaxis.schema-bundle/1'
GROUPS = ('common', 'readers', 'filters', 'rendering', 'writers')
ENTRY = 'paraview.schema.json'


def _group(declaration):
    if declaration.get('role') == 'writer':
        return 'writers'
    filenames = any(binding.get('constructor') and (
        'vtkSMFileListDomain' in binding.get('nativeDomains', [])
        or any(str(part).lower() in ('file', 'files', 'filename', 'filenames') for part in binding.get('path', [])))
        for binding in declaration['options'].values())
    return 'readers' if not declaration['inputs'] and filenames else 'filters'


def _operation(variant, field):
    node = _literal(variant.get('then', variant))
    return _literal(node['properties'][field])['const']


def _pointer(name):
    return name.replace('~', '~0').replace('/', '~1')


def schemas(*, authored=True):
    """Return all modules and a full-document entry point without native imports."""
    from .filters import catalogue
    declarations = catalogue()
    groups = {name: _group(value) for name, value in declarations.items()}
    original = export_schema('paraview', authored=authored)
    root = copy.deepcopy(original)
    definitions = root.pop('$defs')
    modules = {group: {'$schema': DRAFT, 'title': 'ParaView ' + group, '$defs': {}} for group in GROUPS}
    owners = {}
    for name, definition in definitions.items():
        group = groups[name[len('options-'):]] if name.startswith('options-') else 'readers' if name == 'readback' else 'common'
        modules[group]['$defs'][name] = definition
        owners[name] = group

    def partition(union, field, prefix):
        keyword = 'oneOf' if 'oneOf' in union else 'anyOf'
        references = {group: [] for group in GROUPS}
        variants = []
        for variant in union[keyword]:
            name = _operation(variant, field)
            group = groups[name]
            key = prefix + name
            modules[group]['$defs'][key] = variant
            reference = {'$ref': group + '.schema.json#/$defs/' + _pointer(key)}
            variants.append(reference)
            references[group].append(reference)
        union[keyword] = variants
        return keyword, references

    nodes = _literal(_literal(root['properties']['nodes'])['items'])
    keyword, node_refs = partition(nodes, 'filter', 'node-')
    for group in ('readers', 'filters'):
        modules[group]['$defs']['nodes'] = {keyword: node_refs[group]} if node_refs[group] else False
        modules[group]['$ref'] = '#/$defs/nodes'
    # Authored inline nodes have a distinct ID requirement; retain those exact
    # variants while sharing the same operation category and option definitions.
    inline = modules['common']['$defs'].get('inlineNode')
    if inline:
        partition(inline, 'filter', 'inline-')
    scene = _literal(root['properties']['scenes'])['items']
    exports = _literal(_literal(_literal(scene)['properties']['exports'])['items'])
    keyword, writer_refs = partition(exports, 'writer', 'export-')
    modules['writers']['$defs']['exports'] = {keyword: writer_refs['writers']} if writer_refs['writers'] else False
    modules['writers']['$ref'] = '#/$defs/exports'
    modules['rendering']['$defs']['scene'] = scene
    modules['rendering']['$ref'] = '#/$defs/scene'
    _literal(root['properties']['scenes'])['items'] = {'$ref': 'rendering.schema.json#/$defs/scene'}

    def rewrite(value, current):
        result = copy.deepcopy(value)
        aliases = {}
        for _, node in fields(result):
            reference = node.get('$ref')
            if isinstance(reference, str) and reference.startswith('#/$defs/'):
                parts = reference[len('#/$defs/'):].split('/', 1)
                name = parts[0].replace('~1', '/').replace('~0', '~')
                owner = owners.get(name)
                if owner and owner != current:
                    if len(parts) > 1:
                        # A JSON pointer into a definition cannot navigate
                        # through a forwarding $ref as if it were that object.
                        node['$ref'] = owner + '.schema.json' + reference
                        continue
                    # One forwarding definition keeps repeated runtime and
                    # composition references short within each category.
                    aliases[name] = {'$ref': owner + '.schema.json#/$defs/' + _pointer(name)}
        if aliases:
            result.setdefault('$defs', {}).update(aliases)
        return result

    return {**{group + '.schema.json': rewrite(module, group) for group, module in modules.items()},
            ENTRY: rewrite(root, None)}


def _refs(value):
    # Defaults, enum/const values and annotations may contain literal $ref keys.
    # The same schema-only traversal drives Studio's field addresses.
    for _, node in fields(value):
        if '$ref' in node:
            yield node['$ref']


def _closure(documents):
    """Check every local/external pointer offline, including unused definitions."""
    for name, document in documents.items():
        try:
            references = list(_refs(document))
        except (AttributeError, TypeError, ValueError):
            fail('INVALID_SCHEMA_BUNDLE', 'member has malformed schema children', name)
        for reference in references:
            if not isinstance(reference, str):
                fail('INVALID_SCHEMA_BUNDLE', 'schema reference must be text', name)
            member, separator, fragment = reference.partition('#')
            if not separator or (member and member not in documents) or (fragment and not fragment.startswith('/')):
                fail('INVALID_SCHEMA_BUNDLE', 'reference is outside this offline bundle', name, reference=reference)
            target = documents[member or name]
            try:
                for part in fragment.split('/')[1:] if fragment else []:
                    part = part.replace('~1', '/').replace('~0', '~')
                    target = target[int(part)] if isinstance(target, list) else target[part]
            except (KeyError, IndexError, TypeError, ValueError):
                fail('INVALID_SCHEMA_BUNDLE', 'reference target is missing', name, reference=reference)


def write(directory, *, authored=True):
    documents = schemas(authored=authored)
    _closure(documents)
    directory = Path(directory)
    records = {}
    for name, document in documents.items():
        payload = (json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n').encode('utf-8')
        _publish(directory/name, payload)
        records[name] = {'sha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload)}
    manifest = {'version': PROTOCOL, 'provider': 'paraview', 'documentVersion': 'schemaxis/1',
                'authored': authored, 'entryPoint': ENTRY, 'files': records}
    _publish(directory/'bundle.json', (json.dumps(manifest, indent=2) + '\n').encode('utf-8'))
    return manifest


def read(directory):
    """Verify all members and pointer closure; never fetch or regenerate a schema."""
    directory = Path(directory)
    try:
        manifest = json.loads((directory/'bundle.json').read_text(encoding='utf-8'))
        expected = {ENTRY, *(group + '.schema.json' for group in GROUPS)}
        if (not isinstance(manifest, dict) or set(manifest) != {'version', 'provider', 'documentVersion', 'authored', 'entryPoint', 'files'}
                or manifest['version'] != PROTOCOL or manifest['provider'] != 'paraview'
                or manifest['documentVersion'] != 'schemaxis/1' or type(manifest['authored']) is not bool
                or manifest['entryPoint'] != ENTRY or not isinstance(manifest['files'], dict) or set(manifest['files']) != expected):
            raise ValueError('invalid bundle manifest')
        documents = {}
        for name, record in manifest['files'].items():
            path = directory/name
            if path.is_symlink() or not isinstance(record, dict) or set(record) != {'sha256', 'bytes'} or type(record['bytes']) is not int:
                raise ValueError('invalid member record: ' + name)
            payload = path.read_bytes()
            if len(payload) != record['bytes'] or hashlib.sha256(payload).hexdigest() != record['sha256']:
                raise ValueError('member content differs: ' + name)
            document = json.loads(payload)
            if name == ENTRY:
                properties = document.get('properties') if isinstance(document, dict) else None
                selector = properties.get('version') if isinstance(properties, dict) else None
                if not isinstance(selector, dict) or selector.get('const') != manifest['documentVersion']:
                    raise ValueError('entry point must declare its exact document version')
            documents[name] = document
    except (OSError, UnicodeError, ValueError, TypeError) as error:
        fail('INVALID_SCHEMA_BUNDLE', str(error), str(directory))
    _closure(documents)
    return documents


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--expanded', action='store_true')
    parser.add_argument('--check', action='store_true', help='verify saved bytes and references offline')
    args = parser.parse_args(argv)
    if args.check:
        documents = read(args.directory)
        print(json.dumps({'verified': True, 'files': len(documents), 'entryPoint': ENTRY}))
    else:
        print(json.dumps(write(args.directory, authored=not args.expanded), indent=2))


if __name__ == '__main__':
    main()
