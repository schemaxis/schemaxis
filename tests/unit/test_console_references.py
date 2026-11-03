# Copyright (C) 2026 David L F Gaden
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.core.faults import SchemaxisError
from schemaxis.console_references import ReferenceStore


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = ReferenceStore(self.directory.name)
        self.geometry = {'revision': 3, 'units': 'mm', 'objects': [
            {'id': 'gear', 'label': 'GEAR_TOOTH_03', 'faces': [
                {'id': 'Face1', 'vertices': [[0, 0, 0], [1, 0, 0], [0, 1, 0]], 'triangles': [[0, 1, 2]]}]}]}
        self.pick = {'revision': 3, 'object': 'gear', 'subelement': 'Face1', 'point': [.2, .3, 0]}

    def test_reference_survives_restart_with_native_identity_and_prose(self):
        reference = self.store.register(self.pick, 'assembly', self.geometry)
        restored = ReferenceStore(self.directory.name)
        message = restored.message([{'text': 'More clearance beside '}, {'reference': reference['id']}], 'assembly', 3)
        picked = message['segments'][1]['reference']
        self.assertEqual(picked['subelement'], 'Face1')
        self.assertEqual(picked['point'], [.2, .3, 0])
        self.assertIn('GEAR_TOOTH_03', picked['label'])
        self.assertFalse(message['executed'])

    def test_upstream_edit_prevents_reusing_stale_selection(self):
        reference = self.store.register(self.pick, 'assembly', self.geometry)
        self.assertTrue(self.store.list('assembly', 4)[0]['stale'])
        with self.assertRaises(SchemaxisError) as caught:
            self.store.message([{'reference': reference['id']}], 'assembly', 4)
        self.assertEqual(caught.exception.fault.code, 'STALE_REFERENCE')
        with self.assertRaises(SchemaxisError):
            self.store.register({**self.pick, 'revision': 2}, 'assembly', self.geometry)

    def test_unknown_topology_nonfinite_and_outside_points_rejected(self):
        for extra in ({'object': 'other'}, {'subelement': 'Face20'}, {'point': [float('nan'), 0, 0]}, {'point': [5, 5, 5]}):
            with self.subTest(extra=extra), self.assertRaises(SchemaxisError):
                self.store.register({**self.pick, **extra}, 'assembly', self.geometry)
        self.assertEqual(self.store.data['references'], [])

    def test_reference_cannot_cross_document(self):
        ref = self.store.register(self.pick, 'assembly', self.geometry)
        with self.assertRaises(SchemaxisError):
            self.store.message([{'reference': ref['id']}], 'other', 3)

    def test_sketch_edges_and_vertices_can_be_referenced(self):
        self.geometry['objects'][0].update(faces=[], edges=[{'id':'Edge1','points':[[0,0,0],[1,0,0]]}],
                                           vertices=[{'id':'Vertex1','point':[0,0,0]}])
        edge=self.store.register({**self.pick,'subelement':'Edge1','point':[.5,0,0]},'assembly',self.geometry)
        self.assertTrue(edge['label'].startswith('edge '))
        vertex=self.store.register({**self.pick,'subelement':'Vertex1','point':[0,0,0]},'assembly',self.geometry)
        self.assertTrue(vertex['label'].startswith('vertex '))
        with self.assertRaises(SchemaxisError):
            self.store.register({**self.pick,'subelement':'Edge1','point':[.5,.1,0]},'assembly',self.geometry)

    def test_face_bounding_box_alone_is_not_sufficient(self):
        with self.assertRaises(SchemaxisError):
            self.store.register({**self.pick,'point':[.9,.9,0]},'assembly',self.geometry)

    def test_image_reference_is_digest_bound_and_uses_pixel_coordinates(self):
        metadata = {'document': 'sprite', 'revision': 3, 'sha256': 'abc', 'width': 16, 'height': 32, 'artifact': '/retained/preview.png'}
        request = {'revision': 3, 'imageDigest': 'abc', 'pixel': [5, 7]}
        ref = self.store.register_image(request, 'sprite', metadata)
        self.assertEqual(ref['coordinateSpace'], 'image-pixel')
        self.assertEqual(ref['imageSize'], [16, 32])
        message = self.store.message([{'text': 'Recolour '}, {'reference': ref['id']}], 'sprite', 3)
        self.assertEqual(message['segments'][1]['reference']['imageDigest'], 'abc')
        with self.assertRaises(SchemaxisError):
            self.store.message([{'reference': ref['id']}], 'sprite', 3, image_digest='replacement')
        for change in ({'pixel': [16, 0]}, {'pixel': [-1, 0]}, {'pixel': [1.5, 0]},
                       {'pixel': [True, 0]}, {'imageDigest': 'different'}, {'revision': 2}):
            with self.subTest(change=change), self.assertRaises(SchemaxisError):
                self.store.register_image({**request, **change}, 'sprite', metadata)

    def test_failed_persistence_does_not_publish_phantom_reference(self):
        with patch('schemaxis.console_references.atomic', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.store.register(self.pick, 'assembly', self.geometry)
        self.assertEqual(self.store.data['references'], [])
