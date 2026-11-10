"""Host tests of the E5 TIFF and DNG locator (cases T-1..T-12, D-1..D-6, the AM-18R matrix and its negative oracle).

Every file is assembled from literal bytes by ``exiftool_e5_fixtures``; expectations are literals or hashes of literal bytes written here, never
produced by the locator under test.
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
from schemaxis.adaptors.exiftool import e5common as common, e5locate, e5payloads, e5tiff  # noqa: E402


def sha(data):
    return hashlib.sha256(data).hexdigest()


def rows(found, role):
    return {key: (length, digest) for r, key, length, digest in found['protected'] if r == role}


def codes(found):
    return [r['code'] for r in found['write']['refusals']]


def states(found):
    return {s['family']: s['state'] for s in found['slots']}


class SimpleTiff(unittest.TestCase):
    def test_strip_tiff_both_byte_orders(self):
        for order, name in (('<', 'II'), ('>', 'MM')):
            found = e5tiff.locate(f.plain_tiff(order))
            self.assertEqual('tiff', found['container'])
            self.assertEqual((3, 2, 1), (found['frame']['width'], found['frame']['height'], found['frame']['pages']))
            self.assertEqual({'exif': 'present', 'xmp': 'absent', 'iptc': 'absent'}, states(found))
            self.assertTrue(found['write']['admissible'], found['write'])
            self.assertEqual((6, sha(bytes([10, 20, 30, 40, 50, 60]))), rows(found, 'tiff/extent')['IFD0:strip[0]'])
            self.assertEqual((2, sha(name.encode())), rows(found, 'tiff/header')['byteOrder'])
            self.assertEqual(f.plain_tiff(order), found['exif'][0])

    def test_entry_rows_carry_raw_value_bytes(self):
        found = e5tiff.locate(f.plain_tiff('<'))
        entries = rows(found, 'tiff/entry')
        expected = struct.pack('<HHI', 0x013B, 2, 9) + b'A. Mason\0'
        self.assertEqual((len(expected), sha(expected)), entries['IFD0:0x013b'])
        self.assertNotIn('IFD0:0x0111', entries)                   # the strip offset is a pointer tag: relocation is free
        self.assertIn('IFD0:0x0117', entries)                      # the byte count stays protected

    def test_relocation_keeps_the_fingerprint_both_orders(self):
        for order in '<>':
            before = e5tiff.locate(f.plain_tiff(order, title='Quarry gate'))
            after = e5tiff.locate(f.plain_tiff(order, title='Quarry gate, north face, seen from the east road'))
            self.assertNotEqual(before['ranges'], after['ranges'])      # the strip really moved
            faults = common.compare(before['protected'], after['protected'], allow=(('tiff/entry', 'IFD0:0x010e'),))
            self.assertEqual([], faults)

    def test_strip_byte_flip_is_reported_at_its_path(self):
        data = bytearray(f.plain_tiff('<'))
        at = bytes(data).index(f.STRIP)
        data[at + 2] ^= 0xFF
        faults = common.compare(e5tiff.locate(f.plain_tiff('<'))['protected'], e5tiff.locate(bytes(data))['protected'])
        self.assertEqual([{'kind': 'changed', 'path': 'tiff/extent[IFD0:strip[0]]', 'role': 'tiff/extent', 'key': 'IFD0:strip[0]'}], faults)

    def test_tiles_are_fingerprinted_by_index(self):
        data, tiles = f.tiled_tiff('>')
        found = e5tiff.locate(data)
        for index, tile in enumerate(tiles):
            self.assertEqual((8, sha(tile)), rows(found, 'tiff/extent')['IFD0:tile[%d]' % index])
        self.assertEqual(4, len(rows(found, 'tiff/extent')))

    def test_three_compressed_strips(self):
        data, strips = f.lzw_tiff('<')
        found = e5tiff.locate(data)
        self.assertEqual({'IFD0:strip[0]': (4, sha(strips[0])), 'IFD0:strip[1]': (5, sha(strips[1])), 'IFD0:strip[2]': (6, sha(strips[2]))}, rows(found, 'tiff/extent'))
        self.assertEqual(5, [e for e in found['frame']['images']][0]['compression'])

    def test_swapped_strips_are_a_fault(self):
        data, strips = f.lzw_tiff('<')
        swapped = data.replace(strips[0], b'\x09' * 4)
        faults = common.compare(e5tiff.locate(data)['protected'], e5tiff.locate(swapped)['protected'])
        self.assertEqual(['tiff/extent[IFD0:strip[0]]'], [x['path'] for x in faults])

    def test_two_pages_are_both_fingerprinted(self):
        found = e5tiff.locate(f.two_page_tiff('<'))
        self.assertEqual(2, found['frame']['pages'])
        self.assertIn('tiffMultiPage', found['notes'])
        self.assertEqual({'IFD0:strip[0]': (6, sha(f.STRIP)), 'IFD1:strip[0]': (3, sha(bytes([70, 80, 90])))}, rows(found, 'tiff/extent'))

    def test_jpeg_thumbnail_ifd_extent_is_protected(self):
        data, thumb = f.jpeg_thumbnail_tiff('>')
        found = e5tiff.locate(data)
        self.assertEqual((6, sha(thumb)), rows(found, 'tiff/extent')['IFD1:jpeg[0]'])
        self.assertIn('tiffJpegThumbnailIfd:IFD1', found['notes'])


class StructureRefusals(unittest.TestCase):
    def test_overlapping_strips_read_but_do_not_write(self):
        found = e5tiff.locate(f.overlapping_strips_tiff('<'))
        self.assertEqual(['TIFF_LAYOUT_OVERLAP'], codes(found))
        self.assertIn('TIFF_LAYOUT_OVERLAP', found['notes'])
        self.assertEqual('present', states(found)['exif'])

    def test_extent_beyond_end_of_file(self):
        found = e5tiff.locate(f.beyond_eof_tiff('<'))
        self.assertEqual(['TIFF_IMAGE_EXTENT_INVALID'], codes(found))
        self.assertEqual({}, rows(found, 'tiff/extent'))

    def test_bigtiff_is_unsupported_by_name(self):
        with self.assertRaises(common.Refused) as caught:
            e5tiff.locate(f.bigtiff())
        self.assertEqual('TIFF_BIG_UNSUPPORTED', caught.exception.code)

    def test_subifd_cycle(self):
        found = e5tiff.locate(f.subifd_cycle_tiff('<'))
        self.assertEqual(['INVALID_EXIF_STRUCTURE'], codes(found))
        self.assertIn('INVALID_EXIF_STRUCTURE:IFD0/SubIFD[0]', found['notes'])

    def test_interop_ifd_is_walked_and_protected(self):
        before = e5tiff.locate(f.interop_tiff('<', b'R98'))
        self.assertIn('IFD0/Exif/Interop:0x0001', rows(before, 'tiff/entry'))
        after = e5tiff.locate(f.interop_tiff('<', b'R03'))
        faults = common.compare(before['protected'], after['protected'])
        self.assertEqual(['tiff/entry[IFD0/Exif/Interop:0x0001]'], [x['path'] for x in faults])

    def test_gps_and_exif_ifds_have_their_own_paths(self):
        found = e5tiff.locate(f.gps_tiff('>'))
        entries = rows(found, 'tiff/entry')
        self.assertIn('IFD0/GPS:0x0001', entries)
        self.assertIn('IFD0/Exif:0x9000', entries)
        self.assertEqual((struct.calcsize('>HHI') + 4, sha(struct.pack('>HHI', 0x9000, 7, 4) + b'0232')), (entries['IFD0/Exif:0x9000'][0], entries['IFD0/Exif:0x9000'][1]))

    def test_chain_longer_than_the_budget(self):
        o = '<'
        def table(off):
            return f.ifd(o, f.base_rows(o, off), 0)
        # 70 chained IFDs, each one a copy of the base table pointing at the single strip
        parts = []
        for i in range(70):
            parts.append(('ifd%d' % i, lambda off, i=i: f.ifd(o, f.base_rows(o, off), off['ifd%d' % (i + 1)] if i < 69 else 0)))
        parts.append(('strip', lambda off: f.STRIP))
        found = e5tiff.locate(f.assemble(o, parts))
        self.assertIn('TIFF_IFD_BUDGET', codes(found))

    def test_maker_raw_signature_and_cfa_without_dng(self):
        data = bytearray(f.plain_tiff('<'))
        cr2 = bytes(data[:8]) + b'CR\x02\0' + bytes(data[12:])
        with self.assertRaises(common.Refused) as caught:
            e5tiff.locate(cr2)
        self.assertEqual('RAW_FORMAT_UNSUPPORTED', caught.exception.code)
        o = '<'
        def table(off):
            rows_ = [r if struct.unpack(o + 'H', r[:2])[0] != 0x106 else f.row(o, 0x106, f.SHORT, 1, f.short(o, 32803)) for r in f.base_rows(o, off)]
            return f.ifd(o, rows_)
        with self.assertRaises(common.Refused) as caught:
            e5tiff.locate(f.assemble(o, [('ifd0', table), ('strip', lambda off: f.STRIP)]))
        self.assertEqual('RAW_FORMAT_UNSUPPORTED', caught.exception.code)

    def test_not_a_tiff(self):
        with self.assertRaises(common.Refused) as caught:
            e5tiff.locate(b'GIF89a......')
        self.assertEqual('UNSUPPORTED_MEDIA', caught.exception.code)

    def test_damaged_ifd0_is_unreadable(self):
        data = bytearray(f.plain_tiff('<'))
        data[4:8] = struct.pack('<I', 5000)
        with self.assertRaises(common.Refused) as caught:
            e5tiff.locate(bytes(data))
        self.assertEqual('INVALID_EXIF_STRUCTURE', caught.exception.code)


class Payloads(unittest.TestCase):
    def test_xmp_and_iptc_payloads_reach_the_shared_readers(self):
        data, iim = f.three_strip_tiff_with_xmp_iptc('<')
        found = e5tiff.locate(data)
        self.assertEqual(f.XMP_TEXT, found['xmp'][0])
        self.assertEqual(b'Photoshop 3.0\0' + b'8BIM' + b'\x04\x04' + b'\0\0' + b'\0\0\0\x09' + iim + b'\0', found['iptc'][0])
        self.assertEqual({'exif': 'present', 'xmp': 'present', 'iptc': 'present'}, states(found))
        decoded = e5payloads.decode(found)
        self.assertEqual({'x-default': 'Quarry gate'}, decoded['xmp'][0][1]['dc:title'][0]['value'])
        self.assertEqual([b'Gate'], decoded['iptc'][0][1][0]['datasets'][(2, 5)])
        self.assertEqual('ok', decoded['exif'][0][0])
        self.assertIn('iptcWrappedFromTiffTag83BB', found['notes'])


class DngCases(unittest.TestCase):
    def test_d1_vendor_private_data_and_raw_strip_are_protected(self):
        data, raw, matrix = f.dng('<')
        found = e5tiff.locate(data)
        self.assertEqual('dng', found['container'])
        entries, extents = rows(found, 'tiff/entry'), rows(found, 'tiff/extent')
        self.assertEqual(struct.calcsize('<HHI') + 18, entries['IFD0:0xc634'][0])
        self.assertEqual(sha(struct.pack('<HHI', 0xC634, 7, 18) + b'VendorPrivate-0123'), entries['IFD0:0xc634'][1])
        self.assertEqual(sha(struct.pack('<HHI', 0xC621, 10, 9) + matrix), entries['IFD0:0xc621'][1])
        self.assertEqual((16, sha(raw)), extents['IFD0/SubIFD[0]:strip[0]'])
        self.assertEqual((6, sha(f.STRIP)), extents['IFD0:strip[0]'])
        self.assertEqual(sha(struct.pack('<HHI', 0x0106, 3, 1) + struct.pack('<H', 32803)), entries['IFD0/SubIFD[0]:0x0106'][1])
        self.assertIn('makerNoteMayIdentifyDevice', found['limitations'])
        self.assertTrue(found['write']['admissible'], found['write'])

    def test_d1_big_endian(self):
        data, raw, matrix = f.dng('>')
        found = e5tiff.locate(data)
        self.assertEqual('dng', found['container'])
        self.assertEqual((16, sha(raw)), rows(found, 'tiff/extent')['IFD0/SubIFD[0]:strip[0]'])

    def test_d5_color_matrix_mutant_fails_at_the_dng_tag_path(self):
        data, raw, matrix = f.dng('<')
        mutant = data.replace(matrix, matrix[:8] + b'\x7f' + matrix[9:])
        faults = common.compare(e5tiff.locate(data)['protected'], e5tiff.locate(mutant)['protected'])
        self.assertEqual(['tiff/entry[IFD0:0xc621]'], [x['path'] for x in faults])

    def test_private_data_mutant_and_raw_mutant(self):
        data, raw, matrix = f.dng('<')
        before = e5tiff.locate(data)['protected']
        self.assertEqual(['tiff/entry[IFD0:0xc634]'], [x['path'] for x in common.compare(before, e5tiff.locate(data.replace(b'VendorPrivate', b'VendorPrivatX'))['protected'])])
        self.assertEqual(['tiff/extent[IFD0/SubIFD[0]:strip[0]]'], [x['path'] for x in common.compare(before, e5tiff.locate(data.replace(raw, raw[::-1]))['protected'])])

    def test_d2_malformed_adobe_makn_is_noted_not_refused(self):
        private = b'Adobe\0MakN' + struct.pack('>I', 4000) + b'II'
        found = e5tiff.locate(f.dng('<', private)[0])
        self.assertIn('dngPrivateDataAdobeMakN', found['notes'])
        self.assertIn('dngPrivateAdobeMakNMalformed', found['notes'])
        self.assertTrue(found['write']['admissible'])          # the native warning gate refuses at write time (case D-2 in the native tests)

    def test_a_dng_version_makes_the_container_never_the_suffix(self):
        data, _, _ = f.dng('<')
        self.assertEqual('dng', e5locate.locate(data, 'photo.tif')['container'])
        self.assertIn('EXTENSION_MISMATCH', e5locate.locate(data, 'photo.tif')['notes'])
        self.assertEqual('tiff', e5locate.locate(f.plain_tiff('<'), 'photo.dng')['container'])
        self.assertIn('EXTENSION_MISMATCH', e5locate.locate(f.plain_tiff('<'), 'photo.dng')['notes'])

    def test_d6_oversized_item_is_a_resource_limit(self):
        big = bytearray(300 * 1024 * 1024)
        big[:8] = f.plain_tiff('<')[:8]
        with self.assertRaises(common.Refused) as caught:
            e5locate.locate(big)
        self.assertEqual('PHOTO_RESOURCE_LIMIT', caught.exception.code)


class UnknownTagAdmission(unittest.TestCase):
    """AM-18R: literal gaps are the byte ranges measured on the native probe fixtures (192-byte files, little-endian)."""

    CASES = {
        'a1': ('TIFF_UNKNOWN_OFFSET_SUSPECT', 'unaccountedBytes', [[134, 150], [156, 192]]),
        'a2': ('TIFF_UNKNOWN_OFFSET_SUSPECT', 'unaccountedBytes', [[142, 150], [156, 192]]),
        'u8': ('TIFF_UNKNOWN_OFFSET_SUSPECT', 'unaccountedBytes', [[142, 150], [156, 192]]),
        's1': ('TIFF_UNKNOWN_OFFSET_SUSPECT', 'unaccountedBytes', [[134, 150], [156, 192]]),
    }

    def test_t11_pointer_like_private_tags_are_refused(self):
        for variant, (code, reason, gaps) in self.CASES.items():
            found = e5tiff.locate(f.private_tag_tiff(variant))
            self.assertEqual([code], codes(found), variant)
            self.assertEqual(reason, found['write']['refusals'][0]['observed']['reason'], variant)
            self.assertEqual(gaps, found['layout']['unaccounted'], variant)
            self.assertIn('tiffUnknownTagSemanticsNotInterpreted', found['limitations'])
            self.assertEqual('present', states(found)['exif'])               # reading is never narrowed

    def test_t11e_unknown_ifd_type_is_named(self):
        found = e5tiff.locate(f.private_tag_tiff('i1'))
        self.assertEqual(['TIFF_UNKNOWN_IFD_POINTER', 'TIFF_UNKNOWN_OFFSET_SUSPECT'], codes(found))

    def test_an_entry_of_an_unsupported_type_is_refused_for_writing_and_still_read(self):
        found = e5tiff.locate(f._flat_tiff(lambda strip: [struct.pack('<HHI', 0xC7F5, 99, 1) + b'\0\0\0\0'], f.STRIP))
        self.assertIn('TIFF_TYPE_UNSUPPORTED', codes(found))
        refusal = next(r for r in found['write']['refusals'] if r['code'] == 'TIFF_TYPE_UNSUPPORTED')
        self.assertEqual((refusal['observed']['tag'], refusal['observed']['ifd']), (0xC7F5, 'IFD0'))
        self.assertFalse(found['write']['admissible'])
        self.assertEqual('present', states(found)['exif'])                  # reading is never narrowed by a write refusal

    def test_two_xmp_tags_in_ifd0_are_ambiguous_and_refused_for_writing(self):
        packet = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"/>\0'
        o = '<'
        strip = 8 + 2 + 12 * 11 + 4
        rows = [f.row(o, 0x100, f.SHORT, 1, f.short(o, 3)), f.row(o, 0x101, f.SHORT, 1, f.short(o, 2)), f.row(o, 0x102, f.SHORT, 1, f.short(o, 8)), f.row(o, 0x103, f.SHORT, 1, f.short(o, 1)),
                f.row(o, 0x106, f.SHORT, 1, f.short(o, 1)), f.row(o, 0x111, f.LONG, 1, f.long(o, strip + 2 * len(packet))), f.row(o, 0x115, f.SHORT, 1, f.short(o, 1)), f.row(o, 0x116, f.SHORT, 1, f.short(o, 2)),
                f.row(o, 0x117, f.LONG, 1, f.long(o, 6)), f.row(o, 0x02BC, 1, len(packet), f.long(o, strip)), f.row(o, 0x02BC, 1, len(packet), f.long(o, strip + len(packet)))]
        data = b'II*\0' + struct.pack('<I', 8) + f.ifd(o, rows) + packet + packet + f.STRIP
        found = e5tiff.locate(data)
        self.assertEqual(('ambiguous', 2), (states(found)['xmp'], next(s['count'] for s in found['slots'] if s['family'] == 'xmp')))
        self.assertIn('TIFF_DUPLICATE_METADATA_TAG', codes(found))
        self.assertFalse(found['write']['admissible'])

    def test_t11f_duplicate_pointer_without_gaps(self):
        found = e5tiff.locate(f.duplicate_pointer_tiff())
        self.assertEqual(['TIFF_UNKNOWN_OFFSET_SUSPECT'], codes(found))
        self.assertEqual('regionStart', found['write']['refusals'][0]['observed']['reason'])
        self.assertEqual(0xC7F0, found['write']['refusals'][0]['observed']['tag'])
        self.assertEqual([], found['layout']['unaccounted'])

    def test_t11g_plain_pair_is_admitted(self):
        found = e5tiff.locate(f.plain_private_pair_tiff())
        self.assertEqual([], codes(found))
        self.assertTrue(found['write']['admissible'])
        self.assertEqual([0xC7F0], [u['tag'] for u in found['layout']['unrecognised']])
        raw = rows(found, 'tiff/entry')['IFD0:0xc7f0']
        self.assertEqual(sha(struct.pack('<HHI', 0xC7F0, 4, 2) + struct.pack('<II', 3, 7)), raw[1])

    def test_t11h_gap_with_unrecognised_tag_is_refused_and_without_is_noted(self):
        refused = e5tiff.locate(f.gap_tiff(True))
        self.assertEqual(['TIFF_UNKNOWN_OFFSET_SUSPECT'], codes(refused))
        self.assertEqual([[140, 172]], refused['layout']['unaccounted'])
        admitted = e5tiff.locate(f.gap_tiff(False))
        self.assertEqual([], codes(admitted))
        self.assertIn('tiffUnreferencedBytesNotProtected', admitted['notes'])
        self.assertEqual([[140, 172]], admitted['layout']['unaccounted'])

    def test_t11i_free_offsets_are_a_named_unsupported_offset_tag(self):
        self.assertEqual(['TIFF_OFFSET_TAG_UNSUPPORTED'], codes(e5tiff.locate(f.offset_tag_tiff())))

    def test_t11m_the_frozen_admission_is_a_failing_oracle(self):
        """The superseded rule (unrecognised LONG/SLONG/IFD, count 1, value in [8, size) outside known regions) admits the counterexamples."""
        known = {0x100, 0x101, 0x102, 0x103, 0x106, 0x111, 0x115, 0x116, 0x117}

        def frozen_admits(data):
            count = struct.unpack_from('<H', data, 8)[0]
            regions = [(0, 8), (8, 8 + 2 + 12 * count + 4)]
            entries = []
            for i in range(count):
                tag, kind, number = struct.unpack_from('<HHI', data, 10 + 12 * i)
                field = data[18 + 12 * i:22 + 12 * i]
                entries.append((tag, kind, number, field))
            strip = next(struct.unpack('<I', e[3])[0] for e in entries if e[0] == 0x111)
            regions.append((strip, strip + 6))
            for tag, kind, number, field in entries:
                if tag in known or kind not in (4, 9, 13) or number != 1:
                    continue
                value = struct.unpack('<I', field)[0]
                if 8 <= value < len(data) and not any(a <= value < b for a, b in regions):
                    return False
            return True

        for variant in ('a2', 'u8'):
            data = f.private_tag_tiff(variant)
            self.assertTrue(frozen_admits(data), variant)                # the old rule admits it ...
            self.assertFalse(e5tiff.locate(data)['write']['admissible'], variant)   # ... the accounted-region rule does not
        self.assertTrue(frozen_admits(f.duplicate_pointer_tiff()))
        self.assertFalse(e5tiff.locate(f.duplicate_pointer_tiff())['write']['admissible'])
        for variant in ('a1', 's1', 'i1'):
            self.assertFalse(frozen_admits(f.private_tag_tiff(variant)), variant)


class FingerprintCompare(unittest.TestCase):
    def test_compare_kinds(self):
        a = [('r', 'x', 1, 'h1'), ('r', 'y', 2, 'h2')]
        self.assertEqual([], common.compare(a, list(a)))
        self.assertEqual('changed', common.compare(a, [('r', 'x', 1, 'h1'), ('r', 'y', 2, 'hh')])[0]['kind'])
        self.assertEqual('missing', common.compare(a, [a[0]])[0]['kind'])
        self.assertEqual('added', common.compare(a, a + [('r', 'z', 3, 'h3')])[0]['kind'])
        self.assertEqual('reordered', common.compare(a, [a[1], a[0]])[0]['kind'])
        self.assertEqual([], common.compare(a, [a[0]], allow=(('r', 'y'),)))
        self.assertEqual([], common.compare(a, [], allow=('r',)))


if __name__ == '__main__':
    unittest.main()
