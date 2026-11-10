"""One genuine native run per (operation, container) cell of the E5 matrix, against ExifTool 13.55 (SCHEMAXIS_EXIFTOOL).

Read-only operations (auditMetadata, compareMetadata, reconcileTime, locate), host operations (planNames, organiseCopies, exportSidecar) and every removal category are each run ONCE per
container over a hand-built rich photograph (EXIF make/model/serial/time/GPS, XMP title, keywords, creator, rights and capture time; an IPTC time pair in TIFF and DNG), so a cell of the
availability matrix is never inferred from a mixed-container case. Every expected value is a literal written here. Named refusals (minimise of TIFF, DNG and HEIF) are proven with their exact code
and nothing written. No pixel is decoded; nothing here claims anonymisation or privacy.
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
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tools'), str(ROOT / 'tests/unit')]

import exiftool_e3_fixtures as e3  # noqa: E402
import exiftool_e4_fixtures as f4  # noqa: E402
import exiftool_e5_time_fixtures as t  # noqa: E402
import author_exiftool_fixtures as a  # noqa: E402
from schemaxis.adaptors.exiftool import adaptor  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402
from test_exiftool_e5_ops import entry, payloads, PROTECTED, xmp_value  # noqa: E402

EXIFTOOL = os.environ.get('SCHEMAXIS_EXIFTOOL')
V = 'schemaxis.exiftool/1'
KINDS = ('tiff', 'dng', 'png', 'webp', 'heif')
CATEGORIES = ('location', 'captureTime', 'descriptive', 'rights', 'deviceIdentity')
EXT = t.EXTENSIONS
MAKER = b'MAKERNOTE-OPAQUE-0123'
RICH_XMP = e3.xmp_properties(captured='2026-03-01T12:00:00.12+01:00', extra=f4.lang_alt('dc:title', 'Harbour') + f4.bag('dc:subject', 'k1', 'k2') + f4.bag('dc:creator', 'Ann', kind='Seq') + f4.lang_alt('dc:rights', '(c) 2024 A'))


def rich(kind, **kw):
    base = dict(gps=t.TOKYO, serial='SN-0001', make='Quarry Optics', model='QO-7', xmp=RICH_XMP, exif_extra=[a.undefined_entry(0x927C, MAKER)])
    base.update(kw)
    if kind in ('tiff', 'dng'):
        base.setdefault('iptc', [(2, 55, '20260301'), (2, 60, '120000+0100')])
    return t.container(kind, **base)


@unittest.skipUnless(EXIFTOOL and Path(EXIFTOOL).exists(), 'a real ExifTool 13.55 is needed (SCHEMAXIS_EXIFTOOL)')
class Matrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='e5-matrix-')).resolve()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.runs = 0

    def photo(self, kind, ident='x', **kw):
        path = self.tmp / ('%s-%d%s' % (ident, self.runs, EXT[kind]))
        path.write_bytes(rich(kind, **kw))
        return {'id': ident, 'path': str(path)}

    def run_op(self, document):
        type(self).runs += 1
        out = self.tmp / ('run%d' % self.runs)
        result = adaptor.run({'version': V, **document}, out, executable=EXIFTOOL, timeout=300)
        self.assertTrue(result['verified'])
        self.assertEqual(adaptor.verify(out, executable=EXIFTOOL)['nativeReplay'], 'fresh-replay-matched')
        return out, result

    @staticmethod
    def output(out, ident='x'):
        return next(p for p in sorted((out / 'photos').glob(ident + '.*')) if not p.name.endswith('.metadata.json')).read_bytes()

    # ---------------------------------------------------------------- read-only operations
    def audit(self, kind):
        item = self.photo(kind)
        out, result = self.run_op({'operation': 'auditMetadata', 'media': {'items': [item]}, 'rules': ['requiredFields'], 'require': ['title', 'rightsUrl']})
        self.assertEqual((result['succeeded'], result['faulted']), (1, 0))
        findings = json.loads((out / 'audit.json').read_text())['findings']
        self.assertEqual([(x['item'], x['field'], x['status']) for x in findings], [('x', 'rightsUrl', 'absent')])      # the title is present, the rights URL is not

    def compare(self, kind):
        first, second = self.photo(kind, 'a'), self.photo(kind, 'b', model='QO-8')
        out, result = self.run_op({'operation': 'compareMetadata', 'media': {'items': [first, second]}, 'baseline': 'a', 'fields': ['cameraModel', 'title']})
        self.assertEqual((result['succeeded'], result['faulted']), (2, 0))
        rows = {(r['item'], r['field']): (r['outcome'], r['other']['value']) for r in json.loads((out / 'comparison.json').read_text())['rows']}
        self.assertEqual(rows[('b', 'cameraModel')], ('different', 'QO-8'))
        self.assertEqual(rows[('b', 'title')][0], 'same')

    def reconcile(self, kind):
        out, _ = self.run_op({'operation': 'reconcileTime', 'media': {'items': [self.photo(kind)]}})
        row = json.loads((out / 'time-report.json').read_text())['report']['items'][0]
        self.assertEqual((row['recordedLocal'], row['recordedOffset'], row['group']), ('2026-03-01T12:00:00.12', '+01:00', 'dev1'))

    def locate(self, kind):
        out, _ = self.run_op({'operation': 'locate', 'media': {'items': [self.photo(kind)]}})
        row = json.loads((out / 'location-report.json').read_text())['items'][0]
        self.assertEqual((row['position']['latitude'], row['position']['longitude'], row['position']['exact']), ('35.5', '139.25', True))
        self.assertEqual((row['height']['meters'], row['height']['reference']), ('52.3', 'ellipsoidal'))

    # ---------------------------------------------------------------- host operations
    def plan_names(self, kind):
        out, result = self.run_op({'operation': 'planNames', 'media': {'items': [self.photo(kind)]}, 'name': [{'token': 'captureDate'}, {'literal': '_'}, {'token': 'itemId'}]})
        self.assertEqual((result['items'], result['refused']), (1, 0))
        with (out / 'names.csv').open() as stream:
            rows = [(r['id'], r['status'], r['relativePath']) for r in csv.DictReader(stream)]
        self.assertEqual(rows, [('x', 'planned', '20260301_x' + EXT[kind])])

    def organise(self, kind):
        item = self.photo(kind)
        out, result = self.run_op({'operation': 'organiseCopies', 'media': {'items': [item]}, 'names': {'name': [{'token': 'itemId'}], 'extension': 'canonical'}})
        self.assertEqual((result['written'], result['refused'], result['failed']), (1, 0, 0))
        self.assertEqual((out / 'organised' / ('x' + EXT[kind])).read_bytes(), Path(item['path']).read_bytes())

    def export_sidecar(self, kind):
        out, result = self.run_op({'operation': 'exportSidecar', 'media': {'items': [self.photo(kind)]}, 'transfer': {'groups': ['descriptive']}})
        self.assertEqual((result['written'], result['refused']), (1, 0))
        text = (out / 'sidecars' / 'x.xmp').read_bytes()
        for literal in (b'>Harbour<', b'>k1<', b'>k2<'):
            self.assertIn(literal, text)

    # ---------------------------------------------------------------- removal categories
    def remove(self, kind, category):
        item = self.photo(kind)
        before = Path(item['path']).read_bytes()
        out, result = self.run_op({'operation': 'removeMetadata', 'media': {'items': [item]}, 'categories': [category]})
        self.assertEqual((result['written'], result['refused'], result['failed']), (1, 0, 0))
        data = self.output(out)
        row = json.loads((out / 'removal-report.json').read_text())['items'][0]
        self.assertEqual((row['status'], row['removed']['nothingToRemove'], row['proofs']['problems']), ('written', False, 0))
        for part in PROTECTED[kind]:
            self.assertEqual(data.count(part), before.count(part), (kind, part[:10]))           # the image bytes are exactly as before
        ifds = payloads(data).exif[1]['ifds'] if payloads(data).exif[0] == 'ok' else {}
        if category == 'location':
            self.assertNotIn('GPS', ifds)
        elif category == 'captureTime':
            self.assertIsNone(entry(data, 'ExifIFD', 0x9003))
            self.assertIsNone(xmp_value(data, 'photoshop:DateCreated'))
        elif category == 'descriptive':
            self.assertIsNone(xmp_value(data, 'dc:title'))
            self.assertNotIn(b'>Harbour<', data)
        elif category == 'rights':
            self.assertNotIn(b'(c) 2024 A', data)
        else:
            for gone in (b'SN-0001', b'Quarry Optics', b'QO-7'):
                self.assertNotIn(gone, data, gone)
            self.assertEqual(data.count(MAKER), 1)                                              # the opaque maker note stays: the declared residual
            self.assertIn('makerNoteMayIdentifyDevice', json.dumps(json.loads((out / 'residual.json').read_text())))

    # ---------------------------------------------------------------- named refusals
    def refuse_minimise(self, kind):
        item = self.photo(kind)
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.run({'version': V, 'operation': 'removeMetadata', 'media': {'items': [item]}, 'categories': ['minimise']}, self.tmp / ('refuse-' + kind), executable=EXIFTOOL, timeout=300)
        self.assertEqual(caught.exception.fault.code, 'NO_USABLE_ITEMS')
        first = caught.exception.fault.observed['firstFaults'][0]
        code = 'HEIF_REMOVAL_UNSUPPORTED' if kind == 'heif' else 'MINIMISE_UNSUPPORTED_CONTAINER'       # HEIF refuses every removal, minimise included, by its own named code
        self.assertEqual((first['code'], first['observed']['container']), (code, kind))
        self.assertFalse((self.tmp / ('refuse-' + kind) / 'photos').exists())


def _case(method, *args):
    def test(self):
        getattr(self, method)(*args)
    return test


for _kind in KINDS:
    for _op, _method in (('audit', 'audit'), ('compare', 'compare'), ('reconcile_time', 'reconcile'), ('locate', 'locate'), ('plan_names', 'plan_names'), ('organise_copies', 'organise'),
                         ('export_sidecar', 'export_sidecar')):
        setattr(Matrix, 'test_%s_%s' % (_op, _kind), _case(_method, _kind))
for _kind in ('tiff', 'dng', 'png', 'webp'):
    for _category in CATEGORIES:
        setattr(Matrix, 'test_remove_%s_%s' % (_category, _kind), _case('remove', _kind, _category))
for _kind in ('tiff', 'dng', 'heif'):
    setattr(Matrix, 'test_minimise_is_refused_%s' % _kind, _case('refuse_minimise', _kind))


if __name__ == '__main__':
    unittest.main()
