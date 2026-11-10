"""Finite-depth cuts retain native machining intent independently of current shape."""
import copy
import json
from pathlib import Path
import unittest
from schemaxis.adaptors.freecad import adaptor
from schemaxis.core.faults import SchemaxisError
ROOT=Path(__file__).resolve().parents[2]


def document():
    return json.loads((ROOT/'examples/schemaxis/freecad-counterbore.json').read_text())


class FinitePocketTests(unittest.TestCase):
    def fault(self,doc,code,location=None):
        with self.assertRaises(SchemaxisError) as caught:adaptor.plan(doc)
        self.assertEqual(caught.exception.fault.code,code)
        if location:self.assertEqual(caught.exception.fault.location,location)

    def test_driven_counterbore_and_literal_blind_pocket(self):
        d=document();old=copy.deepcopy(d);p=adaptor.plan(d)
        self.assertEqual(d,old)
        self.assertEqual(p['nodes'][-1]['options'],{'extent':'length','length':4})
        self.assertEqual(p['nodes'][4]['options'],{'extent':'throughAll'})
        d['nodes'][-1].pop('drive');d['nodes'][-1]['options']['length']=3
        d['parameters'].pop('counterboreDepth')
        self.assertEqual(adaptor.plan(d)['nodes'][-1]['options']['length'],3)

    def test_extent_and_depth_must_agree(self):
        d=document();d['nodes'][-1]['options']['extent']='throughAll'
        self.fault(d,'INVALID_POCKET_EXTENT','finished.options.length')
        d=document();d['nodes'][-1].pop('drive');d['parameters'].pop('counterboreDepth')
        self.fault(d,'INVALID_POCKET_EXTENT','finished.options.length')
        d=document();d['nodes'][-1]['options']['length']=4
        self.fault(d,'CONFLICTING_BINDING')

    def test_invalid_depths_and_modes(self):
        for value in (0,-1,100001,float('inf'),True,'4'):
            d=document();d['nodes'][-1].pop('drive');d['parameters'].pop('counterboreDepth')
            d['nodes'][-1]['options']['length']=value
            with self.assertRaises(SchemaxisError):adaptor.plan(d)
        d=document();d['nodes'][-1]['options']['extent']='upToFace'
        with self.assertRaises(SchemaxisError):adaptor.plan(d)

    def test_finite_depth_need_not_be_blind(self):
        # Stock intersection is a native check, not a host promise of a blind cavity.
        d=document();d['parameters']['counterboreDepth'].update(value=30,maximum=40)
        self.assertEqual(adaptor.plan(d)['nodes'][-1]['options']['length'],30)

    def test_schema_declares_depth_driver_and_meaningful_starter(self):
        branches=adaptor.schema()['properties']['nodes']['items']['oneOf']
        s=next(s for s in branches if s['properties']['filter']['const']=='pocket')
        self.assertEqual(s['properties']['options']['properties']['extent']['enum'],['throughAll','length'])
        self.assertNotIn('default',s['properties']['options']['properties']['length'])
        self.assertIn('length',s['properties']['drive']['properties'])
        studio=json.loads((ROOT/'src/schemaxis/adaptors/freecad/studio.json').read_text())
        t=next(t for t in studio['templates'] if t['id']=='counterbore')
        self.assertIn('depth',t['description'].lower())
