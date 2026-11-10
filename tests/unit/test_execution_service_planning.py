"""Contained-planning lifecycle with explicit host doubles; no native qualification."""
import copy
import hashlib
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from schemaxis.capabilities import digest
from schemaxis.core.faults import SchemaxisError, Fault
from schemaxis.execution_backends import ExecutionOutcome, VerificationOutcome
from schemaxis.execution_inputs import (CapturePolicy, CapturedInput, InputBindings,
    PlanningOutcome, bindings_record, bind_document)
from schemaxis.execution_service import ExecutionService
from schemaxis.jobs import Cancellation
from schemaxis.mcp_admission import FileAdmission
from schemaxis.storage import atomic, encoded, AtomicPublicationError

DOCUMENT = {'version':'schemaxis.numpy/1','operation':'principalComponents','source':'upload-one',
            'channels':[{'name':'a','unit':'mV'},{'name':'b','unit':'mV'}],
            'scaling':'none','retention':{'components':1}}
PLAN = 'plan-'+'a'*32


class IsolatedDouble:
    isolated = True

    def __init__(self, policy):
        self.capture_policy = policy
        self.calls = []
        self.planned = {'fixture': 'declared-plan'}
        self.plan_error = None
        self.cancel_after_plan = False
        self.cleanup_unknown = False
        self.entered = threading.Event()
        self.resume = threading.Event()
        self.resume.set()
        self.verifications = 0

    def admit(self, document, inputs=None, *, bound=False):
        return FileAdmission().check(document, inputs, bound=bound)

    def recover(self, workspace):
        if self.cleanup_unknown:
            raise SchemaxisError(Fault('ISOLATION_RECOVERY_FAILED', 'fixture cleanup unknown', '$', 'isolation'))
        return []

    def plan(self, request, cancellation):
        self.calls.append(request)
        isolation = {'action':'plan', 'operationId':request.operation_id, 'planningPhase':request.phase,
                     'containerId':'fixture-'+request.operation_id, 'containerExited':True,
                     'cleanup':{'removed':True,'containerAbsent':True}, 'fixtureOnly':True}
        if self.plan_error:
            raise SchemaxisError(Fault(self.plan_error, 'fixture planner failure', '$', 'planning',
                                      observed={'isolation':isolation}))
        if self.cancel_after_plan: cancellation.set()
        return PlanningOutcome(copy.deepcopy(self.planned), isolation)

    def run(self, request, cancellation):
        self.entered.set()
        if not self.resume.wait(3): raise AssertionError('fixture release timed out')
        self.capture_policy.lease(request.inputs).close()
        request.directory.mkdir(parents=True)
        atomic(request.directory/'authored.json', encoded(request.document))
        atomic(request.directory/'verification.json', encoded({'verified':True}))
        return ExecutionOutcome({'fixtureOnly':True})

    def verify(self, request, cancellation):
        self.verifications += 1
        self.capture_policy.lease(request.execution.inputs).close()
        return VerificationOutcome({'verified':True,'fixtureOnly':True}, publications=[])


class ContainedPlanningTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        captures = root/'captures'; captures.mkdir(mode=0o700)
        source = captures/'upload-one.csv'
        data = b'a,b\n1,2\n2,4\n'
        source.write_bytes(data); source.chmod(0o444)
        details = source.stat()
        self.inputs = InputBindings('fixture-task', (CapturedInput('upload-one',source,
            'sha256:'+hashlib.sha256(data).hexdigest(),len(data),details.st_dev,details.st_ino),),
            (('/source','upload-one'),))
        self.backend = IsolatedDouble(CapturePolicy(captures,'fixture-task',1024,2))
        self.service = ExecutionService(root/'state', executor=self.backend)
        self.addCleanup(self.clean_service)
        self.task = self.service.create_task('Contained planning fixture', ['numpy'])

    def clean_service(self):
        self.backend.cleanup_unknown = False
        self.backend.resume.set()
        self.service.close()

    def plan(self, **kwargs):
        return self.service.plan_with_inputs(self.task['id'], copy.deepcopy(DOCUMENT), 0,
            inputs=self.inputs, operation_id='capture-one', plan_id=PLAN, **kwargs)

    def refused(self, code, function):
        with self.assertRaises(SchemaxisError) as caught: function()
        self.assertEqual(caught.exception.fault.code, code)
        return caught.exception.fault

    def test_capture_is_bound_inside_backend_without_host_planner_and_replays(self):
        with patch('schemaxis.execution_service.registry.plan', side_effect=AssertionError('host planner')):
            result = self.plan()
            self.assertEqual(self.plan(), result)
        self.assertEqual(len(self.backend.calls), 1)
        request = self.backend.calls[0]
        self.assertEqual(request.document, bind_document(DOCUMENT, self.inputs))
        self.assertEqual(result['documentDigest'], digest(request.document))
        self.assertEqual(result['inputs'], bindings_record(self.inputs))
        self.assertEqual(self.service.task(self.task['id'])['revision'], 1)
        result['inputs']['namespace'] = 'mutated'
        self.assertEqual(self.plan()['inputs']['namespace'], 'fixture-task')
        self.refused('PLANNING_OPERATION_CONFLICT', lambda: self.service.plan_with_inputs(
            self.task['id'], {**DOCUMENT,'scaling':'standardize'},0, inputs=self.inputs,
            operation_id='capture-one',plan_id=PLAN))

    def test_policy_refuses_before_capture_read_or_planner(self):
        document = {**DOCUMENT, 'unreviewedPath':'/unexpected'}
        with patch.object(CapturePolicy, 'lease', side_effect=AssertionError('capture read')):
            self.refused('MCP_POLICY_DENIED', lambda: self.service.plan_with_inputs(
                self.task['id'],document,0,inputs=self.inputs,operation_id='bad-policy',plan_id=PLAN))
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(self.service.planning_for_operation('bad-policy')['status'], 'failed')

    def test_failure_keeps_exact_isolation_without_advancing_revision_or_retry(self):
        self.backend.plan_error = 'FIXTURE_NATIVE_FAILURE'
        fault = self.refused('FIXTURE_NATIVE_FAILURE', self.plan)
        record = self.service.planning_for_operation('capture-one')
        self.assertEqual(record['fault'], fault.to_dict())
        self.assertEqual(record['isolation'], fault.to_dict()['observed']['isolation'])
        self.assertEqual(self.service.task(self.task['id'])['revision'], 0)
        self.refused('FIXTURE_NATIVE_FAILURE', self.plan)
        self.assertEqual(len(self.backend.calls), 1)

    def test_cancelled_planning_cannot_commit_authority(self):
        self.backend.cancel_after_plan = True
        self.refused('RUNNER_CANCELLED', self.plan)
        record = self.service.planning_for_operation('capture-one')
        self.assertEqual(record['status'], 'failed')
        self.assertIsNotNone(record['isolation'])
        self.assertEqual(self.service.state['plans'], {})
        self.assertEqual(self.service.task(self.task['id'])['revision'], 0)

    def test_deadline_and_stage_cap_apply_before_first_native_task_start(self):
        deadline = time.monotonic()+2
        self.plan(deadline=deadline, stage_timeout=.5)
        request = self.backend.calls[0]
        self.assertLessEqual(request.deadline, deadline)
        self.assertLessEqual(request.stage_timeout, .5)
        self.assertIsNotNone(self.service.task(self.task['id'])['startedAt'])
        self.refused('TIME_BUDGET_EXCEEDED', lambda: self.service.execute_with_control(
            PLAN,1,operation_id='expired-execute',deadline=time.monotonic()-1))
        self.assertEqual(self.service.planning_for_operation('expired-execute')['status'], 'failed')
        self.assertEqual(len(self.backend.calls), 1)

    def test_stale_check_failure_retains_meter_evidence_without_job(self):
        self.plan()
        self.backend.planned = {'fixture':'changed-plan'}
        with patch('schemaxis.execution_service.registry.plan', side_effect=AssertionError('host planner')):
            self.refused('STALE_PLAN', lambda: self.service.execute_with_control(PLAN,1,operation_id='execute-one'))
        record = self.service.planning_for_operation('execute-one')
        self.assertEqual(record['phase'], 'stale-check')
        self.assertEqual(record['isolation']['operationId'], 'execute-one')
        self.assertEqual(self.service.state['jobs'], {})
        self.assertEqual(self.service.task(self.task['id'])['attempts'], 0)
        self.refused('STALE_PLAN', lambda: self.service.execute_with_control(PLAN,1,operation_id='execute-one'))
        self.assertEqual(len(self.backend.calls), 2)

    def test_capture_lease_spans_async_run_fresh_verify_and_replay(self):
        self.plan(); self.backend.resume.clear()
        job = self.service.execute_with_control(PLAN,1,operation_id='execute-one')
        self.assertTrue(self.backend.entered.wait(2))
        self.refused('INPUTS_BUSY', lambda: self.backend.capture_policy.lease(exclusive=True))
        self.assertEqual(self.service.execute_with_control(PLAN,1,operation_id='execute-one')['id'], job['id'])
        self.backend.resume.set()
        self.service.runner.futures[job['id']].result(timeout=3)
        self.assertEqual(self.service.job(job['id'])['status'], 'succeeded')
        self.assertEqual(self.backend.verifications, 1)
        with self.backend.capture_policy.lease(exclusive=True): pass
        self.service.verify(job['id'])
        self.assertEqual(self.backend.verifications, 2)
        self.assertEqual(len(self.backend.calls), 2)

    def test_reverification_cannot_overlap_another_active_isolated_job(self):
        self.plan()
        first = self.service.execute_with_control(PLAN,1,operation_id='first-execute')
        self.service.runner.futures[first['id']].result(timeout=3)
        self.backend.entered.clear(); self.backend.resume.clear()
        second = self.service.execute_with_control(PLAN,1,operation_id='second-execute')
        self.assertTrue(self.backend.entered.wait(2))
        self.refused('SESSION_BUSY', lambda: self.service.verify(first['id']))
        self.assertEqual(self.backend.verifications, 1)
        self.backend.resume.set()
        self.service.runner.futures[second['id']].result(timeout=3)
        self.assertEqual(self.service.job(second['id'])['status'], 'succeeded')

    def test_unresolved_execution_cleanup_blocks_old_job_reverification(self):
        self.plan()
        first = self.service.execute_with_control(PLAN,1,operation_id='first-execute')
        self.service.runner.futures[first['id']].result(timeout=3)
        def uncertain(request, cancellation):
            self.backend.cleanup_unknown = True
            raise SchemaxisError(Fault('FIXTURE_FAILURE','fixture run failure','$','execution'))
        self.backend.run = uncertain
        second = self.service.execute_with_control(PLAN,1,operation_id='second-execute')
        self.service.runner.futures[second['id']].result(timeout=3)
        self.assertEqual(self.service.job(second['id'])['status'], 'interrupted')
        self.refused('ISOLATION_RECOVERY_FAILED', lambda: self.service.verify(first['id']))
        self.assertEqual(self.backend.verifications, 1)
        self.backend.cleanup_unknown = False
        self.service.verify(first['id'])
        self.assertEqual(self.backend.verifications, 2)

    def test_cleanup_unknown_retains_lease_and_prevents_new_dispatch(self):
        original = self.backend.plan
        def uncertain(request, cancellation):
            outcome = original(request,cancellation)
            self.backend.cleanup_unknown = True
            raise SchemaxisError(Fault('FIXTURE_FAILURE','fixture failure','$','planning',
                                      observed={'isolation':outcome.isolation}))
        self.backend.plan = uncertain
        self.refused('ISOLATION_RECOVERY_FAILED', self.plan)
        self.assertEqual(self.service.state['planningOperations']['capture-one']['status'], 'interrupted')
        self.refused('INPUTS_BUSY', lambda: self.backend.capture_policy.lease(exclusive=True))
        self.refused('PLANNING_UNCERTAIN', lambda: self.service.plan_with_inputs(self.task['id'],DOCUMENT,0,
            inputs=self.inputs,operation_id='capture-two',plan_id='plan-'+'b'*32))
        self.backend.cleanup_unknown = False
        record = self.service.planning_for_operation('capture-one')
        self.assertEqual(record['status'], 'failed')
        self.assertEqual(record['fault']['code'], 'FIXTURE_FAILURE')
        with self.backend.capture_policy.lease(exclusive=True): pass

    def test_reopen_intent_is_never_redispatched_and_requires_isolated_recovery(self):
        self.service._begin_planning(self.task,PLAN,'unresolved','capture','fixture-fingerprint',self.inputs)
        workspace = self.service.workspace
        self.service.close()
        self.refused('ISOLATION_RECOVERY_REQUIRED', lambda: ExecutionService(workspace))
        self.service = ExecutionService(workspace,executor=self.backend)
        record = self.service.planning_for_operation('unresolved')
        self.assertEqual(record['status'], 'failed')
        self.assertEqual(record['fault']['code'], 'INTERRUPTED')
        self.assertEqual(self.backend.calls, [])

    def test_corrupt_capture_does_not_skip_owned_container_recovery_on_reopen(self):
        self.service._begin_planning(self.task,PLAN,'unresolved','capture','fixture-fingerprint',self.inputs)
        workspace = self.service.workspace
        self.service.close()
        self.inputs.captures[0].path.unlink()
        with patch.object(self.backend, 'recover', wraps=self.backend.recover) as recovery:
            self.refused('INPUT_CAPTURE_CHANGED', lambda: ExecutionService(workspace,executor=self.backend))
            recovery.assert_called_once_with(workspace)
        self.assertEqual(self.backend.calls, [])

    def test_cleaned_sidecar_restores_usage_without_reconstructing_plan_success(self):
        self.service._begin_planning(self.task,PLAN,'unresolved','capture','fixture-fingerprint',self.inputs)
        state = copy.deepcopy(self.service.state)
        state['planningOperations']['unresolved']['status'] = 'running'
        self.service._commit(state)
        workspace = self.service.workspace
        self.service.close()
        isolation = {'action':'plan','operationId':'unresolved','planningPhase':'capture',
                     'containerExited':True,'cleanup':{'removed':True,'containerAbsent':True},
                     'workerObservations':{'fixtureOnly':True}}
        observed = {'action':'plan','operationId':'unresolved','planningPhase':'capture',
                    'planId':PLAN,'isolation':isolation}
        with patch.object(self.backend, 'recover', return_value=[observed]):
            self.service = ExecutionService(workspace,executor=self.backend)
        record = self.service.planning_for_operation('unresolved')
        self.assertEqual(record['status'],'failed')
        self.assertEqual(record['fault']['code'],'INTERRUPTED')
        self.assertEqual(record['isolation'],isolation)
        self.assertIsNone(record['plan'])
        self.assertEqual(self.service.task(self.task['id'])['revision'],0)
        self.assertEqual(self.backend.calls,[])
        for records in ([observed,observed],[{**observed,'planId':'plan-'+'b'*32}],
                        [{**observed,'planningPhase':'stale-check'}]):
            self.assertIsNone(self.service._recovered_planning_isolation(record,records))

    def test_visible_atomic_commit_failure_does_not_reuse_captured_revision(self):
        original = self.service._commit
        def commit(state):
            original(state)
            if state['planningOperations'].get('capture-one',{}).get('status') == 'succeeded':
                raise AtomicPublicationError(self.service.workspace/'agent.json', OSError('fixture directory sync failure'))
        with patch.object(self.service, '_commit', side_effect=commit):
            with self.assertRaises(AtomicPublicationError): self.plan()
        self.assertEqual(self.service.task(self.task['id'])['revision'], 1)
        self.assertEqual(self.plan()['id'], PLAN)
        self.assertEqual(len(self.backend.calls), 1)

    def test_changed_capture_identity_refuses_before_native_recheck(self):
        self.plan()
        path = self.inputs.captures[0].path
        replacement = path.with_suffix('.replacement')
        replacement.write_bytes(path.read_bytes()); replacement.chmod(0o444)
        replacement.replace(path)
        self.refused('INPUT_CAPTURE_CHANGED', lambda: self.service.execute_with_control(PLAN,1,operation_id='changed-input'))
        self.assertEqual(len(self.backend.calls), 1)
        self.assertEqual(self.service.planning_for_operation('changed-input')['status'], 'failed')

    def test_cancel_parent_reaches_contained_stale_check_without_new_clock(self):
        self.plan()
        token = Cancellation(); token.set()
        self.refused('RUNNER_CANCELLED', lambda: self.service.execute_with_control(
            PLAN,1,operation_id='cancel-execute',cancellation=token))
        self.assertEqual(len(self.backend.calls), 1)
        self.assertEqual(self.service.planning_for_operation('cancel-execute')['status'], 'failed')


if __name__ == '__main__': unittest.main()
