# Copyright (C) 2026 David L F Gaden
"""Host-side contracts for reusable Blender scene preparation and rendering."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.blender.adaptor import plan as prepare_plan
from schemaxis.adaptors.blender.render_job import plan as render_plan
from schemaxis.adaptors.registry import query
from schemaxis.parallel import work_items
from schemaxis.schema import export_schema


class RenderGroupTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads(Path('examples/schemaxis/blender-render-groups.json').read_text())

    def test_preparation_has_one_scene_and_no_image_publications(self):
        document = self.document['operations'][0]['document']
        self.assertEqual(prepare_plan(document)[2]['expectedPublications'], 1)
        document['scenes'][0]['prepareOnly'] = False
        self.assertEqual(prepare_plan(document)[2]['expectedPublications'], 2)
        document['scenes'][0]['prepareOnly'] = 'yes'
        with self.assertRaises(SchemaxisError):
            prepare_plan(document)

    def test_render_plan_does_not_open_scene_or_import_blender(self):
        document = self.document['operations'][1]['document']
        document['sceneFile'] = '/does/not/exist.blend'
        self.assertEqual(render_plan(document)['expectedPublications'], 1)
        for change in [{'size': [0, 1]}, {'cameras': []}, {'render': {'threads': 0}},
                       {'cameras': [{'direction': [0, 0, 1], 'up': [0, 0, 1]}]}]:
            with self.subTest(change=change), self.assertRaises(SchemaxisError):
                render_plan({**document, **change})

    def test_allocation_matches_render_threads_and_requires_gpu_slot(self):
        operation = self.document['operations'][1]
        operation['execution'] = {'threads': 1}
        with self.assertRaises(SchemaxisError):
            work_items(self.document)
        operation['execution'] = {'threads': 2, 'gpus': 0}
        operation['document']['render']['device'] = 'OPTIX'
        with self.assertRaises(SchemaxisError):
            work_items(self.document)

    def test_saved_scene_keeps_known_defaults_without_a_synthetic_filename(self):
        with patch('schemaxis.adaptors.blender.render_job.plan',
                   side_effect=AssertionError('unresolved scene must not be planned')), \
                patch('schemaxis.parallel.provisional',
                      side_effect=AssertionError('synthetic filename prohibited')):
            jobs = work_items(self.document)[2]
        self.assertEqual([job['resources']['threads'] for job in jobs], [2, 2, 2])
        self.assertEqual([job['resources']['gpus'] for job in jobs], [0, 0, 0])
        self.assertEqual(jobs[1]['document']['sceneFile'], {'$artifact': 'prepare', 'index': 0})

    def test_known_device_and_threads_survive_an_unresolved_nonresource_setting(self):
        self.document['execution']['gpus'] = 1
        render = self.document['operations'][1]['document']['render']
        render['samples'] = {'$value': 'prepare', 'path': '/samples'}
        render['device'] = 'OPTIX'
        job = work_items(self.document)[2][1]
        self.assertEqual(job['resources']['threads'], 2)
        self.assertEqual(job['resources']['gpus'], 1)
        render['samples'] = -1
        with self.assertRaises(SchemaxisError):
            work_items(self.document)

    def test_unknown_threads_keep_explicit_reservation_until_verified_resolution(self):
        operation = self.document['operations'][1]
        operation['document']['render']['threads'] = {'$value': 'prepare', 'path': '/threads'}
        operation['execution'] = {'threads': 3}
        self.assertEqual(work_items(self.document)[2][1]['resources']['threads'], 3)

    def test_graph_handoff_reserves_known_render_settings(self):
        self.document['execution']['gpus'] = 1
        self.document['operations'] = [
            {'id': 'design', 'document': {
                'version': 'schemaxis.freecad/1', 'units': 'mm',
                'nodes': [{'id': 'box', 'filter': 'box'}], 'output': 'box'}},
            {'id': 'view', 'document': {
                'version': 'schemaxis.blender/1',
                'nodes': [{'id': 'shape', 'filter': 'readSTL',
                           'options': {'file': {'$artifact': 'design', 'index': 1}}}],
                'scenes': [{'id': 'main', 'visible': ['shape'],
                            'render': {'threads': 3, 'device': 'CUDA'},
                            'images': [{'id': 'view', 'cameras': [{'direction': [1, -2, 1]}]}]}]}}]
        job = work_items(self.document)[2][1]
        self.assertEqual(job['resources']['threads'], 3)
        self.assertEqual(job['resources']['gpus'], 1)

    def test_discovery_and_schema_include_saved_scene_rendering(self):
        report = query(self.document)
        self.assertTrue(report['supported'])
        self.assertTrue(report['adaptors'][0]['savedSceneRendering'])
        schema = export_schema(section='saved-scene-render')
        self.assertEqual(schema['properties']['version']['const'], 'schemaxis.blender.render/1')
