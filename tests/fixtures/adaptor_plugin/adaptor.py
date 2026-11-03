# Copyright (C) 2026 David L F Gaden
"""A small independent test adaptor; no knowledge of existing applications."""
import copy
import json
from pathlib import Path
from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.errors import fail
from schemaxis.schema import object_schema

DECLARATIONS = {'emit': {'id': 'emit', 'native': 'test writer', 'inputs': {},
    'options': {'text': {'value': {'type': 'string', 'default': 'hello'}}}}}


def schema():
    return object_schema({'version': {'const': 'fixtureapp/1'},
        'nodes': {'type': 'array', 'items': object_schema({'id': {'type': 'string'},
            'filter': {'const': 'emit'}, 'options': object_schema({'text': {'type': 'string'}})}, ['id', 'filter'])}}, ['version', 'nodes'])


def plan(document):
    if document.get('version') != 'fixtureapp/1': fail('UNSUPPORTED_VERSION', 'expected fixtureapp/1')
    for node in document['nodes']:
        if node['filter'] != 'emit': fail('UNKNOWN_FILTER', 'expected emit')
    return copy.deepcopy(document)


def run(document, directory, *, executable=None, timeout=300):
    plan(document)
    directory = Path(directory)
    directory.mkdir()
    atomic_json(directory/'authored.json', document)
    output = directory/'output.txt'
    output.write_text(''.join(n.get('options', {}).get('text', 'hello') for n in document['nodes']))
    atomic_json(directory/'verification.json', {'artifacts': [
        {'file': str(output), 'kind': 'text', 'sha256': file_digest(output)}]})
    return {'verified': True, 'executable': executable, 'timeout': timeout}


def verify(directory):
    receipt = json.loads((Path(directory)/'verification.json').read_text())
    for artifact in receipt['artifacts']:
        if file_digest(artifact['file']) != artifact['sha256']: fail('VERIFICATION_FAILED', 'digest differs')
    return {'verified': True, 'artifacts': len(receipt['artifacts'])}


def reusable_inputs(document):
    return {}
