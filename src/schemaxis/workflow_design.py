# Copyright (C) 2026 David L F Gaden
"""Persisted workflow wiring and feedback configuration, without native execution.

The ordinary workflow remains the input baseline. Connections override existing
inputs; removing a connection restores that baseline. Runtime data cycles are
explicit design objects, never silently accepted by the ordinary DAG executor.

Version 2 adds named, typed ports, template parameters, named outputs, output
naming and a presentation-only layout. Each port-to-port connection compiles to
exactly one version 1 connection, so validation, loop detection, controller
identity and DAG compilation are shared rather than duplicated.
"""
import copy
import json
import math
from pathlib import Path
import re

from . import output_naming, storage, workflow, workflow_templates
from .adaptor_runtime import workflow_inputs, output_reference
from .adaptors import registry
from .core.faults import SchemaxisError
from .errors import fail, keys
from .unfilled import find_unfilled, reject_unfilled
from .pipeline import name
from . import workflow_loop_controls as controls

VERSION = 'schemaxis.workflow-design/1'
VERSION_2 = 'schemaxis.workflow-design/2'
DATA_KINDS = ('geometry', 'image', 'video', 'table', 'series', 'text', 'number', 'vector', 'audio', 'archive')
EMPTY = {'version': 'schemaxis.workflow/1', 'operations': []}
_MAX_OPERATIONS = 256
_MAX_CONNECTIONS = 2048


def _json(value):
    remaining = [100000]
    ancestors = set()

    def visit(item, path, depth):
        remaining[0] -= 1
        if remaining[0] < 0 or depth > 64:
            fail('RESOURCE_LIMIT', 'design JSON exceeds 100000 values or 64 nesting levels; split the design', path)
        if type(item) in (dict, list):
            if id(item) in ancestors:
                fail('INVALID_DOCUMENT', 'JSON reference cycles are not allowed; use declared connections', path)
            ancestors.add(id(item))
            for key, child in item.items() if type(item) is dict else enumerate(item):
                if type(item) is dict and not isinstance(key, str):
                    fail('INVALID_DOCUMENT', 'JSON object keys must be strings', path)
                visit(child, path + '/' + str(key), depth + 1)
            ancestors.remove(id(item))
        elif type(item) is float and not math.isfinite(item):
            fail('INVALID_DOCUMENT', 'use finite JSON numbers', path)
        elif item is not None and type(item) not in (str, int, float, bool):
            fail('INVALID_DOCUMENT', 'expected JSON data', path)
    visit(value, '$', 0)
    if len(storage.encoded(value)) > 1048576:
        fail('RESOURCE_LIMIT', 'design exceeds 1 MiB; split the design')


def _parts(pointer, location):
    if not isinstance(pointer, str) or (pointer and not pointer.startswith('/')) or re.search(r'~(?![01])', pointer):
        fail('INVALID_CONNECTION', 'use an RFC 6901 JSON pointer with ~0 and ~1 escapes', location)
    return tuple(part.replace('~1', '/').replace('~0', '~') for part in pointer.split('/')[1:])


def _member(value, part, location):
    if isinstance(value, dict) and part in value:
        return part
    if isinstance(value, list) and re.fullmatch(r'0|[1-9][0-9]*', part) and len(part) <= len(str(len(value))):
        index = int(part)
        if index < len(value):
            return index
    fail('INVALID_CONNECTION', 'connection target is absent; choose a current input', location)


def _lookup(value, parts, location):
    for part in parts:
        value = value[_member(value, part, location)]
    return value


def _replace(value, parts, replacement, location):
    parent = _lookup(value, parts[:-1], location)
    parent[_member(parent, parts[-1], location)] = replacement


def _escape(part):
    return str(part).replace('~', '~0').replace('/', '~1')


def _walk(value, path=''):
    yield path, value
    if isinstance(value, dict):
        # Marker internals are contracts, not independent user inputs.
        if any(key.startswith('$') for key in value):
            return
        for key, child in value.items():
            yield from _walk(child, path + '/' + _escape(key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, path + '/' + str(index))


def _references(value, path=''):
    if isinstance(value, dict):
        if '$artifact' in value or output_reference(value) or '$document' in value:
            yield path, value
            return
        for key, child in value.items():
            yield from _references(child, path + '/' + _escape(key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _references(child, path + '/' + str(index))


def _input_scope(parts):
    return (len(parts) >= 2 and parts[0] in ('dimensions', 'definitions', 'settings') or
            len(parts) >= 4 and parts[0] == 'nodes' and
            re.fullmatch(r'0|[1-9][0-9]*', parts[1]) is not None and parts[2] == 'options')


def _input_kind(value, resolved):
    if isinstance(resolved, dict) and '$fill' in resolved:
        if resolved.get('type') in ('number', 'integer'):
            return 'value'
        if resolved.get('type') in ('path', 'string'):
            return 'artifact'
    if type(value) in (int, float) or output_reference(value):
        return 'value'
    if isinstance(value, dict) and any(key in value for key in ('$document', '$expr', '$value')) and type(resolved) in (int, float):
        return 'value'
    if isinstance(value, str) or isinstance(value, dict) and '$artifact' in value:
        return 'artifact'
    if isinstance(value, dict) and '$document' in value and isinstance(resolved, str):
        return 'artifact'
    return None


def _inputs(body, resolved):
    result = []
    for operation, effective in zip(body['operations'], resolved['operations']):
        for pointer, value in _walk(operation['document']):
            parts = _parts(pointer, pointer)
            if not _input_scope(parts):
                continue
            current = _lookup(effective['document'], parts, pointer)
            kind = _input_kind(value, current)
            if kind:
                result.append({'operation': effective['id'], 'pointer': pointer,
                               'label': pointer, 'kind': kind, 'value': copy.deepcopy(value)})
    return result


def _connection(value, operations, inputs, location):
    keys(value, ('id', 'source', 'target', 'targetPointer', 'kind', 'artifactIndex', 'valuePath'), location)
    name(value.get('id'), location + '.id')
    for field in ('source', 'target'):
        if not isinstance(value.get(field), str) or value[field] not in operations:
            fail('INVALID_CONNECTION', 'choose an existing operation for ' + field, location + '.' + field)
    kind = value.get('kind')
    if kind not in ('value', 'artifact'):
        fail('INVALID_CONNECTION', 'connection kind must be value or artifact', location + '.kind')
    pointer = value.get('targetPointer')
    parts = _parts(pointer, location + '.targetPointer')
    if not _input_scope(parts):
        fail('INVALID_CONNECTION', 'choose an existing numeric or file input under node options or input metadata', location + '.targetPointer')
    match = next((item for item in inputs if item['operation'] == value['target'] and item['pointer'] == pointer), None)
    if match is None or match['kind'] != kind:
        fail('INVALID_CONNECTION', 'choose a compatible existing numeric or file input', location + '.targetPointer')
    index = value.get('artifactIndex')
    if type(index) is not int or index < 0:
        fail('INVALID_CONNECTION', 'artifactIndex must be a nonnegative integer', location + '.artifactIndex')
    if kind == 'value':
        if 'valuePath' not in value:
            fail('INVALID_CONNECTION', 'numeric connections need valuePath within the producer artifact', location + '.valuePath')
        _parts(value['valuePath'], location + '.valuePath')
    elif 'valuePath' in value:
        fail('INVALID_CONNECTION', 'artifact connections do not use valuePath', location + '.valuePath')
    return parts


def _semantic(edge):
    return {key: edge[key] for key in ('source', 'target', 'targetPointer', 'kind', 'artifactIndex',
                                     'valuePath', 'visit') if key in edge}



def _authored_pointer(document, pointer):
    """Resolved aliases can expand containers; locate their retained declaration."""
    value, retained = document, []
    for part in _parts(pointer, pointer):
        if isinstance(value, dict) and '$document' in value:
            break
        if isinstance(value, dict) and part in value:
            key = part
        elif (isinstance(value, list) and re.fullmatch(r'0|[1-9][0-9]*', part)
              and len(part) <= len(str(len(value))) and int(part) < len(value)):
            key = int(part)
        else:
            break
        value = value[key]
        retained.append(part)
    return ''.join('/' + _escape(part) for part in retained)


def _edge(source, target, pointer, ref, origin='base', identity=None, source_pointer=None):
    if '$artifact' in ref:
        values = {'kind': 'artifact', 'artifactIndex': ref['index']}
    elif output_reference(ref):
        values = {'kind': 'value', 'valuePath': ref['path'], 'artifactIndex': ref.get('artifact'),
                  'visit': ref.get('visit', 0)}
    else:
        values = {'kind': 'document-reference', 'valuePath': ref['$document']}
    result = {'source': source, 'target': target, 'targetPointer': pointer,
              'origin': origin, 'removable': origin == 'connection', 'feedbackEligible': '$document' not in ref,
              **values}
    result['id'] = identity or 'base-' + storage.digest(_semantic(result))[:24]
    result['pointer'] = source_pointer
    return result


def _components(identities, edges):
    adjacency = {identity: set() for identity in identities}
    for edge in edges:
        if edge['feedbackEligible']:
            adjacency[edge['source']].add(edge['target'])
    indices, low, active, stack, result = {}, {}, set(), [], []

    def visit(node):
        indices[node] = low[node] = len(indices)
        stack.append(node)
        active.add(node)
        for child in sorted(adjacency[node]):
            if child not in indices:
                visit(child)
                low[node] = min(low[node], low[child])
            elif child in active:
                low[node] = min(low[node], indices[child])
        if low[node] == indices[node]:
            members = []
            while True:
                child = stack.pop()
                active.remove(child)
                members.append(child)
                if child == node:
                    break
            if len(members) > 1 or node in adjacency[node]:
                result.append(sorted(members))
    for identity in identities:
        if identity not in indices:
            visit(identity)
    return sorted(result)


def _prepare(document, allowed, version):
    """Shared envelope and body checks for every design version."""
    _json(document)
    keys(document, allowed, '$')
    if document.get('version') != version:
        fail('UNSUPPORTED_VERSION', 'expected ' + version)
    body = document.get('workflow')
    keys(body, ('version', 'operations', 'execution', 'dimensions', 'definitions', 'settings', 'axes', 'maxStates'), '$.workflow')
    if body.get('version') != EMPTY['version']:
        fail('UNSUPPORTED_VERSION', 'design.workflow must be schemaxis.workflow/1', '$.workflow.version')
    operations = body.get('operations')
    if not isinstance(operations, list) or len(operations) > _MAX_OPERATIONS:
        fail('RESOURCE_LIMIT', 'workflow operations must be a list of at most 256 entries', '$.workflow.operations')
    if operations:
        if find_unfilled(body):
            workflow.validate(body, allow_unfilled=True)
        else:
            workflow.inspect_plan(body)
    resolved = workflow_inputs(body, defer_unfilled=True)
    inputs = _inputs(body, resolved)
    by_id = {effective['id']: operation for operation, effective in zip(operations, resolved['operations'])}
    return body, resolved, inputs, by_id


def _connection_list(document):
    connections = document.get('connections')
    if not isinstance(connections, list) or len(connections) > _MAX_CONNECTIONS:
        fail('RESOURCE_LIMIT', 'connections must be a list of at most 2048 entries', '$.connections')
    return connections


def _state(document, *, check_controllers=True):
    if isinstance(document, dict) and document.get('version') == VERSION_2:
        return _state_v2(document, check_controllers=check_controllers)[0]
    if isinstance(document, dict) and document.get('version') != VERSION:
        _json(document)
        fail('UNSUPPORTED_VERSION', 'expected ' + VERSION + ' or ' + VERSION_2, '$.version')
    prepared = _prepare(document, ('version', 'workflow', 'connections', 'controllers'), VERSION)
    return _wire(document, *prepared, _connection_list(document), check_controllers=check_controllers)


def _wire(document, body, resolved, inputs, by_id, connections, *, check_controllers=True):
    """Apply ordinary (version 1) connections and derive edges and loops."""
    controllers = document.get('controllers')
    if not isinstance(controllers, dict):
        fail('INVALID_FEEDBACK_CONTROLLER', 'controllers must be an object keyed by current loop IDs', '$.controllers')
    effective = copy.deepcopy(body)
    effective_ops = {source['id']: operation for source, operation in zip(resolved['operations'], effective['operations'])}
    used_ids, targets = set(), {}
    for index, connection in enumerate(connections):
        location = '$.connections/' + str(index)
        parts = _connection(connection, by_id, inputs, location)
        if connection['id'] in used_ids:
            fail('INVALID_CONNECTION', 'connection IDs must be unique', location + '.id')
        used_ids.add(connection['id'])
        for previous in targets.get(connection['target'], []):
            if parts[:len(previous)] == previous or previous[:len(parts)] == parts:
                fail('INVALID_CONNECTION', 'connection targets must not overlap; replace or remove the earlier connection', location + '.targetPointer')
        targets.setdefault(connection['target'], []).append(parts)
        ref = ({'$artifact': connection['source'], 'index': connection['artifactIndex']} if connection['kind'] == 'artifact'
               else {'$value': connection['source'], 'artifact': connection['artifactIndex'], 'path': connection['valuePath']})
        _replace(effective_ops[connection['target']]['document'], parts, ref, location)
    resolved_effective = workflow_inputs(effective, defer_unfilled=True)
    for original, current in zip(resolved['operations'], resolved_effective['operations']):
        if current['id'] != original['id'] or current['document'].get('version') != original['document'].get('version'):
            fail('INVALID_CONNECTION', 'data arrows cannot alter operation identities or document versions through aliases; choose a runtime input', '$.connections')
    edges = []
    connection_by_target = {(item['target'], item['targetPointer']): (index, item) for index, item in enumerate(connections)}
    for index, operation in enumerate(resolved_effective['operations']):
        for pointer, ref in _references(operation['document']):
            if '$artifact' not in ref and not output_reference(ref):
                continue
            source = ref.get('$artifact', ref.get('$value'))
            if not isinstance(source, str) or source not in by_id:
                fail('INVALID_CONNECTION', 'runtime reference producer is absent; repair the workflow input', pointer)
            authored = connection_by_target.get((operation['id'], pointer))
            edge = _edge(source, operation['id'], pointer, ref,
                         'connection' if authored else 'base', authored[1]['id'] if authored else None,
                         '/connections/' + str(authored[0]) if authored else '/workflow/operations/' + str(index) + '/document' + _authored_pointer(body['operations'][index]['document'], pointer))
            edges.append(edge)
        for pointer, ref in _references(effective['operations'][index]['document']):
            if '$document' in ref and 'operation' in ref:
                edges.append(_edge(ref['operation'], operation['id'], pointer, ref,
                                   source_pointer='/workflow/operations/' + str(index) + '/document' + pointer))
    if len(edges) > 4096:
        fail('RESOURCE_LIMIT', 'design has more than 4096 projected references; split the design')
    groups = _components(list(by_id), edges)
    loops = []
    shared = {key: body[key] for key in body if key != 'operations'}
    for members in groups:
        internal = [edge for edge in edges if edge['feedbackEligible'] and edge['source'] in members and edge['target'] in members]
        semantics = sorted((_semantic(edge) for edge in internal), key=storage.encoded)
        fingerprint = {'members': members, 'edges': semantics,
                       'operations': [by_id[member] for member in members], 'shared': shared}
        identity = 'loop-' + storage.digest(fingerprint)[:24]
        configuration = controllers.get(identity)
        if configuration is not None:
            configuration = controls.validate_config(configuration, '$.controllers.' + identity)
        elif identity in controllers:
            fail('INVALID_FEEDBACK_CONTROLLER', 'remove an empty controller or configure the current loop', '$.controllers.' + identity)
        loops.append({'id': identity, 'members': members, 'nodes': members.copy(),
                      'edgeIds': [edge['id'] for edge in internal], 'status': 'configured' if configuration else 'unconfigured',
                      'controller': configuration, 'config': copy.deepcopy(configuration), 'executionAvailable': False})
    stale = sorted(set(controllers) - {loop['id'] for loop in loops})
    if stale and check_controllers:
        fail('INVALID_FEEDBACK_CONTROLLER', 'controller no longer matches a current loop; remove it and configure the changed loop',
             '$.controllers', stale=stale)
    return body, inputs, edges, loops, effective


_V2_KEYS = ('version', 'workflow', 'ports', 'connections', 'controllers', 'parameters', 'outputs', 'naming', 'layout')
_PORT_NAME = r'[A-Za-z][A-Za-z0-9_-]*'
_FORMAT_NAME = r'[A-Za-z0-9][A-Za-z0-9_.+-]*'
_MAX_PORTS = 4096
_LAYOUT_MEANING = 'presentation only; excluded from loop identity and the template digest; no execution implied'


def _text(value, location, code):
    if not isinstance(value, str) or not value.strip():
        fail(code, 'expected a nonempty string', location)


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _data(value, location):
    keys(value, ('kind', 'formats', 'units', 'layout', 'streaming', 'contiguous'), location)
    if 'kind' in value and value['kind'] not in DATA_KINDS:
        fail('INVALID_PORT', 'data kind must be one of ' + ', '.join(DATA_KINDS), location + '.kind')
    if 'formats' in value:
        formats = value['formats']
        valid = (isinstance(formats, list) and 0 < len(formats) <= 64
                 and all(isinstance(item, str) and re.fullmatch(_FORMAT_NAME, item) for item in formats)
                 and len(set(formats)) == len(formats))
        if not valid:
            fail('INVALID_PORT', 'formats must be a nonempty list of unique format names such as step or vtu',
                 location + '.formats')
    if 'units' in value:
        _text(value['units'], location + '.units', 'INVALID_PORT')
    if 'layout' in value and value['layout'] not in ('interleaved', 'planar'):
        fail('INVALID_PORT', 'data layout must be interleaved or planar', location + '.layout')
    for flag in ('streaming', 'contiguous'):
        if flag in value and type(value[flag]) is not bool:
            fail('INVALID_PORT', flag + ' must be a boolean', location + '.' + flag)


def _port_common(port, spec, location):
    if not isinstance(port, str) or not re.fullmatch(_PORT_NAME, port) or len(port) > 64:
        fail('INVALID_PORT', 'port names start with a letter and contain letters, digits, _ or -', location)
    if spec.get('kind') not in ('value', 'artifact'):
        fail('INVALID_PORT', 'port kind must be value or artifact', location + '.kind')
    if 'label' in spec:
        _text(spec['label'], location + '.label', 'INVALID_PORT')
    if 'generated' in spec and spec['generated'] is not True:
        fail('INVALID_PORT', 'generated is either true or absent', location + '.generated')
    if 'data' in spec:
        _data(spec['data'], location + '.data')


def _ports(document, by_id, inputs):
    """Validate the named interface of each operation instance."""
    ports = document.get('ports')
    if not isinstance(ports, dict):
        fail('INVALID_PORT', 'ports must be an object keyed by operation ID', '$.ports')
    count = 0
    for operation, entry in ports.items():
        location = '$.ports.' + str(operation)
        if operation not in by_id:
            fail('INVALID_PORT', 'ports must belong to an existing operation', location)
        keys(entry, ('inputs', 'outputs'), location)
        for side in ('inputs', 'outputs'):
            if not isinstance(entry.get(side, {}), dict):
                fail('INVALID_PORT', side + ' must be an object keyed by port name', location + '.' + side)
        available = {item['pointer']: item['kind'] for item in inputs if item['operation'] == operation}
        targets = []
        for port, spec in entry.get('inputs', {}).items():
            here = location + '.inputs.' + port
            keys(spec, ('target', 'kind', 'data', 'label', 'generated'), here)
            _port_common(port, spec, here)
            target = spec.get('target')
            if not isinstance(target, str):
                fail('INVALID_PORT', 'input port target must be a JSON pointer', here + '.target')
            parts = _parts(target, here + '.target')
            if target not in available:
                fail('INVALID_PORT', 'input port must target an existing numeric or file input of its operation',
                     here + '.target', available=sorted(available))
            if available[target] != spec['kind']:
                fail('INVALID_PORT', 'input port kind differs from its target input', here + '.kind',
                     expected=available[target])
            if any(parts[:len(other)] == other or other[:len(parts)] == parts for other in targets):
                fail('INVALID_PORT', 'input ports of one operation must not target the same or nested inputs',
                     here + '.target')
            targets.append(parts)
        for port, spec in entry.get('outputs', {}).items():
            here = location + '.outputs.' + port
            keys(spec, ('artifact', 'kind', 'valuePath', 'data', 'label', 'generated'), here)
            _port_common(port, spec, here)
            if type(spec.get('artifact')) is not int or spec['artifact'] < 0:
                fail('INVALID_PORT', 'output port artifact must be a nonnegative producer artifact index',
                     here + '.artifact')
            if spec['kind'] == 'value':
                if not isinstance(spec.get('valuePath'), str):
                    fail('INVALID_PORT', 'value output ports need valuePath within the producer artifact',
                         here + '.valuePath')
                _parts(spec['valuePath'], here + '.valuePath')
            elif 'valuePath' in spec:
                fail('INVALID_PORT', 'artifact output ports do not use valuePath', here + '.valuePath')
        count += len(entry.get('inputs', {})) + len(entry.get('outputs', {}))
    if count > _MAX_PORTS:
        fail('RESOURCE_LIMIT', 'design declares more than 4096 ports; split the design', '$.ports')
    return ports


def _port_connection(value, ports, by_id, used, location):
    """Translate one port-to-port arrow into exactly one version 1 connection."""
    keys(value, ('id', 'from', 'to'), location)
    name(value.get('id'), location + '.id')
    ends = {}
    for field, side in (('from', 'outputs'), ('to', 'inputs')):
        here = location + '.' + field
        end = value.get(field)
        keys(end, ('operation', 'port'), here)
        operation = end.get('operation')
        if not isinstance(operation, str) or operation not in by_id:
            fail('INVALID_CONNECTION', 'choose an existing operation', here + '.operation')
        declared = ports.get(operation, {}).get(side, {})
        if not isinstance(end.get('port'), str) or end['port'] not in declared:
            fail('INVALID_CONNECTION', 'choose a declared ' + side[:-1] + ' port of ' + operation, here + '.port',
                 available=sorted(declared))
        ends[field] = declared[end['port']]
    source, target = ends['from'], ends['to']
    if source['kind'] != target['kind']:
        fail('INVALID_CONNECTION', 'connect a ' + target['kind'] + ' output port to this ' + target['kind']
             + ' input port', location, source=source['kind'], target=target['kind'])
    endpoint = (value['to']['operation'], value['to']['port'])
    if endpoint in used:
        fail('INVALID_CONNECTION', 'an input port accepts one connection; add another input port for fan-in',
             location + '.to')
    used.add(endpoint)
    compiled = {'id': value['id'], 'source': value['from']['operation'], 'target': value['to']['operation'],
                'targetPointer': target['target'], 'kind': target['kind'], 'artifactIndex': source['artifact']}
    if source['kind'] == 'value':
        compiled['valuePath'] = source['valuePath']
    return compiled


def _warnings(connections, ports):
    """Descriptive data mismatches are hints; the native planner stays authoritative."""
    result = []
    for index, connection in enumerate(connections):
        source = ports[connection['from']['operation']]['outputs'][connection['from']['port']].get('data', {})
        target = ports[connection['to']['operation']]['inputs'][connection['to']['port']].get('data', {})
        location = '$.connections/' + str(index)
        checks = (('kind', 'DATA_KIND_MISMATCH', 'connected ports declare different data kinds'),
                  ('units', 'DATA_UNITS_MISMATCH', 'connected ports declare different units'),
                  ('layout', 'DATA_LAYOUT_MISMATCH', 'connected ports declare different component layouts'))
        for field, code, message in checks:
            if field in source and field in target and source[field] != target[field]:
                result.append({'code': code, 'message': message, 'location': location,
                               'connection': connection['id'], 'from': source[field], 'to': target[field]})
        if 'formats' in source and 'formats' in target and not set(source['formats']) & set(target['formats']):
            result.append({'code': 'DATA_FORMAT_MISMATCH', 'message': 'connected ports share no declared format',
                           'location': location, 'connection': connection['id'],
                           'from': source['formats'], 'to': target['formats']})
    return result


def _template_parts(document, body):
    """Parameters and named outputs use the template contract unchanged."""
    parameters = document.get('parameters', {})
    outputs = document.get('outputs', {})
    if not isinstance(parameters, dict):
        fail('INVALID_TEMPLATE', 'parameters must be an object keyed by parameter ID', '$.parameters')
    if not isinstance(outputs, dict):
        fail('INVALID_TEMPLATE', 'outputs must be an object keyed by output alias', '$.outputs')
    if not parameters and not outputs:
        return
    manifest = {'version': workflow_templates.TEMPLATE_VERSION, 'id': 'design', 'revision': 1, 'title': 'Design',
                'workflow': 'workflow.json', 'parameters': parameters, 'outputs': outputs}
    try:
        workflow_templates._validate(manifest, body, allow_unfilled=True)
    except SchemaxisError as error:
        fault = error.fault
        location = fault.location.replace('$.template.', '$.', 1)
        fail(fault.code, fault.message, location, **dict(fault.to_dict()['observed']))


def _naming(value):
    keys(value, ('pattern', 'indexWidth'), '$.naming')
    if 'pattern' in value:
        output_naming.validate_pattern(value['pattern'], '$.naming.pattern')
    if 'indexWidth' in value:
        output_naming.validate_width(value['indexWidth'], '$.naming.indexWidth')


def _layout(value, by_id):
    keys(value, ('nodes', 'viewport'), '$.layout')
    nodes = value.get('nodes', {})
    if not isinstance(nodes, dict):
        fail('INVALID_LAYOUT', 'layout nodes must be an object keyed by operation ID', '$.layout.nodes')
    for operation, point in nodes.items():
        location = '$.layout.nodes.' + str(operation)
        if operation not in by_id:
            fail('INVALID_LAYOUT', 'layout positions must belong to existing operations', location)
        keys(point, ('x', 'y'), location)
        for axis in ('x', 'y'):
            if not _finite(point.get(axis)) or abs(point[axis]) > 1e7:
                fail('INVALID_LAYOUT', 'positions need finite x and y coordinates', location + '.' + axis)
    if 'viewport' in value:
        viewport = value['viewport']
        keys(viewport, ('x', 'y', 'zoom'), '$.layout.viewport')
        for axis in ('x', 'y'):
            if not _finite(viewport.get(axis)) or abs(viewport[axis]) > 1e7:
                fail('INVALID_LAYOUT', 'viewport needs finite x and y', '$.layout.viewport.' + axis)
        if not _finite(viewport.get('zoom')) or not 0.01 <= viewport['zoom'] <= 100:
            fail('INVALID_LAYOUT', 'viewport zoom must be from 0.01 to 100', '$.layout.viewport.zoom')


def _state_v2(document, *, check_controllers=True):
    body, resolved, inputs, by_id = _prepare(document, _V2_KEYS, VERSION_2)
    ports = _ports(document, by_id, inputs)
    connections = _connection_list(document)
    used, compiled = set(), []
    for index, connection in enumerate(connections):
        compiled.append(_port_connection(connection, ports, by_id, used, '$.connections/' + str(index)))
    state = _wire(document, body, resolved, inputs, by_id, compiled, check_controllers=check_controllers)
    _template_parts(document, body)
    if 'naming' in document:
        _naming(document['naming'])
    if 'layout' in document:
        _layout(document['layout'], by_id)
    return state, {'ports': ports, 'compiled': compiled, 'warnings': _warnings(connections, ports)}


def create(workflow=None):
    """Capture an ordinary workflow as an independent editable version 2 design."""
    _json(EMPTY if workflow is None else workflow)
    document = {'version': VERSION_2, 'workflow': copy.deepcopy(EMPTY if workflow is None else workflow),
                'ports': {}, 'connections': [], 'controllers': {},
                'parameters': {}, 'outputs': {}, 'naming': {}, 'layout': {'nodes': {}}}
    validate(document)
    return document


def _projection(document, state):
    body, inputs, edges, loops, _ = state
    nodes = []
    resolved = workflow_inputs(body, defer_unfilled=True)
    for index, operation in enumerate(resolved['operations']):
        provider, _ = registry.resolve(operation['document'], legacy=True)
        nodes.append({'id': operation['id'], 'provider': provider, 'order': index,
                      'pointer': '/workflow/operations/' + str(index),
                      'documentVersion': operation['document'].get('version', 'legacy'),
                      'nodeCount': len(operation['document'].get('nodes', [])),
                      'inputs': [{key: value for key, value in item.items() if key != 'operation'}
                                 for item in inputs if item['operation'] == operation['id']]})
    status = ('empty' if not nodes else 'feedback-configuration-required' if any(loop['status'] == 'unconfigured' for loop in loops)
              else 'feedback-execution-unavailable' if loops else 'ready')
    return {'version': 'schemaxis.workflow.graph/1', 'design': True, 'designVersion': document['version'],
            'sourceDigest': storage.digest(document),
            'nodes': nodes, 'edges': edges, 'loops': loops, 'inputTargets': inputs,
            'algorithms': controls.catalogue(), 'status': status, 'compilationAvailable': bool(nodes) and not loops,
            'executionAvailable': False,
            'executionMode': 'design', 'orderMeaning': 'Runtime data arrows determine dependency order; declared operation order breaks ties. Authored document references do not create numerical feedback.',
            'verification': 'Host design only; producer artifact types, values and receipts require validation at execution. Native feedback execution is unavailable.',
            'layout': 'presentation only; no execution implied'}


def _projection_v2(document, state, extra):
    result = _projection(document, state)
    ports = extra['ports']
    connected = {}
    for connection in document['connections']:
        source, target = connection['from'], connection['to']
        connected.setdefault((source['operation'], 'outputs', source['port']), []).append(connection['id'])
        connected.setdefault((target['operation'], 'inputs', target['port']), []).append(connection['id'])
    layout = document.get('layout', {})
    positions = layout.get('nodes', {})
    for node in result['nodes']:
        entry = ports.get(node['id'], {})
        node['ports'] = {}
        for side in ('inputs', 'outputs'):
            node['ports'][side] = [{'name': port, **copy.deepcopy(spec),
                                    'connections': connected.get((node['id'], side, port), [])}
                                   for port, spec in entry.get(side, {}).items()]
        node['position'] = copy.deepcopy(positions.get(node['id']))
    authored = {connection['id']: connection for connection in document['connections']}
    for edge in result['edges']:
        connection = authored.get(edge['id']) if edge['origin'] == 'connection' else None
        if connection:
            edge['from'] = copy.deepcopy(connection['from'])
            edge['to'] = copy.deepcopy(connection['to'])
            source = ports[connection['from']['operation']]['outputs'][connection['from']['port']]
            target = ports[connection['to']['operation']]['inputs'][connection['to']['port']]
            edge['dataKind'] = source.get('data', {}).get('kind', target.get('data', {}).get('kind'))
        else:
            edge['from'] = {'operation': edge['source'], 'port': None}
            edge['to'] = {'operation': edge['target'], 'port': None}
            edge['dataKind'] = None
    result.update(ports=copy.deepcopy(ports), connections=copy.deepcopy(document['connections']),
                  warnings=extra['warnings'], parameters=copy.deepcopy(document.get('parameters', {})),
                  outputs=copy.deepcopy(document.get('outputs', {})), naming=copy.deepcopy(document.get('naming', {})),
                  layout={'nodes': copy.deepcopy(positions), 'viewport': copy.deepcopy(layout.get('viewport'))},
                  layoutMeaning=_LAYOUT_MEANING)
    return result


def validate(document, *, draft=True):
    """Validate a savable design, allowing explicitly unconfigured feedback loops."""
    if type(draft) is not bool:
        fail('INVALID_DOCUMENT', 'draft must be a boolean')
    if not draft:
        return workflow.inspect_plan(compile(document))
    if isinstance(document, dict) and document.get('version') == VERSION_2:
        state, extra = _state_v2(document)
        result = _projection_v2(document, state, extra)
    else:
        result = _projection(document, _state(document))
    unfilled = find_unfilled(document)
    if unfilled:
        result.update(status='unfilled', unfilled=unfilled, compilationAvailable=False)
        allowed = {'/workflow' + spec['target']['pointer'] for spec in document.get('parameters', {}).values()}
        result['templateExportAvailable'] = bool(result['nodes']) and not result['loops'] and all(
            item['pointer'] in allowed for item in unfilled)
    else:
        result['templateExportAvailable'] = result['compilationAvailable']
    return result


def project(document):
    """Return a fresh graph derived from the exact persisted design."""
    return validate(document)


def _tidy(document):
    """Drop generated ports without connections, and empty port groups."""
    used = set()
    for connection in document['connections']:
        if isinstance(connection, dict):
            for field, side in (('from', 'outputs'), ('to', 'inputs')):
                end = connection.get(field)
                if isinstance(end, dict):
                    used.add((end.get('operation'), side, end.get('port')))
    for operation in list(document['ports']):
        entry = document['ports'][operation]
        if not isinstance(entry, dict):
            continue
        for side in ('inputs', 'outputs'):
            group = entry.get(side)
            if not isinstance(group, dict):
                continue
            for port in list(group):
                spec = group[port]
                if isinstance(spec, dict) and spec.get('generated') is True and (operation, side, port) not in used:
                    del group[port]
            if not group:
                del entry[side]
        if not entry:
            del document['ports'][operation]


def _prune(document):
    if document.get('version') == VERSION_2:
        _tidy(document)
    state = _state(document, check_controllers=False)
    current = {loop['id'] for loop in state[3]}
    document['controllers'] = {key: value for key, value in document['controllers'].items() if key in current}
    validate(document)
    return document


def _fresh(existing, base):
    if base not in existing:
        return base
    number = 2
    while base + '-' + str(number) in existing:
        number += 1
    return base + '-' + str(number)


def _input_port_name(pointer):
    for part in reversed(_parts(pointer, pointer)):
        if re.fullmatch(_PORT_NAME, part) and len(part) <= 48:
            return part
    return 'input'


def _adopt(document, connection, location, prepared=None):
    """Give a version 1 arrow generated ports on both ends of a version 2 design."""
    if prepared is None:
        prepared = _prepare(document, _V2_KEYS, VERSION_2)
    _, _, inputs, by_id = prepared
    _connection(connection, by_id, inputs, location)
    ports = document['ports']
    kind = connection['kind']
    spec = {'artifact': connection['artifactIndex'], 'kind': kind}
    if kind == 'value':
        spec['valuePath'] = connection['valuePath']
    outputs = ports.setdefault(connection['source'], {}).setdefault('outputs', {})
    output = next((port for port, item in outputs.items()
                   if {key: item.get(key) for key in spec} == spec), None)
    if output is None:
        output = _fresh(outputs, kind + str(connection['artifactIndex']))
        outputs[output] = {**spec, 'generated': True}
    inputs_group = ports.setdefault(connection['target'], {}).setdefault('inputs', {})
    pointer = connection['targetPointer']
    target = next((port for port, item in inputs_group.items() if item.get('target') == pointer), None)
    if target is None:
        target = _fresh(inputs_group, _input_port_name(pointer))
        inputs_group[target] = {'target': pointer, 'kind': kind, 'generated': True}
    return {'id': connection['id'], 'from': {'operation': connection['source'], 'port': output},
            'to': {'operation': connection['target'], 'port': target}}


def connect(document, connection):
    """Append one arrow atomically, restoring no state on invalid input.

    Version 2 designs accept port-to-port connections, and also version 1
    connections, which receive generated ports on both ends.
    """
    validate(document)
    _json(connection)
    result = copy.deepcopy(document)
    shaped = isinstance(connection, dict) and ('from' in connection or 'to' in connection)
    if result['version'] == VERSION_2 and not shaped:
        connection = _adopt(result, copy.deepcopy(connection), '$.connection')
    elif result['version'] == VERSION and shaped:
        fail('INVALID_CONNECTION', 'version 1 designs connect source and target inputs; upgrade to use ports',
             '$.connection')
    result['connections'].append(copy.deepcopy(connection))
    return _prune(result)


def disconnect(document, connection_id):
    """Remove an explicit arrow and restore its original authored input."""
    validate(document)
    if not isinstance(connection_id, str) or not any(item['id'] == connection_id for item in document['connections']):
        fail('INVALID_CONNECTION', 'choose an explicit connection ID; baseline references must be edited in source', '$.connections')
    result = copy.deepcopy(document)
    result['connections'] = [item for item in result['connections'] if item['id'] != connection_id]
    return _prune(result)


def configure(document, loop_id, config):
    """Store a validated policy only for a current runtime feedback loop."""
    graph = validate(document)
    if not isinstance(loop_id, str) or loop_id not in {loop['id'] for loop in graph['loops']}:
        fail('INVALID_FEEDBACK_CONTROLLER', 'choose a current closed runtime data loop', '$.controllers')
    result = copy.deepcopy(document)
    result['controllers'][loop_id] = controls.validate_config(config, '$.controllers.' + loop_id)
    validate(result)
    return result


def upgrade(document):
    """Migrate a version 1 design; each connection gains generated port names."""
    validate(document)
    if document['version'] == VERSION_2:
        return copy.deepcopy(document)
    result = {'version': VERSION_2, 'workflow': copy.deepcopy(document['workflow']), 'ports': {},
              'connections': [], 'controllers': copy.deepcopy(document['controllers']),
              'parameters': {}, 'outputs': {}, 'naming': {}, 'layout': {'nodes': {}}}
    prepared = _prepare(result, _V2_KEYS, VERSION_2)
    for index, connection in enumerate(document['connections']):
        adopted = _adopt(result, copy.deepcopy(connection), '$.connections/' + str(index), prepared)
        result['connections'].append(adopted)
    validate(result)
    return result


def _reindex_references(value, positions, path=()):
    """Preserve definition-site references when operation array indices move."""
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reindex_references(item, positions, path + (str(index),))
    elif isinstance(value, dict):
        pointer = value.get('$document')
        operation = len(path) >= 3 and path[0] == 'operations' and path[2] == 'document'
        if isinstance(pointer, str) and 'operation' not in value:
            relative = pointer.startswith(('./', '../'))
            if relative:
                parts = list(path[:-1])
                for token in pointer.split('/'):
                    if token == '.':
                        continue
                    if token == '..':
                        parts.pop()  # The original workflow already validated the path.
                    else:
                        parts.extend(_parts('/' + token, '$document'))
            elif value.get('scope') == 'workflow' or not operation:
                parts = _parts(pointer, '$document')
            else:
                parts = ()  # Absolute operation-local references move with their operation.
            if len(parts) >= 2 and parts[0] == 'operations' and parts[1] in positions:
                if positions[parts[1]] is None:
                    fail('OPERATION_IN_USE', 'a document reference points into the removed operation; edit it first',
                         '$.workflow/' + '/'.join(_escape(part) for part in path))
                value['$document'] = '/operations/' + str(positions[parts[1]]) + ''.join('/' + _escape(part) for part in parts[2:])
                if relative:
                    value['scope'] = 'workflow'
        for key, item in value.items():
            _reindex_references(item, positions, path + (key,))


def compile(document, *, allow_unfilled_parameters=False):
    """Materialise DAG wiring for the existing executor; never dispatch feedback."""
    allowed = []
    if allow_unfilled_parameters:
        # Validate parameter declarations before granting an exact-target exemption.
        _template_parts(document, document.get('workflow'))
        allowed = ['/workflow' + spec['target']['pointer'] for spec in document.get('parameters', {}).values()]
    reject_unfilled(document, allowed=allowed)
    body, _, edges, loops, effective = _state(document)
    if loops:
        fail('FEEDBACK_EXECUTION_UNAVAILABLE', 'feedback designs can be saved and configured; native participants are not yet qualified for loop execution',
             '$.connections', loops=[loop['id'] for loop in loops], unconfigured=[loop['id'] for loop in loops if loop['status'] == 'unconfigured'])
    if not body['operations']:
        fail('EMPTY_WORKFLOW', 'add operations before planning this design', '$.workflow.operations')
    order = [operation['id'] for operation in workflow_inputs(body, defer_unfilled=True)['operations']]
    parents = {identity: set() for identity in order}
    for edge in edges:
        if edge['feedbackEligible']:
            parents[edge['target']].add(edge['source'])
    arranged, remaining = [], order.copy()
    while remaining:
        ready = next((identity for identity in remaining if not parents[identity] - set(arranged)), None)
        if ready is None:
            fail('FEEDBACK_EXECUTION_UNAVAILABLE', 'runtime dependencies contain a feedback loop', '$.connections')
        arranged.append(ready)
        remaining.remove(ready)
    positions = {str(index): arranged.index(identity) for index, identity in enumerate(order)}
    result = copy.deepcopy(effective)
    by_id = dict(zip(order, result['operations']))
    if arranged != order:
        _reindex_references(result, positions)
    result['operations'] = [by_id[identity] for identity in arranged]
    if not find_unfilled(result):
        workflow.inspect_plan(result)
    return result


# Version 2 editing. Every function returns a new validated document and never
# mutates its input. Faults leave the caller's document unchanged.

def _require_v2(document):
    if not isinstance(document, dict) or document.get('version') != VERSION_2:
        fail('UNSUPPORTED_VERSION', 'this edit needs a ' + VERSION_2 + ' design; upgrade the version 1 design first',
             '$.version')
    validate(document)


def _operation_index(document, operation, location):
    resolved = workflow_inputs(document['workflow'], defer_unfilled=True)
    for index, item in enumerate(resolved['operations']):
        if item['id'] == operation:
            return index
    fail('UNKNOWN_OPERATION', 'choose an existing operation', location, operation=str(operation))


def _plain_identity(document, index, location):
    if not isinstance(document['workflow']['operations'][index].get('id'), str):
        fail('UNSUPPORTED_EDIT', 'this operation identity is an alias; edit it at its definition in source', location)


def _new_identity(document, identity, location):
    name(identity, location)
    if any(item['id'] == identity for item in workflow_inputs(document['workflow'], defer_unfilled=True)['operations']):
        fail('DUPLICATE_OPERATION', 'operation identity is already used', location, operation=identity)


def _point(value, location):
    if not isinstance(value, dict):
        fail('INVALID_LAYOUT', 'a position is an object with x and y', location)
    return copy.deepcopy(value)


def add_operation(document, operation_id, operation_document, *, position=None):
    """Append one adaptor instance; it gains ports only when they are declared."""
    _require_v2(document)
    _new_identity(document, operation_id, '$.id')
    if not isinstance(operation_document, dict):
        fail('INVALID_DOCUMENT', 'operation document must be an object', '$.document')
    _json(operation_document)
    result = copy.deepcopy(document)
    result['workflow']['operations'].append({'id': operation_id, 'document': copy.deepcopy(operation_document)})
    if position is not None:
        result.setdefault('layout', {}).setdefault('nodes', {})[operation_id] = _point(position, '$.position')
    return _prune(result)


def _references_to(value, operation, path=''):
    """Runtime and document references naming one operation identity."""
    for pointer, ref in _references(value, path):
        if ref.get('$artifact') == operation or output_reference(ref) and ref.get('$value') == operation:
            yield pointer
        elif '$document' in ref and ref.get('operation') == operation:
            yield pointer


def _workflow_pointers(document):
    """Absolute workflow-scoped document pointers used inside one document."""
    for _, value in _walk(document):
        if isinstance(value, dict) and isinstance(value.get('$document'), str) and value.get('scope') == 'workflow':
            if 'operation' not in value and value['$document'].startswith('/'):
                yield _parts(value['$document'], '$document')


def _exclusive_parameters(document, index):
    """Parameters whose workflow targets only this operation consumes."""
    operations = document['workflow']['operations']
    used = {position: list(_workflow_pointers(operation['document'])) for position, operation in enumerate(operations)}
    result = []
    for identity, spec in document.get('parameters', {}).items():
        target = _parts(spec['target']['pointer'], '$.parameters.' + identity)

        def consumes(position):
            return any(other[:len(target)] == target or target[:len(other)] == other for other in used[position])
        if consumes(index) and not any(consumes(position) for position in used if position != index):
            result.append(identity)
    return result


def remove_operation(document, operation_id, *, cascade=False):
    """Remove an instance with its ports, arrows and position.

    Parameters consumed only by this operation and named outputs of it block
    removal unless ``cascade`` also removes them.
    """
    _require_v2(document)
    if type(cascade) is not bool:
        fail('INVALID_REQUEST', 'cascade must be a boolean', '$.cascade')
    index = _operation_index(document, operation_id, '$.operation')
    _plain_identity(document, index, '$.operation')
    body = document['workflow']
    for position, operation in enumerate(body['operations']):
        if position == index:
            continue
        prefix = '$.workflow.operations/' + str(position) + '/document'
        for pointer in _references_to(operation['document'], operation_id):
            fail('OPERATION_IN_USE', 'another operation still refers to this operation; rewire it first',
                 prefix + pointer)
    for key in ('dimensions', 'definitions', 'settings'):
        for pointer in _references_to(body.get(key), operation_id):
            fail('OPERATION_IN_USE', 'workflow metadata still refers to this operation', '$.workflow.' + key + pointer)
    parameters = _exclusive_parameters(document, index)
    aliases = [alias for alias, item in document.get('outputs', {}).items() if item.get('operation') == operation_id]
    if (parameters or aliases) and not cascade:
        fail('OPERATION_IN_USE', 'parameters or named outputs depend on this operation; remove them or use cascade',
             '$.parameters' if parameters else '$.outputs', parameters=parameters, outputs=aliases)
    result = copy.deepcopy(document)
    for identity in parameters:
        del result['parameters'][identity]
    for alias in aliases:
        del result['outputs'][alias]
    operations = result['workflow']['operations']
    removed = operations[index]
    operations[index] = {}  # Its own internal references leave with it.
    positions = {str(position): None if position == index else position - (position > index)
                 for position in range(len(operations))}
    _reindex_references(result['workflow'], positions)
    operations[index] = removed
    del operations[index]
    result['connections'] = [item for item in result['connections']
                             if operation_id not in (item['from']['operation'], item['to']['operation'])]
    result['ports'].pop(operation_id, None)
    result.get('layout', {}).get('nodes', {}).pop(operation_id, None)
    return _prune(result)


def _rename_references(value, old, new):
    if isinstance(value, list):
        for item in value:
            _rename_references(item, old, new)
    elif isinstance(value, dict):
        if value.get('$artifact') == old:
            value['$artifact'] = new
        if output_reference(value) and value.get('$value') == old:
            value['$value'] = new
        if '$document' in value and value.get('operation') == old:
            value['operation'] = new
        for item in value.values():
            _rename_references(item, old, new)


def _renamed(mapping, old, new):
    return {new if key == old else key: value for key, value in mapping.items()}


def rename_operation(document, old_id, new_id):
    """Rename an instance everywhere it is named, keeping configured loop settings."""
    _require_v2(document)
    index = _operation_index(document, old_id, '$.operation')
    _plain_identity(document, index, '$.operation')
    _new_identity(document, new_id, '$.newId')
    before = {tuple(loop['members']): loop['controller'] for loop in project(document)['loops'] if loop['controller']}
    result = copy.deepcopy(document)
    result['workflow']['operations'][index]['id'] = new_id
    _rename_references(result['workflow'], old_id, new_id)
    for connection in result['connections']:
        for field in ('from', 'to'):
            if connection[field]['operation'] == old_id:
                connection[field]['operation'] = new_id
    result['ports'] = _renamed(result['ports'], old_id, new_id)
    layout = result.get('layout', {})
    if 'nodes' in layout:
        layout['nodes'] = _renamed(layout['nodes'], old_id, new_id)
    for item in result.get('outputs', {}).values():
        if item.get('operation') == old_id:
            item['operation'] = new_id
    result['controllers'] = {}
    for loop in _state(result, check_controllers=False)[3]:
        members = tuple(sorted(old_id if member == new_id else member for member in loop['members']))
        if members in before:
            result['controllers'][loop['id']] = copy.deepcopy(before[members])
    validate(result)
    return result


def duplicate_operation(document, operation_id, new_id):
    """Copy an instance with its ports and incoming arrows (fan-out from producers)."""
    _require_v2(document)
    index = _operation_index(document, operation_id, '$.operation')
    _new_identity(document, new_id, '$.newId')
    scratch = copy.deepcopy(document['workflow'])
    # Relative references to other operations become absolute before moving.
    _reindex_references(scratch, {str(position): position for position in range(len(scratch['operations']))})
    duplicate = scratch['operations'][index]
    duplicate['id'] = new_id
    result = copy.deepcopy(document)
    result['workflow']['operations'].append(duplicate)
    if operation_id in result['ports']:
        result['ports'][new_id] = copy.deepcopy(result['ports'][operation_id])
    nodes = result.get('layout', {}).get('nodes', {})
    if operation_id in nodes:
        nodes[new_id] = {'x': nodes[operation_id]['x'] + 40, 'y': nodes[operation_id]['y'] + 40}
    identities = {item['id'] for item in result['connections']}
    for connection in document['connections']:
        if connection['to']['operation'] == operation_id:
            copied = copy.deepcopy(connection)
            copied['id'] = _fresh(identities, connection['id'] + '-' + new_id)
            copied['to']['operation'] = new_id
            identities.add(copied['id'])
            result['connections'].append(copied)
    return _prune(result)


def set_ports(document, operation, ports):
    """Replace one instance's port interface; arrows must still name its ports."""
    _require_v2(document)
    _operation_index(document, operation, '$.operation')
    _json(ports)
    result = copy.deepcopy(document)
    result['ports'][operation] = copy.deepcopy(ports)
    return _prune(result)


def move(document, positions, viewport=None):
    """Presentation-only layout edit; loop identity and template digest are unaffected."""
    _require_v2(document)
    if not isinstance(positions, dict):
        fail('INVALID_LAYOUT', 'positions must be an object keyed by operation ID', '$.positions')
    _json(positions)
    result = copy.deepcopy(document)
    layout = result.setdefault('layout', {})
    nodes = layout.setdefault('nodes', {})
    for operation, point in positions.items():
        nodes[operation] = _point(point, '$.positions.' + str(operation))
    if viewport is not None:
        _json(viewport)
        layout['viewport'] = copy.deepcopy(viewport)
    validate(result)
    return result


def _infer_kind(value):
    if type(value) is bool:
        return 'boolean'
    if type(value) in (int, float):
        return 'number'
    if isinstance(value, str):
        return 'string'
    return 'vector'


def expose_parameter(document, operation, pointer, parameter_id, spec=None):
    """Move one operation literal to workflow metadata and declare it a parameter.

    The literal at the operation-local ``pointer`` moves to ``/settings/<id>``
    (or ``/dimensions/<id>`` with ``group: "dimensions"``) and is replaced by a
    workflow-scoped ``$document`` reference, as one edit.
    """
    _require_v2(document)
    spec = {} if spec is None else spec
    keys(spec, ('label', 'help', 'kind', 'constraints', 'default', 'units', 'group'), '$.spec')
    _json(spec)
    group = spec.get('group', 'settings')
    if group not in ('settings', 'dimensions'):
        fail('INVALID_PARAMETER', 'group must be settings or dimensions', '$.spec.group')
    if not isinstance(parameter_id, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]*', parameter_id):
        fail('INVALID_PARAMETER', 'parameter IDs start with a letter and contain letters, digits, _, . or -',
             '$.parameterId')
    if parameter_id in document.get('parameters', {}):
        fail('DUPLICATE_PARAMETER', 'parameter is already declared', '$.parameterId')
    container = document['workflow'].get(group, {})
    if not isinstance(container, dict) or parameter_id in container:
        fail('DUPLICATE_PARAMETER', 'workflow ' + group + ' already defines this name, or is not an object',
             '$.workflow.' + group)
    index = _operation_index(document, operation, '$.operation')
    parts = _parts(pointer, '$.pointer') if isinstance(pointer, str) else None
    if not parts:
        fail('INVALID_PARAMETER', 'choose an operation-local JSON pointer to a literal value', '$.pointer')
    parent = document['workflow']['operations'][index]['document']
    try:
        for part in parts[:-1]:
            parent = parent[_member(parent, part, '$.pointer')]
        key = _member(parent, parts[-1], '$.pointer')
    except SchemaxisError:
        fail('INVALID_PARAMETER', 'the pointer does not name an authored value of this operation', '$.pointer')
    value = parent[key]
    numbers = isinstance(value, list) and value and all(type(item) in (int, float) for item in value)
    if not (type(value) in (bool, int, float, str) or numbers):
        fail('INVALID_PARAMETER', 'only literal numbers, booleans, strings and numeric vectors can be exposed',
             '$.pointer')
    for connection in document['connections']:
        if connection['to']['operation'] == operation:
            target = _parts(document['ports'][operation]['inputs'][connection['to']['port']]['target'], '$')
            if target[:len(parts)] == parts or parts[:len(target)] == target:
                fail('INVALID_PARAMETER', 'a connection drives this input; disconnect it before exposing it',
                     '$.pointer', connection=connection['id'])
    kind = spec.get('kind', _infer_kind(value))
    entry = {'label': spec.get('label', parameter_id), 'kind': kind}
    for field in ('help', 'units', 'default'):
        if field in spec:
            entry[field] = copy.deepcopy(spec[field])
    constraints = copy.deepcopy(spec.get('constraints', {}))
    if kind == 'vector' and isinstance(value, list):
        constraints.setdefault('length', len(value))
    if constraints:
        entry['constraints'] = constraints
    entry['target'] = {'scope': 'workflow', 'pointer': '/' + group + '/' + parameter_id}
    result = copy.deepcopy(document)
    result['workflow'].setdefault(group, {})[parameter_id] = copy.deepcopy(value)
    _replace(result['workflow']['operations'][index]['document'], parts,
             {'$document': '/' + group + '/' + parameter_id, 'scope': 'workflow'}, '$.pointer')
    result.setdefault('parameters', {})[parameter_id] = entry
    return _prune(result)


def _replace_field(document, field, value):
    _require_v2(document)
    _json(value)
    result = copy.deepcopy(document)
    result[field] = copy.deepcopy(value)
    validate(result)
    return result


def set_parameters(document, parameters):
    """Replace template parameters; targets must already exist in workflow metadata."""
    return _replace_field(document, 'parameters', parameters)


def set_outputs(document, outputs):
    """Replace named output aliases; each names an existing operation and artifact."""
    return _replace_field(document, 'outputs', outputs)


def set_naming(document, naming):
    """Replace the output naming pattern and index width."""
    return _replace_field(document, 'naming', naming)


# Artifact kinds from adaptor routes, mapped to descriptive port data kinds.
# Unlisted kinds are reported as unknown rather than guessed.
_ARTIFACT_DATA_KINDS = {'table': 'table', 'image': 'image', 'video': 'video', 'geometry': 'geometry',
                        'gltf': 'geometry', 'cad': 'geometry', 'mesh': 'geometry', 'text': 'text',
                        'audio': 'audio', 'archive': 'archive', 'spriteSheet': 'image'}


def _declared_outputs(document):
    if isinstance(document.get('outputs'), list):
        return [item for item in document['outputs'] if isinstance(item, str)]
    if isinstance(document.get('output'), str):
        return [document['output']]
    return []


def suggest_ports(document, operation):
    """Candidate ports from host-knowable declarations; never native inspection.

    Inputs are exact: they are the runtime inputs a port may target. Outputs
    are best effort: an artifact index assumes one publication per declared
    output in declaration order, which only the producer receipt confirms.
    """
    projection = validate(document)
    node = next((item for item in projection['nodes'] if item['id'] == operation), None)
    if node is None:
        fail('UNKNOWN_OPERATION', 'choose an existing operation', '$.operation', operation=str(operation))
    resolved = workflow_inputs(document['workflow'])['operations'][node['order']]['document']
    provider, route = registry.resolve(resolved, legacy=True)
    accepted = list(route.get('acceptedArtifacts', []))
    accepted_kinds = sorted({_ARTIFACT_DATA_KINDS[item] for item in accepted if item in _ARTIFACT_DATA_KINDS})
    ports = document.get('ports', {}).get(operation, {}) if document['version'] == VERSION_2 else {}
    declared = {spec['target']: port for port, spec in ports.get('inputs', {}).items()}
    taken = set(ports.get('inputs', {}))
    inputs = []
    for item in node['inputs']:
        suggestion = declared.get(item['pointer'])
        if suggestion is None:
            suggestion = _fresh(taken, _input_port_name(item['pointer']))
            taken.add(suggestion)
        entry = {'name': suggestion, 'declared': item['pointer'] in declared, 'target': item['pointer'],
                 'kind': item['kind'], 'current': copy.deepcopy(item['value'])}
        if item['kind'] == 'artifact':
            entry['acceptedArtifacts'] = accepted
            entry['dataKinds'] = accepted_kinds
            entry['dataKindKnown'] = bool(accepted_kinds)
        else:
            entry['dataKinds'] = ['number']
            entry['dataKindKnown'] = True
        inputs.append(entry)
    try:
        declarations = registry.declarations(provider)
    except (SchemaxisError, KeyError, ImportError, AttributeError, TypeError):
        declarations = {}
    filters = {item.get('id'): item.get('filter') for item in resolved.get('nodes', []) if isinstance(item, dict)}
    outputs, taken = [], set(ports.get('outputs', {}))
    for index, output in enumerate(_declared_outputs(resolved)):
        declaration = declarations.get(filters.get(output), {}) if isinstance(declarations, dict) else {}
        suggestion = _fresh(taken, output if re.fullmatch(_PORT_NAME, output) else 'artifact' + str(index))
        taken.add(suggestion)
        outputs.append({'name': suggestion, 'artifact': index, 'kind': 'artifact', 'node': output,
                        'filter': filters.get(output), 'nodeKinds': list(declaration.get('kinds', [])),
                        'confidence': 'declared-order'})
    notes = ['Input targets are exact runtime inputs of this operation.',
             'Output artifact indices assume one publication per declared output, in order; '
             'the producer receipt is authoritative.',
             'Value output paths are not knowable before execution; choose valuePath from a verified artifact.']
    if not outputs:
        notes.append('This document declares no ordered outputs; output ports are unknown until a receipt exists.')
    return {'operation': operation, 'provider': provider, 'inputs': inputs, 'outputs': outputs,
            'outputsKnown': bool(outputs), 'notes': notes}


def _pretty(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def _current(body, pointer):
    value = body
    for part in _parts(pointer, pointer):
        value = value[_member(value, part, pointer)]
    return value


def export_template(document, directory, *, template_id, title, revision=1):
    """Compile a design into a template bundle, checking binding when values exist.

    Writes ``template.json``, ``workflow.json`` and ``cases/example.json`` into a
    new or empty directory. Exposed unfinished values produce a draft example
    case that must be filled before binding. Layout never alters the digest.
    """
    if isinstance(document, dict) and document.get('version') == VERSION:
        document = upgrade(document)
    validate(document)
    body = compile(document, allow_unfilled_parameters=True)
    manifest = {'version': workflow_templates.TEMPLATE_VERSION, 'id': template_id, 'revision': revision,
                'title': title, 'workflow': 'workflow.json',
                'parameters': copy.deepcopy(document.get('parameters', {})),
                'outputs': copy.deepcopy(document.get('outputs', {}))}
    workflow_templates._validate(manifest, body)
    digest = storage.digest({'template': manifest, 'workflow': body})
    values = {}
    for identity, spec in manifest['parameters'].items():
        values[identity] = copy.deepcopy(spec['default'] if 'default' in spec
                                         else _current(body, spec['target']['pointer']))
    case = {'version': workflow_templates.VALUES_VERSION,
            'template': {'id': template_id, 'revision': revision, 'digest': digest}, 'values': values}
    if document.get('naming'):
        case['run'] = {'naming': copy.deepcopy(document['naming'])}
    pending_values = find_unfilled(case)
    if not pending_values:
        workflow_templates.bind_values({'template': manifest, 'workflow': body, 'digest': digest}, case)
    target = Path(directory).expanduser().absolute()
    try:
        if target.is_symlink() or target.exists() and (not target.is_dir() or any(target.iterdir())):
            fail('OUTPUT_EXISTS', 'export into a new or empty directory', str(target))
        target.mkdir(parents=True, exist_ok=True)
        paths = {'template': target / 'template.json', 'workflow': target / 'workflow.json',
                 'case': target / 'cases' / 'example.json'}
        for key, value in (('workflow', body), ('template', manifest), ('case', case)):
            storage.atomic(paths[key], _pretty(value), exclusive=True)
    except OSError as error:
        fail('INVALID_OUTPUT_PATH', 'cannot write template bundle: ' + str(error), str(target))
    bundle = workflow_templates.load_template(paths['template'])
    if bundle['digest'] != digest:
        fail('VERIFICATION_FAILED', 'written template differs from the compiled design', str(paths['template']))
    bound = None if pending_values else workflow_templates.bind_values(
        bundle, storage.load(paths['case'].read_text(encoding='utf-8')))
    return {'directory': str(target), 'template': str(paths['template']), 'workflow': str(paths['workflow']),
            'case': str(paths['case']), 'id': template_id, 'revision': revision, 'digest': digest,
            'boundDigest': bound['digest'] if bound else None,
            'requiresValues': [item['pointer'] for item in pending_values]}
