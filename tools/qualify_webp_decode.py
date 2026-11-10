#!/usr/bin/env python3
"""Bounded native acceptance of decodeToPng with libwebp 1.6 dwebp and cwebp (cwebp only makes this tool's inputs).

A decodeToPng run or verification itself needs only dwebp; this qualifier requires --webp (cwebp) because it builds its
round-trip, lossy and legacy-comparison inputs with the real encoder. Its output is a private probe record with local
executable paths, command lines and PIDs. It is not a public receipt and is not wired into ``schemaxis adaptor conform``.

A hand-written 4x3 RGBA literal (partial alpha and RGB hidden under alpha 0) is encoded by the real cwebp
(``-lossless -exact`` and lossy), decoded by the adaptor, and every PNG sample is compared with the literal
through this tool's own PAM and PNG-row readers. Lossy output is compared with a direct dwebp decode, never with the
original picture. The dwebp launches of the adaptor *runs* in sections 1-4b and the section 7 run go through a logging wrapper that
records PID and arguments before ``exec``; section 8 records its stall wrappers separately, as do the direct probes; the verify-only calls (sections 5-7), the legacy
runs and verifications (section 9) and the command-line runs use the plain dwebp, and their launches have no recorded PID.
The record states this split. Also covered: hand-set VP8 upscaling-bit combinations compared with a direct dwebp decode,
a verify-time alpha-hint forgery, real animated and VP8X/ALPH files, truncated,
bit-flipped and header-forged files, tampered PNGs with every hash refreshed, a decoder-only configuration, the real CLI,
timeout and cancellation, unchanged legacy encode plans/artifacts/receipts compared against the unmodified adaptor
module, read-only verification of legacy receipts, and a Pandoc handoff of the published PNG. It claims semantic agreement
with libwebp 1.6, not an independent WebP decoder, source authenticity or any perceptual quality.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import sys
import threading
import time
import zlib

from schemaxis.adaptors.webp import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'examples/schemaxis/fixtures/webp'
PROCESSES = []
LITERAL = [[(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 255, 255)],
           [(10, 20, 30, 128), (200, 100, 50, 64), (7, 8, 9, 0), (250, 251, 252, 0)],
           [(0, 0, 0, 255), (128, 128, 128, 255), (1, 2, 3, 1), (254, 253, 252, 254)]]
LITERAL_BYTES = bytes(v for row in LITERAL for pixel in row for v in pixel)


def pam(width, height, rgba):
    return b'P7\nWIDTH %d\nHEIGHT %d\nDEPTH 4\nMAXVAL 255\nTUPLTYPE RGB_ALPHA\nENDHDR\n' % (width, height) + rgba


def read_pam(data):
    """This tool's own PAM reader (independent of the adaptor's)."""
    head, _, body = data.partition(b'ENDHDR\n')
    fields = dict(line.split(b' ', 1) for line in head.split(b'\n')[1:] if line)
    width, height = int(fields[b'WIDTH']), int(fields[b'HEIGHT'])
    assert len(body) == 4 * width * height and fields[b'DEPTH'] == b'4', 'PAM'
    return width, height, body


def png_rows(data):
    """This tool's own PNG reader for IHDR/IDAT/IEND filter-none files: returns (width, height, channels, rgba)."""
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    offset, chunks = 8, []
    while offset < len(data):
        length, kind = struct.unpack_from('>I4s', data, offset)
        chunks.append((kind, data[offset + 8:offset + 8 + length]))
        assert zlib.crc32(kind + chunks[-1][1]) == struct.unpack_from('>I', data, offset + 8 + length)[0]
        offset += length + 12
    assert [k for k, _ in chunks] == [b'IHDR', b'IDAT', b'IEND'], [k for k, _ in chunks]
    width, height, depth, colour = struct.unpack('>IIBB', chunks[0][1][:10])
    channels = {2: 3, 6: 4}[colour]
    raw = zlib.decompress(chunks[1][1])
    stride = channels * width
    assert depth == 8 and len(raw) == (stride + 1) * height
    pixels = bytearray()
    for y in range(height):
        row = raw[y * (stride + 1):(y + 1) * (stride + 1)]
        assert row[0] == 0
        for x in range(width):
            pixel = row[1 + x * channels:1 + (x + 1) * channels]
            pixels += pixel + (b'\xff' if channels == 3 else b'')
    return width, height, channels, bytes(pixels)


def native(name, command, cwd, timeout=60, expect=0):
    """Run one probe directly and keep its real PID, command and exit status."""
    process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, err = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        PROCESSES.append({'name': name, 'pid': process.pid, 'timeoutSeconds': timeout, 'command': [Path(command[0]).name, *map(str, command[1:])], 'exitCode': 'timeout'})
        raise
    PROCESSES.append({'name': name, 'pid': process.pid, 'timeoutSeconds': timeout, 'command': [Path(command[0]).name, *map(str, command[1:])], 'exitCode': process.returncode})
    assert process.returncode == expect, (name, process.returncode, err[-300:])
    return out + err if expect else out


def refused(action, *codes):
    try:
        action()
    except SchemaxisError as error:
        assert error.fault.code in codes, error.fault.to_dict()
        return {'code': error.fault.code, 'location': error.fault.location, 'message': error.fault.message[:160]}
    raise AssertionError('accepted; expected one of %s' % (codes,))


def tree_hash(directory):
    result = {}
    for path in sorted(Path(directory).rglob('*')):
        if path.is_file():
            result[str(path.relative_to(directory))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def refresh(directory):
    """Make every ordinary hash agree with the tampered files, as a forging writer would."""
    directory = Path(directory)
    receipt = adaptor.read_json(directory, 'verification.json')
    atomic_json(directory / 'decode-inputs.json', {'captured.webp': adaptor.digest(directory, 'captured.webp')})
    atomic_json(directory / 'captures.json', {**adaptor.read_json(directory, 'captures.json'), 'bytes': (directory / 'captured.webp').stat().st_size,
                                              'sha256': adaptor.digest(directory, 'captured.webp')})
    receipt['evidence'] = {n: adaptor.digest(directory, n) for n in sorted(receipt['evidence'])}
    receipt['artifacts'] = adaptor.publications(directory, image='image.png')
    atomic_json(directory / 'verification.json', receipt)


def wrapper(path, real, log, delay=0, reached=None):
    """A decoder that logs its PID and arguments, optionally sleeps, then execs the real dwebp.

    With a delay the wrapper sleeps BEFORE the exec, so an owned stop during the sleep ends the wrapper shell and the real
    dwebp is never started; ``reached`` is a marker written just before the exec to prove that.
    """
    marker = 'echo reached >> %s\n' % reached if reached else ''
    path.write_text('#!/bin/sh\necho "$$ $*" >> %s\n%s%sexec %s "$@"\n' % (log, 'sleep %d\n' % delay if delay else '', marker, real))
    path.chmod(0o700)
    return str(path)


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dwebp', type=Path, required=True)
    parser.add_argument('--webp', type=Path, required=True, help='cwebp; makes the round-trip, lossy and legacy-comparison inputs (decodeToPng itself needs only dwebp)')
    parser.add_argument('--pandoc', type=Path)
    parser.add_argument('--baseline-adaptor', type=Path, help='the unmodified adaptor.py, for the legacy comparison')
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    out = args.output_directory.absolute()
    out.mkdir(parents=True)
    dwebp, cwebp = str(args.dwebp.absolute()), str(args.webp.absolute())
    bin_dir = Path(dwebp).parent
    log = out / 'adaptor-dwebp-launches.log'
    log.write_text('')
    logged = wrapper(out / 'dwebp-logged', dwebp, log)
    record = {'scope': 'bounded decodeToPng acceptance, serial, libwebp 1.6; not independent-decoder, authenticity or perceptual evidence', 'cases': {}}
    per_run = record['wrapperLoggedLaunchesPerRun'] = {}
    cases = record['cases']
    scratch = out / 'inputs'
    scratch.mkdir()

    def encode(name, rgba, width, height, *flags):
        (scratch / (name + '.pam')).write_bytes(pam(width, height, rgba))
        native('cwebp-' + name, [cwebp, *flags, name + '.pam', '-o', name + '.webp'], scratch)
        return scratch / (name + '.webp')

    def launches():
        return len(log.read_text().splitlines())

    def decode(name, source, decoder=logged, timeout=60):
        before = launches()
        try:
            return adaptor.run({'version': 'schemaxis.webp/1', 'operation': 'decodeToPng', 'source': str(source)}, out / name, decoder=decoder, timeout=timeout)
        finally:
            if decoder == logged:
                per_run[name] = launches() - before

    # 1. hand-literal lossless round trip with hidden RGB (actual cwebp -exact -> adaptor -> own readers)
    source = encode('literal', LITERAL_BYTES, 4, 3, '-lossless', '-exact', '-z', '6')
    result = decode('literal', source)
    assert per_run['literal'] == 6, ('a successful shared-entry-point run makes six wrapper-logged dwebp launches', per_run)
    width, height, channels, samples = png_rows((out / 'literal/image.png').read_bytes())
    assert (width, height, channels, samples) == (4, 3, 4, LITERAL_BYTES), 'literal round trip'
    assert samples[4 * 6:4 * 6 + 4] == bytes([7, 8, 9, 0]) and samples[4 * 7:4 * 7 + 4] == bytes([250, 251, 252, 0])
    summary = json.loads((out / 'literal/webp-summary.json').read_text())
    assert summary['pixels'] == {'total': 12, 'opaque': 6, 'partialAlpha': 4, 'transparent': 2, 'transparentWithRgb': 2}
    cases['literal-lossless-hidden-rgb'] = {'result': result, 'pngSha256': hashlib.sha256((out / 'literal/image.png').read_bytes()).hexdigest(), 'pixels': summary['pixels']}

    # 2. committed fixtures made by libwebp: opaque lossless RGB and lossy, each against a direct dwebp decode
    for name in ('decode-literal-rgba', 'decode-swatch-rgb', 'decode-gradient-lossy'):
        result = decode(name, FIXTURES / (name + '.webp'))
        native('direct-' + name, [dwebp, str(FIXTURES / (name + '.webp')), '-pam', '-o', str(out / (name + '.direct.pam'))], out)
        direct = read_pam((out / (name + '.direct.pam')).read_bytes())
        got = png_rows((out / name / 'image.png').read_bytes())
        assert (got[0], got[1], got[3]) == direct, name
        cases['fixture-' + name] = {'result': result, 'pngChannels': got[2]}
    assert cases['fixture-decode-swatch-rgb']['pngChannels'] == 3 and cases['fixture-decode-gradient-lossy']['pngChannels'] == 3

    # 3. lossy round trips from a real encoder at two qualities: PNG equals the direct decode; the distance to the original is reported only
    for quality in (20, 90):
        rgba = bytes(v for y in range(16) for x in range(24) for v in ((x * 10) % 256, (y * 15) % 256, (x * 5 + y * 7) % 256, 255))
        lossy = encode('lossy-q%d' % quality, rgba, 24, 16, '-q', str(quality), '-m', '6')
        result = decode('lossy-q%d' % quality, lossy)
        native('direct-lossy-q%d' % quality, [dwebp, str(lossy), '-pam', '-o', str(out / ('lossy-q%d.pam' % quality))], out)
        direct = read_pam((out / ('lossy-q%d.pam' % quality)).read_bytes())
        got = png_rows((out / ('lossy-q%d' % quality) / 'image.png').read_bytes())
        assert (got[0], got[1], got[3]) == direct
        error = sum(abs(a - b) for a, b in zip(rgba[0::4] + rgba[1::4] + rgba[2::4], got[3][0::4] + got[3][1::4] + got[3][2::4])) / (24 * 16 * 3)
        cases['lossy-q%d' % quality] = {'result': result, 'meanAbsRgbVersusOriginal(informational, not a claim)': round(error, 3), 'bytes': lossy.stat().st_size}

    # 4. real refusals, each before or at the first decode and none publishing a PNG
    # img2webp in the private build has no libpng, so the two animation frames are themselves real WebP files
    frames = [encode('frame%d' % index, bytes([shade, 0, 0, 255]) * 64, 8, 8, '-lossless') for index, shade in enumerate((20, 200))]
    native('img2webp', [str(bin_dir / 'img2webp'), '-lossless', frames[0].name, frames[1].name, '-o', 'animated.webp'], scratch)
    alpha_rgba = bytes(v for i in range(256) for v in (i % 256, 50, 100, 255 if i % 3 else 128))
    alpha_lossy = encode('alpha-lossy', alpha_rgba, 16, 16, '-q', '80')
    good = (scratch / 'literal.webp').read_bytes()
    flipped = bytearray(good)
    bits = struct.unpack_from('<I', flipped, 21)[0]
    struct.pack_into('<I', flipped, 21, bits & ~(1 << 28))
    zeroed = bytearray(good)
    zeroed[40:60] = bytes(20)
    big = bytearray(good)
    struct.pack_into('<I', big, 21, (bits & ~0x0fffffff) | 4095 | (4095 << 14))
    forged = {'animated': (scratch / 'animated.webp').read_bytes(), 'vp8x-alpha-lossy': alpha_lossy.read_bytes(), 'truncated': good[:60], 'trailing': good + b'EXIF',
              'alpha-hint-cleared': bytes(flipped), 'bitstream-zeroed': bytes(zeroed), 'oversize-header': bytes(big), 'not-webp': b'GIF89a' + bytes(40)}
    expected = {'animated': 'WEBP_ANIMATION_UNSUPPORTED', 'vp8x-alpha-lossy': 'WEBP_FORMAT_UNSUPPORTED', 'truncated': 'INVALID_WEBP_IMAGE', 'trailing': 'INVALID_WEBP_IMAGE',
                'alpha-hint-cleared': 'WEBP_ALPHA_MISMATCH', 'bitstream-zeroed': 'INVALID_WEBP_IMAGE', 'oversize-header': 'WEBP_PIXEL_BUDGET', 'not-webp': 'INVALID_WEBP_IMAGE'}
    refusals = {}
    for name, data in forged.items():
        path = scratch / (name + '.forged.webp')
        path.write_bytes(data)
        before = launches()
        refusals[name] = refused(lambda: decode('refuse-' + name, path), expected[name])
        refusals[name]['dwebpLaunchesDuringRefusal'] = launches() - before
        assert not (out / ('refuse-' + name) / 'image.png').exists(), name
    for name in ('animated', 'vp8x-alpha-lossy', 'truncated', 'trailing', 'oversize-header', 'not-webp'):
        assert refusals[name]['dwebpLaunchesDuringRefusal'] == 0, ('native launched before refusal', name)
    cases['refusals'] = refusals

    # 4b. VP8 upscaling bits: libwebp ignores them, so a real lossy file with the bits toggled must decode to the same
    # samples at the coded size, directly and through the adaptor (a bounded sample of the 16 (horizontal, vertical) values)
    lossy_base = (FIXTURES / 'decode-gradient-lossy.webp').read_bytes()
    raw_width, raw_height = struct.unpack_from('<HH', lossy_base, 26)
    assert lossy_base[12:16] == b'VP8 ' and not (raw_width >> 14 or raw_height >> 14)
    native('direct-scale-base', [dwebp, str(FIXTURES / 'decode-gradient-lossy.webp'), '-pam', '-o', str(out / 'scale-base.pam')], out)
    base_pixels = read_pam((out / 'scale-base.pam').read_bytes())
    scale_cases = {}
    for horizontal, vertical in ((0, 0), (1, 0), (2, 0), (3, 0), (0, 1), (0, 2), (0, 3), (1, 2), (3, 3)):
        toggled = bytearray(lossy_base)
        struct.pack_into('<HH', toggled, 26, raw_width | horizontal << 14, raw_height | vertical << 14)
        label = 'scale-%d-%d' % (horizontal, vertical)
        path = scratch / (label + '.webp')
        path.write_bytes(bytes(toggled))
        native('direct-' + label, [dwebp, str(path), '-pam', '-o', str(out / (label + '.direct.pam'))], out)
        direct = read_pam((out / (label + '.direct.pam')).read_bytes())
        assert direct == base_pixels, ('dwebp decoded the toggled bits differently from the unscaled file', label)
        result = decode(label, path)
        got = png_rows((out / label / 'image.png').read_bytes())
        assert (got[0], got[1], got[3]) == base_pixels and result['dimensions'] == [raw_width, raw_height], label
        scale_cases[label] = {'directEqualsUnscaledDirect': True, 'adaptorPngEqualsDirect': True, 'dimensions': result['dimensions'], 'verified': result['verified']}
    cases['vp8-upscaling-bits'] = {'codedDimensions': [raw_width, raw_height], 'sampled': scale_cases}

    # 5. decoder-only: the real CLI with --dwebp only, then verify through SCHEMAXIS_DWEBP; no cwebp anywhere in the environment
    document = out / 'cli.json'
    atomic_json(document, {'version': 'schemaxis.webp/1', 'operation': 'decodeToPng', 'source': str(FIXTURES / 'decode-literal-rgba.webp')})
    environment = {k: v for k, v in os.environ.items() if not k.startswith('SCHEMAXIS_') and k != 'PATH'}
    environment.update({'PYTHONPATH': str(ROOT / 'src'), 'PATH': '/usr/bin:/bin'})
    process = subprocess.Popen([sys.executable, '-m', 'schemaxis', 'run', str(document), '--output-directory', str(out / 'cli'), '--dwebp', dwebp], cwd=out, env=environment,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate(timeout=120)
    PROCESSES.append({'name': 'cli-run', 'pid': process.pid, 'timeoutSeconds': 120, 'command': ['python3', '-m', 'schemaxis', 'run', 'cli.json', '--output-directory', 'cli', '--dwebp', 'dwebp'], 'exitCode': process.returncode})
    assert process.returncode == 0, stderr[-400:]
    process = subprocess.Popen([sys.executable, '-m', 'schemaxis', 'verify', str(out / 'cli')], cwd=out, env={**environment, 'SCHEMAXIS_DWEBP': dwebp}, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    verified, stderr = process.communicate(timeout=120)
    PROCESSES.append({'name': 'cli-verify', 'pid': process.pid, 'timeoutSeconds': 120, 'command': ['python3', '-m', 'schemaxis', 'verify', 'cli'], 'exitCode': process.returncode})
    assert process.returncode == 0, stderr[-400:]
    process = subprocess.Popen([sys.executable, '-m', 'schemaxis', 'verify', str(out / 'cli')], cwd=out, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    unverified, stderr = process.communicate(timeout=120)
    PROCESSES.append({'name': 'cli-verify-without-decoder', 'pid': process.pid, 'timeoutSeconds': 120, 'command': ['python3', '-m', 'schemaxis', 'verify', 'cli'], 'exitCode': process.returncode})
    assert process.returncode != 0 and b'INTERPRETER_NOT_FOUND' in unverified + stderr, 'verify without a decoder must not succeed'
    cases['decoder-only-cli'] = {'runExit': 0, 'verifyWithEnvironmentDecoder': 'verified', 'verifyWithoutDecoder': 'refused INTERPRETER_NOT_FOUND', 'cwebpConfigured': False}

    # 6. tampering with every ordinary hash refreshed; the original must still verify afterwards
    base = out / 'literal'
    assert adaptor.verify(base, decoder=dwebp)['verified']
    changed = bytearray(LITERAL_BYTES)
    changed[4 * 6] ^= 1
    tamper = {'one hidden RGB sample': adaptor.encode_png(4, 3, bytes(changed), True), 'dropped alpha': adaptor.encode_png(4, 3, LITERAL_BYTES, False),
              'trailing byte': adaptor.encode_png(4, 3, LITERAL_BYTES, True) + b'\0', 'truncated': adaptor.encode_png(4, 3, LITERAL_BYTES, True)[:-20]}
    forged_runs = {}
    for name, data in tamper.items():
        copy = out / ('tamper-' + name.replace(' ', '-'))
        shutil.copytree(base, copy)
        (copy / 'image.png').write_bytes(data)
        refresh(copy)
        forged_runs[name] = refused(lambda: adaptor.verify(copy, decoder=dwebp), 'VERIFICATION_FAILED')
    other = out / 'tamper-other-webp'
    shutil.copytree(base, other)
    (other / 'captured.webp').write_bytes((FIXTURES / 'decode-swatch-rgb.webp').read_bytes())
    refresh(other)
    forged_runs['different captured WebP, stale readback'] = refused(lambda: adaptor.verify(other, decoder=dwebp), 'VERIFICATION_FAILED')
    hinted = out / 'tamper-alpha-hint-cleared'
    shutil.copytree(base, hinted)
    (hinted / 'captured.webp').write_bytes(bytes(flipped))
    refresh(hinted)
    try:
        adaptor.verify(hinted, decoder=dwebp)
    except SchemaxisError as error:
        assert error.fault.code == 'VERIFICATION_FAILED' and error.fault.observed['cause']['code'] == 'WEBP_ALPHA_MISMATCH', error.fault.to_dict()
        forged_runs['captured WebP with the alpha hint cleared (verify-time)'] = {'code': error.fault.code, 'cause': error.fault.observed['cause']['code'], 'message': error.fault.message[:160]}
    else:
        raise AssertionError('verification accepted a cleared alpha hint')
    cases['tampering-with-refreshed-hashes'] = forged_runs
    assert adaptor.verify(base, decoder=dwebp)['verified']

    # 7. no external re-read: remove the source after capture, verification still holds
    keep = scratch / 'ephemeral.webp'
    shutil.copy(FIXTURES / 'decode-literal-rgba.webp', keep)
    decode('ephemeral', keep)
    keep.unlink()
    assert adaptor.verify(out / 'ephemeral', decoder=dwebp)['verified']
    cases['source-removed-after-capture'] = 'verified from the captured copy'

    # 8. lifecycle with the real decoder behind a stalling wrapper
    # The stall wrapper sleeps before it execs dwebp: this proves the owned wrapper process ends, and that the real dwebp
    # never started (the marker written just before the exec is absent); it does not show a real dwebp being terminated.
    stall_log, reached = out / 'adaptor-stall-wrapper-launches.log', out / 'stall-reached-exec.marker'
    stall_log.write_text('')
    stall = wrapper(out / 'dwebp-stall', dwebp, stall_log, delay=30, reached=reached)
    started = time.monotonic()
    cases['timeout'] = refused(lambda: decode('timeout', FIXTURES / 'decode-literal-rgba.webp', decoder=stall, timeout=2), 'RUNNER_TIMED_OUT')
    assert time.monotonic() - started < 20
    timeout_pids = [int(line.split(' ', 1)[0]) for line in stall_log.read_text().splitlines()]
    cancel = threading.Event()
    threading.Timer(1.5, cancel.set).start()
    with allocation({'threads': 1, 'ranks': 1}, cancel):
        cases['cancellation'] = refused(lambda: decode('cancelled', FIXTURES / 'decode-literal-rgba.webp', decoder=stall, timeout=20), 'RUNNER_CANCELLED')
    time.sleep(0.5)
    stall_pids = [int(line.split(' ', 1)[0]) for line in stall_log.read_text().splitlines()]
    assert len(timeout_pids) == 1 and len(stall_pids) == 2, stall_pids
    gone = {pid: not alive(pid) for pid in stall_pids}
    assert all(gone.values()), ('owned stall wrapper still alive', gone)
    assert not reached.exists(), 'the stall wrapper reached its exec: real dwebp started'
    cases['stall-wrapper-lifecycle'] = {'wrapperPids': stall_pids, 'wrapperPidsGoneAfterStop': True, 'realDwebpStarted': False,
                                        'scope': 'owned stall-wrapper shell ended by the timeout and by the cancellation before its exec; a real dwebp process was not terminated because none started'}
    assert adaptor.read_json(out / 'timeout', 'result.json')['status'] == 'failed'
    cases['unsupported-or-missing-decoder'] = {'missing': refused(lambda: decode('missing', FIXTURES / 'decode-literal-rgba.webp', decoder=str(out / 'nope')), 'INTERPRETER_NOT_FOUND'),
                                               'relative': refused(lambda: decode('relative', FIXTURES / 'decode-literal-rgba.webp', decoder='dwebp'), 'INTERPRETER_NOT_FOUND')}

    # 9. legacy encode operations: same plans, artifacts and receipts as the unmodified adaptor; legacy receipts verify read-only
    if args.baseline_adaptor:
        spec = importlib.util.spec_from_file_location('webp_baseline', args.baseline_adaptor)
        old = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old)
        legacy = {}
        for label, document in (('encodeLossless', {'version': 'schemaxis.webp/1', 'operation': 'encodeLossless', 'source': str(FIXTURES / 'swatch-rgba.png')}),
                                ('encodeLossy', {'version': 'schemaxis.webp/1', 'operation': 'encodeLossy', 'source': str(FIXTURES / 'lossy-gradient-rgba.png'), 'quality': 80, 'maxMeanRGBError': 3})):
            assert json.dumps(old.plan(document), sort_keys=True) == json.dumps(adaptor.plan(document), sort_keys=True)
            old_result = old.run(document, out / ('legacy-old-' + label), executable=cwebp, decoder=dwebp)
            new_result = adaptor.run(document, out / ('legacy-new-' + label), executable=cwebp, decoder=dwebp)
            assert json.dumps(old_result, sort_keys=True) == json.dumps(new_result, sort_keys=True), label
            same = {}
            for name in ('authored.json', 'plan.json', 'captures.json', 'captured.png', 'source.pam', 'image.webp', 'reopened.pam', 'webp-summary.json', 'encode.stderr', 'decode.stderr',
                         'encode-launcher.py', 'decode-launcher.py', 'result.json'):
                same[name] = (out / ('legacy-old-' + label) / name).read_bytes() == (out / ('legacy-new-' + label) / name).read_bytes()
            receipts = [adaptor.read_json(out / ('legacy-%s-%s' % (kind, label)), 'verification.json') for kind in ('old', 'new')]
            for receipt, kind in zip(receipts, ('old', 'new')):
                receipt['artifacts'] = json.loads(json.dumps(receipt['artifacts']).replace('legacy-%s-' % kind, 'legacy-X-'))
                # native submission records carry wall-clock seconds and per-run script paths, so only their membership is compared
                receipt['evidence'] = {k: (None if k.endswith('-submission.json') else v) for k, v in receipt['evidence'].items()}
            same['verification.json (directory name normalised; submission digests excluded)'] = json.dumps(receipts[0], sort_keys=True) == json.dumps(receipts[1], sort_keys=True)
            assert all(same.values()), same
            # a receipt written by the unmodified adaptor verifies read-only under the new code and is left byte-identical
            frozen = out / ('legacy-old-' + label)
            before = tree_hash(frozen)
            for path in [frozen, *frozen.rglob('*')]:
                path.chmod(path.stat().st_mode & ~0o222)
            try:
                verified_legacy = adaptor.verify(frozen, decoder=dwebp)
            finally:
                for path in [frozen, *frozen.rglob('*')]:
                    path.chmod(path.stat().st_mode | 0o200)
            assert verified_legacy['verified'] and tree_hash(frozen) == before
            legacy[label] = {'identicalToUnmodifiedAdaptor': same, 'legacyReceiptVerifiedReadOnly': True, 'result': new_result}
        cases['legacy'] = legacy

    # 10. Pandoc handoff of the published PNG (the Pandoc route accepts a PNG path, not an image artifact)
    if args.pandoc:
        report = json.loads((ROOT / 'examples/schemaxis/pandoc-report.json').read_text())
        report['sections'][1]['content'][1]['source'] = str(out / 'literal/image.png')
        report['sections'][1]['content'][1]['alt'] = 'Decoded WebP: four by three RGBA literal'
        atomic_json(out / 'pandoc-report.json', report)
        process = subprocess.Popen([sys.executable, '-m', 'schemaxis', 'run', str(out / 'pandoc-report.json'), '--output-directory', str(out / 'pandoc'), '--pandoc', str(args.pandoc.absolute())],
                                   cwd=out, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate(timeout=240)
        PROCESSES.append({'name': 'pandoc-report-run', 'pid': process.pid, 'timeoutSeconds': 240, 'command': ['python3', '-m', 'schemaxis', 'run', 'pandoc-report.json', '--output-directory', 'pandoc', '--pandoc', 'pandoc'], 'exitCode': process.returncode})
        assert process.returncode == 0, (stdout[-300:], stderr[-300:])
        result = json.loads(stdout)
        assert result.get('verified') is True and result.get('images') == 1, result
        cases['pandoc-handoff'] = {'verified': True, 'images': result['images'], 'sourceImage': 'literal/image.png (decodeToPng output, RGBA with partial alpha)'}

    record['adaptorDwebpLaunches'] = [dict(zip(('pid', 'arguments'), line.split(' ', 1))) for line in log.read_text().splitlines()]
    record['stallWrapperLaunches'] = [dict(zip(('pid', 'arguments'), line.split(' ', 1))) for line in stall_log.read_text().splitlines()]
    record['pidCoverage'] = {
        'recorded': 'dwebp launches through the logging wrapper (adaptorDwebpLaunches: sections 1-4b and the section 7 run; section 8 logs separately, including the version probe, decode and the built-in and shared verifications, plus refusals that reached the decoder), '
                    'the two stall-wrapper shells (stallWrapperLaunches; the real dwebp never started) and the direct probe processes (processes)',
        'notRecorded': ['adaptor.verify calls given the plain dwebp: the base verifies, tamper verifies, the ephemeral-source verify and the two read-only legacy-receipt verifies',
                        'the four legacy encode runs (old and new adaptor module, plain cwebp and dwebp) and the cwebp launches they make',
                        'the command-line run, verify and verify-without-decoder processes (their native dwebp children)',
                        'the Pandoc report run (no dwebp)'],
        'note': 'Launch totals above cover wrapper-logged calls only; no total of all dwebp launches is claimed.'}
    record['processes'] = PROCESSES
    record['runtime'] = {'dwebp': subprocess.run([dwebp, '-version'], capture_output=True, text=True).stdout.strip()}
    atomic_json(out / 'qualification-record.json', record)
    print(json.dumps({'status': 'passed', 'cases': sorted(cases), 'directProbeProcesses': len(PROCESSES), 'wrapperLoggedDwebpLaunches': len(record['adaptorDwebpLaunches']),
                      'stallWrapperShells': len(record['stallWrapperLaunches']), 'allDwebpLaunchesRecorded': False}, indent=2))


if __name__ == '__main__':
    main()
