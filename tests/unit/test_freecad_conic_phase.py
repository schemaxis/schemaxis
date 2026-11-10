"""Pure conic phase controls with exact remainder and independent Decimal oracles."""
from decimal import Decimal, localcontext
from fractions import Fraction
import math
import unittest

from schemaxis.adaptors.freecad import conic_phase as phase
from schemaxis.adaptors.freecad.gauss_green import (
    Budget, EvaluationLimit, MeasurementDeadline, Unresolved)
from schemaxis.core.faults import SchemaxisError
from schemaxis.errors import fail


PI = Decimal('3.141592653589793238462643383279502884197169399375105820974944592307816406286208998628034825342117067982148086513282306647093844609550582231725359408128481')


def decimal_value(value):
    value=Fraction(value)
    return Decimal(value.numerator)/Decimal(value.denominator)


def decimal_atan2(x,y):
    """Independent 160-digit oracle: sqrt half-angle reduction, then series."""
    with localcontext()as context:
        context.prec=160
        x,y=decimal_value(x),decimal_value(y)
        if not x:return +(PI/2 if y>0 else -PI/2)
        q=abs(y/x)
        for _ in range(8):q=q/(1+(1+q*q).sqrt())
        power,total=q,Decimal(0)
        for index in range(160):
            total+=(-1 if index%2 else 1)*power/(2*index+1)
            power*=q*q
        result=total*256*(1 if y/x>=0 else -1)
        if x<0:result+=PI if y>=0 else -PI
        return +result


def decimal_trig(value):
    """Independent high-precision pi literal and direct Decimal Taylor sums."""
    with localcontext()as context:
        context.prec=160
        value=decimal_value(value)
        quadrant=int((value/(PI/2)).to_integral_value())
        reduced=value-quadrant*PI/2
        ct,st=Decimal(1),reduced
        cosine,sine=Decimal(0),Decimal(0)
        for index in range(160):
            cosine+=ct;sine+=st
            ct*=-reduced*reduced/((2*index+1)*(2*index+2))
            st*=-reduced*reduced/((2*index+2)*(2*index+3))
        return ((+cosine,+sine),(-sine,+cosine),(-cosine,-sine),(+sine,-cosine))[quadrant%4]


class ConicPhaseControls(unittest.TestCase):
    def contains(self,interval,value):
        value=Fraction(value)
        self.assertLessEqual(interval[0],value)
        self.assertGreaterEqual(interval[1],value)
        for endpoint in interval:
            self.assertIsInstance(endpoint,Fraction)
            self.assertLessEqual(endpoint.denominator,1<<phase.PRECISION)

    def test_outward_arithmetic_signs_and_nonvanishing_small_fraction(self):
        a,b=Fraction(-3,7),Fraction(5,11)
        for interval,value in ((phase.outward(a),a),(phase.add(a,b),a+b),
                               (phase.sub(a,b),a-b),(phase.mul(a,b),a*b),
                               (phase.div(a,b),a/b),(phase.neg(a),-a)):
            self.contains(interval,value)
        result=phase.div((-2,5),(-3,-2))
        self.contains(result,Fraction(-5,2));self.contains(result,1)
        tiny=Fraction(1,1<<1075)
        result=phase.outward(tiny);self.contains(result,tiny)
        self.assertGreater(result[1],0)
        with self.assertRaises(Unresolved):phase.div(1,(-1,1))
        with self.assertRaises(Unresolved):phase.outward((1,-1))

    def test_machin_pi_and_exact_zero_anchors(self):
        self.contains(phase.pi_interval(Budget()),PI)
        with localcontext()as context:
            context.prec=160
            self.contains(phase.period_interval(Budget()),2*PI)
        self.assertEqual(phase.cos_sin_enclosure(0,Budget()),((Fraction(1),Fraction(1)),(Fraction(0),Fraction(0))))
        self.assertEqual(phase.atan2_enclosure(1,0,Budget()),(Fraction(0),Fraction(0)))

    def test_atan2_axes_all_quadrants_and_independent_known_angle(self):
        with localcontext()as context:
            context.prec=160
            for x,y,expected in ((0,1,PI/2),(0,-1,-PI/2),(-1,0,PI),
                                 (1,1,PI/4),(-1,1,3*PI/4),
                                 (-1,-1,-3*PI/4),(1,-1,-PI/4)):
                with self.subTest(x=x,y=y):
                    self.contains(phase.atan2_enclosure(x,y,Budget()),expected)
        angle=phase.atan2_enclosure(Fraction(3,5),Fraction(4,5),Budget())
        self.contains(angle,Decimal('0.927295218001612232428512462922428804057074108572240527621866177440395728331'))
        for x,y in ((1,-3),(-3,1),(3,-1),(-1,-3)):
            with self.subTest(x=x,y=y):
                self.contains(phase.atan2_enclosure(x,y,Budget()),decimal_atan2(x,y))
        with self.assertRaises(Unresolved):phase.atan2_enclosure(0,0,Budget())

    def test_trig_generic_and_large_start_against_decimal(self):
        for value in (1,-3,100000,Fraction(1,3),phase.MAX_PHASE):
            with self.subTest(value=value):
                actual=phase.cos_sin_enclosure(value,Budget())
                expected=decimal_trig(value)
                for interval,oracle in zip(actual,expected):self.contains(interval,oracle)

    def test_sqrt_half_and_rational_unit_phase_roundtrip(self):
        with localcontext()as context:
            context.prec=160
            half_root=Decimal(2).sqrt()/2
            quarter=phase.div(phase.pi_interval(Budget()),4)
            cosine,sine=phase.cos_sin_enclosure(quarter,Budget())
            self.contains(cosine,half_root);self.contains(sine,half_root)
        for x,y in ((Fraction(3,5),Fraction(4,5)),(Fraction(-4,5),Fraction(3,5)),
                    (Fraction(-3,5),Fraction(-4,5)),(Fraction(4,5),Fraction(-3,5))):
            angle=phase.atan2_enclosure(x,y,Budget())
            cosine,sine=phase.cos_sin_enclosure(angle,Budget())
            self.contains(cosine,x);self.contains(sine,y)

    def test_finite_interval_widening_contains_anchors_and_samples(self):
        small=phase.cos_sin_enclosure((Fraction(-1,10),Fraction(1,10)),Budget())
        large=phase.cos_sin_enclosure((Fraction(-1,5),Fraction(1,5)),Budget())
        for first,second in zip(small,large):
            self.assertLessEqual(second[0],first[0]);self.assertGreaterEqual(second[1],first[1])
        for value in (Fraction(-1,5),0,Fraction(1,5)):
            for interval,oracle in zip(large,decimal_trig(value)):self.contains(interval,oracle)

    def test_exact_alternating_remainder_brackets(self):
        value=Fraction(1,2)
        cosine=sum(((-1)**n*value**(2*n)/math.factorial(2*n)for n in range(40)),Fraction())
        sine=sum(((-1)**n*value**(2*n+1)/math.factorial(2*n+1)for n in range(40)),Fraction())
        actual=phase.cos_sin_enclosure(value,Budget())
        for interval,lower,upper in ((actual[0],cosine,cosine+value**80/math.factorial(80)),
                                     (actual[1],sine,sine+value**81/math.factorial(81))):
            self.contains(interval,lower);self.contains(interval,upper)
        arctangent=sum(((-1)**n*value**(2*n+1)/(2*n+1)for n in range(100)),Fraction())
        interval=phase.atan2_enclosure(1,value,Budget())
        self.contains(interval,arctangent)
        self.contains(interval,arctangent+value**201/201)

    def test_phase_and_operand_bounds_refuse_without_fallback(self):
        for value in (phase.MAX_PHASE+1,-phase.MAX_PHASE-1,math.inf,math.nan):
            with self.subTest(value=value),self.assertRaises(Unresolved):
                phase.cos_sin_enclosure(value,Budget())
        with self.assertRaises(Unresolved):phase.cos_sin_enclosure((-2,2),Budget())
        with self.assertRaises(EvaluationLimit):phase.outward(Fraction(1,1<<(phase.MAX_OPERAND_BITS+1)))
        with self.assertRaises(Unresolved):phase.outward(True)

    def test_term_deadline_resource_and_cancellation_preserved(self):
        budget=Budget(clock=lambda:0);budget.clock=lambda:1000
        with self.assertRaises(MeasurementDeadline):phase.cos_sin_enclosure(1,budget)
        class TermBudget:
            calls=0
            def check(self):
                self.calls+=1
                if self.calls==20:raise EvaluationLimit('term checkpoint discriminator')
        limited=TermBudget()
        with self.assertRaisesRegex(EvaluationLimit,'term checkpoint'):
            phase.atan2_enclosure(1,Fraction(1,2),limited)
        self.assertEqual(limited.calls,20)
        budget=Budget();budget.checkpoint=lambda:fail('RUNNER_CANCELLED','requested')
        with self.assertRaises(SchemaxisError)as caught:phase.pi_interval(budget)
        self.assertEqual(caught.exception.fault.code,'RUNNER_CANCELLED')
        budget=Budget();phase.cos_sin_enclosure(1,budget)
        self.assertEqual(budget.calls,0)  # Pure terms do not pretend to be native evaluations.


if __name__=='__main__':unittest.main()
