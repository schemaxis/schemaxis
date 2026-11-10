#!/usr/bin/env python3
"""Generate the current editorial assessment index; preserve dated baselines.

Use PYTHONPATH=src. --write-baseline creates a new file exclusively, so normal
regeneration cannot overwrite historical estimates. No native runtimes are used.
"""
import argparse
import json
from pathlib import Path

from schemaxis.assessments import report
from schemaxis.adaptors import registry
from schemaxis.errors import fail

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'docs/generated/adaptor-assessments.md'


def builtin_providers():
    """Select the public inventory from the existing registry, never another list."""
    return sorted(name for name, item in registry.ADAPTORS.items()
                  if item.get('source', 'builtin') == 'builtin')


def require_builtin_environment():
    plugins = sorted(set(registry.ADAPTORS) - set(builtin_providers()))
    if plugins:
        fail('PLUGIN_ADAPTORS_LOADED',
             'the public assessment index covers builtin adaptors; set '
             'SCHEMAXIS_ADAPTOR_PLUGINS=off. Use schemaxis assessments for an installed-plugin inventory.',
             'assessments', plugins=plugins)


def markdown(value):
    lines = ['# Adaptor strength assessments', '',
        'Generated from the existing registry and each adaptor’s `assessment.json`.',
        f"{value['providerCount']} registered application providers expose {value['routeCount']} authorable routes; routes are not additional applications.", '',
        'All scores are **subjective**, rounded to five percentage points. Breadth is relative to the **whole application**; abstraction is relative to the **named supported workflows**. High abstraction within a narrow slice does not imply broad application support.', '',
        'These are editorial planning estimates, not native qualification, runtime availability or measured API ratios. A `current` record matches only the declared adaptor-source fingerprint scope. Read [the rubric and limitations](../adaptor-assessments.md) before comparing scores.', '',
        '| Provider | Routes | Whole-application breadth | Supported-workflow abstraction | Estimate confidence (breadth / abstraction) | Date / status |',
        '| --- | --- | --- | --- | --- | --- |']
    for entry in value['providers']:
        item = entry['assessment']; record = item['record']
        if record:
            c, a = record['coverage'], record['abstraction']
            lines.append(f"| `{entry['id']}` | {entry['routeCount']} | {c['percent']}% | {a['percent']}% | {c['confidence']} / {a['confidence']} | {record['assessedOn']} / {item['status']} |")
        else:
            lines.append(f"| `{entry['id']}` | {entry['routeCount']} | unknown | unknown | unknown | {item['status']} |")
    lines += ['', '## Scopes and interpretation', '']
    for entry in value['providers']:
        item = entry['assessment']; record = item['record']
        lines += ['### ' + entry['id'], '']
        if not record:
            lines += ['Assessment ' + item['status'] + '; no score is inferred.', '']; continue
        lines += [record['abstraction']['scope']['description'], '',
            '**Whole-application denominator:** ' + record['coverage']['scope']['denominator'], '',
            '**Breadth rationale:** ' + record['coverage']['rationale'], '',
            '**Abstraction rationale:** ' + record['abstraction']['rationale'], '',
            '**Material limits:** ' + ' '.join(record['limitations']), '',
            '**Evidence:** ' + ', '.join('['+ref+'](../../'+ref+')' for ref in record['evidence']) + '.', '',
            f"Record version `{record['assessmentVersion']}`; rubric `{record['rubric']}`. Query: `schemaxis assessments --app {entry['id']}`.", '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--write-baseline', type=Path, help='create a new dated JSON snapshot; existing files are refused')
    args = parser.parse_args()
    if args.check and args.write_baseline:
        parser.error('--check cannot create a baseline')
    require_builtin_environment()
    # Reserve the new baseline exclusively before changing the current index.
    # An existing/accepted baseline therefore causes no output mutation at all.
    target = args.write_baseline.open('x') if args.write_baseline else None
    baseline_complete = False
    try:
        value = report()
        content = markdown(value)
        encoded = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
        if target is not None:
            target.write(encoded)
            target.flush()
            baseline_complete = True
        if args.check:
            if not OUTPUT.is_file() or OUTPUT.read_text() != content:
                raise SystemExit('Adaptor assessment index is stale; run tools/generate_adaptor_assessments.py')
        else:
            OUTPUT.write_text(content)
    finally:
        if target is not None:
            target.close()
            if not baseline_complete:
                args.write_baseline.unlink()
    print('Assessment index checked' if args.check else 'Assessment index generated')


if __name__ == '__main__':
    main()
