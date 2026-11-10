"""Independent host proof of named cylindrical walls, from mesh coordinates only.

No Gmsh import and no native entity numbers. For an axis index a, the transverse
indices (i, j) = (a+1, a+2) mod 3 make (i, j, a) cyclic, so theta = atan2(y_j, y_i)
is right-handed about +axis and (radial, tangential, axial) is a right-handed
frame. The unrolled wall coordinates are (r*theta, axial) and a triangle with
positive unrolled orientation has its normal pointing away from the axis.
"""
import math

from .mesh import check

PI = math.pi
SIDES = ('inner', 'outer')
COSINE_FLOOR = 1e-6


def frame(axis):
    a = 'xyz'.index(axis)
    return (a+1) % 3, (a+2) % 3, a


def locate(point, group):
    """Radial distance, angle and axial coordinate of a point about the group's axis."""
    i, j, a = frame(group['axis'])
    dx, dy = point[i]-group['centre'][i], point[j]-group['centre'][j]
    return math.hypot(dx, dy), math.atan2(dy, dx), point[a]


def unwrap(angles):
    """Angles relative to the first, each wrapped into (-pi, pi]."""
    first = angles[0]
    return [0.0]+[(value-first+PI) % (2*PI)-PI for value in angles[1:]]


def wall_triangle(points, group):
    """Geometry of a triangle if all vertices lie on the cylinder wall, else None.

    A triangle whose vertices share one axial coordinate is an axis-normal rim
    triangle, never wall. The unwrapped angular range must stay below pi so the
    axis lies outside the transverse projection and the unrolled map is one to one.
    """
    located = [locate(p, group) for p in points]
    tolerance = group['tolerance']
    if any(abs(radial-group['radius']) > tolerance for radial, _, _ in located):
        return None
    axial = [z for _, _, z in located]
    if max(axial)-min(axial) <= tolerance:
        return None
    angles = unwrap([theta for _, theta, _ in located])
    return {'angles': angles, 'axial': axial,
            'range': max(angles)-min(angles), 'residual': max(abs(r-group['radius']) for r, _, _ in located)}


def unrolled_area(wall, radius):
    """Signed area in (r*theta, axial) coordinates, positive for a normal facing away from the axis."""
    (a0, a1, a2), (z0, z1, z2) = wall['angles'], wall['axial']
    return 0.5*radius*((a1-a0)*(z2-z0)-(a2-a0)*(z1-z0))


def outward_sign(triangle, opposite):
    """+1 when the stored vertex order has its normal pointing away from the adjacent tetrahedron."""
    a, b, c = triangle
    u, v = [b[k]-a[k] for k in range(3)], [c[k]-a[k] for k in range(3)]
    normal = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
    toward = sum(normal[k]*(opposite[k]-a[k]) for k in range(3))
    check(toward != 0, 'wall triangle is coplanar with its adjacent tetrahedron')
    return -1 if toward > 0 else 1


def flat_cosine(group, triangle, sign):
    """Cosine between the outward facet normal and the radial direction at the facet centroid."""
    a, b, c = triangle
    u, v = [b[k]-a[k] for k in range(3)], [c[k]-a[k] for k in range(3)]
    normal = [sign*x for x in (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])]
    i, j, _ = frame(group['axis'])
    radial = [0.0, 0.0, 0.0]
    radial[i] = math.fsum(p[i] for p in triangle)/3-group['centre'][i]
    radial[j] = math.fsum(p[j] for p in triangle)/3-group['centre'][j]
    length = math.sqrt(sum(x*x for x in normal))*math.sqrt(sum(x*x for x in radial))
    check(length > 0, 'cylinder wall facet is degenerate or centred on the axis')
    return sum(normal[k]*radial[k] for k in range(3))/length


def side_of(wall, radius, triangle, opposite, group=None):
    """('outer' | 'inner', outward unrolled area, flat cosine) from the adjacent tetrahedron's orientation.

    The flat cosine is None when no group is supplied. With a group, the two independent
    forms must agree and clear a determinacy floor, or the facet is refused.
    """
    sign = outward_sign(triangle, opposite)
    area = sign*unrolled_area(wall, radius)
    cosine = None
    if group is not None:
        cosine = flat_cosine(group, triangle, sign)
        check(abs(cosine) >= COSINE_FLOOR, 'cylinder wall facet side is indeterminate (nearly tangent facet)')
        check(area == 0 or (cosine > 0) == (area > 0), 'cylinder wall facet side differs between flat and unrolled forms')
    return ('outer' if area > 0 else 'inner'), area, cosine


def segment_distance(point, start, end):
    dx, dy = end[0]-start[0], end[1]-start[1]
    length = dx*dx+dy*dy
    t = 0.0 if length == 0 else max(0.0, min(1.0, ((point[0]-start[0])*dx+(point[1]-start[1])*dy)/length))
    return math.hypot(point[0]-start[0]-t*dx, point[1]-start[1]-t*dy)


def projected_distance(group, points):
    """Distance from the axis to the triangle's transverse projection; zero if the axis is inside."""
    i, j, _ = frame(group['axis'])
    origin = (group['centre'][i], group['centre'][j])
    tri = [(p[i], p[j]) for p in points]
    signs = [(origin[0]-b[0])*(a[1]-b[1])-(a[0]-b[0])*(origin[1]-b[1])
             for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0]))]
    if not (any(s < 0 for s in signs) and any(s > 0 for s in signs)):
        return 0.0
    return min(segment_distance(origin, tri[k], tri[(k+1) % 3]) for k in range(3))


def chord_deviation(group, points):
    """Radius minus the nearest approach of the facet to the axis (largest gap to the true wall)."""
    return max(0.0, group['radius']-projected_distance(group, points))


def segments(radius, deviation):
    """Regular-polygon segment count whose chord deviation equals the measured one; None for no deviation."""
    if deviation <= 0:
        return None
    if deviation >= radius:
        return 0.0
    return PI/math.acos(1-deviation/radius)


def matches(points, group):
    return wall_triangle(points, group) is not None


def adjacent(data):
    """Boundary triangle (sorted vertices) to the opposite vertex of its single adjacent tetrahedron."""
    result = {}
    for dimension, _, vertices in data['cells']:
        if dimension != 3:
            continue
        for k in range(4):
            face = tuple(sorted(vertices[:k]+vertices[k+1:]))
            result[face] = result[face]+(vertices[k],) if face in result else (vertices[k],)
    return {face: opposite[0] for face, opposite in result.items() if len(opposite) == 1}


def measure(data, group, tag, opposite=None):
    """Prove every triangle of one named wall and return its measured report.

    Fails for any triangle that is not on the cylinder, spans half a turn or more,
    or faces the wrong material side. Every triangle must carry the authored side's
    orientation, so the unrolled map has no fold and the sum is the unrolled area.
    """
    opposite = adjacent(data) if opposite is None else opposite
    count, area, residual, deviation = 0, 0.0, 0.0, 0.0
    lower, upper, span = math.inf, -math.inf, 0.0
    for dimension, physical, vertices in data['cells']:
        if dimension != 2 or physical != tag:
            continue
        points = [data['nodes'][n] for n in vertices]
        wall = wall_triangle(points, group)
        check(wall is not None, 'cylinder group triangle is off its wall or an axis-normal rim triangle')
        check(wall['range'] < PI, 'cylinder wall triangle spans half a turn or more')
        apex = opposite.get(tuple(sorted(vertices)))
        check(apex is not None, 'cylinder wall triangle lacks one adjacent tetrahedron')
        side, oriented, _ = side_of(wall, group['radius'], points, data['nodes'][apex], group)
        check(oriented != 0, 'cylinder wall triangle is degenerate in unrolled coordinates')
        check(side == group['side'], 'cylinder wall material side differs from authored side')
        count += 1
        area += oriented if side == 'outer' else -oriented
        residual = max(residual, wall['residual'])
        deviation = max(deviation, chord_deviation(group, points))
        span = max(span, wall['range'])
        lower, upper = min(lower, *wall['axial']), max(upper, *wall['axial'])
    check(count > 0, 'cylinder group has no triangles')
    return {'triangles': count, 'unrolledArea': area, 'maximumVertexResidual': residual,
            'maximumChordDeviation': deviation, 'maximumAngularSpan': span,
            'axialRange': [lower, upper]}


def classify(points, plane_matches, groups):
    """Cylinder index for a triangle after planes had their chance, or None; refuse overlaps."""
    if plane_matches:
        return None
    found = [index for index, group in enumerate(groups) if matches(points, group)]
    check(len(found) <= 1, 'boundary triangle matches overlapping cylinder selectors')
    return found[0] if found else None
