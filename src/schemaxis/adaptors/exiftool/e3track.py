"""Tracks of ``geotagFromTrack`` (host-only, standard library): captured GPX files, the span index, the photo instant and the per-item placement.

A track is untrusted input: each GPX file is captured into the run with its sha256 (an optional pin is honoured, the stat is checked before and after the
copy) and parsed only from the retained bytes by ``gpxtrack`` (no entity expansion, bounded depth, element and point counts, no network). The photo instant
is the recorded capture wall time minus the recorded (or declared, labelled assumed) UTC offset, optionally moved by a declared clock correction that is
applied to the photo instant only (the image's own time fields are rewritten by ``correctTime``, never here). A photograph is placed only on a fix or inside
a span, never by extrapolation; the interpolation model, its evidence and its limits are published per item and no accuracy is claimed.
"""
from decimal import Decimal
from fractions import Fraction
import hashlib
import os
from pathlib import Path
import stat

from schemaxis.adaptors.exiftool import clockmodel, e3read, edits, gpxtrack, timecalc as tc
from schemaxis.errors import fail

MAX_TRACKS = 8
TRACK_BYTES = gpxtrack.LIMITS['bytes']
TOTAL_TRACK_BYTES = 64 * 1024 * 1024
PLAN_BYTES = 64 * 1024 * 1024
INPUTS = 'inputs'
GPX_DATUM = 'WGS-84'
DEFAULTS = {'maxGapSeconds': 300, 'endpointSnapSeconds': 0, 'overlapAgreementMeters': '5'}
TRACK_DEFAULTS = {'invalidPoints': 'refuse', 'zonelessTimes': 'asSchema', 'elevation': 'ignore'}


def file_name(index, track_id): return '%s/track-%d-%s.gpx' % (INPUTS, index + 1, track_id)
PLAN_FILE = INPUTS + '/plan.json'


def capture_bytes(path, limit, code, at, **observed):
    """Read one regular file through one descriptor with a before/after stat identity check; the bytes and their stat identity."""
    try:
        before = os.lstat(path)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise ValueError('not a regular file')
        if before.st_size > limit:
            raise ValueError('larger than %d bytes' % limit)
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino):
                raise ValueError('the file identity changed after the pre-read check')
            data = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
        if len(data) > limit:
            raise ValueError('byte budget exceeded')
        if (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or len(data) != info.st_size:
            fail('TRACK_CHANGED_DURING_CAPTURE', 'the file changed while it was read', at, **observed)
        return data
    except (OSError, ValueError) as error:
        fail(code, 'select an intact regular local file within the byte budget: ' + str(error), at, **observed)


def capture_inputs(p, directory):
    """Capture the declared tracks and plan file into ``inputs/``; returns the record kept in ``captures.json`` (``{}`` when the operation has none)."""
    block = p['e3']
    record = {}
    if block.get('tracks'):
        (directory / INPUTS).mkdir(exist_ok=True)
        total, tracks = 0, []
        for index, track in enumerate(block['tracks']):
            at = '$.tracks[%d].path' % index
            data = capture_bytes(track['path'], TRACK_BYTES, 'TRACK_UNREADABLE', at, track=track['id'])
            total += len(data)
            if total > TOTAL_TRACK_BYTES:
                fail('TRACK_RESOURCE_LIMIT', 'the tracks exceed %d bytes in total' % TOTAL_TRACK_BYTES, at, track=track['id'])
            digest = hashlib.sha256(data).hexdigest()
            if track.get('sha256') and track['sha256'] != digest:
                fail('TRACK_HASH_MISMATCH', 'the track bytes differ from the pinned sha256', '$.tracks[%d].sha256' % index, track=track['id'], observed=digest)
            (directory / file_name(index, track['id'])).write_bytes(data)
            tracks.append({'id': track['id'], 'source': track['path'], 'file': file_name(index, track['id']), 'sha256': digest, 'bytes': len(data)})
        record['tracks'] = tracks
    if block.get('planFile'):
        (directory / INPUTS).mkdir(exist_ok=True)
        data = capture_bytes(block['planFile'], PLAN_BYTES, 'PLAN_UNREADABLE', '$.plan')
        (directory / PLAN_FILE).write_bytes(data)
        record['plan'] = {'source': block['planFile'], 'file': PLAN_FILE, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
    if block.get('clockPlanFile'):
        (directory / INPUTS).mkdir(exist_ok=True)
        data = capture_bytes(block['clockPlanFile'], PLAN_BYTES, 'PLAN_UNREADABLE', '$.photoTime.clockCorrection.plan')
        (directory / (INPUTS + '/clock-plan.json')).write_bytes(data)
        record['clockPlan'] = {'source': block['clockPlanFile'], 'file': INPUTS + '/clock-plan.json', 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
    return record


def parse_tracks(directory, inputs, block):
    """The parsed tracks of the retained bytes: ``[{'id', 'meta', 'data'}]``; a track fault fails the run (a track is a set-level input)."""
    out = []
    track_options = {**TRACK_DEFAULTS, **{k: v for k, v in block.get('track', {}).items() if k != 'datum1_0'}}
    invalid = track_options['invalidPoints']
    zoneless = 'refuse' if track_options['zonelessTimes'] == 'refuse' else 'utc' if track_options['zonelessTimes'] == 'utc' else 'asSchema'
    for index, record in enumerate(inputs['tracks']):
        data = (directory / record['file']).read_bytes()
        if hashlib.sha256(data).hexdigest() != record['sha256'] or len(data) != record['bytes']:
            fail('CAPTURE_CHANGED', 'a retained captured track differs from its capture record', record['file'], track=record['id'])
        try:
            parsed = gpxtrack.parse(data, invalid_points=invalid, zoneless=zoneless)
        except gpxtrack.TrackProblem as error:
            fail(error.code, error.message, '$.tracks[%d]' % index, track=record['id'], **error.observed)
        out.append({'id': record['id'], 'index': index, 'data': parsed, 'datum': datum_of(parsed, block)})
    return out


def datum_of(parsed, block):
    """The datum a track establishes: WGS-84 for GPX 1.1 (the schema says so); for 1.0 only an authored assumption, otherwise none."""
    if parsed['version'] == '1.1':
        return GPX_DATUM
    declared = block.get('track', {}).get('datum1_0')
    return declared


def span_index(tracks, block):
    gap = block.get('interpolation', {}).get('maxGapSeconds', DEFAULTS['maxGapSeconds'])
    return gpxtrack.SpanIndex([t['data'] for t in tracks], gap)


def track_report(tracks, index):
    docs = []
    for t in tracks:
        d = t['data']
        counts = d['counts']
        docs.append({'id': t['id'], 'sha256': d['sha256'], 'bytes': d['bytes'], 'version': d['version'], 'namespace': d['namespace'], 'counts': counts,
                     'invalid': d['invalid'], 'datum': t['datum'], 'timeRangeUtc': None if d['range'] is None else [tc.local_text(d['range'][0]), tc.local_text(d['range'][1])],
                     'segments': [r for r in index.segment_reports if r['track'] == t['index']],
                     'zoneNormalisation': {'zonelessReadAsUtc': counts['zonelessReadAsUtc'], 'offsetTimesConverted': counts['offsetTimesConverted']}})
    return {'tracks': docs, 'spans': {'duplicatesRemoved': index.duplicates, 'reversals': index.reversals, 'timeConflicts': len(index.conflict_times)}}


def fraction_ns(item_record):
    return item_record['wall']


def photo_instant(record, assumed, delta_ns, planned=None):
    """``(instant_ns, basis)`` of an item record, or a ``Refusal``: recorded offset first, else the group's assumed offset, else the offset a clock-correction plan sets
    (``planned`` is its ``{'wall', 'offset'}`` after state, which fixes the corrected instant without a before instant); there is no system time zone."""
    if record['wall'] is None:
        raise edits.Refusal('TIME_SOURCE_UNREADABLE' if record.get('timeState') in ('unreadable', 'unsupported') else 'OFFSET_UNKNOWN', 'the item has no readable recorded capture time', '$')
    if record['timeConflict'] or record['subSecondConflict']:
        raise edits.Refusal('TIME_SOURCES_CONFLICT' if record['timeConflict'] else 'TIME_SUBSECOND_CONFLICT', 'the recorded time sources of this item disagree', '$')
    if record['offset'] is not None:
        return tc.instant(record['wall'], record['offset']) - delta_ns, 'recordedOffset'
    if record.get('offsetState') in ('unreadable', 'unsupported', 'ambiguous'):
        raise edits.Refusal('TIME_SOURCE_UNREADABLE', 'the item records a UTC offset that cannot be resolved (%s); an assumed offset never replaces a recorded one' % record['offsetState'], '$', state=record['offsetState'])
    if assumed is not None:
        return tc.instant(record['wall'], assumed) - delta_ns, 'assumedOffset'
    if planned is not None:
        return tc.instant(planned['wall'], planned['offset']), 'plannedOffset'
    raise edits.Refusal('OFFSET_UNKNOWN', 'the item records no UTC offset and none is assumed for its device group; there is no system time zone to fall back on', '$')


def placement(index, instant, options, want_elevation):
    """The resolved placement of a UTC instant: the ``SpanIndex.resolve`` result with every decimal kept exact."""
    interpolation = {**DEFAULTS, **options.get('interpolation', {})}
    return index.resolve(instant, endpoint_snap_seconds=interpolation['endpointSnapSeconds'], overlap_agreement_meters=Decimal(interpolation['overlapAgreementMeters']), want_elevation=want_elevation)


QUANTUM9, QUANTUM3 = Decimal('1e-9'), Decimal('1e-3')


def text9(value): return format(value.quantize(QUANTUM9) + 0, 'f')
def text3(value): return format(value.quantize(QUANTUM3) + 0, 'f')


def public_placement(result):
    """The JSON form of a placement: degrees with exactly 9 decimals and metres with exactly 3 (so a verifier compares stable literals), other decimals as text."""
    out = {}
    for key, value in result.items():
        if key in ('latitude', 'longitude') and isinstance(value, Decimal):
            out[key] = text9(value)
        elif key == 'altitude' and isinstance(value, Decimal):
            out[key] = text3(value)
        elif isinstance(value, Decimal):
            out[key] = format(value, 'f')
        elif isinstance(value, Fraction):
            out[key] = '%d/%d' % (value.numerator, value.denominator)
        elif isinstance(value, dict):
            out[key] = public_placement(value)
        elif isinstance(value, list):
            out[key] = [public_placement(v) if isinstance(v, dict) else (format(v, 'f') if isinstance(v, Decimal) else v) for v in value]
        else:
            out[key] = value
    return out
