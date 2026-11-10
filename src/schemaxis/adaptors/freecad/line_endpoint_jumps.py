"""Pure diagnostics for nonintegrated stored-line endpoint-to-token jumps.

The three-point chart Green-one-form proxy is empirical, not a bound on native
evaluation, closure, skin/rung terms or quadrature. Callers supply the actual
ledger token and the native primitive, and retain ownership of native ticks.
"""
from fractions import Fraction
import math

from .gauss_green import LineCurve, Unresolved, finite


def _vector(values, size):
    if not isinstance(values, (tuple, list)) or len(values) != size:
        raise Unresolved('line endpoint diagnostic component membership differs')
    return [finite(value) for value in values]


def _rounded(value):
    try:
        return finite(float(value))
    except OverflowError as error:
        raise Unresolved('line endpoint diagnostic conversion overflowed') from error


def endpoint_jump(curve, token, budget):
    """Record the exact stored LineCurve END to the explicit ledger token.

    Original curves use evaluate(end); added connectors use piece.after, which
    need not equal connector.evaluate(end). No token or curve is moved. Records
    are internal diagnostics, not a parser for authored Fraction expressions.
    """
    budget.check()
    if not isinstance(curve, LineCurve):
        raise Unresolved('line endpoint diagnostic requires a stored LineCurve')
    start, end = finite(curve.start), finite(curve.end)
    first, slope, token = _vector(curve.first, 2), _vector(curve.slope, 2), _vector(token, 2)
    if not start < end:
        raise Unresolved('line endpoint diagnostic requires a positive original span')
    start_token=_vector(curve.evaluate(start)[0],2)
    if list(map(Fraction,start_token))!=list(map(Fraction,first)):
        raise Unresolved('stored line start differs from its evaluated endpoint token')
    exact = [Fraction(a)+Fraction(d)*(Fraction(end)-Fraction(start))
             for a, d in zip(first, slope)]
    ledger = list(map(Fraction, token))
    delta = [b-a for a, b in zip(exact, ledger)]
    budget.check()
    if not any(delta):
        return None
    absolute = [_rounded(abs(value)) for value in delta]
    if any(value and rounded == 0 for value, rounded in zip(delta, absolute)):
        raise Unresolved('nonzero exact line endpoint jump underflows binary64')
    samples = [[_rounded(value) for value in point]
               for point in (exact, [(a+b)/2 for a, b in zip(exact, ledger)], ledger)]
    budget.check()
    return {'originalParameterRange': [start, end],
            'exactLawEndpoint': list(map(str, exact)),
            'ledgerEndpointToken': token,
            'exactEndpointJump': list(map(str, delta)),
            'samplePoints': samples, 'absoluteDeltaUV': absolute,
            'nonIntegratedJump': True, 'certifiedNative': False}


def one_form_proxy(record, primitive, *, axis, envelope, budget):
    """Sample the actual chart primitive at ideal/mid/token rounded points.

    axis U means the U primitive multiplied by dV; axis V means the alternate
    V primitive multiplied by -dU. Only absolute diagnostic magnitudes result.
    Native evaluations/ticks belong to primitive; this helper checks deadlines
    and propagates its faults unchanged. All points pass preflight before calls.
    """
    budget.check()
    if axis not in ('U', 'V'):
        raise Unresolved('line endpoint proxy primitive axis differs')
    bounds = _vector(envelope, 4)
    if bounds[0] > bounds[1] or bounds[2] > bounds[3]:
        raise Unresolved('line endpoint proxy envelope is inverted')
    points = record['samplePoints']
    if not isinstance(points, (list, tuple)) or len(points) != 3:
        raise Unresolved('line endpoint proxy requires three sample points')
    points = [_vector(point, 2) for point in points]
    delta = _vector(record['absoluteDeltaUV'], 2)
    if any(value < 0 for value in delta):
        raise Unresolved('line endpoint proxy jump magnitude is negative')
    if any(not bounds[0] <= u <= bounds[1] or not bounds[2] <= v <= bounds[3]
           for u, v in points):
        raise Unresolved('line endpoint proxy sample exceeds preflight envelope')
    samples = []
    for point in points:
        budget.check()
        values = _vector(primitive(point), 5)
        budget.check()
        samples.append({'point': point, 'primitive': values})
    differential = delta[1 if axis == 'U' else 0]
    maxima = [max(abs(row['primitive'][index]) for row in samples) for index in range(5)]
    totals = [finite(differential*value) for value in maxima]
    return {'method': 'sampled-chart-green-one-form-simpson3/1',
            'scope': 'LineCurve law-to-token chart jumps only',
            'primitiveAxis': axis, 'samples': samples, 'totals': totals,
            'absoluteDifferential': differential, 'maximumAbsolutePrimitive': maxima,
            'bound': False, 'nonIntegratedJump': True}


def joint_choice(area_choice, choice_volume, line_totals, reference, centre,
                 origin, axis_levers, *, volume,lens_totals=None):
    """Combine empirical choices with one actual-volume denominator."""
    if not isinstance(area_choice, (list, tuple)):
        raise Unresolved('joint choice requires the area inventory')
    areas = [finite(value) for value in area_choice]
    choice_volume, reference, volume = map(finite, (choice_volume, reference, volume))
    lines = _vector(line_totals, 5)
    if any(x<0 for x in lines):raise Unresolved('joint line estimates must be nonnegative')
    if lens_totals is not None:
        lenses=_vector(lens_totals,5)
        if any(x<0 for x in lenses):raise Unresolved('joint conic lens estimates must be nonnegative')
        try:lines=[finite(math.fsum((a,b)))for a,b in zip(lines,lenses)]
        except OverflowError as error:raise Unresolved('joint conic lens proxy sum overflowed')from error
    centre, origin, levers = (_vector(values, 3) for values in (centre, origin, axis_levers))
    if (reference <= 0 or choice_volume < 0
            or any(value < 0 for value in [*areas, *lines, *levers])):
        raise Unresolved('joint choice requires nonnegative estimates and positive reference')
    try:
        area = finite(math.fsum([*areas, lines[0]]))
        error_volume = finite(math.fsum((choice_volume, lines[1])))
        if abs(volume) <= error_volume:
            raise Unresolved('joint empirical choice consumes the signed volume')
        denominator = finite(abs(volume)-error_volume)
        centres = []
        for index, (value, anchor, lever) in enumerate(zip(centre, origin, levers)):
            distance = finite(abs(value-anchor))
            numerator = finite(math.fsum((choice_volume*lever,
                                         reference*lines[index+2], distance*error_volume)))
            centres.append(finite(numerator/denominator))
    except OverflowError as error:
        raise Unresolved('joint empirical choice overflowed') from error
    return [area, error_volume, *centres]
