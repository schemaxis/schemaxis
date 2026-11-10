# Copyright (C) 2026 David L F Gaden
"""Bounded, authenticated artifact reads for Studio viewers."""
from pathlib import Path
import hashlib
import os
import shutil
import subprocess
import threading

from .errors import fail


MAX_FILE_BYTES = 32 * 1024 * 1024
TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif',
         '.webp': 'image/webp', '.json': 'application/json; charset=utf-8',
         '.csv': 'text/plain; charset=utf-8', '.tsv': 'text/plain; charset=utf-8',
         '.txt': 'text/plain; charset=utf-8', '.log': 'text/plain; charset=utf-8',
         '.obj': 'text/plain; charset=utf-8', '.stl': 'application/octet-stream',
         '.vtk': 'application/octet-stream', '.vtu': 'application/octet-stream',
         '.ply': 'application/octet-stream', '.step': 'application/octet-stream',
         '.stp': 'application/octet-stream', '.brep': 'application/octet-stream',
         '.ods': 'application/octet-stream', '.xlsx': 'application/octet-stream',
         '.pdf': 'application/octet-stream', '.zip': 'application/octet-stream'}
TYPES.update({suffix: 'application/octet-stream' for suffix in (
    '.fcstd', '.blend', '.pvsm', '.vtp', '.vtr', '.vts', '.vti', '.vtm', '.msh',
    '.foam', '.h5', '.hdf5', '.nc', '.wav', '.mp3', '.mp4', '.aseprite', '.godot')})
TYPES.update({suffix: 'text/plain; charset=utf-8' for suffix in ('.md', '.yaml', '.yml', '.xml')})
TYPES['.bmp'] = 'image/bmp'
_PICKER_LOCK = threading.Lock()


def choose_input_file(app, filename='', extensions=None):
    """Open an existing-file desktop dialog; no upload or authored shell command."""
    if not isinstance(filename, str) or '\x00' in filename:
        fail('INVALID_REQUEST', 'Provide a file path', 'path')
    if not isinstance(extensions, list) or len(extensions) > 50 or any(
            not isinstance(ext, str) or not ext or any(c in ext for c in ('\x00', '\n', '|')) for ext in extensions):
        fail('INVALID_REQUEST', 'Provide a list of file extensions', 'extensions')
    executable = shutil.which('zenity')
    disabled = os.environ.get('SCHEMAXIS_DESKTOP_CHOOSER') == '0'
    if disabled or not executable or not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        return {'status': 'unavailable', 'message': 'Desktop file chooser unavailable; use the folder browser.'}
    if not _PICKER_LOCK.acquire(blocking=False):
        fail('FILE_CHOOSER_BUSY', 'A file chooser is already open on the desktop')
    try:
        path = Path(filename).expanduser() if filename else app.session.workspace
        path = path.absolute()
        initial = str(path) + (os.sep if path.is_dir() else '')
        arguments = [executable, '--file-selection', '--title=Open input file', '--filename=' + initial]
        if extensions:
            patterns = ' '.join('*.' + extension.lstrip('*.') for extension in extensions)
            arguments.append('--file-filter=Supported files | ' + patterns)
        arguments.append('--file-filter=All files | *')
        result = subprocess.run(arguments, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)
        if result.returncode == 1:
            return {'status': 'cancelled'}
        if result.returncode != 0:
            return {'status': 'unavailable', 'message': 'Desktop file chooser could not open; use the folder browser.'}
        chosen = Path(result.stdout.rstrip('\r\n'))
        if not chosen.is_absolute() or not chosen.is_file():
            fail('INVALID_FILE', 'Choose an existing input file', 'path')
        return {'status': 'selected', 'path': str(chosen)}
    except subprocess.TimeoutExpired:
        return {'status': 'cancelled'}
    finally:
        _PICKER_LOCK.release()


def read_artifact(app, filename, expected_digest=None):
    if not isinstance(filename, str) or not filename:
        fail('INVALID_REQUEST', 'provide an artifact path', 'path')
    path = Path(filename)
    if not path.is_absolute():
        path = app.session.workspace / path
    path = path.resolve()
    roots = [app.session.workspace.resolve()]
    if hasattr(app, 'cases'):
        roots.extend(Path(root).resolve() for root in app.cases.file_roots())
    if not any(path.is_relative_to(root) for root in roots):
        fail('ACCESS_DENIED', 'artifact is outside the workspace and this session\'s run directories', 'path')
    if path.suffix.lower() not in TYPES:
        fail('UNSUPPORTED_FILE', 'this file type is not supported by Studio viewers', 'path')
    if not path.is_file():
        fail('RESOURCE_NOT_FOUND', 'artifact does not exist', 'path')
    with path.open('rb') as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        fail('FILE_TOO_LARGE', 'viewer reads are limited to 32 MiB', 'path')
    if expected_digest is not None and hashlib.sha256(data).hexdigest() != expected_digest:
        fail('VERIFICATION_FAILED', 'artifact changed after verification; run or preview again', 'path')
    return data, TYPES[path.suffix.lower()]


def browse_inputs(app, directory=None, extensions=''):
    """List local input names only; authenticated chooser never reads file bytes."""
    if directory is not None and not isinstance(directory, str):
        fail('INVALID_REQUEST', 'provide a directory path', 'directory')
    path = Path(directory).expanduser() if directory else app.session.workspace
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve()
    if not isinstance(extensions, str):
        fail('INVALID_REQUEST', 'provide comma-separated file extensions', 'extensions')
    allowed = {'.' + suffix.strip().lower().lstrip('*.') for suffix in extensions.split(',') if suffix.strip()}
    entries = []
    try:
        for child in path.iterdir():
            is_directory = child.is_dir()
            if is_directory or (child.is_file() and (not allowed or any(child.name.lower().endswith(suffix) for suffix in allowed))):
                entries.append({'name': child.name, 'path': str(child), 'directory': is_directory})
                if len(entries) > 2000:
                    fail('DIRECTORY_TOO_LARGE', 'too many entries; enter a more specific folder', 'directory')
    except OSError as error:
        fail('DIRECTORY_UNAVAILABLE', str(error), 'directory')
    entries.sort(key=lambda item: (not item['directory'], item['name'].casefold()))
    return {'directory': str(path), 'parent': str(path.parent), 'entries': entries}
