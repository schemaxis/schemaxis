# Copyright (C) 2026 David L F Gaden
"""Resolve recorded run paths within the currently selected, self-contained copy.

An export's origin is a location hint, not verification evidence. Native receipts
remain unchanged and their provider must still verify the retained bytes.
"""
import json
from pathlib import Path

from .errors import fail

MANIFEST = 'publication-metadata.json'
METADATA_VERSION = 'schemaxis.artifact-metadata/1'


def _origin(manifest):
    value = manifest.get('recordedDirectory')
    if value is None:
        return None
    if not isinstance(value, str) or not Path(value).is_absolute() or '..' in Path(value).parts:
        raise ValueError('recorded directory must be an absolute path without traversal')
    return Path(value)


def _manifest(directory):
    path = Path(directory)/MANIFEST
    if not path.exists() and not path.is_symlink():
        return None
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError('publication manifest must be an owned regular file')
        value = json.loads(path.read_text())
        if not isinstance(value, dict) or value.get('version') != METADATA_VERSION:
            raise ValueError('publication manifest version differs')
        _origin(value)
        return value
    except (OSError, ValueError, TypeError) as error:
        raise ValueError(str(path) + ': ' + str(error)) from error


def export_manifest(directory):
    """Retain the first producing directory across export/move/re-export."""
    try:
        value = _manifest(directory)
        if value is None:
            raise ValueError('publication manifest is absent')
        value['recordedDirectory'] = str(_origin(value) or Path(directory).absolute())
        return value
    except (OSError, ValueError, TypeError) as error:
        fail('VERIFICATION_FAILED', 'cannot retain publication origin: ' + str(error), str(directory))


def recorded_directory(directory):
    """Read an existing export hint before replacing its publication manifest."""
    try:
        value = _manifest(directory)
        return _origin(value) if value is not None else None
    except (OSError, ValueError, TypeError) as error:
        fail('PUBLICATION_METADATA_FAILED', 'cannot retain publication origin: ' + str(error), str(directory))


def owned_path(directory, value, *, kind='file', fault='VERIFICATION_FAILED'):
    """Map an absolute recorded path or run-relative name into the owned tree.

Never fall back to an old absolute location. Every component inside the selected
tree must be unlinked. Legacy cwd-relative paths are supported in place only;
portable receipts must use absolute recorded paths or run-relative names.
In place, an alias of the owning directory may supply the recorded prefix.
"""
    directory = Path(directory).absolute()
    try:
        if not isinstance(value, (str, Path)) or not str(value):
            raise ValueError('an owned path is required')
        path = Path(value)
        if '..' in path.parts:
            raise ValueError('owned path must not traverse a parent directory')
        manifest = _manifest(directory)
        origin = _origin(manifest) if manifest else None
        if path.is_absolute():
            if origin is not None and path.is_relative_to(origin):
                path = directory/path.relative_to(origin)
            elif not path.is_relative_to(directory):
                target = None if origin is not None else directory.resolve()
                anchor = None
                if target is not None:
                    # Keep the tail unresolved so internal links remain visible.
                    # The outermost match cannot hide a link that re-enters the run.
                    for parent in reversed(list(path.parents)):
                        if parent.exists() and parent.resolve() == target:
                            anchor = parent
                            break
                if anchor is None:
                    raise ValueError('recorded path is outside its owned directory')
                path = directory/path.relative_to(anchor)
        else:
            candidate = path.absolute()
            if origin is None and candidate.is_relative_to(directory) and candidate.exists():
                path = candidate
            else:
                path = directory/path
        relative = path.relative_to(directory)
        component = directory
        if component.is_symlink() or not component.is_dir():
            raise ValueError('owned directory is missing or linked')
        for part in relative.parts:
            component = component/part
            if component.is_symlink():
                raise ValueError('owned path traverses a link')
        if not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError('owned path escaped its directory')
        if not (path.is_dir() if kind == 'directory' else path.is_file()):
            raise ValueError('owned ' + kind + ' is missing')
        return path
    except (OSError, ValueError, TypeError) as error:
        location = str(value) if str(value).strip() else '$'
        fail(fault, 'cannot resolve retained path: ' + str(error), location)
