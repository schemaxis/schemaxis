import hashlib
import itertools
import json
import math
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from schemaxis.core.faults import SchemaxisError
from schemaxis.job import plan, identities, schedule, verify_receipt
from schemaxis.adaptors.paraview.publication import Renderer, default_distance

VIEW_ANGLE = 30.0
CUBE = [-1, 1, -1, 1, -1, 1]
BAR = [0, 10, 0, 1, 0, 1]
SIZES = ([640, 480], [480, 480], [480, 640], [360, 640], [1080, 1920], [100, 1000])
DIRECTIONS = ([1, -1, 1], [1, 0, 0], [0, 0, 1], [0.3, 1, -0.2])


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def projected(bounds, size, direction, up, distance, angle=VIEW_ANGLE):
    """Worst |ndc| (x, y) of the bounds corners seen by a pinhole camera with a vertical view angle."""
    focal = [(bounds[i] + bounds[i + 1]) / 2 for i in (0, 2, 4)]
    towards = unit(direction)
    position = [focal[i] + towards[i] * distance for i in range(3)]
    forward = [-v for v in towards]
    right = unit(cross(forward, up))
    true_up = cross(right, forward)
    tan_v = math.tan(math.radians(angle / 2))
    tan_h = tan_v * size[0] / size[1]
    worst = [0.0, 0.0]
    for corner in itertools.product(bounds[0:2], bounds[2:4], bounds[4:6]):
        offset = [corner[i] - position[i] for i in range(3)]
        depth = sum(a * b for a, b in zip(offset, forward))
        assert depth > 0
        worst[0] = max(worst[0], abs(sum(a * b for a, b in zip(offset, right))) / (depth * tan_h))
        worst[1] = max(worst[1], abs(sum(a * b for a, b in zip(offset, true_up))) / (depth * tan_v))
    return worst


def diagonal(bounds):
    return math.sqrt(sum((bounds[i + 1] - bounds[i]) ** 2 for i in (0, 2, 4)))


class DefaultDistanceTests(unittest.TestCase):
    def test_landscape_square_and_parallel_keep_the_historical_distance(self):
        for size in ([640, 480], [480, 480], [1920, 1080], [4000, 100]):
            self.assertEqual(default_distance(10.0, size, False), 20.0)
        for size in SIZES:
            self.assertEqual(default_distance(10.0, size, True), 20.0)

    def test_portrait_distance_scales_by_the_height_to_width_ratio(self):
        self.assertAlmostEqual(default_distance(10.0, [480, 640], False), 20.0 * 640 / 480)
        self.assertAlmostEqual(default_distance(10.0, [1080, 1920], False), 20.0 * 1920 / 1080)

    def test_old_distance_crops_portrait_and_the_new_distance_does_not(self):
        up = [0, 0, 1]
        for bounds, size, direction in itertools.product((CUBE, BAR), SIZES, DIRECTIONS):
            old = projected(bounds, size, direction, up if direction[2] != 1 else [0, 1, 0], diagonal(bounds) * 2)
            new = projected(bounds, size, direction, up if direction[2] != 1 else [0, 1, 0],
                            default_distance(diagonal(bounds), size, False))
            with self.subTest(bounds=bounds, size=size, direction=direction):
                self.assertLessEqual(max(new), 1.0)
                if size[0] >= size[1]:
                    self.assertEqual(new, old)
                else:
                    self.assertLess(new[0], old[0])
        crop = projected(CUBE, [1080, 1920], [1, -1, 1], [0, 0, 1], diagonal(CUBE) * 2)
        self.assertGreater(crop[0], 1.4)

    def test_portrait_visible_width_matches_the_landscape_default_height_for_any_view_angle(self):
        landscape_height = default_distance(10.0, [640, 480], False)
        for angle in (10.0, 30.0, 60.0):
            tan_v = math.tan(math.radians(angle / 2))
            for size in ([480, 640], [200, 1000], [1080, 1920]):
                tan_h = tan_v * size[0] / size[1]
                self.assertAlmostEqual(default_distance(10.0, size, False) * tan_h, landscape_height * tan_v, places=9)


class FrameTests(unittest.TestCase):
    def renderer(self):
        renderer = Renderer.__new__(Renderer)
        renderer.view = SimpleNamespace()
        renderer.pv = SimpleNamespace(Render=lambda view: None)
        return renderer

    def position_distance(self, camera, size):
        renderer = self.renderer()
        focal, position = renderer.frame({'size': size}, camera, CUBE)
        self.assertEqual(renderer.view.CameraPosition, position)
        return math.dist(position, focal), renderer.view

    def test_default_perspective_camera_is_aspect_aware(self):
        camera = {'direction': [1, -1, 1], 'up': [0, 0, 1], 'parallel': False}
        base = diagonal(CUBE) * 2
        self.assertAlmostEqual(self.position_distance(camera, [640, 480])[0], base)
        self.assertAlmostEqual(self.position_distance(camera, [480, 480])[0], base)
        self.assertAlmostEqual(self.position_distance(camera, [360, 640])[0], base * 640 / 360)

    def test_explicit_distance_and_parallel_settings_are_preserved(self):
        explicit = {'direction': [1, -1, 1], 'up': [0, 0, 1], 'parallel': False, 'distance': 9.0}
        self.assertAlmostEqual(self.position_distance(explicit, [360, 640])[0], 9.0)
        parallel = {'direction': [1, -1, 1], 'up': [0, 0, 1], 'parallel': True}
        distance, view = self.position_distance(parallel, [360, 640])
        self.assertAlmostEqual(distance, diagonal(CUBE) * 2)
        self.assertAlmostEqual(view.CameraParallelScale, diagonal(CUBE) * 0.5 * 1.1 * 640 / 360)
        self.assertEqual(view.CameraParallelProjection, 1)

    def test_perspective_padding_and_explicit_scale_do_not_change_distance(self):
        # Padding and scale frame the parallel scale only; the perspective default never used them.
        camera = {'direction': [1, 0, 0], 'up': [0, 0, 1], 'parallel': False}
        plain = self.position_distance(camera, [360, 640])[0]
        self.assertEqual(self.position_distance({**camera, 'padding': 0.5}, [360, 640])[0], plain)
        self.assertEqual(self.position_distance({**camera, 'scale': 3.0}, [360, 640])[0], plain)


def receipt_fixture(directory, camera, bounds, framing_version, distance):
    value = {'version': 'schemaxis/1', 'times': [2],
             'nodes': [{'id': 's', 'filter': 'sphere'}],
             'scenes': [{'id': 's', 'visible': {'s': {}},
                         'images': [{'id': 'view', 'size': [360, 640], 'cameras': [camera]}]}]}
    master, scenes, _ = plan(value)
    scene, visit = next(schedule(master, scenes))
    expected = next(identities(scene, visit))
    path = directory / 'image.png'
    path.write_bytes(b'host receipt fixture; native pixels tested separately')
    focal = [(bounds[i] + bounds[i + 1]) / 2 for i in (0, 2, 4)]
    artifact = {'file': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'verified': True, 'identity': expected, 'viewTime': 2,
                'effectiveAppearance': scene['appearances'][0],
                'effectiveCamera': scene['images'][0]['cameras'][0],
                'camera': {'position': [focal[0] + distance, focal[1], focal[2]], 'focalPoint': focal}}
    receipt = {'status': 'succeeded', 'verified': True, 'renderTimeVersion': 1,
               'planDigest': master.to_dict()['digest'], 'planVersion': master.to_dict()['version'],
               'states': [{'scene': 's', 'visit': visit, 'proxyIds': {'s': '1'},
                           'effective': {'s': master.nodes['s']['options']},
                           'observations': {'s': {'bounds': bounds, 'points': 8}}, 'updated': ['s']}],
               'events': [{'event': 'create', 'node': 's'},
                          {'event': 'update', 'node': 's', 'time': 2},
                          {'event': 'delete', 'node': 's'}], 'artifacts': [artifact]}
    if framing_version is not None:
        receipt['cameraFramingVersion'] = framing_version
    (directory / 'verification.json').write_text(json.dumps(receipt))
    return master, scenes, receipt, artifact


class ReceiptCompatibilityTests(unittest.TestCase):
    PERSPECTIVE = {'direction': [1, 0, 0], 'up': [0, 0, 1], 'parallel': False}

    def fault(self, code, action):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code)

    def test_new_receipts_bind_the_aspect_aware_default_distance(self):
        aspect_aware = default_distance(diagonal(CUBE), [360, 640], False)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            master, scenes, receipt, artifact = receipt_fixture(directory, self.PERSPECTIVE, CUBE, 1, aspect_aware)
            self.assertTrue(verify_receipt(directory, master, scenes)['verified'])
            artifact['camera']['position'][0] += 1
            (directory / 'verification.json').write_text(json.dumps(receipt))
            self.fault('VERIFICATION_FAILED', lambda: verify_receipt(directory, master, scenes))
            del artifact['camera']
            (directory / 'verification.json').write_text(json.dumps(receipt))
            self.fault('VERIFICATION_FAILED', lambda: verify_receipt(directory, master, scenes))

    def test_new_receipts_reject_the_cropping_historical_distance(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            master, scenes, *_ = receipt_fixture(directory, self.PERSPECTIVE, CUBE, 1, diagonal(CUBE) * 2)
            self.fault('VERIFICATION_FAILED', lambda: verify_receipt(directory, master, scenes))

    def test_retained_receipts_without_the_framing_version_still_verify(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            master, scenes, *_ = receipt_fixture(directory, self.PERSPECTIVE, CUBE, None, diagonal(CUBE) * 2)
            self.assertTrue(verify_receipt(directory, master, scenes)['verified'])

    def test_unknown_or_wrongly_typed_framing_markers_are_refused(self):
        for marker in ("1", 2, True, 1.0, None):
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                master, scenes, receipt, _ = receipt_fixture(directory, self.PERSPECTIVE, CUBE, 1,
                                                            default_distance(diagonal(CUBE), [360, 640], False))
                receipt['cameraFramingVersion'] = marker
                (directory / 'verification.json').write_text(json.dumps(receipt))
                self.fault('VERIFICATION_FAILED', lambda: verify_receipt(directory, master, scenes))

    def test_explicit_distance_is_not_checked_against_the_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            camera = {**self.PERSPECTIVE, 'distance': 9.0}
            master, scenes, *_ = receipt_fixture(directory, camera, CUBE, 1, 9.0)
            self.assertTrue(verify_receipt(directory, master, scenes)['verified'])


if __name__ == '__main__':
    unittest.main()
