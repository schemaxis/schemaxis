"""Cross-module scheduling/captures with a worker double, not native qualification."""
import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from schemaxis import workflow
from schemaxis.adaptors import registry
from schemaxis.app_modules import ModuleManager
from schemaxis.artifacts import file_digest
from schemaxis.core.faults import SchemaxisError
from schemaxis.errors import fail
from schemaxis.execution_backends import ExecutionOutcome, VerificationOutcome
from schemaxis.module_runtime import runtime, ModuleAdmission, retained_inputs
from schemaxis.storage import atomic, encoded, load
from test_app_modules import Engine, module


class Worker:
    calls = []

    def __init__(self, resolver, *, admission, engine, capture_policy):
        self.admission, self.policy = admission, capture_policy
        self.profile = resolver.profiles[0]

    def run(self, request, cancellation):
        self.calls.append(('run', request.providers, request.document))
        self.admission.check(request.document, request.inputs, bound=request.inputs is not None)
        if self.policy:
            with self.policy.lease(request.inputs):
                pass
        directory = request.directory
        directory.mkdir(parents=True)
        atomic(directory/'authored.json', encoded(request.document))
        filename = directory/('summary.json' if request.providers == ('sympy',) else 'scores.csv')
        filename.write_text('{"degree":2}' if filename.suffix == '.json' else 'x,y\n1,2\n')
        receipt = {'verified': True, 'artifacts': [{'file': str(filename), 'kind': 'text' if filename.suffix == '.json' else 'table',
                                                'sha256': file_digest(filename)}]}
        atomic(directory/'verification.json', encoded(receipt))
        from schemaxis.schema_snapshots import capture_run
        from schemaxis.publication_metadata import publish_artifacts
        capture_run(directory, request.document, workspace_root=directory.parent)
        publish_artifacts(directory, receipt['artifacts'])
        return ExecutionOutcome({'verified': True}, {'image': self.profile.image})

    def verify(self, request, cancellation):
        execution = request.execution
        self.calls.append(('verify', execution.providers, execution.document))
        self.admission.check(execution.document, execution.inputs, bound=execution.inputs is not None)
        if self.policy:
            with self.policy.lease(execution.inputs):
                pass
        if load((execution.directory/'authored.json').read_text()) != execution.document:
            fail('VERIFICATION_FAILED', 'worker authored document changed')
        receipt = load((execution.directory/'verification.json').read_text())
        if any(file_digest(Path(row['file'])) != row['sha256'] for row in receipt['artifacts']):
            fail('VERIFICATION_FAILED', 'worker publication changed')
        return VerificationOutcome({'verified': True}, {'image': self.profile.image}, [])


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manager = ModuleManager(self.root/'modules', engine=Engine())
        self.manager.register(module())
        numpy = module('numpy')
        numpy.update(provider='numpy', routes=['schemaxis.numpy/1'], applicationVersion='2.5.4',
                     inputFiles={'schemaxis.numpy/1': ['/source']})
        self.manager.register(numpy)
        self.source = self.root/'source.csv'
        self.source.write_text('time,ch1,ch2\n0,1,2\n1,2,3\n2,3,4\n')
        self.producer = {'version': 'schemaxis.sympy/1', 'operation': 'isolateRealRoots',
                         'coefficients': ['1', '0', '-2'], 'maximumIntervalWidth': '1/1000'}
        self.consumer = {'version': 'schemaxis.numpy/1', 'operation': 'principalComponents',
            'source': str(self.source), 'rowKey': {'name': 'time', 'unit': 's'},
            'channels': [{'name': 'ch1', 'unit': 'mV'}, {'name': 'ch2', 'unit': 'mV'}],
            'scaling': 'none', 'retention': {'components': {'$value': 'roots', 'artifact': 0, 'path': '/degree'}},
            'output': 'components'}
        self.document = {'version': 'schemaxis.workflow/1', 'operations': [
            {'id': 'roots', 'document': self.producer}, {'id': 'pca', 'document': self.consumer}]}
        patcher = patch('schemaxis.module_runtime.ContainerExecutor', Worker)
        patcher.start()
        self.addCleanup(patcher.stop)
        Worker.calls = []

    def test_cross_module_value_handoff_and_retained_input_verification(self):
        output = self.root/'output'
        with runtime(self.document, manager=self.manager):
            result = workflow.execute(self.document, output)
            self.assertTrue(result['verified'])
            self.assertTrue(workflow.verify(output)['verified'])
            runs = [call for call in Worker.calls if call[0] == 'run']
            self.assertEqual([call[1] for call in runs], [('sympy',), ('numpy',)])
            self.assertEqual(runs[1][2]['retention']['components'], 2)
            self.assertNotEqual(runs[1][2]['source'], str(self.source))
            self.assertEqual(Path(runs[1][2]['source']).read_bytes(), self.source.read_bytes())
            workflow.execute(self.document, output, resume=True)
            self.assertEqual(len([call for call in Worker.calls if call[0] == 'run']), 2)
            self.source.unlink()
            self.assertTrue(workflow.verify(output)['verified'])

    def test_logical_or_worker_publication_tampering_refuses(self):
        output = self.root/'output'
        with runtime(self.producer, manager=self.manager):
            registry.run(self.producer, output)
            (output/'run/summary.json').write_text('{"degree":9}')
            with self.assertRaises(SchemaxisError) as caught:
                registry.verify(output, self.producer)
            self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')

    def test_cache_cannot_be_cleared_while_workflow_owns_shared_lease(self):
        self.manager.fetch(['sympy'])
        plan = self.manager.cleanup_plan(['sympy'])
        with runtime(self.producer, manager=self.manager):
            with self.assertRaises(SchemaxisError) as caught:
                self.manager.clear(plan, plan['confirmation'])
            self.assertEqual(caught.exception.fault.code, 'MODULES_BUSY')

    def test_missing_module_has_no_native_fallback_and_does_not_start_workers(self):
        unknown = {'version': 'schemaxis.freecad/1', 'operation': 'anything'}
        with self.assertRaises(SchemaxisError) as caught:
            with runtime(unknown, manager=self.manager):
                self.fail('unavailable route entered execution')
        self.assertEqual(caught.exception.fault.code, 'MODULE_ROUTE_UNAVAILABLE')
        self.assertFalse(Worker.calls)

    def test_modified_capture_is_rejected_before_verification(self):
        document = copy.deepcopy(self.consumer)
        document['retention'] = {'components': 2}
        output = self.root/'output'
        with runtime(document, manager=self.manager):
            registry.run(document, output)
            record = load((output/'module-run.json').read_text())['record']
            path = Path(record['workerDocument']['source'])
            path.chmod(0o644)
            path.write_text('changed')
            with self.assertRaises(SchemaxisError):
                registry.verify(output, document)

    def test_manifest_file_slots_are_closed_and_explicit(self):
        item = module()
        item['inputFiles']['schemaxis.sympy/1'] = ['/inputs/*/file']
        policy = ModuleAdmission(item)
        self.assertEqual(policy.input_slots({'version': 'schemaxis.sympy/1',
            'inputs': [{'file': '/tmp/a'}, {'file': '/tmp/b'}]}), ['/inputs/0/file', '/inputs/1/file'])
        with self.assertRaises(SchemaxisError):
            policy.input_slots({'version': 'schemaxis.sympy/1', 'inputs': [{'file': {'$artifact': 'later'}}]})

    def test_capture_relocation_cannot_validate_an_invalid_logical_source(self):
        document = copy.deepcopy(self.consumer)
        document.update(source='relative.csv', retention={'components': 2})
        with runtime(document, manager=self.manager):
            with self.assertRaises(SchemaxisError) as caught:
                registry.run(document, self.root/'output')
            self.assertEqual(caught.exception.fault.code, 'PCA_INVALID_SOURCE')
        self.assertFalse(Worker.calls)


if __name__ == '__main__':
    unittest.main()
