# Copyright (C) 2026 David L F Gaden
"""Workflow arrows remain persisted, bounded, and distinct from executable cycles."""
import copy
import sys
import unittest
from unittest.mock import patch

from schemaxis import workflow, workflow_design as design
from schemaxis.adaptor_runtime import workflow_inputs
from schemaxis.core.faults import SchemaxisError
from schemaxis.workflow_loop_controls import catalogue


def body(*identities):
    return {'version': 'schemaxis.workflow/1', 'operations': [
        {'id': identity, 'document': {'version': 'schemaxis.octave/1', 'nodes': [
            {'id': 'data', 'filter': 'sequence', 'options': {'start': 0, 'stop': 4, 'count': 5}}],
            'outputs': ['data']}} for identity in identities]}


def connection(source='a', target='b', identity='link', pointer='/nodes/0/options/stop', **extra):
    return {'id': identity, 'source': source, 'target': target, 'targetPointer': pointer,
            'kind': 'value', 'artifactIndex': 0, 'valuePath': '/rows/0/0', **extra}


class WorkflowDesignTests(unittest.TestCase):
    def fault(self, code, action):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code)
        self.assertTrue(caught.exception.fault.location)

    def loop(self):
        value = design.connect(design.create(body('a', 'b')), connection())
        return design.connect(value, connection('b', 'a', 'back'))

    def config(self):
        return catalogue()[1]['defaults']

    def test_empty_design_is_savable_but_not_executable(self):
        value = design.create()
        view = design.project(value)
        self.assertEqual(view['status'], 'empty')
        self.assertEqual(view['nodes'], [])
        self.assertFalse(view['executionAvailable'])
        self.fault('EMPTY_WORKFLOW', lambda: design.compile(value))

    def test_parameters_can_precede_operations_without_becoming_executable(self):
        value = design.create()
        value['workflow']['dimensions'] = {'distance': 10}
        value['parameters'] = {'distance': {'label': 'Distance', 'kind': 'number', 'units': 'mm',
            'default': 10, 'target': {'scope': 'workflow', 'pointer': '/dimensions/distance'}}}
        view = design.validate(value)
        self.assertEqual(view['status'], 'empty')
        self.assertFalse(view['compilationAvailable'])
        self.assertFalse(view['templateExportAvailable'])
        self.assertEqual(view['parameters']['distance']['units'], 'mm')
        self.fault('EMPTY_WORKFLOW', lambda: design.compile(value))
        value['workflow']['dimensions']['distance'] = 'wrong type'
        self.fault('INVALID_PARAMETER', lambda: design.validate(value))

    def test_values_before_operations_validate_sweeps_and_defer_placeholders(self):
        value = design.create()
        value['workflow']['definitions'] = {'diameter': {'$expr': {'op': 'multiply', 'args': [2, {'$fill': 'radius'}]}}}
        self.assertEqual(design.validate(value)['status'], 'unfilled')
        del value['workflow']['definitions']
        value['workflow']['axes'] = [{'name': 'distance', 'values': []}]
        self.fault('EMPTY_AXIS', lambda: design.validate(value))
        value['workflow']['axes'][0]['values'] = [1, 2, 3]
        self.assertEqual(design.validate(value)['status'], 'empty')

    def test_reentrant_adaptor_visits_are_not_feedback(self):
        value = design.connect(design.create(body('a', 'b', 'aAgain')), connection())
        value = design.connect(value, connection('b', 'aAgain', 'next'))
        view = design.project(value)
        self.assertEqual([node['provider'] for node in view['nodes']], ['octave'] * 3)
        self.assertEqual(view['loops'], [])
        self.assertEqual(view['status'], 'ready')
        self.assertTrue(view['compilationAvailable'])
        self.assertFalse(view['executionAvailable'])

    def test_numeric_arrow_preserves_baseline_and_materialises_existing_reference(self):
        baseline = body('a', 'b')
        value = design.create(baseline)
        changed = design.connect(value, connection())
        self.assertEqual(value['connections'], [])
        self.assertEqual(changed['workflow'], baseline)
        materialised = design.compile(changed)
        expected = copy.deepcopy(baseline)
        expected['operations'][1]['document']['nodes'][0]['options']['stop'] = {
            '$value': 'a', 'artifact': 0, 'path': '/rows/0/0'}
        self.assertEqual(materialised, expected)
        self.assertEqual(design.validate(changed, draft=False), workflow.inspect_plan(expected))
        self.assertEqual(design.disconnect(changed, 'link'), value)
        materialised['operations'][0]['id'] = 'changed'
        self.assertEqual(changed['workflow'], baseline)

    def test_artifact_arrow_can_override_and_restore_baseline_reference(self):
        from schemaxis.workflow_authoring import example
        baseline = example()
        alternate = copy.deepcopy(baseline['operations'][0])
        alternate['id'] = 'alternate'
        baseline['operations'].insert(1, alternate)
        value = design.create(baseline)
        arrow = {'id': 'file', 'source': 'alternate', 'target': 'scaled',
                 'targetPointer': '/nodes/0/options/file', 'kind': 'artifact', 'artifactIndex': 0}
        changed = design.connect(value, arrow)
        view = design.project(changed)
        self.assertEqual(len(view['edges']), 1)
        self.assertEqual(view['edges'][0]['source'], 'alternate')
        self.assertEqual(view['edges'][0]['pointer'], '/connections/0')
        self.assertTrue(view['edges'][0]['removable'])
        restored = design.disconnect(changed, 'file')
        self.assertEqual(restored, value)
        edge = design.project(restored)['edges'][0]
        self.assertEqual(edge['source'], 'samples')
        self.assertFalse(edge['removable'])
        self.fault('INVALID_CONNECTION', lambda: design.disconnect(restored, edge['id']))

    def test_closing_arrow_creates_loop_and_configuration_never_enables_execution(self):
        value = self.loop()
        before = copy.deepcopy(value)
        view = design.project(value)
        self.assertEqual(view['status'], 'feedback-configuration-required')
        self.assertEqual(len(view['loops']), 1)
        loop = view['loops'][0]
        self.assertEqual(loop['members'], ['a', 'b'])
        self.assertEqual(set(loop['edgeIds']), {'link', 'back'})
        changed = design.configure(value, loop['id'], self.config())
        self.assertEqual(value, before)
        configured = design.project(changed)
        self.assertEqual(configured['status'], 'feedback-execution-unavailable')
        self.assertEqual(configured['loops'][0]['controller'], self.config())
        self.fault('FEEDBACK_EXECUTION_UNAVAILABLE', lambda: design.compile(value))
        self.fault('FEEDBACK_EXECUTION_UNAVAILABLE', lambda: design.compile(changed))
        opened = design.disconnect(changed, 'back')
        self.assertEqual(opened['controllers'], {})
        self.assertEqual(design.project(opened)['loops'], [])

    def test_self_loop_is_feedback(self):
        value = design.connect(design.create(body('a')), connection('a', 'a'))
        self.assertEqual(design.project(value)['loops'][0]['members'], ['a'])
        self.fault('FEEDBACK_EXECUTION_UNAVAILABLE', lambda: design.compile(value))

    def test_multiple_cycles_merge_as_one_strongly_connected_group(self):
        value = design.create(body('a', 'b', 'c', 'd'))
        for arrow in [connection('a', 'b', 'ab'), connection('b', 'a', 'ba'),
                      connection('c', 'd', 'cd'), connection('d', 'c', 'dc')]:
            value = design.connect(value, arrow)
        view = design.project(value)
        self.assertEqual([loop['members'] for loop in view['loops']], [['a', 'b'], ['c', 'd']])
        for loop in view['loops']:
            value = design.configure(value, loop['id'], self.config())
        value = design.connect(value, connection('b', 'c', 'bc', '/nodes/0/options/start'))
        self.assertEqual(len(value['controllers']), 2)
        value = design.connect(value, connection('d', 'a', 'da', '/nodes/0/options/start'))
        self.assertEqual(value['controllers'], {})
        self.assertEqual(design.project(value)['loops'][0]['members'], ['a', 'b', 'c', 'd'])

    def test_loop_identity_is_stable_but_invalidates_changed_equations_or_internal_wiring(self):
        value = self.loop()
        identity = design.project(value)['loops'][0]['id']
        changed = copy.deepcopy(value)
        changed['connections'].reverse()
        changed['connections'][0]['id'] = 'renamed'
        self.assertEqual(design.project(changed)['loops'][0]['id'], identity)
        source = changed['connections'][0]['from']  # Version 2: the value path belongs to the output port.
        changed['ports'][source['operation']]['outputs'][source['port']]['valuePath'] = '/rows/1/0'
        self.assertNotEqual(design.project(changed)['loops'][0]['id'], identity)
        configured = design.configure(value, identity, self.config())
        changed = copy.deepcopy(configured)
        changed['workflow']['operations'][0]['document']['nodes'][0]['options']['start'] = 1
        self.fault('INVALID_FEEDBACK_CONTROLLER', lambda: design.project(changed))
        changed = copy.deepcopy(configured)
        changed['workflow']['dimensions'] = {'scale': 2}
        self.fault('INVALID_FEEDBACK_CONTROLLER', lambda: design.project(changed))

    def test_config_requires_current_loop_and_valid_supported_algorithm(self):
        value = design.create(body('a', 'b'))
        self.fault('INVALID_FEEDBACK_CONTROLLER', lambda: design.configure(value, 'none', self.config()))
        value['controllers']['none'] = self.config()
        self.fault('INVALID_FEEDBACK_CONTROLLER', lambda: design.validate(value))
        looped = self.loop()
        identity = design.project(looped)['loops'][0]['id']
        self.fault('FEEDBACK_ALGORITHM_UNAVAILABLE', lambda: design.configure(looped, identity, {'algorithm': 'stsc'}))
        self.fault('INVALID_FEEDBACK_CONFIG', lambda: design.configure(looped, identity, {**self.config(), 'relaxation': 0}))

    def test_forward_arrow_reorders_dag_stably(self):
        value = design.connect(design.create(body('a', 'b', 'c')), connection('c', 'a'))
        self.assertEqual([operation['id'] for operation in design.compile(value)['operations']], ['b', 'c', 'a'])

    def test_compile_preserves_shared_absolute_document_reference_after_reorder(self):
        baseline = body('a', 'b')
        baseline['dimensions'] = {'fromA': {'$document': '/operations/0/document/nodes/0/options/count'}}
        baseline['operations'][1]['document']['nodes'][0]['options']['count'] = {
            '$document': '/dimensions/fromA', 'scope': 'workflow'}
        baseline['operations'][1]['document']['nodes'][0]['options']['start'] = {
            '$document': '/operations/0/document/nodes/0/options/start', 'scope': 'workflow'}
        value = design.connect(design.create(baseline), connection('b', 'a'))
        result = design.compile(value)
        self.assertEqual(result['dimensions']['fromA']['$document'], '/operations/1/document/nodes/0/options/count')
        self.assertEqual(result['operations'][0]['document']['nodes'][0]['options']['start']['$document'],
                         '/operations/1/document/nodes/0/options/start')
        resolved = workflow_inputs(result)
        self.assertEqual(resolved['operations'][0]['document']['nodes'][0]['options']['count'], 5)
        self.assertEqual(resolved['operations'][0]['document']['nodes'][0]['options']['start'], 0)

    def test_static_cross_operation_reference_is_not_native_feedback(self):
        baseline = body('a', 'b')
        baseline['operations'][0]['document']['nodes'][0]['options']['start'] = {
            '$document': '/nodes/0/options/start', 'operation': 'b'}
        value = design.connect(design.create(baseline), connection('a', 'b'))
        view = design.project(value)
        static = next(edge for edge in view['edges'] if edge['kind'] == 'document-reference')
        self.assertFalse(static['feedbackEligible'])
        self.assertEqual(view['loops'], [])
        self.assertEqual([operation['id'] for operation in design.compile(value)['operations']], ['a', 'b'])

    def test_output_dependency_propagated_through_document_alias_counts_as_feedback(self):
        baseline = body('a', 'b')
        baseline['operations'][0]['document']['nodes'][0]['options']['start'] = {
            '$document': '/nodes/0/options/start', 'operation': 'b'}
        value = design.connect(design.create(baseline), connection('a', 'b', pointer='/nodes/0/options/start'))
        view = design.project(value)
        self.assertTrue(any(edge['source'] == edge['target'] == 'a' and edge['kind'] == 'value' for edge in view['edges']))
        self.assertEqual(view['loops'][0]['members'], ['a'])
        self.fault('FEEDBACK_EXECUTION_UNAVAILABLE', lambda: design.compile(value))

    def test_relative_document_references_keep_definition_site_after_reorder(self):
        baseline = body('a', 'b')
        baseline['dimensions'] = {'height': 4, 'alias': {'$document': './height'},
                                  'firstStop': {'$document': '../operations/0/document/nodes/0/options/stop'}}
        baseline['operations'][1]['document']['nodes'][0]['options']['stop'] = 8
        baseline['operations'][0]['document']['nodes'][0]['options']['count'] = {
            '$document': '../../../../../1/document/nodes/0/options/count'}
        untouched = design.create(baseline)
        self.assertEqual(design.compile(untouched), baseline)
        value = design.connect(untouched, connection('b', 'a', pointer='/nodes/0/options/start'))
        materialised = design.compile(value)
        resolved = workflow_inputs(materialised)
        self.assertEqual(resolved['dimensions']['alias'], 4)
        self.assertEqual(resolved['dimensions']['firstStop'], 4)
        self.assertEqual(resolved['operations'][1]['document']['nodes'][0]['options']['count'], 5)

    def test_pure_function_output_dependency_is_not_mistaken_for_producer_name(self):
        from schemaxis.workflow_authoring import example
        baseline = example()
        baseline['operations'][1]['document']['nodes'][1]['options']['factor'] = {
            '$value': 'rangeCentre', 'args': {'range': {'$value': 'samples', 'artifact': 0, 'path': '/rows/0'}}}
        value = design.create(baseline)
        edges = design.project(value)['edges']
        self.assertEqual({edge['source'] for edge in edges}, {'samples'})
        self.assertEqual(design.compile(value), baseline)

    def test_expanded_alias_edge_points_to_a_retained_authored_location(self):
        from schemaxis.adaptor_runtime import select
        baseline = body('a', 'b')
        baseline['definitions'] = {'vector': [{'$value': 'a', 'artifact': 0, 'path': '/rows/0/0'}, 2]}
        baseline['operations'][1]['document']['dimensions'] = {
            'vector': {'$document': '/definitions/vector', 'scope': 'workflow'}}
        value = design.create(baseline)
        view = design.project(value)
        edge = next(edge for edge in view['edges'] if edge['targetPointer'] == '/dimensions/vector/0')
        self.assertEqual(edge['pointer'], '/workflow/operations/1/document/dimensions/vector')
        for current in view['edges']:
            self.assertIsNotNone(select(value, current['pointer']))

    def test_resolved_structural_aliases_remain_valid_baselines(self):
        baseline = body('a', 'b')
        baseline['definitions'] = {'version': 'schemaxis.octave/1', 'firstId': 'a'}
        baseline['operations'][0]['id'] = {'$document': '/definitions/firstId'}
        baseline['operations'][0]['document']['version'] = {
            '$document': '/definitions/version', 'scope': 'workflow'}
        value = design.create(baseline)
        self.assertEqual(design.project(value)['nodes'][0]['id'], 'a')
        self.assertEqual(design.project(value)['nodes'][0]['provider'], 'octave')
        changed = design.connect(value, connection('b', 'a'))
        materialised = design.compile(changed)
        self.assertEqual([operation['id'] for operation in workflow_inputs(materialised)['operations']], ['b', 'a'])

    def test_inputs_are_typed_and_structural_fields_are_excluded(self):
        view = design.project(design.create(body('a', 'b')))
        self.assertEqual(view['nodes'][0]['pointer'], '/workflow/operations/0')
        self.assertEqual([item['pointer'] for item in view['nodes'][0]['inputs']],
                         ['/nodes/0/options/start', '/nodes/0/options/stop', '/nodes/0/options/count'])
        self.assertTrue(all(item['kind'] == 'value' for item in view['inputTargets']))
        value = design.create(body('a', 'b'))
        for pointer in ('/version', '/nodes/0/id', '/nodes/0/filter', '/outputs/0', '/nodes/00/options/stop',
                        '/nodes/0/options/missing', '/nodes/0/options/stop/x', '/nodes/0/options/~2x', '/nodes/0/options'):
            with self.subTest(pointer=pointer):
                self.fault('INVALID_CONNECTION', lambda: design.connect(value, connection(pointer=pointer)))

    def test_escaped_metadata_keys_and_vector_components_are_supported(self):
        baseline = body('a', 'b')
        baseline['operations'][1]['document']['dimensions'] = {'a/b~c': 2, 'direction': [1, 2]}
        value = design.create(baseline)
        value = design.connect(value, connection(pointer='/dimensions/a~1b~0c'))
        value = design.connect(value, connection(identity='component', pointer='/dimensions/direction/1'))
        document = design.compile(value)['operations'][1]['document']
        self.assertEqual(document['dimensions']['a/b~c']['$value'], 'a')
        self.assertEqual(document['dimensions']['direction'][1]['$value'], 'a')

    def test_invalid_connection_shapes_are_atomic(self):
        value = design.create(body('a', 'b'))
        original = copy.deepcopy(value)
        for changes in ({'source': 'missing'}, {'target': 'missing'}, {'id': ''}, {'artifactIndex': True},
                        {'artifactIndex': -1}, {'valuePath': 'relative'}, {'valuePath': '/bad~x'},
                        {'kind': 'artifact'}, {'unexpected': 3}):
            with self.subTest(changes=changes):
                code = 'INVALID_NAME' if changes.get('id') == '' else 'UNKNOWN_ARGUMENT' if 'unexpected' in changes else 'INVALID_CONNECTION'
                self.fault(code, lambda: design.connect(value, connection(**changes)))
                self.assertEqual(value, original)
        changed = design.connect(value, connection())
        self.fault('INVALID_CONNECTION', lambda: design.connect(changed, connection(identity='duplicateTarget')))
        self.fault('INVALID_CONNECTION', lambda: design.connect(changed, connection(pointer='/nodes/0/options/start')))

    def test_design_shape_and_json_are_bounded(self):
        value = design.create(body('a'))
        for field, replacement in [('connections', {}), ('workflow', None), ('controllers', []), ('version', 'other')]:
            changed = copy.deepcopy(value)
            changed[field] = replacement
            code = {'connections': 'RESOURCE_LIMIT', 'workflow': 'INVALID_DOCUMENT', 'controllers': 'INVALID_FEEDBACK_CONTROLLER', 'version': 'UNSUPPORTED_VERSION'}[field]
            self.fault(code, lambda: design.validate(changed))
        recursive = {}
        recursive['self'] = recursive
        self.fault('INVALID_DOCUMENT', lambda: design.create(recursive))
        deep = {}
        for _ in range(1500):
            deep = {'nested': deep}
        self.fault('RESOURCE_LIMIT', lambda: design.create(deep))
        for bad in (float('nan'), float('inf'), set(), {1: 'bad'}):
            changed = copy.deepcopy(value)
            changed['extra'] = bad
            self.fault('INVALID_DOCUMENT', lambda: design.validate(changed))
        self.fault('RESOURCE_LIMIT', lambda: design.create(body(*['n' + str(index) for index in range(257)])))
        huge = copy.deepcopy(value)
        huge['workflow']['definitions'] = {'text': 'x' * 1048576}
        self.fault('RESOURCE_LIMIT', lambda: design.validate(huge))

    def test_projection_and_compile_never_launch_native_applications(self):
        modules = set(sys.modules)
        with patch('subprocess.Popen', side_effect=AssertionError('native launch prohibited')) as launch:
            value = design.connect(design.create(body('a', 'b')), connection())
            design.project(value)
            design.compile(value)
            design.project(self.loop())
        launch.assert_not_called()
        self.assertFalse({name.split('.')[0] for name in set(sys.modules) - modules} & {'FreeCAD', 'paraview', 'gmsh', 'bpy'})


if __name__ == '__main__':
    unittest.main()
