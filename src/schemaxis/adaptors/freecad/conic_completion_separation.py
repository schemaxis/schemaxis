"""Exact finite-coefficient separation from a whole ideal ellipse.

This is not an enclosure of native trigonometric evaluation. The caller must
first establish its existing float-evaluated endpoint incidence. Neither that
endpoint nor the original conic's parameter range is changed here.
"""
from fractions import Fraction
from functools import lru_cache


@lru_cache(maxsize=1)
def _full_period_enclosure():
    """Exact rational enclosure from Machin's identity and alternating series.

    pi = 16 atan(1/5) - 4 atan(1/239). Forty terms give a fixed, bounded
    calculation; unresolved comparisons remain unresolved, never rounded.
    """
    def arctangent(denominator):
        x=Fraction(1,denominator);power=x;total=Fraction(0)
        for index in range(40):
            total+=(-1 if index%2 else 1)*power/(2*index+1)
            power*=x*x
        # The even-length sum ends with a negative term, hence is lower.
        return total,total+power/81
    lo5,hi5=arctangent(5);lo239,hi239=arctangent(239)
    return 2*(16*lo5-4*hi239),2*(16*hi5-4*lo239)


def conic_period_relation(curve, budget):
    """Compare the unchanged finite domain width to the true full period."""
    budget.check()
    width=Fraction(curve.end)-Fraction(curve.start)
    lower,upper=_full_period_enclosure()
    budget.check()
    return 'longer' if width>upper else 'shorter' if width<lower else None


def separated_from_ideal_conic(first, last, curve, budget):
    """Return 'inside', 'outside', or None for an unresolved/touching segment.

    Every input coefficient is a finite binary64, and all vectors have exactly
    two entries. This bounds the rational arithmetic independently of authored
    integers, native curve degree and parameter width. No sampling is used.
    """
    from .gauss_green import finite, Unresolved
    budget.check()
    rows = (first, last, curve.location, curve.cosine, curve.sine)
    if any(len(row) != 2 for row in rows):
        raise Unresolved('implicit conic separation requires two-dimensional coefficients')
    a, z, origin, cosine, sine = [tuple(Fraction(finite(v)) for v in row) for row in rows]
    determinant = cosine[0]*sine[1]-cosine[1]*sine[0]
    if not determinant:
        return None

    def adjoint(vector):
        return (sine[1]*vector[0]-sine[0]*vector[1],
                cosine[0]*vector[1]-cosine[1]*vector[0])

    start = adjoint(tuple(x-y for x, y in zip(a, origin)))
    delta = adjoint(tuple(x-y for x, y in zip(z, a)))
    # Q(A+tD) = |adj(M)(A-O+tD)|^2 - det(M)^2. It is convex.
    quadratic = sum(x*x for x in delta)
    linear = 2*sum(x*y for x, y in zip(start, delta))
    constant = sum(x*x for x in start)-determinant*determinant
    ends = (constant, quadratic+linear+constant)
    minimum = min(ends)
    if quadratic:
        t = -linear/(2*quadratic)
        if 0 < t < 1:
            minimum = min(minimum, (quadratic*t+linear)*t+constant)
    budget.check()
    if minimum > 0:
        return 'outside'
    if max(ends) < 0:
        return 'inside'
    return None
