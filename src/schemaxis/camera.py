"""Shared camera declarations and validation; no application imports."""
import copy
from schemaxis.core.declarations import validate_arguments, validate_value
from schemaxis.core.directions import DIRECTION_ARGUMENT, resolve_direction
from .errors import fail, keys

def _markers(value):
    from .pipeline import markers
    return markers(value)

VECTOR = {'type': 'array', 'items': {'type': 'number'}, 'minItems': 3, 'maxItems': 3}
CAMERA = {
    'direction': {**copy.deepcopy(DIRECTION_ARGUMENT), 'default': [1, 0, 0]},
    'up': {**copy.deepcopy(DIRECTION_ARGUMENT), 'default': [0, 0, 1]},
    'focalPoint': VECTOR,
    'parallel': {'type': 'boolean', 'default': True},
    'scale': {'type': 'number', 'minimum': 0, 'exclusiveMinimum': True},
    'distance': {'type': 'number', 'minimum': 0, 'exclusiveMinimum': True},
    'bounds': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 6, 'maxItems': 6},
    'padding': {'type': 'number', 'minimum': 0, 'default': 0.1},
}


def staged_values(specifications, value, location):
    """Validate constants now, retain marked values for post-update validation."""
    keys(value, specifications, location)
    result = {}
    for key, specification in specifications.items():
        if key in value:
            result[key] = (copy.deepcopy(value[key]) if list(_markers(value[key]))
                           else validate_value(value[key], specification, location + '.' + key))
        elif 'default' in specification:
            result[key] = copy.deepcopy(specification['default'])
        elif specification.get('required'):
            fail('MISSING_ARGUMENT', 'required setting is missing', location + '.' + key)
    return result


def camera_values(value, location, deferred=False):
    result = staged_values(CAMERA, value, location) if deferred else validate_arguments(CAMERA, value, location=location)
    if list(_markers(result)):
        return result
    for key in ('direction', 'up'):
        # Preserve explicit XYZ magnitudes for backward-compatible receipts.
        if not isinstance(result[key], list):
            result[key] = list(resolve_direction(result[key], location=location + '.' + key).vector)
    a, b = result['direction'], result['up']
    scale_a, scale_b = max(abs(v) for v in a), max(abs(v) for v in b)
    if scale_a == 0 or scale_b == 0:
        fail('INVALID_CAMERA', 'direction and up must be nonzero', location)
    a, b = [v / scale_a for v in a], [v / scale_b for v in b]
    cross = [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
    if sum(v*v for v in cross) < 1e-20:
        fail('INVALID_CAMERA', 'direction and up must be nonparallel', location)
    if 'bounds' in result and any(result['bounds'][i] > result['bounds'][i+1] for i in (0, 2, 4)):
        fail('INVALID_BOUNDS', 'camera bounds must not be empty', location)
    return result
