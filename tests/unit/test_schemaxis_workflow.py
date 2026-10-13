import json
from pathlib import Path
import unittest
from unittest.mock import patch
import tempfile
from schemaxis.core.faults import SchemaxisError
from schemaxis.workflow import validate, execute, inspect_plan
from schemaxis.blender_adaptor import plan as blender_plan
from schemaxis.analytics import AnalyticRegistry


class WorkflowTests(unittest.TestCase):
    def test_new_nested_and_existing_empty_output_directories(self):
        document = {'version': 'schemaxis.workflow/1', 'operations': [
            {'id': 'one', 'document': {}}]}
        with tempfile.TemporaryDirectory() as temp:
            for existing in (False, True):
                target = Path(temp) / str(existing) / 'nested' / 'run'
                if existing:
                    target.mkdir(parents=True)
                def completed(document, directory, **options):
                    directory.mkdir()
                    (directory/'verification.json').write_text(json.dumps({'artifacts': []}))
                    return {'verified': True}
                with self.subTest(existing=existing), patch('schemaxis.workflow.run', side_effect=completed) as runner:
                    self.assertTrue(execute(document, target)['verified'])
                    self.assertEqual(json.loads((target / 'authored.json').read_text()), document)
                    with self.assertRaises(SchemaxisError) as caught:
                        execute(document, target)
                    self.assertEqual(caught.exception.fault.code, 'OUTPUT_EXISTS')
                    self.assertEqual(runner.call_count, 1)
                    self.assertEqual(json.loads((target/'publication-metadata.json').read_text())['publications'], [])

    def test_forward_reference_rejected(self):
        document = {'version': 'schemaxis.workflow/1', 'operations': [
            {'id': 'first', 'document': {'file': {'$artifact': 'later', 'index': 0}}}]}
        with self.assertRaises(SchemaxisError) as caught:
            validate(document)
        self.assertEqual(caught.exception.fault.code, 'UNAVAILABLE_OPERATION')

    def test_workflow_plan_marks_deferred_handoffs(self):
        document = json.loads(Path('examples/schemaxis/operation-handoff.json').read_text())
        result = inspect_plan(document)
        self.assertEqual(len(result['operations']), 2)
        self.assertEqual(result['operations'][1]['artifactReferences'], [{'$artifact': 'produce', 'index': 0}])

    def test_failure_stops_next_operation(self):
        document = {'version': 'schemaxis.workflow/1', 'operations': [
            {'id': 'one', 'document': {}}, {'id': 'two', 'document': {}}]}
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'run'
            with patch('schemaxis.workflow.run', side_effect=RuntimeError('native failed')) as runner:
                with self.assertRaises(RuntimeError):
                    execute(document, target)
                self.assertEqual(runner.call_count, 1)
            result = json.loads((target / 'result.json').read_text())
            self.assertEqual(result['status'], 'failed')
            self.assertFalse(result['verified'])

    def test_blender_uses_shared_analytics_and_prunes(self):
        document = json.loads(Path('examples/schemaxis/blender-showcase.json').read_text())
        master, selected, result = blender_plan(document)
        self.assertNotIn('unusedPaint', selected.order)
        self.assertEqual(selected.count, 2)
        self.assertEqual(result['expectedPublications'], 8)
        self.assertEqual(len(master.analytic_bindings), 2)
        self.assertEqual(master.nodes['box']['inputs'], {'material': 'paint'})

    def test_custom_analytic_factory(self):
        registry = AnalyticRegistry()
        registry.register('powers', lambda spec, location, limit: [2**i for i in range(spec['count'])])
        self.assertEqual(registry.values({'type': 'powers', 'count': 3}, 'test', 10), [1, 2, 4])
        with self.assertRaises(SchemaxisError):
            registry.values({'type': 'powers', 'count': 3}, 'test', 2)

    def test_native_fault_preserves_contract(self):
        from schemaxis.native_boundary import execute_guarded
        from schemaxis.errors import fail
        with tempfile.TemporaryDirectory() as directory:
            def operation(path):
                fail('EXPECTED_TEST_FAULT', 'a native fault', 'node.option')
            with self.assertRaises(SchemaxisError):
                execute_guarded(operation, directory)
            fault = json.loads((Path(directory)/'native-fault.json').read_text())
            self.assertEqual(fault['code'], 'EXPECTED_TEST_FAULT')
            self.assertEqual(fault['location'], 'node.option')

    def test_material_input_kind_is_checked_before_execution(self):
        document = json.loads(Path('examples/schemaxis/blender-showcase.json').read_text())
        document['nodes'][2]['inputs']['input'] = 'paint'
        with self.assertRaises(SchemaxisError) as caught:
            blender_plan(document)
        self.assertEqual(caught.exception.fault.code, 'TYPE_MISMATCH')
