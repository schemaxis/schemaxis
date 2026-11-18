# Copyright (C) 2026 David L. F. Gaden
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
import operator
import re
from dataclasses import dataclass
from schemaxis.core.declarations import validate_arguments, validate_value
from schemaxis.documents import resolve_document
from schemaxis.core.faults import SchemaxisError
from .errors import fail, keys
from .bindings import convert_option, validate_binding, validate_options
from .context import ObjectRegistry, InputContext, compile_objects
from .expressions import deliver, fit_box


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def name(value, location):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', value):
        fail('INVALID_NAME', 'expected a name starting with a letter', location)
    return value


def node_name(value, location):
    """Instance names may start with a case number; expression names stay separate."""
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', value):
        fail('INVALID_NAME', 'expected letters, digits, underscore or hyphen, starting with a letter or digit', location)
    return value


def input_reference(value, location):
    """A selected output port retains its producer's graph identity."""
    if isinstance(value, dict):
        keys(value, ('node', 'port'), location)
        if type(value.get('port')) is not int or value['port'] < 0:
            fail('INVALID_OUTPUT_PORT', 'output port must be a nonnegative integer', location)
        return node_name(value.get('node'), location + '.node')
    return node_name(value, location)


def renamed_inputs(inputs, names):
    """Validated input ports with every producer identity mapped through ``names``."""
    result = {}
    for port, value in inputs.items():
        sources = []
        for source in value if isinstance(value, list) else [value]:
            identity = source['node'] if isinstance(source, dict) else source
            if identity not in names:
                fail('IDENTITY_TRANSITION_MISMATCH', 'input producer is not in the resident plan', port)
            sources.append({**source, 'node': names[identity]} if isinstance(source, dict) else names[identity])
        result[port] = sources if isinstance(value, list) else sources[0]
    return result


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


def evaluate(value, axes, observations, time, location, sampler=None, scope=None, pointer=None):
    """Value of authored markers at one visit; pointer is where the value sits in its document."""
    from . import expressions
    extend = expressions.extend
    if isinstance(value, list):
        return [evaluate(v, axes, observations, time, location, sampler, scope, extend(pointer, i))
                for i, v in enumerate(value)]
    if not isinstance(value, dict):
        return value
    if '$expr' in value:
        if isinstance(value['$expr'], str):
            state = expressions.State(axes, observations, time, sampler, location)
            return (scope or expressions.Scope({})).evaluate(value['$expr'], state, extend(pointer, '$expr'))
        return expressions.compose(evaluate(value['$expr'], axes, observations, time, location, sampler, scope,
                                            extend(pointer, '$expr')), location)
    if '$call' in value or ('$value' in value and 'path' not in value and isinstance(value.get('args'), dict)):
        from .functions import FUNCTIONS
        arguments = {k: evaluate(v, axes, observations, time, location + '/' + k, sampler, scope,
                                 extend(extend(pointer, 'args'), k))
                     for k, v in value.get('args', {}).items()}
        return FUNCTIONS.invoke(value.get('$call', value.get('$value')), arguments, location)
    if '$sweep' in value:
        return lookup(axes[value['$sweep']], value.get('path', []), location)
    if '$time' in value:
        return time
    if '$document' in value and scope is not None and scope.reference(value) is not None:
        return scope.reference(value).read(expressions.State(axes, observations, time, sampler, location))
    if expressions.analytic_marker(value) and scope is not None:
        return scope.analytic_value(value, pointer, expressions.State(axes, observations, time, sampler, location))
    if '$sample' in value:
        if sampler is None:
            fail('OBSERVATION_UNAVAILABLE', 'field sampling requires an updated upstream object', location)
        index = evaluate(value['index'], axes, observations, time, location, sampler, scope, extend(pointer, 'index'))
        return sampler(value['$sample'], value['association'], value['field'], index,
                       value.get('component'), value.get('block', []))
    if '$observe' in value:
        source = value['$observe']
        if source not in observations:
            fail('OBSERVATION_UNAVAILABLE', 'upstream data has not been observed', location, node=source)
        return lookup(observations[source], value.get('path', []), location)
    if '$calc' in value:
        args = [evaluate(v, axes, observations, time, location, sampler, scope, extend(extend(pointer, 'args'), i))
                for i, v in enumerate(value['args'])]
        return calculate(value['$calc'], args, location)
    return {k: evaluate(v, axes, observations, time, location, sampler, scope, extend(pointer, k))
            for k, v in value.items()}


def numeric(value):
    return type(value) in (int, float) and math.isfinite(value)


def combine(a, b, operation, location):
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [combine(x, y, operation, location) for x, y in zip(a, b)]
    if isinstance(a, list) and numeric(b):
        return [combine(x, b, operation, location) for x in a]
    if numeric(a) and isinstance(b, list):
        return [combine(a, x, operation, location) for x in b]
    if not numeric(a) or not numeric(b):
        fail('INVALID_EXPRESSION', 'arithmetic requires finite numbers or matching vectors', location)
    return operation(a, b)


ARITHMETIC = {'add': operator.add, 'subtract': operator.sub, 'multiply': operator.mul,
              'divide': operator.truediv, 'min': min, 'max': max}


def calculate(op, args, location):
    """One $calc operation on evaluated arguments."""
    try:
        if op in ('midpoint', 'boundsMin', 'boundsMax') and args:
            from .expressions import SIX
            args[0] = fit_box(args[0], SIX)
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
        elif op in ARITHMETIC:
            result = combine(*args, ARITHMETIC[op], location)
        else:
            fail('INVALID_EXPRESSION', 'unsupported calculation', location, operation=op)
        json.dumps(result, allow_nan=False)
        return result
    except (TypeError, ValueError, ZeroDivisionError, IndexError, OverflowError) as error:
        fail('INVALID_EXPRESSION', str(error), location)


def observed(backend, handle):
    """Observation of an updated object, with the extents of every output port when the backend reports them."""
    observation = backend.observe(handle)
    if hasattr(backend, 'extents') and isinstance(observation, dict):
        from .expressions import recorded_extents
        observation = {**observation, 'extents': recorded_extents(backend.extents(handle))}
    return observation


class DefinitionGraph:
    """Validated immutable-by-ownership library; no native objects are created."""

    def __init__(self, document, declarations, adaptor=None):
        from . import expressions
        self.document, self.provenance = resolve_document(copy.deepcopy(document), defer=expressions.has_markers)
        self.document = expressions.fold_constants(self.document, self.provenance)
        carried = self.document.pop(expressions.CARRIED, None) if isinstance(self.document, dict) else None
        self.outer = self.document.pop(expressions.VISITS, 1) if isinstance(self.document, dict) else 1
        self.given = self.document.pop(expressions.POSITIONS, None) if isinstance(self.document, dict) else None
        keys(self.document, ('version', 'nodes', 'sweeps', 'times', 'scenes', 'maxStates',
                             'maxPublications', 'definitions', 'dimensions', 'views', 'settings'), '$')
        if self.document.get('version') != 'schemaxis/1':
            fail('UNSUPPORTED_VERSION', 'expected schemaxis/1', '$.version')
        self.document = compile_objects(self.document)
        if carried is not None:
            self.document[expressions.CARRIED] = carried
        if self.given is not None:
            if not isinstance(self.given, dict) or any(type(p) is not int for p in self.given.values()):
                fail('INVALID_SELECTION', 'the position of each sweep is a whole number', '$.' + expressions.POSITIONS)
            self.document[expressions.POSITIONS] = self.given
        expressions.check_static(self.document)
        self.analytic_bindings = []
        if any('$analytic' in m for m in markers(self.document)):
            from .analytics import compile_analytics
            self.document, self.analytic_bindings = compile_analytics(self.document)
        self.declarations = copy.deepcopy(declarations)
        self.adaptor = expressions.Adaptor(expressions.extents_capability(self.document, adaptor),
                                           self.declarations, adaptor)
        self.axes = {}
        self.generated = {binding['axis'] for binding in self.analytic_bindings}
        raw_axes = self.document.get('sweeps', [])
        if not isinstance(raw_axes, list):
            fail('INVALID_SWEEP', 'sweeps must be an ordered list, fastest first', '$.sweeps')
        for raw in raw_axes:
            keys(raw, ('name', 'values', 'series', expressions.GENERATED), '$.sweeps')
            if raw.get(expressions.GENERATED) is True:
                self.generated.add(raw.get('name'))
            axis = name(raw.get('name'), '$.sweeps.name')
            if axis in self.axes:
                fail('DUPLICATE_SWEEP', 'sweep name is not unique', axis)
            values = raw.get('values')
            if 'series' in raw:
                if 'values' in raw:
                    fail('INVALID_SWEEP', 'choose values or series, not both', axis)
                from schemaxis.core.series import resolve_series
                values = list(resolve_series(raw['series'], limit=self.document.get('maxStates', 10000)).positions)
            if not isinstance(values, list) or not values:
                fail('EMPTY_SWEEP', 'sweep values must be a nonempty array', axis)
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
        if type(self.outer) is not int or self.outer < 1:
            fail('INVALID_LIMIT', 'the number of study visits is a positive integer')
        self.scope = expressions.Scope(self.document, dict(self.axes), adaptor=self.adaptor)
        self.profiles = {}
        self.pointers = {}
        self.nodes = {}
        raw_nodes = self.document.get('nodes')
        if not isinstance(raw_nodes, list) or not raw_nodes:
            fail('EMPTY_PIPELINE', 'nodes must be a nonempty list', '$.nodes')
        for index, raw in enumerate(raw_nodes):
            keys(raw, ('id', 'filter', 'inputs', 'options', 'onVisit'), '$.nodes')
            node_id = node_name(raw.get('id'), '$.nodes.id')
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
            self.pointers[node_id] = f'/nodes/{index}/options'
            for key, option in spec['options'].items():
                if key not in options and 'default' in option['value']:
                    options[key] = copy.deepcopy(option['value']['default'])
                if key not in options and option['value'].get('required'):
                    fail('MISSING_ARGUMENT', 'required option is missing', node_id + '.' + key)
                if key in options:
                    dynamic = list(markers(options[key]))
                    if option.get('constructor') and dynamic:
                        self._dynamic_constructor(options[key], node_id, key)
                    self._check_markers(dynamic, node_id + '.' + key)
                    if not dynamic:
                        options[key] = expressions.fit_box(options[key], option['value'])
                        validate_value(options[key], option['value'], node_id + '.' + key)
            deps = {input_reference(s, node_id) for value in inputs.values()
                    for s in (value if isinstance(value, list) else [value])}
            self.profiles[node_id] = {key: self._profile(value, node_id + '.' + key, self.pointer(node_id, key))
                                      for key, value in options.items()}
            for profile in self.profiles[node_id].values():
                deps.update(profile.nodes)
            self.nodes[node_id] = {'id': node_id, 'filter': kind, 'inputs': inputs,
                                   'options': options, 'dependencies': sorted(deps)}
            if commands: self.nodes[node_id]['onVisit'] = list(commands)
            if not list(markers(options)):
                validate_options(spec, options, node_id)
        for axis, declared in self.scope.sweeps.items():
            self.axes[axis] = self._positions(axis, declared['count'])
            self.generated.add(axis)
        if self.scope.sweeps:
            for raw in raw_axes:
                if raw['name'] in self.generated:
                    raw[expressions.GENERATED] = True
            first = self._first_use(set(self.nodes), set(self.axes))
            ordered = [axis for axis in self.axes if axis not in self.generated] + list(first)
            ordered.extend(axis for axis in self.axes if axis not in ordered)
            self.axes = {axis: self.axes[axis] for axis in ordered}
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

    def _positions(self, axis, count):
        """Positions this graph steps a generated sweep through: the one a study chose for this visit, else all."""
        if not self.given or axis not in self.given:
            return list(range(count))
        if not 0 <= self.given[axis] < count:
            fail('INVALID_SELECTION', 'the position of a sweep lies within its count', axis,
                 position=self.given[axis], count=count)
        return [self.given[axis]]

    def pointer(self, node, option=None):
        """Where a node's options, or one of them, sit in the document."""
        from . import expressions
        return self.pointers[node] if option is None else expressions.pointer(self.pointers[node], option)

    def _profile(self, value, location, pointer=None):
        from . import expressions
        try:
            return self.scope.profile(value, pointer)
        except expressions.expr.ExprFault as fault:
            expressions.raise_fault(fault, location, 'input')

    def presentation(self, value, pointer, location):
        """Check the late values of a scene, which takes no sweeps, and report what they depend on."""
        from . import expressions
        try:
            for path, marker in expressions.expression_markers(value, pointer):
                expressions.misuse(self.scope, marker, path, expressions.SCENE, location, f'scene value `{path}`')
            return self.scope.profile(value, pointer)
        except expressions.expr.ExprFault as fault:
            expressions.raise_fault(fault, location, 'input')

    def _dynamic_constructor(self, value, node, option):
        from . import expressions
        location = node + '.' + option
        if not any(expressions.is_expression(m) for m in markers(value)):
            fail('DYNAMIC_CONSTRUCTOR', 'constructor arguments must be constant', location)
        try:
            expressions.misuse(self.scope, value, self.pointer(node, option), expressions.CONSTRUCTOR, location,
                               'constructor option ' + location)
        except expressions.expr.ExprFault as fault:
            expressions.raise_fault(fault, location, 'input')
        fail('DYNAMIC_CONSTRUCTOR', 'constructor arguments must be constant', location)

    def _check_markers(self, found, location):
        for marker in found:
            if '$expr' in marker:
                keys(marker, ('$expr',), location)
            elif '$analytic' in marker:
                keys(marker, ('$analytic',), location)
            elif '$call' in marker:
                from .functions import FUNCTIONS
                keys(marker, ('$call', 'args'), location)
                FUNCTIONS.check(marker['$call'], marker.get('args', {}), location)
            elif '$sweep' in marker:
                keys(marker, ('$sweep', 'path'), location)
                if not isinstance(marker['$sweep'], str) or marker['$sweep'] not in self.axes:
                    fail('UNKNOWN_SWEEP', 'unknown sweep', location)
            elif '$observe' in marker:
                keys(marker, ('$observe', 'path'), location)
                node_name(marker['$observe'], location)
            elif '$time' in marker:
                keys(marker, ('$time',), location)
                if marker['$time'] is not True:
                    fail('INVALID_EXPRESSION', '$time must be true', location)
            elif '$sample' in marker:
                keys(marker, ('$sample', 'association', 'field', 'index', 'component', 'block'), location)
                node_name(marker['$sample'], location)
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
                profile = self.profiles[node['id']][key]
                if profile.observed:
                    continue
                relevant = [a for a in self.axes if a in profile.axes]
                count = math.prod(len(self.axes[a]) for a in relevant)
                if count > self.limit:
                    fail('EXPANSION_TOO_LARGE', 'option expansion exceeds maxStates', node['id'])
                selected_times = self.times if profile.time else self.times[:1]
                for values in itertools.product(*(self.axes[a] for a in relevant)):
                    for time in selected_times:
                        result = evaluate(value, dict(zip(relevant, values)), {}, time, node['id'], None, self.scope,
                                          self.pointer(node['id'], key))
                        binding = self.declarations[node['filter']]['options'][key]
                        result = deliver(result, value, binding['value'], node['id'] + '.' + key)
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
        used = {a for k in order for profile in self.profiles[k].values() for a in profile.axes}
        axes = tuple(a for a in self.axes if a in used)
        if self.scope.sweeps:
            axes = tuple(a for a in axes if a not in self.generated) + self._first_use(selected, used)
        count = math.prod(len(self.axes[a]) for a in axes) * len(self.times)
        if count * self.outer > self.limit:
            fail('EXPANSION_TOO_LARGE', 'active pipeline exceeds maxStates', states=count * self.outer,
                 limit=self.limit)
        return Selection(self, tuple(roots), order, axes, count)

    def _first_use(self, selected, used):
        """Generated axes in the order active nodes first use them, walking nodes as authored."""
        found = []
        for key, node in self.nodes.items():
            if key not in selected:
                continue
            for option, value in node['options'].items():
                for axis in self.scope.axis_uses(value, self.pointer(key, option)):
                    if axis in self.generated and axis in used and axis not in found:
                        found.append(axis)
        return tuple(found)

    def to_dict(self):
        value = {'version': 'schemaxis.plan/2', 'document': self.document,
                 'nodes': [self.nodes[k] for k in self.order],
                 'sweepsFastestFirst': list(self.axes), 'sweeps': self.axes, 'times': self.times,
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
                       'sweeps': {a: copy.deepcopy(self.master.axes[a][coordinates[a]]) for a in self.axes}}

    def to_dict(self):
        return {'roots': list(self.roots), 'order': list(self.order),
                'pruned': [k for k in self.master.order if k not in self.order],
                'sweepsFastestFirst': list(self.axes), 'states': self.count}


def declare_objects(master):
    """A typed registry declaring every node of ``master``; nothing is published."""
    objects = ObjectRegistry()
    for identity, node in master.nodes.items():
        kinds = set(master.declarations[node['filter']].get('kinds', ['data'])) | {node['filter']}
        kinds.add('filter' if master.declarations[node['filter']]['inputs'] else 'source')
        if node['filter'] in ('foam', 'readSurface'):
            kinds.add('reader')
        objects.declare(identity, kinds)
    return objects


def direct_values(master, key, visit):
    """Converted values of a node's options that need no observation, at one visit."""
    node = master.nodes[key]
    declaration = master.declarations[node['filter']]
    return {k: convert_option(declaration['options'][k], deliver(
                evaluate(v, visit['sweeps'], {}, visit['time'], key + '.' + k, None, master.scope,
                         master.pointer(key, k)),
                v, declaration['options'][k]['value'], key + '.' + k), key + '.' + k)
            for k, v in node['options'].items() if not master.profiles[key][k].observed}


def evaluated_options(master, key, visit, observations, sampler):
    """Validated values of all of a node's options at one visit, given upstream observations."""
    node = master.nodes[key]
    declaration = master.declarations[node['filter']]
    options = evaluate(node['options'], visit['sweeps'], observations, visit['time'], key, sampler,
                       master.scope, master.pointer(key))
    options = {k: deliver(v, node['options'][k], declaration['options'][k]['value'], key + '.' + k)
               for k, v in options.items()}
    return validate_options(declaration, options, key)


def producers(node):
    """Node identities bound to the input ports of ``node``."""
    return {source['node'] if isinstance(source, dict) else source
            for value in node['inputs'].values() for source in (value if isinstance(value, list) else [value])}


NATIVE_STAGES = ('configure', 'command', 'update', 'observe')


class Transition:
    """Native-free plan of one ordinary change of a closure's plan and selection.

    ``retained`` keep their exact handle; ``unaffected`` is the retained subset
    predicted to receive no configure, command or update; ``replaced`` maps a
    node to the reason its handle is deleted and created again; ``retired`` is
    the deletion order (the old plan's reverse dependency order). Same authored
    IDs grant no continuity on their own.
    """

    def __init__(self, owner, generation, master, selection, visit, recover, **parts):
        self.owner, self.generation, self.master, self.selection = owner, generation, master, selection
        self.visit, self.recover = copy.deepcopy(visit), recover
        self.retained, self.unaffected, self.created = parts['retained'], parts['unaffected'], parts['created']
        self.replaced, self.affected, self.retired = parts['replaced'], parts['affected'], parts['retired']
        self.time_changed, self.previous = parts['time_changed'], parts['previous']

    def report(self):
        return {'retained': list(self.retained), 'unaffected': list(self.unaffected),
                'created': list(self.created), 'replaced': dict(self.replaced), 'affected': dict(self.affected),
                'retired': list(self.retired), 'timeChanged': self.time_changed}


@dataclass(frozen=True)
class _TransitionAnalysis:
    """Read-only planning facts, with no native handles, registry or lifecycle."""
    master: object
    resident: tuple
    values: dict
    observations: dict
    last_time: object
    failed: bool
    failure: object

    def prepare(self, master, roots, visit, preserve):
        if not isinstance(preserve, (list, tuple, set, frozenset)) or any(not isinstance(k, str) for k in preserve):
            fail('INVALID_ARGUMENT', 'preserve names resident nodes')
        selection = master.select(roots)
        old, owned = self.master, set(self.resident)
        suspect = None
        if self.failed and (self.failure or {}).get('stage') in NATIVE_STAGES:
            suspect = self.failure['node']
        created, replaced, retained = [], {}, []
        for key in selection.order:
            if key not in owned:
                created.append(key)
                continue
            reason = self._replacement(master, key, visit, suspect, set(created) | set(replaced))
            if reason:
                replaced[key] = reason
            else:
                retained.append(key)
        retired = [k for k in reversed(old.order) if k in owned and (k not in selection.order or k in replaced)]
        retired += [k for k in reversed(self.resident) if k not in old.order]
        time_changed = self.last_time != visit['time']
        affected = {}
        for key in retained:
            affected_by = self._affected(master, key, visit, time_changed, set(created) | set(replaced) | set(affected))
            if affected_by:
                affected[key] = affected_by
        unaffected = [k for k in retained if k not in affected]
        problems = {}
        for key in preserve:
            if key not in owned:
                problems[key] = 'notResident'
            elif key not in selection.order:
                problems[key] = 'retired'
            elif key in replaced or key in affected:
                problems[key] = replaced.get(key) or affected[key]
        if problems:
            fail('UNSUPPORTED_RESIDENT_TRANSITION', 'this change cannot keep these resident objects unchanged',
                 nodes=problems)
        return selection, dict(retained=retained, unaffected=unaffected, created=created,
                               replaced=replaced, affected=affected, retired=retired, time_changed=time_changed)

    def _replacement(self, master, key, visit, suspect, renewed):
        """Why a resident node cannot keep its handle in ``master``, or None."""
        before, after = self.master.nodes[key], master.nodes[key]
        if key == suspect:
            return 'uncertain'
        if before['filter'] != after['filter']:
            return 'filter'
        declaration = master.declarations[after['filter']]
        if self.master.declarations[before['filter']] != declaration:
            return 'declaration'
        if before['inputs'] != after['inputs']:
            return 'inputs'
        if before.get('onVisit', []) != after.get('onVisit', []):
            return 'commands'
        applied = self.values.get(key, {})
        if (set(before['options']) | set(applied)) - set(after['options']):
            return 'removedOption'
        constructors = [k for k, binding in declaration['options'].items() if binding.get('constructor')]
        for option in constructors:
            profile = master.profiles[key].get(option)
            if profile is not None and (profile.observed or profile.axes or profile.time):
                fail('UNSUPPORTED_RESIDENT_TRANSITION', 'a late constructor value cannot be compared with its handle',
                     key + '.' + option, nodes={key: 'dynamicConstructor'})
        values = direct_values(master, key, visit)
        if ({k: values[k] for k in constructors if k in values}
                != {k: applied[k] for k in constructors if k in applied}):
            return 'constructor'
        if producers(after) & renewed:
            return 'inputReplaced'
        return None

    def _affected(self, master, key, visit, time_changed, affected):
        """Why a retained node would be configured, commanded or updated, or None when provably not."""
        node = master.nodes[key]
        if time_changed:
            return 'time'
        if node.get('onVisit'):
            return 'commands'
        if set(node['dependencies']) & affected:
            return 'dependency'
        applied = self.values.get(key, {})
        if any(k not in applied or applied[k] != v for k, v in direct_values(master, key, visit).items()):
            return 'configured'
        try:
            options = evaluated_options(master, key, visit, self.observations, None)
        except SchemaxisError:
            return 'observation'
        if any(k not in applied or applied[k] != v for k, v in options.items()):
            return 'configured'
        return None


class RuntimeClosure:
    """Own backend handles; reuse intersections when selecting another scene.

    Backend protocol: create(node, declaration, inputs, constructor_values),
    configure(handle, declaration, changes), update(handle, time), observe(handle),
    delete(handle). The caller publishes only after apply() returns successfully.
    A failed apply poisons the instance and records the node and stage that
    failed; only revert() or a recovery transition may continue from it.
    """
    def __init__(self, master, backend):
        self.master, self.backend = master, backend
        self.handles, self.values, self.observations = {}, {}, {}
        self.selection = None
        self.last_time = None
        self.visit = None
        self.failed = False
        self.failure = None
        self.abandoned = {}
        self.unknown = {}
        self.generation = 0
        self.closed = False
        self.events = []
        self.objects = declare_objects(master)

    def activate(self, roots):
        if self.closed or self.failed:
            fail('CLOSED_PIPELINE', 'pipeline cannot accept further work')
        selection = self.master.select(roots)
        self.generation += 1
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
        self.generation += 1
        changed, initial = set(), set()
        key, stage = None, 'evaluate'
        try:
            # All directly authored/axis changes are applied before any explicit update.
            for key in self.selection.order:
                stage = 'evaluate'
                node = self.master.nodes[key]
                declaration = self.master.declarations[node['filter']]
                direct = direct_values(self.master, key, visit)
                if key not in self.handles:
                    stage = 'resolve'
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
                    stage = 'create'
                    self.handles[key] = self.backend.create(key, declaration, inputs, constructor)
                    stage = 'publish'
                    self.objects.publish(key, self.handles[key])
                    self.values[key] = {}
                    initial.add(key)
                    self.events.append({'event': 'create', 'node': key})
                changes = {k: v for k, v in direct.items()
                           if k not in self.values.get(key, {}) or self.values[key][k] != v}
                if changes:
                    stage = 'configure'
                    self.backend.configure(self.handles[key], declaration, changes)
                    self.values.setdefault(key, {}).update(copy.deepcopy(changes))
                    changed.add(key)
            key, stage = None, 'evaluate'
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
                stage = 'evaluate'
                node = self.master.nodes[key]
                declaration = self.master.declarations[node['filter']]
                options = evaluated_options(self.master, key, visit, self.observations, sample)
                changes = {k: v for k, v in options.items()
                           if k not in self.values.get(key, {}) or self.values[key][k] != v}
                if changes:
                    stage = 'configure'
                    self.backend.configure(self.handles[key], declaration, changes)
                    self.values.setdefault(key, {}).update(copy.deepcopy(changes))
                    dirty.add(key)
                if set(node['dependencies']) & dirty:
                    dirty.add(key)
                if key in dirty:
                    stage = 'command'
                    for command in node.get('onVisit', []):
                        if not hasattr(self.backend, 'command'):
                            fail('UNSUPPORTED_COMMAND', 'backend does not implement declared commands', key)
                        self.backend.command(self.handles[key], command)
                        self.events.append({'event':'command','node':key,'command':command,'time':visit['time']})
                    stage = 'update'
                    self.backend.update(self.handles[key], visit['time'])
                    stage = 'observe'
                    self.observations[key] = observed(self.backend, self.handles[key])
                    self.events.append({'event': 'update', 'node': key, 'time': visit['time']})
            self.last_time = visit['time']
            self.visit = copy.deepcopy(visit)
            return {'visit': copy.deepcopy(visit), 'updated': [k for k in self.selection.order if k in dirty],
                    'effective': copy.deepcopy(self.values), 'observations': copy.deepcopy(self.observations),
                    'samples': sampled}
        except SchemaxisError as error:
            self._poison(key, stage, visit, error)
            raise
        except Exception as error:
            self._poison(key, stage, visit, error)
            fail('PIPELINE_EXECUTION_FAILED', str(error), key,
                 exceptionType=type(error).__name__, **({'unknownOwner': True} if stage == 'create' else {}))

    def _poison(self, key, stage, visit, error):
        """Record which node and stage failed; a node updated at another time leaves the time unknown.

        A failure inside backend.create returns no handle yet proves nothing about
        what the backend allocated, so that node's native ownership is unknown.
        """
        self.failed = True
        self.failure = {'node': key, 'stage': stage}
        if stage == 'create':
            self.unknown[key] = {'stage': stage, 'exceptionType': type(error).__name__, 'message': str(error)[:500]}
        if self.last_time != visit['time']:
            self.last_time = None

    def prepare_transition(self, master, roots, visit, preserve=(), recover=False):
        """Plan an ordinary change to ``master`` and ``roots`` at ``visit`` without native calls.

        Old ownership is enumerated before anything changes. A resident node keeps
        its handle only when its filter, full declaration, input bindings, commands
        and applied option set are unchanged, its constructor values convert to the
        values its handle was built with at this visit, and no input producer is
        replaced. ``preserve`` names resident nodes that must keep their handle and
        receive no configure, command or update; otherwise the whole change is
        refused before any native call. ``recover`` permits planning from a failed
        apply, treating its failing node as uncertain. Abandoned deletions and
        unknown creations refuse: no plan can prove what the backend still owns.
        """
        if self.closed or self.selection is None or (self.failed and not recover):
            fail('CLOSED_PIPELINE', 'transition an activated, usable pipeline')
        if self.abandoned or self.unknown:
            fail('CLOSED_PIPELINE', 'native ownership is uncertain; release this resident data',
                 uncertain=True, abandoned=sorted(self.abandoned), unknown=copy.deepcopy(self.unknown))
        analysis = _TransitionAnalysis(self.master, tuple(self.handles), self.values, self.observations,
                                       self.last_time, self.failed, self.failure)
        selection, parts = analysis.prepare(master, roots, visit, preserve)
        previous = None
        if not recover and self.visit is not None:
            previous = (self.master, self.selection.roots, copy.deepcopy(self.visit), copy.deepcopy(self.observations))
        return Transition(self, self.generation, master, selection, visit, recover, previous=previous, **parts)

    def preflight_reidentified_transition(self, steps, planner, master, roots, visit, preserve=(), relabel=None):
        """Check ordinary eligibility after an exact identity replay, without owning a projection.

        Only immutable-by-ownership plan data, resident names and copied measured
        values enter the analysis. No handle, backend or object registry is made
        available to it. The returned report cannot execute or transfer ownership.
        """
        renamed, selection, names, _, _ = self.prepare_reidentify(steps, planner, relabel)
        if self.abandoned or self.unknown:
            fail('CLOSED_PIPELINE', 'native ownership is uncertain', uncertain=True)
        analysis = _TransitionAnalysis(renamed, tuple(names[n] for n in self.handles),
            {names[n]: copy.deepcopy(v) for n, v in self.values.items()},
            {names[n]: copy.deepcopy(v) for n, v in self.observations.items()},
            self.last_time, False, None)
        _, parts = analysis.prepare(master, roots, visit, preserve)
        return {'roots': list(selection.roots), 'transition': {
            **{k: v for k, v in parts.items() if k != 'time_changed'}, 'timeChanged': parts['time_changed']}}

    def transition(self, plan):
        """Execute a prepared transition: retire, rebind ownership, then apply the target visit.

        Retired handles are deleted in the old plan's reverse dependency order
        before any creation. A handle whose deletion fails is abandoned: never
        deleted again, and no further transition is planned from this closure.
        """
        if not isinstance(plan, Transition) or plan.owner is not self or plan.generation != self.generation:
            fail('STALE_TRANSITION', 'the resident pipeline changed after this transition was prepared')
        if self.closed or self.abandoned or self.unknown or (self.failed and not plan.recover):
            fail('CLOSED_PIPELINE', 'transition an activated, usable pipeline')
        self.generation += 1
        for key in plan.retired:
            handle = self.handles.pop(key)
            self.values.pop(key, None)
            self.observations.pop(key, None)
            try:
                self.backend.delete(handle)
            except Exception as error:
                self.abandoned[key] = handle
                self.failed = True
                self.failure = {'node': key, 'stage': 'delete'}
                fail('PIPELINE_TRANSITION_FAILED', 'a retired backend object could not be deleted; its ownership is uncertain',
                     key, cause=str(error), uncertain=True, abandoned=sorted(self.abandoned), owned=sorted(self.handles))
            self.objects.retire(key)
            self.events.append({'event': 'delete', 'node': key})
        objects = declare_objects(plan.master)
        for key, handle in self.handles.items():
            objects.publish(key, handle)
        self.objects.close()
        self.objects = objects
        self.values = {k: v for k, v in self.values.items() if k in self.handles}
        self.observations = {k: v for k, v in self.observations.items() if k in self.handles}
        self.master, self.selection = plan.master, plan.selection
        self.failed, self.failure = False, None
        self.events.append({'event': 'transition', 'retained': list(plan.retained), 'created': list(plan.created),
                            'retired': list(plan.retired)})
        return self.apply(plan.visit)

    def revert(self, plan):
        """Return to the plan, selection and visit captured by ``plan``, verifying observations.

        A failed node is replaced; retained unaffected handles stay. A mismatch
        poisons this closure and leaves its remaining ownership for close().
        """
        if plan.previous is None:
            fail('UNSUPPORTED_RESIDENT_TRANSITION', 'this transition captured no state to return to')
        master, roots, visit, observations = plan.previous
        state = self.transition(self.prepare_transition(master, roots, visit, recover=True))
        if self.observations != observations:
            self.failed = True
            self.failure = {'node': None, 'stage': 'verify'}
            fail('ROLLBACK_MISMATCH', 'restored observations differ from the state before the transition')
        return state

    def reidentify(self, steps, planner, relabel=None):
        """Return a closure owning these same native objects under exactly renamed identities.

        The replacement plan is derived here, never accepted from a caller: the
        checked rename replays ``steps`` on this closure's own plan document and
        ``planner(document)`` (the adaptor's planning of such a document) must
        first reproduce the current plan exactly. Correspondence is validated
        before any native call. ``relabel(handle, old, new)`` is the adaptor's
        declared label operation; completed labels are reversed if a later one
        fails, and an irreversible label state poisons this closure. Nothing is
        created, configured, updated, commanded or deleted. On success this
        instance relinquishes its handles and is closed.
        """
        master, selection, names, labels, steps = self.prepare_reidentify(steps, planner, relabel)
        replacement = RuntimeClosure(master, self.backend)
        replacement.handles = {names[key]: handle for key, handle in self.handles.items()}
        replacement.values = {names[key]: value for key, value in self.values.items()}
        replacement.observations = {names[key]: value for key, value in self.observations.items()}
        replacement.last_time = self.last_time
        replacement.visit = copy.deepcopy(self.visit)
        replacement.selection = selection
        replacement.events = self.events + [{'event': 'reidentify', 'steps': [list(step) for step in steps]}]
        for key, handle in replacement.handles.items():
            replacement.objects.publish(key, handle)
        done = []
        try:
            for key, old, new in labels:
                relabel(self.handles[key], old, new)
                done.append((key, old, new))
        except BaseException as error:
            replacement.objects.close()
            # Only a structured refusal that is not uncertain proves the failing label
            # was left as it was; anything else may have changed it part-way.
            uncertain = not isinstance(error, SchemaxisError) or bool(error.fault.observed.get('uncertain'))
            try:
                for key, old, new in reversed(done):
                    relabel(self.handles[key], new, old)
            except BaseException as rollback:
                uncertain, error = True, rollback
            if uncertain:
                self.failed = True
                fail('IDENTITY_TRANSITION_UNCERTAIN', 'native labels could not be restored; release this resident data',
                     cause=str(error), uncertain=True)
            raise
        self.objects.close()
        self.handles, self.values, self.observations = {}, {}, {}
        self.closed = True
        return replacement

    def prepare_reidentify(self, steps, planner, relabel=None):
        """Prove a native-free ownership transfer and return only its plan correspondence."""
        from .identity_transition import replay, steps_of
        if self.closed or self.failed or self.selection is None:
            fail('CLOSED_PIPELINE', 'reidentify an activated, usable pipeline')
        steps = steps_of(steps)
        if digest(planner(self.master.document).document) != digest(self.master.document):
            fail('UNSUPPORTED_IDENTITY_TRANSITION', 'the resident plan cannot be reproduced exactly from its document')
        replayed = replay(self.master.document, steps)
        master = planner(replayed)
        if digest(master.document) != digest(replayed):
            fail('IDENTITY_TRANSITION_MISMATCH', 'the replacement plan is not exactly the checked rename of this plan')
        names = {key: key for key in self.master.nodes}
        labels = []
        for step in steps:
            owners = [key for key, name in names.items() if name == step[0]]
            if len(owners) != 1:
                fail('IDENTITY_TRANSITION_MISMATCH', 'renamed identity is not in the resident plan', step[0])
            if step[1] in names.values():
                fail('IDENTITY_COLLISION', 'new identity already names another resident plan node', step[1])
            names[owners[0]] = step[1]
            if owners[0] in self.handles:
                labels.append((owners[0], step[0], step[1]))
        if labels and relabel is None:
            fail('UNSUPPORTED_IDENTITY_TRANSITION', 'backend declares no safe native relabel operation')
        if (set(names.values()) != set(master.nodes)
                or tuple(names[key] for key in self.master.order) != tuple(master.order)):
            fail('IDENTITY_TRANSITION_MISMATCH', 'replacement plan nodes are not these nodes under the identity steps')
        for key, before in self.master.nodes.items():
            after = master.nodes[names[key]]
            declaration = self.master.declarations[before['filter']]
            constructors = [k for k, value in declaration['options'].items() if value.get('constructor')]
            if (before['filter'] != after['filter'] or declaration != master.declarations.get(after['filter'])
                    or renamed_inputs(before['inputs'], names) != after['inputs']
                    or sorted(names[d] for d in before['dependencies']) != sorted(after['dependencies'])
                    or before.get('onVisit', []) != after.get('onVisit', [])
                    or set(before['options']) != set(after['options'])
                    or any(before['options'].get(k) != after['options'].get(k) for k in constructors)):
                fail('IDENTITY_TRANSITION_MISMATCH', 'replacement plan changes more than this node identity', names[key])
        selection = master.select([names[key] for key in self.selection.roots])
        if (selection.order != tuple(names[key] for key in self.selection.order)
                or selection.axes != self.selection.axes or selection.count != self.selection.count):
            fail('IDENTITY_TRANSITION_MISMATCH', 'replacement selection differs from the resident selection')
        return master, selection, names, labels, steps

    def close(self):
        """Delete every still-owned handle once, consumers first.

        Abandoned handles are not retried and unknown creations have no handle;
        both remain for the backend's own reset or process shutdown.
        """
        errors = []
        order = [key for key in reversed(self.master.order) if key in self.handles]
        order += [key for key in reversed(list(self.handles)) if key not in order]
        for key in order:
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
