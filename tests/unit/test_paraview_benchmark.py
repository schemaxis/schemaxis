# Copyright (C) 2026 David L F Gaden
"""Portable benchmark plans, task isolation and recoverable fault injection."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from run_paraview_ai_pilot import SANDBOX_HOME, tasks, damage, sandbox, runtime_configuration


class ParaViewBenchmarkTests(unittest.TestCase):
    def test_recipe_expansion_covers_every_requested_publication(self):
        from schemaxis.adaptors.paraview.job import plan
        spec=importlib.util.spec_from_file_location('pv_recipe',ROOT/'examples/benchmarks/paraview/schemaxis_recipe.py')
        recipe=importlib.util.module_from_spec(spec); spec.loader.exec_module(recipe)
        for phase,task in tasks().items():
            before=copy.deepcopy(task)
            for case in task['cases']:
                with self.subTest(phase=phase,case=case['id']):
                    master,scenes,prepared=plan(recipe.document(task,case))
                    expected=len(case['times'])*len(case['fractions'])*(1+len(task['appearances'])*len(case['cameras']))
                    self.assertEqual(prepared['expectedPublications'],expected)
                    self.assertEqual(len(list(master.select(['slice']).visits())),len(case['times'])*len(case['fractions']))
            self.assertEqual(task,before)

    def test_revision_changes_axis_times_range_and_adds_case(self):
        spec=tasks(); a,b=spec['initial'],spec['revision']
        self.assertNotEqual(a['cases'][0]['sliceAxis'],b['cases'][0]['sliceAxis'])
        self.assertNotEqual(a['cases'][0]['times'],b['cases'][0]['times'])
        self.assertEqual(a['cases'][1],b['cases'][1])
        self.assertEqual(len(b['cases']),len(a['cases'])+1)
        self.assertNotEqual(a['appearances'][0]['range'],b['appearances'][0]['range'])

    def test_fault_injection_changes_only_requested_publications(self):
        with tempfile.TemporaryDirectory() as temp:
            work=Path(temp)
            a=work/'submission/field-a'; b=work/'submission/field-b'
            a.mkdir(parents=True); b.mkdir()
            (a/'slice-0-0.vtp').write_text('geometry')
            (a/'retain.log').write_text('evidence')
            target=b/'slice-0-0-appearance-0-camera-0.png'
            target.write_text('correct')
            (b/'slice-0-0-appearance-1-camera-1.png').write_text('wrong')
            changes=damage(work)
            self.assertEqual(len(changes),2)
            self.assertFalse((a/'slice-0-0.vtp').exists())
            self.assertEqual(target.read_text(),'wrong')
            self.assertEqual((a/'retain.log').read_text(),'evidence')

    def test_sandbox_inputs_readonly_and_product_only_when_supplied(self):
        args=sandbox('/isolated/home','/isolated/work','/inputs','/pv','/claude','/credential')
        i=args.index('/inputs'); self.assertEqual(args[i-1:i+2],['--ro-bind','/inputs','/work/inputs'])
        i=args.index('/isolated/home'); self.assertEqual(args[i-1:i+2],['--bind','/isolated/home',SANDBOX_HOME])
        self.assertEqual(args[args.index('HOME')+1],SANDBOX_HOME)
        self.assertNotIn('/opt/schemaxis',args)
        args=sandbox('/isolated/home','/isolated/work','/inputs','/pv','/claude','/credential','/product')
        self.assertIn('/opt/schemaxis',args)
        from schemaxis.configuration import load
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'config.json'; path.write_text(json.dumps(runtime_configuration()))
            self.assertEqual(load(path)['locations']['roots'],['/opt/paraview'])

    def test_onboarding_never_advertises_failed_qualification(self):
        from run_paraview_onboarding_pilot import introduction
        for method in ('native', 'schemaxis'):
            with self.assertRaises(ValueError):
                introduction(method, 'brief', {'passed': False})
            brief = introduction(method, 'brief', {'passed': True, 'artifactChecks': 40})
            self.assertIn('initial inputs and runtime', brief)
            self.assertIn('taskFileSHA256 and recipeSHA256', brief)
            self.assertIn('do not compare it', brief)
            self.assertNotIn('/work/check_outputs.py', brief)
            checked = introduction(method, 'checked', {'passed': True, 'artifactChecks': 40})
            self.assertIn('DOES NOT independently certify image camera', checked)
            self.assertIn('--baseline /work/checked.json', checked)

    def test_public_checker_rejects_changed_task_inputs_and_publications(self):
        spec = importlib.util.spec_from_file_location('pv_checker', ROOT/'examples/benchmarks/paraview/check_outputs.py')
        checker = importlib.util.module_from_spec(spec); spec.loader.exec_module(checker)
        task = {'times': [0, 1]}; files = {'a.png': 'aaa', 'b.vtp': 'bbb'}
        saved = {'taskDigest': checker.digest(task), 'inputDigest': 'inputs', 'files': files}
        self.assertEqual(checker.check_baseline(saved, task, 'inputs', files), [])
        self.assertTrue(checker.check_baseline(saved, {'times': [0, 2]}, 'inputs', files))
        self.assertTrue(checker.check_baseline(saved, task, 'changed', files))
        self.assertTrue(checker.check_baseline(saved, task, 'inputs', {'a.png': 'wrong', 'b.vtp': 'bbb'}))
        self.assertTrue(checker.check_baseline(saved, task, 'inputs', {'a.png': 'aaa'}))

    def test_onboarding_uses_fresh_parameters_and_balances_pair_order(self):
        from run_paraview_onboarding_pilot import tasks as fresh_tasks, ORDERS
        fresh = fresh_tasks()
        self.assertNotEqual(fresh['initial'], tasks()['initial'])
        self.assertEqual(len(fresh['revision']['cases']), 3)
        for condition in ('baseline', 'brief', 'checked'):
            native_first = sum(order.index('native-'+condition) < order.index('schemaxis-'+condition) for order in ORDERS)
            self.assertEqual(native_first, 2)

    def test_model_matrix_counterbalances_every_cell_and_uses_distinct_variants(self):
        from collections import Counter
        from run_paraview_model_pilot import ARMS, orders, tasks as variants
        positions = {arm: Counter() for arm in ARMS}
        for replicate in (1, 2, 3):
            sequence = orders(replicate)
            for order in sequence:
                self.assertEqual(set(order), set(ARMS))
                for index, arm in enumerate(order):
                    positions[arm][index] += 1
            for model in ('haiku', 'sonnet', 'opus'):
                self.assertEqual(sum(o.index(model+'-native') < o.index(model+'-schemaxis')
                                     for o in sequence), 2)
        self.assertTrue(all(set(counts.values()) == {2} for counts in positions.values()))
        self.assertEqual(len({json.dumps(variants(i), sort_keys=True) for i in (1, 2, 3)}), 3)

    def test_trust_instruction_keeps_checker_limits_and_failure_investigation(self):
        from run_paraview_model_pilot import introduction
        for method in ('native', 'schemaxis'):
            text = introduction(method, 'trusted', {'passed': True, 'artifactChecks': 40})
            self.assertIn('Do not audit their implementation', text)
            self.assertIn('when execution fails', text)
            self.assertIn('DOES NOT independently certify image camera', text)
            self.assertIn('--baseline /work/checked.json', text)

    def test_codex_resumed_usage_is_differenced_with_cache_pricing(self):
        from model_pilot_codex import accounting
        first = {'input_tokens': 1000, 'cached_input_tokens': 200,
                 'cache_write_input_tokens': 100, 'output_tokens': 20}
        resumed = {'input_tokens': 1600, 'cached_input_tokens': 500,
                   'cache_write_input_tokens': 150, 'output_tokens': 30}
        initial_usage, initial_cost = accounting(first, {}, 'gpt-5.6-luna')
        usage, cost = accounting(resumed, first, 'gpt-5.6-luna')
        self.assertEqual(usage, {'input_tokens': 250, 'cache_read_input_tokens': 300,
                                'cache_creation_input_tokens': 50, 'output_tokens': 10})
        self.assertAlmostEqual(cost-initial_cost, (250*.2+300*.02+50*.25+10*1.2)/1e6)
        with self.assertRaises(ValueError):
            accounting(first, resumed, 'gpt-5.6-luna')
        with self.assertRaises(ValueError):
            accounting({'input_tokens': 0}, {}, 'gpt-5.6-luna')

    def test_codex_isolation_mounts_only_its_auth_and_preserves_readonly_inputs(self):
        from model_pilot_codex import sandbox as codex_sandbox, command
        args = codex_sandbox('/isolated/home', '/isolated/work', '/inputs', '/pv', '/codex', '/auth')
        self.assertIn(SANDBOX_HOME + '/.codex/auth.json', args)
        self.assertIn('/opt/codex-code-mode-host', args)
        self.assertNotIn(SANDBOX_HOME + '/.claude/.credentials.json', args)
        self.assertNotIn('/opt/schemaxis', args)
        i = args.index('/inputs')
        self.assertEqual(args[i-1:i+2], ['--ro-bind', '/inputs', '/work/inputs'])
        initial = command('gpt-5.6-luna')
        resumed = command('gpt-5.6-luna', session='saved-session')
        self.assertNotIn('resume', initial)
        self.assertIn('saved-session', resumed)
        self.assertIn('--ignore-user-config', initial)

    def test_codex_timeout_retains_session_even_with_truncated_transport(self):
        from unittest.mock import patch
        from model_pilot_codex import invoke
        with tempfile.TemporaryDirectory() as temp:
            logs = Path(temp)
            (logs/'transcript.jsonl').write_text(
                '{"type":"thread.started","thread_id":"kept-session"}\n{"type":')
            with patch('model_pilot_codex.capture', return_value={'exitCode': -15, 'timedOut': True}):
                result = invoke([], 'task', logs, 1)
        self.assertEqual(result['sessionId'], 'kept-session')
        self.assertEqual(result['terminalReason'], 'timeout')
        self.assertTrue(result['isError'])

    def test_codex_missing_tool_host_is_infrastructure_failure_despite_final_reply(self):
        from unittest.mock import patch
        from model_pilot_codex import invoke
        with tempfile.TemporaryDirectory() as temp:
            logs = Path(temp)
            events = [
                {'type': 'thread.started', 'thread_id': 'session'},
                {'type': 'item.completed', 'item': {'type': 'error', 'message': '/opt/codex-code-mode-host is missing'}},
                {'type': 'turn.completed', 'usage': {}}]
            (logs/'transcript.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
            with patch('model_pilot_codex.capture', return_value={'exitCode': 0, 'timedOut': False}):
                result = invoke([], 'task', logs, 1)
        self.assertEqual(result['terminalReason'], 'infrastructure_error')
        self.assertTrue(result['isError'])

    def test_aggregation_excludes_model_substitution_but_keeps_artifact_failure(self):
        from summarise_model_pilots import aggregate
        failure = {'arm': 'haiku-native', 'round': 'initial', 'wallSeconds': 2,
                   'grade': {'passed': False, 'cases': [{'passed': False, 'checks': [],
                                                       'errors': [{'file': 'missing.png'}]}]},
                   'usage': {'input_tokens': 1, 'cache_creation_input_tokens': 0,
                             'cache_read_input_tokens': 0, 'output_tokens': 1},
                   'listPriceCostUSD': .1, 'toolCalls': 1, 'toolErrors': 0, 'timedOut': False,
                   'resultType': 'success', 'isError': False, 'humanInterventions': 0}
        substituted = {**failure, 'arm': 'opus-native', 'eligibleForModelComparison': False,
                       'exclusionReason': 'provider model substitution', 'listPriceCostUSD': .8,
                       'grade': {'passed': None, 'cases': []}}
        report = {'model': 'matrix', 'effort': 'high', 'replicates': 1, 'replicate': 1,
                  'status': 'complete', 'taskMode': 'authoring', 'runs': [substituted, failure],
                  'conditions': {'haiku-native': {'model': 'haiku', 'method': 'native'}}}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'report.json'; path.write_text(json.dumps(report))
            result = aggregate([path])
        self.assertNotIn('authoring/opus-native', result['cells'])
        cell = result['cells']['authoring/haiku-native']
        self.assertEqual(cell['completeArtifactPasses'], 0)
        self.assertEqual(cell['conversations'][0]['artifactChecks'], 1)
        self.assertEqual(len(result['excludedInvocations']), 1)

    def test_aggregation_excludes_whole_adjudicated_experiment(self):
        from summarise_model_pilots import aggregate
        with tempfile.TemporaryDirectory() as temp:
            paths = []
            for i, status in enumerate(('excluded', 'excluded-model-substitution')):
                path = Path(temp)/f'report-{i}.json'
                # Older excluded reports need not have per-invocation eligibility flags.
                path.write_text(json.dumps({'status': status, 'runs': [{'arm': 'opus-native'}]}))
                paths.append(path)
            result = aggregate(paths)
        self.assertEqual(result['cells'], {})
        self.assertEqual(result['reports'], [])
        self.assertEqual(len(result['excludedReports']), 2)
        self.assertEqual(sum(r['retainedInvocations'] for r in result['excludedReports']), 2)
