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
    def __init__(self, workspace, *, locations=None):
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.closed = False
        self.locations = copy.deepcopy(locations)
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
                if not isinstance(self.state, dict) or set(self.state) != {'tasks', 'plans', 'jobs', 'resources'}:
                    fail('RECOVERY_FAILED', 'agent state shape differs')
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
                self.state = {'tasks': {}, 'plans': {}, 'jobs': {}, 'resources': {}}
                self._commit(self.state)
        except Exception:
            self.runner.close()
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

    def _plan(self, task_id, document, expected_revision, bindings=None, draft=None):
        if not isinstance(document, dict) or len(encoded(document)) > 1024*1024:
            fail('INVALID_DOCUMENT', 'document must be an object no larger than one MiB')
        with self.lock:
            task = self._get('tasks', task_id)
            if type(expected_revision) is not int or expected_revision != task['revision']:
                fail('STALE_REVISION', 'task revision changed', currentRevision=task['revision'])
            if document.get('version') in ('schemaxis.workflow-design/1', 'schemaxis.workflow-design/2'):
                from .workflow_design import compile
                compile(document)  # Gives the specific feedback fault for closed groups.
                fail('WORKFLOW_DESIGN_REQUIRES_COMPILATION',
                     'compile the design into a separate workflow draft before planning execution')
            document = copy.deepcopy(document)
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
        with self.lock:
            plan = self._get('plans', plan_id)
            task = self._get('tasks', plan['task'])
            if (type(expected_revision) is not int or expected_revision != task['revision']
                    or plan['revision'] != expected_revision or task.get('currentPlan') != plan_id):
                fail('STALE_REVISION', 'execute requires the current captured plan', currentRevision=task['revision'])
            if plan.get('draft'):
                source = plan['draft']
                session = self._draft_session(source['document'], source['revision'])
                if session.draft()['sourceDigest'] != source['sourceDigest']:
                    fail('STALE_PLAN', 'authored source changed; capture a new draft plan')
                session.document  # An invalid draft is never an executable request.
            if self._busy():
                fail('SESSION_BUSY', 'wait for the active job or cancel it')
            budget = task['budget']
            if task['attempts'] >= budget['maxAttempts']:
                fail('ATTEMPT_BUDGET_EXCEEDED', 'task attempt budget is exhausted')
            deadline = (task['startedAt'] or time.time()) + budget['maxElapsedSeconds']
            if time.time() >= deadline:
                fail('TIME_BUDGET_EXCEEDED', 'task elapsed-time budget is exhausted')
            failed = [j for j in self.state['jobs'].values() if j['task'] == task['id']
                      and j['documentDigest'] == plan['documentDigest'] and j['status'] in ('failed', 'interrupted')]
            counts = {}
            for job in failed:
                code = job.get('fault', {}).get('code', 'UNKNOWN')
                counts[code] = counts.get(code, 0)+1
            if counts and max(counts.values()) >= budget['maxRepeatedFailures']:
                fail('REPEATED_FAILURE', 'unchanged request has repeatedly failed; revise the document or start a newly authorised task')
            document = self._read(plan['document'])
            captured_plan = self._read(plan['plan'])
            for identity in plan['resources']:
                self._resource(identity)
            current_plan = workflow.inspect_plan(document) if document.get('version') == 'schemaxis.workflow/1' else registry.plan(document)
            if current_plan != captured_plan:
                fail('STALE_PLAN', 'host planning changed since capture; create a new plan revision')
            identity = 'job-' + uuid.uuid4().hex
            state = copy.deepcopy(self.state)
            state['tasks'][task['id']].update(attempts=task['attempts']+1, startedAt=task['startedAt'] or time.time())
            record = {'id': identity, 'task': task['id'], 'plan': plan_id, 'revision': expected_revision,
                      'documentDigest': plan['documentDigest'], 'status': 'running', 'verified': False,
                      'nativeState': 'unobserved', 'directory': 'runs/'+identity, 'createdAt': time.time()}
            if plan.get('draft'):
                record['draft'] = copy.deepcopy(plan['draft'])
            state['jobs'][identity] = record
            self._commit(state)
            token = Cancellation(deadline=time.monotonic() + max(0, deadline-time.time()))
            self.runner.submit(identity, lambda: self._run(identity, document, token), token)
            return copy.deepcopy(record)

    def _verify_run(self, job, document):
        target = self.workspace/job['directory']
        if not (target/'authored.json').is_file():
            fail('VERIFICATION_FAILED', 'retained execution input is missing')
        if load((target/'authored.json').read_text()) != document:
            fail('VERIFICATION_FAILED', 'retained execution input differs from captured request')
        result = workflow.verify(target) if document.get('version') == 'schemaxis.workflow/1' else registry.verify(target, document)
        if result.get('verified') is not True:
            fail('VERIFICATION_FAILED', 'verifier did not establish success')
        return result

    def _collect(self, job, document):
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
            timeout = min(budget['timeoutPerStageSeconds'], budget['maxElapsedSeconds'])
            result = (workflow.execute(document, target, locations=self.locations, timeout=timeout)
                      if document.get('version') == 'schemaxis.workflow/1'
                      else registry.run(document, target, locations=self.locations, timeout=timeout))
            verification = self._verify_run(job, document)
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
                self._commit(state)

    def job(self, job_id):
        with self.lock:
            job = self._get('jobs', job_id)
            return {key: copy.deepcopy(value) for key, value in job.items()
                    if key not in ('result', 'verification', 'resources', 'fault')} | {
                        'resourceCount': len(job.get('resources', [])), 'faultCode': job.get('fault', {}).get('code')}

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
        with self.lock:
            job = self._get('jobs', job_id)
            if job['status'] != 'succeeded':
                fail('INCOMPLETE_EXECUTION', 'only a completed job can be reverified', status=job['status'])
            document = self._read(self._get('plans', job['plan'])['document'])
            try:
                result = self._verify_run(job, document)
                for resource_id in job.get('resources', []):
                    self._resource(resource_id)
            except Exception as error:
                state = copy.deepcopy(self.state)
                state['jobs'][job_id].update(status='failed', verified=False, nativeState='unknown', fault=error_fault(error))
                self._commit(state)
                raise
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
                self.closed = True
                self._owner.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
