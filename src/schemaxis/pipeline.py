# Copyright (C) 2026 David L F Gaden
"""Complete graph, dependency-pruned active graph and reusable execution state.

The master owns descriptions only. An active pipeline owns backend objects.
Visibility is deliberately not an execution dependency: explicit output roots and
hidden observation dependencies contribute to the same transitive closure.
"""
import copy
import hashlib
import itertools
import json
import math
import re
from schemaxis.core.declarations import validate_arguments, validate_value
from schemaxis.documents import resolve_document
from schemaxis.core.faults import SchemaxisError
from .errors import fail, keys
from .bindings import convert_option, validate_binding, validate_options
from .context import ObjectRegistry, InputContext, compile_objects


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def name(value, location):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', value):
        fail('INVALID_NAME', 'expected a name starting with a letter', location)
    return value


def input_reference(value, location):
    """A selected output port retains its producer's graph identity."""
    if isinstance(value, dict):
        keys(value, ('node', 'port'), location)
        if type(value.get('port')) is not int or value['port'] < 0:
            fail('INVALID_OUTPUT_PORT', 'output port must be a nonnegative integer', location)
        return name(value.get('node'), location + '.node')
    return name(value, location)


def markers(value):
    if isinstance(value, dict):
        if any(k.startswith('$') for k in value):
            yield value
        for item in value.values():
            yield from markers(item)
    elif isinstance(value, list):
        for item in value:
            yield from markers(item)


def lookup(value, path, location):
    for part in path:
        if isinstance(value, dict) and isinstance(part, str) and part in value:
            value = value[part]
        elif isinstance(value, (list, tuple)) and type(part) is int and 0 <= part < len(value):
            value = value[part]
        else:
            fail('INVALID_SELECTION', 'path does not identify a value', location, path=path)
    return copy.deepcopy(value)


def evaluate(value, axes, observations, time, location, sampler=None):
    if isinstance(value, list):
        return [evaluate(v, axes, observations, time, location, sampler) for v in value]
    if not isinstance(value, dict):
        return value
    if '$call' in value:
        from .functions import FUNCTIONS
        arguments = {k: evaluate(v, axes, observations, time, location + '/' + k, sampler)
                     for k, v in value.get('args', {}).items()}
        return FUNCTIONS.invoke(value['$call'], arguments, location)
    if '$axis' in value:
        return lookup(axes[value['$axis']], value.get('path', []), location)
    if '$time' in value:
        return time
    if '$sample' in value:
        if sampler is None:
            fail('OBSERVATION_UNAVAILABLE', 'field sampling requires an updated upstream object', location)
        index = evaluate(value['index'], axes, observations, time, location, sampler)
        return sampler(value['$sample'], value['association'], value['field'], index,
                       value.get('component'), value.get('block', []))
    if '$observe' in value:
        source = value['$observe']
        if source not in observations:
            fail('OBSERVATION_UNAVAILABLE', 'upstream data has not been observed', location, node=source)
        return lookup(observations[source], value.get('path', []), location)
    if '$calc' in value:
        args = [evaluate(v, axes, observations, time, location, sampler) for v in value['args']]
        op = value['$calc']
        try:
            def numeric(v):
                return type(v) in (int, float) and math.isfinite(v)

            def combine(a, b, operation):
                if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
                    return [combine(x, y, operation) for x, y in zip(a, b)]
                if isinstance(a, list) and numeric(b):
                    return [combine(x, b, operation) for x in a]
                if numeric(a) and isinstance(b, list):
                    return [combine(a, x, operation) for x in b]
                if not numeric(a) or not numeric(b):
                    fail('INVALID_EXPRESSION', 'arithmetic requires finite numbers or matching vectors', location)
                return operation(a, b)

            if op == 'vector':
                if not all(numeric(a) for a in args):
                    fail('INVALID_EXPRESSION', 'vector needs three finite scalar components', location)
                result = args
            elif op in ('midpoint', 'boundsMin', 'boundsMax'):
                bounds = args[0]
                if not isinstance(bounds, list) or len(bounds) != 6 or not all(numeric(v) for v in bounds):
                    fail('INVALID_EXPRESSION', 'bounds require six finite components', location)
                if any(bounds[i] > bounds[i+1] for i in (0, 2, 4)):
                    fail('INVALID_BOUNDS', 'cannot use empty bounds in a calculation', location)
                result = ([(bounds[i] + bounds[i + 1]) / 2 for i in (0, 2, 4)] if op == 'midpoint'
                          else [bounds[i] for i in ((0, 2, 4) if op == 'boundsMin' else (1, 3, 5))])
            elif op == 'add':
                result = combine(*args, lambda a, b: a + b)
            elif op == 'subtract':
                result = combine(*args, lambda a, b: a - b)
            elif op == 'multiply':
                result = combine(*args, lambda a, b: a * b)
            elif op == 'divide':
                result = combine(*args, lambda a, b: a / b)
            elif op == 'min':
                result = combine(*args, min)
            elif op == 'max':
                result = combine(*args, max)
            else:
                fail('INVALID_EXPRESSION', 'unsupported calculation', location, operation=op)
            json.dumps(result, allow_nan=False)
            return result
        except (TypeError, ValueError, ZeroDivisionError, IndexError, OverflowError) as error:
            fail('INVALID_EXPRESSION', str(error), location)
    return {k: evaluate(v, axes, observations, time, location, sampler) for k, v in value.items()}


class DefinitionGraph:
    """Validated immutable-by-ownership library; no native objects are created."""

    def __init__(self, document, declarations):
        self.document, self.provenance = resolve_document(copy.deepcopy(document))
        keys(self.document, ('version', 'nodes', 'axes', 'times', 'scenes', 'maxStates',
                             'maxPublications', 'definitions', 'dimensions', 'views', 'settings'), '$')
        if self.document.get('version') != 'schemaxis/1':
            fail('UNSUPPORTED_VERSION', 'expected schemaxis/1', '$.version')
        self.document = compile_objects(self.document)
        self.analytic_bindings = []
        if any('$analytic' in m for m in markers(self.document)):
            from .analytics import compile_analytics
            self.document, self.analytic_bindings = compile_analytics(self.document)
        self.declarations = copy.deepcopy(declarations)
        self.axes = {}
        raw_axes = self.document.get('axes', [])
        if not isinstance(raw_axes, list):
            fail('INVALID_AXIS', 'axes must be an ordered list, fastest first', '$.axes')
        for raw in raw_axes:
            keys(raw, ('name', 'values', 'series'), '$.axes')
            axis = name(raw.get('name'), '$.axes.name')
            if axis in self.axes:
                fail('DUPLICATE_AXIS', 'axis name is not unique', axis)
            values = raw.get('values')
            if 'series' in raw:
                if 'values' in raw:
                    fail('INVALID_AXIS', 'choose values or series, not both', axis)
                from schemaxis.core.series import resolve_series
                values = list(resolve_series(raw['series'], limit=self.document.get('maxStates', 10000)).positions)
            if not isinstance(values, list) or not values:
                fail('EMPTY_AXIS', 'axis values must be a nonempty array', axis)
            self.axes[axis] = copy.deepcopy(values)
        self.times = self.document.get('times', [0.0])
        if isinstance(self.times, dict):
            keys(self.times, ('source', 'select'), '$.times')
            fail('TIME_INSPECTION_REQUIRED', 'run must inspect the named source before resolving this time selection',
                 '$.times', request=self.times)
        if (not isinstance(self.times, list) or not self.times or
                any(type(t) not in (int, float) or not math.isfinite(t) for t in self.times)):
            fail('INVALID_TIME', 'times must be a nonempty array of finite numbers', '$.times')
        self.limit = self.document.get('maxStates', 10000)
        if type(self.limit) is not int or self.limit < 1:
            fail('INVALID_LIMIT', 'maxStates must be a positive integer')
        self.nodes = {}
        raw_nodes = self.document.get('nodes')
        if not isinstance(raw_nodes, list) or not raw_nodes:
            fail('EMPTY_PIPELINE', 'nodes must be a nonempty list', '$.nodes')
        for raw in raw_nodes:
            keys(raw, ('id', 'filter', 'inputs', 'options', 'onVisit'), '$.nodes')
            node_id = name(raw.get('id'), '$.nodes.id')
            if node_id in self.nodes:
                fail('DUPLICATE_NODE', 'node name is not unique', node_id)
            kind = raw.get('filter')
            if not isinstance(kind, str) or kind not in self.declarations:
                fail('UNKNOWN_FILTER', 'filter is not declared', node_id, available=sorted(self.declarations))
            spec = self.declarations[kind]
            commands = raw.get('onVisit', [])
            if not isinstance(commands, list) or any(not isinstance(c,str) or c not in spec.get('commands', {}) for c in commands):
                fail('INVALID_COMMAND', 'onVisit accepts only declared command names', node_id,
                     available=sorted(spec.get('commands', {})))
            if spec.get('role') == 'writer':
                fail('INVALID_OPERATION_ROLE', 'writers belong in scene exports, not pipeline nodes', node_id)
            inputs = copy.deepcopy(raw.get('inputs', {}))
            keys(inputs, spec['inputs'], node_id + '.inputs')
            for port, port_spec in spec['inputs'].items():
                if port not in inputs:
                    if port_spec.get('required'):
                        fail('MISSING_INPUT', 'required input port is missing', node_id + '.' + port)
                    continue
                sources = inputs[port]
                if port_spec.get('multiple'):
                    if not isinstance(sources, list) or not sources:
                        fail('INVALID_INPUT', 'multi-input port needs a nonempty array', node_id + '.' + port)
                else:
                    sources = [sources]
                for source in sources:
                    input_reference(source, node_id + '.' + port)
                    if isinstance(source,dict) and port_spec.get('kind','data') != 'data':
                        fail('INVALID_OUTPUT_PORT', 'typed resources do not have data output ports', node_id + '.' + port)
            options = copy.deepcopy(raw.get('options', {}))
            keys(options, spec['options'], node_id + '.options')
            for key, option in spec['options'].items():
                if key not in options and 'default' in option['value']:
                    options[key] = copy.deepcopy(option['value']['default'])
                if key not in options and option['value'].get('required'):
                    fail('MISSING_ARGUMENT', 'required option is missing', node_id + '.' + key)
                if key in options:
                    dynamic = list(markers(options[key]))
                    if option.get('constructor') and dynamic:
                        fail('DYNAMIC_CONSTRUCTOR', 'constructor arguments must be constant', node_id + '.' + key)
                    self._check_markers(dynamic, node_id + '.' + key)
                    if not dynamic:
                        validate_value(options[key], option['value'], node_id + '.' + key)
            deps = {input_reference(s, node_id) for value in inputs.values()
                    for s in (value if isinstance(value, list) else [value])}
            deps.update(m['$observe'] for m in markers(options) if '$observe' in m)
            deps.update(m['$sample'] for m in markers(options) if '$sample' in m)
            self.nodes[node_id] = {'id': node_id, 'filter': kind, 'inputs': inputs,
                                   'options': options, 'dependencies': sorted(deps)}
            if commands: self.nodes[node_id]['onVisit'] = list(commands)
            if not list(markers(options)):
                validate_options(spec, options, node_id)
        self.order = self._topological_order()
        for node in self.nodes.values():
            for port, sources in node['inputs'].items():
                expected = self.declarations[node['filter']]['inputs'][port].get('kind', 'data')
                for source in sources if isinstance(sources, list) else [sources]:
                    source = input_reference(source, node['id'] + '.' + port)
                    available = self.declarations[self.nodes[source]['filter']].get('kinds', ['data'])
                    if expected not in available and expected != 'object':
                        fail('TYPE_MISMATCH', 'input object kind does not match its port', node['id'] + '.' + port,
                             expected=expected, available=available)
        self._check_static_axes()

    def _check_markers(self, found, location):
        for marker in found:
            if '$call' in marker:
                from .functions import FUNCTIONS
                keys(marker, ('$call', 'args'), location)
                FUNCTIONS.check(marker['$call'], marker.get('args', {}), location)
            elif '$axis' in marker:
                keys(marker, ('$axis', 'path'), location)
                if not isinstance(marker['$axis'], str) or marker['$axis'] not in self.axes:
                    fail('UNKNOWN_AXIS', 'unknown parameter axis', location)
            elif '$observe' in marker:
                keys(marker, ('$observe', 'path'), location)
                name(marker['$observe'], location)
            elif '$time' in marker:
                keys(marker, ('$time',), location)
                if marker['$time'] is not True:
                    fail('INVALID_EXPRESSION', '$time must be true', location)
            elif '$sample' in marker:
                keys(marker, ('$sample', 'association', 'field', 'index', 'component', 'block'), location)
                name(marker['$sample'], location)
                if marker.get('association') not in ('POINTS', 'CELLS', 'ROWS') or not isinstance(marker.get('field'), str) or not marker['field']:
                    fail('INVALID_SELECTION', 'sample needs an association and field name', location)
                if 'index' not in marker:
                    fail('INVALID_SELECTION', 'sample needs an explicit tuple index', location)
                if 'component' in marker and (type(marker['component']) is not int or marker['component'] < 0):
                    fail('INVALID_SELECTION', 'component must be a nonnegative integer', location)
                if 'block' in marker and (not isinstance(marker['block'], list) or
                        any(type(i) is not int or i < 0 for i in marker['block'])):
                    fail('INVALID_SELECTION', 'block must be a path of nonnegative indices', location)
            elif '$calc' in marker:
                keys(marker, ('$calc', 'args'), location)
                op, args = marker['$calc'], marker.get('args')
                counts = {'vector': 3, 'midpoint': 1, 'boundsMin': 1, 'boundsMax': 1, 'add': 2, 'subtract': 2,
                          'multiply': 2, 'divide': 2, 'min': 2, 'max': 2}
                if not isinstance(op, str) or op not in counts or not isinstance(args, list) or len(args) != counts[op]:
                    fail('INVALID_EXPRESSION', 'invalid calculation or arity', location)
            else:
                fail('INVALID_EXPRESSION', 'unknown runtime marker', location)
            if 'path' in marker and (not isinstance(marker['path'], list) or
                    any(type(p) not in (str, int) for p in marker['path'])):
                fail('INVALID_SELECTION', 'path must contain keys or indices', location)

    def _topological_order(self):
        # Iterative Kahn traversal does not overflow Python recursion on long graphs.
        remaining = {k: set(v['dependencies']) for k, v in self.nodes.items()}
        for key, deps in remaining.items():
            absent = deps - self.nodes.keys()
            if absent:
                fail('UNKNOWN_NODE', 'dependency does not exist', key, missing=sorted(absent))
        order = []
        while remaining:
            ready = [k for k, deps in remaining.items() if not deps]
            if not ready:
                fail('PIPELINE_CYCLE', 'dependency cycle prevents execution', '$.nodes',
                     dependencies={k: sorted(v) for k, v in remaining.items()})
            order.extend(ready)
            for key in ready:
                del remaining[key]
            for deps in remaining.values():
                deps.difference_update(ready)
        return tuple(order)

    def _check_static_axes(self):
        # Validate each independently selected option before native execution.
        for node in self.nodes.values():
            for key, value in node['options'].items():
                found = list(markers(value))
                if any('$observe' in m or '$sample' in m for m in found):
                    continue
                relevant = [a for a in self.axes if any(m.get('$axis') == a for m in found)]
                count = math.prod(len(self.axes[a]) for a in relevant)
                if count > self.limit:
                    fail('EXPANSION_TOO_LARGE', 'option expansion exceeds maxStates', node['id'])
                selected_times = self.times if any('$time' in m for m in found) else self.times[:1]
                for values in itertools.product(*(self.axes[a] for a in relevant)):
                    for time in selected_times:
                        result = evaluate(value, dict(zip(relevant, values)), {}, time, node['id'])
                        binding = self.declarations[node['filter']]['options'][key]
                        result = validate_value(result, binding['value'], node['id'] + '.' + key)
                        validate_binding(binding, convert_option(binding, result, node['id'] + '.' + key),
                                         node['id'] + '.' + key)

    def select(self, roots):
        if not isinstance(roots, (list, tuple)) or not roots:
            fail('EMPTY_SELECTION', 'at least one output or visible root is required')
        selected, pending = set(), list(roots)
        while pending:
            key = pending.pop()
            if not isinstance(key, str) or key not in self.nodes:
                fail('UNKNOWN_NODE', 'selected root does not exist', str(key))
            if key not in selected:
                selected.add(key)
                pending.extend(self.nodes[key]['dependencies'])
        order = tuple(k for k in self.order if k in selected)
        used = {m['$axis'] for k in order for m in markers(self.nodes[k]['options']) if '$axis' in m}
        axes = tuple(a for a in self.axes if a in used)
        count = math.prod(len(self.axes[a]) for a in axes) * len(self.times)
        if count > self.limit:
            fail('EXPANSION_TOO_LARGE', 'active pipeline exceeds maxStates', states=count, limit=self.limit)
        return Selection(self, tuple(roots), order, axes, count)

    def to_dict(self):
        value = {'version': 'schemaxis.plan/2', 'document': self.document,
                 'nodes': [self.nodes[k] for k in self.order],
                 'axesFastestFirst': list(self.axes), 'axes': self.axes, 'times': self.times,
                 'declarations': self.declarations}
        return {**copy.deepcopy(value), 'digest': digest(value)}


class Selection:
    def __init__(self, master, roots, order, axes, count):
        self.master, self.roots, self.order, self.axes, self.count = master, roots, order, axes, count

    def visits(self):
        slow_first = list(reversed(self.axes))
        for time_index, time in enumerate(self.master.times):
            for indices in itertools.product(*(range(len(self.master.axes[a])) for a in slow_first)):
                coordinates = dict(zip(slow_first, indices))
                yield {'time': time, 'timeIndex': time_index, 'indices': coordinates,
                       'axes': {a: copy.deepcopy(self.master.axes[a][coordinates[a]]) for a in self.axes}}

    def to_dict(self):
        return {'roots': list(self.roots), 'order': list(self.order),
                'pruned': [k for k in self.master.order if k not in self.order],
                'axesFastestFirst': list(self.axes), 'states': self.count}


class RuntimeClosure:
    """Own backend handles; reuse intersections when selecting another scene.

    Backend protocol: create(node, declaration, inputs, constructor_values),
    configure(handle, declaration, changes), update(handle, time), observe(handle),
    delete(handle). The caller publishes only after apply() returns successfully.
    Any failed transition poisons the instance; close it rather than retrying a
    partially applied native state.
    """
    def __init__(self, master, backend):
        self.master, self.backend = master, backend
        self.handles, self.values, self.observations = {}, {}, {}
        self.selection = None
        self.last_time = None
        self.failed = False
        self.closed = False
        self.events = []
        self.objects = ObjectRegistry()
        for identity, node in master.nodes.items():
            kinds = set(master.declarations[node['filter']].get('kinds', ['data'])) | {node['filter']}
            kinds.add('filter' if master.declarations[node['filter']]['inputs'] else 'source')
            if node['filter'] in ('foam', 'readSurface'):
                kinds.add('reader')
            self.objects.declare(identity, kinds)

    def activate(self, roots):
        if self.closed or self.failed:
            fail('CLOSED_PIPELINE', 'pipeline cannot accept further work')
        selection = self.master.select(roots)
        try:
            for key in reversed(self.master.order):
                if key in self.handles and key not in selection.order:
                    self.backend.delete(self.handles[key])
                    self.objects.retire(key)
                    del self.handles[key]
                    self.values.pop(key, None)
                    self.observations.pop(key, None)
                    self.events.append({'event': 'delete', 'node': key})
            # Native construction waits for apply(), when axis values are known.
            self.selection = selection
        except Exception:
            self.failed = True
            raise
        return selection

    def apply(self, visit):
        if self.closed or self.failed or self.selection is None:
            fail('CLOSED_PIPELINE', 'activate a usable pipeline before applying a state')
        changed, initial = set(), set()
        try:
            # All directly authored/axis changes are applied before any explicit update.
            for key in self.selection.order:
                node = self.master.nodes[key]
                declaration = self.master.declarations[node['filter']]
                direct = {k: convert_option(declaration['options'][k],
                                           evaluate(v, visit['axes'], {}, visit['time'], key + '.' + k), key + '.' + k)
                          for k, v in node['options'].items()
                          if not any('$observe' in m or '$sample' in m for m in markers(v))}
                if key not in self.handles:
                    context = InputContext(node['inputs'], owner=key + '.inputs', objects=self.objects)
                    def get_input(path, kind):
                        reference = context.get(path, raw=True)
                        if isinstance(reference, dict):
                            handle = self.objects.resolve(reference['node'], kind, key)
                            if not hasattr(self.backend, 'output_port'):
                                fail('UNSUPPORTED_OUTPUT_PORT', 'backend does not expose selected output ports', key)
                            return self.backend.output_port(handle, reference['port'])
                        return context.get(path, object_kind=kind)
                    inputs = {p: ([get_input([p, i], declaration['inputs'][p].get('kind', 'data')) for i in range(len(sources))]
                                  if isinstance(sources, list) else get_input([p], declaration['inputs'][p].get('kind', 'data')))
                              for p, sources in node['inputs'].items()}
                    constructor = {k: v for k, v in direct.items() if declaration['options'][k].get('constructor')}
                    self.handles[key] = self.backend.create(key, declaration, inputs, constructor)
                    self.objects.publish(key, self.handles[key])
                    self.values[key] = {}
                    initial.add(key)
                    self.events.append({'event': 'create', 'node': key})
                changes = {k: v for k, v in direct.items()
                           if k not in self.values.get(key, {}) or self.values[key][k] != v}
                if changes:
                    self.backend.configure(self.handles[key], declaration, changes)
                    self.values.setdefault(key, {}).update(copy.deepcopy(changes))
                    changed.add(key)
            dirty = changed | initial
            dirty.update(k for k in self.selection.order if self.master.nodes[k].get('onVisit'))
            if self.last_time != visit['time']:
                dirty.update(self.selection.order)
            sampled = []

            def sample(source, association, field, index, component, block):
                value = self.backend.sample(self.handles[source], association, field, index, component, block)
                sampled.append({'node': source, 'association': association, 'field': field,
                                'index': index, 'component': component, 'block': block, 'value': value})
                return value

            for key in self.selection.order:
                node = self.master.nodes[key]
                declaration = self.master.declarations[node['filter']]
                options = evaluate(node['options'], visit['axes'], self.observations, visit['time'], key, sample)
                options = validate_options(declaration, options, key)
                changes = {k: v for k, v in options.items()
                           if k not in self.values.get(key, {}) or self.values[key][k] != v}
                if changes:
                    self.backend.configure(self.handles[key], declaration, changes)
                    self.values.setdefault(key, {}).update(copy.deepcopy(changes))
                    dirty.add(key)
                if set(node['dependencies']) & dirty:
                    dirty.add(key)
                if key in dirty:
                    for command in node.get('onVisit', []):
                        if not hasattr(self.backend, 'command'):
                            fail('UNSUPPORTED_COMMAND', 'backend does not implement declared commands', key)
                        self.backend.command(self.handles[key], command)
                        self.events.append({'event':'command','node':key,'command':command,'time':visit['time']})
                    self.backend.update(self.handles[key], visit['time'])
                    self.observations[key] = self.backend.observe(self.handles[key])
                    self.events.append({'event': 'update', 'node': key, 'time': visit['time']})
            self.last_time = visit['time']
            return {'visit': copy.deepcopy(visit), 'updated': [k for k in self.selection.order if k in dirty],
                    'effective': copy.deepcopy(self.values), 'observations': copy.deepcopy(self.observations),
                    'samples': sampled}
        except SchemaxisError:
            self.failed = True
            raise
        except Exception as error:
            self.failed = True
            fail('PIPELINE_EXECUTION_FAILED', str(error), key,
                 exceptionType=type(error).__name__)

    def close(self):
        errors = []
        for key in reversed(self.master.order):
            if key in self.handles:
                try:
                    self.backend.delete(self.handles[key])
                    self.events.append({'event': 'delete', 'node': key})
                except Exception as error:
                    errors.append({'node': key, 'error': str(error)})
        self.objects.close()
        self.handles.clear()
        self.values.clear()
        self.observations.clear()
        self.closed = True
        if errors:
            fail('CLEANUP_FAILED', 'some backend objects could not be deleted', errors=errors)
