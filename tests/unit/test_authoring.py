"""Shared source/property/command semantics, recovery and execution fencing."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from schemaxis import authoring
from schemaxis.console_session import AdaptorConsoleSession
from schemaxis.console_server import ConsoleApplication
from schemaxis.core.faults import SchemaxisError
from schemaxis.execution_service import ExecutionService
from schemaxis.agent_transport import dispatch
from schemaxis.adaptors import registry

BOX = {'version': 'schemaxis.freecad/1', 'nodes': [
    {'id': 'body', 'filter': 'box', 'options': {'length': 20, 'width': 10, 'height': 5}}], 'output': 'body'}


class AuthoringTests(unittest.TestCase):
    def setUp(self):
        config = patch('schemaxis.configuration.load', return_value={'version': 1, 'locations': {}})
        config.start()
        self.addCleanup(config.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.session = AdaptorConsoleSession(self.root/'console', 'freecad')
        self.addCleanup(self.session.close)
        self.edit(json.dumps(BOX, indent=2)+'\n')

    def edit(self, source):
        return self.session.edit_source(source, self.session.active_document, self.session._record['revision'])

    def fault(self, code, function):
        with self.assertRaises(SchemaxisError) as caught: function()
        self.assertEqual(caught.exception.fault.code, code)
        return caught.exception.fault

    def test_invalid_source_survives_reopen_and_blocks_all_execution(self):
        draft = self.edit('{\n "version": ')
        self.assertFalse(draft['valid'])
        self.assertEqual(draft['diagnostics'][0]['line'], 2)
        for operation in (self.session.preview, lambda: self.session.document,
                          lambda: self.session.save(self.root/'valid.json'),
                          lambda: self.session.execute('set body height 9')):
            self.fault('INVALID_DRAFT', operation)
        self.session.close()
        with AdaptorConsoleSession(self.root/'console', 'freecad') as recovered:
            self.assertEqual(recovered.draft()['source'], draft['source'])
            self.assertFalse(recovered.status()['draftValid'])
            recovered.undo()
            self.assertEqual(recovered.document, BOX)
            recovered.redo()
            self.assertFalse(recovered.draft()['valid'])

    def test_semantic_invalid_duplicate_nonfinite_and_nonobject_are_recoverable(self):
        for source in ('[]', '{"version":1,"version":2}', '{"version":NaN}',
                       json.dumps({**BOX, 'nodes': [{'id': 'body', 'filter': 'not-declared'}]})):
            with self.subTest(source=source):
                self.assertFalse(self.edit(source)['valid'])
                self.session.close()
                self.session = AdaptorConsoleSession(self.root/'console', 'freecad')
                self.addCleanup(self.session.close)
                self.assertFalse(self.session.draft()['valid'])
                self.session.undo()
                self.assertEqual(self.session.document, BOX)

    def test_atomic_group_and_stale_client_do_not_partially_edit(self):
        draft = self.session.draft()
        edits = [{'op': 'replace', 'path': '/nodes/0/options/width', 'value': 12},
                 {'op': 'replace', 'path': '/nodes/0/options/height', 'value': 7}]
        result = self.session.patch(edits, draft['document'], draft['revision'])
        self.assertEqual(result['undoCount'], draft['undoCount']+1)
        self.fault('STALE_REVISION', lambda: self.session.patch(edits, draft['document'], draft['revision']))
        self.session.undo()
        self.assertEqual(self.session.document, BOX)
        before = self.session.draft()
        self.fault('INVALID_POINTER', lambda: self.session.patch(edits+[
            {'op': 'remove', 'path': '/absent'}], before['document'], before['revision']))
        self.assertEqual(self.session.draft(), before)

    def test_expression_is_preserved_in_sibling_property_edit(self):
        # Test actual planner-supported expression syntax using repository input.
        example = Path(__file__).resolve().parents[2]/'examples/demos/pipe.input.json'
        self.session.open(example)
        original = self.session.document
        draft = self.session.draft()
        edited = self.session.patch([{'op': 'add', 'path': '/linearDeflection', 'value': .08}], draft['document'], draft['revision'])
        self.assertTrue(edited['valid'])
        expected = copy.deepcopy(original)
        expected['linearDeflection'] = .08
        self.assertEqual(self.session.document, expected)
        self.session.undo()
        self.assertEqual(self.session.document, original)

    def test_file_conflict_and_invalid_source_save(self):
        path = self.root/'source.json'
        path.write_text(json.dumps(BOX))
        self.session.open(path)
        invalid = self.edit('{unfinished')
        self.session.write_source(invalid['document'], invalid['revision'])
        self.assertEqual(path.read_text(), '{unfinished')
        path.write_text('external change')
        self.fault('FILE_CONFLICT', lambda: self.session.write_source(invalid['document'], invalid['revision']))
        self.assertEqual(path.read_text(), 'external change')
        destination = self.root/'recovered.json'
        self.session.write_source(invalid['document'], invalid['revision'], destination)
        self.assertEqual(destination.read_text(), '{unfinished')
        self.session.undo()
        self.assertEqual(self.session.document, BOX)
        self.fault('FILE_CONFLICT', lambda: self.session.write_source(self.session.active_document, self.session._record['revision'], path))

    def test_unopened_destination_is_never_overwritten(self):
        destination = self.root/'exists.json'
        destination.write_text('other work')
        self.fault('OUTPUT_EXISTS', lambda: self.session.write_source(self.session.active_document, self.session._record['revision'], destination))
        self.assertEqual(destination.read_text(), 'other work')

    def test_open_invalid_file_and_exact_source_roundtrip(self):
        path = self.root/'broken.json'
        path.write_text('  {\n"bad":\n')
        self.session.open(path)
        self.assertEqual(self.session.draft()['source'], path.read_text())
        self.assertFalse(self.session.draft()['valid'])
        self.session.undo()
        source = ' \n'+json.dumps(BOX, ensure_ascii=False)+'  \n'
        self.edit(source)
        new = self.root/'exact.json'
        self.session.write_source(self.session.active_document, self.session._record['revision'], new)
        self.assertEqual(new.read_text(), source)

    def test_console_form_and_agent_have_identical_document_and_plan(self):
        self.session.execute('set body height 9')
        expected = self.session.document
        with ExecutionService(self.root/'agent') as service:
            draft = service.create_draft('freecad')
            draft = service.edit_draft(draft['document'], draft['revision'], json.dumps(BOX))
            draft = service.patch_draft(draft['document'], draft['revision'], [
                {'op': 'replace', 'path': '/nodes/0/options/height', 'value': 9}])
            task = service.create_task('Shared edits', ['freecad'])
            planned = service.plan_draft(task['id'], task['revision'], draft['document'], draft['revision'])
            self.assertEqual(service.authoring.document, expected)
            observed = service.observe(plan_id=planned['id'], section='plan', max_bytes=65536)
            self.assertEqual(observed['value'], registry.plan(expected))
            draft = service.undo_draft(draft['document'], draft['revision'])
            draft = service.draft_command(draft['document'], draft['revision'], 'set body height 9')
            self.assertEqual(service.authoring.document, expected)
            app = ConsoleApplication(service.authoring)
            try:
                app.author({'action': 'patch', 'document': draft['document'], 'revision': draft['revision'],
                            'edits': [{'op': 'replace', 'path': '/nodes/0/options/height', 'value': 8}]})
                self.assertEqual(service.authoring.document['nodes'][0]['options']['height'], 8)
            finally: app.close()

    def test_current_draft_required_before_execution_and_after_undo(self):
        with ExecutionService(self.root/'agent') as service:
            draft = service.create_draft('freecad')
            draft = service.edit_draft(draft['document'], draft['revision'], json.dumps(BOX))
            task = service.create_task('Bounded', ['freecad'])
            plan = service.plan_draft(task['id'], 0, draft['document'], draft['revision'])
            invalid = service.edit_draft(draft['document'], draft['revision'], '{')
            with patch('schemaxis.execution_service.registry.run') as run:
                self.fault('STALE_REVISION', lambda: service.execute(plan['id'], plan['revision']))
                self.fault('INVALID_DRAFT', lambda: service.plan_draft(task['id'], plan['revision'], invalid['document'], invalid['revision']))
                restored = service.undo_draft(invalid['document'], invalid['revision'])
                self.fault('STALE_REVISION', lambda: service.execute(plan['id'], plan['revision']))
                run.assert_not_called()
            fresh = service.plan_draft(task['id'], plan['revision'], restored['document'], restored['revision'])
            self.assertEqual(fresh['draft']['revision'], restored['revision'])
            self.assertEqual(service.task(task['id'])['attempts'], 0)

    def test_agent_and_console_reopen_same_authoring_state_and_lock(self):
        with ExecutionService(self.root/'agent') as service:
            draft = service.create_draft('freecad', 'Shared')
            draft = service.edit_draft(draft['document'], draft['revision'], json.dumps(BOX))
            self.fault('WORKSPACE_LOCKED', lambda: AdaptorConsoleSession(self.root/'agent'/'authoring'))
        with AdaptorConsoleSession(self.root/'agent'/'authoring') as console:
            self.assertEqual(console.active_document, draft['document'])
            console.execute('set body height 12')
        with ExecutionService(self.root/'agent') as recovered:
            self.fault('STALE_REVISION', lambda: recovered.draft(draft['document'], draft['revision']))
            entries = recovered.list_drafts()['value']
            current = next(d for d in entries if d['document'] == draft['document'])
            self.assertEqual(json.loads(recovered.draft(current['document'], current['revision'])['source'])['nodes'][0]['options']['height'], 12)

    def test_agent_commands_cannot_bypass_execution_budget(self):
        with ExecutionService(self.root/'agent') as service:
            draft = service.create_draft('freecad')
            for line in ('preview', 'live /tmp/program', 'configure freecad /tmp/program', 'open /tmp/data'):
                self.fault('UNSUPPORTED_COMMAND', lambda: service.draft_command(draft['document'], draft['revision'], line))
            reply = dispatch(service, {'id': 1, 'method': 'edit_draft', 'params': {
                'document_id': draft['document'], 'expected_revision': draft['revision'], 'source': '{'}})
            self.assertFalse(reply['valid'])

    def test_source_location_roundtrip_with_escaped_keys_and_unicode(self):
        source = '{"a/b": {"~value": ["é", 4]}, "other": true}'
        located = authoring.locate(source, '/a~1b/~0value/0')
        self.assertEqual(source[located['start']:located['end']], '"é"')
        reverse = authoring.locate(source, offset=located['start']+1)
        self.assertEqual(reverse, located)
        self.assertEqual(authoring.locate(source, '')['value'], json.loads(source))
        draft = self.session.draft()
        location = self.session.locate_source(draft['document'], draft['revision'], '/nodes/0/options/height')
        self.assertEqual(location['value'], 5)
        self.session.execute('set body height 8')
        self.fault('STALE_REVISION', lambda: self.session.locate_source(draft['document'], draft['revision'], '/nodes'))

    def test_patch_pointer_and_test_boundaries(self):
        value = {'a/b': [1, 2], '~key': 3}
        result = authoring.patch(value, [{'op': 'test', 'path': '/~0key', 'value': 3},
            {'op': 'add', 'path': '/a~1b/-', 'value': 4}, {'op': 'remove', 'path': '/a~1b/0'}])
        self.assertEqual(result, {'a/b': [2, 4], '~key': 3})
        self.assertEqual(value['a/b'], [1, 2])
        self.fault('PATCH_TEST_FAILED', lambda: authoring.patch(value, [{'op': 'test', 'path': '/~0key', 'value': True}]))
        for pointer in ('/a~1b/01', '/a~1b/-1', '/a~1b/99', '/a~2b', 'missing'):
            self.fault('INVALID_POINTER', lambda: authoring.patch(value, [{'op': 'replace', 'path': pointer, 'value': 9}]))

    def test_source_pagination_and_size_limit(self):
        source = self.session.draft()['source']
        parts = [self.session.draft(offset=i, length=7)['source'] for i in range(0, len(source), 7)]
        self.assertEqual(''.join(parts), source)
        before = self.session.draft()
        self.fault('INVALID_SOURCE', lambda: self.edit(' '*(1024*1024+1)))
        self.assertEqual(self.session.draft(), before)

    def test_failed_persistence_does_not_publish_draft_or_history(self):
        before = self.session.draft()
        with patch('schemaxis.console_session.atomic', side_effect=OSError('full disk')):
            with self.assertRaises(OSError): self.edit('{')
        self.assertEqual(self.session.draft(), before)

    def test_busy_console_rejects_edit_without_waiting_for_native_lock(self):
        app = ConsoleApplication(self.session)
        self.addCleanup(app.close)
        app.busy = True
        draft = self.session.draft()
        self.fault('SESSION_BUSY', lambda: app.author({'action': 'source', 'document': draft['document'],
            'revision': draft['revision'], 'source': '{'}))
        self.assertEqual(self.session.draft(), draft)

    def test_browser_command_revision_guard_rejects_stale_client(self):
        app = ConsoleApplication(self.session)
        self.addCleanup(app.close)
        draft = self.session.draft()
        self.session.execute('set body height 8')
        job = app.command('set body height 99', draft['document'], draft['revision'])
        app.job_owner.futures[job['job']].result(timeout=2)
        self.assertEqual(app.jobs[job['job']]['fault']['code'], 'STALE_REVISION')
        self.assertEqual(self.session.document['nodes'][0]['options']['height'], 8)

    def test_http_authoring_uses_current_revision_and_existing_access_controls(self):
        from schemaxis.console_server import ConsoleHTTPServer
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        import threading
        app = ConsoleApplication(self.session)
        server = ConsoleHTTPServer(app)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            draft = self.session.draft()
            body = json.dumps({'action': 'source', 'document': draft['document'],
                               'revision': draft['revision'], 'source': '{'}).encode()
            url = server.origin+'/api/authoring'
            with self.assertRaises(HTTPError): urlopen(Request(url, data=body), timeout=3)
            request = Request(url, data=body, headers={'X-Schemaxis-Token': server.token})
            with urlopen(request, timeout=3) as response:
                result = json.load(response)
            self.assertFalse(result['valid'])
            with self.assertRaises(HTTPError) as caught: urlopen(request, timeout=3)
            self.assertEqual(json.load(caught.exception)['fault']['code'], 'STALE_REVISION')
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=3)
            app.close()
