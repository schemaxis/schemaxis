#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Summarise pilot measurements without double-counting resumed-session cost.

Claude result.usage covers the invocation; result.modelUsage and total_cost_usd
are cumulative across the resumed conversation in the tested CLI. Retain the raw
report/transcripts. Listed costs are provider list-price estimates, not billing.
Method compliance (actually using Schemaxis) still needs transcript review.
"""
import argparse
import json
from pathlib import Path


def summarise(report, mode=None):
    previous_cost = {}
    totals = {}
    rows = []
    for run in report['runs']:
        arm = run['arm']
        usage = run.get('usage') or {}
        cost = run.get('listPriceCostUSD')
        previous = previous_cost.get(arm, 0)
        if cost is not None and cost+1e-9 < previous:
            raise ValueError('cumulative cost decreased; inspect session accounting before comparing')
        delta = cost-previous if cost is not None else None
        if cost is not None:
            previous_cost[arm] = cost
        input_tokens = (sum(usage[k] for k in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'))
                        if all(k in usage for k in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')) else None)
        row = {'arm': arm, 'round': run['round'], 'artifactGradePassed': run['grade']['passed'],
               'casesPassed': sum(c['passed'] for c in run['grade']['cases']),
               'cases': len(run['grade']['cases']), 'wallSeconds': run['wallSeconds'],
               'inputTokensIncludingCache': input_tokens, 'outputTokens': usage.get('output_tokens'),
               'listPriceCostUSDThisInvocation': delta, 'toolCalls': run['toolCalls'],
               'toolErrors': run['toolErrors'], 'timedOut': run['timedOut'],
               'agentCompleted': run.get('resultType') == 'success' and run.get('isError') is False,
               'humanInterventions': run['humanInterventions']}
        rows.append(row)
        total = totals.setdefault(arm, {'wallSeconds': 0, 'inputTokensIncludingCache': 0,
            'outputTokens': 0, 'toolCalls': 0, 'toolErrors': 0, 'casesPassed': 0,
            'cases': 0, 'humanInterventions': 0, 'listPriceCostUSD': None})
        for key in ('wallSeconds', 'inputTokensIncludingCache', 'outputTokens', 'toolCalls',
                    'toolErrors', 'casesPassed', 'cases', 'humanInterventions'):
            total[key] = total[key]+row[key] if total[key] is not None and row[key] is not None else None
        total['listPriceCostUSD'] = cost
    return {'kind': 'autonomous-pilot-measurements', 'schemaxisMode': mode or report.get('schemaxisMode', 'unknown'),
            'model': report['model'], 'effort': report['effort'], 'replicates': report['replicates'],
            'status': report['status'], 'rounds': rows, 'totals': totals,
            'scope': 'One exploratory pair per condition; costs are list-price estimates; method compliance requires transcript review.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--mode', choices=('available', 'required'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = summarise(json.loads(args.report.read_text()), args.mode)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result['totals'], indent=2))


if __name__ == '__main__':
    main()
