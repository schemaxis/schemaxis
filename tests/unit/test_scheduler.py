"""Durable schedule policy, host-only execution and civil-time qualification."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from schemaxis.scheduler import SchedulerStore, SchedulerRunner, next_due, instant, validate
from schemaxis.core.faults import SchemaxisError

BOX = {'version': 'schemaxis.freecad/1', 'nodes': [{'id': 'body', 'filter': 'box'}], 'output': 'body'}


def spec(**changes):
    return {'document': BOX, 'objective': 'scheduled test', 'allowedProviders': ['freecad'],
            'trigger': {'kind': 'interval', 'start': '2026-01-01T00:00:00Z', 'seconds': 60}, **changes}


class FakeService:
    instances = []
    fail_first = False

    def __init__(self, workspace, locations=None):
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.jobs = {}
        self.closed = False
        FakeService.instances.append(self)

    def create_task(self, objective, providers, budget):
        self.budget = budget
        return {'id': 'task', 'revision': 0}

    def plan(self, identity, document, revision):
        self.document = document
        return {'id': 'plan', 'revision': 1}

    def task(self, identity):
        return {'revision': 1}

    def execute(self, identity, revision):
        job = 'job-'+str(len(self.jobs))
        self.jobs[job] = {'id': job, 'status': 'running'}
        return self.jobs[job]

    def job(self, identity):
        return self.jobs[identity]

    def cancel(self, identity):
        self.jobs[identity]['status'] = 'cancelled'

    def close(self):
        self.closed = True


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = SchedulerStore(self.tmp.name)
        FakeService.instances = []
        self.now = instant('2026-01-01T00:00:00Z')

    def runner(self):
        runner = SchedulerRunner(self.tmp.name, service_factory=FakeService)
        self.addCleanup(runner.close)
        return runner

    def test_pinned_document_revision_and_independent_client(self):
        authored = spec()
        record = self.store.create(authored)
        authored['document'] = {}
        self.assertEqual(self.store.get(record['id'])['spec']['document'], BOX)
        runner = self.runner()
        SchedulerStore(self.tmp.name).pause(record['id'], 1)
        runner.tick(self.now)
        self.assertEqual(FakeService.instances, [])
        self.store.resume(record['id'], 2)
        runner.tick(self.now)
        self.assertEqual(FakeService.instances[0].document, BOX)
        with self.assertRaises(SchemaxisError):
            self.store.pause(record['id'], 1)

    def test_once_verified_execution_no_duplicate_and_cancel(self):
        record = self.store.create(spec(trigger={'kind': 'once', 'at': '2026-01-01T00:00:00Z'}))
        runner = self.runner()
        runner.tick(self.now)
        self.store.cancel(record['id'], 1)
        runner.tick(self.now)
        runner.tick(self.now)
        occurrences = self.store.get(record['id'])['occurrences']
        self.assertEqual(len(occurrences), 1)
        self.assertEqual(occurrences[0]['status'], 'cancelled')
        self.assertEqual(len(FakeService.instances), 1)

    def test_verified_success_and_retry(self):
        record = self.store.create(spec(maxRetries=1, maxOccurrences=1))
        runner = self.runner()
        runner.tick(self.now)
        service = FakeService.instances[0]
        service.jobs['job-0']['status'] = 'failed'
        runner.tick(self.now)
        self.assertEqual(len(service.jobs), 2)
        service.jobs['job-1'].update(status='succeeded', verified=True)
        runner.tick(self.now)
        occurrence = self.store.get(record['id'])['occurrences'][0]
        self.assertEqual(occurrence['status'], 'succeeded', occurrence.get('fault'))
        self.assertTrue(occurrence['verified'])
        self.assertEqual(occurrence['retries'], 1)

    def test_recovery_never_replays_claimed_occurrence(self):
        record = self.store.create(spec(maxOccurrences=1))
        runner = self.runner()
        runner.tick(self.now)
        runner.close()
        recovered = self.runner()
        recovered.tick(self.now)
        self.assertEqual(self.store.get(record['id'])['occurrences'][0]['status'], 'interrupted')
        self.assertEqual(len(FakeService.instances), 1)

    def test_single_runner(self):
        self.runner()
        with self.assertRaises(SchemaxisError) as error:
            SchedulerRunner(self.tmp.name)
        self.assertEqual(error.exception.fault.code, 'SCHEDULER_LOCKED')

    def test_misfires_bounded_catch_up_and_skip(self):
        for policy, expected in [('runOnce', 1), ('skip', 1), ('catchUp', 3)]:
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as directory:
                store = SchedulerStore(directory)
                record = store.create(spec(misfire=policy, maxCatchUp=3, graceSeconds=0))
                with SchedulerRunner(directory, service_factory=FakeService) as runner:
                    runner.tick(self.now+600)
                    occurrences = store.get(record['id'])['occurrences']
                    self.assertEqual(len(occurrences), expected)
                    if policy == 'skip':
                        self.assertEqual(occurrences[0]['status'], 'skipped')

    def test_overlap_coalesces_queue(self):
        record = self.store.create(spec(overlap='coalesce'))
        runner = self.runner()
        runner.tick(self.now)
        runner.tick(self.now+60)
        runner.tick(self.now+120)
        pending = [o for o in self.store.get(record['id'])['occurrences'] if o['status'] == 'queued']
        self.assertEqual(len(pending), 1)

    def test_corruption_stops_writes(self):
        self.store.create(spec())
        path = Path(self.tmp.name)/'scheduler.json'
        before = path.read_text().replace('scheduled test', 'corrupt test')
        path.write_text(before)
        with self.assertRaises(SchemaxisError) as error:
            self.store.list()
        self.assertEqual(error.exception.fault.code, 'SCHEDULER_RECOVERY_FAILED')
        self.assertEqual(path.read_text(), before)

    def test_expiry_no_late_dispatch(self):
        record = self.store.create(spec(expiresAt='2026-01-01T00:00:30Z'))
        runner = self.runner()
        runner.tick(self.now+60)
        self.assertEqual(self.store.get(record['id'])['status'], 'completed')
        self.assertEqual(FakeService.instances, [])

    def test_real_execution_service_verified_publication(self):
        from schemaxis.artifacts import atomic_json, file_digest
        def run(document, directory, **kwargs):
            directory.mkdir()
            atomic_json(directory/'authored.json', document)
            (directory/'model.step').write_text('host qualification output')
            atomic_json(directory/'verification.json', {'artifacts': [
                {'file': str(directory/'model.step'), 'kind': 'cad',
                 'sha256': file_digest(directory/'model.step')}]})
            from schemaxis.publication_metadata import finalise
            finalise(directory)
            return {'verified': True}
        def verify(directory, document=None):
            receipt = json.loads((directory/'verification.json').read_text())
            artifact = receipt['artifacts'][0]
            if artifact['sha256'] != file_digest(artifact['file']):
                raise ValueError('changed artifact')
            return {'verified': True, 'scope': 'host double'}
        record = self.store.create(spec(maxOccurrences=1))
        with patch('schemaxis.execution_service.registry.run', side_effect=run), \
                patch('schemaxis.execution_service.registry.verify', side_effect=verify), \
                SchedulerRunner(self.tmp.name, locations={'freecad': '/not-used'}) as runner:
            deadline = time.monotonic()+5
            runner.tick(self.now)
            while runner.active and time.monotonic() < deadline:
                time.sleep(.01)
                runner.tick(self.now)
            self.assertIsNone(runner.active)
        occurrence = self.store.get(record['id'])['occurrences'][0]
        self.assertEqual(occurrence['status'], 'succeeded', occurrence.get('fault'))
        self.assertTrue(occurrence['verified'])
        self.assertTrue((Path(occurrence['workspace'])/'agent.json').exists())

    def test_completed_queue_expires_and_close_idempotent(self):
        record = self.store.create(spec(maxOccurrences=2, misfire='catchUp',
                                       expiresAt='2026-01-01T00:02:00Z'))
        runner = self.runner()
        runner.tick(self.now+60)
        service = FakeService.instances[0]
        service.jobs['job-0'].update(status='succeeded', verified=True)
        runner.tick(self.now+180)
        occurrences = self.store.get(record['id'])['occurrences']
        self.assertEqual([o['status'] for o in occurrences], ['succeeded', 'skipped'])
        self.assertEqual(len(FakeService.instances), 1)
        runner.close()
        runner.close()

    def test_failed_recovery_releases_owner(self):
        (Path(self.tmp.name)/'scheduler.json').write_text('{}')
        with self.assertRaises(SchemaxisError):
            SchedulerRunner(self.tmp.name)
        (Path(self.tmp.name)/'scheduler.json').unlink()
        self.runner()

    def test_cancel_during_planning_prevents_execute(self):
        record = self.store.create(spec(maxOccurrences=1))
        store = self.store
        class CancellingService(FakeService):
            def plan(self, identity, document, revision):
                store.cancel(record['id'], 1)
                return super().plan(identity, document, revision)
        with SchedulerRunner(self.tmp.name, service_factory=CancellingService) as runner:
            runner.tick(self.now)
        self.assertEqual(FakeService.instances[0].jobs, {})
        self.assertEqual(store.get(record['id'])['occurrences'][0]['status'], 'cancelled')

    def test_invalid_authorisation_trigger_and_budget(self):
        for changes in [{'allowedProviders': ['octave']}, {'budget': {'maxAttempts': 0}},
                        {'trigger': {'kind': 'once', 'at': '2026-01-01'}}, {'maxRetries': 100},
                        {'trigger': {'kind': 'interval', 'start': '2026-01-01T00:00:00Z', 'seconds': float('nan')}}]:
            with self.subTest(changes=changes), self.assertRaises(SchemaxisError):
                self.store.create(spec(**changes))

    def test_calendar_dst_gap_skipped_fold_first(self):
        trigger = {'kind': 'calendar', 'start': '2026-03-07T00:00:00Z', 'timezone': 'America/Winnipeg',
                   'hour': 2, 'minute': 30, 'weekdays': list(range(7))}
        due = next_due(trigger, instant('2026-03-08T00:00:00Z'), True)
        self.assertEqual(due, instant('2026-03-09T07:30:00Z'))
        trigger.update(start='2026-10-31T00:00:00Z', hour=1)
        first = next_due(trigger, instant('2026-11-01T00:00:00Z'), True)
        self.assertEqual(first, instant('2026-11-01T06:30:00Z'))
        self.assertEqual(next_due(trigger, first), instant('2026-11-02T07:30:00Z'))

    def test_preview_boundary(self):
        result = self.store.preview(spec(), count=2, now=self.now)
        self.assertEqual(result['upcoming'], ['2026-01-01T00:00:00Z', '2026-01-01T00:01:00Z'])


if __name__ == '__main__':
    unittest.main()
