# Copyright (C) 2026 David L. F. Gaden.
"""Discovery cardinality is a parent contract, independent of native execution."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from schemaxis.adaptors import registry
from schemaxis.adaptors.shotcut import adaptor
from schemaxis.core.faults import SchemaxisError
from schemaxis.studio_catalogue import catalogue, collection_limit
from schemaxis.studio_library import load_library

ROOT = Path(__file__).resolve().parents[2]


class CollectionLimits(unittest.TestCase):
    def test_shotcut_one_projection_keeps_contract_and_guidance(self):
        with patch('subprocess.Popen', side_effect=AssertionError('native discovery')):
            items = catalogue('shotcut')['items']
        timelines = [item for item in items if item.get('operation') == 'editTimeline']
        self.assertEqual(len(timelines), 1)
        item = timelines[0]
        self.assertEqual(item['id'], 'operation:editTimeline')
        self.assertEqual(item['title'], 'Trim and arrange video clips')
        self.assertEqual(item['collectionLimit'], {'path': '/nodes', 'maxItems': 1})
        self.assertEqual(item['ports'], {})
        self.assertEqual(item['bindings'], registry.declarations('shotcut')['editTimeline']['options'])
        self.assertEqual(item['schema']['properties']['filter']['const'], 'editTimeline')
        self.assertEqual(item['schema']['properties']['options']['required'], ['assets', 'clips'])
        self.assertEqual(item['description'], item['guidance']['explanation'])
        self.assertIn('reorder', item['description'].lower())
        self.assertNotIn('studioCatalogue', registry.metadata('shotcut'))

    def test_literal_bounds_nested_targets_refs_and_unbounded(self):
        schema = {'type': 'object', '$defs': {'bounded': {'type': 'array', 'maxItems': 2, 'items': {}}},
                  'properties': {'things': {'$ref': '#/$defs/bounded'}, 'free': {'type': 'array', 'items': {}},
                                 'scenes': {'type': 'array', 'items': {'type': 'object', 'properties': {
                                     'images': {'type': 'array', 'maxItems': 3, 'items': {}}}}}}}
        original = copy.deepcopy(schema)
        self.assertEqual(collection_limit(schema, '/things/-'), {'path': '/things', 'maxItems': 2})
        self.assertEqual(collection_limit(schema, '/scenes/{scene}/images/-'),
                         {'path': '/scenes/{scene}/images', 'maxItems': 3})
        for at in ('/free/-', '/absent/-', '/things', '/scenes/{scene}/absent/-'):
            self.assertIsNone(collection_limit(schema, at))
        self.assertEqual(schema, original)
        for invalid in (-1, True, 1.5, 2 ** 53):
            with self.subTest(invalid=invalid), self.assertRaises(SchemaxisError) as caught:
                collection_limit({'properties': {'nodes': {'type': 'array', 'maxItems': invalid}}}, '/nodes/-')
            self.assertEqual(caught.exception.fault.code, 'INVALID_STUDIO_CATALOGUE')

    def test_conjunctive_reference_bounds_and_unsupported_structural_siblings(self):
        for referenced, sibling, expected in ((1, 2, 1), (5, 2, 2), (1.0, 2.0, 1)):
            schema = {'$defs': {'bound': {'type': 'array', 'maxItems': referenced}},
                      'properties': {'nodes': {'$ref': '#/$defs/bound', 'maxItems': sibling, 'title': 'Nodes'}}}
            self.assertEqual(collection_limit(schema, '/nodes/-'), {'path': '/nodes', 'maxItems': expected})
        chained = {'$defs': {'first': {'$ref': '#/$defs/last', 'maxItems': 5},
                             'last': {'type': 'array', 'maxItems': 1}},
                   'properties': {'nodes': {'$ref': '#/$defs/first', 'maxItems': 9}}}
        self.assertEqual(collection_limit(chained, '/nodes/-'), {'path': '/nodes', 'maxItems': 1})
        for sibling in ({'properties': {'nodes': {'type': 'array', 'maxItems': 9}}},
                        {'items': {'type': 'array', 'maxItems': 9}}, {'type': 'object'}):
            schema = {'$defs': {'bound': {'type': 'object', 'properties': {
                          'nodes': {'type': 'array', 'maxItems': 1}}}},
                      '$ref': '#/$defs/bound', **sibling}
            with self.subTest(sibling=sibling), self.assertRaises(SchemaxisError) as caught:
                collection_limit(schema, '/nodes/-')
            self.assertEqual(caught.exception.fault.code, 'INVALID_STUDIO_CATALOGUE')
            self.assertIn('structural $ref siblings', caught.exception.fault.message)

    def test_json_schema_integral_numbers_normalize_without_relaxing_invalid_bounds(self):
        for spelling, expected in (('1.0', 1), ('0.0', 0), ('2e0', 2), ('9007199254740991', 9007199254740991)):
            spec = json.loads('{"properties":{"nodes":{"type":"array","maxItems":' + spelling + '}}}')
            result = collection_limit(spec, '/nodes/-')
            self.assertEqual(result['maxItems'], expected)
            self.assertIs(type(result['maxItems']), int)
        for invalid in (True, -1.0, 1.5, float('nan'), float('inf'), float('-inf'), 9007199254740992.0):
            with self.subTest(invalid=invalid), self.assertRaises(SchemaxisError):
                collection_limit({'properties': {'nodes': {'type': 'array', 'maxItems': invalid}}}, '/nodes/-')

    def test_actual_multi_item_route_projects_its_declared_bound(self):
        route = registry.metadata('gmsh')['routes']['schemaxis.gmsh/1']
        schema = registry.binding(route['schema'])()
        self.assertEqual(schema['properties']['nodes']['maxItems'], 2)
        entries = [item for item in catalogue('gmsh', 'schemaxis.gmsh/1')['items'] if item['at'] == '/nodes/-']
        self.assertTrue(entries)
        self.assertTrue(all(item['collectionLimit'] == {'path': '/nodes', 'maxItems': 2} for item in entries))

    def test_custom_non_node_hook_survives_without_invented_bound(self):
        items = catalogue('paraview')['items']
        camera = next(item for item in items if item['id'] == 'scene:camera')
        self.assertIn('camera', camera['at'])
        self.assertIsInstance(camera['schema'], dict)
        sphere = next(item for item in items if item.get('operation') == 'sphere')
        self.assertNotIn('collectionLimit', sphere)

    def test_hook_cannot_forge_a_parent_limit(self):
        metadata = registry.metadata('shotcut')
        binding = registry.binding
        hook = 'schemaxis.adaptors.shotcut.adaptor:fixture_hook'
        def resolve(name):
            if name == hook:
                return lambda schema: [{'id': 'forged', 'at': '/nodes/-', 'schema': {},
                                        'collectionLimit': {'path': '/nodes', 'maxItems': 99}}]
            return binding(name)
        with patch.object(registry, 'metadata', return_value={**metadata, 'studioCatalogue': hook}), \
                patch.object(registry, 'binding', side_effect=resolve), self.assertRaises(SchemaxisError) as caught:
            catalogue('shotcut')
        self.assertEqual(caught.exception.fault.code, 'INVALID_STUDIO_CATALOGUE')

    def test_template_describes_literal_ranges_and_planner_retains_repetitions(self):
        library = load_library('shotcut')
        description = library['templates'][0]['description']
        self.assertIn('3–5', description)
        self.assertIn('0–1', description)
        self.assertNotIn('final three', description)
        source = json.loads((ROOT / 'examples/schemaxis/shotcut-timeline.json').read_text())
        source['nodes'][0]['id'] = 'UserTimeline'
        source['nodes'][0]['options']['clips'].append(copy.deepcopy(source['nodes'][0]['options']['clips'][0]))
        before = copy.deepcopy(source)
        result = adaptor.plan(source)
        self.assertEqual(source, before)
        self.assertEqual(result['nodes'][0]['id'], 'UserTimeline')
        self.assertEqual(result['nodes'][0]['options']['clips'], before['nodes'][0]['options']['clips'])
        self.assertEqual([segment['timelineStart'] for segment in result['segments']], [0, 3, 5])

    def test_ledger_limits_credit_to_singleton_suitability(self):
        ledger = json.loads((ROOT / 'verification/adaptor-authoring/ledger.json').read_text())['entries']
        entry = ledger['shotcut/schemaxis.shotcut~11/operation:editTimeline']
        self.assertEqual(set(entry), {'multiMode', 'notes'})
        self.assertEqual(entry['multiMode']['classification'], 'singleton')
        self.assertEqual(entry['multiMode']['implementation'], 'not-applicable')
        self.assertEqual(entry['multiMode']['qualification'], 'not-required')
        self.assertEqual(entry['multiMode']['routes'], ['schemaxis.shotcut/1'])
        self.assertNotIn('shotcut/schemaxis.shotcut~11/operation:editTimeline@2', ledger)
