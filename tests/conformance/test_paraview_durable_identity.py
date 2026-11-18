# Copyright (C) 2026 David L. F. Gaden.
"""Serial file-reader and composite geometry proof for durable checked identity history."""
import copy
import io
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from schemaxis.artifacts import runtime_archive
from schemaxis.console_session import AdaptorConsoleSession
from schemaxis.adaptors.paraview.live import LiveSession
from schemaxis.adaptors.paraview.mvp.runners import find_paraview
from schemaxis.core.faults import SchemaxisError
from test_paraview_live_identity import HARNESS as DATA_HARNESS, TETRA, CountingProcess

HARNESS = DATA_HARNESS.replace('from schemaxis.live_data_worker import Worker',
    'from schemaxis.adaptors.paraview.live_native import Worker').replace(
    'CountingWorker(provider)', 'CountingWorker()')
HARNESS = HARNESS.replace('class CountingWorker(Worker):', '''class CountingWorker(Worker):
    def geometry(self):
        if self.active and 'geometryFault' in self.active.handles and not getattr(self, '_geometry_faulted', False):
            self._geometry_faulted = True
            raise RuntimeError('injected native geometry readback failure')
        return super().geometry()
''')


def archive():
    buffer = io.BytesIO(runtime_archive())
    with zipfile.ZipFile(buffer, 'a') as bundle:
        bundle.writestr('schemaxis_durable_identity_harness.py', HARNESS)
        bundle.writestr('schemaxis_live_identity_harness.py', DATA_HARNESS)
    return buffer.getvalue()


class CountingGraph(LiveSession):
    worker_module = 'schemaxis_durable_identity_harness'


def multiblock(directory):
    """Four explicit tetrahedral surfaces at x=0,4,8,12; no native fixture generator."""
    blocks = []
    for index, name in enumerate(('internal', 'wall_left', 'wall_right', 'outlet')):
        x = index * 4
        text = f'''<?xml version="1.0"?>
<VTKFile type="PolyData" version="0.1" byte_order="LittleEndian"><PolyData>
<Piece NumberOfPoints="4" NumberOfVerts="0" NumberOfLines="0" NumberOfStrips="0" NumberOfPolys="4">
<Points><DataArray type="Float32" NumberOfComponents="3" format="ascii">{x} 0 0 {x+1} 0 0 {x} 2 0 {x} 0 3</DataArray></Points>
<Polys><DataArray type="Int32" Name="connectivity" format="ascii">0 2 1 0 1 3 1 2 3 2 0 3</DataArray>
<DataArray type="Int32" Name="offsets" format="ascii">3 6 9 12</DataArray></Polys>
</Piece></PolyData></VTKFile>'''
        (directory / (name + '.vtp')).write_text(text)
        blocks.append(f'<DataSet index="{index}" name="{name}" file="{name}.vtp"/>')
    path = directory / 'blocks.vtm'
    path.write_text('<?xml version="1.0"?><VTKFile type="vtkMultiBlockDataSet" version="1.0" '
                    'byte_order="LittleEndian"><vtkMultiBlockDataSet>' + ''.join(blocks) +
                    '</vtkMultiBlockDataSet></VTKFile>')
    return path


def exercise(directory, executable, composite=False):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = multiblock(directory) if composite else directory / 'first.ply'
    if not composite: path.write_text(TETRA.format(0, 1))
    nodes = [{'id': 'mesh', 'filter': 'readMultiBlock' if composite else 'readPLY',
              'options': {'files': [str(path)]}}]
    if not composite:
        nodes.append({'id': 'skin', 'filter': 'shrink', 'inputs': {'input': 'mesh'},
                      'options': {'factor': {'$expr': 'extents(mesh).deltaX * 0.5'}}})
    value = {'version': 'schemaxis/1', 'nodes': nodes,
             'scenes': [{'id': 'view', 'geometry': [n['id'] for n in nodes]}]}
    evidence = {'composite': composite, 'steps': []}
    with patch('schemaxis.live_transport.runtime_archive', archive), \
            AdaptorConsoleSession(directory / 'workspace', 'paraview') as session:
        session._edit(value, 'mesh')
        client = CountingGraph(executable, directory / 'native', timeout=120)
        session.live = client
        process = client.process
        session.preview()

        def record(label):
            geometry = session.geometry()
            evidence['steps'].append({'label': label, 'authored': session.document,
                'revision': session._record['revision'], 'geometry': geometry, 'native': client.request('status')})

        def rename(pointer, name):
            session.rename(pointer, name, session.active_document, session._record['revision'])

        record('initial')
        before = client.request('status')
        session.prepare_rename('/nodes/0/id', 'globe', session.active_document, session._record['revision'])
        evidence['cancelUnchanged'] = before == client.request('status')
        rename('/nodes/0/id', 'globe')
        record('source renamed')
        session.undo()
        record('source undo')
        session.redo()
        record('source redo')
        if not composite:
            rename('/nodes/1/id', 'surface')
            record('derived renamed')
            session.undo()
            record('derived undo')
            session.redo()
            record('derived redo')
        session.preview()
        record('explicit preview after rename')
        # Failure occurs after labels changed. Verified inverse keeps these exact
        # native objects and leaves the durable rename pending for an explicit retry.
        rename('/nodes/0/id', 'geometryFault')
        try:
            session.geometry()
            evidence['readbackFailure'] = None
        except SchemaxisError as error:
            evidence['readbackFailure'] = error.fault.to_dict()
        evidence['afterFailureNative'] = client.request('status')
        record('retry after verified readback reversal')
        evidence['checkpoints'] = session.checkpoints
    evidence['exited'] = process.poll() is not None
    return evidence


def assert_evidence(test, evidence):
    steps = evidence['steps']
    initial = steps[0]['native']
    first = initial['harness']['proxies']
    ids = {item['globalId'] for item in first.values()}
    for step in steps:
        native = step['native']
        test.assertEqual(initial['pid'], native['pid'])
        test.assertEqual(ids, {p['globalId'] for p in native['harness']['proxies'].values()})
        for item in native['harness']['proxies'].values():
            test.assertEqual(1, item['executions'])
        for obj in step['geometry']['objects']:
            test.assertEqual(obj['node'], obj['label'])
            test.assertEqual(obj['node'] + '/block/' + obj['block'] if evidence['composite'] else obj['node'], obj['id'])
        original = steps[0]['geometry']['objects']
        test.assertEqual([o['faces'] for o in original], [o['faces'] for o in step['geometry']['objects']])
        test.assertEqual([o['edges'] for o in original], [o['edges'] for o in step['geometry']['objects']])
    test.assertEqual(4 if evidence['composite'] else 2, len(steps[0]['geometry']['objects']))
    test.assertTrue(evidence['cancelUnchanged'])
    test.assertEqual('IDENTITY_TRANSITION_FAILED', evidence['readbackFailure']['code'])
    test.assertTrue(evidence['readbackFailure']['observed']['rolledBack'])
    test.assertTrue(evidence['exited'])


def exercise_both(directory, executable, *, pending_steps=0):
    """One tiny worker per residency domain, owned by the same durable Console session."""
    if not 0 <= pending_steps <= 16:
        raise ValueError('Use at most 16 extra witnessed views in this bounded fixture')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'first.ply'
    path.write_text(TETRA.format(0, 1))
    value = {'version': 'schemaxis/1', 'definitions': {'whole': {'$expr': 'extents(mesh)'}},
             'nodes': [{'id': 'mesh', 'filter': 'readPLY', 'options': {'files': [str(path)]}},
                       {'id': 'skin', 'filter': 'shrink', 'inputs': {'input': 'mesh'}, 'options': {'factor': 0.5}}],
             'scenes': [{'id': 'view', 'geometry': ['mesh', 'skin']}]}
    evidence, CountingProcess.started = {'steps': []}, []
    with patch('schemaxis.live_transport.runtime_archive', archive), \
            AdaptorConsoleSession(directory / 'workspace', 'paraview') as session:
        session.configure('paraview', str(executable))
        session._edit(value, 'mesh')
        graph = CountingGraph(executable, directory / 'graph', timeout=60)
        evidence['graphRequestBudget'] = graph.timeout
        evidence['identityRequests'] = []
        request = graph.request
        def timed_request(command, **args):
            started = time.monotonic()
            result = request(command, **args)
            if command in ('graph-prepare-identity', 'graph-reidentify'):
                evidence['identityRequests'].append({'command': command, 'steps': len(args['proofs']),
                    'seconds': time.monotonic() - started})
            return result
        graph.request = timed_request
        session.live = graph
        session.live_data.factory = CountingProcess
        session.preview()
        session.execute('data load skin')
        data = CountingProcess.started[0]
        processes = [graph.process, data.process]

        def record(label, node):
            records = session.execute('data refresh')['records']
            request = {'input': session.document, 'sessionDocument': session.active_document}
            view = session._runtime.get('identityViews', {}).get(None)
            if view: request['view'] = view
            original_inspection = session.live_data.inspect({'input': value,
                'sessionDocument': session.active_document}, 'mesh', locations={'paraview': [str(executable)]})
            inspection = session.live_data.inspect(request, node, locations={'paraview': [str(executable)]})
            evidence['steps'].append({'label': label, 'authored': session.document,
                'geometry': session.geometry(), 'graph': graph.request('status'), 'data': data.request('status'),
                'inspection': inspection, 'originalInspection': original_inspection,
                'liveDataEdges': len(session.live_data.edges), 'records': records})

        record('initial both domains', 'mesh')
        session.execute('rename /nodes/0/id globe')
        record('renamed both domains', 'globe')
        session.undo()
        record('undo both domains', 'mesh')
        session.redo()
        record('redo both domains', 'globe')
        session.preview()
        record('preview and refresh both domains', 'globe')
        if pending_steps:
            for index in range(pending_steps):
                session.execute('rename /nodes/0/id queued' + str(index))
            record('queued identity chain', 'queued' + str(pending_steps - 1))
            for _ in range(pending_steps): session.undo()
            record('undo queued identity chain', 'globe')
    evidence['exited'] = [process.poll() is not None for process in processes]
    return evidence


def assert_both(test, evidence):
    first = evidence['steps'][0]
    test.assertNotEqual(first['graph']['pid'], first['data']['pid'])
    for domain in ('graph', 'data'):
        initial = first[domain]
        ids = {p['globalId'] for p in initial['harness']['proxies'].values()}
        for step in evidence['steps']:
            native = step[domain]
            test.assertEqual(initial['pid'], native['pid'])
            test.assertEqual(ids, {p['globalId'] for p in native['harness']['proxies'].values()})
            test.assertTrue(all(p['executions'] == 1 for p in native['harness']['proxies'].values()))
            test.assertTrue(all(r['state'] == 'resolved' for r in step['records']))
            test.assertLessEqual(step['liveDataEdges'], 32)
            for key in ('points', 'cells', 'bounds'):
                test.assertEqual(step['inspection']['observation'][key], step['originalInspection']['observation'][key])
            test.assertEqual([step['data']['pid']], [s['pid'] for s in step['originalInspection']['liveData']['sessions']])
            test.assertEqual([o['faces'] for o in first['geometry']['objects']],
                             [o['faces'] for o in step['geometry']['objects']])
    test.assertTrue(all(evidence['exited']))


class NativeDurableIdentity(unittest.TestCase):
    def test_reader_filter_and_composite_geometry_serially(self):
        executable = find_paraview()
        if not executable: self.skipTest('ParaView is not configured')
        with tempfile.TemporaryDirectory() as temporary:
            for composite in (False, True):
                evidence = exercise(Path(temporary) / str(composite), executable[0].executable, composite)
                assert_evidence(self, evidence)
            assert_both(self, exercise_both(Path(temporary) / 'both', executable[0].executable))


if __name__ == '__main__': unittest.main()
