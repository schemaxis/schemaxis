from __future__ import annotations

import unittest

from schemaxis.core.declarations import validate_specification
from schemaxis.core.faults import SchemaxisError
from schemaxis.core.series import SERIES_ARGUMENT, resolve_series


def fault_of(case: unittest.TestCase, *arguments, **keywords):
    with case.assertRaises(SchemaxisError) as trapped:
        resolve_series(*arguments, **keywords)
    return trapped.exception.fault


class DeclarationTests(unittest.TestCase):
    def test_the_fragment_is_valid_in_the_shared_grammar(self) -> None:
        validate_specification(SERIES_ARGUMENT, "$.series")


class CombinationTests(unittest.TestCase):
    def test_start_spacing_end(self) -> None:
        series = resolve_series({"start": 0, "spacing": 0.25, "end": 1})
        self.assertEqual(series.positions, (0.0, 0.25, 0.5, 0.75, 1.0))
        self.assertEqual(series.count, 5)
        self.assertEqual(series.sources["count"], "derived")
        self.assertEqual(series.notes, ())

    def test_start_spacing_count(self) -> None:
        series = resolve_series({"start": 2, "spacing": 3, "count": 4})
        self.assertEqual(series.positions, (2.0, 5.0, 8.0, 11.0))
        self.assertEqual(series.sources["end"], "derived")

    def test_spacing_count_end(self) -> None:
        series = resolve_series({"spacing": 2, "count": 3, "end": 10})
        self.assertEqual(series.positions, (6.0, 8.0, 10.0))
        self.assertEqual(series.sources["start"], "derived")

    def test_start_count_end(self) -> None:
        series = resolve_series({"start": 0, "count": 5, "end": 2})
        self.assertEqual(series.positions, (0.0, 0.5, 1.0, 1.5, 2.0))
        self.assertEqual(series.spacing, 0.5)
        self.assertEqual(series.sources["spacing"], "derived")

    def test_a_single_position_needs_no_spacing(self) -> None:
        series = resolve_series({"start": 4, "count": 1})
        self.assertEqual(series.positions, (4.0,))
        self.assertEqual(series.spacing, 0.0)
        self.assertEqual(series.sources["end"], "derived")
        self.assertEqual(resolve_series({"end": 4, "count": 1}).positions, (4.0,))

    def test_a_single_position_between_bounds_is_ambiguous_and_says_why(self) -> None:
        fault = fault_of(self, {"count": 1}, bounds=(0, 10))
        self.assertEqual(fault.code, "INCONSISTENT_SERIES")
        self.assertEqual(fault.observed["sources"]["start"], "bounds")


class BoundsTests(unittest.TestCase):
    def test_bounds_supply_only_the_ends_that_are_missing(self) -> None:
        series = resolve_series({"spacing": 1}, bounds=(0, 3))
        self.assertEqual(series.positions, (0.0, 1.0, 2.0, 3.0))
        self.assertEqual(series.sources, {
            "count": "derived", "end": "bounds", "spacing": "declared", "start": "bounds",
        })

    def test_declared_spacing_and_count_derive_the_end_rather_than_taking_it_from_bounds(self) -> None:
        series = resolve_series({"spacing": 1, "count": 2}, bounds=(0, 100))
        self.assertEqual(series.positions, (0.0, 1.0))
        self.assertEqual(series.sources["start"], "bounds")
        self.assertEqual(series.sources["end"], "derived")

    def test_padding_insets_bounds_derived_ends_only(self) -> None:
        series = resolve_series({"count": 3, "padding": 0.5}, bounds=(0, 10))
        self.assertEqual(series.positions, (0.5, 5.0, 9.5))
        self.assertIn("inset by 0.5", series.notes[0])

        declared = resolve_series({"start": 0, "count": 2, "end": 10, "padding": 0.5}, bounds=(0, 10))
        self.assertEqual(declared.positions, (0.0, 10.0))

    def test_padding_fraction_is_relative_to_the_extent(self) -> None:
        series = resolve_series({"count": 2, "paddingFraction": 0.1}, bounds=(0, 10))
        self.assertEqual(series.positions, (1.0, 9.0))

    def test_padding_and_padding_fraction_are_alternatives(self) -> None:
        fault = fault_of(self, {"count": 2, "padding": 1, "paddingFraction": 0.1}, bounds=(0, 10))
        self.assertEqual(fault.code, "INCONSISTENT_SERIES")

    def test_padding_may_not_consume_the_extent(self) -> None:
        fault = fault_of(self, {"count": 2, "padding": 5}, bounds=(0, 10))
        self.assertEqual(fault.code, "INCONSISTENT_SERIES")
        self.assertIn("5.0", fault.recovery)

    def test_inverted_bounds_are_read_in_order_and_said_so(self) -> None:
        series = resolve_series({"count": 2}, bounds=(10, 0))
        self.assertEqual(series.positions, (0.0, 10.0))
        self.assertIn("inverted", series.notes[0])

    def test_padding_without_bounds_is_reported_rather_than_ignored(self) -> None:
        series = resolve_series({"start": 0, "end": 1, "count": 2, "padding": 0.1})
        self.assertIn("no bounds were supplied", series.notes[0])


class ToleranceTests(unittest.TestCase):
    def test_an_end_the_spacing_cannot_reach_is_reported(self) -> None:
        series = resolve_series({"start": 0, "spacing": 0.3, "end": 1})
        self.assertEqual(len(series.positions), 4)
        self.assertAlmostEqual(series.end, 0.9)
        self.assertIn("is not an exact multiple", series.notes[0])

    def test_an_exactly_reached_end_produces_no_note(self) -> None:
        self.assertEqual(resolve_series({"start": 0, "spacing": 0.1, "end": 0.3}).count, 4)
        self.assertEqual(resolve_series({"start": 0, "spacing": 0.1, "end": 0.3}).notes, ())

    def test_a_spacing_pointing_the_wrong_way_is_turned_around_and_said_so(self) -> None:
        series = resolve_series({"start": 10, "spacing": 2, "end": 4})
        self.assertEqual(series.positions, (10.0, 8.0, 6.0, 4.0))
        self.assertIn("pointed away", series.notes[0])


class FaultTests(unittest.TestCase):
    def test_under_specified_names_every_valid_combination(self) -> None:
        fault = fault_of(self, {"start": 0, "end": 1})
        self.assertEqual(fault.code, "UNDER_SPECIFIED_SERIES")
        self.assertIn("start + spacing + count", fault.recovery)
        self.assertFalse(fault.observed["boundsSupplied"])

    def test_nothing_declared_and_no_bounds(self) -> None:
        self.assertEqual(fault_of(self, {}).code, "UNDER_SPECIFIED_SERIES")

    def test_over_specified(self) -> None:
        fault = fault_of(self, {"start": 0, "end": 1, "spacing": 0.5, "count": 3})
        self.assertEqual(fault.code, "OVER_SPECIFIED_SERIES")
        self.assertEqual(fault.observed["count"], 3)

    def test_zero_spacing_cannot_span_distinct_ends(self) -> None:
        self.assertEqual(fault_of(self, {"start": 0, "spacing": 0, "end": 1}).code, "INCONSISTENT_SERIES")

    def test_one_position_cannot_span_distinct_ends(self) -> None:
        fault = fault_of(self, {"start": 0, "count": 1, "end": 5})
        self.assertEqual(fault.code, "INCONSISTENT_SERIES")
        self.assertIn("count of at least 2", fault.recovery)

    def test_declaration_faults_carry_the_supplied_location(self) -> None:
        fault = fault_of(self, {"start": "left"}, location="$.steps[1].arguments.positions")
        self.assertEqual(fault.code, "INVALID_ARGUMENT")
        self.assertEqual(fault.location, "$.steps[1].arguments.positions.start")

    def test_unknown_members_are_rejected(self) -> None:
        self.assertEqual(fault_of(self, {"begin": 0}).code, "UNKNOWN_ARGUMENT")

    def test_count_below_one_is_rejected_by_the_declaration(self) -> None:
        self.assertEqual(fault_of(self, {"start": 0, "spacing": 1, "count": 0}).code, "INVALID_ARGUMENT")


class EvidenceTests(unittest.TestCase):
    def test_the_result_is_json_safe_and_records_every_source(self) -> None:
        import json
        series = resolve_series({"spacing": 1}, bounds=(0, 2))
        envelope = series.to_dict()
        self.assertEqual(json.loads(json.dumps(envelope)), envelope)
        self.assertEqual(sorted(envelope["sources"]), ["count", "end", "spacing", "start"])


class ExpansionLimitTests(unittest.TestCase):
    def test_declared_or_derived_huge_counts_fail_before_allocation(self):
        for declaration in ({'start': 0, 'spacing': 1, 'count': 10**12},
                            {'start': 0, 'end': 1e12, 'spacing': 1}):
            with self.subTest(declaration=declaration), self.assertRaises(SchemaxisError) as caught:
                resolve_series(declaration, limit=100)
            self.assertEqual(caught.exception.fault.code, 'EXPANSION_TOO_LARGE')

    def test_finite_inputs_that_overflow_derivation_are_faults(self):
        with self.assertRaises(SchemaxisError) as caught:
            resolve_series({'start': -1e308, 'end': 1e308, 'spacing': 1e-308}, limit=100)
        self.assertEqual(caught.exception.fault.code, 'INCONSISTENT_SERIES')

    def test_limit_boundary_preserves_positions(self):
        result = resolve_series({'start': -5, 'end': 5, 'count': 3}, limit=3)
        self.assertEqual(result.positions, (-5, 0, 5))


if __name__ == "__main__":
    unittest.main()
