# Copyright (C) 2026 David L F Gaden
"""Selection of time values from those an application actually has.

A CFD case stores each field at a set of times. A declaration names the times
it wants — the latest, the first few, some values, a range, some indices — and
this module resolves that against the times that exist.

Two rules follow from Schemaxis's governing value. A requested value that does not
exist is matched to the nearest one that does, and the difference is reported
rather than hidden. A request that selects no times at all is a fault, because
producing nothing is not a successful production of nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .contracts import JsonValue
from .declarations import validate_value
from .faults import SchemaxisError, Fault


NO_TIMES_AVAILABLE = "NO_TIMES_AVAILABLE"
EMPTY_TIME_SELECTION = "EMPTY_TIME_SELECTION"
INVALID_TIME_INDEX = "INVALID_TIME_INDEX"
TIME_OUT_OF_TOLERANCE = "TIME_OUT_OF_TOLERANCE"
UNDER_SPECIFIED_TIMES = "UNDER_SPECIFIED_TIMES"
OVER_SPECIFIED_TIMES = "OVER_SPECIFIED_TIMES"

RESOLUTION_PHASE = "value-resolution"

_SELECTORS = ("latest", "first", "values", "valueRange", "indices", "indexRange")

#: A declaration fragment in the closed grammar of :mod:`schemaxis.core.declarations`.
TIMES_ARGUMENT: Mapping[str, Any] = {
    "type": "union",
    "title": "time selection",
    "summary": "Which stored times to process",
    "options": [
        {"type": "enum", "title": "'latest' or 'first'", "values": ["latest", "first"]},
        {
            "type": "object",
            "title": "time selection object",
            "properties": {
                "latest": {"type": "integer", "minimum": 1, "summary": "The last n stored times"},
                "first": {"type": "integer", "minimum": 1, "summary": "The first n stored times"},
                "values": {
                    "type": "array", "items": {"type": "number"}, "minItems": 1,
                    "summary": "Nearest stored time to each value",
                },
                "valueRange": {
                    "type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2,
                    "summary": "Every stored time within an inclusive range of values",
                },
                "indices": {
                    "type": "array", "items": {"type": "integer", "minimum": 0}, "minItems": 1,
                    "summary": "Stored times by position",
                },
                "indexRange": {
                    "type": "array", "items": {"type": "integer", "minimum": 0},
                    "minItems": 2, "maxItems": 2,
                    "summary": "Every stored time within an inclusive range of positions",
                },
                "tolerance": {
                    "type": "number", "minimum": 0,
                    "summary": "Largest accepted difference between a requested and a stored value",
                },
            },
        },
    ],
}


@dataclass(frozen=True, slots=True)
class SelectedTime:
    """One stored time, with the request it answers when there was one."""

    index: int
    value: float
    requested: float | None = None

    @property
    def difference(self) -> float | None:
        return None if self.requested is None else self.value - self.requested

    def to_dict(self) -> dict[str, JsonValue]:
        value: dict[str, JsonValue] = {"index": self.index, "value": self.value}
        if self.requested is not None:
            value["requested"] = self.requested
            value["difference"] = self.difference
        return value


@dataclass(frozen=True, slots=True)
class TimeSelection:
    times: tuple[SelectedTime, ...]
    spelling: str
    notes: tuple[str, ...] = ()

    @property
    def values(self) -> tuple[float, ...]:
        return tuple(item.value for item in self.times)

    @property
    def indices(self) -> tuple[int, ...]:
        return tuple(item.index for item in self.times)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "times": [item.to_dict() for item in self.times],
            "spelling": self.spelling,
            "notes": list(self.notes),
        }


def _fault(
    code: str, message: str, location: str, *,
    observed: Mapping[str, Any] | None = None, recovery: str | None = None,
) -> SchemaxisError:
    return SchemaxisError(Fault(
        code=code, message=message, location=location, phase=RESOLUTION_PHASE,
        observed=observed or {}, recovery=recovery,
    ))


def resolve_times(
    declared: Any,
    available: Sequence[float],
    *,
    location: str = "$.times",
) -> TimeSelection:
    """Resolve a declared time selection against the times an application has.

    ``available`` is indexed as supplied; positions in ``indices`` and
    ``indexRange`` address that ordering.
    """

    value = validate_value(declared, TIMES_ARGUMENT, location, RESOLUTION_PHASE)
    if isinstance(value, str):
        value = {value: 1}

    stored = _stored_times(available, location)
    notes: list[str] = []
    if [item.value for item in stored] != sorted(item.value for item in stored):
        notes.append("the supplied times were not in ascending order; indices address them as supplied")

    declared_selectors = [name for name in _SELECTORS if name in value]
    if not declared_selectors:
        raise _fault(
            UNDER_SPECIFIED_TIMES, "no times were selected", location,
            observed={"supplied": sorted(value)},
            recovery="declare one of: " + ", ".join(_SELECTORS),
        )
    if len(declared_selectors) > 1:
        raise _fault(
            OVER_SPECIFIED_TIMES,
            f"times were selected in {len(declared_selectors)} ways at once", location,
            observed={"spellings": declared_selectors},
            recovery="declare exactly one of: " + ", ".join(_SELECTORS),
        )

    spelling = declared_selectors[0]
    tolerance = value.get("tolerance")
    if tolerance is not None and spelling not in {"values", "valueRange"}:
        notes.append(f"a tolerance was declared but {spelling} does not approximate anything")

    selected = _select(spelling, value, stored, tolerance, location, notes)
    if not selected:
        raise _fault(
            EMPTY_TIME_SELECTION, "the declared selection matched no stored time", location,
            observed={
                "spelling": spelling, "declared": _observable_selector(value, spelling),
                "storedValues": [item.value for item in stored],
            },
            recovery=f"stored times run from {stored[0].value} to {stored[-1].value} "
                     f"across {len(stored)} positions",
        )

    ordered = _deduplicate(selected, notes)
    return TimeSelection(tuple(ordered), spelling, tuple(notes))


def _stored_times(available: Sequence[float], location: str) -> list[SelectedTime]:
    if not isinstance(available, Sequence) or isinstance(available, str) or not available:
        raise _fault(
            NO_TIMES_AVAILABLE, "the resource has no stored times", location,
            observed={"count": 0 if not available else len(available)},
            recovery="open a case that has written at least one time",
        )
    stored: list[SelectedTime] = []
    for index, item in enumerate(available):
        if not isinstance(item, (int, float)) or isinstance(item, bool):
            raise _fault(
                NO_TIMES_AVAILABLE, "stored times must be numbers", f"{location}[{index}]",
                observed={"value": repr(item)},
            )
        stored.append(SelectedTime(index, float(item)))
    return stored


def _select(
    spelling: str,
    value: Mapping[str, Any],
    stored: list[SelectedTime],
    tolerance: float | None,
    location: str,
    notes: list[str],
) -> list[SelectedTime]:
    ascending = sorted(stored, key=lambda item: item.value)

    if spelling in {"latest", "first"}:
        wanted = int(value[spelling])
        if wanted > len(stored):
            notes.append(
                f"{wanted} {spelling} times were requested but only {len(stored)} are stored"
            )
        wanted = min(wanted, len(stored))
        return ascending[-wanted:] if spelling == "latest" else ascending[:wanted]

    if spelling == "values":
        return [
            _nearest(requested, ascending, tolerance, f"{location}.values[{position}]", notes)
            for position, requested in enumerate(value["values"])
        ]

    if spelling == "valueRange":
        low, high = sorted(float(item) for item in value["valueRange"])
        if tolerance:
            low, high = low - tolerance, high + tolerance
        return [item for item in ascending if low <= item.value <= high]

    if spelling == "indices":
        return [_at_index(int(item), stored, f"{location}.indices[{position}]")
                for position, item in enumerate(value["indices"])]

    low_index, high_index = sorted(int(item) for item in value["indexRange"])
    if low_index >= len(stored) or high_index < 0:
        return []
    if high_index >= len(stored):
        notes.append(
            f"the requested index range ended at {high_index} but the last stored "
            f"position is {len(stored) - 1}; the range was shortened"
        )
        high_index = len(stored) - 1
    return sorted(stored[low_index:high_index + 1], key=lambda item: item.value)


def _nearest(
    requested: float,
    ascending: list[SelectedTime],
    tolerance: float | None,
    location: str,
    notes: list[str],
) -> SelectedTime:
    """Match a requested value to the nearest stored one, saying how near."""

    best = min(ascending, key=lambda item: (abs(item.value - requested), item.value))
    difference = abs(best.value - requested)
    if difference == 0:
        return SelectedTime(best.index, best.value)
    if tolerance is not None and difference > tolerance:
        raise _fault(
            TIME_OUT_OF_TOLERANCE,
            f"no stored time is within {tolerance} of {requested}", location,
            observed={"requested": requested, "nearest": best.value, "difference": difference},
            recovery=f"declare a tolerance of at least {difference}, or request {best.value}",
        )
    notes.append(
        f"no time {requested} is stored; the nearest stored time {best.value} "
        f"at position {best.index} was selected, differing by {difference}"
    )
    return SelectedTime(best.index, best.value, requested)


def _at_index(index: int, stored: list[SelectedTime], location: str) -> SelectedTime:
    """An index is an address, not an approximation, so a wrong one is a fault."""

    if index >= len(stored):
        raise _fault(
            INVALID_TIME_INDEX, f"there is no stored time at position {index}", location,
            observed={"index": index, "storedCount": len(stored)},
            recovery=f"positions run from 0 to {len(stored) - 1}",
        )
    return stored[index]


def _deduplicate(selected: list[SelectedTime], notes: list[str]) -> list[SelectedTime]:
    by_index: dict[int, SelectedTime] = {}
    for item in selected:
        # An earlier entry that recorded an approximation is kept over a bare
        # repeat, so the evidence of what was asked for survives.
        if item.index not in by_index or by_index[item.index].requested is None:
            by_index[item.index] = item
    if len(by_index) != len(selected):
        notes.append(
            f"{len(selected)} requests resolved to {len(by_index)} distinct stored times"
        )
    return sorted(by_index.values(), key=lambda item: (item.value, item.index))


def _observable_selector(value: Mapping[str, Any], spelling: str) -> JsonValue:
    selector = value[spelling]
    return list(selector) if isinstance(selector, (list, tuple)) else selector
