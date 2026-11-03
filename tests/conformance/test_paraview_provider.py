# Copyright (C) 2026 David L F Gaden
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import unquote, urlparse

from schemaxis.core.catalogue import Catalogue
from schemaxis.core.executor import Executor
from schemaxis.core.planner import Planner
from schemaxis.core.runners import find_paraview

PACKAGE = Path(__file__).resolve().parents[2] / 'src/schemaxis/adaptors/paraview/mvp'


@unittest.skipUnless(find_paraview(), 'no ParaView interpreter discoverable')
class ParaViewProviderTests(unittest.TestCase):
    def execute_at(self, directory, origin, normal, **options):
        catalogue = Catalogue.from_roots([PACKAGE])
        document = {'documentVersion': 'schemaxis.workflow/0.1', 'steps': [{
            'id': 'slice', 'use': 'paraview.slice_export', 'arguments': {
                'origin': origin, 'normal': normal, 'outputDirectory': str(directory), **options}}]}
        plan = Planner(catalogue).resolve(document)
        return Executor(catalogue).execute(plan.to_dict())

    def test_planner_executor_export_and_semantic_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = self.execute_at(Path(temporary) / 'result', [2, 0, 0], [2, 1, 0])
            self.assertEqual(result.state.value, 'succeeded', result.to_dict())
            step = result.steps[0]
            evidence = step.observations['verification']
            self.assertTrue(evidence['verified'])
            self.assertGreater(evidence['reopened']['cells'], 0)
            self.assertLess(evidence['reopened']['maximumPlaneDistance'], 1e-5)
            self.assertEqual(evidence['live'], evidence['reopened'])
            self.assertEqual(len(step.artifacts), 3)
            for artifact in step.artifacts:
                path = Path(unquote(urlparse(artifact.uri).path))
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), artifact.digest)
            replay = Path(step.observations['submission']['scriptPath']).read_text()
            self.assertIn('SliceType.Origin = [2, 0, 0]', replay)
            self.assertIn('def export_verified_slice', replay)
            self.assertNotIn('import schemaxis.core', replay)

    def test_crinkle_preserves_whole_cells_and_writes_unstructured_grid(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'crinkle'
            result = self.execute_at(directory, [2.3, 0, 0], [1, 0, 0], crinkle=True)
            self.assertEqual(result.state.value, 'succeeded', result.to_dict())
            evidence = result.steps[0].observations['verification']
            self.assertIn('intersectedWholeInputCells', evidence['checks'])
            self.assertGreater(evidence['live']['maximumPlaneDistance'], 0)
            self.assertEqual(evidence['live']['bounds'][:2], [2, 3])
            self.assertEqual(evidence['inapplicableOptions'], ['triangulate', 'pointMergeMethod'])
            self.assertTrue((directory / 'slice.vtu').is_file())
            self.assertFalse((directory / 'slice.vtp').exists())

    def test_triangulation_and_each_point_merge_method(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence = {}
            for index, (triangulate, merge) in enumerate([
                    (True, 'uniformBinning'), (False, 'uniformBinning'),
                    (True, 'octreeBinning'), (True, 'none')]):
                result = self.execute_at(Path(temporary) / str(index), [2.3, 0, 0], [1, 0, 0],
                                         triangulate=triangulate, pointMergeMethod=merge)
                self.assertEqual(result.state.value, 'succeeded', result.to_dict())
                receipt = result.steps[0].observations['verification']
                expected_locator = {'uniformBinning': 'MergePoints',
                                    'octreeBinning': 'IncrementalOctreeMergePoints',
                                    'none': 'NonMergingPointLocator'}[merge]
                self.assertEqual(receipt['nativeConfiguration']['pointLocatorProxy'], expected_locator)
                evidence[index] = receipt['live']
            self.assertEqual(evidence[0]['cellTypes'], [5])
            self.assertNotEqual(evidence[1]['cellTypes'], [5])
            self.assertLess(evidence[1]['cells'], evidence[0]['cells'])
            self.assertEqual(evidence[2]['points'], evidence[0]['points'])
            # This image-data case has the same point count even without a locator.
            # Read-back above verifies selection; do not promise a universal count change.
            self.assertEqual(evidence[3]['points'], evidence[0]['points'])

    def test_native_intake_matches_reviewed_slice_metadata(self):
        from schemaxis.adaptors.paraview.mvp.intake import inspect_native
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'intake'
            inspect_native('filters', 'Cut', directory)
            actual = json.loads((directory / 'metadata.json').read_text())
            reviewed = json.loads((PACKAGE / 'native/slice-5.13.3.json').read_text())
            if actual['version'] != reviewed['version']:
                self.skipTest('native inventory comparison is specific to the reviewed ParaView build')
            self.assertEqual(actual['proxies'], reviewed['proxies'])
            self.assertEqual(actual['gaps'], [])

    def test_sweep_reuses_one_slice_and_verifies_every_position(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'sweep'
            result = self.execute_at(directory, [0, 0, 0], [2, 0, 0],
                                     sweep={'start': -5, 'end': 5, 'count': 3})
            self.assertEqual(result.state.value, 'succeeded', result.to_dict())
            evidence = result.steps[0].observations['verification']
            self.assertEqual(evidence['completed'], 3)
            self.assertEqual(evidence['requested'], 3)
            self.assertEqual(evidence['resolution']['positions'], [-5, 0, 5])
            self.assertEqual(evidence['resolution']['sources']['spacing'], 'derived')
            self.assertEqual({item['sliceProxyId'] for item in evidence['slices']}, {evidence['sliceProxyId']})
            self.assertEqual(len(result.steps[0].artifacts), 8)
            for index, x in enumerate([-5, 0, 5]):
                item = evidence['slices'][index]
                self.assertEqual(item['origin'], [x, 0, 0])
                self.assertEqual(item['reopened']['bounds'][:2], [x, x])
                self.assertTrue((directory / item['directory'] / 'slice.vtp').is_file())
            replay = Path(result.steps[0].observations['submission']['scriptPath']).read_text()
            self.assertEqual(replay.count('paraview.simple.Slice('), 1)
            self.assertEqual(replay.count('paraview.simple.Wavelet('), 1)

    def test_late_empty_slice_retains_verified_prefix_and_stops(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'late-empty'
            result = self.execute_at(directory, [0, 0, 0], [1, 0, 0],
                                     sweep={'start': 0, 'spacing': 20, 'count': 3})
            self.assertEqual(result.state.value, 'failed')
            self.assertEqual(result.faults[0].code, 'EMPTY_GEOMETRY')
            self.assertEqual(result.faults[0].observed['completed'], 1)
            self.assertEqual(result.faults[0].observed['index'], 1)
            receipt = json.loads((directory / 'verification.json').read_text())
            self.assertFalse(receipt['verified'])
            self.assertEqual(receipt['status'], 'failed')
            self.assertTrue(receipt['slices'][0]['verified'])
            self.assertTrue((directory / 'slice-0000/slice.vtp').is_file())
            self.assertFalse((directory / 'slice-0002').exists())

    def test_oblique_crinkle_sweep_uses_whole_cell_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = self.execute_at(Path(temporary) / 'crinkle-sweep', [0, 0, 0], [1, 1, 0],
                                     crinkle=True, sweep={'start': -2, 'end': 2, 'count': 2})
            self.assertEqual(result.state.value, 'succeeded', result.to_dict())
            for item in result.steps[0].observations['verification']['slices']:
                self.assertEqual(item['geometryFile'], 'slice.vtu')
                self.assertIn('intersectedWholeInputCells', item['checks'])

    def test_empty_slice_is_structured_failure_with_retained_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'empty'
            result = self.execute_at(directory, [50, 0, 0], [1, 0, 0])
            self.assertEqual(result.state.value, 'failed')
            self.assertEqual(result.faults[0].code, 'EMPTY_GEOMETRY')
            self.assertEqual(result.faults[0].observed['cells'], 0)
            self.assertEqual(len(list(directory.glob('replay-*.py'))), 1)
            self.assertFalse((directory / 'slice.vtp').exists())


if __name__ == '__main__':
    unittest.main()
