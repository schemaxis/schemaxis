#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Bounded native acceptance for the KiCad board adaptor.

Runs the original fixtures through an actual kicad-cli, compares results with
literal expectations derived from the declared fixture geometry, requires the
clearance and open-net fixtures to fail with DRC_VIOLATIONS, and probes
tampering, source immutability and shared CLI parity. Nothing here is a skip:
an unavailable runtime fails.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))

from schemaxis.adaptors.kicad import adaptor  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402

FIXTURES = ROOT/'examples/schemaxis/fixtures/kicad'
GATES = {'maximumErrors': 0, 'maximumWarnings': 0, 'maximumUnconnected': 0}
# (x, y) board millimetres, diameter, plated: from the declared fixture coordinates.
BASELINE_HOLES = [(3.5, 3.5, 3.2, False), (26.5, 16.5, 3.2, False), (8, 10, 1.0, True), (10.54, 10, 1.0, True),
                  (8, 6, 0.3, True), (19.05, 6, 0.3, True)]
VARIANT_HOLES = [(3.5, 3.5, 3.2, False), (36.5, 3.5, 3.2, False), (36.5, 21.5, 2.2, False), (8, 12.5, 1.0, True),
                 (5.46, 12.5, 1.0, True), (2.92, 12.5, 1.0, True), (8, 8, 0.4, True), (24.05, 8, 0.4, True),
                 (22, 18, 0.4, True)]
CASES = [
    {'id': 'baseline-inspect', 'board': 'tiny-board', 'document': {'operation': 'inspectBoard'},
     'expect': {'/board/counts/footprints': 4, '/board/counts/holes': 6, '/board/counts/pads/throughHole': 2,
                '/board/counts/pads/smd': 2, '/board/counts/pads/npth': 2, '/board/counts/vias/through': 2,
                '/board/outline/width_mm': 30, '/board/outline/height_mm': 20, '/board/minimumTrackClearance_mm': 1.65,
                '/board/minimumTrackWidth_mm': 0.25, '/board/minimumDrill_mm': 0.3, '/statistics/drillTable': True}},
    {'id': 'baseline-drc', 'board': 'tiny-board', 'document': {'operation': 'designRuleCheck', **GATES},
     'expect': {'/drc/errors': 0, '/drc/warnings': 0, '/drc/unconnected': 0, '/drc/crossCheck/clearance': 'confirmed',
                '/drc/crossCheck/unconnected': 'confirmed', '/drc/assessment/accepted': True}},
    {'id': 'baseline-drill', 'board': 'tiny-board',
     'document': {'operation': 'drillExport', **GATES, 'units': 'mm', 'separatePlating': True}, 'holes': BASELINE_HOLES,
     'expect': {'/drill/holes': 6, '/drill/plated': 4, '/drill/nonPlated': 2, '/drill/files': ['board-PTH.drl', 'board-NPTH.drl']}},
    {'id': 'variant-drill', 'board': 'tiny-variant',
     'document': {'operation': 'drillExport', **GATES, 'units': 'in', 'separatePlating': False}, 'holes': VARIANT_HOLES,
     'expect': {'/drill/holes': 9, '/drill/plated': 6, '/drill/nonPlated': 3, '/drill/files': ['board.drl'],
                '/board/outline/width_mm': 40, '/board/outline/height_mm': 25, '/board/counts/footprints': 6,
                '/board/minimumTrackClearance_mm': 1.55, '/board/thickness_mm': 1.2, '/drc/crossCheck/unconnected': 'confirmed'}},
    {'id': 'clearance-violation', 'board': 'tiny-clearance', 'document': {'operation': 'designRuleCheck', **GATES},
     'fault': 'DRC_VIOLATIONS',
     'expect': {'/drc/errors': 2, '/drc/byType': {'clearance:error': 2}, '/drc/prediction/clearance/gaps_mm': [0.1, 0.1],
                '/drc/crossCheck/clearance': 'confirmed', '/drc/assessment/exceeded': ['errors']}},
    {'id': 'open-net-drill', 'board': 'tiny-open',
     'document': {'operation': 'drillExport', **GATES, 'units': 'mm', 'separatePlating': True}, 'fault': 'DRC_VIOLATIONS',
     'expect': {'/drc/unconnected': 1, '/drc/warnings': 2, '/drc/byType': {'track_dangling:warning': 2},
                '/drc/prediction/unconnected/missing': 1, '/drc/crossCheck/unconnected': 'confirmed',
                '/drc/assessment/exceeded': ['unconnected', 'warnings']}}]


def pointer(value, path):
    for part in path.strip('/').split('/'):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def same(actual, expected):
    if isinstance(expected, bool) or not isinstance(expected, (int, float)):
        return actual == expected
    return isinstance(actual, (int, float)) and abs(actual-expected) <= 1e-6


def digests():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(FIXTURES.iterdir())}


def drill_hits(directory, units):
    """Literal coordinate cross-check of the published Excellon text, separate from the adaptor reader."""
    scale = 25.4 if units == 'in' else 1.0
    hits = []
    for path in sorted((directory/'drill').glob('*.drl')):
        tools, plated, current = {}, None, None
        for line in path.read_text().splitlines():
            if 'TA.AperFunction,' in line:
                plated = ',Plated,' in line
            elif line.startswith('T') and 'C' in line:
                tools[line.split('C')[0]] = (float(line.split('C')[1])*scale, plated)
            elif line.startswith('T'):
                current = line
            elif line.startswith('X'):
                x, y = line[1:].split('Y')
                hits.append((float(x)*scale, -float(y)*scale, *tools[current]))
    return hits


def check_holes(expected, hits, units):
    tolerance = 0.0013 if units == 'in' else 0.0006
    remaining = list(hits)
    for x, y, d, plated in expected:
        match = next((h for h in remaining if abs(h[0]-x) <= tolerance and abs(h[1]-y) <= tolerance
                      and abs(h[2]-d) <= tolerance and h[3] is plated), None)
        if match is None:
            return f'no hit for ({x}, {y}) d={d} plated={plated}'
        remaining.remove(match)
    return 'extra hits: '+str(remaining) if remaining else None


def run_case(case, executable, output, timeout):
    document = {'version': adaptor.VERSION, 'board': str(FIXTURES/(case['board']+'.kicad_pcb')), **case['document']}
    directory = output/case['id']
    entry = {'id': case['id'], 'board': case['board'], 'operation': document['operation'], 'failures': []}
    try:
        result = adaptor.run(document, directory, executable=executable, timeout=timeout)
        entry['result'] = {k: result[k] for k in ('verified', 'operation', 'runtime')}
        if case.get('fault'):
            entry['failures'].append('expected '+case['fault']+' but the run succeeded')
    except SchemaxisError as error:
        entry['fault'] = error.fault.code
        if error.fault.code != case.get('fault'):
            entry['failures'].append('unexpected fault: '+json.dumps(error.fault.to_dict())[:2000])
    summary_path = directory/'board-summary.json'
    if not summary_path.is_file():
        entry['failures'].append('board-summary.json missing')
        return entry
    summary = json.loads(summary_path.read_text())
    entry['observed'] = {}
    for path, expected in case['expect'].items():
        try:
            actual = pointer(summary, path)
        except (KeyError, IndexError, TypeError):
            actual = '<missing>'
        entry['observed'][path] = actual
        if not same(actual, expected):
            entry['failures'].append(f'{path}: expected {expected!r}, observed {actual!r}')
    if case.get('fault'):
        if (directory/'drill').exists() or (directory/'verification.json').exists():
            entry['failures'].append('failed DRC still produced drill files or a publication receipt')
    if 'holes' in case and not case.get('fault'):
        problem = check_holes(case['holes'], drill_hits(directory, document['units']), document['units'])
        if problem:
            entry['failures'].append('literal drill hit check: '+problem)
        entry['observed']['literalDrillHits'] = len(case['holes'])
    return entry


def tamper(directory):
    """Every publication and retained input must be covered by verification."""
    probes = []
    for name in ['board-summary.json', 'board-statistics.json', 'drc-report.json', 'drill/board-PTH.drl',
                 'drill/board-NPTH.drl', 'board/board.kicad_pcb', 'board/board.kicad_pro', 'runtime.json', 'plan.json',
                 'drc-submission.json', 'drill-submission.json', 'stats.stdout', 'drc.stdout']:
        path = directory/name
        original = path.read_bytes()
        try:
            path.write_bytes(original.replace(b'1', b'2', 1) if b'1' in original else original+b' ')
            try:
                adaptor.verify(directory)
                probes.append({'file': name, 'detected': False})
            except SchemaxisError as error:
                probes.append({'file': name, 'detected': True, 'fault': error.fault.code})
        finally:
            path.write_bytes(original)
    adaptor.verify(directory)
    return probes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kicad', default=os.environ.get('KICAD_CLI'), help='absolute KiCad 10.0 kicad-cli executable')
    parser.add_argument('--output-directory', required=True)
    parser.add_argument('--timeout', type=float, default=300)
    args = parser.parse_args()
    output = Path(args.output_directory).absolute()
    if output.exists():
        parser.error('choose a fresh output directory')
    if not args.kicad or not Path(args.kicad).is_absolute():
        parser.error('pass an absolute --kicad executable; an unavailable runtime is unqualified, not skipped')
    output.mkdir(parents=True)
    before = digests()
    cases = [run_case(case, args.kicad, output, args.timeout) for case in CASES]
    report = {'version': 'schemaxis.kicad.acceptance/1', 'cases': cases}
    baseline = output/'baseline-drill'
    report['tamper'] = tamper(baseline) if (baseline/'verification.json').is_file() else []
    environment = dict(os.environ, PYTHONPATH=str(ROOT/'src'), PYTHONDONTWRITEBYTECODE='1')
    document = output/'cli-drc.json'
    document.write_text(json.dumps({'version': adaptor.VERSION, 'operation': 'designRuleCheck',
                                    'board': str(FIXTURES/'tiny-variant.kicad_pcb'), **GATES}))
    cli = subprocess.run([sys.executable, '-m', 'schemaxis', 'run', str(document), '--kicad', args.kicad,
                          '--output-directory', str(output/'cli-drc'), '--timeout', str(args.timeout)],
                         cwd=ROOT, env=environment, capture_output=True, text=True, timeout=args.timeout+60)
    verify = subprocess.run([sys.executable, '-m', 'schemaxis', 'verify', str(output/'cli-drc')], cwd=ROOT, env=environment,
                            capture_output=True, text=True, timeout=120)
    report['cli'] = {'run': cli.returncode, 'verify': verify.returncode, 'stderr': (cli.stderr+verify.stderr)[-2000:]}
    report['fixturesUnchanged'] = digests() == before
    runtimes = {json.dumps(c.get('result', {}).get('runtime', {}), sort_keys=True) for c in cases if c.get('result')}
    report['runtime'] = [json.loads(r) for r in sorted(runtimes)]
    failures = [f"{c['id']}: {f}" for c in cases for f in c['failures']]
    failures += [f"tamper not detected: {p['file']}" for p in report['tamper'] if not p['detected']]
    if not report['tamper']:
        failures.append('tamper probes did not run: baseline drill publication missing')
    if report['cli']['run'] or report['cli']['verify']:
        failures.append('shared CLI run/verify failed')
    if not report['fixturesUnchanged']:
        failures.append('repository fixtures changed during native execution')
    report.update(failures=failures, verified=not failures)
    (output/'acceptance.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'verified': report['verified'], 'failures': failures, 'runtime': report['runtime'],
                      'cases': [{'id': c['id'], 'fault': c.get('fault'), 'failures': c['failures']} for c in cases]}, indent=2))
    return 0 if report['verified'] else 1


if __name__ == '__main__':
    sys.exit(main())
