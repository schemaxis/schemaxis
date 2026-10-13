"""Static capability discovery.

Discovery deliberately reads JSON only.  Provider bindings are names recorded
for a later execution phase; this module never imports them.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Iterator, Mapping


class CatalogueError(ValueError):
    """A stable, machine-identifiable catalogue construction failure."""

    def __init__(self, code: str, message: str, *, location: Path | None = None):
        super().__init__(message)
        self.code = code
        self.location = location


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return deepcopy(value)


@dataclass(frozen=True)
class CapabilityRecord:
    """A validated static manifest plus its deferred implementation binding."""

    id: str
    contract_version: str
    provider: str
    provider_version: str
    kind: str
    binding: str
    manifest_path: Path
    _document: Mapping[str, Any] = field(repr=False, compare=False)

    @property
    def document(self) -> dict[str, Any]:
        """Return a defensive, mutable copy suitable for serialisation."""

        return _thaw(self._document)

    @property
    def inputs(self) -> Mapping[str, Any]:
        return self._document["inputs"]

    @property
    def arguments(self) -> Mapping[str, Any]:
        return self._document["arguments"]

    @property
    def outputs(self) -> Mapping[str, Any]:
        return self._document["outputs"]


class Catalogue:
    """A deterministic index of statically discovered capabilities."""

    def __init__(self, records: Iterable[CapabilityRecord] = ()):
        by_id: dict[str, CapabilityRecord] = {}
        for record in records:
            if record.id in by_id:
                first = by_id[record.id]
                raise CatalogueError(
                    "DUPLICATE_CAPABILITY",
                    f"capability {record.id!r} is declared by both "
                    f"{first.manifest_path} and {record.manifest_path}",
                    location=record.manifest_path,
                )
            by_id[record.id] = record
        self._by_id = MappingProxyType(dict(sorted(by_id.items())))

    @classmethod
    def from_roots(cls, roots: Iterable[str | Path]) -> "Catalogue":
        package_paths: set[Path] = set()
        for supplied_root in roots:
            root = Path(supplied_root).resolve()
            direct = root / "package.json"
            if direct.is_file():
                package_paths.add(direct)
            if root.is_dir():
                package_paths.update(path.resolve() for path in root.glob("*/package.json"))

        records: list[CapabilityRecord] = []
        for package_path in sorted(package_paths, key=lambda path: path.as_posix()):
            records.extend(_read_package(package_path))
        return cls(records)

    def list_capabilities(self) -> tuple[CapabilityRecord, ...]:
        return tuple(self._by_id.values())

    def describe(self, capability_id: str) -> CapabilityRecord:
        try:
            return self._by_id[capability_id]
        except KeyError as error:
            raise CatalogueError(
                "UNKNOWN_CAPABILITY", f"unknown capability {capability_id!r}"
            ) from error

    def __iter__(self) -> Iterator[CapabilityRecord]:
        return iter(self._by_id.values())

    def __len__(self) -> int:
        return len(self._by_id)


def _read_json(path: Path, *, kind: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CatalogueError(
            "INVALID_MANIFEST", f"cannot read {kind} JSON at {path}: {error}", location=path
        ) from error
    if not isinstance(value, dict):
        raise CatalogueError(
            "INVALID_MANIFEST", f"{kind} at {path} must be a JSON object", location=path
        )
    return value


def _required_string(document: Mapping[str, Any], key: str, path: Path) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value:
        raise CatalogueError(
            "INVALID_MANIFEST", f"{path}: {key} must be a non-empty string", location=path
        )
    return value


def _read_package(package_path: Path) -> list[CapabilityRecord]:
    package = _read_json(package_path, kind="package manifest")
    provider = package.get("provider")
    if not isinstance(provider, dict):
        raise CatalogueError(
            "INVALID_MANIFEST", f"{package_path}: provider must be an object", location=package_path
        )
    provider_id = _required_string(provider, "id", package_path)
    provider_version = _required_string(provider, "version", package_path)
    binding = _required_string(package, "binding", package_path)
    capability_names = package.get("capabilities")
    if not isinstance(capability_names, list) or not all(
        isinstance(name, str) and name for name in capability_names
    ):
        raise CatalogueError(
            "INVALID_MANIFEST",
            f"{package_path}: capabilities must be an array of non-empty paths",
            location=package_path,
        )

    package_root = package_path.parent.resolve()
    records: list[CapabilityRecord] = []
    for relative_name in sorted(capability_names):
        manifest_path = (package_root / relative_name).resolve()
        if not manifest_path.is_relative_to(package_root):
            raise CatalogueError(
                "INVALID_MANIFEST",
                f"{package_path}: capability path escapes its package: {relative_name}",
                location=package_path,
            )
        document = _read_json(manifest_path, kind="capability manifest")
        capability_id = _required_string(document, "id", manifest_path)
        contract_version = _required_string(document, "contractVersion", manifest_path)
        manifest_provider = _required_string(document, "provider", manifest_path)
        capability_kind = _required_string(document, "kind", manifest_path)
        if manifest_provider != provider_id:
            raise CatalogueError(
                "INVALID_MANIFEST",
                f"{manifest_path}: provider {manifest_provider!r} does not match package "
                f"provider {provider_id!r}",
                location=manifest_path,
            )
        for object_key in ("inputs", "arguments", "outputs"):
            if not isinstance(document.get(object_key), dict):
                raise CatalogueError(
                    "INVALID_MANIFEST",
                    f"{manifest_path}: {object_key} must be an object",
                    location=manifest_path,
                )
        records.append(
            CapabilityRecord(
                id=capability_id,
                contract_version=contract_version,
                provider=provider_id,
                provider_version=provider_version,
                kind=capability_kind,
                binding=binding,
                manifest_path=manifest_path,
                _document=_freeze(document),
            )
        )
    return records
