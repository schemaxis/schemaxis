"""User-owned application locations; never part of a workflow or runtime archive."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import json
import os
from pathlib import Path
from .errors import fail

LOCAL_CONFIG = '.schemaxis.local.json'
_runtime_locations = ContextVar('schemaxis_runtime_locations', default=None)


def _location_layer(values):
    """Copy and normalize one precedence layer before merging with another."""
    result = deepcopy({key: value for key, value in (values or {}).items() if value is not None})
    from .adaptors.registry import ADAPTORS
    for provider, item in ADAPTORS.items():
        if item.get('locationKind') == 'roots' and provider in result:
            value = result.pop(provider)
            result['roots'] = value if isinstance(value, list) else [value]
    return result


@contextmanager
def location_context(overrides=None):
    """Carry trusted caller locations through execution and verification.

    Nested non-None overrides win; callers and returned location dictionaries
    cannot mutate the stored snapshot. Never populate this scope from receipts.
    """
    values = deepcopy(_runtime_locations.get() or {})
    values.update(_location_layer(overrides))
    token = _runtime_locations.set(values)
    try:
        yield
    finally:
        _runtime_locations.reset(token)


def config_path():
    return Path(os.environ.get('SCHEMAXIS_CONFIG', LOCAL_CONFIG)).expanduser()


def load(path=None):
    path = Path(path) if path is not None else config_path()
    if not path.exists():
        if 'SCHEMAXIS_CONFIG' in os.environ and path == config_path():
            fail('INVALID_CONFIGURATION', 'SCHEMAXIS_CONFIG does not exist', str(path))
        return {'version': 1, 'locations': {}}
    try:
        value = json.loads(path.read_text())
        if not isinstance(value, dict) or value.get('version') != 1 or set(value) != {'version', 'locations'}:
            raise ValueError('expected version 1 and locations')
        locations = value['locations']
        if not isinstance(locations, dict): raise ValueError('locations must be an object')
        for key, location in locations.items():
            valid = (isinstance(location, list) and bool(location) and
                     all(isinstance(v, str) and v.strip() for v in location)) if key == 'roots' else isinstance(location, str) and bool(location.strip())
            if not valid: raise ValueError('invalid application location: ' + key)
        return value
    except (ValueError, OSError) as error:
        fail('INVALID_CONFIGURATION', str(error), str(path))


def locations(overrides=None):
    result = _location_layer(load()['locations'])
    result.update(deepcopy(_runtime_locations.get() or {}))
    result.update(_location_layer(overrides))
    return result


def executable(provider):
    from .adaptors.registry import metadata
    item = metadata(provider)
    value = locations().get('roots' if item.get('locationKind') == 'roots' else provider)
    return value[0] if isinstance(value, list) else value


def configure(provider, location):
    from .adaptors.registry import metadata
    from .artifacts import atomic_json
    item = metadata(provider)
    path = config_path()
    value = load()
    # Executable spelling is part of the runtime identity: resolving a venv's
    # Python symlink selects the base interpreter and loses its environment.
    target = Path(location).expanduser().absolute()
    if not target.exists(): fail('INVALID_CONFIGURATION', 'application location does not exist', str(target))
    if item.get('locationKind') == 'roots':
        target = target.resolve()
        value['locations']['roots'] = [str(target)]
    else:
        if not target.is_file() or not os.access(target, os.X_OK):
            fail('INVALID_CONFIGURATION', 'application executable must be an executable file', str(target))
        value['locations'][provider] = str(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(path, value)
    path.chmod(0o600)
    return {'configuration': str(path.absolute()), 'provider': provider, 'location': str(target)}
