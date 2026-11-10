"""Public surfaces of the E5 container family (host only): capabilities, discovery, readiness, Studio, examples, documentation and the field matrix.

The documented field by family by container matrix is regenerated here from ``writes.json`` and the pinned container profiles and must equal the text of ``docs/exiftool.md``, so the guide
cannot drift from the data. Every refusal code of the pinned profiles appears in the guide. Nothing here runs a native process.
"""
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests/unit')]

from schemaxis.adaptors.exiftool import adaptor, capabilities, e5profiles, writes  # noqa: E402
from schemaxis.capabilities import CapabilityCatalogue  # noqa: E402
from schemaxis.search_acceptance import check_cases  # noqa: E402

PACKAGE = ROOT / 'src/schemaxis/adaptors/exiftool'
GUIDE = (ROOT / 'docs/exiftool.md').read_text()
CONDITIONAL = {'jpeg': ('exif', 'iptc'), 'tiff': ('iptc',), 'dng': ('iptc',), 'png': ('exif',), 'webp': ('exif',), 'heif': ('exif', 'xmp')}


def generated_matrix():
    columns = [('JPEG', 'jpeg'), ('TIFF', 'tiff'), ('DNG', 'dng'), ('PNG', 'png'), ('WebP', 'webp'), ('HEIF', 'heif')]
    lines = ['| Field | ' + ' | '.join(label for label, _ in columns) + ' |', '|---|' + '|'.join(['---'] * len(columns)) + '|']
    for name, spec in writes.fields().items():
        families = [d['family'] for d in spec['destinations']]
        cells = []
        for _, container in columns:
            parts = []
            for family, short in (('xmp', 'XMP'), ('exif', 'EXIF'), ('iptc', 'IPTC')):
                if family not in families:
                    continue
                if container != 'jpeg' and not e5profiles.destination(container, family):
                    parts.append('-' + short)
                else:
                    parts.append(short + ('*' if family in CONDITIONAL[container] else ''))
            cells.append(', '.join(parts))
        lines.append('| `%s` | ' % name + ' | '.join(cells) + ' |')
    return '\n'.join(lines)


class Surface(unittest.TestCase):
    def test_the_documented_field_matrix_equals_the_one_generated_from_the_data(self):
        self.assertIn(generated_matrix(), GUIDE)

    def test_every_refusal_code_of_every_profile_is_documented(self):
        for container in e5profiles.containers():
            for code in e5profiles.profile(container)['refusalCodes']:
                self.assertIn('`%s`' % code, GUIDE, (container, code))

    def test_every_named_limitation_that_is_a_native_capability_gap_is_published(self):
        for text in ('heifNativeMetadataCreationNotReproducible', 'HEIF_METADATA_ITEM_CREATION_UNSUPPORTED', 'HEIF_REMOVAL_UNSUPPORTED', 'tiffUnknownTagSemanticsNotInterpreted', 'IPTC_RESOURCE_TAIL_UNSUPPORTED',
                     'TIFF_IPTC_DIGEST_UNSUPPORTED', 'TIFF_PHOTOSHOP_IPTC_CARRIER_UNSUPPORTED', 'iptcNotAvailableInContainer', 'heifSpecDraftOnly'):
            self.assertIn(text, GUIDE, text)

    def test_capabilities_name_the_containers_on_every_operation_and_keep_no_jpeg_only_write_claim(self):
        catalogue = capabilities.catalogue()
        self.assertEqual(len(capabilities.CONTAINER_OPERATIONS), 15)
        for name in capabilities.CONTAINER_OPERATIONS:
            operation = catalogue['operations'][name]
            self.assertTrue(any('Containers:' in line or 'Container rules:' in line for line in operation['semantics']), name)
            if name not in ('auditMetadata', 'compareMetadata'):
                self.assertTrue(any(c in line for line in operation['semantics'] for c in ('TIFF', 'PNG')), name)
        for name in ('inspectMetadata', 'auditMetadata', 'compareMetadata', 'editMetadata', 'removeMetadata'):
            self.assertIn('TIFF metadata', catalogue['operations'][name]['keywords'], name)
        text = json.dumps(catalogue)
        for stale in ('remain JPEG only in this build', 'are JPEG only in this build', 'writes JPEG files only', 'minimiseNotImplementedForPngWebp'):
            self.assertNotIn(stale, text, stale)
        for reference in [e['reference'] for op in catalogue['operations'].values() for e in op.get('examples', [])]:
            self.assertTrue((ROOT / reference).is_file(), reference)
        references = {e['reference'] for op in catalogue['operations'].values() for e in op.get('examples', [])}
        for name in ('correct-time', 'set-location', 'copy-metadata', 'minimise'):
            self.assertIn('examples/schemaxis/exiftool-%s-containers.json' % name, references)

    def test_search_cases_find_the_containers_and_keep_raw_formats_and_gif_negative(self):
        catalogue = CapabilityCatalogue(providers=['exiftool'])
        self.assertTrue(check_cases(catalogue, 'exiftool')['complete'])
        found = lambda q: [i['id'].split('/')[-1] for i in catalogue.search(q, scope='app/exiftool', limit=100, max_bytes=65536)['items']]
        self.assertIn('editMetadata', found('edit TIFF metadata'))
        self.assertNotIn('inventoryPhotos', found('edit TIFF metadata'))
        self.assertEqual(found('strip metadata from WebP photos'), ['removeMetadata'])
        for query in ('edit CR2 raw file metadata', 'edit GIF metadata', 'run a raw exiftool expression'):
            self.assertEqual(found(query), [], query)

    def test_readiness_examples_exist_and_plan_and_studio_templates_are_valid_documents(self):
        readiness = json.loads((PACKAGE / 'readiness.json').read_text())['routes']['schemaxis.exiftool/1']
        by = {e['id']: e for e in readiness['examples']}
        for name in ('inspect-containers', 'edit-containers', 'remove-containers'):
            path = ROOT / by[name]['reference']
            self.assertTrue(path.is_file(), name)
            self.assertTrue(adaptor.plan(json.loads(path.read_text())), name)
        studio = {t['id']: t for t in json.loads((PACKAGE / 'studio.json').read_text())['templates']}
        for name in ('inspect-containers', 'edit-containers', 'remove-containers'):
            self.assertTrue(adaptor.plan(studio[name]['document']), name)
        self.assertIn('TIFF', readiness['context']['constraints'])

    def test_the_default_folder_scope_and_every_container_suffix_are_stated(self):
        for text in ('`.jpg`, `.jpeg` and `.xmp`', '.tif', '.dng', '.png', '.webp', '.heic', 'never by suffix'):
            self.assertIn(text, GUIDE, text)
        self.assertEqual(re.findall(r'^## Containers: TIFF, DNG, PNG, WebP and HEIF$', GUIDE, flags=re.M), ['## Containers: TIFF, DNG, PNG, WebP and HEIF'])


if __name__ == '__main__':
    unittest.main()
