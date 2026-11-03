# Copyright (C) 2026 David L F Gaden
"""Case Runner adaptor over captured templates, workflow execution and verification.

The HTTP application owns serial jobs and cancellation. This module never
executes input as Python and does not introduce an alternate workflow executor.
"""
import copy
import hashlib
from pathlib import Path
import threading
import uuid

from . import output_naming, storage, workflow, workflow_templates
from .console_server import fault
from .core.faults import SchemaxisError
from .errors import fail, keys


def _operations(document):
    result = []
    for operation in document['operations']:
        dependencies = set()
        for reference in workflow.dependencies(operation['document']):
            dependencies.add(reference.get('$artifact', reference.get('$value')))
        result.append({'id': operation['id'], 'version': operation['document'].get('version'),
                       'dependencies': sorted(dependencies), 'status': 'pending'})
    return result


def _read_status(path):
    try:
        if path.stat().st_size > 16 * 1024 * 1024:
            return {}
        value = storage.load(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, SchemaxisError):
        return {}


class StudioCases:
    """Token-protected POST /api/cases handlers, supplied one ConsoleApplication."""

    def __init__(self, app):
        self.app = app
        self.workspace = Path(app.session.workspace).resolve()
        self.records = {}
        self.file_lock = threading.Lock()

    def file_roots(self):
        with self.app.job_lock:
            return [Path(record['directory']) for record in self.records.values()]

    def _path(self, value, *, case=False):
        if not isinstance(value, str) or not value.strip() or '\x00' in value:
            fail('INVALID_CASE_PATH', 'supply a local path', '$.filename' if case else '$.path')
        path = Path(value).expanduser()
        if '..' in path.parts:
            fail('INVALID_CASE_PATH', 'parent traversal is not permitted', str(path))
        path = path if path.is_absolute() else self.workspace / path
        for component in (*reversed(path.parents), path):
            if component.is_symlink():
                fail('INVALID_CASE_PATH', 'paths must not pass through a symbolic link', str(component))
        return path

    def _template(self, value):
        path = self._path(value)
        if not path.is_dir(): return path
        candidates = [path / name for name in ('template.json', 'template.yaml', 'template.yml') if (path / name).is_file()]
        if len(candidates) > 1:
            fail('INVALID_TEMPLATE_PATH', 'choose the explicit manifest filename when several formats exist', str(path))
        return candidates[0] if candidates else path / 'template.json'

    def inspect(self, value):
        path = self._template(value)
        bundle = workflow_templates.load_template(path)
        template = bundle['template']
        identity = {key: template[key] for key in ('id', 'revision')}
        identity['digest'] = bundle['digest']
        values = {key: copy.deepcopy(spec['default']) for key, spec in template['parameters'].items()
                  if 'default' in spec}
        return {'path': str(path), 'template': template, 'digest': bundle['digest'], 'identity': identity,
                'values': {'version': workflow_templates.VALUES_VERSION, 'template': identity, 'values': values},
                'operations': _operations(bundle['workflow'])}

    def _prepare(self, request):
        path = self._template(request.get('path'))
        prepared = workflow_templates.prepare_template(path, request.get('values'), planning=True)
        bundle = workflow_templates.load_template(path)
        if bundle['digest'] != prepared['template']['digest']:
            fail('STALE_TEMPLATE', 'template changed while preparing the case; inspect it again', '$.path')
        prepared['outputs'] = bundle['template']['outputs']
        workers = prepared['run'].get('workers')
        if workers is not None:
            prepared['document'].setdefault('execution', {})['maxWorkers'] = workers
            prepared['digest'] = storage.digest(prepared['document'])
            prepared['plan'] = workflow.inspect_plan(prepared['document'])
        prepared['operations'] = _operations(prepared['document'])
        return prepared

    def request(self, request):
        keys(request, ('action', 'path', 'values', 'filename', 'job', 'caseDigest'), '$.cases')
        action = request.get('action')
        if action == 'inspect_template':
            return self.inspect(request.get('path'))
        if action == 'load':
            path = self._path(request.get('filename'), case=True)
            try:
                if path.stat().st_size > 1024 * 1024:
                    fail('CASE_TOO_LARGE', 'case files are limited to one MiB', str(path))
                payload = path.read_bytes()
                from .core.documents import load_document, document_format
                values = load_document(payload.decode('utf-8'), 'yaml') if document_format(path) == 'yaml' else storage.load(payload.decode('utf-8'))
            except (OSError, ValueError) as error:
                fail('INVALID_CASE_FILE', 'cannot read case input: ' + str(error), str(path))
            prepared = self._prepare({**request, 'values': values})
            return {'filename': str(path), 'values': values, 'bound': prepared,
                    'caseDigest': hashlib.sha256(payload).hexdigest()}
        if action in ('bind', 'plan', 'save', 'run'):
            prepared = self._prepare(request)
            if action == 'save':
                path = self._path(request.get('filename'), case=True)
                if not path.is_relative_to(self.workspace):
                    fail('INVALID_CASE_PATH', 'save case files inside the Studio workspace', str(path))
                with self.file_lock:
                    exists = path.exists()
                    if exists and not request.get('caseDigest'):
                        fail('CASE_FILE_EXISTS', 'load this case first, or choose a new filename', str(path))
                    if exists and _sha256(path) != request.get('caseDigest'):
                        fail('STALE_CASE_FILE', 'case changed on disk; load it again before saving', str(path))
                    if not exists and request.get('caseDigest'):
                        fail('STALE_CASE_FILE', 'the loaded case was removed; choose a new filename', str(path))
                    path.parent.mkdir(parents=True, exist_ok=True)
                    from .core.documents import document_format
                    if document_format(path) == 'yaml':
                        from .core.yaml_documents import reconcile, dump
                        source = reconcile(path.read_text(encoding='utf-8'), request['values']) if exists else dump(request['values'])
                        payload = source.encode('utf-8')
                    else:
                        payload = storage.encoded(request['values'])
                    storage.atomic(path, payload, exclusive=not exists)
                return {'filename': str(path), 'values': request['values'],
                        'caseDigest': hashlib.sha256(payload).hexdigest()}
            if action == 'run':
                return self._start(request, prepared)
            return prepared
        if action == 'outputs':
            identity = request.get('job')
            if not isinstance(identity, str):
                fail('INVALID_REQUEST', 'supply a case job identity', '$.job')
            with self.app.job_lock:
                record = self.records.get(identity)
                snapshot = self.app.jobs.get(identity, {})
            if record is None:
                fail('UNKNOWN_JOB', 'there is no case with this job identity', '$.job')
            if snapshot.get('status') != 'succeeded':
                fail('INCOMPLETE_EXECUTION', 'outputs become available after the workflow verifies', '$.job')
            workflow.verify(record['directory'])
            outputs = snapshot['result']['outputs']
            for item in outputs:
                if _sha256(Path(item['path'])) != item['sha256']:
                    fail('VERIFICATION_FAILED', 'named output changed after publication', item['path'])
            return copy.deepcopy(snapshot['result'])
        fail('INVALID_REQUEST', 'choose inspect_template, load, save, bind, plan, run or outputs', '$.action')

    def _start(self, request, prepared):
        identity = uuid.uuid4().hex
        directory = self._path(prepared['run'].get('outputDirectory', 'runs/case-' + identity[:12]))
        with self.app.job_lock:
            if self.app.busy:
                fail('SESSION_BUSY', 'wait for the current operation before starting a case')
            # Match authoring's lock order and reject busy before a native command's session lock.
            with self.app.lock:
                configurations = self.app.session.status().get('configurations', {})
                locations = {key: value['executable'] for key, value in configurations.items()}
                settings = self.app.settings.read()['values'] if hasattr(self.app, 'settings') else {}
            if directory.exists() and (not directory.is_dir() or any(directory.iterdir())):
                fail('OUTPUT_EXISTS', 'choose a new or empty output directory', str(directory))
            self.records[identity] = {'directory': str(directory), 'operations': prepared['operations']}
            self.app.busy = True
            self.app.jobs[identity] = {'status': 'running', 'label': 'Case: ' + prepared['template']['id'],
                                       'operations': prepared['operations'], 'directory': str(directory)}
            token = threading.Event()
            self.app.cancellations[identity] = token
        try:
            self.app.job_owner.submit(identity, lambda: self._execute(
                identity, request, prepared, directory, locations, settings, token), token)
        except Exception:
            with self.app.job_lock:
                self.app.busy = False
                self.app.jobs.pop(identity, None)
                self.records.pop(identity, None)
                self.app.cancellations.pop(identity, None)
            raise
        return {'job': identity, 'status': 'running', 'directory': str(directory)}

    def _execute(self, identity, request, prepared, directory, locations, settings, token):
        label = 'Case: ' + prepared['template']['id']
        try:
            if token.is_set():
                fail('RUNNER_CANCELLED', 'case was cancelled before execution')
            directory.parent.mkdir(parents=True, exist_ok=True)
            workflow.execute(prepared['document'], directory, locations=locations)
            verification = workflow.verify(directory)
            if verification.get('verified') is not True:
                fail('VERIFICATION_FAILED', 'workflow verifier did not establish success', str(directory))
            storage.atomic(directory / 'case.json', storage.encoded(request['values']), exclusive=True)
            options = prepared['run'].get('naming', {})
            pattern = options.get('pattern', settings.get('output.namingPattern', output_naming.DEFAULT_PATTERN))
            width = options.get('indexWidth', settings.get('output.indexWidth', output_naming.DEFAULT_WIDTH))
            result = {'directory': str(directory), 'verification': verification, 'naming': None, 'outputs': []}
            try:
                result['naming'] = output_naming.apply(directory, pattern, index_width=width,
                    parameters=prepared['values'], outputs=prepared['outputs'])
            except Exception as error:
                result['namingFault'] = fault(error)
            result['outputs'] = self._outputs(directory, result['naming'])
            snapshot = {'status': 'succeeded', 'label': label, 'result': result, 'verified': True,
                        'directory': str(directory), 'operations': [dict(op, status='succeeded')
                                                                  for op in prepared['operations']]}
        except Exception as error:
            operations = self.snapshot(identity).get('operations', [])
            for operation in operations:
                if operation['status'] == 'running':
                    operation['status'] = 'failed'
                elif operation['status'] == 'pending':
                    operation['status'] = 'blocked'
            snapshot = {'status': 'failed', 'label': label, 'fault': fault(error),
                        'directory': str(directory), 'operations': operations}
        with self.app.job_lock:
            self.app.jobs[identity] = snapshot
            self.app.busy = False

    def _outputs(self, directory, naming):
        if naming is not None:
            return [{'name': name, 'path': str(directory / 'named' / name), **entry}
                    for name, entry in naming['names'].items()]
        outputs = []
        for item in output_naming._collect(directory, {}):
            path = Path(item['record']['file'])
            path = path if path.is_absolute() else directory / path
            if not path.resolve().is_relative_to(directory.resolve()):
                fail('VERIFICATION_FAILED', 'artifact escaped its run directory', str(path))
            outputs.append({'name': path.name, 'path': str(path), 'operation': item['operation'],
                            'artifact': item['artifact'], 'kind': item['record'].get('kind'),
                            'sha256': _sha256(path)})
        return outputs

    def snapshot(self, identity):
        with self.app.job_lock:
            snapshot = copy.deepcopy(self.app.jobs.get(identity, {'status': 'unknown'}))
            record = self.records.get(identity)
        if record is None or snapshot.get('status') != 'running':
            return snapshot
        directory = Path(record['directory'])
        saved = _read_status(directory / 'result.json')
        operations = copy.deepcopy(record['operations'])
        if saved.get('executionVersion') == 2:
            plan = _read_status(directory / 'execution-plan.json')
            outcomes = {job['id']: job for job in saved.get('jobs', [])}
            running = set(saved.get('runningJobs', []))
            for operation in operations:
                members = [job['id'] for job in plan.get('jobs', []) if job['operation'] == operation['id']]
                if members and all(outcomes.get(key, {}).get('status') == 'succeeded' for key in members):
                    operation['status'] = 'succeeded'
                elif any(key in running for key in members):
                    operation['status'] = 'running'
                elif any(outcomes.get(key, {}).get('status') == 'failed' for key in members):
                    operation['status'] = 'failed'
        elif saved.get('states'):
            # Study visits may repeat the same operation; do not claim a completed operation prematurely.
            for operation in operations:
                operation['status'] = 'running'
        else:
            completed = {operation.get('id') for operation in saved.get('operations', [])}
            for operation in operations:
                if operation['id'] in completed:
                    operation['status'] = 'succeeded'
                elif (directory / operation['id']).exists():
                    operation['status'] = 'running'
        snapshot['operations'] = operations
        return snapshot


def _sha256(path):
    digest = hashlib.sha256()
    try:
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
    except OSError as error:
        fail('VERIFICATION_FAILED', 'cannot read output: ' + str(error), str(path))
    return digest.hexdigest()
