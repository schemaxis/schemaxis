"""Trusted native pyproj route-chainage worker; authored documents cannot supply code.

Copied into each run directory and launched as ``python -I -B native-worker.py STAGE`` with the
run directory as working directory. Stages:

* ``compute``: ``Geod.inv`` per leg (and for a requested endpoint gap), ``Geod.fwd`` per fixed
  station, the publications and ``native-result.json``.
* ``readback``: reopen the publications with standard-library parsers, require byte equality
  with a regeneration from ``native-result.json`` and native ``Geod.inv`` agreement between
  consecutive published rows. This is self-consistency only, never independent verification.

Structured refusals are written to ``<stage>-fault.json`` and exit with status 3. Importing this
module has no side effects; resource limits and environment checks apply only in ``main``.
"""
import csv
import hashlib
import io
import json
import math
import os
import stat
import sys

PYPROJ, PROJ = '3.8.0', '9.9.0'
WGS84_A, WGS84_F = 6378137.0, 1 / 298.257223563
LIMIT = 16 * 1024 ** 2
PUBLICATIONS = ('stations.csv', 'legs.csv', 'stations.geojson', 'route.geojson')
STATION_COLUMNS = ['row', 'chainage_m', 'lon_deg', 'lat_deg', 'leg', 'offset_m', 'azimuth_deg', 'kind', 'waypoint']
LEG_COLUMNS = ['leg', 'from_waypoint', 'to_waypoint', 'length_m', 'start_chainage_m', 'end_chainage_m',
               'azimuth_start_deg', 'azimuth_end_deg', 'back_azimuth_deg']
KINDS = {1: 'station', 2: 'waypoint', 3: 'waypoint+station'}
GAP = '$.requirements.endpointGap_m'
THREAD_VARIABLES = ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS')
PRIVATE_VARIABLES = ('HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME', 'XDG_CONFIG_HOME', 'PROJ_USER_WRITABLE_DIRECTORY')


class Refusal(Exception):
    def __init__(self, code, message, location='$'):
        super().__init__(message)
        self.code, self.location = code, location


def bounded(name):
    fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > LIMIT:
            raise Refusal('ROUTE_FILE_LIMIT', 'not a bounded regular file', name)
        data = stream.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise Refusal('ROUTE_FILE_LIMIT', 'file exceeds byte budget', name)
    return data


def strict_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique, parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def finite(values, what):
    for i, v in enumerate(values):
        if type(v) is not float or not math.isfinite(v):
            raise Refusal('NATIVE_NONFINITE', 'native geodesic returned a non-finite value', f'{what}[{i}]')


def azimuth360(value):
    """Clockwise from geodetic north, normalised to [0, 360); 360.0 after rounding maps to 0."""
    result = value % 360.0
    return 0.0 if result == 360.0 else result + 0.0


def wrap180(value):
    result = math.fmod(value, 360.0)
    if result > 180:
        result -= 360
    elif result <= -180:
        result += 360
    return result


def chainage_label(chainage):
    """Presentation label km+metres from integer millimetres; numeric chainage is authoritative."""
    mm = round(chainage * 1000)
    return f'{mm // 1000000}+{(mm % 1000000) // 1000:03d}.{mm % 1000:03d}'


def geod():
    """Return (Geod, runtime observation) after exact identity and network checks."""
    import pyproj
    import pyproj.network
    from pyproj import Geod
    pyproj.network.set_network_enabled(False)
    if pyproj.__version__ != PYPROJ or pyproj.proj_version_str != PROJ:
        raise Refusal('UNSUPPORTED_GEOD_RUNTIME', 'expected pyproj ' + PYPROJ + ' with PROJ ' + PROJ)
    if pyproj.network.is_network_enabled():
        raise Refusal('UNSUPPORTED_GEOD_RUNTIME', 'PROJ network access must be disabled')
    g = Geod(ellps='WGS84')
    if g.a != WGS84_A or g.f != WGS84_F or g.sphere:
        raise Refusal('UNSUPPORTED_GEOD_RUNTIME', 'Geod did not read back the WGS84 a and f')
    return g, {'pyproj': pyproj.__version__, 'proj': pyproj.proj_version_str, 'a': g.a, 'f': g.f,
               'network': pyproj.network.is_network_enabled(), 'python': sys.version.split()[0], 'pid': os.getpid()}


def max_path_latitude(lat1, lat2, az1, az2, f):
    """Largest |latitude| on a leg: endpoints, or the Clairaut vertex when azimuth crosses +-90."""
    peak = max(abs(lat1), abs(lat2))
    if math.cos(math.radians(az1)) * math.cos(math.radians(az2)) < 0:
        phi = math.radians(lat1)
        sb, cb = (1 - f) * math.sin(phi), math.cos(phi)
        cb /= math.hypot(sb, cb)
        sa0 = min(1.0, abs(math.sin(math.radians(az1)) * cb))
        beta = math.acos(sa0)
        peak = max(peak, math.degrees(math.atan(math.tan(beta) / (1 - f))))
    return peak


def compute(config, provider=geod):
    g, runtime = provider()
    limits = config['limits']
    points = [list(p) for p in config['waypoints']]
    names = list(config['names'])
    if config['closed']:
        points.append(points[0])
        names.append(names[0])
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    az1, back, length = g.inv(lons[:-1], lats[:-1], lons[1:], lats[1:], return_back_azimuth=True)
    az1b, azend, length2 = g.inv(lons[:-1], lats[:-1], lons[1:], lats[1:], return_back_azimuth=False)
    for values, what in ((az1, 'azimuth'), (back, 'backAzimuth'), (length, 'length'), (azend, 'azimuthEnd')):
        finite(values, what)
    if az1 != az1b or length != length2:
        raise Refusal('NATIVE_SEMANTICS_CHANGED', 'Geod.inv forward azimuth/distance depend on return_back_azimuth')
    for i in range(len(length)):
        if abs(wrap180(back[i] - azend[i] - 180.0)) > 1e-9:
            raise Refusal('NATIVE_SEMANTICS_CHANGED', 'back azimuth is not the end azimuth reversed', f'leg {i + 1}')
        if length[i] < limits['minLeg_m']:
            raise Refusal('ROUTE_LEG_TOO_SHORT', f"leg is shorter than {limits['minLeg_m']} m", f'leg {i + 1}')
        if length[i] > limits['maxLeg_m']:
            raise Refusal('ROUTE_LEG_TOO_LONG', f"leg exceeds {limits['maxLeg_m']} m", f'leg {i + 1}')
        if max_path_latitude(lats[i], lats[i + 1], az1[i], azend[i], g.f) > limits['maxPathLatitude_deg']:
            raise Refusal('ROUTE_LATITUDE_EXCURSION', 'geodesic leaves the supported latitude band', f'leg {i + 1}')
    # Optional endpoint gap: only when requested, and only inside the qualified leg domain
    # (<= 5000 km, no antimeridian, whole geodesic within the band). No minimum distance.
    gap = None
    if config['endpointGap']:
        p_lon, p_lat, q_lon, q_lat = lons[-1], lats[-1], lons[0], lats[0]
        if abs(q_lon - p_lon) >= 180:
            raise Refusal('ENDPOINT_GAP_OUTSIDE_DOMAIN', 'endpoint gap geodesic crosses or touches the antimeridian', GAP)
        gaz1, gback, gaps = g.inv([p_lon], [p_lat], [q_lon], [q_lat], return_back_azimuth=True)
        _gaz, gazend, _gs = g.inv([p_lon], [p_lat], [q_lon], [q_lat], return_back_azimuth=False)
        for values, what in ((gaz1, 'gapAzimuth'), (gback, 'gapBackAzimuth'), (gaps, 'endpointGap'), (gazend, 'gapAzimuthEnd')):
            finite(values, what)
        if gaps[0] > limits['maxLeg_m']:
            raise Refusal('ENDPOINT_GAP_OUTSIDE_DOMAIN', f"endpoint gap exceeds the qualified {limits['maxLeg_m']} m", GAP)
        if max_path_latitude(p_lat, q_lat, gaz1[0], gazend[0], g.f) > limits['maxPathLatitude_deg']:
            raise Refusal('ENDPOINT_GAP_OUTSIDE_DOMAIN', 'endpoint gap geodesic leaves the supported latitude band', GAP)
        gap = gaps[0]
    chainage = [0.0] + [math.fsum(length[:i + 1]) for i in range(len(length))]
    total = chainage[-1]
    if total > limits['maxTotal_m']:
        raise Refusal('ROUTE_TOTAL_TOO_LONG', f"route exceeds {limits['maxTotal_m']} m")
    spacing = config['spacing_m']
    rows = []

    def add(row):
        if len(rows) >= limits['maxRows']:
            raise Refusal('ROUTE_ROW_LIMIT', f"route would publish more than {limits['maxRows']} rows; increase spacing", '$.spacing_m')
        rows.append(row)

    nlegs = len(length)
    add({'chainage': 0.0, 'leg': 1, 'kind': 3, 'waypoint': 1})
    k = 1
    for i in range(nlegs):
        end = chainage[i + 1]
        while k * spacing < end:
            add({'chainage': k * spacing, 'leg': i + 1, 'kind': 1, 'waypoint': 0})
            k += 1
        merged = k * spacing == end  # bitwise merge only; no tolerance
        if merged:
            k += 1
        add({'chainage': end, 'leg': min(i + 2, nlegs), 'kind': 3 if merged else 2, 'waypoint': i + 2})
    stations = [r for r in rows if r['kind'] == 1]
    for r in rows:
        r['offset'] = r['chainage'] - chainage[r['leg'] - 1]
    if stations:
        slon, slat, saz = g.fwd([lons[r['leg'] - 1] for r in stations], [lats[r['leg'] - 1] for r in stations],
                                [az1[r['leg'] - 1] for r in stations], [r['offset'] for r in stations],
                                return_back_azimuth=False)
        for values, what in ((slon, 'stationLon'), (slat, 'stationLat'), (saz, 'stationAzimuth')):
            finite(values, what)
        for r, lo, la, az in zip(stations, slon, slat, saz):
            if not (-180 < lo < 180) or abs(la) > limits['maxPathLatitude_deg'] + 1e-9:
                raise Refusal('ROUTE_LATITUDE_EXCURSION', 'station leaves the supported geography', f"leg {r['leg']}")
            r['lon'], r['lat'], r['azimuth'] = lo, la, az
    last = len(rows) - 1
    for index, r in enumerate(rows):
        r['row'] = index + 1
        if r['kind'] != 1:
            w = r['waypoint'] - 1
            r['lon'], r['lat'] = lons[w], lats[w]   # captured binary64 values, never regenerated
            r['azimuth'] = azend[nlegs - 1] if index == last else az1[r['leg'] - 1]
        r['azimuth'] = azimuth360(r['azimuth'])
    legs = [{'leg': i + 1, 'from': i + 1, 'to': i + 2, 'length': length[i], 'start': chainage[i], 'end': chainage[i + 1],
             'azStart': azimuth360(az1[i]), 'azEnd': azimuth360(azend[i]), 'back': azimuth360(back[i])} for i in range(nlegs)]
    deflection = {}
    for i in range(1, nlegs):
        deflection[str(i + 1)] = wrap180(az1[i] - azend[i - 1])
    if config['closed']:
        deflection['closure'] = wrap180(az1[0] - azend[nlegs - 1])
    return runtime, {'legs': legs, 'rows': rows, 'names': names, 'total': total, 'gap': gap, 'deflection': deflection,
                     'closed': config['closed'], 'spacing': spacing}


def csv_text(columns, records):
    stream = io.StringIO()
    writer = csv.writer(stream, lineterminator='\n')
    writer.writerow(columns)
    for record in records:
        writer.writerow([repr(v) if type(v) is float else str(v) for v in record])
    return stream.getvalue()


def publications(result):
    rows, legs, names = result['rows'], result['legs'], result['names']
    last = len(rows)
    station_records = [[r['row'], r['chainage'], r['lon'], r['lat'], r['leg'], r['offset'], r['azimuth'], r['kind'], r['waypoint']] for r in rows]
    leg_records = [[l['leg'], l['from'], l['to'], l['length'], l['start'], l['end'], l['azStart'], l['azEnd'], l['back']] for l in legs]
    features = []
    for r in rows:
        if r['kind'] == 1:
            deflection = None
        elif r['row'] == last and result['closed']:
            deflection = result['deflection']['closure']
        else:
            deflection = result['deflection'].get(str(r['waypoint'])) if r['row'] != last else None
        features.append({'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [r['lon'], r['lat']]},
                         'properties': {'row': r['row'], 'label': chainage_label(r['chainage']), 'chainage_m': r['chainage'],
                                        'leg': r['leg'], 'offset_m': r['offset'], 'azimuth_deg': r['azimuth'],
                                        'kind': KINDS[r['kind']], 'waypoint': r['waypoint'] or None,
                                        'name': names[r['waypoint'] - 1] if r['waypoint'] else None,
                                        'deflection_deg': deflection}})
    route = []
    for l in legs:
        # Rows carry their outgoing leg, so a leg's own rows start at its first waypoint; the end
        # waypoint row belongs to the next leg except for the final row.
        vertices = [r for r in rows if r['leg'] == l['leg']]
        if l['leg'] < len(legs):
            vertices.append(next(r for r in rows if r['kind'] != 1 and r['waypoint'] == l['to']))
        route.append({'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': [[r['lon'], r['lat']] for r in vertices]},
                      'properties': {'leg': l['leg'], 'from_waypoint': l['from'], 'to_waypoint': l['to'],
                                     'from_name': names[l['from'] - 1], 'to_name': names[l['to'] - 1],
                                     'length_m': l['length'], 'start_chainage_m': l['start'], 'end_chainage_m': l['end'],
                                     'azimuth_start_deg': l['azStart'], 'azimuth_end_deg': l['azEnd'], 'back_azimuth_deg': l['back']}})

    def geojson(items):
        return json.dumps({'type': 'FeatureCollection', 'features': items}, allow_nan=False, sort_keys=True, separators=(',', ':')) + '\n'

    return {'stations.csv': csv_text(STATION_COLUMNS, station_records), 'legs.csv': csv_text(LEG_COLUMNS, leg_records),
            'stations.geojson': geojson(features), 'route.geojson': geojson(route)}


def write_json(name, value):
    temporary = name + '.tmp'
    with open(temporary, 'w', encoding='ascii') as stream:
        stream.write(json.dumps(value, allow_nan=False, sort_keys=True) + '\n')
    os.replace(temporary, name)


def write_inputs(stage, names):
    write_json(stage + '-inputs.json', {p: hashlib.sha256(bounded(p)).hexdigest() for p in names})


def readback(provider=geod):
    g, runtime = provider()
    computed = strict_json(bounded('native-result.json'))
    expected = publications(computed['result'])
    for name in PUBLICATIONS:
        if bounded(name).decode('utf-8') != expected[name]:
            raise Refusal('READBACK_MISMATCH', 'publication bytes differ from the native result', name)
    table = list(csv.reader(io.StringIO(bounded('stations.csv').decode('ascii')), strict=True))
    if table[0] != STATION_COLUMNS:
        raise Refusal('READBACK_MISMATCH', 'station header differs', 'stations.csv')
    rows = [[float(v) for v in row] for row in table[1:]]
    points = strict_json(bounded('stations.geojson'))['features']
    if len(points) != len(rows) or any(p['geometry']['coordinates'] != [r[2], r[3]] for p, r in zip(points, rows)):
        raise Refusal('READBACK_MISMATCH', 'station GeoJSON differs from the station table', 'stations.geojson')
    worst = 0.0
    if len(rows) > 1:
        _a, _b, dist = g.inv([r[2] for r in rows[:-1]], [r[3] for r in rows[:-1]], [r[2] for r in rows[1:]], [r[3] for r in rows[1:]])
        finite(dist, 'readbackDistance')
        for i, d in enumerate(dist):
            step = rows[i + 1][1] - rows[i][1]
            worst = max(worst, abs(d - step) / (1e-6 + 1e-12 * rows[i + 1][1]))
        if worst > 1:
            raise Refusal('READBACK_GEODESIC_MISMATCH', 'published consecutive rows do not reproduce their chainage step natively')
    return {'runtime': runtime, 'rows': len(rows), 'legs': len(computed['result']['legs']), 'publicationsExact': True,
            'consecutiveInverseWorstRatio': worst, 'scope': 'native self-consistency only'}


def hygiene():
    """Run-private environment, PROJ network off and one thread, checked before importing pyproj."""
    here = os.path.realpath(os.getcwd())
    for name in PRIVATE_VARIABLES:
        value = os.environ.get(name)
        if not value or os.path.commonpath([here, os.path.realpath(value)]) != here:
            raise Refusal('UNSUPPORTED_GEOD_RUNTIME', name + ' must name a private directory inside the run', name)
    if os.environ.get('PROJ_NETWORK') != 'OFF':
        raise Refusal('UNSUPPORTED_GEOD_RUNTIME', 'PROJ_NETWORK must be OFF', 'PROJ_NETWORK')
    for name in THREAD_VARIABLES:
        if os.environ.get(name) != '1':
            raise Refusal('UNSUPPORTED_GEOD_RUNTIME', name + ' must be 1', name)
    for name in ('PROJ_DATA', 'PROJ_LIB', 'PROJ_CURL_CA_BUNDLE'):
        os.environ.pop(name, None)  # use pyproj's own packaged data; never an inherited override


def main():
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024 ** 3, 2 * 1024 ** 3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 ** 2, 16 * 1024 ** 2))
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    stage = sys.argv[1] if len(sys.argv) == 2 else ''
    try:
        if stage not in ('compute', 'readback'):
            raise Refusal('UNKNOWN_STAGE', 'stage must be compute or readback')
        hygiene()
        config = strict_json(bounded('native-config.json'))
        if stage == 'compute':
            write_inputs(stage, ('native-config.json', 'native-worker.py'))
            runtime, result = compute(config)
            for name, text in publications(result).items():
                with open(name, 'w', encoding='ascii', newline='') as stream:
                    stream.write(text)
            write_json('native-result.json', {'runtime': runtime, 'result': result})
        else:
            write_inputs(stage, ('native-config.json', 'native-worker.py', 'native-result.json', *PUBLICATIONS))
            write_json('readback.json', readback())
    except Refusal as refusal:
        write_json(stage + '-fault.json' if stage in ('compute', 'readback') else 'worker-fault.json',
                   {'code': refusal.code, 'message': str(refusal), 'location': refusal.location, 'pid': os.getpid()})
        sys.exit(3)


if __name__ == '__main__':
    main()
