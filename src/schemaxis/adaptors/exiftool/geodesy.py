"""Great-circle interpolation, spherical distance and exact rounding for the location workflows (host-only, standard library).

Interpolation models a constant-speed great-circle path between two fixes on a sphere. The true path between fixes is unknown, so no
accuracy is claimed; geodetic latitude is treated as spherical latitude, which is a stated approximation and not a datum conversion.
Results are rounded half-even to 9 decimal places of degrees (about 0.1 mm) and 3 decimals of metres, so that a verifier recomputing from
the retained track reaches the same published literals.
"""
from decimal import Decimal, ROUND_HALF_EVEN
from fractions import Fraction
import math

MEAN_EARTH_RADIUS_M = 6371008.8
NEAR_POLE_DEGREES = Decimal('89.9999999')
ANTIPODAL_DEGREES = 179.0
TINY_OMEGA = 1e-12
DEGREE_QUANTUM = Decimal('1e-9')
METRE_QUANTUM = Decimal('1e-3')
BOUNDARY_WINDOW = 1e-3          # fraction of one last place around a rounding tie that the verifier treats as indeterminate


class Antipodal(ValueError):
    """The two fixes are nearly antipodal: the great circle between them is ill-conditioned or not unique."""


def vector(lat, lon):
    la, lo = math.radians(float(lat)), math.radians(float(lon))
    c = math.cos(la)
    return (c * math.cos(lo), c * math.sin(lo), math.sin(la))


def central_angle(a, b):
    """The angle in radians between two unit vectors, stable for small and near-antipodal separations."""
    cross = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    return math.atan2(math.sqrt(sum(x * x for x in cross)), sum(x * y for x, y in zip(a, b)))


def haversine_m(a, b):
    """Spherical distance in metres between two ``(lat, lon)`` degree pairs on the mean-radius sphere (labelled an approximation)."""
    la1, lo1, la2, lo2 = (math.radians(float(x)) for x in (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * MEAN_EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def round_degrees(value):
    """``(Decimal, tie)`` of a binary64 degree value rounded half-even to 9 places; ``tie`` marks a value within a hair of a rounding boundary."""
    exact = Decimal(value)
    rounded = exact.quantize(DEGREE_QUANTUM, ROUND_HALF_EVEN)
    place = abs(value) * 1e9
    tie = abs((place - math.floor(place)) - 0.5) < BOUNDARY_WINDOW
    return rounded + 0 if rounded else Decimal(0), tie


def wrap_longitude(value):
    """A longitude in [-180, 180): +180 becomes -180 (the GPX 1.1 range)."""
    return value if -180 <= value < 180 else Decimal(-180) if value == 180 else ((value + 180) % 360) - 180


def interpolate(a, b, f):
    """Position at fraction ``f`` (a ``Fraction`` in the open interval (0, 1)) of the great circle from ``a`` to ``b``.

    ``a`` and ``b`` are ``(lat, lon)`` of Decimals. Returns ``{'latitude', 'longitude', 'omegaDegrees', 'flags', 'roundingBoundary'}`` with Decimal degrees
    rounded half-even to 9 places and the longitude in [-180, 180); raises ``Antipodal`` above 179 degrees of separation.
    """
    if not Fraction(0) < f < Fraction(1):
        raise ValueError('interpolate needs 0 < f < 1; an exact fix is used as published')
    va, vb = vector(*a), vector(*b)
    omega = central_angle(va, vb)
    if math.degrees(omega) > ANTIPODAL_DEGREES:
        raise Antipodal('the span is nearly antipodal')
    t = float(f)
    if omega < TINY_OMEGA:
        p = va
    else:
        s = math.sin(omega)
        wa, wb = math.sin((1 - t) * omega) / s, math.sin(t * omega) / s
        p = tuple(wa * x + wb * y for x, y in zip(va, vb))
    lat = math.degrees(math.atan2(p[2], math.hypot(p[0], p[1])))
    lon = math.degrees(math.atan2(p[1], p[0]))
    rlat, tie_lat = round_degrees(lat)
    rlon, tie_lon = round_degrees(lon)
    rlon = wrap_longitude(rlon)
    flags = []
    if abs(rlat) > NEAR_POLE_DEGREES:
        flags.append('nearPole')
    if abs(rlon) == 180:
        flags.append('antimeridian')
    return {'latitude': rlat, 'longitude': rlon, 'omegaDegrees': math.degrees(omega), 'flags': flags, 'roundingBoundary': tie_lat or tie_lon}


def interpolate_altitude(e0, e1, f):
    """Linear altitude at fraction ``f``, exact in rationals and rounded half-even to 3 decimals (a Decimal in metres)."""
    value = Fraction(e0) + f * (Fraction(e1) - Fraction(e0))
    thousandths = round(value * 1000)          # Fraction rounding is half-even
    result = Decimal(thousandths) / 1000
    return result.quantize(METRE_QUANTUM) + 0 if thousandths else Decimal('0.000')


def fraction_of(t, t0, t1):
    """The exact fraction ``(t - t0) / (t1 - t0)`` of integer times."""
    return Fraction(t - t0, t1 - t0)


def text9(value):
    """Fixed nine-decimal text of a rounded degree value (``-180.000000000``, ``0.000000000``)."""
    return format(Decimal(value).quantize(DEGREE_QUANTUM, ROUND_HALF_EVEN), 'f')
