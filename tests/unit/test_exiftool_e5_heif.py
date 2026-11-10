"""Host tests of the E5 HEIF locator (cases H-1..H-20 with AM-1..AM-6). Basis label P-draft: MPEG w23813 (14496-12) and w18310 with COR1 (23008-12).

Hand-built boxes carry opaque ``hvc1``/``av01`` payloads; no image is decoded and no real HEIC file is used.
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
from schemaxis.adaptors.exiftool import e5common as common, e5heif, e5payloads  # noqa: E402

IMG = b'OPAQUE-HVC1-IMAGE-24BYTES'[:24]
EXIF = f.exif_item()
IMAGE = {'id': 1, 'type': b'hvc1', 'payload': IMG}
XMP_ITEM = {'id': 3, 'type': b'mime', 'content_type': b'application/rdf+xml', 'payload': f.XMP_TEXT}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def codes(found):
    return [r['code'] for r in found['write']['refusals']]


def slot(found, family):
    return [s for s in found['slots'] if s['family'] == family][0]


def rows(found, role):
    return {k: (n, d) for r, k, n, d in found['protected'] if r == role}


def exif_ref(ident=2, to=(1,)):
    return (b'cdsc', ident, list(to))


class Basics(unittest.TestCase):
    def test_h1_minimal_heic(self):
        found = e5heif.locate(f.heic_basic())
        self.assertEqual('heif', found['container'])
        self.assertEqual('heic', found['brand'])
        self.assertEqual({'width': 64, 'height': 48}, found['frame'])
        self.assertEqual({'item': 1, 'type': 'hvc1'}, found['primary'])
        self.assertEqual(['absent', 'absent', 'absent'], [s['state'] for s in found['slots']])
        self.assertEqual([], found['exif'] + found['xmp'])
        self.assertEqual((24, sha(IMG)), rows(found, 'heif/item')['1'])
        self.assertEqual(['ftyp', 'hdlr', 'pitm'], [k for r, k, _, _ in found['protected'] if r in ('heif/ftyp', 'heif/hdlr', 'heif/pitm')])
        self.assertEqual(1, len(rows(found, 'heif/iprp')))
        self.assertIn('heifSpecDraftOnly', found['limitations'])
        self.assertTrue(found['write']['admissible'])

    def test_h2_slot_items_are_payloads_not_protected_rows(self):
        found = e5heif.locate(f.heic_basic(with_metadata=True))
        self.assertEqual([f.exif_stream()], found['exif'])
        self.assertEqual([f.XMP_TEXT], found['xmp'])
        self.assertEqual(('present', 2), (slot(found, 'exif')['state'], slot(found, 'exif')['item']))
        self.assertEqual(('present', 3), (slot(found, 'xmp')['state'], slot(found, 'xmp')['item']))
        self.assertEqual({'1'}, set(rows(found, 'heif/item')))
        self.assertEqual({}, rows(found, 'heif/iref'))                 # the cdsc entries come from slot items
        decoded = e5payloads.decode(found)
        self.assertEqual('ok', decoded['exif'][0][0])
        self.assertEqual({'x-default': 'Quarry gate'}, decoded['xmp'][0][1]['dc:title'][0]['value'])

    def test_h3_growing_the_exif_item_relocates_the_image_and_keeps_the_fingerprint(self):
        def build(artist):
            items = [{'id': 2, 'type': b'Exif', 'payload': f.exif_item('<', artist)}, dict(IMAGE)]
            return f.heic(items, refs=[exif_ref()])
        short, long = e5heif.locate(build('A')), e5heif.locate(build('A. Mason, field assistant to the survey party'))
        self.assertNotEqual([r for r in short['ranges'] if r[0] == 'heif/item'], [r for r in long['ranges'] if r[0] == 'heif/item'])
        self.assertEqual([], common.compare(short['protected'], long['protected']))
        self.assertNotEqual(short['exif'], long['exif'])

    def test_h18_base_offset_is_additive(self):
        plain = e5heif.locate(f.heic_basic())
        based = e5heif.locate(f.heic([dict(IMAGE, base=100)], base_size=4))
        self.assertEqual(plain['frame'], based['frame'])
        self.assertEqual([], common.compare(plain['protected'], based['protected']))

    def test_iloc_version_0_and_idat_construction(self):
        self.assertEqual((24, sha(IMG)), rows(e5heif.locate(f.heic([IMAGE], version=0)), 'heif/item')['1'])
        items = [dict(IMAGE), {'id': 2, 'type': b'Exif', 'payload': EXIF, 'method': 1, 'idat_offset': 0}]
        found = e5heif.locate(f.heic(items, refs=[exif_ref()], idat=EXIF))
        self.assertEqual([f.exif_stream()], found['exif'])
        with self.assertRaises(common.Refused) as caught:
            e5heif.locate(f.heic(items, refs=[exif_ref()]))
        self.assertEqual('INVALID_PHOTO_DATA', caught.exception.code)

    def test_h10_avif_follows_the_same_rules(self):
        found = e5heif.locate(f.heic([{'id': 1, 'type': b'av01', 'payload': IMG}], brand=b'avif', compat=(b'mif1', b'miaf')))
        self.assertEqual(('heif', 'avif', 'av01'), (found['container'], found['brand'], found['primary']['type']))

    def test_h5_grid_primary_with_tiles_and_thumbnail(self):
        tiles = [{'id': 2 + i, 'type': b'hvc1', 'payload': b'TILE-%d' % i} for i in range(4)]
        items = [{'id': 1, 'type': b'grid', 'payload': b'GRIDDESC'}] + tiles + [{'id': 6, 'type': b'hvc1', 'payload': b'THUMB!'}]
        refs = [(b'dimg', 1, [2, 3, 4, 5]), (b'thmb', 6, [1])]
        build = lambda extra, extra_refs: f.heic(items + extra, refs=refs + extra_refs, props=((b'ispe', 128, 96),), associations={1: [1]})
        before = e5heif.locate(build([], []))
        self.assertEqual({'width': 128, 'height': 96}, before['frame'])
        self.assertIn('heifDerivedPrimary', before['notes'])
        self.assertEqual({'1', '2', '3', '4', '5', '6'}, set(rows(before, 'heif/item')))
        self.assertEqual((6, sha(b'THUMB!')), rows(before, 'heif/item')['6'])
        self.assertEqual(['0', '1'], sorted(rows(before, 'heif/iref')))
        after = e5heif.locate(build([{'id': 7, 'type': b'Exif', 'payload': EXIF}], [exif_ref(7)]))
        self.assertEqual([f.exif_stream()], after['exif'])
        self.assertEqual([], common.compare(before['protected'], after['protected']))

    def test_other_boxes_are_protected_or_ignored_as_the_profile_says(self):
        found = e5heif.locate(f.heic([IMAGE], extra_top=f.box(b'abcd', b'zz') + f.box(b'free', b'xx') + f.box(b'skip', b'yy'), extra_meta=f.box(b'grpl', b'')))
        self.assertEqual(['abcd#0'], list(rows(found, 'heif/box')))
        self.assertEqual(['grpl#0'], list(rows(found, 'heif/meta')))
        found = e5heif.locate(f.heic([IMAGE], top_after=f.box(b'mdat', b'unreferenced')))
        self.assertIn('heifUnreferencedMdatBytesNotProtected', found['notes'])


class ZeroLengthExtents(unittest.TestCase):
    def test_h11_exif_item_with_extent_length_zero_is_unreadable_never_absent(self):
        items = [dict(IMAGE), {'id': 2, 'type': b'Exif', 'payload': EXIF, 'implied': True}]
        found = e5heif.locate(f.heic(items, refs=[exif_ref()]))
        self.assertEqual(('unreadable', 'HEIF_IMPLIED_EXTENT'), (slot(found, 'exif')['state'], slot(found, 'exif')['code']))
        self.assertIn('HEIF_IMPLIED_EXTENT', codes(found))
        self.assertIn('heifImpliedExtentLength', found['notes'])
        self.assertEqual([], found['exif'])
        self.assertEqual((24, sha(IMG)), rows(found, 'heif/item')['1'])         # the image item stays readable and protected

    def test_h12_shape_of_the_native_all_equals_output(self):
        items = [dict(IMAGE), {'id': 2, 'type': b'Exif', 'share_with': 1, 'implied': True}, dict(XMP_ITEM, share_with=1, implied=True, payload=b'')]
        data = f.heic(items, refs=[exif_ref(2), exif_ref(3)])
        found = e5heif.locate(data)
        start = data.index(IMG)
        self.assertEqual(['unreadable', 'unreadable'], [slot(found, 'exif')['state'], slot(found, 'xmp')['state']])
        self.assertEqual(['HEIF_IMPLIED_EXTENT', 'HEIF_IMPLIED_EXTENT'], [slot(found, 'exif')['code'], slot(found, 'xmp')['code']])
        self.assertIn('HEIF_EXTENT_OVERLAP', found['notes'])
        self.assertEqual([[(start, 24)]] * 3, [i['resolved'] for i in found['items']])      # items 2 and 3 resolve to the whole image payload
        self.assertIn('HEIF_EXTENT_OVERLAP', codes(found))

    def test_h12m_a_locator_that_reads_length_zero_as_empty_fails_h11_and_h12(self):
        original = e5heif.parse_iloc

        def empty_zero(data, node):
            items = original(data, node)
            for item in items:
                item['extents'] = [(offset, 0, False) for offset, length, implied in item['extents']] if any(i for _, _, i in item['extents']) else item['extents']
            return items

        items = [dict(IMAGE), {'id': 2, 'type': b'Exif', 'share_with': 1, 'implied': True}, dict(XMP_ITEM, share_with=1, implied=True, payload=b'')]
        data = f.heic(items, refs=[exif_ref(2), exif_ref(3)])
        e5heif.parse_iloc = empty_zero
        try:
            mutant = e5heif.locate(data)
        finally:
            e5heif.parse_iloc = original
        self.assertEqual('present', slot(mutant, 'xmp')['state'])                 # an empty XMP packet is read as present: silently wrong
        self.assertNotEqual('HEIF_IMPLIED_EXTENT', slot(mutant, 'exif').get('code'))
        self.assertNotIn('HEIF_IMPLIED_EXTENT', codes(mutant))
        real = e5heif.locate(data)
        self.assertEqual(['unreadable', 'unreadable'], [slot(real, 'exif')['state'], slot(real, 'xmp')['state']])


class Association(unittest.TestCase):
    def test_h13_two_exif_items_are_ambiguous(self):
        items = [dict(IMAGE), {'id': 2, 'type': b'Exif', 'payload': f.exif_item('<', 'First')}, {'id': 4, 'type': b'Exif', 'payload': f.exif_item('>', 'Second')}]
        found = e5heif.locate(f.heic(items, refs=[exif_ref(2), exif_ref(4)]))
        self.assertEqual('ambiguous', slot(found, 'exif')['state'])
        self.assertEqual([f.exif_stream('<', 'First'), f.exif_stream('>', 'Second')], found['exif'])
        self.assertEqual(['HEIF_MULTIPLE_METADATA_ITEMS'], codes(found))

    def test_h14_a_shared_metadata_item_reads_but_does_not_write(self):
        items = [dict(IMAGE), {'id': 5, 'type': b'hvc1', 'payload': b'SECOND'}, dict(XMP_ITEM)]
        found = e5heif.locate(f.heic(items, refs=[(b'cdsc', 3, [1, 5])]))
        self.assertEqual('present', slot(found, 'xmp')['state'])
        self.assertEqual([f.XMP_TEXT], found['xmp'])
        self.assertEqual(['HEIF_SHARED_METADATA_ITEM'], codes(found))

    def test_h15_metadata_of_another_image_is_protected_like_an_image_item(self):
        items = [dict(IMAGE), {'id': 4, 'type': b'hvc1', 'payload': b'THUMB!'}, {'id': 2, 'type': b'Exif', 'payload': EXIF}]
        data = f.heic(items, refs=[exif_ref(2, (4,))])
        found = e5heif.locate(data)
        self.assertEqual('absent', slot(found, 'exif')['state'])
        self.assertIn('metadataForNonPrimaryItem:2', found['notes'])
        self.assertEqual((len(EXIF), sha(EXIF)), rows(found, 'heif/item')['2'])
        self.assertIn('2', rows(found, 'heif/infe'))
        mutant = bytearray(data)
        mutant[data.index(EXIF) + 10] ^= 0xFF
        faults = common.compare(found['protected'], e5heif.locate(bytes(mutant))['protected'])
        self.assertEqual(['heif/item[2]'], [x['path'] for x in faults])

    def test_h16_protected_item(self):
        ipro = f.full(b'ipro', struct.pack('>H', 1) + f.box(b'sinf', b''))
        items = [dict(IMAGE), {'id': 2, 'type': b'Exif', 'payload': EXIF, 'protection': 1}]
        found = e5heif.locate(f.heic(items, refs=[exif_ref()], extra_meta=ipro))
        self.assertEqual(('unreadable', 'HEIF_PROTECTED_ITEM'), (slot(found, 'exif')['state'], slot(found, 'exif')['code']))
        self.assertIn('HEIF_PROTECTED_ITEM', codes(found))
        self.assertEqual((24, sha(IMG)), rows(found, 'heif/item')['1'])

    def test_h17_external_data_reference(self):
        items = [dict(IMAGE), {'id': 2, 'type': b'Exif', 'payload': EXIF, 'dri': 1}]
        found = e5heif.locate(f.heic(items, refs=[exif_ref()]))
        self.assertEqual(('unsupported', 'HEIF_EXTERNAL_DATA'), (slot(found, 'exif')['state'], slot(found, 'exif')['code']))
        self.assertEqual(['HEIF_EXTERNAL_DATA'], codes(found))

    def test_h6_construction_method_2_is_permitted_by_the_standard_but_unsupported_here(self):
        items = [dict(IMAGE), {'id': 2, 'type': b'hvc1', 'method': 2, 'offset': 0, 'length': 4, 'payload': b''}]
        found = e5heif.locate(f.heic(items))
        self.assertEqual(['HEIF_ITEM_CONSTRUCTION_UNSUPPORTED'], codes(found))
        self.assertEqual({'width': 64, 'height': 48}, found['frame'])
        self.assertIn('2', rows(found, 'heif/infe'))
        self.assertNotIn('2', rows(found, 'heif/item'))

    def test_references_must_name_items_once(self):
        self.assertEqual(['HEIF_REFERENCE_INVALID'], codes(e5heif.locate(f.heic([dict(IMAGE)], refs=[(b'thmb', 1, [9])]))))
        self.assertEqual(['HEIF_REFERENCE_INVALID'], codes(e5heif.locate(f.heic([dict(IMAGE), {'id': 2, 'type': b'hvc1', 'payload': b'T'}], refs=[(b'dimg', 1, [2, 2])]))))
        duplicate = f.heic([dict(IMAGE), {'id': 2, 'type': b'hvc1', 'payload': b'AA'}, {'id': 2, 'type': b'hvc1', 'payload': b'BB'}])
        self.assertIn('HEIF_REFERENCE_INVALID', codes(e5heif.locate(duplicate)))


class FingerprintMutants(unittest.TestCase):
    def test_h19_hidden_flag_flip_changes_the_infe_row(self):
        data = bytearray(f.heic_basic())
        before = e5heif.locate(bytes(data))
        data[data.index(b'infe') + 7] |= 1
        faults = common.compare(before['protected'], e5heif.locate(bytes(data))['protected'])
        self.assertEqual(['heif/infe[1]'], [x['path'] for x in faults])

    def test_image_payload_and_property_mutants_name_their_role(self):
        data = f.heic_basic()
        before = e5heif.locate(data)
        flipped = bytearray(data)
        flipped[data.index(IMG) + 5] ^= 1
        self.assertEqual(['heif/item[1]'], [x['path'] for x in common.compare(before['protected'], e5heif.locate(bytes(flipped))['protected'])])
        props = bytearray(data)
        props[data.index(b'ispe') + 8:data.index(b'ispe') + 12] = struct.pack('>I', 65)
        self.assertEqual(['heif/iprp[iprp]'], [x['path'] for x in common.compare(before['protected'], e5heif.locate(bytes(props))['protected'])])

    def test_iref_entries_other_than_slot_cdsc_are_protected(self):
        items = [dict(IMAGE), {'id': 2, 'type': b'hvc1', 'payload': b'THUMB!'}]
        before = e5heif.locate(f.heic(items, refs=[(b'thmb', 2, [1])]))
        after = e5heif.locate(f.heic(items, refs=[(b'thmb', 2, [1]), (b'auxl', 2, [1])]))
        self.assertEqual(['heif/iref[1]'], [x['path'] for x in common.compare(before['protected'], after['protected'])])

    def test_v1_iref_encodes_the_same_entries_as_v0(self):
        items = [dict(IMAGE), {'id': 2, 'type': b'hvc1', 'payload': b'THUMB!'}]
        v0 = f.heic(items, refs=[(b'thmb', 2, [1])])
        v1 = f.heic(items, refs=[(b'thmb', 2, [1])], iref_version=1)
        self.assertNotEqual(v0, v1)
        self.assertEqual(e5heif.locate(v0)['protected'][-1], e5heif.locate(v1)['protected'][-1])
        self.assertEqual('heif/iref', e5heif.locate(v1)['protected'][-1][0])

    def test_h20_exif_header_offset_is_bounded(self):
        for payload in (struct.pack('>I', 0xFFFFFFF0) + b'Exif\0\0' + f.exif_stream(), struct.pack('>I', 0) + b'JUNK', b''):
            items = [dict(IMAGE), {'id': 2, 'type': b'Exif', 'payload': payload if payload else b'\0'}]
            found = e5heif.locate(f.heic(items, refs=[exif_ref()]))
            self.assertEqual(('unreadable', 'HEIF_EXIF_HEADER_INVALID'), (slot(found, 'exif')['state'], slot(found, 'exif')['code']))
        valid = f.heic([dict(IMAGE), {'id': 2, 'type': b'Exif', 'payload': struct.pack('>I', 0) + f.exif_stream()}], refs=[exif_ref()])
        self.assertEqual([f.exif_stream()], e5heif.locate(valid)['exif'])


class Bounds(unittest.TestCase):
    def nested(self, count):
        box = f.box(b'free', b'')
        for _ in range(count):
            box = f.box(b'dinf', box)
        return box

    def test_h8_depth_and_box_budgets(self):
        self.assertEqual('heif', e5heif.locate(f.heic([IMAGE], extra_top=self.nested(7)))['container'])
        for extra in (self.nested(8), f.box(b'dinf', f.box(b'free', b'') * 5000), f.box(b'free', b'') * 65):
            with self.assertRaises(common.Refused) as caught:
                e5heif.locate(f.heic([IMAGE], extra_top=extra))
            self.assertEqual('HEIF_BOUND', caught.exception.code)

    def test_h7_extents_beyond_the_file_and_overlapping_items(self):
        data = f.heic_basic()
        start = data.index(IMG)
        broken = data.replace(struct.pack('>II', start, 24), struct.pack('>II', start, 5000))
        self.assertNotEqual(data, broken)
        with self.assertRaises(common.Refused) as caught:
            e5heif.locate(broken)
        self.assertEqual('INVALID_PHOTO_DATA', caught.exception.code)
        found = e5heif.locate(f.heic([dict(IMAGE), {'id': 2, 'type': b'hvc1', 'share_with': 1, 'payload': IMG}]))
        self.assertIn('HEIF_EXTENT_OVERLAP', found['notes'])
        self.assertEqual(['HEIF_EXTENT_OVERLAP'], codes(found))

    def test_h9_sequence_brand_only(self):
        with self.assertRaises(common.Refused) as caught:
            e5heif.locate(f.heic([IMAGE], brand=b'msf1', compat=(b'iso8',)))
        self.assertEqual('UNSUPPORTED_MEDIA', caught.exception.code)

    def test_structure_failures_are_unreadable(self):
        data = f.heic_basic()
        for broken, code in ((data.replace(b'pict', b'vide'), 'UNSUPPORTED_MEDIA'), (data.replace(b'meta', b'mett'), 'INVALID_PHOTO_DATA'), (data[:30], 'INVALID_PHOTO_DATA'),
                             (f.heic([IMAGE], primary=9), 'INVALID_PHOTO_DATA'), (b'\0' * 8 + b'ftypheic', 'UNSUPPORTED_MEDIA'), (b'not heif at all, but long enough', 'INVALID_PHOTO_DATA')):
            with self.assertRaises(common.Refused) as caught:
                e5heif.locate(broken)
            self.assertEqual(code, caught.exception.code)

    def test_nested_size_zero_and_oversized_boxes(self):
        data = f.heic_basic()
        with self.assertRaises(common.Refused) as caught:
            e5heif.locate(data[:data.index(b'meta') - 4] + struct.pack('>I', 0xFFFFFF) + data[data.index(b'meta'):])
        self.assertEqual('INVALID_PHOTO_DATA', caught.exception.code)

    def test_oversized_file(self):
        with self.assertRaises(common.Refused) as caught:
            e5heif.locate(bytes(e5heif.MAX_BYTES + 1))
        self.assertEqual('PHOTO_RESOURCE_LIMIT', caught.exception.code)


if __name__ == '__main__':
    unittest.main()
