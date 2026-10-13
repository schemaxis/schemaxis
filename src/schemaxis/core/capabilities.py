"""Implementation-adjacent capability declarations and static manifest export."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from .declarations import validate_specifications
from .extensions import Extension
from .faults import SchemaxisError, Fault


class CapabilityExtension(Extension):
    """An Extension whose in-source dictionary is also a catalogue manifest.

    Export is an explicit development action. Discovery continues to read JSON
    only; it never imports the implementation to regenerate stale metadata.
    """

    @classmethod
    def describe(cls) -> dict[str, Any]:
        document = deepcopy(dict(cls.declaration))
        allowed = {"id", "contractVersion", "provider", "kind", "summary",
                   "inputs", "arguments", "outputs", "effects", "faults", "upstream", "nativeProperties"}
        unknown = set(document) - allowed
        if unknown:
            raise ValueError(f"unknown capability declaration keys: {sorted(unknown)}")
        for key in ("id", "contractVersion", "provider", "kind", "summary"):
            if not isinstance(document.get(key), str) or not document[key]:
                raise ValueError(f"capability {key} must be a nonempty string")
        for key in ("inputs", "arguments", "outputs"):
            if not isinstance(document.get(key), dict):
                raise ValueError(f"capability {key} must be an object")
        validate_specifications(document["arguments"], f"{document['id']}.arguments")
        # Reject non-JSON values during export, before a static manifest is written.
        json.dumps(document, allow_nan=False)
        return document

    @classmethod
    def export_manifest(cls, destination: str | Path) -> None:
        Path(destination).write_text(
            json.dumps(cls.describe(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    @classmethod
    def check_manifest(cls, document: dict[str, Any]) -> None:
        if document != cls.describe():
            raise SchemaxisError(Fault(
                "DECLARATION_MISMATCH", "static manifest differs from its in-source declaration",
                cls.declaration["id"], "provider-loading",
                recovery="regenerate the capability manifest from the installed implementation",
            ))
