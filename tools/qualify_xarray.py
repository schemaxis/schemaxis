#!/usr/bin/env python3
"""Qualify xarray named-coordinate profile reduction through the public Schemaxis path.

Runs the shared conformance kit, analytic and permuted-axis native cases with literal outcomes fixed in advance,
host refusals that must happen before any native launch, saved-evidence controls in three separate groups
(integrity controls caught by retained input, worker, readback, publication or receipt checks; meaning-changing
semantic mutants beyond tolerance with the bindings needed to reach independent profile checks refreshed and a named fault cause asserted; a one-ulp within-tolerance control), a single-operation workflow with byte reuse, same-path source invalidation and offline verification of the
retained capture, direct-path Gnuplot controls on separately produced profile.csv files, and the real two-operation
workflow xarray reduceProfile -> Gnuplot plot whose source is {"$artifact": "profile", "index": 1}, executed by the
public workflow scheduler with both native locations and checked with independent SVG and PNG chart expectations.
Host code is standard-library only; the native runtime is the configured isolated Python (exactly xarray 2026.9.0,
SciPy 1.18.1, NumPy 2.5.4). A missing or wrong runtime is reported as a structured failure, never a skip.
"""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import struct
import sys
import xml.etree.ElementTree as ET

from schemaxis.adaptor_conformance import qualify, register
from schemaxis.adaptors.gnuplot import adaptor as gnuplot
from schemaxis.adaptors.gnuplot.inspection import pixels
from schemaxis.adaptors.xarray import adaptor as a, cdf
from schemaxis import publication_metadata
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis import workflow

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / 'examples/schemaxis'
sys.path.insert(0, str(ROOT / 'tools'))
import xarray_fixtures as fx  # noqa: E402

SVG = '{http://www.w3.org/2000/svg}'
MISSING = {(1, 3, 0)}


def document(source, **changes):
    doc = json.loads((EXAMPLES / 'xarray-profile.json').read_text())
    doc['source'] = str(source)
    doc.update(changes)
    return doc


def refused(action):
    try:
        action()
    except SchemaxisError as error:
        return error.fault.to_dict()
    raise AssertionError('expected a structured refusal')


def csv_rows(path):
    return [line.split(',') for line in Path(path).read_text().splitlines()]


def native_case(directory, name, doc, executable, *, rows, totals=None):
    run = directory / name
    result = a.run(doc, run, executable=executable, timeout=60)
    assert a.verify(run)['verified'] and result['status'] == 'succeeded', name
    got = csv_rows(run / 'profile.csv')[1:]
    assert got == [[x if isinstance(x, str) else repr(x) for x in r] for r in rows], (name, got)
    summary = json.loads((run / 'xarray-summary.json').read_text())
    if totals:
        assert summary['totals'] == totals, (name, summary['totals'])
    native = json.loads((run / 'native-result.json').read_text())
    assert native['engine'] == 'scipy' and native['runtime']['xarray'] == '2026.9.0'
    return {'rows': got, 'totals': summary['totals'], 'runtime': summary['runtime']}


def cases(directory, executable):
    sources = directory / 'sources'
    sources.mkdir()
    clean, holes = sources / 'clean.nc', sources / 'holes.nc'
    clean.write_bytes(fx.build())
    holes.write_bytes(fx.build(missing=MISSING))
    report = {}
    base = [[0.0, 280.625, 6, 0], [10.0, 285.625, 6, 0], [20.0, 290.625, 6, 0], [30.0, 295.625, 6, 0]]
    report['baseline'] = native_case(directory, 'baseline', document(clean), executable, rows=base,
                                     totals={'selectedCells': 24, 'validCells': 24, 'missingCells': 0})
    # the same named results from a cube whose storage axes are permuted, declared in the stored order
    permuted = sources / 'permuted.nc'
    permuted.write_bytes(fx.build(order=('station', 'depth', 'time')))
    names = {c['name']: c for c in document(clean)['coordinates']}
    report['permuted'] = native_case(directory, 'permuted', document(permuted, coordinates=[names[k] for k in ('station', 'depth', 'time')]),
                                     executable, rows=base)
    report['retainStation'] = native_case(directory, 'retain-station', document(clean, retain='station'), executable,
                                          rows=[[1.0, 288.0, 12, 0], [2.0, 288.25, 12, 0]])
    ranged = document(clean)
    ranged['coordinates'][0]['range'] = {'minimum': 0, 'maximum': 0}
    report['changedRange'] = native_case(directory, 'changed-range', ranged, executable,
                                         rows=[[0.0, 280.125, 2, 0], [10.0, 285.125, 2, 0], [20.0, 290.125, 2, 0], [30.0, 295.125, 2, 0]])
    prop = document(holes, missing={'value': -999.0, 'policy': 'propagate'})
    report['propagate'] = native_case(directory, 'propagate', prop, executable,
                                      rows=[[0.0, 280.625, 6, 0], [10.0, 285.625, 6, 0], [20.0, 290.625, 6, 0], [30.0, '', 5, 1]],
                                      totals={'selectedCells': 24, 'validCells': 23, 'missingCells': 1})
    skip = document(holes, missing={'value': -999.0, 'policy': 'skip', 'minimumValid': 5})
    report['skip'] = native_case(directory, 'skip', skip, executable,
                                 rows=[[0.0, 280.625, 6, 0], [10.0, 285.625, 6, 0], [20.0, 290.625, 6, 0], [30.0, 295.65, 5, 1]],
                                 totals={'selectedCells': 24, 'validCells': 23, 'missingCells': 1})
    return report, clean, holes


def refusals(directory, executable, clean, holes):
    """Each refusal is a host decision before any native launch."""
    sources = directory / 'sources'
    built = {
        'permutedUndeclared': (fx.build(order=('depth', 'time', 'station')), {}, 'XR_DIMENSION_ORDER'),
        'unitsAbsent': (fx.build(units={'depth': None}), {}, 'XR_UNITS_MISSING'),
        'unitsDifferent': (fx.build(units={'depth': 'cm'}), {}, 'XR_UNITS_MISMATCH'),
        'duplicateCoordinate': (fx.build(axes={'depth': [0.0, 10.0, 10.0, 30.0]}), {}, 'XR_COORDINATE_ORDER'),
        'nonmonotonic': (fx.build(axes={'depth': [0.0, 20.0, 10.0, 30.0]}), {}, 'XR_COORDINATE_ORDER'),
        'allMissingRefuse': (fx.build(missing={(t, d, s) for t in range(3) for d in range(4) for s in range(2)}), {}, 'XR_PROFILE_ALL_MISSING'),
        'fillMismatch': (fx.build(), {'missing': {'value': -998.0, 'policy': 'refuse'}}, 'XR_FILL_MISMATCH'),
        'notClassic': (b'\x89HDF\r\n\x1a\n' + b'\0' * 64, {}, 'XR_UNSUPPORTED_FORMAT'),
    }
    out = {}
    for name, (data, changes, code) in built.items():
        source = sources / (name + '.nc')
        source.write_bytes(data)
        doc = document(source, **changes)
        if name == 'allMissingRefuse':
            doc['missing'] = {'value': -999.0, 'policy': 'propagate'}
        run = directory / ('refused-' + name)
        fault = refused(lambda: a.run(doc, run, executable=executable, timeout=60))
        assert fault['code'] == code, (name, fault)
        assert not (run / 'compute-submission.json').exists(), name
        out[name] = fault['code']
    ranged = document(clean)
    for label, rng, code in (('empty', {'minimum': 11, 'maximum': 19}, 'XR_SELECTION_EMPTY'), ('outOfBounds', {'minimum': -1, 'maximum': 20}, 'XR_RANGE_OUT_OF_BOUNDS')):
        doc = copy.deepcopy(ranged)
        doc['coordinates'][1]['range'] = rng
        fault = refused(lambda: a.run(doc, directory / ('refused-' + label), executable=executable, timeout=60))
        assert fault['code'] == code, (label, fault)
        out[label] = code
    doc = document(holes, missing={'value': -999.0, 'policy': 'refuse'})
    assert refused(lambda: a.run(doc, directory / 'refused-policy', executable=executable, timeout=60))['code'] == 'XR_MISSING_VALUES'
    assert refused(lambda: a.run(ranged, directory / 'refused-runtime', executable='/nonexistent/python'))['code'] == 'INTERPRETER_NOT_FOUND'
    out['missingRuntime'] = 'INTERPRETER_NOT_FOUND'
    return out


def refresh(target):
    """Integrity-control refresh: recompute only the verification receipt (artifact and evidence digests).

    Native-recorded bindings (native-result.json, readback-inputs.json) are NOT refreshed, so a changed publication is
    caught by retained integrity checks, which proves integrity, not meaning."""
    p = a.plan(a.read(target, 'authored.json'))
    receipt = a.read(target, 'verification.json')
    receipt['artifacts'] = a.artifacts(target, p)
    receipt['evidence'] = {name: a.digest(target, name) for name in sorted(a.evidence_names())}
    atomic_json(target / 'verification.json', receipt)


def pack(values):
    return hashlib.sha256(struct.pack('>%dd' % len(values), *values)).hexdigest()


def refresh_all(target):
    """Refresh the bindings needed to reach the independent profile checks after a publication edit.

    Covers the native-recorded file, mean and coordinate digests and counts (native-result.json), readback-inputs.json,
    the verification receipt (artifacts and evidence digests) and the publication metadata companions. Summary
    publication digests are left for the later summary check; each semantic control must reach and fail the earlier
    independent profile comparison."""
    p = a.plan(a.read(target, 'authored.json'))
    parsed = cdf.parse((target / 'profile.nc').read_bytes())
    got = {v['name']: v for v in parsed['vars']}
    native = a.read(target, 'native-result.json')
    native['files'] = {name: hashlib.sha256((target / name).read_bytes()).hexdigest() for name in ('profile.csv', 'profile.nc')}
    native['coordinateDigest'] = pack(got[p['retain']]['values'])
    native['meanDigest'] = pack(got[p['variable']['name']]['values'])
    native['validCounts'], native['missingCounts'] = list(got['validCount']['values']), list(got['missingCount']['values'])
    atomic_json(target / 'native-result.json', native)
    base = {name: a.digest(target, name) for name in ('source.nc', 'native-config.json', 'native-worker.py')}
    atomic_json(target / 'readback-inputs.json', {**base, **{name: a.digest(target, name) for name in ('native-result.json', 'profile.nc', 'profile.csv')}})
    refresh(target)
    publication_metadata.finalise(target)


def rewrite_publication(target, change):
    """Rewrite profile.nc through the host writer and profile.csv with an independent formatter, both consistent with `change`."""
    p = a.plan(a.read(target, 'authored.json'))
    parsed = cdf.parse((target / 'profile.nc').read_bytes())
    variables = [{'name': v['name'], 'dims': v['dims'], 'type': v['type'], 'values': list(v['values']),
                  'attrs': [(k, kind, value) for k, (kind, value) in v['attrs'].items()]} for v in parsed['vars']]
    by = {v['name']: v for v in variables}
    change(by)
    attrs = [(k, kind, value) for k, (kind, value) in parsed['attrs'].items()]
    (target / 'profile.nc').write_bytes(cdf.write(parsed['dims'], attrs, variables))
    sentinel, retain, name = p['missing']['value'], p['retain'], p['variable']['name']
    lines = [','.join([retain, name, 'validCount', 'missingCount'])]
    for x, m, v, k in zip(by[retain]['values'], by[name]['values'], by['validCount']['values'], by['missingCount']['values']):
        lines.append(','.join([repr(x), '' if m == sentinel else repr(m), str(v), str(k)]))
    (target / 'profile.csv').write_bytes(('\n'.join(lines) + '\n').encode('ascii'))


def hostile(directory):
    """Saved-evidence controls, reported in three honest groups.

    integrityControls: the stored evidence was altered and only the verification receipt was refreshed, so the native
        bindings (readback-inputs, native-result, capture, worker, runtime) catch it. They prove integrity, not meaning.
    semanticMutants: meaning-changing edits beyond tolerance with every ordinary digest/binding refreshed
        (refresh_all, including readback-inputs); each must be refused by the independent checker for the named cause.
    toleranceControls: a one-ulp edit within the declared tolerance, which is not a mathematical error.
    """
    baseline = directory / 'baseline'
    report = {'integrityControls': {}, 'semanticMutants': {}, 'toleranceControls': {}}

    def clone(label):
        target = directory / ('hostile-' + label)
        shutil.copytree(baseline, target, ignore=shutil.ignore_patterns('.dispatch'))
        return target

    def expect_refusal(group, label, target, cause):
        fault = refused(lambda: a.verify(target))
        assert fault['code'] == 'VERIFICATION_FAILED' and cause in fault['message'], (label, fault['message'])
        report[group][label] = {'code': fault['code'], 'cause': cause}

    def integrity(label, change, cause, *, refreshed=True):
        target = clone(label)
        change(target)
        if refreshed:
            refresh(target)
        expect_refusal('integrityControls', label, target, cause)

    def semantic(label, change, cause, *, publication=True):
        target = clone(label)
        (rewrite_publication if publication else (lambda t, c: c(t)))(target, change)
        refresh_all(target)
        expect_refusal('semanticMutants', label, target, cause)

    def csv_value(target):
        path = target / 'profile.csv'
        path.write_text(path.read_text().replace('285.625', '285.626'))

    def csv_zero(target):
        path = target / 'profile.csv'
        path.write_text(path.read_text().replace('295.625', '0.0'))

    def nc_value(target):
        path = target / 'profile.nc'
        data = bytearray(path.read_bytes())
        position = bytes(data).rfind(struct.pack('>d', 280.625))      # the published mean at depth 0
        assert position >= 0
        data[position + 7] ^= 1                                       # one ulp: inside the declared tolerance
        path.write_bytes(bytes(data))

    def summary_edit(target):
        summary = json.loads((target / 'xarray-summary.json').read_text())
        summary['profile']['validCounts'][0] = 5
        atomic_json(target / 'xarray-summary.json', summary)

    def source_edit(target):
        data = bytearray((target / 'source.nc').read_bytes())
        data[-9] ^= 1
        (target / 'source.nc').write_bytes(bytes(data))

    def worker(target):
        (target / 'native-worker.py').write_text((target / 'native-worker.py').read_text() + '\n# altered\n')

    def runtime(target):
        record = json.loads((target / 'native-result.json').read_text())
        record['runtime']['xarray'] = '2026.8.0'
        atomic_json(target / 'native-result.json', record)

    def member(target):
        (target / 'extra.csv').write_text('x\n')
        receipt = a.read(target, 'verification.json')
        receipt['artifacts'].append({'file': str(target / 'extra.csv'), 'kind': 'table', 'sha256': a.digest(target, 'extra.csv')})
        atomic_json(target / 'verification.json', receipt)

    readback = 'native readback consumed different publication bytes'
    integrity('csvValue', csv_value, readback)
    integrity('csvFakeZero', csv_zero, readback)
    integrity('netcdfBit', nc_value, readback)
    integrity('summaryCounts', summary_edit, 'summary differs from independent recomputation')
    integrity('sourceBytes', source_edit, 'captured source identity differs')
    integrity('worker', worker, 'trusted worker or native configuration differs')
    integrity('runtimeRecord', runtime, readback)
    integrity('membership', member, 'publication membership or digests differ', refreshed=False)
    integrity('csvValueUnrefreshed', csv_value, readback, refreshed=False)

    beyond = 'published mean disagrees with the exact mean beyond the declared tolerance'
    csv_differs = 'published CSV differs from the values and counts in profile.nc'

    def mean_off(by):                                    # 285.625 -> 285.625001: 1e-6 absolute, far beyond the 1e-13 bound
        by['temperature']['values'][1] += 1e-6

    def mean_zero(by):
        by['temperature']['values'][3] = 0.0

    def count_shift(by):                                 # a self-consistent count forgery: one valid cell recorded as missing
        by['validCount']['values'][0], by['missingCount']['values'][0] = 5, 1

    def coordinate_shift(by):
        by['depth']['values'][2] = 21.0

    semantic('meanBeyondTolerance', mean_off, beyond)
    semantic('meanFakeZero', mean_zero, beyond)
    semantic('countsForged', count_shift, 'published counts differ from the independent counts')
    semantic('coordinateForged', coordinate_shift, 'published coordinates differ from the selected source coordinates')

    def csv_only(old, new):
        def change(target):
            path = target / 'profile.csv'
            path.write_text(path.read_text().replace(old, new))
        return change

    semantic('csvMeanOnly', csv_only('285.625', '285.626'), csv_differs, publication=False)
    semantic('csvFakeZeroOnly', csv_only('295.625', '0.0'), csv_differs, publication=False)

    def netcdf_only(target, change):
        parsed = cdf.parse((target / 'profile.nc').read_bytes())
        variables = [{'name': v['name'], 'dims': v['dims'], 'type': v['type'], 'values': list(v['values']),
                      'attrs': [(k, kind, value) for k, (kind, value) in v['attrs'].items()]} for v in parsed['vars']]
        change({v['name']: v for v in variables})
        attrs = [(k, kind, value) for k, (kind, value) in parsed['attrs'].items()]
        (target / 'profile.nc').write_bytes(cdf.write(parsed['dims'], attrs, variables))

    semantic('netcdfMeanOnly', lambda t: netcdf_only(t, mean_off), beyond, publication=False)

    def summary_mean(target):
        summary = json.loads((target / 'xarray-summary.json').read_text())
        summary['profile']['means'][1] += 1e-6
        atomic_json(target / 'xarray-summary.json', summary)

    semantic('summaryMean', summary_mean, 'summary differs from independent recomputation', publication=False)

    # One ulp is inside the declared tolerance and is NOT a mathematical error. Two honest independent-checker controls:
    def one_ulp(by):
        by['temperature']['values'][0] = math.nextafter(by['temperature']['values'][0], math.inf)

    target = clone('ulpInconsistent')                     # profile.nc moved one ulp, profile.csv not: an inconsistency, not a tolerance breach
    netcdf_only(target, one_ulp)
    refresh_all(target)
    expect_refusal('toleranceControls', 'netcdfOneUlpCsvUnchanged', target, csv_differs)

    target = clone('ulpConsistent')                       # profile.nc and profile.csv agree, summary regenerated: accepted within tolerance
    rewrite_publication(target, one_ulp)
    refresh_all(target)
    p = a.plan(a.read(target, 'authored.json'))
    data = (target / 'source.nc').read_bytes()
    cube, points = a.load_cube(p, data)
    atomic_json(target / 'xarray-summary.json', a.build_summary(target, p, data, cube, points))
    refresh_all(target)
    verified = a.verify(target)
    summary = a.read(target, 'xarray-summary.json')
    exact = points[0]['mean']
    published = summary['profile']['means'][0]
    assert verified['verified'] and published == math.nextafter(exact, math.inf) and 0 < summary['reduction']['maxAbsoluteError'] <= points[0]['tolerance']
    report['toleranceControls']['netcdfOneUlpConsistentAccepted'] = {
        'verified': True, 'exactMean': exact, 'publishedMean': published, 'maxAbsoluteError': summary['reduction']['maxAbsoluteError'],
        'tolerance': points[0]['tolerance'],
        'note': 'one ulp is within the declared first-order tolerance and is not a mathematical error; the stored native readback verdict is not recomputed by the host'}
    return report


def workflows(directory, executable):
    source = directory / 'wf-cube.nc'
    source.write_bytes(fx.build())
    graph = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'reduce', 'document': document(source)}]}
    target = directory / 'workflow'
    locations = {'xarray': executable}
    first = workflow.execute(graph, target, locations=locations, timeout=60)
    assert workflow.verify(target)['verified']
    second = workflow.execute(graph, target, locations=locations, timeout=60, resume=True)
    assert all(j['reused'] for j in second['jobs'])
    source.write_bytes(fx.build(missing={(0, 0, 0)}))          # same path, different bytes (a missing cell appears)
    third = refused(lambda: workflow.execute(graph, target, locations=locations, timeout=60, resume=True))
    assert third['code'] == 'XR_MISSING_VALUES', third
    source.write_bytes(fx.build().replace(b'Analytic', b'Altered '))      # same path, changed title bytes only
    fourth = workflow.execute(graph, target, locations=locations, timeout=60, resume=True)
    assert not any(j['reused'] for j in fourth['jobs']) and workflow.verify(target)['verified']
    source.unlink()
    assert workflow.verify(target)['verified']                 # retained capture verifies offline
    return {'first': first['status'], 'unchangedReused': True, 'changedSourceRefusedByPolicy': third['code'],
            'changedBytesNotReused': True, 'offlineVerifyWithoutSource': True}


def series(svg_path, colour='rgb( 31, 119, 180)'):
    root = ET.fromstring(Path(svg_path).read_bytes())
    points = []
    for node in root.iter(SVG + 'use'):
        if node.get('color') == colour:
            match = re.match(r'translate\(([-0-9.]+),([-0-9.]+)\)', node.get('transform', ''))
            if match and float(match.group(2)) <= 480.1:
                points.append([float(match.group(1)), float(match.group(2))])
    return points


PLOT_COLUMNS = [{'name': 'depth', 'unit': 'm'}, {'name': 'temperature', 'unit': 'K'},
                {'name': 'validCount', 'unit': 'count'}, {'name': 'missingCount', 'unit': 'count'}]
# literal analytic profiles: mean over time and station of v = 280 + 5*depthIndex + 0.5*timeIndex + 0.25*stationIndex
BASE_ROWS = [[0.0, 280.625, 6, 0], [10.0, 285.625, 6, 0], [20.0, 290.625, 6, 0], [30.0, 295.625, 6, 0]]
RANGED_ROWS = [[0.0, 280.125, 2, 0], [10.0, 285.125, 2, 0], [20.0, 290.125, 2, 0], [30.0, 295.125, 2, 0]]
SHIFTED_ROWS = [[0.0, 282.625, 6, 0], [10.0, 287.625, 6, 0], [20.0, 292.625, 6, 0], [30.0, 297.625, 6, 0]]
WORKFLOW_PLOT = {'xr': (0, 30), 'yr': (270, 300)}


def plot_document(source, xr=(0, 30), yr=(270, 300)):
    return {'version': 'schemaxis.gnuplot/1', 'operation': 'plot', 'title': 'Depth profile', 'source': source,
            'columns': copy.deepcopy(PLOT_COLUMNS),
            'series': [{'label': 'Mean temperature', 'x': 'depth', 'y': 'temperature', 'colour': 'blue'}],
            'xAxis': {'label': 'Depth', 'unit': 'm', 'range': list(xr), 'scale': 'linear'},
            'yAxis': {'label': 'Temperature', 'unit': 'K', 'range': list(yr), 'scale': 'linear'}}


def check_plot(run, rows, xr, yr):
    """Independent SVG marker and PNG pixel checks against rows fixed in advance (not read back from the consumer)."""
    expected = [[120 + 640 * (r[0] - xr[0]) / (xr[1] - xr[0]), 480 - 420 * (r[1] - yr[0]) / (yr[1] - yr[0])] for r in rows]
    observed = series(run / 'plot.svg')
    assert len(observed) == len(expected) and all(abs(x - u) <= 0.06 and abs(y - v) <= 0.06 for (x, y), (u, v) in zip(observed, expected)), (observed, expected)
    width, height, image = pixels((run / 'plot.png').read_bytes())
    for x, y in expected:
        assert any(image[yy][xx] == (31, 119, 180) for yy in range(round(y) - 2, round(y) + 3) for xx in range(round(x) - 2, round(x) + 3)), (x, y)
    return observed


def gnuplot_case(directory, name, csv_path, gp_exe, xr=(0, 30), yr=(270, 300)):
    """Direct-path control: Gnuplot reads a profile.csv from a separate producer run (no workflow edge)."""
    run = directory / name
    result = gnuplot.run(plot_document(str(csv_path), xr, yr), run, executable=gp_exe, timeout=60)
    assert gnuplot.verify(run)['verified'] and result['status'] == 'succeeded'
    equal = (run / 'captured.csv').read_bytes() == Path(csv_path).read_bytes()
    assert equal, 'consumer capture differs from producer CSV'
    rows = [list(map(float, r)) for r in csv_rows(csv_path)[1:]]
    observed = check_plot(run, rows, xr, yr)
    version = (run / 'version.stdout').read_text().strip()
    return observed, version, equal


def handoff(directory, gp_exe):
    first, version, equal_first = gnuplot_case(directory, 'plot-baseline', directory / 'baseline/profile.csv', gp_exe)
    second, _, equal_second = gnuplot_case(directory, 'plot-changed-range', directory / 'changed-range/profile.csv', gp_exe)
    assert first != second and all(abs(u[1] - v[1]) > 1 for u, v in zip(first, second)), 'changed selection did not propagate'
    # missing-policy controls stay separate: the consumer refuses an empty mean cell
    refusal = refused(lambda: gnuplot.run(plot_document(str(directory / 'propagate/profile.csv')), directory / 'plot-propagate-refused',
                                          executable=gp_exe, timeout=60))
    return {'gnuplotVersion': version, 'baselineMarkers': first, 'changedRangeMarkers': second,
            'directPathCapturedBytesEqualProducerCsv': equal_first and equal_second, 'consumerRefusesMissingMean': refusal['code']}


def digest_of(data):
    return hashlib.sha256(data).hexdigest()


def edge_graph(source, **changes):
    producer = document(source, **changes)
    consumer = plot_document({'$artifact': 'profile', 'index': 1}, **WORKFLOW_PLOT)
    return {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'profile', 'document': producer}, {'id': 'plot', 'document': consumer}]}


def job_directories(target):
    """Producer and consumer job records and run directories of a scheduled workflow result."""
    result = json.loads((target / 'result.json').read_text())
    by_operation = {job['operation']: job for job in result['jobs']}
    return result, by_operation['profile'], by_operation['plot']


def check_edge(target, rows):
    """The authored $artifact edge: normal workflow verification, handoff provenance, byte identity and chart expectations."""
    result, producer, consumer = job_directories(target)
    assert result['status'] == 'succeeded' and workflow.verify(target)['verified']
    pdir, cdir = Path(producer['directory']), Path(consumer['directory'])
    produced, captured = (pdir / 'profile.csv').read_bytes(), (cdir / 'captured.csv').read_bytes()
    assert produced == captured, 'consumer captured.csv differs from the producer profile.csv'
    assert consumer['document']['source'] == {'$artifact': 'profile', 'index': 1}
    assert consumer['dependencies'] == ['profile'] and consumer['effective']['source'] == str(pdir / 'profile.csv')
    [handoff_record] = consumer['handoffs']
    assert handoff_record == {'from': 'profile', 'index': 1, 'file': str(pdir / 'profile.csv'), 'sha256': digest_of(produced)}, handoff_record
    capture = json.loads((cdir / 'captures.json').read_text())
    assert capture['source'] == str(pdir / 'profile.csv') and capture['sha256'] == digest_of(produced)
    assert a.verify(pdir)['verified'] and gnuplot.verify(cdir)['verified']
    assert [[x if isinstance(x, str) else repr(x) for x in r] for r in rows] == csv_rows(pdir / 'profile.csv')[1:], 'producer rows differ from the literal analytic profile'
    markers = check_plot(cdir, rows, WORKFLOW_PLOT['xr'], WORKFLOW_PLOT['yr'])
    return {'producerCsvSha256': digest_of(produced), 'capturedBytesEqualProducerCsv': produced == captured, 'markers': markers,
            'gnuplotVersion': (cdir / 'version.stdout').read_text().strip(), 'reused': [producer['reused'], consumer['reused']]}


def handoff_workflow(directory, executable, gp_exe):
    locations = {'xarray': executable, 'gnuplot': gp_exe}
    source = directory / 'edge-cube.nc'
    source.write_bytes(fx.build())
    graph = edge_graph(source)
    target = directory / 'edge-workflow'
    out = {}
    workflow.execute(graph, target, locations=locations, timeout=120)
    out['baseline'] = check_edge(target, BASE_ROWS)
    assert out['baseline']['reused'] == [False, False]
    again = workflow.execute(graph, target, locations=locations, timeout=120, resume=True)
    assert all(job['reused'] for job in again['jobs'])
    out['unchangedReuse'] = check_edge(target, BASE_ROWS)['reused']
    assert out['unchangedReuse'] == [True, True]
    # a changed authored selection in a fresh workflow changes the means, the markers and the bytes
    ranged = edge_graph(source)
    ranged['operations'][0]['document']['coordinates'][0]['range'] = {'minimum': 0, 'maximum': 0}
    changed = directory / 'edge-workflow-changed-range'
    workflow.execute(ranged, changed, locations=locations, timeout=120)
    out['changedRange'] = check_edge(changed, RANGED_ROWS)
    assert out['changedRange']['producerCsvSha256'] != out['baseline']['producerCsvSha256']
    assert all(abs(u[1] - v[1]) > 1 for u, v in zip(out['baseline']['markers'], out['changedRange']['markers']))
    # same path, different source bytes (all cells +2): both operations rerun and the chart moves
    cells = [fx.value(t, d, s) + 2.0 for t in range(3) for d in range(4) for s in range(2)]
    source.write_bytes(fx.build(data=cells))
    workflow.execute(graph, target, locations=locations, timeout=120, resume=True)
    out['sameSourcePathNewBytes'] = check_edge(target, SHIFTED_ROWS)
    assert out['sameSourcePathNewBytes']['reused'] == [False, False]
    assert out['sameSourcePathNewBytes']['producerCsvSha256'] != out['baseline']['producerCsvSha256']
    assert all(abs(u[1] - v[1]) > 1 for u, v in zip(out['baseline']['markers'], out['sameSourcePathNewBytes']['markers']))
    # same path, metadata-only source change: the producer reruns on the new source bytes; the identical profile is published again
    source.write_bytes(fx.build(data=cells).replace(b'Analytic', b'Altered '))
    workflow.execute(graph, target, locations=locations, timeout=120, resume=True)
    out['sameSourcePathTitleOnly'] = check_edge(target, SHIFTED_ROWS)
    assert out['sameSourcePathTitleOnly']['reused'][0] is False
    source.unlink()
    assert workflow.verify(target)['verified']                 # retained captures verify offline
    out['offlineVerifyWithoutSource'] = True
    # missing-policy negative stays separate: a propagated empty mean cell is refused by the consumer route
    holes = directory / 'edge-holes.nc'
    holes.write_bytes(fx.build(missing=MISSING))
    refusal_graph = edge_graph(holes, missing={'value': -999.0, 'policy': 'propagate'})
    refused_target = directory / 'edge-workflow-propagate-refused'
    fault = refused(lambda: workflow.execute(refusal_graph, refused_target, locations=locations, timeout=120))
    assert fault['code'] == 'INVALID_PLOT_DATA', fault
    [produced] = sorted((refused_target / 'profile/batch-0').glob('attempt-*'))
    failed = json.loads((refused_target / 'result.json').read_text())
    states = {job['operation']: job['status'] for job in failed['jobs']}
    assert failed['status'] == 'failed' and states == {'profile': 'succeeded', 'plot': 'failed'}, states
    # the consumer route's own host validation refuses before any attempt directory exists, so no Gnuplot process was launched
    assert not list((refused_target / 'plot/batch-0').glob('attempt-*')), 'Gnuplot consumer attempt created for a missing cell'
    out['propagatedMissingRefusedByConsumer'] = {'code': fault['code'], 'location': fault['location'], 'producerVerified': True,
                                                 'consumerRefusedByHostValidationBeforeNativeLaunch': True}
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xarray', type=Path, required=True, help='Absolute isolated Python with xarray 2026.9.0, SciPy 1.18.1, NumPy 2.5.4')
    parser.add_argument('--gnuplot', type=Path, default=Path('/usr/bin/gnuplot'))
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--register', action='store_true')
    args = parser.parse_args()
    directory = args.output_directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    executable = str(args.xarray.absolute())
    report = {'verified': False}
    try:
        receipt = qualify(a.VERSION, directory / 'kit', native=True, root=ROOT, locations={'xarray': executable}, timeout=60, wall_timeout=120)
        report['kit'] = {'verified': receipt['verified'], 'cases': [c['id'] for c in receipt['cases']], 'lifecycle': receipt['lifecycle']}
        report['cases'], clean, holes = cases(directory, executable)
        report['refusals'] = refusals(directory, executable, clean, holes)
        report['hostile'] = hostile(directory)
        report['workflow'] = workflows(directory, executable)
        report['gnuplotHandoff'] = handoff(directory, str(args.gnuplot.absolute()))
        report['gnuplotWorkflowEdge'] = handoff_workflow(directory, executable, str(args.gnuplot.absolute()))
        if args.register:
            register(directory / 'kit/qualification.json')
        report['verified'] = True
    finally:
        atomic_json(directory / 'acceptance.json', report)
    print(json.dumps({'verified': report['verified'], 'cases': len(report.get('cases', {})), 'refusals': len(report.get('refusals', {})),
                      'hostile': {k: len(v) for k, v in report.get('hostile', {}).items()}}, indent=2))


if __name__ == '__main__':
    main()
