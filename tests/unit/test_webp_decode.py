"""WebP to PNG handoff (decodeToPng): planning, source framing, canonical PNG, run/verify boundaries.

Deterministic fake dwebp programs stand in for libwebp. The fake decoder reads a correctly framed simple-format
``VP8L`` or ``VP8 `` file whose payload is raw RGBA (VP8L) or raw RGB (VP8) and writes a PAM; it prints dwebp 1.6's own
report on stderr. These tests therefore prove host behaviour only: framing, canonical PNG, hand-literal samples, refusals,
tampering with refreshed hashes, trusted executables and lifecycle. Native libwebp acceptance is
tools/qualify_webp_decode.py. Tests needing the real binary run only when SCHEMAXIS_DWEBP is set (SCHEMAXIS_WEBP adds
the real encoder round trip) and are reported skipped otherwise, never passed.
"""
import contextlib
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import zlib

from schemaxis import png as shared_png
from schemaxis.adaptors import registry
from schemaxis.adaptors.webp import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'examples/schemaxis/fixtures/webp'

DECODER = '''#!{python}
import struct, sys
args = sys.argv[1:]
if args == ['-version']:
    print('{version}'); sys.exit(0)
assert args[1:4] == ['-nodither', '-pam', '-o'] and len(args) == 5, args
data = open(args[0], 'rb').read()
size = struct.unpack('<I', data[16:20])[0]
if data[12:16] == b'VP8L':
    bits = struct.unpack('<I', data[21:25])[0]
    width, height, alpha, fmt, pixels = (bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1, bool(bits >> 28 & 1), 'lossless', data[25:20 + size]
else:
    width, height = [v & 0x3fff for v in struct.unpack('<HH', data[26:30])]     # libwebp ignores the two upscaling bits
    alpha, fmt, rgb = False, 'lossy', data[30:20 + size]
    pixels = b''.join(rgb[i:i + 3] + b'\\xff' for i in range(0, len(rgb), 3))
{marker}
sys.stderr.write('Decoded %s. Dimensions: %d x %d %s. Format: %s. Now saving...\\nSaved file %s\\n' % (args[0], width, height, ' (with alpha)' if alpha else '', fmt, args[4]))
open(args[4], 'wb').write(b'P7\\nWIDTH %d\\nHEIGHT %d\\nDEPTH 4\\nMAXVAL 255\\nTUPLTYPE RGB_ALPHA\\nENDHDR\\n' % (width, height) + pixels)
'''
CORRUPT = 'sys.stderr.write("Decoding of captured.webp failed.\\nStatus: 3(BITSTREAM_ERROR)\\n"); sys.exit(1)'

# Hand-written 4x3 RGBA literal: pure primaries, partial alpha, and RGB hidden under alpha 0.
LITERAL = [[(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 255, 255)],
           [(10, 20, 30, 128), (200, 100, 50, 64), (7, 8, 9, 0), (250, 251, 252, 0)],
           [(0, 0, 0, 255), (128, 128, 128, 255), (1, 2, 3, 1), (254, 253, 252, 254)]]
LITERAL_BYTES = bytes(v for row in LITERAL for pixel in row for v in pixel)
# Plan digests of two documents taken from the unmodified adaptor (sha256 of the sorted-key JSON plan).
LEGACY_PLANS = {'encodeLossless': ({'version': 'schemaxis.webp/1', 'operation': 'encodeLossless', 'source': '/tmp/a.png'},
                                   '67c9b7e7365ebe5e2051af0f974c78ae83e1f8201a1aea5e4ad13cb393dd5fce'),
                'encodeLossy': ({'version': 'schemaxis.webp/1', 'operation': 'encodeLossy', 'source': '/tmp/a.png', 'quality': 75, 'maxMeanRGBError': 3},
                                '6b5b48fd54cddd2358e298a8aff193fb9a3f68bfca824b7a526ef29ead7a9e2f')}


def program(directory, name, template=DECODER, version='1.6.0', marker=''):
    path = Path(directory) / name
    path.write_text(template.format(python=sys.executable, version=version, marker=marker))
    path.chmod(0o700)
    return str(path)


def vp8l(width, height, rgba, alpha=True, version=0, trailer=b'', riff_delta=0):
    bits = (width - 1) | ((height - 1) << 14) | (int(alpha) << 28) | (version << 29)
    body = b'\x2f' + struct.pack('<I', bits) + rgba
    size = len(body)
    body += b'\0' * (size & 1)
    return b'RIFF' + struct.pack('<I', 12 + len(body) + len(trailer) + riff_delta) + b'WEBPVP8L' + struct.pack('<I', size) + body + trailer


def vp8(width, height, rgb=b'\0' * 12, tag=None, start=b'\x9d\x01\x2a', scale=0, trailer=b'', vscale=None):
    tag = (1 << 4) | (1 << 5) if tag is None else tag
    vscale = scale if vscale is None else vscale
    body = struct.pack('<I', tag)[:3] + start + struct.pack('<HH', width | scale << 14, height | vscale << 14) + rgb
    size = len(body)
    body += b'\0' * (size & 1)
    return b'RIFF' + struct.pack('<I', 12 + len(body) + len(trailer)) + b'WEBPVP8 ' + struct.pack('<I', size) + body + trailer


def riff(fourcc, payload):
    body = fourcc + struct.pack('<I', len(payload)) + payload + b'\0' * (len(payload) & 1)
    return b'RIFF' + struct.pack('<I', 4 + len(body)) + b'WEBP' + body


def chunk(kind, value):
    return struct.pack('>I', len(value)) + kind + value + struct.pack('>I', zlib.crc32(kind + value) & 0xffffffff)


def raw_png(width, height, rows, colour=6, depth=8, interlace=0, extra=(), trailer=b''):
    """A PNG made independently of the adaptor writer, so tampering can vary filter, chunks and colour type."""
    data = b''.join(rows)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, depth, colour, 0, 0, interlace))
            + b''.join(chunk(k, v) for k, v in extra) + chunk(b'IDAT', zlib.compress(data)) + chunk(b'IEND', b'')) + trailer


def literal_rows(filter_type=0):
    return [bytes([filter_type]) + bytes(v for pixel in row for v in pixel) for row in LITERAL]


def refresh(directory):
    """Make every ordinary hash agree with the (tampered) files, as a forging writer would."""
    directory = Path(directory)
    receipt = adaptor.read_json(directory, 'verification.json')
    atomic_json(directory / 'decode-inputs.json', {'captured.webp': adaptor.digest(directory, 'captured.webp')})
    atomic_json(directory / 'captures.json', {**adaptor.read_json(directory, 'captures.json'), 'bytes': (directory / 'captured.webp').stat().st_size,
                                              'sha256': adaptor.digest(directory, 'captured.webp')})
    receipt['evidence'] = {n: adaptor.digest(directory, n) for n in sorted(receipt['evidence'])}
    receipt['artifacts'] = adaptor.publications(directory, image='image.png')
    atomic_json(directory / 'verification.json', receipt)


class Planning(unittest.TestCase):
    def document(self, **changes):
        document = {'version': 'schemaxis.webp/1', 'operation': 'decodeToPng', 'source': '/tmp/a.webp'}
        document.update(changes)
        for key in [k for k, v in document.items() if v is ...]:
            del document[key]
        return document

    def fault(self, action, code):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    def test_plan_is_literal_deterministic_and_native_flags_are_fixed(self):
        document = self.document()
        before = copy.deepcopy(document)
        prepared = adaptor.plan(document)
        self.assertEqual(document, before)
        self.assertEqual(prepared, adaptor.plan(document))
        self.assertEqual(set(prepared), {'version', 'operation', 'source', 'decoding', 'budget', 'losses'})
        self.assertEqual(prepared['decoding']['arguments'], ['-nodither', '-pam'])
        self.assertEqual(prepared['budget'], {'maxSide': 2048, 'maxPixels': 1048576, 'maxWebpBytes': 16777216, 'maxPngBytes': 5242880})
        self.assertTrue(any('not an independent host WebP decoder' in loss for loss in prepared['losses']))
        self.assertEqual(adaptor.query(document), (['decodeToPng'], {}))

    def test_source_must_be_an_absolute_local_webp_and_nothing_else_is_accepted(self):
        for bad in ('relative.webp', 'https://example.test/a.webp', 'file:///tmp/a.webp', '/tmp/a.png', '/tmp/a', '/tmp/a.webp\0', '', '~/a.webp'):
            self.fault(lambda: adaptor.plan(self.document(source=bad)), 'INVALID_WEBP_SOURCE' if bad else 'INVALID_ARGUMENT')
        self.assertEqual(adaptor.plan(self.document(source='/tmp/A.WEBP'))['source'], '/tmp/A.WEBP')
        self.fault(lambda: adaptor.plan(self.document(source=...)), 'MISSING_ARGUMENT')
        self.fault(lambda: adaptor.plan(self.document(source=7)), 'INVALID_ARGUMENT')
        for key in ('quality', 'maxMeanRGBError', 'maxBytes', 'flags', 'dither', 'nofancy', 'format', 'crop', 'scale', 'output'):
            self.fault(lambda: adaptor.plan(self.document(**{key: 1})), 'UNKNOWN_ARGUMENT')
        self.fault(lambda: adaptor.plan({**self.document(), 'operation': 'decode'}), 'UNKNOWN_FILTER')

    def test_the_png_encode_operations_still_require_a_png_and_plan_exactly_as_before(self):
        for name, (document, digest) in LEGACY_PLANS.items():
            self.assertEqual(hashlib.sha256(json.dumps(adaptor.plan(document), sort_keys=True).encode()).hexdigest(), digest, name)
            self.fault(lambda: adaptor.plan({**document, 'source': '/tmp/a.webp'}), 'INVALID_WEBP_SOURCE')

    def test_json_schema_and_declarations_add_one_branch_and_leave_the_others(self):
        lossless, lossy, decode = adaptor.schema()['oneOf']
        self.assertEqual(decode['required'], ['version', 'operation', 'source'])
        self.assertEqual(decode['properties']['operation'], {'const': 'decodeToPng'})
        self.assertFalse(decode['additionalProperties'])
        self.assertEqual(lossless['required'], ['version', 'operation', 'source'])
        self.assertEqual(lossy['required'], ['version', 'operation', 'source', 'quality', 'maxMeanRGBError'])
        self.assertEqual(adaptor.schema()['properties']['operation'], {'enum': ['encodeLossless', 'encodeLossy', 'decodeToPng']})
        self.assertEqual(set(adaptor.DECLARATIONS), {'encodeLossless', 'encodeLossy', 'decodeToPng'})
        self.assertEqual(set(adaptor.DECLARATIONS['decodeToPng']['options']), {'source'})
        self.assertEqual(registry.query(self.document())['adaptors'][0]['operations'], ['decodeToPng'])

    def test_examples_plan_and_the_discovery_surfaces_are_complete(self):
        from schemaxis.adaptor_conformance import host
        from schemaxis.capabilities import CapabilityCatalogue
        from schemaxis.search_acceptance import check_cases
        from schemaxis.studio_guidance import audit
        for name in ('lossless', 'rgb', 'lossy'):
            document = json.loads((ROOT / f'examples/schemaxis/webp-decode-{name}.json').read_text())
            self.assertEqual(adaptor.plan(document)['operation'], 'decodeToPng', name)
        invalid = json.loads((ROOT / 'examples/schemaxis/webp-decode-invalid-source.json').read_text())
        self.fault(lambda: adaptor.plan(invalid), 'INVALID_WEBP_SOURCE')
        self.assertTrue(host(adaptor.VERSION)['verified'])
        self.assertTrue(audit('webp')['complete'])
        self.assertTrue(check_cases(CapabilityCatalogue(providers=['webp']), 'webp')['complete'])
        catalogue = CapabilityCatalogue(providers=['webp'])
        hits = [i['id'] for i in catalogue.search('convert WebP to PNG', scope='app/webp', limit=20, max_bytes=65536)['items']]
        self.assertEqual(hits[:1], ['operation/webp/decodeToPng'])


class SourceFraming(unittest.TestCase):
    def refused(self, data, code='INVALID_WEBP_IMAGE'):
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.source_header(data)
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        self.assertEqual(caught.exception.fault.location, '$.source')

    def test_the_two_simple_profiles_are_read_before_any_native_process(self):
        self.assertEqual(adaptor.source_header(vp8l(4, 3, LITERAL_BYTES)), {'chunk': 'VP8L', 'width': 4, 'height': 3, 'alphaFlag': True})
        self.assertEqual(adaptor.source_header(vp8l(1, 1, b'\1\2\3\4', alpha=False))['alphaFlag'], False)
        self.assertEqual(adaptor.source_header(vp8l(3, 1, b'\0' * 12))['width'], 3)     # odd chunk size: one zero pad byte
        self.assertEqual(adaptor.source_header(vp8(5, 2)), {'chunk': 'VP8', 'width': 5, 'height': 2, 'alphaFlag': False})
        self.assertEqual(adaptor.source_header(vp8l(2048, 512, b''))['height'], 512)
        self.assertEqual(adaptor.source_header(vp8l(1024, 1024, b''))['width'], 1024)   # exactly 1,048,576 pixels
        # the real files made by libwebp 1.6.0 from the committed fixtures
        for name, expected in (('decode-literal-rgba', ('VP8L', 4, 3, True)), ('decode-swatch-rgb', ('VP8L', 5, 3, False)), ('decode-gradient-lossy', ('VP8', 96, 60, False))):
            header = adaptor.source_header((FIXTURES / (name + '.webp')).read_bytes())
            self.assertEqual((header['chunk'], header['width'], header['height'], header['alphaFlag']), expected, name)

    def test_malformed_container_extended_animated_and_oversized_files_are_refused(self):
        good = vp8l(4, 3, LITERAL_BYTES)
        for data in (b'', b'RIFF', good[:-1], good + b'\0', good + b'JUNK', b'RIFX' + good[4:], good[:8] + b'WEBQ' + good[12:], good[:12] + b'VP8Z' + good[16:],
                     vp8l(4, 3, LITERAL_BYTES, riff_delta=2), vp8l(4, 3, LITERAL_BYTES, version=1), good[:20] + b'\x2e' + good[21:],
                     good[:16] + struct.pack('<I', 5) + good[20:], riff(b'ALPH', b'\0' * 8), riff(b'VP8 ', b'\0' * 4)):
            self.refused(data)
        odd = vp8l(3, 1, b'\0' * 12)
        self.refused(odd[:-1] + b'\1')                                                 # non-zero pad byte
        animated = riff(b'VP8X', bytes([0x12, 0, 0, 0, 3, 0, 0, 3, 0, 0]) + b'ANIM' + struct.pack('<I', 6) + b'\0' * 6)
        self.refused(animated, 'WEBP_ANIMATION_UNSUPPORTED')
        for flags in (0x10, 0x20, 0x08, 0x04, 0x00):
            self.refused(riff(b'VP8X', bytes([flags, 0, 0, 0, 3, 0, 0, 3, 0, 0])), 'WEBP_FORMAT_UNSUPPORTED')
        for width, height in ((2049, 1), (1, 2049), (1025, 1025), (2048, 2048), (16384, 1)):
            self.refused(vp8l(width, height, b''), 'WEBP_PIXEL_BUDGET')
        self.refused(vp8(2049, 1), 'WEBP_PIXEL_BUDGET')

    def test_lossy_frame_tag_start_code_and_dimensions_are_checked(self):
        for data in (vp8(4, 4, tag=(1 << 4) | (1 << 5) | 1), vp8(4, 4, tag=(1 << 5)), vp8(4, 4, tag=(1 << 4) | (1 << 5) | (4 << 1)),
                     vp8(4, 4, tag=1 << 4), vp8(4, 4, tag=(1 << 4) | (100 << 5)), vp8(4, 4, start=b'\x9d\x01\x2b'),
                     vp8(4, 4, trailer=b'\0\0'), vp8(0, 4), vp8(4, 0, scale=3), vp8(4, 4)[:29]):
            self.refused(data)
        self.refused(vp8(2049, 1, scale=2), 'WEBP_PIXEL_BUDGET')                         # the budget judges the coded size, not the scaled one

    def test_vp8_upscaling_bits_are_a_display_hint_and_every_combination_is_accepted(self):
        for horizontal in range(4):
            for vertical in range(4):
                header = adaptor.source_header(vp8(5, 2, scale=horizontal, vscale=vertical))
                self.assertEqual(header, {'chunk': 'VP8', 'width': 5, 'height': 2, 'alphaFlag': False}, (horizontal, vertical))


class CanonicalPng(unittest.TestCase):
    def test_encoder_writes_exactly_ihdr_idat_iend_and_two_readers_agree(self):
        rgba = bytes([1, 2, 3, 4, 5, 6, 7, 8])
        data = adaptor.encode_png(2, 1, rgba, True)
        self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(data[8:33], struct.pack('>I', 13) + b'IHDR' + struct.pack('>IIBBBBB', 2, 1, 8, 6, 0, 0, 0) + struct.pack('>I', zlib.crc32(b'IHDR' + struct.pack('>IIBBBBB', 2, 1, 8, 6, 0, 0, 0))))
        self.assertEqual(data[-12:], b'\0\0\0\0IEND\xaeB`\x82')
        kinds, offset = [], 8
        while offset < len(data):
            length, kind = struct.unpack_from('>I4s', data, offset)
            kinds.append(kind)
            if kind == b'IDAT':
                self.assertEqual(zlib.decompress(data[offset + 8:offset + 8 + length]), b'\x00\x01\x02\x03\x04\x05\x06\x07\x08')
            offset += 12 + length
        self.assertEqual(kinds, [b'IHDR', b'IDAT', b'IEND'])
        self.assertEqual(adaptor.read_canonical_png(data)['rgba'], rgba)
        self.assertEqual(shared_png.decode(data)[:2], (2, 1))
        self.assertEqual(bytes(shared_png.decode(data)[2]), rgba)
        # RGB keeps three samples per pixel and reads back with alpha 255
        rgb = adaptor.encode_png(2, 1, bytes([9, 8, 7, 255, 6, 5, 4, 255]), False)
        image = adaptor.read_canonical_png(rgb)
        self.assertEqual((image['alpha'], image['rgba']), (False, bytes([9, 8, 7, 255, 6, 5, 4, 255])))
        self.assertEqual(rgb[8 + 8 + 9], 2)                                            # colour type byte in IHDR
        self.assertEqual(bytes(shared_png.decode(rgb)[2]), image['rgba'])

    def test_every_hand_literal_sample_survives_the_png_round_trip(self):
        data = adaptor.encode_png(4, 3, LITERAL_BYTES, True)
        self.assertEqual(adaptor.read_canonical_png(data)['rgba'], LITERAL_BYTES)
        self.assertEqual(bytes(shared_png.decode(data)[2]), LITERAL_BYTES)
        self.assertEqual(adaptor.read_canonical_png(data)['rgba'][4 * (4 + 2):4 * (4 + 2) + 4], bytes([7, 8, 9, 0]))   # hidden RGB

    def test_the_reader_refuses_everything_that_is_not_the_canonical_form(self):
        good = raw_png(4, 3, literal_rows())
        self.assertEqual(adaptor.read_canonical_png(good)['rgba'], LITERAL_BYTES)
        cases = {
            'trailing': raw_png(4, 3, literal_rows(), trailer=b'\0'),
            'text chunk': raw_png(4, 3, literal_rows(), extra=[(b'tEXt', b'k\0v')]),
            'srgb chunk': raw_png(4, 3, literal_rows(), extra=[(b'sRGB', b'\0')]),
            'filter sub': raw_png(4, 3, literal_rows(1)),
            'sixteen bit': raw_png(4, 3, literal_rows(), depth=16),
            'palette': raw_png(4, 3, [b'\0' + bytes(4)] * 3, colour=3),
            'grey alpha': raw_png(4, 3, [b'\0' + bytes(8)] * 3, colour=4),
            'interlaced': raw_png(4, 3, literal_rows(), interlace=1),
            'wrong height': raw_png(4, 2, literal_rows()),
            'short data': raw_png(4, 3, literal_rows()[:2]),
            'bad crc': good[:-1] + b'\0',
            'no signature': b'\x89PNG' + good[4:8].replace(b'\r', b'\n') + good[8:],
            'truncated': good[:-5], 'empty': b'',
            'oversized': raw_png(2049, 1, [b'\0' + bytes(2049 * 4)]),
        }
        for name, data in cases.items():
            with self.assertRaises(SchemaxisError, msg=name) as caught:
                adaptor.read_canonical_png(data)
            self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED', name)
        idat_twice = good[:-12] + chunk(b'IDAT', b'') + good[-12:]
        with self.assertRaises(SchemaxisError):
            adaptor.read_canonical_png(idat_twice)


class FakeDecodeBoundary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.decoder = program(self.root, 'dwebp')
        self.source = self.root / 'source.webp'
        self.source.write_bytes(vp8l(4, 3, LITERAL_BYTES))
        self.document = {'version': 'schemaxis.webp/1', 'operation': 'decodeToPng', 'source': str(self.source)}
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

    def decode(self, name='run', data=None, decoder=None, **changes):
        if data is not None:
            self.source.write_bytes(data)
        directory = self.root / name
        result = adaptor.run({**self.document, **changes}, directory, decoder=decoder or self.decoder, timeout=60)
        return directory, result

    def reject_after_refresh(self, directory, message=None):
        refresh(directory)
        fault = self.fault(lambda: adaptor.verify(directory, decoder=self.decoder), 'VERIFICATION_FAILED')
        if message:
            self.assertIn(message, fault.message)

    def test_hand_literal_rgba_run_publishes_the_exact_samples_with_only_a_decoder_configured(self):
        with self.private():
            directory, result = self.decode()
        self.assertEqual(result, {'status': 'succeeded', 'verified': True, 'operation': 'decodeToPng', 'artifacts': 2, 'dimensions': [4, 3],
                                  'bytes': (directory / 'image.png').stat().st_size, 'sourceBytes': self.source.stat().st_size,
                                  'runtime': {'decoder': '1.6.0', 'freshDecoder': '1.6.0'}})
        png_bytes = (directory / 'image.png').read_bytes()
        width, height, samples = shared_png.decode(png_bytes)                            # the shared decoder is independent of the writer
        self.assertEqual((width, height, bytes(samples)), (4, 3, LITERAL_BYTES))
        for y, row in enumerate(LITERAL):
            for x, pixel in enumerate(row):
                self.assertEqual(tuple(samples[4 * (4 * y + x):4 * (4 * y + x) + 4]), pixel, (x, y))
        summary = adaptor.read_json(directory, 'webp-summary.json')
        self.assertEqual(summary['pixels'], {'total': 12, 'opaque': 6, 'partialAlpha': 4, 'transparent': 2, 'transparentWithRgb': 2})
        self.assertEqual(summary['source']['container'], 'RIFF WEBP simple format, one VP8L chunk')
        self.assertTrue(summary['source']['alphaFlag'])
        self.assertEqual(summary['image']['format'], 'PNG 8-bit RGBA, chunks IHDR IDAT IEND, filter none')
        self.assertEqual(summary['readback']['rgbaSha256'], hashlib.sha256(LITERAL_BYTES).hexdigest())
        self.assertEqual(summary['readback']['report'], {'dimensions': [4, 3], 'format': 'lossless', 'withAlpha': True})
        receipt = adaptor.read_json(directory, 'verification.json')
        self.assertEqual([(Path(a['file']).name, a['kind']) for a in receipt['artifacts']], [('image.png', 'image'), ('webp-summary.json', 'text')])
        self.assertEqual(set(receipt['executables']), {'decoder'})
        self.assertEqual(set(receipt['runtime']), {'decoder'})
        self.assertEqual(set(receipt['evidence']), adaptor.decode_names())
        self.assertFalse(any((directory / n).exists() for n in ('source.pam', 'captured.png', 'encode-launcher.py', 'image.webp', 'reopened.pam')))
        self.assertIn('-nodither', (directory / 'decode-launcher.py').read_text())
        self.assertEqual(adaptor.verify(directory, decoder=self.decoder)['bytes'], len(png_bytes))

    def test_opaque_lossless_gives_rgb_png_and_lossy_gives_rgb_png_with_the_decoder_samples(self):
        rgb = bytes(v for x in range(6) for v in ((x * 40) % 256, (x * 90 + 3) % 256, 255 - x))
        directory, _ = self.decode('rgb', vp8l(3, 2, b''.join(rgb[i:i + 3] + b'\xff' for i in range(0, 18, 3)), alpha=False))
        data = (directory / 'image.png').read_bytes()
        self.assertEqual(data[8 + 8 + 9], 2)
        self.assertEqual(adaptor.read_canonical_png(data)['rgba'][0::4], rgb[0::3])
        directory, result = self.decode('lossy', vp8(3, 2, rgb))
        self.assertEqual(result['dimensions'], [3, 2])
        summary = adaptor.read_json(directory, 'webp-summary.json')
        self.assertEqual(summary['source']['container'], 'RIFF WEBP simple format, one VP8 chunk')
        self.assertEqual(summary['readback']['report']['format'], 'lossy')
        self.assertEqual(summary['pixels']['opaque'], 6)
        self.assertEqual(summary['image']['format'], 'PNG 8-bit RGB, chunks IHDR IDAT IEND, filter none')
        self.assertEqual(bytes(shared_png.decode((directory / 'image.png').read_bytes())[2]), b''.join(rgb[i:i + 3] + b'\xff' for i in range(0, 18, 3)))

    def test_alpha_hint_must_agree_with_the_decoded_samples(self):
        data = vp8l(2, 1, bytes([1, 2, 3, 255, 4, 5, 6, 0]), alpha=False)
        fault = self.fault(lambda: self.decode('mismatch', data), 'WEBP_ALPHA_MISMATCH')
        self.assertIn('1 of 2', fault.message)
        self.assertEqual(adaptor.read_json(self.root / 'mismatch', 'result.json')['verified'], False)
        self.assertFalse((self.root / 'mismatch' / 'image.png').exists())
        # the hint set with every alpha 255 is legitimate and gives an RGBA PNG
        directory, _ = self.decode('flagged', vp8l(1, 1, bytes([1, 2, 3, 255]), alpha=True))
        self.assertEqual((directory / 'image.png').read_bytes()[8 + 8 + 9], 6)

    def test_upscaling_bits_leave_the_coded_size_and_the_decoded_samples_alone(self):
        rgb = bytes(v for x in range(6) for v in ((x * 40) % 256, (x * 90 + 3) % 256, 255 - x))
        plain, _ = self.decode('scale-0', vp8(3, 2, rgb))
        for name, horizontal, vertical in (('scale-1-2', 1, 2), ('scale-3-0', 3, 0), ('scale-0-3', 0, 3), ('scale-2-2', 2, 2)):
            directory, result = self.decode(name, vp8(3, 2, rgb, scale=horizontal, vscale=vertical))
            self.assertEqual(result['dimensions'], [3, 2], name)
            self.assertEqual(adaptor.read_canonical_png((directory / 'image.png').read_bytes()),
                             adaptor.read_canonical_png((plain / 'image.png').read_bytes()), name)
            self.assertEqual(adaptor.verify(directory, decoder=self.decoder)['dimensions'], [3, 2], name)

    def test_source_faults_stop_before_any_native_launch(self):
        marker = self.root / 'launched'
        decoder = program(self.root, 'dwebp-marked', marker='open(%r, "w").write("x")' % str(marker))
        sources = {'missing': (self.root / 'missing.webp', None), 'bad': (self.root / 'bad.webp', b'not a webp at all' * 4),
                   'animated': (self.root / 'animated.webp', riff(b'VP8X', bytes([0x12, 0, 0, 0, 3, 0, 0, 3, 0, 0]))),
                   'alpha': (self.root / 'alpha.webp', riff(b'VP8X', bytes([0x10, 0, 0, 0, 3, 0, 0, 3, 0, 0]))),
                   'huge': (self.root / 'huge.webp', vp8l(3000, 3000, b'')), 'trailing': (self.root / 'trailing.webp', vp8l(1, 1, b'\0' * 4) + b'EXIF')}
        expected = {'missing': 'INVALID_WEBP_SOURCE', 'bad': 'INVALID_WEBP_IMAGE', 'animated': 'WEBP_ANIMATION_UNSUPPORTED', 'alpha': 'WEBP_FORMAT_UNSUPPORTED',
                    'huge': 'WEBP_PIXEL_BUDGET', 'trailing': 'INVALID_WEBP_IMAGE'}
        for name, (path, data) in sources.items():
            if data is not None:
                path.write_bytes(data)
            self.fault(lambda: adaptor.run({**self.document, 'source': str(path)}, self.root / name, decoder=decoder), expected[name])
            self.assertEqual(adaptor.read_json(self.root / name, 'result.json')['status'], 'failed', name)
        big = self.root / 'big.webp'
        with big.open('wb') as stream:
            stream.truncate(16 * 1024 * 1024 + 1)
        self.fault(lambda: adaptor.run({**self.document, 'source': str(big)}, self.root / 'big', decoder=decoder), 'INVALID_WEBP_SOURCE')
        (self.root / 'link.webp').symlink_to(self.source)
        self.fault(lambda: adaptor.run({**self.document, 'source': str(self.root / 'link.webp')}, self.root / 'link', decoder=decoder), 'INVALID_WEBP_SOURCE')
        self.assertFalse(marker.exists())

    def test_a_well_framed_file_that_dwebp_cannot_decode_is_a_source_fault(self):
        corrupt = program(self.root, 'dwebp-corrupt', marker=CORRUPT)
        fault = self.fault(lambda: self.decode('corrupt', decoder=corrupt), 'INVALID_WEBP_IMAGE')
        self.assertIn('BITSTREAM_ERROR', fault.message)
        self.assertEqual(fault.location, '$.source')
        self.assertEqual(adaptor.read_json(self.root / 'corrupt', 'result.json')['status'], 'failed')

    def test_a_forged_capture_whose_alpha_hint_contradicts_its_pixels_fails_verification_not_the_run_fault(self):
        directory, _ = self.decode('hint')
        # A forger swaps in a coherent capture with the alpha hint cleared but the same non-opaque samples, and refreshes
        # every hash, so verification reaches the decoded-pixel check; the run fault code must not leak out of verify.
        cleared = vp8l(4, 3, LITERAL_BYTES, alpha=False)
        (directory / 'captured.webp').write_bytes(cleared)
        refresh(directory)
        fault = self.fault(lambda: adaptor.verify(directory, decoder=self.decoder), 'VERIFICATION_FAILED')
        self.assertIn('alpha hint', fault.message)
        self.assertEqual(fault.location, 'captured.webp')
        cause = fault.to_dict()['observed']['cause']
        self.assertEqual((cause['code'], cause['observed']), ('WEBP_ALPHA_MISMATCH', {'alphaFlag': False}))
        # the same file given to a run keeps the run fault code
        self.fault(lambda: self.decode('hint-run', cleared), 'WEBP_ALPHA_MISMATCH')

    def test_a_decoder_report_or_pixels_that_contradict_the_framing_are_refused(self):
        lies = {'dimensions': 'width = width + 1; pixels = pixels + bytes(4 * height)', 'format': 'fmt = "lossy"', 'alpha': 'alpha = False',
                'short payload': 'pixels = pixels[:-4]', 'long payload': 'pixels = pixels + bytes(4)',
                'height': 'height = 2; pixels = pixels[:32]'}
        for name, marker in lies.items():
            decoder = program(self.root, 'dwebp-' + name.replace(' ', ''), marker=marker)
            self.fault(lambda: self.decode('lie-' + name.replace(' ', ''), decoder=decoder), 'VERIFICATION_FAILED')
        garbage = program(self.root, 'dwebp-garbage', marker='open(args[4], "wb").write(b"P6\\n"); sys.exit(0)')
        self.fault(lambda: self.decode('garbage', decoder=garbage), 'VERIFICATION_FAILED')

    def test_tampering_is_refused_even_when_every_ordinary_hash_is_refreshed(self):
        directory, _ = self.decode('forged')
        original = {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}

        def restore():
            for path in directory.iterdir():
                if path.name not in original and path.is_file():
                    path.unlink()
            for name, data in original.items():
                (directory / name).write_bytes(data)

        changed = bytearray(LITERAL_BYTES)
        changed[4 * 6] ^= 1                                                              # one hidden-RGB sample under alpha 0
        replacements = {
            'one hidden RGB sample': adaptor.encode_png(4, 3, bytes(changed), True),
            'dropped alpha': adaptor.encode_png(4, 3, LITERAL_BYTES, False),
            'extra text chunk': raw_png(4, 3, literal_rows(), extra=[(b'tEXt', b'Comment\0forged')]),
            'filtered rows': raw_png(4, 3, literal_rows(1)),
            'trailing byte': adaptor.encode_png(4, 3, LITERAL_BYTES, True) + b'\0',
            'other size': adaptor.encode_png(2, 6, LITERAL_BYTES, True),
            'truncated': adaptor.encode_png(4, 3, LITERAL_BYTES, True)[:-20],
            'empty': b'',
        }
        for name, data in replacements.items():
            restore()
            (directory / 'image.png').write_bytes(data)
            self.reject_after_refresh(directory)
        restore()
        # a different valid captured WebP whose samples no longer match the PNG
        self.source_replacement = vp8l(4, 3, bytes(changed))
        (directory / 'captured.webp').write_bytes(self.source_replacement)
        self.reject_after_refresh(directory, 'retained run readback')
        (directory / 'decoded.pam').write_bytes(adaptor.pam(4, 3, bytes(changed)))    # the forger rewrites the readback too
        self.reject_after_refresh(directory, 'published PNG does not equal')
        restore()
        # the retained decode, summary, plan and authored input cannot be edited either
        (directory / 'decoded.pam').write_bytes((directory / 'decoded.pam').read_bytes()[:-1] + b'\1')
        self.reject_after_refresh(directory, 'retained run readback')
        restore()
        summary = json.loads((directory / 'webp-summary.json').read_text())
        summary['pixels']['transparentWithRgb'] = 0
        atomic_json(directory / 'webp-summary.json', summary)
        self.reject_after_refresh(directory, 'summary')
        restore()
        atomic_json(directory / 'plan.json', {**json.loads((directory / 'plan.json').read_text()), 'losses': []})
        self.reject_after_refresh(directory, 'plan')
        restore()
        # a swap to another operation's evidence names is a membership fault
        receipt = adaptor.read_json(directory, 'verification.json')
        receipt['evidence']['image.webp'] = '0' * 64
        atomic_json(directory / 'verification.json', receipt)
        self.fault(lambda: adaptor.verify(directory, decoder=self.decoder), 'VERIFICATION_FAILED')
        restore()
        self.assertTrue(adaptor.verify(directory, decoder=self.decoder)['verified'])

    def test_retained_json_is_strict_typed_and_closed(self):
        directory, _ = self.decode('json')
        names = ('webp-summary.json', 'result.json', 'captures.json', 'decode-inputs.json', 'verification.json')
        original = {n: (directory / n).read_text() for n in names}
        edits = {
            'duplicate key': lambda t: t.replace('{', '{"status": "succeeded", ', 1),
            'NaN': lambda t: t.replace('"verified": true', '"verified": NaN'),
            'overflow': lambda t: t.replace('"artifacts": 2', '"artifacts": 1e400'),
            'bool as int': lambda t: t.replace('"verified": true', '"verified": 1'),
            'int as float': lambda t: t.replace('"artifacts": 2', '"artifacts": 2.0'),
            'extra claim': lambda t: t.replace('"verified": true', '"verified": true, "lossless": true'),
            'promoted': lambda t: t.replace('"verified": true', '"verified": true, "perceptual": true'),
            'dropped claim': lambda t: t.replace('"sourceBytes"', '"sourceBytesX"'),
            'wrong operation': lambda t: t.replace('"decodeToPng"', '"encodeLossless"'),
        }
        for edit_name, edit in edits.items():
            (directory / 'result.json').write_text(edit(original['result.json']))
            fault = self.fault(lambda: adaptor.verify(directory, decoder=self.decoder), 'VERIFICATION_FAILED')
            self.assertTrue(fault.message, edit_name)
            (directory / 'result.json').write_text(original['result.json'])
        (directory / 'webp-summary.json').write_text(original['webp-summary.json'].replace('{', '{"version": "x", ', 1))
        refresh(directory)
        self.fault(lambda: adaptor.verify(directory, decoder=self.decoder), 'VERIFICATION_FAILED')
        (directory / 'webp-summary.json').write_text(original['webp-summary.json'].replace('"exactRgba": true', '"exactRgba": 1'))
        refresh(directory)
        self.fault(lambda: adaptor.verify(directory, decoder=self.decoder), 'VERIFICATION_FAILED')
        (directory / 'webp-summary.json').write_text('﻿' + original['webp-summary.json'])
        refresh(directory)
        self.fault(lambda: adaptor.verify(directory, decoder=self.decoder), 'VERIFICATION_FAILED')

    def test_verification_never_rereads_the_external_source_and_survives_its_removal(self):
        directory, _ = self.decode('captured')
        self.source.write_bytes(vp8l(1, 1, b'\x09' * 4))
        self.assertTrue(adaptor.verify(directory, decoder=self.decoder)['verified'])
        self.source.unlink()
        self.assertTrue(adaptor.verify(directory, decoder=self.decoder)['verified'])
        read = []
        real = adaptor.bounded
        with mock.patch.object(adaptor, 'bounded', side_effect=lambda path, *a, **k: (read.append(str(path)), real(path, *a, **k))[1]):
            adaptor.verify(directory, decoder=self.decoder)
        self.assertNotIn(str(self.source), read)
        self.assertTrue(all(p.startswith(str(directory)) or 'schemaxis-webp-' in p for p in read), read)   # run files or the private decode copy
        self.assertEqual((directory / 'captured.webp').read_bytes()[:4], b'RIFF')

    def test_verification_needs_the_trusted_decoder_and_never_runs_a_receipt_or_path_program(self):
        directory, _ = self.decode('trusted')
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
        receipt['executables'] = {'decoder': str(shim / 'dwebp')}
        atomic_json(forged / 'verification.json', receipt)
        with self.private(), mock.patch.dict(os.environ, {'PATH': str(shim) + os.pathsep + os.environ.get('PATH', '')}):
            self.fault(lambda: adaptor.verify(directory), 'INTERPRETER_NOT_FOUND')
            self.fault(lambda: adaptor.verify(directory, decoder=str(shim / 'missing-dwebp')), 'INTERPRETER_NOT_FOUND')
            self.fault(lambda: adaptor.verify(directory, decoder='relative-dwebp'), 'INTERPRETER_NOT_FOUND')
            self.fault(lambda: adaptor.run(self.document, self.root / 'nodecoder'), 'INTERPRETER_NOT_FOUND')
            self.fault(lambda: adaptor.verify(forged, decoder=self.decoder), 'VERIFICATION_FAILED')
        self.assertFalse(sentinel.exists())
        with self.private({'dwebp': self.decoder}):
            self.assertTrue(adaptor.verify(directory)['verified'])
            self.assertTrue(adaptor.run(self.document, self.root / 'configured', timeout=60)['verified'])
        with self.private(), mock.patch.dict(os.environ, {'SCHEMAXIS_DWEBP': self.decoder}):
            self.assertTrue(adaptor.verify(directory)['verified'])

    def test_unsupported_runtime_and_failed_version_probe_stop_before_decoding(self):
        marker = self.root / 'decoded-anything'
        old = program(self.root, 'dwebp-old', version='1.2.4', marker='open(%r, "w").write("x")' % str(marker))
        self.fault(lambda: self.decode('old', decoder=old), 'UNSUPPORTED_RUNTIME')
        self.assertFalse(marker.exists())
        failing = program(self.root, 'dwebp-fail', marker='sys.stderr.write("Error! bad\\n"); sys.exit(3)')
        self.fault(lambda: self.decode('fail', decoder=failing), 'INVALID_WEBP_IMAGE')
        directory, _ = self.decode('current')
        self.fault(lambda: adaptor.verify(directory, decoder=old), 'UNSUPPORTED_RUNTIME')
        self.fault(lambda: adaptor.verify(directory, decoder=failing), 'VERIFICATION_FAILED')

    def test_timeout_and_cancellation_end_the_owned_process_and_leave_a_failed_run(self):
        marker = self.root / 'slow.pid'
        slow = program(self.root, 'dwebp-slow', marker='import os, time; open(%r, "w").write(str(os.getpid())); time.sleep(30)' % str(marker))
        started = time.monotonic()
        self.fault(lambda: adaptor.run(self.document, self.root / 'slow', decoder=slow, timeout=2), 'RUNNER_TIMED_OUT')
        self.assertLess(time.monotonic() - started, 20)
        pid = int(marker.read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        result = adaptor.read_json(self.root / 'slow', 'result.json')
        self.assertEqual((result['status'], result['verified']), ('failed', False))
        self.fault(lambda: adaptor.run(self.document, self.root / 'slow', decoder=self.decoder), 'OUTPUT_EXISTS')
        self.fault(lambda: adaptor.run(self.document, self.root / 'badtimeout', decoder=self.decoder, timeout=float('nan')), 'INVALID_ARGUMENT')
        marker.unlink()
        cancel = threading.Event()

        def trigger():
            end = time.monotonic() + 8
            while not marker.exists() and time.monotonic() < end:
                time.sleep(.01)
            cancel.set()
        thread = threading.Thread(target=trigger, daemon=True)
        thread.start()
        with allocation({'threads': 1, 'ranks': 1}, cancel):
            self.fault(lambda: adaptor.run(self.document, self.root / 'cancelled', decoder=slow, timeout=20), 'RUNNER_CANCELLED')
        thread.join(10)
        with self.assertRaises(ProcessLookupError):
            os.kill(int(marker.read_text()), 0)
        directory, _ = self.decode('verified')
        with mock.patch.object(adaptor, 'VERIFY_TIMEOUT', 1):
            self.fault(lambda: adaptor.verify(directory, decoder=slow), 'RUNNER_TIMED_OUT')
        cancelled = threading.Event()
        cancelled.set()
        with allocation({'threads': 1, 'ranks': 1}, cancelled):
            self.fault(lambda: adaptor.verify(directory, decoder=slow), 'RUNNER_CANCELLED')

    def test_workflow_reuse_hook_follows_the_captured_webp_bytes_and_refuses_unusable_sources(self):
        before = adaptor.reusableInputs(self.document)
        self.assertEqual(before, {str(self.source): hashlib.sha256(self.source.read_bytes()).hexdigest()})
        self.source.write_bytes(vp8l(1, 1, b'\1\2\3\4'))
        self.assertNotEqual(before, adaptor.reusableInputs(self.document))
        self.source.write_bytes(b'garbage' * 8)
        self.fault(lambda: adaptor.reusableInputs(self.document), 'INVALID_WEBP_IMAGE')
        self.source.unlink()
        self.fault(lambda: adaptor.reusableInputs(self.document), 'INVALID_WEBP_SOURCE')

    def test_the_existing_png_operations_keep_their_fault_for_a_webp_source(self):
        png_document = {'version': 'schemaxis.webp/1', 'operation': 'encodeLossless', 'source': str(self.source)}
        self.fault(lambda: adaptor.run(png_document, self.root / 'wrong', executable=self.decoder, decoder=self.decoder), 'INVALID_WEBP_SOURCE')

    @unittest.skipUnless(os.environ.get('SCHEMAXIS_DWEBP'), 'needs real libwebp 1.6 dwebp')
    def test_real_dwebp_decodes_the_committed_libwebp_fixtures(self):
        expected = {'decode-literal-rgba': (4, 3, LITERAL_BYTES)}
        for name in ('decode-literal-rgba', 'decode-swatch-rgb', 'decode-gradient-lossy'):
            document = {**self.document, 'source': str(FIXTURES / (name + '.webp'))}
            directory = self.root / ('real-' + name)
            result = adaptor.run(document, directory, decoder=os.environ['SCHEMAXIS_DWEBP'])
            self.assertTrue(result['verified'], name)
            if name in expected:
                width, height, samples = shared_png.decode((directory / 'image.png').read_bytes())
                self.assertEqual((width, height, bytes(samples)), expected[name], name)
            direct = subprocess.run([os.environ['SCHEMAXIS_DWEBP'], str(FIXTURES / (name + '.webp')), '-pam', '-o', str(self.root / (name + '.pam'))],
                                    capture_output=True, timeout=60)
            self.assertEqual(direct.returncode, 0)
            self.assertEqual(adaptor.read_pam((self.root / (name + '.pam')).read_bytes())[2], adaptor.read_canonical_png((directory / 'image.png').read_bytes())['rgba'], name)


if __name__ == '__main__':
    unittest.main()
