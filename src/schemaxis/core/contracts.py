"""Small, provider-neutral value contracts used by the Schemaxis core.

Serialized contracts deliberately contain descriptions and symbolic addresses only.
``DataHandle`` is the runtime boundary to provider-owned objects and cannot be serialized.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


JsonScalar = None | bool | int | float | str
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


def json_value(value: Any, *, path: str = "$") -> JsonValue:
    """Return a detached JSON-safe value, rejecting ambiguous Python values."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return json_value(value.value, path=path)
    if isinstance(value, Mapping):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} has a non-string object key: {key!r}")
            result[key] = json_value(item, path=f"{path}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [json_value(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    raise TypeError(f"{path} is not JSON-safe: {type(value).__name__}")


def _frozen_json(value: Mapping[str, Any]) -> Mapping[str, JsonValue]:
    return MappingProxyType(json_value(value))


def _nonempty(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


@dataclass(frozen=True, slots=True)
class LogicalType:
    """Meaning of data independent of its storage representation."""

    kind: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _nonempty("kind", self.kind)
        object.__setattr__(self, "details", _frozen_json(self.details))

    def to_dict(self) -> dict[str, JsonValue]:
        return {"kind": self.kind, **json_value(self.details)}


@dataclass(frozen=True, slots=True)
class PhysicalLayout:
    """Storage arrangement without domain meaning."""

    kind: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _nonempty("kind", self.kind)
        object.__setattr__(self, "details", _frozen_json(self.details))

    def to_dict(self) -> dict[str, JsonValue]:
        return {"kind": self.kind, **json_value(self.details)}


@dataclass(frozen=True, slots=True)
class Encoding:
    """Serialized or transmitted form of a physical layout."""

    media_type: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _nonempty("media_type", self.media_type)
        object.__setattr__(self, "details", _frozen_json(self.details))

    def to_dict(self) -> dict[str, JsonValue]:
        return {"mediaType": self.media_type, **json_value(self.details)}


@dataclass(frozen=True, slots=True)
class Representation:
    logical: LogicalType
    layout: PhysicalLayout | None = None
    encoding: Encoding | None = None

    def to_dict(self) -> dict[str, JsonValue]:
        value: dict[str, JsonValue] = {"logical": self.logical.to_dict()}
        if self.layout is not None:
            value["layout"] = self.layout.to_dict()
        if self.encoding is not None:
            value["encoding"] = self.encoding.to_dict()
        return value


@dataclass(frozen=True, slots=True)
class Resource:
    """Declaration of an identifiable source; it does not imply loaded data."""

    id: str
    uri: str
    kind: str
    provider: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("id", "uri", "kind"):
            _nonempty(name, getattr(self, name))
        if self.provider is not None:
            _nonempty("provider", self.provider)
        object.__setattr__(self, "metadata", _frozen_json(self.metadata))

    def to_dict(self) -> dict[str, JsonValue]:
        value: dict[str, JsonValue] = {
            "id": self.id, "uri": self.uri, "kind": self.kind,
            "metadata": json_value(self.metadata),
        }
        if self.provider is not None:
            value["provider"] = self.provider
        return value


@dataclass(frozen=True, slots=True)
class Reference:
    """Serializable address of a declared graph object or named port."""

    ref: str

    def __post_init__(self) -> None:
        _nonempty("ref", self.ref)

    def to_dict(self) -> dict[str, str]:
        return {"ref": self.ref}


@dataclass(frozen=True, slots=True)
class Port:
    name: str
    representation: Representation
    cardinality: str = "one"
    streaming: bool = False
    required: bool = True

    def __post_init__(self) -> None:
        _nonempty("name", self.name)
        if self.cardinality not in {"one", "optional", "many"}:
            raise ValueError("cardinality must be one, optional, or many")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "name": self.name,
            "representation": self.representation.to_dict(),
            "cardinality": self.cardinality,
            "streaming": self.streaming,
            "required": self.required,
        }


@dataclass(frozen=True, slots=True)
class Artifact:
    id: str
    uri: str
    media_type: str
    role: str = "output"
    digest: str | None = None
    produced_by: str | None = None

    def __post_init__(self) -> None:
        for name in ("id", "uri", "media_type", "role"):
            _nonempty(name, getattr(self, name))

    def to_dict(self) -> dict[str, JsonValue]:
        value: dict[str, JsonValue] = {
            "id": self.id, "uri": self.uri, "mediaType": self.media_type, "role": self.role,
        }
        if self.digest is not None:
            value["digest"] = self.digest
        if self.produced_by is not None:
            value["producedBy"] = self.produced_by
        return value


@dataclass(frozen=True, slots=True)
class DataHandle:
    """Execution-scoped access to a live provider-owned value.

    The payload is intentionally opaque and this type has no ``to_dict`` method. Callers
    must serialize a symbolic ``Reference`` or durable ``Artifact`` instead.
    """

    id: str
    provider: str
    value: Any = field(repr=False, compare=False, hash=False)
    representation: Representation
    ownership: str = "borrowed"
    lifetime: str = "execution"

    def __post_init__(self) -> None:
        for name in ("id", "provider", "ownership", "lifetime"):
            _nonempty(name, getattr(self, name))

    def __reduce__(self) -> Any:
        raise TypeError("DataHandle cannot be serialized; use a Reference or Artifact")
