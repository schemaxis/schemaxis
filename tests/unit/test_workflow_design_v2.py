# Copyright (C) 2026 David L F Gaden
"""Workflow design version 2: ports compile to the shared version 1 machinery."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from schemaxis import storage, workflow_design as design, workflow_templates
from schemaxis.console_session import AdaptorConsoleSession
from schemaxis.core.faults import SchemaxisError
from schemaxis.workflow_authoring import design_action, example
from schemaxis.workflow_loop_controls import catalogue


def body(*identities):
    return {'version': 'schemaxis.workflow/1', 'operations': [
        {'id': identity, 'document': {'version': 'schemaxis.octave/1', 'nodes': [
            {'id': 'data', 'filter': 'sequence', 'options': {'start': 0, 'stop': 4, 'count': 5}}],
            'outputs': ['data']}} for identity in identities]}


def v1(workflow, *connections):
    return {'version': design.VERSION, 'workflow': workflow, 'connections': list(connections), 'controllers': {}}


def arrow(source, target, identity, pointer='/nodes/0/options/stop'):
    return {'id': identity, 'source': source, 'target': target, 'targetPointer': pointer,
            'kind': 'value', 'artifactIndex': 0, 'valuePath': '/rows/0/0'}


def value_ports(*operations):
    ports = {'outputs': {'first': {'artifact': 0, 'kind': 'value', 'valuePath': '/rows/0/0'}},
             'inputs': {'stop': {'target': '/nodes/0/options/stop', 'kind': 'value'},
                        'start': {'target': '/nodes/0/options/start', 'kind': 'value'}}}
    return {operation: copy.deepcopy(ports) for operation in operations}


def link(identity, source, target, output='first', port='stop'):
    return {'id': identity, 'from': {'operation': source, 'port': output},
            'to': {'operation': target, 'port': port}}


class WorkflowDesignV2Tests(unittest.TestCase):
    def fault(self, code, action, location=None):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code)
        self.assertTrue(caught.exception.fault.location)
        if location is not None:
            self.assertEqual(caught.exception.fault.location, location)
        return caught.exception.fault

    def ported(self, *identities):
        value = design.create(body(*identities))
        value['ports'] = value_ports(*identities)
        design.validate(value)
        return value

    def test_create_is_version_2_and_matches_console_template(self):
        from schemaxis.console_session import CONSOLE_TYPES
        value = design.create()
        self.assertEqual(value['version'], design.VERSION_2)
        self.assertEqual(value, CONSOLE_TYPES['workflow-design']['consoleTemplate'])
        view = design.project(value)
        self.assertEqual((view['status'], view['designVersion'], view['warnings']), ('empty', design.VERSION_2, []))

    def test_upgrade_preserves_loop_identity_controllers_and_compilation(self):
        original = v1(body('a', 'b', 'c'), arrow('a', 'b', 'ab'), arrow('b', 'a', 'ba'))
        loop = design.project(original)['loops'][0]['id']
        original = design.configure(original, loop, catalogue()[0]['defaults'])
        frozen = copy.deepcopy(original)
        upgraded = design.upgrade(original)
        self.assertEqual(original, frozen)
        self.assertEqual(upgraded['version'], design.VERSION_2)
        self.assertEqual(design.project(upgraded)['loops'][0]['id'], loop)
        self.assertEqual(upgraded['controllers'], original['controllers'])
        self.assertEqual([item['id'] for item in upgraded['connections']], ['ab', 'ba'])
        self.assertTrue(all(spec.get('generated') for entry in upgraded['ports'].values()
                            for group in entry.values() for spec in group.values()))
        acyclic = v1(body('a', 'b', 'c'), arrow('c', 'a', 'ca'))
        self.assertEqual(design.compile(design.upgrade(acyclic)), design.compile(acyclic))
        self.assertEqual(design.upgrade(upgraded), upgraded)

    def test_version_1_designs_still_validate_connect_and_compile(self):
        value = v1(body('a', 'b'))
        changed = design.connect(value, arrow('a', 'b', 'link'))
        self.assertEqual(changed['version'], design.VERSION)
        self.assertEqual(design.project(changed)['designVersion'], design.VERSION)
        self.assertEqual(design.disconnect(changed, 'link'), value)
        self.fault('INVALID_CONNECTION', lambda: design.connect(value, link('x', 'a', 'b')))
        self.fault('UNSUPPORTED_VERSION', lambda: design.set_naming(value, {}))
        identity = design.project(design.connect(changed, arrow('b', 'a', 'back')))['loops'][0]['id']
        edited = design.connect(changed, arrow('b', 'a', 'back'))
        edited['connections'][1]['valuePath'] = '/rows/1/0'
        self.assertNotEqual(design.project(edited)['loops'][0]['id'], identity)

    def test_port_connections_compile_to_one_version_1_connection_each(self):
        value = self.ported('a', 'b', 'c')
        value = design.connect(value, link('ab', 'a', 'b'))
        value = design.connect(value, link('ac', 'a', 'c'))  # Fan-out from one output port.
        value = design.connect(value, link('bc', 'b', 'c', port='start'))  # Fan-in through another port.
        view = design.project(value)
        edges = {edge['id']: edge for edge in view['edges']}
        self.assertEqual(edges['ab']['from'], {'operation': 'a', 'port': 'first'})
        self.assertEqual(edges['bc']['to'], {'operation': 'c', 'port': 'start'})
        self.assertEqual(edges['ac']['targetPointer'], '/nodes/0/options/stop')
        node = next(item for item in view['nodes'] if item['id'] == 'a')
        self.assertEqual(node['ports']['outputs'][0]['connections'], ['ab', 'ac'])
        compiled = design.compile(value)
        self.assertEqual(compiled['operations'][2]['document']['nodes'][0]['options']['start'],
                         {'$value': 'b', 'artifact': 0, 'path': '/rows/0/0'})
        self.assertEqual(design.compile(design.disconnect(value, 'bc'))['operations'][2]['document']['nodes'][0]
                         ['options']['start'], 0)

    def test_port_and_connection_faults_are_located(self):
        value = self.ported('a', 'b')
        bad_ports = [
            ({'1bad': {'target': '/nodes/0/options/stop', 'kind': 'value'}}, '$.ports.a.inputs.1bad'),
            ({'x': {'target': '/nodes/0/filter', 'kind': 'value'}}, '$.ports.a.inputs.x.target'),
            ({'x': {'target': '/nodes/0/options/stop', 'kind': 'artifact'}}, '$.ports.a.inputs.x.kind'),
            ({'x': {'target': '/nodes/0/options/stop', 'kind': 'value', 'data': {'kind': 'smell'}}},
             '$.ports.a.inputs.x.data.kind'),
            ({'x': {'target': '/nodes/0/options/stop', 'kind': 'value', 'data': {'layout': 'diagonal'}}},
             '$.ports.a.inputs.x.data.layout'),
            ({'x': {'target': '/nodes/0/options/stop', 'kind': 'value', 'data': {'streaming': 1}}},
             '$.ports.a.inputs.x.data.streaming'),
            ({'x': {'target': '/nodes/0/options/stop', 'kind': 'value'},
              'y': {'target': '/nodes/0/options/stop', 'kind': 'value'}}, '$.ports.a.inputs.y.target'),
        ]
        for inputs, location in bad_ports:
            with self.subTest(location=location):
                self.fault('INVALID_PORT', lambda: design.set_ports(value, 'a', {'inputs': inputs}), location)
        self.fault('INVALID_PORT', lambda: design.set_ports(value, 'a', {'outputs': {'o': {
            'artifact': 0, 'kind': 'artifact', 'valuePath': '/x'}}}), '$.ports.a.outputs.o.valuePath')
        self.fault('UNKNOWN_OPERATION', lambda: design.set_ports(value, 'missing', {}))
        orphan = copy.deepcopy(value)
        orphan['ports']['missing'] = {}
        self.fault('INVALID_PORT', lambda: design.validate(orphan), '$.ports.missing')
        self.fault('INVALID_CONNECTION', lambda: design.connect(value, link('x', 'a', 'b', output='none')),
                   '$.connections/0.from.port')
        self.fault('INVALID_CONNECTION', lambda: design.connect(value, link('x', 'zz', 'b')),
                   '$.connections/0.from.operation')
        connected = design.connect(value, link('ab', 'a', 'b'))
        self.fault('INVALID_CONNECTION', lambda: design.connect(connected, link('ab2', 'a', 'b')),
                   '$.connections/1.to')
        mixed = design.set_ports(value, 'a', {'outputs': {'file': {'artifact': 0, 'kind': 'artifact'}}})
        self.fault('INVALID_CONNECTION', lambda: design.connect(mixed, link('x', 'a', 'b', output='file')))
        self.fault('INVALID_CONNECTION', lambda: design.set_ports(connected, 'b', {}), '$.connections/0.to.port')
        self.assertEqual(value, self.ported('a', 'b'))

    def test_data_mismatches_are_warnings_not_faults(self):
        value = self.ported('a', 'b')
        value['ports']['a']['outputs']['first']['data'] = {'kind': 'number', 'units': 'm', 'formats': ['csv']}
        value['ports']['b']['inputs']['stop']['data'] = {'kind': 'vector', 'units': 'mm', 'formats': ['json'],
                                                        'layout': 'planar', 'contiguous': True}
        value = design.connect(value, link('ab', 'a', 'b'))
        warnings = design.project(value)['warnings']
        self.assertEqual(sorted(item['code'] for item in warnings),
                         ['DATA_FORMAT_MISMATCH', 'DATA_KIND_MISMATCH', 'DATA_UNITS_MISMATCH'])
        self.assertTrue(all(item['location'] == '$.connections/0' for item in warnings))
        self.assertEqual(design.compile(value)['operations'][1]['document']['nodes'][0]['options']['stop']['$value'],
                         'a')

    def test_layout_is_presentation_only(self):
        value = self.ported('a', 'b')
        value = design.connect(value, link('ab', 'a', 'b'))
        value = design.connect(value, link('ba', 'b', 'a'))
        identity = design.project(value)['loops'][0]['id']
        value = design.configure(value, identity, catalogue()[1]['defaults'])
        moved = design.move(value, {'a': {'x': 10, 'y': 20.5}}, {'x': 1, 'y': 2, 'zoom': 1.5})
        view = design.project(moved)
        self.assertEqual(view['loops'][0]['id'], identity)
        self.assertEqual(view['layout'], {'nodes': {'a': {'x': 10, 'y': 20.5}},
                                          'viewport': {'x': 1, 'y': 2, 'zoom': 1.5}})
        self.assertEqual(view['nodes'][0]['position'], {'x': 10, 'y': 20.5})
        self.fault('INVALID_LAYOUT', lambda: design.move(value, {'zz': {'x': 0, 'y': 0}}), '$.layout.nodes.zz')
        self.fault('INVALID_LAYOUT', lambda: design.move(value, {'a': {'x': True, 'y': 0}}), '$.layout.nodes.a.x')
        self.fault('INVALID_LAYOUT', lambda: design.move(value, {}, {'x': 0, 'y': 0, 'zoom': 0}))

    def test_add_rename_duplicate_and_remove_operations(self):
        value = self.ported('a', 'b')
        value = design.connect(value, link('ab', 'a', 'b'))
        value = design.connect(value, link('ba', 'b', 'a'))
        loop = design.project(value)['loops'][0]['id']
        value = design.configure(value, loop, catalogue()[0]['defaults'])
        value = design.move(value, {'a': {'x': 0, 'y': 0}})
        value = design.set_outputs(value, {'first': {'operation': 'a', 'artifact': 0, 'kind': 'table'}})
        value = design.add_operation(value, 'c', body('c')['operations'][0]['document'], position={'x': 5, 'y': 5})
        self.fault('DUPLICATE_OPERATION', lambda: design.add_operation(value, 'c', {}))
        renamed = design.rename_operation(value, 'a', 'alpha')
        self.assertEqual(renamed['layout']['nodes']['alpha'], {'x': 0, 'y': 0})
        self.assertEqual(renamed['outputs']['first']['operation'], 'alpha')
        self.assertEqual(renamed['connections'][0]['from']['operation'], 'alpha')
        self.assertEqual(len(renamed['controllers']), 1)
        self.assertEqual(design.project(renamed)['loops'][0]['members'], ['alpha', 'b'])
        self.assertEqual(design.project(renamed)['loops'][0]['controller'], catalogue()[0]['defaults'])
        referenced = example()
        renamed_example = design.rename_operation(design.create(referenced), 'samples', 'source')
        option = renamed_example['workflow']['operations'][1]['document']['nodes'][0]['options']['file']
        self.assertEqual(option, {'$artifact': 'source', 'index': 0})
        duplicated = design.duplicate_operation(renamed, 'b', 'b2')
        self.assertEqual(duplicated['connections'][-1], link('ab-b2', 'alpha', 'b2'))
        self.assertEqual(duplicated['ports']['b2'], duplicated['ports']['b'])
        self.fault('OPERATION_IN_USE', lambda: design.remove_operation(duplicated, 'alpha'), '$.outputs')
        removed = design.remove_operation(duplicated, 'alpha', cascade=True)
        self.assertEqual(removed['outputs'], {})
        self.assertNotIn('alpha', removed['ports'])
        self.assertEqual(removed['connections'], [])
        self.assertEqual(removed['controllers'], {})
        self.assertNotIn('alpha', removed['layout']['nodes'])
        self.fault('OPERATION_IN_USE', lambda: design.remove_operation(design.create(example()), 'samples'),
                   '$.workflow.operations/1/document/nodes/0/options/file')

    def test_remove_reindexes_workflow_document_references(self):
        baseline = body('a', 'b', 'c')
        baseline['operations'][2]['document']['nodes'][0]['options']['start'] = {
            '$document': '/operations/1/document/nodes/0/options/start', 'scope': 'workflow'}
        value = design.remove_operation(design.create(baseline), 'a')
        self.assertEqual(value['workflow']['operations'][1]['document']['nodes'][0]['options']['start']['$document'],
                         '/operations/0/document/nodes/0/options/start')
        self.fault('OPERATION_IN_USE', lambda: design.remove_operation(design.create(baseline), 'b'))

    def test_expose_parameter_moves_literal_and_declares_template_parameter(self):
        value = self.ported('a', 'b')
        value = design.connect(value, link('ab', 'a', 'b'))
        exposed = design.expose_parameter(value, 'b', '/nodes/0/options/count', 'count',
                                          {'label': 'Samples', 'kind': 'integer', 'constraints': {'minimum': 2}})
        self.assertEqual(exposed['workflow']['settings'], {'count': 5})
        self.assertEqual(exposed['workflow']['operations'][1]['document']['nodes'][0]['options']['count'],
                         {'$document': '/settings/count', 'scope': 'workflow'})
        self.assertEqual(exposed['parameters']['count'], {
            'label': 'Samples', 'kind': 'integer', 'constraints': {'minimum': 2},
            'target': {'scope': 'workflow', 'pointer': '/settings/count'}})
        dimension = design.expose_parameter(exposed, 'a', '/nodes/0/options/start', 'origin', {'group': 'dimensions'})
        self.assertEqual(dimension['parameters']['origin']['kind'], 'number')
        self.assertEqual(dimension['parameters']['origin']['target']['pointer'], '/dimensions/origin')
        self.fault('INVALID_PARAMETER', lambda: design.expose_parameter(value, 'b', '/nodes/0/options/stop', 'stop'))
        self.fault('DUPLICATE_PARAMETER', lambda: design.expose_parameter(exposed, 'a', '/nodes/0/options/count',
                                                                          'count'))
        self.fault('INVALID_PARAMETER', lambda: design.expose_parameter(value, 'b', '/nodes/0/missing', 'x'))
        self.fault('INVALID_PARAMETER', lambda: design.expose_parameter(value, 'b', '/nodes/0/filter', 'x',
                                                                        {'group': 'other'}))
        self.fault('INVALID_PARAMETER', lambda: design.set_parameters(exposed, {'count': {
            'label': 'Samples', 'kind': 'boolean', 'target': {'scope': 'workflow', 'pointer': '/settings/count'}}}),
            '$.parameters.count.target')

    def test_naming_and_template_sections_are_validated(self):
        value = self.ported('a')
        self.assertEqual(design.set_naming(value, {'pattern': '{index}-{param:x}{ext}', 'indexWidth': 3})['naming'],
                         {'pattern': '{index}-{param:x}{ext}', 'indexWidth': 3})
        self.fault('INVALID_NAMING', lambda: design.set_naming(value, {'pattern': '../{index}'}), '$.naming.pattern')
        self.fault('INVALID_NAMING', lambda: design.set_naming(value, {'indexWidth': 13}), '$.naming.indexWidth')
        self.fault('INVALID_OUTPUT_ALIAS', lambda: design.set_outputs(value, {'x': {
            'operation': 'missing', 'artifact': 0, 'kind': 'table'}}), '$.outputs.x.operation')

    def test_suggest_ports_reports_exact_inputs_and_best_effort_outputs(self):
        value = design.create(example())
        suggestion = design.suggest_ports(value, 'scaled')
        self.assertEqual([(item['name'], item['target'], item['kind']) for item in suggestion['inputs']],
                         [('file', '/nodes/0/options/file', 'artifact'),
                          ('factor', '/nodes/1/options/factor', 'value')])
        self.assertEqual(suggestion['inputs'][0]['acceptedArtifacts'], ['table'])
        self.assertEqual(suggestion['outputs'], [{'name': 'result', 'artifact': 0, 'kind': 'artifact',
                                                  'node': 'result', 'filter': 'scale', 'nodeKinds': ['table'],
                                                  'confidence': 'declared-order'}])
        ports = {'inputs': {item['name']: {'target': item['target'], 'kind': item['kind']}
                            for item in suggestion['inputs']}}
        declared = design.suggest_ports(design.set_ports(value, 'scaled', ports), 'scaled')
        self.assertTrue(declared['inputs'][0]['declared'])
        self.fault('UNKNOWN_OPERATION', lambda: design.suggest_ports(value, 'missing'))

    def exportable(self):
        value = design.create(example())
        value = design.expose_parameter(value, 'scaled', '/nodes/1/options/factor', 'factor',
                                        {'label': 'Factor', 'constraints': {'minimum': 0}})
        value = design.set_outputs(value, {'scaled': {'operation': 'scaled', 'artifact': 0, 'kind': 'table'}})
        return design.set_naming(value, {'pattern': '{index}-{output}-f{param:factor}{ext}'})

    def test_export_template_writes_a_bundle_that_loads_and_binds(self):
        value = self.exportable()
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'bundle'
            result = design.export_template(value, target, template_id='scale.study', title='Scale study')
            bundle = workflow_templates.load_template(target / 'template.json')
            self.assertEqual(bundle['digest'], result['digest'])
            self.assertEqual(bundle['workflow'], design.compile(value))
            case = json.loads((target / 'cases' / 'example.json').read_text())
            self.assertEqual(case['values'], {'factor': 2})
            self.assertEqual(case['run'], {'naming': value['naming']})
            bound = workflow_templates.bind_values(bundle, {**case, 'values': {'factor': 3}})
            self.assertEqual(bound['values'], {'factor': 3})
            self.fault('OUTPUT_EXISTS', lambda: design.export_template(value, target, template_id='x', title='x'))
            moved = design.move(value, {'scaled': {'x': 400, 'y': 10}})
            again = design.export_template(moved, Path(temporary) / 'moved', template_id='scale.study',
                                           title='Scale study')
            self.assertEqual(again['digest'], result['digest'])
            self.fault('INVALID_TEMPLATE', lambda: design.export_template(value, Path(temporary) / 'bad',
                                                                          template_id='1bad', title='x'))
            self.assertFalse((Path(temporary) / 'bad').exists())

    def test_session_design_actions_are_revisioned_and_undoable(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = AdaptorConsoleSession(Path(temporary) / 'console', 'workflow-design')
            self.addCleanup(session.close)

            def act(action, **params):
                return design_action(session, session.active_document, session._record['revision'], action, params)
            operation = body('a')['operations'][0]['document']
            added = act('add_operation', id='a', document=operation, position={'x': 1, 'y': 2})
            self.assertEqual([node['id'] for node in added['projection']['nodes']], ['a'])
            act('add_operation', id='b', document=operation)
            act('set_ports', operation='a', ports=value_ports('a')['a'])
            act('set_ports', operation='b', ports=value_ports('b')['b'])
            connected = act('connect', connection=link('ab', 'a', 'b'))
            self.assertEqual(connected['projection']['edges'][0]['from'], {'operation': 'a', 'port': 'first'})
            suggested = act('suggest_ports', operation='a')
            self.assertEqual(suggested['revision'], connected['revision'])
            self.assertEqual(suggested['suggestions']['operation'], 'a')
            moved = act('move', positions={'b': {'x': 3, 'y': 4}})
            self.assertEqual(moved['projection']['layout']['nodes']['b'], {'x': 3, 'y': 4})
            session.undo()
            self.assertNotIn('b', session.document['layout']['nodes'])
            act('rename_operation', operation='b', newId='beta')
            self.assertEqual(session.document['connections'][0]['to']['operation'], 'beta')
            with self.assertRaises(SchemaxisError) as caught:
                design_action(session, session.active_document, 0, 'project', {})
            self.assertEqual(caught.exception.fault.code, 'STALE_REVISION')
            with self.assertRaises(SchemaxisError) as caught:
                act('connect', connections=[])
            self.assertEqual(caught.exception.fault.code, 'UNKNOWN_ARGUMENT')
            design_id = session.active_document
            compiled = act('compile')
            self.assertNotEqual(compiled['document'], design_id)
            self.assertEqual(session.provider, 'workflow')
            session.activate(design_id)
            exported = act('export_template', directory=str(Path(temporary) / 'bundle'), templateId='t', title='T')
            self.assertTrue(Path(exported['export']['template']).is_file())
            old = {'version': design.VERSION, 'workflow': body('a', 'b'),
                   'connections': [arrow('a', 'b', 'ab')], 'controllers': {}}
            session._edit(old)
            upgraded = act('upgrade')
            self.assertEqual(upgraded['projection']['designVersion'], design.VERSION_2)
            session.undo()
            self.assertEqual(session.document, old)

    def test_inputs_are_never_mutated_by_failed_or_successful_edits(self):
        value = self.ported('a', 'b')
        value = design.connect(value, link('ab', 'a', 'b'))
        frozen = copy.deepcopy(value)
        design.rename_operation(value, 'a', 'z')
        design.duplicate_operation(value, 'b', 'c')
        design.remove_operation(value, 'b')
        design.expose_parameter(value, 'a', '/nodes/0/options/count', 'n')
        with self.assertRaises(SchemaxisError):
            design.rename_operation(value, 'a', 'b')
        self.assertEqual(value, frozen)
        self.assertEqual(storage.digest(value), storage.digest(frozen))


if __name__ == '__main__':
    unittest.main()
