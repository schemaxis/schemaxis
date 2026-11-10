"""Local opaque captures: exact bindings, hostile files and MCP delegation."""
import copy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis.execution_inputs import CapturePolicy
from schemaxis.execution_service import ExecutionService
from schemaxis.mcp import MODERN, McpDispatcher
from schemaxis.mcp_admission import FileAdmission
from schemaxis.mcp_inputs import LocalInputs
from schemaxis.mcp_isolation import configured_executor


def request(name, arguments):
    return {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
        'name': name, 'arguments': arguments, '_meta': {
            'io.modelcontextprotocol/protocolVersion': MODERN,
            'io.modelcontextprotocol/clientCapabilities': {}}}}


class LocalInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        captures = self.root/'captures'
        captures.mkdir(mode=0o700)
        self.policy = CapturePolicy(captures, 'local-inputs', 65536, 4)
        self.inputs = LocalInputs(self.policy)
        self.source = self.root/'measurements.csv'
        self.source.write_text('time,x,y\n0,1,2\n1,3,4\n2,5,6\n')
        self.inputs.import_source(self.source, identity='measurements', label='Measurements')
        self.service = ExecutionService(self.root/'service')
        self.addCleanup(self.service.close)
        self.task = self.service.create_task('Inspect numeric measurements', ['numpy'])
        self.document = {'version': 'schemaxis.numpy/1', 'operation': 'principalComponents',
            'source': 'measurements', 'rowKey': {'name': 'time', 'unit': 's'},
            'channels': [{'name': 'x', 'unit': 'mV'}, {'name': 'y', 'unit': 'mV'}],
            'scaling': 'none', 'retention': {'components': 1}, 'output': 'components'}

    def test_inventory_survives_restart_and_never_returns_paths_or_bytes(self):
        reopened = LocalInputs(self.policy)
        result = reopened.list(self.service, self.task['id'])
        self.assertEqual(result['inputs'][0]['id'], 'measurements')
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertNotIn('time,x,y', json.dumps(result))
        self.assertEqual(reopened.resolve(self.service, self.task['id'], self.document,
            FileAdmission()).captures[0].path.read_bytes(), self.source.read_bytes())

    def test_unknown_id_and_authored_paths_refuse_before_planner(self):
        for source in ('/etc/passwd', '../measurements.csv', 'unknown'):
            with self.subTest(source=source), patch('schemaxis.execution_service.registry.plan', side_effect=AssertionError('planner ran')):
                with self.assertRaises(SchemaxisError):
                    self.inputs.resolve(self.service, self.task['id'], {**self.document, 'source': source}, FileAdmission())

    def test_capture_mutation_and_external_inventory_edit_refuse(self):
        capture = self.inputs._capture('measurements')
        capture.path.chmod(0o644)
        capture.path.write_bytes(b'x'*capture.bytes)
        capture.path.chmod(0o444)
        with self.assertRaises(SchemaxisError):
            self.inputs.resolve(self.service, self.task['id'], self.document, FileAdmission())
        self.inputs.index_path.write_text('{}')
        with self.assertRaises(SchemaxisError):
            self.inputs.list(self.service, self.task['id'])

    def test_source_links_and_fifo_refuse_without_hanging(self):
        link = self.root/'alias.csv'
        link.symlink_to(self.source)
        with self.assertRaises(SchemaxisError):
            self.inputs.import_source(link, identity='alias')
        link.unlink()
        os.link(self.source, link)
        with self.assertRaises(SchemaxisError):
            self.inputs.import_source(link, identity='hardlink')
        link.unlink()
        os.mkfifo(self.root/'pipe.csv')
        with self.assertRaises(SchemaxisError):
            self.inputs.import_source(self.root/'pipe.csv', identity='pipe')

    def test_byte_capacity_and_wrong_digest_leave_no_capture(self):
        for identity, source, digest in [('wrong', self.source, 'sha256:'+'0'*64),
                                         ('large', self.root/'large.csv', None)]:
            if identity == 'large':
                source.write_bytes(b'x'*65536)
            with self.assertRaises(SchemaxisError):
                self.inputs.import_source(source, identity=identity, expected_digest=digest)
            self.assertFalse((self.policy.root/(identity+'.csv')).exists())
            self.assertNotIn(identity, LocalInputs(self.policy).index['items'])

    def test_orphan_capture_consumes_capacity_after_interrupted_publication(self):
        for index in range(3):
            (self.policy.root/('orphan-'+str(index))).write_bytes(b'x')
        with self.assertRaises(SchemaxisError):
            self.inputs.import_source(self.source, identity='another')

    def test_same_id_retry_never_deletes_preexisting_orphan_even_on_byte_quota_refusal(self):
        orphan = self.policy.root/'interrupted.csv'
        for payload, fault in ((b'uncertain publication', FileExistsError), (b'x'*65520, SchemaxisError)):
            orphan.write_bytes(payload)
            before = orphan.stat()
            with self.subTest(bytes=len(payload)), self.assertRaises(fault):
                self.inputs.import_source(self.source, identity='interrupted')
            self.assertEqual(orphan.read_bytes(), payload)
            self.assertEqual((orphan.stat().st_dev, orphan.stat().st_ino), (before.st_dev, before.st_ino))
            self.assertNotIn('interrupted', LocalInputs(self.policy).index['items'])

    def test_failed_copy_cleanup_preserves_replacement_of_its_own_target(self):
        target = self.policy.root/'replaced.csv'
        def replace_after_write(descriptor):
            target.unlink()
            target.write_bytes(b'foreign replacement')
        with patch('schemaxis.mcp_inputs.os.fsync', side_effect=replace_after_write):
            with self.assertRaises(SchemaxisError):
                self.inputs.import_source(self.source, identity='replaced', expected_digest='0'*64)
        self.assertEqual(target.read_bytes(), b'foreign replacement')

    def dispatcher(self):
        self.service.executor = SimpleNamespace(isolated=True, capture_policy=self.policy)
        return McpDispatcher(self.service, input_store=self.inputs)

    def test_mcp_plan_uses_only_generated_opaque_bindings(self):
        dispatcher = self.dispatcher()
        with patch.object(self.service, 'plan_with_inputs', return_value={'id': 'prepared'}) as plan:
            result = dispatcher.handle(request('plan', {'task_id': self.task['id'],
                'document': self.document, 'expected_revision': 0}))['result']['structuredContent']
        self.assertTrue(result['ok'], result)
        args = plan.call_args
        self.assertEqual(args.kwargs['inputs'].slots, (('/source', 'measurements'),))
        self.assertEqual(args.args[1]['source'], 'measurements')
        self.assertTrue(args.kwargs['operation_id'].startswith('capture-'))
        self.assertTrue(args.kwargs['plan_id'].startswith('plan-'))

    def test_mcp_authored_binding_denied_without_delegation(self):
        dispatcher = self.dispatcher()
        with patch.object(self.service, 'plan_with_inputs') as plan:
            result = dispatcher.handle(request('plan', {'task_id': self.task['id'],
                'document': self.document, 'expected_revision': 0,
                'bindings': {'/source': '/etc/passwd'}}))['result']['structuredContent']
        self.assertFalse(result['ok'])
        plan.assert_not_called()

    def test_mcp_input_tool_requires_declared_arguments_and_task(self):
        dispatcher = self.dispatcher()
        result = dispatcher.handle(request('inputs_list', {'task_id': self.task['id']}))['result']['structuredContent']
        self.assertTrue(result['ok'])
        self.assertNotIn(str(self.root), json.dumps(result))
        for args in ({'task_id': 'unknown'}, {'task_id': self.task['id'], 'path': str(self.source)}):
            result = dispatcher.handle(request('inputs_list', args))['result']['structuredContent']
            self.assertFalse(result['ok'])

    def test_promotion_requires_fresh_verified_resource_and_exact_digest(self):
        resource = {'job': 'producer', 'file': 'artifact.csv',
                    'sha256': hashlib.sha256(self.source.read_bytes()).hexdigest()}
        (self.service.workspace/'artifact.csv').write_bytes(self.source.read_bytes())
        with patch.object(self.service, '_resource', return_value=resource), patch.object(self.service, 'verify') as verify:
            promoted = self.inputs.promote(self.service, self.task['id'], 'resource-id')
        verify.assert_called_once_with('producer')
        self.assertEqual(promoted['sha256'], 'sha256:'+resource['sha256'])
        self.assertNotIn(str(self.root), json.dumps(promoted))
        with patch.object(self.service, '_resource', side_effect=SchemaxisError(Fault(
                'UNVERIFIED_RESOURCE', 'Producer failed verification', '$', 'test'))), patch.object(self.service, 'verify') as verify:
            with self.assertRaises(SchemaxisError):
                self.inputs.promote(self.service, self.task['id'], 'unverified')
        verify.assert_not_called()

    def test_strict_profile_never_executes_on_host_without_image_configuration(self):
        dispatcher = McpDispatcher(self.service)
        for name, args in [('execute', {'plan_id': 'missing', 'expected_revision': 0}),
                           ('verify', {'job_id': 'missing'}),
                           ('run_tool', {'task_id': self.task['id'], 'package_digest': 'missing',
                             'values': {}, 'expected_revision': 0, 'execute': True})]:
            with self.subTest(name=name), patch('subprocess.Popen', side_effect=AssertionError('host executed')):
                result = dispatcher.handle(request(name, args))['result']['structuredContent']
                self.assertEqual(result['fault']['code'], 'ISOLATION_UNAVAILABLE')

    def config(self):
        return {'version': 1, 'profiles': [{'image': 'example/runtime@sha256:'+'a'*64,
            'providers': ['numpy'], 'routes': ['schemaxis.numpy/1'], 'qualification_id': 'reviewed-case',
            'capabilities': ['captured-input-planning-v1'],
            'limits': {'memory_bytes': 536870912, 'cpus': 1, 'pids': 64,
                       'disk_bytes': 33554432, 'inodes': 4096, 'wall_seconds': 60}}],
            'captures': {'root': str(self.policy.root), 'namespace': self.policy.namespace,
                         'max_bytes': self.policy.max_bytes, 'max_files': self.policy.max_files}, 'inputs': []}

    def test_operator_configuration_pins_images_limits_and_has_no_default_permissions(self):
        config = self.config()
        path = self.root/'operator.json'
        path.write_text(json.dumps(config))
        executor, inputs = configured_executor(path)
        self.assertTrue(executor.isolated)
        self.assertEqual(inputs.policy, self.policy)
        for change in ('mutable-image', 'ambiguous-profile', 'no-limits', 'unqualified'):
            document = copy.deepcopy(config)
            if change == 'mutable-image': document['profiles'][0]['image'] = 'example/runtime:latest'
            if change == 'ambiguous-profile': document['profiles'] *= 2
            if change == 'no-limits': document['profiles'][0]['limits'] = {}
            if change == 'unqualified': document['profiles'][0]['qualification_id'] = 'unqualified'
            path.write_text(json.dumps(document))
            with self.subTest(change=change), self.assertRaises(ValueError):
                configured_executor(path)

    def test_raw_digest_configuration_import_and_identical_restart_agree(self):
        config = self.config()
        config['inputs'] = [{'id':'from-startup','source':str(self.source), 'label':'Startup measurements',
                             'sha256':hashlib.sha256(self.source.read_bytes()).hexdigest()}]
        path = self.root/'operator.json'
        path.write_text(json.dumps(config))
        _, first = configured_executor(path)
        _, reopened = configured_executor(path)
        self.assertEqual(first.index, reopened.index)
        self.assertEqual(reopened.index['items']['from-startup']['sha256'], 'sha256:'+config['inputs'][0]['sha256'])
