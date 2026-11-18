# Copyright (C) 2026 David L. F. Gaden.
"""Shared resident plan transitions with counted native stand-ins.

The common RuntimeClosure, the GraphWorker, the Live Data worker and the ParaView
host planner are real; only the native application is a counting stand-in.
"""
import copy
import unittest
from unittest.mock import patch

from schemaxis.adaptors.paraview.filters import catalogue
from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis import live_transport
from schemaxis.live_transport import reply_budget
from schemaxis.identity_transition import proof
from schemaxis.live_data_worker import Worker
from schemaxis.pipeline import DefinitionGraph, RuntimeClosure
from test_durable_identity import Graph, expected
from test_live_identity import Backend, FILES

CATALOGUE = catalogue()


def refuse_created_extra(reply):
    """Reply admission refusing a reply that reports a newly created ``extra``."""
    if 'extra' in reply.get('transition', {}).get('created', []):
        raise SchemaxisError(Fault('LIVE_LIMIT', 'injected reply admission refusal', '$', 'live'))
    return reply_budget(reply)


class Counted(Backend):
    """Counting stand-in that can fail one named call and records every deleted handle.

    ``create`` fails before allocating; ``allocate`` registers the native object and
    then fails without returning it; ``port`` fails while resolving an output port.
    """

    def __init__(self):
        super().__init__()
        self.faults, self.deleted = set(), []

    def trip(self, call, label):
        if (call, label) in self.faults:
            self.faults.discard((call, label))
            raise RuntimeError('injected ' + call + ' failure of ' + label)

    def create(self, node, declaration, inputs, constructor):
        self.trip('create', node)
        handle = super().create(node, declaration, inputs, constructor)
        self.trip('allocate', node)
        return handle

    def output_port(self, handle, port):
        self.trip('port', self.labels[id(handle)])
        return super().output_port(handle, port)

    def configure(self, handle, declaration, values):
        super().configure(handle, declaration, values)
        self.trip('configure', self.labels[id(handle)])

    def update(self, handle, time):
        super().update(handle, time)
        self.trip('update', self.labels[id(handle)])

    def extents(self, handle):
        return self.extents_of(handle)

    def extents_of(self, handle):
        if 'file' in handle['values']:
            return [{'status': 'ok', 'bounds': list(FILES[handle['values']['file']])}]
        source = handle['inputs'].get('input')
        if isinstance(source, list):
            boxes = [self.extents_of(item)[0]['bounds'] for item in source]
            return [{'status': 'ok', 'bounds': [min(b[i] for b in boxes) if i % 2 == 0 else max(b[i] for b in boxes)
                                                for i in range(6)]}]
        return super().extents(handle)

    def delete(self, handle):
        self.trip('delete', self.labels[id(handle)])
        self.deleted.append(handle['id'])
        super().delete(handle)


def scene(*visible):
    return [{'id': 'main', 'visible': {key: {} for key in visible}, 'geometry': list(visible)}]


def document(*extra, visible=('skin',), files=('a.ply',)):
    return {'version': 'schemaxis/1', 'nodes': [
        {'id': 'mesh', 'filter': 'readPLY', 'options': {'files': list(files)}},
        {'id': 'skin', 'filter': 'shrink', 'inputs': {'input': 'mesh'}, 'options': {'factor': 0.5}},
        *copy.deepcopy(extra)], 'scenes': scene(*visible)}


EXTRA = {'id': 'extra', 'filter': 'shrink', 'inputs': {'input': 'mesh'}, 'options': {'factor': 0.25}}


class Resident(Graph):
    def __init__(self):
        super().__init__()
        self.native = Counted()
        self.bad_present = 0

    def present(self, prepared):
        if self.bad_present:
            self.bad_present -= 1
            raise RuntimeError('injected present failure')


class GraphTransitions(unittest.TestCase):
    def setUp(self):
        self.graph = Resident()
        self.addCleanup(self.graph.close)
        self.graph.apply(document())
        self.mesh = self.graph.active.handles['mesh']
        self.skin = self.graph.active.handles['skin']

    @property
    def native(self):
        return self.graph.native

    def since(self, count):
        return self.native.calls[count:]

    def assert_reader_kept(self):
        self.assertIs(self.mesh, self.graph.active.handles['mesh'])
        self.assertEqual({self.mesh['id']: 1}, {k: v for k, v in self.native.reads.items() if k == self.mesh['id']})
        self.assertEqual(1, self.graph.resets)

    def test_visible_sibling_addition_keeps_reader_and_untouched_consumer(self):
        start = len(self.native.calls)
        result = self.graph.apply(document(EXTRA, visible=('skin', 'extra')))
        self.assertEqual([('create', 'extra'), ('configure', 'extra'), ('update', 'extra')], self.since(start))
        self.assert_reader_kept()
        self.assertIs(self.skin, self.graph.active.handles['skin'])
        self.assertTrue(result['reused'])
        self.assertEqual(['extra'], result['updated'])
        self.assertEqual({'retained': ['mesh', 'skin'], 'unaffected': ['mesh', 'skin'], 'created': ['extra'],
                          'replaced': {}, 'affected': {}, 'retired': [], 'timeChanged': False}, result['transition'])
        self.assertEqual(['skin', 'extra'], [item['node'] for item in self.graph.geometry_objects])

    def test_remove_readd_and_reorder_visible_roots_without_rereading(self):
        self.graph.apply(document(EXTRA, visible=('skin', 'extra')))
        extra = self.graph.active.handles['extra']
        start = len(self.native.calls)
        self.graph.apply(document(EXTRA, visible=('extra', 'skin')))
        self.assertEqual([], self.since(start))
        self.assertIs(extra, self.graph.active.handles['extra'])
        self.assertEqual(['extra', 'skin'], [item['node'] for item in self.graph.geometry_objects])
        result = self.graph.apply(document(EXTRA))
        self.assertEqual([('delete', 'extra')], self.since(start))
        self.assertEqual(['extra'], result['transition']['retired'])
        self.graph.apply(document(EXTRA, visible=('extra', 'skin')))
        self.assertIsNot(extra, self.graph.active.handles['extra'])
        self.assertEqual([('delete', 'extra'), ('create', 'extra'), ('configure', 'extra'), ('update', 'extra')],
                         self.since(start))
        self.assert_reader_kept()
        self.assertIs(self.skin, self.graph.active.handles['skin'])

    def test_new_chain_option_change_and_old_reverse_removal_order(self):
        chain = [{'id': 'c1', 'filter': 'shrink', 'inputs': {'input': 'skin'}, 'options': {'factor': 0.9}},
                 {'id': 'c2', 'filter': 'shrink', 'inputs': {'input': 'c1'}, 'options': {'factor': 0.8}}]
        self.graph.apply(document(EXTRA, *chain, visible=('extra', 'c2')))
        extra, c1 = self.graph.active.handles['extra'], self.graph.active.handles['c1']
        start = len(self.native.calls)
        changed = document(EXTRA, *chain, visible=('extra', 'c2'))
        changed['nodes'][1]['options']['factor'] = 0.4
        result = self.graph.apply(changed)
        self.assertEqual([('configure', 'skin'), ('update', 'skin'), ('update', 'c1'), ('update', 'c2')],
                         self.since(start))
        self.assertEqual({'skin': 'configured', 'c1': 'dependency', 'c2': 'dependency'}, result['transition']['affected'])
        self.assertIs(extra, self.graph.active.handles['extra'])
        self.assertIs(c1, self.graph.active.handles['c1'])
        self.assertEqual(0.4, self.skin['values']['factor'])
        start = len(self.native.calls)
        self.graph.apply(document(EXTRA, visible=('extra',)))
        self.assertEqual([('delete', 'c2'), ('delete', 'c1'), ('delete', 'skin')], self.since(start))
        self.assert_reader_kept()

    def test_unselected_source_is_neither_created_nor_loaded(self):
        peer = {'id': 'peer', 'filter': 'readPLY', 'options': {'files': ['b.ply']}}
        start = len(self.native.calls)
        result = self.graph.apply(document(peer))
        self.assertEqual([], self.since(start))
        self.assertNotIn('peer', self.graph.active.handles)
        self.assertEqual(['mesh', 'skin'], result['transition']['retained'])

    def test_changed_peer_source_beside_independent_unchanged_reader(self):
        peer = {'id': 'peer', 'filter': 'readPLY', 'options': {'files': ['b.ply']}}
        view = {'id': 'view', 'filter': 'shrink', 'inputs': {'input': 'peer'}, 'options': {'factor': 0.5}}
        self.graph.apply(document(peer, view, visible=('skin', 'view')))
        old = self.graph.active.handles['peer']
        start = len(self.native.calls)
        changed = document(peer, view, visible=('skin', 'view'))
        changed['nodes'][2]['options']['files'] = ['a.ply']
        result = self.graph.apply(changed)
        self.assertEqual({'peer': 'constructor', 'view': 'inputReplaced'}, result['transition']['replaced'])
        self.assertEqual(['view', 'peer'], result['transition']['retired'])
        self.assertEqual([('delete', 'view'), ('delete', 'peer'), ('create', 'peer'), ('configure', 'peer'),
                          ('create', 'view'), ('configure', 'view'), ('update', 'peer'), ('update', 'view')],
                         self.since(start))
        self.assertEqual(1, self.native.reads[old['id']])
        self.assertEqual(1, self.native.reads[self.graph.active.handles['peer']['id']])
        self.assertEqual([[0, 1, 0, 2, 0, 3]], self.graph.active.observations['peer']['extents'])
        self.assertEqual([[0, 0.5, 0, 1, 0, 1.5]], self.graph.active.observations['view']['extents'])
        self.assert_reader_kept()
        self.assertIs(self.skin, self.graph.active.handles['skin'])

    def test_output_port_and_list_inputs_resolve_in_the_target_registry(self):
        port = {'id': 'port', 'filter': 'shrink', 'inputs': {'input': {'node': 'mesh', 'port': 0}}, 'options': {}}
        both = {'id': 'both', 'filter': 'append', 'inputs': {'input': ['skin', 'port']}}
        self.graph.apply(document(port, both, visible=('both',)))
        self.assertIs(self.mesh, self.graph.active.handles['port']['inputs']['input'])
        self.assertEqual([self.skin, self.graph.active.handles['port']], self.graph.active.handles['both']['inputs']['input'])
        self.assertIs(self.mesh, self.graph.active.objects.resolve('mesh', 'data'))
        self.assertIs(self.graph.active.handles['both'], self.graph.active.objects.resolve('both', 'data'))
        self.assert_reader_kept()

    def test_preserve_refusal_and_invalid_targets_make_no_native_calls(self):
        calls, state = list(self.native.calls), expected(self.graph)
        changed = document(files=('b.ply',))
        with self.assertRaises(SchemaxisError) as raised:
            self.graph.apply(changed, preserve=['mesh'])
        self.assertEqual('UNSUPPORTED_RESIDENT_TRANSITION', raised.exception.fault.code)
        self.assertEqual({'mesh': 'constructor'}, raised.exception.fault.observed['nodes'])
        for invalid, code in ((document(dict(EXTRA, id='skin')), 'DUPLICATE_NODE'),
                              (document(dict(EXTRA, inputs={'input': 'loop'}),
                                        {'id': 'loop', 'filter': 'shrink', 'inputs': {'input': 'extra'}},
                                        visible=('loop',)), 'PIPELINE_CYCLE')):
            with self.assertRaises(SchemaxisError) as raised:
                self.graph.apply(invalid)
            self.assertEqual(code, raised.exception.fault.code)
        self.assertEqual(calls, self.native.calls)
        self.assertEqual(state, expected(self.graph))
        _, plan = self.graph.prepare_transition(document(EXTRA, visible=('extra', 'skin')), ['mesh', 'skin'])
        self.assertEqual(['mesh', 'skin'], plan.unaffected)
        self.assertEqual(calls, self.native.calls)
        result = self.graph.apply(document(EXTRA, visible=('extra', 'skin')), preserve=['mesh', 'skin'])
        self.assertEqual(['extra'], result['updated'])

    def test_changed_time_refuses_preservation_and_rereads_only_when_applied(self):
        later = document()
        later['times'] = [1.0]
        with self.assertRaises(SchemaxisError) as raised:
            self.graph.apply(later, preserve=['mesh'])
        self.assertEqual({'mesh': 'time'}, raised.exception.fault.observed['nodes'])
        self.assertEqual(1, self.native.reads[self.mesh['id']])
        result = self.graph.apply(later)
        self.assertTrue(result['transition']['timeChanged'])
        self.assertIs(self.mesh, self.graph.active.handles['mesh'])
        self.assertEqual(2, self.native.reads[self.mesh['id']])
        start = len(self.native.calls)
        self.graph.apply(document(EXTRA, visible=('skin', 'extra')) | {'times': [1.0]})
        self.assertEqual([('create', 'extra'), ('configure', 'extra'), ('update', 'extra')], self.since(start))
        self.assertEqual(1.0, self.graph.active.last_time)

    def test_injected_native_failures_revert_without_rereading_the_reader(self):
        for call, label in (('configure', 'extra'), ('update', 'extra'), ('present', None), ('geometry', None),
                            ('reply', None)):
            with self.subTest(call=call):
                target = document(EXTRA, visible=('skin', 'extra'))
                if label:
                    self.native.faults.add((call, label))
                elif call == 'present':
                    self.graph.bad_present = 1
                elif call == 'geometry':
                    self.graph.bad_geometry = 1
                state, geometry = expected(self.graph), copy.deepcopy(self.graph.geometry_objects)
                with self.assertRaises(SchemaxisError) as raised:
                    with patch('schemaxis.live_runtime.reply_budget', refuse_created_extra if call == 'reply' else
                               reply_budget):
                        self.graph.apply(target)
                fault = raised.exception.fault
                self.assertEqual('APPLY_FAILED', fault.code)
                self.assertTrue(fault.observed['rolledBack'])
                self.assertEqual(['mesh', 'skin'], fault.observed['kept'])
                self.assertEqual(state, expected(self.graph))
                self.assertEqual(geometry, self.graph.geometry_objects)
                self.assertEqual(['mesh', 'skin'], list(self.graph.active.handles))
                self.assertFalse(self.graph.uncertain)
                self.assert_reader_kept()
                self.assertIs(self.skin, self.graph.active.handles['skin'])
                self.assertEqual(len(self.native.deleted), len(set(self.native.deleted)))
        self.graph.apply(document(EXTRA, visible=('skin', 'extra')))
        self.assert_reader_kept()

    def test_failure_before_construction_reverts_without_any_creation(self):
        port = {'id': 'port', 'filter': 'shrink', 'inputs': {'input': {'node': 'mesh', 'port': 0}}, 'options': {}}
        start = len(self.native.calls)
        self.native.faults.add(('port', 'mesh'))
        with self.assertRaises(SchemaxisError) as raised:
            self.graph.apply(document(port, visible=('skin', 'port')))
        self.assertEqual('APPLY_FAILED', raised.exception.fault.code)
        self.assertTrue(raised.exception.fault.observed['rolledBack'])
        self.assertEqual([], self.since(start))
        self.assertEqual({}, self.graph.active.unknown)
        self.assert_reader_kept()

    def test_create_failure_leaves_unknown_ownership_before_or_after_allocation(self):
        for call in ('create', 'allocate'):
            with self.subTest(call=call):
                graph = Resident()
                self.addCleanup(graph.close)
                graph.apply(document())
                mesh, skin = graph.active.handles['mesh'], graph.active.handles['skin']
                state = expected(graph)
                graph.native.faults.add((call, 'extra'))
                with self.assertRaises(SchemaxisError) as raised:
                    graph.apply(document(EXTRA, visible=('skin', 'extra')))
                fault = raised.exception.fault
                self.assertEqual('UNCERTAIN_STATE', fault.code)
                self.assertEqual(['mesh', 'skin'], fault.observed['owned'])
                self.assertEqual(['extra'], list(fault.observed['unknown']))
                self.assertEqual('create', fault.observed['unknown']['extra']['stage'])
                self.assertEqual('RuntimeError', fault.observed['unknown']['extra']['exceptionType'])
                self.assertEqual(call == 'allocate', 'extra' in graph.native.labels.values())
                self.assertTrue(graph.uncertain)
                self.assertEqual('uncertain', graph.status()['state'])
                self.assertEqual(state['revision'], graph.status()['revision'])
                for command, args in (('geometry', {}), ('apply', {'document': document()}), ('image', {'path': 'x'})):
                    with self.assertRaises(SchemaxisError) as refused:
                        graph.dispatch(command, args)
                    self.assertEqual('UNCERTAIN_STATE', refused.exception.fault.code)
                with self.assertRaises(SchemaxisError):
                    graph.prepare_transition(document())
                self.assertIs(mesh, graph.active.handles['mesh'])
                self.assertEqual(1, graph.native.reads[mesh['id']])
                resets = graph.resets
                graph.reset()
                self.assertEqual([skin['id'], mesh['id']], graph.native.deleted)
                self.assertEqual(resets + 1, graph.resets)

    def test_configure_failure_of_a_retained_consumer_replaces_only_that_consumer(self):
        changed = document()
        changed['nodes'][1]['options']['factor'] = 0.3
        self.native.faults.add(('configure', 'skin'))
        with self.assertRaises(SchemaxisError) as raised:
            self.graph.apply(changed)
        self.assertEqual(['mesh'], raised.exception.fault.observed['kept'])
        self.assertIsNot(self.skin, self.graph.active.handles['skin'])
        self.assertEqual(0.5, self.graph.active.handles['skin']['values']['factor'])
        self.assert_reader_kept()

    def test_delete_failure_keeps_ownership_uncertain_and_cleans_each_handle_once(self):
        self.graph.apply(document(EXTRA, visible=('skin', 'extra')))
        extra = self.graph.active.handles['extra']
        self.native.faults.add(('delete', 'extra'))
        with self.assertRaises(SchemaxisError) as raised:
            self.graph.apply(document())
        fault = raised.exception.fault
        self.assertEqual('UNCERTAIN_STATE', fault.code)
        self.assertEqual(['mesh', 'skin'], fault.observed['owned'])
        self.assertEqual(['extra'], fault.observed['abandoned'])
        self.assertTrue(self.graph.uncertain)
        for command, args in (('geometry', {}), ('apply', {'document': document()})):
            with self.assertRaises(SchemaxisError): self.graph.dispatch(command, args)
        self.assertEqual(1, self.native.reads[self.mesh['id']])
        self.graph.reset()
        self.assertEqual([self.skin['id'], self.mesh['id']], self.native.deleted)
        self.assertNotIn(extra['id'], self.native.deleted)

    def test_failed_reversal_is_uncertain_and_retains_every_owned_handle(self):
        changed = document()
        changed['nodes'][1]['options']['factor'] = 0.3
        self.native.faults.update({('update', 'skin'), ('create', 'skin')})
        with self.assertRaises(SchemaxisError) as raised:
            self.graph.apply(changed)
        self.assertEqual('UNCERTAIN_STATE', raised.exception.fault.code)
        self.assertEqual(['mesh'], raised.exception.fault.observed['owned'])
        self.assertIs(self.mesh, self.graph.active.handles['mesh'])
        self.graph.reset()
        self.assertEqual([self.skin['id'], self.mesh['id']], self.native.deleted)

    def test_identity_transition_still_follows_an_incremental_addition(self):
        target = document(EXTRA, visible=('skin', 'extra'))
        self.graph.apply(target)
        start = len(self.native.calls)
        self.graph.dispatch('graph-reidentify', {'expected': expected(self.graph),
                                                 'proofs': [{'proof': proof(target, '/nodes/0/id', 'globe'), 'reverse': False}]})
        self.assertIs(self.mesh, self.graph.active.handles['globe'])
        self.assertEqual([('relabel', 'mesh', 'globe')], self.since(start))
        renamed = copy.deepcopy(self.graph.document)
        renamed['nodes'][2]['options']['factor'] = 0.2
        self.graph.apply(renamed)
        self.assertEqual([('relabel', 'mesh', 'globe'), ('configure', 'extra'), ('update', 'extra')], self.since(start))
        self.assertEqual(1, self.native.reads[self.mesh['id']])


DECLARATIONS = {
    'source': {'inputs': {}, 'options': {'file': {'value': {'type': 'string'}, 'constructor': True},
                                         'level': {'value': {'type': 'number', 'default': 1}}},
               'commands': {'refresh': {}}},
    'filter': {'inputs': {'input': {'required': True}}, 'options': {'scale': {'value': {'type': 'number', 'default': 1}}}},
    'other': {'inputs': {'input': {'required': True}}, 'options': {'scale': {'value': {'type': 'number', 'default': 1}}}},
}


def primitive(*nodes, sweeps=None, definitions=None, times=None):
    raw = {'version': 'schemaxis/1', 'nodes': copy.deepcopy(list(nodes))}
    if sweeps: raw['sweeps'] = sweeps
    if definitions: raw['definitions'] = definitions
    if times: raw['times'] = times
    return raw


SRC = {'id': 'src', 'filter': 'source', 'options': {'file': 'a.ply'}}
DOWN = {'id': 'down', 'filter': 'filter', 'inputs': {'input': 'src'}}


class PrimitivePolicy(unittest.TestCase):
    def setUp(self):
        self.backend = Counted()
        self.closure = RuntimeClosure(DefinitionGraph(primitive(SRC, DOWN), DECLARATIONS), self.backend)
        self.addCleanup(self.closure.close)
        self.closure.activate(['down'])
        self.closure.apply(next(self.closure.selection.visits()))

    def plan(self, raw, roots=('down',), preserve=()):
        master = DefinitionGraph(raw, DECLARATIONS)
        return self.closure.prepare_transition(master, list(roots), next(master.select(list(roots)).visits()), preserve)

    def test_incompatible_shapes_replace_with_precise_reasons_before_any_call(self):
        calls = list(self.backend.calls)
        cases = {
            'filter': primitive(SRC, dict(DOWN, filter='other')),
            'inputs': primitive(SRC, {'id': 'peer', 'filter': 'source', 'options': {'file': 'a.ply'}},
                                dict(DOWN, inputs={'input': 'peer'})),
            'commands': primitive(dict(SRC, onVisit=['refresh']), DOWN),
            'constructor': primitive(dict(SRC, options={'file': 'b.ply'}), DOWN),
        }
        for reason, raw in cases.items():
            with self.subTest(reason=reason):
                plan = self.plan(raw)
                node = 'src' if reason in ('commands', 'constructor') else 'down'
                self.assertEqual(reason, plan.replaced[node])
        declarations = copy.deepcopy(DECLARATIONS)
        declarations['filter']['options']['scale']['value']['maximum'] = 9
        master = DefinitionGraph(primitive(SRC, DOWN), declarations)
        plan = self.closure.prepare_transition(master, ['down'], next(master.select(['down']).visits()))
        self.assertEqual({'down': 'declaration'}, plan.replaced)
        removed = primitive(SRC, dict(DOWN, options={'scale': 2}))
        self.assertEqual({}, self.plan(removed).replaced)
        self.assertEqual(calls, self.backend.calls)

    def test_constructor_policy_uses_effective_values_not_expression_text(self):
        self.closure.close()
        raw = primitive(dict(SRC, options={'file': {'$expr': 'name'}}), DOWN, definitions={'name': 'a.ply', 'unrelated': 1})
        self.closure = RuntimeClosure(DefinitionGraph(raw, DECLARATIONS), self.backend)
        self.closure.activate(['down'])
        self.closure.apply(next(self.closure.selection.visits()))
        unrelated = copy.deepcopy(raw)
        unrelated['definitions']['unrelated'] = 2
        self.assertEqual(['src', 'down'], self.plan(unrelated, preserve=['src', 'down']).unaffected)
        literal = primitive(SRC, DOWN)
        self.assertEqual(['src', 'down'], self.plan(literal).unaffected)
        renamed = copy.deepcopy(raw)
        renamed['definitions']['name'] = 'b.ply'
        self.assertEqual({'src': 'constructor', 'down': 'inputReplaced'}, self.plan(renamed).replaced)

    def test_commands_axes_and_observations_are_affected_only_when_provable(self):
        self.closure.close()
        raw = primitive(dict(SRC, onVisit=['refresh']), dict(DOWN, options={'scale': {'$sweep': 's'}}),
                        sweeps=[{'name': 's', 'values': [1, 2]}])
        self.closure = RuntimeClosure(DefinitionGraph(raw, DECLARATIONS), self.backend)
        self.closure.activate(['down'])
        visits = list(self.closure.selection.visits())
        self.closure.apply(visits[0])
        master = DefinitionGraph(raw, DECLARATIONS)
        same = self.closure.prepare_transition(master, ['down'], visits[0])
        self.assertEqual({'src': 'commands', 'down': 'dependency'}, same.affected)
        quiet = primitive(SRC, dict(DOWN, options={'scale': {'$sweep': 's'}}), sweeps=[{'name': 's', 'values': [1, 2]}])
        self.assertEqual('commands', self.plan(quiet).replaced['src'])
        self.closure.close()
        self.closure = RuntimeClosure(DefinitionGraph(quiet, DECLARATIONS), self.backend)
        self.closure.activate(['down'])
        self.closure.apply(visits[0])
        master = DefinitionGraph(quiet, DECLARATIONS)
        self.assertEqual({'down': 'configured'}, self.closure.prepare_transition(master, ['down'], visits[1]).affected)
        self.assertEqual({}, self.closure.prepare_transition(master, ['down'], visits[0]).affected)
        observing = primitive(SRC, dict(DOWN, options={'scale': {'$observe': 'src', 'path': ['points']}}))
        self.closure.close()
        self.closure = RuntimeClosure(DefinitionGraph(observing, DECLARATIONS), self.backend)
        self.closure.activate(['down'])
        self.closure.apply(next(self.closure.selection.visits()))
        self.assertEqual(['src', 'down'], self.plan(observing, preserve=['down']).unaffected)
        same = primitive(SRC, dict(DOWN, options={'scale': {'$expr': 'extents(src).deltaX * 4'}}))
        self.assertEqual(['src', 'down'], self.plan(same, preserve=['down']).unaffected)
        changed = primitive(SRC, dict(DOWN, options={'scale': {'$expr': 'extents(src).deltaX * 5'}}))
        with self.assertRaises(SchemaxisError) as raised:
            self.plan(changed, preserve=['down'])
        self.assertEqual({'down': 'configured'}, raised.exception.fault.observed['nodes'])

    def test_stale_plans_and_unusable_closures_are_refused(self):
        plan = self.plan(primitive(SRC, DOWN))
        self.closure.apply(next(self.closure.selection.visits()))
        with self.assertRaises(SchemaxisError) as raised:
            self.closure.transition(plan)
        self.assertEqual('STALE_TRANSITION', raised.exception.fault.code)
        with self.assertRaises(SchemaxisError) as raised:
            self.plan(primitive(SRC, DOWN), preserve=['absent'])
        self.assertEqual({'absent': 'notResident'}, raised.exception.fault.observed['nodes'])
        self.closure.failed = True
        with self.assertRaises(SchemaxisError) as raised:
            self.plan(primitive(SRC, DOWN))
        self.assertEqual('CLOSED_PIPELINE', raised.exception.fault.code)


def data_document(*extra, files=('a.ply',), definitions=None):
    raw = {'version': 'schemaxis/1', 'nodes': [
        {'id': 'mesh', 'filter': 'readPLY', 'options': {'files': list(files)}},
        {'id': 'skin', 'filter': 'shrink', 'inputs': {'input': 'mesh'}, 'options': {'factor': 0.5}},
        *copy.deepcopy(extra)]}
    if definitions: raw['definitions'] = definitions
    return raw


STATE = {'timeIndex': 0, 'indices': {}}


def many_ports(backend, handle):
    """Sixty-four measured extent ports for ``extra``, enough to exceed a small reply budget."""
    result = Counted.extents_of(backend, handle)
    return result * 64 if backend.labels[id(handle)] == 'extra' else result


class DataTransitions(unittest.TestCase):
    def setUp(self):
        self.backend = Counted()
        planner = patch('schemaxis.live_data_worker.registry.binding', return_value=self.plan)
        planner.start()
        self.addCleanup(planner.stop)
        self.worker = Worker('paraview')
        self.addCleanup(self.worker.close)
        self.worker.dispatch('data-load', {'document': data_document(), 'roots': ['skin'], 'state': STATE})
        self.mesh = self.worker.active.handles['mesh']

    def plan(self, document, **_):
        return DefinitionGraph(document, CATALOGUE), self.backend

    def load(self, document, roots, preserve=None):
        if preserve is None:
            return self.worker.dispatch('data-load', {'document': document, 'roots': roots, 'state': STATE})
        return self.worker.load(document, roots, STATE, preserve)

    def test_direct_load_adds_sibling_and_keeps_reader_beside_unrelated_definition(self):
        start = len(self.backend.calls)
        reply = self.load(data_document(EXTRA, definitions={'unrelated': 1}), ['skin', 'extra'])
        self.assertTrue(reply['reused'])
        self.assertEqual(['extra'], reply['created'])
        self.assertEqual(['extra'], reply['updated'])
        self.assertEqual([('create', 'extra'), ('configure', 'extra'), ('update', 'extra')], self.backend.calls[start:])
        self.assertIs(self.mesh, self.worker.active.handles['mesh'])
        self.assertEqual(1, self.backend.reads[self.mesh['id']])
        self.assertEqual({'skin', 'extra', 'mesh'}, {item['node'] for item in reply['extents']})

    def test_preserving_load_refuses_before_calls_and_reverts_native_failure(self):
        calls = list(self.backend.calls)
        with self.assertRaises(SchemaxisError) as raised:
            self.load(data_document(files=('b.ply',)), ['skin'], preserve=['mesh'])
        self.assertEqual({'mesh': 'constructor'}, raised.exception.fault.observed['nodes'])
        self.assertEqual(calls, self.backend.calls)
        self.backend.faults.add(('update', 'extra'))
        with self.assertRaises(SchemaxisError) as raised:
            self.load(data_document(EXTRA), ['skin', 'extra'], preserve=['mesh', 'skin'])
        self.assertEqual('LOAD_FAILED', raised.exception.fault.code)
        self.assertEqual(['mesh', 'skin'], raised.exception.fault.observed['kept'])
        self.assertEqual(['mesh', 'skin'], list(self.worker.active.handles))
        self.assertEqual(data_document(), self.worker.document)
        self.assertIs(self.mesh, self.worker.active.handles['mesh'])
        self.assertEqual(1, self.backend.reads[self.mesh['id']])
        reply = self.load(data_document(EXTRA), ['skin', 'extra'], preserve=['mesh', 'skin'])
        self.assertEqual(['extra'], reply['created'])
        self.assertEqual(1, self.backend.reads[self.mesh['id']])

    def snapshot(self):
        active = self.worker.active
        return (copy.deepcopy(self.worker.document), active.master, active.selection.roots,
                copy.deepcopy(active.observations), dict(active.handles), copy.deepcopy(active.values))

    def assert_restored(self, snapshot):
        document, master, roots, observations, handles, values = snapshot
        active = self.worker.active
        self.assertEqual(document, self.worker.document)
        self.assertIs(master, active.master)
        self.assertEqual(roots, active.selection.roots)
        self.assertEqual(observations, active.observations)
        self.assertEqual(values, active.values)
        self.assertEqual(list(handles), list(active.handles))
        for key, handle in handles.items():
            self.assertIs(handle, active.handles[key])
        self.assertEqual(['mesh', 'skin'], sorted(self.backend.labels.values()))
        self.assertEqual(1, self.backend.reads[self.mesh['id']])
        self.assertFalse(self.worker.uncertain)
        self.assertFalse(active.failed)

    def test_preserving_reply_admission_is_inside_the_transaction(self):
        before = self.snapshot()
        with patch.object(Counted, 'extents', many_ports), patch.object(live_transport, 'MAX_BYTES', 4000):
            report = self.worker.prepare_load(data_document(EXTRA), ['skin', 'extra'], STATE, ['mesh', 'skin'])[-1]
            self.assertEqual(['extra'], report.created)
            with self.assertRaises(SchemaxisError) as raised:
                self.load(data_document(EXTRA), ['skin', 'extra'], preserve=['mesh', 'skin'])
        self.assertEqual('LOAD_FAILED', raised.exception.fault.code)
        self.assertTrue(raised.exception.fault.observed['rolledBack'])
        self.assertIn('transfer limit', raised.exception.fault.observed['cause'])
        self.assert_restored(before)
        reply = self.load(data_document(EXTRA), ['skin', 'extra'], preserve=['mesh', 'skin'])
        self.assertEqual(['extra'], reply['created'])
        self.assertEqual(data_document(EXTRA), self.worker.document)
        self.assertEqual(1, self.backend.reads[self.mesh['id']])

    def test_failed_reversal_of_reply_admission_is_uncertain(self):
        self.backend.faults.add(('delete', 'extra'))
        with patch.object(Counted, 'extents', many_ports), patch.object(live_transport, 'MAX_BYTES', 4000):
            with self.assertRaises(SchemaxisError) as raised:
                self.load(data_document(EXTRA), ['skin', 'extra'], preserve=['mesh', 'skin'])
        fault = raised.exception.fault
        self.assertEqual('UNCERTAIN_STATE', fault.code)
        self.assertEqual(['extra'], fault.observed['abandoned'])
        self.assertEqual(data_document(), self.worker.document)
        self.assertTrue(self.worker.status()['uncertain'])
        with self.assertRaises(SchemaxisError) as refused:
            self.load(data_document(), ['skin'])
        self.assertEqual('UNCERTAIN_STATE', refused.exception.fault.code)
        self.assertEqual(1, self.backend.reads[self.mesh['id']])

    def test_create_failure_in_a_preserving_load_is_unknown_ownership(self):
        skin = self.worker.active.handles['skin']
        self.backend.faults.add(('allocate', 'extra'))
        with self.assertRaises(SchemaxisError) as raised:
            self.load(data_document(EXTRA), ['skin', 'extra'], preserve=['mesh', 'skin'])
        fault = raised.exception.fault
        self.assertEqual('UNCERTAIN_STATE', fault.code)
        self.assertEqual(['mesh', 'skin'], fault.observed['owned'])
        self.assertEqual(['extra'], list(fault.observed['unknown']))
        self.assertEqual(data_document(), self.worker.document)
        self.assertIn('extra', self.backend.labels.values())
        for document, preserve in ((data_document(), ['mesh']), (data_document(), None)):
            with self.assertRaises(SchemaxisError) as refused:
                self.load(document, ['skin'], preserve=preserve)
            self.assertEqual('UNCERTAIN_STATE', refused.exception.fault.code)
        self.assertEqual(1, self.backend.reads[self.mesh['id']])
        self.worker.close()
        self.assertEqual([skin['id'], self.mesh['id']], self.backend.deleted)
        self.assertEqual(['extra'], list(self.backend.labels.values()))

    def test_direct_load_failures_release_known_data_without_success(self):
        for fault, code in ((('reply', None), 'LIVE_LIMIT'), (('allocate', 'extra'), 'PIPELINE_EXECUTION_FAILED')):
            with self.subTest(fault=fault[0]):
                if fault[1]:
                    self.backend.faults.add(fault)
                with patch.object(Counted, 'extents', many_ports if fault[0] == 'reply' else Counted.extents), \
                        patch.object(live_transport, 'MAX_BYTES', 4000 if fault[0] == 'reply' else live_transport.MAX_BYTES):
                    with self.assertRaises(SchemaxisError) as raised:
                        self.load(data_document(EXTRA), ['skin', 'extra'])
                self.assertEqual(code, raised.exception.fault.code)
                self.assertEqual(fault[0] == 'allocate', raised.exception.fault.observed.get('unknownOwner', False))
                self.assertIsNone(self.worker.active)
                self.assertIsNone(self.worker.document)
                self.assertEqual(len(self.backend.deleted), len(set(self.backend.deleted)))
                self.load(data_document(), ['skin'])
                self.mesh = self.worker.active.handles['mesh']

    def test_direct_load_failure_keeps_its_documented_release(self):
        self.backend.faults.add(('update', 'extra'))
        with self.assertRaises(SchemaxisError):
            self.load(data_document(EXTRA), ['skin', 'extra'])
        self.assertIsNone(self.worker.active)
        self.assertEqual(sorted(set(self.backend.deleted)), sorted(self.backend.deleted))
        self.assertIn(self.mesh['id'], self.backend.deleted)


if __name__ == '__main__':
    unittest.main()
