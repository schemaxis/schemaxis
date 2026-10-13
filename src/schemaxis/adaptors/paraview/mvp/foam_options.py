"""Bounded real-case options for the existing slice capability."""
from schemaxis.core.times import TIMES_ARGUMENT

VECTOR = {'type': 'array', 'items': {'type': 'number'}, 'minItems': 3, 'maxItems': 3}
FOAM_ARGUMENT = {'type': 'object', 'properties': {
    'file': {'type': 'string', 'minLength': 1, 'required': True},
    'geometryOrder': {'type': 'enum', 'values': ['positionFastest'], 'default': 'positionFastest'},
    'times': {**TIMES_ARGUMENT, 'default': 'latest'},
    'fractions': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 1,
                  'default': [0.25, 0.5, 0.75],
                  'summary': 'Positions along the bounds projection onto normal; 0=min, 1=max'},
    'requiredFields': {'type': 'array', 'items': {'type': 'string', 'minLength': 1},
                       'minItems': 1, 'default': ['U', 'p']},
    'appearances': {'type': 'array', 'items': {'type': 'enum', 'values': ['p', 'Umag']},
                    'minItems': 1, 'default': ['p', 'Umag']},
    'writers': {'type': 'array', 'default': [], 'items': {'type': 'object', 'properties': {
        'name': {'type': 'string', 'minLength': 1, 'required': True},
        'size': {'type': 'array', 'items': {'type': 'integer', 'minimum': 32, 'maximum': 4096},
                 'minItems': 2, 'maxItems': 2, 'default': [640, 480]},
        'cameras': {'type': 'array', 'minItems': 1, 'items': {'type': 'object', 'properties': {
            'direction': {**VECTOR, 'required': True},
            'up': {**VECTOR, 'default': [0, 0, 1]},
        }}},
    }}},
    'maxPublications': {'type': 'integer', 'minimum': 1, 'maximum': 100000, 'default': 1000},
}}
