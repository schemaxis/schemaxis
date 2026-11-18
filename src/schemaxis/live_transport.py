# Copyright (C) 2026 David L. F. Gaden.
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
DATA_TRANSITION = {'expected', 'document', 'roots', 'state', 'preserve', 'request'}
COMMANDS = {'data-prepare-aligned-transition': {'identity', 'transition'}, 'data-prepare-owned-identity': {'owner', 'expected', 'steps', 'result'},
            'data-owned-identity': {'owner', 'expected', 'steps', 'result'}, 'data-prepare-transition': DATA_TRANSITION, 'data-transition': DATA_TRANSITION | {'prepared'},
            'data-measure': {'expected', 'nodes'}, 'graph-prepare-identity': {'expected', 'proofs'}, 'graph-reidentify': {'expected', 'proofs'},
            'data-inspect': {'node', 'port', 'geometry'}, 'data-load': {'document', 'roots', 'state'},
            'data-reidentify': {'expected', 'steps', 'result'}, 'data-prepare-identity': {'expected', 'steps', 'result'}, 'apply': {'document'}, 'geometry': set(), 'status': set(),
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


def request_budget(command, args):
    from .wire_json import size
    return size({'id': '0' * 32, 'command': command, 'args': args}, MAX_BYTES)


def reply_budget(result):
    from .wire_json import size
    return size({'id': '0' * 32, 'result': result}, MAX_BYTES)


def inspection_reply(result):
    """Optional display geometry may be unavailable; measurements are required."""
    try:
        reply_budget(result)
    except SchemaxisError as error:
        if error.fault.code != 'LIVE_LIMIT' or result.get('geometry') is None:
            raise
        result = {**result, 'geometry': None,
                  'geometryUnavailable': {'code': 'LIVE_LIMIT', 'message': 'Optional display geometry exceeds the transfer limit'}}
        reply_budget(result)
    return result


def owner_matches(actual, expected):
    """Closed ownership token, with exact JSON types and all known candidate fields."""
    def same(left, right):
        if type(left) is not type(right): return False
        if isinstance(left, dict):
            return left.keys() == right.keys() and all(same(left[k], right[k]) for k in left)
        if isinstance(left, list):
            return len(left) == len(right) and all(same(a, b) for a, b in zip(left, right))
        if type(left) is float:
            return math.isfinite(left) and math.isfinite(right) and left == right
        return type(left) in (str, int, bool, type(None)) and left == right
    if (type(actual) is not dict or set(actual) != {'nonce', 'generation', 'documentDigest', 'roots', 'visit'}
            or type(actual['nonce']) is not str or len(actual['nonce']) != 32
            or any(c not in '0123456789abcdef' for c in actual['nonce'])
            or type(actual['generation']) is not int or actual['generation'] < 0):
        return False
    return all(key in actual and same(actual[key], value) for key, value in expected.items())


def validate(command, args, provider=None):
    if not isinstance(command, str) or command not in COMMANDS:
        fault('UNKNOWN_COMMAND', 'Unsupported live command')
    expected = COMMANDS[command] | ({'geometry'} if command == 'inspect' and 'geometry' in args else set())
    if command in ('inspect', 'data-inspect') and type(args.get('geometry', False)) is not bool:
        fault('INVALID_ARGUMENT', 'Geometry inspection must be true or false')
    if set(args) != expected:
        fault('INVALID_ARGUMENT', 'Unexpected or missing live command arguments')
    request_budget(command, args)
    if command == 'data-prepare-aligned-transition':
        if not isinstance(args['identity'], dict) or not isinstance(args['transition'], dict):
            fault('INVALID_ARGUMENT', 'Use the exact identity and ordinary transition candidates')
        validate('data-owned-identity', args['identity'], provider)
        validate('data-prepare-transition', args['transition'], provider)
    if command in ('graph-prepare-identity', 'graph-reidentify') and (
            not isinstance(args['expected'], dict) or set(args['expected']) != {'documentDigest', 'revision', 'geometryDigest'}
            or type(args['expected']['revision']) is not int
            or not all(isinstance(args['expected'][k], str) and len(args['expected'][k]) == 64
                       for k in ('documentDigest', 'geometryDigest'))
            or not isinstance(args['proofs'], list) or not 0 < len(args['proofs']) <= 32):
        fault('INVALID_ARGUMENT', 'Graph identity transitions need exact current evidence and 1-32 proofs')
    if command in ('apply', 'inspect', 'prepare-input', 'data-load', 'data-prepare-transition', 'data-transition') and not isinstance(args['document'], dict):
        fault('INVALID_DOCUMENT', 'Expected a full authored document object')
    if command in ('inspect', 'prepare-input', 'data-inspect') and (not isinstance(args['node'], str) or not args['node']):
        fault('INVALID_ARGUMENT', 'Choose an input node to inspect')
    if command in ('inspect', 'data-inspect') and (type(args['port']) is not int or args['port'] < 0):
        fault('INVALID_ARGUMENT', 'Output port must be a nonnegative integer')
    if command in ('data-load', 'data-prepare-transition', 'data-transition') and (not isinstance(args['roots'], list) or not args['roots']
            or any(not isinstance(n, str) or not n for n in args['roots']) or not isinstance(args['state'], dict)):
        fault('INVALID_ARGUMENT', 'Live Data needs node names and a visit state')
    if command in ('data-prepare-transition', 'data-transition', 'data-measure', 'data-owned-identity', 'data-prepare-owned-identity'):
        import re
        owned_identity = command in ('data-owned-identity', 'data-prepare-owned-identity')
        owner = args['owner'] if owned_identity else args['expected']
        if (not isinstance(owner, dict) or set(owner) != {'nonce', 'generation', 'documentDigest', 'roots', 'visit'}
                or not isinstance(owner['nonce'], str) or not re.fullmatch('[0-9a-f]{32}', owner['nonce'])
                or type(owner['generation']) is not int or owner['generation'] < 0
                or not isinstance(owner['documentDigest'], str) or not re.fullmatch('[0-9a-f]{64}', owner['documentDigest'])
                or not isinstance(owner['roots'], list) or not isinstance(owner['visit'], dict)):
            fault('INVALID_ARGUMENT', 'Use the exact current resident owner token')
        names = [] if owned_identity else args['nodes'] if command == 'data-measure' else args['preserve']
        if not isinstance(names, list) or any(not isinstance(n, str) or not n for n in names) or len(names) != len(set(names)):
            fault('INVALID_ARGUMENT', 'Use distinct resident node names')
        if not owned_identity and command != 'data-measure' and (not isinstance(args['request'], str) or not re.fullmatch('[0-9a-f]{32}', args['request'])):
            fault('INVALID_ARGUMENT', 'Use a fresh transition request identity')
        if command == 'data-transition' and (not isinstance(args['prepared'], str) or not re.fullmatch('[0-9a-f]{64}', args['prepared'])):
            fault('INVALID_ARGUMENT', 'Use an exact preparation digest')
    if command in ('data-reidentify', 'data-prepare-identity', 'data-owned-identity', 'data-prepare-owned-identity') and (
            not all(isinstance(args[k], str) and len(args[k]) == 64 for k in ('expected', 'result'))
            or not isinstance(args['steps'], list) or not 0 < len(args['steps']) <= 32
            or any(not isinstance(s, list) or len(s) != 2 or not all(isinstance(n, str) and n for n in s)
                   for s in args['steps'])):
        fault('INVALID_ARGUMENT', 'Identity transitions need exact plan digests and 1-32 named steps')
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
    worker_module = None

    def __init__(self, executable, directory, *, timeout=60, startup_timeout=60):
        self._lock = threading.RLock()
        self._closed = False
        self._retained_uncertain = False
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
                          'from ' + (self.worker_module or adaptor_package(self.provider) + '.live_native') + ' import start\n'
                          'start(' + repr(str(self.directory)) + ', parent_pid=' + str(owner['pid']) +
                          ', parent_start=' + repr(owner['startTime']) +
                          (', provider=' + repr(self.provider) if self.worker_module else '') + ')\n')
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
        return self._request(command, args, retain=False)

    def request_retained(self, command, **args):
        """Preserving Data IPC: an unacknowledged reply keeps ownership until explicit close."""
        if command not in ('data-prepare-aligned-transition', 'data-prepare-transition', 'data-transition', 'data-measure', 'status',
                           'data-owned-identity', 'data-prepare-owned-identity', 'data-inspect'):
            fault('INVALID_ARGUMENT', 'Retained requests are limited to preserving Data ownership')
        return self._request(command, args, retain=True)

    def _request(self, command, args, *, retain):
        with self._lock:
            if self._closed:
                fault('SESSION_CLOSED', 'Live session is closed')
            if getattr(self, '_retained_uncertain', False):
                fault('UNCERTAIN_STATE', 'A resident request was not acknowledged; explicitly release this owner', uncertain=True)
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
            except BaseException as error:
                if retain and not (isinstance(error, SchemaxisError) and error.fault.code == 'RUNNER_CANCELLED'):
                    self._retained_uncertain = True
                else:
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
                    if self.process is not None and self.process.poll() is None and not getattr(self, '_retained_uncertain', False):
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
                reply_budget(result)
            except Exception as error:
                detail = error.fault if isinstance(error, SchemaxisError) else Fault(
                    'NATIVE_ERROR', str(error), '$', 'live', recovery='Inspect native.log and correct the request.')
                response = {'id': identity, 'fault': detail.to_dict()}
                from .wire_json import size
                try:
                    size(response, MAX_BYTES)
                except SchemaxisError:
                    # Size limits must not erase the ownership outcome of a
                    # mutation. A bounded verified reversal is still useful;
                    # otherwise an oversized mutating fault is uncertain.
                    outcome = {}
                    if detail.observed.get('uncertain'):
                        outcome['uncertain'] = True
                    elif detail.observed.get('rolledBack') is True:
                        outcome['rolledBack'] = True
                    elif command in ('data-transition', 'data-owned-identity'):
                        outcome['uncertain'] = True
                    response = {'id': identity, 'fault': Fault('LIVE_LIMIT',
                        'Worker fault details exceed the transfer limit', '$', 'live', observed=outcome).to_dict()}
                    size(response, MAX_BYTES)
            atomic_json(directory / (identity + '.json'), response)
            if command == 'shutdown':
                break
    finally:
        try:
            worker.close()
        finally:
            finished.set()
