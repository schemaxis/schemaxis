# Copyright (C) 2026 David L. F. Gaden.
"""Closed, host-safe identity/reference declarations, owned by exact routes.

A policy declares semantic identities, not arbitrary strings that happen to look
like names. The initial interpreter supports array-member graph identities,
including closed zero-input source nodes of non-graph routes; other collection
forms need an explicit contract extension before admission.
"""
import copy
import json
import math
import re
from collections import OrderedDict
from threading import RLock
from contextvars import ContextVar
from functools import wraps

from .errors import fail

VERSION = 'schemaxis.authoring-references/1'
LOCAL_VERSION = 'schemaxis.authoring-references/2'
ARRAY = {'each': 'array'}
MAP = {'each': 'map'}
NAME_KEYS = {'type', 'pattern', 'enum', 'minLength', 'maxLength'}
ANNOTATIONS = {'title', 'description', '$comment', 'default', 'examples', 'deprecated', 'readOnly', 'writeOnly',
               'x-schemaxis-contract'}
STRUCTURAL_KEYS = {'type', 'properties', 'items', 'additionalProperties', 'required', 'minItems', 'maxItems',
                   'uniqueItems', 'minProperties', 'maxProperties', 'propertyNames', '$defs', 'definitions', '$schema', '$id'}

# Only successful validation is cached. Loading still crosses the adaptor's
# isolation boundary on every call; the key covers all actual loaded data.
_validated = OrderedDict()
_cache_lock = RLock()
_CACHE_ENTRIES = 8
_CACHE_BYTES = 4 * 1024 * 1024
_request = ContextVar('authoring_policy_snapshot', default=None)
_local_admission = ContextVar('local_identity_admission', default=None)
_AUTHORITY_BYTES = 4 * 1024 * 1024
_SCHEMA_ADDRESS_BYTES = 1024 * 1024


class _LocalAdmission:
    def __init__(self):
        self.work = 100000
        self.address_bytes = _SCHEMA_ADDRESS_BYTES

    def visit(self, depth, location):
        self.work -= 1
        if self.work < 0 or depth > 64:
            invalid('Local identity schema traversal exceeds its work or depth limit', location)

    def address(self, path, location):
        for token in path:
            # Canonical JSON escapes ASCII controls, quotes and non-ASCII.
            self.address_bytes -= 1
            for char in token:
                code = ord(char)
                self.address_bytes -= (2 if char in '\b\f\n\r\t"\\' else 12 if code > 65535
                                       else 6 if code < 32 or code >= 127 else 1)
                if self.address_bytes < 0:
                    invalid('Local identity schema addresses exceed their byte limit', location)
        return '/' + '/'.join(path) if path else ''


def _local_ref(root, reference, location, *, boolean=False):
    if (not isinstance(reference, str) or not reference.startswith('#/') or '%' in reference
            or reference.count('/') > 64 or re.search(r'~(?![01])', reference)):
        invalid('Use a bounded local schema reference with valid pointer escapes', location)
    at = tuple(reference[2:].split('/'))
    target = root
    for token in at:
        key = token.replace('~1', '/').replace('~0', '~')
        target = target.get(key) if isinstance(target, dict) else None
    if not (isinstance(target, dict) or boolean and isinstance(target, bool)):
        invalid('Local schema reference does not address a supported schema', location)
    return target, at


def policy_request(function=None, *, fresh=False):
    """Compile each exact route once in an immutable, request-local snapshot.

    Worker entry points force a new scope even for in-process transports, so
    their independent admission cannot inherit a caller's checked projection.
    """
    def decorate(method):
        @wraps(method)
        def scoped(*args, **kwargs):
            if not fresh and _request.get() is not None:
                return method(*args, **kwargs)
            token = _request.set({})
            try:
                return method(*args, **kwargs)
            finally:
                _request.reset(token)
        return scoped
    return decorate(function) if function is not None else decorate


def invalid(message, location='$policy'):
    fail('INVALID_REFERENCE_POLICY', message, location)


def closed(value, allowed, required, location):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        invalid('Use the declared keys: ' + ', '.join(sorted(allowed)), location)


def selector(value, location):
    if not isinstance(value, list) or not value or len(value) > 32:
        invalid('A selector needs 1..32 property or collection segments', location)
    for part in value:
        if not ((isinstance(part, str) and part) or part == ARRAY or part == MAP):
            invalid('Use a property name, {each: array} or {each: map}', location)


def name_schema(schema, location):
    closed(schema, NAME_KEYS, {'type'}, location)
    if schema['type'] != 'string':
        invalid('An identity schema must describe a string', location)
    if 'pattern' in schema:
        try:
            if not isinstance(schema['pattern'], str):
                raise TypeError()
            re.compile(schema['pattern'])
        except (TypeError, re.error):
            invalid('Use a valid identity pattern', location)
    for key in ('minLength', 'maxLength'):
        if key in schema and (type(schema[key]) is not int or schema[key] < 0):
            invalid('Identity length bounds must be nonnegative integers', location)
    if schema.get('minLength', 0) > schema.get('maxLength', 1048576):
        invalid('Identity length bounds are reversed', location)
    if 'enum' in schema and (not isinstance(schema['enum'], list) or not schema['enum'] or
                            any(not isinstance(x, str) for x in schema['enum'])):
        invalid('Identity enum must contain strings', location)


def accepts_name(value, schema):
    return (isinstance(value, str) and bool(value) and
            len(value) >= schema.get('minLength', 0) and len(value) <= schema.get('maxLength', 1048576) and
            ('pattern' not in schema or re.search(schema['pattern'], value) is not None) and
            ('enum' not in schema or value in schema['enum']))


def schema_nodes(root, path, *, identity_location=None, identity_value=False, start=None,
                 locations=False, start_path=(), local_shape=False):
    """Follow typed selectors through literal schema alternatives and local refs."""
    admission = _local_admission.get()

    def visit(node, remaining, seen, at, depth=0):
        if admission is not None:
            admission.visit(depth, identity_location)
        if not isinstance(node, dict):
            if local_shape:
                invalid('Local selectors must traverse explicit schema objects', identity_location)
            return []
        if admission is not None and 'properties' in node and not isinstance(node['properties'], dict):
            invalid('Schema properties must be an object', identity_location)
        if identity_location:
            if 'oneOf' in node and 'anyOf' in node or identity_value and not remaining and ('oneOf' in node or 'anyOf' in node):
                invalid('Composed identity constraints require an explicit supported contract', identity_location)
            # Traversal must not discard a constraint on the identity or an ancestor.
            # Conjunctive/conditional schemas need an explicit contract extension.
            allowed = (NAME_KEYS if node.get('type') == 'string' else STRUCTURAL_KEYS) | ANNOTATIONS
            if '$ref' in node:
                allowed = {'$ref', '$defs', '$id', '$schema'} | ANNOTATIONS
            elif 'oneOf' in node or 'anyOf' in node:
                allowed = {'oneOf', 'anyOf', '$defs', '$id', '$schema'} | ANNOTATIONS
            if set(node) - allowed:
                invalid('Unsupported identity schema constraints: ' + ', '.join(sorted(set(node) - allowed)), identity_location)
        reference = node.get('$ref')
        if admission is not None and '$ref' in node:
            target, ref_path = _local_ref(root, reference, identity_location)
            if reference in seen:
                invalid('Local identity schema references must be acyclic along the selector', identity_location)
            return visit(target, remaining, seen | {reference}, ref_path, depth + 1)
        if reference:
            if not isinstance(reference, str) or not reference.startswith('#/') or reference in seen:
                return []
            target = root
            for part in reference[2:].split('/'):
                target = target.get(part.replace('~1', '/').replace('~0', '~'), {}) if isinstance(target, dict) else {}
            return visit(target, remaining, seen | {reference}, tuple(reference[2:].split('/')))
        alternatives = node.get('oneOf', node.get('anyOf'))
        if 'oneOf' in node or 'anyOf' in node:
            if admission is not None and (not isinstance(alternatives, list) or not alternatives
                                          or any(not isinstance(child, dict) for child in alternatives)):
                invalid('Schema alternatives must be a nonempty array of objects', identity_location)
            if alternatives is not None:
                keyword = 'oneOf' if 'oneOf' in node else 'anyOf'
                return [found for index, alternative in enumerate(alternatives)
                        for found in visit(alternative, remaining, seen, at + (keyword, str(index)), depth + 1)]
        if not remaining:
            return [(node, admission.address(at, identity_location))] if locations else [node]
        part, *rest = remaining
        if local_shape and node.get('type') != ('array' if part == ARRAY else 'object'):
            invalid('Local selectors require explicit array and object schemas', identity_location)
        child = (node.get('items') if part == ARRAY else node.get('additionalProperties') if part == MAP
                 else node.get('properties', {}).get(part))
        suffix = ('items',) if part == ARRAY else ('additionalProperties',) if part == MAP else ('properties', part.replace('~', '~0').replace('/', '~1'))
        return visit(child, rest, seen, at + suffix, depth + 1)
    return visit(root if start is None else start, path, set(), start_path)


def reference_names(root, schema, identity, location, *, multiple=False, port=False):
    """Prove a consumer accepts every declared identity, within a closed grammar.

    This deliberately admits fewer schemas than a general JSON Schema solver.
    Unsupported constraints must not disappear merely because the shape matches.
    """
    variants = schema_nodes(root, [], start=schema, identity_location=location)
    if not variants:
        invalid('Reference schema cannot be resolved', location)
    for variant in variants:
        kind = variant.get('type')
        if multiple and kind == 'array':
            reference_names(root, variant.get('items'), identity, location, port=port)
        elif not multiple and kind == 'string':
            constraints = {k: v for k, v in variant.items() if k not in ANNOTATIONS}
            name_schema(constraints, location)
            # Equal constraints (or omitted consumer constraints) are sufficient.
            # A finite identity enum also permits a direct inclusion proof.
            if not (all(identity.get(k) == v for k, v in constraints.items()) or
                    'enum' in identity and all(accepts_name(name, constraints) for name in identity['enum'])):
                invalid('Reference constraints are not proven to accept every declared identity', location)
        elif not multiple and port and kind == 'object':
            properties = variant.get('properties', {})
            if set(properties) != {'node', 'port'}:
                invalid('Only declared node/port reference objects are supported', location)
            reference_names(root, properties['node'], identity, location)
        else:
            invalid('Reference schema does not match its declared multiplicity or node shape', location)


def marker_schemas(root, markers, identities):
    """Inspect reachable schema vocabulary, never example/default payloads.

    Local references form a graph (runtime values are recursive). Visit each
    schema object once, then propagate marker reachability to its ancestors.
    """
    if not markers:
        return
    records = {}
    for index, marker in enumerate(markers):
        records.setdefault(marker['key'], []).append(
            (index, next(i['nameSchema'] for i in identities if i['name'] == marker['identity'])))
    string_cache = {}
    string_work = [0]

    def literal_marker(value):
        pending, seen = [value], set()
        while pending:
            item = pending.pop()
            if not isinstance(item, (dict, list)) or id(item) in seen:
                continue
            seen.add(id(item))
            if len(seen) > 100000:
                invalid('Literal marker constraints exceed bounded inspection', '$policy.markers')
            if isinstance(item, dict):
                for marker in records.keys() & item.keys():
                    if isinstance(item[marker], str):
                        return marker
                pending.extend(item.values())
            else:
                pending.extend(item)
        return None

    def string_schemas(node, location, active=frozenset()):
        """Project only possible string values of a wildcard property schema.

        Object/array/number-only values cannot be valid node marker payloads.
        Unknown constraints on possible strings still require a closed proof.
        """
        string_work[0] += 1
        if string_work[0] > 100000:
            invalid('Wildcard marker inspection exceeds its bounded work', location)
        if node is False:
            return []
        if node is True:
            return [{'type': 'string'}]
        if not isinstance(node, dict):
            invalid('Marker property schemas must be objects or booleans', location)
        key = id(node)
        if key in active or len(active) >= 64:
            invalid('Recursive wildcard string constraints require a supported contract', location)
        if key in string_cache:
            return string_cache[key]
        kind = node.get('type')
        if kind is not None and not (isinstance(kind, str) or isinstance(kind, list) and all(isinstance(k, str) for k in kind)):
            invalid('Invalid wildcard property type', location)
        if kind is not None and 'string' not in ([kind] if isinstance(kind, str) else kind):
            return []
        if 'const' in node and not isinstance(node['const'], str):
            return []
        if isinstance(node.get('enum'), list) and not any(isinstance(v, str) for v in node['enum']):
            return []
        if '$ref' in node:
            if set(node) - ({'$ref', '$defs', '$id', '$schema'} | ANNOTATIONS):
                invalid('Wildcard reference siblings require a supported contract', location)
            target = root
            reference = node['$ref']
            if not isinstance(reference, str) or not reference.startswith('#/'):
                invalid('Wildcard marker schemas require local references', location)
            if _local_admission.get() is not None:
                target, _ = _local_ref(root, reference, '$policy.markers', boolean=True)
            else:
                for part in reference[2:].split('/'):
                    target = target.get(part.replace('~1', '/').replace('~0', '~')) if isinstance(target, dict) else None
            result = string_schemas(target, location, active | {key})
        elif 'anyOf' in node or 'oneOf' in node:
            word = 'anyOf' if 'anyOf' in node else 'oneOf'
            if set(node) - ({word, '$defs', '$id', '$schema'} | ANNOTATIONS) or not isinstance(node[word], list):
                invalid('Wildcard alternatives require a supported contract', location)
            result, seen_variants = [], set()
            for child in node[word]:
                variants = string_schemas(child, location, active | {key})
                if word == 'oneOf' and variants and result:
                    invalid('Overlapping wildcard string alternatives require a supported contract', location)
                for variant in variants:
                    string_work[0] += 1
                    if string_work[0] > 100000:
                        invalid('Wildcard marker inspection exceeds its bounded work', location)
                    if id(variant) not in seen_variants:
                        seen_variants.add(id(variant))
                        result.append(variant)
        else:
            # These JSON Schema keywords constrain only non-string instances.
            irrelevant = STRUCTURAL_KEYS | {'patternProperties', 'dependentRequired', 'dependentSchemas',
                'unevaluatedProperties', 'unevaluatedItems', 'additionalItems', 'prefixItems', 'contains',
                'minContains', 'maxContains', 'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum', 'multipleOf'}
            result = [{**{k: v for k, v in node.items() if k not in irrelevant}, 'type': 'string'}]
        string_cache[key] = result
        return result

    pending, nodes, parents, marked = [(root, (), None)], {}, {}, {}
    maps = {'properties', 'patternProperties', 'dependentSchemas'}
    arrays = {'allOf', 'anyOf', 'oneOf', 'prefixItems'}
    singles = {'additionalProperties', 'unevaluatedProperties', 'propertyNames', 'items', 'contains',
               'additionalItems', 'unevaluatedItems', 'not', 'if', 'then', 'else', 'contentSchema'}
    while pending:
        node, path, parent = pending.pop()
        if not isinstance(node, dict):
            continue
        key = id(node)
        if parent is not None:
            parents.setdefault(key, set()).add(parent)
        if key in nodes:
            continue
        if len(nodes) >= 100000 or len(path) > 128:
            invalid('Marker schema inspection exceeds its bounded graph', '$policy.markers')
        nodes[key] = node
        for keyword in ('const', 'enum'):
            if keyword in node:
                constrained_marker = literal_marker(node[keyword])
                if constrained_marker:
                    invalid('Literal object constraints on marker values require a supported contract',
                            '$policy.markers/' + str(records[constrained_marker][0][0]))
        properties, patterns = node.get('properties', {}), node.get('patternProperties', {})
        kind = node.get('type')
        object_possible = kind is None or kind == 'object' or isinstance(kind, list) and 'object' in kind
        # A literal domain without any marker cannot carry one; literal domains
        # containing markers were refused above, including nested payloads.
        if 'const' in node:
            object_possible = False
        if isinstance(node.get('enum'), list):
            object_possible = False
        if object_possible:
            if not isinstance(properties, dict) or not isinstance(patterns, dict):
                invalid('Marker object property declarations must be maps', '$policy.markers')
            try:
                compiled = [(re.compile(pattern), child) for pattern, child in patterns.items()]
            except (TypeError, re.error):
                invalid('Use valid marker property patterns', '$policy.markers')
            for marker, declarations in records.items():
                owners = ([properties[marker]] if marker in properties else [])
                owners += [child for pattern, child in compiled if pattern.search(marker)]
                if not owners:
                    # Pure reference/composition wrappers inherit their branches'
                    # object ownership; they add no unconstrained alternative.
                    wrappers = {'$ref', 'oneOf', 'anyOf', 'allOf', 'not', 'if', 'then', 'else'}
                    object_keywords = {'properties', 'patternProperties', 'additionalProperties', 'propertyNames',
                                       'required', 'minProperties', 'maxProperties', 'dependentSchemas', 'dependentRequired'}
                    if not wrappers & set(node) or object_keywords & set(node) or kind == 'object':
                        owners = [node.get('additionalProperties', True)]
                if not owners:
                    continue
                location = '$policy.markers/' + str(declarations[0][0])
                candidates = [string_schemas(owner, location) for owner in owners]
                if any(not variants for variants in candidates):
                    continue  # Conjunction excludes every valid string marker.
                for index, identity in declarations:
                    location = '$policy.markers/' + str(index)
                    for variants in candidates:
                        for variant in variants:
                            reference_names(root, variant, identity, location)
                    marked[key] = location
        reference = node.get('$ref')
        if reference is not None:
            target = root
            if not isinstance(reference, str) or not reference.startswith('#/'):
                invalid('Marker schemas require inspectable local references', '$policy.markers')
            if _local_admission.get() is not None:
                target, _ = _local_ref(root, reference, '$policy.markers', boolean=True)
            else:
                for part in reference[2:].split('/'):
                    target = target.get(part.replace('~1', '/').replace('~0', '~')) if isinstance(target, dict) else None
            if not isinstance(target, (dict, bool)):
                invalid('Marker schema reference does not exist', '$policy.markers')
            pending.append((target, (), key))
        for word, value in node.items():
            if word in maps and isinstance(value, dict):
                pending.extend((child, path + (word, name), key) for name, child in value.items())
            elif word in arrays and isinstance(value, list):
                pending.extend((child, path + (word, str(index)), key) for index, child in enumerate(value))
            elif word in singles:
                pending.append((value, path + (word,), key))
    # Unsupported conjunctive/conditional restrictions must not hide above the
    # marker property. Non-marker branches keep their independent schema grammar.
    def presence_only(node, depth=0):
        if isinstance(node, bool):
            return True
        if not isinstance(node, dict) or depth > 64 or set(node) - ({'required', 'not', 'oneOf', 'anyOf', 'allOf'} | ANNOTATIONS):
            return False
        if 'required' in node and (not isinstance(node['required'], list) or any(not isinstance(k, str) for k in node['required'])):
            return False
        if 'not' in node and not presence_only(node['not'], depth + 1):
            return False
        return all(isinstance(node[word], list) and all(presence_only(child, depth + 1) for child in node[word])
                   for word in ('oneOf', 'anyOf', 'allOf') if word in node)

    pending = list(marked)
    while pending:
        key = pending.pop()
        node, location = nodes[key], marked[key]
        annotations = ANNOTATIONS | {'x-schemaxis-' + name for name in (
            'constructor', 'convert', 'compiler', 'path', 'cardinalityBasis', 'tupleSize', 'tupleElementTypes',
            'coverage', 'execution', 'nativeIdentity', 'publication', 'role', 'checks', 'commands', 'requires')}
        allowed = STRUCTURAL_KEYS | {'patternProperties'} | annotations
        if presence_only(node):
            allowed |= {'required', 'not', 'oneOf', 'anyOf', 'allOf'}
        elif '$ref' in node:
            allowed = {'$ref', '$defs', '$id', '$schema'} | annotations
        elif 'oneOf' in node or 'anyOf' in node:
            word = 'oneOf' if 'oneOf' in node else 'anyOf'
            if isinstance(node[word], list) and all(presence_only(child) for child in node[word]):
                # Marker spelling changes preserve object property presence.
                allowed |= {word}
            else:
                allowed = {'oneOf', 'anyOf', '$defs', '$id', '$schema'} | annotations
        if set(node) - allowed or 'oneOf' in node and 'anyOf' in node:
            invalid('Unsupported constraints on a reachable marker schema: ' + ', '.join(sorted(set(node) - allowed)), location)
        for parent in parents.get(key, ()):
            if parent not in marked:
                marked[parent] = location
                pending.append(parent)


def local_identity(identity):
    """The admitted declaration's domain, never a caller-supplied change label."""
    return identity.get('form') == 'owner-array-property'


def bounded_authority(value):
    """Bound v2 loaded data before cache hashing/copying; no native or expression work."""
    stack, count, text_size = [iter((value,))], 0, 0
    while stack:
        try:
            item = next(stack[-1])
        except StopIteration:
            stack.pop()
            continue
        count += 1
        if count > 100000 or len(stack) > 65:
            invalid('Local identity authority exceeds 64 levels or 100000 values')
        if isinstance(item, dict):
            if any(not isinstance(k, str) for k in item):
                invalid('Local identity authority keys must be strings')
            text_size += sum(len(k) for k in item)
            stack.append(iter(item.values()))
        elif isinstance(item, (list, tuple)):
            stack.append(iter(item))
        elif type(item) is str:
            text_size += len(item)
        elif type(item) is int:
            if item.bit_length() > (_AUTHORITY_BYTES * 332193) // 100000 + 1:
                invalid('Local identity authority exceeds four MiB')
        elif item is not None and type(item) is not bool and not (type(item) is float and math.isfinite(item)):
            invalid('Local identity authority must be finite JSON data')
        if text_size > _AUTHORITY_BYTES:
            invalid('Local identity authority exceeds four MiB')
    size = 0
    try:
        for chunk in json.JSONEncoder(sort_keys=True, allow_nan=False, separators=(',', ':')).iterencode(value):
            size += len(chunk)
            if size > _AUTHORITY_BYTES:
                invalid('Local identity authority exceeds four MiB')
    except (ValueError, TypeError, RecursionError):
        invalid('Local identity authority must be bounded finite JSON data')


def _overlap(left, right):
    return len(left) == len(right) and all(a == b or a == ARRAY or b == ARRAY for a, b in zip(left, right))


def _path_overlap(left, right):
    size = min(len(left), len(right))
    return _overlap(left[:size], right[:size])


def references_for(policy, identity):
    return (record for record in policy['references'] if record['identity'] == identity['name'])


def _validate_local(policy, schema, declarations, graph_route):
    bounded_authority((policy, schema, declarations))
    if not isinstance(schema, dict) or not isinstance(declarations, dict) or any(
            not isinstance(value, dict) for value in declarations.values()):
        invalid('Schema and operation declarations must be objects')
    identities = policy['identities']
    if not isinstance(identities, list) or not 1 <= len(identities) <= 32:
        invalid('Declare 1..32 identity kinds')
    for key in ('references', 'markers'):
        if not isinstance(policy[key], list) or len(policy[key]) > 256:
            invalid('Reference records must be a bounded array')
    if not isinstance(policy['expressions'], dict):
        invalid('Expressions must be an object')
    names = set()
    for identity in identities:
        if (not isinstance(identity, dict) or not isinstance(identity.get('name'), str)
                or not identity['name'] or identity['name'] in names):
            invalid('Identity kind names must be unique nonempty strings')
        names.add(identity['name'])
    nodes = [i for i in identities if not local_identity(i)]
    locals_ = [i for i in identities if local_identity(i)]
    node_names = {i['name'] for i in nodes}
    for record in policy['references']:
        if not isinstance(record, dict) or not isinstance(record.get('identity'), str) or record['identity'] not in names:
            invalid('References must name a declared identity')
    for marker in policy['markers']:
        if (not isinstance(marker, dict) or not isinstance(marker.get('identity'), str)
                or marker['identity'] not in node_names):
            invalid('Framework markers require a node identity domain')
    if any(not isinstance(v, str) or v not in node_names for v in policy['expressions'].values()):
        invalid('Framework expressions require a node identity domain')
    projected = {}
    if nodes:
        legacy = {**policy, 'version': VERSION, 'identities': nodes,
                  'references': [r for r in policy['references'] if r['identity'] in node_names]}
        projected.update(validate(legacy, schema, declarations, graph_route=graph_route)['projection'])
    elif policy['markers'] or policy['expressions']:
        invalid('Local-only policies have no framework graph bindings')
    targets = [i['collection'] + [ARRAY, i['nameProperty']] for i in nodes]
    protected = [['nodes', ARRAY, 'id']]
    local_targets = []
    for index, identity in enumerate(identities):
        if not local_identity(identity):
            continue
        here = '$policy.identities/' + str(index)
        closed(identity, {'name', 'form', 'owner', 'collection', 'nameProperty', 'nameSchema'},
               {'name', 'form', 'owner', 'collection', 'nameProperty', 'nameSchema'}, here)
        owner = identity['owner']
        closed(owner, {'path', 'discriminator'}, {'path', 'discriminator'}, here + '/owner')
        selector(owner['path'], here + '/owner/path')
        if owner['path'][-1] != ARRAY or len(owner['path']) < 2 or any(not isinstance(p, str) for p in owner['path'][:-1]):
            invalid('Local owners use a literal property prefix and one final array wildcard', here)
        discriminator = owner['discriminator']
        closed(discriminator, {'property', 'value'}, {'property', 'value'}, here)
        if (not all(isinstance(discriminator[k], str) and discriminator[k] for k in discriminator)
                or discriminator['value'] not in declarations
                or declarations[discriminator['value']].get('role') == 'writer'):
            invalid('Local owners select one ordinary declaration', here)
        selector(identity['collection'], here + '/collection')
        if any(not isinstance(p, str) for p in identity['collection']):
            invalid('Local identity collections use literal property paths', here)
        if not isinstance(identity['nameProperty'], str) or not identity['nameProperty']:
            invalid('Local identities need an explicit name property', here)
        name_schema(identity['nameSchema'], here)
        target = owner['path'] + identity['collection'] + [ARRAY, identity['nameProperty']]
        if any(_overlap(target, prior) for prior in targets):
            invalid('Identity target selectors overlap', here)
        targets.append(target)
        local_targets.append(target)
        protected.append(owner['path'] + [discriminator['property']])
        variants = schema_nodes(schema, owner['path'], identity_location=here, locations=True, local_shape=True)
        selected = []
        for variant, address in variants:
            if variant.get('type') != 'object':
                invalid('Local owners must be explicit object schemas', here)
            field = variant.get('properties', {}).get(discriminator['property'])
            if (not isinstance(field, dict) or set(field) - (ANNOTATIONS | {'const'})
                    or not isinstance(field.get('const'), str)):
                invalid('Owner variants require an unambiguous literal discriminator', here)
            if field['const'] == discriminator['value']:
                selected.append((variant, address))
        if not selected:
            invalid('The local owner is absent from the route schema', here)
        name_addresses, reference_addresses, owner_addresses = [], [], []
        references = [r for r in policy['references'] if r['identity'] == identity['name']]
        for record in references:
            closed(record, {'identity', 'scope', 'path', 'shape'}, {'identity', 'scope', 'path', 'shape'}, here)
            if record['scope'] != 'owner' or record['shape'] != 'scalar':
                invalid('Local references are owner-scoped scalar leaves', here)
            selector(record['path'], here)
            if not isinstance(record['path'][-1], str) or any(p == MAP for p in record['path']):
                invalid('Local references use property and array segments, ending at a property', here)
        for variant, address in selected:
            owner_addresses.append(address)
            start_path = tuple(address.split('/')[1:]) if address else ()
            found = schema_nodes(schema, identity['collection'] + [ARRAY, identity['nameProperty']],
                                 start=variant, start_path=start_path, identity_location=here,
                                 identity_value=True, locations=True, local_shape=True)
            if not found or any({k: v for k, v in node.items() if k not in ANNOTATIONS} != identity['nameSchema']
                                for node, _ in found):
                invalid('Local identity constraints differ from the actual schema', here)
            name_addresses.extend(at for _, at in found)
            for record in references:
                found = schema_nodes(schema, record['path'], start=variant, start_path=start_path,
                                     identity_location=here, locations=True, local_shape=True)
                if not found:
                    invalid('Local reference path is absent from its owner schema', here)
                for node, at in found:
                    reference_names(schema, node, identity['nameSchema'], here)
                    reference_addresses.append(at)
        projected[identity['name']] = {
            'domain': 'owner-local', 'operation': discriminator['value'], 'owner': owner,
            'collection': list(identity['collection']), 'ownerSchemas': sorted(set(owner_addresses)),
            'identitySchemas': sorted(set(name_addresses)), 'referenceSchemas': sorted(set(reference_addresses))}
    graph_consumers = []
    for identity in nodes:
        graph = identity['graph']
        if graph['inputs'] is not None:
            graph_consumers.append(identity['collection'] + [ARRAY, graph['inputs']])
    graph_consumers.extend(record['path'] for record in policy['references'] if record['identity'] in node_names)
    consumers = []
    for identity in locals_:
        for record in references_for(policy, identity):
            path = identity['owner']['path'] + record['path']
            if any(_path_overlap(path, prior) for prior in targets + protected + graph_consumers + consumers):
                invalid('Local consumers overlap another declared identity, discriminator or consumer')
            consumers.append(path)
    for path in local_targets:
        if any(_path_overlap(path, prior) for prior in protected + graph_consumers):
            invalid('Local identity overlaps a graph identity, consumer or owner discriminator')
    result = {**policy, 'projection': projected}
    bounded_authority(result)
    return copy.deepcopy(result)


def validate(policy, schema, declarations, *, graph_route=None):
    """Validate policy data and its exact schema, then project actual port declarations.

    ``graph_route`` is the route's effective ``graph`` flag; ``for_route`` passes
    ``False`` when the flag is false or omitted. Only ``False`` admits
    ``graph.inputs: null``: its identity variants are closed source objects whose
    actual declarations have zero input ports. Direct callers that omit it refuse.
    """
    closed(policy, {'version', 'identities', 'references', 'markers', 'expressions'},
           {'version', 'identities', 'references', 'markers', 'expressions'}, '$policy')
    if policy['version'] == LOCAL_VERSION:
        token = _local_admission.set(_LocalAdmission())
        try:
            return _validate_local(policy, schema, declarations, graph_route)
        finally:
            _local_admission.reset(token)
    if policy['version'] != VERSION:
        invalid('Unsupported identity/reference policy version')
    identities = policy['identities']
    if not isinstance(identities, list) or not identities or len(identities) > 32:
        invalid('Declare 1..32 identity kinds', '$policy.identities')
    names, locations, projections = set(), set(), {}
    for index, identity in enumerate(identities):
        here = '$policy.identities/' + str(index)
        closed(identity, {'name', 'form', 'collection', 'nameProperty', 'nameSchema', 'graph'},
               {'name', 'form', 'collection', 'nameProperty', 'nameSchema', 'graph'}, here)
        if not isinstance(identity['name'], str) or not identity['name'] or identity['name'] in names:
            invalid('Identity kind names must be unique', here)
        names.add(identity['name'])
        if identity['form'] != 'array-property':
            invalid('This policy version implements array-property identities only', here)
        selector(identity['collection'], here + '/collection')
        if any(not isinstance(part, str) for part in identity['collection']):
            invalid('Nested local collection scopes require a later policy version', here)
        if not isinstance(identity['nameProperty'], str) or not identity['nameProperty']:
            invalid('Declare the identity property', here)
        identity_location = (*identity['collection'], identity['nameProperty'])
        if identity_location in locations:
            invalid('Identity descriptors must have distinct authored locations', here)
        locations.add(identity_location)
        name_schema(identity['nameSchema'], here + '/nameSchema')
        graph = identity['graph']
        closed(graph, {'discriminator', 'inputs'}, {'discriminator', 'inputs'}, here + '/graph')
        container = graph['inputs']
        if (not isinstance(graph['discriminator'], str) or not graph['discriminator']
                or container is not None and (not isinstance(container, str) or not container)):
            invalid('Graph property names must be nonempty strings', here)
        if container is None and graph_route is not False:
            invalid('Only a non-graph route can declare source identities without an input container', here + '/graph')
        variants = schema_nodes(schema, identity['collection'] + [ARRAY], identity_location=here + '/nameSchema')
        if not variants:
            invalid('Identity collection does not exist in the route schema', here)
        by_operation, closed_properties = {}, {}
        for variant in variants:
            properties = variant.get('properties', {})
            actual = properties.get(identity['nameProperty'])
            if not isinstance(actual, dict):
                invalid('Every graph variant needs an explicit identity schema', here + '/nameSchema')
            actual_names = schema_nodes(schema, [], start=actual, identity_location=here + '/nameSchema', identity_value=True)
            if not actual_names or any({k: v for k, v in candidate.items() if k not in ANNOTATIONS} != identity['nameSchema']
                                       for candidate in actual_names):
                invalid('Identity constraints differ from the route schema', here + '/nameSchema')
            operation = properties.get(graph['discriminator'], {}).get('const')
            if not isinstance(operation, str) or operation not in declarations or operation in by_operation:
                invalid('Each graph variant needs one declared operation discriminator', here)
            declared = declarations[operation]
            ports = declared.get('inputs')
            if not isinstance(ports, dict):
                invalid('Operation inputs must be declared', here)
            if container is None:
                if ports:
                    invalid('A source identity without an input container needs zero declared input ports', here + '/graph')
                if variant.get('type') != 'object' or variant.get('additionalProperties') is not False:
                    invalid('A source identity without an input container needs a closed object schema', here + '/graph')
                if 'inputs' in properties:
                    invalid('The route schema declares the graph input property that the policy says is absent', here + '/graph')
                by_operation[operation] = {}
                closed_properties[operation] = sorted(properties)
                continue
            schema_ports = properties.get(graph['inputs'], {}).get('properties', {})
            if set(schema_ports) != set(ports):
                invalid('Declared input ports differ from the literal schema', here)
            by_operation[operation] = _ports(ports, here)
            # Validate the input-container constraints as well as each leaf.
            containers = schema_nodes(schema, [graph['inputs']], start=variant, identity_location=here + '/graph')
            if len(containers) != 1:
                invalid('Graph inputs need one literal declared container', here + '/graph')
            for port_name, port in by_operation[operation].items():
                reference_names(schema, schema_ports[port_name], identity['nameSchema'], here + '/graph/' + port_name,
                                multiple=port['multiple'], port=port['kind'] == 'data')
        expected = {name for name, value in declarations.items() if value.get('role') != 'writer'}
        if set(by_operation) != expected:
            invalid('Every ordinary declaration must have an identity schema variant', here)
        writers = {name: _ports(value.get('inputs', {}), here) for name, value in declarations.items()
                   if value.get('role') == 'writer'}
        projections[identity['name']] = {'operations': by_operation, 'writers': writers}
        if container is None:
            if writers:
                invalid('Writer declarations need a declared input container', here + '/graph')
            projections[identity['name']]['properties'] = closed_properties
    for key in ('references', 'markers'):
        if not isinstance(policy[key], list) or len(policy[key]) > 256:
            invalid('Reference records must be a bounded array', '$policy.' + key)
    for index, reference in enumerate(policy['references']):
        here = '$policy.references/' + str(index)
        closed(reference, {'identity', 'path', 'shape', 'discriminator'}, {'identity', 'path', 'shape'}, here)
        if not isinstance(reference['identity'], str) or reference['identity'] not in names or reference['shape'] not in ('scalar', 'list', 'keys', 'writer-resources'):
            invalid('Use a declared identity and supported reference shape', here)
        selector(reference['path'], here + '/path')
        nodes = schema_nodes(schema, reference['path'], identity_location=here)
        kind = {'scalar': 'string', 'list': 'array', 'keys': 'object', 'writer-resources': 'object'}[reference['shape']]
        if not nodes or not all(node.get('type') == kind for node in nodes):
            invalid('Reference shape does not match the route schema', here)
        if reference['shape'] == 'writer-resources':
            discriminator = reference.get('discriminator')
            if not isinstance(discriminator, str) or not discriminator:
                invalid('Writer resources need a declared owner discriminator', here)
            for owner in schema_nodes(schema, reference['path'][:-1], identity_location=here):
                writer = owner.get('properties', {}).get(discriminator, {}).get('const')
                if not isinstance(writer, str) or writer not in projections[reference['identity']]['writers']:
                    invalid('Resource owners must select a declared writer', here)
                resources = schema_nodes(schema, reference['path'][-1:], start=owner, identity_location=here)
                ports = {name: port for name, port in projections[reference['identity']]['writers'][writer].items()
                         if port['kind'] != 'data'}
                for resource in resources:
                    if set(resource.get('properties', {})) != set(ports):
                        invalid('Writer resource ports differ from the route schema', here)
                    for name, port in ports.items():
                        reference_names(schema, resource['properties'][name],
                                        next(i['nameSchema'] for i in identities if i['name'] == reference['identity']),
                                        here + '/' + name)
        elif 'discriminator' in reference:
            invalid('Only writer-resource references use a discriminator', here)
        else:
            identity_schema = next(i['nameSchema'] for i in identities if i['name'] == reference['identity'])
            for node in nodes:
                if reference['shape'] == 'keys':
                    if node.get('properties') or node.get('required') or node.get('additionalProperties') is False:
                        invalid('Reference maps need uniform values and no fixed required names', here)
                    if 'propertyNames' in node:
                        reference_names(schema, node['propertyNames'], identity_schema, here)
                else:
                    reference_names(schema, node, identity_schema, here, multiple=reference['shape'] == 'list')
    for index, marker in enumerate(policy['markers']):
        closed(marker, {'key', 'identity'}, {'key', 'identity'}, '$policy.markers/' + str(index))
        if not isinstance(marker['identity'], str) or marker['identity'] not in names or marker['key'] not in ('$observe', '$sample', '$object'):
            invalid('Use a supported framework graph observation marker')
    marker_schemas(schema, policy['markers'], identities)
    if not isinstance(policy['expressions'], dict) or set(policy['expressions']) - {'extents'} or any(
            not isinstance(value, str) or value not in names for value in policy['expressions'].values()):
        invalid('Only checked extents node bindings are implemented')
    return {**copy.deepcopy(policy), 'projection': projections}


def _ports(ports, location):
    result = {}
    for name, port in ports.items():
        if (not isinstance(name, str) or not isinstance(port, dict) or type(port.get('multiple', False)) is not bool
                or not isinstance(port.get('kind', 'data'), str)):
            invalid('Invalid declared input port', location)
        result[name] = {'multiple': port.get('multiple', False), 'kind': port.get('kind', 'data')}
    return result


def for_route(provider, route):
    """Return admitted projected data, or None for an unaudited route."""
    from .adaptors import registry
    binding = route.get('authoringReferences')
    if binding is None:
        return None
    from .storage import digest, encoded
    from .core.faults import SchemaxisError
    snapshot = _request.get()
    route_key = digest([provider, route])
    if snapshot is not None and route_key in snapshot:
        return copy.deepcopy(snapshot[route_key])
    def remember(value):
        if snapshot is not None:
            # Bound the local snapshot independently from the validation cache.
            if len(snapshot) < _CACHE_ENTRIES and sum(len(encoded(p)) for p in snapshot.values()) + len(encoded(value)) <= _CACHE_BYTES:
                snapshot[route_key] = copy.deepcopy(value)
        return value
    def load():
        value = registry.binding(binding)
        return (value() if callable(value) else value,
                registry.binding(route['schema'])(), registry.declarations(provider))
    result, fault = registry.isolated(provider, load)
    if fault is not None:
        from .errors import SchemaxisError
        raise SchemaxisError(fault)
    if isinstance(result[0], dict) and result[0].get('version') == LOCAL_VERSION:
        bounded_authority(result)
    try:
        pending, seen = [result], set()
        while pending:
            item = pending.pop()
            if isinstance(item, (dict, list, tuple)) and id(item) not in seen:
                seen.add(id(item))
                if isinstance(item, dict):
                    if any(not isinstance(k, str) for k in item):
                        invalid('Schema and declaration keys must be strings')
                    pending.extend(item.values())
                else:
                    pending.extend(item)
        key = digest([provider, route, result])
    except SchemaxisError:
        invalid('Reference policy, schema and declarations must be finite JSON data')
    with _cache_lock:
        if key in _validated:
            _validated.move_to_end(key)
            return remember(copy.deepcopy(_validated[key][0]))
    projected = validate(*result, graph_route=bool(route.get('graph')))
    size = len(encoded(projected))
    if size <= _CACHE_BYTES:
        with _cache_lock:
            _validated[key] = (copy.deepcopy(projected), size)
            _validated.move_to_end(key)
            while len(_validated) > _CACHE_ENTRIES or sum(item[1] for item in _validated.values()) > _CACHE_BYTES:
                _validated.popitem(last=False)
    return remember(projected)
