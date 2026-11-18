# Copyright (C) 2026 David L. F. Gaden.
"""Durable identity publication and graph ownership with counted native stand-ins."""
import copy
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.core.faults import SchemaxisError
from schemaxis.identity_transition import proof
from schemaxis.live_runtime import GraphWorker
from schemaxis.storage import digest
from test_live_identity import Backend


def document():
    return {'version': 'schemaxis/1', 'nodes': [
        {'id': 'mesh', 'filter': 'readPLY', 'options': {'files': ['a.ply']}},
        {'id': 'skin', 'filter': 'shrink', 'inputs': {'input': 'mesh'}, 'options': {'factor': 0.5}}],
        'scenes': [{'id': 'main', 'visible': {'skin': {}}, 'geometry': ['skin']}]}


class Graph(GraphWorker):
    provider = 'paraview'

    def __init__(self):
        super().__init__()
        self.native = Backend()
        self.resets = 0
        self.bad_geometry = 0

    def backend(self): return self.native
    def reset_native(self): self.resets += 1
    def present(self, prepared): pass
    def object_ids(self):
        return [{'id': key, 'handle': handle['id'], 'label': self.native.labels[id(handle)]}
                for key, handle in self.active.handles.items()]

    def geometry(self):
        if self.bad_geometry:
            self.bad_geometry -= 1
            raise RuntimeError('injected geometry readback failure')
        return [{'id': key + '/block/1', 'node': key, 'label': self.native.labels[id(self.active.handles[key])],
                 'block': 1, 'faces': [{'id': 0, 'vertices': [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                                      'triangles': [[0, 1, 2]]}], 'edges': []} for key in self.prepared[3]]

    def request(self, command, **args): return self.dispatch(command, args)


def expected(worker):
    status = worker.status()
    return {key: status[key] for key in ('documentDigest', 'revision', 'geometryDigest')}


class GraphIdentity(unittest.TestCase):
    def setUp(self):
        self.graph = Graph()
        self.before = document()
        self.graph.apply(self.before)
        self.proof = proof(self.before, '/nodes/0/id', 'globe')

    def tearDown(self): self.graph.close()

    def transition(self, reverse=False):
        return self.graph.dispatch('graph-reidentify', {'expected': expected(self.graph),
            'proofs': [{'proof': self.proof, 'reverse': reverse}]})

    def test_prepare_and_roundtrip_preserve_handles_and_calls(self):
        handles = dict(self.graph.active.handles)
        calls = list(self.graph.native.calls)
        args = {'expected': expected(self.graph), 'proofs': [{'proof': self.proof, 'reverse': False}]}
        self.graph.dispatch('graph-prepare-identity', args)
        self.assertEqual(calls, self.graph.native.calls)
        self.assertEqual(self.before, self.graph.document)
        for reverse in (False, True, False): self.transition(reverse)
        self.assertIs(handles['mesh'], self.graph.active.handles['globe'])
        self.assertIs(handles['skin'], self.graph.active.handles['skin'])
        self.assertEqual(1, self.graph.native.reads[handles['mesh']['id']])
        self.assertEqual(calls, [call for call in self.graph.native.calls if call[0] != 'relabel'])
        self.assertEqual(1, self.graph.resets)

    def test_expression_option_inverse_restores_authored_spelling_without_reapply(self):
        self.before['nodes'][1]['options']['factor'] = {'$expr': 'extents(mesh).deltaX * 0.5'}
        self.graph.apply(self.before)
        self.proof = proof(self.before, '/nodes/0/id', 'globe')
        calls = list(self.graph.native.calls)
        self.assertIn('extents(mesh)', str(self.graph.active.master.document['nodes'][1]['options']))
        self.transition()
        self.transition(True)
        self.assertEqual(self.before, self.graph.document)
        self.assertIn('extents(`mesh`)', str(self.graph.active.master.document['nodes'][1]['options']))
        self.transition()
        self.assertEqual(calls, [call for call in self.graph.native.calls if call[0] != 'relabel'])

    def test_derived_composite_projection(self):
        self.proof = proof(self.before, '/nodes/1/id', 'surface')
        before = copy.deepcopy(self.graph.geometry_objects)
        self.transition()
        after = self.graph.geometry_objects
        self.assertEqual('surface/block/1', after[0]['id'])
        self.assertEqual(before[0]['faces'], after[0]['faces'])
        self.assertEqual(before[0]['edges'], after[0]['edges'])
        self.transition(True)
        self.assertEqual(before, self.graph.geometry_objects)

    def test_readback_failure_reverses_without_rebuild(self):
        handles = dict(self.graph.active.handles)
        token = expected(self.graph)
        self.graph.bad_geometry = 1
        with self.assertRaises(SchemaxisError) as raised: self.transition()
        self.assertEqual('IDENTITY_TRANSITION_FAILED', raised.exception.fault.code)
        self.assertEqual(token, expected(self.graph))
        self.assertIs(handles['mesh'], self.graph.active.handles['mesh'])
        self.assertFalse(self.graph.uncertain)
        self.assertEqual(1, self.graph.resets)
        self.transition()

    def test_readback_and_reverse_failure_preserves_uncertain_handles(self):
        handle = self.graph.active.handles['mesh']
        self.graph.bad_geometry = 1
        self.graph.native.fail_pairs.add(('globe', 'mesh'))
        with self.assertRaises(SchemaxisError) as raised: self.transition()
        self.assertEqual('IDENTITY_TRANSITION_UNCERTAIN', raised.exception.fault.code)
        self.assertTrue(self.graph.uncertain)
        self.assertIs(handle, self.graph.active.handles['globe'])
        self.assertEqual(1, self.graph.resets)

    def test_forged_scene_and_stale_revision_refuse_without_native_calls(self):
        calls = list(self.graph.native.calls)
        forged = copy.deepcopy(self.proof)
        forged['after']['scenes'][0]['visible'] = {'globe': {}}
        for args in ({'expected': expected(self.graph), 'proofs': [{'proof': forged, 'reverse': False}]},
                     {'expected': {**expected(self.graph), 'revision': -1},
                      'proofs': [{'proof': self.proof, 'reverse': False}]}):
            with self.assertRaises(SchemaxisError): self.graph.dispatch('graph-reidentify', args)
        self.assertEqual(calls, self.graph.native.calls)



class GraphClient:
    provider = 'paraview'
    def __init__(self, worker): self.worker = worker
    def request(self, command, **args): return self.worker.dispatch(command, args)
    def close(self): self.worker.close()


class DurableIdentity(unittest.TestCase):
    def setUp(self):
        from schemaxis.console_session import AdaptorConsoleSession
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.session = AdaptorConsoleSession(self.temp.name, 'paraview')
        self.addCleanup(lambda: self.session.close())
        self.session._edit(document(), 'mesh')
        self.graph = Graph()
        self.session.live = GraphClient(self.graph)
        self.graph.apply(document())

    def rename(self, name='globe'):
        s = self.session
        return s.rename('/nodes/0/id', name, s.active_document, s._record['revision'])

    def test_publication_then_lazy_alignment_and_exact_history(self):
        s = self.session
        calls = list(self.graph.native.calls)
        original = s._snapshot(s._record)
        self.rename()
        self.assertEqual(calls, self.graph.native.calls)
        self.assertEqual('globe', s.selected)
        self.assertFalse(s.status()['resident'])
        s.geometry()
        handle = self.graph.active.handles['globe']
        s.undo()
        self.assertEqual(original, s._snapshot(s._record))
        s.geometry()
        self.assertIs(handle, self.graph.active.handles['mesh'])
        s.redo()
        s.geometry()
        self.assertIs(handle, self.graph.active.handles['globe'])
        self.assertEqual(1, self.graph.native.reads[handle['id']])

    def test_unpublished_failure_consumes_no_views_or_native_calls(self):
        s = self.session
        state, calls = copy.deepcopy(s._state), list(self.graph.native.calls)
        with patch('schemaxis.console_session.atomic', side_effect=OSError('before publication')):
            with self.assertRaises(OSError): self.rename()
        self.assertEqual(state, s._state)
        self.assertEqual({}, s.live_data.views)
        self.assertNotIn('pendingIdentity', s._runtime)
        self.assertEqual(calls, self.graph.native.calls)

    def test_visible_uncertain_publication_installs_once_and_can_align(self):
        from schemaxis.storage import atomic, AtomicPublicationError
        s = self.session
        revision, undo = s._record['revision'], len(s.history)
        def published(path, payload, *args):
            atomic(path, payload, *args)
            raise AtomicPublicationError(path, OSError('directory fsync'))
        with patch('schemaxis.console_session.atomic', side_effect=published):
            with self.assertRaises(AtomicPublicationError): self.rename()
        self.assertEqual(revision + 1, s._record['revision'])
        self.assertEqual(undo + 1, len(s.history))
        self.assertEqual(0, len(s.live_data.edges))
        self.assertEqual('globe', s.document['nodes'][0]['id'])
        s.geometry()
        s.undo()
        s.geometry()
        self.assertEqual(0, len(s.live_data.edges))

    def test_pending_chain_survives_ordinary_edit_undo_without_preview(self):
        s = self.session
        handle = self.graph.active.handles['mesh']
        self.rename()
        s.patch([{'op': 'replace', 'path': '/nodes/1/options/factor', 'value': 0.6}],
                s.active_document, s._record['revision'])
        self.assertNotIn('pendingIdentity', s._runtime)
        s.undo()  # Restore the exact witnessed snapshot, not merely equal settings.
        s.undo()  # Undo the rename although native state has not aligned yet.
        s.geometry()
        self.assertIs(handle, self.graph.active.handles['mesh'])
        s.redo()
        s.geometry()
        self.assertIs(handle, self.graph.active.handles['globe'])
        self.assertEqual(1, self.graph.native.reads[handle['id']])

    def test_geometry_transport_retry_does_not_repeat_committed_native_rename(self):
        s = self.session
        self.rename()
        request = s.live.request
        broken = [True]
        def once(command, **args):
            if command == 'geometry' and broken[0]:
                broken[0] = False
                raise OSError('injected response loss')
            return request(command, **args)
        with patch.object(s.live, 'request', side_effect=once):
            with self.assertRaises(SchemaxisError) as caught: s.geometry()
            self.assertEqual('NATIVE_TRANSPORT_FAILED', caught.exception.fault.code)
            self.assertTrue(s._runtime['pendingIdentity']['aligned'])
            s.geometry()
        self.assertEqual(1, self.graph.native.count('relabel'))
        self.assertEqual(1, self.graph.resets)

    def test_yaml_and_expression_source_restore_exactly(self):
        from schemaxis.core.yaml_documents import dump
        s = self.session
        value = document()
        value['nodes'][1]['options']['factor'] = {'$expr': 'extents(mesh).deltaX * 0.5'}
        try:
            source = '# retained human comment\n' + dump(value)
            s.edit_source(source, s.active_document, s._record['revision'], 'yaml')
        except SchemaxisError as error:
            if error.fault.code == 'YAML_UNAVAILABLE': self.skipTest('YAML extra unavailable')
            raise
        self.graph.apply(value)
        self.rename()
        s.geometry()
        self.assertEqual('yaml', s._record['sourceFormat'])
        s.undo()
        self.assertEqual(source, s._record['source'])
        self.assertEqual(value, s.document)
        s.geometry()
        s.redo()
        s.geometry()
        self.assertEqual(1, self.graph.native.reads[self.graph.active.handles['globe']['id']])

    def test_aligned_rename_then_ordinary_edit_undo_keeps_exact_native_owner(self):
        s = self.session
        self.rename()
        s.geometry()
        handle = self.graph.active.handles['globe']
        s.patch([{'op': 'replace', 'path': '/nodes/1/options/factor', 'value': 0.6}],
                s.active_document, s._record['revision'])
        s.undo()
        s.undo()
        s.geometry()
        self.assertIs(handle, self.graph.active.handles['mesh'])
        s.redo()
        s.geometry()
        self.assertIs(handle, self.graph.active.handles['globe'])
        self.assertEqual(1, self.graph.native.reads[handle['id']])

    def test_stale_native_plan_refuses_before_publication(self):
        s = self.session
        other = document()
        other['nodes'][1]['options']['factor'] = 0.7
        self.graph.apply(other)
        state, calls = copy.deepcopy(s._state), list(self.graph.native.calls)
        with self.assertRaises(SchemaxisError) as caught: self.rename()
        self.assertEqual('STALE_IDENTITY_TRANSITION', caught.exception.fault.code)
        self.assertEqual(state, s._state)
        self.assertEqual(calls, self.graph.native.calls)
        self.assertEqual({}, s.live_data.views)

    def test_client_replacement_discards_old_pending_ownership(self):
        s = self.session
        self.rename()
        replacement = Graph()
        s.live = GraphClient(replacement)
        self.assertNotIn('pendingIdentity', s._runtime)
        self.assertFalse(s.status()['resident'])
        with self.assertRaises(SchemaxisError) as caught: s.geometry()
        self.assertEqual('NO_GEOMETRY', caught.exception.fault.code)
        self.assertIsNone(replacement.active)

    def test_preview_stale_and_collision_leave_state_untouched(self):
        s = self.session
        before, calls = copy.deepcopy(s._state), list(self.graph.native.calls)
        for _ in range(2): s.execute('rename-preview /nodes/0/id globe')
        with self.assertRaises(SchemaxisError): s.rename('/nodes/0/id', 'globe', s.active_document, -1)
        with self.assertRaises(SchemaxisError): self.rename('skin')
        self.assertEqual(before, s._state)
        self.assertEqual(calls, self.graph.native.calls)
        self.assertEqual({}, s.live_data.views)

    def test_published_native_refusal_stays_pending_without_fallback(self):
        s = self.session
        self.rename()
        self.graph.native.fail_pairs.add(('mesh', 'globe'))
        with self.assertRaises(SchemaxisError): s.geometry()
        self.assertEqual('globe', s.document['nodes'][0]['id'])
        self.assertIn('pendingIdentity', s._runtime)
        self.assertFalse(s.status()['resident'])
        self.assertEqual(1, self.graph.resets)
        self.graph.native.fail_pairs.clear()
        s.geometry()
        self.assertEqual(1, self.graph.resets)

class BothResidentDomains(unittest.TestCase):
    setUp = DurableIdentity.setUp
    rename = DurableIdentity.rename

    def prepare_data(self):
        from test_live_identity import Process
        Process.instances = []
        self.session.live_data.factory = Process
        discovery = patch('schemaxis.adaptors.paraview.mvp.runners.require_paraview', return_value='/test/pvpython')
        discovery.start()
        self.addCleanup(discovery.stop)
        self.session.execute('data load skin')
        return Process

    def request(self, value=None, *, bare=False):
        s = self.session
        result = {'input': value or s.document, 'sessionDocument': s.active_document}
        if not bare and s._runtime.get('identityViews', {}).get(None):
            result['view'] = s._runtime['identityViews'][None]
        return result

    def test_both_domains_and_old_bare_window_keep_independent_handles(self):
        Process = self.prepare_data()
        s = self.session
        old = copy.deepcopy(s.document)
        data_handle = Process.instances[0].worker.active.handles['mesh']
        graph_handle = self.graph.active.handles['mesh']
        self.rename()
        for _ in range(2):
            s.geometry()
            s.execute('data refresh')
            self.assertEqual(data_handle['id'], s.live_data.inspect(self.request(), 'globe')['handle'])
            self.assertEqual(data_handle['id'], s.live_data.inspect(self.request(old, bare=True), 'mesh')['handle'])
            s.undo()
            s.geometry()
            s.execute('data refresh')
            self.assertEqual(data_handle['id'], s.live_data.inspect(self.request(), 'mesh')['handle'])
            s.redo()
        self.assertEqual(1, len(Process.instances))
        self.assertEqual(1, Process.instances[0].backend.reads[data_handle['id']])
        self.assertEqual(1, self.graph.native.reads[graph_handle['id']])
        self.assertEqual(1, self.graph.resets)

    def test_recovered_reverse_adopts_new_bare_B_as_root_and_keeps_old_window(self):
        from schemaxis.console_session import AdaptorConsoleSession
        from test_live_identity import Process
        s = self.session
        self.rename()
        s.close()
        self.session = s = AdaptorConsoleSession(self.temp.name, 'paraview')
        self.assertIsNone(s.live)
        self.assertFalse(s.status()['resident'])
        Process = self.prepare_data()
        old_B = copy.deepcopy(s.document)
        handle = Process.instances[0].worker.active.handles['globe']
        s.undo()
        for _ in range(2):
            self.assertEqual(handle['id'], s.live_data.inspect(self.request(), 'mesh')['handle'])
            self.assertEqual(handle['id'], s.live_data.inspect(self.request(old_B, bare=True), 'globe')['handle'])
            s.redo()
            self.assertEqual(handle['id'], s.live_data.inspect(self.request(), 'globe')['handle'])
            s.undo()
        self.assertEqual(1, len(Process.instances))
        self.assertEqual(1, Process.instances[0].backend.reads[handle['id']])

    def test_new_old_name_is_a_different_reader_in_the_console_view(self):
        Process = self.prepare_data()
        s = self.session
        original = Process.instances[0].worker.active.handles['mesh']
        self.rename()
        s.geometry()
        s.execute('data refresh')
        s.patch([{'op': 'add', 'path': '/nodes/-', 'value': {
            'id': 'mesh', 'filter': 'readPLY', 'options': {'files': ['b.ply']}}}],
            s.active_document, s._record['revision'])
        s.execute('data load mesh')
        loaded = s.live_data.inspect(self.request(), 'mesh')
        renamed = s.live_data.inspect(self.request(), 'globe')
        owners = [(process, handle) for process in Process.instances
                  for key, handle in process.worker.active.handles.items() if key == 'mesh']
        self.assertTrue(owners)
        self.assertTrue(all(handle is not original for _, handle in owners))
        self.assertEqual(original['id'], renamed['handle'])
        self.assertEqual(1, Process.instances[0].backend.reads[original['id']])

    def test_unsupported_data_owner_refuses_publication_even_with_graph_support(self):
        Process = self.prepare_data()
        s = self.session
        state, calls = copy.deepcopy(s._state), list(self.graph.native.calls)
        with patch('schemaxis.live_data.registry_relabel', return_value=None):
            with self.assertRaises(SchemaxisError): self.rename()
        self.assertEqual(state, s._state)
        self.assertEqual(calls, self.graph.native.calls)
        self.assertEqual(0, Process.instances[0].backend.count('relabel'))
        self.assertEqual({}, s.live_data.views)


class EmbeddedHistory(unittest.TestCase):
    def test_incomplete_draft_keeps_unrelated_semantic_diagnostic(self):
        import json
        from schemaxis.console_session import AdaptorConsoleSession
        value = {'version': 'schemaxis/1', 'nodes': [
            {'id': 'mesh', 'filter': 'readPLY', 'options': {}}], 'scenes': []}
        with tempfile.TemporaryDirectory() as directory, AdaptorConsoleSession(directory, 'paraview') as session:
            session.edit_source(json.dumps(value), session.active_document, session._record['revision'])
            self.assertEqual('MISSING_ARGUMENT', session._record['diagnostics'][0]['code'])
            session.execute('rename /nodes/0/id globe')
            self.assertEqual('globe', session._record['document']['nodes'][0]['id'])
            self.assertEqual('MISSING_ARGUMENT', session._record['diagnostics'][0]['code'])
            self.assertEqual({}, session.live_data.workers)
            session.undo()
            self.assertEqual(value, session._record['document'])

    def test_workflow_and_both_design_versions_keep_full_scope_and_envelope(self):
        from schemaxis.console_session import AdaptorConsoleSession
        from schemaxis.spatial_actions import Draft
        from schemaxis import workflow_design
        body = {'version': 'schemaxis.workflow/1', 'settings': {'keep': 3},
                'definitions': {'size': {'$expr': '2 * 3'}},
                'operations': [{'id': 'mesh', 'document': document()},
                               {'id': 'peer', 'document': document()}]}
        cases = [(body, 'workflow', '')]
        cases.append(({'version': 'schemaxis.workflow-design/1', 'workflow': body,
                       'connections': [], 'controllers': {}}, 'workflow-design', '/workflow'))
        cases.append((workflow_design.create(body), 'workflow-design', '/workflow'))
        for value, provider, base in cases:
            with self.subTest(provider=provider, version=value['version']), tempfile.TemporaryDirectory() as directory:
                with AdaptorConsoleSession(directory, provider) as session:
                    session._edit(value, 'mesh')
                    before = copy.deepcopy(session.document)
                    selected = Draft({'input': before, 'operation': 'mesh'})
                    self.assertEqual(base + '/operations/0/document', selected.selected.base)
                    self.assertEqual(digest(before), selected.digest)
                    session.execute('rename ' + base + '/operations/0/document/nodes/0/id globe --operation mesh')
                    current = session.document['workflow'] if base else session.document
                    self.assertEqual('globe', current['operations'][0]['document']['nodes'][0]['id'])
                    self.assertEqual(body['operations'][1], current['operations'][1])
                    self.assertEqual(body['definitions'], current['definitions'])
                    self.assertEqual('mesh', session.selected)
                    session.execute('data list --operation mesh')
                    session.undo()
                    self.assertEqual(before, session.document)
                    session.redo()
                    session.execute('data list --operation mesh')


if __name__ == '__main__': unittest.main()
