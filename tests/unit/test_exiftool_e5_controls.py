"""Container-specific stale-plan, forged-plan, descriptor and sidecar controls of the shared time, location and transfer writers (genuine ExifTool 13.55 through SCHEMAXIS_EXIFTOOL).

The controls run on a TIFF and a PNG (the two carrier families that differ most): a published plan applies only to the capture it was made for (PLAN_STALE), is recomputed and never trusted
(PLAN_INCONSISTENT), a plan-only run publishes documents only and the plan applies later to byte-identical output, a symbolic-link or non-regular capture path is refused as a descriptor fault before
any read, and a sidecar paired with a container item is refused for every write except applySidecar (WRITE_SIDECAR_PRESENT). Every expected value is a literal written here. They are controls: none of
them counts as support in the qualifier.
"""
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
from schemaxis.adaptors.exiftool import adaptor  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402

EXIFTOOL = os.environ.get('SCHEMAXIS_EXIFTOOL')
V = 'schemaxis.exiftool/1'
SHIFT = [{'group': 'dev1', 'shift': {'seconds': '3600'}}]


def doc(kind_paths, **rest):
    return {'version': V, 'operation': 'correctTime', 'media': {'items': [{'id': k, 'path': str(p)} for k, p in kind_paths.items()]}, **({} if 'plan' in rest else {'corrections': SHIFT}), **rest}      # a plan carries every other input


@unittest.skipUnless(EXIFTOOL and Path(EXIFTOOL).exists(), 'a real ExifTool 13.55 is needed (SCHEMAXIS_EXIFTOOL)')
class Controls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='e5-controls-')).resolve()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        cls.media = cls.tmp / 'media'
        cls.media.mkdir()
        cls.paths = {}
        for kind in ('tiff', 'png'):
            cls.paths[kind] = cls.media / ('c' + t.EXTENSIONS[kind])
            cls.paths[kind].write_bytes(t.full_time(kind))
        cls.runs = 0

    def out(self):
        type(self).runs += 1
        return self.tmp / ('run%d' % self.runs)

    def published(self, out, ident='tiff'):
        return next(p for p in sorted((out / 'photos').glob('%s.*' % ident)) if not p.name.endswith('.metadata.json')).read_bytes()

    def test_a_plan_only_run_publishes_documents_only_and_the_plan_applies_later_to_identical_output(self):
        planned = self.out()
        result = adaptor.run(doc(self.paths, apply='plan'), planned, executable=EXIFTOOL, timeout=300)
        self.assertEqual((result['apply'], result['written'], result['planned']), ('plan', 0, 2))
        self.assertFalse((planned / 'photos').exists())
        self.assertEqual(adaptor.verify(planned, executable=EXIFTOOL)['apply'], 'plan')
        direct, applied = self.out(), self.out()
        adaptor.run(doc(self.paths), direct, executable=EXIFTOOL, timeout=300)
        result = adaptor.run(doc(self.paths, plan=str(planned / 'time-correction-plan.json')), applied, executable=EXIFTOOL, timeout=300)
        self.assertTrue(result['verified'])
        for kind in ('tiff', 'png'):
            self.assertEqual(self.published(applied, kind), self.published(direct, kind), kind)
        self.assertTrue(adaptor.verify(applied, executable=EXIFTOOL)['verified'])

    def test_a_forged_plan_is_recomputed_never_trusted_and_a_changed_capture_is_stale(self):
        planned = self.out()
        adaptor.run(doc(self.paths, apply='plan'), planned, executable=EXIFTOOL, timeout=300)
        text = (planned / 'time-correction-plan.json').read_text()
        forged = json.loads(text)
        forged['items'][0]['arguments'][1] = '-ExifIFD:DateTimeOriginal=2026:03:01 13:00:01'
        path = self.tmp / 'forged-plan.json'
        path.write_text(json.dumps(forged))
        out = self.out()
        adaptor.run(doc(self.paths, plan=str(path)), out, executable=EXIFTOOL, timeout=300)
        first = json.loads((out / 'outcomes' / 'tiff.json').read_text())
        self.assertEqual((first['status'], first['fault']['code']), ('refused', 'PLAN_INCONSISTENT'))
        self.assertIs(first['image'], False)
        # a capture that is not the file the plan was made for: another make in the PNG
        changed = self.tmp / 'changed'
        changed.mkdir(exist_ok=True)
        stale = {'tiff': self.paths['tiff'], 'png': changed / 'c.png'}
        stale['png'].write_bytes(t.full_time('png', make='Z'))
        out = self.out()
        adaptor.run(doc(stale, plan=str(planned / 'time-correction-plan.json')), out, executable=EXIFTOOL, timeout=300)
        refused = json.loads((out / 'outcomes' / 'png.json').read_text())
        self.assertEqual((refused['status'], refused['fault']['code']), ('refused', 'PLAN_STALE'))
        self.assertTrue(any((out / 'photos').glob('tiff.*')))                                  # the unchanged capture is still written

    def test_a_symbolic_link_and_a_directory_are_refused_as_descriptor_faults_before_any_read(self):
        link = self.media / 'link.tif'
        if not link.exists():
            link.symlink_to(self.paths['tiff'])
        for name, path in (('link', link), ('directory', self.media)):
            with self.assertRaises(SchemaxisError) as caught:
                adaptor.run({'version': V, 'operation': 'correctTime', 'media': {'items': [{'id': name, 'path': str(path)}]}, 'corrections': SHIFT}, self.out(), executable=EXIFTOOL, timeout=300)
            first = caught.exception.fault.observed['firstFaults'][0] if caught.exception.fault.code == 'NO_USABLE_ITEMS' else caught.exception.fault.to_dict()
            self.assertEqual(first['code'], 'INVALID_PHOTO_SOURCE', name)

    def test_a_sidecar_paired_with_a_container_item_is_refused_for_every_write_except_applying_it(self):
        sidecar = self.media / 'c.xmp'
        sidecar.write_bytes(__import__('author_exiftool_fixtures').xmp_packet(e3.xmp_properties(extra=f4.lang_alt('dc:title', 'Harbour'))))
        item = {'id': 'png', 'path': str(self.paths['png']), 'sidecar': str(sidecar)}
        for operation, rest in (('correctTime', {'corrections': SHIFT}), ('editMetadata', {'edits': {'title': {'set': 'x'}}}), ('removeMetadata', {'categories': ['descriptive']})):
            out = self.out()
            with self.assertRaises(SchemaxisError) as caught:
                adaptor.run({'version': V, 'operation': operation, 'media': {'items': [item]}, **rest}, out, executable=EXIFTOOL, timeout=300)
            fault = caught.exception.fault
            code = fault.observed['firstFaults'][0]['code'] if fault.code == 'NO_USABLE_ITEMS' else fault.code
            self.assertIn(code, ('WRITE_SIDECAR_UNSUPPORTED', 'WRITE_SIDECAR_PRESENT'), operation)           # the E2 planner states it at the document, the E3 planner per item
            self.assertFalse((out / 'photos').exists(), operation)                                           # nothing was written
        out = self.out()
        result = adaptor.run({'version': V, 'operation': 'applySidecar', 'media': {'items': [item]}, 'source': {'sidecar': 'declared'}, 'transfer': {'groups': ['descriptive']}, 'policies': {'existing': 'replace'}}, out,
                             executable=EXIFTOOL, timeout=300)
        self.assertEqual((result['written'], result['refused']), (1, 0))


if __name__ == '__main__':
    unittest.main()
