# Copyright (C) 2026 David L F Gaden
"""Private, bounded file IPC shared by the two headless live adaptors.

Only packaged trusted scripts execute. This is a local single-client protocol,
not a security boundary against other processes belonging to the same user.
"""
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

MAX_BYTES = 32 * 1024 * 1024
COMMANDS = {'apply': {'document'}, 'geometry': set(), 'status': set(),
            'inspect': {'document', 'node', 'port'}, 'prepare-input': {'document', 'node'},
            'image': {'path'}, 'save': {'path'}, 'shutdown': set()}


def process_identity(pid):
    """Linux birth time prevents a recycled PID from keeping an orphan alive."""
    try:
        fields = Path('/proc/' + str(pid) + '/stat').read_text().rsplit(')', 1)[1].split()
        return fields[0], fields[19]
    except (OSError, ValueError, IndexError):
        return None


def owner_alive(pid, start_time=None):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    identity = process_identity(pid)
    if identity is None:
        return start_time is None  # POSIX fallback where /proc is unavailable.
    return identity[0] not in ('Z', 'X') and (start_time is None or identity[1] == start_time)


def fault(code, message, **observed):
    raise SchemaxisError(Fault(code, message, '$', 'live', observed=observed,
                        recovery='Correct the request; restart after transport failure or uncertain state.'))


def validate(command, args, provider=None):
    if not isinstance(command, str) or command not in COMMANDS:
        fault('UNKNOWN_COMMAND', 'Unsupported live command')
    if set(args) != COMMANDS[command]:
        fault('INVALID_ARGUMENT', 'Unexpected or missing live command arguments')
    try:
        size = len(json.dumps(args, allow_nan=False).encode())
    except (ValueError, TypeError, RecursionError):
        fault('INVALID_ARGUMENT', 'Live input must be finite JSON')
    if size > MAX_BYTES:
        fault('LIVE_LIMIT', 'Request exceeds transfer limit')
    if command in ('apply', 'inspect', 'prepare-input') and not isinstance(args['document'], dict):
        fault('INVALID_DOCUMENT', 'Expected a full authored document object')
    if command in ('inspect', 'prepare-input') and (not isinstance(args['node'], str) or not args['node']):
        fault('INVALID_ARGUMENT', 'Choose an input node to inspect')
    if command == 'inspect' and (type(args['port']) is not int or args['port'] < 0):
        fault('INVALID_ARGUMENT', 'Output port must be a nonnegative integer')
    if command in ('image', 'save'):
        path = args['path']
        from .adaptors.registry import ADAPTORS
        suffixes = {'.png'} if command == 'image' else {
            m['nativeExtension'] for key, m in ADAPTORS.items()
            if m.get('nativeExtension') and (provider is None or key == provider)}
        if not isinstance(path, str) or not Path(path).is_absolute() or Path(path).suffix.lower() not in suffixes:
            fault('INVALID_PATH', 'Output requires an absolute path with the native file extension')
        path = Path(path)
        if path.exists() or path.is_symlink() or not path.parent.is_dir():
            fault('OUTPUT_EXISTS', 'Output requires a fresh path with an existing parent')
        receipt = Path(str(path) + '.receipt.json')
        if command == 'save' and (receipt.exists() or receipt.is_symlink()):
            fault('OUTPUT_EXISTS', 'Native save receipt already exists')


class ProcessSession:
    """Synchronous requests, bounded waits, and owned-process-group cleanup."""
    provider = None

    def __init__(self, executable, directory, *, timeout=60, startup_timeout=60):
        self._lock = threading.RLock()
        self._closed = False
        self.process = None
        self._log = None
        for value in (timeout, startup_timeout):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                fault('INVALID_ARGUMENT', 'Timeouts must be finite and positive')
        self.timeout = timeout
        executable = Path(executable)
        from .adaptors.registry import metadata
        configuration = metadata(self.provider)
        if configuration.get('liveExecutable') and executable.is_dir():
            executable = executable / configuration['liveExecutable']
        if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
            fault('INTERPRETER_NOT_FOUND', 'Provide an absolute executable or adaptor installation root')
        self.directory = Path(directory).absolute()
        if self.directory.exists() or self.directory.is_symlink():
            fault('OUTPUT_EXISTS', 'Live session directory must be fresh')
        self.directory.mkdir(mode=0o700, parents=True)
        (self.directory / 'runtime.zip').write_bytes(runtime_archive())
        identity = process_identity(os.getpid())
        owner = {'pid': os.getpid(), 'startTime': identity[1] if identity else None}
        atomic_json(self.directory / 'owner.json', owner)
        script = self.directory / 'worker.py'
        from .adaptors.registry import adaptor_package
        script.write_text('import sys\nsys.path.insert(0, ' + repr(str(self.directory / 'runtime.zip')) + ')\n'
                          'from ' + adaptor_package(self.provider) + '.live_native import start\n'
                          'start(' + repr(str(self.directory)) + ', parent_pid=' + str(owner['pid']) +
                          ', parent_start=' + repr(owner['startTime']) + ')\n')
        arguments = [str(executable), *configuration.get('liveArguments', []), str(script)]
        environment = os.environ.copy()
        for key in ('PYTHONHOME', 'PYTHONPATH', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'LD_PRELOAD'):
            environment.pop(key, None)
        self._log = (self.directory / 'native.log').open('wb')
        try:
            self.process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=self._log,
                                            stderr=subprocess.STDOUT, env=environment, start_new_session=True)
            ready = self._await(self.directory / 'ready.json', startup_timeout)
            if ready.get('provider') != self.provider:
                fault('IPC_ERROR', 'Unexpected worker handshake')
            self.request('status')
        except BaseException:
            self._terminate()
            raise

    def _await(self, path, timeout):
        from schemaxis.dispatch import cancellation_requested
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cancellation_requested():
                fault('RUNNER_CANCELLED', 'Live request cancelled; worker terminated', uncertain=True)
            if path.is_file():
                if path.stat().st_size > MAX_BYTES:
                    fault('LIVE_LIMIT', 'Worker response exceeds transfer limit')
                return json.loads(path.read_text())
            if self.process.poll() is not None:
                fault('NATIVE_EXIT', 'Native worker exited', log=str(self.directory / 'native.log'), uncertain=True)
            time.sleep(0.025)
        fault('LIVE_TIMEOUT', 'Native worker did not respond', uncertain=True, log=str(self.directory / 'native.log'))

    def request(self, command, **args):
        with self._lock:
            if self._closed:
                fault('SESSION_CLOSED', 'Live session is closed')
            validate(command, args, self.provider)
            identity = uuid.uuid4().hex
            response_path = self.directory / (identity + '.json')
            try:
                from schemaxis.dispatch import cancellation_requested
                if cancellation_requested():
                    fault('RUNNER_CANCELLED', 'Live request cancelled before submission; worker terminated', uncertain=True)
                atomic_json(self.directory / 'request.json', {'id': identity, 'command': command, 'args': args})
                response = self._await(response_path, self.timeout)
                response_path.unlink()
                if response.get('id') != identity or ('result' in response) == ('fault' in response):
                    fault('IPC_ERROR', 'Invalid response envelope')
            except BaseException:
                self._terminate()
                raise
            if 'fault' in response:
                raise SchemaxisError(Fault(**response['fault']))
            if command == 'shutdown':
                self._terminate(grace=5)
            return response['result']

    def image(self, path):
        return self.request('image', path=str(path))

    def save(self, path):
        return self.request('save', path=str(path))

    def _terminate(self, grace=0):
        self._closed = True
        if self.process is not None:
            if grace:
                try:
                    self.process.wait(timeout=grace)
                except subprocess.TimeoutExpired:
                    pass
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(self.process.pid, sig)
                except ProcessLookupError:
                    pass
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    continue
            self.process.wait(timeout=2)
        if self._log is not None:
            self._log.close()

    def close(self):
        with self._lock:
            if not self._closed:
                try:
                    if self.process is not None and self.process.poll() is None:
                        self.request('shutdown')
                finally:
                    self._terminate()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def serve(directory, worker, parent_pid=None, parent_start=None):
    """Run synchronously on the native main thread; native stdout stays in a log."""
    directory = Path(directory)
    owner_gone, finished = threading.Event(), threading.Event()
    def watch_owner():
        while not finished.wait(0.1):
            if not owner_alive(parent_pid, parent_start):
                owner_gone.set()
                # Native API cleanup belongs to the main thread. If it is stuck
                # inside a native call, terminate only this orphaned process.
                if not finished.wait(2):
                    os._exit(143)
                return
    if parent_pid is not None:
        threading.Thread(target=watch_owner, name='live-owner-watch', daemon=True).start()
    atomic_json(directory / 'ready.json', {'provider': worker.provider, 'pid': os.getpid()})
    try:
        while True:
            if owner_gone.is_set() or (parent_pid is not None and not owner_alive(parent_pid, parent_start)):
                break
            request_path = directory / 'request.json'
            if not request_path.exists():
                time.sleep(0.025)
                continue
            if request_path.stat().st_size > MAX_BYTES:
                fault('LIVE_LIMIT', 'IPC request exceeds transfer limit')
            request = json.loads(request_path.read_text())
            request_path.unlink()
            identity = request['id']
            if not isinstance(identity, str) or len(identity) != 32 or any(c not in '0123456789abcdef' for c in identity):
                fault('IPC_ERROR', 'Invalid request identity')
            command = request.get('command')
            try:
                args = request.get('args', {})
                validate(command, args, worker.provider)
                result = worker.dispatch(command, args)
                response = {'id': identity, 'result': result}
                if len(json.dumps(response, allow_nan=False).encode()) > MAX_BYTES:
                    fault('LIVE_LIMIT', 'Geometry response exceeds transfer limit; simplify the model')
            except Exception as error:
                detail = error.fault if isinstance(error, SchemaxisError) else Fault(
                    'NATIVE_ERROR', str(error), '$', 'live', recovery='Inspect native.log and correct the request.')
                response = {'id': identity, 'fault': detail.to_dict()}
            atomic_json(directory / (identity + '.json'), response)
            if command == 'shutdown':
                break
    finally:
        try:
            worker.close()
        finally:
            finished.set()
