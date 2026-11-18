# Copyright (C) 2026 David L. F. Gaden.
"""Bounded serial qualification of witnessed identity views on resident ParaView data.

A test-only worker module, packaged into this test's runtime archive, counts each
native algorithm's StartEvent by proxy global ID and reports it through the
existing status command. It also makes RenameSource fail after changing the real
registration for two test names. It adds no product command or endpoint.
"""
import copy
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from schemaxis.adaptors.paraview.mvp.runners import find_paraview
from schemaxis.artifacts import runtime_archive
from schemaxis.core.faults import SchemaxisError
from schemaxis.live_data import DataProcess, LiveDataSession
from schemaxis.storage import digest

HARNESS = '''
from paraview import servermanager, simple
from schemaxis.adaptors.paraview import native
from schemaxis.live_data_worker import Worker
from schemaxis.live_transport import serve

EXECUTIONS = {}
CREATE = native.ParaViewBackend.create


class Counter:
    def __init__(self, identity):
        self.identity = identity

    def __call__(self, algorithm, event):
        EXECUTIONS[self.identity] += 1


def counted(backend, node, declaration, inputs, constructor):
    proxy = CREATE(backend, node, declaration, inputs, constructor)
    identity = proxy.SMProxy.GetGlobalIDAsString()
    EXECUTIONS.setdefault(identity, 0)
    proxy.GetClientSideObject().AddObserver('StartEvent', Counter(identity))
    return proxy


native.ParaViewBackend.create = counted
RENAME = simple.RenameSource


def injected_rename(name, proxy=None):
    """'faulty' and 'doomed' fail after the real rename; restoring 'doomed' also fails."""
    if servermanager.ProxyManager().GetProxyName('sources', proxy.SMProxy) == 'doomed':
        raise RuntimeError('injected restore failure')
    RENAME(name, proxy)
    if name in ('faulty', 'doomed'):
        raise RuntimeError('injected after RenameSource changed the registration')


simple.RenameSource = injected_rename


class CountingWorker(Worker):
    def status(self):
        result = super().status()
        manager = servermanager.ProxyManager()
        proxies = {}
        for node, proxy in (self.active.handles.items() if self.active else []):
            identity = proxy.SMProxy.GetGlobalIDAsString()
            proxies[node] = {'globalId': identity, 'registration': manager.GetProxyName('sources', proxy.SMProxy),
                             'algorithm': proxy.GetClientSideObject().GetClassName(),
                             'executions': EXECUTIONS.get(identity)}
        return {**result, 'harness': {'proxies': proxies,
                                      'registered': sorted({name for name, _ in manager.GetProxiesInGroup('sources')})}}


def start(directory, parent_pid=None, parent_start=None, provider=None):
    simple.Sphere(registrationName='occupied')
    serve(directory, CountingWorker(provider), parent_pid, parent_start)
'''
TETRA = ('ply\nformat ascii 1.0\nelement vertex 4\nproperty float x\nproperty float y\nproperty float z\n'
         'element face 4\nproperty list uchar int vertex_indices\nend_header\n'
         '{0} 0 0\n{1} 0 0\n{0} 2 0\n{0} 0 3\n3 0 2 1\n3 0 1 3\n3 1 2 3\n3 2 0 3\n')


def archive():
    buffer = io.BytesIO(runtime_archive())
    with zipfile.ZipFile(buffer, 'a') as bundle:
        bundle.writestr('schemaxis_live_identity_harness.py', HARNESS)
    return buffer.getvalue()


class CountingProcess(DataProcess):
    worker_module = 'schemaxis_live_identity_harness'
    started = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        CountingProcess.started.append(self)


def native_state(live):
    result = {}
    for worker in live.workers.values():
        status = worker['client'].request('status')
        result[status['pid']] = {'nodes': status['nodes'], 'transitions': status['transitions'],
                                 'uncertain': status['uncertain'], **status['harness']}
    return result


def exercise(directory):
    """Run the qualification; return inspectable evidence (no assertions)."""
    directory = Path(directory)
    first, second = directory / 'first.ply', directory / 'second.ply'
    first.write_text(TETRA.format(0, 1))
    second.write_text(TETRA.format(10, 11))
    old = {'version': 'schemaxis/1',
           'definitions': {'whole': {'$expr': 'extents(mesh)'}, 'part': {'$expr': 'extents(skin)'}},
           'nodes': [{'id': 'mesh', 'filter': 'readPLY', 'options': {'files': [str(first)]}},
                     {'id': 'skin', 'filter': 'shrink', 'inputs': {'input': 'mesh'}, 'options': {'factor': 0.5}}]}
    evidence, CountingProcess.started = {'steps': []}, []

    def request(input, view=None, **extra):
        return {'input': input, 'sessionDocument': 'doc', **({'view': view} if view else {}), **extra}

    def accept(input, pointer, name, view=None):
        preview = live.prepare_identity_transition(request(input, view), pointer, name, digest(input))
        expected = {k: preview['transition'][k] for k in ('inputDigest', 'outputDigest', 'policyDigest')}
        return live.accept_identity_transition(request(input, view), pointer, name, expected)

    def record(label, input, view=None, node=None, refresh=True):
        entry = {'label': label}
        if refresh:
            records = live.refresh(request(input, view))['records']
            entry['records'] = [{'state': r['state'], 'value': r.get('value')} for r in records]
        if node:
            inspected = live.inspect(request(input, view), node)
            entry['inspect'] = {k: inspected['observation'][k] for k in ('bounds', 'points', 'cells', 'dataType')}
        entry['selection'] = {n['id']: n['loaded'] for n in live.selection(request(input, view))['nodes']}
        entry['native'] = native_state(live)
        entry['factories'] = len(CountingProcess.started)
        evidence['steps'].append(entry)

    def failure(transition):
        try:
            live.refresh(request(transition['input'], transition['to']))
            return None
        except SchemaxisError as error:
            return {'code': error.fault.code, 'restored': error.fault.observed.get('restored'),
                    'uncertain': error.fault.observed.get('uncertain'), 'native': native_state(live),
                    'factories': len(CountingProcess.started)}

    with patch('schemaxis.live_transport.runtime_archive', archive), \
            LiveDataSession(directory / 'live', CountingProcess) as live:
        live.load(request(old, nodes=['skin']))
        record('loaded original', old, node='mesh')
        renamed = accept(old, '/nodes/0/id', 'globe')
        evidence['source'] = {k: renamed[k] for k in ('retainedObservations', 'adoptedWorkers')}
        record('accepted source rename, bare original view', old, node='mesh')
        record('witnessed source rename view', renamed['input'], renamed['to'], node='globe')
        derived = accept(renamed['input'], '/nodes/1/id', 'hull', renamed['to'])
        record('witnessed derived rename view', derived['input'], derived['to'], node='hull')
        record('undo to bare original view', old, node='skin')
        record('redo to derived rename view', derived['input'], derived['to'], node='globe')
        clash = accept(derived['input'], '/nodes/0/id', 'occupied', derived['to'])
        try:
            live.refresh(request(clash['input'], clash['to']))
            evidence['collision'] = None
        except SchemaxisError as error:
            evidence['collision'] = error.fault.code
        record('after refused native collision', derived['input'], derived['to'])
        evidence['restored'] = failure(accept(derived['input'], '/nodes/0/id', 'faulty', derived['to']))
        record('after restored partial native relabel', derived['input'], derived['to'], node='globe')
        settings = copy.deepcopy(derived['input'])
        settings['nodes'][1]['options']['factor'] = 0.25
        record('derived settings change in witnessed view', settings, derived['to'], node='hull')
        record('original view after derived settings change', old, node='mesh')
        evidence['uncertain'] = failure(accept(derived['input'], '/nodes/0/id', 'doomed', derived['to']))
        record('original view with uncertain worker', old)
        try:
            live.load(request(old, nodes=['mesh']))
            evidence['uncertainLoad'] = None
        except SchemaxisError as error:
            evidence['uncertainLoad'] = error.fault.code
        changed = copy.deepcopy(derived['input'])
        changed['nodes'][0]['options']['files'] = [str(second)]
        record('changed source recipe refresh', changed, derived['to'])
        live.unload()  # One native process at a time.
        live.load(request(changed, derived['to'], nodes=['hull']))
        record('changed source recipe explicit load', changed, derived['to'], node='globe', refresh=False)
        processes = [process.process for process in CountingProcess.started]
    evidence['exited'] = [process.poll() is not None for process in processes]
    return evidence


def exercise_peer(directory):
    """An unchanged reader beside a changed peer reader; return inspectable evidence."""
    directory = Path(directory)
    first, second = directory / 'first.ply', directory / 'second.ply'
    first.write_text(TETRA.format(0, 1))
    second.write_text(TETRA.format(10, 11))
    old = {'version': 'schemaxis/1',
           'definitions': {'whole': {'$expr': 'extents(mesh)'}, 'other': {'$expr': 'extents(spare)'}},
           'nodes': [{'id': 'mesh', 'filter': 'readPLY', 'options': {'files': [str(first)]}},
                     {'id': 'spare', 'filter': 'readPLY', 'options': {'files': [str(second)]}}]}
    evidence, CountingProcess.started = {'steps': []}, []

    def request(input, view=None, **extra):
        return {'input': input, 'sessionDocument': 'doc', **({'view': view} if view else {}), **extra}

    def record(label, input, view=None, inspect=(), refresh=None):
        entry = {'label': label, 'inspect': {}}
        if refresh is not None:
            records = live.refresh(request(input, view, nodes=refresh))['records']
            entry['records'] = [{'state': r['state'], 'value': r.get('value')} for r in records]
        for node in inspect:
            inspected = live.inspect(request(input, view), node)['observation']
            entry['inspect'][node] = {k: inspected[k] for k in ('bounds', 'points', 'cells')}
        entry['selection'] = {n['id']: n['loaded'] for n in live.selection(request(input, view))['nodes']}
        entry['native'] = native_state(live)
        entry['factories'] = len(CountingProcess.started)
        evidence['steps'].append(entry)

    with patch('schemaxis.live_transport.runtime_archive', archive), \
            LiveDataSession(directory / 'live', CountingProcess) as live:
        live.load(request(old, nodes=['mesh', 'spare']))
        record('original two readers', old, inspect=('mesh', 'spare'))
        preview = live.prepare_identity_transition(request(old), '/nodes/0/id', 'globe', digest(old))
        accepted = live.accept_identity_transition(request(old), '/nodes/0/id', 'globe', {
            k: preview['transition'][k] for k in ('inputDigest', 'outputDigest', 'policyDigest')})
        live.unload()  # One native process at a time.
        changed = copy.deepcopy(accepted['input'])
        changed['nodes'][1]['options']['files'] = [str(first)]
        live.load(request(changed, accepted['to'], nodes=['globe', 'spare']))
        record('changed peer explicit load in witnessed view', changed, accepted['to'], inspect=('globe', 'spare'))
        for round in (1, 2):
            record(f'original view {round}', old, inspect=('mesh',), refresh=['mesh'])
            record(f'changed witnessed view {round}', changed, accepted['to'], inspect=('globe', 'spare'),
                   refresh=['globe', 'spare'])
        processes = [process.process for process in CountingProcess.started]
    evidence['exited'] = [process.poll() is not None for process in processes]
    return evidence


@unittest.skipUnless(find_paraview(), 'set SCHEMAXIS_PARAVIEW_ROOTS to a ParaView installation')
class ResidentIdentityViews(unittest.TestCase):
    def test_reader_handles_survive_source_derived_inverse_and_redo_views(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence = exercise(temporary)
        steps = {step['label']: step for step in evidence['steps']}
        loaded = steps['loaded original']
        (pid,) = loaded['native']
        proxies = loaded['native'][pid]['proxies']
        reader, shrink = proxies['mesh']['globalId'], proxies['skin']['globalId']
        self.assertEqual(proxies['mesh']['algorithm'], 'vtkFileSeriesReader')
        self.assertEqual((proxies['mesh']['executions'], proxies['skin']['executions']), (1, 1))
        self.assertEqual(loaded['inspect'], {'bounds': [0.0, 1.0, 0.0, 2.0, 0.0, 3.0], 'points': 4, 'cells': 4,
                                             'dataType': 'vtkPolyData'})
        self.assertEqual(evidence['source'], {'retainedObservations': 2, 'adoptedWorkers': 1})
        names = {'accepted source rename, bare original view': ('mesh', 'skin'),
                 'witnessed source rename view': ('globe', 'skin'),
                 'witnessed derived rename view': ('globe', 'hull'),
                 'undo to bare original view': ('mesh', 'skin'),
                 'redo to derived rename view': ('globe', 'hull'),
                 'after refused native collision': ('globe', 'hull')}
        for label, (source, consumer) in names.items():
            step = steps[label]
            self.assertEqual(list(step['native']), [pid], label)
            native = step['native'][pid]
            self.assertEqual(native['proxies'][source], {**proxies['mesh'], 'registration': source}, label)
            self.assertEqual(native['proxies'][consumer]['globalId'], shrink, label)
            self.assertEqual(native['proxies'][consumer]['registration'], consumer, label)
            self.assertEqual(native['proxies'][consumer]['executions'], 1, label)
            self.assertEqual(step['factories'], 1, label)
            self.assertTrue(all(record['state'] == 'resolved' for record in step['records']), label)
            self.assertTrue(all(step['selection'].values()), label)
            self.assertNotIn('mesh' if source != 'mesh' else 'globe', native['registered'], label)
        self.assertEqual(steps['witnessed source rename view']['inspect'], loaded['inspect'])
        self.assertEqual(steps['witnessed derived rename view']['inspect']['cells'], 4)
        self.assertEqual(evidence['collision'], 'NATIVE_IDENTITY_COLLISION')
        restored = evidence['restored']
        self.assertEqual((restored['code'], restored['restored'], restored['uncertain']), ('NATIVE_RELABEL_FAILED', True, None))
        self.assertEqual(restored['native'][pid]['proxies']['globe'], {**proxies['mesh'], 'registration': 'globe'})
        self.assertNotIn('faulty', restored['native'][pid]['registered'])
        after = steps['after restored partial native relabel']
        self.assertEqual(after['native'][pid]['proxies']['globe']['executions'], 1)
        self.assertEqual((after['factories'], after['inspect']['cells']), (1, 4))
        # A changed derived setting is rebuilt by ordinary refresh semantics; the reader is never reread.
        step = steps['derived settings change in witnessed view']
        settings = step['native'][pid]['proxies']
        self.assertEqual((settings['globe']['globalId'], settings['globe']['executions']), (reader, 1))
        self.assertNotEqual(settings['hull']['globalId'], shrink)
        self.assertEqual(settings['hull']['executions'], 1)
        self.assertEqual(step['records'][1]['value'], {'min': [0.0, 0.0, 0.0], 'max': [0.5, 1.0, 1.5]})
        # The original view keeps its unchanged reader after the other view changed a consumer.
        original = steps['original view after derived settings change']
        self.assertEqual(original['native'][pid]['proxies']['mesh'], {**proxies['mesh'], 'registration': 'mesh'})
        self.assertEqual((original['factories'], original['selection']['mesh']), (1, True))
        self.assertEqual(original['inspect'], loaded['inspect'])
        uncertain = evidence['uncertain']
        self.assertEqual((uncertain['code'], uncertain['factories']), ('IDENTITY_TRANSITION_UNCERTAIN', 1))
        self.assertTrue(uncertain['native'][pid]['uncertain'])
        # Logical and native labels disagree; the proxy is kept and visible, never reset or reread.
        self.assertEqual(uncertain['native'][pid]['proxies']['mesh'], {**proxies['mesh'], 'registration': 'doomed'})
        held = steps['original view with uncertain worker']
        self.assertEqual((held['factories'], held['selection']['mesh']), (1, False))
        self.assertEqual(evidence['uncertainLoad'], 'IDENTITY_TRANSITION_UNAVAILABLE')
        refresh = steps['changed source recipe refresh']
        self.assertEqual(refresh['factories'], 1)  # Refresh never enables or reads the changed source.
        self.assertEqual([r['state'] for r in refresh['records']], ['unresolved', 'unresolved'])
        explicit = steps['changed source recipe explicit load']
        self.assertEqual(explicit['factories'], 2)
        (other,) = explicit['native']
        self.assertNotEqual(other, pid)
        self.assertEqual(explicit['native'][other]['proxies']['globe']['executions'], 1)
        self.assertEqual(explicit['inspect']['bounds'][:2], [10.0, 11.0])
        self.assertEqual(evidence['exited'], [True, True])


    def test_unchanged_reader_beside_a_changed_peer_keeps_both_proxies(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence = exercise_peer(temporary)
        steps = {step['label']: step for step in evidence['steps']}
        loaded = steps['changed peer explicit load in witnessed view']
        (pid,) = loaded['native']
        proxies = loaded['native'][pid]['proxies']
        reader, peer = proxies['globe'], proxies['spare']
        self.assertNotEqual(reader['globalId'], peer['globalId'])  # Same file, two ordinary proxies.
        self.assertEqual((reader['executions'], peer['executions'], loaded['factories']), (1, 1, 2))
        self.assertEqual(loaded['inspect']['globe']['bounds'], [0.0, 1.0, 0.0, 2.0, 0.0, 3.0])
        self.assertEqual(loaded['inspect']['spare']['bounds'], [0.0, 1.0, 0.0, 2.0, 0.0, 3.0])
        original = steps['original two readers']
        self.assertEqual(original['inspect']['spare']['bounds'][:2], [10.0, 11.0])
        for round in (1, 2):
            old, new = steps[f'original view {round}'], steps[f'changed witnessed view {round}']
            for step, label in ((old, 'mesh'), (new, 'globe')):
                native = step['native'][pid]['proxies']
                self.assertEqual(native[label], {**reader, 'registration': label}, step['label'])
                self.assertEqual(native['spare'], peer, step['label'])
                self.assertEqual(step['factories'], 2, step['label'])
            self.assertEqual(old['inspect']['mesh'], loaded['inspect']['globe'])
            self.assertEqual((old['selection']['mesh'], old['selection']['spare']), (True, False))
            self.assertEqual(new['selection'], {'globe': True, 'spare': True})
            self.assertEqual(new['inspect'], loaded['inspect'])
            self.assertTrue(all(r['state'] == 'resolved' for r in old['records'] + new['records']))
        self.assertEqual(evidence['exited'], [True, True])

if __name__ == '__main__':
    unittest.main()
