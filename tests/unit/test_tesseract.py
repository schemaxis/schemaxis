"""Host-only Tesseract contract checks: planning, discovery, guidance and image admission. No native process runs."""
import copy
import json
from pathlib import Path
import struct
import unittest

from schemaxis.adaptors import registry
from schemaxis.adaptors.tesseract import adaptor, tsv
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / 'examples/schemaxis'
FIXTURES = EXAMPLES / 'fixtures/tesseract'


def example(name): return json.loads((EXAMPLES / name).read_text())


def fixture(name): return (FIXTURES / name).read_bytes()


def header(width, height, colour=2, depth=8, interlace=0):
    """A PNG signature and IHDR only: enough for header-first refusals, with no pixel allocation."""
    import zlib
    body = struct.pack('>IIBBBBB', width, height, depth, colour, 0, 0, interlace)
    return b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + b'IHDR' + body + struct.pack('>I', zlib.crc32(b'IHDR' + body))


class Tesseract(unittest.TestCase):
    def fault(self, action, code, location=None):
        with self.assertRaises(SchemaxisError) as raised: action()
        self.assertEqual(raised.exception.fault.code, code, raised.exception.fault.to_dict())
        if location: self.assertEqual(raised.exception.fault.location, location)

    def test_registered_without_framework_branches(self):
        self.assertIn('tesseract', [p['id'] for p in registry.discover()['providers']])
        for path in (ROOT / 'src/schemaxis').glob('*.py'):
            self.assertNotIn('tesseract', path.read_text().lower(), path.name)
        manifest = json.loads((ROOT / 'src/schemaxis/adaptors/tesseract/adaptor.json').read_text())
        self.assertEqual(manifest['routes']['schemaxis.tesseract/1']['acceptedArtifacts'], ['image', 'text'])

    def test_plan_is_deterministic_immutable_and_records_settings(self):
        document = example('tesseract-baseline.json');original = copy.deepcopy(document)
        first = adaptor.plan(document)
        self.assertEqual(first, adaptor.plan(document));self.assertEqual(document, original)
        self.assertEqual((first['language'], first['pageSegmentation'], first['settings']['psm'], first['settings']['oem']), ('eng', 'uniform-block', 6, 1))
        self.assertEqual(first['settings']['densitySource'], 'authored')
        line = adaptor.plan(example('tesseract-single-line.json'))
        self.assertEqual(line['settings']['psm'], 7)
        no_dpi = {k: v for k, v in document.items() if k != 'dpi'}
        self.assertEqual(adaptor.plan(no_dpi)['settings']['densitySource'], 'png-declared-or-native-estimate')
        self.assertNotIn('--dpi', adaptor.commands('/x', adaptor.plan(no_dpi))['recognize'])
        command = adaptor.commands('/x', first)['recognize']
        self.assertEqual(command[command.index('--dpi') + 1], '200')
        self.assertEqual(sum(1 for c in command if c == '-c'), 2)
        self.assertNotEqual(adaptor.plan(document), adaptor.plan(example('tesseract-variant.json')))
        self.assertNotEqual(adaptor.plan(document), line)

    def test_closed_input_and_exact_faults(self):
        base = example('tesseract-baseline.json')
        self.fault(lambda: adaptor.plan({**base, 'extra': 1}), 'UNKNOWN_ARGUMENT')
        self.fault(lambda: adaptor.plan({**base, 'operation': 'other'}), 'UNKNOWN_OPERATION')
        self.fault(lambda: adaptor.plan({**base, 'image': {'path': 'page.png'}}), 'INVALID_IMAGE_SOURCE', '$.image.path')
        self.fault(lambda: adaptor.plan({**base, 'image': {'path': '/a/../b.png'}}), 'INVALID_IMAGE_SOURCE')
        self.fault(lambda: adaptor.plan({**base, 'image': {'path': 'https://x.invalid/a.png'}}), 'INVALID_IMAGE_SOURCE')
        self.fault(lambda: adaptor.plan({**base, 'model': {**base['model'], 'path': '/a/eng.bin'}}), 'INVALID_MODEL', '$.model.path')
        self.fault(lambda: adaptor.plan({**base, 'model': {'path': base['model']['path'], 'sha256': 'A' * 64}}), 'INVALID_SHA256', '$.model.sha256')
        self.fault(lambda: adaptor.plan({**base, 'model': {'path': base['model']['path']}}), 'MISSING_ARGUMENT')
        for key, value in (('language', 'fra'), ('pageSegmentation', 'sparse-text'), ('dpi', 20), ('dpi', 5000), ('dpi', True)):
            self.fault(lambda: adaptor.plan({**base, key: value}), 'INVALID_ARGUMENT')
        self.fault(lambda: adaptor.plan({**base, 'origin': {'kind': 'other', 'summary': '/a.json', 'page': 1}}), 'INVALID_ARGUMENT')
        self.fault(lambda: adaptor.plan({**base, 'origin': {'kind': 'mupdf-review', 'summary': 'a.json', 'page': 1}}), 'INVALID_ORIGIN_SOURCE', '$.origin.summary')
        for name, code in (('tesseract-image-relative-invalid.json', 'INVALID_IMAGE_SOURCE'), ('tesseract-hash-invalid.json', 'INVALID_SHA256'),
                           ('tesseract-segmentation-invalid.json', 'INVALID_ARGUMENT'), ('tesseract-language-invalid.json', 'INVALID_ARGUMENT'), ('tesseract-dpi-invalid.json', 'INVALID_ARGUMENT')):
            self.fault(lambda: registry.plan(example(name)), code)

    def test_resources_serial_only(self):
        self.assertEqual(adaptor.resources({}, {}, 'x'), {'threads': 1})
        self.fault(lambda: adaptor.resources({}, {'threads': 2}, 'x'), 'INVALID_EXECUTION')

    def test_image_admission_accepts_rgb_and_refuses_each_unsupported_class_distinctly(self):
        info = adaptor.admit_image(fixture('baseline.png'))
        self.assertEqual((info['width'], info['height'], info['declaredDensityDpi']), (483, 228, 200))
        self.assertEqual(len(info['rgbSha256']), 64)
        self.fault(lambda: adaptor.admit_image(header(10, 10, colour=6)), 'UNSUPPORTED_IMAGE')
        self.fault(lambda: adaptor.admit_image(header(10, 10, colour=0)), 'UNSUPPORTED_IMAGE')
        self.fault(lambda: adaptor.admit_image(header(10, 10, colour=3)), 'UNSUPPORTED_IMAGE')
        self.fault(lambda: adaptor.admit_image(header(10, 10, depth=16)), 'UNSUPPORTED_IMAGE')
        self.fault(lambda: adaptor.admit_image(header(10, 10, interlace=1)), 'UNSUPPORTED_IMAGE')
        self.fault(lambda: adaptor.admit_image(header(5000, 10)), 'IMAGE_RESOURCE_LIMIT')
        self.fault(lambda: adaptor.admit_image(header(4096, 4096)), 'IMAGE_RESOURCE_LIMIT')
        self.fault(lambda: adaptor.admit_image(header(0, 10)), 'IMAGE_RESOURCE_LIMIT')
        self.fault(lambda: adaptor.admit_image(b'not a png'), 'INVALID_IMAGE_DATA')
        self.fault(lambda: adaptor.admit_image(fixture('baseline.png')[:-20]), 'INVALID_IMAGE_DATA')
        self.fault(lambda: adaptor.admit_image(fixture('baseline.png')[:60]), 'INVALID_IMAGE_DATA')

    def test_origin_binds_only_matching_pixels_and_unknown_is_explicit(self):
        data = fixture('baseline.png');image = adaptor.admit_image(data)
        p = adaptor.plan({**example('tesseract-origin.json')})
        summary = {'sourceSha256': 'a' * 64, 'pageCount': 3, 'dpi': 72, 'rotation': 0,
                   'pages': [{'page': 1, 'width': 483, 'height': 228, 'rgbSha256': image['rgbSha256']}]}
        origin = adaptor.origin_document(p, json.dumps(summary).encode(), image)
        self.assertEqual((origin['state'], origin['page'], origin['pdfSha256'], origin['pageCount']), ('declared-bound-to-pixels', 1, 'a' * 64, 3))
        wrong = copy.deepcopy(summary);wrong['pages'][0]['rgbSha256'] = 'b' * 64
        self.fault(lambda: adaptor.origin_document(p, json.dumps(wrong).encode(), image), 'ORIGIN_MISMATCH')
        wrong = copy.deepcopy(summary);wrong['pages'][0]['width'] = 484
        self.fault(lambda: adaptor.origin_document(p, json.dumps(wrong).encode(), image), 'ORIGIN_MISMATCH')
        self.fault(lambda: adaptor.origin_document({**p, 'origin': {**p['origin'], 'page': 2}}, json.dumps(summary).encode(), image), 'ORIGIN_MISMATCH')
        self.fault(lambda: adaptor.origin_document(p, b'{', image), 'ORIGIN_INVALID')
        self.fault(lambda: adaptor.origin_document(p, b'{"pages": [], "sourceSha256": "x"}', image), 'ORIGIN_INVALID')
        pixel_only = {k: v for k, v in p.items() if k != 'origin'}
        self.assertEqual(adaptor.origin_document(pixel_only, None, image)['state'], 'unknown')

    def test_discovery_guidance_and_search_cases(self):
        from schemaxis.adaptors.tesseract import capabilities
        catalogue = capabilities.catalogue()
        self.assertIn('recognizePage', catalogue['operations'])
        kinds = {case['kind'] for case in catalogue['searchCases']}
        self.assertEqual(kinds, {'synonym', 'multiword', 'ambiguous', 'negative'})
        guidance = json.loads((ROOT / 'src/schemaxis/adaptors/tesseract/guidance.json').read_text())
        for address in ('/properties/image/properties/path', '/properties/model/properties/sha256', '/properties/origin/properties/page', '/properties/dpi', '/properties/pageSegmentation'):
            self.assertEqual(guidance['routes']['schemaxis.tesseract/1']['fields'][address]['status'], 'reviewed')
        self.assertEqual(guidance['operations']['recognizePage']['status'], 'reviewed')

    def test_schema_matches_planner(self):
        schema = adaptor.schema()
        self.assertEqual(set(schema['properties']), {'version', 'operation', 'image', 'model', 'origin', 'language', 'pageSegmentation', 'dpi'})
        self.assertEqual(set(schema['required']), {'version', 'operation', 'image', 'model'})
