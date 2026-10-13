#!/usr/bin/env python3
"""Aggregate independent conversations without treating artifacts as replicates."""
import argparse
import json
from pathlib import Path
import statistics

from summarise_ai_pilot import summarise


def aggregate(paths):
    cells = {}; reports = []; excluded = []; excluded_reports = []
    for path in paths:
        report = json.loads(path.read_text())
        if str(report.get('status', '')).startswith('excluded'):
            excluded_reports.append({'path': str(path.resolve()), 'status': report['status'],
                                     'retainedInvocations': len(report.get('runs', []))})
            continue
        eligible = [r for r in report['runs'] if r.get('eligibleForModelComparison', True)]
        excluded.extend({'report': str(path.resolve()), 'arm': r['arm'], 'round': r['round'],
                         'reason': r.get('exclusionReason'), 'seconds': r['wallSeconds'],
                         'cumulativeCostUSD': r.get('listPriceCostUSD')}
                        for r in report['runs'] if not r.get('eligibleForModelComparison', True))
        measured = summarise({**report, 'runs': eligible})
        reports.append({'path': str(path.resolve()), 'status': report['status'],
                        'provider': report.get('provider', 'claude'),
                        'replicate': report['replicate'], 'taskMode': report.get('taskMode', 'recipe')})
        for arm, total in measured['totals'].items():
            runs = [r for r in eligible if r['arm'] == arm]
            expected = 2 if report.get('taskMode') == 'authoring' else 4
            row = {'report': str(path.resolve()), 'replicate': report['replicate'], **total,
                   'turns': len(runs), 'expectedTurns': expected,
                   'completeArtifactPass': len(runs) == expected and all(r['grade']['passed'] is True for r in runs),
                   'completeAgentPass': len(runs) == expected and all(r['isError'] is False and not r['timedOut'] for r in runs),
                   'artifactChecks': sum(len(c['checks'])+len(c['errors']) for r in runs for c in r['grade']['cases']),
                   'artifactChecksPassed': sum(len(c['checks']) for r in runs for c in r['grade']['cases']),
                   'preparationSeconds': sum(p['seconds'] for p in report.get('preflights', []) if p['arm'] == arm)}
            key = report.get('taskMode', 'recipe')+'/'+arm
            cell = cells.setdefault(key, {'model': report['conditions'][arm]['model'],
                                          'method': report['conditions'][arm]['method'], 'conversations': []})
            cell['conversations'].append(row)
    for cell in cells.values():
        rows = cell['conversations']; cell['replicates'] = len(rows)
        cell['completeArtifactPasses'] = sum(r['completeArtifactPass'] for r in rows)
        cell['completeAgentPasses'] = sum(r['completeAgentPass'] for r in rows)
        for field in ('wallSeconds', 'listPriceCostUSD', 'inputTokensIncludingCache', 'outputTokens'):
            values = [r[field] for r in rows]
            cell[field] = ({'median': statistics.median(values), 'min': min(values), 'max': max(values), 'sum': sum(values)}
                           if all(v is not None for v in values) else None)
    return {'reports': reports, 'cells': cells, 'excludedInvocations': excluded,
            'excludedReports': excluded_reports,
            'scope': 'Small matched experiment; not a statistical equivalence test. Costs are API list-price estimates, not subscription billing.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reports', type=Path, nargs='+'); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); result = aggregate(args.reports)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    for name, cell in result['cells'].items():
        print(name, cell['completeArtifactPasses'], '/', cell['replicates'],
              cell['wallSeconds'], cell['listPriceCostUSD'])


if __name__ == '__main__':
    main()
