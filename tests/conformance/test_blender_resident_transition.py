# Copyright (C) 2026 David L. F. Gaden.
"""Serial Blender proof of ordinary resident graph edits and honest construction failure.

A test-only worker module, packaged into this test's runtime archive, wraps the
Blender backend's create/update/delete and the mesh importer. It gives every
created object a creation epoch (a re-added object may reuse a memory address),
counts importer calls and updates, and reports them with Blender's own object and
mesh membership through the existing status command. No product command is added.
"""
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from schemaxis.artifacts import runtime_archive
from schemaxis.adaptors.blender.live import LiveSession
from schemaxis.core.faults import SchemaxisError

HARNESS = '''
import bpy
from schemaxis.adaptors.blender import extended_native, native
from schemaxis.adaptors.blender.live_native import Worker
from schemaxis.live_transport import serve

CREATE, UPDATE, DELETE, IMPORT = native.Backend.create, native.Backend.update, native.Backend.delete, extended_native.import_mesh
EPOCHS, LIVE, IMPORTS = {}, {}, []


def counted_import(identity, kind, options, sources):
    IMPORTS.append(identity)
    return IMPORT(identity, kind, options, sources)


def counted_create(backend, node, declaration, inputs, constructor):
    obj = CREATE(backend, node, declaration, inputs, constructor)
    epoch = len(EPOCHS) + 1
    EPOCHS[epoch] = {'node': node, 'pointer': obj.as_pointer(), 'updates': 0, 'deleted': False}
    LIVE[obj.as_pointer()] = epoch
    return obj


def counted_update(backend, obj, time):
    UPDATE(backend, obj, time)
    EPOCHS[LIVE[obj.as_pointer()]]['updates'] += 1


def counted_delete(backend, obj):
    epoch = LIVE.pop(obj.as_pointer())
    DELETE(backend, obj)
    EPOCHS[epoch]['deleted'] = True


extended_native.import_mesh = counted_import
native.Backend.create, native.Backend.update, native.Backend.delete = counted_create, counted_update, counted_delete


class CountingWorker(Worker):
    def status(self):
        result = super().status()
        handles = {node: LIVE.get(obj.as_pointer()) for node, obj in (self.active.handles.items() if self.active else [])}
        return {**result, 'harness': {'epochs': {str(k): v for k, v in EPOCHS.items()}, 'handles': handles,
                'imports': list(IMPORTS), 'objects': sorted(o.name for o in bpy.data.objects),
                'meshes': len(bpy.data.meshes),
                'backendRecords': len(self.active.backend.records) if self.active else None}}


def start(directory, parent_pid=None, parent_start=None, provider=None):
    serve(directory, CountingWorker(), parent_pid=parent_pid, parent_start=parent_start)
'''
TETRA = ('ply\nformat ascii 1.0\nelement vertex 4\nproperty float x\nproperty float y\nproperty float z\n'
         'element face 4\nproperty list uchar int vertex_indices\nend_header\n'
         '0 0 0\n1 0 0\n0 2 0\n0 0 3\n3 0 2 1\n3 0 1 3\n3 1 2 3\n3 2 0 3\n')
FLAT = ('ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\n'
        'element face 0\nproperty list uchar int vertex_indices\nend_header\n0 0 0\n1 0 0\n0 1 0\n')


def archive():
    buffer = io.BytesIO(runtime_archive())
    with zipfile.ZipFile(buffer, 'a') as bundle:
        bundle.writestr('schemaxis_blender_transition_harness.py', HARNESS)
    return buffer.getvalue()


class CountingSession(LiveSession):
    worker_module = 'schemaxis_blender_transition_harness'


def document(path, third, *extra, visible=('moved',)):
    return {'version': 'schemaxis.blender/1', 'nodes': [
        {'id': 'mesh', 'filter': 'readPLY', 'options': {'file': str(path)}},
        {'id': 'third', 'filter': 'readPLY', 'options': {'file': str(third)}},
        {'id': 'moved', 'filter': 'transform', 'inputs': {'input': 'mesh'}, 'options': {'translation': [1, 0, 0]}},
        *extra], 'scenes': [{'id': 'preview', 'visible': list(visible),
                             'images': [{'id': 'image', 'size': [64, 64], 'cameras': [{}]}]}]}


def sibling(y):
    return {'id': 'extra', 'filter': 'transform', 'inputs': {'input': 'mesh'}, 'options': {'translation': [0, y, 0]}}


def exercise(directory, executable):
    """Run the bounded sequence and the polygon-free failure; return evidence without assertions."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path, third, flat = directory / 'tetra.ply', directory / 'third.ply', directory / 'flat.ply'
    path.write_text(TETRA)
    third.write_text(TETRA)
    flat.write_text(FLAT)
    states = [
        ('initial', document(path, third)),
        ('add sibling', document(path, third, sibling(2), visible=('moved', 'extra'))),
        ('reorder visible', document(path, third, sibling(2), visible=('extra', 'moved'))),
        ('remove sibling', document(path, third)),
        ('re-add sibling', document(path, third, sibling(2), visible=('moved', 'extra'))),
        ('change sibling option', document(path, third, sibling(3), visible=('moved', 'extra'))),
    ]
    evidence = {'steps': []}
    with patch('schemaxis.live_transport.runtime_archive', archive):
        session = CountingSession(executable, directory / 'native', timeout=120)
        process = session.process
        try:
            for label, value in states:
                applied = session.request('apply', document=value)
                evidence['steps'].append({'label': label, 'applied': applied,
                                          'geometry': session.request('geometry'), 'native': session.request('status')})
            failing = document(path, third, sibling(3), {'id': 'flat', 'filter': 'readPLY', 'options': {'file': str(flat)}},
                               visible=('moved', 'extra', 'flat'))
            failure = {}
            try:
                session.request('apply', document=failing)
            except SchemaxisError as error:
                failure['fault'] = error.fault.to_dict()
            failure['native'] = session.request('status')
            for command in ('geometry', 'apply'):
                try:
                    session.request(command, **({'document': states[0][1]} if command == 'apply' else {}))
                    failure[command] = None
                except SchemaxisError as error:
                    failure[command] = error.fault.code
            evidence['failure'] = failure
        finally:
            session.close()
    evidence['exited'] = process.poll() is not None
    evidence['returncode'] = process.poll()
    return evidence


def vertices(step, node):
    return [v for o in step['geometry']['objects'] if o['id'] == node for f in o['faces'] for v in f['vertices']]


def bounds(points):
    return [round(f(p[i] for p in points), 6) for i in range(3) for f in (min, max)]


def assert_evidence(test, evidence):
    steps = {step['label']: step for step in evidence['steps']}
    first = steps['initial']['native']
    handles = first['harness']['handles']
    for step in evidence['steps']:
        harness = step['native']['harness']
        test.assertEqual(first['pid'], step['native']['pid'])
        test.assertEqual(handles['mesh'], harness['handles']['mesh'])
        test.assertEqual(handles['moved'], harness['handles']['moved'])
        epochs = harness['epochs']
        test.assertEqual(1, epochs[str(handles['mesh'])]['updates'])
        test.assertEqual(1, epochs[str(handles['moved'])]['updates'])
        test.assertEqual(['mesh'], harness['imports'])
        test.assertEqual(sorted(harness['handles']), harness['objects'])
        test.assertEqual(len(harness['handles']), harness['backendRecords'])
        test.assertNotIn('third', harness['objects'])
        test.assertEqual([1, 2, 0, 2, 0, 3], bounds(vertices(step, 'moved')))
        test.assertEqual(4, sum(1 for o in step['geometry']['objects'] if o['id'] == 'moved' for _ in o['faces']))
    added = steps['add sibling']['native']['harness']['handles']['extra']
    readded = steps['re-add sibling']['native']['harness']['handles']['extra']
    test.assertEqual(added, steps['reorder visible']['native']['harness']['handles']['extra'])
    test.assertNotIn('extra', steps['remove sibling']['native']['harness']['handles'])
    test.assertTrue(steps['remove sibling']['native']['harness']['epochs'][str(added)]['deleted'])
    test.assertNotEqual(added, readded)
    final = steps['change sibling option']['native']['harness']['epochs']
    test.assertEqual(readded, steps['change sibling option']['native']['harness']['handles']['extra'])
    test.assertEqual(2, final[str(readded)]['updates'])
    test.assertEqual(['moved', 'extra'], [o['id'] for o in steps['add sibling']['geometry']['objects']])
    test.assertEqual(['extra', 'moved'], [o['id'] for o in steps['reorder visible']['geometry']['objects']])
    test.assertEqual([0, 1, 2, 4, 0, 3], bounds(vertices(steps['add sibling'], 'extra')))
    test.assertEqual(vertices(steps['add sibling'], 'extra'), vertices(steps['re-add sibling'], 'extra'))
    test.assertEqual([0, 1, 3, 5, 0, 3], bounds(vertices(steps['change sibling option'], 'extra')))
    for label, created in (('add sibling', ['extra']), ('reorder visible', []), ('remove sibling', []),
                           ('re-add sibling', ['extra']), ('change sibling option', [])):
        report = steps[label]['applied']['transition']
        test.assertEqual(created, report['created'])
        test.assertEqual({}, report['replaced'])
        test.assertIn('mesh', report['unaffected'])
    failure = evidence['failure']
    fault = failure['fault']
    test.assertEqual('UNCERTAIN_STATE', fault['code'])
    test.assertEqual(['extra', 'mesh', 'moved'], fault['observed']['owned'])
    test.assertEqual(['flat'], list(fault['observed']['unknown']))
    harness = failure['native']['harness']
    test.assertEqual('uncertain', failure['native']['state'])
    test.assertEqual(['mesh', 'flat'], harness['imports'])
    test.assertEqual(handles['mesh'], harness['handles']['mesh'])
    test.assertEqual(1, harness['epochs'][str(handles['mesh'])]['updates'])
    test.assertNotIn('flat', harness['handles'])
    test.assertEqual(3, harness['backendRecords'])
    test.assertIn('flat', harness['objects'])
    test.assertEqual(('UNCERTAIN_STATE', 'UNCERTAIN_STATE'), (failure['geometry'], failure['apply']))
    test.assertTrue(evidence['exited'])


@unittest.skipUnless(os.environ.get('SCHEMAXIS_LIVE_BLENDER'), 'Set SCHEMAXIS_LIVE_BLENDER for serial native acceptance')
class NativeBlenderResidentTransition(unittest.TestCase):
    def test_reader_survives_sibling_edits_and_construction_failure_is_uncertain(self):
        with tempfile.TemporaryDirectory() as temporary:
            assert_evidence(self, exercise(Path(temporary), os.environ['SCHEMAXIS_LIVE_BLENDER']))


if __name__ == '__main__': unittest.main()
