"""Host tests of the case-row classification of the native qualifier (tools/qualify_exiftool_time_location.py).

A report row may claim ``supported`` only for an explicit, finite list of positive cases that exist in the test modules and cover each of the five operations; lifecycle,
verification and every unknown or unlisted test are neutral controls that never vouch for support, and only refusals the test itself proves are ``refused``.
"""
import importlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tools'), str(ROOT / 'tests/unit')]
import qualify_exiftool_time_location as q  # noqa: E402

OPERATIONS = {'reconcileTime', 'locate', 'correctTime', 'setLocation', 'geotagFromTrack'}


class QualifierRows(unittest.TestCase):
    def test_every_positive_and_proven_refusal_id_names_a_real_test_and_each_operation_has_a_positive(self):
        for ident in list(q.POSITIVE) + list(q.REFUSAL_PROVEN):
            module, klass, method = ident.split('.')
            self.assertTrue(hasattr(getattr(importlib.import_module(module), klass), method), ident)
        self.assertEqual(set(q.POSITIVE.values()), OPERATIONS)
        for ident, operation in q.POSITIVE.items():
            self.assertEqual(q.operation_of(*ident.split('.')), operation)

    def test_only_a_passed_positive_is_support_and_a_skipped_or_failed_one_is_not(self):
        ident = 'test_exiftool_e3_correct.Native.test_T1_a_reference_correction_rewrites_exif_xmp_and_iptc_exactly'
        self.assertEqual(q.classify(ident, 'Native', ident.split('.')[-1], 'passed', 'correctTime'), {'kind': 'supported', 'outcome': 'succeeded', 'supported': True, 'written': True})
        for status in ('failed', 'skipped'):
            self.assertFalse(q.classify(ident, 'Native', ident.split('.')[-1], status, 'correctTime')['supported'])
        read = 'test_exiftool_e3_read.Native.test_R60_coordinate_matrix'
        self.assertEqual(q.classify(read, 'Native', read.split('.')[-1], 'passed', 'locate')['written'], None)         # a read operation writes nothing and claims no write

    def test_lifecycle_verification_and_unknown_tests_are_neutral_controls(self):
        cases = (('test_exiftool_e3_lifecycle.Lifecycle.test_correct_time_timeout', 'Lifecycle', 'lifecycle-control'),
                 ('test_exiftool_e3_metadata_first.CorrectTimeMetadataFirst.test_M_T4_x', 'CorrectTimeMetadataFirst', 'verification-control'),
                 ('test_exiftool_e3_place.Mutants.test_M_L1_x', 'Mutants', 'verification-control'),
                 ('test_exiftool_e3_correct.PlanAndMutants.test_M_T5_x', 'PlanAndMutants', 'verification-control'),
                 ('test_exiftool_e3_place.Native.test_a_brand_new_unlisted_case', 'Native', 'control'),
                 ('test_exiftool_e3_geotag.Native.test_refuses_something_but_is_not_listed', 'Native', 'control'))
        for ident, klass, kind in cases:
            row = q.classify(ident, klass, ident.split('.')[-1], 'passed', 'setLocation')
            self.assertEqual((row['kind'], row['supported'], row['written']), (kind, False, None), ident)
            self.assertNotIn('outcome', row)

    def test_only_listed_refusals_are_refused_with_written_false_and_a_code(self):
        for ident, (operation, code) in q.REFUSAL_PROVEN.items():
            row = q.classify(ident, ident.split('.')[1], ident.split('.')[-1], 'passed', operation)
            self.assertEqual((row['kind'], row['outcome'], row['supported'], row['written'], row['faultCode']), ('refusal', 'refused', False, False, code))


if __name__ == '__main__':
    unittest.main()
