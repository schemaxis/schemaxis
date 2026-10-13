"""Explicit typed runtime function catalogue; functions here have no side effects.

Application bindings register trusted callables. Authored input names a registered
function, never an import path. Dependencies live in its argument expressions.
"""
import copy
import math
from schemaxis.core.declarations import validate_arguments, validate_value, validate_specifications
from .errors import fail


class FunctionRegistry:
    def __init__(self):
        self.entries = {}

    def register(self, name, arguments, result, function):
        if not isinstance(name, str) or not name or name in self.entries:
            fail('DUPLICATE_FUNCTION', 'function name must be new and nonempty', str(name))
        object_arguments = {k: v for k, v in arguments.items() if 'objectKind' in v}
        for key, spec in object_arguments.items():
            if set(spec) - {'objectKind', 'required'} or not isinstance(spec['objectKind'], str):
                fail('INVALID_FUNCTION', 'invalid object argument declaration', name + '/' + key)
        validate_specifications({k: v for k, v in arguments.items() if k not in object_arguments}, name)
        if 'objectKind' not in result:
            validate_specifications({'result': result}, name)
        elif set(result) != {'objectKind'} or not isinstance(result['objectKind'], str):
            fail('INVALID_FUNCTION', 'invalid object result declaration', name)
        if not callable(function):
            fail('INVALID_FUNCTION', 'binding must be callable', name)
        self.entries[name] = (copy.deepcopy(arguments), copy.deepcopy(result), function)

    def describe(self):
        return {name: {'arguments': copy.deepcopy(args), 'result': copy.deepcopy(result),
                       'effects': [], 'phase': 'value', 'dependencies': 'argument expressions'}
                for name, (args, result, _) in sorted(self.entries.items())}

    def check(self, name, arguments, location):
        if not isinstance(name, str) or name not in self.entries:
            fail('UNKNOWN_FUNCTION', 'runtime function is not registered', location, available=sorted(self.entries))
        from .errors import keys
        spec = self.entries[name][0]
        keys(arguments, spec, location)
        for key, declaration in spec.items():
            if declaration.get('required') and key not in arguments:
                fail('MISSING_ARGUMENT', 'function argument is required', location + '/' + key)

    def invoke(self, name, arguments, location, objects=None):
        self.check(name, arguments, location)
        spec, result, function = self.entries[name]
        native = {k: v for k, v in spec.items() if 'objectKind' in v}
        values = validate_arguments({k: v for k, v in spec.items() if k not in native},
                                    {k: v for k, v in arguments.items() if k not in native}, location=location)
        for key, declaration in native.items():
            if key in arguments:
                if objects is None:
                    fail('OBJECT_CONTEXT_UNAVAILABLE', 'function needs an object registry', location)
                values[key] = objects.require_kind(arguments[key], declaration['objectKind'], location + '/' + key)
        arguments = values
        try:
            value = function(**arguments)
        except (ValueError, TypeError, ArithmeticError) as error:
            fail('FUNCTION_FAILED', str(error), location, function=name)
        if 'objectKind' in result:
            if objects is None:
                fail('OBJECT_CONTEXT_UNAVAILABLE', 'object result needs a registry', location)
            return objects.require_kind(value, result['objectKind'], location + '/result')
        return validate_value(value, result, location + '/result')


def make_registry():
    registry = FunctionRegistry()
    number = {'type': 'number'}
    vector = {'type': 'array', 'items': number, 'minItems': 3, 'maxItems': 3}
    bounds = {'type': 'array', 'items': number, 'minItems': 6, 'maxItems': 6}
    def midpoint(bounds):
        if any(bounds[i] > bounds[i + 1] for i in (0, 2, 4)):
            raise ValueError('bounds are empty')
        return [bounds[i] / 2 + bounds[i+1] / 2 for i in (0, 2, 4)]
    registry.register('boundsCentre', {'bounds': {**bounds, 'required': True}}, vector, midpoint)
    registry.register('vectorLength', {'vector': {**vector, 'required': True}}, number,
                      lambda vector: math.hypot(*vector))
    registry.register('sinDegrees', {'angle': {**number, 'required': True}}, number,
                      lambda angle: math.sin(math.radians(angle)))
    registry.register('rangeCentre', {
        'range': {'type': 'array', 'items': number, 'minItems': 2, 'maxItems': 2, 'required': True}},
        number, lambda range: range[0] / 2 + range[1] / 2)
    from .spatial import register
    register(registry)
    from .adaptors.registry import ADAPTORS, binding, isolated
    for name, item in list(ADAPTORS.items()):
        if item.get("registerFunctions"):
            isolated(name, lambda: binding(item["registerFunctions"])(registry))
    return registry


FUNCTIONS = make_registry()
