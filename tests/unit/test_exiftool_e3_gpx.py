"""Host tests of the secure GPX parser and the span index. Coordinates and times are hand-written literals; the expected placements are
derived by hand (a meridian midpoint, an equator quarter) and never taken from the code under test."""
from decimal import Decimal as D
import random
from pathlib import Path
import sys
import tracemalloc
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from schemaxis.adaptors.exiftool import geodesy, gpxtrack as gx, timecalc as tc  # noqa: E402

NS = {'1.1': 'http://www.topografix.com/GPX/1/1', '1.0': 'http://www.topografix.com/GPX/1/0'}


def doc(segments, version='1.1', extra='', head='<?xml version="1.0" encoding="UTF-8"?>\n', root_extra=''):
    out = [head, '<gpx version="%s" creator="t" xmlns="%s"%s>' % (version, NS[version], root_extra), extra, '<trk>']
    for points in segments:
        out.append('<trkseg>')
        for p in points:
            lat, lon, when = p[:3]
            inner = ''
            if len(p) > 3 and p[3] is not None:
                inner += '<ele>%s</ele>' % p[3]
            if when is not None:
                inner += '<time>%s</time>' % when
            out.append('<trkpt lat="%s" lon="%s">%s</trkpt>' % (lat, lon, inner))
        out.append('</trkseg>')
    out.append('</trk></gpx>')
    return ''.join(out).encode('utf-8')


def ns(text):
    return tc.parse_local(text.rstrip('Z'))[0]


def index_of(*raws, gap=300, **kw):
    return gx.SpanIndex([gx.parse(r, **kw) for r in raws], gap)


def code_of(raw, **kw):
    try:
        gx.parse(raw, **kw)
    except gx.TrackProblem as error:
        return error.code
    return None


class Placement(unittest.TestCase):
    def test_meridian_and_equator_literals(self):
        raw = doc([[('0', '0', '2026-03-01T00:00:00Z'), ('0', '8', '2026-03-01T00:00:08Z')],
                   [('0', '30', '2026-03-01T01:00:00Z'), ('10', '30', '2026-03-01T01:00:10Z')]])
        index = index_of(raw)
        quarter = index.resolve(ns('2026-03-01T00:00:02'))
        self.assertEqual((quarter['status'], quarter['method'], geodesy.text9(quarter['latitude']), geodesy.text9(quarter['longitude'])), ('ok', 'interpolated', '0.000000000', '2.000000000'))
        self.assertEqual(quarter['evidence']['fraction'], '1/4')
        half = index.resolve(ns('2026-03-01T01:00:05'))
        self.assertEqual((geodesy.text9(half['latitude']), geodesy.text9(half['longitude'])), ('5.000000000', '30.000000000'))
        fix = index.resolve(ns('2026-03-01T00:00:08'))
        self.assertEqual((fix['method'], geodesy.text9(fix['latitude']), geodesy.text9(fix['longitude'])), ('exactFix', '0.000000000', '8.000000000'))

    def test_uncovered_reasons(self):
        raw = doc([[('0', '0', '2026-03-01T00:00:00Z'), ('0', '1', '2026-03-01T00:00:10Z')], [('0', '2', '2026-03-01T00:10:00Z'), ('0', '3', '2026-03-01T00:10:10Z')]])
        index = index_of(raw)
        for when, reason in (('2026-02-28T23:59:59', 'beforeStart'), ('2026-03-01T00:10:11', 'afterEnd'), ('2026-03-01T00:05:00', 'inSegmentGap')):
            r = index.resolve(ns(when))
            self.assertEqual((r['status'], r['code'], r['reason']), ('refused', 'TRACK_NOT_COVERED', reason), when)
        # contract G4: one segment with a 900 s span and maxGap 300 -> the span is a gap span, not interpolated
        wide = index_of(doc([[('0', '0', '2026-03-01T00:00:00Z'), ('0', '9', '2026-03-01T00:15:00Z')]]))
        r = wide.resolve(ns('2026-03-01T00:07:30'))
        self.assertEqual((r['code'], r['reason']), ('TRACK_NOT_COVERED', 'inGapSpan'))
        self.assertEqual(index_of(doc([[('0', '0', '2026-03-01T00:00:00Z'), ('0', '9', '2026-03-01T00:15:00Z')]]), gap=900).resolve(ns('2026-03-01T00:07:30'))['method'], 'interpolated')

    def test_endpoint_snap_is_bounded_and_labelled(self):
        index = index_of(doc([[('1.5', '2.5', '2026-03-01T00:00:00Z'), ('1.5', '2.6', '2026-03-01T00:00:10Z')]]))
        near = index.resolve(ns('2026-02-28T23:59:59'), endpoint_snap_seconds=2)
        self.assertEqual((near['method'], geodesy.text9(near['latitude']), geodesy.text9(near['longitude']), near['timeDistanceSeconds']), ('endpointSnap', '1.500000000', '2.500000000', '1'))
        self.assertEqual(index.resolve(ns('2026-02-28T23:59:57'), endpoint_snap_seconds=2)['code'], 'TRACK_NOT_COVERED')
        late = index.resolve(ns('2026-03-01T00:00:11.5'), endpoint_snap_seconds=2)
        self.assertEqual((late['method'], late['timeDistanceSeconds']), ('endpointSnap', '1.5'))

    def test_duplicates_conflicts_and_reversals(self):
        raw = doc([[('0', '0', '2026-03-01T00:00:00Z'), ('0', '1', '2026-03-01T00:00:10Z'), ('0', '1', '2026-03-01T00:00:10Z'),   # duplicate
                    ('0', '2', '2026-03-01T00:00:20Z'), ('5', '5', '2026-03-01T00:00:20Z'),                                          # equal time, different place
                    ('5', '6', '2026-03-01T00:00:30Z'), ('5', '7', '2026-03-01T00:00:40Z')]])
        index = index_of(raw)
        self.assertEqual(index.duplicates, 1)
        self.assertEqual(index.resolve(ns('2026-03-01T00:00:20'))['code'], 'TRACK_TIME_CONFLICT')
        self.assertEqual(index.resolve(ns('2026-03-01T00:00:15'))['code'], 'TRACK_TIME_CONFLICT')       # the span before the conflict pair is adjacent
        self.assertEqual(index.resolve(ns('2026-03-01T00:00:25'))['code'], 'TRACK_TIME_CONFLICT')       # and so is the one after it
        self.assertEqual(index.resolve(ns('2026-03-01T00:00:35'))['status'], 'ok')                      # the next span is not adjacent
        self.assertEqual(index.resolve(ns('2026-03-01T00:00:05'))['status'], 'ok')
        rev = index_of(doc([[('0', '0', '2026-03-01T00:00:00Z'), ('0', '1', '2026-03-01T00:00:30Z'), ('0', '2', '2026-03-01T00:00:10Z'), ('0', '3', '2026-03-01T00:00:50Z')]]))
        self.assertEqual(rev.reversals, 1)
        # the reversal yields no span; 0:05 is covered only by the first span (0:00..0:30), 0:40 only by the last (0:10..0:50) ...
        self.assertEqual(rev.resolve(ns('2026-03-01T00:00:05'))['evidence']['afterUtc'], '2026-03-01T00:00:30')
        self.assertEqual(rev.resolve(ns('2026-03-01T00:00:40'))['evidence']['beforeUtc'], '2026-03-01T00:00:10')
        # ... and 0:15 lies in both overlapping spans, which disagree, so the reversed logger clock is not repaired or averaged
        self.assertEqual(rev.resolve(ns('2026-03-01T00:00:15'))['code'], 'TRACK_OVERLAP_CONFLICT')

    def test_overlapping_tracks_agree_or_conflict(self):
        a = doc([[('10.000000', '20.000000', '2026-03-01T00:00:00Z'), ('10.000100', '20.000000', '2026-03-01T00:00:10Z')]])
        near = doc([[('10.000020', '20.000000', '2026-03-01T00:00:00Z'), ('10.000120', '20.000000', '2026-03-01T00:00:10Z')]])     # 0.00002 deg = 2.2 m
        far = doc([[('10.000450', '20.000000', '2026-03-01T00:00:00Z'), ('10.000550', '20.000000', '2026-03-01T00:00:10Z')]])      # 0.00045 deg = 50 m
        agree = index_of(a, near).resolve(ns('2026-03-01T00:00:05'))
        self.assertEqual((agree['status'], agree['track'], agree['overlapCandidates'], geodesy.text9(agree['latitude'])), ('ok', 0, 2, '10.000050000'))
        swapped = index_of(near, a).resolve(ns('2026-03-01T00:00:05'))
        self.assertEqual((swapped['track'], geodesy.text9(swapped['latitude'])), (0, '10.000070000'))      # deterministic: the first listed track wins, no averaging
        clash = index_of(a, far).resolve(ns('2026-03-01T00:00:05'))
        self.assertEqual(clash['code'], 'TRACK_OVERLAP_CONFLICT')
        self.assertEqual(len(clash['candidates']), 2)

    def test_antipodal_span(self):
        r = index_of(doc([[('0', '0', '2026-03-01T00:00:00Z'), ('0', '179.5', '2026-03-01T00:00:10Z')]])).resolve(ns('2026-03-01T00:00:05'))
        self.assertEqual(r['code'], 'TRACK_SPAN_ANTIPODAL')

    def test_antimeridian_span(self):
        r = index_of(doc([[('0', '179.9999', '2026-03-01T00:00:00Z'), ('0', '-179.9999', '2026-03-01T00:00:10Z')]])).resolve(ns('2026-03-01T00:00:05'))
        self.assertEqual((geodesy.text9(r['latitude']), geodesy.text9(r['longitude'])), ('0.000000000', '-180.000000000'))
        self.assertIn('antimeridian', r['flags'])

    def test_elevation_is_linear_and_optional(self):
        raw = doc([[('0', '0', '2026-03-01T00:00:00Z', '10'), ('0', '1', '2026-03-01T00:00:10Z', '11')], [('0', '5', '2026-03-01T01:00:00Z'), ('0', '6', '2026-03-01T01:00:10Z', '3')]])
        index = index_of(raw)
        self.assertEqual(index.resolve(ns('2026-03-01T00:00:05'), want_elevation=True)['altitude'], D('10.500'))
        self.assertIsNone(index.resolve(ns('2026-03-01T00:00:05'))['altitude'])
        self.assertIsNone(index.resolve(ns('2026-03-01T01:00:05'), want_elevation=True)['altitude'])         # one end has no ele: unavailable, not a fault
        self.assertEqual(index.resolve(ns('2026-03-01T00:00:10'), want_elevation=True)['altitude'], D('11.000'))

    def test_waypoints_and_routes_only(self):
        extra = '<wpt lat="1" lon="1"><time>2026-03-01T00:00:00Z</time></wpt><rte><rtept lat="2" lon="2"/></rte>'
        result = gx.parse(doc([], extra=extra))
        self.assertEqual((result['counts']['waypoints'], result['counts']['routes'], result['counts']['timed']), (1, 1, 0))
        self.assertEqual(gx.SpanIndex([result]).resolve(ns('2026-03-01T00:00:00'))['reason'], 'beforeStart')


class Times(unittest.TestCase):
    def test_zone_normalisation(self):
        raw = doc([[('0', '0', '2026-03-01T02:00:00+02:00'), ('0', '1', '2026-03-01T00:00:10'), ('0', '2', '2026-03-01T00:00:20Z')]])
        track = gx.parse(raw)
        self.assertEqual([tc.local_text(p.t) for p in track['segments'][0]['points']], ['2026-03-01T00:00:00', '2026-03-01T00:00:10', '2026-03-01T00:00:20'])
        self.assertEqual((track['counts']['offsetTimesConverted'], track['counts']['zonelessReadAsUtc']), (1, 1))
        self.assertEqual(code_of(raw, zoneless='refuse'), 'TRACK_POINT_INVALID')

    def test_gpx_1_0_zoneless_needs_a_declaration(self):
        raw = doc([[('0', '0', '2026-03-01T00:00:00'), ('0', '1', '2026-03-01T00:00:10')]], version='1.0')
        self.assertEqual(code_of(raw), 'TRACK_POINT_INVALID')
        self.assertEqual(gx.parse(raw, zoneless='utc')['counts']['zonelessReadAsUtc'], 2)
        self.assertEqual(gx.parse(raw, zoneless='utc')['version'], '1.0')

    def test_untimed_points_are_excluded_not_faults(self):
        track = gx.parse(doc([[('0', '0', None), ('0', '1', '2026-03-01T00:00:10Z')]]))
        self.assertEqual((track['counts']['untimed'], track['counts']['timed']), (1, 1))

    def test_invalid_times(self):
        for when in ('2026-03-01T24:00:00Z', '2026-03-01T00:00:60Z', '2026-02-30T00:00:00Z', '1899-12-31T23:59:59Z', '2026-03-01 00:00:00Z', '2026-03-01T00:00Z'):
            raw = doc([[('0', '0', when)]])
            self.assertEqual(code_of(raw), 'TRACK_POINT_INVALID', when)
            self.assertEqual(gx.parse(raw, invalid_points='exclude')['counts']['timed'], 0, when)


class Points(unittest.TestCase):
    def test_coordinate_domains(self):
        t = '2026-03-01T00:00:00Z'
        for lat, lon in (('0', '180'), ('90.0000001', '0'), ('0', '1e1'), ('NaN', '0'), ('abc', '0'), ('0', 'INF'), ('+', '0'), ('0.', '-180.5'), ('', '0')):
            raw = doc([[(lat, lon, t)]])
            self.assertEqual(code_of(raw), 'TRACK_POINT_INVALID', (lat, lon))
        for lat, lon in (('90', '0'), ('-90', '-180'), ('0', '179.999999999'), ('.5', '+0.5'), ('0.', '0')):
            self.assertEqual(gx.parse(doc([[(lat, lon, t)]]))['counts']['timed'], 1, (lat, lon))
        self.assertEqual(code_of(doc([[('0', '180', t)]], version='1.0')), None)    # 1.0 admits +180

    def test_exclude_reports_reasons_and_locations(self):
        track = gx.parse(doc([[('0', '180', '2026-03-01T00:00:00Z'), ('0', '1', '2026-03-01T00:00:10Z'), ('x', '1', '2026-03-01T00:00:20Z')]]), invalid_points='exclude')
        self.assertEqual(track['invalid']['byReason'], {'coordinateSyntax': 1, 'longitudeRange': 1})
        self.assertEqual([x['point'] for x in track['invalid']['firstLocations']], [0, 2])

    def test_elevation_domain(self):
        for ele in ('100001', 'abc', '1e2'):
            self.assertEqual(code_of(doc([[('0', '0', '2026-03-01T00:00:00Z', ele)]])), 'TRACK_POINT_INVALID', ele)
        self.assertEqual(gx.parse(doc([[('0', '0', '2026-03-01T00:00:00Z', '0')]]))['counts']['timed'], 1)
        self.assertEqual(gx.parse(doc([[('0', '0', '2026-03-01T00:00:00Z', '-100000')]]))['counts']['timed'], 1)


class Security(unittest.TestCase):
    LAUGHS = ('<?xml version="1.0"?>\n<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>\n'
              '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><metadata><name>&lol2;</name></metadata></gpx>')
    EXTERNAL = ('<?xml version="1.0"?>\n<!DOCTYPE g [<!ENTITY x SYSTEM "file:///etc/passwd">]>\n'
                '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><metadata><name>&x;</name></metadata></gpx>')

    def test_dtd_and_entities_are_refused_before_parsing(self):
        self.assertEqual(code_of(self.LAUGHS.encode()), 'TRACK_DTD_REFUSED')
        self.assertEqual(code_of(self.EXTERNAL.encode()), 'TRACK_DTD_REFUSED')
        for decl in ('<!ENTITY a "b">', '<!ATTLIST a b CDATA #IMPLIED>', '<!ELEMENT a ANY>', '<!NOTATION n SYSTEM "x">'):
            self.assertEqual(code_of(doc([], extra=decl)), 'TRACK_DTD_REFUSED', decl)
        self.assertEqual(code_of(doc([], extra='<?xml-stylesheet href="x"?>')), 'TRACK_DTD_REFUSED')
        self.assertEqual(code_of(doc([], extra='<!-- fine --><![CDATA[ fine ]]>')), None)

    def test_undefined_entity_and_predefined_entities(self):
        self.assertEqual(code_of(doc([], extra='<metadata><name>&undefined;</name></metadata>')), 'TRACK_MALFORMED')
        track = gx.parse(doc([], extra='<metadata><name>a &amp; b &#65; &lt;</name></metadata>'))
        self.assertEqual(track['counts']['tracks'], 1)

    def test_encodings(self):
        utf16 = doc([[('0', '0', '2026-03-01T00:00:00Z')]]).decode().encode('utf-16')
        self.assertEqual(code_of(utf16), 'TRACK_ENCODING_UNSUPPORTED')
        self.assertEqual(code_of(doc([], head='<?xml version="1.0" encoding="UTF-16"?>').replace(b'UTF-16', b'UTF-16')), 'TRACK_ENCODING_UNSUPPORTED')
        self.assertEqual(code_of(doc([], head='<?xml version="1.0" encoding="ISO-8859-1"?>')), 'TRACK_ENCODING_UNSUPPORTED')
        self.assertEqual(code_of(doc([], head='<?xml version="1.0" encoding="utf-8"?>')), None)
        self.assertEqual(code_of(doc([], head='<?xml version="1.0" encoding="US-ASCII"?>')), None)
        self.assertEqual(code_of(b'\xef\xbb\xbf' + doc([])), None)
        self.assertEqual(code_of(doc([]).replace(b'creator="t"', b'creator="\xff"')), 'TRACK_MALFORMED')

    def test_root_and_version(self):
        self.assertEqual(code_of(b'<gpx version="1.1"/>'), 'TRACK_NOT_GPX')
        self.assertEqual(code_of(b'<kml xmlns="http://www.topografix.com/GPX/1/1"/>'), 'TRACK_NOT_GPX')
        self.assertEqual(code_of(b'<gpx version="1.0" xmlns="http://www.topografix.com/GPX/1/1"/>'), 'TRACK_VERSION_MISMATCH')
        self.assertEqual(code_of(b'<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/0"/>'), 'TRACK_VERSION_MISMATCH')
        self.assertEqual(code_of(b''), 'TRACK_MALFORMED')

    def test_malformed_reports_a_position(self):
        try:
            gx.parse(b'<?xml version="1.0"?>\n<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">\n<trk></gpx>')
        except gx.TrackProblem as error:
            self.assertEqual((error.code, error.observed['position'][0]), ('TRACK_MALFORMED', 3))
        else:
            self.fail('expected a malformed track')

    def test_resource_limits(self):
        small = dict(gx.LIMITS, depth=3)
        self.assertEqual(code_of(doc([[('0', '0', '2026-03-01T00:00:00Z')]]), limits=small), 'TRACK_RESOURCE_LIMIT')
        deep = ('<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">' + '<a>' * 31 + '</a>' * 31 + '</gpx>').encode()
        self.assertEqual(code_of(deep), None)                                      # depth 32 with the root
        deeper = ('<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">' + '<a>' * 32 + '</a>' * 32 + '</gpx>').encode()
        self.assertEqual(code_of(deeper), 'TRACK_RESOURCE_LIMIT')                  # contract G15: depth 33
        points = [('0', '0', '2026-03-01T00:%02d:%02dZ' % divmod(i, 60)) for i in range(5)]
        self.assertEqual(code_of(doc([points]), limits=dict(gx.LIMITS, points=4)), 'TRACK_RESOURCE_LIMIT')
        self.assertEqual(code_of(doc([points]), limits=dict(gx.LIMITS, bytes=100)), 'TRACK_RESOURCE_LIMIT')
        self.assertEqual(code_of(doc([points]), limits=dict(gx.LIMITS, elements=5)), 'TRACK_RESOURCE_LIMIT')
        self.assertEqual(code_of(doc([], extra='<metadata><name>%s</name></metadata>' % ('x' * 4097))), 'TRACK_RESOURCE_LIMIT')
        self.assertEqual(code_of(doc([], root_extra=' a="%s"' % ('x' * 4097))), 'TRACK_RESOURCE_LIMIT')

    def test_extension_elements_are_skipped_and_counted(self):
        raw = doc([[('0', '0', '2026-03-01T00:00:00Z')]]).replace(b'</trkpt>', b'<extensions><x:h xmlns:x="urn:x">1</x:h></extensions></trkpt>')
        track = gx.parse(raw)
        self.assertEqual(track['counts']['timed'], 1)
        self.assertEqual(track['counts']['extensionElements'], 1)

    def test_streaming_discards_finished_points(self):
        # a large file is parsed with bounded growth: finished trkpt elements are removed, so memory is dominated by the retained Points only
        n = 60000
        body = ''.join('<trkpt lat="1" lon="2"><time>2026-03-01T00:00:00Z</time></trkpt>' for _ in range(n))
        raw = ('<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>' + body + '</trkseg></trk></gpx>').encode()
        tracemalloc.start()
        track = gx.parse(raw)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.assertEqual(track['counts']['timed'], n)
        self.assertLess(peak, len(raw) * 6)

    def test_fuzz_never_escapes_a_closed_code(self):
        rng = random.Random(20261026)
        base = doc([[('1', '2', '2026-03-01T00:00:00Z', '5'), ('1', '3', '2026-03-01T00:00:10Z')]], extra='<metadata><name>n</name></metadata>')
        pieces = [b'<', b'>', b'&', b'"', b'/', b'<!', b'<?', b'\x00', b'\xff', b'<trkpt lat="1" lon="2">', b'</trkpt>', b'<![CDATA[', b'&#0;', b'&#x110000;', b'xmlns=']
        closed = {'TRACK_NOT_GPX', 'TRACK_VERSION_MISMATCH', 'TRACK_ENCODING_UNSUPPORTED', 'TRACK_DTD_REFUSED', 'TRACK_MALFORMED', 'TRACK_RESOURCE_LIMIT', 'TRACK_POINT_INVALID'}
        for _ in range(500):
            data = bytearray(base)
            for _ in range(rng.randint(1, 4)):
                at = rng.randrange(len(data) + 1)
                if rng.random() < 0.5:
                    data[at:at] = rng.choice(pieces)
                else:
                    del data[at:at + rng.randint(1, 12)]
            try:
                gx.parse(bytes(data), invalid_points=rng.choice(['refuse', 'exclude']), zoneless=rng.choice(['asSchema', 'refuse', 'utc']))
            except gx.TrackProblem as error:
                self.assertIn(error.code, closed)


class ReviewFindings(unittest.TestCase):
    """Finite counterexample regressions of the independent early review (P3-1 to P3-4); hand-written literals."""

    def test_P3_1_only_ascii_digits_are_coordinates_and_times(self):
        for raw in (doc([[('\u0661\u0662', '20', '2026-03-01T00:00:00Z')]]), doc([[('10', '20', '\u0662\u0660\u0662\u0666-03-01T00:00:00Z')]])):
            with self.assertRaises(gx.TrackProblem) as caught:
                gx.parse(raw)
            self.assertEqual(caught.exception.code, 'TRACK_POINT_INVALID')
        excluded = gx.parse(doc([[('\u0661\u0662', '20', '2026-03-01T00:00:00Z'), ('10', '20', '2026-03-01T00:00:10Z')]]), invalid_points='exclude')
        self.assertEqual((excluded['counts']['timed'], sum(excluded['invalid']['byReason'].values())), (1, 1))

    def test_P3_2_the_full_xsd_offset_range_is_accepted_and_nothing_wider(self):
        # xsd:dateTime zones run from -14:00 to +14:00 and -00:00 is UTC; 12:00 at -13:00 is 25:00 UTC, i.e. 01:00 the next day
        cases = {'-00:00': '2026-03-01T12:00:00', '-13:00': '2026-03-02T01:00:00', '-14:00': '2026-03-02T02:00:00', '+14:00': '2026-02-28T22:00:00', '+05:30': '2026-03-01T06:30:00'}
        for zone, utc in cases.items():
            track = gx.parse(doc([[('10', '20', '2026-03-01T12:00:00' + zone)]]))
            self.assertEqual(tc.local_text(track['segments'][0]['points'][0].t), utc, zone)
        for zone in ('+14:01', '+15:00', '-14:30', '+05:60'):
            with self.assertRaises(gx.TrackProblem) as caught:
                gx.parse(doc([[('10', '20', '2026-03-01T12:00:00' + zone)]]))
            self.assertEqual(caught.exception.code, 'TRACK_POINT_INVALID', zone)
        # the camera-side policy is unchanged: -00:00 is an unknown offset there, never UTC
        with self.assertRaises(tc.TimeProblem):
            tc.parse_offset('-00:00')

    def stationary(self, lat):
        return doc([[('%s' % lat, '20.000000', '2026-03-01T00:00:00Z'), ('%s' % lat, '20.000000', '2026-03-01T00:00:10Z')]])

    def test_P3_3_overlap_agreement_is_pairwise_not_each_with_the_first(self):
        # A at 10.000000, B 0.000036 deg north of A and C 0.000036 deg south: A-B and A-C are 4.003 m, B-C is 8.006 m
        a, b, c = self.stationary('10.000000'), self.stationary('10.000036'), self.stationary('9.999964')
        t = ns('2026-03-01T00:00:05')
        refused = index_of(a, b, c).resolve(t, overlap_agreement_meters=5)
        self.assertEqual(refused['code'], 'TRACK_OVERLAP_CONFLICT')
        self.assertEqual(refused['separationMeters'], 8.006)       # 0.000072 deg of latitude on the 6371008.8 m sphere
        self.assertEqual(index_of(a, b).resolve(t, overlap_agreement_meters=5)['overlapCandidates'], 2)
        self.assertEqual(index_of(a, b, c).resolve(t, overlap_agreement_meters=9)['overlapCandidates'], 3)

    def test_P3_3_the_pairwise_check_is_bounded(self):
        many = [self.stationary('10.000000')] * (gx.MAX_OVERLAP_CANDIDATES + 1)
        refused = index_of(*many).resolve(ns('2026-03-01T00:00:05'), overlap_agreement_meters=1000)
        self.assertEqual((refused['code'], refused['count']), ('TRACK_OVERLAP_CONFLICT', gx.MAX_OVERLAP_CANDIDATES + 1))
        self.assertEqual(index_of(*many[:gx.MAX_OVERLAP_CANDIDATES]).resolve(ns('2026-03-01T00:00:05'), overlap_agreement_meters=1000)['overlapCandidates'], gx.MAX_OVERLAP_CANDIDATES)


if __name__ == '__main__':
    unittest.main()
