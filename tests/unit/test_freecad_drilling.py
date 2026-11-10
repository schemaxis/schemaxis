"""Mechanical drilling layout, conditional extent and safe native-history policy."""
import copy
import math
import unittest
from schemaxis.adaptors.freecad import adaptor,drilling,parameters
from schemaxis.core.faults import SchemaxisError


def design(kind='boltGrid',options=None,finish=None):
    return {'version':'schemaxis.freecad/1','units':'mm','nodes':[
        {'id':'body','filter':'body'},
        {'id':'outline','filter':'rectangle','options':{'width':40,'height':40},'inputs':{'body':'body'}},
        {'id':'stock','filter':'pad','options':{'length':12},'inputs':{'body':'body','profile':'outline'}},
        {'id':'locations','filter':kind,'options':{'onFace':{'face':'top'},**(options or {})},'inputs':{'body':'body','support':'stock'}},
        {'id':'holes','filter':'hole','options':finish or {'diameter':3},'inputs':{'body':'body','base':'stock','profile':'locations'}}],
        'output':'holes'}


class DrillingIntent(unittest.TestCase):
    def fault(self,d,code):
        with self.assertRaises(SchemaxisError) as error:adaptor.plan(d)
        self.assertEqual(error.exception.fault.code,code)

    def test_grid_and_bolt_circle_have_independent_geometric_oracles(self):
        p=adaptor.plan(design());node=p['nodes'][-2];self.assertEqual(drilling.centres(node['filter'],node['options']),[[-10,-7.5],[10,-7.5],[-10,7.5],[10,7.5]])
        p=adaptor.plan(design('boltCircle',{'count':4,'radius':10,'phase':90}));node=p['nodes'][-2]
        for actual,expected in zip(drilling.centres('boltCircle',node['options']),[[0,10],[-10,0],[0,-10],[10,0]]):self.assertLess(math.dist(actual,expected),1e-12)
        self.assertEqual(drilling.hole_settings(p['nodes'][-1]['options'])['diameter'],3)

    def test_marker_radius_is_not_an_authored_drill_dimension(self):
        p=adaptor.plan(design('holeLocations',{'centres':[[0,0],[4,5]]}));n=p['nodes'][-2]
        self.assertTrue(all(g['radius']==1 for g in drilling.geometry(n['filter'],n['options'])))
        bad=design();bad['nodes'][-2]['options']['radius']=3;self.fault(bad,'UNKNOWN_ARGUMENT')

    def test_no_native_constraint_indices_are_required_and_pitch_intent_is_retained(self):
        p=adaptor.plan(design());n=p['nodes'][-2];expr=parameters.expected_expressions(n)
        self.assertEqual(expr['.Constraints.x_0'],'-0.5 * .Constraints.xPitch')
        self.assertIn('xPitch',[c['name'] for c in drilling.constraints(n['filter'],n['options'])])
        p=adaptor.plan(design('boltCircle'));n=p['nodes'][-2]
        self.assertEqual(parameters.expected_expressions(n)['.Constraints.y_1'],'sin(.Constraints.phase + 90 deg) * .Constraints.pitchRadius')

    def test_planner_preserves_input_and_same_body_current_tip(self):
        d=design();before=copy.deepcopy(d);p=adaptor.plan(d);self.assertEqual(d,before)
        self.assertEqual(p['partDesign']['owners']['holes'],'body');self.assertEqual(p['partDesign']['bodies']['body']['tip'],'holes')
        d['nodes'][-1]['inputs']['base']='outline';self.fault(d,'TYPE_MISMATCH')

    def test_drilling_locations_cannot_be_material_profiles(self):
        d=design();d['nodes'][-1]={'id':'holes','filter':'pad','options':{'length':2},'inputs':{'body':'body','base':'stock','profile':'locations'}}
        self.fault(d,'INVALID_HOLE_PROFILE')
        d=design();d['nodes'][-2]['inputs'].pop('body');self.fault(d,'INVALID_DEPENDENCY')

    def test_duplicate_and_excessive_patterns_refused_before_native(self):
        self.fault(design('holeLocations',{'centres':[[0,0],[0,0]]}),'INVALID_HOLE_LOCATIONS')
        self.fault(design('boltGrid',{'columns':64,'rows':64}),'RESOURCE_LIMIT')
        self.fault(design('boltGrid',{'columns':64,'rows':1,'xPitch':100000}),'INVALID_HOLE_LOCATIONS')

    def test_conditional_extent_and_recess_dimensions(self):
        for finish,code in [({'depth':5},'INVALID_HOLE_EXTENT'),({'extent':'length'},'INVALID_HOLE_EXTENT'),
            ({'tip':'conical'},'INVALID_HOLE_EXTENT'),({'recess':'counterbore'},'INVALID_HOLE_RECESS'),
            ({'recess':'none','recessDiameter':5},'INVALID_HOLE_RECESS'),
            ({'diameter':4,'recess':'counterbore','recessDiameter':3,'recessDepth':2},'INVALID_HOLE_RECESS'),
            ({'extent':'length','depth':2,'diameter':3,'recess':'counterbore','recessDiameter':6,'recessDepth':2},'INVALID_HOLE_RECESS'),
            ({'extent':'length','depth':.1,'diameter':3,'tip':'conical','depthMeasure':'tip'},'INVALID_HOLE_EXTENT')]:
            with self.subTest(finish=finish):self.fault(design(finish=finish),code)

    def test_virtual_countersink_apex_and_both_blind_tip_depth_conventions(self):
        p=adaptor.plan(design(finish={'diameter':2,'recess':'countersink','recessDiameter':4,'recessAngle':90}));self.assertAlmostEqual(drilling.hole_settings(p['nodes'][-1]['options'])['recessDepth'],2)
        for measurement,value in [('cylindrical',False),('tip',True)]:
            p=adaptor.plan(design(finish={'diameter':2,'extent':'length','depth':5,'tip':'conical','depthMeasure':measurement}));self.assertEqual(drilling.hole_settings(p['nodes'][-1]['options'])['tipIncludesDepth'],value)


if __name__=='__main__':unittest.main()
