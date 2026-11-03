# Copyright (C) 2026 David L F Gaden
"""Host lifecycle tests and opt-in serial native Blender acceptance."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import selectors
import signal
import unittest
from unittest.mock import patch

from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.blender.live import LiveSession
from schemaxis.adaptors.blender.live_runtime import GraphWorker
from schemaxis.adaptors.blender.live_transport import validate, serve, owner_alive, process_identity
from schemaxis.dispatch import allocation


def document(size=2):
    return {'version': 'schemaxis.blender/1', 'nodes': [
        {'id': 'paint', 'filter': 'material'},
        {'id': 'box', 'filter': 'cube', 'inputs': {'material': 'paint'}, 'options': {'size': size}}],
        'scenes': [{'id': 'preview', 'visible': ['box'],
                    'images': [{'id': 'image', 'size': [64, 64], 'cameras': [{}]}]}]}


def qualify_owner_death(test, provider, executable):
    """Kill only a known host PID, then check its native child exits by itself."""
    with tempfile.TemporaryDirectory() as directory:
        expression = (f'from schemaxis.adaptors.{provider}.live import LiveSession; import json,time; '
                      f's=LiveSession({executable!r},{str(Path(directory) / "session")!r}); '
                      'print(json.dumps({"pid":s.request("status")["pid"]}),flush=True); time.sleep(60)')
        host = subprocess.Popen([sys.executable, '-c', expression], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        pid, identity = None, None
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(host.stdout, selectors.EVENT_READ)
                test.assertTrue(selector.select(30), 'Native owner did not become ready')
            line = host.stdout.readline()
            test.assertTrue(line, 'Host exited before reporting its native PID')
            pid = json.loads(line)['pid']
            identity = process_identity(pid)
            test.assertIsNotNone(identity)
            host.terminate()  # No custom SIGTERM handler: exercises orphan cleanup.
            host.wait(timeout=5)
            deadline = time.monotonic() + 5
            while owner_alive(pid, identity[1]) and time.monotonic() < deadline:
                time.sleep(0.05)
            test.assertFalse(owner_alive(pid, identity[1]), 'Native worker survived owner death')
        finally:
            if host.poll() is None:
                host.kill()
                host.wait(timeout=5)
            if pid and identity and owner_alive(pid, identity[1]):
                os.kill(pid, signal.SIGKILL)
            host.stdout.close()
            host.stderr.close()


class FakeBackend:
    def __init__(self, owner):
        self.owner = owner

    def create(self, node, declaration, inputs, constructor):
        return {'id': node, 'options': {}}

    def configure(self, obj, declaration, changes):
        obj['options'].update(changes)
        if changes.get('size') == 13:
            raise RuntimeError('injected native failure after mutation')
        if self.owner.fail_restore and changes.get('size') == 2:
            raise RuntimeError('injected restoration failure')

    def update(self, obj, time):
        pass

    def observe(self, obj):
        return copy.deepcopy(obj['options'])

    def delete(self, obj):
        pass


class FakeWorker(GraphWorker):
    provider = 'blender'
    fail_restore = False

    def backend(self): return FakeBackend(self)
    def reset_native(self): pass
    def present(self, prepared): pass
    def object_ids(self): return list(self.active.handles)
    def geometry(self): return copy.deepcopy(self.active.observations)


class LiveHostTests(unittest.TestCase):
    def test_host_imports_do_not_load_native_modules(self):
        result = subprocess.run([sys.executable, '-c',
            'import sys; import schemaxis.adaptors.blender.live; import schemaxis.adaptors.paraview.live; '
            'assert "bpy" not in sys.modules and "paraview.simple" not in sys.modules'],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_reuse_revision_validation_and_rollback(self):
        worker = FakeWorker()
        first = worker.apply(document())
        obj = worker.active.handles['box']
        second = worker.apply(document(3))
        self.assertTrue(second['reused'])
        self.assertIs(worker.active.handles['box'], obj)
        self.assertEqual((first['revision'], second['revision']), (1, 2))
        with self.assertRaises(SchemaxisError): worker.apply(document(-1))
        self.assertIs(worker.active.handles['box'], obj)
        with self.assertRaises(SchemaxisError) as caught: worker.apply(document(13))
        self.assertTrue(caught.exception.fault.observed['rolledBack'])
        self.assertEqual(worker.document, document(3))
        self.assertEqual(worker.active.observations['box']['size'], 3)
        self.assertEqual(worker.revision, 2)

    def test_uncertain_state_blocks_reads_and_edits(self):
        worker = FakeWorker()
        worker.apply(document())
        worker.fail_restore = True
        with self.assertRaises(SchemaxisError) as caught: worker.apply(document(13))
        self.assertEqual(caught.exception.fault.code, 'UNCERTAIN_STATE')
        self.assertEqual(worker.status()['state'], 'uncertain')
        for command, args in [('geometry', {}), ('apply', {'document': document(4)})]:
            with self.assertRaises(SchemaxisError): worker.dispatch(command, args)

    def test_geometry_carries_revision_scoped_observations_without_mutating_native_state(self):
        worker = FakeWorker()
        worker.apply(document())
        worker.active.observations['box']['fields'] = {'POINTS': {'pressure': {'components': 1}}}
        reply = worker.dispatch('geometry', {})
        self.assertEqual(reply['revision'], worker.revision)
        self.assertEqual(reply['observations']['box']['fields'], {'POINTS': {'pressure': {'components': 1}}})
        reply['observations']['box']['fields']['POINTS']['pressure']['components'] = 3
        self.assertEqual(worker.active.observations['box']['fields']['POINTS']['pressure']['components'], 1)
        worker.apply(document(3))
        updated = worker.dispatch('geometry', {})
        self.assertEqual(updated['revision'], 2)
        self.assertEqual(updated['observations']['box']['size'], 3)
        self.assertNotIn('fields', updated['observations']['box'])

    def test_rejects_batch_and_arbitrary_commands(self):
        worker = FakeWorker()
        authored = document()
        authored['nodes'][1]['options']['size'] = {'$axis': 'sizes'}
        authored['axes'] = [{'name': 'sizes', 'values': [1, 2]}]
        with self.assertRaises(SchemaxisError) as caught: worker.apply(authored)
        self.assertEqual(caught.exception.fault.code, 'UNSUPPORTED_LIVE_INPUT')
        for command, args in [('exec', {'code': 'print(1)'}), ('status', {'extra': True}),
                              ('apply', {'document': document(float('nan'))})]:
            with self.assertRaises(SchemaxisError): validate(command, args)

    def test_startup_exit_and_timeout_reap_process(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(SchemaxisError) as caught:
                LiveSession('/bin/true', Path(root) / 'exit', startup_timeout=2)
            self.assertEqual(caught.exception.fault.code, 'NATIVE_EXIT')
            real_popen, processes = subprocess.Popen, []
            def launch(*args, **kwargs):
                process = real_popen([sys.executable, '-c', 'import time; time.sleep(30)'], **kwargs)
                processes.append(process)
                return process
            with patch('schemaxis.adaptors.blender.live_transport.subprocess.Popen', side_effect=launch):
                with self.assertRaises(SchemaxisError) as caught:
                    LiveSession('/bin/true', Path(root) / 'timeout', startup_timeout=0.1)
            self.assertEqual(caught.exception.fault.code, 'LIVE_TIMEOUT')
            self.assertIsNotNone(processes[0].poll())

    def test_idle_worker_closes_when_host_exits(self):
        worker = FakeWorker()
        worker.apply(document())
        with tempfile.TemporaryDirectory() as directory:
            with patch('schemaxis.adaptors.blender.live_transport.os.kill', side_effect=ProcessLookupError):
                serve(directory, worker, parent_pid=1234)
        self.assertIsNone(worker.active)

    def test_owner_identity_rejects_zombies_and_pid_reuse(self):
        with patch('schemaxis.adaptors.blender.live_transport.os.kill'):
            with patch('schemaxis.adaptors.blender.live_transport.process_identity', return_value=('Z', '11')):
                self.assertFalse(owner_alive(123, '11'))
            with patch('schemaxis.adaptors.blender.live_transport.process_identity', return_value=('S', '12')):
                self.assertFalse(owner_alive(123, '11'))
                self.assertTrue(owner_alive(123, '12'))

    def test_cancellation_interrupts_pending_request_and_reaps_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            session = LiveSession.__new__(LiveSession)
            session._lock = threading.RLock()
            session._closed = False
            session._log = None
            session.directory = Path(directory)
            session.timeout = 30
            session.process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)
            cancelled = threading.Event()
            timer = threading.Timer(0.1, cancelled.set)
            started = time.monotonic()
            timer.start()
            try:
                with allocation({}, cancelled), self.assertRaises(SchemaxisError) as caught:
                    session.request('status')
                self.assertEqual(caught.exception.fault.code, 'RUNNER_CANCELLED')
                self.assertTrue(session._closed)
                self.assertIsNotNone(session.process.poll())
                self.assertLess(time.monotonic() - started, 3)
            finally:
                timer.join()
                session._terminate()

    def test_save_suffix_and_receipt_overwrite_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'scene.blend'
            validate('save', {'path': str(target)}, 'blender')
            with self.assertRaises(SchemaxisError): validate('save', {'path': str(target)}, 'paraview')
            receipt = Path(str(target) + '.receipt.json')
            receipt.touch()
            with self.assertRaises(SchemaxisError): validate('save', {'path': str(target)}, 'blender')


@unittest.skipUnless(os.environ.get('SCHEMAXIS_LIVE_BLENDER'), 'Set SCHEMAXIS_LIVE_BLENDER for serial native acceptance')
class BlenderNativeLiveTests(unittest.TestCase):
    def test_native_worker_exits_when_host_is_terminated(self):
        qualify_owner_death(self, 'blender', os.environ['SCHEMAXIS_LIVE_BLENDER'])

    def test_existing_mesh_workshop_operations(self):
        root = Path(__file__).resolve().parents[2]
        workshop = json.loads((root / 'examples/schemaxis/expanded/blender-mesh-workshop.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            with LiveSession(os.environ['SCHEMAXIS_LIVE_BLENDER'], Path(directory) / 'session', timeout=120) as session:
                pid = session.request('status')['pid']
                for operation in workshop['operations']:
                    authored = copy.deepcopy(operation['document'])
                    for axis in authored.get('axes', []):
                        axis['values'] = axis['values'][-1:]
                    for node in authored['nodes']:
                        if 'file' in node.get('options', {}):
                            node['options']['file'] = str(root / node['options']['file'])
                    with self.subTest(operation=operation['id']):
                        result = session.request('apply', document=authored)
                        self.assertEqual(result['pid'], pid)
                        geometry = session.request('geometry')
                        self.assertTrue(geometry['objects'][0]['faces'])

    def test_persistent_edit_geometry_image_and_failure(self):
        with tempfile.TemporaryDirectory() as root:
            with LiveSession(os.environ['SCHEMAXIS_LIVE_BLENDER'], Path(root) / 'session', timeout=120) as session:
                a = session.request('apply', document=document())
                geometry = session.request('geometry')
                self.assertEqual(len(geometry['objects'][0]['faces']), 6)
                self.assertEqual(sum(len(f['triangles']) for f in geometry['objects'][0]['faces']), 12)
                b = session.request('apply', document=document(4))
                self.assertEqual(a['pid'], b['pid'])
                self.assertEqual(a['objects'], b['objects'])
                geometry = session.request('geometry')
                xs = [v[0] for f in geometry['objects'][0]['faces'] for v in f['vertices']]
                self.assertEqual((min(xs), max(xs)), (-2, 2))
                # Invalid native file construction must rebuild the previous mesh.
                broken = document()
                broken['nodes'] = [{'id': 'missing', 'filter': 'readSTL', 'options': {'file': str(Path(root) / 'absent.stl')}}]
                broken['scenes'][0]['visible'] = ['missing']
                with self.assertRaises(SchemaxisError) as caught: session.request('apply', document=broken)
                self.assertTrue(caught.exception.fault.observed['rolledBack'])
                self.assertEqual(session.request('geometry'), geometry)
                image = session.image(Path(root) / 'preview.png')
                self.assertTrue(image['verified'])
                self.assertTrue(Path(image['file']).is_file())
                self.assertEqual(session.request('status')['pid'], a['pid'])
                saved = session.save(Path(root) / 'scene.blend')
                self.assertTrue(saved['verified'])
                metadata = json.loads(Path(saved['receipt']).read_text())
                self.assertEqual(metadata['document'], document(4))
                self.assertEqual(saved['geometryDigest'], session.request('status')['geometryDigest'])
                self.assertEqual(session.request('geometry'), geometry)
                session.request('apply', document=document(5))
                self.assertEqual(session.request('status')['pid'], a['pid'])
                process = session.process
            self.assertIsNotNone(process.poll())
            session.close()
            with self.assertRaises(SchemaxisError): session.request('status')
            # A separate native process reopens the saved copy after the live
            # worker exits and compares actual evaluated geometry, not file size.
            expression = (
                'import sys,json; from types import SimpleNamespace; '
                f'sys.path.insert(0,{str(session.directory / "runtime.zip")!r}); '
                'import bpy; from schemaxis.adaptors.blender.live_native import Worker; '
                'from schemaxis.pipeline import digest; '
                'metadata=json.loads(bpy.context.scene["schemaxisLiveReceipt"]); '
                'worker=Worker(); worker.prepared=(None,None,None,metadata["visible"]); '
                'worker.active=SimpleNamespace(handles={n:bpy.data.objects[n] for n in metadata["visible"]}); '
                'assert digest(worker.geometry()) == metadata["geometryDigest"]')
            result = subprocess.run([os.environ['SCHEMAXIS_LIVE_BLENDER'], '--background', '--disable-autoexec',
                saved['file'], '--python-exit-code', '1', '--python-expr', expression],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
