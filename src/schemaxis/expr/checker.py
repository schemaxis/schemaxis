"""Static checking: names, types, argument counts, phases and dependencies."""
import math

from . import syntax
from .environment import Environment, Info
from .faults import ExprFault
from .boxes import FACES
from .functions import (BUILTINS, CASTS, CONDITIONAL, FACE_ARGUMENT, RESERVED_FUNCTIONS, RESERVED_SIGNATURES,
                        builtin_names)
from .values import BOOLEAN, BOX, JSON, MISSING, NAMESPACE, SCALAR, STRING, UNKNOWN, VECTOR, classify

CONSTANTS = {'pi': math.pi, 'true': True, 'false': False}
VECTOR_PROPERTIES = {'x': SCALAR, 'y': SCALAR, 'z': SCALAR, 'length': SCALAR}
BOX_PROPERTIES = {'valid': BOOLEAN, 'min': VECTOR, 'max': VECTOR, 'mid': VECTOR, 'size': VECTOR,
                  'span': SCALAR, 'deltaX': SCALAR, 'deltaY': SCALAR, 'deltaZ': SCALAR}
COMPARABLE = (SCALAR, BOOLEAN, STRING, VECTOR, BOX)
PLANNED = 'this form is planned and not yet available'


class Checked:
    """A parsed and checked expression, ready to evaluate."""

    def __init__(self, text, tree, info):
        self.text = text
        self.tree = tree
        self.type = info.type
        self.phase = info.phase
        self.dependencies = info.dependencies
        self.known = info.known
        self.shape = info.shape


class Checker:
    """Walks a syntax tree and records an Info on every node."""

    def __init__(self, text, environment):
        self.text = text
        self.environment = environment
        self.handlers = {
            syntax.Number: self.literal,
            syntax.String: self.literal,
            syntax.Name: self.name,
            syntax.Select: self.select,
            syntax.Index: self.index,
            syntax.Call: self.call,
            syntax.Method: self.method,
            syntax.Unary: self.unary,
            syntax.Binary: self.binary,
            syntax.Conditional: self.conditional,
        }

    def check(self, node):
        chain = [node]
        while syntax.spine(chain[-1]) is not None:
            chain.append(syntax.spine(chain[-1]))
        for current in reversed(chain):
            if current.info is None:
                current.info = self.handlers[type(current)](current)
        return node.info

    def fault(self, code, message, node, **observed):
        return ExprFault(code, message, node.position, node.length, expression=self.text, **observed)

    def source(self, node):
        return self.text[node.position:node.position + node.length]

    def combine(self, kind, *infos):
        phase = max([info.phase for info in infos], default=0)
        dependencies = frozenset().union(*[info.dependencies for info in infos])
        return Info(kind, phase, dependencies)

    def require(self, info, node, *kinds):
        if info.type in kinds:
            return
        if info.type == UNKNOWN:
            raise self.fault('EXPR_TYPE_UNKNOWN', f'`{self.source(node)}` needs a cast: its type is not known '
                             'until it is evaluated', node, source=self.source(node), expected=list(kinds))
        raise self.fault('EXPR_TYPE', f'`{self.source(node)}` is {info.type}; expected {" or ".join(kinds)}',
                         node, expected=list(kinds), actual=info.type)

    def literal(self, node):
        return Info(classify(node.value), known=node.value)

    def from_binding(self, binding):
        info = Info(binding.type, binding.phase, binding.dependencies, binding.known, binding.shape)
        info.binding = binding
        return info

    def name(self, node):
        try:
            binding = self.environment.resolve(node.name, node.quoted)
        except ExprFault as fault:
            fault.observed.setdefault('expression', self.text)
            raise fault.locate(node)
        if not node.quoted and node.name in CONSTANTS:
            if binding is not None:
                raise self.fault('EXPR_AMBIGUOUS_NAME', f'`{node.name}` is both an entry and a built-in name',
                                 node, name=node.name, candidates=[binding.label or node.name, 'built-in'])
            return Info(classify(CONSTANTS[node.name]), known=CONSTANTS[node.name])
        if binding is None:
            raise self.fault('EXPR_UNKNOWN_NAME', f'`{node.name}` is not defined', node, name=node.name,
                             available=self.environment.available())
        return self.from_binding(binding)

    def unknown_property(self, node, name, target, available):
        return self.fault('EXPR_UNKNOWN_PROPERTY', f'{target.type} has no `{name}`', node, name=name,
                          type=target.type, available=available)

    def selection(self, node, target, key):
        if target.known is not MISSING:
            container = target.known
            present = (key in container if isinstance(container, dict) and isinstance(key, str)
                       else isinstance(container, list) and isinstance(key, int) and key < len(container))
            if not present:
                available = sorted(container) if isinstance(container, dict) else []
                raise self.unknown_property(node, key, target, available)
            value = container[key]
            return Info(classify(value), target.phase, target.dependencies, value)
        if target.shape is not None:
            shape = target.shape.member(key) if isinstance(key, str) else target.shape.item(key)
            if shape is None:
                raise self.unknown_property(node, key, target, [])
            return Info(shape.type, target.phase, target.dependencies, shape=shape)
        return Info(UNKNOWN, target.phase, target.dependencies)

    def select(self, node):
        target = self.check(node.target)
        if target.type == NAMESPACE:
            member = target.binding.member(node.key)
            if member is None:
                raise self.fault('EXPR_UNKNOWN_NAME', f'`{node.key}` is not defined in {target.binding.label}',
                                 node, name=node.key, available=target.binding.available())
            return self.from_binding(member)
        if target.type in (JSON, UNKNOWN):
            return self.selection(node, target, node.key)
        properties = VECTOR_PROPERTIES if target.type == VECTOR else BOX_PROPERTIES if target.type == BOX else {}
        if node.key not in properties:
            raise self.unknown_property(node, node.key, target, sorted(properties))
        return self.combine(properties[node.key], target)

    def index(self, node):
        target = self.check(node.target)
        if target.type in (JSON, UNKNOWN):
            return self.selection(node, target, node.index)
        if target.type != VECTOR or node.index > 2:
            raise self.unknown_property(node, node.index, target, [0, 1, 2] if target.type == VECTOR else [])
        return self.combine(SCALAR, target)

    def call(self, node):
        if node.name == CONDITIONAL:
            if node.named or len(node.arguments) != 3:
                raise self.fault('EXPR_ARGUMENTS', 'if takes a condition and two values', node,
                                 function=node.name, expected=[['boolean', 'value', 'value']])
            info = self.branches(node, *node.arguments)
            info.target = CONDITIONAL
            return info
        if node.name in CASTS and len(node.arguments) == 1 and not node.named:
            return self.cast(node)
        if node.name in BUILTINS:
            return self.builtin(node, BUILTINS[node.name], node.arguments, node.named)
        if node.name in CASTS:
            raise self.fault('EXPR_ARGUMENTS', f'{node.name} takes one value', node, function=node.name,
                             expected=[['value']])
        host = self.environment.function(node.name)
        if host is not None:
            info = host.check(node, self)
            info.target = host
            return info
        if node.name in RESERVED_FUNCTIONS:
            raise self.fault('EXPR_UNKNOWN_FUNCTION', f'{node.name}: {PLANNED}', node, name=node.name,
                             reserved=True, available=[])
        raise self.fault('EXPR_UNKNOWN_FUNCTION', f'there is no function `{node.name}`', node, name=node.name,
                         reserved=False, available=builtin_names() + list(self.environment.functions()))

    def method(self, node):
        target = self.check(node.target)
        builtin = BUILTINS.get(node.name)
        if builtin is None or not builtin.method:
            available = sorted(name for name, entry in BUILTINS.items() if entry.method)
            raise self.unknown_property(node, node.name, target, available)
        return self.builtin(node, builtin, [node.target] + node.arguments, node.named)

    def cast(self, node):
        argument = node.arguments[0]
        info = self.check(argument)
        self.require(info, argument, node.name, JSON, UNKNOWN)
        if info.known is not MISSING and classify(info.known) != node.name:
            raise self.fault('EXPR_TYPE', f'`{self.source(argument)}` is {classify(info.known)}, not {node.name}',
                             argument, expected=[node.name], actual=classify(info.known))
        result = self.combine(node.name, info)
        result.target = 'cast'
        return result

    def builtin(self, node, builtin, arguments, named):
        expected = [signature.describe() for signature in builtin.signatures]
        if named:
            raise self.fault('EXPR_ARGUMENTS', f'{builtin.name} takes positional arguments only', node,
                             function=builtin.name, expected=expected, reserved=False)
        infos = [self.check(argument) for argument in arguments]
        candidates = [s for s in builtin.signatures if s.accepts_count(len(arguments))]
        if not candidates:
            reserved = (builtin.name, len(arguments)) in RESERVED_SIGNATURES
            message = PLANNED if reserved else 'wrong number of arguments'
            raise self.fault('EXPR_ARGUMENTS', f'{builtin.name}: {message}', node, function=builtin.name,
                             expected=expected, reserved=reserved)
        types = [info.type for info in infos]
        matching = [s for s in candidates if s.matches(types)]
        if not matching:
            self.mismatch(candidates, arguments, infos)
        if builtin.name == 'corner':
            self.corner_number(node, arguments[1])
        if builtin.name in FACE_ARGUMENT and len(arguments) > FACE_ARGUMENT[builtin.name]:
            self.face_token(builtin, arguments[FACE_ARGUMENT[builtin.name]])
        result = self.combine(matching[0].result, *infos)
        result.target = builtin
        return result

    def mismatch(self, candidates, arguments, infos):
        for position, (argument, info) in enumerate(zip(arguments, infos)):
            accepted = [s.parameter(position) for s in candidates
                        if s.matches([i.type for i in infos[:position]])]
            if info.type not in accepted:
                self.require(info, argument, *dict.fromkeys(accepted or [candidates[0].parameter(position)]))
        self.require(infos[-1], arguments[-1], candidates[0].parameter(len(infos) - 1))

    def corner_number(self, node, argument):
        if not isinstance(argument, syntax.Number) or not isinstance(argument.value, int) or argument.value > 7:
            raise self.fault('EXPR_ARGUMENTS', 'corner takes an integer from 0 to 7', argument,
                             function='corner', expected=list(range(8)))

    def face_token(self, builtin, argument):
        if isinstance(argument, syntax.String) and argument.value not in FACES:
            raise self.fault('EXPR_ARGUMENTS', f'unknown face {argument.value!r}', argument,
                             function=builtin.name, expected=list(FACES))

    def unary(self, node):
        operand = self.check(node.operand)
        if node.operator == '!':
            self.require(operand, node.operand, BOOLEAN)
        else:
            self.require(operand, node.operand, SCALAR, VECTOR)
        return self.combine(operand.type, operand)

    def binary(self, node):
        left, right = self.check(node.left), self.check(node.right)
        operator = node.operator
        if operator in ('&&', '||'):
            self.require(left, node.left, BOOLEAN)
            self.require(right, node.right, BOOLEAN)
            return self.combine(BOOLEAN, left, right)
        if operator in ('==', '!='):
            self.require(left, node.left, *COMPARABLE)
            self.require(right, node.right, left.type)
            return self.combine(BOOLEAN, left, right)
        if operator in ('<', '<=', '>', '>=', '%'):
            self.require(left, node.left, SCALAR)
            self.require(right, node.right, SCALAR)
            return self.combine(SCALAR if operator == '%' else BOOLEAN, left, right)
        self.require(left, node.left, SCALAR, VECTOR)
        self.require(right, node.right, SCALAR, VECTOR)
        return self.combine(VECTOR if VECTOR in (left.type, right.type) else SCALAR, left, right)

    def conditional(self, node):
        return self.branches(node, node.condition, node.chosen, node.otherwise)

    def branches(self, node, condition, chosen, otherwise):
        test, first, second = self.check(condition), self.check(chosen), self.check(otherwise)
        self.require(test, condition, BOOLEAN)
        self.require(first, chosen, *COMPARABLE)
        self.require(second, otherwise, first.type)
        return self.combine(first.type, test, first, second)


def check(text, environment=None):
    tree = syntax.parse(text)
    checker = Checker(text, environment or Environment())
    try:
        info = checker.check(tree)
    except RecursionError:
        raise ExprFault('EXPR_LIMIT', 'the expression is nested too deeply', 0, len(text), expression=text,
                        limit=syntax.MAX_DEPTH) from None
    if info.type == NAMESPACE:
        raise checker.fault('EXPR_TYPE', f'`{text.strip()}` is a section, not a value', tree,
                            expected=['value'], actual=NAMESPACE)
    return Checked(text, tree, info)
