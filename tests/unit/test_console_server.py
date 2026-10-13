import json
import tempfile
import threading
import time
from pathlib import Path
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from schemaxis.console_server import ConsoleApplication, ConsoleHTTPServer


class Session:
    def __init__(self, workspace):
        self.workspace = workspace

    def status(self):
        return {'activeDocument': 'test', 'revision': 1}

    def execute(self, line):
        return {'command': line}


class ServerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.app = ConsoleApplication(Session(directory.name))
        self.server = ConsoleHTTPServer(self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.finish)

    def finish(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.app.close()

    def request(self, endpoint, headers=None, data=None):
        return urlopen(Request(self.server.origin + endpoint, headers=headers or {}, data=data), timeout=3)

    def test_token_required_and_cross_origin_denied(self):
        with self.assertRaises(HTTPError) as caught:
            self.request('/api/state')
        self.assertEqual(caught.exception.code, 403)
        for name in ('X-Schemaxis-Token',):
            with self.subTest(header=name):
                with self.request('/api/state', {name: self.server.token}) as response:
                    self.assertEqual(json.load(response)['revision'], 1)
                with self.assertRaises(HTTPError) as denied:
                    self.request('/api/state', {name: 'incorrect-token'})
                self.assertEqual(denied.exception.code, 403)
        headers = {'X-Schemaxis-Token': self.server.token}
        with self.assertRaises(HTTPError):
            self.request('/api/state', {**headers, 'Origin': 'https://unrelated.example'})

    def test_unknown_and_traversal_paths_not_served(self):
        for endpoint in ('/../console.py', '/references.json', '/api/other'):
            with self.subTest(endpoint=endpoint), self.assertRaises(HTTPError) as caught:
                self.request(endpoint, {'X-Schemaxis-Token': self.server.token})
            self.assertEqual(caught.exception.code, 404)

    def test_command_returns_pollable_job(self):
        headers = {'X-Schemaxis-Token': self.server.token, 'Content-Type': 'application/json'}
        with self.request('/api/command', headers, b'{"line":"status"}') as response:
            job = json.load(response)['job']
        self.app.executor.shutdown(wait=True)
        with self.request('/api/jobs/' + job, headers) as response:
            result = json.load(response)
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['result'], {'command': 'status'})

    def test_running_command_can_be_cancelled_without_session_lock(self):
        from schemaxis.dispatch import cancellation_requested
        from schemaxis.errors import fail
        entered = threading.Event()
        def execute(line):
            entered.set()
            deadline = time.monotonic() + 2
            while not cancellation_requested() and time.monotonic() < deadline:
                time.sleep(.005)
            if cancellation_requested():
                fail('RUNNER_CANCELLED', 'cancelled by user')
            return {'timedOut': True}
        self.app.session.execute = execute
        job = self.app.command('preview')['job']
        self.assertTrue(entered.wait(1))
        headers = {'X-Schemaxis-Token': self.server.token, 'Content-Type': 'application/json'}
        with self.request('/api/cancel', headers, json.dumps({'job': job}).encode()) as response:
            self.assertEqual(json.load(response)['status'], 'cancellation-requested')
        self.app.executor.shutdown(wait=True)
        self.assertEqual(self.app.jobs[job]['fault']['code'], 'RUNNER_CANCELLED')
        self.assertFalse(self.app.busy)

    def test_image_bytes_and_references_are_bound_to_same_digest(self):
        # Header fixture exercises transport identity; native image decoding is
        # the adaptor checkpoint verifier's responsibility.
        png = b'\x89PNG\r\n\x1a\n' + (13).to_bytes(4, 'big') + b'IHDR' + (16).to_bytes(4, 'big') + (32).to_bytes(4, 'big')
        path = Path(self.app.session.workspace) / 'preview.png'
        path.write_bytes(png)
        self.app.session.image = lambda: str(path)
        headers = {'X-Schemaxis-Token': self.server.token, 'Content-Type': 'application/json'}
        with self.request('/api/image-info', headers) as response:
            info = json.load(response)
        self.assertEqual((info['width'], info['height']), (16, 32))
        with self.request('/api/image?digest=' + info['sha256'], headers) as response:
            self.assertEqual(response.read(), png)
        body = json.dumps({'revision': 1, 'imageDigest': info['sha256'], 'pixel': [2, 3]}).encode()
        with self.request('/api/image-reference', headers, body) as response:
            self.assertEqual(json.load(response)['point'], [2, 3])
        path.write_bytes(png + b'changed')
        with self.assertRaises(HTTPError):
            self.request('/api/image-reference', headers, body)

    def test_prose_save_requires_displayed_document_and_revision(self):
        headers = {'X-Schemaxis-Token': self.server.token, 'Content-Type': 'application/json'}
        request = {'segments': [{'text': 'Please adjust the clearance'}], 'document': 'test', 'revision': 1}
        for change in ({'document': 'other'}, {'revision': 0}):
            with self.subTest(change=change), self.assertRaises(HTTPError):
                self.request('/api/message', headers, json.dumps({**request, **change}).encode())
        with self.request('/api/message', headers, json.dumps(request).encode()) as response:
            message = json.load(response)
        self.assertEqual(message['document'], 'test')
        self.assertFalse(message['executed'])

    def test_native_divergence_blocks_saving_model_references(self):
        from schemaxis.errors import fail
        geometry = {'revision': 1, 'objects': [{'id': 'box', 'faces': [{'id': 'Face1',
            'vertices': [[0, 0, 0], [1, 0, 0], [0, 1, 0]], 'triangles': [[0, 1, 2]]}]}]}
        reference = self.app.references.register({'object': 'box', 'subelement': 'Face1', 'revision': 1, 'point': [.2, .2, 0]}, 'test', geometry)
        def divergent():
            fail('NATIVE_DIVERGENCE', 'owned native model was edited')
        self.app.session.geometry = divergent
        body = {'document': 'test', 'revision': 1, 'segments': [{'reference': reference['id']}]}
        with self.assertRaises(HTTPError) as caught:
            self.request('/api/message', {'X-Schemaxis-Token': self.server.token}, json.dumps(body).encode())
        self.assertEqual(json.load(caught.exception)['fault']['code'], 'NATIVE_DIVERGENCE')
        self.assertEqual(self.app.references.data['messages'], [])
