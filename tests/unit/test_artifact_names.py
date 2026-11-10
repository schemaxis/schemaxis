"""Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0"""
from concurrent.futures import ProcessPoolExecutor
from contextvars import copy_context
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import json

from schemaxis.artifact_names import OutputSequence, run_scope, run_root, scalar, stem
from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.paraview.output_names import image_properties
from schemaxis_viewer.library import inventory


def reservations(root):
    sequence = OutputSequence(root)
    return [sequence.reserve() for _ in range(25)]


class ArtifactNamesTests(unittest.TestCase):
    def test_readable_numbers_and_lossless_text(self):
        self.assertEqual(stem(7, {'pos': -4.38e-6, 'normal': [-2.1, 1., 3], 'related': ['A', 'B', 'C', 11]}),
                         '000007__pos_-4.38e-06__normal_list_-2.1_1.0_3__related_list_A_B_C_11')
        self.assertEqual(scalar('wall_shear'), 'wall.x5F.shear')
        self.assertEqual(scalar('11'), '.x31.1')
        self.assertEqual(scalar('list'), '.x6C.ist')
        self.assertEqual(scalar('a.x5F.b'), 'a.x2E.x5F.x2E.b')
        self.assertEqual(scalar('é'), '.xC3..xA9.')
        self.assertEqual(stem(3, {'empty': []}, worker=20), '000003.20__empty_list')
        for bad in (float('inf'), float('nan'), {'a': 1}, [[1]]):
            with self.assertRaises(SchemaxisError):
                stem(1, {'value': bad})
        with self.assertRaises(SchemaxisError):
            stem(1000000, {})
        with self.assertRaises(SchemaxisError):
            stem(1, {'scene': 'a' * 200})

    def test_parallel_processes_resume_and_fresh_runs(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as other:
            with ProcessPoolExecutor(max_workers=4) as pool:
                groups = list(pool.map(reservations, [root]*4))
            self.assertEqual(sorted(n for group in groups for n in group), list(range(100)))
            self.assertTrue(all(group == sorted(group) for group in groups))
            self.assertEqual(OutputSequence(root).reserve(), 100)
            self.assertEqual(OutputSequence(other).reserve(), 0)
            self.assertEqual(inventory([root]), [])

    def test_workflow_root_propagates_into_children_and_copied_contexts(self):
        with run_scope('/outer'):
            with run_scope('/outer/child'):
                self.assertEqual(copy_context().run(run_root, '/ignored'), Path('/outer'))
        self.assertEqual(run_root('/fresh'), Path('/fresh'))

    def test_reservation_survives_failed_write_and_range_exhaustion(self):
        with tempfile.TemporaryDirectory() as root:
            sequence = OutputSequence(root)
            self.assertEqual(sequence.path(root, {'kind': 'image'}, '.png').name, '000000__kind_image.png')
            self.assertEqual(OutputSequence(root).reserve(), 1)
            sequence.next = 999999
            self.assertEqual(sequence.reserve(), 999999)
            with self.assertRaises(SchemaxisError):
                sequence.reserve()

    def test_legacy_resume_advances_beyond_retained_output_prefixes(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / '000042-old-image.png').write_bytes(b'old evidence')
            self.assertEqual(OutputSequence(root).reserve(), 43)

    def test_fields_and_native_plane_define_names_without_guessing(self):
        scene = {'id': 'sliceX00', 'appearances': [{'slice': {'field': ['POINTS', 'U']}},
                                                {'slice': {'field': ['POINTS', 'p']}}]}
        fields = image_properties(scene, {'slice': {'field': ['POINTS', 'U']}},
                                  {'origin': [-.0483, 0, 0], 'normal': [2, 0, 0]}, 0, 0)
        self.assertEqual(fields, {'kind': 'slice', 'scene': 'sliceX00', 'axis': 'X', 'pos': -.0483,
                                  'var': 'U', 'time': 0})
        scene['appearances'] *= 2
        fields = image_properties(scene, {'a': {'field': ['POINTS', 'U']}, 'b': {'field': ['CELLS', 'p']}},
                                  None, 1, 0)
        self.assertEqual(fields['var'], ['U', 'p'])
        self.assertEqual(fields['appearance'], 0)
        self.assertNotIn('model', fields)  # Context geometry is not inferred from node names.

    def test_native_publication_loop_numbers_every_payload_across_operations(self):
        # Exercise the actual native publication loop and plan with a mocked
        # application boundary; native scientific export checks live elsewhere.
        from schemaxis.adaptors.paraview import native_run
        document = {'version': 'schemaxis/1', 'nodes': [{'id': 's', 'filter': 'sphere'}],
                    'scenes': [{'id': f'sliceX{i:02d}', 'visible': {'s': {'field': ['POINTS', 'U']}},
                                'geometry': ['s'], 'measurements': [{'node': 's'}],
                                'appearances': [{}, {'s': {'field': ['POINTS', 'p']}}],
                                'images': [{'id': 'view', 'cameras': [{}, {}]}]} for i in range(2)]}
        def closure(*args):
            active = MagicMock(closed=False, events=[])
            active.handles = {'s': MagicMock()}
            active.apply.side_effect = lambda visit: {'observations': {}, 'samples': []}
            active.close.side_effect = lambda: setattr(active, 'closed', True)
            return active
        def artifact(path, extension=''):
            path = Path(str(path)+extension)
            path.write_bytes(b'synthetic test payload')
            return {'file': str(path)}
        renderer = MagicMock()
        renderer.prepare.return_value = {}
        renderer.write.side_effect = lambda path, *args: artifact(path)
        vtk = SimpleNamespace(vtkMultiProcessController=SimpleNamespace(GetGlobalController=lambda: None))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.dict('sys.modules', {'vtkmodules.vtkParallelCore': vtk}), \
                    patch.dict('os.environ', {'SCHEMAXIS_OUTPUT_RUN_ROOT': temporary}), \
                    patch.object(native_run, 'ParaViewBackend'), patch.object(native_run, 'RuntimeClosure', closure), \
                    patch.object(native_run, 'Renderer', return_value=renderer), \
                    patch.object(native_run, 'runtime_identity', return_value={}), \
                    patch.object(native_run, 'scene_bounds', return_value=[0, 1, 0, 1, 0, 1]), \
                    patch.object(native_run, 'observed_slice_plane', return_value={'origin': [.1, 0, 0], 'normal': [1, 0, 0]}), \
                    patch.object(native_run, 'geometry', side_effect=lambda b, p, path: artifact(path, '.vtu')), \
                    patch.object(native_run, 'measurement', side_effect=lambda b, p, path, a: artifact(path, '.csv')):
                names = []
                for i in range(2):
                    directory = root / f'operation{i}'
                    directory.mkdir()
                    native_run.execute(document, directory)
                    receipt = json.loads((directory / 'verification.json').read_text())
                    self.assertEqual(receipt['status'], 'succeeded')
                    names.extend(Path(a['file']).name for a in receipt['artifacts'])
            self.assertEqual([int(n[:6]) for n in names], list(range(24)))
            self.assertTrue(any('__var_U__' in n for n in names))
            self.assertTrue(any('__var_p__' in n for n in names))
            self.assertTrue(all('appearance-' not in n for n in names))
