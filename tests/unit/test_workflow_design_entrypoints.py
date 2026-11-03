# Copyright (C) 2026 David L F Gaden
"""The diagram, agent and source editor share one durable authoring contract."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from schemaxis.agent_transport import dispatch
from schemaxis.console_server import ConsoleApplication
from schemaxis.console_session import AdaptorConsoleSession
from schemaxis.core.faults import SchemaxisError
from schemaxis.execution_service import ExecutionService
from schemaxis.workflow_authoring import example, graph


BACK_EDGE = {'id': 'feedback', 'source': 'scaled', 'target': 'samples',
             'targetPointer': '/nodes/0/options/stop', 'kind': 'value',
             'artifactIndex': 0, 'valuePath': '/rows/0/0'}
CONFIG = {'algorithm': 'constant-relaxation', 'maxIterations': 25,
          'absoluteTolerance': 1e-6, 'relativeTolerance': 1e-4, 'relaxation': .5}


class WorkflowDesignEntrypointTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def fault(self, code, action):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code)

    def session(self):
        session = AdaptorConsoleSession(self.root/'console', 'workflow')
        self.addCleanup(session.close)
        session._edit(example())
        return session

    @staticmethod
    def identity(session):
        return {'document': session.active_document, 'revision': session._record['revision']}

    def test_browser_commands_preserve_original_and_share_undo_and_recovery(self):
        session = self.session()
        app = ConsoleApplication(session)
        self.addCleanup(app.close)
        original = self.identity(session)
        app.author({'action': 'workflow_design_create', **original})
        self.assertNotEqual(session.active_document, original['document'])
        self.assertEqual(session._state['documents'][original['document']]['document'], example())
        design_id = session.active_document
        before = self.identity(session)
        app.author({'action': 'workflow_connect', **before, 'connection': BACK_EDGE})
        projection = app.author({'action': 'workflow_graph', **self.identity(session)})['value']
        self.assertEqual(len(projection['loops']), 1)
        loop_id = projection['loops'][0]['id']
        self.fault('STALE_REVISION', lambda: app.author(
            {'action': 'workflow_disconnect', **before, 'connectionId': 'feedback'}))
        app.author({'action': 'workflow_feedback', **self.identity(session), 'loopId': loop_id, 'config': CONFIG})
        configured = session.document
        self.assertEqual(configured['controllers'][loop_id], CONFIG)
        self.assertEqual([op['id'] for op in session.list_features()], ['samples', 'scaled'])
        self.assertEqual(session.inspect('samples'), example()['operations'][0])
        selected = app.author({'action': 'workflow_reference', **self.identity(session), 'operation': 'samples'})
        self.assertFalse(selected['replayable'])
        self.assertEqual(selected['payload']['pointer'], '/workflow/operations/0')
        app.author({'action': 'workflow_disconnect', **self.identity(session), 'connectionId': 'feedback'})
        self.assertEqual(session.document['controllers'], {})
        self.assertEqual(graph(session, session.active_document, session._record['revision'])['loops'], [])
        app.author({'action': 'undo', **self.identity(session)})
        self.assertEqual(session.document, configured)
        saved = self.root/'design.json'
        app.author({'action': 'write', **self.identity(session), 'filename': str(saved)})
        self.assertEqual(json.loads(saved.read_text()), configured)
        app.close()
        session.close()
        recovered = AdaptorConsoleSession(self.root/'console', 'workflow-design')
        self.addCleanup(recovered.close)
        self.assertEqual(recovered.active_document, design_id)
        self.assertEqual(recovered.document, configured)
        recovered.undo()
        self.assertEqual(recovered.document['controllers'], {})

    def test_compile_creates_separate_ordinary_draft_and_cycles_are_blocked_atomically(self):
        session = self.session()
        app = ConsoleApplication(session)
        self.addCleanup(app.close)
        app.author({'action': 'workflow_design_create', **self.identity(session)})
        design_id = session.active_document
        app.author({'action': 'workflow_compile', **self.identity(session)})
        self.assertEqual(session.document, example())
        self.assertEqual(session.provider, 'workflow')
        self.assertNotEqual(session.active_document, design_id)
        session.activate(design_id)
        app.author({'action': 'workflow_connect', **self.identity(session), 'connection': BACK_EDGE})
        state = copy.deepcopy(session._state)
        self.fault('FEEDBACK_EXECUTION_UNAVAILABLE', lambda: app.author(
            {'action': 'workflow_compile', **self.identity(session)}))
        self.assertEqual(session._state, state)
        app.busy = True
        self.fault('SESSION_BUSY', lambda: app.author(
            {'action': 'workflow_disconnect', **self.identity(session), 'connectionId': 'feedback'}))
        self.assertEqual(session._state, state)

    def test_agent_transport_and_browser_share_projection_and_execution_boundary(self):
        with ExecutionService(self.root/'agent') as service:
            draft = service.create_draft('workflow')
            draft = service.edit_draft(draft['document'], draft['revision'], json.dumps(example()))
            def invoke(method, current=draft, **extra):
                return dispatch(service, {'id': 'design-test', 'method': method, 'params': {
                    'document_id': current['document'], 'expected_revision': current['revision'], **extra}})
            draft = invoke('create_workflow_design')
            design_id = draft['document']
            task = service.create_task('Diagram planning', ['octave'])
            before = copy.deepcopy(service.state)
            self.fault('WORKFLOW_DESIGN_REQUIRES_COMPILATION', lambda: service.plan_draft(
                task['id'], 0, design_id, draft['revision']))
            self.assertEqual(service.state, before)
            draft = invoke('connect_workflow', draft, connection=BACK_EDGE)
            projection = invoke('workflow_graph', draft, max_bytes=65536)['value']
            app = ConsoleApplication(service.authoring)
            try:
                browser_projection = app.author({'action': 'workflow_graph',
                    'document': draft['document'], 'revision': draft['revision']})['value']
                self.assertEqual(projection, browser_projection)
            finally:
                app.close()
            draft = invoke('configure_workflow_feedback', draft,
                           loop_id=projection['loops'][0]['id'], config=CONFIG)
            self.fault('FEEDBACK_EXECUTION_UNAVAILABLE', lambda: service.plan_draft(
                task['id'], 0, design_id, draft['revision']))
            self.assertEqual(service.state, before)
            self.assertEqual(service.state['jobs'], {})
            draft = invoke('disconnect_workflow', draft, connection_id='feedback')
            compiled = invoke('compile_workflow_design', draft)
            self.assertNotEqual(compiled['document'], design_id)
            planned = service.plan_draft(task['id'], 0, compiled['document'], compiled['revision'])
            self.assertEqual(planned['providers'], ['octave'])

    def test_invalid_source_never_reuses_last_valid_loop_graph(self):
        session = self.session()
        app = ConsoleApplication(session)
        self.addCleanup(app.close)
        app.author({'action': 'workflow_design_create', **self.identity(session)})
        app.author({'action': 'workflow_connect', **self.identity(session), 'connection': BACK_EDGE})
        app.author({'action': 'source', **self.identity(session), 'source': '{unfinished'})
        self.fault('INVALID_DRAFT', lambda: app.author({'action': 'workflow_graph', **self.identity(session)}))
        app.author({'action': 'undo', **self.identity(session)})
        self.assertEqual(len(app.author({'action': 'workflow_graph', **self.identity(session)})['value']['loops']), 1)


if __name__ == '__main__':
    unittest.main()
