# Copyright (C) 2026 David L F Gaden
"""Schema projection, graph boundaries and generated documentation consistency."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest
from schemaxis.core.faults import SchemaxisError
from schemaxis.schema import argument_schema, arguments_schema, declarations, expand_input, export_schema

try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None

ROOT = Path(__file__).resolve().parents[2]


class SchemaProjectionTests(unittest.TestCase):
    def test_required_defaults_closed_objects_and_exclusive_bounds(self):
        spec = {'radius': {'type': 'number', 'minimum': 0, 'exclusiveMinimum': True, 'default': 1},
                'label': {'type': 'string', 'required': True}}
        schema = arguments_schema(spec)
        self.assertEqual(schema['required'], ['label'])
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(schema['properties']['radius']['exclusiveMinimum'], 0)
        self.assertNotIn('minimum', schema['properties']['radius'])
        self.assertEqual(schema['properties']['radius']['default'], 1)
        self.assertEqual(spec['radius']['exclusiveMinimum'], True)

    def test_nested_union_and_enum_projection(self):
        value = argument_schema({'type':'union', 'options':[
            {'type':'enum','values':['auto']},
            {'type':'array','minItems':2,'maxItems':2,'items':{'type':'integer','minimum':0}}]})
        self.assertEqual(value['anyOf'][0], {'enum':['auto']})
        self.assertEqual(value['anyOf'][1]['items'], {'type':'integer','minimum':0})
        with self.assertRaises(SchemaxisError):
            argument_schema({'type':'number','typo':4})

    def test_new_option_is_exported_without_another_option_list(self):
        from schemaxis.schema import option_schema
        schema = option_schema({'id':'test','options':{'newSetting':{
            'value':{'type':'integer','minimum':2,'default':5},'path':['NativeSetting']}}})
        self.assertEqual(schema['properties']['newSetting']['default'], 5)
        self.assertEqual(schema['properties']['newSetting']['minimum'], 2)

    def test_expansion_retains_authored_input_and_removes_conveniences(self):
        source = json.loads((ROOT/'examples/schemaxis/blender-primitives.json').read_text())
        original = copy.deepcopy(source)
        expanded = expand_input(source)
        self.assertEqual(source, original)
        self.assertNotIn('$analytic', json.dumps(expanded))
        self.assertNotIn('$object', json.dumps(expanded))
        self.assertIn('$axis', json.dumps(expanded))

    def test_generated_reference_has_no_drift(self):
        spec = importlib.util.spec_from_file_location('export_input_reference', ROOT/'tools/export_input_reference.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for name, expected in module.artifacts().items():
            with self.subTest(name=name):
                self.assertEqual((ROOT/'docs/generated'/name).read_text(), expected)


@unittest.skipIf(Draft202012Validator is None, 'optional jsonschema developer package unavailable')
class SchemaConformanceTests(unittest.TestCase):
    def test_schemas_and_every_declared_option_default(self):
        for provider in ('paraview','blender','freecad','godot','aseprite'):
            Draft202012Validator.check_schema(export_schema(provider))
            for name, declaration in declarations(provider).items():
                Draft202012Validator.check_schema(export_schema(provider, operation=name))
                for key, binding in declaration['options'].items():
                    value = binding['value']
                    if 'default' in value:
                        with self.subTest(provider=provider, operation=name, option=key):
                            Draft202012Validator(argument_schema(value)).validate(value['default'])
        for section in ('camera','style','render','series','time-selection'):
            Draft202012Validator.check_schema(export_schema(section=section))

    def test_all_single_provider_examples(self):
        for path in (ROOT/'examples/schemaxis').glob('*.json'):
            document = json.loads(path.read_text())
            provider = {'schemaxis/1':'paraview','schemaxis.blender/1':'blender','schemaxis.freecad/1':'freecad'}.get(document.get('version'))
            if provider:
                with self.subTest(path=path.name):
                    expanded = expand_input(document)
                    if expanded['version'] == 'schemaxis.study/1':
                        # A finite variant study is validated state by state.
                        self.assertEqual(expanded['documentVersion'], document['version'])
                        self.assertGreater(len(expanded['visits']), 1)
                        states = [expand_input(visit['document']) for visit in expanded['visits']]
                    else:
                        states = [expanded]
                    for state in states:
                        Draft202012Validator(export_schema(provider)).validate(state)

    def test_invalid_literal_nodes_and_headers_are_rejected(self):
        original = {'version':'schemaxis/1', 'nodes':[{'id':'sphere','filter':'sphere'}],
                    'scenes':[{'id':'output','geometry':['sphere']}]}
        validator = Draft202012Validator(export_schema())
        validator.validate(original)
        mutations = [lambda d:d.update(extra=1),
                     lambda d:d['nodes'][0].update(filter='unregistered'),
                     lambda d:d['nodes'][0].update(options={'radius':0}),
                     lambda d:d['nodes'][0].update(options={'typo':1}),
                     lambda d:d.update(maxStates=False),
                     lambda d:d['nodes'][0].update(filter='slice'),
                     lambda d:d['nodes'][0].update(filter='readSurface')]
        for mutate in mutations:
            doc = copy.deepcopy(original);mutate(doc)
            self.assertFalse(validator.is_valid(doc), doc)

    def test_runtime_values_allowed_but_constructor_values_constant(self):
        schema = export_schema()
        validator = Draft202012Validator(schema)
        document = {'version':'schemaxis/1','nodes':[{'id':'sphere','filter':'sphere',
            'options':{'radius':{'$axis':'size'}}}], 'axes':[{'name':'size','values':[1,2]}],
            'scenes':[{'id':'output','geometry':['sphere']}]}
        validator.validate(document)
        document['nodes'][0] = {'id':'sphere','filter':'readSurface',
            'options':{'files':[{'$axis':'size'}]}}
        self.assertFalse(validator.is_valid(document))

    def test_document_schema_does_not_claim_graph_semantics(self):
        from schemaxis.job import plan
        document = {'version':'schemaxis/1','nodes':[{'id':'cut','filter':'slice','inputs':{'input':'missing'}}],
                    'scenes':[{'id':'output','geometry':['cut']}]}
        Draft202012Validator(export_schema()).validate(document)
        with self.assertRaises(SchemaxisError):
            plan(document)
