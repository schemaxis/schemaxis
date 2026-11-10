"""Tests of ``geotagFromTrack``: document planning and, with a real ExifTool 13.55 through SCHEMAXIS_EXIFTOOL, genuine placements of captured photographs on captured
GPX tracks, truthful partial outcomes, clock-correction plans, plan-only runs and exact mutants.

The tracks lie on the equator, where the great-circle interpolation equals the linear one, so every expected position is an exact hand literal (a fix at
03:00:00 / 03:00:20 / 03:00:40 UTC at 10.000 / 10.002 / 10.004 degrees east puts 03:00:10 at 10.001). The native geotag feature is never used and never compared.
"""
from fractions import Fraction
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests/unit'))

import exiftool_e3_fixtures as fx  # noqa: E402
from schemaxis.adaptors.exiftool import adaptor  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402
from test_exiftool_e3_gpx import doc as gpx  # noqa: E402

V = 'schemaxis.exiftool/1'
BOUND = Fraction(2, 10 ** 10)


def items(root, names):
    return {'items': [{'id': n, 'path': str(root / (n + '.jpg'))} for n in names]}


def doc(operation, media, **rest):
    return {'version': V, 'operation': operation, 'media': media, **rest}


def fault_of(call):
    try:
        call()
    except SchemaxisError as error:
        return error.fault
    raise AssertionError('no fault')


def total(triple):
    return sum(Fraction(n, d) / div for (n, d), div in zip(triple, (1, 60, 3600)))


EQUATOR = gpx([[('0', '10.000', '2026-03-01T03:00:00Z', '10'), ('0', '10.002', '2026-03-01T03:00:20Z', '20'), ('0', '10.004', '2026-03-01T03:00:40Z', '30')]])


class Planning(unittest.TestCase):
    BASE = doc('geotagFromTrack', {'items': [{'id': 'a1', 'path': '/x/a1.jpg'}]}, tracks=[{'id': 'watch', 'path': '/x/watch.gpx'}])

    def plan(self, **change):
        document = copy.deepcopy(self.BASE)
        document.update(change)
        return adaptor.plan(document)

    def test_defaults_are_explicit(self):
        p = self.plan()
        self.assertEqual(p['e3']['interpolation'], {'maxGapSeconds': 300, 'endpointSnapSeconds': 0, 'overlapAgreementMeters': '5'})
        self.assertEqual(p['e3']['track'], {'invalidPoints': 'refuse', 'zonelessTimes': 'asSchema', 'elevation': 'ignore'})
        self.assertEqual(p['e3']['photoTime'], {'source': 'captured', 'assumedOffsets': [], 'clockCorrection': 'none'})
        self.assertEqual(p['e3']['policies'], {'staleCompanions': 'remove', 'xmp': 'ifPresent', 'createExif': 'allow', 'altitudeNotExpressible': 'refuse', 'removeDirection': False,
                                              'uncorrectedItems': 'copyUnchanged', 'gpsStamp': 'photoInstant'})
        self.assertEqual(p['e3']['groups'], {'by': 'recordedDevice', 'keys': ['cameraMake', 'cameraModel', 'bodySerialNumber'], 'itemOverrides': []})

    def test_exact_faults(self):
        track = {'id': 'watch', 'path': '/x/watch.gpx'}
        cases = [(dict(tracks=[dict(track, path='watch.gpx')]), 'INVALID_ARGUMENT', '$.tracks[0].path'),
                 (dict(tracks=[dict(track, path='/x/../y.gpx')]), 'INVALID_ARGUMENT', '$.tracks[0].path'),
                 (dict(tracks=[track, dict(track)]), 'INVALID_ARGUMENT', '$.tracks[1].id'),
                 (dict(tracks=[dict(track, id='a b')]), 'INVALID_ARGUMENT', '$.tracks[0].id'),
                 (dict(tracks=[dict(track, sha256='G' * 64)]), 'INVALID_SHA256', '$.tracks[0].sha256'),
                 (dict(track={'elevation': {'reference': 'geoid'}}), 'INVALID_ARGUMENT', '$.arguments.track.elevation'),
                 (dict(photoTime={'clockCorrection': {'shifts': [{'group': 'dev1', 'shift': {'seconds': '1'}}], 'plan': '/x/p.json'}}), 'INVALID_ARGUMENT', '$.photoTime.clockCorrection'),
                 (dict(photoTime={'assumedOffsets': [{'group': 'dev1', 'offset': '+15:00'}]}), 'INVALID_ARGUMENT', '$.photoTime.assumedOffsets[0].offset'),
                 (dict(photoTime={'assumedOffsets': [{'group': 'dev1', 'offset': '+01:00'}, {'group': 'dev1', 'offset': '+02:00'}]}), 'INVALID_ARGUMENT', '$.assumedOffsets[1].group'),
                 (dict(interpolation={'maxGapSeconds': 3601}), 'INVALID_ARGUMENT', '$.arguments.interpolation.maxGapSeconds'),
                 (dict(interpolation={'overlapAgreementMeters': '1001'}), 'INVALID_ARGUMENT', '$.interpolation.overlapAgreementMeters'),
                 (dict(track={'datum1_0': 'café'}), 'INVALID_ARGUMENT', '$.track.datum1_0'),
                 (dict(policies={'maxSpeedMetersPerSecond': '1001'}), 'INVALID_ARGUMENT', '$.policies.maxSpeedMetersPerSecond')]
        for change, code, at in cases:
            f = fault_of(lambda: self.plan(**change))
            self.assertEqual((f.code, f.location), (code, at), change)
        document = copy.deepcopy(self.BASE)
        del document['tracks']
        self.assertEqual((fault_of(lambda: adaptor.plan(document)).code, fault_of(lambda: adaptor.plan(document)).location), ('MISSING_ARGUMENT', '$.tracks'))

    def test_no_native_geotag_flag_or_expression_can_be_named(self):
        for key in ('geotag', 'geosync', 'expression', 'config', 'api', 'timezone'):
            self.assertEqual(fault_of(lambda: self.plan(**{key: 'x'})).code, 'UNKNOWN_ARGUMENT', key)
        text = json.dumps([b for b in adaptor.schema()['oneOf'] if b['properties']['operation'].get('const') == 'geotagFromTrack']).lower()
        for banned in ('geosync', 'perl', 'expression', 'geotime'):
            self.assertNotIn(banned, text)

    def test_a_plan_and_a_clock_plan_are_paths(self):
        p = self.plan(photoTime={'clockCorrection': {'plan': '/x/time-correction-plan.json'}})
        self.assertEqual(p['e3']['photoTime']['clockCorrection'], {'plan': '/x/time-correction-plan.json'})
        self.assertEqual(self.plan(photoTime={'clockCorrection': 'none'})['e3']['photoTime']['clockCorrection'], 'none')


class Native(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.environ.get('SCHEMAXIS_EXIFTOOL')
        if not path or not os.path.isabs(path) or not Path(path).is_file() or not Path(adaptor.PERL).is_file():
            raise unittest.SkipTest('real ExifTool 13.55 is not configured through SCHEMAXIS_EXIFTOOL')
        cls.exe = path

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='e3-geotag-'))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.runs = 0
        self.track('watch', EQUATOR)

    def track(self, name, data):
        (self.root / (name + '.gpx')).write_bytes(data)
        return str(self.root / (name + '.gpx'))

    def photo_file(self, name, local='12:00:10', offset='+09:00', **kw):
        (self.root / (name + '.jpg')).write_bytes(fx.jpeg(exif_version=b'0300', dto='2026:03:01 ' + local, off=offset, sub=None, **kw))

    def run_op(self, names, tracks=('watch',), **extra):
        self.runs += 1
        out = self.root / ('run%d' % self.runs)
        document = doc('geotagFromTrack', items(self.root, names), tracks=[{'id': t, 'path': str(self.root / (t + '.gpx'))} for t in tracks], **extra)
        result = adaptor.run(document, out, executable=self.exe)
        self.assertTrue(result['verified'])
        self.assertTrue(adaptor.verify(out, executable=self.exe)['verified'])
        return out

    def photo(self, out, name):
        return (out / 'photos' / (name + '.jpg')).read_bytes()

    def report(self, out, name='write-report.json'):
        return json.loads((out / name).read_text())

    def row(self, out, item):
        return next(r for r in self.report(out)['items'] if r['id'] == item)

    def outcome(self, out, item):
        return json.loads((out / 'outcomes' / (item + '.json')).read_text())

    def where(self, data):
        return (total(fx.exif_rationals(data, 'GPS', 2)), fx.exif_ascii(data, 'GPS', 1), total(fx.exif_rationals(data, 'GPS', 4)), fx.exif_ascii(data, 'GPS', 3))

    def test_G1_photographs_are_placed_on_and_between_fixes_with_stamps_and_datum(self):
        for name, local in (('mid', '12:00:10'), ('fix', '12:00:20'), ('late', '12:00:30')):
            self.photo_file(name, local)
        out = self.run_op(['mid', 'fix', 'late'])
        for name, east in (('mid', '10.001'), ('fix', '10.002'), ('late', '10.003')):
            data = self.photo(out, name)
            lat, lat_ref, lon, lon_ref = self.where(data)
            self.assertEqual((lat, lat_ref, lon_ref), (0, 'N', 'E'))
            self.assertLessEqual(abs(lon - Fraction(east)), BOUND, name)                       # the analytic position, within the serialisation bound
            self.assertEqual((fx.exif_bytes(data, 'GPS', 0), fx.exif_ascii(data, 'GPS', 0x12)), ([2, 4, 0, 0], 'WGS-84'))        # a created GPS IFD in an Exif 3.x file; the GPX 1.1 datum
            self.assertEqual(fx.exif_ascii(data, 'GPS', 0x1D), '2026:03:01')
        stamp = fx.exif_rationals(self.photo(out, 'mid'), 'GPS', 7)
        self.assertEqual(sum(Fraction(n, d) * unit for (n, d), unit in zip(stamp, (3600, 60, 1))), 3 * 3600 + 10)      # the photo instant 03:00:10 UTC
        self.assertEqual([self.report(out, 'geotag-plan.json')['items'][i]['placement']['method'] for i in range(3)], ['interpolated', 'exactFix', 'interpolated'])
        mid = self.report(out, 'geotag-plan.json')['items'][0]
        self.assertEqual((mid['placement']['latitude'], mid['placement']['longitude'], mid['photoInstant']['utc'], mid['photoInstant']['basis']), ('0.000000000', '10.001000000', '2026-03-01T03:00:10Z', 'recordedOffset'))
        self.assertEqual((mid['placement']['evidence']['fraction'], mid['placement']['evidence']['spanSeconds']), ('1/2', '20'))

    def test_an_unplaceable_item_is_published_unchanged_with_its_reason_or_refused_by_policy(self):
        self.photo_file('ok')
        self.photo_file('after', '13:00:00')
        original = (self.root / 'after.jpg').read_bytes()
        out = self.run_op(['ok', 'after'])
        row = self.row(out, 'after')
        self.assertEqual((row['outcome'], row['reason'], (out / 'photos' / 'after.jpg').read_bytes()), ('unchanged', 'TRACK_NOT_COVERED', original))
        self.assertEqual(self.report(out, 'geotag-plan.json')['items'][1]['detail']['reason'], 'afterEnd')
        refused = self.run_op(['ok', 'after'], policies={'uncorrectedItems': 'refuseSlot'})
        self.assertEqual(self.outcome(refused, 'after')['fault']['code'], 'ITEM_UNCHANGED')
        self.assertEqual(self.outcome(refused, 'after')['fault']['observed']['reason'], 'TRACK_NOT_COVERED')

    def test_G11_an_elevation_is_written_only_with_a_declared_reference(self):
        self.photo_file('mid')
        self.photo_file('fix', '12:00:20')
        silent = self.run_op(['mid', 'fix'])
        self.assertEqual(fx.exif_rationals(self.photo(silent, 'mid'), 'GPS', 6), None)
        self.assertIn('elevationReferenceUndeclared', self.row(silent, 'mid')['infos'])
        declared = self.run_op(['mid', 'fix'], track={'elevation': {'reference': 'seaLevel'}})
        mid, fix = self.photo(declared, 'mid'), self.photo(declared, 'fix')
        self.assertEqual((fx.exif_bytes(mid, 'GPS', 5), fx.exif_rationals(mid, 'GPS', 6)), ([2], [(15, 1)]))         # halfway between ele 10 and 20
        self.assertEqual((fx.exif_bytes(fix, 'GPS', 5), fx.exif_rationals(fix, 'GPS', 6)), ([2], [(20, 1)]))         # exactly on the fix
        ellipsoidal = self.run_op(['mid'], track={'elevation': {'reference': 'ellipsoidal'}})
        self.assertEqual(fx.exif_bytes(self.photo(ellipsoidal, 'mid'), 'GPS', 5), [0])
        geoid = self.track('geoid', EQUATOR.replace(b'<ele>10</ele>', b'<ele>10</ele><geoidheight>30</geoidheight>', 1))
        self.assertIn('geoidheightPresent', self.row(self.run_op(['mid'], tracks=('geoid',)), 'mid')['infos'])

    def test_G7_two_tracks_agree_or_conflict_deterministically(self):
        self.photo_file('mid')
        near = gpx([[('0.000020', '10.000', '2026-03-01T03:00:00Z'), ('0.000020', '10.002', '2026-03-01T03:00:20Z')]])          # 2.2 m north of the first track
        far = gpx([[('0.000450', '10.000', '2026-03-01T03:00:00Z'), ('0.000450', '10.002', '2026-03-01T03:00:20Z')]])           # 50 m north
        self.track('near', near)
        self.track('far', far)
        agree = self.run_op(['mid'], tracks=('watch', 'near'))
        self.assertEqual(self.report(agree, 'geotag-plan.json')['items'][0]['placement']['overlapCandidates'], 2)
        self.assertEqual(self.where(self.photo(agree, 'mid'))[0], 0)                          # the first listed track wins; nothing is averaged
        clash = self.run_op(['mid'], tracks=('watch', 'far'))
        row = self.row(clash, 'mid')
        self.assertEqual((row['outcome'], row['reason']), ('unchanged', 'TRACK_OVERLAP_CONFLICT'))      # the tracks disagree by 50 m at an agreement of 5 m: refused, not averaged
        self.assertEqual(self.report(clash, 'geotag-plan.json')['items'][0]['detail']['agreementMeters'], '5')

    def test_an_offset_that_is_neither_recorded_nor_assumed_leaves_the_item_unplaced(self):
        (self.root / 'bare.jpg').write_bytes(fx.jpeg(exif_version=b'0300', dto='2026:03:01 12:00:10', off=None, sub=None))
        self.photo_file('ok')
        out = self.run_op(['ok', 'bare'])
        self.assertEqual((self.row(out, 'bare')['outcome'], self.row(out, 'bare')['reason']), ('unchanged', 'OFFSET_UNKNOWN'))       # there is no system time zone to fall back on
        assumed = self.run_op(['ok', 'bare'], photoTime={'assumedOffsets': [{'group': 'dev1', 'offset': '+09:00'}]})
        self.assertLessEqual(abs(self.where(self.photo(assumed, 'bare'))[2] - Fraction('10.001')), BOUND)
        self.assertEqual(self.report(assumed, 'geotag-plan.json')['items'][1]['photoInstant']['basis'], 'assumedOffset')

    def test_a_declared_clock_correction_moves_the_photo_instant_only(self):
        # the camera clock is 5 s fast: recorded 12:00:15 is 03:00:10 true
        self.photo_file('fast', '12:00:15')
        original_time = fx.exif_ascii((self.root / 'fast.jpg').read_bytes(), 'ExifIFD', 0x9003)
        out = self.run_op(['fast'], photoTime={'clockCorrection': {'shifts': [{'group': 'dev1', 'shift': {'seconds': '-5'}}]}})
        data = self.photo(out, 'fast')
        self.assertLessEqual(abs(self.where(data)[2] - Fraction('10.001')), BOUND)
        self.assertEqual(fx.exif_ascii(data, 'ExifIFD', 0x9003), original_time)               # the image's own time field is not rewritten by a geotag
        self.assertEqual(self.report(out, 'geotag-plan.json')['items'][0]['photoInstant']['clockCorrectionNanoseconds'], -5000000000)

    def test_G18_a_correction_plan_applies_to_the_photo_instant_and_a_double_application_is_refused(self):
        self.photo_file('fast', '12:00:15')
        planned = self.root / 'time-plan'
        adaptor.run(doc('correctTime', items(self.root, ['fast']), apply='plan', corrections=[{'group': 'dev1', 'shift': {'seconds': '-5'}}]), planned, executable=self.exe)
        plan = str(planned / 'time-correction-plan.json')
        placed = self.run_op(['fast'], photoTime={'clockCorrection': {'plan': plan}})
        self.assertLessEqual(abs(self.where(self.photo(placed, 'fast'))[2] - Fraction('10.001')), BOUND)
        # the same time correction applied to the file, then geotagged WITH the plan, would correct twice: refused
        corrected = self.root / 'corrected-run'
        adaptor.run(doc('correctTime', items(self.root, ['fast']), corrections=[{'group': 'dev1', 'shift': {'seconds': '-5'}}]), corrected, executable=self.exe)
        (self.root / 'fast.jpg').write_bytes(self.photo(corrected, 'fast'))
        out = self.root / 'double'
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.run(doc('geotagFromTrack', items(self.root, ['fast']), tracks=[{'id': 'watch', 'path': str(self.root / 'watch.gpx')}], photoTime={'clockCorrection': {'plan': plan}}), out, executable=self.exe)
        self.assertEqual(caught.exception.fault.code, 'NO_USABLE_ITEMS')
        self.assertEqual(self.outcome(out, 'fast')['fault']['code'], 'CORRECTION_ALREADY_APPLIED')
        none = self.run_op(['fast'], photoTime={'clockCorrection': 'none'})                  # the corrected file with no further correction: the same position
        self.assertLessEqual(abs(self.where(self.photo(none, 'fast'))[2] - Fraction('10.001')), BOUND)

    def test_gps_stamps_and_old_positions(self):
        gps = {'version': (2, 3, 0, 0), 'lat': ((12, 1), (34, 1), (5, 1)), 'lon': ((45, 1), (40, 1), (0, 1)), 'alt': (100, 1), 'alt_ref': 0, 'datum': 'NAD27', 'date': '2020:01:02', 'time': ((1, 1), (2, 1), (3, 1)), 'direction': (90, 1)}
        self.photo_file('old', gps=gps)
        data = self.photo(self.run_op(['old'], policies={'gpsStamp': 'none'}), 'old')
        self.assertEqual((fx.exif_ascii(data, 'GPS', 0x1D), fx.exif_rationals(data, 'GPS', 7), fx.exif_rationals(data, 'GPS', 6), fx.exif_ascii(data, 'GPS', 0x12)), (None, None, None, 'WGS-84'))
        self.assertEqual((fx.exif_rationals(data, 'GPS', 0x11), fx.exif_bytes(data, 'GPS', 0)), ([(90, 1)], [2, 3, 0, 0]))      # the camera's direction is kept; the GPS version is never rewritten
        self.assertLessEqual(abs(self.where(data)[2] - Fraction('10.001')), BOUND)

    def test_plan_only_publishes_the_plan_first_and_the_plan_applies(self):
        self.photo_file('mid')
        self.photo_file('fix', '12:00:20')
        tracks = [{'id': 'watch', 'path': str(self.root / 'watch.gpx')}]
        planned = self.root / 'planned'
        result = adaptor.run(doc('geotagFromTrack', items(self.root, ['mid', 'fix']), tracks=tracks, apply='plan'), planned, executable=self.exe)
        self.assertEqual((result['planned'], result['written']), (2, 0))
        receipt = json.loads((planned / 'verification.json').read_text())
        self.assertEqual([Path(a['file']).name for a in receipt['artifacts']], ['geotag-plan.json', 'track-report.json', 'manifest.json'])
        self.assertTrue(adaptor.verify(planned, executable=self.exe)['verified'])
        direct = self.run_op(['mid', 'fix'])
        applied = self.root / 'applied'
        adaptor.run(doc('geotagFromTrack', items(self.root, ['mid', 'fix']), plan=str(planned / 'geotag-plan.json')), applied, executable=self.exe)
        for name in ('mid', 'fix'):
            self.assertEqual(self.photo(applied, name), self.photo(direct, name))
        # a different track under the same name is not the recorded one
        self.track('watch', EQUATOR.replace(b'10.004', b'10.005'))
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.run(doc('geotagFromTrack', items(self.root, ['mid', 'fix']), plan=str(planned / 'geotag-plan.json')), self.root / 'changed-track', executable=self.exe)
        self.assertEqual(caught.exception.fault.code, 'TRACK_HASH_MISMATCH')

    def test_a_refused_or_unsupported_track_fails_the_run_before_anything_is_written(self):
        self.photo_file('mid')
        bomb = b'<?xml version="1.0"?><!DOCTYPE gpx [<!ENTITY a "aaaa">]><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"/>'
        for name, data, code in (('dtd', bomb, 'TRACK_DTD_REFUSED'), ('notgpx', b'<?xml version="1.0"?><kml/>', 'TRACK_NOT_GPX'), ('utf16', '<gpx/>'.encode('utf-16'), 'TRACK_ENCODING_UNSUPPORTED')):
            self.track(name, data)
            out = self.root / ('fail-' + name)
            with self.assertRaises(SchemaxisError) as caught:
                adaptor.run(doc('geotagFromTrack', items(self.root, ['mid']), tracks=[{'id': name, 'path': str(self.root / (name + '.gpx'))}]), out, executable=self.exe)
            self.assertEqual(caught.exception.fault.code, code, name)
            self.assertFalse((out / 'photos').exists())
        pinned = self.root / 'fail-pin'
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.run(doc('geotagFromTrack', items(self.root, ['mid']), tracks=[{'id': 'watch', 'path': str(self.root / 'watch.gpx'), 'sha256': '0' * 64}]), pinned, executable=self.exe)
        self.assertEqual(caught.exception.fault.code, 'TRACK_HASH_MISMATCH')


    # ---------------------------------------------------------------- writer-review regressions (E3W-1, E3W-4, E3W-5 and the plan pins)
    LONG = gpx([[('0', '10.000', '2026-03-01T03:00:00Z', '10'), ('0', '10.002', '2026-03-01T03:00:20Z', '20'), ('0', '10.004', '2026-03-01T03:00:40Z', '30'),
                 ('0', '10.060', '2026-03-01T04:00:00Z', '40'), ('0', '10.062', '2026-03-01T04:00:20Z', '50')]])

    def clock_plan(self, name, corrections, files=('fast',)):
        planned = self.root / ('clock-' + name)
        adaptor.run(doc('correctTime', items(self.root, list(files)), apply='plan', corrections=corrections), planned, executable=self.exe)
        return planned, str(planned / 'time-correction-plan.json')

    def test_E3W1_a_clock_plan_that_sets_the_offset_places_the_corrected_instant_in_both_keep_modes(self):
        """12:00:10 +09:00 is 03:00:10Z. Keeping the instant while setting +10:00 leaves 03:00:10Z (lon 10.001); keeping the wall clock while setting +08:00 makes 12:00:10 +08:00 =
        04:00:10Z (lon 10.061). Applying the plan and applying correctTime to the file then geotagging with no correction must give the same placement."""
        self.track('long', self.LONG)
        for keep, offset, instant, lon in (('instant', '+10:00', '2026-03-01T03:00:10Z', '10.001'), ('wallClock', '+08:00', '2026-03-01T04:00:10Z', '10.061')):
            self.photo_file('p', '12:00:10')
            corrections = [{'group': 'dev1', 'setOffset': {'offset': offset, 'keep': keep}}]
            _, plan = self.clock_plan(keep, corrections, ['p'])
            via_plan = self.run_op(['p'], tracks=('long',), photoTime={'clockCorrection': {'plan': plan}})
            self.assertEqual(self.report(via_plan, 'geotag-plan.json')['items'][0]['photoInstant']['utc'], instant, keep)
            self.assertLessEqual(abs(self.where(self.photo(via_plan, 'p'))[2] - Fraction(lon)), BOUND, keep)
            applied = self.root / ('applied-' + keep)
            adaptor.run(doc('correctTime', items(self.root, ['p']), corrections=corrections), applied, executable=self.exe)
            (self.root / 'p.jpg').write_bytes(self.photo(applied, 'p'))
            via_file = self.run_op(['p'], tracks=('long',), photoTime={'clockCorrection': 'none'})
            self.assertEqual(self.where(self.photo(via_file, 'p')), self.where(self.photo(via_plan, 'p')), keep)       # the two documented-equivalent routes agree exactly
            self.assertEqual(self.report(via_file, 'geotag-plan.json')['items'][0]['photoInstant']['utc'], instant, keep)

    def test_E3W4_a_refused_clock_plan_entry_is_never_a_zero_correction_and_a_forged_delta_is_inconsistent(self):
        self.track('long', self.LONG)
        for name, make in (('a', 'A'), ('b', 'B')):
            (self.root / (name + '.jpg')).write_bytes(fx.jpeg(exif_version=b'0300', make=make, dto='2026:03:01 12:00:15', off='+09:00', sub=None))
        planned, plan = self.clock_plan('mixed', [{'group': 'dev1', 'shift': {'seconds': '-5'}}, {'group': 'dev2', 'from': 'references'}], ['a', 'b'])
        out = self.run_op(['a', 'b'], tracks=('long',), photoTime={'clockCorrection': {'plan': plan}})
        self.assertEqual(self.row(out, 'a')['outcome'], 'located')
        self.assertLessEqual(abs(self.where(self.photo(out, 'a'))[2] - Fraction('10.001')), BOUND)         # 12:00:15 - 5 s = 12:00:10 = 03:00:10Z
        self.assertEqual((self.row(out, 'b')['status'], self.row(out, 'b')['fault']['code']), ('refused', 'CLOCK_CORRECTION_UNAVAILABLE'))      # the plan has no correction for b: it is not placed on its uncorrected instant
        self.assertFalse((out / 'photos' / 'b.jpg').exists())
        self.assertEqual(self.outcome(out, 'b')['fault']['observed']['planCode'], 'GROUP_NOT_ANCHORED')
        document = json.loads((planned / 'time-correction-plan.json').read_text())
        captured = next(g for g in document['items'][0]['groups'] if g['group'] == 'captured')
        captured['deltaNanoseconds'] = -15000000000                                                          # contradicts the plan's own before and after states
        forged = self.root / 'forged.json'
        forged.write_text(json.dumps(document, indent=2))
        out2 = self.root / 'forged-run'
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.run(doc('geotagFromTrack', items(self.root, ['a']), tracks=[{'id': 'long', 'path': str(self.root / 'long.gpx')}], photoTime={'clockCorrection': {'plan': str(forged)}}), out2, executable=self.exe)
        self.assertEqual(caught.exception.fault.code, 'NO_USABLE_ITEMS')
        self.assertEqual(self.outcome(out2, 'a')['fault']['code'], 'PLAN_INCONSISTENT')

    def test_E3W5_an_unresolved_recorded_offset_is_not_replaced_by_an_assumed_one(self):
        (self.root / 'bad.jpg').write_bytes(fx.jpeg(exif_version=b'0300', dto='2026:03:01 12:00:10', off='+15:00', sub=None))        # +15:00 is outside the offset range: unreadable, not absent
        (self.root / 'none.jpg').write_bytes(fx.jpeg(exif_version=b'0300', dto='2026:03:01 12:00:10', off=None, sub=None))
        out = self.run_op(['bad', 'none'], photoTime={'assumedOffsets': [{'group': 'dev1', 'offset': '+09:00'}]})
        self.assertEqual((self.row(out, 'bad')['outcome'], self.row(out, 'bad')['reason']), ('unchanged', 'TIME_SOURCE_UNREADABLE'))
        self.assertEqual(self.row(out, 'none')['outcome'], 'located')                                       # a truly absent offset is still assumed
        self.assertEqual(self.report(out, 'geotag-plan.json')['items'][1]['photoInstant']['basis'], 'assumedOffset')

    def test_P3_a_changed_clock_plan_is_pinned_and_part_of_the_reuse_identity_of_a_plan_application(self):
        self.track('long', self.LONG)
        self.photo_file('p', '12:00:10')
        _, clock = self.clock_plan('pin', [{'group': 'dev1', 'shift': {'seconds': '0'}}], ['p'])
        geo = self.root / 'geo-planned'
        adaptor.run(doc('geotagFromTrack', items(self.root, ['p']), tracks=[{'id': 'long', 'path': str(self.root / 'long.gpx')}], photoTime={'clockCorrection': {'plan': clock}}, apply='plan'), geo, executable=self.exe)
        application = doc('geotagFromTrack', items(self.root, ['p']), plan=str(geo / 'geotag-plan.json'))
        keys = adaptor.reusableInputs(application)
        self.assertIn(clock, keys)                                                                           # the clock plan named in the recorded inputs is a reuse input
        Path(clock).write_bytes(Path(clock).read_bytes() + b'\n')                                              # the same document with other bytes is a different input
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.run(application, self.root / 'pin', executable=self.exe)
        self.assertEqual(caught.exception.fault.code, 'CLOCK_PLAN_HASH_MISMATCH')

    # ---------------------------------------------------------------- clock-plan consistency (final-review findings E3F-1, E3F-2 and E3F-P3-1)
    # Hand literals: on LONG, t seconds after 03:00:00Z (t < 20) is at longitude 10 + t / 10000 degrees east. Every expected instant below is worked by hand from the
    # recorded 12:00:10 +09:00 (03:00:10Z) and the declared correction, never read from a plan or from the writer under test.
    def forged(self, plan, tag, edit):
        document = json.loads(Path(plan).read_text())
        edit(document)
        path = self.root / ('forged-%s.json' % tag)
        path.write_text(json.dumps(document, indent=2))
        return str(path)

    def refused_by_the_clock_plan(self, names, plan, tag):
        out = self.root / ('forged-run-' + tag)
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.run(doc('geotagFromTrack', items(self.root, names), tracks=[{'id': 'long', 'path': str(self.root / 'long.gpx')}], photoTime={'clockCorrection': {'plan': plan}}), out, executable=self.exe)
        self.assertEqual(caught.exception.fault.code, 'NO_USABLE_ITEMS', tag)
        self.assertFalse((out / 'photos').exists(), tag)                                                      # nothing is placed or written from a contradictory plan
        return [self.outcome(out, n)['fault']['code'] for n in names]

    @staticmethod
    def entry_of(document, name):
        return next(e for e in document['items'] if e['id'] == name)

    @classmethod
    def captured_of(cls, document, name):
        return next(g for g in cls.entry_of(document, name)['groups'] if g['group'] == 'captured')

    def test_E3F1_a_clock_plan_that_contradicts_its_own_offset_is_refused_whatever_component_is_edited(self):
        """The plan keeps the instant while setting +10:00: 12:00:10 +09:00 -> 13:00:10 +10:00, still 03:00:10Z (lon 10.001). Editing only after.offset back to +09:00 would put
        the photo at 13:00:10 +09:00 = 04:00:10Z (lon 10.061), 3600 s late; every such edit is PLAN_INCONSISTENT and nothing is placed."""
        self.track('long', self.LONG)
        self.photo_file('a', '12:00:10')
        _, plan = self.clock_plan('f1', [{'group': 'dev1', 'setOffset': {'offset': '+10:00', 'keep': 'instant'}}], ['a'])
        genuine = json.loads(Path(plan).read_text())
        self.assertEqual(self.entry_of(genuine, 'a')['arguments'], ['-n', '-ExifIFD:DateTimeOriginal=2026:03:01 13:00:10', '-ExifIFD:OffsetTimeOriginal=+10:00'])        # hand literal
        control = self.run_op(['a'], tracks=('long',), photoTime={'clockCorrection': {'plan': plan}})
        self.assertEqual(self.report(control, 'geotag-plan.json')['items'][0]['photoInstant']['utc'], '2026-03-01T03:00:10Z')
        self.assertLessEqual(abs(self.where(self.photo(control, 'a'))[2] - Fraction('10.001')), BOUND)

        def after_offset(d): self.captured_of(d, 'a')['after']['offset'] = '+09:00'
        def argument_only(d): self.entry_of(d, 'a')['arguments'][2] = '-ExifIFD:OffsetTimeOriginal=+09:00'
        def target_only(d):
            for t in self.captured_of(d, 'a')['targets']:
                for c in t['components']:
                    if c['kind'] == 'offset':
                        c['after'] = '+09:00'
        def target_write_only(d):
            for t in self.captured_of(d, 'a')['targets']:
                for w in t['writes']:
                    if w['name'] == 'ExifIFD:OffsetTimeOriginal':
                        w['value'] = '+09:00'
        def coherent_but_not_the_declared_intent(d):                                                           # the after offset, its target and its native argument agree with each other, not with the keep-instant request
            after_offset(d)
            argument_only(d)
            target_only(d)
            target_write_only(d)
        def extra_native_argument(d): self.entry_of(d, 'a')['arguments'].append('-Artist=forged')
        def dropped_native_argument(d): self.entry_of(d, 'a')['arguments'].pop()
        def claimed_unchanged(d): self.entry_of(d, 'a').update(status='unchanged', outcome='unchanged', reason='zeroNetChange', detail={'group': 'dev1'}, arguments=[])
        for tag, edit in (('after-offset', after_offset), ('argument', argument_only), ('target', target_only), ('target-write', target_write_only), ('coherent', coherent_but_not_the_declared_intent),
                          ('extra-argument', extra_native_argument), ('dropped-argument', dropped_native_argument)):
            self.assertEqual(self.refused_by_the_clock_plan(['a'], self.forged(plan, tag, edit), tag), ['PLAN_INCONSISTENT'], tag)
        entry_gone = self.forged(plan, 'unchanged', claimed_unchanged)
        self.assertEqual(self.refused_by_the_clock_plan(['a'], entry_gone, 'unchanged'), ['PLAN_INCONSISTENT'])   # a correction cannot be dropped by relabelling the entry as unchanged

    def test_E3F1_a_forged_fraction_or_wall_time_is_refused_even_when_the_delta_agrees(self):
        """12:00:10.12 +09:00 shifted by 0.5 s is 12:00:10.62 = 03:00:10.62Z (lon 10.001062); the plan writes SubSecTimeOriginal=62. Forging after.fraction to 92 and the delta to
        0.8 s keeps the wall equation but would place 03:00:10.92Z (lon 10.001092) while the native argument still says 62."""
        self.track('long', self.LONG)
        (self.root / 's.jpg').write_bytes(fx.jpeg(exif_version=b'0300', dto='2026:03:01 12:00:10', off='+09:00', sub='12'))
        _, plan = self.clock_plan('f1-fraction', [{'group': 'dev1', 'shift': {'seconds': '0.5'}}], ['s'])
        genuine = json.loads(Path(plan).read_text())
        self.assertEqual(self.entry_of(genuine, 's')['arguments'], ['-n', '-ExifIFD:SubSecTimeOriginal=62'])                      # hand literal: the whole second does not change, so only the fraction is written
        control = self.run_op(['s'], tracks=('long',), photoTime={'clockCorrection': {'plan': plan}})
        self.assertEqual(self.report(control, 'geotag-plan.json')['items'][0]['photoInstant']['utc'], '2026-03-01T03:00:10.62Z')
        self.assertLessEqual(abs(self.where(self.photo(control, 's'))[2] - Fraction('10.001062')), BOUND)

        def fraction_and_delta(d):
            captured = self.captured_of(d, 's')
            captured['after']['fraction'] = '92'
            captured['deltaNanoseconds'] = 800000000
        def fraction_only(d): self.captured_of(d, 's')['after']['fraction'] = '92'
        def sub_second_argument_only(d): self.entry_of(d, 's')['arguments'][1] = '-ExifIFD:SubSecTimeOriginal=92'
        for tag, edit in (('fraction-and-delta', fraction_and_delta), ('fraction', fraction_only), ('subsecond-argument', sub_second_argument_only)):
            self.assertEqual(self.refused_by_the_clock_plan(['s'], self.forged(plan, tag, edit), tag), ['PLAN_INCONSISTENT'], tag)
        # a whole-second shift of 5 s: 12:00:10 -> 12:00:15 = 03:00:15Z (lon 10.0015). One hour later (after.local, delta, native date and target all agreeing) is not what 5 s declares.
        self.photo_file('w', '12:00:10')
        _, shift = self.clock_plan('f1-wall', [{'group': 'dev1', 'shift': {'seconds': '5'}}], ['w'])
        self.assertEqual(self.entry_of(json.loads(Path(shift).read_text()), 'w')['arguments'], ['-n', '-ExifIFD:DateTimeOriginal=2026:03:01 12:00:15'])      # hand literal
        placed = self.run_op(['w'], tracks=('long',), photoTime={'clockCorrection': {'plan': shift}})
        self.assertEqual(self.report(placed, 'geotag-plan.json')['items'][0]['photoInstant']['utc'], '2026-03-01T03:00:15Z')
        self.assertLessEqual(abs(self.where(self.photo(placed, 'w'))[2] - Fraction('10.0015')), BOUND)

        def whole_second_forgery(d):
            captured = self.captured_of(d, 'w')
            captured['after']['local'] = '2026-03-01T13:00:15'
            captured['deltaNanoseconds'] = 3605000000000
            self.entry_of(d, 'w')['arguments'][1] = '-ExifIFD:DateTimeOriginal=2026:03:01 13:00:15'
            for t in captured['targets']:
                for c in t['components']:
                    if c['kind'] == 'local':
                        c['after'] = '2026-03-01T13:00:15'
                for w in t['writes']:
                    w['value'] = '2026:03:01 13:00:15'
        self.assertEqual(self.refused_by_the_clock_plan(['w'], self.forged(shift, 'whole-second', whole_second_forgery), 'whole-second'), ['PLAN_INCONSISTENT'])

    def test_E3F2_genuine_clock_plans_over_exif_xmp_xmp_only_iptc_and_subsecond_sources_place_the_corrected_instants(self):
        """All four photographs record 12:00:10 +09:00 (xmponly: 12:00:10.5; subsec: 12:00:10.12). A +0.5 s shift gives 03:00:10.5Z, 03:00:11Z (12:00:10.5 + 0.5), 03:00:10.5Z and
        03:00:10.62Z; setOffset +10:00 keeping the instant leaves 03:00:10Z, 03:00:10.5Z, 03:00:10Z and 03:00:10.12Z. Longitude is 10 + t/10000."""
        self.track('long', self.LONG)
        (self.root / 'exifxmp.jpg').write_bytes(fx.jpeg(exif_version=b'0300', dto='2026:03:01 12:00:10', off='+09:00', sub=None,
                                                        xmp=fx.xmp_properties(exif_dto='2026-03-01T12:00:10+09:00', captured='2026-03-01T12:00:10+09:00')))
        (self.root / 'xmponly.jpg').write_bytes(fx.jpeg(exif=False, xmp=fx.xmp_properties(exif_dto='2026-03-01T12:00:10.5+09:00')))
        (self.root / 'iptc.jpg').write_bytes(fx.jpeg(exif_version=b'0300', dto='2026:03:01 12:00:10', off='+09:00', sub=None, iptc=[(2, 55, '20260301'), (2, 60, '120010+0900')]))
        (self.root / 'subsec.jpg').write_bytes(fx.jpeg(exif_version=b'0300', dto='2026:03:01 12:00:10', off='+09:00', sub='12'))
        names = ['exifxmp', 'xmponly', 'iptc', 'subsec']
        for tag, correction, expected in (
                ('shift', lambda g: {'group': g, 'shift': {'seconds': '0.5'}},
                 {'exifxmp': ('2026-03-01T03:00:10.5Z', '10.00105'), 'xmponly': ('2026-03-01T03:00:11Z', '10.0011'), 'iptc': ('2026-03-01T03:00:10.5Z', '10.00105'), 'subsec': ('2026-03-01T03:00:10.62Z', '10.001062')}),
                ('offset', lambda g: {'group': g, 'setOffset': {'offset': '+10:00', 'keep': 'instant'}},
                 {'exifxmp': ('2026-03-01T03:00:10Z', '10.001'), 'xmponly': ('2026-03-01T03:00:10.5Z', '10.00105'), 'iptc': ('2026-03-01T03:00:10Z', '10.001'), 'subsec': ('2026-03-01T03:00:10.12Z', '10.001012')})):
            planned, plan = self.clock_plan('f2-' + tag, [correction(g) for g in ('dev1', 'dev2')], names)
            entries = {e['id']: e for e in json.loads(Path(plan).read_text())['items']}
            self.assertEqual({n: e['status'] for n, e in entries.items()}, {n: 'planned' for n in names}, tag)        # the planner corrected every source family
            out = self.run_op(names, tracks=('long',), photoTime={'clockCorrection': {'plan': plan}})
            reported = {r['id']: r for r in self.report(out, 'geotag-plan.json')['items']}
            for name, (instant, longitude) in expected.items():
                self.assertEqual((tag, name, reported[name]['outcome'], reported[name]['photoInstant']['utc']), (tag, name, 'located', instant))
                self.assertLessEqual(abs(self.where(self.photo(out, name))[2] - Fraction(longitude)), BOUND, (tag, name))

    def test_E3FP3_a_plan_that_sets_an_offset_on_an_unrecorded_one_places_the_planned_after_instant_without_inventing_a_before_instant(self):
        """No recorded offset and none assumed: setOffset +09:00 keeping the wall clock makes 12:00:10 +09:00 = 03:00:10Z (lon 10.001), as the corrected file does. The
        before instant stays unknown, so the published correction amount is null; an assumed offset keeps its own basis, and a shift alone still has no offset."""
        self.track('long', self.LONG)
        self.photo_file('b', '12:00:10', offset=None)
        _, plan = self.clock_plan('p3', [{'group': 'dev1', 'setOffset': {'offset': '+09:00', 'keep': 'wallClock'}}], ['b'])
        via_plan = self.run_op(['b'], tracks=('long',), photoTime={'clockCorrection': {'plan': plan}})
        instant = self.report(via_plan, 'geotag-plan.json')['items'][0]['photoInstant']
        self.assertEqual(instant, {'utc': '2026-03-01T03:00:10Z', 'basis': 'plannedOffset', 'clockCorrectionNanoseconds': None})
        self.assertLessEqual(abs(self.where(self.photo(via_plan, 'b'))[2] - Fraction('10.001')), BOUND)
        corrected = self.root / 'p3-corrected'
        adaptor.run(doc('correctTime', items(self.root, ['b']), corrections=[{'group': 'dev1', 'setOffset': {'offset': '+09:00', 'keep': 'wallClock'}}]), corrected, executable=self.exe)
        (self.root / 'b2.jpg').write_bytes(self.photo(corrected, 'b'))
        via_file = self.run_op(['b2'], tracks=('long',), photoTime={'clockCorrection': 'none'})
        self.assertEqual(self.where(self.photo(via_file, 'b2')), self.where(self.photo(via_plan, 'b')))                      # the plan route and the corrected-file route agree exactly
        geo = self.root / 'p3-planned'
        adaptor.run(doc('geotagFromTrack', items(self.root, ['b']), tracks=[{'id': 'long', 'path': str(self.root / 'long.gpx')}], photoTime={'clockCorrection': {'plan': plan}}, apply='plan'), geo, executable=self.exe)
        applied = self.root / 'p3-applied'
        self.assertTrue(adaptor.run(doc('geotagFromTrack', items(self.root, ['b']), plan=str(geo / 'geotag-plan.json')), applied, executable=self.exe)['verified'])
        self.assertEqual(self.report(applied, 'geotag-plan.json')['items'][0]['photoInstant'], instant)
        assumed = self.run_op(['b'], tracks=('long',), photoTime={'assumedOffsets': [{'group': 'dev1', 'offset': '+08:00'}], 'clockCorrection': {'plan': plan}})
        self.assertEqual(self.report(assumed, 'geotag-plan.json')['items'][0]['photoInstant'],
                         {'utc': '2026-03-01T03:00:10Z', 'basis': 'assumedOffset', 'clockCorrectionNanoseconds': -3600000000000})   # 12:00:10 +08:00 would be 04:00:10Z; the plan's +09:00 moves it back 3600 s
        self.assertEqual(self.refused_by_the_clock_plan(['b'], self.forged(plan, 'p3-offset', lambda d: self.captured_of(d, 'b')['after'].update(offset='+10:00')), 'p3-offset'), ['PLAN_INCONSISTENT'])
        _, shift_only = self.clock_plan('p3-shift', [{'group': 'dev1', 'shift': {'seconds': '5'}}], ['b'])
        unplaced = self.run_op(['b'], tracks=('long',), photoTime={'clockCorrection': {'plan': shift_only}})
        self.assertEqual((self.row(unplaced, 'b')['outcome'], self.row(unplaced, 'b')['reason']), ('unchanged', 'OFFSET_UNKNOWN'))      # a wall-clock shift alone still has no offset to place the photograph on

    def test_E3F1_a_references_clock_plan_is_consumed_and_its_wall_move_must_match_its_recorded_skew(self):
        """The reference says 12:00:10 on this camera was truly 12:00:05 +09:00, so the camera is 5 s fast: 12:00:10 -> 03:00:05Z (lon 10.0005) and 12:00:20 -> 03:00:15Z
        (lon 10.0015). The wall-clock move of a references plan cannot be re-derived from one geotag run, but it must agree with the plan's recorded skew."""
        self.track('long', self.LONG)
        self.photo_file('r', '12:00:10')
        self.photo_file('q', '12:00:20')
        planned = self.root / 'clock-references'
        adaptor.run(doc('correctTime', items(self.root, ['r', 'q']), apply='plan', references=[{'item': 'r', 'trueLocal': '2026-03-01T12:00:05', 'trueOffset': '+09:00'}],
                        corrections=[{'group': 'dev1', 'from': 'references'}]), planned, executable=self.exe)
        plan = str(planned / 'time-correction-plan.json')
        entries = json.loads(Path(plan).read_text())
        self.assertEqual((self.entry_of(entries, 'r')['skewSeconds'], self.entry_of(entries, 'r')['basis']), ('5', 'references'))      # skew = recorded - true
        out = self.run_op(['r', 'q'], tracks=('long',), photoTime={'clockCorrection': {'plan': plan}})
        reported = {r['id']: r['photoInstant'] for r in self.report(out, 'geotag-plan.json')['items']}
        self.assertEqual((reported['r']['utc'], reported['q']['utc']), ('2026-03-01T03:00:05Z', '2026-03-01T03:00:15Z'))
        self.assertLessEqual(abs(self.where(self.photo(out, 'r'))[2] - Fraction('10.0005')), BOUND)
        self.assertLessEqual(abs(self.where(self.photo(out, 'q'))[2] - Fraction('10.0015')), BOUND)

        def other_skew(d): self.entry_of(d, 'r')['skewSeconds'] = '6'
        def other_delta(d): self.captured_of(d, 'r')['deltaNanoseconds'] = -6000000000
        for tag, edit in (('skew', other_skew), ('delta', other_delta)):
            self.assertEqual(self.refused_by_the_clock_plan(['r'], self.forged(plan, 'ref-' + tag, edit), 'ref-' + tag), ['PLAN_INCONSISTENT'], tag)


class Mutants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.environ.get('SCHEMAXIS_EXIFTOOL')
        if not path or not os.path.isabs(path) or not Path(path).is_file() or not Path(adaptor.PERL).is_file():
            raise unittest.SkipTest('real ExifTool 13.55 is not configured through SCHEMAXIS_EXIFTOOL')
        cls.exe = path
        cls.tmp = Path(tempfile.mkdtemp(prefix='e3-geotag-mutants-')).resolve()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        (cls.tmp / 'watch.gpx').write_bytes(EQUATOR)
        for name, local in (('mid', '12:00:10'), ('late', '13:00:00')):
            (cls.tmp / (name + '.jpg')).write_bytes(fx.jpeg(exif_version=b'0300', dto='2026:03:01 ' + local, off='+09:00', sub=None))
        cls.main = cls.tmp / 'main'
        adaptor.run(doc('geotagFromTrack', items(cls.tmp, ['mid', 'late']), tracks=[{'id': 'watch', 'path': str(cls.tmp / 'watch.gpx')}]), cls.main, executable=cls.exe)

    def mutate(self, name, relative, replace, refresh_first=True):
        target = self.tmp / ('mutant-' + name)
        shutil.copytree(self.main, target, symlinks=True)
        path = target / relative
        path.write_bytes(replace(path.read_bytes()))
        if refresh_first:
            from test_exiftool_write_complete import refresh
            refresh(target, self.main)
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.verify(target, executable=self.exe)
        fault = caught.exception.fault
        cause = fault.observed.get('cause', {})
        return cause.get('code', fault.code), cause.get('location', fault.location)

    def test_the_unmutated_run_verifies(self):
        self.assertTrue(adaptor.verify(self.main, executable=self.exe)['verified'])

    def test_M_G1_an_altered_retained_track_is_a_changed_capture(self):
        code, _ = self.mutate('G1', 'inputs/track-1-watch.gpx', lambda d: d.replace(b'10.002', b'10.003', 1), refresh_first=False)
        self.assertEqual(code, 'CAPTURE_CHANGED')

    def test_M_G2_an_edited_interpolation_in_the_plan(self):
        code, location = self.mutate('G2', 'geotag-plan.json', lambda d: d.replace(b'"longitude": "10.001000000"', b'"longitude": "10.001000001"', 1))
        self.assertEqual((code, location), ('INTERPOLATION_MISMATCH', 'geotag-plan.json'))

    def test_M_G3_edited_track_report_counts_fail_the_publication_check(self):
        code, location = self.mutate('G3', 'track-report.json', lambda d: d.replace(b'"timed": 3', b'"timed": 4', 1))
        self.assertEqual((code, location), ('VERIFICATION_FAILED', 'track-report.json'))


if __name__ == '__main__':
    unittest.main()
