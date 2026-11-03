# Copyright (C) 2026 David L F Gaden
"""Formulation-independent geodesic anchor: the geodesic ODE on the implicit WGS84 surface.

No auxiliary sphere, Clairaut relation or series: for G(x) = x^2/a^2 + y^2/a^2 + z^2/b^2 - 1 the
unit-speed geodesic satisfies x'' = -(v^T H v / |grad G|^2) grad G with H = diag(2/a^2, 2/a^2,
2/b^2). Integrated by classical RK4 in ECEF with compensated (Kahan) accumulation at N and 2N
steps. Used by tests and qualification to anchor ``geodesy.direct``; not on the run path.
Shared inputs with the oracle: WGS84 a and 1/f, binary64 arithmetic and libm.

Error model (explicit engineering estimate, not certified): RK4 global error is O(h^4); the
Richardson estimate |x_2N - x_N| / 15 approximates the truncation error of the 2N solution, and
compensated accumulation keeps rounding near a few u * |x| plus the geodetic conversion.
"""
import math

A = 6378137.0
F = 1 / 298.257223563
B = A * (1 - F)
E2 = F * (2 - F)
U = 2.0 ** -53
D = (2 / A ** 2, 2 / A ** 2, 2 / B ** 2)


def ecef(lon, lat):
    sp, cp = math.sin(math.radians(lat)), math.cos(math.radians(lat))
    n = A / math.sqrt(1 - E2 * sp * sp)
    return [n * cp * math.cos(math.radians(lon)), n * cp * math.sin(math.radians(lon)), n * (1 - E2) * sp]


def geodetic(x, y, z):
    lon = math.degrees(math.atan2(y, x))
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1 - E2))
    for _ in range(60):
        sp = math.sin(lat)
        n = A / math.sqrt(1 - E2 * sp * sp)
        nxt = math.atan2(z + E2 * n * sp, p)
        if nxt == lat:
            break
        lat = nxt
    return lon, math.degrees(lat)


def enu(lon, lat):
    l, p = math.radians(lon), math.radians(lat)
    east = [-math.sin(l), math.cos(l), 0.0]
    north = [-math.sin(p) * math.cos(l), -math.sin(p) * math.sin(l), math.cos(p)]
    return east, north


def accel(x, v):
    grad = [D[0] * x[0], D[1] * x[1], D[2] * x[2]]
    k = (D[0] * v[0] * v[0] + D[1] * v[1] * v[1] + D[2] * v[2] * v[2]) / (grad[0] ** 2 + grad[1] ** 2 + grad[2] ** 2)
    return [-k * g for g in grad]


def integrate(lon, lat, azi, s, steps):
    """Return (lon2, lat2, azi2_deg, surface_residual, speed_drift, ecef_end)."""
    x = ecef(lon, lat)
    e, n = enu(lon, lat)
    a = math.radians(azi)
    v = [math.sin(a) * e[i] + math.cos(a) * n[i] for i in range(3)]
    cx, cv = [0.0] * 3, [0.0] * 3
    h = s / steps
    for _ in range(steps):
        k1v = accel(x, v); k1x = v
        x2 = [x[i] + 0.5 * h * k1x[i] for i in range(3)]; v2 = [v[i] + 0.5 * h * k1v[i] for i in range(3)]
        k2v = accel(x2, v2); k2x = v2
        x3 = [x[i] + 0.5 * h * k2x[i] for i in range(3)]; v3 = [v[i] + 0.5 * h * k2v[i] for i in range(3)]
        k3v = accel(x3, v3); k3x = v3
        x4 = [x[i] + h * k3x[i] for i in range(3)]; v4 = [v[i] + h * k3v[i] for i in range(3)]
        k4v = accel(x4, v4); k4x = v4
        for i in range(3):
            dx = h / 6 * (k1x[i] + 2 * k2x[i] + 2 * k3x[i] + k4x[i]) - cx[i]
            tx = x[i] + dx
            cx[i] = (tx - x[i]) - dx
            x[i] = tx
            dv = h / 6 * (k1v[i] + 2 * k2v[i] + 2 * k3v[i] + k4v[i]) - cv[i]
            tv = v[i] + dv
            cv[i] = (tv - v[i]) - dv
            v[i] = tv
    lon2, lat2 = geodetic(*x)
    e2, n2 = enu(lon2, lat2)
    azi2 = math.degrees(math.atan2(sum(v[i] * e2[i] for i in range(3)), sum(v[i] * n2[i] for i in range(3))))
    residual = x[0] ** 2 / A ** 2 + x[1] ** 2 / A ** 2 + x[2] ** 2 / B ** 2 - 1
    return lon2, lat2, azi2, residual, math.sqrt(sum(c * c for c in v)) - 1, list(x)


def anchor(lon, lat, azi, s, step_m=100.0):
    """Integrate at N and 2N steps; return the 2N endpoint with a Richardson error estimate."""
    steps = max(200, math.ceil(s / step_m))
    coarse = integrate(lon, lat, azi, s, steps)
    fine = integrate(lon, lat, azi, s, 2 * steps)
    richardson = math.dist(coarse[5], fine[5]) / 15
    rounding = 64 * U * (A + s)  # compensated accumulation + geodetic conversion (engineering estimate)
    return {'steps': [steps, 2 * steps], 'lon': fine[0], 'lat': fine[1], 'azi2': fine[2], 'surfaceResidual': fine[3],
            'speedDrift': fine[4], 'richardson_m': richardson, 'rounding_m': rounding,
            'coarseFineSeparation_m': math.dist(coarse[5], fine[5]),
            'richardsonAzi_deg': abs(((fine[2] - coarse[2]) + 180) % 360 - 180) / 15}
