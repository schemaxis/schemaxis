"""Experimental presentation invariance, honest scope and pilot telemetry."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
import compact_plan_cli as cli
import compact_plan_experiment as experiment
from schemaxis.adaptors import registry
from schemaxis.capabilities import digest, response_bytes
from schemaxis.observations import at_pointer, bounded


DOCUMENT = {'version': 'schemaxis/1', 'nodes': [
    {'id': 'source', 'filter': 'wavelet'},
    {'id': 'slice', 'filter': 'slice', 'inputs': {'input': 'source'},
     'options': {'origin': {'$axis': 'cut'}, 'normal': 'z+'}}],
    'times': [0, 1], 'axes': [{'name': 'cut', 'values': [[0, 0, 0], [0, 0, 1]]}],
    'scenes': [{'id': 'sections', 'geometry': ['slice'], 'visible': {'slice': {}},
                'images': [{'id': 'image', 'size': [192, 160], 'cameras': [{'direction': [0, 0, 1], 'up': [0, 1, 0]}]}]}]}


class CompactPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = registry.plan(DOCUMENT)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def invoke(self, document, mode='compact', extra=()):
        source = self.root/'input.json'
        source.write_text(json.dumps(document))
        output = io.StringIO()
        with patch.dict(os.environ, SCHEMAXIS_PLAN_PRESENTATION=mode), contextlib.redirect_stdout(output):
            code = cli.main(['plan', str(source), '--retain', str(self.root/'retained'), *extra])
        return code, json.loads(output.getvalue())

    def test_same_plan_bytes_digest_and_ownership_are_unchanged(self):
        before = copy.deepcopy(self.plan)
        original_bytes = cli.encoded(self.plan)
        original_digest = self.plan['pipeline']['digest']
        full, full_ref = cli.present(self.plan, self.root, compact=False)
        compact, compact_ref = cli.present(self.plan, self.root)
        self.assertEqual(full, self.plan)
        self.assertEqual(full_ref, compact_ref)
        self.assertEqual(Path(compact_ref['file']).read_bytes(), original_bytes)
        self.assertEqual(self.plan, before)
        self.assertEqual(compact['existingPipelineDigest'], original_digest)
        self.assertEqual(compact, cli.present(self.plan, self.root)[0])
        compact['view']['value']['nodes'][0]['options']['Centre'] = 'client mutation'
        self.assertEqual(self.plan, before)

    def test_success_exposes_selected_work_settings_and_resolvable_pointers(self):
        result, _ = cli.present(self.plan, self.root)
        view = result['view']['value']
        self.assertEqual(view['counts']['selectedNodes'], 2)
        self.assertEqual(view['counts']['sceneStateVisits'], 4)
        self.assertEqual(view['counts']['expectedPublications'], 8)
        node = view['nodes'][1]
        self.assertEqual(node['options'], self.plan['pipeline']['nodes'][1]['options'])
        self.assertEqual(at_pointer(self.plan, node['contractPointer']), self.plan['pipeline']['declarations']['slice'])
        self.assertEqual(at_pointer(self.plan, node['canonicalPointer'])['id'], 'slice')
        self.assertEqual(result['nativeExecution'], 'not-run')
        self.assertEqual(result['outputVerification'], 'not-run')
        self.assertNotIn('verified', result)
        self.assertEqual(view['diagnosticAvailability'], 'not-reported')

    def test_large_view_is_paged_without_losing_phase_or_details(self):
        plan = copy.deepcopy(self.plan)
        plan['scenes'][0]['images'] *= 100
        result, _ = cli.present(plan, self.root, max_bytes=4096)
        self.assertLessEqual(response_bytes(result), 4096)
        self.assertEqual(result['nativeExecution'], 'not-run')
        self.assertEqual(result['view']['mode'], 'members')
        view = json.loads(Path(result['retainedView']['file']).read_text())
        self.assertEqual(view, cli.projection(plan))
        for item in result['view']['items']:
            at_pointer(view, item['pointer'])

    def test_reported_warnings_and_deferred_states_survive_bounding(self):
        plan = {'operations': [{'id': 'consumer', 'provisionalPlan': {'status': 'deferred',
                'reason': 'verified producer values required'}}], 'warnings': ['bounded diagnostic'] * 500}
        result, _ = cli.present(plan, self.root, max_bytes=4096)
        self.assertLessEqual(response_bytes(result), 4096)
        view = json.loads(Path(result['retainedView']['file']).read_text())
        diagnostics = view['reportedDiagnostics']
        self.assertEqual(diagnostics[0]['reported']['status'], 'deferred')
        self.assertEqual(diagnostics[1]['reported'], plan['warnings'])
        self.assertEqual(result['outputVerification'], 'not-run')

    def test_invalid_reference_preserves_fault_and_nonzero_exit(self):
        invalid = copy.deepcopy(DOCUMENT)
        invalid['nodes'][1]['inputs']['input'] = 'missing'
        full_code, full = self.invoke(invalid, 'full')
        code, compact = self.invoke(invalid)
        self.assertEqual((full_code, code), (1, 1))
        retained = json.loads(Path(compact['retainedFault']['file']).read_text())
        self.assertEqual(retained, full)
        self.assertEqual(compact['faultCode'], full['fault']['code'])
        self.assertEqual(compact['hostPlanning'], 'failed')
        self.assertEqual(compact['nativeExecution'], 'not-run')

    def test_native_time_inspection_requirement_is_not_a_success(self):
        document = copy.deepcopy(DOCUMENT)
        document['times'] = {'source': 'source', 'select': {'values': [0]}}
        code, result = self.invoke(document)
        self.assertEqual(code, 1)
        self.assertEqual(result['faultCode'], 'TIME_INSPECTION_REQUIRED')
        self.assertEqual(result['outputVerification'], 'not-run')

    def test_production_cli_bytes_equal_full_control(self):
        source = self.root/'input.json'; source.write_text(json.dumps(DOCUMENT))
        result = subprocess.run([sys.executable, '-m', 'schemaxis', 'plan', str(source)],
                                cwd=ROOT, capture_output=True, check=True)
        full, _ = cli.present(self.plan, self.root, compact=False)
        self.assertEqual(result.stdout, cli.encoded(full))

    def test_planner_is_called_once_and_inspection_rejects_changed_evidence(self):
        with patch.object(cli, 'plan_once', return_value=self.plan) as planner:
            code, result = self.invoke(DOCUMENT)
        self.assertEqual(code, 0)
        planner.assert_called_once()
        ref = result['retainedPlan']
        args = ['inspect', ref['file'], '--pointer', '/pipeline/nodes/1/options', '--revision', ref['observationRevision']]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(args), 0)
        self.assertEqual(json.loads(output.getvalue())['value'], self.plan['pipeline']['nodes'][1]['options'])
        Path(ref['file']).write_text('{}')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(args), 1)

    def test_no_native_import_or_launch_during_projection(self):
        with patch('subprocess.Popen', side_effect=AssertionError('native launch')):
            result, _ = cli.present(self.plan, self.root)
        self.assertEqual(result['nativeExecution'], 'not-run')
        self.assertNotIn('paraview', sys.modules)

    def test_large_failure_is_retained_and_bounded_without_success_claim(self):
        from schemaxis.core.faults import Fault, SchemaxisError
        fault = SchemaxisError(Fault('UNKNOWN_FILTER', 'undeclared operation', '$.nodes', 'input',
                                    observed={'available': ['operation-' + str(i) for i in range(10000)]}))
        with patch.object(cli, 'plan_once', side_effect=fault):
            code, result = self.invoke(DOCUMENT)
        self.assertEqual(code, 1)
        self.assertLessEqual(response_bytes(result), 8192)
        self.assertEqual(json.loads(Path(result['retainedFault']['file']).read_text()), fault.to_dict())
        self.assertEqual(result['hostPlanning'], 'failed')

    def test_malformed_json_is_a_structured_failure(self):
        source = self.root/'broken.json'; source.write_text('{')
        output = io.StringIO()
        with patch.dict(os.environ, SCHEMAXIS_PLAN_PRESENTATION='compact'), contextlib.redirect_stdout(output):
            code = cli.main(['plan', str(source), '--retain', str(self.root/'retained')])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(result['nativeExecution'], 'not-run')
        self.assertEqual(result['hostPlanning'], 'failed')


class CompactPilotTests(unittest.TestCase):
    def test_arm_onboarding_differs_only_through_environment(self):
        from run_paraview_model_pilot import authoring_start
        text = experiment.introduction(authoring_start('schemaxis'), 'schemaxis')
        self.assertIn('schema --provider paraview --authored', text)
        self.assertIn('/experiment/plan_cli.py plan', text)
        prefix = ['bwrap', '--', 'python3']
        full = experiment.prefix_environment(prefix, 'astra-full')
        compact = experiment.prefix_environment(prefix, 'astra-compact')
        self.assertEqual([s.replace('full', 'compact') for s in full], compact)
        self.assertEqual(prefix, ['bwrap', '--', 'python3'])
        self.assertEqual(experiment.ROUNDS, ('initial', 'repeat', 'revision'))

    def test_telemetry_separates_requests_tools_and_resumed_turns(self):
        events = [
            {'type': 'response_item', 'payload': {'type': 'custom_tool_call', 'call_id': 'a', 'input': 'local calls'}},
            {'type': 'response_item', 'payload': {'type': 'custom_tool_call_output', 'call_id': 'a',
                'output': [{'type': 'input_text', 'text': 'truncated response'}]}},
            {'type': 'token_usage_record', 'payload': {'response_id': 'r1', 'usage': {'input_tokens': 100}}},
            {'type': 'token_usage_record', 'payload': {'response_id': 'r1', 'usage': {'input_tokens': 100}}}]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); path = root/'session.jsonl'
            path.write_text(''.join(json.dumps(v)+'\n' for v in events))
            info = experiment.session_telemetry(path, root/'capture')
            self.assertEqual(info['recordedModelRequests'], 1)
            self.assertEqual(info['modelToolResponses'], 1)
            self.assertEqual(info['recordedToolResponseTextBytes'], len('truncated response'))
            self.assertEqual(info['usageCategories']['input_tokens'], 100)
            next_info = experiment.session_telemetry(path, root/'next', info['nextLineOffset'])
            self.assertIsNone(next_info['recordedModelRequests'])
            self.assertEqual(next_info['modelToolResponses'], 0)

    def test_cost_gate_uses_latest_conversation_totals(self):
        report = {'runs': [{'arm': 'a', 'listPriceCostUSD': 1},
                          {'arm': 'b', 'listPriceCostUSD': 2}, {'arm': 'a', 'listPriceCostUSD': 3}]}
        for run in report['runs']:
            run['accounting'] = {'complete': True}
        self.assertEqual(experiment.spent(report)['knownListPriceCostUSD'], 5)
        self.assertTrue(experiment.spent(report)['complete'])

    def test_retained_local_timings_distinguish_reuse_from_new_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); work = root/'work'; work.mkdir()
            (work/'submission.json').write_text(json.dumps({'seconds': 3, 'exitCode': 0}))
            events = work/'presentation-events.jsonl'
            events.write_text(json.dumps({'action': 'plan', 'planningSeconds': .1})+'\n')
            previous = experiment.local_evidence(work, root/'first')
            first = json.loads((root/'first/local-evidence.json').read_text())
            self.assertEqual(len(first['nativeTimingRecords']), 1)
            self.assertEqual(len(first['presentationEvents']), 1)
            experiment.local_evidence(work, root/'repeat', previous)
            repeated = json.loads((root/'repeat/local-evidence.json').read_text())
            self.assertEqual(repeated['nativeTimingRecords'], [])
            self.assertEqual(repeated['presentationEvents'], [])

    def test_stale_time_check_requires_distinct_times_and_distinct_references(self):
        import compact_plan_evaluator as evaluator
        task = {'cases': [{'id': 'a', 'times': [0, 1], 'fractions': [.5], 'cameras': [{}]}], 'appearances': [{}]}
        # A tiny numpy double keeps the host tests dependency-free.
        fake_numpy = types.SimpleNamespace(array_equal=lambda a, b: a == b)
        def pixels(path):
            return (2, 2), [1 if str(path).startswith('submission') or 'slice-0-' in path.name else 2]
        with patch.dict(sys.modules, numpy=fake_numpy), patch.object(evaluator, 'image', side_effect=pixels):
            errors = evaluator.repeated_time_images(task, Path('submission'), Path('reference'))
            self.assertEqual(len(errors), 1)
            task['cases'][0]['times'] = [0, 0]
            self.assertEqual(evaluator.repeated_time_images(task, Path('submission'), Path('reference')), [])
            task['cases'][0]['times'] = [0, 1]
            with patch.object(evaluator, 'image', return_value=((2, 2), [1])):
                self.assertEqual(evaluator.repeated_time_images(task, Path('submission'), Path('reference')), [])


if __name__ == '__main__':
    unittest.main()
