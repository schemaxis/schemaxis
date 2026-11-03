# Copyright (C) 2026 David L F Gaden
"""Bounded dependency scheduler with verified, immutable retry attempts."""
import copy
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextvars import copy_context
import fcntl
import json
import math
import os
from pathlib import Path
import re
import threading
import time
from .artifacts import atomic_json
from .adaptors import registry
from .dispatch import allocation, cancellation_token, execution_deadline
from .jobs import Cancellation
from .errors import fail, keys
from .storage import prepare_run_directory
from .run_paths import owned_path


def integer(value, name, minimum=1):
    if type(value) is not int or value < minimum:
        fail('INVALID_EXECUTION', 'expected integer >= ' + str(minimum), name)
    return value


def configuration(document):
    from .adaptor_runtime import workflow_inputs
    document = workflow_inputs(document)
    settings = document.get('execution', {})
    keys(settings, ('maxWorkers', 'cpus', 'memoryMB', 'gpus'), '$.execution')
    budget = {'maxWorkers': settings.get('maxWorkers', 1), 'cpus': settings.get('cpus', os.cpu_count() or 1),
              'memoryMB': settings.get('memoryMB', 8192), 'gpus': settings.get('gpus', 1)}
    for key, value in budget.items():
        integer(value, key, 0 if key == 'gpus' else 1)
    if budget['gpus'] > 1:
        fail('UNSUPPORTED_EXECUTION', 'only one GPU slot is supported until explicit device binding is available')
    return budget


def provisional(value):
    """Legacy schema-expansion helper; not a verified workflow planning input."""
    if isinstance(value, list):
        return [provisional(item) for item in value]
    if isinstance(value, dict):
        if '$artifact' in value:
            return '/unresolved-artifact'
        return {key: provisional(item) for key, item in value.items()}
    return value


def requests(operation, budget):
    spec = operation.get('execution', {})
    keys(spec, ('threads', 'ranks', 'mpiexec', 'memoryMB', 'gpus', 'timeChunkSize'), operation['id'])
    pipeline = operation['document']
    registry.resolve(pipeline, legacy=True)
    hook = registry.route_hook(pipeline, 'resources', legacy=True)
    from .adaptor_runtime import InputProgram
    from .workflow import dependencies
    deferred = any(dependencies(pipeline))
    defaults = {}
    if deferred:
        provisional_hook = registry.route_hook(pipeline, 'provisionalResources', legacy=True)
        if provisional_hook:
            defaults = provisional_hook(pipeline, spec, operation['id'])
    elif hook:
        route = registry.resolve(pipeline, legacy=True)[1]
        for visit in InputProgram(pipeline, route).visits():
            current = hook(visit['document'], spec, operation['id'])
            for key, value in current.items(): defaults[key] = max(defaults.get(key, 0), value)
    threads = integer(spec.get('threads', defaults.get('threads', 1)), 'threads')
    ranks = integer(spec.get('ranks', 1), 'ranks')
    gpu = defaults.get('gpus', 0)
    resources = {'threads': threads, 'ranks': ranks, 'cpus': threads*ranks,
                 'memoryMB': integer(spec.get('memoryMB', 1024), 'memoryMB'),
                 'gpus': integer(spec.get('gpus', gpu), 'gpus', 0)}
    if resources['gpus'] < gpu:
        fail('INVALID_EXECUTION', 'GPU rendering needs a GPU reservation', operation['id'])
    if ranks > 1:
        from .adaptors.execution import validate_execution
        if deferred:
            # The route must support MPI now; its input-dependent checks await
            # real publications. No guessed filename enters the adaptor hook.
            if registry.route_hook(pipeline, 'validateExecution', legacy=True) is None:
                fail('UNSUPPORTED_EXECUTION', 'this adaptor has no MPI execution mode', version=pipeline.get('version'))
        else:
            validate_execution(pipeline, ranks)
        executable = spec.get('mpiexec')
        if not isinstance(executable, str) or not Path(executable).is_absolute():
            fail('INVALID_EXECUTION', 'MPI requires an explicit absolute mpiexec path', operation['id'])
        resources['mpiexec'] = executable
    for key in ('cpus', 'memoryMB', 'gpus'):
        if resources[key] > budget[key]:
            fail('RESOURCE_BUDGET_EXCEEDED', 'job cannot fit resource budget', operation['id'], resource=key)
    return resources


def work_items(document):
    from .workflow import validate, dependencies, provisional_plan
    operations = validate(document)
    budget = configuration(document)
    jobs = []
    for operation in operations:
        resources = requests(operation, budget)
        spec = operation.get('execution', {})
        pipeline = operation['document']
        chunks = [copy.deepcopy(pipeline)]
        indices = [None]
        if 'timeChunkSize' in spec:
            _, route = registry.resolve(pipeline, legacy=True)
            if not route.get('timeBatches'):
                fail('UNSUPPORTED_BATCH', 'this document does not support time visits', operation['id'])
            size = integer(spec['timeChunkSize'], 'timeChunkSize')
            times = pipeline.get('times', [0.0])
            if not isinstance(times, list) or not times or any(type(t) not in (int, float) or not math.isfinite(t) for t in times):
                fail('UNSUPPORTED_BATCH', 'time batching requires explicit finite times', operation['id'])
            provisional_plan(pipeline)
            chunks = [{**copy.deepcopy(pipeline), 'times': times[start:start+size]} for start in range(0, len(times), size)]
            indices = [list(range(start, min(start+size, len(times)))) for start in range(0, len(times), size)]
        parents = sorted({ref.get('$artifact', ref.get('$value')) for ref in dependencies(pipeline)})
        for index, (chunk, time_indices) in enumerate(zip(chunks, indices)):
            jobs.append({'id': operation['id'] + '/' + str(index), 'operation': operation['id'],
                         'batch': index, 'timeIndices': time_indices, 'document': chunk,
                         'dependencies': parents, 'resources': resources})
    return operations, budget, jobs


def verify_native(directory, expected):
    """Recheck actual artifacts, authored input and provider verification."""
    directory = Path(directory)
    if json.loads((directory/'authored.json').read_text()) != expected:
        fail('VERIFICATION_FAILED', 'attempt input differs from requested input', str(directory))
    from .adaptor_runtime import is_common
    hook = None if is_common(directory) else registry.route_hook(expected, 'verifyAttempt', legacy=True)
    if hook: hook(directory, expected)
    else: registry.verify(directory, expected)
    from .publication_metadata import verify as verify_metadata
    verify_metadata(directory)
    receipt = json.loads((directory/'verification.json').read_text())
    return receipt


def reusable_inputs(document):
    """Conservative input provenance for retries: unknown external readers rerun."""
    hook = registry.route_hook(document, 'reusableInputs', legacy=True)
    if hook is None: return None
    from .adaptor_runtime import InputProgram
    result = {}
    for visit in InputProgram(document, registry.resolve(document, legacy=True)[1]).visits():
        hashes = hook(visit['document'])
        if hashes is None: return None
        for key, value in hashes.items():
            if key in result and result[key] != value: fail('INPUT_CHANGED', 'input changed while collecting study provenance', key)
            result[key] = value
    return result


def retained_inputs(directory, document):
    """Read capture bindings only after successful native/whole-study verification.

    A missing hook is deliberately conservative: old providers still need their
    original inputs when saved scheduler provenance is checked.
    """
    from .adaptor_runtime import is_common
    if is_common(directory):
        receipt = json.loads((Path(directory)/'verification.json').read_text())
        maps = [retained_inputs(owned_path(directory, state['directory'], kind='directory'), state['document'])
                for state in receipt['states']]
    else:
        hook = registry.route_hook(document, 'retainedInputs', legacy=True)
        if hook is None:
            return None
        maps = [hook(Path(directory), document)]
    result = {}
    for hashes in maps:
        if hashes is None:
            return None
        if not isinstance(hashes, dict):
            fail('VERIFICATION_FAILED', 'retained input provenance must be a complete path/digest map')
        for path, digest in hashes.items():
            if (not isinstance(path, str) or not Path(path).is_absolute()
                    or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest)):
                fail('VERIFICATION_FAILED', 'retained input provenance contains an invalid path or SHA256')
            if path in result and result[path] != digest:
                fail('VERIFICATION_FAILED', 'study captured conflicting source bytes', path)
            result[path] = digest
    return result


def resolve(pipeline, completed, *, directory=None):
    handoffs = []
    def target_for(outcome):
        return (owned_path(directory, outcome['directory'], kind='directory')
                if directory is not None else Path(outcome['directory']))
    def visit(value):
        if isinstance(value, list):
            return [visit(item) for item in value]
        if not isinstance(value, dict):
            return value
        from .adaptor_runtime import output_reference, select, is_common
        if output_reference(value):
            source = value['$value']
            choices = []
            owners = []
            for outcome in completed[source]:
                target = target_for(outcome)
                receipt = verify_native(target, outcome['effective'])
                if is_common(target):
                    for state in receipt['states']:
                        child = owned_path(target, state['directory'], kind='directory')
                        choices.append(json.loads((child/'verification.json').read_text()))
                        owners.append(child)
                else:
                    choices.append(receipt)
                    owners.append(target)
            if len(choices) != 1 and 'visit' not in value:
                fail('AMBIGUOUS_VALUE', 'select an explicit producer visit', source, visits=len(choices))
            index = value.get('visit', 0)
            if type(index) is not int or not 0 <= index < len(choices):
                fail('INVALID_SELECTION', 'producer visit is absent', source)
            data = choices[index]
            if 'artifact' in value:
                artifact_index = value['artifact']
                if type(artifact_index) is not int or not 0 <= artifact_index < len(data['artifacts']):
                    fail('INVALID_SELECTION', 'producer artifact is absent', source)
                artifact = data['artifacts'][artifact_index]
                filename = owned_path(owners[index], artifact['file'])
                with filename.open('rb') as stream: payload = stream.read(8*1024*1024+1)
                if len(payload) > 8*1024*1024:
                    fail('RESOURCE_LIMIT', 'value publication exceeds 8 MiB', source)
                import hashlib
                if hashlib.sha256(payload).hexdigest() != artifact.get('sha256'):
                    fail('VERIFICATION_FAILED', 'value publication changed after verification', source)
                kind = artifact.get('kind', artifact.get('identity', {}).get('kind'))
                if kind == 'table':
                    from .tabular import parse_csv
                    data = parse_csv(payload, location=str(filename))
                elif filename.suffix.lower() == '.json':
                    from .storage import load
                    data = load(payload.decode('utf-8'))
                else:
                    fail('TYPE_MISMATCH', 'value extraction requires JSON or a numeric table publication', source)
            selected = select(data, value['path'], source)
            from .storage import digest
            handoffs.append({'from': source, 'visit': index, 'path': value['path'], 'artifact': value.get('artifact'),
                             'value': selected, 'receiptDigest': digest(choices[index])})
            return selected
        if '$artifact' in value:
            source, index = value['$artifact'], value['index']
            artifacts = []
            for outcome in completed[source]:
                receipt = verify_native(target_for(outcome), outcome['effective'])
                artifacts.extend(receipt['artifacts'])
            if index >= len(artifacts):
                fail('INVALID_SELECTION', 'artifact index exceeds output count', source)
            artifact = artifacts[index]
            kind = artifact.get('kind', artifact.get('identity', {}).get('kind'))
            allowed = registry.resolve(pipeline, legacy=True)[1].get('acceptedArtifacts', [])
            if kind not in allowed:
                fail('TYPE_MISMATCH', 'artifact kind is incompatible with consumer', source, kind=kind)
            handoffs.append({'from': source, 'index': index, 'file': artifact['file'], 'sha256': artifact.get('sha256')})
            return artifact['file']
        return {key: visit(item) for key, item in value.items()}
    return visit(pipeline), handoffs


def run_native(document, directory, roots=None, blender=None, timeout=300, freecad=None, *, locations=None):
    return registry.run(document, directory, locations=locations, roots=roots, blender=blender, freecad=freecad, timeout=timeout)


def execute(document, directory, *, roots=None, blender=None, freecad=None, timeout=300, resume=False, locations=None):
    from .configuration import location_context, locations as configured_locations
    roots, locations = copy.deepcopy(roots), copy.deepcopy(locations)
    overrides = {'roots': roots, 'blender': blender, 'freecad': freecad,
                 **{key: value for key, value in (locations or {}).items() if value is not None}}
    with location_context(overrides):
        resolved_locations = configured_locations()
        return _execute_configured(document, directory, roots=roots, blender=blender, freecad=freecad,
                                   timeout=timeout, resume=resume, locations=locations,
                                   resolved_locations=resolved_locations)


def _execute_configured(document, directory, *, roots, blender, freecad, timeout, resume,
                        locations, resolved_locations):
    operations, budget, jobs = work_items(document)
    directory = Path(directory).expanduser().absolute()
    if resume:
        if not directory.is_dir() or json.loads((directory/'authored.json').read_text()) != document:
            fail('RESUME_MISMATCH', 'resume requires the unchanged authored workflow', str(directory))
    else:
        directory = prepare_run_directory(directory, document)
    from .schema_snapshots import capture_run, verify_run
    if resume:
        verify_run(directory)
    else:
        capture_run(directory, document)
    with (directory/'.coordinator.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail('WORKFLOW_BUSY', 'another coordinator owns this output directory', str(directory))
        return _execute(document, directory, operations, budget, jobs, roots, blender, timeout,
                        resume, freecad, locations, resolved_locations)


def _execute(document, directory, operations, budget, jobs, roots, blender, timeout, resume, freecad,
             locations, resolved_locations):
    started = time.monotonic()
    cancel = Cancellation(parent=cancellation_token())
    outcomes, completed, running = {}, {}, {}
    pending = list(jobs)
    failure = None
    status = {'executionVersion': 2, 'status': 'incomplete', 'verified': False, 'budget': budget,
              'jobs': [], 'seconds': 0}
    atomic_json(directory/'execution-plan.json', {'budget': budget, 'jobs': jobs})

    def save():
        status['jobs'] = [outcomes[job['id']] for job in jobs if job['id'] in outcomes]
        status['pendingJobs'] = [job['id'] for job in pending]
        status['runningJobs'] = [job['id'] for job in running.values()]
        status['seconds'] = time.monotonic()-started
        atomic_json(directory/'result.json', status)

    def worker(job, effective, handoffs, target):
        from .configuration import location_context
        stamp = time.time()
        input_hashes = reusable_inputs(effective)
        with location_context(resolved_locations), allocation(job['resources'], cancel), execution_deadline(timeout):
            result = run_native(effective, target, roots, blender, timeout, freecad, **({"locations": locations} if locations is not None else {}))
            verify_started = time.monotonic()
            verify_native(target, effective)
            captured = retained_inputs(target, effective)
            if captured is not None and captured != input_hashes:
                fail('INPUT_CHANGED', 'captured source bytes differ from scheduled inputs', job['id'])
            verification_seconds = time.monotonic()-verify_started
        if reusable_inputs(effective) != input_hashes:
            fail('INPUT_CHANGED', 'input files changed during execution', job['id'])
        receipt = json.loads((target/'verification.json').read_text())
        if job['resources']['ranks'] > 1 and receipt.get('ranks') != job['resources']['ranks']:
            fail('MPI_SIZE_MISMATCH', 'receipt does not evidence allocated ranks', job['id'])
        outcome = {**job, 'directory': str(target), 'effective': effective, 'handoffs': handoffs,
                   'result': result, 'status': 'succeeded', 'startedAt': stamp,
                   'seconds': time.time()-stamp, 'verificationSeconds': verification_seconds, 'reused': False, 'inputHashes': input_hashes}
        atomic_json(target/'job.json', outcome)
        return outcome

    def refresh():
        for operation in operations:
            members = [job for job in jobs if job['operation'] == operation['id']]
            if all(outcomes.get(job['id'], {}).get('status') == 'succeeded' for job in members):
                completed[operation['id']] = [outcomes[job['id']] for job in members]

    save()
    with ThreadPoolExecutor(max_workers=budget['maxWorkers']) as pool:
        try:
            while pending or running:
                if cancel.is_set() and failure is None:
                    fail('RUNNER_CANCELLED', 'workflow cancelled; retained attempts may be incomplete')
                refresh()
                used = {key: sum(job['resources'][key] for job in running.values()) for key in ('cpus', 'memoryMB', 'gpus')}
                for job in list(pending):
                    if failure or len(running) >= budget['maxWorkers']:
                        break
                    if not set(job['dependencies']) <= completed.keys():
                        continue
                    with execution_deadline(timeout):
                        effective, handoffs = resolve(job['document'], completed)
                    if job['dependencies']:
                        actual = requests({'id': job['operation'], 'document': effective,
                                           'execution': {k:v for k,v in job['resources'].items() if k in ('threads','ranks','memoryMB','gpus','mpiexec')}}, budget)
                        if actual != job['resources']:
                            fail('INVALID_EXECUTION', 'resolved inputs need a different declared allocation', job['id'])
                        if job['timeIndices'] is not None:
                            # Validate limits over the complete authored time
                            # sequence, not only its smaller dispatched chunks.
                            original = next(op['document'] for op in operations if op['id'] == job['operation'])
                            with execution_deadline(timeout):
                                full, _ = resolve(original, completed)
                            registry.plan(full, legacy=True)
                        registry.plan(effective, legacy=True)
                    parent = directory/job['operation']/('batch-' + str(job['batch']))
                    parent.mkdir(parents=True, exist_ok=True)
                    attempts = sorted(parent.glob('attempt-*'))
                    reused = None
                    if resume:
                        input_hashes = reusable_inputs(effective)
                        for attempt in reversed(attempts):
                            try:
                                candidate = json.loads((attempt/'job.json').read_text())
                                if not isinstance(candidate, dict) or candidate.get('status') != 'succeeded':
                                    continue
                                if input_hashes is None or candidate.get('inputHashes') != input_hashes:
                                    continue
                                if any(candidate.get(key) != job[key] for key in job) or candidate.get('effective') != effective:
                                    continue
                                if candidate.get('directory') != str(attempt) or candidate.get('handoffs') != handoffs:
                                    continue
                                with execution_deadline(timeout):
                                    receipt = verify_native(attempt, effective)
                                    captured = retained_inputs(attempt, effective)
                                    if captured is not None and captured != input_hashes:
                                        continue
                                if job['resources']['ranks'] > 1 and receipt.get('ranks') != job['resources']['ranks']:
                                    continue
                                reused = {**candidate, 'reused': True}
                                break
                            except (OSError, ValueError, KeyError):
                                continue
                            except Exception as error:
                                from schemaxis.core.faults import SchemaxisError
                                if not isinstance(error, SchemaxisError):
                                    raise
                                if error.fault.code in ('RUNNER_CANCELLED', 'RUNNER_TIMED_OUT'):
                                    # An interrupted check is not evidence that
                                    # an old result needs a new native attempt.
                                    raise
                    if reused:
                        outcomes[job['id']] = reused
                        pending.remove(job)
                        save()
                        continue
                    if any(used[key]+job['resources'][key] > budget[key] for key in used):
                        continue
                    number = max([int(p.name.split('-')[-1]) for p in attempts] or [0])+1
                    target = parent/('attempt-' + str(number).zfill(4))
                    # Each worker owns a fresh Context. This also preserves an
                    # enclosing study deadline without sharing mutable state.
                    future = pool.submit(copy_context().run, worker, job, effective, handoffs, target)
                    running[future] = job
                    pending.remove(job)
                    save()
                    for key in used:
                        used[key] += job['resources'][key]
                if not running:
                    if failure:
                        break
                    if pending:
                        refresh()
                        if not any(set(job['dependencies']) <= completed.keys() for job in pending):
                            fail('SCHEDULER_STALLED', 'no dependency-ready job remains')
                    continue
                done, _ = wait(running, timeout=.1, return_when=FIRST_COMPLETED)
                for future in done:
                    job = running.pop(future)
                    try:
                        outcomes[job['id']] = future.result()
                    except Exception as error:
                        outcomes[job['id']] = {**job, 'status': 'failed', 'fault': str(error)}
                        if failure is None:
                            failure = error
                            cancel.set()
                    save()
            if failure:
                raise failure
            if cancel.is_set():
                fail('RUNNER_CANCELLED', 'workflow cancelled before completion was recorded')
            from .publication_metadata import publish_artifacts
            aggregate = [artifact for job in jobs
                         for artifact in json.loads((Path(outcomes[job['id']]['directory'])/'verification.json').read_text())['artifacts']]
            publish_artifacts(directory, aggregate)
            status.update(status='succeeded', verified=True)
            save()
        except BaseException as error:
            cancel.set()
            # Workers retain their own attempt evidence; preserve successful completions.
            for future, job in list(running.items()):
                try:
                    outcomes[job['id']] = future.result()
                except BaseException:
                    pass
            status.update(status='failed', verified=False, fault=str(error))
            save()
            raise
    return status


def verify(directory):
    directory = Path(directory).absolute()
    from .schema_snapshots import verify_run
    verify_run(directory)
    document = json.loads((directory/'authored.json').read_text())
    operations, budget, jobs = work_items(document)
    saved = json.loads((directory/'result.json').read_text())
    if saved.get('status') != 'succeeded' or saved.get('verified') is not True:
        fail('INCOMPLETE_EXECUTION', 'workflow is incomplete', str(directory))
    outcomes = saved.get('jobs', [])
    if [item.get('id') for item in outcomes] != [job['id'] for job in jobs]:
        fail('VERIFICATION_FAILED', 'job membership/order differs')
    completed = {}
    count = 0
    aggregate = []
    for job, outcome in zip(jobs, outcomes):
        if outcome.get('status') != 'succeeded' or any(outcome.get(key) != job[key] for key in job):
            fail('VERIFICATION_FAILED', 'job identity or allocation differs', job['id'])
        effective, handoffs = resolve(job['document'], completed, directory=directory)
        target = owned_path(directory, outcome['directory'], kind='directory')
        parent = directory/job['operation']/('batch-'+str(job['batch']))
        if target.parent != parent or not re.fullmatch('attempt-[0-9]+', target.name) or target.resolve().parent != parent.resolve():
            fail('VERIFICATION_FAILED', 'attempt escaped its job directory', job['id'])
        if outcome.get('effective') != effective or outcome.get('handoffs') != handoffs:
            fail('VERIFICATION_FAILED', 'job handoff differs', job['id'])
        receipt = verify_native(target, effective)
        captured = retained_inputs(target, effective)
        if captured is not None:
            if captured != outcome.get('inputHashes'):
                fail('VERIFICATION_FAILED', 'job input hashes differ from verified retained inputs', job['id'])
        elif outcome.get('inputHashes') is not None and reusable_inputs(effective) != outcome['inputHashes']:
            fail('VERIFICATION_FAILED', 'job source input changed', job['id'])
        if job['resources']['ranks'] > 1 and receipt.get('ranks') != job['resources']['ranks']:
            fail('VERIFICATION_FAILED', 'MPI rank evidence differs', job['id'])
        aggregate.extend(receipt['artifacts'])
        count += len(receipt['artifacts'])
        completed.setdefault(job['operation'], []).append(outcome)
    from .publication_metadata import verify as verify_metadata
    verify_metadata(directory, aggregate)
    return {'verified': True, 'jobs': len(jobs), 'operations': len(operations), 'artifacts': count}
