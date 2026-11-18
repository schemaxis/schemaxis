# Copyright (C) 2026 David L. F. Gaden.
"""Load the extents spatial entries or an ad-hoc expression depend on, without running anything downstream.

The host takes the nodes the entries read and their upstream closure, plans only
those, and asks the document's adaptor for their extents in its own process. A
node that fails is reported as a fault; nodes that do not depend on it are
still loaded (docs/design/expression-language.md, appendix A.4).
"""
import copy
import json
import re
import tempfile
from pathlib import Path

from schemaxis.core.faults import SchemaxisError
from . import expressions
from .errors import fail
from .expressions import SECTIONS, pointer
from .context import compile_objects
from .spatial_actions import Draft, Expression, Visit, fault_of, records

SWEEP_NODE = re.compile(r'^sweep:/nodes/([0-9]+)/')
APPLICATION_FAULTS = ('INTERPRETER_NOT_FOUND', 'INTERPRETER_UNUSABLE', 'UNSUPPORTED_RUNTIME', 'RUNNER_TIMED_OUT',
                      'RUNNER_CANCELLED')


def sources(node):
    """Node IDs a raw node reads through its inputs."""
    found = []
    inputs = node.get('inputs')
    for value in inputs.values() if isinstance(inputs, dict) else []:
        for source in value if isinstance(value, list) else [value]:
            identity = source.get('node') if isinstance(source, dict) else source
            if isinstance(identity, str):
                found.append(identity)
    return found


class Closure:
    """The part of a document that loading some nodes needs, and nothing else."""

    def __init__(self, member):
        self.member = member
        self.scope = member.scope
        self.lifted = compile_objects(member.document)
        nodes = self.lifted.get('nodes')
        self.raw = [node for node in nodes if isinstance(node, dict) and isinstance(node.get('id'), str)] \
            if isinstance(nodes, list) else []
        self.index = {node['id']: index for index, node in enumerate(nodes)
                      if isinstance(node, dict) and isinstance(node.get('id'), str)} if isinstance(nodes, list) else {}
        self.by_id = {node['id']: node for node in self.raw}

    def profile(self, node):
        path = pointer(pointer(pointer('', 'nodes'), self.index[node]), 'options')
        return self.scope.profile(self.by_id[node].get('options', {}), path)

    def upstream(self, roots):
        """Roots and everything they read, or the fault that stops them being planned."""
        found, pending = [], list(roots)
        while pending:
            node = pending.pop()
            if node in found:
                continue
            if node not in self.by_id:
                fail('UNKNOWN_NODE', 'dependency does not exist', node, available=sorted(self.by_id))
            found.append(node)
            try:
                pending.extend(sorted(self.profile(node).nodes))
            except expressions.expr.ExprFault as fault:
                expressions.raise_fault(fault, self.member.location(f'/nodes/{self.index[node]}/options'), 'input')
            pending.extend(sources(self.by_id[node]))
        return [node for node in self.by_id if node in found]

    def document(self, nodes, envelope):
        """A document holding only these nodes and the entries their options read."""
        source = self.lifted
        result = {key: copy.deepcopy(source[key]) for key in ('version', 'sweeps', 'times', 'maxStates') if key in source}
        result['nodes'] = [copy.deepcopy(self.by_id[node]) for node in nodes]
        needed, carried = set(), set()
        for node in nodes:
            entries = self.profile(node).entries
            needed.update(item[1:] for item in entries if item[0] == 'document')
            carried.update(item[1:] for item in entries if item[0] == 'workflow')
        for section, key in sorted(needed):
            result.setdefault(section, {})[key] = copy.deepcopy(self.scope.sections[section][key])
        for section, key in sorted(carried):
            constant = envelope.scope.entry(section, key).profile.constant
            result.setdefault(expressions.CARRIED, {}).setdefault(section, {})[key] = (
                envelope.scope.entry_value(section, key, expressions.State(location=envelope.location()))
                if constant else copy.deepcopy(envelope.scope.sections[section][key]))
        return result

    def indices(self, nodes, indices):
        """State positions with sweep axes renamed to where their nodes sit in the smaller document."""
        moved = {self.index[node]: position for position, node in enumerate(nodes)}
        result = {}
        for axis, position in indices.items():
            match = SWEEP_NODE.match(axis)
            if match and int(match.group(1)) in moved:
                axis = f'sweep:/nodes/{moved[int(match.group(1))]}/' + axis[match.end():]
            result[axis] = position
        return result


def wanted_nodes(draft, member, identities, expression=None):
    """Nodes the requested entries or expression depend on, in document order."""
    scope, found = member.scope, set()
    if expression is not None:
        if expression.fault is not None:
            return []
        found.update(expression.profile.nodes)
        if expression.profile.data:
            found.update(scope.loaders() or [])
        return [node for node in scope.nodes or {} if node in found]
    if identities is None:
        chosen = member.entries()
    else:
        chosen = [(identity['section'], identity['key']) for identity in identities
                  if draft.find(identity) is member]
    for section, key in chosen:
        try:
            binding = scope.entry(section, key)
        except expressions.expr.ExprFault:
            continue
        found.update(binding.profile.nodes)
        if binding.profile.data:
            found.update(scope.loaders() or [])
    return [node for node in scope.nodes or {} if node in found]


def visit_of(master, selection, state):
    """The visit of a selection that a state names; omitted positions are 0."""
    time_index, indices = state['timeIndex'], state['indices']
    if time_index >= len(master.times) or any(
            indices.get(axis, 0) >= len(master.axes[axis]) for axis in selection.axes):
        fail('INVALID_SELECTION', 'the state is outside the planned visits', '$.state',
             sweeps={axis: len(master.axes[axis]) for axis in selection.axes}, times=len(master.times))
    coordinates = {axis: indices.get(axis, 0) for axis in selection.axes}
    return {'time': master.times[time_index], 'timeIndex': time_index, 'indices': coordinates,
            'sweeps': {axis: copy.deepcopy(master.axes[axis][coordinates[axis]]) for axis in selection.axes}}


def failed_node(master, error):
    """The node a fault belongs to, read from its location."""
    location = error.fault.location if isinstance(error.fault.location, str) else ''
    for separator in ('.', '/'):
        candidate = location.split(separator)[0]
        if candidate in master.nodes:
            return candidate
    return None


def depends(master, node, target):
    """Whether a node is the target or reads it, directly or not."""
    pending, seen = [node], set()
    while pending:
        current = pending.pop()
        if current == target:
            return True
        if current not in seen:
            seen.add(current)
            pending.extend(master.nodes[current]['dependencies'])
    return False


def collect(master, backend, roots, state):
    """Extents of every output port of the roots; a failing node faults only what reads it."""
    from .pipeline import RuntimeClosure
    remaining, faults, observations = list(roots), {}, {}
    while remaining:
        active = RuntimeClosure(master, backend)
        try:
            selection = active.activate(remaining)
            observations = active.apply(visit_of(master, selection, state))['observations']
            break
        except SchemaxisError as error:
            culprit = failed_node(master, error)
            lost = [node for node in remaining if culprit is None or depends(master, node, culprit)]
            faults.update({node: fault_of(error) for node in lost})
            remaining = [node for node in remaining if node not in lost]
        finally:
            if not active.closed:
                try:
                    active.close()
                except SchemaxisError:
                    pass
    result = []
    for node in roots:
        if node in faults:
            result.append({'node': node, 'port': 0, 'status': 'fault', 'fault': faults[node]})
            continue
        observation = observations[node]
        ports = observation['extents'] if 'extents' in observation else [observation.get('bounds')]
        for port, value in enumerate(ports):
            if value is None:
                result.append({'node': node, 'port': port, 'status': 'notSpatial'})
            elif expressions.is_invalid_box(value):
                result.append({'node': node, 'port': port, 'status': 'empty'})
            else:
                result.append({'node': node, 'port': port, 'status': 'ok', 'bounds': list(value)})
    return result


def execute_native(document, roots, state, directory):
    """Inside the application: load the roots and write their extents."""
    from .adaptors import registry
    from .artifacts import atomic_json
    provider = registry.resolve(document)[0]
    master, backend = registry.binding(registry.metadata(provider)['extents']['native'])(document)
    atomic_json(Path(directory) / 'extents.json', {'extents': collect(master, backend, roots, state)})


def native_extents(document, roots, state, locations, timeout, directory):
    """Plan on the host, then run the load in the adaptor's application."""
    from .adaptors import registry
    from .artifacts import atomic_json, runtime_archive
    from .configuration import locations as configured_locations
    from .dispatch import SubprocessRunner
    provider = registry.resolve(document)[0]
    setup = registry.binding(registry.metadata(provider)['extents']['setup'])
    master, interpreter, arguments = setup(document, configured_locations(locations or {}))
    visit_of(master, master.select(roots), state)
    directory = Path(directory).absolute()
    directory.mkdir(parents=True, exist_ok=True)
    atomic_json(directory / 'authored.json', document)
    (directory / 'runtime.zip').write_bytes(runtime_archive())
    runner = SubprocessRunner(interpreter, directory, arguments=arguments, timeout=timeout)
    lowered = {**master.document, 'version': document['version']}
    report = runner(f'import sys, json\nsys.path.insert(0, {str(directory / "runtime.zip")!r})\n'
                    'from schemaxis.spatial_load import execute_native\n'
                    f'execute_native(json.loads({json.dumps(lowered)!r}), json.loads({json.dumps(roots)!r}), '
                    f'json.loads({json.dumps(state)!r}), {str(directory)!r})\n')
    atomic_json(directory / 'submission.json', report.to_dict())
    return json.loads((directory / 'extents.json').read_text())['extents']


def spatial_load(request, *, locations=None, timeout=300, directory=None, load=None):
    """Appendix A.4: observations of the nodes the entries read, and the records they give."""
    load = load or native_extents
    draft = Draft(request)
    member = draft.selected
    if member.scope.adaptor.extents is not True:
        fail('EXTENTS_UNSUPPORTED', 'this adaptor does not report extents, so there is nothing to load',
             member.location(), adaptor=member.scope.adaptor.name)
    visit = Visit(draft, True)
    expression = (Expression(member, request['expression'], request.get('destination'))
                  if 'expression' in request else None)
    identities = request.get('entries')
    if identities is not None and not isinstance(identities, list):
        fail('INVALID_REQUEST', 'entries is a list of entry identities', '$.entries')
    closure = Closure(member)
    extents, loadable = [], []
    for node in wanted_nodes(draft, member, identities, expression):
        try:
            nodes = closure.upstream([node])
            closure.document(nodes, draft.envelope)
            loadable.append(node)
        except SchemaxisError as error:
            extents.append({'node': node, 'port': 0, 'status': 'fault', 'fault': fault_of(error)})
        except expressions.expr.ExprFault as fault:
            from .spatial_actions import located
            extents.append({'node': node, 'port': 0, 'status': 'fault',
                            'fault': located(fault, member.location())})
    if loadable:
        request = Request(closure, draft.envelope, visit, load, locations, timeout, directory)
        try:
            extents.extend(request.run(loadable))
        except SchemaxisError as together:
            if together.fault.code in APPLICATION_FAULTS:
                raise
            if len(loadable) == 1:
                extents.append({'node': loadable[0], 'port': 0, 'status': 'fault', 'fault': fault_of(together)})
            else:
                extents.extend(item for node in loadable for item in request.alone(node))
    order = {node: position for position, node in enumerate(member.scope.nodes or {})}
    extents.sort(key=Position(order))
    observations = {'inputDigest': draft.digest, 'state': copy.deepcopy(visit.state), 'extents': extents}
    if draft.operation is not None:
        observations['operation'] = draft.operation
    visit.observations = observations
    visit.read_observations()
    evaluated = [expression.record(visit)] if expression is not None else records(draft, visit, identities)
    return draft.response(observations=observations, records=evaluated)


class Request:
    """One load of some nodes: the smaller document, the state and where the application runs."""

    def __init__(self, closure, envelope, visit, load, locations, timeout, directory):
        self.closure, self.envelope, self.visit, self.load = closure, envelope, visit, load
        self.locations, self.timeout, self.directory = locations, timeout, directory
        self.count = 0

    def run(self, roots):
        nodes = self.closure.upstream(roots)
        state = {'timeIndex': self.visit.time_index, 'indices': self.closure.indices(nodes, self.visit.indices)}
        document = self.closure.document(nodes, self.envelope)
        self.count += 1
        if self.directory is None:
            with tempfile.TemporaryDirectory(prefix='schemaxis-extents-') as root:
                return self.load(document, roots, state, self.locations, self.timeout, Path(root) / 'load')
        target = Path(self.directory) / f'load-{self.count}'
        return self.load(document, roots, state, self.locations, self.timeout, target)

    def alone(self, node):
        """Load one node by itself, so a fault in planning another does not reach it."""
        try:
            return self.run([node])
        except SchemaxisError as error:
            if error.fault.code in APPLICATION_FAULTS:
                raise
            return [{'node': node, 'port': 0, 'status': 'fault', 'fault': fault_of(error)}]


class Position:
    """Sort key: nodes as authored, then ports."""

    def __init__(self, order):
        self.order = order

    def __call__(self, item):
        return self.order.get(item['node'], len(self.order)), item['port']
