"""Typed read model of the E3 time and location workflows (host-only, standard library): item time records, edition and height evidence, location rows.

Everything is derived from the independent readers' field records of the internal E3 catalogue view (``catalogue.VERSION_E3``) and from raw IFD entries of the
captured bytes. ExifTool's own interpretation is never used to decide a value; the fixed native listing only anchors the independent decode.
"""
from fractions import Fraction
import re

from schemaxis.adaptors.exiftool import catalogue, locations, timecalc as tc

VIEW = catalogue.VERSION_E3
TIME_FIELDS = ('capturedLocalE3', 'capturedOffsetE3', 'capturedSubSecondE3', 'capturedUtcE3', 'digitizedLocalE3', 'digitizedOffset', 'digitizedSubSecond', 'digitizedUtc',
               'modifiedLocal', 'modifiedOffset', 'modifiedSubSecond', 'modifiedUtc', 'cameraMake', 'cameraModel', 'bodySerialNumber', 'gpsUtcExact', 'gpsUtcDate', 'gpsUtcTimeExact')
LOCATION_FIELDS = ('gpsLatitudeE3', 'gpsLongitudeE3', 'gpsDatumE3', 'gpsUtcExact', 'gpsUtcDate', 'gpsUtcTimeExact', 'gpsHorizontalError', 'gpsDirection', 'gpsDirectionReference')
WGS84_TEXTS = ('WGS-84', 'WGS84', 'WGS 84')
NULL_ISLAND = 'nullIsland'


def field_names(operation):
    """The assessed field ids of an E3 read operation, in catalogue order (internal: authors never select them)."""
    wanted = set(TIME_FIELDS if operation == 'reconcileTime' else LOCATION_FIELDS)
    return [name for name in catalogue.fields(VIEW) if name in wanted]


# ---------------------------------------------------------------- raw GPS and Exif IFD entries
def entries(payloads, ifd, tag):
    """``('ok', [Entry...])`` of one tag of one IFD, or ``('absent',)`` / ``('error', code)`` when the IFD is not readable."""
    state = payloads.exif
    if state[0] != 'ok':
        return ('absent',) if state[0] in ('absent', 'notApplicable') else ('error', state[2] if state[0] == 'error' else state[1])
    group = state[1]['ifds'].get(ifd)
    if group is None:
        return ('absent',)
    if group[0] == 'error':
        return ('error', group[1])
    return ('ok', [e for e in group[1] if e.tag == tag])


def exif_version_state(payloads):
    """``('absent',)``, ``('present', text)`` or ``('unresolved', code)``: a version tag that exists but is repeated, mistyped, malformed or inside a damaged IFD is unresolved, never absent."""
    state = payloads.exif
    if state[0] in ('absent', 'notApplicable'):
        return ('absent',)
    if state[0] != 'ok':
        return ('unresolved', 'EXIF_UNREADABLE')
    group = state[1]['ifds'].get('ExifIFD')
    if group is None:
        return ('absent',)
    if group[0] == 'error':
        return ('unresolved', 'EXIF_IFD_UNREADABLE')
    found = [e for e in group[1] if e.tag == 0x9000]
    if not found:
        return ('absent',)
    if len(found) > 1:
        return ('unresolved', 'EXIF_TAG_REPEATED')
    entry = found[0]
    if entry.raw is None or entry.kind != 7 or entry.count != 4 or not re.fullmatch(rb'[0-9]{4}', entry.raw):
        return ('unresolved', 'EXIF_VERSION_MALFORMED')
    return ('present', entry.raw.decode('ascii'))


def exif_version(payloads):
    state = exif_version_state(payloads)
    return state[1] if state[0] == 'present' else None


def gps_ifd_present(payloads):
    state = payloads.exif
    return state[0] == 'ok' and state[1]['ifds'].get('GPS', ('absent',))[0] == 'ok'


def gps_version_state(payloads):
    """``('absent',)``, ``('present', [bytes])`` or ``('unresolved', code)`` for GPSVersionID."""
    state = payloads.exif
    if state[0] != 'ok':
        return ('absent',) if state[0] in ('absent', 'notApplicable') else ('unresolved', 'EXIF_UNREADABLE')
    group = state[1]['ifds'].get('GPS')
    if group is None:
        return ('absent',)
    if group[0] == 'error':
        return ('unresolved', 'GPS_IFD_UNREADABLE')
    found = [e for e in group[1] if e.tag == 0x0000]
    if not found:
        return ('absent',)
    if len(found) > 1:
        return ('unresolved', 'EXIF_TAG_REPEATED')
    values = found[0].values()
    if not values or found[0].kind != 1 or len(values) != 4:
        return ('unresolved', 'GPS_VERSION_MALFORMED')
    return ('present', values)


def gps_version(payloads):
    state = gps_version_state(payloads)
    return state[1] if state[0] == 'present' else None


def edition(payloads):
    """``(evidence, infos, exifVersion, gpsVersionText)`` of the file as read (contract amendment A1; ``unresolved`` when a version tag cannot be resolved)."""
    exif_state, gps_state = exif_version_state(payloads), gps_version_state(payloads)
    version, gps = (exif_state[1] if exif_state[0] == 'present' else None), (gps_state[1] if gps_state[0] == 'present' else None)
    unresolved = tuple(name for name, st in (('exif', exif_state), ('gps', gps_state)) if st[0] == 'unresolved')
    evidence, infos = locations.classify_edition(version, gps, gps_ifd_present(payloads), unresolved)
    return evidence, infos, version, None if gps is None else '.'.join(str(x) for x in gps)


def raw_triple(payloads, tag):
    found = entries(payloads, 'GPS', tag)
    if found[0] != 'ok' or len(found[1]) != 1 or found[1][0].kind != 5 or found[1][0].count != 3 or found[1][0].raw is None:
        return None
    return [(int(n), int(d)) for n, d in found[1][0].values()]


# ---------------------------------------------------------------- time records for the clock model
def digits_of(record):
    return record['canonical'] if record['state'] == 'present' else None


def time_record(item_id, fields):
    """The clock-model item record of one captured file (see ``clockmodel``): the concordant recorded wall time with its fraction, the offset and the device keys."""
    local, offset, sub = fields['capturedLocalE3'], fields['capturedOffsetE3'], fields['capturedSubSecondE3']
    wall = digits = None
    if local['state'] == 'present':
        wall, text = tc.parse_local(local['canonical'])
        digits = ''
        if sub['state'] == 'present':
            digits = sub['canonical']
            wall += int(digits.ljust(9, '0')) if digits else 0
    off = tc.parse_offset(offset['canonical']) if offset['state'] == 'present' else None
    gps = fields['gpsUtcExact']
    gps_ns = tc.parse_utc(gps['canonical']) if gps['state'] == 'present' else None
    device = {name: {'state': fields[name]['state'], **({'value': fields[name]['canonical']} if fields[name]['state'] == 'present' else {})} for name in ('cameraMake', 'cameraModel', 'bodySerialNumber')}
    return {'id': item_id, 'wall': wall, 'digits': digits, 'offset': off, 'offsetState': offset['state'], 'gpsUtc': gps_ns, 'device': device, 'timeState': local['state'],
            'timeConflict': local['state'] == 'ambiguous' or offset['state'] == 'ambiguous', 'subSecondConflict': sub['state'] == 'ambiguous'}


# ---------------------------------------------------------------- the typed height
def height(payloads):
    """The typed altitude of a file (EXIF, and the legacy XMP pair as a separate concordance statement), or ``{'state': 'absent'}``."""
    evidence, infos, version, gps_text = edition(payloads)
    found = entries(payloads, 'GPS', 0x0006)
    ref_found = entries(payloads, 'GPS', 0x0005)
    out = {'state': 'absent', 'edition': {'evidence': evidence, 'exifVersion': version, 'gpsVersionId': gps_text}, 'flags': list(infos)}
    if found[0] == 'error':
        return {**out, 'state': 'unreadable', 'code': found[1]}
    if found[0] == 'ok' and len(found[1]) > 1:
        return {**out, 'state': 'ambiguous', 'code': 'EXIF_TAG_REPEATED'}
    if found[0] == 'ok' and found[1]:
        entry = found[1][0]
        values = entry.values() if entry.kind == 5 and entry.count == 1 and entry.raw is not None else None
        if not values or values[0][1] == 0:
            return {**out, 'state': 'unreadable', 'code': 'EXIF_TYPE_MISMATCH'}
        ref = None
        if ref_found[0] == 'ok' and len(ref_found[1]) > 1:
            return {**out, 'state': 'ambiguous', 'code': 'EXIF_COMPANION_REPEATED'}
        if ref_found[0] == 'ok' and ref_found[1]:
            r = ref_found[1][0]
            if r.kind != 1 or r.count != 1 or r.raw is None:
                return {**out, 'state': 'unreadable', 'code': 'EXIF_TYPE_MISMATCH'}
            ref = r.values()[0]
        try:
            typed = locations.read_height(ref, Fraction(*values[0]), evidence, infos)
        except locations.LocationProblem as problem:
            return {**out, 'state': 'unreadable', 'code': problem.code}
        signed = typed['magnitude'] * (typed['sign'] or 1)
        meters, exact = tc.decimal_text(signed if typed['signKnown'] else typed['magnitude'], 12)
        out.update(state='present', meters=meters, exact=exact, stored=[values[0][0], values[0][1]], signKnown=typed['signKnown'], reference=typed['reference'], basis=typed['basis'],
                   rawRef=ref, historicalLabel=typed['historicalLabel'], flags=typed['flags'])
        out['meaning'] = HEIGHT_MEANING[typed['reference']]
    return out


HEIGHT_MEANING = {'ellipsoidal': 'height above the ellipsoid of the recorded datum (Exif 3.x definition)',
                  'seaLevel': 'height relative to a sea-level reference (Exif 3.x references 2 and 3); the vertical datum is not recorded',
                  'unspecified': 'reference not established: legacy GPSAltitudeRef 0/1 was defined as sea level in Exif 2.32 and earlier, which CIPA later stated was erroneous for unadjusted GNSS heights'}


# ---------------------------------------------------------------- locate rows
def decimal(value):
    text, exact = tc.decimal_text(value, 12)
    return text, exact


def raw_position(payloads, axis):
    tag, ref_tag = (0x0002, 0x0001) if axis == 'lat' else (0x0004, 0x0003)
    triple = raw_triple(payloads, tag)
    found = entries(payloads, 'GPS', ref_tag)
    ref = None
    if found[0] == 'ok' and len(found[1]) == 1 and found[1][0].kind == 2 and found[1][0].raw is not None:
        ref = found[1][0].raw.rstrip(b'\0').decode('latin-1')
    return triple, ref


def position(fields, payloads):
    lat, lon = fields['gpsLatitudeE3'], fields['gpsLongitudeE3']
    out = {'state': 'absent'}
    states = {lat['state'], lon['state']}
    if states == {'present'}:
        la, exact_a = decimal(lat['canonical'])
        lo, exact_o = decimal(lon['canonical'])
        out = {'state': 'present', 'latitude': la, 'longitude': lo, 'exact': exact_a and exact_o}
        stored = {}
        for axis, record in (('latitude', lat), ('longitude', lon)):
            triple, ref = raw_position(payloads, 'lat' if axis == 'latitude' else 'lon')
            stored[axis] = {'rationals': None if triple is None else [list(x) for x in triple], 'ref': ref,
                            'flags': ['nonCanonicalSeconds60'] if triple and triple[2][1] and triple[2][0] == 60 * triple[2][1] else []}
        out['stored'] = stored
        out['concordance'] = {'latitude': lat['reconciliation'], 'longitude': lon['reconciliation']}
    elif 'ambiguous' in states:
        out = {'state': 'ambiguous'}
    elif states & {'unreadable', 'unsupported'}:
        bad = lat if lat['state'] in ('unreadable', 'unsupported') else lon
        out = {'state': bad['state'], 'codes': sorted({s['code'] for r in (lat, lon) for s in r['sources'] if s.get('code')})}
    elif states == {'absent'}:
        out = {'state': 'absent'}
    else:
        out = {'state': 'unreadable', 'code': 'GPS_COORDINATE_INCOMPLETE', 'message': 'only one of latitude and longitude is recorded'}
    return out


def flags_of(pos, datum_record, height_state, exact=None):
    """Information flags of a position, tested on the exact canonical values (``exact`` is ``(latitude, longitude)`` as Fractions), never on the cut decimal text."""
    flags = []
    if pos['state'] != 'present':
        return flags
    lat, lon = exact if exact is not None else (Fraction(pos['latitude']), Fraction(pos['longitude']))
    if lat == 0 and lon == 0:
        flags.append('nullIsland')
    for axis, refs in (('latitude', ('S',)), ('longitude', ('W',))):
        ref = pos['stored'][axis]['ref']
        if ref in refs and (lat if axis == 'latitude' else lon) == 0:
            flags.append('zeroWithSouthOrWestRef')
            break
    if abs(lat) == 90:
        flags.append('pole')
    if abs(lon) == 180:
        flags.append('antimeridian')
    if datum_record['state'] == 'present' and datum_record['canonical'] not in WGS84_TEXTS:
        flags.append('datumNotWgs84Text')
    if height_state.get('state') == 'present' and 'altitudeRefAbsent' in height_state.get('flags', []):
        flags.append('altitudeRefAbsent')
    return flags


def compare(pos, datum_record, target):
    """Distance in metres on the mean-radius sphere between the recorded position and a declared one (never a geodesic and never a datum conversion)."""
    from decimal import Decimal
    from schemaxis.adaptors.exiftool import geodesy
    if pos['state'] != 'present':
        return {'state': 'notComputed', 'reason': 'noPosition'}
    recorded = datum_record['canonical'] if datum_record['state'] == 'present' else None
    declared = target.get('datum')
    if declared is not None and recorded is not None and recorded != declared:
        return {'state': 'refused', 'code': 'DATUM_MISMATCH', 'recordedDatum': recorded, 'declaredDatum': declared}
    meters = geodesy.haversine_m((Decimal(pos['latitude']), Decimal(pos['longitude'])), (Decimal(target['latitude']), Decimal(target['longitude'])))
    return {'state': 'computed', 'meters': round(meters, 3), 'model': 'sphericalApproximation', 'radiusMeters': geodesy.MEAN_EARTH_RADIUS_M, 'datumUnverified': recorded is None or declared is None,
            'note': 'haversine on a sphere of the mean Earth radius; against the ellipsoidal geodesic the relative error is under about 0.5%'}


def location_row(item_id, fields, payloads, target=None):
    pos = position(fields, payloads)
    h = height(payloads)
    datum = fields['gpsDatumE3']
    row = {'id': item_id, 'position': pos, 'height': h, 'datum': {'state': datum['state'], 'value': datum['canonical'] if datum['state'] == 'present' else None, 'reconciliation': datum['reconciliation']},
           'gpsUtc': {'state': fields['gpsUtcExact']['state'], 'value': fields['gpsUtcExact']['canonical']},
           'horizontalError': {'state': fields['gpsHorizontalError']['state'], 'meters': None if fields['gpsHorizontalError']['state'] != 'present' else decimal(fields['gpsHorizontalError']['canonical'])[0]},
           'direction': {'state': fields['gpsDirection']['state'], 'degrees': None if fields['gpsDirection']['state'] != 'present' else decimal(fields['gpsDirection']['canonical'])[0],
                         'reference': fields['gpsDirectionReference']['canonical']},
           'flags': flags_of(pos, datum, h, (fields['gpsLatitudeE3']['canonical'], fields['gpsLongitudeE3']['canonical']) if pos['state'] == 'present' else None)}
    if target is not None:
        row['compareTo'] = compare(pos, datum, target)
    return row
