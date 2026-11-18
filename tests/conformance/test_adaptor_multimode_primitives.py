# Copyright (C) 2026 David L. F. Gaden.
"""Native evidence for independently authored sibling primitives."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from schemaxis.adaptors.blender.adaptor import run as run_blender, verify as verify_blender
from schemaxis.adaptors.freecad.adaptor import run as run_freecad, verify as verify_freecad
from schemaxis.adaptors.godot.adaptor import run as run_godot, verify as verify_godot
from schemaxis.configuration import location_context


class MultimodePrimitives(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('FREECAD_CMD'), 'set FREECAD_CMD for native FreeCAD')
    def test_freecad_seeds_have_independent_owners_and_solids(self):
        document = {'version': 'schemaxis.freecad/1', 'output': 'rightSeed', 'nodes': [
            {'id': 'shortStock', 'filter': 'box', 'options': {'length': 10, 'width': 10, 'height': 10}},
            {'id': 'longStock', 'filter': 'box', 'options': {'length': 20, 'width': 10, 'height': 10}},
            {'id': 'leftBody', 'filter': 'body'}, {'id': 'rightBody', 'filter': 'body'},
            {'id': 'leftSeed', 'filter': 'bodySeed', 'inputs': {'body': 'leftBody', 'source': 'shortStock'}},
            {'id': 'rightSeed', 'filter': 'bodySeed', 'inputs': {'body': 'rightBody', 'source': 'longStock'}},
        ], 'measurements': [
            {'id': 'leftVolume', 'node': 'leftSeed', 'quantity': 'volume'},
            {'id': 'rightVolume', 'node': 'rightSeed', 'quantity': 'volume'},
        ]}
        with tempfile.TemporaryDirectory() as temporary, location_context({'freecad': os.environ['FREECAD_CMD']}):
            directory = Path(temporary) / 'seeds'
            run_freecad(document, directory, timeout=120)
            checked = verify_freecad(directory)
            self.assertTrue(checked['verified'])
            self.assertAlmostEqual(checked['volumeMM3'], 2000, places=3)
            measurements = json.loads((directory / 'measurements.json').read_text())['measurements']
            self.assertAlmostEqual(measurements['leftVolume']['value'], 1000, places=3)
            self.assertAlmostEqual(measurements['rightVolume']['value'], 2000, places=3)

    @unittest.skipUnless(os.environ.get('FREECAD_CMD'), 'set FREECAD_CMD for native FreeCAD')
    def test_freecad_boxes_keep_independent_dimensions(self):
        first = {'id': 'original', 'filter': 'box', 'options': {
            'length': 10, 'width': 20, 'height': 30, 'origin': [1, 2, 3]}}
        sibling = copy.deepcopy(first)
        sibling['id'] = 'box_15_20_30'
        sibling['options']['length'] = 15
        document = {'version': 'schemaxis.freecad/1', 'units': 'mm', 'nodes': [first, sibling],
                    'measurements': [
                        {'id': 'originalVolume', 'node': 'original', 'quantity': 'volume'},
                        {'id': 'siblingVolume', 'node': sibling['id'], 'quantity': 'volume'},
                    ]}
        with tempfile.TemporaryDirectory() as temporary:
            for output, expected in [('original', 6000), ('box_15_20_30', 9000)]:
                directory = Path(temporary) / output
                run_freecad({**document, 'output': output}, directory, timeout=120)
                checked = verify_freecad(directory)
                self.assertTrue(checked['verified'])
                self.assertAlmostEqual(checked['volumeMM3'], expected, places=3)
                measurements = json.loads((directory / 'measurements.json').read_text())['measurements']
                self.assertAlmostEqual(measurements['originalVolume']['value'], 6000, places=3)
                self.assertAlmostEqual(measurements['siblingVolume']['value'], 9000, places=3)

    @unittest.skipUnless(os.environ.get('GODOT_EXECUTABLE'), 'set GODOT_EXECUTABLE for native Godot')
    def test_godot_spheres_share_material_but_keep_independent_transforms(self):
        nodes = [
            {'id': 'paint', 'filter': 'material', 'options': {'colour': [0.1, 0.4, 0.8]}},
            {'id': 'first', 'filter': 'sphere', 'inputs': {'material': 'paint'},
             'options': {'position': [-2, 0, 0], 'radius': 0.5}},
            {'id': 'sphere_2_0_0_1', 'filter': 'sphere', 'inputs': {'material': 'paint'},
             'options': {'position': [2, 0, 0], 'radius': 1}},
            {'id': 'view', 'filter': 'camera', 'options': {'position': [6, 4, 8], 'target': [0, 0, 0]}},
        ]
        document = {'version': 'schemaxis.godot/1', 'units': 'm', 'nodes': nodes}
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'scene'
            run_godot(document, directory, timeout=120)
            verified = verify_godot(directory)
            self.assertTrue(verified['verified'])
            receipts = list(directory.rglob('reopened.json'))
            self.assertEqual(len(receipts), 1)
            observed = json.loads(receipts[0].read_text())['scene']['nodes']
            for identity, position, radius in (
                    ('first', [-2, 0, 0], 0.5), ('sphere_2_0_0_1', [2, 0, 0], 1)):
                self.assertEqual(observed[identity]['position'], position)
                self.assertEqual(observed[identity]['parameters']['radius'], radius)
            self.assertEqual(observed['first']['material'], observed['sphere_2_0_0_1']['material'])

    @unittest.skipUnless(os.environ.get('SCHEMAXIS_BLENDER'), 'set SCHEMAXIS_BLENDER for native Blender')
    def test_blender_cubes_share_material_but_keep_independent_dimensions(self):
        nodes = [
            {'id': 'paint', 'filter': 'material'},
            {'id': 'first', 'filter': 'cube', 'inputs': {'material': 'paint'},
             'options': {'size': 2, 'centre': [-3, 0, 0]}},
            {'id': 'second', 'filter': 'cube', 'inputs': {'material': 'paint'},
             'options': {'size': 4, 'centre': [3, 0, 0]}},
        ]
        document = {'version': 'schemaxis.blender/1', 'nodes': nodes,
                    'scenes': [{'id': 'main', 'visible': ['first', 'second'], 'prepareOnly': True,
                                'render': {'samples': 1, 'threads': 1},
                                'images': [{'id': 'view', 'size': [32, 32],
                                            'cameras': [{'direction': [1, -2, 1]}]}],
                                'production': {'exports': [
                                    {'id': 'firstPart', 'format': 'ply', 'objects': ['first']},
                                    {'id': 'secondPart', 'format': 'ply', 'objects': ['second']},
                                ]}}]}
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'scene'
            run_blender(document, directory, timeout=120)
            self.assertTrue(verify_blender(directory)['verified'])
            receipts = list(directory.rglob('verification.json'))
            native = [data for path in receipts if 'states' in (data := json.loads(path.read_text()))
                      and data['states'] and 'observations' in data['states'][0]]
            self.assertEqual(len(native), 1)
            observations = native[0]['states'][0]['observations']
            self.assertEqual(observations['first']['bounds'][:2], [-4, -2])
            self.assertEqual(observations['second']['bounds'][:2], [1, 5])
            files = {path.name for path in directory.rglob('*.ply')}
            self.assertTrue(any(name.endswith('-export-firstPart.ply') for name in files), files)
            self.assertTrue(any(name.endswith('-export-secondPart.ply') for name in files), files)

    @unittest.skipUnless(os.environ.get('SCHEMAXIS_BLENDER'), 'set SCHEMAXIS_BLENDER for native Blender')
    def test_blender_material_graph_preserves_separate_value_nodes_and_links(self):
        graph = {
            'id': 'paint',
            'nodes': [
                {'id': 'original', 'kind': 'value', 'properties': {'value': 0.25}},
                {'id': 'shader', 'kind': 'principled'},
                {'id': 'out', 'kind': 'output'},
                {'id': 'value_0_5', 'kind': 'value', 'properties': {'value': 0.5}},
            ],
            'links': [
                {'from': {'node': 'original', 'socket': 'value'},
                 'to': {'node': 'shader', 'socket': 'roughness'}},
                {'from': {'node': 'value_0_5', 'socket': 'value'},
                 'to': {'node': 'shader', 'socket': 'metallic'}},
                {'from': {'node': 'shader', 'socket': 'shader'},
                 'to': {'node': 'out', 'socket': 'surface'}},
            ],
        }
        document = {'version': 'schemaxis.blender.production/1', 'id': 'nestedRows',
                    'prepareOnly': True, 'size': [32, 32], 'render': {'samples': 1, 'threads': 1},
                    'cameras': [{'direction': [1, -2, 1]}],
                    'production': {'materialGraphs': [graph], 'objects': [
                        {'id': 'panel', 'kind': 'mesh', 'material': 'paint',
                         'vertices': [[0, 0, 0], [1, 0, 0], [0, 1, 0]], 'faces': [[0, 1, 2]]},
                    ]}}
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'scene'
            run_blender(document, directory, timeout=120)
            # The verifier compares the reopened graph's nodes, socket values and links.
            self.assertTrue(verify_blender(directory)['verified'])
