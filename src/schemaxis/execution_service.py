# Copyright (C) 2026 David L F Gaden
"""Durable agent lifecycle over existing registry/workflow execution and receipts.

Captured requests use the existing authored JSON model. This is a service/job
façade, not another graph evaluator, native runner or editable document model.
"""
import base64
import copy
import csv
import io
import fcntl
import json
import math
import re
from pathlib import Path
import threading
import time
import uuid

from .adaptors import registry
from .artifacts import file_digest
from .capabilities import CapabilityCatalogue, digest
from .storage import atomic, encoded, load, AtomicPublicationError
from .core.faults import SchemaxisError, Fault
from .jobs import SerialJobs, Cancellation
from .observations import bounded, at_pointer, fail
from . import workflow

PROTOCOL = 'schemaxis.agent/1'
DEFAULT_BUDGET = {'maxAttempts': 4, 'maxRepeatedFailures': 2, 'maxElapsedSeconds': 600,
                  'timeoutPerStageSeconds': 120}
TERMINAL = {'succeeded', 'failed', 'cancelled', 'interrupted'}


def error_fault(error):
    if isinstance(error, SchemaxisError):
        return error.fault.to_dict()
    return Fault('EXECUTION_ERROR', str(error), '$', 'agent',
                 recovery='Inspect retained job evidence before retrying.').to_dict()


class ExecutionService:
    def __init__(self, workspace, *, locations=None, executor=None):
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.closed = False
        self.locations = copy.deepcopy(locations)
        from .execution_backends import LocalExecutor
        self.executor = executor if executor is not None else LocalExecutor()
        self.isolation_recovery = []
        self._input_leases = {}
        self._owner = (self.workspace/'agent.lock').open('a+b')
        self.runner = SerialJobs()
        self._catalogue = None
        self._authoring = None
        self._inspection = None
        try:
            try:
                fcntl.flock(self._owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                fail('WORKSPACE_LOCKED', 'another agent service owns this workspace')
            path = self.workspace/'agent.json'
            if path.exists():
                try:
                    envelope = load(path.read_text())
                except (OSError, SchemaxisError):
                    fail('RECOVERY_FAILED', 'agent state is unreadable or malformed')
                if (not isinstance(envelope, dict) or envelope.get('version') != 1
                        or envelope.get('digest') != digest(envelope.get('state'))):
                    fail('RECOVERY_FAILED', 'agent state checksum or version differs')
                self.state = envelope['state']
                if not isinstance(self.state, dict) or set(self.state) not in ({'tasks', 'plans', 'jobs', 'resources'}, {'tasks', 'plans', 'jobs', 'resources', 'planningOperations'}):
                    fail('RECOVERY_FAILED', 'agent state shape differs')
                self.state.setdefault('planningOperations', {})
                self._validate_state()
                recovered = copy.deepcopy(self.state)
                for record in recovered['jobs'].values():
                    if record['status'] not in TERMINAL:
                        record.update(status='interrupted', verified=False, nativeState='unknown',
                                      fault=error_fault(SchemaxisError(Fault('INTERRUPTED',
                                          'service owner exited before job completion', '$', 'agent',
                                          recovery='Inspect retained evidence; this attempt was not resumed automatically.'))))
                self._commit(recovered)
            else:
                self.state = {'tasks': {}, 'plans': {}, 'jobs': {}, 'resources': {}, 'planningOperations': {}}
                self._commit(self.state)
            if getattr(self.executor, 'isolated', False):
                if not callable(getattr(self.executor, 'recover', None)):
                    fail('ISOLATION_RECOVERY_REQUIRED', 'isolated owner requires durable cleanup recovery')
                capture_error = None
                for operation in self.state['planningOperations'].values():
                    job = self.state['jobs'].get(operation.get('jobId'), {})
                    if operation['status'] in ('intent', 'running', 'interrupted') or job.get('status') == 'interrupted':
                        from .execution_inputs import bindings_from_record
                        inputs = bindings_from_record(operation['inputs']) if operation.get('inputs') is not None else None
                        try:
                            self._hold_inputs(operation['operationId'], inputs)
                        except SchemaxisError as error:
                            capture_error = error
                # A missing or tampered input must not prevent exact owned
                # container cleanup. Preserve the input fault after recovery.
                self.isolation_recovery = self.executor.recover(self.workspace)
                if capture_error is not None: raise capture_error
            self._recover_planning_operations()
            for identity in list(self._input_leases): self._release_inputs(identity)
        except Exception:
            self.runner.close()
            # Construction failed before an owner became available. Durable
            # operation records still fence retry; a later owner must recover.
            for lease in self._input_leases.values(): lease.close()
            self._input_leases.clear()
            self._owner.close()
            self.closed = True
            raise

    def _validate_state(self):
        def require(condition):
            if not condition: fail('RECOVERY_FAILED', 'agent state relationships are invalid')
        try:
            state = self.state
            require(all(isinstance(state[key], dict) for key in state))
            for identity, task in state['tasks'].items():
                require(isinstance(task, dict))
                require(identity == task['id'] and type(task['revision']) is int and task['revision'] >= 0)
                require(type(task['attempts']) is int and task['attempts'] >= 0)
                require(isinstance(task['budget'], dict) and set(task['budget']) == set(DEFAULT_BUDGET))
                require(isinstance(task['authorisation']['allowedProviders'], list))
            for identity, plan in state['plans'].items():
                require(isinstance(plan, dict))
                require(plan['id'] == identity and plan['task'] in state['tasks'])
                require(type(plan['revision']) is int and 0 < plan['revision'] <= state['tasks'][plan['task']]['revision'])
                for section in ('document', 'plan'):
                    require(isinstance(plan[section]['file'], str) and isinstance(plan[section]['sha256'], str))
                if plan.get('inputs') is not None:
                    from .execution_inputs import bindings_from_record
                    bindings_from_record(plan['inputs'])
            for identity, operation in state['planningOperations'].items():
                require(isinstance(operation, dict) and operation['operationId'] == identity)
                require(operation['taskId'] in state['tasks'] and operation['phase'] in ('capture', 'stale-check'))
                require(operation['status'] in ('intent', 'running', 'succeeded', 'failed', 'interrupted'))
                require(isinstance(operation['requestDigest'], str))
                if operation['phase'] == 'stale-check': require(operation['planId'] in state['plans'])
                if operation['status'] == 'succeeded' and operation['phase'] == 'capture':
                    require(operation['planId'] in state['plans'])
            for identity, job in state['jobs'].items():
                require(isinstance(job, dict))
                require(identity == job['id'] and job['plan'] in state['plans'] and job['task'] in state['tasks'])
                require(job['status'] in TERMINAL | {'running', 'cancellation-requested'})
            for identity, resource in state['resources'].items():
                require(isinstance(resource, dict))
                require(identity == resource['id'] and resource['job'] in state['jobs'])
        except (TypeError, KeyError):
            fail('RECOVERY_FAILED', 'agent state relationships are invalid')

    @property
    def catalogue(self):
        if self._catalogue is None:
            self._catalogue = CapabilityCatalogue()
        return self._catalogue

    def adaptor_context(self, version, **page):
        from .adaptor_delivery import context
        return context(version, **page)

    @property
    def schedules(self):
        """Control durable triggers without owning their independent worker."""
        if self.closed:
            fail('SESSION_CLOSED', 'open a new service owner')
        from .scheduler import SchedulerStore
        return SchedulerStore(self.workspace/'schedules')

    def schedule_create(self, spec):
        return self.schedules.create(spec)

    def schedule_preview(self, spec, count=5):
        return self.schedules.preview(spec, count=count)

    def schedule_list(self):
        return self.schedules.list()

    def schedule_get(self, schedule_id):
        return self.schedules.get(schedule_id)

    def schedule_update(self, schedule_id, expected_revision, changes):
        return self.schedules.update(schedule_id, expected_revision, changes)

    def schedule_pause(self, schedule_id, expected_revision):
        return self.schedules.pause(schedule_id, expected_revision)

    def schedule_resume(self, schedule_id, expected_revision):
        return self.schedules.resume(schedule_id, expected_revision)

    def schedule_cancel(self, schedule_id, expected_revision):
        return self.schedules.cancel(schedule_id, expected_revision)

    def schedule_delete(self, schedule_id, expected_revision):
        return self.schedules.delete(schedule_id, expected_revision)

    def prepare_template(self, filename, values, planning=False):
        """Bind an exact template case; execution still requires an ordinary plan.

        This is a host-only read. The returned provenance is not a native receipt
        and is not silently inserted into an editable authoring document.
        """
        from .workflow_templates import prepare_template
        with self.lock:
            if self.closed:
                fail('SESSION_CLOSED', 'open a new service owner')
            if type(planning) is not bool:
                fail('INVALID_ARGUMENT', 'planning must be a boolean')
            return prepare_template(filename, values, planning=planning)

    @property
    def authoring(self):
        if self.closed:
            fail('SESSION_CLOSED', 'open a new service owner')
        if self._authoring is None:
            from .console_session import AdaptorConsoleSession
            self._authoring = AdaptorConsoleSession(self.workspace/'authoring')
        return self._authoring

    @property
    def inspection(self):
        if self.closed:
            fail('SESSION_CLOSED', 'open a new service owner')
        if self._inspection is None:
            from .resource_inspection import InspectionStore
            self._inspection = InspectionStore(self.authoring.workspace)
        return self._inspection

    def inspection_workspace(self, preset=None, resource_id=None):
        with self.lock:
            return self.inspection.workspace(preset, resource_id)

    def inspection_resources(self, **page):
        with self.lock:
            return self.inspection.resources(**page)

    def capture_inspection(self, filename, kind, resource_id=None, expected_revision=None):
        with self.lock:
            return self.inspection.capture(filename, kind, resource_id, expected_revision)

    def inspect_snapshot(self, resource_id, revision, view, offset=0, limit=50, columns=None, x_column=None, y_column=None):
        with self.lock:
            return self.inspection.inspect(resource_id, revision, view, offset, limit, columns, x_column, y_column)

    def reference_snapshot(self, resource_id, revision, kind, selection):
        with self.lock:
            return self.inspection.reference(resource_id, revision, kind, selection)

    def inspect_selection(self, reference_id, **page):
        with self.lock:
            return self.inspection.inspect_reference(reference_id, **page)

    def selections(self, **page):
        with self.lock:
            session = self.authoring
            refs = self.inspection.references.list(session.active_document, session._record['revision'], self.inspection.revisions())
            return bounded(refs, 'selections', **page)

    def snapshot_resource(self, resource_id, kind):
        with self.lock:
            resource = copy.deepcopy(self._resource(resource_id))
            if resource['bytes'] > 1024*1024:
                fail('INSPECTION_LIMIT', 'structured snapshots are limited to one MiB')
            with (self.workspace/resource['file']).open('rb') as stream:
                data = stream.read(1024*1024+1)
            self._resource(resource_id)
            from .resource_inspection import sha
            if sha(data) != resource['sha256']:
                fail('RESOURCE_CHANGED', 'captured bytes differ from the verified publication')
            return self.inspection.capture_bytes(data, kind, resource['name'],
                {'kind': 'verified-publication', 'resource': resource['id'], 'job': resource['job'],
                 'documentDigest': resource['documentDigest'], 'receiptSha256': resource['receiptSha256'],
                 'sha256': resource['sha256'], 'verification': 'verified at snapshot capture; subsequent inspection is historical evidence'})

    def _draft_session(self, document_id, expected_revision):
        from .authoring import check
        session = self.authoring
        record = session._state['documents'].get(document_id)
        if record is None:
            fail('UNKNOWN_DOCUMENT', 'document is not in the authoring workspace')
        check(record, document_id, document_id, expected_revision)
        if session.active_document != document_id:
            session.activate(document_id)
        return session

    def workflow_graph(self, document_id, expected_revision, **page):
        from .workflow_authoring import observe
        with self.lock:
            return observe(self._draft_session(document_id, expected_revision), document_id, expected_revision, **page)

    def rewire_workflow(self, document_id, expected_revision, pointer, source, artifact_index):
        from .workflow_authoring import rewire
        with self.lock:
            return rewire(self._draft_session(document_id, expected_revision), document_id, expected_revision, pointer, source, artifact_index)

    def create_workflow_design(self, document_id, expected_revision):
        from .workflow_authoring import create_design
        with self.lock:
            return create_design(self._draft_session(document_id, expected_revision), document_id, expected_revision)

    def connect_workflow(self, document_id, expected_revision, connection):
        from .workflow_authoring import edit_design
        with self.lock:
            return edit_design(self._draft_session(document_id, expected_revision), document_id, expected_revision,
                               'connect', connection=connection)

    def disconnect_workflow(self, document_id, expected_revision, connection_id):
        from .workflow_authoring import edit_design
        with self.lock:
            return edit_design(self._draft_session(document_id, expected_revision), document_id, expected_revision,
                               'disconnect', connection_id=connection_id)

    def configure_workflow_feedback(self, document_id, expected_revision, loop_id, config):
        from .workflow_authoring import edit_design
        with self.lock:
            return edit_design(self._draft_session(document_id, expected_revision), document_id, expected_revision,
                               'configure', loop_id=loop_id, config=config)

    def compile_workflow_design(self, document_id, expected_revision):
        from .workflow_authoring import compile_design
        with self.lock:
            return compile_design(self._draft_session(document_id, expected_revision), document_id, expected_revision)

    def reference_workflow(self, document_id, expected_revision, operation_id):
        from .workflow_authoring import reference
        with self.lock:
            session = self._draft_session(document_id, expected_revision)
            return reference(session, self.inspection.references, document_id, expected_revision, operation_id)

    def create_draft(self, provider, name='Untitled'):
        with self.lock:
            self.authoring.new(name, provider)
            return self.authoring.draft()

    def list_drafts(self, **page):
        with self.lock:
            entries = [{'document': key, 'name': value['name'], 'provider': value['provider'],
                        'revision': value['revision'], 'valid': not bool(value.get('diagnostics'))}
                       for key, value in self.authoring._state['documents'].items()]
            return bounded(entries, 'drafts', **page)

    def draft(self, document_id, expected_revision, offset=0, length=4096):
        with self.lock:
            return self._draft_session(document_id, expected_revision).draft(offset=offset, length=length)

    def locate_draft(self, document_id, expected_revision, pointer=None, offset=None):
        with self.lock:
            return self._draft_session(document_id, expected_revision).locate_source(
                document_id, expected_revision, pointer, offset)

    def edit_draft(self, document_id, expected_revision, source, format=None):
        with self.lock:
            return self._draft_session(document_id, expected_revision).edit_source(source, document_id, expected_revision, format=format)

    def patch_draft(self, document_id, expected_revision, edits):
        with self.lock:
            return self._draft_session(document_id, expected_revision).patch(edits, document_id, expected_revision)

    def undo_draft(self, document_id, expected_revision):
        with self.lock:
            session = self._draft_session(document_id, expected_revision)
            session.undo()
            return session.draft()

    def redo_draft(self, document_id, expected_revision):
        with self.lock:
            session = self._draft_session(document_id, expected_revision)
            session.redo()
            return session.draft()

    def draft_command(self, document_id, expected_revision, line):
        # Agent authoring has no native command escape around task budgets.
        import shlex
        if not isinstance(line, str) or len(line) > 100000:
            fail('INVALID_COMMAND', 'use a bounded authored command')
        try:
            parts = shlex.split(line, comments=True)
        except ValueError:
            fail('INVALID_COMMAND', 'malformed command quoting')
        if not parts or parts[0].lower() not in ('add', 'set', 'remove', 'show', 'select', 'undo', 'redo', 'patch', 'source'):
            fail('UNSUPPORTED_COMMAND', 'use authored edits here; native execution requires a captured task plan')
        with self.lock:
            session = self._draft_session(document_id, expected_revision)
            session.execute(line, document_id=document_id, expected_revision=expected_revision)
            return session.draft()

    def open_draft(self, document_id, expected_revision, filename):
        with self.lock:
            session = self._draft_session(document_id, expected_revision)
            session.open(filename)
            return session.draft()

    def write_draft(self, document_id, expected_revision, filename=None):
        with self.lock:
            return self._draft_session(document_id, expected_revision).write_source(document_id, expected_revision, filename)

    def plan_draft(self, task_id, expected_revision, document_id, draft_revision, bindings=None):
        with self.lock:
            session = self._draft_session(document_id, draft_revision)
            draft = session.draft()
            return self._plan(task_id, session.document, expected_revision, bindings,
                {'document': document_id, 'revision': draft_revision, 'sourceDigest': draft['sourceDigest']})

    def _commit(self, state):
        if self.closed:
            fail('SESSION_CLOSED', 'open a new service owner')
        path = self.workspace/'agent.json'
        payload = encoded({'version': 1, 'state': state, 'digest': digest(state)})
        try:
            atomic(path, payload)
        except AtomicPublicationError:
            # Match console ownership semantics: published revisions cannot be reused.
            try:
                matches = path.read_bytes() == payload
            except OSError:
                matches = False
            if matches:
                self.state = state
            else:
                self.closed = True
            raise
        self.state = state

    def _get(self, section, identity):
        if self.closed:
            fail('SESSION_CLOSED', 'open a new service owner')
        if not isinstance(identity, str) or identity not in self.state[section]:
            fail('UNKNOWN_' + section[:-1].upper(), 'unknown ' + section[:-1] + ' identity')
        return self.state[section][identity]

    def _write(self, name, value):
        path = self.workspace/name
        atomic(path, encoded(value), exclusive=True)
        return {'file': name, 'sha256': file_digest(path)}

    def _read(self, reference):
        path = (self.workspace/reference['file']).resolve()
        if not path.is_relative_to(self.workspace) or not path.is_file() or file_digest(path) != reference['sha256']:
            fail('EVIDENCE_CHANGED', 'retained request or evidence changed')
        return load(path.read_text())

    def create_task(self, objective, allowed_providers, budget=None):
        if not isinstance(objective, str) or not objective.strip() or len(objective) > 2000:
            fail('INVALID_OBJECTIVE', 'objective must be nonempty and at most 2000 characters')
        if (not isinstance(allowed_providers, list) or not allowed_providers
                or any(not isinstance(p, str) or p not in registry.ADAPTORS for p in allowed_providers)):
            fail('INVALID_AUTHORISATION', 'supply registered providers authorised by the caller')
        budget = {} if budget is None else budget
        if not isinstance(budget, dict) or set(budget)-set(DEFAULT_BUDGET):
            fail('INVALID_BUDGET', 'unknown budget fields', fields=list(DEFAULT_BUDGET))
        budget = {**DEFAULT_BUDGET, **budget}
        for key in ('maxAttempts', 'maxRepeatedFailures'):
            if type(budget[key]) is not int or not 1 <= budget[key] <= 100:
                fail('INVALID_BUDGET', key + ' must be 1..100')
        for key in ('maxElapsedSeconds', 'timeoutPerStageSeconds'):
            if type(budget[key]) not in (int, float) or not math.isfinite(budget[key]) or not 0 < budget[key] <= 86400:
                fail('INVALID_BUDGET', key + ' must be finite, positive and <=86400')
        identity = 'task-' + uuid.uuid4().hex
        with self.lock:
            state = copy.deepcopy(self.state)
            state['tasks'][identity] = {'id': identity, 'objective': objective, 'revision': 0,
                'authorisation': {'source': 'caller', 'allowedProviders': sorted(set(allowed_providers))},
                'budget': budget, 'attempts': 0, 'createdAt': time.time(), 'startedAt': None}
            self._commit(state)
            return copy.deepcopy(state['tasks'][identity])

    def task(self, task_id):
        with self.lock:
            return copy.deepcopy(self._get('tasks', task_id))

    @staticmethod
    def _providers(document):
        docs = [o['document'] for o in workflow.validate(document)] if document.get('version') == 'schemaxis.workflow/1' else [document]
        return sorted({registry.resolve(d)[0] for d in docs})

    def _bind(self, document, bindings):
        if not isinstance(bindings, dict):
            fail('INVALID_BINDING', 'bindings must map existing document JSON pointers to resource IDs')
        if bindings and document.get('version') == 'schemaxis.workflow/1':
            fail('UNSUPPORTED_BINDING', 'workflow handoffs use existing $artifact references; external bindings currently target standalone documents')
        resources = []
        for pointer, identity in bindings.items():
            if not pointer or not isinstance(pointer, str):
                fail('INVALID_BINDING', 'binding requires a non-root JSON pointer')
            at_pointer(document, pointer)
            resource = self._resource(identity)
            _, route = registry.resolve(document)
            if resource['kind'] not in route.get('acceptedArtifacts', []):
                fail('TYPE_MISMATCH', 'resource kind is incompatible with this consumer', resource=identity, kind=resource['kind'])
            parent, _, leaf = pointer.rpartition('/')
            container = at_pointer(document, parent)
            leaf = leaf.replace('~1', '/').replace('~0', '~')
            container[int(leaf) if isinstance(container, list) else leaf] = str(self.workspace/resource['file'])
            resources.append(identity)
        return resources

    def plan(self, task_id, document, expected_revision, bindings=None):
        return self._plan(task_id, document, expected_revision, bindings)

    @staticmethod
    def _plan_projection(record):
        return {key: copy.deepcopy(record[key]) for key in
                ('id', 'task', 'revision', 'documentDigest', 'providers', 'resources',
                 'draft', 'inputs', 'planningIsolation') if key in record}

    def _input_bindings(self, plan):
        from .execution_inputs import bindings_from_record
        return bindings_from_record(plan['inputs']) if plan.get('inputs') is not None else None

    def _hold_inputs(self, identity, inputs):
        if inputs is None:
            return
        if not getattr(self.executor, 'isolated', False):
            fail('ISOLATION_UNAVAILABLE', 'captured inputs require an isolated executor')
        policy = getattr(self.executor, 'capture_policy', None)
        from .execution_inputs import CapturePolicy
        if not isinstance(policy, CapturePolicy):
            fail('ISOLATION_UNAVAILABLE', 'captured inputs require a trusted capture policy')
        if identity in self._input_leases:
            fail('PLANNING_UNCERTAIN', 'previous capture lease has not been reconciled')
        self._input_leases[identity] = policy.lease(inputs)

    def _release_inputs(self, identity):
        lease = self._input_leases.get(identity)
        if lease is None:
            return
        # A failed cleanup retains this owner's cooperative lease. After owner
        # death, the embedding service's durable task references fence deletion.
        self.executor.recover(self.workspace)
        lease.close()
        del self._input_leases[identity]

    def _controls(self, task, cancellation, deadline, stage_timeout):
        if cancellation is not None and not isinstance(cancellation, Cancellation):
            raise ValueError('trusted cancellation must be a Cancellation')
        for value in (deadline, stage_timeout):
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                raise ValueError('trusted time bounds must be finite')
        if stage_timeout is not None and not 0 < stage_timeout <= 86400:
            raise ValueError('trusted stage timeout must be positive and bounded')
        budget = task['budget']
        remaining = budget['maxElapsedSeconds']
        if task['startedAt'] is not None:
            if time.time() < task['startedAt']:
                fail('TIME_BUDGET_EXCEEDED', 'task clock moved behind its recorded start')
            remaining -= time.time()-task['startedAt']
        maximum = time.monotonic()+remaining
        if deadline is not None: maximum = min(maximum, deadline)
        if cancellation is not None and cancellation.deadline is not None:
            maximum = min(maximum, cancellation.deadline)
        token = Cancellation(parent=cancellation, deadline=maximum)
        stage = min(budget['timeoutPerStageSeconds'], remaining, maximum-time.monotonic(),
                    stage_timeout if stage_timeout is not None else 86400)
        if token.is_set() or stage <= 0:
            fail('TIME_BUDGET_EXCEEDED' if token.expired() else 'RUNNER_CANCELLED',
                 'planning cancelled or its time budget exhausted before dispatch')
        return token, stage

    def _begin_planning(self, task, plan_id, operation_id, phase, fingerprint, inputs=None):
        from .execution_inputs import validate_identity
        validate_identity(operation_id)
        if not isinstance(plan_id, str) or not re.fullmatch(r'plan-[0-9a-f]{32}', plan_id):
            fail('INVALID_PLAN_ID', 'trusted reserved plan identity must be plan plus 32 hexadecimal digits')
        previous = self.state['planningOperations'].get(operation_id)
        if previous is not None:
            if previous['requestDigest'] != fingerprint or previous['phase'] != phase:
                fail('PLANNING_OPERATION_CONFLICT', 'operation identity already belongs to another captured request')
            return copy.deepcopy(previous)
        if sum(record['taskId'] == task['id'] for record in self.state['planningOperations'].values()) >= 100:
            fail('PLANNING_LIMIT', 'task planning operation limit is exhausted')
        if any(record['status'] in ('intent', 'running', 'interrupted')
               for record in self.state['planningOperations'].values()):
            fail('PLANNING_UNCERTAIN', 'reconcile previous planning before another native operation')
        if self._busy():
            fail('SESSION_BUSY', 'wait for active execution before native planning')
        if getattr(self.executor, 'isolated', False):
            if not callable(getattr(self.executor, 'recover', None)):
                fail('ISOLATION_RECOVERY_REQUIRED', 'isolated planning requires durable cleanup recovery')
            self.isolation_recovery = self.executor.recover(self.workspace)
            for identity in list(self._input_leases): self._release_inputs(identity)
        record = {'version': 1, 'operationId': operation_id, 'planId': plan_id, 'taskId': task['id'],
                  'phase': phase, 'status': 'intent', 'requestDigest': fingerprint,
                  'plan': None, 'fault': None, 'isolation': None, 'jobId': None,
                  'isolated': bool(getattr(self.executor, 'isolated', False))}
        state = copy.deepcopy(self.state)
        if inputs is not None:
            from .execution_inputs import bindings_record
            record['inputs'] = bindings_record(inputs)
        state['planningOperations'][operation_id] = record
        self._commit(state)
        return None

    @staticmethod
    def _replay_planning(record):
        if record['status'] == 'succeeded':
            return copy.deepcopy(record['plan'])
        if record['status'] == 'failed' and record.get('fault'):
            raise SchemaxisError(Fault(**record['fault']))
        fail('PLANNING_UNCERTAIN', 'planning operation is unresolved and will not be redispatched',
             operationId=record['operationId'])

    @staticmethod
    def _recovered_planning_isolation(operation, records):
        matches = [record for record in records if record.get('action') == 'plan'
            and record.get('operationId') == operation['operationId']
            and record.get('planId') == operation['planId']
            and record.get('planningPhase') == operation['phase']]
        if len(matches) != 1:
            return None
        isolation = matches[0].get('isolation')
        if (not isinstance(isolation, dict) or isolation.get('action') != 'plan'
                or isolation.get('operationId') != operation['operationId']
                or isolation.get('planningPhase') != operation['phase']
                or isolation.get('containerExited') is not True
                or isolation.get('cleanup', {}).get('removed') is not True
                or isolation.get('cleanup', {}).get('containerAbsent') is not True):
            return None
        return copy.deepcopy(isolation)

    def _planning_failed(self, operation_id, error, isolation=None):
        current = self.state['planningOperations'].get(operation_id)
        if current is None or current['status'] == 'succeeded' or self.closed:
            return
        info = error_fault(error)
        observed = info.get('observed', {})
        isolation = isolation or observed.get('isolation') or current.get('isolation')
        status, cleanup_fault = 'failed', None
        if getattr(self.executor, 'isolated', False):
            try:
                recovered = self.executor.recover(self.workspace)
                if isolation is None:
                    isolation = self._recovered_planning_isolation(current, recovered)
            except Exception as cleanup_error:
                status, cleanup_fault = 'interrupted', error_fault(cleanup_error)
        state = copy.deepcopy(self.state)
        state['planningOperations'][operation_id].update(status=status, fault=info,
            isolation=copy.deepcopy(isolation), cleanupFault=cleanup_fault)
        self._commit(state)

    def _recover_planning_operations(self):
        state = copy.deepcopy(self.state)
        changed = False
        for record in state['planningOperations'].values():
            if record['status'] not in ('intent', 'running', 'interrupted'):
                continue
            if record.get('isolated') and not getattr(self.executor, 'isolated', False):
                fail('ISOLATION_RECOVERY_REQUIRED', 'pending planning requires its isolated recovery backend')
            # Constructor/query recovery has already proved owned container
            # cleanup. It cannot reconstruct a missing native result or usage.
            record.update(status='failed', fault=record.get('fault') or error_fault(
                SchemaxisError(Fault('INTERRUPTED', 'planning owner exited before its outcome was committed',
                    '$', 'agent', recovery='Inspect retained planning evidence; this operation is never retried.'))))
            if record.get('isolation') is None:
                record['isolation'] = self._recovered_planning_isolation(record, self.isolation_recovery)
            changed = True
        if changed: self._commit(state)

    def planning_for_operation(self, operation_id):
        """Trusted durable outcome query; never launches or retries a planner."""
        with self.lock:
            record = self._get('planningOperations', operation_id)
            if record['status'] == 'interrupted' and not self._busy():
                if getattr(self.executor, 'isolated', False):
                    self.isolation_recovery = self.executor.recover(self.workspace)
                self._recover_planning_operations()
                for identity in list(self._input_leases): self._release_inputs(identity)
                record = self._get('planningOperations', operation_id)
            return {key: copy.deepcopy(value) for key, value in record.items() if key != 'requestDigest'}

    def _contained_plan(self, operation_id, plan_id, document, providers, inputs, token, stage, phase):
        from .execution_inputs import PlanningRequest, check_bound_document
        if not callable(getattr(self.executor, 'plan', None)):
            fail('ISOLATION_UNAVAILABLE', 'executor has no contained planning interface')
        if inputs is not None:
            check_bound_document(document, inputs)
        if getattr(self.executor, 'isolated', False):
            self.executor.admit(document, inputs, bound=inputs is not None)
        state = copy.deepcopy(self.state)
        state['planningOperations'][operation_id]['status'] = 'running'
        task = state['tasks'][state['planningOperations'][operation_id]['taskId']]
        task['startedAt'] = task['startedAt'] or time.time()
        self._commit(state)
        from .dispatch import allocation
        with allocation({}, token):
            outcome = self.executor.plan(PlanningRequest(operation_id=operation_id, plan_id=plan_id,
                workspace=self.workspace, document=copy.deepcopy(document), providers=tuple(providers),
                stage_timeout=stage, deadline=token.deadline, inputs=inputs,
                locations=copy.deepcopy(self.locations), phase=phase), token)
        isolation = copy.deepcopy(outcome.isolation)
        state = copy.deepcopy(self.state)
        state['planningOperations'][operation_id]['isolation'] = isolation or None
        self._commit(state)
        if getattr(self.executor, 'isolated', False):
            if (isolation.get('action') != 'plan' or isolation.get('operationId') != operation_id
                    or isolation.get('planningPhase') != phase or isolation.get('containerExited') is not True
                    or isolation.get('cleanup', {}).get('removed') is not True
                    or isolation.get('cleanup', {}).get('containerAbsent') is not True):
                fail('ISOLATION_FAILED', 'planner did not prove the exact operation and container cleanup', isolation=isolation)
        if token.is_set():
            fail('TIME_BUDGET_EXCEEDED' if token.expired() else 'RUNNER_CANCELLED',
                 'planning cancelled before its outcome was committed', isolation=isolation)
        if not isinstance(outcome.response, dict) or len(encoded(outcome.response)) > 1024*1024:
            fail('INVALID_PLAN', 'planner returned an invalid or oversized response', isolation=isolation)
        lease = self._input_leases.get(operation_id)
        if lease is not None: lease.recheck()
        return copy.deepcopy(outcome.response), isolation

    def plan_with_inputs(self, task_id, document, expected_revision, *, inputs=None,
                         operation_id, plan_id, cancellation=None, deadline=None, stage_timeout=None):
        """Trusted captured planning; paths never come from transport arguments."""
        from .execution_inputs import bind_document, bindings_record
        if not isinstance(document, dict) or len(encoded(document)) > 1024*1024:
            fail('INVALID_DOCUMENT', 'document must be an object no larger than one MiB')
        document = copy.deepcopy(document)
        codec = bindings_record(inputs) if inputs is not None else None
        fingerprint = digest({'task': task_id, 'plan': plan_id, 'revision': expected_revision,
                              'document': document, 'inputs': codec})
        with self.lock:
            task = self._get('tasks', task_id)
            previous = self._begin_planning(task, plan_id, operation_id, 'capture', fingerprint, inputs)
            if previous is not None: return self._replay_planning(previous)
            try:
                if type(expected_revision) is not int or expected_revision != task['revision']:
                    fail('STALE_REVISION', 'task revision changed', currentRevision=task['revision'])
                if plan_id in self.state['plans']:
                    fail('PLANNING_OPERATION_CONFLICT', 'reserved plan identity already exists')
                token, stage = self._controls(task, cancellation, deadline, stage_timeout)
                if getattr(self.executor, 'isolated', False):
                    self.executor.admit(document, inputs, bound=False)
                elif inputs is not None:
                    fail('ISOLATION_UNAVAILABLE', 'captured inputs require isolated planning')
                self._hold_inputs(operation_id, inputs)
                bound = bind_document(document, inputs) if inputs is not None else document
                providers = self._providers(bound)
                if set(providers)-set(task['authorisation']['allowedProviders']):
                    fail('SCOPE_EXCEEDED', 'document uses providers outside task authorisation', providers=providers)
                planned, isolation = self._contained_plan(operation_id, plan_id, bound, providers,
                    inputs, token, stage, 'capture')
                record = {'id': plan_id, 'task': task_id, 'revision': task['revision']+1,
                    'documentDigest': digest(bound), 'providers': providers,
                    'document': self._write('plans/'+plan_id+'/authored.json', bound),
                    'plan': self._write('plans/'+plan_id+'/plan.json', planned),
                    'bindings': {}, 'resources': [], 'inputs': codec,
                    'planningIsolation': isolation, 'planningOperation': operation_id}
                if token.is_set():
                    fail('RUNNER_CANCELLED', 'planning cancelled before capture was committed', isolation=isolation)
                state = copy.deepcopy(self.state)
                state['tasks'][task_id].update(revision=record['revision'], currentPlan=plan_id)
                state['plans'][plan_id] = record
                state['planningOperations'][operation_id].update(status='succeeded',
                    plan=self._plan_projection(record), isolation=isolation or None)
                self._commit(state)
                return self._plan_projection(record)
            except Exception as error:
                self._planning_failed(operation_id, error)
                raise
            finally:
                try:
                    self._release_inputs(operation_id)
                except Exception as error:
                    state = copy.deepcopy(self.state)
                    state['planningOperations'][operation_id].update(status='interrupted',
                        cleanupFault=error_fault(error))
                    self._commit(state)
                    raise

    def _plan(self, task_id, document, expected_revision, bindings=None, draft=None):
        if getattr(self.executor, 'isolated', False):
            if bindings or draft is not None:
                fail('ISOLATION_UNAVAILABLE', 'isolated planning requires a declared document without external or draft bindings')
            return self.plan_with_inputs(task_id, document, expected_revision,
                operation_id='planning-'+uuid.uuid4().hex, plan_id='plan-'+uuid.uuid4().hex)
        if not isinstance(document, dict) or len(encoded(document)) > 1024*1024:
            fail('INVALID_DOCUMENT', 'document must be an object no larger than one MiB')
        with self.lock:
            task = self._get('tasks', task_id)
            if type(expected_revision) is not int or expected_revision != task['revision']:
                fail('STALE_REVISION', 'task revision changed', currentRevision=task['revision'])
            document = copy.deepcopy(document)
            if getattr(self.executor, 'isolated', False):
                if bindings:
                    fail('ISOLATION_UNAVAILABLE', 'external bindings have no qualified staging contract')
                self.executor.admit(document)
            if document.get('version') in ('schemaxis.workflow-design/1', 'schemaxis.workflow-design/2'):
                from .workflow_design import compile
                compile(document)  # Gives the specific feedback fault for closed groups.
                fail('WORKFLOW_DESIGN_REQUIRES_COMPILATION',
                     'compile the design into a separate workflow draft before planning execution')
            resources = self._bind(document, {} if bindings is None else bindings)
            providers = self._providers(document)
            if set(providers)-set(task['authorisation']['allowedProviders']):
                fail('SCOPE_EXCEEDED', 'document uses providers outside task authorisation', providers=providers)
            planned = workflow.inspect_plan(document) if document.get('version') == 'schemaxis.workflow/1' else registry.plan(document)
            identity = 'plan-' + uuid.uuid4().hex
            record = {'id': identity, 'task': task_id, 'revision': task['revision']+1,
                      'documentDigest': digest(document), 'providers': providers,
                      'document': self._write('plans/'+identity+'/authored.json', document),
                      'plan': self._write('plans/'+identity+'/plan.json', planned),
                      'bindings': copy.deepcopy(bindings or {}), 'resources': resources}
            if draft is not None:
                record['draft'] = draft
            state = copy.deepcopy(self.state)
            state['tasks'][task_id].update(revision=record['revision'], currentPlan=identity)
            state['plans'][identity] = record
            self._commit(state)
            return {key: copy.deepcopy(record[key]) for key in ('id', 'task', 'revision', 'documentDigest', 'providers', 'resources', 'draft') if key in record}

    def _busy(self):
        return any(j['status'] not in TERMINAL for j in self.state['jobs'].values())

    def execute(self, plan_id, expected_revision):
        if getattr(self.executor, 'isolated', False):
            return self.execute_with_control(plan_id, expected_revision,
                operation_id='execution-'+uuid.uuid4().hex)
        return self._execute(plan_id, expected_revision)

    def execute_with_control(self, plan_id, expected_revision, *, operation_id,
                             cancellation=None, deadline=None, stage_timeout=None):
        """Trusted operation identity and cancellation; no transport schema change."""
        from .execution_inputs import validate_identity
        validate_identity(operation_id)
        fingerprint = digest({'plan': plan_id, 'revision': expected_revision})
        with self.lock:
            previous = self.state['planningOperations'].get(operation_id)
            if previous is not None:
                if previous['phase'] != 'stale-check' or previous['requestDigest'] != fingerprint:
                    fail('PLANNING_OPERATION_CONFLICT', 'execution operation belongs to another request')
                if previous['status'] == 'succeeded' and previous.get('jobId'):
                    return self.job(previous['jobId'])
                self._replay_planning(previous)
                fail('PLANNING_UNCERTAIN', 'stale check completed without a committed job; no redispatch')
            return self._execute(plan_id, expected_revision, operation_id=operation_id,
                cancellation=cancellation, deadline=deadline, stage_timeout=stage_timeout)

    def _execute(self, plan_id, expected_revision, *, operation_id=None,
                 cancellation=None, deadline=None, stage_timeout=None):
        with self.lock:
            plan = self._get('plans', plan_id)
            task = self._get('tasks', plan['task'])
            if operation_id is not None:
                self._begin_planning(task, plan_id, operation_id, 'stale-check',
                    digest({'plan': plan_id, 'revision': expected_revision}), self._input_bindings(plan))
            lease_id = operation_id
            try:
                if (type(expected_revision) is not int or expected_revision != task['revision']
                        or plan['revision'] != expected_revision or task.get('currentPlan') != plan_id):
                    fail('STALE_REVISION', 'execute requires the current captured plan', currentRevision=task['revision'])
                if plan.get('draft'):
                    source = plan['draft']
                    session = self._draft_session(source['document'], source['revision'])
                    if session.draft()['sourceDigest'] != source['sourceDigest']:
                        fail('STALE_PLAN', 'authored source changed; capture a new draft plan')
                    session.document
                if self._busy():
                    fail('SESSION_BUSY', 'wait for the active job or cancel it')
                budget = task['budget']
                if task['attempts'] >= budget['maxAttempts']:
                    fail('ATTEMPT_BUDGET_EXCEEDED', 'task attempt budget is exhausted')
                token, stage = self._controls(task, cancellation, deadline, stage_timeout)
                failed = [j for j in self.state['jobs'].values() if j['task'] == task['id']
                          and j['documentDigest'] == plan['documentDigest'] and j['status'] in ('failed', 'interrupted')]
                counts = {}
                for job in failed:
                    code = job.get('fault', {}).get('code', 'UNKNOWN')
                    counts[code] = counts.get(code, 0)+1
                if counts and max(counts.values()) >= budget['maxRepeatedFailures']:
                    fail('REPEATED_FAILURE', 'unchanged request has repeatedly failed; revise the document or start a newly authorised task')
                document = self._read(plan['document'])
                if digest(document) != plan['documentDigest']:
                    fail('EVIDENCE_CHANGED', 'captured document digest differs')
                inputs = self._input_bindings(plan)
                if getattr(self.executor, 'isolated', False):
                    self.executor.admit(document, inputs, bound=inputs is not None)
                elif inputs is not None:
                    fail('ISOLATION_UNAVAILABLE', 'captured inputs cannot fall back to host execution')
                if inputs is not None:
                    self._hold_inputs(operation_id, inputs)
                captured_plan = self._read(plan['plan'])
                for identity in plan['resources']:
                    self._resource(identity)
                if operation_id is not None:
                    current_plan, isolation = self._contained_plan(operation_id, plan_id, document,
                        plan['providers'], inputs, token, stage, 'stale-check')
                else:
                    current_plan = workflow.inspect_plan(document) if document.get('version') == 'schemaxis.workflow/1' else registry.plan(document)
                    isolation = None
                if current_plan != captured_plan:
                    fail('STALE_PLAN', 'planning changed since capture; create a new plan revision',
                         **({'isolation': isolation} if isolation else {}))
                if token.is_set():
                    fail('RUNNER_CANCELLED', 'execution cancelled after stale-plan check')
                identity = 'job-' + uuid.uuid4().hex
                state = copy.deepcopy(self.state)
                state['tasks'][task['id']].update(attempts=task['attempts']+1,
                    startedAt=state['tasks'][task['id']]['startedAt'] or time.time())
                record = {'id': identity, 'task': task['id'], 'plan': plan_id, 'revision': expected_revision,
                          'documentDigest': plan['documentDigest'], 'status': 'running', 'verified': False,
                          'nativeState': 'unobserved', 'directory': 'runs/'+identity
                              + ('/run' if getattr(self.executor, 'isolated', False) else ''),
                          'createdAt': time.time(), 'stageTimeout': stage}
                if plan.get('draft'): record['draft'] = copy.deepcopy(plan['draft'])
                if operation_id is not None:
                    record['planningOperation'] = operation_id
                    state['planningOperations'][operation_id].update(status='succeeded',
                        plan=self._plan_projection(plan), isolation=isolation or None, jobId=identity)
                state['jobs'][identity] = record
                self._commit(state)
                if operation_id in self._input_leases:
                    self._input_leases[identity] = self._input_leases.pop(operation_id)
                    lease_id = identity
                try:
                    self.runner.submit(identity, lambda: self._run(identity, document, token), token)
                except Exception as error:
                    state = copy.deepcopy(self.state)
                    state['jobs'][identity].update(status='interrupted', fault=error_fault(error))
                    self._commit(state)
                    raise
                lease_id = None  # The serial worker owns release through fresh verification.
                return copy.deepcopy(record)
            except Exception as error:
                if operation_id is not None: self._planning_failed(operation_id, error)
                raise
            finally:
                if lease_id is not None: self._release_inputs(lease_id)

    def _execution_request(self, job, document, token):
        from .execution_backends import ExecutionRequest
        plan = self.state['plans'][job['plan']]
        budget = self.state['tasks'][job['task']]['budget']
        inputs = self._input_bindings(plan)
        extra = {'inputs': inputs, 'operation_id': job.get('planningOperation'),
                 'planning_phase': 'stale-check' if job.get('planningOperation') else None}
        return ExecutionRequest(job['id'], job['plan'], copy.deepcopy(document),
            self._read(plan['plan']), plan['documentDigest'], plan['plan']['sha256'],
            self.workspace/job['directory'], self.workspace, tuple(plan['providers']),
            tuple(copy.deepcopy(self.state['resources'][key]) for key in plan['resources']),
            min(budget['timeoutPerStageSeconds'], budget['maxElapsedSeconds'], job.get('stageTimeout', 86400)),
            token.deadline, copy.deepcopy(self.locations), **extra)

    def _verify_run(self, job, document, token=None):
        target = self.workspace/job['directory']
        if getattr(self.executor, 'isolated', False):
            from .execution_backends import owned_regular
            owned_regular(target, target/'authored.json')
        if not (target/'authored.json').is_file():
            fail('VERIFICATION_FAILED', 'retained execution input is missing')
        if load((target/'authored.json').read_text()) != document:
            fail('VERIFICATION_FAILED', 'retained execution input differs from captured request')
        from .execution_backends import VerificationRequest
        if token is None:
            budget = self.state['tasks'][job['task']]['budget']
            token = Cancellation(deadline=time.monotonic()+budget['timeoutPerStageSeconds'])
        receipts = {str(target/'verification.json')}
        receipts.update(str(self.workspace/self.state['resources'][key]['receipt'])
                        for key in job.get('resources', []))
        if getattr(self.executor, 'isolated', False):
            for path in receipts:
                owned_regular(target, Path(path))
        expected = tuple((str(Path(path).relative_to(target)), file_digest(Path(path)))
                         for path in sorted(receipts) if Path(path).is_file())
        if token.is_set():
            fail('RUNNER_CANCELLED', 'verification cancelled before native dispatch')
        from .dispatch import allocation
        with allocation({}, token):
            outcome = self.executor.verify(VerificationRequest(
                self._execution_request(job, document, token), expected), token)
        if token.is_set():
            fail('RUNNER_CANCELLED', 'verification cancelled before completion was accepted')
        result = outcome.response
        if outcome.isolation:
            job.setdefault('isolation', {})['verification'] = copy.deepcopy(outcome.isolation)
        if getattr(self.executor, 'isolated', False):
            job['_isolated_publications'] = outcome.publications
        if result.get('verified') is not True:
            fail('VERIFICATION_FAILED', 'verifier did not establish success')
        return result

    def _collect(self, job, document):
        if getattr(self.executor, 'isolated', False):
            from .execution_backends import validate_publications
            return validate_publications(job.get('_isolated_publications'), job, self.workspace)
        root = self.workspace/job['directory']
        owners = [(root, None)]
        from .adaptor_runtime import is_common
        if document.get('version') == 'schemaxis.workflow/1' and not is_common(root):
            outcome = load((root/'result.json').read_text())
            if outcome.get('executionVersion') == 2:
                owners = [(Path(item['directory']), item['id']) for item in outcome['jobs']]
            else:
                owners = [(root/op['id'], op['id']) for op in workflow.validate(document)]
        resources = []
        for directory, operation in owners:
            receipt = load((directory/'verification.json').read_text())
            from .publication_metadata import verify as verify_metadata, MANIFEST
            verify_metadata(directory)
            metadata_manifest = load((directory/MANIFEST).read_text())
            companions = {str((directory/entry['file']).resolve()): entry
                          for entry in metadata_manifest['publications']}
            for artifact in receipt.get('artifacts', []):
                path = Path(artifact.get('file', '')).resolve()
                if not path.is_relative_to(root.resolve()) or not path.is_file() or Path(artifact['file']).is_symlink():
                    fail('VERIFICATION_FAILED', 'published artifact escaped its owned job')
                sha = file_digest(path)
                if artifact.get('sha256') is not None and artifact['sha256'] != sha:
                    fail('VERIFICATION_FAILED', 'published artifact digest differs')
                companion = companions[str(path)]
                metadata_path = (directory/companion['metadata']).resolve()
                metadata = load(metadata_path.read_text(encoding='utf-8'))
                resources.append({'id': 'resource-' + job['id'][4:] + '-' + str(len(resources)),
                    'job': job['id'], 'operation': operation, 'documentDigest': job['documentDigest'],
                    'file': str(path.relative_to(self.workspace)), 'name': path.name,
                    'kind': artifact.get('kind', artifact.get('identity', {}).get('kind', 'unknown')),
                    'sha256': sha, 'bytes': path.stat().st_size, 'units': metadata.get('spatial', {}).get('units', 'unknown'),
                    'metadata': str(metadata_path.relative_to(self.workspace)),
                    'metadataSha256': companion['sha256'],
                    'metadataManifest': str((directory/MANIFEST).relative_to(self.workspace)),
                    'metadataManifestSha256': file_digest(directory/MANIFEST),
                    'receipt': str((directory/'verification.json').relative_to(self.workspace)),
                    'receiptSha256': file_digest(directory/'verification.json')})
        return resources

    def _run(self, identity, document, token):
        with self.lock:
            job = copy.deepcopy(self.state['jobs'][identity])
            budget = self.state['tasks'][job['task']]['budget']
        try:
            if token.is_set():
                fail('RUNNER_CANCELLED', 'job cancelled before execution')
            target = self.workspace/job['directory']
            target.parent.mkdir(parents=True, exist_ok=True)
            outcome = self.executor.run(self._execution_request(job, document, token), token)
            result = outcome.response
            if outcome.isolation:
                job.setdefault('isolation', {})['execution'] = copy.deepcopy(outcome.isolation)
            verification = self._verify_run(job, document, token)
            with self.lock:
                for resource_id in self.state['plans'][job['plan']]['resources']:
                    self._resource(resource_id)
            resources = self._collect(job, document)
            if token.is_set():
                fail('RUNNER_CANCELLED', 'cancellation arrived before job completion was recorded')
            result_ref = self._write('jobs/'+identity+'/result.json', result)
            verification_ref = self._write('jobs/'+identity+'/verification.json', verification)
            with self.lock:
                if token.is_set():
                    fail('RUNNER_CANCELLED', 'cancellation arrived before completion was committed')
                state = copy.deepcopy(self.state)
                state['jobs'][identity].update(status='succeeded', verified=True, nativeState='verified',
                    finishedAt=time.time(), result=result_ref, verification=verification_ref,
                    resources=[r['id'] for r in resources])
                if job.get('isolation'):
                    state['jobs'][identity]['isolation'] = copy.deepcopy(job['isolation'])
                state['resources'].update({r['id']: r for r in resources})
                self._commit(state)
        except Exception as error:
            info = error_fault(error)
            if token.expired():
                info = Fault('TIME_BUDGET_EXCEEDED', 'task elapsed-time budget was exhausted', '$', 'agent',
                             observed={'cause': info}, recovery='Inspect partial evidence before creating a newly authorised task.').to_dict()
            cancelled = info['code'] in ('RUNNER_CANCELLED', 'TIME_BUDGET_EXCEEDED')
            with self.lock:
                state = copy.deepcopy(self.state)
                state['jobs'][identity].update(status='cancelled' if cancelled else 'failed', verified=False,
                                               nativeState='unknown', fault=info, finishedAt=time.time())
                if job.get('isolation'): state['jobs'][identity]['isolation'] = copy.deepcopy(job['isolation'])
                self._commit(state)
        finally:
            with self.lock:
                try:
                    self._release_inputs(identity)
                except Exception as error:
                    state = copy.deepcopy(self.state)
                    state['jobs'][identity].update(status='interrupted', verified=False, nativeState='unknown',
                        cleanupFault=error_fault(error))
                    self._commit(state)

    def job(self, job_id):
        with self.lock:
            job = self._get('jobs', job_id)
            return {key: copy.deepcopy(value) for key, value in job.items()
                    if key not in ('result', 'verification', 'resources', 'fault')} | {
                        'resourceCount': len(job.get('resources', [])), 'faultCode': job.get('fault', {}).get('code')}

    def jobs_for_plan(self, plan_id):
        """Trusted embedding recovery lookup; not an agent transport method."""
        with self.lock:
            self._get('plans', plan_id)
            return [self.job(identity) for identity, job in self.state['jobs'].items()
                    if job['plan'] == plan_id]

    def cancel(self, job_id):
        with self.lock:
            job = self._get('jobs', job_id)
            if job['status'] in TERMINAL:
                return self.job(job_id)
            self.runner.cancellations[job_id].set()
            state = copy.deepcopy(self.state)
            state['jobs'][job_id]['status'] = 'cancellation-requested'
            self._commit(state)
            return self.job(job_id)

    def observe(self, job_id=None, plan_id=None, section='verification', **page):
        with self.lock:
            if (job_id is None) == (plan_id is None):
                fail('INVALID_OBSERVATION', 'choose one job_id or plan_id')
            job = self._get('jobs', job_id) if job_id is not None else None
            plan = self._get('plans', job['plan'] if job else plan_id)
            if section in ('document', 'plan'):
                value = self._read(plan[section])
            elif job and section in ('result', 'verification'):
                if section not in job:
                    fail('EVIDENCE_UNAVAILABLE', 'job has no successful ' + section, status=job['status'])
                value = self._read(job[section])
            elif job and section == 'resources':
                value = [self.state['resources'][r] for r in job.get('resources', [])]
            elif job and section == 'fault':
                value = job.get('fault')
            else:
                fail('INVALID_OBSERVATION', 'choose document, plan, result, verification, resources or fault')
            return bounded(value, (job_id or plan_id) + '/' + section, **page)

    def verify(self, job_id):
        return self.verify_with_control(job_id)

    def verify_with_control(self, job_id, *, cancellation=None, deadline=None):
        """Trusted embedding controls; not an authored/transport argument surface."""
        with self.lock:
            job = copy.deepcopy(self._get('jobs', job_id))
            if job['status'] != 'succeeded':
                fail('INCOMPLETE_EXECUTION', 'only a completed job can be reverified', status=job['status'])
            if getattr(self.executor, 'isolated', False):
                if self._busy():
                    fail('SESSION_BUSY', 'wait for active execution before isolated reverification')
                if any(record['status'] in ('intent', 'running', 'interrupted')
                       for record in self.state['planningOperations'].values()):
                    fail('PLANNING_UNCERTAIN', 'reconcile previous planning before isolated reverification')
                self.isolation_recovery = self.executor.recover(self.workspace)
                for identity in list(self._input_leases): self._release_inputs(identity)
            document = self._read(self._get('plans', job['plan'])['document'])
            budget = self.state['tasks'][job['task']]['budget']
            maximum = time.monotonic()+budget['timeoutPerStageSeconds']
            if deadline is not None:
                if type(deadline) not in (int, float) or not math.isfinite(deadline):
                    raise ValueError('trusted verification deadline must be finite')
                maximum = min(maximum, deadline)
            if getattr(self.executor, 'isolated', False):
                token, _ = self._controls(self.state['tasks'][job['task']], cancellation, maximum, None)
            else:
                token = Cancellation(parent=cancellation, deadline=maximum)
            lease_id = 'verification-'+uuid.uuid4().hex
            inputs = self._input_bindings(self.state['plans'][job['plan']])
            if getattr(self.executor, 'isolated', False):
                self.executor.admit(document, inputs, bound=inputs is not None)
            elif inputs is not None:
                fail('ISOLATION_UNAVAILABLE', 'captured inputs cannot be verified on the host')
            self._hold_inputs(lease_id, inputs)
            try:
                result = self._verify_run(job, document, token)
                if getattr(self.executor, 'isolated', False):
                    self._collect(job, document)
                for resource_id in job.get('resources', []):
                    self._resource(resource_id)
            except Exception as error:
                state = copy.deepcopy(self.state)
                state['jobs'][job_id].update(status='failed', verified=False, nativeState='unknown', fault=error_fault(error))
                self._commit(state)
                raise
            finally:
                try:
                    self._release_inputs(lease_id)
                except Exception as error:
                    state = copy.deepcopy(self.state)
                    state['jobs'][job_id].update(status='interrupted', verified=False, nativeState='unknown',
                        cleanupFault=error_fault(error))
                    self._commit(state)
                    raise
            if job.get('isolation'):
                state = copy.deepcopy(self.state)
                state['jobs'][job_id]['isolation'] = job['isolation']
                self._commit(state)
            return bounded(result, job_id + '/verification')

    def _resource(self, resource_id):
        resource = self._get('resources', resource_id)
        job = self._get('jobs', resource['job'])
        if job['status'] != 'succeeded' or not job['verified']:
            fail('UNVERIFIED_RESOURCE', 'producer is not a verified successful job')
        pairs = [('file', 'sha256'), ('receipt', 'receiptSha256')]
        if 'metadata' in resource:
            pairs.extend([('metadata', 'metadataSha256'), ('metadataManifest', 'metadataManifestSha256')])
        for key, sha in pairs:
            path = self.workspace/resource[key]
            if getattr(self.executor, 'isolated', False):
                from .execution_backends import owned_regular
                owned_regular(self.workspace/job['directory'], path)
            if (not path.resolve().is_relative_to(self.workspace) or path.is_symlink()
                    or not path.is_file() or file_digest(path) != resource[sha]):
                fail('RESOURCE_CHANGED', 'resource or its provenance changed', resource=resource_id)
        return resource

    def inspect_resource(self, resource_id, **page):
        """Inspect bounded JSON/CSV publications without an agent conversion script."""
        with self.lock:
            resource = self._resource(resource_id)
            if resource['bytes'] > 1024*1024:
                fail('INSPECTION_LIMIT', 'structured inspection is limited to one MiB; use bounded byte reads')
            path = self.workspace/resource['file']
            if path.suffix.lower() == '.json':
                value = load(path.read_text(encoding='utf-8'))
            elif path.suffix.lower() == '.csv':
                rows = list(csv.reader(io.StringIO(path.read_text(encoding='utf-8'), newline=''), strict=True))
                value = {'columns': rows[0] if rows else [], 'rows': rows[1:],
                         'valueType': 'string', 'units': 'unknown'}
            else:
                fail('UNSUPPORTED_INSPECTION', 'structured inspection currently supports JSON and CSV publications')
            self._resource(resource_id)
            return bounded(value, resource_id, **page)

    def inspect_resource_metadata(self, resource_id, **page):
        """Read bounded placement/size evidence after checking its publication."""
        with self.lock:
            resource = self._resource(resource_id)
            if 'metadata' not in resource:
                fail('UNSUPPORTED_INSPECTION', 'older resource has no metadata companion; rerun its producer')
            value = load((self.workspace/resource['metadata']).read_text(encoding='utf-8'))
            self._resource(resource_id)
            return bounded(value, resource_id+'/metadata', **page)

    def list_tasks(self, **page):
        with self.lock:
            return bounded(list(self.state['tasks'].values()), 'tasks', **page)

    def resource(self, resource_id, *, offset=0, length=4096):
        if type(offset) is not int or offset < 0 or type(length) is not int or not 1 <= length <= 16384:
            fail('INVALID_PAGE', 'offset must be nonnegative and length 1..16384 bytes')
        with self.lock:
            resource = copy.deepcopy(self._resource(resource_id))
            if offset > resource['bytes']:
                fail('INVALID_PAGE', 'offset exceeds artifact size')
            with (self.workspace/resource['file']).open('rb') as stream:
                stream.seek(offset)
                data = stream.read(length)
            self._resource(resource_id)
            return {'resource': resource, 'encoding': 'base64', 'offset': offset,
                    'data': base64.b64encode(data).decode('ascii'), 'returnedBytes': len(data),
                    'nextOffset': offset+len(data) if offset+len(data) < resource['bytes'] else None}

    def close(self):
        if not self._owner.closed:
            self.runner.close()
            if self._authoring is not None:
                self._authoring.close()
            with self.lock:
                for identity in list(self._input_leases): self._release_inputs(identity)
                self.closed = True
                self._owner.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
