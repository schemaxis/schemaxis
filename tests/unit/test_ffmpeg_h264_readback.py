"""H.264 colour declaration and damaged-source diagnostics, checked without a native runtime."""
import json
from pathlib import Path
import stat
import struct
import sys
import tempfile
from contextlib import contextmanager
import unittest
from unittest.mock import patch
import zlib

from schemaxis.adaptors.ffmpeg import adaptor, fresh, video
from schemaxis.core.faults import SchemaxisError

EBML = bytes.fromhex('1a45dfa3') + b'\x9f' + bytes(32)


def png(width, height, colour):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    raw = b''.join(b'\0' + bytes(colour) * width for _ in range(height))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def prepared(codec):
    return adaptor.plan({'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'movie', 'filter': 'encodeFrames',
        'options': {'files': ['/a.png'], 'codec': codec, 'fps': 25}}]})


def probe(codec='h264', **stream):
    return {'streams': [{'codec_type': 'video', 'codec_name': codec,
        'pix_fmt': 'yuv420p' if codec == 'h264' else 'bgr0', 'width': 4, 'height': 2,
        'nb_read_frames': '1', 'avg_frame_rate': '25/1', **stream}], 'format': {'duration': '0.04'}}


@contextmanager
def retained_only():
    """These tests use a synthetic native stand-in, so they exercise the retained consistency pass alone. The fresh native
    decision (trusted runtime, private decode, forgeries) is covered natively by test_ffmpeg_fresh."""
    stub = {'frames': 1, 'fps': 25, 'runtime': 'ffmpeg version stub', 'errors': [0.0], 'duration': 0.04}
    with patch.object(fresh, 'trusted', return_value={'ffmpeg': '/native/ffmpeg', 'ffprobe': '/native/ffprobe'}), \
            patch.object(fresh, 'observe', return_value=stub), patch.object(fresh, 'bind'):
        yield


class ColourDeclarationTests(unittest.TestCase):
    def fault(self, action, code='VERIFICATION_FAILED'):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code)
        return caught.exception.fault

    def test_h264_encode_declares_bt601_limited_range_before_the_output(self):
        encode = adaptor.native_commands('/native/ffmpeg', Path('/out'), prepared('h264'), 4, 2)['encode']
        index = encode.index('-colorspace')
        self.assertEqual(encode[index:index + 4], ['-colorspace', 'smpte170m', '-color_range', 'tv'])
        self.assertLess(index, encode.index('-movflags'))
        self.assertEqual(encode[-1], '/out/video.mp4')
        self.assertEqual(encode[encode.index('-pix_fmt') + 1], 'yuv420p')

    def test_ffv1_encode_is_unchanged(self):
        encode = adaptor.native_commands('/native/ffmpeg', Path('/out'), prepared('ffv1'), 4, 2)['encode']
        self.assertNotIn('-colorspace', encode)
        self.assertEqual(encode[-7:], ['-c:v', 'ffv1', '-level', '1', '-pix_fmt', 'bgr0', '/out/video.mkv'])

    def test_probe_must_report_the_declared_matrix_and_range(self):
        options = prepared('h264')['nodes'][0]['options']
        adaptor.validate_probe(probe(color_space='smpte170m', color_range='tv'), 4, 2, 1, options)
        for stream in ({}, {'color_space': 'smpte170m'}, {'color_range': 'tv'},
                       {'color_space': 'bt709', 'color_range': 'tv'},
                       {'color_space': 'smpte170m', 'color_range': 'pc'}):
            with self.subTest(stream=stream):
                self.assertIn('BT.601', self.fault(lambda: adaptor.validate_probe(
                    probe(**stream), 4, 2, 1, options)).message)

    def test_retained_untagged_h264_and_ffv1_probes_stay_verifiable(self):
        h264 = prepared('h264')['nodes'][0]['options']
        adaptor.validate_probe(probe(), 4, 2, 1, h264, tagged=False)
        adaptor.validate_probe(probe('ffv1'), 4, 2, 1, prepared('ffv1')['nodes'][0]['options'])

    def fake_run(self, root, tagged=True, stream=None):
        source = root / 'a.png'; source.write_bytes(png(4, 2, (40, 120, 200, 255)))
        document = {'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'movie', 'filter': 'encodeFrames',
            'options': {'files': [str(source)], 'codec': 'h264', 'fps': 25}}]}
        output = root / 'run'
        colours = {'color_space': 'smpte170m', 'color_range': 'tv'} if tagged else {}

        def execute(command, directory, stage, timeout):
            from schemaxis.artifacts import atomic_json
            if stage == 'encode' and not tagged:
                index = command.index('-colorspace'); command = command[:index] + command[index + 4:]
            atomic_json(directory / (stage + '-submission.json'), {'exitCode': 0, 'nativeCommand': command,
                'interpreter': {'executable': command[0]}})
            if stage in ('decode', 'probe'):
                atomic_json(directory / (stage + '-inputs.json'), {str(directory / 'video.mp4'):
                    adaptor.file_digest(directory / 'video.mp4')})
            if stage == 'encode': (directory / 'video.mp4').write_bytes(b'synthetic video fixture')
            elif stage == 'decode': (directory / 'decoded.rgb').write_bytes((directory / 'frames.rgb').read_bytes())
            elif stage == 'version': (directory / 'version.stdout').write_text('ffmpeg fixture\n')
            elif stage == 'probe': atomic_json(directory / 'probe.stdout', probe(**(stream or colours)))
        with patch.object(adaptor, 'execute', side_effect=execute), patch('os.access', return_value=True):
            adaptor.run(document, output, executable='/native/ffmpeg')
        return output

    def test_complete_run_verifies_only_with_the_declared_colour(self):
        with tempfile.TemporaryDirectory() as temporary, retained_only():
            self.assertTrue(adaptor.verify(self.fake_run(Path(temporary)))['verified'])
        with tempfile.TemporaryDirectory() as temporary, retained_only():
            # A native run whose output ignores the declaration is not accepted.
            fault = self.fault(lambda: self.fake_run(Path(temporary), stream={'color_space': 'bt709', 'color_range': 'tv'}))
            self.assertIn('BT.601', fault.message)

    def test_exact_untagged_recipe_from_retained_runs_remains_verifiable(self):
        with tempfile.TemporaryDirectory() as temporary, retained_only():
            output = self.fake_legacy_run(Path(temporary))
            self.assertTrue(adaptor.verify(output)['verified'])
            # The untagged exception is exact: any other altered flag is rejected.
            path = output / 'encode-submission.json'; submission = json.loads(path.read_text())
            submission['nativeCommand'][submission['nativeCommand'].index('-crf') + 1] = '30'
            path.write_text(json.dumps(submission))
            self.fault(lambda: adaptor.verify(output))

    def fake_legacy_run(self, root):
        """A retained run: untagged recipe and probe, as written before explicit tagging."""
        original = adaptor.validate_probe
        with patch.object(adaptor, 'validate_probe', lambda *a, **k: original(*a, **{**k, 'tagged': False})):
            return self.fake_run(root, tagged=False)


class SourceDiagnosticsTests(unittest.TestCase):
    def fault(self, action, code):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code)
        return caught.exception.fault

    def test_clean_empty_diagnostics_are_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for stage in ('source-probe', 'source-decode'):
                (root / (stage + '.stderr')).write_text('\n')
                video.check_diagnostics(root, stage)

    def test_native_errors_make_a_damaged_source_invalid_with_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            text = f'[matroska,webm @ 0x1] File ended prematurely\n{root}/input-0000: partial file\n[h264 @ 0x2] ' + 'x' * 5000
            (root / 'source-decode.stderr').write_text(text)
            fault = self.fault(lambda: video.check_diagnostics(root, 'source-decode'), 'INVALID_RESOURCE')
            self.assertEqual(fault.location, '$.nodes[0].options.file')
            self.assertEqual(fault.observed['stage'], 'source-decode')
            self.assertIn('File ended prematurely', fault.observed['diagnostics'])
            self.assertIn('<run>/input-0000', fault.observed['diagnostics'])
            self.assertNotIn(str(root), fault.observed['diagnostics'])
            self.assertLessEqual(len(fault.observed['diagnostics']), video.MAX_DIAGNOSTIC)
            self.assertIn('truncated', fault.recovery)

    def test_missing_or_symlinked_diagnostics_are_not_assumed_clean(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fault(lambda: video.check_diagnostics(root, 'source-probe'), 'VERIFICATION_FAILED')
            (root / 'real').write_text('')
            (root / 'source-probe.stderr').symlink_to(root / 'real')
            self.fault(lambda: video.check_diagnostics(root, 'source-probe'), 'VERIFICATION_FAILED')


class DamagedSourceRunTests(unittest.TestCase):
    """A native stand-in that exits 0 yet reports damage must stop before frames are trusted."""
    PROBE = json.dumps({'streams': [{'codec_type': 'video', 'codec_name': 'ffv1', 'pix_fmt': 'bgr0', 'width': 2,
                                     'height': 2, 'avg_frame_rate': '10/1', 'r_frame_rate': '10/1'}],
                        'format': {'format_name': 'matroska,webm'},
                        'frames': [{'width': 2, 'height': 2, 'pix_fmt': 'bgr0',
                                    'best_effort_timestamp_time': str(i / 10)} for i in range(3)]})

    def stub(self, root, probe_error, decode_error):
        tools = root / 'tools'; tools.mkdir()
        log = root / 'launches'
        probe = tools / 'ffprobe'
        probe.write_text(f"#!/bin/sh\necho probe >> {log}\ncat <<'EOF'\n{self.PROBE}\nEOF\n"
                         + (f'echo "{probe_error}" >&2\n' if probe_error else ''))
        ffmpeg = tools / 'ffmpeg'
        ffmpeg.write_text(f'#!{sys.executable}\nimport sys\nfrom pathlib import Path\n'
                          + f'with Path({str(log)!r}).open("a") as stream: stream.write(" ".join(sys.argv[1:])+"\\n")\n'
                          + 'if sys.argv[-1].endswith("source-decoded.rgb"): Path(sys.argv[-1]).write_bytes(bytes(36))\n'
                          + f'print({decode_error!r}, file=sys.stderr) if {bool(decode_error)!r} else None\n')
        for path in (probe, ffmpeg): path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return ffmpeg, log

    def run_source(self, probe_error='', decode_error=''):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name); source = root / 'clip.mkv'; source.write_bytes(EBML)
        ffmpeg, log = self.stub(root, probe_error, decode_error)
        document = {'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'clip', 'filter': 'encodeVideo',
            'options': {'file': str(source), 'endFrame': 2, 'codec': 'ffv1'}}]}
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.run(document, root / 'out', executable=str(ffmpeg), timeout=20)
        return caught.exception.fault, log.read_text()

    def test_probe_diagnostics_stop_before_decoding(self):
        fault, launches = self.run_source(probe_error='[matroska,webm @ 0x1] File ended prematurely')
        self.assertEqual((fault.code, fault.observed['stage']), ('INVALID_RESOURCE', 'source-probe'))
        self.assertEqual(launches.strip(), 'probe')

    def test_launcher_or_loader_diagnostics_are_not_a_source_fault(self):
        fault, launches = self.run_source(probe_error="ERROR: ld.so: object missing.so cannot be preloaded: ignored")
        self.assertEqual((fault.code, fault.observed['stage']), ('RUNNER_FAILED', 'source-probe'))
        self.assertEqual(launches.strip(), 'probe')

    def test_decode_diagnostics_stop_before_encoding(self):
        fault, launches = self.run_source(decode_error='[h264 @ 0x1] Invalid NAL unit size')
        self.assertEqual((fault.code, fault.observed['stage']), ('INVALID_RESOURCE', 'source-decode'))
        self.assertEqual(len(launches.splitlines()), 2, 'only the source probe and decode were launched')
        self.assertNotIn('libx264', launches)
        self.assertNotIn('ffv1', launches)


if __name__ == '__main__':
    unittest.main()
