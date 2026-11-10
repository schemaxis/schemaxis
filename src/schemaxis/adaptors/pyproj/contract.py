# Copyright (C) 2026 David L F Gaden
"""Host contract for routeStations: declarations, strict waypoint CSV, conclusive prechecks and exact rules.

Standard library only (plus the shared declaration grammar and fault envelope). Never imports pyproj.
"""
import csv
import io
import json
import math
from pathlib import Path
import re

from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis.errors import fail, keys
from . import geodesy

VERSION = 'schemaxis.pyproj/1'
OPERATION = 'routeStations'
RUNTIME = 'pyproj 3.8.0 / PROJ 9.9.0'
LIMITS = {'minLeg_m': 0.01, 'maxLeg_m': 5.0e6, 'maxTotal_m': 2.0e7, 'maxRows': 10000, 'maxPathLatitude_deg': 75.0,
          'maxWaypoints': 500, 'maxSourceBytes': 1024 * 1024}
GAP = '$.requirements.endpointGap_m'
U = 2.0 ** -53
NUMBER = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]{1,3})?')
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9 ._()+/\-]{0,39}')
PUBLICATIONS = ('stations.csv', 'legs.csv', 'stations.geojson', 'route.geojson')
STATION_COLUMNS = ['row', 'chainage_m', 'lon_deg', 'lat_deg', 'leg', 'offset_m', 'azimuth_deg', 'kind', 'waypoint']
LEG_COLUMNS = ['leg', 'from_waypoint', 'to_waypoint', 'length_m', 'start_chainage_m', 'end_chainage_m',
               'azimuth_start_deg', 'azimuth_end_deg', 'back_azimuth_deg']
KINDS = {1: 'station', 2: 'waypoint', 3: 'waypoint+station'}

BOUND = lambda high: {'type': 'number', 'minimum': 0, 'maximum': high}
REQUIREMENTS = {'type': 'object', 'properties': {
    'totalLength_m': {'type': 'object', 'properties': {'minimum': BOUND(LIMITS['maxTotal_m']), 'maximum': BOUND(LIMITS['maxTotal_m'])}},
    'endpointGap_m': {'type': 'object', 'properties': {'maximum': {**BOUND(LIMITS['maxLeg_m']), 'required': True}}}}}
OPTIONS = {
    'source': {'type': 'string', 'minLength': 1, 'maxLength': 4096, 'required': True},
    'ellipsoid': {'type': 'enum', 'values': ['WGS84'], 'required': True},
    'coordinateOrder': {'type': 'enum', 'values': ['lonLat'], 'required': True},
    'spacing_m': {'type': 'number', 'minimum': 0.1, 'maximum': 1.0e6, 'required': True},
    'closed': {'type': 'boolean', 'default': False},
    'requirements': REQUIREMENTS,
}
LOSSES = [
    'Coordinates are the parsed binary64 values of longitude-first decimal degrees on the WGS84 ellipsoid; no datum, CRS, '
    'epoch, height, geoid or grid transformation is applied and no survey, measured-position, physical or regulatory accuracy is claimed.',
    'Distances follow the shortest ellipsoidal geodesic between consecutive waypoints; GeoJSON segments between published '
    'vertices are straight in longitude/latitude (RFC 7946), not geodesic.',
    'Supported geography: every point of every leg within |latitude| <= 75 degrees, no antimeridian crossing or touching, legs '
    '0.01 m to 5000 km, total <= 20000 km, 2-500 waypoints and at most 10000 rows.',
    'An optional endpoint gap is evaluated only inside the same domain as a leg (<= 5000 km, no antimeridian, whole geodesic '
    'within the band); otherwise the requirement is refused with ENDPOINT_GAP_OUTSIDE_DOMAIN.',
    'Stations and waypoints merge only when chainages are bitwise equal; adjacent rows may differ by a few ulps, share a '
    'presentation label and leave a tiny nonzero final interval. Numeric chainage is authoritative.',
    'Requirement states express numerical agreement under a conditional engineering model, not measurement, statistical or '
    'regulatory certification; only met requirements give an accepted deliverable.',
]
NUMERICAL_MODEL = {
    'tolerance': 'tau(s) = 1e-6 m + 1e-12 s for a geodesic distance s; station positions 2 tau(leg); consecutive steps 4 tau(leg)',
    'adequacy': 'every independent evaluation must resolve to tau/10 at its own distance scale: legs and the endpoint gap '
                'tau(s)/10; station forward evaluations (direct residual + rounding estimate + propagated leg inverse error) '
                'tau(leg)/10; consecutive inverses tau(step)/10',
    'assumptions': ['coordinates are the parsed binary64 values of the captured decimals',
                    'each verified geodesic is the qualified local shortest solution (<= 5000 km, within the latitude band, no antimeridian)',
                    'floating-point and libm rounding follow the stated model (sin/cos/atan2 within about one ulp); the 1 mm '
                    'local-metric regime uses a stated curvature term; both are engineering estimates, not certified intervals'],
    'meaning': 'numerical agreement between pyproj/PROJ and an independent standard-library implementation of the same '
               'auxiliary-sphere theory, anchored by exact equator, meridian-quadrature and surface-ODE checks; not survey, '
               'datum, measured-position, physical or regulatory accuracy',
    'failClosed': 'if any adequacy check fails, the whole run fails with VERIFICATION_INDETERMINATE, even without requirements',
    'savedVerification': 'retained host evidence is recomputed and compared bitwise; qualified on the producing host and libm '
                         '(same-host relocation and canonical export supported); cross-host or cross-libm re-verification is not qualified',
    'nativeReadback': 'native readback is self-consistency only, never independent verification',
}
RECOVERY = {
    'UNSUPPORTED_GEOGRAPHY': 'keep every waypoint within |latitude| <= 75 and longitude strictly inside (-180, 180); split routes at the antimeridian',
    'ENDPOINT_GAP_OUTSIDE_DOMAIN': 'the gap from the last to the first waypoint must stay within 5000 km, inside the latitude band and away '
                                   'from the antimeridian; remove the endpoint gap requirement or add the closing path as legs',
    'ROUTE_LEG_TOO_LONG': 'add intermediate waypoints so that every leg is at most 5000 km',
    'ROUTE_LEG_TOO_SHORT': 'merge waypoints closer than 1 cm',
    'ROUTE_TOTAL_TOO_LONG': 'split the route into parts of at most 20000 km',
    'ROUTE_ROW_LIMIT': 'increase spacing_m or split the route so that at most 10000 rows are published',
    'ROUTE_LATITUDE_EXCURSION': 'add waypoints so that each leg stays within |latitude| <= 75 degrees',
}


def located(code, message, location='$', recovery=None, **observed):
    raise SchemaxisError(Fault(code, message, location, 'pipeline', observed=observed, recovery=recovery or RECOVERY.get(code)))


def tau(s):
    """Contract tolerance in metres for a geodesic distance s in metres."""
    return 1e-6 + 1e-12 * abs(s)


def plain(number):
    return format(number, 'f').rstrip('0').rstrip('.')


def binary64_screen(document):
    """Refuse integers that cannot become binary64 before the shared grammar converts them (OverflowError otherwise)."""
    requirements = document.get('requirements')
    requirements = requirements if isinstance(requirements, dict) else {}
    members = [('$.spacing_m', document.get('spacing_m'), OPTIONS['spacing_m']['minimum'], OPTIONS['spacing_m']['maximum'])]
    for name, bounds in requirements.items():
        if isinstance(bounds, dict):
            for key, value in bounds.items():
                members.append((f'$.requirements.{name}.{key}', value, 0, LIMITS['maxTotal_m' if name == 'totalLength_m' else 'maxLeg_m']))
    for location, value, low, high in members:
        if type(value) is int:
            try:
                float(value)
            except OverflowError:
                located('INVALID_ARGUMENT', 'integer is outside the finite binary64 range; distances are binary64 metres', location,
                        f'declare a number from {plain(low)} to {plain(high)} metres')


def validate(document):
    """Validate an authored document; return the effective options (defaults applied)."""
    keys(document, ('version', 'operation', *OPTIONS), '$')
    if document.get('version') != VERSION:
        fail('UNSUPPORTED_VERSION', 'select ' + VERSION, '$.version')
    if document.get('operation') != OPERATION:
        fail('UNKNOWN_FILTER', 'select ' + OPERATION, '$.operation')
    if 'ellipsoid' in document and document['ellipsoid'] != 'WGS84':
        located('UNSUPPORTED_ELLIPSOID', 'only the WGS84 ellipsoid is supported; a sphere or other ellipsoid is never substituted',
                '$.ellipsoid', 'declare ellipsoid WGS84 for WGS84 longitude/latitude waypoints')
    if 'coordinateOrder' in document and document['coordinateOrder'] != 'lonLat':
        located('INVALID_ARGUMENT', 'coordinates are longitude first; latitude-first input is never guessed', '$.coordinateOrder',
                'declare coordinateOrder lonLat and supply lon_deg,lat_deg columns')
    binary64_screen(document)
    p = validate_arguments(OPTIONS, {k: v for k, v in document.items() if k in OPTIONS}, location='$')
    # Distances are binary64 throughout: an authored integer spacing or bound becomes its float
    # value, so k * spacing_m is one floating multiplication on host and native alike.
    p['spacing_m'] = float(p['spacing_m'])
    for requirement in p.get('requirements', {}).values():
        for key in list(requirement):
            requirement[key] = float(requirement[key])
    source = Path(p['source'])
    if '\x00' in p['source'] or not source.is_absolute() or source.suffix.lower() != '.csv':
        located('INVALID_ROUTE_SOURCE', 'select an absolute local .csv waypoint file', '$.source')
    requirements = p.get('requirements', {})
    total = requirements.get('totalLength_m')
    if total is not None:
        if not total:
            located('INVALID_REQUIREMENT', 'declare a minimum and/or maximum total length in metres', '$.requirements.totalLength_m')
        if 'minimum' in total and 'maximum' in total and not total['minimum'] < total['maximum']:
            located('INVALID_REQUIREMENT', 'minimum must be below maximum', '$.requirements.totalLength_m')
    if 'endpointGap_m' in requirements and p['closed']:
        located('REQUIREMENT_NOT_APPLICABLE', 'a closed route returns to its start through the closing leg and has no endpoint gap', GAP,
                'remove the endpoint gap requirement or declare an open route')
    return p


def parse_waypoints(data):
    """Strict ASCII waypoint CSV -> (points [[lon, lat]], names). Arithmetic uses the parsed binary64 values."""
    if len(data) > LIMITS['maxSourceBytes']:
        located('ROUTE_FILE_LIMIT', 'waypoint CSV exceeds 1 MiB', '$.source', 'split the route or remove unused columns')
    try:
        rows = list(csv.reader(io.StringIO(data.decode('ascii'), newline=''), strict=True))
    except (UnicodeError, csv.Error) as error:
        located('INVALID_ROUTE_CSV', 'use ASCII comma-separated text: ' + str(error), '$.source')
    if not rows:
        located('INVALID_ROUTE_CSV', 'the CSV needs a header and waypoint rows', '$.source')
    header = rows[0]
    if header in (['lat_deg', 'lon_deg'], ['name', 'lat_deg', 'lon_deg']):
        located('INVALID_ROUTE_CSV', 'latitude-first columns are not accepted and never guessed', 'line 1',
                'reorder the columns to lon_deg,lat_deg (optionally preceded by name)')
    if header not in (['lon_deg', 'lat_deg'], ['name', 'lon_deg', 'lat_deg']):
        located('INVALID_ROUTE_CSV', 'header must be lon_deg,lat_deg or name,lon_deg,lat_deg', 'line 1')
    named = len(header) == 3
    body = rows[1:]
    if not 2 <= len(body) <= LIMITS['maxWaypoints']:
        located('ROUTE_WAYPOINT_LIMIT', f"declare 2 to {LIMITS['maxWaypoints']} waypoints", '$.source', observed=len(body))
    points, names = [], []
    for i, row in enumerate(body):
        at = f'line {i + 2}'
        if len(row) != len(header):
            located('INVALID_ROUTE_CSV', 'row width differs from the header (blank lines are not allowed)', at)
        if named:
            if not NAME.fullmatch(row[0]) or row[0] != row[0].strip():
                located('INVALID_ROUTE_CSV', 'names use ASCII letters, digits, spaces and ._()+/- (at most 40, no edge spaces)', at)
            names.append(row[0])
        else:
            names.append(f'WP{i + 1}')
        cells = row[-2:]
        if any(not NUMBER.fullmatch(cell) for cell in cells):
            located('INVALID_ROUTE_CSV', 'coordinates must be plain decimal numbers without spaces, nan, inf or separators', at)
        lon, lat = float(cells[0]), float(cells[1])
        if not (math.isfinite(lon) and math.isfinite(lat)):
            located('INVALID_ROUTE_CSV', 'coordinates must be finite binary64 values', at)
        if not -180 < lon < 180:
            located('UNSUPPORTED_GEOGRAPHY', 'longitude must lie strictly between -180 and 180 degrees', at)
        if not -LIMITS['maxPathLatitude_deg'] <= lat <= LIMITS['maxPathLatitude_deg']:
            located('UNSUPPORTED_GEOGRAPHY', 'latitude must lie within [-75, 75] degrees', at)
        if points and points[-1] == [lon, lat]:
            located('ROUTE_COINCIDENT_WAYPOINTS', 'consecutive waypoints coincide', at, 'remove the repeated waypoint')
        points.append([lon, lat])
    return points, names


def chord(p, q):
    """Straight-line (ECEF) distance: a rigorous lower bound on the geodesic, with 1e-12 slack."""
    def ecef(lon, lat):
        sp, cp = math.sin(math.radians(lat)), math.cos(math.radians(lat))
        n = geodesy.A / math.sqrt(1 - geodesy.E2 * sp * sp)
        return n * cp * math.cos(math.radians(lon)), n * cp * math.sin(math.radians(lon)), n * (1 - geodesy.E2) * sp
    return math.dist(ecef(*p), ecef(*q)) * (1 - 1e-12)


def surface_upper(p, q):
    """Length of a meridian-then-parallel surface path: a rigorous upper bound, with 1e-12 slack."""
    m_max = geodesy.A / math.sqrt(1 - geodesy.E2)
    return (m_max * abs(math.radians(q[1] - p[1])) + geodesy.A * abs(math.radians(geodesy.wrap180(q[0] - p[0])))) * (1 + 1e-12)


def gap_domain_precheck(p, q):
    """Conclusive host refusals for the endpoint gap (last -> first waypoint)."""
    if abs(q[0] - p[0]) >= 180:
        located('ENDPOINT_GAP_OUTSIDE_DOMAIN', 'the endpoint gap geodesic crosses or touches the antimeridian', GAP)
    if chord(p, q) > LIMITS['maxLeg_m']:
        located('ENDPOINT_GAP_OUTSIDE_DOMAIN', 'the endpoint gap certainly exceeds the qualified 5000 km', GAP)


def native_config(p, points, names):
    """Conclusive route prechecks, then the exact native configuration (no native work is done when they refuse)."""
    closed = p['closed']
    if points[-1] == points[0]:
        located('ROUTE_CLOSURE_AMBIGUOUS', 'the last waypoint repeats the first', '$.source',
                'closed routes add the closing leg themselves; omit the repeated waypoint and declare closed as intended')
    route = points + ([points[0]] if closed else [])
    lower_total = 0.0
    for i in range(len(route) - 1):
        a, b = route[i], route[i + 1]
        at = f'leg {i + 1}'
        if abs(b[0] - a[0]) >= 180:
            located('UNSUPPORTED_GEOGRAPHY', 'the leg crosses or touches the antimeridian', at)
        lower = chord(a, b)
        if lower > LIMITS['maxLeg_m']:
            located('ROUTE_LEG_TOO_LONG', 'the leg certainly exceeds 5000 km', at)
        if surface_upper(a, b) < LIMITS['minLeg_m']:
            located('ROUTE_LEG_TOO_SHORT', 'the leg is certainly shorter than 1 cm', at)
        lower_total += lower
    if lower_total > LIMITS['maxTotal_m']:
        located('ROUTE_TOTAL_TOO_LONG', 'the route certainly exceeds 20000 km')
    if len(route) + math.floor(lower_total / p['spacing_m']) > LIMITS['maxRows']:
        located('ROUTE_ROW_LIMIT', 'the route certainly publishes more than 10000 rows', '$.spacing_m')
    requested = 'endpointGap_m' in p.get('requirements', {})
    if requested:
        gap_domain_precheck(points[-1], points[0])
    return {'waypoints': points, 'names': names, 'closed': closed, 'spacing_m': p['spacing_m'],
            'limits': {k: LIMITS[k] for k in ('minLeg_m', 'maxLeg_m', 'maxTotal_m', 'maxRows', 'maxPathLatitude_deg')},
            'endpointGap': requested}


def chainage_label(chainage):
    """Presentation label km+metres from integer millimetres; numeric chainage is authoritative."""
    mm = round(chainage * 1000)
    return f'{mm // 1000000}+{(mm % 1000000) // 1000:03d}.{mm % 1000:03d}'


def parse_table(data, columns, name, integers=('row', 'leg', 'kind', 'waypoint', 'from_waypoint', 'to_waypoint')):
    """Strict numeric publication table: exact header, plain numbers, integer index columns, finite within 1e100."""
    try:
        rows = list(csv.reader(io.StringIO(data.decode('ascii'), newline=''), strict=True))
    except (UnicodeError, csv.Error) as error:
        fail('VERIFICATION_FAILED', 'unreadable table: ' + str(error), name)
    if not rows or rows[0] != columns:
        fail('VERIFICATION_FAILED', 'table header differs', name)
    out = []
    for i, row in enumerate(rows[1:]):
        at = f'{name} line {i + 2}'
        if len(row) != len(columns) or any(not NUMBER.fullmatch(c) for c in row):
            fail('VERIFICATION_FAILED', 'rectangular plain numeric cells required', at)
        record = {}
        for column, cell in zip(columns, row):
            if column in integers:
                if not re.fullmatch(r'0|[1-9][0-9]{0,5}', cell):
                    fail('VERIFICATION_FAILED', 'index columns are small non-negative integers', at)
                record[column] = int(cell)
            else:
                value = float(cell)
                if not math.isfinite(value) or abs(value) > 1e100:
                    fail('VERIFICATION_FAILED', 'non-finite or out-of-range number', at)
                record[column] = value
        out.append(record)
    return out


def expected_rows(lengths, spacing, cap=LIMITS['maxRows']):
    """Replicate the declared chainage rule exactly: fsum prefix sums, k*spacing stations, bitwise merges."""
    chainage = [0.0] + [math.fsum(lengths[:i + 1]) for i in range(len(lengths))]
    rows = [{'chainage': 0.0, 'leg': 1, 'kind': 3, 'waypoint': 1}]
    k = 1
    n = len(lengths)
    for i in range(n):
        end = chainage[i + 1]
        while k * spacing < end:
            rows.append({'chainage': k * spacing, 'leg': i + 1, 'kind': 1, 'waypoint': 0})
            k += 1
            if len(rows) > cap:
                return chainage, None
        merged = k * spacing == end
        if merged:
            k += 1
        rows.append({'chainage': end, 'leg': min(i + 2, n), 'kind': 3 if merged else 2, 'waypoint': i + 2})
    if len(rows) > cap:
        return chainage, None
    for r in rows:
        r['offset'] = r['chainage'] - chainage[r['leg'] - 1]
    return chainage, rows


def three_state(value, band, bounds):
    """Host decision against a numerical band: met, unmet or indeterminate (never forced)."""
    lo, hi = value - band, value + band
    if ('maximum' in bounds and lo > bounds['maximum']) or ('minimum' in bounds and hi < bounds['minimum']):
        return 'unmet'
    if ('maximum' not in bounds or hi <= bounds['maximum']) and ('minimum' not in bounds or lo >= bounds['minimum']):
        return 'met'
    return 'indeterminate'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
