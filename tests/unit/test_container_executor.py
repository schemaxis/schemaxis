"""Host doubles exercise protocol/refusals; these are not Docker qualification."""
import copy
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch

from schemaxis.container_executor import (ContainerExecutor, DockerEngine, EngineResult,
    ImageResolver, IsolationLimits, IsolationProfile, failure)
from schemaxis.container_protocol import frame, unframe, pack_tree, unpack_tree
from schemaxis.execution_backends import (ExecutionRequest, VerificationRequest, LocalExecutor,
    ExecutionOutcome, VerificationOutcome)
from schemaxis.core.faults import SchemaxisError
from schemaxis.jobs import Cancellation
from schemaxis.storage import encoded, digest
from schemaxis.capabilities import digest as document_digest
from schemaxis.execution_inputs import (PlanningRequest, PlanningOutcome, CapturePolicy, CapturedInput,
    InputBindings, check_bound_document)

IMAGE = 'example.invalid/worker@sha256:' + 'a'*64
CID = 'b'*64


class Admission:
    def check(self, document):
        if document.get('external'):
            failure('ISOLATION_UNAVAILABLE', 'external input denied by test policy')
        return True


class FakeEngine:
    def __init__(self, root):
        self.root = root
        self.calls = []
        self.exists = False
        self.running = False
        self.corrupt_binding = False
        self.cancel_start = False
        self.cleanup_fails = False
        self.weaken = False
        self.response_change = None

    def command(self, arguments, **options):
        self.calls.append((arguments, options))
        operation = arguments[1]
        if operation == 'create':
            def option(name):
                return arguments[arguments.index(name)+1]
            self.exists = True
            labels = dict(arguments[index+1].split('=', 1)
                          for index, value in enumerate(arguments) if value == '--label')
            intent = json.loads((self.root/'container-lifecycle'/
                                (labels['io.schemaxis.attempt']+'.json')).read_text())['record']
            assert intent['state'] == 'intent' and intent['containerId'] is None
            assert intent['jobId'] == labels['io.schemaxis.job']
            self.record = {'Config': {'Image': IMAGE, 'User': option('--user'),
                'Labels': labels},
                'HostConfig': {'NetworkMode': option('--network'), 'ReadonlyRootfs': True,
                    'Privileged': False, 'Binds': None, 'Devices': [], 'PidMode': '',
                    'IpcMode': 'none', 'CgroupnsMode': 'private',
                    'Memory': int(option('--memory')), 'MemorySwap': int(option('--memory-swap')),
                    'PidsLimit': int(option('--pids-limit')),
                    'NanoCpus': int(float(option('--cpus'))*1000000000),
                    'Tmpfs': dict([option('--tmpfs').split(':', 1)]),
                    'CapDrop': ['ALL'], 'CapAdd': [], 'SecurityOpt': ['no-new-privileges=true']},
                'Mounts': []}
            if self.weaken:
                self.record['HostConfig']['MemorySwap'] = -1
            mounts = [dict(item.split('=', 1) if '=' in item else (item, True)
                           for item in arguments[index+1].split(','))
                      for index, value in enumerate(arguments) if value == '--mount']
            self.record['HostConfig']['Mounts'] = [
                {'Type': item['type'], 'Source': item['src'], 'Target': item['dst'],
                 'ReadOnly': item.get('readonly') is True,
                 'BindOptions': {'Propagation': item.get('bind-propagation')}} for item in mounts]
            self.record['Mounts'] = [{'Type': item['type'], 'Source': item['src'],
                'Destination': item['dst'], 'RW': item.get('readonly') is not True,
                'Propagation': item.get('bind-propagation')} for item in mounts]
            return EngineResult(0, CID.encode()+b'\n', b'')
        if operation == 'inspect':
            record = copy.deepcopy(self.record)
            record['State'] = {'Running': self.running, 'ExitCode': 0, 'OOMKilled': False}
            return EngineResult(0, json.dumps([record]).encode(), b'')
        if operation == 'start':
            self.running = True
            if self.cancel_start:
                failure('RUNNER_CANCELLED', 'cancelled during fake worker')
            header, archive = unframe(options['payload'], 96*1024*1024)
            self.last_header = header
            if header['action'] == 'run':
                run = self.root/'worker'/'run'
                run.mkdir(parents=True)
                (run/'authored.json').write_bytes(encoded(header['document']))
                (run/'verification.json').write_bytes(encoded({'verified': True, 'artifacts': []}))
                archive, inventory = pack_tree(run, header['limits']['disk_bytes'], header['limits']['inodes'])
            elif header['action'] == 'plan':
                archive, inventory = b'', {}
            else:
                inventory = unpack_tree(archive, self.root/'unused',
                    header['limits']['disk_bytes'], header['limits']['inodes'], validate_only=True)
            envelope = {'requestDigest': digest(header), 'action': header['action'],
                'result': {'verified': True, 'ordinary': 'unchanged'},
                'publications': [], 'inventory': inventory,
                'quiescence': {'remainingProcesses': 0}, 'limits': {'testDouble': True}}
            if self.corrupt_binding:
                envelope['requestDigest'] = '0'*64
            if self.response_change is not None:
                envelope, archive = self.response_change(envelope, archive)
            self.running = False
            return EngineResult(0, frame(envelope, archive), b'')
        if operation == 'ls':
            return EngineResult(0, CID.encode()+b'\n' if self.exists else b'', b'')
        if operation == 'kill':
            self.running = False
            return EngineResult(0, CID.encode(), b'')
        if operation == 'rm':
            if not self.cleanup_fails:
                self.exists = False
            return EngineResult(0, CID.encode(), b'')
        raise AssertionError(arguments)


class ContainerExecutorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.engine = FakeEngine(self.root)
        self.profile = IsolationProfile(IMAGE, ('fixture_geo',), ('schemaxis.fixture/1',),
            qualification_id='explicit-test-double-only')
        self.executor = ContainerExecutor(ImageResolver([self.profile]),
            admission=Admission(), engine=self.engine)
        document = {'version': 'schemaxis.fixture/1', 'operation': 'fixture'}
        plan = {'planned': True}
        self.request = ExecutionRequest('job-123', 'plan-123', document, plan,
            document_digest(document), hashlib.sha256(encoded(plan)).hexdigest(),
            self.root/'runs'/'job-123'/'run', self.root, ('fixture_geo',), (),
            10, time.monotonic()+30, {'secretHostLocation': '/not-forwarded'})

    def test_run_and_fresh_verify_preserve_results_paths_and_digest_checks(self):
        result = self.executor.run(self.request, Cancellation())
        self.assertEqual(result.response, {'verified': True, 'ordinary': 'unchanged'})
        self.assertTrue(result.isolation['containerExited'])
        self.assertTrue(result.isolation['cleanup']['containerAbsent'])
        self.assertEqual(json.loads((self.request.directory/'authored.json').read_text()), self.request.document)
        receipt = hashlib.sha256((self.request.directory/'verification.json').read_bytes()).hexdigest()
        verified = self.executor.verify(VerificationRequest(self.request,
            (('verification.json', receipt),)), Cancellation())
        self.assertTrue(verified.response['verified'])
        self.assertEqual(verified.publications, [])
        creates = [args for args, _ in self.engine.calls if args[1] == 'create']
        self.assertEqual(len(creates), 2)
        for args in creates:
            self.assertIn('--read-only', args)
            self.assertEqual(args[args.index('--network')+1], 'none')
            self.assertNotIn('--mount', args)
            self.assertNotIn('--volume', args)
            self.assertIn('nr_inodes=4096', args[args.index('--tmpfs')+1])
            self.assertEqual(args[-5:], [IMAGE, '-I', '-B', '-m', 'schemaxis.container_worker'])
        self.assertNotIn('locations', self.engine.last_header)

    def test_plan_requires_explicit_capability_before_engine_use(self):
        request = PlanningRequest('operation-1', 'plan-1', self.root,
            self.request.document, self.request.providers, 10, time.monotonic()+30)
        with self.assertRaises(SchemaxisError):
            self.executor.plan(request, Cancellation())
        self.assertEqual(self.engine.calls, [])

    def test_contained_plan_never_calls_host_hooks_and_binds_phase(self):
        profile = replace(self.profile, capabilities=('isolated-planning-v1',))
        executor = ContainerExecutor(ImageResolver([profile]), admission=Admission(), engine=self.engine)
        request = PlanningRequest('operation-1', 'plan-1', self.root,
            self.request.document, self.request.providers, 10, time.monotonic()+30,
            phase='stale-check')
        with patch('schemaxis.adaptors.registry.plan', side_effect=AssertionError('host hook')):
            result = executor.plan(request, Cancellation())
        self.assertEqual(result.response, {'verified': True, 'ordinary': 'unchanged'})
        self.assertEqual(result.isolation['operationId'], 'operation-1')
        self.assertEqual(result.isolation['planningPhase'], 'stale-check')
        self.assertEqual(result.isolation['action'], 'plan')
        self.assertTrue(result.isolation['cleanup']['containerAbsent'])
        records = list((self.root/'container-lifecycle').glob('*.json'))
        record = json.loads(records[0].read_text())['record']
        self.assertEqual(record['operationId'], 'operation-1')
        self.assertEqual(record['planningPhase'], 'stale-check')
        self.assertEqual(record['isolation'], result.isolation)
        before = len(self.engine.calls)
        recovered = executor.recover(self.root)
        self.assertEqual(len(self.engine.calls), before)
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]['planId'], 'plan-1')
        self.assertEqual(recovered[0]['isolation'], result.isolation)

    def test_unexpected_read_only_mount_is_refused(self):
        self.executor.run(self.request, Cancellation())
        record = copy.deepcopy(self.engine.record)
        record['Mounts'] = [{'Type': 'bind', 'Source': '/etc/passwd',
                             'Destination': '/etc/passwd', 'RW': False, 'Propagation': 'rprivate'}]
        create = next(args for args, _ in self.engine.calls if args[1] == 'create')
        with self.assertRaises(SchemaxisError):
            self.executor._check_config(record, self.profile, self.request.directory.parent,
                create[create.index('--tmpfs')+1], record['Config']['Labels']['io.schemaxis.attempt'])

    def test_strict_admission_emits_pinned_worker_guard_contract(self):
        from schemaxis.mcp_admission import FileAdmission
        root = self.root/'captures'
        root.mkdir(mode=0o700)
        path = root/'input.png'
        path.write_bytes(b'opaque native parser fixture')
        path.chmod(0o444)
        info = path.stat()
        capture = CapturedInput('upload-1', path, 'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest(),
            info.st_size, info.st_dev, info.st_ino)
        bindings = InputBindings('task-1', (capture,), (('/nodes/0/options/FileNames/0', 'upload-1'),))
        document = {'version': 'schemaxis/1', 'nodes': [{'id': 'data', 'filter': 'pvPNGSeriesReader',
            'options': {'FileNames': [str(path)]}}], 'scenes': [{'id': 'view', 'geometry': ['data']}]}
        admission = FileAdmission()
        profile = replace(self.profile, providers=('paraview',), routes=('schemaxis/1',),
            capabilities=('captured-input-planning-v1',))
        executor = ContainerExecutor(ImageResolver([profile]), admission=admission,
            engine=self.engine, capture_policy=CapturePolicy(root, 'task-1', 512, 1))
        request = PlanningRequest('operation-1', 'plan-1', self.root, document, ('paraview',),
            10, time.monotonic()+30, inputs=bindings)
        executor.plan(request, Cancellation())
        self.assertEqual(self.engine.last_header['capturedContentPolicy'],
            admission.captured_content_policy(document, bindings))
        self.assertEqual(self.engine.last_header['capturedContentPolicy']['contracts'],
            [admission.policies['schemaxis/1']['contractDigest']])

    def test_captured_planning_mounts_only_the_leased_file_and_refuses_mutation(self):
        root = self.root/'captures'
        root.mkdir(mode=0o700)
        path = root/'input.bin'
        path.write_bytes(b'captured bytes')
        path.chmod(0o444)
        info = path.stat()
        capture = CapturedInput('upload-1', path, 'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest(),
            info.st_size, info.st_dev, info.st_ino)
        bindings = InputBindings('task-1', (capture,), (('/source', 'upload-1'),))
        class CapturedAdmission:
            def check(self, document, context=None, *, bound=False):
                if not bound:
                    raise AssertionError('expected already captured document')
                check_bound_document(document, context)
        profile = replace(self.profile, capabilities=('captured-input-planning-v1',))
        executor = ContainerExecutor(ImageResolver([profile]), admission=CapturedAdmission(),
            engine=self.engine, capture_policy=CapturePolicy(root, 'task-1', 512, 1))
        request = PlanningRequest('operation-1', 'plan-1', self.root,
            {**self.request.document, 'source': str(path)}, self.request.providers,
            10, time.monotonic()+30, inputs=bindings)
        result = executor.plan(request, Cancellation())
        self.assertTrue(result.isolation['cleanup']['containerAbsent'])
        self.assertNotIn('capturedContentPolicy', self.engine.last_header)
        mount = self.engine.record['Mounts'][0]
        self.assertEqual(mount['Source'], str(path))
        self.assertEqual(mount['Destination'], str(path))
        self.assertFalse(mount['RW'])
        path.chmod(0o644)
        before = len(self.engine.calls)
        with self.assertRaises(SchemaxisError):
            executor.plan(replace(request, operation_id='operation-2'), Cancellation())
        self.assertEqual(len(self.engine.calls), before)
        path.chmod(0o444)
        self.engine.cleanup_fails = True
        with self.assertRaises(SchemaxisError) as caught:
            executor.plan(replace(request, operation_id='operation-3'), Cancellation())
        self.assertEqual(caught.exception.fault.code, 'ISOLATION_CLEANUP_UNKNOWN')
        with self.assertRaises(SchemaxisError) as busy:
            executor.capture_policy.lease(exclusive=True)
        self.assertEqual(busy.exception.fault.code, 'INPUTS_BUSY')
        before = len(self.engine.calls)
        with self.assertRaises(SchemaxisError) as fenced:
            executor.plan(replace(request, operation_id='operation-4'), Cancellation())
        self.assertEqual(fenced.exception.fault.code, 'ISOLATION_RECOVERY_REQUIRED')
        self.assertEqual(len(self.engine.calls), before)
        self.engine.cleanup_fails = False
        executor.recover(self.root)
        with executor.capture_policy.lease(exclusive=True):
            pass

    def test_missing_admission_and_missing_qualification_refuse_before_engine(self):
        absent = ContainerExecutor(ImageResolver([self.profile]), engine=self.engine)
        with self.assertRaises(SchemaxisError):
            absent.run(self.request, Cancellation())
        unqualified = IsolationProfile(IMAGE, self.profile.providers, self.profile.routes)
        executor = ContainerExecutor(ImageResolver([unqualified]), admission=Admission(), engine=self.engine)
        with self.assertRaises(SchemaxisError):
            executor.run(self.request, Cancellation())
        self.assertEqual(self.engine.calls, [])

    def test_forged_control_frame_never_publishes_and_container_is_removed(self):
        self.engine.corrupt_binding = True
        with self.assertRaises(SchemaxisError) as caught:
            self.executor.run(self.request, Cancellation())
        self.assertEqual(caught.exception.fault.code, 'ISOLATION_PROTOCOL_ERROR')
        self.assertFalse(self.request.directory.exists())
        self.assertFalse(self.engine.exists)

    def test_postcleanup_protocol_faults_preserve_exact_isolation(self):
        changes = (
            lambda value, archive: ({**value, 'inventory': {}}, archive),
            lambda value, archive: (value, b'not a tar archive'),
            lambda value, archive: ({k: v for k, v in value.items() if k != 'result'}, archive),
        )
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                self.engine.response_change = change
                request = replace(self.request, job_id='job-'+str(index),
                    directory=self.root/'runs'/('job-'+str(index))/'run')
                # Each fake worker has an independent output tree too.
                worker = self.root/'worker'
                if worker.exists():
                    import shutil
                    shutil.rmtree(worker)
                with self.assertRaises(SchemaxisError) as caught:
                    self.executor.run(request, Cancellation())
                isolation = caught.exception.fault.observed['isolation']
                self.assertEqual(isolation['image'], IMAGE)
                self.assertTrue(isolation['containerExited'])
                self.assertTrue(isolation['cleanup']['removed'])
                self.assertTrue(isolation['cleanup']['containerAbsent'])
                self.assertEqual(isolation['workerObservations']['quiescence']['remainingProcesses'], 0)

    def test_weaker_swap_control_is_refused_without_start(self):
        self.engine.weaken = True
        with self.assertRaises(SchemaxisError) as caught:
            self.executor.run(self.request, Cancellation())
        self.assertEqual(caught.exception.fault.code, 'ISOLATION_UNAVAILABLE')
        self.assertFalse(any(args[1] == 'start' for args, _ in self.engine.calls))
        self.assertFalse(self.engine.exists)

    def test_cancellation_kills_actual_container_and_retains_cleanup_observation(self):
        self.engine.cancel_start = True
        with self.assertRaises(SchemaxisError) as caught:
            self.executor.run(self.request, Cancellation())
        self.assertEqual(caught.exception.fault.code, 'RUNNER_CANCELLED')
        self.assertTrue(any(args[1] == 'kill' and args[-1] == CID for args, _ in self.engine.calls))
        self.assertTrue(caught.exception.fault.observed['isolation']['cleanup']['removed'])

    def test_unknown_cleanup_can_never_return_success(self):
        self.engine.cleanup_fails = True
        with self.assertRaises(SchemaxisError) as caught:
            self.executor.run(self.request, Cancellation())
        self.assertEqual(caught.exception.fault.code, 'ISOLATION_CLEANUP_UNKNOWN')
        self.assertFalse(self.request.directory.exists())

    def test_pin_and_limit_validation(self):
        with self.assertRaises(ValueError):
            IsolationProfile('worker:latest', ('p',), ('v',))
        for changes in ({'memory_bytes': 8*1024**3}, {'cpus': float('nan')},
                        {'disk_bytes': 1024**3}, {'pids': True}):
            with self.assertRaises(ValueError):
                IsolationLimits(**changes)

    def test_ambiguous_create_intent_is_recovered_by_exact_labelled_name(self):
        from schemaxis.container_lifecycle import LifecycleJournal
        nonce = 'c'*32
        journal = LifecycleJournal(self.root)
        journal.begin(name='schemaxis-'+nonce, nonce=nonce, request=self.request,
                      action='run', image=IMAGE, deadline=time.monotonic()+10)
        # Model an owner death between engine create and durable CID update.
        self.engine.exists = self.engine.running = True
        self.engine.record = {'Config': {'Labels': {'io.schemaxis.attempt': nonce,
            'io.schemaxis.job': self.request.job_id, 'io.schemaxis.action': 'run'}}}
        recovered = self.executor.recover(self.root)
        self.assertEqual(len(recovered), 1)
        self.assertTrue(recovered[0]['cleanup']['containerAbsent'])
        self.assertFalse(self.engine.exists)
        self.assertEqual(journal.pending(), [])
        self.assertEqual(self.executor.recover(self.root), [])

    def test_corrupt_recovery_record_blocks_reconciliation(self):
        from schemaxis.container_lifecycle import LifecycleJournal
        nonce = 'c'*32
        journal = LifecycleJournal(self.root)
        journal.begin(name='schemaxis-'+nonce, nonce=nonce, request=self.request,
                      action='run', image=IMAGE, deadline=time.monotonic()+10)
        path = journal.root/(nonce+'.json')
        value = json.loads(path.read_text())
        value['record']['jobId'] = 'forged'
        path.write_text(json.dumps(value))
        with self.assertRaises(SchemaxisError) as caught:
            self.executor.recover(self.root)
        self.assertEqual(caught.exception.fault.code, 'ISOLATION_RECOVERY_FAILED')
        self.assertEqual(self.engine.calls, [])

    def test_absent_ambiguous_create_remains_unresolved_for_late_daemon_rpc(self):
        from schemaxis.container_lifecycle import LifecycleJournal
        nonce = 'c'*32
        journal = LifecycleJournal(self.root)
        journal.begin(name='schemaxis-'+nonce, nonce=nonce, request=self.request,
                      action='run', image=IMAGE, deadline=time.monotonic()+10)
        with self.assertRaises(SchemaxisError) as caught:
            self.executor.recover(self.root)
        self.assertEqual(caught.exception.fault.code, 'ISOLATION_RECOVERY_FAILED')
        self.assertEqual(len(journal.pending()), 1)
        self.assertEqual(journal.pending()[0]['state'], 'intent')
        # The delayed create may become visible only after that failed recovery.
        self.engine.exists = self.engine.running = True
        self.engine.record = {'Config': {'Labels': {'io.schemaxis.attempt': nonce,
            'io.schemaxis.job': self.request.job_id, 'io.schemaxis.action': 'run'}}}
        recovered = self.executor.recover(self.root)
        self.assertTrue(recovered[0]['cleanup']['containerAbsent'])


class EvidenceArchiveTests(unittest.TestCase):
    def archive(self, entries):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w') as archive:
            for name, kind, contents in entries:
                entry = tarfile.TarInfo(name)
                entry.type = kind
                if kind == tarfile.REGTYPE:
                    entry.size = len(contents)
                    archive.addfile(entry, io.BytesIO(contents))
                else:
                    entry.linkname = '/outside' if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE) else ''
                    archive.addfile(entry)
        return output.getvalue()

    def test_all_unsafe_members_are_rejected_before_any_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'target'
            for name, kind in (('run/../escape', tarfile.REGTYPE),
                               ('/run/absolute', tarfile.REGTYPE),
                               ('run/link', tarfile.SYMTYPE), ('run/hard', tarfile.LNKTYPE),
                               ('run/pipe', tarfile.FIFOTYPE), ('run//alias', tarfile.REGTYPE)):
                with self.subTest(name=name, kind=kind):
                    data = self.archive([('run', tarfile.DIRTYPE, b''),
                        ('run/good', tarfile.REGTYPE, b'good'), (name, kind, b'bad')])
                    with self.assertRaises(SchemaxisError):
                        unpack_tree(data, target, 4096, 16)
                    self.assertFalse(target.exists())

    def test_duplicate_and_oversize_payload_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            for entries in ([('run', tarfile.DIRTYPE, b''),
                             ('run/a', tarfile.REGTYPE, b'x'), ('run/a', tarfile.REGTYPE, b'y')],
                            [('run', tarfile.DIRTYPE, b''), ('run/a', tarfile.REGTYPE, b'x'*4097)]):
                with self.assertRaises(SchemaxisError):
                    unpack_tree(self.archive(entries), Path(directory)/'target', 4096, 16)
                self.assertFalse((Path(directory)/'target').exists())

    def test_missing_directory_ancestors_cannot_multiply_exported_host_inodes(self):
        with tempfile.TemporaryDirectory() as directory:
            data = self.archive([('run', tarfile.DIRTYPE, b''),
                                 ('run/implicit-a/implicit-b/file', tarfile.REGTYPE, b'x')])
            target = Path(directory)/'target'
            with self.assertRaises(SchemaxisError):
                unpack_tree(data, target, 4096, 16)
            self.assertFalse(target.exists())

    def test_shared_schema_dependency_survives_bounded_export_without_rewriting(self):
        from schemaxis.schema_snapshots import store_shared, read
        with tempfile.TemporaryDirectory() as directory:
            owner = Path(directory)/'source'
            run = owner/'run'
            run.mkdir(parents=True)
            schema = encoded({'type': 'object', 'properties': {'version': {'const': 'example/1'}}})
            manifest = store_shared(owner, run/'schema.snapshot.json', schema,
                                    provider='example', document_version='example/1')
            original = manifest.read_bytes()
            (owner/'unrelated-secret').write_bytes(b'not exported')
            (owner/'schemas'/'unreferenced').write_bytes(b'not exported')
            data, inventory = pack_tree(run, 16384, 32)
            self.assertEqual(len(inventory), 2)
            self.assertIn('run/schema.snapshot.json', inventory)
            target = Path(directory)/'target'
            self.assertEqual(unpack_tree(data, target, 16384, 32), inventory)
            self.assertEqual((target/'run/schema.snapshot.json').read_bytes(), original)
            self.assertEqual(read(target/'run/schema.snapshot.json'), read(manifest))
            self.assertFalse((target/'schemas/index.json').exists())
            self.assertFalse((target/'unrelated-secret').exists())
            self.assertFalse((target/'schemas/unreferenced').exists())
            with self.assertRaises(SchemaxisError):
                pack_tree(run, 16384, 3)

    def test_schema_dependency_outside_job_or_symlink_is_refused(self):
        from schemaxis.schema_snapshots import store_shared
        with tempfile.TemporaryDirectory() as directory:
            outer = Path(directory)
            owner = outer/'job'
            run = owner/'run'
            run.mkdir(parents=True)
            schema = encoded({'properties': {'version': {'const': 'example/1'}}})
            store_shared(outer, run/'schema.snapshot.json', schema,
                         provider='example', document_version='example/1')
            with self.assertRaises(SchemaxisError):
                pack_tree(run, 16384, 32)
            (run/'schema.snapshot.json').unlink()
            store_shared(owner, run/'schema.snapshot.json', schema,
                         provider='example', document_version='example/1')
            import shutil
            shutil.rmtree(owner/'schemas')
            (owner/'schemas').symlink_to(outer/'schemas', target_is_directory=True)
            with self.assertRaises(SchemaxisError):
                pack_tree(run, 16384, 32)

    def test_schema_archive_accepts_only_digest_named_regular_objects(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ('schemas/index.json', 'schemas/'+'a'*64+'.json', 'schemas/nested/file'):
                data = self.archive([('run', tarfile.DIRTYPE, b''),
                                     ('schemas', tarfile.DIRTYPE, b''),
                                     (name, tarfile.REGTYPE, b'bad')])
                target = Path(directory)/'target'
                with self.assertRaises(SchemaxisError):
                    unpack_tree(data, target, 4096, 16)
                self.assertFalse(target.exists())

    def test_truncated_or_forged_frame_is_refused(self):
        for value in (b'', frame({'verified': True})[:-1], frame({'verified': True})+b'extra'):
            with self.assertRaises(SchemaxisError):
                unframe(value, 1024)

    def test_export_rejects_host_symlink_and_hardlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'run'
            root.mkdir()
            (root/'source').write_bytes(b'x')
            (root/'alias').symlink_to(root/'source')
            with self.assertRaises(SchemaxisError):
                pack_tree(root, 4096, 16)
            (root/'alias').unlink()
            import os
            os.link(root/'source', root/'alias')
            with self.assertRaises(SchemaxisError):
                pack_tree(root, 4096, 16)


class LocalExecutorTests(unittest.TestCase):
    def test_local_backend_preserves_registry_parameters_and_response(self):
        request = ExecutionRequest('job', 'plan', {'version': 'v'}, {}, 'doc', 'plan',
            Path('/unused/run'), Path('/unused'), ('p',), (), 7, None, {'p': '/native'})
        sentinel = {'verified': True, 'ordinary': ['result']}
        with patch('schemaxis.adaptors.registry.run', return_value=sentinel) as run:
            outcome = LocalExecutor().run(request, Cancellation())
        self.assertIs(outcome.response, sentinel)
        run.assert_called_once_with(request.document, request.directory,
                                    locations=request.locations, timeout=7)
        with patch('schemaxis.adaptors.registry.verify', return_value=sentinel) as verify:
            outcome = LocalExecutor().verify(VerificationRequest(request), Cancellation())
        self.assertIs(outcome.response, sentinel)
        verify.assert_called_once_with(request.directory, request.document)


class ServiceBackendDouble:
    isolated = True

    def recover(self, workspace):
        return []

    def plan(self, request, cancellation):
        return PlanningOutcome({'fixtureOnly': 'declared-plan'},
            {'action': 'plan', 'operationId': request.operation_id, 'planningPhase': request.phase,
             'containerExited': True, 'cleanup': {'removed': True, 'containerAbsent': True}})


class ServiceExecutorSeamTests(unittest.TestCase):
    def test_isolated_admission_precedes_workflow_design_compilation(self):
        from schemaxis.execution_service import ExecutionService
        class Backend(ServiceBackendDouble):
            def admit(self, document, inputs=None, *, bound=False):
                failure('ISOLATION_UNAVAILABLE', 'designs denied before hooks')
        with tempfile.TemporaryDirectory() as root, ExecutionService(root, executor=Backend()) as service:
            task = service.create_task('pure admission', ['freecad'])
            with patch('schemaxis.workflow_design.compile', side_effect=AssertionError('planner hook')):
                with self.assertRaises(SchemaxisError) as caught:
                    service.plan(task['id'], {'version': 'schemaxis.workflow-design/1'}, 0)
            self.assertEqual(caught.exception.fault.code, 'ISOLATION_UNAVAILABLE')

    def test_isolated_run_reverify_collection_never_call_host_native_paths(self):
        from schemaxis.execution_service import ExecutionService
        class Backend(ServiceBackendDouble):
            calls = []
            def admit(self, document, inputs=None, *, bound=False):
                self.calls.append('admit')
            def run(self, request, cancellation):
                self.calls.append('run')
                self.request = request
                request.directory.mkdir()
                (request.directory/'authored.json').write_bytes(encoded(request.document))
                (request.directory/'verification.json').write_bytes(encoded({'verified': True, 'artifacts': []}))
                return ExecutionOutcome({'verified': True, 'ordinary': 'core-result'}, {'testDouble': True})
            def verify(self, request, cancellation):
                self.calls.append('verify')
                return VerificationOutcome({'verified': True, 'ordinary': 'core-verifier'},
                                           {'testDouble': True}, [])
        backend = Backend()
        document = {'version': 'schemaxis.freecad/1',
                    'nodes': [{'id': 'body', 'filter': 'box'}], 'output': 'body'}
        with tempfile.TemporaryDirectory() as root:
            with ExecutionService(root, executor=backend) as service:
                task = service.create_task('seam proof', ['freecad'])
                with patch('schemaxis.adaptors.registry.plan', side_effect=AssertionError('host plan')):
                    plan = service.plan(task['id'], document, 0)
                with (patch('schemaxis.adaptors.registry.run', side_effect=AssertionError('host run')),
                     patch('schemaxis.adaptors.registry.verify', side_effect=AssertionError('host verify')),
                     patch('schemaxis.publication_metadata.verify', side_effect=AssertionError('host metadata'))):
                    job = service.execute(plan['id'], plan['revision'])
                    service.runner.futures[job['id']].result(timeout=5)
                    self.assertEqual(service.job(job['id'])['status'], 'succeeded')
                    verified = service.verify(job['id'])
                self.assertEqual(verified['value']['ordinary'], 'core-verifier')
                self.assertEqual(backend.calls.count('verify'), 2)
                self.assertEqual(backend.request.directory.name, 'run')
                self.assertEqual(backend.request.document_digest, plan['documentDigest'])
                self.assertEqual([item['id'] for item in service.jobs_for_plan(plan['id'])], [job['id']])
                self.assertIn('isolation', service.job(job['id']))
                self.assertNotIn('_isolated_publications', service.state['jobs'][job['id']])
                cancelled = Cancellation()
                cancelled.set()
                with self.assertRaises(SchemaxisError) as caught:
                    service.verify_with_control(job['id'], cancellation=cancelled,
                                                deadline=time.monotonic()+1)
                self.assertEqual(caught.exception.fault.code, 'RUNNER_CANCELLED')
                self.assertEqual(backend.calls.count('verify'), 2)

    def test_run_boolean_cannot_bypass_verifier_failure(self):
        from schemaxis.execution_service import ExecutionService
        class Backend(ServiceBackendDouble):
            def admit(self, document, inputs=None, *, bound=False):
                pass
            def run(self, request, cancellation):
                request.directory.mkdir()
                (request.directory/'authored.json').write_bytes(encoded(request.document))
                (request.directory/'verification.json').write_bytes(encoded({'verified': True}))
                return ExecutionOutcome({'verified': True})
            def verify(self, request, cancellation):
                return VerificationOutcome({'verified': False}, publications=[])
        with tempfile.TemporaryDirectory() as root, ExecutionService(root, executor=Backend()) as service:
            task = service.create_task('verifier proof', ['freecad'])
            document = {'version': 'schemaxis.freecad/1',
                        'nodes': [{'id': 'body', 'filter': 'box'}], 'output': 'body'}
            plan = service.plan(task['id'], document, 0)
            job = service.execute(plan['id'], plan['revision'])
            service.runner.futures[job['id']].result(timeout=5)
            state = service.job(job['id'])
            self.assertEqual(state['status'], 'failed')
            self.assertFalse(state['verified'])
            self.assertEqual(state['faultCode'], 'VERIFICATION_FAILED')


class IndependentWatchdogTests(unittest.TestCase):
    def test_tmpfs_proof_accepts_kernel_escaped_workspace_path(self):
        from types import SimpleNamespace
        from schemaxis.container_worker import enforced_limits
        contents = {'memory.max': str(512*1024**2), 'memory.swap.max': '0',
                    'pids.max': '64', 'cpu.max': '100000 100000',
                    'mountinfo': '29 23 0:50 / /owned/a\\040b rw - tmpfs tmpfs rw,size=4k\n'}
        with (patch('schemaxis.container_worker.os.getppid', return_value=1),
              patch('schemaxis.container_worker.Path.read_text', autospec=True,
                    side_effect=lambda path: contents[path.name]),
              patch('schemaxis.container_worker.os.statvfs',
                    return_value=SimpleNamespace(f_blocks=1, f_frsize=4096, f_files=16))):
            observed = enforced_limits(Path('/owned/a b'),
                {'memory_bytes': 512*1024**2, 'pids': 64, 'cpus': 1, 'disk_bytes': 4096, 'inodes': 16})
        self.assertEqual(observed['tmpfsBytes'], 4096)

    def test_cpu_sample_names_application_boundary_and_excludes_export_teardown(self):
        from schemaxis.container_worker import metrics
        with patch('schemaxis.container_worker.Path.read_text', return_value='usage_usec 42\n'):
            sample = metrics()
        self.assertEqual(sample['kind'], 'observed-worker-cgroup-sample')
        self.assertEqual(sample['boundary'], 'post-native-quiescence-pre-export')
        self.assertEqual(sample['cpu.stat'], 'usage_usec 42\n')
        self.assertEqual(sample['excludes'], ['archive export', 'container teardown'])

    def test_pid1_supervisor_kills_children_on_total_deadline_without_worker_cooperation(self):
        from schemaxis.container_worker import supervise
        processes = [Path('/proc/1'), Path('/proc/2'), Path('/proc/3')]
        with (patch('schemaxis.container_worker.os.waitpid', return_value=(0, 0)),
              patch('schemaxis.container_worker.time.monotonic', side_effect=[0, 2]),
              patch('schemaxis.container_worker.Path.iterdir', return_value=iter(processes)),
              patch('schemaxis.container_worker.os.kill') as kill,
              patch('schemaxis.container_worker.os.close')):
            result = supervise(2, 99, startup_seconds=1)
        self.assertEqual(result, 124)
        self.assertEqual([call.args[0] for call in kill.call_args_list], [2, 3])

    def test_export_quiescence_excludes_only_exporter_and_pid1_supervisor(self):
        from schemaxis.container_worker import quiesce
        processes = [Path('/proc/1'), Path('/proc/2')]
        with (patch('schemaxis.container_worker.os.getpid', return_value=2),
              patch('schemaxis.container_worker.os.getppid', return_value=1),
              patch('schemaxis.container_worker.Path.iterdir', side_effect=lambda: iter(processes)),
              patch('schemaxis.container_worker.os.waitpid', side_effect=ChildProcessError),
              patch('schemaxis.container_worker.os.kill') as kill):
            result = quiesce()
        self.assertEqual(result['remainingProcesses'], 0)
        kill.assert_not_called()
