#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Qualify pyproj route chainage through the public Schemaxis paths with the real runtime.

Shared conformance kit; domain, endpoint-gap, merge, analytic and requirement cases with outcomes
fixed in advance; executable adequacy fault injection for every category; semantic worker mutants;
hostile saved evidence with refreshed ordinary hashes; workflow reuse, invalidation and forged
resume provenance; a finite study; canonical schema-aware export with original sources removed;
the CLI path; in-flight and host-verification timeout/cancellation; host-contract consumer checks.
Host code is standard-library only; the native runtime is the configured isolated Python with
exactly pyproj 3.8.0 / PROJ 9.9.0. Every native PID is recorded and checked absent afterwards.
"""
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
# Child interpreters (shared conformance kit, CLI) must import the same checkout.
os.environ['PYTHONPATH'] = str(ROOT / 'src') + (os.pathsep + os.environ['PYTHONPATH'] if os.environ.get('PYTHONPATH') else '')
from schemaxis import workflow  # noqa: E402
from schemaxis.adaptor_conformance import qualify  # noqa: E402
from schemaxis.adaptors import registry  # noqa: E402
from schemaxis.adaptors.pyproj import adaptor as a, contract, geodesy as g, verifier as v  # noqa: E402
from schemaxis.artifacts import atomic_json  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402
from schemaxis.dispatch import allocation  # noqa: E402
from schemaxis.schema_snapshots import export_run  # noqa: E402

EXAMPLES = ROOT / 'examples/schemaxis'
WPG, SELKIRK, LOCKPORT = [-97.1384, 49.8951], [-96.8845, 50.1436], [-96.937, 50.0861]
V = [-123.1207, 49.2827]
GAP = contract.GAP
PIDS = []


def csv_text(points):
    return 'lon_deg,lat_deg\n' + ''.join(f'{lon!r},{lat!r}\n' for lon, lat in points)


def document(source, spacing, **extra):
    doc = {'version': a.VERSION, 'operation': a.OPERATION, 'source': str(source), 'ellipsoid': 'WGS84',
           'coordinateOrder': 'lonLat', 'spacing_m': spacing}
    doc.update(extra)
    return doc


def native_pids(directory):
    found = []
    for name in ('native-result.json', 'readback.json', 'compute-fault.json', 'readback-fault.json'):
        path = Path(directory) / name
        if path.is_file():
            value = json.loads(path.read_text())
            pid = (value.get('runtime') or {}).get('pid') if 'runtime' in value else value.get('pid')
            if type(pid) is int:
                found.append(pid)
    PIDS.extend(found)
    return found


def outcome(action):
    try:
        result = action()
        return {'outcome': 'accept', 'result': result}
    except SchemaxisError as error:
        return {'outcome': error.fault.code, 'location': error.fault.location, 'message': error.fault.message}


class Cases:
    def __init__(self, directory, locations):
        self.root = directory / 'cases'
        self.root.mkdir()
        self.inputs = directory / 'inputs'
        self.inputs.mkdir()
        self.locations = locations
        self.records = []

    def source(self, name, points):
        path = self.inputs / (name + '.csv')
        path.write_text(csv_text(points))
        return path

    def case(self, name, doc, expect='accept', location=None, layer=None, check=None):
        target = self.root / name
        record = {'case': name, 'expect': expect, **outcome(lambda: registry.run(doc, target, locations=self.locations, timeout=60))}
        record['nativePids'] = native_pids(target) if target.exists() else []
        stages = sorted(p.name[:-len('-submission.json')] for p in target.glob('*-submission.json')) if target.exists() else []
        faults = sorted(p.name for p in target.glob('*-fault.json')) if target.exists() else []
        record['nativeStages'], record['nativeFaults'] = stages, faults
        if record['outcome'] != expect or (location and record.get('location') != location):
            raise AssertionError('unexpected outcome: ' + json.dumps(record, default=str)[:2000])
        if layer == 'host' and (record['nativePids'] or stages):
            raise AssertionError('host refusal launched native code: ' + name)
        if layer == 'native' and not (faults == ['compute-fault.json'] and record['nativePids']):
            raise AssertionError('expected a confirmed native refusal: ' + name)
        if (target / 'route-summary.json').is_file():
            summary = json.loads((target / 'route-summary.json').read_text())
            record['summary'] = {k: summary[k] for k in ('rows', 'legs', 'totalLength_m', 'lengthNumericalBand_m', 'finalInterval_m',
                                                        'endpointGap_m', 'endpointGapNumericalBand_m', 'presentation', 'requirements', 'overall', 'outcome')}
            record['adequacy'] = json.loads((target / 'route-verification.json').read_text())['oracle']['ratios']['adequacy']
            record['savedVerify'] = outcome(lambda: registry.verify(target))['outcome']
            if record['savedVerify'] != expect:
                raise AssertionError('saved verification differs from the run outcome: ' + name)
            if check:
                record['checks'] = check(target, summary)
                if not all(value is True for key, value in record['checks'].items() if key.startswith('check')):
                    raise AssertionError('case check failed: ' + json.dumps(record, default=str)[:2000])
        self.records.append(record)
        return target


def semantic_cases(cases):
    c = cases.case
    base = cases.source('baseline', [WPG, SELKIRK, LOCKPORT])
    near = cases.source('nearly-closed', [WPG, SELKIRK, [-97.1380, 49.8953]])
    r1 = cases.source('review-r1', [[-97.0, 49.9], [-70.0, 30.0], [-40.0, 15.0], [0.0, 0.0], [30.0, -10.0]])
    r2 = cases.source('review-r2', [[0.0, 10.0], [40.0, 5.0], [80.0, 0.0], [120.0, -5.0], [160.0, -8.0], [179.5, -10.2]])
    band = cases.source('gap-leaves-band', [[-50.0, 74.0], [-80.0, 60.0], [-110.0, 74.0]])
    circ = cases.source('circumnavigation', [[lon, 70.0] for lon in (179.5, 130.0, 80.0, 30.0, -20.0, -70.0, -120.0, -179.5)])
    ulp = cases.source('gap-one-ulp', [WPG, SELKIRK, [-97.1384, math.nextafter(49.8951, 90.0)]])
    per_m = g.radii(49.8951)[0] * math.pi / 180
    five_mm = cases.source('gap-5mm', [WPG, SELKIRK, [-97.1384, 49.8951 + 0.005 / per_m]])
    sub = cases.source('gap-sub-resolution', [WPG, SELKIRK, [-97.1384, 49.8951 + 5e-7 / per_m]])
    gap = lambda m: {'endpointGap_m': {'maximum': m}}
    # Endpoint-gap domain closure (decision 2) and the review's R1/R2.
    c('gap-review-r1', document(r1, 100000.0, requirements=gap(4e6)), 'ENDPOINT_GAP_OUTSIDE_DOMAIN', GAP, 'host')
    c('gap-review-r1-no-requirement', document(r1, 100000.0), check=lambda d, s: {'checkGapNull': s['endpointGap_m'] is None})
    c('gap-review-r2-near-antipodal', document(r2, 100000.0, requirements=gap(4e6)), 'ENDPOINT_GAP_OUTSIDE_DOMAIN', GAP, 'host')
    c('gap-regional-met', document(near, 2000.0, requirements=gap(100.0)),
      check=lambda d, s: {'checkMet': s['requirements']['endpointGap_m']['state'] == 'met', 'gap_m': s['endpointGap_m']})
    for label, delta, accept in (('minus-0.1m', -0.1, True), ('plus-0.1m', 0.1, False), ('minus-1mm', -0.001, True), ('plus-1mm', 0.001, False)):
        end, mid = g.direct(*V, 100.0, 5e6 + delta), g.direct(*V, 100.0, (5e6 + delta) / 2)
        src = cases.source('gap-5000km-' + label, [V, [mid['lon'], mid['lat']], [end['lon'], end['lat']]])
        doc = document(src, 50000.0, requirements=gap(5e6))
        if accept:
            c('gap-5000km-' + label, doc, check=lambda d, s: {'checkBelowCap': s['endpointGap_m'] <= 5e6, 'gapMinusCap_m': s['endpointGap_m'] - 5e6})
        else:
            c('gap-5000km-' + label, doc, 'ENDPOINT_GAP_OUTSIDE_DOMAIN', GAP, 'native')
    c('gap-leaves-band', document(band, 20000.0, requirements=gap(3e6)), 'ENDPOINT_GAP_OUTSIDE_DOMAIN', GAP, 'native')
    c('gap-leaves-band-no-requirement', document(band, 20000.0))
    c('gap-crosses-antimeridian', document(circ, 100000.0, requirements=gap(1e5)), 'ENDPOINT_GAP_OUTSIDE_DOMAIN', GAP, 'host')
    c('circumnavigation-no-requirement', document(circ, 100000.0))
    c('gap-one-ulp-met', document(ulp, 2000.0, requirements=gap(1.0)), check=lambda d, s: {'checkTiny': s['endpointGap_m'] < 1e-8})
    c('gap-one-ulp-zero-maximum', document(ulp, 2000.0, requirements=gap(0.0)), 'ROUTE_REQUIREMENT_INDETERMINATE', GAP)
    c('gap-5mm-met', document(five_mm, 2000.0, requirements=gap(0.01)))
    c('gap-sub-resolution-indeterminate', document(sub, 2000.0, requirements=gap(1e-7)), 'ROUTE_REQUIREMENT_INDETERMINATE', GAP)
    c('gap-sub-resolution-met', document(sub, 2000.0, requirements=gap(1e-5)))
    # Requirements: host-owned three-state decision; unmet/indeterminate keep evidence, fail acceptance.
    probe = c('baseline-measurement', document(base, 1000.0))
    total = json.loads((probe / 'route-summary.json').read_text())['totalLength_m']
    length = lambda **b: {'totalLength_m': b}
    c('length-met', document(base, 1000.0, requirements=length(maximum=total + 1.0)))
    c('length-unmet', document(base, 1000.0, requirements=length(maximum=total - 1.0)), 'ROUTE_REQUIREMENT_NOT_MET', '$.requirements.totalLength_m')
    c('length-at-bound', document(base, 1000.0, requirements=length(maximum=total)), 'ROUTE_REQUIREMENT_INDETERMINATE', '$.requirements.totalLength_m')
    c('length-range-met', document(base, 1000.0, requirements=length(minimum=total - 1.0, maximum=total + 1.0)))
    # Exact merge rule and its presentation consequences (decision 4).
    single = cases.source('single-leg', [WPG, SELKIRK])
    seed = c('merge-seed', document(single, 10000.0))
    L = json.loads((seed / 'native-result.json').read_text())['result']['legs'][0]['length']
    def spacing_for(target):
        sp = target / 3
        while 3 * sp != target:
            sp = math.nextafter(sp, math.inf if 3 * sp < target else -math.inf)
        return sp
    rows = lambda d: contract.parse_table((d / 'stations.csv').read_bytes(), contract.STATION_COLUMNS, 'stations.csv')
    c('merge-exact', document(single, L / 2), check=lambda d, s: {'checkKind3': rows(d)[-1]['kind'] == 3, 'checkZero': s['finalInterval_m'] == 0.0})
    c('merge-one-ulp-below', document(single, spacing_for(math.nextafter(L, 0))),
      check=lambda d, s: {'checkTwoRows': [r['kind'] for r in rows(d)[-2:]] == [1, 2], 'checkLabels': s['presentation']['adjacentRowsWithIdenticalLabels'] == 1,
                          'checkOneUlp': s['finalInterval_m'] == L - math.nextafter(L, 0), 'finalInterval_m': s['finalInterval_m']})
    c('merge-one-ulp-above', document(single, spacing_for(math.nextafter(L, math.inf))),
      check=lambda d, s: {'checkNoStation': [r['kind'] for r in rows(d)] == [3, 1, 1, 2]})
    # Analytic anchors, geography variants and a spherical discriminator.
    equator = cases.source('equator', [[0.0, 0.0], [10.0, 0.0], [10.5, 0.0]])
    c('equator-exact', document(equator, 50000.0), check=lambda d, s: {'checkExact': abs(s['totalLength_m'] - g.equator_arc(0, 10.5)) <= s['lengthNumericalBand_m']})
    meridian = cases.source('meridian', [[-97.0, 20.0], [-97.0, 60.0]])
    c('meridian-quadrature', document(meridian, 100000.0), check=lambda d, s: {'checkArc': abs(s['totalLength_m'] - g.meridian_arc(20.0, 60.0)) <= s['lengthNumericalBand_m']})
    def sphere_gap(d, s):
        legs = contract.parse_table((d / 'legs.csv').read_bytes(), contract.LEG_COLUMNS, 'legs.csv')
        pts = [WPG, SELKIRK, LOCKPORT]
        worst = max(abs(l['length_m'] - g.spherical_inverse(*p, *q)['s']) / contract.tau(l['length_m']) for l, p, q in zip(legs, pts, pts[1:]))
        return {'sphereGapOverTau': worst, 'checkDiscriminates': worst > 1000}
    c('spherical-discriminator', document(base, 5000.0), check=sphere_gap)
    c('southern-eastern', document(cases.source('sydney', [[151.2093, -33.8688], [150.8931, -34.4278]]), 2000.0))
    c('near-antimeridian', document(cases.source('fiji', [[179.2, -16.8], [179.95, -16.3]]), 5000.0))
    c('north-to-75', document(cases.source('north', [[-97.8558, 55.7435], [-94.165, 58.7684], [-94.8297, 74.6973]]), 20000.0))
    c('tiny-legs', document(cases.source('tiny', [WPG, [-97.1384, 49.8951005], [-97.1383993, 49.8951005]]), 0.1))
    started = time.monotonic()
    big = cases.source('near-row-limit', [V, [-75.181342, 37.8539]])
    c('near-row-limit', document(big, 401.0), check=lambda d, s: {'checkRows': 9900 <= s['rows'] <= 10000, 'wallSeconds': time.monotonic() - started})
    # Domain refusals: conclusive host bounds versus exact native values confirmed by the oracle.
    c('host-latitude-80', document(cases.source('lat80', [[-97.0, 80.0], [-96.0, 79.0]]), 1000.0), 'UNSUPPORTED_GEOGRAPHY', 'line 2', 'host')
    c('host-antimeridian-leg', document(cases.source('cross', [[179.5, -17.0], [-179.5, -17.0]]), 1000.0), 'UNSUPPORTED_GEOGRAPHY', 'leg 1', 'host')
    c('host-coincident', document(cases.source('coincident', [WPG, WPG, SELKIRK]), 1000.0), 'ROUTE_COINCIDENT_WAYPOINTS', 'line 3', 'host')
    c('host-closure-ambiguous', document(cases.source('repeat', [WPG, SELKIRK, WPG]), 1000.0), 'ROUTE_CLOSURE_AMBIGUOUS', '$.source', 'host')
    lat_first = cases.inputs / 'lat-first.csv'
    lat_first.write_text('lat_deg,lon_deg\n49.8951,-97.1384\n50.1436,-96.8845\n')
    c('host-latitude-first', document(lat_first, 1000.0), 'INVALID_ROUTE_CSV', 'line 1', 'host')
    big_capture = cases.inputs / 'over-1mib.csv'
    big_capture.write_text('lon_deg,lat_deg\n' + '-97.00000000000000000000,49.000000000000000000\n' * 25000)
    c('host-capture-limit', document(big_capture, 1000.0), 'ROUTE_FILE_LIMIT', '$.source', 'host')
    c('native-leg-too-long', document(cases.source('leg-5050km', [V, [-65.980945, 32.159215]]), 50000.0), 'ROUTE_LEG_TOO_LONG', 'leg 1', 'native')
    c('native-row-limit', document(cases.source('rows', [V, [-75.181342, 37.8539]]), 400.0), 'ROUTE_ROW_LIMIT', '$.spacing_m', 'native')
    c('native-total', document(cases.source('total', [V, [-74.713251, 37.59952]] * 3), 100000.0), 'ROUTE_TOTAL_TOO_LONG', '$', 'native')
    c('native-excursion', document(cases.source('excursion', [[-110.0, 74.0], [-50.0, 74.0]]), 10000.0), 'ROUTE_LATITUDE_EXCURSION', 'leg 1', 'native')
    c('native-short', document(cases.source('short', [[10.0, 60.0], [10.0000000722, 60.0000000722]]), 0.1), 'ROUTE_LEG_TOO_SHORT', 'leg 1', 'native')
    return base


def adequacy_injection(directory, base, locations):
    """Every adequacy category fails the whole run with VERIFICATION_INDETERMINATE (no requirements)."""
    near = directory / 'inputs' / 'nearly-closed.csv'
    results = {}
    real_direct, real_inverse, real_rounding = v._direct, g.inverse, g.rounding_estimate
    legs = {(tuple(p), tuple(q)) for p, q in zip([WPG, SELKIRK, LOCKPORT, [-97.1380, 49.8953]], [SELKIRK, LOCKPORT, [-97.1380, 49.8953], WPG])}
    def scaled(selector, factor=5.0):
        def inverse(x1, y1, x2, y2, **kw):
            r = real_inverse(x1, y1, x2, y2, **kw)
            return {**r, 'error_m': factor * contract.tau(r['s']) / 10} if selector((x1, y1), (x2, y2)) else r
        return inverse
    plans = {
        'stationForwardResidual1m': ('direct', lambda *args: {**real_direct(*args), 'residual_m': 1.0}, base, 'stationForward', None),
        'consecutiveInverse5x': ('inverse', scaled(lambda p, q: (p, q) not in legs), base, 'consecutiveInverse', None),
        'legInverse5x': ('inverse', scaled(lambda p, q: (p, q) in legs), base, 'legInverse', None),
        'endpointGapInverse5x': ('inverse', scaled(lambda p, q: (p, q) == (tuple([-97.1380, 49.8953]), tuple(WPG))), near, 'endpointGapInverse', {'endpointGap_m': {'maximum': 100.0}}),
        'roundingModelUnresolved': ('rounding', lambda s: 1.0, base, '', None)}
    for label, (kind, replacement, source, category, requirements) in plans.items():
        try:
            if kind == 'direct':
                v._direct = replacement
            elif kind == 'inverse':
                g.inverse = replacement
            else:
                g.rounding_estimate = replacement
            doc = document(source, 2000.0, **({'requirements': requirements} if requirements else {}))
            target = directory / 'adequacy' / label
            record = outcome(lambda: registry.run(doc, target, locations=locations, timeout=60))
        finally:
            v._direct, g.inverse, g.rounding_estimate = real_direct, real_inverse, real_rounding
        record['nativePids'] = native_pids(target)
        record['result'] = json.loads((target / 'result.json').read_text())['status']
        if record['outcome'] != 'VERIFICATION_INDETERMINATE' or category not in record['message'] or record['result'] != 'failed':
            raise AssertionError(label + ': ' + json.dumps(record, default=str))
        results[label] = record
    return results


def mutants(directory, base, locations):
    """Semantic native-worker mutants installed as the trusted worker on purpose (semantics, not hashes)."""
    worker = a.worker_source()
    swap_all = lambda geod: [("    g = Geod(ellps='WGS84')\n", "    g = Geod(ellps='WGS84')\n    _check = g\n"),
                             ("    return g, {'pyproj'", "    g = Geod(" + geod + ")\n    return g, {'pyproj'"),
                             ("'a': g.a, 'f': g.f,", "'a': _check.a, 'f': _check.f,")]
    # A compromised worker also lies in its readback record (ratio 0), so rejection must come from the host oracle.
    no_readback = [("        if worst > 1:\n            raise Refusal('READBACK_GEODESIC_MISMATCH'", "        worst = 0.0\n        if False:\n            raise Refusal('READBACK_GEODESIC_MISMATCH'")]
    station = "            r['lon'], r['lat'], r['azimuth'] = lo, la, az\n"
    edits = {
        'sphere-everything': (swap_all('a=6371008.7714, f=0.0'), 'GEODESIC_VERIFICATION_FAILED'),
        'grs80-long-legs': (swap_all("ellps='GRS80'"), 'GEODESIC_VERIFICATION_FAILED'),
        'constant-station-azimuth': ([(station, "            r['lon'], r['lat'], r['azimuth'] = lo, la, az1[r['leg'] - 1]\n")], 'GEODESIC_VERIFICATION_FAILED'),
        'lonlat-linear-stations': ([(station, "            t_ = r['offset'] / length[r['leg'] - 1]\n            r['lon'], r['lat'], r['azimuth'] = lons[r['leg'] - 1] + t_ * (lons[r['leg']] - lons[r['leg'] - 1]), lats[r['leg'] - 1] + t_ * (lats[r['leg']] - lats[r['leg'] - 1]), az\n")] + no_readback, 'GEODESIC_VERIFICATION_FAILED'),
        'six-decimal-stations': ([(station, "            r['lon'], r['lat'], r['azimuth'] = round(lo, 6), round(la, 6), az\n")] + no_readback, 'GEODESIC_VERIFICATION_FAILED'),
        'benign-from-leg-end': ([("        slon, slat, saz = g.fwd([lons[r['leg'] - 1] for r in stations], [lats[r['leg'] - 1] for r in stations],\n                                [az1[r['leg'] - 1] for r in stations], [r['offset'] for r in stations],\n                                return_back_azimuth=False)",
                                  "        slon, slat, saz = g.fwd([lons[r['leg']] for r in stations], [lats[r['leg']] for r in stations],\n                                [back[r['leg'] - 1] for r in stations], [length[r['leg'] - 1] - r['offset'] for r in stations],\n                                return_back_azimuth=False)\n        saz = [x + 180.0 for x in saz]")], 'accept'),
    }
    long_route = directory / 'inputs' / 'continental.csv'
    long_route.write_text(csv_text([V, WPG, [-63.5752, 44.6488]]))
    results = {}
    original = a.worker_source
    for label, (changes, expected) in edits.items():
        source = worker
        for old, new in changes:
            if source.count(old) != 1:
                raise AssertionError('mutant edit did not apply: ' + label)
            source = source.replace(old, new)
        doc = document(long_route if label == 'grs80-long-legs' else base, 10000.0 if label == 'grs80-long-legs' else 1000.0)
        target = directory / 'mutants' / label
        try:
            a.worker_source = lambda source=source: source
            record = outcome(lambda: a.run(doc, target, executable=locations['pyproj'], timeout=60))
        finally:
            a.worker_source = original
        record['nativePids'] = native_pids(target)
        if record['outcome'] != expected:
            raise AssertionError(label + ': ' + json.dumps(record, default=str))
        results[label] = {k: record.get(k) for k in ('outcome', 'location', 'message', 'nativePids')}
    return results


def recorded_identity(directory):
    """Recorded locations and commands that a digest refresh must never rewrite."""
    from schemaxis.publication_metadata import MANIFEST
    directory = Path(directory)
    receipt = a.read(directory, 'verification.json')
    manifest = directory / MANIFEST
    return {'artifacts': [{k: v for k, v in item.items() if k != 'sha256'} for item in receipt['artifacts']],
            'executable': receipt.get('executable'),
            'submissions': {s: a.read(directory, s + '-submission.json').get('nativeCommand') for s in a.STAGES},
            'recordedDirectory': json.loads(manifest.read_text()).get('recordedDirectory') if manifest.is_file() else None}


def refresh(directory):
    """Refresh ONLY ordinary digests, as a careless editor or attacker could; never rebase recorded locations.

    Receipt artifact file strings, kinds and order, the receipt executable, native submissions and the
    publication manifest's first recorded origin are preserved (finalise keeps recordedDirectory).
    """
    directory = Path(directory)
    consumed = {n: a.digest(directory, n) for n in ('native-config.json', 'native-worker.py', 'native-result.json', *contract.PUBLICATIONS)}
    atomic_json(directory / 'readback-inputs.json', consumed)
    receipt = a.read(directory, 'verification.json')
    receipt['artifacts'] = [{**item, 'sha256': a.digest(directory, Path(item['file']).name)} for item in receipt['artifacts']]
    receipt['evidence'] = {n: a.digest(directory, n) for n in receipt['evidence']}
    atomic_json(directory / 'verification.json', receipt)
    from schemaxis.publication_metadata import finalise
    finalise(directory)


HOSTILE_EXPECTED = {   # exact intended rejection: code and message fragment
    'summaryStateFlip': ('VERIFICATION_FAILED', 'route summary differs from recomputation'),
    'decisionOutcomeFlip': ('VERIFICATION_FAILED', 'host verification record differs from recomputation'),
    'foreignHostRecord': ('VERIFICATION_FAILED', 'host verification record differs from recomputation'),
    'stationShift1e-8deg': ('GEODESIC_VERIFICATION_FAILED', 'stationPosition exceeds its contract tolerance'),
    'stationShift1e-10deg': ('GEODESIC_VERIFICATION_FAILED', 'stationPosition exceeds its contract tolerance'),
    'readbackTruthyInteger': ('VERIFICATION_FAILED', 'native readback record is malformed or not exact'),
    'runtimeObservationChanged': ('VERIFICATION_FAILED', 'native runtime observation differs'),
    'absoluteWorkerCommand': ('VERIFICATION_FAILED', 'native command or completion differs'),
    'commandWithoutIsolation': ('VERIFICATION_FAILED', 'native command or completion differs'),
    'workerBytesChanged': ('VERIFICATION_FAILED', 'trusted native worker differs'),
    'privateHomeWritten': ('VERIFICATION_FAILED', 'private native home must remain an empty'),
    'capturedSourceRehashed': ('VERIFICATION_FAILED', 'native configuration differs from the captured route'),
}


def hostile(directory, baseline, variant):
    """Hostile saved evidence on canonical export copies; digests refreshed, recorded locations preserved."""
    from schemaxis.publication_metadata import MANIFEST
    baseline_manifest = json.loads((Path(baseline) / MANIFEST).read_text())
    first_origin = baseline_manifest.get('recordedDirectory') or str(Path(baseline).absolute())
    results = {}
    def mutate(label, change, expected, refreshed=True):
        target = directory / 'hostile' / label
        export_run(baseline, target)
        change(target)
        recorded = recorded_identity(target)
        if refreshed:
            refresh(target)
        after = recorded_identity(target)
        if after != recorded or after['recordedDirectory'] != first_origin:
            raise AssertionError(label + ': refresh changed recorded identity: ' + json.dumps({'before': recorded, 'after': after}, default=str)[:1500])
        if any(not Path(item['file']).is_relative_to(first_origin) for item in after['artifacts']):
            raise AssertionError(label + ': recorded artifacts no longer name the original run')
        record = outcome(lambda: registry.verify(target))
        code, fragment = expected
        if record['outcome'] != code or fragment not in record.get('message', ''):
            raise AssertionError(label + ': ' + json.dumps(record, default=str))
        results[label] = {**{k: record.get(k) for k in ('outcome', 'location', 'message')},
                          'recordedArtifactFiles': [item['file'] for item in after['artifacts']],
                          'recordedDirectory': after['recordedDirectory'], 'submissions': after['submissions'], 'digestsRefreshed': refreshed}
    def edit_json(name, fn):
        def apply(t):
            value = a.read(t, name); fn(value); atomic_json(t / name, value)
        return apply
    def shift(t, delta=1e-8):
        record = a.read(t, 'native-result.json')
        row = next(r for r in record['result']['rows'] if r['kind'] == 1)
        row['lat'] += delta
        from schemaxis.adaptors.pyproj import native_worker
        for name, text in native_worker.publications(record['result']).items():
            (t / name).write_text(text)
        atomic_json(t / 'native-result.json', record)
    def capture(t):
        data = (t / 'source.csv').read_bytes().replace(b'-96.937', b'-96.938')
        (t / 'source.csv').write_bytes(data)
        atomic_json(t / 'capture.json', {**a.read(t, 'capture.json'), 'sha256': hashlib.sha256(data).hexdigest()})
    changes = {
        'summaryStateFlip': edit_json('route-summary.json', lambda x: x['requirements']['totalLength_m'].update(state='unmet')),
        'decisionOutcomeFlip': edit_json('route-verification.json', lambda x: x['decision'].update(outcome='requirementsUnmet')),
        'foreignHostRecord': lambda t: shutil.copy(Path(variant) / 'route-verification.json', t / 'route-verification.json'),
        'stationShift1e-8deg': shift,
        'stationShift1e-10deg': lambda t: shift(t, 1e-10),
        'readbackTruthyInteger': edit_json('readback.json', lambda x: x.update(publicationsExact=1)),
        'runtimeObservationChanged': edit_json('native-result.json', lambda x: x['runtime'].update(pyproj='3.7.2')),
        'absoluteWorkerCommand': edit_json('compute-submission.json', lambda x: x.update(nativeCommand=[x['nativeCommand'][0], '-I', '-B', str(Path(baseline) / 'native-worker.py'), 'compute'])),
        'commandWithoutIsolation': edit_json('readback-submission.json', lambda x: x.update(nativeCommand=[x['nativeCommand'][0], '-B', 'native-worker.py', 'readback'])),
        'workerBytesChanged': lambda t: (t / 'native-worker.py').write_text((t / 'native-worker.py').read_text() + '# altered\n'),
        'privateHomeWritten': lambda t: (t / a.HOME / 'cache.db').write_text('x'),
        'capturedSourceRehashed': capture,
    }
    for label, change in changes.items():
        mutate(label, change, HOSTILE_EXPECTED[label])
    # Valid controls: an untouched canonical export, and one whose digests were refreshed with locations preserved.
    mutate('controlUnmodifiedExport', lambda t: None, ('accept', ''), refreshed=False)
    mutate('controlDigestsRefreshedLocationsPreserved', lambda t: None, ('accept', ''))
    return results


def accepted(label, action):
    """Mandatory acceptance: any refusal fails the qualification (diagnostics are kept in the message)."""
    record = outcome(action)
    if record['outcome'] != 'accept':
        raise AssertionError(label + ' was refused: ' + json.dumps(record, default=str)[:1500])
    return record['result']


def refused_with(label, action, code, fragment=''):
    record = outcome(action)
    if record['outcome'] != code or fragment not in record.get('message', ''):
        raise AssertionError(label + ' expected ' + code + ': ' + json.dumps(record, default=str)[:1500])
    return {k: record[k] for k in ('outcome', 'location', 'message')}


def job_attempts(root):
    """Saved job identity of a scheduled workflow, resolved inside its own (possibly exported) tree."""
    from schemaxis.run_paths import owned_path
    saved = json.loads((Path(root) / 'result.json').read_text())
    return [(job, owned_path(root, job['directory'], kind='directory')) for job in saved['jobs']]


def forge_hashes(root, claimed):
    """Forge BOTH the workflow result.json and every job.json to claim different source bytes."""
    saved = json.loads((Path(root) / 'result.json').read_text())
    for job, attempt in job_attempts(root):
        forged = {path: claimed for path in job['inputHashes']}
        record = json.loads((attempt / 'job.json').read_text())
        record['inputHashes'] = forged
        (attempt / 'job.json').write_text(json.dumps(record))
    for job in saved['jobs']:
        job['inputHashes'] = {path: claimed for path in job['inputHashes']}
    (Path(root) / 'result.json').write_text(json.dumps(saved))


def workflows(directory, locations):
    """Scheduled workflow and common study: reuse, canonical export/re-export, physical source removal,
    saved verification after a source change, forged result.json + job.json input hashes, fresh resume."""
    from schemaxis.parallel import retained_inputs
    source = directory / 'workflow-input.csv'
    source.write_text(csv_text([WPG, SELKIRK, LOCKPORT]))
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    identity = {str(source): original}
    graph = {'version': 'schemaxis.workflow/1', 'operations': [
        {'id': 'coarse', 'document': document(source, 1000.0, requirements={'totalLength_m': {'maximum': 50000.0}})},
        {'id': 'fine', 'document': document(source, 250.0)}]}
    root = directory / 'workflow'
    first = workflow.execute(graph, root, locations=locations, timeout=60)
    accepted('workflow verify', lambda: workflow.verify(root))
    second = workflow.execute(graph, root, locations=locations, timeout=60, resume=True)
    assert all(j.get('reused') for j in second['jobs']), second['jobs']
    study = document(source, {'$axis': 'spacing'})
    study['axes'] = [{'name': 'spacing', 'values': [1000.0, 2000.0]}]
    states = a.run(study, directory / 'study', executable=locations['pyproj'], timeout=60)
    assert len(states['states']) == 2
    accepted('study verify', lambda: registry.verify(directory / 'study'))
    for item in directory.rglob('native-result.json'):
        native_pids(item.parent)
    before = [(job['effective'], job['handoffs'], job['inputHashes'], attempt.name) for job, attempt in job_attempts(root)]
    assert all(h == identity for _, _, h, _ in before), before
    # Canonical schema-aware export and re-export of both the workflow and the study.
    copies = {}
    for kind, target in (('workflow', root), ('study', directory / 'study')):
        first_copy, second_copy = directory / 'exports' / (kind + '-export'), directory / 'exports' / (kind + '-reexport')
        export_run(target, first_copy)
        export_run(first_copy, second_copy)
        copies[kind] = (target, first_copy, second_copy)
    check = {'workflow': workflow.verify, 'study': registry.verify}
    # Physical removal of the original source: retained captures alone must verify.
    removed = source.read_bytes()
    source.unlink()
    removal = {}
    for kind, trees in copies.items():
        for tree in trees:
            accepted(kind + ' verify after source removal: ' + tree.name, lambda: check[kind](tree))
            removal[kind + ':' + tree.name] = 'verified'
    for tree in copies['workflow']:
        for job, attempt in job_attempts(tree):
            assert job['inputHashes'] == identity and a.retainedInputs(attempt, job['effective']) == identity, (tree, job['id'])
    for tree in copies['study']:
        assert retained_inputs(tree, study) == identity, tree
    reuse_refused = refused_with('reuse after removal', lambda: a.reusableInputs(graph['operations'][0]['document']), 'INVALID_ROUTE_SOURCE')
    # Changed current source: saved verification still uses the authentic retained capture.
    source.write_bytes(removed.replace(b'-96.937', b'-96.936'))
    fresh = hashlib.sha256(source.read_bytes()).hexdigest()
    assert fresh != original
    for kind, trees in copies.items():
        for tree in trees:
            accepted(kind + ' verify after source change: ' + tree.name, lambda: check[kind](tree))
    # Forged result.json AND job.json hashes claiming the new bytes fail saved verification.
    forged = {}
    for tree in (root, copies['workflow'][2]):
        forge_hashes(tree, fresh)
        forged[tree.name] = refused_with('forged hashes ' + tree.name, lambda: workflow.verify(tree), 'VERIFICATION_FAILED', 'verified retained inputs')
    # Resume on the forged original: the stale attempts must not be reused; fresh attempts capture the new bytes.
    third = workflow.execute(graph, root, locations=locations, timeout=60, resume=True)
    assert not any(j.get('reused') for j in third['jobs']), third['jobs']
    for item in root.rglob('native-result.json'):
        native_pids(item.parent)
    accepted('workflow verify after fresh attempts', lambda: workflow.verify(root))
    after = [(job['effective'], job['handoffs'], job['inputHashes'], attempt.name) for job, attempt in job_attempts(root)]
    for (effective, handoffs, _, old), (effective2, handoffs2, hashes2, new), (job, attempt) in zip(before, after, job_attempts(root)):
        assert effective2 == effective and handoffs2 == handoffs and effective2['source'] == str(source), job['id']
        assert hashes2 == {str(source): fresh} == a.retainedInputs(attempt, job['effective']) and new != old, (job['id'], old, new)
    blocked = {'version': 'schemaxis.workflow/1', 'operations': [
        {'id': 'route', 'document': document(source, 1000.0, requirements={'totalLength_m': {'maximum': 1000.0}})},
        {'id': 'gis', 'document': {'version': 'schemaxis.qgis/1', 'nodes': [{'id': 'legs', 'filter': 'readVector', 'options': {'file': {'$artifact': 'route', 'index': 3}}}], 'output': 'legs', 'preview': False}}]}
    stopped = outcome(lambda: workflow.execute(blocked, directory / 'workflow-blocked', locations=locations, timeout=60))
    for item in (directory / 'workflow-blocked').rglob('native-result.json'):
        native_pids(item.parent)
    consumers = sorted(str(p.relative_to(directory)) for p in (directory / 'workflow-blocked').rglob('*.gpkg'))
    assert stopped['outcome'] in ('ROUTE_REQUIREMENT_NOT_MET', 'VERIFICATION_FAILED', 'RUNNER_FAILED', 'INPUT_CHANGED') or 'ROUTE_REQUIREMENT_NOT_MET' in stopped.get('message', ''), stopped
    assert not consumers, consumers
    planned = {}
    for name in ('pyproj-qgis-workflow.json', 'pyproj-calc-workflow.json'):
        graph_ = json.loads((EXAMPLES / name).read_text())
        graph_['operations'][0]['document']['source'] = str(source)
        planned[name] = bool(workflow.validate(graph_))
    return {'jobs': len(first['jobs']), 'unchangedReused': True, 'studyStates': 2,
            'verifiedAfterSourceRemoval': removal, 'reuseAfterRemoval': reuse_refused,
            'verifiedAfterSourceChange': 'original, export and re-export of workflow and study',
            'forgedResultAndJobHashes': forged, 'resumeAfterForgery': {'reused': False, 'attempts': {j['id']: [o, n] for j, (_, _, _, o), (_, _, _, n) in zip(third['jobs'], before, after)}},
            'identity': {'source': str(source), 'originalSha256': original, 'freshSha256': fresh, 'effectiveAndHandoffsUnchanged': True},
            'unmetProducerBlocks': stopped, 'consumerOutputs': consumers, 'hostPlannedHandoffs': planned,
            'scope': 'two independent pyproj routes; no native cross-app consumer was run'}


def portable_export(directory, locations):
    """Canonical export and re-export; full registry.verify of every copy is mandatory (no native-only fallback)."""
    root = directory / 'export'
    inputs = root / 'input'
    inputs.mkdir(parents=True)
    report = {}
    exported = {}
    for name, example, csv_name in (('baseline', 'pyproj-winnipeg-route.json', 'pyproj-winnipeg-route.csv'),
                                    ('variant', 'pyproj-winnipeg-loop.json', 'pyproj-winnipeg-loop.csv')):
        source = inputs / (name + '.csv')
        source.write_bytes((EXAMPLES / csv_name).read_bytes())
        doc = json.loads((EXAMPLES / example).read_text()); doc['source'] = str(source)
        registry.run(doc, root / name, locations=locations, timeout=60)
        native_pids(root / name)
        commands = [a.read(root / name, s + '-submission.json')['nativeCommand'] for s in a.STAGES]
        assert commands == [a.command(locations['pyproj'], s) for s in a.STAGES], commands
        export_run(root / name, root / 'exported' / name)
        export_run(root / 'exported' / name, root / 'reexported' / name)
        exported[name] = (root / 'exported' / name, root / 'reexported' / name, doc, {doc['source']: hashlib.sha256(source.read_bytes()).hexdigest()})
    for path in inputs.iterdir():
        path.unlink()
    for name, (target, again, doc, identity) in exported.items():
        record = {'savedVerification': accepted(name + ' exported registry.verify', lambda: registry.verify(target)),
                  'reexportSavedVerification': accepted(name + ' re-exported registry.verify', lambda: registry.verify(again)),
                  'nativeLayer': accepted(name + ' exported native verify', lambda: registry._verify_native(target, doc)),
                  'originalAfterSourceRemoval': accepted(name + ' original registry.verify', lambda: registry.verify(root / name)),
                  'reuseAfterSourceRemoval': refused_with(name + ' reuse', lambda: a.reusableInputs(doc), 'INVALID_ROUTE_SOURCE')['outcome'],
                  'retainedInputs': {'exported': a.retainedInputs(target, doc), 'reexported': a.retainedInputs(again, doc)}}
        assert record['retainedInputs'] == {'exported': identity, 'reexported': identity}, record
        report[name] = record
    report['savedVerificationLayer'] = 'mandatory full registry.verify (shared publication metadata included) of export and re-export'
    report['hostile'] = hostile(root, exported['baseline'][0], exported['variant'][0])
    return report


def cli(directory, locations):
    doc = json.loads((EXAMPLES / 'pyproj-winnipeg-route.json').read_text())
    doc['source'] = str(EXAMPLES / 'pyproj-winnipeg-route.csv')
    path = directory / 'cli-document.json'
    path.write_text(json.dumps(doc))
    env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src')}
    runs = {}
    for label, argv in (('run', [sys.executable, '-B', '-m', 'schemaxis', 'run', str(path), '--output-directory', str(directory / 'cli-run'),
                                 '--pyproj', locations['pyproj'], '--timeout', '60']),
                        ('verify', [sys.executable, '-B', '-m', 'schemaxis', 'verify', str(directory / 'cli-run')])):
        done = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=300, start_new_session=True)
        runs[label] = {'argv': argv[1:], 'exit': done.returncode, 'stdoutTail': done.stdout[-600:], 'stderrTail': done.stderr[-600:]}
        assert done.returncode == 0, runs[label]
    native_pids(directory / 'cli-run')
    return runs


def lifecycle(directory, locations):
    """In-flight native timeout/cancel with owned children, and a deadline expiring in host verification."""
    doc = document(EXAMPLES / 'pyproj-winnipeg-route.csv', 1000.0)
    wrapper, marker = directory / 'slow-runtime.py', directory / 'slow.pid'
    wrapper.write_text('#!' + sys.executable + '\nimport os,time\nfrom pathlib import Path\nPath(' + repr(str(marker)) + ').write_text(str(os.getpid()))\ntime.sleep(30)\n')
    wrapper.chmod(0o700)
    result = {}
    for action in ('timeout', 'cancel'):
        if marker.exists():
            marker.unlink()
        event = threading.Event()
        def trigger():
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            if marker.exists():
                event.set()
        thread = threading.Thread(target=trigger, daemon=True) if action == 'cancel' else None
        if thread:
            thread.start()
        with allocation({'threads': 1, 'ranks': 1}, event):
            record = outcome(lambda: a.run(doc, directory / ('inflight-' + action), executable=str(wrapper), timeout=8 if thread else .6))
        if thread:
            thread.join(6)
        pid = int(marker.read_text())
        try:
            os.kill(pid, 0)
            alive = True
        except ProcessLookupError:
            alive = False
        assert record['outcome'] == ('RUNNER_CANCELLED' if thread else 'RUNNER_TIMED_OUT') and not alive, (record, alive)
        result[action] = {'outcome': record['outcome'], 'childPid': pid, 'childAlive': alive}
    # Host-verification deadline: native completes quickly, the host verifier of ~10000 rows does not.
    big = directory / 'inputs' / 'near-row-limit.csv'
    measured = directory / 'cases' / 'near-row-limit'
    native_seconds = sum(json.loads((measured / (s + '-submission.json')).read_text())['seconds'] for s in a.STAGES)
    budget = native_seconds + 0.4      # enough for both native stages, not for host verification of ~10000 rows
    target = directory / 'deadline-in-host-verification'
    record = outcome(lambda: registry.run(document(big, 401.0), target, locations=locations, timeout=budget))
    native_pids(target)
    saved = json.loads((target / 'result.json').read_text())
    assert record['outcome'] == 'RUNNER_TIMED_OUT' and saved['status'] == 'failed', (record, saved)
    result['hostVerificationDeadline'] = {'outcome': record['outcome'], 'message': record['message'], 'budgetSeconds': budget, 'measuredNativeSeconds': native_seconds,
                                         'nativeStagesCompleted': sorted(p.name for p in target.glob('*-submission.json')),
                                         'routeSummaryWritten': (target / 'route-summary.json').exists(), 'resultStatus': saved['status']}
    return result


def consumers(directory):
    from schemaxis import tabular
    from schemaxis.adaptors.gnuplot import adaptor as gnuplot
    from schemaxis.adaptors.qgis import adaptor as qgis
    target = directory / 'export' / 'baseline'
    stations = (target / 'stations.csv').read_bytes()
    rows = tabular.parse_csv(stations)['rows']
    units = {'row': '1', 'chainage_m': 'm', 'lon_deg': 'deg', 'lat_deg': 'deg', 'leg': '1', 'offset_m': 'm', 'azimuth_deg': 'deg', 'kind': '1', 'waypoint': '1'}
    xs, ys = [r[1] for r in rows], [r[3] for r in rows]
    plot = {'version': 'schemaxis.gnuplot/1', 'operation': 'plot', 'title': 'Route profile', 'source': str(target / 'stations.csv'),
            'columns': [{'name': n, 'unit': u} for n, u in units.items()], 'series': [{'label': 'latitude', 'x': 'chainage_m', 'y': 'lat_deg'}],
            'xAxis': {'label': 'chainage', 'unit': 'm', 'range': [min(xs) - 1, max(xs) + 1]},
            'yAxis': {'label': 'latitude', 'unit': 'deg', 'range': [min(ys) - 0.01, max(ys) + 0.01]}}
    vector = {'version': 'schemaxis.qgis/1', 'nodes': [{'id': 'legs', 'filter': 'readVector', 'options': {'file': str(target / 'route.geojson')}}], 'output': 'legs'}
    return {'scope': 'host contracts only; no native consumer launched',
            'calcStations': len(tabular.parse_csv(stations, minimum=2)['rows']),
            'calcLegs': len(tabular.parse_csv((target / 'legs.csv').read_bytes(), minimum=2)['rows']),
            'gnuplotChainageProfile': len(gnuplot.table(stations, gnuplot.plan(plot))),
            'qgisRouteGeoJSON': bool(qgis.plan(vector)) and bool(qgis.reusableInputs(vector))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pyproj', type=Path, help='Absolute isolated Python with pyproj 3.8.0 / PROJ 9.9.0 (required except for --phase hostile)')
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--phase', choices=('full', 'portability', 'hostile'), default='full',
                        help='full (default) qualification; portability: the workflow/study/export acceptance functions; '
                             'hostile: host-only hostile saved-evidence gate on canonical copies of existing verified runs')
    parser.add_argument('--baseline-run', type=Path, help='--phase hostile: verified baseline route run (read only; copied canonically)')
    parser.add_argument('--variant-run', type=Path, help='--phase hostile: verified variant route run (read only; copied canonically)')
    args = parser.parse_args()
    if args.phase == 'hostile' and not (args.baseline_run and args.variant_run):
        parser.error('--phase hostile needs --baseline-run and --variant-run')
    if args.phase != 'hostile' and not args.pyproj:
        parser.error('--pyproj is required for native phases')
    directory = args.output_directory.absolute()
    directory.mkdir(parents=True, exist_ok=False)
    locations = {'pyproj': str(args.pyproj.absolute())} if args.pyproj else {}
    report = {'verified': False, 'phase': args.phase, 'sourceDigests': a.implementation()}
    try:
        if args.phase == 'hostile':
            copies = {}
            for name, run in (('baseline', args.baseline_run), ('variant', args.variant_run)):
                copies[name] = directory / 'retained-copies' / name
                export_run(run.absolute(), copies[name])
                accepted(name + ' canonical copy of the retained run', lambda: registry.verify(copies[name]))
            report['hostile'] = hostile(directory, copies['baseline'], copies['variant'])
            report['verified'] = True
            return
        if args.phase == 'portability':
            report['workflow'] = workflows(directory, locations)
            report['portableExport'] = portable_export(directory, locations)
            report['consumers'] = consumers(directory)
            report['verified'] = True
            return
        receipt = qualify(a.VERSION, directory / 'kit', native=True, root=ROOT, locations=locations, timeout=60, wall_timeout=180)
        for case in receipt['cases']:
            native_pids(directory / 'kit' / case['id'])
        report['kit'] = {'verified': receipt['verified'], 'cases': [c['id'] for c in receipt['cases']], 'lifecycle': receipt['lifecycle'],
                         'checks': {c['id']: len(c['checks']) for c in receipt['cases']}, 'integrity': {c['id']: len(c['integrity']) for c in receipt['cases']}}
        cases = Cases(directory, locations)
        base = semantic_cases(cases)
        report['cases'] = cases.records
        report['adequacyInjection'] = adequacy_injection(directory, base, locations)
        report['mutants'] = mutants(directory, base, locations)
        report['workflow'] = workflows(directory, locations)
        report['portableExport'] = portable_export(directory, locations)
        report['cli'] = cli(directory, locations)
        report['lifecycle'] = lifecycle(directory, locations)
        report['consumers'] = consumers(directory)
        report['verified'] = True
    finally:
        alive = []
        for pid in sorted(set(PIDS)):
            try:
                os.kill(pid, 0)
                alive.append(pid)
            except ProcessLookupError:
                pass
        report['nativeProcesses'] = {'pids': sorted(set(PIDS)), 'count': len(set(PIDS)), 'aliveAfterRun': alive}
        if report['sourceDigests'] != a.implementation():
            report['verified'] = False
            report['sourceChangedDuringQualification'] = True
        atomic_json(directory / 'acceptance.json', report)
        print(json.dumps({'verified': report['verified'], 'phase': args.phase, 'cases': len(report.get('cases', [])), 'nativeProcesses': len(set(PIDS))}, indent=2))


if __name__ == '__main__':
    main()
