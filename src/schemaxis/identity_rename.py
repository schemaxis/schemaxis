# Copyright (C) 2026 David L. F. Gaden.
"""Pure, digest-checked preview of one declared authored identity change.

This module does not commit authoring state or preserve live native handles.
Durable consumers must implement the separate identity/history contract before
exposing Apply. Every edit below addresses the original document, then one
reconstruction publishes the cloned candidate.
"""
import copy
import json
import math
import re

from .errors import fail, SchemaxisError
from .storage import digest
from .identity_policy import ARRAY, MAP, LOCAL_VERSION, accepts_name, for_route, local_identity
from .core.documents import reference_pointer

VERSION = 'schemaxis.identity-change/1'
WORKFLOW = 'schemaxis.workflow/1'
DESIGNS = ('schemaxis.workflow-design/1', 'schemaxis.workflow-design/2')
_ORIGIN_BYTES = 1048576
GRAPH_MARKERS = frozenset(('$observe', '$sample', '$object'))


def node_inputs(node, graph):
    """The node's literal input container; a declared zero-input source has none."""
    return {} if graph['inputs'] is None else node.get(graph['inputs'], {})


def pointer(path):
    return ''.join('/' + str(part).replace('~', '~0').replace('/', '~1') for part in path)


def parts(value, location='$'):
    if location == '$identityPointer' and isinstance(value, str):
        if len(value) > 1048576 or value.count('/') > 64:
            fail('IDENTITY_LIMIT', 'Identity pointers are limited to one MiB and 64 segments', location)
        if len(value.encode('utf-8', errors='surrogatepass')) > 1048576:
            fail('IDENTITY_LIMIT', 'Identity pointers are limited to one MiB', location)
    if not isinstance(value, str) or value and not value.startswith('/') or re.search(r'~(?![01])', value):
        fail('INVALID_IDENTITY_POINTER', 'Use an RFC 6901 pointer', location)
    return tuple(x.replace('~1', '/').replace('~0', '~') for x in value.split('/')[1:]) if value else ()


def read(document, path):
    value = document
    for key in path:
        if isinstance(value, dict) and key in value:
            value = value[key]
        elif isinstance(value, list) and value:
            token, last = str(key), str(len(value) - 1)
            if (len(token) < len(last) or len(token) == len(last) and token <= last) and re.fullmatch(r'0|[1-9][0-9]*', token):
                value = value[int(token)]
                continue
            fail('UNKNOWN_IDENTITY_REFERENCE', 'The addressed authored value does not exist', '$' + pointer(path))
        else:
            fail('UNKNOWN_IDENTITY_REFERENCE', 'The addressed authored value does not exist', '$' + pointer(path))
    return value


def mapping(value, path):
    if not isinstance(value, dict):
        fail('INVALID_IDENTITY_SCOPE', 'This identity/reference scope must be an object', '$' + pointer(path))
    return value


def walk(value, path=()):
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk(child, path + (key,))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            yield from walk(child, path + (str(i),))


def bounded(value):
    pending, count = [iter((value,))], 0
    while pending:
        try:
            item = next(pending[-1])
        except StopIteration:
            pending.pop()
            continue
        depth = len(pending) - 1
        count += 1
        if depth > 64 or count > 100000:
            fail('IDENTITY_LIMIT', 'Use at most 64 levels and 100000 JSON values')
        if isinstance(item, dict):
            if any(not isinstance(k, str) for k in item):
                fail('INVALID_DOCUMENT', 'JSON object keys must be strings')
            if any(len(k) > 1048576 for k in item):
                fail('IDENTITY_LIMIT', 'Identity preview JSON is limited to one MiB')
            pending.append(iter(item.values()))
        elif isinstance(item, list):
            pending.append(iter(item))
        elif not (item is None or type(item) in (str, bool, int, float)) or type(item) is float and not math.isfinite(item):
            fail('INVALID_DOCUMENT', 'Use finite JSON values')
        elif isinstance(item, str) and len(item) > 1048576 or type(item) is int and item.bit_length() > 3483295:
            fail('IDENTITY_LIMIT', 'Identity preview JSON is limited to one MiB')
    # The canonical encoder emits ASCII chunks; count without materializing the
    # expanded document. A small source can otherwise repeat a large new name
    # thousands of times before the result-size check gets a chance to refuse.
    size = 0
    try:
        for chunk in json.JSONEncoder(sort_keys=True, allow_nan=False, separators=(',', ':')).iterencode(value):
            size += len(chunk)
            if size > 1048576:
                fail('IDENTITY_LIMIT', 'Identity preview JSON is limited to one MiB')
    except (TypeError, ValueError, RecursionError):
        fail('INVALID_DOCUMENT', 'Use finite JSON values')
    return size


def scopes(document):
    """Exact framework envelopes, without planning or resolving incomplete values."""
    version = document.get('version')
    workflow_base = ('workflow',) if version in DESIGNS else ()
    body = document.get('workflow') if workflow_base else document
    if workflow_base and (not isinstance(body, dict) or body.get('version') != WORKFLOW):
        fail('INVALID_IDENTITY_SCOPE', 'A design needs an ordinary workflow', '$/workflow')
    if not isinstance(body, dict) or body.get('version') != WORKFLOW:
        return None, {}, [((), document, None)]
    operations = body.get('operations')
    if not isinstance(operations, list):
        fail('INVALID_IDENTITY_SCOPE', 'Workflow operations must be an array', '$' + pointer(workflow_base))
    sources, members = {}, []
    for index, operation in enumerate(operations):
        path = workflow_base + ('operations', str(index))
        if not isinstance(operation, dict) or not isinstance(operation.get('id'), str) or not isinstance(operation.get('document'), dict):
            fail('INVALID_IDENTITY_SCOPE', 'Each operation needs an explicit identity and document', '$' + pointer(path))
        if operation['id'] in sources:
            fail('AMBIGUOUS_IDENTITY_SCOPE', 'Workflow operation identities must be unique', '$' + pointer(path))
        from .pipeline import name
        name(operation['id'], '$' + pointer(path + ('id',)))
        sources[operation['id']] = path + ('document',)
        members.append((sources[operation['id']], operation['document'], operation['id']))
    return workflow_base, sources, members


def selected_values(document, selector, base=()):
    """Read only declared selector paths, retaining each original authored address."""
    if not selector:
        yield base, document
        return
    if isinstance(document, dict) and set(document) == {'$fill'}:
        return
    part, *rest = selector
    if part == ARRAY or part == MAP:
        expected = list if part == ARRAY else dict
        if not isinstance(document, expected):
            fail('UNRESOLVED_IDENTITY_REFERENCE', 'This reference collection must be literal before renaming', '$' + pointer(base))
        items = enumerate(document) if part == ARRAY else document.items()
        for key, child in items:
            yield from selected_values(child, rest, base + (str(key),))
    elif isinstance(document, dict):
        if part in document:
            yield from selected_values(document[part], rest, base + (part,))
        elif any(key.startswith('$') for key in document):
            fail('UNRESOLVED_IDENTITY_REFERENCE', 'This reference container must be literal before renaming', '$' + pointer(base))


def resolve_target(input, target, members):
    """Resolve an actual admitted authored slot; no result label conveys authority."""
    selected = [member for member in members if target[:len(member[0])] == member[0]]
    if not selected:
        fail('UNSUPPORTED_IDENTITY', 'Choose a declared identity within an operation document', '$' + pointer(target))
    base, document, operation = max(selected, key=lambda member: len(member[0]))
    from .adaptors import registry
    provider, route = registry.resolve(document)
    policy = for_route(provider, route)
    if policy is None:
        fail('UNSUPPORTED_IDENTITY', 'This exact route has no audited identity/reference policy', '$' + pointer(base),
             version=document.get('version'), provider=provider)
    choices = []
    for identity in policy['identities']:
        if local_identity(identity):
            owner_spec = identity['owner']
            owner_size = len(owner_spec['path'])
            relative = target[len(base):]
            if len(relative) != owner_size + len(identity['collection']) + 2:
                continue
            if any(part != ARRAY and part != token or part == ARRAY and not re.fullmatch(r'0|[1-9][0-9]*', token)
                   for part, token in zip(owner_spec['path'], relative)):
                continue
            owner = base + relative[:owner_size]
            collection = owner + tuple(identity['collection'])
        else:
            owner = None
            collection = base + tuple(identity['collection'])
        if (target[:len(collection)] == collection and len(target) == len(collection) + 2
                and re.fullmatch(r'0|[1-9][0-9]*', target[-2]) and target[-1] == identity['nameProperty']):
            if owner is not None:
                if not isinstance(read(input, owner[:-1]), list):
                    fail('INVALID_IDENTITY_SCOPE', 'Local owners must be array members', '$' + pointer(owner[:-1]))
                record = read(input, owner)
                discriminator = identity['owner']['discriminator']
                if not isinstance(record, dict) or record.get(discriminator['property']) != discriminator['value']:
                    fail('INVALID_IDENTITY_SCOPE', 'The local identity needs its literal declared owner', '$' + pointer(owner))
            choices.append((identity, owner))
    if len(choices) != 1:
        fail('UNSUPPORTED_IDENTITY', 'Choose one ordinary declared identity slot', '$' + pointer(target))
    identity, owner = choices[0]
    return base, document, operation, provider, route, policy, identity, owner


def local_values(value, selector, base):
    """Local identity consumers cannot hide unresolved containers or scalar fills."""
    if not selector:
        yield base, value
        return
    part, *rest = selector
    if part == ARRAY:
        if not isinstance(value, list):
            fail('UNRESOLVED_IDENTITY_REFERENCE', 'Local reference arrays must be literal', '$' + pointer(base))
        for index, child in enumerate(value):
            yield from local_values(child, rest, base + (str(index),))
    elif not isinstance(value, dict) or any(k.startswith('$') for k in value):
        fail('UNRESOLVED_IDENTITY_REFERENCE', 'Local reference containers must be literal objects', '$' + pointer(base))
    elif part in value:
        yield from local_values(value[part], rest, base + (part,))


def rename_identity(input, identity_pointer, new_name, expected_input_digest):
    """Return a checked candidate for one identity; never mutate ``input``.

    The digest is ``schemaxis.storage.digest(input)``. Unsupported consumers
    fail atomically. Syntax and relevant identity safety are checked, while
    unrelated missing options and semantic expression diagnostics are retained.
    """
    bounded(input)
    if not isinstance(input, dict):
        fail('INVALID_DOCUMENT', 'Identity preview needs an authored JSON object')
    before = digest(input)
    if not isinstance(expected_input_digest, str) or expected_input_digest != before:
        fail('STALE_IDENTITY_INPUT', 'The document changed; preview against its current digest')
    target = parts(identity_pointer, '$identityPointer')
    workflow_base, sources, members = scopes(input)
    base, document, operation, provider, route, policy, identity, local_owner = resolve_target(input, target, members)
    from .adaptors import registry
    is_local = local_identity(identity)
    old = read(input, target)
    if not accepts_name(old, identity['nameSchema']):
        fail('INVALID_IDENTITY', 'The existing identity violates its declared schema', '$' + identity_pointer)
    if not accepts_name(new_name, identity['nameSchema']):
        fail('INVALID_IDENTITY', 'The new identity violates its declared schema', '$newName', schema=identity['nameSchema'])
    projection = policy['projection'][identity['name']]
    edits, moves, nodes, named, constructions, indirect = {}, {}, [], {}, {}, []
    owned_references = {target}
    replacement_bytes = 0
    quoted_name = None

    def edit(path, value):
        nonlocal replacement_bytes
        if path in edits and edits[path] != value:
            fail('AMBIGUOUS_IDENTITY_REFERENCE', 'Conflicting edits address one reference', '$' + pointer(path))
        if read(input, path) != value:
            if path not in edits:
                replacement_bytes += bounded(value)
                if replacement_bytes > 1048576:
                    fail('IDENTITY_LIMIT', 'Identity replacements exceed the one MiB candidate limit')
            edits[path] = value

    def address(marker, path):
        if workflow_base is not None:
            from .adaptor_runtime import workflow_document_pointer
            local = pointer(path[len(workflow_base):])
            relative_sources = {key: pointer(value[len(workflow_base):]) for key, value in sources.items()}
            try:
                value = workflow_document_pointer(marker, local, relative_sources)
                if value is None:
                    value = reference_pointer(marker['$document'], local)
            except SchemaxisError as error:
                from dataclasses import replace
                raise type(error)(replace(error.fault, location='$' + pointer(path))) from error
            return workflow_base + parts(value, '$' + pointer(path))
        if set(marker) != {'$document'}:
            fail('INVALID_DOCUMENT_REFERENCE', 'Standalone references contain only $document', '$' + pointer(path))
        return parts(reference_pointer(marker['$document'], pointer(path)), '$' + pointer(path))

    def reference(value, path, multiple=False, port=True):
        if multiple:
            if not isinstance(value, list):
                if isinstance(value, dict) and '$document' in value:
                    indirect.append((value, path, True, port))
                    return
                if isinstance(value, dict) and set(value) == {'$fill'}:
                    return
                fail('UNRESOLVED_IDENTITY_REFERENCE', 'This reference list must be literal', '$' + pointer(path))
            for index, item in enumerate(value):
                reference(item, path + (str(index),), port=port)
        elif isinstance(value, str):
            if old != new_name and value == new_name:
                fail('IDENTITY_COLLISION', 'The destination name already occurs in an unresolved identity reference', '$' + pointer(path))
            owned_references.add(path)
            if value == old:
                edit(path, new_name)
        elif isinstance(value, dict):
            if set(value) == {'$fill'}:
                return
            if '$document' in value:
                indirect.append((value, path, False, port))
            elif set(value) == {'$object'}:
                reference(value['$object'], path + ('$object',), port=port)
            elif port and set(value) == {'node', 'port'} and type(value['port']) is int and value['port'] >= 0:
                reference(value['node'], path + ('node',), port=False)
            elif set(value) == {'$create'}:
                # The graph traversal checks definitions and their consumers separately.
                return
            else:
                fail('UNRESOLVED_IDENTITY_REFERENCE', 'This graph reference has no checked literal identity', '$' + pointer(path))
        else:
            fail('UNRESOLVED_IDENTITY_REFERENCE', 'Use a declared graph reference', '$' + pointer(path))

    if is_local:
        collection = local_owner + tuple(identity['collection'])
        ordinary = read(input, collection)
        if not isinstance(ordinary, list):
            fail('AMBIGUOUS_IDENTITY_SCOPE', 'Local identity collections must be literal arrays', '$' + pointer(collection))
        for index, item in enumerate(ordinary):
            at = collection + (str(index),)
            if not isinstance(item, dict) or not accepts_name(item.get(identity['nameProperty']), identity['nameSchema']):
                fail('INVALID_IDENTITY', 'Every local member needs a literal valid name', '$' + pointer(at))
            name = item[identity['nameProperty']]
            if name in named:
                fail('AMBIGUOUS_IDENTITY_SCOPE', 'Local names must be unique within their owner', '$' + pointer(at))
            named[name] = at
        if old != new_name and new_name in named:
            fail('IDENTITY_COLLISION', 'The local destination name already exists', '$newName')
        edit(target, new_name)
        for descriptor in policy['references']:
            if descriptor['identity'] != identity['name']:
                continue
            for at, value in local_values(read(input, local_owner), descriptor['path'], local_owner):
                if not isinstance(value, str):
                    fail('UNRESOLVED_IDENTITY_REFERENCE', 'Local references must be literal strings', '$' + pointer(at))
                if old != new_name and value == new_name:
                    fail('IDENTITY_COLLISION', 'A local reference already uses the destination name', '$' + pointer(at))
                owned_references.add(at)
                if value == old:
                    edit(at, new_name)
    else:
        collection = base + tuple(identity['collection'])
        name_property, graph = identity['nameProperty'], identity['graph']

        def graph_node(node, path, top, generated=None, owner=None):
            if not isinstance(node, dict):
                fail('AMBIGUOUS_IDENTITY_SCOPE', 'Graph definitions must be literal objects', '$' + pointer(path))
            if name_property not in node and owner == old and old != new_name:
                fail('UNSUPPORTED_IDENTITY_DESCENDANTS', 'Renaming this owner changes generated inline identities; descendant preservation is not implemented', '$' + pointer(path))
            name = node.get(name_property, generated)
            if name is not None:
                if not accepts_name(name, identity['nameSchema']):
                    fail('INVALID_IDENTITY', 'Graph identity violates its declared schema', '$' + pointer(path))
                construction = {**node, name_property: name}
                if name in constructions and constructions[name] != construction:
                    fail('AMBIGUOUS_IDENTITY_SCOPE', 'Repeated inline identities need identical constructions', '$' + pointer(path))
                constructions[name] = construction
                named.setdefault(name, path)
                if not top and name == old and name_property in node:
                    edit(path + (name_property,), new_name)
            elif top:
                fail('AMBIGUOUS_IDENTITY_SCOPE', 'Ordinary nodes need an explicit identity', '$' + pointer(path))
            kind = node.get(graph['discriminator'])
            if not isinstance(kind, str) or kind not in projection['operations']:
                fail('UNSUPPORTED_IDENTITY_REFERENCE', 'Rename requires literal declared graph discriminators, including incomplete template nodes', '$' + pointer(path + (graph['discriminator'],)))
            if graph['inputs'] is None:
                undeclared = sorted(set(node) - set(projection['properties'][kind]))
                if undeclared:
                    fail('UNSUPPORTED_IDENTITY_REFERENCE', 'This source node has no input container; an undeclared property could hold an unchecked reference',
                         '$' + pointer(path + (undeclared[0],)))
            inputs = node_inputs(node, graph)
            if not isinstance(inputs, dict) or set(inputs) - set(projection['operations'][kind]):
                fail('UNRESOLVED_IDENTITY_REFERENCE', 'Rename requires a literal input container with declared ports; unresolved container slots are unsupported', '$' + pointer(path + (graph['inputs'],)))
            nodes.append((node, path, projection['operations'][kind]))
            for port_name, value in inputs.items():
                input_path = path + (graph['inputs'], port_name)
                # Only the input construction grammar owns $create; native options do not.
                candidates = list(enumerate(value)) if isinstance(value, list) else [(None, value)]
                for index, candidate in candidates:
                    if isinstance(candidate, dict) and '$create' in candidate:
                        if set(candidate) != {'$create'}:
                            fail('UNRESOLVED_IDENTITY_REFERENCE', '$create must be the entire input', '$' + pointer(input_path))
                        from .context import inline_identity
                        generated = inline_identity(str(name), port_name, index)
                        graph_node(candidate['$create'], input_path + (() if index is None else (str(index),)) + ('$create',), False, generated, name)

        ordinary = read(input, collection)
        if not isinstance(ordinary, list):
            fail('AMBIGUOUS_IDENTITY_SCOPE', 'Identity collection must be a literal array', '$' + pointer(collection))
        for index, node in enumerate(ordinary):
            if isinstance(node, dict) and isinstance(node.get(name_property), str):
                name = node[name_property]
                if name in named:
                    fail('AMBIGUOUS_IDENTITY_SCOPE', 'Ordinary graph identities must be unique', '$' + pointer(collection + (str(index),)))
                named[name] = collection + (str(index),)
                constructions[name] = node
        for index, node in enumerate(ordinary):
            graph_node(node, collection + (str(index),), True)
        if new_name != old and new_name in named:
            fail('IDENTITY_COLLISION', 'The destination identity already exists, including inline definitions', '$newName')
        edit(target, new_name)
        for node, path, ports in nodes:
            for key, value in node_inputs(node, graph).items():
                reference(value, path + (graph['inputs'], key), ports[key]['multiple'], ports[key]['kind'] == 'data')
        for descriptor in policy['references']:
            if descriptor['identity'] != identity['name']:
                continue
            for path, value in selected_values(document, descriptor['path'], base):
                if isinstance(value, dict) and set(value) == {'$fill'}:
                    continue
                shape = descriptor['shape']
                if shape == 'keys':
                    if not isinstance(value, dict) or any(key.startswith('$') for key in value):
                        fail('UNRESOLVED_IDENTITY_REFERENCE', 'Reference map keys must be literal identities', '$' + pointer(path))
                    if old != new_name and new_name in value:
                        fail('IDENTITY_COLLISION', 'The destination name already occurs in a reference map', '$' + pointer(path + (new_name,)))
                    if old in value and old != new_name:
                        if new_name in value:
                            fail('IDENTITY_COLLISION', 'Renaming would overwrite an existing map key', '$' + pointer(path + (new_name,)))
                        moves[path] = (old, new_name)
                elif shape == 'writer-resources':
                    owner = read(input, path[:-1])
                    writer = owner.get(descriptor['discriminator'])
                    declared = projection['writers'].get(writer) if isinstance(writer, str) else None
                    if declared is None or not isinstance(value, dict):
                        fail('UNRESOLVED_IDENTITY_REFERENCE', 'Export resources need a declared writer', '$' + pointer(path))
                    allowed = {key: port for key, port in declared.items() if port['kind'] != 'data'}
                    if set(value) - set(allowed):
                        fail('UNRESOLVED_IDENTITY_REFERENCE', 'Export resources must name declared resource ports', '$' + pointer(path))
                    for key, item in value.items():
                        # Publication's schema uses a scalar resource identity even for a writer port.
                        reference(item, path + (key,), port=False)
                else:
                    reference(value, path, shape == 'list', port=False)

    # Direct markers bind in this operation. Borrowed JSON is audited below at its consuming scope.
    from . import expr, expressions
    from .expr import syntax
    scope = None
    markers = {m['key'] for m in policy['markers'] if m['identity'] == identity['name']}
    undeclared_markers = frozenset() if is_local else GRAPH_MARKERS - {m['key'] for m in policy['markers']}
    document_references = []
    for path, value in walk(input):
        if not isinstance(value, dict):
            continue
        selected_scope = path[:len(base)] == base
        # The whole document is syntax checked, but only the selected lexical scope binds node calls.
        if isinstance(value.get('$expr'), str):
            text = value['$expr']
            try:
                tree = syntax.parse(text)
                replacements = []
                if selected_scope and policy['expressions'].get('extents') == identity['name']:
                    for node in expressions.preorder(tree):
                        if isinstance(node, syntax.Call) and node.name == 'extents':
                            # Call binding is authoritative; unrelated expression types are not executed/checked.
                            candidate_name = node.arguments[0].name if node.arguments and isinstance(node.arguments[0], syntax.Name) else None
                            if candidate_name not in (None, old, new_name):
                                continue
                            if scope is None:
                                scope = expressions.Scope(document, axes={}, adaptor=expressions.Adaptor(
                                    bool(registry.metadata(provider).get('extents')), registry.declarations(provider), provider))
                                scope.nodes = {name: read(input, site).get(graph['discriminator']) for name, site in named.items()}
                            capture = old != new_name and candidate_name == new_name
                            if capture:
                                scope.nodes[new_name] = scope.nodes[old]
                            try:
                                info = expr.Checker(text, scope).check(node)
                            finally:
                                if capture:
                                    del scope.nodes[new_name]
                            if capture and isinstance(info.target, expressions.ExtentsFunction):
                                fail('IDENTITY_COLLISION', 'The destination name already occurs in an unresolved extents binding', '$' + pointer(path + ('$expr',)))
                            if isinstance(info.target, expressions.ExtentsFunction) and info.target.scope is scope and info.target.node == old:
                                token = node.arguments[0]
                                if quoted_name is None:
                                    quoted_name = '`' + new_name + '`'
                                    quoted = syntax.parse(quoted_name)
                                    if not isinstance(quoted, syntax.Name) or quoted.name != new_name:
                                        fail('INVALID_IDENTITY', 'The new identity cannot be represented as an expression name', '$newName')
                                replacements.append((token.position, token.length, quoted_name))
                if old != new_name:
                    if len(text) + sum(len(replacement) - length for _, length, replacement in replacements) > syntax.MAX_LENGTH:
                        fail('UNRESOLVED_IDENTITY_EXPRESSION', 'Renamed expression exceeds the host expression length limit',
                             '$' + pointer(path + ('$expr',)), expressionCode='EXPR_LIMIT')
                    for start, length, replacement in sorted(replacements, reverse=True):
                        text = text[:start] + replacement + text[start + length:]
                    edit(path + ('$expr',), text)
            except expr.ExprFault as error:
                fail('UNRESOLVED_IDENTITY_EXPRESSION', error.message, '$' + pointer(path + ('$expr',)),
                     expressionCode=error.code, position=error.position)
        if selected_scope:
            for marker in markers & set(value):
                reference(value[marker], path + (marker,), port=marker == '$object')
            for marker in undeclared_markers & set(value):
                if not isinstance(value[marker], str) or value[marker] in (old, new_name):
                    fail('UNSUPPORTED_IDENTITY_REFERENCE', 'This route declares no identity contract for this graph marker',
                         '$' + pointer(path + (marker,)))
        if '$document' in value:
            # Design metadata is not a document-composition context.
            if workflow_base and path[:len(workflow_base)] != workflow_base:
                continue
            destination = address(value, path)
            document_references.append((path, value, destination))
        if operation is not None and (value.get('$artifact') == operation or
                '$value' in value and 'path' in value and value['$value'] == operation):
            fail('UNSUPPORTED_IDENTITY_OUTPUT_REFERENCE', 'The renamed producer has a runtime output consumer; an output identity contract is required', '$' + pointer(path))

    if document_references and old != new_name:
        # Audit borrowed JSON at its consuming operation, with physical-source
        # provenance. Only $document is followed: no values/expressions are
        # executed, and ordinary incomplete metadata remains authored.
        policies = {(provider, document.get('version')): policy}
        peers = []
        for consumer, original, _ in members:
            try:
                owner, member_route = registry.resolve(original)
            except SchemaxisError:
                peers.append((consumer, None, None))
                continue
            route_key = (owner, original.get('version'))
            if route_key not in policies:
                policies[route_key] = for_route(owner, member_route)
            peers.append((consumer, owner, policies[route_key]))
        check_origin_budget = any(item and item['version'] == LOCAL_VERSION for item in policies.values())
        origins, remaining = {}, [100000]
        origin_budget = _ORIGIN_BYTES

        def record_origin(site, origin, imports):
            nonlocal origin_budget
            if check_origin_budget and imports:
                for address in (site, origin, *imports):
                    for token in address:
                        origin_budget -= len(token) + 1 + token.count('/') + token.count('~')
                        if origin_budget < 0:
                            fail('IDENTITY_LIMIT', 'Document-reference provenance exceeds one MiB')
            origins[site] = (origin, imports)

        def borrowed(value, origin, site, imports=(), active=frozenset(), depth=0):
            remaining[0] -= 1
            if remaining[0] < 0 or depth > 64:
                fail('IDENTITY_LIMIT', 'Document-reference inspection exceeds its bounded expansion', '$' + pointer(site))
            if isinstance(value, dict) and '$document' in value:
                destination = address(value, origin)
                if destination in active:
                    fail('UNRESOLVED_IDENTITY_REFERENCE', 'Document reference cycle during identity inspection', '$' + pointer(site))
                try:
                    source = read(input, destination)
                except SchemaxisError as error:
                    if error.fault.code != 'UNKNOWN_IDENTITY_REFERENCE':
                        raise
                    record_origin(site, origin, imports)
                    return copy.deepcopy(value)  # Unrelated missing metadata is not a planning requirement.
                return borrowed(source, destination, site, imports + (site,), active | {destination}, depth + 1)
            record_origin(site, origin, imports)
            if isinstance(value, dict):
                return {key: borrowed(child, origin + (key,), site + (key,), imports, active, depth + 1)
                        for key, child in value.items()}
            if isinstance(value, list):
                return [borrowed(child, origin + (str(i),), site + (str(i),), imports, active, depth + 1)
                        for i, child in enumerate(value)]
            return value

        if workflow_base:
            effective = {**input, 'workflow': borrowed(input['workflow'], workflow_base, workflow_base)}
        else:
            effective = borrowed(input, (), ())

        def audit_values(member, selector, consumer):
            try:
                return list(selected_values(member, selector, consumer))
            except SchemaxisError as error:
                if consumer != base and error.fault.code == 'UNRESOLVED_IDENTITY_REFERENCE':
                    return []  # An unrelated peer's unfilled container is not a full-plan gate.
                raise

        def owning_scope(path):
            return next((member[0] for member in members if path[:len(member[0])] == member[0]), None)

        def audit_name(name, site, consumer, *, key=False, local_namespace=None):
            if name not in (old, new_name):
                return
            origin, imports = origins.get(site, (site, ()))
            if not imports:
                return
            selected_consumer = (local_namespace == local_owner if is_local else local_namespace is None and consumer == base)
            if selected_consumer and name == new_name:
                fail('IDENTITY_COLLISION', 'A borrowed identity reference already uses the destination name',
                     '$' + pointer(imports[0]), reference=pointer(site), origin=pointer(origin))
            changed_source = origin in edits or key and origin in moves
            if name == old and ((selected_consumer and owning_scope(origin) != base) or
                                (not selected_consumer and changed_source)):
                fail('UNSUPPORTED_IDENTITY_COMPOSITION',
                     'This borrowed identity-bearing value binds in another operation; cross-scope rebinding is not implemented',
                     '$' + pointer(imports[0]), reference=pointer(site), origin=pointer(origin))

        def audit_reference(value, path, consumer):
            if isinstance(value, str):
                audit_name(value, path, consumer)
            elif isinstance(value, list):
                for i, child in enumerate(value):
                    audit_reference(child, path + (str(i),), consumer)
            elif isinstance(value, dict):
                if 'node' in value:
                    audit_reference(value['node'], path + ('node',), consumer)
                elif '$object' in value:
                    audit_reference(value['$object'], path + ('$object',), consumer)

        def reject_changed_borrow(site, message):
            origin, imports = origins.get(site, (site, ()))
            if imports and (origin in edits or origin in moves):
                fail('UNSUPPORTED_IDENTITY_COMPOSITION', message, '$' + pointer(imports[0]),
                     reference=pointer(site), origin=pointer(origin))

        for consumer, owner, member_policy in peers:
            member = read(effective, consumer)
            if member_policy is None:
                if owner is not None or is_local:
                    for site in origins:
                        if site[:len(consumer)] == consumer:
                            reject_changed_borrow(site, 'A changed identity-bearing value is imported into a route without an audited reference policy')
                continue
            if member_policy['version'] == LOCAL_VERSION:
                for at, _ in audit_values(member, ['nodes', ARRAY, 'id'], consumer):
                    reject_changed_borrow(at, 'A changed identity-bearing value is imported into a publication identity')
            for kind in member_policy['identities']:
                if local_identity(kind):
                    owner_spec = kind['owner']
                    for owner_at, owner_value in audit_values(member, owner_spec['path'], consumer):
                        discriminator = owner_spec['discriminator']
                        if not isinstance(owner_value, dict):
                            continue
                        reject_changed_borrow(owner_at + (discriminator['property'],),
                                              'A changed identity-bearing value is imported into an owner discriminator')
                        if owner_value.get(discriminator['property']) != discriminator['value']:
                            continue
                        for collection_at, items in audit_values(owner_value, kind['collection'], owner_at):
                            if isinstance(items, list):
                                for i, item in enumerate(items):
                                    if isinstance(item, dict):
                                        audit_name(item.get(kind['nameProperty']), collection_at + (str(i), kind['nameProperty']),
                                                   consumer, local_namespace=owner_at)
                        for descriptor in member_policy['references']:
                            if descriptor['identity'] == kind['name']:
                                for at, value in audit_values(owner_value, descriptor['path'], owner_at):
                                    audit_name(value, at, consumer, local_namespace=owner_at)
                    continue
                graph_spec = kind['graph']
                projected = member_policy['projection'][kind['name']]
                candidates = audit_values(member, kind['collection'], consumer)
                for location, definitions in candidates:
                    if not isinstance(definitions, list):
                        continue
                    def audit_node(node, path):
                        if not isinstance(node, dict):
                            return
                        audit_name(node.get(kind['nameProperty']), path + (kind['nameProperty'],), consumer)
                        operation_name = node.get(graph_spec['discriminator'])
                        ports = projected['operations'].get(operation_name, {}) if isinstance(operation_name, str) else {}
                        inputs = node_inputs(node, graph_spec)
                        if isinstance(inputs, dict):
                            for port_name in ports.keys() & inputs.keys():
                                at = path + (graph_spec['inputs'], port_name)
                                audit_reference(inputs[port_name], at, consumer)
                                for nested, child in walk(inputs[port_name], at):
                                    if isinstance(child, dict) and set(child) == {'$create'}:
                                        audit_node(child['$create'], nested + ('$create',))
                    for i, node in enumerate(definitions):
                        audit_node(node, location + (str(i),))
                for descriptor in member_policy['references']:
                    if descriptor['identity'] != kind['name']:
                        continue
                    for at, value in audit_values(member, descriptor['path'], consumer):
                        if descriptor['shape'] == 'keys' and isinstance(value, dict):
                            for name in value:
                                audit_name(name, at, consumer, key=True)
                        elif descriptor['shape'] == 'writer-resources' and isinstance(value, dict):
                            for name, child in value.items():
                                audit_reference(child, at + (name,), consumer)
                        else:
                            audit_reference(value, at, consumer)
            member_scope = None
            for at, value in walk(member, consumer):
                if not isinstance(value, dict):
                    continue
                for record in member_policy['markers']:
                    if record['key'] in value:
                        audit_reference(value[record['key']], at + (record['key'],), consumer)
                if not isinstance(value.get('$expr'), str) or 'extents' not in member_policy['expressions']:
                    continue
                origin, imports = origins.get(at + ('$expr',), (at, ()))
                if not imports:
                    continue
                source = value['$expr']
                for call in expressions.preorder(syntax.parse(source)):
                    if not isinstance(call, syntax.Call):
                        continue
                    if member_scope is None:
                        member_scope = expressions.Scope(member, axes={}, adaptor=expressions.Adaptor(
                            bool(registry.metadata(owner).get('extents')), registry.declarations(owner), owner))
                    if not isinstance(member_scope.function(call.name), expressions.ExtentsFunction):
                        continue
                    # Check through the host binding. Add the prospective identity
                    # only for detecting capture of an otherwise unresolved name.
                    candidate = call.arguments[0].name if call.arguments and isinstance(call.arguments[0], syntax.Name) else None
                    if candidate not in (old, new_name):
                        continue
                    if is_local and origin not in edits:
                        continue
                    if not isinstance(member_scope.nodes, dict):
                        fail('UNSUPPORTED_IDENTITY_COMPOSITION', 'The importing operation needs a literal graph scope to check this borrowed extents binding',
                             '$' + pointer(imports[0]))
                    previous = member_scope.nodes.get(candidate)
                    if is_local:
                        if candidate not in member_scope.nodes:
                            fail('UNSUPPORTED_IDENTITY_COMPOSITION', 'An imported graph binding needs an explicit consumer identity',
                                 '$' + pointer(imports[0]))
                    else:
                        member_scope.nodes.setdefault(candidate, read(input, target[:-1])[graph['discriminator']])
                    try:
                        info = expr.Checker(source, member_scope).check(call)
                    except expr.ExprFault as error:
                        fail('UNRESOLVED_IDENTITY_EXPRESSION', error.message, '$' + pointer(imports[0]), expressionCode=error.code)
                    finally:
                        if previous is None:
                            member_scope.nodes.pop(candidate, None)
                    if isinstance(info.target, expressions.ExtentsFunction):
                        audit_name(info.target.node, at + ('$expr',), consumer)

    def moved(path):
        result = list(path)
        for parent, (previous, current) in moves.items():
            if path[:len(parent)] == parent and len(path) > len(parent) and path[len(parent)] == previous:
                result[len(parent)] = current
        return tuple(result)

    def relative(destination, site):
        parent = site[:-1]
        common = 0
        while common < min(len(parent), len(destination)) and parent[common] == destination[common]:
            common += 1
        up = len(parent) - common
        suffix = '/'.join(str(p).replace('~', '~0').replace('/', '~1') for p in destination[common:])
        return ('../' * up if up else './') + suffix

    for path, marker, destination in document_references:
        changed = moved(destination)
        site = moved(path)
        if changed == destination and site == path:
            continue
        original = marker['$document']
        if not original.startswith('/'):
            replacement = relative(changed, site)
        elif 'operation' in marker:
            replacement = pointer(changed[len(sources[marker['operation']]):])
        elif marker.get('scope') == 'workflow':
            replacement = pointer(changed[len(workflow_base):])
        else:
            owner = next((member[0] for member in members if path[:len(member[0])] == member[0]), workflow_base or ())
            replacement = pointer(changed[len(owner):])
        edit(path + ('$document',), replacement)

    # An indirect graph identity must be owned by the same checked identity contract.
    def check_indirect(marker, path, multiple, port, seen):
        destination = address(marker, path)
        if destination in seen:
            fail('UNRESOLVED_IDENTITY_REFERENCE', 'Document reference cycle', '$' + pointer(path))
        value = read(input, destination)
        if isinstance(value, dict) and '$document' in value:
            return check_indirect(value, destination, multiple, port, seen | {destination})
        def check(value, path):
            if isinstance(value, str) and value == old and path not in owned_references:
                fail('UNSUPPORTED_INDIRECT_IDENTITY', 'This graph reference reads an unowned string; preserve the recipe and declare its identity semantics first', '$' + pointer(path))
            elif isinstance(value, list):
                for i, child in enumerate(value):
                    check(child, path + (str(i),))
            elif isinstance(value, dict) and 'node' in value:
                check(value['node'], path + ('node',))
            elif not isinstance(value, str):
                fail('UNRESOLVED_IDENTITY_REFERENCE', 'Indirect graph reference is not a literal identity', '$' + pointer(path))
        check(value, destination)
    for marker, path, multiple, port in indirect:
        check_indirect(marker, path, multiple, port, set())

    # Framework design pointers are relative to their owning operation document.
    if input.get('version') in DESIGNS:
        for owner, record in mapping(input.get('ports', {}), ('ports',)).items():
            if owner not in sources or not isinstance(record, dict):
                fail('INVALID_IDENTITY_SCOPE', 'Design ports need an existing operation owner', '$/ports')
            if owner == operation and record.get('outputs'):
                fail('UNSUPPORTED_IDENTITY_OUTPUT_REFERENCE', 'Design output ports need a producer output identity contract', '$/ports/' + owner)
            for name, spec in mapping(record.get('inputs', {}), ('ports', owner, 'inputs')).items():
                path = ('ports', owner, 'inputs', name, 'target')
                mapping(spec, path[:-1])
                destination = sources[owner] + parts(spec.get('target'), '$' + pointer(path))
                changed = moved(destination)
                if changed != destination:
                    edit(path, pointer(changed[len(sources[owner]):]))
        connections = input.get('connections', [])
        if not isinstance(connections, list):
            fail('INVALID_IDENTITY_SCOPE', 'Design connections must be an array', '$/connections')
        for index, connection in enumerate(connections):
            mapping(connection, ('connections', str(index)))
            if 'from' in connection:
                mapping(connection['from'], ('connections', str(index), 'from'))
            if connection.get('source') == operation or connection.get('from', {}).get('operation') == operation:
                fail('UNSUPPORTED_IDENTITY_OUTPUT_REFERENCE', 'Design connections from this producer need an output identity contract', '$/connections/' + str(index))
            if isinstance(connection.get('target'), str) and connection['target'] in sources and 'targetPointer' in connection:
                owner = connection['target']
                path = ('connections', str(index), 'targetPointer')
                destination = sources[owner] + parts(connection['targetPointer'], '$' + pointer(path))
                if moved(destination) != destination:
                    edit(path, pointer(moved(destination)[len(sources[owner]):]))
        for name, output in mapping(input.get('outputs', {}), ('outputs',)).items():
            mapping(output, ('outputs', name))
            if output.get('operation') == operation:
                fail('UNSUPPORTED_IDENTITY_OUTPUT_REFERENCE', 'Named outputs need a producer output identity contract', '$/outputs/' + name)

    def apply(value, path=()):
        if path in edits:
            return copy.deepcopy(edits[path])
        if isinstance(value, dict):
            change = moves.get(path)
            return {(change[1] if change and key == change[0] else key): apply(child, path + (key,))
                    for key, child in value.items()}
        if isinstance(value, list):
            return [apply(child, path + (str(i),)) for i, child in enumerate(value)]
        return value
    result = apply(input)
    bounded(result)
    identity_changes = [] if old == new_name else [{
        'identity': identity['name'], 'scope': pointer(base), 'pointer': identity_pointer,
        'old': old, 'new': new_name, 'route': document['version'], 'provider': provider}]
    if is_local and identity_changes:
        identity_changes[0].update(domain='owner-local', owner=pointer(local_owner), collection=pointer(collection))
    try:
        provenance_size = bounded({'changedPointers': [], 'identityChanges': identity_changes})
    except SchemaxisError as error:
        if error.fault.code == 'IDENTITY_LIMIT':
            fail('IDENTITY_LIMIT', 'Identity change provenance is limited to one MiB', '$identityChanges')
        raise
    changed = []
    # Shared long path prefixes can amplify small JSON into huge provenance.
    # Budget the encoded address before constructing it, including JSON and
    # RFC 6901 escaping; tuple deduplication does not duplicate prefix strings.
    for path in set(edits) | {path + (old,) for path in moves}:
        address_size = 2 + sum(1 + bounded(part) - 2 + part.count('~') + part.count('/') for part in path)
        provenance_size += address_size + bool(changed)
        if provenance_size > 1048576:
            fail('IDENTITY_LIMIT', 'Identity change provenance is limited to one MiB', '$changedPointers')
        changed.append(pointer(path))
    changed.sort()
    return {'version': 'schemaxis.identity-change/2' if is_local else VERSION, 'input': result, 'inputDigest': before, 'outputDigest': digest(result),
            'policyDigest': digest(policy),
            'changedPointers': changed, 'identityChanges': identity_changes}
