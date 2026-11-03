# Copyright (C) 2026 David L F Gaden
"""Existing-video contract tests; native qualification lives in its own tool."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

from schemaxis.adaptors.ffmpeg import adaptor, video
from schemaxis.core.faults import SchemaxisError


def document(**options):
    return {'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'clip', 'filter': 'encodeVideo',
        'options': {'file': '/input/source.mkv', 'startFrame': 1, 'endFrame': 4, 'codec': 'ffv1', **options}}]}


def probe():
    return {'streams': [{'codec_type': 'video', 'codec_name': 'ffv1', 'pix_fmt': 'bgr0',
        'width': 2, 'height': 1, 'avg_frame_rate': '10/1', 'r_frame_rate': '10/1', 'sample_aspect_ratio': '1:1'}],
        'format': {'format_name': 'matroska,webm'},
        'frames': [{'width': 2, 'height': 1, 'pix_fmt': 'bgr0', 'best_effort_timestamp_time': str(index / 10)}
                   for index in range(5)]}


class VideoInputTests(unittest.TestCase):
    def fault(self, action, code):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code)

    def test_default_range_and_immutable_plan(self):
        authored = document(); original = copy.deepcopy(authored)
        planned = adaptor.plan(authored)
        self.assertEqual(authored, original)
        self.assertEqual(planned['nodes'][0]['options']['fps'], 25)
        self.assertEqual(adaptor.plan(document(startFrame=0))['nodes'][0]['options']['startFrame'], 0)
        self.assertEqual(video.source_paths(planned['nodes'][0]), ['/input/source.mkv'])

    def test_reject_invalid_ranges_extensions_paths_and_options(self):
        for options, code in (({'startFrame': 4}, 'INVALID_FRAME_RANGE'),
                              ({'startFrame': -1}, 'INVALID_ARGUMENT'),
                              ({'endFrame': 601}, 'INVALID_ARGUMENT'),
                              ({'endFrame': True}, 'INVALID_ARGUMENT'),
                              ({'file': '/input/list.m3u8'}, 'UNSUPPORTED_VIDEO'),
                              ({'file': 'source.mp4'}, 'INVALID_RESOURCE'),
                              ({'vf': 'scale=2:2'}, 'UNKNOWN_ARGUMENT')):
            with self.subTest(options=options):
                self.fault(lambda: adaptor.plan(document(**options)), code)

    def test_schema_typed_video_fields_and_unknown_options(self):
        import jsonschema
        validator = jsonschema.Draft202012Validator(adaptor.schema())
        self.assertTrue(validator.is_valid(document()))
        self.assertFalse(validator.is_valid(document(endFrame=True)))
        self.assertFalse(validator.is_valid(document(startFrame=-1)))
        authored = document(); del authored['nodes'][0]['options']['endFrame']
        self.assertFalse(validator.is_valid(authored))
        self.assertFalse(validator.is_valid(document(command='arbitrary')))

    def test_uniform_source_required_before_any_selection(self):
        self.assertEqual(video.inspect(probe()), (2, 1, 5, 10))
        candidates = []
        item = probe(); item['streams'].append({'codec_type': 'audio'}); candidates.append(item)
        for key, value in (('sample_aspect_ratio', '2:1'), ('side_data_list', [{'rotation': 90}]),
                           ('field_order', 'tt'), ('avg_frame_rate', '30000/1001'), ('codec_name', 'vp9'), ('tags', None)):
            item = probe(); item['streams'][0][key] = value; candidates.append(item)
        # Even an unselected last frame invalidates variable cadence/shape.
        item = probe(); item['frames'][-1]['best_effort_timestamp_time'] = '.46'; candidates.append(item)
        item = probe(); item['frames'][0]['best_effort_timestamp_time'] = '.1'; candidates.append(item)
        item = probe(); item['frames'][-1]['width'] = 3; candidates.append(item)
        for item in candidates:
            self.fault(lambda: video.inspect(item), 'UNSUPPORTED_VIDEO')

    def test_exact_exclusive_frame_slice_and_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'source-probe.stdout').write_text(json.dumps(probe()))
            raw = bytes(range(30)); (root / 'source-decoded.rgb').write_bytes(raw)
            width, height, frames = video.read(root, adaptor.plan(document()))
            self.assertEqual((width, height), (2, 1))
            self.assertEqual(frames, [raw[6:12], raw[12:18], raw[18:24]])
            self.fault(lambda: video.read(root, adaptor.plan(document(endFrame=6))), 'INVALID_FRAME_RANGE')
            (root / 'source-decoded.rgb').write_bytes(raw + b'extra')
            self.fault(lambda: video.read(root, adaptor.plan(document())), 'VERIFICATION_FAILED')

    def test_capture_fingerprint_changes_and_unsafe_source_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'source.mkv'; source.write_bytes(b'first')
            authored = document(file=str(source))
            first = adaptor.reusableInputs(authored)
            source.write_bytes(b'changed')
            self.assertNotEqual(first, adaptor.reusableInputs(authored))
            self.fault(lambda: adaptor.reusableInputs(document(file='/dev/null.mp4')), 'RESOURCE_NOT_FOUND')

    def test_nonregular_and_oversized_sources_fail_before_open(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'source.mkv'
            os.mkfifo(source)
            self.fault(lambda: adaptor.reusableInputs(document(file=str(source))), 'INVALID_RESOURCE')
            source.unlink()
            with source.open('wb') as stream:
                stream.truncate(33 * 1024 * 1024)
            self.fault(lambda: adaptor.reusableInputs(document(file=str(source))), 'RESOURCE_LIMIT')

    def test_source_commands_are_fixed_and_local(self):
        commands = video.commands('/tools/ffmpeg', Path('/out'), adaptor.plan(document(file='/in/input.mp4')))
        self.assertIn('-noautorotate', commands['source-decode'])
        self.assertEqual(commands['source-probe'][commands['source-probe'].index('-threads')+1], '1')
        self.assertNotIn('-ignore_editlist', commands['source-probe'])
        self.assertIn('file', commands['source-decode'])
        self.assertNotIn('/in/input.mp4', commands['source-decode'])
        self.assertEqual(commands['source-decode'][-1], '/out/source-decoded.rgb')


if __name__ == '__main__':
    unittest.main()
