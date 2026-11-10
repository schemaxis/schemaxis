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
