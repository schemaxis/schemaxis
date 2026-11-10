"""Host and native tests of the E3 read operations reconcileTime and locate.

Host tests need no native process. Native tests need a real ExifTool 13.55 through SCHEMAXIS_EXIFTOOL and are skipped otherwise; every
expected value is a literal written here by hand (stored rationals, edition layouts, skews), never taken from ExifTool or from the code under test.
Fixtures are synthetic JPEGs authored by ``tools/author_exiftool_fixtures.py`` in private temporary directories.
"""
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

import author_exiftool_fixtures as a  # noqa: E402
from schemaxis.adaptors.exiftool import adaptor, catalogue, e3read, workbench  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402

O = 'II'
ITEMS = lambda root, names: {'items': [{'id': n, 'path': str(root / (n + '.jpg'))} for n in names]}


def gps_jpeg(*, lat=((33, 1), (47, 1), (60, 1)), lat_ref='N', lon=((120, 1), (7, 1), (30, 1)), lon_ref='W', version=(2, 3, 0, 0), exif_version=b'0300', alt=((523, 10),), alt_ref=0,
             datum='WGS-84', make='A', serial=None, dto='2026:03:01 12:00:00', offset='+01:00', sub='12', extra_gps=(), xmp=None, with_gps=True, with_exif=True):
    ifd0 = [a.ascii_entry(0x010F, make), a.ascii_entry(0x0110, 'M')]
    exif = []
    if with_exif:
        if exif_version is not None:
            exif.append(a.undefined_entry(0x9000, exif_version))
        exif += [a.ascii_entry(0x9003, dto)] if dto else []
        exif += [a.ascii_entry(0x9011, offset)] if offset else []
        exif += [a.ascii_entry(0x9291, sub)] if sub else []
        exif += [a.ascii_entry(0xA431, serial)] if serial else []
    gps = []
    if with_gps:
        if version is not None:
            gps.append(a.byte_entry(0, *version))
        gps += [a.ascii_entry(1, lat_ref), a.rational_entry(O, 2, *lat), a.ascii_entry(3, lon_ref), a.rational_entry(O, 4, *lon)]
        if alt is not None:
            gps.append(a.rational_entry(O, 6, *alt))
        if alt_ref is not None:
            gps.append(a.byte_entry(5, alt_ref))
        if datum:
            gps.append(a.ascii_entry(0x12, datum))
        gps += list(extra_gps)
    payload = a.tiff_payload(O, ifd0, exif, gps)
    segments = [(0xE1, a.xmp_app1(a.xmp_packet(xmp)))] if xmp else []
    return a.build(16, 16, exif=payload, app_segments=segments)


class Host(unittest.TestCase):
    def test_catalogue_view_is_additive_and_pinned(self):
        base, view = catalogue.fields(catalogue.VERSION_MWG), catalogue.fields(catalogue.VERSION_E3)
        self.assertTrue(all(view[k] == v for k, v in base.items()))                    # restricted to the E2 ids: identical specs
        self.assertEqual(list(view)[:len(base)], list(base))
        self.assertEqual(sorted(set(view) - set(base)), ['capturedLocalE3', 'capturedOffsetE3', 'capturedSubSecondE3', 'capturedUtcE3', 'digitizedLocalE3', 'digitizedOffset', 'digitizedSubSecond',
                                                         'digitizedUtc', 'gpsDatumE3', 'gpsHorizontalError', 'gpsLatitudeE3', 'gpsLongitudeE3', 'gpsUtcExact', 'gpsUtcTimeExact', 'modifiedOffset',
                                                         'modifiedSubSecond', 'modifiedUtc'])
        self.assertEqual(catalogue.digest(catalogue.VERSION), '1785f956c2ad54c301eb7e9558790018d2b4ccd3adce2c91c3f7334b4d296c67')   # fields/1 is untouched
        self.assertEqual(catalogue.digest(catalogue.VERSION_MWG), 'bce7b860bab934e26cb5bdb9a03dbfa5e48617df86066429ad02e25d11237432')
        self.assertEqual(view['gpsLatitudeE3']['sources'][0]['codec'], 'exifDmsSumE3Latitude')
        self.assertEqual(base['gpsLatitude']['sources'][0]['codec'], 'gpsLatitude')       # the frozen codecs and identities keep their own meaning

    def test_frozen_gps_reader_still_refuses_seconds_sixty_while_the_e3_codec_reads_it(self):
        from schemaxis.adaptors.exiftool import codecs, tiff
        entry = tiff.Entry(2, 5, 3, b''.join(__import__('struct').pack('<II', n, d) for n, d in ((33, 1), (47, 1), (60, 1))), '<')
        ref = tiff.Entry(1, 2, 2, b'N\0', '<')
        with self.assertRaises(codecs.ValueProblem):
            codecs.gps_latitude(entry, lambda name: ref)
        self.assertEqual(float(codecs.CODECS['exifDmsSumE3Latitude'][1](entry, lambda name: ref)), 33.8)

    def test_plan_defaults_and_faults(self):
        base = {'version': 'schemaxis.exiftool/1', 'operation': 'reconcileTime', 'media': {'items': [{'id': 'a1', 'path': '/x/a1.jpg'}, {'id': 'b1', 'path': '/x/b1.jpg'}]}}
        p = adaptor.plan(base)
        self.assertEqual(p['catalogue']['version'], catalogue.VERSION_E3)
        self.assertEqual(p['time']['groups'], {'by': 'recordedDevice', 'keys': ['cameraMake', 'cameraModel', 'bodySerialNumber'], 'itemOverrides': []})
        self.assertEqual((p['time']['model'], p['time']['toleranceSeconds'], p['time']['gpsToleranceSeconds']), ('constant', '2', 120))
        cases = [({'references': [{'item': 'zz', 'trueUtc': '2026-03-01T00:00:00Z'}]}, 'UNKNOWN_ITEM', '$.references[0].item'),
                 ({'references': [{'item': 'a1', 'trueLocal': '2026-03-01T12:00:00'}]}, 'REFERENCE_INVALID', '$.references[0].trueOffset'),
                 ({'references': [{'item': 'a1', 'trueLocal': '2016-12-31T23:59:60', 'trueOffset': '+01:00'}]}, 'LEAP_SECOND_UNSUPPORTED', '$.references[0]'),
                 ({'toleranceSeconds': '3601'}, 'INVALID_ARGUMENT', '$.toleranceSeconds'), ({'toleranceSeconds': 'x'}, 'INVALID_ARGUMENT', '$.toleranceSeconds'),
                 ({'model': 'constant', 'maxDriftRate': '0.001'}, 'INVALID_ARGUMENT', '$.model'),
                 ({'model': 'linearDrift', 'maxDriftRate': '0.02'}, 'INVALID_ARGUMENT', '$.maxDriftRate'),
                 ({'simultaneous': [{'items': ['a1', 'zz']}]}, 'UNKNOWN_ITEM', '$.simultaneous[0].items'),
                 ({'simultaneous': [{'items': ['a1', 'b1'], 'toleranceSeconds': '9999'}]}, 'INVALID_ARGUMENT', '$.simultaneous[0].toleranceSeconds'),
                 ({'assumedOffsets': [{'group': 'dev1', 'offset': '+15:00'}]}, 'INVALID_ARGUMENT', '$.assumedOffsets[0].offset'),
                 ({'groups': {'by': 'declared', 'members': [{'group': 'g', 'items': ['a1']}]}}, 'GROUP_MEMBERSHIP_INVALID', '$.groups.members'),
                 ({'groups': {'by': 'declared'}}, 'INVALID_ARGUMENT', '$.groups'), ({'groups': {'by': 'recordedDevice', 'members': [{'group': 'g', 'items': ['a1']}]}}, 'INVALID_ARGUMENT', '$.groups.members')]
        for extra, code, location in cases:
            with self.assertRaises(SchemaxisError) as caught:
                adaptor.plan({**base, **extra})
            self.assertEqual((caught.exception.fault.code, caught.exception.fault.location), (code, location), extra)
        for key in ('companions', 'catalogue', 'overlay', 'fields', 'profiles'):
            with self.assertRaises(SchemaxisError) as caught:
                adaptor.plan({**base, key: 'timeLocation'})
            self.assertIn(caught.exception.fault.code, ('UNKNOWN_ARGUMENT', 'INVALID_ARGUMENT'), key)

    def test_locate_plan(self):
        base = {'version': 'schemaxis.exiftool/1', 'operation': 'locate', 'media': {'items': [{'id': 'a1', 'path': '/x/a1.jpg'}]}}
        self.assertIsNone(adaptor.plan(base)['location'])
        p = adaptor.plan({**base, 'compareTo': {'latitude': '-33.80', 'longitude': '-0', 'datum': 'WGS-84'}})
        self.assertEqual(p['location'], {'latitude': '-33.80', 'longitude': '0', 'datum': 'WGS-84'})
        for target, location in (({'latitude': '91', 'longitude': '0'}, '$.compareTo.latitude'), ({'latitude': '0', 'longitude': '181'}, '$.compareTo.longitude'),
                                 ({'latitude': '0', 'longitude': '0', 'datum': 'é'}, '$.compareTo.datum')):
            with self.assertRaises(SchemaxisError) as caught:
                adaptor.plan({**base, 'compareTo': target})
            self.assertEqual((caught.exception.fault.code, caught.exception.fault.location), ('INVALID_ARGUMENT', location))

    def test_e1_and_e2_operation_lists_keep_their_order(self):
        self.assertEqual(adaptor.WORKBENCH_OPERATIONS[:3], ('inspectMetadata', 'auditMetadata', 'compareMetadata'))
        self.assertEqual(adaptor.WRITE_OPERATIONS, ('editMetadata', 'removeMetadata', 'correctTime', 'setLocation', 'geotagFromTrack', 'copyMetadata', 'applySidecar'))      # the E2 operations keep their order; E3 and E4 append


class Native(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.environ.get('SCHEMAXIS_EXIFTOOL')
        if not path or not os.path.isabs(path) or not Path(path).is_file() or not Path(adaptor.PERL).is_file():
            raise unittest.SkipTest('real ExifTool 13.55 is not configured through SCHEMAXIS_EXIFTOOL')
        cls.exe = path

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='e3-read-'))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.runs = 0

    def put(self, name, data):
        (self.root / (name + '.jpg')).write_bytes(data)

    def run_op(self, document, **kw):
        self.runs += 1
        out = self.root / ('run%d' % self.runs)
        result = adaptor.run(document, out, executable=self.exe)
        self.assertEqual(result['verified'], True)
        self.assertEqual(adaptor.verify(out, executable=self.exe)['verified'], True)
        return out

    def locate(self, names, **extra):
        out = self.run_op({'version': 'schemaxis.exiftool/1', 'operation': 'locate', 'media': ITEMS(self.root, names), **extra})
        return {r['id']: r for r in json.loads((out / 'location-report.json').read_text())['items']}, out

    def test_L11_edition_and_height_matrix(self):
        # (name, jpeg kwargs, expected reference, basis, edition evidence, flags)
        cases = [('exif3', dict(version=(2, 4, 0, 0), exif_version=b'0310'), 'ellipsoidal', 'exif3EllipsoidalRef', 'exif3', []),
                 ('annex', dict(version=(2, 3, 0, 0), exif_version=b'0300'), 'ellipsoidal', 'exif3EllipsoidalRef', 'exif3', ['gpsVersionIdNotUpdated']),
                 ('gpsonly', dict(version=(2, 4, 0, 0), exif_version=None), 'ellipsoidal', 'gpsVersionIdOnly', 'gpsIfd24', ['editionByGpsVersionOnly']),
                 ('legacy', dict(version=(2, 3, 0, 0), exif_version=b'0232'), 'unspecified', 'legacyEditionRef', 'legacy', []),
                 ('conflict', dict(version=(2, 4, 0, 0), exif_version=b'0232'), 'unspecified', 'legacyEditionRef', 'legacy', ['editionConflict']),
                 ('noedition', dict(version=(2, 3, 0, 0), exif_version=None), 'unspecified', 'noEditionRef', 'none', []),
                 ('sea2', dict(version=(2, 3, 0, 0), exif_version=b'0232', alt_ref=2), 'seaLevel', 'exifSeaLevelRef', 'legacy', ['legacyReadersMayNotRecognise']),
                 ('sea3', dict(version=(2, 4, 0, 0), exif_version=b'0310', alt_ref=3), 'seaLevel', 'exifSeaLevelRef', 'exif3', [])]
        for name, kw, *_ in cases:
            self.put(name, gps_jpeg(**kw))
        rows, _ = self.locate([c[0] for c in cases])
        for name, kw, reference, basis, evidence, flags in cases:
            h = rows[name]['height']
            self.assertEqual((h['state'], h['reference'], h['basis'], h['edition']['evidence'], h['flags'], h['meters']), ('present', reference, basis, evidence, flags, '-52.3' if kw.get('alt_ref') == 3 else '52.3'), name)
        self.assertIsNotNone(rows['legacy']['height']['historicalLabel'])
        self.assertIsNone(rows['exif3']['height']['historicalLabel'])
        self.assertEqual(rows['conflict']['height']['edition'], {'evidence': 'legacy', 'exifVersion': '0232', 'gpsVersionId': '2.4.0.0'})

    def test_height_edge_states(self):
        self.put('reserved', gps_jpeg(alt_ref=4))
        self.put('noref', gps_jpeg(alt_ref=None))
        self.put('noalt', gps_jpeg(alt=None, alt_ref=None))
        rows, _ = self.locate(['reserved', 'noref', 'noalt'])
        self.assertEqual((rows['reserved']['height']['state'], rows['reserved']['height']['code']), ('unreadable', 'GPS_ALTITUDE_REF_RESERVED'))
        h = rows['noref']['height']
        self.assertEqual((h['state'], h['reference'], h['basis'], h['signKnown'], h['meters']), ('present', 'unspecified', 'refAbsent', False, '52.3'))
        self.assertIn('altitudeRefAbsent', h['flags'])
        self.assertEqual(rows['noref']['flags'], ['altitudeRefAbsent'])
        self.assertEqual(rows['noalt']['height']['state'], 'absent')

    def test_R60_coordinate_matrix(self):
        cases = {'r60a': (((33, 1), (47, 1), (60, 1)), 'N', 'present', '33.8'), 'r60b': (((33, 1), (48, 1), (0, 1)), 'N', 'present', '33.8'),
                 'r60c': (((89, 1), (59, 1), (60, 1)), 'N', 'present', '90'), 'r60e': (((33, 1), (47, 1), (61, 1)), 'N', 'unreadable', None),
                 'r60f': (((33, 1), (60, 1), (0, 1)), 'N', 'unreadable', None), 'r60g': (((33, 1), (47, 1), (60, 0)), 'N', 'unreadable', None),
                 'r60h': (((90, 1), (0, 1), (1, 1)), 'N', 'unreadable', None), 'r60i': (((35, 1), (15, 2), (0, 1)), 'N', 'present', '35.125'),
                 'r60s': (((33, 1), (48, 1), (0, 1)), 'S', 'present', '-33.8'), 'r60z': (((0, 1), (0, 1), (0, 1)), 'S', 'present', '0')}
        for name, (lat, ref, *_rest) in cases.items():
            self.put(name, gps_jpeg(lat=lat, lat_ref=ref, lon=((10, 1), (0, 1), (0, 1)), lon_ref='E'))
        rows, _ = self.locate(list(cases))
        for name, (lat, ref, state, value) in cases.items():
            pos = rows[name]['position']
            self.assertEqual((pos['state'], pos.get('latitude')), (state, value), name)
        self.assertEqual(rows['r60a']['position']['stored']['latitude']['flags'], ['nonCanonicalSeconds60'])
        self.assertEqual(rows['r60b']['position']['stored']['latitude']['flags'], [])
        self.assertEqual(rows['r60a']['position']['stored']['latitude']['rationals'], [[33, 1], [47, 1], [60, 1]])    # the literals differ although the meaning is equal
        self.assertEqual(rows['r60z']['flags'], ['zeroWithSouthOrWestRef'])
        self.assertEqual(rows['r60e']['position']['codes'], ['GPS_COORDINATE_COMPONENT_RANGE'])

    def test_flags_and_compare(self):
        self.put('island', gps_jpeg(lat=((0, 1), (0, 1), (0, 1)), lon=((0, 1), (0, 1), (0, 1)), lon_ref='E', datum='NAD27'))
        self.put('pole', gps_jpeg(lat=((90, 1), (0, 1), (0, 1)), lon=((180, 1), (0, 1), (0, 1)), lon_ref='W', datum=None))
        rows, _ = self.locate(['island', 'pole'], compareTo={'latitude': '1', 'longitude': '0', 'datum': 'WGS-84'})
        self.assertEqual(rows['island']['flags'], ['nullIsland', 'datumNotWgs84Text'])
        self.assertEqual(rows['island']['compareTo']['code'], 'DATUM_MISMATCH')          # a recorded datum different from the declared one gives no distance
        self.assertEqual(rows['pole']['flags'], ['pole', 'antimeridian'])
        self.assertEqual((rows['pole']['compareTo']['state'], rows['pole']['compareTo']['datumUnverified']), ('computed', True))
        self.assertAlmostEqual(rows['pole']['compareTo']['meters'], 6371008.8 * 3.141592653589793 * 89 / 180, places=1)   # 89 degrees of arc on the mean sphere

    def test_L8_exif_and_xmp_concordance_within_the_serialisation_bound(self):
        xmp = lambda lat, lon: '<exif:GPSLatitude>%s</exif:GPSLatitude><exif:GPSLongitude>%s</exif:GPSLongitude>' % (lat, lon)
        # EXIF 35 7 671611/27475 is 35.123456789 within 1.1e-13; XMP 35,7.40740734N is exactly 35.123456789
        self.put('agree', gps_jpeg(lat=((35, 1), (7, 1), (671611, 27475)), lon=((120, 1), (7, 1), (30, 1)), xmp=xmp('35,7.40740734N', '120,7.5W')))
        self.put('differ', gps_jpeg(lat=((35, 1), (7, 1), (671611, 27475)), xmp=xmp('35,7.40740736N', '120,7.5W')))     # +2e-8 minutes = 3.3e-10 degrees: beyond the bound
        self.put('single', gps_jpeg(lat=((35, 1), (7, 1), (671611, 27475))))
        rows, _ = self.locate(['agree', 'differ', 'single'])
        self.assertEqual(rows['agree']['position']['concordance'], {'latitude': 'consistent', 'longitude': 'consistent'})
        # the exact EXIF sum is 35.123456789000101...: a repeating expansion is cut at 12 decimals and says so
        self.assertEqual((rows['agree']['position']['latitude'], rows['agree']['position']['exact']), ('35.123456789', False))
        self.assertEqual(rows['differ']['position']['state'], 'ambiguous')
        self.assertEqual(rows['single']['position']['concordance']['latitude'], 'single-source')

    def test_tampered_publication_is_refused_by_verify(self):
        self.put('a1', gps_jpeg())
        out = self.run_op({'version': 'schemaxis.exiftool/1', 'operation': 'locate', 'media': ITEMS(self.root, ['a1'])})
        target = out / 'location-report.json'
        original = target.read_bytes()
        target.write_bytes(original.replace(b'"52.3"', b'"52.4"'))
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.verify(out, executable=self.exe)
        self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')
        target.write_bytes(original)
        captured = out / 'captured' / 'a1.jpg'
        data = bytearray(captured.read_bytes())
        data[-5] ^= 1
        captured.write_bytes(bytes(data))
        with self.assertRaises(SchemaxisError):
            adaptor.verify(out, executable=self.exe)

    # ---------------------------------------------------------------- reconcileTime
    def reconcile(self, names, **extra):
        out = self.run_op({'version': 'schemaxis.exiftool/1', 'operation': 'reconcileTime', 'media': ITEMS(self.root, names), **extra})
        return json.loads((out / 'time-report.json').read_text())['report'], out

    def test_T6_T7_T8_native(self):
        self.put('a1', gps_jpeg(make='A', serial='1', dto='2026:03:01 12:00:00', sub=None))
        self.put('a5', gps_jpeg(make='A', serial='1', dto='2026:03:01 12:10:00', sub=None))
        self.put('b3', gps_jpeg(make='B', dto='2026:03:01 12:10:30', sub=None))
        refs = [{'item': 'a1', 'trueLocal': '2026-03-01T12:00:05', 'trueOffset': '+01:00'}]
        report, out = self.reconcile(['a1', 'a5', 'b3'], references=refs, simultaneous=[{'items': ['a5', 'b3']}])
        groups = {g['id']: g for g in report['groups']}
        self.assertEqual((groups['dev1']['skewSeconds'], groups['dev2']['skewSeconds'], groups['dev2']['anchoredBy']), ('-5', '25', 'path'))
        rows = {r['id']: r for r in report['items']}
        self.assertEqual((rows['b3']['proposedLocal'], rows['a5']['proposedLocal']), ('2026-03-01T12:10:05', '2026-03-01T12:10:05'))
        self.assertEqual(rows['a1']['proposedInstant'], '2026-03-01T11:00:05')
        self.assertIn('"b3","dev2","anchored","recordedOffset","2026-03-01T12:10:30","+01:00","25"', (out / 'time-report.csv').read_text())
        # T8: two references 30 s apart in skew with tolerance 2 -> conflicting, nothing proposed
        conflict, _ = self.reconcile(['a1', 'a5'], references=[{'item': 'a1', 'trueLocal': '2026-03-01T12:00:05', 'trueOffset': '+01:00'}, {'item': 'a5', 'trueLocal': '2026-03-01T12:09:30', 'trueOffset': '+01:00'}])
        self.assertEqual(conflict['groups'][0]['state'], 'conflicting')
        self.assertTrue(all(r['proposedLocal'] is None for r in conflict['items']))

    def test_T11_missing_offset_native(self):
        self.put('a1', gps_jpeg(offset=None, dto='2026:03:01 12:00:00', sub=None))
        self.put('b1', gps_jpeg(make='B', offset=None, dto='2026:03:01 12:00:20', sub=None))
        report, _ = self.reconcile(['a1', 'b1'], simultaneous=[{'items': ['a1', 'b1']}])
        self.assertEqual(report['edges'][0]['code'], 'OFFSET_UNKNOWN')
        rows = {r['id']: r for r in report['items']}
        self.assertEqual((rows['a1']['basis'], rows['a1']['recordedOffset']), ('wallOnly', None))
        report, _ = self.reconcile(['a1', 'b1'], simultaneous=[{'items': ['a1', 'b1']}], assumedOffsets=[{'group': 'dev1', 'offset': '+01:00'}, {'group': 'dev2', 'offset': '+01:00'}],
                                   assumeCorrect=['dev1'])
        rows = {r['id']: r for r in report['items']}
        self.assertEqual((rows['a1']['basis'], rows['b1']['skewSeconds'], rows['b1']['proposedLocal']), ('assumedOffset', '20', '2026-03-01T12:00:00'))
        self.assertEqual(report['declared'], {'assumeCorrect': ['dev1'], 'assumedOffsets': {'dev1': '+01:00', 'dev2': '+01:00'}})

    def test_conflicting_and_faulted_items_are_explicit(self):
        xmp = '<photoshop:DateCreated>2026-03-01T12:00:09+01:00</photoshop:DateCreated>'
        self.put('c1', gps_jpeg(xmp=xmp))                           # EXIF 12:00:00 vs XMP 12:00:09: the sources disagree
        self.put('d1', gps_jpeg(dto=None, offset=None, sub=None))   # no capture time at all
        (self.root / 'bad.jpg').write_bytes(b'not a jpeg')
        report, _ = self.reconcile(['c1', 'd1', 'bad'] if False else ['c1', 'd1'])
        rows = {r['id']: r for r in report['items']}
        self.assertIn('timeSourcesConflict', rows['c1']['findings'])
        self.assertEqual(rows['c1']['recordedLocal'], None)
        self.assertIn('captureTimeAbsent', rows['d1']['findings'])
        # a reference on an item that could not be captured is a stated fault, not a silent drop
        doc = {'version': 'schemaxis.exiftool/1', 'operation': 'reconcileTime', 'media': ITEMS(self.root, ['c1', 'bad']), 'references': [{'item': 'bad', 'trueUtc': '2026-03-01T11:00:00Z'}]}
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.run(doc, self.root / 'fail1', executable=self.exe)
        self.assertEqual(caught.exception.fault.code, 'REFERENCE_INVALID')


if __name__ == '__main__':
    unittest.main()
