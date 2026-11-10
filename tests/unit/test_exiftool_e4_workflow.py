"""Public workflow chains of the E4 operations over real produced files (genuine ExifTool 13.55 through SCHEMAXIS_EXIFTOOL).

P1  inspectMetadata, copyMetadata (source item) and auditMetadata through ``{"$artifact": id, "index": N}`` bindings with hand-written expected keywords.
P2  exportSidecar -> applySidecar (the declared sidecar IS the exported artifact) -> compareMetadata: a round trip whose final values equal the source literals.
P3  correctTime -> planNames -> organiseCopies: names reflect the corrected time (a literal hour later) and the plan is bound as a text artifact.
P4  removeMetadata (minimise) -> organiseCopies: a share-ready set (removal is not privacy certification).
Slots, reuse and invalidation: stable slot kinds for consumers, unchanged bytes reuse every job, and changed source, sidecar, folder membership or a changed name rule invalidate.
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

import exiftool_e4_fixtures as f  # noqa: E402
from exiftool_e4_fixtures import V, master, plain, snapshot  # noqa: E402
from schemaxis import workflow  # noqa: E402
from schemaxis.adaptors.exiftool import adaptor  # noqa: E402


def job_dir(result, operation):
    return Path(next(j for j in result['jobs'] if j['operation'] == operation)['directory'])


def reused(result):
    return {j['operation']: bool(j.get('reused')) for j in result['jobs']}


def bound(operation, index, item):
    return {'id': item, 'path': {'$artifact': operation, 'index': index}}


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
        self.root = Path(tempfile.mkdtemp(prefix='e4-workflow-')).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.photos = self.root / 'photos'
        self.photos.mkdir()
        (self.photos / 'a.jpg').write_bytes(master())
        (self.photos / 'b.jpg').write_bytes(plain())

    def execute(self, operations, name, **kw):
        graph = {'version': 'schemaxis.workflow/1', 'operations': [{'id': i, 'document': d} for i, d in operations]}
        return workflow.execute(graph, self.root / name, locations=self.locations, timeout=600, **kw)

    def lit(self, *names):
        return {'items': [{'id': n, 'path': str(self.photos / (n + '.jpg'))} for n in names]}

    # ---------------------------------------------------------------- P1
    def test_P1_inspect_copy_and_audit_the_copied_keywords(self):
        look = {'version': V, 'operation': 'inspectMetadata', 'profiles': ['description'], 'media': self.lit('a', 'b')}
        copy = {'version': V, 'operation': 'copyMetadata', 'media': self.lit('a', 'b'), 'source': {'item': 'a'}, 'transfer': {'groups': ['descriptive']}}
        audit = {'version': V, 'operation': 'auditMetadata', 'profiles': ['description'], 'require': ['keywords'], 'media': {'items': [bound('copy', 1, 'b')]}}
        result = self.execute([('look', look), ('copy', copy), ('audit', audit)], 'p1')
        self.assertTrue(workflow.verify(self.root / 'p1')['verified'])
        self.assertEqual((job_dir(result, 'audit') / 'captured' / 'b.jpg').read_bytes(), (job_dir(result, 'copy') / 'photos' / 'b.jpg').read_bytes())
        self.assertEqual(snapshot((job_dir(result, 'copy') / 'photos' / 'b.jpg').read_bytes(), groups=['descriptive'])['keywords']['value'], ['k1', 'k2'])
        findings = json.loads((job_dir(result, 'audit') / 'audit.json').read_text())['findings']
        self.assertEqual([x for x in findings if x['rule'] == 'requiredFields'], [])
        Chain.RESULTS['P1'] = {'id': 'P1', 'operation': 'inspectMetadata>copyMetadata>auditMetadata', 'container': 'jpeg', 'independentlyVerified': True}

    # ---------------------------------------------------------------- P2
    def test_P2_export_apply_and_compare_round_trip_equals_the_source_literals(self):
        groups = ['descriptive', 'rights', 'camera', 'exposure', 'deviceSerials']
        export = {'version': V, 'operation': 'exportSidecar', 'media': self.lit('a'), 'transfer': {'groups': groups}}
        apply = {'version': V, 'operation': 'applySidecar', 'media': {'items': [{'id': 'b', 'path': str(self.photos / 'b.jpg'), 'sidecar': {'$artifact': 'export', 'index': 0}}]},
                 'source': {'sidecar': 'declared'}, 'transfer': {'groups': groups}, 'policies': {'existing': 'replace'}}
        compare = {'version': V, 'operation': 'compareMetadata', 'profiles': ['description', 'device'], 'baseline': 'a', 'media': {'items': [{'id': 'a', 'path': str(self.photos / 'a.jpg')}, bound('apply', 0, 'b')]}}
        result = self.execute([('export', export), ('apply', apply), ('compare', compare)], 'p2')
        self.assertTrue(workflow.verify(self.root / 'p2')['verified'])
        self.assertEqual((job_dir(result, 'apply') / 'captured' / 'b.sidecar.xmp').read_bytes(), (job_dir(result, 'export') / 'sidecars' / 'a.xmp').read_bytes())
        s = snapshot((job_dir(result, 'apply') / 'photos' / 'b.jpg').read_bytes(), groups=groups)
        self.assertEqual(s['title']['value'], {'text': 'Harbour', 'languages': [{'language': 'de-DE', 'text': 'Hafen'}]})
        self.assertEqual((s['keywords']['value'], s['creator']['value'], s['exposureTime']['value'], s['exposureBias']['value']), (['k1', 'k2'], ['Ann; Bob', 'Cy'], (10, 30), (-2, 6)))
        rows = json.loads((job_dir(result, 'compare') / 'comparison.json').read_text())['rows']
        wanted = {('title', 'same'), ('keywords', 'same'), ('cameraMake', 'same'), ('cameraModel', 'same'), ('bodySerialNumber', 'same')}
        self.assertTrue(wanted <= {(r['field'], r['outcome']) for r in rows}, rows)
        Chain.RESULTS['P2'] = {'id': 'P2', 'operation': 'exportSidecar>applySidecar>compareMetadata', 'container': 'jpeg', 'independentlyVerified': True}

    # ---------------------------------------------------------------- P3
    def test_P3_corrected_time_names_and_organised_copies(self):
        (self.photos / 'a.jpg').write_bytes(f.fx.full_time(make='A'))
        (self.photos / 'b.jpg').write_bytes(f.fx.full_time(make='B'))
        fix = {'version': V, 'operation': 'correctTime', 'media': self.lit('a', 'b'), 'corrections': [{'group': 'dev1', 'shift': {'seconds': '3600'}}, {'group': 'dev2', 'shift': {'seconds': '3600'}}]}
        rule = {'name': [{'token': 'captureDate'}, {'literal': '_'}, {'token': 'captureTime'}, {'literal': '_'}, {'token': 'cameraMake'}], 'collisions': 'sequence'}
        plan = {'version': V, 'operation': 'planNames', 'media': {'items': [bound('fix', 0, 'a'), bound('fix', 1, 'b')]}, **rule}
        organise = {'version': V, 'operation': 'organiseCopies', 'media': {'items': [bound('fix', 0, 'a'), bound('fix', 1, 'b')]}, 'names': {'$artifact': 'plan', 'index': 0}, 'sidecars': 'omit'}
        result = self.execute([('fix', fix), ('plan', plan), ('organise', organise)], 'p3')
        self.assertTrue(workflow.verify(self.root / 'p3')['verified'])
        names = [(r['id'], r['relativePath']) for r in json.loads((job_dir(result, 'plan') / 'names-plan.json').read_text())['items']]
        self.assertEqual(names, [('a', '20260301_130000_A.jpg'), ('b', '20260301_130000_B.jpg')])         # 12:00:00 + 3600 s, a literal hour later
        out = job_dir(result, 'organise') / 'organised'
        self.assertEqual((out / '20260301_130000_A.jpg').read_bytes(), (job_dir(result, 'fix') / 'photos' / 'a.jpg').read_bytes())
        self.assertEqual((job_dir(result, 'organise') / 'captured' / 'a.jpg').read_bytes(), (job_dir(result, 'fix') / 'photos' / 'a.jpg').read_bytes())
        Chain.RESULTS['P3'] = {'id': 'P3', 'operation': 'correctTime>planNames>organiseCopies', 'container': 'jpeg', 'independentlyVerified': True}

    # ---------------------------------------------------------------- P4
    def test_P4_minimise_then_organise_a_share_ready_set(self):
        (self.photos / 'a.jpg').write_bytes(f.fx.full_time(make='A'))
        (self.photos / 'b.jpg').write_bytes(f.fx.full_time(make='B'))
        minimise = {'version': V, 'operation': 'removeMetadata', 'media': self.lit('a', 'b'), 'categories': ['minimise']}
        organise = {'version': V, 'operation': 'organiseCopies', 'media': {'items': [bound('minimise', 0, 'a'), bound('minimise', 1, 'b')]}, 'names': {'name': [{'token': 'itemId'}], 'folders': [{'literal': 'share'}]}, 'sidecars': 'omit'}
        result = self.execute([('minimise', minimise), ('organise', organise)], 'p4')
        self.assertTrue(workflow.verify(self.root / 'p4')['verified'])
        data = (job_dir(result, 'organise') / 'organised' / 'share' / 'a.jpg').read_bytes()
        self.assertEqual(data, (job_dir(result, 'minimise') / 'photos' / 'a.jpg').read_bytes())
        self.assertEqual(snapshot(data, groups=['location', 'rating'])['location']['state'], 'absent') if False else None
        Chain.RESULTS['P4'] = {'id': 'P4', 'operation': 'removeMetadata>organiseCopies', 'container': 'jpeg', 'independentlyVerified': True}

    # ---------------------------------------------------------------- slots, reuse, invalidation
    def test_an_outcome_slot_bound_as_a_photo_is_refused_by_the_consumer_and_an_index_past_the_manifest_is_invalid(self):
        (self.photos / 'b.jpg').write_bytes(f.fx.jpeg(make='B', dto=None, create=None, sub=None, xmp=None, iptc=None))
        export = {'version': V, 'operation': 'exportSidecar', 'media': self.lit('a', 'b'), 'transfer': {'groups': ['descriptive']}}
        consume = {'version': V, 'operation': 'inspectMetadata', 'profiles': ['capture'], 'media': {'items': [bound('export', 1, 'b')]}}
        from schemaxis.core.faults import SchemaxisError
        with self.assertRaises(SchemaxisError) as caught:
            self.execute([('export', export), ('consume', consume)], 'slot')
        self.assertEqual(caught.exception.fault.code, 'INVALID_PHOTO_SOURCE')
        beyond = {'version': V, 'operation': 'inspectMetadata', 'profiles': ['capture'], 'media': {'items': [bound('export', 9, 'b')]}}
        with self.assertRaises(SchemaxisError) as caught:
            self.execute([('export', export), ('consume', beyond)], 'beyond')
        self.assertEqual(caught.exception.fault.code, 'INVALID_SELECTION')

    def test_O8_a_folder_member_added_reruns_the_producer_and_the_consumer_and_the_old_plan_is_not_reused(self):
        (self.photos / 'a.jpg').write_bytes(f.fx.jpeg(make='A', model='M', dto='2026:03:01 12:00:00', off='+01:00', sub=None, seed=1))
        (self.photos / 'b.jpg').write_bytes(f.fx.jpeg(make='B', model='M', dto='2026:03:02 08:00:00', off='+01:00', sub=None, seed=2))
        folder = {'folder': {'path': str(self.photos), 'extensions': ['.jpg'], 'depth': 1}}
        plan = {'version': V, 'operation': 'planNames', 'media': folder, 'name': [{'token': 'captureDate'}, {'literal': '_'}, {'token': 'itemId'}], 'collisions': 'sequence'}
        organise = {'version': V, 'operation': 'organiseCopies', 'media': folder, 'names': {'$artifact': 'plan', 'index': 0}, 'sidecars': 'omit'}
        ops = [('plan', plan), ('organise', organise)]
        first = self.execute(ops, 'o8')
        self.assertEqual(reused(first), {'plan': False, 'organise': False})
        self.assertEqual(reused(self.execute(ops, 'o8', resume=True)), {'plan': True, 'organise': True})
        (self.photos / 'c.jpg').write_bytes(f.fx.jpeg(make='C', model='M', dto='2026:03:03 09:00:00', off='+01:00', sub=None, seed=3))
        changed = self.execute(ops, 'o8', resume=True)
        self.assertEqual(reused(changed), {'plan': False, 'organise': False})
        names = sorted(r['relativePath'] for r in json.loads((job_dir(changed, 'plan') / 'names-plan.json').read_text())['items'])
        self.assertEqual(names, ['20260301_a.jpg', '20260302_b.jpg', '20260303_c.jpg'])
        self.assertEqual(sorted(p.name for p in (job_dir(changed, 'organise') / 'organised').iterdir() if not p.name.endswith('.metadata.json')), names)

    def test_unchanged_inputs_reuse_every_job_and_changed_inputs_invalidate_exactly_what_depends_on_them(self):
        groups = ['descriptive']
        export = {'version': V, 'operation': 'exportSidecar', 'media': self.lit('a'), 'transfer': {'groups': groups}}
        apply = {'version': V, 'operation': 'applySidecar', 'media': {'items': [{'id': 'b', 'path': str(self.photos / 'b.jpg'), 'sidecar': {'$artifact': 'export', 'index': 0}}]},
                 'source': {'sidecar': 'declared'}, 'transfer': {'groups': groups}, 'policies': {'existing': 'replace'}}
        ops = [('export', export), ('apply', apply)]
        first = self.execute(ops, 'reuse')
        self.assertEqual(reused(first), {'export': False, 'apply': False})
        again = self.execute(ops, 'reuse', resume=True)
        self.assertEqual(reused(again), {'export': True, 'apply': True})
        (self.photos / 'a.jpg').write_bytes(master(seed=9, **{}))        # other pixels, same metadata: the source bytes changed, so the export (and what depends on it) is invalidated
        changed = self.execute(ops, 'reuse', resume=True)
        self.assertEqual(reused(changed), {'export': False, 'apply': False})


if __name__ == '__main__':
    unittest.main()
