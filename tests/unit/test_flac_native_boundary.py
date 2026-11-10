"""FLAC run/verify boundaries with a deterministic fake flac program (no libFLAC).

The fake codec stores the raw PCM after a correctly framed FLAC prefix (STREAMINFO, metadata, first frame header) and mimics
libFLAC's decode checks (MD5 mismatch and a smaller-than-claimed length are errors; a longer stream is not). It proves host
behaviour only: framing, comparison, receipts, trusted executables, lifecycle and standard hooks. Native acceptance is
tools/qualify_flac.py. Tests needing the real binary run only when SCHEMAXIS_FLAC is set and are reported skipped otherwise.
"""
import contextlib
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from schemaxis import configuration, workflow
from schemaxis.adaptors import registry
from schemaxis.adaptors.flac import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_flac import private_configuration   # noqa: E402
from test_flac_fakes import MARKER, build_flac, parse_fake, streaminfo, wav_bytes   # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'src'
TESTS = Path(__file__).resolve().parent
FIXTURES = ROOT / 'examples/schemaxis/fixtures/flac'
FAKE = '''#!{python}
import hashlib, sys
sys.path.insert(0, {tests!r})
from test_flac_fakes import build_flac, parse_fake
args = sys.argv[1:]
if args == ['--version']:
    print({version!r}); sys.exit(0)
{marker}
if '-d' in args:
    info, pcm = parse_fake(open(args[-1], 'rb').read())
    if hashlib.md5(pcm).hexdigest() != info['md5']:
        sys.stderr.write(args[-1] + ': ERROR, MD5 signature mismatch\\n'); sys.exit(1)
    if len(pcm) < info['totalSamples'] * info['channels'] * 2:
        sys.stderr.write('ERROR, decoded number of samples is smaller than the total number of samples set in the STREAMINFO\\n'); sys.exit(1)
    open(args[args.index('-o') + 1], 'wb').write(pcm + {extra})
else:
    channels = int([a for a in args if a.startswith('--channels=')][0].split('=')[1])
    rate = int([a for a in args if a.startswith('--sample-rate=')][0].split('=')[1])
    pcm = open(args[-1], 'rb').read()
    open(args[args.index('-o') + 1], 'wb').write({build})
'''


def program(directory, name, version='flac 1.5.0', marker='', extra='b""', build='build_flac(rate, channels, pcm)'):
    path = Path(directory) / name
    path.write_text(FAKE.format(python=sys.executable, tests=str(TESTS), version=version, marker=marker, extra=extra, build=build))
    path.chmod(0o700)
    return str(path)


def refresh(directory):
    """Make every ordinary hash agree with the (tampered) files, as a forging writer would."""
    directory = Path(directory)
    operation = json.loads((directory / 'plan.json').read_text())['operation']
    if operation == 'encodeLossless':
        atomic_json(directory / 'encode-inputs.json', {'source.pcm': adaptor.digest(directory, 'source.pcm')})
        atomic_json(directory / 'decode-inputs.json', {'audio.flac': adaptor.digest(directory, 'audio.flac')})
    else:
        atomic_json(directory / 'decode-inputs.json', {'captured.flac': adaptor.digest(directory, 'captured.flac')})
    rebind(directory)


def rebind(directory):
    """Rebind only the receipt's artifact and evidence digests to the files as they now are."""
    directory = Path(directory)
    operation = json.loads((directory / 'plan.json').read_text())['operation']
    receipt = adaptor.read_json(directory, 'verification.json')
    receipt['evidence'] = {n: adaptor.digest(directory, n) for n in sorted(receipt['evidence'])}
    receipt['artifacts'] = adaptor.publications(directory, operation)
    atomic_json(directory / 'verification.json', receipt)


class FakeNativeBoundary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.flac = program(self.root, 'flac')
        self.wav_data = (FIXTURES / 'stereo-16000.wav').read_bytes()
        self.pcm = self.wav_data[44:]
        self.wav = self.root / 'a.wav'
        self.wav.write_bytes(self.wav_data)
        self.source = self.root / 'a.flac'
        self.source.write_bytes(build_flac(16000, 2, self.pcm))
        self.encode = {'version': 'schemaxis.flac/1', 'operation': 'encodeLossless', 'source': str(self.wav)}
        self.decode = {'version': 'schemaxis.flac/1', 'operation': 'decodePCM16', 'source': str(self.source)}
        self.environment = {k: v for k, v in os.environ.items() if k not in ('SCHEMAXIS_FLAC', 'SCHEMAXIS_CONFIG')}
        (self.root / 'empty.json').write_text('{"version": 1, "locations": {}}')
        self.environment['SCHEMAXIS_CONFIG'] = str(self.root / 'empty.json')
        self.environment['PYTHONPATH'] = str(SRC)

    def fault(self, action, code):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    def publish(self, document, name='run', executable=None):
        directory = self.root / name
        return directory, adaptor.run(document, directory, executable=executable or self.flac, timeout=60)

    # ------------------------------------------------------------ happy paths
    def test_encode_publishes_two_artifacts_and_verifies_fresh(self):
        directory, result = self.publish(self.encode)
        self.assertTrue(result['verified'])
        self.assertEqual((result['operation'], result['audio'], result['pcmSha256']), ('encodeLossless', {'sampleRate': 16000, 'channels': 2, 'frames': 2049}, hashlib.sha256(self.pcm).hexdigest()))
        receipt = adaptor.read_json(directory, 'verification.json')
        self.assertEqual([(Path(a['file']).name, a['kind']) for a in receipt['artifacts']], [('audio.flac', 'file'), ('flac-summary.json', 'text')])
        summary = adaptor.read_json(directory, 'flac-summary.json')
        self.assertEqual((summary['audio']['frames'], summary['pcm']['bytes'], summary['pcm']['peakMin'], summary['pcm']['peakMax']), (2049, 8196, [-32768, -32767], [32766, 32767]))
        self.assertEqual(summary['pcm']['md5'], hashlib.md5(self.pcm).hexdigest())
        self.assertEqual(summary['flac']['streaminfo']['md5'], summary['pcm']['md5'])
        self.assertTrue(summary['readback']['exactPcm'])
        self.assertTrue(adaptor.verify(directory, executable=self.flac)['verified'])
        launcher = (directory / 'encode-launcher.py').read_text()
        self.assertIn("'-8', '-V', '-s', '-w', '--no-padding', '--no-seektable'", launcher)
        self.assertIn("'--channels=2', '--sample-rate=16000', '-o', 'audio.flac', 'source.pcm'", launcher)
        self.assertIn('{"LANG":"C","LC_ALL":"C"}', launcher)
        self.assertEqual((directory / 'source.pcm').read_bytes(), self.pcm)
        self.assertEqual((directory / 'captured.wav').read_bytes(), self.wav_data)

    def test_encode_drops_and_lists_wav_chunks(self):
        self.wav.write_bytes((FIXTURES / 'mono-8000.wav').read_bytes())
        directory, result = self.publish(self.encode)
        self.assertEqual(result['audio'], {'sampleRate': 8000, 'channels': 1, 'frames': 1001})
        self.assertEqual(adaptor.read_json(directory, 'flac-summary.json')['source']['droppedChunks'], ['LIST'])

    def test_decode_publishes_the_canonical_wav_and_verifies_fresh(self):
        directory, result = self.publish(self.decode)
        self.assertTrue(result['verified'])
        self.assertEqual(result['operation'], 'decodePCM16')
        self.assertEqual((directory / 'audio.wav').read_bytes(), self.wav_data)
        receipt = adaptor.read_json(directory, 'verification.json')
        self.assertEqual([(Path(a['file']).name, a['kind']) for a in receipt['artifacts']], [('audio.wav', 'file'), ('flac-summary.json', 'text')])
        summary = adaptor.read_json(directory, 'flac-summary.json')
        self.assertEqual((summary['wav']['bytes'], summary['source']['droppedMetadataBlocks'], summary['readback']['streaminfoMd5Matches']), (8240, ['VORBIS_COMMENT'], True))
        self.assertIn('does not certify', summary['verification'])
        self.assertTrue(adaptor.verify(directory, executable=self.flac)['verified'])
        decode_launcher = (directory / 'decode-launcher.py').read_text()
        self.assertIn("'-d', '-s', '-w', '--no-preserve-modtime', '--force-raw-format', '--endian=little', '--sign=signed', '-o', 'decoded.pcm', 'captured.flac'", decode_launcher)
        self.assertNotIn('decode-through-errors', decode_launcher)

    def test_decoded_wav_is_accepted_by_the_sox_reader_rules(self):
        directory, _ = self.publish(self.decode)
        from schemaxis.adaptors.sox import conform
        info = conform.info_of((directory / 'audio.wav').read_bytes(), 'VERIFICATION_FAILED', 'audio.wav')[0]
        self.assertEqual(info, {'rate': 16000, 'channels': 2, 'frames': 2049})

    # ------------------------------------------------------------ hostile files with every hash refreshed
    def test_changed_encoded_pcm_is_rejected_even_when_every_hash_is_refreshed(self):
        def body_changed(data):
            return data[:-1] + bytes([data[-1] ^ 1])

        def body_and_md5(data):
            changed = body_changed(data)
            start = changed.index(MARKER) + 4
            return changed[:26] + hashlib.md5(changed[start:]).digest() + changed[42:]

        def shorter(data):
            return data[:-4]

        def geometry(data):
            return build_flac(16000, 1, self.pcm[:4096])
        for label, change, message in (('body only', body_changed, 'do not decode natively'), ('body and md5', body_and_md5, 'MD5 differs from the captured PCM'),
                                       ('shorter', shorter, 'do not decode natively'), ('geometry', geometry, 'geometry or sample count differs')):
            with self.subTest(label):
                directory, _ = self.publish(self.encode, 'run-' + label.replace(' ', '-'))
                path = directory / 'audio.flac'
                path.write_bytes(change(path.read_bytes()))
                refresh(directory)
                fault = self.fault(lambda: adaptor.verify(directory, executable=self.flac), 'VERIFICATION_FAILED')
                self.assertIn(message, fault.message)

    def test_equivalent_re_encode_is_accepted_only_when_the_receipt_is_fully_rewritten(self):
        directory, _ = self.publish(self.encode)
        (directory / 'audio.flac').write_bytes(build_flac(16000, 2, self.pcm))      # identical bytes here: the host judges decoded PCM
        refresh(directory)
        self.assertTrue(adaptor.verify(directory, executable=self.flac)['verified'])

    def test_changed_published_wav_or_input_flac_is_rejected_after_refreshing_hashes(self):
        directory, _ = self.publish(self.decode)
        wav = (directory / 'audio.wav').read_bytes()
        for label, forged in (('sample', wav[:-1] + bytes([wav[-1] ^ 1])), ('truncated', wav[:-4]), ('header', wav[:20] + b'\x02' + wav[21:]), ('trailing', wav + b'\0\0')):
            (directory / 'audio.wav').write_bytes(forged)
            refresh(directory)
            self.fault(lambda: adaptor.verify(directory, executable=self.flac), 'VERIFICATION_FAILED')
        (directory / 'audio.wav').write_bytes(wav)
        refresh(directory)
        self.assertTrue(adaptor.verify(directory, executable=self.flac)['verified'])
        captured = (directory / 'captured.flac').read_bytes()
        adaptor_captures = adaptor.read_json(directory, 'captures.json')
        for label, forged in (('body', captured[:-1] + bytes([captured[-1] ^ 1])), ('md5', captured[:26] + bytes([captured[26] ^ 1]) + captured[27:]),
                              ('count', build_flac(16000, 2, self.pcm, total=2048, body=self.pcm))):
            (directory / 'captured.flac').write_bytes(forged)
            atomic_json(directory / 'captures.json', {**adaptor_captures, 'bytes': len(forged), 'sha256': adaptor.sha(forged)})
            refresh(directory)
            self.fault(lambda: adaptor.verify(directory, executable=self.flac), 'VERIFICATION_FAILED')
        (directory / 'captured.flac').write_bytes(captured)
        atomic_json(directory / 'captures.json', adaptor_captures)
        refresh(directory)
        self.assertTrue(adaptor.verify(directory, executable=self.flac)['verified'])

    def test_retained_input_that_no_longer_meets_admission_is_a_verification_failure(self):
        directory, _ = self.publish(self.encode)
        captured = (directory / 'captured.wav').read_bytes()
        forged = captured[:-1]
        (directory / 'captured.wav').write_bytes(forged)
        atomic_json(directory / 'captures.json', {'source': str(self.wav), 'bytes': len(forged), 'sha256': adaptor.sha(forged)})
        refresh(directory)
        fault = self.fault(lambda: adaptor.verify(directory, executable=self.flac), 'VERIFICATION_FAILED')
        self.assertEqual(fault.observed['cause']['code'], 'INVALID_FLAC_WAV')

    def test_retained_evidence_is_bound_without_refresh(self):
        directory, _ = self.publish(self.encode)
        saved = {p: p.read_bytes() for p in directory.rglob('*') if p.is_file()}
        for name, change in (('audio.flac', lambda b: b[:-1] + b'\x01'), ('flac-summary.json', lambda b: b.replace(b'"exactPcm": true', b'"exactPcm": false')),
                             ('captured.wav', lambda b: b[:-2] + b'\x01\x01'), ('source.pcm', lambda b: b[:-1] + b'\x01'), ('reopened.pcm', lambda b: b[:-1] + b'\x01'),
                             ('encode-launcher.py', lambda b: b.replace(b'-8', b'-1')), ('version.stdout', lambda b: b'flac 1.6.0\n'), ('encode.stderr', lambda b: b'noise'),
                             ('verification.json', lambda b: b.replace(b'"artifacts"', b'"artefacts"')), ('plan.json', lambda b: b.replace(b'encodeLossless', b'decodePCM16')),
                             ('encode-submission.json', lambda b: b.replace(b'"exitCode": 0', b'"exitCode": 1')), ('decode-inputs.json', lambda b: b.replace(b'0', b'1', 1)),
                             ('captures.json', lambda b: b.replace(b'"bytes": ', b'"bytes": 1')), ('result.json', lambda b: b.replace(b'"frames": 2049', b'"frames": 2050'))):
            try:
                path = directory / name
                path.write_bytes(change(path.read_bytes()))
                self.fault(lambda: adaptor.verify(directory, executable=self.flac), 'VERIFICATION_FAILED')
            finally:
                for path, data in saved.items():
                    path.write_bytes(data)
        receipt = adaptor.read_json(directory, 'verification.json')
        for label, mutate in (('membership', lambda r: r['artifacts'].pop()), ('evidence', lambda r: r['evidence'].pop('encode.stdout')),
                              ('extra', lambda r: r['evidence'].update({'unowned.json': '0' * 64})), ('runtime', lambda r: r['runtime'].update(flac='flac 9.9.9')),
                              ('executables', lambda r: r.update(executables={'flac': 'relative/flac'}))):
            try:
                changed = copy.deepcopy(receipt)
                mutate(changed)
                atomic_json(directory / 'verification.json', changed)
                self.fault(lambda: adaptor.verify(directory, executable=self.flac), 'VERIFICATION_FAILED')
            finally:
                atomic_json(directory / 'verification.json', receipt)
        self.assertTrue(adaptor.verify(directory, executable=self.flac)['verified'])

    def test_unreferenced_files_are_refused(self):
        directory, _ = self.publish(self.encode)
        (directory / 'stray.txt').write_text('x')
        fault = self.fault(lambda: adaptor.verify(directory, executable=self.flac), 'VERIFICATION_FAILED')
        self.assertIn('stray.txt', fault.message)
        (directory / 'stray.txt').unlink()
        (directory / 'link.flac').symlink_to(directory / 'audio.flac')
        self.fault(lambda: adaptor.verify(directory, executable=self.flac), 'VERIFICATION_FAILED')
        (directory / 'link.flac').unlink()
        self.assertTrue(adaptor.verify(directory, executable=self.flac)['verified'])

    # ------------------------------------------------------------ trusted flac only
    def test_verification_requires_the_trusted_flac_and_never_runs_a_receipt_path(self):
        marker = self.root / 'executed.marker'
        directory, _ = self.publish(self.encode)
        trap = program(self.root, 'trap-flac', marker='open(%r, "w").write("ran")' % str(marker))
        receipt = adaptor.read_json(directory, 'verification.json')
        receipt['executables']['flac'] = trap
        atomic_json(directory / 'verification.json', receipt)
        with private_configuration():
            fault = self.fault(lambda: adaptor.verify(directory), 'INTERPRETER_NOT_FOUND')
            self.assertEqual(fault.location, '$.runtime.flac')
            self.assertFalse(marker.exists())
            refresh(directory)    # the receipt names another executable, so the recomputed launchers differ
            self.fault(lambda: adaptor.verify(directory, executable=self.flac), 'VERIFICATION_FAILED')
            self.assertFalse(marker.exists())
        for bad in ('flac', str(self.root / 'missing'), str(self.wav)):
            self.fault(lambda: adaptor.verify(directory, executable=bad), 'INTERPRETER_NOT_FOUND')

    def test_unsupported_runtime_stops_before_encoding(self):
        old = program(self.root, 'old-flac', version='flac 1.4.3')
        self.fault(lambda: adaptor.run(self.encode, self.root / 'old', executable=old, timeout=30), 'UNSUPPORTED_RUNTIME')
        self.assertFalse((self.root / 'old/audio.flac').exists())
        self.assertFalse((self.root / 'old/encode-submission.json').exists())
        self.assertEqual(adaptor.read_json(self.root / 'old', 'result.json')['status'], 'failed')
        directory, _ = self.publish(self.decode)
        newer = program(self.root, 'newer-flac', version='flac 1.6.0')
        self.fault(lambda: adaptor.verify(directory, executable=newer), 'UNSUPPORTED_RUNTIME')

    def test_source_faults_stop_before_any_native_launch(self):
        cases = []
        for label, name, data, code in (('corrupt wav', 'a.wav', b'not audio', 'INVALID_FLAC_WAV'),
                                        ('24-bit wav', 'a.wav', wav_bytes(bits=24, pcm=bytes(12)), 'INVALID_FLAC_WAV'),
                                        ('long wav', 'a.wav', wav_bytes(rate=8000, channels=1, pcm=bytes(2 * 600 * 8000 + 2)), 'FLAC_BUDGET'),
                                        ('ogg', 'a.flac', b'OggS' + bytes(80), 'UNSUPPORTED_FLAC_FORMAT'),
                                        ('id3', 'a.flac', b'ID3\x04\0\0\0\0\0\0' + build_flac(), 'UNSUPPORTED_FLAC_FORMAT'),
                                        ('unknown count', 'a.flac', build_flac(info=streaminfo(total=0)), 'UNSUPPORTED_FLAC_FORMAT'),
                                        ('truncated', 'a.flac', b'fLaC\0\0', 'INVALID_FLAC_STREAM')):
            (self.root / name).write_bytes(data)
            document = self.encode if name.endswith('wav') else self.decode
            fault = self.fault(lambda: adaptor.run(document, self.root / ('refused-' + label.replace(' ', '-')), executable=self.flac, timeout=30), code)
            self.assertEqual(fault.location, '$.source')
            self.assertFalse((self.root / ('refused-' + label.replace(' ', '-')) / 'version-submission.json').exists(), label)
            cases.append(label)
        self.assertEqual(len(cases), 7)
        self.fault(lambda: adaptor.run(self.encode, self.root / 'zero', executable=self.flac, timeout=0), 'INVALID_ARGUMENT')
        self.fault(lambda: adaptor.run({**self.encode, 'source': str(self.root / 'absent.wav')}, self.root / 'absent', executable=self.flac, timeout=30), 'INVALID_FLAC_SOURCE')
        self.wav.write_bytes(self.wav_data)
        self.publish(self.encode, 'fresh')
        self.fault(lambda: self.publish(self.encode, 'fresh'), 'OUTPUT_EXISTS')

    def test_native_failures_are_structured_and_decode_rejections_are_input_faults(self):
        failing = program(self.root, 'failing-flac', marker='sys.stderr.write("ERROR: bad input\\n"); sys.exit(3)')
        fault = self.fault(lambda: adaptor.run(self.encode, self.root / 'bad', executable=failing, timeout=30), 'NATIVE_EXECUTION_FAILED')
        self.assertIn('exit 3', fault.message)
        self.assertIn('bad input', fault.message)
        damaged = build_flac(16000, 2, self.pcm)
        self.source.write_bytes(damaged[:26] + bytes([damaged[26] ^ 1]) + damaged[27:])           # STREAMINFO MD5 changed
        fault = self.fault(lambda: adaptor.run(self.decode, self.root / 'md5', executable=self.flac, timeout=30), 'FLAC_STREAM_REJECTED')
        self.assertIn('MD5 signature mismatch', fault.observed['cause']['message'])
        self.assertEqual(fault.location, '$.source')
        self.source.write_bytes(build_flac(16000, 2, self.pcm, total=2048, body=self.pcm))        # native accepts a longer body (as libFLAC does)
        fault = self.fault(lambda: adaptor.run(self.decode, self.root / 'count', executable=self.flac, timeout=30), 'FLAC_STREAM_REJECTED')
        self.assertIn('disagrees with the STREAMINFO sample count', fault.message)
        self.assertEqual(adaptor.read_json(self.root / 'count', 'result.json')['status'], 'failed')
        self.assertFalse((self.root / 'count/audio.wav').exists())

    def test_native_output_beyond_the_expected_size_is_stopped_by_the_launcher_cap(self):
        flooding = program(self.root, 'flooding-flac', extra='bytes(3 * 1024 * 1024)')
        self.fault(lambda: adaptor.run(self.decode, self.root / 'flood', executable=flooding, timeout=60), 'FLAC_STREAM_REJECTED')
        self.assertFalse((self.root / 'flood/audio.wav').exists())

    def test_noisy_native_stage_is_not_accepted_as_silent(self):
        noisy = program(self.root, 'noisy-flac', marker='if "-d" not in args:\n    sys.stderr.write("WARNING: something\\n")')
        fault = self.fault(lambda: adaptor.run(self.encode, self.root / 'noisy', executable=noisy, timeout=60), 'VERIFICATION_FAILED')
        self.assertIn('silent native stage', fault.message)

    def test_unusable_encoder_output_is_refused_at_the_right_boundary(self):
        garbage = program(self.root, 'garbage-flac', marker='if "-d" not in args:\n    open(args[args.index("-o") + 1], "wb").write(b"fLaC\\0\\0\\0")\n    sys.exit(0)')
        self.assertEqual(self.fault(lambda: adaptor.run(self.encode, self.root / 'garbage', executable=garbage, timeout=60), 'NATIVE_EXECUTION_FAILED').location, 'decode')
        padded = program(self.root, 'padded-flac', build='build_flac(rate, channels, pcm, extra_blocks=[(1, bytes(8))])')    # decodes, but not the fixed encode's metadata
        fault = self.fault(lambda: adaptor.run(self.encode, self.root / 'padded', executable=padded, timeout=60), 'VERIFICATION_FAILED')
        self.assertEqual(fault.observed['cause']['code'], 'INVALID_FLAC_STREAM')

    def test_timeout_and_cancellation_terminate_the_owned_process(self):
        marker = self.root / 'slow.pid'
        slow = Path(self.root) / 'slow-flac'
        slow.write_text('#!%s\nimport os, sys, time\nif sys.argv[1:] == ["--version"]:\n    print("flac 1.5.0"); sys.exit(0)\nopen(%r, "w").write(str(os.getpid()))\ntime.sleep(30)\n' % (sys.executable, str(marker)))
        slow.chmod(0o700)
        for action in ('timeout', 'cancel'):
            marker.unlink(missing_ok=True)
            cancel = threading.Event()
            thread = None
            if action == 'cancel':
                def trigger():
                    end = time.monotonic() + 8
                    while not marker.exists() and time.monotonic() < end:
                        time.sleep(.01)
                    cancel.set()
                thread = threading.Thread(target=trigger, daemon=True)
                thread.start()
            try:
                with allocation({'threads': 1, 'ranks': 1}, cancel):
                    self.fault(lambda: adaptor.run(self.encode, self.root / ('inflight-' + action), executable=str(slow),
                                                   timeout=10 if thread else 2), 'RUNNER_CANCELLED' if thread else 'RUNNER_TIMED_OUT')
            finally:
                if thread:
                    thread.join(10)
            self.assertTrue(marker.exists())
            with self.assertRaises(ProcessLookupError):
                os.kill(int(marker.read_text()), 0)

    def test_verification_timeout_and_cancellation_keep_their_own_codes(self):
        directory, _ = self.publish(self.encode)
        slow = program(self.root, 'slow-flac2', marker='if "-d" in args:\n    import time; time.sleep(30)')
        started = time.monotonic()
        with mock.patch.object(adaptor, 'VERIFY_TIMEOUT', 2):
            self.fault(lambda: adaptor.verify(directory, executable=slow), 'RUNNER_TIMED_OUT')
        self.assertLess(time.monotonic() - started, 20)
        cancel = threading.Event()
        cancel.set()
        with allocation({'threads': 1, 'ranks': 1}, cancel):
            self.fault(lambda: adaptor.verify(directory, executable=self.flac), 'RUNNER_CANCELLED')
        self.assertTrue(adaptor.verify(directory, executable=self.flac)['verified'])

    def test_directory_that_appears_before_creation_is_output_exists(self):
        with mock.patch.object(Path, 'mkdir', side_effect=FileExistsError('raced')):
            fault = self.fault(lambda: adaptor.run(self.encode, self.root / 'raced', executable=self.flac, timeout=30), 'OUTPUT_EXISTS')
        self.assertEqual(fault.location, str(self.root / 'raced'))
        occupied = self.root / 'occupied'
        occupied.write_text('a file')
        self.fault(lambda: adaptor.run(self.encode, occupied, executable=self.flac, timeout=30), 'OUTPUT_EXISTS')

    # ------------------------------------------------------------ retained JSON, typed and strict
    def test_typed_duplicate_and_nonfinite_retained_json_is_refused_with_every_hash_refreshed(self):
        directory, _ = self.publish(self.encode)
        saved = {p: p.read_bytes() for p in directory.rglob('*') if p.is_file()}

        def first(old, new):
            def edit(text):
                self.assertEqual(text.count(old), 1, old)
                return text.replace(old, new)
            return edit

        def leading(entry):
            return lambda text: '{' + entry + ', ' + text.lstrip()[1:]
        cases = [
            ('flac-summary.json', first('"exactPcm": true', '"exactPcm": 1'), True, 'summary differs'),
            ('flac-summary.json', re_float(r'("audio": \{[^}]*?"channels": )(\d+)'), True, 'summary differs'),
            ('flac-summary.json', first('"exactPcm": true', '"exactPcm": false, "exactPcm": true'), False, 'duplicate JSON key'),
            ('flac-summary.json', first('"exactPcm": true', '"exactPcm": NaN'), False, 'non-finite'),
            ('flac-summary.json', first('"exactPcm": true', '"exactPcm": 1e400'), False, 'non-finite'),
            ('plan.json', leading('"operation": "encodeLossless"'), False, 'duplicate JSON key'),
            ('captures.json', re_float(r'("bytes": )(\d+)'), True, 'capture record differs'),
            ('captures.json', leading('"bytes": 1'), False, 'duplicate JSON key'),
            ('encode-inputs.json', leading('"source.pcm": "0"'), False, 'duplicate JSON key'),
            ('decode-inputs.json', leading('"audio.flac": "0"'), False, 'duplicate JSON key'),
            ('encode-submission.json', first('"exitCode": 0', '"exitCode": 0.0'), True, 'completion record differs'),
            ('authored.json', leading('"operation": "encodeLossless"'), False, 'duplicate JSON key'),
            ('result.json', first('"verified": true', '"verified": 1'), True, 'result claims differ'),
            ('result.json', first('"artifacts": 2', '"artifacts": 2.0'), True, 'result claims differ'),
            ('result.json', leading('"status": "failed"'), False, 'duplicate JSON key'),
            ('verification.json', leading('"extra": NaN'), False, 'non-finite'),
            ('verification.json', leading('"extra": 1e400'), False, 'non-finite'),
            ('verification.json', first('"encode.stdout"', '"encode.stdout": "0", "encode.stdout"'), False, 'duplicate JSON key'),
        ]
        for name, edit, collapses, message in cases:
            with self.subTest(file=name, message=message):
                path = directory / name
                try:
                    if name == 'verification.json':
                        rebind(directory)    # the receipt is rebound first, then textually forged
                    before = path.read_text()
                    path.write_text(edit(before))
                    self.assertNotEqual(before, path.read_text(), (name, message))
                    if collapses:    # Python equality (1 == True, 66 == 66.0) would have accepted this edit
                        self.assertEqual(json.loads(before), json.loads(path.read_text()), (name, message))
                    if name != 'verification.json':
                        rebind(directory)    # every ordinary hash agrees with the forged file
                    fault = self.fault(lambda: adaptor.verify(directory, executable=self.flac),
                                       'INVALID_SCHEMA_SNAPSHOT' if name == 'authored.json' else 'VERIFICATION_FAILED')
                    self.assertIn(message, fault.message, (name, fault.message))
                finally:
                    for path, data in saved.items():
                        path.write_bytes(data)
        self.assertTrue(adaptor.verify(directory, executable=self.flac)['verified'])

    def test_result_claims_must_be_succeeded_and_typed_when_a_result_is_required(self):
        directory, result = self.publish(self.decode)
        recorded = adaptor.read_json(directory, 'result.json')
        self.assertEqual({k: recorded[k] for k in ('status', 'verified', 'artifacts', 'operation')}, {'status': 'succeeded', 'verified': True, 'artifacts': 2, 'operation': 'decodePCM16'})
        for label, mutate, code in (('failed', lambda r: r.update(status='failed'), 'INCOMPLETE_EXECUTION'), ('status type', lambda r: r.update(status=['succeeded']), 'INCOMPLETE_EXECUTION'),
                                    ('frames', lambda r: r['audio'].update(frames=2050), 'VERIFICATION_FAILED'), ('frame type', lambda r: r['audio'].update(frames=2049.0), 'VERIFICATION_FAILED'),
                                    ('bytes', lambda r: r['bytes'].update(wav=1), 'VERIFICATION_FAILED'), ('sha', lambda r: r.update(pcmSha256='0' * 64), 'VERIFICATION_FAILED'),
                                    ('runtime claim', lambda r: r['runtime'].update(flac='flac 1.5.9'), 'VERIFICATION_FAILED'),
                                    ('extra promotion', lambda r: r.update(authenticityVerified=True), 'VERIFICATION_FAILED'),
                                    ('extra runtime field', lambda r: r['runtime'].update(accuracyCertified=True), 'VERIFICATION_FAILED'),
                                    ('malformed runtime', lambda r: r.update(runtime=[]), 'VERIFICATION_FAILED'),
                                    ('fresh decoder text', lambda r: r['runtime'].update(freshDecoder={'x': 1}), 'VERIFICATION_FAILED')):
            changed = copy.deepcopy(recorded)
            mutate(changed)
            atomic_json(directory / 'result.json', changed)
            self.fault(lambda: adaptor.verify(directory, executable=self.flac), code)
            self.assertTrue(adaptor.verify(directory, require_result=False, executable=self.flac)['verified'], label)
        (directory / 'result.json').write_text('[]')
        self.fault(lambda: adaptor.verify(directory, executable=self.flac), 'INCOMPLETE_EXECUTION')
        atomic_json(directory / 'result.json', recorded)
        self.assertTrue(adaptor.verify(directory, executable=self.flac)['verified'])

    # ------------------------------------------------------------ one snapshot of the decoded FLAC
    def test_verify_reads_the_published_flac_once_and_binds_the_receipt_to_that_snapshot(self):
        directory, _ = self.publish(self.encode)
        flac_path = directory / 'audio.flac'
        original = flac_path.read_bytes()
        swapped = b'a different file than the one that was decoded'
        real = adaptor.bounded
        reads = []

        def reading(path, *args, **kwargs):
            if Path(path) == flac_path:
                reads.append(path)
            return real(path, *args, **kwargs)
        with mock.patch.object(adaptor, 'bounded', reading):
            self.assertTrue(adaptor.verify(directory, executable=self.flac)['verified'])
        self.assertEqual(len(reads), 1)
        receipt = adaptor.read_json(directory, 'verification.json')
        receipt['artifacts'][0]['sha256'] = adaptor.sha(swapped)
        atomic_json(directory / 'verification.json', receipt)
        flips = []

        def flipping(path, *args, **kwargs):
            if Path(path) == flac_path:
                flips.append(path)
                return original if len(flips) % 2 else swapped
            return real(path, *args, **kwargs)
        with mock.patch.object(adaptor, 'bounded', flipping):
            fault = self.fault(lambda: adaptor.verify(directory, executable=self.flac), 'VERIFICATION_FAILED')
        self.assertIn('publication membership or digests differ from the receipt', fault.message)
        self.assertEqual(len(flips), 1)

    # ------------------------------------------------------------ standard hooks, CLI, configuration, workflow
    def test_standard_registry_hooks_and_cli_use_the_trusted_location(self):
        locations = {'flac': self.flac}
        directory = self.root / 'registry'
        result = registry.run(self.encode, directory, locations=locations, timeout=60)
        self.assertTrue(result['verified'])
        with configuration.location_context(locations):
            self.assertTrue(registry.verify(directory)['verified'])
        with private_configuration():
            self.fault(lambda: registry.verify(directory), 'INTERPRETER_NOT_FOUND')
        (self.root / 'doc.json').write_text(json.dumps(self.decode))
        completed = subprocess.run([sys.executable, '-m', 'schemaxis', 'run', str(self.root / 'doc.json'), '--output-directory', str(self.root / 'cli'),
                                    '--flac', self.flac, '--timeout', '60'], env=self.environment, capture_output=True, text=True, timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stderr[-600:] + completed.stdout[-600:])
        self.assertTrue(json.loads(completed.stdout)['verified'])
        absent = subprocess.run([sys.executable, '-m', 'schemaxis', 'verify', str(self.root / 'cli')], env=self.environment, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(absent.returncode, 0)
        self.assertIn('INTERPRETER_NOT_FOUND', absent.stdout + absent.stderr)
        fine = subprocess.run([sys.executable, '-m', 'schemaxis', 'verify', str(self.root / 'cli')], env={**self.environment, 'SCHEMAXIS_FLAC': self.flac}, capture_output=True, text=True, timeout=60)
        self.assertEqual(fine.returncode, 0, fine.stderr[-600:] + fine.stdout[-600:])
        planned = subprocess.run([sys.executable, '-m', 'schemaxis', 'plan', str(self.root / 'doc.json')], env=self.environment, capture_output=True, text=True, timeout=60)
        self.assertEqual(planned.returncode, 0, planned.stderr[-400:])
        self.assertNotIn(self.flac, planned.stdout)

    def test_stored_location_verifies_and_isolation_hides_it_from_other_tests(self):
        directory, _ = self.publish(self.encode)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ):
            config = Path(tmp) / 'config.json'
            config.write_text(json.dumps({'version': 1, 'locations': {'flac': self.flac}}))
            os.environ['SCHEMAXIS_CONFIG'] = str(config)
            os.environ.pop('SCHEMAXIS_FLAC', None)
            self.assertTrue(adaptor.verify(directory)['verified'])
            with configuration.location_context({'flac': None}):    # None does not clear a stored location
                self.assertTrue(registry.verify(directory)['verified'])
            completed = subprocess.run([sys.executable, '-m', 'schemaxis', 'verify', str(directory)], env={**self.environment, 'SCHEMAXIS_CONFIG': str(config)},
                                       capture_output=True, text=True, timeout=120)
            self.assertEqual(completed.returncode, 0, completed.stderr[-600:] + completed.stdout[-600:])
        with private_configuration():
            self.fault(lambda: adaptor.verify(directory), 'INTERPRETER_NOT_FOUND')

    def test_workflow_reuse_follows_captured_source_bytes_and_artifacts_chain(self):
        locations = {'flac': self.flac}
        graph = {'version': 'schemaxis.workflow/1', 'operations': [
            {'id': 'archive', 'document': self.encode},
            {'id': 'restore', 'document': {'version': 'schemaxis.flac/1', 'operation': 'decodePCM16', 'source': {'$artifact': 'archive', 'index': 0}}}]}
        directory = self.root / 'workflow'
        first = workflow.execute(graph, directory, locations=locations, timeout=120)
        self.assertEqual(first['status'], 'succeeded')
        with configuration.location_context(locations):
            self.assertTrue(workflow.verify(directory)['verified'])
        restored = [p for p in directory.rglob('audio.wav')]
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored[0].read_bytes(), self.wav_data)    # WAV to FLAC to WAV is identity for a canonical PCM16 WAV
        second = workflow.execute(graph, directory, locations=locations, timeout=120, resume=True)
        self.assertTrue(all(job['reused'] for job in second['jobs']))
        self.wav.write_bytes((FIXTURES / 'stereo-48000.wav').read_bytes())
        third = workflow.execute(graph, directory, locations=locations, timeout=120, resume=True)
        self.assertTrue(all(not job['reused'] for job in third['jobs']))

    def test_example_workflows_plan_on_the_host_with_deferred_artifacts(self):
        document = json.loads((ROOT / 'examples/schemaxis/flac-speech-workflow.json').read_text())
        planned = workflow.inspect_plan(document)
        speech = {entry['id']: entry for entry in planned['operations']}['speech']['provisionalPlan']
        self.assertEqual((speech['status'], speech['references']), ('deferred', [{'$artifact': 'decode', 'index': 0}]))
        archive = json.loads((ROOT / 'examples/schemaxis/flac-archive-workflow.json').read_text())
        planned = workflow.inspect_plan(archive)
        entry = {entry['id']: entry for entry in planned['operations']}['archive']['provisionalPlan']
        self.assertEqual((entry['status'], entry['references']), ('deferred', [{'$artifact': 'speech', 'index': 0}]))
        self.assertEqual({job['id']: job for job in planned['jobs']}['archive/0']['dependencies'], ['speech'])


def re_float(pattern):
    return lambda text: re.sub(pattern, lambda m: m.group(1) + m.group(2) + '.0', text, count=1, flags=re.S)


@unittest.skipUnless(os.environ.get('SCHEMAXIS_FLAC'), 'real flac not configured: unqualified, see tools/qualify_flac.py')
class RealFlac(unittest.TestCase):
    def test_all_fixtures_roundtrip_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            flac = os.environ['SCHEMAXIS_FLAC']
            for name in ('mono-8000', 'stereo-16000', 'stereo-48000'):
                directory = Path(tmp) / (name + '-enc')
                document = {'version': 'schemaxis.flac/1', 'operation': 'encodeLossless', 'source': str(FIXTURES / (name + '.wav'))}
                self.assertTrue(adaptor.run(document, directory, executable=flac, timeout=60)['verified'])
                self.assertTrue(adaptor.verify(directory)['verified'])
                directory = Path(tmp) / (name + '-dec')
                document = {'version': 'schemaxis.flac/1', 'operation': 'decodePCM16', 'source': str(FIXTURES / (name + '.flac'))}
                self.assertTrue(adaptor.run(document, directory, executable=flac, timeout=60)['verified'])
                expected = adaptor.canonical_wav(*[adaptor.parse_wav((FIXTURES / (name + '.wav')).read_bytes())[k] for k in ('rate', 'channels', 'pcm')])
                self.assertEqual((directory / 'audio.wav').read_bytes(), expected)


if __name__ == '__main__':
    unittest.main()
