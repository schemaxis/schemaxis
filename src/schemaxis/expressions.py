"""Binding of the expression language to Schemaxis documents.

The language itself lives in schemaxis.expr and knows nothing of documents.
This module supplies its environment: named entries, axes, time, the function
catalogue, phases, and faults reported at document locations.
"""
import copy
import math
import re
import types

from schemaxis.core.composition import evaluate as compose
from schemaxis.core.faults import Fault, SchemaxisError
from . import expr
from .expr import syntax
from .expr.values import BOX, JSON, SCALAR, STRING, BOOLEAN, UNKNOWN, VECTOR, is_box_object, is_six

SECTIONS = ('dimensions', 'settings', 'definitions')
ROOTS = SECTIONS + ('sweeps', 'workflow')
ARITHMETIC = ('add', 'subtract', 'multiply', 'divide')
VECTOR_CALCULATIONS = ('vector', 'midpoint', 'boundsMin', 'boundsMax')
SIX = {'type': 'array', 'items': {'type': 'number'}, 'minItems': 6, 'maxItems': 6}
TIME = ('time',)
OPERATION_DOCUMENT = re.compile(r'/operations/[0-9]+/document')
OPTION_VALUE = re.compile(r'/nodes/[0-9]+/options/')
PENDING = ('pending',)
DATA = ('data',)
CARRIED = '%%workflowScope%%'
VISITS = '%%studyVisits%%'
POSITIONS = '%%studyPositions%%'
GENERATED = '%%generated%%'
INVALID_SIX = [1, -1, 1, -1, 1, -1]
ANALYTIC = '$analytic'
CONSTRUCTOR, OPTION, SCENE, STATIC, ENTRY = 'constructor', 'option', 'scene', 'static', 'entry'


def has_markers(value):
    if isinstance(value, dict):
        return any(key.startswith('$') for key in value) or any(has_markers(item) for item in value.values())
    if isinstance(value, list):
        return any(has_markers(item) for item in value)
    return False


def is_expression(value):
    return isinstance(value, dict) and isinstance(value.get('$expr'), str)


def raise_fault(fault, location, phase):
    observed = {key: value for key, value in fault.observed.items() if value is not None}
    if fault.position is not None:
        observed.update(position=fault.position, length=fault.length)
    raise SchemaxisError(Fault(fault.code, fault.message, location, phase, observed=observed)) from None


def six_numbers(specification):
    return (specification.get('type') == 'array' and specification.get('minItems') == 6
            and specification.get('maxItems') == 6 and specification.get('items', {}).get('type') == 'number')


def three_numbers(specification):
    return (specification.get('type') == 'array' and specification.get('minItems') == 3
            and specification.get('maxItems') == 3 and specification.get('items', {}).get('type') == 'number')


def corner_object(specification):
    properties = specification.get('properties', {})
    return (specification.get('type') == 'object' and set(properties) == {'min', 'max'}
            and three_numbers(properties['min']) and three_numbers(properties['max']))


def declared_type(specification):
    """Language type of a declared JSON shape."""
    kind = specification.get('type')
    if kind in ('number', 'integer'):
        return SCALAR
    if kind == 'boolean':
        return BOOLEAN
    if kind in ('string', 'enum'):
        return STRING
    if six_numbers(specification) or corner_object(specification):
        return BOX
    if kind == 'union' and all(declared_type(option) == BOX for option in specification.get('options', [])):
        return BOX
    if three_numbers(specification):
        return VECTOR
    return JSON


def fit_box(value, specification):
    """Write a box in the form its destination declares."""
    if is_box_object(value) and six_numbers(specification):
        return [x for pair in zip(value['min'], value['max']) for x in pair]
    if is_six(value) and corner_object(specification):
        return {'min': list(value[0::2]), 'max': list(value[1::2])}
    return value


def is_invalid_box(value):
    if is_six(value):
        return any(lower > upper for lower, upper in zip(value[0::2], value[1::2]))
    return is_box_object(value) and any(lower > upper for lower, upper in zip(value['min'], value['max']))


def refuse_invalid_box(text, location, phase):
    raise SchemaxisError(Fault(
        'EXPR_INVALID_BOX', f'`{text}` is an invalid box and cannot be the value of an option', location, phase,
        observed={'expression': text, 'source': text}))


def deliver(value, authored, specification, location):
    """Value of an option in its declared form; an invalid box from an expression is refused."""
    if is_expression(authored) and is_invalid_box(value):
        refuse_invalid_box(authored['$expr'], location, 'pipeline')
    return fit_box(value, specification)


class DeclaredShape(expr.Shape):
    """A declared result, so a selection from it is typed before evaluation."""

    def __init__(self, specification):
        self.specification = specification
        self.type = declared_type(specification)

    def member(self, key):
        properties = self.specification.get('properties', {})
        return DeclaredShape(properties[key]) if key in properties else None

    def item(self, index):
        items = self.specification.get('items')
        return DeclaredShape(items) if isinstance(items, dict) else None


class State:
    """What is known at one visit while a value is evaluated."""

    def __init__(self, axes=None, observations=None, time=None, sampler=None, location='$'):
        self.axes = axes or {}
        self.observations = observations or {}
        self.time = time
        self.sampler = sampler
        self.location = location


class Profile:
    """When a value can be evaluated and what it depends on."""

    def __init__(self, dependencies=frozenset()):
        self.dependencies = frozenset(dependencies)
        self.nodes = frozenset(item[1] for item in self.dependencies if item[0] == 'node')
        self.axes = frozenset(item[1] for item in self.dependencies if item[0] == 'axis')
        self.sweeps = frozenset(item[1] for item in self.dependencies if item[0] == 'sweep')
        self.entries = frozenset(item[1:] for item in self.dependencies if item[0] == 'entry')
        self.awaits = frozenset(item[1] for item in self.dependencies if item[0] == 'awaits')
        self.time = TIME in self.dependencies
        self.pending = PENDING in self.dependencies
        self.data = DATA in self.dependencies
        self.phase = (expr.OBSERVED if self.nodes or self.data
                      else expr.VISIT if self.axes or self.time else expr.CONSTANT)

    @property
    def observed(self):
        return self.phase == expr.OBSERVED

    @property
    def constant(self):
        return self.phase == expr.CONSTANT and not self.pending


class Adaptor:
    """What the document's adaptor declares: the extents capability and its node declarations."""

    def __init__(self, extents=None, declarations=None, name=None):
        self.extents = extents
        self.declarations = declarations
        self.name = name


def adaptor_of(document):
    """Adaptor of a document found by its version; unknown versions give no knowledge."""
    from .adaptors import registry
    version = document.get('version') if isinstance(document, dict) else None
    route = registry.routes().get(version) if isinstance(version, str) else None
    if route is None:
        return Adaptor()
    provider = route[0]
    try:
        declarations = registry.declarations(provider)
    except Exception:
        declarations = None
    return Adaptor(bool(registry.metadata(provider).get('extents')), declarations, provider)


class EntryBinding(expr.Binding):
    """A named entry of dimensions, settings or definitions."""

    def __init__(self, scope, section, key, kind, known, shape, profile):
        dependencies = profile.dependencies | {('entry', scope.kind, section, key)}
        super().__init__(kind, profile.phase, dependencies, known, shape, f'{section}.{key}')
        self.scope = scope
        self.section = section
        self.key = key
        self.profile = profile

    def read(self, state):
        return self.scope.entry_value(self.section, self.key, state)


class AxisBinding(expr.Binding):
    """A declared axis: its value at the current visit."""

    def __init__(self, name, kind):
        super().__init__(kind, expr.VISIT, [('axis', name)], label=f'sweeps.{name}')
        self.name = name

    def read(self, state):
        if self.name not in state.axes:
            raise expr.ExprFault('EXPR_PHASE', f'sweep `{self.name}` has no value here', variable=self.name,
                                 phase='visit', accepted=['constant'])
        return state.axes[self.name]


class TimeBinding(expr.Binding):
    """The time of the current visit."""

    def __init__(self):
        super().__init__(SCALAR, expr.VISIT, [TIME], label='time')

    def read(self, state):
        if state.time is None:
            raise expr.ExprFault('EXPR_PHASE', '`time` has no value here', variable='time', phase='visit',
                                 accepted=['constant'])
        return state.time


class DataExtentsBinding(expr.Binding):
    """dataExtents: the union of every output of every data-loading node."""

    def __init__(self, scope):
        loaders = scope.loaders()
        dependencies = [DATA] if loaders is None else [item for node in loaders
                                                       for item in (('node', node), ('ports', node))]
        super().__init__(BOX, expr.OBSERVED, dependencies or [DATA], label='dataExtents')
        self.scope = scope
        self.nodes = loaders

    def read(self, state):
        result = expr.INVALID
        for node in self.nodes if self.nodes is not None else self.scope.loaders() or []:
            for value in self.scope.port_extents(node, state):
                if value is not None:
                    result = expr.boxes.union(result, expr.make_box(value[0::2], value[1::2]))
        return result


class Root(expr.Namespace):
    """A reserved root: one document section, or the declared axes."""

    def __init__(self, scope, name):
        super().__init__(name)
        self.scope = scope
        self.name = name

    def member(self, name):
        if self.name == 'sweeps':
            return self.scope.axis(name)
        if self.name in SECTIONS:
            return self.scope.entry(self.name, name)
        if self.scope.workflow is not None and name in SECTIONS:
            return Root(self.scope.workflow, name)
        return None

    def available(self):
        if self.name == 'sweeps':
            return sorted(self.scope.axes)
        if self.name == 'workflow':
            return list(SECTIONS) if self.scope.workflow is not None else []
        return sorted(self.scope.sections.get(self.name, {}))


class CatalogueFunction(expr.HostFunction):
    """A registered catalogue function, called with named arguments."""

    def __init__(self, name, arguments, result):
        self.name = name
        self.arguments = arguments
        self.result = result

    def check(self, call, checker):
        expected = sorted(self.arguments)
        if call.arguments:
            raise checker.fault('EXPR_ARGUMENTS', f'{self.name} takes named arguments only', call,
                                function=self.name, expected=expected)
        given = [argument.name for argument in call.named]
        missing = [key for key, spec in self.arguments.items() if spec.get('required') and key not in given]
        unknown = [key for key in given if key not in self.arguments]
        if missing or unknown or len(set(given)) != len(given):
            raise checker.fault('EXPR_ARGUMENTS', f'{self.name} takes {", ".join(expected)}', call,
                                function=self.name, expected=expected, missing=missing, unknown=unknown)
        infos = []
        for argument in call.named:
            info = checker.check(argument.value)
            accepted = declared_type(self.arguments[argument.name])
            if accepted != JSON and info.type not in (accepted, JSON, UNKNOWN):
                raise checker.fault('EXPR_TYPE', f'{self.name}.{argument.name} takes {accepted}, not {info.type}',
                                    argument.value, expected=[accepted], actual=info.type)
            infos.append(info)
        result = checker.combine(declared_type(self.result), *infos)
        result.shape = DeclaredShape(self.result)
        return result

    def evaluate(self, call, evaluator):
        from .functions import FUNCTIONS
        arguments = {}
        for argument in call.named:
            value = expr.to_json(evaluator.evaluate(argument.value))
            arguments[argument.name] = fit_box(value, self.arguments[argument.name])
        return FUNCTIONS.invoke(self.name, arguments, evaluator.context.location)


class ExtentsFunction(expr.HostFunction):
    """extents(node) and extents(node, port): the bounds an adaptor reports for an updated node."""

    def __init__(self, scope):
        self.scope = scope
        self.node = None
        self.port = 0

    def check(self, call, checker):
        expected = [['node'], ['node', 'port']]
        if call.named or len(call.arguments) not in (1, 2) or not isinstance(call.arguments[0], syntax.Name):
            raise checker.fault('EXPR_ARGUMENTS', 'extents takes a node ID written as a name, and optionally '
                                'an output port number', call, function='extents', expected=expected)
        if len(call.arguments) == 2:
            port = call.arguments[1]
            if not isinstance(port, syntax.Number) or not isinstance(port.value, int):
                raise checker.fault('EXPR_ARGUMENTS', 'the output port of extents is a whole number written '
                                    'as a literal', port, function='extents', expected=expected)
            self.port = port.value
        self.node = call.arguments[0].name
        self.scope.require_extents(checker, call)
        self.scope.require_node(checker, call.arguments[0], self.node, self.port)
        return expr.Info(BOX, expr.OBSERVED, [('node', self.node), ('port', self.node, self.port)])

    def evaluate(self, call, evaluator):
        ports = self.scope.port_extents(self.node, evaluator.context)
        if self.port >= len(ports):
            raise expr.ExprFault('INVALID_OUTPUT_PORT', f'node `{self.node}` has no output port {self.port}',
                                 node=self.node, port=self.port, available=len(ports))
        value = ports[self.port]
        if value is None:
            raise expr.ExprFault('EXTENTS_UNAVAILABLE', f'output {self.port} of node `{self.node}` has no '
                                 'spatial bounds', node=self.node, port=self.port)
        return expr.make_box(value[0::2], value[1::2])


class SweepFunction(expr.HostFunction):
    """sweep(a, b, count[, sync]): one scheduled axis, interpolated at each visit."""

    def __init__(self, scope):
        self.scope = scope
        self.axis = None
        self.count = None

    def check(self, call, checker):
        expected = [['value', 'value', 'count'], ['value', 'value', 'count', 'sync']]
        if call.named or len(call.arguments) not in (3, 4):
            raise checker.fault('EXPR_ARGUMENTS', 'sweep takes two ends, a count and optionally a sync name',
                                call, function='sweep', expected=expected)
        first, second = checker.check(call.arguments[0]), checker.check(call.arguments[1])
        checker.require(first, call.arguments[0], SCALAR, VECTOR)
        checker.require(second, call.arguments[1], first.type)
        self.count = self.scope.sweep_count(checker, call.arguments[2])
        sync = None
        if len(call.arguments) == 4:
            name = call.arguments[3]
            if not isinstance(name, syntax.String) or not name.value:
                raise checker.fault('EXPR_ARGUMENTS', 'the sync name of sweep is a nonempty string literal',
                                    name, function='sweep', expected=expected)
            sync = name.value
        self.axis = self.scope.sweep_axis(checker, call, self.count, sync)
        info = checker.combine(first.type, first, second)
        return expr.Info(first.type, max(expr.VISIT, info.phase),
                         info.dependencies | {('axis', self.axis), ('sweep', self.axis)})

    def evaluate(self, call, evaluator):
        first = evaluator.evaluate(call.arguments[0])
        second = evaluator.evaluate(call.arguments[1])
        return expr.functions.lerp(first, second, sweep_fraction(self.axis, self.count, evaluator.context))


def sweep_fraction(axis, count, state):
    """Where a visit lies between the two ends of a generated axis."""
    index = state.axes.get(axis)
    if type(index) is not int or not 0 <= index < count:
        raise expr.ExprFault('EXPR_PHASE', f'sweep `{axis}` has no position here', variable=axis, phase='visit',
                             accepted=['constant'])
    return 0.5 if count == 1 else index / (count - 1)


def sweep_positions(text):
    """Code-point positions of every sweep( in a text, in the order written."""
    try:
        tokens = syntax.tokenize(text)
    except expr.ExprFault:
        return []
    return [token.position for token, following, before in zip(tokens[:-1], tokens[1:], [None] + tokens[:-2])
            if token.kind == syntax.IDENTIFIER and token.text == 'sweep' and following.text == '('
            and following.kind == syntax.OPERATOR and not (before is not None and before.text == '.'
                                                           and before.kind == syntax.OPERATOR)]


def late_analytic(spec, syncs):
    """An analytic evaluated at the visit: its ends are only known then, or a sweep shares its axis."""
    if not isinstance(spec, dict) or spec.get('type') not in ('linear', 'values'):
        return False
    if isinstance(spec.get('sync'), str) and spec['sync'] in syncs:
        return True
    return spec['type'] == 'linear' and (has_markers(spec.get('start')) or has_markers(spec.get('end')))


def sweep_syncs(document):
    """Sync names used by sweeps anywhere in a document."""
    names = set()
    for _, marker in expression_markers(document):
        if 'sweep' not in marker['$expr']:
            continue
        try:
            tree = syntax.parse(marker['$expr'])
        except expr.ExprFault:
            continue
        names.update(node.arguments[3].value for node in preorder(tree)
                     if isinstance(node, syntax.Call) and node.name == 'sweep' and len(node.arguments) == 4
                     and isinstance(node.arguments[3], syntax.String))
    return names


def late_syncs(document):
    """Sync names of analytics whose ends are only known at the visit."""
    return {spec['sync'] for _, spec in analytic_specifications(document)
            if isinstance(spec.get('sync'), str) and late_analytic(spec, ())}


def sync_names(document):
    """Every sync name a document uses, in its analytics and in its sweeps."""
    return sweep_syncs(document) | {spec['sync'] for _, spec in analytic_specifications(document)
                                    if isinstance(spec.get('sync'), str)}


def analytic_marker(value):
    return isinstance(value, dict) and isinstance(value.get(ANALYTIC), dict)


class Scope(expr.Environment):
    """The names one document offers to its expressions."""

    def __init__(self, document, axes=None, workflow=None, kind='document', adaptor=None):
        self.sections = {name: document.get(name) for name in SECTIONS if isinstance(document.get(name), dict)}
        self.series = set()
        self.kind = kind
        self.adaptor = adaptor or Adaptor()
        limit = document.get('maxStates', 10000)
        self.limit = limit if type(limit) is int and limit >= 1 else 10000
        raw_nodes = document.get('nodes')
        self.nodes = ({node['id']: node.get('filter') for node in raw_nodes
                       if isinstance(node, dict) and isinstance(node.get('id'), str)}
                      if isinstance(raw_nodes, list) else None)
        self.axes = axes if axes is not None else self.declared_axes(document)
        if workflow is None and isinstance(document.get(CARRIED), dict):
            workflow = Scope(document[CARRIED], axes={}, kind='workflow')
        self.workflow = workflow
        self.entries = {}
        self.active = []
        self.checked = {}
        self.sited = {}
        self.sweeps = {}
        self.site = None
        self.positions = []
        self.visit_axes = None

    def declared_axes(self, document):
        axes = {}
        for axis in document.get('sweeps', []) if isinstance(document.get('sweeps'), list) else []:
            if isinstance(axis, dict) and isinstance(axis.get('name'), str):
                axes[axis['name']] = self.axis_values(axis, self.limit)
                if 'series' in axis:
                    self.series.add(axis['name'])
        return axes

    def axis_values(self, axis, limit):
        """Declared values of an axis, or None when they cannot be read here."""
        if isinstance(axis.get('values'), list):
            return axis['values']
        if 'series' not in axis:
            return None
        from schemaxis.core.series import resolve_series
        try:
            return list(resolve_series(axis['series'], limit=limit).positions)
        except SchemaxisError:
            return None

    def resolve(self, name, quoted):
        if not quoted and name in ROOTS:
            return Root(self, name)
        found = [self.entry(section, name) for section in self.sections if name in self.sections[section]]
        if name in self.axes:
            found.append(self.axis(name))
        if not quoted and name == 'time':
            found.append(TimeBinding())
        if not quoted and name == 'dataExtents':
            self.require_extents()
            found.append(DataExtentsBinding(self))
        if len(found) > 1:
            raise expr.ExprFault('EXPR_AMBIGUOUS_NAME', f'`{name}` is defined more than once; qualify it',
                                 name=name, candidates=[binding.label for binding in found])
        return found[0] if found else None

    def available(self):
        names = {section: sorted(entries) for section, entries in self.sections.items()}
        names['sweeps'] = sorted(self.axes)
        return names

    def function(self, name):
        if name == 'extents':
            return ExtentsFunction(self)
        if name == 'sweep':
            return SweepFunction(self)
        from .functions import FUNCTIONS
        if name not in FUNCTIONS.entries:
            return None
        arguments, result, _ = FUNCTIONS.entries[name]
        if 'objectKind' in result or any('objectKind' in spec for spec in arguments.values()):
            return None
        return CatalogueFunction(name, arguments, result)

    def functions(self):
        from .functions import FUNCTIONS
        return sorted(['extents', 'sweep'] + [name for name in FUNCTIONS.entries if self.function(name) is not None])

    def require_extents(self, checker=None, node=None):
        if self.adaptor.extents is not False:
            return
        message = 'this adaptor does not report extents, so extents and dataExtents cannot be used here'
        if checker is not None:
            raise checker.fault('EXTENTS_UNSUPPORTED', message, node, adaptor=self.adaptor.name)
        raise expr.ExprFault('EXTENTS_UNSUPPORTED', message, adaptor=self.adaptor.name)

    def require_node(self, checker, node, name, port):
        if self.nodes is None:
            return
        if name not in self.nodes:
            raise expr.ExprFault('UNKNOWN_NODE', f'there is no node `{name}`', node.position, node.length,
                                 expression=checker.text, node=name, available=sorted(self.nodes))
        count = self.port_count(name)
        if count is not None and port >= count:
            raise expr.ExprFault('INVALID_OUTPUT_PORT', f'node `{name}` has no output port {port}', node.position,
                                 node.length, expression=checker.text, node=name, port=port, available=count)

    def declaration(self, node):
        declarations = self.adaptor.declarations
        return declarations.get(self.nodes.get(node)) if declarations and self.nodes else None

    def port_count(self, node):
        """Number of output ports when the declaration fixes it, else None."""
        declaration = self.declaration(node)
        if not isinstance(declaration, dict):
            return None
        count = declaration.get('outputPorts', (declaration.get('coverage') or {}).get('outputPorts'))
        return count if type(count) is int and count > 0 else None

    def loaders(self):
        """Data-loading nodes in document order, or None when the declarations are not known."""
        if self.nodes is None or self.adaptor.declarations is None:
            return None
        return [node for node in self.nodes if (self.declaration(node) or {}).get('loadsData') is True]

    def port_extents(self, node, state):
        """Recorded extents of every output port of an updated node."""
        observation = state.observations.get(node)
        if observation is None:
            raise expr.ExprFault('OBSERVATION_UNAVAILABLE', f'node `{node}` has not been updated', node=node)
        if isinstance(observation.get('extentsFault'), dict):
            fault = observation['extentsFault']
            raise expr.ExprFault(fault.get('code', 'EXTENTS_UNAVAILABLE'),
                                 fault.get('message', f'node `{node}` could not be loaded'), node=node)
        if 'extents' in observation:
            return observation['extents']
        return [observation.get('bounds')]

    def sweep_count(self, checker, node):
        info = checker.check(node)
        value = self.constant(checker, node, info)
        if type(value) is not int or not 1 <= value <= self.limit:
            shown = None if value is expr.MISSING else value
            raise checker.fault('SWEEP_COUNT', 'the count of a sweep is a constant whole number from 1 to '
                                f'{self.limit}', node, count=shown, limit=self.limit)
        return value

    def constant(self, checker, node, info):
        """Value of a constant sub-expression while it is checked, else MISSING."""
        if info.known is not expr.MISSING:
            return info.known
        if not Profile(info.dependencies).constant:
            return expr.MISSING
        evaluator = expr.Evaluator(types.SimpleNamespace(text=checker.text), State())
        return expr.to_json(evaluator.evaluate(node))

    def sweep_axis(self, checker, call, count, sync):
        if self.site is None:
            raise checker.fault('SWEEP_PLACEMENT', 'a sweep is scheduled from a place in a document; this '
                                'expression has none', call, destination=None)
        axis = ('sync:' + sync if sync
                else f'sweep:{self.site}#{self.positions.index(call.position)}')
        try:
            self.register_axis(axis, count, sync, 'sweep')
        except expr.ExprFault as fault:
            fault.observed.setdefault('expression', checker.text)
            raise fault.locate(call)
        return axis

    def register_axis(self, axis, count, sync, kind):
        known = self.sweeps.get(axis)
        if known is not None and known['count'] != count:
            raise expr.ExprFault('ANALYTIC_LENGTH_MISMATCH', f'everything synchronised as `{sync}` has the '
                                 'same count', expected=known['count'], actual=count, sync=sync)
        if known is None:
            self.sweeps[axis] = {'count': count, 'sync': sync, 'kind': kind}

    def axis(self, name):
        if name not in self.axes:
            return None
        if name in self.series:
            return AxisBinding(name, SCALAR)
        label = f'sweeps.{name}'
        if label in self.active:
            chain = self.active[self.active.index(label):] + [label]
            raise expr.ExprFault('EXPR_CYCLE', 'entries refer to each other in a loop: ' + ' → '.join(chain),
                                 chain=chain)
        self.active.append(label)
        try:
            kinds = {self.describe(value)[0] for value in self.axes[name] or []} or {UNKNOWN}
        finally:
            self.active.pop()
        return AxisBinding(name, kinds.pop() if len(kinds) == 1 else UNKNOWN)

    def entry(self, section, key):
        if key not in self.sections.get(section, {}):
            return None
        identity = (section, key)
        if identity in self.entries:
            return self.entries[identity]
        label = f'{section}.{key}'
        if label in self.active:
            chain = self.active[self.active.index(label):] + [label]
            raise expr.ExprFault('EXPR_CYCLE', 'entries refer to each other in a loop: ' + ' → '.join(chain),
                                 chain=chain)
        self.active.append(label)
        try:
            raw = self.sections[section][key]
            path = pointer(pointer('', section), key)
            kind, known, shape = self.describe(raw, path)
            binding = EntryBinding(self, section, key, kind, known, shape, self.profile(raw, path))
        finally:
            self.active.pop()
        self.entries[identity] = binding
        return binding

    def check(self, text, site=None):
        positions = sweep_positions(text) if isinstance(text, str) else []
        cache, key = (self.sited, (site, text)) if positions else (self.checked, text)
        if key not in cache:
            previous = self.site, self.positions
            self.site, self.positions = site, positions
            try:
                cache[key] = expr.check(text, self)
            finally:
                self.site, self.positions = previous
        return cache[key]

    def checked_at(self, text, location, site=None):
        try:
            return self.check(text, site)
        except expr.ExprFault as fault:
            raise_fault(fault, location, 'input')

    def profile(self, value, path=None):
        return Profile(self.dependencies(value, path))

    def reference(self, value):
        """Entry a $document marker reads: one of this document's or, with scope workflow, the envelope's."""
        target = value.get('$document') if isinstance(value, dict) else None
        if not isinstance(target, str) or not target.startswith('/') or set(value) - {'$document', 'scope'}:
            return None
        parts = [part.replace('~1', '/').replace('~0', '~') for part in target.split('/')[1:]]
        scope = self.workflow if value.get('scope') == 'workflow' else self if 'scope' not in value else None
        if scope is None or len(parts) != 2 or parts[0] not in SECTIONS:
            return None
        return scope.entry(parts[0], parts[1])

    def dependencies(self, value, path=None):
        if isinstance(value, list):
            return frozenset().union(*[self.dependencies(item, extend(path, index))
                                       for index, item in enumerate(value)])
        if not isinstance(value, dict):
            return frozenset()
        if is_expression(value):
            return self.check(value['$expr'], extend(path, '$expr')).dependencies
        if '$document' in value:
            binding = self.reference(value)
            return binding.dependencies if binding is not None else frozenset()
        found = set()
        if isinstance(value.get('$sweep'), str):
            found.add(('axis', value['$sweep']))
        if '$time' in value:
            found.add(TIME)
        if ANALYTIC in value:
            found.update(self.analytic_dependencies(value, path))
        for marker in ('$observe', '$sample'):
            if isinstance(value.get(marker), str):
                found.add(('node', value[marker]))
        if '$artifact' in value or '$fill' in value or ('$value' in value and 'path' in value):
            found.add(PENDING)
            source = value.get('$artifact', value.get('$value'))
            if isinstance(source, str) and '$fill' not in value:
                found.add(('awaits', source))
        return frozenset(found).union(*[self.dependencies(item, extend(path, key))
                                        for key, item in value.items()])

    def analytic_axis(self, value, path):
        """Axis and count of an analytic that is evaluated at the visit, or None."""
        spec = value[ANALYTIC] if analytic_marker(value) else {}
        count = spec.get('count') if spec.get('type') != 'values' else (
            len(spec['values']) if isinstance(spec.get('values'), list) else None)
        if path is None or type(count) is not int or not 1 <= count <= self.limit:
            return None
        sync = spec.get('sync') if isinstance(spec.get('sync'), str) and spec.get('sync') else None
        return ('sync:' + sync if sync else f'sweep:{extend(path, ANALYTIC)}#0'), count, sync

    def analytic_dependencies(self, value, path):
        axis = self.analytic_axis(value, path)
        if axis is None:
            return {('axis', ANALYTIC)}
        self.register_axis(axis[0], axis[1], axis[2], 'analytic')
        return {('axis', axis[0]), ('sweep', axis[0])}

    def analytic_value(self, value, path, state):
        """Value at one visit of an analytic whose ends are only known then."""
        axis = self.analytic_axis(value, path)
        spec = value[ANALYTIC]
        if axis is None or spec.get('type') not in ('linear', 'values'):
            raise SchemaxisError(Fault('INVALID_ANALYTIC', 'only a linear analytic may have ends that are '
                                       'known at the visit', state.location, 'pipeline'))
        try:
            fraction = sweep_fraction(axis[0], axis[1], state)
        except expr.ExprFault as fault:
            raise_fault(fault, state.location, 'pipeline')
        inside = extend(path, ANALYTIC)
        if spec['type'] == 'values':
            return self.part_value(spec['values'][state.axes[axis[0]]], extend(inside, 'values'), state)
        start = self.part_value(spec.get('start'), extend(inside, 'start'), state)
        end = self.part_value(spec.get('end'), extend(inside, 'end'), state)
        if axis[1] == 1 and start != end:
            raise SchemaxisError(Fault('INVALID_ANALYTIC', 'one sample requires equal endpoints',
                                       state.location, 'pipeline', observed={'start': start, 'end': end}))
        return interpolate(start, end, 0 if axis[1] == 1 else fraction, state.location)

    def part_value(self, value, path, state):
        from .pipeline import evaluate
        axes = state.axes if self.visit_axes is None else self.visit_axes
        return evaluate(value, axes, state.observations, state.time, state.location, state.sampler, self, path)

    def describe(self, value, path=None):
        """Type, known value and declared shape of an entry (section 5.1)."""
        if not has_markers(value):
            return expr.classify(value), value, None
        if not isinstance(value, dict):
            return UNKNOWN, expr.MISSING, None
        if is_expression(value):
            checked = self.check(value['$expr'], extend(path, '$expr'))
            return checked.type, checked.known, checked.shape
        if '$document' in value:
            binding = self.reference(value)
            return (UNKNOWN, expr.MISSING, None) if binding is None else (binding.type, binding.known, binding.shape)
        if '$expr' in value:
            operation = value['$expr'].get('op') if isinstance(value['$expr'], dict) else None
            return (SCALAR if operation in ARITHMETIC else UNKNOWN), expr.MISSING, None
        if '$calc' in value:
            return self.calculation_type(value), expr.MISSING, None
        if '$time' in value:
            return SCALAR, expr.MISSING, None
        if '$observe' in value:
            return (BOX if value.get('path') == ['bounds'] else UNKNOWN), expr.MISSING, None
        if '$sweep' in value:
            return self.axis_type(value), expr.MISSING, None
        if analytic_marker(value):
            return self.analytic_type(value, path), expr.MISSING, None
        name = value.get('$call', value.get('$value') if 'path' not in value else None)
        function = self.function(name) if isinstance(name, str) and name not in ('extents', 'sweep') else None
        if function is not None:
            return declared_type(function.result), expr.MISSING, DeclaredShape(function.result)
        return UNKNOWN, expr.MISSING, None

    def analytic_type(self, value, path=None):
        spec = value[ANALYTIC]
        if spec.get('type') == 'orbit':
            return JSON
        inside = extend(path, ANALYTIC)
        if spec.get('type') == 'values' and isinstance(spec.get('values'), list):
            samples = [(sample, extend(extend(inside, 'values'), index))
                       for index, sample in enumerate(spec['values'])]
        else:
            samples = [(spec.get(end), extend(inside, end)) for end in ('start', 'end')]
        kinds = {self.describe(sample, where)[0] for sample, where in samples}
        return kinds.pop() if len(kinds) == 1 else UNKNOWN

    def calculation_type(self, value):
        operation, arguments = value.get('$calc'), value.get('args')
        if operation in VECTOR_CALCULATIONS:
            return VECTOR
        if not isinstance(arguments, list) or len(arguments) != 2:
            return UNKNOWN
        kinds = [self.describe(argument)[0] for argument in arguments]
        if UNKNOWN in kinds:
            return UNKNOWN
        if kinds == [SCALAR, SCALAR]:
            return SCALAR
        if VECTOR in kinds and all(kind in (SCALAR, VECTOR) for kind in kinds):
            return VECTOR
        return JSON

    def axis_type(self, value):
        values = self.axes.get(value.get('$sweep'))
        if not values:
            return UNKNOWN
        kinds = set()
        for item in values:
            for part in value.get('path', []):
                inside = (isinstance(item, dict) and part in item) or (
                    isinstance(item, list) and type(part) is int and 0 <= part < len(item))
                if not inside:
                    return UNKNOWN
                item = item[part]
            kinds.add(expr.classify(item))
        return kinds.pop() if len(kinds) == 1 else UNKNOWN

    def entry_value(self, section, key, state):
        return self.part_value(self.sections[section][key], pointer(pointer('', section), key), state)

    def evaluate(self, text, state, site=None):
        """JSON value of a string expression at one visit."""
        try:
            checked = self.check(text, site)
        except expr.ExprFault as fault:
            raise_fault(fault, state.location, 'input')
        try:
            return copy.deepcopy(expr.to_json(expr.evaluate(checked, context=state)))
        except expr.ExprFault as fault:
            raise_fault(fault, state.location, 'pipeline')

    def causes(self, value, path=None):
        """Why a value is late: chains of names ending at what is only known later."""
        if isinstance(value, list):
            return [cause for index, item in enumerate(value) for cause in self.causes(item, extend(path, index))]
        if not isinstance(value, dict):
            return []
        if is_expression(value):
            checked = self.check(value['$expr'], extend(path, '$expr'))
            return self.tree_causes(checked.text, checked.tree)
        if '$document' in value:
            binding = self.reference(value)
            return [] if binding is None else self.entry_causes(binding)
        found = []
        if isinstance(value.get('$sweep'), str):
            found.append(Cause(['$sweep ' + value['$sweep']], expr.VISIT, 'axis', value['$sweep']))
        if '$time' in value:
            found.append(Cause(['time'], expr.VISIT, 'time', None))
        if analytic_marker(value) and self.analytic_axis(value, path):
            found.append(Cause([ANALYTIC], expr.VISIT, 'sweep', self.analytic_axis(value, path)[0]))
        for marker in ('$observe', '$sample'):
            if isinstance(value.get(marker), str):
                found.append(Cause([f'{marker} {value[marker]}'], expr.OBSERVED, 'node', value[marker]))
        return found + [cause for key, item in value.items() for cause in self.causes(item, extend(path, key))]

    def tree_causes(self, text, tree):
        found = []
        for node in preorder(tree):
            info = node.info
            if info is None:
                continue
            source = text[node.position:node.position + node.length]
            if isinstance(info.target, SweepFunction):
                found.append(Cause([source], expr.VISIT, 'sweep', info.target.axis))
            elif isinstance(info.target, ExtentsFunction):
                found.append(Cause([source], expr.OBSERVED, 'node', info.target.node))
            elif isinstance(info.binding, AxisBinding):
                found.append(Cause([source], expr.VISIT, 'axis', info.binding.name))
            elif isinstance(info.binding, TimeBinding):
                found.append(Cause([source], expr.VISIT, 'time', None))
            elif isinstance(info.binding, DataExtentsBinding):
                found.append(Cause([source], expr.OBSERVED, 'data', None))
            elif isinstance(info.binding, EntryBinding):
                found.extend(self.entry_causes(info.binding))
        return found

    def entry_causes(self, binding):
        """Why an entry is late, with its own name at the head of each chain."""
        path = pointer(pointer('', binding.section), binding.key)
        return [Cause([binding.key] + cause.chain, cause.phase, cause.kind, cause.detail)
                for cause in binding.scope.causes(binding.scope.sections[binding.section][binding.key], path)]

    def axis_uses(self, value, path=None):
        """Axes a value reads, in the order they are first used."""
        found = []
        self.collect_axes(value, path, found)
        return found

    def collect_axes(self, value, path, found):
        if isinstance(value, list):
            for index, item in enumerate(value):
                self.collect_axes(item, extend(path, index), found)
        elif is_expression(value):
            for node in preorder(self.check(value['$expr'], extend(path, '$expr')).tree):
                info = node.info
                if info is None:
                    continue
                if isinstance(info.target, SweepFunction):
                    first_use(found, info.target.axis)
                elif isinstance(info.binding, AxisBinding):
                    first_use(found, info.binding.name)
                elif isinstance(info.binding, EntryBinding):
                    binding = info.binding
                    binding.scope.collect_axes(binding.scope.sections[binding.section][binding.key],
                                               pointer(pointer('', binding.section), binding.key), found)
        elif isinstance(value, dict) and '$document' in value:
            binding = self.reference(value)
            if binding is not None:
                binding.scope.collect_axes(binding.scope.sections[binding.section][binding.key],
                                           pointer(pointer('', binding.section), binding.key), found)
        elif isinstance(value, dict):
            if isinstance(value.get('$sweep'), str):
                first_use(found, value['$sweep'])
            axis = self.analytic_axis(value, path) if analytic_marker(value) else None
            if axis is not None:
                self.register_axis(axis[0], axis[1], axis[2], 'analytic')
                first_use(found, axis[0])
            for key, item in value.items():
                self.collect_axes(item, extend(path, key), found)


def first_use(found, axis):
    if axis not in found:
        found.append(axis)


def preorder(tree):
    """Nodes of a syntax tree in the order they are written."""
    pending = [tree]
    while pending:
        node = pending.pop()
        yield node
        pending.extend(reversed(syntax.children(node)))


class Cause:
    """One reason a value is late: the names leading to it and what it waits for."""

    def __init__(self, chain, phase, kind, detail):
        self.chain = chain
        self.phase = phase
        self.kind = kind
        self.detail = detail

    def reason(self):
        if self.kind == 'node':
            return f'it is only known after node `{self.detail}` has been updated'
        if self.kind == 'data':
            return 'it is only known after the data-loading nodes have been updated'
        if self.kind == 'time':
            return 'it changes with time'
        return 'it changes at each visit'


def extents_capability(document, adaptor=None):
    """Whether the adaptor of a document declares an extents provider; None when it is not known."""
    from .adaptors import registry
    if adaptor is None:
        version = document.get('version') if isinstance(document, dict) else None
        route = registry.routes().get(version) if isinstance(version, str) else None
        if route is None:
            return None
        adaptor = route[0]
    return bool(registry.metadata(adaptor).get('extents'))


def recorded_extents(results):
    """Recorded form of a provider's results: six numbers, the invalid six for empty, None when not spatial."""
    recorded = []
    for result in results:
        status = result.get('status') if isinstance(result, dict) else None
        if status == 'ok' and is_six(result.get('bounds')) and all(math.isfinite(x) for x in result['bounds']):
            recorded.append(list(result['bounds']))
        elif status == 'empty':
            recorded.append(list(INVALID_SIX))
        elif status == 'notSpatial':
            recorded.append(None)
        else:
            raise SchemaxisError(Fault('INVALID_EXTENTS', 'an extents provider reports ok with six finite numbers, '
                                       'empty or notSpatial for each output port', '$', 'pipeline',
                                       observed={'result': result if isinstance(result, (dict, list, str)) else None}))
    return recorded


def check_static(document, base=''):
    """Refuse late values where a document is fixed at planning: axes, times and limits."""
    found = [(path, marker) for key in ('sweeps', 'times', 'maxStates', 'maxPublications') if key in document
             for path, marker in expression_markers(document[key], pointer('', key))]
    for path, spec in analytic_specifications(document):
        late = ('start', 'end') if spec.get('type') == 'linear' else ()
        found.extend(item for key, value in spec.items() if key not in late
                     for item in expression_markers(value, pointer(path, key)))
    if not found:
        return
    scope = Scope(document)
    for path, marker in found:
        try:
            misuse(scope, marker, path, STATIC, '$' + base + path,
                   f'`{path}`, which is fixed when the document is planned')
        except expr.ExprFault as fault:
            raise_fault(fault, '$' + base + path, 'input')


def analytic_specifications(value, path=''):
    """Every analytic of a value with the pointer of its specification."""
    if analytic_marker(value):
        yield pointer(path, ANALYTIC), value[ANALYTIC]
    if isinstance(value, dict):
        for key, item in value.items():
            yield from analytic_specifications(item, pointer(path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from analytic_specifications(item, pointer(path, index))


def extend(path, key):
    return None if path is None else pointer(path, key)


def interpolate(start, end, fraction, location):
    if isinstance(start, list) and isinstance(end, list) and len(start) == len(end) and start:
        return [interpolate(a, b, fraction, location) for a, b in zip(start, end)]
    numbers = all(type(x) in (int, float) and math.isfinite(x) for x in (start, end))
    result = (1 - fraction) * start + fraction * end if numbers else math.nan
    if not math.isfinite(result):
        raise SchemaxisError(Fault('INVALID_ANALYTIC', 'linear endpoints need finite scalars or matching vectors',
                                   location, 'pipeline', observed={'start': start, 'end': end}))
    return result


def misuse(scope, value, path, kind, location, label):
    """Refuse a value whose dependencies its destination does not accept (section 8.2)."""
    profile = scope.profile(value, path)
    if kind in (OPTION, ENTRY) or (profile.constant and not profile.sweeps):
        return
    if kind == SCENE and not profile.sweeps:
        return
    causes = scope.causes(value, path)
    wanted = 'sweep' if kind == SCENE else None
    cause = next((c for c in causes if (c.kind == wanted if wanted else c.phase == profile.phase)), None)
    cause = cause or (causes[0] if causes else Cause([label], profile.phase, 'axis', None))
    chain = ' → '.join(cause.chain)
    observed = {'variable': cause.chain[0], 'phase': expr.PHASES[profile.phase], 'chain': cause.chain,
                'destination': label}
    if kind == SCENE:
        raise SchemaxisError(Fault('SWEEP_PLACEMENT', f'`{cause.chain[0]}` cannot be used in {label}: a sweep '
                                   f'adds scheduled visits, which this value does not accept ({chain})',
                                   location, 'input', observed=observed))
    code = 'DYNAMIC_CONSTRUCTOR' if kind == CONSTRUCTOR else 'EXPR_PHASE'
    raise SchemaxisError(Fault(code, f'`{cause.chain[0]}` cannot be used in {label}: {cause.reason()} ({chain})',
                               location, 'input', observed={**observed, 'accepted': ['constant']}))


def pointer(path, key):
    return path + '/' + str(key).replace('~', '~0').replace('/', '~1')


class Folder:
    """Checks every string expression and replaces constant markers by values."""

    def __init__(self, document, evidence=None, base='', workflow=None, axes=None):
        version = document.get('version')
        self.envelope = workflow is None and isinstance(version, str) and version.startswith('schemaxis.workflow/')
        self.scope = Scope(document, workflow=workflow, kind='workflow' if self.envelope else 'document',
                           adaptor=Adaptor(extents_capability(document)))
        self.evidence = evidence
        self.base = base
        self.study = axes
        self.axes = axes.get(base) if axes is not None else None
        self.scope.visit_axes = self.axes
        if self.envelope:
            self.scope.workflow = self.scope

    def fold(self, value, path):
        if isinstance(value, list):
            return [self.fold(item, pointer(path, index)) for index, item in enumerate(value)]
        if not isinstance(value, dict):
            return value
        if self.envelope and OPERATION_DOCUMENT.fullmatch(path):
            inner = Folder(value, self.evidence, self.base + path, self.scope, self.study)
            return inner.carry(inner.fold(value, ''))
        location = '$' + self.base + path
        if is_expression(value):
            return self.expression(value, location, path)
        folded = {key: self.fold(item, pointer(path, key)) for key, item in value.items()}
        if '$value' in folded and 'path' not in folded and set(folded) == {'$value', 'args'}:
            folded = {'$call': folded['$value'], 'args': folded['args']}
        arguments = folded.get('$expr') if '$expr' in folded else folded.get('args')
        if has_markers(arguments):
            return folded
        if '$call' in folded and set(folded) == {'$call', 'args'} and isinstance(arguments, dict):
            return self.call(folded, location)
        if '$expr' in folded and set(folded) == {'$expr'}:
            return compose(folded['$expr'], location)
        return folded

    def carry(self, folded):
        """Give an operation the envelope entries its late expressions still read.

        The operation is planned on its own, so what is constant in the envelope
        travels with it as values under a reserved key.
        """
        needed = set()
        for path, marker in expression_markers(folded):
            try:
                dependencies = self.scope.check(marker['$expr'], pointer(path, '$expr')).dependencies
            except expr.ExprFault:
                continue
            needed.update(item[2:] for item in dependencies if item[:2] == ('entry', 'workflow'))
        folded = {key: item for key, item in folded.items() if key != CARRIED}
        if not needed:
            return folded
        envelope, carried = self.scope.workflow, {}
        for section, key in sorted(needed):
            carried.setdefault(section, {})[key] = self.carried(envelope, section, key)
        return {**folded, CARRIED: carried}

    def carried(self, envelope, section, key):
        """An envelope entry as an operation takes it: its value when it is known here, else as authored.

        At a visit of a study the envelope's sweeps stand at a position, so an
        entry that waits only for them is a value too.
        """
        profile = envelope.entry(section, key).profile
        location = '$' + pointer(pointer('', section), key)
        if profile.constant:
            return envelope.entry_value(section, key, State(location=location))
        if self.study is not None and study_evaluable(profile):
            try:
                return envelope.entry_value(section, key, State(self.study.get(''), location=location))
            except SchemaxisError as error:
                if error.fault.code != 'EXPR_PHASE':
                    raise
        return copy.deepcopy(envelope.sections[section][key])

    def expression(self, value, location, path):
        if set(value) != {'$expr'}:
            raise SchemaxisError(Fault('INVALID_EXPRESSION', 'Expression marker must be the entire value',
                                       location, 'input'))
        option = bool(OPTION_VALUE.match(path))
        try:
            profile = self.scope.profile(value, path)
        except expr.ExprFault as fault:
            raise_fault(fault, location, 'input')
        if profile.constant and not profile.sweeps:
            result = self.scope.evaluate(value['$expr'], State(location=location), pointer(path, '$expr'))
        elif self.axes is not None and study_evaluable(profile):
            try:
                result = self.scope.evaluate(value['$expr'], State(self.axes, location=location),
                                             pointer(path, '$expr'))
            except SchemaxisError as error:
                if error.fault.code != 'EXPR_PHASE':
                    raise
                return value
        else:
            return value
        if option and is_invalid_box(result):
            refuse_invalid_box(value['$expr'], location, 'input')
        if self.evidence is not None:
            self.evidence.append({'location': location, 'expression': value['$expr'],
                                  'effectiveValue': copy.deepcopy(result)})
        return result

    def call(self, marker, location):
        if self.scope.function(marker['$call']) is None:
            return marker
        from .functions import FUNCTIONS
        return FUNCTIONS.invoke(marker['$call'], marker['args'], location)


def expression_markers(value, path=''):
    """Every string expression marker of a value with its pointer."""
    if is_expression(value):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from expression_markers(item, pointer(path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from expression_markers(item, pointer(path, index))


def has_expressions(value):
    if isinstance(value, dict):
        return is_expression(value) or any(has_expressions(item) for item in value.values())
    if isinstance(value, list):
        return any(has_expressions(item) for item in value)
    return False


def study_evaluable(profile):
    """A value a study can compute before the application runs: it waits only for axes."""
    return not (profile.nodes or profile.data or profile.time or profile.pending)


def refuse_late(document, base=''):
    """Refuse values that are still late in a document whose adaptor takes them fixed before it runs."""
    scope = Scope(document, adaptor=Adaptor(extents_capability(document)))
    body = {key: value for key, value in document.items() if key not in (*SECTIONS, 'sweeps', CARRIED)}
    for path, marker in expression_markers(body):
        try:
            if scope.profile(marker, path).pending:
                continue
            misuse(scope, marker, path, STATIC, '$' + base + path,
                   'a document of this adaptor, whose values are fixed before it runs')
        except expr.ExprFault as fault:
            raise_fault(fault, '$' + base + path, 'input')


def fold_constants(document, evidence=None, axes=None):
    """Resolve what is constant; late markers stay for evaluation at a visit."""
    return Folder(document, evidence, axes=axes).fold(document, '')
