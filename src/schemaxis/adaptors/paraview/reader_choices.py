# Copyright (C) 2026 David L. F. Gaden
"""Deferred reader selection; host validation and native domain resolution.

A selection is every available name, one pattern, or a list of entries. A list
entry is an exact name or a ``{"pattern": ...}`` regular expression.
"""
import re
from schemaxis.errors import fail

PATTERN = {'type': 'object', 'properties': {'pattern': {'type': 'string', 'minLength': 1, 'maxLength': 256, 'required': True}}}


def selection(path, default=None):
    entry = {'type': 'union', 'options': [{'type': 'string', 'minLength': 1}, PATTERN]}
    spec = {'type': 'union', 'options': [
        {'type': 'array', 'items': entry, 'minItems': 1},
        {'type': 'object', 'properties': {'select': {'type': 'enum', 'values': ['all'], 'required': True}}},
        PATTERN]}
    if default is not None: spec['default'] = default
    return {'value': spec, 'path': [path], 'readerSelection': True, 'compiler': 'paraview-reader-selection'}


def is_deferred(value):
    """True when the reader's available names are needed to resolve ``value``."""
    return isinstance(value, dict) or any(isinstance(entry, dict) for entry in value)


def compile_pattern(entry, location):
    try: return re.compile(entry['pattern'])
    except re.error as error: fail('INVALID_PATTERN', str(error), location)


def resolve_selection(value, available, location):
    if isinstance(value, list):
        if not is_deferred(value): return value
        result = []
        for index, entry in enumerate(value):
            if isinstance(entry, dict):
                pattern = compile_pattern(entry, location)
                names = [name for name in available if pattern.search(name)]
                if not names:
                    fail('EMPTY_SELECTION', 'Reader selection entry matched no available names',
                         '%s[%d]' % (location, index), pattern=entry['pattern'], available=list(available))
            else: names = [entry]
            result.extend(name for name in names if name not in result)
        return result
    if 'pattern' in value:
        pattern = compile_pattern(value, location)
        result = [name for name in available if pattern.search(name)]
    else: result = list(available)
    if not result:
        fail('EMPTY_SELECTION', 'Reader selection matched no available names', location, available=list(available))
    return result


def validate_selection(value, location):
    for entry in value if isinstance(value, list) else [value]:
        if isinstance(entry, dict) and 'pattern' in entry: compile_pattern(entry, location)
    return value


from schemaxis.bindings import register_compiler
register_compiler('paraview-reader-selection', validate_selection)


def selection_fields(declaration):
    if declaration.get('inputs') or not declaration.get('nativeIdentity', '').startswith('sources/'):
        return ()
    return tuple(key for key, binding in declaration['options'].items()
                 if binding.get('path') == [key]
                 and 'vtkSMArraySelectionDomain' in binding.get('nativeDomains', ())
                 and binding['value'].get('type') == 'array'
                 and binding['value'].get('items', {}).get('type') == 'string')


def single_file_source(declaration):
    """Return the sole file constructor of an independent generated data source."""
    if (declaration.get('inputs') or not declaration.get('loadsData')
            or not declaration.get('nativeIdentity', '').startswith('sources/')):
        return None
    constructors = [(key, binding) for key, binding in declaration['options'].items()
                    if binding.get('constructor')]
    if len(constructors) != 1:
        return None
    key, binding = constructors[0]
    value = binding['value']
    if ('vtkSMFileListDomain' in binding.get('nativeDomains', ()) and
            (value.get('type') == 'string' or value.get('type') == 'array'
             and value.get('items', {}).get('type') == 'string')):
        return key
    return None


def available_choices(declaration, source, properties):
    """Keep optional names bounded independently of the inspection reply."""
    result, remaining = {}, 65536
    for field in selection_fields(declaration):
        if field not in properties:
            continue
        try:
            available = getattr(source.GetProperty(field), 'Available', None)
        except (AttributeError, RuntimeError, TypeError):
            continue
        if available is None or len(available) > 5000:
            continue
        names = []
        for value in available:
            if not isinstance(value, str) or len(value) > remaining:
                break
            remaining -= len(value.encode('utf-8')) + 4
            if remaining < 0:
                break
            names.append(value)
        else:
            result[field] = list(dict.fromkeys(names))
    return result
