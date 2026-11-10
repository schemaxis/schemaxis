"""Meaningful authoring and independently decoded frame-publication controls."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from schemaxis.adaptors.blender.production_outputs import (
    file_geometry, matching_metrics, output_count, output_jobs,
    triangle_metrics, validate_outputs, verify_outputs)
from schemaxis.core.faults import SchemaxisError


class ProductionOutputsTest(unittest.TestCase):
    def production(self):
        return {'frameStart': 2, 'frameEnd': 20, 'currentFrame': 5,
                'exports': [{'id': 'part', 'format': 'obj', 'objects': ['mesh']}],
                'renderFrames': [2, 20], 'camera': 'camera'}

    def test_frame_defaults_do_not_mutate_authored_input(self):
        production = self.production()
        original = copy.deepcopy(production)
        normal = validate_outputs(production, {'mesh', 'camera'})
        self.assertEqual(normal['exports'][0]['frame'], 5)
        self.assertEqual(production, original)
        self.assertEqual(output_count(normal), 3)
        self.assertEqual([j['name'] for j in output_jobs(normal, '0000')],
                         ['0000-export-part.obj', '0000-frame-000002.png', '0000-frame-000020.png'])

    def test_invalid_intent_and_references_fail_before_native_execution(self):
        for change in [
            {'exports': [{'id': '../part', 'format': 'obj', 'objects': ['mesh']}]},
            {'exports': [{'id': 'part', 'format': 'obj', 'objects': ['missing']}]},
            {'exports': [{'id': 'part', 'format': 'obj', 'objects': ['mesh', 'mesh']}]},
            {'exports': [{'id': 'part', 'format': 'fbx', 'objects': ['mesh']}]},
            {'exports': [{'id': 'part', 'format': 'obj', 'objects': ['mesh'], 'frame': True}]},
            {'exports': [{'id': 'part', 'format': 'obj', 'objects': ['mesh'], 'frame': 21}]},
            {'exports': [{'id': 'part', 'format': 'obj', 'objects': ['mesh'], 'python': 'pass'}]},
            {'renderFrames': [2, 2]}, {'renderFrames': [True]},
            {'renderFrames': [1]}, {'camera': 'missing'}, {'frameStart': 30}]:
            with self.subTest(change=change), self.assertRaises(SchemaxisError):
                validate_outputs({**self.production(), **change}, {'mesh', 'camera'})

    def test_duplicate_publication_names_and_unsafe_prefix_are_rejected(self):
        production = self.production()
        production['exports'] *= 2
        with self.assertRaises(SchemaxisError):
            validate_outputs(production, {'mesh', 'camera'})
        with self.assertRaises(SchemaxisError):
            output_jobs(self.production(), '../escape')

    def test_geometric_moments_and_winding_have_literal_expectations(self):
        a, b, c, d = (0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)
        mesh = [(a, c, b), (a, b, d), (a, d, c), (b, c, d)]
        observed = triangle_metrics(mesh)
        self.assertEqual(observed['triangles'], 4)
        self.assertEqual(observed['bounds'], [0, 1, 0, 1, 0, 1])
        self.assertAlmostEqual(observed['signedVolume'], 1/6)
        self.assertAlmostEqual(observed['area'], (3 + 3**.5)/2)
        reversed_mesh = [tuple(reversed(face)) for face in mesh]
        self.assertFalse(matching_metrics(observed, triangle_metrics(reversed_mesh)))

    def test_boolean_numeric_metrics_and_geometry_are_rejected(self):
        triangle = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
        expected = triangle_metrics([triangle])
        for key, forged in [('triangles', True), ('area', True), ('bounds', [False]*6)]:
            with self.subTest(key=key):
                self.assertFalse(matching_metrics(expected, {**expected, key: forged}))
        with self.assertRaises(SchemaxisError):
            triangle_metrics([[(False, 0, 0), *triangle[1:]]])

    def test_three_file_encodings_are_checked_against_one_literal_triangle(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'part.obj').write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nf -3 -2 -1\n')
            (root/'part.ply').write_text('ply\nformat ascii 1.0\nelement vertex 3\n'
                'property float x\nproperty float y\nproperty float z\nelement face 1\n'
                'property list uchar uint vertex_indices\nend_header\n0 0 0\n1 0 0\n0 1 0\n3 0 1 2\n')
            (root/'part.stl').write_bytes(bytes(80) + struct.pack('<I', 1)
                + struct.pack('<12fH', 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0))
            for format in ('obj', 'ply', 'stl'):
                with self.subTest(format=format):
                    result = file_geometry(root/f'part.{format}', format)
                    self.assertEqual(result['triangles'], 1)
                    self.assertEqual(result['area'], .5)
                    self.assertEqual(result['bounds'], [0, 1, 0, 1, 0, 0])
                    self.assertEqual(result['surfaceCentre'], [1/3, 1/3, 0])

    def test_small_geometry_uses_dimensionally_scaled_tolerances(self):
        small = triangle_metrics([[(0, 0, 0), (.001, 0, 0), (0, .001, 0)]])
        self.assertFalse(matching_metrics(small, {**small, 'area': small['area']*1.1}))
        self.assertTrue(matching_metrics(small, {**small, 'area': small['area']*(1+1e-6)}))

    def test_glb_axis_conversion_and_binary_geometry_are_independently_decoded(self):
        # glTF Y-up points represent a Blender XY-plane triangle.
        binary = struct.pack('<9f3H', 0, 0, 0, 1, 0, 0, 0, 0, -1, 0, 1, 2)
        document = {'asset': {'version': '2.0'}, 'buffers': [{'byteLength': len(binary)}],
            'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': 36},
                            {'buffer': 0, 'byteOffset': 36, 'byteLength': 6}],
            'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 3, 'type': 'VEC3'},
                          {'bufferView': 1, 'componentType': 5123, 'count': 3, 'type': 'SCALAR'}],
            'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1}]}],
            'nodes': [{'mesh': 0}], 'scenes': [{'nodes': [0]}], 'scene': 0}
        def encoded():
            source = json.dumps(document).encode()
            source += b' ' * (-len(source) % 4)
            data = binary + b'\0' * (-len(binary) % 4)
            length = 12 + 8 + len(source) + 8 + len(data)
            return (struct.pack('<III', 0x46546C67, 2, length)
                + struct.pack('<II', len(source), 0x4E4F534A) + source
                + struct.pack('<II', len(data), 0x004E4942) + data)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'part.glb'
            path.write_bytes(encoded())
            self.assertEqual(file_geometry(path, 'glb')['area'], .5)
            self.assertEqual(file_geometry(path, 'glb')['bounds'], [0, 1, 0, 1, 0, 0])
            document['nodes'][0]['translation'] = [1, 0, 0]
            path.write_bytes(encoded())
            with self.assertRaises(SchemaxisError):
                file_geometry(path, 'glb')

    def test_usd_geometry_and_active_transform_unit_controls_are_independent(self):
        source = '''#usda 1.0
( metersPerUnit = 1
upAxis = "Z" )
def Mesh "part" (active = true) {
 int[] faceVertexCounts = [3]
 int[] faceVertexIndices = [0, 1, 2]
 point3f[] points = [(0,0,0), (1,0,0), (0,1,0)]
 uniform token subdivisionScheme = "none"
}
'''
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'part.usda'
            path.write_text(source)
            self.assertEqual(file_geometry(path, 'usd')['area'], .5)
            for changed in [source.replace('active = true', 'active = false'),
                            source.replace('metersPerUnit = 1', 'metersPerUnit = 0.001'),
                            source.replace('"none"', '"catmullClark"'),
                            source.replace(' int[] faceVertexCounts', ' double3 xformOp:translate = (1,0,0)\n int[] faceVertexCounts')]:
                path.write_text(changed)
                with self.subTest(changed=changed), self.assertRaises(SchemaxisError):
                    file_geometry(path, 'usd')

    def test_refreshed_hash_does_not_hide_changed_obj_geometry(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root/'run-export-part.obj'
            path.write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n')
            prod = {'exports': [{'id': 'part', 'format': 'obj', 'objects': ['mesh'], 'frame': 1}]}
            metrics = file_geometry(path, 'obj')
            record = {'id': 'part', 'format': 'obj', 'objects': ['mesh'], 'frame': 1,
                      'units': 'metres', 'sourceUnits': 'metres', 'coordinateScale': 1.0,
                      'kind': 'geometry', 'file': str(path), 'productionOutput': True,
                      'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                      'before': metrics, 'after': metrics}
            self.assertTrue(verify_outputs([record], prod, root, 'run'))
            path.write_text(path.read_text().replace('v 1 0 0', 'v 2 0 0'))
            record['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaises(SchemaxisError):
                verify_outputs([record], prod, root, 'run')

    def test_membership_path_and_frame_cannot_be_substituted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root/'run-export-part.obj'
            path.write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n')
            prod = {'exports': [{'id': 'part', 'format': 'obj', 'objects': ['mesh'], 'frame': 1}]}
            metrics = file_geometry(path, 'obj')
            record = {'id': 'part', 'format': 'obj', 'objects': ['mesh'], 'frame': 1,
                      'units': 'metres', 'sourceUnits': 'metres', 'coordinateScale': 1.0,
                      'kind': 'geometry', 'file': str(path), 'productionOutput': True,
                      'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                      'before': metrics, 'after': metrics}
            for key, value in [('frame', True), ('objects', ['other']), ('id', 'other'),
                               ('units', 'millimetres'), ('coordinateScale', True),
                               ('file', str(root/'../run-export-part.obj'))]:
                with self.subTest(key=key), self.assertRaises(SchemaxisError):
                    verify_outputs([{**record, key: value}], prod, root, 'run')

    def test_malformed_file_and_external_obj_dependencies_are_structured_faults(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'bad.obj'
            for text in ['v broken 0 0\n', 'mtllib untracked.mtl\n',
                         'v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 4\n']:
                path.write_text(text)
                with self.subTest(text=text), self.assertRaises(SchemaxisError):
                    file_geometry(path, 'obj')


if __name__ == '__main__':
    unittest.main()
