"""ImageJ TIFF ImageDescription boundary: metadata ImageJ turns into stacks or density calibration."""
import json
from pathlib import Path
import struct
import unittest

from schemaxis.adaptors.imagej import adaptor, images
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT/'examples/schemaxis/fixtures/imagej'
WIDTH, HEIGHT = 4, 3


def tiff8(description=None, pointer=None):
    """Little-endian, single-strip, uncompressed 8-bit TIFF with an optional ASCII ImageDescription."""
    pixels = bytes([0, 0, 0, 0, 0, 200, 200, 0, 0, 0, 0, 0])
    text = None if description is None else description.encode('utf-8')+b'\0'
    entries = [(256, 3, 1, WIDTH), (257, 3, 1, HEIGHT), (258, 3, 1, 8), (259, 3, 1, 1), (262, 3, 1, 1),
               (273, 4, 1, None), (277, 3, 1, 1), (278, 3, 1, HEIGHT), (279, 4, 1, len(pixels))]
    if text is not None: entries.insert(5, (270, 2, len(text), None))
    table = 8+2+12*len(entries)+4
    data_at = table
    text_at = data_at+len(pixels)
    out = bytearray(b'II*\x00'+struct.pack('<IH', 8, len(entries)))
    for tag, kind, count, value in entries:
        if tag == 273: value = data_at
        if tag == 270: value = text_at if pointer is None else pointer
        packed = struct.pack('<I', value) if kind == 4 or tag == 270 else struct.pack('<HH', value, 0)
        out += struct.pack('<HHI', tag, kind, count)+packed
    out += struct.pack('<I', 0)+pixels+(text or b'')
    return bytes(out)


def fault(action):
    try:
        action()
    except SchemaxisError as error:
        return error.fault
    raise AssertionError('expected a structured fault')


def prepared():
    return adaptor.plan({'version': 'schemaxis.imagej/1', 'operation': 'analyzeParticles', 'image': '/x/a.tif',
                         'calibration': {'pixelWidth': 1, 'pixelHeight': 1, 'unit': 'um'},
                         'threshold': {'lower': 100, 'upper': 255}})


class DescriptionBoundaryTests(unittest.TestCase):
    def test_builder_matches_decoder_contract(self):
        image, analysis = adaptor.reference(prepared(), tiff8())
        self.assertEqual((image['width'], image['height'], image['bitDepth']), (WIDTH, HEIGHT, 8))
        self.assertEqual([p['pixelCount'] for p in analysis['particles']], [2])

    def test_imagej_stack_and_density_metadata_are_unsupported_before_native_launch(self):
        cases = [('ImageJ=1.54t\nimages=3\nslices=3\n', 'images'),
                 ('ImageJ=1.54t\nimages=6\nchannels=2\nframes=3\nhyperstack=true\n', 'images'),
                 ('ImageJ=1.54t\nimages=2.0\n', 'images'),
                 ('ImageJ=1.54t\nimages=1\nimages=3\n', 'images'),  # the last repeat wins, as in ImageJ
                 ('ImageJ=1.54t\n# note\n  images = 4\n', 'images'),
                 ('ImageJ=1.54t\r\nimages: 2\r\n', 'images'),
                 ('ImageJ=1.54t\nvunit=Gray Value\ncf=0\nc0=0.0\nc1=0.5\n', 'cf')]
        for text, key in cases:
            with self.subTest(key=key, text=text):
                observed = fault(lambda: adaptor.reference(prepared(), tiff8(text)))
                self.assertEqual((observed.code, observed.location), ('UNSUPPORTED_IMAGE', '$.image'))
                self.assertEqual(observed.observed['key'], key)
                self.assertEqual(observed.observed['tag'], 270)

    def test_benign_description_metadata_is_still_accepted(self):
        for text in ('ImageJ=1.54t\nunit=micron\nspacing=1.0\nmin=0.0\nmax=255.0\nimages=1\nslices=1\n',
                     'ImageJ=1.54t\nvunit=Gray Value\n',  # no calibration function: nothing replaces raw values
                     'ImageJ=1.54t\nvunit=Gray Value\ncf=0\n',  # no coefficients: ImageJ installs no function
                     'ImageJ=1.54t\nchannels=2\nframes=4\nhyperstack=true\n',  # shape a stack only when images>1
                     'ImageJ=1.54t\nimages=3\nimages=1\n',
                     'Scanner export images=3 channels=2 cf=0',  # not ImageJ-authored: ImageJ ignores it
                     'ImageJ=1.54t\n=3\n',
                     'ImageJ=1.54t\n:3\n',
                     'ImageJ=1.54t\n\vkey=3\n',
                     'ImageJ=1.54t\nvunit=x\ncf=Infinity\n',
                     'ImageJ=1.54t\nvunit=x\ncf=1e400\n',
                     'ImageJ'):
            with self.subTest(text=text):
                image, _ = adaptor.reference(prepared(), tiff8(text))
                self.assertEqual(image['values'], tiff8() and images.decode(tiff8(), '.tif')['values'])

    def test_description_pointing_outside_file_is_malformed_not_unsupported(self):
        observed = fault(lambda: adaptor.reference(prepared(), tiff8('ImageJ=1.54t\nimages=3\n', pointer=10**6)))
        self.assertEqual((observed.code, observed.location), ('INVALID_IMAGE', '$.image'))
        unterminated = tiff8('ImageJ=1.54t\nimages=3\n')[:-1]  # drops the terminating NUL
        self.assertEqual(fault(lambda: adaptor.reference(prepared(), unterminated)).code, 'INVALID_IMAGE')

    def test_fixtures_unchanged_by_boundary(self):
        data = (FIXTURES/'particles-16bit.tif').read_bytes()
        self.assertEqual(images.decode(data, '.tif')['bitDepth'], 16)


if __name__ == '__main__':
    unittest.main()
