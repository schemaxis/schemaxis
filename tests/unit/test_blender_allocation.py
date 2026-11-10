"""Host-only Blender handoff and input-provenance boundaries (no native Blender)."""
import tempfile
import unittest
from pathlib import Path

from schemaxis.adaptors.blender.integration import reusableInputs, validateHandoff
from schemaxis.core.faults import SchemaxisError

RENDER = {'version': 'schemaxis.blender.render/1', 'sceneFile': '/scene.blend',
          'cameras': [{'direction': [1, 1, 1]}]}
IMAGE_CONSUMER = {'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'movie', 'filter': 'encodeFrames',
                  'options': {'files': ['/frame.png'], 'codec': 'ffv1', 'fps': 25}}]}


def scene_producer(**scene):
    return {'version': 'schemaxis.blender/1', 'scenes': [{'id': 'main', **scene}]}


class HandoffTests(unittest.TestCase):
    def test_render_job_publishes_images_not_scenes(self):
        with self.assertRaises(SchemaxisError) as caught:
            validateHandoff(RENDER, RENDER, 'again')
        fault = caught.exception.fault
        self.assertEqual((fault.code, fault.location), ('UNSUPPORTED_HANDOFF', 'again'))
        self.assertIn('images', fault.message)
        self.assertTrue(fault.recovery)

    def test_prepare_only_scene_publishes_no_images(self):
        with self.assertRaises(SchemaxisError) as caught:
            validateHandoff(scene_producer(prepareOnly=True), IMAGE_CONSUMER, 'movie')
        self.assertEqual(caught.exception.fault.code, 'UNSUPPORTED_HANDOFF')
        self.assertTrue(caught.exception.fault.recovery)

    def test_valid_handoffs_remain_accepted(self):
        validateHandoff(scene_producer(prepareOnly=True), RENDER, 'render')
        validateHandoff(scene_producer(), IMAGE_CONSUMER, 'movie')
        validateHandoff(RENDER, IMAGE_CONSUMER, 'movie')
        validateHandoff({'version': 'schemaxis.blender/1'}, IMAGE_CONSUMER, 'movie')
        validateHandoff({'version': 'schemaxis.blender/1', 'scenes': {'$artifact': 'x'}}, IMAGE_CONSUMER, 'movie')


class WorkflowPlanningTests(unittest.TestCase):
    def test_render_chain_is_rejected_before_any_native_run(self):
        from schemaxis import workflow
        document = {'version': 'schemaxis.workflow/1', 'operations': [
            {'id': 'first', 'document': RENDER},
            {'id': 'second', 'document': {**RENDER, 'sceneFile': {'$artifact': 'first', 'index': 0}}}]}
        with self.assertRaises(SchemaxisError) as caught:
            workflow.validate(document)
        self.assertEqual((caught.exception.fault.code, caught.exception.fault.location),
                         ('UNSUPPORTED_HANDOFF', 'second'))

    def test_shipped_blender_workflows_still_validate(self):
        import json
        from schemaxis import workflow
        root = Path(__file__).resolve().parents[2] / 'examples' / 'schemaxis'
        for name in ('blender-render-groups.json', 'blender-to-video.json'):
            with self.subTest(name):
                workflow.validate(json.loads((root / name).read_text()))


class InputProvenanceTests(unittest.TestCase):
    def render(self, scene):
        return {**RENDER, 'sceneFile': str(scene)}

    def test_missing_scene_is_a_structured_fault(self):
        with tempfile.TemporaryDirectory() as root:
            missing = Path(root) / 'missing.blend'
            with self.assertRaises(SchemaxisError) as caught:
                reusableInputs(self.render(missing))
        fault = caught.exception.fault
        self.assertEqual((fault.code, fault.location), ('RESOURCE_NOT_FOUND', str(missing)))
        self.assertTrue(fault.recovery)

    def test_directory_is_invalid_not_missing(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(SchemaxisError) as caught:
                reusableInputs(self.render(root))
        self.assertEqual(caught.exception.fault.code, 'INVALID_RESOURCE')

    def test_fifo_is_rejected_without_opening(self):
        import os
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'scene.blend'
            os.mkfifo(source)
            with patch('schemaxis.adaptors.blender.integration.file_digest') as digest:
                with self.assertRaises(SchemaxisError) as caught:
                    reusableInputs(self.render(source))
                digest.assert_not_called()
        self.assertEqual(caught.exception.fault.code, 'INVALID_RESOURCE')

    def test_existing_scene_is_hashed(self):
        with tempfile.TemporaryDirectory() as root:
            scene = Path(root) / 'a.blend'
            scene.write_bytes(b'BLENDER')
            hashes = reusableInputs(self.render(scene))
        self.assertEqual(list(hashes), [str(scene.absolute())])
        self.assertEqual(len(next(iter(hashes.values()))), 64)


if __name__ == '__main__':
    unittest.main()
