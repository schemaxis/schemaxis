"""Deterministic expansion of nested iteration into an ordered visit list.

Producing a set of images from a case is a nest of loops: times, then views,
then the positions a swept object takes, then how it is coloured, then the
writers. The order matters for cost, not only for tidiness. Rebuilding geometry
is expensive, recolouring is cheap, so the expensive axis belongs outside the
cheap one, and a provider needs to know, at each step, which axes actually
changed so it can move a slice instead of building a new one.

This module supplies exactly that and nothing else: axes are given outermost
first, and each visit reports its coordinates and which axes advanced to reach
it. It knows nothing about what an axis means.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Any, Callable, Iterator, Mapping, Sequence

from .contracts import JsonValue, json_value
from .faults import SchemaxisError, Fault


EMPTY_ITERATION_AXIS = "EMPTY_ITERATION_AXIS"
DUPLICATE_ITERATION_AXIS = "DUPLICATE_ITERATION_AXIS"
INVALID_ITERATION_AXIS = "INVALID_ITERATION_AXIS"
EXPANSION_TOO_LARGE = "EXPANSION_TOO_LARGE"

EXPANSION_PHASE = "expansion"


def _fault(
    code: str, message: str, location: str, *,
    observed: Mapping[str, Any] | None = None, recovery: str | None = None,
) -> SchemaxisError:
    return SchemaxisError(Fault(
        code=code, message=message, location=location, phase=EXPANSION_PHASE,
        observed=observed or {}, recovery=recovery,
    ))


def _default_label(index: int, item: Any, width: int) -> str:
    if isinstance(item, str) and item:
        return item
    return str(index).rjust(width, "0")


@dataclass(frozen=True, slots=True)
class Axis:
    """One level of the nest: a name and the values it takes, in order."""

    name: str
    items: tuple[Any, ...]
    labels: tuple[str, ...]

    @classmethod
    def of(
        cls,
        name: str,
        items: Sequence[Any],
        *,
        labels: Sequence[str] | None = None,
        label: Callable[[int, Any], str] | None = None,
        location: str = "$.axes",
    ) -> "Axis":
        if not isinstance(name, str) or not name:
            raise _fault(
                INVALID_ITERATION_AXIS, "an axis needs a non-empty name", location,
                observed={"name": repr(name)},
            )
        where = f"{location}.{name}"
        if isinstance(items, str) or not isinstance(items, Sequence):
            raise _fault(
                INVALID_ITERATION_AXIS, f"axis {name!r} must be given a sequence of values", where,
                observed={"type": type(items).__name__},
            )
        if not items:
            # A zero-length axis multiplies the whole expansion to nothing. That
            # is a request that produces no output, not a successful production
            # of no output, so it fails here rather than silently later.
            raise _fault(
                EMPTY_ITERATION_AXIS, f"axis {name!r} has no values", where,
                observed={"axis": name},
                recovery=f"give {name!r} at least one value, or leave the axis out entirely",
            )
        width = len(str(len(items) - 1))
        if labels is not None:
            resolved = tuple(str(item) for item in labels)
            if len(resolved) != len(items):
                raise _fault(
                    INVALID_ITERATION_AXIS,
                    f"axis {name!r} was given {len(resolved)} labels for {len(items)} values",
                    where, observed={"labels": len(resolved), "values": len(items)},
                )
        elif label is not None:
            resolved = tuple(str(label(index, item)) for index, item in enumerate(items))
        else:
            resolved = tuple(_default_label(index, item, width) for index, item in enumerate(items))
        if len(set(resolved)) != len(resolved):
            raise _fault(
                INVALID_ITERATION_AXIS, f"axis {name!r} has repeated labels", where,
                observed={"labels": list(resolved)},
                recovery="labels name an output, so they must be distinct within an axis",
            )
        return cls(name, tuple(items), resolved)

    def __len__(self) -> int:
        return len(self.items)


@dataclass(frozen=True, slots=True)
class Visit:
    """One leaf of the nest, and what it took to get there."""

    ordinal: int
    coordinates: Mapping[str, Any]
    labels: Mapping[str, str]
    positions: Mapping[str, int]
    #: Axes that advanced on entering this visit, outermost first. The first
    #: visit reports every axis, because everything had to be established.
    changed: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("coordinates", "labels", "positions"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    @property
    def key(self) -> str:
        """A stable, ordered identity for this visit's outputs."""

        return "/".join(f"{name}={label}" for name, label in self.labels.items())

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "ordinal": self.ordinal,
            "key": self.key,
            "labels": dict(self.labels),
            "positions": dict(self.positions),
            "changed": list(self.changed),
            "coordinates": json_value(dict(self.coordinates)),
        }


def _checked_axes(axes: Sequence[Axis], location: str) -> tuple[Axis, ...]:
    seen: dict[str, int] = {}
    for index, axis in enumerate(axes):
        if not isinstance(axis, Axis):
            raise _fault(
                INVALID_ITERATION_AXIS, "every axis must be an Axis", f"{location}[{index}]",
                observed={"type": type(axis).__name__},
                recovery="build axes with Axis.of(name, values)",
            )
        if axis.name in seen:
            raise _fault(
                DUPLICATE_ITERATION_AXIS,
                f"axis {axis.name!r} is declared at depths {seen[axis.name]} and {index}",
                f"{location}[{index}]", observed={"axis": axis.name},
                recovery="axis names identify a coordinate, so they must be distinct",
            )
        seen[axis.name] = index
        if not axis.items:
            raise _fault(
                EMPTY_ITERATION_AXIS, f"axis {axis.name!r} has no values",
                f"{location}[{index}]", observed={"axis": axis.name},
            )
    return tuple(axes)


def count_visits(axes: Sequence[Axis]) -> int:
    """The size of the expansion, without building it."""

    return math.prod(len(axis) for axis in axes) if axes else 1


def iter_visits(
    axes: Sequence[Axis], *, limit: int | None = None, location: str = "$.axes"
) -> Iterator[Visit]:
    """Yield every leaf of the nest, outermost axis varying slowest."""

    checked = _checked_axes(axes, location)
    total = count_visits(checked)
    if limit is not None and total > limit:
        raise _fault(
            EXPANSION_TOO_LARGE,
            f"the declared nest expands to {total} visits, above the limit of {limit}",
            location,
            observed={
                "visits": total, "limit": limit,
                "axes": {axis.name: len(axis) for axis in checked},
            },
            recovery="narrow an axis, or raise the declared limit deliberately",
        )

    if not checked:
        # No axes is one visit with no coordinates, not zero visits: a single
        # unparameterised production is still a production.
        yield Visit(0, {}, {}, {}, ())
        return

    positions = [0] * len(checked)
    for ordinal in range(total):
        remainder = ordinal
        for depth in reversed(range(len(checked))):
            positions[depth] = remainder % len(checked[depth])
            remainder //= len(checked[depth])
        if ordinal == 0:
            changed = tuple(axis.name for axis in checked)
        else:
            # An axis advanced exactly when every axis inside it has wrapped.
            deepest = len(checked) - 1
            while deepest > 0 and positions[deepest] == 0:
                deepest -= 1
            changed = tuple(axis.name for axis in checked[deepest:])
        yield Visit(
            ordinal=ordinal,
            coordinates={axis.name: axis.items[positions[depth]] for depth, axis in enumerate(checked)},
            labels={axis.name: axis.labels[positions[depth]] for depth, axis in enumerate(checked)},
            positions={axis.name: positions[depth] for depth, axis in enumerate(checked)},
            changed=changed,
        )


def expand(
    axes: Sequence[Axis], *, limit: int | None = None, location: str = "$.axes"
) -> tuple[Visit, ...]:
    """Materialise the whole ordered visit list."""

    return tuple(iter_visits(axes, limit=limit, location=location))
