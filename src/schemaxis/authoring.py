"""Shared revision transitions for JSON source, properties and console commands.

Persistence and native ownership belong to the session. Each transition is one
undo group; source text is retained exactly, including invalid JSON.
"""
import copy
import json
import re
from .storage import encoded, load
from .core.documents import load_document
from .errors import fail
from .core.faults import SchemaxisError
from .observations import at_pointer

LIMIT = 1024 * 1024
FIELDS = ('document', 'name', 'file', 'selected', 'source', 'sourceFormat', 'diagnostics')


def text(record):
    return record.get('source', json.dumps(record['document'], indent=2, ensure_ascii=False) + '\n')


def snapshot(record):
    return copy.deepcopy({k: record[k] for k in FIELDS if k in record})


def check(record, identity, expected_document, expected_revision):
    if (identity != expected_document or type(expected_revision) is not int
            or record['revision'] != expected_revision):
        fail('STALE_REVISION', 'document or revision changed; refresh before editing',
             document=identity, revision=record['revision'])


def analyse(source, validate, format="json"):
    if not isinstance(source, str) or len(source.encode('utf-8')) > LIMIT:
        fail('INVALID_SOURCE', 'source must be UTF-8 JSON or YAML text no larger than one MiB')
    document = None
    try:
        # Retain exact syntax coordinates before strict duplicate/nonfinite checks.
        if format == "json": json.loads(source)
        document = load(source) if format == "json" else load_document(source, format)
        if not isinstance(document, dict):
            fail('INVALID_DOCUMENT', 'authored document must be an object')
        validate(document)
        return document, []
    except json.JSONDecodeError as error:
        return None, [{'code': 'INVALID_JSON', 'message': error.msg, 'location': '$',
                       'line': error.lineno, 'column': error.colno, 'offset': error.pos}]
    except SchemaxisError as error:
        return document, [source_diagnostic(source, document, error.fault.to_dict(), format)]


def replace(state, identity, values):
    result = copy.deepcopy(state)
    record = result['documents'][identity]
    record['undo'].append(snapshot(record))
    record['redo'] = []
    record.update(copy.deepcopy(values))
    result['nextRevision'] += 1
    record['revision'] = result['nextRevision']
    return result


def travel(state, identity, direction):
    result = copy.deepcopy(state)
    record = result['documents'][identity]
    target = 'redo' if direction == 'undo' else 'undo'
    if not record[direction]:
        fail('NO_' + direction.upper(), 'there is no authored operation to ' + direction)
    previous = record[direction].pop()
    record[target].append(snapshot(record))
    for key in FIELDS:
        record.pop(key, None)
    record.update(previous)
    result['nextRevision'] += 1
    record['revision'] = result['nextRevision']
    return result


def patch(document, edits):
    """Atomic ordered group of add/replace/remove/test RFC 6901 edits."""
    if not isinstance(edits, list) or not 1 <= len(edits) <= 100:
        fail('INVALID_PATCH', 'provide 1..100 edits in one undo group')
    result = copy.deepcopy(document)
    for edit in edits:
        if not isinstance(edit, dict) or set(edit)-{'op', 'path', 'value'}:
            fail('INVALID_PATCH', 'edit requires op, path and optional value')
        op, pointer = edit.get('op'), edit.get('path')
        if op not in ('add', 'replace', 'remove', 'test') or not isinstance(pointer, str):
            fail('INVALID_PATCH', 'use add, replace, remove or test with a JSON pointer')
        if (op != 'remove') != ('value' in edit):
            fail('INVALID_PATCH', 'value is required except for remove', pointer or '$')
        if op == 'test':
            if encoded(at_pointer(result, pointer)) != encoded(edit['value']):
                fail('PATCH_TEST_FAILED', 'current value differs', pointer or '$')
            continue
        if not pointer:
            if op == 'remove': fail('INVALID_PATCH', 'cannot remove the document root')
            result = copy.deepcopy(edit['value'])
            continue
        parent, _, token = pointer.rpartition('/')
        if not pointer.startswith('/') or re.search('~(?![01])', token):
            fail('INVALID_POINTER', 'use an RFC 6901 pointer', pointer)
        container = at_pointer(result, parent)
        token = token.replace('~1', '/').replace('~0', '~')
        if isinstance(container, list):
            if token == '-' and op == 'add':
                index = len(container)
            elif re.fullmatch('0|[1-9][0-9]*', token):
                index = int(token)
            else:
                fail('INVALID_POINTER', 'array index is invalid', pointer)
            if index > len(container) or (op != 'add' and index == len(container)):
                fail('INVALID_POINTER', 'array index is out of range', pointer)
            if op == 'add': container.insert(index, copy.deepcopy(edit['value']))
            elif op == 'replace': container[index] = copy.deepcopy(edit['value'])
            else: container.pop(index)
        elif isinstance(container, dict):
            if op != 'add' and token not in container:
                fail('INVALID_POINTER', 'member does not exist', pointer)
            if op == 'remove': del container[token]
            else: container[token] = copy.deepcopy(edit['value'])
        else:
            fail('INVALID_POINTER', 'parent must be an object or array', pointer)
    if len(encoded(result)) > LIMIT:
        fail('INVALID_DOCUMENT', 'edited document exceeds one MiB')
    return result


def locate(source, pointer=None, offset=None, format="json"):
    if (pointer is None) == (offset is None):
        fail("INVALID_LOCATION", "choose one pointer or source offset")
    if format == "yaml":
        from .core.yaml_documents import ranges, load as yaml_load
        spans = ranges(source)
        if offset is not None:
            if type(offset) is not int or not 0 <= offset <= len(source):
                fail("INVALID_LOCATION", "source offset is out of range")
            matches = [(key, span) for key, span in spans.items() if span[0] <= offset <= span[1]]
            pointer = max(matches, key=lambda pair: len(pair[0]))[0] if matches else ""
        if pointer not in spans: fail("INVALID_POINTER", "pointer has no source value", str(pointer))
        start, end = spans[pointer]
        return {"pointer": pointer, "start": start, "end": end,
                "line": source.count("\n", 0, start)+1, "column": start-source.rfind("\n", 0, start),
                "value": at_pointer(yaml_load(source), pointer)}

    """Map a JSON value pointer to an exact source range, or a caret to its value."""
    if (pointer is None) == (offset is None):
        fail('INVALID_LOCATION', 'choose one pointer or source offset')
    load(source)  # strict JSON, including duplicate keys
    if offset is not None and (type(offset) is not int or not 0 <= offset <= len(source)):
        fail('INVALID_LOCATION', 'source offset is out of range')
    spans = {}
    decoder = json.JSONDecoder()

    def whitespace(index):
        while index < len(source) and source[index].isspace(): index += 1
        return index

    def value(index, path):
        start = whitespace(index)
        index = start
        if source[index] == '{':
            index = whitespace(index+1)
            while source[index] != '}':
                key, index = decoder.raw_decode(source, index)
                index = whitespace(index)+1  # colon, syntax already validated
                index = value(index, path+'/'+key.replace('~', '~0').replace('/', '~1'))
                index = whitespace(index)
                if source[index] == ',': index = whitespace(index+1)
            index += 1
        elif source[index] == '[':
            index, item = whitespace(index+1), 0
            while source[index] != ']':
                index = whitespace(value(index, path+'/'+str(item)))
                item += 1
                if source[index] == ',': index = whitespace(index+1)
            index += 1
        else:
            _, index = decoder.raw_decode(source, index)
        spans[path] = (start, index)
        return index

    value(0, '')
    if offset is not None:
        candidates = [(end-start, path) for path, (start, end) in spans.items() if start <= offset < end]
        pointer = min(candidates)[1] if candidates else ''
    if pointer not in spans:
        fail('INVALID_POINTER', 'pointer has no source value', str(pointer))
    start, end = spans[pointer]
    return {'pointer': pointer, 'start': start, 'end': end,
            'line': source.count('\n', 0, start)+1,
            'column': start-source.rfind('\n', 0, start),
            'value': at_pointer(load(source), pointer)}


def source_diagnostic(source, document, fault, format="json"):
    """Retain fault provenance and add an authored address and source coordinates."""
    result = dict(fault)
    for key in ('line', 'column', 'offset'):
        if key in result.get('observed', {}): result[key] = result['observed'][key]
    location = result.get('pointer', result.get('location', '$'))
    if location.startswith('/'):
        pointer = location
    elif location == '$':
        pointer = ''
    else:
        parts = re.sub(r'\[(\d+)\]', r'.\1', re.sub(r'^\$\.?', '', location)).split('.')
        if isinstance(document, dict):
            for index, node in enumerate(document.get('nodes', []) if isinstance(document.get('nodes'), list) else []):
                if isinstance(node, dict) and node.get('id') == parts[0]:
                    rest = parts[1:]
                    group = next((key for key in ('options', 'inputs') if rest and rest[0] in node.get(key, {})), None)
                    if group is None and rest and rest[0] not in ('id', 'filter', 'options', 'inputs', 'onVisit'):
                        from .adaptors import registry
                        try:
                            provider, _ = registry.resolve(document)
                            declaration = registry.declarations(provider).get(node.get('filter'), {})
                            group = next((key for key in ('options', 'inputs') if rest[0] in declaration.get(key, {})), None)
                        except SchemaxisError:
                            pass
                    parts = ['nodes', str(index)] + ([group] if group else []) + rest
                    break
        pointer = '/' + '/'.join(part.replace('~', '~0').replace('/', '~1') for part in parts)
    result['pointer'] = pointer
    # Missing keys keep their exact intended pointer; highlight the containing value.
    candidate = pointer
    if document is not None:
        while True:
            try:
                span = locate(source, pointer=candidate, format=format)
                result.update(line=span['line'], column=span['column'], offset=span['start'],
                              sourcePointer=candidate)
                break
            except SchemaxisError:
                if not candidate:
                    break
                candidate = candidate.rpartition('/')[0]
    observed = result.get('observed', {})
    if observed.get('keys'):
        result['message'] += ': ' + ', '.join(map(str, observed['keys']))
    if result.get('recovery'):
        result['message'] += ' ' + result['recovery']
    return result


def render(record, document):
    if record.get('sourceFormat', 'json') == 'yaml':
        from .core.yaml_documents import reconcile, dump
        return reconcile(text(record), document) if record.get('document') is not None else dump(document)
    return json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
