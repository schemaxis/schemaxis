"""Geometric selection meaning and ambiguity, independent of native edge order."""
import copy
import math
from pathlib import Path
import tempfile
import unittest
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.freecad import selections as s
from schemaxis.adaptors.freecad.adaptor import plan
from unittest.mock import patch


def selector(where=None, expect=4):
    value=validate_arguments({'value':s.EDGES},{'value':{'where':where or {'parallelTo':[0,0,1]},'expect':expect}})['value']
    s.validate(value,'test')
    return value


def box_edges(origin=(0,0,0),size=(10,20,5)):
    points=[[origin[i]+bit[i]*size[i] for i in range(3)] for bit in
            [(x,y,z) for x in (0,1) for y in (0,1) for z in (0,1)]]
    result=[]
    for index,a in enumerate(points):
        for b in points[index+1:]:
            if sum(x!=y for x,y in zip(a,b))!=1:continue
            result.append({'index':len(result)+1,'curve':'Line','lengthMM':math.dist(a,b),
                'centreMM':[(x+y)/2 for x,y in zip(a,b)],
                'boundsMM':[f(a[k],b[k]) for k in range(3) for f in (min,max)],'verticesMM':[a,b]})
    return result


class SelectionTests(unittest.TestCase):
    def test_inspection_prepares_the_requested_analytic_visit(self):
        from schemaxis.adaptors.freecad.inspection import inspect
        doc={'version':'schemaxis.freecad/1','nodes':[{'id':'blank','filter':'box',
             'options':{'height':{'$analytic':{'type':'values','values':[5,7]}}}}],'output':'blank'}
        class Captured(Exception):pass
        def capture(document,*args,**kwargs):
            self.assertEqual(document['nodes'][0]['options']['height'],7)
            raise Captured()
        with patch('schemaxis.adaptors.freecad.inspection.run',side_effect=capture),self.assertRaises(Captured):
            inspect(doc,'blank','/unused',visit=1)
        for index in (-1,2,True):
            with self.assertRaises(SchemaxisError):inspect(doc,'blank','/unused',visit=index)

    def test_direction_is_sign_and_scale_invariant_and_survives_dimensions_and_translation(self):
        for origin,size in [((0,0,0),(10,20,5)),((12,-4,3),(7,11,9))]:
            edges=box_edges(origin,size)
            selected=s.resolve(selector(),edges)
            self.assertEqual(selected,s.resolve(selector({'parallelTo':[0,0,-9]}),edges))
            self.assertEqual(len(selected),4)
            self.assertTrue(all(edges[i-1]['lengthMM']==size[2] for i in selected))
            # Changing topology enumeration must change the selected indices,
            # while preserving the independently specified geometric property.
            edges=list(reversed(edges))
            for i,e in enumerate(edges):e['index']=i+1
            selected=s.resolve(selector(),edges)
            self.assertTrue(all(edges[i-1]['lengthMM']==size[2] for i in selected))

    def test_plane_length_and_curve_predicates_conjoin(self):
        edges=box_edges()
        picked=s.resolve(selector({'curve':'line','onPlane':{'axis':'z','coordinate':5},'length':{'minimum':9,'maximum':11}},2),edges)
        self.assertEqual(len(picked),2)
        for i in picked:
            self.assertEqual(edges[i-1]['boundsMM'][4:],[5,5]);self.assertEqual(edges[i-1]['lengthMM'],10)
        edges[0]['curve']='Circle'
        self.assertEqual(s.resolve(selector({'curve':'circle'},1),edges),[1])

    def test_empty_ambiguous_and_missing_matches_do_not_choose_a_nearby_edge(self):
        cases=[({'onPlane':{'axis':'z','coordinate':99}},1,'EMPTY_SELECTION'),
               ({'parallelTo':[0,0,1]},1,'AMBIGUOUS_SELECTION'),
               ({'parallelTo':[0,0,1]},5,'SELECTION_COUNT_MISMATCH')]
        for where,count,code in cases:
            with self.subTest(code=code),self.assertRaises(SchemaxisError) as error:s.resolve(selector(where,count),box_edges())
            self.assertEqual(error.exception.fault.code,code)

    def test_invalid_authored_predicates_and_bounds_fail_before_native_execution(self):
        document={'version':'schemaxis.freecad/1','nodes':[{'id':'blank','filter':'box'},
            {'id':'finish','filter':'fillet','inputs':{'base':'blank'},'options':{'edges':{'where':{'parallelTo':[0,0,1]},'expect':4}}}], 'output':'finish'}
        self.assertEqual(plan(document)['nodes'][1]['options']['edges']['expect'],4)
        for field,value in [('where',{}),('expect',0),('tolerance',0),('angularTolerance',1),
                            ('where',{'parallelTo':[0,0,0]}),('where',{'curve':'circle','parallelTo':[0,0,1]}),
                            ('where',{'length':{'minimum':2,'maximum':1}}),('where',{'script':'eval'})]:
            bad=copy.deepcopy(document);bad['nodes'][1]['options']['edges'][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(SchemaxisError):plan(bad)

    def test_replay_rejects_wrong_source_indices_and_native_assignment(self):
        edge_selector=selector();edges=box_edges();indices=s.resolve(edge_selector,edges)
        node={'id':'finish','filter':'fillet','options':{'radius':1,'edges':edge_selector},'inputs':{'base':'blank'}}
        original={'finish':{'source':'blank','edges':edges,'indices':indices,'applied':[[i,1.,1.] for i in indices]}}
        s.verify({'nodes':[node]},original,copy.deepcopy(original))
        for field,value in [('source','other'),('indices',[1]),('applied',[[1,1,1]])]:
            bad=copy.deepcopy(original);bad['finish'][field]=value
            with self.subTest(field=field),self.assertRaises(SchemaxisError):s.verify({'nodes':[node]},bad,copy.deepcopy(bad))
        bad=copy.deepcopy(original);bad['finish']['edges'][0]['lengthMM']=float('nan')
        with self.assertRaises(SchemaxisError):s.verify({'nodes':[node]},bad,copy.deepcopy(bad))
