# Copyright (C) 2026 David L F Gaden
"""Standalone authored contracts: real inputs, recursive grammar and rejection."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from schemaxis.schema import export_schema
from schemaxis.schema_authoring import VERSIONS, version_schema
from schemaxis.adaptors import registry
from schemaxis.adaptor_delivery import route_materials
from schemaxis.core.faults import SchemaxisError

try:
    from jsonschema import Draft202012Validator as Validator
except ImportError:
    Validator = None

ROOT = Path(__file__).resolve().parents[2]


def sphere(value=1):
    return {'version': 'schemaxis/1', 'nodes': [{'id': 's', 'filter': 'sphere',
        'options': {'radius': value}}], 'scenes': [{'id': 'out', 'geometry': ['s']}]}


@unittest.skipIf(Validator is None, 'optional jsonschema developer dependency unavailable')
class AuthoredSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = {v: version_schema(v, authored=True) for v in VERSIONS}
        cls.validators = {v: Validator(s) for v, s in cls.schemas.items()}
        cls.invalid_fixtures = {ROOT / example['reference']: example
            for version in registry.routes()
            for example in route_materials(version)[2].get('examples', [])
            if example.get('expect') == 'invalid' and 'reference' in example}

    def valid(self, document):
        self.assertTrue(self.validators[document['version']].is_valid(document), document)

    def invalid(self, document):
        self.assertFalse(self.validators[document['version']].is_valid(document), document)

    def test_all_eight_metaschemas_and_internal_references(self):
        for version, schema in self.schemas.items():
            with self.subTest(version=version):
                Validator.check_schema(schema)
                def walk(value):
                    if isinstance(value, list):
                        for child in value: walk(child)
                    elif isinstance(value, dict):
                        if '$ref' in value:
                            target = schema
                            self.assertTrue(value['$ref'].startswith('#/'))
                            for part in value['$ref'][2:].split('/'):
                                target = target[part.replace('~1', '/').replace('~0', '~')]
                        for child in value.values(): walk(child)
                walk(schema)

    def test_recursive_repository_corpus_with_extension_explicitly_separate(self):
        checked = 0
        for path in sorted((ROOT / 'examples').rglob('*.json')):
            document = json.loads(path.read_text())
            if not isinstance(document, dict) or document.get('version') not in VERSIONS:
                continue  # Native assets, catalogue capsules and legacy MVP are not routed inputs.
            with self.subTest(path=str(path.relative_to(ROOT))):
                if path == ROOT / 'examples/schemaxis/extensions/pipeline.json':
                    self.invalid(document)
                elif path in self.invalid_fixtures:
                    example = self.invalid_fixtures[path]
                    (self.invalid if example.get('schemaValid') is False else self.valid)(document)
                    with self.assertRaises(SchemaxisError) as caught: registry.plan(document)
                    self.assertEqual(caught.exception.fault.code, example['fault'])
                else:
                    self.valid(document)
                checked += 1
        self.assertGreaterEqual(checked, 49)

    def test_registered_extension_capsule_is_in_schema_without_native_import(self):
        from schemaxis.adaptors.paraview.catalogue import _package
        _package()  # Keep the real pinned package while substituting only extension lookup.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'paraview_extensions').mkdir()
            shutil.copyfile(ROOT / 'examples/schemaxis/extensions/schemaxis-shrink.json',
                            root / 'paraview_extensions/schemaxis-shrink.json')
            with patch('schemaxis.adaptors.paraview.catalogue.files', return_value=root):
                validator = Validator(version_schema('schemaxis/1', authored=True))
                document = json.loads((ROOT / 'examples/schemaxis/extensions/pipeline.json').read_text())
                self.assertTrue(validator.is_valid(document))
                document['nodes'][1]['options']['Factor'] = 'invalid'
                self.assertFalse(validator.is_valid(document))
                self.assertIn('Factor', export_schema(operation='pvSchemaxisShrink')['properties'])

    def test_expanded_recursive_corpus(self):
        from schemaxis.schema import expand_input
        validators = {v: Validator(version_schema(v)) for v in VERSIONS}
        for path in sorted((ROOT / 'examples').rglob('*.json')):
            document = json.loads(path.read_text())
            if not isinstance(document, dict) or document.get('version') not in VERSIONS or path.parent.name == 'extensions':
                continue
            with self.subTest(path=str(path.relative_to(ROOT))):
                if path in self.invalid_fixtures:
                    example = self.invalid_fixtures[path]
                    schema_invalid = example.get('schemaValid') is False
                    (self.invalid if schema_invalid else self.valid)(document)
                    with self.assertRaises(SchemaxisError) as caught: registry.plan(document)
                    self.assertEqual(caught.exception.fault.code, example['fault'])
                    try: expanded = expand_input(document)
                    except SchemaxisError as error:
                        self.assertEqual(error.fault.code, example['fault'])
                    else:
                        self.assertEqual(validators[document['version']].is_valid(expanded), not schema_invalid)
                    continue
                expanded = expand_input(document)
                if expanded['version'] == 'schemaxis.study/1':
                    self.assertTrue(expanded['visits'])
                    from schemaxis.adaptor_runtime import pending
                    from schemaxis.workflow import inspect_plan
                    for visit in expanded['visits']:
                        effective = visit['document']
                        if pending(effective):
                            # Result-dependent inputs remain authored data until
                            # producer verification; they are not literal input.
                            self.assertTrue(Validator(version_schema(effective['version'], authored=True)).is_valid(effective))
                            inspect_plan(effective)
                        else:
                            self.assertTrue(validators[effective['version']].is_valid(effective))
                else:
                    self.assertTrue(validators[document['version']].is_valid(expanded))

    def test_all_composition_operators_typed_and_closed(self):
        from schemaxis.core.composition import evaluate
        validator = Validator(export_schema(section='composition'))
        pairs = {'add': [1, 2], 'subtract': [3, 1], 'multiply': [2, 3], 'divide': [4, 2],
            'concat': [[1], [2]], 'merge': [{'a': 1}, {'b': 2}], 'overlay': [{'a': 1}, {'a': 2}],
            'omit': [{'a': 1}, ['a']], 'get': [[1], 0],
            'namedMerge': [[{'name': 'a'}], [{'name': 'b'}]], 'namedGet': [[{'name': 'a'}], 'a']}
        for op, args in pairs.items():
            expression = {'op': op, 'args': args}
            with self.subTest(op=op):
                self.assertTrue(validator.is_valid({'$expr': expression}))
                evaluate(expression, '$')
                self.assertFalse(validator.is_valid({'$expr': {**expression, 'extra': 1}}))
                self.assertFalse(validator.is_valid({'$expr': {**expression, 'args': args[:1]}}))
        self.assertFalse(validator.is_valid({'$expr': {'op': 'add', 'args': [1, 2], 'conflict': 'left'}}))

    def test_nested_composition_matches_planner(self):
        from schemaxis.job import plan
        cases = [
            {'$analytic': {'type': 'linear', 'start': 1, 'end': 2, 'count': {'$document': '/definitions/n'}}},
            {'$analytic': {'$document': '/definitions/spec'}},
            {'$expr': {'op': {'$document': '/definitions/op'}, 'args': {'$document': '/definitions/args'}}},
            {'$expr': {'$document': '/definitions/expression'}},
            {'$calc': 'add', 'args': [1, {'$analytic': {'type': 'values', 'values': [1, 2]}}]},
        ]
        for value in cases:
            document = sphere(value)
            document['definitions'] = {'n': 2, 'op': 'add', 'args': [1, 2],
                'spec': {'type': 'linear', 'start': 1, 'end': 2, 'count': 2},
                'expression': {'op': 'add', 'args': [1, 2]}}
            with self.subTest(value=value):
                self.valid(document)
                plan(document)

    def test_inline_targets_and_whole_create_are_composed(self):
        from schemaxis.job import plan
        for source in ({'$object': {'node': 's', 'port': 0}},
                       {'$object': {'$document': '/definitions/source'}},
                       {'$create': {'$document': '/definitions/node'}}):
            document = sphere()
            document['definitions'] = {'source': 's', 'node': {'filter': 'sphere'}}
            document['nodes'].append({'id': 'cut', 'filter': 'slice', 'inputs': {'input': source}})
            document['scenes'][0]['geometry'] = ['cut']
            self.valid(document)
            plan(document)

    def test_strict_dispatch_headers_and_recursive_markers(self):
        self.valid(sphere())
        for value in ({'$document': 3}, {'$document': '/x', 'extra': 1},
                      {'$calc': 'add', 'args': [1, {'$time': False}]},
                      {'$expr': {'op': 'merge', 'args': [{'$document': 3}, {}]}},
                      {'$expr': {'op': 'add', 'args': [1]}},
                      {'$expr': {'op': 'add', 'args': [1, 'two']}}):
            with self.subTest(value=value): self.invalid(sphere(value))
        document = sphere(); document['execution'] = {}
        self.invalid(document)
        validator = self.validators['schemaxis/1']
        self.assertFalse(validator.is_valid({'$expr': {'op': 'merge', 'args': [sphere(), {}]}}))
        document = sphere(); document['version'] = {'$document': '/definitions/version'}
        self.assertFalse(validator.is_valid(document))
        document = sphere(); document['nodes'][0]['onVisit'] = []
        self.valid(document)
        document['nodes'][0]['onVisit'] = ['undeclared']
        self.invalid(document)

    def test_common_runtime_accepts_constructor_and_camera_member_analytics(self):
        value = {'$analytic': {'type': 'values', 'values': [1, 2]}}
        document = sphere()
        document['nodes'][0] = {'id': 's', 'filter': 'readSurface', 'options': {'files': [value]}}
        self.valid(document)
        document = sphere()
        document['scenes'][0]['images'] = [{'id': 'im', 'cameras': [{'distance': value}]}]
        self.valid(document)
        document['scenes'][0]['images'][0]['cameras'] = {
            '$analytic': {'type': 'values', 'values': [{}], 'sync': 'unsupported'}}
        self.invalid(document)

    def test_all_providers_gain_composition(self):
        for version, property_name in [('schemaxis.godot/1', 'preview'),
                                       ('schemaxis.aseprite/1', 'output')]:
            path = next(p for p in (ROOT / 'examples').rglob('*.json')
                if isinstance((d := json.loads(p.read_text())), dict) and d.get('version') == version)
            document = json.loads(path.read_text())
            document[property_name] = {'$document': '/definitions/value'}
            self.valid(document)
        document = {'version': 'schemaxis.blender.render/1', 'sceneFile': '/prepared.blend', 'cameras': [{}]}
        self.valid(document)
        document['sceneFile'] = {'$document': '/definitions/file'}
        self.valid(document)

    def test_freecad_default_export_requires_read_file_and_names(self):
        validator = Validator(export_schema('freecad'))
        document = {'version': 'schemaxis.freecad/1', 'nodes': [{'id': 'part', 'filter': 'readSTEP'}], 'output': 'part'}
        self.assertFalse(validator.is_valid(document))
        document['nodes'][0]['options'] = {'file': '/part.step'}
        self.assertTrue(validator.is_valid(document))
        document['nodes'][0]['id'] = 'bad name'
        self.assertFalse(validator.is_valid(document))

    def test_aseprite_operation_schema_shares_lossless_colour_contract(self):
        validator = Validator(export_schema('aseprite', operation='pixel'))
        from schemaxis.schema import declarations
        declaration = declarations('aseprite')['pixel']
        options = {k: v['value'].get('default', 1) for k, v in declaration['options'].items()}
        options['layer'] = 'base'
        options['colour'] = [12, 34, 56, 255]
        self.assertTrue(validator.is_valid(options), options)
        options['colour'] = [12, 34, 56, 128]
        self.assertFalse(validator.is_valid(options))

    def test_readback_null_closed_reader_and_managed_filename(self):
        schema = version_schema('schemaxis/1')
        # Remove the document envelope to validate just its shared definition.
        validator = Validator({'$defs': schema['$defs'], '$ref': '#/$defs/readback'})
        self.assertTrue(validator.is_valid(None))
        self.assertTrue(validator.is_valid({'operation': 'pvXMLPolyDataReader'}))
        for value in ({'operation': 'sphere'}, {'operation': 'pvXMLPolyDataReader', 'options': {'FileName': ['managed.vtp']}},
                      {'operation': 'pvXMLPolyDataReader', 'options': {'notDeclared': 1}}):
            self.assertFalse(validator.is_valid(value), value)

    def test_workflow_artifacts_and_execution(self):
        document = {'version': 'schemaxis.workflow/1', 'execution': {'maxWorkers': 2, 'cpus': 4},
            'operations': [{'id': 'render', 'document': {'version': 'schemaxis.blender.render/1',
                'sceneFile': {'$artifact': 'prepare', 'index': 0}, 'cameras': [{}]}}]}
        self.valid(document)  # Earlier-operation existence is a semantic planner check.
        for artifact in ({'$artifact': 'prepare'}, {'$artifact': 'prepare', 'index': -1},
                         {'$artifact': 'prepare', 'index': 0, 'extra': 1}):
            changed = copy.deepcopy(document)
            changed['operations'][0]['document']['sceneFile'] = artifact
            self.invalid(changed)
        execution = Validator(export_schema(section='operation-execution'))
        for value in ({'ranks': 2}, {'ranks': 2, 'mpiexec': 'relative'}, {'threads': False}, {'typo': 1}):
            self.assertFalse(execution.is_valid(value))
        self.assertTrue(execution.is_valid({'ranks': 2, 'mpiexec': '/usr/bin/mpiexec'}))
        self.assertTrue(execution.is_valid({'ranks': 1, 'mpiexec': None}))
        for version in ('schemaxis.godot/1', 'schemaxis.aseprite/1', 'schemaxis.freecad.assembly/1'):
            changed = copy.deepcopy(document)
            changed['operations'][0]['document'] = {'version': version}
            self.invalid(changed)

    def test_discriminator_performance_preserves_complex_primitives(self):
        document = json.loads((ROOT / 'examples/schemaxis/primitives.json').read_text())
        started = time.monotonic()
        self.valid(document)
        self.assertLess(time.monotonic() - started, 10, 'irrelevant catalogue branches must short-circuit')

    def test_analytic_section_authored_flag_and_resource_port_boundary(self):
        value = {'$analytic': {'type': 'linear', 'start': 1, 'end': 2,
                              'count': {'$document': '/definitions/count'}}}
        self.assertTrue(Validator(export_schema(section='analytic', authored=True)).is_valid(value))
        self.assertFalse(Validator(export_schema(section='analytic')).is_valid(value))
        from schemaxis.schema import declarations
        catalogue = declarations('paraview')
        operation, port = next((op, p) for op, d in catalogue.items() if d.get('role') != 'writer'
            for p, spec in d['inputs'].items() if spec.get('kind', 'data') != 'data')
        # Isolate the generated node variant: other required ports/options are
        # irrelevant to whether a typed resource accepts a numeric output port.
        schema = self.schemas['schemaxis/1']
        node = next(v['then'] for v in schema['properties']['nodes']['anyOf'][0]['items']['anyOf'][0]['anyOf']
                    if v['then']['properties']['filter']['anyOf'][0].get('const') == operation)
        field = node['properties']['inputs']['anyOf'][0]['properties'][port]
        self.assertFalse(Validator({'$defs': schema['$defs'], **field}).is_valid(
            {'$object': {'node': 'resource', 'port': 0}}))


class SchemaCliTests(unittest.TestCase):
    def test_conflicting_cli_targets_fail_instead_of_ignoring_selection(self):
        env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src')}
        for flags in (['--all', '--version', 'schemaxis/1'], ['--authored', '--expanded']):
            result = subprocess.run([sys.executable, '-m', 'schemaxis', 'schema', *flags],
                cwd=ROOT, env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)

    def test_all_cli_modes_are_standalone_eight_version_contracts(self):
        env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src')}
        for flags, authored in [(['--all'], True), (['--all', '--expanded'], False)]:
            result = subprocess.run([sys.executable, '-m', 'schemaxis', 'schema', *flags],
                cwd=ROOT, env=env, capture_output=True, text=True, check=True)
            schema = json.loads(result.stdout)
            self.assertEqual(len(schema['oneOf']), len(VERSIONS))
            self.assertEqual('composition' in schema['$defs']['document0']['$defs'], authored)

    def test_cli_contract_and_no_native_or_schema_dependency_import(self):
        env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src')}
        for flags, expected in [(['--authored', '--version', 'schemaxis.freecad.assembly/1'], 'schemaxis.freecad.assembly/1'),
                                (['--provider', 'godot'], 'schemaxis.godot/1')]:
            result = subprocess.run([sys.executable, '-m', 'schemaxis', 'schema', *flags],
                cwd=ROOT, env=env, capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout)['properties']['version']['const'], expected)
        probe = "from schemaxis.schema import export_schema; import sys; export_schema(authored=True); assert not set(('bpy','paraview','FreeCAD','jsonschema')) & set(sys.modules)"
        subprocess.run([sys.executable, '-c', probe], cwd=ROOT, env=env, check=True)


if __name__ == '__main__':
    unittest.main()
