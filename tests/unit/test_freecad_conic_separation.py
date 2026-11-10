"""Strict whole-ellipse controls, including an interior secant discriminator."""
from decimal import Decimal, localcontext
from fractions import Fraction
import math
from types import SimpleNamespace
import unittest

from schemaxis.adaptors.freecad.conic_completion_separation import (
    separated_from_ideal_conic, conic_period_relation, _full_period_enclosure)
from schemaxis.adaptors.freecad.gauss_green import Budget, ConicCurve, MeasurementDeadline, Unresolved
from schemaxis.adaptors.freecad.mass_boundary_admission import separated_adjacent_curve,incidence_and_uv_admission
from schemaxis.adaptors.freecad.mass_boundary_native import CornerPiece,PairPiece


def conic(location=(0.,0.), cosine=(3.,0.), sine=(0.,3.)):
    return SimpleNamespace(location=location, cosine=cosine, sine=sine)


class WholeConicSeparationTests(unittest.TestCase):
    def test_equal_tokens_do_not_erase_a_surplus_turn_before_whole_incidence(self):
        # Large translated UV coordinates hide a real surplus turn in rounded
        # tokens. The complete two-chart formal chain previously bypassed the
        # period guard because it generated no connector at either corner.
        def state(width,origin=10.):
            curve=ConicCurve(0.,width,[origin,origin],[1.,0.],[0.,1.],[1.,1.])
            first=tuple(curve.evaluate(curve.start)[0]);last=tuple(curve.evaluate(curve.end)[0])
            self.assertEqual(first,last)
            vertex=SimpleNamespace();vertex.hashCode=lambda:1;vertex.isSame=lambda other:other is vertex
            edge=SimpleNamespace(firstVertex=lambda unused:vertex,lastVertex=lambda unused:vertex,
                                 Degenerated=False,isClosed=lambda:False)
            faces=[object(),object()]
            return {'occurrences':tuple((face,sign,edge,curve,1)for face,sign in zip(faces,(1,-1))),
                    'pairs':(PairPiece(0,1,-1,-1,1),),'poles':(),
                    'corners':tuple(CornerPiece(face,vertex,index,width,last,index,0.,first,sign,-sign,sign)
                                    for index,(face,sign)in enumerate(zip(faces,(1,-1))))}
        self.assertTrue(incidence_and_uv_admission(state(2*math.pi),Budget())['zeroBoundary'])
        for width,origin in ((math.nextafter(2*math.pi,math.inf),10.),(6.28318530717959,100.)):
            # Equal tokens alone do not supply the mandatory native closed-wire
            # context for the new explicitly declared auxiliary-lens policy.
            with self.subTest(width=width),self.assertRaisesRegex(Unresolved,'single-occurrence closed native wire'):
                incidence_and_uv_admission(state(width,origin),Budget())

    def test_quarter_circle_native_record_and_inside(self):
        self.assertEqual(separated_from_ideal_conic(
            [1.8369701987210297e-16,3.], [3.330669073875e-16,3.], conic(), Budget()), 'outside')
        self.assertEqual(separated_from_ideal_conic([-1.,0.], [1.,0.], conic(), Budget()), 'inside')

    def test_outside_endpoints_do_not_hide_a_secant_or_tangency(self):
        # Both endpoints are outside. The secant's interior is inside; the
        # tangent has an exact zero at its interior minimum. Neither separates.
        for first,last in (([-4.,0.],[4.,0.]), ([-1.,3.],[1.,3.])):
            self.assertIsNone(separated_from_ideal_conic(first,last,conic(),Budget()))

    def test_endpoint_zero_and_degenerate_matrix_stay_unresolved(self):
        self.assertIsNone(separated_from_ideal_conic([3.,0.],[4.,0.],conic(),Budget()))
        self.assertIsNone(separated_from_ideal_conic(
            [0.,4.],[1.,4.],conic(sine=(6.,0.)),Budget()))

    def test_rotated_non_dyadic_ellipse_against_decimal_coordinate_oracle(self):
        shape=conic((.2,-.6),(1.8,2.4),(-1.6,1.2))
        cases=[((2.,.2),(3.,.4),'outside'), ((-.3,.2),(.4,.3),'inside')]
        for p,q,expected in cases:
            points=[tuple(o+c*u+s*v for o,c,s in zip(shape.location,shape.cosine,shape.sine))
                    for u,v in (p,q)]
            with self.subTest(expected=expected),localcontext()as context:
                context.prec=100
                o,c,s=[tuple(Decimal(x)for x in row)for row in (shape.location,shape.cosine,shape.sine)]
                determinant=c[0]*s[1]-c[1]*s[0]
                # Independently solve M(u,v)=X-O in high-precision decimal
                # coordinates; the known normalised segments have ample margin.
                for index in range(17):
                    t=Decimal(index)/16
                    x,y=[Decimal(a)+(Decimal(b)-Decimal(a))*t-z
                         for a,b,z in zip(points[0],points[1],o)]
                    u=(s[1]*x-s[0]*y)/determinant
                    v=(c[0]*y-c[1]*x)/determinant
                    self.assertEqual(u*u+v*v>1,expected=='outside')
            self.assertEqual(separated_from_ideal_conic(*points,shape,Budget()),expected)

    def test_invalid_coefficients_and_existing_budget_faults(self):
        with self.assertRaises(Unresolved):
            separated_from_ideal_conic([math.inf,0.],[0.,0.],conic(),Budget())
        now=[0.];budget=Budget(seconds=1,clock=lambda:now[0]);now[0]=2.
        with self.assertRaises(MeasurementDeadline):
            separated_from_ideal_conic([0.,0.],[1.,0.],conic(),budget)
        self.assertEqual(budget.calls,0)

    def test_period_enclosure_and_overturned_conic_keep_original_domain(self):
        lower,upper=_full_period_enclosure()
        self.assertGreater(lower,Decimal('6.2831853071795864769252867665590057'))
        self.assertLess(upper,Decimal('6.2831853071795864769252867665590058'))
        for width,expected in ((2*math.pi,'shorter'),(6.28318530717959,'longer')):
            shape=ConicCurve(0.,width,[0.,0.],[1.,0.],[0.,1.],[3.,3.])
            self.assertEqual(conic_period_relation(shape,Budget()),expected)
        shape=ConicCurve(0.,6.28318530717959,[0.,0.],[-1.,0.],[0.,1.],[3.,3.])
        original=(shape.start,shape.end,tuple(shape.cosine),tuple(shape.sine))
        with self.assertRaisesRegex(Unresolved,'lens multiplicity is not 0/1'):
            separated_adjacent_curve(shape.evaluate(shape.end)[0],shape.evaluate(shape.start)[0],
                                     shape,[shape.start,shape.end],Budget(),closed=True)
        self.assertEqual((shape.start,shape.end,tuple(shape.cosine),tuple(shape.sine)),original)

    def test_actual_adjacent_quarter_record_and_endpoint_identity_precedes_proof(self):
        shape=ConicCurve(0.,math.pi/2,[0.,0.],[1.,0.],[0.,1.],[3.,3.])
        first=[1.8369701987210297e-16,3.];last=[3.330669073875e-16,3.];records=[]
        self.assertEqual(separated_adjacent_curve(first,last,shape,[shape.end],Budget(),
                         conic_separations=records),1)
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['floatingEndpoint'],first)
        self.assertEqual(records[0]['side'],'outside')
        self.assertFalse(records[0]['lawToEvaluatedEndpointGapModelled'])
        # The Q proof would pass this outside segment, but it has no declared
        # shared floating endpoint and must fail before reaching that proof.
        with self.assertRaisesRegex(Unresolved,'do not share the exact endpoint'):
            separated_adjacent_curve([2e-16,3.],last,shape,[shape.end],Budget())

    def test_overturned_circle_has_an_oppositely_wound_exterior_lens(self):
        # Independent rational witness, far below binary64 coordinate spacing.
        # X(t)=(-3 cos(t),3 sin(t)) has clockwise full-circle orientation.
        # Its native stored domain contains a further positive-angle arc.
        # Closing that arc by the tangent x=-3 encloses an EXTERIOR lens.
        period_lower=Fraction('6.2831853071795864769252867665590057')
        period_upper=Fraction('6.2831853071795864769252867665590058')
        width=Fraction(6.28318530717959)
        excess_lower,excess_upper=width-period_upper,width-period_lower
        self.assertTrue(0<excess_lower<excess_upper<Fraction(1,10**12))
        s=excess_lower/4
        x,y=-3+3*s*s/4,3*s
        self.assertGreater(x*x+y*y,9)  # Strictly outside the original disc.
        self.assertGreater(x,-3)        # Strictly right of the closing segment.
        # At this height the left circle root is -3 sqrt(1-s²).
        # Prove it is strictly RIGHT of the witness without rounded sqrt.
        self.assertLess(x,0)
        self.assertGreater(x*x,9*(1-s*s))
        # δ=asin(s) lies in (s,2s) for 0<s<1/2. Thus all three
        # horizontal-ray crossings δ, pi-δ, 2pi+δ precede the stored end.
        self.assertLess(2*s,excess_lower)
        # The float connector and any horizontal law-end closure are above
        # this witness or strictly left of its ray; neither adds a crossing.
        shape=ConicCurve(0.,float(width),[0.,0.],[-1.,0.],[0.,1.],[3.,3.])
        endpoint=shape.evaluate(shape.end)[0]
        self.assertEqual(endpoint[0],-3.)
        self.assertTrue(0<y<Fraction(endpoint[1]))
        ray_crossings=(1,-1,1)  # Sign(dy/dt) at those three exact roots.
        orientation=-1
        self.assertEqual(sum(ray_crossings)/orientation,-1)
        # A sampled/full-period approximation would erase this positive-area
        # lens and falsely label the completed winding as only 0 or 1.
        with self.assertRaisesRegex(Unresolved,'lens multiplicity is not 0/1'):
            separated_adjacent_curve(endpoint,shape.evaluate(0.)[0],shape,
                                     [shape.start,shape.end],Budget(),closed=True)


if __name__=='__main__':unittest.main()
