"""Lossless WebP contract: planning, PNG admission, strict readers, discovery and guidance (host only)."""
import contextlib
import copy
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import zlib

from schemaxis.adaptors import registry
from schemaxis.adaptors.webp import adaptor
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'examples/schemaxis/fixtures/webp'


@contextlib.contextmanager
def private_configuration(locations=None):
    """A private SCHEMAXIS_CONFIG with cleared SCHEMAXIS_WEBP/DWEBP.

    ``location_context({'dwebp': None})`` drops None values and so does not clear stored settings: a machine with a
    stored decoder would otherwise leak into these tests.
    """
    with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ):
        path = Path(tmp) / 'private-config.json'
        path.write_text(json.dumps({'version': 1, 'locations': locations or {}}))
        os.environ['SCHEMAXIS_CONFIG'] = str(path)
        os.environ.pop('SCHEMAXIS_WEBP', None)
        os.environ.pop('SCHEMAXIS_DWEBP', None)
        yield


def chunk(kind, value):
    return struct.pack('>I', len(value)) + kind + value + struct.pack('>I', zlib.crc32(kind + value) & 0xffffffff)


def image(raw=b'\0' + bytes(8), width=2, height=1, depth=8, colour=6, interlace=0, extra=b''):
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, depth, colour, 0, 0, interlace))
            + extra + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def vp8l(width, height, alpha=True, payload=b'', version=0):
    bits = (width - 1) | ((height - 1) << 14) | (int(alpha) << 28) | (version << 29)
    body = b'\x2f' + struct.pack('<I', bits) + payload
    size = len(body)
    body += b'\0' * (size & 1)
    return b'RIFF' + struct.pack('<I', 12 + len(body)) + b'WEBPVP8L' + struct.pack('<I', size) + body


class WebpContract(unittest.TestCase):
    def document(self, name='baseline'):
        return json.loads((ROOT / f'examples/schemaxis/webp-{name}.json').read_text())

    def fault(self, action, code):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    def test_registered_with_both_native_options_and_no_framework_branch(self):
        item = registry.ADAPTORS['webp']
        self.assertEqual(item['routes']['schemaxis.webp/1']['runOptions'], {'decoder': 'dwebp'})
        self.assertEqual({o['dest'] for o in item['cliOptions']}, {'webp', 'dwebp'})
        self.assertEqual(item['executables'], ['cwebp'])
        self.assertEqual(registry.query(self.document())['adaptors'][0]['operations'], ['encodeLossless'])

    def test_host_contract_guidance_and_curated_search(self):
        from schemaxis.adaptor_conformance import host
        from schemaxis.capabilities import CapabilityCatalogue
        from schemaxis.search_acceptance import check_cases
        from schemaxis.studio_guidance import audit
        self.assertTrue(host(adaptor.VERSION)['verified'])
        self.assertTrue(audit('webp')['complete'])
        self.assertTrue(check_cases(CapabilityCatalogue(providers=['webp']), 'webp')['complete'])

    def test_planning_is_immutable_deterministic_and_closed(self):
        document = self.document()
        before = copy.deepcopy(document)
        prepared = adaptor.plan(document)
        self.assertEqual(before, document)
        self.assertEqual(prepared, adaptor.plan(document))
        self.assertEqual(prepared['encoding']['arguments'], ['-lossless', '-exact', '-z', '6'])
        for key in ('quality', 'lossless', 'resize', 'metadata', 'command', 'flags', 'animation'):
            bad = copy.deepcopy(document)
            bad[key] = 1
            self.fault(lambda: adaptor.plan(bad), 'UNKNOWN_ARGUMENT')
        bad = copy.deepcopy(document)
        bad['operation'] = 'encodeNearLossless'
        self.assertEqual(self.fault(lambda: adaptor.plan(bad), 'UNKNOWN_FILTER').location, '$.operation')
        for source in ('relative.png', 'https://example.org/a.png', 'PNG:/tmp/a.png', '/tmp/a.jpg', '/tmp/a.webp', '/tmp/a\0.png'):
            bad = copy.deepcopy(document)
            bad['source'] = source
            self.assertEqual(self.fault(lambda: adaptor.plan(bad), 'INVALID_WEBP_SOURCE').location, '$.source')
        self.assertEqual(self.fault(lambda: adaptor.plan(self.document('invalid-source')), 'INVALID_WEBP_SOURCE').location, '$.source')
        self.fault(lambda: adaptor.resources(document, {'threads': 2}, 'op'), 'INVALID_EXECUTION')

    def test_png_admission_accepts_the_documented_subset(self):
        rgba = adaptor.admit_png((FIXTURES / 'swatch-rgba.png').read_bytes())
        self.assertEqual((rgba['width'], rgba['height'], len(rgba['rgba'])), (7, 5, 140))
        self.assertEqual(rgba['colourDeclaration'], 'sRGB')
        self.assertEqual(rgba['droppedChunks'], ['tEXt'])
        self.assertEqual(rgba['rgba'][4 * 14:4 * 14 + 4], bytes([17, 33, 65, 0]))   # hidden RGB under alpha 0 is kept
        rgb = adaptor.admit_png((FIXTURES / 'swatch-rgb.png').read_bytes())
        self.assertEqual((rgb['width'], rgb['height']), (5, 3))
        self.assertEqual(rgb['rgba'][:8], bytes([255, 0, 0, 255, 0, 255, 0, 255]))
        self.assertEqual(rgb['colourDeclaration'], 'untagged (treated as sRGB)')
        self.assertEqual(adaptor.admit_png(image(extra=chunk(b'gAMA', struct.pack('>I', 45455)) + chunk(b'sRGB', b'\0')))['colourDeclaration'], 'gAMA+sRGB')

    def test_png_refusals_are_distinct_and_located(self):
        good = image()
        for bad in (good[:-1], good + b'x', good.replace(b'IDAT', b'JUNK'), image(b'\5' + bytes(8)), image(depth=16), image(colour=3),
                    image(interlace=1), image(extra=chunk(b'tRNS', bytes(6)), colour=2, raw=b'\0' + bytes(6)), b'not a png' * 8):
            fault = self.fault(lambda: adaptor.admit_png(bad), 'INVALID_WEBP_PNG')
            self.assertEqual(fault.location, '$.source')
        for bad in (image(extra=chunk(b'iCCP', b'p\0\0' + zlib.compress(b'x'))), image(extra=chunk(b'cICP', bytes(4))),
                    image(extra=chunk(b'gAMA', struct.pack('>I', 100000))), image(extra=chunk(b'cHRM', bytes(32)))):
            self.fault(lambda: adaptor.admit_png(bad), 'WEBP_COLOUR_UNSUPPORTED')
        self.fault(lambda: adaptor.admit_png(image(extra=chunk(b'acTL', bytes(8)))), 'WEBP_ANIMATION_UNSUPPORTED')
        # The pixel budget is judged from IHDR before any decompression.
        huge = image(width=4096, height=4096)
        self.fault(lambda: adaptor.admit_png(huge), 'WEBP_PIXEL_BUDGET')
        self.fault(lambda: adaptor.admit_png(image(width=2049, height=1)), 'WEBP_PIXEL_BUDGET')
        self.fault(lambda: adaptor.admit_png(image(width=1025, height=1025)), 'WEBP_PIXEL_BUDGET')

    def test_pam_reader_is_strict_and_canonical(self):
        pixels = bytes(range(24))
        canonical = adaptor.pam(3, 2, pixels)
        self.assertEqual(adaptor.read_pam(canonical), (3, 2, pixels))
        for bad in (canonical[:-1], canonical + b'\0', canonical.replace(b'RGB_ALPHA', b'RGB'), canonical.replace(b'DEPTH 4', b'DEPTH 3'),
                    canonical.replace(b'WIDTH 3', b'WIDTH 03'), canonical.replace(b'P7\n', b'P7\n# comment\n'), canonical.replace(b'WIDTH 3', b'WIDTH 4'),
                    adaptor.pam(2049, 1, bytes(4 * 2049)), adaptor.pam(1025, 1025, bytes(4 * 1025 * 1025)), b''):
            self.fault(lambda: adaptor.read_pam(bad), 'VERIFICATION_FAILED')

    def test_webp_framing_accepts_only_one_simple_lossless_chunk(self):
        good = vp8l(7, 5, payload=b'abc')
        self.assertEqual(adaptor.webp_header(good), {'width': 7, 'height': 5, 'alphaFlag': True})
        self.assertFalse(adaptor.webp_header(vp8l(5, 3, alpha=False, payload=b'ab'))['alphaFlag'])
        self.assertEqual(adaptor.webp_header(vp8l(2048, 512))['width'], 2048)
        extra = chunk_riff(b'EXIF', b'x')
        odd = vp8l(7, 5, payload=b'ab')
        self.assertEqual(adaptor.webp_header(odd)['width'], 7)
        for bad in (good[:-1], good + b'\0', good.replace(b'VP8L', b'VP8 '), good.replace(b'VP8L', b'VP8X'), good.replace(b'WEBP', b'WEBQ'),
                    good[:4] + struct.pack('<I', 99) + good[8:], good[:12] + b'VP8L' + struct.pack('<I', 5) + good[20:],
                    riff_with(good, extra), vp8l(7, 5, version=1), vp8l(2049, 1), vp8l(1025, 1025), b'RIFF', b'',
                    odd[:-1] + b'\x01'):
            self.fault(lambda: adaptor.webp_header(bad), 'VERIFICATION_FAILED')

    def test_sources_are_regular_bounded_and_byte_current(self):
        import os
        import tempfile
        document = self.document()
        data = (FIXTURES / 'swatch-rgba.png').read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'a.png'
            path.write_bytes(data)
            document['source'] = str(path)
            first = adaptor.reusableInputs(document)
            path.write_bytes((FIXTURES / 'swatch-rgba-changed.png').read_bytes())
            self.assertNotEqual(first, adaptor.reusableInputs(document))
            link = Path(tmp) / 'link.png'
            link.symlink_to(path)
            self.fault(lambda: adaptor.bounded(link, 'INVALID_WEBP_SOURCE'), 'INVALID_WEBP_SOURCE')
            if hasattr(os, 'mkfifo'):
                fifo = Path(tmp) / 'fifo.png'
                os.mkfifo(fifo)
                self.fault(lambda: adaptor.bounded(fifo, 'INVALID_WEBP_SOURCE'), 'INVALID_WEBP_SOURCE')
            path.write_bytes(b'x' * (adaptor.MAX_SOURCE_BYTES + 1))
            self.fault(lambda: adaptor.reusableInputs(document), 'INVALID_WEBP_SOURCE')
            path.write_bytes(image(width=3000, height=3000))
            self.fault(lambda: adaptor.reusableInputs(document), 'WEBP_PIXEL_BUDGET')

    def test_runtime_never_comes_from_receipts_or_relative_paths(self):
        with private_configuration():
            fault = self.fault(lambda: adaptor.runtime(decoder=None, need_encoder=False), 'INTERPRETER_NOT_FOUND')
            self.assertIn('no host WebP decoder', fault.message)
            self.fault(lambda: adaptor.runtime('cwebp', '/bin/true'), 'INTERPRETER_NOT_FOUND')

    def test_stored_decoder_location_and_environment_are_the_only_verify_routes(self):
        with private_configuration({'dwebp': '/bin/true'}):
            self.assertEqual(adaptor.runtime(need_encoder=False), {'decoder': '/bin/true'})
        with private_configuration():
            with mock.patch.dict(os.environ, {'SCHEMAXIS_DWEBP': '/bin/true'}):
                self.assertEqual(adaptor.runtime(need_encoder=False), {'decoder': '/bin/true'})
        with private_configuration():
            fault = self.fault(lambda: adaptor.runtime(need_encoder=False), 'INTERPRETER_NOT_FOUND')
            self.assertEqual(fault.location, '$.runtime.decoder')
            recovery = fault.observed['recovery']
            self.assertIn('SCHEMAXIS_DWEBP', recovery)
            self.assertIn('locations.dwebp', recovery)
            self.assertIn('for run', recovery)
            self.assertNotIn('run and inspect', recovery)
            self.assertNotIn('also for verify', recovery)

    def test_help_readiness_and_docs_do_not_claim_dwebp_flag_reaches_bare_verify(self):
        item = registry.ADAPTORS['webp']
        help_text = {o['dest']: o['help'] for o in item['cliOptions']}
        self.assertIn('for run', help_text['dwebp'])
        self.assertNotIn('run and inspect', help_text['dwebp'])
        self.assertIn('SCHEMAXIS_DWEBP', help_text['dwebp'])
        self.assertNotIn('fresh decode for WebP run and verification', help_text['dwebp'])
        route = json.loads((ROOT / 'src/schemaxis/adaptors/webp/readiness.json').read_text())
        recovery = json.dumps(route)
        self.assertNotIn('also for verify', recovery)
        self.assertIn('SCHEMAXIS_DWEBP', recovery)
        docs = (ROOT / 'docs/webp.md').read_text()
        self.assertIn('SCHEMAXIS_DWEBP=/path/to/dwebp schemaxis verify output/webp', docs)
        self.assertNotIn('my probes', (ROOT / 'verification/2026-10-25-webp-40.md').read_text())

    def test_retained_json_is_read_strictly(self):
        good = b'{"a": [1, 2.5, true, null, "x"]}'
        self.assertEqual(adaptor.strict_json(good, 'x.json'), {'a': [1, 2.5, True, None, 'x']})
        deep = b'[' * 100000 + b']' * 100000
        for label, bad in (('duplicate', b'{"a": 1, "a": 2}'), ('nested duplicate', b'{"a": {"b": 1, "b": 1}}'), ('NaN', b'{"a": NaN}'),
                           ('Infinity', b'{"a": Infinity}'), ('-Infinity', b'{"a": -Infinity}'), ('overflow', b'{"a": 1e400}'),
                           ('negative overflow', b'{"a": -1e400}'), ('byte-order mark', b'\xef\xbb\xbf' + good),
                           ('UTF-16', good.decode().encode('utf-16')), ('invalid UTF-8', b'{"a": "\xff"}'), ('deep', deep), ('truncated', b'{"a":')):
            fault = self.fault(lambda: adaptor.strict_json(bad, 'x.json'), 'VERIFICATION_FAILED')
            self.assertIn('x.json', fault.message, label)

    def test_typed_comparison_does_not_collapse_booleans_numbers_or_member_order(self):
        self.assertTrue(adaptor.same_json({'b': 1, 'a': [True, 66]}, {'a': [True, 66], 'b': 1}))
        for actual, expected in ((1, True), (True, 1), (66.0, 66), (66, 66.0), (0, False), (0.0, 0), ([1], [True]), ({'a': 1}, {'a': 1.0}),
                                 ({'a': 1}, {'a': 1, 'b': 2}), ('1', 1), (float('nan'), float('nan')), (float('inf'), float('inf')), (None, 0)):
            self.assertFalse(adaptor.same_json(actual, expected), (actual, expected))
        nest = []
        for _ in range(100000):
            nest = [nest]
        self.assertFalse(adaptor.same_json(nest, nest))    # excess depth is a refusal, not a crash

    def test_identity_probes_pin_libwebp_1_6(self):
        self.assertEqual(adaptor.check_identity('encoder-version', '1.6.0\nlibsharpyuv: 0.4.2\n'), '1.6.0\nlibsharpyuv: 0.4.2')
        self.assertEqual(adaptor.check_identity('decoder-version', '1.6.3\n'), '1.6.3')
        for stage, text in (('encoder-version', '1.7.0\nlibsharpyuv: 0.4.2\n'), ('encoder-version', '1.6.0\n'), ('decoder-version', '1.5.0\n'),
                            ('decoder-version', 'WebP Decoder version: 1.6.0\n'), ('decoder-version', '')):
            self.fault(lambda: adaptor.check_identity(stage, text), 'UNSUPPORTED_RUNTIME')


def chunk_riff(kind, value):
    return kind + struct.pack('<I', len(value)) + value + b'\0' * (len(value) & 1)


def riff_with(webp, extra):
    body = webp[8:] + extra
    return b'RIFF' + struct.pack('<I', len(body)) + body


if __name__ == '__main__':
    unittest.main()
