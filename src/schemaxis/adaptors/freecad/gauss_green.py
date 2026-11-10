"""Bounded stdlib integration primitives for an unconnected CAD instrument.

Embedded-rule differences are heuristic estimates. Neither agreement between
rules nor agreement between partitions supplies a certified integration bound.
No public FreeCAD operation or verification policy calls this module yet.
"""
import bisect
import math
import time


class Unresolved(ValueError):
    """A numerical or resource precondition could not be established."""


class EvaluationLimit(Unresolved):
    """The fixed shared request or per-level evaluation cap was exhausted."""


class MeasurementDeadline(Unresolved):
    """The measurement's cooperative deadline was exhausted."""


def finite(value):
    if type(value) not in (int, float):
        raise Unresolved('a finite numeric value is required')
    try:
        value = float(value)
    except OverflowError as error:
        raise Unresolved('numeric conversion overflowed') from error
    if not math.isfinite(value):
        raise Unresolved('a finite numeric value is required')
    return value


class Budget:
    """One cooperative deadline shared by preprocessing and measurements.

The external native process runner still enforces its own hard timeout and
memory limit, including while a non-interruptible native call is in progress.
"""

    def __init__(self, maximum=4_000_000, seconds=240, *, checkpoint=None,
                 clock=time.monotonic):
        if type(maximum) is not int or not 1 <= maximum <= 12_000_000:
            raise Unresolved('invalid request evaluation budget')
        seconds = finite(seconds)
        if not 0 < seconds <= 2400:
            raise Unresolved('invalid request time budget')
        self.maximum = maximum
        self.calls = 0
        self.splits = 0
        self.clock = clock
        self.deadline = clock() + seconds
        self.checkpoint = checkpoint
        self.check()

    def check(self):
        if self.clock() >= self.deadline:
            raise MeasurementDeadline('shared measurement deadline exhausted')
        if self.checkpoint is not None:
            self.checkpoint()

    def tick(self):
        self.calls += 1
        if self.calls > self.maximum:
            raise EvaluationLimit('request evaluation budget exhausted')
        if self.calls % 256 == 0:
            self.check()


_X = (.9914553711208126, .9491079123427585, .8648644233597691,
      .7415311855993945, .5860872354676911, .4058451513773972,
      .2077849550078985)
_WK = (.02293532201052922, .06309209262997855, .1047900103222502,
       .1406532597155259, .1690047266392679, .1903505780647854,
       .2044329400752989, .2094821410847278)
_WG = (.1294849661688697, .2797053914892767, .3818300505051189,
       .4179591836734694)


def _vector(function, parameter, size, budget):
    budget.tick()
    values = function(parameter)
    if not isinstance(values, (list, tuple)) or len(values) != size:
        raise Unresolved('integrand component membership differs')
    return [finite(value) for value in values]


def _rule(function, start, end, size, budget):
    middle = start + (end - start)/2
    half = (end - start)/2
    centre = _vector(function, middle, size, budget)
    kronrod = [[_WK[7]*value] for value in centre]
    gauss = [[_WG[3]*value] for value in centre]
    for index, abscissa in enumerate(_X):
        left = _vector(function, middle-half*abscissa, size, budget)
        right = _vector(function, middle+half*abscissa, size, budget)
        for component in range(size):
            kronrod[component].extend((_WK[index]*left[component],
                                       _WK[index]*right[component]))
            if index in (1, 3, 5):
                weight = _WG[(index-1)//2]
                gauss[component].extend((weight*left[component],
                                         weight*right[component]))
    try:
        value = [finite(half*math.fsum(row)) for row in kronrod]
        estimate = [finite(abs(k-half*math.fsum(g)))
                    for k, g in zip(value, gauss)]
    except (OverflowError, ValueError) as error:
        raise Unresolved('non-finite integration result') from error
    return value, estimate


def integrate(function, start, end, tolerance, *, budget, depth=0):
    """Adaptive vector G7/K15, bounded at 18 levels and by the shared budget."""
    start, end = finite(start), finite(end)
    if (not isinstance(tolerance, (list, tuple))
            or not 1 <= len(tolerance) <= 16):
        raise Unresolved('invalid integration component budget')
    tolerance = [finite(value) for value in tolerance]
    if any(value <= 0 for value in tolerance):
        raise Unresolved('integration targets must be positive')
    if type(depth) is not int or not 0 <= depth <= 18:
        raise Unresolved('invalid adaptive depth')
    budget.check()
    if start == end:
        return [0.0]*len(tolerance)
    if end < start:
        return [-value for value in integrate(function, end, start, tolerance,
                                               budget=budget, depth=depth)]
    value, estimate = _rule(function, start, end, len(tolerance), budget)
    if all(error <= target for error, target in zip(estimate, tolerance)):
        return value
    if depth == 18:
        raise Unresolved('adaptive integration depth exhausted')
    middle = start + (end-start)/2
    if middle in (start, end):
        raise Unresolved('floating parameter resolution exhausted')
    budget.splits += 1
    targets = [target/2 for target in tolerance]
    left = integrate(function, start, middle, targets, budget=budget,
                     depth=depth+1)
    right = integrate(function, middle, end, targets, budget=budget,
                      depth=depth+1)
    return [finite(math.fsum((a, b))) for a, b in zip(left, right)]


def partitions(start, end, knots=(), *, thirds=False, third_cut=False):
    """Known spans, optionally with a non-dyadic fine partition."""
    start, end = finite(start), finite(end)
    if not start < end or len(knots) > 4096:
        raise Unresolved('invalid integration span inventory')
    values = [finite(value) for value in knots]
    if any(a > b for a, b in zip(values, values[1:])):
        raise Unresolved('knots must be non-decreasing')
    base = [start, *sorted(set(k for k in values if start < k < end)), end]
    if type(thirds) is not bool or type(third_cut) is not bool or (thirds and third_cut):
        raise Unresolved('invalid non-dyadic partition scheme')
    if not thirds and not third_cut:
        return base
    result = [start]
    for a, b in zip(base, base[1:]):
        result.extend((a+(b-a)/3, a+2*(b-a)/3, b) if thirds
                      else (a+(b-a)/3, b))
    if any(a >= b for a, b in zip(result, result[1:])):
        raise Unresolved('fine partition exhausted parameter resolution')
    return result


def _deboor(parameter, degree, knots, poles):
    span = min(len(poles)-1,
               max(degree, bisect.bisect_right(knots, parameter)-1))
    values = [list(poles[index])
              for index in range(span-degree, span+1)]
    for level in range(1, degree+1):
        for index in range(degree, level-1, -1):
            knot = span-degree+index
            denominator = knots[knot+degree-level+1]-knots[knot]
            alpha = (parameter-knots[knot])/denominator if denominator else 0.0
            values[index] = [(1-alpha)*a+alpha*b
                             for a, b in zip(values[index-1], values[index])]
    return values[degree]


def coordinate_bounds(curve):
    """Conservative finite envelope of the ORIGINAL admitted pcurve law.

Native face ParameterRange can describe a basis-clamped UV bound. Positive
rational control weights give a convex-hull envelope; conic extrema retain
their original angular parameter. No fitted approximation or sampled bound.
"""
    if isinstance(curve, RationalCurve):
        points = [[finite(p[i]/p[2]) for i in (0, 1)] for p in curve.poles]
        bounds = [(min(p[i] for p in points), max(p[i] for p in points))
                  for i in (0, 1)]
    elif isinstance(curve, LineCurve):
        points = [curve.evaluate(t)[0] for t in (curve.start, curve.end)]
        bounds = [(min(p[i] for p in points), max(p[i] for p in points))
                  for i in (0, 1)]
    elif isinstance(curve, ConicCurve):
        bounds = []
        for axis in (0, 1):
            values = [curve.evaluate(t)[0][axis] for t in (curve.start, curve.end)]
            phase = math.atan2(curve.sine[axis], curve.cosine[axis])
            first = math.ceil((curve.start-phase)/math.pi)
            last = math.floor((curve.end-phase)/math.pi)
            radius = math.hypot(curve.cosine[axis], curve.sine[axis])
            for turn in range(first, last+1):
                values.append(finite(curve.location[axis]
                                     + (radius if turn % 2 == 0 else -radius)))
            bounds.append((min(values), max(values)))
    else:
        raise Unresolved('unknown pcurve envelope')
    return [finite(math.nextafter(value, direction))
            for pair in bounds for value, direction in
            zip(pair, (-math.inf, math.inf))]


def continuation_weight_bound(minimum, maximum, axes):
    """Sufficient positive-denominator bound for tensor spline continuation.

Inside a knot span de Boor blends are convex. Outside the complete basis
domain, each blend coefficient can exceed [0,1] by at most distance divided
by the minimum distinct knot span. Expand the global weight interval for
each degree step and each continued coordinate, rounding outwards. Failure
to prove positivity refuses; success certifies only denominator positivity.
"""
    low, high = finite(minimum), finite(maximum)
    if not 0 < low <= high:
        raise Unresolved('invalid denominator weight range')
    if low == high:
        return [low, high]  # Constant denominator everywhere, including continuation.
    for axis in axes:
        degree, knots, domain, periodic, *basis = axis
        if periodic or degree == 0:
            continue
        if len(knots) < 2:
            raise Unresolved('nonuniform rational basis has no bounded knot spans')
        ends = basis[0] if basis else [knots[0], knots[-1]]
        # Unclamped splines have exterior knots beyond their native basis
        # bounds. Those knots do not move the polynomial continuation ends.
        left = (math.nextafter(finite(ends[0]-domain[0]), math.inf)
                if domain[0] < ends[0] else 0.)
        right = (math.nextafter(finite(domain[1]-ends[1]), math.inf)
                 if domain[1] > ends[1] else 0.)
        distance = finite(max(left, right))
        if distance == 0:
            continue
        span = min(math.nextafter(finite(b-a), -math.inf)
                   for a, b in zip(knots, knots[1:]))
        if span <= 0:
            raise Unresolved('native knot span has no positive outward lower bound')
        epsilon = finite(math.nextafter(finite(distance/span), math.inf))
        for _ in range(degree):
            width = finite(math.nextafter(finite(high-low), math.inf))
            change = finite(math.nextafter(finite(epsilon*width), math.inf))
            low = finite(math.nextafter(low-change, -math.inf))
            high = finite(math.nextafter(high+change, math.inf))
            if low <= 0:
                raise Unresolved('rational continuation denominator is unresolved')
    return [low, high]


class LineCurve:
    """Stored finite affine parameter law, evaluated with floating arithmetic.

    Slope construction and evaluation can round; the exact coefficient law's
    endpoint need not equal the floating evaluation at that parameter.
    """

    def __init__(self, start, end, first, last):
        self.start, self.end = finite(start), finite(end)
        if not self.start < self.end or len(first) != 2 or len(last) != 2:
            raise Unresolved('invalid original line domain')
        self.first = [finite(x) for x in first]
        self.slope = [finite((finite(b)-a)/(self.end-self.start))
                      for a, b in zip(self.first, last)]
        if not math.hypot(*self.slope) > 0:
            raise Unresolved('zero original line speed')
        self.knots = [self.start, self.end]

    def evaluate(self, parameter):
        parameter = finite(parameter)
        if not self.start <= parameter <= self.end:
            raise Unresolved('line evaluation outside domain')
        return ([finite(a+(parameter-self.start)*d)
                 for a, d in zip(self.first, self.slope)], list(self.slope))

    def crossings(self, axis, level, budget):
        budget.check()
        if axis not in (0, 1):
            raise Unresolved('invalid coordinate axis')
        level = finite(level)
        if self.slope[axis] == 0:
            return []
        root = finite(self.start+(level-self.first[axis])/self.slope[axis])
        return [root] if self.start < root < self.end else []


class ConicCurve:
    """Original angular circle/ellipse law, including exact parameter speed."""

    def __init__(self, start, end, location, xaxis, yaxis, radii):
        self.start, self.end = finite(start), finite(end)
        if not 0 < self.end-self.start <= 128*math.pi:
            raise Unresolved('invalid finite original conic domain')
        if any(len(v) != 2 for v in (location, xaxis, yaxis, radii)):
            raise Unresolved('invalid conic vector dimensions')
        self.location, xaxis, yaxis, radii = [list(map(finite, values))
                                           for values in (location, xaxis, yaxis, radii)]
        if (any(r <= 0 for r in radii)
                or abs(math.hypot(*xaxis)-1) > 1e-12
                or abs(math.hypot(*yaxis)-1) > 1e-12
                or abs(math.fsum(a*b for a, b in zip(xaxis, yaxis))) > 1e-12):
            raise Unresolved('invalid original conic axes or radii')
        self.cosine = [finite(radii[0]*v) for v in xaxis]
        self.sine = [finite(radii[1]*v) for v in yaxis]
        self.knots = [self.start, self.end]

    def evaluate(self, parameter):
        parameter = finite(parameter)
        if not self.start <= parameter <= self.end:
            raise Unresolved('conic evaluation outside domain')
        c, s = math.cos(parameter), math.sin(parameter)
        return ([finite(o+a*c+b*s) for o, a, b in
                 zip(self.location, self.cosine, self.sine)],
                [finite(-a*s+b*c) for a, b in zip(self.cosine, self.sine)])

    def crossings(self, axis, level, budget):
        budget.check()
        if axis not in (0, 1):
            raise Unresolved('invalid coordinate axis')
        a, b = self.cosine[axis], self.sine[axis]
        radius = math.hypot(a, b)
        ratio = finite((finite(level)-self.location[axis])/radius)
        if abs(ratio) > 1:
            return []
        phase, offset = math.atan2(b, a), math.acos(ratio)
        roots = set()
        for base in (phase-offset, phase+offset):
            first = math.ceil((self.start-base)/(2*math.pi))
            last = math.floor((self.end-base)/(2*math.pi))
            for turn in range(first, last+1):
                budget.tick()
                root = finite(base+turn*2*math.pi)
                if self.start < root < self.end:
                    roots.add(root)
        return sorted(roots)


def uv_area_integral(curve, start, end, *, budget):
    """Original line/conic integral of U dV, exact in real arithmetic.

    This supplies a signed orientation contribution, not a certified floating
    error bound. No fitted curve, translated domain or relaxed target is used.
    """
    start,end=finite(start),finite(end)
    if not curve.start<=min(start,end)<=max(start,end)<=curve.end:
        raise Unresolved('orientation integral exceeds original curve domain')
    budget.tick()
    if isinstance(curve,LineCurve):
        first,_=curve.evaluate(start)
        budget.tick()
        last,_=curve.evaluate(end)
        return finite((first[0]/2+last[0]/2)*(last[1]-first[1]))
    if not isinstance(curve,ConicCurve):
        raise Unresolved('orientation primitive requires an original line or conic')
    a,c=curve.cosine
    b,d=curve.sine
    centre=curve.location[0]
    delta=end-start
    middle=start+delta/2
    integrals=[delta,2*math.cos(middle)*math.sin(delta/2),
               2*math.sin(middle)*math.sin(delta/2),
               math.cos(2*middle)*math.sin(delta),
               math.sin(2*middle)*math.sin(delta)]
    coefficients=[(a*d-b*c)/2,centre*d,-centre*c,
                  (a*d+b*c)/2,(b*d-a*c)/2]
    return finite(math.fsum(x*y for x,y in zip(coefficients,integrals)))


class RationalCurve:
    """Finite clamped 2D rational spline and its parameter derivative.

The knot and pole limits are instrument admission limits, not exclusions of
required modelling families. A family exceeding them remains unqualified.
"""

    def __init__(self, degree, knots, poles, weights):
        if type(degree) is not int or not 1 <= degree <= 25:
            raise Unresolved('unsupported rational curve degree')
        if (not 2 <= len(poles) <= 2048 or len(knots) > 4096
                or len(knots) != len(poles)+degree+1
                or len(weights) != len(poles)):
            raise Unresolved('invalid rational curve dimensions')
        self.degree = degree
        self.knots = [finite(value) for value in knots]
        if any(a > b for a, b in zip(self.knots, self.knots[1:])):
            raise Unresolved('rational curve knots are not non-decreasing')
        self.start, self.end = self.knots[degree], self.knots[len(poles)]
        if (not self.start < self.end
                or self.knots[:degree+1] != [self.start]*(degree+1)
                or self.knots[-degree-1:] != [self.end]*(degree+1)):
            raise Unresolved('rational curve needs a clamped finite domain')
        for knot in set(self.knots[degree+1:-degree-1]):
            if self.knots.count(knot) > degree:
                raise Unresolved('discontinuous rational curve')
        weights = [finite(weight) for weight in weights]
        if any(weight <= 0 for weight in weights):
            raise Unresolved('rational curve weights must be positive')
        if any(not isinstance(pole, (list, tuple)) or len(pole) != 2
               for pole in poles):
            raise Unresolved('rational curve poles must be two-dimensional')
        self.poles = [tuple(finite(value) for value in
                            (finite(p[0])*w, finite(p[1])*w, w))
                      for p, w in zip(poles, weights)]
        self.derived = []
        for index in range(len(poles)-1):
            denominator = self.knots[index+degree+1]-self.knots[index+1]
            if denominator <= 0:
                raise Unresolved('invalid derivative knot interval')
            self.derived.append(tuple(finite(degree*(b-a)/denominator)
                                      for a, b in zip(self.poles[index],
                                                      self.poles[index+1])))
        self._segments = None

    def evaluate(self, parameter):
        parameter = finite(parameter)
        if not self.start <= parameter <= self.end:
            raise Unresolved('rational evaluation outside its domain')
        value = _deboor(parameter, self.degree, self.knots, self.poles)
        derivative = _deboor(parameter, self.degree-1, self.knots[1:-1],
                             self.derived)
        if value[2] <= 0:
            raise Unresolved('nonpositive rational denominator')
        point = [finite(value[index]/value[2]) for index in (0, 1)]
        tangent = [finite((derivative[index]-point[index]*derivative[2])/value[2])
                   for index in (0, 1)]
        return point, tangent

    def bezier_spans(self, budget):
        """Exact-form knot insertion, with a prospective allocation cap."""
        if self._segments is not None:
            return self._segments
        budget.check()
        degree = self.degree
        unique = sorted(set(self.knots[degree+1:-degree-1]))
        additions = sum(degree-self.knots.count(knot) for knot in unique)
        if len(self.poles)+additions > 16384:
            raise Unresolved('Bezier extraction allocation budget exhausted')
        knots, poles = list(self.knots), list(self.poles)
        for knot in unique:
            while knots.count(knot) < degree:
                budget.check()
                span = bisect.bisect_right(knots, knot)-1
                multiplicity = knots.count(knot)
                updated = [None]*(len(poles)+1)
                for index in range(span-degree+1):
                    updated[index] = poles[index]
                for index in range(span-multiplicity, len(poles)):
                    updated[index+1] = poles[index]
                for index in range(span-degree+1, span-multiplicity+1):
                    denominator = knots[index+degree]-knots[index]
                    if denominator <= 0:
                        raise Unresolved('invalid knot insertion interval')
                    alpha = (knot-knots[index])/denominator
                    updated[index] = tuple(finite((1-alpha)*a+alpha*b)
                                           for a, b in zip(poles[index-1],
                                                           poles[index]))
                if any(pole is None for pole in updated):
                    raise Unresolved('incomplete Bezier extraction')
                knots.insert(span+1, knot)
                poles = updated
        edges = [self.start, *unique, self.end]
        self._segments = [(a, b, poles[index*degree:index*degree+degree+1])
                          for index, (a, b) in enumerate(zip(edges, edges[1:]))]
        if any(len(segment[2]) != degree+1 for segment in self._segments):
            raise Unresolved('incomplete Bezier span inventory')
        return self._segments

    def crossings(self, axis, level, *, budget):
        """Isolate knot crossings using positive-weight Bezier convex hulls.

Unresolved tangencies or exhausted isolation budgets refuse; sampling does not
silently declare that a curve has no crossing.
"""
        if axis not in (0, 1) or type(axis) is not int:
            raise Unresolved('invalid curve axis')
        level = finite(level)
        roots = []
        pending = [(a, b, [finite(p[axis]-level*p[2]) for p in poles], 0)
                   for a, b, poles in self.bezier_spans(budget)]
        visited = 0
        while pending:
            budget.check()
            a, b, values, depth = pending.pop()
            visited += 1
            if visited > 8192 or len(roots) > 256:
                raise Unresolved('knot crossing isolation budget exhausted')
            if values[0] == 0:
                roots.append(a)
            if values[-1] == 0:
                roots.append(b)
            if min(values) >= 0 or max(values) <= 0:
                continue
            signs = [value > 0 for value in values if value != 0]
            variations = sum(x != y for x, y in zip(signs, signs[1:]))
            if (variations == 1 and values[0] != 0 and values[-1] != 0
                    and (values[0] > 0) != (values[-1] > 0)):
                left, right = a, b
                left_value = values[0]
                for _ in range(64):
                    budget.check()
                    middle = left+(right-left)/2
                    if middle in (left, right):
                        break
                    parameter = (middle-a)/(b-a)
                    work = list(values)
                    while len(work) > 1:
                        work = [(1-parameter)*x+parameter*y
                                for x, y in zip(work, work[1:])]
                    current = work[0]
                    if current == 0:
                        left = right = middle
                        break
                    if (current > 0) == (left_value > 0):
                        left, left_value = middle, current
                    else:
                        right = middle
                if left != right and math.nextafter(left, math.inf) != right:
                    raise Unresolved('knot crossing bisection cap exhausted')
                roots.append(left+(right-left)/2)
                continue
            if depth == 48:
                raise Unresolved('unresolved knot crossing or tangency')
            middle = a+(b-a)/2
            if middle in (a, b):
                raise Unresolved('knot isolation exhausted parameter resolution')
            work = list(values)
            left, right = [work[0]], [work[-1]]
            while len(work) > 1:
                work = [(x+y)/2 for x, y in zip(work, work[1:])]
                left.append(work[0])
                right.append(work[-1])
            pending.append((middle, b, list(reversed(right)), depth+1))
            pending.append((a, middle, left, depth+1))
        return sorted(set(root for root in roots if self.start < root < self.end))
