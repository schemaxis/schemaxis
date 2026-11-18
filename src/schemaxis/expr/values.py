"""Value types of the expression language and their JSON forms."""
import math

from .faults import ExprFault

SCALAR = 'scalar'
VECTOR = 'vector'
BOX = 'box'
BOOLEAN = 'boolean'
STRING = 'string'
JSON = 'json'
UNKNOWN = 'unknown'
NAMESPACE = 'namespace'

RESERVED_TYPES = ('line', 'plane', 'tensor', 'symmTensor', 'list', 'field')


class Missing:
    """Marks a value that is not known when an expression is checked."""

    def __repr__(self):
        return 'MISSING'


MISSING = Missing()


class Box:
    """An axis-aligned box; every invalid box is the one value INVALID."""

    __slots__ = ('min', 'max')

    def __init__(self, lower, upper):
        self.min = tuple(lower)
        self.max = tuple(upper)

    @property
    def valid(self):
        return all(a <= b for a, b in zip(self.min, self.max))

    def __eq__(self, other):
        return isinstance(other, Box) and self.min == other.min and self.max == other.max

    def __hash__(self):
        return hash((self.min, self.max))

    def __repr__(self):
        return f'Box({list(self.min)}, {list(self.max)})'


INVALID = Box((1, 1, 1), (-1, -1, -1))


def make_box(lower, upper):
    if any(a > b for a, b in zip(lower, upper)):
        return INVALID
    return Box(lower, upper)


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_triple(value):
    return isinstance(value, (list, tuple)) and len(value) == 3 and all(is_number(x) for x in value)


def is_six(value):
    return isinstance(value, (list, tuple)) and len(value) == 6 and all(is_number(x) for x in value)


def is_box_object(value):
    return (isinstance(value, dict) and set(value) == {'min', 'max'}
            and is_triple(value['min']) and is_triple(value['max']))


def classify(value):
    """Type of a known JSON or language value."""
    if isinstance(value, bool):
        return BOOLEAN
    if is_number(value):
        return SCALAR
    if isinstance(value, str):
        return STRING
    if isinstance(value, Box) or is_box_object(value) or is_six(value):
        return BOX
    if is_triple(value):
        return VECTOR
    return JSON


def finite(value):
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def ensure_finite(value):
    if is_number(value):
        numbers = (value,)
    elif isinstance(value, tuple):
        numbers = value
    elif isinstance(value, Box):
        numbers = value.min + value.max
    else:
        return value
    if not all(finite(x) for x in numbers):
        raise ExprFault('EXPR_NONFINITE', 'the result is not a finite number')
    return value


def coerce(value, kind):
    """Convert a JSON or language value to the language value of a type."""
    actual = classify(value)
    if kind in (JSON, UNKNOWN):
        return value
    if actual != kind:
        raise ExprFault('EXPR_TYPE', f'expected {kind}, found {actual}', expected=kind, actual=actual)
    if kind == VECTOR:
        value = tuple(value)
    elif kind == BOX and not isinstance(value, Box):
        if isinstance(value, dict):
            value = make_box(value['min'], value['max'])
        else:
            value = make_box(value[0::2], value[1::2])
    return ensure_finite(value)


def to_json(value, six=False):
    """JSON form of a language value; boxes are canonical unless six is set."""
    if isinstance(value, Box):
        if six:
            return [x for pair in zip(value.min, value.max) for x in pair]
        return {'min': list(value.min), 'max': list(value.max)}
    if isinstance(value, tuple):
        return list(value)
    return value
