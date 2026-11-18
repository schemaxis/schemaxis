"""Resolved spatial entries of a run and the late values they read.

A run writes, into each verified receipt, the value of every named scalar,
vector and box at every visit, with the extents, observations and samples
those values were computed from. Verification replays the entries from that
record alone, without the application, and refuses any difference
(docs/design/expression-language.md, section 11.2).
"""
import copy
import math

from schemaxis.core.faults import SchemaxisError
from . import expr, expressions
from .errors import fail
from .expr.values import BOX, SCALAR, VECTOR
from .expressions import SECTIONS, State, pointer

VERSION = 1
SPATIAL = (SCALAR, VECTOR, BOX)
TOLERANCE = 1e-12


def spatial_entries(scope):
    """Named scalars, vectors and boxes of a scope with their bindings."""
    found = []
    for section in SECTIONS:
        for key in scope.sections.get(section, {}):
            try:
                binding = scope.entry(section, key)
            except expr.ExprFault:
                continue
            if binding.type in SPATIAL:
                found.append((section, key, binding))
    return found


def late_markers(scope):
    """Every $observe and $sample marker of the named sections, with its pointer."""
    observes, samples = [], []
    for section in SECTIONS:
        collect_markers(scope.sections.get(section, {}), pointer('', section), observes, samples)
    return observes, samples


def collect_markers(value, path, observes, samples):
    if isinstance(value, list):
        for index, item in enumerate(value):
            collect_markers(item, pointer(path, index), observes, samples)
    elif isinstance(value, dict):
        if isinstance(value.get('$observe'), str):
            observes.append((value['$observe'], list(value.get('path', []))))
        if isinstance(value.get('$sample'), str):
            samples.append((path, value))
        for key, item in value.items():
            collect_markers(item, pointer(path, key), observes, samples)


def read_ports(scope, entries):
    """Output ports whose extents the entries read; None stands for every port of a node."""
    ports = set()
    for _, _, binding in entries:
        for item in binding.profile.dependencies:
            if item[0] == 'port':
                ports.add((item[1], item[2]))
            elif item[0] == 'ports':
                ports.add((item[1], None))
        if binding.profile.data:
            ports.update((node, None) for node in scope.loaders() or [])
    return ports


def port_values(observation):
    """Extents of every output port of one observation, in the recorded form."""
    if not isinstance(observation, dict):
        return []
    if 'extents' in observation:
        return observation['extents']
    return [observation['bounds']] if 'bounds' in observation else []


def select(value, path):
    for part in path:
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and type(part) is int and 0 <= part < len(value):
            value = value[part]
        else:
            return None
    return copy.deepcopy(value)


class Samples:
    """Sample values of one visit, found by what was asked rather than asked of the application."""

    def __init__(self, items):
        self.items = items

    def __call__(self, source, association, field, index, component, block):
        request = {'node': source, 'association': association, 'field': field, 'index': index,
                   'component': component, 'block': block}
        for item in self.items:
            if all(item.get(key) == value for key, value in request.items()):
                return item['value']
        fail('OBSERVATION_UNAVAILABLE', 'this sample was not recorded', source)


def entry_value(scope, section, key, binding, visit, observations, sampler):
    """Canonical value of an entry at one visit, or None when it cannot be evaluated there."""
    state = State(visit['sweeps'], observations, visit['time'], sampler, '$' + pointer(pointer('', section), key))
    try:
        return expr.to_json(expr.coerce(scope.entry_value(section, key, state), binding.type))
    except (SchemaxisError, expr.ExprFault, KeyError, TypeError):
        return None


def sample_value(scope, marker, path, visit, observations, sampler):
    from .pipeline import evaluate
    try:
        return evaluate(marker, visit['sweeps'], observations, visit['time'], '$' + path, sampler, scope, path)
    except (SchemaxisError, expr.ExprFault, KeyError, TypeError):
        return None


def axes_fastest_first(states):
    """Axes the recorded visits step through, fastest first."""
    found = []
    for state in states:
        for axis in reversed(list(state['visit']['indices'])):
            if axis not in found:
                found.append(axis)
    return found


def record(master, states):
    """The spatial block of a receipt from the states a run visited."""
    scope = master.scope
    entries = spatial_entries(scope)
    observes, samples = late_markers(scope)
    extents = []
    for node, port in sorted(read_ports(scope, entries), key=port_order):
        count = max((len(port_values(state['observations'].get(node))) for state in states), default=0)
        for number in range(count) if port is None else [port]:
            if all(item['node'] != node or item['port'] != number for item in extents):
                extents.append({'node': node, 'port': number, 'values': [
                    select(port_values(state['observations'].get(node)), [number]) for state in states]})
    observations = []
    for node, path in observes:
        if all(item['node'] != node or item['path'] != path for item in observations):
            observations.append({'node': node, 'path': path, 'values': [
                select(state['observations'].get(node), path) for state in states]})
    sampled = [{'pointer': path, 'values': [
        sample_value(scope, marker, path, state['visit'], state['observations'], Samples(state.get('samples', [])))
        for state in states]} for path, marker in samples]
    nodes = sorted({item['node'] for item in extents + observations} | {marker['$sample'] for _, marker in samples})
    updated = [{'node': node, 'values': [node in state['observations'] for state in states]} for node in nodes]
    result = {'sweepsFastestFirst': axes_fastest_first(states),
              'inputs': {'extents': extents, 'observations': observations, 'samples': sampled, 'upstream': [],
                         'updated': updated},
              'entries': {}}
    for section, key, binding in entries:
        values = [entry_value(scope, section, key, binding, state['visit'], state['observations'],
                              Samples(state.get('samples', []))) for state in states]
        result['entries'].setdefault(section, {})[key] = {
            'type': binding.type, 'phase': expr.PHASES[binding.profile.phase], 'values': values}
    return result


def port_order(item):
    return item[0], -1 if item[1] is None else item[1]


def holds(target, part):
    """Whether a container can hold a value under this part of a path: a key in an object, a position in a list."""
    return isinstance(part, str) if isinstance(target, dict) else isinstance(target, list) and type(part) is int \
        and part >= 0


def inside(target, part, empty):
    """The container under one part of a path, made when it is not there yet."""
    if isinstance(target, list):
        target.extend([None] * (part + 1 - len(target)))
        if target[part] is None:
            target[part] = empty
        return target[part]
    return target.setdefault(part, empty)


def place(target, path, value):
    """Put a recorded observation back where its path says it was read from.

    A whole number in the path is a position in a list, as it was when the value was read.
    """
    if not path:
        if isinstance(value, dict):
            target.update(copy.deepcopy(value))
        return
    for part, following in zip(path[:-1], path[1:]):
        if not holds(target, part):
            return
        target = inside(target, part, [] if type(following) is int else {})
    if not holds(target, path[-1]):
        return
    if isinstance(target, list):
        target.extend([None] * (path[-1] + 1 - len(target)))
    target[path[-1]] = copy.deepcopy(value)


def recorded_observations(inputs, index):
    """What the entries could observe at one visit, rebuilt from the recorded inputs alone."""
    observations = {item['node']: {} for item in inputs['updated'] if item['values'][index]}
    for item in inputs['observations']:
        if item['node'] in observations and item['values'][index] is not None:
            place(observations[item['node']], item['path'], item['values'][index])
    for item in inputs['extents']:
        if item['node'] in observations:
            ports = observations[item['node']].setdefault('extents', [])
            ports.extend([None] * (item['port'] + 1 - len(ports)))
            ports[item['port']] = copy.deepcopy(item['values'][index])
    return observations


class RecordedSamples:
    """Sample values of one visit, taken from the record by the marker that read them."""

    def __init__(self, scope, inputs, index, visit, observations):
        from .pipeline import evaluate
        self.values = {}
        _, markers = late_markers(scope)
        recorded = {item['pointer']: item['values'][index] for item in inputs['samples']}
        for path, marker in markers:
            if recorded.get(path) is None:
                continue
            try:
                position = evaluate(marker.get('index'), visit['sweeps'], observations, visit['time'], '$' + path,
                                    None, scope, pointer(path, 'index'))
            except (SchemaxisError, expr.ExprFault, KeyError, TypeError):
                continue
            self.values[self.key(marker['$sample'], marker.get('association'), marker.get('field'), position,
                                 marker.get('component'), marker.get('block', []))] = recorded[path]

    def key(self, source, association, field, index, component, block):
        return source, association, field, index, component, tuple(block)

    def __call__(self, source, association, field, index, component, block):
        key = self.key(source, association, field, index, component, block)
        if key not in self.values:
            fail('OBSERVATION_UNAVAILABLE', 'this sample was not recorded', source)
        return self.values[key]


def same(recorded, computed):
    """Recorded and recomputed values agree to the tolerance of the specification's examples."""
    if isinstance(recorded, dict) and isinstance(computed, dict):
        return set(recorded) == set(computed) and all(same(recorded[key], computed[key]) for key in recorded)
    if isinstance(recorded, list) and isinstance(computed, list):
        return len(recorded) == len(computed) and all(same(a, b) for a, b in zip(recorded, computed))
    numbers = all(type(value) in (int, float) for value in (recorded, computed))
    if numbers:
        return math.isclose(recorded, computed, rel_tol=TOLERANCE, abs_tol=TOLERANCE)
    return recorded == computed


def verify(master, receipt, location):
    """Recompute every recorded entry from the recorded inputs and refuse any difference.

    A receipt without a spatial record is accepted only for a document that has
    no scalar, vector or box entry to record; removing the record is otherwise a difference.
    """
    states = receipt.get('states', [])
    expected = record(master, states)
    if receipt.get('spatialVersion') is None and 'spatial' not in receipt:
        if expected['entries']:
            fail('VERIFICATION_FAILED', 'the spatial record of this run is missing', str(location))
        return
    if receipt.get('spatialVersion') != VERSION or not isinstance(receipt.get('spatial'), dict):
        fail('VERIFICATION_FAILED', 'unsupported or missing spatial record', str(location))
    block = receipt['spatial']
    if block.get('inputs') != expected['inputs'] or block.get('sweepsFastestFirst') != expected['sweepsFastestFirst']:
        fail('VERIFICATION_FAILED', 'recorded spatial inputs differ from the observations of the run', str(location))
    scope = master.scope
    entries = spatial_entries(scope)
    declared = {section: {key: {'type': binding.type, 'phase': expr.PHASES[binding.profile.phase]}
                          for part, key, binding in entries if part == section}
                for section in {section for section, _, _ in entries}}
    recorded = block.get('entries')
    if not isinstance(recorded, dict) or {section: {key: {'type': item.get('type'), 'phase': item.get('phase')}
                                                    for key, item in items.items()}
                                          for section, items in recorded.items()} != declared:
        fail('VERIFICATION_FAILED', 'recorded spatial entries differ from the plan', str(location))
    for index, state in enumerate(states):
        observations = recorded_observations(block['inputs'], index)
        sampler = RecordedSamples(scope, block['inputs'], index, state['visit'], observations)
        for section, key, binding in entries:
            values = recorded[section][key].get('values')
            if not isinstance(values, list) or len(values) != len(states):
                fail('VERIFICATION_FAILED', 'a spatial entry needs one value for each visit', f'{section}.{key}')
            computed = entry_value(scope, section, key, binding, state['visit'], observations, sampler)
            if not same(values[index], computed):
                fail('VERIFICATION_FAILED', 'a recorded spatial entry differs from its recomputation',
                     f'{section}.{key}', visit=index, recorded=values[index], recomputed=computed)


def run_receipt(directory, operation=None):
    """Receipt of a verified run that holds a spatial record, for a document or one workflow operation."""
    import json
    from pathlib import Path
    directory = Path(directory)
    candidates = [directory if operation is None else directory / operation]
    result = directory / 'result.json'
    if operation is not None and result.is_file():
        for job in json.loads(result.read_text()).get('jobs', []):
            if isinstance(job, dict) and job.get('operation') == operation and isinstance(job.get('directory'), str):
                candidates.append(directory / job['directory'])
    for candidate in candidates:
        path = candidate / 'verification.json'
        if path.is_file():
            receipt = json.loads(path.read_text())
            if isinstance(receipt, dict) and isinstance(receipt.get('spatial'), dict) and receipt.get('states'):
                return receipt
    return None


def run_records(document, directory):
    """Records of the spatial entries of a verified run, at its first visit (appendix A common fields).

    The values are the ones the run recorded and verification replayed; nothing
    is evaluated here beyond what is constant in the input.
    """
    from .spatial_actions import Draft, Visit, entry_record
    draft = Draft({'input': document})
    visit = Visit(draft, False)
    records = []
    for member in draft.listed():
        receipt = run_receipt(directory, member.operation)
        entries = receipt['spatial'].get('entries', {}) if receipt else {}
        state = receipt['states'][0]['visit'] if receipt else None
        for section, key in member.entries():
            record = entry_record(draft, member, section, key, visit)
            if record is None:
                continue
            values = entries.get(section, {}).get(key, {}).get('values') or [None]
            if values[0] is not None and record['state'] == 'unresolved':
                record.pop('reason', None)
                record.update(state='resolved', value=copy.deepcopy(values[0]), source={
                    'kind': 'run', 'inputDigest': draft.digest,
                    'state': {'timeIndex': state['timeIndex'], 'indices': dict(state['indices'])}})
                if record['type'] == BOX:
                    record['valid'] = not expressions.is_invalid_box(values[0])
            records.append(record)
    return draft.response(records=records)


def job_records(document, directory):
    """Run records for a job result; a failure to read them is reported in place, not raised into the job."""
    try:
        return run_records(document, directory)
    except SchemaxisError as error:
        return {'fault': error.fault.to_dict()}
