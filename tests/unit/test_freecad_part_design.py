"""Body ownership and feature-history rules are independent of native availability."""
import copy
import json
from pathlib import Path
import unittest
from schemaxis.adaptors.freecad import adaptor
from schemaxis.adaptors.freecad.live import prepare as live_prepare
from schemaxis.core.faults import SchemaxisError

ROOT=Path(__file__).resolve().parents[2]


def document():return json.loads((ROOT/'examples/schemaxis/freecad-part-design.json').read_text())


class PartDesignTests(unittest.TestCase):
    def fault(self,doc,code):
        with self.assertRaises(SchemaxisError) as caught:adaptor.plan(doc)
        self.assertEqual(caught.exception.fault.code,code)

    def test_normal_workflow_has_explicit_container_and_tip(self):
        d=document();original=copy.deepcopy(d);p=adaptor.plan(d)
        self.assertEqual(d,original)
        self.assertEqual(p['partDesign'],{'body':'part','members':['outline','slab','bore','finished'],'tip':'finished'})
        self.assertEqual(p['nodes'][2]['inputs'],{'body':'part','profile':'outline'})
        self.assertEqual(p['nodes'][2]['options'],{'length':5})
        self.assertEqual(p['nodes'][4]['options'],{'extent':'throughAll'})
        self.assertEqual(p['expectedPublications'],4)

    def test_optional_ports_match_schema_and_legacy_profile_plans(self):
        schema=adaptor.schema();nodes=schema['properties']['nodes']['items']['oneOf']
        for op in ('rectangle','circle'):
            s=next(s for s in nodes if s['properties']['filter']['const']==op)
            self.assertNotIn('inputs',s['required']);self.assertNotIn('required',s['properties']['inputs'])
            self.assertFalse(adaptor.DECLARATIONS[op]['inputs']['body']['required'])
        old={'version':'schemaxis.freecad/1','nodes':[{'id':'p','filter':'circle'},{'id':'s','filter':'extrude','inputs':{'profile':'p'}}],'output':'s'}
        p=adaptor.plan(old);self.assertEqual(p['nodes'][0]['inputs'],{});self.assertNotIn('centre',p['nodes'][0]['options']);self.assertNotIn('partDesign',p)

    def test_missing_wrong_and_forward_ports_refuse(self):
        d=document();d['nodes'][2]['inputs'].pop('body');self.fault(d,'INVALID_DEPENDENCY')
        d=document();d['nodes'][2]['inputs']['body']='outline';self.fault(d,'TYPE_MISMATCH')
        d=document();d['nodes'][1]['inputs']['body']='finished';self.fault(d,'INVALID_DEPENDENCY')
        d=document();d['output']='part';self.fault(d,'TYPE_MISMATCH')

    def test_ownership_and_branching_are_not_implicit(self):
        d=document();d['nodes'][1].pop('inputs');self.fault(d,'INVALID_BODY_OWNERSHIP')
        d=document();d['nodes'].insert(1,{'id':'other','filter':'body'});self.fault(d,'UNSUPPORTED_BODY')
        d=document();d['nodes'].append({'id':'second','filter':'pad','inputs':{'body':'part','profile':'bore'}});self.fault(d,'INVALID_BODY_HISTORY')
        d=document();d['nodes'].append({'id':'branch','filter':'pocket','inputs':{'base':'slab','profile':'bore'}});self.fault(d,'INVALID_BODY_HISTORY')
        d=document();d['nodes'].append({'id':'reuse','filter':'pocket','inputs':{'base':'finished','profile':'bore'}});self.fault(d,'INVALID_BODY_OWNERSHIP')
        d=document();d['output']='slab';self.fault(d,'INVALID_BODY_HISTORY')

    def test_part_and_partdesign_ownership_never_mix_silently(self):
        d=document();d['nodes'].append({'id':'outside','filter':'extrude','inputs':{'profile':'bore'}});self.fault(d,'INVALID_BODY_OWNERSHIP')
        d=document();d['nodes'].append({'id':'outside','filter':'cut','inputs':{'base':'finished','tool':'slab'}});self.fault(d,'INVALID_BODY_OWNERSHIP')

    def test_empty_and_unused_profiles_retain_an_explicit_tip(self):
        empty={'version':'schemaxis.freecad/1','nodes':[{'id':'part','filter':'body'},{'id':'stock','filter':'box'}],'output':'stock'}
        self.assertEqual(adaptor.plan(empty)['partDesign'],{'body':'part','members':[],'tip':None})
        d=document();d['nodes'].append({'id':'later','filter':'circle','inputs':{'body':'part'}})
        p=adaptor.plan(d);self.assertEqual(p['partDesign']['tip'],'finished');self.assertEqual(p['partDesign']['members'][-1],'later')

    def test_unqualified_attachment_and_extent_modes_refuse(self):
        for key,value in [('plane','XZ'),('origin',[0,0,1])]:
            d=document();d['nodes'][1]['options'][key]=value;self.fault(d,'UNSUPPORTED_ATTACHMENT')
        d=document();d['nodes'][4]['options']['extent']='length'
        with self.assertRaises(SchemaxisError):adaptor.plan(d)
        d=document();d['nodes'][3]['options']['centre']=[float('nan'),0]
        with self.assertRaises(SchemaxisError):adaptor.plan(d)

    def test_batch_only_contract_is_explicit(self):
        with self.assertRaises(SchemaxisError) as caught:live_prepare(document())
        self.assertEqual(caught.exception.fault.code,'UNSUPPORTED_LIVE_INPUT')
        d=document();d.pop('parameters')
        for n in d['nodes']:n.pop('drive',None)
        d['designStudy']={};self.fault(d,'UNSUPPORTED_BODY_STUDY')

    def test_inspection_preserves_only_required_parameter_relationships(self):
        from unittest.mock import patch
        from schemaxis.adaptors.freecad.inspection import inspect
        class Captured(Exception):pass
        def capture(reduced,*args,**kwargs):
            self.assertEqual(set(reduced['parameters']),{'width','thickness'})
            self.assertNotIn('length',reduced['nodes'][2]['options'])
            planned=adaptor.plan(reduced)
            self.assertEqual(planned['partDesign']['tip'],'slab')
            self.assertEqual(planned['nodes'][2]['drive']['length']['terms'],{'thickness':1})
            raise Captured()
        with patch('schemaxis.adaptors.freecad.inspection.run',side_effect=capture),self.assertRaises(Captured):
            inspect(document(),'slab','unused',executable='unused')
