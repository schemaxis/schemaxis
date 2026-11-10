"""Classic spline intent boundaries and cross-family dependency admission."""
import copy
import json
import unittest
from schemaxis.adaptors.blender.production import validate,schema
from schemaxis.core.faults import SchemaxisError


def path(kind='POLY',**options):
    return {'id':'path','kind':'spline','splines':[{'id':'centre','kind':kind,'points':[{'position':[0,0,0]},{'position':[1,0,0]},{'position':[2,1,0]}]}],**options}


class SplineContracts(unittest.TestCase):
    def reject(self,objects,code='INVALID_SPLINE',**fields):
        with self.assertRaises(SchemaxisError) as error:validate({'objects':objects,**fields},{})
        self.assertEqual(error.exception.fault.code,code)
    def test_native_editable_shapes_have_stable_defaults_and_roundtrip(self):
        for kind in ('POLY','BEZIER','NURBS'):
            value={'objects':[path(kind)]};before=copy.deepcopy(value);result=validate(value,{})
            self.assertEqual(value,before);self.assertEqual(validate(result,{}),result)
            self.assertEqual(result['objects'][0]['splines'][0].get('sampling',0),0)
            if kind=='POLY':self.assertNotIn('sampling',result['objects'][0]['splines'][0])
        json.dumps(schema())
    def test_dimension_fill_and_xy_controls_are_semantic(self):
        self.reject([path(dimensions='2D',fill='FULL')])
        self.reject([path(fill='BOTH')]);self.reject([path(offset=1)])
        p=path(dimensions='2D');p['splines'][0]['points'][1]['position'][2]=.1;self.reject([p])
        self.reject([path(fillSolver='CDT')]);self.reject([path(dimensions='2D',fillRule='NONZERO')])
        self.assertEqual(validate({'objects':[path(dimensions='2D',fillSolver='CDT')]},{})['objects'][0]['fillSolver'],'CDT')
    def test_nurbs_knots_weights_and_orders_are_meaningful(self):
        for change in ({'order':4},{'closed':True},{'bezierKnots':True,'order':4}):
            p=path('NURBS');p['splines'][0].update(change);self.reject([p])
        p=path('NURBS');p['splines'][0].update(closed=True,endpoint=False);validate({'objects':[p]}, {})
        p['splines'][0]['points'][1]['weight']=0;self.reject([p],'INVALID_ARGUMENT')
    def test_duplicate_or_collapsed_controls_are_rejected(self):
        p=path();p['splines'].append(copy.deepcopy(p['splines'][0]));self.reject([p],'DUPLICATE_ID')
        p=path();p['splines'][0]['points'][1]['position']=[0,0,0];self.reject([p])
    def test_explicit_aligned_handles_cannot_be_silently_rewritten(self):
        p=path('BEZIER');p['splines'][0]['points'][1].update(left={'kind':'ALIGNED','position':[0,0,0]},right={'kind':'FREE','position':[1,1,0]});self.reject([p])
        p['splines'][0]['points'][1]['right']['position']=[2,0,0];validate({'objects':[p]}, {})
    def test_no_effect_taper_caps_and_trim_are_refused(self):
        for change in ({'caps':True},{'trim':{'end':.5}},{'taper':{'object':'profile'}},{'taper':{'mode':'ADD'}}):self.reject([path(**change)])
        self.reject([path(bevel={'kind':'round'},trim={'start':.8,'end':.2})])
    def test_profile_alias_cycle_and_path_compose_with_hierarchy(self):
        a=path(bevel={'kind':'object','object':'profileAlias'});b={**path(dimensions='2D'),'id':'profile'}
        fields={'geometryResources':[{'id':'profileAlias','kind':'object','object':'profile'}]}
        validate({'objects':[a,b,{'id':'follower','kind':'empty'}],**fields,'constraints':[{'id':'move','object':'follower','kind':'followPath','target':'path','factor':.5}]},{})
        self.reject([a,b],'DEPENDENCY_CYCLE',**fields,hierarchy=[{'object':'profile','parent':'path'}])
        self.reject([a,{'id':'profile','kind':'empty'}],'TYPE_MISMATCH',**fields)
        self.reject([a],'UNKNOWN_REFERENCE')
    def test_custom_profile_endpoints_and_duplicates_refuse(self):
        for positions in ([[0,0],[0,1]],[[1,0],[1,0],[0,1]]):self.reject([path(bevel={'kind':'profile','points':[{'position':p} for p in positions]})])
    def test_irrelevant_poly_sampling_and_zero_sweep_depth_refuse(self):
        p=path();p['splines'][0]['sampling']=3;self.reject([p],'INVALID_ARGUMENT')
        self.reject([path(bevel={'kind':'round','depth':0})],'INVALID_ARGUMENT')
    def test_disabled_path_cannot_silently_accept_a_follower(self):
        self.reject([path(path={'enabled':False}),{'id':'follower','kind':'empty'}],constraints=[{'id':'travel','kind':'followPath','object':'follower','target':'path'}])
    def test_partial_trim_requires_constant_point_radii_with_full_sweep_control(self):
        p=path(bevel={'kind':'round'},trim={'end':.75});p['splines'][0]['points'][1]['radius']=2
        self.reject([p]);p['caps']=True;self.reject([p])
        p['trim']={'end':1};validate({'objects':[p]}, {})
        p['trim']={'end':.75}
        for point in p['splines'][0]['points']:point['radius']=2
        validate({'objects':[p]}, {})

    def test_unknown_rna_or_unsupported_spline_is_not_an_escape(self):
        p=path();p['splines'][0]['nativePath']='bpy.context';self.reject([p],'INVALID_ARGUMENT')
        p=path();p['splines'][0]['kind']='CATMULL_ROM';self.reject([p],'INVALID_ARGUMENT')
