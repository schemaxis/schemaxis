# Copyright (C) 2026 David L F Gaden
"""Generate a reviewable source overlay; never install or qualify an adaptor."""
import copy
import json
import keyword
from pathlib import Path
import re

from .adaptors import registry
from .adaptor_delivery import FEATURES
from .errors import fail


def scaffold(provider, directory, *, model='nodes'):
    if (not isinstance(provider, str) or not re.fullmatch('[a-z][a-z0-9_]{0,47}', provider)
            or keyword.iskeyword(provider) or provider in registry.ADAPTORS):
        fail('INVALID_ADAPTOR_ID', 'choose a new lowercase adaptor ID, not an installed provider or Python keyword')
    if model not in ('nodes', 'document'):
        fail('INVALID_AUTHORING_MODEL', 'choose nodes or document')
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink():
        fail('OUTPUT_EXISTS', 'scaffolding requires a new directory; existing files are never overwritten', str(directory))
    version = 'schemaxis.' + provider + '/1'
    package = 'schemaxis.adaptors.' + provider
    prefix = 'src/schemaxis/adaptors/' + provider + '/'
    valid = ({'version': version, 'nodes': [{'id': 'example', 'filter': 'exampleOperation', 'options': {'value': 3}}]}
             if model == 'nodes' else {'version': version, 'operation': 'exampleOperation', 'value': 3})
    invalid = copy.deepcopy(valid)
    if model == 'nodes':
        invalid['nodes'][0]['options']['value'] = 'invalid'
    else:
        invalid['value'] = 'invalid'
    value_path = '/nodes/0/options/value' if model == 'nodes' else '/value'
    manifest = {'id': provider, 'version': version, 'adaptor': package + '.adaptor',
                'runtimeFamily': 'unqualified', 'execution': 'Development scaffold only; native execution is not implemented.',
                'executables': [], 'keywords': ['development scaffold'],
                'capabilities': package + '.capabilities:catalogue', 'executionCapabilities': {'mpi': False},
                'consoleTemplate': valid,
                'routes': {version: {'module': package + '.adaptor', 'schema': package + '.adaptor:schema',
                                    'graphEditing': model == 'nodes', 'workflow': False, 'compose': False,
                                    'timeBatches': False, 'schemaName': provider, 'acceptedArtifacts': []}}}
    feature = {name: {'status': 'supported' if name in ('source-authoring', 'property-authoring') else 'unsupported',
                      'scope': 'TODO decide the supported subset and provide feature-specific proof.'} for name in FEATURES}
    entry = {'guide': 'docs/' + provider + '.md',
             'context': {name: 'TODO describe ' + name + ' for the real bounded capability.'
                         for name in ('purpose', 'assumptions', 'constraints', 'inspection', 'recovery')},
             'examples': [{'id': 'baseline', 'document': valid},
                          {'id': 'invalid-value', 'document': invalid, 'expect': 'invalid', 'fault': 'INVALID_ARGUMENT', 'schemaValid': False}],
             'conformance': ['tests/unit/test_' + provider + '_admission.py'],
             'acceptance': ['tools/qualify_' + provider + '.py'], 'profiles': {},
             'completion': {'scope': 'TODO name the operations/routes changed and retained review evidence.',
                            'review': [], 'notApplicable': {}},
             'development': {'api': ['https://example.invalid/replace-with-public-native-api'],
                             'lifecycle': {name: 'TODO implement and document ' + name for name in ('timeout', 'cancellation', 'logs', 'verification')},
                             'data': [{'id': 'output', 'direction': 'output', 'kind': 'text', 'format': 'JSON',
                                       'traits': {'units': None}, 'losses': [], 'scope': 'TODO define the actual output promise and losses.'}],
                             'inspection': [{'panel': 'text', 'scope': 'TODO name the inspected result.', 'limits': 'TODO define bounds.'}],
                             'authoring': {'model': model, 'example': 'baseline', 'reuse': 'TODO explain how to reuse this example.'},
                             'features': feature,
                             'cases': [{'id': name, 'example': 'baseline', 'edits': edits,
                                        'scope': 'TODO replace scaffold values with independent domain expectations.',
                                        'checks': [{'file': 'output.json', 'format': 'json', 'pointer': '/value', 'expected': expected}]}
                                       for name, edits, expected in [('baseline', [], 3),
                                           ('variant', [{'op': 'replace', 'path': value_path, 'value': 4}], 4)]]}}
    adaptor = '''"""Host scaffold. Replace the illustrative operation with a bounded native contract."""
from schemaxis.core.declarations import validate_arguments
from schemaxis.errors import fail, keys
from schemaxis.schema import object_schema, argument_schema

VERSION = @VERSION@
VALUE = {'type': 'number', 'minimum': 0, 'maximum': 1000, 'default': 3}
DECLARATIONS = {'exampleOperation': {'native': 'NOT_IMPLEMENTED', 'inputs': {}, 'kinds': ['text'],
                                    'options': {'value': {'value': VALUE}}}}


def plan(document):
@PLAN@
    return {'version': VERSION, 'value': validate_arguments({'value': VALUE}, options)['value']}


def schema():
@SCHEMA@


def run(document, directory, *, executable=None, timeout=120):
    plan(document)
    # Implement isolated native invocation using native_command.execute or
    # SubprocessRunner. Retain authored.json, plan.json, logs, runtime identity,
    # independently checked publications and verification.json with artifact hashes.
    fail('ADAPTOR_NOT_IMPLEMENTED', 'Replace this scaffold with a bounded native runner')


def verify(directory):
    # Recheck actual artifacts, authored/plan agreement, independent expectations,
    # captured input provenance and receipt membership. Never trust a success flag.
    fail('ADAPTOR_NOT_IMPLEMENTED', 'Implement independent saved-result verification')
'''
    if model == 'nodes':
        plan = '''    keys(document, ('version', 'nodes'), '$')
    if document.get('version') != VERSION:
        fail('UNSUPPORTED_VERSION', 'expected ' + VERSION)
    nodes = document.get('nodes')
    if not isinstance(nodes, list) or len(nodes) != 1:
        fail('INVALID_DOCUMENT', 'provide one example node')
    node = nodes[0]
    keys(node, ('id', 'filter', 'options'), '$.nodes[0]')
    if node.get('id') != 'example' or node.get('filter') != 'exampleOperation':
        fail('UNKNOWN_FILTER', 'use the scaffold example identity and operation')
    options = node.get('options', {})'''
        schema = '''    node = object_schema({'id': {'const': 'example'}, 'filter': {'const': 'exampleOperation'},
                          'options': object_schema({'value': argument_schema(VALUE)})}, ['id', 'filter'])
    return object_schema({'version': {'const': VERSION},
                          'nodes': {'type': 'array', 'minItems': 1, 'maxItems': 1, 'items': {'oneOf': [node]}}}, ['version', 'nodes'])'''
    else:
        plan = '''    keys(document, ('version', 'operation', 'value'), '$')
    if document.get('version') != VERSION:
        fail('UNSUPPORTED_VERSION', 'expected ' + VERSION)
    if document.get('operation') != 'exampleOperation':
        fail('UNKNOWN_FILTER', 'use the scaffold example operation')
    options = {'value': document['value']} if 'value' in document else {}'''
        schema = '''    return object_schema({'version': {'const': VERSION}, 'operation': {'const': 'exampleOperation'},
                          'value': argument_schema(VALUE)}, ['version', 'operation'])'''
    adaptor = adaptor.replace('@VERSION@', repr(version)).replace('@PLAN@', plan).replace('@SCHEMA@', schema)
    catalogue = '''"""Replace scaffold prose with curated selection guidance and semantics."""


def catalogue():
    return {'application': {'label': @PROVIDER@, 'purpose': 'TODO describe application scope and when to choose it.', 'keywords': []},
        'searchCases': [{'id': 'replace-phrase', 'query': 'TODO realistic user phrase', 'kind': 'synonym', 'status': 'pending',
            'expected': {'capabilities': [@OPERATION@], 'adaptor': [@APP@], 'add': [@OPERATION@], 'help': [@OPERATION@]}}],
        'operations': {'exampleOperation': {
        'purpose': 'Development scaffold only; replace before admission.',
        'keywords': [],
        'semantics': ['No native implementation or qualification exists.']}},
        'references': [@GUIDE@, @BUNDLE@]}
'''.replace('@GUIDE@', repr('docs/' + provider + '.md')).replace('@BUNDLE@', repr(prefix+'readiness.json')).replace('@PROVIDER@', repr(provider)).replace('@OPERATION@', repr('operation/' + provider + '/exampleOperation')).replace('@APP@', repr('app/' + provider))
    native = '''"""Native-process implementation belongs here; never import it for discovery."""


def execute(request):
    from schemaxis.errors import fail
    fail('ADAPTOR_NOT_IMPLEMENTED', 'Implement the bounded native API, readback and runtime identity')
'''
    test = '''"""Generated host fixture checks; native acceptance must be implemented separately."""
import json
from importlib.resources import files
import unittest
from schemaxis.adaptors import registry
from schemaxis.core.faults import SchemaxisError


class AdmissionTests(unittest.TestCase):
    def test_planner_examples(self):
        bundle = json.loads(files(@PACKAGE@).joinpath('readiness.json').read_text())
        valid, invalid = bundle['routes'][@VERSION@]['examples']
        registry.plan(valid['document'])
        with self.assertRaises(SchemaxisError) as caught:
            registry.plan(invalid['document'])
        self.assertEqual(caught.exception.fault.code, invalid['fault'])

    def test_native_scaffold_does_not_claim_success(self):
        bundle = json.loads(files(@PACKAGE@).joinpath('readiness.json').read_text())
        valid = bundle['routes'][@VERSION@]['examples'][0]['document']
        with self.assertRaises(SchemaxisError) as caught:
            registry.run(valid, 'unused-scaffold-output')
        self.assertEqual(caught.exception.fault.code, 'ADAPTOR_NOT_IMPLEMENTED')
'''.replace('@PACKAGE@', repr(package)).replace('@VERSION@', repr(version))
    qualifier = '''"""After implementing independent checks, opt in to bounded native acceptance."""
import argparse
import json
from schemaxis.adaptor_conformance import qualify

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-directory', required=True)
parser.add_argument('--native', action='store_true')
args = parser.parse_args()
print(json.dumps(qualify(@VERSION@, args.output_directory, native=args.native), indent=2))
'''.replace('@VERSION@', repr(version))
    guide = '# ' + provider + ' adaptor development\n\nThis is an unimplemented scaffold, not an advertised native capability.\n\n' + \
        'Complete the [authoritative checklist](adaptor-completion.md) for this route and every later operation/field addition.\n' + \
        'Follow the [kit](adaptor-development.md), [Studio guidance contract](studio-adaptor-contract.md) and [extension contract](adaptors.md).\n\n' + \
        '## Pending authoring\n\nTODO explain supported scope, inputs/outputs, assumptions and limits. Replace the illustrative operation,\n' + \
        'author operation/field explanations in guidance.json, useful synonyms and realistic searchCases in capabilities.py,\n' + \
        'and editable starters in studio.json. Pending questions must remain pending until domain review.\n\n' + \
        '## Pending recovery and examples\n\nTODO explain stable faults, diagnosis and safe retry; link independent baseline/variant expectations.\n\n' + \
        '## Pending API and maintenance\n\nTODO cite public upstream API pages; remove example.invalid and select a release source in upstream.json.\n'
    # Inventory the exact illustrative schema without loading generated code.
    from .schema import object_schema, argument_schema
    from .studio_guidance import fields, VERSION as GUIDANCE_VERSION
    value_schema = argument_schema({'type': 'number', 'minimum': 0, 'maximum': 1000, 'default': 3})
    if model == 'nodes':
        node = object_schema({'id': {'const': 'example'}, 'filter': {'const': 'exampleOperation'},
                              'options': object_schema({'value': value_schema})}, ['id', 'filter'])
        document_schema = object_schema({'version': {'const': version}, 'nodes': {'type': 'array', 'minItems': 1,
                                         'maxItems': 1, 'items': {'oneOf': [node]}}}, ['version', 'nodes'])
    else:
        document_schema = object_schema({'version': {'const': version}, 'operation': {'const': 'exampleOperation'},
                                         'value': value_schema}, ['version', 'operation'])
    pending = {'status': 'pending', 'question': 'Explain purpose/use, meaning and units, omission/defaults, valid choices and common mistakes. Retain sources and meaningful examples; do not promote generated types to reviewed prose.'}
    guidance = {'version': GUIDANCE_VERSION, 'operations': {'exampleOperation': {**pending,
        'question': 'Explain when to use this operation, its inputs/outputs, assumptions, limitations and examples.'}},
        'routes': {version: {'fields': {address: dict(pending) for address, _ in fields(document_schema)}}}}
    studio = {'version': 'schemaxis.studio-adaptor/2', 'categories': [{'id': 'pending', 'title': 'Pending authoring'}],
              'templates': [{'id': 'pending-example', 'title': 'Unimplemented example',
                  'description': 'TODO replace this illustrative starter with a meaningful workflow.',
                  'requires': 'Native implementation, public API mapping and independent verification are pending.',
                  'document': valid}], 'snippets': [{'id': 'pending-value', 'title': 'Unimplemented value setting',
                      'description': 'TODO replace this sample with a useful authoring recipe and describe prerequisites.',
                      'category': 'pending', 'baseDocument': valid,
                      'inserts': [{'at': value_path, 'values': [3]}]}], 'viewers': ['text']}
    content = {prefix+'__init__.py': '', prefix+'adaptor.py': adaptor,
               prefix+'native.py': native, prefix+'capabilities.py': catalogue,
               prefix+'adaptor.json': json.dumps(manifest, indent=2)+'\n',
               prefix+'guidance.json': json.dumps(guidance, indent=2)+'\n',
               prefix+'studio.json': json.dumps(studio, indent=2)+'\n',
               prefix+'readiness.json': json.dumps({'version': 'schemaxis.readiness/1', 'routes': {version: entry}}, indent=2)+'\n',
               prefix+'upstream.json': json.dumps({'policy': 'latest-stable', 'absorbedVersion': None,
                   'source': None, 'manualReason': 'Select a public release source before admission.',
                   'scope': 'Unqualified scaffold. Select a public release source and run native acceptance before absorption.',
                   'evidence': [], 'acceptance': ['Complete the generated native acceptance recipe.']}, indent=2)+'\n',
               'tests/unit/test_'+provider+'_admission.py': test, 'tools/qualify_'+provider+'.py': qualifier,
               'examples/schemaxis/'+provider+'-minimal.json': json.dumps(valid, indent=2)+'\n',
               'docs/'+provider+'.md': guide,
               'DEVELOPMENT.md': '# Reviewable adaptor overlay\n\nNothing has been installed or qualified. Review these files, then copy the new\npackage, test, example, guide and recipe into the matching repository paths.\nDo not overwrite existing files. Complete TODOs using docs/adaptor-development.md.\n\n' +
                 '[Canonical completion checklist](docs/adaptor-completion.md) (available after merging into the checkout).\n\n' +
                 'Keep every generated explanation pending. Author synonyms and all four search-case kinds; retain review evidence.\n\n' +
                 f'After merging, run with `PYTHONPATH=src`:\n\n```sh\npython3 tools/studio_guidance.py --app {provider} --seed\n' +
                 f'python3 tools/studio_guidance.py --app {provider} --review evidence/{provider}-guidance.json\n' +
                 f'python3 tools/studio_guidance.py --app {provider} --check\npython3 -m schemaxis reference\n' +
                 'python3 tools/generate_studio_help.py\npython3 -m schemaxis reference --check\npython3 tools/generate_studio_help.py --check\n' +
                 f'python3 -m schemaxis readiness --app {provider} --admission --check\n' +
                 f'python3 -m schemaxis adaptor conform {version} --output-directory evidence/{provider}-host\n' +
                 'node --test src/schemaxis/studio_ui/tests/search-acceptance.test.mjs\n' +
                 f'python3 -m schemaxis adaptor conform {version} --native --output-directory evidence/{provider}-native\n```\n' +
                 'The gate is intentionally incomplete until real contracts and evidence exist.\n'}
    directory.mkdir(parents=True)
    for relative, value in content.items():
        path = directory/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    return {'provider': provider, 'documentVersion': version, 'directory': str(directory),
            'installed': False, 'qualification': 'unknown', 'files': sorted(content),
            'next': 'Review the overlay, implement the bounded capability, then run admission and conformance.'}
