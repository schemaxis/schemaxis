"""Shared loopback API transport; the Studio module supplies the visual shell."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import hashlib
from pathlib import Path
import secrets
import threading
from urllib.parse import parse_qs, urlsplit
import uuid

from schemaxis.core.faults import SchemaxisError
from .console_references import ReferenceStore
from .errors import fail
from .jobs import SerialJobs
from .resource_inspection import InspectionStore
from .storage import digest


def copy_presentation(inspection):
    return dict(inspection.state['presentation'])


class ConsoleApplication:
    def __init__(self, session):
        self.session = session
        self.lock = threading.RLock()
        self.job_lock = threading.Lock()
        self.references = ReferenceStore(session.workspace)
        self.inspection = InspectionStore(session.workspace, self.references)
        self.jobs = {}
        self.job_owner = SerialJobs()
        self.cancellations = self.job_owner.cancellations
        self.executor = self.job_owner.executor
        self.busy = False
        self.image_cache = None
        self.image_checkpoint = None

    def identity(self):
        state = self.session.status()
        return state.get('activeDocument'), state.get('revision')

    def state(self):
        with self.lock:
            state = self.session.status()
            document, revision = self.identity()
            return {**state, 'references': self.references.list(document, revision, self.inspection.revisions()),
                    'messages': self.references.data['messages'], 'busy': self.busy,
                    'presentation': copy_presentation(self.inspection),
                    'inspectionRevision': digest(self.inspection.revisions())}

    def command(self, line, document=None, revision=None):
        if not isinstance(line, str) or len(line) > 100000:
            fail('INVALID_COMMAND', 'command must be a string of at most 100000 characters')
        with self.job_lock:
            if self.busy:
                fail('SESSION_BUSY', 'wait for the current native operation to finish')
            self.busy = True
            identity = uuid.uuid4().hex
            self.jobs[identity] = {'status': 'running'}
            self.cancellations[identity] = threading.Event()
        def execute():
            try:
                with self.lock:
                    from .dispatch import allocation
                    with allocation({}, self.cancellations[identity]):
                        if document is not None or revision is not None:
                            self.session._check_revision(document, revision)
                        result = self.session.execute(line)
                    self.jobs[identity] = {'status': 'succeeded', 'result': result}
            except Exception as error:
                with self.job_lock:
                    self.jobs[identity] = {'status': 'failed', 'fault': fault(error)}
            finally:
                with self.job_lock:
                    self.busy = False
        self.job_owner.submit(identity, execute, self.cancellations[identity])
        return {'job': identity, 'status': 'running'}

    def author(self, value):
        """Synchronous host edits share ownership and revisions with commands."""
        with self.job_lock:
            if self.busy:
                fail('SESSION_BUSY', 'wait for the current command before editing')
            with self.lock:
                document, revision = value.get('document'), value.get('revision')
                self.session._check_revision(document, revision)
                action = value.get('action')
                if action in ('workflow_graph', 'workflow_rewire', 'workflow_reference', 'workflow_example',
                              'workflow_design_create', 'workflow_connect', 'workflow_disconnect',
                              'workflow_feedback', 'workflow_compile'):
                    from . import workflow_authoring as workflow
                    if action == 'workflow_graph':
                        return workflow.observe(self.session, document, revision, max_bytes=65536)
                    if action == 'workflow_rewire':
                        return workflow.rewire(self.session, document, revision, value.get('pointer'), value.get('source'), value.get('artifactIndex'))
                    if action == 'workflow_reference':
                        return workflow.reference(self.session, self.references, document, revision, value.get('operation'))
                    if action == 'workflow_design_create':
                        return workflow.create_design(self.session, document, revision)
                    if action == 'workflow_connect':
                        return workflow.edit_design(self.session, document, revision, 'connect', connection=value.get('connection'))
                    if action == 'workflow_disconnect':
                        return workflow.edit_design(self.session, document, revision, 'disconnect', connection_id=value.get('connectionId'))
                    if action == 'workflow_feedback':
                        return workflow.edit_design(self.session, document, revision, 'configure', loop_id=value.get('loopId'), config=value.get('config'))
                    if action == 'workflow_compile':
                        return workflow.compile_design(self.session, document, revision)
                    example = workflow.example()
                    workflow.validate(example)
                    self.session.new('Numerical workflow example', 'workflow')
                    self.session._edit(example)
                    return self.session.draft()
                if action == 'read':
                    return self.session.draft(offset=value.get('offset', 0), length=value.get('length', 4096))
                if action == 'source':
                    return self.session.edit_source(value.get('source'), document, revision, value.get('format'))
                if action == 'patch':
                    return self.session.patch(value.get('edits'), document, revision)
                if action == 'locate':
                    return self.session.locate_source(document, revision, value.get('pointer'), value.get('offset'))
                if action in ('undo', 'redo'):
                    getattr(self.session, action)()
                    return self.session.draft()
                if action == 'write':
                    return self.session.write_source(document, revision, value.get('filename'))
                fail('INVALID_REQUEST', 'choose read, source, patch, locate, undo, redo or write')

    def inspect_evidence(self, request):
        # No native work: serialise snapshot publication and references only.
        from .errors import keys
        keys(request, ('action', 'params'), 'inspection')
        methods = {'workspace': self.inspection.workspace, 'resources': self.inspection.resources,
                   'capture': self.inspection.capture, 'demo': self.inspection.demo,
                   'inspect': self.inspection.inspect, 'reference': self.inspection.reference,
                   'inspect_reference': self.inspection.inspect_reference}
        action, params = request.get('action'), request.get('params', {})
        if not isinstance(action, str) or action not in methods or not isinstance(params, dict):
            fail('INVALID_REQUEST', 'choose a declared inspection action and parameter object')
        with self.lock:
            return methods[action](**params)

    def image_info(self, refresh=False):
        document, revision = self.identity()
        checkpoint = self.session.status().get('lastPreview')
        cached = self.image_cache
        if refresh or cached is None or (cached['document'], cached['revision']) != (document, revision) or self.image_checkpoint != checkpoint:
            path = Path(self.session.image())
            data = path.read_bytes()
            if len(data) < 24 or data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR':
                fail('INVALID_IMAGE', 'native preview is not a PNG image')
            width, height = int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big')
            if not 0 < width <= 32768 or not 0 < height <= 32768:
                fail('INVALID_IMAGE', 'image dimensions exceed the console limit')
            self.image_cache = {'document': document, 'revision': revision,
                'sha256': hashlib.sha256(data).hexdigest(), 'width': width, 'height': height,
                'artifact': str(path), 'units': 'px'}
            self.image_checkpoint = checkpoint
        return dict(self.image_cache)

    def cancel(self, identity):
        if not isinstance(identity, str):
            fail('INVALID_REQUEST', 'job must be a command identity string')
        with self.job_lock:
            if identity not in self.jobs:
                fail('UNKNOWN_JOB', 'there is no command with this job identity')
            if self.jobs[identity]['status'] == 'running':
                self.cancellations[identity].set()
                return {'job': identity, 'status': 'cancellation-requested'}
            return {'job': identity, **self.jobs[identity]}

    def close(self):
        with self.job_lock:
            for event in self.cancellations.values():
                event.set()
        self.job_owner.close()


def fault(error):
    if isinstance(error, SchemaxisError):
        return error.fault.to_dict()
    return {'code': 'CONSOLE_ERROR', 'message': str(error), 'location': 'console'}


class ConsoleHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, application, port=0):
        self.application = application
        self.token = secrets.token_urlsafe(32)
        super().__init__(('127.0.0.1', port), Handler)
        self.origin = 'http://127.0.0.1:' + str(self.server_port)
        self.url = self.origin + '/?token=' + self.token


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # URLs include a local access token. Do not echo them into access logs.
        pass

    def send(self, status, payload, content_type='application/json'):
        if content_type == 'application/json':
            payload = json.dumps(payload, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(payload)

    def authorised(self, parsed):
        host = self.headers.get('Host')
        if host != '127.0.0.1:' + str(self.server.server_port):
            fail('ACCESS_DENIED', 'invalid local server host')
        origin = self.headers.get('Origin')
        if origin and origin != self.server.origin:
            fail('ACCESS_DENIED', 'cross-origin console requests are forbidden')
        token = (self.headers.get('X-Schemaxis-Token')
                 or parse_qs(parsed.query).get('token', [''])[0])
        if not secrets.compare_digest(token, self.server.token):
            fail('ACCESS_DENIED', 'open the console using its local session URL')

    def do_GET(self):
        try:
            parsed = urlsplit(self.path)
            if parsed.path.startswith('/api/'):
                self.authorised(parsed)
                app = self.server.application
                if parsed.path == '/api/state':
                    return self.send(200, app.state())
                if parsed.path.startswith('/api/jobs/'):
                    identity = parsed.path.rsplit('/', 1)[1]
                    # Job snapshots are replaced atomically; never block polling
                    # on the native process holding the session mutation lock.
                    return self.send(200, app.jobs.get(identity, {'status': 'unknown'}))
                with app.lock:
                    if parsed.path == '/api/geometry':
                        return self.send(200, app.session.geometry())
                    if parsed.path == '/api/image':
                        info = app.image_info()
                        expected = parse_qs(parsed.query).get('digest', [info['sha256']])[0]
                        data = Path(info['artifact']).read_bytes()
                        if expected != info['sha256'] or hashlib.sha256(data).hexdigest() != expected:
                            fail('STALE_REFERENCE', 'preview image changed; refresh before picking')
                        return self.send(200, data, 'image/png')
                    if parsed.path == '/api/image-info':
                        return self.send(200, app.image_info())
                return self.send(404, {'fault': {'code': 'NOT_FOUND', 'message': 'unknown endpoint'}})
            # StudioHandler owns packaged assets; the base transport is API-only.
            return self.send(404, {'fault': {'code': 'NOT_FOUND'}})
        except Exception as error:
            self.send(403 if isinstance(error, SchemaxisError) and error.fault.code == 'ACCESS_DENIED' else 400, {'fault': fault(error)})

    def do_POST(self):
        try:
            parsed = urlsplit(self.path)
            self.authorised(parsed)
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 1024 * 1024:
                fail('INVALID_REQUEST', 'request body must be between one byte and one MiB')
            value = json.loads(self.rfile.read(size))
            if not isinstance(value, dict):
                fail('INVALID_REQUEST', 'request body must be an object')
            app = self.server.application
            if parsed.path == '/api/inspection':
                return self.send(200, app.inspect_evidence(value))
            if parsed.path == '/api/authoring':
                return self.send(200, app.author(value))
            if parsed.path == '/api/command':
                return self.send(202, app.command(value.get('line'), value.get('document'), value.get('revision')))
            if parsed.path == '/api/cancel':
                return self.send(200, app.cancel(value.get('job')))
            with app.lock:
                document, revision = app.identity()
                if parsed.path == '/api/reference':
                    geometry = app.session.geometry()
                    return self.send(200, app.references.register(value, document, geometry))
                if parsed.path == '/api/image-reference':
                    info = app.image_info()
                    if hashlib.sha256(Path(info['artifact']).read_bytes()).hexdigest() != info['sha256']:
                        fail('STALE_REFERENCE', 'retained image changed; refresh before picking')
                    return self.send(200, app.references.register_image(value, document, info))
                if parsed.path == '/api/message':
                    if value.get('document') != document or value.get('revision') != revision:
                        fail('STALE_REFERENCE', 'request belongs to a different document or revision; refresh before saving')
                    segments = value.get('segments')
                    selected = {s.get('reference') for s in segments if isinstance(s, dict) and isinstance(s.get('reference'), str)} if isinstance(segments, list) else set()
                    image_refs = [r for r in app.references.data['references'] if r['id'] in selected and r.get('imageDigest')]
                    if any(r['id'] in selected and r.get('coordinateSpace') == 'model' for r in app.references.data['references']):
                        app.session.geometry()  # Detect out-of-band native changes before accepting current intent.
                    app.inspection.check_references(selected)
                    image_digest = app.image_info()['sha256'] if image_refs else None
                    return self.send(200, app.references.message(segments, document, revision, image_digest, app.inspection.revisions()))
            self.send(404, {'fault': {'code': 'NOT_FOUND'}})
        except Exception as error:
            self.send(400, {'fault': fault(error)})


def serve(session, port=0):
    """Keep the historical entry point routed to the current Studio shell."""
    from .studio_server import serve as serve_studio
    return serve_studio(session, port)
