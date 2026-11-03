# Copyright (C) 2026 David L F Gaden
"""Submission of replay source to an external Python interpreter.

:mod:`schemaxis.core.replay` emits the exact source to be executed and hands it to an
injected runner. This module supplies a real one: a subprocess runner for an
application's own Python interpreter, such as ParaView's ``pvbatch``.

Two boundaries are deliberate.

Discovery of an interpreter is separate from discovery of capabilities. Reading
a capability manifest must never start an application; asking which ParaView is
installed obviously must, so it is a distinct, explicit operation.

A zero exit status is evidence that the submitted source ran to completion. It
is not evidence that the intended thing happened. This module reports what the
interpreter did, and stops there; whether the resulting artifact is correct is
verification, which belongs elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any, Mapping, Sequence

from .contracts import JsonValue
from .faults import SchemaxisError, Fault


INTERPRETER_NOT_FOUND = "INTERPRETER_NOT_FOUND"
INTERPRETER_UNUSABLE = "INTERPRETER_UNUSABLE"
RUNNER_FAILED = "RUNNER_FAILED"
RUNNER_TIMED_OUT = "RUNNER_TIMED_OUT"

SUBMISSION_PHASE = "submission"

_VERSION = re.compile(r"(\d+\.\d+(?:\.\d+)?)")
_EXCERPT = 4000


def _fault(
    code: str, message: str, location: str, *,
    observed: Mapping[str, Any] | None = None, recovery: str | None = None,
    retryable: bool = False,
) -> SchemaxisError:
    return SchemaxisError(Fault(
        code=code, message=message, location=location, phase=SUBMISSION_PHASE,
        retryable=retryable, observed=observed or {}, recovery=recovery,
    ))


def _tail(text: str | bytes) -> str:
    """Keep the end of a long output, where the failure usually is."""

    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    if len(text) <= _EXCERPT:
        return text
    return f"...[{len(text) - _EXCERPT} characters omitted]...\n" + text[-_EXCERPT:]


@dataclass(frozen=True, slots=True)
class Interpreter:
    """An external Python interpreter Schemaxis may submit replay source to."""

    kind: str
    executable: str
    version: str | None = None

    def to_dict(self) -> dict[str, JsonValue]:
        value: dict[str, JsonValue] = {"kind": self.kind, "executable": self.executable}
        if self.version is not None:
            value["version"] = self.version
        return value

    def probe(self, *, timeout: float = 120.0) -> "Interpreter":
        """Ask the interpreter its version. This starts the application."""

        try:
            completed = subprocess.run(
                [self.executable, "--version"], capture_output=True, text=True,
                timeout=timeout, check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise _fault(
                INTERPRETER_UNUSABLE, f"could not run {self.executable}: {error}",
                self.executable, observed={"exceptionType": type(error).__name__},
            ) from error
        reported = f"{completed.stdout}\n{completed.stderr}".strip()
        match = _VERSION.search(reported)
        if completed.returncode != 0 or match is None:
            raise _fault(
                INTERPRETER_UNUSABLE, f"{self.executable} did not report a version",
                self.executable,
                observed={"exitCode": completed.returncode, "output": _tail(reported)},
                recovery="check that this is an application interpreter and that it starts",
            )
        return Interpreter(self.kind, self.executable, match.group(1))




@dataclass(frozen=True, slots=True)
class RunReport:
    """What the interpreter did with the submitted source.

    A zero ``exit_code`` means the source ran to completion. It does not mean
    the intended artifact was produced, or is correct.
    """

    interpreter: Interpreter
    script_path: str
    exit_code: int
    stdout: str
    stderr: str
    seconds: float
    command: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "interpreter": self.interpreter.to_dict(),
            "scriptPath": self.script_path,
            "exitCode": self.exit_code,
            "stdout": _tail(self.stdout),
            "stderr": _tail(self.stderr),
            "seconds": round(self.seconds, 6),
            "command": list(self.command),
        }


@dataclass(frozen=True, slots=True)
class SubprocessRunner:
    """Submit replay source to an interpreter as a retained script file."""

    interpreter: Interpreter
    workspace: Path
    arguments: tuple[str, ...] = ()
    timeout: float | None = None
    environment: Mapping[str, str] | None = field(default=None)

    def __call__(self, source: str) -> RunReport:
        if not isinstance(source, str):
            raise TypeError("replay source must be a string")
        workspace = Path(self.workspace)
        workspace.mkdir(parents=True, exist_ok=True)
        # The script is named by its own content, so the artifact on disk is
        # provably the source that was submitted.
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
        script = workspace / f"replay-{digest}.py"
        script.write_text(source, encoding="utf-8")

        command = (self.interpreter.executable, *self.arguments, str(script))
        environment = dict(os.environ, **self.environment) if self.environment else None
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=self.timeout,
                check=False, env=environment,
            )
        except subprocess.TimeoutExpired as error:
            raise _fault(
                RUNNER_TIMED_OUT,
                f"the interpreter did not finish within {self.timeout} seconds",
                str(script), retryable=True,
                observed={
                    "seconds": self.timeout, "command": list(command),
                    "stdout": _tail(error.stdout or ""), "stderr": _tail(error.stderr or ""),
                },
                recovery="raise the timeout, or reduce the work submitted in one script",
            ) from error
        except OSError as error:
            raise _fault(
                INTERPRETER_UNUSABLE, f"could not start {self.interpreter.executable}: {error}",
                self.interpreter.executable, observed={"command": list(command)},
            ) from error

        report = RunReport(
            interpreter=self.interpreter, script_path=str(script),
            exit_code=completed.returncode, stdout=completed.stdout or "",
            stderr=completed.stderr or "", seconds=time.monotonic() - started,
            command=command,
        )
        if completed.returncode != 0:
            raise _fault(
                RUNNER_FAILED,
                f"the interpreter exited with status {completed.returncode}",
                str(script), observed=report.to_dict(),
                recovery="the submitted source is retained at the reported script path",
            )
        return report


def __getattr__(name):
    """Compatibility exports for the former application-specific runner API."""
    if name in ('find_paraview', 'require_paraview', 'PARAVIEW_OFFSCREEN', 'ROOTS_VARIABLE'):
        from schemaxis.adaptors.paraview.mvp import runners
        return getattr(runners, name)
    raise AttributeError(name)
