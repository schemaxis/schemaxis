"""Host doubles prove service lifecycle; separate qualification runs native apps."""
import base64
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.capabilities import digest, response_bytes
from schemaxis.console_session import atomic, encoded, AtomicPublicationError
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import cancellation_requested, SubprocessRunner
from schemaxis.core.runners import Interpreter
from schemaxis.errors import fail
from schemaxis.execution_service import ExecutionService, TERMINAL
from schemaxis.observations import bounded
from schemaxis.agent_transport import serve, dispatch

ROOT = Path(__file__).resolve().parents[2]
BOX = {'version': 'schemaxis.freecad/1', 'nodes': [{'id': 'body', 'filter': 'box'}], 'output': 'body'}


def fake_run(document, directory, **kwargs):
    directory.mkdir()
    atomic_json(directory/'authored.json', document)
    atomic_json(directory/'numbers.json', {'volume': 1000, 'samples': list(range(1000))})
    (directory/'data.csv').write_text('x,y\n0,1\n1,2\n')
    (directory/'model.step').write_text('host test double')
    artifacts = [{'file': str(directory/name), 'kind': kind, 'sha256': file_digest(directory/name)}
                 for name, kind in [('numbers.json', 'analysis'), ('data.csv', 'table'), ('model.step', 'cad')]]
    atomic_json(directory/'verification.json', {'artifacts': artifacts})
    from schemaxis.publication_metadata import finalise
    finalise(directory)
    return {'verified': True, 'scope': 'host double'}


def fake_verify(directory, document=None):
    receipt = json.loads((directory/'verification.json').read_text())
    for a in receipt['artifacts']:
        if file_digest(a['file']) != a['sha256']:
            fail('VERIFICATION_FAILED', 'changed test artifact')
    return {'verified': True, 'volumeMM3': 1000, 'artifacts': len(receipt['artifacts'])}


class ExecutionServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.service = ExecutionService(self.tmp.name, locations={'freecad': '/not-used'})
        self.addCleanup(self.service.close)
        for name, function in [('run', fake_run), ('verify', fake_verify)]:
            patcher = patch('schemaxis.execution_service.registry.'+name, side_effect=function)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.task = self.service.create_task('Host lifecycle proof', ['freecad', 'octave'])

    def wait(self, identity):
        until = time.monotonic()+5
        while time.monotonic()<until:
            status = self.service.job(identity)
            if status['status'] in TERMINAL:
                return status
            time.sleep(.01)
        self.fail('job did not finish within five seconds')

    def plan(self, document=None):
        return self.service.plan(self.task['id'], copy.deepcopy(document or BOX), self.service.task(self.task['id'])['revision'])

    def run_job(self):
        plan = self.plan()
        job = self.service.execute(plan['id'], plan['revision'])
        self.assertEqual(self.wait(job['id'])['status'], 'succeeded')
        return job['id']

    def test_resource_companion_tampering_blocks_reuse(self):
        identity = self.run_job()
        resource = next(value for value in self.service.state['resources'].values() if value['job'] == identity)
        self.assertIn('metadata', resource)
        observed = self.service.inspect_resource_metadata(resource['id'])
        self.assertEqual(observed['value']['size']['bytes'], resource['bytes'])
        path = self.service.workspace/resource['metadata']
        path.write_text('{}')
        self.fault('RESOURCE_CHANGED', lambda: self.service.resource(resource['id']))

    def test_workflow_study_collects_aggregate_publications(self):
        from schemaxis.adaptor_runtime import PROTOCOL
        document = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'one', 'document': BOX}]}
        root = self.service.workspace/'runs'/'study'
        root.parent.mkdir(exist_ok=True)
        fake_run(document, root)
        atomic_json(root/'result.json', {'protocol': PROTOCOL, 'status': 'succeeded', 'verified': True})
        resources = self.service._collect({'id': 'job-study', 'directory': 'runs/study',
                                          'documentDigest': digest(document)}, document)
        self.assertEqual(len(resources), 3)
        self.assertTrue(all('metadata' in resource for resource in resources))

    def fault(self, code, callback):
        with self.assertRaises(SchemaxisError) as caught:
            callback()
        self.assertEqual(caught.exception.fault.code, code)
        return caught.exception.fault

    def test_captured_revision_and_plan_cannot_be_replaced_under_execution(self):
        first = self.plan()
        second = self.plan({**BOX, 'nodes': [{'id': 'body', 'filter': 'box', 'options': {'height': 20}}]})
        self.fault('STALE_REVISION', lambda: self.service.execute(first['id'], second['revision']))
        self.fault('STALE_REVISION', lambda: self.service.execute(second['id'], True))
        self.fault('STALE_REVISION', lambda: self.service.plan(self.task['id'], BOX, 0))
        document = self.service.observe(plan_id=first['id'], section='document')['value']
        self.assertEqual(document, BOX)
        document['nodes'].clear()
        self.assertEqual(self.service.observe(plan_id=first['id'], section='document')['value'], BOX)
        self.assertEqual(self.service.task(self.task['id'])['attempts'], 0)

    def test_changed_host_plan_is_rejected_before_native_dispatch(self):
        plan = self.plan()
        with patch('schemaxis.execution_service.registry.plan', return_value={'changed': True}):
            self.fault('STALE_PLAN', lambda: self.service.execute(plan['id'], plan['revision']))
        self.assertEqual(self.service.task(self.task['id'])['attempts'], 0)

    def test_cancellation_during_evidence_publication_cannot_commit_success(self):
        original = self.service._write
        def interrupt(name, value):
            reference = original(name, value)
            if name.startswith('jobs/') and name.endswith('/verification.json'):
                job_id = name.split('/')[1]
                self.service.cancel(job_id)
            return reference
        with patch.object(self.service, '_write', side_effect=interrupt):
            plan = self.plan()
            job = self.service.execute(plan['id'], plan['revision'])
            result = self.wait(job['id'])
        self.assertEqual(result['status'], 'cancelled')
        self.assertFalse(result['verified'])
        self.assertEqual(result['resourceCount'], 0)

    def test_scope_and_bad_plans_do_not_consume_revision_or_attempts(self):
        other = self.service.create_task('Only numeric', ['octave'])
        self.fault('SCOPE_EXCEEDED', lambda: self.service.plan(other['id'], BOX, 0))
        bad = {**BOX, 'output': 'missing'}
        self.fault('INVALID_SELECTION', lambda: self.plan(bad))
        self.assertEqual(self.service.task(self.task['id'])['revision'], 0)
        self.assertEqual(self.service.task(self.task['id'])['attempts'], 0)

    def test_successful_evidence_and_resources_are_digest_bound(self):
        job = self.run_job()
        self.assertEqual(self.service.observe(job_id=job)['value']['volumeMM3'], 1000)
        resources = self.service.observe(job_id=job, section='resources')['value']
        self.assertEqual(len(resources), 3)
        self.assertEqual(self.service.inspect_resource(resources[0]['id'], pointer='/volume')['value'], 1000)
        table = self.service.inspect_resource(resources[1]['id'])['value']
        self.assertEqual(table['rows'], [['0', '1'], ['1', '2']])
        read = self.service.resource(resources[1]['id'], length=4)
        self.assertEqual(base64.b64decode(read['data']), b'x,y\n')
        self.assertEqual(read['nextOffset'], 4)
        self.assertEqual(self.service.resource(resources[1]['id'], offset=read['resource']['bytes'])['nextOffset'], None)
        self.assertTrue(self.service.verify(job)['value']['verified'])

    def test_tamper_invalidates_reverification_and_resource_use(self):
        job = self.run_job()
        resource = self.service.observe(job_id=job, section='resources')['value'][0]
        (self.service.workspace/resource['file']).write_text('changed')
        self.fault('RESOURCE_CHANGED', lambda: self.service.resource(resource['id']))
        self.fault('VERIFICATION_FAILED', lambda: self.service.verify(job))
        self.assertFalse(self.service.job(job)['verified'])
        self.fault('UNVERIFIED_RESOURCE', lambda: self.service.inspect_resource(resource['id']))

    def test_changed_captured_document_prevents_dispatch(self):
        plan = self.plan()
        reference = self.service.state['plans'][plan['id']]['document']
        (self.service.workspace/reference['file']).write_text('{}')
        self.fault('EVIDENCE_CHANGED', lambda: self.service.execute(plan['id'], plan['revision']))
        self.assertEqual(self.service.task(self.task['id'])['attempts'], 0)

    def test_resource_binding_reuses_verified_artifacts_without_new_document_syntax(self):
        job = self.run_job()
        resource = self.service.observe(job_id=job, section='resources')['value'][1]
        doc = {'version': 'schemaxis.octave/1', 'nodes': [
            {'id': 'data', 'filter': 'readCSV', 'options': {'file': None, 'xColumn': 'x', 'yColumn': 'y'}}], 'outputs': ['data']}
        plan = self.service.plan(self.task['id'], doc, 1, bindings={'/nodes/0/options/file': resource['id']})
        captured = self.service.observe(plan_id=plan['id'], section='document')['value']
        self.assertEqual(captured['nodes'][0]['options']['file'], str(self.service.workspace/resource['file']))
        self.assertIsNone(doc['nodes'][0]['options']['file'])
        (self.service.workspace/resource['file']).write_text('x,y\n0,9\n1,8\n')
        self.fault('RESOURCE_CHANGED', lambda: self.service.execute(plan['id'], plan['revision']))

    def test_incompatible_binding_is_distinct_from_missing_runtime(self):
        job = self.run_job()
        resource = self.service.observe(job_id=job, section='resources')['value'][1]
        doc = {**BOX, 'nodes': [{'id': 'body', 'filter': 'readSTEP', 'options': {'file': None}}]}
        self.fault('TYPE_MISMATCH', lambda: self.service.plan(self.task['id'], doc, 1, bindings={'/nodes/0/options/file': resource['id']}))
        with patch('schemaxis.execution_service.registry.run', side_effect=lambda *a, **k: fail('INTERPRETER_NOT_FOUND', 'absent runtime')):
            plan = self.plan()
            identity = self.service.execute(plan['id'], plan['revision'])['id']
            self.assertEqual(self.wait(identity)['faultCode'], 'INTERPRETER_NOT_FOUND')
            self.assertEqual(self.service.observe(job_id=identity, section='fault')['value']['code'], 'INTERPRETER_NOT_FOUND')
            self.fault('EVIDENCE_UNAVAILABLE', lambda: self.service.observe(job_id=identity))

    def test_repeated_unchanged_failure_stops_at_budget(self):
        with patch('schemaxis.execution_service.registry.run', side_effect=lambda *a, **k: fail('NATIVE_FAILED', 'same failure')):
            for _ in range(2):
                plan = self.plan()
                job = self.service.execute(plan['id'], plan['revision'])
                self.assertEqual(self.wait(job['id'])['status'], 'failed')
            plan = self.plan()
            self.fault('REPEATED_FAILURE', lambda: self.service.execute(plan['id'], plan['revision']))
        self.assertEqual(self.service.task(self.task['id'])['attempts'], 2)

    def test_attempt_budget_and_task_elapsed_deadline(self):
        self.task = self.service.create_task('One attempt', ['freecad'], {'maxAttempts': 1})
        self.run_job()
        plan = self.plan()
        self.fault('ATTEMPT_BUDGET_EXCEEDED', lambda: self.service.execute(plan['id'], plan['revision']))
        self.task = self.service.create_task('Short deadline', ['freecad'], {'maxElapsedSeconds': .02})
        def wait_for_deadline(*args, **kwargs):
            deadline = time.monotonic()+2
            while not cancellation_requested() and time.monotonic()<deadline:
                time.sleep(.005)
            fail('RUNNER_CANCELLED', 'token set')
        with patch('schemaxis.execution_service.registry.run', side_effect=wait_for_deadline):
            plan = self.plan()
            job = self.service.execute(plan['id'], plan['revision'])
            self.assertEqual(self.wait(job['id'])['faultCode'], 'TIME_BUDGET_EXCEEDED')
        self.fault('TIME_BUDGET_EXCEEDED', lambda: self.service.execute(plan['id'], plan['revision']))

    def test_cancellation_stops_process_and_retains_authored_evidence(self):
        entered = threading.Event()
        def slow(document, directory, **kwargs):
            directory.mkdir()
            atomic_json(directory/'authored.json', document)
            entered.set()
            SubprocessRunner(Interpreter('python', sys.executable), directory, timeout=3)('import time\ntime.sleep(20)')
        with patch('schemaxis.execution_service.registry.run', side_effect=slow):
            plan = self.plan()
            job = self.service.execute(plan['id'], plan['revision'])
            self.assertTrue(entered.wait(2))
            self.fault('SESSION_BUSY', lambda: self.service.execute(plan['id'], plan['revision']))
            self.service.cancel(job['id'])
            final = self.wait(job['id'])
        self.assertEqual(final['status'], 'cancelled')
        self.assertEqual(final['nativeState'], 'unknown')
        self.assertEqual(self.service.observe(job_id=job['id'], section='document')['value'], BOX)
        self.assertEqual(self.service.cancel(job['id'])['status'], 'cancelled')

    def test_workspace_ownership_restart_and_interrupted_recovery(self):
        self.fault('WORKSPACE_LOCKED', lambda: ExecutionService(self.tmp.name))
        job = self.run_job()
        self.service.close()
        self.service = ExecutionService(self.tmp.name)
        self.addCleanup(self.service.close)
        self.assertTrue(self.service.verify(job)['value']['verified'])
        self.service.state['jobs'][job]['status'] = 'running'
        self.service._commit(copy.deepcopy(self.service.state))
        self.service.close()
        self.service = ExecutionService(self.tmp.name)
        self.addCleanup(self.service.close)
        self.assertEqual(self.service.job(job)['status'], 'interrupted')
        self.assertFalse(self.service.job(job)['verified'])
        self.assertEqual(self.service.job(job)['nativeState'], 'unknown')

    def test_uncertain_publication_consumes_visible_revision_and_releases_owner(self):
        def published(path, payload, **kwargs):
            atomic(path, payload, **kwargs)
            if path.name == 'agent.json':
                raise AtomicPublicationError(path, OSError('directory sync failed'))
        with patch('schemaxis.execution_service.atomic', side_effect=published):
            with self.assertRaises(AtomicPublicationError):
                self.plan()
        self.assertEqual(self.service.task(self.task['id'])['revision'], 1)
        self.service.close()
        self.service = ExecutionService(self.tmp.name)
        self.addCleanup(self.service.close)
        self.assertEqual(self.service.task(self.task['id'])['revision'], 1)

    def test_unreconciled_publication_stops_writes_but_can_still_close(self):
        def uncertain(path, payload, **kwargs):
            if path.name == 'agent.json':
                raise AtomicPublicationError(path, OSError('publication could not be reconciled'))
            atomic(path, payload, **kwargs)
        with patch('schemaxis.execution_service.atomic', side_effect=uncertain):
            with self.assertRaises(AtomicPublicationError):
                self.plan()
        self.fault('SESSION_CLOSED', lambda: self.service.task(self.task['id']))
        self.service.close()
        self.service = ExecutionService(self.tmp.name)
        self.addCleanup(self.service.close)
        self.assertEqual(self.service.task(self.task['id'])['revision'], 0)

    def test_corrupted_persistent_state_is_not_accepted(self):
        self.service.close()
        path = Path(self.tmp.name)/'agent.json'
        envelope = json.loads(path.read_text())
        envelope['state']['tasks'].clear()
        path.write_text(json.dumps(envelope))
        self.fault('RECOVERY_FAILED', lambda: ExecutionService(self.tmp.name))

    def test_bounded_observation_reconstruction_and_staleness(self):
        value = {'items': [{'id': i, 'data': 'x'*200} for i in range(100)], 'escaped/key~': [1, 2]}
        first = bounded(value, 'test', pointer='/items', limit=100, max_bytes=2048)
        self.assertEqual(first['mode'], 'members')
        self.assertLessEqual(response_bytes(first), 2048)
        second = bounded(value, 'test', pointer='/items', offset=first['page']['nextOffset'], max_bytes=2048, revision=first['revision'])
        self.assertEqual(second['items'][0]['key'], first['page']['returned'])
        self.assertEqual(bounded(value, 'test', pointer='/escaped~1key~0/1')['value'], 2)
        self.fault('STALE_OBSERVATION', lambda: bounded([], 'test', revision=first['revision']))
        self.fault('INVALID_POINTER', lambda: bounded(value, 'test', pointer='/items/-1'))
        self.fault('OBSERVATION_TOO_LARGE', lambda: bounded('x'*9999, 'test', max_bytes=2048))

    def test_verified_resource_snapshot_preserves_provenance_and_historical_bytes(self):
        job_id = self.run_job()
        original = next(r for r in self.service.state['resources'].values()
                        if r['job'] == job_id and r['name'] == 'data.csv')
        snapshot = self.service.snapshot_resource(original['id'], 'table')
        self.assertEqual(snapshot['provenance']['receiptSha256'], original['receiptSha256'])
        reference = self.service.reference_snapshot(snapshot['id'], snapshot['revision'], 'table-range',
            {'rowStart': 0, 'rowEnd': 2, 'columnStart': 0, 'columnEnd': 2})
        (Path(self.tmp.name)/original['file']).write_text('changed')
        self.fault('RESOURCE_CHANGED', lambda: self.service.snapshot_resource(original['id'], 'table'))
        observed = self.service.inspect_selection(reference['id'])['value']
        self.assertEqual(observed['evidence']['rows'], [['0','1'],['1','2']])
        self.assertIn('historical', snapshot['provenance']['verification'])
        self.service.close()
        self.fault('SESSION_CLOSED', lambda: self.service.inspection_workspace())

    def test_transport_dispatch_and_failure_recovery(self):
        methods = dispatch(self.service, {'id': 1, 'method': 'methods'})
        self.assertIn('execute', methods['methods'])
        self.fault('UNKNOWN_METHOD', lambda: dispatch(self.service, {'id': 2, 'method': '__dict__'}))
        self.fault('INVALID_REQUEST', lambda: dispatch(self.service, {'id': True, 'method': 'methods'}))
        self.fault('INVALID_REQUEST', lambda: dispatch(self.service, {'id': 2, 'method': 'execute', 'params': {}}))
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            serve(directory, io.BytesIO(b'{bad}\n{"id":"ok","method":"methods"}\n'), output)
            responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertFalse(responses[0]['ok'])
        self.assertTrue(responses[1]['ok'])
        self.assertEqual(responses[1]['id'], 'ok')

    def test_discovery_and_planning_remain_native_free_in_fresh_process(self):
        script = r"""
import importlib.abc, sys, tempfile
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'bpy','paraview','vtk','vtkmodules','FreeCAD','FreeCADGui','Part','Mesh','Sketcher','PySide','PySide2'}:
            raise AssertionError('native import: '+fullname)
sys.meta_path.insert(0, NoNative())
def audit(event,args):
    if event in {'subprocess.Popen','os.system','os.posix_spawn','os.fork','os.exec'}:
        raise AssertionError('native process: '+event)
sys.addaudithook(audit)
from schemaxis.execution_service import ExecutionService
from schemaxis.agent_transport import dispatch
with tempfile.TemporaryDirectory() as tmp, ExecutionService(tmp) as service:
    assert dispatch(service, {'id':1,'method':'methods'})['methods']
    task=service.create_task('Host-only proof',['freecad'])
    plan=service.plan(task['id'],{'version':'schemaxis.freecad/1','nodes':[{'id':'body','filter':'box'}],'output':'body'},0)
    assert service.observe(plan_id=plan['id'],section='plan')['value']['output']=='body'
    import json
    draft=service.create_draft('freecad')
    draft=service.edit_draft(draft['document'],draft['revision'],json.dumps({'version':'schemaxis.freecad/1','nodes':[{'id':'body','filter':'box'}],'output':'body'}))
    captured=service.plan_draft(task['id'],1,draft['document'],draft['revision'])
    assert captured['draft']['document']==draft['document']
    from pathlib import Path
    path=Path(tmp)/'sample.csv'
    path.write_text('x,y\n0,1\n1,2\n')
    snapshot=service.capture_inspection(str(path),'table')
    assert service.inspect_snapshot(snapshot['id'],snapshot['revision'],'series',x_column=0,y_column=1)['points']
    assert service.inspection_workspace('table-analysis')['presentation']['preset']=='table-analysis'
    from schemaxis.workflow_authoring import example
    workflow=service.create_draft('workflow')
    workflow=service.edit_draft(workflow['document'],workflow['revision'],json.dumps(example()))
    view=service.workflow_graph(workflow['document'],workflow['revision'])['value']
    assert view['edges'][0]['source']=='samples'
    service.rewire_workflow(workflow['document'],workflow['revision'],view['edges'][0]['pointer'],'samples',0)
"""
        completed = subprocess.run([sys.executable, '-c', script], cwd=ROOT,
            env={**os.environ, 'PYTHONPATH': str(ROOT/'src')}, capture_output=True, text=True, timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)

    def test_public_stdio_cli_emits_only_correlated_response_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-m', 'schemaxis', 'agent', '--workspace', directory],
                input='{"id":1,"method":"capabilities.browse"}\n{"id":2,"method":"no-such-method"}\n',
                text=True, capture_output=True, cwd=ROOT, env={**os.environ, 'PYTHONPATH': str(ROOT/'src')}, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([r['id'] for r in lines], [1, 2])
        self.assertTrue(lines[0]['ok'])
        self.assertEqual(lines[1]['fault']['code'], 'UNKNOWN_METHOD')
