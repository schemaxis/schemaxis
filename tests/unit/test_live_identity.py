# Copyright (C) 2026 David L. F. Gaden.
"""Witnessed identity views for resident Live Data, with counting native stand-ins.

Host planning, the checked rename, the Live Data worker, the shared RuntimeClosure
primitive, the declared ParaView relabel hook and transport validation are real.
Only executable discovery and the native application are replaced.
"""
import copy
import tempfile
import unittest
from unittest.mock import patch

from types import SimpleNamespace

from schemaxis.adaptors import registry
from schemaxis.adaptors.paraview.native import ParaViewBackend
from schemaxis.adaptors.paraview.filters import catalogue
from schemaxis.core.faults import SchemaxisError
from schemaxis.errors import fail
from schemaxis.live_data import LiveDataSession
from schemaxis.live_data_worker import Worker
from schemaxis.live_transport import validate
from schemaxis.pipeline import DefinitionGraph, RuntimeClosure, digest
from schemaxis.storage import digest as input_digest

CATALOGUE = catalogue()
NATIVE = registry.metadata('paraview')['extents']['native']
INSPECT = registry.metadata('paraview')['extents']['inspect']
REAL_BINDING = registry.binding
FILES = {'a.ply': [0, 1, 0, 2, 0, 3], 'b.ply': [5, 6, 5, 6, 5, 6]}


class Backend:
    """Counts every native call; a source update stands for one file read."""

    def __init__(self):
        self.labels, self.calls, self.reads = {}, [], {}
        self.fail_pairs, self.raw_pairs = set(), set()

    def create(self, node, declaration, inputs, constructor):
        if node in self.labels.values():
            fail('NATIVE_IDENTITY_COLLISION', 'native label already exists', node)
        handle = {'id': len(self.calls), 'values': dict(constructor), 'inputs': inputs}
        self.labels[id(handle)] = node
        self.calls.append(('create', node))
        return handle

    def output_port(self, handle, port):
        return handle

    def configure(self, handle, declaration, values):
        handle['values'].update(copy.deepcopy(values))
        self.calls.append(('configure', self.labels[id(handle)]))

    def update(self, handle, time):
        label = self.labels[id(handle)]
        self.calls.append(('update', label))
        if not handle['inputs']:
            self.reads[handle['id']] = self.reads.get(handle['id'], 0) + 1

    def command(self, handle, name):
        self.calls.append(('command', self.labels[id(handle)]))

    def observe(self, handle):
        return {'points': 4}

    def extents(self, handle):
        if 'files' in handle['values']:
            return [{'status': 'ok', 'bounds': list(FILES[handle['values']['files'][0]])}]
        bounds = self.extents(handle['inputs']['input'])[0]['bounds']
        factor = handle['values'].get('factor', 0.5)
        return [{'status': 'ok', 'bounds': [v * factor for v in bounds]}]

    def relabel(self, handle, old, new):
        if self.labels.get(id(handle)) != old:
            fail('IDENTITY_TRANSITION_MISMATCH', 'label differs', old)
        if (old, new) in self.fail_pairs:
            fail('NATIVE_RELABEL_FAILED', 'injected', old)
        if (old, new) in self.raw_pairs:  # A native call that changed the label, then raised.
            self.labels[id(handle)] = new
            raise RuntimeError('injected after the native label changed')
        if new in self.labels.values():
            fail('NATIVE_IDENTITY_COLLISION', 'native label exists', new)
        self.labels[id(handle)] = new
        self.calls.append(('relabel', old, new))

    def delete(self, handle):
        self.calls.append(('delete', self.labels.pop(id(handle))))

    def count(self, kind):
        return sum(1 for call in self.calls if call[0] == kind)


def plan(document, **_):
    return DefinitionGraph(document, CATALOGUE), Process.current.backend


def inspected(active, node, port=0, geometry=False):
    handle = active.handles[node]
    return {'node': node, 'handle': handle['id'], 'label': active.backend.labels[id(handle)]}


def binding(path):
    if path == NATIVE:
        return plan
    if path == INSPECT:
        return inspected
    return REAL_BINDING(path)


class Process:
    """One stand-in native process with its own label namespace."""
    instances = []
    current = None

    def __init__(self, provider, executable, directory, timeout):
        Process.instances.append(self)
        self.backend = Backend()
        self.worker = Worker(provider)
        self.closed = False
        self.requests = []

    def request(self, command, **args):
        validate(command, args, 'paraview')
        self.requests.append(command)
        Process.current = self
        with patch('schemaxis.live_data_worker.registry.binding', side_effect=binding):
            return copy.deepcopy(self.worker.dispatch(command, copy.deepcopy(args)))

    def request_retained(self, command, **args):
        # Synchronous in-process transport: exceptions never destroy the worker.
        return self.request(command, **args)

    def close(self):
        self.worker.close()
        self.closed = True


def document(*extra):
    return {'version': 'schemaxis/1',
            'definitions': {'box': {'$expr': 'inflate(extents(mesh), 0.1)'}, 'part': {'$expr': 'extents(skin)'}},
            'nodes': [{'id': 'mesh', 'filter': 'readPLY', 'options': {'files': ['a.ply']}},
                      {'id': 'skin', 'filter': 'shrink', 'inputs': {'input': 'mesh'}, 'options': {'factor': 0.5}},
                      *extra]}


def faulted(test, code, call, *args, **kwargs):
    with test.assertRaises(SchemaxisError) as caught:
        call(*args, **kwargs)
    test.assertEqual(caught.exception.fault.code, code, caught.exception.fault)
    return caught.exception.fault


class Fixture(unittest.TestCase):
    def setUp(self):
        Process.instances = []
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.live = LiveDataSession(self.temp.name, Process)
        self.addCleanup(self.live.close)
        discovery = patch('schemaxis.adaptors.paraview.mvp.runners.require_paraview', return_value='/test/pvpython')
        discovery.start()
        self.addCleanup(discovery.stop)
        self.old = document()

    @property
    def backend(self):
        return Process.instances[0].backend

    @property
    def created(self):
        return len(Process.instances)

    def request(self, input, view=None, **extra):
        return {'input': input, 'sessionDocument': 'doc', **({'view': view} if view else {}), **extra}

    def rename(self, input, pointer='/nodes/0/id', name='globe', view=None, **extra):
        request = self.request(input, view, **extra)
        preview = self.live.prepare_identity_transition(request, pointer, name, input_digest(input))
        expected = {k: preview['transition'][k] for k in ('inputDigest', 'outputDigest', 'policyDigest')}
        return preview, self.live.accept_identity_transition(request, pointer, name, expected)

    def snapshot(self):
        return copy.deepcopy({'cache': self.live.cache, 'visits': self.live.visits, 'views': self.live.views,
                              'roots': self.live.roots, 'accepted': self.live.accepted,
                              'edges': {k: v['result'] for k, v in self.live.edges.items()},
                              'workers': {k: {f: v for f, v in w.items() if f != 'client'}
                                          for k, w in self.live.workers.items()},
                              'calls': [list(p.backend.calls) for p in Process.instances], 'created': self.created})

    def worker(self):
        (worker,) = self.live.workers.values()
        return worker['client'].worker

    def states(self, input, view=None):
        result = self.live.refresh(self.request(input, view))
        return [record['state'] for record in result['records']]

    def loaded(self, input, view=None):
        nodes = self.live.selection(self.request(input, view))['nodes']
        return {node['id']: (node['loaded'], node['observed']) for node in nodes}


class WitnessedViews(Fixture):
    def test_bare_old_window_and_witnessed_new_view_share_one_resident_reader(self):
        self.live.load(self.request(self.old, nodes=['skin']))
        active = self.worker().active
        mesh, skin = active.handles['mesh'], active.handles['skin']
        values, last = copy.deepcopy(active.values), active.last_time
        before = self.snapshot()
        preview = self.live.prepare_identity_transition(self.request(self.old), '/nodes/0/id', 'globe',
                                                         input_digest(self.old))
        self.assertEqual(self.snapshot(), before)  # Preview and Cancel change nothing.
        self.assertEqual(preview['input']['definitions']['box']['$expr'], 'inflate(extents(`globe`), 0.1)')
        _, accepted = self.rename(self.old)
        new = accepted['input']
        self.assertEqual(accepted['retainedObservations'], 2)
        self.assertEqual(accepted['adoptedWorkers'], 1)
        self.assertEqual(len(self.live.cache), 4)  # Old observations are retained beside the new view.
        self.assertEqual(self.backend.count('relabel'), 0)  # Native alignment is lazy.
        for _ in range(3):
            self.assertEqual(self.loaded(self.old), {'mesh': (True, True), 'skin': (True, True)})
            self.assertEqual(self.states(self.old), ['resolved', 'resolved'])
            self.assertEqual(self.live.inspect(self.request(self.old), 'mesh')['handle'], mesh['id'])
            self.assertEqual(self.loaded(new, accepted['to']), {'globe': (True, True), 'skin': (True, True)})
            self.assertEqual(self.states(new, accepted['to']), ['resolved', 'resolved'])
            result = self.live.inspect(self.request(new, accepted['to']), 'globe')
            self.assertEqual((result['handle'], result['label']), (mesh['id'], 'globe'))
        active = self.worker().active
        self.assertIs(active.handles['globe'], mesh)
        self.assertIs(active.handles['skin'], skin)
        self.assertEqual(active.values, {'globe': values['mesh'], 'skin': values['skin']})
        self.assertEqual(active.last_time, last)
        self.assertEqual((self.created, self.backend.count('create'), self.backend.count('delete')), (1, 2, 0))
        self.assertEqual(self.backend.reads, {mesh['id']: 1})
        self.assertEqual(self.backend.count('relabel'), 5)  # Old, then four alternations.
        worker = self.worker()
        self.assertEqual(worker.transition_count, 5)
        self.assertEqual([t['steps'] for t in worker.transitions], [[['mesh', 'globe']], [['globe', 'mesh']]] * 2
                         + [[['mesh', 'globe']]])
        evaluated = self.live.evaluate(self.request(new, accepted['to'], expression='box'))['records'][0]
        original = self.live.evaluate(self.request(self.old, expression='box'))['records'][0]
        self.assertEqual((evaluated['state'], evaluated['value']), ('resolved', original['value']))
        self.assertEqual(self.live.evaluate(self.request(self.old, expression='box'))['records'][0]['state'], 'resolved')

    def test_derived_rename_and_witnessed_undo_redo_are_idempotent(self):
        self.live.load(self.request(self.old, nodes=['skin']))
        handles = dict(self.worker().active.handles)
        _, first = self.rename(self.old, '/nodes/1/id', 'hull')
        _, again = self.rename(self.old, '/nodes/1/id', 'hull')
        self.assertEqual(first, again)
        self.assertEqual(len(self.live.edges), 1)
        new = first['input']
        for _ in range(2):  # Undo to the bare original, Redo to the witnessed view.
            self.assertEqual(self.states(new, first['to']), ['resolved', 'resolved'])
            self.assertEqual(self.states(self.old), ['resolved', 'resolved'])
        active = self.worker().active
        self.assertIs(active.handles['mesh'], handles['mesh'])
        self.assertIs(active.handles['skin'], handles['skin'])
        self.assertEqual((self.backend.count('create'), self.backend.count('relabel')), (2, 4))
        self.assertEqual(sum(self.backend.reads.values()), 1)

    def test_chain_and_inverse_rename_keep_views_isolated(self):
        self.live.load(self.request(self.old, nodes=['skin']))
        mesh = self.worker().active.handles['mesh']
        _, first = self.rename(self.old)
        _, second = self.rename(first['input'], name='planet', view=first['to'])
        _, inverse = self.rename(first['input'], name='mesh', view=first['to'])
        self.assertEqual(inverse['input']['nodes'], self.old['nodes'])  # Same identities, a separate view.
        self.assertNotEqual(inverse['to'], first['from'])
        self.assertEqual(self.states(second['input'], second['to']), ['resolved', 'resolved'])
        self.assertEqual(self.worker().active.backend.labels[id(mesh)], 'planet')
        self.assertEqual(self.states(self.old), ['resolved', 'resolved'])  # Two witnessed steps back.
        self.assertEqual(self.states(self.old, inverse['to']), ['resolved', 'resolved'])
        self.assertIs(self.worker().active.handles['mesh'], mesh)
        self.assertEqual((self.created, self.backend.count('create'), sum(self.backend.reads.values())), (1, 2, 1))
        faulted(self, 'IDENTITY_VIEW_REQUIRED', self.rename, second['input'], name='other')
        # A later view's draft holding a new node with the original name cannot claim the original view.
        reused = copy.deepcopy(second['input'])
        reused['nodes'].append({'id': 'mesh', 'filter': 'readPLY', 'options': {'files': ['a.ply']}})
        calls = len(self.backend.calls)
        self.assertEqual(self.loaded(reused)['mesh'][0], False)
        self.live.refresh(self.request(reused, nodes=['mesh']))
        self.assertEqual(len(self.backend.calls), calls)
        self.assertEqual(self.live.renamed(('paraview', 'doc', None)), {'globe', 'planet'})

    def test_unrelated_new_old_name_never_acquires_the_renamed_object(self):
        self.live.load(self.request(self.old, nodes=['mesh']))
        mesh = self.worker().active.handles['mesh']
        _, accepted = self.rename(self.old)
        reused = copy.deepcopy(accepted['input'])
        reused['nodes'].append({'id': 'mesh', 'filter': 'readPLY', 'options': {'files': ['a.ply']}})
        calls = len(self.backend.calls)
        # A bare draft containing the witnessed destination is not the original view.
        self.assertEqual(self.loaded(reused)['mesh'][0], False)
        self.live.refresh(self.request(reused, nodes=['mesh']))
        self.assertEqual((len(self.backend.calls), self.created), (calls, 1))
        # In the witnessed view, the new node is a new source; the renamed one keeps its object.
        self.assertEqual(self.loaded(reused, accepted['to'])['mesh'][0], False)
        self.live.load(self.request(reused, accepted['to'], nodes=['mesh']))
        active = self.worker().active
        self.assertIs(active.handles['globe'], mesh)
        self.assertIsNot(active.handles['mesh'], mesh)
        self.assertEqual((self.created, self.backend.count('create')), (1, 2))

    def test_visit_recipe_document_and_operation_isolation(self):
        self.live.load(self.request(self.old, nodes=['skin']))
        _, accepted = self.rename(self.old)
        new = accepted['input']
        self.assertIsNone(self.live.observations(self.request(new, accepted['to'], state={'timeIndex': 1})))
        changed = copy.deepcopy(new)
        changed['nodes'][0]['options']['files'] = ['b.ply']
        self.assertEqual(self.loaded(changed, accepted['to'])['globe'], (False, False))
        self.assertEqual(self.states(changed, accepted['to']), ['unresolved', 'unresolved'])
        self.assertEqual(self.created, 1)
        # Another document: views do not cross; the original content stays shareable.
        faulted(self, 'IDENTITY_VIEW_MISMATCH', self.live.selection,
                {'input': new, 'sessionDocument': 'other', 'view': accepted['to']})
        other = self.live.refresh({'input': self.old, 'sessionDocument': 'other'})
        self.assertEqual([r['state'] for r in other['records']], ['resolved', 'resolved'])
        foreign = self.live.refresh({'input': new, 'sessionDocument': 'other'})
        self.assertEqual(foreign['records'][1]['state'], 'resolved')  # Content-shared observation.
        self.assertEqual(self.created, 1)

    def test_workflow_operation_scope(self):
        workflow = {'version': 'schemaxis.workflow/1', 'operations': [
            {'id': 'a', 'document': document()}, {'id': 'b', 'document': document()}]}
        for operation in ('a', 'b'):
            self.live.load(self.request(workflow, operation=operation, nodes=['mesh']))
        faulted(self, 'IDENTITY_SCOPE_MISMATCH', self.rename, workflow, '/operations/1/document/nodes/0/id',
                operation='a')
        _, accepted = self.rename(workflow, '/operations/0/document/nodes/0/id', operation='a')
        renamed = accepted['input']
        self.assertEqual(renamed['operations'][1], workflow['operations'][1])
        self.assertTrue(self.live.selection(self.request(renamed, operation='b'))['nodes'][0]['loaded'])
        self.assertEqual(self.live.selection(self.request(renamed, accepted['to'], operation='a'))['nodes'][0]['id'],
                         'globe')
        faulted(self, 'IDENTITY_VIEW_MISMATCH', self.live.selection, self.request(renamed, accepted['to'], operation='b'))

    def test_unload_close_and_bounded_lifetime(self):
        self.live.load(self.request(self.old, nodes=['skin']))
        _, accepted = self.rename(self.old)
        self.live.unload()
        self.assertEqual(self.states(accepted['input'], accepted['to']), ['resolved', 'resolved'])
        self.assertEqual(self.loaded(accepted['input'], accepted['to'])['globe'], (False, True))
        self.assertEqual(self.created, 1)
        self.live.close()
        faulted(self, 'SESSION_CLOSED', self.rename, self.old)


class AtomicRefusals(Fixture):
    def test_noop_stale_forged_collision_changed_and_unknown_views_change_nothing(self):
        self.live.load(self.request(self.old, nodes=['skin']))
        before = self.snapshot()
        request, current = self.request(self.old), input_digest(self.old)
        faulted(self, 'IDENTITY_TRANSITION_NOOP', self.live.prepare_identity_transition, request, '/nodes/0/id', 'mesh', current)
        faulted(self, 'STALE_IDENTITY_INPUT', self.live.prepare_identity_transition, request, '/nodes/0/id', 'globe', 'x' * 64)
        faulted(self, 'IDENTITY_COLLISION', self.live.prepare_identity_transition, request, '/nodes/0/id', 'skin', current)
        preview = self.live.prepare_identity_transition(request, '/nodes/0/id', 'globe', current)
        expected = {k: preview['transition'][k] for k in ('inputDigest', 'outputDigest', 'policyDigest')}
        faulted(self, 'STALE_IDENTITY_TRANSITION', self.live.accept_identity_transition, request, '/nodes/0/id',
                'globe', {**expected, 'outputDigest': '0' * 64})
        faulted(self, 'STALE_IDENTITY_TRANSITION', self.live.accept_identity_transition, request, '/nodes/0/id',
                'planet', expected)
        faulted(self, 'INVALID_REQUEST', self.live.accept_identity_transition, request, '/nodes/0/id', 'globe',
                {**expected, 'identityChanges': [{'old': 'mesh', 'new': 'globe'}]})
        changed = copy.deepcopy(self.old)
        changed['nodes'][0]['options']['files'] = ['b.ply']
        faulted(self, 'STALE_IDENTITY_INPUT', self.live.accept_identity_transition, self.request(changed),
                '/nodes/0/id', 'globe', expected)
        faulted(self, 'UNKNOWN_IDENTITY_VIEW', self.live.accept_identity_transition, self.request(self.old, 'forged'),
                '/nodes/0/id', 'globe', expected)
        faulted(self, 'UNSUPPORTED_IDENTITY', self.live.prepare_identity_transition, request, '/definitions/box',
                'globe', current)
        self.assertEqual(self.snapshot(), before)

    def test_unsupported_relabel_refuses_before_adoption(self):
        self.live.load(self.request(self.old, nodes=['mesh']))
        before = self.snapshot()
        extents = {k: v for k, v in registry.metadata('paraview')['extents'].items() if k != 'relabel'}
        with patch.dict(registry.metadata('paraview'), {'extents': extents}):
            faulted(self, 'UNSUPPORTED_IDENTITY_TRANSITION', self.rename, self.old)
        self.assertEqual(self.snapshot(), before)

    def test_native_relabel_failure_keeps_handles_and_rollback_failure_is_uncertain(self):
        self.live.load(self.request(self.old, nodes=['skin']))
        mesh = self.worker().active.handles['mesh']
        _, first = self.rename(self.old)
        _, second = self.rename(first['input'], '/nodes/1/id', 'hull', view=first['to'])
        self.backend.fail_pairs = {('skin', 'hull')}
        faulted(self, 'NATIVE_RELABEL_FAILED', self.live.refresh, self.request(second['input'], second['to']))
        active = self.worker().active
        self.assertIs(active.handles['mesh'], mesh)  # First step was reversed; nothing rebuilt.
        self.assertEqual(self.backend.labels[id(mesh)], 'mesh')
        self.assertEqual(self.states(self.old), ['resolved', 'resolved'])
        self.backend.fail_pairs = {('skin', 'hull'), ('globe', 'mesh')}
        faulted(self, 'IDENTITY_TRANSITION_UNCERTAIN', self.live.refresh, self.request(second['input'], second['to']))
        self.assertTrue(self.live.status()['sessions'][0]['uncertain'])
        self.assertEqual(self.states(self.old), ['resolved', 'resolved'])  # Cached, not refreshed.
        calls = len(self.backend.calls)
        faulted(self, 'IDENTITY_TRANSITION_UNAVAILABLE', self.live.load, self.request(self.old, nodes=['skin']))
        self.assertEqual((len(self.backend.calls), self.created), (calls, 1))
        self.live.unload()
        self.assertFalse(self.live.status()['enabled'])


class Primitive(unittest.TestCase):
    def setUp(self):
        self.backend = Backend()
        self.document = {'version': 'schemaxis/1', 'definitions': {'box': {'$expr': 'extents(mesh)'}},
                         'nodes': [{'id': 'mesh', 'filter': 'readPLY', 'options': {'files': ['a.ply']}},
                                   {'id': 'skin', 'filter': 'shrink', 'inputs': {'input': 'mesh'},
                                    'options': {'factor': {'$expr': '0.5'}}}]}
        self.active = RuntimeClosure(DefinitionGraph(self.document, CATALOGUE), self.backend)
        selection = self.active.activate(['skin'])
        self.active.apply({'time': 0.0, 'timeIndex': 0, 'indices': {}, 'sweeps': {}})
        self.selection = selection

    @staticmethod
    def planner(document):
        return DefinitionGraph(document, CATALOGUE)

    @staticmethod
    def altering(document):
        changed = copy.deepcopy(document)
        if any(node['id'] == 'globe' for node in changed['nodes']):
            changed['nodes'][1]['options']['factor'] = 0.25
        return DefinitionGraph(changed, CATALOGUE)

    def relabel(self, handle, old, new):
        self.backend.relabel(handle, old, new)

    def test_rebinds_the_same_objects_without_native_execution(self):
        handles, observations = dict(self.active.handles), copy.deepcopy(self.active.observations)
        calls = len(self.backend.calls)
        replacement = self.active.reidentify([['mesh', 'globe']], self.planner, self.relabel)
        self.assertEqual(self.backend.calls[calls:], [('relabel', 'mesh', 'globe')])
        self.assertIs(replacement.handles['globe'], handles['mesh'])
        self.assertIs(replacement.handles['skin'], handles['skin'])
        self.assertEqual(replacement.observations, {'globe': observations['mesh'], 'skin': observations['skin']})
        self.assertEqual(replacement.selection.order, ('globe', 'skin'))
        self.assertIs(replacement.objects.resolve('globe'), handles['mesh'])
        faulted(self, 'UNKNOWN_REFERENCE', replacement.objects.resolve, 'mesh')
        self.assertTrue(self.active.closed)
        self.assertEqual(self.active.handles, {})
        self.active.close()  # The retired closure no longer owns or deletes anything.
        self.assertEqual(self.backend.count('delete'), 0)
        state = replacement.apply({'time': 0.0, 'timeIndex': 0, 'indices': {}, 'sweeps': {}})
        self.assertEqual(state['updated'], [])  # Same evaluated values, no reconfigure or reread.

    def test_refuses_altered_plans_forged_steps_and_collisions_before_native_calls(self):
        calls, handles = list(self.backend.calls), dict(self.active.handles)
        faulted(self, 'IDENTITY_TRANSITION_MISMATCH', self.active.reidentify, [['mesh', 'globe']], self.altering, self.relabel)
        faulted(self, 'IDENTITY_TRANSITION_MISMATCH', self.active.reidentify, [['absent', 'globe']], self.planner, self.relabel)
        faulted(self, 'IDENTITY_COLLISION', self.active.reidentify, [['mesh', 'skin']], self.planner, self.relabel)
        faulted(self, 'INVALID_IDENTITY_TRANSITION', self.active.reidentify, [['mesh', 'mesh']], self.planner, self.relabel)
        faulted(self, 'UNSUPPORTED_IDENTITY_TRANSITION', self.active.reidentify, [['mesh', 'globe']], self.planner)
        self.assertEqual((self.backend.calls, self.active.handles, self.active.closed), (calls, handles, False))

    def test_worker_validates_its_current_plan_and_result(self):
        process = Process('paraview', None, None, None)
        lowered = {**DefinitionGraph(self.document, CATALOGUE).document, 'version': 'schemaxis/1'}
        process.request('data-load', document=lowered, roots=['skin'], state={'timeIndex': 0, 'indices': {}})
        faulted(self, 'STALE_IDENTITY_TRANSITION', process.request, 'data-reidentify', expected='0' * 64,
                steps=[['mesh', 'globe']], result='0' * 64)
        faulted(self, 'IDENTITY_TRANSITION_MISMATCH', process.request, 'data-reidentify', expected=digest(lowered),
                steps=[['mesh', 'globe']], result='0' * 64)
        faulted(self, 'INVALID_ARGUMENT', process.request, 'data-reidentify', expected=digest(lowered),
                steps=[], result='0' * 64)
        self.assertEqual(process.backend.count('relabel'), 0)
        process.close()


class UnaffectedResidency(Fixture):
    """Exact per-node residency across witnessed views (reviewer P1a and P1b)."""

    def spare(self):
        old = document({'id': 'spare', 'filter': 'readPLY', 'options': {'files': ['b.ply']}})
        self.live.load(self.request(old, nodes=['skin', 'spare']))
        handles = dict(self.worker().active.handles)
        _, accepted = self.rename(old)
        self.live.refresh(self.request(accepted['input'], accepted['to'], nodes=['skin', 'spare']))
        contested = copy.deepcopy(old)
        contested['nodes'].append({'id': 'globe', 'filter': 'readPLY', 'options': {'files': ['b.ply']}})
        return old, accepted, contested, handles

    def test_unaffected_source_stays_resident_beside_a_reused_witnessed_name(self):
        old, accepted, contested, handles = self.spare()
        self.assertEqual(self.loaded(contested), {'mesh': (False, True), 'skin': (False, True),
                                                  'spare': (True, True), 'globe': (False, False)})
        calls = len(self.backend.calls)
        self.assertEqual(self.live.inspect(self.request(contested), 'spare')['handle'], handles['spare']['id'])
        refreshed = self.live.refresh(self.request(contested, nodes=['spare']))
        self.assertTrue(any(e['node'] == 'spare' for e in refreshed['observations']['extents']))
        # Unaffected service reloads the worker's own plan in place: no create, update or delete.
        self.assertEqual(self.backend.calls[calls:], [('relabel', 'globe', 'mesh')])  # Alignment only.
        calls = len(self.backend.calls)
        # Contested values resolve only from content-shared observations; no native contact.
        self.assertEqual(self.states(contested), ['resolved', 'resolved'])
        self.assertEqual((len(self.backend.calls), self.loaded(contested)['mesh']), (calls, (False, True)))
        before = self.snapshot()
        fault = faulted(self, 'IDENTITY_VIEW_REQUIRED', self.live.load, self.request(contested, nodes=['mesh']))
        self.assertEqual(fault.observed['nodes'], ['mesh'])
        faulted(self, 'IDENTITY_VIEW_REQUIRED', self.live.inspect, self.request(contested), 'skin')
        self.assertEqual(self.snapshot(), before)
        # The other views keep the same objects; nothing was retired or reread.
        for _ in range(2):
            self.assertEqual(self.states(accepted['input'], accepted['to']), ['resolved', 'resolved'])
            self.assertEqual(self.states(old), ['resolved', 'resolved'])
        active = self.worker().active
        self.assertEqual({k: id(v) for k, v in active.handles.items()}, {k: id(v) for k, v in handles.items()})
        self.assertEqual((self.created, self.backend.count('create'), self.backend.count('delete')), (1, 3, 0))
        self.assertEqual(self.backend.reads, {handles['mesh']['id']: 1, handles['spare']['id']: 1})

    def test_changed_derived_setting_in_one_view_keeps_the_original_reader_resident(self):
        self.live.load(self.request(self.old, nodes=['skin']))
        mesh = self.worker().active.handles['mesh']
        _, accepted = self.rename(self.old)
        self.live.refresh(self.request(accepted['input'], accepted['to']))
        changed = copy.deepcopy(accepted['input'])
        changed['nodes'][1]['options']['factor'] = 0.25
        self.assertEqual(self.states(changed, accepted['to']), ['resolved', 'resolved'])
        # The changed consumer inherits nothing; the unchanged reader keeps exact provenance.
        self.assertEqual(self.loaded(self.old), {'mesh': (True, True), 'skin': (False, True)})
        self.assertEqual(self.live.inspect(self.request(self.old), 'mesh')['handle'], mesh['id'])
        for _ in range(2):
            self.assertEqual(self.states(self.old), ['resolved', 'resolved'])
            self.assertEqual(self.states(changed, accepted['to']), ['resolved', 'resolved'])
        self.assertIs(self.worker().active.handles['globe'], mesh)
        self.assertEqual((self.created, self.backend.reads), (1, {mesh['id']: 1}))
        # A changed source still invalidates and an unrelated reused name still acquires nothing.
        source = copy.deepcopy(self.old)
        source['nodes'][0]['options']['files'] = ['b.ply']
        self.assertEqual(self.loaded(source)['mesh'], (False, False))
        self.assertEqual(self.states(source), ['unresolved', 'unresolved'])
        reused = copy.deepcopy(changed)
        reused['nodes'].append({'id': 'mesh', 'filter': 'readPLY', 'options': {'files': ['a.ply']}})
        self.assertEqual(self.loaded(reused)['mesh'][0], False)
        self.assertEqual(self.created, 1)

    def test_unchanged_source_beside_a_changed_peer_serves_both_views(self):
        old = document({'id': 'spare', 'filter': 'readPLY', 'options': {'files': ['b.ply']}})
        self.live.load(self.request(old, nodes=['skin', 'spare']))
        _, accepted = self.rename(old)
        self.live.unload()
        changed = copy.deepcopy(accepted['input'])
        changed['nodes'][2]['options']['files'] = ['a.ply']
        self.live.load(self.request(changed, accepted['to'], nodes=['globe', 'spare']))
        process = Process.instances[-1]
        handles = dict(process.worker.active.handles)
        reads = dict(process.backend.reads)
        self.assertEqual(reads, {handles['globe']['id']: 1, handles['spare']['id']: 1})
        for _ in range(2):
            # The original view owns the unchanged reader, never the changed peer.
            self.assertEqual(self.loaded(old)['mesh'], (True, True))
            self.assertEqual(self.loaded(old)['spare'][0], False)
            calls = len(process.backend.calls)
            self.assertEqual(self.live.inspect(self.request(old), 'mesh')['handle'], handles['globe']['id'])
            self.live.refresh(self.request(old, nodes=['mesh']))
            self.assertEqual([c for c in process.backend.calls[calls:] if c[0] != 'relabel'], [])
            # The changed view keeps both of its readers.
            self.assertEqual(self.loaded(changed, accepted['to']), {'globe': (True, True), 'skin': (False, True),
                                                                  'spare': (True, True)})
            for node in ('globe', 'spare'):
                self.assertEqual(self.live.inspect(self.request(changed, accepted['to']), node)['handle'],
                                 handles[node]['id'])
            self.live.refresh(self.request(changed, accepted['to'], nodes=['globe', 'spare']))
            active = process.worker.active
            self.assertIs(active.handles['spare'], handles['spare'])
            self.assertIs(active.handles.get('globe', active.handles.get('mesh')), handles['globe'])
        self.assertEqual((self.created, dict(process.backend.reads)), (2, reads))
        self.assertEqual(process.backend.count('delete'), 0)
        # Refresh may build the original view's derived node; the changed peer stays untouched.
        self.assertEqual(self.states(old), ['resolved', 'resolved'])
        self.assertIs(process.worker.active.handles['spare'], handles['spare'])
        self.assertEqual((self.created, dict(process.backend.reads), process.backend.count('delete')), (2, reads, 0))
        self.assertEqual(self.states(changed, accepted['to']), ['resolved', 'resolved'])
        self.assertEqual(dict(process.backend.reads), reads)
        # The original spare (b.ply) is a different recipe: its explicit load is a separate pipeline.
        self.live.load(self.request(old, nodes=['spare']))
        self.assertEqual(self.created, 3)
        self.assertIs(process.worker.active.handles['spare'], handles['spare'])
        self.assertEqual(dict(process.backend.reads), reads)

    def test_raw_native_label_exception_poisons_without_a_new_process(self):
        self.live.load(self.request(self.old, nodes=['skin']))
        mesh = self.worker().active.handles['mesh']
        _, accepted = self.rename(self.old)
        self.backend.raw_pairs = {('mesh', 'globe')}
        faulted(self, 'IDENTITY_TRANSITION_UNCERTAIN', self.live.refresh, self.request(accepted['input'], accepted['to']))
        worker = self.worker()
        self.assertTrue(worker.uncertain)
        self.assertEqual(self.live.status()['sessions'][0]['uncertain'], True)
        self.assertIs(worker.active.handles['mesh'], mesh)  # Preserved, not deleted or rebuilt.
        self.assertEqual(self.backend.count('delete'), 0)
        calls = len(self.backend.calls)
        self.assertEqual(self.states(self.old), ['resolved', 'resolved'])  # Cached observations only.
        faulted(self, 'IDENTITY_TRANSITION_UNAVAILABLE', self.live.load, self.request(self.old, nodes=['mesh']))
        faulted(self, 'UNCERTAIN_STATE', Process.instances[0].request, 'data-load', document=self.old,
                roots=['mesh'], state={'timeIndex': 0, 'indices': {}})
        self.assertEqual((len(self.backend.calls), self.created), (calls, 1))


class NativeManager:
    """A stand-in ParaView proxy manager with injectable RenameSource faults."""

    def __init__(self, proxies):
        self.names = dict((name, proxy.SMProxy) for name, proxy in proxies.items())
        self.faults, self.reads_fail = {}, False

    def GetProxyName(self, group, smproxy):
        if self.reads_fail:
            raise RuntimeError('injected readback failure')
        return next((name for name, value in self.names.items() if value is smproxy), None)

    def GetProxy(self, group, name):
        return self.names.get(name)

    def UnRegisterProxy(self, group, name, proxy):
        self.names.pop(name)

    def rename(self, new, proxy):
        old = next(name for name, value in self.names.items() if value is proxy.SMProxy)
        mode = self.faults.get((old, new))
        if mode == 'raise-before':
            raise RuntimeError('injected before any change')
        self.names[new] = proxy.SMProxy
        if mode == 'register-only':
            raise RuntimeError('injected with both names registered')
        del self.names[old]
        if mode == 'raise-after':
            raise RuntimeError('injected after the change')
        if mode == 'readback':
            self.reads_fail = True


class NativeRelabel(unittest.TestCase):
    """The declared ParaView hook and shared primitive with a stand-in proxy manager.

    This is host evidence of reconciliation logic; it is not physical native failure coverage.
    """

    def setUp(self):
        primitive = Primitive('test_rebinds_the_same_objects_without_native_execution')
        primitive.setUp()
        self.active = primitive.active
        self.proxies = {name: SimpleNamespace(SMProxy=object()) for name in self.active.handles}
        self.manager = NativeManager(self.proxies)
        self.backend = object.__new__(ParaViewBackend)
        self.backend.records = {id(p): {'node': n, 'declaration': {'role': 'filter'}} for n, p in self.proxies.items()}
        self.backend.sm = SimpleNamespace(ProxyManager=self.manager_of)
        self.backend.pv = SimpleNamespace(RenameSource=self.manager.rename)
        self.by_handle = {id(self.active.handles[n]): p for n, p in self.proxies.items()}
        self.handles = dict(self.active.handles)

    def manager_of(self):
        return self.manager

    def relabel(self, handle, old, new):
        self.backend.relabel(self.by_handle[id(handle)], old, new)

    def reidentify(self, steps):
        return self.active.reidentify(steps, Primitive.planner, self.relabel)

    def labels(self):
        return sorted(self.manager.names), sorted(r['node'] for r in self.backend.records.values())

    def test_partial_native_changes_are_restored_and_verified(self):
        for mode in ('raise-after', 'register-only', 'raise-before'):
            self.manager.faults = {('mesh', 'globe'): mode}
            fault = faulted(self, 'NATIVE_RELABEL_FAILED', self.reidentify, [['mesh', 'globe']])
            self.assertTrue(fault.observed['restored'], mode)
            self.assertEqual(self.labels(), (['mesh', 'skin'], ['mesh', 'skin']), mode)
            self.assertFalse(self.active.failed, mode)
        self.manager.faults = {}
        replacement = self.reidentify([['mesh', 'globe']])
        self.assertIs(replacement.handles['globe'], self.handles['mesh'])
        self.assertEqual(self.labels(), (['globe', 'skin'], ['globe', 'skin']))

    def test_completed_steps_are_reversed_and_unprovable_states_poison(self):
        self.manager.faults = {('skin', 'hull'): 'raise-after'}
        faulted(self, 'NATIVE_RELABEL_FAILED', self.reidentify, [['mesh', 'globe'], ['skin', 'hull']])
        self.assertEqual(self.labels(), (['mesh', 'skin'], ['mesh', 'skin']))
        self.assertFalse(self.active.failed)
        # The failing step is restored, but reversing the completed one fails: uncertain.
        self.manager.faults = {('skin', 'hull'): 'raise-after', ('globe', 'mesh'): 'raise-before'}
        faulted(self, 'IDENTITY_TRANSITION_UNCERTAIN', self.reidentify, [['mesh', 'globe'], ['skin', 'hull']])
        self.assertTrue(self.active.failed)
        self.assertEqual(dict(self.active.handles), self.handles)  # Preserved for explicit release.
        faulted(self, 'CLOSED_PIPELINE', self.reidentify, [['mesh', 'globe']])

    def test_unreadable_registrations_after_a_change_are_uncertain(self):
        self.manager.faults = {('mesh', 'globe'): 'readback'}
        fault = faulted(self, 'IDENTITY_TRANSITION_UNCERTAIN', self.reidentify, [['mesh', 'globe']])
        self.assertIn('could not be restored', fault.message)
        self.assertTrue(self.active.failed)
        self.assertEqual(dict(self.active.handles), self.handles)

    def test_refusals_before_rename_change_nothing(self):
        self.manager.names['globe'] = object()  # Registered natively outside the plan.
        faulted(self, 'NATIVE_IDENTITY_COLLISION', self.reidentify, [['mesh', 'globe']])
        self.manager.names.pop('globe')
        self.manager.reads_fail = True
        fault = faulted(self, 'NATIVE_RELABEL_FAILED', self.reidentify, [['mesh', 'globe']])
        self.assertNotIn('uncertain', fault.observed)
        self.manager.reads_fail = False
        self.assertEqual(self.labels(), (['mesh', 'skin'], ['mesh', 'skin']))
        self.assertFalse(self.active.failed)


if __name__ == '__main__':
    unittest.main()
