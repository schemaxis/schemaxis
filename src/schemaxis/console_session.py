"""Durable host-only multi-document sessions. Callers serialise session access."""
import copy
from collections import ChainMap
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import uuid
import zipfile
from xml.etree import ElementTree
from .errors import fail
from .storage import encoded, load, digest, atomic, AtomicPublicationError
from . import authoring
from .core.documents import document_format
from .adaptors.registry import ADAPTORS, declarations
from .adaptors import registry

# Framework documents share authoring ownership but are not native adaptors.
CONSOLE_TYPES = ChainMap({'workflow': {
    'version': 'schemaxis.workflow/1', 'adaptor': 'schemaxis.workflow_authoring',
    'consoleTemplate': {'version': 'schemaxis.workflow/1', 'operations': []},
    'documentValidation': 'schemaxis.workflow_authoring:validate',
    'hostOnly': True, 'graphEditing': False, 'collection': 'operations'},
    'workflow-design': {
    'version': 'schemaxis.workflow-design/2', 'adaptor': 'schemaxis.workflow_design',
    # New designs use version 2 (ports); validation also accepts version 1.
    'consoleTemplate': {'version': 'schemaxis.workflow-design/2',
        'workflow': {'version': 'schemaxis.workflow/1', 'operations': []},
        'ports': {}, 'connections': [], 'controllers': {},
        'parameters': {}, 'outputs': {}, 'naming': {}, 'layout': {'nodes': {}}},
    'documentValidation': 'schemaxis.workflow_design:validate',
    'hostOnly': True, 'graphEditing': False, 'collection': 'operations',
    'collectionParent': 'workflow'}}, ADAPTORS)

PROVIDER_VERSIONS = {name: item['version'] for name, item in CONSOLE_TYPES.items()}
COMMANDS = ['new [NAME] [PROVIDER]', 'provider PROVIDER', 'use DOCUMENT_UUID', 'configure PROVIDER LOCATION',
    'connect [LOCATION]', 'live EXECUTABLE_OR_ROOT', 'open FILE', 'add ID FILTER [OPTIONS_JSON] [INPUTS_JSON]',
    'set ID OPTION JSON', 'set document FIELD JSON', 'source JSON_STRING', 'patch EDITS_JSON', 'draft', 'write [FILE]', 'remove ID', 'show ID', 'select ID', 'undo', 'redo',
    'preview [DIRECTORY]', 'geometry', 'image [FILE]', 'save FILE', 'inspect [ID]', 'artifacts',
    'list', 'history', 'status', 'unload', 'disconnect', 'help', 'quit']


def adaptor(provider):
    if not isinstance(provider, str) or provider not in CONSOLE_TYPES:
        fail('UNKNOWN_PROVIDER', 'choose a registered provider', providers=sorted(CONSOLE_TYPES))
    return importlib.import_module(CONSOLE_TYPES[provider]['adaptor'])



class AdaptorConsoleSession:
    def __init__(self, workspace, provider=None, executable=None):
        provider = provider or registry.default_provider(console=True)
        adaptor(provider)
        self.workspace = Path(workspace).absolute()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._lock = (self.workspace / 'session.lock').open('a+b')
        self._closed = False
        self._runtimes = {}
        self._pending_clients = []
        try:
            # POSIX locking is imported here so host-only commands that read
            # CONSOLE_TYPES (discover, describe, plan) do not need fcntl.
            import fcntl
            try: fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: fail('WORKSPACE_LOCKED', 'another session owns this workspace')
            path = self.workspace / 'session.json'
            if path.exists():
                envelope = load(path.read_text())
                if not isinstance(envelope, dict) or envelope.get('version') != 1 or envelope.get('sha256') != digest(envelope.get('state')):
                    fail('RECOVERY_FAILED', 'session checksum or version differs')
                self._state = envelope['state']
                self._validate_state()
                recovered = copy.deepcopy(self._state)
                interrupted = False
                for record in recovered['documents'].values():
                    for attempt in record.get('attempts', []):
                        if attempt['status'] == 'running':
                            attempt.update(status='interrupted', fault={'code': 'INTERRUPTED', 'message': 'owner exited before completing this attempt'})
                            interrupted = True
                if interrupted: self._commit(recovered)
            else:
                self._state = {'documents': {}, 'activeDocument': None, 'nextRevision': 0, 'configurations': {}, 'references': {}}
                self.new('Schemaxis', provider)
            if not executable and not CONSOLE_TYPES[provider].get('hostOnly') and not self._state['configurations'].get(provider):
                from .configuration import executable as configured_executable
                executable = configured_executable(provider)
            if executable: self.configure(provider, executable)
        except Exception:
            self._lock.close()
            self._closed = True
            raise

    def _validate_state(self):
        try:
            state = self._state
            assert state['activeDocument'] in state['documents']
            assert type(state['nextRevision']) is int
            for identity, record in state['documents'].items():
                assert str(uuid.UUID(identity)) == identity
                assert type(record['revision']) is int and 0 < record['revision'] <= state['nextRevision']
                for snapshot in [record] + record['undo'] + record['redo']:
                    if 'source' in snapshot:
                        document, diagnostics = authoring.analyse(snapshot['source'],
                            lambda value: self._validate(value, record['provider']), snapshot.get('sourceFormat', 'json'))
                        assert document == snapshot['document']
                        assert bool(diagnostics) == bool(snapshot.get('diagnostics'))
                    else:
                        self._validate(snapshot['document'], record['provider'])
            assert isinstance(state['configurations'], dict) and isinstance(state['references'], dict)
        except (KeyError, TypeError, ValueError, AssertionError):
            fail('RECOVERY_FAILED', 'session structure is invalid')

    def _commit(self, state):
        if self._closed: fail('SESSION_CLOSED', 'open a new session')
        path = self.workspace / 'session.json'
        payload = encoded({'version': 1, 'state': state, 'sha256': digest(state)})
        try:
            atomic(path, payload)
        except AtomicPublicationError:
            try:
                if path.read_bytes() != payload: raise OSError('published session bytes differ')
            except OSError:
                try: self.close()
                except Exception: pass
            else:
                # Publication committed even though directory durability is
                # uncertain. Never allow the next command to reuse its revision.
                self._state = state
                for identity, runtime in self._runtimes.items():
                    record = state['documents'].get(identity)
                    if not record or runtime.get('resident') != (identity, record['revision'], id(runtime.get('client'))):
                        runtime.update(resident=None, geometry=None, geometryDigest=None)
            raise
        self._state = state

    @property
    def active_document(self): return self._state['activeDocument']
    @property
    def _record(self): return self._state['documents'][self.active_document]
    @property
    def provider(self): return self._record['provider']
    @property
    def document(self):
        if self._record.get('diagnostics'):
            from .unfilled import reject_unfilled
            reject_unfilled(self._record.get('document'))
            fail('INVALID_DRAFT', 'repair or undo the current source before editing properties or executing',
                 revision=self._record['revision'], diagnostics=self._record['diagnostics'])
        return copy.deepcopy(self._record['document'])
    @property
    def nodes(self): return self.document.get('nodes', [])
    @property
    def output(self): return self.document.get('output')
    @property
    def selected(self): return self._record['selected']
    @property
    def connection(self): return copy.deepcopy(self._state['configurations'].get(self.provider))
    @property
    def executable(self): return (self.connection or {}).get('executable')
    @property
    def history(self): return copy.deepcopy(self._record['undo'])
    @property
    def checkpoints(self): return copy.deepcopy(self._record['checkpoints'])
    @property
    def last_preview(self): return (self._checkpoint() or {}).get('directory')
    @property
    def _runtime(self):
        # Runtime records are deliberately excluded from durable authored state.
        return self._runtimes.setdefault(self.active_document, {})

    @property
    def live(self): return self._runtime.get('client')
    @live.setter
    def live(self, client):
        if client is not None:
            if self._closed: fail('SESSION_CLOSED', 'open a new session')
            if any(identity != self.active_document and runtime.get('client') is client
                   for identity, runtime in self._runtimes.items()):
                fail('LIVE_DOCUMENT_MISMATCH', 'a native client cannot belong to two documents')
            if getattr(client, 'provider', self.provider) != self.provider:
                fail('LIVE_PROVIDER_MISMATCH', 'native client provider differs from the active document')
        previous = self.live
        if previous is client: return
        try:
            if previous is not None: previous.close()
        except Exception:
            self._invalidate()
            self._native_fault = {'code': 'NATIVE_CLOSE_FAILED', 'message': 'previous client cleanup failed'}
            raise
        self._runtime['client'] = client
        self._native_fault = None
        self._invalidate()

    @property
    def _live_owner(self):
        return (self.active_document, self.provider) if self.live is not None else None

    @property
    def _resident(self): return self._runtime.get('resident')
    @_resident.setter
    def _resident(self, value): self._runtime['resident'] = value
    @property
    def _geometry(self): return self._runtime.get('geometry')
    @_geometry.setter
    def _geometry(self, value): self._runtime['geometry'] = value
    @property
    def _native_fault(self): return self._runtime.get('fault')
    @_native_fault.setter
    def _native_fault(self, value): self._runtime['fault'] = value

    def _invalidate(self):
        self._resident = None
        self._geometry = None
        self._runtime['geometryDigest'] = None

    def _assembly(self, document=None):
        document = self.document if document is None else document
        return isinstance(document, dict) and any(document.get('version') == v and r.get('graphEditing', True) is False for v, (_, r) in registry.routes().items())

    def _graph_required(self):
        if CONSOLE_TYPES[self.provider].get('graphEditing') is False:
            fail('UNSUPPORTED_COMMAND', 'use source/property edits for workflow operations')
        if self._assembly(): fail('UNSUPPORTED_COMMAND', 'assembly edits use set document FIELD JSON or open')

    @staticmethod
    def _empty(provider):
        return copy.deepcopy(CONSOLE_TYPES[provider].get('consoleTemplate', {'version': CONSOLE_TYPES[provider]['version'], 'nodes': []}))

    def _hook(self, name, provider=None):
        path = CONSOLE_TYPES[provider or self.provider].get('consoleHooks', {}).get(name)
        return registry.binding(path) if path else None

    def _validate(self, document, provider=None, *, draft=True):
        from .unfilled import reject_unfilled
        reject_unfilled(document)
        provider = provider or self.provider
        adaptor(provider)
        encoded(document)
        from .adaptor_runtime import walk
        if not CONSOLE_TYPES[provider].get('hostOnly') and any(any(key in value for key in ('$document', '$expr', '$value', '$analytic')) for _, value in walk(document)):
            owner, _ = registry.resolve(document)
            if owner != provider: fail('UNSUPPORTED_VERSION', 'document must match selected provider')
            return registry.plan(document)
        validation = CONSOLE_TYPES[provider].get('documentValidation')
        if validation: return registry.binding(validation)(document, draft=draft)
        if self._assembly(document):
            owner, _ = registry.resolve(document)
            if owner != provider: fail('UNSUPPORTED_VERSION', 'document must match selected provider')
            return registry.plan(document)
        if not isinstance(document, dict) or document.get('version') != CONSOLE_TYPES[provider]['version']:
            fail('UNSUPPORTED_VERSION', 'document must match the selected provider')
        nodes = document.get('nodes')
        if not isinstance(nodes, list) or any(not isinstance(n, dict) for n in nodes):
            fail('INVALID_DOCUMENT', 'nodes must be an array of objects')
        for index, node in enumerate(nodes):
            for key in ('id', 'filter'):
                if not isinstance(node.get(key), str):
                    fail('INVALID_DOCUMENT', f'node requires a string {key}', f'/nodes/{index}/{key}')
            if not isinstance(node.get('inputs', {}), dict) or not isinstance(node.get('options', {}), dict):
                fail('INVALID_DOCUMENT', 'node options and inputs must be objects', f'/nodes/{index}')
        if document.get('nodes') == []:
            if document != self._empty(provider): fail('INVALID_DOCUMENT', 'empty document must match provider template')
            return {'status': 'empty'}
        hook = self._hook('validate', provider)
        return hook(document, draft=draft) if hook else registry.plan(copy.deepcopy(document))

    def new(self, name='Schemaxis', provider=None):
        provider = provider or (self.provider if self._state['documents'] else registry.default_provider(console=True))
        adaptor(provider)
        if not isinstance(name, str) or not name.strip(): fail('INVALID_DOCUMENT', 'provide a document name')
        state = copy.deepcopy(self._state)
        identity = str(uuid.uuid4())
        state['nextRevision'] += 1
        state['documents'][identity] = {'name': name, 'provider': provider, 'document': self._empty(provider),
            'revision': state['nextRevision'], 'selected': None, 'file': None, 'undo': [], 'redo': [], 'checkpoints': [], 'attempts': []}
        state['activeDocument'] = identity
        self._commit(state)
        self._invalidate()
        return self.status()

    def activate(self, identity):
        if identity not in self._state['documents']: fail('UNKNOWN_DOCUMENT', 'document is not in this workspace')
        state = copy.deepcopy(self._state)
        state['activeDocument'] = identity
        self._commit(state)
        return self.status()

    def switch_provider(self, provider):
        adaptor(provider)
        for identity, record in self._state['documents'].items():
            if record['provider'] == provider: return self.activate(identity)
        return self.new(provider.title(), provider)

    def configure(self, provider, executable):
        adaptor(provider)
        if CONSOLE_TYPES[provider].get('hostOnly'): fail('UNSUPPORTED_COMMAND', 'configure the workflow stage providers individually')
        path = Path(executable)
        if not path.is_absolute() or not path.exists() or (CONSOLE_TYPES[provider].get('locationKind') != 'roots' and (not path.is_file() or not os.access(path, os.X_OK))):
            fail('INTERPRETER_NOT_FOUND', 'provide an absolute executable or adaptor installation root')
        state = copy.deepcopy(self._state)
        # Keep executable symlinks, notably a virtual environment's Python.
        # Installation roots can still use their canonical directory identity.
        location = path.resolve() if CONSOLE_TYPES[provider].get('locationKind') == 'roots' else path
        state['configurations'][provider] = {'provider': provider, 'executable': str(location), 'mode': 'isolated-preview'}
        self._commit(state)
        return copy.deepcopy(state['configurations'][provider])

    def connect(self, executable=None):
        if CONSOLE_TYPES[self.provider].get('hostOnly'): fail('UNSUPPORTED_COMMAND', 'workflow documents have no native connection')
        executable = executable or self.executable or os.environ.get(CONSOLE_TYPES[self.provider].get('environment', ''))
        if not executable: fail('INTERPRETER_NOT_FOUND', 'provide an adaptor location')
        return self.configure(self.provider, executable)

    def start_live(self, executable):
        if CONSOLE_TYPES[self.provider].get('hostOnly'): fail('UNSUPPORTED_LIVE', 'workflow execution uses the shared execution service')
        if self._assembly(): fail('UNSUPPORTED_LIVE', 'assembly documents require configured batch execution')
        module_name = CONSOLE_TYPES[self.provider].get('liveModule', registry.adaptor_package(self.provider) + '.live')
        try: module = importlib.import_module(module_name)
        except ModuleNotFoundError as error:
            if error.name != module_name: raise
            fail('UNSUPPORTED_LIVE', 'this provider has no resident client')
        client = module.LiveSession(executable, self.workspace / ('live-' + str(uuid.uuid4())))
        try:
            self.live = client
        except BaseException:
            try: client.close()
            except Exception: self._pending_clients.append(client)
            raise
        self._invalidate()
        return self.status()

    _snapshot = staticmethod(authoring.snapshot)

    def _check_revision(self, document_id, expected_revision):
        authoring.check(self._record, self.active_document, document_id, expected_revision)

    def _edit(self, document, selected=None, **metadata):
        self._validate(document)
        source = authoring.render(self._record, document)
        if len(source.encode('utf-8')) > authoring.LIMIT:
            fail('INVALID_DOCUMENT', 'edited document exceeds one MiB')
        state = authoring.replace(self._state, self.active_document,
            dict(document=document, selected=selected, source=source, diagnostics=[], **metadata))
        self._commit(state)
        self._invalidate()
        return self.status()

    def draft(self, *, offset=0, length=4096):
        if type(offset) is not int or offset < 0 or type(length) is not int or not 1 <= length <= 16384:
            fail('INVALID_PAGE', 'offset must be nonnegative and length 1..16384 characters')
        source = authoring.text(self._record)
        if offset > len(source): fail('INVALID_PAGE', 'offset exceeds source length')
        chunk = source[offset:offset+length]
        return {'document': self.active_document, 'revision': self._record['revision'],
                'sourceFormat': self._record.get('sourceFormat', 'json'), 'source': chunk, 'offset': offset, 'totalCharacters': len(source),
                'nextOffset': offset+len(chunk) if offset+len(chunk) < len(source) else None,
                'sourceDigest': hashlib.sha256(source.encode('utf-8')).hexdigest(),
                'valid': not bool(self._record.get('diagnostics')),
                'diagnostics': copy.deepcopy(self._record.get('diagnostics', [])),
                'undoCount': len(self._record['undo']), 'redoCount': len(self._record['redo']),
                'file': self._record['file']}

    def locate_source(self, document_id, expected_revision, pointer=None, offset=None):
        self._check_revision(document_id, expected_revision)
        result = authoring.locate(authoring.text(self._record), pointer, offset, self._record.get("sourceFormat", "json"))
        if len(encoded(result)) > 65536:
            fail('OBSERVATION_TOO_LARGE', 'select a smaller source value')
        return {'document': document_id, 'revision': expected_revision, **result}

    def edit_source(self, source, document_id, expected_revision, format=None):
        self._check_revision(document_id, expected_revision)
        format = document_format(format=format or self._record.get("sourceFormat", "json"))
        document, diagnostics = authoring.analyse(source, self._validate, format)
        state = authoring.replace(self._state, self.active_document,
            {'source': source, 'sourceFormat': format, 'document': document, 'diagnostics': diagnostics, 'selected': None})
        self._commit(state)
        self._invalidate()
        return self.draft()

    def patch(self, edits, document_id, expected_revision):
        self._check_revision(document_id, expected_revision)
        self._edit(authoring.patch(self.document, edits), self.selected)
        return self.draft()

    def open(self, filename):
        path = Path(filename).absolute()
        try: payload = path.read_bytes()
        except OSError as error: fail('RESOURCE_NOT_FOUND', str(error), str(path))
        if len(payload) > authoring.LIMIT: fail('INVALID_SOURCE', 'source exceeds one MiB')
        try: source = payload.decode('utf-8')
        except UnicodeDecodeError: fail('INVALID_SOURCE', 'source must be UTF-8')
        format = document_format(path)
        document, diagnostics = authoring.analyse(source, self._validate, format)
        state = authoring.replace(self._state, self.active_document,
            {'source': source, 'sourceFormat': format, 'document': document, 'diagnostics': diagnostics,
             'selected': None, 'name': path.stem, 'file': str(path)})
        state.setdefault('fileBaselines', {})[str(path)] = hashlib.sha256(payload).hexdigest()
        self._commit(state)
        self._invalidate()
        return self.status()

    def write_source(self, document_id, expected_revision, filename=None):
        self._check_revision(document_id, expected_revision)
        filename = filename or self._record['file']
        if not filename: fail('NO_SOURCE_FILE', 'choose a source file destination')
        path = Path(filename).absolute()
        suffix = path.suffix.lower()
        format = self._record.get('sourceFormat', 'json')
        if suffix in ('.json', '.yaml', '.yml') and document_format(path) != format:
            fail('FORMAT_MISMATCH', 'source format is ' + format + '; choose a .' + format
                 + ' destination or explicitly convert the source before saving', str(path))
        payload = authoring.text(self._record).encode('utf-8')
        baseline = self._state.get('fileBaselines', {}).get(str(path))
        if path.is_symlink(): fail('FILE_CONFLICT', 'source destination is a symbolic link', str(path))
        if baseline is not None:
            try: current = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError: current = None
            if current != baseline:
                fail('FILE_CONFLICT', 'source file changed outside this workspace; reopen or choose a new destination', str(path))
        # Reconcile publication uncertainty using the same visible-byte rule as
        # session commits. Source saving does not change the authored revision.
        error = None
        try:
            atomic(path, payload, exclusive=baseline is None)
        except AtomicPublicationError as caught:
            if path.read_bytes() != payload: raise
            error = caught
        state = copy.deepcopy(self._state)
        state['documents'][self.active_document]['file'] = str(path)
        state.setdefault('fileBaselines', {})[str(path)] = hashlib.sha256(payload).hexdigest()
        self._commit(state)
        if error: raise error
        return {'saved': str(path), 'revision': expected_revision, 'valid': not bool(self._record.get('diagnostics')),
                'sha256': hashlib.sha256(payload).hexdigest()}

    def _travel(self, source, target):
        self._commit(authoring.travel(self._state, self.active_document, source))
        self._invalidate()
        return self.status()

    def undo(self): return self._travel('undo', 'redo')
    def redo(self): return self._travel('redo', 'undo')

    def _node(self, identity, document=None):
        authored = self.document if document is None else document
        parent = CONSOLE_TYPES[self.provider].get('collectionParent')
        if parent: authored = authored[parent]
        for node in authored.get(CONSOLE_TYPES[self.provider].get('collection', 'nodes'), authored.get('components', [])):
            if node['id'] == identity: return node
        fail('UNKNOWN_REFERENCE', 'feature is not in the active document', str(identity))

    def add(self, identity, operation, options=None, inputs=None):
        self._graph_required()
        if not isinstance(identity, str) or not isinstance(operation, str):
            fail('INVALID_DOCUMENT', 'node id and filter must be strings')
        document = self.document
        document['nodes'].append({'id': identity, 'filter': operation, 'options': {} if options is None else options, 'inputs': {} if inputs is None else inputs})
        hook = self._hook('add')
        if hook: hook(document, identity, operation, self._renderable(operation))
        elif CONSOLE_TYPES[self.provider].get('consoleOutput'): document['output'] = identity
        self._edit(document, identity)
        return {'created': identity, 'filter': operation, 'revision': self._record['revision']}

    def _renderable(self, operation):
        kinds = declarations(self.provider).get(operation, {}).get('kinds', ['data'])
        return any(kind in ('data', 'mesh', 'solid') for kind in kinds)

    def show(self, identity):
        self._graph_required()
        document = self.document
        node = self._node(identity, document)
        hook = self._hook('show')
        if hook is None: fail('UNSUPPORTED_COMMAND', 'adaptor does not support choosing visible output')
        hook(document, identity, self._renderable(node['filter']))
        return self._edit(document, identity)

    def set(self, identity, option, value):
        document = self.document
        if identity == 'document':
            if option in ('version', 'nodes'): fail('INVALID_COMMAND', 'use node commands or open for structural changes')
            document[option] = value
        else:
            self._graph_required()
            self._node(identity, document).setdefault('options', {})[option] = value
        return self._edit(document, self.selected)

    def remove(self, identity):
        self._graph_required()
        document = self.document
        self._node(identity, document)
        document['nodes'] = [n for n in document['nodes'] if n['id'] != identity]
        if not document['nodes']:
            return self._edit(self._empty(self.provider))
        if CONSOLE_TYPES[self.provider].get('consoleOutput') and document['output'] == identity:
            document['output'] = document['nodes'][-1]['id'] if document['nodes'] else None
        return self._edit(document, None if self.selected == identity else self.selected)

    def select(self, identity):
        self._node(identity)
        state = copy.deepcopy(self._state)
        state['documents'][self.active_document]['selected'] = identity
        self._commit(state)
        return {'selected': identity}

    def _model(self, operation, *args):
        hook = self._hook('model')
        if hook is None: fail('UNSUPPORTED_COMMAND', 'adaptor does not support this modelling shortcut')
        return hook(self, operation, *args)

    @staticmethod
    def _number(value):
        try: number = float(value)
        except (ValueError, TypeError): fail('INVALID_INPUT', 'expected a positive finite dimension')
        if isinstance(value, bool) or not math.isfinite(number) or number <= 0: fail('INVALID_INPUT', 'expected a positive finite dimension')
        return number

    # Compatibility Python methods; modelling semantics belong to the adaptor.
    def create_box(self, identity, *dimensions): return self._model('box', identity, *dimensions)
    def create_rectangle(self, identity, *dimensions): return self._model('rectangle', identity, *dimensions)
    def create_circle(self, identity, *dimensions): return self._model('circle', identity, *dimensions)
    def extrude(self, identity, profile, length): return self._model('extrude', identity, profile, length)

    def _run(self, document, target):
        location = [self.executable] if CONSOLE_TYPES[self.provider].get('locationKind') == 'roots' else self.executable
        return registry.run(document, target, locations={self.provider: location})

    def _live_call(self, command, **kwargs):
        try:
            method = getattr(self.live, command, None)
            if callable(method): return method(*kwargs.values())
            return self.live.request(command, **kwargs)
        except Exception as error:
            self._invalidate()
            code = getattr(getattr(error, 'fault', None), 'code', 'NATIVE_FAILED')
            if code in ('RUNNER_CANCELLED', 'LIVE_TIMEOUT', 'NATIVE_EXIT', 'UNCERTAIN_STATE', 'SESSION_CLOSED', 'NATIVE_DIVERGENCE') or getattr(self.live, '_closed', False):
                owner = self._live_owner
                try: self.live = None
                except Exception: pass
                self._native_fault = {'code': code, 'message': str(error), 'document': owner[0], 'provider': owner[1]}
            raise

    def preview(self, directory=None):
        if CONSOLE_TYPES[self.provider].get('hostOnly'): fail('UNSUPPORTED_COMMAND', 'use plan_draft and execute through the shared service, or CLI plan/run')
        self._validate(self.document, draft=False)
        if not self.nodes and not self._assembly(): fail('INVALID_DOCUMENT', 'add a feature before previewing')
        if self.live is not None and self._assembly(): fail('UNSUPPORTED_LIVE', 'unload live client and use configured batch assembly execution')
        if self.live is not None and self._live_owner != (self.active_document, self.provider):
            fail('LIVE_DOCUMENT_MISMATCH', 'live client belongs to another document; unload or start a new live client')
        attempt = {'id': str(uuid.uuid4()), 'revision': self._record['revision'], 'status': 'running'}
        state = copy.deepcopy(self._state)
        state['documents'][self.active_document].setdefault('attempts', []).append(attempt)
        self._commit(state)
        try:
            result = self._preview(directory)
        except Exception as error:
            self._invalidate()
            state = copy.deepcopy(self._state)
            record = state['documents'][self.active_document]['attempts'][-1]
            record.update(status='failed', fault={'code': getattr(getattr(error, 'fault', None), 'code', 'PREVIEW_FAILED'), 'message': str(error)})
            self._commit(state)
            raise
        state = copy.deepcopy(self._state)
        state['documents'][self.active_document]['attempts'][-1].update(status=result['status'], checkpoint=result['checkpoint'])
        self._commit(state)
        return result

    def _preview(self, directory=None):
        document = self.document
        if not document.get('nodes') and not self._assembly(document): fail('INVALID_DOCUMENT', 'add a feature before previewing')
        planned = self._validate(document, draft=False)
        identity = str(uuid.uuid4())
        target = Path(directory).absolute() if directory else self.workspace / ('checkpoint-' + identity)
        if target.exists() or target.is_symlink(): fail('OUTPUT_EXISTS', 'choose a fresh checkpoint directory')
        self._invalidate()
        native, artifacts, geometry, native_save = False, [], None, None
        if self.live is not None:
            target.mkdir(parents=True)
            applied = self._live_call('apply', document=document)
            geometry = self._live_call('geometry')
            if not isinstance(geometry, dict) or not isinstance(geometry.get('objects'), (list, dict)):
                fail('INVALID_GEOMETRY', 'live client must return an objects collection')
            hook = self._hook('live_save')
            if hook:
                artifacts, native_save = hook(self, target, applied, geometry, document)
            elif CONSOLE_TYPES[self.provider].get('liveSaveName') and 'save' in applied.get('capabilities', []):
                path = target / CONSOLE_TYPES[self.provider]['liveSaveName']
                native_save = self._live_call('save', path=str(path))
                if (not isinstance(native_save, dict) or native_save.get('verified') is not True
                        or native_save.get('file') != str(path)
                        or native_save.get('revision') != geometry.get('revision')
                        or native_save.get('documentDigest') != digest(document)
                        or native_save.get('geometryDigest') != applied.get('geometryDigest')):
                    fail('VERIFICATION_FAILED', 'live save provenance differs from the applied document')
                receipt_path = Path(str(path) + '.receipt.json')
                if native_save.get('receipt') != str(receipt_path) or receipt_path.is_symlink() or not receipt_path.is_file():
                    fail('VERIFICATION_FAILED', 'live save receipt is absent or outside its checkpoint')
                receipt = load(receipt_path.read_text())
                if any(receipt.get(k) != v for k, v in native_save.items()) or receipt.get('document') != document or receipt.get('provider') != self.provider:
                    fail('VERIFICATION_FAILED', 'live save receipt differs from returned evidence')
                artifacts = [{'file': str(path), 'kind': native_save['kind'], 'sha256': native_save['sha256']},
                    {'file': str(receipt_path), 'kind': 'nativeSaveReceipt', 'sha256': hashlib.sha256(receipt_path.read_bytes()).hexdigest()}]
            else:
                # Older or geometry-only live clients cannot publish scenes.
                path = target / 'geometry.json'
                atomic(path, encoded(geometry), True)
                artifacts = [{'file': str(path), 'kind': 'liveGeometry', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}]
            native = True
        elif self.executable:
            result = self._run(document, target)
            if not isinstance(result, dict) or result.get('verified') is not True: fail('VERIFICATION_FAILED', 'adaptor did not verify output')
            receipt_path = target / 'verification.json'
            receipt = load(receipt_path.read_text()) if receipt_path.is_file() else {}
            artifacts = receipt.get('artifacts', [])
            if not artifacts and isinstance(receipt.get('artifact'), dict): artifacts = [receipt['artifact']]
            if not artifacts:
                manifest_path = target / 'artifacts.json'
                manifest = load(manifest_path.read_text()) if manifest_path.is_file() else result.get('sha256', {})
                allowed = getattr(adaptor(self.provider), 'FILES', tuple(manifest))
                artifacts = [{'file': str(target / name), 'sha256': sha} for name, sha in manifest.items() if name in allowed]
            if not artifacts: fail('VERIFICATION_FAILED', 'verified execution supplied no artifact digests')
            native = True
        else: target.mkdir(parents=True)
        atomic(target / 'authored.json', encoded(document))
        from .schema_snapshots import capture_run
        capture_run(target, document)
        if not native: atomic(target / 'plan.json', encoded(planned[-1] if isinstance(planned, tuple) else planned))
        checkpoint = {'id': identity, 'directory': str(target), 'document': self.active_document,
            'revision': self._record['revision'], 'documentDigest': digest(document), 'provider': self.provider, 'native': native, 'artifacts': artifacts}
        checkpoint['verificationScope'] = (native_save or {}).get('verificationScope', 'adaptorVerified' if native else 'planningOnly')
        if native_save is not None: checkpoint['nativeSave'] = native_save
        for artifact in artifacts: self._artifact(artifact, target)
        atomic(target / 'console-receipt.json', encoded(checkpoint), True)
        checkpoint['receiptDigest'] = hashlib.sha256((target / 'console-receipt.json').read_bytes()).hexdigest()
        state = copy.deepcopy(self._state)
        state['documents'][self.active_document]['checkpoints'].append(checkpoint)
        self._commit(state)
        if geometry is not None:
            self._resident = (self.active_document, self._record['revision'], id(self.live))
            self._geometry = {**geometry, 'nativeRevision': geometry.get('revision'), 'revision': self._record['revision'], 'document': self.active_document}
            self._runtime['geometryDigest'] = digest(geometry)
        return {'status': 'succeeded' if native else 'planned', 'preview': str(target), 'native': native, 'checkpoint': identity, 'artifacts': artifacts, 'revision': self._record['revision']}

    @staticmethod
    def _artifact(artifact, directory):
        from .schema_snapshots import verify_run
        verify_run(directory)
        path = Path(artifact.get('file', ''))
        if not path.is_absolute() or not path.resolve().is_relative_to(Path(directory).resolve()) or path.is_symlink() or not path.is_file():
            fail('VERIFICATION_FAILED', 'artifact must be a regular file within its checkpoint')
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != artifact.get('sha256'): fail('VERIFICATION_FAILED', 'artifact digest differs')
        return payload

    def _checkpoint(self):
        for item in reversed(self._record['checkpoints']):
            if item['revision'] == self._record['revision'] and item['documentDigest'] == digest(self.document): return item
        return None

    def artifacts(self): return copy.deepcopy((self._checkpoint() or {}).get('artifacts', []))

    def _verified_checkpoint(self):
        checkpoint = self._checkpoint()
        if not checkpoint or not checkpoint['native']: fail('NO_PREVIEW', 'preview this revision natively first')
        path = Path(checkpoint['directory']) / 'console-receipt.json'
        if not path.is_file() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != checkpoint['receiptDigest']:
            fail('VERIFICATION_FAILED', 'checkpoint receipt digest differs')
        receipt = load(path.read_text())
        if receipt != {k: v for k, v in checkpoint.items() if k != 'receiptDigest'}: fail('VERIFICATION_FAILED', 'checkpoint provenance differs')
        for artifact in checkpoint['artifacts']: self._artifact(artifact, checkpoint['directory'])
        return checkpoint

    def save(self, filename):
        destination = Path(filename).absolute()
        provenance = None
        if destination.suffix.lower() in ('.json', '.schemaxis'):
            self._validate(self.document)
            payload, kind = encoded(self.document), 'authoredDocument'
        else:
            checkpoint = self._verified_checkpoint()
            if CONSOLE_TYPES[self.provider].get('saveError'):
                fail('UNSUPPORTED_SAVE', CONSOLE_TYPES[self.provider]['saveError'], checkpoint['directory'])
            suffix = CONSOLE_TYPES[self.provider].get('nativeExtension')
            if not suffix or destination.suffix.lower() != suffix: fail('UNSUPPORTED_SAVE', 'use the provider native extension')
            candidates = [a for a in checkpoint['artifacts'] if Path(a['file']).suffix.lower() == suffix]
            if not candidates: fail('NO_NATIVE_DOCUMENT', 'this checkpoint has no saved native scene; use a configured batch preview')
            if len(candidates) != 1: fail('AMBIGUOUS_ARTIFACT', 'checkpoint must contain exactly one native scene')
            payload, kind = self._artifact(candidates[0], checkpoint['directory']), 'nativeDocument'
            provenance = copy.deepcopy(checkpoint.get('nativeSave'))
        atomic(destination, payload, True)
        return {'saved': str(destination), 'kind': kind, 'document': self.active_document, 'revision': self._record['revision'], 'sha256': hashlib.sha256(payload).hexdigest(), 'nativeSave': provenance}

    def geometry(self):
        if self._resident != (self.active_document, self._record['revision'], id(self.live)) or self._geometry is None:
            fail('NO_GEOMETRY', 'preview this revision with a live provider first')
        # Ask the worker to run its native-divergence checks before serving the
        # retained geometry. GUI edits must not silently validate references.
        try:
            current = self._live_call('geometry')
            if current.get('revision') != self._geometry['nativeRevision'] or digest(current) != self._runtime['geometryDigest']:
                fail('NATIVE_DIVERGENCE', 'native revision or geometry differs; refresh the preview')
        except Exception:
            self._invalidate()
            raise
        return copy.deepcopy(self._geometry)

    def image(self, filename=None):
        checkpoint = self._checkpoint()
        images = [a for a in (checkpoint or {}).get('artifacts', []) if Path(a['file']).suffix.lower() == '.png']
        if images:
            checkpoint = self._verified_checkpoint()
            preferred = [a for a in images if Path(a['file']).name == 'preview.png']
            candidates = preferred or images
            if len(candidates) != 1: fail('AMBIGUOUS_ARTIFACT', 'checkpoint contains multiple images without a unique preview.png')
            artifact = candidates[0]
            payload = self._artifact(artifact, checkpoint['directory'])
            if not payload.startswith(b'\x89PNG\r\n\x1a\n'): fail('VERIFICATION_FAILED', 'preview artifact is not PNG data')
            if filename is None: return artifact['file']
            destination = Path(filename).absolute()
            if destination.suffix.lower() != '.png': fail('UNSUPPORTED_SAVE', 'image destination must be PNG')
            atomic(destination, payload, True)
            return str(destination)
        self.geometry()
        path = Path(filename).absolute() if filename else self.workspace / ('image-' + str(uuid.uuid4()) + '.png')
        if path.suffix.lower() != '.png': fail('UNSUPPORTED_SAVE', 'image destination must be PNG')
        if path.exists() or path.is_symlink(): fail('OUTPUT_EXISTS', 'choose a fresh image destination')
        path.parent.mkdir(parents=True, exist_ok=True)
        self._live_call('image', path=str(path))
        if not path.is_file() or path.is_symlink() or not path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
            fail('VERIFICATION_FAILED', 'live image did not produce PNG data')
        return str(path)

    def unload(self):
        try: self.live = None
        finally: self._invalidate()
        return {'unloaded': True, 'configured': self.connection is not None, 'resident': False}

    def disconnect(self):
        self.unload()
        state = copy.deepcopy(self._state)
        state['configurations'].pop(self.provider, None)
        self._commit(state)
        return self.status()

    def status(self):
        records = {identity: {k: copy.deepcopy(v) for k, v in record.items() if k not in ('undo', 'redo', 'source')} for identity, record in self._state['documents'].items()}
        connections = [{**copy.deepcopy(config), 'status': 'configured'} for config in self._state['configurations'].values()]
        for identity, record in records.items():
            runtime = self._runtimes.get(identity, {})
            client = runtime.get('client')
            resident = client is not None and runtime.get('resident') == (identity, record['revision'], id(client))
            record.update(resident=resident, nativeState='unavailable' if runtime.get('fault') else ('resident' if resident else 'not resident'),
                          nativeFault=copy.deepcopy(runtime.get('fault')))
            if client is not None:
                connections.append({'provider': record['provider'], 'document': identity, 'mode': 'live',
                                    'status': 'resident' if resident else 'awaiting preview'})
        current = self._record['document'] if isinstance(self._record['document'], dict) else {}
        return {'provider': self.provider, 'document': self._record['name'], 'activeDocument': self.active_document,
            'revision': self._record['revision'], 'documents': records, 'references': copy.deepcopy(self._state['references']),
            'configurations': copy.deepcopy(self._state['configurations']), 'connection': self.connection,
            'connections': connections,
            'configured': self.connection is not None, 'resident': self._resident == (self.active_document, self._record['revision'], id(self.live)),
            'nativeState': 'unavailable' if self._native_fault else ('resident' if self._resident else 'not resident'),
            'nativeFault': copy.deepcopy(self._native_fault),
            'nodes': len(current.get('nodes', [])) if isinstance(current.get('nodes'), list) else 0, 'output': current.get('output'), 'selected': self.selected, 'checkpoints': self.checkpoints,
            'documentVersion': current.get('version'), 'components': len(current.get('components', [])) if isinstance(current.get('components'), list) else 0,
            'draftValid': not bool(self._record.get('diagnostics')), 'diagnostics': copy.deepcopy(self._record.get('diagnostics', [])),
            'artifacts': self.artifacts(),
            'lastPreview': self.last_preview, 'nativeEdits': 'not synchronized'}

    def list_features(self):
        authored = self.document
        parent = CONSOLE_TYPES[self.provider].get('collectionParent')
        if parent: authored = authored[parent]
        entries = authored.get('components', []) if self._assembly() else authored.get(CONSOLE_TYPES[self.provider].get('collection', 'nodes'), [])
        return [{**n, 'selected': n['id'] == self.selected} for n in entries]
    def inspect(self, identity=None): return copy.deepcopy(self._node(identity)) if identity else self.document

    def execute(self, line, *, document_id=None, expected_revision=None):
        if self._closed: fail('SESSION_CLOSED', 'open a new session')
        if document_id is not None or expected_revision is not None:
            self._check_revision(document_id, expected_revision)
        if not isinstance(line, str) or len(line) > 100000: fail('INVALID_COMMAND', 'command must be a bounded string')
        try: parts = shlex.split(line, comments=True)
        except ValueError as error: fail('INVALID_COMMAND', str(error))
        if not parts: return {'status': 'empty'}
        command, args = parts[0].lower(), parts[1:]
        zero = {'draft': self.draft, 'status': self.status, 'list': self.list_features, 'ls': self.list_features, 'undo': self.undo,
            'redo': self.redo, 'unload': self.unload, 'disconnect': self.disconnect, 'geometry': self.geometry,
            'artifacts': self.artifacts, 'history': lambda: self.history, 'help': lambda: {'commands': COMMANDS + CONSOLE_TYPES[self.provider].get('consoleCommands', [])}, '?': lambda: {'commands': COMMANDS + CONSOLE_TYPES[self.provider].get('consoleCommands', [])}}
        one = {'open': self.open, 'save': self.save, 'select': self.select, 'remove': self.remove, 'show': self.show, 'use': self.activate, 'provider': self.switch_provider, 'live': self.start_live}
        optional = {'preview': self.preview, 'connect': self.connect, 'inspect': self.inspect, 'image': self.image}
        if command in zero and not args: return zero[command]()
        if command in one and len(args) == 1: return one[command](*args)
        if command in optional and len(args) <= 1: return optional[command](*args)
        if command == 'source' and len(args) == 1:
            return self.edit_source(load(args[0]), self.active_document, self._record['revision'])
        if command == 'patch' and len(args) == 1:
            return self.patch(load(args[0]), self.active_document, self._record['revision'])
        if command == 'write' and len(args) <= 1:
            return self.write_source(self.active_document, self._record['revision'], *args)
        if command == 'new' and len(args) <= 2: return self.new(*args)
        if command == 'configure' and len(args) == 2: return self.configure(*args)
        if command == 'add' and 2 <= len(args) <= 4: return self.add(*args[:2], *[load(a) for a in args[2:]])
        if command == 'set' and len(args) == 3: return self.set(args[0], args[1], load(args[2]))
        hook = self._hook('command')
        if hook:
            result = hook(self, command, args, line)
            if result is not None: return result
        fail('INVALID_COMMAND', 'use help for exact bounded command syntax', 'console')

    def close(self):
        if not self._closed:
            first_error = None
            try:
                clients = [runtime.get('client') for runtime in self._runtimes.values()] + self._pending_clients
                for client in clients:
                    if client is not None:
                        try: client.close()
                        except Exception as error:
                            if first_error is None: first_error = error
                self._runtimes.clear()
                self._pending_clients.clear()
            finally:
                self._lock.close()
                self._closed = True
            if first_error is not None: raise first_error

    def __enter__(self): return self
    def __exit__(self, *exc): self.close()


class ConsoleSession(AdaptorConsoleSession):
    def __init__(self, workspace, executable=None):
        super().__init__(workspace, registry.default_provider(console=True), executable)
