"""Native structural tests of the E5 locators against a real ExifTool 13.55 (skipped without SCHEMAXIS_EXIFTOOL).

Every input is a hand-built literal fixture; each test runs one native copy-write (``-config "" ... -o out in``) in a private temporary directory
and judges the output with the independent locators and the literal expectations written here. These tests establish what the native writer did
to the protected structures; they do not claim that native behaviour is correct, and they say nothing about pixels.
"""
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import exiftool_e5_fixtures as f  # noqa: E402
from schemaxis.adaptors.exiftool import e5common as common, e5locate, e5proof, e5riff  # noqa: E402

EXIFTOOL = os.environ.get('SCHEMAXIS_EXIFTOOL')
ARTIST = ('tiff/entry', 'IFD0:0x013b')
VP8 = f.ck(b'VP8 ', f.vp8())
VP8L = f.ck(b'VP8L', f.vp8l())
VP8L_ALPHA = f.ck(b'VP8L', f.vp8l(alpha=True))
ICCP, ALPH, ANIM = f.ck(b'ICCP', f.ICC), f.ck(b'ALPH', f.ALPH), f.ck(b'ANIM', bytes(6))
E, X = f.webp_exif(), f.webp_xmp()


@unittest.skipUnless(EXIFTOOL and Path(EXIFTOOL).exists(), 'a real ExifTool 13.55 is needed (SCHEMAXIS_EXIFTOOL)')
class NativeBase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='e5-native-'))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.count = 0

    def native(self, data, args, suffix):
        self.count += 1
        source, out = self.dir / ('in%d%s' % (self.count, suffix)), self.dir / ('out%d%s' % (self.count, suffix))
        source.write_bytes(data)
        run = subprocess.run(['perl', EXIFTOOL, '-config', ''] + args + ['-o', str(out), str(source)], capture_output=True, env={'LANG': 'C', 'LC_ALL': 'C', 'PATH': '/usr/bin:/bin'},
                             timeout=60, cwd=str(self.dir))
        return run.returncode, run.stdout.decode(), run.stderr.decode(), (out.read_bytes() if out.exists() else None)

    def edit(self, data, args, suffix):
        code, out, err, result = self.native(data, args, suffix)
        self.assertEqual((0, ''), (code, err), (out, err))
        return result

    def faults(self, before, after, allow=()):
        return [x['path'] for x in common.compare(e5locate.locate(before)['protected'], e5locate.locate(after)['protected'], allow=allow)]


class NativeProof(NativeBase):
    """The one proof entry point, applied to real native output of every container."""

    def test_p_passes_on_native_edits_and_names_the_loss_of_a_native_all_equals(self):
        cases = [('.tif', f.plain_tiff('>'), ['-IFD0:Artist=Native Artist'], (ARTIST,)), ('.dng', f.dng('<')[0], ['-IFD0:Artist=Native Artist'], (ARTIST,)),
                 ('.png', f.basic_png(), ['-XMP-dc:Title=Native Title', '-IFD0:Artist=Native Artist'], ()),
                 ('.webp', f.riff(f.vp8x(0x2C), ICCP, VP8, E, X), ['-IFD0:Artist=Native Artist'], ()), ('.heic', f.heic_basic(with_metadata=True), ['-IFD0:Artist=Native Artist'], ())]
        for suffix, data, args, allow in cases:
            with self.subTest(suffix):
                after = self.edit(data, args, suffix)
                self.assertEqual({'ok': True, 'faults': []}, {k: v for k, v in e5proof.preserve(data, after, allow=allow).items() if k != 'container'})
        png = f.basic_png()
        code, out, err, after = self.native(png, ['-all='], '.png')
        self.assertEqual([('PRESERVATION_MISMATCH', 'png/ancillary[gAMA#0]')], [(x['code'], x['path']) for x in e5proof.preserve(png, after, allow=('png/text',))['faults']])


class NativeTiff(NativeBase):
    def test_strips_tiles_pages_and_dng_survive_relocation(self):
        data, tiles = f.tiled_tiff('<')
        cases = [('tiff-le', f.plain_tiff('<')), ('tiff-be', f.plain_tiff('>')), ('tiled', data), ('lzw', f.lzw_tiff('<')[0]), ('two-page', f.two_page_tiff('<')),
                 ('thumbnail', f.jpeg_thumbnail_tiff('<')[0]), ('dng', f.dng('<')[0]), ('dng-be', f.dng('>')[0]), ('gps', f.gps_tiff('<')), ('interop', f.interop_tiff('>')),
                 ('xmp-iptc', f.three_strip_tiff_with_xmp_iptc('<')[0])]
        for name, fixture in cases:
            with self.subTest(name):
                after = self.edit(fixture, ['-IFD0:Artist=Native Artist'], '.dng' if name.startswith('dng') else '.tif')
                self.assertEqual([], self.faults(fixture, after, allow=(ARTIST,)))
                self.assertIn(b'Native Artist', after)
                self.assertEqual(e5locate.locate(fixture)['container'], e5locate.locate(after)['container'])

    def test_the_native_writer_really_relocates_the_strip(self):
        data = f.plain_tiff('<')
        after = self.edit(data, ['-IFD0:Artist=A much longer artist name that moves the data'], '.tif')
        old = [r for r in e5locate.locate(data)['ranges'] if r[0] == 'tiff/extent'][0]
        new = [r for r in e5locate.locate(after)['ranges'] if r[0] == 'tiff/extent'][0]
        self.assertNotEqual(old[2], new[2])
        self.assertEqual(f.STRIP, after[new[2]:new[2] + 6])

    def test_xmp_slot_is_written_to_tag_0x02bc_and_read_back_by_the_locator(self):
        after = self.edit(f.plain_tiff('>'), ['-XMP-dc:Title=Native Title'], '.tif')
        found = e5locate.locate(after)
        self.assertEqual('present', [s for s in found['slots'] if s['family'] == 'xmp'][0]['state'])
        self.assertIn(b'Native Title', found['xmp'][0])
        self.assertEqual([], self.faults(f.plain_tiff('>'), after))

    def test_t11_native_counterexamples_the_pointer_goes_stale_while_value_bytes_stay_equal(self):
        for variant, tag in (('a2', 0xC7F0), ('u8', 0xC7F1)):
            with self.subTest(variant):
                data = f.private_tag_tiff(variant)
                self.assertFalse(e5locate.locate(data)['write']['admissible'])
                after = self.edit(data, ['-IFD0:Artist=probe'], '.tif')
                entries = {row[0]: row for row in self.ifd0(after)}
                before_entries = {row[0]: row for row in self.ifd0(data)}
                self.assertEqual(before_entries[tag][1:4], entries[tag][1:4])                 # value bytes equal
                pointer = struct.unpack('<I', entries[tag][3][:4])[0]
                self.assertNotEqual(f.BLOB, after[pointer:pointer + 16])                      # ... but the block they point at is no longer there
                self.assertIn(f.BLOB, after)                                                  # (the block itself was moved)

    def test_t11g_plain_pair_is_admitted_and_survives(self):
        data = f.plain_private_pair_tiff()
        self.assertTrue(e5locate.locate(data)['write']['admissible'])
        after = self.edit(data, ['-IFD0:Artist=probe'], '.tif')
        self.assertEqual([], self.faults(data, after, allow=(ARTIST,)))
        self.assertEqual((4, 2, struct.pack('<II', 3, 7)), {r[0]: r[1:4] for r in self.ifd0(after)}[0xC7F0])

    def test_t11h0_a_gap_without_unrecognised_tags_is_kept_by_native(self):
        data = f.gap_tiff(False)
        after = self.edit(data, ['-IFD0:Artist=probe'], '.tif')
        self.assertEqual([], self.faults(data, after, allow=(ARTIST,)))
        self.assertIn(b'G' * 32, after)

    def test_native_ifd0_all_equals_warns_and_is_therefore_never_a_recipe(self):
        data = f.plain_tiff('<')
        code, out, err, after = self.native(data, ['-IFD0:all='], '.tif')
        self.assertIn("Can't delete IFD0 from TIFF", err)                                    # native refuses to delete IFD0 and keeps it: a warning, never accepted
        self.assertEqual(0, code)

    @staticmethod
    def ifd0(data):
        count = struct.unpack_from('<H', data, struct.unpack_from('<I', data, 4)[0])[0]
        base = struct.unpack_from('<I', data, 4)[0] + 2
        out = []
        for i in range(count):
            tag, kind, number = struct.unpack_from('<HHI', data, base + 12 * i)
            size = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8, 13: 4}[kind] * number
            field = data[base + 12 * i + 8:base + 12 * i + 12]
            raw = field[:size] if size <= 4 else data[struct.unpack('<I', field)[0]:][:size]
            out.append((tag, kind, number, raw))
        return out


class NativePng(NativeBase):
    def test_g1_edit_keeps_every_protected_chunk(self):
        data = f.basic_png()
        after = self.edit(data, ['-XMP-dc:Title=Native Title', '-IFD0:Artist=Native Artist'], '.png')
        self.assertEqual([], self.faults(data, after))
        found = e5locate.locate(after)
        self.assertEqual(['present', 'present'], [s['state'] for s in found['slots'][:2]])
        self.assertTrue(found['write']['admissible'])

    def test_png_metadata_is_created_when_absent_and_stays_before_idat(self):
        data = f.basic_png(metadata=False)
        after = self.edit(data, ['-XMP-dc:Title=Native Title', '-IFD0:Artist=Native Artist'], '.png')
        self.assertEqual([], self.faults(data, after))
        self.assertTrue(e5locate.locate(after)['write']['admissible'])

    def test_g7_native_all_equals_removes_gamma_and_the_proof_sees_it(self):
        data = f.basic_png()
        after = self.edit(data, ['-all='], '.png')
        self.assertIn('png/ancillary[gAMA#0]', self.faults(data, after))

    def test_g9_private_chunk_after_idat_is_kept(self):
        data = f.png(f.ihdr(), f.IDAT, f.chunk(b'prVt', b'private'), f.IEND)
        after = self.edit(data, ['-IFD0:Artist=Native Artist'], '.png')
        self.assertEqual([], self.faults(data, after))
        self.assertIn(b'prVt', after)


class NativeWebp(NativeBase):
    REMOVE = ['-EXIF:all=', '-XMP:all=']

    def test_w1_w2_vp8x_creation(self):
        for name, stream, flags in (('lossy', VP8, 0x0C), ('lossless', VP8L, 0x0C), ('lossless-alpha', VP8L_ALPHA, 0x1C)):
            with self.subTest(name):
                before = f.riff(stream)
                after = self.edit(before, ['-XMP-dc:Title=Native Title', '-IFD0:Artist=Native Artist'], '.webp')
                self.assertEqual([], e5riff.prove_layout(before, after))
                located = e5locate.locate(after)
                self.assertEqual((flags, 3, 2), (located['layout']['vp8x']['flags'], located['layout']['vp8x']['width'], located['layout']['vp8x']['height']))

    def test_am16r_native_removal_rows(self):
        rows = [('w12 iccp', (f.vp8x(0x2C), ICCP, VP8, E, X), ['VP8X', 'ICCP', 'VP8 '], 0x20), ('w13 alph', (f.vp8x(0x1C), ALPH, VP8, E, X), ['VP8X', 'ALPH', 'VP8 '], 0x10),
                ('w14 anim', (f.vp8x(0x0E), ANIM, f.anmf(), f.anmf(), E, X), ['VP8X', 'ANIM', 'ANMF', 'ANMF'], 0x02),
                ('w15 iccp_unk', (f.vp8x(0x2C), ICCP, VP8, E, X, f.UNKNOWN), ['VP8X', 'ICCP', 'VP8 ', 'zzzz'], 0x20),
                ('w15b alph_unk', (f.vp8x(0x1C), ALPH, VP8, E, f.UNKNOWN), ['VP8X', 'ALPH', 'VP8 ', 'zzzz'], 0x10), ('w7 plain', (f.vp8x(0x0C), VP8, E, X), ['VP8 '], None),
                ('w17b vp8l alpha L', (f.vp8x(0x18), VP8L_ALPHA, E), ['VP8L'], None), ('w17c vp8l alpha noL', (f.vp8x(0x08), VP8L_ALPHA, E), ['VP8L'], None)]
        for name, chunks, expected, flags in rows:
            with self.subTest(name):
                before = f.riff(*chunks)
                self.assertTrue(e5riff.predict_vp8x(e5riff.facts(before, e5riff.parse(before)))['admitted'])
                after = self.edit(before, self.REMOVE, '.webp')
                self.assertEqual([], e5riff.prove_layout(before, after))
                self.assertEqual(expected, [c['id'].decode().replace('\0', '') for c in e5riff.parse(after)['chunks']])
                if flags is not None:
                    self.assertEqual(flags, e5riff.facts(after, e5riff.parse(after))['vp8x']['flags'])

    def test_am16r_refused_rows_native_output_fails_the_proof_and_the_plan_refuses_first(self):
        rows = [('w10 unk', (f.vp8x(0x0C), VP8, E, X, f.UNKNOWN), 'WEBP_LAYOUT_INVALID_AFTER_WRITE'), ('w16 lflag_noalph', (f.vp8x(0x1C), VP8, E, X), 'WEBP_LAYOUT_INVALID_AFTER_WRITE'),
                ('w17 vp8l_lflag', (f.vp8x(0x18), VP8L, E), 'WEBP_LAYOUT_INVALID_AFTER_WRITE')]
        for name, chunks, code in rows:
            with self.subTest(name):
                before = f.riff(*chunks)
                self.assertFalse(e5riff.predict_vp8x(e5riff.facts(before, e5riff.parse(before)))['admitted'])
                after = self.edit(before, self.REMOVE, '.webp')
                self.assertIn(code, [x['code'] for x in e5riff.prove_layout(before, after)])

    def test_native_all_equals_deletes_the_icc_profile_and_vp8x(self):
        before = f.riff(f.vp8x(0x2C), ICCP, VP8, E, X)
        code, out, err, after = self.native(before, ['-all='], '.webp')
        self.assertIn('ICC_Profile deleted', err)
        proved = {x['code'] for x in e5riff.prove_layout(before, after)}
        self.assertEqual({'PRESERVATION_MISMATCH', 'WEBP_LAYOUT_INVALID_AFTER_WRITE'}, proved)      # ICCP gone, and the I flag lost with VP8X

    def test_edit_keeps_icc_alpha_animation_and_unknown_chunks(self):
        for chunks in ((f.vp8x(0x2C), ICCP, VP8, E, X, f.UNKNOWN), (f.vp8x(0x1C), ALPH, VP8, E, X), (f.vp8x(0x0E), ANIM, f.anmf(), f.anmf(), E, X)):
            before = f.riff(*chunks)
            after = self.edit(before, ['-IFD0:Artist=Native Artist'], '.webp')
            self.assertEqual([], e5riff.prove_layout(before, after))
            self.assertEqual([], self.faults(before, after))


class NativeHeif(NativeBase):
    def test_h3_edit_of_an_existing_exif_item_keeps_the_image_and_properties(self):
        data = f.heic_basic(with_metadata=True)
        after = self.edit(data, ['-IFD0:Artist=A much longer artist name than the original one'], '.heic')
        self.assertEqual([], self.faults(data, after))
        found = e5locate.locate(after)
        self.assertEqual(['present', 'present'], [s['state'] for s in found['slots'][:2]])
        self.assertTrue(found['write']['admissible'])

    ATTEMPTS = 8

    def attempts(self, data, args):
        """Native HEIC creation on a file without metadata items is not reproducible (hash order); judge every attempt, never assume one."""
        outcomes = []
        for _ in range(self.ATTEMPTS):
            code, out, err, after = self.native(data, args, '.heic')
            outcomes.append((code, out + err, after))
        return outcomes

    def test_h2_creating_one_metadata_item_never_yields_a_wrong_accepted_file(self):
        data = f.heic_basic()
        for args, family in ((['-XMP-dc:Title=Native Title'], 'xmp'), (['-IFD0:Artist=Native Artist'], 'exif')):
            seen = set()
            for code, text, after in self.attempts(data, args):
                if code != 0:
                    self.assertIn('Chunk offset in iloc atom is outside media data', text)       # native fails by itself and writes nothing
                    self.assertIsNone(after)
                    seen.add('native-error')
                else:
                    self.assertEqual([], self.faults(data, after))                               # a written file passes the independent proof
                    found = e5locate.locate(after)
                    self.assertEqual('present', [s for s in found['slots'] if s['family'] == family][0]['state'])
                    self.assertTrue(found['write']['admissible'])
                    seen.add('proved')
            self.assertTrue(seen)

    def test_native_gap_creating_exif_and_xmp_together_is_always_refused_by_the_proof(self):
        """13.55 writes the second cdsc entry with 32-bit item IDs inside a version-0 iref (or damages the file); no attempt may pass."""
        data = f.heic_basic()
        for code, text, after in self.attempts(data, ['-XMP-dc:Title=Native Title', '-IFD0:Artist=Native Artist']):
            if after is None:
                continue
            try:
                found = e5locate.locate(after)
                verdict = (not found['write']['admissible']) or bool(self.faults(data, after))
            except common.Refused:
                verdict = True
            self.assertTrue(verdict)

    def test_h12_native_all_equals_produces_items_that_alias_the_image_payload(self):
        items = [{'id': 1, 'type': b'hvc1', 'payload': b'OPAQUE-HVC1-IMAGE-24BYTES'[:24]}, {'id': 2, 'type': b'Exif', 'payload': f.exif_item()},
                 {'id': 3, 'type': b'mime', 'content_type': b'application/rdf+xml', 'payload': f.XMP_TEXT}]
        data = f.heic(items, refs=[(b'cdsc', 2, [1]), (b'cdsc', 3, [1])], layout=[2, 3, 1])
        after = self.edit(data, ['-all='], '.heic')
        found = e5locate.locate(after)
        self.assertEqual(['unreadable', 'unreadable'], [s['state'] for s in found['slots'][:2]])
        self.assertEqual(['HEIF_IMPLIED_EXTENT', 'HEIF_IMPLIED_EXTENT'], [s['code'] for s in found['slots'][:2]])
        self.assertIn('HEIF_EXTENT_OVERLAP', found['notes'])
        start = after.index(b'OPAQUE-HVC1-IMAGE-24')
        self.assertEqual({(start, 24)}, {tuple(i['resolved'][0]) for i in found['items']})   # all three items resolve to the same 24 bytes

    def test_native_all_equals_with_the_metadata_last_leaves_unreadable_slots_at_end_of_file(self):
        after = self.edit(f.heic_basic(with_metadata=True), ['-all='], '.heic')
        found = e5locate.locate(after)
        self.assertEqual(['HEIF_IMPLIED_EXTENT', 'HEIF_IMPLIED_EXTENT'], [s['code'] for s in found['slots'][:2]])
        self.assertFalse(found['write']['admissible'])


if __name__ == '__main__':
    unittest.main()
