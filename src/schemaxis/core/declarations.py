# Copyright (C) 2026 David L F Gaden
"""One declaration grammar and one validation path for declared arguments.

An argument declaration is an ordinary dictionary. It is written either as an
in-code literal beside the implementation it configures, or as JSON inside a
static capability manifest; both are the same grammar, checked by the same code
here. That is deliberate: a manifest and an implementation that describe an
argument differently is the drift this module exists to make impossible.

Validation is total and closed. Every declared argument has a declared type,
every unknown key is rejected in both the declaration and the value, and every
failure is a structured :class:`~schemaxis.core.faults.Fault` carrying the exact dotted
location that failed, what was observed there, and what would have been
accepted instead.

Nothing here imports a provider, reads a resource, or executes anything.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

from .contracts import JsonValue, json_value
from .faults import SchemaxisError, Fault


INVALID_DECLARATION = "INVALID_DECLARATION"
UNKNOWN_ARGUMENT = "UNKNOWN_ARGUMENT"
MISSING_ARGUMENT = "MISSING_ARGUMENT"
INVALID_ARGUMENT = "INVALID_ARGUMENT"

DECLARATION_PHASE = "declaration"
VALIDATION_PHASE = "validation"

SCALAR_KINDS = frozenset({"string", "integer", "number", "boolean"})
COMPOSITE_KINDS = frozenset({"array", "object"})
KINDS = SCALAR_KINDS | COMPOSITE_KINDS | frozenset({"enum", "union"})

# Keys every declaration may carry, then the keys each kind adds. A key that
# appears in neither set is a typo, and a silently ignored typo in a
# declaration is a lie about what the argument accepts.
_COMMON_KEYS = frozenset({"type", "required", "default", "title", "summary"})
_KEYS_BY_KIND: dict[str, frozenset[str]] = {
    "string": frozenset({"minLength", "maxLength"}),
    "integer": frozenset({"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"}),
    "number": frozenset({"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"}),
    "boolean": frozenset(),
    "enum": frozenset({"values"}),
    "array": frozenset({"items", "minItems", "maxItems", "uniqueItems"}),
    "object": frozenset({"properties", "additionalProperties"}),
    "union": frozenset({"options"}),
}


def _fault(
    code: str,
    message: str,
    location: str,
    phase: str,
    *,
    observed: Mapping[str, Any] | None = None,
    recovery: str | None = None,
) -> SchemaxisError:
    return SchemaxisError(Fault(
        code=code, message=message, location=location, phase=phase,
        observed=observed or {}, recovery=recovery,
    ))


def _kind_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    return type(value).__name__


# ---------------------------------------------------------------------------
# Declaration checking
# ---------------------------------------------------------------------------

def validate_specification(
    specification: Any, location: str, *, phase: str = DECLARATION_PHASE
) -> Mapping[str, Any]:
    """Check one argument declaration and return it unchanged."""

    if not isinstance(specification, Mapping):
        raise _fault(
            INVALID_DECLARATION, "an argument declaration must be an object",
            location, phase, observed={"type": _kind_name(specification)},
            recovery='declare the argument as {"type": "..."}',
        )
    kind = specification.get("type")
    if kind not in KINDS:
        raise _fault(
            INVALID_DECLARATION, f"unsupported argument type {kind!r}", location, phase,
            observed={"type": kind if isinstance(kind, str) or kind is None else _kind_name(kind)},
            recovery=f"use one of: {', '.join(sorted(KINDS))}",
        )
    unknown = sorted(set(specification) - _COMMON_KEYS - _KEYS_BY_KIND[kind])
    if unknown:
        raise _fault(
            INVALID_DECLARATION,
            f"unsupported declaration keys for a {kind} argument: {', '.join(unknown)}",
            location, phase, observed={"unsupported": unknown},
            recovery=f"a {kind} argument accepts: "
                     f"{', '.join(sorted(_COMMON_KEYS | _KEYS_BY_KIND[kind]))}",
        )
    required = specification.get("required", False)
    if not isinstance(required, bool):
        raise _fault(
            INVALID_DECLARATION, "'required' must be a boolean", f"{location}.required", phase,
            observed={"type": _kind_name(required)},
        )
    if required and "default" in specification:
        raise _fault(
            INVALID_DECLARATION,
            "a required argument cannot also declare a default",
            location, phase, observed={"default": json_value(specification["default"])},
            recovery="drop 'required' if the default is the intended value, or drop the default",
        )
    for key in ("title", "summary"):
        if key in specification and not isinstance(specification[key], str):
            raise _fault(
                INVALID_DECLARATION, f"'{key}' must be a string", f"{location}.{key}", phase,
                observed={"type": _kind_name(specification[key])},
            )

    _validate_kind_keys(kind, specification, location, phase)

    if "default" in specification:
        # A default that its own declaration would reject is the worst kind of
        # declaration bug: it only fails for callers who omit the argument.
        validate_value(specification["default"], specification, f"{location}.default", phase)
    return specification


def _validate_kind_keys(
    kind: str, specification: Mapping[str, Any], location: str, phase: str
) -> None:
    if kind == "enum":
        values = specification.get("values")
        if not isinstance(values, (list, tuple)) or not values:
            raise _fault(
                INVALID_DECLARATION, "an enum argument requires a non-empty 'values' array",
                f"{location}.values", phase, observed={"type": _kind_name(values)},
            )
        for index, value in enumerate(values):
            if value is not None and not isinstance(value, (bool, int, float, str)):
                raise _fault(
                    INVALID_DECLARATION, "enum values must be JSON scalars",
                    f"{location}.values[{index}]", phase,
                    observed={"type": _kind_name(value)},
                )
        if len(values) != len(_distinct(values)):
            raise _fault(
                INVALID_DECLARATION, "enum values must be distinct",
                f"{location}.values", phase, observed={"values": json_value(list(values))},
            )
    elif kind == "array":
        if "items" not in specification:
            raise _fault(
                INVALID_DECLARATION, "an array argument requires an 'items' declaration",
                f"{location}.items", phase,
                recovery='declare the element type, e.g. "items": {"type": "string"}',
            )
        validate_specification(specification["items"], f"{location}.items", phase=phase)
        _bound_pair(specification, "minItems", "maxItems", location, phase)
        if "uniqueItems" in specification and not isinstance(specification["uniqueItems"], bool):
            raise _fault(
                INVALID_DECLARATION, "'uniqueItems' must be a boolean",
                f"{location}.uniqueItems", phase,
                observed={"type": _kind_name(specification["uniqueItems"])},
            )
    elif kind == "object":
        properties = specification.get("properties")
        if not isinstance(properties, Mapping):
            raise _fault(
                INVALID_DECLARATION, "an object argument requires a 'properties' object",
                f"{location}.properties", phase, observed={"type": _kind_name(properties)},
                recovery="declare each accepted property; open objects are not supported",
            )
        if specification.get("additionalProperties", False) is not False:
            raise _fault(
                INVALID_DECLARATION,
                "'additionalProperties' must be false; object arguments are closed",
                f"{location}.additionalProperties", phase,
                observed={"additionalProperties": json_value(specification["additionalProperties"])},
                recovery="declare every accepted property explicitly",
            )
        for name, member in properties.items():
            _valid_name(name, f"{location}.properties", phase)
            validate_specification(member, f"{location}.properties.{name}", phase=phase)
    elif kind == "union":
        options = specification.get("options")
        if not isinstance(options, (list, tuple)) or len(options) < 2:
            raise _fault(
                INVALID_DECLARATION, "a union argument requires at least two 'options'",
                f"{location}.options", phase, observed={"type": _kind_name(options)},
                recovery="declare each accepted spelling as its own option",
            )
        for index, option in enumerate(options):
            validate_specification(option, f"{location}.options[{index}]", phase=phase)
            if "default" in option or option.get("required", False):
                raise _fault(
                    INVALID_DECLARATION,
                    "a union option declares a spelling, not a default or a requirement",
                    f"{location}.options[{index}]", phase,
                    recovery="declare 'default' and 'required' on the union itself",
                )
    elif kind == "string":
        _bound_pair(specification, "minLength", "maxLength", location, phase)
    elif kind in {"integer", "number"}:
        for key in ("minimum", "maximum"):
            if key in specification and not _finite_number(specification[key]):
                raise _fault(
                    INVALID_DECLARATION, f"'{key}' must be a finite number",
                    f"{location}.{key}", phase, observed={"type": _kind_name(specification[key])},
                )
        for key in ("exclusiveMinimum", "exclusiveMaximum"):
            if key in specification and not isinstance(specification[key], bool):
                raise _fault(
                    INVALID_DECLARATION, f"'{key}' must be a boolean",
                    f"{location}.{key}", phase,
                    observed={"type": _kind_name(specification[key])},
                    recovery="this grammar spells exclusivity as a boolean beside 'minimum'/'maximum'",
                )
        low, high = specification.get("minimum"), specification.get("maximum")
        if _finite_number(low) and _finite_number(high) and low > high:
            raise _fault(
                INVALID_DECLARATION, "'minimum' exceeds 'maximum'", location, phase,
                observed={"minimum": low, "maximum": high},
            )


def _bound_pair(
    specification: Mapping[str, Any], low_key: str, high_key: str, location: str, phase: str
) -> None:
    for key in (low_key, high_key):
        value = specification.get(key)
        if key in specification and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            raise _fault(
                INVALID_DECLARATION, f"'{key}' must be a non-negative integer",
                f"{location}.{key}", phase, observed={"value": json_value(value)},
            )
    low, high = specification.get(low_key), specification.get(high_key)
    if isinstance(low, int) and isinstance(high, int) and low > high:
        raise _fault(
            INVALID_DECLARATION, f"'{low_key}' exceeds '{high_key}'", location, phase,
            observed={low_key: low, high_key: high},
        )


def _valid_name(name: Any, location: str, phase: str) -> str:
    if not isinstance(name, str) or not name or not name[0].isalpha() or not all(
        character.isalnum() or character == "_" for character in name
    ):
        raise _fault(
            INVALID_DECLARATION, f"invalid argument name {name!r}", location, phase,
            observed={"name": name if isinstance(name, str) else _kind_name(name)},
            recovery="names start with a letter and contain letters, digits or underscores",
        )
    return name


def _distinct(values: Iterable[Any]) -> list[Any]:
    seen: list[Any] = []
    for value in values:
        # Membership by value and type: 1 and True are distinct declarations.
        if not any(type(value) is type(item) and value == item for item in seen):
            seen.append(value)
    return seen


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_specifications(
    specifications: Any, location: str, *, phase: str = DECLARATION_PHASE
) -> Mapping[str, Mapping[str, Any]]:
    """Check a whole ``{name: declaration}`` mapping and return it unchanged."""

    if not isinstance(specifications, Mapping):
        raise _fault(
            INVALID_DECLARATION, "declared arguments must be an object", location, phase,
            observed={"type": _kind_name(specifications)},
            recovery="declare an empty object when a capability takes no arguments",
        )
    for name, specification in specifications.items():
        _valid_name(name, location, phase)
        validate_specification(specification, f"{location}.{name}", phase=phase)
    return specifications


# ---------------------------------------------------------------------------
# Value checking
# ---------------------------------------------------------------------------

def validate_value(
    value: Any, specification: Mapping[str, Any], location: str, phase: str = VALIDATION_PHASE
) -> JsonValue:
    """Check one value against one already-checked declaration."""

    kind = specification["type"]
    if kind == "enum":
        if not any(type(value) is type(item) and value == item for item in specification["values"]):
            raise _fault(
                INVALID_ARGUMENT, "value is not one of the declared choices", location, phase,
                observed={"value": _observable(value)},
                recovery=f"use one of: {', '.join(repr(item) for item in specification['values'])}",
            )
        return value
    if kind == "boolean":
        _require(isinstance(value, bool), value, "boolean", location, phase)
        return value
    if kind == "integer":
        _require(isinstance(value, int) and not isinstance(value, bool), value, "integer", location, phase)
        _check_range(value, specification, location, phase)
        return value
    if kind == "number":
        _require(_finite_number(value), value, "finite number", location, phase)
        _check_range(value, specification, location, phase)
        return value
    if kind == "string":
        _require(isinstance(value, str), value, "string", location, phase)
        _check_length(len(value), specification, "minLength", "maxLength", "characters", location, phase)
        return value
    if kind == "union":
        return _validate_union(value, specification, location, phase)
    if kind == "array":
        _require(isinstance(value, (list, tuple)) and not isinstance(value, str), value, "array", location, phase)
        _check_length(len(value), specification, "minItems", "maxItems", "items", location, phase)
        items = specification["items"]
        result = [
            validate_value(item, items, f"{location}[{index}]", phase)
            for index, item in enumerate(value)
        ]
        if specification.get("uniqueItems", False) and len(_distinct(result)) != len(result):
            raise _fault(
                INVALID_ARGUMENT, "array items must be distinct", location, phase,
                observed={"value": _observable(result)},
            )
        return result
    # object
    _require(isinstance(value, Mapping), value, "object", location, phase)
    return _validate_members(specification["properties"], value, location, phase)


def _validate_union(
    value: Any, specification: Mapping[str, Any], location: str, phase: str
) -> JsonValue:
    """Accept the first declared spelling that fits, and say so when none does.

    Several spellings of one intention are safe as long as they resolve to one
    meaning. Options are tried in declaration order, so the most specific
    spelling must be declared first.
    """

    rejections: list[dict[str, JsonValue]] = []
    for option in specification["options"]:
        try:
            return validate_value(value, option, location, phase)
        except SchemaxisError as error:
            rejections.append({
                "spelling": _spelling(option),
                "because": error.fault.message,
                "at": error.fault.location,
            })
    raise _fault(
        INVALID_ARGUMENT, "no declared spelling accepts this value", location, phase,
        observed={"type": _kind_name(value), "value": _observable(value), "rejected": rejections},
        recovery="supply one of: " + "; ".join(str(item["spelling"]) for item in rejections),
    )


def _spelling(option: Mapping[str, Any]) -> str:
    if "title" in option:
        return str(option["title"])
    if option["type"] == "enum":
        return f"one of {', '.join(repr(item) for item in option['values'])}"
    return str(option["type"])


def _validate_members(
    properties: Mapping[str, Mapping[str, Any]],
    value: Mapping[str, Any],
    location: str,
    phase: str,
) -> dict[str, JsonValue]:
    unknown = sorted(set(value) - set(properties))
    if unknown:
        raise _fault(
            UNKNOWN_ARGUMENT, f"unknown properties: {', '.join(unknown)}", location, phase,
            observed={"unknown": unknown, "declared": sorted(properties)},
            recovery=f"declared properties are: {', '.join(sorted(properties)) or '(none)'}",
        )
    result: dict[str, JsonValue] = {}
    for name, specification in properties.items():
        member = f"{location}.{name}"
        if name in value:
            result[name] = validate_value(value[name], specification, member, phase)
        elif "default" in specification:
            result[name] = _detach(specification["default"])
        elif specification.get("required", False):
            raise _fault(
                MISSING_ARGUMENT, f"missing required property {name!r}", member, phase,
                observed={"supplied": sorted(value)},
                recovery=_expectation(specification),
            )
    return result


def _require(condition: bool, value: Any, expected: str, location: str, phase: str) -> None:
    if not condition:
        raise _fault(
            INVALID_ARGUMENT, f"expected a {expected}", location, phase,
            observed={"type": _kind_name(value), "value": _observable(value)},
            recovery=f"supply a {expected}",
        )


def _check_range(value: int | float, specification: Mapping[str, Any], location: str, phase: str) -> None:
    low, high = specification.get("minimum"), specification.get("maximum")
    if _finite_number(low):
        exclusive = specification.get("exclusiveMinimum", False)
        if value < low or (exclusive and value == low):
            raise _fault(
                INVALID_ARGUMENT,
                f"value must be {'greater than' if exclusive else 'at least'} {low}",
                location, phase, observed={"value": value, "minimum": low, "exclusive": exclusive},
            )
    if _finite_number(high):
        exclusive = specification.get("exclusiveMaximum", False)
        if value > high or (exclusive and value == high):
            raise _fault(
                INVALID_ARGUMENT,
                f"value must be {'less than' if exclusive else 'at most'} {high}",
                location, phase, observed={"value": value, "maximum": high, "exclusive": exclusive},
            )


def _check_length(
    size: int, specification: Mapping[str, Any], low_key: str, high_key: str,
    unit: str, location: str, phase: str,
) -> None:
    low, high = specification.get(low_key), specification.get(high_key)
    if isinstance(low, int) and size < low:
        raise _fault(
            INVALID_ARGUMENT, f"expected at least {low} {unit}", location, phase,
            observed={"observed": size, low_key: low},
        )
    if isinstance(high, int) and size > high:
        raise _fault(
            INVALID_ARGUMENT, f"expected at most {high} {unit}", location, phase,
            observed={"observed": size, high_key: high},
        )


def _detach(value: Any) -> JsonValue:
    """Return an owned, mutable, JSON-safe copy of a declared default.

    Declarations are frozen at their boundaries, so a default may arrive as a
    read-only mapping or a tuple. A validated result must never alias one.
    """

    if isinstance(value, Mapping):
        return {str(key): _detach(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_detach(item) for item in value]
    return value


def _observable(value: Any) -> JsonValue:
    """Return a value safe to embed in a fault, never a live object."""

    try:
        return json_value(value)
    except TypeError:
        return f"<{type(value).__name__}>"


def _expectation(specification: Mapping[str, Any]) -> str:
    kind = specification["type"]
    if kind == "enum":
        return f"supply one of: {', '.join(repr(item) for item in specification['values'])}"
    return f"supply a {kind}"


def validate_arguments(
    specifications: Mapping[str, Any],
    values: Any,
    *,
    location: str = "$.arguments",
    phase: str = VALIDATION_PHASE,
    check_specifications: bool = True,
) -> dict[str, JsonValue]:
    """Validate supplied values, apply declared defaults, and return a copy.

    This is the single path. A document argument, a CLI-derived argument and an
    in-code extension argument all arrive here, so they cannot disagree about
    what is accepted or what a missing value defaults to.
    """

    if check_specifications:
        validate_specifications(specifications, location, phase=DECLARATION_PHASE)
    if not isinstance(values, Mapping):
        raise _fault(
            INVALID_ARGUMENT, "arguments must be an object", location, phase,
            observed={"type": _kind_name(values)},
        )
    return _validate_members(specifications, values, location, phase)


def describe_arguments(specifications: Mapping[str, Any]) -> dict[str, JsonValue]:
    """Return a canonical JSON description of declared arguments.

    This is what makes an in-code declaration statically publishable: the same
    dictionary an implementer wrote beside their class can be exported to a
    manifest and compared against it, without importing the implementation at
    read time.
    """

    return {name: json_value(specification) for name, specification in sorted(specifications.items())}
