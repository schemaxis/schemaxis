import copy
import unittest
from schemaxis.core.faults import SchemaxisError
from schemaxis.filters import catalogue
from schemaxis.pipeline import RuntimeClosure, DefinitionGraph


class Backend:
    def __init__(self):
        self.events = []
        self.serial = 0
        self.fail_update = None

    def create(self, node, declaration, inputs, constructor):
        self.serial += 1
        handle = {'node': node, 'serial': self.serial, 'values': {}, 'inputs': inputs}
        self.events.append(('create', node))
        return handle

    def configure(self, handle, declaration, values):
        handle['values'].update(copy.deepcopy(values))
        self.events.append(('set', handle['node'], copy.deepcopy(values)))

    def update(self, handle, time):
        self.events.append(('update', handle['node'], time))
        if handle['node'] == self.fail_update:
            raise RuntimeError('backend rejected state')

    def observe(self, handle):
        return {'bounds': [-2, 2, -4, 4, -6, 6], 'serial': handle['serial']}

    def delete(self, handle):
        self.events.append(('delete', handle['node']))

    def sample(self, handle, association, field, index, component, block):
        self.events.append(('sample', handle['node']))
        return index + 1.0


def document():
    return {'version': 'schemaxis/1', 'nodes': [
        {'id': 'source', 'filter': 'wavelet'},
        {'id': 'slice', 'filter': 'slice', 'inputs': {'input': 'source'},
         'options': {'origin': {'$axis': 'position'}}},
        {'id': 'contour', 'filter': 'contour', 'inputs': {'input': 'slice'},
         'options': {'field': ['POINTS', 'RTData'], 'values': {'$axis': 'level'}}},
        {'id': 'unused', 'filter': 'sphere'},
    ], 'axes': [{'name': 'position', 'values': [[0, 0, 0], [1, 0, 0]]},
                {'name': 'level', 'values': [[100], [150], [200]]}]}


class PipelineTests(unittest.TestCase):
    def test_declared_commands_repeat_and_invalidate_downstream_without_rebuild(self):
        value=document();value['nodes'][0]['onVisit']=['Refresh']
        declarations=catalogue()
        declarations['wavelet']['commands']={'Refresh':{'native':'Refresh'}}
        backend=Backend()
        backend.command=lambda handle,command: backend.events.append(('command',handle['node'],command))
        active=RuntimeClosure(DefinitionGraph(value,declarations),backend)
        visit=next(active.activate(['slice']).visits())
        active.apply(visit);source=active.handles['source']
        result=active.apply(visit)
        self.assertEqual(result['updated'],['source','slice'])
        self.assertIs(active.handles['source'],source)
        self.assertEqual(len([e for e in backend.events if e[0]=='command']),2)
        self.assertLess(backend.events.index(('command','source','Refresh')),
                        backend.events.index(('update','source',visit['time'])))

    def test_unknown_command_never_reaches_backend(self):
        value=document();value['nodes'][0]['onVisit']=['Delete']
        self.assertFault('INVALID_COMMAND',lambda:self.make(value))

    def test_output_port_keeps_producer_dependency_and_lifetime(self):
        value = document()
        value['nodes'][1]['inputs']['input'] = {'node': 'source', 'port': 1}
        backend = Backend()
        backend.output_port = lambda handle, port: (handle, port)
        active = RuntimeClosure(self.make(value), backend)
        active.apply(next(active.activate(['slice']).visits()))
        source = active.handles['source']
        self.assertEqual(active.handles['slice']['inputs']['input'], (source, 1))
        self.assertEqual(active.master.nodes['slice']['dependencies'], ['source'])
        active.close()
        self.assertEqual([e for e in backend.events if e[0] == 'delete'],
                         [('delete', 'slice'), ('delete', 'source')])

    def test_invalid_output_port_references_fail_during_planning(self):
        for ref in [{'node':'source','port':-1}, {'node':'source','port':True},
                    {'node':'source'}, {'node':'source','port':0,'extra':1}]:
            value = document()
            value['nodes'][1]['inputs']['input'] = ref
            with self.subTest(ref=ref), self.assertRaises(SchemaxisError):
                self.make(value)

    def make(self, value=None):
        return DefinitionGraph(document() if value is None else value, catalogue())

    def assertFault(self, code, action):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code)

    def test_pruning_and_fastest_first_product(self):
        selected = self.make().select(['contour'])
        self.assertEqual(selected.order, ('source', 'slice', 'contour'))
        self.assertEqual([list(v['indices'].values()) for v in selected.visits()],
                         [[0, 0], [0, 1], [1, 0], [1, 1], [2, 0], [2, 1]])
        self.assertEqual(selected.count, 6)

    def test_unused_axis_is_removed_with_unused_branch(self):
        selection = self.make().select(['source'])
        self.assertEqual(selection.count, 1)
        self.assertEqual(selection.axes, ())

    def test_reuse_invalidation_and_no_transient_carry_update(self):
        active = RuntimeClosure(self.make(), Backend())
        selection = active.activate(['contour'])
        visits = list(selection.visits())
        first = active.apply(visits[0])
        self.assertEqual(first['updated'], ['source', 'slice', 'contour'])
        identities = {k: id(v) for k, v in active.handles.items()}
        self.assertEqual(active.apply(visits[1])['updated'], ['slice', 'contour'])
        start = len(active.backend.events)
        active.apply(visits[2])
        events = active.backend.events[start:]
        setters = [i for i, e in enumerate(events) if e[0] == 'set']
        updates = [i for i, e in enumerate(events) if e[0] == 'update']
        self.assertLess(max(setters), min(updates))
        self.assertEqual([e[1] for e in events if e[0] == 'update'], ['slice', 'contour'])
        self.assertEqual(identities, {k: id(v) for k, v in active.handles.items()})
        self.assertEqual(active.apply(visits[2])['updated'], [])

    def test_scene_switch_removes_dependents_first_and_preserves_intersection(self):
        active = RuntimeClosure(self.make(), Backend())
        active.apply(next(active.activate(['contour']).visits()))
        source = active.handles['source']
        active.activate(['source', 'unused'])
        self.assertEqual([e[1] for e in active.backend.events if e[0] == 'delete'], ['contour', 'slice'])
        active.apply(next(active.selection.visits()))
        self.assertIs(source, active.handles['source'])
        active.close()
        active.close()
        self.assertEqual(active.handles, {})

    def test_hidden_observation_dependencies_survive_pruning(self):
        value = document()
        value['nodes'][1]['options']['origin'] = {'$calc': 'midpoint', 'args': [
            {'$observe': 'unused', 'path': ['bounds']}]}
        active = RuntimeClosure(self.make(value), Backend())
        selected = active.activate(['slice'])
        self.assertIn('unused', selected.order)
        active.apply(next(selected.visits()))
        self.assertEqual(active.values['slice']['origin'], [0, 0, 0])
        updates = [e[1] for e in active.backend.events if e[0] == 'update']
        self.assertLess(updates.index('unused'), updates.index('slice'))

    def test_explicit_and_hidden_cycles(self):
        value = document()
        value['nodes'][0]['options'] = {'centre': {'$observe': 'contour', 'path': ['bounds']}}
        self.assertFault('PIPELINE_CYCLE', lambda: self.make(value))

    def test_unknown_dependency(self):
        value = document()
        value['nodes'][1]['inputs']['input'] = 'absent'
        self.assertFault('UNKNOWN_NODE', lambda: self.make(value))

    def test_every_axis_sample_is_validated(self):
        value = document()
        value['axes'][0]['values'][1] = [1, 2]
        self.assertFault('INVALID_ARGUMENT', lambda: self.make(value))

    def test_expansion_limit_and_invalid_versions(self):
        value = document()
        value['maxStates'] = 5
        master = self.make(value)
        self.assertFault('EXPANSION_TOO_LARGE', lambda: master.select(['contour']))
        value['version'] = 'schemaxis/999'
        self.assertFault('UNSUPPORTED_VERSION', lambda: self.make(value))

    def test_backend_failure_poisoning_and_cleanup(self):
        active = RuntimeClosure(self.make(), Backend())
        visit = next(active.activate(['contour']).visits())
        active.backend.fail_update = 'slice'
        self.assertFault('PIPELINE_EXECUTION_FAILED', lambda: active.apply(visit))
        self.assertFault('CLOSED_PIPELINE', lambda: active.apply(visit))
        active.close()
        self.assertEqual([e[1] for e in active.backend.events if e[0] == 'delete'],
                         ['contour', 'slice', 'source'])

    def test_synchronised_properties_share_one_axis(self):
        value = {'version': 'schemaxis/1', 'nodes': [{'id': 'line', 'filter': 'line', 'options': {
            'start': {'$axis': 'seed', 'path': ['a']},
            'end': {'$axis': 'seed', 'path': ['b']}}}],
            'axes': [{'name': 'seed', 'values': [
                {'a': [0, 0, 0], 'b': [0, 1, 0]}, {'a': [1, 0, 0], 'b': [1, 1, 0]}]}]}
        active = RuntimeClosure(self.make(value), Backend())
        selected = active.activate(['line'])
        self.assertEqual(selected.count, 2)
        for visit in selected.visits():
            active.apply(visit)
            self.assertEqual(active.values['line']['start'][0], active.values['line']['end'][0])

    def test_multi_input_and_seed_ports(self):
        value = {'version': 'schemaxis/1', 'nodes': [
            {'id': 'a', 'filter': 'sphere'}, {'id': 'b', 'filter': 'sphere'},
            {'id': 'g', 'filter': 'group', 'inputs': {'input': ['a', 'b']}}]}
        active = RuntimeClosure(self.make(value), Backend())
        active.apply(next(active.activate(['g']).visits()))
        self.assertEqual(len(active.handles['g']['inputs']['input']), 2)

    def test_constructor_changes_cannot_be_swept(self):
        value = document()
        value['nodes'].append({'id': 'case', 'filter': 'foam', 'options': {'file': {'$axis': 'level'}}})
        self.assertFault('DYNAMIC_CONSTRUCTOR', lambda: self.make(value))

    def test_time_change_invalidates_and_duplicate_time_does_not(self):
        value = document()
        value['times'] = [0, 1, 1]
        active = RuntimeClosure(self.make(value), Backend())
        visits = list(active.activate(['source']).visits())
        self.assertEqual([active.apply(v)['updated'] for v in visits], [['source'], ['source'], []])

    def test_owned_document_and_reproducible_digest(self):
        value = document()
        master = self.make(value)
        old = master.to_dict()
        value['nodes'].clear()
        self.assertEqual(old, master.to_dict())
        self.assertEqual(old['digest'], self.make().to_dict()['digest'])

    def test_field_sample_retains_hidden_dependency_and_evidence(self):
        value = {'version': 'schemaxis/1', 'nodes': [{'id': 'upstream', 'filter': 'wavelet'},
                 {'id': 'output', 'filter': 'sphere', 'options': {'radius': {
                     '$sample': 'upstream', 'association': 'POINTS', 'field': 'RTData', 'index': 2}}}]}
        active = RuntimeClosure(self.make(value), Backend())
        result = active.apply(next(active.activate(['output']).visits()))
        self.assertEqual(active.values['output']['radius'], 3)
        self.assertEqual(result['samples'][0]['value'], 3)
        self.assertLess(active.backend.events.index(('update', 'upstream', 0.0)),
                        active.backend.events.index(('sample', 'upstream')))

    def test_axis_series_and_direction_conversion(self):
        value = document()
        value['axes'][1] = {'name': 'level', 'series': {'start': 100, 'end': 200, 'count': 3}}
        value['nodes'][2]['options']['values'] = [{'$axis': 'level'}]
        value['nodes'][1]['options']['normal'] = 'y+'
        active = RuntimeClosure(self.make(value), Backend())
        active.apply(next(active.activate(['contour']).visits()))
        self.assertEqual(active.values['slice']['normal'], [0, 1, 0])
        self.assertEqual(active.selection.count, 6)

    def test_conditional_dictionary_requirements(self):
        value = {'version': 'schemaxis/1', 'nodes': [{'id': 'source', 'filter': 'wavelet'},
                 {'id': 'convert', 'filter': 'pointToCell', 'inputs': {'input': 'source'},
                  'options': {'allArrays': False}}]}
        self.assertFault('MISSING_ARGUMENT', lambda: self.make(value))

    def test_nonzero_direction_and_cross_property_constraints(self):
        value = document()
        value['nodes'][1]['options']['normal'] = [0, 0, 0]
        self.assertFault('DEGENERATE_DIRECTION', lambda: self.make(value))
        value = {'version': 'schemaxis/1', 'nodes': [{'id': 'source', 'filter': 'wavelet'},
                 {'id': 'threshold', 'filter': 'threshold', 'inputs': {'input': 'source'},
                  'options': {'field': ['POINTS', 'RTData'], 'lower': 3, 'upper': 2}}]}
        self.assertFault('INVALID_RANGE', lambda: self.make(value))


if __name__ == '__main__':
    unittest.main()
