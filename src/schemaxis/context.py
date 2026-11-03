# Copyright (C) 2026 David L F Gaden
"""Contextual typed dictionary reads and execution-scoped object identities.

No native runtime imports. Object values stay in process and are never copied.
"""
import copy
from schemaxis.core.declarations import validate_value
from .errors import fail, keys

_MISSING = object()


class ObjectRegistry:
    def __init__(self):
        self.entries = {}
        self.closed = False

    def declare(self, identity, kinds):
        if self.closed:
            fail('CLOSED_REGISTRY', 'object registry is closed', identity)
        if identity in self.entries:
            fail('DUPLICATE_OBJECT', 'object identity is already declared', identity)
        self.entries[identity] = {'kinds': frozenset(kinds), 'value': _MISSING, 'closed': False}

    def publish(self, identity, value):
        entry = self._entry(identity)
        if value is None:
            fail('INVALID_OBJECT', 'cannot publish a null object', identity)
        if entry['value'] is not _MISSING and not entry['closed']:
            fail('DUPLICATE_OBJECT', 'live object identity is already published', identity)
        entry.update(value=value, closed=False)

    def _entry(self, identity):
        if self.closed:
            fail('CLOSED_REGISTRY', 'object registry is closed', str(identity))
        if not isinstance(identity, str) or identity not in self.entries:
            fail('UNKNOWN_REFERENCE', 'object identity is not declared', str(identity),
                 available=sorted(self.entries))
        return self.entries[identity]

    def resolve(self, identity, expected='object', location=None):
        entry = self._entry(identity)
        location = location or identity
        if entry['closed']:
            fail('CLOSED_HANDLE', 'object has been retired', location, identity=identity)
        if expected != 'object' and expected not in entry['kinds']:
            fail('TYPE_MISMATCH', 'object does not have the requested kind', location,
                 expected=expected, available=sorted(entry['kinds']))
        if entry['value'] is _MISSING:
            fail('NOT_YET_PRODUCED', 'object is declared but not constructed', location, identity=identity)
        return entry['value']

    def require_kind(self, value, expected, location):
        for identity, entry in self.entries.items():
            if entry['value'] is value:
                return self.resolve(identity, expected, location)
        fail('UNKNOWN_REFERENCE', 'function returned an unregistered object', location)

    def retire(self, identity):
        entry = self._entry(identity)
        entry.update(value=_MISSING, closed=True)

    def close(self):
        for entry in self.entries.values():
            entry.update(value=_MISSING, closed=True)
        self.closed = True


class InputContext:
    """Read primitives or full objects through one source-located interface.

    Defaults apply only to missing keys, never to invalid supplied values.
    ``resolve`` can be a runtime expression evaluator with the current visit.
    """
    def __init__(self, source, *, owner, objects=None, resolve=None, analytics=None, functions=None):
        self.source, self.owner = source, owner
        self.objects, self.resolver = objects, resolve
        self.analytics = analytics
        self.functions = functions
        self.dependencies = set()

    def _expression(self, value, location):
        if isinstance(value, dict) and '$call' in value:
            keys(value, ('$call', 'args'), location)
            from .functions import FUNCTIONS
            registry = self.functions or FUNCTIONS
            arguments = value.get('args', {})
            registry.check(value['$call'], arguments, location)
            resolved = {}
            for key, item in arguments.items():
                if isinstance(item, dict) and '$object' in item:
                    keys(item, ('$object',), location + '/' + key)
                    if self.objects is None:
                        fail('OBJECT_CONTEXT_UNAVAILABLE', 'function needs object lookup', location)
                    resolved[key] = self.objects.resolve(item['$object'], location=location + '/' + key)
                    self.dependencies.add(item['$object'])
                else:
                    resolved[key] = self._expression(item, location + '/' + key)
            return registry.invoke(value['$call'], resolved, location, self.objects)
        return self.resolver(value, location) if self.resolver else value

    def get(self, path, specification=None, *, object_kind=None, default=_MISSING, raw=False):
        if not isinstance(path, (list, tuple)):
            fail('INVALID_SELECTION', 'lookup path must be a list or tuple', self.owner)
        value = self.source
        location = self.owner
        for part in path:
            location += '/' + str(part).replace('~', '~0').replace('/', '~1')
            if isinstance(value, dict) and isinstance(part, str) and part in value:
                value = value[part]
            elif isinstance(value, (list, tuple)) and type(part) is int and 0 <= part < len(value):
                value = value[part]
            else:
                if default is not _MISSING:
                    return copy.deepcopy(default)
                fail('MISSING_ARGUMENT', 'dictionary path is absent', location)
        if raw:
            return copy.deepcopy(value)
        if isinstance(value, dict) and '$analytic' in value:
            keys(value, ('$analytic',), location)
            if self.analytics is None:
                fail('ANALYTIC_CONTEXT_UNAVAILABLE', 'lookup needs an analytic binding registry', location)
            value = self.analytics.read(self.owner, path, value['$analytic'])
        value = self._expression(value, location)
        if object_kind is not None:
            if self.objects is not None:
                for identity, entry in self.objects.entries.items():
                    if entry['value'] is value:
                        self.dependencies.add(identity)
                        return self.objects.resolve(identity, object_kind, location)
            if isinstance(value, dict):
                keys(value, ('$object',), location)
                value = value.get('$object')
            if self.objects is None:
                fail('OBJECT_CONTEXT_UNAVAILABLE', 'lookup needs an object registry', location)
            result = self.objects.resolve(value, object_kind, location)
            self.dependencies.add(value)
            return result
        return validate_value(value, specification, location) if specification else copy.deepcopy(value)


def compile_objects(document):
    """Lift inline input constructions into the master graph, without executing.

    An explicit identity may be reused only with the identical construction.
    Anonymous constructions receive deterministic identities from their location.
    """
    document = copy.deepcopy(document)
    nodes = document.get('nodes')
    if not isinstance(nodes, list):
        return document
    known = {node.get('id'): copy.deepcopy(node) for node in nodes if isinstance(node, dict) and isinstance(node.get('id'), str)}
    additions = []
    def resolve(value, owner, port, index=None):
        if isinstance(value, list):
            return [resolve(v, owner, port, i) for i, v in enumerate(value)]
        if not isinstance(value, dict):
            return value
        if 'node' in value or 'port' in value:
            return copy.deepcopy(value)
        if '$object' in value:
            keys(value, ('$object',), owner + '/' + port)
            return value['$object']
        keys(value, ('$create',), owner + '/' + port)
        node = copy.deepcopy(value.get('$create'))
        keys(node, ('id', 'filter', 'inputs', 'options', 'onVisit'), owner + '/' + port)
        if 'id' not in node:
            import hashlib
            path = owner + '/' + port + ('/' + str(index) if index is not None else '')
            node['id'] = 'inline' + hashlib.sha256(path.encode()).hexdigest()[:16]
        identity = node['id']
        if not isinstance(identity, str):
            fail('INVALID_NAME', 'inline identity must be a string', owner + '/' + port)
        if identity in known:
            if known[identity] != node:
                fail('CONFLICTING_OBJECT', 'identity has a different construction', identity)
        else:
            known[identity] = copy.deepcopy(node)
            additions.append(node)
        return identity
    # Appending to the worklist handles nested constructors without recursive
    # creation. The master graph still detects reference cycles before execution.
    work = list(nodes)
    i = 0
    while i < len(work):
        node = work[i]
        i += 1
        if isinstance(node, dict) and isinstance(node.get('inputs'), dict):
            node['inputs'] = {p: resolve(v, str(node.get('id')), p) for p, v in node['inputs'].items()}
        if additions:
            work.extend(additions)
            additions.clear()
    document['nodes'] = work
    return document
