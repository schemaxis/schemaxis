"""No-inference integration checks for compact-pilot metering and durability."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
import compact_plan_evaluator as evaluator
import compact_plan_experiment as experiment
import model_pilot_codex as codex
import run_paraview_model_pilot as runner


def usage(n=1):
    return {'input_tokens': 1000*n, 'cached_input_tokens': 200*n,
            'cache_write_input_tokens': 100*n, 'output_tokens': 20*n}


def accepted():
    return {'passed': True, 'cases': [{'id': 'a', 'passed': True,
            'checks': [{'file': 'image.png'}], 'errors': []}], 'scope': 'test double'}


class CompactRobustnessTests(unittest.TestCase):
    def test_supplement_preserves_upstream_verdicts_and_diagnostics(self):
        for overall, case, duplicate, expected in (
                (False, True, False, False), (True, False, False, False),
                (True, True, True, False), (True, True, False, True)):
            with self.subTest(overall=overall, case=case, duplicate=duplicate):
                original = accepted()
                original['passed'] = overall
                original['cases'][0]['passed'] = case
                original['diagnostics'] = ['keep upstream evidence']
                failures = [{'case': 'a', 'file': 'image.png', 'error': 'duplicate'}] if duplicate else []
                with patch.object(evaluator, 'original_grade', return_value=original), patch.object(
                        evaluator, 'repeated_time_images', return_value=failures):
                    result = evaluator.grade({}, Path('actual'), Path('reference'))
                self.assertEqual(result['passed'], expected)
                self.assertEqual(result['originalPixelGradePassed'], overall)
                self.assertEqual(result['cases'][0]['originalPixelGradePassed'], case)
                self.assertEqual(result['diagnostics'], ['keep upstream evidence'])
                self.assertEqual(len(result['cases'][0]['checks']), 0 if duplicate else 1)

    def test_response_identity_is_reconciled_across_capture_boundaries(self):
        def event(identity, tokens):
            return {'type': 'token_usage_record', 'payload': {
                'response_id': identity, 'usage': {'input_tokens': tokens}}}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); path = root/'session.jsonl'
            events = [event('r1', 100)]
            path.write_text(json.dumps(events[0])+'\n')
            first = experiment.session_telemetry(path, root/'first')
            events += [event('r1', 100), event('r2', 200)]
            path.write_text(''.join(json.dumps(e)+'\n' for e in events))
            second = experiment.session_telemetry(path, root/'second', first['nextLineOffset'])
            self.assertTrue(second['complete'])
            self.assertEqual(second['duplicateUsageRecords'], 1)
            self.assertEqual(first['recordedModelRequests']+second['recordedModelRequests'], 2)
            self.assertEqual(second['usageCategories']['input_tokens'], 200)
            events.append(event('r1', 101))
            path.write_text(''.join(json.dumps(e)+'\n' for e in events))
            third = experiment.session_telemetry(path, root/'third', second['nextLineOffset'])
            self.assertFalse(third['complete'])
            self.assertEqual(third['conflictingResponseIds'][0]['responseId'], 'r1')

    def test_unsuitable_receipts_are_reported_and_collection_continues(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); work = root/'work'; work.mkdir()
            for name in ('null', 'dangling', 'invalid', 'valid'):
                (work/name).mkdir()
            (work/'null/verification.json').write_text('{"states": null}')
            (work/'dangling/verification.json').symlink_to('missing.json')
            (work/'invalid/verification.json').write_text('[]')
            (work/'valid/submission.json').write_text('{"seconds": 3}')
            (work/'valid/verification.json').write_text('{"states": [{"timings": {"native": 2}}]}')
            state = experiment.local_evidence(work, root/'first')
            evidence = json.loads((root/'first/local-evidence.json').read_text())
            self.assertFalse(evidence['complete'])
            self.assertEqual(len(evidence['errors']), 3)
            self.assertEqual(len(evidence['nativeTimingRecords']), 2)
            experiment.local_evidence(work, root/'next', state)
            self.assertEqual(len(json.loads((root/'next/local-evidence.json').read_text())['errors']), 3)

    def test_missing_cost_never_disappears_from_gate(self):
        _, first = codex.accounting(usage(), {}, 'gpt-5.6-luna')
        _, second = codex.accounting(usage(2), usage(), 'gpt-5.6-luna')
        report = {'runs': [
            {'arm': 'luna-full', 'round': 'initial', 'listPriceCostUSD': first, 'accounting': {'complete': True}},
            {'arm': 'luna-full', 'round': 'repeat', 'listPriceCostUSD': second, 'accounting': {'complete': True}},
            {'arm': 'luna-compact', 'round': 'initial', 'listPriceCostUSD': None}]}
        spending = experiment.spent(report)
        self.assertAlmostEqual(spending['knownListPriceCostUSD'], second)
        self.assertFalse(spending['complete'])
        self.assertEqual(spending['unresolvedInvocations'], [{'arm': 'luna-compact', 'round': 'initial'}])

    def test_no_retained_metering_keeps_cost_unknown(self):
        record = {'usage': {}, 'terminalReason': 'timeout', 'timedOut': True}
        with tempfile.TemporaryDirectory() as temp:
            result = experiment.account_invocation(record, {}, 'gpt-5.6-luna', Path(temp), 'missing')
        self.assertEqual(result, {})
        self.assertFalse(record['accounting']['complete'])
        self.assertIsNone(record['listPriceCostUSD'])
        self.assertEqual(record['usage'], {})


class CompactCoordinatorTests(unittest.TestCase):
    """Real run(), codex.invoke(), accounting(), capture and summarise().

    The process-capture boundary emits fake CLI/session records. Native preflight
    and native grading are doubles; no provider, sandbox or native process runs.
    """
    def smoke(self, root, failure=None, cost_limit=20, failure_turn=7):
        package = root/'package'
        for phase, task in runner.tasks(2).items():
            path = package/phase; path.mkdir(parents=True)
            (path/'task.json').write_text(json.dumps(task))
            (path/'inputs').mkdir(); (path/'reference').mkdir()
        pvroot = root/'pv'; (pvroot/'bin').mkdir(parents=True)
        (pvroot/'bin/pvbatch').write_text('native process double')
        args = SimpleNamespace(provider='codex', task_mode='authoring', compact_plan=True,
            omit_arm=[], output_directory=root/'run', package=package, replicate=2,
            claude=root/'codex', credentials=root/'auth', seconds=600, effort='high',
            budget_usd=6, pilot_cost_limit=cost_limit, stage_only=False)
        invocations, turns = [], {}

        def isolate(home, work, *unused):
            return ['fake-isolate', str(home), str(work), '--']

        def native(argv, **unused):
            work = Path(argv[2])
            if '/opt/schemaxis/experiment/plan_cli.py' in argv:
                (work/'.plan-preflight').mkdir()
            elif '/work/check_outputs.py' not in argv:
                (work/'.preflight-output').mkdir()
            return SimpleNamespace(returncode=0, stdout='{"scope": "fake native preflight"}', stderr='')

        def capture(argv, prompt, logs, seconds):
            logs.mkdir()
            arm = logs.parent.name; label = logs.name
            invocations.append((arm, label))
            turns[arm] = n = turns.get(arm, 0)+1
            model = argv[argv.index('--model')+1]
            session = arm+'-session'
            current_failure = failure if len(invocations) == failure_turn else None
            if current_failure == 'before-session':
                (logs/'transcript.jsonl').write_text(json.dumps({
                    'type': 'error', 'message': 'Provider failed before session creation'})+'\n')
                return {'exitCode': 1, 'timedOut': False, 'wallSeconds': 1,
                        'apiErrorStatus': None, 'humanInterventions': 0}
            if label != 'initial':
                self.assertIn('resume', argv)
                self.assertIn(session, argv)
            home = Path(argv[1]); retained = home/'.codex/sessions'
            retained.mkdir(parents=True, exist_ok=True)
            events = [{'type': 'turn_context', 'payload': {'model': model}}]
            if current_failure not in ('missing-metering', 'missing-telemetry'):
                events += [{'type': 'token_usage_record', 'payload': {
                    'response_id': f'{arm}-{n}', 'usage': usage(), 'thread_token_usage': usage(n)}},
                    {'type': 'event_msg', 'payload': {'type': 'token_count',
                        'info': {'last_token_usage': {'input_tokens': 1000}}}}]
            with (retained/(session+'.jsonl')).open('a') as output:
                output.write(''.join(json.dumps(e)+'\n' for e in events))
            stream = [{'type': 'thread.started', 'thread_id': session}]
            if current_failure not in ('missing-metering', 'timeout'):
                stream.append({'type': 'turn.completed', 'usage': usage(n)})
            (logs/'transcript.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in stream))
            return {'exitCode': 1 if current_failure == 'charged-failure' else -15 if current_failure in ('missing-metering', 'timeout') else 0,
                'timedOut': current_failure in ('missing-metering', 'timeout'), 'wallSeconds': 1,
                'apiErrorStatus': None, 'humanInterventions': 0}

        actual_local = experiment.local_evidence
        def local(work, directory, previous):
            if len(invocations) == 7 and failure in ('diagnostic', 'cancel'):
                saved = json.loads((args.output_directory/'report.json').read_text())
                self.assertEqual(len(saved['runs']), 7)
                self.assertTrue(saved['runs'][-1]['accounting']['complete'])
                self.assertEqual(saved['runs'][-1]['terminalReason'], 'completed')
                self.assertTrue((directory/'invocation-result.json').exists())
                self.assertTrue((directory/'normalised-result.json').exists())
                if failure == 'cancel':
                    raise KeyboardInterrupt('simulated cancellation')
                raise OSError('simulated diagnostic failure')
            return actual_local(work, directory, previous)

        with patch.object(codex, 'sandbox', side_effect=isolate), patch.object(codex, 'capture', side_effect=capture), \
                patch.object(runner.subprocess, 'check_output', return_value='fake version'), \
                patch.object(runner.subprocess, 'run', side_effect=native), \
                patch.object(experiment, 'grade', side_effect=lambda *args: accepted()), \
                patch.object(experiment, 'local_evidence', side_effect=local), contextlib.redirect_stdout(io.StringIO()):
            report = runner.run(args, pvroot)
        measured = json.loads((args.output_directory/'measurements.json').read_text())
        self.assertEqual(len(invocations), len(report['runs']))
        self.assertEqual(len(measured['rounds']), len(invocations))
        self.assertEqual(measured['status'], report['status'])
        self.assertEqual(json.loads((args.output_directory/'report.json').read_text()), json.loads(json.dumps(report)))
        return report, measured

    def test_all_six_arms_progress_with_real_accounting_and_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            report, measured = self.smoke(Path(temp))
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(len(report['runs']), 18)
        self.assertTrue(report['spending']['complete'])
        self.assertTrue(measured['observationsComplete'])
        expected_cost = 0
        for arm, total in measured['totals'].items():
            rows = [r for r in report['runs'] if r['arm'] == arm]
            self.assertEqual([r['round'] for r in rows], ['initial', 'repeat', 'revision'])
            normalised, cost = codex.accounting(usage(3), usage(2), rows[-1]['model'])
            self.assertEqual(rows[-1]['usage'], normalised)
            self.assertAlmostEqual(total['listPriceCostUSD'], cost)
            self.assertEqual(total['inputTokensIncludingCache'], 3000)
            self.assertAlmostEqual(sum(r['listPriceCostUSDThisInvocation'] for r in measured['rounds'] if r['arm'] == arm), cost)
            expected_cost += cost
        self.assertAlmostEqual(report['spending']['knownListPriceCostUSD'], expected_cost)

    def test_diagnostic_failure_and_missing_telemetry_stop_with_durable_usage(self):
        for failure in ('diagnostic', 'missing-telemetry'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                report, measured = self.smoke(Path(temp), failure)
                self.assertEqual(report['status'], 'incomplete-observation')
                self.assertEqual(len(report['runs']), 7)
                last = report['runs'][-1]
                self.assertTrue(last['accounting']['complete'])
                self.assertFalse(last['observationComplete'])
                self.assertTrue(last['diagnosticErrors'])
                self.assertTrue(last['grade']['passed'])
                self.assertFalse(measured['observationsComplete'])

    def test_missing_final_metering_stops_and_preserves_known_timeout_cost(self):
        for failure in ('missing-metering', 'timeout'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                report, measured = self.smoke(Path(temp), failure)
                self.assertEqual(report['status'], 'unresolved-accounting')
                self.assertEqual(len(report['runs']), 7)
                last = report['runs'][-1]
                self.assertTrue(last['timedOut'])
                self.assertFalse(last['accounting']['complete'])
                _, known = codex.accounting(usage(2 if failure == 'timeout' else 1), {}, last['model'])
                self.assertAlmostEqual(last['listPriceCostUSD'], known)
                self.assertFalse(measured['spending']['complete'])
                self.assertEqual(last['usage']['output_tokens'], 20 if failure == 'timeout' else 0)
                self.assertIsNone(measured['rounds'][-1]['listPriceCostUSDThisInvocation'])
                self.assertIsNone(measured['totals'][last['arm']]['listPriceCostUSD'])
                self.assertAlmostEqual(measured['totals'][last['arm']]['knownListPriceCostUSD'], known)

    def test_charged_failed_process_keeps_final_metering(self):
        with tempfile.TemporaryDirectory() as temp:
            report, measured = self.smoke(Path(temp), 'charged-failure')
        failed = report['runs'][6]
        self.assertTrue(failed['isError'])
        self.assertTrue(failed['accounting']['complete'])
        self.assertGreater(measured['rounds'][6]['listPriceCostUSDThisInvocation'], 0)
        self.assertFalse(measured['rounds'][6]['agentCompleted'])

    def test_soft_limit_stops_between_invocations(self):
        with tempfile.TemporaryDirectory() as temp:
            report, measured = self.smoke(Path(temp), cost_limit=.00001)
        self.assertEqual(report['status'], 'budget-stopped')
        self.assertEqual(len(report['runs']), 1)
        self.assertTrue(report['spending']['complete'])

    def test_failure_before_session_creation_retains_outcome_and_stops(self):
        with tempfile.TemporaryDirectory() as temp:
            report, measured = self.smoke(Path(temp), 'before-session', failure_turn=1)
        self.assertEqual(report['status'], 'unresolved-accounting')
        self.assertEqual(len(report['runs']), 1)
        failed = report['runs'][0]
        self.assertIsNone(failed['sessionId'])
        self.assertEqual(failed['terminalReason'], 'api_error')
        self.assertIn('Provider failed before session creation', failed['providerMessage'])
        self.assertFalse(failed['accounting']['complete'])
        self.assertIsNone(failed['listPriceCostUSD'])
        self.assertFalse(failed['observationComplete'])
        self.assertEqual(failed['grade']['status'], 'not-scored-provider-failure')
        self.assertFalse(measured['spending']['complete'])

    def test_cancellation_propagates_with_invocation_checkpoint_intact(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(KeyboardInterrupt):
                self.smoke(root, 'cancel')
            report = json.loads((root/'run/report.json').read_text())
            self.assertEqual(len(report['runs']), 7)
            self.assertTrue(report['runs'][-1]['accounting']['complete'])
            self.assertEqual(report['runs'][-1]['grade']['status'], 'pending')


if __name__ == '__main__':
    unittest.main()
