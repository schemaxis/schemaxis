#!/usr/bin/env python3
"""Bounded native acceptance of the eSpeak NG narration draft with an eSpeak NG 1.52.0 `espeak-ng` and its matching data.

The tool synthesises with `espeak-ng` itself (own command line, own WAV reader) and compares every PCM byte with the published
audio, checks hand-derived literal counts and duration estimates, observes two fresh native processes per bounded case,
forges hostile publications from real native output (different words, different rate, edited waveforms) with every ordinary hash
refreshed, refuses unsupported text before any native process, drives a real changed-native-data runtime, plants a receipt
executable that must never run, exercises the documented `schemaxis verify` routes as real CLI processes, in-flight timeout and
cancellation, and the output budget edges. With SoX, FLAC and whisper.cpp executables it also runs narration -> conform,
narration -> lossless archive and transcript -> narration workflows. Determinism is observed only for the bounded cases it lists.
Public output replaces every workstation path with a placeholder; the full probe record stays in the private acceptance file.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import threading
import time

from schemaxis.adaptor_conformance import qualify, register
from schemaxis.adaptors.espeakng import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.configuration import location_context
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation
from schemaxis import workflow

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'examples/schemaxis/fixtures/espeakng'
PROCESSES = []
VERSION = 'schemaxis.espeakng/1'
BASE = 'Welcome to the plant tour. Please wear your safety glasses and stay behind the yellow line.'


def native(name, command, cwd, timeout=60, env=None, expect=0):
    """Run one probe process directly and keep its real PID, command and exit status."""
    process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    try:
        out, err = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise
    PROCESSES.append({'name': name, 'pid': process.pid, 'timeoutSeconds': timeout, 'command': [Path(command[0]).name, *[Path(a).name if str(a).startswith('/') else str(a) for a in command[1:]]],
                      'exitCode': process.returncode})
    assert process.returncode == expect, (name, process.returncode, err[-300:])
    return out if expect == 0 else out + err


class configuration_file:
    """Select a private SCHEMAXIS_CONFIG for a block, then restore the caller's environment."""
    def __init__(self, path, locations):
        self.path, self.locations = Path(path), locations

    def __enter__(self):
        atomic_json(self.path, {'version': 1, 'locations': self.locations})
        self.saved = {k: os.environ.get(k) for k in ('SCHEMAXIS_CONFIG', 'SCHEMAXIS_ESPEAKNG')}
        os.environ['SCHEMAXIS_CONFIG'] = str(self.path)
        os.environ.pop('SCHEMAXIS_ESPEAKNG', None)

    def __exit__(self, *error):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def refused(action, code='VERIFICATION_FAILED'):
    try:
        action()
    except SchemaxisError as error:
        assert error.fault.code == code, error.fault.to_dict()
        return error.fault
    raise AssertionError('invalid narration evidence accepted')


# ---------------------------------------------------------------- independent synthesis and WAV reading
def wav_parts(data):
    """This tool's own WAV parser: ((format, channels, rate, byte rate, align, bits), pcm); any RIFF/WAVE layout a native tool wrote."""
    assert data[:4] == b'RIFF' and data[8:12] == b'WAVE', data[:12]
    offset, fmt = 12, None
    while offset + 8 <= len(data):
        kind, size = data[offset:offset + 4], struct.unpack_from('<I', data, offset + 4)[0]
        if kind == b'fmt ':
            fmt = struct.unpack_from('<HHIIHH', data, offset + 8)
        if kind == b'data':
            return fmt, data[offset + 8:offset + 8 + size]
        offset += 8 + size + (size & 1)
    raise AssertionError('no data chunk')


def wav_of(pcm):
    return (b'RIFF' + struct.pack('<I', 36 + len(pcm)) + b'WAVEfmt ' + struct.pack('<IHHIIHH', 16, 1, 1, 22050, 44100, 2, 16) + b'data' + struct.pack('<I', len(pcm)) + pcm)


def synthesise(espeak, work, name, text, rate, *, executable=None):
    """Run espeak-ng itself with this tool's own command line (the documented -b1 UTF-8 text file, -w WAV file) and return the WAV bytes."""
    source, target = Path(work) / (name + '.txt'), Path(work) / (name + '-independent.wav')
    source.write_bytes(text if isinstance(text, bytes) else text.encode('utf-8'))
    target.unlink(missing_ok=True)
    native('synthesise-' + name, [executable or espeak, '-ven-us', '-s%d' % rate, '-p50', '-a100', '-b1', '-w', str(target), '-f', str(source)], work, timeout=60)
    return target.read_bytes()


def samples(pcm):
    return struct.unpack('<%dh' % (len(pcm) // 2), pcm)


def words_of(text):
    return len(text.split())


# ---------------------------------------------------------------- forging helpers (the dishonest writer the verifier must survive)
def snapshot(run):
    return {p: p.read_bytes() for p in Path(run).rglob('*') if p.is_file()}


def restore(saved):
    for path, content in saved.items():
        path.write_bytes(content)


def recorded_runtime(run):
    receipt = adaptor.read_json(run, 'verification.json')
    return {'identity': receipt['runtime']['espeakng'], 'dataFingerprint': receipt['runtime']['dataFingerprint']}


def rebind(run):
    run = Path(run)
    receipt = adaptor.read_json(run, 'verification.json')
    receipt['evidence'] = {n: adaptor.digest(run, n) for n in sorted(receipt['evidence'])}
    receipt['artifacts'] = adaptor.publications(run)
    atomic_json(run / 'verification.json', receipt)
    from schemaxis.publication_metadata import finalise
    finalise(run)    # the shared publication manifest is rebound too


def refresh(run, espeak=None, rewrite_summary=True):
    """Rebind every ordinary hash, and optionally rebuild the summary as a fully consistent forging writer would (only possible when the audio is genuine)."""
    run = Path(run)
    atomic_json(run / 'narrate-inputs.json', {'captured.txt': adaptor.digest(run, 'captured.txt')})
    rewritten = False
    if rewrite_summary:
        try:
            prepared = adaptor.plan(json.loads((run / 'authored.json').read_text()))
            observation = adaptor.observe(run, prepared, adaptor.runtime(espeak), {}, recorded_runtime(run))
            atomic_json(run / 'espeakng-summary.json', observation['summary'])
            rewritten = True
        except SchemaxisError:
            pass    # a forgery the verifier's own observation already refuses keeps the stale summary
    rebind(run)
    return rewritten


def verify_fault(run, espeak):
    try:
        adaptor.verify(run, executable=espeak)
    except SchemaxisError as error:
        return error.fault
    raise AssertionError('accepted')


# ---------------------------------------------------------------- acceptance sections
def literal_checks(kit, espeak, work):
    """Every PCM byte of every published file equals this tool's own native synthesis, and the hand-derived counts hold."""
    report = {}
    texts = {'baseline': (BASE, 175, 'literal'), 'variant': ((FIXTURES / 'script-numbered.txt').read_text(encoding='utf-8'), 140, 'file'),
             'fast': ('Flight 204 to Winnipeg now boards at gate 17, and the doors close in 10 minutes.', 240, 'literal')}
    for case, (text, rate, kind) in texts.items():
        run = kit / case
        independent = synthesise(espeak, work, 'literal-' + case, text, rate)
        fmt, pcm = wav_parts(independent)
        assert fmt == (1, 1, 22050, 44100, 2, 16), fmt
        assert independent == wav_of(pcm), 'native WAV is not the canonical layout'
        published = (run / 'narration.wav').read_bytes()
        assert published == independent == (run / 'native.wav').read_bytes(), case
        assert (run / 'captured.txt').read_bytes() == text.encode('utf-8')
        summary = adaptor.read_json(run, 'espeakng-summary.json')
        frames = len(pcm) // 2
        estimate = words_of(text) * 60 / rate
        assert summary['audio']['frames'] == frames and summary['source']['codePoints'] == len(text) and summary['source']['kind'] == kind, case
        assert abs(frames / 22050 - estimate) <= 0.15 * estimate, (case, frames / 22050, estimate)
        assert summary['pcm']['peakAbs'] == max(abs(s) for s in samples(pcm)) and summary['pcm']['nonzeroSamples'] == sum(1 for s in samples(pcm) if s)
        report[case] = {'rateWpm': rate, 'codePoints': len(text), 'frames': frames, 'durationSeconds': round(frames / 22050, 3), 'estimateWordsOverRate': round(estimate, 3),
                        'pcmSha256': hashlib.sha256(pcm).hexdigest(), 'everyPcmByteEqualsOwnNativeSynthesis': True, 'canonicalHeaderIndependentlyRead': True}
    return report


def determinism(work, espeak):
    """Two fresh adaptor runs (each with fresh native processes) and one direct synthesis per bounded case: identical PCM, or a failure."""
    long_text = ' '.join('Section %d: the quick brown fox jumps over the lazy dog, and then rests.' % i for i in range(1, 15))[:1000]
    cases = {'baseline-175': (BASE, 175), 'baseline-120': (BASE, 120), 'baseline-240': (BASE, 240), 'rate-121': (BASE, 121), 'rate-239': (BASE, 239),
             'multiline': ((FIXTURES / 'script-numbered.txt').read_text(encoding='utf-8'), 140),
             'numbers-abbreviations': ('Dr. Smith paid $5.50 on 10/25/2026 at 3:45 p.m. for 12 apples, 7 pears and 1,000 grapes.', 175),
             'punctuation-mix': ('Wait -- what?! "Yes," she said; (maybe) 50% of it... costs a lot: really!', 175),
             'cyrillic-greek': ('Привет, мир. Καλημέρα κόσμε.', 175), 'accents': ('Le café est à côté de la résumé naïve.', 160),
             'long-1000-characters': (long_text, 200), 'digits-1024-at-240': (('1234567890 ' * 94)[:1024].rstrip() + '7', 240)}
    report = {}
    for label, (text, rate) in cases.items():
        text = text[:1024]
        document = {'version': VERSION, 'operation': 'narrate', 'text': text, 'rateWpm': rate}
        digests, frames = [], []
        for attempt in (1, 2):
            run = Path(work) / ('determinism-%s-%d' % (label, attempt))
            result = adaptor.run(document, run, executable=espeak, timeout=120)
            assert result['verified'], label
            digests.append((run / 'narration.wav').read_bytes())
            frames.append(result['audio']['frames'])
        direct = synthesise(espeak, work, 'determinism-' + label, text, rate)
        assert digests[0] == digests[1] == direct, label
        report[label] = {'codePoints': len(text), 'rateWpm': rate, 'frames': frames[0], 'durationSeconds': round(frames[0] / 22050, 2), 'wavSha256': hashlib.sha256(digests[0]).hexdigest(),
                         'freshRunsIdentical': True, 'directSynthesisIdentical': True}
        shutil.rmtree(Path(work) / ('determinism-%s-1' % label))
        shutil.rmtree(Path(work) / ('determinism-%s-2' % label))
    return report


def hostile(kit, espeak, work):
    """Real native output for other words, other rates and edited waveforms replaces the publication with every ordinary hash refreshed."""
    run, report = kit / 'baseline', {}
    saved = snapshot(run)
    good = (run / 'narration.wav').read_bytes()
    pcm = good[44:]
    flipped = bytearray(pcm)
    flipped[1000] ^= 0x01
    halved = b''.join(struct.pack('<h', s // 2) for s in samples(pcm))
    shifted = pcm[2:] + pcm[:2]
    other_words = synthesise(espeak, work, 'hostile-words', BASE.replace('yellow', 'orange'), 175)
    variants = {
        'differentWordsRealNativeOutput': other_words,
        'sameWordsRate176RealNativeOutput': synthesise(espeak, work, 'hostile-rate176', BASE, 176),
        'sameWordsRate120RealNativeOutput': synthesise(espeak, work, 'hostile-rate120', BASE, 120),
        'sameWordsRate240RealNativeOutput': synthesise(espeak, work, 'hostile-rate240', BASE, 240),
        'oneSampleBitFlipped': wav_of(bytes(flipped)),
        'amplitudeHalved': wav_of(halved),
        'sampleRotatedByOne': wav_of(shifted),
        'lastTenSamplesDropped': wav_of(pcm[:-20]),
        'tenSamplesAppended': wav_of(pcm + pcm[:20]),
        'silence': wav_of(bytes(len(pcm))),
        'headerRateEdited': good[:24] + struct.pack('<I', 16000) + good[28:],
        'trailingByte': good + b'\0',
    }
    try:
        for label, forged in variants.items():
            assert forged != good, label
            for target in (('narration.wav',), ('narration.wav', 'native.wav')):
                for name in target:
                    (run / name).write_bytes(forged)
                rewritten = refresh(run, espeak)
                fault = verify_fault(run, espeak)
                assert fault.code == 'VERIFICATION_FAILED', (label, fault.to_dict())
                report['%s/%s' % (label, '+'.join(target))] = {'summaryRewritten': rewritten, 'fault': fault.code, 'reason': fault.message[:130]}
                restore(saved)
        # The captured text is an unauthenticated trust anchor: other words with the audio really synthesised from them verify once everything is rewritten.
        words = BASE.replace('yellow', 'orange')
        authored = {'version': VERSION, 'operation': 'narrate', 'text': words, 'rateWpm': 175}
        atomic_json(run / 'authored.json', authored)
        atomic_json(run / 'plan.json', adaptor.plan(authored))
        (run / 'captured.txt').write_bytes(words.encode())
        atomic_json(run / 'captures.json', adaptor.capture_record(adaptor.plan(authored), words.encode()))
        (run / 'narration.wav').write_bytes(other_words)
        (run / 'native.wav').write_bytes(other_words)
        refresh(run, espeak)
        verified = adaptor.verify_semantic(run, adaptor.runtime(espeak), require_result=False)
        atomic_json(run / 'result.json', {'status': 'succeeded', **verified})
        report['coherentRewriteOfWordsAndAudio'] = {'accepted': adaptor.verify(run, executable=espeak)['verified'],
                                                    'meaning': 'documented limit: the captured text and its derived records are an unauthenticated trust anchor'}
    finally:
        restore(saved)
    assert adaptor.verify(run, executable=espeak)['verified']
    return report


def source_refusals(work, espeak):
    """Hostile or unsupported real inputs refused at run time: code, location and whether any native process started."""
    longest = 'word ' * 300
    cases = {
        'crlf-file': ('a.txt', b'One line.\r\nTwo lines.\r\n', 'INVALID_ESPEAKNG_TEXT'), 'tab': ('a.txt', b'one\ttwo', 'INVALID_ESPEAKNG_TEXT'),
        'form-feed-tail': ('a.txt', b'Review Alpha\n\n\x0c', 'INVALID_ESPEAKNG_TEXT'), 'nul': ('a.txt', b'one\0two', 'INVALID_ESPEAKNG_TEXT'),
        'byte-order-mark': ('a.txt', b'\xef\xbb\xbfHello there.', 'INVALID_ESPEAKNG_TEXT'), 'latin-1': ('a.txt', 'caf\xe9 au lait'.encode('latin-1'), 'INVALID_ESPEAKNG_TEXT'),
        'invalid-utf8': ('a.txt', b'ab\xff\xfecd', 'INVALID_ESPEAKNG_TEXT'), 'utf-16': ('a.txt', 'Hello there.'.encode('utf-16'), 'INVALID_ESPEAKNG_TEXT'),
        'phoneme-escape': ('a.txt', b"Say [[h@'loU]] now.", 'INVALID_ESPEAKNG_TEXT'), 'ssml': ('a.txt', b'<speak>Hello <break time="1s"/> there.</speak>', 'INVALID_ESPEAKNG_TEXT'),
        'entity': ('a.txt', b'fish &amp; chips', 'INVALID_ESPEAKNG_TEXT'), 'punctuation-only': ('a.txt', b'... --- !!!', 'INVALID_ESPEAKNG_TEXT'),
        'whitespace-only': ('a.txt', b' \n \n', 'INVALID_ESPEAKNG_TEXT'), 'empty': ('a.txt', b'', 'INVALID_ESPEAKNG_TEXT'),
        'internal-code-point': ('a.txt', 'a԰b'.encode(), 'INVALID_ESPEAKNG_TEXT'), 'private-use': ('a.txt', 'ab'.encode(), 'INVALID_ESPEAKNG_TEXT'),
        'over-1024-code-points': ('a.txt', longest.encode(), 'ESPEAKNG_BUDGET'), 'over-8-KiB': ('a.txt', b'x' * 9000, 'ESPEAKNG_BUDGET'),
    }
    report = {}
    for label, (name, data, code) in cases.items():
        path = Path(work) / ('refusal-' + label + '-' + name)
        path.write_bytes(data)
        run = Path(work) / ('refusal-run-' + label)
        fault = refused(lambda: adaptor.run({'version': VERSION, 'operation': 'narrate', 'source': str(path)}, run, executable=espeak, timeout=60), code)
        assert fault.location == '$.source' and not (run / 'version-submission.json').exists(), label
        report[label] = {'fault': fault.code, 'location': fault.location, 'nativeProcessStarted': False}
    # literal refusals happen while planning: no run directory exists at all
    for label, text, code in (('literal-tab', 'a\tb', 'INVALID_ESPEAKNG_TEXT'), ('literal-phoneme', 'x [[y]] z', 'INVALID_ESPEAKNG_TEXT'), ('literal-1025', 'x' * 1025, 'ESPEAKNG_BUDGET'),
                              ('literal-punctuation', '?!', 'INVALID_ESPEAKNG_TEXT')):
        run = Path(work) / ('refusal-run-' + label)
        fault = refused(lambda: adaptor.run({'version': VERSION, 'operation': 'narrate', 'text': text}, run, executable=espeak, timeout=60), code)
        assert fault.location == '$.text' and not run.exists(), label
        report[label] = {'fault': fault.code, 'location': fault.location, 'runDirectoryCreated': False}
    for label, source in (('relative', 'script.txt'), ('url', 'https://example.org/a.txt'), ('wrong-suffix', str(Path(work) / 'a.text'))):
        fault = refused(lambda: adaptor.run({'version': VERSION, 'operation': 'narrate', 'source': source}, Path(work) / ('refusal-run-' + label), executable=espeak, timeout=60), 'INVALID_ESPEAKNG_SOURCE')
        report['source-' + label] = {'fault': fault.code, 'location': fault.location}
    link, target = Path(work) / 'link.txt', Path(work) / 'refusal-empty-a.txt'
    target.write_bytes(b'Hello there.')
    link.symlink_to(target)
    report['symlink'] = refused(lambda: adaptor.run({'version': VERSION, 'operation': 'narrate', 'source': str(link)}, Path(work) / 'refusal-run-symlink', executable=espeak, timeout=60),
                                'INVALID_ESPEAKNG_SOURCE').code
    return report


def native_silence_and_runtime_guards(work, espeak):
    """The real synthesizer writes a zero-PCM WAV for text the profile refuses; the adaptor's own output guard (used by run) refuses it as silence."""
    report = {}
    for label, text in (('dots', '.' * 200), ('spaces', ' \n '), ('dashes-and-underscores', '- _ - _')):
        scratch = Path(work) / ('silence-' + label)
        scratch.mkdir()
        (scratch / 'captured.txt').write_bytes(text.encode())
        fault = refused(lambda: adaptor.synthesize(scratch, espeak, 175), 'ESPEAKNG_SILENT_OUTPUT')
        fmt, pcm = wav_parts((scratch / 'native.wav').read_bytes())
        assert not any(pcm) and fmt == (1, 1, 22050, 44100, 2, 16)
        report[label] = {'nativeWavBytes': 44 + len(pcm), 'allSamplesZero': True, 'fault': fault.code}
    return report


def budget(work, espeak):
    """The speaking-time budget is judged on the finished native output: largest accepted shapes and the first refused ones, with observed wall times."""
    report = {}
    accepted = (('maximum-1024-code-points', ('1234567890 ' * 94)[:1024].rstrip() + '7', 240), ('zeros-200-at-120-wpm', '0 ' * 200, 120), ('zeros-200-at-175-wpm', '0 ' * 200, 175))
    for label, text, rate in accepted:
        document = {'version': VERSION, 'operation': 'narrate', 'text': text[:1024], 'rateWpm': rate}
        start = time.monotonic()
        result = adaptor.run(document, Path(work) / ('budget-' + label), executable=espeak, timeout=300)
        run_seconds = time.monotonic() - start
        start = time.monotonic()
        assert adaptor.verify(Path(work) / ('budget-' + label), executable=espeak)['verified']
        report[label] = {'codePoints': len(document['text']), 'rateWpm': rate, 'frames': result['audio']['frames'], 'durationSeconds': round(result['audio']['frames'] / 22050, 1),
                         'wavBytes': result['bytes']['wav'], 'runSeconds': round(run_seconds, 1), 'verifySeconds': round(time.monotonic() - start, 1)}
        assert result['audio']['frames'] <= 120 * 22050 and result['verified']
        shutil.rmtree(Path(work) / ('budget-' + label))
    for label, text, rate in (('zeros-250-at-120-wpm', '0 ' * 250, 120), ('zeros-512-at-120-wpm', '0 ' * 512, 120), ('nines-512-at-120-wpm', '9 ' * 512, 120),
                              ('doctor-abbreviations-250-at-120-wpm', 'Dr. ' * 250, 120)):
        run = Path(work) / ('budget-refused-' + label)
        start = time.monotonic()
        fault = refused(lambda: adaptor.run({'version': VERSION, 'operation': 'narrate', 'text': text, 'rateWpm': rate}, run, executable=espeak, timeout=300), 'ESPEAKNG_BUDGET')
        native_wav = (run / 'native.wav').stat().st_size if (run / 'native.wav').exists() else 0
        assert not (run / 'narration.wav').exists() and adaptor.read_json(run, 'result.json')['status'] == 'failed'
        report[label] = {'fault': fault.code, 'message': fault.message[:90], 'nativeWavBytesBeforeRefusal': native_wav, 'seconds': round(time.monotonic() - start, 1),
                         'publicationsLeft': False}
    return report


def retained_json(kit, espeak):
    """Type-only, duplicate-key and non-finite edits of retained JSON with every ordinary hash and the manifest rebound."""
    run = kit / 'baseline'
    saved = snapshot(run)

    def first(old, new):
        def edit(text):
            assert text.count(old) == 1, old
            return text.replace(old, new)
        return edit

    def leading(entry):
        return lambda text: '{' + entry + ', ' + text.lstrip()[1:]

    def to_float(pattern):
        return lambda text: re.sub(pattern, lambda m: m.group(1) + m.group(2) + '.0', text, count=1, flags=re.S)
    cases = [('summaryBooleanAsInteger', 'espeakng-summary.json', first('"pcmIdentical": true', '"pcmIdentical": 1'), True),
             ('summaryRateAsFloat', 'espeakng-summary.json', to_float(r'("rateWpm": )(\d+)'), True),
             ('summaryDuplicateKey', 'espeakng-summary.json', first('"pcmIdentical": true', '"pcmIdentical": false, "pcmIdentical": true'), False),
             ('summaryNaN', 'espeakng-summary.json', first('"pcmIdentical": true', '"pcmIdentical": NaN'), False),
             ('summaryOverflow1e400', 'espeakng-summary.json', first('"pcmIdentical": true', '"pcmIdentical": 1e400'), False),
             ('planRateAsFloat', 'plan.json', to_float(r'("rateWpm": )(\d+)'), True), ('capturesBytesAsFloat', 'captures.json', to_float(r'("bytes": )(\d+)'), True),
             ('narrateInputsDuplicateKey', 'narrate-inputs.json', leading('"captured.txt": "0"'), False),
             ('resultBooleanAsInteger', 'result.json', first('"verified": true', '"verified": 1'), True), ('resultCountAsFloat', 'result.json', first('"artifacts": 2', '"artifacts": 2.0'), True),
             ('resultDuplicateStatus', 'result.json', leading('"status": "failed"'), False), ('receiptNaN', 'verification.json', leading('"extra": NaN'), False),
             ('receiptOverflow1e400', 'verification.json', leading('"extra": 1e400'), False)]
    report = {}
    try:
        for label, name, edit, collapses in cases:
            path = run / name
            if name == 'verification.json':
                rebind(run)
            before = path.read_text()
            path.write_text(edit(before))
            assert path.read_text() != before, label
            if collapses:
                assert json.loads(before) == json.loads(path.read_text()), label
            if name != 'verification.json':
                rebind(run)
            fault = verify_fault(run, espeak)
            assert fault.code == 'VERIFICATION_FAILED', fault.to_dict()
            report[label] = {'pythonEqualityWouldCollapse': collapses, 'fault': fault.code, 'reason': fault.message[:100]}
            restore(saved)
    finally:
        restore(saved)
    assert adaptor.verify(run, executable=espeak)['verified']
    return report


def wrapper(path, real, environment=None):
    """A private script that runs the real espeak-ng with extra environment variables, for changed-runtime probes."""
    path.write_text('#!%s\nimport os, sys\nos.environ.update(%r)\nos.execv(%r, [%r, *sys.argv[1:]])\n' % (sys.executable, dict(environment or {}), real, real))
    path.chmod(0o700)
    return str(path)


def runtime_and_data(kit, espeak, work):
    """Receipt executables are inert; a missing trusted espeak-ng is unavailable; a real changed-data runtime fails an older proof with the matching-runtime hint."""
    run = kit / 'baseline'
    marker = Path(work) / 'sentinel.marker'
    trap = Path(work) / 'sentinel-espeak-ng'
    trap.write_text('#!%s\nfrom pathlib import Path\nPath(%r).write_text("ran")\n' % (sys.executable, str(marker)))
    trap.chmod(0o700)
    saved = snapshot(run)
    report = {}
    try:
        receipt = adaptor.read_json(run, 'verification.json')
        receipt['executables']['espeakng'] = str(trap)
        atomic_json(run / 'verification.json', receipt)
        decoys = Path(work) / 'decoy-bin'
        decoys.mkdir()
        (decoys / 'espeak-ng').write_text(trap.read_text())
        (decoys / 'espeak-ng').chmod(0o700)
        atomic_json(work / 'absent-config.json', {'version': 1, 'locations': {}})
        probe = ('import sys\nfrom pathlib import Path\nfrom schemaxis.adaptors.espeakng import adaptor\n'
                 'try:\n    adaptor.verify(Path(sys.argv[1]))\nexcept Exception as error:\n    print(error.fault.code, error.fault.location)\nelse:\n    print("verified")\n')
        environment = {k: v for k, v in os.environ.items() if not k.startswith('SCHEMAXIS_')} | {'PYTHONPATH': str(ROOT / 'src'), 'SCHEMAXIS_CONFIG': str(work / 'absent-config.json'),
                                                                                                  'PATH': str(decoys) + os.pathsep + os.environ.get('PATH', '')}
        outcome = native('verify-without-trusted-espeak-ng', [sys.executable, '-c', probe, str(run)], work, env=environment).decode().strip()
        assert outcome == 'INTERPRETER_NOT_FOUND $.runtime.espeakng', outcome
        report['withoutTrustedEspeakNg'] = outcome
        assert not marker.exists()
        report['pathDecoyNeverLaunched'] = True
        rebind(run)
        report['receiptNamesDifferentExecutable'] = verify_fault(run, espeak).message[:90]
        assert not marker.exists()
        report['receiptExecutableNeverLaunched'] = True
    finally:
        restore(saved)
    for label, bad in (('relativeName', 'espeak-ng'), ('missingFile', str(Path(work) / 'missing')), ('notExecutable', str(run / 'captured.txt'))):
        report[label] = refused(lambda: adaptor.verify(run, executable=bad), 'INTERPRETER_NOT_FOUND').code
    wrong = Path(work) / 'newer-espeak-ng'
    wrong.write_text('#!%s\nimport os, sys\nif sys.argv[1:] == ["--version"]:\n    print("eSpeak NG text-to-speech: 1.52.1  Data at: /nonexistent")\n    sys.exit(0)\nos.execv(%r, [%r, *sys.argv[1:]])\n' % (sys.executable, espeak, espeak))
    wrong.chmod(0o700)
    report['wrongVersion'] = refused(lambda: adaptor.verify(run, executable=str(wrong)), 'UNSUPPORTED_RUNTIME').code
    # real changed native data: a private copy of the data directory, selected by a wrapper through ESPEAK_DATA_PATH (which both --version and synthesis honour;
    # --path is not used because --version ignores it). The adaptor's own launcher never sets or passes either.
    data = Path(native('version-for-data', [espeak, '--version'], work).decode().split('Data at: ')[1].strip())
    for label, edit, expect_pcm in (('commentOnlyVoiceFileEdit', lambda text: text + '\n// a comment that changes no synthesis parameter\n', True),
                                    ('stressLengthVoiceFileEdit', lambda text: text.replace('stressLength 140 120 190 170 0 0 255 300', 'stressLength 150 120 190 170 0 0 255 300'), False)):
        copy = Path(work) / ('data-' + label)
        (copy / 'espeak-ng-data').parent.mkdir(parents=True)
        shutil.copytree(data, copy / 'espeak-ng-data')
        voice = copy / 'espeak-ng-data/lang/gmw/en-US'
        text = voice.read_text()
        assert edit(text) != text, label
        voice.write_text(edit(text))
        changed = wrapper(Path(work) / ('changed-' + label), espeak, {'ESPEAK_DATA_PATH': str(copy / 'espeak-ng-data')})
        fault = verify_fault(run, changed)
        assert fault.code == 'VERIFICATION_FAILED' and 'matching runtime and data' in fault.message, fault.to_dict()
        assert ('although the PCM agrees' in fault.message) == expect_pcm, fault.message
        report[label] = {'fault': fault.code, 'pcmStillAgrees': expect_pcm, 'reason': fault.message[:170]}
    assert adaptor.verify(run, executable=espeak)['verified']
    return report


def cli_verify(run, espeak, work):
    """The documented routes for bare `schemaxis verify`: SCHEMAXIS_ESPEAKNG or a stored espeakng location; there is no --espeakng flag."""
    base = {k: v for k, v in os.environ.items() if not k.startswith('SCHEMAXIS_')}
    base['PYTHONPATH'] = str(ROOT / 'src')
    atomic_json(work / 'cli-empty.json', {'version': 1, 'locations': {}})
    atomic_json(work / 'cli-stored.json', {'version': 1, 'locations': {'espeakng': espeak}})
    command = [sys.executable, '-m', 'schemaxis', 'verify', str(run)]
    report = {'environmentVariable': json.loads(native('cli-verify-environment', command, work, env={**base, 'SCHEMAXIS_CONFIG': str(work / 'cli-empty.json'), 'SCHEMAXIS_ESPEAKNG': espeak}))['verified'],
              'storedLocation': json.loads(native('cli-verify-stored-location', command, work, env={**base, 'SCHEMAXIS_CONFIG': str(work / 'cli-stored.json')}))['verified']}
    missing = native('cli-verify-without-espeakng', command, work, env={**base, 'SCHEMAXIS_CONFIG': str(work / 'cli-empty.json')}, expect=1).decode()
    assert 'INTERPRETER_NOT_FOUND' in missing, missing[-300:]
    report['withoutEspeakNg'] = 'INTERPRETER_NOT_FOUND'
    flag = native('cli-verify-with-espeakng-flag', [*command, '--espeakng', espeak], work, env={**base, 'SCHEMAXIS_CONFIG': str(work / 'cli-empty.json')}, expect=2).decode()
    assert 'unrecognized arguments' in flag and '--espeakng' in flag, flag[-300:]
    report['espeakngFlagOnBareVerify'] = 'rejected by the argument parser (exit 2): the flag belongs to run and inspect'
    document = work / 'cli-run.json'
    document.write_text(json.dumps({'version': VERSION, 'operation': 'narrate', 'text': 'Spoken through the command line.', 'rateWpm': 200}))
    ran = json.loads(native('cli-run', [sys.executable, '-m', 'schemaxis', 'run', str(document), '--output-directory', str(work / 'cli-run'), '--espeakng', espeak, '--timeout', '120'],
                            work, timeout=180, env={**base, 'SCHEMAXIS_CONFIG': str(work / 'cli-empty.json')}))
    assert ran['verified'] and espeak not in json.dumps(ran) and '/espeak-ng-data' not in json.dumps(ran)
    report['cliRun'] = {'verified': True, 'resultNamesNoPath': True}
    return report


def lifecycle(work, espeak):
    wrapper_path = work / 'slow-espeak-ng.py'
    marker = work / 'slow.pid'
    wrapper_path.write_text('#!%s\nimport os, sys, time\nfrom pathlib import Path\nif sys.argv[1:] in (["--version"], ["--voices=en"]):\n    os.execv(%r, [%r, *sys.argv[1:]])\nPath(%r).write_text(str(os.getpid()))\ntime.sleep(30)\n'
                            % (sys.executable, espeak, espeak, str(marker)))
    wrapper_path.chmod(0o700)
    document = {'version': VERSION, 'operation': 'narrate', 'text': BASE}
    results = {}
    for action in ('timeout', 'cancel'):
        marker.unlink(missing_ok=True)
        cancel = threading.Event()
        thread = None
        if action == 'cancel':
            def trigger():
                end = time.monotonic() + 8
                while not marker.exists() and time.monotonic() < end:
                    time.sleep(.01)
                if marker.exists():
                    cancel.set()
            thread = threading.Thread(target=trigger, daemon=True)
            thread.start()
        try:
            with allocation({'threads': 1, 'ranks': 1}, cancel):
                results[action] = refused(lambda: adaptor.run(document, work / ('inflight-' + action), executable=str(wrapper_path), timeout=10 if thread else 2),
                                          'RUNNER_CANCELLED' if thread else 'RUNNER_TIMED_OUT').code
        finally:
            if thread:
                thread.join(10)
        assert marker.exists()
        try:
            os.kill(int(marker.read_text()), 0)
        except ProcessLookupError:
            pass
        else:
            raise AssertionError('owned process survived ' + action)
        assert not (work / ('inflight-' + action) / 'narration.wav').exists()
    results['outputCollision'] = refused(lambda: adaptor.run(document, work / 'inflight-timeout', executable=espeak, timeout=30), 'OUTPUT_EXISTS').code
    return results


def workflows(work, espeak, sox, flac, whisper):
    """narrate -> SoX conform, narrate -> lossless FLAC, and (with whisper.cpp) transcript.txt -> narrate, with reuse invalidation."""
    report = {}
    locations = {'espeakng': espeak}
    if sox:
        locations['sox'] = sox
    if flac:
        locations['flac'] = flac
    if whisper:
        locations['whispercpp'] = whisper['executable']
    if sox:
        script = work / 'narration-script.txt'
        script.write_text(BASE, encoding='utf-8')
        graph = {'version': 'schemaxis.workflow/1', 'operations': [
            {'id': 'narration', 'document': {'version': VERSION, 'operation': 'narrate', 'source': str(script)}},
            {'id': 'speech', 'document': {'version': 'schemaxis.sox/1', 'operation': 'conform', 'source': {'$artifact': 'narration', 'index': 0}, 'channelPolicy': 'average'}}]}
        first = workflow.execute(graph, work / 'speech-workflow', locations=locations, timeout=240)
        assert first['status'] == 'succeeded'
        with location_context(locations):
            assert workflow.verify(work / 'speech-workflow')['verified']
        root = work / 'speech-workflow'
        conformed = [p for p in root.rglob('audio.wav') if p.relative_to(root).parts[0] == 'speech']
        narrated = [p for p in root.rglob('narration.wav')]
        assert len(conformed) == 1 and len(narrated) == 1
        fmt, pcm = wav_parts(conformed[0].read_bytes())
        source_frames = len(wav_parts(narrated[0].read_bytes())[1]) // 2
        expected = source_frames * 16000 / 22050
        assert (fmt[1], fmt[2], fmt[5]) == (1, 16000, 16) and abs(len(pcm) // 2 - expected) <= 2, (fmt, len(pcm) // 2, expected)
        second = workflow.execute(graph, work / 'speech-workflow', locations=locations, timeout=240, resume=True)
        assert all(job['reused'] for job in second['jobs'])
        script.write_text(BASE.replace('yellow', 'orange'), encoding='utf-8')    # same path, different bytes
        third = workflow.execute(graph, work / 'speech-workflow', locations=locations, timeout=240, resume=True)
        assert all(not job['reused'] for job in third['jobs'])
        report['narrateThenSoxConform'] = {'status': first['status'], 'conformedFormat': 'PCM16 mono %d Hz' % fmt[2], 'narrationFrames': source_frames, 'conformedFrames': len(pcm) // 2,
                                          'frameCountMatchesRateRatioWithinTwo': True, 'unchangedReused': True, 'changedSamePathSourceBytesReused': False,
                                          'soxRuntime': re.sub(r'^.*?(SoX v)', r'\1', native('sox-version', [sox, '--version'], work, timeout=20).decode().strip())}
    if flac:
        graph = {'version': 'schemaxis.workflow/1', 'operations': [
            {'id': 'narration', 'document': {'version': VERSION, 'operation': 'narrate', 'text': BASE, 'rateWpm': 160}},
            {'id': 'archive', 'document': {'version': 'schemaxis.flac/1', 'operation': 'encodeLossless', 'source': {'$artifact': 'narration', 'index': 0}}}]}
        result = workflow.execute(graph, work / 'archive-workflow', locations=locations, timeout=240)
        assert result['status'] == 'succeeded'
        root = work / 'archive-workflow'
        archive = [p for p in root.rglob('audio.flac')]
        narrated = [p for p in root.rglob('narration.wav')]
        assert len(archive) == 1 and len(narrated) == 1
        decoded = Path(work) / 'archive-decoded.wav'
        native('flac-independent-decode', [flac, '-d', '-s', '-w', '--no-preserve-modtime', '-o', str(decoded), str(archive[0])], work)
        assert wav_parts(decoded.read_bytes())[1] == wav_parts(narrated[0].read_bytes())[1]
        report['narrateThenFlacArchive'] = {'status': result['status'], 'independentFlacDecodeEqualsNarrationPcm': True}
    if whisper:
        graph = {'version': 'schemaxis.workflow/1', 'operations': [
            {'id': 'transcribe', 'document': {'version': 'schemaxis.whispercpp/1', 'operation': 'transcribe', 'audio': {'path': whisper['audio'], 'sha256': whisper['audioSha256']},
                                              'model': {'path': whisper['model'], 'sha256': whisper['modelSha256']}, 'language': 'en'}},
            {'id': 'narration', 'document': {'version': VERSION, 'operation': 'narrate', 'source': {'$artifact': 'transcribe', 'index': 1}, 'rateWpm': 160}}]}
        try:
            result = workflow.execute(graph, work / 'transcript-workflow', locations=locations, timeout=600)
        except SchemaxisError as error:
            report['transcriptThenNarrate'] = {'fault': error.fault.code, 'location': error.fault.location, 'message': error.fault.message[:200]}
            return report
        assert result['status'] == 'succeeded'
        root = work / 'transcript-workflow'
        transcript = [p for p in root.rglob('transcript.txt')]
        captured = [p for p in root.rglob('captured.txt')]
        narrated = [p for p in root.rglob('narration.wav')]
        assert len(transcript) == len(captured) == len(narrated) == 1
        assert captured[0].read_bytes() == transcript[0].read_bytes()
        independent = synthesise(espeak, work, 'transcript', transcript[0].read_bytes(), 160)
        assert narrated[0].read_bytes() == independent
        report['transcriptThenNarrate'] = {'status': result['status'], 'capturedBytesEqualTranscriptFile': True, 'transcriptBytes': transcript[0].stat().st_size,
                                          'everyPcmByteEqualsOwnNativeSynthesis': True}
    return report


def public(value, espeak, directory):
    """Replace every workstation path in the public report with a placeholder."""
    text = json.dumps(value, indent=2)
    version = subprocess.run([espeak, '--version'], capture_output=True, text=True, check=True).stdout
    data = version.split('Data at: ')[1].strip()
    for private, label in ((data, '<espeak-ng-data>'), (espeak, '<espeak-ng>'), (str(directory), '<output>'), (str(ROOT), '<repository>')):
        text = text.replace(private, label).replace(json.dumps(private)[1:-1], label)
    return json.loads(re.sub(r'/(?:home|tmp|usr|opt|var)/[^\s"\\]*', '<path>', text))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--espeakng', type=Path, required=True, help='absolute eSpeak NG 1.52.0 espeak-ng')
    parser.add_argument('--sox', type=Path, help='absolute SoX 14.4.2 sox for the narrate -> conform workflow (reported unavailable when absent)')
    parser.add_argument('--flac', type=Path, help='absolute FLAC 1.5 flac for the narrate -> archive workflow (reported unavailable when absent)')
    parser.add_argument('--whispercpp', type=Path, help='absolute whisper-cli for the transcript -> narrate workflow (needs --whisper-model and --whisper-audio)')
    parser.add_argument('--whisper-model', type=Path)
    parser.add_argument('--whisper-audio', type=Path)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--register', action='store_true', help='retain the native receipt in the source package (only after shared integration freezes)')
    parser.add_argument('--skip-budget', action='store_true')
    parser.add_argument('--skip-determinism', action='store_true')
    parser.add_argument('--only', help='comma-separated section names to run (development aid; a receipt for the full acceptance runs every section)')
    args = parser.parse_args()
    directory = args.output_directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    espeak = os.path.abspath(args.espeakng)
    locations = {'espeakng': espeak}
    report = {'verified': False, 'acceptancePid': os.getpid()}
    try:
        version = native('espeak-ng-version', [espeak, '--version'], directory).decode().strip()
        report['runtime'] = {'identity': version.split('  Data at:')[0], 'dataFingerprint': adaptor.data_fingerprint(version.split('Data at: ')[1].strip())}
        report['voices'] = native('espeak-ng-voices-en', [espeak, '--voices=en'], directory).decode().splitlines()[:4]
        with configuration_file(directory / 'config.json', locations):
            receipt = qualify(adaptor.VERSION, directory / 'kit', native=True, root=ROOT, locations=locations, timeout=120, wall_timeout=240)
        report['native'] = {'verified': receipt['verified'], 'cases': [c['id'] for c in receipt['cases']], 'runtimes': [c['runtime'] for c in receipt['cases']], 'lifecycle': receipt['lifecycle']}
        kit = directory / 'kit'
        with configuration_file(directory / 'config-empty.json', {}):
            report['verifyWithoutConfiguredEspeakNg'] = refused(lambda: adaptor.verify(kit / 'baseline'), 'INTERPRETER_NOT_FOUND').code
        with configuration_file(directory / 'config-with-espeakng.json', locations):
            report['verifyWithStoredEspeakNg'] = adaptor.verify(kit / 'baseline')['verified']
        work = directory / 'work'
        work.mkdir()
        with location_context(locations):
            sections = (('literalPcm', lambda: literal_checks(kit, espeak, work)), ('determinism', lambda: determinism(work, espeak)), ('hostile', lambda: hostile(kit, espeak, work)),
                        ('sourceRefusals', lambda: source_refusals(work, espeak)), ('nativeSilence', lambda: native_silence_and_runtime_guards(work, espeak)),
                        ('retainedJson', lambda: retained_json(kit, espeak)), ('runtimeAndData', lambda: runtime_and_data(kit, espeak, work)),
                        ('cliVerifyRoutes', lambda: cli_verify(kit / 'baseline', espeak, work)), ('inflightLifecycle', lambda: lifecycle(work, espeak)),
                        ('budget', lambda: budget(work, espeak)))
            for name, section in sections:
                if (args.only and name not in args.only.split(',')) or (name == 'budget' and args.skip_budget) or (name == 'determinism' and args.skip_determinism):
                    report[name] = 'not run in this invocation'
                    continue
                report[name] = section()
            if args.only and 'workflow' not in args.only.split(','):
                report['workflow'] = 'not run in this invocation'
            elif args.sox or args.flac or args.whispercpp:
                whisper = None
                if args.whispercpp and args.whisper_model and args.whisper_audio:
                    sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()    # noqa: E731
                    whisper = {'executable': os.path.abspath(args.whispercpp), 'model': os.path.abspath(args.whisper_model), 'audio': os.path.abspath(args.whisper_audio),
                               'modelSha256': sha(args.whisper_model), 'audioSha256': sha(args.whisper_audio)}
                report['workflow'] = workflows(work, espeak, os.path.abspath(args.sox) if args.sox else None, os.path.abspath(args.flac) if args.flac else None, whisper)
            else:
                report['workflow'] = 'unavailable: no --sox, --flac or --whispercpp executable given; no workflow was run'
        if args.register:
            register(directory / 'kit/qualification.json')
        report['verified'] = True
    finally:
        report['probeProcesses'] = PROCESSES
        atomic_json(directory / 'acceptance.json', report)
        try:
            atomic_json(directory / 'acceptance-public.json', public(report, espeak, directory))
        except Exception as error:    # a failed run still keeps the private record
            print('public report not written:', error, file=sys.stderr)
    print(json.dumps(public(report, espeak, directory), indent=2))


if __name__ == '__main__':
    main()
