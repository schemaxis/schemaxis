"""Independent host verification of routeStations publications (standard library only).

* ``structural``: exact, oracle-free rules (tables, GeoJSON, chainage rule, captured waypoints).
* ``independent``: the stdlib oracle re-evaluates every leg, station, consecutive step and the
  requested endpoint gap. Each evaluation must first pass its adequacy rule (resolve to tau/10 at
  its own distance scale) or the run fails with VERIFICATION_INDETERMINATE, with or without
  requirements. Agreement is then checked against the contract tolerance.
* ``decide``: the host-owned summary and requirement decision.
* ``confirm_refusal``: a native domain refusal is accepted only when the oracle reproduces it.

All results are deterministic so saved verification can recompute and compare them bitwise.
"""
import math

from schemaxis.errors import fail
from . import contract, geodesy
from .contract import GAP, LIMITS, U, located, tau

BAND = LIMITS['maxPathLatitude_deg']
CHECKPOINT_EVERY = 128


def structural(stations, legs, geo, p, points, names):
    """Exact rules. ``points``/``names`` include the closing copy of waypoint 1 for closed routes."""
    n = len(points) - 1
    if len(legs) != n:
        fail('VERIFICATION_FAILED', 'leg count differs from waypoints', 'legs.csv')
    for i, leg in enumerate(legs):
        at = f'legs.csv leg {i + 1}'
        if [leg['leg'], leg['from_waypoint'], leg['to_waypoint']] != [i + 1, i + 1, i + 2]:
            fail('VERIFICATION_FAILED', 'leg identity differs', at)
        for key in ('azimuth_start_deg', 'azimuth_end_deg', 'back_azimuth_deg'):
            if not 0 <= leg[key] < 360:
                fail('VERIFICATION_FAILED', 'azimuths must lie in [0, 360)', at)
        if abs(geodesy.wrap180(leg['back_azimuth_deg'] - leg['azimuth_end_deg'] - 180)) > 1e-9:
            fail('VERIFICATION_FAILED', 'back azimuth is not the end azimuth reversed', at)
        if not 0 < leg['length_m'] <= 2 * LIMITS['maxLeg_m']:
            fail('VERIFICATION_FAILED', 'leg length is outside the published range', at)
    chainage, rows = contract.expected_rows([leg['length_m'] for leg in legs], p['spacing_m'])
    if rows is None:
        fail('VERIFICATION_FAILED', 'published lengths imply more rows than the row limit', 'legs.csv')
    for i, leg in enumerate(legs):
        if leg['start_chainage_m'] != chainage[i] or leg['end_chainage_m'] != chainage[i + 1]:
            fail('VERIFICATION_FAILED', 'leg chainage is not the correctly rounded prefix sum', f'legs.csv leg {i + 1}')
    if len(rows) != len(stations):
        fail('VERIFICATION_FAILED', f'row membership differs: expected {len(rows)}, published {len(stations)}', 'stations.csv')
    last = len(rows) - 1
    for index, (r, s) in enumerate(zip(rows, stations)):
        at = f'stations.csv row {index + 1}'
        if [s['row'], s['chainage_m'], s['leg'], s['offset_m'], s['kind'], s['waypoint']] != \
                [index + 1, r['chainage'], r['leg'], r['offset'], r['kind'], r['waypoint']]:
            fail('VERIFICATION_FAILED', 'row identity, chainage, leg, offset or kind differs from the declared rule', at)
        if not 0 <= s['azimuth_deg'] < 360:
            fail('VERIFICATION_FAILED', 'azimuths must lie in [0, 360)', at)
        if r['kind'] != 1:
            if [s['lon_deg'], s['lat_deg']] != points[r['waypoint'] - 1]:
                fail('VERIFICATION_FAILED', 'waypoint row does not republish the captured binary64 coordinates exactly', at)
            expected = legs[n - 1]['azimuth_end_deg'] if index == last else legs[r['leg'] - 1]['azimuth_start_deg']
            if s['azimuth_deg'] != expected:
                fail('VERIFICATION_FAILED', 'waypoint row azimuth differs from its leg azimuth', at)
        elif not (-180 < s['lon_deg'] < 180 and abs(s['lat_deg']) <= BAND + 1e-9):
            fail('GEODESIC_VERIFICATION_FAILED', 'station leaves the supported geography', at)
    if any(b['chainage_m'] <= a['chainage_m'] for a, b in zip(stations, stations[1:])):
        fail('VERIFICATION_FAILED', 'chainage must increase strictly', 'stations.csv')
    _geojson(stations, legs, geo, p, names, n)


def _deflection(kind, w, legs, n, closed):
    if kind == 1 or w == 1 or (w == n + 1 and not closed):
        return None
    if w == n + 1:
        return geodesy.wrap180(legs[0]['azimuth_start_deg'] - legs[n - 1]['azimuth_end_deg'])
    return geodesy.wrap180(legs[w - 1]['azimuth_start_deg'] - legs[w - 2]['azimuth_end_deg'])


def _geojson(stations, legs, geo, p, names, n):
    for name, doc in geo.items():
        if not isinstance(doc, dict) or set(doc) != {'type', 'features'} or doc['type'] != 'FeatureCollection' \
                or not isinstance(doc['features'], list):
            fail('VERIFICATION_FAILED', 'GeoJSON must be a FeatureCollection without crs or bbox members', name)
    points = geo['stations.geojson']['features']
    if len(points) != len(stations):
        fail('VERIFICATION_FAILED', 'station feature count differs', 'stations.geojson')
    for s, f in zip(stations, points):
        w = s['waypoint']
        expected = {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [s['lon_deg'], s['lat_deg']]},
                    'properties': {'row': s['row'], 'label': contract.chainage_label(s['chainage_m']), 'chainage_m': s['chainage_m'],
                                   'leg': s['leg'], 'offset_m': s['offset_m'], 'azimuth_deg': s['azimuth_deg'],
                                   'kind': contract.KINDS[s['kind']], 'waypoint': w or None, 'name': names[w - 1] if w else None}}
        published = dict(f.get('properties', {})) if isinstance(f, dict) and isinstance(f.get('properties'), dict) else None
        deflection = published.pop('deflection_deg', 'missing') if published is not None else 'missing'
        want = _deflection(s['kind'], w, legs, n, p['closed'])
        same = (published is not None and {**f, 'properties': published} == expected and
                (deflection is None if want is None else type(deflection) is float and abs(geodesy.wrap180(deflection - want)) <= 1e-9))
        if not same:
            fail('VERIFICATION_FAILED', 'station feature differs from the station table', f"stations.geojson row {s['row']}")
    lines = geo['route.geojson']['features']
    if len(lines) != n:
        fail('VERIFICATION_FAILED', 'route feature count differs from legs', 'route.geojson')
    for i, f in enumerate(lines):
        members = [s for s in stations if s['leg'] == i + 1]
        if i + 1 < n:
            members.append(next(s for s in stations if s['kind'] != 1 and s['waypoint'] == i + 2))
        leg = legs[i]
        expected = {'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': [[s['lon_deg'], s['lat_deg']] for s in members]},
                    'properties': {'leg': i + 1, 'from_waypoint': i + 1, 'to_waypoint': i + 2, 'from_name': names[i], 'to_name': names[i + 1],
                                   'length_m': leg['length_m'], 'start_chainage_m': leg['start_chainage_m'],
                                   'end_chainage_m': leg['end_chainage_m'], 'azimuth_start_deg': leg['azimuth_start_deg'],
                                   'azimuth_end_deg': leg['azimuth_end_deg'], 'back_azimuth_deg': leg['back_azimuth_deg']}}
        if f != expected:
            fail('VERIFICATION_FAILED', 'route feature differs from legs and stations', f'route.geojson leg {i + 1}')


class Ratios:
    """Worst agreement and adequacy ratios; unusable allowances fail closed."""

    def __init__(self):
        self.agreement, self.adequacy, self.count = {}, {}, {}

    def agree(self, kind, numerator, denominator, at):
        ratio = self._ratio(kind, numerator, denominator, at)
        if ratio > 1:
            fail('GEODESIC_VERIFICATION_FAILED', f'{kind} exceeds its contract tolerance (ratio {ratio:.3g})', at)
        self._keep(self.agreement, kind, ratio, at)

    def adequate(self, kind, error, scale, at):
        """The independent evaluation must resolve to tau(scale)/10; otherwise the run is indeterminate."""
        ratio = self._ratio(kind, error, tau(scale) / 10, at)
        self.count[kind] = self.count.get(kind, 0) + 1
        if ratio > 1:
            located('VERIFICATION_INDETERMINATE', f'{kind}: the independent evaluation cannot resolve to tau/10 '
                    f'(error {error:.3g} m at distance scale {scale:.6g} m)', at,
                    'the numerical agreement cannot be established; no result is published as verified', ratio=ratio)
        self._keep(self.adequacy, kind, ratio, at)

    @staticmethod
    def _ratio(kind, numerator, denominator, at):
        if not (isinstance(numerator, float) or isinstance(numerator, int)) or not (isinstance(denominator, float) or isinstance(denominator, int)) \
                or not (math.isfinite(denominator) and denominator > 0 and math.isfinite(numerator) and numerator >= 0):
            located('VERIFICATION_INDETERMINATE', f'{kind}: allowance or residual is not resolvable', at)
        return numerator / denominator

    @staticmethod
    def _keep(table, kind, ratio, at):
        if ratio > table.get(kind, (-1.0, ''))[0]:
            table[kind] = (ratio, at)

    def record(self):
        render = lambda table: {k: {'ratio': v[0], 'at': v[1]} for k, v in sorted(table.items())}
        return {'agreement': render(self.agreement), 'adequacy': render(self.adequacy),
                'adequacyEvaluations': dict(sorted(self.count.items()))}


def _inverse(lon1, lat1, lon2, lat2, at, outside='GEODESIC_VERIFICATION_FAILED', outside_at=None):
    try:
        return geodesy.inverse(lon1, lat1, lon2, lat2)
    except geodesy.OracleOutsideDomain as error:
        located(outside, 'geodesic outside the qualified independent domain: ' + str(error), outside_at or at)
    except geodesy.OracleIndeterminate as error:
        located('VERIFICATION_INDETERMINATE', 'the independent oracle could not resolve: ' + str(error), at)


def _direct(lon, lat, azi, s, at):
    try:
        return geodesy.direct(lon, lat, azi, s)
    except geodesy.OracleIndeterminate as error:
        located('VERIFICATION_INDETERMINATE', 'the independent oracle could not resolve: ' + str(error), at)


def _peak(p, q, inv):
    peak = max(abs(p[1]), abs(q[1]))
    if math.cos(math.radians(inv['azi1'])) * math.cos(math.radians(inv['azi2'])) < 0:
        peak = max(peak, geodesy.vertex_latitude(p[1], inv['azi1']))
    return peak


def independent(stations, legs, p, points, checkpoint=lambda: None):
    """Re-evaluate every published geodesic quantity; return deterministic oracle evidence."""
    ratios = Ratios()
    oracle_legs = []
    for i, leg in enumerate(legs):
        a, b = points[i], points[i + 1]
        at = f'leg {i + 1}'
        inv = _inverse(a[0], a[1], b[0], b[1], at)
        ratios.adequate('legInverse', inv['error_m'], inv['s'], at)
        t = tau(inv['s'])
        ratios.agree('legLength', abs(leg['length_m'] - inv['s']) + inv['error_m'], t, at)
        ratios.agree('azimuthStart', abs(math.radians(geodesy.wrap180(leg['azimuth_start_deg'] - inv['azi1']))) * inv['s'], t - inv['error_m'], at)
        ratios.agree('azimuthEnd', abs(math.radians(geodesy.wrap180(leg['azimuth_end_deg'] - inv['azi2']))) * inv['s'], t - inv['error_m'], at)
        if _peak(a, b, inv) > BAND + 1e-9:
            fail('GEODESIC_VERIFICATION_FAILED', 'published route leaves the supported latitude band', at)
        oracle_legs.append(inv)
    budget = 0.0
    for i, leg in enumerate(legs):
        total = math.fsum(o['s'] for o in oracle_legs[:i + 1])
        budget += tau(oracle_legs[i]['s'])
        ratios.agree('chainage', abs(leg['end_chainage_m'] - total), budget + U * total, f'leg {i + 1}')
    for index, s in enumerate(stations):
        if index % CHECKPOINT_EVERY == 0:
            checkpoint()
        if s['kind'] != 1:
            continue
        i = s['leg'] - 1
        leg_inverse = oracle_legs[i]
        at = f"station row {s['row']}"
        d = _direct(points[i][0], points[i][1], leg_inverse['azi1'], s['offset_m'], at)
        # Station adequacy: direct residual + rounding estimate at the offset + the leg inverse error
        # propagated to the offset (bounded by the full leg error because the reduced length is
        # monotone over legs <= 5000 km), against the leg's tau/10.
        error = d['residual_m'] + geodesy.rounding_estimate(s['offset_m']) + leg_inverse['error_m']
        ratios.adequate('stationForward', error, leg_inverse['s'], at)
        sep, _dn, _de = geodesy.local_separation(d['lon'], d['lat'], s['lon_deg'], s['lat_deg'])
        allowance = 2 * tau(leg_inverse['s'])
        ratios.agree('stationPosition', sep + error, allowance, at)
        ratios.agree('stationAzimuth', abs(math.radians(geodesy.wrap180(s['azimuth_deg'] - d['azi2']))) * leg_inverse['s'], allowance - error, at)
    # Consecutive rows share one geodesic leg (row a's leg), so the oracle inverse between their
    # published positions must reproduce the chainage step; it uses positions only.
    for index, (a, b) in enumerate(zip(stations, stations[1:])):
        if index % CHECKPOINT_EVERY == 0:
            checkpoint()
        at = f"rows {a['row']}-{b['row']}"
        step = b['chainage_m'] - a['chainage_m']
        inv = _inverse(a['lon_deg'], a['lat_deg'], b['lon_deg'], b['lat_deg'], at)
        ratios.adequate('consecutiveInverse', inv['error_m'], inv['s'], at)
        ratios.agree('consecutiveStep', abs(inv['s'] - step) + inv['error_m'] + U * b['chainage_m'], 4 * tau(oracle_legs[a['leg'] - 1]['s']), at)
    gap = None
    if 'endpointGap_m' in p.get('requirements', {}):
        # Domain closure before any comparison: host bounds, the oracle's qualified cap, its vertex.
        last, first = points[-1], points[0]
        contract.gap_domain_precheck(last, first)
        inv = _inverse(last[0], last[1], first[0], first[1], GAP, outside='ENDPOINT_GAP_OUTSIDE_DOMAIN')
        if inv['s'] > LIMITS['maxLeg_m'] + tau(LIMITS['maxLeg_m']):
            located('ENDPOINT_GAP_OUTSIDE_DOMAIN', 'the endpoint gap exceeds the qualified 5000 km', GAP)
        if _peak(last, first, inv) > BAND + 1e-9:
            located('ENDPOINT_GAP_OUTSIDE_DOMAIN', 'the endpoint gap geodesic leaves the supported latitude band', GAP)
        ratios.adequate('endpointGapInverse', inv['error_m'], inv['s'], GAP)
        gap = {'s': inv['s'], 'error_m': inv['error_m'], 'regime': inv['regime']}
    checkpoint()
    return {'ratios': ratios.record(),
            'legs': [{'s': o['s'], 'azi1': o['azi1'], 'azi2': o['azi2'], 'error_m': o['error_m'], 'regime': o['regime']} for o in oracle_legs],
            'endpointGap': gap}


def decide(p, stations, legs, native_gap, evidence):
    """Host-owned summary values and requirement decision (never taken from native output)."""
    requirements = p.get('requirements', {})
    total = legs[-1]['end_chainage_m']
    band = math.fsum([tau(leg['length_m']) for leg in legs]) + U * total
    states = {}
    if 'endpointGap_m' not in requirements:
        if native_gap is not None or evidence['endpointGap'] is not None:
            fail('VERIFICATION_FAILED', 'the endpoint gap must stay uncomputed when no gap requirement is declared', GAP)
        gap_band = None
    else:
        if type(native_gap) is not float or not math.isfinite(native_gap) or native_gap < 0 or evidence['endpointGap'] is None:
            fail('VERIFICATION_FAILED', 'the native endpoint gap must be a finite non-negative binary64 number', GAP)
        gap_band = tau(native_gap)
        if not abs(native_gap - evidence['endpointGap']['s']) + evidence['endpointGap']['error_m'] <= gap_band:
            fail('GEODESIC_VERIFICATION_FAILED', 'the endpoint gap exceeds its contract tolerance', GAP)
        states['endpointGap_m'] = contract.three_state(native_gap, gap_band, requirements['endpointGap_m'])
    if 'totalLength_m' in requirements:
        states['totalLength_m'] = contract.three_state(total, band, requirements['totalLength_m'])
    values = set(states.values())
    overall = 'none' if not states else 'unmet' if 'unmet' in values else 'indeterminate' if 'indeterminate' in values else 'met'
    fixed = [s['chainage_m'] for s in stations if s['kind'] in (1, 3)]
    labels = [contract.chainage_label(s['chainage_m']) for s in stations]
    return {'totalLength_m': total, 'lengthNumericalBand_m': band, 'finalInterval_m': total - fixed[-1],
            'endpointGap_m': native_gap, 'endpointGapNumericalBand_m': gap_band,
            'presentation': {'adjacentRowsWithIdenticalLabels': sum(x == y for x, y in zip(labels, labels[1:])), 'labelResolution_m': 0.001},
            'requirements': {k: {**requirements[k], 'state': v} for k, v in sorted(states.items())}, 'overall': overall,
            'outcome': 'accepted' if overall in ('none', 'met') else 'requirementsUnmet' if overall == 'unmet' else 'requirementsIndeterminate'}


def confirm_refusal(code, location, p, points):
    """Accept a native domain refusal only when the independent oracle reproduces it (within tau)."""
    def leg_index():
        try:
            index = int(location.split()[-1]) - 1 if location.startswith('leg ') else -1
        except ValueError:
            index = -1
        if not 0 <= index < len(points) - 1:
            fail('VERIFICATION_FAILED', 'native refusal names no leg of this route', location, nativeCode=code)
        return index

    def oracle(a, b):
        try:
            return geodesy.inverse(a[0], a[1], b[0], b[1])
        except geodesy.OracleOutsideDomain:
            return None
        except geodesy.OracleIndeterminate:
            return 'indeterminate'

    confirmed = False
    if code in ('ROUTE_LEG_TOO_LONG', 'ROUTE_LEG_TOO_SHORT', 'ROUTE_LATITUDE_EXCURSION'):
        i = leg_index()
        inv = oracle(points[i], points[i + 1])
        if code == 'ROUTE_LEG_TOO_LONG':
            confirmed = inv is None or (isinstance(inv, dict) and inv['s'] >= LIMITS['maxLeg_m'] - tau(LIMITS['maxLeg_m']))
        elif code == 'ROUTE_LEG_TOO_SHORT':
            confirmed = isinstance(inv, dict) and inv['s'] <= LIMITS['minLeg_m'] + tau(LIMITS['minLeg_m'])
        else:
            confirmed = isinstance(inv, dict) and _peak(points[i], points[i + 1], inv) >= BAND - 1e-9
    elif code in ('ROUTE_TOTAL_TOO_LONG', 'ROUTE_ROW_LIMIT'):
        lengths = [oracle(a, b) for a, b in zip(points, points[1:])]
        if all(isinstance(x, dict) for x in lengths):
            values = [x['s'] for x in lengths]
            if code == 'ROUTE_TOTAL_TOO_LONG':
                confirmed = math.fsum(values) >= LIMITS['maxTotal_m'] - math.fsum(tau(v) for v in values)
            else:
                # Native counts with its own lengths; a boundary row may differ by one.
                _, rows = contract.expected_rows(values, p['spacing_m'], cap=LIMITS['maxRows'] - 1)
                confirmed = rows is None
    elif code == 'ENDPOINT_GAP_OUTSIDE_DOMAIN' and location == GAP and 'endpointGap_m' in p.get('requirements', {}):
        last, first = points[-1], points[0]
        inv = oracle(last, first)
        confirmed = (abs(first[0] - last[0]) >= 180 or inv is None or
                     (isinstance(inv, dict) and (inv['s'] >= LIMITS['maxLeg_m'] - tau(LIMITS['maxLeg_m']) or _peak(last, first, inv) >= BAND - 1e-9)))
    if not confirmed:
        fail('VERIFICATION_FAILED', 'native refusal is not reproduced by the independent oracle', location, nativeCode=code)
