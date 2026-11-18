"""What a caller supplies: how names resolve and which extra functions exist."""
from .values import JSON, MISSING, NAMESPACE, classify

CONSTANT = 0
VISIT = 1
OBSERVED = 2
PHASES = ('constant', 'visit', 'observed')


class Info:
    """What the checker knows about one sub-expression."""

    __slots__ = ('type', 'phase', 'dependencies', 'known', 'shape', 'binding', 'target')

    def __init__(self, type, phase=CONSTANT, dependencies=frozenset(), known=MISSING, shape=None):
        self.type = type
        self.phase = phase
        self.dependencies = frozenset(dependencies)
        self.known = known
        self.shape = shape
        self.binding = None
        self.target = None


class Binding:
    """A named value: its type, phase, dependencies and how to read it."""

    def __init__(self, type, phase=CONSTANT, dependencies=(), known=MISSING, shape=None, label=None):
        self.type = type
        self.phase = phase
        self.dependencies = frozenset(dependencies)
        self.known = known
        self.shape = shape
        self.label = label

    def read(self, context):
        return self.known


class Namespace(Binding):
    """A reserved root such as settings; it is not a value, only a container."""

    def __init__(self, label=None):
        super().__init__(NAMESPACE, label=label)

    def member(self, name):
        return None

    def available(self):
        return []


class Shape:
    """A declared result shape, used to type a selection before evaluation."""

    type = JSON

    def member(self, key):
        return None

    def item(self, index):
        return None


class HostFunction:
    """A function supplied by the caller; it sees its unevaluated arguments."""

    def check(self, call, checker):
        raise NotImplementedError

    def evaluate(self, call, evaluator):
        raise NotImplementedError


class Environment:
    """Names and functions of the caller; the default has none."""

    def resolve(self, name, quoted):
        return None

    def available(self):
        return []

    def function(self, name):
        return None

    def functions(self):
        return []


class MappingEnvironment(Environment):
    """Constant named values and host functions held in two mappings."""

    def __init__(self, values=None, functions=None):
        self.values = dict(values or {})
        self.host_functions = dict(functions or {})

    def resolve(self, name, quoted):
        if name not in self.values:
            return None
        value = self.values[name]
        return Binding(classify(value), known=value, label=name)

    def available(self):
        return sorted(self.values)

    def function(self, name):
        return self.host_functions.get(name)

    def functions(self):
        return sorted(self.host_functions)
