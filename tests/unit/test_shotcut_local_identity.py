# Copyright (C) 2026 David L. F. Gaden.
"""Host-only tests of the authored Shotcut identity contract."""
import copy
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

from schemaxis.adaptors import registry
from schemaxis.adaptors.shotcut import adaptor, authoring_references
from schemaxis.errors import SchemaxisError
from schemaxis.identity_policy import for_route, validate
from schemaxis.identity_rename import rename_identity
from schemaxis.identity_transition import checked_transition, proof
from schemaxis.schema import export_schema
from schemaxis.storage import digest

TARGET = '/nodes/0/options/assets/0/name'
OWNER_SCHEMA = '/properties/nodes/items'
OPTION_SCHEMA = OWNER_SCHEMA + '/properties/options/properties'
ROUTE = 'schemaxis.shotcut/1'


def timeline(first='Intro'):
    return {'version': ROUTE, 'nodes': [{'id': 'Intro', 'filter': 'editTimeline', 'options': {
        'assets': [{'name': first, 'file': '/missing/Entrée.mkv'},
                   {'name': 'Outro', 'file': '/missing/Closing.mkv'}],
        'clips': [{'asset': first, 'startFrame': 3, 'frameCount': 3},
                  {'asset': 'Outro', 'startFrame': 1, 'frameCount': 2},
                  {'asset': first, 'startFrame': 0, 'frameCount': 2}],
        'fps': 25, 'width': 32, 'height': 24, 'threads': 1}}]}


def workflow(first, second):
    return {'version': 'schemaxis.workflow/1', 'operations': [
        {'id': 'first', 'document': first}, {'id': 'second', 'document': second}]}


def calc():
    return {'version': 'schemaxis.calc/1', 'nodes': [
        {'id': 'Intro', 'filter': 'fromRows', 'options': {'columns': ['letter'], 'rows': [[1]]}}]}


class LocalIdentity(unittest.TestCase):
    def preview(self, document, target=TARGET, name='Opening-1'):
        return rename_identity(document, target, name, digest(document))

    def refuses(self, code, document, target=TARGET, name='Opening-1'):
        before = copy.deepcopy(document)
        with self.assertRaises(SchemaxisError) as caught:
            self.preview(document, target, name)
        self.assertEqual(caught.exception.fault.code, code)
        self.assertEqual(document, before)
        return caught.exception.fault

    def test_preview_updates_every_ordered_consumer_and_preserves_parent(self):
        document = timeline()
        before = copy.deepcopy(document)
        result = self.preview(document)
        self.assertEqual(document, before)
        self.assertEqual(result['version'], 'schemaxis.identity-change/2')
        self.assertEqual(result['input'], timeline('Opening-1'))
        self.assertEqual(result['inputDigest'], digest(before))
        self.assertEqual(result['outputDigest'], digest(timeline('Opening-1')))
        self.assertEqual(result['changedPointers'], [
            TARGET, '/nodes/0/options/clips/0/asset', '/nodes/0/options/clips/2/asset'])
        self.assertEqual(result['identityChanges'], [{
            'identity': 'asset', 'domain': 'owner-local', 'scope': '', 'pointer': TARGET,
            'old': 'Intro', 'new': 'Opening-1', 'route': ROUTE, 'provider': 'shotcut',
            'owner': '/nodes/0', 'collection': '/nodes/0/options/assets'}])
        unchanged = self.preview(document, name='Intro')
        self.assertEqual(unchanged['changedPointers'], [])
        self.assertEqual(unchanged['identityChanges'], [])
        self.assertEqual(unchanged['input'], document)

    def test_lowered_timeline_preserves_project_resources_and_ranges(self):
        original = timeline()
        renamed = self.preview(original)['input']
        for document, name in ((original, 'Intro'), (renamed, 'Opening-1')):
            with self.subTest(name=name):
                plan = adaptor.plan(document)
                self.assertEqual(plan['frames'], 7)
                self.assertEqual([s['timelineStart'] for s in plan['segments']], [0, 3, 5])
                root = ElementTree.fromstring(adaptor.project(plan, '/missing'))
                self.assertEqual(root.find('profile').get('frame_rate_num'), '25')
                producers = root.findall('producer')
                self.assertEqual([p.get('id') for p in producers], ['asset-' + name, 'asset-Outro', 'black'])
                self.assertEqual([p.find("property[@name='resource']").text for p in producers],
                                 ['asset-00.media', 'asset-01.media', '#000000'])
                self.assertEqual(producers[0].find("property[@name='shotcut:caption']").text, name)
                self.assertEqual([entry.attrib for entry in root.findall("playlist[@id='timeline']/entry")], [
                    {'producer': 'asset-' + name, 'in': '3', 'out': '5'},
                    {'producer': 'asset-Outro', 'in': '1', 'out': '2'},
                    {'producer': 'asset-' + name, 'in': '0', 'out': '1'}])

    def test_names_reject_collisions_and_match_the_planner(self):
        self.refuses('IDENTITY_COLLISION', timeline(), name='Outro')
        for invalid in ('', '0Intro', 'A' * 65, 'Intro\n', 'É'):
            with self.subTest(invalid=invalid):
                self.refuses('INVALID_IDENTITY', timeline(), name=invalid)
                with self.assertRaises(SchemaxisError):
                    adaptor.plan(timeline(invalid))
        for valid in ('A', 'A' * 64, 'Intro_aa-bb'):
            self.assertEqual(self.preview(timeline(), name=valid)['input'], timeline(valid))
            self.assertEqual(adaptor.plan(timeline(valid))['frames'], 7)

    def test_computed_consumer_and_destination_capture_refuse(self):
        document = timeline()
        clip = document['nodes'][0]['options']['clips'][2]
        clip['asset'] = {'$document': TARGET}
        self.refuses('UNRESOLVED_IDENTITY_REFERENCE', document)
        clip['asset'] = 'Opening-1'
        self.refuses('IDENTITY_COLLISION', document)

    def test_wrong_owner_shape_and_huge_index_refuse(self):
        document = timeline()
        document['nodes'] = {'0': document['nodes'][0]}
        self.refuses('INVALID_IDENTITY_SCOPE', document)
        self.refuses('UNKNOWN_IDENTITY_REFERENCE', timeline(), TARGET.replace('/0/', '/' + '9' * 5000 + '/', 1))
        self.refuses('UNSUPPORTED_IDENTITY', timeline(), TARGET.replace('/0/', '/00/', 1))

    def test_stale_digest_and_no_graph_authority(self):
        document = timeline()
        with self.assertRaises(SchemaxisError) as caught:
            self.preview(document, '/nodes/0/id')
        self.assertEqual(caught.exception.fault.code, 'UNSUPPORTED_IDENTITY')
        with self.assertRaises(SchemaxisError) as caught:
            checked_transition({'input': document}, TARGET, 'Opening-1', 'stale')
        self.assertEqual(caught.exception.fault.code, 'STALE_IDENTITY_INPUT')
        with patch('schemaxis.spatial_load.Closure', side_effect=AssertionError('local proof reached graph closure')):
            with self.assertRaises(SchemaxisError) as caught:
                proof(document, TARGET, 'Opening-1')
        self.assertEqual(caught.exception.fault.code, 'UNSUPPORTED_IDENTITY_TRANSITION')

    def test_workflow_does_not_touch_another_timeline(self):
        document = workflow(timeline(), timeline())
        self.assertEqual(self.preview(document, '/operations/0/document' + TARGET)['input'],
                         workflow(timeline('Opening-1'), timeline()))

    def test_changed_borrow_into_graph_or_local_slots_refuses(self):
        graph = calc()
        graph['nodes'][0]['id'] = {'$document': TARGET, 'operation': 'first'}
        self.refuses('UNSUPPORTED_IDENTITY_COMPOSITION', workflow(timeline(), graph),
                     '/operations/0/document' + TARGET)
        peer = timeline()
        peer['nodes'][0]['options']['clips'][2]['asset'] = {'$document': '/nodes/0/id', 'operation': 'first'}
        self.refuses('UNSUPPORTED_IDENTITY_COMPOSITION', workflow(calc(), peer),
                     '/operations/0/document/nodes/0/id', name='Opening_1')

    def test_unrelated_import_succeeds_in_mixed_workflows(self):
        for source, slot, destination, version, expected_document in (
                (timeline(), TARGET, 'Opening-1', 'schemaxis.identity-change/2', timeline('Opening-1')),
                (calc(), '/nodes/0/id', 'Opening_1', 'schemaxis.identity-change/1',
                 {'version': 'schemaxis.calc/1', 'nodes': [
                     {'id': 'Opening_1', 'filter': 'fromRows', 'options': {'columns': ['letter'], 'rows': [[1]]}}]})):
            with self.subTest(version=version):
                peer = timeline()
                peer['nodes'][0]['options']['assets'][0]['file'] = {
                    '$document': slot, 'operation': 'first'}
                document = workflow(source, peer)
                before = copy.deepcopy(document)
                result = self.preview(document, '/operations/0/document' + slot, destination)
                self.assertEqual(result['version'], version)
                self.assertEqual(result['input'], workflow(expected_document, peer))
                self.assertEqual(document, before)

    def test_publication_id_and_unknown_route_stay_protected(self):
        document = timeline()
        document['nodes'][0]['id'] = {'$document': TARGET}
        self.refuses('UNSUPPORTED_IDENTITY_COMPOSITION', document)
        peer = timeline()
        peer['nodes'][0]['id'] = {'$document': '/nodes/0/id', 'operation': 'first'}
        self.refuses('UNSUPPORTED_IDENTITY_COMPOSITION', workflow(calc(), peer),
                     '/operations/0/document/nodes/0/id', name='Opening_1')
        unknown = {'version': 'schemaxis.unknown/1', 'value': {'$document': TARGET, 'operation': 'first'}}
        self.refuses('UNSUPPORTED_IDENTITY_COMPOSITION', workflow(timeline(), unknown),
                     '/operations/0/document' + TARGET)
        unknown['value'] = 'Intro'
        self.assertEqual(self.preview(workflow(timeline(), unknown), '/operations/0/document' + TARGET)['input'],
                         workflow(timeline('Opening-1'), unknown))


class LocalAdmission(unittest.TestCase):
    def assert_invalid(self, policy, schema, declarations=None):
        with self.assertRaises(SchemaxisError) as caught:
            validate(policy, schema, adaptor.DECLARATIONS if declarations is None else declarations)
        self.assertEqual(caught.exception.fault.code, 'INVALID_REFERENCE_POLICY')

    def test_actual_schema_and_projected_addresses(self):
        route = registry.metadata('shotcut')['routes'][ROUTE]
        projected = for_route('shotcut', route)['projection']['asset']
        self.assertNotIn('operations', projected)
        self.assertEqual(projected['ownerSchemas'], [OWNER_SCHEMA])
        self.assertEqual(projected['identitySchemas'], [OPTION_SCHEMA + '/assets/items/properties/name'])
        self.assertEqual(projected['referenceSchemas'], [OPTION_SCHEMA + '/clips/items/properties/asset'])
        options = export_schema('shotcut', 'editTimeline')['properties']
        for array, prop in (('assets', 'name'), ('clips', 'asset')):
            self.assertEqual(options[array]['items']['properties'][prop], authoring_references.ASSET_NAME)

    def test_semantic_types_and_closed_ownership(self):
        for marker in ([], {}, None):
            policy = authoring_references.policy()
            policy['markers'] = [{'key': '$observe', 'identity': marker}]
            self.assert_invalid(policy, adaptor.schema())
        policy = authoring_references.policy()
        self.assert_invalid(policy, adaptor.schema(), {'editTimeline': []})
        for key, malformed in (('type', 'object'), ('items', []), ('items', {'oneOf': {}})):
            schema = adaptor.schema()
            schema['properties']['nodes'][key] = malformed
            self.assert_invalid(policy, schema)

    def test_ref_escapes_depth_and_address_bytes(self):
        schema = adaptor.schema()
        owner = schema['properties']['nodes']['items']
        schema['$defs'] = {'owner/~': owner}
        schema['properties']['nodes']['items'] = {'$ref': '#/$defs/owner~1~0'}
        policy = authoring_references.policy()
        projected = validate(policy, schema, adaptor.DECLARATIONS)['projection']['asset']
        self.assertEqual(projected['ownerSchemas'], ['/$defs/owner~1~0'])
        with patch('schemaxis.identity_policy._SCHEMA_ADDRESS_BYTES', 20):
            self.assert_invalid(policy, schema)
        schema['properties']['nodes']['items'] = {'$ref': '#/$defs/owner~2'}
        self.assert_invalid(policy, schema)
        schema['properties']['nodes']['items'] = {'$ref': '#/$defs/0'}
        schema['$defs'].update({str(i): {'$ref': '#/$defs/' + str(i + 1)} for i in range(72)})
        schema['$defs']['72'] = owner
        self.assert_invalid(policy, schema)

    def test_local_consumer_paths_cannot_overlap(self):
        policy = authoring_references.policy()
        policy['references'].append(dict(policy['references'][0]))
        self.assert_invalid(policy, adaptor.schema())
