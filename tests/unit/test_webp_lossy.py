"""Bounded lossy WebP (encodeLossy): planning, strict VP8 framing, exact error judgement, run/verify boundaries.

Deterministic fake cwebp/dwebp programs stand in for libwebp. The fake encoder quantises RGB according to ``-q`` and
stores it in a correctly framed simple-format ``VP8 `` chunk; the fake decoder returns it as an opaque PAM. These tests
therefore prove host behaviour only (budget judgement, framing, receipts, trusted executables, lifecycle). Native
libwebp acceptance is tools/qualify_webp_lossy.py. Tests needing real binaries run only when SCHEMAXIS_WEBP and
SCHEMAXIS_DWEBP are set and are reported skipped otherwise, never passed.
"""
import contextlib
import copy
from fractions import Fraction
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
from unittest import mock
import zlib

from schemaxis.adaptors import registry
from schemaxis.adaptors.webp import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'examples/schemaxis/fixtures/webp'

ENCODER = '''#!{python}
import re, struct, sys
args = sys.argv[1:]
if args == ['-version']:
    print('{version}'); print('libsharpyuv: 0.4.2'); sys.exit(0)
{marker}
quality = int(args[args.index('-q') + 1])
shift = {{100: 0}}.get(quality, 1 + (100 - quality) // 15)
data = open(args[args.index('source.pam')], 'rb').read()
found = re.match(rb'P7\\nWIDTH (\\d+)\\nHEIGHT (\\d+)\\n.*?ENDHDR\\n', data, re.S)
width, height, pixels = int(found.group(1)), int(found.group(2)), data[found.end():]
rgb = bytes(((v >> shift) << shift) for i, v in enumerate(pixels) if i % 4 != 3)
size = 10 + len(rgb)
tag = (1 << 4) | (1 << 5)           # key frame, version 0, shown, one-byte first partition
body = struct.pack('<I', tag)[:3] + b'\\x9d\\x01\\x2a' + struct.pack('<HH', width, height) + rgb
body += b'\\0' * (size & 1)
open(args[args.index('-o') + 1], 'wb').write(b'RIFF' + struct.pack('<I', 12 + len(body)) + b'WEBPVP8 ' + struct.pack('<I', size) + body)
sys.stderr.write('Output:    %d bytes (0.00 bpp)\\n' % (20 + len(body)))
'''
DECODER = '''#!{python}
import struct, sys
args = sys.argv[1:]
if args == ['-version']:
    print('1.6.0'); sys.exit(0)
{marker}
data = open(args[0], 'rb').read()
size = struct.unpack('<I', data[16:20])[0]
width, height = struct.unpack('<HH', data[26:30])
rgb = data[30:20 + size]
out = bytearray()
for i in range(0, len(rgb), 3):
    out += rgb[i:i + 3] + b'\\xff'
open(args[args.index('-o') + 1], 'wb').write(b'P7\\nWIDTH %d\\nHEIGHT %d\\nDEPTH 4\\nMAXVAL 255\\nTUPLTYPE RGB_ALPHA\\nENDHDR\\n' % (width, height) + bytes(out))
'''
REFUSE_ZEROED = (
    'if set(open(args[0], "rb").read()[30:]) == {0}:\n'
    '    sys.stderr.write("Decoding of image.webp failed.\\nStatus: 3(BITSTREAM_ERROR)\\n"); sys.exit(1)')

def program(directory, name, template, version='1.6.0', marker=''):
    path = Path(directory) / name
    path.write_text(template.format(python=sys.executable, version=version, marker=marker))
    path.chmod(0o700)
    return str(path)


def chunk(kind, value):
    return struct.pack('>I', len(value)) + kind + value + struct.pack('>I', zlib.crc32(kind + value) & 0xffffffff)


def png(width, height, pixel, colour=6):
    count = 4 if colour == 6 else 3
    raw = b''.join(b'\0' + bytes(v for x in range(width) for v in pixel(x, y)[:count]) for y in range(height))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, colour, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def vp8(width, height, payload=b'\0' * 12, tag=None, start=b'\x9d\x01\x2a', scale=0, kind=b'VP8 ', trailer=b''):
    """A simple-format VP8 file; ``tag`` defaults to a displayed key frame whose first partition is one byte."""
    tag = (1 << 4) | (1 << 5) if tag is None else tag
    body = struct.pack('<I', tag)[:3] + start + struct.pack('<HH', width | scale << 14, height | scale << 14) + payload
    size = len(body)
    body += b'\0' * (size & 1)
    body += trailer
    return b'RIFF' + struct.pack('<I', 12 + len(body) - 0) + b'WEBP' + kind + struct.pack('<I', size) + body


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


class Planning(unittest.TestCase):
    def document(self, **changes):
        document = {'version': 'schemaxis.webp/1', 'operation': 'encodeLossy', 'source': '/tmp/a.png', 'quality': 75, 'maxMeanRGBError': 3}
        document.update(changes)
        for key in [k for k, v in document.items() if v is ...]:
            del document[key]
        return document

    def fault(self, action, code):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    def test_plan_is_literal_deterministic_and_records_the_default_byte_cap(self):
        document = self.document()
        before = copy.deepcopy(document)
        prepared = adaptor.plan(document)
        self.assertEqual(document, before)
        self.assertEqual(prepared, adaptor.plan(document))
        self.assertEqual(prepared['operation'], 'encodeLossy')
        self.assertEqual(prepared['encoding']['arguments'], ['-q', '75', '-m', '6', '-alpha_q', '100'])
        for forbidden in ('-lossless', '-near_lossless', '-exact', '-z', '-preset', '-resize', '-crop'):
            self.assertNotIn(forbidden, prepared['encoding']['arguments'])
        self.assertEqual(prepared['budget']['maxBytes'], 16 * 1024 * 1024)
        self.assertIn('default', prepared['budget']['maxBytesSource'])
        self.assertEqual(adaptor.plan(self.document(maxBytes=4096))['budget']['maxBytes'], 4096)
        self.assertEqual(adaptor.plan(self.document(maxBytes=4096))['budget']['maxBytesSource'], 'authored')
        self.assertTrue(any('100 is not lossless' in loss for loss in prepared['losses']))

    def test_lossless_plan_and_arguments_are_untouched(self):
        prepared = adaptor.plan({'version': 'schemaxis.webp/1', 'operation': 'encodeLossless', 'source': '/tmp/a.png'})
        self.assertEqual(prepared['encoding']['arguments'], ['-lossless', '-exact', '-z', '6'])
        self.assertEqual(set(prepared), {'version', 'operation', 'source', 'encoding', 'budget', 'losses'})
        self.assertEqual(prepared['budget'], {'maxSide': 2048, 'maxPixels': 1048576, 'maxSourceBytes': 8388608, 'maxWebpBytes': 16777216})
        for key in ('quality', 'maxMeanRGBError', 'maxBytes'):
            self.fault(lambda: adaptor.plan({'version': 'schemaxis.webp/1', 'operation': 'encodeLossless', 'source': '/tmp/a.png', key: 1}), 'UNKNOWN_ARGUMENT')

    def test_quality_and_budgets_are_strict_typed_and_bounded(self):
        self.fault(lambda: adaptor.plan(self.document(quality=...)), 'MISSING_ARGUMENT')
        self.fault(lambda: adaptor.plan(self.document(maxMeanRGBError=...)), 'MISSING_ARGUMENT')
        for bad in (True, False, 75.0, '75', None, -1, 101, [75]):
            self.fault(lambda: adaptor.plan(self.document(quality=bad)), 'INVALID_ARGUMENT')
        for bad in (float('nan'), float('inf'), float('-inf'), True, '3', None, -0.001, 255.001, 256):
            self.fault(lambda: adaptor.plan(self.document(maxMeanRGBError=bad)), 'INVALID_ARGUMENT')
        for bad in (0, -1, 16 * 1024 * 1024 + 1, True, 4096.0, '4096', None):
            self.fault(lambda: adaptor.plan(self.document(maxBytes=bad)), 'INVALID_ARGUMENT')
        for edge in (0, 100):
            self.assertEqual(adaptor.plan(self.document(quality=edge))['quality'], edge)
        for edge in (0, 0.5, 255):
            self.assertEqual(adaptor.plan(self.document(maxMeanRGBError=edge))['maxMeanRGBError'], edge)
        for key in ('near_lossless', 'lossless', 'preset', 'flags', 'command', 'autoQuality', 'targetSize', 'resize', 'metadata'):
            self.fault(lambda: adaptor.plan(self.document(**{key: 1})), 'UNKNOWN_ARGUMENT')

    def test_json_schema_selects_operation_branches_and_requires_budgets(self):
        schema = adaptor.schema()
        lossless, lossy, _decode = schema['oneOf']
        self.assertEqual(lossless['required'], ['version', 'operation', 'source'])
        self.assertEqual(lossy['required'], ['version', 'operation', 'source', 'quality', 'maxMeanRGBError'])
        self.assertEqual(lossy['properties']['quality'], {'type': 'integer', 'minimum': 0, 'maximum': 100})
        self.assertEqual(lossy['properties']['maxMeanRGBError']['maximum'], 255)
        self.assertFalse(lossy['additionalProperties'])
        self.assertNotIn('quality', lossless['properties'])

    def test_registry_and_declarations_expose_both_operations(self):
        self.assertEqual(set(adaptor.DECLARATIONS), {'encodeLossless', 'encodeLossy', 'decodeToPng'})
        self.assertEqual(registry.query(self.document())['adaptors'][0]['operations'], ['encodeLossy'])
        self.assertEqual(set(adaptor.DECLARATIONS['encodeLossy']['options']), {'source', 'quality', 'maxMeanRGBError', 'maxBytes'})

    def test_examples_plan_and_the_discovery_surfaces_are_complete(self):
        from schemaxis.adaptor_conformance import host
        from schemaxis.capabilities import CapabilityCatalogue
        from schemaxis.search_acceptance import check_cases
        from schemaxis.studio_guidance import audit
        for name in ('gradient', 'chart', 'tight-budget', 'translucent'):
            document = json.loads((ROOT / f'examples/schemaxis/webp-lossy-{name}.json').read_text())
            self.assertEqual(adaptor.plan(document)['operation'], 'encodeLossy', name)
        self.assertTrue(host(adaptor.VERSION)['verified'])
        self.assertTrue(audit('webp')['complete'])
        self.assertTrue(check_cases(CapabilityCatalogue(providers=['webp']), 'webp')['complete'])
        catalogue = CapabilityCatalogue(providers=['webp'])
        hits = [i['id'] for i in catalogue.search('compress photo for web', scope='app/webp', limit=20, max_bytes=65536)['items']]
        self.assertEqual(hits, ['operation/webp/encodeLossy'])


class Judgement(unittest.TestCase):
    def prepared(self, budget, quality=50):
        return {'maxMeanRGBError': budget, 'quality': quality, 'budget': {'maxBytes': 100}}

    def test_error_is_the_exact_sum_over_every_rgb_sample(self):
        source = bytes([10, 20, 30, 255, 0, 0, 0, 255])
        decoded = bytes([12, 20, 25, 255, 1, 2, 3, 255])
        measure = adaptor.rgb_error(source, decoded)
        self.assertEqual((measure['sumAbsRGB'], measure['samples']), (2 + 0 + 5 + 1 + 2 + 3, 6))
        self.assertEqual(adaptor.rgb_error(source, source)['sumAbsRGB'], 0)
        # alpha samples never contribute: a differing alpha channel does not change the RGB error
        self.assertEqual(adaptor.rgb_error(source, bytes([10, 20, 30, 0, 0, 0, 0, 7]))['sumAbsRGB'], 0)

    def judge(self, total, samples, budget):
        adaptor.judge_lossy(self.prepared(budget), {'sumAbsRGB': total, 'samples': samples, 'meanAbsRGB': total / samples})

    def accepted(self, total, samples, budget):
        self.judge(total, samples, budget)

    def refused(self, total, samples, budget):
        with self.assertRaises(SchemaxisError) as caught:
            self.judge(total, samples, budget)
        fault = caught.exception.fault
        self.assertEqual((fault.code, fault.location), ('DELIVERABLE_NOT_MET', '$.maxMeanRGBError'))
        self.assertEqual(fault.observed['assessment']['sumAbsRGB'], total)
        self.assertEqual(fault.observed['assessment']['meanAbsRGBExact'], '%d/%d' % (Fraction(total, samples).numerator, Fraction(total, samples).denominator))
        self.assertIn('encodeLossless', fault.recovery)
        return fault

    def test_budget_comparison_is_exact_rational_arithmetic(self):
        measure = {'sumAbsRGB': 1, 'samples': 3, 'meanAbsRGB': 1 / 3}
        adaptor.judge_lossy(self.prepared(1), measure)
        adaptor.judge_lossy(self.prepared(0.34), measure)
        self.refused(1, 3, 0.3333333333333333)    # 1/3 is above the authored decimal 0.3333333333333333
        self.accepted(0, 3, 0)
        self.refused(1, 10 ** 6, 0)

    def test_an_error_exactly_equal_to_an_authored_decimal_budget_is_accepted(self):
        # the nearest doubles of 0.3 and 0.7 lie below the decimals; Fraction(0.3) once refused exactly 18/60
        self.accepted(18, 60, 0.3)
        self.accepted(6, 60, 0.1)
        self.accepted(42, 60, 0.7)
        self.accepted(12, 60, 0.2)
        self.accepted(321, 120, 2.675)
        self.accepted(18, 60, 0.30)
        self.accepted(3, 3, 1.0)

    def test_just_above_an_authored_decimal_budget_is_refused_and_just_below_accepted(self):
        self.refused(19, 60, 0.3)
        self.refused(7, 60, 0.1)
        self.refused(43, 60, 0.7)
        self.accepted(17, 60, 0.3)
        self.accepted(5, 60, 0.1)
        self.refused(322, 120, 2.675)
        # 1e17+1 over 1e18 is 0.100000000000000001: above the decimal 0.1 although below the double nearest 0.1
        self.refused(10 ** 17 + 1, 10 ** 18, 0.1)
        self.accepted(10 ** 17, 10 ** 18, 0.1)

    def test_integer_and_zero_budgets_are_exact(self):
        self.accepted(180, 60, 3)
        self.refused(181, 60, 3)
        self.accepted(255 * 60, 60, 255)
        self.accepted(0, 60, 0)
        self.accepted(0, 60, 0.0)
        self.refused(1, 60, 0)
        self.refused(1, 60, 0.0)

    def test_the_refusal_message_shows_the_exact_fraction_and_budget_never_equal_looking_numbers(self):
        fault = self.refused(19, 60, 0.3)
        self.assertIn('19/60', fault.message)
        self.assertIn('0.3', fault.message)
        self.assertNotIn('0.3 exceeds the budget 0.3', fault.message)
        self.assertEqual(fault.observed['assessment']['maxMeanRGBError'], 0.3)
        close = self.refused(10 ** 17 + 1, 10 ** 18, 0.1)
        self.assertIn('100000000000000001/1000000000000000000', close.message)
        self.assertIn('budget 0.1', close.message)

    def test_budgets_that_the_plan_refuses_never_reach_the_judgement(self):
        for bad in (float('nan'), float('inf'), float('-inf'), True, False, '0.3', None):
            with self.assertRaises(SchemaxisError) as caught:
                adaptor.plan({'version': 'schemaxis.webp/1', 'operation': 'encodeLossy', 'source': '/tmp/a.png', 'quality': 75, 'maxMeanRGBError': bad})
            self.assertEqual(caught.exception.fault.code, 'INVALID_ARGUMENT', repr(bad))

    def test_byte_budget_refusal_carries_figures_and_recovery(self):
        adaptor.judge_bytes(self.prepared(1), b'x' * 100)
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.judge_bytes(self.prepared(1), b'x' * 101)
        fault = caught.exception.fault
        self.assertEqual((fault.code, fault.location), ('DELIVERABLE_NOT_MET', '$.maxBytes'))
        self.assertEqual(fault.observed['assessment'], {'bytes': 101, 'maxBytes': 100, 'quality': 50})
        self.assertTrue(fault.recovery)

    def test_opaque_requirement_names_the_alpha_counts(self):
        opaque = {'rgba': bytes([1, 2, 3, 255] * 4)}
        adaptor.require_opaque(opaque)
        for alpha in (0, 1, 254):
            with self.assertRaises(SchemaxisError) as caught:
                adaptor.require_opaque({'rgba': bytes([1, 2, 3, 255] * 3 + [9, 9, 9, alpha])})
            fault = caught.exception.fault
            self.assertEqual(fault.code, 'WEBP_ALPHA_UNSUPPORTED')
            self.assertEqual(fault.observed['pixels']['opaque'], 3)
            self.assertIn('encodeLossless', fault.recovery)


class Vp8Framing(unittest.TestCase):
    def refuses(self, data):
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.vp8_header(data)
        self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED', caught.exception.fault.to_dict())
        return caught.exception.fault.message

    def test_a_plain_opaque_key_frame_is_accepted(self):
        self.assertEqual(adaptor.vp8_header(vp8(37, 23)), {'width': 37, 'height': 23, 'alphaFlag': False})
        self.assertEqual(adaptor.vp8_header(vp8(1, 1, payload=b'\0' * 11))['width'], 1)    # odd chunk size gets a pad byte
        self.assertEqual(adaptor.vp8_header(vp8(2048, 512))['height'], 512)

    def test_other_containers_and_trailing_data_are_refused(self):
        self.assertIn('not VP8', self.refuses(vp8(4, 4, kind=b'VP8L')))
        self.assertIn('not VP8', self.refuses(vp8(4, 4, kind=b'VP8X')))
        self.assertIn('not VP8', self.refuses(vp8(4, 4, kind=b'ALPH')))
        extra = vp8(4, 4)
        self.refuses(extra + b'\0\0')
        riff = bytearray(vp8(4, 4))
        riff[4:8] = struct.pack('<I', len(riff))            # RIFF size one chunk too large
        self.refuses(bytes(riff))
        chunk_size = bytearray(vp8(4, 4))
        chunk_size[16:20] = struct.pack('<I', 200)
        self.refuses(bytes(chunk_size))
        self.refuses(b'RIFF' + bytes(40))
        self.refuses(b'')
        self.refuses(vp8(4, 4)[:29])

    def test_frame_tag_start_code_scaling_and_dimensions_are_checked(self):
        self.assertIn('key frame', self.refuses(vp8(4, 4, tag=1 | (1 << 4) | (1 << 5))))      # inter frame
        self.assertIn('key frame', self.refuses(vp8(4, 4, tag=(1 << 5))))                     # not shown
        self.assertIn('key frame', self.refuses(vp8(4, 4, tag=(1 << 4) | (1 << 5) | (4 << 1))))   # version above 3
        self.assertIn('partition', self.refuses(vp8(4, 4, tag=(1 << 4))))                     # empty first partition
        self.assertIn('partition', self.refuses(vp8(4, 4, tag=(1 << 4) | (999 << 5))))
        self.assertIn('start code', self.refuses(vp8(4, 4, start=b'\x9d\x01\x2b')))
        self.assertIn('upscaling', self.refuses(vp8(4, 4, scale=1)))
        self.assertIn('budget', self.refuses(vp8(2049, 4)))
        self.assertIn('budget', self.refuses(vp8(1024, 1025)))
        self.assertIn('budget', self.refuses(vp8(0, 4)))


class FakeLossyBoundary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.encoder = program(self.root, 'cwebp', ENCODER)
        self.decoder = program(self.root, 'dwebp', DECODER)
        self.source = self.root / 'source.png'
        # asymmetric 13x7 opaque image: red follows x, green follows y, blue follows a diagonal
        self.pixel = lambda x, y: ((x * 19) % 256, (y * 37) % 256, (x * 5 + y * 11) % 256, 255)
        self.source.write_bytes(png(13, 7, self.pixel))
        self.document = {'version': 'schemaxis.webp/1', 'operation': 'encodeLossy', 'source': str(self.source), 'quality': 100, 'maxMeanRGBError': 0}
        self.environment = {k: v for k, v in os.environ.items() if k not in ('SCHEMAXIS_WEBP', 'SCHEMAXIS_DWEBP', 'SCHEMAXIS_CONFIG')}
        (self.root / 'empty.json').write_text('{"version": 1, "locations": {}}')

    @contextlib.contextmanager
    def private(self, locations=None):
        path = self.root / 'private-config.json'
        path.write_text(json.dumps({'version': 1, 'locations': locations or {}}))
        with mock.patch.dict(os.environ):
            os.environ['SCHEMAXIS_CONFIG'] = str(path)
            os.environ.pop('SCHEMAXIS_WEBP', None)
            os.environ.pop('SCHEMAXIS_DWEBP', None)
            yield

    def fault(self, action, code):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    def publish(self, name='run', encoder=None, decoder=None, **changes):
        directory = self.root / name
        document = {**self.document, **changes}
        result = adaptor.run(document, directory, executable=encoder or self.encoder, decoder=decoder or self.decoder, timeout=60)
        return directory, result

    def expected_error(self, shift):
        """Independent oracle: quantise each RGB sample like the fake codec and sum the differences."""
        total = 0
        for y in range(7):
            for x in range(13):
                for value in self.pixel(x, y)[:3]:
                    total += value - ((value >> shift) << shift)
        return total, 13 * 7 * 3

    def test_exact_budget_zero_run_succeeds_and_publishes_two_artifacts(self):
        directory, result = self.publish()
        self.assertTrue(result['verified'])
        self.assertEqual(result['operation'], 'encodeLossy')
        self.assertEqual(result['error']['sumAbsoluteRgb'], 0)
        self.assertEqual(result['error']['samples'], 273)
        receipt = adaptor.read_json(directory, 'verification.json')
        self.assertEqual([(Path(a['file']).name, a['kind']) for a in receipt['artifacts']], [('image.webp', 'image'), ('webp-summary.json', 'text')])
        summary = adaptor.read_json(directory, 'webp-summary.json')
        self.assertEqual(summary['image']['container'], 'RIFF WEBP simple format, one VP8 chunk')
        self.assertEqual(summary['request'], {'quality': 100, 'maxMeanRGBError': 0, 'maxBytes': 16 * 1024 * 1024})
        self.assertEqual(summary['error'], {'meanAbsoluteRgb': 0.0, 'sumAbsoluteRgb': 0, 'samples': 273, 'withinBudget': True})
        self.assertFalse(summary['image']['alphaFlag'])
        self.assertEqual(adaptor.verify(directory, decoder=self.decoder)['bytes'], (directory / 'image.webp').stat().st_size)
        self.assertIn('-q', (directory / 'encode-launcher.py').read_text())
        self.assertNotIn('-lossless', (directory / 'encode-launcher.py').read_text())

    def test_measured_error_matches_an_independent_oracle_and_is_judged_exactly(self):
        for quality, shift in ((85, 2), (55, 4), (25, 6)):
            total, samples = self.expected_error(shift)
            mean = total / samples
            directory, result = self.publish('q%d' % quality, quality=quality, maxMeanRGBError=mean + 0.001)
            self.assertEqual((result['error']['sumAbsoluteRgb'], result['error']['samples']), (total, samples))
            self.assertAlmostEqual(result['error']['meanAbsoluteRgb'], mean)
            self.assertEqual(adaptor.verify(directory, decoder=self.decoder)['error']['sumAbsoluteRgb'], total)
            below = self.fault(lambda: self.publish('below%d' % quality, quality=quality, maxMeanRGBError=mean - 0.001), 'DELIVERABLE_NOT_MET')
            self.assertEqual(below.observed['assessment']['sumAbsRGB'], total)

    def test_over_budget_is_a_failed_unverified_run_with_retained_evidence_and_no_publication(self):
        directory = self.root / 'over'
        fault = self.fault(lambda: adaptor.run({**self.document, 'quality': 25, 'maxMeanRGBError': 0.5}, directory, executable=self.encoder, decoder=self.decoder), 'DELIVERABLE_NOT_MET')
        self.assertEqual(fault.location, '$.maxMeanRGBError')
        self.assertTrue(fault.recovery)
        result = adaptor.read_json(directory, 'result.json')
        self.assertEqual((result['status'], result['verified']), ('failed', False))
        self.assertEqual(result['fault']['code'], 'DELIVERABLE_NOT_MET')
        self.assertTrue((directory / 'image.webp').is_file() and (directory / 'reopened.pam').is_file() and (directory / 'encode.stderr').is_file())
        self.assertFalse((directory / 'webp-summary.json').exists())
        self.assertFalse((directory / 'verification.json').exists())
        self.fault(lambda: adaptor.verify(directory, decoder=self.decoder), 'INCOMPLETE_EXECUTION')

    def test_byte_budget_refuses_a_correct_but_large_file(self):
        directory = self.root / 'big'
        fault = self.fault(lambda: adaptor.run({**self.document, 'maxBytes': 200}, directory, executable=self.encoder, decoder=self.decoder), 'DELIVERABLE_NOT_MET')
        self.assertEqual(fault.location, '$.maxBytes')
        self.assertGreater(fault.observed['assessment']['bytes'], 200)
        self.assertEqual(adaptor.read_json(directory, 'result.json')['status'], 'failed')
        exact = (directory / 'image.webp').stat().st_size
        self.publish('fits', maxBytes=exact)
        self.fault(lambda: self.publish('onelow', maxBytes=exact - 1), 'DELIVERABLE_NOT_MET')

    def test_verify_cannot_promote_a_failed_run_by_editing_retained_claims(self):
        directory = self.root / 'forge'
        self.fault(lambda: adaptor.run({**self.document, 'quality': 25, 'maxMeanRGBError': 0.5}, directory, executable=self.encoder, decoder=self.decoder), 'DELIVERABLE_NOT_MET')
        atomic_json(directory / 'result.json', {'status': 'succeeded', 'verified': True, 'artifacts': 2, 'dimensions': [13, 7], 'bytes': (directory / 'image.webp').stat().st_size})
        self.fault(lambda: adaptor.verify(directory, decoder=self.decoder), 'DELIVERABLE_NOT_MET')   # the fresh decode is judged, not the claims
        # raising the authored budget in both retained copies still cannot hide the missing summary and receipt
        for name in ('authored.json', 'plan.json'):
            document = adaptor.read_json(directory, name)
            document['maxMeanRGBError'] = 255
            if name == 'plan.json':
                document['budget']['maxMeanRGBError'] = 255
            atomic_json(directory / name, document)
        self.fault(lambda: adaptor.verify(directory, decoder=self.decoder), 'VERIFICATION_FAILED')

    def test_tampering_after_success_is_rejected_even_with_hashes_refreshed(self):
        directory, _ = self.publish('ok', quality=85, maxMeanRGBError=2)
        adaptor.verify(directory, decoder=self.decoder)
        for name in ('authored.json', 'plan.json'):                         # tighten the retained budget in both copies
            document = adaptor.read_json(directory, name)
            document['maxMeanRGBError'] = 0.01
            if name == 'plan.json':
                document['budget']['maxMeanRGBError'] = 0.01
            atomic_json(directory / name, document)
        refresh(directory)
        self.fault(lambda: adaptor.verify(directory, decoder=self.decoder), 'DELIVERABLE_NOT_MET')    # a fresh decode is judged against the tightened budget
        # replace the published bytes with a rougher encoding and refresh everything: the fresh decode is over budget
        directory, _ = self.publish('rough', quality=85, maxMeanRGBError=2)
        other, _ = self.publish('lowq', quality=5, maxMeanRGBError=255)
        (directory / 'image.webp').write_bytes((other / 'image.webp').read_bytes())
        (directory / 'reopened.pam').write_bytes((other / 'reopened.pam').read_bytes())
        refresh(directory)
        self.fault(lambda: adaptor.verify(directory, decoder=self.decoder), 'DELIVERABLE_NOT_MET')

    def test_retained_error_claims_and_summary_cannot_be_edited(self):
        directory, _ = self.publish('claims', quality=85, maxMeanRGBError=2)
        summary = adaptor.read_json(directory, 'webp-summary.json')
        summary['error']['meanAbsoluteRgb'] = 0.0
        atomic_json(directory / 'webp-summary.json', summary)
        self.fault(lambda: adaptor.verify(directory, decoder=self.decoder), 'VERIFICATION_FAILED')
        directory, _ = self.publish('claims2', quality=85, maxMeanRGBError=2)
        result = adaptor.read_json(directory, 'result.json')
        result['error']['sumAbsoluteRgb'] = 0
        atomic_json(directory / 'result.json', result)
        self.fault(lambda: adaptor.verify(directory, decoder=self.decoder), 'VERIFICATION_FAILED')
        directory, _ = self.publish('claims3', quality=85, maxMeanRGBError=2)
        result = adaptor.read_json(directory, 'result.json')
        result['operation'] = 'encodeLossless'
        atomic_json(directory / 'result.json', result)
        self.fault(lambda: adaptor.verify(directory, decoder=self.decoder), 'VERIFICATION_FAILED')

    def test_a_run_whose_exact_error_equals_the_authored_decimal_is_accepted_at_run_and_verify(self):
        # 5x4 opaque image, 60 samples; at quality 99 the fake codec drops the low bit, so error = number of odd samples
        for odd, name in ((18, 'edge'), (19, 'above')):
            source = self.root / (name + '.png')
            # six pixels of (1,1,1) give 18 odd samples; the 19th is one odd green sample of a seventh pixel
            source.write_bytes(png(5, 4, lambda x, y: (1, 1, 1, 255) if y * 5 + x < 6 else (1, 2, 2, 255) if odd == 19 and y * 5 + x == 6 else (2, 2, 2, 255)))
            change = {'source': str(source), 'quality': 99, 'maxMeanRGBError': 0.3}
            if odd == 18:
                directory, result = self.publish(name, **change)
                self.assertEqual((result['error']['sumAbsoluteRgb'], result['error']['samples']), (18, 60))
                self.assertEqual(adaptor.verify(directory, decoder=self.decoder)['error']['sumAbsoluteRgb'], 18)
                self.assertEqual(adaptor.read_json(directory, 'webp-summary.json')['request']['maxMeanRGBError'], 0.3)
            else:
                fault = self.fault(lambda: self.publish(name, **change), 'DELIVERABLE_NOT_MET')
                self.assertEqual(fault.observed['assessment']['sumAbsRGB'], 19)
                self.assertIn('19/60', fault.message)

    def forge_result(self, name, edit):
        directory, _ = self.publish(name, quality=85, maxMeanRGBError=2)
        result = adaptor.read_json(directory, 'result.json')
        edit(result)
        atomic_json(directory / 'result.json', result)
        return directory

    def test_result_record_is_a_closed_claim_set(self):
        def wipe(*path):
            def edit(result):
                for key in path[:-1]:
                    result = result[key]
                del result[path[-1]]
            return edit

        def put(path, value):
            def edit(result):
                for key in path[:-1]:
                    result = result[key]
                result[path[-1]] = value
            return edit
        forged = {
            'extra-lossless': put(('lossless',), True), 'extra-perceptual': put(('perceptual',), True),
            'extra-ratio': put(('compressionRatio',), 2.0), 'extra-nested-error': put(('error', 'lossless'), True),
            'extra-nested-runtime': put(('runtime', 'extra'), 'x'), 'extra-null': put(('note',), None),
            'missing-bytes': wipe('bytes'), 'missing-error': wipe('error'), 'missing-operation': wipe('operation'),
            'missing-runtime': wipe('runtime'), 'missing-encoder': wipe('runtime', 'encoder'), 'missing-fresh': wipe('runtime', 'freshDecoder'),
            'missing-error-field': wipe('error', 'maxBytes'),
            'promoted-verified-int': put(('verified',), 1), 'promoted-artifacts': put(('artifacts',), 3), 'promoted-unverified': put(('verified',), False),
            'promoted-operation': put(('operation',), 'encodeLossless'), 'promoted-bytes-float': lambda result: result.update(bytes=float(result['bytes'])),
            'type-dimensions': put(('dimensions',), ['13', 7]), 'type-bytes-text': put(('bytes',), 'many'),
            'type-error-mean': put(('error', 'meanAbsoluteRgb'), '0.5'), 'type-error-samples-float': put(('error', 'samples'), 273.0),
            'fresh-arbitrary': put(('runtime', 'freshDecoder'), 'bit-exact, lossless and perceptually identical'),
            'fresh-empty': put(('runtime', 'freshDecoder'), ''), 'fresh-number': put(('runtime', 'freshDecoder'), 1.6),
            'fresh-null': put(('runtime', 'freshDecoder'), None), 'fresh-list': put(('runtime', 'freshDecoder'), ['1.6.0']),
            'fresh-old': put(('runtime', 'freshDecoder'), '1.2.4'), 'fresh-trailing-text': put(('runtime', 'freshDecoder'), '1.6.0 lossless'),
            'runtime-not-object': put(('runtime',), '1.6.0'),
        }
        for name, edit in forged.items():
            with self.subTest(name):
                directory = self.forge_result(name, edit)
                self.fault(lambda: adaptor.verify(directory, decoder=self.decoder), 'VERIFICATION_FAILED')

    def test_a_legitimately_different_fresh_decoder_identity_still_verifies_but_nothing_else_may_change(self):
        for name, identity in (('patch', '1.6.9'), ('newline', '1.6.0\n')):
            directory = self.forge_result(name, lambda result, identity=identity: result['runtime'].update(freshDecoder=identity))
            self.assertTrue(adaptor.verify(directory, decoder=self.decoder)['verified'], name)
        directory, result = self.publish('genuine-shape', quality=85, maxMeanRGBError=2)
        self.assertEqual(set(result), {'status', 'verified', 'artifacts', 'dimensions', 'bytes', 'runtime', 'operation', 'error'})
        self.assertEqual(set(result['runtime']), {'encoder', 'decoder', 'freshDecoder'})
        self.assertEqual(adaptor.read_json(directory, 'result.json'), result)
        self.assertTrue(adaptor.verify(directory, decoder=self.decoder)['verified'])

    def test_lossless_result_record_keeps_its_genuine_shape_and_is_also_closed(self):
        encoder = program(self.root, 'cwebp-ll2', LOSSLESS_ENCODER)
        decoder = program(self.root, 'dwebp-ll2', LOSSLESS_DECODER)
        document = {'version': 'schemaxis.webp/1', 'operation': 'encodeLossless', 'source': str(self.source)}
        directory = self.root / 'lossless-closed'
        result = adaptor.run(document, directory, executable=encoder, decoder=decoder)
        self.assertEqual(set(result), {'status', 'verified', 'artifacts', 'dimensions', 'bytes', 'runtime'})
        self.assertEqual(set(result['runtime']), {'encoder', 'decoder', 'freshDecoder'})
        self.assertTrue(adaptor.verify(directory, decoder=decoder)['verified'])
        for edit in (lambda r: r.update(lossy=True), lambda r: r.update(error={}), lambda r: r.update(operation='encodeLossless'),
                     lambda r: r['runtime'].update(freshDecoder='lies'), lambda r: r.pop('bytes')):
            edited = dict(result, runtime=dict(result['runtime']))
            edit(edited)
            atomic_json(directory / 'result.json', edited)
            self.fault(lambda: adaptor.verify(directory, decoder=decoder), 'VERIFICATION_FAILED')

    def test_partial_and_transparent_alpha_are_refused_before_any_native_launch(self):
        marker = self.root / 'launched'
        encoder = program(self.root, 'cwebp-marked', ENCODER, marker='open(%r, "w").write("x")' % str(marker))
        for alpha in (0, 128, 254):
            source = self.root / ('alpha%d.png' % alpha)
            source.write_bytes(png(4, 3, lambda x, y: (9, 9, 9, alpha if (x, y) == (1, 1) else 255)))
            fault = self.fault(lambda: adaptor.run({**self.document, 'source': str(source)}, self.root / ('a%d' % alpha), executable=encoder, decoder=self.decoder), 'WEBP_ALPHA_UNSUPPORTED')
            self.assertEqual(fault.location, '$.source')
            self.assertIn('encodeLossless', fault.recovery)
            self.assertEqual(adaptor.read_json(self.root / ('a%d' % alpha), 'result.json')['fault']['code'], 'WEBP_ALPHA_UNSUPPORTED')
        self.assertFalse(marker.exists())
        # an opaque RGBA PNG and an RGB PNG are both accepted; lossless still takes the transparent source
        rgb = self.root / 'rgb.png'
        rgb.write_bytes(png(5, 3, self.pixel, colour=2))
        self.assertTrue(self.publish('rgb', source=str(rgb))[1]['verified'])
        transparent = self.root / 'alpha0.png'
        lossless = adaptor.run({'version': 'schemaxis.webp/1', 'operation': 'encodeLossless', 'source': str(transparent)}, self.root / 'lossless-a0',
                               executable=program(self.root, 'cwebp-ll', LOSSLESS_ENCODER), decoder=program(self.root, 'dwebp-ll', LOSSLESS_DECODER))
        self.assertTrue(lossless['verified'])

    def test_odd_and_one_pixel_geometry_round_trips(self):
        for width, height in ((1, 1), (1, 9), (9, 1), (17, 3), (3, 17)):
            source = self.root / ('g%dx%d.png' % (width, height))
            source.write_bytes(png(width, height, self.pixel))
            result = self.publish('g%dx%d' % (width, height), source=str(source))[1]
            self.assertEqual(result['dimensions'], [width, height])
            self.assertEqual(result['error']['samples'], width * height * 3)

    def test_corrupt_wrong_geometry_and_non_opaque_native_decodes_are_verification_failures(self):
        directory, _ = self.publish('good', quality=85, maxMeanRGBError=2)
        corrupt = program(self.root, 'dwebp-corrupt', DECODER, marker=REFUSE_ZEROED)
        webp = bytearray((directory / 'image.webp').read_bytes())
        webp[30:] = bytes(len(webp) - 30)
        (directory / 'image.webp').write_bytes(bytes(webp))
        refresh(directory)
        fault = self.fault(lambda: adaptor.verify(directory, decoder=corrupt), 'VERIFICATION_FAILED')
        self.assertIn('do not decode', fault.message)
        self.assertIn('cause', fault.observed)
        # a decoder that reports a different size than the captured PNG
        wrong = program(self.root, 'dwebp-wrong', DECODER, marker=(
            'import re as _r\n'
            'if args[0] != "-version":\n'
            '    _o = args[args.index("-o") + 1]\n'
            '    _d = open(args[0], "rb").read()\n'
            '    _s = struct.unpack("<I", _d[16:20])[0]\n'
            '    open(_o, "wb").write(b"P7\\nWIDTH 7\\nHEIGHT 13\\nDEPTH 4\\nMAXVAL 255\\nTUPLTYPE RGB_ALPHA\\nENDHDR\\n" + bytes(7 * 13 * 4))\n'
            '    sys.exit(0)'))
        directory, _ = self.publish('good2', quality=85, maxMeanRGBError=2)
        self.assertIn('dimensions', self.fault(lambda: adaptor.verify(directory, decoder=wrong), 'VERIFICATION_FAILED').message)
        # a decoder that returns partly transparent pixels
        translucent = program(self.root, 'dwebp-translucent', DECODER, marker=(
            'if args[0] != "-version":\n'
            '    _d = open(args[0], "rb").read()\n'
            '    _w, _h = struct.unpack("<HH", _d[26:30])\n'
            '    open(args[args.index("-o") + 1], "wb").write(b"P7\\nWIDTH %d\\nHEIGHT %d\\nDEPTH 4\\nMAXVAL 255\\nTUPLTYPE RGB_ALPHA\\nENDHDR\\n" % (_w, _h) + b"\\x01\\x02\\x03\\x80" * (_w * _h))\n'
            '    sys.exit(0)'))
        self.assertIn('opaque', self.fault(lambda: adaptor.verify(directory, decoder=translucent), 'VERIFICATION_FAILED').message)

    def test_a_non_vp8_native_emission_is_refused_at_run(self):
        lossless = program(self.root, 'cwebp-lossless', LOSSLESS_ENCODER)
        fault = self.fault(lambda: self.publish('wrong-container', encoder=lossless), 'VERIFICATION_FAILED')
        self.assertIn('not VP8', fault.message)
        self.assertEqual(adaptor.read_json(self.root / 'wrong-container', 'result.json')['verified'], False)

    def test_verification_needs_the_trusted_decoder_and_never_runs_a_receipt_or_path_program(self):
        directory, _ = self.publish('trusted')
        sentinel = self.root / 'sentinel-ran'
        shim = self.root / 'bin'
        shim.mkdir()
        for name in ('cwebp', 'dwebp'):
            path = shim / name
            path.write_text('#!/bin/sh\necho x >> %s\nexit 1\n' % sentinel)
            path.chmod(0o700)
        forged = self.root / 'forged-receipt'
        shutil.copytree(directory, forged)
        receipt = adaptor.read_json(forged, 'verification.json')
        receipt['executables'] = {'encoder': str(shim / 'cwebp'), 'decoder': str(shim / 'dwebp')}
        atomic_json(forged / 'verification.json', receipt)
        with self.private(), mock.patch.dict(os.environ, {'PATH': str(shim) + os.pathsep + os.environ.get('PATH', '')}):
            self.fault(lambda: adaptor.verify(directory), 'INTERPRETER_NOT_FOUND')
            self.fault(lambda: adaptor.verify(directory, decoder=str(shim / 'missing-dwebp')), 'INTERPRETER_NOT_FOUND')
            self.fault(lambda: adaptor.verify(directory, decoder='relative-dwebp'), 'INTERPRETER_NOT_FOUND')
            # a receipt naming a program is inert provenance: with the trusted decoder it is compared, never launched
            self.fault(lambda: adaptor.verify(forged, decoder=self.decoder), 'VERIFICATION_FAILED')
        self.assertFalse(sentinel.exists())
        with self.private({'dwebp': self.decoder}):
            self.assertTrue(adaptor.verify(directory)['verified'])

    def test_unsupported_runtime_stops_before_encoding_and_failed_native_stage_is_structured(self):
        old = program(self.root, 'cwebp-old', ENCODER, version='1.2.4')
        self.fault(lambda: self.publish('old', encoder=old), 'UNSUPPORTED_RUNTIME')
        failing = program(self.root, 'cwebp-fail', ENCODER, marker='sys.stderr.write("Error! Cannot read input\\n"); sys.exit(1)')
        fault = self.fault(lambda: self.publish('fail', encoder=failing), 'NATIVE_EXECUTION_FAILED')
        self.assertIn('exit 1', fault.message)

    def test_timeout_and_cancellation_end_the_owned_process_and_leave_a_failed_run(self):
        slow = program(self.root, 'cwebp-slow', ENCODER, marker='import time; time.sleep(30)')
        started = __import__('time').monotonic()
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.run(self.document, self.root / 'slow', executable=slow, decoder=self.decoder, timeout=2)
        self.assertLess(__import__('time').monotonic() - started, 20)
        self.assertNotEqual(caught.exception.fault.code, 'DELIVERABLE_NOT_MET')
        result = adaptor.read_json(self.root / 'slow', 'result.json')
        self.assertEqual((result['status'], result['verified']), ('failed', False))
        self.fault(lambda: adaptor.run(self.document, self.root / 'slow', executable=self.encoder, decoder=self.decoder), 'OUTPUT_EXISTS')
        self.fault(lambda: adaptor.run(self.document, self.root / 'badtimeout', executable=self.encoder, decoder=self.decoder, timeout=float('nan')), 'INVALID_ARGUMENT')

    def test_source_faults_for_lossy_stop_before_native_launch(self):
        marker = self.root / 'launched'
        encoder = program(self.root, 'cwebp-marked', ENCODER, marker='open(%r, "w").write("x")' % str(marker))
        missing = self.root / 'missing.png'
        self.fault(lambda: adaptor.run({**self.document, 'source': str(missing)}, self.root / 'm', executable=encoder, decoder=self.decoder), 'INVALID_WEBP_SOURCE')
        bad = self.root / 'bad.png'
        bad.write_bytes(b'not a png at all' * 4)
        self.fault(lambda: adaptor.run({**self.document, 'source': str(bad)}, self.root / 'b', executable=encoder, decoder=self.decoder), 'INVALID_WEBP_PNG')
        huge = self.root / 'huge.png'
        huge.write_bytes(png(1, 1, self.pixel)[:16] + struct.pack('>II', 3000, 3000) + png(1, 1, self.pixel)[24:])
        self.fault(lambda: adaptor.run({**self.document, 'source': str(huge)}, self.root / 'h', executable=encoder, decoder=self.decoder), 'WEBP_PIXEL_BUDGET')
        self.assertFalse(marker.exists())

    def test_workflow_reuse_hook_follows_the_captured_source_bytes(self):
        before = adaptor.reusableInputs(self.document)
        self.source.write_bytes(png(13, 7, lambda x, y: (1, 2, 3, 255)))
        self.assertNotEqual(before, adaptor.reusableInputs(self.document))

    @unittest.skipUnless(os.environ.get('SCHEMAXIS_WEBP') and os.environ.get('SCHEMAXIS_DWEBP'), 'needs real libwebp 1.6 cwebp and dwebp')
    def test_real_libwebp_publishes_the_gradient_fixture(self):
        document = {**json.loads((ROOT / 'examples/schemaxis/webp-lossy-gradient.json').read_text()), 'source': str(FIXTURES / 'lossy-gradient-rgba.png')}
        result = adaptor.run(document, self.root / 'real', executable=os.environ['SCHEMAXIS_WEBP'], decoder=os.environ['SCHEMAXIS_DWEBP'])
        self.assertTrue(result['verified'])
        self.assertLessEqual(result['error']['meanAbsoluteRgb'], 3)
        self.assertLessEqual(result['bytes'], 1024)


LOSSLESS_ENCODER = '''#!{python}
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
LOSSLESS_DECODER = '''#!{python}
import struct, sys
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


if __name__ == '__main__':
    unittest.main()
