# Copyright (C) 2026 David L F Gaden
"""Execution-scoped handle resolution and lazy provider invocation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import importlib
from types import MappingProxyType
from typing import Any, Mapping, Protocol
import uuid

from .catalogue import Catalogue, CapabilityRecord
from .contracts import Artifact, DataHandle, JsonValue, Reference, Representation, json_value
from .faults import SchemaxisError, Fault


UNKNOWN_REFERENCE = "UNKNOWN_REFERENCE"
NOT_YET_PRODUCED = "NOT_YET_PRODUCED"
TYPE_MISMATCH = "TYPE_MISMATCH"
CLOSED_HANDLE = "CLOSED_HANDLE"
NO_EXECUTED_WORK = "NO_EXECUTED_WORK"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ExecutionState(str, Enum):
    WAITING = "waiting"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIALLY_SUCCEEDED = "partially-succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class _Binding:
    representation: Representation
    handle: DataHandle | None = None
    closed: bool = False


class ExecutionRegistry:
    """Registry of declared symbolic addresses and live handles for one execution."""

    def __init__(self, execution_id: str):
        if not execution_id:
            raise ValueError("execution_id must be non-empty")
        self.execution_id = execution_id
        self._bindings: dict[str, _Binding] = {}

    def declare(self, address: str, representation: Representation) -> None:
        if not address:
            raise ValueError("address must be non-empty")
        if address in self._bindings:
            raise ValueError(f"address already declared: {address}")
        self._bindings[address] = _Binding(representation)

    def publish(self, address: str, handle: DataHandle) -> None:
        binding = self._bindings.get(address)
        if binding is None:
            self._bindings[address] = _Binding(handle.representation, handle)
            return
        if binding.closed:
            raise self._error(CLOSED_HANDLE, address, "Cannot publish to a closed binding")
        if binding.representation != handle.representation:
            raise self._type_error(address, binding.representation, handle.representation)
        binding.handle = handle

    def resolve(
        self, reference: Reference | str, expected: Representation | None = None
    ) -> DataHandle:
        address = reference.ref if isinstance(reference, Reference) else reference
        binding = self._bindings.get(address)
        if binding is None:
            raise self._error(
                UNKNOWN_REFERENCE, address, f"Unknown reference: {address}",
                observed={"available": sorted(self._bindings)},
            )
        if binding.closed:
            raise self._error(CLOSED_HANDLE, address, f"Handle is closed: {address}")
        if binding.handle is None:
            raise self._error(
                NOT_YET_PRODUCED, address, f"Value has not yet been produced: {address}",
                retryable=True,
            )
        if expected is not None and expected != binding.handle.representation:
            raise self._type_error(address, expected, binding.handle.representation)
        return binding.handle

    def close(self, reference: Reference | str) -> None:
        address = reference.ref if isinstance(reference, Reference) else reference
        binding = self._bindings.get(address)
        if binding is None:
            raise self._error(UNKNOWN_REFERENCE, address, f"Unknown reference: {address}")
        binding.closed = True

    def addresses(self) -> tuple[str, ...]:
        return tuple(sorted(self._bindings))

    def _type_error(
        self, address: str, expected: Representation, actual: Representation
    ) -> SchemaxisError:
        return self._error(
            TYPE_MISMATCH, address, f"Representation mismatch at {address}",
            observed={"expected": expected.to_dict(), "actual": actual.to_dict()},
        )

    @staticmethod
    def _error(
        code: str, address: str, message: str, *, retryable: bool = False,
        observed: Mapping[str, Any] | None = None,
    ) -> SchemaxisError:
        return SchemaxisError(Fault(
            code, message, address or "/", "reference-resolution", retryable,
            observed or {},
        ))


@dataclass(frozen=True, slots=True)
class ProviderContext:
    execution_id: str
    step_id: str
    registry: ExecutionRegistry


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    capability: CapabilityRecord
    inputs: Mapping[str, DataHandle]
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "inputs", MappingProxyType(dict(self.inputs)))
        object.__setattr__(self, "arguments", MappingProxyType(dict(self.arguments)))


@dataclass(frozen=True, slots=True)
class ProviderResult:
    outputs: Mapping[str, DataHandle] = field(default_factory=dict)
    observations: Mapping[str, Any] = field(default_factory=dict)
    artifacts: tuple[Artifact, ...] = ()
    warnings: tuple[Fault, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "outputs", MappingProxyType(dict(self.outputs)))
        object.__setattr__(self, "observations", MappingProxyType(dict(self.observations)))
        json_value(self.observations)


class Provider(Protocol):
    def execute(self, request: ProviderRequest, context: ProviderContext) -> ProviderResult: ...


@dataclass(frozen=True, slots=True)
class StepResult:
    id: str
    capability: str
    state: ExecutionState
    output_refs: Mapping[str, str] = field(default_factory=dict)
    observations: Mapping[str, Any] = field(default_factory=dict)
    artifacts: tuple[Artifact, ...] = ()
    faults: tuple[Fault, ...] = ()
    warnings: tuple[Fault, ...] = ()

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "id": self.id, "capability": self.capability, "state": self.state.value,
            "outputs": dict(self.output_refs), "observations": json_value(self.observations),
            "artifacts": [item.to_dict() for item in self.artifacts],
            "faults": [item.to_dict() for item in self.faults],
            "warnings": [item.to_dict() for item in self.warnings],
        }


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    execution_id: str
    state: ExecutionState
    started_at: str
    completed_at: str
    steps: tuple[StepResult, ...]
    faults: tuple[Fault, ...] = ()

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "executionId": self.execution_id, "state": self.state.value,
            "startedAt": self.started_at, "completedAt": self.completed_at,
            "steps": [step.to_dict() for step in self.steps],
            "faults": [fault.to_dict() for fault in self.faults],
        }


class Executor:
    def __init__(self, catalogue: Catalogue):
        self.catalogue = catalogue
        self._providers: dict[str, Provider] = {}

    def _provider(self, record: CapabilityRecord) -> Provider:
        """Import a package binding only when a capability is executed."""
        if record.binding in self._providers:
            return self._providers[record.binding]
        module_name, separator, attribute = record.binding.partition(":")
        if not separator or not module_name or not attribute:
            raise SchemaxisError(Fault(
                "INVALID_BINDING", f"Invalid provider binding: {record.binding}",
                f"capabilities.{record.id}", "provider-loading",
            ))
        try:
            target = getattr(importlib.import_module(module_name), attribute)
            provider = target() if isinstance(target, type) else target
        except (ImportError, AttributeError, TypeError) as error:
            raise SchemaxisError(Fault(
                "PROVIDER_LOAD_FAILED", f"Could not load {record.binding}: {error}",
                f"capabilities.{record.id}", "provider-loading", observed={
                    "binding": record.binding, "exceptionType": type(error).__name__,
                },
            )) from error
        if not callable(getattr(provider, "execute", None)):
            raise SchemaxisError(Fault(
                "INVALID_PROVIDER", f"Binding {record.binding} has no execute method",
                f"capabilities.{record.id}", "provider-loading",
            ))
        self._providers[record.binding] = provider
        return provider

    def execute(self, plan: Mapping[str, Any], *, execution_id: str | None = None) -> ExecutionResult:
        execution_id = execution_id or uuid.uuid4().hex
        started = _now()
        registry = ExecutionRegistry(execution_id)
        results: list[StepResult] = []
        faults: list[Fault] = []
        for raw_step in _plan_nodes(plan):
            step_id = raw_step["id"]
            capability_id = raw_step["capability"]
            # A resolved node keeps its section, so a reader publishes at
            # resources.<id>.outputs.<port>, which is where the planner told
            # every consumer to look for it.
            section = raw_step.get("section", "steps")
            try:
                record = self.catalogue.describe(capability_id)
                inputs = {
                    name: registry.resolve(value["ref"] if isinstance(value, Mapping) else value)
                    for name, value in raw_step.get("inputs", {}).items()
                }
                request = ProviderRequest(record, inputs, raw_step.get("arguments", {}))
                provided = self._provider(record).execute(
                    request, ProviderContext(execution_id, step_id, registry)
                )
                if not isinstance(provided, ProviderResult):
                    raise TypeError("provider execute must return ProviderResult")
                output_refs = {}
                for name, handle in provided.outputs.items():
                    address = f"{section}.{step_id}.outputs.{name}"
                    registry.publish(address, handle)
                    output_refs[name] = address
                results.append(StepResult(
                    step_id, capability_id, ExecutionState.SUCCEEDED, output_refs,
                    provided.observations, provided.artifacts, warnings=provided.warnings,
                ))
            except SchemaxisError as error:
                faults.append(error.fault)
                results.append(StepResult(
                    step_id, capability_id, ExecutionState.FAILED, faults=(error.fault,)
                ))
                break
            except Exception as error:
                fault = Fault(
                    "PROVIDER_EXECUTION_FAILED", str(error) or type(error).__name__,
                    f"steps.{step_id}", "execution", observed={
                        "exceptionType": type(error).__name__
                    },
                )
                faults.append(fault)
                results.append(StepResult(
                    step_id, capability_id, ExecutionState.FAILED, faults=(fault,)
                ))
                break
        if not results:
            # An execution that ran nothing has evidenced nothing. Reporting
            # success here would be the exact untruthfulness Schemaxis exists to
            # remove, so absence of work is a failure with a stated cause.
            faults.append(Fault(
                NO_EXECUTED_WORK,
                "the plan contained no executable nodes, so no result can be evidenced",
                "$", "execution", observed={"planKeys": sorted(plan)},
                recovery="execute a resolved plan whose 'nodes' array is not empty",
            ))
        state = ExecutionState.FAILED if faults else ExecutionState.SUCCEEDED
        return ExecutionResult(execution_id, state, started, _now(), tuple(results), tuple(faults))


def _plan_nodes(plan: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    """Return the nodes of a resolved plan.

    ``ResolvedPlan.to_dict()`` names them ``nodes``; earlier callers passed
    ``steps``. Both are accepted, but neither silently yields nothing: an
    unrecognised plan shape produces no nodes and therefore a failed result.
    """

    for key in ("nodes", "steps"):
        value = plan.get(key)
        if isinstance(value, (list, tuple)):
            return tuple(value)
    return ()
