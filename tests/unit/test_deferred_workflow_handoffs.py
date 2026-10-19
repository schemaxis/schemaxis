"""Future verified publications must not masquerade as host filesystem paths."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from schemaxis import parallel, workflow
from schemaxis.adaptors import registry
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError


def artifact_workflow():
    return {'version': 'schemaxis.workflow/1',
            'execution': {'maxWorkers': 1, 'cpus': 4, 'memoryMB': 2048, 'gpus': 0},
            'operations': [
                {'id': 'design', 'document': {
                    'version': 'schemaxis.freecad/1', 'units': 'mm',
                    'nodes': [{'id': 'box', 'filter': 'box',
                               'options': {'length': 20, 'width': 10, 'height': 5}}],
                    'output': 'box'}},
                {'id': 'mesh', 'document': {
                    'version': 'schemaxis.gmsh/1', 'units': 'mm',
                    'nodes': [
                        {'id': 'solid', 'filter': 'readSTEP',
                         'options': {'file': {'$artifact': 'design', 'index': 0}}},
                        {'id': 'mesh', 'filter': 'tetrahedral', 'inputs': {'input': 'solid'},
                         'options': {'size': 2}}],
                    'output': 'mesh'}}]}


def fixture_receipt(directory, expected):
    directory = Path(directory)
    if json.loads((directory/'authored.json').read_text()) != expected:
        raise AssertionError('fixture input differs')
    return json.loads((directory/'verification.json').read_text())


def fixture_run(document, directory, *args, suffix='.step', kind='cad'):
    directory.mkdir()
    atomic_json(directory/'authored.json', document)
    # The real retained-input hook replays this input-free CAD producer's plan.
    # Keep that check active even though native execution and receipts are fixtures.
    atomic_json(directory/'plan.json', registry.plan(document))
    artifact = directory/('result' + suffix)
    artifact.write_text('fixture publication; no native execution')
    atomic_json(directory/'verification.json', {'artifacts': [{'file': str(artifact), 'kind': kind}]})
    return {'verified': True}


class DeferredHandoffTests(unittest.TestCase):
    def test_artifact_only_plan_is_explicitly_deferred_without_native_import_or_launch(self):
        document = artifact_workflow()
        original = copy.deepcopy(document)
        native_before = {name for name in sys.modules
                         if name.split('.')[0] in ('paraview', 'FreeCAD', 'gmsh', 'bpy')}
        def concrete_only(value):
            self.assertFalse(list(workflow.dependencies(value)))
            return copy.deepcopy(value)
        with patch('subprocess.Popen', side_effect=AssertionError('native launch prohibited')), \
                patch('schemaxis.parallel.provisional', side_effect=concrete_only), \
                patch('schemaxis.adaptors.gmsh.adaptor.resources',
                      side_effect=AssertionError('unresolved resource hook prohibited')):
            prepared = workflow.inspect_plan(document)
            jobs = parallel.work_items(document)[2]
        deferred = prepared['operations'][1]['provisionalPlan']
        self.assertEqual(deferred['status'], 'deferred')
        self.assertEqual(deferred['references'], [{'$artifact': 'design', 'index': 0}])
        self.assertIn('adaptor input and resource validation deferred', deferred['validation'])
        self.assertNotIn('/unresolved-artifact', json.dumps(prepared))
        self.assertEqual([job['dependencies'] for job in jobs], [[], ['design']])
        self.assertEqual(document, original)
        self.assertEqual({name for name in sys.modules
                          if name.split('.')[0] in ('paraview', 'FreeCAD', 'gmsh', 'bpy')}, native_before)

    def test_reference_structure_and_order_remain_checked(self):
        for reference, code in (
                ({'$artifact': 'later', 'index': 0}, 'UNAVAILABLE_OPERATION'),
                ({'$artifact': 'design'}, 'INVALID_SELECTION'),
                ({'$artifact': 'design', 'index': -1}, 'INVALID_SELECTION'),
                ({'$artifact': 'design', 'index': True}, 'INVALID_SELECTION'),
                ({'$artifact': 'design', 'index': 0, 'file': 'guess.step'}, 'UNKNOWN_ARGUMENT')):
            for check in (workflow.inspect_plan, parallel.work_items):
                with self.subTest(reference=reference, check=check.__name__):
                    document = artifact_workflow()
                    document['operations'][1]['document']['nodes'][0]['options']['file'] = reference
                    with self.assertRaises(SchemaxisError) as caught:
                        check(document)
                    self.assertEqual(caught.exception.fault.code, code)

    def test_independent_invalid_document_is_not_hidden_by_another_deferred_operation(self):
        document = artifact_workflow()
        invalid = copy.deepcopy(document['operations'][0])
        invalid['id'] = 'invalid'
        invalid['document']['output'] = 'missing'
        document['operations'].append(invalid)
        with self.assertRaises(SchemaxisError):
            workflow.inspect_plan(document)

    def test_declared_resource_limits_are_checked_while_inputs_are_deferred(self):
        for spec, code in (({'memoryMB': 4096}, 'RESOURCE_BUDGET_EXCEEDED'),
                           ({'threads': True}, 'INVALID_EXECUTION'),
                           ({'ranks': 2, 'mpiexec': '/mpi'}, 'UNSUPPORTED_EXECUTION')):
            with self.subTest(spec=spec):
                document = artifact_workflow()
                document['operations'][1]['execution'] = spec
                with self.assertRaises(SchemaxisError) as caught:
                    workflow.inspect_plan(document)
                self.assertEqual(caught.exception.fault.code, code)

    def execute_fixture(self, document, directory, runner=fixture_run):
        with patch('schemaxis.parallel.run_native', side_effect=runner) as dispatch, \
                patch('schemaxis.parallel.verify_native', side_effect=fixture_receipt), \
                patch('schemaxis.parallel.reusable_inputs', return_value={}):
            return parallel.execute(document, directory), dispatch.call_args_list

    def test_resolved_artifact_runs_real_host_validation_with_actual_path(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(registry, 'plan', wraps=registry.plan) as planner:
            result, dispatched = self.execute_fixture(artifact_workflow(), Path(temp)/'run')
        self.assertTrue(result['verified'])
        self.assertEqual(len(dispatched), 2)
        consumer = dispatched[1].args[0]
        self.assertTrue(consumer['nodes'][0]['options']['file'].endswith('/result.step'))
        self.assertNotIn('/unresolved-artifact', repr(planner.call_args_list))
        self.assertTrue(any(call.args[0] == consumer for call in planner.call_args_list))

    def test_invalid_resolved_inputs_or_resource_hook_never_dispatch_consumer(self):
        for fault, spec, suffix, kind in (
                ('INVALID_EXECUTION', {'threads': 2}, '.step', 'cad'),
                ('INVALID_RESOURCE', {}, '.txt', 'cad'),
                ('TYPE_MISMATCH', {}, '.step', 'image')):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temp:
                document = artifact_workflow()
                document['operations'][1]['execution'] = spec
                def producer(value, directory, *args):
                    return fixture_run(value, directory, suffix=suffix, kind=kind)
                with patch('schemaxis.parallel.run_native', side_effect=producer) as dispatch, \
                        patch('schemaxis.parallel.verify_native', side_effect=fixture_receipt), \
                        patch('schemaxis.parallel.reusable_inputs', return_value={}):
                    with self.assertRaises(SchemaxisError) as caught:
                        parallel.execute(document, Path(temp)/'run')
                    self.assertEqual(caught.exception.fault.code, fault)
                    self.assertEqual(dispatch.call_count, 1)

    def test_batched_dependent_input_cannot_evade_whole_operation_limits(self):
        document = artifact_workflow()
        document['operations'][1] = {'id': 'view', 'execution': {'timeChunkSize': 1}, 'document': {
            'version': 'schemaxis/1', 'times': [0, 1, 2], 'maxPublications': 2,
            'nodes': [{'id': 'mesh', 'filter': 'readSurface',
                       'options': {'files': [{'$artifact': 'design', 'index': 0}]}}],
            'scenes': [{'id': 'view', 'geometry': ['mesh']}]}}
        self.assertEqual(len(parallel.work_items(document)[2]), 4)
        with tempfile.TemporaryDirectory() as temp, \
                patch('schemaxis.parallel.run_native',
                      side_effect=lambda value, target, *args: fixture_run(value, target, suffix='.vtp', kind='geometry')) as dispatch, \
                patch('schemaxis.parallel.verify_native', side_effect=fixture_receipt), \
                patch('schemaxis.parallel.reusable_inputs', return_value={}):
            with self.assertRaises(SchemaxisError) as caught:
                parallel.execute(document, Path(temp)/'run')
            self.assertEqual(caught.exception.fault.code, 'EXPANSION_TOO_LARGE')
            self.assertEqual(dispatch.call_count, 1)


if __name__ == '__main__':
    unittest.main()
