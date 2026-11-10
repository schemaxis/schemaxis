"""Fixed PID-1 worker for trusted images; never an authored command endpoint."""
import errno
import hashlib
import math
import os
import re
import stat
from pathlib import Path
import signal
import select
import struct
import sys
import time

from .container_protocol import read_frame, frame, pack_tree, unpack_tree, archive_limit
from .core.faults import SchemaxisError, Fault
from .storage import digest, encoded, load
from .observations import fail


def mount_path(field):
    return re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), field)


def quiesce(timeout=3):
    """Kill/reap every other namespace process before exporting any evidence."""
    if os.getppid() != 1:
        fail('ISOLATION_RUNTIME_UNAVAILABLE', 'worker must belong to its private PID-1 supervisor')
    trusted = {1, os.getpid()}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # An unreadable procfs is uncertainty, never evidence of no children.
        processes = [int(path.name) for path in Path('/proc').iterdir()
                     if path.name.isdecimal() and int(path.name) not in trusted]
        for pid in processes:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        while True:
            try:
                if os.waitpid(-1, os.WNOHANG)[0] == 0:
                    break
            except ChildProcessError:
                break
        remaining = [path for path in Path('/proc').iterdir()
                     if path.name.isdecimal() and int(path.name) not in trusted]
        if not remaining:
            return {'remainingProcesses': 0, 'method': 'supervised-private-pid-namespace-kill-and-reap'}
        time.sleep(0.01)
    fail('ISOLATION_CLEANUP_UNKNOWN', 'native namespace processes did not terminate')


def enforced_limits(volume, limits):
    if os.getppid() != 1:
        fail('ISOLATION_RUNTIME_UNAVAILABLE', 'worker does not belong to its PID-1 supervisor')
    cgroup = Path('/sys/fs/cgroup')
    actual = {name: (cgroup / name).read_text().strip()
              for name in ('memory.max', 'memory.swap.max', 'pids.max', 'cpu.max')}
    quota, period = actual['cpu.max'].split()
    if (actual['memory.max'] == 'max' or int(actual['memory.max']) > limits['memory_bytes']
            or actual['memory.swap.max'] != '0' or actual['pids.max'] == 'max'
            or int(actual['pids.max']) > limits['pids'] or quota == 'max'
            or int(quota) / int(period) > limits['cpus'] + 0.00001):
        fail('ISOLATION_UNAVAILABLE', 'worker cgroup limits are absent or weaker than requested')
    mounted = False
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        fields, filesystem = line.split(' - ', 1)
        if mount_path(fields.split()[4]) == str(volume) and filesystem.split()[0] == 'tmpfs':
            mounted = True
    space = os.statvfs(volume)
    if (not mounted or space.f_blocks * space.f_frsize > limits['disk_bytes']
            or not 0 < space.f_files <= limits['inodes']):
        fail('ISOLATION_UNAVAILABLE', 'job tmpfs byte/inode limits were not established')
    return {'cgroup': actual, 'tmpfsBytes': space.f_blocks * space.f_frsize,
            'tmpfsInodes': space.f_files}


def metrics():
    root = Path('/sys/fs/cgroup')
    result = {'kind': 'observed-worker-cgroup-sample',
              'boundary': 'post-native-quiescence-pre-export',
              'scope': 'container startup, input staging and application through native quiescence',
              'excludes': ['archive export', 'container teardown']}
    for name in ('cpu.stat', 'memory.peak', 'memory.events', 'pids.events'):
        try:
            result[name] = (root / name).read_text()[:4096]
        except OSError:
            result[name] = None
    return result


def check_inputs(header):
    """Validate the exact read-only file mount closure before any adaptor hook."""
    if header.get('inputs') is None:
        if 'capturedContentPolicy' in header:
            fail('MCP_POLICY_DENIED', 'captured-content policy requires immutable input bindings')
        return
    from .execution_inputs import bindings_from_record, check_bound_document
    inputs = bindings_from_record(header['inputs'])
    check_bound_document(header['document'], inputs)
    mounts = {}
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        fields = line.split(' - ', 1)[0].split()
        path = mount_path(fields[4])
        mounts[path] = set(fields[5].split(','))
    for capture in inputs.captures:
        info = capture.path.lstat()
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o444
                or info.st_nlink != 1 or info.st_dev != capture.device or info.st_ino != capture.inode
                or info.st_size != capture.bytes or 'ro' not in mounts.get(str(capture.path), set())):
            fail('ISOLATION_UNAVAILABLE', 'captured file identity or read-only mount differs')
        with capture.path.open('rb') as stream:
            actual = 'sha256:'+hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != capture.sha256:
            fail('ISOLATION_UNAVAILABLE', 'captured file digest differs')
    # No adaptor hook sees a path until every exact mount and immutable digest
    # has been proved. This is repeated for capture, stale-check, run and verify.
    if 'capturedContentPolicy' in header:
        from .mcp_admission import FileAdmission
        admission = FileAdmission()
        expected = admission.captured_content_policy(header['document'], inputs)
        if header['capturedContentPolicy'] != expected:
            fail('MCP_POLICY_DENIED', 'captured-content policy differs from the installed pinned contracts')
        admission.validate_captured_content(header['document'], inputs)


def perform(header, archive, observations=None):
    from .adaptors import registry
    from . import workflow
    from .capabilities import digest as document_digest
    from .execution_backends import collect_publications
    limits = header['limits']
    volume = Path(header['volume'])
    directory = Path(header['directory'])
    if (not volume.is_absolute() or directory != volume / 'run'
            or Path.cwd() != volume or not 4096 <= limits['disk_bytes'] <= 64*1024*1024
            or not 16 <= limits['inodes'] <= 8192):
        fail('ISOLATION_PROTOCOL_ERROR', 'worker paths or bounds differ from its contract')
    proof = enforced_limits(volume, limits)
    if observations is not None:
        observations['limits'] = proof
    for name in ('HOME', 'TMPDIR', 'XDG_CACHE_HOME'):
        path = Path(os.environ[name])
        if not path.is_relative_to(volume):
            fail('ISOLATION_UNAVAILABLE', 'worker scratch escaped its job volume')
        path.mkdir(parents=True, exist_ok=True)
    document = header['document']
    if (document_digest(document) != header['documentDigest']
            or hashlib.sha256(encoded(header['plan'])).hexdigest() != header['planDigest']):
        fail('ISOLATION_PROTOCOL_ERROR', 'captured worker request digests differ')
    if archive:
        unpack_tree(archive, volume, limits['disk_bytes'], limits['inodes'])
    check_inputs(header)
    planned = (workflow.inspect_plan(document) if document.get('version') == 'schemaxis.workflow/1'
               else registry.plan(document))
    if header['action'] == 'plan':
        if archive:
            fail('ISOLATION_PROTOCOL_ERROR', 'planning cannot import prior run evidence')
        check_inputs(header)
        return planned, None, proof
    if planned != header['plan']:
        fail('STALE_PLAN', 'image planning differs from the captured plan')
    if header['action'] == 'run':
        if archive:
            fail('ISOLATION_PROTOCOL_ERROR', 'execution cannot import prior run evidence')
        result = (workflow.execute(document, directory, timeout=header['timeout'])
                  if document.get('version') == 'schemaxis.workflow/1'
                  else registry.run(document, directory, timeout=header['timeout']))
        publications = None
    elif header['action'] == 'verify':
        if load((directory / 'authored.json').read_text()) != document:
            fail('VERIFICATION_FAILED', 'retained execution differs from captured request')
        for relative, expected in header['receiptDigests']:
            path = directory / relative
            if (Path(relative).is_absolute() or '..' in Path(relative).parts
                    or hashlib.sha256(path.read_bytes()).hexdigest() != expected):
                fail('VERIFICATION_FAILED', 'retained receipt digest changed')
        result = (workflow.verify(directory) if document.get('version') == 'schemaxis.workflow/1'
                  else registry.verify(directory, document))
        publications = collect_publications(header['job'], document, Path(header['workspace']))
    else:
        fail('ISOLATION_PROTOCOL_ERROR', 'unknown fixed worker action')
    check_inputs(header)
    return result, publications, proof


def work(deadline_pipe):
    # Save the protocol FD before redirecting both native stdout and stderr.
    # Descendants inherit only the log descriptors; this is not authentication
    # against a same-UID compromised worker/application.
    protocol = os.fdopen(os.dup(1), 'wb', buffering=0)
    header, archive = read_frame(sys.stdin.buffer, 96*1024*1024)
    deadline = header['deadlineMonotonic']
    if type(deadline) not in (int, float) or not math.isfinite(deadline):
        fail('ISOLATION_PROTOCOL_ERROR', 'worker total deadline is invalid')
    os.write(deadline_pipe, struct.pack('!d', deadline))
    os.close(deadline_pipe)
    volume = Path(header['volume'])
    log = volume / '.worker.log'
    response = {'requestDigest': digest(header), 'action': header.get('action')}
    original = os.dup(1)
    original_error = os.dup(2)
    started = time.monotonic()
    try:
        with log.open('xb') as stream:
            os.dup2(stream.fileno(), 1)
            os.dup2(stream.fileno(), 2)
            try:
                result, publications, proof = perform(header, archive, response)
                response.update(result=result, publications=publications, limits=proof)
            except Exception as error:
                fault = (error.fault.to_dict() if isinstance(error, SchemaxisError)
                         else Fault('ISOLATION_WORKER_FAILED', str(error), '$', 'execution').to_dict())
                if isinstance(error, OSError) and error.errno == errno.ENOSPC:
                    fault = Fault('ISOLATION_LIMIT_EXCEEDED', 'job tmpfs was exhausted', '$',
                                  'execution', observed={'limit': 'disk-or-inodes'}).to_dict()
                response['fault'] = fault
            sys.stdout.flush()
            sys.stderr.flush()
            response['quiescence'] = quiesce()
            response['metrics'] = metrics()
            response['wallSeconds'] = time.monotonic() - started
            limits = header['limits']
            payload, inventory = pack_tree(volume / 'run', limits['disk_bytes'], limits['inodes'])
            response['inventory'] = inventory
            protocol.write(frame(response, payload))
    finally:
        os.dup2(original, 1)
        os.dup2(original_error, 2)
        os.close(original)
        os.close(original_error)
        protocol.close()


def supervise(child, deadline_pipe, *, startup_seconds=15):
    """PID 1 stays outside application code and independently enforces total time."""
    deadline = time.monotonic()+startup_seconds
    awaiting_deadline = True
    try:
        while True:
            try:
                while True:
                    pid, status = os.waitpid(-1, os.WNOHANG)
                    if pid == 0:
                        break
                    if pid == child:
                        return os.waitstatus_to_exitcode(status)
            except ChildProcessError:
                return 125
            if time.monotonic() >= deadline:
                # PID 1 can kill every other namespace process and terminate
                # itself. A child watchdog cannot force-kill namespace init.
                for path in Path('/proc').iterdir():
                    if path.name.isdecimal() and int(path.name) != 1:
                        try:
                            os.kill(int(path.name), signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                return 124
            if awaiting_deadline:
                ready, _, _ = select.select([deadline_pipe], [], [], min(.01, max(0, deadline-time.monotonic())))
                if ready:
                    value = os.read(deadline_pipe, 8)
                    if len(value) != 8:
                        return 125
                    supplied, = struct.unpack('!d', value)
                    if not math.isfinite(supplied):
                        return 125
                    deadline = min(supplied, time.monotonic()+86400)
                    awaiting_deadline = False
                    os.close(deadline_pipe)
            else:
                time.sleep(.01)
    finally:
        if awaiting_deadline:
            os.close(deadline_pipe)


def main():
    if os.getpid() != 1:
        fail('ISOLATION_RUNTIME_UNAVAILABLE', 'supervisor must own a private PID namespace')
    read_end, write_end = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(read_end)
        try:
            work(write_end)
        except BaseException:
            os._exit(125)
        os._exit(0)
    os.close(write_end)
    status = supervise(child, read_end)
    # Exiting namespace init destroys every remaining process, even on malformed
    # protocol/early child exit. Never enter an unbounded interpreter cleanup.
    os._exit(status if 0 <= status <= 255 else 125)


if __name__ == '__main__':
    main()
