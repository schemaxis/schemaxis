# Copyright (C) 2026 David L. F. Gaden.
"""History applicability, optional witnesses and bounded checked identity work."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from schemaxis.console_session import AdaptorConsoleSession
from schemaxis.core.faults import SchemaxisError
from schemaxis.storage import atomic, AtomicPublicationError, digest, encoded
from test_durable_identity import Graph, GraphClient, document


class PreviewClient(GraphClient):
    def request(self, command, **args):
        result = super().request(command, **args)
        if isinstance(result, dict) and 'capabilities' in result:
            result = {**result, 'capabilities': [c for c in result['capabilities'] if c != 'save']}
        return result


class HistoryRepair(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.session = AdaptorConsoleSession(self.temp.name, 'paraview')
        self.addCleanup(lambda: self.session.close())
        self.session._edit(document(), 'mesh')
        self.graph = Graph()
        self.session.live = PreviewClient(self.graph)
        self.graph.apply(document())

    def rename(self, name='globe'):
        s = self.session
        return s.rename('/nodes/0/id', name, s.active_document, s._record['revision'])

    def edit(self):
        s = self.session
        s.patch([{'op': 'replace', 'path': '/nodes/1/options/factor', 'value': 0.6}],
                s.active_document, s._record['revision'])

    def test_public_preview_invalidates_only_inapplicable_archive(self):
        for aligned in (False, True):
            with self.subTest(aligned=aligned):
                self.assertEqual('succeeded', self.session.preview()['status'])
                self.rename('globe' if self.session.document['nodes'][0]['id'] == 'mesh' else 'mesh')
                if aligned:
                    self.session.geometry()
                self.edit()
                self.assertEqual('succeeded', self.session.preview()['status'])
                relabels = self.graph.native.count('relabel')
                self.session.undo()
                self.assertNotIn('pendingIdentity', self.session._runtime)
                self.assertEqual('succeeded', self.session.preview()['status'])
                self.assertEqual(relabels, self.graph.native.count('relabel'))
                self.session.geometry()
                self.session.undo()  # The preceding rename still has exact authored proof.
                self.session.geometry()
                self.session.redo()
                self.session.geometry()

    def test_visible_ordinary_publication_cleans_pending_all_paths(self):
        s = self.session
        def published(path, payload, *args):
            atomic(path, payload, *args)
            raise AtomicPublicationError(path, OSError('directory fsync'))
        for action in ('patch', 'source', 'open', 'undo'):
            with self.subTest(action=action):
                self.graph.apply(s.document)
                self.rename('next' if s.document['nodes'][0]['id'] != 'next' else 'other')
                value = s.document
                value['nodes'][1]['options']['factor'] = 0.6
                if action == 'undo':
                    self.edit()
                    s.undo()  # Restore pending rename, then ordinary Redo to edited state.
                path = Path(self.temp.name) / 'input.json'
                path.write_text(json.dumps(value))
                with patch('schemaxis.console_session.atomic', side_effect=published):
                    with self.assertRaises(AtomicPublicationError):
                        if action == 'patch': self.edit()
                        elif action == 'source': s.edit_source(json.dumps(value), s.active_document, s._record['revision'])
                        elif action == 'open': s.open(path)
                        else: s.redo()
                self.assertNotIn('pendingIdentity', s._runtime)
                self.assertEqual('succeeded', s.preview()['status'])
                s.geometry()

    def test_unpublished_ordinary_failure_preserves_pending_and_state(self):
        self.rename()
        s = self.session
        state, pending = copy.deepcopy(s._state), copy.deepcopy(s._runtime['pendingIdentity'])
        with patch('schemaxis.console_session.atomic', side_effect=OSError('not published')):
            with self.assertRaises(OSError): self.edit()
        self.assertEqual(state, s._state)
        self.assertEqual(pending, s._runtime['pendingIdentity'])
        s.geometry()

    def test_stale_base_uncertainty_and_dead_transport_are_precise(self):
        s = self.session
        self.edit()
        state = copy.deepcopy(s._state)
        calls, handles = list(self.graph.native.calls), dict(self.graph.active.handles)
        with self.assertRaises(SchemaxisError) as caught: self.rename()
        self.assertEqual('STALE_IDENTITY_TRANSITION', caught.exception.fault.code)
        self.assertIn('Preview the current document', str(caught.exception))
        self.assertEqual(state, s._state)
        self.graph.uncertain = True
        with self.assertRaisesRegex(SchemaxisError, 'explicitly release'): self.rename()
        self.assertEqual('NO_RESIDENT_DATA', s._native_fault['code'])
        self.assertFalse(s.status()['resident'])
        self.graph.uncertain = False
        client = s.live
        with patch.object(client, 'request', side_effect=OSError('dead transport')):
            with self.assertRaises(SchemaxisError) as caught: self.rename()
        self.assertEqual('NATIVE_TRANSPORT_FAILED', caught.exception.fault.code)
        self.assertEqual(caught.exception.fault.code, s._native_fault['code'])
        self.assertIs(client, s.live)
        self.assertEqual(state, s._state)
        self.assertEqual(calls, self.graph.native.calls)
        for name, handle in handles.items():
            self.assertIs(handle, self.graph.active.handles[name])

    def test_checked_preparation_refusals_preserve_healthy_preview(self):
        from schemaxis.adaptors import registry
        s, graph = self.session, self.graph
        s.preview()
        metadata = registry.metadata
        prepare = graph.prepare_identity
        def unsupported(provider):
            value = copy.deepcopy(metadata(provider))
            value.pop('liveIdentityGeometry', None)
            return value
        def mismatch(expected, proofs):
            return prepare({**expected, 'revision': expected['revision'] + 1}, proofs)
        for target, replacement, code in ((registry, unsupported, 'UNSUPPORTED_IDENTITY_TRANSITION'),
                                          (graph, mismatch, 'STALE_IDENTITY_TRANSITION')):
            with self.subTest(code=code):
                state, runtime = copy.deepcopy(s._state), dict(s._runtime)
                client, geometry = s.live, s._geometry
                views, calls = copy.deepcopy(s.live_data.views), list(graph.native.calls)
                handles = dict(graph.active.handles)
                with patch.object(target, 'metadata' if target is registry else 'prepare_identity', side_effect=replacement):
                    with self.assertRaises(SchemaxisError) as caught: self.rename()
                self.assertEqual(code, caught.exception.fault.code)
                self.assertEqual(state, s._state)
                self.assertEqual(runtime, s._runtime)
                self.assertIs(geometry, s._geometry)
                self.assertIs(client, s.live)
                self.assertEqual(views, s.live_data.views)
                self.assertEqual(calls, graph.native.calls)
                for name, handle in handles.items(): self.assertIs(handle, graph.active.handles[name])
                self.assertTrue(s.status()['resident'])
                self.assertIsNone(s.status()['nativeFault'])
                s.geometry()

    def test_uncertain_preparation_fault_and_successful_preview_recovery(self):
        from schemaxis.errors import fail
        s, graph = self.session, self.graph
        s.preview()
        state, calls, client = copy.deepcopy(s._state), list(graph.native.calls), s.live
        handles = dict(graph.active.handles)
        for code, observations in (('UNSUPPORTED_IDENTITY_TRANSITION', {'uncertain': True}),
                                   ('NATIVE_DIVERGENCE', {})):
            def refusal(*args): fail(code, 'uncertain native owner', **observations)
            with patch.object(graph, 'prepare_identity', side_effect=refusal):
                with self.assertRaises(SchemaxisError): self.rename()
            self.assertEqual(code, s._native_fault['code'])
            self.assertFalse(s.status()['resident'])
            self.assertEqual(state, s._state)
            self.assertEqual(calls, graph.native.calls)
            self.assertIs(client, s.live)
            for name, handle in handles.items(): self.assertIs(handle, graph.active.handles[name])
            self.assertEqual('succeeded', s.preview()['status'])
            self.assertIsNone(s._native_fault)
            self.assertEqual('resident', s.status()['nativeState'])
            state, calls = copy.deepcopy(s._state), list(graph.native.calls)
            handles = dict(graph.active.handles)

    def test_cancelled_chain_reads_existing_geometry_without_apply(self):
        s = self.session
        handle = self.graph.active.handles['mesh']
        self.rename()
        s.undo()
        self.assertEqual([], s._runtime['pendingIdentity']['proofs'])
        self.assertEqual('succeeded', s.preview()['status'])
        self.assertIs(handle, self.graph.active.handles['mesh'])
        self.assertEqual(1, self.graph.resets)
        self.assertEqual(1, self.graph.native.reads[handle['id']])
        s.redo()
        s.geometry()
        self.assertIs(handle, self.graph.active.handles['globe'])

    def test_long_pending_chain_bound_keeps_undo_redo_and_alignment_usable(self):
        s = self.session
        handle = self.graph.active.handles['mesh']
        start = time.monotonic()
        for index in range(32): self.rename('n' + str(index))
        construction = time.monotonic() - start
        state = copy.deepcopy(s._state)
        with self.assertRaisesRegex(SchemaxisError, 'Preview') as caught: self.rename('overflow')
        self.assertEqual('IDENTITY_LIMIT', caught.exception.fault.code)
        self.assertIn('Undo, Redo or rename', str(caught.exception))
        self.assertNotIn('Undo remains available', str(caught.exception))
        self.assertEqual(state, s._state)
        s.undo()
        self.assertEqual(31, len(s._runtime['pendingIdentity']['proofs']))
        s.redo()
        self.assertEqual(32, len(s._runtime['pendingIdentity']['proofs']))
        start = time.monotonic()
        s.geometry()
        alignment = time.monotonic() - start
        self.rename('overflow')
        s.geometry()
        self.assertIs(handle, self.graph.active.handles['overflow'])
        self.assertEqual(1, self.graph.native.reads[handle['id']])
        print('32-step host construction %.3fs; worker alignment %.3fs' % (construction, alignment), flush=True)

    def test_unused_family_renames_do_not_consume_another_familys_views(self):
        from test_live_identity import Process
        s = self.session
        s.live_data.factory = Process
        original = s.active_document
        old = s.document
        with patch('schemaxis.adaptors.paraview.mvp.runners.require_paraview', return_value='/test/pvpython'):
            s.execute('data load skin')
            self.rename()
            old_request = {'input': old, 'sessionDocument': original}
            old_handle = s.live_data.inspect(old_request, 'mesh')['handle']
            old_worker = next(w for k, w in s.live_data.workers.items() if k[1] == original)
            old_object = old_worker['client'].worker.active.handles['mesh']
            edge_count = len(s.live_data.edges)
            s.new('unused')
            s._edit(document(), 'mesh')
            for index in range(34): self.rename('unused' + str(index))
            s.undo(); s.redo()
            self.assertEqual(edge_count, len(s.live_data.edges))
            self.assertNotIn(None, s._runtime.get('identityViews', {}))
            s.execute('data load skin')
            fresh = s.live_data.inspect({'input': s.document, 'sessionDocument': s.active_document}, 'unused33')
            new_worker = next(w for k, w in s.live_data.workers.items() if k[1] == s.active_document)
            self.assertIsNot(old_object, new_worker['client'].worker.active.handles['unused33'])
            self.assertEqual(1, old_worker['client'].backend.reads[old_object['id']])
            self.assertEqual(old_handle, s.live_data.inspect(old_request, 'mesh')['handle'])
            self.assertEqual(edge_count, len(s.live_data.edges))


    def test_visible_publication_with_live_family_installs_metadata_once(self):
        from test_live_identity import Process
        s = self.session
        s.live_data.factory = Process
        def published(path, payload, *args):
            atomic(path, payload, *args)
            raise AtomicPublicationError(path, OSError('directory fsync'))
        with patch('schemaxis.adaptors.paraview.mvp.runners.require_paraview', return_value='/test/pvpython'):
            s.execute('data load skin')
            worker = next(iter(s.live_data.workers.values()))['client']
            handle = worker.worker.active.handles['mesh']
            calls = list(worker.backend.calls)
            with patch('schemaxis.console_session.atomic', side_effect=published):
                with self.assertRaises(AtomicPublicationError): self.rename()
            self.assertEqual(calls, worker.backend.calls)
            self.assertEqual(1, len(s.live_data.edges))
            self.assertIn(None, s._runtime['identityViews'])
            s.geometry()
            s.execute('data refresh skin')
            self.assertIs(handle, worker.worker.active.handles['globe'])
            s.undo()
            s.execute('data refresh skin')
            self.assertIs(handle, worker.worker.active.handles['mesh'])
            self.assertEqual(1, len(s.live_data.edges))
            self.assertEqual(1, worker.backend.reads[handle['id']])


class RecoveryPolicy(unittest.TestCase):
    def test_valid_catalogue_upgrade_keeps_source_history_without_old_credit(self):
        from schemaxis.adaptors.paraview import filters
        with tempfile.TemporaryDirectory() as directory:
            s = AdaptorConsoleSession(directory, 'paraview')
            s._edit(document(), 'mesh')
            original = s._record['source']
            s.rename('/nodes/0/id', 'globe', s.active_document, s._record['revision'])
            renamed = s._record['source']
            revision = s._record['revision']
            s.close()
            catalogue = copy.deepcopy(filters.catalogue())
            catalogue['newHarmlessSibling'] = copy.deepcopy(catalogue['shrink'])
            with patch.object(filters, 'catalogue', return_value=catalogue):
                with AdaptorConsoleSession(directory, 'paraview') as recovered:
                    self.assertEqual(renamed, recovered._record['source'])
                    self.assertEqual(revision, recovered._record['revision'])
                    self.assertNotIn('identityTransition', recovered._record)
                    recovered.undo()
                    self.assertEqual(original, recovered._record['source'])
                    recovered.redo()
                    self.assertEqual(renamed, recovered._record['source'])
                    self.assertEqual({}, recovered.live_data.views)
                    self.assertNotIn('pendingIdentity', recovered._runtime)

    def test_unchanged_policy_rejects_consistent_nonidentity_forgery(self):
        with tempfile.TemporaryDirectory() as directory:
            with AdaptorConsoleSession(directory, 'paraview') as s:
                s._edit(document(), 'mesh')
                s.rename('/nodes/0/id', 'globe', s.active_document, s._record['revision'])
            path = Path(directory) / 'session.json'
            payload = json.loads(path.read_text())
            record = payload['state']['documents'][payload['state']['activeDocument']]
            proof = record['identityTransition']['proof']
            proof['after']['nodes'][1]['options']['factor'] = 0.9
            proof['binding']['outputDigest'] = digest(proof['after'])
            record['document'] = copy.deepcopy(proof['after'])
            record.pop('source', None)
            payload['sha256'] = digest(payload['state'])
            path.write_bytes(encoded(payload))
            with self.assertRaises(SchemaxisError) as caught: AdaptorConsoleSession(directory, 'paraview')
            self.assertEqual('RECOVERY_FAILED', caught.exception.fault.code)
            self.assertEqual('STALE_IDENTITY_TRANSITION', caught.exception.fault.observed['cause'])

    def test_malformed_saved_marker_is_not_an_upgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            s = AdaptorConsoleSession(directory, 'paraview')
            s._edit(document(), 'mesh')
            s.rename('/nodes/0/id', 'globe', s.active_document, s._record['revision'])
            s.close()
            path = Path(directory) / 'session.json'
            payload = json.loads(path.read_text())
            record = payload['state']['documents'][payload['state']['activeDocument']]
            record['identityTransition']['proof']['binding']['inputDigest'] = '0' * 64
            payload['sha256'] = digest(payload['state'])
            path.write_bytes(encoded(payload))
            with self.assertRaises(SchemaxisError) as caught: AdaptorConsoleSession(directory, 'paraview')
            self.assertEqual('RECOVERY_FAILED', caught.exception.fault.code)


class PolicyCache(unittest.TestCase):
    def test_cache_is_defensive_and_tracks_all_loaded_data(self):
        from schemaxis import identity_policy as policy
        from schemaxis.adaptors import registry
        provider, route = registry.resolve(document())
        actual = registry.binding
        values = [copy.deepcopy(value) for value in (actual(route['authoringReferences'])(), actual(route['schema'])(), registry.declarations(provider))]
        policy._validated.clear()
        def binding(name):
            if name == route['authoringReferences']: return lambda: values[0]
            if name == route['schema']: return lambda: values[1]
            return actual(name)
        with patch.object(registry, 'binding', side_effect=binding), patch.object(registry, 'declarations', side_effect=lambda p: values[2]), patch.object(policy, 'validate', wraps=policy.validate) as validate:
            first = policy.for_route(provider, route)
            first['projection']['node']['operations'].clear()
            self.assertTrue(policy.for_route(provider, route)['projection']['node']['operations'])
            self.assertEqual(1, validate.call_count)
            for index, key in [(0, 'version'), (1, 'unsupportedMarkerConstraint'), (2, 'bad')]:
                saved = copy.deepcopy(values)
                if index == 0: values[index][key] = 'invalid'
                elif index == 1: values[index]['properties']['nodes']['items']['oneOf'][0]['properties']['id']['const'] = 'A'
                else: values[index][key] = copy.deepcopy(values[index]['shrink'])
                with self.assertRaises(SchemaxisError) as caught: policy.for_route(provider, route)
                self.assertEqual('INVALID_REFERENCE_POLICY', caught.exception.fault.code)
                values[:] = saved
            self.assertEqual(4, validate.call_count)
            values[0]['bad'] = float('nan')
            with self.assertRaises(SchemaxisError) as caught: policy.for_route(provider, route)
            self.assertEqual('INVALID_REFERENCE_POLICY', caught.exception.fault.code)
            values[0]['bad'] = object()
            with self.assertRaises(SchemaxisError) as caught: policy.for_route(provider, route)
            self.assertEqual('INVALID_REFERENCE_POLICY', caught.exception.fault.code)

    def test_request_snapshot_is_fresh_after_failure_and_worker_does_not_inherit(self):
        from schemaxis import identity_policy as policy
        from schemaxis.adaptors import registry
        from schemaxis.identity_transition import proof
        from test_durable_identity import expected
        provider, route = registry.resolve(document())
        graph = Graph()
        self.addCleanup(graph.close)
        graph.apply(document())
        evidence = proof(document(), '/nodes/0/id', 'globe')
        actual = registry.binding
        schema = copy.deepcopy(actual(route['schema'])())
        def binding(name):
            return (lambda: schema) if name == route['schema'] else actual(name)
        @policy.policy_request
        def host():
            original = policy.for_route(provider, route)
            schema['properties']['nodes']['items']['oneOf'][0]['properties']['id']['const'] = 'A'
            self.assertEqual(original, policy.for_route(provider, route))
            # Even this in-process worker must independently load the now changed schema.
            return graph.dispatch('graph-prepare-identity', {'expected': expected(graph),
                'proofs': [{'proof': evidence, 'reverse': False}]})
        with patch.object(registry, 'binding', side_effect=binding):
            with self.assertRaises(SchemaxisError) as caught: host()
            self.assertEqual('INVALID_REFERENCE_POLICY', caught.exception.fault.code)
            self.assertIsNone(policy._request.get())
            with self.assertRaises(SchemaxisError): policy.for_route(provider, route)
        self.assertTrue(policy.for_route(provider, route)['projection'])
        self.assertEqual(1, graph.resets)
        self.assertEqual(0, graph.native.count('relabel'))

    def test_request_snapshots_are_context_local_and_cache_is_bounded(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from schemaxis import identity_policy as policy
        from schemaxis.adaptors import registry
        barrier = Barrier(2)
        @policy.policy_request
        def task(value):
            policy._request.get()['test'] = value
            barrier.wait(timeout=10)
            return policy._request.get()['test']
        with ThreadPoolExecutor(2) as pool:
            a, b = pool.submit(task, 'a'), pool.submit(task, 'b')
            self.assertEqual(('a', 'b'), (a.result(), b.result()))
        self.assertIsNone(policy._request.get())
        provider, route = registry.resolve(document())
        policy._validated.clear()
        with patch.object(policy, '_CACHE_ENTRIES', 2):
            for index in range(3): policy.for_route(provider, {**route, 'cacheTest': index})
            self.assertEqual(2, len(policy._validated))
        policy._validated.clear()
        with patch.object(policy, '_CACHE_BYTES', 1):
            policy.for_route(provider, route)
            self.assertEqual(0, len(policy._validated))

    def test_hot_plugin_load_fault_still_quarantines_but_loaded_data_does_not(self):
        import sys
        import warnings
        from types import SimpleNamespace
        from schemaxis import identity_policy as policy
        from schemaxis.adaptors import registry
        provider, pv_route = registry.resolve(document())
        data = copy.deepcopy(registry.binding(pv_route['authoringReferences'])())
        schema = registry.binding(pv_route['schema'])()
        declarations = registry.declarations(provider)
        root = Path(__file__).resolve().parents[2]
        entry = SimpleNamespace(name='fixtureplugin', value='schemaxis_fixture_plugin', group=registry.GROUP,
                                dist=SimpleNamespace(name='schemaxis-fixture-plugin'))
        with patch.object(sys, 'path', [str(root / 'tests/fixtures/plugin_adaptor'), *sys.path]):
            admitted = registry.load_registry(plugins=[entry], strict=True)['fixtureplugin']
            route = admitted['routes'][admitted['version']]
            route['authoringReferences'] = admitted['package'] + ':successful_policy'
            broken = [False]
            actual = registry.binding
            def load_policy():
                if broken[0]: raise RuntimeError('plugin load failed after hot admission')
                return data
            def binding(name):
                if name == route['authoringReferences']: return load_policy
                if name == route['schema']: return lambda: schema
                return actual(name)
            with patch.dict(registry.ADAPTORS, {'fixtureplugin': admitted}), patch.object(registry, 'PLUGIN_FAULTS', []), \
                    patch.object(registry, '_EXCLUDED', {}), patch.object(registry, 'binding', side_effect=binding), \
                    patch.object(registry, 'declarations', return_value=declarations), warnings.catch_warnings():
                warnings.simplefilter('ignore', registry.AdaptorPluginWarning)
                policy.for_route('fixtureplugin', route)
                policy.for_route('fixtureplugin', route)
                data['bad'] = float('nan')
                with self.assertRaises(SchemaxisError) as caught: policy.for_route('fixtureplugin', route)
                self.assertEqual('INVALID_REFERENCE_POLICY', caught.exception.fault.code)
                self.assertIn('fixtureplugin', registry.ADAPTORS)
                self.assertEqual([], registry.PLUGIN_FAULTS)
                data.pop('bad')
                broken[0] = True
                with self.assertRaises(SchemaxisError): policy.for_route('fixtureplugin', route)
                self.assertNotIn('fixtureplugin', registry.ADAPTORS)
                self.assertTrue(registry.PLUGIN_FAULTS)
