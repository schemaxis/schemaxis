"""Strategic history foundation: domain composition and independently checked intent."""
import copy
import math
import unittest
from schemaxis.adaptors.freecad import adaptor, history, sketch
from schemaxis.core.faults import SchemaxisError


def example():
    return {'version':'schemaxis.freecad/1','nodes':[
        {'id':'part','filter':'body'},
        {'id':'outline','filter':'rectangle','options':{'width':40,'height':30},'inputs':{'body':'part'}},
        {'id':'stock','filter':'pad','options':{'length':10},'inputs':{'body':'part','profile':'outline'}},
        {'id':'bossProfile','filter':'circle','options':{'radius':5,'frame':{'origin':[0,0,10],'xAxis':[1,0,0],'normal':[0,0,1]}},'inputs':{'body':'part'}},
        {'id':'boss','filter':'pad','options':{'length':8},'inputs':{'body':'part','base':'stock','profile':'bossProfile'}}], 'output':'boss'}


class DesignHistories(unittest.TestCase):
    def fault(self,d,code):
        with self.assertRaises(SchemaxisError) as c:adaptor.plan(d)
        self.assertEqual(c.exception.fault.code,code)

    def test_subsequent_pad_preserves_per_body_base_and_immutable_input(self):
        d=example();before=copy.deepcopy(d);p=adaptor.plan(d)
        self.assertEqual(d,before);self.assertEqual(p['partDesign']['generation'],2)
        self.assertEqual(p['partDesign']['bodies']['part']['tip'],'boss')
        self.assertEqual(p['partDesign']['owners']['bossProfile'],'part')
        self.assertEqual(p['nodes'][-1]['inputs']['base'],'stock')

    def test_multiple_body_tips_are_independent(self):
        d=example();d['nodes'].insert(3,{'id':'other','filter':'body'})
        p=adaptor.plan(d);self.assertIsNone(p['partDesign']['bodies']['other']['tip'])
        self.assertEqual(p['partDesign']['bodies']['part']['tip'],'boss')
        d['nodes'][-1]['inputs']['body']='other';self.fault(d,'INVALID_BODY_HISTORY')

    def test_history_branch_reuse_and_cross_body_profiles_refused(self):
        for change,code in [('missingBase','INVALID_BODY_HISTORY'),('staleOutput','INVALID_BODY_HISTORY'),('usedProfile','INVALID_BODY_OWNERSHIP'),('crossBody','INVALID_BODY_OWNERSHIP')]:
            d=example()
            if change=='missingBase':d['nodes'][-1]['inputs'].pop('base')
            if change=='staleOutput':d['output']='stock'
            if change=='usedProfile':d['nodes'][-1]['inputs']['profile']='outline'
            if change=='crossBody':
                d['nodes'].insert(3,{'id':'other','filter':'body'});d['nodes'][-2]['inputs']['body']='other'
            with self.subTest(change=change):self.fault(d,code)

    def test_orthonormal_explicit_frames_and_native_shortcuts(self):
        d=example();o=d['nodes'][-2]['options']
        for x,n in [([2,0,0],[0,0,1]),([1,0,0],[1,0,0]),([0,0,0],[0,0,1])]:
            o['frame'].update(xAxis=x,normal=n);self.fault(d,'INVALID_FRAME')
        o['frame'].update(xAxis=[0,1,0],normal=[1,0,0]);p=adaptor.plan(d)
        self.assertEqual(history.matrix(p['nodes'][-2]['options']),[0,0,1,0,1,0,0,0,0,1,0,10,0,0,0,1])
        o['plane']='XZ';self.fault(d,'CONFLICTING_FRAME')

    def test_named_geometry_and_constraint_reference_validation(self):
        d=example();d['nodes'][-2]={'id':'bossProfile','filter':'sketch','inputs':{'body':'part'},'options':{'geometry':[{'id':'c','kind':'circle','centre':[0,0],'radius':5}]}}
        p=adaptor.plan(d);self.assertEqual(sketch.definitions(p['nodes'][-2])[0]['type'],'Block')
        o=d['nodes'][-2]['options'];o['constraints']=[{'id':'r','kind':'radius','first':{'geometry':'unknown'},'value':5}]
        self.fault(d,'CONFLICTING_CONSTRAINTS');o['constraintMode']='solve';self.fault(d,'INVALID_CONSTRAINT')
        o['constraints'][0]['first']['geometry']='c';p=adaptor.plan(d)
        self.assertEqual(sketch.definitions(p['nodes'][-2])[0]['name'],'r')

    def test_independent_sketch_radius_and_offset_residuals(self):
        n={'id':'profile','filter':'sketch','options':{'constraintMode':'solve','geometry':[{'id':'c','kind':'circle','centre':[1,2],'radius':3,'construction':False}],
            'constraints':[{'id':'radius','kind':'radius','first':{'geometry':'c','point':'whole'},'value':3},{'id':'x','kind':'distanceX','first':{'geometry':'c','point':'centre'},'value':1}]}}
        geometry=[{'kind':'circle','centre':[1,2],'radius':3,'construction':False}]
        sketch.verify_geometry(n,geometry)
        for key,value in [('radius',4),('centre',[2,2]),('construction',True)]:
            changed=copy.deepcopy(geometry);changed[0][key]=value
            with self.subTest(key=key),self.assertRaises(SchemaxisError):sketch.verify_geometry(n,changed)

    def test_numeric_storage_tolerance_does_not_accept_bool_or_changed_identity(self):
        self.assertTrue(history.equivalent({'matrix':[0.,1.]},{'matrix':[2e-16,1.]}))
        self.assertFalse(history.equivalent({'matrix':[0.,1.]},{'matrix':[True,1.]}))
        self.assertFalse(history.equivalent({'profile':'N2'},{'profile':'N3'}))
        self.assertFalse(history.equivalent({'matrix':[0.,1.]},{'matrix':[.01,1.]}))

    def test_all_catalogue_fields_are_closed_and_executable(self):
        for op in ['sketch','datumAxis','bodyRevolve','groove','bodyFillet','bodyChamfer','linearPattern','polarPattern','mirror','additiveLoft','subtractiveLoft']:
            self.assertIn(op,adaptor.DECLARATIONS)
        d=example();d['nodes'][-1]['options']['nativeProperty']='Shape';self.fault(d,'UNKNOWN_ARGUMENT')
        d=example();d['nodes'][-2]['options']['frame']['script']='print(1)';self.fault(d,'UNKNOWN_ARGUMENT')

    def test_face_intent_checks_extreme_position_and_ambiguity(self):
        from schemaxis.adaptors.freecad.faces import resolve,frame
        inventory=[{'index':1,'planar':True,'normal':[0,0,1],'centre':[2,3,10],'area':20},
                   {'index':2,'planar':True,'normal':[0,0,1],'centre':[4,5,3],'area':10}]
        self.assertEqual(resolve({'face':'top'},inventory)['index'],1)
        self.assertEqual(resolve({'face':'top','position':'innermost'},inventory)['index'],2)
        self.assertEqual(frame({'face':'top','offset':2},inventory[1])['origin'],[0,0,5])
        self.assertEqual(frame({'face':'top','offset':2,'anchor':'centroid'},inventory[1])['origin'],[4,5,5])
        duplicate=copy.deepcopy(inventory[0]);duplicate['index']=3
        with self.assertRaises(SchemaxisError) as c:resolve({'face':'top'},inventory+[duplicate])
        self.assertEqual(c.exception.fault.code,'AMBIGUOUS_SELECTION')
        with self.assertRaises(SchemaxisError) as c:resolve({'face':'bottom'},inventory)
        self.assertEqual(c.exception.fault.code,'EMPTY_SELECTION')

    def test_attachment_support_is_required_and_must_be_current_owned_tip(self):
        d=example();o=d['nodes'][-2]['options'];o.pop('frame');o['onFace']={'face':'top'}
        self.fault(d,'INVALID_ATTACHMENT')
        d['nodes'][-2]['inputs']['support']='stock';adaptor.plan(d)
        d['nodes'][-2]['inputs']['support']='outline';self.fault(d,'TYPE_MISMATCH')

    def test_capsule_slot_intent_and_persistent_native_driver(self):
        from schemaxis.adaptors.freecad.slot import geometry,constraints
        d=example();d['nodes'][-2]={'id':'bossProfile','filter':'slot','options':{'length':10,'radius':2},'inputs':{'body':'part'}}
        p=adaptor.plan(d);self.assertEqual(len(geometry(p['nodes'][-2]['options'])),4)
        self.assertEqual({c['name'] for c in constraints(p['nodes'][-2]['options']) if c['name']},{'span','radius','anchorX','centreY'})
        d['parameters']={'span':{'kind':'length','value':10,'minimum':8,'maximum':12}}
        d['nodes'][-2]['options'].pop('length');d['nodes'][-2]['drive']={'length':{'terms':{'span':1}}}
        p=adaptor.plan(d);self.assertEqual(p['nodes'][-2]['options']['length'],10)
        from schemaxis.adaptors.freecad.parameters import expected_expressions
        self.assertIn('.Constraints.span',expected_expressions(p['nodes'][-2]))

    def test_typed_constraint_shapes_refuse_undefined_native_relations(self):
        options={'geometry':[{'id':'a','kind':'line','start':[0,0],'end':[1,0]},{'id':'b','kind':'circle','centre':[0,0],'radius':2}],
                 'constraintMode':'solve','constraints':[{'id':'bad','kind':'equal','first':{'geometry':'a','point':'whole'},'second':{'geometry':'b','point':'whole'}}]}
        with self.assertRaises(SchemaxisError) as c:sketch.validate(options,'s')
        self.assertEqual(c.exception.fault.code,'INVALID_CONSTRAINT')
        options['constraints'][0]={'id':'bad','kind':'coincident','first':{'geometry':'a','point':'whole'},'second':{'geometry':'b','point':'centre'}}
        with self.assertRaises(SchemaxisError) as c:sketch.validate(options,'s')
        self.assertEqual(c.exception.fault.code,'INVALID_CONSTRAINT')
