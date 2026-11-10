"""DNG device-identity removal (D-4), the native warning gate (D-2), the per-container size bound (64 MiB default, 256 MiB TIFF and DNG) and the HEIF grid edit (H-5), against a genuine ExifTool 13.55.

Expected values are literals written here. The size tests use sparse files and one opaque 65 MiB strip, so no pixel is decoded and no giant buffer is built beyond what the bound itself requires.
"""
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tools'), str(ROOT / 'tests/unit')]

import exiftool_e5_fixtures as f  # noqa: E402
import exiftool_e5_time_fixtures as t  # noqa: E402
import author_exiftool_fixtures as a  # noqa: E402
from schemaxis.adaptors.exiftool import adaptor, e5profiles, mediaset  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402
from test_exiftool_e5_ops import payloads, entry  # noqa: E402

EXIFTOOL = os.environ.get('SCHEMAXIS_EXIFTOOL')
V = 'schemaxis.exiftool/1'
MIB = 1024 * 1024
PRIVATE = b'VendorPrivate-0123'
MAKER = b'MAKERNOTE-OPAQUE-0123'


class Host(unittest.TestCase):
    """The size bound is one function of the item name, equal to the registry (host only)."""

    def test_the_item_bound_is_the_registry_bound_of_the_container(self):
        for suffix, container in (('.tif', 'tiff'), ('.tiff', 'tiff'), ('.dng', 'dng'), ('.TIF', 'tiff'), ('.png', 'png'), ('.webp', 'webp'), ('.heic', 'heif'), ('.jpg', None), ('.jpeg', None), ('.xmp', None)):
            expected = e5profiles.profile(container)['maxBytes'] if container else 64 * MIB
            self.assertEqual(mediaset.item_limit('a' + suffix), expected, suffix)
        self.assertEqual((mediaset.ITEM_BYTES, mediaset.LARGE_ITEM_BYTES), (64 * MIB, 256 * MIB))
        self.assertEqual({e5profiles.profile(c)['maxBytes'] for c in ('tiff', 'dng')}, {256 * MIB})
        self.assertEqual({e5profiles.profile(c)['maxBytes'] for c in ('png', 'webp', 'heif')}, {64 * MIB})

    def test_a_sparse_file_at_each_boundary_is_admitted_or_refused_at_stat_by_its_name(self):
        directory = Path(tempfile.mkdtemp(prefix='e5-bound-'))
        self.addCleanup(shutil.rmtree, directory, True)
        for name, size, ok in (('a.png', 64 * MIB, True), ('b.png', 64 * MIB + 1, False), ('c.jpg', 64 * MIB + 1, False), ('d.tif', 64 * MIB + 1, True), ('e.dng', 256 * MIB, True),
                               ('f.dng', 256 * MIB + 1, False), ('g.tif', 256 * MIB + 1, False), ('h.webp', 64 * MIB + 1, False), ('i.heic', 64 * MIB + 1, False)):
            with (directory / name).open('wb') as stream:
                stream.truncate(size)
            if ok:
                mediaset.explicit_stat(str(directory / name), '$.media.items[0].path', name)
            else:
                with self.assertRaises(SchemaxisError) as caught:
                    mediaset.explicit_stat(str(directory / name), '$.media.items[0].path', name)
                self.assertEqual(caught.exception.fault.code, 'PHOTO_RESOURCE_LIMIT', name)
                self.assertEqual(caught.exception.fault.observed['observed'], size)


@unittest.skipUnless(EXIFTOOL and Path(EXIFTOOL).exists(), 'a real ExifTool 13.55 is needed (SCHEMAXIS_EXIFTOOL)')
class Native(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='e5-residual-')).resolve()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.runs = 0

    def run_op(self, name, data, document, expect_fault=False):
        type(self).runs += 1
        path = self.tmp / name
        path.write_bytes(data) if isinstance(data, bytes) else None
        out = self.tmp / ('run%d' % self.runs)
        doc = {'version': V, **document, 'media': {'items': [{'id': 'x', 'path': str(path)}]}}
        if expect_fault:
            with self.assertRaises(SchemaxisError) as caught:
                adaptor.run(doc, out, executable=EXIFTOOL, timeout=600)
            return caught.exception.fault, out
        result = adaptor.run(doc, out, executable=EXIFTOOL, timeout=600)
        self.assertTrue(result['verified'])
        return result, out

    # ------------------------------------------------------------------ D-4
    def test_d4_dng_device_identity_removal_keeps_the_maker_note_and_private_data_and_publishes_the_residual(self):
        before = t.container('dng', serial='SN-0001', make='Quarry Optics', model='QO-7', exif_extra=[a.undefined_entry(0x927C, MAKER)], ifd0_extra=[a.entry(0xC634, 7, PRIVATE)])
        for needle in (b'SN-0001', b'Quarry Optics', b'QO-7', PRIVATE, MAKER):
            self.assertEqual(before.count(needle), 1, needle)
        result, out = self.run_op('d4.dng', before, {'operation': 'removeMetadata', 'categories': ['deviceIdentity']})
        self.assertEqual((result['written'], result['refused'], result['failed']), (1, 0, 0))
        data = next(p for p in (out / 'photos').glob('x.*') if not p.name.endswith('.json')).read_bytes()
        for gone in (b'SN-0001', b'Quarry Optics', b'QO-7'):
            self.assertNotIn(gone, data, gone)                                       # the serial number, make and model are removed
        self.assertEqual((data.count(PRIVATE), data.count(MAKER), data.count(f.STRIP)), (1, 1, 1))     # DNGPrivateData, the maker note and the strip are byte equal
        residual = json.loads((out / 'residual.json').read_text())
        text = json.dumps(residual)
        self.assertIn('makerNoteMayIdentifyDevice', text)                            # the declared residual: a maker note may still identify the device
        report = json.loads((out / 'removal-report.json').read_text())['items'][0]
        self.assertEqual(report['proofs']['problems'], 0)

    # ------------------------------------------------------------------ D-2
    def test_d2_a_malformed_adobe_makn_private_block_is_refused_by_the_native_warning_gate_before_any_write(self):
        private = b'Adobe\0MakN' + struct.pack('>I', 4000) + b'II'
        data = f.dng('<', private)[0]
        fault, out = self.run_op('d2.dng', data, {'operation': 'editMetadata', 'edits': {'title': {'set': 'Quarry gate north'}}}, expect_fault=True)
        self.assertEqual(fault.code, 'NO_USABLE_ITEMS')
        first = fault.observed['firstFaults'][0]
        self.assertEqual(first['code'], 'WRITE_INPUT_NATIVE_WARNING')
        self.assertFalse((out / 'photos').exists())

    # ------------------------------------------------------------------ size bound with real bytes
    def test_a_65_mib_tiff_is_edited_because_a_tiff_may_reach_256_mib(self):
        strip = bytes(65 * MIB)
        data = t.tiff(strips=strip)
        self.assertGreater(len(data), 64 * MIB)
        result, out = self.run_op('big.tif', data, {'operation': 'editMetadata', 'edits': {'title': {'set': 'Quarry gate north'}}})
        self.assertEqual((result['written'], result['refused'], result['failed']), (1, 0, 0))
        written = next(p for p in (out / 'photos').glob('x.*') if not p.name.endswith('.json')).read_bytes()
        self.assertGreater(len(written), 64 * MIB)
        self.assertEqual(written.count(strip[:4096]) >= 1, True)
        self.assertIn(b'Quarry gate north', written)
        self.assertEqual(adaptor.verify(out, executable=EXIFTOOL)['nativeReplay'], 'fresh-replay-matched')

    def test_a_65_mib_png_is_refused_by_its_signature_even_under_a_tif_name(self):
        data = f.png(f.ihdr(), f.chunk(b'IDAT', bytes(65 * MIB)), f.IEND)
        fault, _ = self.run_op('big.tif', data, {'operation': 'editMetadata', 'edits': {'title': {'set': 'x'}}}, expect_fault=True)
        self.assertEqual(fault.code, 'NO_USABLE_ITEMS')
        self.assertEqual(fault.observed['firstFaults'][0]['code'], 'PHOTO_RESOURCE_LIMIT')

    def test_a_sparse_png_just_over_64_mib_is_refused_at_stat_without_reading_it(self):
        path = self.tmp / 'sparse.png'
        with path.open('wb') as stream:
            stream.truncate(64 * MIB + 1)
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.run({'version': V, 'operation': 'editMetadata', 'media': {'items': [{'id': 'x', 'path': str(path)}]}, 'edits': {'title': {'set': 'x'}}}, self.tmp / 'sparse-run', executable=EXIFTOOL)
        first = caught.exception.fault.observed['firstFaults'][0]
        self.assertEqual((caught.exception.fault.code, first['code'], first['observed']['observed']), ('NO_USABLE_ITEMS', 'PHOTO_RESOURCE_LIMIT', 64 * MIB + 1))

    # ------------------------------------------------------------------ AM-18R end to end: unknown offset-like tags are refused before any native process, clean structures are written
    def test_am18r_unknown_pointer_like_structures_are_refused_before_native_and_clean_ones_are_written_with_the_private_words_kept(self):
        refused = (('private_pointer', f.duplicate_pointer_tiff(), 'TIFF_UNKNOWN_OFFSET_SUSPECT', 'regionStart'), ('gap_with_unrecognised_tag', f.gap_tiff(True), 'TIFF_UNKNOWN_OFFSET_SUSPECT', 'unaccountedBytes'),
                   ('free_offsets_tag', f.offset_tag_tiff(), 'TIFF_OFFSET_TAG_UNSUPPORTED', None),
                   ('unsupported_type', f._flat_tiff(lambda strip: [struct.pack('<HHI', 0xC7F5, 99, 1) + b'\0\0\0\0'], f.STRIP), 'TIFF_TYPE_UNSUPPORTED', None))
        for name, data, code, reason in refused:
            fault, out = self.run_op(name + '.tif', data, {'operation': 'editMetadata', 'edits': {'title': {'set': 'Quarry gate north'}}}, expect_fault=True)
            first = fault.observed['firstFaults'][0]
            self.assertEqual((fault.code, first['code']), ('NO_USABLE_ITEMS', code), name)
            if reason:
                self.assertEqual(first['observed']['reason'], reason, name)
            self.assertFalse((out / 'photos').exists(), name)                                  # nothing was written
        # controls: a plain private LONG pair that no region owns is admitted and its two words survive; a known tag in a gap is written
        for name, data, keep in (('plain_private_pair', f.plain_private_pair_tiff(), [struct.pack('<II', 3, 7), f.STRIP]), ('gap_with_known_tag', f.gap_tiff(False), [f.STRIP])):
            result, out = self.run_op(name + '.tif', data, {'operation': 'editMetadata', 'edits': {'title': {'set': 'Quarry gate north'}}})
            self.assertEqual((result['written'], result['refused'], result['failed']), (1, 0, 0), name)
            written = next(p for p in (out / 'photos').glob('x.*') if not p.name.endswith('.json')).read_bytes()
            for part in keep:
                self.assertEqual(written.count(part), 1, (name, part[:8]))

    # ------------------------------------------------------------------ H-5
    def test_h5_a_heif_grid_with_tiles_and_a_thumbnail_is_edited_through_its_existing_metadata_items(self):
        tiles = [{'id': 2 + i, 'type': b'hvc1', 'payload': b'TILE-%d' % i} for i in range(4)]
        items = [{'id': 1, 'type': b'grid', 'payload': b'GRIDDESC'}] + tiles + [{'id': 6, 'type': b'hvc1', 'payload': b'THUMB!'},
                 {'id': 7, 'type': b'Exif', 'payload': struct.pack('>I', 0) + t.stream()}, {'id': 8, 'type': b'mime', 'content_type': b'application/rdf+xml', 'payload': f.XMP_TEXT}]
        refs = [(b'dimg', 1, [2, 3, 4, 5]), (b'thmb', 6, [1]), (b'cdsc', 7, [1]), (b'cdsc', 8, [1])]
        data = f.heic(items, refs=refs, props=((b'ispe', 128, 96),), associations={1: [1]})
        result, out = self.run_op('grid.heic', data, {'operation': 'editMetadata', 'edits': {'title': {'set': 'Grid title'}}})
        self.assertEqual((result['written'], result['refused'], result['failed']), (1, 0, 0))
        written = next(p for p in (out / 'photos').glob('x.*') if not p.name.endswith('.json')).read_bytes()
        for payload in (b'GRIDDESC', b'TILE-0', b'TILE-1', b'TILE-2', b'TILE-3', b'THUMB!'):
            self.assertEqual(written.count(payload), 1, payload)                      # grid descriptor, every tile and the thumbnail are byte equal
        self.assertIn(b'Grid title', written)
        report = json.loads((out / 'edit-report.json').read_text())['items'][0]
        self.assertEqual((report['status'], report['proofs']['problems']), ('written', 0))


if __name__ == '__main__':
    unittest.main()
