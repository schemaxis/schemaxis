"""Evaluation of a checked expression."""
import math
import operator

from . import boxes, syntax
from .checker import CONSTANTS, Checked, check
from .faults import ExprFault
from .functions import CONDITIONAL, Builtin, domain
from .values import BOX, JSON, NAMESPACE, UNKNOWN, VECTOR, Box, coerce, ensure_finite, to_json

ORDERING = {'<': operator.lt, '<=': operator.le, '>': operator.gt, '>=': operator.ge}
ARITHMETIC = {'+': operator.add, '-': operator.sub, '*': operator.mul}


def remainder(a, b):
    if isinstance(a, int) and isinstance(b, int):
        result = abs(a) % abs(b)
        return -result if a < 0 else result
    return math.fmod(a, b)


def scalar_arithmetic(symbol, a, b):
    if symbol in ARITHMETIC:
        return ARITHMETIC[symbol](a, b)
    if b == 0:
        raise domain(symbol, a, b)
    return a / b if symbol == '/' else remainder(a, b)


def arithmetic(symbol, a, b):
    if not isinstance(a, tuple) and not isinstance(b, tuple):
        return scalar_arithmetic(symbol, a, b)
    left = a if isinstance(a, tuple) else (a, a, a)
    right = b if isinstance(b, tuple) else (b, b, b)
    return tuple(scalar_arithmetic(symbol, x, y) for x, y in zip(left, right))


class Evaluator:
    """Evaluates the nodes of one checked expression against a context."""

    def __init__(self, checked, context=None):
        self.text = checked.text
        self.context = context
        self.ready = {}
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

    def first_operand(self, node):
        inner = syntax.spine(node)
        return None if inner is None or inner.info.type == NAMESPACE else inner

    def evaluate(self, node):
        if id(node) in self.ready:
            return self.ready.pop(id(node))
        chain = [node]
        while self.first_operand(chain[-1]) is not None:
            chain.append(self.first_operand(chain[-1]))
        for current in reversed(chain):
            try:
                value = ensure_finite(self.handlers[type(current)](current))
            except ExprFault as fault:
                fault.observed.setdefault('expression', self.text)
                raise fault.locate(current)
            if current is not node:
                self.ready[id(current)] = value
        return value

    def source(self, node):
        return self.text[node.position:node.position + node.length]

    def literal(self, node):
        return node.value

    def name(self, node):
        if node.info.binding is None:
            return CONSTANTS[node.name]
        return coerce(node.info.binding.read(self.context), node.info.type)

    def pick(self, node, container, key):
        present = (key in container if isinstance(container, dict) and isinstance(key, str)
                   else isinstance(container, (list, tuple)) and isinstance(key, int) and key < len(container))
        if not present:
            raise ExprFault('EXPR_UNKNOWN_PROPERTY', f'the value has no `{key}`', name=key,
                            type=node.target.info.type, available=sorted(container) if isinstance(container, dict) else [])
        return coerce(container[key], node.info.type)

    def select(self, node):
        kind = node.target.info.type
        if kind == NAMESPACE:
            return coerce(node.info.binding.read(self.context), node.info.type)
        target = self.evaluate(node.target)
        if kind in (JSON, UNKNOWN):
            return self.pick(node, target, node.key)
        if kind == VECTOR:
            return math.hypot(*target) if node.key == 'length' else target['xyz'.index(node.key)]
        return self.box_property(node, target)

    def box_property(self, node, box):
        key = node.key
        if key == 'valid':
            return box.valid
        if not box.valid:
            raise ExprFault('EXPR_INVALID_BOX', f'`{self.source(node.target)}` is an invalid box; its {key} '
                            'cannot be read', source=self.source(node.target))
        if key in ('min', 'max'):
            return getattr(box, key)
        if key == 'mid':
            return boxes.middle(box)
        if key == 'size':
            return boxes.size(box)
        if key == 'span':
            return boxes.span(box)
        return boxes.size(box)[('deltaX', 'deltaY', 'deltaZ').index(key)]

    def index(self, node):
        target = self.evaluate(node.target)
        if node.target.info.type == VECTOR:
            return target[node.index]
        return self.pick(node, target, node.index)

    def call(self, node):
        target = node.info.target
        if target == CONDITIONAL:
            return self.choose(*node.arguments)
        if target == 'cast':
            return coerce(self.evaluate(node.arguments[0]), node.info.type)
        if isinstance(target, Builtin):
            return self.apply(target, node.arguments)
        return ensure_finite(coerce(target.evaluate(node, self), node.info.type))

    def method(self, node):
        return self.apply(node.info.target, [node.target] + node.arguments)

    def apply(self, builtin, nodes):
        arguments = [self.evaluate(node) for node in nodes]
        shown = [to_json(argument) for argument in arguments]
        try:
            return ensure_finite(builtin.implementation(*arguments))
        except ExprFault as fault:
            if fault.code == 'EXPR_INVALID_BOX':
                fault.observed.setdefault('source', self.source(nodes[0]))
            elif fault.code == 'EXPR_NONFINITE':
                fault.observed.update(function=builtin.name, arguments=shown)
            raise
        except (ValueError, ZeroDivisionError):
            raise domain(builtin.name, *shown) from None
        except OverflowError:
            raise ExprFault('EXPR_NONFINITE', f'{builtin.name} of {shown} is too large', function=builtin.name,
                            arguments=shown) from None

    def unary(self, node):
        operand = self.evaluate(node.operand)
        if node.operator == '!':
            return not operand
        if node.operator == '+':
            return operand
        return tuple(-x for x in operand) if isinstance(operand, tuple) else -operand

    def binary(self, node):
        symbol = node.operator
        left = self.evaluate(node.left)
        if symbol == '&&':
            return left and self.evaluate(node.right)
        if symbol == '||':
            return left or self.evaluate(node.right)
        right = self.evaluate(node.right)
        if symbol == '==':
            return left == right
        if symbol == '!=':
            return left != right
        if symbol in ORDERING:
            return ORDERING[symbol](left, right)
        shown = [to_json(left), to_json(right)]
        try:
            return ensure_finite(arithmetic(symbol, left, right))
        except OverflowError:
            raise ExprFault('EXPR_NONFINITE', f'{symbol} of {shown} is too large', operator=symbol,
                            arguments=shown) from None
        except ExprFault as fault:
            if fault.code == 'EXPR_NONFINITE':
                fault.observed.update(operator=symbol, arguments=shown)
            raise

    def conditional(self, node):
        return self.choose(node.condition, node.chosen, node.otherwise)

    def choose(self, condition, chosen, otherwise):
        return self.evaluate(chosen if self.evaluate(condition) else otherwise)


def evaluate(expression, environment=None, context=None):
    """Value of an expression given as text or as a Checked object."""
    checked = expression if isinstance(expression, Checked) else check(expression, environment)
    try:
        return Evaluator(checked, context).evaluate(checked.tree)
    except RecursionError:
        raise ExprFault('EXPR_LIMIT', 'the expression is nested too deeply', 0, len(checked.text),
                        expression=checked.text, limit=syntax.MAX_DEPTH) from None
