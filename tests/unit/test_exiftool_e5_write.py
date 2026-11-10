"""Host and native tests of the E5 write path: editMetadata and removeMetadata over TIFF, DNG, PNG, WebP and HEIF captures.

Host tests need no native process. Native tests need a real ExifTool 13.55 through SCHEMAXIS_EXIFTOOL and are skipped otherwise. Every expectation is a literal
authored here (the fixtures are assembled from literal bytes, see ``exiftool_e5_fixtures``): protected bytes are looked up in the produced files directly, never
computed by the locators or by ExifTool. Nothing here decodes pixels.
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
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests/unit'), str(ROOT / 'tools')]

import author_exiftool_fixtures as author  # noqa: E402
import exiftool_e5_fixtures as f  # noqa: E402
from schemaxis.adaptors.exiftool import containers, e5edit, e5locate, e5payloads, e5profiles, edits, editing, listing, mediaset, records, workbench  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402

EXIFTOOL = os.environ.get('SCHEMAXIS_EXIFTOOL')
TITLE, ARTIST = 'Quarry gate north', 'B. Mason'
EDIT = {'title': {'set': TITLE}, 'creator': {'set': [ARTIST]}}
HEIC_IMAGE = b'OPAQUE-HVC1-IMAGE-24BYTES'[:24]


def doc(operation, items, **rest):
    return {'version': 'schemaxis.exiftool/1', 'operation': operation, 'media': {'items': items}, **rest}


def fixtures():
    return {'tiff_le.tif': f.plain_tiff('<'), 'tiff_be.tif': f.plain_tiff('>'), 'tiff_tiled.tif': f.tiled_tiff()[0], 'tiff_twopage.tif': f.two_page_tiff(), 'tiff_gps.tif': f.gps_tiff(),
            'tiff_iptc.tif': f.three_strip_tiff_with_xmp_iptc()[0], 'dng_vendor.dng': f.dng()[0], 'dng_be.dng': f.dng('>')[0], 'png_basic.png': f.basic_png(), 'png_nometa.png': f.basic_png(metadata=False),
            'webp_plain.webp': f.riff(f.ck(b'VP8 ', f.vp8())), 'webp_lossless.webp': f.riff(f.ck(b'VP8L', f.vp8l())), 'webp_meta.webp': f.riff(f.vp8x(0x0C), f.ck(b'VP8 ', f.vp8()), f.webp_exif(), f.webp_xmp()),
            'heic_basic.heic': f.heic_basic(), 'heic_meta.heic': f.heic_basic(with_metadata=True)}


class Host(unittest.TestCase):
    def fault(self, call, code):
        with self.assertRaises(SchemaxisError) as caught:
            call()
        self.assertEqual(caught.exception.fault.code, code)
        return caught.exception.fault

    def payloads(self, data):
        return records.Payloads(e5locate.locate(data))

    def plan(self, data, edit=EDIT):
        entries = {k: edits.normalise_edit(k, v, '$.edits.' + k) for k, v in edit.items()}
        return edits.plan_item(entries, self.payloads(data), edits.normalise_policies(None))

    def test_capabilities_equal_the_pinned_profile_destinations(self):
        for container, capabilities in containers.CAPABILITIES.items():
            if container in ('xmp', 'jpeg'):
                continue
            profile = e5profiles.profile(container)['destinations']
            self.assertEqual({'exif', 'xmp', 'iptc'} & set(capabilities), {k for k, v in profile.items() if v}, container)

    def test_default_folder_scope_and_jpeg_suffixes_are_unchanged(self):
        self.assertEqual(mediaset.IMAGE_SUFFIXES, ('.jpg', '.jpeg'))
        planned = workbench.plan({'version': 'schemaxis.exiftool/1', 'operation': 'inspectMetadata', 'profiles': ['capture'], 'media': {'folder': {'path': '/x'}}})
        self.assertEqual(planned['media']['folder']['extensions'], ['.jpg', '.jpeg', '.xmp'])
        chosen = workbench.plan({'version': 'schemaxis.exiftool/1', 'operation': 'inspectMetadata', 'profiles': ['capture'], 'media': {'folder': {'path': '/x', 'extensions': ['.png', '.tif', '.jpg']}}})
        self.assertEqual(chosen['media']['folder']['extensions'], ['.jpg', '.tif', '.png'])

    def test_write_plans_accept_the_container_suffixes_and_keep_xmp_out(self):
        for suffix in ('.tif', '.tiff', '.dng', '.png', '.webp', '.heic', '.heif', '.avif'):
            planned = editing.plan(doc('editMetadata', [{'id': 'a', 'path': '/x/a' + suffix}], edits=EDIT))
            self.assertEqual(planned['media']['items'][0]['path'], '/x/a' + suffix)
        self.fault(lambda: editing.plan(doc('editMetadata', [{'id': 'a', 'path': '/x/a.xmp'}], edits=EDIT)), 'INVALID_PHOTO_SOURCE')
        self.fault(lambda: editing.plan(doc('editMetadata', [{'id': 'a', 'path': '/x/a.png', 'sidecar': '/x/a.xmp'}], edits=EDIT)), 'WRITE_SIDECAR_UNSUPPORTED')

    def test_iptc_has_no_destination_in_png_webp_and_heif_and_that_is_a_declared_loss(self):
        for name, data in (('png', f.basic_png()), ('webp', f.riff(f.vp8x(0x0C), f.ck(b'VP8 ', f.vp8()), f.webp_exif(), f.webp_xmp())), ('heif', f.heic_basic(with_metadata=True))):
            plan = self.plan(data)
            self.assertEqual(plan['iptc']['state'], 'notApplicable', name)
            self.assertFalse(plan['iptc']['changed'], name)
            skipped = [d for field in plan['fields'].values() for d in field['destinations'] if d['family'] == 'iptc']
            self.assertTrue(skipped and all(d['state'] == 'skip' and d['reason'] == 'notAvailableInContainer' for d in skipped), name)
            losses = [loss for field in plan['fields'].values() for loss in field['losses']]
            self.assertIn({'field': 'title', 'destination': 'IPTC:ObjectName', 'reason': 'iptcNotAvailableInContainer', 'treatment': 'companionNotWritten'}, losses, name)

    def test_tiff_keeps_its_iptc_destination(self):
        plan = self.plan(f.three_strip_tiff_with_xmp_iptc()[0])
        self.assertEqual(plan['iptc']['state'], 'ok')
        self.assertTrue(plan['iptc']['changed'])

    def test_h2_a_heif_without_the_items_is_never_asked_to_create_them(self):
        for data in (f.heic_basic(),):
            plan = self.plan(data)
            refusal = self.fault_of(lambda: e5edit.creation_guard('heif', self.payloads(data), plan))
            self.assertEqual(refusal.code, 'HEIF_METADATA_ITEM_CREATION_UNSUPPORTED')
            self.assertEqual(refusal.observed['missing'], ['xmp'])
            self.assertEqual(refusal.observed['limitation'], 'heifNativeMetadataCreationNotReproducible')

    def fault_of(self, call):
        with self.assertRaises(edits.Refusal) as caught:
            call()
        return caught.exception

    def test_h3_existing_items_are_edited_without_a_creation_refusal(self):
        data = f.heic_basic(with_metadata=True)
        e5edit.creation_guard('heif', self.payloads(data), self.plan(data))
        e5edit.creation_guard('png', self.payloads(f.basic_png(metadata=False)), self.plan(f.basic_png(metadata=False)))      # only HEIF is guarded

    def test_tiff_iptc_digest_is_never_assigned_and_an_existing_digest_refuses_an_iptc_change(self):
        plan = self.plan(f.three_strip_tiff_with_xmp_iptc()[0])
        plan['iptc']['digest'] = True
        e5edit.tiff_iptc_guard('tiff', plan, False)
        self.assertFalse(plan['iptc']['digest'])
        refusal = self.fault_of(lambda: e5edit.tiff_iptc_guard('dng', plan, True))
        self.assertEqual(refusal.code, 'TIFF_IPTC_DIGEST_UNSUPPORTED')
        e5edit.tiff_iptc_guard('png', {'iptc': {'digest': True, 'changed': True}}, True)     # not a TIFF: untouched

    def test_iim_zero_padding_of_a_tiff_long_array_is_trimmed_only_when_the_rest_is_well_formed(self):
        iim = b'\x1c\x02\x05\x00\x04Gate'
        self.assertEqual(e5payloads.trim_iim_padding(iim + b'\0\0\0'), iim)
        self.assertEqual(e5payloads.trim_iim_padding(iim), iim)
        broken = b'\x1c\x02\x05\x00\x09Gate\0\0\0'          # the length claims 9 bytes: not padding, left as it is
        self.assertEqual(e5payloads.trim_iim_padding(broken), broken)

    def test_mailbox7_a_photoshop_resource_tail_is_found_protected_and_refused_for_writing(self):
        control, blocks = f.photoshop_tiff()
        tailed, _ = f.photoshop_tiff(tail=b'TAIL5')
        clean, dirty = e5locate.locate(control), e5locate.locate(tailed)
        self.assertTrue(clean['write']['admissible'])
        self.assertEqual([r['code'] for r in dirty['write']['refusals']], ['IPTC_RESOURCE_TAIL_UNSUPPORTED'])
        self.assertIn('photoshopResourceTailOpaque', dirty['limitations'])
        self.assertEqual(e5payloads.psir_walk(blocks)[1], b'')
        walked, tail = e5payloads.psir_walk(blocks + b'TAIL5')
        self.assertEqual((tail, [ident for ident, _, _ in walked]), (b'TAIL5', [0x0404, 0x0FA1]))
        rows = {r[1] for r in clean['protected'] if r[0] == 'tiff/psir'}
        self.assertEqual(rows, {'IFD0:0x8649:res[0x0fa1#0]'})                  # the IPTC-NAA resource is the slot; every other resource is a protected row
        self.assertIn('IFD0:0x8649:tail', {r[1] for r in dirty['protected'] if r[0] == 'tiff/psir'})
        self.assertIsNone(e5payloads.psir_walk(b'XXXX' + b'\0' * 10))            # twelve bytes that are not a resource are malformed (an 11-byte remainder is a tail, as for iptc.resources)

    def test_native_frame_keys_follow_the_container_group(self):
        spec = {'native': 'File:ImageWidth'}
        self.assertEqual(listing.native_key(spec, 'png'), 'PNG:ImageWidth')
        self.assertEqual(listing.native_key(spec, 'webp'), 'RIFF:ImageWidth')
        self.assertEqual(listing.native_key(spec, 'dng'), 'EXIF:IFD0:ImageWidth')
        self.assertEqual(listing.native_key(spec, 'jpeg'), 'File:ImageWidth')
        self.assertEqual(listing.native_key(spec, 'heif'), 'File:ImageWidth')

    def test_removal_guard_follows_the_registry(self):
        from schemaxis.adaptors.exiftool import removal
        for container, categories, code in (('heif', ['location'], 'HEIF_REMOVAL_UNSUPPORTED'), ('tiff', ['minimise'], 'MINIMISE_UNSUPPORTED_CONTAINER'), ('dng', ['minimise'], 'MINIMISE_UNSUPPORTED_CONTAINER'),
                                            ('tiff', ['thumbnails'], 'REMOVAL_CATEGORY_UNSUPPORTED_IN_CONTAINER'), ('png', ['thumbnails'], 'REMOVAL_CATEGORY_UNSUPPORTED_IN_CONTAINER')):
            self.assertEqual(self.fault_of(lambda: removal.container_guard(container, categories)).code, code, (container, categories))
        removal.container_guard('png', ['location', 'rights'])
        removal.container_guard('tiff', ['captureTime'])
        removal.container_guard('png', ['minimise'])           # AM-17: PNG and WebP offer minimise
        removal.container_guard('webp', ['minimise'])


@unittest.skipUnless(EXIFTOOL and Path(EXIFTOOL).exists(), 'a real ExifTool 13.55 is needed (SCHEMAXIS_EXIFTOOL)')
class Native(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='e5write-'))
        cls.inputs = cls.tmp / 'inputs'
        cls.inputs.mkdir()
        for name, data in fixtures().items():
            (cls.inputs / name).write_bytes(data)
        cls.runs = 0

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_doc(self, operation, names, **rest):
        type(self).runs += 1
        directory = self.tmp / ('run%d' % self.runs)
        document = doc(operation, [{'id': 'p%d' % i, 'path': str(self.inputs / n)} for i, n in enumerate(names)], **rest)
        return directory, editing.run(document, directory, executable=EXIFTOOL, timeout=300)

    def out(self, directory, index, suffix):
        return (directory / 'photos' / ('p%d%s' % (index, suffix))).read_bytes()

    def edit_one(self, name, suffix, edit=EDIT):
        directory, result = self.run_doc('editMetadata', [name], edits=edit)
        self.assertTrue(result['verified'])
        self.assertEqual((result['written'], result['refused'], result['failed']), (1, 0, 0))
        return directory, self.out(directory, 0, suffix)

    def report(self, directory):
        name = 'edit-report.json' if (directory / 'edit-report.json').exists() else 'removal-report.json'
        return json.loads((directory / name).read_text())

    # ------------------------------------------------------------------ TIFF and DNG
    def test_t1_t2_t3_t5_tiff_edits_keep_every_strip_and_tile_and_write_xmp_and_artist(self):
        second_page = bytes([70, 80, 90])
        for name, order, protected in (('tiff_le.tif', b'II', [f.STRIP]), ('tiff_be.tif', b'MM', [f.STRIP]), ('tiff_tiled.tif', b'II', f.tiled_tiff()[1]), ('tiff_twopage.tif', b'II', [f.STRIP, second_page])):
            _, out = self.edit_one(name, '.tif')
            self.assertEqual(out[:2], order, name)
            self.assertIn(TITLE.encode(), out, name)                  # the XMP packet (tag 0x02BC)
            self.assertIn(ARTIST.encode() + b'\0', out, name)         # the EXIF Artist companion
            for part in protected:
                self.assertEqual(out.count(part), 1, (name, part))

    def test_t4_the_strip_really_moves_while_its_bytes_stay(self):
        before = fixtures()['tiff_le.tif']
        _, out = self.edit_one('tiff_le.tif', '.tif')
        self.assertNotEqual(before.index(f.STRIP), out.index(f.STRIP))
        self.assertEqual(out.count(f.STRIP), 1)

    def test_d1_dng_private_data_and_raw_strip_are_byte_equal(self):
        for name in ('dng_vendor.dng', 'dng_be.dng'):
            _, out = self.edit_one(name, '.dng')
            self.assertIn(b'VendorPrivate-0123', out, name)
            self.assertIn(f.STRIP, out, name)
            self.assertIn(TITLE.encode(), out, name)

    def test_tiff_iptc_companion_is_written_when_an_iptc_block_exists(self):
        _, out = self.edit_one('tiff_iptc.tif', '.tif')
        self.assertIn(b'\x1c\x02\x05\x00\x11' + TITLE.encode(), out)        # IIM 2:5 ObjectName, 17 bytes
        self.assertIn(b'\x1c\x02\x50\x00\x08' + ARTIST.encode(), out)       # IIM 2:80 By-line

    def test_tr1_location_removal_leaves_the_image_bytes(self):
        directory, result = self.run_doc('removeMetadata', ['tiff_gps.tif'], categories=['location'])
        self.assertTrue(result['verified'])
        row = self.report(directory)['items'][0]
        self.assertEqual(row['status'], 'written')
        self.assertEqual(row['removed']['found']['ifds'], ['GPS'])
        self.assertIn(f.STRIP, self.out(directory, 0, '.tif'))

    def test_removal_over_every_container_and_nothing_to_remove_is_an_unchanged_copy(self):
        for name, suffix in (('tiff_le.tif', '.tif'), ('dng_vendor.dng', '.dng'), ('png_basic.png', '.png'), ('webp_meta.webp', '.webp'), ('webp_plain.webp', '.webp')):
            directory, result = self.run_doc('removeMetadata', [name], categories=['location', 'descriptive', 'rights'])
            self.assertTrue(result['verified'], name)
            out = self.out(directory, 0, suffix)
            if name == 'png_basic.png':
                self.assertIn(f.GAMA, out)
                self.assertIn(f.IDAT, out)
                self.assertNotIn(b'Quarry gate', out)                    # the XMP title went with the XMP chunk
            if name == 'webp_meta.webp':
                self.assertEqual(out[12:16], b'VP8 ')                   # VP8X was removed as predicted (nothing else needs it)
                self.assertIn(f.ck(b'VP8 ', f.vp8()), out)
            if name == 'webp_plain.webp':
                self.assertEqual(out, fixtures()[name])

    # ------------------------------------------------------------------ PNG
    def test_g1_png_edit_inserts_exif_and_xmp_before_idat_and_keeps_every_protected_chunk(self):
        _, out = self.edit_one('png_basic.png', '.png')
        self.assertIn(f.GAMA, out)
        self.assertIn(f.text_chunk(b'Comment', b'plain text'), out)
        self.assertIn(f.IDAT + f.IEND, out)
        self.assertTrue(out.index(b'eXIf') < out.index(b'IDAT') and out.index(b'iTXt') < out.index(b'IDAT'))
        self.assertIn(TITLE.encode(), out)

    def test_g1b_png_without_metadata_gets_xmp_only_and_no_native_warning(self):
        directory, out = self.edit_one('png_nometa.png', '.png')
        self.assertNotIn(b'eXIf', out)                                    # no Exif block is created for a field edit
        self.assertIn(TITLE.encode(), out)
        losses = [loss['reason'] for field in self.report(directory)['items'][0]['fields'].values() for loss in field['losses']]
        self.assertIn('iptcNotAvailableInContainer', losses)

    # ------------------------------------------------------------------ WebP
    def test_w1_w2_a_simple_webp_gets_a_vp8x_with_only_the_needed_flag_and_keeps_its_bitstream(self):
        for name, stream in (('webp_plain.webp', f.ck(b'VP8 ', f.vp8())), ('webp_lossless.webp', f.ck(b'VP8L', f.vp8l()))):
            _, out = self.edit_one(name, '.webp')
            self.assertEqual(out[12:16], b'VP8X', name)
            self.assertEqual(out[20], 0x04, name)                          # the XMP flag only
            self.assertIn(stream, out, name)

    def test_w3_an_extended_webp_with_metadata_keeps_vp8_and_updates_the_chunks(self):
        _, out = self.edit_one('webp_meta.webp', '.webp')
        self.assertIn(f.ck(b'VP8 ', f.vp8()), out)
        self.assertEqual(out[20] & 0x0C, 0x0C)
        self.assertIn(TITLE.encode(), out)

    # ------------------------------------------------------------------ HEIF
    def test_h3_existing_heif_items_are_edited_and_the_image_item_bytes_stay(self):
        _, out = self.edit_one('heic_meta.heic', '.heic')
        self.assertIn(HEIC_IMAGE, out)
        self.assertIn(TITLE.encode(), out)
        self.assertIn(ARTIST.encode() + b'\0', out)

    def test_h2_h4_heif_creation_and_removal_are_named_refusals_and_the_other_item_is_still_written(self):
        directory, result = self.run_doc('editMetadata', ['tiff_le.tif', 'heic_basic.heic'], edits=EDIT)
        self.assertEqual((result['written'], result['refused'], result['failed']), (1, 1, 0))
        row = self.report(directory)['items'][1]
        self.assertEqual((row['status'], row['fault']['code']), ('refused', 'HEIF_METADATA_ITEM_CREATION_UNSUPPORTED'))
        self.assertEqual(row['fault']['observed']['limitation'], 'heifNativeMetadataCreationNotReproducible')
        self.assertTrue((directory / 'outcomes' / 'p1.json').is_file())
        self.assertFalse((directory / 'photos' / 'p1.heic').exists())
        directory, result = self.run_doc('removeMetadata', ['png_basic.png', 'heic_meta.heic'], categories=['location'])
        row = self.report(directory)['items'][1]
        self.assertEqual((row['status'], row['fault']['code']), ('refused', 'HEIF_REMOVAL_UNSUPPORTED'))

    def test_minimise_and_thumbnail_refusals_are_named_per_container(self):
        for categories, code in ((['minimise'], 'MINIMISE_UNSUPPORTED_CONTAINER'), (['thumbnails'], 'REMOVAL_CATEGORY_UNSUPPORTED_IN_CONTAINER')):
            with self.assertRaises(SchemaxisError) as caught:            # every item is refused, so no item is written and the run says so
                self.run_doc('removeMetadata', ['tiff_le.tif', 'dng_vendor.dng'], categories=categories)
            self.assertEqual(caught.exception.fault.code, 'NO_USABLE_ITEMS')
            directory = self.tmp / ('run%d' % self.runs)
            for index in (0, 1):
                outcome = json.loads((directory / 'outcomes' / ('p%d.json' % index)).read_text())
                self.assertEqual((outcome['status'], outcome['fault']['code']), ('refused', code), (categories, index))
                self.assertIs(outcome['image'], False)

    # ------------------------------------------------------------------ mailbox 7: the opaque tail of a Photoshop resource block
    def refused_code(self, names, **rest):
        with self.assertRaises(SchemaxisError) as caught:
            self.run_doc('editMetadata', names, **rest)
        self.assertEqual(caught.exception.fault.code, 'NO_USABLE_ITEMS')
        outcome = json.loads((self.tmp / ('run%d' % self.runs) / 'outcomes' / 'p0.json').read_text())
        self.assertIs(outcome['image'], False)
        return outcome['fault']['code']

    def test_mailbox7_tiff_photoshop_block_clean_control_and_tail(self):
        for name, data in (('psir_control.tif', f.photoshop_tiff()[0]), ('psir_tail5.tif', f.photoshop_tiff(tail=b'TAIL5')[0]), ('psir_tail11.tif', f.photoshop_tiff(tail=b'ELEVEN-BYTE')[0])):
            (self.inputs / name).write_bytes(data)
        # the clean control: an IPTC change would need a second carrier (named refusal), a field without an IPTC companion is written and every resource is equal
        self.assertEqual(self.refused_code(['psir_control.tif'], edits={'title': {'set': TITLE}}), 'TIFF_PHOTOSHOP_IPTC_CARRIER_UNSUPPORTED')
        directory, result = self.run_doc('editMetadata', ['psir_control.tif'], edits={'rating': {'set': 4}})
        self.assertTrue(result['verified'])
        self.assertIn(f.photoshop_block(0x0FA1, b'OPAQUE-PLUGIN'), self.out(directory, 0, '.tif'))
        # the tail: native drops it on any rewrite (observed; with an 11-byte remainder it even reports 'Bad Photoshop IRB resource'), so every write is refused before native
        self.assertEqual(self.refused_code(['psir_tail5.tif'], edits={'title': {'set': TITLE}}), 'IPTC_RESOURCE_TAIL_UNSUPPORTED')
        self.assertEqual(self.refused_code(['psir_tail5.tif'], edits={'rating': {'set': 4}}), 'IPTC_RESOURCE_TAIL_UNSUPPORTED')
        self.assertEqual(self.refused_code(['psir_tail11.tif'], edits={'rating': {'set': 4}}), 'IPTC_RESOURCE_TAIL_UNSUPPORTED')

    def test_mailbox7_jpeg_app13_tail_is_refused_for_iptc_changes_and_kept_otherwise(self):
        import struct as _struct
        base = author.edit_files()['edit-ascii-iptc.jpg']
        position = 2
        while True:
            marker, length = base[position + 1], _struct.unpack_from('>H', base, position + 2)[0]
            if marker == 0xED:
                break
            position += 2 + length
        body = base[position + 4:position + 2 + length] + b'TAIL5'
        (self.inputs / 'app13_tail5.jpg').write_bytes(base[:position + 2] + _struct.pack('>H', len(body) + 2) + body + base[position + 2 + length:])
        (self.inputs / 'app13_control.jpg').write_bytes(base)
        self.assertEqual(self.refused_code(['app13_tail5.jpg'], edits={'title': {'set': TITLE}}), 'IPTC_RESOURCE_TAIL_UNSUPPORTED')
        directory, result = self.run_doc('editMetadata', ['app13_tail5.jpg'], edits={'rating': {'set': 4}})        # APP13 untouched: byte-equal, tail kept
        self.assertTrue(result['verified'])
        self.assertIn(b'TAIL5', self.out(directory, 0, '.jpg'))
        directory, result = self.run_doc('editMetadata', ['app13_control.jpg'], edits={'title': {'set': TITLE}})
        self.assertTrue(result['verified'])

    # ------------------------------------------------------------------ mutants (verify re-proves the retained bytes)
    def test_mutants_a_changed_protected_byte_is_found_with_its_exact_path(self):
        directory, _ = self.run_doc('editMetadata', ['tiff_le.tif', 'png_basic.png', 'webp_meta.webp'], edits=EDIT)
        gama_changed = f.chunk(b'gAMA', struct.pack('>I', 45456))          # a different value with a valid CRC, so only P (not the CRC check) can find it
        for index, suffix, needle, replacement, code_path in ((0, '.tif', f.STRIP, bytes([f.STRIP[0] ^ 1]) + f.STRIP[1:], 'tiff/extent[IFD0:strip[0]]'), (1, '.png', f.GAMA, gama_changed, 'png/ancillary[gAMA#0]'),
                                                              (2, '.webp', f.ck(b'VP8 ', f.vp8()), f.ck(b'VP8 ', f.vp8())[:20] + b'\x11' + f.ck(b'VP8 ', f.vp8())[21:], 'riff/chunk[VP8 #0]')):          # a filler byte after the 10-byte frame header
            mutant = self.tmp / ('mutant%d' % self.runs) / str(index)
            type(self).runs += 1
            shutil.copytree(directory, mutant)
            published = mutant / 'photos' / ('p%d%s' % (index, suffix))
            data = published.read_bytes()
            changed = data.replace(needle, replacement, 1)
            self.assertNotEqual(changed, data)
            published.write_bytes(changed)
            with self.assertRaises(SchemaxisError) as caught:
                editing.verify(mutant, executable=EXIFTOOL)
            fault = caught.exception.fault
            self.assertEqual(fault.code, 'VERIFICATION_FAILED', (index, fault.to_dict()))
            cause = fault.observed['cause']
            self.assertEqual(cause['code'], 'PRESERVATION_MISMATCH', (index, cause))
            self.assertEqual(cause['observed']['problems'][0]['path'], code_path, index)          # the exact protected fingerprint path, written by hand above
            self.assertEqual(cause['location'], '$.items[%d].image' % index, index)

    # ------------------------------------------------------------------ X-6: signature, not suffix
    def test_x6_a_tif_that_is_really_a_png_is_located_as_png_with_a_note_and_named_by_what_it_is(self):
        folder = self.tmp / 'mixed'
        folder.mkdir()
        (folder / 'really.tif').write_bytes(f.basic_png())
        (folder / 'plain.png').write_bytes(f.basic_png(metadata=False))
        document = {'version': 'schemaxis.exiftool/1', 'operation': 'inspectMetadata', 'profiles': ['capture', 'description'], 'nativeListing': True,
                    'media': {'folder': {'path': str(folder), 'extensions': ['.tif', '.png'], 'sidecars': 'none'}}}
        directory = self.tmp / 'mixed-run'
        result = workbench.run(document, directory, executable=EXIFTOOL)
        self.assertEqual((result['succeeded'], result['faulted']), (2, 0))
        captures = json.loads((directory / 'captures.json').read_text())['items']
        self.assertEqual({c['id']: (c['container'], Path(c['file']).suffix) for c in captures}, {'plain': ('png', '.png'), 'really': ('png', '.png')})
        metadata = (directory / 'metadata.json').read_text()
        self.assertIn('EXTENSION_MISMATCH', metadata)


if __name__ == '__main__':
    unittest.main()
