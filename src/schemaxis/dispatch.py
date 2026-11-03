# Copyright (C) 2026 David L F Gaden
"""Isolated native process groups, cooperative cancellation and resource hints."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from schemaxis.core.runners import RunReport
from schemaxis.artifacts import atomic_json
from schemaxis.errors import fail

_local = threading.local()
_deadline = ContextVar('schemaxis_execution_deadline', default=None)
# Bound at import so an adaptor test that scripts the shared time.monotonic for
# its own stage budget does not also feed the enclosing framework deadline.
_clock = time.monotonic


def _valid_timeout(timeout):
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        fail('INVALID_TIMEOUT', 'timeout must be finite and positive')


@contextmanager
def execution_deadline(timeout):
    """Bound a run and its verification without extending an enclosing budget.

    Native verifiers opt in by calling remaining_timeout before each launch and
    after their final observation. Existing subprocess timeout policy is unchanged.
    """
    _valid_timeout(timeout)
    deadline = _clock() + timeout
    parent = _deadline.get()
    token = _deadline.set(min(parent, deadline) if parent is not None else deadline)
    try:
        yield
    finally:
        _deadline.reset(token)


def remaining_timeout(default=300):
    """Return a native-call budget or reject cancelled/expired verification.

    Standalone verification has no run scope and uses the supplied default.
    """
    _valid_timeout(default)
    if cancellation_requested():
        fail('RUNNER_CANCELLED', 'execution cancelled before verification completed')
    deadline = _deadline.get()
    remaining = default if deadline is None else min(default, deadline - _clock())
    if remaining <= 0:
        fail('RUNNER_TIMED_OUT', 'execution and verification exhausted the timeout')
    return remaining


def cancellation_token():
    current = getattr(_local, 'value', None)
    return current[1] if current else None


def cancellation_requested():
    """Share console cancellation with persistent native transports."""
    current = getattr(_local, 'value', None)
    return bool(current and current[1] is not None and current[1].is_set())


@contextmanager
def allocation(resources, cancel=None):
    previous = getattr(_local, 'value', None)
    _local.value = (resources, cancel)
    try:
        yield
    finally:
        _local.value = previous


def process_tree_sample(root, known):
    """Track descendants even if MPI gives them separate process groups/sessions.

    Linux start times protect against PID reuse. RSS includes shared pages and is sampled.
    """
    processes = {}
    for stat in Path('/proc').glob('[0-9]*/stat'):
        try:
            fields = stat.read_text().rsplit(')', 1)[1].split()
            processes[int(stat.parent.name)] = (int(fields[1]), int(fields[2]), int(fields[19]),
                                               int(fields[21])*os.sysconf('SC_PAGE_SIZE'))
        except (OSError, ValueError, IndexError):
            continue
    live = {pid: start for pid, start in known.items() if pid in processes and processes[pid][2] == start}
    if root in processes and (root not in known or processes[root][2] == known[root]):
        live[root] = processes[root][2]
    changed = True
    while changed:
        changed = False
        for pid, (parent, group, start, rss) in processes.items():
            if pid not in live and (parent in live or group == root):
                live[pid] = start
                changed = True
    known.update(live)
    return (sum(processes[pid][3] for pid in live),
            sum(value[3] for value in processes.values() if value[1] == root), live)


def terminate_tree(process, known):
    _, _, live = process_tree_sample(process.pid, known)
    def send(pid, start, sig):
        try:
            fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
            if int(fields[19]) == start:
                os.kill(pid, sig)
        except (OSError, ValueError, IndexError):
            pass
    for pid, start in live.items():
        send(pid, start, signal.SIGTERM)
    if process.poll() is None:
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
    # Include children created during shutdown and tracked children reparented by MPI.
    _, _, live = process_tree_sample(process.pid, known)
    for pid, start in live.items():
        send(pid, start, signal.SIGKILL)
    # Also clean any not-yet-sampled children in the original process group.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


@dataclass
class SubprocessRunner:
    interpreter: object
    workspace: Path
    arguments: tuple = ()
    timeout: float = 300
    environment: dict = None

    def __call__(self, source):
        if self.timeout is not None and (type(self.timeout) not in (int, float) or not math.isfinite(self.timeout) or self.timeout <= 0):
            fail('INVALID_EXECUTION', 'timeout must be finite and positive')
        resources, cancel = getattr(_local, 'value', None) or ({}, None)
        if cancel is not None and cancel.is_set():
            fail('RUNNER_CANCELLED', 'execution cancelled before dispatch')
        directory = Path(self.workspace)
        directory.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(source.encode()).hexdigest()[:16]
        script = directory / ('replay-' + digest + '.py')
        script.write_text(source)
        command = [self.interpreter.executable, *self.arguments, str(script)]
        ranks = resources.get('ranks', 1)
        if ranks > 1:
            from .adaptors.registry import ADAPTORS
            capabilities = ADAPTORS.get(self.interpreter.kind, {}).get('executionCapabilities', {})
            if not capabilities.get('mpi') and 'mpi' not in capabilities.get('modes', []):
                fail('UNSUPPORTED_EXECUTION', 'adaptor does not support MPI')
            command = [resources['mpiexec'], '-n', str(ranks), *command]
        environment = dict(os.environ, **(self.environment or {}))
        if resources:
            threads = str(resources.get('threads', 1))
            environment.update(OMP_NUM_THREADS=threads, OPENBLAS_NUM_THREADS=threads,
                               MKL_NUM_THREADS=threads,
                               SCHEMAXIS_EXPECTED_RANKS=str(ranks))
            from .adaptors.registry import ADAPTORS
            environment.update({key: threads for key in ADAPTORS.get(self.interpreter.kind, {}).get('threadEnvironment', [])})
        started = time.monotonic()
        fault = None
        peak = group_peak = 0
        known = {}
        outpath, errpath = script.with_suffix('.stdout.log'), script.with_suffix('.stderr.log')
        with outpath.open('w') as stdout, errpath.open('w') as stderr:
            try:
                process = subprocess.Popen(command, stdout=stdout, stderr=stderr, env=environment,
                                           start_new_session=True)
            except OSError as error:
                fail('INTERPRETER_UNUSABLE', str(error), self.interpreter.executable)
            try:
                while process.poll() is None:
                    tree_rss, group_rss, _ = process_tree_sample(process.pid, known)
                    peak, group_peak = max(peak, tree_rss), max(group_peak, group_rss)
                    if cancel is not None and cancel.is_set():
                        fault = 'RUNNER_CANCELLED'
                    elif self.timeout is not None and time.monotonic()-started > self.timeout:
                        fault = 'RUNNER_TIMED_OUT'
                    if fault:
                        break
                    time.sleep(.1)
            finally:
                terminate_tree(process, known)
        report = RunReport(self.interpreter, str(script), process.returncode,
                           outpath.read_text(errors='replace')[-4000:],
                           errpath.read_text(errors='replace')[-4000:], time.monotonic()-started, tuple(command))
        atomic_json(script.with_suffix('.metrics.json'), {**report.to_dict(),
                    'sampledPeakGroupRssBytes': group_peak, 'sampledPeakTreeRssBytes': peak, 'resources': resources,
                    'fault': fault, 'stdoutLog': str(outpath), 'stderrLog': str(errpath)})
        if fault or process.returncode != 0:
            fail(fault or 'RUNNER_FAILED', 'native execution did not complete', str(script), **report.to_dict())
        return report
