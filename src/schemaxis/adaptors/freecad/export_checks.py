# Copyright (C) 2026 David L F Gaden
"""Host-only, CAD-kernel-independent checks of the published STL against native B-rep facts.

Native Mesh.Volume is not used: it accumulates float32 products about the world
origin and is wrong for far-placed parts. The host reads the binary STL, integrates
in float64 about a local origin (the native bounds centre), and checks signed
volume, centre of mass, bounds and directed-edge closure.

Error model (conditional engineering estimate, not a rigorous bound for arbitrary
topology). It assumes OCCT's meshing contract: mesh vertices lie on the surface,
planar faces are triangulated exactly, curved faces deviate by at most the meshing
linear deflection d, and the gap between mesh and surface is a thin layer:

  delta32   = sqrt(3) * Rmax * 2^-24            float32 rounding of each written vertex
  layer     = curvedArea * d + area * delta32   bound on |V_mesh - V| and on the unsigned layer
  roundoff  = n * r^3 * 2^-50                   float64 accumulation over n facets of radius r
  volumeAllowance = layer + roundoff
  comAllowance    = (layer * rc + n * r^3 * (r + |o - c|) * 2^-50) / (V - volumeAllowance)

rc is the largest distance from the native centre to the corners of the native
bounds expanded by d + delta32. The established 0.5 % relative / 1e-5 mm^3 absolute
volume acceptance remains an additional ceiling, now applied to the host volume.
A budget that is non-finite, negative or not smaller than the volume is refused as
uninformative. The per-axis report states whether a mirror about the bounds centre
would move the centre of mass beyond twice the allowance; it is not an identity
or orientation guarantee.
"""
import math
import struct
from pathlib import Path
from schemaxis.errors import fail

MAX_FACETS = 2000000
CHECK_EVERY = 65536   # facets between cooperative deadline/cancellation checks
EPS32 = 2.0**-24
EPS_SUM = 2.0**-50
ADVICE = 'reduce linearDeflection so the tessellation can meet the check, or inspect the native solid'


def _finite(values):
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values)


def native_facts(record, location):
    """Schema, type, finiteness and range checks on a native export snapshot."""
    if not isinstance(record, dict):
        fail('VERIFICATION_FAILED', 'Native export facts are missing', location)
    volume, area, curved = record.get('volume'), record.get('area'), record.get('curvedArea')
    bounds, centre, faces = record.get('bounds'), record.get('centreOfMass'), record.get('faces')
    if (record.get('valid') is not True or record.get('solids') != 1 or not _finite([volume, area, curved])
            or volume <= 0 or area <= 0 or not 0 <= curved <= area*(1+1e-9) or not isinstance(bounds, list) or len(bounds) != 6
            or not _finite(bounds) or any(bounds[2*k] > bounds[2*k+1] for k in range(3)) or not isinstance(centre, list)
            or len(centre) != 3 or not _finite(centre) or type(faces) is not int or faces < 1
            or any(not bounds[2*k]-1e-6*(1+abs(bounds[2*k])) <= centre[k] <= bounds[2*k+1]+1e-6*(1+abs(bounds[2*k+1])) for k in range(3))):
        fail('VERIFICATION_FAILED', 'Native export facts are malformed or out of range', location)
    return record


def integrals(path, origin):
    data = Path(path).read_bytes() if Path(path).stat().st_size <= 84+50*MAX_FACETS else None
    if data is None:
        fail('VERIFICATION_FAILED', 'Published STL exceeds the hardened verification bound', str(path),
             limit=MAX_FACETS, recovery='increase linearDeflection to publish a coarser mesh')
    if len(data) < 84:
        fail('VERIFICATION_FAILED', 'Published STL is not a binary STL', str(path))
    count = struct.unpack('<I', data[80:84])[0]
    if count < 4 or count > MAX_FACETS or len(data) != 84+50*count:
        fail('VERIFICATION_FAILED', 'Published STL facet count or size differs from a binary STL', str(path), facets=count)
    ox, oy, oz = origin
    volume = mx = my = mz = 0.0
    lo, hi = [math.inf]*3, [-math.inf]*3
    vertices, forward = {}, []
    radius = 0.0
    view = memoryview(data)[84:]
    from .step_source import checkpoint
    for index, record in enumerate(struct.iter_unpack('<12fH', view)):
        if index % CHECK_EVERY == 0:
            checkpoint()
        triangle = (record[3:6], record[6:9], record[9:12])
        ids = []
        for p in triangle:
            if not _finite(p):
                fail('VERIFICATION_FAILED', 'Published STL has a non-finite coordinate', str(path))
            for k in range(3):
                if p[k] < lo[k]: lo[k] = p[k]
                if p[k] > hi[k]: hi[k] = p[k]
            ids.append(vertices.setdefault(p, len(vertices)))
        if len(set(ids)) != 3:
            fail('VERIFICATION_FAILED', 'Published STL has a degenerate facet', str(path))
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = [(p[0]-ox, p[1]-oy, p[2]-oz) for p in triangle]
        radius = max(radius, math.sqrt(ax*ax+ay*ay+az*az), math.sqrt(bx*bx+by*by+bz*bz), math.sqrt(cx*cx+cy*cy+cz*cz))
        d = (ax*(by*cz-bz*cy) - ay*(bx*cz-bz*cx) + az*(bx*cy-by*cx))/6
        volume += d
        mx += d*(ax+bx+cx)/4; my += d*(ay+by+cy)/4; mz += d*(az+bz+cz)/4
        a, b, c = ids
        forward.extend(((a << 32) | b, (b << 32) | c, (c << 32) | a))
    checkpoint()
    unique = len(set(forward)) == len(forward)
    reverse = sorted(((code & 0xffffffff) << 32) | (code >> 32) for code in forward)
    checkpoint()
    closed = unique and sorted(forward) == reverse
    centre = [mx/volume+ox, my/volume+oy, mz/volume+oz] if volume else None
    return {'facets': count, 'signedVolume': volume, 'centreOfMass': centre, 'bounds': [lo[0], hi[0], lo[1], hi[1], lo[2], hi[2]],
            'closedConsistentlyOriented': closed, 'origin': list(origin), 'localRadius': radius,
            'maxCoordinate': max(max(abs(v) for v in lo), max(abs(v) for v in hi))}


def check_stl(path, native, deflection, location='model.stl'):
    """Compare the published STL with exact native facts; return the evidence and allowances."""
    native = native_facts(native, location)
    if not _finite([deflection]) or deflection <= 0:
        fail('VERIFICATION_FAILED', 'Meshing deflection evidence is missing or invalid', location)
    nb, c, V = native['bounds'], native['centreOfMass'], native['volume']
    origin = [(nb[2*k]+nb[2*k+1])/2 for k in range(3)]
    mesh = integrals(path, origin)
    if not mesh['closedConsistentlyOriented']:
        fail('VERIFICATION_FAILED', 'Published STL is not closed with consistently oriented facets', location)
    n, r = mesh['facets'], mesh['localRadius']
    delta32 = math.sqrt(3)*mesh['maxCoordinate']*EPS32
    layer = native['curvedArea']*deflection + native['area']*delta32
    roundoff = n*r**3*EPS_SUM
    volume_allowance = layer + roundoff
    corner = max(math.dist(c, tuple(nb[i]+(-1 if i % 2 == 0 else 1)*(deflection+delta32) for i in idx))
                 for idx in ((a, b, e) for a in (0, 1) for b in (2, 3) for e in (4, 5)))
    denominator = V - volume_allowance
    com_allowance = (layer*corner + n*r**3*(r+math.dist(origin, c))*EPS_SUM)/denominator if denominator > 0 else math.inf
    if not _finite([volume_allowance, com_allowance]) or volume_allowance < 0 or com_allowance < 0 or V <= volume_allowance:
        fail('VERIFICATION_FAILED', 'STL error budget is uninformative for this part', location,
             volume=V, volumeAllowance=volume_allowance, recovery=ADVICE)
    host = mesh['signedVolume']
    error = abs(host-V)
    ceiling = max(0.005*max(abs(host), abs(V)), 1e-5)
    if host <= 0:
        fail('VERIFICATION_FAILED', 'Published STL is inside-out (non-positive signed volume)', location, signedVolume=host)
    if error > volume_allowance or error > ceiling:
        fail('VERIFICATION_FAILED', 'Published STL volume differs from the native solid beyond its allowance', location,
             hostVolume=host, nativeVolume=V, allowance=volume_allowance, ceiling=ceiling, recovery=ADVICE)
    com_error = math.dist(mesh['centreOfMass'], c)
    if com_error > com_allowance:
        fail('VERIFICATION_FAILED', 'Published STL centre of mass differs from the native solid beyond its allowance', location,
             hostCentre=mesh['centreOfMass'], nativeCentre=c, allowance=com_allowance, recovery=ADVICE)
    slack = 1e-6 + 1e-9*mesh['maxCoordinate']
    for k in range(3):
        low, high = mesh['bounds'][2*k], mesh['bounds'][2*k+1]
        if not (nb[2*k]-delta32-slack <= low <= nb[2*k]+deflection+delta32+slack
                and nb[2*k+1]-deflection-delta32-slack <= high <= nb[2*k+1]+delta32+slack):
            fail('VERIFICATION_FAILED', 'Published STL bounds differ from the native solid beyond the deflection', location,
                 axis='xyz'[k], hostBounds=mesh['bounds'], nativeBounds=nb)
    centre = [(nb[2*k]+nb[2*k+1])/2 for k in range(3)]
    flips = {axis: {'centreShift': 2*abs(c[k]-centre[k]), 'detectable': 2*abs(c[k]-centre[k]) > 2*com_allowance}
             for k, axis in enumerate('xyz')}
    return {'host': mesh, 'deflection': deflection, 'delta32': delta32, 'volumeError': host-V,
            'volumeAllowance': volume_allowance, 'volumeCeiling': ceiling, 'centreError': com_error,
            'centreAllowance': com_allowance, 'mirrorDiscriminability': flips,
            'assumptions': 'vertices on surface; planar faces exact; curved chord deviation <= deflection; thin layer'}
