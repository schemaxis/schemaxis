# Copyright (C) 2026 David L. F. Gaden.
"""Adversarial contracts for pure authored identity previews; no native execution."""
import copy
import importlib.abc
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from schemaxis.adaptors import registry
from schemaxis.errors import SchemaxisError
from schemaxis.identity_policy import for_route, validate
from schemaxis.identity_rename import rename_identity
from schemaxis.storage import digest


def document():
    return {'version': 'schemaxis/1', 'nodes': [{'id': 'A', 'filter': 'sphere'},
            {'id': 'B', 'filter': 'surface', 'inputs': {'input': 'A'}}]}


def workflow():
    return {'version': 'schemaxis.workflow/1', 'operations': [
        {'id': 'first', 'document': {**document(), 'scenes': [{'id': 'view', 'geometry': ['B']}]}},
        {'id': 'second', 'document': {**document(), 'scenes': [{'id': 'view', 'geometry': ['B']}]}}]}


class IdentityRename(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider, cls.route = registry.resolve(document())
        cls.policy = for_route(cls.provider, cls.route)

    def setUp(self):
        # Admission is independently tested below. Reuse the admitted immutable data
        # to exercise all 645 declaration projections without rebuilding their schemas.
        self.policy_patch = patch('schemaxis.identity_rename.for_route', return_value=self.policy)
        self.policy_patch.start()
        self.addCleanup(self.policy_patch.stop)

    def rename(self, value, path='/nodes/0/id', new='2-left'):
        before = copy.deepcopy(value)
        result = rename_identity(value, path, new, digest(value))
        self.assertEqual(value, before)
        self.assertEqual(result['inputDigest'], digest(before))
        self.assertEqual(result['outputDigest'], digest(result['input']))
        return result['input']

    def refuses(self, value, code, path='/nodes/0/id', new='2-left'):
        before = copy.deepcopy(value)
        with self.assertRaises(SchemaxisError) as caught:
            rename_identity(value, path, new, digest(value))
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault)
        self.assertEqual(value, before)
        return caught.exception.fault

    def test_declared_consumers_order_ports_and_unrelated_literals(self):
        value = document()
        value['nodes'][1]['inputs']['input'] = {'node': 'A', 'port': 1}
        value['nodes'] += [{'id': 'C', 'filter': 'group', 'inputs': {'input': ['B', {'$object': 'A'}, 'A']},
                            'options': {'names': ['A', 'not identities']}}]
        value['times'] = {'source': 'A', 'select': {'indices': [0]}}
        value['settings'] = {'A': 'A', 'file': 'A', 'selectors': ['A']}
        value['definitions'] = {'A': 4, 'box': {'$expr': 'extents(A, 0).mid.x + A'},
                                'observation': {'$observe': 'A', 'path': ['bounds']},
                                'sample': {'$sample': 'A', 'field': 'A', 'association': 'POINTS', 'index': 0}}
        value['scenes'] = [{'id': 'view', 'visible': {'B': {}, 'A': {'label': 'A'}},
                            'appearances': [{'A': {}, 'B': {}}], 'geometry': ['B', 'A'],
                            'measurements': [{'node': 'A'}], 'exports': [{'id': 'A', 'node': 'A', 'writer': 'unused'}]}]
        output = self.rename(value)
        self.assertEqual(output['nodes'][1]['inputs']['input'], {'node': '2-left', 'port': 1})
        self.assertEqual(output['nodes'][2]['inputs']['input'], ['B', {'$object': '2-left'}, '2-left'])
        self.assertEqual(output['settings'], value['settings'])
        self.assertEqual(output['nodes'][2]['options'], value['nodes'][2]['options'])
        self.assertEqual(output['definitions']['box']['$expr'], 'extents(`2-left`, 0).mid.x + A')
        self.assertEqual(output['definitions']['A'], 4)
        self.assertEqual(output['definitions']['sample']['field'], 'A')
        self.assertEqual(output['definitions']['sample']['$sample'], '2-left')
        self.assertEqual(output['definitions']['observation']['$observe'], '2-left')
        self.assertEqual(output['times']['source'], '2-left')
        scene = output['scenes'][0]
        self.assertEqual(list(scene['visible']), ['B', '2-left'])
        self.assertEqual(scene['visible']['2-left']['label'], 'A')
        self.assertEqual(scene['geometry'], ['B', '2-left'])
        self.assertEqual(scene['exports'][0]['id'], 'A')
        self.assertEqual(scene['exports'][0]['node'], '2-left')
        self.assertEqual(scene['measurements'][0]['node'], '2-left')

    def test_all_generated_operations_and_ports_use_the_admitted_projection(self):
        declarations = registry.declarations('paraview')
        ordinary = self.policy['projection']['node']['operations']
        self.assertEqual(len(ordinary), 601)
        self.assertEqual(len(self.policy['projection']['node']['writers']), 44)
        for operation, ports in ordinary.items():
            with self.subTest(operation=operation):
                value = document()
                value['nodes'][1] = {'id': 'B', 'filter': operation, 'inputs': {
                    name: ['A'] if spec['multiple'] else 'A' for name, spec in ports.items()}}
                output = self.rename(value)
                for name, spec in ports.items():
                    self.assertEqual(output['nodes'][1]['inputs'][name], ['2-left'] if spec['multiple'] else '2-left')
                # Each operation can itself be the selected ordinary identity, with incomplete options.
                renamed = self.rename(value, '/nodes/1/id', 'target')
                self.assertEqual(renamed['nodes'][1]['id'], 'target')
        self.assertEqual(set(ordinary), {name for name, spec in declarations.items() if spec.get('role') != 'writer'})

    def test_writer_resources_are_projected_from_actual_declarations(self):
        checked = 0
        for writer, ports in self.policy['projection']['node']['writers'].items():
            resources = {name: 'A' for name, spec in ports.items() if spec['kind'] != 'data'}
            value = document()
            value['scenes'] = [{'id': 'view', 'exports': [{'id': 'export', 'writer': writer,
                                                         'node': 'A', 'resources': resources}]}]
            output = self.rename(value)
            self.assertEqual(output['scenes'][0]['exports'][0]['resources'], {key: '2-left' for key in resources})
            checked += len(resources)
        self.assertGreater(checked, 0)

    def test_malformed_writer_selector_is_a_structured_atomic_refusal(self):
        value = document()
        value['scenes'] = [{'id': 'view', 'exports': [
            {'id': 'export', 'writer': [], 'node': 'A', 'resources': {}}]}]
        self.refuses(value, 'UNRESOLVED_IDENTITY_REFERENCE')

    def test_incomplete_options_and_unrelated_semantic_errors_are_retained(self):
        value = document()
        value['nodes'][0]['options'] = {'radius': {'$fill': 'radius'}}
        value['definitions'] = {'unknown': {'$expr': 'missing + 1'},
                                'combined': {'$expr': 'missing + extents(A).mid.x'},
                                'missing': {'$document': '/settings/notYetAuthored'}}
        value['times'] = [0, 1]
        value['scenes'] = {'$fill': 'scenes'}
        output = self.rename(value)
        self.assertEqual(output['nodes'][0]['options'], value['nodes'][0]['options'])
        self.assertEqual(output['definitions']['unknown'], value['definitions']['unknown'])
        self.assertEqual(output['definitions']['combined']['$expr'], 'missing + extents(`2-left`).mid.x')
        self.assertEqual(output['definitions']['missing'], value['definitions']['missing'])
        self.assertEqual(output['times'], [0, 1])
        self.assertEqual(output['scenes'], value['scenes'])

    def test_syntax_and_relevant_extents_calls_are_checked(self):
        for text in ('extents(A, -1)', 'extents(A, 999)', 'extents("A")', 'extents(A) + ('):
            with self.subTest(text=text):
                value = document(); value['definitions'] = {'x': {'$expr': text}}
                if text == 'extents(A, 999)':
                    declarations = registry.declarations('paraview')
                    value['nodes'][0]['filter'] = next(name for name, spec in declarations.items()
                        if spec.get('outputPorts', spec.get('coverage', {}).get('outputPorts')) == 1)
                self.refuses(value, 'UNRESOLVED_IDENTITY_EXPRESSION')

    def test_actual_name_schema_and_stale_guard(self):
        for name in ('é', 'A"', '', ['A']):
            with self.subTest(name=name): self.refuses(document(), 'INVALID_IDENTITY', new=name)
        for name in ('004', 'A-B', 'A_B'):
            self.assertEqual(self.rename(document(), new=name)['nodes'][0]['id'], name)
        with self.assertRaises(SchemaxisError) as caught:
            rename_identity(document(), '/nodes/0/id', 'A', 'stale')
        self.assertEqual(caught.exception.fault.code, 'STALE_IDENTITY_INPUT')
        original = document()
        output = rename_identity(original, '/nodes/0/id', 'A', digest(original))
        self.assertEqual(output['input'], original)
        self.assertIsNot(output['input'], original)
        self.assertEqual(output['identityChanges'], [])
        self.assertEqual(output['changedPointers'], [])

    def test_collisions_and_ambiguous_namespaces_fail_without_partial_edit(self):
        self.refuses(document(), 'IDENTITY_COLLISION', new='B')
        value = document(); value['nodes'].append({'id': 'A', 'filter': 'sphere'})
        self.refuses(value, 'AMBIGUOUS_IDENTITY_SCOPE')
        value = document(); value['scenes'] = [{'id': 'view', 'visible': {'A': {}, '2-left': {}}}]
        self.refuses(value, 'IDENTITY_COLLISION')
        value = workflow(); value['operations'][1]['id'] = 'first'
        self.refuses(value, 'AMBIGUOUS_IDENTITY_SCOPE', '/operations/0/document/nodes/0/id')

    def test_inline_consumers_collision_and_generated_descendant_boundaries(self):
        value = document()
        value['nodes'][1]['inputs']['input'] = {'$create': {'id': 'C', 'filter': 'surface', 'inputs': {'input': 'A'}}}
        output = self.rename(value)
        self.assertEqual(output['nodes'][1]['inputs']['input']['$create']['inputs']['input'], '2-left')
        self.refuses(value, 'IDENTITY_COLLISION', new='C')
        self.refuses(value, 'UNSUPPORTED_IDENTITY', '/nodes/1/inputs/input/$create/id')
        value['nodes'][0] = {'id': 'A', 'filter': 'surface', 'inputs': {'input': {'$create': {'filter': 'sphere'}}}}
        self.refuses(value, 'UNSUPPORTED_IDENTITY_DESCENDANTS')

    def test_generated_sibling_identity_is_reserved_and_object_arguments_are_repaired(self):
        from schemaxis.context import inline_identity, compile_objects
        value = document()
        value['nodes'][1]['inputs']['input'] = {'$create': {'filter': 'sphere'}}
        reserved = inline_identity('B', 'input')
        self.assertIn(reserved, [node['id'] for node in compile_objects(value)['nodes']])
        self.refuses(value, 'IDENTITY_COLLISION', new=reserved)
        value['nodes'][0]['options'] = {'opaque': {'$call': 'unavailable', 'args': {'body': {'$object': 'A'}}}}
        output = self.rename(value)
        self.assertEqual(output['nodes'][0]['options']['opaque']['args']['body'], {'$object': '2-left'})
        value = document()
        value['nodes'][0] = {'id': 'A', 'filter': 'surface', 'inputs': {'input': {'$create': {'id': 'C', 'filter': 'surface',
            'inputs': {'input': {'$create': {'filter': 'sphere'}}}}}}}
        before = [node['id'] for node in compile_objects(value)['nodes']]
        output = self.rename(value)
        after = [node['id'] for node in compile_objects(output)['nodes']]
        self.assertEqual(after, ['2-left' if name == 'A' else name for name in before])

    def test_workflow_scope_and_cross_operation_pointer_suffix(self):
        value = workflow()
        first, second = [op['document'] for op in value['operations']]
        first['scenes'] = [{'id': 'view', 'visible': {'A': {'opacity': 0.5}}}]
        first['definitions'] = {'x': {'$expr': 'extents(A).mid'}}
        second['definitions'] = {'x': {'$expr': 'extents(A).mid'}, 'copy': {
            '$document': '/scenes/0/visible/A/opacity', 'operation': 'first'}}
        output = self.rename(value, '/operations/0/document/nodes/0/id')
        self.assertEqual(output['operations'][1]['document']['nodes'], second['nodes'])
        self.assertEqual(output['operations'][1]['document']['definitions']['x'], second['definitions']['x'])
        self.assertEqual(output['operations'][1]['document']['definitions']['copy']['$document'], '/scenes/0/visible/2-left/opacity')

    def test_relative_pointer_moves_both_definition_site_and_destination(self):
        value = document()
        value['scenes'] = [{'id': 'view', 'visible': {'A': {'opacity': 0.5, 'copy': {'$document': './opacity'},
            'peer': {'$document': '../B/opacity'}}, 'B': {'opacity': 0.9, 'copy': {'$document': '../A/opacity'}}}}]
        output = self.rename(value)
        visible = output['scenes'][0]['visible']
        self.assertEqual(visible['2-left']['copy']['$document'], './opacity')
        self.assertEqual(visible['2-left']['peer']['$document'], '../B/opacity')
        self.assertEqual(visible['B']['copy']['$document'], '../2-left/opacity')
        from schemaxis.core.documents import resolve_document
        resolved = resolve_document(output)[0]
        self.assertEqual(resolved['scenes'][0]['visible']['B']['copy'], 0.5)
        self.assertEqual(resolved['scenes'][0]['visible']['2-left']['peer'], 0.9)

    def test_workflow_scoped_and_relative_cross_operation_document_markers(self):
        value = workflow()
        value['operations'][0]['document']['scenes'] = [{'id': 'view', 'visible': {'A': {'opacity': 0.5}}}]
        value['definitions'] = {'copy': {'$document': '/operations/0/document/scenes/0/visible/A/opacity', 'scope': 'workflow'}}
        value['operations'][1]['document']['definitions'] = {'copy': {
            '$document': '../../../0/document/scenes/0/visible/A/opacity'}}
        output = self.rename(value, '/operations/0/document/nodes/0/id')
        from schemaxis.adaptor_runtime import workflow_inputs
        resolved = workflow_inputs(output)
        self.assertEqual(resolved['definitions']['copy'], 0.5)
        self.assertEqual(resolved['operations'][1]['document']['definitions']['copy'], 0.5)

    def test_contract_valid_design_input_targets_and_parameters_remain_unchanged(self):
        from schemaxis import workflow_design
        body = workflow()
        body['operations'][0]['document']['nodes'][0]['options'] = {'radius': 1}
        value = workflow_design.create(body)
        value['ports'] = {'first': {'inputs': {'radius': {'target': '/nodes/0/options/radius', 'kind': 'value'}}}}
        value['workflow']['settings'] = {'size': 2}
        value['parameters'] = {'size': {'label': 'Size', 'kind': 'number', 'target': {'scope': 'workflow', 'pointer': '/settings/size'}}}
        workflow_design.validate(value)
        output = self.rename(value, '/workflow/operations/0/document/nodes/0/id')
        workflow_design.validate(output)
        self.assertEqual(output['ports'], value['ports'])
        self.assertEqual(output['parameters'], value['parameters'])
        version_one = {'version': 'schemaxis.workflow-design/1', 'workflow': body, 'connections': [], 'controllers': {}}
        workflow_design.validate(version_one)
        output = self.rename(version_one, '/workflow/operations/0/document/nodes/0/id')
        workflow_design.validate(output)

    def test_known_output_consumers_refuse_even_without_old_name_in_path(self):
        for marker in ({'$value': 'first', 'path': '/states/0/observations'}, {'$artifact': 'first', 'index': 0}):
            value = workflow(); value['operations'][1]['document']['settings'] = {'receipt': marker}
            self.refuses(value, 'UNSUPPORTED_IDENTITY_OUTPUT_REFERENCE', '/operations/0/document/nodes/0/id')
        for field, content in (
                ('ports', {'first': {'outputs': {'out': {'kind': 'value', 'valuePath': '/result'}}}}),
                ('outputs', {'out': {'operation': 'first', 'pointer': '/result'}}),
                ('connections', [{'source': 'first', 'target': 'second', 'valuePath': '/result'}])):
            value = {'version': 'schemaxis.workflow-design/2', 'workflow': workflow(), field: content}
            self.refuses(value, 'UNSUPPORTED_IDENTITY_OUTPUT_REFERENCE', '/workflow/operations/0/document/nodes/0/id')

    def test_indirect_owned_identity_follows_but_free_string_is_not_rewritten(self):
        value = document(); value['nodes'][1]['inputs']['input'] = {'$document': '/nodes/0/id'}
        output = self.rename(value)
        self.assertEqual(output['nodes'][1]['inputs'], value['nodes'][1]['inputs'])
        value['settings'] = {'source': 'A'}
        value['nodes'][1]['inputs']['input'] = {'$document': '/settings/source'}
        self.refuses(value, 'UNSUPPORTED_INDIRECT_IDENTITY')

    def test_destination_name_capture_refuses_all_typed_consumers(self):
        cases = [
            lambda d: d['nodes'][1]['inputs'].update(input='fresh'),
            lambda d: d.update(scenes=[{'id': 'view', 'geometry': ['fresh']}]),
            lambda d: d.update(scenes=[{'id': 'view', 'visible': {'fresh': {}}}]),
            lambda d: d.update(times={'source': 'fresh'}),
            lambda d: d.update(definitions={'box': {'$expr': 'extents(fresh).mid.x'}}),
            lambda d: d.update(definitions={'box': {'$observe': 'fresh', 'path': ['bounds']}}),
            lambda d: d.update(definitions={'s': {'$sample': 'fresh', 'field': 'p', 'association': 'POINTS', 'index': 0}}),
            lambda d: d.update(definitions={'r': {'$object': 'fresh'}}),
        ]
        for change in cases:
            value = document(); change(value)
            with self.subTest(value=value): self.refuses(value, 'IDENTITY_COLLISION', new='fresh')
        value = document(); value['settings'] = {'name': 'fresh'}
        value['nodes'][1]['inputs']['input'] = {'$document': '/settings/name'}
        self.refuses(value, 'IDENTITY_COLLISION', new='fresh')
        value = workflow(); value['operations'][1]['document']['definitions'] = {'later': {'$expr': 'extents(fresh)'}}
        value['operations'][0]['document']['settings'] = {'literal': 'fresh'}
        self.rename(value, '/operations/0/document/nodes/0/id', 'fresh')

    def test_cross_scope_borrowed_graph_identity_refuses_valid_workflows(self):
        from schemaxis.workflow import inspect_plan
        for marker in ({'$document': '/nodes/0/id', 'operation': 'first'},
                       {'$document': '../../../../../0/document/nodes/0/id'},
                       {'$document': '/operations/0/document/nodes/0/id', 'scope': 'workflow'}):
            value = workflow(); value['operations'][1]['document']['nodes'][1]['inputs']['input'] = marker
            inspect_plan(value)
            fault = self.refuses(value, 'UNSUPPORTED_IDENTITY_COMPOSITION', '/operations/0/document/nodes/0/id')
            self.assertEqual(fault.location, '$/operations/1/document/nodes/1/inputs/input')

    def test_borrowed_markers_bind_in_consumer_scope_and_refuse_inbound_and_outbound(self):
        from schemaxis.workflow import inspect_plan
        for outward in (False, True):
            value = workflow()
            observation = {'$observe': 'A', 'path': ['bounds']}
            first, second = [operation['document'] for operation in value['operations']]
            if outward:
                first['definitions'] = {'obs': observation}
                marker = {'$document': '/definitions/obs', 'operation': 'first'}
                consumer = second
            else:
                value['definitions'] = {'obs': observation}
                marker = {'$document': '/definitions/obs', 'scope': 'workflow'}
                consumer = first
            consumer['nodes'].append({'id': 'C', 'filter': 'sphere', 'options': {
                'centre': {'$call': 'boundsCentre', 'args': {'bounds': marker}}}})
            inspect_plan(value)
            self.refuses(value, 'UNSUPPORTED_IDENTITY_COMPOSITION', '/operations/0/document/nodes/0/id')
        for payload in ({'$sample': 'A', 'field': 'p', 'association': 'POINTS', 'index': 0},
                        {'$expr': 'extents(A).mid'}, {'nested': [{'$observe': 'A', 'path': ['bounds']}]},
                        {'$object': 'A'}):
            value = workflow(); value['definitions'] = {'payload': payload, 'alias': {'$document': './payload'}}
            value['operations'][0]['document']['definitions'] = {'borrowed': {'$document': '/definitions/alias', 'scope': 'workflow'}}
            self.refuses(value, 'UNSUPPORTED_IDENTITY_COMPOSITION', '/operations/0/document/nodes/0/id')

    def test_borrowed_collection_and_measurement_references_and_harmless_metadata(self):
        for field, value in (('geometry', ['A']), ('measurements', [{'node': 'A'}])):
            source = workflow(); source['definitions'] = {'borrowed': value}
            source['operations'][0]['document']['scenes'] = [{'id': 'view', field: {'$document': '/definitions/borrowed', 'scope': 'workflow'}}]
            expected = 'UNRESOLVED_IDENTITY_REFERENCE' if field == 'measurements' else 'UNSUPPORTED_IDENTITY_COMPOSITION'
            self.refuses(source, expected, '/operations/0/document/nodes/0/id')
        source = workflow(); first, second = [operation['document'] for operation in source['operations']]
        first['settings'] = {'unchangedString': 'A'}
        second['nodes'][1]['inputs']['input'] = {'$document': '/settings/unchangedString', 'operation': 'first'}
        first['definitions'] = {'metadata': {'$document': '/settings/label', 'operation': 'second'}}
        second['settings'] = {'label': 'fresh', 'unfilled': {'$fill': 'later'}}
        output = self.rename(source, '/operations/0/document/nodes/0/id', 'fresh')
        from schemaxis.adaptor_runtime import workflow_inputs
        self.assertEqual(workflow_inputs(output)['operations'][1]['document']['nodes'][1]['inputs']['input'], 'A')

    def test_borrowed_whole_nodes_and_outbound_nested_payload_are_refused(self):
        value = workflow()
        value['operations'][1]['document']['nodes'] = {'$document': '/nodes', 'operation': 'first'}
        from schemaxis.workflow import inspect_plan
        inspect_plan(value)
        self.refuses(value, 'UNSUPPORTED_IDENTITY_COMPOSITION', '/operations/0/document/nodes/0/id')
        for payload in ({'nested': [{'$observe': 'A', 'path': ['bounds']}]}, {'$expr': 'extents(A).mid'}):
            value = workflow(); value['operations'][0]['document']['definitions'] = {'payload': payload}
            value['operations'][1]['document']['definitions'] = {'borrowed': {'$document': '/definitions/payload', 'operation': 'first'}}
            self.refuses(value, 'UNSUPPORTED_IDENTITY_COMPOSITION', '/operations/0/document/nodes/0/id')
        # A destination-name alias cannot quietly bind through a workflow-level list.
        value = workflow(); value['definitions'] = {'geometry': ['fresh']}
        value['operations'][0]['document']['scenes'][0]['geometry'] = {'$document': '/definitions/geometry', 'scope': 'workflow'}
        self.refuses(value, 'IDENTITY_COLLISION', '/operations/0/document/nodes/0/id', 'fresh')

    def test_repeated_identical_inline_constructions_follow_compiler_contract(self):
        from schemaxis.context import compile_objects
        value = document()
        child = {'id': 'C', 'filter': 'surface', 'inputs': {'input': 'A'}}
        value['nodes'][1] = {'id': 'B', 'filter': 'group', 'inputs': {'input': [
            {'$create': copy.deepcopy(child)}, {'$create': copy.deepcopy(child)}]}}
        compile_objects(value)
        output = self.rename(value)
        compiled = compile_objects(output)
        self.assertEqual(next(n for n in compiled['nodes'] if n['id'] == 'C')['inputs']['input'], '2-left')
        for item in output['nodes'][1]['inputs']['input']:
            self.assertEqual(item['$create']['inputs']['input'], '2-left')
        value['nodes'][1]['inputs']['input'][1]['$create']['options'] = {'different': 1}
        self.refuses(value, 'AMBIGUOUS_IDENTITY_SCOPE')
        value = document(); value['nodes'][1]['inputs']['input'] = {'$create': copy.deepcopy(value['nodes'][0])}
        output = self.rename(value)
        self.assertEqual(output['nodes'][1]['inputs']['input']['$create']['id'], '2-left')
        compile_objects(output)

    def test_workflow_marker_errors_have_full_input_locations(self):
        for version in (None, 'schemaxis.workflow-design/1', 'schemaxis.workflow-design/2'):
            for marker, code in (({'$document': '/x', 'operation': 'missing'}, 'UNKNOWN_DOCUMENT_REFERENCE'),
                                 ({'$document': '/x', 'scope': 'bad'}, 'INVALID_DOCUMENT_REFERENCE'),
                                 ({'$document': '/x', 'extra': True}, 'UNKNOWN_ARGUMENT')):
                value = workflow(); value['operations'][1]['document']['settings'] = {'r': marker}
                prefix = '/workflow' if version else ''
                if version: value = {'version': version, 'workflow': value}
                with self.subTest(version=version, marker=marker):
                    fault = self.refuses(value, code, prefix + '/operations/0/document/nodes/0/id')
                    self.assertEqual(fault.location, '$' + prefix + '/operations/1/document/settings/r')

    def test_unresolved_borrowing_scope_has_structured_full_location(self):
        for version in (None, 'schemaxis.workflow-design/1', 'schemaxis.workflow-design/2'):
            for missing in (True, False):
                value = workflow()
                value['operations'][0]['document']['definitions'] = {'b': {'$expr': 'extents(A).mid.x'}}
                peer = value['operations'][1]['document']
                if missing: del peer['nodes']
                else: peer['nodes'] = {'$fill': 'nodes'}
                peer['definitions'] = {'b': {'$document': '/definitions/b', 'operation': 'first'}}
                prefix = '/workflow' if version else ''
                if version: value = {'version': version, 'workflow': value}
                with self.subTest(version=version, missing=missing):
                    fault = self.refuses(value, 'UNSUPPORTED_IDENTITY_COMPOSITION', prefix + '/operations/0/document/nodes/0/id')
                    self.assertEqual(fault.location, '$' + prefix + '/operations/1/document/definitions/b')
        value = workflow(); del value['operations'][1]['document']['nodes']
        value['operations'][0]['document']['settings'] = {'text': 'ordinary metadata'}
        value['operations'][1]['document']['settings'] = {'text': {'$document': '/settings/text', 'operation': 'first'}}
        self.rename(value, '/operations/0/document/nodes/0/id')

    def test_provenance_budget_precedes_address_materialization(self):
        from schemaxis import identity_rename as module
        from schemaxis.storage import encoded
        def make(key, count):
            return {'version': 'schemaxis/1', 'nodes': [{'id': 'A', 'filter': 'sphere'}],
                    'definitions': {key: [{'$observe': 'A'} for _ in range(count)]}}
        original = module.pointer
        produced = [0]
        def guarded(path):
            estimate = sum(1 + len(part) + part.count('~') + part.count('/') for part in path)
            produced[0] += estimate
            self.assertLess(produced[0], 2 * 1048576, 'Provenance constructed before aggregate refusal')
            return original(path)
        with patch.object(module, 'pointer', side_effect=guarded):
            fault = self.refuses(make('x' * 200000, 500), 'IDENTITY_LIMIT', new='B')
        self.assertEqual(fault.location, '$changedPointers')
        for key in ('x' * 1000, '/~' * 500, chr(0) * 1000, chr(0x1f680) * 250):
            value = make(key, 140)
            with self.subTest(key_length=len(key)):
                result = rename_identity(value, '/nodes/0/id', 'B', digest(value))
                self.assertEqual(result['changedPointers'], sorted(result['changedPointers']))
                self.assertEqual(len(result['changedPointers']), 141)
                self.assertLess(len(encoded({k: result[k] for k in ('changedPointers', 'identityChanges')})), 1048576)
                escaped_key = key.replace('~', '~0').replace('/', '~1')
                self.assertIn('/definitions/' + escaped_key + '/0/$observe', result['changedPointers'])
        fault = self.refuses(make(chr(0) * 1000, 180), 'IDENTITY_LIMIT', new='B')
        self.assertEqual(fault.location, '$changedPointers')
        value = {'version': 'schemaxis/1', 'nodes': [{'id': 'A' * 600000, 'filter': 'sphere'}]}
        fault = self.refuses(value, 'IDENTITY_LIMIT', new='B' * 600000)
        self.assertEqual(fault.location, '$identityChanges')

    def test_pointer_and_json_bounds(self):
        for path in ('nodes/0/id', '/nodes/00/id', '/nodes/~2/id', '/nodes/0/filter'):
            with self.subTest(path=path), self.assertRaises(SchemaxisError):
                rename_identity(document(), path, 'new', digest(document()))
        for invalid in ({'version': 'schemaxis/1', 'bad': float('nan')}, {'version': 'schemaxis/1', 3: 'bad'}):
            with self.assertRaises(SchemaxisError): rename_identity(invalid, '/nodes/0/id', 'new', 'unused')

    def test_expanded_result_is_bounded_before_canonical_materialization(self):
        value = {'version': 'schemaxis/1', 'nodes': [{'id': 'A', 'filter': 'sphere'}],
                 'scenes': [{'id': 'view', 'geometry': ['A'] * 2048}]}
        before = copy.deepcopy(value)
        # Only about two MiB if fully encoded, but the guard proves no oversized
        # candidate is passed to storage.digest/encoded even at larger counts.
        from schemaxis import storage
        original = storage.encoded
        def guarded(candidate):
            self.assertEqual(candidate, before, 'Oversized result reached canonical materialization')
            return original(candidate)
        expected = digest(value)
        with patch.object(storage, 'encoded', side_effect=guarded), self.assertRaises(SchemaxisError) as caught:
            rename_identity(value, '/nodes/0/id', 'N' * 1024, expected)
        self.assertEqual(caught.exception.fault.code, 'IDENTITY_LIMIT')
        self.assertEqual(value, before)
        value = {'version': 'schemaxis/1', 'nodes': [{'id': 'A', 'filter': 'sphere'}],
                 'settings': {'x': {'$expr': ' + '.join(['extents(A).mid.x'] * 20)}}}
        before = copy.deepcopy(value)
        expected = digest(value)
        with patch.object(storage, 'encoded', side_effect=guarded), self.assertRaises(SchemaxisError) as expanded:
            rename_identity(value, '/nodes/0/id', 'N' * 4000, expected)
        self.assertEqual(expanded.exception.fault.code, 'UNRESOLVED_IDENTITY_EXPRESSION')
        self.assertEqual(expanded.exception.fault.observed['expressionCode'], 'EXPR_LIMIT')
        self.assertEqual(value, before)
        from schemaxis.identity_rename import bounded
        with self.assertRaises(SchemaxisError) as escaped:
            bounded({'value': chr(0) * 200000})
        self.assertEqual(escaped.exception.fault.code, 'IDENTITY_LIMIT')


class PolicyAdmission(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider, cls.route = registry.resolve(document())
        cls.data = registry.binding(cls.route['authoringReferences'])()
        cls.schema = registry.binding(cls.route['schema'])()
        cls.declarations = registry.declarations(cls.provider)

    def test_real_policy_matches_schema_and_is_data(self):
        result = validate(self.data, self.schema, self.declarations)
        json.dumps(result, allow_nan=False)
        self.assertEqual(len(result['projection']['node']['operations']), 601)

    def test_new_declared_port_is_automatically_projected(self):
        declarations, schema = copy.deepcopy(self.declarations), copy.deepcopy(self.schema)
        declarations['sphere']['inputs']['newPort'] = {'multiple': True, 'kind': 'data'}
        for node in schema['properties']['nodes']['items']['oneOf']:
            if node['properties']['filter']['const'] == 'sphere':
                node['properties']['inputs']['properties']['newPort'] = {'type': 'array', 'items': {'type': 'string'}}
        result = validate(self.data, schema, declarations)
        self.assertEqual(result['projection']['node']['operations']['sphere']['newPort'], {'multiple': True, 'kind': 'data'})

    def test_invalid_policy_and_schema_mismatch_are_structured(self):
        mutations = [lambda p: p.update(extra=True), lambda p: p.update(version='bad'),
                     lambda p: p['identities'][0]['nameSchema'].update(pattern='^[a-z]+$'),
                     lambda p: p['references'][0].update(path=['missing']),
                     lambda p: p['references'][0].update(shape='keys'),
                     lambda p: p['identities'][0].update(form='map-key'),
                     lambda p: p['references'][0].update(identity=[]),
                     lambda p: p['markers'][0].update(identity={}),
                     lambda p: p['expressions'].update(extents=[])]
        for mutation in mutations:
            value = copy.deepcopy(self.data); mutation(value)
            with self.subTest(value=value), self.assertRaises(SchemaxisError) as caught:
                validate(value, self.schema, self.declarations)
            self.assertEqual(caught.exception.fault.code, 'INVALID_REFERENCE_POLICY')

    def test_unsupported_identity_constraints_fail_closed_at_name_and_ancestors(self):
        variants = lambda schema: schema['properties']['nodes']['items']['oneOf']
        additions = [{'const': 'A'}, {'not': {'const': 'B'}}, {'allOf': [{'enum': ['A']}]},
                     {'format': 'custom'}, {'oneOf': [{'type': 'string'}, {'type': 'string'}]}]
        mutations = [lambda schema, extra=extra: [node['properties']['id'].update(extra) for node in variants(schema)]
                     for extra in additions]
        mutations += [lambda schema: variants(schema)[0].update(allOf=[{'properties': {'id': {'const': 'A'}}}]),
                      lambda schema: schema.update(**{'if': {'properties': {'version': {'const': 'schemaxis/1'}}},
                                                       'then': {'properties': {'nodes': {'maxItems': 0}}}}),
                      lambda schema: schema['properties']['nodes']['items'].update(not_implemented=True)]
        for change in mutations:
            schema = copy.deepcopy(self.schema); change(schema)
            with self.subTest(change=change), self.assertRaises(SchemaxisError) as caught:
                validate(self.data, schema, self.declarations)
            self.assertEqual(caught.exception.fault.code, 'INVALID_REFERENCE_POLICY')
            self.assertEqual(caught.exception.fault.location, '$policy.identities/0/nameSchema')
            actual_binding = registry.binding
            with patch.object(registry, 'binding', side_effect=lambda name: (lambda: schema) if name == self.route['schema'] else actual_binding(name)), \
                    self.assertRaises(SchemaxisError) as full:
                rename_identity(document(), '/nodes/0/id', 'B-new', digest(document()))
            self.assertEqual(full.exception.fault.code, 'INVALID_REFERENCE_POLICY')
        schema = copy.deepcopy(self.schema)
        for node in variants(schema):
            node['properties']['id'].update(description='A harmless explanation', title='Identity', examples=['A'])
        validate(self.data, schema, self.declarations)
        # Local references must retain both their destination constraints and sibling constraints.
        schema = copy.deepcopy(self.schema)
        schema.setdefault('$defs', {})['restrictedIdentity'] = {**self.data['identities'][0]['nameSchema'], 'const': 'A'}
        variants(schema)[0]['properties']['id'] = {'$ref': '#/$defs/restrictedIdentity'}
        with self.assertRaises(SchemaxisError): validate(self.data, schema, self.declarations)
        variants(schema)[0]['properties']['id'] = {'$ref': '#/$defs/restrictedIdentity', 'not': {'const': 'B'}}
        with self.assertRaises(SchemaxisError): validate(self.data, schema, self.declarations)
        schema = copy.deepcopy(self.schema)
        del variants(schema)[0]['properties']['id']
        with self.assertRaises(SchemaxisError): validate(self.data, schema, self.declarations)

    def test_understood_name_constraints_are_enforced_in_full_preview(self):
        from schemaxis.identity_policy import accepts_name
        policy, schema = copy.deepcopy(self.data), copy.deepcopy(self.schema)
        name_schema = {'type': 'string', 'pattern': '^[A-Z]+$', 'minLength': 1, 'maxLength': 2, 'enum': ['A', 'B']}
        policy['identities'][0]['nameSchema'] = name_schema
        for node in schema['properties']['nodes']['items']['oneOf']:
            node['properties']['id'] = dict(name_schema)
        admitted = validate(policy, schema, self.declarations)
        self.assertTrue(accepts_name('B', name_schema))
        for bad in ('C', 'a', 'AAA', ''): self.assertFalse(accepts_name(bad, name_schema))
        value = {'version': 'schemaxis/1', 'nodes': [{'id': 'A', 'filter': 'sphere'}]}
        with patch('schemaxis.identity_rename.for_route', return_value=admitted):
            self.assertEqual(rename_identity(value, '/nodes/0/id', 'B', digest(value))['input']['nodes'][0]['id'], 'B')
            with self.assertRaises(SchemaxisError): rename_identity(value, '/nodes/0/id', 'C', digest(value))

    def test_consumer_constraints_cannot_be_discarded_by_shape_admission(self):
        from schemaxis.identity_policy import schema_nodes, ARRAY
        mutations = [
            (['times', 'source'], lambda node: node.update(const='A')),
            (['scenes', ARRAY, 'geometry'], lambda node: node['items'].update(enum=['A'])),
            (['scenes', ARRAY, 'visible'], lambda node: node.update(propertyNames={'type': 'string', 'pattern': '^A$'})),
            (['scenes', ARRAY, 'appearances', ARRAY], lambda node: node.update(propertyNames={'type': 'string', 'enum': ['A']})),
            (['scenes', ARRAY, 'visible'], lambda node: node.update(required=['A'])),
            (['scenes', ARRAY, 'visible'], lambda node: node.update(properties={'B': {'type': 'null'}})),
            (['scenes', ARRAY, 'measurements', ARRAY], lambda node: node.update(allOf=[{'properties': {'node': {'const': 'A'}}}])),
            (['nodes', ARRAY, 'inputs'], lambda node: node.update(allOf=[{'properties': {'input': {'const': 'A'}}}])),
        ]
        schemas = []
        for path, mutation in mutations:
            schema = copy.deepcopy(self.schema)
            mutation(schema_nodes(schema, path)[0]); schemas.append(schema)
        schema = copy.deepcopy(self.schema)
        ports = schema_nodes(schema, ['nodes', ARRAY, 'inputs'])
        first_ports = next(node['properties'] for node in ports if node.get('properties'))
        first_ports[next(iter(first_ports))] = {'type': 'string', 'const': 'A'}
        schemas.append(schema)
        schema = copy.deepcopy(self.schema)
        node_port = next(node for node in schema_nodes(schema, ['nodes', ARRAY, 'inputs', 'input']) if 'node' in node.get('properties', {}))
        node_port['properties']['node'].update(enum=['A'])
        schemas.append(schema)
        schema = copy.deepcopy(self.schema)
        resource = next(node for node in schema_nodes(schema, ['scenes', ARRAY, 'exports', ARRAY, 'resources']) if node.get('properties'))
        next(iter(resource['properties'].values())).update(const='A'); schemas.append(schema)
        schema = copy.deepcopy(self.schema)
        schema['$defs']['restrictedReference'] = {'type': 'string', 'not': {'const': 'B'}}
        source = schema_nodes(schema, ['times', 'source'])[0]
        source.clear(); source['$ref'] = '#/$defs/restrictedReference'
        schemas.append(schema)
        for index, schema in enumerate(schemas):
            with self.subTest(case=index):
                with self.assertRaises(SchemaxisError) as caught: validate(self.data, schema, self.declarations)
                self.assertEqual(caught.exception.fault.code, 'INVALID_REFERENCE_POLICY')
                self.assertTrue(caught.exception.fault.location.startswith('$policy.'))
                binding = registry.binding
                value = document(); before = copy.deepcopy(value)
                with patch.object(registry, 'binding', side_effect=lambda name: (lambda: schema) if name == self.route['schema'] else binding(name)), self.assertRaises(SchemaxisError) as full:
                    rename_identity(value, '/nodes/0/id', 'newName', digest(value))
                self.assertEqual(full.exception.fault.code, 'INVALID_REFERENCE_POLICY')
                self.assertEqual(value, before)
        schema = copy.deepcopy(self.schema)
        schema_nodes(schema, ['scenes', ARRAY, 'visible'])[0]['propertyNames'] = dict(self.data['identities'][0]['nameSchema'])
        schema_nodes(schema, ['times', 'source'])[0]['description'] = 'Explanatory consumer annotation'
        validate(self.data, schema, self.declarations)

    def test_reachable_marker_schemas_preserve_consumer_constraints(self):
        names = self.data['identities'][0]['nameSchema']
        cases = []
        for marker in ('$observe', '$sample', '$object'):
            for restriction in ({'const': 'A'}, {'enum': ['A']}, {'allOf': [{'const': 'A'}]}):
                schema = copy.deepcopy(self.schema)
                schema['properties']['probe'] = {'type': 'object', 'properties': {marker: {**names, **restriction}}}
                cases.append(schema)
        for marker in ('$observe', '$sample'):
            schema = copy.deepcopy(self.schema)
            variant = next(node for node in schema['$defs']['runtime']['anyOf'] if marker in node.get('properties', {}))
            variant['properties'][marker] = {'$ref': '#/$defs/restrictedMarker'}
            schema['$defs']['restrictedMarker'] = {**names, 'const': 'A'}
            cases.append(schema)
        schema = copy.deepcopy(self.schema)
        schema['properties']['probe'] = {'$ref': '#/$defs/markerCycle'}
        schema['$defs']['markerCycle'] = {'type': 'object', 'properties': {'again': {'$ref': '#/$defs/markerCycle'}, '$object': names},
                                        'allOf': [{'properties': {'$object': {'const': 'A'}}}]}
        cases.append(schema)
        for index, schema in enumerate(cases):
            with self.subTest(case=index):
                with self.assertRaises(SchemaxisError) as caught: validate(self.data, schema, self.declarations)
                self.assertEqual(caught.exception.fault.code, 'INVALID_REFERENCE_POLICY')
                self.assertTrue(caught.exception.fault.location.startswith('$policy.markers/'))
                binding = registry.binding
                value = document(); value['probe'] = {'$observe': 'A'}
                before = copy.deepcopy(value)
                with patch.object(registry, 'binding', side_effect=lambda name: (lambda: schema) if name == self.route['schema'] else binding(name)), self.assertRaises(SchemaxisError) as full:
                    rename_identity(value, '/nodes/0/id', 'B-new', digest(value))
                self.assertEqual(full.exception.fault.code, 'INVALID_REFERENCE_POLICY')
                self.assertEqual(value, before)
        # Real runtimeSchema hook data is included by the owning route schema.
        from schemaxis.adaptors.paraview import schema as pv_schema
        variants = pv_schema.runtime_variants()
        variants[0]['properties']['$sample'] = {**names, 'const': 'A'}
        with patch.object(pv_schema, 'runtime_variants', return_value=variants), self.assertRaises(SchemaxisError):
            for_route(self.provider, self.route)
        schema = copy.deepcopy(self.schema)
        schema['properties']['probe'] = {'$ref': '#/$defs/markerCycle'}
        schema['$defs']['markerCycle'] = {'type': 'object', 'properties': {
            'again': {'$ref': '#/$defs/markerCycle'}, '$object': {**names, 'description': 'Compatible marker'}}}
        fake = {'type': 'object', 'properties': {'$observe': {'type': 'string', 'const': 'A'}}}
        schema['default'] = fake
        schema['examples'] = [fake]
        schema['$defs']['unusedMarker'] = fake
        admitted = validate(self.data, schema, self.declarations)
        self.assertEqual(len(admitted['projection']['node']['operations']), 601)
        self.assertEqual(len(admitted['projection']['node']['writers']), 44)

    def test_wildcard_marker_ownership_and_string_constraints(self):
        names = self.data['identities'][0]['nameSchema']
        narrow = {**names, 'const': 'A'}
        cases = [
            {'type': 'object', 'patternProperties': {r'^\$observe$': narrow}},
            {'type': 'object', 'additionalProperties': narrow},
            {'type': 'object', 'properties': {'$observe': names}, 'patternProperties': {r'^\$observe$': narrow}},
            {'type': 'object', 'patternProperties': {r'^\$': names, 'observe$': narrow}},
            {'type': 'object', 'patternProperties': {'[': names}},
            {'type': 'object', 'patternProperties': {r'^\u0024observe$': narrow}},
            {'type': 'object', 'additionalProperties': {'$ref': '#/$defs/narrowWildcard'}},
            {'type': 'object', 'additionalProperties': {'anyOf': [{'type': 'number'}, narrow]}},
            {'type': 'object', 'additionalProperties': {'oneOf': [names, names]}},
            {'type': 'object', 'additionalProperties': True, 'const': {'$observe': 'A'}},
            {'type': 'object', 'const': {'$observe': 'A'}},
            {'type': 'object', 'const': {'nested': {'$observe': 'A'}}},
            {'type': 'object', 'enum': [{'$observe': 'A'}]},
        ]
        for index, probe in enumerate(cases):
            schema = copy.deepcopy(self.schema)
            schema['properties']['probe'] = probe
            schema['$defs']['narrowWildcard'] = narrow
            with self.subTest(case=index):
                with self.assertRaises(SchemaxisError) as caught: validate(self.data, schema, self.declarations)
                self.assertEqual(caught.exception.fault.code, 'INVALID_REFERENCE_POLICY')
                self.assertTrue(caught.exception.fault.location.startswith('$policy.markers'))
                binding = registry.binding
                value = document(); value['probe'] = {'$observe': 'A'}
                before = copy.deepcopy(value)
                with patch.object(registry, 'binding', side_effect=lambda name: (lambda: schema) if name == self.route['schema'] else binding(name)), self.assertRaises(SchemaxisError) as full:
                    rename_identity(value, '/nodes/0/id', 'B-new', digest(value))
                self.assertEqual(full.exception.fault.code, 'INVALID_REFERENCE_POLICY')
                self.assertEqual(value, before)
        controls = [
            {'type': 'object', 'patternProperties': {r'^\$': names, 'observe$': {'type': 'string'}}},
            {'type': 'object', 'additionalProperties': names},
            {'type': 'object', 'properties': {'$observe': names, '$sample': names, '$object': names}, 'additionalProperties': narrow},
            {'type': 'object', 'patternProperties': {r'^\$': names}, 'additionalProperties': narrow},
            {'type': 'object', 'patternProperties': {'^ordinary$': narrow}},
            {'type': 'object', 'additionalProperties': {'type': 'number', 'const': 7}},
            {'type': 'object', 'additionalProperties': {'type': 'object', 'properties': {'label': {'type': 'string'}}}},
            {'type': 'object', 'additionalProperties': {'anyOf': [{'type': 'number'}, names]}},
            {'type': 'object', 'additionalProperties': {'oneOf': [{'type': 'object'}, names]}},
            {'type': 'object', 'additionalProperties': {'$ref': '#/$defs/json'}},
            {'type': 'object', 'patternProperties': {r'^\$': False, 'observe$': narrow}},
            {'type': 'object', 'additionalProperties': True},
            {'type': 'object'},
            {'type': 'object', 'additionalProperties': False},
            {'type': 'object', 'const': {'ordinary': 'A'}},
            {'type': 'object', 'enum': [{'ordinary': 'A'}]},
        ]
        for index, probe in enumerate(controls):
            schema = copy.deepcopy(self.schema); schema['properties']['probe'] = probe
            with self.subTest(control=index):
                validate(self.data, schema, self.declarations)
                if index in (0, 1, 2, 3, 4, 7, 8, 9, 11, 12):
                    binding = registry.binding
                    value = document(); value['probe'] = {'$observe': 'A'}
                    with patch.object(registry, 'binding', side_effect=lambda name: (lambda: schema) if name == self.route['schema'] else binding(name)):
                        result = rename_identity(value, '/nodes/0/id', 'B-new', digest(value))
                    self.assertEqual(result['input']['probe']['$observe'], 'B-new')
                    try:
                        from jsonschema import Draft202012Validator
                    except ImportError:
                        pass  # Full preview assertions above do not need this optional oracle.
                    else:
                        validator = Draft202012Validator({'$defs': schema['$defs'], **probe})
                        validator.validate(value['probe'])
                        validator.validate(result['input']['probe'])

    def test_marker_ancestors_allow_presence_only_alternatives(self):
        names = self.data['identities'][0]['nameSchema']
        schema = copy.deepcopy(self.schema)
        schema['properties']['probe'] = {'type': 'object', 'properties': {'$observe': names},
            'oneOf': [{'required': ['left'], 'not': {'required': ['right']}},
                      {'required': ['right'], 'not': {'required': ['left']}}]}
        validate(self.data, schema, self.declarations)
        schema['properties']['probe']['oneOf'][0]['properties'] = {'$observe': {'const': 'A'}}
        with self.assertRaises(SchemaxisError) as caught: validate(self.data, schema, self.declarations)
        self.assertEqual(caught.exception.fault.code, 'INVALID_REFERENCE_POLICY')

    def test_invalid_returned_policy_data_does_not_quarantine_plugin(self):
        from types import SimpleNamespace
        root = Path(__file__).resolve().parents[2]
        entry = SimpleNamespace(name='fixtureplugin', value='schemaxis_fixture_plugin', group=registry.GROUP,
                                dist=SimpleNamespace(name='schemaxis-fixture-plugin'))
        with patch.object(sys, 'path', [str(root / 'tests/fixtures/plugin_adaptor'), *sys.path]):
            admitted = registry.load_registry(plugins=[entry], strict=True)['fixtureplugin']
            route = admitted['routes'][admitted['version']]
            route['authoringReferences'] = admitted['package'] + ':successful_policy'
            malformed = {**self.data, 'identities': []}
            binding = registry.binding
            with patch.dict(registry.ADAPTORS, {'fixtureplugin': admitted}), \
                    patch.object(registry, 'PLUGIN_FAULTS', []), patch.object(registry, '_EXCLUDED', {}), \
                    patch.object(registry, 'binding', side_effect=lambda name: (lambda: malformed) if name == route['authoringReferences'] else binding(name)):
                before = copy.deepcopy(registry.ADAPTORS)
                with self.assertRaises(SchemaxisError) as caught: for_route('fixtureplugin', route)
                self.assertEqual(caught.exception.fault.code, 'INVALID_REFERENCE_POLICY')
                self.assertEqual(caught.exception.fault.location, '$policy.identities')
                self.assertEqual(registry.ADAPTORS, before)
                self.assertEqual(registry.PLUGIN_FAULTS, [])
                self.assertEqual(registry._EXCLUDED, {})

    def test_unaudited_route_is_unsupported(self):
        value = {'version': 'schemaxis.freecad/1', 'nodes': [{'id': 'A', 'filter': 'box'}]}
        with self.assertRaises(SchemaxisError) as caught:
            rename_identity(value, '/nodes/0/id', 'new', digest(value))
        self.assertEqual(caught.exception.fault.code, 'UNSUPPORTED_IDENTITY')

    def test_plugin_cannot_bind_outside_its_package(self):
        root = Path(__file__).resolve().parents[2]
        manifest = json.loads((root / 'tests/fixtures/plugin_adaptor/schemaxis_fixture_plugin/adaptor.json').read_text())
        manifest['routes'][manifest['version']]['authoringReferences'] = 'schemaxis.adaptors.paraview.authoring_references:policy'
        claims = {'versions': set(), 'sections': set(), 'flags': {}, 'names': {}}
        with self.assertRaisesRegex(ValueError, 'bindings must belong'):
            registry._admit(manifest, manifest['id'], 'schemaxis_fixture_plugin.', claims)

    def test_failing_plugin_binding_retains_existing_quarantine_boundary(self):
        import warnings
        from types import SimpleNamespace
        root = Path(__file__).resolve().parents[2]
        fixture_path = str(root / 'tests/fixtures/plugin_adaptor')
        entry = SimpleNamespace(name='fixtureplugin', value='schemaxis_fixture_plugin',
                                group=registry.GROUP, dist=SimpleNamespace(name='schemaxis-fixture-plugin'))
        with patch.object(sys, 'path', [fixture_path, *sys.path]):
            admitted = registry.load_registry(plugins=[entry], strict=True)['fixtureplugin']
            route = admitted['routes'][admitted['version']]
            route['authoringReferences'] = admitted['package'] + '.missing:policy'
            with patch.dict(registry.ADAPTORS, {'fixtureplugin': admitted}), \
                    patch.object(registry, 'PLUGIN_FAULTS', []), patch.object(registry, '_EXCLUDED', {}), \
                    warnings.catch_warnings():
                warnings.simplefilter('ignore', registry.AdaptorPluginWarning)
                with self.assertRaises(SchemaxisError) as caught:
                    for_route('fixtureplugin', route)
                self.assertNotIn('fixtureplugin', registry.ADAPTORS)
                self.assertIn('plugin', caught.exception.fault.message)

    def test_import_and_preview_do_not_load_native_modules_or_sessions(self):
        root = Path(__file__).resolve().parents[2]
        script = '''
import importlib.abc, sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in {'paraview','vtk','vtkmodules','bpy','FreeCAD'} or name in {'schemaxis.console_session','schemaxis.live_data'}:
            raise AssertionError('forbidden import: '+name)
sys.meta_path.insert(0, Guard())
from schemaxis.identity_rename import rename_identity
from schemaxis.storage import digest
value={'version':'schemaxis/1','nodes':[{'id':'A','filter':'sphere'}]}
assert rename_identity(value,'/nodes/0/id','B',digest(value))['input']['nodes'][0]['id']=='B'
'''
        result = subprocess.run([sys.executable, '-c', script], cwd=root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
