import json
import hashlib
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from schemaxis.adaptors import registry
from schemaxis.console_session import AdaptorConsoleSession
from schemaxis.studio_server import StudioApplication, StudioHTTPServer
from schemaxis.studio_settings import SettingsStore


class StudioServerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.session = AdaptorConsoleSession(directory.name, provider='workflow-design')
        self.addCleanup(self.session.close)
        self.app = StudioApplication(self.session)
        self.server = StudioHTTPServer(self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.finish)

    def finish(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.app.close()

    def call(self, path, body=None, token=True, raw=False):
        headers = {'Host': '127.0.0.1:' + str(self.server.server_port)}
        if token:
            headers['X-Schemaxis-Token'] = self.server.token
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers['Content-Type'] = 'application/json'
        request = Request(self.server.origin + path, data=data, headers=headers)
        try:
            with urlopen(request, timeout=10) as response:
                payload = response.read()
                return response.status, (payload if raw else json.loads(payload)), response.headers
        except HTTPError as error:
            return error.code, json.loads(error.read()), error.headers

    def test_input_browser_is_authenticated_and_lists_marker_paths(self):
        (self.session.workspace / 'case.foam').touch()
        status, body, _ = self.call('/api/input-files?extensions=.foam')
        self.assertEqual(status, 200)
        self.assertIn('case.foam', [entry['name'] for entry in body['entries']])
        status, _, _ = self.call('/api/input-files', token=False)
        self.assertEqual(status, 403)

    def test_native_input_choices_use_jobs_without_changing_the_active_document(self):
        request = {'provider': 'paraview', 'input': {'version': 'schemaxis/1', 'nodes': [
            {'id': 'source', 'filter': 'sphere'}], 'scenes': []}, 'node': 'source', 'port': 1}
        before = json.dumps(self.session.document, sort_keys=True)
        with patch.object(self.app.setup, 'location', return_value='/configured/pvpython'), \
             patch.object(self.app.setup, 'available', return_value=True), \
             patch('schemaxis.adaptors.paraview.studio.inspect_input', return_value={'assemblies': {'Hierarchy': []}}) as inspect:
            status, started, _ = self.call('/api/inspect-input', request)
            self.assertEqual(status, 200)
            self.app.job_owner.futures[started['job']].result(timeout=5)
            outcome = self.app.jobs[started['job']]
            self.assertEqual(outcome['status'], 'succeeded', outcome)
            self.assertEqual(inspect.call_args.kwargs, {'port': 1, 'prepare': False})
            self.assertIn('inputDigest', outcome['result'])
            self.assertEqual(json.dumps(self.session.document, sort_keys=True), before)
            self.assertFalse(self.app.busy)
            status, _, _ = self.call('/api/inspect-input', request, token=False)
            self.assertEqual(status, 403)
            self.assertEqual(inspect.call_count, 1)

    def test_input_dialog_requires_authentication_and_validated_request_fields(self):
        with patch('schemaxis.studio_server.choose_input_file', return_value={'status': 'cancelled'}) as choose:
            self.assertEqual(self.call('/api/input-file', {'path': '', 'extensions': ['.foam']})[1], {'status': 'cancelled'})
            self.assertEqual(self.call('/api/input-file', {}, token=False)[0], 403)
            self.assertNotEqual(self.call('/api/input-file', {'command': 'bad'})[0], 200)
            self.assertEqual(choose.call_count, 1)

    def test_static_files_are_confined_and_typed(self):
        status, body, headers = self.call('/', token=False, raw=True)
        self.assertEqual(status, 200)
        self.assertIn(b'Schemaxis Studio', body)
        self.assertIn("default-src 'self'", headers['Content-Security-Policy'])
        status, _, headers = self.call('/shell/app.mjs', token=False, raw=True)
        self.assertEqual((status, headers['Content-Type']), (200, 'text/javascript'))
        for path in ('/../studio_server.py', '/%2e%2e/studio_server.py', '/tests/harness.mjs', '/missing.mjs'):
            status, body, _ = self.call(path, token=False)
            self.assertEqual(status, 404, path)

    def test_packaged_help_is_available_without_repository_or_native_apps(self):
        status, index, headers = self.call('/help/index.json', token=False)
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'application/json; charset=utf-8')
        operations = [item for item in index['entries'] if item['provider'] == 'paraview' and item['operation']]
        self.assertEqual(len(operations), 645)
        clip = next(item for item in operations if item['title'] == 'pvClip')
        status, page, _ = self.call('/help/' + clip['id'] + '.json', token=False)
        self.assertEqual(status, 200)
        self.assertIn('ClipType', page['body'])
        self.assertIn('Input', page['body'])
        # Contextual Help opens each registered adaptor's own guide, not Studio Home.
        from schemaxis.adaptors import registry
        topics = {item['id']: item for item in index['entries']}
        for provider in registry.ADAPTORS:
            with self.subTest(provider=provider):
                self.assertIn(index['guides'].get(provider), topics)
                self.assertNotEqual(index['guides'][provider], index['home'])

    def test_api_requires_token(self):
        status, body, _ = self.call('/api/state', token=False)
        self.assertEqual((status, body['fault']['code']), (403, 'ACCESS_DENIED'))

    def test_light_state_has_no_document_bodies(self):
        status, state, _ = self.call('/api/state')
        self.assertEqual(status, 200)
        self.assertEqual(len(state['documents']), 1)
        self.assertNotIn('document', state['documents'][0])
        self.assertEqual(state['documents'][0]['provider'], 'workflow-design')

    def test_function_picker_uses_the_live_typed_catalogue(self):
        from schemaxis.functions import FUNCTIONS
        status, result, _ = self.call('/api/functions')
        self.assertEqual(status, 200)
        self.assertEqual(result['functions'], FUNCTIONS.describe())
        self.assertEqual(result['analytics'], ['linear', 'values', 'orbit'])
        self.assertEqual(self.call('/api/functions', token=False)[0], 403)

    def test_documents_new_activate_and_read(self):
        empty = {'version': 'schemaxis.freecad/1', 'nodes': []}
        status, created, _ = self.call('/api/documents', {'action': 'new', 'provider': 'freecad', 'name': 'cad'})
        self.assertEqual(status, 200)
        self.assertEqual((created['name'], created['provider']), ('cad', 'freecad'))
        self.assertEqual(created['document']['version'], empty['version'])
        status, read, _ = self.call('/api/document?id=' + created['id'])
        self.assertEqual(read['source'], created['source'])
        status, body, _ = self.call('/api/documents', {'action': 'new', 'provider': 'nonsense'})
        self.assertEqual((status, body['fault']['code']), (400, 'UNKNOWN_PROVIDER'))
        status, body, _ = self.call('/api/document?id=missing')
        self.assertEqual(body['fault']['code'], 'UNKNOWN_DOCUMENT')

    def test_adaptors_schema_and_capabilities(self):
        status, adaptors, _ = self.call('/api/adaptors')
        names = {item['id'] for item in adaptors['adaptors']}
        self.assertTrue({'paraview', 'freecad', 'workflow', 'workflow-design'} <= names)
        freecad = next(item for item in adaptors['adaptors'] if item['id'] == 'freecad')
        self.assertEqual(freecad['emptyDocument']['version'], 'schemaxis.freecad/1')
        status, library, _ = self.call('/api/studio/adaptor?id=freecad')
        self.assertEqual(status, 200)
        self.assertEqual(library['operationKinds']['box'], registry.declarations('freecad')['box']['kinds'])
        status, schema, _ = self.call('/api/schema?version=schemaxis.freecad/1')
        self.assertEqual(schema['properties']['version']['const'], 'schemaxis.freecad/1')
        for version in ('schemaxis.workflow-design/1', 'schemaxis.workflow-design/2'):
            status, schema, _ = self.call('/api/schema?version=' + version)
            self.assertEqual(status, 200)
            self.assertEqual(schema['properties']['version']['const'], version)
            self.assertEqual(schema['properties']['workflow']['properties']['operations']['minItems'], 0)
        status, body, _ = self.call('/api/schema?version=schemaxis.nothing/1')
        self.assertEqual(body['fault']['code'], 'UNKNOWN_VERSION')
        status, found, _ = self.call('/api/capabilities', {'action': 'search', 'query': 'plane'})
        self.assertIn('operation/blender/plane', [item['id'] for item in found['items']])
        self.assertTrue(all(item['kind'] == 'operation' for item in found['items']))

    def test_design_actions_are_revision_checked(self):
        _, state, _ = self.call('/api/state')
        document = state['documents'][0]
        status, result, _ = self.call('/api/design', {'document': document['id'], 'revision': document['revision'],
                                                      'action': 'project'})
        self.assertEqual(status, 200)
        self.assertEqual(result['projection']['designVersion'], 'schemaxis.workflow-design/2')
        status, body, _ = self.call('/api/design', {'document': document['id'], 'revision': 999,
                                                    'action': 'project'})
        self.assertEqual(body['fault']['code'], 'STALE_REVISION')

    def test_validate_source_reports_without_saving(self):
        status, result, _ = self.call('/api/validate', {'provider': 'freecad', 'source': '{"version": '})
        self.assertFalse(result['valid'])
        self.assertTrue(result['diagnostics'])
        _, state, _ = self.call('/api/state')
        self.assertEqual(len(state['documents']), 1)

    def test_settings_are_role_scoped(self):
        status, settings, _ = self.call('/api/settings', {'action': 'read'})
        self.assertEqual(settings['values']['output.indexWidth'], 6)
        status, body, _ = self.call('/api/settings', {'action': 'write', 'role': 'user',
                                                      'values': {'output.indexWidth': 4}})
        self.assertEqual(body['fault']['code'], 'SETTING_SCOPE')
        status, settings, _ = self.call('/api/settings', {'action': 'write', 'role': 'dev',
                                                          'values': {'output.indexWidth': 4}})
        self.assertEqual(settings['values']['output.indexWidth'], 4)
        self.assertEqual(SettingsStore(self.session.workspace).read()['values']['output.indexWidth'], 4)
        status, body, _ = self.call('/api/settings', {'action': 'write', 'role': 'admin',
                                                      'values': {'output.indexWidth': 99}})
        self.assertEqual(body['fault']['code'], 'INVALID_SETTING')

    def test_document_lifecycle_preserves_drafts_and_checks_revisions(self):
        _, original, _ = self.call('/api/documents', {'action': 'new', 'provider': 'freecad',
                                                     'name': 'Draft', 'source': '{"version":'})
        self.assertFalse(original['valid'])
        status, duplicate, _ = self.call('/api/documents', {'action': 'duplicate', 'id': original['id'],
                                                           'revision': original['revision']})
        self.assertEqual(status, 200)
        self.assertEqual(duplicate['source'], original['source'])
        self.assertNotEqual(duplicate['id'], original['id'])
        self.assertEqual(duplicate['undoCount'], 0)
        _, renamed, _ = self.call('/api/documents', {'action': 'rename', 'id': original['id'],
                                                    'revision': original['revision'], 'name': 'Recovered draft'})
        self.assertEqual(renamed['name'], 'Recovered draft')
        _, stale, _ = self.call('/api/documents', {'action': 'close', 'id': original['id'],
                                                  'revision': original['revision']})
        self.assertEqual(stale['fault']['code'], 'STALE_REVISION')
        _, result, _ = self.call('/api/documents', {'action': 'close', 'id': original['id'],
                                                   'revision': renamed['revision']})
        self.assertEqual(result['closed'], original['id'])
        self.assertEqual(self.session._state['documents'][duplicate['id']]['source'], original['source'])

    def test_invalid_new_document_is_atomic(self):
        before = len(self.session._state['documents'])
        status, result, _ = self.call('/api/documents', {'action': 'new', 'provider': 'freecad',
            'document': {'version': 'wrong', 'nodes': []}})
        self.assertEqual(status, 400)
        self.assertEqual(len(self.session._state['documents']), before)

    def test_edits_and_commands_target_the_named_document(self):
        first = self.app.document(self.session.active_document)
        self.app.documents({'action': 'new', 'provider': 'freecad', 'name': 'Second'})
        result = self.app.author({'action': 'source', 'document': first['id'], 'revision': first['revision'],
                                 'source': first['source']})
        self.assertEqual(result['document'], first['id'])
        self.app.documents({'action': 'new', 'provider': 'freecad', 'name': 'Third'})
        reached = threading.Event()
        with patch.object(self.session, 'execute', side_effect=lambda line: {
                'document': self.session.active_document, 'signal': reached.set()}):
            job = self.app.command('status', first['id'], result['revision'])
            self.assertTrue(reached.wait(5))
            self.app.executor.submit(lambda: None).result(timeout=5)
        self.assertEqual(self.app.jobs[job['job']]['result']['document'], first['id'])
        self.assertFalse(self.app.busy)

    def test_state_is_nonblocking_during_native_job(self):
        locked = threading.Event()
        release = threading.Event()

        def hold():
            with self.app.lock:
                locked.set()
                release.wait(5)
        worker = threading.Thread(target=hold)
        worker.start()
        try:
            self.assertTrue(locked.wait(2))
            state = self.app.light_state()
            self.assertEqual(len(state['documents']), 1)
        finally:
            release.set()
            worker.join(5)

    def test_viewer_files_are_bounded_typed_and_confined(self):
        path = self.session.workspace / 'sample.csv'
        path.write_text('x,y\n1,2\n')
        status, data, headers = self.call('/api/file?path=sample.csv', raw=True)
        self.assertEqual((status, data), (200, b'x,y\n1,2\n'))
        digest = hashlib.sha256(data).hexdigest()
        self.assertEqual(self.call('/api/file?path=sample.csv&sha256=' + digest, raw=True)[0], 200)
        status, error, _ = self.call('/api/file?path=sample.csv&sha256=' + '0' * 64)
        self.assertEqual((status, error['fault']['code']), (400, 'VERIFICATION_FAILED'))
        self.assertEqual(headers['Content-Type'], 'text/plain; charset=utf-8')
        outside = Path(tempfile.gettempdir()) / 'outside-studio.txt'
        link = self.session.workspace / 'escape.txt'
        link.symlink_to(outside)
        for name in ('../outside-studio.txt', 'escape.txt'):
            status, error, _ = self.call('/api/file?path=' + name)
            self.assertEqual((status, error['fault']['code']), (403, 'ACCESS_DENIED'))
        path = self.session.workspace / 'unsafe.html'
        path.write_text('<script>alert(1)</script>')
        status, error, _ = self.call('/api/file?path=unsafe.html')
        self.assertEqual(error['fault']['code'], 'UNSUPPORTED_FILE')

    def test_setup_locations_are_admin_managed_and_reused_on_focus(self):
        import sys
        status, setup, _ = self.call('/api/setup', {'action': 'read'})
        self.assertEqual(status, 200)
        self.assertIn('octave', {app['provider'] for app in setup['applications']})
        status, result, _ = self.call('/api/setup', {'action': 'configure', 'provider': 'octave',
            'location': sys.executable, 'role': 'dev'})
        self.assertEqual(result['fault']['code'], 'SETTING_SCOPE')
        status, result, _ = self.call('/api/setup', {'action': 'configure', 'provider': 'octave',
            'location': sys.executable, 'role': 'admin'})
        self.assertEqual(status, 200)
        self.assertTrue(next(app for app in result['applications'] if app['provider'] == 'octave')['available'])
        self.app.setup.defaults['freecad'] = sys.executable
        _, record, _ = self.call('/api/documents', {'action': 'new', 'provider': 'freecad'})
        self.app.focus(record['id'])
        self.assertEqual(self.session.executable, str(Path(sys.executable).absolute()))

    def test_live_preview_validates_before_native_start(self):
        import sys
        _, record, _ = self.call('/api/documents', {'action': 'new', 'provider': 'freecad',
            'document': {'version': 'schemaxis.freecad/1', 'nodes': [
                {'id': 'box', 'filter': 'box', 'options': {}}], 'output': 'box'}})
        self.session.configure('freecad', sys.executable)
        with patch.object(self.session, 'start_live') as start, patch.object(self.session, 'preview') as preview:
            preview.return_value = {'status': 'succeeded', 'native': True, 'artifacts': []}
            _, started, _ = self.call('/api/preview', {'document': record['id'], 'revision': record['revision']})
            self.app.job_owner.futures[started['job']].result(timeout=5)
            start.assert_called_once_with(str(Path(sys.executable).absolute()))
            preview.assert_called_once()
        self.app.author({'document': record['id'], 'revision': record['revision'], 'action': 'source', 'source': '{'})
        latest = self.app.document(record['id'])
        with patch.object(self.session, 'start_live') as start:
            _, started, _ = self.call('/api/preview', {'document': record['id'], 'revision': latest['revision']})
            self.app.job_owner.futures[started['job']].result(timeout=5)
            start.assert_not_called()
            self.assertEqual(self.app.jobs[started['job']]['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
