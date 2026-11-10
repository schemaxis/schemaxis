"""Opt-in, fail-closed Docker worker executor with bounded tmpfs evidence export.

Profiles and admission are trusted operator configuration. This implementation
has no qualified image by default and never falls back to native host execution.
"""
from dataclasses import asdict, dataclass
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import time
import uuid

from .container_protocol import (frame, unframe, pack_tree, unpack_tree,
                                 archive_limit, HEADER_LIMIT)
from .execution_backends import ExecutionRequest, ExecutionOutcome, VerificationOutcome, PlanningOutcome
from .storage import digest, encoded
from .core.faults import Fault, SchemaxisError


def failure(code, message, **observed):
    raise SchemaxisError(Fault(code, message, '$', 'isolation', observed=observed))


@dataclass(frozen=True)
class IsolationLimits:
    memory_bytes: int = 512 * 1024 * 1024
    cpus: float = 1.0
    pids: int = 64
    disk_bytes: int = 32 * 1024 * 1024
    inodes: int = 4096
    wall_seconds: float = 120

    def __post_init__(self):
        for name, lower, upper in (('memory_bytes', 16*1024*1024, 4*1024**3),
                                    ('pids', 16, 256), ('disk_bytes', 4096, 64*1024*1024),
                                    ('inodes', 16, 8192)):
            value = getattr(self, name)
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError('invalid isolation limit: ' + name)
        for name, upper in (('cpus', 4), ('wall_seconds', 86400)):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= upper:
                raise ValueError('invalid isolation limit: ' + name)


@dataclass(frozen=True)
class IsolationProfile:
    image: str
    providers: tuple
    routes: tuple
    limits: IsolationLimits = IsolationLimits()
    qualification_id: str | None = None
    capabilities: tuple = ()

    def __post_init__(self):
        if not re.fullmatch(r'[a-z0-9][a-z0-9./:_-]*@sha256:[0-9a-f]{64}', self.image):
            raise ValueError('an immutable image digest is required')
        if (not isinstance(self.providers, tuple) or not self.providers
                or not isinstance(self.routes, tuple) or not self.routes
                or any(not isinstance(v, str) or not v for v in self.providers+self.routes)):
            raise ValueError('nonempty trusted provider/route tuples are required')
        if self.qualification_id is not None and (not isinstance(self.qualification_id, str)
                                                   or not self.qualification_id.strip()):
            raise ValueError('qualification identity must be a nonempty trusted string')
        if (not isinstance(self.capabilities, tuple) or len(self.capabilities) > 32
                or any(not isinstance(v, str) or not re.fullmatch('[a-z][a-z0-9-]{0,63}', v)
                       for v in self.capabilities) or len(set(self.capabilities)) != len(self.capabilities)):
            raise ValueError('invalid trusted image capabilities')


class ImageResolver:
    def __init__(self, profiles=()):
        self.profiles = tuple(profiles)

    def resolve(self, providers, routes):
        matches = [profile for profile in self.profiles
                   if set(profile.providers) == set(providers) and set(profile.routes) == set(routes)]
        if len(matches) != 1 or not matches[0].qualification_id:
            failure('ISOLATION_UNAVAILABLE', 'no uniquely qualified image covers this provider/route set')
        return matches[0]


@dataclass(frozen=True)
class EngineResult:
    returncode: int
    stdout: bytes
    stderr: bytes


class DockerEngine:
    """Bounded CLI I/O; actual daemon/container cleanup belongs to the executor."""
    def __init__(self, executable='/usr/bin/docker'):
        if not Path(executable).is_absolute():
            raise ValueError('engine executable must be an absolute trusted path')
        self.executable = executable

    def command(self, arguments, *, payload=b'', timeout=15, cancellation=None,
                max_output=1024*1024):
        try:
            process = subprocess.Popen([self.executable, *arguments], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        except OSError as error:
            failure('ISOLATION_RUNTIME_UNAVAILABLE', 'container engine could not start', cause=str(error))
        started, sent = time.monotonic(), 0
        output, errors = bytearray(), bytearray()
        selector = selectors.DefaultSelector()
        for stream in (process.stdin, process.stdout, process.stderr):
            os.set_blocking(stream.fileno(), False)
        selector.register(process.stdout, selectors.EVENT_READ, output)
        selector.register(process.stderr, selectors.EVENT_READ, errors)
        if payload:
            selector.register(process.stdin, selectors.EVENT_WRITE, None)
        else:
            process.stdin.close()
        try:
            while selector.get_map():
                if cancellation is not None and cancellation.is_set():
                    failure('RUNNER_CANCELLED', 'container request was cancelled')
                if time.monotonic()-started >= timeout:
                    failure('ISOLATION_LIMIT_EXCEEDED', 'container command exceeded its deadline', limit='wall')
                for key, _ in selector.select(0.05):
                    if key.fileobj is process.stdin:
                        try:
                            sent += os.write(process.stdin.fileno(), payload[sent:sent+65536])
                        except BrokenPipeError:
                            sent = len(payload)
                        if sent == len(payload):
                            selector.unregister(process.stdin)
                            process.stdin.close()
                    else:
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                            continue
                        bound = max_output if key.data is output else 65536
                        if len(key.data)+len(chunk) > bound:
                            failure('ISOLATION_LIMIT_EXCEEDED', 'container protocol output exceeded its bound', limit='protocol')
                        key.data.extend(chunk)
            remaining = timeout-(time.monotonic()-started)
            if remaining <= 0:
                failure('ISOLATION_LIMIT_EXCEEDED', 'container command exceeded its deadline', limit='wall')
            return EngineResult(process.wait(timeout=remaining), bytes(output), bytes(errors))
        finally:
            selector.close()
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                if not stream.closed:
                    stream.close()


class ContainerExecutor:
    isolated = True

    def __init__(self, resolver, *, admission=None, engine=None, capture_policy=None):
        self.resolver = resolver
        self.admission = admission
        self.engine = engine if engine is not None else DockerEngine()
        self.capture_policy = capture_policy
        self._retained_leases = {}
        self._uncertain_workspaces = set()

    def admit(self, document, inputs=None, *, bound=False):
        if self.admission is None:
            failure('ISOLATION_UNAVAILABLE', 'a pure qualified file-free admission policy is required')
        if inputs is None:
            return self.admission.check(copy.deepcopy(document))
        from .execution_inputs import validate_bindings, check_bound_document
        validate_bindings(inputs)
        admitted = self.admission.check(copy.deepcopy(document), context=inputs, bound=bound)
        if bound:
            check_bound_document(document, inputs)
        return admitted

    def plan(self, request, cancellation):
        if (request.phase not in ('capture', 'stale-check')
                or not isinstance(request.operation_id, str) or not request.operation_id
                or len(request.operation_id) > 256):
            failure('ISOLATION_UNAVAILABLE', 'planning needs a bounded trusted operation identity and phase')
        from .capabilities import digest as document_digest
        job_id = 'job-'+hashlib.sha256(request.operation_id.encode()).hexdigest()[:32]
        execution = ExecutionRequest(job_id=job_id, plan_id=request.plan_id,
            document=request.document, plan={}, document_digest=document_digest(request.document),
            plan_digest=hashlib.sha256(encoded({})).hexdigest(),
            directory=Path(request.workspace)/'runs'/job_id/'run', workspace=Path(request.workspace),
            providers=request.providers, bindings=(), stage_timeout=request.stage_timeout,
            deadline=request.deadline, locations=request.locations, inputs=request.inputs,
            operation_id=request.operation_id, planning_phase=request.phase)
        response, isolation, _ = self._exchange('plan', execution, cancellation)
        return PlanningOutcome(response, isolation)

    def recover(self, workspace):
        """Reconcile ambiguous launches only while the caller owns its workspace."""
        from .container_lifecycle import LifecycleJournal
        journal = LifecycleJournal(workspace)
        recovered = []
        for record in journal.pending(include_cleaned_plans=True):
            if record['state'] == 'cleaned':
                recovered.append(copy.deepcopy(record))
                continue
            try:
                cleanup = self._cleanup(record['name'], record['nonce'],
                    container_id=record.get('containerId'), job_id=record['jobId'],
                    action=record['action'], ambiguous_create=record.get('containerId') is None)
                journal.update(record, state='cleaned', cleanup=cleanup, recovered=True,
                               containerId=cleanup.get('containerId', record.get('containerId')))
                recovered.append(copy.deepcopy(record))
            except Exception as error:
                failure('ISOLATION_RECOVERY_FAILED', 'an interrupted container could not be reconciled',
                        job=record['jobId'], attempt=record['nonce'], cause=str(error))
        key = str(Path(workspace).resolve())
        for lease in self._retained_leases.pop(key, ()):
            lease.close()
        self._uncertain_workspaces.discard(key)
        return recovered

    def run(self, request, cancellation):
        response, isolation, publications = self._exchange('run', request, cancellation)
        return ExecutionOutcome(response, isolation)

    def verify(self, request, cancellation):
        response, isolation, publications = self._exchange('verify', request.execution,
            cancellation, receipt_digests=request.receipt_digests)
        return VerificationOutcome(response, isolation, publications)

    def _inspect(self, identity, *, deadline=None, cancellation=None):
        timeout = 15 if deadline is None else min(15, deadline-time.monotonic())
        if timeout <= 0:
            failure('ISOLATION_LIMIT_EXCEEDED', 'worker setup exceeded its deadline', limit='wall')
        result = self.engine.command(['container', 'inspect', identity],
                                     timeout=timeout, cancellation=cancellation)
        if result.returncode:
            failure('ISOLATION_ENGINE_FAILED', 'container state could not be inspected')
        records = json.loads(result.stdout)
        if not isinstance(records, list) or len(records) != 1:
            failure('ISOLATION_PROTOCOL_ERROR', 'engine returned ambiguous container state')
        return records[0]

    def _cleanup(self, name, nonce, *, container_id=None, job_id=None, action=None,
                 ambiguous_create=False):
        selection = 'id='+container_id if container_id else 'name=^/'+name+'$'
        found = self.engine.command(['container', 'ls', '-a', '--no-trunc',
            '--filter', selection, '--format', '{{.ID}}'])
        if found.returncode:
            failure('ISOLATION_CLEANUP_UNKNOWN', 'container ownership could not be inspected')
        identities = found.stdout.decode().split()
        if not identities:
            if ambiguous_create:
                failure('ISOLATION_CLEANUP_UNKNOWN',
                    'create has no durable acknowledgement; an absent name cannot rule out a late create')
            return {'removed': True, 'containerAbsent': True}
        if len(identities) != 1 or not re.fullmatch('[0-9a-f]{64}', identities[0]):
            failure('ISOLATION_CLEANUP_UNKNOWN', 'container identity is ambiguous')
        identity = identities[0]
        record = self._inspect(identity)
        labels = record.get('Config', {}).get('Labels', {})
        if (labels.get('io.schemaxis.attempt') != nonce
                or (job_id is not None and labels.get('io.schemaxis.job') != job_id)
                or (action is not None and labels.get('io.schemaxis.action') != action)):
            failure('ISOLATION_CLEANUP_UNKNOWN', 'container ownership label differs')
        if record.get('State', {}).get('Running'):
            killed = self.engine.command(['container', 'kill', identity])
            if killed.returncode:
                failure('ISOLATION_CLEANUP_UNKNOWN', 'owned container could not be killed')
        removed = self.engine.command(['container', 'rm', '--force', '--volumes', identity])
        remaining = self.engine.command(['container', 'ls', '-a', '--no-trunc',
            '--filter', 'id='+identity, '--format', '{{.ID}}'])
        if removed.returncode or remaining.returncode or remaining.stdout.strip():
            failure('ISOLATION_CLEANUP_UNKNOWN', 'container removal was not established')
        return {'removed': True, 'containerAbsent': True, 'containerId': identity}

    def _exchange(self, action, request, cancellation, receipt_digests=()):
        key = str(Path(request.workspace).resolve())
        if key in self._uncertain_workspaces:
            failure('ISOLATION_RECOVERY_REQUIRED', 'workspace has an unreconciled container attempt')
        self.admit(request.document, request.inputs, bound=request.inputs is not None)
        lease = None
        retain = False
        if request.inputs is not None:
            if self.capture_policy is None:
                failure('ISOLATION_UNAVAILABLE', 'captured inputs require an operator capture policy')
            lease = self.capture_policy.lease(request.inputs)
        try:
            if lease is not None:
                lease.recheck()
            result = self._exchange_owned(action, request, cancellation, receipt_digests)
            try:
                if lease is not None:
                    lease.recheck()
            except SchemaxisError as error:
                fault = error.fault
                raise SchemaxisError(Fault(fault.code, fault.message, fault.location, fault.phase,
                    fault.retryable, {**dict(fault.observed), 'isolation': result[1]}, fault.recovery))
            return result
        except SchemaxisError as error:
            if error.fault.code == 'ISOLATION_CLEANUP_UNKNOWN':
                self._uncertain_workspaces.add(key)
                if lease is not None:
                    self._retained_leases.setdefault(key, []).append(lease)
                    retain = True
            raise
        finally:
            if lease is not None and not retain:
                lease.close()

    def _exchange_owned(self, action, request, cancellation, receipt_digests=()):
        if request.bindings:
            failure('ISOLATION_UNAVAILABLE', 'external input bindings have no qualified staging contract')
        from .mcp_admission import materialise_workflow
        documents = ([item['document'] for item in materialise_workflow(request.document)['operations']]
                     if request.document.get('version') == 'schemaxis.workflow/1' else [request.document])
        routes = tuple(sorted({value['version'] for value in documents}))
        profile = self.resolver.resolve(request.providers, routes)
        if (request.inputs is not None and 'captured-input-planning-v1' not in profile.capabilities
                or action == 'plan' and not set(profile.capabilities).intersection(
                    ('isolated-planning-v1', 'captured-input-planning-v1'))):
            failure('ISOLATION_UNAVAILABLE', 'image lacks the qualified planning/input protocol capability')
        limits = asdict(profile.limits)
        timeout = min(profile.limits.wall_seconds, request.stage_timeout)
        if request.deadline is not None:
            timeout = min(timeout, request.deadline-time.monotonic())
        if timeout <= 0 or cancellation.is_set():
            failure('RUNNER_CANCELLED', 'job deadline or cancellation preceded launch')
        deadline = time.monotonic() + timeout
        directory = Path(request.directory)
        volume = directory.parent
        if (not directory.is_absolute() or directory != volume/'run'
                or not directory.is_relative_to(Path(request.workspace))
                or any(character in str(volume) for character in (':', ',', '\n', '\r', '\\'))):
            failure('ISOLATION_UNAVAILABLE', 'job path is incompatible with the owned mount contract')
        for path in (volume, *volume.parents):
            if path.is_symlink():
                failure('ISOLATION_UNAVAILABLE', 'owned job path traverses a symlink')
        volume.mkdir(parents=True, exist_ok=True)
        if action == 'run' and any(volume.iterdir()):
            failure('OUTPUT_EXISTS', 'isolated execution requires a fresh owned job directory')
        incoming, expected_inventory = (pack_tree(directory, limits['disk_bytes'], limits['inodes'])
                                        if action == 'verify' else (b'', {}))
        job = {'id': request.job_id, 'directory': str(directory.relative_to(request.workspace)),
               'documentDigest': request.document_digest}
        header = {'action': action, 'document': request.document, 'plan': request.plan,
            'documentDigest': request.document_digest, 'planDigest': request.plan_digest,
            'volume': str(volume), 'directory': str(directory), 'workspace': str(request.workspace),
            'timeout': timeout, 'deadlineMonotonic': deadline, 'limits': limits,
            'job': job, 'receiptDigests': receipt_digests}
        from .execution_inputs import bindings_record
        captures = request.inputs.captures if request.inputs is not None else ()
        header['inputs'] = bindings_record(request.inputs) if request.inputs is not None else None
        from .mcp_admission import FileAdmission
        if request.inputs is not None and isinstance(self.admission, FileAdmission):
            header['capturedContentPolicy'] = self.admission.captured_content_policy(request.document, request.inputs)
        for capture in captures:
            path = capture.path
            if (any(c in str(path) for c in (':', ',', '\n', '\r', '\\'))
                    or path.is_relative_to(volume) or volume.is_relative_to(path)):
                failure('ISOLATION_UNAVAILABLE', 'capture path conflicts with the job mount contract')
        if request.operation_id is not None:
            header['operationId'] = request.operation_id
        if action == 'plan':
            header['planningPhase'] = request.planning_phase
        nonce = uuid.uuid4().hex
        name = 'schemaxis-'+nonce
        tmpfs = (str(volume)+':rw,nosuid,nodev,noexec,size='+str(limits['disk_bytes'])
                 +',nr_inodes='+str(limits['inodes'])+',uid=10001,gid=10001,mode=0700')
        arguments = ['container', 'create', '--name', name, '--label', 'io.schemaxis.attempt='+nonce,
            '--label', 'io.schemaxis.job='+request.job_id,
            '--label', 'io.schemaxis.plan='+request.plan_id, '--label', 'io.schemaxis.action='+action,
            '--platform', 'linux/amd64', '--pull', 'never', '--interactive', '--network', 'none',
            '--read-only', '--user', '10001:10001', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges=true', '--cgroupns', 'private', '--ipc', 'none',
            '--memory', str(limits['memory_bytes']), '--memory-swap', str(limits['memory_bytes']),
            '--cpus', str(limits['cpus']), '--pids-limit', str(limits['pids']),
            '--ulimit', 'core=0:0', '--ulimit', 'nofile=256:256', '--log-driver', 'none',
            '--tmpfs', tmpfs, '--workdir', str(volume),
            '--env', 'HOME='+str(volume/'.home'), '--env', 'TMPDIR='+str(volume/'.tmp'),
            '--env', 'XDG_CACHE_HOME='+str(volume/'.cache'),
            *[value for capture in captures for value in ('--mount',
                'type=bind,src='+str(capture.path)+',dst='+str(capture.path)+',readonly,bind-propagation=rprivate')],
            '--entrypoint', '/usr/local/bin/python3', profile.image,
            '-I', '-B', '-m', 'schemaxis.container_worker']
        isolation = {'image': profile.image, 'qualification': profile.qualification_id,
                     'limits': limits, 'network': 'none', 'storage': 'bounded-container-tmpfs',
                     'action': action}
        if request.operation_id is not None:
            isolation['operationId'] = request.operation_id
        if action == 'plan':
            isolation['planningPhase'] = request.planning_phase
        from .container_lifecycle import LifecycleJournal
        journal = LifecycleJournal(request.workspace)
        intent = journal.begin(name=name, nonce=nonce, request=request, action=action,
                               image=profile.image, deadline=deadline)
        isolation['lifecycleRecord'] = 'container-lifecycle/'+nonce+'.json'
        original = None
        identity = None
        try:
            created = self.engine.command(arguments, timeout=min(timeout, 15), cancellation=cancellation)
            if created.returncode:
                failure('ISOLATION_LAUNCH_FAILED', 'pinned worker image could not be created')
            candidate = created.stdout.decode().strip()
            if not re.fullmatch('[0-9a-f]{64}', candidate):
                failure('ISOLATION_PROTOCOL_ERROR', 'engine did not return an exact container ID')
            identity = candidate
            journal.update(intent, state='created', containerId=identity)
            record = self._inspect(identity, deadline=deadline, cancellation=cancellation)
            self._check_config(record, profile, volume, tmpfs, nonce, captures)
            launched = time.monotonic()
            result = self.engine.command(['container', 'start', '--attach', '--interactive', identity],
                payload=frame(header, incoming), timeout=max(0, deadline-time.monotonic()), cancellation=cancellation,
                max_output=16+HEADER_LIMIT+archive_limit(limits['disk_bytes'], limits['inodes']))
            record = self._inspect(identity)
            state = record.get('State', {})
            isolation.update(containerId=identity, exitCode=state.get('ExitCode'),
                             containerExited=state.get('Running') is False,
                             supervisorWallSeconds=time.monotonic()-launched)
            if state.get('OOMKilled'):
                failure('ISOLATION_LIMIT_EXCEEDED', 'worker memory cgroup was exhausted', limit='memory')
            if state.get('ExitCode') == 124:
                failure('ISOLATION_LIMIT_EXCEEDED', 'independent worker total deadline was exhausted', limit='wall')
            if state.get('Running') is not False:
                failure('ISOLATION_CLEANUP_UNKNOWN', 'worker did not exit after its response')
            if result.returncode or state.get('ExitCode') != 0:
                failure('ISOLATION_WORKER_FAILED', 'worker exited without a completed protocol response')
            envelope, archive = unframe(result.stdout, archive_limit(limits['disk_bytes'], limits['inodes']))
            if (envelope.get('requestDigest') != digest(header) or envelope.get('action') != action
                    or envelope.get('quiescence', {}).get('remainingProcesses') != 0):
                failure('ISOLATION_PROTOCOL_ERROR', 'worker request binding or quiescence differs')
            isolation['workerObservations'] = {key: envelope.get(key) for key in
                                               ('limits', 'metrics', 'quiescence', 'wallSeconds')}
        except Exception as error:
            original = error
        finally:
            try:
                isolation['cleanup'] = self._cleanup(name, nonce, container_id=identity,
                    job_id=request.job_id, action=action, ambiguous_create=identity is None)
                journal.update(intent, state='cleaned', cleanup=isolation['cleanup'], isolation=isolation,
                               containerId=isolation['cleanup'].get('containerId', identity))
            except Exception as cleanup_error:
                try:
                    journal.update(intent, state='cleanup-unknown')
                except Exception:
                    pass  # The original durable intent still requires reconciliation.
                failure('ISOLATION_CLEANUP_UNKNOWN', 'owned container cleanup was not established',
                        isolation=isolation, cause=str(original or cleanup_error))
        if original is not None:
            if isinstance(original, SchemaxisError):
                fault = original.fault
                raise SchemaxisError(Fault(fault.code, fault.message, fault.location, fault.phase,
                    fault.retryable, {**dict(fault.observed), 'isolation': isolation}, fault.recovery))
            failure('ISOLATION_PROTOCOL_ERROR', 'worker exchange failed before a validated response',
                    isolation=isolation, cause=str(original))
        try:
            return self._consume_response(action, envelope, archive, volume, limits,
                                          expected_inventory, isolation)
        except SchemaxisError as error:
            fault = error.fault
            raise SchemaxisError(Fault(fault.code, fault.message, fault.location, fault.phase,
                fault.retryable, {**dict(fault.observed), 'isolation': isolation}, fault.recovery))
        except Exception as error:
            failure('ISOLATION_PROTOCOL_ERROR', 'worker response failed structural validation',
                    isolation=isolation, cause=str(error))

    @staticmethod
    def _consume_response(action, envelope, archive, volume, limits, expected_inventory, isolation):
        if 'fault' in envelope:
            value = envelope['fault']
            if (not isinstance(value, dict)
                    or any(not isinstance(value.get(key), str) for key in ('code', 'message', 'location', 'phase'))
                    or not isinstance(value.get('observed', {}), dict)
                    or type(value.get('retryable', False)) is not bool
                    or value.get('recovery') is not None and not isinstance(value['recovery'], str)):
                failure('ISOLATION_PROTOCOL_ERROR', 'worker fault is structurally invalid')
        elif not isinstance(envelope.get('result'), dict):
            failure('ISOLATION_PROTOCOL_ERROR', 'worker result is missing')
        actual_inventory = (unpack_tree(archive, volume, limits['disk_bytes'], limits['inodes'],
                                       validate_only=True) if archive else {})
        if action == 'plan' and (archive or actual_inventory):
            failure('ISOLATION_PROTOCOL_ERROR', 'planning cannot publish run evidence', isolation=isolation)
        if actual_inventory != envelope.get('inventory'):
            failure('ISOLATION_PROTOCOL_ERROR', 'export inventory differs from validated archive')
        if action == 'verify' and actual_inventory != expected_inventory:
            failure('VERIFICATION_FAILED', 'isolated verification changed retained evidence')
        if action == 'run' and archive:
            unpack_tree(archive, volume, limits['disk_bytes'], limits['inodes'])
        if 'fault' in envelope:
            value = envelope['fault']
            raise SchemaxisError(Fault(value['code'], value['message'], value['location'], value['phase'],
                value.get('retryable', False), {**value.get('observed', {}), 'isolation': isolation},
                value.get('recovery')))
        return envelope['result'], isolation, envelope.get('publications')

    @staticmethod
    def _check_config(record, profile, volume, tmpfs, nonce, captures=()):
        host, config = record.get('HostConfig', {}), record.get('Config', {})
        limits = profile.limits
        expected = {str(capture.path) for capture in captures}
        declared = host.get('Mounts') or []
        bound = [mount for mount in record.get('Mounts', []) if mount.get('Type') != 'tmpfs']
        def exact_mounts(mounts, declared=False):
            return (len(mounts) == len(expected)
                and {mount.get('Target' if declared else 'Destination') for mount in mounts} == expected
                and all(mount.get('Type') == 'bind'
                    and mount.get('Source') == mount.get('Target' if declared else 'Destination')
                    and (mount.get('ReadOnly') is True if declared else mount.get('RW') is False)
                    and (mount.get('BindOptions', {}).get('Propagation') == 'rprivate' if declared
                         else mount.get('Propagation') == 'rprivate') for mount in mounts))
        if (config.get('Image') != profile.image or config.get('User') != '10001:10001'
                or config.get('Labels', {}).get('io.schemaxis.attempt') != nonce
                or host.get('NetworkMode') != 'none' or host.get('ReadonlyRootfs') is not True
                or host.get('Privileged') is not False or host.get('Binds')
                or not exact_mounts(declared, True) or not exact_mounts(bound)
                or host.get('CgroupnsMode') != 'private'
                or any(mount.get('Destination') != str(volume)
                       for mount in record.get('Mounts', []) if mount.get('Type') == 'tmpfs')
                or host.get('Devices') or host.get('PidMode') or host.get('IpcMode') != 'none'
                or host.get('Memory') != limits.memory_bytes
                or host.get('MemorySwap') != limits.memory_bytes
                or host.get('PidsLimit') != limits.pids
                or host.get('NanoCpus') != int(limits.cpus*1000000000)
                or host.get('Tmpfs') != {str(volume): tmpfs.split(':', 1)[1]}
                or set(host.get('CapDrop') or ()) != {'ALL'}
                or host.get('CapAdd') or host.get('SecurityOpt') != ['no-new-privileges=true']):
            failure('ISOLATION_UNAVAILABLE', 'engine did not establish the requested hard isolation profile')
