# Copyright (C) 2026 David L F Gaden
"""Pure planning for the Schemaxis Python contract spike.

Planning consumes static catalogue records only. It performs no provider
imports, resource access, or execution.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping

from .catalogue import Catalogue, CatalogueError, CapabilityRecord
from .declarations import validate_arguments
from .faults import SchemaxisError
from .documents import resolve_document
from .references import ParsedReference, ReferenceSyntaxError, parse_reference


class PlanningError(ValueError):
    """A stable planning failure suitable for conversion to a Fault."""

    def __init__(self, code: str, message: str, *, location: str = "$"):
        super().__init__(message)
        self.code = code
        self.location = location


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return deepcopy(value)


@dataclass(frozen=True, slots=True)
class ResolvedNode:
    key: str
    id: str
    section: str
    capability_id: str
    provider: str
    provider_version: str
    contract_version: str
    inputs: Mapping[str, ParsedReference] = field(default_factory=dict)
    arguments: Mapping[str, Any] = field(default_factory=dict)
    outputs: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "inputs", MappingProxyType(dict(self.inputs)))
        object.__setattr__(self, "arguments", _freeze(self.arguments))
        object.__setattr__(self, "outputs", _freeze(self.outputs))

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "id": self.id,
            "section": self.section,
            "capability": self.capability_id,
            "provider": self.provider,
            "providerVersion": self.provider_version,
            "contractVersion": self.contract_version,
            "inputs": {name: reference.to_dict() for name, reference in self.inputs.items()},
            "arguments": _thaw(self.arguments),
            "outputs": _thaw(self.outputs),
        }


@dataclass(frozen=True, slots=True)
class ResolvedPlan:
    document_version: str
    nodes: tuple[ResolvedNode, ...]
    topological_order: tuple[str, ...]
    digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "documentVersion": self.document_version,
            "nodes": [node.to_dict() for node in self.nodes],
            "topologicalOrder": list(self.topological_order),
            "digest": self.digest,
        }


class Planner:
    def __init__(self, catalogue: Catalogue):
        self.catalogue = catalogue

    def resolve(self, workflow: Mapping[str, Any]) -> ResolvedPlan:
        return plan_workflow(workflow, self.catalogue)

    # Natural alias for clients that use the component name as the verb.
    plan = resolve


def plan_workflow(workflow: Mapping[str, Any], catalogue: Catalogue) -> ResolvedPlan:
    if not isinstance(workflow, Mapping):
        raise PlanningError("INVALID_WORKFLOW", "workflow must be an object")
    workflow, _ = resolve_document(dict(workflow))
    document_version = workflow.get("documentVersion")
    if not isinstance(document_version, str) or not document_version:
        raise PlanningError(
            "INVALID_WORKFLOW", "documentVersion must be a non-empty string",
            location="$.documentVersion",
        )
    resources = workflow.get("resources", {})
    steps = workflow.get("steps", [])
    outputs = workflow.get("outputs", {})
    if not isinstance(resources, Mapping):
        raise PlanningError("INVALID_WORKFLOW", "resources must be an object", location="$.resources")
    if not isinstance(steps, list):
        raise PlanningError("INVALID_WORKFLOW", "steps must be an array", location="$.steps")
    if not isinstance(outputs, Mapping):
        raise PlanningError("INVALID_WORKFLOW", "outputs must be an object", location="$.outputs")

    drafts: list[tuple[str, str, str, Mapping[str, Any], str]] = []
    seen: set[str] = set()
    for resource_id, declaration in resources.items():
        _valid_identifier(resource_id, f"$.resources.{resource_id}")
        if not isinstance(declaration, Mapping):
            raise PlanningError("INVALID_WORKFLOW", "resource must be an object", location=f"$.resources.{resource_id}")
        capability = declaration.get("reader")
        arguments = dict(_object(declaration.get("arguments", {}), f"$.resources.{resource_id}.arguments"))
        source = declaration.get("source")
        if isinstance(source, Mapping) and "uri" in source and "uri" not in arguments:
            arguments["uri"] = source["uri"]
        drafts.append(("resources", resource_id, capability, {**declaration, "arguments": arguments}, f"$.resources.{resource_id}"))
        seen.add(f"resources.{resource_id}")

    for index, declaration in enumerate(steps):
        location = f"$.steps[{index}]"
        if not isinstance(declaration, Mapping):
            raise PlanningError("INVALID_WORKFLOW", "step must be an object", location=location)
        step_id = declaration.get("id")
        _valid_identifier(step_id, f"{location}.id")
        key = f"steps.{step_id}"
        if key in seen:
            raise PlanningError("DUPLICATE_NODE", f"duplicate step {step_id!r}", location=f"{location}.id")
        seen.add(key)
        drafts.append(("steps", step_id, declaration.get("use"), declaration, location))

    # Publications are planned as writer nodes, but deliberately cannot be referenced.
    for output_id, declaration in outputs.items():
        _valid_identifier(output_id, f"$.outputs.{output_id}")
        if not isinstance(declaration, Mapping):
            raise PlanningError("INVALID_WORKFLOW", "output must be an object", location=f"$.outputs.{output_id}")
        normalised = dict(declaration)
        if "input" in normalised and "inputs" not in normalised:
            normalised["inputs"] = {"dataset": normalised["input"]}
        arguments = dict(_object(normalised.get("arguments", {}), f"$.outputs.{output_id}.arguments"))
        destination = normalised.get("destination")
        if isinstance(destination, Mapping) and "uri" in destination and "uri" not in arguments:
            arguments["uri"] = destination["uri"]
        normalised["arguments"] = arguments
        drafts.append(("outputs", output_id, declaration.get("writer"), normalised, f"$.outputs.{output_id}"))

    resolved: dict[str, ResolvedNode] = {}
    dependencies: dict[str, set[str]] = {}
    for section, node_id, capability_id, declaration, location in drafts:
        if not isinstance(capability_id, str) or not capability_id:
            field_name = "reader" if section == "resources" else "writer" if section == "outputs" else "use"
            raise PlanningError("INVALID_WORKFLOW", f"{field_name} must be a non-empty string", location=f"{location}.{field_name}")
        record = _capability(catalogue, capability_id, f"{location}.use")
        inputs_value = _object(declaration.get("inputs", {}), f"{location}.inputs")
        inputs = _resolve_inputs(inputs_value, record, location)
        arguments = _resolve_arguments(
            _object(declaration.get("arguments", {}), f"{location}.arguments"), record, location
        )
        key = f"{section}.{node_id}"
        resolved[key] = ResolvedNode(
            key=key, id=node_id, section=section, capability_id=record.id,
            provider=record.provider, provider_version=record.provider_version,
            contract_version=record.contract_version, inputs=inputs,
            arguments=arguments, outputs=record.outputs,
        )
        dependencies[key] = {reference.node_key for reference in inputs.values()}

    for key, node in resolved.items():
        for input_name, reference in node.inputs.items():
            source = resolved.get(reference.node_key)
            location = f"$.{key}.inputs.{input_name}"
            if source is None or source.section == "outputs":
                raise PlanningError("UNKNOWN_REFERENCE", f"unknown reference {reference.ref!r}", location=location)
            if reference.port not in source.outputs:
                raise PlanningError("UNKNOWN_PORT", f"{reference.node_key!r} has no output {reference.port!r}", location=location)
            _check_types(source.outputs[reference.port], node_input_spec(node, input_name, catalogue), location)

    order = _topological_order(dependencies)
    ordered_nodes = tuple(resolved[key] for key in order)
    digest_payload = {
        "documentVersion": document_version,
        "nodes": [node.to_dict() for node in ordered_nodes],
        "topologicalOrder": order,
    }
    canonical = json.dumps(digest_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return ResolvedPlan(document_version, ordered_nodes, tuple(order), digest)


def node_input_spec(node: ResolvedNode, name: str, catalogue: Catalogue) -> Mapping[str, Any]:
    return catalogue.describe(node.capability_id).inputs[name]


def _capability(catalogue: Catalogue, capability_id: str, location: str) -> CapabilityRecord:
    try:
        return catalogue.describe(capability_id)
    except CatalogueError as error:
        raise PlanningError("UNKNOWN_CAPABILITY", str(error), location=location) from error


def _object(value: Any, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PlanningError("INVALID_WORKFLOW", "value must be an object", location=location)
    return value


def _valid_identifier(value: Any, location: str) -> None:
    # Reuse the exact reference grammar rather than maintaining a looser copy.
    try:
        parse_reference(f"steps.{value}.outputs.port")
    except ReferenceSyntaxError as error:
        raise PlanningError("INVALID_IDENTIFIER", f"invalid identifier {value!r}", location=location) from error


def _resolve_inputs(values: Mapping[str, Any], record: CapabilityRecord, location: str) -> dict[str, ParsedReference]:
    unknown = set(values) - set(record.inputs)
    if unknown:
        name = sorted(unknown)[0]
        raise PlanningError("UNKNOWN_INPUT", f"unknown input port {name!r}", location=f"{location}.inputs.{name}")
    missing = [name for name, spec in record.inputs.items() if spec.get("required", True) and name not in values]
    if missing:
        raise PlanningError("MISSING_INPUT", f"missing required input {missing[0]!r}", location=f"{location}.inputs.{missing[0]}")
    result: dict[str, ParsedReference] = {}
    for name, value in values.items():
        try:
            result[name] = parse_reference(value)
        except ReferenceSyntaxError as error:
            raise PlanningError("INVALID_REFERENCE", str(error), location=f"{location}.inputs.{name}") from error
    return result


def _resolve_arguments(values: Mapping[str, Any], record: CapabilityRecord, location: str) -> dict[str, Any]:
    """Check and default declared arguments through the shared grammar.

    The manifest's declarations are checked here too, so a capability whose
    manifest mis-declares an argument fails at planning time rather than
    silently accepting whatever a caller supplied.
    """

    try:
        return validate_arguments(
            record.arguments, values, location=f"{location}.arguments", phase="planning",
        )
    except SchemaxisError as error:
        raise PlanningError(
            error.fault.code, error.fault.message, location=error.fault.location
        ) from error


def _logical_types(spec: Mapping[str, Any]) -> set[str]:
    value = spec.get("logicalType")
    if isinstance(value, str):
        return {value}
    if isinstance(value, (list, tuple)) and value and all(isinstance(item, str) for item in value):
        return set(value)
    return set()


def _check_types(source: Mapping[str, Any], target: Mapping[str, Any], location: str) -> None:
    source_types = _logical_types(source)
    target_types = _logical_types(target)
    if not source_types or not target_types or source_types.isdisjoint(target_types):
        raise PlanningError(
            "INCOMPATIBLE_PORT_TYPE",
            f"source logical type {sorted(source_types)!r} is incompatible with {sorted(target_types)!r}",
            location=location,
        )


def _topological_order(dependencies: Mapping[str, set[str]]) -> list[str]:
    remaining = {key: set(value) for key, value in dependencies.items()}
    order: list[str] = []
    while remaining:
        ready = sorted(key for key, needed in remaining.items() if not needed)
        if not ready:
            cycle = sorted(remaining)
            raise PlanningError("WORKFLOW_CYCLE", f"workflow contains a cycle involving {cycle!r}")
        order.extend(ready)
        for key in ready:
            del remaining[key]
        for needed in remaining.values():
            needed.difference_update(ready)
    return order


# Convenient functional spelling used by some clients.
resolve_workflow = plan_workflow
