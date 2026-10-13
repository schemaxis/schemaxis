"""Closed authored-value operations; no evaluation of Python or native objects."""
from copy import deepcopy
import math

from .faults import SchemaxisError, Fault


def evaluate(expression, location):
    def fail(message, suffix=''):
        raise SchemaxisError(Fault('INVALID_EXPRESSION', message, location + suffix, 'input'))

    if not isinstance(expression, dict) or set(expression) - {'op', 'args', 'conflict'}:
        fail('Expression must contain op, args and optionally conflict')
    op, args = expression.get('op'), expression.get('args')
    if not isinstance(op, str) or not isinstance(args, list) or len(args) != 2:
        fail('The supported operations require an op name and two arguments')
    if 'conflict' in expression and op not in ('merge', 'namedMerge'):
        fail('conflict is only accepted by merge or namedMerge')
    left, right = args
    if op in ('namedMerge', 'namedGet'):
        def named_items(value):
            if not isinstance(value, list):
                fail('named collection operations require an explicit array of named objects')
            result = {}
            for index, item in enumerate(value):
                if not isinstance(item, dict) or not isinstance(item.get('name'), str) or not item['name']:
                    fail('each named entry requires a nonempty string name', '/' + str(index))
                if item['name'] in result:
                    fail('duplicate name in named collection: ' + item['name'], '/' + str(index))
                result[item['name']] = item
            return result
        first = named_items(left)
        if op == 'namedGet':
            if not isinstance(right, str) or right not in first:
                fail('namedGet requires an existing string name')
            return deepcopy(first[right])
        second = named_items(right)
        conflict = expression.get('conflict', 'left')
        if conflict not in ('left', 'right', 'error'):
            fail('namedMerge conflict must be left, right or error')
        result = []
        for key, item in first.items():
            result.append(evaluate({'op': 'merge', 'args': [item, second[key]], 'conflict': conflict},
                                   location + '/' + key.replace('~', '~0').replace('/', '~1'))
                          if key in second else deepcopy(item))
        result.extend(deepcopy(item) for key, item in second.items() if key not in first)
        return result
    if op == 'concat':
        if (isinstance(left, str) and isinstance(right, str)) or (isinstance(left, list) and isinstance(right, list)):
            return deepcopy(left + right)
        fail('concat requires two strings or two arrays')
    if op in ('overlay', 'merge', 'omit'):
        if not isinstance(left, dict):
            fail(op + ' requires an object as its first argument')
        if op == 'omit':
            if not isinstance(right, (dict, list)) or any(not isinstance(k, str) for k in right):
                fail('omit requires an object or array of direct string keys')
            return {key: deepcopy(value) for key, value in left.items() if key not in right}
        if not isinstance(right, dict):
            fail(op + ' requires two objects; named collections are not yet supported')
        if op == 'overlay':
            return deepcopy({**left, **right})
        conflict = expression.get('conflict', 'left')
        if conflict not in ('left', 'right', 'error'):
            fail('merge conflict must be left, right or error')

        def equal(a, b):
            # JSON numbers share a type, but booleans do not equal numbers.
            if isinstance(a, bool) != isinstance(b, bool):
                return False
            if isinstance(a, dict) and isinstance(b, dict):
                return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
            if isinstance(a, list) and isinstance(b, list):
                return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
            return a == b

        def merge(a, b, path):
            if isinstance(a, dict) and isinstance(b, dict):
                result = deepcopy(a)
                for key, value in b.items():
                    child = path + '/' + key.replace('~', '~0').replace('/', '~1')
                    result[key] = merge(a[key], value, child) if key in a else deepcopy(value)
                return result
            if equal(a, b):
                return deepcopy(a)
            if conflict == 'error':
                raise SchemaxisError(Fault('COMPOSITION_CONFLICT', 'Conflicting atomic values', location + path, 'input', observed={'left': a, 'right': b}))
            return deepcopy(a if conflict == 'left' else b)
        return merge(left, right, '')
    if op == 'get':
        if isinstance(left, dict) and isinstance(right, str) and right in left:
            return deepcopy(left[right])
        if isinstance(left, list) and type(right) is int and 0 <= right < len(left):
            return deepcopy(left[right])
        fail('get requires an existing object key or a valid nonnegative array index')
    if op in ('add', 'subtract', 'multiply', 'divide'):
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in args):
            fail('Arithmetic requires two finite numbers')
        try:
            if op == 'add':
                value = left + right
            elif op == 'subtract':
                value = left - right
            elif op == 'multiply':
                value = left * right
            else:
                value = left / right
            if not math.isfinite(value):
                fail('Arithmetic result must be finite')
            return value
        except (ZeroDivisionError, OverflowError):
            fail('Arithmetic is undefined or exceeds finite numeric range')
    fail('Unknown operation ' + repr(op))
