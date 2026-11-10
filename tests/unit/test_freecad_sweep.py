"""Mechanical bend/sweep intent, safe frames and current native Body ownership."""
import copy,math,unittest
from schemaxis.adaptors.freecad import adaptor,sweep
from schemaxis.core.faults import SchemaxisError


def design(options=None):
    return {'version':'schemaxis.freecad/1','nodes':[{'id':'body','filter':'body'},
        {'id':'profile','filter':'circle','inputs':{'body':'body'}},
        {'id':'path','filter':'arcPath','inputs':{'body':'body'}},
        {'id':'finished','filter':'additivePipe','options':options or {},'inputs':{'body':'body','profile':'profile','spine':'path'}}],'output':'finished'}


class SweepIntent(unittest.TestCase):
    def fault(self,d,code):
        with self.assertRaises(SchemaxisError) as e:adaptor.plan(d)
        self.assertEqual(e.exception.fault.code,code)

    def test_path_intent_has_one_radius_one_angle_and_stable_origin(self):
        d=design();original=copy.deepcopy(d);p=adaptor.plan(d);self.assertEqual(d,original)
        n=p['nodes'][2];g=sweep.path_geometry(n['options']);c=sweep.path_constraints(n['options'])
        self.assertEqual(g[2]['centre'],[-10,0]);self.assertEqual(g[2]['startAngle'],0);self.assertEqual(g[2]['endAngle'],90)
        self.assertEqual([x['name'] for x in c],['origin','radialDirection','bendRadius','sharedCentre','sweep','arcCentre','arcStart','arcEnd'])
        self.assertAlmostEqual(next(x['value'] for x in c if x['name']=='sweep'),math.pi/2)
        self.assertEqual(p['partDesign']['bodies']['body']['tip'],'finished')

    def test_world_binormal_requires_its_own_mode_and_nonzero_direction(self):
        self.fault(design({'binormal':[0,1,0]}),'INVALID_SWEEP_ORIENTATION')
        self.fault(design({'orientation':'binormal'}),'INVALID_SWEEP_ORIENTATION')
        self.fault(design({'orientation':'binormal','binormal':[0,0,0]}),'INVALID_SWEEP_ORIENTATION')
        p=adaptor.plan(design({'orientation':'binormal','binormal':[0,2,0]}));self.assertEqual(sweep.settings(p['nodes'][-1])['binormal'],[0,2,0])

    def test_guide_and_sections_are_distinct_same_body_and_mode_consistent(self):
        d=design({'orientation':'auxiliary'});self.fault(d,'INVALID_SWEEP_ORIENTATION')
        d['nodes'][-1]['inputs']['auxiliary']='path';self.fault(d,'INVALID_SWEEP_PATH')
        d=design();d['nodes'][-1]['inputs']['sections']=['profile'];self.fault(d,'INVALID_SWEEP_SECTION')
        d=design();d['nodes'][-1]['inputs']['sections']=['path'];self.fault(d,'INVALID_SWEEP_PATH')
        d=design();d['nodes'].insert(2,{'id':'other','filter':'body'});d['nodes'][3]['inputs']['body']='other';self.fault(d,'INVALID_SWEEP_PATH')

    def test_native_reflection_and_unimplemented_transforms_are_not_authored(self):
        self.fault(design({'Transformation':'Linear'}),'UNKNOWN_ARGUMENT')
        self.fault(design({'orientation':'nativeMagic'}),'INVALID_ARGUMENT')
        self.fault(design({'auxiliaryEquivalence':False}),'INVALID_SWEEP_ORIENTATION')
        for radius,angle in [(0,90),(10,0),(10,360)]:
            d=design();d['nodes'][2]['options']={'bendRadius':radius,'sweepAngle':angle};self.fault(d,'INVALID_ARGUMENT')

    def test_bend_radius_drives_real_native_constraint_without_mutating_input(self):
        d=design();d['parameters']={'bend':{'kind':'length','value':12,'minimum':8,'maximum':15}};d['nodes'][2]['drive']={'bendRadius':{'terms':{'bend':1}}}
        p=adaptor.plan(d);self.assertEqual(p['nodes'][2]['options']['bendRadius'],12)
        from schemaxis.adaptors.freecad.parameters import expected_expressions
        self.assertEqual(expected_expressions(p['nodes'][2]),{'.Constraints.bendRadius':{'terms':{'bend':1},'offset':0}})

    def test_centroid_materialisation_is_explicit_only_when_requested(self):
        from schemaxis.adaptors.freecad.faces import attachment_mode,check_attacher
        p=adaptor.plan(design());self.assertNotIn('centroidAttachment',p['partDesign'])
        d=design();d['nodes'].append({'id':'attached','filter':'circle','options':{'onFace':{'face':'top','anchor':'centroid'}},'inputs':{'body':'body','support':'finished'}})
        p=adaptor.plan(d);n=p['nodes'][-1];self.assertEqual(p['partDesign']['centroidAttachment'],'native-centre-of-mass')
        self.assertEqual(attachment_mode(p,n),'CenterOfMass');check_attacher('CenterOfMass','Attacher::AttachEnginePoint','attached')
        old=copy.deepcopy(p);old['partDesign'].pop('centroidAttachment');self.assertEqual(attachment_mode(old,n),'FlatFace')
        with self.assertRaises(SchemaxisError):check_attacher('CenterOfMass','Attacher::AttachEnginePlane','attached')
        d['nodes'][-1]['options']['onFace']['engine']='arbitrary';self.fault(d,'UNKNOWN_ARGUMENT')


if __name__=='__main__':unittest.main()
