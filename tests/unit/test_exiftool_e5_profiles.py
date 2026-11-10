"""Host tests of the E5 container profile registry, the signature-based dispatcher and the shared payload decoders."""
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import exiftool_e3_fixtures as jpegs  # noqa: E402
import exiftool_e5_fixtures as f  # noqa: E402
from schemaxis.adaptors.exiftool import containers, e5common as common, e5locate, e5payloads, e5profiles, e5tiff  # noqa: E402

EXIF_DIR = ROOT / 'src' / 'schemaxis' / 'adaptors' / 'exiftool'


class Registry(unittest.TestCase):
    def test_the_profile_file_is_pinned_by_digest(self):
        self.assertEqual(hashlib.sha256((EXIF_DIR / 'containerprofiles.json').read_bytes()).hexdigest(), e5profiles.PROFILES_SHA256)
        self.assertEqual(('tiff', 'dng', 'png', 'webp', 'heif'), e5profiles.containers())

    def test_a_changed_profile_fails_closed(self):
        original = e5profiles.PROFILES_SHA256
        e5profiles._CACHE.clear()
        e5profiles.PROFILES_SHA256 = '0' * 64
        try:
            with self.assertRaises(e5profiles.PinMismatch):
                e5profiles.load()
        finally:
            e5profiles.PROFILES_SHA256 = original
            e5profiles._CACHE.clear()
        self.assertTrue(e5profiles.load())

    def test_every_container_declares_the_same_closed_set_of_facts(self):
        for name in e5profiles.containers():
            profile = e5profiles.profile(name)
            for key in ('locator', 'signatures', 'suffixes', 'maxBytes', 'slots', 'protected', 'allowedChanges', 'nativeSideEffects', 'destinations', 'removal', 'minimise',
                        'timeLocationWrite', 'refusalCodes', 'limitations'):
                self.assertIn(key, profile, '%s lacks %s' % (name, key))
            self.assertEqual({'exif', 'xmp', 'iptc'}, set(profile['destinations']))

    def test_size_bounds_and_destinations_are_the_contract_values(self):
        self.assertEqual({'tiff': 256, 'dng': 256, 'png': 64, 'webp': 64, 'heif': 64}, {n: e5profiles.profile(n)['maxBytes'] >> 20 for n in e5profiles.containers()})
        self.assertEqual([(True, True, True), (True, True, True), (True, True, False), (True, True, False), (True, True, False)],
                         [tuple(e5profiles.destination(n, fam) for fam in ('exif', 'xmp', 'iptc')) for n in e5profiles.containers()])
        self.assertFalse(e5profiles.destination('jpeg2000', 'xmp'))             # an unknown container fails closed
        self.assertFalse(e5profiles.destination('png', 'maker'))
        with self.assertRaises(KeyError):
            e5profiles.profile('jpeg2000')

    def test_removal_and_minimise_declarations(self):
        self.assertEqual([], e5profiles.profile('heif')['removal']['categories'])
        self.assertEqual('HEIF_REMOVAL_UNSUPPORTED', e5profiles.profile('heif')['removal']['unsupportedCode'])
        for name in ('tiff', 'dng', 'heif'):
            self.assertEqual((False, 'MINIMISE_UNSUPPORTED_CONTAINER'), (e5profiles.profile(name)['minimise']['supported'], e5profiles.profile(name)['minimise']['code']))
        for name in ('png', 'webp'):         # AM-17: minimise is offered, with the E2 keep-set; the retired gap name is no longer a limitation
            mini = e5profiles.profile(name)['minimise']
            self.assertEqual(True, mini['supported'])
            self.assertNotIn('code', mini)
            self.assertEqual(['EXIF:Orientation', 'EXIF:YCbCrPositioning', 'EXIF:ColorSpace'], mini['keep'])
            self.assertNotIn('minimiseNotImplementedForPngWebp', e5profiles.profile(name)['limitations'])
        self.assertIn('-all=', e5profiles.profile('webp')['removal']['forbiddenArguments'])
        # AM-19: the pinned recipe and rule describe the arguments the planner really builds (the E2 closed reset, then the keep-set write-back); no stale "by name" or "only when no keep-set key" method claim
        for name in ('png', 'webp'):
            profile = e5profiles.profile(name)
            recipe, rule = profile['removal']['recipes']['exif'], profile['minimise']['rule']
            for text in (recipe, rule):
                self.assertIn('-EXIF:all=', text, name)
                self.assertIn('AM-19', text, name)
                self.assertIn('-ExifByteOrder=', text, name)
                self.assertIn('#=', text, name)
            self.assertNotIn('only when no minimise keep-set key is present', recipe)
            self.assertNotIn('is deleted by name from the trusted listing', rule)
            self.assertIn('MINIMISE_RENDERING_UNPRESERVED', rule)
            self.assertIn('closed residual proof', rule)
        self.assertIn('PNG:<Keyword>', e5profiles.profile('png')['minimise']['rule'])
        self.assertIn('-PNG:all=', e5profiles.profile('png')['removal']['forbiddenArguments'])
        self.assertIn('-EXIF:all=', e5profiles.profile('tiff')['removal']['forbiddenArguments'])
        self.assertIn('heifSpecDraftOnly', e5profiles.profile('heif')['limitations'])
        self.assertIn('tiffUnknownTagSemanticsNotInterpreted', e5profiles.profile('tiff')['limitations'])

    def test_every_refusal_code_a_locator_can_raise_is_declared(self):
        declared = {code for n in e5profiles.containers() for code in e5profiles.profile(n)['refusalCodes']}
        source = ''.join((EXIF_DIR / name).read_text() for name in ('e5tiff.py', 'e5png.py', 'e5riff.py', 'e5heif.py'))
        import re
        used = set(re.findall(r"'((?:TIFF|PNG|RIFF|WEBP|HEIF|DNG|RAW)_[A-Z_]+)'", source))
        used -= {'INFO_IGNORED_NEXT'}
        self.assertEqual(set(), used - declared)

    def test_recognised_tag_sets_are_pinned_data(self):
        document = json.loads((EXIF_DIR / 'tifftags.json').read_text())
        self.assertEqual({'image', 'exif', 'gps', 'interop'}, set(document['contexts']))
        self.assertIn('0xC612', document['contexts']['image'])         # DNGVersion
        self.assertIn('0x0201', document['contexts']['image'])
        self.assertNotIn('0x0201', document['contexts']['exif'])
        self.assertEqual('tiffRecognisedTagSetConservative', document['limitation'])


class Dispatch(unittest.TestCase):
    def test_detection_is_by_signature(self):
        self.assertEqual(['tiff', 'tiff', 'png', 'webp', 'heif', None], [e5profiles.detect(d) for d in (f.plain_tiff('<'), f.plain_tiff('>'), f.basic_png(), f.riff(f.ck(b'VP8 ', f.vp8())),
                                                                                                         f.heic_basic(), b'\xff\xd8\xff\xe0' + bytes(20))])

    def test_each_container_reaches_its_locator(self):
        for data, container in ((f.plain_tiff('<'), 'tiff'), (f.dng('<')[0], 'dng'), (f.basic_png(), 'png'), (f.riff(f.ck(b'VP8 ', f.vp8())), 'webp'), (f.heic_basic(), 'heif')):
            found = e5locate.locate(data)
            self.assertEqual(container, found['container'])
            self.assertEqual({'exif', 'xmp', 'iptc'}, {s['family'] for s in found['slots']})
            self.assertTrue(found['protected'])

    def test_x6_a_tif_that_is_really_a_png_is_located_as_png(self):
        found = e5locate.locate(f.basic_png(), 'folder/photo.tif')
        self.assertEqual('png', found['container'])
        self.assertIn('EXTENSION_MISMATCH', found['notes'])
        self.assertEqual({'suffix': '.tif', 'detected': 'png'}, found['extension'])
        for name, data in (('a.png', f.basic_png()), ('a.webp', f.riff(f.ck(b'VP8 ', f.vp8()))), ('a.heic', f.heic_basic()), ('a.tiff', f.plain_tiff('>')), ('a.TIF', f.plain_tiff('<'))):
            self.assertNotIn('EXTENSION_MISMATCH', e5locate.locate(data, name)['notes'], name)
        self.assertNotIn('EXTENSION_MISMATCH', e5locate.locate(data, 'no-suffix')['notes'])
        self.assertNotIn('EXTENSION_MISMATCH', e5locate.locate(f.basic_png(), 'a.unknownsuffix')['notes'])

    def test_unsupported_signatures_stay_unsupported_by_name(self):
        for data in (b'GIF89a' + bytes(40), b'\x00\x00\x00\x0cJXL \r\n\x87\n' + bytes(20), bytes(40)):
            with self.assertRaises(common.Refused) as caught:
                e5locate.locate(data)
            self.assertEqual('UNSUPPORTED_MEDIA', caught.exception.code)
        with self.assertRaises(common.Refused) as caught:
            e5locate.locate(f.bigtiff())
        self.assertEqual('TIFF_BIG_UNSUPPORTED', caught.exception.code)

    def test_size_bounds_come_from_the_profile(self):
        big = bytearray(65 * 1024 * 1024)
        big[:len(f.basic_png()[:20])] = f.basic_png()[:20]
        with self.assertRaises(common.Refused) as caught:
            e5locate.locate(big)
        self.assertEqual('PHOTO_RESOURCE_LIMIT', caught.exception.code)

    def test_x7_jpeg_is_untouched_by_the_dispatcher(self):
        data = jpegs.jpeg(make='A', model='M', xmp='<dc:title><rdf:Alt><rdf:li xml:lang="x-default">T</rdf:li></rdf:Alt></dc:title>', iptc=[(2, 5, b'T')])
        old, new = containers.locate(data), e5locate.locate(data, 'x.jpg')
        for key in ('container', 'exif', 'xmp', 'iptc', 'frame', 'notes', 'scans'):
            self.assertEqual(old[key], new[key], key)
        self.assertIsNone(new['protected'])                        # JPEG protection stays with jpegwrite.preservation
        self.assertEqual({'exif': 'present', 'xmp': 'present', 'iptc': 'present'}, {s['family']: s['state'] for s in new['slots']})
        self.assertIn('EXTENSION_MISMATCH', e5locate.locate(data, 'x.png')['notes'])

    def test_sidecars_keep_their_existing_locator(self):
        found = e5locate.locate(f.XMP_TEXT, 'a.xmp')
        self.assertEqual(('xmp', [f.XMP_TEXT]), (found['container'], found['xmp']))


class SharedDecoders(unittest.TestCase):
    def test_one_xmp_and_exif_decoder_serves_every_container(self):
        for data in (f.basic_png(), f.riff(f.vp8x(0x0C), f.ck(b'VP8 ', f.vp8()), f.webp_exif(), f.webp_xmp()), f.heic_basic(with_metadata=True)):
            decoded = e5payloads.decode(e5locate.locate(data))
            self.assertEqual('ok', decoded['exif'][0][0])
            self.assertEqual({'x-default': 'Quarry gate'}, decoded['xmp'][0][1]['dc:title'][0]['value'])

    def test_decoder_errors_stay_per_payload(self):
        found = {'exif': [b'II+\0nope'], 'xmp': [b'<!DOCTYPE x>'], 'iptc': [b'Photoshop 3.0\0' + b'garbage-garbage-garbage']}
        decoded = e5payloads.decode(found)
        self.assertEqual(['INVALID_EXIF_STRUCTURE', 'XMP_DOCTYPE_REFUSED', 'IPTC_MALFORMED'], [decoded['exif'][0][1], decoded['xmp'][0][1], decoded['iptc'][0][1]])

    def test_photoshop_wrapping_of_bare_iim(self):
        body = e5payloads.photoshop_body_from_iim(b'\x1c\x02\x05\x00\x04Gate')
        self.assertEqual(b'Photoshop 3.0\0' + b'8BIM\x04\x04\0\0\0\0\0\x09\x1c\x02\x05\x00\x04Gate\0', body)
        self.assertTrue(e5payloads.has_iptc_resource(body))
        self.assertFalse(e5payloads.has_iptc_resource(e5payloads.photoshop_body_from_resources(b'8BIM\x03\xed\0\0\0\0\0\x02ab')))
        self.assertIsNone(e5payloads.has_iptc_resource(b'Photoshop 3.0\0' + b'garbage-garbage-garbage'))

    def test_bounded_inflate(self):
        import zlib
        self.assertEqual(b'abc', e5payloads.inflate_bounded(zlib.compress(b'abc'), 10))
        for data, code in ((zlib.compress(b'a' * 100), 'XMP_BOUND'), (b'garbage', 'XMP_MALFORMED'), (zlib.compress(b'abc')[:-3], 'XMP_MALFORMED')):
            with self.assertRaises(e5payloads.Problem) as caught:
                e5payloads.inflate_bounded(data, 10)
            self.assertEqual(code, caught.exception.code)

    def test_raw_profile_text(self):
        payload = b'Exif\0\0abc'
        self.assertEqual(('exif', payload), e5payloads.raw_profile(b'\nexif\n%8d\n' % len(payload) + payload.hex().encode()))
        self.assertIsNone(e5payloads.raw_profile(b'\nexif\n       3\n' + payload.hex().encode()))
        self.assertIsNone(e5payloads.raw_profile(b'no newlines'))

    def test_the_tiff_walker_is_the_existing_one(self):
        from schemaxis.adaptors.exiftool import tiff
        self.assertIs(tiff.walk, __import__('schemaxis.adaptors.exiftool.e5payloads', fromlist=['tiff']).tiff.walk)
        self.assertEqual('II', e5tiff.locate(f.plain_tiff('<'))['layout']['byteOrder'])


if __name__ == '__main__':
    unittest.main()
