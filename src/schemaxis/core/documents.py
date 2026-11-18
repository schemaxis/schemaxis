# Copyright (C) 2026 David L. F. Gaden.
"""Bounded, typed references within JSON authoring documents.

Authored composition and arithmetic are closed data operations; no filesystem reads or runtime handles.
"""
from copy import deepcopy
import json
import math
import re

from .faults import SchemaxisError, Fault
from .composition import evaluate


def _fail(code, message, location):
    raise SchemaxisError(Fault(code, message, location, 'input',
                         recovery='Use a complete {"$document": "/section/key"} value pointing to existing JSON data.'))


def reference_pointer(reference, site):
    """Address a document marker without reading or evaluating its target.

    ``site`` is the marker's RFC 6901 address. Relative paths start at its
    containing object, exactly as authored document resolution does.
    """
    if not isinstance(reference, str) or not reference.startswith(('/', './', '../')):
        _fail('INVALID_DOCUMENT_REFERENCE', 'Use an absolute, ./ or ../ document pointer', '$' + site)
    if re.search(r'~(?![01])', reference):
        _fail('INVALID_DOCUMENT_REFERENCE', 'Invalid JSON pointer escape', '$' + site)
    if reference.startswith('/'):
        return reference
    parts = site.split('/')[1:-1]
    for token in reference.split('/'):
        if token == '.':
            continue
        if token == '..':
            if not parts:
                _fail('INVALID_DOCUMENT_REFERENCE', 'Relative reference escapes the document root', '$' + site)
            parts.pop()
        else:
            parts.append(token)
    return '/' + '/'.join(parts) if parts else ''


def load_document(text, format="json"):
    """Read strict JSON or the optional, bounded YAML 1.2 authoring profile."""
    if format == "yaml":
        from .yaml_documents import load
        return load(text)
    if format != "json":
        _fail("INVALID_FORMAT", "Choose json or yaml", "$")

    # Reject duplicate keys and non-finite constants in canonical JSON.
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _fail('DUPLICATE_KEY', f'Duplicate JSON key {key!r}', '$')
            result[key] = value
        return result

    def constant(value):
        _fail('INVALID_JSON', f'Non-finite JSON constant {value}', '$')

    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, RecursionError) as error:
        _fail('INVALID_JSON', str(error), '$')


def document_format(path=None, format=None):
    """Explicit syntax overrides extension; ambiguous names remain strict JSON."""
    if format is not None:
        if format not in ('json', 'yaml'):
            _fail('INVALID_FORMAT', 'Choose json or yaml', '$')
        return format
    from pathlib import Path
    return 'yaml' if path is not None and Path(path).suffix.lower() in ('.yaml', '.yml') else 'json'


def load_document_file(path, format=None):
    from pathlib import Path
    return load_document(Path(path).read_text(encoding='utf-8'), document_format(path, format))


RESERVED = re.compile(r'%%.*%%', re.DOTALL)


def refuse_reserved(value, location='$'):
    """Refuse an authored document that uses a field name Schemaxis keeps for its own records.

    A name written between double percent signs is added by Schemaxis to the
    documents it prepares for each visit of a study, and is never authored.
    """
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and RESERVED.fullmatch(key):
                raise SchemaxisError(Fault(
                    'RESERVED_KEY', f'The field name {key!r} is reserved for internal use', location, 'input',
                    observed={'key': key},
                    recovery='Remove the field. Names written between double percent signs are added by '
                             'Schemaxis itself and are not authored.'))
            refuse_reserved(item, location + '.' + key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            refuse_reserved(item, location + '[' + str(index) + ']')


_ENTRY = re.compile(r'(/operations/[0-9]+/document)?/(dimensions|settings|definitions)/([^/]+)')
_OPERATION = re.compile(r'/operations/[0-9]+/document(?:/|$)')


def _entry_reference(document, path, active):
    """Name of an expression-valued entry that is being read through a reference, or None.

    A string expression is evaluated among the names of the document that
    holds it. Copying its text to the place that refers to it would evaluate
    it among other names and schedule its sweeps a second time, so the
    reference reads the entry by name instead.
    """
    match = _ENTRY.fullmatch(path)
    if match is None:
        return None
    key = match.group(3).replace('~1', '/').replace('~0', '~')
    if '`' in key or any(ord(character) < 32 for character in key):
        return None
    sites = {found.group(0).rstrip('/') for found in map(_OPERATION.match, active) if found}
    name = match.group(2) + '.`' + key + '`'
    if sites == ({match.group(1)} if match.group(1) else set()):
        return name
    version = document.get('version')
    if match.group(1) is None and isinstance(version, str) and version.startswith('schemaxis.workflow/'):
        return 'workflow.' + name
    return None


def resolve_document(document, *, max_values=100000, max_depth=128, value_resolver=None,
                     marker_resolver=None, defer=None):
    """Return independent resolved JSON and lookup provenance.

    Absolute references use RFC 6901 pointers; ./ and ../ are relative
    to the marker's containing object or array at its definition site.
    A marker replaces the entire value,
    preserving its JSON type. Runtime output references are unaffected.
    """
    if not isinstance(document, dict):
        _fail('INVALID_DOCUMENT', 'Document must be a JSON object', '$')
    evidence = []
    active = set()
    remaining = max_values
    reading = None

    def follow(value, target, origin, depth):
        nonlocal reading
        reading = None if target == origin or target.startswith(origin + '/') else target
        return visit(value, target, depth)

    def visit(value, path, depth):
        nonlocal remaining, reading
        referenced, reading = reading is not None and reading == path, None
        remaining -= 1
        location = '$' + path
        if remaining < 0 or depth > max_depth:
            _fail('DOCUMENT_LIMIT', 'Document expansion exceeds its size or depth limit', location)
        if path in active:
            _fail('DOCUMENT_CYCLE', 'Cyclic document reference', location)
        active.add(path)
        try:
            if isinstance(value, dict):
                if marker_resolver is not None:
                    handled, result = marker_resolver(value, path, lambda item, where: follow(item, where, path, depth + 1))
                    if handled:
                        return result
                if '$value' in value and value_resolver is not None:
                    if set(value) != {'$value', 'args'}:
                        _fail('INVALID_EXPRESSION', '$value requires a name and args object', location)
                    arguments = visit(value['args'], path + '/args', depth + 1)
                    if defer is not None and defer(arguments):
                        return {'$value': value['$value'], 'args': arguments}
                    result = value_resolver(value['$value'], arguments, location)
                    evidence.append({'location': location, 'function': value['$value'], 'effectiveValue': deepcopy(result)})
                    return result
                if '$expr' in value:
                    if set(value) != {'$expr'}:
                        _fail('INVALID_EXPRESSION', 'Expression marker must be the entire value', location)
                    if isinstance(value['$expr'], str):
                        return {'$expr': (_entry_reference(document, path, active) if referenced else None)
                                or value['$expr']}
                    expression = visit(value['$expr'], path + '/$expr', depth + 1)
                    if defer is not None and defer(expression):
                        return {'$expr': expression}
                    result = evaluate(expression, location)
                    evidence.append({'location': location, 'operation': expression['op'], 'effectiveValue': deepcopy(result)})
                    return result
                if '$document' in value:
                    pointer = value['$document']
                    if set(value) != {'$document'} or not isinstance(pointer, str) or not pointer.startswith(('/', './', '../')):
                        _fail('INVALID_DOCUMENT_REFERENCE', 'Reference must contain only $document with an absolute pointer or ./ or ../ path', location)
                    reference = pointer
                    pointer = reference_pointer(pointer, path)
                    target = document
                    for token in pointer[1:].split('/') if pointer else []:
                        if re.search(r'~(?![01])', token):
                            _fail('INVALID_DOCUMENT_REFERENCE', 'Invalid JSON pointer escape', location)
                        token = token.replace('~1', '/').replace('~0', '~')
                        if isinstance(target, dict) and token in target:
                            target = target[token]
                        elif isinstance(target, list) and re.fullmatch(r'0|[1-9][0-9]*', token) and int(token) < len(target):
                            target = target[int(token)]
                        else:
                            _fail('UNKNOWN_DOCUMENT_REFERENCE', f'No document value at {pointer!r}', location)
                    evidence.append({'location': location, 'reference': reference, 'pointer': pointer})
                    return follow(target, pointer, path, depth + 1)
                result = {}
                for key, item in value.items():
                    if not isinstance(key, str):
                        _fail('INVALID_JSON', 'Object keys must be strings', location)
                    escaped = key.replace('~', '~0').replace('/', '~1')
                    result[key] = visit(item, path + '/' + escaped, depth + 1)
                return result
            if isinstance(value, list):
                return [visit(item, path + '/' + str(i), depth + 1) for i, item in enumerate(value)]
            if value is None or isinstance(value, (str, bool, int)):
                return value
            if isinstance(value, float) and math.isfinite(value):
                return value
            _fail('INVALID_JSON', 'Value must be finite JSON data', location)
        finally:
            active.remove(path)

    return visit(document, '', 0), deepcopy(evidence)
