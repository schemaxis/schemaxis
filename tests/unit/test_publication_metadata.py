# Copyright (C) 2026 David L F Gaden
"""Output identity, spatial placement and interruption-aware companion checks."""
import json
from pathlib import Path
import struct
import tempfile
import unittest

from schemaxis.publication_metadata import publish_artifacts, verify, camera_mapping
from schemaxis.core.faults import SchemaxisError


class MetadataTests(unittest.TestCase):
    def test_table_records_do_not_invent_a_header(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root/'numbers.csv'
            path.write_text('1,2\n3,4\n')
            artifacts = [{'file': str(path), 'kind': 'table'}]
            publish_artifacts(root, artifacts)
            size = json.loads((root/'numbers.csv.metadata.json').read_text())['size']
            self.assertEqual(size['records'], 2)
            self.assertNotIn('rows', size)
            self.assertEqual(size['header'], 'unknown')
            self.assertEqual(size['columns'], 2)
            self.assertTrue(verify(root, artifacts)['verified'])
    def test_companion_membership_and_tamper(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root/'image.png'
            image.write_bytes(b'\x89PNG\r\n\x1a\n'+b'\0\0\0\rIHDR'+struct.pack('>II', 40, 20))
            artifacts = [{'file': str(image), 'kind': 'image'}]
            manifest = publish_artifacts(root, artifacts)
            metadata = json.loads((root/'image.png.metadata.json').read_text())
            self.assertEqual(metadata['size'], {'bytes': 24, 'pixels': [40, 20]})
            self.assertEqual(metadata['spatial']['state'], 'unknown')
            self.assertEqual(verify(root, artifacts)['publications'], 1)
            (root/'image.png.metadata.json').unlink()
            with self.assertRaises(SchemaxisError): verify(root, artifacts)
            self.assertFalse((root/'image.png.metadata.json').exists())
            publish_artifacts(root, artifacts)
            image.write_bytes(b'changed')
            with self.assertRaises(SchemaxisError): verify(root, artifacts)

    def test_parallel_pieces_and_escaping_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'dataset.pvtu').write_text('header')
            (root/'piece.vtu').write_text('piece')
            artifacts = [{'file': str(root/'dataset.pvtu'), 'files': [
                {'file': str(root/'dataset.pvtu')}, {'file': str(root/'piece.vtu')}]}]
            publish_artifacts(root, artifacts)
            self.assertEqual(verify(root, artifacts)['publications'], 2)
            self.assertEqual(json.loads((root/'dataset.pvtu.metadata.json').read_text())['size']['bundleBytes'], 11)
            (root/'linked').symlink_to(root/'piece.vtu')
            with self.assertRaises(SchemaxisError): publish_artifacts(root, [{'file': str(root/'linked')}])

    def test_orthographic_slice_corners(self):
        camera = {'position': [0,0,10], 'focalPoint': [0,0,0], 'up': [0,1,0], 'parallel': True, 'scale': 2}
        result = camera_mapping(camera, [200,100], {'origin': [0,0,3], 'normal': [0,0,1]})
        self.assertEqual(result['corners'], [[-4,2,3],[4,2,3],[4,-2,3],[-4,-2,3]])
        self.assertEqual(result['mapping'], 'pixel-edge-rays-to-slice-plane')

    def test_perspective_and_focal_plane_are_distinct(self):
        camera = {'position': [0,0,10], 'focalPoint': [0,0,0], 'up': [0,1,0], 'parallel': False, 'scale': 2, 'viewAngle': 90}
        result = camera_mapping(camera, [100,100], {'origin': [0,0,5], 'normal': [0,0,1]})
        self.assertAlmostEqual(result['corners'][0][0], -5)
        self.assertEqual(result['corners'][0][2], 5)
        self.assertEqual(camera_mapping(camera, [100,100])['mapping'], 'camera-focal-plane')
        with self.assertRaises(ValueError):
            camera_mapping(camera, [100,100], {'origin': [0,0,11], 'normal': [0,0,1]})

    def test_failed_staging_does_not_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'a').write_text('a')
            with self.assertRaises(SchemaxisError):
                publish_artifacts(root, [{'file': str(root/'a')}, {'file': str(root/'missing')}])
            self.assertFalse((root/'publication-metadata.json').exists())

    def test_observed_size_and_spatial_are_retained(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'table.csv').write_text('x,y\n1,2\n')
            artifact = {'file': str(root/'table.csv'), 'kind': 'table', 'rows': 1,
                        'columns': ['x','y'], 'spatial': {'state': 'known', 'frame': 'native-world',
                        'units': 'mm', 'bounds': [0,1,0,2,0,0],
                        'boundsOrder':['xmin','xmax','ymin','ymax','zmin','zmax']}}
            publish_artifacts(root, [artifact])
            metadata = json.loads((root/'table.csv.metadata.json').read_text())
            self.assertEqual(metadata['spatial'], artifact['spatial'])
            self.assertEqual(metadata['size']['rows'], 1)
            self.assertEqual(metadata['size']['columns'], ['x','y'])

    def test_finalisation_failure_marks_execution_failed(self):
        from unittest.mock import patch
        from schemaxis.adaptor_runtime import execute
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = {'version': 'schemaxis.test/1'}
            def native_run(document, directory, **kwargs):
                (directory/'result.json').write_text(json.dumps({'status':'succeeded','verified':True,'nativeEvidence':'retained'}))
                return {'status':'succeeded'}
            with patch('schemaxis.schema_snapshots.capture_run'), \
                    patch('schemaxis.publication_metadata.finalise', side_effect=OSError('injected disk failure')):
                with self.assertRaises(OSError):
                    execute(document, root, {}, native_run, lambda *a: True, lambda d: {}, timeout=1)
            result = json.loads((root/'result.json').read_text())
            self.assertEqual(result['status'], 'failed')
            self.assertFalse(result['verified'])
            self.assertEqual(result['nativeEvidence'], 'retained')

    def test_gmsh_axis_group_bounds_order(self):
        from schemaxis.adaptors.gmsh.adaptor import manifest
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bounds = [1,2,3,11,22,33]
            for name in ('result.msh','volume.vtu','boundary.vtu'):
                (root/name).write_text('fixture')
            (root/'mesh-summary.json').write_text(json.dumps({'bounds':bounds,'nodes':8,'elements':5}))
            records = manifest(root)
            self.assertEqual(records[0]['spatial']['bounds'], bounds)
            self.assertEqual(records[0]['spatial']['boundsOrder'], ['xmin','ymin','zmin','xmax','ymax','zmax'])
            self.assertEqual(records[0]['data'], {'nodes':8,'elements':5})
            self.assertEqual(records[-1]['spatial']['state'], 'notApplicable')
