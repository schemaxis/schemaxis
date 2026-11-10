"""Pinned file and directory snapshots at typed compression input positions."""
import copy
from schemaxis.errors import fail


def _item(values, token):
    if not isinstance(values, list) or not token.isascii() or not token.isdecimal() or len(token) > 20:
        return None
    index = int(token)
    return values[index] if str(index) == token and index < len(values) else None


def accept_resource(document, pointer, resource):
    from .adaptor import VERSION, OPTIONS
    operation = document.get('operation')
    parts = pointer.split('/')[1:]
    role = None
    directory = False
    if document.get('version') == VERSION and isinstance(operation, str) and operation in OPTIONS:
        options = OPTIONS[operation]
        if len(parts) == 1 and parts[0] in ('source', 'dictionary', 'reference') and parts[0] in options:
            role = parts[0]
        elif len(parts) == 2 and parts[0] in ('sources', 'samples') and parts[0] in options:
            if _item(document.get(parts[0]), parts[1]) is not None:
                role = parts[0]
        elif 'fileSet' in options and isinstance(document.get('fileSet'), dict):
            selected = document['fileSet']
            if parts == ['fileSet', 'root']:
                role, directory = 'file-set directory', True
            elif len(parts) == 4 and parts[:2] == ['fileSet', 'files'] and parts[3] == 'source':
                if isinstance(_item(selected.get('files'), parts[2]), dict):
                    role = 'named file-set member'
    if role is None:
        fail('UNSUPPORTED_RESOURCE', 'choose a file input belonging to the selected Zstandard task', pointer)
    if directory:
        if resource['kind'] != 'directory' or resource['member'] is not None:
            fail('UNSUPPORTED_RESOURCE', 'fileSet.root requires a complete captured directory snapshot', pointer)
    elif resource['member'] is None:
        fail('UNSUPPORTED_RESOURCE', 'choose one captured file, including an explicit member of a directory snapshot', pointer)
    return {'reader': role, 'scope': 'pinned directory membership' if directory else 'selected pinned file',
            'limits': 'existing codec, regular-file, byte and file-set bounds remain enforced'}


def captured_schema(schema, reference):
    """Keep snapshot references within the same file-input grammar as consumption."""
    def literal(node):
        while 'anyOf' in node and 'type' not in node:
            node = node['anyOf'][0]
        return node

    def admit(node):
        if 'anyOf' in node:
            node['anyOf'].append(copy.deepcopy(reference))
        else:
            previous = copy.deepcopy(node)
            node.clear()
            node['anyOf'] = [previous, copy.deepcopy(reference)]

    # The shared envelope and each task arm both constrain these fields.
    for document in (schema, *(schema.get('oneOf') or schema['anyOf'])):
        props = document['properties']
        for key in ('source', 'dictionary', 'reference'):
            if key in props:
                admit(props[key])
        for key in ('sources', 'samples'):
            if key in props:
                admit(literal(props[key])['items'])
        if 'fileSet' in props:
            selected = literal(props['fileSet'])['properties']
            admit(selected['root'])
            members = literal(literal(selected['files'])['items'])['properties']
            admit(members['source'])
