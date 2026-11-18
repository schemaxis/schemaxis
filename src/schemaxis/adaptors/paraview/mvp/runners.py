# Copyright (C) 2026 David L F Gaden
"""ParaView executable discovery and launch flags; no native imports."""
import os
import shutil
from pathlib import Path
from typing import Sequence
from schemaxis.core.runners import Interpreter, _fault, INTERPRETER_NOT_FOUND

#: Environment variable holding extra roots to search, separated as a path list.
ROOTS_VARIABLE = "SCHEMAXIS_PARAVIEW_ROOTS"

#: Relative locations of ``pvbatch`` within a ParaView installation or build.
_PARAVIEW_SUBPATHS = (
    "bin/pvbatch",
    "install/bin/pvbatch",
    "build/install/bin/pvbatch",
)


def executable_candidates(location, names):
    """Accept an installation/build root, bin directory or ParaView executable."""
    base = Path(location).expanduser()
    if base.name in ('paraview', 'pvpython', 'pvbatch') and not base.is_dir():
        if base.name in names:
            yield base
        base = base.parent
    for name in names:
        yield base / name
        for subpath in _PARAVIEW_SUBPATHS:
            yield base / Path(subpath).parent / name
        if base.is_dir():
            yield from sorted(base.glob('build*/install/bin/' + name))


def live_executable(location):
    """Resolve only the chosen installation, without launching or probing it."""
    for candidate in executable_candidates(location, ('pvpython', 'pvbatch')):
        if candidate.is_absolute() and candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
    raise _fault(INTERPRETER_NOT_FOUND, 'No pvpython or pvbatch executable was found in the selected ParaView installation',
                 '$.interpreter', observed={'location': str(location)},
                 recovery='Choose a ParaView installation root, its bin directory, or pvpython/pvbatch.')

#: pvbatch renders to an offscreen buffer only when told to.
PARAVIEW_OFFSCREEN: tuple[str, ...] = ("--force-offscreen-rendering",)

def find_paraview(
    roots: Sequence[str | Path] | None = None, *, search_path: bool = True
) -> tuple[Interpreter, ...]:
    """Find ``pvbatch`` executables, without starting any of them.

    Roots come from the caller, then from ``SCHEMAXIS_PARAVIEW_ROOTS``, then from
    ``PATH``. No installation location is built into Schemaxis.
    """

    candidates: list[str] = []
    supplied = list(roots or ())
    supplied += [
        item for item in os.environ.get(ROOTS_VARIABLE, "").split(os.pathsep) if item
    ]
    for root in supplied:
        candidates.extend(str(path) for path in executable_candidates(root, ('pvbatch',)))
    if search_path:
        located = shutil.which("pvbatch")
        if located:
            candidates.append(located)

    found: list[Interpreter] = []
    seen: set[str] = set()
    for candidate in candidates:
        resolved = str(Path(candidate).resolve())
        if resolved in seen or not os.access(resolved, os.X_OK) or not Path(resolved).is_file():
            continue
        seen.add(resolved)
        found.append(Interpreter("paraview", resolved))
    return tuple(found)


def require_paraview(
    roots: Sequence[str | Path] | None = None, *, probe: bool = True
) -> Interpreter:
    """Return one ParaView interpreter, or fail saying where Schemaxis looked."""

    found = find_paraview(roots)
    if not found:
        raise _fault(
            INTERPRETER_NOT_FOUND, "no pvbatch executable was found", "$.interpreter",
            observed={
                "rootsSupplied": [str(item) for item in (roots or ())],
                "environmentVariable": ROOTS_VARIABLE,
                "environmentValue": os.environ.get(ROOTS_VARIABLE, ""),
            },
            recovery=f"pass a ParaView installation root, or set {ROOTS_VARIABLE}",
        )
    return found[0].probe() if probe else found[0]
