# Copyright (C) 2026 David L F Gaden
"""Deterministic Python replay source generation with injected submission.

This module never imports or executes a target application.  It records a
small, closed command model, emits Python source, and submits that exact source
to a caller-supplied runner.  Successful generation is not runtime evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
import keyword
import re
from types import MappingProxyType
from typing import Any, Callable, Iterator, Mapping, Protocol

from .faults import SchemaxisError, Fault
from .references import ParsedReference, ReferenceSyntaxError, parse_reference


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_PUBLIC_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")
_MODULE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\Z")

#: The name of the result table in emitted source.
_RESULTS = "schemaxis_results"


class ReplayValidationError(ValueError):
    """A command cannot be represented by the safe replay language."""


class ReplayStatus(str, Enum):
    SUBMITTED = "submitted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SourceRunner(Protocol):
    def __call__(self, source: str) -> Any: ...


Primitive = None | bool | int | float | str


@dataclass(frozen=True, slots=True)
class Connection:
    """An argument that is the result of an earlier call in the same script.

    A pipeline is calls joined to calls, so an argument must be able to name a
    previous result. It renders as a lookup in the script's own result table,
    never as a bare name, so nothing an identifier could shadow is introduced.
    """

    reference: ParsedReference

    @classmethod
    def to(cls, value: "str | Mapping[str, Any] | ParsedReference") -> "Connection":
        candidate = value.ref if isinstance(value, ParsedReference) else value
        try:
            return cls(parse_reference(candidate))
        except ReferenceSyntaxError as error:
            raise ReplayValidationError(f"invalid connected reference: {error}") from error


#: Short spelling for building a connected argument.
connect = Connection.to

Renderable = Primitive | Connection | list["Renderable"] | dict[str, "Renderable"]

#: Applications routinely take a point or a colour as a list, so lists and
#: string-keyed dictionaries of primitives are renderable. The nesting limit
#: keeps a hostile or accidental structure from exhausting the stack.
_MAX_DEPTH = 8


def _literal(value: Any, depth: int = 0) -> str:
    """Return a deterministic Python literal for the closed value set."""

    if depth > _MAX_DEPTH:
        raise ReplayValidationError(
            f"argument values may not nest deeper than {_MAX_DEPTH} levels"
        )
    if type(value) is type(None):
        return "None"
    if type(value) is bool:
        return "True" if value else "False"
    # Exact types prevent subclasses from supplying hostile renderings.
    if type(value) is int:
        return str(value)
    if type(value) is float:
        if not math.isfinite(value):
            raise ReplayValidationError("floating-point arguments must be finite")
        return repr(value)
    if type(value) is str:
        # ascii() is deterministic and always emits a valid quoted Python
        # literal, including for quotes, newlines, backslashes, and Unicode.
        return ascii(value)
    if type(value) is Connection:
        return f"{_RESULTS}[{ascii(value.reference.ref)}]"
    if type(value) is list:
        return "[" + ", ".join(_literal(item, depth + 1) for item in value) + "]"
    if type(value) is dict:
        members = []
        for key, item in value.items():
            if type(key) is not str:
                raise ReplayValidationError(
                    f"argument dictionary keys must be strings, got {type(key).__name__}"
                )
            members.append(f"{ascii(key)}: {_literal(item, depth + 1)}")
        return "{" + ", ".join(members) + "}"
    raise ReplayValidationError(
        f"argument values must be primitive JSON-compatible values, got {type(value).__name__}"
    )


def _require_identifier(value: Any, *, role: str, public: bool = False) -> str:
    expression = _PUBLIC_IDENTIFIER if public else _IDENTIFIER
    if type(value) is not str or expression.fullmatch(value) is None or keyword.iskeyword(value):
        raise ReplayValidationError(f"invalid Python {role}: {value!r}")
    return value


@dataclass(frozen=True, slots=True)
class ReplayCall:
    module: str
    function: str
    result: ParsedReference
    arguments: Mapping[str, Renderable] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            type(self.module) is not str
            or _MODULE.fullmatch(self.module) is None
            or any(keyword.iskeyword(segment) for segment in self.module.split("."))
        ):
            raise ReplayValidationError(f"invalid Python module: {self.module!r}")
        _require_identifier(self.function, role="function")
        if not isinstance(self.result, ParsedReference):
            raise ReplayValidationError("result must be a parsed Schemaxis reference")
        if not isinstance(self.arguments, Mapping):
            raise ReplayValidationError("arguments must be a mapping")
        checked: dict[str, Renderable] = {}
        for name, value in self.arguments.items():
            _require_identifier(name, role="keyword argument")
            _literal(value)
            checked[name] = value
        object.__setattr__(self, "arguments", MappingProxyType(checked))


@dataclass(frozen=True, slots=True)
class ReplayOutcome:
    """Truthful report of submission and the injected runner's outcome."""

    submitted_source: str
    status: ReplayStatus
    events: tuple[ReplayStatus, ...]
    runner_result: Any = field(default=None, repr=False, compare=False)
    failure_type: str | None = None
    failure_message: str | None = None
    #: The structured fault, when the runner failed with one. A runner that
    #: raises an ordinary exception leaves this empty and only its type and
    #: message survive.
    fault: Fault | None = None

    @property
    def submitted(self) -> bool:
        return bool(self.events) and self.events[0] is ReplayStatus.SUBMITTED

    @property
    def succeeded(self) -> bool:
        return self.status is ReplayStatus.SUCCEEDED


class ReplayScript:
    """Ordered recorder for explicit, keyword-only Python function calls."""

    def __init__(self) -> None:
        self._calls: list[ReplayCall] = []
        self._commands: list[ReplayCall | str] = []
        self._assignment_connections: set[str] = set()

    @property
    def calls(self) -> tuple[ReplayCall, ...]:
        return tuple(self._calls)

    def record_call(
        self,
        module: str,
        function: str,
        arguments: Mapping[str, Renderable],
        result_ref: str | Mapping[str, Any] | ParsedReference,
    ) -> ReplayCall:
        """Validate and append one call without importing or invoking it."""

        try:
            # Reparse direct ParsedReference values because their constructor is public.
            candidate = result_ref.ref if isinstance(result_ref, ParsedReference) else result_ref
            result = parse_reference(candidate)
        except ReferenceSyntaxError as error:
            raise ReplayValidationError(f"invalid result reference: {error}") from error
        produced = {call.result.ref for call in self._calls}
        if result.ref in produced:
            raise ReplayValidationError(
                f"{result.ref} is already produced by an earlier call in this script"
            )
        for connection in _connections(arguments):
            # A connection to something never produced would be a NameError at
            # run time, in the application, far from its cause.
            if connection.reference.ref not in produced:
                raise ReplayValidationError(
                    f"{connection.reference.ref} is not produced by an earlier call in this script"
                )
        call = ReplayCall(module, function, result, arguments)
        self._calls.append(call)
        self._commands.append(call)
        return call

    def record_assignment(self, target: Connection, path: str, value: Renderable) -> None:
        """Assign a public property path on an earlier result.

        This is a trusted adaptor operation, not an extension of Schemaxis reference
        syntax or an application property allowlist. Providers own the allowed
        properties and their types. No indexing, expressions or method calls.
        """
        if type(target) is not Connection:
            raise ReplayValidationError("assignment target must be a Connection")
        if type(path) is not str or not 1 <= len(path.split(".")) <= 4:
            raise ReplayValidationError("property paths must contain one to four names")
        for segment in path.split("."):
            _require_identifier(segment, role="property", public=True)
        literal = _literal(value)
        produced = {call.result.ref for call in self._calls}
        for connection in (target, *_connections(value)):
            if connection.reference.ref not in produced:
                raise ReplayValidationError(
                    f"{connection.reference.ref} is not produced by an earlier call in this script"
                )
        self._assignment_connections.update(
            connection.reference.ref for connection in (target, *_connections(value))
        )
        self._commands.append(f"{_literal(target)}.{path} = {literal}")

    # Short spelling for command-recording clients.
    add = record_call

    def connections(self) -> tuple[str, ...]:
        """Every earlier result this script feeds back into a later call."""

        return tuple(sorted(self._assignment_connections | {
            connection.reference.ref
            for call in self._calls for connection in _connections(call.arguments)
        }))

    def emit(self) -> str:
        """Emit canonical source.  This says nothing about runtime success."""

        modules: list[str] = []
        for call in self._calls:
            if call.module not in modules:
                modules.append(call.module)

        lines = [f"import {module}" for module in modules]
        if lines:
            lines.append("")
        lines.append(f"{_RESULTS} = {{}}")
        for call in self._commands:
            if isinstance(call, str):
                lines.append(call)
                continue
            arguments = ", ".join(
                f"{name}={_literal(value)}" for name, value in call.arguments.items()
            )
            lines.append(
                f"{_RESULTS}[{_literal(call.result.ref)}] = "
                f"{call.module}.{call.function}({arguments})"
            )
        return "\n".join(lines) + "\n"

    def execute(self, runner: SourceRunner | Callable[[str], Any]) -> ReplayOutcome:
        """Submit exact emitted source and retain the runner outcome.

        ``SUCCEEDED`` means only that the injected runner returned normally. It
        is not scientific verification or interpretation of a returned status
        or exit code; those belong to the caller and runner adaptor contract.
        """

        if not callable(runner):
            raise TypeError("runner must be callable")
        source = self.emit()
        events = [ReplayStatus.SUBMITTED]
        try:
            result = runner(source)
        except Exception as error:  # The runner boundary must preserve failure as data.
            events.append(ReplayStatus.FAILED)
            return ReplayOutcome(
                submitted_source=source,
                status=ReplayStatus.FAILED,
                events=tuple(events),
                failure_type=type(error).__name__,
                failure_message=str(error),
                fault=error.fault if isinstance(error, SchemaxisError) else None,
            )
        events.append(ReplayStatus.SUCCEEDED)
        return ReplayOutcome(
            submitted_source=source,
            status=ReplayStatus.SUCCEEDED,
            events=tuple(events),
            runner_result=result,
        )


def _connections(value: Any) -> Iterator[Connection]:
    """Yield every connected reference anywhere inside an argument value."""

    if type(value) is Connection:
        yield value
    elif type(value) is list:
        for item in value:
            yield from _connections(item)
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _connections(item)


def emit_replay(calls: tuple[ReplayCall, ...] | list[ReplayCall]) -> str:
    """Functional source-emission convenience for already validated calls."""

    replay = ReplayScript()
    for call in calls:
        if not isinstance(call, ReplayCall):
            raise ReplayValidationError("calls must contain ReplayCall values")
        replay.record_call(call.module, call.function, call.arguments, call.result)
    return replay.emit()
