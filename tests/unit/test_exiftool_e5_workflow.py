"""Public workflow chains of the E5 container operations over real produced files (genuine ExifTool 13.55 through SCHEMAXIS_EXIFTOOL).

W1  correctTime over a TIFF, a DNG, a PNG, a WebP and a HEIC -> planNames -> organiseCopies: canonical extensions and names that carry the corrected time (a literal hour later), organised bytes equal to the
    corrected files.
W2  exportSidecar of a JPEG master -> applySidecar into four containers (the declared sidecar IS the exported artifact): every destination carries the master's literal title and keywords.
W3  setLocation over three containers -> auditMetadata that requires a location: the audit passes only because the typed handoff delivered the written files.
W4  removeMetadata minimise over a PNG and a WebP -> organiseCopies: a share set whose bytes equal the minimised outputs.
Controls: a changed container source invalidates the producer and its consumers while unchanged bytes reuse every job; a new member of an opted-in mixed folder invalidates a folder consumer; a refused
item keeps its slot as an outcome document that a consumer refuses to read as a photo (partial); a set in which every item is refused is NO_USABLE_ITEMS and no consumer runs (noSuccess).
Every expected value is a hand-written literal.
"""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests/unit')]

import exiftool_e3_fixtures as e3  # noqa: E402
import exiftool_e4_fixtures as f4  # noqa: E402
import exiftool_e5_fixtures as f  # noqa: E402
import exiftool_e5_time_fixtures as t  # noqa: E402
from schemaxis import workflow  # noqa: E402
from schemaxis.adaptors.exiftool import adaptor  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402
from test_exiftool_e5_ops import payloads, snapshot  # noqa: E402

V = 'schemaxis.exiftool/1'
KINDS = ('tiff', 'dng', 'png', 'webp', 'heif')


def job_dir(result, operation):
    return Path(next(j for j in result['jobs'] if j['operation'] == operation)['directory'])


def reused(result):
    return {j['operation']: bool(j.get('reused')) for j in result['jobs']}


def bound(operation, index, item):
    return {'id': item, 'path': {'$artifact': operation, 'index': index}}


def produced(directory, ident):
    return next(p for p in sorted((directory / 'photos').glob(ident + '.*')) if not p.name.endswith('.metadata.json'))


class Chain(unittest.TestCase):
    RESULTS = {}

    @classmethod
    def setUpClass(cls):
        path = os.environ.get('SCHEMAXIS_EXIFTOOL')
        if not path or not os.path.isabs(path) or not Path(path).is_file() or not Path(adaptor.PERL).is_file():
            raise unittest.SkipTest('real ExifTool 13.55 is not configured through SCHEMAXIS_EXIFTOOL')
        cls.exe = path
        cls.locations = {'exiftool': path}
        os.environ['SCHEMAXIS_EXIFTOOL'] = path

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='e5-workflow-')).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.photos = self.root / 'photos'
        self.photos.mkdir()

    def execute(self, operations, name, **kw):
        graph = {'version': 'schemaxis.workflow/1', 'operations': [{'id': i, 'document': d} for i, d in operations]}
        return workflow.execute(graph, self.root / name, locations=self.locations, timeout=900, **kw)

    def put(self, kind, ident, **kw):
        path = self.photos / (ident + t.EXTENSIONS[kind])
        path.write_bytes(t.full_time(kind, **kw))
        return path

    def items(self, kinds, prefix='p', **kw):
        return {'items': [{'id': prefix + k, 'path': str(self.put(k, prefix + k, **kw))} for k in kinds]}

    # ---------------------------------------------------------------- W1
    def test_W1_corrected_time_names_and_organised_copies_over_every_container(self):
        media = self.items(KINDS)
        ids = ['p' + k for k in KINDS]
        fix = {'version': V, 'operation': 'correctTime', 'media': media, 'corrections': [{'group': 'dev1', 'shift': {'seconds': '3600'}}]}
        rule = {'name': [{'token': 'captureDate'}, {'literal': '_'}, {'token': 'captureTime'}, {'literal': '_'}, {'token': 'itemId'}], 'collisions': 'sequence'}
        plan = {'version': V, 'operation': 'planNames', 'media': {'items': [bound('fix', i, n) for i, n in enumerate(ids)]}, **rule}
        organise = {'version': V, 'operation': 'organiseCopies', 'media': {'items': [bound('fix', i, n) for i, n in enumerate(ids)]}, 'names': {'$artifact': 'plan', 'index': 0}, 'sidecars': 'omit'}
        result = self.execute([('fix', fix), ('plan', plan), ('organise', organise)], 'w1')
        self.assertTrue(workflow.verify(self.root / 'w1')['verified'])
        names = [(r['id'], r['relativePath']) for r in json.loads((job_dir(result, 'plan') / 'names-plan.json').read_text())['items']]
        self.assertEqual(names, [('ptiff', '20260301_130000_ptiff.tif'), ('pdng', '20260301_130000_pdng.dng'), ('ppng', '20260301_130000_ppng.png'), ('pwebp', '20260301_130000_pwebp.webp'),
                                 ('pheif', '20260301_130000_pheif.heic')])          # 12:00:00 + 3600 s, with each container's canonical extension
        for ident, (_, name) in zip(ids, names):
            self.assertEqual((job_dir(result, 'organise') / 'organised' / name).read_bytes(), produced(job_dir(result, 'fix'), ident).read_bytes(), name)
        Chain.RESULTS['W1'] = {'id': 'W1', 'operation': 'correctTime>planNames>organiseCopies', 'container': 'mixed', 'independentlyVerified': True}

    # ---------------------------------------------------------------- W2
    def test_W2_an_exported_sidecar_is_applied_to_four_containers(self):
        kinds = ('tiff', 'png', 'webp', 'heif')
        masters = []
        for index in range(len(kinds)):
            path = self.photos / ('m%d.jpg' % index)
            path.write_bytes(f4.master(seed=index + 1))
            masters.append({'id': 'm%d' % index, 'path': str(path)})
        export = {'version': V, 'operation': 'exportSidecar', 'media': {'items': masters}, 'transfer': {'groups': ['descriptive']}}
        targets = [{'id': 'd' + k, 'path': str(self.put(k, 'd' + k)), 'sidecar': {'$artifact': 'export', 'index': i}} for i, k in enumerate(kinds)]
        apply = {'version': V, 'operation': 'applySidecar', 'media': {'items': targets}, 'source': {'sidecar': 'declared'}, 'transfer': {'groups': ['descriptive']}, 'policies': {'existing': 'replace'}}
        result = self.execute([('export', export), ('apply', apply)], 'w2')
        self.assertTrue(workflow.verify(self.root / 'w2')['verified'])
        for k in kinds:
            data = produced(job_dir(result, 'apply'), 'd' + k).read_bytes()
            s = snapshot(data, groups=['descriptive'])
            self.assertEqual((s['title']['value']['text'], s['keywords']['value']), ('Harbour', ['k1', 'k2']), k)
        Chain.RESULTS['W2'] = {'id': 'W2', 'operation': 'exportSidecar>applySidecar', 'container': 'mixed', 'independentlyVerified': True}

    # ---------------------------------------------------------------- W3
    def test_W3_located_files_are_audited_through_the_typed_handoff(self):
        kinds = ('tiff', 'png', 'webp')
        ids = ['p' + k for k in kinds]
        locate = {'version': V, 'operation': 'setLocation', 'media': self.items(kinds), 'default': {'latitude': '35.658581', 'longitude': '139.745433'}}
        audit = {'version': V, 'operation': 'auditMetadata', 'rules': ['requiredFields'], 'require': ['gpsLatitude', 'gpsLongitude'], 'media': {'items': [bound('locate', i, n) for i, n in enumerate(ids)]}}
        result = self.execute([('locate', locate), ('audit', audit)], 'w3')
        self.assertTrue(workflow.verify(self.root / 'w3')['verified'])
        findings = json.loads((job_dir(result, 'audit') / 'audit.json').read_text())['findings']
        self.assertEqual(findings, [])                                                  # every written file records a location, so nothing is missing
        before = [(job_dir(result, 'audit') / 'captured' / (n + t.EXTENSIONS[k])).read_bytes() for n, k in zip(ids, kinds)]
        self.assertEqual(before, [produced(job_dir(result, 'locate'), n).read_bytes() for n in ids])
        Chain.RESULTS['W3'] = {'id': 'W3', 'operation': 'setLocation>auditMetadata', 'container': 'mixed', 'independentlyVerified': True}

    # ---------------------------------------------------------------- W4
    def test_W4_minimised_png_and_webp_are_organised_as_a_share_set(self):
        png = self.photos / 'ppng.png'
        png.write_bytes(t.png_g6())
        webp = self.photos / 'pwebp.webp'
        webp.write_bytes(f.riff(f.vp8x(0x0C), f.ck(b'VP8 ', f.vp8()), f.ck(b'EXIF', t.stream()), f.webp_xmp()))
        minimise = {'version': V, 'operation': 'removeMetadata', 'media': {'items': [{'id': 'ppng', 'path': str(png)}, {'id': 'pwebp', 'path': str(webp)}]}, 'categories': ['minimise']}
        organise = {'version': V, 'operation': 'organiseCopies', 'media': {'items': [bound('minimise', 0, 'ppng'), bound('minimise', 1, 'pwebp')]}, 'names': {'name': [{'token': 'itemId'}], 'folders': [{'literal': 'share'}]}, 'sidecars': 'omit'}
        result = self.execute([('minimise', minimise), ('organise', organise)], 'w4')
        self.assertTrue(workflow.verify(self.root / 'w4')['verified'])
        shared = job_dir(result, 'organise') / 'organised' / 'share'
        self.assertEqual((shared / 'pwebp.webp').read_bytes(), f.riff(f.ck(b'VP8 ', f.vp8())))                    # literal: only the bitstream chunk is left
        self.assertEqual(payloads((shared / 'ppng.png').read_bytes()).xmp[0], 'absent')
        self.assertEqual((shared / 'ppng.png').read_bytes(), produced(job_dir(result, 'minimise'), 'ppng').read_bytes())
        Chain.RESULTS['W4'] = {'id': 'W4', 'operation': 'removeMetadata>organiseCopies', 'container': 'mixed', 'independentlyVerified': True}

    # ---------------------------------------------------------------- reuse and invalidation
    def test_unchanged_container_bytes_reuse_every_job_and_changed_bytes_invalidate_what_depends_on_them(self):
        media = self.items(('png', 'webp'))
        fix = {'version': V, 'operation': 'correctTime', 'media': media, 'corrections': [{'group': 'dev1', 'shift': {'seconds': '60'}}]}
        organise = {'version': V, 'operation': 'organiseCopies', 'media': {'items': [bound('fix', 0, 'ppng'), bound('fix', 1, 'pwebp')]}, 'names': {'name': [{'token': 'itemId'}]}, 'sidecars': 'omit'}
        ops = [('fix', fix), ('organise', organise)]
        self.assertEqual(reused(self.execute(ops, 'reuse')), {'fix': False, 'organise': False})
        self.assertEqual(reused(self.execute(ops, 'reuse', resume=True)), {'fix': True, 'organise': True})
        (self.photos / 'ppng.png').write_bytes(t.full_time('png', make='Z'))                  # another camera make: the source bytes changed
        self.assertEqual(reused(self.execute(ops, 'reuse', resume=True)), {'fix': False, 'organise': False})

    def test_a_new_member_of_an_opted_in_mixed_folder_invalidates_the_folder_consumers(self):
        self.put('png', 'a')
        self.put('tiff', 'b')
        folder = {'folder': {'path': str(self.photos), 'extensions': ['.png', '.tif'], 'depth': 1}}
        plan = {'version': V, 'operation': 'planNames', 'media': folder, 'name': [{'token': 'captureDate'}, {'literal': '_'}, {'token': 'itemId'}], 'collisions': 'sequence'}
        organise = {'version': V, 'operation': 'organiseCopies', 'media': folder, 'names': {'$artifact': 'plan', 'index': 0}, 'sidecars': 'omit'}
        ops = [('plan', plan), ('organise', organise)]
        first = self.execute(ops, 'folder')
        self.assertEqual(reused(first), {'plan': False, 'organise': False})
        self.assertEqual(reused(self.execute(ops, 'folder', resume=True)), {'plan': True, 'organise': True})
        self.put('png', 'c')
        changed = self.execute(ops, 'folder', resume=True)
        self.assertEqual(reused(changed), {'plan': False, 'organise': False})
        names = sorted(r['relativePath'] for r in json.loads((job_dir(changed, 'plan') / 'names-plan.json').read_text())['items'])
        self.assertEqual(names, ['20260301_a.png', '20260301_b.tif', '20260301_c.png'])

    # ---------------------------------------------------------------- partial and noSuccess
    def test_a_refused_item_keeps_its_slot_as_an_outcome_and_a_consumer_refuses_it_as_a_photo(self):
        good = self.put('png', 'good')
        bare = self.photos / 'bare.heic'
        bare.write_bytes(t.full_time('heif', exif_block=False))               # no Exif item: the named HEIF capability gap refuses the location write for this item only
        locate = {'version': V, 'operation': 'setLocation', 'media': {'items': [{'id': 'good', 'path': str(good)}, {'id': 'bare', 'path': str(bare)}]}, 'default': {'latitude': '35.658581', 'longitude': '139.745433'}}
        consume = {'version': V, 'operation': 'inspectMetadata', 'profiles': ['capture'], 'media': {'items': [bound('locate', 1, 'bare')]}}
        with self.assertRaises(SchemaxisError) as caught:
            self.execute([('locate', locate), ('consume', consume)], 'partial')
        self.assertEqual(caught.exception.fault.code, 'INVALID_PHOTO_SOURCE')
        manifests = sorted((self.root / 'partial' / 'locate').rglob('manifest.json'))
        self.assertEqual(len(manifests), 1)
        manifest = json.loads(manifests[0].read_text())
        self.assertEqual([(e['id'], e['outcome']) for e in manifest['entries'] if e['role'] == 'item'], [('good', 'written'), ('bare', 'refused')])
        ok = {'version': V, 'operation': 'inspectMetadata', 'profiles': ['capture'], 'media': {'items': [bound('locate', 0, 'good')]}}
        result = self.execute([('locate', locate), ('consume', ok)], 'partial-ok')
        self.assertEqual(reused(result), {'locate': False, 'consume': False})

    def test_when_every_item_is_refused_nothing_is_written_and_no_consumer_runs(self):
        bare = self.photos / 'bare.heic'
        bare.write_bytes(t.full_time('heif', exif_block=False))
        locate = {'version': V, 'operation': 'setLocation', 'media': {'items': [{'id': 'bare', 'path': str(bare)}]}, 'default': {'latitude': '35.658581', 'longitude': '139.745433'}}
        consume = {'version': V, 'operation': 'inspectMetadata', 'profiles': ['capture'], 'media': {'items': [bound('locate', 0, 'bare')]}}
        with self.assertRaises(SchemaxisError) as caught:
            self.execute([('locate', locate), ('consume', consume)], 'nosuccess')
        self.assertEqual(caught.exception.fault.code, 'NO_USABLE_ITEMS')
        self.assertFalse(any(p for p in (self.root / 'nosuccess').rglob('photos') if any(p.iterdir())))
        self.assertEqual(len([d for d in (self.root / 'nosuccess').iterdir() if d.is_dir() and 'consume' in d.name]), 0)


if __name__ == '__main__':
    unittest.main()
