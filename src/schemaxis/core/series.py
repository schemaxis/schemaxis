"""Resolution of a declared linear series into explicit positions.

A slice sweep, a camera sweep and a sample line are all the same declaration:
some subset of ``start``, ``end``, ``spacing`` and ``count``, possibly leaning
on the bounds of the thing being swept. Several spellings are accepted, but
they all resolve to exactly one canonical answer, and the answer carries the
record of which numbers the caller declared and which Schemaxis derived.

That record is the point. Accepting many spellings is only safe when the
resolved meaning is reported back, because then a caller can see that the
series it got is the series it meant.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

from .contracts import JsonValue
from .declarations import validate_value
from .faults import SchemaxisError, Fault


UNDER_SPECIFIED_SERIES = "UNDER_SPECIFIED_SERIES"
OVER_SPECIFIED_SERIES = "OVER_SPECIFIED_SERIES"
INCONSISTENT_SERIES = "INCONSISTENT_SERIES"
BOUNDS_REQUIRED = "BOUNDS_REQUIRED"

RESOLUTION_PHASE = "value-resolution"

# The four ways to pin a series down, in the order a fault should offer them.
COMBINATIONS = (
    ("start", "spacing", "end"),
    ("start", "spacing", "count"),
    ("spacing", "count", "end"),
    ("start", "count", "end"),
)

#: A declaration fragment in the closed grammar of :mod:`schemaxis.core.declarations`.
#: Every member is optional because the valid combinations are alternatives;
#: which ones are present is checked here, where a useful fault can be raised.
SERIES_ARGUMENT: Mapping[str, Any] = {
    "type": "object",
    "title": "Linear series",
    "summary": "Positions along an axis, given as any three of start, end, spacing and count",
    "properties": {
        "start": {"type": "number", "summary": "First position; defaults to the padded lower bound"},
        "end": {"type": "number", "summary": "Last position; defaults to the padded upper bound"},
        "spacing": {"type": "number", "summary": "Distance between consecutive positions"},
        "count": {"type": "integer", "minimum": 1, "summary": "Number of positions"},
        "padding": {
            "type": "number", "minimum": 0,
            "summary": "Absolute inset applied to bounds-derived ends only",
        },
        "paddingFraction": {
            "type": "number", "minimum": 0, "maximum": 0.5,
            "summary": "Inset as a fraction of the bounds extent, applied to bounds-derived ends only",
        },
    },
}

_QUANTITIES = ("start", "end", "spacing", "count")
_TOLERANCE = 1e-9


@dataclass(frozen=True, slots=True)
class ResolvedSeries:
    """One canonical series plus the evidence of how it was arrived at."""

    positions: tuple[float, ...]
    start: float
    end: float
    spacing: float
    count: int
    #: For each quantity: ``declared``, ``derived`` or ``bounds``.
    sources: Mapping[str, str]
    #: Human-readable statements about anything Schemaxis decided on its own.
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "positions": list(self.positions),
            "start": self.start,
            "end": self.end,
            "spacing": self.spacing,
            "count": self.count,
            "sources": dict(self.sources),
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


def _combinations_text() -> str:
    return "; ".join(" + ".join(names) for names in COMBINATIONS)


def resolve_series(
    declared: Mapping[str, Any],
    *,
    bounds: Sequence[float] | None = None,
    location: str = "$.series",
    limit: int | None = None,
) -> ResolvedSeries:
    """Resolve a declared series against optional ``(minimum, maximum)`` bounds."""

    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("series limit must be a positive integer")
    values = validate_value(declared, SERIES_ARGUMENT, location, RESOLUTION_PHASE)
    known: dict[str, float] = {name: values[name] for name in _QUANTITIES if name in values}
    sources = {name: "declared" for name in known}
    notes: list[str] = []

    if len(known) == 4:
        raise _fault(
            OVER_SPECIFIED_SERIES,
            "start, end, spacing and count were all declared; three of them fix the fourth",
            location, observed={name: known[name] for name in _QUANTITIES},
            recovery=f"declare exactly three of: {_combinations_text()}",
        )

    low, high = _padded_bounds(values, bounds, location, notes)
    # Fill from bounds only while a quantity is still missing, so a caller who
    # declared spacing and count gets an end derived from them, not from the
    # geometry.
    for name, value in (("start", low), ("end", high)):
        if len(known) >= 3:
            break
        if name not in known and value is not None:
            known[name] = value
            sources[name] = "bounds"

    if known.get("count") == 1 and ("start" in known) != ("end" in known):
        # One position is fully determined by where it goes; spacing is moot.
        anchor = float(known.get("start", known.get("end")))
        missing = "end" if "start" in known else "start"
        sources[missing] = "derived"
        sources["spacing"] = "derived"
        return ResolvedSeries(
            positions=(anchor,), start=anchor, end=anchor, spacing=0.0, count=1,
            sources=dict(sorted(sources.items())), notes=tuple(notes),
        )

    if len(known) < 3:
        raise _fault(
            UNDER_SPECIFIED_SERIES,
            "the series is not determined by what was declared",
            location,
            observed={"declared": sorted(values), "resolved": sorted(known),
                      "boundsSupplied": bounds is not None},
            recovery=f"declare enough of: {_combinations_text()}"
                     + ("" if bounds is not None else ", or supply bounds for the swept object"),
        )

    resolved = _solve(known, sources, location, notes)
    if limit is not None and resolved["count"] > limit:
        raise _fault("EXPANSION_TOO_LARGE", "the series exceeds the declared position limit", location,
                     observed={"count": resolved["count"], "limit": limit},
                     recovery="reduce the count or increase the position limit deliberately")
    if not all(math.isfinite(value) for value in resolved.values()):
        raise _fault(INCONSISTENT_SERIES, "resolved series values must be finite", location,
                     recovery="use a smaller finite extent or spacing")
    positions = tuple(
        resolved["start"] + index * resolved["spacing"] for index in range(int(resolved["count"]))
    )
    if not all(math.isfinite(position) for position in positions):
        raise _fault(INCONSISTENT_SERIES, "resolved positions must be finite", location,
                     recovery="use a smaller finite extent or spacing")
    return ResolvedSeries(
        positions=positions,
        start=positions[0],
        end=positions[-1],
        spacing=float(resolved["spacing"]),
        count=len(positions),
        sources=dict(sorted(sources.items())),
        notes=tuple(notes),
    )


def _padded_bounds(
    values: Mapping[str, Any],
    bounds: Sequence[float] | None,
    location: str,
    notes: list[str],
) -> tuple[float | None, float | None]:
    """Return the inward-padded bounds, or ``(None, None)`` when none were given.

    Padding is applied only to bounds-derived ends. A position placed exactly on
    the geometry's boundary frequently renders as nothing at all, and a caller
    who declared an end explicitly meant that end.
    """

    padding = values.get("padding")
    fraction = values.get("paddingFraction")
    if padding is not None and fraction is not None:
        raise _fault(
            INCONSISTENT_SERIES, "padding and paddingFraction are alternatives", location,
            observed={"padding": padding, "paddingFraction": fraction},
            recovery="declare padding as an absolute distance or paddingFraction of the extent, not both",
        )
    if bounds is None:
        if padding is not None or fraction is not None:
            notes.append("padding was declared but no bounds were supplied, so nothing was padded")
        return None, None

    if len(bounds) != 2 or not all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in bounds):
        raise _fault(
            INCONSISTENT_SERIES, "bounds must be a (minimum, maximum) pair of numbers", location,
            observed={"bounds": list(bounds)},
        )
    low, high = float(bounds[0]), float(bounds[1])
    if low > high:
        low, high = high, low
        notes.append("supplied bounds were inverted and were read as (minimum, maximum)")
    inset = 0.0
    if padding is not None:
        inset = float(padding)
    elif fraction is not None:
        inset = float(fraction) * (high - low)
    if inset > 0:
        if 2 * inset >= high - low:
            raise _fault(
                INCONSISTENT_SERIES, "padding consumes the whole extent of the bounds", location,
                observed={"bounds": [low, high], "padding": inset},
                recovery=f"declare a padding below {(high - low) / 2}",
            )
        low, high = low + inset, high - inset
        notes.append(f"bounds-derived ends were inset by {inset} to {low} .. {high}")
    return low, high


def _solve(
    known: Mapping[str, float], sources: dict[str, str], location: str, notes: list[str]
) -> dict[str, float]:
    resolved = dict(known)
    missing = [name for name in _QUANTITIES if name not in resolved]
    if len(missing) != 1:
        raise _fault(
            INCONSISTENT_SERIES, "the declared series does not determine exactly one unknown",
            location, observed={"known": sorted(resolved), "missing": missing},
            recovery=f"declare exactly three of: {_combinations_text()}",
        )
    unknown = missing[0]

    if "count" in resolved and resolved["count"] < 1:
        raise _fault(
            INCONSISTENT_SERIES, "a series needs at least one position", location,
            observed={"count": resolved["count"]},
        )

    if unknown == "count":
        span = resolved["end"] - resolved["start"]
        spacing = _oriented_spacing(resolved["spacing"], span, location, notes)
        resolved["spacing"] = spacing
        if spacing == 0:
            raise _fault(
                INCONSISTENT_SERIES, "a spacing of zero cannot span the declared ends", location,
                observed={"start": resolved["start"], "end": resolved["end"]},
                recovery="declare a non-zero spacing, or declare count instead",
            )
        quotient = abs(span) / abs(spacing)
        if not math.isfinite(quotient):
            raise _fault(INCONSISTENT_SERIES, "series span/spacing exceeds finite arithmetic", location,
                         recovery="reduce the extent or increase the spacing")
        steps = int(quotient + _TOLERANCE)
        resolved["count"] = steps + 1
        reached = resolved["start"] + steps * spacing
        if abs(reached - resolved["end"]) > abs(spacing) * _TOLERANCE:
            notes.append(
                f"the last position is {reached}; the declared end {resolved['end']} "
                f"is not an exact multiple of the spacing {spacing} from the start"
            )
    elif unknown == "end":
        resolved["end"] = resolved["start"] + resolved["spacing"] * (resolved["count"] - 1)
    elif unknown == "start":
        resolved["start"] = resolved["end"] - resolved["spacing"] * (resolved["count"] - 1)
    else:  # spacing
        if resolved["count"] == 1:
            if resolved["end"] != resolved["start"]:
                raise _fault(
                    INCONSISTENT_SERIES,
                    "a series of one position cannot span distinct ends", location,
                    observed={
                        "start": resolved["start"], "end": resolved["end"], "count": 1,
                        "sources": dict(sorted(sources.items())),
                    },
                    recovery="declare count of at least 2, or declare exactly one of start "
                             "and end so the single position is unambiguous",
                )
            resolved["spacing"] = 0.0
        else:
            resolved["spacing"] = (resolved["end"] - resolved["start"]) / (resolved["count"] - 1)

    sources[unknown] = "derived"
    return resolved


def _oriented_spacing(spacing: float, span: float, location: str, notes: list[str]) -> float:
    """Point the spacing along the declared span, saying so when it is flipped."""

    if spacing == 0 or span == 0:
        return float(spacing)
    if (spacing < 0) != (span < 0):
        notes.append(
            f"the declared spacing {spacing} pointed away from the declared end; "
            f"it was read as {-spacing}"
        )
        return -float(spacing)
    return float(spacing)
