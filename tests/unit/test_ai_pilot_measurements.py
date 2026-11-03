# Copyright (C) 2026 David L F Gaden
"""Keep resumed-conversation cost and per-invocation tokens distinct."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'tools'))
from summarise_ai_pilot import summarise


class PilotMeasurementTests(unittest.TestCase):
    def test_api_error_retained_despite_success_subtype(self):
        from run_rlc_ai_pilot import invoke
        event = {'type': 'result', 'subtype': 'success', 'is_error': True,
                 'terminal_reason': 'api_error', 'api_error_status': 429,
                 'result': 'provider limit', 'usage': {}, 'modelUsage': {}}
        with tempfile.TemporaryDirectory() as temp:
            result = invoke([sys.executable, '-c', 'print('+repr(json.dumps(event))+')'],
                            'fixture', Path(temp)/'logs', 5)
            self.assertEqual(result['apiErrorStatus'], 429)
            self.assertEqual(result['terminalReason'], 'api_error')
            self.assertTrue(result['isError'])
            self.assertEqual(result['toolCalls'], 0)

    def test_runtime_config_accepted_by_real_loader(self):
        from run_rlc_ai_pilot import runtime_configuration
        from schemaxis.configuration import load
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'runtime.json'
            path.write_text(json.dumps(runtime_configuration()))
            self.assertEqual(load(path)['locations']['ngspice'], '/opt/ngspice/bin/ngspice')

    def report(self):
        run = {'arm': 'ordinary', 'round': 'initial', 'wallSeconds': 2,
               'listPriceCostUSD': .3, 'usage': {'input_tokens': 2,
                   'cache_creation_input_tokens': 3, 'cache_read_input_tokens': 5, 'output_tokens': 7},
               'grade': {'passed': True, 'cases': [{'passed': True}, {'passed': True}]},
               'toolCalls': 4, 'toolErrors': 0, 'timedOut': False, 'humanInterventions': 0,
               'resultType': 'success', 'isError': False}
        repeat = copy.deepcopy(run)
        repeat.update(round='repeat', listPriceCostUSD=.4)
        return {'model': 'fixture', 'effort': 'high', 'replicates': 1,
                'status': 'complete', 'runs': [run, repeat]}

    def test_cost_cumulative_tokens_per_invocation(self):
        result = summarise(self.report(), 'available')
        self.assertAlmostEqual(result['rounds'][1]['listPriceCostUSDThisInvocation'], .1)
        total = result['totals']['ordinary']
        self.assertEqual(total['listPriceCostUSD'], .4)
        self.assertEqual(total['inputTokensIncludingCache'], 20)
        self.assertEqual(total['outputTokens'], 14)
        self.assertEqual(total['casesPassed'], 4)

    def test_unknown_usage_stays_unknown(self):
        report = self.report(); report['runs'][1]['usage'] = None
        self.assertIsNone(summarise(report)['totals']['ordinary']['outputTokens'])
        self.assertIsNone(summarise(report)['totals']['ordinary']['inputTokensIncludingCache'])

    def test_decreased_cumulative_cost_requires_review(self):
        report = self.report(); report['runs'][1]['listPriceCostUSD'] = .1
        with self.assertRaises(ValueError):
            summarise(report)


if __name__ == '__main__':
    unittest.main()
