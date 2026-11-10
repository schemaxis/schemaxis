"""WebP run/verify boundaries with deterministic fake cwebp/dwebp programs (no libwebp).

The fake codec stores the PAM pixels inside a correctly framed VP8L chunk. It proves host behaviour
only (framing, comparison, receipts, trusted executables, lifecycle, standard hooks); native
libwebp acceptance is tools/qualify_webp.py. Tests needing real binaries run only when
SCHEMAXIS_WEBP and SCHEMAXIS_DWEBP are set, and are reported skipped otherwise, never passed.
"""
import contextlib
import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from schemaxis import configuration, workflow
from schemaxis.adaptors import registry
from schemaxis.adaptors.webp import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'examples/schemaxis/fixtures/webp'
ENCODER = '''#!{python}
import re, struct, sys
args = sys.argv[1:]
if args == ['-version']:
    print('{version}'); print('libsharpyuv: 0.4.2'); sys.exit(0)
{marker}
data = open(args[args.index('source.pam')], 'rb').read()
found = re.match(rb'P7\\nWIDTH (\\d+)\\nHEIGHT (\\d+)\\n.*?ENDHDR\\n', data, re.S)
width, height, pixels = int(found.group(1)), int(found.group(2)), data[found.end():]
body = b'\\x2f' + struct.pack('<I', (width - 1) | ((height - 1) << 14) | (1 << 28)) + pixels
size = len(body); body += b'\\0' * (size & 1)
open(args[args.index('-o') + 1], 'wb').write(b'RIFF' + struct.pack('<I', 12 + len(body)) + b'WEBPVP8L' + struct.pack('<I', size) + body)
sys.stderr.write('Output:    %d bytes (0.00 bpp)\\n' % (20 + len(body)))
'''
DECODER = '''#!{python}
import re, struct, sys
args = sys.argv[1:]
if args == ['-version']:
    print('1.6.0'); sys.exit(0)
{marker}
data = open(args[0], 'rb').read()
size = struct.unpack('<I', data[16:20])[0]
bits = struct.unpack('<I', data[21:25])[0]
width, height = (bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1
open(args[args.index('-o') + 1], 'wb').write(b'P7\\nWIDTH %d\\nHEIGHT %d\\nDEPTH 4\\nMAXVAL 255\\nTUPLTYPE RGB_ALPHA\\nENDHDR\\n' % (width, height) + data[25:20 + size])
'''


REFUSE_ZEROED_PAYLOAD = (
    'if set(open(args[0], "rb").read()[25:]) == {0}:\n'
    '    sys.stderr.write("Decoding of image.webp failed.\\nStatus: 3(BITSTREAM_ERROR)\\n"); sys.exit(1)')


def program(directory, name, template, version='1.6.0', marker=''):
    path = Path(directory) / name
    path.write_text(template.format(python=sys.executable, version=version, marker=marker))
    path.chmod(0o700)
    return str(path)


@contextlib.contextmanager
def private_configuration(directory, locations=None):
    """A private SCHEMAXIS_CONFIG with cleared SCHEMAXIS_WEBP/DWEBP (location_context(None) does not clear stored settings)."""
    path = Path(directory) / 'private-config.json'
    path.write_text(json.dumps({'version': 1, 'locations': locations or {}}))
    with mock.patch.dict(os.environ):
        os.environ['SCHEMAXIS_CONFIG'] = str(path)
        os.environ.pop('SCHEMAXIS_WEBP', None)
        os.environ.pop('SCHEMAXIS_DWEBP', None)
        yield


def refresh(directory):
    """Make every ordinary hash agree with the (tampered) files, as a forging writer would."""
    directory = Path(directory)
    receipt = adaptor.read_json(directory, 'verification.json')
    names = sorted(receipt['evidence'])
    atomic_json(directory / 'decode-inputs.json', {'image.webp': adaptor.digest(directory, 'image.webp')})
    webp = (directory / 'image.webp').read_bytes()
    (directory / 'encode.stderr').write_text('Output:    %d bytes (0.00 bpp)\n' % len(webp))
    receipt['evidence'] = {n: adaptor.digest(directory, n) for n in names}
    receipt['artifacts'] = adaptor.publications(directory)
    atomic_json(directory / 'verification.json', receipt)


def rebind(directory):
    """Rebind only the receipt's artifact and evidence digests to the files as they now are (no other rewriting)."""
    directory = Path(directory)
    receipt = adaptor.read_json(directory, 'verification.json')
    receipt['evidence'] = {n: adaptor.digest(directory, n) for n in sorted(receipt['evidence'])}
    receipt['artifacts'] = adaptor.publications(directory)
    atomic_json(directory / 'verification.json', receipt)


class FakeNativeBoundary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.encoder = program(self.root, 'cwebp', ENCODER)
        self.decoder = program(self.root, 'dwebp', DECODER)
        self.source = self.root / 'swatch.png'
        shutil.copyfile(FIXTURES / 'swatch-rgba.png', self.source)
        self.document = {'version': 'schemaxis.webp/1', 'operation': 'encodeLossless', 'source': str(self.source)}
        self.environment = {k: v for k, v in os.environ.items() if k not in ('SCHEMAXIS_WEBP', 'SCHEMAXIS_DWEBP', 'SCHEMAXIS_CONFIG')}
        (self.root / 'empty.json').write_text('{"version": 1, "locations": {}}')
        self.environment['SCHEMAXIS_CONFIG'] = str(self.root / 'empty.json')
        self.environment['PYTHONPATH'] = str(ROOT / 'src')

    def fault(self, action, code):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    def publish(self, name='run'):
        directory = self.root / name
        result = adaptor.run(self.document, directory, executable=self.encoder, decoder=self.decoder, timeout=60)
        return directory, result

    def test_run_publishes_two_artifacts_and_verifies_fresh(self):
        directory, result = self.publish()
        self.assertTrue(result['verified'])
        self.assertEqual(result['dimensions'], [7, 5])
        receipt = adaptor.read_json(directory, 'verification.json')
        self.assertEqual([(Path(a['file']).name, a['kind']) for a in receipt['artifacts']], [('image.webp', 'image'), ('webp-summary.json', 'text')])
        summary = adaptor.read_json(directory, 'webp-summary.json')
        self.assertEqual(summary['pixels'], {'total': 35, 'opaque': 18, 'partialAlpha': 6, 'transparent': 11, 'transparentWithRgb': 7})
        self.assertEqual(summary['source']['droppedAncillaryChunks'], ['tEXt'])
        self.assertTrue(adaptor.verify(directory, decoder=self.decoder)['verified'])
        launcher = (directory / 'encode-launcher.py').read_text()
        self.assertIn("'-lossless', '-exact', '-z', '6', 'source.pam', '-o', 'image.webp'", launcher)
        self.assertIn('{"LANG":"C","LC_ALL":"C"}', launcher)
        self.assertIn('RLIMIT_AS', launcher)

    def test_changed_pixels_are_rejected_even_when_every_hash_is_refreshed(self):
        for label, change in (('pixel', lambda b: b[:25] + bytes([b[25] ^ 1]) + b[26:]),
                              ('hiddenRgb', lambda b: b[:25 + 4 * 14] + bytes(3) + b[25 + 4 * 14 + 3:])):
            directory, _ = self.publish(label)
            path = directory / 'image.webp'
            before = path.read_bytes()
            path.write_bytes(change(before))
            self.assertNotEqual(before, path.read_bytes())
            refresh(directory)
            fault = self.fault(lambda: adaptor.verify(directory, decoder=self.decoder), 'VERIFICATION_FAILED')
            self.assertIn('does not decode to the captured PNG samples', fault.message)

    def test_wrong_container_is_rejected_after_refreshing_hashes(self):
        directory, _ = self.publish()
        good = (directory / 'image.webp').read_bytes()
        for label, forged in (('lossy', good.replace(b'VP8L', b'VP8 ')), ('extended', good.replace(b'VP8L', b'VP8X')),
                              ('trailing', good + b'\0\0'), ('truncated', good[:-4])):
            (directory / 'image.webp').write_bytes(forged)
            refresh(directory)
            self.fault(lambda: adaptor.verify(directory, decoder=self.decoder), 'VERIFICATION_FAILED')
        (directory / 'image.webp').write_bytes(good)
        refresh(directory)
        self.assertTrue(adaptor.verify(directory, decoder=self.decoder)['verified'])

    def test_retained_evidence_is_bound_without_refresh(self):
        directory, _ = self.publish()
        saved = {p: p.read_bytes() for p in directory.rglob('*') if p.is_file()}
        for name, change in (('image.webp', lambda b: b[:-1] + b'\x01'), ('webp-summary.json', lambda b: b.replace(b'"opaque": 18', b'"opaque": 19')),
                             ('captured.png', lambda b: (FIXTURES / 'swatch-rgba-changed.png').read_bytes()), ('source.pam', lambda b: b.replace(b'WIDTH 7', b'WIDTH 8')),
                             ('reopened.pam', lambda b: b[:-1] + b'\x01'), ('encode-launcher.py', lambda b: b.replace(b'-z', b'-q')),
                             ('encode.stderr', lambda b: b.replace(b'Output:', b'Output: 1')), ('decoder-version.stdout', lambda b: b'1.7.0\n'),
                             ('verification.json', lambda b: b.replace(b'"artifacts"', b'"artefacts"')), ('plan.json', lambda b: b.replace(b'encodeLossless', b'encodeLossy')),
                             ('encode-submission.json', lambda b: b.replace(b'"exitCode": 0', b'"exitCode": 1')), ('decode-inputs.json', lambda b: b.replace(b'0', b'1', 1))):
            try:
                path = directory / name
                path.write_bytes(change(path.read_bytes()))
                self.fault(lambda: adaptor.verify(directory, decoder=self.decoder), 'VERIFICATION_FAILED')
            finally:
                for path, data in saved.items():
                    path.write_bytes(data)
        receipt = adaptor.read_json(directory, 'verification.json')
        for label, mutate in (('membership', lambda r: r['artifacts'].pop()), ('evidence', lambda r: r['evidence'].pop('encode.stdout')),
                              ('extra', lambda r: r['evidence'].update({'unowned.json': '0' * 64})), ('runtime', lambda r: r['runtime'].update(decoder='9.9.9'))):
            try:
                changed = copy.deepcopy(receipt)
                mutate(changed)
                atomic_json(directory / 'verification.json', changed)
                self.fault(lambda: adaptor.verify(directory, decoder=self.decoder), 'VERIFICATION_FAILED')
            finally:
                atomic_json(directory / 'verification.json', receipt)
        self.assertTrue(adaptor.verify(directory, decoder=self.decoder)['verified'])

    def test_verification_requires_trusted_dwebp_and_never_runs_a_receipt_path(self):
        marker = self.root / 'executed.marker'
        directory, _ = self.publish()
        trap = program(self.root, 'trap-dwebp', DECODER, marker='open(%r, "w").write("ran")' % str(marker))
        receipt = adaptor.read_json(directory, 'verification.json')
        receipt['executables']['decoder'] = trap
        atomic_json(directory / 'verification.json', receipt)
        with private_configuration(self.root):
            fault = self.fault(lambda: adaptor.verify(directory), 'INTERPRETER_NOT_FOUND')
            self.assertEqual(fault.location, '$.runtime.decoder')
            self.assertFalse(marker.exists())
            refresh(directory)    # the receipt names a different executable, so the recomputed launcher differs
            self.fault(lambda: adaptor.verify(directory, decoder=self.decoder), 'VERIFICATION_FAILED')
            self.assertFalse(marker.exists())
        # A relative, missing or non-executable trusted path is also unavailable, not verified.
        for bad in ('dwebp', str(self.root / 'missing'), str(self.source)):
            self.fault(lambda: adaptor.verify(directory, decoder=bad), 'INTERPRETER_NOT_FOUND')

    def test_unsupported_runtime_stops_before_encoding(self):
        old = program(self.root, 'old-cwebp', ENCODER, version='1.5.0')
        self.fault(lambda: adaptor.run(self.document, self.root / 'old', executable=old, decoder=self.decoder, timeout=30), 'UNSUPPORTED_RUNTIME')
        self.assertFalse((self.root / 'old/image.webp').exists())
        self.assertEqual(adaptor.read_json(self.root / 'old', 'result.json')['status'], 'failed')

    def test_source_faults_stop_before_any_native_launch(self):
        for label, data, code in (('corrupt', b'not a png', 'INVALID_WEBP_PNG'), ('huge', (FIXTURES / 'swatch-rgba.png').read_bytes()[:16] + b'\0\0\x10\0\0\0\x10\0' + bytes(100), 'WEBP_PIXEL_BUDGET')):
            self.source.write_bytes(data)
            self.fault(lambda: adaptor.run(self.document, self.root / label, executable=self.encoder, decoder=self.decoder, timeout=30), code)
            self.assertFalse((self.root / label / 'encoder-version-submission.json').exists())
        self.fault(lambda: adaptor.run(self.document, self.root / 'run', executable=self.encoder, decoder=self.decoder, timeout=0), 'INVALID_ARGUMENT')
        shutil.copyfile(FIXTURES / 'swatch-rgba.png', self.source)
        self.publish('fresh')
        self.fault(lambda: self.publish('fresh'), 'OUTPUT_EXISTS')

    def test_native_failure_and_nonzero_exit_are_structured(self):
        failing = program(self.root, 'failing-cwebp', ENCODER, marker='sys.stderr.write("Error! bad input\\n"); sys.exit(3)')
        fault = self.fault(lambda: adaptor.run(self.document, self.root / 'bad', executable=failing, decoder=self.decoder, timeout=30), 'NATIVE_EXECUTION_FAILED')
        self.assertIn('exit 3', fault.message)
        self.assertIn('Error! bad input', fault.message)
        garbage = program(self.root, 'garbage-dwebp', DECODER, marker='open(args[args.index("-o") + 1], "wb").write(b"P6\\n"); sys.exit(0)')
        self.fault(lambda: adaptor.run(self.document, self.root / 'garbage', executable=self.encoder, decoder=garbage, timeout=30), 'VERIFICATION_FAILED')

    def test_timeout_and_cancellation_terminate_the_owned_process(self):
        marker = self.root / 'slow.pid'
        slow = Path(self.root) / 'slow-cwebp'
        slow.write_text('#!%s\nimport os, time\nopen(%r, "w").write(str(os.getpid()))\ntime.sleep(30)\n' % (sys.executable, str(marker)))
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
                    self.fault(lambda: adaptor.run(self.document, self.root / ('inflight-' + action), executable=str(slow), decoder=self.decoder,
                                                   timeout=10 if thread else .5), 'RUNNER_CANCELLED' if thread else 'RUNNER_TIMED_OUT')
            finally:
                if thread:
                    thread.join(10)
            self.assertTrue(marker.exists())
            with self.assertRaises(ProcessLookupError):
                os.kill(int(marker.read_text()), 0)

    def test_standard_registry_hooks_and_cli_use_both_trusted_locations(self):
        locations = {'webp': self.encoder, 'dwebp': self.decoder}
        directory = self.root / 'registry'
        result = registry.run(self.document, directory, locations=locations, timeout=60)
        self.assertTrue(result['verified'])
        with configuration.location_context({'dwebp': self.decoder}):
            self.assertTrue(registry.verify(directory)['verified'])
        with private_configuration(self.root):
            self.fault(lambda: registry.verify(directory), 'INTERPRETER_NOT_FOUND')
        (self.root / 'doc.json').write_text(json.dumps(self.document))
        completed = subprocess.run([sys.executable, '-m', 'schemaxis', 'run', str(self.root / 'doc.json'), '--output-directory', str(self.root / 'cli'),
                                    '--webp', self.encoder, '--dwebp', self.decoder, '--timeout', '60'], env=self.environment, capture_output=True, text=True, timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stderr[-600:] + completed.stdout[-600:])
        self.assertTrue(json.loads(completed.stdout)['verified'])
        absent = subprocess.run([sys.executable, '-m', 'schemaxis', 'verify', str(self.root / 'cli')], env=self.environment, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(absent.returncode, 0)
        self.assertIn('INTERPRETER_NOT_FOUND', absent.stdout + absent.stderr)
        fine = subprocess.run([sys.executable, '-m', 'schemaxis', 'verify', str(self.root / 'cli')], env={**self.environment, 'SCHEMAXIS_DWEBP': self.decoder}, capture_output=True, text=True, timeout=60)
        self.assertEqual(fine.returncode, 0, fine.stderr[-600:] + fine.stdout[-600:])
        planned = subprocess.run([sys.executable, '-m', 'schemaxis', 'plan', str(self.root / 'doc.json')], env=self.environment, capture_output=True, text=True, timeout=60)
        self.assertEqual(planned.returncode, 0, planned.stderr[-400:])
        self.assertNotIn(self.encoder, planned.stdout)
        self.assertFalse((self.root / 'plan-effects').exists())

    # ------------------------------------------------------------ retained JSON, typed and strict
    def test_typed_duplicate_and_nonfinite_retained_json_is_refused_with_every_hash_refreshed(self):
        directory, _ = self.publish()
        saved = {p: p.read_bytes() for p in directory.rglob('*') if p.is_file()}
        rebind(directory)
        self.assertTrue(adaptor.verify(directory, decoder=self.decoder)['verified'])    # rebinding itself is harmless
        for path, data in saved.items():
            path.write_bytes(data)

        def first(old, new):
            def edit(text):
                self.assertEqual(text.count(old), 1, old)
                return text.replace(old, new)
            return edit

        def leading(entry):
            return lambda text: '{' + entry + ', ' + text.lstrip()[1:]

        def integer_to_float(pattern, count=0):
            return lambda text: re.sub(pattern, lambda m: m.group(1) + m.group(2) + '.0', text, count=count, flags=re.S)
        # (file, edit, loose Python equality cannot tell the edit apart, expected message)
        cases = [
            ('webp-summary.json', first('"exactRgba": true', '"exactRgba": 1'), True, 'summary differs'),
            ('webp-summary.json', first('"alphaFlag": true', '"alphaFlag": 1'), True, 'summary differs'),
            ('webp-summary.json', integer_to_float(r'("image": \{[^}]*?"bytes": )(\d+)', 1), True, 'summary differs'),
            ('webp-summary.json', first('"opaque": 18', '"opaque": 18.0'), True, 'summary differs'),
            ('webp-summary.json', first('"exactRgba": true', '"exactRgba": false, "exactRgba": true'), False, 'duplicate JSON key'),
            ('webp-summary.json', first('"exactRgba": true', '"exactRgba": NaN'), False, 'non-finite'),
            ('webp-summary.json', first('"exactRgba": true', '"exactRgba": 1e400'), False, 'non-finite'),
            ('plan.json', first('"maxPixels": 1048576', '"maxPixels": 1048576.0'), True, 'plan differs'),
            ('plan.json', leading('"operation": "encodeLossless"'), False, 'duplicate JSON key'),
            ('captures.json', integer_to_float(r'("bytes": )(\d+)'), True, 'capture record differs'),
            ('captures.json', leading('"bytes": 1'), False, 'duplicate JSON key'),
            ('encode-inputs.json', leading('"source.pam": "0"'), False, 'duplicate JSON key'),
            ('decode-inputs.json', leading('"image.webp": "0"'), False, 'duplicate JSON key'),
            ('encode-submission.json', first('"exitCode": 0', '"exitCode": 0.0'), True, 'completion record differs'),
            ('authored.json', leading('"operation": "encodeLossless"'), False, 'duplicate JSON key'),
            ('result.json', first('"verified": true', '"verified": 1'), True, 'result claims differ'),
            ('result.json', first('"artifacts": 2', '"artifacts": 2.0'), True, 'result claims differ'),
            ('result.json', integer_to_float(r'("bytes": )(\d+)', 1), True, 'result claims differ'),
            ('result.json', leading('"status": "failed"'), False, 'duplicate JSON key'),
            ('verification.json', leading('"executables": {"encoder": "/x", "decoder": "/y"}'), False, 'duplicate JSON key'),
            ('verification.json', leading('"extra": NaN'), False, 'non-finite'),
            ('verification.json', leading('"extra": 1e400'), False, 'non-finite'),
            ('verification.json', leading('"extra": -Infinity'), False, 'non-finite'),
            ('verification.json', first('"encode.stdout"', '"encode.stdout": "0", "encode.stdout"'), False, 'duplicate JSON key'),
        ]
        for name, edit, collapses, message in cases:
            with self.subTest(file=name, message=message):
                path = directory / name
                try:
                    before = path.read_text()
                    if name == 'verification.json':
                        rebind(directory)    # the receipt is rebound first, then textually forged
                        before = path.read_text()
                    path.write_text(edit(before))
                    self.assertNotEqual(before, path.read_text(), (name, message))
                    if collapses:    # Python equality (1 == True, 66 == 66.0) would have accepted this edit
                        self.assertEqual(json.loads(before), json.loads(path.read_text()), (name, message))
                    if name != 'verification.json':
                        rebind(directory)    # every ordinary hash agrees with the forged file
                    # The shared runtime layer reads authored.json first and refuses duplicate keys with its own code.
                    fault = self.fault(lambda: adaptor.verify(directory, decoder=self.decoder),
                                       'INVALID_SCHEMA_SNAPSHOT' if name == 'authored.json' else 'VERIFICATION_FAILED')
                    self.assertIn(message, fault.message, (name, fault.message))
                finally:
                    for path, data in saved.items():
                        path.write_bytes(data)
        self.assertTrue(adaptor.verify(directory, decoder=self.decoder)['verified'])

    def test_result_claims_must_be_succeeded_and_typed_when_a_result_is_required(self):
        directory, result = self.publish()
        recorded = adaptor.read_json(directory, 'result.json')
        self.assertEqual({k: recorded[k] for k in ('status', 'verified', 'artifacts', 'dimensions', 'bytes')},
                         {'status': 'succeeded', 'verified': True, 'artifacts': 2, 'dimensions': [7, 5], 'bytes': result['bytes']})
        for label, mutate, code in (('failed', lambda r: r.update(status='failed'), 'INCOMPLETE_EXECUTION'),
                                    ('status type', lambda r: r.update(status=['succeeded']), 'INCOMPLETE_EXECUTION'),
                                    ('dimensions', lambda r: r.update(dimensions=[7, 6]), 'VERIFICATION_FAILED'),
                                    ('dimension type', lambda r: r.update(dimensions=[7.0, 5]), 'VERIFICATION_FAILED'),
                                    ('byte count', lambda r: r.update(bytes=r['bytes'] + 1), 'VERIFICATION_FAILED'),
                                    ('decoder claim', lambda r: r['runtime'].update(decoder='1.6.1'), 'VERIFICATION_FAILED')):
            changed = copy.deepcopy(recorded)
            mutate(changed)
            atomic_json(directory / 'result.json', changed)
            self.fault(lambda: adaptor.verify(directory, decoder=self.decoder), code)
            self.assertTrue(adaptor.verify(directory, require_result=False, decoder=self.decoder)['verified'], label)
        (directory / 'result.json').write_text('[]')
        self.fault(lambda: adaptor.verify(directory, decoder=self.decoder), 'INCOMPLETE_EXECUTION')
        atomic_json(directory / 'result.json', recorded)
        self.assertTrue(adaptor.verify(directory, decoder=self.decoder)['verified'])

    # ------------------------------------------------------------ one snapshot of image.webp
    def test_verify_reads_image_webp_once_and_binds_the_receipt_to_that_snapshot(self):
        directory, _ = self.publish()
        image_path = directory / 'image.webp'
        original = image_path.read_bytes()
        swapped = b'a different file than the one that was decoded'
        real = adaptor.bounded
        reads = []

        def reading(path, *args, **kwargs):
            if Path(path) == image_path:
                reads.append(path)
            return real(path, *args, **kwargs)
        with mock.patch.object(adaptor, 'bounded', reading):
            self.assertTrue(adaptor.verify(directory, decoder=self.decoder)['verified'])
        self.assertEqual(len(reads), 1)
        # A writer that flips the file between reads (A, B, A) used to satisfy the receipt (B) and the decode binding (A).
        receipt = adaptor.read_json(directory, 'verification.json')
        receipt['artifacts'][0]['sha256'] = adaptor.sha(swapped)
        atomic_json(directory / 'verification.json', receipt)
        flips = []

        def flipping(path, *args, **kwargs):
            if Path(path) == image_path:
                flips.append(path)
                return original if len(flips) % 2 else swapped
            return real(path, *args, **kwargs)
        with mock.patch.object(adaptor, 'bounded', flipping):
            fault = self.fault(lambda: adaptor.verify(directory, decoder=self.decoder), 'VERIFICATION_FAILED')
        self.assertIn('publication membership or digests differ from the receipt', fault.message)
        self.assertEqual(len(flips), 1)

    # ------------------------------------------------------------ decode failure of a well-framed payload
    def test_well_framed_corrupt_payload_is_a_verification_failure_with_the_original_cause(self):
        refusing = program(self.root, 'refusing-dwebp', DECODER, marker=REFUSE_ZEROED_PAYLOAD)
        directory, _ = self.publish()
        good = (directory / 'image.webp').read_bytes()
        corrupt = good[:25] + bytes(len(good) - 25)
        self.assertEqual((len(corrupt), corrupt[:25]), (len(good), good[:25]))
        self.assertEqual(adaptor.webp_header(corrupt)['width'], 7)    # framing and sizes stay valid
        (directory / 'image.webp').write_bytes(corrupt)
        refresh(directory)
        fault = self.fault(lambda: adaptor.verify(directory, decoder=refusing), 'VERIFICATION_FAILED')
        self.assertIn('do not decode', fault.message)
        self.assertEqual(fault.location, 'image.webp')
        self.assertEqual(fault.observed['cause']['code'], 'NATIVE_EXECUTION_FAILED')
        self.assertIn('BITSTREAM_ERROR', fault.observed['cause']['message'])
        (directory / 'image.webp').write_bytes(good)
        refresh(directory)
        self.assertTrue(adaptor.verify(directory, decoder=refusing)['verified'])

    def test_other_fresh_decode_faults_keep_their_own_codes(self):
        directory, _ = self.publish()
        newer = program(self.root, 'new-dwebp', DECODER.replace("print('1.6.0')", "print('1.7.0')"))
        self.fault(lambda: adaptor.verify(directory, decoder=newer), 'UNSUPPORTED_RUNTIME')
        self.fault(lambda: adaptor.verify(directory, decoder=str(self.root / 'missing-dwebp')), 'INTERPRETER_NOT_FOUND')
        slow = program(self.root, 'slow-dwebp', DECODER, marker='import time; time.sleep(30)')
        started = time.monotonic()
        with mock.patch.object(adaptor, 'VERIFY_TIMEOUT', 1):
            self.fault(lambda: adaptor.verify(directory, decoder=slow), 'RUNNER_TIMED_OUT')
        self.assertLess(time.monotonic() - started, 15)
        cancel = threading.Event()
        cancel.set()
        with allocation({'threads': 1, 'ranks': 1}, cancel):
            self.fault(lambda: adaptor.verify(directory, decoder=slow), 'RUNNER_CANCELLED')
        self.assertTrue(adaptor.verify(directory, decoder=self.decoder)['verified'])

    def test_run_stage_decode_failure_stays_an_execution_failure(self):
        refusing = program(self.root, 'refusing-dwebp', DECODER, marker='sys.stderr.write("cannot decode\\n"); sys.exit(1)')
        self.fault(lambda: adaptor.run(self.document, self.root / 'refused', executable=self.encoder, decoder=refusing, timeout=30), 'NATIVE_EXECUTION_FAILED')

    # ------------------------------------------------------------ output directory race
    def test_directory_that_appears_before_creation_is_output_exists(self):
        with mock.patch.object(Path, 'mkdir', side_effect=FileExistsError('raced')):
            fault = self.fault(lambda: adaptor.run(self.document, self.root / 'raced', executable=self.encoder, decoder=self.decoder, timeout=30), 'OUTPUT_EXISTS')
        self.assertEqual(fault.location, str(self.root / 'raced'))
        occupied = self.root / 'occupied'
        occupied.write_text('a file')
        self.fault(lambda: adaptor.run(self.document, occupied, executable=self.encoder, decoder=self.decoder, timeout=30), 'OUTPUT_EXISTS')

    # ------------------------------------------------------------ simulated stored decoder configuration
    def test_stored_decoder_location_verifies_and_isolation_hides_it_from_other_tests(self):
        directory, _ = self.publish()
        stored = {'webp': self.encoder, 'dwebp': self.decoder}
        with private_configuration(self.root, stored):
            self.assertTrue(adaptor.verify(directory)['verified'])
            with configuration.location_context({'dwebp': None}):    # None does not clear a stored location
                self.assertTrue(registry.verify(directory)['verified'])
            completed = subprocess.run([sys.executable, '-m', 'schemaxis', 'verify', str(directory)],
                                       env={**self.environment, 'SCHEMAXIS_CONFIG': os.environ['SCHEMAXIS_CONFIG']},
                                       capture_output=True, text=True, timeout=120)
            self.assertEqual(completed.returncode, 0, completed.stderr[-600:] + completed.stdout[-600:])
            self.assertTrue(json.loads(completed.stdout)['verified'])
        with private_configuration(self.root):
            self.fault(lambda: adaptor.verify(directory), 'INTERPRETER_NOT_FOUND')
            with configuration.location_context({'dwebp': None}):
                self.fault(lambda: registry.verify(directory), 'INTERPRETER_NOT_FOUND')

    def test_workflow_reuse_follows_captured_source_bytes(self):
        locations = {'webp': self.encoder, 'dwebp': self.decoder}
        graph = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'publish', 'document': self.document}]}
        directory = self.root / 'workflow'
        first = workflow.execute(graph, directory, locations=locations, timeout=60)
        self.assertEqual(first['status'], 'succeeded')
        with configuration.location_context(locations):
            self.assertTrue(workflow.verify(directory)['verified'])
        second = workflow.execute(graph, directory, locations=locations, timeout=60, resume=True)
        self.assertTrue(all(job['reused'] for job in second['jobs']))
        shutil.copyfile(FIXTURES / 'swatch-rgba-changed.png', self.source)
        third = workflow.execute(graph, directory, locations=locations, timeout=60, resume=True)
        self.assertTrue(all(not job['reused'] for job in third['jobs']))

    def test_imagemagick_png_artifact_handoff_plans_on_the_host(self):
        document = json.loads((ROOT / 'examples/schemaxis/webp-publish-workflow.json').read_text())
        planned = workflow.inspect_plan(document)
        publish = {entry['id']: entry for entry in planned['operations']}['publish']['provisionalPlan']
        self.assertEqual(publish['status'], 'deferred')
        self.assertEqual(publish['references'], [{'$artifact': 'prepare', 'index': 0}])
        jobs = {job['id']: job for job in planned['jobs']}
        self.assertEqual(jobs['publish/0']['dependencies'], ['prepare'])
        # An unrelated artifact kind is not accepted: the route declares only image publications.
        self.assertEqual(registry.ADAPTORS['webp']['routes']['schemaxis.webp/1']['acceptedArtifacts'], ['image'])


@unittest.skipUnless(os.environ.get('SCHEMAXIS_WEBP') and os.environ.get('SCHEMAXIS_DWEBP'), 'real cwebp/dwebp not configured: unqualified, see tools/qualify_webp.py')
class RealLibwebp(unittest.TestCase):
    def test_all_fixtures_roundtrip_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('swatch-rgba', 'swatch-rgb', 'landscape-rgba'):
                document = {'version': 'schemaxis.webp/1', 'operation': 'encodeLossless', 'source': str(FIXTURES / (name + '.png'))}
                directory = Path(tmp) / name
                self.assertTrue(adaptor.run(document, directory, executable=os.environ['SCHEMAXIS_WEBP'], decoder=os.environ['SCHEMAXIS_DWEBP'], timeout=60)['verified'])
                self.assertTrue(adaptor.verify(directory)['verified'])


if __name__ == '__main__':
    unittest.main()
