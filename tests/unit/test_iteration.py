# Copyright (C) 2026 David L F Gaden
from __future__ import annotations

import unittest

from schemaxis.core.faults import SchemaxisError
from schemaxis.core.iteration import Axis, count_visits, expand, iter_visits


def axes():
    return [
        Axis.of("time", [0.001, 0.002]),
        Axis.of("slice", [1.0, 2.0, 3.0]),
        Axis.of("field", ["p", "U"]),
    ]


def fault_of(case: unittest.TestCase, function, *arguments, **keywords):
    with case.assertRaises(SchemaxisError) as trapped:
        function(*arguments, **keywords)
    return trapped.exception.fault


class OrderTests(unittest.TestCase):
    def test_the_outermost_axis_varies_slowest(self) -> None:
        visits = expand(axes())
        self.assertEqual(len(visits), 12)
        self.assertEqual(
            [visit.key for visit in visits[:4]],
            ["time=0/slice=0/field=p", "time=0/slice=0/field=U",
             "time=0/slice=1/field=p", "time=0/slice=1/field=U"],
        )
        self.assertEqual(visits[-1].coordinates, {"time": 0.002, "slice": 3.0, "field": "U"})

    def test_pipeline_digits_a_fastest_include_carry_resets(self) -> None:
        visits = expand([Axis.of("C", [0, 1]), Axis.of("B", [0, 1]),
                         Axis.of("A", [0, 1, 2, 3])])
        states = [tuple(v.coordinates[k] for k in ("A", "B", "C")) for v in visits]
        self.assertEqual(states, [(a, b, c) for c in range(2)
                                  for b in range(2) for a in range(4)])
        self.assertEqual(states[3:6], [(3, 0, 0), (0, 1, 0), (1, 1, 0)])
        self.assertEqual(visits[4].changed, ("B", "A"))
        self.assertEqual(visits[8].changed, ("C", "B", "A"))

    def test_coordinated_surfaces_are_one_appearance_axis(self) -> None:
        appearances = [dict(s0="black", s1=field, s2=field, s3=field)
                       for field in ("p", "rho", "Umag")]
        visits = expand([Axis.of("geometry", [0, 1]),
                         Axis.of("appearance", appearances)])
        self.assertEqual(len(visits), 6)
        self.assertEqual([v.coordinates["appearance"] for v in visits], appearances * 2)
        self.assertEqual(visits[1].changed, ("appearance",))
        self.assertEqual(visits[3].changed, ("geometry", "appearance"))

    def test_ordinals_are_dense_and_ascending(self) -> None:
        self.assertEqual([visit.ordinal for visit in expand(axes())], list(range(12)))

    def test_count_matches_the_expansion_without_building_it(self) -> None:
        self.assertEqual(count_visits(axes()), len(expand(axes())))


class ChangeTests(unittest.TestCase):
    def test_the_first_visit_establishes_every_axis(self) -> None:
        self.assertEqual(expand(axes())[0].changed, ("time", "slice", "field"))

    def test_only_the_cheap_inner_axis_changes_between_neighbours(self) -> None:
        self.assertEqual(expand(axes())[1].changed, ("field",))

    def test_an_outer_axis_changes_only_when_the_inner_ones_have_wrapped(self) -> None:
        visits = expand(axes())
        self.assertEqual(visits[2].changed, ("slice", "field"))
        self.assertEqual(visits[6].changed, ("time", "slice", "field"))

    def test_every_visit_after_the_first_changes_the_innermost_axis(self) -> None:
        for visit in expand(axes())[1:]:
            self.assertEqual(visit.changed[-1], "field")

    def test_an_expensive_axis_is_re_entered_exactly_as_often_as_it_has_values(self) -> None:
        entries = [visit for visit in expand(axes()) if "time" in visit.changed]
        self.assertEqual(len(entries), 2)


class LabelTests(unittest.TestCase):
    def test_numeric_axes_get_zero_padded_ordinal_labels(self) -> None:
        axis = Axis.of("slice", [float(index) for index in range(12)])
        self.assertEqual(axis.labels[0], "00")
        self.assertEqual(axis.labels[11], "11")

    def test_string_values_label_themselves(self) -> None:
        self.assertEqual(Axis.of("field", ["p", "U"]).labels, ("p", "U"))

    def test_labels_may_be_supplied_or_computed(self) -> None:
        self.assertEqual(Axis.of("time", [0.1, 0.2], labels=["a", "b"]).labels, ("a", "b"))
        self.assertEqual(
            Axis.of("time", [0.1, 0.2], label=lambda index, item: f"t{item}").labels,
            ("t0.1", "t0.2"),
        )

    def test_repeated_labels_are_refused_because_they_name_outputs(self) -> None:
        fault = fault_of(self, Axis.of, "field", ["p", "U"], labels=["same", "same"])
        self.assertEqual(fault.code, "INVALID_ITERATION_AXIS")

    def test_a_label_count_mismatch_is_refused(self) -> None:
        self.assertEqual(
            fault_of(self, Axis.of, "field", ["p", "U"], labels=["only"]).code,
            "INVALID_ITERATION_AXIS",
        )


class FaultTests(unittest.TestCase):
    def test_an_empty_axis_is_refused_rather_than_silently_producing_nothing(self) -> None:
        fault = fault_of(self, Axis.of, "field", [])
        self.assertEqual(fault.code, "EMPTY_ITERATION_AXIS")
        self.assertIn("leave the axis out", fault.recovery)

    def test_duplicate_axis_names_are_refused(self) -> None:
        fault = fault_of(self, expand, [Axis.of("field", ["p"]), Axis.of("field", ["U"])])
        self.assertEqual(fault.code, "DUPLICATE_ITERATION_AXIS")
        self.assertIn("depths 0 and 1", fault.message)

    def test_an_expansion_above_a_declared_limit_is_refused_before_it_runs(self) -> None:
        fault = fault_of(self, expand, axes(), limit=11)
        self.assertEqual(fault.code, "EXPANSION_TOO_LARGE")
        self.assertEqual(fault.observed["visits"], 12)
        self.assertEqual(fault.observed["axes"], {"time": 2, "slice": 3, "field": 2})

    def test_a_limit_is_checked_before_the_first_visit_is_yielded(self) -> None:
        with self.assertRaises(SchemaxisError):
            next(iter_visits(axes(), limit=1))

    def test_a_string_is_not_a_sequence_of_values(self) -> None:
        self.assertEqual(fault_of(self, Axis.of, "field", "pU").code, "INVALID_ITERATION_AXIS")


class DegenerateTests(unittest.TestCase):
    def test_no_axes_is_one_unparameterised_visit(self) -> None:
        visits = expand([])
        self.assertEqual(len(visits), 1)
        self.assertEqual(visits[0].key, "")
        self.assertEqual(visits[0].changed, ())

    def test_single_valued_axes_still_produce_one_visit(self) -> None:
        visits = expand([Axis.of("time", [0.5]), Axis.of("field", ["p"])])
        self.assertEqual(len(visits), 1)
        self.assertEqual(visits[0].key, "time=0/field=p")

    def test_visits_are_json_safe_and_do_not_expose_mutable_state(self) -> None:
        import json
        visit = expand(axes())[3]
        envelope = visit.to_dict()
        self.assertEqual(json.loads(json.dumps(envelope)), envelope)
        with self.assertRaises(TypeError):
            visit.labels["field"] = "mutated"


if __name__ == "__main__":
    unittest.main()
