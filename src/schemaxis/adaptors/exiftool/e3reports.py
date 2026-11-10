"""Plan normalisation and publications of the E3 read operations ``reconcileTime`` and ``locate`` (host-only, standard library).

The plan echoes every declared input with its defaults made explicit; a reference time, an assumed offset or an ``assumeCorrect`` group is published as
declared by the author and is never verified. Reports are typed documents plus a fixed-column typed CSV; no value is rounded, no zone is inferred, no
position is verified, and nothing is converted between datums or between vertical references.
"""
from fractions import Fraction
import re

from schemaxis.adaptors.exiftool import clockmodel, e3read, locations, timecalc as tc
from schemaxis.errors import fail

TIME_REPORT_VERSION = 'schemaxis.exiftool.time-report/1'
LOCATION_REPORT_VERSION = 'schemaxis.exiftool.location-report/1'
TOLERANCE = re.compile(r'(\d{1,4})(?:\.(\d{1,9}))?', re.ASCII)
TIME_COLUMNS = (('item', 'text', False), ('group', 'text', True), ('groupState', 'text', False), ('basis', 'text', False), ('recordedLocal', 'text', True), ('recordedOffset', 'text', True),
                ('skewSeconds', 'text', True), ('proposedLocal', 'text', True), ('proposedOffset', 'text', True), ('findings', 'text', True))
LOCATION_COLUMNS = (('item', 'text', False), ('positionState', 'text', False), ('latitude', 'text', True), ('longitude', 'text', True), ('heightState', 'text', False), ('heightMeters', 'text', True),
                    ('heightReference', 'text', True), ('datum', 'text', True), ('flags', 'text', True))
TIME_LOSSES = [
    'Time is the recorded wall clock of each file; no time zone, daylight-saving rule or leap second is known. A UTC instant exists only where the same file records an offset or the author assumed one (labelled). A reference true time, an assumed offset and an assumeCorrect group are declared by the author and published as declared: they are never verified.',
    'Skew is recorded minus true, in exact seconds. Grouping by recorded device compares make, model and body serial text exactly with each field state kept; a missing or ambiguous identity is reported, never merged or guessed, and two bodies of one model without serial numbers are indistinguishable.',
    'The report is an analysis: nothing is written or corrected, and GPS time stamps are independent evidence compared with the proposed times, never used to estimate a skew unless the author lists a reference.']
LOCATION_LOSSES = [
    'Positions are what the file records, summed exactly from the stored rationals (seconds of exactly 60 are accepted as an exact non-canonical form). Stored precision is a serialisation property, not GPS accuracy, and no position is verified, geocoded or converted between datums.',
    'A recorded altitude is reported with its reference only as far as the file establishes it: the Exif 3.x references 0/1 (ellipsoidal) and 2/3 (sea level) are read by the edition evidence of the file; legacy 0/1 values are reported as unspecified, never converted, and no vertical datum is ever applied.',
    'Distances in compareTo are spherical (mean radius 6371008.8 m) and are labelled approximate; a recorded datum different from the declared one gives no distance.']


def tolerance_text(text, location, maximum=3600, minimum=0):
    match = TOLERANCE.fullmatch(text) if isinstance(text, str) else None
    value = Fraction(text) if match else None
    if value is None or value < minimum or value > maximum:
        fail('INVALID_ARGUMENT', 'use a non-negative decimal string of at most %d with up to 9 fractional digits' % maximum, location, value=str(text)[:24])
    return value


def clock_problem(error):
    fail(error.code, error.message, error.location, **error.observed)


def plan_reconcile(p, media):
    """The effective ``time`` block of a reconcileTime plan (defaults explicit; authored faults carry exact ``$`` locations)."""
    ids = [i['id'] for i in media['items']] if media['kind'] == 'items' else None
    groups = p.get('groups') or {'by': 'recordedDevice'}
    if groups['by'] == 'declared':
        if 'members' not in groups or 'keys' in groups or 'itemOverrides' in groups:
            fail('INVALID_ARGUMENT', 'declared groups list members; keys and itemOverrides belong to recordedDevice grouping', '$.groups')
        block_groups = {'by': 'declared', 'members': [{'group': m['group'], 'items': list(m['items'])} for m in groups['members']]}
    else:
        if 'members' in groups:
            fail('INVALID_ARGUMENT', 'members belong to declared grouping', '$.groups.members')
        block_groups = {'by': 'recordedDevice', 'keys': list(groups.get('keys') or clockmodel.DEFAULT_KEYS), 'itemOverrides': [dict(o) for o in groups.get('itemOverrides', [])]}
    references = []
    for index, entry in enumerate(p.get('references', [])):
        try:
            clockmodel.read_reference(entry, index)
        except clockmodel.ClockProblem as error:
            clock_problem(error)
        references.append({k: v for k, v in entry.items()})
    simultaneous = []
    for index, entry in enumerate(p.get('simultaneous', [])):
        tolerance_text(entry.get('toleranceSeconds', '1'), '$.simultaneous[%d].toleranceSeconds' % index)
        simultaneous.append({'items': list(entry['items']), 'toleranceSeconds': entry.get('toleranceSeconds', '1')})
    offsets, seen_groups = [], set()
    for index, entry in enumerate(p.get('assumedOffsets', [])):
        if entry['group'] in seen_groups:
            fail('INVALID_ARGUMENT', 'a group has more than one assumed offset', '$.assumedOffsets[%d].group' % index, value=entry['group'][:64])
        seen_groups.add(entry['group'])
        try:
            tc.parse_offset(entry['offset'], '$.assumedOffsets[%d].offset' % index)
        except tc.TimeProblem as error:
            fail('INVALID_ARGUMENT', error.message, '$.assumedOffsets[%d].offset' % index)
        offsets.append(dict(entry))
    tolerance = p.get('toleranceSeconds', '2')
    tolerance_text(tolerance, '$.toleranceSeconds')
    rate = p.get('maxDriftRate', '0.001')
    if tolerance_text(rate, '$.maxDriftRate', maximum=1) > Fraction(1, 100) or Fraction(rate) == 0:
        fail('INVALID_ARGUMENT', 'maxDriftRate is above 0 and at most 0.01 (seconds of skew per second)', '$.maxDriftRate', value=str(rate)[:24])
    if p.get('model', 'constant') != 'linearDrift' and any(k in p for k in ('maxDriftRate', 'maxDriftExtrapolationSeconds')):
        fail('INVALID_ARGUMENT', 'maxDriftRate and maxDriftExtrapolationSeconds apply to the linearDrift model only', '$.model')
    if ids is not None:
        known = set(ids)
        listed = ([('$.references[%d].item' % i, r['item']) for i, r in enumerate(references)] + [('$.simultaneous[%d].items' % i, x) for i, e in enumerate(simultaneous) for x in e['items']] +
                  [('$.groups.itemOverrides[%d].item' % i, o['item']) for i, o in enumerate(block_groups.get('itemOverrides', []))])
        for at, name in listed:
            if name not in known:
                fail('UNKNOWN_ITEM', 'the document names an item that is not in media.items', at, value=name[:64], items=ids[:20])
        if block_groups['by'] == 'declared':
            listed = [i for m in block_groups['members'] for i in m['items']]
            if sorted(listed) != sorted(ids):
                fail('GROUP_MEMBERSHIP_INVALID', 'every media item must belong to exactly one declared group and every named item must exist', '$.groups.members',
                     unknown=sorted(set(listed) - set(ids))[:20], uncovered=[i for i in ids if i not in listed][:20])
    return {'groups': block_groups, 'references': references, 'simultaneous': simultaneous, 'assumeCorrect': list(p.get('assumeCorrect', [])), 'assumedOffsets': offsets,
            'model': p.get('model', 'constant'), 'toleranceSeconds': tolerance, 'maxDriftRate': rate, 'maxDriftExtrapolationSeconds': p.get('maxDriftExtrapolationSeconds', 0),
            'gpsToleranceSeconds': p.get('gpsToleranceSeconds', 120)}


def plan_locate(p):
    target = p.get('compareTo')
    if target is None:
        return None
    try:
        lat = locations.parse_coordinate(target['latitude'], 'lat', '$.compareTo.latitude')
        lon = locations.parse_coordinate(target['longitude'], 'lon', '$.compareTo.longitude')
        datum = locations.parse_datum(target['datum'], '$.compareTo.datum') if 'datum' in target else None
    except locations.LocationProblem as error:
        fail(error.code, error.message, error.observed.get('field', '$.compareTo'))
    return {'latitude': format(lat['value'], 'f'), 'longitude': format(lon['value'], 'f'), **({'datum': datum} if datum is not None else {})}


# ---------------------------------------------------------------- publications
def time_documents(p, items, encode, csv_bytes, runtime):
    ok = [i for i in items if i['status'] == 'ok']
    records = [e3read.time_record(i['id'], i['fields']) for i in ok]
    try:
        report = clockmodel.reconcile(records, p['time'], [i['id'] for i in items if i['status'] != 'ok'])
    except clockmodel.ClockProblem as error:
        clock_problem(error)
    document = {'version': TIME_REPORT_VERSION, 'operation': 'reconcileTime', 'runtime': runtime, 'catalogue': p['catalogue'],
                'conventions': {'skew': 'recorded minus true, in exact decimal seconds (a trailing ~ marks a repeating decimal cut at 9 places); positive means the camera is ahead',
                                'instants': 'recordedInstant = recorded wall time minus the recorded (or declared, labelled assumed) UTC offset; no time zone or daylight-saving rule is used',
                                'declared': 'references, assumeCorrect and assumedOffsets are the author\'s declarations and are never verified'},
                'declared': p['time'], 'report': report, 'losses': TIME_LOSSES}
    table = [[r['id'], r['group'], r['groupState'], r['basis'], r['recordedLocal'], r['recordedOffset'], r['skewSeconds'], r['proposedLocal'], r['proposedOffset'],
              ';'.join(r['findings']) or None] for r in report['items']]
    return {'time-report.json': encode(document), 'time-report.csv': csv_bytes(TIME_COLUMNS, table)}


def location_documents(p, items, encode, csv_bytes, runtime, payloads_of):
    ok = [i for i in items if i['status'] == 'ok']
    rows = [e3read.location_row(i['id'], i['fields'], payloads_of(i), p.get('location')) for i in ok]
    document = {'version': LOCATION_REPORT_VERSION, 'operation': 'locate', 'runtime': runtime, 'catalogue': p['catalogue'], 'compareTo': p.get('location'),
                'conventions': {'latitude': 'signed decimal degrees, exact from the stored rationals (north positive)', 'longitude': 'signed decimal degrees, exact from the stored rationals (east positive)',
                                'height': 'metres with the reference the file establishes; legacy 0/1 references are unspecified', 'precision': 'storage precision only; no accuracy is claimed'},
                'items': rows, 'losses': LOCATION_LOSSES}
    table = []
    for r in rows:
        pos, h = r['position'], r['height']
        table.append([r['id'], pos['state'], pos.get('latitude'), pos.get('longitude'), h['state'], h.get('meters'), h.get('reference'), r['datum']['value'], ';'.join(r['flags']) or None])
    return {'location-report.json': encode(document), 'location.csv': csv_bytes(LOCATION_COLUMNS, table)}
