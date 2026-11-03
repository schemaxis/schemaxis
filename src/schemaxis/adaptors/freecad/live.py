# Copyright (C) 2026 David L F Gaden
"""Bounded, synchronous client for a dedicated persistent FreeCAD GUI.

LiveSession(executable, directory) requires a fresh directory and a working GUI
display. request('apply', document=...) accepts schemaxis.freecad/1 declarations,
including profile outputs for wire previews. Pure document references/functions
are resolved before native validation; file imports are excluded. Full
declarations replace the previous tree; retained IDs reuse
native objects (changing an ID's feature type is rejected). Dimensions are mm.

geometry returns an objects array with output faces, local triangle indices, world coordinates,
and revision-scoped FaceN IDs, plus EdgeN polylines and VertexN points. Native
topology names are NOT stable across edits. Selection uses declared object IDs.
Edges use 33 samples per edge; they are previews, not tolerance-certified curves.
Limits: 100 nodes, 100 points per polygon, 16 MiB IPC, 10000 faces, 20000 edges,
40000 topological vertices, 200000 combined face mesh vertices and triangles.
save and image require fresh absolute .FCStd/.png paths. Images are 960x720.
No arbitrary Python, property reflection, external document opening, arbitrary sketch constraints,
STEP imports, or concurrent GUI editing is supported. This is a single-client
local IPC boundary, not a sandbox against other processes running as this user.
Timeouts kill the owned process group; in-flight edits then have unknown outcome
and the session cannot be reused. Tessellation limits cap transferred output,
not OCC's transient memory. Save/image are not document transactions.
Successful edits discard native undo history; failures abort the current
transaction. Divergence checks cover declared settings, membership, expressions,
shape and placement, not GUI styling or selection. GUI edits are not reverse-synced.
The worker checks its owning host every 0.5 seconds while the GUI event loop is
responsive and exits when that host dies. Blocking native operations delay this
watchdog; it is not a hard realtime limit on OCC execution.
"""
import copy
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
import uuid

from schemaxis.core.faults import SchemaxisError, Fault
from schemaxis.artifacts import atomic_json, runtime_archive
from .adaptor import plan

MAX_BYTES = 16 * 1024 * 1024
COMMANDS = {'status': (), 'apply': ('document',), 'geometry': (),
            'save': ('path',), 'image': ('path',),
            'select': ('object', 'subelement'), 'shutdown': ()}


def owner_record():
    pid = os.getpid()
    record = {'pid': pid}
    try:
        record['startTime'] = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        pass
    return record


def owner_alive(owner):
    """Check one recorded owner; Linux start time protects against PID reuse."""
    pid = owner.get('pid')
    if type(pid) is not int or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    if 'startTime' in owner:
        try:
            fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
            return fields[0] != 'Z' and fields[19] == owner['startTime']
        except (OSError, IndexError):
            return False
    return True


def fault(code, message, location='$'):
    raise SchemaxisError(Fault(code, message, location, 'live',
                         recovery='Correct the request; after timeout or exit start a new session.'))


def prepare(document):
    """Resolve pure authoring data and validate, permitting any declared profile."""
    from schemaxis.documents import resolve_document
    document, _ = resolve_document(copy.deepcopy(document))
    for container in ('dimensions', 'definitions', 'settings'):
        document.pop(container, None)
    def literals(value):
        if isinstance(value, dict):
            if any(not isinstance(k, str) or k.startswith('$') for k in value):
                fault('UNSUPPORTED_LIVE_INPUT', 'Only literal declared input is supported')
            for item in value.values():
                literals(item)
        elif isinstance(value, list):
            for item in value:
                literals(item)
        elif type(value) in (int, float) and (not math.isfinite(value) or abs(value) > 1000000):
            fault('LIVE_LIMIT', 'Numeric input must be finite and within +/-1000000')
    literals(document)
    if not isinstance(document, dict):
        fault('INVALID_DOCUMENT', 'Expected a document object')
    if any(isinstance(n,dict) and (n.get('filter') in ('body','pad','pocket') or (isinstance(n.get('inputs'),dict) and 'body' in n['inputs'])) for n in (document.get('nodes') if isinstance(document.get('nodes'),list) else [])):
        fault('UNSUPPORTED_LIVE_INPUT','PartDesign Body workflows currently require a batch run')
    if 'parameters' in document or any(isinstance(n, dict) and 'drive' in n for n in (document.get('nodes') if isinstance(document.get('nodes'), list) else [])):
        fault('UNSUPPORTED_LIVE_INPUT', 'Native parameters and drive are batch-only; use run with finite variants')
    if 'designStudy' in document:
        fault('UNSUPPORTED_LIVE_INPUT', 'Run designStudy through batch execution; a live apply accepts one candidate')
    nodes = document.get('nodes')
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 100:
        fault('LIVE_LIMIT', 'Provide 1 to 100 live nodes')
    if any(isinstance(n, dict) and n.get('filter') in ('readSTEP', 'importSTEP') for n in nodes):
        fault('UNSUPPORTED_LIVE_INPUT', 'Live STEP imports are not supported; use a batch run')
    return plan(document, allow_profile=True)


def validate(command, args):
    if not isinstance(command, str) or command not in COMMANDS:
        fault('UNKNOWN_COMMAND', 'Unsupported live command')
    if set(args) != set(COMMANDS[command]):
        fault('INVALID_ARGUMENT', 'Command arguments must exactly match '+str(COMMANDS[command]))
    if command == 'apply':
        prepare(args['document'])
    if command in ('save', 'image'):
        path = args['path']
        suffix = '.FCStd' if command == 'save' else '.png'
        if not isinstance(path, str) or not Path(path).is_absolute() or Path(path).suffix != suffix:
            fault('INVALID_PATH', 'Provide an absolute '+suffix+' path')
        if Path(path).exists() or Path(path).is_symlink() or not Path(path).parent.is_dir():
            fault('INVALID_PATH', 'Output must be fresh and its parent must exist', path)
    if command == 'select' and (not isinstance(args['object'], str) or not isinstance(args['subelement'], str)):
        fault('INVALID_SELECTION', 'Selection requires object and subelement strings')


class LiveSession:
    def __init__(self, executable, directory, *, timeout=60, startup_timeout=60):
        self._lock = threading.RLock()
        self._closed = False
        self.process = None
        self._log = None
        if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in (timeout, startup_timeout)):
            fault('INVALID_ARGUMENT', 'Timeouts must be finite and positive')
        self.timeout = timeout
        executable = Path(executable)
        if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
            fault('INTERPRETER_NOT_FOUND', 'Provide an absolute executable FreeCAD GUI launcher')
        self.directory = Path(directory).absolute()
        if self.directory.exists() or self.directory.is_symlink():
            fault('OUTPUT_EXISTS', 'Live session directory must be fresh', str(self.directory))
        self.directory.mkdir(mode=0o700, parents=True)
        atomic_json(self.directory/'owner.json', owner_record())
        (self.directory/'runtime.zip').write_bytes(runtime_archive())
        macro = self.directory/'bridge.FCMacro'
        macro.write_text('import sys\nsys.path.insert(0, '+repr(str(self.directory/'runtime.zip'))+')\n'
                         'from schemaxis.adaptors.freecad.live_native import start\n'
                         'start('+repr(str(self.directory))+')\n')
        environment = os.environ.copy()
        # Native AppImage supplies its Python and Qt. Do not inject host runtimes.
        for key in ('PYTHONHOME', 'PYTHONPATH', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'LD_PRELOAD'):
            environment.pop(key, None)
        self._log = (self.directory/'freecad.log').open('wb')
        try:
            self.process = subprocess.Popen([str(executable), str(macro)], env=environment,
                stdin=subprocess.DEVNULL, stdout=self._log, stderr=subprocess.STDOUT,
                start_new_session=True)
            self._await(self.directory/'ready.json', startup_timeout)
            self.request('status')
        except BaseException:
            self._terminate()
            raise

    def _await(self, path, timeout):
        from schemaxis.dispatch import cancellation_requested
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            if cancellation_requested():
                fault('RUNNER_CANCELLED', 'FreeCAD live request was cancelled')
            if path.exists():
                if path.stat().st_size > MAX_BYTES:
                    fault('LIVE_LIMIT', 'Response exceeds transfer limit')
                return json.loads(path.read_text())
            if self.process.poll() is not None:
                fault('NATIVE_EXIT', 'FreeCAD exited; inspect '+str(self.directory/'freecad.log'))
            time.sleep(0.025)
        fault('LIVE_TIMEOUT', 'FreeCAD did not respond; inspect '+str(self.directory/'freecad.log'))

    def request(self, command, **args):
        with self._lock:
            if self._closed:
                fault('SESSION_CLOSED', 'Session is closed')
            validate(command, args)
            identity = uuid.uuid4().hex
            payload = {'id': identity, 'command': command, 'args': args}
            if len(json.dumps(payload, indent=2, allow_nan=False).encode())+1 > MAX_BYTES:
                fault('LIVE_LIMIT', 'Request exceeds transfer limit')
            try:
                atomic_json(self.directory/'request.json', payload)
                response = self._await(self.directory/(identity+'.json'), self.timeout)
                (self.directory/(identity+'.json')).unlink()
                if response.get('id') != identity:
                    fault('IPC_ERROR', 'Response identity differs')
            except BaseException:
                self._terminate()
                raise
            if 'fault' in response:
                raise SchemaxisError(Fault(**response['fault']))
            if command == 'shutdown':
                self._terminate(grace=5)
            return response['result']

    def _terminate(self, grace=0):
        self._closed = True
        if self.process is not None:
            if grace:
                try:
                    self.process.wait(timeout=grace)
                except subprocess.TimeoutExpired:
                    pass
            # AppImage's launcher is a shell; terminate its entire owned group.
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait(timeout=2)
        if self._log:
            self._log.close()

    def close(self):
        with self._lock:
            if not self._closed:
                try:
                    self.request('shutdown')
                finally:
                    self._terminate()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
