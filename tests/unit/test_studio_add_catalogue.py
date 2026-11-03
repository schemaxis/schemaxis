# Copyright (C) 2026 David L F Gaden
"""Complete Add coverage and located authoring diagnostics stay host-only."""
import json
import unittest
from unittest.mock import patch
from schemaxis import authoring
from schemaxis.adaptors import registry
from schemaxis.errors import fail
from schemaxis.studio_catalogue import catalogue


class StudioAddCatalogueTests(unittest.TestCase):
    def test_complete_paraview_operations_and_controls(self):
        with patch('subprocess.Popen', side_effect=AssertionError('host-only')):
            result = catalogue('paraview')
        self.assertEqual({i['operation'] for i in result['items'] if 'operation' in i},
                         set(registry.declarations('paraview')))
        self.assertEqual(len({i['id'] for i in result['items']}), len(result['items']))
        groups = {i['group'] for i in result['items']}
        self.assertEqual(groups, {'inputs', 'sources', 'filters', 'outputs', 'presentation'})
        self.assertIn('scene:camera', {i['id'] for i in result['items']})
        self.assertIn('scene:appearance', {i['id'] for i in result['items']})
        for name, declaration in registry.declarations('paraview').items():
            with self.subTest(operation=name):
                options = result['definitions']['options-' + name]
                self.assertEqual(set(options['properties']), set(declaration['options']))
                self.assertEqual(set(options.get('required', [])),
                    {k for k, v in declaration['options'].items() if v['value'].get('required')})
        clip = result['definitions']['options-pvClip']['properties']['ClipType']
        self.assertEqual({v['properties']['type']['enum'][0] for v in clip['anyOf']},
                         set(registry.declarations('paraview')['pvClip']['options']['ClipType']['proxyChoices']))

    def test_missing_key_and_node_id_faults_have_coordinates(self):
        source = json.dumps({'version': 'schemaxis/1', 'nodes': [
            {'id': 'cut', 'filter': 'slice', 'options': {'normal': '🧭'}}]}, indent=2)
        def invalid(document):
            fail('MISSING_ARGUMENT', 'Missing required input', '/nodes/0/inputs/input')
        _, diagnostics = authoring.analyse(source, invalid)
        fault = diagnostics[0]
        self.assertEqual(fault['pointer'], '/nodes/0/inputs/input')
        self.assertEqual(fault['sourcePointer'], '/nodes/0')
        self.assertGreater(fault['line'], 1)
        def wrong(document):
            fail('INVALID_ARGUMENT', 'Invalid direction', 'cut.normal')
        _, diagnostics = authoring.analyse(source, wrong)
        self.assertEqual(diagnostics[0]['pointer'], '/nodes/0/options/normal')
        self.assertEqual(source[diagnostics[0]['offset']], '"')

    def test_nested_addresses_and_syntax_coordinates(self):
        source = '{\n "outer": [{"a/b~c": [false]}]\n}'
        _, faults = authoring.analyse(source, lambda d: fail('INVALID', 'Bad value', '/outer/0/a~1b~0c/0'))
        self.assertEqual(faults[0]['pointer'], '/outer/0/a~1b~0c/0')
        self.assertEqual(source[faults[0]['offset']:][:5], 'false')
        _, faults = authoring.analyse('{\n "nodes": ]}', lambda d: None)
        self.assertEqual(faults[0]['line'], 2)
        self.assertEqual(faults[0]['code'], 'INVALID_JSON')

    def test_native_publication_validation_retains_nested_image_and_export_paths(self):
        body = {'version': 'schemaxis/1', 'nodes': [{'id': 'source', 'filter': 'sphere'}],
                'scenes': [{'id': 'first', 'geometry': ['source']},
                           {'id': 'second', 'visible': {'source': {}},
                            'images': [{'id': 'preview', 'cameras': [{'padding': -1}]}]}]}
        _, faults = authoring.analyse(json.dumps(body, indent=2), registry.plan)
        self.assertEqual(faults[0]['pointer'], '/scenes/1/images/0/cameras/0/padding')
        body['scenes'][1] = {'id': 'second', 'exports': [{'id': 'mesh', 'node': 'source',
            'writer': 'pvWriteXMLPolyDataWriter', 'tolerance': -1}]}
        # Use a real declared exact writer; naming follows the captured native catalogue.
        writers = {name: value for name, value in registry.declarations('paraview').items()
                   if value.get('role') == 'writer' and value['publication']['comparison'] == 'exact'}
        body['scenes'][1]['exports'][0]['writer'] = next(iter(writers))
        _, faults = authoring.analyse(json.dumps(body, indent=2), registry.plan)
        self.assertEqual(faults[0]['pointer'], '/scenes/1/exports/0/tolerance')

    def test_schema_projection_keeps_annotations_owned_and_source_unchanged(self):
        from schemaxis.schema_authoring import _lift, _literal, discriminated
        original = {'type': 'object', 'properties': {'items': {'type': 'array',
            'items': {'type': 'object', 'properties': {'filter': {'const': 'sphere'}}},
            'default': [{'colour': [1, 0, 0]}]}}, 'examples': [{'items': []}]}
        saved = json.loads(json.dumps(original))
        for transform in (lambda value: _lift(value, compose=True, wrap=False), discriminated):
            result = transform(original)
            _literal(result['properties']['items'])['default'][0]['colour'][0] = 0
            result['examples'][0]['items'].append('changed')
            self.assertEqual(original, saved)
