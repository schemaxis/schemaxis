"""Scheduling invariants: isolation, dependencies, budgets, retry and cancellation."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from schemaxis.core.faults import SchemaxisError
from schemaxis.core.runners import Interpreter
from schemaxis.artifacts import atomic_json
from schemaxis.dispatch import SubprocessRunner, allocation
from schemaxis.parallel import execute, verify, work_items


def workflow(count=3, **budget):
    return {'version': 'schemaxis.workflow/1',
            'execution': {'maxWorkers': 2, 'cpus': 2, 'memoryMB': 2048, 'gpus': 0, **budget},
            'operations': [{'id': 'job'+str(i), 'document': {'version': 'schemaxis/1', 'test': i}}
                           for i in range(count)]}


def fake_verify(directory, expected):
    if json.loads((Path(directory)/'authored.json').read_text()) != expected:
        raise ValueError('wrong input')
    receipt = json.loads((Path(directory)/'verification.json').read_text())
    if not (Path(directory)/'data.vtp').exists():
        raise ValueError('missing artifact')
    return receipt


def fake_run(document, directory, *args):
    directory.mkdir()
    atomic_json(directory/'authored.json', document)
    (directory/'data.vtp').write_text('verified test data')
    atomic_json(directory/'verification.json', {'artifacts': [{'file': str(directory/'data.vtp'),
                 'identity': {'kind': 'geometry'}}]})
    return {'verified': True}


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        patcher = patch('schemaxis.parallel.reusable_inputs', return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_new_nested_and_existing_empty_outputs_preserve_resume(self):
        doc = workflow(1)
        with tempfile.TemporaryDirectory() as temp, patch('schemaxis.parallel.run_native', side_effect=fake_run) as runner, patch('schemaxis.parallel.verify_native', side_effect=fake_verify):
            for existing in (False, True):
                target = Path(temp) / str(existing) / 'nested' / 'run'
                if existing:
                    target.mkdir(parents=True)
                with self.subTest(existing=existing):
                    self.assertTrue(execute(doc, target)['verified'])
                    self.assertTrue(verify(target)['verified'])
                    count = runner.call_count
                    with self.assertRaises(SchemaxisError) as caught:
                        execute(doc, target)
                    self.assertEqual(caught.exception.fault.code, 'OUTPUT_EXISTS')
                    self.assertTrue(execute(doc, target, resume=True)['verified'])
                    self.assertEqual(runner.call_count, count)

    def test_concurrency_is_real_and_output_order_is_planned(self):
        barrier = threading.Barrier(2)
        def run(doc, target, *args):
            if doc['test'] < 2:
                barrier.wait(timeout=3)
            if doc['test'] == 0:
                time.sleep(.04)
            return fake_run(doc, target)
        with tempfile.TemporaryDirectory() as tmp, patch('schemaxis.parallel.run_native', side_effect=run), patch('schemaxis.parallel.verify_native', side_effect=fake_verify):
            result = execute(workflow(), Path(tmp)/'run')
            self.assertEqual([j['id'] for j in result['jobs']], ['job0/0', 'job1/0', 'job2/0'])
            self.assertTrue(verify(Path(tmp)/'run')['verified'])

    def test_parent_cancellation_reaches_scheduled_workers(self):
        from schemaxis.dispatch import cancellation_requested
        entered = threading.Event()
        parent = threading.Event()
        result = []
        def run(doc, target, *args):
            entered.set()
            deadline = time.monotonic()+3
            while not cancellation_requested() and time.monotonic()<deadline:
                time.sleep(.005)
            from schemaxis.errors import fail
            fail('RUNNER_CANCELLED', 'parent cancellation reached worker')
        def coordinate(directory):
            try:
                with allocation({}, parent):
                    execute(workflow(count=1), directory)
            except SchemaxisError as error:
                result.append(error.fault.code)
        with tempfile.TemporaryDirectory() as tmp, patch('schemaxis.parallel.run_native', side_effect=run):
            thread = threading.Thread(target=coordinate, args=(Path(tmp)/'run',))
            thread.start()
            self.assertTrue(entered.wait(2))
            parent.set()
            thread.join(timeout=4)
            self.assertFalse(thread.is_alive())
            self.assertEqual(result, ['RUNNER_CANCELLED'])
            self.assertFalse(json.loads((Path(tmp)/'run/result.json').read_text())['verified'])

    def test_failure_cancels_an_active_native_sibling(self):
        barrier = threading.Barrier(2)
        def run(doc, target, *args):
            target.mkdir()
            barrier.wait(timeout=3)
            code = 'import time, sys\ntime.sleep(.2)\nsys.exit(1)' if doc['test'] == 0 else 'import time\ntime.sleep(30)'
            return SubprocessRunner(Interpreter('python', sys.executable), target)(code)
        with tempfile.TemporaryDirectory() as tmp, patch('schemaxis.parallel.run_native', side_effect=run):
            started = time.monotonic()
            with self.assertRaises(SchemaxisError):
                execute(workflow(2), Path(tmp)/'run')
            self.assertLess(time.monotonic()-started, 5)
            metrics = [json.loads(p.read_text()) for p in Path(tmp).rglob('*.metrics.json')]
            self.assertIn('RUNNER_CANCELLED', [m['fault'] for m in metrics])

    def test_dependency_waits_for_verified_producer(self):
        doc = workflow(2)
        doc['operations'][1]['document']['file'] = {'$artifact': 'job0', 'index': 0}
        seen = []
        def run(value, target, *args):
            if value['test'] == 1:
                self.assertEqual(seen, [0])
                self.assertTrue(Path(value['file']).is_file())
            result = fake_run(value, target)
            seen.append(value['test'])
            return result
        # This fixture tests scheduling, not an adaptor document. Dependent
        # inputs now receive a full host plan after receipt resolution.
        with tempfile.TemporaryDirectory() as tmp, patch('schemaxis.parallel.run_native', side_effect=run), patch('schemaxis.parallel.verify_native', side_effect=fake_verify), patch('schemaxis.parallel.registry.plan', return_value={}):
            execute(doc, Path(tmp)/'run')
            self.assertEqual(seen, [0, 1])

    def test_memory_budget_serialises_jobs(self):
        active, peak = 0, 0
        lock = threading.Lock()
        def run(doc, target, *args):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(.02)
            result = fake_run(doc, target)
            with lock:
                active -= 1
            return result
        with tempfile.TemporaryDirectory() as tmp, patch('schemaxis.parallel.run_native', side_effect=run), patch('schemaxis.parallel.verify_native', side_effect=fake_verify):
            execute(workflow(memoryMB=1024), Path(tmp)/'run')
            self.assertEqual(peak, 1)

    def test_failed_attempt_retained_and_verified_success_reused(self):
        doc = workflow(2, maxWorkers=1)
        failed = True
        def run(value, target, *args):
            fake_run(value, target)
            if value['test'] == 1 and failed:
                raise RuntimeError('deliberate failure')
            return {'verified': True}
        with tempfile.TemporaryDirectory() as tmp, patch('schemaxis.parallel.run_native', side_effect=run), patch('schemaxis.parallel.verify_native', side_effect=fake_verify):
            target = Path(tmp)/'run'
            with self.assertRaises(RuntimeError):
                execute(doc, target)
            failed = False
            result = execute(doc, target, resume=True)
            self.assertTrue(result['jobs'][0]['reused'])
            self.assertFalse(result['jobs'][1]['reused'])
            self.assertTrue((target/'job1/batch-0/attempt-0001').is_dir())
            self.assertTrue((target/'job1/batch-0/attempt-0002/job.json').is_file())
            # A missing output invalidates reuse, even with a success receipt.
            Path(result['jobs'][0]['directory'], 'data.vtp').unlink()
            result = execute(doc, target, resume=True)
            self.assertFalse(result['jobs'][0]['reused'])

    def test_time_chunks_preserve_exact_membership(self):
        doc = workflow(1)
        doc['operations'][0]['document'] = {'version': 'schemaxis/1', 'times': [0, 1, 2, 3, 4],
            'nodes': [{'id': 'sphere', 'filter': 'sphere'}], 'scenes': [{'id': 'view', 'geometry': ['sphere']}]}

        doc['operations'][0]['execution'] = {'timeChunkSize': 2}
        jobs = work_items(doc)[2]
        self.assertEqual([j['timeIndices'] for j in jobs], [[0, 1], [2, 3], [4]])
        self.assertEqual([j['document']['times'] for j in jobs], [[0, 1], [2, 3], [4]])
        doc['operations'][0]['document']['maxPublications'] = 2
        with self.assertRaises(SchemaxisError):
            work_items(doc)

    def test_invalid_allocations_fail_before_output_creation(self):
        for spec in [{'threads': True}, {'threads': 3}, {'memoryMB': 4096}, {'gpus': 1}, {'timeChunkSize': 0}]:
            doc = workflow(1)
            doc['operations'][0]['execution'] = spec
            with self.subTest(spec=spec), self.assertRaises(SchemaxisError):
                work_items(doc)

    def test_resume_rejects_changed_input_and_verifier_rejects_duplicate_job(self):
        with tempfile.TemporaryDirectory() as tmp, patch('schemaxis.parallel.run_native', side_effect=fake_run), patch('schemaxis.parallel.verify_native', side_effect=fake_verify):
            doc = workflow(1)
            target = Path(tmp)/'run'
            result = execute(doc, target)
            changed = copy.deepcopy(doc)
            changed['operations'][0]['document']['test'] = 99
            with self.assertRaises(SchemaxisError):
                execute(changed, target, resume=True)
            result['jobs'].append(result['jobs'][0])
            atomic_json(target/'result.json', result)
            with self.assertRaises(SchemaxisError):
                verify(target)


class InputProvenanceTests(unittest.TestCase):
    def test_unknown_external_readers_are_not_reused(self):
        from schemaxis.parallel import reusable_inputs
        doc = {'version': 'schemaxis/1', 'nodes': [{'id': 'mesh', 'filter': 'readSurface', 'options': {'files': ['/tmp/a.vtp']}}],
               'scenes': [{'id': 'view', 'geometry': ['mesh']}]}
        self.assertIsNone(reusable_inputs(doc))


class DispatchTests(unittest.TestCase):
    def test_timeout_kills_process_group_and_keeps_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = SubprocessRunner(Interpreter('python', sys.executable), Path(tmp), timeout=.2)
            with self.assertRaises(SchemaxisError) as caught:
                runner('import time\nprint("started", flush=True)\ntime.sleep(30)\n')
            self.assertEqual(caught.exception.fault.code, 'RUNNER_TIMED_OUT')
            self.assertIn('started', next(Path(tmp).glob('*.stdout.log')).read_text())
            self.assertTrue(next(Path(tmp).glob('*.metrics.json')).exists())

    def test_separate_session_children_are_measured_and_terminated(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = ("import subprocess, sys, time\n"
                      "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)\n"
                      f"open({str(root/'child.pid')!r}, 'w').write(str(child.pid))\n"
                      "time.sleep(.4)\n")
            SubprocessRunner(Interpreter('python', sys.executable), root)(source)
            child = int((root/'child.pid').read_text())
            status = Path(f'/proc/{child}/stat')
            deadline = time.monotonic()+2
            while status.exists() and status.read_text().rsplit(')', 1)[1].split()[0] != 'Z' and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(not status.exists() or status.read_text().rsplit(')', 1)[1].split()[0] == 'Z')
            metrics = json.loads(next(root.glob('*.metrics.json')).read_text())
            self.assertGreater(metrics['sampledPeakTreeRssBytes'], metrics['sampledPeakGroupRssBytes'])

    def test_cancellation_and_thread_limits_reach_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            event = threading.Event()
            with allocation({'threads': 2, 'ranks': 1}, event):
                report = SubprocessRunner(Interpreter('python', sys.executable), Path(tmp))('import os\nprint(os.environ["OMP_NUM_THREADS"])')
                self.assertEqual(report.stdout.strip(), '2')
                event.set()
                with self.assertRaises(SchemaxisError) as caught:
                    SubprocessRunner(Interpreter('python', sys.executable), Path(tmp))('pass')
                self.assertEqual(caught.exception.fault.code, 'RUNNER_CANCELLED')
