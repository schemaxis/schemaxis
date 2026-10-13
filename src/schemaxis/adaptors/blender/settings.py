"""Static, bounded Cycles rendering contract (no Blender imports)."""
from schemaxis.core.declarations import validate_arguments

RENDER_OPTIONS = {
    'device': {'type': 'enum', 'values': ['CPU', 'CUDA', 'OPTIX'], 'default': 'CPU'},
    'samples': {'type': 'integer', 'minimum': 1, 'maximum': 4096, 'default': 8},
    'threads': {'type': 'integer', 'minimum': 1, 'maximum': 64, 'default': 4},
    'denoise': {'type': 'boolean', 'default': False},
    'transparent': {'type': 'boolean', 'default': False},
    'seed': {'type': 'integer', 'minimum': 0, 'maximum': 2147483647, 'default': 0},
    'worldColour': {'type': 'array', 'items': {'type': 'number', 'minimum': 0, 'maximum': 1},
                    'minItems': 3, 'maxItems': 3, 'default': [.8, .8, .8]},
    'worldStrength': {'type': 'number', 'minimum': 0, 'default': .8},
    'lightEnergy': {'type': 'number', 'minimum': 0, 'default': 1000},
    'lightPosition': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 3, 'maxItems': 3,
                      'default': [4, -4, 6]},
    'lightSize': {'type': 'number', 'minimum': 0, 'exclusiveMinimum': True, 'default': 1},
}


def render_settings(value):
    return validate_arguments(RENDER_OPTIONS, value, location='$.scenes[0].render')


def matching(actual, expected):
    """Native float properties may round to float32; retain strict membership."""
    import math
    if isinstance(expected, dict):
        return isinstance(actual, dict) and actual.keys() == expected.keys() and all(
            matching(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            matching(a, b) for a, b in zip(actual, expected))
    if type(expected) in (int, float):
        return type(actual) in (int, float) and math.isclose(actual, expected, rel_tol=1e-6, abs_tol=1e-7)
    return type(actual) is type(expected) and actual == expected


def clipping(diagonal, distance):
    """Camera clipping in the same world units as the mesh, including small CAD parts."""
    return max(1e-6, diagonal*1e-4), max(1.0, diagonal*10, distance+diagonal*2)
