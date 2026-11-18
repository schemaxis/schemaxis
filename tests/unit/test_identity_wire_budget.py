# Copyright (C) 2026 David L. F. Gaden.
"""Actual IPC bytes and checked identity reply admission, without native imports."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from schemaxis import live_transport as transport
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.storage import digest
from schemaxis.wire_json import Budget, size
from schemaxis.identity_transition import proof, replay
from test_durable_identity import Graph, document, expected
from test_durable_identity_repair import PreviewClient
from schemaxis.console_session import AdaptorConsoleSession


class Encoding(unittest.TestCase):
    def test_exact_file_bytes_and_finite_errors(self):
        value = {'id': 'a' * 32, 'result': {'unicode': '雪😀', 'quoted': '"\\\n', 'nested': [1, {}, [False, None]]}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'wire.json'
            atomic_json(path, value)
            self.assertEqual(json.dumps(value, indent=2, allow_nan=False) + '\n', path.read_text())
            length = len(path.read_bytes())
            self.assertEqual(length, size(value, length))
            with self.assertRaises(SchemaxisError) as caught: size(value, length - 1)
            self.assertEqual('LIVE_LIMIT', caught.exception.fault.code)
        cyclic = []; cyclic.append(cyclic)
        for invalid in (float('nan'), object(), cyclic):
            with self.subTest(value=type(invalid).__name__):
                with self.assertRaises(SchemaxisError) as caught: size(invalid, 10000)
                self.assertEqual('INVALID_ARGUMENT', caught.exception.fault.code)

    def test_pretty_request_refuses_before_submission_without_termination(self):
        args = {'document': {'version': 'schemaxis/1', 'nodes': [{'id': 'x'} for _ in range(32)]}}
        envelope = {'id': '0' * 32, 'command': 'apply', 'args': args}
        compact = len(json.dumps(envelope).encode())
        self.assertGreater(size(envelope, 10000), compact + 1)
        with tempfile.TemporaryDirectory() as directory:
            client = transport.ProcessSession.__new__(transport.ProcessSession)
            client._lock, client._closed, client.provider = threading.RLock(), False, 'paraview'
            client.directory = Path(directory)
            terminated = []
            client._terminate = lambda *a, **k: terminated.append(True)
            with patch.object(transport, 'MAX_BYTES', compact + 1):
                with self.assertRaises(SchemaxisError) as caught: client.request('apply', **args)
            self.assertEqual('LIVE_LIMIT', caught.exception.fault.code)
            self.assertEqual([], terminated)
            self.assertEqual([], list(Path(directory).iterdir()))

    def test_serve_bounds_actual_results_and_fault_details(self):
        class Worker:
            provider = 'paraview'
            def dispatch(self, command, args):
                if command == 'shutdown': return {'closed': True}
                if command == 'status': raise RuntimeError('x' * 10000)
                return {'objects': [{'id': 'mesh', 'label': 'mesh'} for _ in range(32)]}
            def close(self): pass
        with tempfile.TemporaryDirectory() as directory, patch.object(transport, 'MAX_BYTES', 1600):
            root = Path(directory)
            thread = threading.Thread(target=transport.serve, args=(root, Worker()), daemon=True)
            thread.start()
            def request(command, index):
                identity = ('%032x' % index)
                atomic_json(root / 'request.json', {'id': identity, 'command': command, 'args': {}})
                path = root / (identity + '.json')
                deadline = time.monotonic() + 3
                while not path.exists() and time.monotonic() < deadline: time.sleep(.01)
                self.assertTrue(path.exists())
                self.assertLessEqual(path.stat().st_size, 1600)
                return json.loads(path.read_text())
            try:
                # Compact result fits1600; actual indented reply exceeds it.
                for index, command in enumerate(('geometry', 'status'), 1):
                    response = request(command, index)
                    self.assertEqual('LIVE_LIMIT', response['fault']['code'])
                    self.assertTrue(thread.is_alive())
            finally:
                request('shutdown', 3)
                thread.join(3)
            self.assertFalse(thread.is_alive())


class Composite(Graph):
    def geometry(self):
        root = super().geometry()[0]
        return [{**root, 'id': root['node'] + '/block/' + str(i), 'block': i} for i in range(32)]


def source_document():
    value = document()
    value['nodes'] = value['nodes'][:1]
    value['scenes'][0].update(visible={'mesh': {}}, geometry=['mesh'])
    return value


class GraphBudget(unittest.TestCase):
    def test_console_composite_rejects_before_publication_and_projection_stops_early(self):
        from schemaxis.adaptors.paraview.integration import identityGeometry
        with tempfile.TemporaryDirectory() as directory:
            with AdaptorConsoleSession(directory, 'paraview') as session:
                session._edit(source_document(), 'mesh')
                graph = Composite(); session.live = PreviewClient(graph); session.preview()
                state, runtime = copy.deepcopy(session._state), dict(session._runtime)
                geometry, handle = session._geometry, graph.active.handles['mesh']
                calls = list(graph.native.calls)
                with patch.object(transport, 'MAX_BYTES', 40000):
                    for _ in range(2):
                        with self.assertRaises(SchemaxisError) as caught:
                            session.rename('/nodes/0/id', 'a' * 1000, session.active_document, session._record['revision'])
                        self.assertEqual('LIVE_LIMIT', caught.exception.fault.code)
                        self.assertEqual(state, session._state)
                        self.assertEqual(runtime, session._runtime)
                        self.assertIs(geometry, session._geometry)
                        self.assertEqual({}, session.live_data.views)
                        self.assertEqual(calls, graph.native.calls)
                        self.assertIs(handle, graph.active.handles['mesh'])
                # Reserve identities before deep-copying all expanded members.
                original = copy.deepcopy
                copied = []
                def track(value):
                    if isinstance(value, dict) and 'block' in value: copied.append(value['block'])
                    return original(value)
                with patch('copy.deepcopy', side_effect=track):
                    with self.assertRaises(SchemaxisError):
                        identityGeometry(graph.geometry_objects, [['mesh', 'a' * 1000]], budget=Budget(4000))
                self.assertLess(len(copied), 4)

    def test_complete_observation_reply_and_direct_reidentify_are_bounded(self):
        graph = Graph(); before = source_document(); graph.apply(before)
        self.addCleanup(graph.close)
        graph.active.observations['mesh']['retainedMetadata'] = 'x' * 12000
        evidence = proof(before, '/nodes/0/id', 'globe')
        args = {'expected': expected(graph), 'proofs': [{'proof': evidence, 'reverse': False}]}
        calls, handle = list(graph.native.calls), graph.active.handles['mesh']
        with patch.object(transport, 'MAX_BYTES', 10000):
            transport.reply_budget({'objects': graph.geometry_objects})
            for command in ('graph-prepare-identity', 'graph-reidentify'):
                with self.assertRaises(SchemaxisError) as caught: graph.dispatch(command, args)
                self.assertEqual('LIVE_LIMIT', caught.exception.fault.code)
        self.assertEqual(before, graph.document)
        self.assertEqual(calls, graph.native.calls)
        self.assertIs(handle, graph.active.handles['mesh'])

    def test_status_projection_and_each_full_reply_are_admitted(self):
        graph = Graph(); before = source_document(); graph.apply(before); self.addCleanup(graph.close)
        evidence = proof(before, '/nodes/0/id', 'a' * 100)
        args = {'expected': expected(graph), 'proofs': [{'proof': evidence, 'reverse': False}]}
        original = transport.reply_budget
        kinds = []
        def record(value):
            kinds.append('geometry' if 'observations' in value else 'reidentify' if 'reidentified' in value
                         else 'prepare' if 'steps' in value else 'status')
            return original(value)
        with patch.object(transport, 'reply_budget', side_effect=record): graph.dispatch('graph-prepare-identity', args)
        self.assertEqual(['geometry', 'status', 'reidentify', 'prepare'], kinds)
        ids = graph.object_ids()
        with patch.object(graph, 'object_ids', return_value=ids * 64), patch.object(transport, 'MAX_BYTES', 12000):
            with self.assertRaises(SchemaxisError) as caught: graph.dispatch('graph-reidentify', args)
        self.assertEqual('LIVE_LIMIT', caught.exception.fault.code)
        self.assertEqual(0, graph.native.count('relabel'))

    def test_optional_inspection_keeps_measurements_and_bounds_required_metadata(self):
        from schemaxis.adaptors.paraview.live_native import inspection_reply
        required = {'node': 'mesh', 'observation': {'points': 4, 'cells': 4}, 'assemblies': {}}
        with patch.object(transport, 'MAX_BYTES', 1000):
            result = inspection_reply({**required, 'geometry': {'objects': ['x' * 2000]}})
            self.assertIsNone(result['geometry'])
            self.assertEqual('LIVE_LIMIT', result['geometryUnavailable']['code'])
            self.assertEqual(required['observation'], result['observation'])
            with self.assertRaises(SchemaxisError): inspection_reply({**required, 'geometry': None, 'assemblies': 'x' * 2000})

    def test_durable_data_preflight_and_existing_history_refuse_before_commit(self):
        from test_live_identity import Process
        with tempfile.TemporaryDirectory() as directory, patch(
                'schemaxis.adaptors.paraview.mvp.runners.require_paraview', return_value='/test/pvpython'):
            with AdaptorConsoleSession(directory, 'paraview') as session:
                Process.instances = []
                session.live_data.factory = Process
                session._edit(document(), 'mesh')
                graph = Graph(); session.live = PreviewClient(graph); session.preview()
                session.execute('data load skin')
                process = Process.instances[0]
                worker = process.worker
                worker.active.observations['mesh']['extents'] = [[0, 1, 0, 1, 0, 1]] * 64
                def refusal(action):
                    state, runtime = copy.deepcopy(session._state), dict(session._runtime)
                    views = copy.deepcopy(session.live_data.views)
                    calls = list(process.backend.calls), list(graph.native.calls)
                    handles = dict(worker.active.handles), dict(graph.active.handles)
                    with patch.object(transport, 'MAX_BYTES', 9000):
                        with self.assertRaises(SchemaxisError) as caught: action()
                    self.assertEqual('LIVE_LIMIT', caught.exception.fault.code)
                    self.assertEqual(state, session._state)
                    self.assertEqual(runtime, session._runtime)
                    self.assertEqual(views, session.live_data.views)
                    self.assertEqual(calls, (process.backend.calls, graph.native.calls))
                    for saved, current in zip(handles, (worker.active.handles, graph.active.handles)):
                        for node, handle in saved.items(): self.assertIs(handle, current[node])
                rename = lambda: session.rename('/nodes/0/id', 'globe', session.active_document, session._record['revision'])
                refusal(rename)
                rename(); session.geometry(); session.execute('data refresh skin')
                worker.active.observations['globe']['extents'] = [[0, 1, 0, 1, 0, 1]] * 64
                process.requests.clear()
                refusal(session.undo)
                self.assertIn('data-prepare-owned-identity', process.requests)
                reader = worker.active.handles['globe']
                session.undo(); session.geometry(); session.execute('data refresh skin')
                self.assertIs(reader, worker.active.handles['mesh'])
                self.assertEqual(1, process.backend.reads[reader['id']])


from test_live_identity import Fixture, Process


class DataBudget(Fixture):
    def test_current_many_port_reply_refuses_adoption_and_direct_mutation(self):
        self.live.load(self.request(self.old, nodes=['skin']))
        worker = self.worker()
        worker.active.observations['mesh']['extents'] = [[0, 1, 0, 1, 0, 1]] * 64
        snapshot = self.snapshot()
        with patch.object(transport, 'MAX_BYTES', 16000):
            with self.assertRaises(SchemaxisError) as caught: self.rename(self.old, name='a' * 300)
        self.assertEqual('LIVE_LIMIT', caught.exception.fault.code)
        self.assertEqual(snapshot, self.snapshot())
        process = Process.instances[0]
        steps = [['mesh', 'a' * 300]]
        result = digest(replay(worker.document, steps))
        calls = list(process.backend.calls)
        with patch.object(transport, 'MAX_BYTES', 16000):
            with self.assertRaises(SchemaxisError) as caught:
                process.request('data-reidentify', expected=digest(worker.document), steps=steps, result=result)
        self.assertEqual('LIVE_LIMIT', caught.exception.fault.code)
        self.assertEqual(calls, process.backend.calls)
        self.assertIn('mesh', worker.active.handles)

    def test_cached_only_many_port_observations_refuse_without_loading(self):
        self.live.load(self.request(self.old, nodes=['skin']))
        key = next(key for key, items in self.live.cache.items() if items[0]['node'] == 'mesh')
        item = self.live.cache[key][0]
        self.live.cache[key] = [{**item, 'port': port} for port in range(64)]
        self.live.unload()
        self.assertEqual({}, self.live.workers)
        snapshot = self.snapshot()
        with patch.object(transport, 'MAX_BYTES', 20000):
            with self.assertRaises(SchemaxisError) as caught: self.rename(self.old, name='a' * 300)
        self.assertEqual('LIVE_LIMIT', caught.exception.fault.code)
        self.assertEqual(snapshot, self.snapshot())
        self.assertEqual(1, self.created)

    def test_existing_view_inverse_prepares_before_history_publication(self):
        self.live.load(self.request(self.old, nodes=['skin']))
        preview, adopted = self.rename(self.old)
        self.live.refresh(self.request(preview['input'], adopted['to']))
        worker = self.worker()
        calls = list(self.backend.calls)
        Process.instances[0].requests.clear()
        self.live.check_identity_view(self.request(self.old), adopted['from'])
        self.assertIn('data-prepare-owned-identity', Process.instances[0].requests)
        self.assertEqual(calls, self.backend.calls)
        self.assertIn('globe', worker.active.handles)
