"""Authenticated HTTP scheduling captures exact saved documents without a worker."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from schemaxis.console_session import AdaptorConsoleSession
from schemaxis.studio_server import StudioApplication, StudioHTTPServer

BOX = {'version': 'schemaxis.freecad/1', 'nodes': [{'id': 'body', 'filter': 'box'}], 'output': 'body'}


class StudioScheduleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.session = AdaptorConsoleSession(self.tmp.name, provider='freecad')
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

    def call(self, path, body, token=True):
        headers = {'Host': '127.0.0.1:'+str(self.server.server_port), 'Content-Type': 'application/json'}
        if token:
            headers['X-Schemaxis-Token'] = self.server.token
        request = Request(self.server.origin+path, data=json.dumps(body).encode(), headers=headers)
        try:
            with urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def test_exact_revision_authorisation_and_controls(self):
        status, document = self.call('/api/documents', {'action': 'new', 'provider': 'freecad', 'document': BOX})
        self.assertEqual(status, 200)
        declaration = {'objective': 'scheduled HTTP qualification',
                       'trigger': {'kind': 'once', 'at': '2099-01-01T00:00:00Z'}}
        captured = {'document': document['id'], 'documentRevision': document['revision'], 'spec': declaration}
        self.assertEqual(self.call('/api/schedules', {'action': 'create', **captured}, token=False)[0], 403)
        status, preview = self.call('/api/schedules', {'action': 'preview', **captured})
        self.assertEqual(status, 200)
        self.assertEqual(preview['upcoming'], ['2099-01-01T00:00:00Z'])
        self.assertEqual(self.call('/api/schedules', {'action': 'list'})[1]['schedules'], [])
        status, record = self.call('/api/schedules', {'action': 'create', **captured})
        self.assertEqual(status, 200)
        self.assertEqual(record['spec']['document'], BOX)
        self.assertEqual(record['spec']['allowedProviders'], ['freecad'])
        status, paused = self.call('/api/schedules', {'action': 'pause', 'id': record['id'], 'revision': 1})
        self.assertEqual((status, paused['status']), (200, 'paused'))
        status, failure = self.call('/api/schedules', {'action': 'resume', 'id': record['id'], 'revision': 1})
        self.assertEqual((status, failure['fault']['code']), (400, 'STALE_REVISION'))
        status, resumed = self.call('/api/schedules', {'action': 'resume', 'id': record['id'], 'revision': 2})
        self.assertEqual((status, resumed['status']), (200, 'active'))
        self.call('/api/documents', {'action': 'rename', 'id': document['id'], 'revision': document['revision'], 'name': 'revised'})
        status, failure = self.call('/api/schedules', {'action': 'create', **captured})
        self.assertEqual((status, failure['fault']['code']), (400, 'STALE_REVISION'))
        state = self.call('/api/schedules', {'action': 'get', 'id': record['id']})[1]
        self.assertEqual(state['occurrences'], [])
        self.assertFalse((Path(self.tmp.name)/'schedules'/'scheduler-owner.lock').exists())
        self.assertFalse((Path(self.tmp.name)/'schedules'/'occurrences').exists())
