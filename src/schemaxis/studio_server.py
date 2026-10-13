"""Loopback server for Schemaxis Studio.

Security is inherited from the console server: loopback binding, a per-launch
token, Host and Origin checks, a strict content security policy and a one-MiB
request limit. Studio adds per-document reads, adaptor/schema/capability
discovery and role-scoped settings. Native work still runs one job at a time.
"""
import copy
import hashlib
import json
from pathlib import Path
import signal
import threading
import tempfile
import uuid
from urllib.parse import parse_qs, urlsplit

from . import authoring
from .adaptors import registry
from .console_server import ConsoleApplication, ConsoleHTTPServer, Handler as ConsoleHandler, fault
from .console_session import CONSOLE_TYPES
from .core.faults import SchemaxisError
from .errors import fail, keys
from .studio_settings import SettingsStore
from .studio_documents import document_request
from .studio_files import read_artifact, browse_inputs, choose_input_file
from .studio_cases import StudioCases
from .studio_setup import StudioSetup
from .studio_library import load_library

STATIC_ROOT = Path(__file__).with_name('studio_ui')
STATIC_TYPES = {'.html': 'text/html', '.mjs': 'text/javascript', '.js': 'text/javascript',
                '.css': 'text/css', '.svg': 'image/svg+xml', '.json': 'application/json',
                '.png': 'image/png'}


class StudioApplication(ConsoleApplication):
    def __init__(self, session):
        super().__init__(session)
        self.job_lock = threading.RLock()
        self.settings = SettingsStore(session.workspace)
        self.cases = StudioCases(self)
        self.setup = StudioSetup(self)
        self._schemas = {}
        self._catalogue = None
        self._snapshot = None
        self._snapshot_lock = threading.Lock()
        self.refresh_snapshot()

    # State ---------------------------------------------------------------

    def refresh_snapshot(self):
        """Publish a light, body-free summary. Callers hold the session lock."""
        state = self.session._state
        documents = []
        for identity, record in state['documents'].items():
            document = record['document'] if isinstance(record['document'], dict) else {}
            documents.append({
                'id': identity, 'name': record['name'], 'provider': record['provider'],
                'version': document.get('version'), 'revision': record['revision'],
                'valid': not record.get('diagnostics'), 'file': record.get('file'),
                'undoCount': len(record['undo']), 'redoCount': len(record['redo']),
            })
        configured = sorted(item['provider'] for item in self.setup.read()['applications'] if item['available'])
        with self._snapshot_lock:
            self._snapshot = {'activeDocument': state['activeDocument'], 'revision': state['nextRevision'],
                              'documents': documents, 'configured': configured}

    def light_state(self):
        # Never wait for a native job: return the last published summary instead.
        if self.lock.acquire(blocking=False):
            try:
                self.refresh_snapshot()
            finally:
                self.lock.release()
        with self._snapshot_lock:
            snapshot = copy.deepcopy(self._snapshot)
        with self.job_lock:
            jobs = [{'id': identity, 'status': job['status'], 'label': job.get('label')}
                    for identity, job in list(self.jobs.items())[-20:]]
        return {**snapshot, 'busy': self.busy, 'jobs': jobs, 'workspace': str(self.session.workspace)}

    def focus(self, identity):
        """Make an explicitly named document active. Callers hold the session lock."""
        if identity is None:
            return
        if not isinstance(identity, str) or identity not in self.session._state['documents']:
            fail('UNKNOWN_DOCUMENT', 'document is not in this workspace', 'document')
        if self.session.active_document != identity:
            self.session.activate(identity)
        self.setup.configure_default(self.session.provider)

    def document(self, identity):
        with self.lock:
            records = self.session._state['documents']
            if identity not in records:
                fail('UNKNOWN_DOCUMENT', 'document is not in this workspace', 'id')
            record = records[identity]
            source = authoring.text(record)
            return {'id': identity, 'name': record['name'], 'provider': record['provider'],
                    'revision': record['revision'], 'source': source, 'sourceFormat': record.get('sourceFormat', 'json'),
                    'document': copy.deepcopy(record['document']),
                    'valid': not record.get('diagnostics'),
                    'diagnostics': copy.deepcopy(record.get('diagnostics', [])),
                    'undoCount': len(record['undo']), 'redoCount': len(record['redo']),
                    'file': record.get('file'),
                    'sourceDigest': hashlib.sha256(source.encode('utf-8')).hexdigest()}

    def documents(self, request):
        return document_request(self, request)

    def schedule_request(self, request):
        from .studio_schedules import request as schedule_request
        return schedule_request(self, request)

    def author(self, value):
        if value.get('action') == 'validate_source':
            return self.validate_source({key: value[key] for key in ('provider', 'source', 'format') if key in value})
        # Focusing and editing are one transaction. Another tab cannot change
        # the active document between the revision check and mutation.
        with self.job_lock:
            if self.busy:
                fail('SESSION_BUSY', 'wait for the current native operation to finish')
            with self.lock:
                self.focus(value.get('document'))
                try:
                    return super().author(value)
                finally:
                    self.refresh_snapshot()

    def command(self, line, document=None, revision=None, *, live_preview=False):
        if not isinstance(line, str) or len(line) > 100000:
            fail('INVALID_COMMAND', 'command must be a string of at most 100000 characters')
        with self.job_lock:
            if self.busy:
                fail('SESSION_BUSY', 'wait for the current native operation to finish')
            with self.lock:
                self.focus(document)
                if document is not None or revision is not None:
                    self.session._check_revision(document, revision)
                document, revision = self.identity()
                self.refresh_snapshot()
            identity = uuid.uuid4().hex
            self.busy = True
            self.jobs[identity] = {'status': 'running', 'label': line.split()[0] if line.split() else 'Command'}
            self.cancellations[identity] = threading.Event()

        def execute():
            outcome = {'status': 'failed', 'fault': {'code': 'INTERRUPTED', 'message': 'Native command interrupted'}}
            try:
                with self.lock:
                    from .dispatch import allocation
                    self.focus(document)
                    self.session._check_revision(document, revision)
                    with allocation({}, self.cancellations[identity]):
                        if live_preview:
                            result = self._preview_document()
                        else:
                            result = self.session.execute(line)
                    self.refresh_snapshot()
                outcome = {'status': 'succeeded', 'result': result}
            except Exception as error:
                outcome = {'status': 'failed', 'fault': fault(error)}
            finally:
                with self.job_lock:
                    self.jobs[identity] = {**self.jobs[identity], **outcome}
                    self.busy = False
        try:
            self.job_owner.submit(identity, execute, self.cancellations[identity])
        except Exception:
            with self.job_lock:
                self.busy = False
                self.jobs.pop(identity, None)
                self.cancellations.pop(identity, None)
            raise
        return {'job': identity, 'status': 'running'}

    def _preview_document(self):
        session = self.session
        session._validate(session.document, draft=False)
        capabilities = CONSOLE_TYPES[session.provider].get('consoleCapabilities', {})
        if capabilities.get('liveGeometry') and session.executable and not session._assembly():
            if session.live is None:
                resolve_location = session._hook('live_location')
                session.start_live(resolve_location(session) if resolve_location else session.executable)
        result = session.preview()
        return {**result, 'live': session.live is not None}

    def preview_request(self, request):
        keys(request, ('document', 'revision'), 'preview')
        return self.command('preview', request.get('document'), request.get('revision'), live_preview=True)

    def input_file_request(self, request):
        keys(request, ('path', 'extensions'), 'input-file')
        return choose_input_file(self, request.get('path', ''), request.get('extensions', []))

    def inspect_input_request(self, request):
        keys(request, ('provider', 'input', 'node', 'port', 'prepare'), 'inspect-input')
        provider, document, node = request.get('provider'), request.get('input'), request.get('node')
        port, prepare = request.get('port', 0), request.get('prepare', False)
        if type(port) is not int or port < 0 or type(prepare) is not bool:
            fail('INVALID_REQUEST', 'Choose a valid output port and inspection mode')
        if not isinstance(document, dict) or not isinstance(node, str) or not node:
            fail('INVALID_REQUEST', 'Choose a pipeline input to inspect')
        meta = registry.metadata(provider)
        if document.get('version') not in meta['routes'] or not meta.get('studioInspect'):
            fail('UNSUPPORTED_INSPECTION', 'This adaptor does not provide interactive input choices yet')
        hook = registry.binding(meta['studioInspect'])
        with self.job_lock:
            if self.busy:
                fail('SESSION_BUSY', 'Wait for the current native operation to finish')
            executable = self.setup.location(provider)
            if not self.setup.available(provider, executable):
                fail('NATIVE_UNAVAILABLE', 'Configure this application in Setup before inspecting its input')
            identity = uuid.uuid4().hex
            self.busy = True
            self.jobs[identity] = {'status': 'running', 'label': 'Inspect ' + node}
            self.cancellations[identity] = threading.Event()

        def execute():
            outcome = {'status': 'failed', 'fault': {'code': 'INTERRUPTED', 'message': 'Input inspection interrupted'}}
            try:
                from .dispatch import allocation
                from .pipeline import digest
                with allocation({}, self.cancellations[identity]), tempfile.TemporaryDirectory(prefix='studio-inspect-') as root:
                    result = hook(document, node, executable, Path(root) / 'session', port=port, prepare=prepare)
                outcome = {'status': 'succeeded', 'result': {**result, 'inputDigest': digest(document)}}
            except Exception as error:
                outcome = {'status': 'failed', 'fault': fault(error)}
            finally:
                with self.job_lock:
                    self.jobs[identity] = {**self.jobs[identity], **outcome}
                    self.busy = False
        try:
            self.job_owner.submit(identity, execute, self.cancellations[identity])
        except Exception:
            with self.job_lock:
                self.busy = False
                self.jobs.pop(identity, None)
                self.cancellations.pop(identity, None)
            raise
        return {'job': identity, 'status': 'running'}

    def design(self, request):
        keys(request, ('document', 'revision', 'action', 'params'), 'design')
        from .workflow_authoring import design_action
        params = request.get('params', {})
        if not isinstance(params, dict):
            fail('INVALID_REQUEST', 'params must be an object', 'params')
        with self.job_lock:
            if self.busy:
                fail('SESSION_BUSY', 'wait for the current native operation to finish')
            with self.lock:
                self.focus(request.get('document'))
                try:
                    return design_action(self.session, request.get('document'), request.get('revision'),
                                         request.get('action'), params)
                finally:
                    self.refresh_snapshot()

    def validate_source(self, value):
        keys(value, ('provider', 'source', 'format'), 'validate')
        provider, source = value.get('provider'), value.get('source')
        if provider not in CONSOLE_TYPES:
            fail('UNKNOWN_PROVIDER', 'choose a registered adaptor or workflow type', 'provider')
        if not isinstance(source, str) or len(source.encode('utf-8')) > authoring.LIMIT:
            fail('INVALID_DOCUMENT', 'source must be text of at most one MiB', 'source')
        with self.lock:
            document, diagnostics = authoring.analyse(
                source, lambda candidate: self.session._validate(candidate, provider), value.get('format', 'json'))
        return {'valid': not diagnostics, 'diagnostics': diagnostics}

    # Discovery -----------------------------------------------------------

    def functions(self):
        """Typed, pure function declarations for the expression picker."""
        from .functions import FUNCTIONS
        return {'functions': FUNCTIONS.describe(), 'analytics': ['linear', 'values', 'orbit']}

    def adaptors(self):
        from .capabilities import CapabilityCatalogue
        discovery = CapabilityCatalogue()
        providers = {item['id']: item for item in registry.discover()['providers']}
        result = []
        for name, item in sorted(CONSOLE_TYPES.items()):
            meta = providers.get(name, {})
            studio = _studio_metadata(name)
            result.append({
                'id': name, 'version': item['version'],
                'routes': [item['version'], *meta.get('additionalDocumentVersions', [])],
                'hostOnly': bool(item.get('hostOnly')),
                'emptyDocument': copy.deepcopy(item.get('consoleTemplate',
                                                        {'version': item['version'], 'nodes': []})),
                'scope': meta.get('scope', ''), 'keywords': meta.get('keywords', []),
                'operations': meta.get('operations', []),
                'runtimeFamily': meta.get('runtimeFamily'),
                **({'display': copy.deepcopy(item['display'])} if isinstance(item.get('display'), dict) else {}),
                'console': copy.deepcopy(item.get('consoleCapabilities', {})),
                'execution': meta.get('executionCapabilities', {}),
                'viewers': studio.get('viewers', _default_viewers(item)),
                'templates': [{k: t[k] for k in ('id', 'title', 'description', 'fields') if k in t}
                              for t in studio.get('templates', [])],
                'snippetCount': len(studio.get('snippets', [])),
                'subsets': studio.get('subsets', []),
                **(discovery.application_projection(name) if name in registry.ADAPTORS else {}),
            })
        return {'adaptors': result}

    def studio_adaptor(self, name, version=None):
        if name not in CONSOLE_TYPES:
            fail('UNKNOWN_PROVIDER', 'choose a registered adaptor', 'id')
        studio = _studio_metadata(name)
        kinds = {}
        if name in registry.ADAPTORS and registry.metadata(name).get('declarations'):
            kinds = {key: spec['kinds'] for key, spec in registry.declarations(name).items() if spec.get('kinds')}
        from .studio_catalogue import catalogue
        additions = catalogue(name, version) if name in registry.ADAPTORS else {'items': [], 'definitions': {}}
        if version and name in registry.ADAPTORS and version != registry.metadata(name)['version']:
            studio = {**studio, 'snippets': [], 'templates': [], 'categories': []}
        return {**studio, 'id': name, 'operationKinds': kinds, 'addCatalogue': additions,
                'viewers': studio.get('viewers', _default_viewers(CONSOLE_TYPES[name]))}

    def schema(self, version):
        if not isinstance(version, str):
            fail('INVALID_REQUEST', 'provide a document version', 'version')
        if version not in self._schemas:
            from .schema import export_schema
            try:
                from .studio_guidance import SHARED, enrich_shared, enrich_markers, document_annotator
                if version in SHARED:
                    schema = enrich_shared(version)
                else:
                    from .schema_authoring import version_schema
                    schema = enrich_markers(version_schema(version, authored=True, annotate=document_annotator(version)))
            except SchemaxisError as error:
                fail('UNKNOWN_VERSION', 'no authored schema is registered for this document version', 'version',
                     version=version, cause=error.fault.code)
            self._schemas[version] = json.dumps(schema, allow_nan=False, separators=(',', ':')).encode()
        return self._schemas[version]

    def capabilities(self, request):
        keys(request, ('action', 'query', 'scope', 'id', 'inputKind', 'outputKind', 'limit', 'cursor',
                       'pointer', 'sections'), 'capabilities')
        if self._catalogue is None:
            from .capabilities import CapabilityCatalogue
            self._catalogue = CapabilityCatalogue()
        catalogue, action = self._catalogue, request.get('action')
        page = {key: request[key] for key in ('limit', 'cursor') if key in request}
        if action == 'browse':
            return catalogue.browse(request.get('scope', 'root'), **page)
        if action == 'search':
            return catalogue.search(request.get('query', ''), scope=request.get('scope', 'root'),
                                    input_kind=request.get('inputKind'), output_kind=request.get('outputKind'), **page)
        if action == 'describe':
            return catalogue.describe(request.get('id'), sections=request.get('sections'))
        if action == 'schema':
            return catalogue.schema(request.get('id'), pointer=request.get('pointer', ''), **page)
        fail('INVALID_REQUEST', 'choose browse, search, describe or schema', 'action')

    def settings_request(self, request):
        keys(request, ('action', 'values', 'role'), 'settings')
        if request.get('action') == 'read':
            return self.settings.read()
        if request.get('action') == 'write':
            return self.settings.write(request.get('values'), request.get('role'))
        fail('INVALID_REQUEST', 'choose read or write', 'action')

    def case_request(self, request):
        return self.cases.request(request)

    def setup_request(self, request):
        return self.setup.request(request)


def _adaptor_directory(name):
    return Path(str(registry.adaptor_files(name)))


def _studio_metadata(name):
    return load_library(name)


def _default_viewers(item):
    console = item.get('consoleCapabilities', {})
    viewers = []
    if console.get('liveGeometry') or console.get('geometryReferences'):
        viewers.append('3d')
    if console.get('imagePixelReferences'):
        viewers.append('image')
    return viewers


class StudioHandler(ConsoleHandler):
    def _static(self, parsed):
        relative = 'index.html' if parsed.path in ('/', '') else parsed.path.lstrip('/')
        root = STATIC_ROOT.resolve()
        path = (root / relative).resolve()
        if (root not in path.parents and path != root) or path.suffix not in STATIC_TYPES or not path.is_file():
            return self.send(404, {'fault': {'code': 'NOT_FOUND', 'message': 'unknown resource'}})
        if 'tests' in path.relative_to(root).parts:
            return self.send(404, {'fault': {'code': 'NOT_FOUND', 'message': 'unknown resource'}})
        content_type = STATIC_TYPES[path.suffix]
        if path.suffix == '.json':
            # Static JSON is already encoded; send() encodes application/json objects.
            content_type += '; charset=utf-8'
        return self.send(200, path.read_bytes(), content_type)

    def do_GET(self):
        try:
            parsed = urlsplit(self.path)
            if not parsed.path.startswith('/api/'):
                return self._static(parsed)
            self.authorised(parsed)
            app = self.server.application
            query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
            if parsed.path == '/api/state':
                return self.send(200, app.light_state())
            if parsed.path.startswith('/api/jobs/'):
                return self.send(200, app.cases.snapshot(parsed.path.rsplit('/', 1)[1]))
            if parsed.path == '/api/document':
                return self.send(200, app.document(query.get('id')))
            if parsed.path == '/api/adaptors':
                return self.send(200, app.adaptors())
            if parsed.path == '/api/functions':
                return self.send(200, app.functions())
            if parsed.path == '/api/studio/adaptor':
                return self.send(200, app.studio_adaptor(query.get('id'), query.get('version')))
            if parsed.path == '/api/schema':
                # Pre-encoded and cached; a charset suffix bypasses re-encoding in send().
                return self.send(200, app.schema(query.get('version')), 'application/json; charset=utf-8')
            if parsed.path == '/api/input-files':
                return self.send(200, browse_inputs(app, query.get('directory'), query.get('extensions', '')))
            if parsed.path == '/api/file':
                data, content_type = read_artifact(app, query.get('path'), query.get('sha256'))
                return self.send(200, data, content_type)
            if parsed.path in ('/api/geometry', '/api/image', '/api/image-info'):
                with app.lock:
                    app.focus(query.get('document'))
                    if 'revision' in query:
                        app.session._check_revision(query.get('document'), int(query['revision']))
                    return super().do_GET()
            return super().do_GET()
        except Exception as error:
            denied = isinstance(error, SchemaxisError) and error.fault.code == 'ACCESS_DENIED'
            self.send(403 if denied else 400, {'fault': fault(error)})

    def do_POST(self):
        parsed = urlsplit(self.path)
        routes = {'/api/documents': 'documents', '/api/capabilities': 'capabilities', '/api/schedules': 'schedule_request',
                  '/api/settings': 'settings_request', '/api/validate': 'validate_source',
                  '/api/design': 'design', '/api/cases': 'case_request', '/api/setup': 'setup_request',
                  '/api/preview': 'preview_request', '/api/input-file': 'input_file_request',
                  '/api/inspect-input': 'inspect_input_request'}
        if parsed.path not in routes:
            return super().do_POST()
        try:
            self.authorised(parsed)
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 1024 * 1024:
                fail('INVALID_REQUEST', 'request body must be between one byte and one MiB')
            value = json.loads(self.rfile.read(size))
            if not isinstance(value, dict):
                fail('INVALID_REQUEST', 'request body must be an object')
            return self.send(200, getattr(self.server.application, routes[parsed.path])(value))
        except Exception as error:
            denied = isinstance(error, SchemaxisError) and error.fault.code == 'ACCESS_DENIED'
            self.send(403 if denied else 400, {'fault': fault(error)})


class StudioHTTPServer(ConsoleHTTPServer):
    def __init__(self, application, port=0):
        super().__init__(application, port)
        self.RequestHandlerClass = StudioHandler


def serve(session, port=0):
    application = StudioApplication(session)
    server = StudioHTTPServer(application, port)
    print('Schemaxis Studio: ' + server.url, flush=True)
    previous_term = None
    if threading.current_thread() is threading.main_thread():
        previous_term = signal.getsignal(signal.SIGTERM)

        def terminate(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, terminate)
    try:
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:
        pass
    finally:
        if previous_term is not None:
            signal.signal(signal.SIGTERM, previous_term)
        server.server_close()
        application.close()
    return {'status': 'closed', 'workspace': str(session.workspace)}
