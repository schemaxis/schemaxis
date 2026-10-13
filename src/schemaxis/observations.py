"""Bounded, exact JSON observations with pointers into retained evidence."""
import copy
import re
from .capabilities import digest, response_bytes
from .core.faults import Fault, SchemaxisError


def fail(code, message, location='$', **observed):
    raise SchemaxisError(Fault(code, message, location, 'agent', observed=observed,
                              recovery='Read current task/job state and correct the request before retrying.'))


def at_pointer(value, pointer):
    if not isinstance(pointer, str) or len(pointer) > 2048 or (pointer and not pointer.startswith('/')):
        fail('INVALID_POINTER', 'use an RFC 6901 pointer', 'pointer')
    try:
        for token in pointer.split('/')[1:] if pointer else []:
            if re.search('~(?![01])', token):
                raise ValueError('invalid escape')
            token = token.replace('~1', '/').replace('~0', '~')
            if isinstance(value, list):
                if not re.fullmatch('0|[1-9][0-9]*', token):
                    raise ValueError('invalid index')
                value = value[int(token)]
            else:
                value = value[token]
        return value
    except (KeyError, IndexError, TypeError, ValueError):
        fail('INVALID_POINTER', 'pointer does not address retained evidence', pointer or '$')


def bounded(value, identity, *, pointer='', offset=0, limit=12, max_bytes=8192, revision=None):
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        fail('INVALID_PAGE', 'limit must be 1..100 and offset nonnegative')
    if type(max_bytes) is not int or not 2048 <= max_bytes <= 65536:
        fail('INVALID_BYTE_LIMIT', 'max_bytes must be 2048..65536')
    stamp = digest(value)
    if revision is not None and revision != stamp:
        fail('STALE_OBSERVATION', 'evidence changed; restart observation', revision=stamp)
    selected = at_pointer(value, pointer)
    base = {'identity': identity, 'revision': stamp, 'pointer': pointer, 'maxBytes': max_bytes}
    result = {**base, 'mode': 'value', 'value': copy.deepcopy(selected)}
    if offset == 0 and response_bytes(result) <= max_bytes:
        return result
    if not isinstance(selected, (dict, list)):
        fail('OBSERVATION_TOO_LARGE', 'scalar exceeds budget; use the retained file or a larger budget')
    keys = sorted(selected) if isinstance(selected, dict) else list(range(len(selected)))
    if offset >= len(keys) and offset != 0:
        fail('INVALID_PAGE', 'offset is beyond evidence membership')
    end = min(len(keys), offset + limit)
    while end > offset:
        items = []
        for key in keys[offset:end]:
            child = selected[key]
            child_pointer = pointer + '/' + str(key).replace('~', '~0').replace('/', '~1')
            item = {'key': key, 'pointer': child_pointer,
                    'kind': 'object' if isinstance(child, dict) else 'array' if isinstance(child, list) else 'scalar'}
            if response_bytes(child) <= 256:
                item['value'] = copy.deepcopy(child)
            items.append(item)
        result = {**base, 'mode': 'members', 'container': 'object' if isinstance(selected, dict) else 'array',
                  'items': items, 'page': {'offset': offset, 'returned': end-offset, 'total': len(keys),
                                        'nextOffset': end if end < len(keys) else None}}
        if response_bytes(result) <= max_bytes:
            return result
        end -= 1
    fail('OBSERVATION_TOO_LARGE', 'one complete member exceeds budget; increase max_bytes')
