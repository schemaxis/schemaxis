"""E5 completion-repair cases (the prereview findings E5C-1 to E5C-6 and the canonical orphan-time adoption), each a literal case against a genuine ExifTool 13.55 (SCHEMAXIS_EXIFTOOL) or the host only.

Every expectation is a literal written in this file: the fixtures are assembled from raw bytes (JPEG segments, TIFF entries, ISO-BMFF boxes), the expected codes, locations, names and byte strings are
hand-written, and the produced files are read with the standard library only to compare with those literals. Nothing here decodes pixels. These are controls (and one family of named refusals), never
support rows: the supported cells of ``tools/qualify_exiftool_containers.py`` are its explicit finite list.
"""
import csv
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

import exiftool_e3_fixtures as e3  # noqa: E402
import exiftool_e4_fixtures as f4  # noqa: E402
import exiftool_e5_fixtures as f5  # noqa: E402
from schemaxis import workflow  # noqa: E402
from schemaxis.adaptors.exiftool import adaptor, e5edit, e5locate, e5tiff, edits, mediaset, naming, records  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402

EXIFTOOL = os.environ.get('SCHEMAXIS_EXIFTOOL')
V = 'schemaxis.exiftool/1'
TAIL = b'TAIL5'


def with_tail(base, tail=TAIL):
    """The same JPEG whose APP13 Photoshop block ends with ``tail``, opaque bytes shorter than a resource header that no resource owns."""
    position = 2
    while True:
        marker, length = base[position + 1], struct.unpack_from('>H', base, position + 2)[0]
        if marker == 0xED:
            break
        position += 2 + length
    body = base[position + 4:position + 2 + length] + tail
    return base[:position + 2] + struct.pack('>H', len(body) + 2) + body + base[position + 2 + length:]


class Case(unittest.TestCase):
    """A fresh private directory per class and one real native run per call."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='e5-completion-')).resolve()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.media = cls.tmp / 'media'
        cls.media.mkdir()
        cls.runs = 0

    def put(self, name, data):
        (self.media / name).write_bytes(data)
        return str(self.media / name)

    def go(self, document):
        type(self).runs += 1
        out = self.tmp / ('run%d' % self.runs)
        return out, adaptor.run(document, out, executable=EXIFTOOL, timeout=300)

    def refused_run(self, document):
        """A run in which every item is refused: ``NO_USABLE_ITEMS`` with its ordered first faults, and nothing written or published."""
        type(self).runs += 1
        out = self.tmp / ('run%d' % self.runs)
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.run(document, out, executable=EXIFTOOL, timeout=300)
        self.assertEqual(caught.exception.fault.code, 'NO_USABLE_ITEMS')
        self.assertFalse(list((out / 'photos').glob('*')) if (out / 'photos').exists() else [], 'nothing is published')
        self.assertFalse([p for p in out.rglob('write-*') if p.is_file()] if out.exists() else [], 'no write was attempted')
        return caught.exception.fault.observed['firstFaults']

    def published(self, out, name):
        return next(p for p in sorted((out / 'photos').glob(name + '.*')) if not p.name.endswith('.metadata.json')).read_bytes()


@unittest.skipUnless(EXIFTOOL and Path(EXIFTOOL).exists(), 'a real ExifTool 13.55 is needed (SCHEMAXIS_EXIFTOOL)')
class TailedJpeg(Case):
    """E5C-1: an IPTC rebuild of a JPEG whose Photoshop block ends with opaque bytes is refused before native by the one shared guard, whichever operation plans it; a plan that leaves the IPTC alone
    and a clean block are written and verified."""
    CLASH = ('IPTC_RESOURCE_TAIL_UNSUPPORTED', '$.items[t]')

    def doc_correct(self, path, seconds='3600'):
        return {'version': V, 'operation': 'correctTime', 'media': {'items': [{'id': 't', 'path': path}]}, 'corrections': [{'group': 'dev1', 'shift': {'seconds': seconds}}]}

    def assert_tail_refusal(self, faults, only=True):
        first = faults[0]
        self.assertEqual((first['code'], first['location']), self.CLASH)
        self.assertEqual((first['observed']['tailBytes'], first['observed']['limitation']), (5, 'photoshopResourceTailOpaque'))
        self.assertIn('5 opaque byte(s)', first['message'])
        if only:
            self.assertEqual([f['code'] for f in faults], ['IPTC_RESOURCE_TAIL_UNSUPPORTED'])

    def test_correct_time_into_a_tailed_block_that_holds_the_iptc_time_is_refused_before_native(self):
        path = self.put('tail.jpg', with_tail(e3.full_time()))
        before = Path(path).read_bytes()
        self.assert_tail_refusal(self.refused_run(self.doc_correct(path)))
        self.assertEqual(Path(path).read_bytes(), before)

    def test_copy_capture_time_into_a_tailed_block_is_refused_before_native(self):
        source = self.put('src.jpg', e3.full_time(dto='2025:06:01 08:00:00', off='-05:00', sub='34', xmp=e3.xmp_properties(captured='2025-06-01T08:00:00.34-05:00'), iptc=[(2, 55, '20250601'), (2, 60, '080000-0500')]))
        dest = self.put('dest.jpg', with_tail(e3.full_time()))
        faults = self.refused_run({'version': V, 'operation': 'copyMetadata', 'media': {'items': [{'id': 's', 'path': source}, {'id': 't', 'path': dest}]}, 'source': {'item': 's'},
                                   'transfer': {'groups': ['captureTime']}, 'policies': {'existing': 'replace'}})
        by_location = {f['location']: f for f in faults}
        self.assertEqual(by_location['$.items[t]']['code'], 'IPTC_RESOURCE_TAIL_UNSUPPORTED')

    def test_copy_descriptive_into_a_tailed_block_is_refused_before_native(self):
        dest = self.put('dest.jpg', with_tail(e3.full_time()))
        source = self.put('master.jpg', f4.master())
        faults = self.refused_run({'version': V, 'operation': 'copyMetadata', 'media': {'items': [{'id': 's', 'path': source}, {'id': 't', 'path': dest}]}, 'source': {'item': 's'},
                                   'transfer': {'groups': ['descriptive']}, 'policies': {'existing': 'replace'}})
        by_location = {f['location']: f for f in faults}
        self.assertEqual((by_location['$.items[t]']['code'], by_location['$.items[t]']['observed']['tailBytes']), ('IPTC_RESOURCE_TAIL_UNSUPPORTED', 5))

    def test_apply_sidecar_into_a_tailed_block_is_refused_before_native(self):
        master = self.put('m.jpg', f4.master())
        exported, _ = self.go({'version': V, 'operation': 'exportSidecar', 'media': {'items': [{'id': 'm', 'path': master}]}, 'transfer': {'groups': ['descriptive']}})
        sidecar = str(exported / 'sidecars' / 'm.xmp')
        dest = self.put('s.jpg', with_tail(e3.full_time()))
        faults = self.refused_run({'version': V, 'operation': 'applySidecar', 'media': {'items': [{'id': 't', 'path': dest, 'sidecar': sidecar}]}, 'source': {'sidecar': 'declared'},
                                   'transfer': {'groups': ['descriptive']}, 'policies': {'existing': 'replace'}})
        self.assert_tail_refusal(faults)

    def test_a_tailed_block_whose_iptc_the_plan_leaves_alone_is_written_and_keeps_its_tail(self):
        # IPTC holds no capture time, so a time correction writes Exif and XMP only; the block is neither parsed for rewriting nor rebuilt
        data = with_tail(e3.jpeg(xmp=e3.xmp_properties(captured='2026-03-01T12:00:00.12+01:00'), iptc=[(2, 5, 'Quarry')]))
        out, result = self.go(self.doc_correct(self.put('keep.jpg', data)))
        self.assertTrue(result['verified'])
        self.assertEqual((result['written'], result['refused'], result['failed']), (1, 0, 0))
        published = self.published(out, 't')
        self.assertEqual(published.count(TAIL), 1)
        self.assertEqual(e3.exif_ascii(published, 'ExifIFD', 0x9003), '2026:03:01 13:00:00')
        self.assertEqual(adaptor.verify(out, executable=EXIFTOOL)['nativeReplay'], 'fresh-replay-matched')

    def test_a_clean_block_is_rewritten_and_verified_by_the_same_plans(self):
        out, result = self.go(self.doc_correct(self.put('clean.jpg', e3.full_time())))
        self.assertTrue(result['verified'])
        published = self.published(out, 't')
        self.assertIn(b'130000+0100', published)
        self.assertNotIn(b'120000+0100', published)
        self.assertEqual(adaptor.verify(out, executable=EXIFTOOL)['nativeReplay'], 'fresh-replay-matched')

    def test_an_edit_metadata_title_into_the_same_tailed_block_is_still_refused_by_the_edit_location(self):
        dest = self.put('edit.jpg', with_tail(e3.full_time()))
        faults = self.refused_run({'version': V, 'operation': 'editMetadata', 'media': {'items': [{'id': 't', 'path': dest}]}, 'edits': {'title': {'set': 'Probe'}}})
        self.assertEqual((faults[0]['code'], faults[0]['location']), ('IPTC_RESOURCE_TAIL_UNSUPPORTED', '$.edits'))


AVIF = f5.heic([{'id': 1, 'type': b'av01', 'payload': b'OPAQUE-AV01-IMAGE-24BYTE'[:24]}], brand=b'avif', compat=(b'mif1', b'miaf'))
HEIC = f5.heic_basic()


class AvifNamingHost(unittest.TestCase):
    """E5C-2, host only: the canonical extension of a HEIF follows the located brand (the one rule of ``e5profiles.extension``), keepOriginal keeps the suffix."""

    def test_the_canonical_extension_of_a_heif_follows_its_brand(self):
        rule = {'extension': 'canonical'}
        self.assertEqual(naming.extension_of(rule, {'container': 'heif', 'suffix': '.avif', 'brand': 'avif'})[0], '.avif')
        self.assertEqual(naming.extension_of(rule, {'container': 'heif', 'suffix': '.heic', 'brand': 'heic'})[0], '.heic')
        self.assertEqual(naming.extension_of(rule, {'container': 'heif', 'suffix': '.heif', 'brand': 'mif1'})[0], '.heic')
        self.assertEqual(naming.extension_of(rule, {'container': 'heif', 'suffix': '.avif', 'brand': 'avif'})[1], None)
        keep = {'extension': 'keepOriginal'}
        self.assertEqual((naming.extension_of(keep, {'container': 'heif', 'suffix': '.avif', 'brand': 'avif'})[0], naming.extension_of(keep, {'container': 'heif', 'suffix': '.HEIF', 'brand': 'heic'})[0]), ('.avif', '.heif'))

    def test_the_other_containers_keep_their_canonical_extension(self):
        for container, suffix, expected in (('jpeg', '.jpeg', '.jpg'), ('tiff', '.tiff', '.tif'), ('dng', '.dng', '.dng'), ('png', '.png', '.png'), ('webp', '.webp', '.webp')):
            self.assertEqual(naming.extension_of({'extension': 'canonical'}, {'container': container, 'suffix': suffix, 'brand': None})[0], expected, container)


@unittest.skipUnless(EXIFTOOL and Path(EXIFTOOL).exists(), 'a real ExifTool 13.55 is needed (SCHEMAXIS_EXIFTOOL)')
class AvifNaming(Case):
    """E5C-2, native: planNames and organiseCopies name an AVIF ``.avif`` under the default canonical rule, a HEIC ``.heic``; the written copies are the exact input bytes."""

    def items(self):
        return [{'id': 'pic', 'path': self.put('pic.avif', AVIF)}, {'id': 'ctl', 'path': self.put('ctl.heic', HEIC)}]

    def test_plan_names_canonical_names_the_avif_by_its_brand(self):
        out, result = self.go({'version': V, 'operation': 'planNames', 'media': {'items': self.items()}, 'name': [{'token': 'itemId'}], 'extension': 'canonical'})
        with open(out / 'names.csv', newline='') as stream:
            csv_rows = sorted((r['id'], r['status'], r['relativePath']) for r in csv.DictReader(stream))
        self.assertEqual(csv_rows, [('ctl', 'planned', 'ctl.heic'), ('pic', 'planned', 'pic.avif')])
        plan = {r['id']: r['relativePath'] for r in json.loads((out / 'names-plan.json').read_text())['items']}
        self.assertEqual(plan, {'pic': 'pic.avif', 'ctl': 'ctl.heic'})

    def test_organise_copies_canonical_writes_the_avif_as_dot_avif_with_its_exact_bytes(self):
        out, result = self.go({'version': V, 'operation': 'organiseCopies', 'media': {'items': self.items()}, 'names': {'name': [{'token': 'itemId'}], 'extension': 'canonical'}})
        self.assertTrue(result['verified'])
        self.assertEqual((result['written'], result['refused'], result['failed']), (2, 0, 0))
        self.assertEqual(sorted(p.name for p in (out / 'organised').iterdir() if not p.name.endswith('.metadata.json')), ['ctl.heic', 'pic.avif'])
        self.assertEqual((out / 'organised' / 'pic.avif').read_bytes(), AVIF)
        self.assertEqual((out / 'organised' / 'ctl.heic').read_bytes(), HEIC)
        self.assertEqual(adaptor.verify(out, executable=EXIFTOOL)['nativeReplay'], 'fresh-replay-matched')

    def test_the_avif_organise_job_is_reused_on_unchanged_bytes_and_invalidated_by_changed_bytes(self):
        items = self.items()
        graph = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'organise', 'document': {'version': V, 'operation': 'organiseCopies', 'media': {'items': items}, 'names': {'name': [{'token': 'itemId'}], 'extension': 'canonical'}}}]}
        root = self.tmp / 'chain'

        def execute(**kw):
            return workflow.execute(graph, root, locations={'exiftool': EXIFTOOL}, timeout=900, **kw)
        first = execute()
        self.assertEqual([j.get('reused') for j in first['jobs']], [False])
        directory = Path(first['jobs'][0]['directory'])
        self.assertEqual((directory / 'organised' / 'pic.avif').read_bytes(), AVIF)
        self.assertEqual([bool(j.get('reused')) for j in execute(resume=True)['jobs']], [True])
        (self.media / 'pic.avif').write_bytes(f5.heic([{'id': 1, 'type': b'av01', 'payload': b'OTHER-AV01-IMAGE-24BYTE'[:24]}], brand=b'avif', compat=(b'mif1', b'miaf')))
        again = execute(resume=True)
        self.assertEqual([bool(j.get('reused')) for j in again['jobs']], [False])
        self.assertTrue((Path(again['jobs'][0]['directory']) / 'organised' / 'pic.avif').is_file())

    def test_keep_original_is_unchanged(self):
        out, result = self.go({'version': V, 'operation': 'organiseCopies', 'media': {'items': self.items()}, 'names': {'name': [{'token': 'itemId'}], 'extension': 'keepOriginal'}})
        self.assertTrue(result['verified'])
        self.assertEqual(sorted(p.name for p in (out / 'organised').iterdir() if not p.name.endswith('.metadata.json')), ['ctl.heic', 'pic.avif'])


def extent_tiff(count):
    """A literal little-endian TIFF whose single image IFD declares ``count`` one-byte strips: StripOffsets and StripByteCounts are LONG arrays of ``count`` values (the offsets all point at one zero byte)."""
    first = 8 + 2 + 12 * 4 + 4
    second = first + 4 * count
    rows = [struct.pack('<HHII', 0x0100, 4, 1, 1), struct.pack('<HHII', 0x0101, 4, 1, 1), struct.pack('<HHII', 0x0111, 4, count, first), struct.pack('<HHII', 0x0117, 4, count, second)]
    data = b'II*\0' + struct.pack('<I', 8) + struct.pack('<H', 4) + b''.join(rows) + struct.pack('<I', 0)
    data += struct.pack('<I', len(data) + 8 * count) * count + struct.pack('<I', 1) * count + b'\0'
    return data


class TiffExtentBound(unittest.TestCase):
    """E5C-5: the declared extent count is compared with the 65,536 bound BEFORE either array is unpacked, so a hostile count never allocates; ordinary arrays are unchanged."""

    def locate_counting(self, data):
        calls = []
        original = e5tiff.Walk.values

        def counting(walk, row, kinds=(3, 4)):
            calls.append((row['tag'], row['count']))
            return original(walk, row, kinds)
        e5tiff.Walk.values = counting
        try:
            return e5locate.locate(data), calls
        finally:
            e5tiff.Walk.values = original

    def test_one_over_the_bound_is_refused_and_no_array_is_unpacked(self):
        found, calls = self.locate_counting(extent_tiff(65537))
        self.assertEqual([r['code'] for r in found['write']['refusals']], ['TIFF_IFD_BUDGET'])
        self.assertIn('more than 65536', found['write']['refusals'][0]['message'])
        self.assertEqual([c for c in calls if c[0] in (0x0111, 0x0117)], [])

    def test_a_larger_bounded_count_is_refused_the_same_way_without_unpacking(self):
        found, calls = self.locate_counting(extent_tiff(1000000))
        self.assertEqual([r['code'] for r in found['write']['refusals']], ['TIFF_IFD_BUDGET'])
        self.assertEqual([c for c in calls if c[0] in (0x0111, 0x0117)], [])

    def test_exactly_the_bound_and_an_ordinary_count_are_unpacked_and_accepted(self):
        for count in (65536, 1, 3):
            found, calls = self.locate_counting(extent_tiff(count))
            self.assertNotIn('TIFF_IFD_BUDGET', [r['code'] for r in found['write']['refusals']], count)
            self.assertEqual(sorted(c for c in calls if c[0] in (0x0111, 0x0117)), [(0x0111, count), (0x0117, count)], count)

    def test_unequal_or_mistyped_arrays_keep_their_own_refusal_before_any_bound(self):
        data = bytearray(extent_tiff(70000))
        data[8 + 2 + 12 * 3 + 4:8 + 2 + 12 * 3 + 8] = struct.pack('<I', 69999)       # StripByteCounts now declares one fewer value than StripOffsets
        found, calls = self.locate_counting(bytes(data))
        self.assertEqual([r['code'] for r in found['write']['refusals']][:1], ['TIFF_IMAGE_EXTENT_INVALID'])
        self.assertEqual([c for c in calls if c[0] in (0x0111, 0x0117)], [])


@unittest.skipUnless(EXIFTOOL and Path(EXIFTOOL).exists(), 'a real ExifTool 13.55 is needed (SCHEMAXIS_EXIFTOOL)')
class TiffExtentBoundNative(Case):
    """E5C-5 through the public edit: a TIFF that declares 65,537 extents is refused by name before any native process, a TIFF with three is written."""

    def test_an_over_bound_tiff_is_refused_by_name_and_a_small_literal_control_is_written(self):
        faults = self.refused_run({'version': V, 'operation': 'editMetadata', 'media': {'items': [{'id': 't', 'path': self.put('many.tif', extent_tiff(65537))}]}, 'edits': {'title': {'set': 'Probe'}}})
        self.assertEqual((faults[0]['code'], faults[0]['location']), ('TIFF_IFD_BUDGET', 'captured/t.tif'))
        out, result = self.go({'version': V, 'operation': 'inspectMetadata', 'profiles': ['capture'], 'nativeListing': True, 'media': {'items': [{'id': 't', 'path': self.put('few.tif', extent_tiff(3))}]}})
        self.assertEqual((result['succeeded'], result['faulted']), (1, 0))


IMAGE = b'OPAQUE-HVC1-IMAGE-24BYTES'[:24]
KEEPER = b'Keeper description'


def heic_xmp_only():
    return f5.heic([{'id': 1, 'type': b'hvc1', 'payload': IMAGE}, {'id': 3, 'type': b'mime', 'content_type': b'application/rdf+xml', 'payload': f5.XMP_TEXT}], refs=[(b'cdsc', 3, [1])])


def heic_exif_only():
    return f5.heic([{'id': 1, 'type': b'hvc1', 'payload': IMAGE}, {'id': 2, 'type': b'Exif', 'payload': f5.exif_item()}], refs=[(b'cdsc', 2, [1])])


def exif_two_entries(o='<'):
    """An Exif stream holding ImageDescription ``Keeper description`` and Artist ``A. Mason`` in IFD0."""
    def table(off):
        return f5.ifd(o, [f5.text_row(o, 0x010E, KEEPER.decode(), 'description', off), f5.text_row(o, 0x013B, 'A. Mason', 'artist', off)])
    return f5.assemble(o, [('ifd0', table), ('description', lambda off: f5.text_block(KEEPER.decode())), ('artist', lambda off: f5.text_block('A. Mason'))])


def heic_with_survivors():
    """XMP item holding dc:title and dc:description; Exif item holding ImageDescription and Artist."""
    xmp = f5.XMP_TEXT.replace(b'</dc:title>', b'</dc:title><dc:description><rdf:Alt><rdf:li xml:lang="x-default">' + KEEPER + b'</rdf:li></rdf:Alt></dc:description>')
    exif = struct.pack('>I', 6) + b'Exif\0\0' + exif_two_entries()
    return f5.heic([{'id': 1, 'type': b'hvc1', 'payload': IMAGE}, {'id': 2, 'type': b'Exif', 'payload': exif}, {'id': 3, 'type': b'mime', 'content_type': b'application/rdf+xml', 'payload': xmp}],
                   refs=[(b'cdsc', 2, [1]), (b'cdsc', 3, [1])])


class HeifEmptyItemHost(unittest.TestCase):
    """E5C-4, host only: the shared guard judges what the plan leaves in an existing Exif or XMP item, for an edit and for a transfer's extras."""

    def payloads(self, data):
        return records.Payloads(e5locate.locate(data))

    def plan(self, data, edit):
        entries = {k: edits.normalise_edit(k, v, '$.edits.' + k) for k, v in edit.items()}
        return edits.plan_item(entries, self.payloads(data), edits.normalise_policies(None))

    def refused(self, data, edit):
        plan = self.plan(data, edit)
        plan['kind'] = 'edit'
        try:
            e5edit.empty_item_guard('heif', self.payloads(data), plan)
        except edits.Refusal as error:
            return error
        return None

    def test_clearing_the_only_xmp_property_or_the_only_exif_entry_is_refused_by_name(self):
        error = self.refused(heic_xmp_only(), {'title': {'clear': True}})
        self.assertEqual((error.code, error.location, error.observed['items'], error.observed['limitation']), ('HEIF_EMPTY_METADATA_ITEM', '$.edits', ['xmp'], 'heifEmptyMetadataItemNotWritable'))
        error = self.refused(heic_exif_only(), {'creator': {'clear': True}})
        self.assertEqual((error.code, error.observed['items']), ('HEIF_EMPTY_METADATA_ITEM', ['exif']))
        self.assertIn('zero-length extent', error.message)

    def test_a_clear_that_leaves_another_property_or_entry_is_not_refused(self):
        self.assertIsNone(self.refused(heic_with_survivors(), {'title': {'clear': True}}))
        self.assertIsNone(self.refused(heic_with_survivors(), {'creator': {'clear': True}}))

    def test_a_write_into_the_item_or_a_clear_that_changes_nothing_is_not_refused(self):
        self.assertIsNone(self.refused(heic_xmp_only(), {'title': {'set': 'Other title'}}))            # the item keeps a value
        self.assertIsNone(self.refused(heic_exif_only(), {'title': {'clear': True}}))               # no Exif entry is touched, so the Exif item is not judged

    def test_the_other_containers_and_unchanged_plans_are_never_judged(self):
        plan = self.plan(heic_xmp_only(), {'title': {'clear': True}})
        plan['kind'] = 'edit'
        e5edit.empty_item_guard('png', self.payloads(heic_xmp_only()), plan)
        e5edit.empty_item_guard('heif', self.payloads(heic_xmp_only()), {'kind': 'unchanged'})

    def test_a_transfer_whose_extras_delete_the_last_property_is_refused_the_same_way(self):
        data = heic_xmp_only()
        plan = {'kind': 'transfer', 'edit': None, 'time': None, 'location': None, 'extras': [{'destinations': [{'family': 'xmp', 'state': 'delete', 'property': 'dc:title', 'write': 'XMP-dc:Title'}]}]}
        with self.assertRaises(edits.Refusal) as caught:
            e5edit.empty_item_guard('heif', self.payloads(data), plan, '$.items[h]')
        self.assertEqual((caught.exception.code, caught.exception.location), ('HEIF_EMPTY_METADATA_ITEM', '$.items[h]'))
        plan['time'] = {'xmpTargets': ['photoshop:DateCreated']}            # the same plan writing a time into the item keeps it alive
        e5edit.empty_item_guard('heif', self.payloads(data), plan, '$.items[h]')


@unittest.skipUnless(EXIFTOOL and Path(EXIFTOOL).exists(), 'a real ExifTool 13.55 is needed (SCHEMAXIS_EXIFTOOL)')
class HeifEmptyItem(Case):
    """E5C-4, native: a clear that would empty an existing item is refused before native by name and publishes nothing; the ordinary clear that leaves metadata behind is written and verified."""

    def edit(self, name, data, edit):
        return {'version': V, 'operation': 'editMetadata', 'media': {'items': [{'id': 'h', 'path': self.put(name, data)}]}, 'edits': edit}

    def test_title_clear_of_the_only_xmp_property_is_refused_before_native(self):
        faults = self.refused_run(self.edit('xmp-only.heic', heic_xmp_only(), {'title': {'clear': True}}))
        self.assertEqual([(f['code'], f['location'], f['observed']['items']) for f in faults], [('HEIF_EMPTY_METADATA_ITEM', '$.edits', ['xmp'])])

    def test_creator_clear_of_the_only_exif_entry_is_refused_before_native(self):
        faults = self.refused_run(self.edit('exif-only.heic', heic_exif_only(), {'creator': {'clear': True}}))
        self.assertEqual([(f['code'], f['location'], f['observed']['items']) for f in faults], [('HEIF_EMPTY_METADATA_ITEM', '$.edits', ['exif'])])

    def test_clearing_both_last_fields_of_both_items_names_both(self):
        faults = self.refused_run(self.edit('both.heic', f5.heic_basic(with_metadata=True), {'title': {'clear': True}, 'creator': {'clear': True}}))
        self.assertEqual([(f['code'], f['observed']['items']) for f in faults], [('HEIF_EMPTY_METADATA_ITEM', ['xmp', 'exif'])])

    def test_the_ordinary_clear_with_surviving_metadata_is_written_and_verified(self):
        out, result = self.go(self.edit('survivors.heic', heic_with_survivors(), {'title': {'clear': True}, 'creator': {'clear': True}}))
        self.assertTrue(result['verified'])
        self.assertEqual((result['written'], result['refused'], result['failed']), (1, 0, 0))
        data = self.published(out, 'h')
        self.assertNotIn(b'Quarry gate', data)                 # the XMP title is gone
        self.assertNotIn(b'A. Mason', data)                    # the Exif Artist is gone
        self.assertIn(KEEPER, data)                            # the other XMP property and the other Exif entry stay
        self.assertEqual(data.count(IMAGE), 1)
        self.assertEqual(adaptor.verify(out, executable=EXIFTOOL)['nativeReplay'], 'fresh-replay-matched')

    def test_a_set_into_the_only_property_item_is_still_written(self):
        out, result = self.go(self.edit('set.heic', heic_xmp_only(), {'title': {'set': 'Other title'}}))
        self.assertTrue(result['verified'])
        self.assertIn(b'Other title', self.published(out, 'h'))


J = [{'id': 'a', 'path': '/x/a.jpg'}]
BASE = {'maxItems': 512, 'maxItemBytes': 67108864, 'maxTotalBytes': 1073741824}
READ = {**BASE, 'maxScannedEntries': 4096, 'maxFolderDepth': 2, 'maxNativeTagsPerFile': 4096, 'maxNativeListingBytes': 67108864}
WRITE = {**BASE, 'maxScans': 1024}
NAMES = {**BASE, 'maxSidecarBytes': 1048576}
LARGE = {'maxLargeItemBytes': 268435456, 'largeItemSuffixes': ['.dng', '.tif', '.tiff']}
# the plan documents of the JPEG-only cases and the plan hashes the retained F2 source (before this repair) computed for them: X-7, a JPEG-only plan never changes
CASES = (('inspect', {'operation': 'inspectMetadata', 'profiles': ['capture'], 'media': {'items': J}}, READ, '5683ef93a24bab379e905e7396d2b07629bcaa8af6d92d602b1e0ff0fcf58500'),
         ('reconcile', {'operation': 'reconcileTime', 'media': {'items': J}}, READ, '41c08d33600de96baeed4da2a644bff2bdda727560e5eb5447654cef205a797d'),
         ('edit', {'operation': 'editMetadata', 'media': {'items': J}, 'edits': {'title': {'set': 'T'}}}, WRITE, '9dbc67cafc9e0ce7f6970c1d0a22969d4620b94dcef2b7b712c8939797e54ced'),
         ('correct', {'operation': 'correctTime', 'media': {'items': J}, 'corrections': [{'group': 'g', 'shift': {'seconds': '1'}}]}, WRITE, 'e068d66a687a8e9eedfd3487a371c72076aa13cffe7e2176f2d33e24186d0044'),
         ('names', {'operation': 'planNames', 'media': {'items': J}, 'name': [{'token': 'itemId'}]}, NAMES, '512e4d637d5d50c1689f43997ce5c84de6ba5ee96ca512ede0de150c4641c445'),
         ('default folder', {'operation': 'planNames', 'media': {'folder': {'path': '/x'}}, 'name': [{'token': 'itemId'}]}, NAMES, '56c2a9d4c8a8ae4b3b31178bda234bd93a7e11f29c26ecddcdfde958b5696f04'))


def with_media(document, media):
    return {**document, 'media': media}


class PublishedBudget(unittest.TestCase):
    """E5C-6: the published budget states the bound that is enforced. ``maxItemBytes`` stays 64 MiB (the bound of every name that is not a large suffix) and a plan that can admit a TIFF or DNG name
    adds ``maxLargeItemBytes`` and ``largeItemSuffixes``; a JPEG-only plan is byte-identical to before (its hash is the retained literal)."""

    def plan(self, document):
        return adaptor.plan({'version': V, **document})

    def test_a_jpeg_only_plan_keeps_its_exact_budget_and_plan_hash(self):
        for label, document, budget, digest in CASES:
            plan = self.plan(document)
            self.assertEqual(plan['budget'], budget, label)
            self.assertEqual(adaptor.plan_hash(plan), digest, label)

    def test_every_other_non_large_container_name_adds_nothing(self):
        for suffix in ('.png', '.webp', '.heic', '.heif', '.avif', '.jpeg'):
            plan = self.plan({'operation': 'planNames', 'media': {'items': [{'id': 'a', 'path': '/x/a' + suffix}]}, 'name': [{'token': 'itemId'}]})
            self.assertEqual(plan['budget'], NAMES, suffix)

    def test_a_large_name_or_a_listed_large_folder_extension_adds_the_literal_large_bound(self):
        for label, document, budget, _ in CASES[:5]:
            for name in ('/x/b.tif', '/x/b.TIFF', '/x/b.dng'):
                plan = self.plan(with_media(document, {'items': [*J, {'id': 'b', 'path': name}]}))
                self.assertEqual(plan['budget'], {**budget, **LARGE}, (label, name))
        for extensions in (['.jpg', '.tif'], ['.dng'], ['.png', '.tiff', '.webp']):
            plan = self.plan({'operation': 'planNames', 'media': {'folder': {'path': '/x', 'extensions': extensions}}, 'name': [{'token': 'itemId'}]})
            self.assertEqual(plan['budget'], {**NAMES, **LARGE}, extensions)
        plan = self.plan({'operation': 'planNames', 'media': {'folder': {'path': '/x', 'extensions': ['.jpg', '.png', '.webp', '.heic']}}, 'name': [{'token': 'itemId'}]})
        self.assertEqual(plan['budget'], NAMES)

    def test_the_item_limit_by_name_is_exactly_what_the_budget_publishes(self):
        for suffix in LARGE['largeItemSuffixes']:
            self.assertEqual(mediaset.item_limit('/x/y' + suffix), LARGE['maxLargeItemBytes'])
            self.assertEqual(mediaset.item_limit('/x/Y' + suffix.upper()), LARGE['maxLargeItemBytes'])
        for suffix in ('.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif', '.avif', '.xmp'):
            self.assertEqual(mediaset.item_limit('/x/y' + suffix), BASE['maxItemBytes'], suffix)
        self.assertEqual((mediaset.ITEM_BYTES, mediaset.LARGE_ITEM_BYTES), (67108864, 268435456))


@unittest.skipUnless(EXIFTOOL and Path(EXIFTOOL).exists(), 'a real ExifTool 13.55 is needed (SCHEMAXIS_EXIFTOOL)')
class PublishedBudgetRun(Case):
    """E5C-6 through real runs: the plan a run publishes states the large bound for a mixed set and the unchanged budget for a JPEG-only set."""

    def test_the_published_plan_of_a_mixed_run_and_of_a_jpeg_only_run(self):
        jpeg, tiff = self.put('a.jpg', e3.full_time()), self.put('b.tif', extent_tiff(3))
        out, _ = self.go({'version': V, 'operation': 'inspectMetadata', 'profiles': ['capture'], 'media': {'items': [{'id': 'a', 'path': jpeg}, {'id': 'b', 'path': tiff}]}})
        self.assertEqual(json.loads((out / 'plan.json').read_text())['budget'], {**READ, **LARGE})
        out, _ = self.go({'version': V, 'operation': 'inspectMetadata', 'profiles': ['capture'], 'media': {'items': [{'id': 'a', 'path': jpeg}]}})
        self.assertEqual(json.loads((out / 'plan.json').read_text())['budget'], READ)
        out, result = self.go({'version': V, 'operation': 'correctTime', 'media': {'items': [{'id': 't', 'path': jpeg}]}, 'corrections': [{'group': 'dev1', 'shift': {'seconds': '60'}}]})
        self.assertEqual(json.loads((out / 'plan.json').read_text())['budget'], WRITE)


class PublicText(unittest.TestCase):
    """The public prose says what the code does after the completion repair: no stale method, tail, naming or bound claim remains in the capabilities, guidance, docs, profile and changelog."""
    EXIF_DIR = ROOT / 'src/schemaxis/adaptors/exiftool'

    def read(self, relative):
        return (ROOT / relative).read_text()

    def test_the_minimise_method_text_is_the_am19_method_everywhere(self):
        capabilities = (self.EXIF_DIR / 'capabilities.py').read_text()
        docs, changelog = self.read('docs/exiftool.md'), self.read('CHANGELOG.md')
        for text in (capabilities, docs):
            self.assertIn('AM-19', text)
            self.assertIn('-EXIF:all=', text)
        self.assertIn('PNG:<Keyword>', capabilities)
        self.assertIn('numeric assignments', docs)
        self.assertIn('-IFD0:Orientation#=6', docs)
        self.assertIn('`-EXIF:all=`', changelog)
        for stale in ('deletes every Exif, XMP and (PNG) text chunk by name', 'every Exif, XMP and PNG text chunk is deleted by name and only', 'every Exif, XMP and text chunk deleted by name'):
            for label, text in (('capabilities', capabilities), ('docs', docs), ('profile', (self.EXIF_DIR / 'containerprofiles.json').read_text())):
                self.assertNotIn(stale, text, label)

    def test_the_tail_the_heif_empty_item_the_avif_name_and_the_bounds_are_stated(self):
        docs = self.read('docs/exiftool.md')
        for text in ('an edit, a time correction, a copy of metadata and an applied', 'HEIF_EMPTY_METADATA_ITEM', 'heifEmptyMetadataItemNotWritable', '`avif` is `.avif`', 'maxLargeItemBytes', 'largeItemSuffixes'):
            self.assertIn(text, docs, text)
        capabilities = (self.EXIF_DIR / 'capabilities.py').read_text()
        self.assertIn('maxLargeItemBytes with largeItemSuffixes', capabilities)
        guidance = (self.EXIF_DIR / 'guidance.json').read_text()
        self.assertNotIn('Symbolic links, other formats, files over 64 MiB and missing files fault this item', guidance)
        self.assertIn('256 MiB for a name ending .tif, .tiff or .dng', guidance)
        changelog = self.read('CHANGELOG.md')
        for text in ('`HEIF_EMPTY_METADATA_ITEM`', '`.avif`', 'for edits, time\n  corrections and transfers alike', 'the published budget\n  states both bounds'):
            self.assertIn(text, changelog, text)


if __name__ == '__main__':
    unittest.main()
