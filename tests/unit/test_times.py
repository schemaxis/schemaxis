from __future__ import annotations

import unittest

from schemaxis.core.declarations import validate_specification
from schemaxis.core.faults import SchemaxisError
from schemaxis.core.times import TIMES_ARGUMENT, resolve_times


STORED = [0.0, 0.001, 0.002, 0.003, 0.004]


def fault_of(case: unittest.TestCase, *arguments, **keywords):
    with case.assertRaises(SchemaxisError) as trapped:
        resolve_times(*arguments, **keywords)
    return trapped.exception.fault


class DeclarationTests(unittest.TestCase):
    def test_the_fragment_is_valid_in_the_shared_grammar(self) -> None:
        validate_specification(TIMES_ARGUMENT, "$.times")


class ShorthandTests(unittest.TestCase):
    def test_latest_and_first_select_one_time(self) -> None:
        self.assertEqual(resolve_times("latest", STORED).values, (0.004,))
        self.assertEqual(resolve_times("first", STORED).values, (0.0,))

    def test_a_count_selects_that_many_in_ascending_order(self) -> None:
        self.assertEqual(resolve_times({"latest": 2}, STORED).values, (0.003, 0.004))
        self.assertEqual(resolve_times({"first": 3}, STORED).indices, (0, 1, 2))

    def test_asking_for_more_than_are_stored_returns_all_and_says_so(self) -> None:
        selection = resolve_times({"latest": 50}, STORED)
        self.assertEqual(len(selection.times), 5)
        self.assertIn("only 5 are stored", selection.notes[0])


class ValueTests(unittest.TestCase):
    def test_exact_values_carry_no_approximation(self) -> None:
        selection = resolve_times({"values": [0.002, 0.0]}, STORED)
        self.assertEqual(selection.values, (0.0, 0.002))
        self.assertTrue(all(item.requested is None for item in selection.times))
        self.assertEqual(selection.notes, ())

    def test_a_missing_value_takes_the_nearest_and_reports_the_difference(self) -> None:
        selection = resolve_times({"values": [0.0022]}, STORED)
        self.assertEqual(selection.values, (0.002,))
        self.assertAlmostEqual(selection.times[0].requested, 0.0022)
        self.assertAlmostEqual(selection.times[0].difference, -0.0002)
        self.assertIn("nearest stored time", selection.notes[0])

    def test_a_declared_tolerance_is_enforced(self) -> None:
        self.assertEqual(resolve_times({"values": [0.0022], "tolerance": 0.001}, STORED).values, (0.002,))
        fault = fault_of(self, {"values": [0.0022], "tolerance": 1e-9}, STORED)
        self.assertEqual(fault.code, "TIME_OUT_OF_TOLERANCE")
        self.assertAlmostEqual(fault.observed["nearest"], 0.002)
        self.assertIn("0.002", fault.recovery)

    def test_a_tolerance_that_approximates_nothing_is_reported(self) -> None:
        selection = resolve_times({"latest": 1, "tolerance": 0.1}, STORED)
        self.assertIn("does not approximate anything", selection.notes[0])

    def test_a_value_range_is_inclusive_and_order_free(self) -> None:
        self.assertEqual(resolve_times({"valueRange": [0.001, 0.003]}, STORED).values,
                         (0.001, 0.002, 0.003))
        self.assertEqual(resolve_times({"valueRange": [0.003, 0.001]}, STORED).values,
                         (0.001, 0.002, 0.003))

    def test_a_value_range_matching_nothing_is_a_fault_not_an_empty_success(self) -> None:
        fault = fault_of(self, {"valueRange": [10, 20]}, STORED)
        self.assertEqual(fault.code, "EMPTY_TIME_SELECTION")
        self.assertIn("0.0 to 0.004", fault.recovery)


class IndexTests(unittest.TestCase):
    def test_indices_address_stored_positions(self) -> None:
        self.assertEqual(resolve_times({"indices": [0, 4]}, STORED).values, (0.0, 0.004))

    def test_an_index_that_does_not_exist_is_a_fault_not_a_clamp(self) -> None:
        fault = fault_of(self, {"indices": [9]}, STORED)
        self.assertEqual(fault.code, "INVALID_TIME_INDEX")
        self.assertEqual(fault.recovery, "positions run from 0 to 4")

    def test_an_index_range_is_shortened_to_what_exists_and_says_so(self) -> None:
        selection = resolve_times({"indexRange": [3, 99]}, STORED)
        self.assertEqual(selection.indices, (3, 4))
        self.assertIn("was shortened", selection.notes[0])

    def test_an_index_range_entirely_beyond_the_stored_times_is_a_fault(self) -> None:
        self.assertEqual(fault_of(self, {"indexRange": [20, 30]}, STORED).code, "EMPTY_TIME_SELECTION")


class SelectorTests(unittest.TestCase):
    def test_two_selectors_at_once_are_refused(self) -> None:
        fault = fault_of(self, {"latest": 1, "first": 1}, STORED)
        self.assertEqual(fault.code, "OVER_SPECIFIED_TIMES")
        self.assertEqual(fault.observed["spellings"], ["latest", "first"])

    def test_no_selector_is_refused(self) -> None:
        self.assertEqual(fault_of(self, {"tolerance": 1}, STORED).code, "UNDER_SPECIFIED_TIMES")

    def test_a_case_with_no_stored_times_is_refused(self) -> None:
        self.assertEqual(fault_of(self, "latest", []).code, "NO_TIMES_AVAILABLE")


class OrderingTests(unittest.TestCase):
    def test_results_are_ascending_and_deduplicated(self) -> None:
        selection = resolve_times({"values": [0.004, 0.0, 0.0041]}, STORED)
        self.assertEqual(selection.values, (0.0, 0.004))
        self.assertIn("resolved to 2 distinct", selection.notes[-1])

    def test_deduplication_keeps_the_approximation_evidence(self) -> None:
        selection = resolve_times({"values": [0.004, 0.0039]}, STORED)
        self.assertEqual(selection.values, (0.004,))
        self.assertAlmostEqual(selection.times[0].requested, 0.0039)

    def test_times_supplied_out_of_order_are_reported(self) -> None:
        selection = resolve_times({"first": 2}, [0.002, 0.0, 0.001])
        self.assertIn("not in ascending order", selection.notes[0])
        self.assertEqual(selection.values, (0.0, 0.001))
        self.assertEqual(selection.indices, (1, 2))

    def test_the_result_is_json_safe(self) -> None:
        import json
        envelope = resolve_times({"values": [0.0022]}, STORED).to_dict()
        self.assertEqual(json.loads(json.dumps(envelope)), envelope)


if __name__ == "__main__":
    unittest.main()
