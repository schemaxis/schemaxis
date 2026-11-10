"""E5 time, location, geotag, transfer and minimise operations over TIFF, DNG, PNG, WebP and HEIF (genuine ExifTool 13.55 through SCHEMAXIS_EXIFTOOL).

One test is one real native run of ONE declared operation over ONE container. Every expected value is a literal derived by hand in this file (calendar arithmetic, the decimal
coordinates of the request, the literal fields of the hand-built source photograph); the produced bytes are read with the standard-library walkers of the shipped readers only to compare
with those literals, never to derive them. Fixtures are assembled by ``exiftool_e5_time_fixtures`` from raw TIFF, XMP and IIM entries and opaque payloads: no pixel is decoded.

The positive rows of the qualifier (``tools/qualify_exiftool_containers.py``) are exactly the tests named in its explicit list; refusals, controls and mutants never count as support.
"""
from fractions import Fraction
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tools'), str(ROOT / 'tests/unit')]

import exiftool_e3_fixtures as e3  # noqa: E402
import exiftool_e4_fixtures as f4  # noqa: E402
import exiftool_e5_fixtures as f  # noqa: E402
import exiftool_e5_time_fixtures as t  # noqa: E402
import author_exiftool_fixtures as a  # noqa: E402
from schemaxis.adaptors.exiftool import adaptor, e4model, e5locate, records  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402
from test_exiftool_e3_geotag import EQUATOR  # noqa: E402

EXIFTOOL = os.environ.get('SCHEMAXIS_EXIFTOOL')
V = 'schemaxis.exiftool/1'
KINDS = ('tiff', 'dng', 'png', 'webp', 'heif')
BOUND = Fraction(2, 10 ** 10)
# what each fixture's opaque, protected payload looks like in the file (written here, never taken from the code under test)
PROTECTED = {'tiff': [f.STRIP], 'dng': [f.STRIP], 'png': [f.GAMA, f.IDAT + f.IEND], 'webp': [f.ck(b'VP8 ', f.vp8())], 'heif': [b'OPAQUE-HVC1-IMAGE-24BYTES'[:24]]}
ALL_GROUPS = ['descriptive', 'rights', 'camera', 'exposure', 'deviceSerials', 'rating']


def payloads(data):
    return records.Payloads(e5locate.locate(data))


def entry(data, ifd, tag):
    state = payloads(data).exif
    if state[0] != 'ok':
        return None
    group = state[1]['ifds'].get(ifd)
    found = [e for e in group[1] if e.tag == tag] if group and group[0] == 'ok' else []
    assert len(found) <= 1, (ifd, tag)
    return found[0] if found else None


def ascii_of(data, ifd, tag):
    e = entry(data, ifd, tag)
    return None if e is None else e.raw.rstrip(b'\0').decode('ascii')


def total(data, ifd, tag):
    e = entry(data, ifd, tag)
    return None if e is None else sum(Fraction(n, d) / unit for (n, d), unit in zip(e.values(), (1, 60, 3600)))


def xmp_value(data, prop):
    state = payloads(data).xmp
    found = state[1].get(prop) if state[0] == 'ok' else None
    assert not found or len(found) == 1, prop
    return None if not found else found[0].get('value')


def snapshot(data, groups=None, fields=None):
    return e4model.snapshot(payloads(data), e4model.selection({'groups': groups or [], 'fields': fields or []}))


def iim(data, record, dataset):
    state = payloads(data).iptc
    found = state[1]['datasets'].get((record, dataset)) if state[0] == 'ok' else None
    return None if not found else found[0].decode('ascii')


@unittest.skipUnless(EXIFTOOL and Path(EXIFTOOL).exists(), 'a real ExifTool 13.55 is needed (SCHEMAXIS_EXIFTOOL)')
class Operations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='e5-ops-')).resolve()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.media = cls.tmp / 'media'
        cls.media.mkdir()
        cls.runs = 0

    # ------------------------------------------------------------------ helpers
    def put(self, name, data):
        (self.media / name).write_bytes(data)
        return str(self.media / name)

    def run_op(self, document, **kw):
        type(self).runs += 1
        out = self.tmp / ('run%d' % self.runs)
        result = adaptor.run(document, out, executable=EXIFTOOL, timeout=300, **kw)
        self.assertTrue(result['verified'])
        self.assertEqual(adaptor.verify(out, executable=EXIFTOOL)['nativeReplay'], 'fresh-replay-matched')
        return out, result

    def output(self, out, ident):
        return next(p for p in sorted((out / 'photos').glob(ident + '.*')) if not p.name.endswith('.metadata.json')).read_bytes()

    def report(self, out, name):
        return json.loads((out / name).read_text())

    def proofs_of(self, out, name, ident):
        row = next(r for r in self.report(out, name)['items'] if r['id'] == ident)
        self.assertEqual(row['status'], 'written')
        proofs = row['proofs']
        self.assertEqual(proofs['problems'], 0)
        self.assertTrue(all(k in proofs for k in ('P', 'R', 'N')))
        return row

    def keeps(self, kind, data):
        for part in PROTECTED[kind]:
            self.assertEqual(data.count(part), 1, (kind, part[:12]))

    # ------------------------------------------------------------------ correctTime: one hour later (the shift is +3600 s; 12:00:00 becomes 13:00:00 on 2026-03-01)
    def correct_time(self, kind):
        path = self.put('t' + t.EXTENSIONS[kind], t.full_time(kind))
        out, result = self.run_op({'version': V, 'operation': 'correctTime', 'media': {'items': [{'id': 't', 'path': path}]}, 'corrections': [{'group': 'dev1', 'shift': {'seconds': '3600'}}]})
        self.assertEqual((result['written'], result['refused'], result['failed']), (1, 0, 0))
        data = self.output(out, 't')
        self.assertEqual(ascii_of(data, 'ExifIFD', 0x9003), '2026:03:01 13:00:00')
        self.assertEqual((ascii_of(data, 'ExifIFD', 0x9011), ascii_of(data, 'ExifIFD', 0x9291)), ('+01:00', '12'))      # the offset and the fraction are untouched
        self.assertEqual(xmp_value(data, 'photoshop:DateCreated'), '2026-03-01T13:00:00.12+01:00')
        if kind in ('tiff', 'dng'):
            self.assertEqual((iim(data, 2, 55), iim(data, 2, 60)), ('20260301', '130000+0100'))
        else:
            self.assertEqual(payloads(data).iptc[0], 'notApplicable')      # PNG, WebP and HEIF have no IPTC slot
        self.keeps(kind, data)
        self.assertNotIn(b'2026:03:01 12:00:00', data)
        row = self.proofs_of(out, 'write-report.json', 't')
        self.assertEqual(self.report(out, 'write-report.json')['operation'], 'correctTime')
        return row

    def test_correct_time_tiff(self): self.correct_time('tiff')
    def test_correct_time_dng(self): self.correct_time('dng')
    def test_correct_time_png(self): self.correct_time('png')
    def test_correct_time_webp(self): self.correct_time('webp')
    def test_correct_time_heif(self): self.correct_time('heif')

    # ------------------------------------------------------------------ setLocation: 35.658581 N 139.745433 E
    def set_location(self, kind, altitude=None):
        path = self.put('l' + t.EXTENSIONS[kind], t.full_time(kind))
        position = {'latitude': '35.658581', 'longitude': '139.745433', **({'altitude': altitude} if altitude else {})}
        out, result = self.run_op({'version': V, 'operation': 'setLocation', 'media': {'items': [{'id': 'l', 'path': path}]}, 'default': position})
        self.assertEqual((result['written'], result['refused'], result['failed']), (1, 0, 0))
        data = self.output(out, 'l')
        self.assertEqual((ascii_of(data, 'GPS', 1), ascii_of(data, 'GPS', 3)), ('N', 'E'))
        self.assertLessEqual(abs(total(data, 'GPS', 2) - Fraction('35.658581')), BOUND)
        self.assertLessEqual(abs(total(data, 'GPS', 4) - Fraction('139.745433')), BOUND)
        if altitude:
            self.assertEqual((entry(data, 'GPS', 5).values(), entry(data, 'GPS', 6).values()), ([2], [(25, 2)]))      # 12.5 m above sea level in an Exif 3.0 file (the E3 edition rule: reference byte 2), exactly 25/2
        self.assertEqual(ascii_of(data, 'ExifIFD', 0x9003), '2026:03:01 12:00:00')                                       # the capture time is not part of this write
        self.keeps(kind, data)
        self.proofs_of(out, 'write-report.json', 'l')

    def test_set_location_tiff(self): self.set_location('tiff')
    def test_set_location_dng(self): self.set_location('dng')
    def test_set_location_png(self): self.set_location('png')
    def test_set_location_webp(self): self.set_location('webp')
    def test_set_location_heif(self): self.set_location('heif')
    def test_set_location_with_typed_altitude_tiff(self): self.set_location('tiff', {'meters': '12.5', 'reference': 'seaLevel'})
    def test_set_location_with_typed_altitude_png(self): self.set_location('png', {'meters': '12.5', 'reference': 'seaLevel'})

    # ------------------------------------------------------------------ geotagFromTrack: the watch track places a photo at 12:00:10 +09:00 on the equator at 10.001 E (hand interpolation)
    def geotag(self, kind):
        track = self.put('watch.gpx', EQUATOR)
        local = dict(dto='2026:03:01 12:00:10', off='+09:00', sub=None, xmp=e3.xmp_properties(captured='2026-03-01T12:00:10+09:00'))
        if kind in ('tiff', 'dng'):
            local['iptc'] = [(2, 55, '20260301'), (2, 60, '120010+0900')]
        path = self.put('g' + t.EXTENSIONS[kind], t.full_time(kind, **local))
        out, result = self.run_op({'version': V, 'operation': 'geotagFromTrack', 'media': {'items': [{'id': 'g', 'path': path}]}, 'tracks': [{'id': 'watch', 'path': track}]})
        self.assertEqual((result['written'], result['refused'], result['failed']), (1, 0, 0))
        data = self.output(out, 'g')
        self.assertEqual((total(data, 'GPS', 2), ascii_of(data, 'GPS', 1), ascii_of(data, 'GPS', 3)), (0, 'N', 'E'))
        self.assertLessEqual(abs(total(data, 'GPS', 4) - Fraction('10.001')), BOUND)
        self.assertEqual(ascii_of(data, 'GPS', 0x1D), '2026:03:01')                                                     # the photo instant 03:00:10 UTC
        self.keeps(kind, data)
        self.proofs_of(out, 'geotag-report.json' if (out / 'geotag-report.json').exists() else 'write-report.json', 'g')

    def test_geotag_tiff(self): self.geotag('tiff')
    def test_geotag_dng(self): self.geotag('dng')
    def test_geotag_png(self): self.geotag('png')
    def test_geotag_webp(self): self.geotag('webp')
    def test_geotag_heif(self): self.geotag('heif')

    # ------------------------------------------------------------------ copyMetadata from a JPEG photograph into each container
    def copy_descriptive(self, kind):
        source = self.put('a.jpg', f4.master())
        dest = self.put('b' + t.EXTENSIONS[kind], t.full_time(kind))
        out, result = self.run_op({'version': V, 'operation': 'copyMetadata', 'media': {'items': [{'id': 'a', 'path': source}, {'id': 'b', 'path': dest}]}, 'source': {'item': 'a'},
                                   'transfer': {'groups': ALL_GROUPS}, 'policies': {'existing': 'replace'}})
        self.assertEqual((result['written'], result['refused']), (1, 1))           # the source is its own refused destination
        data = self.output(out, 'b')
        s = snapshot(data, groups=ALL_GROUPS)
        self.assertEqual(s['title']['value'], {'text': 'Harbour', 'languages': [{'language': 'de-DE', 'text': 'Hafen'}]})
        self.assertEqual((s['keywords']['value'], s['creator']['value'], s['copyright']['value']), (['k1', 'k2'], ['Ann; Bob', 'Cy'], {'text': '(c) 2024 A', 'languages': []}))
        self.assertEqual((s['cameraMake']['value'], s['cameraModel']['value'], s['lensMake']['value'], s['lensModel']['value']), ('Canon', 'EOS 5D', 'LensCo', 'L50'))
        self.assertEqual([s[k]['value'] for k in ('exposureTime', 'fNumber', 'focalLength', 'exposureBias')], [(10, 30), (28, 10), (35, 2), (-2, 6)])
        self.assertEqual((s['isoSpeed']['value'], s['focalLength35mm']['value'], s['rating']['value']), (400, 52, 4))
        self.assertEqual((s['bodySerialNumber']['value'], s['lensSerialNumber']['value']), ('B123', 'L456'))
        self.keeps(kind, data)
        row = self.proofs_of(out, 'transfer-report.json', 'b')
        self.assertIn('T', row['proofs'])
        losses = {(x['destination'], x['reason']) for x in row['losses']}
        if kind in ('png', 'webp', 'heif'):
            self.assertEqual(payloads(data).iptc[0], 'notApplicable')                      # no IPTC slot: the declared loss, never a created carrier
            self.assertEqual({('IPTC:ObjectName', 'iptcNotAvailableInContainer'), ('IPTC:Keywords', 'iptcNotAvailableInContainer'), ('IPTC:By-line', 'iptcNotAvailableInContainer'),
                              ('IPTC:CopyrightNotice', 'iptcNotAvailableInContainer')}, {l for l in losses if l[1] == 'iptcNotAvailableInContainer'})
        else:
            self.assertFalse([l for l in losses if l[1] == 'iptcNotAvailableInContainer'])         # TIFF and DNG have the slot: no such loss

    def test_copy_into_tiff(self): self.copy_descriptive('tiff')
    def test_copy_into_dng(self): self.copy_descriptive('dng')
    def test_copy_into_png(self): self.copy_descriptive('png')
    def test_copy_into_webp(self): self.copy_descriptive('webp')
    def test_copy_into_heif(self): self.copy_descriptive('heif')

    # ------------------------------------------------------------------ copyMetadata of the capture time and the position (source 2026-03-01 12:00:00.12 +01:00, 35.5 N 139.25 E, 52.3 m)
    def copy_time_location(self, kind):
        source = self.put('a.jpg', f4.master(gps=t.TOKYO))
        earlier = dict(dto='2025:06:01 08:00:00', off='-05:00', sub='34', xmp=None)
        if kind in ('tiff', 'dng'):
            earlier['iptc'] = [(2, 55, '20250601'), (2, 60, '080000-0500')]
        dest = self.put('b' + t.EXTENSIONS[kind], t.full_time(kind, **earlier))
        out, result = self.run_op({'version': V, 'operation': 'copyMetadata', 'media': {'items': [{'id': 'a', 'path': source}, {'id': 'b', 'path': dest}]}, 'source': {'item': 'a'},
                                   'transfer': {'groups': ['captureTime', 'location']}, 'policies': {'existing': 'replace'}})
        self.assertEqual((result['written'], result['refused']), (1, 1))
        data = self.output(out, 'b')
        self.assertEqual((ascii_of(data, 'ExifIFD', 0x9003), ascii_of(data, 'ExifIFD', 0x9011), ascii_of(data, 'ExifIFD', 0x9291)), ('2026:03:01 12:00:00', '+01:00', '12'))
        self.assertEqual((total(data, 'GPS', 2), total(data, 'GPS', 4), ascii_of(data, 'GPS', 1), ascii_of(data, 'GPS', 3)), (Fraction(71, 2), Fraction(557, 4), 'N', 'E'))
        self.assertEqual(entry(data, 'GPS', 6).values(), [(523, 10)])
        if kind in ('tiff', 'dng'):
            self.assertEqual(iim(data, 2, 60), '120000+0100')
        self.keeps(kind, data)
        self.proofs_of(out, 'transfer-report.json', 'b')

    def test_copy_time_and_location_into_tiff(self): self.copy_time_location('tiff')
    def test_copy_time_and_location_into_dng(self): self.copy_time_location('dng')
    def test_copy_time_and_location_into_png(self): self.copy_time_location('png')
    def test_copy_time_and_location_into_webp(self): self.copy_time_location('webp')
    def test_copy_time_and_location_into_heif(self): self.copy_time_location('heif')

    # ------------------------------------------------------------------ a capture time spread across carriers of a container source (EXIF wall time, IPTC time with an offset) is carried whole
    def test_a_capture_time_spread_across_the_carriers_of_a_tiff_source_is_carried_into_a_png_destination(self):
        source = self.put('a.tif', t.full_time('tiff', dto='2026:03:01 12:00:00', off=None, sub=None, xmp=None, iptc=[(2, 55, '20260301'), (2, 60, '120000+0900')]))
        dest = self.put('b.png', t.full_time('png', dto='2025:06:01 08:00:00', off='-05:00', sub=None, xmp=None))
        out, result = self.run_op({'version': V, 'operation': 'copyMetadata', 'media': {'items': [{'id': 'a', 'path': source}, {'id': 'b', 'path': dest}]}, 'source': {'item': 'a'},
                                   'transfer': {'groups': ['captureTime']}, 'policies': {'existing': 'replace'}})
        self.assertEqual((result['written'], result['refused']), (1, 1))
        data = self.output(out, 'b')
        self.assertEqual((ascii_of(data, 'ExifIFD', 0x9003), ascii_of(data, 'ExifIFD', 0x9011)), ('2026:03:01 12:00:00', '+09:00'))     # the wall time from EXIF, the offset from the IPTC time
        self.assertIsNone(ascii_of(data, 'ExifIFD', 0x9291))                                                                         # the source records no fraction anywhere
        self.proofs_of(out, 'transfer-report.json', 'b')

    # ------------------------------------------------------------------ the container as the transfer SOURCE (a PNG photograph's values go to a JPEG destination)
    def test_a_png_source_transfers_into_a_jpeg_destination(self):
        source = self.put('a.png', t.png(xmp=e3.xmp_properties(extra=f4.lang_alt('dc:title', 'Harbour')), make='Nikon', model='Z6'))
        dest = self.put('b.jpg', f4.plain())
        out, result = self.run_op({'version': V, 'operation': 'copyMetadata', 'media': {'items': [{'id': 'a', 'path': source}, {'id': 'b', 'path': dest}]}, 'source': {'item': 'a'},
                                   'transfer': {'groups': ['descriptive', 'camera']}, 'policies': {'existing': 'replace'}})
        self.assertEqual((result['written'], result['refused']), (1, 1))
        s = snapshot((out / 'photos' / 'b.jpg').read_bytes(), groups=['descriptive', 'camera'])
        self.assertEqual((s['title']['value']['text'], s['cameraMake']['value'], s['cameraModel']['value']), ('Harbour', 'Nikon', 'Z6'))

    def test_a_transfer_that_needs_an_xmp_item_a_heif_does_not_have_is_refused_before_native(self):
        source = self.put('a.jpg', f4.master())
        dest = self.put('b.heic', t.heic(xmp=None))                              # an Exif item exists, an XMP item does not
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.run({'version': V, 'operation': 'copyMetadata', 'media': {'items': [{'id': 'a', 'path': source}, {'id': 'b', 'path': dest}]}, 'source': {'item': 'a'},
                         'transfer': {'groups': ['descriptive']}, 'policies': {'existing': 'replace'}}, self.tmp / 'h-xmp', executable=EXIFTOOL, timeout=300)
        faults = {f['location']: f for f in caught.exception.fault.observed['firstFaults']}
        refused = faults['$.items[b]']
        self.assertEqual((refused['code'], refused['observed']['missing'], refused['observed']['limitation']), ('HEIF_METADATA_ITEM_CREATION_UNSUPPORTED', ['xmp'], 'heifNativeMetadataCreationNotReproducible'))

    # ------------------------------------------------------------------ applySidecar: a sidecar exported from the JPEG master is applied to a container item
    def apply_sidecar(self, kind):
        master = self.put('m.jpg', f4.master())
        exported, _ = self.run_op({'version': V, 'operation': 'exportSidecar', 'media': {'items': [{'id': 'm', 'path': master}]}, 'transfer': {'groups': ['descriptive', 'camera', 'exposure']}})
        sidecar = str(exported / 'sidecars' / 'm.xmp')
        dest = self.put('s' + t.EXTENSIONS[kind], t.full_time(kind))
        out, result = self.run_op({'version': V, 'operation': 'applySidecar', 'media': {'items': [{'id': 's', 'path': dest, 'sidecar': sidecar}]}, 'source': {'sidecar': 'declared'},
                                   'transfer': {'groups': ['descriptive', 'camera', 'exposure']}, 'policies': {'existing': 'replace'}})
        self.assertEqual((result['written'], result['refused']), (1, 0))
        data = self.output(out, 's')
        s = snapshot(data, groups=['descriptive', 'camera', 'exposure'])
        self.assertEqual((s['title']['value']['text'], s['keywords']['value'], s['cameraMake']['value'], s['cameraModel']['value']), ('Harbour', ['k1', 'k2'], 'Canon', 'EOS 5D'))
        self.assertEqual([s[k]['value'] for k in ('exposureTime', 'fNumber', 'focalLength')], [(10, 30), (28, 10), (35, 2)])
        self.keeps(kind, data)
        self.proofs_of(out, 'transfer-report.json', 's')

    def test_apply_sidecar_tiff(self): self.apply_sidecar('tiff')
    def test_apply_sidecar_dng(self): self.apply_sidecar('dng')
    def test_apply_sidecar_png(self): self.apply_sidecar('png')
    def test_apply_sidecar_webp(self): self.apply_sidecar('webp')
    def test_apply_sidecar_heif(self): self.apply_sidecar('heif')

    # ------------------------------------------------------------------ exportSidecar from a DNG that carries descriptive XMP (a real positive, not a documented blanket refusal)
    def test_export_sidecar_from_a_dng_with_descriptive_metadata(self):
        xmp = e3.xmp_properties(extra=f4.lang_alt('dc:title', 'Harbour', de_DE='Hafen') + f4.bag('dc:subject', 'k1', 'k2'))
        path = self.put('d.dng', t.full_time('dng', xmp=xmp))
        out, result = self.run_op({'version': V, 'operation': 'exportSidecar', 'media': {'items': [{'id': 'd', 'path': path}]}, 'transfer': {'groups': ['descriptive']}})
        self.assertEqual((result['written'], result['refused']), (1, 0))
        text = (out / 'sidecars' / 'd.xmp').read_bytes()
        for literal in (b'>Harbour<', b'>Hafen<', b'>k1<', b'>k2<'):
            self.assertIn(literal, text)

    # ------------------------------------------------------------------ the Exif block is created where the container can hold one (no Exif at all before the write)
    def creates_exif(self, kind):
        path = self.put('n' + t.EXTENSIONS[kind], t.full_time(kind, **({'exif': False} if kind in ('tiff', 'dng') else {'exif_block': False})))
        before = Path(path).read_bytes()
        self.assertEqual(entry(before, 'GPS', 2), None)
        out, result = self.run_op({'version': V, 'operation': 'setLocation', 'media': {'items': [{'id': 'n', 'path': path}]}, 'default': {'latitude': '35.658581', 'longitude': '139.745433'}})
        self.assertEqual((result['written'], result['refused'], result['failed']), (1, 0, 0))
        data = self.output(out, 'n')
        self.assertEqual(payloads(data).exif[0], 'ok')
        self.assertLessEqual(abs(total(data, 'GPS', 2) - Fraction('35.658581')), BOUND)
        self.assertLessEqual(abs(total(data, 'GPS', 4) - Fraction('139.745433')), BOUND)
        self.assertEqual(xmp_value(data, 'photoshop:DateCreated'), '2026-03-01T12:00:00.12+01:00')       # the XMP time that was already there is untouched
        self.keeps(kind, data)
        row = self.proofs_of(out, 'write-report.json', 'n')
        if kind != 'tiff':       # a TIFF always has its IFD0 (only a GPS IFD is added); PNG and WebP gain a whole Exif block, recorded as a declared fact
            self.assertIn('exifCreated', json.dumps(row))

    def test_set_location_creates_a_gps_ifd_in_a_tiff_without_an_exif_sub_ifd(self): self.creates_exif('tiff')
    def test_set_location_creates_an_exif_block_in_a_png_without_one(self): self.creates_exif('png')
    def test_set_location_creates_an_exif_block_in_a_webp_without_one(self): self.creates_exif('webp')

    # ------------------------------------------------------------------ a HEIF without an Exif item is never asked to create one (named native capability gap)
    def test_set_location_on_a_heif_without_an_exif_item_is_refused_before_native(self):
        path = self.put('h.heic', t.full_time('heif', exif_block=False))
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.run({'version': V, 'operation': 'setLocation', 'media': {'items': [{'id': 'h', 'path': path}]}, 'default': {'latitude': '35.658581', 'longitude': '139.745433'}}, self.tmp / 'h2', executable=EXIFTOOL)
        self.assertEqual(caught.exception.fault.code, 'NO_USABLE_ITEMS')
        first = caught.exception.fault.observed['firstFaults'][0]
        self.assertEqual((first['code'], first['observed']['missing'], first['observed']['limitation']), ('HEIF_METADATA_ITEM_CREATION_UNSUPPORTED', ['exif'], 'heifNativeMetadataCreationNotReproducible'))
        self.assertEqual(first['location'], '$.items[h]')
        self.assertFalse((self.tmp / 'h2' / 'photos').exists())


if __name__ == '__main__':
    unittest.main()
