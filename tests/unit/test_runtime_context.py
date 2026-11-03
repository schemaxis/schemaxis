# Copyright (C) 2026 David L F Gaden
"""Trusted native locations and budgets survive real shared execution boundaries."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import ModuleType
import unittest
from unittest.mock import patch

from schemaxis import adaptor_runtime, configuration, dispatch, parallel, workflow
from schemaxis.adaptors import registry
from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.core.faults import SchemaxisError


PROVIDER = 'runtime_fixture'
ORACLE = 'runtime_oracle'
VERSION = 'schemaxis.runtime-fixture/1'
MODULE = '_schemaxis_runtime_context_fixture'


class RuntimeContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.events = []
        self.expected = {}
        self.after_run = lambda document: None
        self.before_verify = lambda document: None
        self.module = ModuleType(MODULE)
        self.route = {'module': MODULE, 'workflow': True, 'compose': True,
                      'scheduled': False, 'acceptedArtifacts': ['text'],
                      'runOptions': {'oracle': ORACLE},
                      'hooks': {'reusableInputs': MODULE + ':reusable_inputs'}}
        entries = {PROVIDER: {'version': VERSION, 'adaptor': MODULE,
                             'routes': {VERSION: self.route}},
                   ORACLE: {'version': 'schemaxis.runtime-oracle/1', 'adaptor': MODULE,
                            'routes': {}}}
        for target, kwargs in (
                (patch.dict, {'in_dict': sys.modules, 'values': {MODULE: self.module}}),
                (patch.dict, {'in_dict': registry.ADAPTORS, 'values': entries})):
            patcher = target(**kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        # This synthetic adaptor has no schema resources. Real registry, input
        # expansion, execution, provider verification and publication checks run.
        for name in ('capture_run', 'verify_run'):
            patcher = patch('schemaxis.schema_snapshots.' + name)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch('schemaxis.configuration.config_path', return_value=self.root/'config.json')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.write_config('/configured', '/configured-oracle')

        def observe(phase, document):
            tools = (configuration.executable(PROVIDER), configuration.executable(ORACLE))
            if document['value'] in self.expected:
                self.assertEqual(tools, self.expected[document['value']])
            self.events.append((phase, document['value'], tools,
                                dispatch.remaining_timeout(1000), dispatch.cancellation_token()))

        def run(document, directory, *, executable=None, oracle=None, timeout=300):
            observe('run', document)
            directory = Path(directory)
            directory.mkdir()
            atomic_json(directory/'authored.json', document)
            artifact = directory/'value.txt'
            artifact.write_text(str(document['value']))
            atomic_json(directory/'verification.json', {
                'executable': '/untrusted-receipt-must-not-be-used',
                'artifacts': [{'file': str(artifact), 'kind': 'text', 'sha256': file_digest(artifact)}]})
            atomic_json(directory/'result.json', {'status': 'succeeded', 'verified': True})
            self.after_run(document)
            return {'verified': True}

        def verify(directory):
            directory = Path(directory)
            document = json.loads((directory/'authored.json').read_text())
            self.before_verify(document)
            observe('verify', document)
            self.assertEqual((directory/'value.txt').read_text(), str(document['value']))
            return {'verified': True}

        self.module.plan = copy.deepcopy
        self.module.run = run
        self.module.verify = verify
        self.module.reusable_inputs = lambda document: {}
        adaptor_runtime.bind(vars(self.module))

    def write_config(self, executable, oracle):
        atomic_json(self.root/'config.json', {'version': 1, 'locations': {
            PROVIDER: executable, ORACLE: oracle}})

    def document(self, value=1):
        return {'version': VERSION, 'value': value}

    def flow(self, scheduled=False):
        document = {'version': 'schemaxis.workflow/1', 'operations': [
            {'id': 'first', 'document': self.document(1)},
            {'id': 'second', 'document': {**self.document(2),
                                         'source': {'$artifact': 'first', 'index': 0}}}]}
        if scheduled:
            document['execution'] = {'maxWorkers': 2, 'cpus': 2, 'memoryMB': 2048, 'gpus': 0}
        return document

    def test_registry_run_and_saved_verify_use_different_trusted_invocations(self):
        self.expected[1] = ('/invocation', '/invocation-oracle')
        registry.run(self.document(), self.root/'run', timeout=17,
                     locations={PROVIDER: '/invocation', ORACLE: '/invocation-oracle'})
        self.assertEqual([e[0] for e in self.events], ['run', 'verify'])
        self.assertTrue(all(0 < e[3] <= 17 for e in self.events))
        self.expected[1] = ('/configured', '/configured-oracle')
        self.assertTrue(registry.verify(self.root/'run')['verified'])
        self.assertEqual(self.events[-1][3], 1000)
        self.assertEqual(configuration.executable(PROVIDER), '/configured')

    def test_direct_bound_run_and_study_retain_reverse_run_options(self):
        self.expected.update({1: ('/direct', '/oracle'), 2: ('/direct', '/oracle')})
        self.module.run(self.document(), self.root/'single', executable='/direct', oracle='/oracle', timeout=19)
        document = self.document({'$document': '/dimensions/value'})
        document['dimensions'] = {'value': {'$analytic': {'type': 'values', 'values': [1, 2]}}}
        self.module.run(document, self.root/'study', executable='/direct', oracle='/oracle', timeout=19)
        self.assertEqual([e[1] for e in self.events if e[0] == 'run'], [1, 1, 2])
        self.assertGreaterEqual(len([e for e in self.events if e[0] == 'verify']), 5)
        self.assertTrue(all(0 < e[3] <= 19 for e in self.events))
        self.assertEqual(configuration.executable(ORACLE), '/configured-oracle')

    def test_nested_context_copies_input_output_and_resets_after_exception(self):
        overrides = {PROVIDER: '/outer', 'roots': ['/root-one']}
        with configuration.location_context(overrides):
            overrides['roots'].append('/caller-mutation')
            overrides[PROVIDER] = '/caller-mutation'
            observed = configuration.locations()
            observed['roots'].append('/returned-mutation')
            self.assertEqual(configuration.locations()['roots'], ['/root-one'])
            with self.assertRaisesRegex(RuntimeError, 'stop'):
                with configuration.location_context({PROVIDER: '/inner', ORACLE: None}):
                    self.assertEqual(configuration.executable(PROVIDER), '/inner')
                    raise RuntimeError('stop')
            self.expected[1] = ('/outer', '/configured-oracle')
            self.module.run(self.document(), self.root/'nested', executable=None, oracle=None)
        self.assertEqual(configuration.executable(PROVIDER), '/configured')
        self.assertNotIn('roots', configuration.locations())

    def test_failed_run_restores_context_and_deadline(self):
        def broken(document):
            raise RuntimeError('native failure')
        self.after_run = broken
        with self.assertRaisesRegex(RuntimeError, 'native failure'):
            self.module.run(self.document(), self.root/'failure', executable='/temporary', timeout=10)
        self.assertEqual(configuration.executable(PROVIDER), '/configured')
        self.assertEqual(dispatch.remaining_timeout(1000), 1000)

    def test_roots_aliases_are_normalized_before_precedence_is_applied(self):
        for parent, child in (({'paraview': '/parent'}, {'roots': ['/child']}),
                              ({'roots': ['/parent']}, {'paraview': '/child'})):
            with self.subTest(parent=parent, child=child):
                with configuration.location_context(parent):
                    self.assertEqual(configuration.locations(child)['roots'], ['/child'])
                    with configuration.location_context(child):
                        self.assertEqual(configuration.executable('paraview'), '/child')
                        self.assertNotIn('paraview', configuration.locations())
                    self.assertEqual(configuration.executable('paraview'), '/parent')
        atomic_json(self.root/'config.json', {'version': 1, 'locations': {'paraview': '/configured-root'}})
        self.assertEqual(configuration.locations({'roots': ['/explicit']})['roots'], ['/explicit'])

    def test_parallel_worker_cannot_extend_enclosing_study_deadline(self):
        clock = [100.0]
        self.after_run = lambda document: clock.__setitem__(0, 111.0)
        with patch('schemaxis.dispatch._clock', side_effect=lambda: clock[0]):
            with dispatch.execution_deadline(10):
                with self.assertRaises(SchemaxisError) as caught:
                    parallel.execute(self.flow(scheduled=True), self.root/'parent-budget', timeout=100)
        self.assertEqual(caught.exception.fault.code, 'RUNNER_TIMED_OUT')

    def test_two_concurrent_direct_invocations_are_isolated(self):
        barrier = threading.Barrier(2)
        self.after_run = lambda document: barrier.wait(timeout=5)
        self.expected = {1: ('/one', '/oracle-one'), 2: ('/two', '/oracle-two')}
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.module.run, self.document(value), self.root/str(value),
                                   executable=tools[0], oracle=tools[1], timeout=20)
                       for value, tools in self.expected.items()]
            for future in futures:
                self.assertTrue(future.result(timeout=10)['verified'])
        self.assertEqual(len(self.events), 4)
        self.assertEqual(configuration.executable(PROVIDER), '/configured')

    def test_ordinary_workflow_handoff_reverification_keeps_locations_and_budget(self):
        self.expected = {1: ('/workflow', '/workflow-oracle'), 2: ('/workflow', '/workflow-oracle')}
        result = workflow.execute(self.flow(), self.root/'flow', timeout=23,
                                  locations={PROVIDER: '/workflow', ORACLE: '/workflow-oracle'})
        self.assertTrue(result['verified'])
        self.assertEqual(len([e for e in self.events if e[0] == 'verify' and e[1] == 1]), 2)
        self.assertTrue(all(0 < e[3] <= 23 for e in self.events))

    def test_parallel_postrun_handoff_and_resume_reuse_keep_locations(self):
        self.expected = {1: ('/parallel', '/parallel-oracle'), 2: ('/parallel', '/parallel-oracle')}
        kwargs = {'timeout': 29, 'locations': {PROVIDER: '/parallel', ORACLE: '/parallel-oracle'}}
        result = workflow.execute(self.flow(scheduled=True), self.root/'parallel', **kwargs)
        self.assertTrue(result['verified'])
        self.assertEqual(len([e for e in self.events if e[0] == 'run']), 2)
        for value in (1, 2):
            verifications = [e for e in self.events if e[0] == 'verify' and e[1] == value]
            # Both common verification and worker's extra verification retain
            # the owned cancellation token. Handoff verification is coordinator-side.
            self.assertEqual(len([e for e in verifications if e[4] is not None]), 2)
        self.events.clear()
        resumed = workflow.execute(self.flow(scheduled=True), self.root/'parallel', resume=True, **kwargs)
        self.assertTrue(all(job['reused'] for job in resumed['jobs']))
        self.assertFalse(any(e[0] == 'run' for e in self.events))
        self.assertGreaterEqual(len(self.events), 3)
        self.assertTrue(all(0 < e[3] <= 29 for e in self.events))
        self.assertEqual(configuration.executable(PROVIDER), '/configured')

    def test_parallel_verification_observes_parent_cancellation(self):
        parent = threading.Event()
        checks = []
        def cancel_during_verify(document):
            checks.append(document['value'])
            if len(checks) == 2:
                # The common adaptor verification already finished. Cancel
                # during the worker's additional check after run_native returns.
                parent.set()
        self.before_verify = cancel_during_verify
        with dispatch.allocation({}, parent), self.assertRaises(SchemaxisError) as caught:
            parallel.execute(self.flow(scheduled=True), self.root/'cancelled', timeout=30)
        self.assertEqual(caught.exception.fault.code, 'RUNNER_CANCELLED')
        self.assertFalse(json.loads((self.root/'cancelled/result.json').read_text())['verified'])
        self.assertIsNone(dispatch.cancellation_token())

    def test_parallel_timeout_is_per_job_and_includes_worker_verification(self):
        clock = [100.0]
        self.after_run = lambda document: clock.__setitem__(0, clock[0] + 8)
        with patch('schemaxis.dispatch._clock', side_effect=lambda: clock[0]):
            result = parallel.execute(self.flow(scheduled=True), self.root/'budgets', timeout=10)
        self.assertTrue(result['verified'])
        self.assertEqual(clock[0], 116.0)
        self.assertTrue(all(e[3] == 2 for e in self.events if e[0] == 'verify' and e[4] is not None))

    def test_parallel_worker_extra_verification_cannot_reset_job_timeout(self):
        clock = [100.0]
        checks = []
        def expire_during_verify(document):
            checks.append(document['value'])
            if len(checks) == 2:
                clock[0] = 111.0
        self.before_verify = expire_during_verify
        with patch('schemaxis.dispatch._clock', side_effect=lambda: clock[0]):
            with self.assertRaises(SchemaxisError) as caught:
                parallel.execute(self.flow(scheduled=True), self.root/'late-check', timeout=10)
        self.assertEqual(caught.exception.fault.code, 'RUNNER_TIMED_OUT')

    def test_workflow_copies_location_arguments_before_caller_mutation(self):
        supplied = {PROVIDER: '/snapshot', ORACLE: '/snapshot-oracle'}
        self.expected = {1: ('/snapshot', '/snapshot-oracle'), 2: ('/snapshot', '/snapshot-oracle')}
        def change_caller_mapping(document):
            supplied.update({PROVIDER: '/changed', ORACLE: '/changed-oracle'})
        self.after_run = change_caller_mapping
        workflow.execute(self.flow(scheduled=True), self.root/'snapshot', locations=supplied)
        self.assertEqual(supplied[PROVIDER], '/changed')

    def test_interrupted_reuse_check_does_not_launch_replacement_attempt(self):
        for cancelled in (False, True):
            with self.subTest(cancelled=cancelled):
                directory = self.root/('reuse-' + str(cancelled))
                self.before_verify = lambda document: None
                parallel.execute(self.flow(scheduled=True), directory, timeout=10)
                self.events.clear()
                clock, parent = [100.0], threading.Event()
                def interrupt(document):
                    if cancelled:
                        parent.set()
                    else:
                        clock[0] = 111.0
                self.before_verify = interrupt
                with dispatch.allocation({}, parent), patch('schemaxis.dispatch._clock', side_effect=lambda: clock[0]):
                    with self.assertRaises(SchemaxisError) as caught:
                        parallel.execute(self.flow(scheduled=True), directory, resume=True, timeout=10)
                self.assertEqual(caught.exception.fault.code,
                                 'RUNNER_CANCELLED' if cancelled else 'RUNNER_TIMED_OUT')
                self.assertFalse(any(event[0] == 'run' for event in self.events))

    def test_expired_budget_is_seen_during_postrun_verification(self):
        clock = [100.0]
        self.after_run = lambda document: clock.__setitem__(0, 111.0)
        with patch('schemaxis.dispatch._clock', side_effect=lambda: clock[0]):
            with self.assertRaises(SchemaxisError) as caught:
                registry.run(self.document(), self.root/'expired', timeout=10)
        self.assertEqual(caught.exception.fault.code, 'RUNNER_TIMED_OUT')
        self.assertFalse(json.loads((self.root/'expired/result.json').read_text())['verified'])
        self.assertEqual(dispatch.remaining_timeout(1000), 1000)

    def test_nested_deadline_cannot_extend_enclosing_budget(self):
        clock = [100.0]
        with patch('schemaxis.dispatch._clock', side_effect=lambda: clock[0]):
            with dispatch.execution_deadline(12):
                clock[0] = 103.0
                with dispatch.execution_deadline(100):
                    self.assertEqual(dispatch.remaining_timeout(1000), 9)
                with dispatch.execution_deadline(2):
                    self.assertEqual(dispatch.remaining_timeout(1000), 2)
                self.assertEqual(dispatch.remaining_timeout(1000), 9)
            self.assertEqual(dispatch.remaining_timeout(1000), 1000)

    def test_missing_standalone_configuration_does_not_trust_receipt(self):
        registry.run(self.document(), self.root/'saved')
        (self.root/'config.json').unlink()
        self.expected[1] = (None, None)
        with patch('subprocess.Popen', side_effect=AssertionError('receipt execution prohibited')):
            registry.verify(self.root/'saved')
        self.assertEqual(self.events[-1][2], (None, None))


if __name__ == '__main__':
    unittest.main()
