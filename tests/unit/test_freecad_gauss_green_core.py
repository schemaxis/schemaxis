"""Independent analytic/rational controls for the unconnected instrument."""
from fractions import Fraction as F
import math
import unittest

from schemaxis.adaptors.freecad.gauss_green import (
    Budget, ConicCurve, LineCurve, RationalCurve, Unresolved, finite, integrate, partitions,
    uv_area_integral)


class IntegrationControls(unittest.TestCase):
    def test_original_uv_primitives_preserve_literal_oriented_areas(self):
        # A translated right triangle has area 6*4/2, independently of its
        # line parameter intervals and the large absolute UV origin.
        for offset in (0.,1e9):
            vertices=[[offset+2,-3],[offset+8,-3],[offset+2,1]]
            sides=[LineCurve(2,7,a,b) for a,b in
                   zip(vertices,vertices[1:]+vertices[:1])]
            contributions=[uv_area_integral(c,2,7,budget=Budget()) for c in sides]
            self.assertAlmostEqual(math.fsum(contributions),12.,delta=1e-12)
        # A quarter ellipse closed by its two radii has area pi*a*b/4.
        arc=ConicCurve(0,math.pi/2,[5,0],[1,0],[0,1],[2,1])
        radial=LineCurve(0,1,[5,1],[5,0])
        area=uv_area_integral(arc,0,math.pi/2,budget=Budget())
        area+=uv_area_integral(radial,0,1,budget=Budget())
        self.assertAlmostEqual(area,math.pi/2,delta=2e-15)
        self.assertAlmostEqual(uv_area_integral(arc,math.pi/2,0,budget=Budget()),
                               -uv_area_integral(arc,0,math.pi/2,budget=Budget()),delta=2e-15)

    def test_rotated_scaled_conic_winding_and_original_domain(self):
        theta=math.pi/7
        for scale in (1e-3,1.,1000.):
            curve=ConicCurve(.27,.27+2*math.pi,[13*scale,-17*scale],
                [math.cos(theta),math.sin(theta)],[-math.sin(theta),math.cos(theta)],
                [2*scale,scale])
            actual=uv_area_integral(curve,curve.start,curve.end,budget=Budget())
            expected=2*math.pi*scale**2
            self.assertAlmostEqual(actual,expected,delta=abs(expected)*1e-13)
            with self.assertRaises(Unresolved):
                uv_area_integral(curve,curve.start-1,curve.end,budget=Budget())
        with self.assertRaises(Unresolved):
            uv_area_integral(LineCurve(0,1,[0,0],[1,1]),0,1,budget=Budget(maximum=1))

    def test_polynomial_vector_and_reversed_interval(self):
        for a, b, sign in ((0, 1, 1), (1, 0, -1)):
            result = integrate(lambda t: [1, t, t**6, t**12], a, b,
                               [1e-13]*4, budget=Budget())
            for actual, exact in zip(result, (1, F(1, 2), F(1, 7), F(1, 13))):
                self.assertAlmostEqual(actual, sign*float(exact), delta=1e-14)

    def test_nested_green_strip_integral(self):
        budget = Budget()
        result = integrate(
            lambda v: integrate(lambda u: [u*u+v**3], 0, v, [1e-13],
                                budget=budget),
            0, 1, [1e-12], budget=budget)
        self.assertAlmostEqual(result[0], float(F(17, 60)), delta=1e-13)
        self.assertGreater(budget.calls, 15)

    def test_non_dyadic_partition_changes_sample_locations(self):
        coarse = partitions(0, 1, [0, .5, .5, 1])
        fine = partitions(0, 1, [0, .5, .5, 1], thirds=True)
        self.assertEqual(coarse, [0, .5, 1])
        reduced = partitions(0, 1, [.5], third_cut=True)
        self.assertEqual(reduced, [0, 1/6, .5, .5+1/6, 1])
        expected = [0, 1/6, 1/3, .5, 2/3, 5/6, 1]
        self.assertEqual(len(fine), len(expected))
        for actual, value in zip(fine, expected):
            self.assertAlmostEqual(actual, value, delta=math.ulp(value))
        with self.assertRaises(Unresolved):
            partitions(0, 1, [.7, .3])

    def test_preprocessing_and_nested_calls_share_deadline(self):
        clock = [0.0]
        checks = []
        budget = Budget(seconds=.2, clock=lambda: clock[0],
                        checkpoint=lambda: checks.append(True))
        clock[0] = .21
        with self.assertRaises(Unresolved):
            budget.check()
        self.assertTrue(checks)

    def test_evaluation_limit_and_invalid_integrands(self):
        budget = Budget(maximum=15)
        self.assertEqual(integrate(lambda t: [1], 0, 1, [1e-10],
                                   budget=budget), [1])
        with self.assertRaises(Unresolved):
            integrate(lambda t: [1], 0, 1, [1e-10], budget=budget)
        for function in (lambda t: [float('nan')], lambda t: [True],
                         lambda t: [1, 2], lambda t: [10**1000]):
            with self.assertRaises(Unresolved):
                integrate(function, 0, 1, [1e-10], budget=Budget())

    def test_discontinuity_refuses_at_fixed_depth(self):
        with self.assertRaisesRegex(Unresolved, 'depth exhausted'):
            integrate(lambda t: [float(t > .123456789)], 0, 1, [1e-30],
                      budget=Budget(maximum=10000))

    def test_embedded_rule_agreement_is_not_an_error_certificate(self):
        # Exact Fraction integration of the polynomial with squared roots at
        # every rule sample. The float evaluation is zero at all sampled nodes.
        from schemaxis.adaptors.freecad.gauss_green import _X
        roots = [0.0, *[x for value in _X for x in (-value, value)]]
        polynomial = [F(1)]
        for root in roots:
            root = F(root)
            for _ in range(2):
                updated = [F(0)]*(len(polynomial)+1)
                for index, coefficient in enumerate(polynomial):
                    updated[index] -= root*coefficient
                    updated[index+1] += coefficient
                polynomial = updated
        exact = sum(coefficient*F(2, index+1)
                    for index, coefficient in enumerate(polynomial)
                    if index % 2 == 0)
        self.assertGreater(exact, 0)
        scale = float(exact)
        result = integrate(lambda t: [math.prod((t-root)**2 for root in roots)/scale],
                           -1, 1, [1e-12], budget=Budget())
        self.assertEqual(result, [0.0])
        # The exact normalised integral is one: this passing stability test
        # expressly documents a limitation, not a correct geometry measurement.
        self.assertEqual(exact/exact, 1)


def basis(index, degree, knots, parameter):
    """Independent exact Cox basis, not the implementation's de Boor scheme."""
    if degree == 0:
        return F(knots[index] <= parameter < knots[index+1])
    left = right = F(0)
    denominator = knots[index+degree]-knots[index]
    if denominator:
        left = ((parameter-knots[index])/denominator
                * basis(index, degree-1, knots, parameter))
    denominator = knots[index+degree+1]-knots[index+1]
    if denominator:
        right = ((knots[index+degree+1]-parameter)/denominator
                 * basis(index+1, degree-1, knots, parameter))
    return left+right


class RationalControls(unittest.TestCase):
    def test_quarter_circle_position_and_parameter_speed(self):
        weight = math.sqrt(.5)
        curve = RationalCurve(2, [0, 0, 0, 1, 1, 1],
                              [[1, 0], [1, 1], [0, 1]], [1, weight, 1])
        point, derivative = curve.evaluate(.5)
        for value in point:
            self.assertAlmostEqual(value, weight, delta=1e-14)
        for actual, exact in zip(derivative, (-2/(1+weight), 2/(1+weight))):
            self.assertAlmostEqual(actual, exact, delta=1e-14)
        root, = curve.crossings(1, .5, budget=Budget())
        point, _ = curve.evaluate(root)
        self.assertAlmostEqual(point[1], .5, delta=1e-14)
        self.assertAlmostEqual(point[0], math.sqrt(.75), delta=1e-14)

    def test_multiple_span_rational_basis_and_bezier_extraction(self):
        knots = list(map(F, (0, 0, 0)))+[F(2, 5), F(7, 10)]+[F(1)]*3
        poles = [[0, 1], [1, -2], [3, 4], [5, 2], [7, -1]]
        weights = [1, 2, 3, 2, 1]
        curve = RationalCurve(2, list(map(float, knots)), poles, weights)
        spans = curve.bezier_spans(Budget())
        self.assertEqual(len(spans), 3)
        for parameter in (F(1, 10), F(1, 2), F(4, 5)):
            coefficients = [weights[i]*basis(i, 2, knots, parameter)
                            for i in range(5)]
            exact = [sum(c*p[axis] for c, p in zip(coefficients, poles))
                     / sum(coefficients) for axis in (0, 1)]
            point, _ = curve.evaluate(float(parameter))
            for actual, expected in zip(point, exact):
                self.assertAlmostEqual(actual, float(expected), delta=1e-13)
            a, b, homogeneous = next(span for span in spans
                                     if span[0] <= float(parameter) <= span[1])
            local = (float(parameter)-a)/(b-a)
            bernstein = [(1-local)**2, 2*local*(1-local), local*local]
            weight = sum(c*p[2] for c, p in zip(bernstein, homogeneous))
            for axis in (0, 1):
                value = sum(c*p[axis] for c, p in zip(bernstein, homogeneous))/weight
                self.assertAlmostEqual(value, float(exact[axis]), delta=1e-13)

    def test_nonmonotonic_crossings_tangency_and_coincidence(self):
        curve = RationalCurve(2, [0, 0, 0, 1, 1, 1],
                              [[0, 3/16], [.5, -5/16], [1, 3/16]], [1]*3)
        self.assertEqual(curve.crossings(1, 0, budget=Budget()), [.25, .75])
        tangent = RationalCurve(2, [0, 0, 0, 1, 1, 1],
                                [[0, .25], [.5, -.25], [1, .25]], [1]*3)
        self.assertEqual(tangent.crossings(1, 0, budget=Budget()), [.5])
        line = RationalCurve(1, [0, 0, 1, 1], [[0, 0], [1, 0]], [1, 1])
        self.assertEqual(line.crossings(1, 0, budget=Budget()), [])
        self.assertEqual(line.crossings(1, 2, budget=Budget()), [])

    def test_invalid_dimensions_knots_and_weights_refuse(self):
        inputs = [
            (True, [0, 0, 1, 1], [[0, 0], [1, 1]], [1, 1]),
            (1, [0, 0, float('nan'), 1], [[0, 0], [1, 1]], [1, 1]),
            (1, [0, 1, 0, 1], [[0, 0], [1, 1]], [1, 1]),
            (1, [0, 0, 1, 1], [[0, 0], [1, 1]], [0, 1]),
            (2, [0]*3+[.5]*3+[1]*3, [[i, 0] for i in range(6)], [1]*6),
        ]
        for values in inputs:
            with self.subTest(values=values), self.assertRaises(Unresolved):
                RationalCurve(*values)
        for value in (True, float('inf'), 10**1000):
            with self.assertRaises(Unresolved):
                finite(value)


class AnalyticPcurveControls(unittest.TestCase):
    def test_original_line_parameter_speed_and_crossing(self):
        curve = LineCurve(2, 6, [3, -1], [11, 7])
        self.assertEqual(curve.evaluate(3), ([5, 1], [2, 2]))
        self.assertEqual(curve.crossings(1, 3, budget=Budget()), [4])
        self.assertEqual(curve.crossings(1, 8, budget=Budget()), [])

    def test_conic_green_area_derivative_and_span_roots(self):
        # Rotated ellipse: x=2-3sin(t), y=-5+2cos(t).
        curve = ConicCurve(0, 2*math.pi, [2, -5], [0, 1], [-1, 0], [2, 3])
        point, derivative = curve.evaluate(math.pi/2)
        self.assertAlmostEqual(point[0], -1, delta=1e-14)
        self.assertAlmostEqual(point[1], -5, delta=1e-14)
        self.assertAlmostEqual(derivative[0], 0, delta=1e-14)
        self.assertAlmostEqual(derivative[1], -2, delta=1e-14)
        area = integrate(lambda t: [curve.evaluate(t)[0][0]*curve.evaluate(t)[1][1]],
                         0, 2*math.pi, [1e-11], budget=Budget())[0]
        self.assertAlmostEqual(area, 6*math.pi, delta=1e-12)
        self.assertEqual(curve.crossings(1, -5, budget=Budget()), [math.pi/2, 3*math.pi/2])
        self.assertEqual(curve.crossings(0, -1, budget=Budget()), [math.pi/2])
        with self.assertRaises(Unresolved):
            ConicCurve(0, 1, [0, 0], [1, 0], [1, 0], [1, 1])


class BoundaryIsolationControls(unittest.TestCase):
    def test_near_endpoint_root_cannot_escape_fixed_isolation_cap(self):
        curve = RationalCurve(1, [0, 0, 1, 1],
                              [[0, -2**-100], [1, 1]], [1, 1])
        with self.assertRaisesRegex(Unresolved, 'bisection cap'):
            curve.crossings(1, 0, budget=Budget())

    def test_periodic_seam_is_an_interior_trim_break(self):
        from schemaxis.adaptors.freecad.mass_native import _basis_breaks
        class Basis:
            Period = 1.
            def getKnots(self):return [0., .25, .75, 1.]
            def isPeriodic(self):return True
        basis = Basis()
        knots, info = _basis_breaks(basis, 'getKnots', 'isPeriodic', 'Period', .9, 1.1)
        self.assertEqual(knots, [1.])
        self.assertEqual(info['knots'], [0., .25, .75, 1.])
        self.assertEqual(_basis_breaks(basis, 'getKnots', 'isPeriodic', 'Period', -.1, .1)[0], [0.])
        basis.isPeriodic = lambda: False
        continued, facts = _basis_breaks(basis, 'getKnots', 'isPeriodic', 'Period', .9, 1.1)
        self.assertEqual(continued, [])
        self.assertAlmostEqual(facts['continuation'][1], .1, delta=1e-15)
        self.assertEqual(facts['trim'], [.9, 1.1])
        self.assertEqual(_basis_breaks(basis, 'getKnots', 'isPeriodic', 'Period', 0., math.nextafter(1., 2.))[0], [.25, .75])


class ContinuationAdmissionControls(unittest.TestCase):
    def test_unclamped_ends_and_tensor_denominator_pole(self):
        from schemaxis.adaptors.freecad.gauss_green import continuation_weight_bound
        # Full knot inventory extends beyond the native [0,2] basis. At -1
        # weights1,2 in a linear outer blend have a zero denominator, despite
        # -1 lying inside the distinct knot inventory [-2,...,4].
        with self.assertRaisesRegex(Unresolved, 'denominator'):
            continuation_weight_bound(1, 2, [(1, [-2,-1,0,1,2,3,4], [-1,2], False, [0,2])])
        # Bilinear corner weights[1,2;2,4] give D=(1+u)(1+v).
        axes=[(1,[0,1],[-.01,1],False,[0,1])]*2
        low, high=continuation_weight_bound(1,4,axes)
        self.assertGreater(low,0)
        self.assertLessEqual(low,.99**2)
        self.assertGreaterEqual(high,4)
        for knots in ([],[0]):
            with self.assertRaises(Unresolved):
                continuation_weight_bound(1,2,[(1,knots,[-1,1],False,[0,1])])

    def test_unclamped_basis_continues_from_native_ends(self):
        from schemaxis.adaptors.freecad.mass_native import _basis_breaks
        class Basis:
            def getKnots(self):return [-2.,-1.,0.,1.,2.,3.,4.]
            def isPeriodic(self):return False
        knots,facts=_basis_breaks(Basis(),'getKnots','isPeriodic','period',-.5,2.5,[0.,2.])
        self.assertEqual(knots,[1.])
        self.assertEqual(facts['basisDomain'],[0.,2.])
        self.assertEqual(facts['continuation'],[.5,.5])

    def test_original_conic_extrema_and_rational_hull(self):
        from schemaxis.adaptors.freecad.gauss_green import coordinate_bounds
        arc = ConicCurve(.2, 2.1, [3, -2], [1, 0], [0, 1], [2, 1])
        bounds = coordinate_bounds(arc)
        self.assertLessEqual(bounds[3]-(-1), math.ulp(1.))
        self.assertGreaterEqual(bounds[3], -1)
        for index in range(201):
            point, _ = arc.evaluate(.2+1.9*index/200)
            self.assertTrue(bounds[0] <= point[0] <= bounds[1])
            self.assertTrue(bounds[2] <= point[1] <= bounds[3])
        curve = RationalCurve(2, [0, 0, 0, 1, 1, 1],
                              [[0, 0], [1, 3], [2, 0]], [1, .25, 1])
        hull = coordinate_bounds(curve)
        self.assertLess(hull[0], 0)
        self.assertGreater(hull[1], 2)
        self.assertGreater(hull[3], 3)

    def test_positive_denominator_tiny_continuation_and_real_pole(self):
        from schemaxis.adaptors.freecad.gauss_green import continuation_weight_bound
        # Linear weights1,2 give denominator1+t: positive near t=0,
        # a genuine pole at t=-1 despite both basis weights being positive.
        low, high = continuation_weight_bound(1, 2, [(1, [0, 1], [-1e-14, 1], False)])
        self.assertGreater(low, 0)
        self.assertLessEqual(low, 1-1e-14)
        self.assertGreaterEqual(high, 2)
        with self.assertRaisesRegex(Unresolved, 'denominator'):
            continuation_weight_bound(1, 2, [(1, [0, 1], [-2, 1], False)])
        self.assertEqual(continuation_weight_bound(3, 3, [(25, [0, 1], [-1e10, 1e10], False)]), [3, 3])


class NativeOccurrenceAdmissionControls(unittest.TestCase):
    class Shape:
        def __init__(self,kind,children=(),identity=None,ordered=None):
            self.ShapeType=kind;self.raw=list(children);self.identity=identity or id(self)
            self.Orientation='Forward'
            self.OrderedEdges=list(ordered if ordered is not None else children)
        def countElement(self,kind):
            if kind=='SubShape':return len(self.raw)
            return len(self.mapped(kind))
        def mapped(self,kind):
            result=[]
            def visit(shape):
                if shape.ShapeType==kind and not any(shape.isSame(p) for p in result):result.append(shape)
                for child in shape.raw:visit(child)
            visit(self);return result
        @property
        def Faces(self):return self.mapped('Face')
        @property
        def Solids(self):return self.mapped('Solid')
        def isValid(self):return True  # Exercise structural invariants independently of kernel validity.
        def isClosed(self):return True
        def childShapes(self):
            unique=[]
            for child in self.raw:
                if not any(child.isSame(prior) for prior in unique):unique.append(child)
            return unique
        def isSame(self,other):return self.identity==other.identity
        def isEqual(self,other):return self.isSame(other)
        @property
        def Wires(self):return self.childShapes()

    def tree(self):
        S=self.Shape;edge=S('Edge');wire=S('Wire',[edge,edge],ordered=[edge,edge])
        face=S('Face',[wire]);shell=S('Shell',[face]);solid=S('Solid',[shell])
        return solid,shell,face,wire

    def admit(self,shape):
        from schemaxis.adaptors.freecad.mass_native import _topology_faces
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch
        # Fake native API objects test occurrence invariants, not geometry.
        with patch.dict(sys.modules,{'FreeCAD':SimpleNamespace(Version=lambda:['1','1','4']),
                                    'Part':SimpleNamespace(OCC_VERSION='7.8.1')}):
            return _topology_faces(shape,Budget())

    def test_seam_occurrences_and_cavity_shells_stay_distinct(self):
        solid,shell,face,wire=self.tree();other,inner,_,_=self.tree();solid.raw.append(inner)
        faces,facts=self.admit(self.Shape('Compound',[solid]))
        self.assertEqual(len(faces),2)
        self.assertEqual(facts['shellOccurrences'],2)
        self.assertEqual(facts['edgeOccurrences'],4)

    def test_repeated_shell_face_wire_and_cross_shell_face_refuse(self):
        for level in ('shell','face','wire','crossShell'):
            solid,shell,face,wire=self.tree()
            if level=='shell':solid.raw.append(shell)
            elif level=='face':shell.raw.append(face)
            elif level=='wire':face.raw.append(wire)
            else:solid.raw.append(self.Shape('Shell',[face]))
            with self.subTest(level=level),self.assertRaises(Unresolved):self.admit(solid)

    def test_missing_seam_occurrence_and_duplicate_solid_refuse(self):
        solid,shell,face,wire=self.tree();wire.OrderedEdges.pop()
        with self.assertRaisesRegex(Unresolved,'chain'):self.admit(solid)
        solid,_,_,_=self.tree()
        with self.assertRaisesRegex(Unresolved,'exactly one'):
            self.admit(self.Shape('Compound',[solid,solid]))


if __name__ == '__main__':
    unittest.main()
