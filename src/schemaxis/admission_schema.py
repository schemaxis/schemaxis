"""Bounded validation of installed declarative schemas, without planner hooks.

Schemas are trusted generated contracts, never request-supplied validators.
Unknown assertion keywords refuse instead of silently weakening admission.
"""
import json
import math
import re

from .observations import fail

MAX_WORK = 262144
MAX_DEPTH = 128


class _Mismatch(Exception):
    """A value mismatch only; fatal policy/schema errors must never be negated."""

ANNOTATIONS = {'$schema', '$id', '$defs', 'title', 'description', 'default', 'examples',
               'deprecated', 'readOnly', 'writeOnly', '$comment'}
ASSERTIONS = {'$ref', 'type', 'properties', 'required', 'additionalProperties',
              'const', 'enum', 'items', 'minItems', 'maxItems', 'minLength', 'maxLength',
              'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum',
              'minProperties', 'maxProperties', 'pattern', 'uniqueItems', 'oneOf',
              'anyOf', 'allOf', 'not', 'dependentRequired'}


def validate(value, schema):
    """Validate finite JSON and the canonical schema under one shared work bound."""
    try:
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        if len(raw.encode('utf-8')) > 1024 * 1024:
            raise ValueError()
    except (TypeError, ValueError, UnicodeError, RecursionError):
        fail('MCP_POLICY_DENIED', 'input must be finite JSON within one MiB')
    work = 0
    def check(v, s, pointer='$', depth=0):
        nonlocal work
        work += 1
        if work > MAX_WORK or depth > MAX_DEPTH:
            fail('MCP_POLICY_DENIED', 'schema validation exceeds its work or depth budget', pointer)
        def refuse(message):
            raise _Mismatch(message, pointer)
        if s is True:
            return
        if s is False:
            refuse('value is excluded by the declared schema')
        if type(s) is not dict or any(k not in ASSERTIONS | ANNOTATIONS and not k.startswith('x-schemaxis-') for k in s):
            fail('MCP_POLICY_DENIED', 'admission schema uses an unqualified keyword', pointer)
        if '$ref' in s:
            ref = s['$ref']
            if type(ref) is not str or not ref.startswith('#/'):
                fail('MCP_POLICY_DENIED', 'only local schema references are admitted', pointer)
            target = schema
            try:
                for part in ref[2:].split('/'):
                    target = target[part.replace('~1', '/').replace('~0', '~')]
            except (KeyError, TypeError):
                fail('MCP_POLICY_DENIED', 'schema reference is unresolved', pointer)
            check(v, target, pointer, depth+1)
        for keyword in ('allOf', 'oneOf', 'anyOf'):
            if keyword not in s:
                continue
            matches = 0
            for branch in s[keyword]:
                # Literal discriminators avoid walking hundreds of unrelated
                # catalogue branches, without inventing an application router.
                props = branch.get('properties', {}) if type(branch) is dict else {}
                if type(v) is dict and any(k in v and 'const' in p and
                        (type(v[k]) is not type(p['const']) or v[k] != p['const'])
                        for k, p in props.items() if type(p) is dict):
                    if keyword == 'allOf':
                        refuse('input differs from a declared discriminator')
                    continue
                try:
                    check(v, branch, pointer, depth+1)
                    matches += 1
                except _Mismatch:
                    if keyword == 'allOf':
                        raise
                if keyword == 'anyOf' and matches:
                    break
            if keyword == 'oneOf' and matches != 1 or keyword == 'anyOf' and not matches:
                refuse('input does not match a unique declared variant' if keyword == 'oneOf' else 'input matches no declared variant')
        if 'not' in s:
            try:
                check(v, s['not'], pointer, depth+1)
            except _Mismatch:
                pass
            else:
                refuse('input uses an excluded declared variant')
        kind = s.get('type')
        types = {'object': dict, 'array': list, 'string': str, 'integer': int,
                 'boolean': bool, 'null': type(None)}
        kinds = kind if type(kind) is list else [kind]
        if kind is not None and not any(type(v) in (int, float) if k == 'number'
                                       else k in types and type(v) is types[k] for k in kinds):
            refuse('input does not match the declared type')
        if 'const' in s and (type(v) is not type(s['const']) or v != s['const']):
            refuse('input differs from the declared identity')
        if 'enum' in s and not any(type(v) is type(x) and v == x for x in s['enum']):
            refuse('input differs from the declared enumeration')
        if type(v) in (int, float):
            if type(v) is float and not math.isfinite(v):
                refuse('numeric input must be finite')
            for key, good in (('minimum', lambda b: v >= b), ('maximum', lambda b: v <= b),
                              ('exclusiveMinimum', lambda b: v > b), ('exclusiveMaximum', lambda b: v < b)):
                if key in s and not good(s[key]):
                    refuse('numeric input exceeds the declared bound')
        if type(v) is dict:
            if any(type(k) is not str for k in v) or set(s.get('required', ())) - set(v):
                refuse('input has non-string keys or missing declared fields')
            if not s.get('minProperties', 0) <= len(v) <= s.get('maxProperties', 32768):
                refuse('object exceeds the declared bound')
            props = s.get('properties', {})
            additional = s.get('additionalProperties', True)
            for key, child in v.items():
                if key in props:
                    check(child, props[key], pointer+'/'+key.replace('~', '~0').replace('/', '~1'), depth+1)
                elif additional is False:
                    refuse('unknown field in declared input')
                elif type(additional) is dict:
                    check(child, additional, pointer+'/'+key, depth+1)
            for key, required in s.get('dependentRequired', {}).items():
                if key in v and set(required)-set(v):
                    refuse('dependent declared field is missing')
        if type(v) in (list, str):
            lower, upper = ('minItems', 'maxItems') if type(v) is list else ('minLength', 'maxLength')
            if not s.get(lower, 0) <= len(v) <= s.get(upper, 1048576):
                refuse('input exceeds the declared length bound')
            if type(v) is list:
                if s.get('uniqueItems') and len({json.dumps(x, sort_keys=True, separators=(',', ':')) for x in v}) != len(v):
                    refuse('declared array items must be unique')
                for index, child in enumerate(v):
                    check(child, s.get('items', True), pointer+'/'+str(index), depth+1)
            elif 'pattern' in s and re.search(s['pattern'], v) is None:
                refuse('input differs from the declared text grammar')
    try:
        check(value, schema)
    except _Mismatch as error:
        fail('MCP_POLICY_DENIED', *error.args)
