"""Independent pure S1 controls; fake native identities do not qualify native files.

The quarter fixture follows the three-occurrence topology in the retained
context inventory. Literal coefficients/tokens are constructed here, not loaded
from a receipt. No FreeCAD import or native process is used.
"""
from dataclasses import replace
from fractions import Fraction as F
import copy
import math
import unittest

from schemaxis.adaptors.freecad import conic_lens as lens
from schemaxis.adaptors.freecad.gauss_green import (
    Budget, ConicCurve, LineCurve, RationalCurve, Unresolved,
    EvaluationLimit, MeasurementDeadline)
from schemaxis.adaptors.freecad.mass_boundary_native import CornerPiece


class EndpointTokenConic(ConicCurve):
    """Synthetic endpoint-rounding discriminator, never a native fixture."""
    def evaluate(self, parameter):
        point, tangent = super().evaluate(parameter)
        if parameter == self.end and hasattr(self, 'endpoint_token'):
            point = list(self.endpoint_token)
        return point, tangent


class EdgeIdentity:
    Degenerated = False
    def __init__(self, closed=False): self.closed = closed
    def isClosed(self): return self.closed


def circle(start=0., end=None, *, origin=(0., 0.), radius=3., reflected=False):
    if end is None: end = math.nextafter(2*math.pi, math.inf)
    return ConicCurve(start, end, origin, (-1., 0.) if reflected else (1., 0.),
                      (0., 1.), (radius, radius))


def corner(face, first, first_t, before, second, second_t, after):
    return CornerPiece(face, object(), first, first_t, tuple(before), second,
                       second_t, tuple(after), 1, -1, 1)


def single(curve, direction=1):
    face=object()
    first,last=(tuple(curve.evaluate(t)[0]) for t in (curve.start,curve.end))
    before,after=(last,first) if direction>0 else (first,last)
    ti,tj=(curve.end,curve.start) if direction>0 else (curve.start,curve.end)
    piece=corner(face,0,ti,before,0,tj,after)
    return {'occurrences':[(face,1,EdgeIdentity(True),curve,direction)],'corners':[piece]}


def quarter():
    c=circle(end=math.nextafter(math.pi/2,math.inf),reflected=True)
    face=object();token=tuple(c.evaluate(c.end)[0]);other=(-1e-15,3.)
    first=LineCurve(0,1,other,(-3.,3.));second=LineCurve(0,1,(-3.,3.),(-3.,0.))
    return {'occurrences':[(face,1,EdgeIdentity(),c,1),
                           (face,1,EdgeIdentity(),first,1),
                           (face,1,EdgeIdentity(),second,1)],
            'corners':[corner(face,0,c.end,token,1,0,other),
                       corner(face,1,1,(-3.,3.),2,0,(-3.,3.)),
                       corner(face,2,1,(-3.,0.),0,0,(-3.,0.))]}


def box(x0=0,x1=2,y0=0,y1=3, *, cap=1):
    vertices=((F(x0),F(y0)),(F(x1),F(y0)),(F(x1),F(y1)),(F(x0),F(y1)))
    return lens.Lens('literal-test-support',None,object(),0,0,'incoming',(0.,1.),
                     (F(0),F(1)),vertices,F(x1-x0)*F(y1-y0),cap,())


def winding(vertices, point=(0.,0.)):
    """Independent half-open ray crossing for a closed literal polygon."""
    x,y=point;answer=0
    for a,b in zip(vertices,vertices[1:]+vertices[:1]):
        determinant=(b[0]-a[0])*(y-a[1])-(x-a[0])*(b[1]-a[1])
        if a[1]<=y<b[1] and determinant>0:answer+=1
        if b[1]<=y<a[1] and determinant<0:answer-=1
    return answer


class ConicLensControls(unittest.TestCase):
    def test_full_turn_single_wire_reversal_and_inputs_unchanged(self):
        c=circle();saved=copy.deepcopy(c.__dict__)
        for direction in (1,-1):
            state=single(c,direction);pieces=tuple(state['corners'])
            records,count=lens.classify_lenses(state,Budget())
            self.assertEqual(len(records),1);self.assertEqual(count,0)
            row=records[0]
            self.assertEqual(row.cap,2);self.assertGreater(row.area,0)
            self.assertEqual(row.role,'closed-wire')
            self.assertEqual(row.record()['virtualJoins'],{'integrated':False,'oneFormProxied':False})
            self.assertTrue(row.record()['referenceWindingAssumed'])
            for token in (pieces[0].before,pieces[0].after):
                e=row.envelope();self.assertTrue(e[0]<=token[0]<=e[1] and e[2]<=token[1]<=e[3])
            self.assertEqual(tuple(state['corners']),pieces)
        self.assertEqual(c.__dict__,saved)

    def test_equal_tokens_still_classified_and_bad_wire_or_period_refuses(self):
        state=single(circle(origin=(10.,10.),radius=1.))
        self.assertEqual(state['corners'][0].before,state['corners'][0].after)
        self.assertEqual(len(lens.classify_lenses(state,Budget())[0]),1)
        for mutation in ('extra-corner','open-edge','wrong-token','wrong-direction','wrong-face'):
            state=single(circle());p=state['corners'][0]
            if mutation=='extra-corner':state['corners'].append(p)
            elif mutation=='open-edge':state['occurrences'][0][2].closed=False
            elif mutation=='wrong-token':state['corners'][0]=replace(p,before=(7.,8.))
            elif mutation=='wrong-direction':state['occurrences'][0]=(*state['occurrences'][0][:4],0)
            else:state['corners'][0]=replace(p,face=object())
            with self.subTest(mutation=mutation),self.assertRaises(Unresolved):
                lens.classify_lenses(state,Budget())
        for start,end in ((0,4*math.pi+1e-6),(2**20+1,2**20+8)):
            with self.subTest(start=start),self.assertRaises(Unresolved):
                lens.classify_lenses(single(circle(start,end)),Budget())

    def test_cap_two_has_independent_non_jordan_witness(self):
        # One circle arc plus three straight returns can wind twice. Every ray
        # crossing is away from a vertex; reversing the chain changes its sign.
        vertices=[(math.cos(t),math.sin(t)) for t in
                  (math.radians(350)*i/700 for i in range(701))]
        vertices += [(3*math.cos(math.radians(t)),3*math.sin(math.radians(t))) for t in (110,230)]
        self.assertEqual(winding(vertices),2)
        self.assertEqual(winding(vertices[::-1]),-2)
        self.assertEqual(lens.classify_lenses(single(circle()),Budget())[0][0].cap,2)

    def test_actual_quarter_pattern_and_exact_contact_in_rotated_matrix(self):
        state=quarter();rows,count=lens.classify_lenses(state,Budget())
        self.assertEqual(len(rows),1);self.assertGreater(count,0)
        row=rows[0];self.assertEqual(row.kind,'exact-terminal-tangent');self.assertEqual(row.cap,1)
        data=row.record();self.assertEqual(data['exactContact'],['0','3'])
        self.assertEqual(data['role'],'incoming');self.assertEqual(data['occurrence'],0)
        self.assertEqual(data['corner'],0);self.assertGreater(row.area,0)
        # Orthogonal matrix with unequal axes, q=(3/5,4/5). Literal tangent
        # endpoints map exactly to integer coordinates, avoiding rounded tangency.
        c=ConicCurve(0,2,(0,0),(.6,.8),(-.8,.6),(25,50))
        contact=lens.tangent_contact((-41,37),(-5,35),c,Budget())
        self.assertEqual(contact['unit'],(F(3,5),F(4,5)))
        self.assertEqual(contact['point'],(F(-23),F(36)))
        self.assertEqual(contact['parameter'],F(1,2))
        for a,z in (((-41,36),(-5,34)),((-23,36),(-5,35))):
            self.assertIsNone(lens.tangent_contact(a,z,c,Budget()))

    def test_tangent_wrong_role_phase_side_and_duplicate_windows_refuse(self):
        for mutation in ('role','face','direction','phase','side'):
            state=quarter();p=state['corners'][0];c=state['occurrences'][0][3]
            if mutation=='role':state['corners'][0]=replace(p,first_parameter=c.start)
            elif mutation=='face':state['corners'][0]=replace(p,face=object())
            elif mutation=='direction':state['occurrences'][0]=(*state['occurrences'][0][:4],0)
            elif mutation=='phase':c.start=math.nextafter(math.pi/2,math.inf)
            else:
                # Explicitly inject a wrong-side evaluated token while keeping
                # the ideal phase unchanged: tests the declared T5 predicate,
                # not a claim that FreeCAD generates this rounded endpoint.
                c=EndpointTokenConic(c.start,c.end,(0,0),(-1,0),(0,1),(3,3))
                c.endpoint_token=(-abs(p.before[0]),3.)
                state['occurrences'][0]=(*state['occurrences'][0][:3],c,1)
                state['corners'][0]=replace(p,before=c.endpoint_token,after=(1e-15,3.))
            with self.subTest(mutation=mutation),self.assertRaises(Unresolved):
                lens.terminal_tangent(c,0,0,state['corners'][0],state['occurrences'],Budget())
        state=quarter();rows,_=lens.classify_lenses(state,Budget());row=rows[0]
        with self.assertRaisesRegex(Unresolved,'duplicate'):
            lens.validate_lens_isolation((row,row),state,Budget())
        other=replace(row,corner=99,role='outgoing')
        with self.assertRaisesRegex(Unresolved,'windows overlap'):
            lens.validate_lens_isolation((row,other),state,Budget())

    def test_other_curve_hole_and_connector_cannot_use_own_lens_exemption(self):
        for kind in ('line','hole','connector'):
            state=single(circle());rows,_=lens.classify_lenses(state,Budget());row=rows[0]
            face=row.face
            if kind=='line':
                c=LineCurve(0,1,(2,-1),(4,1));state['occurrences'].append((face,1,EdgeIdentity(),c,1))
            elif kind=='hole':
                c=circle(0,1,origin=(3,0),radius=1e-15)
                state['occurrences'].append((face,1,EdgeIdentity(),c,1))
            else:state['corners'].append(corner(face,1,1,(2,0),2,0,(4,0)))
            with self.subTest(kind=kind),self.assertRaises(Unresolved):
                lens.validate_lens_isolation(rows,state,Budget())

    def test_rational_midpoint_rounding_false_isolation_regression(self):
        c=RationalCurve(2,[0,0,0,1,1,1],[(1,-1),(1+2**-52,0),(1,1)],[1,1,1])
        # Exact de Casteljau midpoint: (1+2^-53,0), strictly inside this box.
        row=box(F(1)+F(1,2**54),F(1)+F(3,2**54),F(-1,8),F(1,8))
        midpoint=(F(1)+F(1,2**53),F(0))
        self.assertTrue(row.vertices[0][0]<midpoint[0]<row.vertices[1][0])
        with self.assertRaisesRegex(Unresolved,'unresolved original curve hull'):
            lens.separated_support_curve(row,c,Budget())
        self.assertEqual(lens.separated_support_curve(box(2,3,-1,1),c,Budget()),1)
        # Curved hull overlaps, but exact subdivisions prove the central curve
        # stays below this box; this must not become blanket rational refusal.
        arch=RationalCurve(2,[0,0,0,1,1,1],[(0,0),(1,2),(2,0)],[1,1,1])
        self.assertGreater(lens.separated_support_curve(box(F(3,4),F(5,4),F(3,2),F(7,4)),arch,Budget()),1)

    def test_multispan_whole_original_hull_policy(self):
        c=RationalCurve(1,[0,0,.5,1,1],[(0,0),(1,1),(2,0)],[1,.5,2])
        self.assertEqual(lens.separated_support_curve(box(3,4,3,4),c,Budget()),1)
        self.assertIsNone(c._segments)  # no floating knot extraction was used
        with self.assertRaisesRegex(Unresolved,'multi-span'):
            lens.separated_support_curve(box(F(3,4),F(5,4),F(1,2),F(3,4)),c,Budget())
        self.assertIsNone(c._segments)

    def test_constant_five_density_literal_area_and_scaled_oracles(self):
        for scale in (F(1,4),F(1),F(8)):
            row=box(0,2*scale,0,3*scale,cap=2);calls=[]
            result=lens.density_proxy(row,lambda u,v:(calls.append((u,v)) or [2,-3,4,-5,6]),row.envelope(),Budget())
            self.assertEqual(len(calls),9)
            expected=[2*row.area*abs(v) for v in (2,-3,4,-5,6)]
            self.assertEqual(list(map(F,result['totals'])),expected)
            self.assertFalse(result['bound']);self.assertFalse(result['descriptor']['bound'])
            self.assertEqual(result['descriptor']['exactSupportArea'],str(6*scale*scale))
        row=box();positive=lens.density_proxy(row,lambda u,v:[1,2,3,4,5],row.envelope(),Budget())
        reversed_=lens.density_proxy(row,lambda u,v:[1,-2,-3,-4,-5],row.envelope(),Budget())
        self.assertEqual(positive['totals'],reversed_['totals'])

    def test_missed_spike_explicitly_demonstrates_not_a_bound(self):
        row=box(0,1,0,1)
        def spike(u,v):return [100 if abs(u-.25)<.01 and abs(v-.25)<.01 else 0]*5
        self.assertEqual(spike(.25,.25),[100]*5)
        result=lens.density_proxy(row,spike,row.envelope(),Budget())
        self.assertEqual(result['totals'],[0]*5);self.assertFalse(result['bound'])
        self.assertIn('unmodelled',result['scope'])

    def test_underflow_outward_overflow_and_preflight_before_callbacks(self):
        tiny=box(0,F(1,2**600),0,F(1,2**600))
        result=lens.density_proxy(tiny,lambda u,v:[1]*5,tiny.envelope(),Budget())
        self.assertEqual(result['totals'],[math.ulp(0.)]*5)
        with self.assertRaises(Unresolved):
            lens.density_proxy(box(0,2**600,0,2**600),lambda u,v:[1]*5,[-1e300,1e300,-1e300,1e300],Budget())
        calls=[]
        with self.assertRaisesRegex(Unresolved,'preflight envelope'):
            lens.density_proxy(box(),lambda u,v:calls.append((u,v)),[0,1,0,1],Budget())
        self.assertEqual(calls,[])
        with self.assertRaises(Unresolved):
            lens.density_proxy(box(),lambda u,v:[1,math.inf,1,1,1],box().envelope(),Budget())

    def test_deadline_resource_and_callback_faults_propagate(self):
        row=box();budget=Budget(clock=lambda:0);budget.clock=lambda:1000
        with self.assertRaises(MeasurementDeadline):lens.density_proxy(row,lambda u,v:[1]*5,row.envelope(),budget)
        calls=[]
        with self.assertRaises(EvaluationLimit):
            lens.density_proxy(row,lambda u,v:(calls.append(1) or [1]*5),row.envelope(),Budget(maximum=1))
        self.assertEqual(len(calls),1)
        class Stop(Exception):pass
        def cancelled():raise Stop('cancelled checkpoint')
        budget=Budget();budget.checkpoint=cancelled
        with self.assertRaisesRegex(Stop,'cancelled'):
            lens.classify_lenses(single(circle()),budget)


if __name__=='__main__':unittest.main()
