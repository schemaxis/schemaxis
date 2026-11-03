# Copyright (C) 2026 David L F Gaden
"""Persistent design intent has distinct validation, lifetime and evidence."""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from schemaxis.adaptors.freecad import adaptor, parameters
from schemaxis.adaptors.freecad.live import prepare as live_prepare
from schemaxis.core.faults import SchemaxisError


def document():
    return {'version':'schemaxis.freecad/1','parameters':{
        'thickness':{'kind':'length','value':5,'minimum':2,'maximum':10}},
        'nodes':[{'id':'stock','filter':'box','options':{'length':80,'width':50},
                  'drive':{'height':{'terms':{'thickness':1}}}}], 'output':'stock'}


def observation(prepared):
    return {'object':{'name':parameters.OBJECT_NAME,'label':parameters.OBJECT_LABEL,'type':'App::VarSet',
                      'properties':sorted(parameters.BASE_PROPERTIES | {'dim_thickness'}),'visibility':False},
            'parameters':{'thickness':{'property':'dim_thickness','type':'App::PropertyLength','value':5}},
            'expressions':{'SchemaxisParameters':[], 'N0':[['Height','1 * SchemaxisParameters.dim_thickness + 0 mm']]},
            'targets':{'stock.height':5}}


class ParameterTests(unittest.TestCase):
    def fault(self, doc, expected):
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.plan(doc)
        self.assertEqual(caught.exception.fault.code, expected)

    def test_old_exact_plan_is_unchanged_and_driver_is_opt_in(self):
        old={'version':'schemaxis.freecad/1','nodes':[{'id':'stock','filter':'box'}],'output':'stock'}
        self.assertEqual(adaptor.plan(old), {'version':'schemaxis.freecad.plan/1','units':'mm',
            'nodes':[{'id':'stock','filter':'box','options':{'length':10,'width':10,'height':10,'origin':[0,0,0]},'inputs':{}}],
            'output':'stock','linearDeflection':0.1,'expectedPublications':3})
        d=document();original=copy.deepcopy(d);p=adaptor.plan(d)
        self.assertEqual(d,original)
        self.assertEqual(p['nodes'][0]['options']['height'],5)
        self.assertEqual(p['nodes'][0]['drive']['height']['offset'],0)
        self.assertEqual(p['expectedPublications'],3)

    def test_current_option_default_never_hides_literal_conflict(self):
        for value in (5,10):
            d=document();d['nodes'][0]['options']['height']=value
            self.fault(d,'CONFLICTING_BINDING')

    def test_invalid_parameters_and_targets_have_structured_faults(self):
        for value in (True,float('nan'),float('inf'),-1,0,11):
            d=document();d['parameters']['thickness']['value']=value
            with self.subTest(value=value),self.assertRaises(SchemaxisError):adaptor.plan(d)
        for key,value in [('kind','angle'),('minimum',5),('maximum',2)]:
            d=document();d['parameters']['thickness'][key]=value
            if key=='minimum':d['parameters']['thickness']['maximum']=5
            self.fault(d,'INVALID_PARAMETER')
        for name in ('two-parts','_private','x'*65):
            d=document();d['parameters']={name:d['parameters']['thickness']}
            self.fault(d,'INVALID_PARAMETER')
        d=document();d['nodes'][0]['drive']={'origin':{'terms':{'thickness':1}}}
        self.fault(d,'INVALID_BINDING')
        d=document();d.pop('parameters');self.fault(d,'INVALID_BINDING')
        d=document();d['nodes'][0].pop('drive');self.fault(d,'INVALID_PARAMETER')
        d=document();d['nodes'][0]['drive']['height']['terms']={'missing':1};self.fault(d,'INVALID_BINDING')

    def test_affine_bounds_handle_negative_coefficients_and_extremes(self):
        d=document();b=d['nodes'][0]['drive']['height'];b.update(terms={'thickness':-1},offset=20)
        self.assertEqual(adaptor.plan(d)['nodes'][0]['options']['height'],15)
        b['offset']=10;self.fault(d,'INVALID_BINDING')
        for coefficient in (0,1e7,1e-320):
            d=document();d['nodes'][0]['drive']['height']['terms']['thickness']=coefficient
            with self.subTest(coefficient=coefficient),self.assertRaises(SchemaxisError):adaptor.plan(d)
        with self.assertRaises(SchemaxisError):parameters.numeric(10**1000,'x')
        with self.assertRaises(SchemaxisError):parameters.evaluate({'terms':{'x':1e308},'offset':0},{'x':1e308})

    def test_batch_analytics_resolve_driver_values_and_keep_relationships(self):
        d=document();d['parameters']['thickness']['value']={'$analytic':{'type':'values','values':[5,8]}}
        p=adaptor.plan(d)
        self.assertEqual(p['states'],2)
        self.assertEqual([v['plan']['nodes'][0]['options']['height'] for v in p['visits']],[5,8])
        self.assertEqual(p['visits'][0]['plan']['nodes'][0]['drive'],p['visits'][1]['plan']['nodes'][0]['drive'])

    def test_live_and_feedback_reject_new_contract_explicitly(self):
        with self.assertRaises(SchemaxisError) as caught:live_prepare(document())
        self.assertEqual(caught.exception.fault.code,'UNSUPPORTED_LIVE_INPUT')
        d=document();d['designStudy']={};self.fault(d,'UNSUPPORTED_PARAMETER_STUDY')

    def test_native_expression_structure_not_only_current_values_is_checked(self):
        p=adaptor.plan(document());good=observation(p);parameters.verify_observation(p,good)
        changes=[lambda o:o['expressions']['N0'].clear(),
                 lambda o:o['expressions']['N0'].append(['Width','50 mm']),
                 lambda o:o['expressions']['N0'][0].__setitem__(1,'2 * SchemaxisParameters.dim_thickness + -5 mm'),
                 lambda o:o['expressions'].__setitem__('Unknown',[]),
                 lambda o:o['object']['properties'].append('Unexpected'),
                 lambda o:o['parameters']['thickness'].__setitem__('value',True),
                 lambda o:o['targets'].__setitem__('stock.height',0)]
        for change in changes:
            o=copy.deepcopy(good);change(o)
            with self.subTest(change=change),self.assertRaises(SchemaxisError):parameters.verify_observation(p,o)

    def test_native_decimal_normalisation_preserves_coefficients_not_arbitrary_math(self):
        b={'terms':{'thickness':.1},'offset':-.2}
        parameters.check_expression('0.1 * SchemaxisParameters.dim_thickness + -0.2 mm',b,'x')
        for expression in ('0.1 * SchemaxisParameters.dim_thickness + -0.2',
                           'sin(SchemaxisParameters.dim_thickness)',
                           '0.1 * Other.dim_thickness + -0.2 mm'):
            with self.assertRaises(SchemaxisError):parameters.check_expression(expression,b,'x')

    def test_native_precision_is_a_specific_representation_not_a_loose_tolerance(self):
        binding={'terms':{'thickness':1.2345678901234567e-3},'offset':10.123456789012346}
        parameters.check_expression('0.00123456789012346 * SchemaxisParameters.dim_thickness + 10.1234567890123 mm',binding,'x')
        with self.assertRaises(SchemaxisError):
            parameters.check_expression('0.00123456789012347 * SchemaxisParameters.dim_thickness + 10.1234567890123 mm',binding,'x')
        self.assertEqual(parameters.saved_length(.12345678901234568),.1234567890123457)
        d=document();d['parameters']['thickness'].update(value=1e-18,minimum=1e-19,maximum=10)
        self.fault(d,'UNREPRESENTABLE_PARAMETER')
        d=document();d['parameters']['thickness'].update(value=1,minimum=1e-18,maximum=2)
        self.fault(d,'UNREPRESENTABLE_PARAMETER')
        for field in ('parameters','expressions','targets'):
            observed=observation(adaptor.plan(document()));observed[field]=None
            with self.assertRaises(SchemaxisError):parameters.verify_observation(adaptor.plan(document()),observed)

    def test_saved_fcstd_expression_tampering_is_checked_without_native_import(self):
        p=adaptor.plan(document())
        root=ET.Element('Document');objects=ET.SubElement(root,'Objects');data=ET.SubElement(root,'ObjectData')
        for name,typeid,label in [('SchemaxisParameters','App::VarSet','Design parameters'),('N0','Part::Box','stock')]:
            ET.SubElement(objects,'Object',name=name,type=typeid)
            properties=ET.SubElement(ET.SubElement(data,'Object',name=name),'Properties')
            def prop(n,t,child,**attrs):
                return ET.SubElement(ET.SubElement(properties,'Property',name=n,type=t),child,**attrs)
            prop('Label','App::PropertyString','String',value=label)
            prop('Label2','App::PropertyString','String',value='')
            prop('Visibility','App::PropertyBool','Bool',value='false')
            eng=prop('ExpressionEngine','App::PropertyExpressionEngine','ExpressionEngine')
            if name=='SchemaxisParameters':prop('dim_thickness','App::PropertyLength','Float',value='5')
            else:
                prop('Height','App::PropertyLength','Float',value='5')
                ET.SubElement(eng,'Expression',path='Height',expression='1 * SchemaxisParameters.dim_thickness + 0 mm')
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'test.FCStd'
            def save():
                with ZipFile(path,'w') as z:z.writestr('Document.xml',ET.tostring(root))
            save();parameters.verify_saved(p,path)
            expression=root.find("./ObjectData/Object[@name='N0']/Properties/Property[@name='ExpressionEngine']/ExpressionEngine/Expression")
            expression.set('expression','2 * SchemaxisParameters.dim_thickness + -5 mm');save()
            with self.assertRaises(SchemaxisError):parameters.verify_saved(p,path)
