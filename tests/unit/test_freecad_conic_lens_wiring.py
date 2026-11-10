"""Exact exemption identity and native-call resource boundaries for lenses."""
from dataclasses import replace
from fractions import Fraction
from types import SimpleNamespace
import unittest

from schemaxis.adaptors.freecad.conic_lens import Lens,density_proxy,overperiod_residual
from schemaxis.adaptors.freecad.gauss_green import Budget,ConicCurve,EvaluationLimit,Unresolved
from schemaxis.adaptors.freecad.mass_boundary_admission import separated_adjacent_curve
from schemaxis.adaptors.freecad.mass_boundary_native import CornerPiece
from schemaxis.adaptors.freecad.mass_native import _level
from schemaxis.core.faults import SchemaxisError
from schemaxis.errors import fail


def square(face):
    return Lens('test-support',None,face,0,0,'incoming',(0.,1.),(Fraction(0),Fraction(1)),
                ((Fraction(0),Fraction(0)),(Fraction(1),Fraction(0)),
                 (Fraction(1),Fraction(1)),(Fraction(0),Fraction(1))),Fraction(1),1,())


class LensWiringTests(unittest.TestCase):
    def test_level_cap_is_checked_before_any_native_surface_call(self):
        calls=[]
        class Plane:pass
        face=SimpleNamespace(Surface=Plane(),valueAt=lambda *uv:calls.append(uv))
        lens=square(face)
        class NextCallExhaustsLevel(Budget):
            def tick(self):self.calls+=2_000_001
        prepared={'referenceVolume':1.,'origin':[0.]*3,'limits':[1e-6]*5,'axisLevers':[1.]*3,'edges':1,
                  'faces':[(face,1,[0.,1.,0.,1.],[],[],[])],
                  'completionState':{'conicLensDescriptors':(lens,)},
                  'surfaceDomains':[{'lineEndpointJumpPreparation':{'jumps':[],'uKnots':[],'envelope':[0.,1.,0.,1.]},
                                     'conicLensPreparation':{'envelope':[0.,1.,0.,1.]}}]}
        with self.assertRaisesRegex(EvaluationLimit,'one measurement evaluation cap'):
            _level(prepared,NextCallExhaustsLevel(),fine=False)
        self.assertEqual(calls,[])

    def test_cancellation_after_one_density_read_stops_before_the_next(self):
        requested=[False];calls=[];budget=Budget()
        def checkpoint():
            if requested[0]:fail('RUNNER_CANCELLED','requested during density sampling')
        budget.checkpoint=checkpoint
        def field(*uv):calls.append(uv);requested[0]=True;return[1.]*5
        with self.assertRaises(SchemaxisError)as caught:
            density_proxy(square(object()),field,[0.,1.,0.,1.],budget)
        self.assertEqual(caught.exception.fault.code,'RUNNER_CANCELLED')
        self.assertEqual(len(calls),1)

    def test_exemption_requires_original_curve_corner_role_and_tokens(self):
        curve=ConicCurve(0.,6.28318530717959,[0.,0.],[1.,0.],[0.,1.],[3.,3.])
        face=object();edge=SimpleNamespace(Degenerated=False,isClosed=lambda:True)
        before=tuple(curve.evaluate(curve.end)[0]);after=tuple(curve.evaluate(curve.start)[0])
        piece=CornerPiece(face,object(),0,curve.end,before,0,curve.start,after,1,-1,1)
        occurrences=((face,1,edge,curve,1),)
        lens=overperiod_residual(curve,0,0,piece,occurrences,(piece,),Budget())
        kwargs={'closed':True,'declared_lens':lens,'lens_corner':piece,'lens_corner_index':0}
        self.assertEqual(separated_adjacent_curve(before,after,curve,[curve.start,curve.end],Budget(),**kwargs),1)
        controls=[{**kwargs,'lens_corner_index':1},{**kwargs,'closed':False},
                  {**kwargs,'declared_lens':{}},
                  {**kwargs,'lens_corner':replace(piece,after=(after[0]+1.,after[1]))}]
        for changed in controls:
            with self.subTest(control=changed.keys()),self.assertRaises(Unresolved):
                separated_adjacent_curve(before,after,curve,[curve.start,curve.end],Budget(),**changed)
        other=ConicCurve(0.,curve.end,[0.,0.],[1.,0.],[0.,1.],[3.,3.])
        with self.assertRaises(Unresolved):
            separated_adjacent_curve(before,after,other,[other.start,other.end],Budget(),**kwargs)


if __name__=='__main__':unittest.main()
