"""Coefficient-admitted original BSpline surface's ruled-U Green primitive.

A clamped degree-one U basis with two poles and identical corresponding
U-column weights has denominator independent of U. Thus S(U,V)=A(V)+U*B(V)
exactly, including rational V bases. The physical normal is affine in U;
volume flux is affine and first-moment fluxes are quadratic. G2 integrates
those polynomials, while area uses the norm-of-affine-vector primitive.

Full original U-span derivative anchors avoid dividing by a tiny trim span.
These real-arithmetic identities do not certify native floating-point error.
The caller retains original-chart, basis, continuation and topology admission.
"""
import math
from .gauss_green import EvaluationLimit, Unresolved, finite


def _norm_integral(mid, slope, half):
    """Integral of |mid+s*slope| on [-half,half], without close F subtraction."""
    a = finite(slope.Length)
    if a == 0:
        return finite(2*half*mid.Length)
    unit = slope*(1/a)
    p, k = finite(mid.dot(unit)), finite(mid.cross(unit).Length)
    x0, x1, delta = p-half*a, p+half*a, 2*half*a
    if delta == 0:
        raise Unresolved('ruled primitive cannot represent the angular variation')
    if k == 0:
        if x0 >= 0 or x1 <= 0:
            return finite(2*half*abs(p))
        return finite((x0*x0+x1*x1)/(2*a))
    r0, r1 = math.hypot(x0, k), math.hypot(x1, k)
    denominator = finite(r0+r1)
    difference = delta*(x1+x0)/denominator
    ratio = delta/denominator
    if ratio < 1:
        asinh_difference = 2*math.atanh(ratio)
    else:
        def scaled_asinh(x):
            q = abs(x)
            value = (math.asinh(q/k) if q <= k else
                     math.log(q)+math.log1p(math.hypot(1, k/q))-math.log(k))
            return math.copysign(value, x)
        asinh_difference = scaled_asinh(x1)-scaled_asinh(x0)
    value = finite((delta*r1+x0*difference+k*k*asinh_difference)/(2*a))
    if value < 0:
        raise Unresolved('ruled area primitive is negative')
    return value


def admit(surface):
    """Exact basis membership after the caller's bounded surface preflight."""
    if type(surface).__name__ != 'BSplineSurface':
        return False
    if surface.UDegree != 1 or surface.NbUPoles != 2 or surface.isUPeriodic():
        return False
    knots, multiplicities = surface.getUKnots(), surface.getUMultiplicities()
    if len(knots) != 2 or multiplicities != [2, 2]:
        return False
    weights = surface.getWeights()
    return len(weights) == 2 and weights[0] == weights[1]


def strip(face, u0, u, v, origin, reference, sign, budget, beginning, targets):
    """Preserve typed faults for unrepresentable arithmetic and native values."""
    try:
        return _strip(face, u0, u, v, origin, reference, sign,
                      budget, beginning, targets)
    except Unresolved:
        raise
    except (ArithmeticError, ValueError) as error:
        raise Unresolved('original ruled-U primitive is unrepresentable') from error


def _strip(face, u0, u, v, origin, reference, sign, budget, beginning, targets):
    import FreeCAD as App
    span = u-u0
    if span == 0:
        return [0.]*5
    half, middle = abs(span)/2, (u+u0)/2

    def tick():
        budget.tick()
        if budget.calls-beginning > 2_000_000:
            raise EvaluationLimit('one measurement evaluation cap exhausted')

    low, high = face.Surface.getUKnots()
    tick()
    point = face.valueAt(middle, v)
    tick()
    su, sv = face.derivative1At(low, v)
    tick()
    _, end_v = face.derivative1At(high, v)
    slope = su.cross((end_v-sv)*(1/(high-low)))
    normal = su.cross(sv)+slope*(middle-low)
    relative = point-App.Vector(*origin)
    if half == 0 or (slope.Length != 0 and 2*half*slope.Length == 0):
        # Outward nextafter envelopes at zero may have subnormal width.
        # Omit the entire strip only if its affine coefficient bounds fit
        # strictly inside the caller's already allocated local error target.
        width = abs(span)
        maximum_normal = normal.Length+width*slope.Length
        maximum_radius = relative.Length+width*su.Length
        maximum_dot = maximum_radius*maximum_normal
        bounds = [width*maximum_normal, width*maximum_dot/3,
                  *[width*(abs(x)+width*abs(dx))*maximum_dot/(4*reference)
                    for x, dx in zip(relative, su)]]
        if all(math.isfinite(x) and x <= target/16
               for x, target in zip(bounds, targets)):
            return [0.]*5
        raise Unresolved('subnormal ruled strip exceeds its allocated target')
    area = _norm_integral(normal, slope, half)
    terms = []
    for parameter in (-half/math.sqrt(3), half/math.sqrt(3)):
        point = relative+su*parameter
        current_normal = normal+slope*parameter
        dot = point.dot(current_normal)
        terms.append([sign*dot/3,
                      *[sign*x*dot/(4*reference) for x in point]])
    return [finite(math.copysign(area, span)),
            *[finite(span*math.fsum(row[i] for row in terms)/2)
              for i in range(4)]]
