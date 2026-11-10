#!/usr/bin/env python3
"""Bounded native acceptance of encodeLossy with libwebp 1.6 cwebp and dwebp.

Quality, geometry and opacity variants; every RGB error is recomputed here from the source rows and an independent
dwebp decode (the tool's own tiny PAM and PNG-row readers, not the adaptor's); exact byte and rational error
boundaries; refusals (partial alpha, bounds, profiles, formats, over-budget, truncated and garbage bitstreams,
mismatched geometry, missing trusted decoder, fully refreshed content and result forgery, collisions, timeout and
cancellation); an untouched PATH/receipt sentinel; real CLI run and verify; workflow reuse. It states no perceptual
quality or compression guarantee: it measures mean absolute RGB error against the decode of dwebp's default options.
"""
import argparse
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import threading
import time
import zlib

from schemaxis.adaptor_conformance import qualify, register
from schemaxis.adaptors.webp import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.configuration import location_context
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation
from schemaxis import workflow

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'examples/schemaxis/fixtures/webp'
PROCESSES = []
LOSSY = 'encodeLossy'


def native(name, command, cwd, timeout=60, env=None, expect=0):
    """Run one probe process directly and keep its real PID, command and exit status."""
    process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    try:
        out, err = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        PROCESSES.append({'name': name, 'pid': process.pid, 'command': [Path(command[0]).name, *command[1:]], 'exitCode': 'timeout'})
        raise
    PROCESSES.append({'name': name, 'pid': process.pid, 'command': [Path(command[0]).name, *command[1:]], 'exitCode': process.returncode})
    assert process.returncode == expect, (name, process.returncode, err[-300:])
    return out if expect == 0 else out + err


def refused(action, code):
    """Require a structured fault; ``code`` may be a tuple when the fresh judgement legitimately precedes a digest check."""
    codes = code if isinstance(code, tuple) else (code,)
    try:
        action()
    except SchemaxisError as error:
        assert error.fault.code in codes, error.fault.to_dict()
        return {'code': error.fault.code, 'location': error.fault.location, 'message': error.fault.message[:140], 'recovery': error.fault.recovery}
    raise AssertionError('accepted: expected ' + code)


class configuration_file:
    """A private SCHEMAXIS_CONFIG for a block, then the caller's environment restored."""
    def __init__(self, path, locations):
        self.path, self.locations = Path(path), locations

    def __enter__(self):
        atomic_json(self.path, {'version': 1, 'locations': self.locations})
        self.saved = {k: os.environ.get(k) for k in ('SCHEMAXIS_CONFIG', 'SCHEMAXIS_WEBP', 'SCHEMAXIS_DWEBP')}
        os.environ['SCHEMAXIS_CONFIG'] = str(self.path)
        os.environ.pop('SCHEMAXIS_WEBP', None)
        os.environ.pop('SCHEMAXIS_DWEBP', None)

    def __exit__(self, *error):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def chunk(kind, value):
    return struct.pack('>I', len(value)) + kind + value + struct.pack('>I', zlib.crc32(kind + value) & 0xffffffff)


def png(rows, colour=6, depth=8, interlace=0, extra=b''):
    count = 4 if colour == 6 else 3
    raw = b''.join(b'\0' + bytes(v for px in row for v in px[:count]) for row in rows)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', len(rows[0]), len(rows), depth, colour, 0, 0, interlace))
            + extra + chunk(b'IDAT', zlib.compress(raw, 1)) + chunk(b'IEND', b''))


def png_rows(data):
    """Independent reader for the tool's own filter-0 8-bit RGB/RGBA PNGs and the filter-0 fixtures."""
    width, height, depth, colour = struct.unpack('>IIBB', data[16:26])
    assert depth == 8 and colour in (2, 6)
    offset, idat = 8, b''
    while offset < len(data):
        length, kind = struct.unpack('>I4s', data[offset:offset + 8])
        if kind == b'IDAT':
            idat += data[offset + 8:offset + 8 + length]
        offset += length + 12
    raw, step = zlib.decompress(idat), 3 if colour == 2 else 4
    rows = []
    for y in range(height):
        line = raw[y * (1 + width * step):(y + 1) * (1 + width * step)]
        assert line[0] == 0, 'fixture rows use filter 0'
        rows.append([tuple(line[1 + x * step:1 + x * step + step]) + ((255,) if step == 3 else ()) for x in range(width)])
    return rows


def decode_pam(dwebp, webp, work, name):
    """Independent dwebp -pam decode and a deliberately separate tiny PAM parser."""
    out = Path(work) / (name + '-independent.pam')
    native('independent-decode-' + name, [dwebp, str(webp), '-pam', '-o', str(out)], work)
    head, _, body = out.read_bytes().partition(b'ENDHDR\n')
    fields = dict(line.split(b' ', 1) for line in head.split(b'\n')[1:] if b' ' in line)
    width, height = int(fields[b'WIDTH']), int(fields[b'HEIGHT'])
    assert int(fields[b'DEPTH']) == 4 and len(body) == 4 * width * height
    return [[tuple(body[4 * (y * width + x):4 * (y * width + x) + 4]) for x in range(width)] for y in range(height)]


def sum_error(source_rows, decoded_rows):
    assert len(source_rows) == len(decoded_rows) and len(source_rows[0]) == len(decoded_rows[0])
    return sum(abs(a - b) for sr, dr in zip(source_rows, decoded_rows) for sp, dp in zip(sr, dr) for a, b in zip(sp[:3], dp[:3]))


def gradient(width, height):
    return [[((x * 255) // max(width - 1, 1), 255 - (y * 255) // max(height - 1, 1), ((x + 2 * y) * 255) // max(width + 2 * height - 3, 1), 255)
             for x in range(width)] for y in range(height)]


def noise(width, height, seed=12345):
    state, rows = seed, []
    for _ in range(height):
        row = []
        for _ in range(width):
            state = (state * 1103515245 + 12345) & 0x7fffffff
            row.append(((state >> 4) & 255, (state >> 12) & 255, (state >> 20) & 255, 255))
        rows.append(row)
    return rows


def document(source, quality, mean, **extra):
    return {'version': 'schemaxis.webp/1', 'operation': LOSSY, 'source': str(source), 'quality': quality, 'maxMeanRGBError': mean, **extra}


def variants(directory, cwebp, dwebp):
    """Quality sweep, opacity and geometry variants; every error and byte figure is recomputed independently."""
    work = directory / 'variants'
    work.mkdir()
    sources = {'gradient-fixture': (FIXTURES / 'lossy-gradient-rgba.png').read_bytes(), 'chart-fixture': (FIXTURES / 'lossy-chart-rgb.png').read_bytes(),
               'one-pixel': png([[(250, 3, 130, 255)]]), 'one-by-seventeen': png([[row[0]] for row in gradient(1, 17)]),
               'seventeen-by-one': png([gradient(17, 1)[0]]), 'odd-33x31': png(gradient(33, 31)), 'odd-rgb-5x3': png([r[:5] for r in gradient(5, 3)], colour=2),
               'asymmetric-rgb-40x9': png([[(x * 6 % 256, (x * y * 3) % 256, 255 - y * 25) for x in range(40)] for y in range(9)], colour=2)}
    report = {}
    for label, data in sources.items():
        source = work / (label + '.png')
        source.write_bytes(data)
        rows = png_rows(data)
        height, width = len(rows), len(rows[0])
        assert all(px[3] == 255 for row in rows for px in row)
        for quality in ((0, 30, 60, 80, 100) if label in ('gradient-fixture', 'chart-fixture') else (50, 100)):
            name = '%s-q%d' % (label, quality)
            result = adaptor.run(document(source, quality, 255), work / name, executable=cwebp, decoder=dwebp, timeout=120)
            webp = work / name / 'image.webp'
            decoded = decode_pam(dwebp, webp, work, name)
            total, samples = sum_error(rows, decoded), width * height * 3
            assert all(px[3] == 255 for row in decoded for px in row)
            assert result['error']['sumAbsoluteRgb'] == total and result['error']['samples'] == samples, (name, total, result['error'])
            assert result['bytes'] == webp.stat().st_size and result['dimensions'] == [width, height]
            info = native('webpinfo-' + name, [str(Path(cwebp).with_name('webpinfo')), str(webp)], work).decode()
            assert 'Format: Lossy' in info and 'Alpha: 0' in info and 'ALPH' not in info and 'VP8X' not in info, info
            assert adaptor.verify(work / name, decoder=dwebp)['error']['sumAbsoluteRgb'] == total
            report[name] = {'dimensions': [width, height], 'pngBytes': len(data), 'webpBytes': result['bytes'], 'sumAbsoluteRgb': total, 'samples': samples,
                            'meanAbsoluteRgb': total / samples, 'independentSumEqualsAdaptor': True, 'webpinfo': 'Format: Lossy, Alpha: 0, no ALPH/VP8X'}
    return report


def decimal_value(budget):
    """The decision rule under test: the authored budget is the decimal written, i.e. the shortest round-trip text of the float."""
    return Fraction(str(budget))


def decimal_edge_source(work, cwebp, dwebp):
    """A real 10x2 encoding whose exact mean error is a terminating decimal that the nearest binary double undershoots.

    Searches deterministic noise images and qualities with independent native cwebp/dwebp probes (not the adaptor) for an exact
    mean ``total/60`` that is a short decimal ``d`` with ``Fraction(float(d)) < d``: the case an authored ``d`` once refused.
    """
    probe = work / 'edge-search'
    probe.mkdir()
    for seed in range(1, 40):
        source = probe / ('s%d.png' % seed)
        source.write_bytes(png(noise(10, 2, seed)))
        pam = probe / 's.pam'
        rows = png_rows(source.read_bytes())
        pam.write_bytes(adaptor.pam(10, 2, b''.join(bytes(px) for row in rows for px in row)))
        for quality in (5, 15, 25, 35, 45, 55, 65, 75, 85, 95):
            webp = probe / 'p.webp'
            native('edge-search-encode', [cwebp, '-q', str(quality), '-m', '6', '-alpha_q', '100', str(pam), '-o', str(webp)], probe)
            total = sum_error(rows, decode_pam(dwebp, webp, probe, 'p'))
            mean = Fraction(total, 60)
            if total and all(prime in (2, 5) for prime in prime_factors(mean.denominator)) and Fraction(float(mean)) != mean:
                text = repr(float(mean))
                if Fraction(text) == mean and Fraction(float(text)) < mean:
                    return source, quality, total, float(mean)
    raise AssertionError('no real 10x2 encoding with a decimal-exact, binary-undershot mean error was found')


def prime_factors(number):
    found, divisor = set(), 2
    while divisor * divisor <= number:
        while number % divisor == 0:
            found.add(divisor)
            number //= divisor
        divisor += 1
    if number > 1:
        found.add(number)
    return found


def boundaries(directory, cwebp, dwebp):
    """The exact decimal-rule error edge and the exact byte edge on real encodings."""
    work = directory / 'boundaries'
    work.mkdir()
    source = work / 'source.png'
    source.write_bytes((FIXTURES / 'lossy-chart-rgb.png').read_bytes())
    base = adaptor.run(document(source, 80, 255), work / 'base', executable=cwebp, decoder=dwebp, timeout=120)
    total, samples = base['error']['sumAbsoluteRgb'], base['error']['samples']
    edge = Fraction(total, samples)
    high = total / samples
    while decimal_value(high) < edge:
        high = math.nextafter(high, math.inf)
    while decimal_value(math.nextafter(high, -math.inf)) >= edge:
        high = math.nextafter(high, -math.inf)
    low = math.nextafter(high, -math.inf)
    assert decimal_value(low) < edge <= decimal_value(high)
    report = {'sumAbsoluteRgb': total, 'samples': samples, 'rule': 'budget = Fraction(str(authored float)); accept iff exact mean <= budget'}
    accepted = adaptor.run(document(source, 80, high), work / 'at-edge', executable=cwebp, decoder=dwebp, timeout=120)
    assert accepted['verified'] and adaptor.verify(work / 'at-edge', decoder=dwebp)['verified']
    report['smallestFloatWhoseDecimalIsAtOrAboveExactMean'] = {'maxMeanRGBError': high, 'accepted': True}
    report['largestFloatWhoseDecimalIsBelowExactMean'] = {'maxMeanRGBError': low, **refused(lambda: adaptor.run(document(source, 80, low), work / 'below-edge', executable=cwebp, decoder=dwebp, timeout=120), 'DELIVERABLE_NOT_MET')}
    exact_source, exact_quality, exact_total, decimal = decimal_edge_source(work, cwebp, dwebp)
    assert Fraction(float(decimal)) < Fraction(exact_total, 60) == decimal_value(decimal)
    exact = adaptor.run(document(exact_source, exact_quality, decimal), work / 'decimal-exact', executable=cwebp, decoder=dwebp, timeout=120)
    assert exact['error']['sumAbsoluteRgb'] == exact_total and exact['error']['samples'] == 60 and adaptor.verify(work / 'decimal-exact', decoder=dwebp)['verified']
    below = math.nextafter(decimal, -math.inf)
    assert decimal_value(below) < decimal_value(decimal)
    report['decimalExactRealEncoding'] = {'quality': exact_quality, 'sumAbsoluteRgb': exact_total, 'samples': 60, 'exactMean': '%d/60' % exact_total, 'maxMeanRGBError': decimal,
                                          'binaryFractionOfBudgetUndershootsDecimal': True, 'acceptedAtRunAndVerify': True,
                                          'nextFloatBelow': {'maxMeanRGBError': below, **refused(lambda: adaptor.run(document(exact_source, exact_quality, below), work / 'decimal-below', executable=cwebp, decoder=dwebp, timeout=120), 'DELIVERABLE_NOT_MET')}}
    report['zeroBudget'] = refused(lambda: adaptor.run(document(source, 100, 0), work / 'zero', executable=cwebp, decoder=dwebp, timeout=120), 'DELIVERABLE_NOT_MET')
    size = base['bytes']
    assert adaptor.run(document(source, 80, 255, maxBytes=size), work / 'bytes-at', executable=cwebp, decoder=dwebp, timeout=120)['verified']
    report['byteBudget'] = {'bytes': size, 'maxBytesEqualAccepted': True,
                            'maxBytesOneBelow': refused(lambda: adaptor.run(document(source, 80, 255, maxBytes=size - 1), work / 'bytes-below', executable=cwebp, decoder=dwebp, timeout=120), 'DELIVERABLE_NOT_MET')}
    report['failedRunsAreUnverified'] = all(adaptor.read_json(work / n, 'result.json')['verified'] is False and adaptor.read_json(work / n, 'result.json')['status'] == 'failed'
                                            for n in ('below-edge', 'zero', 'bytes-below', 'decimal-below'))
    assert report['failedRunsAreUnverified']
    return report


def negatives(directory, cwebp, dwebp):
    """Refusals that never reach, or are decided independently of, the native encoder."""
    work = directory / 'negatives'
    work.mkdir()
    translucent = png([[(1, 2, 3, 255), (4, 5, 6, 254)], [(7, 8, 9, 255), (10, 11, 12, 255)]])
    clear = png([[(1, 2, 3, 255), (4, 5, 6, 0)]])
    srgb = png(gradient(3, 3))
    cases = {'partialAlpha': (translucent, 'WEBP_ALPHA_UNSUPPORTED'), 'zeroAlpha': (clear, 'WEBP_ALPHA_UNSUPPORTED'),
             'iccProfile': (png(gradient(3, 3), extra=chunk(b'iCCP', b'p\0\0' + zlib.compress(b'x'))), 'WEBP_COLOUR_UNSUPPORTED'),
             'nonSrgbGamma': (png(gradient(3, 3), extra=chunk(b'gAMA', struct.pack('>I', 100000))), 'WEBP_COLOUR_UNSUPPORTED'),
             'sixteenBit': (png(gradient(3, 3), depth=16), 'INVALID_WEBP_PNG'), 'palette': (png(gradient(3, 3), colour=3), 'INVALID_WEBP_PNG'),
             'interlaced': (png(gradient(3, 3), interlace=1), 'INVALID_WEBP_PNG'), 'trns': (png(gradient(3, 3), colour=2, extra=chunk(b'tRNS', bytes(6))), 'INVALID_WEBP_PNG'),
             'truncatedPng': (srgb[:-5], 'INVALID_WEBP_PNG'), 'notPng': (b'GIF89a' + bytes(64), 'INVALID_WEBP_PNG'),
             'tooWide': (srgb[:16] + struct.pack('>II', 3000, 3000) + srgb[24:], 'WEBP_PIXEL_BUDGET'), 'overPixels': (srgb[:16] + struct.pack('>II', 1025, 1025) + srgb[24:], 'WEBP_PIXEL_BUDGET')}
    report = {}
    for label, (data, code) in cases.items():
        source = work / (label + '.png')
        source.write_bytes(data)
        target = work / label
        report[label] = refused(lambda: adaptor.run(document(source, 80, 10), target, executable=cwebp, decoder=dwebp, timeout=60), code)
        assert not (target / 'encoder-version-submission.json').exists(), label + ' reached a native process'
        assert adaptor.read_json(target, 'result.json')['verified'] is False
    plain = work / 'plain.png'
    plain.write_bytes(srgb)
    for label, edit in (('qualityBool', {'quality': True}), ('qualityFloat', {'quality': 80.0}), ('qualityString', {'quality': '80'}), ('qualityLow', {'quality': -1}),
                        ('qualityHigh', {'quality': 101}), ('errorNaN', {'maxMeanRGBError': float('nan')}), ('errorInfinity', {'maxMeanRGBError': float('inf')}),
                        ('errorBool', {'maxMeanRGBError': False}), ('errorNegative', {'maxMeanRGBError': -0.01}), ('errorAboveRange', {'maxMeanRGBError': 255.01}),
                        ('bytesZero', {'maxBytes': 0}), ('bytesAboveCap', {'maxBytes': 16 * 1024 * 1024 + 1}), ('bytesBool', {'maxBytes': True}),
                        ('nearLossless', {'near_lossless': 60}), ('authoredFlags', {'flags': ['-lossless']}), ('autoQuality', {'targetSize': 1000})):
        report[label] = refused(lambda: adaptor.plan({**document(plain, 80, 10), **edit}), 'INVALID_ARGUMENT' if not label.startswith(('nearL', 'autho', 'autoQ')) else 'UNKNOWN_ARGUMENT')
    for label, source in (('relativePath', 'relative.png'), ('urlSource', 'https://example.org/a.png'), ('wrongSuffix', str(work / 'a.jpg')), ('nulPath', str(work / 'a\0.png'))):
        report[label] = refused(lambda: adaptor.plan(document(source, 80, 10)), 'INVALID_WEBP_SOURCE')
    for label in ('quality', 'maxMeanRGBError'):
        missing = document(plain, 80, 10)
        del missing[label]
        report['missing' + label[0].upper() + label[1:]] = refused(lambda: adaptor.plan(missing), 'MISSING_ARGUMENT')
    report['webpAsSource'] = refused(lambda: adaptor.plan(document(work / 'a.webp', 80, 10)), 'INVALID_WEBP_SOURCE')
    return report


def hostile(directory, cwebp, dwebp):
    """Replace image.webp with real or damaged libwebp outputs, refresh every ordinary hash, and let only decoding and judgement decide."""
    work = directory / 'hostile'
    work.mkdir()
    source = work / 'source.png'
    source.write_bytes((FIXTURES / 'lossy-gradient-rgba.png').read_bytes())
    other = work / 'other.png'
    other.write_bytes(png(gradient(40, 40)))                               # different geometry
    other_content = work / 'other-content.png'                             # same geometry, different pixels
    rows = png_rows(source.read_bytes())
    other_content.write_bytes(png([[(255 - p[0], 255 - p[1], 255 - p[2], 255) for p in row] for row in rows]))
    run = work / 'run'
    adaptor.run(document(source, 80, 3.5, maxBytes=1024), run, executable=cwebp, decoder=dwebp, timeout=120)
    quality0 = work / 'q0'
    adaptor.run(document(source, 0, 255), quality0, executable=cwebp, decoder=dwebp, timeout=120)
    smaller = work / 'smaller'
    adaptor.run(document(other, 80, 255), smaller, executable=cwebp, decoder=dwebp, timeout=120)
    inverted = work / 'inverted'
    adaptor.run(document(other_content, 80, 255), inverted, executable=cwebp, decoder=dwebp, timeout=120)
    rougher = work / 'rougher-within-budget'
    adaptor.run(document(source, 60, 3.5), rougher, executable=cwebp, decoder=dwebp, timeout=120)
    good = (run / 'image.webp').read_bytes()
    saved = {p: p.read_bytes() for p in run.rglob('*') if p.is_file()}
    # damaged but framed: consistent truncation of the real VP8 chunk with a first partition that still fits
    tag = good[20] | good[21] << 8 | good[22] << 16
    body = struct.pack('<I', (tag & 0x1f) | (10 << 5))[:3] + good[23:80]
    framed_truncated = b'RIFF' + struct.pack('<I', 12 + len(body) + (len(body) & 1)) + b'WEBPVP8 ' + struct.pack('<I', len(body)) + body + b'\0' * (len(body) & 1)
    assert adaptor.vp8_header(framed_truncated)['width'] == 96
    zeroed = good[:30] + bytes(len(good) - 30)
    flipped = good[:60] + bytes(x ^ 0xff for x in good[60:300]) + good[300:]
    lossless = work / 'lossless.webp'
    native('lossless-encode', [cwebp, '-lossless', '-z', '6', str(run / 'source.pam'), '-o', str(lossless)], work)
    alpha = work / 'alpha.webp'
    native('alpha-lossy-encode', [cwebp, '-q', '80', str(run / 'source.pam'), '-o', str(alpha)], work)
    cases = {'truncatedFramedBitstream': (framed_truncated, 'VERIFICATION_FAILED'), 'losslessVP8L': (lossless.read_bytes(), 'VERIFICATION_FAILED'),
             'trailingBytes': (good + b'\0\0', 'VERIFICATION_FAILED'), 'truncatedFile': (good[:-3], 'VERIFICATION_FAILED'),
             'zeroedBitstreamGarbageDecode': (zeroed, 'DELIVERABLE_NOT_MET'), 'bitFlippedBitstreamGarbageDecode': (flipped, 'DELIVERABLE_NOT_MET'),
             'roughestQuality0OverBudget': ((quality0 / 'image.webp').read_bytes(), 'DELIVERABLE_NOT_MET'),
             'differentNativeGeometry': ((smaller / 'image.webp').read_bytes(), 'VERIFICATION_FAILED'),
             'sameGeometryDifferentContent': ((inverted / 'image.webp').read_bytes(), 'DELIVERABLE_NOT_MET')}
    report = {}

    def refresh(rewrite_records=True):
        """Make every ordinary hash agree with the replaced image.webp; optionally rebuild the readback, summary and result too.

        Returns whether the summary, run readback and result record were really rewritten for the new bytes. They cannot be
        rebuilt when the bytes fail strict VP8 framing, do not decode, or decode to other dimensions: no valid record exists then.
        """
        webp = (run / 'image.webp').read_bytes()
        atomic_json(run / 'decode-inputs.json', {'image.webp': adaptor.digest(run, 'image.webp')})
        (run / 'encode.stderr').write_text('Output:    %d bytes (0.00 bpp)\n' % len(webp))
        rewritten = False
        if rewrite_records:
            try:
                prepared = adaptor.plan(adaptor.read_json(run, 'authored.json'))
                capture = (run / 'captured.png').read_bytes()
                image = adaptor.admit_png(capture)
                header = adaptor.vp8_header(webp)
                decoded, identity = adaptor.native_decode({'decoder': dwebp}, webp)
                width, height, pixels = adaptor.read_pam(decoded)
                assert (width, height) == (image['width'], image['height']) == (header['width'], header['height'])
                measure = adaptor.rgb_error(image['rgba'], pixels)
            except (SchemaxisError, AssertionError, ValueError):
                pass
            else:
                (run / 'reopened.pam').write_bytes(decoded)
                atomic_json(run / 'webp-summary.json', adaptor.summarize_lossy(prepared, image, capture, webp, header, pixels, measure))
                result = adaptor.read_json(run, 'result.json')
                result.update(bytes=len(webp), dimensions=[width, height],
                              error={'meanAbsoluteRgb': measure['meanAbsRGB'], 'sumAbsoluteRgb': measure['sumAbsRGB'], 'samples': measure['samples'],
                                     'maxMeanRGBError': prepared['maxMeanRGBError'], 'maxBytes': prepared['budget']['maxBytes']})
                result['runtime']['freshDecoder'] = identity
                atomic_json(run / 'result.json', result)
                rewritten = True
        receipt = adaptor.read_json(run, 'verification.json')
        receipt['evidence'] = {n: adaptor.digest(run, n) for n in sorted(receipt['evidence'])}
        receipt['artifacts'] = adaptor.publications(run)
        atomic_json(run / 'verification.json', receipt)
        from schemaxis.publication_metadata import finalise
        finalise(run)
        return rewritten
    try:
        for label, (data, code) in cases.items():
            assert data != good, label
            (run / 'image.webp').write_bytes(data)
            report[label + 'WithoutRefresh'] = refused(lambda: adaptor.verify(run, decoder=dwebp), ('VERIFICATION_FAILED', code))['message']
            rewritten = refresh()
            fault = refused(lambda: adaptor.verify(run, decoder=dwebp), code)
            # 'FullyRefreshed' only where a valid summary, readback and result could really be rebuilt for the bytes
            report[label + ('FullyRefreshed' if rewritten else 'ReceiptRefreshedRecordsNotRebuildable')] = {'code': fault['code'], 'message': fault['message'], 'summaryReadbackAndResultRewritten': rewritten}
            for path, content in saved.items():
                path.write_bytes(content)
        # A different real encoding of the same source that fits the budget verifies once every record is rewritten to agree.
        # This is the documented limit: pixels within budget against dwebp, not the encoder history, quality, -m or -alpha_q.
        (run / 'image.webp').write_bytes((rougher / 'image.webp').read_bytes())
        report['roughButWithinBudgetWithoutRefresh'] = refused(lambda: adaptor.verify(run, decoder=dwebp), 'VERIFICATION_FAILED')['message']
        assert not refresh(rewrite_records=False)
        report['roughButWithinBudgetReceiptRefreshedSummaryStale'] = refused(lambda: adaptor.verify(run, decoder=dwebp), 'VERIFICATION_FAILED')['message']
        assert refresh(rewrite_records=True)
        accepted = adaptor.verify(run, decoder=dwebp)                      # require_result=True: the result record is rewritten and compared too
        summary = adaptor.read_json(run, 'webp-summary.json')
        assert accepted['verified'] and accepted['bytes'] == len((rougher / 'image.webp').read_bytes()) != len(good)
        assert summary['request']['quality'] == 80 and adaptor.read_json(rougher, 'plan.json')['quality'] == 60 and summary['image']['sha256'] != adaptor.sha(good)
        report['roughButWithinBudgetFullyRewrittenAccepted'] = {
            'verified': True, 'requireResult': True, 'authoredQuality': summary['request']['quality'], 'actualEncodingQuality': 60,
            'bytes': accepted['bytes'], 'originalBytes': len(good), 'meanAbsoluteRgb': accepted['error']['meanAbsoluteRgb'], 'maxMeanRGBError': accepted['error']['maxMeanRGBError'],
            'limit': 'the claim is decoded pixels and bytes within budget against dwebp; request.quality is the authored setting, not recovered or authenticated, and encoder history is not proven'}
        for path, content in saved.items():
            path.write_bytes(content)
        # Retained claims: no edit of the result, summary, plan or budget promotes the bytes.
        for label, name, edit in (('resultErrorSum', 'result.json', lambda d: d['error'].__setitem__('sumAbsoluteRgb', 0)),
                                  ('resultOperation', 'result.json', lambda d: d.__setitem__('operation', 'encodeLossless')),
                                  ('resultLosslessClaim', 'result.json', lambda d: d.__setitem__('lossless', True)),
                                  ('resultPerceptualClaim', 'result.json', lambda d: d.__setitem__('perceptual', True)),
                                  ('resultFreshDecoderArbitraryText', 'result.json', lambda d: d['runtime'].__setitem__('freshDecoder', 'bit-exact lossless')),
                                  ('resultFreshDecoderMissing', 'result.json', lambda d: d['runtime'].pop('freshDecoder')),
                                  ('resultBytesRetyped', 'result.json', lambda d: d.__setitem__('bytes', float(d['bytes']))),
                                  ('summaryMeanError', 'webp-summary.json', lambda d: d['error'].__setitem__('meanAbsoluteRgb', 0.0)),
                                  ('summaryWithinBudget', 'webp-summary.json', lambda d: d['error'].__setitem__('withinBudget', 1)),
                                  ('planBudget', 'plan.json', lambda d: d['budget'].__setitem__('maxMeanRGBError', 255)),
                                  ('authoredQuality', 'authored.json', lambda d: d.__setitem__('quality', 100))):
            data = adaptor.read_json(run, name)
            edit(data)
            atomic_json(run / name, data)
            report[label] = refused(lambda: adaptor.verify(run, decoder=dwebp), 'VERIFICATION_FAILED')['message']
            for path, content in saved.items():
                path.write_bytes(content)
        for name in ('authored.json', 'plan.json'):                       # a tighter budget in both copies makes the same bytes unacceptable
            data = adaptor.read_json(run, name)
            data['maxMeanRGBError'] = 0.5
            if name == 'plan.json':
                data['budget']['maxMeanRGBError'] = 0.5
            atomic_json(run / name, data)
        refresh()
        report['tightenedBudgetBothCopies'] = refused(lambda: adaptor.verify(run, decoder=dwebp), 'DELIVERABLE_NOT_MET')['message']
    finally:
        for path, content in saved.items():
            path.write_bytes(content)
    assert adaptor.verify(run, decoder=dwebp)['verified']
    return report


def trust(directory, cwebp, dwebp):
    """A receipt or PATH program is never launched; the decoder must be configured separately."""
    work = directory / 'trust'
    work.mkdir()
    sentinel = work / 'sentinel'
    shim = work / 'bin'
    shim.mkdir()
    for name in ('cwebp', 'dwebp'):
        (shim / name).write_text('#!/bin/sh\necho "$0" >> %s\nexit 1\n' % sentinel)
        (shim / name).chmod(0o700)
    run = directory / 'variants/gradient-fixture-q80'
    forged = run.parent / 'forged-receipt'    # a sibling, so the shared schema snapshot beside the run still resolves
    shutil.copytree(run, forged)
    receipt = adaptor.read_json(forged, 'verification.json')
    receipt['executables'] = {'encoder': str(shim / 'cwebp'), 'decoder': str(shim / 'dwebp')}
    atomic_json(forged / 'verification.json', receipt)
    saved = os.environ.get('PATH', '')
    os.environ['PATH'] = str(shim) + os.pathsep + saved
    report = {}
    try:
        with configuration_file(work / 'empty.json', {}):
            report['verifyWithoutConfiguredDecoder'] = refused(lambda: adaptor.verify(run), 'INTERPRETER_NOT_FOUND')
            report['runWithoutDecoder'] = refused(lambda: adaptor.run(document(FIXTURES / 'lossy-gradient-rgba.png', 80, 3), work / 'nodecoder', executable=cwebp), 'INTERPRETER_NOT_FOUND')
            report['runWithoutEncoder'] = refused(lambda: adaptor.run(document(FIXTURES / 'lossy-gradient-rgba.png', 80, 3), work / 'noencoder', decoder=dwebp), 'INTERPRETER_NOT_FOUND')
            report['relativeDecoder'] = refused(lambda: adaptor.verify(run, decoder='dwebp'), 'INTERPRETER_NOT_FOUND')
            report['receiptExecutableNotLaunched'] = refused(lambda: adaptor.verify(forged, decoder=dwebp), 'VERIFICATION_FAILED')['message']
        with configuration_file(work / 'stored.json', {'dwebp': dwebp}):
            report['storedDecoderVerifies'] = adaptor.verify(run)['verified']
    finally:
        os.environ['PATH'] = saved
    assert not sentinel.exists(), 'a PATH or receipt program was launched'
    report['sentinelUntouched'] = True
    return report


def cli(directory, cwebp, dwebp):
    """Real CLI processes: run into a fresh directory, verify by environment variable, and the over-budget exit."""
    work = directory / 'cli'
    work.mkdir()
    base = {k: v for k, v in os.environ.items() if not k.startswith('SCHEMAXIS_')}
    base['PYTHONPATH'] = str(ROOT / 'src')
    atomic_json(work / 'empty.json', {'version': 1, 'locations': {}})
    env = {**base, 'SCHEMAXIS_CONFIG': str(work / 'empty.json')}
    atomic_json(work / 'good.json', document(FIXTURES / 'lossy-gradient-rgba.png', 80, 3, maxBytes=1024))
    atomic_json(work / 'tight.json', document(FIXTURES / 'lossy-chart-rgb.png', 90, 0))
    atomic_json(work / 'translucent.json', document(FIXTURES / 'lossy-translucent-rgba.png', 80, 10))
    command = [sys.executable, '-m', 'schemaxis']
    out = native('cli-run-good', [*command, 'run', str(work / 'good.json'), '--webp', cwebp, '--dwebp', dwebp, '--output-directory', str(work / 'good')], work, env=env, timeout=120)
    report = {'run': json.loads(out)}
    report['verifyEnvironmentDecoder'] = json.loads(native('cli-verify-good', [*command, 'verify', str(work / 'good')], work, env={**env, 'SCHEMAXIS_DWEBP': dwebp}))['verified']
    tight = native('cli-run-tight', [*command, 'run', str(work / 'tight.json'), '--webp', cwebp, '--dwebp', dwebp, '--output-directory', str(work / 'tight')], work, env=env, timeout=120, expect=1).decode()
    assert 'DELIVERABLE_NOT_MET' in tight, tight[-400:]
    report['overBudgetRun'] = 'DELIVERABLE_NOT_MET (exit 1)'
    translucent = native('cli-run-translucent', [*command, 'run', str(work / 'translucent.json'), '--webp', cwebp, '--dwebp', dwebp, '--output-directory', str(work / 'translucent')], work, env=env, timeout=120, expect=1).decode()
    assert 'WEBP_ALPHA_UNSUPPORTED' in translucent, translucent[-400:]
    report['translucentRun'] = 'WEBP_ALPHA_UNSUPPORTED (exit 1)'
    verify_failed = native('cli-verify-failed-run', [*command, 'verify', str(work / 'tight')], work, env={**env, 'SCHEMAXIS_DWEBP': dwebp}, expect=1).decode()
    report['verifyOfFailedRun'] = 'refused (exit 1): ' + verify_failed.strip().replace('\n', ' ')[:140]
    return report


def lifecycle(directory, source, dwebp):
    wrapper = directory / 'slow-cwebp.py'
    marker = directory / 'slow.pid'
    wrapper.write_text('#!' + sys.executable + '\nimport os,time\nfrom pathlib import Path\nPath(' + repr(str(marker)) + ').write_text(str(os.getpid()))\ntime.sleep(30)\n')
    wrapper.chmod(0o700)
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
                results[action] = refused(lambda: adaptor.run(document(source, 80, 3), directory / ('inflight-' + action), executable=str(wrapper), decoder=dwebp,
                                                              timeout=10 if thread else .5), 'RUNNER_CANCELLED' if thread else 'RUNNER_TIMED_OUT')
        finally:
            if thread:
                thread.join(10)
        assert marker.exists()
        pid = int(marker.read_text())
        results[action]['nativePid'] = pid
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            results[action]['ownedProcessSurvived'] = False
        else:
            raise AssertionError('owned process survived ' + action)
        assert adaptor.read_json(directory / ('inflight-' + action), 'result.json')['verified'] is False
    return results


def collisions(directory, cwebp, dwebp):
    work = directory / 'collision'
    work.mkdir()
    source = FIXTURES / 'lossy-gradient-rgba.png'
    existing = work / 'existing'
    existing.mkdir()
    report = {'existingDirectory': refused(lambda: adaptor.run(document(source, 80, 3), existing, executable=cwebp, decoder=dwebp), 'OUTPUT_EXISTS')}
    target = work / 'raced'
    outcomes = []

    def attempt():
        try:
            outcomes.append(adaptor.run(document(source, 80, 3), target, executable=cwebp, decoder=dwebp, timeout=120)['status'])
        except SchemaxisError as error:
            outcomes.append(error.fault.code)
    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(180)
    assert sorted(outcomes) == ['OUTPUT_EXISTS', 'succeeded'], outcomes
    assert adaptor.verify(target, decoder=dwebp)['verified']
    report['simultaneousRunsSameDirectory'] = sorted(outcomes)
    return report


def budget(directory, cwebp, dwebp):
    """Largest accepted shapes with observed wall time, and a byte-budget refusal of a large noisy image."""
    report = {}
    for label, shape in (('1024x1024', (1024, 1024)), ('2048x512', (2048, 512))):
        source = directory / ('budget-%s.png' % label)
        source.write_bytes(png(noise(*shape)))
        start = time.monotonic()
        result = adaptor.run(document(source, 75, 255), directory / ('budget-' + label), executable=cwebp, decoder=dwebp, timeout=240)
        run_seconds = time.monotonic() - start
        start = time.monotonic()
        assert adaptor.verify(directory / ('budget-' + label), decoder=dwebp)['verified']
        report[label] = {'verified': result['verified'], 'sourceBytes': source.stat().st_size, 'webpBytes': result['bytes'], 'meanAbsoluteRgb': result['error']['meanAbsoluteRgb'],
                         'runSeconds': round(run_seconds, 1), 'verifySeconds': round(time.monotonic() - start, 1), 'content': 'pseudo-random opaque RGB noise (worst case for lossy coding)'}
    report['noisyOverByteBudget'] = refused(lambda: adaptor.run(document(directory / 'budget-1024x1024.png', 75, 255, maxBytes=100000), directory / 'budget-bytes', executable=cwebp, decoder=dwebp, timeout=240), 'DELIVERABLE_NOT_MET')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--webp', type=Path, required=True, help='absolute libwebp 1.6 cwebp')
    parser.add_argument('--dwebp', type=Path, required=True, help='absolute libwebp 1.6 dwebp')
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--register', action='store_true')
    args = parser.parse_args()
    directory = args.output_directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    cwebp, dwebp = str(args.webp.absolute()), str(args.dwebp.absolute())
    locations = {'webp': cwebp, 'dwebp': dwebp}
    report = {'verified': False, 'acceptancePid': os.getpid()}
    try:
        report['runtime'] = {'cwebp': native('cwebp-version', [cwebp, '-version'], directory).decode().strip().replace('\n', ' / '),
                             'dwebp': native('dwebp-version', [dwebp, '-version'], directory).decode().strip()}
        with configuration_file(directory / 'config.json', locations):
            receipt = qualify(adaptor.VERSION, directory / 'kit', native=True, root=ROOT, locations=locations, timeout=60, wall_timeout=180)
        report['native'] = {'verified': receipt['verified'], 'cases': [c['id'] for c in receipt['cases']], 'runtimes': [c['runtime'] for c in receipt['cases']],
                            'lifecycle': receipt['lifecycle']}
        with location_context(locations):
            report['variants'] = variants(directory, cwebp, dwebp)
            report['boundaries'] = boundaries(directory, cwebp, dwebp)
            report['negatives'] = negatives(directory, cwebp, dwebp)
            report['hostile'] = hostile(directory, cwebp, dwebp)
        report['trust'] = trust(directory, cwebp, dwebp)    # outside location_context: no decoder is supplied implicitly
        with location_context(locations):
            report['cli'] = cli(directory, cwebp, dwebp)
            source = directory / 'reuse.png'
            shutil.copyfile(FIXTURES / 'lossy-gradient-rgba.png', source)
            graph = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'publish', 'document': document(source, 80, 255)}]}
            first = workflow.execute(graph, directory / 'workflow', locations=locations, timeout=90)
            assert first['status'] == 'succeeded' and workflow.verify(directory / 'workflow')['verified']
            second = workflow.execute(graph, directory / 'workflow', locations=locations, timeout=90, resume=True)
            assert all(j['reused'] for j in second['jobs'])
            source.write_bytes(png(gradient(50, 30)))
            third = workflow.execute(graph, directory / 'workflow', locations=locations, timeout=90, resume=True)
            assert all(not j['reused'] for j in third['jobs']) and workflow.verify(directory / 'workflow')['verified']
            report['workflow'] = {'baseline': first['status'], 'unchangedReused': True, 'changedSamePathSourceBytesReused': False}
            report['inflightLifecycle'] = lifecycle(directory, FIXTURES / 'lossy-gradient-rgba.png', dwebp)
            report['collisions'] = collisions(directory, cwebp, dwebp)
            report['budget'] = budget(directory, cwebp, dwebp)
        if args.register:
            register(directory / 'kit/qualification.json')
        report['verified'] = True
    finally:
        report['probeProcesses'] = PROCESSES
        atomic_json(directory / 'acceptance.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
