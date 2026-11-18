"""Observed values in scene camera settings: accepted, scheduled after what they read, and never a sweep."""
import unittest

from schemaxis.adaptors.blender.adaptor import plan as blender_plan
from schemaxis.adaptors.paraview.job import plan
from schemaxis.adaptors.paraview.publication import camera_values
from schemaxis.core.faults import SchemaxisError
from schemaxis.pipeline import evaluate

BODY = [0, 4.5, -0.9, 0.9, 0.2, 1.4]
WHEELS = [0.5, 3.6, -1, 1, 0, 0.7]


def expression(text):
    return {'$expr': text}


def document(camera, **definitions):
    return {'version': 'schemaxis/1', 'nodes': [
        {'id': 'bodySurface', 'filter': 'sphere'}, {'id': 'wheelSurface', 'filter': 'sphere'},
        {'id': 'shown', 'filter': 'sphere', 'options': {'radius': {'$sweep': 't'}}}],
        'settings': {'zoom': 0.52},
        'definitions': {'car': expression('union(extents(bodySurface), extents(wheelSurface))'), **definitions},
        'sweeps': [{'name': 't', 'values': [0.5, 1, 1.5]}, {'name': 'unused', 'values': [1, 2]}],
        'scenes': [{'id': 'view', 'visible': {'shown': {}}, 'images': [{'id': 'image', 'cameras': [camera]}]}]}


class ParaViewCameras(unittest.TestCase):
    def planned(self, camera, **definitions):
        master, scenes, _ = plan(document(camera, **definitions))
        return master, scenes[0]

    def effective(self, master, scene, axes):
        observations = {'bodySurface': {'extents': [BODY]}, 'wheelSurface': {'extents': [WHEELS]}}
        camera = scene['images'][0]['cameras'][0]
        return camera_values(evaluate(camera, axes, observations, 0.0, 'view', None, master.scope), 'image')

    def refused(self, camera, **definitions):
        with self.assertRaises(SchemaxisError) as caught:
            self.planned(camera, **definitions)
        return caught.exception.fault

    def test_a_camera_framing_an_observed_box_waits_for_the_nodes_it_reads(self):
        master, scene = self.planned({'bounds': expression('car.inflate(zoom)'), 'direction': [1, 0, 0]})
        self.assertEqual(scene['selection']['order'], ['bodySurface', 'wheelSurface', 'shown'])
        camera = self.effective(master, scene, {'t': 0.5})
        for actual, expected in zip(camera['bounds'], [-1.17, 5.67, -1.52, 1.52, -0.364, 1.764]):
            self.assertAlmostEqual(actual, expected, places=12)

    def test_a_scene_value_may_read_an_active_axis_and_observed_data_together(self):
        master, scene = self.planned({'distance': expression('t + extents(bodySurface).max.x')})
        self.assertEqual(scene['selection']['sweepsFastestFirst'], ['t'])
        self.assertEqual([self.effective(master, scene, {'t': value})['distance'] for value in (0.5, 1, 1.5)],
                         [5.0, 5.5, 6.0])
        fault = self.refused({'distance': expression('unused + 1')})
        self.assertEqual((fault.code, fault.observed['axis']), ('PRESENTATION_SWEEP_UNAVAILABLE', 'unused'))

    def test_a_whole_camera_may_come_from_a_catalogue_function_of_observed_data(self):
        master, scene = self.planned(expression("fitCamera(bounds = car.inflate(zoom), direction = 'x+')"))
        self.assertEqual(scene['selection']['order'], ['bodySurface', 'wheelSurface', 'shown'])
        camera = self.effective(master, scene, {'t': 0.5})
        self.assertEqual((camera['direction'], camera['up']), ([1, 0, 0], [0, 0, 1]))
        for actual, expected in zip(camera['focalPoint'], [2.25, 0, 0.7]):
            self.assertAlmostEqual(actual, expected, places=12)
        self.assertAlmostEqual(camera['distance'], 15.563493695182968, places=9)
        self.assertAlmostEqual(camera['scale'], 1.2236, places=4)

    def test_a_sweep_is_refused_in_a_scene_directly_or_through_an_entry(self):
        for camera, definitions, variable in (
                ({'distance': expression('sweep(1, 2, 3)')}, {}, 'sweep(1, 2, 3)'),
                ({'distance': expression('swept + 1')}, {'swept': expression('sweep(1, 2, 3)')}, 'swept')):
            fault = self.refused(camera, **definitions)
            self.assertEqual((fault.code, fault.phase, fault.observed['variable']),
                             ('SWEEP_PLACEMENT', 'input', variable))
            self.assertIn('/scenes/0/images/0/cameras/0/distance', fault.observed['destination'])


class BlenderCameras(unittest.TestCase):
    def document(self, camera):
        return {'version': 'schemaxis.blender/1', 'nodes': [
            {'id': 'paint', 'filter': 'material'},
            {'id': 'block', 'filter': 'cube', 'inputs': {'material': 'paint'}},
            {'id': 'aside', 'filter': 'cube', 'inputs': {'material': 'paint'}, 'options': {'centre': [5, 0, 0]}}],
            'scenes': [{'id': 'view', 'visible': ['block'],
                        'images': [{'id': 'image', 'size': [64, 64], 'cameras': [camera]}]}]}

    def test_an_observed_camera_value_adds_the_node_it_reads_to_the_active_graph(self):
        _, selection, _ = blender_plan(self.document({'focalPoint': expression('extents(aside).mid')}))
        self.assertEqual(list(selection.order), ['paint', 'block', 'aside'])
        _, selection, _ = blender_plan(self.document({'focalPoint': [0, 0, 0]}))
        self.assertEqual(list(selection.order), ['paint', 'block'])

    def test_a_sweep_is_refused_in_a_blender_camera(self):
        with self.assertRaises(SchemaxisError) as caught:
            blender_plan(self.document({'distance': expression('sweep(1, 2, 3)')}))
        self.assertEqual(caught.exception.fault.code, 'SWEEP_PLACEMENT')


if __name__ == '__main__':
    unittest.main()
