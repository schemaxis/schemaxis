"""Literal/exact-oracle controls for a deliberately empirical chart diagnostic."""
from fractions import Fraction
import math
import unittest

from schemaxis.adaptors.freecad.gauss_green import (
    Budget, EvaluationLimit, LineCurve, MeasurementDeadline, Unresolved)
from schemaxis.adaptors.freecad.line_endpoint_jumps import (
    endpoint_jump, joint_choice, one_form_proxy)
from schemaxis.core.faults import SchemaxisError
from schemaxis.errors import fail


class LineEndpointControls(unittest.TestCase):
    def vertical_record(self):
        return endpoint_jump(LineCurve(0,1,[0,0],[1,0]),[1,1],Budget())

    def proxy(self, record, primitive, **kwargs):
        return one_form_proxy(record,primitive,axis=kwargs.pop('axis','U'),
                              envelope=kwargs.pop('envelope',[-2,2,-2,2]),
                              budget=kwargs.pop('budget',Budget()),**kwargs)

    def test_zero_original_end_and_explicit_connector_token(self):
        line=LineCurve(0,1,[1e16,0],[1,1])
        self.assertIsNone(endpoint_jump(line,line.evaluate(1)[0],Budget()))
        # The connector's ledger ends at piece.after=(1,1), not evaluate(1).
        record=endpoint_jump(line,[1,1],Budget())
        self.assertEqual(record['exactLawEndpoint'],['0','1'])
        self.assertEqual(record['ledgerEndpointToken'],[1.,1.])
        self.assertEqual(record['exactEndpointJump'],['1','0'])
        self.assertEqual(record['originalParameterRange'],[0.,1.])
        self.assertEqual(record['samplePoints'],[[0.,1.],[.5,1.],[1.,1.]])
        self.assertEqual(self.proxy(record,lambda p:[2]*5,axis='V')['totals'],[2]*5)
        self.assertEqual(self.proxy(record,lambda p:[2]*5,axis='U')['totals'],[0]*5)

    def test_nonzero_collinear_u_dv_jump_is_not_zero_flux(self):
        line=LineCurve(0,3,[.1,.1],[1,1]);token=line.evaluate(3)[0]
        record=endpoint_jump(line,token,Budget())
        ideal=list(map(Fraction,record['exactLawEndpoint']))
        delta=list(map(Fraction,record['exactEndpointJump']))
        exact=delta[1]*(ideal[0]+Fraction(token[0]))/2
        self.assertNotEqual(exact,0)
        result=self.proxy(record,lambda p:[p[0],0,0,0,0])
        self.assertGreater(result['totals'][0],0)
        self.assertGreaterEqual(Fraction(result['totals'][0]),abs(exact))
        self.assertFalse(result['bound']);self.assertTrue(record['nonIntegratedJump'])

    def test_degree_zero_through_three_against_fraction_integrals(self):
        record=self.vertical_record()
        polynomials=[(2,),(-1,3),(1,-4,2),(-3,8,-6,4),(0,1,-3,2)]
        for coefficients in polynomials:
            with self.subTest(coefficients=coefficients):
                exact=sum((Fraction(c,power+1) for power,c in enumerate(coefficients)),Fraction())
                def primitive(point):
                    t=point[1]
                    value=sum(c*t**power for power,c in enumerate(coefficients))
                    return [value]*5
                result=self.proxy(record,primitive)
                self.assertTrue(all(Fraction(value)>=abs(exact) for value in result['totals']))
                self.assertEqual([row['point'][1]for row in result['samples']],[0.,.5,1.])

    def test_degree_five_can_exceed_proxy_so_it_is_not_a_bound(self):
        # t(t-1/2)^2(t-1)^2 vanishes at all three samples but integrates1/240.
        coefficients=[0,Fraction(1,4),Fraction(-3,2),Fraction(13,4),-3,1]
        exact=sum((Fraction(c,p+1) for p,c in enumerate(coefficients)),Fraction())
        self.assertEqual(exact,Fraction(1,240))
        result=self.proxy(self.vertical_record(),lambda p:[p[1]*(p[1]-.5)**2*(p[1]-1)**2]*5)
        self.assertEqual(result['totals'],[0]*5)
        self.assertGreater(exact,Fraction(result['totals'][0]))
        self.assertFalse(result['bound'])

    def test_envelope_preflight_before_any_primitive_and_gauge_amplification(self):
        calls=[];record=self.vertical_record()
        with self.assertRaisesRegex(Unresolved,'preflight envelope'):
            self.proxy(record,lambda p:calls.append(p)or[1]*5,envelope=[0,2,0,.75])
        self.assertEqual(calls,[])
        ordinary=self.proxy(record,lambda p:[p[0],p[0],0,0,0])
        shifted=self.proxy(record,lambda p:[p[0]-10,7*(p[0]-10),0,0,0])
        self.assertEqual(ordinary['totals'][:2],[1.,1.])
        self.assertEqual(shifted['totals'][:2],[9.,63.])

    def test_nonzero_exact_component_underflow_overflow_and_nonfinite_refuse(self):
        tiny=math.ulp(0.)
        line=LineCurve(0,.75,[0,0],[tiny,1])
        with self.assertRaisesRegex(Unresolved,'underflows'):
            endpoint_jump(line,line.evaluate(.75)[0],Budget())
        line=LineCurve(0,2,[0,0],[1,1])
        line.first[0]=float.fromhex('0x1.fffffffffffffp+1023')
        line.slope[0]=line.first[0]
        with self.assertRaises(Unresolved):endpoint_jump(line,[1,1],Budget())
        for token in ([math.nan,0],[0,math.inf],[True,0]):
            with self.subTest(token=token),self.assertRaises(Unresolved):
                endpoint_jump(LineCurve(0,1,[0,0],[1,1]),token,Budget())
        with self.assertRaises(Unresolved):
            self.proxy(self.vertical_record(),lambda p:[0,0,math.nan,0,0])

    def test_resource_deadline_and_cancellation_are_preserved(self):
        record=self.vertical_record();budget=Budget(maximum=1)
        def primitive(point):budget.tick();return[1]*5
        with self.assertRaises(EvaluationLimit):self.proxy(record,primitive,budget=budget)
        budget=Budget(clock=lambda:0);budget.clock=lambda:1000
        with self.assertRaises(MeasurementDeadline):
            endpoint_jump(LineCurve(0,1,[0,0],[1,1]),[1,2],budget)
        with self.assertRaises(MeasurementDeadline):self.proxy(record,lambda p:[1]*5,budget=budget)
        def cancel():fail('RUNNER_CANCELLED','requested')
        budget=Budget();budget.checkpoint=cancel
        with self.assertRaises(SchemaxisError)as caught:self.proxy(record,lambda p:[1]*5,budget=budget)
        self.assertEqual(caught.exception.fault.code,'RUNNER_CANCELLED')


class JointChoiceControls(unittest.TestCase):
    def test_lens_and_line_diagnostics_share_one_actual_volume_denominator(self):
        args=([1/8,1/4],2,[3/8,3,1,2,3],6,[2,-3,4],[0,1,-2],[4,5,6])
        lenses=[1/4,1,.5,1,1.5]
        expected=[1.,6.,29/4,13.,75/4]
        self.assertEqual(joint_choice(*args,volume=10,lens_totals=lenses),expected)
        self.assertEqual(joint_choice(*args,volume=-10,lens_totals=lenses),expected)
        with self.assertRaisesRegex(Unresolved,'consumes'):
            joint_choice(*args,volume=6,lens_totals=lenses)
        with self.assertRaisesRegex(Unresolved,'nonnegative'):
            joint_choice(*args,volume=10,lens_totals=[0,-1,0,0,0])
        negative=list(args);negative[2]=[-1,0,0,0,0]
        with self.assertRaisesRegex(Unresolved,'nonnegative'):
            joint_choice(*negative,volume=10,lens_totals=[2,0,0,0,0])

    def test_joint_denominator_and_normalised_moment_reference(self):
        args=([1/8,1/4],2,[3/8,3,1,2,3],6,[2,-3,4],[0,1,-2],[4,5,6])
        expected=[.75,5,float(Fraction(24,5)),float(Fraction(42,5)),12.]
        self.assertEqual(joint_choice(*args,volume=10),expected)
        self.assertEqual(joint_choice(*args,volume=-10),expected)
        separately=2*(4+2)/(10-2)+(6+2*3)/(10-3)
        self.assertLess(separately,expected[2])
        # A conditioning reference must not be used as the actual denominator.
        self.assertNotEqual(joint_choice(*args,volume=20),expected)

    def test_zero_line_estimate_recovers_previous_joint_choice(self):
        result=joint_choice([.25],2,[0]*5,100,[2,-3,4],[0,1,-2],[4,5,6],volume=10)
        self.assertEqual(result,[.25,2,1.5,2.25,3.])

    def test_consumed_nonfinite_and_negative_choices_refuse(self):
        args=([0],2,[0,3,1,1,1],1,[0]*3,[0]*3,[1]*3)
        for volume in (5,0,math.inf,math.nan):
            with self.subTest(volume=volume),self.assertRaises(Unresolved):
                joint_choice(*args,volume=volume)
        for line in ([-1,0,0,0,0],[0,0,0,math.inf,0]):
            with self.assertRaises(Unresolved):
                joint_choice([],0,line,1,[0]*3,[0]*3,[1]*3,volume=10)


if __name__=='__main__':unittest.main()
