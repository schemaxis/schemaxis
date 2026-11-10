"""Public workflow chains of the E3 time and location operations over real produced images (genuine ExifTool 13.55 through SCHEMAXIS_EXIFTOOL).

W1  editMetadata -> correctTime -> geotagFromTrack -> inspectMetadata and auditMetadata through ``{"$artifact": id, "index": N}`` bindings: exact bound bytes, and
    typed values decoded by the test's own hand-written readers (EXIF text, rational triples) rather than taken from any report.
W2  stable typed slots in a partly refused run: binding an outcome slot to an image consumer fails (INVALID_PHOTO_SOURCE at the bound path) and an index past the manifest fails (INVALID_SELECTION).
W3  a published plan (a text artifact) bound to the ``plan`` option of the applying operation.
W4  reuse: an unchanged resume reuses every job; a modification time alone changes nothing.
W5  invalidation by exactly the inputs that changed: GPX bytes, plan-file bytes, source photo bytes and folder membership (an authored change is a refused resume).
W6  folder mode and a mixed folder for the three write operations, with per-item outcomes and the manifest's inclusion reasons.
W7  a track that exceeds a parser limit fails the run with TRACK_RESOURCE_LIMIT before anything is written, in a direct run and in a workflow job.
Every expected value is a hand-written literal (calendar arithmetic, equator positions); each case records a stable row for the qualifier report.
"""
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests/unit'))

import exiftool_e3_fixtures as fx  # noqa: E402
from schemaxis import workflow  # noqa: E402
from schemaxis.adaptors.exiftool import adaptor  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402
from test_exiftool_e3_gpx import doc as gpx  # noqa: E402

V = 'schemaxis.exiftool/1'
# three fixes on the equator, two minutes apart: the fixtures record .12 s, so a photo 0.12 s after a fix lies 0.001 of the way to the next one (2e-6 degrees)
TRACK = gpx([[('0', '10.000', '2026-03-01T10:59:00Z', '10'), ('0', '10.002', '2026-03-01T11:01:00Z', '20'), ('0', '10.004', '2026-03-01T11:03:00Z', '30')]])


def sha(data):
    return hashlib.sha256(data).hexdigest()


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
        os.environ['SCHEMAXIS_EXIFTOOL'] = path           # workflow.verify replays native stages with the configured trusted runtime

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='e3-workflow-')).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.photos = self.root / 'photos'
        self.photos.mkdir()
        (self.photos / 'a1.jpg').write_bytes(fx.full_time(make='A'))
        (self.photos / 'b1.jpg').write_bytes(fx.full_time(make='B'))
        self.track = self.root / 'walk.gpx'
        self.track.write_bytes(TRACK)
        self.folder = {'folder': {'path': str(self.photos), 'extensions': ['.jpg'], 'depth': 1}}
        self.runs = 0

    # ---------------------------------------------------------------- graphs
    def chain(self, shift_a='60', shift_b='-60'):
        """tidy (edit, folder) -> fix (correct) -> tag (geotag) -> look (inspect) and audit."""
        tidy = {'version': V, 'operation': 'editMetadata', 'media': self.folder, 'edits': {'title': {'set': 'Chained title'}}}
        fix = {'version': V, 'operation': 'correctTime', 'media': {'items': [bound('tidy', 0, 'a1'), bound('tidy', 1, 'b1')]},
               'corrections': [{'group': 'dev1', 'shift': {'seconds': shift_a}}, {'group': 'dev2', 'shift': {'seconds': shift_b}}]}
        tag = {'version': V, 'operation': 'geotagFromTrack', 'media': {'items': [bound('fix', 0, 'a1'), bound('fix', 1, 'b1')]}, 'tracks': [{'id': 'walk', 'path': str(self.track)}]}
        look = {'version': V, 'operation': 'inspectMetadata', 'profiles': ['capture', 'location'], 'media': {'items': [bound('tag', 0, 'a1'), bound('tag', 1, 'b1')]}}
        audit = {'version': V, 'operation': 'auditMetadata', 'profiles': ['capture', 'location'], 'media': {'items': [bound('tag', 0, 'a1')]}}
        return {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'tidy', 'document': tidy}, {'id': 'fix', 'document': fix}, {'id': 'tag', 'document': tag},
                                                                    {'id': 'look', 'document': look}, {'id': 'audit', 'document': audit}]}

    def execute(self, graph, name, **kw):
        self.runs += 1
        return workflow.execute(graph, self.root / name, locations=self.locations, timeout=600, **kw)

    # ---------------------------------------------------------------- readers (hand-written, no code under test)
    @staticmethod
    def degrees(triple):
        """Exact degrees of a stored degrees/minutes/seconds rational triple."""
        (d, dd), (m, md), (sec, sd) = triple
        return Fraction(d, dd) + Fraction(m, md) / 60 + Fraction(sec, sd) / 3600

    # ---------------------------------------------------------------- W1
    def test_W1_edit_correct_geotag_inspect_audit_chain(self):
        result = self.execute(self.chain(), 'w1')
        self.assertTrue(workflow.verify(self.root / 'w1')['verified'])
        tidy, fix, tag = (job_dir(result, name) for name in ('tidy', 'fix', 'tag'))
        # the consumer captured exactly the producer bytes at every hand-off
        self.assertEqual((job_dir(result, 'fix') / 'captured' / 'a1.jpg').read_bytes(), (tidy / 'photos' / 'a1.jpg').read_bytes())
        self.assertEqual((tag / 'captured' / 'b1.jpg').read_bytes(), (fix / 'photos' / 'b1.jpg').read_bytes())
        self.assertEqual((job_dir(result, 'look') / 'captured' / 'a1.jpg').read_bytes(), (tag / 'photos' / 'a1.jpg').read_bytes())
        # values: a1 +60 s (12:01:00.12 +01:00 = 11:01:00.12Z: 0.12 s past the second fix, lon 10.002 + 0.002 * 0.001 = 10.002002); b1 -60 s (11:59:00.12 +01:00 = 10:59:00.12Z:
        # 0.12 s past the first fix, lon 10.000002)
        a1, b1 = (tag / 'photos' / 'a1.jpg').read_bytes(), (tag / 'photos' / 'b1.jpg').read_bytes()
        self.assertEqual((fx.exif_ascii(a1, 'ExifIFD', 0x9003), fx.exif_ascii(b1, 'ExifIFD', 0x9003)), ('2026:03:01 12:01:00', '2026:03:01 11:59:00'))
        for data, wanted in ((a1, Fraction(10002002, 10 ** 6)), (b1, Fraction(10000002, 10 ** 6))):
            self.assertLessEqual(abs(self.degrees(fx.exif_rationals(data, 'GPS', 0x0004)) - wanted), Fraction(2, 10 ** 10))
            self.assertEqual(fx.exif_ascii(data, 'GPS', 0x0003), 'E')
            self.assertEqual(fx.exif_rationals(data, 'GPS', 0x0002), [(0, 1), (0, 1), (0, 1)])       # the equator is exactly zero
            self.assertEqual(fx.exif_ascii(data, 'GPS', 0x0001), 'N')
        self.assertTrue((fix / 'time-report.json').is_file())
        self.assertFalse((fix / 'time-report.csv').exists())                         # the time-report CSV belongs to reconcileTime; correctTime promises its JSON reports only
        # inspect reads the same positions through the family's readers (an independent route from the writer's own report)
        profile = next((job_dir(result, 'look')).glob('profile-location.csv')).read_text()
        self.assertIn('10.002002', profile)
        audit = json.loads((job_dir(result, 'audit') / 'audit.json').read_text())
        self.assertEqual(audit['summary']['itemsAudited'], 1)
        Chain.RESULTS['W1'] = {'id': 'W1', 'operation': 'editMetadata>correctTime>geotagFromTrack>inspectMetadata+auditMetadata', 'container': 'jpeg', 'independentlyVerified': True}

    # ---------------------------------------------------------------- W2
    def test_W2_typed_slots_in_a_partly_refused_run(self):
        (self.photos / 'a1.jpg').write_bytes(fx.full_time(make='A'))
        (self.photos / 'b1.jpg').write_bytes(fx.jpeg(make='B', dto=None, create=None, sub=None, xmp=None, iptc=None))      # no time source at all
        correct = {'version': V, 'operation': 'correctTime', 'media': self.folder, 'corrections': [{'group': 'dev1', 'shift': {'seconds': '60'}}],
                   'policies': {'uncorrectedItems': 'refuseSlot'}}

        def graph(index):
            consumer = {'version': V, 'operation': 'inspectMetadata', 'profiles': ['capture'], 'media': {'items': [bound('fix', index, 'seen')]}}
            return {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'fix', 'document': correct}, {'id': 'look', 'document': consumer}]}
        result = self.execute(graph(0), 'w2-ok')
        manifest = json.loads((job_dir(result, 'fix') / 'manifest.json').read_text())
        slots = [(e['id'], e['outcome'], e['artifactIndex']) for e in manifest['entries'] if e['role'] == 'item']
        self.assertEqual([(i, o) for i, o, _ in slots], [('a1', 'written'), ('b1', 'refused')])
        # the route accepts image and text artifacts (a plan or a track is text), so an outcome document bound to a photo path is refused by the consumer, never read as another photo
        for index, code, location in ((1, 'INVALID_PHOTO_SOURCE', '$.media.items[0].path'), (99, 'INVALID_SELECTION', None)):
            with self.assertRaises(SchemaxisError) as caught:
                self.execute(graph(index), 'w2-%d' % index)
            self.assertEqual(caught.exception.fault.code, code, index)
            if location:
                self.assertEqual(caught.exception.fault.location, location)
        self.assertTrue((job_dir(result, 'fix') / 'outcomes' / 'b1.json').is_file())
        Chain.RESULTS['W2'] = {'id': 'W2', 'operation': 'correctTime', 'container': 'jpeg', 'independentlyVerified': True}

    # ---------------------------------------------------------------- W3 / W4 / W5
    def plan_graph(self, plan_literal=None):
        """plan-only correctTime -> the same operation applying the published plan (a text artifact or a literal plan file)."""
        items = {'items': [{'id': 'a1', 'path': str(self.photos / 'a1.jpg')}, {'id': 'b1', 'path': str(self.photos / 'b1.jpg')}]}
        plan = {'version': V, 'operation': 'correctTime', 'media': items, 'corrections': [{'group': 'dev1', 'shift': {'seconds': '60'}}], 'apply': 'plan'}
        apply_ = {'version': V, 'operation': 'correctTime', 'media': items, 'plan': plan_literal or {'$artifact': 'plan', 'index': 0}}
        operations = ([{'id': 'plan', 'document': plan}] if plan_literal is None else []) + [{'id': 'apply', 'document': apply_}]
        return {'version': 'schemaxis.workflow/1', 'operations': operations}

    def test_W3_a_published_plan_is_a_text_artifact_bound_to_the_plan_option(self):
        result = self.execute(self.plan_graph(), 'w3')
        self.assertTrue(workflow.verify(self.root / 'w3')['verified'])
        plan_job = job_dir(result, 'plan')
        self.assertFalse((plan_job / 'photos').exists())                           # plan-only: no image, only documents
        applied = (job_dir(result, 'apply') / 'photos' / 'a1.jpg').read_bytes()
        self.assertEqual(fx.exif_ascii(applied, 'ExifIFD', 0x9003), '2026:03:01 12:01:00')         # dev1 shifted +60 s
        self.assertEqual(fx.exif_ascii((job_dir(result, 'apply') / 'photos' / 'b1.jpg').read_bytes(), 'ExifIFD', 0x9003), '2026:03:01 12:00:00')   # dev2 untouched
        Chain.RESULTS['W3'] = {'id': 'W3', 'operation': 'correctTime(plan)>correctTime(apply)', 'container': 'jpeg', 'independentlyVerified': True}

    def test_W4_unchanged_resume_reuses_everything_and_a_modification_time_alone_changes_nothing(self):
        graph = self.chain()
        first = self.execute(graph, 'w4')
        self.assertEqual(set(reused(first).values()), {False})
        again = self.execute(graph, 'w4', resume=True)
        self.assertEqual(set(reused(again).values()), {True}, reused(again))
        future = time.time() + 3600
        for path in (self.photos / 'a1.jpg', self.track):
            os.utime(path, (future, future))                                        # the modification time changes, the bytes do not
        touched = self.execute(graph, 'w4', resume=True)
        self.assertEqual(set(reused(touched).values()), {True}, reused(touched))
        Chain.RESULTS['W4'] = {'id': 'W4', 'operation': 'editMetadata>correctTime>geotagFromTrack>inspectMetadata+auditMetadata', 'container': 'jpeg', 'independentlyVerified': True}

    def test_W5_exactly_the_changed_inputs_invalidate_reuse(self):
        graph = self.chain()
        self.execute(graph, 'w5')
        # changed GPX bytes: only the geotag job and its consumers run again; the producers keep their results
        self.track.write_bytes(TRACK.replace(b'10.002', b'10.003'))      # b1 is now 0.001 of the way from 10.000 to 10.003: 10.000003
        changed = self.execute(graph, 'w5', resume=True)
        self.assertEqual(reused(changed), {'tidy': True, 'fix': True, 'tag': False, 'look': False, 'audit': False})
        tag = (job_dir(changed, 'tag') / 'photos' / 'b1.jpg').read_bytes()
        self.assertLessEqual(abs(self.degrees(fx.exif_rationals(tag, 'GPS', 0x0004)) - Fraction(10000003, 10 ** 6)), Fraction(2, 10 ** 10))
        # changed source photo bytes: every job runs again
        (self.photos / 'a1.jpg').write_bytes(fx.full_time(make='A', seed=7))
        source = self.execute(graph, 'w5', resume=True)
        self.assertEqual(set(reused(source).values()), {False}, reused(source))
        # changed folder membership: an added matching file changes the producer's manifest, so the producer and every consumer run again (the file sorts last, so the bound
        # ordinals 0 and 1 still name a1 and b1; a file that sorted first would shift them, which is why a static index is an ordinal of one manifest, never an identity)
        (self.photos / 'c1.jpg').write_bytes(fx.full_time(make='B'))
        added = self.execute(graph, 'w5', resume=True)
        self.assertEqual(set(reused(added).values()), {False}, reused(added))
        manifest = json.loads((job_dir(added, 'tidy') / 'manifest.json').read_text())
        self.assertEqual([e['id'] for e in manifest['entries'] if e['role'] == 'item'], ['a1', 'b1', 'c1'])
        # an authored change is a refused resume, never a mixture of old and new results
        other = self.chain(shift_a='61')
        with self.assertRaises(SchemaxisError) as caught:
            self.execute(other, 'w5', resume=True)
        self.assertEqual(caught.exception.fault.code, 'RESUME_MISMATCH')
        # a plan file on disk: its bytes are a reusable input of the applying job
        planned = self.root / 'planned'
        adaptor.run(self.plan_graph()['operations'][0]['document'], planned, executable=self.exe)
        plan_file = self.root / 'time-correction-plan.json'
        shutil.copyfile(planned / 'time-correction-plan.json', plan_file)
        graph2 = self.plan_graph(plan_literal=str(plan_file))
        self.execute(graph2, 'w5-plan')
        self.assertEqual(set(reused(self.execute(graph2, 'w5-plan', resume=True)).values()), {True})
        data = plan_file.read_bytes()
        plan_file.write_bytes(data.replace(b'"Chained', b'"Chained'))              # identical bytes written again: reused
        self.assertEqual(set(reused(self.execute(graph2, 'w5-plan', resume=True)).values()), {True})
        document = json.loads(data)
        document['items'][0]['captureSha256'] = '0' * 64
        plan_file.write_bytes(json.dumps(document, indent=2).encode())
        edited = self.execute(graph2, 'w5-plan', resume=True)                       # the changed plan bytes are a changed input: the job runs again, and the edited entry is a per-item refusal
        self.assertEqual(reused(edited), {'apply': False})
        refusal = json.loads((job_dir(edited, 'apply') / 'outcomes' / 'a1.json').read_text())['fault']['code']
        self.assertIn(refusal, ('PLAN_STALE', 'PLAN_INCONSISTENT'))
        self.assertTrue((job_dir(edited, 'apply') / 'photos' / 'b1.jpg').is_file())  # the other item is still written
        Chain.RESULTS['W5'] = {'id': 'W5', 'operation': 'geotagFromTrack+correctTime', 'container': 'jpeg', 'independentlyVerified': True}

    def test_W5b_the_clock_plan_named_by_a_geotag_plan_is_a_reuse_input_and_a_pinned_capture(self):
        """A geotag plan application reuses only while the plan, its tracks and the clock-correction plan it names are unchanged; a changed clock plan reruns the job, which
        then refuses it with the exact hash fault (never a quiet reuse and never a different placement)."""
        items = {'items': [{'id': 'a1', 'path': str(self.photos / 'a1.jpg')}]}
        clock_run = self.root / 'clock-run'
        adaptor.run({'version': V, 'operation': 'correctTime', 'media': items, 'corrections': [{'group': 'dev1', 'shift': {'seconds': '60'}}], 'apply': 'plan'}, clock_run, executable=self.exe)
        clock = self.root / 'clock-plan.json'
        shutil.copyfile(clock_run / 'time-correction-plan.json', clock)
        geo_run = self.root / 'geo-run'
        adaptor.run({'version': V, 'operation': 'geotagFromTrack', 'media': items, 'tracks': [{'id': 'walk', 'path': str(self.track)}], 'photoTime': {'clockCorrection': {'plan': str(clock)}}, 'apply': 'plan'},
                    geo_run, executable=self.exe)
        geo = self.root / 'geo-plan.json'
        shutil.copyfile(geo_run / 'geotag-plan.json', geo)
        graph = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'tag', 'document': {'version': V, 'operation': 'geotagFromTrack', 'media': items, 'plan': str(geo)}}]}
        first = self.execute(graph, 'w5b')
        self.assertEqual(reused(first), {'tag': False})
        self.assertEqual(reused(self.execute(graph, 'w5b', resume=True)), {'tag': True})
        clock.write_bytes(clock.read_bytes() + b'\n')                                      # the same document with other bytes: a different input
        with self.assertRaises(SchemaxisError) as caught:                                   # not reused: the job ran again and met the pin
            self.execute(graph, 'w5b', resume=True)
        self.assertIn('CLOCK_PLAN_HASH_MISMATCH', json.dumps(caught.exception.fault.to_dict()))
        Chain.RESULTS['W5b'] = {'id': 'W5b', 'operation': 'geotagFromTrack', 'container': 'jpeg', 'independentlyVerified': True}

    # ---------------------------------------------------------------- W6
    def test_W6_folder_mode_and_a_mixed_folder_for_the_write_operations(self):
        (self.photos / 'c1.jpg').write_bytes(fx.jpeg(make='C', dto=None, create=None, sub=None, xmp=None, iptc=None))     # no time: unchanged or refused by policy
        (self.photos / 'notes.txt').write_bytes(b'not a photograph')
        (self.photos / 'big.jpeg').write_bytes(b'not a jpeg at all')                  # a .jpeg that is not a JPEG: that item faults, the rest continue
        folder = {'folder': {'path': str(self.photos), 'extensions': ['.jpg', '.jpeg'], 'depth': 1}}
        for name, document in (('correctTime', {'corrections': [{'group': 'dev1', 'shift': {'seconds': '60'}}]}),
                               ('setLocation', {'default': {'latitude': '10.5', 'longitude': '20.25'}}),
                               ('geotagFromTrack', {'tracks': [{'id': 'walk', 'path': str(self.track)}]})):
            out = self.root / ('w6-' + name)
            result = adaptor.run({'version': V, 'operation': name, 'media': folder, **document}, out, executable=self.exe)
            self.assertTrue(result['verified'])
            manifest = json.loads((out / 'manifest.json').read_text())
            excluded = {e['path']: e['reason'] for e in manifest['entries'] if e['role'] == 'excluded'}
            self.assertEqual(excluded, {'notes.txt': 'extension'})
            report = {r['id']: r for r in json.loads((out / 'write-report.json').read_text())['items']}
            self.assertEqual(report['a1']['status'], 'written', name)
            self.assertNotEqual(report['big']['status'], 'written', name)
            slots = [e['artifactIndex'] for e in manifest['entries'] if e['role'] == 'item']
            self.assertEqual(slots, sorted(slots))
            self.assertTrue(adaptor.verify(out, executable=self.exe)['verified'])
        Chain.RESULTS['W6'] = {'id': 'W6', 'operation': 'correctTime+setLocation+geotagFromTrack', 'container': 'jpeg', 'independentlyVerified': True}

    # ---------------------------------------------------------------- W7
    def test_W7_a_track_beyond_a_parser_limit_fails_before_anything_is_written(self):
        deep = b'<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">' + b'<extensions>' * 40 + b'</extensions>' * 40 + b'</gpx>'
        bomb = self.root / 'deep.gpx'
        bomb.write_bytes(deep)
        document = {'version': V, 'operation': 'geotagFromTrack', 'media': {'items': [{'id': 'a1', 'path': str(self.photos / 'a1.jpg')}]}, 'tracks': [{'id': 'deep', 'path': str(bomb)}]}
        out = self.root / 'w7'
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.run(document, out, executable=self.exe)
        self.assertEqual(caught.exception.fault.code, 'TRACK_RESOURCE_LIMIT')
        self.assertFalse((out / 'photos').exists())
        graph = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'tag', 'document': document}]}
        with self.assertRaises(SchemaxisError) as caught:
            self.execute(graph, 'w7-workflow')
        self.assertIn('TRACK_RESOURCE_LIMIT', json.dumps(caught.exception.fault.to_dict()))
        Chain.RESULTS['W7'] = {'id': 'W7', 'operation': 'geotagFromTrack', 'container': 'jpeg', 'independentlyVerified': True}


if __name__ == '__main__':
    unittest.main()
