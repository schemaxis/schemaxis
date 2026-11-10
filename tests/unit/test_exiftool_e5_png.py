"""Host tests of the E5 PNG locator (cases G-1..G-9 and the structure refusals); all fixtures are literal bytes."""
import hashlib
from pathlib import Path
import struct
import sys
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import exiftool_e5_fixtures as f  # noqa: E402
from schemaxis.adaptors.exiftool import e5common as common, e5payloads, e5png  # noqa: E402


def sha(data):
    return hashlib.sha256(data).hexdigest()


def codes(found):
    return [r['code'] for r in found['write']['refusals']]


def states(found):
    return {s['family']: s['state'] for s in found['slots']}


def names(found):
    return [(r, k) for r, k, _, _ in found['protected']]


class PngSlots(unittest.TestCase):
    def test_g1_eXIf_and_xmp_before_idat(self):
        data = f.basic_png()
        found = e5png.locate(data)
        self.assertEqual('png', found['container'])
        self.assertEqual({'width': 2, 'height': 2, 'bitDepth': 8, 'colourType': 'truecolour', 'interlaced': False}, found['frame'])
        self.assertEqual({'exif': 'present', 'xmp': 'present', 'iptc': 'absent'}, states(found))
        self.assertEqual([f.exif_stream()], found['exif'])
        self.assertEqual([f.XMP_TEXT], found['xmp'])
        self.assertEqual([('png/critical', 'IHDR#0'), ('png/ancillary', 'gAMA#0'), ('png/text', 'tEXt:Comment#0'), ('png/critical', 'IDAT#0'), ('png/critical', 'IEND#0')],
                         names(found))
        self.assertTrue(found['write']['admissible'])
        self.assertEqual(['gAMA'], found['render'])

    def test_protected_rows_hash_the_whole_chunk(self):
        found = e5png.locate(f.basic_png())
        gama = [row for row in found['protected'] if row[1] == 'gAMA#0'][0]
        self.assertEqual((16, sha(struct.pack('>I', 4) + b'gAMA' + struct.pack('>I', 45455) + struct.pack('>I', zlib.crc32(b'gAMA' + struct.pack('>I', 45455))))), gama[2:])

    def test_chunks_without_metadata(self):
        found = e5png.locate(f.basic_png(metadata=False))
        self.assertEqual({'exif': 'absent', 'xmp': 'absent', 'iptc': 'absent'}, states(found))
        self.assertEqual([], found['exif'] + found['xmp'])

    def test_g2_exif_after_idat_reads_but_does_not_write(self):
        data = f.png(f.ihdr(), f.IDAT, f.chunk(b'eXIf', f.exif_stream()), f.IEND)
        found = e5png.locate(data)
        self.assertEqual(['PNG_METADATA_AFTER_IDAT'], codes(found))
        self.assertIn('pngMetadataAfterIdat', found['notes'])
        self.assertEqual('present', states(found)['exif'])

    def test_g3_bad_crc_is_unreadable(self):
        data = f.png(f.ihdr(), f.chunk(b'gAMA', struct.pack('>I', 45455), crc=0), f.IDAT, f.IEND)
        with self.assertRaises(common.Refused) as caught:
            e5png.locate(data)
        self.assertEqual('PNG_CRC_INVALID', caught.exception.code)

    def test_g4_split_idat_is_ordered_and_swapping_is_a_fault(self):
        first, second = f.chunk(b'IDAT', b'one-part'), f.chunk(b'IDAT', b'two-part')
        found = e5png.locate(f.png(f.ihdr(), first, second, f.IEND))
        self.assertEqual([('png/critical', 'IDAT#0'), ('png/critical', 'IDAT#1')], [n for n in names(found) if n[1].startswith('IDAT')])
        swapped = e5png.locate(f.png(f.ihdr(), second, first, f.IEND))
        faults = common.compare(found['protected'], swapped['protected'])
        self.assertEqual(['png/critical[IDAT#0]', 'png/critical[IDAT#1]'], [x['path'] for x in faults])

    def test_g5_compressed_xmp_bomb_is_bounded(self):
        bomb = b'<' + b'A' * (5 * 1024 * 1024)
        found = e5png.locate(f.png(f.ihdr(), f.xmp_itxt(bomb, compressed=True), f.IDAT, f.IEND))
        self.assertEqual('unreadable', states(found)['xmp'])
        self.assertEqual('XMP_BOUND', [s for s in found['slots'] if s['family'] == 'xmp'][0]['code'])
        self.assertIn('XMP_BOUND', codes(found))
        self.assertEqual([], found['xmp'])

    def test_compressed_xmp_inside_the_bound_is_read(self):
        found = e5png.locate(f.png(f.ihdr(), f.xmp_itxt(compressed=True), f.IDAT, f.IEND))
        self.assertEqual([f.XMP_TEXT], found['xmp'])

    def test_damaged_compressed_xmp_is_unreadable_not_an_exception(self):
        body = b'XML:com.adobe.xmp\0\x01\x00\0\0' + b'not-a-zlib-stream'
        found = e5png.locate(f.png(f.ihdr(), f.chunk(b'iTXt', body), f.IDAT, f.IEND))
        self.assertEqual('XMP_MALFORMED', [s for s in found['slots'] if s['family'] == 'xmp'][0]['code'])

    def test_other_itxt_is_a_text_chunk_not_a_slot(self):
        other = f.chunk(b'iTXt', b'Comment\0\0\0\0\0hello')
        found = e5png.locate(f.png(f.ihdr(), other, f.IDAT, f.IEND))
        self.assertEqual('absent', states(found)['xmp'])
        self.assertEqual(('png/text', 'iTXt:Comment#0'), names(found)[1])

    def test_duplicate_slots_are_ambiguous_and_listed(self):
        found = e5png.locate(f.png(f.ihdr(), f.chunk(b'eXIf', f.exif_stream('<', 'First')), f.chunk(b'eXIf', f.exif_stream('>', 'Second')), f.IDAT, f.IEND))
        self.assertEqual('ambiguous', states(found)['exif'])
        self.assertEqual(2, len(found['exif']))
        self.assertIn('PNG_DUPLICATE_CHUNK', codes(found))
        two = e5png.locate(f.png(f.ihdr(), f.xmp_itxt(), f.xmp_itxt(), f.IDAT, f.IEND))
        self.assertEqual('ambiguous', states(two)['xmp'])

    def test_exif_without_a_tiff_header_is_unreadable(self):
        found = e5png.locate(f.png(f.ihdr(), f.chunk(b'eXIf', b'Exif\0\0II*\0'), f.IDAT, f.IEND))
        self.assertEqual('unreadable', states(found)['exif'])
        self.assertEqual(['INVALID_EXIF_STRUCTURE'], codes(found))

    def test_legacy_raw_profile_is_read_never_written(self):
        payload = b'Exif\0\0' + f.exif_stream()
        text = b'\nexif\n%8d\n' % len(payload) + payload.hex().encode()
        found = e5png.locate(f.png(f.ihdr(), f.text_chunk(b'Raw profile type exif', text), f.IDAT, f.IEND))
        self.assertEqual([f.exif_stream()], found['exif'])
        self.assertIn('pngLegacyRawProfile', found['notes'])
        self.assertEqual(['PNG_LEGACY_RAW_PROFILE'], codes(found))
        self.assertEqual(('png/text', 'tEXt:Raw profile type exif#0'), names(found)[1])


class PngStructure(unittest.TestCase):
    def test_g7_mutant_dropping_gama_is_reported(self):
        before = e5png.locate(f.basic_png())
        after = e5png.locate(f.png(f.ihdr(), f.text_chunk(b'Comment', b'plain text'), f.IDAT, f.IEND))
        faults = common.compare(before['protected'], after['protected'], allow=('png/text',))
        self.assertEqual([{'kind': 'missing', 'path': 'png/ancillary[gAMA#0]', 'role': 'png/ancillary', 'key': 'gAMA#0'}], faults)

    def test_slot_position_may_move_but_protected_order_may_not(self):
        base = e5png.locate(f.basic_png())
        moved = e5png.locate(f.png(f.ihdr(), f.xmp_itxt(), f.GAMA, f.chunk(b'eXIf', f.exif_stream()), f.text_chunk(b'Comment', b'plain text'), f.IDAT, f.IEND))
        self.assertEqual([], common.compare(base['protected'], moved['protected']))
        reordered = e5png.locate(f.png(f.ihdr(), f.text_chunk(b'Comment', b'plain text'), f.GAMA, f.IDAT, f.IEND))
        self.assertNotEqual([], common.compare(base['protected'], reordered['protected']))

    def test_g8_apng_animation_chunks_are_protected(self):
        actl = f.chunk(b'acTL', struct.pack('>II', 2, 0))
        fctl = f.chunk(b'fcTL', bytes(26))
        fdat = f.chunk(b'fdAT', struct.pack('>I', 1) + b'frame-two')
        found = e5png.locate(f.png(f.ihdr(), actl, fctl, f.IDAT, fctl, fdat, f.IEND))
        self.assertIn('apng', found['notes'])
        self.assertEqual(2, found['frame']['animationFrames'])
        keys = [k for _, k in names(found)]
        self.assertEqual(['IHDR#0', 'acTL#0', 'fcTL#0', 'IDAT#0', 'fcTL#1', 'fdAT#0', 'IEND#0'], keys)

    def test_g9_private_chunk_after_idat_is_kept_in_place(self):
        found = e5png.locate(f.png(f.ihdr(), f.IDAT, f.chunk(b'prVt', b'private'), f.IEND))
        self.assertEqual(('png/ancillary', 'prVt#0'), names(found)[2])
        self.assertTrue(found['write']['admissible'])

    def test_trailing_bytes_after_iend(self):
        found = e5png.locate(f.png(f.ihdr(), f.IDAT, f.IEND) + b'junk')
        self.assertIn('PNG_TRAILING_BYTES', found['notes'])
        self.assertEqual(['PNG_TRAILING_BYTES'], codes(found))

    def test_order_and_duplicates_refuse_writes_only(self):
        split = e5png.locate(f.png(f.ihdr(), f.IDAT, f.chunk(b'tEXt', b'k\0v'), f.IDAT, f.IEND))
        self.assertEqual(['PNG_CHUNK_ORDER_INVALID'], codes(split))
        twice = e5png.locate(f.png(f.ihdr(), f.GAMA, f.GAMA, f.IDAT, f.IEND))
        self.assertEqual(['PNG_DUPLICATE_CHUNK'], codes(twice))
        self.assertIn('pngDuplicateChunk:gAMA', twice['notes'])
        late_palette = e5png.locate(f.png(f.ihdr(), f.IDAT, f.chunk(b'PLTE', bytes(3)), f.IEND))
        self.assertEqual(['PNG_CHUNK_ORDER_INVALID'], codes(late_palette))

    def test_unreadable_files(self):
        for data, code in ((f.png(f.ihdr(), f.IDAT), 'INVALID_PHOTO_DATA'), (f.png(f.IDAT, f.IEND), 'INVALID_PHOTO_DATA'), (b'GIF89a' + bytes(20), 'UNSUPPORTED_MEDIA'),
                           (f.png(f.ihdr(), f.IDAT, f.IEND)[:-6], 'INVALID_PHOTO_DATA'), (f.png(f.ihdr(), f.chunk(b'ab1d', b''), f.IEND), 'INVALID_PHOTO_DATA')):
            with self.assertRaises(common.Refused) as caught:
                e5png.locate(data)
            self.assertEqual(code, caught.exception.code)

    def test_chunk_budget_and_declared_length(self):
        many = [f.ihdr()] + [f.chunk(b'tEXt', b'k\0v')] * 4100 + [f.IEND]
        with self.assertRaises(common.Refused) as caught:
            e5png.locate(f.png(*many))
        self.assertEqual('PHOTO_RESOURCE_LIMIT', caught.exception.code)
        huge = f.PNG_SIGNATURE + f.ihdr() + struct.pack('>I', 0x7FFFFFFF) + b'IDAT'
        with self.assertRaises(common.Refused) as caught:
            e5png.locate(huge)
        self.assertEqual('INVALID_PHOTO_DATA', caught.exception.code)

    def test_render_facts_are_listed(self):
        chunks = [f.ihdr(), f.chunk(b'cHRM', bytes(32)), f.chunk(b'sRGB', b'\0'), f.chunk(b'iCCP', b'p\0\0' + zlib.compress(b'icc')), f.chunk(b'pHYs', bytes(9)),
                  f.chunk(b'cICP', bytes(4)), f.IDAT, f.IEND]
        found = e5png.locate(f.png(*chunks))
        self.assertEqual(['cHRM', 'sRGB', 'iCCP', 'cICP', 'pHYs'], sorted(found['render'], key=['cHRM', 'sRGB', 'iCCP', 'cICP', 'pHYs'].index))
        self.assertEqual(8, len(found['protected']))

    def test_shared_decoders_read_png_payloads(self):
        decoded = e5payloads.decode(e5png.locate(f.basic_png()))
        self.assertEqual('ok', decoded['exif'][0][0])
        self.assertEqual('A. Mason', decoded['exif'][0][1]['ifds']['IFD0'][1][0].raw.rstrip(b'\0').decode())
        self.assertEqual({'x-default': 'Quarry gate'}, decoded['xmp'][0][1]['dc:title'][0]['value'])


if __name__ == '__main__':
    unittest.main()
