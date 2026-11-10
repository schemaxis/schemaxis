"""Host-only proof of named cylindrical walls, from closed-form synthetic meshes."""
import math
import unittest

from schemaxis.adaptors.gmsh import cylinders, geometry, groups, mesh
from schemaxis.core.faults import SchemaxisError


def group(axis='z', centre=(0, 0, 0), radius=2.0, side='outer', tolerance=1e-6):
    return {'name': 'wall', 'axis': axis, 'centre': list(centre), 'radius': radius, 'side': side, 'tolerance': tolerance}


def place(g, radial, theta, axial):
    i, j, a = cylinders.frame(g['axis'])
    point = list(g['centre'])
    point[i] += radial*math.cos(theta)
    point[j] += radial*math.sin(theta)
    point[a] = axial
    return tuple(point)


def solid(g, bottom_angles, top_angles, lower, upper, flat=None):
    """A closed solid cone-decomposed about the axis midpoint. Wall tag 3, caps and any flat tag 2.

    The rings may be offset (antiprism) and omit an arc, closed by a chord strip (a D shape).
    """
    nodes, cells, ids = {}, [], iter(range(1, 10**6))
    def node(p):
        key = next(ids); nodes[key] = p; return key
    r = g['radius']
    bottom = [node(place(g, r, a, lower)) for a in bottom_angles]
    top = [node(place(g, r, a, upper)) for a in top_angles]
    centre_bottom, centre_top, middle = node(place(g, 0, 0, lower)), node(place(g, 0, 0, upper)), node(place(g, 0, 0, (lower+upper)/2))
    faces = []
    n = len(bottom)
    closed = flat is None
    for k in range(n if closed else n-1):
        j = (k+1) % n
        faces += [(3, (bottom[k], bottom[j], top[k])), (3, (bottom[j], top[j], top[k]))] if bottom_angles == top_angles else [
            (3, (bottom[k], bottom[j], top[k])), (3, (bottom[j], top[j], top[k]))]
    if flat:
        faces += [(2, (bottom[-1], bottom[0], top[-1])), (2, (bottom[0], top[0], top[-1]))]
    for k in range(n):
        j = (k+1) % n
        if closed or k < n-1 or flat:
            faces += [(2, (centre_bottom, bottom[j], bottom[k])), (2, (centre_top, top[k], top[j]))]
    for physical, vertices in faces:
        pts = [nodes[v] for v in vertices]
        cells.append((2, physical, vertices))
        ordered = vertices+(middle,) if mesh.determinant(*pts, nodes[middle]) >= 0 else (vertices[1], vertices[0], vertices[2], middle)
        cells.append((3, 1, ordered))
    return {'nodes': nodes, 'cells': cells, 'groups': {(2, 2): 'rest', (2, 3): 'wall', (3, 1): 'vol'}}


def prism(g, segments, lower, upper):
    angles = [2*math.pi*k/segments for k in range(segments)]
    return solid(g, angles, angles, lower, upper)


def triangle_area(points):
    a, b, c = points
    u, v = [b[k]-a[k] for k in range(3)], [c[k]-a[k] for k in range(3)]
    return 0.5*math.sqrt((u[1]*v[2]-u[2]*v[1])**2+(u[2]*v[0]-u[0]*v[2])**2+(u[0]*v[1]-u[1]*v[0])**2)


class CylinderProofTests(unittest.TestCase):
    def test_chord_deviation_matches_regular_polygon_closed_form(self):
        for axis in 'xyz':
            for segments in (8, 16, 36):
                g = group(axis, (3, -2, 5), 4.0)
                step = 2*math.pi/segments
                points = [place(g, 4.0, 0, 0), place(g, 4.0, step, 0), place(g, 4.0, 0, 1)]
                self.assertAlmostEqual(cylinders.chord_deviation(g, points), 4.0*(1-math.cos(math.pi/segments)), places=12)
                self.assertAlmostEqual(cylinders.segments(4.0, cylinders.chord_deviation(g, points)), segments, places=6)

    def test_axis_inside_the_projection_is_a_full_radius_gap_and_refused_as_a_wall(self):
        g = group()
        points = [place(g, 2, math.radians(a), z) for a, z in ((0, 0), (120, 1), (240, 0))]
        self.assertEqual(cylinders.projected_distance(g, points), 0.0)
        self.assertEqual(cylinders.chord_deviation(g, points), 2.0)
        self.assertGreaterEqual(cylinders.wall_triangle(points, g)['range'], math.pi)

    def test_full_wall_unrolled_area_is_exactly_two_pi_r_h_on_every_axis_and_placement(self):
        for axis, centre, side in (('x', (1, 2, 3), 'outer'), ('y', (-4, 0, 7), 'outer'), ('z', (0, 0, 0), 'outer')):
            g = group(axis, centre, 4.0, side)
            data = prism(g, 24, -1.5, 6.5)
            report = cylinders.measure(data, g, 3)
            self.assertAlmostEqual(report['unrolledArea'], 2*math.pi*4.0*8.0, places=9)
            self.assertAlmostEqual(report['axialRange'][0], -1.5)
            self.assertAlmostEqual(report['maximumChordDeviation'], 4.0*(1-math.cos(math.pi/24)), places=9)
            self.assertLess(report['maximumVertexResidual'], 1e-12)
            self.assertEqual(report['triangles'], 48)

    def test_side_follows_tetrahedron_orientation_even_when_every_vertex_is_on_the_cylinder(self):
        g = group()
        a, b, c = place(g, 2, 0, 0), place(g, 2, math.radians(30), 0), place(g, 2, math.radians(15), 1)
        wall = cylinders.wall_triangle([a, b, c], g)
        for apex, expected in ((place(g, 2, math.radians(180), 0.5), 'outer'), (place(g, 2, math.radians(15), 0.5), 'inner'),
                               (place(g, 0, 0, 0.5), 'outer'), (place(g, 5, math.radians(15), 0.5), 'inner')):
            self.assertEqual(cylinders.side_of(wall, 2, [a, b, c], apex)[0], expected)
            self.assertEqual(cylinders.side_of(cylinders.wall_triangle([a, c, b], g), 2, [a, c, b], apex)[0], expected)

    def test_wrong_authored_side_and_off_radius_vertex_are_refused(self):
        g = group()
        data = prism(g, 12, 0, 4)
        with self.assertRaises(SchemaxisError) as caught:
            cylinders.measure(data, dict(g, side='inner'), 3)
        self.assertIn('material side', caught.exception.fault.message)
        data['nodes'][1] = place(g, 2.0-1e-4, 0, 0)
        with self.assertRaises(SchemaxisError) as caught:
            cylinders.measure(data, g, 3)
        self.assertIn('off its wall', caught.exception.fault.message)

    def test_rim_chord_cap_triangle_is_never_wall_and_stays_remainder(self):
        g = group()
        rim = [place(g, 2, math.radians(a), 0) for a in (0, 100, 200)]
        self.assertIsNone(cylinders.wall_triangle(rim, g))
        data = {'nodes': dict(enumerate(rim, 1)), 'cells': [(2, 2, (1, 2, 3))]}
        mesh.verify_face_groups(data, [], [g])
        data['cells'] = [(2, 3, (1, 2, 3))]
        with self.assertRaises(SchemaxisError):
            mesh.verify_face_groups(data, [], [g])
        plane = {'axis': 'z', 'coordinate': 0, 'tolerance': 1e-6}
        data['cells'] = [(2, 3, (1, 2, 3))]
        mesh.verify_face_groups(data, [plane], [g])

    def test_inscribed_flat_is_geometrically_a_wall_so_a_remainder_tag_fails(self):
        g = group()
        flat = [place(g, 2, math.radians(a), z) for a, z in ((10, 0), (50, 0), (10, 3))]
        self.assertIsNotNone(cylinders.wall_triangle(flat, g))
        data = {'nodes': dict(enumerate(flat, 1)), 'cells': [(2, 2, (1, 2, 3))]}
        with self.assertRaises(SchemaxisError):
            mesh.verify_face_groups(data, [], [g])

    def test_partition_in_both_directions_and_overlap_refusal(self):
        g = group()
        data = prism(g, 12, 0, 4)
        mesh.verify_face_groups(data, [], [g])
        first = next(i for i, c in enumerate(data['cells']) if c[:2] == (2, 3))
        cells = list(data['cells']); cells[first] = (2, 2, cells[first][2])
        with self.assertRaises(SchemaxisError):
            mesh.verify_face_groups(dict(data, cells=cells), [], [g])
        twin = dict(g, name='twin')
        with self.assertRaises(SchemaxisError):
            mesh.verify_face_groups(data, [], [g, twin])
        cells = [(d, 3 if (d, p) == (2, 2) else p, v) for d, p, v in data['cells']]
        with self.assertRaises(SchemaxisError):
            mesh.verify_face_groups(dict(data, cells=cells), [], [g])

    def test_fold_or_double_cover_is_detected_by_the_primitive_area_identity(self):
        g = group()
        data = prism(g, 12, 0, 4)
        report = cylinders.measure(data, g, 3)
        source = {'filter': 'cylinder', 'options': {'origin': [0, 0, 0], 'axis': 'z', 'radius': 2.0, 'height': 4}}
        geometry.verify_wall(source, g, report)
        with self.assertRaises(SchemaxisError):
            geometry.verify_wall(source, g, dict(report, unrolledArea=report['unrolledArea']*1.01))
        with self.assertRaises(SchemaxisError):
            geometry.verify_wall(dict(source, options=dict(source['options'], radius=2.5)), g, report)

    def test_reviewer_f1_tetrahedron_with_every_vertex_on_the_cylinder(self):
        g = group(radius=5.0)
        a, b, c, d = (place(g, 5.0, math.radians(t), z) for t, z in ((0, 0), (30, 0), (40, 2), (10, 2)))
        self.assertAlmostEqual(abs(mesh.determinant(a, b, c, d)), 0.387740741, places=8)
        expected = {'ABD': ((a, b, d), c, 'outer', 0.996708), 'BCD': ((b, c, d), a, 'outer', 0.996708),
                    'ABC': ((a, b, c), d, 'inner', -0.978288), 'ACD': ((a, c, d), b, 'inner', -0.978288)}
        for label, (triangle, apex, side, cosine) in expected.items():
            wall = cylinders.wall_triangle(list(triangle), g)
            found, area, flat = cylinders.side_of(wall, 5.0, list(triangle), apex, g)
            self.assertEqual(found, side, label)
            self.assertAlmostEqual(flat, cosine, places=6, msg=label)
            self.assertAlmostEqual(abs(area), 5*math.pi/6, places=9)

    def test_reviewer_f2_helix_sliver_is_indeterminate_and_refused(self):
        g = group(radius=5.0)
        points = [place(g, 5.0, math.radians(t), z) for t, z in ((-12, -1), (0, 0), (12, 1))]
        self.assertAlmostEqual(triangle_area(points), 0.158, places=3)
        apex = (points[1][0]+0.3, points[1][1]-0.4, points[1][2]+0.2)
        nodes = dict(enumerate(points+[apex], 1))
        data = {'nodes': nodes, 'cells': [(2, 3, (1, 2, 3)), (3, 1, (1, 2, 3, 4))]}
        with self.assertRaises(SchemaxisError) as caught:
            cylinders.measure(data, g, 3)
        self.assertIn('indeterminate', caught.exception.fault.message)

    def test_reviewer_f3_antiprism_band_passes_although_flat_area_exceeds_the_cylinder(self):
        g = group(radius=10.0)
        step = 2*math.pi/12
        bottom = [step*k for k in range(12)]
        top = [step*(k+0.5) for k in range(12)]
        data = solid(g, bottom, top, 0.0, 1.0)
        flat = sum(triangle_area([data['nodes'][n] for n in v]) for d, p, v in data['cells'] if d == 2 and p == 3)
        self.assertAlmostEqual(flat, 65.623590, places=5)
        report = cylinders.measure(data, g, 3)
        self.assertAlmostEqual(report['unrolledArea'], 2*math.pi*10*1, places=9)
        self.assertGreater(flat, 2*math.pi*10*1)
        self.assertAlmostEqual(report['maximumChordDeviation'], 10*(1-math.cos(math.pi/12)), places=9)

    def test_complete_d_shaped_solid_with_flat_vertices_on_the_cylinder_is_refused(self):
        g = group(radius=4.0)
        cut = math.radians(40)
        arc = [cut+(2*math.pi-2*cut)*k/9 for k in range(10)]
        data = solid(g, arc, arc, 0.0, 2.0, flat=True)
        observed = mesh.inspect(data)
        self.assertEqual(observed['tetrahedra'], sum(1 for c in data['cells'] if c[0] == 3))
        flat = [v for d, p, v in data['cells'] if d == 2 and p == 2 and all(abs(data['nodes'][n][0]-4*math.cos(cut)) < 1e-9 for n in v)]
        self.assertEqual(len(flat), 2)
        with self.assertRaises(SchemaxisError) as caught:
            mesh.verify_face_groups(data, [], [g])
        self.assertIn('finer mesh', caught.exception.fault.message)

    def test_group_layout_has_one_tag_map(self):
        settings = {'boundaryName': 'rest', 'volumeName': 'vol', 'faceGroups': [{'name': 'a'}, {'name': 'b'}],
                    'cylinderGroups': [{'name': 'bore'}, {'name': 'outside'}]}
        self.assertEqual(groups.tags(settings), {'rest': 2, 'a': 3, 'b': 4, 'bore': 5, 'outside': 6})
        self.assertNotIn('rest', groups.tags(settings, remainder=False))
        self.assertEqual([g['tag'] for g in groups.expected(settings, False)], [3, 4, 5, 6, 1])
        legacy = {k: v for k, v in settings.items() if k != 'cylinderGroups'}
        self.assertEqual(groups.tags(legacy), {'rest': 2, 'a': 3, 'b': 4})


if __name__ == '__main__':
    unittest.main()
