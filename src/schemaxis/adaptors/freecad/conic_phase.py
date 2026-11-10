"""Bounded dyadic enclosures of analytic conic phases, without native calls.

atan2_enclosure takes X FIRST, Y SECOND; its principal branch is (-pi, pi],
with negative x and zero y assigned +pi (signed floating zero has no meaning).
cos_sin_enclosure returns COSINE FIRST, SINE SECOND. These enclose the ideal
functions of the supplied exact finite values, not native trig evaluation.
"""
from fractions import Fraction

from .gauss_green import EvaluationLimit, Unresolved, finite

PRECISION = 256
MAX_OPERAND_BITS = 16384
MAX_PHASE = 1 << 20
_SCALE = 1 << PRECISION
_PI = None


def _rational(value):
    if type(value) is float:
        value = Fraction(finite(value))
    elif type(value) is int:
        if value.bit_length() > MAX_OPERAND_BITS:
            raise EvaluationLimit('conic phase operand exceeds bounded precision')
        value = Fraction(value)
    elif not isinstance(value, Fraction):
        raise Unresolved('conic phase requires finite numeric coefficients')
    if max(abs(value.numerator).bit_length(), value.denominator.bit_length()) > MAX_OPERAND_BITS:
        raise EvaluationLimit('conic phase operand exceeds bounded precision')
    return value


def _enclose(low, high):
    low, high = _rational(low), _rational(high)
    if low > high:
        raise Unresolved('conic phase interval is inverted')
    lo = Fraction((low.numerator*_SCALE)//low.denominator, _SCALE)
    hi = Fraction(-((-high.numerator*_SCALE)//high.denominator), _SCALE)
    return _rational(lo), _rational(hi)


def outward(value):
    """Enclose a scalar or (lower, upper) on the fixed outward dyadic grid."""
    if isinstance(value, (tuple, list)):
        if len(value) != 2:
            raise Unresolved('conic phase interval membership differs')
        return _enclose(*value)
    value = _rational(value)
    return _enclose(value, value)


def add(first, second):
    a, b = outward(first), outward(second)
    return _enclose(a[0]+b[0], a[1]+b[1])


def sub(first, second):
    a, b = outward(first), outward(second)
    return _enclose(a[0]-b[1], a[1]-b[0])


def neg(value):
    low, high = outward(value)
    return -high, -low


def mul(first, second):
    a, b = outward(first), outward(second)
    values = [x*y for x in a for y in b]
    return _enclose(min(values), max(values))


def div(first, second):
    a, b = outward(first), outward(second)
    if b[0] <= 0 <= b[1]:
        raise Unresolved('conic phase interval division includes zero')
    values = [x/y for x in a for y in b]
    return _enclose(min(values), max(values))


def _atan_series_positive(value, terms, budget):
    """Even-length lower alternating sum and its positive next-term bound."""
    if terms not in (40, 100) or not 0 <= value <= Fraction(1, 2):
        raise Unresolved('conic atan series outside its bounded argument')
    power = outward(value)
    square = mul(power, power)
    total = outward(0)
    for index in range(terms):
        budget.check()
        term = div(power, 2*index+1)
        total = add(total, neg(term) if index % 2 else term)
        power = mul(power, square)
    # atan(x) is between S_even and S_even+x^(2N+1)/(2N+1).
    remainder = div(power, 2*terms+1)[1]
    budget.check()
    return _enclose(total[0], total[1]+remainder)


def pi_interval(budget):
    """Machin's pi enclosure, same40 terms as the original conic policy.

    The alternating sums and every intermediate operation are outward-rounded.
    A cached immutable constant needs only the caller's current deadline check.
    """
    global _PI
    budget.check()
    if _PI is None:
        a = _atan_series_positive(Fraction(1, 5), 40, budget)
        b = _atan_series_positive(Fraction(1, 239), 40, budget)
        result = sub(mul(16, a), mul(4, b))
        budget.check()
        _PI = result
    return _PI


def period_interval(budget):
    return mul(2, pi_interval(budget))


def _atan(value, budget):
    value = _rational(value)
    if not -1 <= value <= 1:
        raise Unresolved('conic atan argument exceeds its reduced domain')
    absolute = abs(value)
    if absolute <= Fraction(1, 2):
        result = _atan_series_positive(absolute, 100, budget)
    else:
        # z in [-1/3,0]; atan(x)=pi/4+atan(z), avoiding the slow x≈1 series.
        z = _rational((absolute-1)/(absolute+1))
        result = sub(div(pi_interval(budget), 4),
                     _atan_series_positive(-z, 100, budget))
    return neg(result) if value < 0 else result


def atan2_enclosure(x, y, budget):
    """Principal angle of the exact vector (X,Y), X first; (0,0) refuses."""
    budget.check()
    x, y = _rational(x), _rational(y)
    if x == y == 0:
        raise Unresolved('conic phase is undefined for the zero vector')
    if y == 0:
        return outward(0) if x > 0 else pi_interval(budget)
    if x == 0:
        half = div(pi_interval(budget), 2)
        return half if y > 0 else neg(half)
    if abs(y) <= abs(x):
        result = _atan(_rational(y/x), budget)
        if x < 0:
            result = add(result, pi_interval(budget)) if y > 0 else sub(result, pi_interval(budget))
    else:
        result = sub(div(pi_interval(budget), 2) if y > 0 else neg(div(pi_interval(budget), 2)),
                     _atan(_rational(x/y), budget))
    budget.check()
    return result


def _midpoint(interval):
    # The chosen point is itself dyadic and lies inside the outward interval.
    low, high = interval
    result = Fraction(round((low+high)*_SCALE/2), _SCALE)
    if not low <= result <= high:
        raise Unresolved('conic phase midpoint exceeds its enclosure')
    return result


def _trig_midpoint(midpoint, budget):
    square = mul(midpoint, midpoint)
    cosine, sine = outward(0), outward(0)
    ct, st = outward(1), outward(midpoint)
    for index in range(40):
        budget.check()
        cosine, sine = add(cosine, ct), add(sine, st)
        ct = neg(div(mul(ct, square), (2*index+1)*(2*index+2)))
        st = neg(div(mul(st, square), (2*index+2)*(2*index+3)))
    # For |m|<=1 the next terms bound the alternating remainders, even after
    # interval rounding. They are m^80/80! and m^81/81!, respectively.
    ce, se = max(map(abs, ct)), max(map(abs, st))
    return _enclose(cosine[0]-ce, cosine[1]+ce), _enclose(sine[0]-se, sine[1]+se)


def cos_sin_enclosure(angle, budget):
    """Enclose (cos,sin) of a scalar or narrow interval with |phase|<=2^20.

    Reduction uses the enclosed pi/2. Taylor is evaluated at a dyadic midpoint
    with |m|<=1; widening by the reduced radius uses the global Lipschitz1 law.
    A wide/unresolved reduced interval refuses rather than subdividing/retrying.
    """
    budget.check()
    angle = outward(angle)
    if max(map(abs, angle)) > MAX_PHASE:
        raise Unresolved('conic phase reduction outside bounded range')
    half_pi = div(pi_interval(budget), 2)
    turn = round(_midpoint(angle)/_midpoint(half_pi))
    reduced = sub(angle, mul(turn, half_pi))
    if max(map(abs, reduced)) > 1:
        raise Unresolved('conic reduced phase interval exceeds bounded Taylor domain')
    midpoint = _midpoint(reduced)
    radius = max(midpoint-reduced[0], reduced[1]-midpoint)
    cosine, sine = _trig_midpoint(midpoint, budget)
    cosine = _enclose(max(Fraction(-1), cosine[0]-radius), min(Fraction(1), cosine[1]+radius))
    sine = _enclose(max(Fraction(-1), sine[0]-radius), min(Fraction(1), sine[1]+radius))
    budget.check()
    return ((cosine, sine), (neg(sine), cosine), (neg(cosine), neg(sine)), (sine, neg(cosine)))[turn % 4]
