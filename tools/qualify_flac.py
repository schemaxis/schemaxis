#!/usr/bin/env python3
"""Bounded native acceptance of lossless FLAC archive and PCM16 decode with FLAC 1.5 `flac`.

Independent literal PCM (the tool regenerates the fixture samples from their recipe and decodes with its own `flac -d` to WAV and
its own parser), hostile real FLAC files with every ordinary receipt hash refreshed (different PCM, corrupted MD5, sample count,
header, body, trailing and truncated bytes, extra metadata, 24-bit), refusals of unknown bit depth, sample rate and container before
any native process, typed/duplicate-key/non-finite retained JSON, the documented `schemaxis verify` routes as real CLI processes, a
receipt-named executable that must never run, missing trusted runtime, output collision, in-flight timeout and cancellation, the
largest accepted budget and the first refused shapes, and a decodePCM16 -> SoX conform workflow when a SoX executable is given.
The tool decodes with flac itself and compares hand-derived values; it does not reuse the adaptor's readers for those expectations.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import random
import re
import shutil
import struct
import subprocess
import sys
import threading
import time

from schemaxis.adaptor_conformance import qualify, register
from schemaxis.adaptors.flac import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.configuration import location_context
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation
from schemaxis import workflow

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'examples/schemaxis/fixtures/flac'
PROCESSES = []
ENCODE = ['-8', '-V', '-s', '-w', '--no-padding', '--no-seektable', '--no-preserve-modtime', '--force-raw-format', '--endian=little', '--sign=signed']


def native(name, command, cwd, timeout=60, env=None, expect=0):
    """Run one probe process directly and keep its real PID, command and exit status."""
    process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    try:
        out, err = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise
    PROCESSES.append({'name': name, 'pid': process.pid, 'timeoutSeconds': timeout, 'command': [Path(command[0]).name, *map(str, command[1:])], 'exitCode': process.returncode})
    assert process.returncode == expect, (name, process.returncode, err[-300:])
    return out if expect == 0 else out + err


class configuration_file:
    """Select a private SCHEMAXIS_CONFIG for a block, then restore the caller's environment."""
    def __init__(self, path, locations):
        self.path, self.locations = Path(path), locations

    def __enter__(self):
        atomic_json(self.path, {'version': 1, 'locations': self.locations})
        self.saved = {k: os.environ.get(k) for k in ('SCHEMAXIS_CONFIG', 'SCHEMAXIS_FLAC')}
        os.environ['SCHEMAXIS_CONFIG'] = str(self.path)
        os.environ.pop('SCHEMAXIS_FLAC', None)

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
    raise AssertionError('invalid FLAC evidence accepted')


# ---------------------------------------------------------------- independent literal samples (the fixture recipe, re-derived here)
def lcg(seed):
    x = seed
    while True:
        x = (x * 1103515245 + 12345) & 0x7fffffff
        yield (x >> 8) % 129 - 64


def channel(frames, seed, pins):
    noise = lcg(seed)
    values = [((i * 7) % 4001) - 2000 + next(noise) for i in range(frames)]
    for index, value in pins.items():
        values[index] = value
    return values


LITERAL = {   # name: (rate, columns, pinned literal rows)
    'mono-8000': (8000, [channel(1001, 1, {0: -32768, 1: 32767, 2: 0, 3: 1, 4: -1, 500: 32767, 1000: -32768})],
                  {(0, 0): -32768, (0, 1): 32767, (0, 2): 0, (0, 3): 1, (0, 4): -1, (0, 500): 32767, (0, 1000): -32768}),
    'stereo-16000': (16000, [channel(2049, 2, {0: -32768, 1: 32766, 2048: 0}), channel(2049, 3, {0: 32767, 1: -32767, 2048: -1})],
                     {(0, 0): -32768, (0, 1): 32766, (0, 2048): 0, (1, 0): 32767, (1, 1): -32767, (1, 2048): -1}),
    'stereo-48000': (48000, [channel(4099, 4, {0: 1, 4096: 32767, 4098: -32768}), channel(4099, 5, {0: -32768, 2048: 20000, 4098: -1})],
                     {(0, 0): 1, (0, 4096): 32767, (0, 4098): -32768, (1, 0): -32768, (1, 2048): 20000, (1, 4098): -1})}


def literal_pcm(name):
    rate, columns, pins = LITERAL[name]
    frames = len(columns[0])
    return rate, len(columns), b''.join(struct.pack('<h', columns[c][i]) for i in range(frames) for c in range(len(columns))), pins


def sample(pcm, channels, channel_index, frame):
    return struct.unpack_from('<h', pcm, 2 * (frame * channels + channel_index))[0]


def wav_data(data):
    """Independent tiny WAV parser: geometry and the data chunk of any RIFF/WAVE a native tool wrote."""
    assert data[:4] == b'RIFF' and data[8:12] == b'WAVE'
    offset, fmt = 12, None
    while offset + 8 <= len(data):
        kind, size = data[offset:offset + 4], struct.unpack_from('<I', data, offset + 4)[0]
        if kind == b'fmt ':
            fmt = struct.unpack_from('<HHIIHH', data, offset + 8)
        if kind == b'data':
            return fmt, data[offset + 8:offset + 8 + size]
        offset += 8 + size + (size & 1)
    raise AssertionError('no data chunk')


def streaminfo_of(data):
    """Independent STREAMINFO reader: (rate, channels, bits, total samples, md5 hex) at its fixed offset."""
    assert data[:4] == b'fLaC' and data[4] & 0x7f == 0
    packed = int.from_bytes(data[18:26], 'big')
    return packed >> 44, ((packed >> 41) & 7) + 1, ((packed >> 36) & 31) + 1, packed & 0xfffffffff, data[26:42].hex()


def patch_info(data, rate=None, channels=None, bits=None, total=None, md5=None):
    rate0, channels0, bits0, total0, md50 = streaminfo_of(data)
    packed = ((rate if rate is not None else rate0) << 44) | (((channels if channels is not None else channels0) - 1) << 41) \
        | (((bits if bits is not None else bits0) - 1) << 36) | (total if total is not None else total0)
    return data[:18] + packed.to_bytes(8, 'big') + (bytes.fromhex(md5) if md5 is not None else bytes.fromhex(md50)) + data[42:]


def flac_encode(flac, work, name, raw, rate, channels, bps=16, extra=()):
    source = Path(work) / (name + '.raw')
    source.write_bytes(raw)
    target = Path(work) / (name + '.flac')
    target.unlink(missing_ok=True)
    native('encode-' + name, [flac, *ENCODE, '--bps=%d' % bps, '--channels=%d' % channels, '--sample-rate=%d' % rate, *extra, '-o', str(target), str(source)], work)
    return target.read_bytes()


def independent_decode(flac, data, work, name):
    """Decode with flac to a native WAV and parse it with this tool's own reader: (rate, channels, bits, pcm)."""
    source, target = Path(work) / (name + '.flac'), Path(work) / (name + '-independent.wav')
    source.write_bytes(data)
    target.unlink(missing_ok=True)
    native('independent-decode-' + name, [flac, '-d', '-s', '-w', '--no-preserve-modtime', '-o', str(target), str(source)], work)
    fmt, pcm = wav_data(target.read_bytes())
    return fmt[2], fmt[1], fmt[5], pcm


# ---------------------------------------------------------------- forging helpers (the dishonest writer the verifier must survive)
def refresh(run, rewrite_summary=True):
    """Rebind every ordinary hash, and optionally rebuild the summary and result claims, as a fully consistent forging writer would."""
    run = Path(run)
    operation = json.loads((run / 'plan.json').read_text())['operation']
    if operation == 'encodeLossless':
        atomic_json(run / 'encode-inputs.json', {'source.pcm': adaptor.digest(run, 'source.pcm')})
        atomic_json(run / 'decode-inputs.json', {'audio.flac': adaptor.digest(run, 'audio.flac')})
    else:
        atomic_json(run / 'decode-inputs.json', {'captured.flac': adaptor.digest(run, 'captured.flac')})
    rewritten = False
    if rewrite_summary:
        try:
            prepared = adaptor.plan(json.loads((run / 'authored.json').read_text()))
            observation = adaptor.observe(run, prepared, adaptor.runtime(), {})
            atomic_json(run / 'flac-summary.json', observation['summary'])
            result = adaptor.read_json(run, 'result.json')
            atomic_json(run / 'result.json', {**result, 'bytes': {'flac': len((run / ('audio.flac' if operation == 'encodeLossless' else 'captured.flac')).read_bytes()),
                                                                  'wav': result['bytes']['wav']}})
            rewritten = True
        except SchemaxisError:
            pass    # a forgery the verifier's own observation already refuses keeps the stale summary
    rebind(run)
    return rewritten


def rebind(run):
    run = Path(run)
    operation = json.loads((run / 'plan.json').read_text())['operation']
    receipt = adaptor.read_json(run, 'verification.json')
    receipt['evidence'] = {n: adaptor.digest(run, n) for n in sorted(receipt['evidence'])}
    receipt['artifacts'] = adaptor.publications(run, operation)
    atomic_json(run / 'verification.json', receipt)
    from schemaxis.publication_metadata import finalise
    finalise(run)    # the shared publication manifest is rebound too


def snapshot(run):
    return {p: p.read_bytes() for p in Path(run).rglob('*') if p.is_file()}


def restore(saved):
    for path, content in saved.items():
        path.write_bytes(content)


def verify_fault(run, flac):
    try:
        adaptor.verify(run, executable=flac)
    except SchemaxisError as error:
        return error.fault
    raise AssertionError('accepted')


# ---------------------------------------------------------------- acceptance sections
def literal_checks(kit, flac, work):
    """Every PCM byte of every published or decoded file equals the independently derived literal samples."""
    report = {}
    for case, name, operation in (('baseline', 'stereo-48000', 'encode'), ('variant', 'mono-8000', 'encode'), ('decode', 'stereo-16000', 'decode'), ('decode-tagged', 'stereo-16000', 'decode')):
        rate, channels, pcm, pins = literal_pcm(name)
        run = kit / case
        for (index, frame), value in pins.items():
            assert sample(pcm, channels, index, frame) == value, (name, index, frame)
        if operation == 'encode':
            data = (run / 'audio.flac').read_bytes()
            info_rate, info_channels, bits, total, md5 = streaminfo_of(data)
            assert (info_rate, info_channels, bits, total) == (rate, channels, 16, len(pcm) // (2 * channels)), name
            import hashlib
            assert md5 == hashlib.md5(pcm).hexdigest()
            assert independent_decode(flac, data, work, case) == (rate, channels, 16, pcm), name
            assert (run / 'source.pcm').read_bytes() == pcm and (run / 'reopened.pcm').read_bytes() == pcm
        else:
            fmt, published = wav_data((run / 'audio.wav').read_bytes())
            assert fmt == (1, channels, rate, rate * 2 * channels, 2 * channels, 16) and published == pcm, name
            assert (run / 'audio.wav').stat().st_size == 44 + len(pcm)
            assert independent_decode(flac, (run / 'captured.flac').read_bytes(), work, case) == (rate, channels, 16, pcm)
        report[case] = {'fixture': name, 'rate': rate, 'channels': channels, 'frames': len(pcm) // (2 * channels), 'pcmBytes': len(pcm),
                        'pinnedLiteralRows': len(pins), 'everyPcmByteEqualsRecipe': True}
    return report


def hostile_encode(kit, flac, work):
    """Real flac outputs replace audio.flac and every ordinary hash is refreshed; only decoding the actual bytes can decide."""
    run, report = kit / 'baseline', {}
    rate, channels, pcm, _ = literal_pcm('stereo-48000')
    good = (run / 'audio.flac').read_bytes()
    saved = snapshot(run)
    changed = bytearray(pcm)
    changed[400] ^= 1
    different = flac_encode(flac, work, 'different-pcm', bytes(changed), rate, channels)
    forged_md5 = good[:26] + bytes([good[26] ^ 1]) + good[27:]
    offset = good.index(b'\xff\xf8', 8)
    variants = {
        'differentPcmSameGeometry': different,
        'streaminfoMd5Flipped': forged_md5,
        'sampleCountPlusOne': patch_info(good, total=4100),
        'sampleCountMinusOne': patch_info(good, total=4098),
        'firstFrameHeaderByteFlipped': good[:offset + 3] + bytes([good[offset + 3] ^ 0x10]) + good[offset + 4:],
        'bodyByteFlipped': good[:offset + 40] + bytes([good[offset + 40] ^ 0x55]) + good[offset + 41:],
        'trailingBytes': good + b'\0' * 5,
        'truncated': good[:-10],
        'twentyFourBit': flac_encode(flac, work, 'bits24', b''.join(pcm[i:i + 2] + b'\0' for i in range(0, len(pcm), 2)), rate, channels, bps=24),
        'extraMetadataSamePcm': flac_encode(flac, work, 'tagged', pcm, rate, channels, extra=['--tag=TITLE=forged', '--padding=64']),
        'differentRate': flac_encode(flac, work, 'rate44100', pcm, 44100, channels),
        'mono': flac_encode(flac, work, 'mono', pcm[:2 * 4099], rate, 1),
    }
    try:
        for label, data in variants.items():
            assert data != good, label
            (run / 'audio.flac').write_bytes(data)
            fault = refused(lambda: adaptor.verify(run, executable=flac))
            report[label + 'WithoutRefresh'] = fault.message[:110]
            rewritten = refresh(run)
            fault = verify_fault(run, flac)
            assert fault.code == 'VERIFICATION_FAILED', (label, fault.to_dict())
            report[label] = {'summaryRewritten': rewritten, 'fault': fault.code, 'reason': fault.message[:150]}
            if 'cause' in fault.observed:
                report[label]['originalCause'] = {'code': fault.observed['cause']['code'], 'message': fault.observed['cause']['message'][:170]}
            restore(saved)
        # A different valid lossless encoding of the identical PCM is accepted once every record is rewritten, and only then:
        # verification proves exact PCM identity, not which encoder settings produced the file.
        raw = work / 'effort0.raw'
        raw.write_bytes(pcm)
        effort0 = work / 'effort0.flac'
        effort0.unlink(missing_ok=True)
        native('encode-effort0', [flac, '-0', '-V', '-s', '-w', '--no-padding', '--no-seektable', '--no-preserve-modtime', '--force-raw-format', '--endian=little',
                                  '--sign=signed', '--bps=16', '--channels=%d' % channels, '--sample-rate=%d' % rate, '-o', str(effort0), str(raw)], work)
        fast = effort0.read_bytes()
        assert fast != good and fast[:4] == b'fLaC'
        (run / 'audio.flac').write_bytes(fast)
        report['equivalentEncodingWithoutRefresh'] = refused(lambda: adaptor.verify(run, executable=flac)).message[:100]
        refresh(run, rewrite_summary=False)
        report['equivalentEncodingReceiptRefreshedSummaryStale'] = refused(lambda: adaptor.verify(run, executable=flac)).message[:100]
        refresh(run)
        report['equivalentEncodingFullyRewrittenAccepted'] = adaptor.verify(run, executable=flac)['verified']
    finally:
        restore(saved)
    assert adaptor.verify(run, executable=flac)['verified']
    return report


def understated_count(work, flac):
    """STREAMINFO says one sample fewer on a two-block FLAC: the first frame header still agrees and libFLAC exits 0.

    Verifying a decodePCM16 publication reaches the fresh decode length guard (the only check that can see it); an encodeLossless
    publication is refused earlier, by the captured WAV geometry, which is recorded and not weakened.
    """
    source = FIXTURES / 'stereo-48000.flac'    # 4096 + 3 samples
    forged = patch_info(source.read_bytes(), total=4098)
    document = {'version': 'schemaxis.flac/1', 'operation': 'decodePCM16', 'source': str(source)}
    run = Path(work) / 'understated-decode'
    adaptor.run(document, run, executable=flac, timeout=60)
    (run / 'captured.flac').write_bytes(forged)
    captures = adaptor.read_json(run, 'captures.json')
    atomic_json(run / 'captures.json', {**captures, 'bytes': len(forged), 'sha256': adaptor.sha(forged)})
    refresh(run)
    fault = verify_fault(run, flac)
    assert fault.code == 'VERIFICATION_FAILED' and 'native decode produced' in fault.message, fault.to_dict()
    encoded = Path(work) / 'understated-encode'
    adaptor.run({**document, 'operation': 'encodeLossless', 'source': str(FIXTURES / 'stereo-48000.wav')}, encoded, executable=flac, timeout=60)
    (encoded / 'audio.flac').write_bytes(forged)
    refresh(encoded)
    early = verify_fault(encoded, flac)
    assert early.code == 'VERIFICATION_FAILED' and 'native decode produced' not in early.message, early.to_dict()
    return {'decodeUnderstatedCountTwoBlocks': {'fault': fault.code, 'guard': 'fresh decode length', 'reason': fault.message[:150]},
            'encodeUnderstatedCountTwoBlocks': {'fault': early.code, 'guard': 'captured WAV geometry (earlier host check)', 'reason': early.message[:150]}}


def hostile_decode(kit, flac, work):
    """Published WAV and captured FLAC forgeries with every ordinary hash refreshed."""
    run, report = kit / 'decode', {}
    rate, channels, pcm, _ = literal_pcm('stereo-16000')
    saved = snapshot(run)
    wav = (run / 'audio.wav').read_bytes()
    other = bytearray(pcm)
    other[100] ^= 1
    other_flac = flac_encode(flac, work, 'other', bytes(other), rate, channels)
    good = (run / 'captured.flac').read_bytes()
    try:
        for label, forged in (('wavSampleChanged', wav[:-1] + bytes([wav[-1] ^ 1])), ('wavTruncated', wav[:-4]), ('wavTrailing', wav + b'\0\0'),
                              ('wavHeaderRate', wav[:24] + struct.pack('<I', 8000) + wav[28:])):
            (run / 'audio.wav').write_bytes(forged)
            rebind(run)
            fault = verify_fault(run, flac)
            assert fault.code == 'VERIFICATION_FAILED', label
            report[label] = fault.message[:120]
            restore(saved)
        for label, forged in (('capturedFlacDifferentValidFlac', other_flac), ('capturedFlacMd5Flipped', good[:26] + bytes([good[26] ^ 1]) + good[27:]),
                              ('capturedFlacCountMinusOne', patch_info(good, total=2048))):
            (run / 'captured.flac').write_bytes(forged)
            captures = adaptor.read_json(run, 'captures.json')
            atomic_json(run / 'captures.json', {**captures, 'bytes': len(forged), 'sha256': adaptor.sha(forged)})
            refresh(run)
            fault = verify_fault(run, flac)
            assert fault.code == 'VERIFICATION_FAILED', label
            report[label] = fault.message[:150]
            restore(saved)
        report.update(understated_count(work, flac))
    finally:
        restore(saved)
    assert adaptor.verify(run, executable=flac)['verified']
    return report


def source_refusals(work, flac):
    """Hostile or unsupported real inputs refused at run time: code, location and whether any native process started."""
    rate, channels, pcm, _ = literal_pcm('stereo-16000')
    good = (FIXTURES / 'stereo-16000.flac').read_bytes()
    offset = good.index(b'\xff\xf8', 8)
    cases = {
        'ogg-prefix': (b'OggS' + good[4:], 'UNSUPPORTED_FLAC_FORMAT'), 'id3-prefix': (b'ID3\x04\0\0\0\0\0\0' + good, 'UNSUPPORTED_FLAC_FORMAT'),
        'not-flac': (b'RIFF' + good[4:], 'INVALID_FLAC_STREAM'), 'unknown-bit-depth-24': (flac_encode(flac, work, 'depth24', b''.join(pcm[i:i + 2] + b'\0' for i in range(0, len(pcm), 2)), rate, channels, bps=24), 'UNSUPPORTED_FLAC_FORMAT'),
        'unknown-bit-depth-8': (patch_info(good, bits=8), 'UNSUPPORTED_FLAC_FORMAT'),
        'unknown-sample-rate-7999': (patch_info(good, rate=7999), 'UNSUPPORTED_FLAC_FORMAT'), 'unknown-sample-rate-192001': (patch_info(good, rate=192001), 'UNSUPPORTED_FLAC_FORMAT'),
        'three-channels': (patch_info(good, channels=3), 'UNSUPPORTED_FLAC_FORMAT'), 'unknown-sample-count': (patch_info(good, total=0), 'UNSUPPORTED_FLAC_FORMAT'),
        'zero-md5': (patch_info(good, md5='00' * 16), 'UNSUPPORTED_FLAC_FORMAT'), 'over-duration': (patch_info(good, total=600 * 16000 + 1), 'FLAC_BUDGET'),
        'over-pcm-budget': (patch_info(good, rate=48000, total=adaptor.MAX_PCM_BYTES // 4 + 1), 'FLAC_BUDGET'),
        'first-frame-header-byte': (good[:offset + 3] + bytes([good[offset + 3] ^ 0x10]) + good[offset + 4:], 'INVALID_FLAC_STREAM'),
        'first-frame-crc': (good[:offset + 5] + bytes([good[offset + 5] ^ 1]) + good[offset + 6:], 'INVALID_FLAC_STREAM'),
        'streaminfo-twice': (good[:4] + bytes([good[4] & 0x7f]) + good[5:42] + bytes([0, 0, 0, 34]) + good[8:42] + good[42:], 'INVALID_FLAC_STREAM'),
        'truncated-metadata': (good[:30], 'INVALID_FLAC_STREAM'),
        'single-frame-count-plus-one': (patch_info(good, total=2050), 'INVALID_FLAC_STREAM'), 'single-frame-count-minus-one': (patch_info(good, total=2048), 'INVALID_FLAC_STREAM'),
    }
    report = {}
    for label, (data, code) in cases.items():
        path = Path(work) / ('refusal-' + label + '.flac')
        path.write_bytes(data)
        document = {'version': 'schemaxis.flac/1', 'operation': 'decodePCM16', 'source': str(path)}
        run = Path(work) / ('refusal-run-' + label)
        fault = refused(lambda: adaptor.run(document, run, executable=flac, timeout=60), code)
        assert fault.location == '$.source' and not (run / 'version-submission.json').exists(), label
        report[label] = {'fault': fault.code, 'location': fault.location, 'nativeProcessStarted': False}
    # WAV inputs
    wav = (FIXTURES / 'stereo-16000.wav').read_bytes()
    for label, data, code in (('wav-24-bit', wav[:34] + struct.pack('<H', 24) + wav[36:], 'INVALID_FLAC_WAV'), ('wav-unknown-rate-7999', wav[:24] + struct.pack('<I', 7999) + wav[28:], 'INVALID_FLAC_WAV'),
                              ('wav-float', wav[:20] + struct.pack('<H', 3) + wav[22:], 'INVALID_FLAC_WAV'), ('wav-truncated', wav[:-1], 'INVALID_FLAC_WAV'),
                              ('wav-container-is-flac', good, 'INVALID_FLAC_WAV')):
        path = Path(work) / ('refusal-' + label + '.wav')
        path.write_bytes(data)
        run = Path(work) / ('refusal-run-' + label)
        fault = refused(lambda: adaptor.run({'version': 'schemaxis.flac/1', 'operation': 'encodeLossless', 'source': str(path)}, run, executable=flac, timeout=60), code)
        assert not (run / 'version-submission.json').exists(), label
        report[label] = {'fault': fault.code, 'location': fault.location, 'nativeProcessStarted': False}
    return report


def short_inputs(work, flac):
    """One and fifteen frames (fewer than the 16-sample minimum block size): flac 1.5 keeps STREAMINFO min and max block at 4096."""
    report = {}
    for channels, rate in ((1, 8000), (2, 16000)):
        for frames in (1, 15):
            label = 'c%d-f%d' % (channels, frames)
            pcm = b''.join(struct.pack('<h', (i * 977 + c * 311) % 20000 - 10000) for i in range(frames) for c in range(channels))
            source = Path(work) / ('short-' + label + '.wav')
            source.write_bytes(adaptor.canonical_wav(rate, channels, pcm))
            encoded = adaptor.run({'version': 'schemaxis.flac/1', 'operation': 'encodeLossless', 'source': str(source)}, Path(work) / ('short-' + label + '-encode'), executable=flac, timeout=60)
            published = (Path(work) / ('short-' + label + '-encode/audio.flac')).read_bytes()
            assert streaminfo_of(published)[:4] == (rate, channels, 16, frames) and int.from_bytes(published[8:10], 'big') >= 16, label
            assert independent_decode(flac, published, work, 'short-' + label) == (rate, channels, 16, pcm), label
            assert adaptor.verify(Path(work) / ('short-' + label + '-encode'), executable=flac)['verified']
            decoded = adaptor.run({'version': 'schemaxis.flac/1', 'operation': 'decodePCM16', 'source': str(Path(work) / ('short-' + label + '-encode/audio.flac'))},
                                  Path(work) / ('short-' + label + '-decode'), executable=flac, timeout=60)
            assert (Path(work) / ('short-' + label + '-decode/audio.wav')).read_bytes() == source.read_bytes(), label
            report[label] = {'frames': frames, 'minBlockSize': int.from_bytes(published[8:10], 'big'), 'flacBytes': encoded['bytes']['flac'], 'verified': encoded['verified'] and decoded['verified'],
                             'decodedWavIdenticalToSource': True}
    return report


def native_rejections(work, flac):
    """Real damaged FLAC inputs that pass the host framing checks: the native decoder (or the length check) refuses them."""
    good = (FIXTURES / 'stereo-48000.flac').read_bytes()    # two frames (4096 + 3 samples): a wrong count is not already visible in the first frame
    offset = good.index(b'\xff\xf8', 8)
    cases = {'md5-flipped': good[:26] + bytes([good[26] ^ 1]) + good[27:], 'count-plus-one': patch_info(good, total=4100), 'count-minus-one-native-accepts': patch_info(good, total=4098),
             'body-byte-flipped': good[:offset + 40] + bytes([good[offset + 40] ^ 0x55]) + good[offset + 41:], 'trailing-bytes': good + b'\0' * 5, 'truncated-body': good[:-10]}
    report = {}
    for label, data in cases.items():
        path = Path(work) / ('native-' + label + '.flac')
        path.write_bytes(data)
        run = Path(work) / ('native-run-' + label)
        fault = refused(lambda: adaptor.run({'version': 'schemaxis.flac/1', 'operation': 'decodePCM16', 'source': str(path)}, run, executable=flac, timeout=60), 'FLAC_STREAM_REJECTED')
        assert not (run / 'audio.wav').exists() and adaptor.read_json(run, 'result.json')['status'] == 'failed', label
        report[label] = {'fault': fault.code, 'nativeCause': (fault.observed.get('cause') or {}).get('message', '')[:140] or None, 'message': fault.message[:120]}
    assert report['count-minus-one-native-accepts']['nativeCause'] is None     # libFLAC accepted it; the host length check refused it
    return report


def retained_json(kit, flac):
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
    cases = [('summaryBooleanAsInteger', 'flac-summary.json', first('"exactPcm": true', '"exactPcm": 1'), True),
             ('summaryFramesAsFloat', 'flac-summary.json', to_float(r'("audio": \{.*?"frames": )(\d+)'), True),
             ('summaryDuplicateKey', 'flac-summary.json', first('"exactPcm": true', '"exactPcm": false, "exactPcm": true'), False),
             ('summaryNaN', 'flac-summary.json', first('"exactPcm": true', '"exactPcm": NaN'), False),
             ('summaryOverflow1e400', 'flac-summary.json', first('"exactPcm": true', '"exactPcm": 1e400'), False),
             ('capturesBytesAsFloat', 'captures.json', to_float(r'("bytes": )(\d+)'), True),
             ('decodeInputsDuplicateKey', 'decode-inputs.json', leading('"audio.flac": "0"'), False),
             ('resultBooleanAsInteger', 'result.json', first('"verified": true', '"verified": 1'), True),
             ('resultCountAsFloat', 'result.json', first('"artifacts": 2', '"artifacts": 2.0'), True),
             ('resultDuplicateStatus', 'result.json', leading('"status": "failed"'), False),
             ('receiptNaN', 'verification.json', leading('"extra": NaN'), False),
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
            fault = verify_fault(run, flac)
            assert fault.code == 'VERIFICATION_FAILED', fault.to_dict()
            report[label] = {'pythonEqualityWouldCollapse': collapses, 'fault': fault.code, 'reason': fault.message[:100]}
            restore(saved)
    finally:
        restore(saved)
    assert adaptor.verify(run, executable=flac)['verified']
    return report


def trusted_runtime(kit, flac, work):
    """Receipt executables are inert; a missing trusted flac is unavailable, never verified."""
    run = kit / 'baseline'
    marker = Path(work) / 'sentinel.marker'
    trap = Path(work) / 'sentinel-flac'
    trap.write_text('#!%s\nfrom pathlib import Path\nPath(%r).write_text("ran")\n' % (sys.executable, str(marker)))
    trap.chmod(0o700)
    saved = snapshot(run)
    report = {}
    try:
        receipt = adaptor.read_json(run, 'verification.json')
        receipt['executables']['flac'] = str(trap)
        atomic_json(run / 'verification.json', receipt)
        # a separate process: the caller's location scope cannot be emptied from inside it, and a clean environment is the honest absence test
        atomic_json(work / 'absent-config.json', {'version': 1, 'locations': {}})
        probe = ('import sys\nfrom pathlib import Path\nfrom schemaxis.adaptors.flac import adaptor\n'
                 'try:\n    adaptor.verify(Path(sys.argv[1]))\nexcept Exception as error:\n    print(error.fault.code, error.fault.location)\nelse:\n    print("verified")\n')
        environment = {k: v for k, v in os.environ.items() if not k.startswith('SCHEMAXIS_')} | {'PYTHONPATH': str(ROOT / 'src'), 'SCHEMAXIS_CONFIG': str(work / 'absent-config.json')}
        outcome = native('verify-without-trusted-flac', [sys.executable, '-c', probe, str(run)], work, env=environment).decode().strip()
        assert outcome == 'INTERPRETER_NOT_FOUND $.runtime.flac', outcome
        report['withoutTrustedFlac'] = outcome
        assert not marker.exists()
        rebind(run)
        report['receiptNamesDifferentExecutable'] = verify_fault(run, flac).message[:90]
        assert not marker.exists()
        report['receiptExecutableNeverLaunched'] = True
    finally:
        restore(saved)
    for label, bad in (('relativeName', 'flac'), ('missingFile', str(Path(work) / 'missing')), ('notExecutable', str(run / 'captured.wav'))):
        report[label] = refused(lambda: adaptor.verify(run, executable=bad), 'INTERPRETER_NOT_FOUND').code
    wrong = Path(work) / 'old-flac'
    wrong.write_text('#!%s\nprint("flac 1.4.3")\n' % sys.executable)
    wrong.chmod(0o700)
    report['wrongVersion'] = refused(lambda: adaptor.verify(run, executable=str(wrong)), 'UNSUPPORTED_RUNTIME').code
    report['pathIsNotSearched'] = 'verified only through explicit, stored or SCHEMAXIS_FLAC locations'
    return report


def cli_verify(run, flac, work):
    """The documented routes for bare `schemaxis verify`: SCHEMAXIS_FLAC or a stored flac location; there is no --flac flag."""
    base = {k: v for k, v in os.environ.items() if not k.startswith('SCHEMAXIS_')}
    base['PYTHONPATH'] = str(ROOT / 'src')
    atomic_json(work / 'cli-empty.json', {'version': 1, 'locations': {}})
    atomic_json(work / 'cli-stored.json', {'version': 1, 'locations': {'flac': flac}})
    command = [sys.executable, '-m', 'schemaxis', 'verify', str(run)]
    report = {'environmentVariable': json.loads(native('cli-verify-environment', command, work, env={**base, 'SCHEMAXIS_CONFIG': str(work / 'cli-empty.json'), 'SCHEMAXIS_FLAC': flac}))['verified'],
              'storedLocation': json.loads(native('cli-verify-stored-location', command, work, env={**base, 'SCHEMAXIS_CONFIG': str(work / 'cli-stored.json')}))['verified']}
    missing = native('cli-verify-without-flac', command, work, env={**base, 'SCHEMAXIS_CONFIG': str(work / 'cli-empty.json')}, expect=1).decode()
    assert 'INTERPRETER_NOT_FOUND' in missing, missing[-300:]
    report['withoutFlac'] = 'INTERPRETER_NOT_FOUND'
    flag = native('cli-verify-with-flac-flag', [*command, '--flac', flac], work, env={**base, 'SCHEMAXIS_CONFIG': str(work / 'cli-empty.json')}, expect=2).decode()
    assert 'unrecognized arguments' in flag and '--flac' in flag, flag[-300:]
    report['flacFlagOnBareVerify'] = 'rejected by the argument parser (exit 2): the flag belongs to run and inspect'
    return report


def lifecycle(work, flac):
    wrapper = work / 'slow-flac.py'
    marker = work / 'slow.pid'
    wrapper.write_text('#!%s\nimport os, sys, time\nfrom pathlib import Path\nif sys.argv[1:] == ["--version"]:\n    print("flac 1.5.0"); sys.exit(0)\nPath(%r).write_text(str(os.getpid()))\ntime.sleep(30)\n' % (sys.executable, str(marker)))
    wrapper.chmod(0o700)
    document = {'version': 'schemaxis.flac/1', 'operation': 'encodeLossless', 'source': str(FIXTURES / 'mono-8000.wav')}
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
                results[action] = refused(lambda: adaptor.run(document, work / ('inflight-' + action), executable=str(wrapper), timeout=10 if thread else 2),
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
    results['outputCollision'] = refused(lambda: adaptor.run(document, work / 'inflight-timeout', executable=flac, timeout=30), 'OUTPUT_EXISTS').code
    return results


def budget(work, flac):
    """Largest accepted shapes with observed wall time, and the first refused ones before any native process."""
    report, rng = {}, random.Random(41)
    shapes = (('stereo-44100-max-pcm-noise', 44100, 2, adaptor.MAX_PCM_BYTES // 4, 'noise'), ('mono-8000-600-seconds-ramp', 8000, 1, 600 * 8000, 'ramp'))
    for label, rate, channels, frames, kind in shapes:
        pcm = rng.randbytes(frames * channels * 2) if kind == 'noise' else b''.join(struct.pack('<h', (i * 3) % 20001 - 10000) for i in range(frames))
        source = work / (label + '.wav')
        source.write_bytes(adaptor.canonical_wav(rate, channels, pcm))
        start = time.monotonic()
        encoded = adaptor.run({'version': 'schemaxis.flac/1', 'operation': 'encodeLossless', 'source': str(source)}, work / (label + '-encode'), executable=flac, timeout=600)
        encode_seconds = time.monotonic() - start
        start = time.monotonic()
        assert adaptor.verify(work / (label + '-encode'), executable=flac)['verified']
        verify_seconds = time.monotonic() - start
        start = time.monotonic()
        decoded = adaptor.run({'version': 'schemaxis.flac/1', 'operation': 'decodePCM16', 'source': str(work / (label + '-encode/audio.flac'))}, work / (label + '-decode'), executable=flac, timeout=600)
        decode_seconds = time.monotonic() - start
        assert (work / (label + '-decode/audio.wav')).read_bytes() == source.read_bytes()
        report[label] = {'frames': frames, 'wavBytes': source.stat().st_size, 'flacBytes': encoded['bytes']['flac'], 'encodeRunSeconds': round(encode_seconds, 1),
                         'verifySeconds': round(verify_seconds, 1), 'decodeRunSeconds': round(decode_seconds, 1), 'decodedWavIdenticalToSource': True, 'verified': encoded['verified'] and decoded['verified']}
        shutil.rmtree(work / (label + '-encode'))
        shutil.rmtree(work / (label + '-decode'))
        source.unlink()
    # four PCM bytes over the budget make the WAV file itself exceed 32 MiB, so the file bound refuses it before any WAV parsing
    for label, rate, channels, frames, code in (('over-pcm-budget', 44100, 2, adaptor.MAX_PCM_BYTES // 4 + 1, 'INVALID_FLAC_SOURCE'), ('over-duration', 8000, 1, 600 * 8000 + 1, 'FLAC_BUDGET')):
        source = work / ('over-' + label + '.wav')
        pcm = bytes(frames * channels * 2)
        try:
            source.write_bytes(adaptor.canonical_wav(rate, channels, pcm))
        except Exception:
            raise
        run = work / ('over-' + label)
        fault = refused(lambda: adaptor.run({'version': 'schemaxis.flac/1', 'operation': 'encodeLossless', 'source': str(source)}, run, executable=flac, timeout=60), code)
        assert not (run / 'version-submission.json').exists()
        report[label + 'Refused'] = {'fault': fault.code, 'message': fault.message[:100], 'nativeProcessStarted': False}
        source.unlink()
    return report


def sox_workflow(work, flac, sox):
    """decodePCM16 -> SoX conform (speech preparation) and WAV -> FLAC -> WAV chain, with byte-change reuse invalidation."""
    locations = {'flac': flac, 'sox': sox}
    source = work / 'recording.flac'
    shutil.copyfile(FIXTURES / 'stereo-16000.flac', source)
    graph = {'version': 'schemaxis.workflow/1', 'operations': [
        {'id': 'decode', 'document': {'version': 'schemaxis.flac/1', 'operation': 'decodePCM16', 'source': str(source)}},
        {'id': 'speech', 'document': {'version': 'schemaxis.sox/1', 'operation': 'conform', 'source': {'$artifact': 'decode', 'index': 0}, 'channelPolicy': 'average'}}]}
    first = workflow.execute(graph, work / 'speech-workflow', locations=locations, timeout=240)
    assert first['status'] == 'succeeded'
    with location_context(locations):
        assert workflow.verify(work / 'speech-workflow')['verified']
    root = work / 'speech-workflow'
    speech = [p for p in root.rglob('audio.wav') if p.relative_to(root).parts[0] == 'speech']
    decoded = [p for p in root.rglob('audio.wav') if p.relative_to(root).parts[0] == 'decode']
    assert len(speech) == 1 and len(decoded) == 1
    fmt, pcm = wav_data(speech[0].read_bytes())
    rate, channels, source_pcm, _ = literal_pcm('stereo-16000')
    expected = b''.join(struct.pack('<h', (sample(source_pcm, 2, 0, i) + sample(source_pcm, 2, 1, i) + 1) >> 1) for i in range(2049))
    assert (fmt[1], fmt[2], fmt[5], len(pcm)) == (1, 16000, 16, 2 * 2049) and pcm == expected    # same-rate average is exact: the host and SoX agree
    second = workflow.execute(graph, work / 'speech-workflow', locations=locations, timeout=240, resume=True)
    assert all(job['reused'] for job in second['jobs'])
    (work / 'recording.flac').write_bytes((FIXTURES / 'tagged-stereo-16000.flac').read_bytes())
    third = workflow.execute(graph, work / 'speech-workflow', locations=locations, timeout=240, resume=True)
    assert all(not job['reused'] for job in third['jobs'])
    archive = {'version': 'schemaxis.workflow/1', 'operations': [
        {'id': 'archive', 'document': {'version': 'schemaxis.flac/1', 'operation': 'encodeLossless', 'source': str(FIXTURES / 'stereo-48000.wav')}},
        {'id': 'restore', 'document': {'version': 'schemaxis.flac/1', 'operation': 'decodePCM16', 'source': {'$artifact': 'archive', 'index': 0}}}]}
    chain = workflow.execute(archive, work / 'archive-workflow', locations=locations, timeout=240)
    assert chain['status'] == 'succeeded'
    restored = list((work / 'archive-workflow').rglob('audio.wav'))
    assert len(restored) == 1 and restored[0].read_bytes() == (FIXTURES / 'stereo-48000.wav').read_bytes()
    return {'decodeThenSoxConform': first['status'], 'conformedMonoSamplesEqualIndependentAverage': True, 'unchangedReused': True, 'changedSamePathSourceBytesReused': False,
            'wavToFlacToWavIdentical': True, 'soxRuntime': native('sox-version', [sox, '--version'], work, timeout=20).decode().strip()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--flac', type=Path, required=True, help='absolute FLAC 1.5 flac')
    parser.add_argument('--sox', type=Path, help='absolute SoX 14.4.2 sox for the decode -> conform workflow smoke (reported unavailable when absent)')
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--register', action='store_true', help='retain the native receipt in the source package (only after shared integration freezes)')
    parser.add_argument('--skip-budget', action='store_true')
    args = parser.parse_args()
    directory = args.output_directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    flac = str(args.flac.absolute())
    locations = {'flac': flac}
    report = {'verified': False, 'acceptancePid': os.getpid()}
    try:
        report['runtime'] = {'flac': native('flac-version', [flac, '--version'], directory).decode().strip()}
        with configuration_file(directory / 'config.json', locations):
            receipt = qualify(adaptor.VERSION, directory / 'kit', native=True, root=ROOT, locations=locations, timeout=60, wall_timeout=240)
        report['native'] = {'verified': receipt['verified'], 'cases': [c['id'] for c in receipt['cases']], 'runtimes': [c['runtime'] for c in receipt['cases']], 'lifecycle': receipt['lifecycle']}
        kit = directory / 'kit'
        with configuration_file(directory / 'config-empty.json', {}):
            report['verifyWithoutConfiguredFlac'] = refused(lambda: adaptor.verify(kit / 'baseline'), 'INTERPRETER_NOT_FOUND').code
        with configuration_file(directory / 'config-with-flac.json', locations):
            report['verifyWithStoredFlac'] = adaptor.verify(kit / 'baseline')['verified']
        work = directory / 'work'
        work.mkdir()
        with location_context(locations):
            report['literalPcm'] = literal_checks(kit, flac, work)
            report['hostileEncode'] = hostile_encode(kit, flac, work)
            report['hostileDecode'] = hostile_decode(kit, flac, work)
            report['sourceRefusals'] = source_refusals(work, flac)
            report['shortInputs'] = short_inputs(work, flac)
            report['nativeRejections'] = native_rejections(work, flac)
            report['retainedJson'] = retained_json(kit, flac)
            report['trustedRuntime'] = trusted_runtime(kit, flac, work)
            report['cliVerifyRoutes'] = cli_verify(kit / 'baseline', flac, work)
            report['inflightLifecycle'] = lifecycle(work, flac)
            if not args.skip_budget:
                report['budget'] = budget(work, flac)
            if args.sox:
                report['workflow'] = sox_workflow(work, flac, str(args.sox.absolute()))
            else:
                report['workflow'] = 'unavailable: no --sox executable given; the decode -> conform smoke was not run'
        if args.register:
            register(directory / 'kit/qualification.json')
        report['verified'] = True
    finally:
        report['probeProcesses'] = PROCESSES
        atomic_json(directory / 'acceptance.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
