"""Existing-video source type and length boundaries, checked without a native runtime."""
import os
from pathlib import Path
import stat
import tempfile
import unittest

from schemaxis.adaptors.ffmpeg import adaptor, video
from schemaxis.core.faults import SchemaxisError

EBML = bytes.fromhex('1a45dfa3') + b'\x9f' + bytes(32)
MP4 = b'\0\0\0\x18ftypisom\0\0\2\0isomiso2' + bytes(32)


def document(path, **options):
    return {'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'clip', 'filter': 'encodeVideo',
        'options': {'file': str(path), 'endFrame': 2, 'codec': 'ffv1', **options}}]}


def probe(count):
    return {'streams': [{'codec_type': 'video', 'codec_name': 'ffv1', 'pix_fmt': 'bgr0', 'width': 2,
                         'height': 2, 'avg_frame_rate': '10/1', 'r_frame_rate': '10/1'}],
            'format': {'format_name': 'matroska,webm'},
            'frames': [{'width': 2, 'height': 2, 'pix_fmt': 'bgr0', 'best_effort_timestamp_time': str(i / 10)}
                       for i in range(count)]}


class SourceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        # A native stand-in that records every launch and always fails. Boundary
        # faults must happen before it is ever started.
        self.launches = self.root / 'launches'
        self.stub = self.root / 'tools' / 'ffmpeg'; self.stub.parent.mkdir()
        self.stub.write_text(f'#!/bin/sh\necho started >> {self.launches}\necho "Invalid data" >&2\nexit 1\n')
        self.stub.chmod(self.stub.stat().st_mode | stat.S_IXUSR)
        (self.stub.parent / 'ffprobe').write_bytes(self.stub.read_bytes())
        (self.stub.parent / 'ffprobe').chmod(self.stub.stat().st_mode)

    def run_source(self, name, data):
        source = self.root / name; source.write_bytes(data)
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.run(document(source), self.root / ('out-' + name), executable=str(self.stub), timeout=20)
        return caught.exception.fault

    def test_unrecognised_or_empty_bytes_are_malformed_before_native_launch(self):
        for name, data in (('text.mkv', b'not a video\n'), ('empty.mkv', b''), ('png.mp4', b'\x89PNG\r\n\x1a\n' + bytes(64)),
                           ('short.mp4', b'\0\0\0\x18ft'), ('badsize.mp4', b'\0\0\0\3ftypisom' + bytes(32))):
            with self.subTest(name=name):
                fault = self.run_source(name, data)
                self.assertEqual(fault.code, 'INVALID_RESOURCE')
                self.assertEqual(fault.location, '$.nodes[0].options.file')
                self.assertIsNone(fault.observed['detected'])
                self.assertIn('Matroska', fault.recovery)
        self.assertFalse(self.launches.exists())

    def test_known_container_under_other_extension_is_unsupported_not_malformed(self):
        for name, data, declared, detected in (('mkv-bytes.mp4', EBML, 'mp4', 'matroska'),
                                               ('mp4-bytes.mkv', MP4, 'matroska', 'mp4')):
            with self.subTest(name=name):
                fault = self.run_source(name, data)
                self.assertEqual(fault.code, 'UNSUPPORTED_VIDEO')
                self.assertEqual((fault.observed['declared'], fault.observed['detected']), (declared, detected))
                self.assertTrue(fault.recovery)
        self.assertFalse(self.launches.exists())

    def test_matching_containers_reach_native_and_native_failure_stays_distinct(self):
        for name, data in (('ok.mkv', EBML), ('ok.mp4', MP4), ('moov-first.mp4', b'\0\0\0\x10moov' + bytes(32)),
                           ('upper.MKV', EBML)):
            with self.subTest(name=name):
                self.launches.unlink(missing_ok=True)
                fault = self.run_source(name, data)
                self.assertEqual(fault.code, 'RUNNER_FAILED')
                self.assertTrue(self.launches.exists(), 'valid signature must proceed to native probing')

    def test_container_detection_is_exact(self):
        self.assertEqual(video.container_signature(EBML), 'matroska')
        self.assertEqual(video.container_signature(MP4), 'mp4')
        self.assertEqual(video.container_signature(b'\0\0\0\1ftyp' + bytes(8)), 'mp4')
        self.assertEqual(video.container_signature(b'\0\0\0\0mdat' + bytes(8)), 'mp4')
        for data in (b'', EBML[:3], b'\x1a\x45\xdf\xa4' + bytes(16), b'\0\0\0\x18abcd' + bytes(16), b'\0\0\0\2ftyp'):
            self.assertIsNone(video.container_signature(data))

    def test_over_long_source_is_a_resource_limit_with_recovery(self):
        self.assertEqual(video.inspect(probe(600))[2], 600)
        for count in (601, 602):
            with self.assertRaises(SchemaxisError) as caught:
                video.inspect(probe(count))
            fault = caught.exception.fault
            self.assertEqual(fault.code, 'RESOURCE_LIMIT')
            self.assertEqual(fault.location, '$.nodes[0].options.file')
            self.assertEqual(fault.observed['maximumFrames'], 600)
            self.assertIn('600', fault.recovery)

    def test_zero_frame_source_is_still_unsupported(self):
        with self.assertRaises(SchemaxisError) as caught:
            video.inspect(probe(0))
        self.assertEqual(caught.exception.fault.code, 'UNSUPPORTED_VIDEO')


if __name__ == '__main__':
    unittest.main()
