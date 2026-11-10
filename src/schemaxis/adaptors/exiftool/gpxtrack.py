"""Secure, bounded GPX track parsing and the span index used to place photographs on tracks (host-only, standard library).

A track is untrusted XML. Before any parser runs the decoded text is scanned and every markup declaration (``<!DOCTYPE``, ``<!ENTITY``, ``<!ATTLIST`` and
the like) and every processing instruction other than the leading XML declaration is refused, so no internal or external entity can exist and expat only
resolves the five predefined entities. The document is then parsed incrementally; finished elements are discarded, and depth, element, attribute, text
and point counts are bounded. Nothing here opens a URL or the network.

The span index is one abstraction for several tracks, segments, duplicates, reversals and gaps: a *span* joins two consecutive timed, valid points of one
segment. A photograph is placed only inside a span (interpolated), on a fix (exact), or, when the author allows it, at a nearby segment endpoint.
There is never extrapolation, and segments and tracks are never bridged.
"""
from bisect import bisect_right
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from fractions import Fraction
import hashlib
import re
from xml.etree import ElementTree

from schemaxis.adaptors.exiftool import geodesy, timecalc as tc

NS11 = 'http://www.topografix.com/GPX/1/1'
NS10 = 'http://www.topografix.com/GPX/1/0'
LIMITS = {'bytes': 32 * 1024 * 1024, 'depth': 32, 'elements': 4_000_000, 'attribute': 4096, 'text': 4096, 'points': 1_000_000}
MAX_REPORTED = 32
MAX_OVERLAP_CANDIDATES = 32
CHUNK = 65536
DECIMAL = re.compile(r'[+-]?(\d+(\.\d*)?|\.\d+)', re.ASCII)
TIME = re.compile(r'(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})?', re.ASCII)
DECLARATION = re.compile(r'<\?xml(?=[\s?])[^>]*\?>')
ENCODING = re.compile(r'<\?xml[^>]*?\sencoding\s*=\s*["\']([^"\']*)["\']')
MARKUP_DECLARATION = re.compile(r'<!(?!--|\[CDATA\[)')
PROCESSING_INSTRUCTION = re.compile(r'<\?')
UTF16_OR_32 = (b'\xff\xfe', b'\xfe\xff', b'\x00\x00\xfe\xff')
QUANTUM9 = Decimal('1e-9')
QUANTUM3 = Decimal('1e-3')
ELE_MAX = Decimal(100000)


class TrackProblem(ValueError):
    """A refused track with a stable code from the E3 contract; ``observed`` may hold a line/column or a bounded list of locations."""

    def __init__(self, code, message, **observed):
        super().__init__(message)
        self.code, self.message, self.observed = code, message, observed


class Point:
    """One timed, valid track point. Coordinates stay decimal strings until used, so a million points stay cheap."""
    __slots__ = ('t', 'lat', 'lon', 'ele', 'ordinal', 'hdop', 'sat', 'fix')

    def __init__(self, t, lat, lon, ele, ordinal, hdop=None, sat=None, fix=None):
        self.t, self.lat, self.lon, self.ele, self.ordinal, self.hdop, self.sat, self.fix = t, lat, lon, ele, ordinal, hdop, sat, fix

    def position(self): return Decimal(self.lat), Decimal(self.lon)
    def same_place(self, other): return Decimal(self.lat) == Decimal(other.lat) and Decimal(self.lon) == Decimal(other.lon) and (Decimal(self.ele) if self.ele else None) == (Decimal(other.ele) if other.ele else None)


def to_decimal(text):
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


# ---------------------------------------------------------------- admission of the bytes
def decode(data, limits=LIMITS):
    """The text of a track after the encoding and markup-declaration gates; raises ``TrackProblem``."""
    if len(data) > limits['bytes']:
        raise TrackProblem('TRACK_RESOURCE_LIMIT', 'a track is at most %d bytes' % limits['bytes'], bytes=len(data))
    if data.startswith(UTF16_OR_32) or data[:4] in (b'\x00<\x00?', b'<\x00?\x00', b'\xff\xfe\x00\x00'):
        raise TrackProblem('TRACK_ENCODING_UNSUPPORTED', 'only UTF-8 (and US-ASCII) tracks are read; UTF-16 and UTF-32 are not')
    body = data[3:] if data.startswith(b'\xef\xbb\xbf') else data
    try:
        text = body.decode('utf-8')
    except UnicodeDecodeError as error:
        raise TrackProblem('TRACK_MALFORMED', 'the track is not valid UTF-8', byteOffset=error.start)
    head = DECLARATION.match(text)
    declared = ENCODING.match(text) if head else None
    if declared and declared.group(1).lower().replace('_', '-') not in ('utf-8', 'us-ascii'):
        raise TrackProblem('TRACK_ENCODING_UNSUPPORTED', 'the XML declaration names an encoding other than UTF-8 or US-ASCII', encoding=declared.group(1)[:32])
    found = MARKUP_DECLARATION.search(text)
    if found:
        raise TrackProblem('TRACK_DTD_REFUSED', 'markup declarations (DOCTYPE, ENTITY, ATTLIST, ...) are refused before parsing', offset=found.start())
    for found in PROCESSING_INSTRUCTION.finditer(text):
        if found.start() == 0 and head:
            continue
        raise TrackProblem('TRACK_DTD_REFUSED', 'processing instructions other than the XML declaration are refused', offset=found.start())
    return text


# ---------------------------------------------------------------- parsing
def local_name(tag, namespace):
    prefix = '{' + namespace + '}'
    return tag[len(prefix):] if tag.startswith(prefix) else None


def parse_time(text, version, zoneless, counts):
    """UTC nanoseconds of a GPX ``time``, or ``(None, reason)``."""
    match = TIME.fullmatch(text.strip())
    if not match:
        return None, 'timeSyntax'
    y, mo, d, h, mi, s = (int(match.group(i)) for i in range(1, 7))
    if (h, mi, s) == (24, 0, 0) or s == 60:
        return None, 'leapSecondOrMidnight24'
    zone = match.group(8)
    try:
        wall = tc.from_parts(y, mo, d, h, mi, s, int((match.group(7) or '').ljust(9, '0') or '0'))
    except tc.TimeProblem as problem:
        return None, 'timeRange' if problem.code == 'TIME_OUT_OF_RANGE' else 'timeCalendar'
    if zone == 'Z':
        return wall, None
    if zone:
        hours, minutes_part = int(zone[1:3]), int(zone[4:6])
        if minutes_part > 59 or hours > 14 or (hours == 14 and minutes_part):
            return None, 'timeOffset'
        minutes = (hours * 60 + minutes_part) * (-1 if zone[0] == '-' else 1)       # xsd:dateTime allows -14:00 to +14:00, and -00:00 is UTC
        counts['offsetTimesConverted'] += 1
        return tc.instant(wall, minutes), None
    if zoneless == 'refuse' or (version == '1.0' and zoneless != 'utc'):
        return None, 'zonelessTime'
    counts['zonelessReadAsUtc'] += 1
    return wall, None


def read_point(elem, namespace, version, zoneless, counts, ordinal):
    """``(Point | None, reason | None, state)`` for one ``trkpt``; ``state`` is ``untimed`` for a valid point without a time."""
    lat, lon = elem.get('lat'), elem.get('lon')
    for text in (lat, lon):
        if text is None or len(text) > 30 or not DECIMAL.fullmatch(text):
            return None, 'coordinateSyntax', None
    dlat, dlon = to_decimal(lat), to_decimal(lon)
    if dlat is None or dlon is None or not -90 <= dlat <= 90:
        return None, 'latitudeRange', None
    if not (-180 <= dlon < 180 if version == '1.1' else -180 <= dlon <= 180):
        return None, 'longitudeRange', None
    ele = hdop = sat = fix = geoid = None
    t = None
    time_text = None
    for child in elem:
        name = local_name(child.tag, namespace)
        text = (child.text or '').strip()
        if name == 'ele':
            value = to_decimal(text) if DECIMAL.fullmatch(text) and len(text) <= 30 else None
            if value is None or abs(value) > ELE_MAX:
                return None, 'elevation', None
            ele = text
        elif name == 'time':
            time_text = text
        elif name == 'hdop':
            hdop = text[:16]
        elif name == 'sat':
            sat = text[:8]
        elif name == 'fix':
            fix = text[:8]
        elif name == 'geoidheight':
            geoid = text
    if geoid is not None:
        counts['geoidheightPresent'] += 1
    if time_text is None:
        return None, None, 'untimed'
    t, reason = parse_time(time_text, version, zoneless, counts)
    if reason:
        return None, reason, None
    return Point(t, lat, lon, ele, ordinal, hdop, sat, fix), None, 'timed'


def parse(data, *, invalid_points='refuse', zoneless='asSchema', limits=LIMITS):
    """Parse one track. Returns ``{'version', 'namespace', 'sha256', 'bytes', 'segments', 'counts', 'invalid', 'range'}``; raises ``TrackProblem``."""
    text = decode(data, limits)
    counts = {'tracks': 0, 'segments': 0, 'points': 0, 'timed': 0, 'untimed': 0, 'waypoints': 0, 'routes': 0, 'extensionElements': 0, 'elements': 0,
              'offsetTimesConverted': 0, 'zonelessReadAsUtc': 0, 'geoidheightPresent': 0}
    excluded, locations = {}, []
    parser = ElementTree.XMLPullParser(events=('start', 'end'))
    stack, segments = [], []
    state = {'version': None, 'namespace': None, 'segment': None, 'track': -1}
    ordinal = 0

    def handle(event, elem):
        nonlocal ordinal
        if event == 'start':
            depth = len(stack) + 1
            counts['elements'] += 1
            if depth > limits['depth'] or counts['elements'] > limits['elements']:
                raise TrackProblem('TRACK_RESOURCE_LIMIT', 'the track is nested too deeply or has too many elements', depth=depth, elements=counts['elements'])
            for value in elem.attrib.values():
                if len(value) > limits['attribute']:
                    raise TrackProblem('TRACK_RESOURCE_LIMIT', 'an attribute value is longer than %d characters' % limits['attribute'])
            if not stack:
                root_check(elem)
            elif state['namespace'] and not elem.tag.startswith('{' + state['namespace'] + '}'):
                counts['extensionElements'] += 1
            stack.append(elem)
            name = local_name(elem.tag, state['namespace']) if state['namespace'] else None
            if len(stack) == 2 and name == 'trk':
                counts['tracks'] += 1
                state['track'] += 1
            elif len(stack) == 3 and name == 'trkseg' and local_name(stack[1].tag, state['namespace']) == 'trk':
                counts['segments'] += 1
                state['segment'] = {'track': state['track'], 'segment': counts['segments'] - 1, 'points': []}
                segments.append(state['segment'])
            return
        stack.pop()
        if elem.text and len(elem.text) > limits['text']:
            raise TrackProblem('TRACK_RESOURCE_LIMIT', 'an element holds more than %d characters of text' % limits['text'])
        namespace = state['namespace']
        name = local_name(elem.tag, namespace) if namespace else None
        depth = len(stack) + 1
        if name == 'trkpt' and depth == 4 and local_name(stack[2].tag, namespace) == 'trkseg':
            point, reason, kind = read_point(elem, namespace, state['version'], zoneless, counts, ordinal)
            ordinal += 1
            counts['points'] += 1
            if counts['points'] > limits['points']:
                raise TrackProblem('TRACK_RESOURCE_LIMIT', 'a track has at most %d points' % limits['points'])
            if reason:
                excluded[reason] = excluded.get(reason, 0) + 1
                if len(locations) < MAX_REPORTED:
                    locations.append({'segment': state['segment']['segment'], 'point': counts['points'] - 1, 'reason': reason})
            elif kind == 'untimed':
                counts['untimed'] += 1
            else:
                counts['timed'] += 1
                state['segment']['points'].append(point)
        elif depth == 2 and name == 'wpt':
            counts['waypoints'] += 1
        elif depth == 2 and name == 'rte':
            counts['routes'] += 1
        inside_point = len(stack) >= 4 and local_name(stack[3].tag, namespace) == 'trkpt'
        if depth >= 2 and not inside_point:
            elem.clear()
            stack[-1].remove(elem)

    def root_check(elem):
        tag = elem.tag
        if tag == '{%s}gpx' % NS11:
            state.update(namespace=NS11, version='1.1')
        elif tag == '{%s}gpx' % NS10:
            state.update(namespace=NS10, version='1.0')
        else:
            raise TrackProblem('TRACK_NOT_GPX', 'the root element is not a GPX 1.0 or 1.1 gpx element', root=tag[:80])
        if elem.get('version') != state['version']:
            raise TrackProblem('TRACK_VERSION_MISMATCH', 'the version attribute does not match the namespace', namespace=state['namespace'], version=str(elem.get('version'))[:16])

    try:
        for start in range(0, len(text), CHUNK):
            parser.feed(text[start:start + CHUNK])
            for event, elem in parser.read_events():
                handle(event, elem)
        parser.close()
        for event, elem in parser.read_events():
            handle(event, elem)
    except ElementTree.ParseError as error:
        raise TrackProblem('TRACK_MALFORMED', 'the track is not well-formed XML: ' + str(error)[:120], position=list(getattr(error, 'position', ())) or None)
    except RecursionError:
        raise TrackProblem('TRACK_RESOURCE_LIMIT', 'the track is nested too deeply')
    if state['version'] is None:
        raise TrackProblem('TRACK_NOT_GPX', 'the document has no GPX root element')
    if excluded and invalid_points == 'refuse':
        raise TrackProblem('TRACK_POINT_INVALID', 'the track has invalid points', counts=excluded, firstLocations=locations)
    times = [p.t for s in segments for p in s['points']]
    return {'version': state['version'], 'namespace': state['namespace'], 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'segments': segments,
            'counts': counts, 'invalid': {'byReason': dict(sorted(excluded.items())), 'firstLocations': locations},
            'range': (min(times), max(times)) if times else None}


# ---------------------------------------------------------------- the span index
class Span:
    __slots__ = ('track', 'segment', 'a', 'b', 'gap', 'tainted')

    def __init__(self, track, segment, a, b, gap):
        self.track, self.segment, self.a, self.b, self.gap, self.tainted = track, segment, a, b, gap, False


def quantise(value, quantum=QUANTUM9):
    """``(Decimal, rounded)`` of a decimal rounded half-even to a quantum; ``rounded`` says whether the input had more digits."""
    rounded = value.quantize(quantum, ROUND_HALF_EVEN)
    return rounded + 0 if rounded else Decimal(0), rounded != value


class SpanIndex:
    """Spans, fixes and segment endpoints of every track of a run, in track order."""

    def __init__(self, tracks, max_gap_seconds=300):
        self.max_gap_ns = int(max_gap_seconds * tc.NS)
        self.spans, self.fixes, self.conflict_times, self.endpoints = [], {}, set(), []
        self.duplicates = self.reversals = 0
        self.segment_reports = []
        self.segment_ids = []
        for t_index, track in enumerate(tracks):
            for segment in track['segments']:
                self.add_segment(t_index, segment)
        self.spans.sort(key=lambda s: (s.a.t, s.track, s.segment))
        self.starts = [s.a.t for s in self.spans]
        running, self.max_end = None, []
        for s in self.spans:
            running = s.b.t if running is None else max(running, s.b.t)
            self.max_end.append(running)
        self.all_times = sorted(self.fixes)

    def add_segment(self, t_index, segment):
        points, duplicates, reversals = [], 0, 0
        for p in segment['points']:
            if points and p.t == points[-1].t and p.same_place(points[-1]):
                duplicates += 1
                continue
            points.append(p)
        links = []
        for a, b in zip(points, points[1:]):
            links.append('conflict' if a.t == b.t else 'reversal' if b.t < a.t else 'span')
        made = {}
        for i, (kind, (a, b)) in enumerate(zip(links, zip(points, points[1:]))):
            if kind == 'conflict':
                self.conflict_times.add(a.t)
            elif kind == 'reversal':
                reversals += 1
            else:
                made[i] = Span(t_index, segment['segment'], a, b, b.t - a.t > self.max_gap_ns)
        for i, kind in enumerate(links):
            if kind == 'conflict':
                for j in (i - 1, i + 1):
                    if j in made:
                        made[j].tainted = True
        self.spans.extend(made.values())
        for p in points:
            self.fixes.setdefault(p.t, []).append((t_index, segment['segment'], p))
        if points:
            self.endpoints.extend([(points[0], t_index, segment['segment']), (points[-1], t_index, segment['segment'])])
        self.duplicates += duplicates
        self.reversals += reversals
        gaps = [s for s in made.values() if s.gap]
        self.segment_reports.append({'track': t_index, 'segment': segment['segment'], 'points': len(points), 'duplicatesRemoved': duplicates, 'reversals': reversals,
                                     'spans': len(made), 'gapSpans': len(gaps), 'maxGapSeconds': tc.seconds_text(max((s.b.t - s.a.t for s in made.values()), default=0)),
                                     'firstUtc': tc.local_text(points[0].t) if points else None, 'lastUtc': tc.local_text(points[-1].t) if points else None})

    # -- resolution of one photograph instant
    def containing(self, t):
        """Spans (gap or not) with ``a.t < t < b.t`` in index order."""
        found, i = [], bisect_right(self.starts, t) - 1
        while i >= 0 and self.max_end[i] > t:
            s = self.spans[i]
            if s.a.t < t < s.b.t:
                found.append(s)
            i -= 1
        return sorted(found, key=lambda s: (s.track, s.segment, s.a.ordinal))

    def nearest_seconds(self, t):
        if not self.all_times:
            return None
        i = bisect_right(self.all_times, t)
        near = [self.all_times[j] for j in (i - 1, i) if 0 <= j < len(self.all_times)]
        return min(abs(t - x) for x in near)

    def resolve(self, t, *, endpoint_snap_seconds=0, overlap_agreement_meters=5, want_elevation=False):
        """The placement of a UTC instant (integer nanoseconds): ``{'status': 'ok', ...}`` or ``{'status': 'refused', 'code': ..., ...}``."""
        if t in self.conflict_times:
            return refused('TRACK_TIME_CONFLICT', 'two fixes share this instant at different positions')
        spans = self.containing(t)
        usable = [s for s in spans if not s.gap]
        if any(s.tainted for s in usable):
            return refused('TRACK_TIME_CONFLICT', 'the span around this instant is adjacent to two fixes with equal times at different positions')
        candidates = [candidate_fix(ti, si, p, want_elevation) for ti, si, p in self.fixes.get(t, [])]
        candidates += [candidate_span(s, t, want_elevation) for s in usable]
        candidates = [c for c in candidates if c is not None]
        if any(c.get('antipodal') for c in candidates):
            return refused('TRACK_SPAN_ANTIPODAL', 'the span around this instant is nearly antipodal; the great circle is not defined')
        candidates.sort(key=lambda c: (c['track'], c['segment'], c['ordinal']))
        if candidates:
            first = candidates[0]
            if len(candidates) > MAX_OVERLAP_CANDIDATES:       # the pairwise check stays bounded: more simultaneous candidate positions than this is not a usable overlap
                return refused('TRACK_OVERLAP_CONFLICT', 'more than %d overlapping candidate positions cover this instant' % MAX_OVERLAP_CANDIDATES, candidates=[public(c) for c in candidates[:8]],
                               count=len(candidates), agreementMeters=str(overlap_agreement_meters))
            worst = max((geodesy.haversine_m((a['latitude'], a['longitude']), (b['latitude'], b['longitude'])) for i, a in enumerate(candidates) for b in candidates[i + 1:]), default=0.0)
            if worst > float(overlap_agreement_meters):       # agreement is not transitive: every pair of candidates must agree, not only each with the first
                return refused('TRACK_OVERLAP_CONFLICT', 'overlapping tracks disagree about this instant by %.1f m' % worst,
                               candidates=[public(c) for c in candidates[:8]], separationMeters=round(worst, 3), agreementMeters=str(overlap_agreement_meters))
            return {'status': 'ok', **public(first), 'overlapCandidates': len(candidates)}
        if endpoint_snap_seconds:
            snap = self.nearest_endpoint(t, int(endpoint_snap_seconds * tc.NS))
            if snap:
                point, ti, si = snap
                lat, _ = quantise(Decimal(point.lat))
                lon, _ = quantise(Decimal(point.lon))
                return {'status': 'ok', 'method': 'endpointSnap', 'track': ti, 'segment': si, 'ordinal': point.ordinal, 'latitude': lat, 'longitude': lon,
                        'altitude': altitude_of_point(point) if want_elevation else None, 'timeDistanceSeconds': tc.seconds_text(abs(t - point.t)), 'overlapCandidates': 1,
                        'evidence': {'fixUtc': tc.local_text(point.t), 'fixPosition': [point.lat, point.lon]}}
        reason = self.uncovered_reason(t, spans)
        return refused('TRACK_NOT_COVERED', 'no fix or usable span covers this instant (%s)' % reason, reason=reason, nearestFixSeconds=tc.seconds_text(self.nearest_seconds(t)) if self.all_times else None)

    def nearest_endpoint(self, t, limit_ns):
        best = None
        for point, ti, si in self.endpoints:
            d = abs(t - point.t)
            if d <= limit_ns and (best is None or (d, ti, si) < (best[0], best[2], best[3])):
                best = (d, point, ti, si)
        return (best[1], best[2], best[3]) if best else None

    def uncovered_reason(self, t, spans):
        if any(s.gap for s in spans):
            return 'inGapSpan'
        if not self.all_times or t < self.all_times[0]:
            return 'beforeStart'
        if t > self.all_times[-1]:
            return 'afterEnd'
        return 'inSegmentGap'


def refused(code, message, **observed):
    return {'status': 'refused', 'code': code, 'message': message, **observed}


def altitude_of_point(point):
    if point.ele is None:
        return None
    return Decimal(round(Fraction(Decimal(point.ele)) * 1000)) / 1000 if Decimal(point.ele) else Decimal('0.000')


def candidate_fix(track, segment, p, want_elevation):
    lat, lat_rounded = quantise(Decimal(p.lat))
    lon, lon_rounded = quantise(Decimal(p.lon))
    return {'method': 'exactFix', 'track': track, 'segment': segment, 'ordinal': p.ordinal, 'latitude': lat, 'longitude': lon,
            'altitude': altitude_of_point(p) if want_elevation else None, 'inputRounded': lat_rounded or lon_rounded,
            'evidence': {'fixUtc': tc.local_text(p.t), 'fixPosition': [p.lat, p.lon], 'hdop': p.hdop, 'sat': p.sat, 'fix': p.fix}}


def candidate_span(span, t, want_elevation):
    a, b = span.a, span.b
    f = geodesy.fraction_of(t, a.t, b.t)
    try:
        r = geodesy.interpolate(a.position(), b.position(), f)
    except geodesy.Antipodal:
        return {'antipodal': True, 'track': span.track, 'segment': span.segment, 'ordinal': a.ordinal}
    altitude = None
    if want_elevation and a.ele is not None and b.ele is not None:
        altitude = geodesy.interpolate_altitude(Decimal(a.ele), Decimal(b.ele), f)
    separation = geodesy.haversine_m(a.position(), b.position())
    dt = b.t - a.t
    near_first = (t - a.t) <= (b.t - t)
    near = a if near_first else b
    return {'method': 'interpolated', 'track': span.track, 'segment': span.segment, 'ordinal': a.ordinal, 'latitude': r['latitude'], 'longitude': r['longitude'],
            'altitude': altitude, 'flags': r['flags'], 'roundingBoundary': r['roundingBoundary'], 'inputRounded': False,
            'evidence': {'beforeUtc': tc.local_text(a.t), 'afterUtc': tc.local_text(b.t), 'beforePosition': [a.lat, a.lon], 'afterPosition': [b.lat, b.lon],
                         'spanSeconds': tc.seconds_text(dt), 'fraction': '%d/%d' % (f.numerator, f.denominator), 'separationMeters': round(separation, 3),
                         'impliedSpeedMetersPerSecond': round(separation / (dt / tc.NS), 6), 'nearerFixSeconds': tc.seconds_text(abs(t - near.t)),
                         'nearerFixMeters': round(geodesy.haversine_m(a.position() if near_first else b.position(), (r['latitude'], r['longitude'])), 3),
                         'beforeHdop': a.hdop, 'afterHdop': b.hdop, 'beforeSat': a.sat, 'afterSat': b.sat}}


def public(candidate):
    return {k: v for k, v in candidate.items() if k != 'antipodal'}
