"""Validated, data-only Studio libraries and the host catalogue verification contract.

Libraries use inline ``baseDocument``, field ``testValues`` and a human-readable
``requires`` note when prerequisites are needed. Templates use either a confined
``file`` or an inline ``document``. No library content is evaluated as code.
"""
import copy
import math
from pathlib import Path
import re

from .errors import fail
from .storage import load
from .unfilled import find_unfilled, reject_unfilled

VERSION = 'schemaxis.studio-adaptor/2'
TYPES = {'number', 'integer', 'boolean', 'string', 'enum', 'vector3', 'bounds', 'colour',
         'path', 'id', 'nodeRef', 'axisRef', 'field', 'json'}
INTERPOLATION = re.compile(r'\$\{([^}:]+)\}')
LEGACY = re.compile(r'\$\{([^}:]+):([^}]*)\}')


def _check(condition, message, location='$'):
    if not condition:
        fail('INVALID_STUDIO_LIBRARY', message, location)


def _keys(value, allowed, location):
    _check(isinstance(value, dict), 'expected an object', location)
    _check(not set(value) - set(allowed), 'unsupported keys: ' + ', '.join(sorted(set(value) - set(allowed))), location)


def _text(value, location):
    _check(isinstance(value, str) and bool(value.strip()), 'expected nonempty text', location)


def _pointer(value):
    _check(isinstance(value, str) and (value == '' or value.startswith('/')) and not re.search(r'~(?![01])', value),
           'expected an RFC 6901 pointer')
    return [part.replace('~1', '/').replace('~0', '~') for part in value[1:].split('/')] if value else []


def _equal(left, right):
    if type(left) in (int, float) and type(right) in (int, float):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, list):
        return len(left) == len(right) and all(_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_equal(left[k], right[k]) for k in left)
    return left == right


def _field_value(value, spec, location):
    kind = spec['type']
    numeric = lambda item: type(item) is int or type(item) is float and math.isfinite(item)
    valid = {'number': lambda: numeric(value), 'integer': lambda: type(value) is int,
             'boolean': lambda: type(value) is bool,
             'enum': lambda: any(_equal(value, choice) for choice in spec['values']),
             'vector3': lambda: isinstance(value, list) and len(value) == 3 and all(map(numeric, value)),
             'colour': lambda: isinstance(value, list) and len(value) == 3 and all(map(numeric, value)),
             'bounds': lambda: isinstance(value, list) and len(value) == 6 and all(map(numeric, value)),
             'json': lambda: True}.get(kind, lambda: isinstance(value, str))()
    _check(valid, 'value does not match field type ' + kind, location)
    if kind == 'colour':
        _check(all(0 <= v <= 1 for v in value), 'colour components must be between zero and one', location)
    if kind == 'bounds':
        _check(all(value[i] <= value[i + 1] for i in (0, 2, 4)), 'bounds limits are reversed', location)
    if kind in ('id', 'nodeRef', 'axisRef', 'path'):
        _check(bool(value), 'field requires a nonempty value', location)
    if kind == 'id':
        _check(bool(re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', value)), 'invalid identifier', location)
    if kind == 'path' and spec.get('extensions'):
        _check(any(value.lower().endswith('.' + suffix.lstrip('*.').lower()) for suffix in spec['extensions']),
               'path extension is not allowed', location)
    if numeric(value):
        _check(('minimum' not in spec or value >= spec['minimum'])
               and ('maximum' not in spec or value <= spec['maximum']), 'value exceeds field limits', location)


def _fields(fields, location):
    _check(isinstance(fields, dict), 'fields must be an object', location)
    for identity, spec in fields.items():
        _text(identity, location)
        _keys(spec, ('label', 'type', 'required', 'default', 'minimum', 'maximum', 'values', 'extensions',
                     'acceptsKinds', 'description'), location + '/' + identity)
        _text(spec.get('label'), location)
        _check(isinstance(spec.get('type'), str) and spec['type'] in TYPES, 'unknown field type', location)
        _check('required' not in spec or type(spec['required']) is bool, 'required must be boolean', location)
        for key in ('minimum', 'maximum'):
            _check(key not in spec or type(spec[key]) in (int, float) and math.isfinite(spec[key]),
                   key + ' must be finite and numeric', location)
        if 'minimum' in spec and 'maximum' in spec:
            _check(spec['minimum'] <= spec['maximum'], 'field limits are reversed', location)
        for key in ('extensions', 'acceptsKinds'):
            _check(key not in spec or isinstance(spec[key], list)
                   and all(isinstance(v, str) for v in spec[key]), key + ' must be a string array', location)
        if spec['type'] == 'enum':
            _check(isinstance(spec.get('values'), list) and bool(spec['values']), 'enum requires values', location)
        if 'default' in spec:
            _field_value(spec['default'], spec, location)


def _body(value, fields, location):
    if isinstance(value, dict):
        if '$fill' in value:
            _check(set(value) == {'$fill'} and isinstance(value['$fill'], str) and value['$fill'] in fields,
                   'body marker must reference a declared field', location)
        else:
            for key, child in value.items():
                _check(not INTERPOLATION.search(key), 'interpolation applies to values, not object keys', location)
                _body(child, fields, location + '/' + key)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _body(child, fields, location + '/' + str(index))
    elif isinstance(value, str):
        for match in INTERPOLATION.finditer(value):
            _check(match[1] in fields and fields[match[1]]['type'] == 'id',
                   'string interpolation requires a declared id field', location)
        _check(len(set(INTERPOLATION.findall(value))) <= 1, 'one interpolated id field per string', location)


def migrate_library(data):
    """Copy a v1 library to v2; callers load template documents before migration."""
    data = copy.deepcopy(data)
    if data.get('version') != 'schemaxis.studio-adaptor/1':
        return data
    data['version'] = VERSION
    data['categories'] = [{'id': 'general', 'title': 'General', 'icon': 'layers'}]
    for group in ('templates', 'snippets'):
        for item in data.get(group, []):
            fields = {}

            def convert(value, key=''):
                if isinstance(value, str):
                    matches = list(LEGACY.finditer(value))
                    for match in matches:
                        kind = 'nodeRef' if match[1] == 'source' else 'string'
                        if key == 'id' or match[0] != value:
                            kind = 'id'
                        fields[match[1]] = {'label': match[1], 'type': kind, 'default': match[2], 'required': True}
                    if len(matches) == 1 and matches[0][0] == value:
                        return {'$fill': matches[0][1]}
                    return LEGACY.sub(lambda m: '${' + m[1] + '}', value)
                if isinstance(value, list):
                    return [convert(v, key) for v in value]
                if isinstance(value, dict):
                    return {k: convert(v, k) for k, v in value.items()}
                return value

            if group == 'snippets':
                item['inserts'] = [convert(item.pop('insert'))]
                item['category'] = 'general'
                if data.get('templates') and 'document' in data['templates'][0]:
                    item.setdefault('baseDocument', copy.deepcopy(data['templates'][0]['document']))
            else:
                item['document'] = convert(item.get('document', {}))
            item['fields'] = fields
    return data


def validate_library(data):
    """Validate strict v2 metadata after template files have been loaded."""
    _keys(data, ('version', 'categories', 'templates', 'snippets', 'viewers', 'subsets', 'baseDocument',
                 'testValues', 'requires', 'helpGuide'), '$')
    _check(data.get('version') == VERSION, 'unsupported Studio library version')
    if 'helpGuide' in data:
        _text(data['helpGuide'], '$.helpGuide')
    for key in ('categories', 'templates', 'snippets', 'viewers', 'subsets'):
        _check(isinstance(data.get(key, []), list), key + ' must be an array')
    _check(all(v in ('3d', 'image', 'table', 'text') for v in data.get('viewers', [])), 'unknown viewer')
    for subset in data.get('subsets', []):
        _keys(subset, ('id', 'title', 'description', 'operations'), '$.subsets')
        _text(subset.get('id'), '$.subsets.id')
        _check(isinstance(subset.get('operations'), list)
               and all(isinstance(v, str) for v in subset['operations']), 'subset requires operation names')
    categories = set()
    for category in data.get('categories', []):
        _keys(category, ('id', 'title', 'icon', 'description'), '$.categories')
        for key in ('id', 'title'):
            _text(category.get(key), '$.categories.' + key)
        _check(category['id'] not in categories, 'duplicate category')
        categories.add(category['id'])
    identities = set()
    for group in ('templates', 'snippets'):
        _check(isinstance(data.get(group, []), list), group + ' must be an array')
        for item in data.get(group, []):
            location = '$.' + group
            _keys(item, ('id', 'title', 'description', 'icon', 'category', 'complexity', 'fields', 'inserts',
                         'file', 'document', 'baseDocument', 'testValues', 'requires', 'testCursor'), location)
            _check(not (set(item) & ({'inserts'} if group == 'templates' else {'document', 'file'})),
                   'item contains fields for the other library kind', location)
            for key in ('id', 'title'):
                _text(item.get(key), location + '.' + key)
            _check(item['id'] not in identities, 'duplicate library item id', location)
            identities.add(item['id'])
            if 'testCursor' in item:
                _pointer(item['testCursor'])
            fields = item.get('fields', {})
            _fields(fields, location + '.fields')
            for holder in (data, item):
                if 'requires' in holder:
                    _text(holder['requires'], location + '.requires')
                if 'baseDocument' in holder:
                    _check(isinstance(holder['baseDocument'], dict), 'baseDocument must be an object', location)
                _check(isinstance(holder.get('testValues', {}), dict), 'testValues must be an object', location)
            for field, value in item.get('testValues', {}).items():
                _check(field in fields, 'testValues must reference declared fields', location)
                _field_value(value, fields[field], location + '.testValues.' + field)
            if group == 'templates':
                _check(isinstance(item.get('document'), dict), 'template requires a document', location)
                _body(item['document'], fields, location)
            else:
                _check(item.get('category') in categories, 'snippet must name a declared category', location)
                _check(item.get('complexity', 'simple') in ('simple', 'composite'), 'unknown complexity', location)
                _check(isinstance(item.get('inserts'), list) and bool(item['inserts']),
                       'snippet needs inserts', location)
                for insert in item['inserts']:
                    _keys(insert, ('at', 'values', 'merge'), location + '.inserts')
                    if insert.get('at') != '@cursor':
                        _pointer(insert.get('at'))
                    else:
                        _check('testCursor' in item, '@cursor snippets require testCursor', location)
                    _check(('values' in insert) != ('merge' in insert), 'choose values or merge', location)
                    if 'values' in insert:
                        _check(isinstance(insert['values'], list) and bool(insert['values']),
                               'values need an array', location)
                        _check(insert['at'] != '@cursor' or len(insert['values']) == 1,
                               '@cursor requires exactly one value', location)
                    else:
                        _check(isinstance(insert['merge'], dict), 'merge needs an object', location)
                    _body(insert.get('values', insert.get('merge')), fields, location)
    return data


def load_library(provider, directory=None):
    """Return normalised metadata with template bodies; paths stay inside the package."""
    from .adaptors import registry
    directory = Path(directory) if directory is not None else Path(str(registry.adaptor_files(provider)))
    path = directory / 'studio.json'
    if not path.is_file():
        return {'version': VERSION, 'categories': [], 'templates': [], 'snippets': []}
    data = load(path.read_text(encoding='utf-8'))
    _check(isinstance(data, dict), 'library must be an object', str(path))
    for item in data.get('templates', []):
        _check(isinstance(item, dict), 'template must be an object')
        _check(('file' in item) != ('document' in item), 'template needs either file or document')
        if 'file' in item:
            filename = item['file']
            _text(filename, '$.templates.file')
            parts = filename.split('/')
            _check(not Path(filename).is_absolute() and not any(v in ('', '.', '..') for v in parts)
                   and '\\' not in filename and '\x00' not in filename, 'template file must be confined')
            target = directory.joinpath(*parts)
            _check(directory.resolve() in target.resolve().parents and not target.is_symlink(),
                   'template file must be confined')
            try:
                from .core.documents import document_format, load_document_file
                item['document'] = load_document_file(target) if document_format(target) == 'yaml' else load(target.read_text(encoding='utf-8'))
            except OSError as error:
                fail('INVALID_STUDIO_LIBRARY', str(error), str(target))
    return validate_library(migrate_library(data))


def fill_fields(value, fields, replacements=None):
    """Substitute supplied fields, enriching the others as durable markers."""
    replacements = replacements or {}
    if isinstance(value, dict):
        if '$fill' in value:
            identity = value['$fill']
            if identity in replacements:
                return copy.deepcopy(replacements[identity])
            return {'$fill': identity, **copy.deepcopy(fields[identity])}
        return {key: fill_fields(child, fields, replacements) for key, child in value.items()}
    if isinstance(value, list):
        return [fill_fields(child, fields, replacements) for child in value]
    if isinstance(value, str) and INTERPOLATION.search(value):
        identity = INTERPOLATION.search(value)[1]
        if identity not in replacements:
            return {'$fill': identity, **copy.deepcopy(fields[identity]), 'template': value}
        return INTERPOLATION.sub(lambda match: str(replacements[match[1]]), value)
    return copy.deepcopy(value)


def _merge(target, value):
    for key, child in value.items():
        if isinstance(child, dict) and isinstance(target.get(key), dict):
            _merge(target[key], child)
        else:
            target[key] = copy.deepcopy(child)


def apply_inserts(document, inserts, *, cursor=''):
    """Pure sequential application used by catalogue tests; never mutates its input."""
    result = copy.deepcopy(document)
    for insert in inserts:
        pointer = cursor if insert['at'] == '@cursor' else insert['at']
        parts = _pointer(pointer)
        parent = result
        for index, part in enumerate(parts[:-1]):
            child = [] if parts[index + 1] == '-' or parts[index + 1].isdigit() else {}
            if isinstance(parent, list):
                position = int(part)
                while len(parent) <= position:
                    parent.append(copy.deepcopy(child))
                parent = parent[position]
            else:
                parent = parent.setdefault(part, child)
        key = parts[-1] if parts else None
        if 'merge' in insert:
            if key is None:
                target = result
            elif isinstance(parent, list):
                target = parent[int(key)]
            else:
                target = parent.setdefault(key, {})
            _check(isinstance(target, dict), 'merge target must be an object', pointer)
            _merge(target, insert['merge'])
        elif key is None:
            result = copy.deepcopy(insert['values'][0])
        elif isinstance(parent, list):
            index = len(parent) if key == '-' else int(key)
            if insert['at'] == '@cursor' and index < len(parent):
                parent[index] = copy.deepcopy(insert['values'][0])
            else:
                parent[index:index] = copy.deepcopy(insert['values'])
        else:
            _check(len(insert['values']) == 1, 'object member accepts one value', pointer)
            parent[key] = copy.deepcopy(insert['values'][0])
    return result


def instantiate_item(library, item, *, provider=None, filled=True):
    """Materialise one test case; every used field needs a default or test value."""
    fields = item.get('fields', {})
    values = {key: spec['default'] for key, spec in fields.items() if 'default' in spec} if filled else {}
    if filled:
        values.update({k: v for k, v in library.get('testValues', {}).items() if k in fields})
        values.update(item.get('testValues', {}))
        for identity, value in values.items():
            _field_value(value, fields[identity], '$.testValues.' + identity)
    if 'document' in item:
        result = fill_fields(item['document'], fields, values)
    else:
        base = item.get('baseDocument', library.get('baseDocument'))
        if base is None:
            from .console_session import ConsoleSession
            base = ConsoleSession._empty(provider)
        result = apply_inserts(base, fill_fields(item['inserts'], fields, values), cursor=item.get('testCursor', ''))
    if filled:
        reject_unfilled(result)
    return result


def plan_item(document):
    """Host-only plan for a generated catalogue case (including workflow designs)."""
    from .adaptors import registry
    from . import workflow
    if document.get('version', '').startswith('schemaxis.workflow-design/'):
        from .workflow_design import compile as compile_design
        return workflow.inspect_plan(compile_design(document))
    if document.get('version') == 'schemaxis.workflow/1':
        return workflow.inspect_plan(document)
    return registry.plan(document)
