"""Host tests of the E5 WebP locator and the AM-16R VP8X prediction and post-write proof (cases W-1..W-19m).

Fixtures are literal RIFF bytes with opaque bitstream payloads; the expected chunk lists and flags of every AM-16R row are written here by hand.
"""
import hashlib
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import exiftool_e5_fixtures as f  # noqa: E402
from schemaxis.adaptors.exiftool import e5common as common, e5payloads, e5riff  # noqa: E402

VP8 = f.ck(b'VP8 ', f.vp8())
VP8L = f.ck(b'VP8L', f.vp8l())
VP8L_ALPHA = f.ck(b'VP8L', f.vp8l(alpha=True))
ICCP = f.ck(b'ICCP', f.ICC)
ALPH = f.ck(b'ALPH', f.ALPH)
ANIM = f.ck(b'ANIM', bytes(6))
E, X = f.webp_exif(), f.webp_xmp()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def codes(found):
    return [r['code'] for r in found['write']['refusals']]


def states(found):
    return {s['family']: s['state'] for s in found['slots']}


def facts(data):
    return e5riff.facts(data, e5riff.parse(data))


def fault_codes(before, after):
    return [x['code'] for x in e5riff.prove_layout(before, after)]


class WebpLocator(unittest.TestCase):
    def test_w1_simple_lossy(self):
        data = f.riff(VP8)
        found = e5riff.locate(data)
        self.assertEqual('webp', found['container'])
        self.assertEqual('simple-lossy', found['form'])
        self.assertEqual({'width': 3, 'height': 2, 'bitstream': 'VP8'}, found['frame'])
        self.assertEqual({'exif': 'absent', 'xmp': 'absent', 'iptc': 'absent'}, states(found))
        self.assertEqual([('riff/chunk', 'VP8 #0', 8 + 17 + 1, sha(VP8))], found['protected'])         # 17 payload bytes plus one pad byte
        self.assertTrue(found['write']['admissible'])

    def test_w2_simple_lossless(self):
        found = e5riff.locate(f.riff(VP8L))
        self.assertEqual('simple-lossless', found['form'])
        self.assertEqual({'width': 3, 'height': 2, 'bitstream': 'VP8L'}, found['frame'])
        self.assertEqual([('riff/chunk', 'VP8L#0', 8 + 8, sha(VP8L))], found['protected'])

    def test_w3_extended_with_alpha_and_unknown_chunk(self):
        found = e5riff.locate(f.riff(f.vp8x(0x10), ALPH, VP8, f.UNKNOWN))
        self.assertEqual('extended', found['form'])
        self.assertEqual([('riff/vp8x', 'canvas+flags'), ('riff/chunk', 'ALPH#0'), ('riff/chunk', 'VP8 #0'), ('riff/chunk', 'zzzz#0')], [(r, k) for r, k, _, _ in found['protected']])
        self.assertEqual(0x10, found['frame']['flags'])

    def test_fingerprint_ignores_exif_and_xmp_flags_but_not_the_others(self):
        plain = e5riff.locate(f.riff(f.vp8x(0x00), VP8))
        edited = e5riff.locate(f.riff(f.vp8x(0x0C), VP8, E, X))
        self.assertEqual(plain['protected'], edited['protected'])
        alpha = e5riff.locate(f.riff(f.vp8x(0x10), VP8))
        self.assertNotEqual(plain['protected'], alpha['protected'])

    def test_exif_and_xmp_payloads_are_delivered(self):
        found = e5riff.locate(f.riff(f.vp8x(0x0C), VP8, E, X))
        self.assertEqual([f.exif_stream()], found['exif'])
        self.assertEqual([f.XMP_TEXT], found['xmp'])
        decoded = e5payloads.decode(found)
        self.assertEqual({'x-default': 'Quarry gate'}, decoded['xmp'][0][1]['dc:title'][0]['value'])

    def test_w4_riff_size_mismatch(self):
        data = bytearray(f.riff(VP8))
        data[4:8] = struct.pack('<I', len(data) - 8 + 10)
        with self.assertRaises(common.Refused) as caught:
            e5riff.locate(bytes(data))
        self.assertEqual('RIFF_SIZE_MISMATCH', caught.exception.code)
        longer = e5riff.locate(f.riff(VP8) + b'trailing')
        self.assertEqual(['RIFF_TRAILING_BYTES'], codes(longer))
        self.assertIn('RIFF_TRAILING_BYTES', longer['notes'])

    def test_w5_nonzero_pad_byte(self):
        data = f.riff(VP8)
        pad_at = data.index(b'\xaa' * 7) + 7
        found = e5riff.locate(data[:pad_at] + b'\x01' + data[pad_at + 1:])
        self.assertEqual(['RIFF_PADDING_INVALID'], codes(found))
        self.assertEqual('absent', states(found)['exif'])

    def test_w6_two_xmp_chunks_are_ambiguous(self):
        found = e5riff.locate(f.riff(f.vp8x(0x04), VP8, X, f.ck(b'XMP ', f.XMP_TEXT + b' ')))
        self.assertEqual('ambiguous', states(found)['xmp'])
        self.assertEqual(2, len(found['xmp']))
        self.assertEqual(['WEBP_DUPLICATE_METADATA_CHUNK'], codes(found))

    def test_w8_animated_frames_are_protected_whole(self):
        found = e5riff.locate(f.riff(f.vp8x(0x0E), ANIM, f.anmf(), f.anmf(), E, X))
        self.assertIn('animated', found['notes'])
        self.assertEqual({'width': 3, 'height': 2, 'animated': True, 'flags': 0x0E}, found['frame'])
        self.assertEqual(['ANIM#0', 'ANMF#0', 'ANMF#1'], [k for r, k, _, _ in found['protected'] if r == 'riff/chunk'])

    def test_exif_with_a_leading_exif_header_is_noted_and_refused_for_writing(self):
        prefixed = f.ck(b'EXIF', b'Exif\0\0' + f.exif_stream())
        found = e5riff.locate(f.riff(f.vp8x(0x08), VP8, prefixed))
        self.assertIn('webpExifPrefix', found['notes'])
        self.assertEqual(['WEBP_EXIF_PREFIX_UNSUPPORTED'], codes(found))
        self.assertEqual([f.exif_stream()], found['exif'])

    def test_canvas_must_equal_the_bitstream(self):
        found = e5riff.locate(f.riff(f.vp8x(0x00, 4, 2), VP8))
        self.assertIn('canvasBitstreamMismatch', found['notes'])
        self.assertEqual(['WEBP_CANVAS_MISMATCH'], codes(found))

    def test_short_bitstream_headers_cannot_size_a_created_vp8x(self):
        short = f.riff(f.ck(b'VP8 ', f.vp8()[:12]))
        self.assertEqual(['WEBP_BITSTREAM_HEADER_SHORT'], codes(e5riff.locate(short)))

    def test_layout_without_vp8x_but_with_metadata_chunks(self):
        found = e5riff.locate(f.riff(VP8, E))
        self.assertEqual(['WEBP_LAYOUT_UNSUPPORTED'], codes(found))

    def test_unreadable_and_unsupported_files(self):
        for data, code in ((b'RF64' + bytes(8) + b'WEBP', 'UNSUPPORTED_MEDIA'), (b'RIFF\x04\0\0\0WAVE', 'UNSUPPORTED_MEDIA'), (f.riff(f.ck(b'EXIF', b'x')), 'INVALID_PHOTO_DATA'),
                           (f.riff(f.ck(b'VP8 ', b'\x01' * 20)), 'INVALID_PHOTO_DATA')):
            with self.assertRaises(common.Refused) as caught:
                e5riff.locate(data)
            self.assertEqual(code, caught.exception.code)
        chunks = [f.vp8x(0x00)] + [f.ck(b'junk', b'')] * 1100
        with self.assertRaises(common.Refused) as caught:
            e5riff.locate(f.riff(*chunks, VP8))
        self.assertEqual('PHOTO_RESOURCE_LIMIT', caught.exception.code)


class Vp8xPrediction(unittest.TestCase):
    """AM-16R table: each row lists the input chunks with the metadata the plan deletes, then the expected admission."""

    def predict(self, *chunks):
        return e5riff.predict_vp8x(facts(f.riff(*chunks)))

    def test_rows_that_keep_vp8x(self):
        for name, chunks in (('w12 iccp', (f.vp8x(0x2C), ICCP, VP8, E, X)), ('w13 alph', (f.vp8x(0x1C), ALPH, VP8, E, X)),
                             ('w14 anim', (f.vp8x(0x0E), ANIM, f.anmf(), f.anmf(), E, X)), ('w15 iccp_unk', (f.vp8x(0x2C), ICCP, VP8, E, X, f.UNKNOWN)),
                             ('w15b alph_unk', (f.vp8x(0x1C), ALPH, VP8, E, f.UNKNOWN))):
            outcome = self.predict(*chunks)
            self.assertEqual({'admitted': True, 'vp8x': 'kept', 'code': None, 'reason': None}, outcome, name)

    def test_rows_where_vp8x_is_removed_and_admitted(self):
        for name, chunks in (('w7 plain', (f.vp8x(0x0C), VP8, E, X)), ('w17b vp8l alpha with L', (f.vp8x(0x18), VP8L_ALPHA, E)),
                             ('w17c vp8l alpha without L', (f.vp8x(0x08), VP8L_ALPHA, E))):
            outcome = self.predict(*chunks)
            self.assertEqual((True, 'removed'), (outcome['admitted'], outcome['vp8x']), name)

    def test_rows_refused_at_plan(self):
        for name, chunks in (('w10 unknown chunk', (f.vp8x(0x0C), VP8, E, X, f.UNKNOWN)), ('w16 L flag without alpha', (f.vp8x(0x1C), VP8, E, X)),
                             ('w17 vp8l without alpha but L', (f.vp8x(0x18), VP8L, E)), ('icc flag without chunk', (f.vp8x(0x2C), VP8, E, X)),
                             ('anim flag without chunk', (f.vp8x(0x0E), VP8, E, X))):
            outcome = self.predict(*chunks)
            self.assertEqual((False, 'WEBP_METADATA_REMOVAL_LAYOUT_UNSUPPORTED'), (outcome['admitted'], outcome['code']), name)
            self.assertTrue(outcome['reason'], name)

    def test_files_without_vp8x_need_no_prediction(self):
        self.assertEqual('absent', self.predict(VP8)['vp8x'])

    def test_deleting_only_one_metadata_chunk_keeps_vp8x(self):
        outcome = e5riff.predict_vp8x(facts(f.riff(f.vp8x(0x0C), VP8, E, X)), delete=(b'EXIF',))
        self.assertEqual('kept', outcome['vp8x'])


class Vp8xProof(unittest.TestCase):
    def test_w1_creation_for_simple_lossy_and_lossless(self):
        for stream in (VP8, VP8L):
            before = f.riff(stream)
            self.assertEqual([], fault_codes(before, f.riff(f.vp8x(0x0C), stream, E, X)))

    def test_creation_may_carry_the_alpha_flag_only_for_a_vp8l_alpha_bitstream(self):
        self.assertEqual([], fault_codes(f.riff(VP8L_ALPHA), f.riff(f.vp8x(0x1C), VP8L_ALPHA, E, X)))
        self.assertEqual(['PRESERVATION_MISMATCH'], fault_codes(f.riff(VP8L), f.riff(f.vp8x(0x1C), VP8L, E, X)))
        self.assertEqual(['PRESERVATION_MISMATCH'], fault_codes(f.riff(VP8), f.riff(f.vp8x(0x2C), VP8, E, X)))
        self.assertEqual(['PRESERVATION_MISMATCH'], fault_codes(f.riff(VP8), f.riff(f.vp8x(0x0C, 4, 2), VP8, E, X)))

    def test_w12_to_w15_native_shapes_pass(self):
        for before, after in (((f.vp8x(0x2C), ICCP, VP8, E, X), (f.vp8x(0x20), ICCP, VP8)), ((f.vp8x(0x1C), ALPH, VP8, E, X), (f.vp8x(0x10), ALPH, VP8)),
                              ((f.vp8x(0x0E), ANIM, f.anmf(), f.anmf(), E, X), (f.vp8x(0x02), ANIM, f.anmf(), f.anmf())),
                              ((f.vp8x(0x2C), ICCP, VP8, E, X, f.UNKNOWN), (f.vp8x(0x20), ICCP, VP8, f.UNKNOWN)),
                              ((f.vp8x(0x1C), ALPH, VP8, E, f.UNKNOWN), (f.vp8x(0x10), ALPH, VP8, f.UNKNOWN)), ((f.vp8x(0x0C), VP8, E, X), (VP8,)),
                              ((f.vp8x(0x18), VP8L_ALPHA, E), (VP8L_ALPHA,)), ((f.vp8x(0x08), VP8L_ALPHA, E), (VP8L_ALPHA,))):
            self.assertEqual([], fault_codes(f.riff(*before), f.riff(*after)), after)

    def test_w3_alpha_extended_edit_changes_only_e_and_x(self):
        self.assertEqual([], fault_codes(f.riff(f.vp8x(0x10), ALPH, VP8, f.UNKNOWN), f.riff(f.vp8x(0x1C), ALPH, VP8, E, X, f.UNKNOWN)))

    def test_w18m_mutants_on_the_w12_output(self):
        before = f.riff(f.vp8x(0x2C), ICCP, VP8, E, X)
        self.assertEqual(['WEBP_LAYOUT_INVALID_AFTER_WRITE'], fault_codes(before, f.riff(ICCP, VP8)))                       # VP8X dropped
        self.assertEqual(['PRESERVATION_MISMATCH'], fault_codes(before, f.riff(f.vp8x(0x30), ICCP, VP8)))                  # L bit set
        self.assertEqual({'PRESERVATION_MISMATCH'}, set(fault_codes(before, f.riff(f.vp8x(0x00), VP8))))                    # ICCP dropped, I flag cleared

    def test_w9_mutant_sets_the_alpha_flag(self):
        self.assertEqual(['PRESERVATION_MISMATCH'], fault_codes(f.riff(f.vp8x(0x0C), VP8, E, X), f.riff(f.vp8x(0x1C), VP8, E, X)))

    def test_e_and_x_flags_must_match_the_chunks(self):
        before = f.riff(f.vp8x(0x00), VP8)
        self.assertEqual(['WEBP_FLAGS_INCONSISTENT'], fault_codes(before, f.riff(f.vp8x(0x00), VP8, E)))
        self.assertEqual(['WEBP_FLAGS_INCONSISTENT'], fault_codes(before, f.riff(f.vp8x(0x0C), VP8, E)))

    def test_every_non_metadata_byte_is_protected_padding_included(self):
        before = f.riff(f.vp8x(0x0C), VP8, E, X)
        after = bytearray(f.riff(f.vp8x(0x0C), VP8, E, X))
        after[after.index(b'\xaa' * 7) + 3] ^= 1
        self.assertEqual(['PRESERVATION_MISMATCH'], fault_codes(before, bytes(after)))

    def test_reordering_protected_chunks_is_a_fault(self):
        self.assertEqual({'PRESERVATION_MISMATCH'}, set(fault_codes(f.riff(f.vp8x(0x2C), VP8, ICCP, E, X), f.riff(f.vp8x(0x2C), ICCP, VP8, E, X))))

    def test_size_fields_are_checked_on_the_output(self):
        before = f.riff(f.vp8x(0x0C), VP8, E, X)
        after = bytearray(before)
        after[4:8] = struct.pack('<I', len(after) - 8 + 4)
        self.assertEqual(['RIFF_SIZE_MISMATCH'], fault_codes(before, bytes(after)))

    def test_w19m_the_frozen_oracle_accepts_the_w10_native_output(self):
        """A mutant oracle that treats every VP8X drop as closed accepts ``VP8 zzzz``; the AM-16R proof refuses it."""
        before = f.riff(f.vp8x(0x0C), VP8, E, X, f.UNKNOWN)
        native_output = f.riff(VP8, f.UNKNOWN)

        def frozen(a, b):
            keep = lambda data: e5riff.non_metadata(data, e5riff.parse(data))
            return keep(a) == keep(b)

        self.assertTrue(frozen(before, native_output))
        self.assertEqual(['WEBP_LAYOUT_INVALID_AFTER_WRITE'], fault_codes(before, native_output))

    def test_simple_format_output_must_be_exactly_one_bitstream(self):
        self.assertEqual(['PRESERVATION_MISMATCH', 'WEBP_LAYOUT_INVALID_AFTER_WRITE'], fault_codes(f.riff(f.vp8x(0x0C), VP8, E, X), f.riff(VP8, VP8)))

    def test_unreadable_output_is_a_fault_not_an_exception(self):
        self.assertEqual(['UNSUPPORTED_MEDIA'], fault_codes(f.riff(VP8), b'not a webp file'))


if __name__ == '__main__':
    unittest.main()
