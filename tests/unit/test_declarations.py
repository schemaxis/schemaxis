from __future__ import annotations

import unittest

from schemaxis.core.declarations import (
    describe_arguments,
    validate_arguments,
    validate_specifications,
)
from schemaxis.core.faults import SchemaxisError


# A composite declaration of roughly the shape a slice-series capability needs:
# a list of named planes, each with its own defaulted members.
SLICE_ARGUMENTS = {
    "axes": {
        "type": "array",
        "required": True,
        "minItems": 1,
        "uniqueItems": True,
        "items": {"type": "enum", "values": ["x", "y", "z"]},
    },
    "spacing": {"type": "number", "minimum": 0, "exclusiveMinimum": True, "default": 1.0},
    "colouring": {
        "type": "object",
        "properties": {
            "field": {"type": "string", "required": True},
            "legend": {"type": "boolean", "default": True},
            "range": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 2,
                "maxItems": 2,
            },
        },
        "default": {"field": "p", "legend": False},
    },
}


def fault_of(caught: unittest.TestCase, function, *arguments, **keywords):
    with caught.assertRaises(SchemaxisError) as trapped:
        function(*arguments, **keywords)
    return trapped.exception.fault


class ValueValidationTests(unittest.TestCase):
    def test_applies_nested_defaults_without_aliasing_the_declaration(self) -> None:
        first = validate_arguments(SLICE_ARGUMENTS, {"axes": ["x", "z"]})
        self.assertEqual(first["spacing"], 1.0)
        self.assertEqual(first["colouring"], {"field": "p", "legend": False})

        first["colouring"]["field"] = "mutated"
        second = validate_arguments(SLICE_ARGUMENTS, {"axes": ["x"]})
        self.assertEqual(second["colouring"]["field"], "p")

    def test_validates_and_defaults_members_of_a_supplied_object(self) -> None:
        values = validate_arguments(
            SLICE_ARGUMENTS, {"axes": ["y"], "colouring": {"field": "U", "range": [0, 12.5]}}
        )
        self.assertEqual(values["colouring"], {"field": "U", "legend": True, "range": [0, 12.5]})

    def test_reports_the_exact_location_inside_an_array(self) -> None:
        fault = fault_of(self, validate_arguments, SLICE_ARGUMENTS, {"axes": ["x", "w"]})
        self.assertEqual(fault.code, "INVALID_ARGUMENT")
        self.assertEqual(fault.location, "$.arguments.axes[1]")
        self.assertIn("'z'", fault.recovery)

    def test_reports_the_exact_location_inside_a_nested_object(self) -> None:
        fault = fault_of(
            self, validate_arguments, SLICE_ARGUMENTS,
            {"axes": ["x"], "colouring": {"field": "p", "legend": "yes"}},
        )
        self.assertEqual(fault.location, "$.arguments.colouring.legend")
        self.assertEqual(fault.observed["type"], "string")
        self.assertEqual(fault.recovery, "supply a boolean")

    def test_missing_required_member_names_what_would_be_accepted(self) -> None:
        fault = fault_of(
            self, validate_arguments, SLICE_ARGUMENTS, {"axes": ["x"], "colouring": {}}
        )
        self.assertEqual(fault.code, "MISSING_ARGUMENT")
        self.assertEqual(fault.location, "$.arguments.colouring.field")
        self.assertEqual(fault.recovery, "supply a string")

    def test_missing_required_argument(self) -> None:
        fault = fault_of(self, validate_arguments, SLICE_ARGUMENTS, {})
        self.assertEqual(fault.code, "MISSING_ARGUMENT")
        self.assertEqual(fault.location, "$.arguments.axes")

    def test_unknown_argument_lists_the_declared_names(self) -> None:
        fault = fault_of(
            self, validate_arguments, SLICE_ARGUMENTS, {"axes": ["x"], "spaceing": 2}
        )
        self.assertEqual(fault.code, "UNKNOWN_ARGUMENT")
        self.assertEqual(fault.observed["unknown"], ["spaceing"])
        self.assertIn("spacing", fault.observed["declared"])

    def test_enforces_exclusive_bounds_and_lengths(self) -> None:
        self.assertEqual(
            validate_arguments(SLICE_ARGUMENTS, {"axes": ["x"], "spacing": 0.5})["spacing"], 0.5
        )
        self.assertEqual(
            fault_of(self, validate_arguments, SLICE_ARGUMENTS, {"axes": ["x"], "spacing": 0}).location,
            "$.arguments.spacing",
        )
        self.assertEqual(
            fault_of(self, validate_arguments, SLICE_ARGUMENTS, {"axes": []}).location,
            "$.arguments.axes",
        )
        self.assertEqual(
            fault_of(
                self, validate_arguments, SLICE_ARGUMENTS,
                {"axes": ["x"], "colouring": {"field": "p", "range": [1, 2, 3]}},
            ).location,
            "$.arguments.colouring.range",
        )

    def test_rejects_duplicate_array_items_when_declared_unique(self) -> None:
        fault = fault_of(self, validate_arguments, SLICE_ARGUMENTS, {"axes": ["x", "x"]})
        self.assertEqual(fault.code, "INVALID_ARGUMENT")
        self.assertEqual(fault.location, "$.arguments.axes")

    def test_booleans_are_not_integers_and_integers_are_not_booleans(self) -> None:
        arguments = {"count": {"type": "integer"}, "flag": {"type": "boolean"}}
        self.assertEqual(fault_of(self, validate_arguments, arguments, {"count": True}).location, "$.arguments.count")
        self.assertEqual(fault_of(self, validate_arguments, arguments, {"flag": 1}).location, "$.arguments.flag")

    def test_rejects_a_nonfinite_number(self) -> None:
        arguments = {"value": {"type": "number"}}
        self.assertEqual(fault_of(self, validate_arguments, arguments, {"value": float("nan")}).code, "INVALID_ARGUMENT")

    def test_a_string_is_not_an_array(self) -> None:
        arguments = {"axes": {"type": "array", "items": {"type": "string"}}}
        self.assertEqual(fault_of(self, validate_arguments, arguments, {"axes": "xyz"}).location, "$.arguments.axes")

    def test_location_prefix_is_caller_supplied(self) -> None:
        fault = fault_of(
            self, validate_arguments, SLICE_ARGUMENTS, {"axes": ["q"]},
            location="$.steps[2].arguments", phase="planning",
        )
        self.assertEqual(fault.location, "$.steps[2].arguments.axes[0]")
        self.assertEqual(fault.phase, "planning")


class DeclarationValidationTests(unittest.TestCase):
    def check(self, specification):
        return fault_of(self, validate_specifications, {"item": specification}, "$.arguments")

    def test_accepts_the_composite_declaration(self) -> None:
        self.assertIs(validate_specifications(SLICE_ARGUMENTS, "$.arguments"), SLICE_ARGUMENTS)

    def test_rejects_an_undeclared_type(self) -> None:
        fault = self.check({"kind": "string"})
        self.assertEqual(fault.code, "INVALID_DECLARATION")
        self.assertIn("enum", fault.recovery)

    def test_rejects_a_misspelled_declaration_key(self) -> None:
        fault = self.check({"type": "number", "minimun": 0})
        self.assertEqual(fault.observed["unsupported"], ["minimun"])

    def test_rejects_a_default_its_own_declaration_would_reject(self) -> None:
        fault = self.check({"type": "enum", "values": ["x", "y"], "default": "w"})
        self.assertEqual(fault.location, "$.arguments.item.default")

    def test_rejects_required_together_with_a_default(self) -> None:
        self.assertEqual(self.check({"type": "string", "required": True, "default": "a"}).code, "INVALID_DECLARATION")

    def test_rejects_an_array_without_an_item_declaration(self) -> None:
        self.assertEqual(self.check({"type": "array"}).location, "$.arguments.item.items")

    def test_rejects_an_open_object(self) -> None:
        fault = self.check({"type": "object", "properties": {}, "additionalProperties": True})
        self.assertEqual(fault.location, "$.arguments.item.additionalProperties")

    def test_rejects_an_object_without_properties(self) -> None:
        self.assertEqual(self.check({"type": "object"}).location, "$.arguments.item.properties")

    def test_rejects_an_empty_enum(self) -> None:
        self.assertEqual(self.check({"type": "enum", "values": []}).location, "$.arguments.item.values")

    def test_checks_nested_declarations(self) -> None:
        fault = self.check({"type": "array", "items": {"type": "object", "properties": {"a": {"type": "bogus"}}}})
        self.assertEqual(fault.location, "$.arguments.item.items.properties.a")

    def test_rejects_inverted_bounds(self) -> None:
        self.assertEqual(self.check({"type": "integer", "minimum": 5, "maximum": 1}).code, "INVALID_DECLARATION")

    def test_rejects_an_invalid_argument_name(self) -> None:
        fault = fault_of(self, validate_specifications, {"2bad": {"type": "string"}}, "$.arguments")
        self.assertEqual(fault.code, "INVALID_DECLARATION")


class DescriptionTests(unittest.TestCase):
    def test_description_is_ordered_and_json_safe(self) -> None:
        description = describe_arguments(SLICE_ARGUMENTS)
        self.assertEqual(list(description), ["axes", "colouring", "spacing"])
        self.assertEqual(description["axes"]["items"]["values"], ["x", "y", "z"])

    def test_description_does_not_alias_the_declaration(self) -> None:
        description = describe_arguments(SLICE_ARGUMENTS)
        description["spacing"]["default"] = 99
        self.assertEqual(SLICE_ARGUMENTS["spacing"]["default"], 1.0)


if __name__ == "__main__":
    unittest.main()
