# Copyright (C) 2026 David L F Gaden
"""Host semantics of pyproj route chainage; never imports pyproj.

Full run/verify plumbing uses a FAKE runtime: a wrapper interpreter that injects a standard-library
`pyproj` stand-in backed by the adaptor's own oracle. Native == oracle there, so these tests check
contracts, faults, hostile evidence, decisions and lifecycle, not numerical independence; the real
pyproj 3.8.0 / PROJ 9.9.0 runtime is exercised by tools/qualify_pyproj.py.
"""
import copy
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest

from schemaxis.adaptors.pyproj import adaptor as a, anchors, contract, geodesy as g, native_worker as w, verifier as v
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / 'examples/schemaxis'
WPG = [-97.1384, 49.8951]
SELKIRK = [-96.8845, 50.1436]


def code(action):
    try:
        action()
    except SchemaxisError as error:
        return error.fault.code, error.fault.location
    return 'accepted', None


def document(source, spacing=1000.0, **extra):
    doc = {'version': a.VERSION, 'operation': a.OPERATION, 'source': str(source), 'ellipsoid': 'WGS84',
           'coordinateOrder': 'lonLat', 'spacing_m': spacing}
    doc.update(extra)
    return doc


def csv_bytes(points, names=None):
    if names:
        return ('name,lon_deg,lat_deg\n' + ''.join(f'{n},{lon!r},{lat!r}\n' for n, (lon, lat) in zip(names, points))).encode()
    return ('lon_deg,lat_deg\n' + ''.join(f'{lon!r},{lat!r}\n' for lon, lat in points)).encode()


class OracleGeod:
    """In-process stand-in for pyproj.Geod built on the stdlib oracle (test fixture only)."""
    a, f, sphere = 6378137.0, 1 / 298.257223563, False

    def inv(self, lons1, lats1, lons2, lats2, return_back_azimuth=True):
        az1, az2, s = [], [], []
        for x1, y1, x2, y2 in zip(lons1, lats1, lons2, lats2):
            r = g.inverse(x1, y1, x2, y2)
            end = g.wrap180(r['azi2'])
            az1.append(g.wrap180(r['azi1'])); s.append(r['s'])
            az2.append(g.wrap180(end - 180.0) if return_back_azimuth else end)
        return az1, az2, s

    def fwd(self, lons, lats, az, dist, return_back_azimuth=True):
        lo, la, ba = [], [], []
        for x, y, b, d in zip(lons, lats, az, dist):
            r = g.direct(x, y, b, d)
            lo.append(r['lon']); la.append(r['lat'])
            ba.append(g.wrap180(r['azi2'] - 180.0) if return_back_azimuth else g.wrap180(r['azi2']))
        return lo, la, ba


def oracle_provider():
    return OracleGeod(), {'pyproj': '3.8.0', 'proj': '9.9.0', 'a': OracleGeod.a, 'f': OracleGeod.f, 'network': False, 'python': '3.12.15', 'pid': 1}


def synthetic(points, spacing, closed=False, gap=False, names=None):
    """Native-shaped tables built in process with the oracle stand-in (clean reference publication)."""
    names = names or [f'WP{i + 1}' for i in range(len(points))]
    p = contract.validate(document('/x/route.csv', spacing, closed=closed, **({'requirements': {'endpointGap_m': {'maximum': 5e6}}} if gap else {})))
    config = contract.native_config(p, points, names)
    _runtime, result = w.compute(config, oracle_provider)
    texts = w.publications(result)
    stations = contract.parse_table(texts['stations.csv'].encode(), contract.STATION_COLUMNS, 'stations.csv')
    legs = contract.parse_table(texts['legs.csv'].encode(), contract.LEG_COLUMNS, 'legs.csv')
    route, route_names = a.route_points(config)
    return p, stations, legs, route, route_names, result, {k: json.loads(texts[k]) for k in ('stations.geojson', 'route.geojson')}


FAKE_PYPROJ = '''"""Standard-library pyproj stand-in for host tests only (oracle-backed)."""
import importlib.util
_spec = importlib.util.spec_from_file_location('_oracle', {geodesy!r})
_g = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_g)
__version__ = '3.8.0'
proj_version_str = '9.9.0'
from . import network
LIE = {lie!r}


class Geod:
    def __init__(self, ellps=None, **kw):
        self.a, self.f, self.sphere = 6378137.0, 1 / 298.257223563, False

    def inv(self, lons1, lats1, lons2, lats2, return_back_azimuth=True):
        az1, az2, s = [], [], []
        for x1, y1, x2, y2 in zip(lons1, lats1, lons2, lats2):
            try:
                r = _g.inverse(x1, y1, x2, y2)
            except _g.OracleOutsideDomain:   # real pyproj has no cap; the stand-in falls back to Vincenty
                r = _g.vincenty_inverse(x1, y1, x2, y2)
            end = _g.wrap180(r['azi2'])
            az1.append(_g.wrap180(r['azi1'])); s.append(r['s'] * LIE)
            az2.append(_g.wrap180(end - 180.0) if return_back_azimuth else end)
        return az1, az2, s

    def fwd(self, lons, lats, az, dist, return_back_azimuth=True):
        lo, la, ba = [], [], []
        for x, y, b, d in zip(lons, lats, az, dist):
            r = _g.direct(x, y, b, d / LIE)
            lo.append(r['lon']); la.append(r['lat'])
            ba.append(_g.wrap180(r['azi2'] - 180.0) if return_back_azimuth else _g.wrap180(r['azi2']))
        return lo, la, ba
'''
FAKE_NETWORK = '_on = [True]\ndef set_network_enabled(value=True):\n    _on[0] = bool(value)\ndef is_network_enabled():\n    return _on[0]\n'
WRAPPER = '''#!{python}
import runpy, sys
sys.path.insert(0, {fake!r})
sys.version = '3.12.15 (fake oracle-backed runtime for host tests)'
args = [x for x in sys.argv[1:] if x not in ('-I', '-B')]
sys.argv = args
runpy.run_path(args[0], run_name='__main__')
'''


def fake_runtime(directory, lie=1.0):
    directory = Path(directory)
    package = directory / 'fake' / 'pyproj'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text(FAKE_PYPROJ.format(geodesy=str(Path(g.__file__)), lie=lie))
    (package / 'network.py').write_text(FAKE_NETWORK)
    wrapper = directory / 'fake-python'
    wrapper.write_text(WRAPPER.format(python=sys.executable, fake=str(directory / 'fake')))
    wrapper.chmod(0o700)
    return str(wrapper)


def recorded_identity(directory):
    """Recorded artifact locations, executable, native commands and manifest origin (never rewritten by refresh)."""
    from schemaxis.publication_metadata import MANIFEST
    directory = Path(directory)
    receipt = a.read(directory, 'verification.json')
    return {'artifacts': [{k: v for k, v in item.items() if k != 'sha256'} for item in receipt['artifacts']],
            'executable': receipt['executable'],
            'submissions': {s: a.read(directory, s + '-submission.json')['nativeCommand'] for s in a.STAGES},
            'recordedDirectory': json.loads((directory / MANIFEST).read_text()).get('recordedDirectory')}


def refresh(directory):
    """Refresh ONLY ordinary digests a careless editor or attacker could refresh; recorded locations are preserved."""
    directory = Path(directory)
    consumed = {n: a.digest(directory, n) for n in ('native-config.json', 'native-worker.py', 'native-result.json', *contract.PUBLICATIONS)}
    atomic_json(directory / 'readback-inputs.json', consumed)
    receipt = a.read(directory, 'verification.json')
    receipt['artifacts'] = [{**item, 'sha256': a.digest(directory, Path(item['file']).name)} for item in receipt['artifacts']]
    receipt['evidence'] = {n: a.digest(directory, n) for n in receipt['evidence']}
    atomic_json(directory / 'verification.json', receipt)
    from schemaxis.publication_metadata import finalise
    finalise(directory)


class Contract(unittest.TestCase):
    def test_schema_parity_and_immutable_planning(self):
        schema = a.schema()
        self.assertEqual(set(schema['properties']), {'version', 'operation', *contract.OPTIONS})
        self.assertEqual(set(schema['required']), {'version', 'operation', 'source', 'ellipsoid', 'coordinateOrder', 'spacing_m'})
        doc = document('/abs/route.csv', 1000, requirements={'totalLength_m': {'maximum': 50000}})
        before = copy.deepcopy(doc)
        p = a.plan(doc)
        self.assertEqual(doc, before)
        self.assertIs(p['closed'], False)
        self.assertEqual((type(p['spacing_m']), type(p['requirements']['totalLength_m']['maximum'])), (float, float))
        self.assertEqual(a.plan(doc), p)

    def test_plan_faults_are_located(self):
        cases = {
            'UNSUPPORTED_ELLIPSOID': document('/abs/r.csv', ellipsoid='sphere'),
            'INVALID_ARGUMENT': document('/abs/r.csv', coordinateOrder='latLon'),
            'INVALID_ROUTE_SOURCE': document('relative.csv'),
            'REQUIREMENT_NOT_APPLICABLE': document('/abs/r.csv', closed=True, requirements={'endpointGap_m': {'maximum': 1}}),
            'INVALID_REQUIREMENT': document('/abs/r.csv', requirements={'totalLength_m': {'minimum': 5, 'maximum': 5}}),
            'UNKNOWN_ARGUMENT': {**document('/abs/r.csv'), 'densify': True}}
        for expected, doc in cases.items():
            self.assertEqual(code(lambda: a.plan(doc))[0], expected, doc)
        self.assertEqual(code(lambda: a.plan(document('/abs/r.csv', 0.05)))[0], 'INVALID_ARGUMENT')
        self.assertEqual(code(lambda: a.plan(document('/abs/r.csv', True)))[0], 'INVALID_ARGUMENT')
        self.assertEqual(code(lambda: a.plan(document('/abs/r.csv', requirements={'totalLength_m': {}})))[0], 'INVALID_REQUIREMENT')
        self.assertEqual(code(lambda: a.plan(document('/abs/r.csv', closed=True, requirements={'endpointGap_m': {'maximum': 1}}))),
                         ('REQUIREMENT_NOT_APPLICABLE', '$.requirements.endpointGap_m'))

    def test_strict_waypoint_csv(self):
        good = b'lon_deg,lat_deg\n-97.0,49.0\n-96.0,49.0\n'
        cases = [(b'lat_deg,lon_deg\n49,-97\n49,-96\n', 'INVALID_ROUTE_CSV', 'line 1'),
                 (good.replace(b'-97.0', b'nan'), 'INVALID_ROUTE_CSV', 'line 2'),
                 (good.replace(b'-97.0', b'1e400'), 'INVALID_ROUTE_CSV', 'line 2'),
                 (good.replace(b'-97.0', b' -97.0'), 'INVALID_ROUTE_CSV', 'line 2'),
                 (good.replace(b'49.0\n-96', b'80.0\n-96'), 'UNSUPPORTED_GEOGRAPHY', 'line 2'),
                 (good.replace(b'-97.0', b'180'), 'UNSUPPORTED_GEOGRAPHY', 'line 2'),
                 (b'lon_deg,lat_deg\n-97.0,49.0\n-97.0,49.0\n', 'ROUTE_COINCIDENT_WAYPOINTS', 'line 3'),
                 (b'lon_deg,lat_deg\n-97.0,49.0\n\n-96.0,49.0\n', 'INVALID_ROUTE_CSV', 'line 3'),
                 (b'name,lon_deg,lat_deg\nA";x,-97,49\nB,-96,49\n', 'INVALID_ROUTE_CSV', 'line 2'),
                 (b'lon_deg,lat_deg\n-97.0,49.0\n', 'ROUTE_WAYPOINT_LIMIT', '$.source'),
                 (b'lon_deg,lat_deg\n' + b'-97.00000000000000000000,49.000000000000000000\n' * 25000, 'ROUTE_FILE_LIMIT', '$.source')]
        for data, expected, where in cases:
            self.assertEqual(code(lambda: contract.parse_waypoints(data)), (expected, where), data[:40])
        points, names = contract.parse_waypoints(b'name,lon_deg,lat_deg\nWinnipeg City Hall,-97.1384,49.8951\nSelkirk,-96.8845,50.1436\n')
        self.assertEqual((points, names), ([WPG, SELKIRK], ['Winnipeg City Hall', 'Selkirk']))

    def test_conclusive_host_prechecks(self):
        p = contract.validate(document('/abs/r.csv'))
        gap = contract.validate(document('/abs/r.csv', 100000.0, requirements={'endpointGap_m': {'maximum': 1}}))
        cases = [(p, [[179.5, -17.0], [-179.5, -17.0]], ('UNSUPPORTED_GEOGRAPHY', 'leg 1')),
                 (p, [WPG, SELKIRK, WPG], ('ROUTE_CLOSURE_AMBIGUOUS', '$.source')),
                 (contract.validate(document('/abs/r.csv', 0.5)), [WPG, [-97.1384, 49.98505]], ('ROUTE_ROW_LIMIT', '$.spacing_m')),
                 (p, [[10.0, 60.0], [10.0, 60.00000001]], ('ROUTE_LEG_TOO_SHORT', 'leg 1')),
                 (gap, [[-97.0, 49.9], [-70.0, 30.0], [-40.0, 15.0], [0.0, 0.0], [30.0, -10.0]], ('ENDPOINT_GAP_OUTSIDE_DOMAIN', contract.GAP)),
                 (gap, [[179.5, 70.0], [130.0, 70.0], [80.0, 70.0], [30.0, 70.0], [-20.0, 70.0], [-70.0, 70.0], [-120.0, 70.0], [-179.5, 70.0]],
                  ('ENDPOINT_GAP_OUTSIDE_DOMAIN', contract.GAP))]
        for prepared, points, expected in cases:
            self.assertEqual(code(lambda: contract.native_config(prepared, points, ['n'] * len(points))), expected, points[:2])
        config = contract.native_config(p, [WPG, SELKIRK], ['a', 'b'])
        self.assertIs(config['endpointGap'], False)

    def test_exact_merge_rule_and_presentation(self):
        length = 33092.269933878
        _, exact = contract.expected_rows([length], length / 2)
        self.assertEqual([r['kind'] for r in exact], [3, 1, 3])
        def spacing_for(target):
            sp = target / 3
            while 3 * sp != target:
                sp = math.nextafter(sp, math.inf if 3 * sp < target else -math.inf)
            return sp
        _, below = contract.expected_rows([length], spacing_for(math.nextafter(length, 0)))
        self.assertEqual([r['kind'] for r in below], [3, 1, 1, 1, 2])
        self.assertEqual(below[-1]['chainage'] - below[-2]['chainage'], length - math.nextafter(length, 0))
        self.assertEqual(contract.chainage_label(below[-1]['chainage']), contract.chainage_label(below[-2]['chainage']))
        _, above = contract.expected_rows([length], spacing_for(math.nextafter(length, math.inf)))
        self.assertEqual([r['kind'] for r in above], [3, 1, 1, 2])

    def test_three_state_band(self):
        self.assertEqual(contract.three_state(10.0, 1.0, {'maximum': 11.0}), 'met')
        self.assertEqual(contract.three_state(10.0, 1.0, {'maximum': 10.5}), 'indeterminate')
        self.assertEqual(contract.three_state(10.0, 1.0, {'maximum': 8.9}), 'unmet')
        self.assertEqual(contract.three_state(10.0, 1.0, {'minimum': 9.0, 'maximum': 11.0}), 'met')
        self.assertEqual(contract.three_state(10.0, 1.0, {'minimum': 11.5}), 'unmet')


class Oracle(unittest.TestCase):
    def test_formulation_independent_anchors(self):
        for dl in (0.5, 10.0, 44.9):
            r = g.inverse(-97.0, 0.0, -97.0 + dl, 0.0)
            self.assertLessEqual(abs(r['s'] - g.equator_arc(-97.0, -97.0 + dl)) + r['error_m'], contract.tau(r['s']) / 10)
        for lat1, lat2 in ((0.0, 1.0), (10.0, 50.0), (-20.0, 24.0)):
            r = g.inverse(-97.0, lat1, -97.0, lat2)
            self.assertLessEqual(abs(r['s'] - g.meridian_arc(lat1, lat2)) + r['error_m'], contract.tau(r['s']) / 10)
        ode = anchors.anchor(-97.1384, 49.8951, 37.0, 3.0e5)
        d = g.direct(-97.1384, 49.8951, 37.0, 3.0e5)
        sep = g.local_separation(d['lon'], d['lat'], ode['lon'], ode['lat'])[0]
        self.assertLessEqual(sep + ode['richardson_m'] + ode['rounding_m'] + g.rounding_estimate(3e5), contract.tau(3e5) / 10)

    def test_one_millimetre_regime_transition(self):
        # 36 pairs across the 1 mm switch: flat and Newton evaluations agree far inside tau/10.
        pairs = 0
        for lat in (0.0, 49.8951, 74.9):
            for az in (0.0, 37.0, 90.0, 233.0):
                for dist in (0.9e-3, 1.1e-3, 5e-3):
                    d = g.direct(-97.0, lat, az, dist)
                    flat = g.flat_inverse(*g.local_separation(-97.0, lat, d['lon'], d['lat']), lat, d['lat'])
                    saved = g.FLAT_MAX_M
                    g.FLAT_MAX_M = 0.0
                    try:
                        newton = g.inverse(-97.0, lat, d['lon'], d['lat'])
                    finally:
                        g.FLAT_MAX_M = saved
                    self.assertLessEqual(abs(flat['s'] - newton['s']) + flat['error_m'], 1e-7)
                    pairs += 1
        self.assertEqual(pairs, 36)
        tiny = g.inverse(-97.1384, 49.8951, -97.1384, math.nextafter(49.8951, 90.0))
        self.assertEqual(tiny['regime'], 'flat')
        self.assertLess(tiny['s'], 1e-8)

    def test_qualified_domain_and_guards(self):
        with self.assertRaises(g.OracleOutsideDomain):
            g.inverse(-97.0, -75.0, -97.0, 75.0)
        real = g.direct
        try:
            g.direct = lambda lon, lat, azi, s: real(lon, lat, round(azi, 3), s)
            with self.assertRaises(g.OracleIndeterminate):
                g.inverse(-97.1384, 49.8951, -96.0, 50.6)
            g.direct = lambda lon, lat, azi, s: {**real(lon, lat, azi, s), 'lon': float('nan')}
            with self.assertRaises(g.OracleIndeterminate):
                g.inverse(-97.1384, 49.8951, -96.0, 50.6)
        finally:
            g.direct = real
        vincenty = g.vincenty_inverse
        try:
            g.vincenty_inverse = lambda *args: {'s': 0.0, 'azi1': 10.0, 'azi2': 10.0}
            with self.assertRaises(g.OracleIndeterminate):
                g.inverse(-97.1384, 49.8951, -97.1384, 49.89511)
        finally:
            g.vincenty_inverse = vincenty


class Verifier(unittest.TestCase):
    def setUp(self):
        self.p, self.stations, self.legs, self.route, self.names, self.result, self.geo = synthetic(
            [WPG, SELKIRK, [-96.937, 50.0861], [-97.1380, 49.8953]], 1000.0, gap=True)

    def independent(self):
        return v.independent(self.stations, self.legs, self.p, self.route)

    def test_clean_reference_passes_structural_and_independent(self):
        v.structural(self.stations, self.legs, self.geo, self.p, self.route, self.names)
        evidence = self.independent()
        self.assertEqual(set(evidence['ratios']['adequacy']), {'legInverse', 'stationForward', 'consecutiveInverse', 'endpointGapInverse'})
        self.assertTrue(all(x['ratio'] <= 1 for x in evidence['ratios']['adequacy'].values()))

    def test_station_direct_residual_fails_adequacy(self):
        # Root probe 0021: a 1 m direct residual on station forward evaluations must not pass.
        real = v._direct
        try:
            v._direct = lambda *args: {**real(*args), 'residual_m': 1.0}
            with self.assertRaises(SchemaxisError) as caught:
                self.independent()
            self.assertEqual(caught.exception.fault.code, 'VERIFICATION_INDETERMINATE')
            self.assertIn('stationForward', caught.exception.fault.message)
        finally:
            v._direct = real

    def test_consecutive_inverse_at_five_times_budget_fails(self):
        real = g.inverse
        legs = {(tuple(a_), tuple(b_)) for a_, b_ in zip(self.route, self.route[1:])} | {(tuple(self.route[-1]), tuple(self.route[0]))}
        def inflated(x1, y1, x2, y2, **kw):
            r = real(x1, y1, x2, y2, **kw)
            if ((x1, y1), (x2, y2)) not in legs:
                r = {**r, 'error_m': 5 * contract.tau(r['s']) / 10}
            return r
        try:
            g.inverse = inflated
            with self.assertRaises(SchemaxisError) as caught:
                self.independent()
            self.assertEqual(caught.exception.fault.code, 'VERIFICATION_INDETERMINATE')
            self.assertIn('consecutiveInverse', caught.exception.fault.message)
        finally:
            g.inverse = real

    def test_leg_and_gap_adequacy(self):
        real = g.inverse
        for target, where in ((tuple(self.route[0]), 'leg 1'), (tuple(self.route[-1]), contract.GAP)):
            def inflated(x1, y1, x2, y2, **kw):
                r = real(x1, y1, x2, y2, **kw)
                return {**r, 'error_m': contract.tau(r['s'])} if (x1, y1) == target and (x2, y2) in {tuple(self.route[1]), tuple(self.route[0])} else r
            try:
                g.inverse = inflated
                self.assertEqual(code(self.independent), ('VERIFICATION_INDETERMINATE', where))
            finally:
                g.inverse = real

    def test_gap_outside_qualified_domain_is_refused_before_comparison(self):
        # Gap 5000 km + 0.1 m: the host chord bound (~4880 km) cannot refuse it, so the saved
        # verifier's own qualified-domain closure must, before any numerical comparison.
        start = [-123.1207, 49.2827]
        mid, end = g.direct(*start, 100.0, 2.5e6), g.direct(*start, 100.0, 5.0e6 + 0.1)
        points = [start, [mid['lon'], mid['lat']], [end['lon'], end['lat']]]
        _p, stations, legs, route, *_ = synthetic(points, 100000.0)
        requested = contract.validate(document('/x/route.csv', 100000.0, requirements={'endpointGap_m': {'maximum': 5e6}}))
        self.assertEqual(code(lambda: v.independent(stations, legs, requested, route)), ('ENDPOINT_GAP_OUTSIDE_DOMAIN', contract.GAP))

    def test_host_decision_and_gap_null(self):
        evidence = self.independent()
        decision = v.decide(self.p, self.stations, self.legs, self.result['gap'], evidence)
        self.assertEqual(decision['outcome'], 'accepted')
        plain = contract.validate(document('/x/route.csv'))
        self.assertEqual(code(lambda: v.decide(plain, self.stations, self.legs, 36.0, {'endpointGap': None})),
                         ('VERIFICATION_FAILED', contract.GAP))

    def test_native_refusal_needs_oracle_confirmation(self):
        p = contract.validate(document('/x/route.csv'))
        v.confirm_refusal('ROUTE_LEG_TOO_LONG', 'leg 1', p, [[-123.1207, 49.2827], [-65.980945, 32.159215]])
        self.assertEqual(code(lambda: v.confirm_refusal('ROUTE_LEG_TOO_LONG', 'leg 1', p, [WPG, SELKIRK]))[0], 'VERIFICATION_FAILED')
        self.assertEqual(code(lambda: v.confirm_refusal('ROUTE_LATITUDE_EXCURSION', 'leg 1', p, [WPG, SELKIRK]))[0], 'VERIFICATION_FAILED')


class FakeRuntime(unittest.TestCase):
    """Full adaptor plumbing with the oracle-backed fake interpreter (see module docstring)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='pyproj-test-'))
        self.python = fake_runtime(self.tmp)
        self.source = self.tmp / 'route.csv'
        self.source.write_bytes((EXAMPLES / 'pyproj-winnipeg-route.csv').read_bytes())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_route(self, name, doc, **kw):
        return a.run(doc, self.tmp / name, executable=self.python, timeout=kw.pop('timeout', 60), **kw)

    def baseline(self, name='base', **extra):
        doc = document(self.source, 1000.0, requirements={'totalLength_m': {'maximum': 50000}}, **extra)
        return doc, self.run_route(name, doc)

    def test_baseline_saved_verification_and_retained_inputs(self):
        doc, result = self.baseline()
        target = self.tmp / 'base'
        self.assertEqual((result['rows'], result['requirements']), (43, 'met'))
        self.assertTrue(a.verify(target)['verified'])
        submission = a.read(target, 'compute-submission.json')['nativeCommand']
        self.assertEqual(submission, [self.python, '-I', '-B', 'native-worker.py', 'compute'])
        digest = a.reusableInputs(doc)[str(self.source)]
        self.assertEqual(a.retainedInputs(target, doc), {str(self.source): digest})
        self.source.unlink()                                   # original removed: retained capture suffices
        self.assertTrue(a.verify(target)['verified'])
        self.assertEqual(a.retainedInputs(target, doc), {str(self.source): digest})
        self.assertEqual(code(lambda: a.reusableInputs(doc))[0], 'INVALID_ROUTE_SOURCE')
        self.source.write_bytes(b'lon_deg,lat_deg\n-97.0,49.0\n-96.0,49.0\n')   # current source changed
        self.assertNotEqual(a.reusableInputs(doc), a.retainedInputs(target, doc))
        from schemaxis.schema_snapshots import export_run
        moved = self.tmp / 'exported'
        export_run(target, moved)                              # canonical schema-aware same-host export
        self.assertTrue(a.verify(moved)['verified'])
        self.assertEqual(code(lambda: a.retainedInputs(target, {**doc, 'spacing_m': 500.0}))[0], 'VERIFICATION_FAILED')

    def test_hostile_saved_evidence_with_refreshed_hashes(self):
        from schemaxis.schema_snapshots import export_run
        self.baseline()
        target = self.tmp / 'base'
        origin = str(target)
        def mutate(label, change, expected, fragment, refreshed=True):
            copy_ = self.tmp / ('mutant-' + label)
            export_run(target, copy_)                      # canonical copy with its schema dependencies
            change(copy_)
            recorded = recorded_identity(copy_)
            if refreshed:
                refresh(copy_)
            after = recorded_identity(copy_)
            self.assertEqual(after, recorded, label)       # the helper never rebases recorded locations
            self.assertEqual(after['recordedDirectory'], origin, label)
            self.assertTrue(all(Path(item['file']).parent == target for item in after['artifacts']), label)
            try:
                result = a.verify(copy_)
                observed = ('accept', '')
                self.assertTrue(result['verified'])
            except SchemaxisError as error:
                observed = (error.fault.code, error.fault.message)
            self.assertEqual(observed[0], expected, (label, observed))
            self.assertIn(fragment, observed[1], label)
        def edit_json(name, fn):
            def apply(d):
                value = a.read(d, name); fn(value); atomic_json(d / name, value)
            return apply
        def shift_station(d):
            record = a.read(d, 'native-result.json')
            row = next(r for r in record['result']['rows'] if r['kind'] == 1)
            row['lat'] += 1e-8
            for name, text in w.publications(record['result']).items():
                (d / name).write_text(text)
            atomic_json(d / 'native-result.json', record)
        failed = 'VERIFICATION_FAILED'
        mutate('summaryStateFlip', edit_json('route-summary.json', lambda x: x['requirements']['totalLength_m'].update(state='unmet')), failed, 'route summary differs from recomputation')
        mutate('decisionFlip', edit_json('route-verification.json', lambda x: x['decision'].update(outcome='requirementsUnmet')), failed, 'host verification record differs')
        mutate('stationShift1e-8deg', shift_station, 'GEODESIC_VERIFICATION_FAILED', 'stationPosition')
        mutate('readbackTruthyInteger', edit_json('readback.json', lambda x: x.update(publicationsExact=1)), failed, 'native readback record is malformed')
        mutate('readbackRatioOutOfRange', edit_json('readback.json', lambda x: x.update(consecutiveInverseWorstRatio=2.0)), failed, 'native readback record is malformed')
        mutate('runtimeObservation', edit_json('native-result.json', lambda x: x['runtime'].update(proj='9.8.0')), failed, 'native runtime observation differs')
        mutate('networkObservedOn', edit_json('native-result.json', lambda x: x['runtime'].update(network=True)), failed, 'native runtime observation differs')
        mutate('absoluteWorkerCommand', edit_json('compute-submission.json', lambda x: x.update(nativeCommand=[self.python, '-I', '-B', str(target / 'native-worker.py'), 'compute'])), failed, 'native command or completion differs')
        def worker_bytes(d):
            (d / 'native-worker.py').write_text((d / 'native-worker.py').read_text() + '# altered\n')
        mutate('workerBytes', worker_bytes, failed, 'trusted native worker differs')
        def private_home(d):
            (d / a.HOME / 'cache.db').write_text('x')
        mutate('privateHomeWritten', private_home, failed, 'private native home')
        def gap_without_requirement(d):
            record = a.read(d, 'native-result.json'); record['result']['gap'] = 1.0
            atomic_json(d / 'native-result.json', record)
        mutate('gapComputedWithoutRequirement', gap_without_requirement, failed, 'endpoint gap must stay uncomputed')
        # Valid controls: the current baseline export as is, and with digests refreshed but locations preserved.
        mutate('controlCurrentBaselineExport', lambda d: None, 'accept', '', refreshed=False)
        mutate('controlDigestsRefreshedLocationsPreserved', lambda d: None, 'accept', '')
        self.assertTrue(a.verify(target)['verified'])

    def test_unmet_and_indeterminate_requirements_are_not_accepted(self):
        unmet = document(self.source, 1000.0, requirements={'totalLength_m': {'maximum': 40000}})
        self.assertEqual(code(lambda: self.run_route('unmet', unmet)), ('ROUTE_REQUIREMENT_NOT_MET', '$.requirements.totalLength_m'))
        target = self.tmp / 'unmet'
        self.assertTrue((target / 'route-summary.json').is_file())
        self.assertEqual(a.read(target, 'result.json')['status'], 'failed')
        self.assertEqual(code(lambda: a.verify(target))[0], 'ROUTE_REQUIREMENT_NOT_MET')
        atomic_json(target / 'result.json', {'status': 'succeeded', 'verified': True})
        self.assertEqual(code(lambda: a.verify(target))[0], 'ROUTE_REQUIREMENT_NOT_MET')
        total = a.read(self.tmp / 'unmet', 'route-summary.json')['totalLength_m']
        boundary = document(self.source, 1000.0, requirements={'totalLength_m': {'maximum': total}})
        self.assertEqual(code(lambda: self.run_route('boundary', boundary))[0], 'ROUTE_REQUIREMENT_INDETERMINATE')

    def test_gap_requirement_and_native_domain_refusal(self):
        gap_source = self.tmp / 'gap.csv'
        gap_source.write_bytes(csv_bytes([WPG, SELKIRK, [-97.1380, 49.8953]]))
        result = self.run_route('gap', document(gap_source, 2000.0, requirements={'endpointGap_m': {'maximum': 100}}))
        self.assertEqual(result['requirements'], 'met')
        summary = a.read(self.tmp / 'gap', 'route-summary.json')
        self.assertLess(abs(summary['endpointGap_m'] - 36.343911848583865), 1e-6)
        start = [-123.1207, 49.2827]
        end = g.direct(*start, 100.0, 5.0e6 + 0.1)
        mid = g.direct(*start, 100.0, 2.5e6)
        far = self.tmp / 'far.csv'
        far.write_bytes(csv_bytes([start, [mid['lon'], mid['lat']], [end['lon'], end['lat']]]))
        doc = document(far, 50000.0, requirements={'endpointGap_m': {'maximum': 5e6}})
        self.assertEqual(code(lambda: self.run_route('far', doc)), ('ENDPOINT_GAP_OUTSIDE_DOMAIN', contract.GAP))
        self.assertTrue((self.tmp / 'far' / 'compute-fault.json').is_file())
        self.assertFalse((self.tmp / 'far' / 'readback-submission.json').exists())

    def test_lying_native_refusal_is_not_trusted(self):
        liar = fake_runtime(self.tmp / 'liar', lie=1000.0)        # claims a 33 km leg is 33,000 km
        doc = document(self.source, 1000.0)
        self.assertEqual(code(lambda: a.run(doc, self.tmp / 'lie', executable=liar, timeout=60))[0], 'VERIFICATION_FAILED')

    def test_deadline_and_cancellation_cover_host_verification(self):
        doc = document(self.source, 1000.0)
        real = g.direct
        def slow(*args):
            import time
            time.sleep(0.02)
            return real(*args)
        try:
            g.direct = slow
            self.assertEqual(code(lambda: self.run_route('slow', doc, timeout=4))[0], 'RUNNER_TIMED_OUT')
            self.assertEqual(a.read(self.tmp / 'slow', 'result.json')['status'], 'failed')
            event = threading.Event()
            calls = []
            def cancelling(*args):
                calls.append(1)
                if len(calls) == 20:
                    event.set()
                return real(*args)
            g.direct = cancelling
            with allocation({'threads': 1, 'ranks': 1}, event):
                self.assertEqual(code(lambda: self.run_route('cancel', doc))[0], 'RUNNER_CANCELLED')
            self.assertEqual(a.read(self.tmp / 'cancel', 'result.json')['status'], 'failed')
        finally:
            g.direct = real

    def test_forged_scheduled_job_input_hashes(self):
        from schemaxis import workflow
        import hashlib
        graph = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'route', 'document': document(self.source, 1000.0)}]}
        root = self.tmp / 'wf'
        workflow.execute(graph, root, locations={'pyproj': self.python}, timeout=60)
        self.assertTrue(workflow.verify(root)['verified'])
        # Saved verification: forged result.json job inputHashes disagree with the verified capture.
        saved = json.loads((root / 'result.json').read_text())
        forged = copy.deepcopy(saved)
        forged['jobs'][0]['inputHashes'] = {str(self.source): '0' * 64}
        (root / 'result.json').write_text(json.dumps(forged))
        self.assertEqual(code(lambda: workflow.verify(root))[0], 'VERIFICATION_FAILED')
        (root / 'result.json').write_text(json.dumps(saved))
        # Resume: the source changes and job.json is forged to claim the new bytes; the retained
        # capture still holds the old bytes, so the stale attempt must not be reused.
        self.source.write_bytes(self.source.read_bytes().replace(b'-96.937', b'-96.938'))
        fresh = hashlib.sha256(self.source.read_bytes()).hexdigest()
        job_path = next(root.rglob('job.json'))
        job = json.loads(job_path.read_text())
        job['inputHashes'] = {str(self.source): fresh}
        job_path.write_text(json.dumps(job))
        second = workflow.execute(graph, root, locations={'pyproj': self.python}, timeout=60, resume=True)
        self.assertFalse(any(j.get('reused') for j in second['jobs']))
        self.assertTrue(workflow.verify(root)['verified'])

    def test_exported_workflow_after_source_removal_and_forged_result_and_job_hashes(self):
        from schemaxis import workflow
        from schemaxis.run_paths import owned_path
        from schemaxis.schema_snapshots import export_run
        import hashlib
        graph = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'route', 'document': document(self.source, 1000.0)}]}
        root = self.tmp / 'wf'
        workflow.execute(graph, root, locations={'pyproj': self.python}, timeout=60)
        identity = {str(self.source): hashlib.sha256(self.source.read_bytes()).hexdigest()}
        exported, again = self.tmp / 'wf-export', self.tmp / 'wf-reexport'
        export_run(root, exported)
        export_run(exported, again)
        removed = self.source.read_bytes()
        self.source.unlink()                                   # physical removal: captures alone verify
        for tree in (root, exported, again):
            self.assertTrue(workflow.verify(tree)['verified'], tree)
            job = json.loads((tree / 'result.json').read_text())['jobs'][0]
            self.assertEqual(a.retainedInputs(owned_path(tree, job['directory'], kind='directory'), job['effective']), identity)
        self.source.write_bytes(removed.replace(b'-96.937', b'-96.938'))
        fresh = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.assertTrue(workflow.verify(again)['verified'])     # changed source: authentic capture still verifies
        for tree in (root, again):                            # forge BOTH result.json and job.json
            saved = json.loads((tree / 'result.json').read_text())
            attempt = owned_path(tree, saved['jobs'][0]['directory'], kind='directory')
            record = json.loads((attempt / 'job.json').read_text())
            record['inputHashes'] = saved['jobs'][0]['inputHashes'] = {str(self.source): fresh}
            (attempt / 'job.json').write_text(json.dumps(record))
            (tree / 'result.json').write_text(json.dumps(saved))
            self.assertEqual(code(lambda: workflow.verify(tree))[0], 'VERIFICATION_FAILED')
        second = workflow.execute(graph, root, locations={'pyproj': self.python}, timeout=60, resume=True)
        self.assertFalse(any(j.get('reused') for j in second['jobs']))
        self.assertTrue(workflow.verify(root)['verified'])
        job = json.loads((root / 'result.json').read_text())['jobs'][0]
        self.assertEqual(job['inputHashes'], {str(self.source): fresh})
        self.assertEqual(job['effective']['source'], str(self.source))

    def test_studio_templates_plan(self):
        studio = json.loads((ROOT / 'src/schemaxis/adaptors/pyproj/studio.json').read_text())
        for template in studio['templates']:
            filled = {**template['document'], 'source': template['testValues']['source']}
            self.assertEqual(a.plan(filled)['operation'], 'routeStations')
        self.assertEqual(a.plan(studio['baseDocument'])['spacing_m'], 1000.0)


if __name__ == '__main__':
    unittest.main()
