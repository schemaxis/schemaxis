# Copyright (C) 2026 David L F Gaden
"""Shared typed option validation for all adaptors."""
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.directions import resolve_direction
from .errors import fail
from .core.faults import Fault, SchemaxisError

def convert_option(binding, value, location):
    if binding.get('convert') == 'direction':
        return list(resolve_direction(value, location=location).vector)
    return value


# Adaptors register trusted compilers for values whose native form Schemaxis must
# generate rather than accept as authored text. A declaration names a compiler,
# never an import path; an unregistered name fails closed.
COMPILERS = {}


def register_compiler(name, function):
    if not isinstance(name, str) or not name or not callable(function):
        fail('INVALID_COMPILER', 'compiler needs a nonempty name and a callable', str(name))
    if COMPILERS.get(name, function) is not function:
        fail('DUPLICATE_COMPILER', 'value compiler is already registered', name)
    COMPILERS[name] = function


def native_value(binding, value, location):
    """Return the value to assign natively: compiled when the binding names a compiler."""
    name = binding.get('compiler')
    if name is None:
        return value
    if name not in COMPILERS:
        fail('UNAVAILABLE_COMPILER', 'option value compiler is not registered', location, compiler=name)
    return COMPILERS[name](value, location)


def validate_binding(binding, value, location):
    native_value(binding, value, location)
    size=binding.get('tupleSize')
    if size and isinstance(value,list) and len(value)%size:
        fail('INVALID_LENGTH','native property values must form complete tuples',location,
             tupleSize=size,actual=len(value))
    types=binding.get('tupleElementTypes')
    if types and size and isinstance(value,list):
        # An 'index' element is a non-negative integer written as text; the native side would
        # otherwise convert other text silently (atoi gives 0).
        for position,item in enumerate(value):
            if types[position%size]=='index' and not (isinstance(item,str) and item.isascii() and item.isdigit()):
                fail('INVALID_ARGUMENT','tuple element must be a non-negative integer written as digits',
                     location+'['+str(position)+']',actual=item)
    if 'proxyChoices' in binding:
        choice=binding['proxyChoices'][value['type']]
        for key,item in value.get('options',{}).items():
            validate_binding(choice['options'][key],item,location+'.'+key)


def validate_options(declaration, values, location):
    result = validate_arguments({k: v['value'] for k, v in declaration['options'].items()}, values, location=location)
    result = {k: convert_option(declaration['options'][k], v, location + '.' + k) for k, v in result.items()}
    for key,value in result.items():validate_binding(declaration['options'][key],value,location+'.'+key)
    for condition in declaration.get('requires', []):
        option_name, expected = condition['when']
        if result.get(option_name) == expected and condition['option'] not in result:
            fail('MISSING_ARGUMENT', 'conditionally required option is missing', location + '.' + condition['option'])
    for check in declaration.get('checks', []):
        if check['kind'] == 'ordered':
            left, right = check['options']
            if result[left] > result[right]:
                fail('INVALID_RANGE', 'lower value exceeds upper value', location, options=[left, right])
        elif check['kind'] == 'firstItem':
            # The first element of an array option must be one of the accepted values.
            if not check.get('values') or not check.get('message') or check.get('option') not in declaration['options']:
                fail('INVALID_DECLARATION', 'firstItem check needs an option, values and a message', location)
            value = result.get(check['option'])
            # A malformed authored value is reported by the option's own type validation.
            if isinstance(value, list) and value and value[0] not in check['values']:
                raise SchemaxisError(Fault(
                    check.get('code', 'INVALID_ARGUMENT'), check['message'],
                    location + '.' + check['option'] + '[0]', 'pipeline',
                    observed={'value': value[0], 'accepted': list(check['values'])},
                    recovery=check.get('recovery')))
        elif check['kind'] == 'bounds':
            bounds = result[check['option']]
            if any(bounds[i] >= bounds[i+1] for i in (0, 2, 4)):
                fail('INVALID_BOUNDS', 'source extents must increase in each dimension', location)
    return result
