"""Draft face intent, same-Body reference ownership and measured selection."""
import copy
import unittest
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from schemaxis.adaptors.freecad import adaptor,draft
from schemaxis.core.faults import SchemaxisError


def design(cylinder=False):
    faces=[{'surface':'cylinder','axis':[0,0,1],'radius':15}] if cylinder else [
        {'surface':'plane','normal':normal} for normal in ([1,0,0],[-1,0,0],[0,1,0],[0,-1,0])]
    return {'version':'schemaxis.freecad/1','nodes':[
        {'id':'body','filter':'body'},
        {'id':'outline','filter':'circle' if cylinder else 'rectangle','options':{'radius':15} if cylinder else {'width':40,'height':30},'inputs':{'body':'body'}},
        {'id':'stock','filter':'pad','options':{'length':20},'inputs':{'body':'body','profile':'outline'}},
        {'id':'release','filter':'bodyDraft','options':{'faces':faces},'inputs':{'base':'stock','neutralPlane':'outline'}},
        {'id':'housing','filter':'shell','options':{'openings':[{'face':'top'}]},'inputs':{'base':'release'}}],
        'output':'housing'}


def face(index,normal=None,centre=None,**kwargs):
    return {'index':index,'surface':'plane' if normal else 'cylinder','normal':normal or [0,0,0],
            'centre':centre or [0,0,10],'area':100,'axis':[0,0,0] if normal else [0,0,1],
            'axisPoint':[0,0,0],'radius':0 if normal else 15,**kwargs}


class MouldDraft(unittest.TestCase):
    def fault(self,document,code):
        with self.assertRaises(SchemaxisError) as caught:adaptor.plan(document)
        self.assertEqual(caught.exception.fault.code,code)

    def test_defaults_and_neutral_reference_preserve_authored_data(self):
        document=design();original=copy.deepcopy(document);plan=adaptor.plan(document)
        self.assertEqual(document,original)
        node=next(n for n in plan['nodes'] if n['id']=='release')
        self.assertEqual(node['options']['angle'],3);self.assertFalse(node['options']['reversed'])
        self.assertTrue(all(f['position']=='outermost' for f in node['options']['faces']))
        self.assertEqual(plan['partDesign']['owners']['release'],'body')
        self.assertEqual(plan['partDesign']['bodies']['body']['tip'],'housing')
        cylinder=adaptor.plan(design(True))['nodes'][3]
        self.assertEqual(cylinder['options']['faces'][0]['axisPoint'],[0,0,0])

    def test_angle_limits_unit_directions_and_no_native_reflection(self):
        for value in (0,-1,90,True,float('nan')):
            document=design();document['nodes'][3]['options']['angle']=value
            self.fault(document,'INVALID_JSON' if type(value) is float else 'INVALID_ARGUMENT')
        document=design();document['nodes'][3]['options']['faces'][0]['normal']=[2,0,0]
        self.fault(document,'INVALID_DRAFT_SELECTION')
        document=design();document['nodes'][3]['options']['Base']=['Face1'];self.fault(document,'UNKNOWN_ARGUMENT')
        document=design();document['nodes'][3]['options']['faces'][0]['index']=1;self.fault(document,'INVALID_ARGUMENT')

    def test_current_tip_and_neutral_plane_ownership_are_required(self):
        document=design();document['nodes'][4]['inputs']['base']='stock';self.fault(document,'INVALID_BODY_HISTORY')
        document=design();document['nodes'].insert(0,{'id':'other','filter':'body'})
        document['nodes'].insert(1,{'id':'otherProfile','filter':'rectangle','inputs':{'body':'other'}})
        document['nodes'][5]['inputs']['neutralPlane']='otherProfile';self.fault(document,'INVALID_BODY_OWNERSHIP')

    def test_selection_is_directional_unique_and_cylinder_axis_is_a_line(self):
        options={'faces':[{'surface':'plane','normal':[1,0,0],'position':'outermost'}]}
        inventory=[face(1,[1,0,0],[20,0,10]),face(2,[1,0,0],[10,0,10])]
        self.assertEqual(draft.selected(options,inventory,'release'),['Face1'])
        inventory.append(face(3,[1,0,0],[20,5,10]))
        with self.assertRaises(SchemaxisError) as caught:draft.selected(options,inventory,'release')
        self.assertEqual(caught.exception.fault.code,'AMBIGUOUS_SELECTION')
        options={'faces':[{'surface':'cylinder','axis':[0,0,-1],'axisPoint':[0,0,500],'radius':15}]}
        self.assertEqual(draft.selected(options,[face(1)],'release'),['Face1'])
        options['faces'][0]['axisPoint']=[1,0,0]
        with self.assertRaises(SchemaxisError) as caught:draft.selected(options,[face(1)],'release')
        self.assertEqual(caught.exception.fault.code,'EMPTY_SELECTION')

    def test_duplicate_resolved_faces_and_malformed_measurements_fail(self):
        options={'faces':[{'surface':'plane','normal':[1,0,0],'position':'outermost'}]*2}
        with self.assertRaises(SchemaxisError) as caught:draft.selected(options,[face(1,[1,0,0])],'release')
        self.assertEqual(caught.exception.fault.code,'INVALID_DRAFT_SELECTION')
        options={'faces':[{'surface':'cylinder','axis':[0,0,1],'axisPoint':[0,0,0],'radius':15}]}
        for patch in ({'axis':[0,0,0]},{'area':float('nan')},{'index':True},{'radius':0}):
            record=face(1);record.update(patch)
            with self.subTest(patch=patch),self.assertRaises(SchemaxisError) as caught:draft.selected(options,[record],'release')
            self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')

    def test_coforged_witnesses_cannot_change_freshly_measured_saved_selection(self):
        from schemaxis.adaptors.freecad import draft_verify
        document=design();document['nodes'][3]['options']['faces']=[{'surface':'plane','normal':[1,0,0]}]
        prepared=adaptor.plan(document)
        inventory=[face(1,[1,0,0],[20,0,10]),face(2,[0,0,1],[0,0,20])]
        positive={'features':{'release':{'base':['N2',['Face1']],'faceInventory':inventory}}}
        saved={'features':{'release':{'base':['N2',['Face1']]}}}
        forged=copy.deepcopy(positive);forged['features']['release']['base'][1]=['Face2']
        forged['features']['release']['faceInventory']=[{**inventory[1],'index':1},{**inventory[0],'index':2}]
        with patch.object(draft_verify,'fresh_inventories',return_value={'stock':inventory}):
            draft_verify.verify('unused.FCStd',prepared,positive,copy.deepcopy(positive),saved)
            changed=copy.deepcopy(saved);changed['features']['release']['base'][1]=['Face2']
            with self.assertRaises(SchemaxisError) as caught:
                draft_verify.verify('unused.FCStd',prepared,forged,copy.deepcopy(forged),changed)
            self.assertIn('authored intent',caught.exception.fault.message)
            witness_only=copy.deepcopy(forged);witness_only['features']['release']['base'][1]=['Face1']
            with self.assertRaises(SchemaxisError) as caught:
                draft_verify.verify('unused.FCStd',prepared,witness_only,copy.deepcopy(witness_only),saved)
            self.assertIn('witness',caught.exception.fault.message)

    def test_geometry_reader_is_host_only_and_requires_configured_runtime(self):
        from schemaxis.adaptors.freecad import draft_verify
        prepared=adaptor.plan(design())
        with patch.dict(sys.modules,{'FreeCAD':object()}),patch('subprocess.Popen') as launch:
            with self.assertRaises(SchemaxisError) as caught:draft_verify.fresh_inventories('unused.FCStd',prepared)
            self.assertEqual(caught.exception.fault.code,'VERIFICATION_CONTEXT_REQUIRED');launch.assert_not_called()
        with patch.object(draft_verify,'executable',return_value=None),patch('subprocess.Popen') as launch:
            with self.assertRaises(SchemaxisError) as caught:draft_verify.fresh_inventories('unused.FCStd',prepared)
            self.assertEqual(caught.exception.fault.code,'VERIFICATION_RUNTIME_REQUIRED');launch.assert_not_called()

    def test_geometry_receipts_are_bounded_strict_finite_json(self):
        from schemaxis.adaptors.freecad.draft_verify import read_object
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'inventory.json';path.write_text('{"stock":[]}')
            self.assertEqual(read_object(path),{'stock':[]})
            for data in (b'{"stock":[],"stock":[]}',b'{"stock":NaN}',b'{"stock":1e999}',b'\xff',b'[]'):
                path.write_bytes(data)
                with self.subTest(data=data),self.assertRaises(SchemaxisError) as caught:read_object(path)
                self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')
            path.write_bytes(b' '*101)
            with self.assertRaises(SchemaxisError) as caught:read_object(path,100)
            self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')


if __name__=='__main__':unittest.main()
