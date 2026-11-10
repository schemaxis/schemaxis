"""Draft polygons bind native editable intent to independent planar geometry."""
import copy,math,unittest
from schemaxis.adaptors.freecad import adaptor,drafting
from schemaxis.core.faults import SchemaxisError


POINTS=[[0,0],[10,0],[10,2],[4,2],[4,6],[0,6]]


def document(points=None,**options):
    return {'version':'schemaxis.freecad/1','nodes':[
        {'id':'outline','filter':'draftProfile','options':{'points':POINTS if points is None else points,**options}},
        {'id':'stock','filter':'extrude','inputs':{'profile':'outline'},'options':{'length':10}}],'output':'stock'}


def inventory(node):
    p=node['options']['points'];n=len(p)
    return {'vertices':[[*q,0] for q in p],
            'edges':[{'vertices':[i,(i+1)%n],'straight':True} for i in range(n)],
            'normal':[0,0,node['profile']['winding']],'planar':True,'faces':1,'wires':1,
            'area':36,'perimeter':32}


class DraftProfiles(unittest.TestCase):
    def test_concave_polygon_has_independent_area_perimeter_and_closed_native_policy(self):
        d=document();before=copy.deepcopy(d);p=adaptor.plan(d);self.assertEqual(d,before)
        node=p['nodes'][0];self.assertEqual(node['profile']['area'],36);self.assertEqual(node['profile']['perimeter'],32)
        self.assertEqual(node['profile']['winding'],1);drafting.verify_inventory(inventory(node),node)
        self.assertEqual(adaptor.DECLARATIONS['draftProfile']['native'],'Part::FeaturePython')
        reverse=adaptor.plan(document(list(reversed(POINTS))))['nodes'][0]
        self.assertEqual(reverse['profile']['winding'],-1);drafting.verify_inventory(inventory(reverse),reverse)

    def test_crossings_touch_overlap_repeated_close_and_zero_area_refuse(self):
        cases=[[[0,0],[4,4],[0,4],[4,0]],[[0,0],[4,0],[4,4],[2,0],[0,4]],
               [[0,0],[4,0],[2,0],[4,4],[0,4]],POINTS+[POINTS[0]],[[0,0],[1,0],[2,0]]]
        for points in cases:
            with self.subTest(points=points):
                with self.assertRaises(SchemaxisError):adaptor.plan(document(points))
        # A straight continuation is distinct from doubling back.
        adaptor.plan(document([[0,0],[2,0],[4,0],[4,4],[0,4]]))

    def test_principal_plane_frame_clocking_is_independent_of_polygon_coordinates(self):
        n=adaptor.plan(document(plane='YZ',origin=[20,-10,5],angle=90))['nodes'][0]
        actual=drafting.placement(n);expected=[0,0,1,20,0,-1,0,-10,1,0,0,5]
        self.assertTrue(all(abs(a-b)<1e-14 for a,b in zip(actual,expected)))

    def test_same_counts_or_measured_witnesses_cannot_hide_changed_boundary(self):
        node=adaptor.plan(document())['nodes'][0]
        for change in ('point','edge','curved','winding','extra-wire','extra-key'):
            value=inventory(node)
            if change=='point':value['vertices'][0][0]+=.001
            elif change=='edge':value['edges'][0]['vertices']=[0,2]
            elif change=='curved':value['edges'][0]['straight']=False
            elif change=='winding':value['normal']=[0,0,-1]
            elif change=='extra-wire':value['wires']=2
            else:value['unbound']='ignored'
            with self.subTest(change=change):
                with self.assertRaises(SchemaxisError):drafting.verify_inventory(value,node)

    def test_body_and_live_profile_bridges_are_explicitly_unavailable(self):
        d=document();d['nodes'].insert(0,{'id':'body','filter':'body'})
        with self.assertRaises(SchemaxisError) as error:adaptor.plan(d)
        self.assertEqual(error.exception.fault.code,'UNSUPPORTED_BODY_PROFILE')
