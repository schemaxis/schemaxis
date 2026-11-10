"""Host tests of the generalised preservation proof P (``e5proof.preserve``) over every E5 container, with byte-level mutants."""
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import exiftool_e3_fixtures as jpegs  # noqa: E402
import exiftool_e5_fixtures as f  # noqa: E402
from schemaxis.adaptors.exiftool import e5proof  # noqa: E402

ARTIST = ('tiff/entry', 'IFD0:0x013b')
VP8 = f.ck(b'VP8 ', f.vp8())
E, X = f.webp_exif(), f.webp_xmp()


def paths(result):
    return [(x['code'], x['path']) for x in result['faults']]


class Png(unittest.TestCase):
    def test_slot_changes_and_moves_pass_and_protected_changes_do_not(self):
        before = f.basic_png()
        moved = f.png(f.ihdr(), f.xmp_itxt(), f.GAMA, f.chunk(b'eXIf', f.exif_stream('<', 'Someone else')), f.text_chunk(b'Comment', b'plain text'), f.IDAT, f.IEND)
        self.assertEqual({'ok': True, 'container': 'png', 'faults': []}, e5proof.preserve(before, moved))
        dropped = f.png(f.ihdr(), f.text_chunk(b'Comment', b'plain text'), f.IDAT, f.IEND)
        self.assertEqual([('PRESERVATION_MISMATCH', 'png/ancillary[gAMA#0]')], paths(e5proof.preserve(before, dropped)))
        self.assertTrue(e5proof.preserve(before, dropped, allow=(('png/ancillary', 'gAMA#0'),))['ok'])

    def test_a_damaged_output_is_a_fault_with_the_locator_code(self):
        data = bytearray(f.basic_png())
        data[data.index(b'IDAT') + 6] ^= 0xFF
        self.assertEqual([('PNG_CRC_INVALID', 'output')], paths(e5proof.preserve(f.basic_png(), bytes(data))))

    def test_new_structure_faults_in_the_output_are_reported_once(self):
        after = f.png(f.ihdr(), f.GAMA, f.text_chunk(b'Comment', b'plain text'), f.IDAT, f.chunk(b'eXIf', f.exif_stream()), f.IEND)
        result = e5proof.preserve(f.basic_png(metadata=False), after)
        self.assertEqual(1, paths(result).count(('PNG_METADATA_AFTER_IDAT', 'output')))


class MakerNote(unittest.TestCase):
    """D-3: a maker note that moved with the Exif data is proved equal only by the relocation-aware comparison of a plain IFD; anything else that changed is MAKERNOTE_CHANGED."""

    @staticmethod
    def note(where, value=b'ABCDEFG\0', second=7):
        """A two-entry plain IFD (tag 1 SHORT inline, tag 6 ASCII with an offset relative to the TIFF header) as the maker note of a DNG-like TIFF, placed at file offset ``where``."""
        table_end = 2 + 12 * 2 + 4
        return (struct.pack('<H', 2) + struct.pack('<HHI', 1, 3, 1) + struct.pack('<HH', second, 0) + struct.pack('<HHI', 6, 2, len(value)) + struct.pack('<I', where + table_end)
                + struct.pack('<I', 0) + value)

    def build(self, extra_entries=(), value=b'ABCDEFG\0', opaque=None):
        import exiftool_e5_time_fixtures as t
        import author_exiftool_fixtures as a
        where = 0
        for _ in range(2):                   # the first pass finds where the note lands, the second writes its offsets for that place
            payload = self.note(where, value) if opaque is None else opaque
            data = t.tiff(dng=True, exif_extra=[a.undefined_entry(0x927C, payload)] + list(extra_entries))
            at = data.index(payload)
            where = at
        return data

    def test_a_relocated_plain_ifd_maker_note_is_proved_equal_and_declared(self):
        import author_exiftool_fixtures as a
        before = self.build()
        after = self.build(extra_entries=[a.ascii_entry(0xA430, 'owner')])           # one more Exif entry moves the note by twelve bytes
        self.assertEqual(after.index(b'ABCDEFG') - before.index(b'ABCDEFG'), 12)         # the note's value really moved by the size of the one added Exif entry
        added = (('tiff/entry', 'IFD0/Exif:0xa430'),)
        result = e5proof.preserve(before, after, allow=added)
        self.assertEqual((result['ok'], result['faults']), (True, []))
        self.assertEqual(len(result['effects']), 1)                                       # a declared side effect, never silent
        self.assertIn(result['effects'][0]['rule'], ('S8-makerNoteRebuilt', 'S8-makerNoteRelocated'))

    def test_a_changed_maker_note_value_is_never_verified(self):
        import author_exiftool_fixtures as a
        before = self.build()
        after = self.build(extra_entries=[a.ascii_entry(0xA430, 'owner')], value=b'ABCDEFX\0')
        result = e5proof.preserve(before, after, allow=(('tiff/entry', 'IFD0/Exif:0xa430'),))
        self.assertEqual([c for c, _ in paths(result)], ['MAKERNOTE_CHANGED'])

    def test_a_changed_opaque_maker_note_is_never_verified(self):
        import author_exiftool_fixtures as a
        before = self.build(opaque=b'OPAQUE-NOTE-0123456')
        after = self.build(opaque=b'OPAQUE-NOTE-012345X', extra_entries=[a.ascii_entry(0xA430, 'owner')])
        result = e5proof.preserve(before, after, allow=(('tiff/entry', 'IFD0/Exif:0xa430'),))
        self.assertEqual([c for c, _ in paths(result)], ['MAKERNOTE_CHANGED'])


class Tiff(unittest.TestCase):
    def test_planned_target_only(self):
        before, after = f.plain_tiff('<', creator='A. Mason'), f.plain_tiff('<', creator='A. Mason and a longer co-author list')
        self.assertEqual([('PRESERVATION_MISMATCH', 'tiff/entry[IFD0:0x013b]')], paths(e5proof.preserve(before, after)))
        self.assertTrue(e5proof.preserve(before, after, allow=(ARTIST,))['ok'])

    def test_strip_bytes_and_byte_order_are_protected(self):
        data = f.plain_tiff('<')
        flipped = bytearray(data)
        flipped[data.index(f.STRIP)] ^= 1
        self.assertEqual([('PRESERVATION_MISMATCH', 'tiff/extent[IFD0:strip[0]]')], paths(e5proof.preserve(data, bytes(flipped))))
        swapped = f.plain_tiff('>')
        self.assertIn(('PRESERVATION_MISMATCH', 'tiff/header[byteOrder]'), paths(e5proof.preserve(data, swapped, allow=(ARTIST,))))

    def test_container_identity_is_part_of_the_proof(self):
        dng = f.dng('<')[0]
        result = e5proof.preserve(dng, f.plain_tiff('<'))
        self.assertIn(('PRESERVATION_MISMATCH', 'container'), paths(result))
        self.assertFalse(result['ok'])

    def test_dng_color_matrix_and_private_data(self):
        data, raw, matrix = f.dng('<')
        mutant = data.replace(matrix, matrix[:8] + b'\x7f' + matrix[9:])
        self.assertEqual([('PRESERVATION_MISMATCH', 'tiff/entry[IFD0:0xc621]')], paths(e5proof.preserve(data, mutant)))
        self.assertEqual([('PRESERVATION_MISMATCH', 'tiff/entry[IFD0:0xc634]')], paths(e5proof.preserve(data, data.replace(b'VendorPrivate', b'VendorPrivatX'))))

    def test_interop_ifd_mutant(self):
        self.assertEqual([('PRESERVATION_MISMATCH', 'tiff/entry[IFD0/Exif/Interop:0x0001]')], paths(e5proof.preserve(f.interop_tiff('<', b'R98'), f.interop_tiff('<', b'R03'))))


class Webp(unittest.TestCase):
    def test_creation_and_removal_pass_with_the_layout_proof(self):
        self.assertTrue(e5proof.preserve(f.riff(VP8), f.riff(f.vp8x(0x0C), VP8, E, X))['ok'])
        self.assertTrue(e5proof.preserve(f.riff(f.vp8x(0x0C), VP8, E, X), f.riff(VP8))['ok'])

    def test_w9_alpha_flag_mutant_and_w10_unknown_chunk_output(self):
        flagged = e5proof.preserve(f.riff(f.vp8x(0x0C), VP8, E, X), f.riff(f.vp8x(0x1C), VP8, E, X))
        self.assertEqual([('PRESERVATION_MISMATCH', 'riff/layout')], paths(flagged))
        refused = e5proof.preserve(f.riff(f.vp8x(0x0C), VP8, E, X, f.UNKNOWN), f.riff(VP8, f.UNKNOWN))
        self.assertIn(('WEBP_LAYOUT_INVALID_AFTER_WRITE', 'riff/layout'), paths(refused))

    def test_chunk_bytes_are_protected_including_padding(self):
        before = f.riff(f.vp8x(0x0C), VP8, E, X)
        after = bytearray(before)
        after[after.index(b'\xaa' * 7) + 2] ^= 1
        result = e5proof.preserve(before, bytes(after))
        self.assertEqual({'PRESERVATION_MISMATCH'}, {x['code'] for x in result['faults']})
        self.assertIn('riff/chunk[VP8 #0]', [x['path'] for x in result['faults']])


class Heif(unittest.TestCase):
    def test_metadata_added_after_the_image_passes(self):
        self.assertTrue(e5proof.preserve(f.heic_basic(with_metadata=True), f.heic_basic(with_metadata=True))['ok'])

    def test_a_reference_the_input_did_not_have_is_reported(self):
        items = [{'id': 1, 'type': b'hvc1', 'payload': b'OPAQUE-HVC1-IMAGE-24BYTES'[:24]}]
        before = f.heic(items)
        after = f.heic(items, refs=[(b'thmb', 1, [9])])
        result = e5proof.preserve(before, after)
        self.assertIn(('HEIF_REFERENCE_INVALID', 'output'), paths(result))
        self.assertIn(('PRESERVATION_MISMATCH', 'heif/iref[0]'), paths(result))

    def test_hidden_flag_and_image_payload(self):
        data = bytearray(f.heic_basic())
        flipped = bytearray(data)
        flipped[data.index(b'infe') + 7] |= 1
        self.assertEqual([('PRESERVATION_MISMATCH', 'heif/infe[1]')], paths(e5proof.preserve(bytes(data), bytes(flipped))))


class Boundaries(unittest.TestCase):
    def test_jpeg_is_never_silently_passed(self):
        data = jpegs.jpeg(make='A', model='M')
        with self.assertRaises(ValueError):
            e5proof.preserve(data, data)


if __name__ == '__main__':
    unittest.main()
