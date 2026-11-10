"""Malformed versus unsupported PNG sources: distinct stable faults with recovery."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from schemaxis.adaptors import registry
from schemaxis.adaptors.imagemagick import adaptor, png
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
PIXEL = bytes([10, 20, 30, 40])


def chunk(kind, value):
    return struct.pack('>I', len(value)) + kind + value + struct.pack('>I', zlib.crc32(kind + value) & 0xffffffff)


def image(raw=b'\0' + PIXEL, width=1, height=1, depth=8, colour=6, interlace=0, extra=b'', after=b'', compression=0):
    header = struct.pack('>IIBBBBB', width, height, depth, colour, compression, 0, interlace)
    return png.SIGNATURE + chunk(b'IHDR', header) + extra + chunk(b'IDAT', zlib.compress(raw)) + after + chunk(b'IEND', b'')


class PngSourceTaxonomy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pending = ROOT / 'src/schemaxis/adaptors/imagemagick/adaptor.json.pending'
        cls.registration = patch.dict(registry.ADAPTORS, {'imagemagick': json.loads(pending.read_text())} if pending.exists() else {})
        cls.registration.start()

    @classmethod
    def tearDownClass(cls):
        cls.registration.stop()

    def fault(self, data, code, output=False):
        with self.assertRaises(SchemaxisError) as caught:
            png.decode(data, output=output)
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    # Well-formed files that are legitimately outside the supported subset.
    UNSUPPORTED = {
        'palette': lambda: image(b'\0\0', colour=3),
        'greyscale': lambda: image(b'\0\x10', colour=0),
        'greyscale-alpha': lambda: image(b'\0\x10\x20', colour=4),
        'sixteen-bit-rgba': lambda: image(b'\0' + bytes(8), depth=16),
        'interlaced': lambda: image(interlace=1),
        'icc-profile': lambda: image(extra=chunk(b'iCCP', b'ICC\0\0bad')),
        'animation': lambda: image(extra=chunk(b'acTL', bytes(8))),
        'compressed-text': lambda: image(extra=chunk(b'zTXt', b'bad')),
        'transparency-key': lambda: image(b'\0' + bytes([1, 2, 3]), colour=2, extra=chunk(b'tRNS', bytes(6))),
        'international-text': lambda: image(extra=chunk(b'iTXt', b'k\0\0\0\0\0v')),
        'nonstandard-gamma': lambda: image(extra=chunk(b'gAMA', struct.pack('>I', 100000))),
        'lone-gamma': lambda: image(extra=chunk(b'gAMA', struct.pack('>I', 45455))),
        'nonstandard-chromaticities': lambda: image(extra=chunk(b'cHRM', struct.pack('>8I', *[1] * 8))),
        'oversize-dimensions': lambda: image(b'', width=4096, height=4096),
        'oversize-text': lambda: image(extra=chunk(b'tEXt', b'k\0' + bytes(65536))),
    }

    # Corrupt or structurally invalid files.
    MALFORMED = {
        'truncated': lambda: image()[:-1],
        'trailing-bytes': lambda: image() + b'x',
        'bad-crc': lambda: image().replace(b'IDAT', b'IDAU'),
        'missing-iend': lambda: image()[:-12],
        'not-png': lambda: b'GIF89a' + bytes(40),
        'short-pixels': lambda: image(b'\0' + bytes(3)),
        'unknown-filter': lambda: image(b'\5' + PIXEL),
        'bad-sample-depth-combination': lambda: image(depth=4, colour=2),
        'bad-compression-method': lambda: image(compression=1),
        'zero-width': lambda: image(width=0),
        'bad-srgb-intent': lambda: image(extra=chunk(b'sRGB', b'\4')),
        'bad-srgb-length': lambda: image(extra=chunk(b'sRGB', b'\0\0')),
        'duplicate-srgb': lambda: image(extra=chunk(b'sRGB', b'\0') * 2),
        'text-without-separator': lambda: image(extra=chunk(b'tEXt', b'keyonly')),
        'invalid-chunk-name': lambda: image(extra=chunk(b'ab1d', b'')),
        'srgb-after-data': lambda: image(after=chunk(b'sRGB', b'\0')),
    }

    def test_unsupported_but_well_formed_png_has_its_own_stable_fault(self):
        for name, build in self.UNSUPPORTED.items():
            with self.subTest(name):
                fault = self.fault(build(), 'UNSUPPORTED_RASTER_PNG')
                self.assertEqual(fault.observed['category'], 'unsupported')
                self.assertTrue(fault.observed['feature'])
                self.assertTrue(fault.observed['reason'])
                self.assertIn('RGB', fault.recovery)
                self.assertFalse(fault.retryable)

    def test_malformed_png_keeps_invalid_fault_and_says_how_to_recover(self):
        for name, build in self.MALFORMED.items():
            with self.subTest(name):
                fault = self.fault(build(), 'INVALID_RASTER_PNG')
                self.assertEqual(fault.observed['category'], 'malformed')
                self.assertTrue(fault.observed['reason'])
                self.assertIn('corrupt', fault.recovery)

    def test_corruption_after_an_unsupported_feature_is_still_malformed(self):
        # Unsupported is only claimed for a completely well-formed chunk structure.
        data = image(extra=chunk(b'iCCP', b'ICC\0\0bad'))
        self.fault(data[:-1], 'INVALID_RASTER_PNG')
        self.fault(data + b'x', 'INVALID_RASTER_PNG')
        bad_crc = data.replace(b'IDAT', b'IDAU')
        self.fault(bad_crc, 'INVALID_RASTER_PNG')

    def test_published_output_checks_never_use_source_codes(self):
        for name, build in {**self.UNSUPPORTED, **self.MALFORMED}.items():
            with self.subTest(name):
                self.fault(build(), 'VERIFICATION_FAILED', output=True)
        self.fault(image(extra=chunk(b'sRGB', b'\0')), 'VERIFICATION_FAILED', output=True)

    def test_acceptance_set_is_unchanged(self):
        accepted = {
            'rgba': (image(), 'untagged: authored assume-srgb'),
            'rgb': (image(b'\0\x01\x02\x03', colour=2), 'untagged: authored assume-srgb'),
            'srgb': (image(extra=chunk(b'sRGB', b'\1')), 'sRGB chunk'),
            'gamma+chroma': (image(extra=chunk(b'gAMA', struct.pack('>I', 45455)) + chunk(b'cHRM', struct.pack('>8I', *png.CHROMATICITIES))), 'standard sRGB gAMA+cHRM'),
            'physical+text+time': (image(extra=chunk(b'pHYs', struct.pack('>IIB', 1, 1, 1)) + chunk(b'tEXt', b'k\0v') + chunk(b'tIME', bytes(7))), 'untagged: authored assume-srgb'),
            'text-after-data': (image(after=chunk(b'tEXt', b'k\0v')), 'untagged: authored assume-srgb'),
        }
        for name, (data, colour) in accepted.items():
            with self.subTest(name):
                self.assertEqual(png.decode(data)[3], colour)
        self.assertEqual(png.decode(image())[2], PIXEL)
        for fixture in sorted((ROOT / 'examples/schemaxis/fixtures/imagemagick').glob('*.png')):
            with self.subTest(fixture.name):
                self.assertEqual(png.decode(fixture.read_bytes())[3], 'sRGB chunk')

    def test_source_faults_name_the_authored_image_and_flow_through_the_adaptor(self):
        document = json.loads((ROOT / 'examples/schemaxis/imagemagick-sheet.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            good = ROOT / 'examples/schemaxis/fixtures/imagemagick/grid.png'
            bad = Path(tmp) / 'palette.png'
            bad.write_bytes(self.UNSUPPORTED['palette']())
            document['images'][0]['source'] = str(good)
            document['images'][1]['source'] = str(bad)
            with self.assertRaises(SchemaxisError) as caught:
                adaptor.reusableInputs(document)
            fault = caught.exception.fault
            self.assertEqual((fault.code, fault.location), ('UNSUPPORTED_RASTER_PNG', '$.images[1].source'))
            bad.write_bytes(self.MALFORMED['truncated']())
            with self.assertRaises(SchemaxisError) as caught:
                adaptor.reusableInputs(document)
            fault = caught.exception.fault
            self.assertEqual((fault.code, fault.location), ('INVALID_RASTER_PNG', '$.images[1].source'))
            # A failed run records the structured fault and publishes nothing.
            out = Path(tmp) / 'run'
            with self.assertRaises(SchemaxisError):
                adaptor.run(document, out, executable='/bin/true')
            result = json.loads((out / 'result.json').read_text())
            self.assertEqual(result['status'], 'failed')
            self.assertFalse(result['verified'])
            self.assertEqual(result['fault']['code'], 'INVALID_RASTER_PNG')
            self.assertEqual(result['fault']['location'], '$.images[1].source')
            self.assertIn('recovery', result['fault'])
            self.assertFalse(list(out.glob('image-*.png')))

    def test_reopened_capture_png_fault_is_verification_failure(self):
        document = json.loads((ROOT / 'examples/schemaxis/imagemagick-sheet.json').read_text())
        document['images'] = document['images'][:1]
        document.pop('sheet', None)
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / 'captured-00.png').write_bytes(self.UNSUPPORTED['palette']())
            for name, value in [('authored.json', document), ('plan.json', adaptor.plan(document)),
                                ('result.json', {'status': 'succeeded'}), ('verification.json', {}),
                                ('captures.json', [{'source': document['images'][0]['source'],
                                  'sha256': adaptor.digest(run, 'captured-00.png'),
                                  'bytes': len((run / 'captured-00.png').read_bytes())}])]:
                (run / name).write_text(json.dumps(value))
            with self.assertRaises(SchemaxisError) as caught:
                adaptor.verify(run)
            self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')
            self.assertEqual(caught.exception.fault.observed['cause']['code'], 'UNSUPPORTED_RASTER_PNG')

    def test_documented_recovery_names_both_codes(self):
        readiness = json.loads((ROOT / 'src/schemaxis/adaptors/imagemagick/readiness.json').read_text())
        recovery = readiness['routes'][adaptor.VERSION]['context']['recovery']
        guide = (ROOT / 'docs/imagemagick.md').read_text()
        for code in ('INVALID_RASTER_PNG', 'UNSUPPORTED_RASTER_PNG'):
            self.assertIn(code, recovery)
            self.assertIn(code, guide)


if __name__ == '__main__':
    unittest.main()
