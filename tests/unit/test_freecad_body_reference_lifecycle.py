"""Trusted reference geometry cannot drift or omit indexed history across saves."""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET

from schemaxis.adaptors.freecad.part_reconstruction import body_reference_lifecycle
from schemaxis.core.faults import SchemaxisError


def fixture():
    element={'type':'Face','valid':True,'vertices':[[0,0,0],[1,0,0],[1,1,0],[0,1,0]],
             'faces':[['Plane',1]],'edges':[['Line',1]]*4,'counts':[0,0,1,1,4,4],
             'volume':0,'area':1.0,'length':4,'bounds':[0,1,0,1,0,0],
             'centreOfMass':None,'orientation':'Forward'}
    history={'shapes':{'N0.Shape':{'faces':[element],'edges':[],'vertices':[]}},
             'references':{'N0.Support':[{'target':'N0','sub':'Face1','shape':copy.deepcopy(element)}]}}
    root=ET.fromstring('<Document><Objects><Object name="N0"/></Objects><ObjectData>'
        '<Object name="N0"><Properties><Property name="Shape" type="Part::PropertyPartShape"/>'
        '<_Property name="Support" type="App::PropertyLinkSub"/></Properties></Object></ObjectData></Document>')
    return {'version':'schemaxis.freecad.body-reference-lifecycle/1','objects':['N0'],
            'before':history,'after':copy.deepcopy(history)},root


class BodyReferenceLifecycle(unittest.TestCase):
    def check(self,value,baseline=None):
        _,root=fixture()
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);(directory/'reference-lifecycle.json').write_text(json.dumps(value))
            with patch('schemaxis.adaptors.freecad.part_reconstruction.Document',return_value=type('Document',(),{'root':root})()):
                return body_reference_lifecycle(directory,baseline)

    def test_complete_unchanged_history_and_roundoff_retain_the_first_baseline(self):
        value,_=fixture();baseline=self.check(value)
        changed=copy.deepcopy(value)
        changed['after']['shapes']['N0.Shape']['faces'][0]['area']+=32*math.ulp(1.0)
        self.assertEqual(self.check(changed,baseline),baseline)

    def test_each_transition_cannot_accumulate_drift_beyond_the_first_reference(self):
        value,_=fixture();baseline=self.check(value);changed=copy.deepcopy(value)
        changed['before']['shapes']['N0.Shape']['faces'][0]['area']+=32*math.ulp(1.0)
        changed['after']['shapes']['N0.Shape']['faces'][0]['area']+=65*math.ulp(1.0)
        with self.assertRaises(SchemaxisError):self.check(changed,baseline)

    def test_relocation_orientation_consumer_and_membership_changes_refuse(self):
        value,_=fixture()
        for kind in ('vertex','orientation','consumer','omit-shape','omit-consumer','extra-object','extra-shape'):
            changed=copy.deepcopy(value)
            if kind=='vertex':changed['after']['shapes']['N0.Shape']['faces'][0]['vertices'][0][0]=0.25
            elif kind=='orientation':changed['after']['shapes']['N0.Shape']['faces'][0]['orientation']='Reversed'
            elif kind=='consumer':changed['after']['references']['N0.Support'][0]['sub']='Face2'
            elif kind=='omit-shape':changed['before']['shapes'].clear();changed['after']['shapes'].clear()
            elif kind=='omit-consumer':changed['before']['references'].clear();changed['after']['references'].clear()
            elif kind=='extra-object':changed['objects'].append('N1')
            else:changed['before']['shapes']['N1.Shape']=None;changed['after']['shapes']['N1.Shape']=None
            with self.subTest(kind=kind),self.assertRaises((ValueError,SchemaxisError)):self.check(changed)

    def test_unknown_incomplete_and_legacy_receipts_do_not_select_local_authority(self):
        value,_=fixture()
        for kind in ('version','extra','missing','objects-type','duplicate','legacy','empty'):
            changed=copy.deepcopy(value)
            if kind=='version':changed['version']='future'
            elif kind=='extra':changed['ignored']=True
            elif kind=='missing':changed.pop('after')
            elif kind=='objects-type':changed['objects']={'N0':True}
            elif kind=='duplicate':changed['objects'].append('N0')
            elif kind=='legacy':changed.pop('version');changed.pop('objects')
            else:changed['before']={};changed['after']={}
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.check(changed)


if __name__=='__main__':unittest.main()
