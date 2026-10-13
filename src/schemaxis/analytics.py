"""Compile member-local analytic bindings into explicit scheduled axes."""
import copy
import math
from .errors import fail, keys


def _builtin_values(spec, location, limit):
    keys(spec, ('type', 'values', 'start', 'end', 'count', 'sync', 'elevation'), location)
    kind = spec.get('type')
    allowed = {'values': {'type', 'values', 'sync'},
               'linear': {'type', 'start', 'end', 'count', 'sync'},
               'orbit': {'type', 'start', 'end', 'count', 'elevation'}}
    if kind not in allowed:
        fail('UNKNOWN_ANALYTIC', 'analytic type is not registered', location, available=sorted(allowed))
    keys(spec, allowed[kind], location)
    if kind == 'values':
        result = spec.get('values')
        if not isinstance(result, list) or not result:
            fail('EMPTY_ANALYTIC', 'analytic values must be a nonempty array', location)
        if len(result) > limit:
            fail('EXPANSION_TOO_LARGE', 'analytic exceeds state limit', location)
        return copy.deepcopy(result)
    count = spec.get('count')
    if type(count) is not int or count < 1 or count > limit:
        fail('INVALID_ANALYTIC_COUNT', 'count must be positive and within the state limit', location)
    start, end = spec.get('start'), spec.get('end')
    def interpolate(a, b, fraction):
        if isinstance(a, list) and isinstance(b, list) and len(a) == len(b) and a:
            return [interpolate(x, y, fraction) for x, y in zip(a, b)]
        if type(a) not in (int, float) or type(b) not in (int, float) or not all(math.isfinite(x) for x in (a, b)):
            fail('INVALID_ANALYTIC', 'linear endpoints need finite scalars or matching vectors', location)
        result = (1 - fraction) * a + fraction * b
        if not math.isfinite(result):
            fail('INVALID_ANALYTIC', 'interpolated value is not finite', location)
        return result
    if count == 1 and start != end:
        fail('INVALID_ANALYTIC', 'one sample requires equal endpoints', location)
    result = [interpolate(start, end, i / (count - 1) if count > 1 else 0) for i in range(count)]
    if kind == 'orbit':
        elevation = spec.get('elevation', 0)
        if type(elevation) not in (int, float) or not math.isfinite(elevation) or not -90 < elevation < 90:
            fail('INVALID_ANALYTIC', 'orbit elevation must lie strictly between -90 and 90 degrees', location)
        if any(type(v) not in (float, int) for v in result):
            fail('INVALID_ANALYTIC', 'orbit angles must be scalar', location)
        elev = math.radians(elevation)
        result = [{'direction': [math.cos(math.radians(v))*math.cos(elev),
                                 math.sin(math.radians(v))*math.cos(elev), math.sin(elev)],
                   'up': [0, 0, 1]} for v in result]
    return result


class AnalyticRegistry:
    """Explicit trusted analytic factories shared by member and sequence scopes."""
    def __init__(self):
        self.factories = {}

    def register(self, name, factory):
        if not isinstance(name, str) or not name or name in self.factories or not callable(factory):
            fail('INVALID_ANALYTIC_FACTORY', 'factory needs a new name and callable', str(name))
        self.factories[name] = factory

    def values(self, spec, location, limit):
        if not isinstance(spec, dict) or not isinstance(spec.get('type'), str) or spec['type'] not in self.factories:
            fail('UNKNOWN_ANALYTIC', 'analytic type is not registered', location, available=sorted(self.factories))
        result = self.factories[spec['type']](copy.deepcopy(spec), location, limit)
        if not isinstance(result, list) or not result:
            fail('EMPTY_ANALYTIC', 'factory must produce a nonempty array', location)
        if len(result) > limit:
            fail('EXPANSION_TOO_LARGE', 'analytic exceeds state limit', location)
        return copy.deepcopy(result)


ANALYTICS = AnalyticRegistry()
for _kind in ('values', 'linear', 'orbit'):
    ANALYTICS.register(_kind, _builtin_values)


def values(spec, location, limit):
    return ANALYTICS.values(spec, location, limit)


class AnalyticBindings:
    """Owner/member bindings with shared synchronized axes and repeatable reads."""
    def __init__(self, *, axes=None, limit=10000):
        self.axes = axes if axes is not None else []
        self.limit = limit
        self.names = {a.get('name') for a in self.axes if isinstance(a, dict) and isinstance(a.get('name'), str)}
        self.groups, self.entries = {}, {}
        self.bindings = []
        self.indices = {}

    def bind(self, owner, path, spec):
        identity = (owner, tuple(path))
        location = owner + '/' + '/'.join(str(x) for x in path)
        if identity in self.entries:
            old, marker, axis, member = self.entries[identity]
            if old != spec:
                fail('CONFLICTING_ANALYTIC', 'member already has a different analytic binding', location)
            return copy.deepcopy(marker)
        data = values(spec, location, self.limit)
        sync = spec.get('sync')
        if sync is not None and (not isinstance(sync, str) or not sync):
            fail('INVALID_SYNC', 'sync must be a nonempty string', location)
        group = ('sync', sync) if sync else ('member', identity)
        if group not in self.groups:
            name = 'analytic' + str(len(self.groups))
            while name in self.names:
                name += 'x'
            self.names.add(name)
            self.groups[group] = {'name': name, 'values': [{} for _ in data]}
            self.axes.append(self.groups[group])
        axis = self.groups[group]
        if len(axis['values']) != len(data):
            fail('ANALYTIC_LENGTH_MISMATCH', 'synchronized members must have equal lengths', location,
                 expected=len(axis['values']), actual=len(data), sync=sync)
        member = 'member' + str(len(self.bindings))
        for row, value in zip(axis['values'], data):
            row[member] = value
        marker = {'$axis': axis['name'], 'path': [member]}
        self.entries[identity] = (copy.deepcopy(spec), marker, axis, member)
        self.bindings.append({'owner': owner, 'memberPath': list(path), 'axis': axis['name'], 'member': member, 'sync': sync})
        return copy.deepcopy(marker)

    def read(self, owner, path, spec):
        self.bind(owner, path, spec)
        _, _, axis, member = self.entries[(owner, tuple(path))]
        index = self.indices.get(axis['name'], 0)
        if type(index) is not int or not 0 <= index < len(axis['values']):
            fail('ANALYTIC_EXHAUSTED', 'analytic index is outside its sequence', owner, index=index)
        return copy.deepcopy(axis['values'][index][member])


def compile_analytics(document):
    document = copy.deepcopy(document)
    limit = document.get('maxStates', 10000)
    if type(limit) is not int or limit < 1:
        fail('INVALID_LIMIT', 'maxStates must be a positive integer')
    axes = document.setdefault('axes', [])
    if not isinstance(axes, list):
        fail('INVALID_AXIS', 'axes must be an array')
    registry = AnalyticBindings(axes=axes, limit=limit)
    def bind(value, owner, path):
        if isinstance(value, dict) and '$analytic' in value:
            keys(value, ('$analytic',), owner + '/' + '/'.join(str(x) for x in path))
            return registry.bind(owner, path, value['$analytic'])
        if isinstance(value, dict):
            return {k: bind(v, owner, [*path, k]) for k, v in value.items()}
        if isinstance(value, list):
            return [bind(v, owner, [*path, i]) for i, v in enumerate(value)]
        return value
    nodes = document.get('nodes', [])
    if isinstance(nodes, list):
        for i, node in enumerate(nodes):
            if isinstance(node, dict) and 'options' in node:
                node['options'] = bind(node['options'], str(node.get('id', i)), ['options'])
    scenes = document.get('scenes', [])
    if isinstance(scenes, list):
        for i, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                continue
            targets = [(scene, 'appearances', '$/scenes/' + str(i))]
            images = scene.get('images', [])
            if isinstance(images, list):
                targets.extend((writer, 'cameras', '$/scenes/' + str(i) + '/images/' + str(j))
                               for j, writer in enumerate(images) if isinstance(writer, dict))
            for owner, key, path in targets:
                entry = owner.get(key)
                if isinstance(entry, dict) and '$analytic' in entry:
                    keys(entry, ('$analytic',), path + '/' + key)
                    if not isinstance(entry['$analytic'], dict):
                        fail('INVALID_ANALYTIC', 'analytic definition must be an object', path + '/' + key)
                    if 'sync' in entry['$analytic']:
                        fail('INVALID_SYNC', 'publication sequences have their own iteration scope', path + '/' + key)
                    owner[key] = values(entry['$analytic'], path + '/' + key, limit)
    return document, registry.bindings
