"""A verified image publication reaches a Pandoc image block; no other artifact kind, nor an unfit PNG, does."""
import json
from pathlib import Path
import random
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from schemaxis import parallel
from schemaxis.adaptors import registry
from schemaxis.adaptors.pandoc import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
RGBA = [[(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 255, 255)],
        [(10, 20, 30, 128), (200, 100, 50, 64), (7, 8, 9, 0), (250, 251, 252, 0)],
        [(0, 0, 0, 255), (128, 128, 128, 255), (1, 2, 3, 1), (254, 253, 252, 254)]]


def chunk(kind, body):
    return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))


def literal_png(rows=RGBA, colour=6, width=None, height=None, extra=b'', compression=9):
    """Hand-written PNG: every scanline filter 0, written independently of the adaptor's reader."""
    height = height or len(rows)
    width = width or len(rows[0])
    channels = 4 if colour == 6 else 3
    raw = b''.join(b'\0' + b''.join(bytes(pixel[:channels]) for pixel in row) for row in rows)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, colour, 0, 0, 0))
            + extra + chunk(b'IDAT', zlib.compress(raw, compression)) + chunk(b'IEND', b''))


def producer_document():
    return {'version': 'schemaxis.webp/1', 'operation': 'decodeToPng',
            'source': str(ROOT / 'examples/schemaxis/fixtures/webp/decode-literal-rgba.webp')}


def workflow(source=None, **block):
    source = source or {'$artifact': 'decode', 'index': 0}
    return {'version': 'schemaxis.workflow/1', 'operations': [
        {'id': 'decode', 'document': producer_document()},
        {'id': 'report', 'document': {'version': 'schemaxis.pandoc/1', 'operation': 'report', 'title': 'Decoded image',
            'sections': [{'heading': 'Image', 'level': 1, 'content': [
                {'kind': 'image', 'source': source, 'alt': 'Four by three RGBA literal', 'widthMm': 40, **block}]}]}}]}


class Producer:
    """Fixture producer publishing one artifact; consumers run the real Pandoc planning and capture rules."""
    def __init__(self, payload, kind='image', suffix='.png'):
        self.payload, self.kind, self.suffix, self.consumed = payload, kind, suffix, []

    def run(self, document, directory, *args, **options):
        directory.mkdir()
        atomic_json(directory / 'authored.json', document)
        if document['version'] == 'schemaxis.webp/1':
            atomic_json(directory / 'plan.json', registry.plan(document))
            artifact = directory / ('image' + self.suffix)
            artifact.write_bytes(self.payload)
            atomic_json(directory / 'verification.json', {'artifacts': [{'file': str(artifact), 'kind': self.kind}]})
            return {'verified': True}
        prepared = adaptor.plan(document)
        for i, j, block in adaptor.image_blocks(prepared):
            data = adaptor.bounded(block['source'], 'INVALID_REPORT_IMAGE', 4 * 1024 * 1024)
            adaptor.png(data, block['source'])
            self.consumed.append((block['source'], data))
        atomic_json(directory / 'plan.json', prepared)
        atomic_json(directory / 'verification.json', {'artifacts': []})
        return {'verified': True}

    def receipt(self, directory, expected):
        return json.loads((Path(directory) / 'verification.json').read_text())


class PandocImageArtifact(unittest.TestCase):
    def execute(self, producer, document=None):
        with tempfile.TemporaryDirectory() as temp, patch('schemaxis.parallel.run_native', side_effect=producer.run), \
                patch('schemaxis.parallel.verify_native', side_effect=producer.receipt):
            return parallel.execute(document or workflow(), Path(temp) / 'run')

    def refusal(self, producer, code, document=None):
        with self.assertRaises(SchemaxisError) as caught: self.execute(producer, document)
        self.assertEqual(caught.exception.fault.code, code)
        return caught.exception.fault

    def test_route_declares_text_and_image_and_nothing_wider(self):
        self.assertEqual(registry.resolve({'version': 'schemaxis.pandoc/1'}, legacy=True)[1]['acceptedArtifacts'], ['text', 'image'])
        manifest = json.loads((ROOT / 'src/schemaxis/adaptors/pandoc/adaptor.json').read_text())
        self.assertEqual(manifest['routes']['schemaxis.pandoc/1']['acceptedArtifacts'], ['text', 'image'])

    def test_typed_png_reaches_the_image_block_byte_for_byte(self):
        for label, rows, colour in (('transparent', RGBA, 6), ('opaque', [[p[:3] for p in row] for row in RGBA], 2)):
            with self.subTest(label):
                payload = literal_png(rows, colour)
                producer = Producer(payload)
                result = self.execute(producer)
                self.assertTrue(result['verified'])
                (path, data), = producer.consumed
                self.assertTrue(path.endswith('/decode/batch-0/attempt-0001/image.png'))
                self.assertEqual(data, payload)

    def test_unrelated_artifact_kinds_are_refused_before_the_consumer_starts(self):
        for kind, suffix in (('table', '.csv'), ('audio', '.wav'), ('file', '.png'), ('archive', '.zip'), ('video', '.mp4'),
                             ('geometry', '.stl'), ('spriteSheet', '.png')):
            with self.subTest(kind=kind):
                producer = Producer(literal_png(), kind, suffix)
                fault = self.refusal(producer, 'TYPE_MISMATCH')
                self.assertEqual(fault.observed['kind'], kind)
                self.assertEqual(producer.consumed, [])

    def test_text_handoff_is_still_accepted_for_transcripts(self):
        self.assertIn('text', registry.resolve({'version': 'schemaxis.pandoc/1'}, legacy=True)[1]['acceptedArtifacts'])

    def test_a_typed_image_that_is_not_a_plain_png_fails_closed(self):
        cases = {
            'not a png': b'GIF89a' + bytes(64),
            'palette colour': literal_png(colour=3),
            'ancillary chunk': literal_png(extra=chunk(b'tEXt', b'Comment\0forged')),
            'trailing bytes': literal_png() + b'\0',
            'truncated': literal_png()[:-5],
            'oversize panel': literal_png(rows=[[(1, 2, 3, 4)] * 2049], width=2049),
        }
        for name, payload in cases.items():
            with self.subTest(name):
                producer = Producer(payload)
                fault = self.refusal(producer, 'INVALID_REPORT_IMAGE')
                if name == 'palette colour':
                    self.assertIn('colour', fault.message)
                self.assertEqual(producer.consumed, [])

    def test_image_artifact_at_transcript_path_is_refused_before_consumption(self):
        document = workflow()
        document['operations'][1]['document']['sections'][0]['content'] = [
            {'kind': 'transcript', 'segments': {'path': {'$artifact': 'decode', 'index': 0}}}]
        producer = Producer(literal_png())
        fault = self.refusal(producer, 'INVALID_TRANSCRIPT_SOURCE', document)
        self.assertEqual(fault.location, '$.sections[0].content[0].segments.path')
        self.assertEqual(producer.consumed, [])

    def test_image_over_the_per_file_byte_budget_is_refused_not_rescaled(self):
        payload = literal_png() + bytes(4 * 1024 * 1024)
        producer = Producer(payload)
        fault = self.refusal(producer, 'INVALID_REPORT_IMAGE')
        self.assertIn('bounded', fault.message)
        self.assertEqual(producer.consumed, [])

    def test_combined_budget_refuses_a_third_valid_image_without_truncation(self):
        # Each incompressible 1024x1024 RGB PNG is about 3 MiB, inside the 4 MiB per-file limit;
        # three exceed the 8 MiB total, so capture stops before any native process starts.
        generator = random.Random(53)
        raw = b''.join(b'\0' + generator.randbytes(3 * 1024) for _ in range(1024))
        payload = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1024, 1024, 8, 2, 0, 0, 0))
                   + chunk(b'IDAT', zlib.compress(raw, 0)) + chunk(b'IEND', b''))
        self.assertLess(len(payload), 4 * 1024 * 1024)
        self.assertGreater(3 * len(payload), 8 * 1024 * 1024)
        with tempfile.TemporaryDirectory() as temp:
            files = []
            for n in range(3):
                path = Path(temp) / f'{n}.png'
                path.write_bytes(payload); files.append(str(path))
            document = {'version': 'schemaxis.pandoc/1', 'operation': 'report', 'title': 't', 'sections': [
                {'heading': 'h', 'level': 1, 'content': [{'kind': 'image', 'source': f, 'alt': 'a', 'widthMm': 10} for f in files]}]}
            with patch('subprocess.Popen', side_effect=AssertionError('native launch prohibited')), \
                    self.assertRaises(SchemaxisError) as caught:
                adaptor.run(document, Path(temp) / 'out', executable='/bin/true')
            self.assertEqual(caught.exception.fault.code, 'REPORT_RESOURCE_LIMIT')

    def test_width_limit_still_applies_to_a_handed_over_image(self):
        # The width is checked once the handed-over path resolves, still before any native launch.
        for width, code in ((149, 'INVALID_ARGUMENT'), (12.3456789, 'INVALID_REPORT_IMAGE')):
            with self.subTest(width=width):
                producer = Producer(literal_png())
                self.refusal(producer, code, workflow(widthMm=width))
                self.assertEqual(producer.consumed, [])

    def test_literal_path_reports_are_unchanged(self):
        document = json.loads((ROOT / 'examples/schemaxis/pandoc-report.json').read_text())
        self.assertEqual(adaptor.plan(document)['sections'][1]['content'][1]['source'], '/replace/with/calibration.png')
        document['sections'][1]['content'][1]['source'] = {'$artifact': 'x', 'index': 0}
        with self.assertRaises(SchemaxisError): adaptor.plan(document)


if __name__ == '__main__':
    unittest.main()
