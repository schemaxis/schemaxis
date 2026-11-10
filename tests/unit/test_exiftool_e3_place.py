"""Tests of ``setLocation``: document planning, the per-item location plan (altitude edition rules A1, exact decimal assignment A2, creation of the Exif block,
stale companions and the XMP policy), and (with a real ExifTool 13.55 through SCHEMAXIS_EXIFTOOL) genuine writes read back by the standard-library walkers.

Every expected value is a hand-written literal: native argument lists, stored rationals (the supplement's observed quantisations), XMP literals and edition
layouts. Fixtures are synthetic JPEGs built by ``exiftool_e3_fixtures``.
"""
import copy
from decimal import Decimal as D
from fractions import Fraction
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
from schemaxis.adaptors.exiftool import adaptor, containers, e3place, e3read, e3proofs, edits, jpegwrite, records  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402

V = 'schemaxis.exiftool/1'
POLICIES = {'staleCompanions': 'remove', 'xmp': 'ifPresent', 'createExif': 'allow', 'altitudeNotExpressible': 'refuse', 'removeDirection': False}


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


def plan(data, spec, **policies):
    request = e3place.parse_entry(spec, None, '$.positions[0]')
    return e3place.plan_item(request, records.Payloads(containers.locate(data)), jpegwrite.walk(data), {**POLICIES, **policies}, '$.items[0]')


def refusal(data, spec, **policies):
    try:
        plan(data, spec, **policies)
    except edits.Refusal as error:
        return error.code, error.message
    raise AssertionError('no refusal')


POS = {'latitude': '35.5', 'longitude': '139.25'}
ELLIPSOIDAL = {**POS, 'altitude': {'meters': '52.317', 'reference': 'ellipsoidal'}}


class Planning(unittest.TestCase):
    BASE = doc('setLocation', {'items': [{'id': 'a1', 'path': '/x/a1.jpg'}, {'id': 'b1', 'path': '/x/b1.jpg'}]}, positions=[{'item': 'a1', 'latitude': '35.658581', 'longitude': '139.745433'}])

    def plan(self, **change):
        document = copy.deepcopy(self.BASE)
        document.update(change)
        return adaptor.plan(document)

    def test_defaults_are_explicit_and_numbers_are_echoed_as_text(self):
        p = self.plan(positions=[{'item': 'a1', 'latitude': 35.658581, 'longitude': -0.0, 'altitude': {'meters': '-12.5', 'reference': 'seaLevel'}}])
        self.assertEqual(p['e3']['policies'], {'staleCompanions': 'remove', 'xmp': 'ifPresent', 'createExif': 'allow', 'altitudeNotExpressible': 'refuse', 'removeDirection': False, 'uncorrectedItems': 'copyUnchanged'})
        self.assertEqual(p['e3']['positions'][0]['latitude'], '35.658581')
        self.assertEqual(p['e3']['positions'][0]['longitude'], '-0.0')                  # echoed as authored; the canonical form (zero, east) is decided when the item is planned
        self.assertEqual((p['catalogue']['version'], p['writes']['version']), ('schemaxis.exiftool.fields/3', 'schemaxis.exiftool.writes/3'))

    def test_exact_faults(self):
        good = {'item': 'a1', 'latitude': '35', 'longitude': '139'}
        cases = [(dict(positions=[dict(good, latitude='91')]), 'INVALID_ARGUMENT', '$.positions[0].latitude'),
                 (dict(positions=[dict(good, longitude='180.5')]), 'INVALID_ARGUMENT', '$.positions[0].longitude'),
                 (dict(positions=[dict(good, latitude='35.1234567891')]), 'INVALID_ARGUMENT', '$.positions[0].latitude'),            # more than 9 decimals
                 (dict(positions=[dict(good, latitude='٣٥')]), 'INVALID_ARGUMENT', '$.positions[0].latitude'),            # only ASCII digits
                 (dict(positions=[dict(good, altitude={'meters': '40000.001', 'reference': 'seaLevel'})]), 'INVALID_ARGUMENT', '$.positions[0].altitude.meters'),
                 (dict(positions=[dict(good, altitude={'meters': '1', 'reference': 'geoid'})]), 'INVALID_ARGUMENT', '$.arguments.positions[0].altitude.reference'),
                 (dict(positions=[dict(good, altitude={'meters': '1'})]), 'MISSING_ARGUMENT', '$.arguments.positions[0].altitude.reference'),
                 (dict(positions=[dict(good, datum='WGSé')]), 'INVALID_ARGUMENT', '$.positions[0].datum'),
                 (dict(positions=[dict(good, horizontalErrorMeters='-1')]), 'INVALID_ARGUMENT', '$.positions[0].horizontalErrorMeters'),
                 (dict(positions=[dict(good, gpsUtc='2026-03-01T03:34:60Z')]), 'LEAP_SECOND_UNSUPPORTED', '$.positions[0].gpsUtc'),
                 (dict(positions=[dict(good, gpsUtc='2026-03-01T03:34:56')]), 'INVALID_ARGUMENT', '$.positions[0].gpsUtc'),
                 (dict(positions=[dict(good, item='zz')]), 'UNKNOWN_ITEM', '$.positions[0].item'),
                 (dict(positions=[good, dict(good)]), 'INVALID_ARGUMENT', '$.positions[1].item'),
                 (dict(positions=[good], policies={'xmp': 'sometimes'}), 'INVALID_ARGUMENT', '$.arguments.policies.xmp'),
                 (dict(positions=[good], policies={'removeDirection': 'yes'}), 'INVALID_ARGUMENT', '$.arguments.policies.removeDirection'),
                 (dict(positions=[good], policies={'gpsStamp': 'none'}), 'UNKNOWN_ARGUMENT', '$.arguments.policies')]
        for change, code, at in cases:
            f = fault_of(lambda: self.plan(**change))
            self.assertEqual((f.code, f.location), (code, at), change)
        self.assertEqual(fault_of(lambda: adaptor.plan(doc('setLocation', self.BASE['media']))).code, 'INVALID_ARGUMENT')       # positions or a default are required

    def test_a_default_applies_to_items_without_an_entry_and_a_plan_carries_everything(self):
        p = adaptor.plan(doc('setLocation', self.BASE['media'], **{'default': {'latitude': '46.5', 'longitude': '6.6'}}))
        self.assertEqual(p['e3']['default'], {'latitude': '46.5', 'longitude': '6.6'})
        self.assertEqual(fault_of(lambda: self.plan(plan='/x/p.json')).location, '$.plan')           # positions and a plan together
        for key in ('companions', 'elevation', 'config'):
            self.assertEqual(fault_of(lambda: self.plan(**{key: 'x'})).code, 'UNKNOWN_ARGUMENT', key)


class LocationPlan(unittest.TestCase):
    def test_L1_a_jfif_only_file_gets_a_created_exif_block_with_the_jfif_resolution(self):
        p = plan(fx.jpeg(exif=False, xmp=None), {**POS, 'altitude': {'meters': '12.5', 'reference': 'seaLevel'}, 'datum': 'WGS-84'})
        self.assertEqual(p['args'], ['-n', '-GPS:GPSLatitude=35.5', '-GPS:GPSLatitudeRef=N', '-GPS:GPSLongitude=139.25', '-GPS:GPSLongitudeRef=E', '-GPS:GPSAltitude=12.5', '-GPS:GPSAltitudeRef=2', '-GPS:GPSMapDatum=WGS-84'])
        self.assertEqual(p['creation'], {'jfif': {'units': 0, 'x': 1, 'y': 1}, 'ifd0': {'XResolution': 1, 'YResolution': 1, 'ResolutionUnit': 1, 'YCbCrPositioning': 1}})
        self.assertEqual((p['edition']['evidence'], p['infos']), ('none', ['exifCreated', 'legacyReadersMayNotRecognise']))
        self.assertEqual(p['exifExpect']['version'], {'target': None, 'created': True})      # the native default 2.3.0.0 stands: a sea-level height needs no edition claim
        self.assertEqual(p['declared'], {'exif': True, 'xmp': False, 'iptc': False, 'exifCreate': True})

    def test_L2_the_jfif_density_is_copied(self):
        p = plan(fx.jpeg(exif=False, xmp=None, jfif=(1, 72, 72)), POS)
        self.assertEqual(p['creation']['ifd0'], {'XResolution': 72, 'YResolution': 72, 'ResolutionUnit': 2, 'YCbCrPositioning': 1})

    def test_L20_without_jfif_and_exif_only_ycbcr_positioning_is_created_and_an_ellipsoidal_height_is_a_gps_only_declaration(self):
        p = plan(fx.jpeg(exif=False, xmp=None, jfif=False), ELLIPSOIDAL)
        self.assertEqual(p['args'][:2], ['-n', '-GPS:GPSVersionID=2 4 0 0'])
        self.assertEqual(p['args'][-2:], ['-GPS:GPSAltitude=52.317', '-GPS:GPSAltitudeRef=0'])
        self.assertEqual(p['creation'], {'jfif': None, 'ifd0': {'YCbCrPositioning': 1}})
        self.assertEqual(p['infos'], ['editionByGpsVersionOnly', 'exifCreated', 'legacyReadersMayNotRecognise'])
        self.assertNotIn('ExifIFD', json.dumps(p['args']))

    def test_L14_a_created_gps_ifd_in_an_exif3_file_is_the_2_4_edition(self):
        p = plan(fx.jpeg(exif_version=b'0300'), ELLIPSOIDAL)
        self.assertEqual((p['args'][1], p['args'][-1]), ('-GPS:GPSVersionID=2 4 0 0', '-GPS:GPSAltitudeRef=0'))
        self.assertEqual(p['exifExpect']['version'], {'target': [2, 4, 0, 0], 'created': True})
        self.assertEqual(plan(fx.jpeg(exif_version=b'0300'), POS)['args'][1], '-GPS:GPSVersionID=2 4 0 0')              # without an altitude as well (S4g)

    def test_L22_an_existing_gps_version_is_never_changed(self):
        p = plan(fx.jpeg(exif_version=b'0300', gps={'version': (2, 3, 0, 0), 'lat': ((1, 1), (0, 1), (0, 1)), 'lon': ((2, 1), (0, 1), (0, 1))}), ELLIPSOIDAL)
        self.assertNotIn('GPSVersionID', ' '.join(p['args']))
        self.assertEqual((p['edition']['evidence'], p['infos']), ('exif3', ['gpsVersionIdNotUpdated']))

    def test_L21_and_L15_an_ellipsoidal_height_is_refused_where_the_edition_cannot_express_it(self):
        gps = {'version': (2, 3, 0, 0), 'lat': ((1, 1), (0, 1), (0, 1)), 'lon': ((2, 1), (0, 1), (0, 1)), 'alt': (523, 10), 'alt_ref': 0}
        code, message = refusal(fx.jpeg(exif_version=None, gps=gps), ELLIPSOIDAL)                      # L21: no ExifVersion but an existing GPS IFD below 2.4
        self.assertEqual(code, 'ALTITUDE_REFERENCE_NOT_EXPRESSIBLE')
        code, message = refusal(fx.jpeg(exif_version=b'0232', gps=gps), ELLIPSOIDAL)                   # L15: an explicit 0232 declaration
        self.assertIn('without converting it or promoting its ExifVersion', message)
        omitted = plan(fx.jpeg(exif_version=b'0232', gps=gps), ELLIPSOIDAL, altitudeNotExpressible='omitAltitude')
        self.assertEqual(omitted['args'], ['-n', '-GPS:GPSLatitude=35.5', '-GPS:GPSLatitudeRef=N', '-GPS:GPSLongitude=139.25', '-GPS:GPSLongitudeRef=E', '-GPS:GPSAltitudeRef=', '-GPS:GPSAltitude='])      # removed in tag order: reference (5) then altitude (6)
        self.assertEqual([(l['key'], l['before'], l['reason']) for l in omitted['losses']], [('GPS:GPSAltitudeRef', '0', 'altitudeOmitted'), ('GPS:GPSAltitude', '523/10', 'altitudeOmitted')])
        self.assertIn('altitudeOmitted', omitted['infos'])

    def test_L16_a_sea_level_height_is_expressible_in_any_edition_and_never_touches_the_version(self):
        gps = {'version': (2, 3, 0, 0), 'lat': ((1, 1), (0, 1), (0, 1)), 'lon': ((2, 1), (0, 1), (0, 1)), 'alt': (523, 10), 'alt_ref': 0}
        p = plan(fx.jpeg(exif_version=b'0232', gps=gps), {**POS, 'altitude': {'meters': '-430.5', 'reference': 'seaLevel'}})
        self.assertEqual(p['args'][5:7], ['-GPS:GPSAltitude=430.5', '-GPS:GPSAltitudeRef=3'])
        self.assertNotIn('GPSVersionID', ' '.join(p['args']))
        self.assertIn('legacyReadersMayNotRecognise', p['infos'])

    def test_E3R3_unresolved_edition_evidence_is_not_an_edition(self):
        gps = {'version': (2, 4, 0, 0), 'lat': ((1, 1), (0, 1), (0, 1)), 'lon': ((2, 1), (0, 1), (0, 1))}
        twice = fx.jpeg(exif_version=b'0232', exif_extra=[fx.a.undefined_entry(0x9000, b'0300')], gps=gps)        # two ExifVersion entries: which one declares the edition?
        code, message = refusal(twice, ELLIPSOIDAL)
        self.assertEqual(code, 'ALTITUDE_REFERENCE_NOT_EXPRESSIBLE')
        self.assertIn('cannot be resolved', message)
        self.assertEqual(plan(twice, {**POS, 'altitude': {'meters': '1', 'reference': 'seaLevel'}})['edition']['evidence'], 'unresolved')       # sea level needs no edition claim
        malformed = fx.jpeg(exif_version=b'03x0', gps=gps)
        self.assertEqual(refusal(malformed, ELLIPSOIDAL)[0], 'ALTITUDE_REFERENCE_NOT_EXPRESSIBLE')
        self.assertEqual(e3read.edition(records.Payloads(containers.locate(malformed)))[0], 'unresolved')

    def test_a_damaged_ifd_is_never_rewritten_around(self):
        data = fx.jpeg(exif_version=b'0232')
        payloads = records.Payloads(containers.locate(data))
        payloads.exif[1]['ifds']['ExifIFD'] = ('error', 'INVALID_EXIF_STRUCTURE', 'damaged')
        request = e3place.parse_entry(POS, None, '$')
        with self.assertRaises(edits.Refusal) as caught:
            e3place.plan_item(request, payloads, jpegwrite.walk(data), POLICIES, '$.items[0]')
        self.assertEqual((caught.exception.code, caught.exception.observed['ifd']), ('EDIT_DESTINATION_UNREADABLE', 'ExifIFD'))

    def test_L4_L5_L6_signs_zero_poles_and_the_antimeridian(self):
        p = plan(fx.jpeg(exif=False), {'latitude': '-33.8', 'longitude': '-70.6', 'altitude': {'meters': '-12.5', 'reference': 'seaLevel'}})
        self.assertEqual(p['args'][1:7], ['-GPS:GPSLatitude=33.8', '-GPS:GPSLatitudeRef=S', '-GPS:GPSLongitude=70.6', '-GPS:GPSLongitudeRef=W', '-GPS:GPSAltitude=12.5', '-GPS:GPSAltitudeRef=3'])
        z = plan(fx.jpeg(exif=False), {'latitude': '-0.0', 'longitude': '-0'})
        self.assertEqual(z['args'], ['-n', '-GPS:GPSLatitude=0', '-GPS:GPSLatitudeRef=N', '-GPS:GPSLongitude=0', '-GPS:GPSLongitudeRef=E'])       # a zero never carries a south or west reference
        self.assertEqual(z['infos'], ['exifCreated', 'signedZeroNormalised'])
        edge = plan(fx.jpeg(exif=False), {'latitude': '90', 'longitude': '-180'})
        self.assertEqual(edge['args'][1:5], ['-GPS:GPSLatitude=90', '-GPS:GPSLatitudeRef=N', '-GPS:GPSLongitude=180', '-GPS:GPSLongitudeRef=W'])
        self.assertEqual(plan(fx.jpeg(exif=False), {'latitude': '-90', 'longitude': '+180'})['args'][1:5], ['-GPS:GPSLatitude=90', '-GPS:GPSLatitudeRef=S', '-GPS:GPSLongitude=180', '-GPS:GPSLongitudeRef=E'])

    def test_L13_gps_time_stamps_keep_their_exact_fraction(self):
        p = plan(fx.jpeg(exif=False), {**POS, 'gpsUtc': '2026-03-01T03:34:56.25Z', 'horizontalErrorMeters': '5', 'datum': 'WGS-84'})
        self.assertEqual(p['args'][5:], ['-GPS:GPSMapDatum=WGS-84', '-GPS:GPSHPositioningError=5', '-GPS:GPSDateStamp=2026:03:01', '-GPS:GPSTimeStamp=03:34:56.25'])

    def stale_fixture(self, **kw):
        gps = {'version': (2, 3, 0, 0), 'lat': ((12, 1), (34, 1), (5, 1)), 'lon': ((45, 1), (40, 1), (0, 1)), 'alt': (100, 1), 'alt_ref': 0, 'datum': 'NAD27', 'error': (7, 1),
               'date': '2020:01:02', 'time': ((1, 1), (2, 1), (3, 1)), 'direction': (90, 1)}
        return fx.jpeg(exif_version=b'0300', gps=gps, **kw)

    def test_L3_stale_companions_are_removed_and_the_camera_direction_is_kept(self):
        p = plan(self.stale_fixture(), POS)
        self.assertEqual(p['args'][1:5], ['-GPS:GPSLatitude=35.5', '-GPS:GPSLatitudeRef=N', '-GPS:GPSLongitude=139.25', '-GPS:GPSLongitudeRef=E'])
        # removed in tag order: altitude reference (5), altitude (6), time stamp (7), datum (0x12), date stamp (0x1D), horizontal error (0x1F)
        self.assertEqual(p['args'][5:], ['-GPS:GPSAltitudeRef=', '-GPS:GPSAltitude=', '-GPS:GPSTimeStamp=', '-GPS:GPSMapDatum=', '-GPS:GPSDateStamp=', '-GPS:GPSHPositioningError='])
        self.assertEqual(sorted(l['key'] for l in p['losses']), ['GPS:GPSAltitude', 'GPS:GPSAltitudeRef', 'GPS:GPSDateStamp', 'GPS:GPSHPositioningError', 'GPS:GPSMapDatum', 'GPS:GPSTimeStamp'])
        self.assertNotIn('GPSImgDirection', ' '.join(p['args']))                          # the direction is the camera's, not the fix's
        self.assertEqual({l['key']: l['before'] for l in p['losses']}['GPS:GPSTimeStamp'], '1/1 2/1 3/1')
        gone = plan(self.stale_fixture(), POS, removeDirection=True)
        self.assertIn('-GPS:GPSImgDirection=', gone['args'])

    def test_staleCompanions_keep_reports_what_stays(self):
        p = plan(self.stale_fixture(), POS, staleCompanions='keep')
        self.assertEqual(p['args'], ['-n', '-GPS:GPSLatitude=35.5', '-GPS:GPSLatitudeRef=N', '-GPS:GPSLongitude=139.25', '-GPS:GPSLongitudeRef=E'])
        self.assertIn('staleKept', p['infos'])
        self.assertTrue(all(l['treatment'] == 'kept' for l in p['losses']))

    def test_the_xmp_policy(self):
        xmp = fx.xmp_properties(lat='33,47.9999N', lon='120,7.5W', altitude='523/10', altitude_ref='0', datum='NAD27')
        with_xmp = fx.jpeg(exif_version=b'0300', xmp=xmp)
        none = fx.jpeg(exif_version=b'0300', xmp=fx.xmp_properties(captured='2026-03-01T12:00:00+01:00'))
        self.assertNotIn('XMP', ' '.join(plan(none, POS)['args']))                         # ifPresent: no exif:GPS* property, no XMP write
        written = plan(with_xmp, {'latitude': '-33.8', 'longitude': '-70.6', 'datum': 'WGS-84'})
        self.assertEqual([a for a in written['args'] if a.startswith('-XMP')], ['-XMP-exif:GPSLatitude=-33.8', '-XMP-exif:GPSLongitude=-70.6', '-XMP-exif:GPSMapDatum=WGS-84', '-XMP-exif:GPSAltitude=', '-XMP-exif:GPSAltitudeRef='])
        self.assertEqual(written['xmpExpect'], {'latitude': D('-33.8'), 'longitude': D('-70.6'), 'datum': 'WGS-84', 'removed': ['exif:GPSAltitude', 'exif:GPSAltitudeRef']})
        always = plan(none, POS, xmp='always')
        self.assertEqual([a for a in always['args'] if a.startswith('-XMP')], ['-XMP-exif:GPSLatitude=35.5', '-XMP-exif:GPSLongitude=139.25'])
        removed = plan(with_xmp, POS, xmp='remove')
        self.assertEqual([a for a in removed['args'] if a.startswith('-XMP')], ['-XMP-exif:GPSMapDatum=', '-XMP-exif:GPSAltitude=', '-XMP-exif:GPSAltitudeRef=', '-XMP-exif:GPSLatitude=', '-XMP-exif:GPSLongitude='])

    def test_L17_an_xmp_altitude_cannot_be_kept_next_to_a_new_altitude_and_exifex_cannot_be_rewritten(self):
        xmp = fx.xmp_properties(lat='33,47.9999N', lon='120,7.5W', altitude='523/10', altitude_ref='0')
        data = fx.jpeg(exif_version=b'0300', xmp=xmp)
        p = plan(data, {**POS, 'altitude': {'meters': '12.5', 'reference': 'seaLevel'}}, staleCompanions='keep')
        self.assertEqual([l['reason'] for l in p['losses'] if l['key'].startswith('XMP')], ['xmpAltitudeNotExpressible', 'xmpAltitudeNotExpressible'])
        self.assertIn('xmpAltitudeNotExpressible', p['infos'])
        exifex = fx.jpeg(exif_version=b'0300', xmp=fx.xmp_properties(lat='33,47.9999N', lon='120,7.5W', extra='<exifEX:GPSAltitudeRef xmlns:exifEX="http://cipa.jp/exif/1.0/">1</exifEX:GPSAltitudeRef>'))
        self.assertEqual(refusal(exifex, {**POS, 'altitude': {'meters': '12.5', 'reference': 'seaLevel'}})[0], 'ALTITUDE_REFERENCE_NOT_EXPRESSIBLE')
        self.assertIn('-GPS:GPSLatitude=35.5', plan(exifex, POS)['args'])               # a position alone does not touch the altitude properties

    def test_L10_creation_of_an_exif_block_can_be_refused_and_xmp_only_is_the_alternative(self):
        data = fx.jpeg(exif=False)
        self.assertEqual(refusal(data, POS, createExif='refuse')[0], 'EXIF_CREATION_REFUSED')
        p = plan(data, POS, createExif='refuse', xmp='always')
        self.assertEqual((p['args'], p['exifActive'], p['infos']), (['-n', '-XMP-exif:GPSLatitude=35.5', '-XMP-exif:GPSLongitude=139.25'], False, ['exifNotCreated']))
        self.assertEqual(p['declared'], {'exif': False, 'xmp': True, 'iptc': False, 'exifCreate': False})
        alt = plan(data, ELLIPSOIDAL, createExif='refuse', xmp='always')
        self.assertEqual([l['reason'] for l in alt['losses']], ['xmpAltitudeNotExpressible'])      # an XMP-only item cannot carry the altitude: declared, not silent

    def test_a_repeated_gps_tag_or_xmp_property_is_not_replaced_blindly(self):
        twice = fx.jpeg(exif_version=b'0300', gps={'version': (2, 3, 0, 0), 'lat': ((1, 1), (0, 1), (0, 1)), 'lon': ((2, 1), (0, 1), (0, 1)), 'alt': (1, 1), 'alt_ref': 0, 'extra': [fx.a.rational_entry(fx.O, 6, (2, 1))]})
        self.assertEqual(refusal(twice, POS)[0], 'EDIT_DESTINATION_UNREADABLE')
        dup_lat = fx.jpeg(exif_version=b'0300', gps={'version': (2, 3, 0, 0), 'lat': ((1, 1), (0, 1), (0, 1)), 'lon': ((2, 1), (0, 1), (0, 1)), 'extra': [fx.a.rational_entry(fx.O, 2, (3, 1), (0, 1), (0, 1))]})
        self.assertEqual(refusal(dup_lat, POS)[0], 'EDIT_DESTINATION_UNREADABLE')
        xmp_twice = fx.jpeg(exif_version=b'0300', xmp=fx.xmp_properties(lat='33,47.9999N', lon='120,7.5W') + '<exif:GPSLatitude>10,0.0N</exif:GPSLatitude>')
        self.assertEqual(refusal(xmp_twice, POS)[0], 'EDIT_DESTINATION_UNREADABLE')


GPS_FULL = {'version': (2, 3, 0, 0), 'lat': ((12, 1), (34, 1), (5, 1)), 'lon': ((45, 1), (40, 1), (0, 1)), 'alt': (100, 1), 'alt_ref': 0, 'datum': 'NAD27', 'error': (7, 1),
            'date': '2020:01:02', 'time': ((1, 1), (2, 1), (3, 1)), 'direction': (90, 1)}


class NativeBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.environ.get('SCHEMAXIS_EXIFTOOL')
        if not path or not os.path.isabs(path) or not Path(path).is_file() or not Path(adaptor.PERL).is_file():
            raise unittest.SkipTest('real ExifTool 13.55 is not configured through SCHEMAXIS_EXIFTOOL')
        cls.exe = path

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='e3-place-'))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.runs = 0

    def put(self, name, data):
        (self.root / (name + '.jpg')).write_bytes(data)

    def run_op(self, document):
        self.runs += 1
        out = self.root / ('run%d' % self.runs)
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

    def locate(self, data):
        payloads = records.Payloads(containers.locate(data))
        return e3read.height(payloads)

    def position(self, data):
        return {a: (fx.exif_rationals(data, 'GPS', t), fx.exif_ascii(data, 'GPS', r)) for a, t, r in (('lat', 2, 1), ('lon', 4, 3))}


class Native(NativeBase):
    def put_positions(self, names_to_specs, **extra):
        return self.run_op(doc('setLocation', items(self.root, list(names_to_specs)), positions=[{'item': n, **s} for n, s in names_to_specs.items()], **extra))

    def test_L1_L2_a_jfif_only_file_gets_an_exif_block_with_the_jfif_resolution(self):
        self.put('plain', fx.jpeg(exif=False, xmp=None))
        self.put('dpi', fx.jpeg(exif=False, xmp=None, jfif=(1, 72, 72)))
        spec = {**POS, 'altitude': {'meters': '12.5', 'reference': 'seaLevel'}, 'datum': 'WGS-84'}
        out = self.put_positions({'plain': spec, 'dpi': spec})
        plain, dpi = self.photo(out, 'plain'), self.photo(out, 'dpi')
        self.assertEqual(fx.exif_tags(plain, 'IFD0'), [0x011A, 0x011B, 0x0128, 0x0213, 0x8825])         # exactly the creation values and the GPS pointer, nothing else
        self.assertEqual((fx.exif_rationals(plain, 'IFD0', 0x011A), fx.exif_rationals(plain, 'IFD0', 0x011B), fx.exif_bytes(plain, 'IFD0', 0x0128), fx.exif_bytes(plain, 'IFD0', 0x0213)),
                         ([(1, 1)], [(1, 1)], [1], [1]))
        self.assertEqual((fx.exif_rationals(dpi, 'IFD0', 0x011A), fx.exif_bytes(dpi, 'IFD0', 0x0128)), ([(72, 1)], [2]))
        self.assertEqual(fx.exif_tags(plain, 'ExifIFD'), [])                                              # no ExifIFD and so no ExifVersion
        self.assertEqual(fx.exif_bytes(plain, 'GPS', 0), [2, 3, 0, 0])                                    # the native default of a created GPS IFD
        self.assertEqual(self.position(plain), {'lat': ([(35, 1), (30, 1), (0, 1)], 'N'), 'lon': ([(139, 1), (15, 1), (0, 1)], 'E')})
        self.assertEqual((fx.exif_bytes(plain, 'GPS', 5), fx.exif_rationals(plain, 'GPS', 6), fx.exif_ascii(plain, 'GPS', 0x12)), ([2], [(25, 2)], 'WGS-84'))
        height = self.locate(plain)
        self.assertEqual((height['reference'], height['basis'], height['flags']), ('seaLevel', 'exifSeaLevelRef', ['legacyReadersMayNotRecognise']))
        self.assertEqual(self.row(out, 'plain')['readback']['latitude']['storedDegrees'], '35.5')

    def test_L20_and_L20b_an_ellipsoidal_height_in_a_file_with_no_exif_is_a_gps_only_2_4_declaration(self):
        self.put('bare', fx.jpeg(exif=False, xmp=None, jfif=False))
        self.put('jfif', fx.jpeg(exif=False, xmp=None))
        spec = {**POS, 'altitude': {'meters': '52.317', 'reference': 'ellipsoidal'}}
        out = self.put_positions({'bare': spec, 'jfif': spec})
        bare, jfif = self.photo(out, 'bare'), self.photo(out, 'jfif')
        self.assertEqual(fx.exif_tags(bare, 'IFD0'), [0x0213, 0x8825])                                    # only YCbCrPositioning and the GPS pointer
        self.assertEqual(fx.exif_tags(jfif, 'IFD0'), [0x011A, 0x011B, 0x0128, 0x0213, 0x8825])
        for data in (bare, jfif):
            self.assertEqual(fx.exif_tags(data, 'ExifIFD'), [])                                          # M-V2 territory: no ExifIFD and no ExifVersion was created
            self.assertEqual((fx.exif_bytes(data, 'GPS', 0), fx.exif_bytes(data, 'GPS', 5), fx.exif_rationals(data, 'GPS', 6)), ([2, 4, 0, 0], [0], [(52317, 1000)]))
            height = self.locate(data)
            self.assertEqual((height['reference'], height['basis'], height['edition']['evidence']), ('ellipsoidal', 'gpsVersionIdOnly', 'gpsIfd24'))
        self.assertEqual(set(self.row(out, 'bare')['infos']), {'editionByGpsVersionOnly', 'exifCreated', 'legacyReadersMayNotRecognise'})

    def test_L14_L22_L16_L15_L21_the_edition_matrix_of_the_altitude_reference(self):
        gps = lambda ref: {'version': (2, 3, 0, 0), 'lat': ((1, 1), (0, 1), (0, 1)), 'lon': ((2, 1), (0, 1), (0, 1)), 'alt': (523, 10), 'alt_ref': ref}
        self.put('l14', fx.jpeg(exif_version=b'0300'))
        self.put('l22', fx.jpeg(exif_version=b'0300', gps=gps(0)))
        self.put('l16', fx.jpeg(exif_version=b'0232', gps=gps(0)))
        self.put('l15', fx.jpeg(exif_version=b'0232', gps=gps(0)))
        self.put('l21', fx.jpeg(exif_version=None, gps=gps(0)))
        ell = {**POS, 'altitude': {'meters': '52.317', 'reference': 'ellipsoidal'}}
        out = self.put_positions({'l14': ell, 'l22': ell, 'l16': {**POS, 'altitude': {'meters': '-430.5', 'reference': 'seaLevel'}}, 'l15': ell, 'l21': ell})
        l14, l22, l16 = (self.photo(out, n) for n in ('l14', 'l22', 'l16'))
        self.assertEqual((fx.exif_bytes(l14, 'GPS', 0), fx.exif_bytes(l14, 'GPS', 5), fx.exif_rationals(l14, 'GPS', 6)), ([2, 4, 0, 0], [0], [(52317, 1000)]))      # L14: created GPS IFD, 2.4 target
        self.assertEqual((fx.exif_bytes(l22, 'GPS', 0), fx.exif_bytes(l22, 'GPS', 5)), ([2, 3, 0, 0], [0]))        # L22: the existing GPSVersionID stays
        self.assertEqual((fx.exif_bytes(l16, 'GPS', 0), fx.exif_bytes(l16, 'GPS', 5), fx.exif_rationals(l16, 'GPS', 6), fx.exif_ascii(l16, 'ExifIFD', 0x9000)), ([2, 3, 0, 0], [3], [(861, 2)], '0232'))
        self.assertEqual([self.outcome(out, n)['fault']['code'] for n in ('l15', 'l21')], ['ALTITUDE_REFERENCE_NOT_EXPRESSIBLE'] * 2)
        self.assertEqual(self.outcome(out, 'l15')['fault']['observed']['edition'], 'legacy')
        omitted = self.run_op(doc('setLocation', items(self.root, ['l15', 'l21']), positions=[{'item': 'l15', **ell}, {'item': 'l21', **ell}], policies={'altitudeNotExpressible': 'omitAltitude'}))
        for name in ('l15', 'l21'):
            data = self.photo(omitted, name)
            self.assertEqual((fx.exif_rationals(data, 'GPS', 6), fx.exif_bytes(data, 'GPS', 5), fx.exif_bytes(data, 'GPS', 0)), (None, None, [2, 3, 0, 0]))
            self.assertIn('altitudeOmitted', self.row(omitted, name)['infos'])
        self.assertEqual(fx.exif_ascii(self.photo(omitted, 'l15'), 'ExifIFD', 0x9000), '0232')              # never promoted or demoted

    def test_E3R3_unresolved_edition_evidence_refuses_an_ellipsoidal_height_natively(self):
        gps = {'version': (2, 4, 0, 0), 'lat': ((1, 1), (0, 1), (0, 1)), 'lon': ((2, 1), (0, 1), (0, 1)), 'alt': (523, 10), 'alt_ref': 0}
        self.put('twice', fx.jpeg(exif_version=b'0232', exif_extra=[fx.a.undefined_entry(0x9000, b'0300')], gps=gps))
        self.put('good', fx.jpeg(exif_version=b'0300', gps=gps))
        ell = {**POS, 'altitude': {'meters': '52.317', 'reference': 'ellipsoidal'}}
        out = self.put_positions({'twice': ell, 'good': ell})
        self.assertEqual(self.outcome(out, 'twice')['fault']['code'], 'ALTITUDE_REFERENCE_NOT_EXPRESSIBLE')
        self.assertEqual(self.outcome(out, 'twice')['fault']['observed']['edition'], 'unresolved')
        self.assertEqual(fx.exif_rationals(self.photo(out, 'good'), 'GPS', 6), [(52317, 1000)])

    def test_L3_stale_companions_are_removed_the_direction_kept_and_the_version_untouched(self):
        self.put('s', fx.jpeg(exif_version=b'0300', gps=GPS_FULL))
        out = self.put_positions({'s': POS})
        data = self.photo(out, 's')
        self.assertEqual(fx.exif_tags(data, 'GPS'), [0x0000, 0x0001, 0x0002, 0x0003, 0x0004, 0x0010, 0x0011])
        self.assertEqual((fx.exif_bytes(data, 'GPS', 0), fx.exif_rationals(data, 'GPS', 0x11), fx.exif_ascii(data, 'GPS', 0x10)), ([2, 3, 0, 0], [(90, 1)], 'T'))
        kept = self.run_op(doc('setLocation', items(self.root, ['s']), positions=[{'item': 's', **POS}], policies={'staleCompanions': 'keep'}))
        data = self.photo(kept, 's')
        self.assertEqual((fx.exif_rationals(data, 'GPS', 6), fx.exif_ascii(data, 'GPS', 0x12), fx.exif_ascii(data, 'GPS', 0x1D), fx.exif_rationals(data, 'GPS', 7), fx.exif_rationals(data, 'GPS', 0x1F)),
                         ([(100, 1)], 'NAD27', '2020:01:02', [(1, 1), (2, 1), (3, 1)], [(7, 1)]))
        self.assertIn('staleKept', self.row(kept, 's')['infos'])
        gone = self.run_op(doc('setLocation', items(self.root, ['s']), positions=[{'item': 's', **POS}], policies={'removeDirection': True}))
        self.assertEqual(fx.exif_tags(self.photo(gone, 's'), 'GPS'), [0x0000, 0x0001, 0x0002, 0x0003, 0x0004])

    def test_L4_L5_L6_signs_zero_poles_and_the_antimeridian(self):
        for name in ('neg', 'zero', 'poleN', 'poleS'):
            self.put(name, fx.jpeg(exif=False))
        out = self.put_positions({'neg': {'latitude': '-33.8', 'longitude': '-70.6', 'altitude': {'meters': '-12.5', 'reference': 'seaLevel'}}, 'zero': {'latitude': '-0.0', 'longitude': '-0'},
                                  'poleN': {'latitude': '90', 'longitude': '-180'}, 'poleS': {'latitude': '-90', 'longitude': '180'}})
        neg = self.photo(out, 'neg')
        # The oracle is the exact sum of the stored rationals. ExifTool computes minutes in binary floating point, so it stores 33.8 as 33 47 60 and 70.6 as 70 35 60:
        # exact, non-canonical forms (seconds of exactly 60) that the A3 reader sums and flags rather than refuses.
        position = self.position(neg)
        self.assertEqual((position['lat'][1], position['lon'][1]), ('S', 'W'))
        total = lambda triple: sum(Fraction(n, d) / div for (n, d), div in zip(triple, (1, 60, 3600)))
        self.assertEqual((total(position['lat'][0]), total(position['lon'][0])), (Fraction('33.8'), Fraction('70.6')))
        self.assertEqual((position['lat'][0], position['lon'][0]), ([(33, 1), (47, 1), (60, 1)], [(70, 1), (35, 1), (60, 1)]))      # the native forms observed with 13.55
        self.assertEqual((fx.exif_bytes(neg, 'GPS', 5), fx.exif_rationals(neg, 'GPS', 6)), ([3], [(25, 2)]))
        zero = self.photo(out, 'zero')
        self.assertEqual(self.position(zero), {'lat': ([(0, 1), (0, 1), (0, 1)], 'N'), 'lon': ([(0, 1), (0, 1), (0, 1)], 'E')})
        self.assertIn('signedZeroNormalised', self.row(out, 'zero')['infos'])
        self.assertEqual(self.position(self.photo(out, 'poleN')), {'lat': ([(90, 1), (0, 1), (0, 1)], 'N'), 'lon': ([(180, 1), (0, 1), (0, 1)], 'W')})
        self.assertEqual(self.position(self.photo(out, 'poleS')), {'lat': ([(90, 1), (0, 1), (0, 1)], 'S'), 'lon': ([(180, 1), (0, 1), (0, 1)], 'E')})

    def test_L7_the_stored_rationals_are_the_native_quantisation_published_exactly_and_within_the_bound(self):
        for name in ('q1', 'q2', 'q3'):
            self.put(name, fx.jpeg(exif_version=b'0300'))
        out = self.put_positions({'q1': {'latitude': '35.123456789', 'longitude': '179.999999', 'altitude': {'meters': '1234.567', 'reference': 'seaLevel'}},
                                  'q2': {'latitude': '9.87654321', 'longitude': '33.8'}, 'q3': {'latitude': '0.000000001', 'longitude': '-0.000000005'}})
        q1, q2, q3 = (self.photo(out, n) for n in ('q1', 'q2', 'q3'))
        self.assertEqual(self.position(q1)['lat'][0], [(35, 1), (7, 1), (671611, 27475)])
        self.assertEqual(self.position(q1)['lon'][0], [(179, 1), (59, 1), (83335, 1389)])
        self.assertEqual(fx.exif_rationals(q1, 'GPS', 6), [(119753, 97)])                                  # 1234.567 m is stored as 119753/97 (+1.03e-5 m): within 1e-8 relative
        self.assertEqual(self.position(q2), {'lat': ([(9, 1), (52, 1), (8888889, 250000)], 'N'), 'lon': ([(33, 1), (47, 1), (60, 1)], 'E')})
        self.assertEqual(self.position(q3), {'lat': ([(0, 1), (0, 1), (9, 2500000)], 'N'), 'lon': ([(0, 1), (0, 1), (9, 500000)], 'W')})      # 1e-9 deg = 9/2500000 s and 5e-9 deg = 9/500000 s: near zero is never erased
        published = self.row(out, 'q1')['readback']
        self.assertEqual((published['latitude']['stored'], published['latitude']['bound'], published['latitude']['storedDegreesExact']), ([[35, 1], [7, 1], [671611, 27475]], '2e-10', False))
        self.assertEqual(published['latitude']['storedDegrees'], '35.123456789')                           # cut at 12 decimals; the exact sum is 35.123456789000101...
        self.assertEqual(published['height']['stored'], [119753, 97])

    def test_L7b_and_L7c_xmp_coordinates_are_exact_decimal_minutes(self):
        self.put('x1', fx.jpeg(exif_version=b'0300'))
        self.put('x2', fx.jpeg(exif_version=b'0300'))
        out = self.put_positions({'x1': {'latitude': '35.123456789', 'longitude': '-179.999999999'}, 'x2': {'latitude': '33.8', 'longitude': '-70.6'}}, policies={'xmp': 'always'})
        x1, x2 = self.photo(out, 'x1'), self.photo(out, 'x2')
        self.assertEqual((fx.xmp_value(x1, 'exif:GPSLatitude'), fx.xmp_value(x1, 'exif:GPSLongitude')), ('35,7.40740734N', '179,59.99999994W'))
        self.assertEqual((fx.xmp_value(x2, 'exif:GPSLatitude'), fx.xmp_value(x2, 'exif:GPSLongitude')), ('33,48.0N', '70,36.0W'))

    def test_L8_exif_and_xmp_that_disagreed_before_agree_exactly_after(self):
        xmp = fx.xmp_properties(lat='20,0.0N', lon='120,7.5W')                                            # EXIF says 12 deg 34' 5"; XMP says 20 deg
        self.put('d', fx.jpeg(exif_version=b'0300', gps=GPS_FULL, xmp=xmp))
        report = self.run_op(doc('locate', items(self.root, ['d'])))
        self.assertEqual(json.loads((report / 'location-report.json').read_text())['items'][0]['position']['state'], 'ambiguous')
        out = self.put_positions({'d': POS})
        data = self.photo(out, 'd')
        self.assertEqual((fx.exif_rationals(data, 'GPS', 2), fx.xmp_value(data, 'exif:GPSLatitude'), fx.xmp_value(data, 'exif:GPSLongitude')), ([(35, 1), (30, 1), (0, 1)], '35,30.0N', '139,15.0E'))
        after = self.run_op(doc('locate', {'items': [{'id': 'd', 'path': str(out / 'photos' / 'd.jpg')}]}))
        self.assertEqual(json.loads((after / 'location-report.json').read_text())['items'][0]['position']['concordance'], {'latitude': 'consistent', 'longitude': 'consistent'})

    def test_L9_L10_xmp_policies_and_the_refusal_to_create_exif(self):
        xmp = fx.xmp_properties(lat='20,0.0N', lon='120,7.5W', datum='NAD27')
        self.put('has', fx.jpeg(exif_version=b'0300', xmp=xmp))
        self.put('bare', fx.jpeg(exif=False))
        self.put('good', fx.jpeg(exif_version=b'0300'))
        removed = self.put_positions({'has': POS}, policies={'xmp': 'remove'})
        self.assertEqual([fx.xmp_value(self.photo(removed, 'has'), p) for p in ('exif:GPSLatitude', 'exif:GPSLongitude', 'exif:GPSMapDatum')], [None, None, None])
        self.assertEqual(fx.exif_rationals(self.photo(removed, 'has'), 'GPS', 2), [(35, 1), (30, 1), (0, 1)])
        out = self.put_positions({'bare': POS, 'good': POS}, policies={'createExif': 'refuse'})
        self.assertEqual(self.outcome(out, 'bare')['fault']['code'], 'EXIF_CREATION_REFUSED')
        only = self.put_positions({'bare': POS, 'good': POS}, policies={'createExif': 'refuse', 'xmp': 'always'})
        data = self.photo(only, 'bare')
        self.assertEqual(containers.locate(data)['exif'], [])                                              # XMP only: no Exif block was created
        self.assertEqual((fx.xmp_value(data, 'exif:GPSLatitude'), fx.xmp_value(data, 'exif:GPSLongitude')), ('35,30.0N', '139,15.0E'))

    def test_L13_a_fractional_gps_time_stamp_is_exact(self):
        self.put('t', fx.jpeg(exif_version=b'0300'))
        out = self.put_positions({'t': {**POS, 'gpsUtc': '2026-03-01T03:34:56.25Z', 'horizontalErrorMeters': '5', 'datum': 'WGS-84'}})
        data = self.photo(out, 't')
        (h, hd), (m, md), (s, sd) = fx.exif_rationals(data, 'GPS', 7)
        self.assertEqual((h / hd, m / md, s / sd), (3, 34, 56.25))
        self.assertEqual((fx.exif_ascii(data, 'GPS', 0x1D), fx.exif_rationals(data, 'GPS', 0x1F), fx.exif_ascii(data, 'GPS', 0x12)), ('2026:03:01', [(5, 1)], 'WGS-84'))

    def test_L17_an_xmp_altitude_is_removed_and_the_xmp_position_rewritten_exactly(self):
        xmp = fx.xmp_properties(lat='33,47.9999N', lon='120,7.5W', altitude='523/10', altitude_ref='0')
        self.put('x', fx.jpeg(exif_version=b'0300', gps={'version': (2, 3, 0, 0), 'lat': ((1, 1), (0, 1), (0, 1)), 'lon': ((2, 1), (0, 1), (0, 1)), 'alt': (523, 10), 'alt_ref': 0}, xmp=xmp))
        out = self.put_positions({'x': {**POS, 'altitude': {'meters': '12.5', 'reference': 'seaLevel'}}}, policies={'staleCompanions': 'keep'})
        data = self.photo(out, 'x')
        self.assertEqual((fx.xmp_value(data, 'exif:GPSAltitude'), fx.xmp_value(data, 'exif:GPSAltitudeRef'), fx.xmp_value(data, 'exif:GPSLatitude')), (None, None, '35,30.0N'))
        self.assertEqual((fx.exif_bytes(data, 'GPS', 5), fx.exif_rationals(data, 'GPS', 6)), ([2], [(25, 2)]))
        losses = [(l['key'], l['before'], l['reason']) for l in self.row(out, 'x')['losses']]
        self.assertEqual(losses, [('XMP-exif:GPSAltitude', '523/10', 'xmpAltitudeNotExpressible'), ('XMP-exif:GPSAltitudeRef', '0', 'xmpAltitudeNotExpressible')])
        plan = self.report(out, 'location-plan.json')['items'][0]
        self.assertEqual([l['reason'] for l in plan['losses']], ['xmpAltitudeNotExpressible'] * 2)            # declared in the plan before any write


class CrossOperation(NativeBase):
    """E3R-5: a time write must never change the meaning of an untouched GPS height by creating an ExifIFD (the native writer then adds an ExifVersion of 0232), and a
    location write must not either. Both operation orders, over the metadata editions, compare the typed height (not only the GPS bytes) after every step."""
    XMP_TIME = fx.xmp_properties(captured='2026-03-01T12:00:00+01:00')
    GPS24 = {'version': (2, 4, 0, 0), 'lat': ((10, 1), (0, 1), (0, 1)), 'lon': ((20, 1), (0, 1), (0, 1)), 'alt': (523, 10), 'alt_ref': 0}

    def fixtures(self):
        return {'none24': fx.jpeg(exif_version=None, dto=None, off=None, sub=None, gps=self.GPS24, xmp=self.XMP_TIME),                       # GPS-only 2.4, no ExifIFD at all
                'none24dto': fx.jpeg(exif_version=None, dto='2026:03:01 12:00:00', off=None, sub=None, gps=self.GPS24, xmp=self.XMP_TIME),      # an ExifIFD without an ExifVersion
                'legacy': fx.jpeg(exif_version=b'0232', dto='2026:03:01 12:00:00', off=None, sub=None, gps=self.GPS24, xmp=self.XMP_TIME),
                'exif3': fx.jpeg(exif_version=b'0300', dto='2026:03:01 12:00:00', off=None, sub=None, gps={**self.GPS24, 'version': (2, 3, 0, 0)}, xmp=self.XMP_TIME)}

    EXPECTED = {'none24': ('ellipsoidal', 'gpsVersionIdOnly'), 'none24dto': ('ellipsoidal', 'gpsVersionIdOnly'), 'legacy': ('unspecified', 'legacyEditionRef'), 'exif3': ('ellipsoidal', 'exif3EllipsoidalRef')}

    def step(self, names, operation):
        if operation == 'time':
            document = doc('correctTime', items(self.root, names), corrections=[{'group': 'dev1', 'shift': {'seconds': '60'}}])
        else:
            document = doc('setLocation', items(self.root, names), positions=[{'item': n, **POS} for n in names], policies={'staleCompanions': 'keep'})
        out = self.run_op(document)
        for name in names:
            (self.root / (name + '.jpg')).write_bytes(self.photo(out, name))        # the next step starts from this step's output
        return out

    def snapshot(self, names):
        return {n: (lambda h: (h['reference'], h['basis'], h['meters']))(self.locate((self.root / (n + '.jpg')).read_bytes())) for n in names}

    def test_the_typed_height_survives_both_operation_orders_in_every_edition(self):
        for order in (('time', 'location', 'time'), ('location', 'time', 'location')):
            for name, data in self.fixtures().items():
                (self.root / (name + '.jpg')).write_bytes(data)
            names = list(self.fixtures())
            before = self.snapshot(names)
            self.assertEqual({n: v[:2] for n, v in before.items()}, self.EXPECTED)
            for operation in order:
                self.step(names, operation)
                self.assertEqual(self.snapshot(names), before, (order, operation))             # reference, basis and metres: the meaning is preserved, not just the raw bytes
            for name in names:
                data = (self.root / (name + '.jpg')).read_bytes()
                if name == 'none24':
                    self.assertEqual(fx.exif_tags(data, 'ExifIFD'), [])                      # no ExifIFD, and so no ExifVersion, was ever created
                self.assertEqual(fx.exif_bytes(data, 'GPS', 0), [2, 4, 0, 0] if name != 'exif3' else [2, 3, 0, 0])      # the GPS version is never rewritten
                self.assertEqual(fx.exif_ascii(data, 'ExifIFD', 0x9000), {'legacy': '0232', 'exif3': '0300'}.get(name))

    def test_the_native_precondition_is_real_and_a_correction_never_triggers_it(self):
        import subprocess
        data = self.fixtures()['none24']
        self.put('direct', data)
        target = self.root / 'direct-out.jpg'
        done = subprocess.run(['/usr/bin/perl', self.exe, '-config', '', '-n', '-ExifIFD:DateTimeOriginal=2026:03:01 12:00:00', '-o', str(target), str(self.root / 'direct.jpg')], capture_output=True, text=True)
        self.assertEqual((done.returncode, done.stderr), (0, ''))
        created = target.read_bytes()
        self.assertEqual(fx.exif_ascii(created, 'ExifIFD', 0x9000), '0232')                      # the hazard: a native time write that creates the ExifIFD adds ExifVersion 0232 ...
        self.assertEqual(fx.exif_rationals(created, 'GPS', 6), fx.exif_rationals(data, 'GPS', 6))     # ... while every GPS byte stays identical ...
        self.assertEqual(self.locate(created)['reference'], 'unspecified')                       # ... and an ellipsoidal height has silently become unspecified
        before = self.locate(data)
        self.assertEqual(before['reference'], 'ellipsoidal')
        # the proof catches exactly that: the typed meaning is compared after the write, so such a write could never be published
        payloads_before, payloads_after = (records.Payloads(containers.locate(d)) for d in (data, created))
        problems = e3proofs.height_problems({'kind': 'time', 'exifTargets': []}, payloads_before, payloads_after, '$.items[0]')
        self.assertEqual([(p['code'], p['editionBefore'], p['editionAfter']) for p in problems], [('ALTITUDE_MEANING_CHANGED', 'gpsIfd24', 'legacy')])
        from schemaxis.adaptors.exiftool import proofs
        unexpected = e3proofs.exif_problems(proofs.exif_nontarget(payloads_before, payloads_after, set(), set(), '$.items[0]'))
        self.assertIn('UNREQUESTED_METADATA_CHANGED', [p['code'] for p in unexpected])
        # a correction of this very file (XMP time only) neither creates an ExifIFD nor changes the meaning
        self.step(['direct'], 'time')
        self.assertEqual(fx.exif_tags((self.root / 'direct.jpg').read_bytes(), 'ExifIFD'), [])
        self.assertEqual(self.locate((self.root / 'direct.jpg').read_bytes())['reference'], 'ellipsoidal')


class Mutants(NativeBase):
    """Byte-level mutants of a real setLocation run: every mutant edits a copy of the retained run and must fail verify with one exact semantic code."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = Path(tempfile.mkdtemp(prefix='e3-place-mutants-')).resolve()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.media = cls.tmp / 'media'
        cls.media.mkdir()
        soft = fx.jpeg(exif_version=b'0300', ifd0_extra=[fx.a.ascii_entry(0x0131, 'OriginalSoft')], xmp=fx.xmp_properties(extra='<dc:title><rdf:Alt><rdf:li xml:lang="x-default">Original title</rdf:li></rdf:Alt></dc:title>'))
        cls.files = {'zero': fx.jpeg(exif_version=b'0300'), 'tiny': fx.jpeg(exif_version=b'0300'), 'plus': fx.jpeg(exif_version=b'0300'), 'flip': fx.jpeg(exif_version=b'0300'),
                     'create': fx.jpeg(exif=False), 'soft': soft, 'v232': fx.jpeg(exif_version=b'0232'), 'v3': fx.jpeg(exif_version=b'0300', gps={'version': (2, 3, 0, 0), 'lat': ((1, 1), (0, 1), (0, 1)), 'lon': ((2, 1), (0, 1), (0, 1))}),
                     'xmpx': fx.jpeg(exif_version=b'0300', xmp=fx.xmp_properties(lat='1,0.0N', lon='2,0.0E')), 'alt': fx.jpeg(exif_version=b'0300')}
        for name, data in cls.files.items():
            (cls.media / (name + '.jpg')).write_bytes(data)
        cls.positions = {'zero': {'latitude': '0', 'longitude': '0'}, 'tiny': {'latitude': '0.000000001', 'longitude': '10'}, 'plus': {'latitude': '35.5', 'longitude': '10'},
                         'flip': {'latitude': '35.5', 'longitude': '10'}, 'create': {'latitude': '35.5', 'longitude': '10'}, 'soft': {'latitude': '35.5', 'longitude': '10'},
                         'v232': {'latitude': '35.5', 'longitude': '10'}, 'v3': {'latitude': '35.5', 'longitude': '10'}, 'xmpx': {'latitude': '35.123456789', 'longitude': '10'},
                         'alt': {'latitude': '35.5', 'longitude': '10', 'altitude': {'meters': '39999.999', 'reference': 'seaLevel'}}}
        cls.names = list(cls.files)
        cls.main = cls.tmp / 'main'
        adaptor.run(doc('setLocation', items(cls.media, cls.names), positions=[{'item': n, **s} for n, s in cls.positions.items()], policies={'xmp': 'ifPresent'}), cls.main, executable=cls.exe)

    def setUp(self):
        pass

    def index(self, name):
        return self.names.index(name)

    def mutate(self, name, change):
        target = self.tmp / ('mutant-' + name)
        shutil.copytree(self.main, target, symlinks=True)
        change(target)
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.verify(target, executable=self.exe)
        fault = caught.exception.fault
        cause = fault.observed.get('cause', {})
        problems = [p['code'] for p in cause.get('observed', {}).get('problems', [])] if isinstance(cause.get('observed'), dict) else []
        return cause.get('code', fault.code), cause.get('location', fault.location), problems

    @staticmethod
    def order(data):
        at = data.index(b'Exif\0\0') + 6
        return '<' if data[at:at + 2] == b'II' else '>'

    def rationals(self, data, pairs):
        import struct
        return b''.join(struct.pack(self.order(data) + 'II', n, d) for n, d in pairs)

    def edit(self, item, old_pairs, new_pairs):
        def go(directory):
            path = directory / 'photos' / (item + '.jpg')
            data = path.read_bytes()
            old, new = self.rationals(data, old_pairs), self.rationals(data, new_pairs)
            self.assertEqual(data.count(old), 1, item)
            path.write_bytes(data.replace(old, new))
        return go

    def replace(self, item, old, new, count=1):
        def go(directory):
            path = directory / 'photos' / (item + '.jpg')
            data = path.read_bytes()
            self.assertEqual(data.count(old), count, (item, old))
            path.write_bytes(data.replace(old, new))
        return go

    def test_the_unmutated_run_verifies(self):
        self.assertTrue(adaptor.verify(self.main, executable=self.exe)['verified'])

    def test_M_L0_and_M_L0b_the_zero_rule(self):
        # requested latitude 0 stored as 9/50000000 s (= 5e-11 degrees, inside the 2e-10 bound): the exact-zero rule still refuses it
        code, location, _ = self.mutate('L0', self.edit_lat_zero())
        self.assertEqual((code, location), ('READBACK_MISMATCH', '$.items[%d].location.latitude' % self.index('zero')))
        # requested 1e-9 degrees (stored 0/1 0/1 9/2500000) mutated to an exact zero: a non-zero request may never read back as zero
        code, location, _ = self.mutate('L0b', self.edit('tiny', [(0, 1), (0, 1), (9, 2500000)], [(0, 1), (0, 1), (0, 1)]))
        self.assertEqual((code, location), ('READBACK_MISMATCH', '$.items[%d].location.latitude' % self.index('tiny')))

    def edit_lat_zero(self):
        def go(directory):
            path = directory / 'photos' / 'zero.jpg'
            data = path.read_bytes()
            zero = self.rationals(data, [(0, 1)] * 3)
            self.assertEqual(data.count(zero), 2)                        # latitude and longitude are both three zero rationals; the first (tag 2) is the latitude
            at = data.index(zero)
            path.write_bytes(data[:at] + self.rationals(data, [(0, 1), (0, 1), (9, 50000000)]) + data[at + len(zero):])
        return go

    def test_M_L1_one_input_unit_of_error_is_detected(self):
        code, location, _ = self.mutate('L1', self.edit('plus', [(35, 1), (30, 1), (0, 1)], [(35, 1), (30, 1), (9, 2500000)]))       # +1e-9 degrees > the 2e-10 bound
        self.assertEqual((code, location), ('READBACK_MISMATCH', '$.items[%d].location.latitude' % self.index('plus')))

    def test_M_L2_a_flipped_reference_letter(self):
        code, location, _ = self.mutate('L2', self.flip_reference())
        self.assertEqual((code, location), ('READBACK_MISMATCH', '$.items[%d].location.latitude' % self.index('flip')))

    def flip_reference(self):
        def go(directory):
            path = directory / 'photos' / 'flip.jpg'
            data = path.read_bytes()
            order = self.order(data)
            import struct
            head = struct.pack(order + 'HHI', 1, 2, 2) + b'N\x00\x00\x00'
            self.assertEqual(data.count(head), 1)
            path.write_bytes(data.replace(head, head[:-4] + b'S\x00\x00\x00'))
        return go

    def test_M_L3_and_M_L5_created_values_must_be_the_declared_ones(self):
        import struct
        def version(directory):
            path = directory / 'photos' / 'create.jpg'
            data = path.read_bytes()
            old = struct.pack(self.order(data) + 'HHI', 0, 1, 4) + bytes([2, 3, 0, 0])
            self.assertEqual(data.count(old), 1)
            path.write_bytes(data.replace(old, old[:-4] + bytes([2, 2, 0, 0])))

        def ycbcr(directory):
            path = directory / 'photos' / 'create.jpg'
            data = path.read_bytes()
            old = struct.pack(self.order(data) + 'HHI', 0x0213, 3, 1) + struct.pack(self.order(data) + 'H', 1) + b'\x00\x00'
            self.assertEqual(data.count(old), 1)
            path.write_bytes(data.replace(old, old[:-4] + struct.pack(self.order(data) + 'H', 2) + b'\x00\x00'))
        code, location, _ = self.mutate('L3', version)
        self.assertEqual((code, location), ('SIDE_EFFECT_VALUE_INVALID', '$.items[%d].location.gpsVersionId' % self.index('create')))
        code, location, _ = self.mutate('L5', ycbcr)
        self.assertEqual((code, location), ('SIDE_EFFECT_VALUE_INVALID', '$.items[%d].location.creation' % self.index('create')))

    def test_M_L6_M_V_M_V3_a_change_outside_the_targets_is_unrequested_metadata(self):
        code, location, _ = self.mutate('software', self.replace('soft', b'OriginalSoft', b'XriginalSoft'))
        self.assertEqual((code, location), ('UNREQUESTED_METADATA_CHANGED', '$.items[%d].exif' % self.index('soft')))
        code, location, _ = self.mutate('title', self.replace('soft', b'Original title', b'Xriginal title'))
        self.assertEqual((code, location), ('UNREQUESTED_METADATA_CHANGED', '$.items[%d].xmp' % self.index('soft')))
        code, location, _ = self.mutate('M-V', self.replace('v232', b'0232', b'0300'))                     # ExifVersion 0232 -> 0300: a silent promotion
        self.assertEqual((code, location), ('UNREQUESTED_METADATA_CHANGED', '$.items[%d].exif' % self.index('v232')))
        import struct
        def regress(directory):
            path = directory / 'photos' / 'v3.jpg'
            data = path.read_bytes()
            old = struct.pack(self.order(data) + 'HHI', 0, 1, 4) + bytes([2, 3, 0, 0])
            self.assertEqual(data.count(old), 1)
            path.write_bytes(data.replace(old, old[:-4] + bytes([2, 4, 0, 0])))
        code, location, _ = self.mutate('M-V3', regress)                                                  # an existing GPSVersionID is never changed
        self.assertEqual((code, location), ('UNREQUESTED_METADATA_CHANGED', '$.items[%d].exif' % self.index('v3')))

    def test_M_L2_xmp_one_unit_in_the_last_minute_digit_breaks_the_exact_rule(self):
        code, location, _ = self.mutate('xmp', self.replace('xmpx', b'35,7.40740734N', b'35,7.40740735N'))
        self.assertEqual((code, location), ('READBACK_MISMATCH', '$.items[%d].location.xmp.latitude' % self.index('xmpx')))

    def test_M_L3_altitude_one_millimetre_at_39999_999_m(self):
        code, location, _ = self.mutate('alt', self.altitude_mm())
        self.assertEqual((code, location), ('READBACK_MISMATCH', '$.items[%d].location.altitude' % self.index('alt')))

    def altitude_mm(self):
        def go(directory):
            path = directory / 'photos' / 'alt.jpg'
            data = path.read_bytes()
            old, new = self.rationals(data, [(39999999, 1000)]), self.rationals(data, [(39999998, 1000)])
            self.assertEqual(data.count(old), 1)
            path.write_bytes(data.replace(old, new))
        return go
