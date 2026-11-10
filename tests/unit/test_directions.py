# Copyright (C) 2026 David L F Gaden
from __future__ import annotations

import math
import unittest

from schemaxis.core.declarations import validate_specification
from schemaxis.core.directions import DIRECTION_ARGUMENT, resolve_direction, resolve_up
from schemaxis.core.faults import SchemaxisError


def fault_of(case: unittest.TestCase, *arguments, **keywords):
    with case.assertRaises(SchemaxisError) as trapped:
        resolve_direction(*arguments, **keywords)
    return trapped.exception.fault


def close(case: unittest.TestCase, actual, expected, places=9):
    for index, (a, b) in enumerate(zip(actual, expected)):
        case.assertAlmostEqual(a, b, places=places, msg=f"component {index}")


class DeclarationTests(unittest.TestCase):
    def test_the_fragment_is_valid_in_the_shared_grammar(self) -> None:
        validate_specification(DIRECTION_ARGUMENT, "$.direction")


class AxisTokenTests(unittest.TestCase):
    def test_every_positive_spelling_agrees(self) -> None:
        for token in ("x", "x+", "xp", "+x", "X+", " x "):
            with self.subTest(token=token):
                self.assertEqual(resolve_direction(token).vector, (1.0, 0.0, 0.0))

    def test_every_negative_spelling_agrees(self) -> None:
        for token in ("z-", "zm", "-z", "Z-"):
            with self.subTest(token=token):
                self.assertEqual(resolve_direction(token).vector, (0.0, 0.0, -1.0))

    def test_an_unknown_token_lists_what_is_accepted(self) -> None:
        fault = fault_of(self, "up")
        self.assertEqual(fault.code, "UNKNOWN_AXIS_TOKEN")
        self.assertIn("x+", fault.recovery)

    def test_the_object_spelling_agrees_with_the_shorthand(self) -> None:
        self.assertEqual(resolve_direction({"axis": "y-"}).vector, resolve_direction("y-").vector)


class VectorTests(unittest.TestCase):
    def test_a_bare_array_is_a_vector_and_is_normalised(self) -> None:
        direction = resolve_direction([0, 3, 4])
        close(self, direction.vector, (0.0, 0.6, 0.8))
        self.assertEqual(direction.spelling, "vector")

    def test_a_zero_vector_is_refused(self) -> None:
        self.assertEqual(fault_of(self, [0, 0, 0]).code, "DEGENERATE_DIRECTION")

    def test_a_vector_of_the_wrong_length_is_refused_by_the_declaration(self) -> None:
        self.assertEqual(fault_of(self, [1, 0]).code, "INVALID_ARGUMENT")


class AzimuthElevationTests(unittest.TestCase):
    def test_zero_azimuth_and_elevation_is_the_reference_axis(self) -> None:
        close(self, resolve_direction({"azimuth": 0, "elevation": 0}).vector, (1.0, 0.0, 0.0))

    def test_azimuth_turns_anticlockwise_about_up(self) -> None:
        close(self, resolve_direction({"azimuth": 90}).vector, (0.0, 1.0, 0.0))
        close(self, resolve_direction({"azimuth": -90}).vector, (0.0, -1.0, 0.0))
        close(self, resolve_direction({"azimuth": 180}).vector, (-1.0, 0.0, 0.0))

    def test_elevation_tilts_towards_up(self) -> None:
        close(self, resolve_direction({"azimuth": 0, "elevation": 90}).vector, (0.0, 0.0, 1.0))
        close(self, resolve_direction({"elevation": -90}).vector, (0.0, 0.0, -1.0))
        close(self, resolve_direction({"azimuth": 0, "elevation": 45}).vector,
              (math.sqrt(0.5), 0.0, math.sqrt(0.5)))

    def test_a_missing_angle_is_taken_as_zero_and_said_so(self) -> None:
        direction = resolve_direction({"azimuth": 90})
        self.assertIn("elevation was not declared", direction.notes[0])

    def test_a_declared_up_moves_the_reference_frame(self) -> None:
        direction = resolve_direction({"azimuth": 0, "elevation": 90, "up": "y+"})
        close(self, direction.vector, (0.0, 1.0, 0.0))
        close(self, resolve_direction({"azimuth": 0, "up": "x+"}).vector, (0.0, 1.0, 0.0))

    def test_angles_outside_the_declared_range_are_refused(self) -> None:
        self.assertEqual(fault_of(self, {"azimuth": 400}).code, "INVALID_ARGUMENT")
        self.assertEqual(fault_of(self, {"elevation": 200}).code, "INVALID_ARGUMENT")


class RoundTripTests(unittest.TestCase):
    def test_every_spelling_reports_its_azimuth_and_elevation(self) -> None:
        self.assertAlmostEqual(resolve_direction("y+").azimuth, 90.0)
        self.assertAlmostEqual(resolve_direction("y+").elevation, 0.0)
        self.assertAlmostEqual(resolve_direction("z+").elevation, 90.0)
        direction = resolve_direction([1, 1, 0])
        self.assertAlmostEqual(direction.azimuth, 45.0)
        self.assertAlmostEqual(direction.elevation, 0.0)

    def test_angles_round_trip_back_to_the_same_vector(self) -> None:
        for supplied in ([1, 2, 3], [-4, 0.5, -2], "x-"):
            with self.subTest(supplied=supplied):
                first = resolve_direction(supplied)
                second = resolve_direction(
                    {"azimuth": first.azimuth, "elevation": first.elevation}
                )
                close(self, second.vector, first.vector, places=9)


class ViewUpTests(unittest.TestCase):
    def test_view_up_is_perpendicular_to_the_direction(self) -> None:
        direction = resolve_direction({"azimuth": 30, "elevation": 40})
        self.assertAlmostEqual(sum(a * b for a, b in zip(direction.vector, direction.view_up)), 0.0)
        self.assertAlmostEqual(math.sqrt(sum(c * c for c in direction.view_up)), 1.0)

    def test_looking_along_up_states_its_fallback_rather_than_producing_nothing(self) -> None:
        direction = resolve_direction("z-")
        close(self, direction.view_up, (1.0, 0.0, 0.0))
        self.assertIn("parallel to up", direction.notes[0])

    def test_a_horizontal_direction_keeps_up_as_view_up(self) -> None:
        close(self, resolve_direction("x+").view_up, (0.0, 0.0, 1.0))
        self.assertEqual(resolve_direction("x+").notes, ())


class InterpreterIndependenceTests(unittest.TestCase):
    """Host and native interpreters must resolve identical bits.

    Built-in float sum() became compensated in Python 3.12, so a host on 3.12+
    and a native ParaView interpreter on 3.10 disagreed in the last bit and exact
    presentation verification refused the run. These literals are the correctly
    rounded results; plain left-to-right summation misses them on Python 3.10.
    """

    def test_a_reported_orbit_camera_resolves_to_the_correctly_rounded_vector(self) -> None:
        self.assertEqual(resolve_direction({"azimuth": 49.09, "elevation": 25}).vector,
                         (0.5935162502410517, 0.6849323072706318, 0.4226182617406995))

    def test_cancelling_terms_are_summed_exactly(self) -> None:
        from schemaxis.core.directions import _combine, _dot
        self.assertEqual(_dot((1e16, 1.0, -1e16), (1.0, 1.0, 1.0)), 1.0)
        self.assertEqual(_combine((1e16, (1.0, 0.0, 0.0)), (1.0, (1.0, 0.0, 0.0)), (-1e16, (1.0, 0.0, 0.0))),
                         (1.0, 0.0, 0.0))


class SpecificationTests(unittest.TestCase):
    def test_declaring_two_spellings_at_once_is_refused(self) -> None:
        fault = fault_of(self, {"axis": "x+", "vector": [0, 1, 0]})
        self.assertEqual(fault.code, "OVER_SPECIFIED_DIRECTION")
        self.assertEqual(fault.observed["spellings"], ["axis", "vector"])

    def test_declaring_nothing_is_refused(self) -> None:
        self.assertEqual(fault_of(self, {"up": "z+"}).code, "UNDER_SPECIFIED_DIRECTION")

    def test_an_up_may_not_itself_be_an_azimuth(self) -> None:
        fault = fault_of(self, {"axis": "x+", "up": {"azimuth": 0}})
        self.assertEqual(fault.code, "INVALID_ARGUMENT")

    def test_up_accepts_a_token_or_a_vector(self) -> None:
        self.assertEqual(resolve_up("y-"), (0.0, -1.0, 0.0))
        close(self, resolve_up([0, 0, 2]), (0.0, 0.0, 1.0))

    def test_the_result_is_json_safe(self) -> None:
        import json
        envelope = resolve_direction({"azimuth": 12, "elevation": 34}).to_dict()
        self.assertEqual(json.loads(json.dumps(envelope)), envelope)


if __name__ == "__main__":
    unittest.main()
