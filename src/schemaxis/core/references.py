"""Strict parsing for Schemaxis MVP symbolic output references."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping


_IDENTIFIER = r"[A-Za-z][A-Za-z0-9_-]*"
_REFERENCE = re.compile(
    rf"(?P<namespace>resources|steps)\.(?P<identifier>{_IDENTIFIER})"
    rf"\.outputs\.(?P<port>{_IDENTIFIER})\Z"
)


class ReferenceSyntaxError(ValueError):
    """A reference is not in the closed MVP reference language."""

    code = "INVALID_REFERENCE"


@dataclass(frozen=True, slots=True)
class ParsedReference:
    namespace: str
    identifier: str
    port: str

    @property
    def ref(self) -> str:
        return f"{self.namespace}.{self.identifier}.outputs.{self.port}"

    @property
    def node_key(self) -> str:
        return f"{self.namespace}.{self.identifier}"

    def to_dict(self) -> dict[str, str]:
        return {"ref": self.ref}


def parse_reference(value: str | Mapping[str, Any]) -> ParsedReference:
    """Parse a canonical string or its exact ``{"ref": string}`` envelope.

    The grammar is deliberately closed. In particular, array indexing, empty
    segments, dots inside identifiers, and reflection-like segments cannot be
    smuggled through this parser.
    """

    if isinstance(value, Mapping):
        if set(value) != {"ref"}:
            raise ReferenceSyntaxError("a reference object must contain only 'ref'")
        value = value["ref"]
    if not isinstance(value, str):
        raise ReferenceSyntaxError("reference must be a string or {'ref': string}")
    match = _REFERENCE.fullmatch(value)
    if match is None:
        raise ReferenceSyntaxError(
            "reference must match "
            "(resources|steps).<identifier>.outputs.<port>"
        )
    return ParsedReference(
        namespace=match.group("namespace"),
        identifier=match.group("identifier"),
        port=match.group("port"),
    )


# A concise name for callers that regard the parsed value as an address.
ReferenceAddress = ParsedReference
