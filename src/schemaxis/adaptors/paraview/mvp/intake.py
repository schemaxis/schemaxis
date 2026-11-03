# Copyright (C) 2026 David L F Gaden
"""Explicit developer intake; separate from static capability discovery."""
from pathlib import Path

from schemaxis.adaptors.paraview.mvp.runners import require_paraview
from schemaxis.core.runners import SubprocessRunner


def inspect_native(group: str, proxy: str, directory: Path):
    interpreter = require_paraview()
    directory = directory.absolute()
    directory.mkdir(exist_ok=False)
    destination = directory / 'metadata.json'
    source = Path(__file__).with_name('metadata_runtime.py').read_text(encoding='utf-8')
    source += f'\ncapture_native_metadata({group!r}, {proxy!r}, {str(destination)!r})\n'
    return SubprocessRunner(interpreter, directory, timeout=120)(source)


def inspect_commands(directory: Path):
    interpreter = require_paraview()
    directory = directory.absolute()
    directory.mkdir(exist_ok=False)
    source = Path(__file__).with_name('metadata_runtime.py').read_text(encoding='utf-8')
    source += f'\ncapture_command_index({str(directory / "commands.json")!r})\n'
    return SubprocessRunner(interpreter, directory, timeout=120)(source)
