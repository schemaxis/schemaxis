"""Resolution of a declared direction into a canonical frame.

A direction can be spelled as an axis token (``x+``), as a vector, or as an
azimuth and elevation about an ``up`` axis. All three resolve to the same
canonical answer: a unit direction, the ``up`` it was resolved against, and a
view-up perpendicular to the direction, which is what a camera actually needs.

The resolved answer also reports the azimuth and elevation of whatever was
supplied, so a caller can see the direction it asked for expressed in the other
spelling, and catch a sign or handedness mistake before it reaches an image.

Conventions, stated because they cannot be inferred:

- ``up`` defaults to ``z+``.
- Azimuth is measured about ``up``, anticlockwise seen from the ``up`` side,
  starting from the reference axis (``x+``, or ``y+`` when ``up`` is along x).
- Elevation tilts from the plane perpendicular to ``up`` towards ``up``.
- The resolved vector is the direction a viewer faces, not the position of a
  camera. Placing a camera along it is the writer's business.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

from .contracts import JsonValue
from .declarations import validate_value
from .faults import SchemaxisError, Fault


UNDER_SPECIFIED_DIRECTION = "UNDER_SPECIFIED_DIRECTION"
OVER_SPECIFIED_DIRECTION = "OVER_SPECIFIED_DIRECTION"
UNKNOWN_AXIS_TOKEN = "UNKNOWN_AXIS_TOKEN"
DEGENERATE_DIRECTION = "DEGENERATE_DIRECTION"

RESOLUTION_PHASE = "value-resolution"

_AXES = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}
_NEGLIGIBLE = 1e-9


def _axis_tokens() -> dict[str, tuple[float, float, float]]:
    tokens: dict[str, tuple[float, float, float]] = {}
    for name, vector in _AXES.items():
        negated = tuple(-component for component in vector)
        for token in (name, f"{name}+", f"{name}p", f"+{name}"):
            tokens[token] = vector
        for token in (f"{name}-", f"{name}m", f"-{name}"):
            tokens[token] = negated
    return tokens


AXIS_TOKENS = _axis_tokens()

_VECTOR_ARGUMENT: Mapping[str, Any] = {
    "type": "array",
    "title": "vector [x, y, z]",
    "items": {"type": "number"},
    "minItems": 3,
    "maxItems": 3,
}

#: An ``up`` may be spelled as an axis token or a vector, but never as another
#: azimuth and elevation: that would need an ``up`` of its own.
UP_ARGUMENT: Mapping[str, Any] = {
    "type": "union",
    "title": "up direction",
    "options": [{"type": "string", "title": "axis token such as 'z+'"}, _VECTOR_ARGUMENT],
}

#: A declaration fragment in the closed grammar of :mod:`schemaxis.core.declarations`.
DIRECTION_ARGUMENT: Mapping[str, Any] = {
    "type": "union",
    "title": "direction",
    "summary": "An axis token, a vector, or an azimuth and elevation about an up axis",
    "options": [
        {"type": "string", "title": "axis token such as 'x+' or 'z-'"},
        _VECTOR_ARGUMENT,
        {
            "type": "object",
            "title": "direction object",
            "properties": {
                "axis": {"type": "string", "summary": "Axis token such as 'x+'"},
                "azimuth": {
                    "type": "number", "minimum": -360, "maximum": 360,
                    "summary": "Degrees about the up axis from the reference axis",
                },
                "elevation": {
                    "type": "number", "minimum": -180, "maximum": 180,
                    "summary": "Degrees tilted from the plane perpendicular to up",
                },
                "vector": _VECTOR_ARGUMENT,
                "up": UP_ARGUMENT,
            },
        },
    ],
}


@dataclass(frozen=True, slots=True)
class ResolvedDirection:
    """One canonical direction plus the evidence of how it was arrived at."""

    vector: tuple[float, float, float]
    up: tuple[float, float, float]
    #: Perpendicular to ``vector``; what a camera needs and ``up`` may not be.
    view_up: tuple[float, float, float]
    azimuth: float
    elevation: float
    #: ``axis``, ``vector`` or ``azimuth-elevation``.
    spelling: str
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "vector": list(self.vector),
            "up": list(self.up),
            "viewUp": list(self.view_up),
            "azimuth": self.azimuth,
            "elevation": self.elevation,
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


def _normalise(vector: Sequence[float], location: str, role: str) -> tuple[float, float, float]:
    length = math.sqrt(sum(component * component for component in vector))
    if not math.isfinite(length) or length < _NEGLIGIBLE:
        raise _fault(
            DEGENERATE_DIRECTION, f"the {role} has no length", location,
            observed={"vector": [float(component) for component in vector]},
            recovery=f"supply a {role} with a non-zero length",
        )
    return tuple(float(component) / length for component in vector)  # type: ignore[return-value]


def _cross(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _combine(*terms: tuple[float, Sequence[float]]) -> tuple[float, float, float]:
    return tuple(  # type: ignore[return-value]
        sum(scale * vector[axis] for scale, vector in terms) for axis in range(3)
    )


def resolve_axis_token(token: str, location: str) -> tuple[float, float, float]:
    """Resolve ``x``, ``x+``, ``xp``, ``+x``, ``x-``, ``xm`` or ``-x``."""

    key = token.strip().lower() if isinstance(token, str) else token
    if key not in AXIS_TOKENS:
        raise _fault(
            UNKNOWN_AXIS_TOKEN, f"unknown axis token {token!r}", location,
            observed={"token": token},
            recovery="use one of: " + ", ".join(sorted(AXIS_TOKENS)),
        )
    return AXIS_TOKENS[key]


def resolve_up(declared: Any, location: str = "$.up") -> tuple[float, float, float]:
    value = validate_value(declared, UP_ARGUMENT, location, RESOLUTION_PHASE)
    if isinstance(value, str):
        return resolve_axis_token(value, location)
    return _normalise(value, location, "up direction")


def _reference_frame(
    up: tuple[float, float, float]
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Return (forward, right) spanning the plane perpendicular to ``up``."""

    seed = _AXES["x"] if abs(_dot(up, _AXES["x"])) < 0.9 else _AXES["y"]
    forward = _combine((1.0, seed), (-_dot(seed, up), up))
    length = math.sqrt(_dot(forward, forward))
    forward = tuple(component / length for component in forward)  # type: ignore[assignment]
    return forward, _cross(up, forward)


def resolve_direction(declared: Any, *, location: str = "$.direction") -> ResolvedDirection:
    """Resolve any declared spelling of a direction into one canonical frame."""

    value = validate_value(declared, DIRECTION_ARGUMENT, location, RESOLUTION_PHASE)
    if isinstance(value, str):
        value = {"axis": value}
    elif isinstance(value, list):
        value = {"vector": value}

    notes: list[str] = []
    up = resolve_up(value["up"], f"{location}.up") if "up" in value else _AXES["z"]
    forward, right = _reference_frame(up)

    families = [
        name for name in ("axis", "vector") if name in value
    ] + (["azimuth-elevation"] if {"azimuth", "elevation"} & set(value) else [])
    if not families:
        raise _fault(
            UNDER_SPECIFIED_DIRECTION, "no direction was declared", location,
            observed={"supplied": sorted(value)},
            recovery="declare an axis token, a vector, or an azimuth and elevation",
        )
    if len(families) > 1:
        raise _fault(
            OVER_SPECIFIED_DIRECTION,
            f"the direction was declared in {len(families)} ways at once", location,
            observed={"spellings": families},
            recovery="declare exactly one of: axis, vector, azimuth and elevation",
        )

    spelling = families[0]
    if spelling == "axis":
        vector = resolve_axis_token(value["axis"], f"{location}.axis")
    elif spelling == "vector":
        vector = _normalise(value["vector"], f"{location}.vector", "direction")
    else:
        for name in ("azimuth", "elevation"):
            if name not in value:
                notes.append(f"{name} was not declared and was taken as 0")
        azimuth = math.radians(value.get("azimuth", 0.0))
        elevation = math.radians(value.get("elevation", 0.0))
        heading = _combine((math.cos(azimuth), forward), (math.sin(azimuth), right))
        vector = _normalise(
            _combine((math.cos(elevation), heading), (math.sin(elevation), up)),
            location, "direction",
        )

    return ResolvedDirection(
        vector=vector, up=up, view_up=_view_up(vector, up, forward, notes),
        **_angles(vector, up, forward, right),
        spelling=spelling, notes=tuple(notes),
    )


def _view_up(
    vector: tuple[float, float, float],
    up: tuple[float, float, float],
    forward: tuple[float, float, float],
    notes: list[str],
) -> tuple[float, float, float]:
    """Return the component of ``up`` perpendicular to the direction.

    Looking straight along ``up`` leaves no such component. That is the case
    that silently produces a rolled or empty image, so it is resolved to a
    stated fallback rather than left to the application.
    """

    residual = _combine((1.0, up), (-_dot(up, vector), vector))
    if math.sqrt(_dot(residual, residual)) < _NEGLIGIBLE:
        notes.append(
            "the direction is parallel to up, so the view-up was taken as the "
            f"reference axis {tuple(round(component, 12) for component in forward)}"
        )
        return forward
    return _normalise(residual, "$", "view-up")


def _angles(
    vector: tuple[float, float, float],
    up: tuple[float, float, float],
    forward: tuple[float, float, float],
    right: tuple[float, float, float],
) -> dict[str, float]:
    """Express any resolved direction in the azimuth/elevation spelling."""

    elevation = math.degrees(math.asin(max(-1.0, min(1.0, _dot(vector, up)))))
    planar = _combine((1.0, vector), (-_dot(vector, up), up))
    if math.sqrt(_dot(planar, planar)) < _NEGLIGIBLE:
        return {"azimuth": 0.0, "elevation": elevation}
    return {
        "azimuth": math.degrees(math.atan2(_dot(planar, right), _dot(planar, forward))),
        "elevation": elevation,
    }
