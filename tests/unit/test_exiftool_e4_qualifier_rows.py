"""The E4 qualifier report classifies cases by explicit proved outcome, never by a test class or name heuristic (host only, no native process).

Coverage-positive rows are the explicit finite list with ``supported`` true, ``outcome`` succeeded and no refusal code; proven refusals are ``refused`` with ``written`` false and a fault code;
lifecycle, metadata-integrity and verification-mutant tests are controls and never support; an unknown test defaults to a neutral control.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tools')]

import qualify_exiftool_transfer_sidecar_naming as q  # noqa: E402


class Rows(unittest.TestCase):
    def test_exactly_one_positive_row_per_operation(self):
        self.assertEqual(sorted(op for op, _ in q.POSITIVE.values()), sorted(q.OPERATIONS))

    def test_a_positive_is_supported_succeeded_and_a_failed_positive_is_not_support(self):
        ident = next(iter(q.POSITIVE))
        module, klass, method = ident.rsplit('.', 2)
        row = q.classify(ident, klass, method, 'passed', q.POSITIVE[ident][0])
        self.assertEqual((row['kind'], row['outcome'], row['supported']), ('supported', 'succeeded', True))
        self.assertNotIn('faultCode', row)
        self.assertFalse(q.classify(ident, klass, method, 'failed', q.POSITIVE[ident][0])['supported'])

    def test_proven_refusals_are_refused_and_wrote_nothing(self):
        for ident, (operation, code) in q.REFUSAL_PROVEN.items():
            module, klass, method = ident.rsplit('.', 2)
            row = q.classify(ident, klass, method, 'passed', operation)
            self.assertEqual((row['kind'], row['outcome'], row['supported'], row['written'], row['faultCode']), ('refusal', 'refused', False, False, code))

    def test_the_orphan_time_refusals_are_refusal_rows_with_their_item_fault_and_never_support(self):
        orphan = [ident for ident in q.REFUSAL_PROVEN if '.test_E4H1_' in ident]
        self.assertEqual(len(orphan), 3)
        self.assertEqual(set(orphan), set(q.REFUSAL_ITEM_FAULT))
        for ident in orphan:
            module, klass, method = ident.rsplit('.', 2)
            row = q.classify(ident, klass, method, 'passed', 'copyMetadata')
            self.assertEqual((row['kind'], row['outcome'], row['supported'], row['written'], row['faultCode'], row['itemFaultCode']), ('refusal', 'refused', False, False, 'NO_USABLE_ITEMS', 'TRANSFER_TIME_COMPONENT_UNANCHORED'))
            self.assertNotIn(ident, q.POSITIVE_CLAIMS)
        # the written-and-verified orphan controls stay neutral controls: they extend no supported claim
        for method in ('test_E4H1_an_orphan_that_an_anchored_carrier_states_too_is_redundant_and_the_time_is_written_and_verified', 'test_E4H1_an_iptc_time_with_its_own_date_is_anchored_and_still_written_and_verified'):
            row = q.classify('test_exiftool_e4_transfer.Repair.' + method, 'Repair', method, 'passed', 'copyMetadata')
            self.assertEqual((row['kind'], row['supported'], row['written']), ('control', False, None))

    def test_lifecycle_mutants_and_unknown_tests_are_controls_that_never_vouch_for_support(self):
        for klass, method, kind in (('Lifecycle', 'test_copyMetadata_cancel', 'lifecycle-control'), ('Mutants', 'test_M_a_changed_title_after_publish_is_a_transfer_readback_mismatch', 'verification-control'),
                                    ('Native', 'test_M_S8_a_doctype_injected_into_the_sidecar_is_not_reproducible', 'verification-control'), ('Native', 'test_some_new_native_test', 'control'),
                                    ('Names', 'test_the_names_plan_is_the_text_artifact_with_the_capture_hash_of_every_item', 'control')):
            row = q.classify('x.%s.%s' % (klass, method), klass, method, 'passed', 'copyMetadata')
            self.assertEqual((row['kind'], row['supported'], row['written']), (kind, False, None))
            self.assertNotIn('outcome', row)

    def test_the_group_claims_have_their_own_positive_rows_and_never_replace_the_operation_positives(self):
        self.assertEqual({op for op, _ in q.POSITIVE_CLAIMS.values()}, {'copyMetadata', 'applySidecar'})
        self.assertEqual({claim for _, claim in q.POSITIVE_CLAIMS.values()} >= {'captureTime', 'location', 'mixed selection'}, True)
        for ident, (operation, claim) in q.POSITIVE_CLAIMS.items():
            module, klass, method = ident.rsplit('.', 2)
            row = q.classify(ident, klass, method, 'passed', operation)
            self.assertEqual((row['kind'], row['outcome'], row['supported'], row['written'], row['claim']), ('supported', 'succeeded', True, True, claim))
            self.assertFalse(q.classify(ident, klass, method, 'failed', operation)['supported'])
        self.assertFalse(set(q.POSITIVE) & set(q.POSITIVE_CLAIMS))

    def test_every_listed_test_id_exists_in_a_module_of_the_suite(self):
        sys.path.insert(0, str(ROOT / 'tests/unit'))
        import importlib
        for ident in list(q.POSITIVE) + list(q.POSITIVE_CLAIMS) + list(q.REFUSAL_PROVEN):
            module, klass, method = ident.rsplit('.', 2)
            self.assertTrue(hasattr(getattr(importlib.import_module(module), klass), method), ident)


if __name__ == '__main__':
    unittest.main()
