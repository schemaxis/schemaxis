# Copyright (C) 2026 David L F Gaden
"""Structured, transport-neutral Schemaxis faults and exceptions."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from .contracts import JsonValue, _frozen_json, _nonempty, json_value


@dataclass(frozen=True, slots=True)
class Fault:
    code: str
    message: str
    location: str
    phase: str
    retryable: bool = False
    observed: Mapping[str, Any] = field(default_factory=dict)
    recovery: str | None = None

    def __post_init__(self) -> None:
        for name in ("code", "message", "location", "phase"):
            _nonempty(name, getattr(self, name))
        object.__setattr__(self, "observed", _frozen_json(self.observed))
        if self.recovery is not None:
            _nonempty("recovery", self.recovery)

    def to_dict(self) -> dict[str, JsonValue]:
        value: dict[str, JsonValue] = {
            "code": self.code,
            "message": self.message,
            "location": self.location,
            "phase": self.phase,
            "retryable": self.retryable,
            "observed": json_value(self.observed),
        }
        if self.recovery is not None:
            value["recovery"] = self.recovery
        return value


class SchemaxisError(Exception):
    """Exception wrapper for a structured fault at an internal API boundary."""

    def __init__(self, fault: Fault):
        if not isinstance(fault, Fault):
            raise TypeError("fault must be a Fault")
        self.fault = fault
        super().__init__(fault.message)

    def to_dict(self) -> dict[str, JsonValue]:
        return {"fault": self.fault.to_dict()}
