"""Deterministic JSON-descriptor provider used to exercise Schemaxis integration.

This provider does not perform geospatial computation and must not be presented
as GDAL.  It preserves and derives descriptor metadata so the Schemaxis execution
contracts can be tested on machines with no geospatial runtime installed.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from schemaxis.core.contracts import (
    Artifact,
    DataHandle,
    Encoding,
    JsonValue,
    LogicalType,
    Representation,
    json_value,
)
from schemaxis.core.faults import SchemaxisError, Fault


RASTER_TYPE = "geo.raster-dataset"
VECTOR_TYPE = "geo.vector-dataset"
ARTIFACT_TYPE = "schemaxis.artifact"
CAPABILITIES = frozenset(
    {"fixture.geo.open", "fixture.geo.slope", "fixture.geo.contours", "fixture.geo.write"}
)


@dataclass(frozen=True, slots=True)
class ProviderResult:
    outputs: Mapping[str, Any] = field(default_factory=dict)
    observations: Mapping[str, JsonValue] = field(default_factory=dict)
    artifacts: tuple[Artifact, ...] = ()
    verification: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "outputs", MappingProxyType(dict(self.outputs)))
        object.__setattr__(self, "observations", MappingProxyType(json_value(self.observations)))
        object.__setattr__(self, "verification", MappingProxyType(json_value(self.verification)))


class Provider:
    id = "fixture.geo"
    version = "0.1.0"
    capability_ids = CAPABILITIES

    def execute(
        self,
        capability_id: str,
        inputs: Mapping[str, DataHandle],
        arguments: Mapping[str, Any],
        context: Any,
    ) -> ProviderResult:
        dispatch = {
            "fixture.geo.open": self._open,
            "fixture.geo.slope": self._slope,
            "fixture.geo.contours": self._contours,
            "fixture.geo.write": self._write,
        }
        try:
            operation = dispatch[capability_id]
        except KeyError as error:
            raise _fault(
                "UNKNOWN_CAPABILITY", f"fixture provider does not implement {capability_id!r}",
                capability_id, "execute",
            ) from error
        return operation(inputs, arguments, context)

    def _open(
        self, inputs: Mapping[str, DataHandle], arguments: Mapping[str, Any], context: Any
    ) -> ProviderResult:
        if inputs:
            raise _fault("INVALID_INPUT", "open does not accept input ports", "fixture.geo.open", "connect")
        uri = _string_argument(arguments, "uri", "fixture.geo.open")
        path = _resolve_path(context, uri, output=False)
        try:
            source_bytes = path.read_bytes()
            descriptor = json.loads(source_bytes)
        except FileNotFoundError as error:
            raise _fault(
                "RESOURCE_NOT_FOUND", f"fixture resource does not exist: {uri}",
                "fixture.geo.open", "execute", observed={"uri": uri},
            ) from error
        except (OSError, json.JSONDecodeError) as error:
            raise _fault(
                "INVALID_FIXTURE", f"cannot read fixture descriptor {uri}: {error}",
                "fixture.geo.open", "execute", observed={"uri": uri},
            ) from error
        descriptor = _validate_raster_descriptor(descriptor, "fixture.geo.open")
        descriptor["source"] = {
            "uri": uri,
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
        }
        handle = _handle(context, "open.dataset", RASTER_TYPE, descriptor)
        inspection = {
            key: deepcopy(descriptor[key])
            for key in ("crs", "width", "height", "extent", "resolution", "bands")
        }
        return ProviderResult(outputs={"dataset": handle}, observations={"inspection": inspection})

    def _slope(
        self, inputs: Mapping[str, DataHandle], arguments: Mapping[str, Any], context: Any
    ) -> ProviderResult:
        source = _dataset_input(inputs, RASTER_TYPE, "fixture.geo.slope")
        unit = arguments.get("unit", "degrees")
        if unit not in {"degrees", "percent"}:
            raise _fault(
                "INVALID_ARGUMENT", "unit must be 'degrees' or 'percent'",
                "fixture.geo.slope", "configure", observed={"unit": unit},
            )
        descriptor = deepcopy(source.value)
        _require_spatial_metadata(descriptor, "fixture.geo.slope")
        descriptor["product"] = {"kind": "slope", "unit": unit}
        return ProviderResult(outputs={"dataset": _handle(context, "slope.dataset", RASTER_TYPE, descriptor)})

    def _contours(
        self, inputs: Mapping[str, DataHandle], arguments: Mapping[str, Any], context: Any
    ) -> ProviderResult:
        source = _dataset_input(inputs, RASTER_TYPE, "fixture.geo.contours")
        interval = arguments.get("interval", 10)
        if isinstance(interval, bool) or not isinstance(interval, (int, float)) or interval <= 0:
            raise _fault(
                "INVALID_ARGUMENT", "interval must be a positive number",
                "fixture.geo.contours", "configure", observed={"interval": interval},
            )
        _require_spatial_metadata(source.value, "fixture.geo.contours")
        descriptor = {
            "fixtureVersion": "schemaxis.fixture-vector/0.1",
            "crs": source.value["crs"],
            "extent": deepcopy(source.value["extent"]),
            "geometryType": "LineString",
            "product": {"kind": "contours", "interval": interval},
            "source": deepcopy(source.value.get("source", {})),
        }
        return ProviderResult(outputs={"dataset": _handle(context, "contours.dataset", VECTOR_TYPE, descriptor)})

    def _write(
        self, inputs: Mapping[str, DataHandle], arguments: Mapping[str, Any], context: Any
    ) -> ProviderResult:
        dataset = _dataset_input(inputs, {RASTER_TYPE, VECTOR_TYPE}, "fixture.geo.write")
        uri = _string_argument(arguments, "uri", "fixture.geo.write")
        _require_spatial_metadata(dataset.value, "fixture.geo.write")
        path = _resolve_path(context, uri, output=True)
        if path.exists() and not bool(arguments.get("overwrite", False)):
            raise _fault(
                "DESTINATION_EXISTS", f"destination already exists: {uri}",
                "fixture.geo.write", "execute", observed={"uri": uri},
            )
        descriptor = {
            "artifactVersion": "schemaxis.fixture-artifact/0.1",
            "logicalType": dataset.representation.logical.kind,
            "dataset": deepcopy(dataset.value),
        }
        encoded = (json.dumps(descriptor, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(encoded)
        except OSError as error:
            raise _fault(
                "WRITE_FAILED", f"cannot write fixture artifact {uri}: {error}",
                "fixture.geo.write", "execute", observed={"uri": uri},
            ) from error
        digest = hashlib.sha256(encoded).hexdigest()
        persisted = json.loads(path.read_text(encoding="utf-8"))
        verification = {
            "logicalType": persisted.get("logicalType") == dataset.representation.logical.kind,
            "crs": persisted.get("dataset", {}).get("crs") == dataset.value["crs"],
            "extent": persisted.get("dataset", {}).get("extent") == dataset.value["extent"],
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest() == digest,
        }
        if not all(verification.values()):
            raise _fault(
                "VERIFICATION_FAILED", f"fixture artifact verification failed: {uri}",
                "fixture.geo.write", "verify", observed=verification,
            )
        artifact = Artifact(
            id=f"fixture-{digest[:16]}", uri=str(path), media_type="application/json",
            digest=f"sha256:{digest}", produced_by="fixture.geo.write",
        )
        artifact_handle = _handle(context, "write.artifact", ARTIFACT_TYPE, artifact)
        return ProviderResult(
            outputs={"artifact": artifact_handle}, artifacts=(artifact,), verification=verification
        )


def create_provider() -> Provider:
    return Provider()


def _handle(context: Any, suffix: str, logical_type: str, value: Any) -> DataHandle:
    execution_id = str(getattr(context, "execution_id", "fixture-execution"))
    representation = Representation(
        logical=LogicalType(logical_type),
        encoding=Encoding("application/json", {"profile": "schemaxis-fixture-descriptor"}),
    )
    return DataHandle(
        id=f"{execution_id}:{suffix}", provider="fixture.geo", value=value,
        representation=representation, ownership="owned", lifetime="execution",
    )


def _dataset_input(
    inputs: Mapping[str, DataHandle], expected: str | set[str], capability_id: str
) -> DataHandle:
    dataset = inputs.get("dataset")
    if not isinstance(dataset, DataHandle):
        raise _fault("INVALID_INPUT", "dataset input must be a DataHandle", capability_id, "connect")
    accepted = {expected} if isinstance(expected, str) else expected
    actual = dataset.representation.logical.kind
    if actual not in accepted:
        raise _fault(
            "TYPE_MISMATCH", f"dataset has logical type {actual!r}; expected {sorted(accepted)!r}",
            capability_id, "connect", observed={"actual": actual, "expected": sorted(accepted)},
        )
    if not isinstance(dataset.value, dict):
        raise _fault("INVALID_DATASET", "fixture dataset payload must be an object", capability_id, "execute")
    return dataset


def _validate_raster_descriptor(value: Any, capability_id: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _fault("INVALID_FIXTURE", "fixture descriptor must be an object", capability_id, "execute")
    _require_spatial_metadata(value, capability_id)
    width, height, bands = value.get("width"), value.get("height"), value.get("bands")
    if not isinstance(width, int) or isinstance(width, bool) or width <= 0:
        raise _fault("INVALID_FIXTURE", "width must be a positive integer", capability_id, "execute")
    if not isinstance(height, int) or isinstance(height, bool) or height <= 0:
        raise _fault("INVALID_FIXTURE", "height must be a positive integer", capability_id, "execute")
    if not isinstance(bands, list) or not bands:
        raise _fault("INVALID_FIXTURE", "bands must be a non-empty array", capability_id, "execute")
    return deepcopy(value)


def _require_spatial_metadata(value: Mapping[str, Any], capability_id: str) -> None:
    crs, extent = value.get("crs"), value.get("extent")
    if not isinstance(crs, str) or not crs:
        raise _fault("INVALID_DATASET", "dataset CRS is missing", capability_id, "verify")
    if (
        not isinstance(extent, list) or len(extent) != 4
        or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in extent)
    ):
        raise _fault("INVALID_DATASET", "dataset extent must contain four numbers", capability_id, "verify")


def _string_argument(arguments: Mapping[str, Any], name: str, capability_id: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value:
        raise _fault(
            "INVALID_ARGUMENT", f"{name} must be a non-empty string", capability_id,
            "configure", observed={name: value},
        )
    return value


def _resolve_path(context: Any, uri: str, *, output: bool) -> Path:
    resolver = getattr(context, "resolve_path", None)
    if callable(resolver):
        return Path(resolver(uri, output=output))
    root_name = "output_root" if output else "resource_root"
    root = Path(getattr(context, root_name, "."))
    path = Path(uri)
    return path if path.is_absolute() else root / path


def _fault(
    code: str, message: str, location: str, phase: str, *, observed: Mapping[str, Any] | None = None
) -> SchemaxisError:
    return SchemaxisError(
        Fault(
            code=code, message=message, location=location, phase=phase,
            observed={} if observed is None else observed,
        )
    )
