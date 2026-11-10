"""Adversarial finite-chain and UV controls, without importing FreeCAD."""
from dataclasses import replace
import math
from fractions import Fraction
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from schemaxis.adaptors.freecad.gauss_green import (
    Budget, ConicCurve, EvaluationLimit, LineCurve, MeasurementDeadline,
    RationalCurve, Unresolved)
from schemaxis.adaptors.freecad.mass_boundary_native import CornerPiece, PairPiece, PolePiece
from schemaxis.adaptors.freecad.mass_boundary_admission import (
    coarse_winding, incidence_and_uv_admission, separated_adjacent_curve,
    separated_from_curve, _isolated_connector_endpoint, _terminal_affine_retrace,
    _retained_affine_spans)
from schemaxis.adaptors.freecad.mass_completion_native import _passive_length_integral, complete_level
from schemaxis.errors import fail
from schemaxis.core.faults import SchemaxisError


class Vertex:
    def __init__(self, identity): self.identity = identity
    def hashCode(self): return self.identity
    def isSame(self, other): return self.identity == other.identity


class Edge:
    def __init__(self, first, last): self.first, self.last = first, last
    def firstVertex(self, unused): return self.first
    def lastVertex(self, unused): return self.last


def closed_chain(starts=None, ends=None):
    """Two opposite charts; optional endpoints make real connector controls."""
    starts = starts if starts is not None else [(0.,0.), (1.,.1), (1.,1.), (0.,1.)]
    ends = ends if ends is not None else [(1.,0.), (1.,1.), (0.,1.), (0.,0.)]
    count = len(starts)
    assert count == len(ends)
    vertices = [Vertex(i) for i in range(count)]
    edges = [Edge(v, vertices[(i+1)%count]) for i, v in enumerate(vertices)]
    occurrences, corners = [], []
    for face_index, sign in enumerate((1,-1)):
        face = object(); offset = count*face_index
        for i in range(count):
            occurrences.append((face, sign, edges[i], LineCurve(0,1,starts[i],ends[i]), 1))
            j = (i+1)%count
            corners.append(CornerPiece(face,vertices[j],offset+i,1.,ends[i],
                                       offset+j,0.,starts[j],sign,-sign,sign))
    return {'occurrences':tuple(occurrences), 'corners':tuple(corners),
            'pairs':tuple(PairPiece(i,i+count,-1,-1,1)for i in range(count)), 'poles':()}


def end_retraces(incoming_start, outgoing_end):
    """Initial and terminal backtracks of the SAME non-closed occurrence.

    The middle vertices remain separated even when both shortcuts reach the
    same X, so neither a zero-length original edge nor fictitious vertex
    identity is used to create the negative control.
    """
    return closed_chain(
        starts=[(0.,0.),(incoming_start,0.),(3.,2.),(1.,2.)],
        ends=[(4.,0.),(3.,2.),(1.,2.),(outgoing_end,0.)])


def closed_end_retraces(incoming_start, outgoing_end, direction=1):
    """A native closed seam whose affine UV occurrence is still injective."""
    state=end_retraces(incoming_start,outgoing_end)
    # Identify the seam's native endpoints throughout both charts and their
    # adjacent edges/caps. Its two UV endpoints remain distinct and unchanged.
    state['occurrences'][0][2].last.identity=state['occurrences'][0][2].first.identity
    if direction<0:
        occurrences=list(state['occurrences']);corners=list(state['corners'])
        for index in (0,4):
            face,sign,edge,_,_=occurrences[index]
            occurrences[index]=(face,sign,edge,LineCurve(0,1,[4,0],[0,0]),-1)
            corners[index]=replace(corners[index],first_parameter=0.)
            corners[index+3]=replace(corners[index+3],second_parameter=1.)
        pairs=list(state['pairs']);pairs[0]=PairPiece(0,4,1,1,-1)
        state.update(occurrences=tuple(occurrences),corners=tuple(corners),pairs=tuple(pairs))
    return state


class IncidenceControls(unittest.TestCase):
    def test_closed_chain_and_each_numeric_coefficient(self):
        state = closed_chain()
        self.assertTrue(incidence_and_uv_admission(state,Budget())['zeroBoundary'])
        for key, index, fields in (('pairs',0,('coefficient','start_cap','end_cap')),
                                   ('corners',0,('chart_coefficient','patch_coefficient','cap_coefficient'))):
            for field in fields:
                with self.subTest(piece=key,field=field):
                    changed=dict(state);pieces=list(state[key])
                    pieces[index]=replace(pieces[index],**{field:0});changed[key]=tuple(pieces)
                    with self.assertRaisesRegex(Unresolved,'boundary is not zero'):
                        incidence_and_uv_admission(changed,Budget())

    def test_incidence_records_actual_retrace_corner_and_occurrence(self):
        result=incidence_and_uv_admission(end_retraces(3.,1.),Budget())
        self.assertTrue(result['zeroBoundary'])
        records=result['terminalAffineRetraces']
        self.assertEqual(result['terminalAffineRetraceCount'],4)
        self.assertEqual({(r['corner'],r['occurrence'],r['role'])for r in records},
                         {(0,0,'incoming'),(3,0,'outgoing'),
                          (4,4,'incoming'),(7,4,'outgoing')})
        for record in records:
            self.assertEqual(record['wireDirection'],1)
            self.assertEqual(record['originalParameterRange'],[0.,1.])
            self.assertEqual(record['fractionOfOriginalAffinePath'],.25)
            if record['role']=='incoming':
                self.assertEqual(record['endpointParameter'],1.)
                self.assertEqual(record['endpointPair'],[[4.,0.],[3.,0.]])
                self.assertEqual(record['retraceParameterRange'],[.75,1.])
                self.assertEqual(record['exactOtherParameter'],'3/4')
            else:
                self.assertEqual(record['endpointParameter'],0.)
                self.assertEqual(record['endpointPair'],[[1.,0.],[0.,0.]])
                self.assertEqual(record['retraceParameterRange'],[0.,.25])
                self.assertEqual(record['exactOtherParameter'],'1/4')

    def test_closed_uv_affine_retraces_keep_exact_span_in_both_wire_directions(self):
        for direction in (1,-1):
            with self.subTest(direction=direction):
                state=closed_end_retraces(3.,1.,direction)
                result=incidence_and_uv_admission(state,Budget())
                self.assertTrue(result['zeroBoundary'])
                self.assertEqual(result['terminalAffineRetainedSpans'],[
                    {'occurrence':0,'exactRetainedParameterRange':['1/4','3/4']},
                    {'occurrence':4,'exactRetainedParameterRange':['1/4','3/4']}])
                self.assertEqual({(r['corner'],r['occurrence'],r['role'])
                                 for r in result['terminalAffineRetraces']},
                                 {(0,0,'incoming'),(3,0,'outgoing'),
                                  (4,4,'incoming'),(7,4,'outgoing')})
                self.assertTrue(all(r['nativeClosedEdge'] is True and r['wireDirection']==direction
                                    for r in result['terminalAffineRetraces']))

    def test_closed_same_vertex_X_must_leave_a_strict_original_span(self):
        state=closed_end_retraces(2.,2.)
        first,last=state['corners'][0],state['corners'][3]
        # The existing pair guard genuinely permits this same-vertex X: the
        # rays are opposite. The exact retained-span guard must still refuse.
        self.assertTrue(first.vertex.isSame(last.vertex))
        self.assertTrue(_isolated_connector_endpoint(first,last,Budget()))
        # The whole function refuses first at a separately tested nonadjacent
        # original endpoint. Isolate only that dependency to reach the new
        # span guard; adjacent, pair, coefficient and native-ID checks stay real.
        with self.assertRaises(Unresolved):incidence_and_uv_admission(state,Budget())
        with patch('schemaxis.adaptors.freecad.mass_boundary_admission.separated_from_curve',return_value=1):
            with self.assertRaisesRegex(Unresolved,'no strict retained original span'):
                incidence_and_uv_admission(state,Budget())
        single=closed_chain(starts=[(0.,0.)],ends=[(1.,0.)])
        self.assertEqual(single['corners'][0].first,single['corners'][0].second)
        with self.assertRaises(Unresolved):
            incidence_and_uv_admission(single,Budget())

    def test_exact_span_guard_ignores_rounded_ranges_and_rejects_duplicate_roles(self):
        state=closed_end_retraces(3.,1.)
        # Select the two roles of occurrence0, not the opposite chart.
        rows=[r for r in incidence_and_uv_admission(state,Budget())['terminalAffineRetraces']
              if r['occurrence']==0]
        epsilon=Fraction(1,2**100)
        for row in rows:
            row['retraceParameterRange']=[.5,.5]
            row['exactOtherParameter']=str(Fraction(1,2)+(epsilon if row['role']=='incoming'else-epsilon))
        result=_retained_affine_spans(rows,state['occurrences'],Budget())
        self.assertEqual(result[0]['exactRetainedParameterRange'],
                         [str(Fraction(1,2)-epsilon),str(Fraction(1,2)+epsilon)])
        for other in (Fraction(1,2)+epsilon,Fraction(1,2)+2*epsilon):
            changed=[dict(r)for r in rows];changed[1]['exactOtherParameter']=str(other)
            with self.assertRaisesRegex(Unresolved,'no strict retained original span'):
                _retained_affine_spans(changed,state['occurrences'],Budget())
        for changed in ([rows[0],dict(rows[0],corner=99)],
                        [rows[0],dict(rows[1],role='incoming')],
                        [rows[0],dict(rows[1],corner=rows[0]['corner'])],
                        [rows[0],dict(rows[1],wireDirection=-1)]):
            with self.assertRaisesRegex(Unresolved,'duplicate or inconsistent roles'):
                _retained_affine_spans(changed,state['occurrences'],Budget())

    def test_incidence_retrace_does_not_skip_nonadjacent_crossing(self):
        starts=[(0.,0.),(1.,0.),(2.,2.),(0.,2.)]
        ends=[(2.,0.),(2.,2.),(0.,2.),(0.,0.)]
        safe=closed_chain(starts,ends)
        result=incidence_and_uv_admission(safe,Budget())
        self.assertEqual({(r['corner'],r['occurrence'])for r in result['terminalAffineRetraces']},
                         {(0,0),(4,4)})
        # Keep the eligible first connector and its two adjacent curves. Only
        # the third side changes, crossing that connector at x=5/3, y=0.
        starts=starts[:];ends=ends[:]
        ends[2]=(1.5,-1.);starts[3]=ends[2]
        crossing=closed_chain(starts,ends)
        with self.assertRaisesRegex(Unresolved,'connector meets non-adjacent line'):
            incidence_and_uv_admission(crossing,Budget())
        # Native closure of the affine occurrence grants no other exemption.
        crossing['occurrences'][0][2].last.identity=crossing['occurrences'][0][2].first.identity
        with self.assertRaisesRegex(Unresolved,'connector meets non-adjacent line'):
            incidence_and_uv_admission(crossing,Budget())

    def test_incidence_full_end_retraces_refuse_overlap_and_distinct_vertex_X(self):
        for state in (end_retraces(1.,3.),end_retraces(2.,2.)):
            with self.subTest(ends=[state['corners'][i].after for i in (0,3)]):
                self.assertFalse(state['corners'][0].vertex.isSame(state['corners'][3].vertex))
                with self.assertRaisesRegex(Unresolved,'connector meets non-adjacent line'):
                    incidence_and_uv_admission(state,Budget())

    def test_incidence_isolated_connector_pair_guard_after_real_retrace_checks(self):
        # The complete guards above refuse first at the other original edge's
        # endpoint. Isolate ONLY that separately tested nonadjacent-curve
        # dependency here to reach the real connector-pair loop. Adjacent
        # eligibility, coefficients, vertex identity and pair guards stay real.
        target='schemaxis.adaptors.freecad.mass_boundary_admission.separated_from_curve'
        with patch(target,return_value=1):
            self.assertTrue(incidence_and_uv_admission(end_retraces(3.,1.),Budget())['zeroBoundary'])
            for state in (end_retraces(1.,3.),end_retraces(2.,2.)):
                with self.subTest(ends=[state['corners'][i].after for i in (0,3)]):
                    with self.assertRaisesRegex(Unresolved,'non-adjacent UV connectors are not separated'):
                        incidence_and_uv_admission(state,Budget())

    def test_collapsed_fan_coefficient_and_vertex(self):
        vertex=Vertex(10);face=object()
        state={'pairs':(), 'poles':(PolePiece(0,vertex,-1),), 'corners':()}
        # Closed rational UV loop isolates the actual collapsed-fan ledger.
        curve=RationalCurve(2,[0,0,0,1,1,1],[[0,0],[1,1],[0,0]],[1,1,1])
        state['occurrences']=((face,1,Edge(vertex,vertex),curve,1),);state['corners']=()
        self.assertTrue(incidence_and_uv_admission(state,Budget())['zeroBoundary'])
        state['poles']=(PolePiece(0,vertex,0),)
        with self.assertRaisesRegex(Unresolved,'boundary is not zero'):
            incidence_and_uv_admission(state,Budget())
        state['poles']=(PolePiece(0,Vertex(11),-1),)
        with self.assertRaisesRegex(Unresolved,'pole differs'):
            incidence_and_uv_admission(state,Budget())


class UVControls(unittest.TestCase):
    def test_line_and_rational_touch_cross_and_ambiguous_hulls(self):
        line=LineCurve(0,1,[-1,0],[1,0])
        rational=RationalCurve(2,[0,0,0,1,1,1],[[-1,0],[0,2],[1,0]],[1,.5,1])
        for curve in (line,rational):
            self.assertGreater(separated_from_curve([-1,3],[1,3],curve,Budget()),0)
            with self.assertRaises(Unresolved):
                separated_from_curve([0,-1],[0,2],curve,Budget())
        for first,last in (([-1,0],[-1,1]),([-1,math.ulp(1.)],[1,math.ulp(1.)])):
            with self.assertRaises(Unresolved):separated_from_curve(first,last,line,Budget())

    def test_adjacent_endpoint_is_not_an_occurrence_exemption(self):
        line=LineCurve(0,1,[0,0],[1,0])
        separated_adjacent_curve([1,0],[1,1],line,[1],Budget())
        for other in ([.5,0],[0,0]):
            with self.assertRaises(Unresolved):
                separated_adjacent_curve([1,0],other,line,[1],Budget())
        # Starts away from the connector, doubles back and crosses it later.
        looping=RationalCurve(3,[0]*4+[1]*4,[[0,0],[-2,1],[2,1],[-1,-1]],[1]*4)
        with self.assertRaises(Unresolved):
            separated_adjacent_curve([0,0],[0,2],looping,[0],Budget())

    def test_adjacent_rational_and_conic_positive_and_endpoint_mismatch(self):
        rational=RationalCurve(2,[0]*3+[1]*3,[[0,0],[1,0],[1,1]],[1,.3,2])
        separated_adjacent_curve([0,0],[-1,0],rational,[0],Budget())
        conic=ConicCurve(0,math.pi/2,[0,0],[1,0],[0,1],[2,1])
        separated_adjacent_curve([2,0],[3,0],conic,[0],Budget())
        class MismatchedRational(RationalCurve):
            def evaluate(self,t):
                point,tangent=super().evaluate(t)
                if t==self.start:point[0]+=1e-12
                return point,tangent
        mismatch=MismatchedRational(1,[0,0,1,1],[[0,0],[1,0]],[1,1])
        with self.assertRaisesRegex(Unresolved,'coefficient hull'):
            separated_adjacent_curve([1e-12,0],[-1,0],mismatch,[0],Budget())
        with self.assertRaisesRegex(Unresolved,'exact endpoint'):
            separated_adjacent_curve([2,1e-12],[3,0],conic,[0],Budget())

    def test_exact_terminal_retrace_requires_opposite_actual_wire_direction(self):
        line=LineCurve(0,1,[0,0],[1,0])
        for first,last,parameter,direction,role in (
            ([1,0],[.5,0],1,1,'incoming'),([.5,0],[0,0],0,1,'outgoing'),
            ([0,0],[.5,0],0,-1,'incoming'),([.5,0],[1,0],1,-1,'outgoing')):
            with self.subTest(direction=direction,role=role):
                records=[]
                separated_adjacent_curve(first,last,line,[parameter],Budget(),
                    wire_direction=direction,role=role,retraces=records)
                self.assertEqual(len(records),1)
                self.assertEqual(records[0]['fractionOfOriginalAffinePath'],.5)
                with self.assertRaises(Unresolved):
                    separated_adjacent_curve(first,last,line,[parameter],Budget(),
                        wire_direction=-direction,role=role)
        for other in ([0,0],[-1,0]):
            with self.assertRaises(Unresolved):
                separated_adjacent_curve([1,0],other,line,[1],Budget(),wire_direction=1,role='incoming')
        records=[]
        separated_adjacent_curve([1,0],[.5,0],line,[1],Budget(),
                                  wire_direction=1,role='incoming',closed=True,retraces=records)
        self.assertIs(records[0]['nativeClosedEdge'],True)
        with self.assertRaises(Unresolved):
            separated_adjacent_curve([1,0],[.5,0],line,[0,1],Budget(),
                                      wire_direction=1,role='incoming',closed=True)
        curve=RationalCurve(1,[0,0,1,1],[[0,0],[2,0]],[.5,3])
        records=[]
        separated_adjacent_curve([2,0],[1,0],curve,[1],Budget(),
                                  wire_direction=1,role='incoming',retraces=records)
        self.assertEqual(len(records),1)
        self.assertIn('positive-weight-rational',records[0]['law'])
        almost=RationalCurve(2,[0]*3+[1]*3,[[0,0],[.5,1e-30],[1,0]],[1]*3)
        self.assertIsNone(_terminal_affine_retrace([1,0],[.5,0],almost,1,1,'incoming'))
        self.assertIsNone(_terminal_affine_retrace([1,0],[.5,1e-30],line,1,1,'incoming'))

    def test_line_exact_law_endpoint_is_not_its_rounded_evaluated_endpoint(self):
        line=LineCurve(0,3,[.1,0],[1,0])
        evaluated=line.evaluate(line.end)[0]
        exact=[Fraction(a)+Fraction(v)*(Fraction(line.end)-Fraction(line.start))
               for a,v in zip(line.first,line.slope)]
        self.assertNotEqual(exact,list(map(Fraction,evaluated)))
        # A rounded endpoint is explicitly empirical eligibility; it must not
        # be relabelled an exact zero-chain cancellation.
        self.assertIsNotNone(_terminal_affine_retrace([.5,0],[.1,0],line,0,1,'outgoing'))
        record=_terminal_affine_retrace(evaluated,[.5,0],line,3,1,'incoming')
        self.assertTrue(record['nonIntegratedJump'])
        self.assertEqual(record['exactLawEndpoint'],list(map(str,exact)))
        self.assertIn('empirical-collinear-overlap',record['eligibilityKind'])
        self.assertNotIn('zero',record['cancellation'])
        records=[]
        separated_adjacent_curve(evaluated,[.5,0],line,[3],Budget(),
                                 wire_direction=1,role='incoming',closed=True,retraces=records)
        self.assertEqual(records[0]['exactEndpointJump'],
                         [str(Fraction(y)-x)for x,y in zip(exact,evaluated)])

    def test_actual_uc0_endpoint_overlap_keeps_both_span_and_collinearity_guards(self):
        line=LineCurve(0.,1.1313708498984762,[.9,.9],[.1,.1])
        evaluated=line.evaluate(line.end)[0];other=[.1,.1]
        ideal=[Fraction(a)+Fraction(v)*Fraction(line.end)for a,v in zip(line.first,line.slope)]
        self.assertEqual(evaluated,[.09999999999999998]*2)
        self.assertNotEqual(ideal,list(map(Fraction,evaluated)))
        for direction,role,first,last in ((1,'incoming',evaluated,other),
                                          (-1,'outgoing',other,evaluated)):
            record=_terminal_affine_retrace(first,last,line,line.end,direction,role)
            self.assertTrue(record['nonIntegratedJump'])
            self.assertEqual(record['residualJumpWireCoefficient'],-direction)
            self.assertEqual(record['ordering'],'ledger-endpoint-nearer-Q')
            self.assertTrue(0<Fraction(record['exactOtherParameter'])<Fraction(line.end))
            self.assertIsNone(_terminal_affine_retrace(first,last,line,line.end,-direction,role))
        # The exact point between ideal and token ends fails one of the two
        # strict spans. Checking only the evaluated span would accept it.
        between=[(x+Fraction(y))/2 for x,y in zip(ideal,evaluated)]
        self.assertIsNone(_terminal_affine_retrace(evaluated,between,line,line.end,1,'incoming'))
        self.assertIsNone(_terminal_affine_retrace(evaluated,[.1,.10000001],line,line.end,1,'incoming'))
        class OffLine(LineCurve):
            def evaluate(self,t):
                point,tangent=super().evaluate(t)
                if t==self.end:point[1]+=1e-12
                return point,tangent
        off=OffLine(0.,3.,[.1,.1],[1.,1.])
        self.assertIsNone(_terminal_affine_retrace(off.evaluate(off.end)[0],[.5,.5],off,off.end,1,'incoming'))

    def test_actual_closed_seam_parameter_record_and_mislabelled_role(self):
        end=6.28318530717959;other=6.283185307179586
        line=LineCurve(0,end,[0,0],[end,0]);records=[]
        separated_adjacent_curve([end,0],[other,0],line,[end],Budget(),
            wire_direction=1,role='incoming',closed=True,retraces=records)
        self.assertEqual(Fraction(records[0]['exactOtherParameter']),Fraction(other))
        self.assertIs(records[0]['nativeClosedEdge'],True)
        for parameter,role in ((0,'incoming'),(end,'outgoing')):
            self.assertIsNone(_terminal_affine_retrace([end,0],[other,0],line,parameter,1,role))
            with self.assertRaises(Unresolved):
                separated_adjacent_curve([end,0],[other,0],line,[parameter],Budget(),
                                         wire_direction=1,role=role,closed=True)

    def test_near_parallel_exact_endpoint_cone_does_not_use_float_angle_cutoff(self):
        line=LineCurve(0,1,[0,0],[1,0])
        for offset in (1e-30,-1e-30,1e-300):
            separated_adjacent_curve([0,0],[1,offset],line,[0],Budget())
        with self.assertRaises(Unresolved):
            separated_adjacent_curve([0,0],[.5,0],line,[0],Budget())

    def test_weighted_endpoint_rounding_is_not_exact_contact(self):
        # The quotient rounds to the native-looking endpoint but is NOT that
        # exact binary64 point. No zero-slack contact is inferred from rounding.
        curve=RationalCurve(1,[0,0,1,1],[[.1,0],[1,1]],[.3,1])
        anchor=Fraction(curve.poles[0][0])/Fraction(curve.poles[0][2])
        point=curve.evaluate(0)[0]
        self.assertEqual(float(anchor),point[0])
        self.assertNotEqual(anchor,Fraction(point[0]))
        self.assertIsNone(_terminal_affine_retrace(point,[.5,0],curve,0,-1,'incoming'))
        with self.assertRaisesRegex(Unresolved,'coefficient hull'):
            separated_adjacent_curve(point,[-1,0],curve,[0],Budget())

    def test_same_occurrence_connectors_may_not_cross_or_overlap(self):
        state=closed_chain();piece=state['corners'][0]
        first=replace(piece,before=(-1.,0.),after=(1.,0.))
        for before,after in (((0.,-1.),(0.,1.)),((0.,0.),(1.,0.))):
            second=replace(piece,before=before,after=after)
            self.assertFalse(_isolated_connector_endpoint(first,second,Budget()))
        first=replace(piece,before=(0.,0.),after=(1.,0.))
        second=replace(piece,before=(0.,0.),after=(0.,1.))
        self.assertTrue(_isolated_connector_endpoint(first,second,Budget()))
        self.assertFalse(_isolated_connector_endpoint(first,replace(second,vertex=Vertex(99)),Budget()))


class CompletionPropagationControls(unittest.TestCase):
    class Vector(tuple):
        def __new__(cls,*values): return tuple.__new__(cls,values or (0.,0.,0.))
        def __add__(self,other): return type(self)(*(a+b for a,b in zip(self,other)))
        def __sub__(self,other): return type(self)(*(a-b for a,b in zip(self,other)))
        def __mul__(self,scale): return type(self)(*(a*scale for a in self))
        def dot(self,other): return math.fsum(a*b for a,b in zip(self,other))
        def cross(self,other):
            a,b,c=self;d,e,f=other
            return type(self)(b*f-c*e,c*d-a*f,a*e-b*d)
        @property
        def Length(self): return math.hypot(*self)

    def fixture(self):
        vector=self.Vector;epsilon=1e-6
        # A quadratic connector bows 1.5 epsilon beyond a chord whose ends
        # are sqrt(2) epsilon from the common native vertex. The chord length
        # is 2 epsilon, so neither max(gap,bow) nor max(...,chord) is the radius.
        face=SimpleNamespace(
            valueAt=lambda u,v:vector(u,v,epsilon+1.5*epsilon*(1-(u/epsilon)**2)),
            derivative1At=lambda u,v:(vector(1,0,-3*u/epsilon),vector(0,1,0)))
        vertex=SimpleNamespace(Point=vector(),Tolerance=1e-4,hashCode=lambda:0,
                               isNull=lambda:False)
        vertex.isSame=lambda other:vertex is other
        piece=CornerPiece(face,vertex,0,1.,(-epsilon,0.),1,0.,(epsilon,0.),1,-1,1)
        state={'pairs':(),'poles':(),'corners':(piece,), 'wireRules':[],
               'uvGapMaximum':2*epsilon,'physicalEndpointMaximum':0.}
        prepared={'origin':[0.,0.,0.],'referenceVolume':2.,'axisLevers':[1.,1.,1.],'edges':1}
        row={'signedVolume':2.,'area':100.,'centre':[4.,0.,0.],
             'targets':[1e-10,2e-10,3e-10,4e-10,5e-10],'evaluations':0}
        return prepared,state,row

    def test_bowed_connector_radius_adds_endpoint_gap_and_bow(self):
        prepared,state,row=self.fixture()
        with patch.dict('sys.modules',{'FreeCAD':SimpleNamespace(Vector=self.Vector)}):
            result=complete_level(prepared,state,Budget(),row,fine=False)
        vertex=result['completion']['vertices'][0]
        self.assertAlmostEqual(vertex['maximumEndpointGap'],math.sqrt(2)*1e-6,places=18)
        self.assertAlmostEqual(vertex['maximumConnectorBow'],1.5e-6,places=18)
        self.assertAlmostEqual(vertex['empiricalRadius'],(math.sqrt(2)+1.5)*1e-6,places=18)
        self.assertGreater(vertex['empiricalRadius'],vertex['maximumConnectorChord'])

    def test_completed_centre_targets_use_completed_volume_and_centre(self):
        prepared,state,row=self.fixture()
        # Isolate integration with a known signed-volume/normalised-moment
        # correction. The production completion and target propagation run;
        # this is not a native geometry-accuracy control.
        with patch.dict('sys.modules',{'FreeCAD':SimpleNamespace(Vector=self.Vector)}), \
                patch('schemaxis.adaptors.freecad.mass_completion_native._passive_length_integral',
                      return_value=[2.,3.,0.,0.,0.,0.,0.]):
            result=complete_level(prepared,state,Budget(),row,fine=False)
        self.assertEqual(result['signedVolume'],4.)
        self.assertEqual(result['centre'],[3.5,0.,0.])
        for actual,expected in zip(result['propagatedCentreTargets'],[3.25e-10,2e-10,2.5e-10]):
            self.assertAlmostEqual(actual,expected,places=22)

    def test_zero_and_nonfinite_completed_volume_refuse_before_division(self):
        for volume in (0.,math.inf,math.nan):
            prepared,state,row=self.fixture();state['corners']=();row['signedVolume']=volume
            with self.subTest(volume=volume), \
                    patch.dict('sys.modules',{'FreeCAD':SimpleNamespace(Vector=self.Vector)}):
                with self.assertRaisesRegex(Unresolved,'nonfinite or zero signed volume'):
                    complete_level(prepared,state,Budget(),row,fine=False)


class PassiveAndFaultControls(unittest.TestCase):
    def test_only_first_five_fields_drive_refinement(self):
        budget=Budget()
        values=_passive_length_integral(lambda t:[1,2,3,4,5,float(t>.123),float(t>.731)],
                                        0,1,[1e-12]*5,budget=budget)
        self.assertEqual(budget.calls,15);self.assertEqual(budget.splits,0)
        for actual,expected in zip(values[:5],range(1,6)):self.assertAlmostEqual(actual,expected)
        budget=Budget()
        with self.assertRaises(Unresolved):
            _passive_length_integral(lambda t:[0,0,0,0,float(t>.123),1,1],
                                     0,1,[1e-30]*5,budget=budget)
        self.assertGreater(budget.calls,15)

    def test_mesh_ratio_and_exhausted_budget_before_native_call(self):
        class OCCError(RuntimeError):pass
        points=[(0,0,0),(1,0,0),(0,1,0),(0,0,1)]
        triangles=[(0,2,1),(0,1,3),(0,3,2),(1,2,3)]
        mesh=SimpleNamespace(CountFacets=4,CountPoints=4,Topology=(points,triangles))
        calls=[]
        def build(**kwargs):calls.append(kwargs);return mesh
        shape=SimpleNamespace(BoundBox=SimpleNamespace(XLength=1,YLength=1,ZLength=1,
                              Center=SimpleNamespace(x=0,y=0,z=0)),copy=lambda *args:object())
        with patch.dict('sys.modules',{'MeshPart':SimpleNamespace(meshFromShape=build),
                                      'Part':SimpleNamespace(OCCError=OCCError)}):
            result=coarse_winding(shape,1/6,1.5+math.sqrt(3)/2,Budget())
            self.assertAlmostEqual(result['signedVolume'],1/6)
            self.assertAlmostEqual(result['allowanceToAbsoluteVolume'],result['allowance']*6)
            calls.clear();budget=Budget(maximum=1);budget.calls=1
            with self.assertRaises(EvaluationLimit):coarse_winding(shape,1/6,3,budget)
            self.assertEqual(calls,[])

    def test_mesher_errors_typed_but_resource_deadline_and_cancel_preserved(self):
        class OCCError(RuntimeError):pass
        shape=SimpleNamespace(BoundBox=SimpleNamespace(XLength=1,YLength=1,ZLength=1),copy=lambda *args:object())
        for error in (OCCError('native'),RuntimeError('native mesher'),ValueError('bad mesh'),EvaluationLimit('cap'),MeasurementDeadline('deadline')):
            mesh=SimpleNamespace(meshFromShape=lambda **kwargs:(_ for _ in ()).throw(error))
            with patch.dict('sys.modules',{'MeshPart':mesh,'Part':SimpleNamespace(OCCError=OCCError)}):
                with self.assertRaises(Unresolved)as caught:coarse_winding(shape,1,6,Budget())
            if isinstance(error,(EvaluationLimit,MeasurementDeadline)):self.assertIs(caught.exception,error)
            else:self.assertIn('mesher failed',str(caught.exception))
        def cancel(**unused):fail('RUNNER_CANCELLED','cancelled')
        with patch.dict('sys.modules',{'MeshPart':SimpleNamespace(meshFromShape=cancel),'Part':SimpleNamespace(OCCError=OCCError)}):
            with self.assertRaises(SchemaxisError)as caught:coarse_winding(shape,1,6,Budget())
        self.assertEqual(caught.exception.fault.code,'RUNNER_CANCELLED')


if __name__=='__main__':unittest.main()
