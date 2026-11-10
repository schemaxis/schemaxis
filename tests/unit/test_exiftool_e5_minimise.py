"""PNG and WebP ``minimise`` (AM-17 semantics with the AM-19 method, cases G-6, G-10, W-7, W-11) and the AM-16R VP8X removal layouts, against a genuine ExifTool 13.55 (SCHEMAXIS_EXIFTOOL).

Every expected value is a literal written here: the bytes of the hand-built fixtures, the chunks that must stay byte for byte (gAMA, iCCP, tIME, the bitstream, ICC, alpha), the chunks that must
go, the exact values the keep-set preserves and, since AM-19, the exact native argument array of each run: the E2 closed reset (``-EXIF:all=``, ``-XMP:all=``, a PNG text chunk by its ``PNG:<Keyword>`` key) followed by the keep-set write-back
as numeric assignments in the capture's byte order, and never ``-all=`` or ``-PNG:all=``. Host planning cases need no native process. Nothing decodes a pixel; nothing claims anonymisation, privacy or authenticity.
"""
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
import exiftool_e5_fixtures as f  # noqa: E402
import exiftool_e5_time_fixtures as t  # noqa: E402
import author_exiftool_fixtures as a  # noqa: E402
from schemaxis.adaptors.exiftool import adaptor, e5locate, edits, removal, records  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402
from test_exiftool_e5_ops import entry, payloads  # noqa: E402

EXIFTOOL = os.environ.get('SCHEMAXIS_EXIFTOOL')
V = 'schemaxis.exiftool/1'
MINIMISE = {'version': V, 'operation': 'removeMetadata', 'categories': ['minimise']}
VP8 = f.ck(b'VP8 ', f.vp8())
VP8L_ALPHA = f.ck(b'VP8L', f.vp8l(alpha=True))
ICCP = f.ck(b'ICCP', t.valid_icc())
ALPH = f.ck(b'ALPH', f.ALPH)
XMP_TITLE = a.xmp_packet('<dc:title><rdf:Alt><rdf:li xml:lang="x-default">Quarry gate</rdf:li></rdf:Alt></dc:title>')
EXIF_ARTIST = f.ck(b'EXIF', f.exif_stream())


def keep(data):
    return {'png': sorted(r[1] for r in e5locate.locate(data)['protected'])}


@unittest.skipUnless(EXIFTOOL and Path(EXIFTOOL).exists(), 'a real ExifTool 13.55 is needed (SCHEMAXIS_EXIFTOOL)')
class Native(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='e5-minimise-')).resolve()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.runs = 0

    def run_op(self, name, data, document=None):
        type(self).runs += 1
        path = self.tmp / name
        path.write_bytes(data)
        out = self.tmp / ('run%d' % self.runs)
        doc = {**(document or MINIMISE), 'media': {'items': [{'id': 'x', 'path': str(path)}]}}
        result = adaptor.run(doc, out, executable=EXIFTOOL, timeout=300)
        self.assertTrue(result['verified'])
        self.assertEqual(adaptor.verify(out, executable=EXIFTOOL)['nativeReplay'], 'fresh-replay-matched')
        output = next(p for p in sorted((out / 'photos').glob('x.*')) if not p.name.endswith('.metadata.json')).read_bytes()
        row = json.loads((out / 'removal-report.json').read_text())['items'][0]
        return out, result, output, row

    def refusal(self, name, data, document=None):
        path = self.tmp / name
        path.write_bytes(data)
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.run({**(document or MINIMISE), 'media': {'items': [{'id': 'x', 'path': str(path)}]}}, self.tmp / ('refused-' + name), executable=EXIFTOOL, timeout=300)
        self.assertEqual(caught.exception.fault.code, 'NO_USABLE_ITEMS')
        first = caught.exception.fault.observed['firstFaults'][0]
        self.assertFalse((self.tmp / ('refused-' + name) / 'photos').exists())       # nothing was written
        return first

    # ------------------------------------------------------------------ PNG
    def test_g6_png_minimise_keeps_gamma_profile_and_orientation_and_removes_exif_xmp_and_text(self):
        out, result, data, row = self.run_op('g6.png', t.png_g6())
        self.assertEqual((result['written'], result['refused'], result['failed']), (1, 0, 0))
        self.assertEqual(row['status'], 'written')
        self.assertEqual(data.count(f.GAMA), 1)                                                   # gAMA bytes unchanged
        self.assertEqual(data.count(f.chunk(b'tIME', bytes([7, 234, 3, 1, 12, 0, 0]))), 1)      # the modification time chunk is kept (declared residual)
        self.assertIn(b'iCCP', data)
        self.assertNotIn(b'plain text', data)                                                     # the tEXt Comment is gone
        self.assertEqual(payloads(data).xmp[0], 'absent')
        self.assertEqual(data.count(f.IDAT + f.IEND), 1)
        state = payloads(data).exif
        self.assertEqual(sorted(state[1]['ifds']), ['IFD0'])                                      # no ExifIFD, no GPS IFD
        self.assertEqual((entry(data, 'IFD0', 0x0112).values(), entry(data, 'IFD0', 0x0213).values()), ([6], [2]))
        self.assertEqual(sorted(e.tag for e in state[1]['ifds']['IFD0'][1]), [0x0112, 0x0213])
        self.assertFalse(any(k.endswith('PNG:Gamma') for k in row['proofs']['N']['targets']))     # N: the gamma was not touched
        self.assertEqual(row['proofs']['problems'], 0)
        self.assertEqual(row['arguments'], ['-EXIF:all=', '-XMP:all=', '-PNG:Comment=', '-ExifByteOrder=Little-endian', '-IFD0:Orientation#=6', '-IFD0:YCbCrPositioning#=2'])        # AM-19: reset, text by keyword, keep-set written back

    def test_g10_png_orientation_6_stays_and_the_gps_goes(self):
        _, _, data, row = self.run_op('g10.png', t.png_g6(ycbcr=None))
        self.assertEqual(entry(data, 'IFD0', 0x0112).values(), [6])
        self.assertNotIn('GPS', payloads(data).exif[1]['ifds'])
        self.assertIsNone(entry(data, 'GPS', 2))
        self.assertEqual(row['removed']['minimise']['preserved'], {'Orientation': 6})
        self.assertEqual(row['arguments'], ['-EXIF:all=', '-XMP:all=', '-PNG:Comment=', '-ExifByteOrder=Little-endian', '-IFD0:Orientation#=6'])
        self.assertEqual(data.count(f.GAMA), 1)                                                   # gamma and image data are not touched by the reset
        self.assertEqual(data.count(f.IDAT + f.IEND), 1)

    def test_a_png_without_orientation_loses_the_whole_exif_block(self):
        _, _, data, row = self.run_op('plain.png', t.png_g6(orientation=None, ycbcr=None))
        self.assertEqual(payloads(data).exif[0], 'absent')
        self.assertEqual(row['removed']['minimise']['preserved'], {})
        self.assertNotIn(b'eXIf', data)

    def test_a_png_with_nothing_to_minimise_is_published_unchanged_with_that_reason(self):
        original = f.basic_png(metadata=False)
        original = f.png(f.ihdr(), f.GAMA, f.IDAT, f.IEND)
        _, _, data, row = self.run_op('bare.png', original)
        self.assertEqual((data, row['removed']['nothingToRemove']), (original, True))

    # ------------------------------------------------------------------ WebP
    def test_w7_webp_minimise_removes_vp8x_and_leaves_exactly_the_bitstream(self):
        before = f.riff(f.vp8x(0x0C), VP8, f.ck(b'EXIF', t.stream()), f.ck(b'XMP ', XMP_TITLE))
        out, _, data, row = self.run_op('w7.webp', before)
        self.assertEqual(data, f.riff(VP8))                                                       # VP8X removed, the VP8 chunk and its pad byte are equal, canvas = bitstream
        self.assertEqual(row['removed']['minimise']['vp8x'], 'removed')
        sides = [s['rule'] for s in row['proofs']['N']['sideEffects']]
        self.assertIn('E5-webpVp8xRemoved', sides)
        self.assertEqual(row['arguments'], ['-EXIF:all=', '-XMP:all='])                            # nothing is kept, so nothing is written back

    def test_w11_webp_orientation_6_stays_with_the_icc_profile_and_the_gps_goes(self):
        exif = t.exif_with(orientation=6, ycbcr=2)
        before = f.riff(f.vp8x(0x2C), ICCP, VP8, f.ck(b'EXIF', exif), f.ck(b'XMP ', XMP_TITLE))
        _, _, data, row = self.run_op('w11.webp', before)
        self.assertEqual((data.count(ICCP), data.count(VP8)), (1, 1))
        self.assertIn(b'VP8X\x0a\x00\x00\x00\x28', data)                                          # flags 0x20 (ICC) | 0x08 (EXIF); XMP flag cleared
        self.assertEqual(payloads(data).xmp[0], 'absent')
        self.assertEqual(entry(data, 'IFD0', 0x0112).values(), [6])
        self.assertIsNone(entry(data, 'GPS', 2))
        self.assertEqual(row['arguments'], ['-EXIF:all=', '-XMP:all=', '-ExifByteOrder=Little-endian', '-IFD0:Orientation#=6', '-IFD0:YCbCrPositioning#=2'])
        self.assertEqual(row['removed']['minimise']['vp8x'], 'kept')                                # AM-16R at plan: the EXIF chunk stays, so VP8X stays

    # ------------------------------------------------------------------ a keep-set value that cannot be kept faithfully is refused by name before native
    def test_an_orientation_outside_the_understood_values_is_refused_rendering_unpreserved(self):
        first = self.refusal('o9.png', t.png_g6(orientation=9))
        self.assertEqual((first['code'], first['observed']['tag']), ('MINIMISE_RENDERING_UNPRESERVED', 'Orientation'))

    # ------------------------------------------------------------------ AM-16R: ordinary removal layouts
    def remove(self, name, data, categories=('descriptive', 'rights')):
        return self.run_op(name, data, {'version': V, 'operation': 'removeMetadata', 'categories': list(categories)})

    def test_w12_iccp_keeps_vp8x_with_the_icc_flag_only(self):
        _, _, data, _ = self.remove('w12.webp', f.riff(f.vp8x(0x2C), ICCP, VP8, EXIF_ARTIST, f.ck(b'XMP ', XMP_TITLE)))
        self.assertEqual(data, f.riff(f.vp8x(0x20), ICCP, VP8))

    def test_w13_alph_keeps_vp8x_with_the_alpha_flag_only(self):
        _, _, data, _ = self.remove('w13.webp', f.riff(f.vp8x(0x1C), ALPH, VP8, EXIF_ARTIST, f.ck(b'XMP ', XMP_TITLE)))
        self.assertEqual(data, f.riff(f.vp8x(0x10), ALPH, VP8))

    def test_w14_anim_keeps_vp8x_with_the_animation_flag_only(self):
        _, _, data, _ = self.remove('w14.webp', f.riff(f.vp8x(0x0E), f.ck(b'ANIM', b'\0' * 6), f.anmf(), f.anmf(), EXIF_ARTIST, f.ck(b'XMP ', XMP_TITLE)))
        self.assertEqual(data, f.riff(f.vp8x(0x02), f.ck(b'ANIM', b'\0' * 6), f.anmf(), f.anmf()))

    def test_w17b_a_vp8l_bitstream_that_carries_alpha_lets_vp8x_go(self):
        _, _, data, _ = self.remove('w17b.webp', f.riff(f.vp8x(0x18), VP8L_ALPHA, EXIF_ARTIST))
        self.assertEqual(data, f.riff(VP8L_ALPHA))

    def test_w10_an_unknown_chunk_is_refused_at_plan_before_any_native_process(self):
        first = self.refusal('w10.webp', f.riff(f.vp8x(0x0C), VP8, EXIF_ARTIST, f.ck(b'XMP ', XMP_TITLE), f.UNKNOWN), {'version': V, 'operation': 'removeMetadata', 'categories': ['descriptive', 'rights']})
        self.assertEqual(first['code'], 'WEBP_METADATA_REMOVAL_LAYOUT_UNSUPPORTED')
        self.assertEqual(first['location'], '$.categories')
        self.assertIn('exactly one VP8 or VP8L bitstream', first['message'])
        self.assertFalse(any((self.tmp / ('refused-w10.webp')).glob('write-*')))              # no write stage ran

    def test_an_icc_flag_without_an_icc_chunk_is_refused_at_plan(self):
        first = self.refusal('w10b.webp', f.riff(f.vp8x(0x2C), VP8, EXIF_ARTIST, f.ck(b'XMP ', XMP_TITLE)), {'version': V, 'operation': 'removeMetadata', 'categories': ['descriptive', 'rights']})
        self.assertEqual(first['code'], 'WEBP_METADATA_REMOVAL_LAYOUT_UNSUPPORTED')


if __name__ == '__main__':
    unittest.main()
