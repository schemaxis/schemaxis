"""Independent standard-library geodesic oracle for WGS84; never imports pyproj, PROJ or GeographicLib.

Theory: Bessel's auxiliary sphere with the exact distance and longitude integrals
(Karney 2013, J. Geodesy 87:43-55, doi:10.1007/s00190-012-0578-z, eqs. 7-8)::

    s / b  = integral sqrt(1 + k^2 sin^2 sigma) d sigma,     k^2 = e'^2 cos^2 alpha0
    lambda = omega - f sin(alpha0) integral (2 - f) / (1 + (1 - f) sqrt(1 + k^2 sin^2 sigma)) d sigma

PROJ (GeographicLib algorithms) and this module are separate implementations of the same theory.
PROJ evaluates truncated series and series-based Newton steps. This module evaluates the integrals
by composite Gauss-Legendre quadrature (truncation bounded analytically), solves the direct problem
by Newton on sigma and the inverse problem by Newton on its own direct solution, and reports the
final position residual. Formulation-independent anchors (exact equatorial arcs, meridian arcs by
quadrature over geodetic latitude and the surface-ODE integration in ``anchors.py``) check it.

Error model: ``error_m`` values are conditional engineering estimates, not certified intervals.
They assume parsed binary64 inputs, the qualified local shortest solution (at most 5000 km) and
libm sin/cos/atan2 within about one ulp. Separations below 1 mm use a local-metric regime whose
stated curvature term is also an engineering estimate. Results beyond 5000 km raise
OracleOutsideDomain and are never certified; zero or nonfinite Newton quantities raise
OracleIndeterminate. Constants: WGS84 a = 6378137 m, 1/f = 298.257223563 (NGA.STND.0036).
"""
import math

A = 6378137.0
F = 1 / 298.257223563
B = A * (1 - F)
E2 = F * (2 - F)
EP2 = E2 / (1 - E2)
U = 2.0 ** -53
R_MEAN = (2 * A + B) / 3  # IUGG mean radius R1, used only by the spherical discriminator
QUALIFIED_MAX_M = 5.0e6  # minimality argument and evidence cover geodesics up to 5000 km only
QUALIFIED_SLACK_M = 1e-6 + 1e-12 * QUALIFIED_MAX_M  # tau at the cap; absorbs native/oracle disagreement


class OracleIndeterminate(Exception):
    """The oracle cannot produce a qualified answer (zero/nonfinite Newton quantity)."""


class OracleOutsideDomain(Exception):
    """The converged geodesic lies outside the qualified distance domain; never certified."""


def _finite(*values):
    for v in values:
        if not isinstance(v, float) and not isinstance(v, int) or not math.isfinite(v):
            raise OracleIndeterminate('nonfinite oracle quantity')


def _gauss_legendre(n):
    nodes, weights = [], []
    for i in range(1, n + 1):
        x = math.cos(math.pi * (i - 0.25) / (n + 0.5))
        for _ in range(100):
            p0, p1 = 1.0, x
            for j in range(2, n + 1):
                p0, p1 = p1, ((2 * j - 1) * x * p1 - (j - 1) * p0) / j
            dp = n * (x * p1 - p0) / (x * x - 1)
            dx = p1 / dp
            x -= dx
            if abs(dx) < 1e-17:
                break
        p0, p1 = 1.0, x
        for j in range(2, n + 1):
            p0, p1 = p1, ((2 * j - 1) * x * p1 - (j - 1) * p0) / j
        dp = n * (x * p1 - p0) / (x * x - 1)
        nodes.append(x)
        weights.append(2 / ((1 - x * x) * dp * dp))
    return nodes, weights


GL_N = 16
NODES, WEIGHTS = _gauss_legendre(GL_N)
PANEL = 0.2  # maximum panel width in sigma (radians)


def quadrature_truncation_bound(h_half=PANEL / 2, rho=8.0, n=GL_N):
    """Rigorous Gauss-Legendre truncation bound for one panel (Trefethen 2008, Thm 4.5).

    Both integrands are analytic inside the Bernstein ellipse E_rho of the panel because
    1 + k^2 sin^2(z) only vanishes at |Im z| = asinh(1/k) >= asinh(1/e') ~ 3.19, while
    E_rho reaches |Im z| <= h (rho - 1/rho)/2 = 0.39 for h = 0.1, rho = 8. There
    |sin z|^2 <= cosh(0.39)^2 < 1.17, so |1 + k^2 sin^2 z| >= 1 - 0.0068*1.17 > 0.99 and
    both integrands are bounded by Mbound = 1.02. Error <= (64/15) M rho^(-2n)/(rho^2-1) * h.
    """
    im = h_half * (rho - 1 / rho) / 2
    s2 = math.cosh(im) ** 2
    assert EP2 * s2 < 0.5
    m_bound = max(math.sqrt(1 + EP2 * s2), (2 - F) / (1 + (1 - F) * math.sqrt(1 - EP2 * s2)))
    return 64 / 15 * m_bound * rho ** (-2 * n) / (rho * rho - 1) * h_half


def _integrals(s1, s2, k2):
    """Return (I1, I3) over [s1, s2] by composite Gauss-Legendre with fsum accumulation."""
    span = s2 - s1
    panels = max(1, math.ceil(abs(span) / PANEL))
    h = span / panels
    t1, t3 = [], []
    for p in range(panels):
        lo = s1 + p * h
        half = h / 2
        mid = lo + half
        for x, w in zip(NODES, WEIGHTS):
            sg = math.sin(mid + half * x)
            root = math.sqrt(1 + k2 * sg * sg)
            t1.append(w * half * root)
            t3.append(w * half * (2 - F) / (1 + (1 - F) * root))
    return math.fsum(t1), math.fsum(t3)


def wrap180(x):
    y = math.fmod(x, 360.0)
    if y > 180:
        y -= 360
    elif y <= -180:
        y += 360
    return y


def wrap_pi(x):
    y = math.fmod(x, 2 * math.pi)
    if y > math.pi:
        y -= 2 * math.pi
    elif y <= -math.pi:
        y += 2 * math.pi
    return y


def direct(lon1, lat1, azi1, s):
    """Return dict(lon, lat, azi2 [deg, forward azimuth at end], residual_m, sigma12)."""
    _finite(lon1, lat1, azi1, s)
    phi1 = math.radians(lat1)
    alpha1 = math.radians(azi1)
    sb1, cb1 = (1 - F) * math.sin(phi1), math.cos(phi1)
    r = math.hypot(sb1, cb1)
    sb1, cb1 = sb1 / r, cb1 / r
    sa1, ca1 = math.sin(alpha1), math.cos(alpha1)
    sa0 = sa1 * cb1
    ca0 = math.hypot(ca1, sa1 * sb1)
    sig1 = math.atan2(sb1, ca1 * cb1)
    om1 = math.atan2(sa0 * math.sin(sig1), math.cos(sig1))
    k2 = EP2 * ca0 * ca0
    target = s / B
    sig2 = sig1 + target
    for _ in range(50):
        i1, _i3 = _integrals(sig1, sig2, k2)
        step = (i1 - target) / math.sqrt(1 + k2 * math.sin(sig2) ** 2)  # denominator >= 1
        sig2 -= step
        _finite(sig2)
        if abs(step) <= 4 * U * max(1.0, abs(sig2)):
            break
    i1, i3 = _integrals(sig1, sig2, k2)
    residual = abs(B * i1 - s)
    ss2, cs2 = math.sin(sig2), math.cos(sig2)
    sb2 = ca0 * ss2
    cb2 = math.hypot(sa0, ca0 * cs2)
    alpha2 = math.atan2(sa0, ca0 * cs2)
    om2 = math.atan2(sa0 * ss2, cs2)
    om12 = wrap_pi(om2 - om1)
    lam12 = om12 - F * sa0 * i3
    phi2 = math.atan2(sb2, (1 - F) * cb2)
    _finite(residual, lam12, phi2, alpha2)
    return {'lon': lon1 + math.degrees(lam12), 'lat': math.degrees(phi2), 'azi2': math.degrees(alpha2),
            'residual_m': residual, 'sigma12': sig2 - sig1}


def radii(lat):
    sp = math.sin(math.radians(lat))
    w2 = 1 - E2 * sp * sp
    return A * (1 - E2) / w2 ** 1.5, A / math.sqrt(w2)


def local_separation(lon1, lat1, lon2, lat2):
    """Metres between nearby points by the local metric (M dphi, N cos(phi) dlambda)."""
    mid = (lat1 + lat2) / 2
    m, n = radii(mid)
    dn = math.radians(lat2 - lat1) * m
    de = math.radians(wrap180(lon2 - lon1)) * n * math.cos(math.radians(mid))
    return math.hypot(dn, de), dn, de


def rounding_estimate(s):
    """Engineering estimate of oracle floating-point error in metres (not a certified bound).

    Standard model: each quadrature term carries a few roundings (sin, sqrt, products, node and
    weight representation); fsum adds at most half an ulp. 32 u relative on the arc plus 32 u on
    the coordinate magnitude a (degree/radian conversion, trigonometric evaluation, atan2
    reconstruction) assuming libm sin/cos/atan2 within 1 ulp (glibc documented maxima).
    """
    return 32 * U * abs(s) + 32 * U * A


FLAT_MAX_M = 1e-3  # below 1 mm the Newton residual is dominated by 1-ulp coordinate quantisation (~0.8 nm)
M_MIN = A * (1 - E2)  # smallest WGS84 radius of curvature (meridian, at the equator)


def flat_inverse(r0, dn, de, lat1, lat2):
    """Sub-millimetre separations: local-metric distance with an explicit error model.

    Model (engineering estimate, not certified): the midpoint local metric differs from the
    geodesic by second-order curvature terms bounded here by 16 r^3 / M_min^2 * (1 + tan^2 phi)
    (<1e-18 m for r < 1 mm inside the band), plus rounding_estimate(r) for the coordinate
    arithmetic. Azimuths are the local-metric direction; meridian convergence over 1 mm changes
    them by < 1e-12 m of cross-track displacement. Exact coincidence returns s = 0 with azimuth 0.
    """
    phi = math.radians(max(abs(lat1), abs(lat2)))
    curvature = 16 * r0 ** 3 / M_MIN ** 2 * (1 + math.tan(phi) ** 2)
    azi = math.degrees(math.atan2(de, dn)) if r0 > 0 else 0.0
    return {'s': r0, 'azi1': azi, 'azi2': azi, 'residual_m': 0.0, 'iterations': 0, 'regime': 'flat',
            'error_m': curvature + rounding_estimate(r0)}


def inverse(lon1, lat1, lon2, lat2, max_iter=40):
    """Inverse problem by Newton iteration on the oracle direct problem.

    Returns dict(s, azi1, azi2, residual_m, iterations, error_m). Conditional on (i) the
    converged geodesic being the shortest one, argued only for s <= 5000 km (far shorter than
    the distance to the cut locus on the parallel through the antipodal point; longer results
    raise OracleOutsideDomain and are never certified) and (ii) the rounding model of
    rounding_estimate, error_m estimates |s - s_true| <= residual_m + direct residual +
    rounding_estimate(s) by the triangle inequality. It is an engineering estimate, not a
    certified interval bound. Zero/nonfinite Newton quantities raise OracleIndeterminate.
    """
    _finite(lon1, lat1, lon2, lat2)
    r0, dn0, de0 = local_separation(lon1, lat1, lon2, lat2)
    _finite(r0)
    if r0 < FLAT_MAX_M:
        return flat_inverse(r0, dn0, de0, lat1, lat2)
    start = vincenty_inverse(lon1, lat1, lon2, lat2)
    if start is None:
        start = spherical_inverse(lon1, lat1, lon2, lat2)
    s, azi = start['s'], start['azi1']
    _finite(s, azi)
    best = None
    for iteration in range(1, max_iter + 1):
        d = direct(lon1, lat1, azi, s)
        r, dn, de = local_separation(d['lon'], d['lat'], lon2, lat2)
        if best is None or r < best[0]:
            best = (r, s, azi, d, iteration)
        elif r >= best[0] and iteration > 3:
            break
        if r == 0:
            break
        a2 = math.radians(d['azi2'])
        along = dn * math.cos(a2) + de * math.sin(a2)
        cross = -dn * math.sin(a2) + de * math.cos(a2)
        # Approximate Jacobian only: the residual itself is always evaluated exactly, so an
        # inexact reduced length m12 slows convergence but cannot bias the converged result.
        if s > 1000:
            delta = 1e-6
            dd = direct(lon1, lat1, azi + math.degrees(delta), s)
            _rr, pn, pe = local_separation(d['lon'], d['lat'], dd['lon'], dd['lat'])
            m12 = (-pn * math.sin(a2) + pe * math.cos(a2)) / delta
        else:
            m12 = s  # flat limit; relative error O((s/R)^2) < 3e-8 here
        # Fail closed instead of dividing by a zero/nonfinite reduced length or iterating on
        # nonfinite values (degenerate start, hostile coordinates, near-coincident points).
        _finite(along, cross, m12)
        if not m12 > 0:
            raise OracleIndeterminate('zero or negative reduced-length Jacobian')
        s += along
        azi += math.degrees(cross / m12)
        _finite(s, azi)
        if not s > 0:
            raise OracleIndeterminate('nonpositive Newton distance iterate')
    r, s, azi, d, iteration = best
    if s > QUALIFIED_MAX_M + QUALIFIED_SLACK_M:
        raise OracleOutsideDomain(f'converged geodesic {s:.6f} m exceeds the qualified 5000 km domain')
    return {'s': s, 'azi1': azi, 'azi2': d['azi2'], 'residual_m': r, 'iterations': iteration, 'regime': 'newton',
            'error_m': r + d['residual_m'] + rounding_estimate(s)}


def vincenty_inverse(lon1, lat1, lon2, lat2):
    """Vincenty (1975) inverse; returns None when its lambda iteration does not converge."""
    L = math.radians(wrap180(lon2 - lon1))
    U1 = math.atan((1 - F) * math.tan(math.radians(lat1)))
    U2 = math.atan((1 - F) * math.tan(math.radians(lat2)))
    sU1, cU1, sU2, cU2 = math.sin(U1), math.cos(U1), math.sin(U2), math.cos(U2)
    lam = L
    for _ in range(200):
        sl, cl = math.sin(lam), math.cos(lam)
        ss = math.hypot(cU2 * sl, cU1 * sU2 - sU1 * cU2 * cl)
        if ss == 0:
            return None
        cs = sU1 * sU2 + cU1 * cU2 * cl
        sig = math.atan2(ss, cs)
        sa = cU1 * cU2 * sl / ss
        c2a = 1 - sa * sa
        c2sm = cs - 2 * sU1 * sU2 / c2a if c2a != 0 else 0.0
        C = F / 16 * c2a * (4 + F * (4 - 3 * c2a))
        prev = lam
        lam = L + (1 - C) * F * sa * (sig + C * ss * (c2sm + C * cs * (-1 + 2 * c2sm * c2sm)))
        if abs(lam - prev) < 1e-14:
            break
    else:
        return None
    u2 = c2a * EP2
    Aa = 1 + u2 / 16384 * (4096 + u2 * (-768 + u2 * (320 - 175 * u2)))
    Bb = u2 / 1024 * (256 + u2 * (-128 + u2 * (74 - 47 * u2)))
    ds = Bb * ss * (c2sm + Bb / 4 * (cs * (-1 + 2 * c2sm * c2sm) - Bb / 6 * c2sm * (-3 + 4 * ss * ss) * (-3 + 4 * c2sm * c2sm)))
    s = B * Aa * (sig - ds)
    a1 = math.degrees(math.atan2(cU2 * math.sin(lam), cU1 * sU2 - sU1 * cU2 * math.cos(lam)))
    a2 = math.degrees(math.atan2(cU1 * math.sin(lam), -sU1 * cU2 + cU1 * sU2 * math.cos(lam)))
    return {'s': s, 'azi1': a1, 'azi2': a2}


def spherical_inverse(lon1, lat1, lon2, lat2, radius=R_MEAN):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(wrap180(lon2 - lon1))
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    c = 2 * math.asin(min(1.0, math.sqrt(h)))
    az = math.degrees(math.atan2(math.sin(dl) * math.cos(p2), math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)))
    return {'s': radius * c, 'azi1': az}


def meridian_arc(lat1, lat2, panels=64):
    """Meridian arc length by quadrature of M(phi) over geodetic latitude (independent form)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = (p2 - p1) / panels
    terms = []
    for p in range(panels):
        half = h / 2
        mid = p1 + p * h + half
        for x, w in zip(NODES, WEIGHTS):
            sp = math.sin(mid + half * x)
            terms.append(w * half * A * (1 - E2) / (1 - E2 * sp * sp) ** 1.5)
    return abs(math.fsum(terms))


def equator_arc(lon1, lon2):
    return A * abs(math.radians(wrap180(lon2 - lon1)))


def vertex_latitude(lat1, azi1):
    """Maximum |latitude| reached by the full geodesic through (lat1, azi1) (Clairaut)."""
    phi1 = math.radians(lat1)
    sb1, cb1 = (1 - F) * math.sin(phi1), math.cos(phi1)
    r = math.hypot(sb1, cb1)
    cb1 /= r
    sa0 = abs(math.sin(math.radians(azi1)) * cb1)
    beta = math.acos(min(1.0, sa0))
    return math.degrees(math.atan(math.tan(beta) / (1 - F))) if beta < math.pi / 2 else 90.0
