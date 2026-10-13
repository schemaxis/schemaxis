"""Static extension indexing with lazy, scoped configuration.

An index is intentionally small: it maps a public extension identifier to a
``module:class`` binding. Listing the index reads JSON only. The selected class
is imported later, when its declaration or implementation is actually needed.

An extension's ``declaration`` uses the grammar in :mod:`schemaxis.core.declarations`, the
same one a static capability manifest uses, and is validated by the same code.
CLI options and document values therefore share one defaulting and checking
path rather than two that drift.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import importlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .declarations import (
    COMPOSITE_KINDS,
    describe_arguments,
    validate_arguments,
    validate_specifications,
)
from .faults import SchemaxisError, Fault


class ExtensionError(ValueError):
    """An extension indexing, declaration or configuration failure.

    The structured :class:`~schemaxis.core.faults.Fault` is the contract; this exception
    only carries it across the module boundary.
    """

    def __init__(
        self, code: str, message: str, *, location: str = "extensions",
        fault: Fault | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.location = location
        self.fault = fault or Fault(code, message, location, "extension")

    @classmethod
    def from_fault(cls, error: SchemaxisError, *, location: str | None = None) -> "ExtensionError":
        fault = error.fault
        return cls(fault.code, fault.message, location=location or fault.location, fault=fault)


class Extension:
    """Convenience base class for an extension with a static declaration.

    Derived classes define ``declaration`` as an in-code dictionary literal and
    implement ``configure``. Configuration delivered to the hook has already
    passed the declaration's defaults, type, enum, required, and unknown-key
    checks.
    """

    declaration: Mapping[str, Any] = {}

    @classmethod
    def contribute_cli_arguments(cls, parser: argparse.ArgumentParser) -> dict[str, str]:
        """Contribute this selected extension's scoped options."""

        declaration = _validated_declaration(cls.declaration, cls.__name__)
        destinations: dict[str, str] = {}
        for name, specification in declaration["arguments"].items():
            destination = f"extension_{name}"
            destinations[name] = destination
            parser.add_argument(
                f"--{declaration['id']}.{name}", dest=destination,
                default=argparse.SUPPRESS, help=_option_help(specification),
                metavar="JSON" if specification["type"] in COMPOSITE_KINDS else None,
            )
        return destinations

    @classmethod
    def describe(cls) -> dict[str, Any]:
        """Return this extension's canonical JSON declaration."""

        declaration = _validated_declaration(cls.declaration, cls.__name__)
        return {
            "id": declaration["id"],
            "arguments": describe_arguments(declaration["arguments"]),
        }

    def configure(self, config: Mapping[str, Any]) -> None:
        """Receive validated configuration for this selected extension."""

        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ExtensionRecord:
    id: str
    binding: str
    index_path: Path


class ExtensionRegistry:
    """Deterministic static extension index and lazy binding loader."""

    def __init__(self, records: Iterable[ExtensionRecord] = ()):
        by_id: dict[str, ExtensionRecord] = {}
        for record in records:
            if record.id in by_id:
                raise ExtensionError(
                    "DUPLICATE_EXTENSION",
                    f"extension {record.id!r} is indexed more than once",
                    location=str(record.index_path),
                )
            by_id[record.id] = record
        self._records = MappingProxyType(dict(sorted(by_id.items())))

    @classmethod
    def from_indexes(cls, paths: Iterable[str | Path]) -> "ExtensionRegistry":
        records: list[ExtensionRecord] = []
        for path in sorted((Path(item).resolve() for item in paths), key=lambda item: item.as_posix()):
            document = _read_index(path)
            for extension_id in sorted(document):
                binding = document[extension_id]
                if not isinstance(extension_id, str) or not extension_id:
                    raise ExtensionError("INVALID_INDEX", "extension IDs must be non-empty strings", location=str(path))
                if not isinstance(binding, str) or not binding:
                    raise ExtensionError(
                        "INVALID_INDEX", f"binding for {extension_id!r} must be a non-empty string",
                        location=str(path),
                    )
                records.append(ExtensionRecord(extension_id, binding, path))
        return cls(records)

    def list_extensions(self) -> tuple[ExtensionRecord, ...]:
        return tuple(self._records.values())

    def describe(self, extension_id: str) -> ExtensionRecord:
        try:
            return self._records[extension_id]
        except KeyError as error:
            raise ExtensionError("UNKNOWN_EXTENSION", f"unknown extension {extension_id!r}") from error

    def load_class(self, extension_id: str) -> type[Extension]:
        record = self.describe(extension_id)
        module_name, separator, class_name = record.binding.partition(":")
        if not separator or not module_name or not class_name:
            raise ExtensionError(
                "INVALID_BINDING", f"invalid binding for {extension_id!r}: {record.binding!r}",
                location=str(record.index_path),
            )
        try:
            candidate = getattr(importlib.import_module(module_name), class_name)
        except (ImportError, AttributeError) as error:
            raise ExtensionError(
                "EXTENSION_LOAD_FAILED", f"could not load {record.binding!r}: {error}",
                location=str(record.index_path),
            ) from error
        if not isinstance(candidate, type) or not issubclass(candidate, Extension):
            raise ExtensionError(
                "INVALID_EXTENSION", f"{record.binding!r} is not an Extension class",
                location=str(record.index_path),
            )
        declaration = _validated_declaration(candidate.declaration, record.binding)
        if declaration["id"] != extension_id:
            raise ExtensionError(
                "DECLARATION_ID_MISMATCH",
                f"index ID {extension_id!r} does not match declaration ID {declaration['id']!r}",
                location=record.binding,
            )
        return candidate

    def configure_document(self, extension_id: str, config: Mapping[str, Any]) -> Extension:
        extension_class = self.load_class(extension_id)
        values = validate_config(extension_class.declaration, config)
        instance = extension_class()
        instance.configure(MappingProxyType(values))
        return instance

    def configure_cli(self, extension_id: str, argv: Iterable[str]) -> Extension:
        extension_class = self.load_class(extension_id)
        declaration = _validated_declaration(extension_class.declaration, extension_class.__name__)
        parser = _ScopedArgumentParser(prog=extension_id, add_help=False)
        destination_by_name = extension_class.contribute_cli_arguments(parser)
        try:
            namespace = parser.parse_args(list(argv))
        except argparse.ArgumentError as error:
            raise ExtensionError("INVALID_CLI", f"invalid options for {extension_id!r}: {error}") from error
        raw = {
            name: _parse_cli_value(
                getattr(namespace, destination), declaration["arguments"][name],
                f"--{declaration['id']}.{name}",
            )
            for name, destination in destination_by_name.items()
            if hasattr(namespace, destination)
        }
        values = validate_config(declaration, raw)
        instance = extension_class()
        instance.configure(MappingProxyType(values))
        return instance


class _ScopedArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise argparse.ArgumentError(None, message)


def validate_config(declaration: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    """Validate document or CLI values through the same declaration path."""

    declaration = _validated_declaration(declaration, "declaration")
    try:
        return validate_arguments(
            declaration["arguments"], config,
            location=declaration["id"], check_specifications=False,
        )
    except SchemaxisError as error:
        raise ExtensionError.from_fault(error) from error


def _option_help(specification: Mapping[str, Any]) -> str:
    kind = specification["type"]
    detail = specification.get("summary") or specification.get("title") or ""
    if kind == "enum":
        detail = f"{detail} one of: {', '.join(str(item) for item in specification['values'])}".strip()
    elif kind in COMPOSITE_KINDS:
        detail = f"{detail} ({kind} as JSON text)".strip()
    if "default" in specification:
        detail = f"{detail} [default: {specification['default']!r}]".strip()
    elif specification.get("required", False):
        detail = f"{detail} [required]".strip()
    return detail


def _read_index(path: Path) -> dict[str, str]:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ExtensionError("DUPLICATE_EXTENSION", f"duplicate extension ID {key!r}", location=str(path))
            result[key] = value
        return result

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    except ExtensionError:
        raise
    except (OSError, json.JSONDecodeError) as error:
        raise ExtensionError("INVALID_INDEX", f"cannot read extension index {path}: {error}", location=str(path)) from error
    if not isinstance(value, dict):
        raise ExtensionError("INVALID_INDEX", "extension index must be a JSON object", location=str(path))
    return value


def _validated_declaration(value: Any, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ExtensionError("INVALID_DECLARATION", "extension declaration must be an object", location=location)
    extension_id = value.get("id")
    arguments = value.get("arguments", {})
    if not isinstance(extension_id, str) or not extension_id:
        raise ExtensionError("INVALID_DECLARATION", "declaration id must be a non-empty string", location=location)
    try:
        validate_specifications(arguments, location)
    except SchemaxisError as error:
        raise ExtensionError.from_fault(error, location=location) from error
    return {"id": extension_id, "arguments": arguments}


def _parse_cli_value(value: str, specification: Mapping[str, Any], option: str) -> Any:
    """Convert one CLI string into a declared value, then hand it to validation.

    A composite argument is supplied as JSON text. That keeps one grammar and
    one validation path instead of inventing a second, weaker CLI syntax whose
    accepted values would differ from the document's.
    """

    kind = specification["type"]
    try:
        if kind == "integer":
            return int(value)
        if kind == "number":
            return float(value)
        if kind == "boolean":
            lowered = value.lower()
            if lowered in {"true", "1", "yes"}:
                return True
            if lowered in {"false", "0", "no"}:
                return False
            raise ValueError("expected true or false")
        if kind == "enum":
            if all(isinstance(item, str) for item in specification["values"]):
                return value
            return json.loads(value)
        if kind in COMPOSITE_KINDS:
            return json.loads(value)
        if kind == "union":
            # A union may accept a bare string spelling, so JSON is preferred
            # but its failure is not itself an error.
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value
    except (ValueError, json.JSONDecodeError) as error:
        raise ExtensionError(
            "INVALID_ARGUMENT", f"invalid value for {option}: {value!r} is not a valid {kind}",
            location=option,
            fault=Fault(
                "INVALID_ARGUMENT", f"{value!r} is not a valid {kind}", option, "validation",
                observed={"option": option, "supplied": value, "type": kind},
                recovery=f"supply a {kind}" + (" as JSON text" if kind in COMPOSITE_KINDS else ""),
            ),
        ) from error
