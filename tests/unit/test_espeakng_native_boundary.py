"""eSpeak NG run/verify boundaries with a deterministic HOST FAKE espeak-ng program (it makes no speech).

The fake derives a tone from the captured text and rate (see test_espeakng_fakes.py), so it proves host behaviour only: fixed
arguments, captured input, canonical WAV handling, forged evidence with every ordinary hash refreshed, receipts, trusted
executables, lifecycle and standard hooks. Native acceptance is tools/qualify_espeakng.py. Tests that need the real binary run only
when SCHEMAXIS_ESPEAKNG is set and are reported skipped otherwise.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
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
from schemaxis.adaptors.espeakng import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_espeakng import private_configuration   # noqa: E402
from test_espeakng_fakes import EN_US, HEADER, VERSION_TEXT, VOICES, make_data, program, synth_wav, tone_pcm, wav_bytes   # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'src'
TESTS = Path(__file__).resolve().parent
FIXTURES = ROOT / 'examples/schemaxis/fixtures/espeakng'
TEXT = 'Welcome to the plant tour. Please wear your safety glasses and stay behind the yellow line.'
EVIDENCE = ('authored.json', 'plan.json', 'captures.json', 'captured.txt', 'native.wav')


def rebind(directory):
    """Rebind only the receipt's artifact and evidence digests to the files as they now are."""
    directory = Path(directory)
    receipt = adaptor.read_json(directory, 'verification.json')
    receipt['evidence'] = {n: adaptor.digest(directory, n) for n in sorted(receipt['evidence'])}
    receipt['artifacts'] = adaptor.publications(directory)
    atomic_json(directory / 'verification.json', receipt)
    from schemaxis.publication_metadata import finalise
    finalise(directory)    # the shared publication manifest is rebound too, as a thorough forger would


def refresh(directory):
    """Make every ordinary hash agree with the (tampered) files, as a forging writer would."""
    directory = Path(directory)
    atomic_json(directory / 'narrate-inputs.json', {'captured.txt': adaptor.digest(directory, 'captured.txt')})
    rebind(directory)


def forge(directory, executable, *, text=None, rate=None):
    """A fully coherent rewrite: the plan, captured text, audio, launcher, summary, result and receipt all agree. Verification cannot catch it."""
    directory = Path(directory)
    authored = adaptor.read_json(directory, 'authored.json')
    if text is not None:
        authored['text'] = text
    if rate is not None:
        authored['rateWpm'] = rate
    prepared = adaptor.plan(authored)
    atomic_json(directory / 'authored.json', authored)
    atomic_json(directory / 'plan.json', prepared)
    capture = prepared['text'].encode('utf-8')
    (directory / 'captured.txt').write_bytes(capture)
    atomic_json(directory / 'captures.json', adaptor.capture_record(prepared, capture))
    wav = synth_wav(capture, prepared['rateWpm'])
    (directory / 'native.wav').write_bytes(wav)
    (directory / 'narration.wav').write_bytes(wav)
    command, names, limit = adaptor.stage_commands(prepared['rateWpm'], executable)['narrate']
    (directory / 'narrate-launcher.py').write_text(adaptor.launcher('narrate', names, command, limit))
    atomic_json(directory / 'narrate-inputs.json', {'captured.txt': adaptor.digest(directory, 'captured.txt')})
    receipt = adaptor.read_json(directory, 'verification.json')
    observation = adaptor.observe(directory, prepared, adaptor.runtime(executable), {}, {'identity': receipt['runtime']['espeakng'], 'dataFingerprint': receipt['runtime']['dataFingerprint']})
    atomic_json(directory / 'espeakng-summary.json', observation['summary'])
    rebind(directory)
    verified = adaptor.verify_semantic(directory, adaptor.runtime(executable), require_result=False)
    atomic_json(directory / 'result.json', {'status': 'succeeded', **verified})


def re_float(pattern):
    return lambda text: re.sub(pattern, lambda m: m.group(1) + m.group(2) + '.0', text, count=1, flags=re.S)


class FakeNativeBoundary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = make_data(self.root / 'data')
        self.log = self.root / 'argv.log'
        self.espeak = self.program('espeak-ng', log=str(self.log))
        self.script = self.root / 'script.txt'
        self.script_bytes = (FIXTURES / 'script-numbered.txt').read_bytes()
        self.script.write_bytes(self.script_bytes)
        self.literal = {'version': 'schemaxis.espeakng/1', 'operation': 'narrate', 'text': TEXT}
        self.file = {'version': 'schemaxis.espeakng/1', 'operation': 'narrate', 'source': str(self.script), 'rateWpm': 140}
        self.environment = {k: v for k, v in os.environ.items() if k not in ('SCHEMAXIS_ESPEAKNG', 'SCHEMAXIS_CONFIG')}
        (self.root / 'empty.json').write_text('{"version": 1, "locations": {}}')
        self.environment['SCHEMAXIS_CONFIG'] = str(self.root / 'empty.json')
        self.environment['PYTHONPATH'] = str(SRC)

    def program(self, name, **options):
        options.setdefault('data', self.data)
        return program(self.root, name, TESTS, **options)

    def fault(self, action, code):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    def publish(self, document, name='run', executable=None):
        directory = self.root / name
        return directory, adaptor.run(document, directory, executable=executable or self.espeak, timeout=60)

    def verify_fault(self, directory, code='VERIFICATION_FAILED', executable=None):
        return self.fault(lambda: adaptor.verify(directory, executable=executable or self.espeak), code)

    def invocations(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    # ------------------------------------------------------------ happy paths
    def test_literal_run_publishes_two_artifacts_and_verifies_fresh(self):
        directory, result = self.publish(self.literal)
        capture = TEXT.encode()
        pcm = tone_pcm(capture, 175)
        self.assertEqual(result, {'status': 'succeeded', 'verified': True, 'operation': 'narrate', 'artifacts': 2, 'audio': {'sampleRate': 22050, 'channels': 1, 'frames': len(pcm) // 2},
                                  'bytes': {'text': 91, 'wav': 44 + len(pcm)}, 'pcmSha256': hashlib.sha256(pcm).hexdigest(),
                                  'runtime': {'espeakng': 'eSpeak NG 1.52.0', 'dataFingerprint': adaptor.data_fingerprint(self.data)}})
        receipt = adaptor.read_json(directory, 'verification.json')
        self.assertEqual([(Path(a['file']).name, a['kind']) for a in receipt['artifacts']], [('narration.wav', 'file'), ('espeakng-summary.json', 'text')])
        self.assertEqual((directory / 'narration.wav').read_bytes(), wav_bytes(pcm))
        self.assertEqual((directory / 'captured.txt').read_bytes(), capture)
        summary = adaptor.read_json(directory, 'espeakng-summary.json')
        self.assertEqual(summary['source'], {'kind': 'literal', 'file': 'captured.txt', 'bytes': 91, 'sha256': hashlib.sha256(capture).hexdigest(), 'codePoints': 91, 'lines': 1})
        self.assertEqual(summary['voice'], {'requested': 'en-us', 'listing': {'language': 'en-us', 'name': 'English_(America)', 'file': 'gmw/en-US'}, 'rateWpm': 175, 'pitch': 50,
                                            'amplitude': 100, 'inputEncoding': 'UTF-8 (-b1)'})
        self.assertEqual((summary['audio']['frames'], summary['audio']['durationSeconds']), (len(pcm) // 2, len(pcm) / 2 / 22050))
        samples = struct.unpack('<%dh' % (len(pcm) // 2), pcm)
        self.assertEqual(summary['pcm'], {'bytes': len(pcm), 'sha256': hashlib.sha256(pcm).hexdigest(), 'peakAbs': max(abs(sample) for sample in samples),
                                          'nonzeroSamples': sum(1 for sample in samples if sample)})
        self.assertEqual(summary['runtime'], {'identity': 'eSpeak NG 1.52.0', 'dataFingerprint': adaptor.data_fingerprint(self.data)})
        self.assertEqual(summary['review'], adaptor.REVIEW)
        self.assertIn('not a human recording', summary['review'])
        self.assertTrue(adaptor.verify(directory, executable=self.espeak)['verified'])
        for public in (summary, receipt['artifacts']):
            text = json.dumps(public)
            self.assertNotIn(self.data, text.replace(str(directory), ''))      # no native data path in public summary
        self.assertNotIn(self.data, json.dumps(summary))
        self.assertIn(self.data, (directory / 'version.stdout').read_text())      # the data directory stays in private evidence
        launcher = (directory / 'narrate-launcher.py').read_text()
        self.assertIn("'-ven-us', '-s175', '-p50', '-a100', '-b1', '-w', 'native.wav', '-f', 'captured.txt']", launcher)
        self.assertIn('{"LANG":"C.UTF-8","LC_ALL":"C.UTF-8"}', launcher)

    def test_native_receives_only_the_three_fixed_stages(self):
        directory, _ = self.publish(self.literal)
        narrate = ['-ven-us', '-s175', '-p50', '-a100', '-b1', '-w', 'native.wav', '-f', 'captured.txt']
        fixed = [['--version'], ['--voices=en'], narrate]
        invoked = self.invocations()
        self.assertEqual(invoked[:3], fixed)                                         # the run itself, in the run directory
        self.assertEqual(len(invoked) % 3, 0)
        self.assertEqual(invoked, fixed * (len(invoked) // 3))                      # then fresh verification syntheses, never anything else
        before = len(invoked)
        adaptor.verify(directory, executable=self.espeak)
        self.assertEqual(self.invocations()[before:], fixed)                        # standalone verification: exactly one fresh synthesis

    def test_file_run_binds_captured_bytes_not_the_original_file(self):
        directory, result = self.publish(self.file)
        self.assertEqual((directory / 'captured.txt').read_bytes(), self.script_bytes)
        captures = adaptor.read_json(directory, 'captures.json')
        self.assertEqual(captures, {'kind': 'file', 'bytes': 173, 'sha256': hashlib.sha256(self.script_bytes).hexdigest(), 'source': str(self.script)})
        summary = adaptor.read_json(directory, 'espeakng-summary.json')
        self.assertEqual((summary['source']['kind'], summary['source']['codePoints'], summary['source']['bytes'], summary['source']['lines'], summary['voice']['rateWpm']), ('file', 169, 173, 3, 140))
        self.assertEqual(result['bytes']['text'], 173)
        self.script.write_bytes(b'Something else entirely.\n')            # the original changes after the run
        self.assertTrue(adaptor.verify(directory, executable=self.espeak)['verified'])
        self.script.unlink()
        self.assertTrue(adaptor.verify(directory, executable=self.espeak)['verified'])

    def test_rates_reach_the_native_arguments_and_change_the_sound(self):
        sums = set()
        for rate in (120, 175, 240):
            directory, result = self.publish({**self.literal, 'rateWpm': rate}, 'rate-%d' % rate)
            self.assertIn('-s%d' % rate, (directory / 'narrate-launcher.py').read_text())
            self.assertEqual(adaptor.read_json(directory, 'espeakng-summary.json')['voice']['rateWpm'], rate)
            sums.add(result['pcmSha256'])
        self.assertEqual(len(sums), 3)
        self.assertIn(['-ven-us', '-s120', '-p50', '-a100', '-b1', '-w', 'native.wav', '-f', 'captured.txt'], self.invocations())
        self.assertIn(['-ven-us', '-s240', '-p50', '-a100', '-b1', '-w', 'native.wav', '-f', 'captured.txt'], self.invocations())

    def test_utf8_and_line_feeds_reach_the_native_file_unchanged(self):
        text = 'Le café est ouvert.\nLa résumé est naïve.\n'
        directory, _ = self.publish({**self.literal, 'text': text})
        self.assertEqual((directory / 'captured.txt').read_bytes(), text.encode('utf-8'))
        self.assertEqual(adaptor.read_json(directory, 'espeakng-summary.json')['source']['lines'], 2)
        self.assertEqual(adaptor.read_json(directory, 'narrate-inputs.json'), {'captured.txt': hashlib.sha256(text.encode()).hexdigest()})

    def test_repeated_runs_are_byte_identical_for_a_deterministic_runtime(self):
        first, _ = self.publish(self.literal, 'one')
        second, _ = self.publish(self.literal, 'two')
        self.assertEqual((first / 'narration.wav').read_bytes(), (second / 'narration.wav').read_bytes())
        self.assertEqual((first / 'espeakng-summary.json').read_bytes(), (second / 'espeakng-summary.json').read_bytes())
        changed, _ = self.publish({**self.literal, 'text': TEXT.replace('yellow', 'orange')}, 'three')
        self.assertNotEqual((first / 'narration.wav').read_bytes(), (changed / 'narration.wav').read_bytes())

    # ------------------------------------------------------------ hostile outputs with every hash refreshed
    def test_changed_published_audio_is_rejected_even_when_every_hash_is_refreshed(self):
        directory, _ = self.publish(self.literal)
        good = (directory / 'narration.wav').read_bytes()
        pcm = good[44:]
        other = tone_pcm(TEXT.replace('yellow', 'orange').encode(), 175)
        flipped = bytearray(pcm)
        flipped[1000] ^= 0x10
        cases = (('sample changed', wav_bytes(bytes(flipped)), 'does not equal fresh native re-synthesis (first difference at sample 500)'),
                 ('different words, same length', wav_bytes(other), 'does not equal fresh native re-synthesis'),
                 ('shorter', wav_bytes(pcm[:-2]), 'lengths differ'), ('longer', wav_bytes(pcm + b'\x01\x00'), 'lengths differ'),
                 ('header rate', good[:24] + struct.pack('<I', 44100) + good[28:], 'ESPEAKNG_OUTPUT_REJECTED'),
                 ('extra chunk', wav_bytes(pcm, extra=b'LIST' + struct.pack('<I', 4) + b'INFO'), 'ESPEAKNG_OUTPUT_REJECTED'),
                 ('trailing byte', good + b'\0', 'ESPEAKNG_OUTPUT_REJECTED'), ('silence', wav_bytes(bytes(len(pcm))), 'ESPEAKNG_SILENT_OUTPUT'),
                 ('stereo', wav_bytes(pcm, channels=2), 'ESPEAKNG_OUTPUT_REJECTED'), ('empty', b'', 'ESPEAKNG_OUTPUT_REJECTED'))
        for label, forged, message in cases:
            with self.subTest(label):
                (directory / 'narration.wav').write_bytes(forged)
                refresh(directory)
                fault = self.verify_fault(directory)
                self.assertIn(message, fault.message)
                self.assertEqual(fault.location, 'narration.wav')
        (directory / 'narration.wav').write_bytes(good)
        refresh(directory)
        self.assertTrue(adaptor.verify(directory, executable=self.espeak)['verified'])

    def test_changed_retained_native_output_is_rejected_even_when_every_hash_is_refreshed(self):
        directory, _ = self.publish(self.literal)
        good = (directory / 'native.wav').read_bytes()
        (directory / 'native.wav').write_bytes(wav_bytes(tone_pcm(b'a different narration entirely', 175)))
        refresh(directory)
        fault = self.verify_fault(directory)
        self.assertIn('retained run output does not equal fresh native re-synthesis', fault.message)
        (directory / 'native.wav').write_bytes(good)
        refresh(directory)
        self.assertTrue(adaptor.verify(directory, executable=self.espeak)['verified'])

    def test_changed_words_or_rate_are_caught_unless_every_record_and_the_audio_are_rewritten(self):
        directory, _ = self.publish(self.literal)
        saved = {p: p.read_bytes() for p in directory.rglob('*') if p.is_file()}

        def restore():
            for path, data in saved.items():
                path.write_bytes(data)
        # words changed in the captured text and its capture record only: the literal authored text no longer matches
        words = TEXT.replace('yellow', 'orange').encode()
        (directory / 'captured.txt').write_bytes(words)
        atomic_json(directory / 'captures.json', {'kind': 'literal', 'bytes': len(words), 'sha256': adaptor.sha(words)})
        refresh(directory)
        self.assertIn('captured text differs from the authored literal text', self.verify_fault(directory).message)
        # words changed coherently in the authored text, plan, capture and bindings, but the audio is the old sound
        authored = {**self.literal, 'text': TEXT.replace('yellow', 'orange')}
        atomic_json(directory / 'authored.json', authored)
        atomic_json(directory / 'plan.json', adaptor.plan(authored))
        refresh(directory)
        self.assertIn('does not equal fresh native re-synthesis', self.verify_fault(directory).message)
        restore()
        # the declared rate changed in the authored input and plan: the launcher, summary and audio still describe 175
        authored = {**self.literal, 'rateWpm': 200}
        atomic_json(directory / 'authored.json', authored)
        atomic_json(directory / 'plan.json', adaptor.plan(authored))
        refresh(directory)
        self.verify_fault(directory)
        restore()
        # a coherent rewrite of everything (the documented unauthenticated trust anchor) is not detected, and says so
        forge(directory, self.espeak, text=TEXT.replace('yellow', 'orange'))
        self.assertTrue(adaptor.verify(directory, executable=self.espeak)['verified'])
        self.assertIn('orange', (directory / 'captured.txt').read_text())
        forge(directory, self.espeak, rate=200)
        self.assertEqual(adaptor.verify(directory, executable=self.espeak)['audio']['frames'], len(tone_pcm(TEXT.replace('yellow', 'orange').encode(), 200)) // 2)
        self.assertIn('unauthenticated trust anchor', adaptor.read_json(directory, 'espeakng-summary.json')['verification'])

    def test_retained_captured_text_that_no_longer_meets_the_profile_is_a_verification_failure(self):
        directory, _ = self.publish(self.file)
        forged = b'one\r\ntwo\r\n'
        (directory / 'captured.txt').write_bytes(forged)
        atomic_json(directory / 'captures.json', {**adaptor.read_json(directory, 'captures.json'), 'bytes': len(forged), 'sha256': adaptor.sha(forged)})
        refresh(directory)
        fault = self.verify_fault(directory)
        self.assertEqual(fault.observed['cause']['code'], 'INVALID_ESPEAKNG_TEXT')

    def test_retained_evidence_is_bound_without_refresh(self):
        directory, _ = self.publish(self.literal)
        saved = {p: p.read_bytes() for p in directory.rglob('*') if p.is_file()}
        for name, change in (('narration.wav', lambda b: b[:-2] + b'\x01\x01'), ('native.wav', lambda b: b[:-2] + b'\x01\x01'), ('espeakng-summary.json', lambda b: b.replace(b'"pcmIdentical": true', b'"pcmIdentical": false')),
                             ('captured.txt', lambda b: b.replace(b'yellow', b'orange')), ('narrate-launcher.py', lambda b: b.replace(b'-s175', b'-s176')), ('version-launcher.py', lambda b: b + b'#'),
                             ('voices-launcher.py', lambda b: b + b'#'), ('version.stdout', lambda b: b.replace(b'1.52.0', b'1.53.0')), ('voices.stdout', lambda b: b.replace(b'English_(America)', b'English_(Canada)')),
                             ('narrate.stderr', lambda b: b'noise'), ('narrate.stdout', lambda b: b'noise'), ('version.stderr', lambda b: b'noise'),
                             ('verification.json', lambda b: b.replace(b'"artifacts"', b'"artefacts"')), ('plan.json', lambda b: b.replace(b'175', b'176')),
                             ('narrate-submission.json', lambda b: b.replace(b'"exitCode": 0', b'"exitCode": 1')), ('version-submission.json', lambda b: b.replace(b'"exitCode": 0', b'"exitCode": 9')),
                             ('narrate-inputs.json', lambda b: b.replace(b'0', b'1', 1)), ('version-inputs.json', lambda b: b'{"x": "0"}'),
                             ('captures.json', lambda b: b.replace(b'"bytes": ', b'"bytes": 1')), ('result.json', lambda b: b.replace(b'"verified": true', b'"verified": false')),
                             ('authored.json', lambda b: b.replace(b'Welcome', b'Goodbye'))):
            with self.subTest(name):
                try:
                    path = directory / name
                    path.write_bytes(change(path.read_bytes()))
                    self.assertNotEqual(path.read_bytes(), saved[path], name)
                    code = 'INVALID_SCHEMA_SNAPSHOT' if name == 'authored.json' else 'VERIFICATION_FAILED'
                    with self.assertRaises(SchemaxisError) as caught:
                        adaptor.verify(directory, executable=self.espeak)
                    self.assertIn(caught.exception.fault.code, (code, 'VERIFICATION_FAILED', 'UNSUPPORTED_RUNTIME'), (name, caught.exception.fault.to_dict()))
                finally:
                    for path, data in saved.items():
                        path.write_bytes(data)
        receipt = adaptor.read_json(directory, 'verification.json')
        for label, mutate in (('membership', lambda r: r['artifacts'].pop()), ('evidence', lambda r: r['evidence'].pop('narrate.stdout')),
                              ('extra', lambda r: r['evidence'].update({'unowned.json': '0' * 64})), ('runtime name', lambda r: r['runtime'].update(espeakng='eSpeak NG 9.9.9')),
                              ('runtime fingerprint', lambda r: r['runtime'].update(dataFingerprint='0' * 64)), ('runtime extra', lambda r: r['runtime'].update(certified=True)),
                              ('runtime shape', lambda r: r.update(runtime=[])), ('executables', lambda r: r.update(executables={'espeakng': 'relative/espeak-ng'})),
                              ('executables extra', lambda r: r['executables'].update(other='/bin/true'))):
            with self.subTest(label):
                try:
                    changed = copy.deepcopy(receipt)
                    mutate(changed)
                    atomic_json(directory / 'verification.json', changed)
                    self.verify_fault(directory)
                finally:
                    atomic_json(directory / 'verification.json', receipt)
        self.assertTrue(adaptor.verify(directory, executable=self.espeak)['verified'])

    def test_unreferenced_files_are_refused(self):
        directory, _ = self.publish(self.literal)
        (directory / 'stray.txt').write_text('x')
        self.assertIn('stray.txt', self.verify_fault(directory).message)
        (directory / 'stray.txt').unlink()
        (directory / 'link.wav').symlink_to(directory / 'narration.wav')
        self.verify_fault(directory)
        (directory / 'link.wav').unlink()
        (directory / 'core').mkdir()
        self.verify_fault(directory)
        (directory / 'core').rmdir()
        self.assertTrue(adaptor.verify(directory, executable=self.espeak)['verified'])

    # ------------------------------------------------------------ trusted espeak-ng only
    def test_verification_requires_the_trusted_runtime_and_never_runs_a_receipt_path_or_path_entry(self):
        marker = self.root / 'executed.marker'
        directory, _ = self.publish(self.literal)
        trap = self.program('trap-espeak-ng', marker='open(%r, "w").write("ran")' % str(marker))
        receipt = adaptor.read_json(directory, 'verification.json')
        receipt['executables']['espeakng'] = trap
        atomic_json(directory / 'verification.json', receipt)
        bin_directory = self.root / 'bin'
        bin_directory.mkdir()
        decoy = bin_directory / 'espeak-ng'
        decoy.write_text(Path(trap).read_text())
        decoy.chmod(0o700)
        with private_configuration(), mock.patch.dict(os.environ, {'PATH': str(bin_directory) + os.pathsep + os.environ.get('PATH', '')}):
            fault = self.fault(lambda: adaptor.verify(directory), 'INTERPRETER_NOT_FOUND')
            self.assertEqual(fault.location, '$.runtime.espeakng')
            self.assertFalse(marker.exists())
            refresh(directory)    # the receipt names another executable, so the recomputed launchers differ
            self.verify_fault(directory)
            self.assertFalse(marker.exists())
        for bad in ('espeak-ng', str(self.root / 'missing'), str(self.script)):
            self.fault(lambda: adaptor.verify(directory, executable=bad), 'INTERPRETER_NOT_FOUND')

    def test_unsupported_runtimes_stop_before_synthesis(self):
        for name, options, code, location in (('old', {'version': VERSION_TEXT.replace('1.52.0', '1.51.0') % self.data}, 'UNSUPPORTED_RUNTIME', 'version'),
                                              ('newer', {'version': VERSION_TEXT.replace('1.52.0', '1.52.1') % self.data}, 'UNSUPPORTED_RUNTIME', 'version'),
                                              ('no data', {'version': VERSION_TEXT % (self.root / 'absent')}, 'UNSUPPORTED_RUNTIME', 'version'),
                                              ('no en-us', {'voices': HEADER + ' 2  en-gb           --/M      English_(Great_Britain) gmw/en               (en 2)\n'}, 'UNSUPPORTED_RUNTIME', 'voices'),
                                              ('wrong en-us', {'voices': HEADER + ' 2  en-us           --/M      English_(Canada)   gmw/en-CA            (en 3)\n'}, 'UNSUPPORTED_RUNTIME', 'voices')):
            with self.subTest(name):
                executable = self.program(name + '-espeak-ng', **options)
                fault = self.fault(lambda: adaptor.run(self.literal, self.root / name, executable=executable, timeout=30), code)
                self.assertEqual(fault.location, location)
                self.assertFalse((self.root / name / 'narrate-submission.json').exists())
                self.assertFalse((self.root / name / 'narration.wav').exists())
                self.assertEqual(adaptor.read_json(self.root / name, 'result.json')['status'], 'failed')
        incomplete = self.root / 'incomplete-data'
        make_data(incomplete)
        (incomplete / 'en_dict').unlink()
        self.fault(lambda: adaptor.run(self.literal, self.root / 'incomplete', executable=self.program('incomplete-espeak-ng', data=str(incomplete)), timeout=30), 'UNSUPPORTED_RUNTIME')
        directory, _ = self.publish(self.literal)
        newer = self.program('verify-newer', version=VERSION_TEXT.replace('1.52.0', '1.52.1') % self.data)
        self.verify_fault(directory, 'UNSUPPORTED_RUNTIME', newer)

    def test_a_different_runtime_or_native_data_is_reported_with_the_matching_runtime_hint(self):
        directory, _ = self.publish(self.literal)
        other = make_data(self.root / 'other-data', tag=b'-updated')
        same_sound = self.program('other-data-espeak-ng', data=other)             # identical PCM, different data
        fault = self.verify_fault(directory, executable=same_sound)
        self.assertIn('although the PCM agrees', fault.message)
        self.assertIn('matching runtime and data', fault.message)
        self.assertEqual(fault.location, 'version')
        changed_sound = self.program('changed-espeak-ng', data=other, marker='rate += 7')            # different PCM, different data
        fault = self.verify_fault(directory, executable=changed_sound)
        self.assertIn('does not equal fresh native re-synthesis', fault.message)
        self.assertIn('differs from the recorded ones', fault.message)
        self.assertIn('matching runtime and data', fault.message)
        regression = self.program('regressed-espeak-ng', marker='rate += 7')                   # same data, different PCM: a genuine mismatch, no hint
        fault = self.verify_fault(directory, executable=regression)
        self.assertIn('does not equal fresh native re-synthesis', fault.message)
        self.assertNotIn('differs from the recorded ones', fault.message)
        self.assertTrue(adaptor.verify(directory, executable=self.espeak)['verified'])

    def test_source_faults_stop_before_any_native_launch(self):
        cases = []
        long_text = self.root / 'long.txt'
        long_text.write_bytes(b'word ' * 300)
        for label, name, data, code in (('crlf', 'a.txt', b'one\r\ntwo\r\n', 'INVALID_ESPEAKNG_TEXT'), ('latin-1', 'a.txt', 'café'.encode('latin-1'), 'INVALID_ESPEAKNG_TEXT'),
                                        ('markup', 'a.txt', b'<speak>hi</speak>', 'INVALID_ESPEAKNG_TEXT'), ('phoneme', 'a.txt', b'[[h@l]] there', 'INVALID_ESPEAKNG_TEXT'),
                                        ('punctuation', 'a.txt', b'... ?!', 'INVALID_ESPEAKNG_TEXT'), ('empty', 'a.txt', b'', 'INVALID_ESPEAKNG_TEXT'),
                                        ('long', 'a.txt', b'word ' * 300, 'ESPEAKNG_BUDGET'), ('huge', 'a.txt', b'x' * 9000, 'ESPEAKNG_BUDGET')):
            (self.root / name).write_bytes(data)
            target = self.root / ('refused-' + label)
            fault = self.fault(lambda: adaptor.run({**self.file, 'source': str(self.root / name)}, target, executable=self.espeak, timeout=30), code)
            self.assertEqual(fault.location, '$.source', label)
            self.assertFalse((target / 'version-submission.json').exists(), label)
            self.assertEqual(adaptor.read_json(target, 'result.json')['status'], 'failed')
            cases.append(label)
        self.assertEqual(len(cases), 8)
        self.assertFalse(self.log.exists())                                       # no native process ever started
        self.fault(lambda: adaptor.run(self.literal, self.root / 'zero', executable=self.espeak, timeout=0), 'INVALID_ARGUMENT')
        self.fault(lambda: adaptor.run({**self.file, 'source': str(self.root / 'absent.txt')}, self.root / 'absent', executable=self.espeak, timeout=30), 'INVALID_ESPEAKNG_SOURCE')
        self.fault(lambda: adaptor.run({**self.literal, 'text': 'x[[y]]'}, self.root / 'phoneme', executable=self.espeak, timeout=30), 'INVALID_ESPEAKNG_TEXT')
        self.assertFalse((self.root / 'phoneme').exists())                         # plan faults create nothing
        self.assertFalse(self.log.exists())

    # ------------------------------------------------------------ native failures and output validation
    def test_native_failures_are_structured_and_leave_no_unverified_publication(self):
        for label, options, code, message in (
                ('failing', {'marker': 'sys.stderr.write("Failed to read file\\n"); sys.exit(3)'}, 'NATIVE_EXECUTION_FAILED', 'exit 3'),
                ('noisy', {'marker': 'sys.stderr.write("WARNING: something\\n")'}, 'NATIVE_EXECUTION_FAILED', 'unexpected output'),
                ('no output file', {'transform': 'None'}, 'ESPEAKNG_SILENT_OUTPUT', 'no audio'),
                ('silent', {'transform': 'wav_bytes(bytes(40000))'}, 'ESPEAKNG_SILENT_OUTPUT', 'only silence'),
                ('wrong rate', {'transform': 'wav_bytes(tone_pcm(text, rate), rate=44100)'}, 'ESPEAKNG_OUTPUT_REJECTED', '44100 Hz'),
                ('stereo', {'transform': 'wav_bytes(tone_pcm(text, rate), channels=2)'}, 'ESPEAKNG_OUTPUT_REJECTED', '2 channel'),
                ('extra chunk', {'transform': 'wav_bytes(tone_pcm(text, rate), extra=b"LIST" + bytes([4, 0, 0, 0]) + b"INFO")'}, 'ESPEAKNG_OUTPUT_REJECTED', 'chunk layout'),
                ('truncated header', {'transform': 'wav[:30]'}, 'ESPEAKNG_OUTPUT_REJECTED', 'shorter than a 44-byte header'),
                ('too long', {'transform': 'synth_wav(text, rate, 121)'}, 'ESPEAKNG_BUDGET', '120 seconds'),
                ('too large', {'transform': 'wav_bytes(b"\\x01\\x00" * (4 * 1024 * 1024 + 1))'}, 'ESPEAKNG_BUDGET', 'larger than'),
                ('runaway', {'transform': 'b"\\x01\\x00" * (10 * 1024 * 1024)'}, 'ESPEAKNG_BUDGET', 'runaway guard')):
            with self.subTest(label):
                executable = self.program(label.replace(' ', '-') + '-espeak-ng', **options)
                target = self.root / ('native-' + label.replace(' ', '-'))
                fault = self.fault(lambda: adaptor.run(self.literal, target, executable=executable, timeout=60), code)
                self.assertIn(message, fault.message)
                self.assertEqual(adaptor.read_json(target, 'result.json')['status'], 'failed')
                for name in ('narration.wav', 'espeakng-summary.json', 'verification.json'):
                    self.assertFalse((target / name).exists(), (label, name))
                self.assertFalse((target / 'core').exists())
        failing = adaptor.read_json(self.root / 'native-failing', 'result.json')
        self.assertEqual(failing['fault']['code'], 'NATIVE_EXECUTION_FAILED')

    def test_output_at_the_budget_edges_is_accepted(self):
        executable = self.program('edge-espeak-ng', transform='synth_wav(text, rate, 120)')
        directory, result = self.publish(self.literal, 'edge', executable)
        self.assertEqual(result['audio']['frames'], 120 * 22050)
        self.assertEqual(adaptor.read_json(directory, 'espeakng-summary.json')['audio']['durationSeconds'], 120.0)

    def test_timeout_and_cancellation_terminate_the_owned_process(self):
        marker = self.root / 'slow.pid'
        slow = self.program('slow-espeak-ng', marker='import os, time\nopen(%r, "w").write(str(os.getpid()))\ntime.sleep(30)' % str(marker))
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
                    self.fault(lambda: adaptor.run(self.literal, self.root / ('inflight-' + action), executable=slow, timeout=10 if thread else 2),
                               'RUNNER_CANCELLED' if thread else 'RUNNER_TIMED_OUT')
            finally:
                if thread:
                    thread.join(10)
            self.assertTrue(marker.exists())
            with self.assertRaises(ProcessLookupError):
                os.kill(int(marker.read_text()), 0)
            self.assertFalse((self.root / ('inflight-' + action) / 'narration.wav').exists())
            self.assertEqual(adaptor.read_json(self.root / ('inflight-' + action), 'result.json')['status'], 'failed')

    def test_verification_timeout_and_cancellation_keep_their_own_codes(self):
        directory, _ = self.publish(self.literal)
        slow = self.program('slow-verify-espeak-ng', marker='import time; time.sleep(30)')
        started = time.monotonic()
        with mock.patch.object(adaptor, 'VERIFY_TIMEOUT', 2):
            self.verify_fault(directory, 'RUNNER_TIMED_OUT', slow)
        self.assertLess(time.monotonic() - started, 20)
        cancel = threading.Event()
        cancel.set()
        with allocation({'threads': 1, 'ranks': 1}, cancel):
            self.verify_fault(directory, 'RUNNER_CANCELLED')
        self.assertTrue(adaptor.verify(directory, executable=self.espeak)['verified'])

    def test_directory_that_appears_before_creation_is_output_exists(self):
        with mock.patch.object(Path, 'mkdir', side_effect=FileExistsError('raced')):
            fault = self.fault(lambda: adaptor.run(self.literal, self.root / 'raced', executable=self.espeak, timeout=30), 'OUTPUT_EXISTS')
        self.assertEqual(fault.location, str(self.root / 'raced'))
        occupied = self.root / 'occupied'
        occupied.write_text('a file')
        self.fault(lambda: adaptor.run(self.literal, occupied, executable=self.espeak, timeout=30), 'OUTPUT_EXISTS')
        self.assertEqual(occupied.read_text(), 'a file')
        self.publish(self.literal, 'fresh')
        self.fault(lambda: self.publish(self.literal, 'fresh'), 'OUTPUT_EXISTS')
        link = self.root / 'link'
        link.symlink_to(self.root / 'fresh')
        self.fault(lambda: adaptor.run(self.literal, link, executable=self.espeak, timeout=30), 'OUTPUT_EXISTS')

    def test_failed_runs_clean_their_private_temporary_directories(self):
        temporary_directory = tempfile.TemporaryDirectory
        owned = []

        def record_scratch(*args, **kwargs):
            scratch = temporary_directory(*args, **kwargs)
            if kwargs.get('prefix') == 'schemaxis-espeakng-':
                owned.append(Path(scratch.name))
            return scratch

        # Other test processes may be synthesising speech in the same system
        # temporary directory. Check only the scratch directories we create.
        with mock.patch.object(adaptor.tempfile, 'TemporaryDirectory', side_effect=record_scratch):
            directory, _ = self.publish(self.literal)
            broken = self.program('broken-verify-espeak-ng', marker='sys.exit(5)')
            before_verify = len(owned)
            self.verify_fault(directory, executable=broken)
        self.assertGreater(len(owned), before_verify, 'verification must create a private synthesis directory')
        self.assertEqual([path for path in owned if path.exists()], [])

    # ------------------------------------------------------------ retained JSON, typed and strict
    def test_typed_duplicate_and_nonfinite_retained_json_is_refused_with_every_hash_refreshed(self):
        directory, _ = self.publish(self.literal)
        saved = {p: p.read_bytes() for p in directory.rglob('*') if p.is_file()}

        def first(old, new):
            def edit(text):
                self.assertEqual(text.count(old), 1, old)
                return text.replace(old, new)
            return edit

        def leading(entry):
            return lambda text: '{' + entry + ', ' + text.lstrip()[1:]
        cases = [
            ('espeakng-summary.json', first('"pcmIdentical": true', '"pcmIdentical": 1'), True, 'summary differs'),
            ('espeakng-summary.json', re_float(r'("audio": \{[^}]*?"channels": )(\d+)'), True, 'summary differs'),
            ('espeakng-summary.json', re_float(r'("voice": \{.*?"rateWpm": )(\d+)'), True, 'summary differs'),
            ('espeakng-summary.json', first('"pcmIdentical": true', '"pcmIdentical": false, "pcmIdentical": true'), False, 'duplicate JSON key'),
            ('espeakng-summary.json', first('"pcmIdentical": true', '"pcmIdentical": NaN'), False, 'non-finite'),
            ('espeakng-summary.json', first('"pcmIdentical": true', '"pcmIdentical": 1e400'), False, 'non-finite'),
            ('plan.json', leading('"operation": "narrate"'), False, 'duplicate JSON key'),
            ('plan.json', re_float(r'("rateWpm": )(\d+)'), True, 'retained plan differs'),
            ('captures.json', re_float(r'("bytes": )(\d+)'), True, 'capture record differs'),
            ('captures.json', leading('"bytes": 1'), False, 'duplicate JSON key'),
            ('narrate-inputs.json', leading('"captured.txt": "0"'), False, 'duplicate JSON key'),
            ('version-inputs.json', lambda text: '{"x": "0", "x": "1"}', False, 'duplicate JSON key'),
            ('narrate-submission.json', first('"exitCode": 0', '"exitCode": 0.0'), True, 'completion record differs'),
            ('narrate-submission.json', first('"exitCode": 0', '"exitCode": false'), True, 'completion record differs'),
            ('authored.json', leading('"operation": "narrate"'), False, 'duplicate JSON key'),
            ('result.json', first('"verified": true', '"verified": 1'), True, 'result claims differ'),
            ('result.json', first('"artifacts": 2', '"artifacts": 2.0'), True, 'result claims differ'),
            ('result.json', re_float(r'("audio": \{[^}]*?"frames": )(\d+)'), True, 'result claims differ'),
            ('result.json', leading('"status": "failed"'), False, 'duplicate JSON key'),
            ('verification.json', leading('"extra": NaN'), False, 'non-finite'),
            ('verification.json', leading('"extra": 1e400'), False, 'non-finite'),
            ('verification.json', first('"narrate.stdout"', '"narrate.stdout": "0", "narrate.stdout"'), False, 'duplicate JSON key'),
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
                    fault = self.verify_fault(directory, 'INVALID_SCHEMA_SNAPSHOT' if name == 'authored.json' else 'VERIFICATION_FAILED')
                    self.assertIn(message, fault.message, (name, fault.message))
                finally:
                    for path, data in saved.items():
                        path.write_bytes(data)
        self.assertTrue(adaptor.verify(directory, executable=self.espeak)['verified'])

    def test_result_claims_must_be_succeeded_and_typed_when_a_result_is_required(self):
        directory, result = self.publish(self.file)
        recorded = adaptor.read_json(directory, 'result.json')
        self.assertEqual({k: recorded[k] for k in ('status', 'verified', 'artifacts', 'operation')}, {'status': 'succeeded', 'verified': True, 'artifacts': 2, 'operation': 'narrate'})
        for label, mutate, code in (('failed', lambda r: r.update(status='failed'), 'INCOMPLETE_EXECUTION'), ('status type', lambda r: r.update(status=['succeeded']), 'INCOMPLETE_EXECUTION'),
                                    ('frames', lambda r: r['audio'].update(frames=1), 'VERIFICATION_FAILED'), ('frame type', lambda r: r['audio'].update(frames=float(r['audio']['frames'])), 'VERIFICATION_FAILED'),
                                    ('bytes', lambda r: r['bytes'].update(wav=1), 'VERIFICATION_FAILED'), ('sha', lambda r: r.update(pcmSha256='0' * 64), 'VERIFICATION_FAILED'),
                                    ('runtime claim', lambda r: r['runtime'].update(espeakng='eSpeak NG 1.52.9'), 'VERIFICATION_FAILED'),
                                    ('fingerprint', lambda r: r['runtime'].update(dataFingerprint='0' * 64), 'VERIFICATION_FAILED'),
                                    ('extra promotion', lambda r: r.update(intelligibilityCertified=True), 'VERIFICATION_FAILED'),
                                    ('accessibility claim', lambda r: r.update(accessible=True), 'VERIFICATION_FAILED'),
                                    ('extra runtime field', lambda r: r['runtime'].update(accentCertified=True), 'VERIFICATION_FAILED'),
                                    ('malformed runtime', lambda r: r.update(runtime=[]), 'VERIFICATION_FAILED'), ('removed claim', lambda r: r.pop('pcmSha256'), 'VERIFICATION_FAILED')):
            changed = copy.deepcopy(recorded)
            mutate(changed)
            atomic_json(directory / 'result.json', changed)
            self.verify_fault(directory, code)
            self.assertTrue(adaptor.verify(directory, require_result=False, executable=self.espeak)['verified'], label)
        (directory / 'result.json').write_text('[]')
        self.verify_fault(directory, 'INCOMPLETE_EXECUTION')
        atomic_json(directory / 'result.json', recorded)
        self.assertTrue(adaptor.verify(directory, executable=self.espeak)['verified'])

    # ------------------------------------------------------------ one snapshot of the published WAV
    def test_verify_reads_the_published_wav_once_and_binds_the_receipt_to_that_snapshot(self):
        directory, _ = self.publish(self.literal)
        wav_path = directory / 'narration.wav'
        original = wav_path.read_bytes()
        swapped = wav_bytes(tone_pcm(b'a different file than the one that was compared', 175))
        real = adaptor.bounded
        reads = []

        def reading(path, *args, **kwargs):
            if Path(path) == wav_path:
                reads.append(path)
            return real(path, *args, **kwargs)
        with mock.patch.object(adaptor, 'bounded', reading):
            self.assertTrue(adaptor.verify(directory, executable=self.espeak)['verified'])
        self.assertEqual(len(reads), 1)
        receipt = adaptor.read_json(directory, 'verification.json')
        receipt['artifacts'][0]['sha256'] = adaptor.sha(swapped)
        atomic_json(directory / 'verification.json', receipt)
        flips = []

        def flipping(path, *args, **kwargs):
            if Path(path) == wav_path:
                flips.append(path)
                return original if len(flips) % 2 else swapped
            return real(path, *args, **kwargs)
        with mock.patch.object(adaptor, 'bounded', flipping):
            fault = self.verify_fault(directory)
        self.assertIn('publication membership or digests differ from the receipt', fault.message)
        self.assertEqual(len(flips), 1)

    def test_verify_binds_the_captured_text_to_one_snapshot_for_every_comparison(self):
        directory, _ = self.publish(self.literal)
        captured = directory / 'captured.txt'
        original = captured.read_bytes()
        real = adaptor.bounded
        reads = []

        def reading(path, *args, **kwargs):
            if Path(path) == captured:
                reads.append(path)
            return real(path, *args, **kwargs)
        with mock.patch.object(adaptor, 'bounded', reading):
            self.assertTrue(adaptor.verify(directory, executable=self.espeak)['verified'])
        self.assertEqual(len(reads), 1)
        self.assertEqual(captured.read_bytes(), original)

    # ------------------------------------------------------------ standard hooks, CLI, configuration, workflow
    def test_standard_registry_hooks_and_cli_use_the_trusted_location(self):
        locations = {'espeakng': self.espeak}
        directory = self.root / 'registry'
        result = registry.run(self.literal, directory, locations=locations, timeout=60)
        self.assertTrue(result['verified'])
        with configuration.location_context(locations):
            self.assertTrue(registry.verify(directory)['verified'])
        with private_configuration():
            self.fault(lambda: registry.verify(directory), 'INTERPRETER_NOT_FOUND')
        (self.root / 'doc.json').write_text(json.dumps(self.file))
        completed = subprocess.run([sys.executable, '-m', 'schemaxis', 'run', str(self.root / 'doc.json'), '--output-directory', str(self.root / 'cli'),
                                    '--espeakng', self.espeak, '--timeout', '60'], env=self.environment, capture_output=True, text=True, timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stderr[-600:] + completed.stdout[-600:])
        self.assertTrue(json.loads(completed.stdout)['verified'])
        self.assertNotIn(self.data, completed.stdout)
        absent = subprocess.run([sys.executable, '-m', 'schemaxis', 'verify', str(self.root / 'cli')], env=self.environment, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(absent.returncode, 0)
        self.assertIn('INTERPRETER_NOT_FOUND', absent.stdout + absent.stderr)
        fine = subprocess.run([sys.executable, '-m', 'schemaxis', 'verify', str(self.root / 'cli')], env={**self.environment, 'SCHEMAXIS_ESPEAKNG': self.espeak},
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(fine.returncode, 0, fine.stderr[-600:] + fine.stdout[-600:])
        flag = subprocess.run([sys.executable, '-m', 'schemaxis', 'verify', str(self.root / 'cli'), '--espeakng', self.espeak], env=self.environment, capture_output=True, text=True, timeout=60)
        self.assertEqual(flag.returncode, 2)
        self.assertIn('unrecognized arguments', flag.stderr)
        planned = subprocess.run([sys.executable, '-m', 'schemaxis', 'plan', str(self.root / 'doc.json')], env=self.environment, capture_output=True, text=True, timeout=60)
        self.assertEqual(planned.returncode, 0, planned.stderr[-400:])
        self.assertNotIn(self.espeak, planned.stdout)
        refused = subprocess.run([sys.executable, '-m', 'schemaxis', 'plan', str(ROOT / 'examples/schemaxis/espeakng-invalid-phoneme.json')], env=self.environment, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('INVALID_ESPEAKNG_TEXT', refused.stdout + refused.stderr)

    def test_stored_location_verifies_and_isolation_hides_it_from_other_tests(self):
        directory, _ = self.publish(self.literal)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ):
            config = Path(tmp) / 'config.json'
            config.write_text(json.dumps({'version': 1, 'locations': {'espeakng': self.espeak}}))
            os.environ['SCHEMAXIS_CONFIG'] = str(config)
            os.environ.pop('SCHEMAXIS_ESPEAKNG', None)
            self.assertTrue(adaptor.verify(directory)['verified'])
            with configuration.location_context({'espeakng': None}):    # None does not clear a stored location
                self.assertTrue(registry.verify(directory)['verified'])
            completed = subprocess.run([sys.executable, '-m', 'schemaxis', 'verify', str(directory)], env={**self.environment, 'SCHEMAXIS_CONFIG': str(config)},
                                       capture_output=True, text=True, timeout=120)
            self.assertEqual(completed.returncode, 0, completed.stderr[-600:] + completed.stdout[-600:])
        with private_configuration():
            self.fault(lambda: adaptor.verify(directory), 'INTERPRETER_NOT_FOUND')

    def test_workflow_reuse_follows_literal_documents_and_captured_source_bytes(self):
        locations = {'espeakng': self.espeak}
        graph = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'script', 'document': self.file}, {'id': 'line', 'document': self.literal}]}
        directory = self.root / 'workflow'
        first = workflow.execute(graph, directory, locations=locations, timeout=120)
        self.assertEqual(first['status'], 'succeeded')
        with configuration.location_context(locations):
            self.assertTrue(workflow.verify(directory)['verified'])
        second = workflow.execute(graph, directory, locations=locations, timeout=120, resume=True)
        self.assertTrue(all(job['reused'] for job in second['jobs']))
        self.script.write_bytes(b'A different script.\n')                       # same path, different bytes
        third = workflow.execute(graph, directory, locations=locations, timeout=120, resume=True)
        reused = {job['id']: job['reused'] for job in third['jobs']}
        self.assertEqual(sorted(reused.values()), [False, True])
        self.assertTrue(reused['line/0'] if 'line/0' in reused else list(reused.values())[1])


@unittest.skipUnless(os.environ.get('SCHEMAXIS_ESPEAKNG'), 'real espeak-ng not configured: unqualified, see tools/qualify_espeakng.py')
class RealEspeakng(unittest.TestCase):
    def test_examples_run_verify_and_repeat_identically(self):
        espeak = os.environ['SCHEMAXIS_ESPEAKNG']
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('baseline', 'variant', 'fast'):
                document = json.loads((ROOT / f'examples/schemaxis/espeakng-{name}.json').read_text())
                if 'source' in document:
                    document['source'] = str(FIXTURES / 'script-numbered.txt')
                digests = []
                for attempt in (1, 2):
                    directory = Path(tmp) / f'{name}-{attempt}'
                    result = adaptor.run(document, directory, executable=espeak, timeout=120)
                    self.assertTrue(result['verified'])
                    self.assertTrue(adaptor.verify(directory)['verified'])
                    digests.append(result['pcmSha256'])
                self.assertEqual(digests[0], digests[1], name)


if __name__ == '__main__':
    unittest.main()
