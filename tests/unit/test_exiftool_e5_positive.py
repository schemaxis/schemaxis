"""Explicit per-operation, per-container positive cases of E5 (genuine ExifTool 13.55 through SCHEMAXIS_EXIFTOOL).

Each test is one real native run of ONE declared operation over ONE container, decoded against literals written here (the fixtures are assembled from literal bytes by
``exiftool_e5_fixtures``; nothing is read back through the code under test for its expectation). They are the finite rows of the format-feature qualifier that carry ``supported: true``:
inspectMetadata, editMetadata and removeMetadata for TIFF, DNG, PNG, WebP and HEIF (removal is not offered for HEIF), plus one mixed-container auditMetadata and compareMetadata. Every
other behaviour (refusals, controls, mutants, lifecycle) lives in the other E5 test modules and is never counted as support. No pixel is decoded; no authenticity is claimed.
"""
import csv
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests/unit')]

import exiftool_e5_fixtures as f  # noqa: E402
from schemaxis.adaptors.exiftool import editing, workbench  # noqa: E402

EXIFTOOL = os.environ.get('SCHEMAXIS_EXIFTOOL')
TITLE, ARTIST = 'Quarry gate north', 'B. Mason'
EDIT = {'title': {'set': TITLE}, 'creator': {'set': [ARTIST]}}
V = 'schemaxis.exiftool/1'
WEBP_META = f.riff(f.vp8x(0x0C), f.ck(b'VP8 ', f.vp8()), f.webp_exif(), f.webp_xmp())
# container -> (file name, bytes, frame width, frame height, the title recorded by the fixture or None)
FILES = {'tiff': ('q.tif', f.plain_tiff('<'), 3, 2, None), 'dng': ('q.dng', f.dng(artist='A. Mason')[0], 3, 2, None), 'png': ('q.png', f.basic_png(), 2, 2, 'Quarry gate'),
         'webp': ('q.webp', WEBP_META, 3, 2, 'Quarry gate'), 'heif': ('q.heic', f.heic_basic(with_metadata=True), 64, 48, 'Quarry gate')}


@unittest.skipUnless(EXIFTOOL and Path(EXIFTOOL).exists(), 'a real ExifTool 13.55 is needed (SCHEMAXIS_EXIFTOOL)')
class Positive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='e5-positive-'))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.inputs = cls.tmp / 'inputs'
        cls.inputs.mkdir()
        for name, data, *_ in FILES.values():
            (cls.inputs / name).write_bytes(data)
        cls.count = 0

    def directory(self):
        type(self).count += 1
        return self.tmp / ('run%d' % self.count)

    def item(self, container):
        return {'id': 'q', 'path': str(self.inputs / FILES[container][0])}

    @staticmethod
    def table(path):
        with path.open() as stream:
            return list(csv.DictReader(stream))[0]

    # ------------------------------------------------------------------ inspectMetadata
    def inspect(self, container):
        name, _, width, height, title = FILES[container]
        directory = self.directory()
        result = workbench.run({'version': V, 'operation': 'inspectMetadata', 'profiles': ['rendering', 'description'], 'nativeListing': True, 'media': {'items': [self.item(container)]}}, directory, executable=EXIFTOOL)
        self.assertEqual((result['succeeded'], result['faulted'], result['verified'], result['nativeReplay']), (1, 0, True, 'fresh-replay-matched'))
        rendering = self.table(directory / 'profile-rendering.csv')
        self.assertEqual((rendering['imageWidth'], rendering['imageHeight'], rendering['imageWidthState']), (str(width), str(height), 'present'))
        row = self.table(directory / 'profile-description.csv')
        if title is None:
            self.assertEqual(row['titleState'], 'absent')
        else:
            self.assertEqual((row['title'], row['titleState']), (title, 'present'))
        captures = json.loads((directory / 'captures.json').read_text())['items']
        self.assertEqual(captures[0]['container'], container)
        self.assertEqual(Path(captures[0]['file']).suffix, Path(name).suffix)

    def test_inspect_tiff(self): self.inspect('tiff')
    def test_inspect_dng(self): self.inspect('dng')
    def test_inspect_png(self): self.inspect('png')
    def test_inspect_webp(self): self.inspect('webp')
    def test_inspect_heif(self): self.inspect('heif')

    # ------------------------------------------------------------------ editMetadata
    def edit(self, container, protected):
        directory = self.directory()
        result = editing.run({'version': V, 'operation': 'editMetadata', 'media': {'items': [self.item(container)]}, 'edits': EDIT}, directory, executable=EXIFTOOL, timeout=300)
        self.assertEqual((result['verified'], result['written'], result['refused'], result['failed'], result['nativeReplay']), (True, 1, 0, 0, 'fresh-replay-matched'))
        out = next((directory / 'photos').glob('q.*')).read_bytes()
        self.assertIn(TITLE.encode(), out)
        self.assertIn(ARTIST.encode() + b'\0', out)
        for part in protected:
            self.assertEqual(out.count(part), 1, part)
        report = json.loads((directory / 'edit-report.json').read_text())['items'][0]
        self.assertEqual((report['status'], report['source']['container']), ('written', container))
        self.assertEqual(sorted(report['proofs']), ['N', 'P', 'R', 'problems'])
        self.assertEqual(report['proofs']['problems'], 0)

    def test_edit_tiff(self): self.edit('tiff', [f.STRIP])
    def test_edit_dng(self): self.edit('dng', [f.STRIP, b'VendorPrivate-0123'])
    def test_edit_png(self): self.edit('png', [f.GAMA, f.IDAT + f.IEND])
    def test_edit_webp(self): self.edit('webp', [f.ck(b'VP8 ', f.vp8())])
    def test_edit_heif(self): self.edit('heif', [b'OPAQUE-HVC1-IMAGE-24BYTES'[:24]])

    # ------------------------------------------------------------------ removeMetadata
    def remove(self, container, protected, gone):
        directory = self.directory()
        result = editing.run({'version': V, 'operation': 'removeMetadata', 'media': {'items': [self.item(container)]}, 'categories': ['descriptive', 'rights']}, directory, executable=EXIFTOOL, timeout=300)
        self.assertEqual((result['verified'], result['written'], result['refused'], result['failed']), (True, 1, 0, 0))
        out = next((directory / 'photos').glob('q.*')).read_bytes()
        for part in protected:
            self.assertEqual(out.count(part), 1, part)
        for part in gone:
            self.assertNotIn(part, out, part)
        report = json.loads((directory / 'removal-report.json').read_text())['items'][0]
        self.assertEqual((report['status'], report['removed']['nothingToRemove']), ('written', False))

    def test_remove_tiff(self): self.remove('tiff', [f.STRIP], [b'Quarry gate\0', b'A. Mason\0'])
    def test_remove_dng(self): self.remove('dng', [f.STRIP, b'VendorPrivate-0123'], [b'A. Mason\0'])
    def test_remove_png(self): self.remove('png', [f.GAMA, f.IDAT + f.IEND], [b'Quarry gate'])
    def test_remove_webp(self): self.remove('webp', [f.ck(b'VP8 ', f.vp8())], [b'Quarry gate'])

    # ------------------------------------------------------------------ auditMetadata and compareMetadata over one mixed set
    def mixed(self):
        names = {'png_basic': f.basic_png(), 'png_nometa': f.basic_png(metadata=False), 'tiff_le': f.plain_tiff('<'), 'webp_meta': WEBP_META, 'heic_meta': f.heic_basic(with_metadata=True)}
        folder = self.tmp / 'mixed'
        folder.mkdir(exist_ok=True)
        items = []
        for ident, data in names.items():
            suffix = {'png': '.png', 'tiff': '.tif', 'webp': '.webp', 'heic': '.heic'}[ident.split('_')[0]]
            (folder / (ident + suffix)).write_bytes(data)
            items.append({'id': ident, 'path': str(folder / (ident + suffix))})
        return {'version': V, 'media': {'items': items}}

    def test_audit_mixed_containers(self):
        directory = self.directory()
        result = workbench.run({**self.mixed(), 'operation': 'auditMetadata', 'rules': ['requiredFields'], 'require': ['title', 'imageWidth']}, directory, executable=EXIFTOOL)
        self.assertEqual((result['succeeded'], result['faulted'], result['verified']), (5, 0, True))
        findings = json.loads((directory / 'audit.json').read_text())['findings']
        self.assertEqual(sorted((x['item'], x['field'], x['status']) for x in findings), [('png_nometa', 'title', 'absent'), ('tiff_le', 'title', 'absent')])

    def test_compare_mixed_containers(self):
        directory = self.directory()
        result = workbench.run({**self.mixed(), 'operation': 'compareMetadata', 'baseline': 'png_basic', 'fields': ['imageWidth', 'title']}, directory, executable=EXIFTOOL)
        self.assertEqual((result['succeeded'], result['faulted'], result['verified']), (5, 0, True))
        rows = {(r['item'], r['field']): (r['outcome'], r['other']['value']) for r in json.loads((directory / 'comparison.json').read_text())['rows']}
        self.assertEqual(rows[('png_nometa', 'imageWidth')], ('same', 2))
        self.assertEqual(rows[('tiff_le', 'imageWidth')], ('different', 3))
        self.assertEqual(rows[('webp_meta', 'title')], ('same', 'Quarry gate'))
        self.assertEqual(rows[('heic_meta', 'imageWidth')], ('different', 64))
        self.assertEqual(rows[('tiff_le', 'title')], ('missing-in-item', None))


    # ------------------------------------------------------------------ E4 host operations over the containers (planNames, organiseCopies, exportSidecar)
    def host_items(self):
        data = {'a_tiff.tif': f.plain_tiff('<'), 'b_dng.dng': f.dng(artist='A. Mason')[0], 'c_png.png': f.basic_png(), 'd_webp.webp': WEBP_META, 'e_heic.heic': f.heic_basic(with_metadata=True)}
        folder = self.tmp / 'host'
        folder.mkdir(exist_ok=True)
        for name, content in data.items():
            (folder / name).write_bytes(content)
        return data, [{'id': name.split('.')[0], 'path': str(folder / name)} for name in data]

    def test_plan_names_every_container_keeps_its_canonical_extension(self):
        _, items = self.host_items()
        directory = self.directory()
        result = adaptor_run({'version': V, 'operation': 'planNames', 'media': {'items': items}, 'name': [{'token': 'itemId'}]}, directory)
        self.assertEqual((result['verified'], result['items'], result['refused']), (True, 5, 0))
        with (directory / 'names.csv').open() as stream:
            rows = [(r['id'], r['status'], r['relativePath']) for r in csv.DictReader(stream)]
        self.assertEqual(rows, [('a_tiff', 'planned', 'a_tiff.tif'), ('b_dng', 'planned', 'b_dng.dng'), ('c_png', 'planned', 'c_png.png'), ('d_webp', 'planned', 'd_webp.webp'), ('e_heic', 'planned', 'e_heic.heic')])

    def test_organise_copies_every_container_is_an_exact_byte_copy(self):
        data, items = self.host_items()
        directory = self.directory()
        result = adaptor_run({'version': V, 'operation': 'organiseCopies', 'media': {'items': items}, 'names': {'name': [{'token': 'itemId'}], 'extension': 'canonical'}}, directory)
        self.assertEqual((result['verified'], result['written'], result['refused'], result['failed']), (True, 5, 0, 0))
        for name, content in data.items():
            self.assertEqual((directory / 'organised' / name).read_bytes(), content, name)

    def test_export_sidecar_writes_the_container_payload_values_and_refuses_what_has_none(self):
        _, items = self.host_items()
        directory = self.directory()
        result = adaptor_run({'version': V, 'operation': 'exportSidecar', 'media': {'items': items}, 'transfer': {'groups': ['descriptive']}}, directory)
        self.assertEqual((result['verified'], result['written'], result['refused'], result['setStatus']), (True, 4, 1, 'partial'))
        for name in ('a_tiff', 'c_png', 'd_webp', 'e_heic'):
            self.assertIn(b'>Quarry gate<', (directory / 'sidecars' / (name + '.xmp')).read_bytes(), name)
        refused = [r for r in json.loads((directory / 'sidecar-report.json').read_text())['items'] if r['status'] == 'refused']
        self.assertEqual([(r['id'], r['fault']['code']) for r in refused], [('b_dng', 'SIDECAR_NOTHING_TO_WRITE')])


def adaptor_run(document, directory):
    from schemaxis.adaptors.exiftool import adaptor
    return adaptor.run(document, directory, executable=EXIFTOOL)


if __name__ == '__main__':
    unittest.main()
