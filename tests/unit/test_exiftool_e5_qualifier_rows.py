"""The E5 qualifier report classifies cases by explicit proved outcome, never by a test class or name heuristic (host only, no native process).

Coverage-positive rows are the explicit finite list with ``supported`` true, ``outcome`` succeeded and no refusal code, one per declared operation and container; proven refusals are
``refused`` with ``written`` false and a fault code; lifecycle, metadata-integrity and verification-mutant tests are controls and never support; an unknown test defaults to a neutral control.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tools')]

import qualify_exiftool_containers as q  # noqa: E402

CONTAINERS = ('tiff', 'dng', 'png', 'webp', 'heif')


class Rows(unittest.TestCase):
    def test_the_positive_list_is_one_row_per_operation_container_and_category(self):
        cells = sorted((v[0], v[1], v[2] if len(v) > 2 else None) for v in q.POSITIVE.values())
        self.assertEqual(len(cells), len(set(cells)))
        self.assertEqual(set(cells), q.REQUIRED_CELLS)                      # exactly the contract cells: no mixed row stands in for an untested pair
        self.assertEqual(len(cells), 92)
        for operation in q.OPERATIONS:
            if operation == 'removeMetadata':
                continue
            for container in CONTAINERS:
                self.assertIn((operation, container, None), cells)
        for container in ('tiff', 'dng', 'png', 'webp'):
            for category in q.CATEGORIES:
                self.assertIn(('removeMetadata', container, category), cells)
        self.assertIn(('removeMetadata', 'png', 'minimise'), cells)
        self.assertIn(('removeMetadata', 'webp', 'minimise'), cells)
        self.assertFalse([c for c in cells if c[:2] == ('removeMetadata', 'heif')])        # HEIF removal and minimise are refused: never a positive row
        self.assertFalse([c for c in cells if c[0] == 'removeMetadata' and c[1] in ('tiff', 'dng') and c[2] == 'minimise'])
        self.assertEqual({c[0] for c in cells}, set(q.OPERATIONS))
        self.assertFalse([c for c in cells if c[1] == 'mixed'])

    def test_the_named_refusals_are_the_three_minimise_gaps_and_the_proven_limits(self):
        refused = {(v[0], v[1], v[2]) for v in q.REFUSAL_PROVEN.values()}
        for container, code in (('tiff', 'MINIMISE_UNSUPPORTED_CONTAINER'), ('dng', 'MINIMISE_UNSUPPORTED_CONTAINER'), ('heif', 'HEIF_REMOVAL_UNSUPPORTED')):
            self.assertIn(('removeMetadata', container, code), refused)
        self.assertIn(('setLocation', 'heif', 'HEIF_METADATA_ITEM_CREATION_UNSUPPORTED'), refused)
        self.assertIn(('removeMetadata', 'webp', 'WEBP_METADATA_REMOVAL_LAYOUT_UNSUPPORTED'), refused)

    def test_a_positive_is_supported_succeeded_and_a_failed_positive_is_not_support(self):
        ident = next(iter(q.POSITIVE))
        module, klass, method = ident.rsplit('.', 2)
        row = q.classify(ident, klass, method, 'passed')
        self.assertEqual((row['kind'], row['outcome'], row['supported']), ('supported', 'succeeded', True))
        self.assertNotIn('faultCode', row)
        self.assertFalse(q.classify(ident, klass, method, 'failed')['supported'])
        self.assertFalse(q.classify(ident, klass, method, 'skipped')['supported'])

    def test_proven_refusals_are_refused_and_wrote_nothing(self):
        for ident, (operation, container, code) in q.REFUSAL_PROVEN.items():
            module, klass, method = ident.rsplit('.', 2)
            row = q.classify(ident, klass, method, 'passed')
            self.assertEqual((row['kind'], row['outcome'], row['supported'], row['written'], row['faultCode']), ('refusal', 'refused', False, False, code))

    def test_lifecycle_mutants_and_unknown_tests_are_controls_that_never_vouch_for_support(self):
        for klass, method, kind in (('Lifecycle', 'test_png_cancel', 'lifecycle-control'), ('MetadataFirst', 'test_png_gamma', 'verification-control'), ('Native', 'test_mutants_a_changed_protected_byte_is_found_with_its_exact_path', 'verification-control'),
                                    ('Native', 'test_some_new_native_test', 'control'), ('Host', 'test_h2_a_heif_without_the_items_is_never_asked_to_create_them', 'control')):
            row = q.classify('x.%s.%s' % (klass, method), klass, method, 'passed')
            self.assertEqual((row['kind'], row['supported'], row['written']), (kind, False, None))
            self.assertNotIn('outcome', row)

    def test_every_listed_test_id_exists_in_a_module_of_the_suite(self):
        sys.path.insert(0, str(ROOT / 'tests/unit'))
        import importlib
        for ident in list(q.POSITIVE) + list(q.REFUSAL_PROVEN):
            module, klass, method = ident.rsplit('.', 2)
            self.assertTrue(hasattr(getattr(importlib.import_module(module), klass), method), ident)

    def test_the_container_of_a_row_comes_from_the_explicit_lists_or_the_test_name(self):
        self.assertEqual(q.container_of('test_png_timeout'), 'png')
        self.assertEqual(q.container_of('test_t1_t2_t3_t5_tiff_edits_keep_every_strip'), 'tiff')
        self.assertEqual(q.container_of('test_x6_something'), 'mixed')


if __name__ == '__main__':
    unittest.main()
