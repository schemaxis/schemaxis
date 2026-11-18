"""Built-in functions of the expression language and their signatures."""
import math

from . import boxes
from .faults import ExprFault
from .values import BOOLEAN, BOX, SCALAR, STRING, VECTOR

FIRST = 'first'


class Signature:
    """One accepted argument list; variadic repeats the last parameter."""

    __slots__ = ('parameters', 'result', 'variadic')

    def __init__(self, parameters, result, variadic=False):
        self.parameters = parameters
        self.result = result
        self.variadic = variadic

    def accepts_count(self, count):
        if self.variadic:
            return count >= len(self.parameters)
        return count == len(self.parameters)

    def parameter(self, index):
        return self.parameters[min(index, len(self.parameters) - 1)]

    def matches(self, types):
        return all(self.parameter(i) == kind for i, kind in enumerate(types))

    def describe(self):
        return list(self.parameters) + (['…'] if self.variadic else [])


class Builtin:
    """A built-in function: implementation, signatures and method-form flag."""

    __slots__ = ('name', 'implementation', 'signatures', 'method')

    def __init__(self, name, implementation, signatures, method):
        self.name = name
        self.implementation = implementation
        self.signatures = signatures
        self.method = method


def domain(name, *arguments):
    return ExprFault('EXPR_DOMAIN', f'{name} is not defined for {list(arguments)}',
                     function=name, arguments=list(arguments))


def componentwise(function, values):
    if isinstance(values[0], tuple):
        return tuple(function(*parts) for parts in zip(*values))
    return function(*values)


def minimum(*values):
    return componentwise(min, values)


def maximum(*values):
    return componentwise(max, values)


def absolute(value):
    return componentwise(abs, (value,))


def magnitude(value):
    return math.hypot(*value) if isinstance(value, tuple) else abs(value)


def magnitude_squared(value):
    return sum(x * x for x in value) if isinstance(value, tuple) else value * value


def square(value):
    return value * value


def cube_root(value):
    return math.copysign(abs(value) ** (1 / 3), value) if not hasattr(math, 'cbrt') else math.cbrt(value)


def logarithm(value):
    if value <= 0:
        raise domain('log', value)
    return math.log(value)


def logarithm10(value):
    if value <= 0:
        raise domain('log10', value)
    return math.log10(value)


def round_half_away(value):
    return int(math.copysign(math.floor(abs(value) + 0.5), value))


def sign(value):
    return 1 if value >= 0 else -1


def positive(value):
    return 1 if value >= 0 else 0


def negative(value):
    return 1 if value < 0 else 0


def clamp(value, low, high):
    if low > high:
        raise domain('clamp', value, low, high)
    return min(max(value, low), high)


def near(a, b, tolerance):
    if isinstance(a, tuple):
        return math.hypot(*(x - y for x, y in zip(a, b))) <= tolerance
    return abs(a - b) <= tolerance


def sine(value):
    return math.sin(math.radians(value))


def cosine(value):
    return math.cos(math.radians(value))


def tangent(value):
    return math.tan(math.radians(value))


def arc_sine(value):
    return math.degrees(math.asin(value))


def arc_cosine(value):
    return math.degrees(math.acos(value))


def arc_tangent(value):
    return math.degrees(math.atan(value))


def arc_tangent2(y, x):
    return math.degrees(math.atan2(y, x))


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def normalize(value):
    length = math.hypot(*value)
    if length == 0:
        raise domain('normalize', list(value))
    return tuple(x / length for x in value)


def lerp(a, b, fraction):
    if isinstance(a, tuple):
        return tuple((1 - fraction) * x + fraction * y for x, y in zip(a, b))
    return (1 - fraction) * a + fraction * b


def vector(x, y, z):
    return (x, y, z)


def box(*arguments):
    if not arguments:
        return boxes.INVALID
    if len(arguments) == 2:
        return boxes.make_box(*arguments)
    return boxes.from_six(*arguments)


S, V, B = (SCALAR,), (VECTOR,), (BOX,)
SS, SSS, VV = (SCALAR,) * 2, (SCALAR,) * 3, (VECTOR,) * 2
SCALAR_TO_SCALAR = (Signature(S, SCALAR),)
SCALAR_OR_VECTOR = (Signature(S, SCALAR), Signature(V, VECTOR))
SEVERAL = (Signature(SS, SCALAR, True), Signature(VV, VECTOR, True))
BOX_AMOUNT = (Signature((BOX, SCALAR), BOX), Signature((BOX, VECTOR), BOX))
BOX_SCALAR = (Signature((BOX, SCALAR), BOX),)
BOX_FACE = (Signature((BOX, STRING, SCALAR), BOX),)

TABLE = (
    Builtin('min', minimum, SEVERAL, True),
    Builtin('max', maximum, SEVERAL, True),
    Builtin('abs', absolute, SCALAR_OR_VECTOR, True),
    Builtin('mag', magnitude, (Signature(S, SCALAR), Signature(V, SCALAR)), True),
    Builtin('magSqr', magnitude_squared, (Signature(S, SCALAR), Signature(V, SCALAR)), True),
    Builtin('sqr', square, SCALAR_TO_SCALAR, True),
    Builtin('sqrt', math.sqrt, SCALAR_TO_SCALAR, True),
    Builtin('cbrt', cube_root, SCALAR_TO_SCALAR, True),
    Builtin('pow', math.pow, (Signature(SS, SCALAR),), True),
    Builtin('hypot', math.hypot, (Signature(SS, SCALAR),), True),
    Builtin('exp', math.exp, SCALAR_TO_SCALAR, True),
    Builtin('log', logarithm, SCALAR_TO_SCALAR, True),
    Builtin('log10', logarithm10, SCALAR_TO_SCALAR, True),
    Builtin('floor', math.floor, SCALAR_TO_SCALAR, True),
    Builtin('ceil', math.ceil, SCALAR_TO_SCALAR, True),
    Builtin('round', round_half_away, SCALAR_TO_SCALAR, True),
    Builtin('sign', sign, SCALAR_TO_SCALAR, True),
    Builtin('pos', positive, SCALAR_TO_SCALAR, True),
    Builtin('neg', negative, SCALAR_TO_SCALAR, True),
    Builtin('clamp', clamp, (Signature(SSS, SCALAR),), True),
    Builtin('near', near, (Signature(SSS, BOOLEAN), Signature((VECTOR, VECTOR, SCALAR), BOOLEAN)), True),
    Builtin('sin', sine, SCALAR_TO_SCALAR, True),
    Builtin('cos', cosine, SCALAR_TO_SCALAR, True),
    Builtin('tan', tangent, SCALAR_TO_SCALAR, True),
    Builtin('asin', arc_sine, SCALAR_TO_SCALAR, True),
    Builtin('acos', arc_cosine, SCALAR_TO_SCALAR, True),
    Builtin('atan', arc_tangent, SCALAR_TO_SCALAR, True),
    Builtin('atan2', arc_tangent2, (Signature(SS, SCALAR),), True),
    Builtin('sinh', math.sinh, SCALAR_TO_SCALAR, True),
    Builtin('cosh', math.cosh, SCALAR_TO_SCALAR, True),
    Builtin('tanh', math.tanh, SCALAR_TO_SCALAR, True),
    Builtin('asinh', math.asinh, SCALAR_TO_SCALAR, True),
    Builtin('acosh', math.acosh, SCALAR_TO_SCALAR, True),
    Builtin('atanh', math.atanh, SCALAR_TO_SCALAR, True),
    Builtin('deg', math.degrees, SCALAR_TO_SCALAR, True),
    Builtin('rad', math.radians, SCALAR_TO_SCALAR, True),
    Builtin('erf', math.erf, SCALAR_TO_SCALAR, True),
    Builtin('erfc', math.erfc, SCALAR_TO_SCALAR, True),
    Builtin('lgamma', math.lgamma, SCALAR_TO_SCALAR, True),
    Builtin('length', magnitude, (Signature(V, SCALAR),), True),
    Builtin('dot', dot, (Signature(VV, SCALAR),), True),
    Builtin('cross', cross, (Signature(VV, VECTOR),), True),
    Builtin('normalize', normalize, (Signature(V, VECTOR),), True),
    Builtin('lerp', lerp, (Signature(SSS, SCALAR), Signature((VECTOR, VECTOR, SCALAR), VECTOR)), True),
    Builtin('vector', vector, (Signature(SSS, VECTOR),), False),
    Builtin('box', box, (Signature((), BOX), Signature(VV, BOX), Signature((SCALAR,) * 6, BOX)), False),
    Builtin('boxAt', boxes.box_at, (Signature(VV, BOX),), False),
    Builtin('union', boxes.union, (Signature(B, BOX, True),), True),
    Builtin('intersect', boxes.intersect, (Signature((BOX, BOX), BOX, True),), True),
    Builtin('overlaps', boxes.overlaps, (Signature((BOX, BOX), BOOLEAN),), True),
    Builtin('contains', boxes.contains, (Signature((BOX, BOX), BOOLEAN), Signature((BOX, VECTOR), BOOLEAN)), True),
    Builtin('subtract', boxes.subtract, (Signature((BOX, BOX), BOX), Signature((BOX, BOX, STRING), BOX)), True),
    Builtin('translate', boxes.translate, (Signature((BOX, VECTOR), BOX),), True),
    Builtin('inflate', boxes.inflate, BOX_AMOUNT, True),
    Builtin('inflateAbs', boxes.inflate_abs, BOX_AMOUNT, True),
    Builtin('inflateX', boxes.inflate_x, BOX_SCALAR, True),
    Builtin('inflateY', boxes.inflate_y, BOX_SCALAR, True),
    Builtin('inflateZ', boxes.inflate_z, BOX_SCALAR, True),
    Builtin('inflateXAbs', boxes.inflate_x_abs, BOX_SCALAR, True),
    Builtin('inflateYAbs', boxes.inflate_y_abs, BOX_SCALAR, True),
    Builtin('inflateZAbs', boxes.inflate_z_abs, BOX_SCALAR, True),
    Builtin('push', boxes.push, BOX_FACE, True),
    Builtin('pushAbs', boxes.push_abs, BOX_FACE, True),
    Builtin('setFace', boxes.set_face, BOX_FACE, True),
    Builtin('corner', boxes.corner, (Signature((BOX, SCALAR), VECTOR),), True),
)

BUILTINS = {builtin.name: builtin for builtin in TABLE}

CASTS = ('scalar', 'vector', 'box')
CONDITIONAL = 'if'

RESERVED_FUNCTIONS = frozenset((
    'lookup', 'tensor', 'symmTensor', 'tr', 'dev', 'symm', 'skew', 'det', 'inv', 'transpose',
    'eigenValues', 'eigenVectors', 'field', 'vol', 'area', 'dist', 'sum', 'average', 'weightedAverage',
    'median', 'quantile', 'range', 'integrate', 'size', 'grad', 'div', 'curl', 'laplacian', 'snGrad',
    'ddt', 'interpolate', 'reconstruct', 'flux', 'previous', 'stored', 'delay', 'isState', 'changedTo',
    'timeSinceChange', 'stepsSinceChange', 'rand', 'randNormal', 'besselJ0', 'besselJ1', 'besselY0',
    'besselY1'))

RESERVED_SIGNATURES = frozenset((('min', 1), ('max', 1), ('pos', 0)))

FACE_ARGUMENT = {'push': 1, 'pushAbs': 1, 'setFace': 1, 'subtract': 2}


def builtin_names():
    return sorted(set(BUILTINS) | set(CASTS) | {CONDITIONAL})
