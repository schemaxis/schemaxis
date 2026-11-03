# Copyright (C) 2026 David L F Gaden
"""Case Runner uses actual bind, schedule, verification and naming with a host native fixture."""
import copy
import importlib.util
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import hashlib
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from schemaxis import storage
from schemaxis.console_server import ConsoleApplication
from schemaxis.console_session import AdaptorConsoleSession
from schemaxis.core.faults import SchemaxisError
from schemaxis.errors import fail
from schemaxis.dispatch import cancellation_token
from schemaxis.studio_cases import StudioCases
from schemaxis.workflow_authoring import example


def native_fixture(document, directory, *args, **kwargs):
    directory = Path(directory)
    directory.mkdir(parents=True)
    (directory / 'authored.json').write_bytes(storage.encoded(document))
    output = directory / 'result.csv'
    output.write_text('x,value\n0,0\n1,2\n2,4\n')
    receipt = {'artifacts': [{'file': str(output), 'kind': 'table',
                              'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}]}
    (directory / 'verification.json').write_bytes(storage.encoded(receipt))
    return {'verified': True}


def verify_fixture(directory, document):
    directory = Path(directory)
    if storage.load((directory / 'authored.json').read_text()) != document:
        raise AssertionError('native authored document changed')
    receipt = storage.load((directory / 'verification.json').read_text())
    for artifact in receipt['artifacts']:
        if hashlib.sha256(Path(artifact['file']).read_bytes()).hexdigest() != artifact['sha256']:
            fail('VERIFICATION_FAILED', 'changed fixture')
    return receipt


class StudioCaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        session = AdaptorConsoleSession(self.root, provider='workflow')
        self.addCleanup(session.close)
        self.app = ConsoleApplication(session)
        self.addCleanup(self.app.close)
        self.cases = StudioCases(self.app)
        directory = self.root / 'template'
        directory.mkdir()
        document = example()
        document['settings'] = {'stop': 4}
        document['operations'][0]['document']['nodes'][0]['options']['stop'] = {
            '$document': '/settings/stop', 'scope': 'workflow'}
        manifest = {'version': 'schemaxis.workflow-template/1', 'id': 'test.sequence', 'revision': 1,
                    'title': 'Sequence study', 'workflow': 'workflow.json', 'parameters': {
                        'stop': {'kind': 'number', 'label': 'Upper bound', 'default': 4,
                                 'constraints': {'minimum': 1, 'maximum': 20},
                                 'target': {'scope': 'workflow', 'pointer': '/settings/stop'}}},
                    'outputs': {'scaled': {'operation': 'scaled', 'artifact': 0, 'kind': 'table'}}}
        (directory / 'template.json').write_bytes(storage.encoded(manifest))
        (directory / 'workflow.json').write_bytes(storage.encoded(document))
        self.path = str(directory)
        self.inspected = self.request('inspect_template')
        self.values = copy.deepcopy(self.inspected['values'])
        for target, replacement in (('schemaxis.parallel.run_native', native_fixture),
                                    ('schemaxis.parallel.verify_native', verify_fixture)):
            patcher = patch(target, side_effect=replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch('schemaxis.parallel.reusable_inputs', return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)

    @unittest.skipUnless(importlib.util.find_spec('ruamel') is not None, 'optional YAML extra')
    def test_yaml_case_roundtrip_preserves_comments(self):
        from schemaxis.source_formats import dump_document
        from schemaxis.core.documents import load_document_file
        path = self.root / 'parameters.yaml'
        path.write_text('# parameter note\n' + dump_document(self.values, 'yaml'))
        loaded = self.request('load', filename=str(path))
        self.assertEqual(loaded['values'], self.values)
        changed = copy.deepcopy(self.values)
        changed['values']['stop'] = 5
        saved = self.request('save', filename=str(path), values=changed, caseDigest=loaded['caseDigest'])
        self.assertEqual(load_document_file(path), changed)
        self.assertIn('# parameter note', path.read_text())
        self.assertNotEqual(saved['caseDigest'], loaded['caseDigest'])

    def request(self, action, **extra):
        request = {'action': action, 'path': self.path, **extra}
        if action in ('bind', 'plan', 'run', 'save'):
            request.setdefault('values', self.values)
        return self.cases.request(request)

    def assert_fault(self, code, function):
        with self.assertRaises(SchemaxisError) as error:
            function()
        self.assertEqual(error.exception.fault.code, code)

    def finish(self, job):
        self.app.job_owner.futures[job['job']].result(timeout=15)
        result = self.cases.snapshot(job['job'])
        self.assertEqual(result['status'], 'succeeded', result)
        return result

    def test_inspect_plan_and_case_file_roundtrip(self):
        self.assertEqual(self.inspected['operations'][1]['dependencies'], ['samples'])
        self.values['values']['stop'] = 7
        self.values['run'] = {'workers': 2, 'outputDirectory': 'my-run'}
        with patch('subprocess.Popen', side_effect=AssertionError('planning must not launch a process')):
            prepared = self.request('plan')
        self.assertEqual(prepared['document']['execution']['maxWorkers'], 2)
        self.assertEqual(prepared['plan']['budget']['maxWorkers'], 2)
        self.assertEqual(prepared['document']['settings']['stop'], 7)
        self.assertFalse(self.app.busy)
        saved = self.request('save', filename='cases/test.json')
        loaded = self.request('load', filename=saved['filename'])
        self.assertEqual(loaded['values'], self.values)
        self.assertEqual(loaded['bound']['digest'], prepared['digest'])
        self.values['template']['digest'] = 'changed'
        self.assert_fault('STALE_TEMPLATE', lambda: self.request('run'))
        self.assertFalse(self.app.busy)

    def test_marked_case_cannot_bind_plan_or_start_a_native_job(self):
        self.values['values']['stop'] = {'$fill': 'stop', 'type': 'number', 'label': 'Upper bound'}
        with patch('subprocess.Popen', side_effect=AssertionError('unfilled cases must not execute')):
            for action in ('bind', 'plan', 'run'):
                with self.subTest(action=action):
                    with self.assertRaises(SchemaxisError) as caught:
                        self.request(action)
                    self.assertEqual(caught.exception.fault.code, 'UNFILLED_VALUES')
                    self.assertEqual(caught.exception.fault.observed['pointers'], ['/values/stop'])
        self.assertFalse(self.app.busy)

    def test_two_editors_cannot_overwrite_the_same_case_baseline(self):
        saved = self.request('save', filename='cases/shared.json')
        first, second = copy.deepcopy(self.values), copy.deepcopy(self.values)
        first['values']['stop'], second['values']['stop'] = 6, 7
        reached_write, release, second_prepared = threading.Event(), threading.Event(), threading.Event()
        original_atomic, original_prepare = storage.atomic, self.cases._prepare

        def hold_write(*args, **kwargs):
            reached_write.set()
            if not release.wait(5):
                raise AssertionError('test did not release pending save')
            return original_atomic(*args, **kwargs)

        def prepare(request):
            result = original_prepare(request)
            second_prepared.set()
            return result

        with ThreadPoolExecutor(max_workers=2) as workers, patch('schemaxis.storage.atomic', hold_write):
            one = workers.submit(self.request, 'save', filename=saved['filename'],
                                 caseDigest=saved['caseDigest'], values=first)
            try:
                self.assertTrue(reached_write.wait(3))
                with patch.object(self.cases, '_prepare', prepare):
                    two = workers.submit(self.request, 'save', filename=saved['filename'],
                                         caseDigest=saved['caseDigest'], values=second)
                    self.assertTrue(second_prepared.wait(3))
                    with self.assertRaises(TimeoutError):
                        two.result(timeout=.2)
            finally:
                release.set()
            one.result(timeout=3)
            self.assert_fault('STALE_CASE_FILE', lambda: two.result(timeout=3))
        self.assertEqual(self.request('load', filename=saved['filename'])['values']['values']['stop'], 6)

    def test_real_workflow_job_verifies_names_outputs_and_preserves_case(self):
        self.values['values']['stop'] = 5.5
        self.values['run'] = {'workers': 2, 'naming': {
            'pattern': '{index}-{operation}-{output}-{param:stop}{ext}', 'indexWidth': 3}}
        job = self.request('run')
        snapshot = self.finish(job)
        self.assertTrue(snapshot['verified'])
        self.assertEqual({op['status'] for op in snapshot['operations']}, {'succeeded'})
        result = self.request('outputs', job=job['job'])
        self.assertEqual([item['name'] for item in result['outputs']], [
            '001-samples-result-5p5.csv', '002-scaled-scaled-5p5.csv'])
        self.assertEqual(storage.load((Path(job['directory']) / 'case.json').read_text()), self.values)
        self.assertEqual(self.cases.file_roots(), [Path(job['directory'])])
        self.assertFalse(self.app.busy)
        self.assertEqual(self.cases.snapshot('missing'), {'status': 'unknown'})

    def test_naming_failure_keeps_verified_native_outputs(self):
        self.values['run'] = {'naming': {'pattern': '{param:missing}{ext}'}}
        job = self.request('run')
        snapshot = self.finish(job)
        self.assertTrue(snapshot['verified'])
        self.assertEqual(snapshot['result']['namingFault']['code'], 'INVALID_NAMING')
        self.assertEqual(len(self.request('outputs', job=job['job'])['outputs']), 2)
        self.assertIsNone(snapshot['result']['naming'])

    def test_job_polling_and_busy_response_do_not_wait_for_native_work(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def delayed(*args, **kwargs):
            entered.set()
            if not release.wait(10):
                raise RuntimeError('test fixture timed out')
            return native_fixture(*args, **kwargs)

        with patch('schemaxis.parallel.run_native', side_effect=delayed):
            job = self.request('run')
            self.assertTrue(entered.wait(5))
            self.assertEqual(self.cases.snapshot(job['job'])['status'], 'running')
            self.assert_fault('SESSION_BUSY', lambda: self.request('run'))
            self.assert_fault('INCOMPLETE_EXECUTION', lambda: self.request('outputs', job=job['job']))
            # Captured parameters and aliases remain usable if the template is edited during execution.
            (Path(self.path) / 'template.json').write_text('{}')
            release.set()
            self.finish(job)

    def test_busy_other_command_does_not_wait_for_its_session_lock(self):
        entered, release, exited = threading.Event(), threading.Event(), threading.Event()

        def hold_session():
            with self.app.lock:
                entered.set()
                release.wait(5)
            exited.set()

        worker = threading.Thread(target=hold_session)
        self.app.busy = True
        worker.start()
        self.assertTrue(entered.wait(2))
        try:
            self.assert_fault('SESSION_BUSY', lambda: self.request('run'))
            self.assertFalse(exited.is_set(), 'busy response waited for the native session lock')
        finally:
            self.app.busy = False
            release.set()
            worker.join(timeout=5)

    def test_failed_run_is_not_reported_as_verified(self):
        with patch('schemaxis.parallel.run_native', side_effect=RuntimeError('native fixture failure')):
            job = self.request('run')
            self.app.job_owner.futures[job['job']].result(timeout=10)
        snapshot = self.cases.snapshot(job['job'])
        self.assertEqual(snapshot['status'], 'failed')
        self.assertNotIn('verified', snapshot)
        self.assertIn('native fixture failure', snapshot['fault']['message'])
        self.assertFalse(self.app.busy)
        self.assert_fault('INCOMPLETE_EXECUTION', lambda: self.request('outputs', job=job['job']))

    def test_saving_requires_loaded_baseline_and_detects_external_edits(self):
        saved = self.request('save', filename='cases/edit.json')
        self.assert_fault('CASE_FILE_EXISTS', lambda: self.request('save', filename=saved['filename']))
        self.values['values']['stop'] = 8
        updated = self.request('save', filename=saved['filename'], caseDigest=saved['caseDigest'])
        self.assertNotEqual(saved['caseDigest'], updated['caseDigest'])
        Path(saved['filename']).write_text('{}')
        self.assert_fault('STALE_CASE_FILE', lambda: self.request(
            'save', filename=saved['filename'], caseDigest=updated['caseDigest']))
        self.assertEqual(Path(saved['filename']).read_text(), '{}')

    def test_cancellation_reaches_native_dispatch_and_does_not_publish_outputs(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def cancellable(*args, **kwargs):
            token = cancellation_token()
            entered.set()
            self.assertTrue(release.wait(5))
            if token.is_set():
                fail('RUNNER_CANCELLED', 'fixture observed native cancellation')
            raise AssertionError('native cancellation token was not set')

        with patch('schemaxis.parallel.run_native', side_effect=cancellable):
            job = self.request('run')
            self.assertTrue(entered.wait(5))
            self.assertEqual(self.app.cancel(job['job'])['status'], 'cancellation-requested')
            release.set()
            self.app.job_owner.futures[job['job']].result(timeout=10)
        result = self.cases.snapshot(job['job'])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['fault']['code'], 'RUNNER_CANCELLED')
        self.assertNotIn('result', result)
        self.assertFalse(self.app.busy)

    def test_changed_publications_fail_output_reverification(self):
        job = self.request('run')
        result = self.finish(job)
        Path(result['result']['outputs'][0]['path']).write_text('changed output')
        self.assert_fault('VERIFICATION_FAILED', lambda: self.request('outputs', job=job['job']))

    def test_paths_and_case_limits_are_checked_before_writing(self):
        self.assert_fault('INVALID_CASE_PATH', lambda: self.request('save', filename='../escape.json'))
        (self.root / 'linked').symlink_to(self.root / 'template', target_is_directory=True)
        self.assert_fault('INVALID_CASE_PATH', lambda: self.request('save', filename='linked/case.json'))
        (self.root / 'huge.json').write_text(' ' * (1024 * 1024 + 1))
        self.assert_fault('CASE_TOO_LARGE', lambda: self.request('load', filename='huge.json'))
        self.values['run'] = {'outputDirectory': str(self.root)}
        self.assert_fault('OUTPUT_EXISTS', lambda: self.request('run'))
        self.assertFalse(self.app.busy)


if __name__ == '__main__':
    unittest.main()
