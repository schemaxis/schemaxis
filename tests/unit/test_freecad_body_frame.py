"""Explicit Body layout keeps world publication and local source facts distinct."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptors.freecad.adaptor import _native_plan
from schemaxis.adaptors.freecad.body_seed import world_body,output_name,frame
from schemaxis.adaptors.freecad import source_bridge,assembly_sources
from schemaxis.core.faults import SchemaxisError

FRAME={'origin':[7,-11,13],'xAxis':[.6,.8,0],'normal':[.48,-.36,.8]}


def document():
    return {'version':'schemaxis.freecad/1','nodes':[
        {'id':'part','filter':'body','options':{'frame':copy.deepcopy(FRAME)}},
        {'id':'outline','filter':'rectangle','options':{'width':24,'height':16},'inputs':{'body':'part'}},
        {'id':'slab','filter':'pad','options':{'length':7},'inputs':{'body':'part','profile':'outline'}},
        {'id':'bore','filter':'circle','options':{'radius':2,'origin':[0,0,7],'centre':[3,2]},'inputs':{'body':'part'}},
        {'id':'finished','filter':'pocket','options':{'direction':'backward'},'inputs':{'base':'slab','profile':'bore'}}],
        'output':'finished'}


class BodyFrame(unittest.TestCase):
    def test_explicit_frame_publishes_only_selected_final_body_without_hidden_options(self):
        authored=document();before=copy.deepcopy(authored);prepared=_native_plan(authored)
        self.assertEqual(authored,before);self.assertEqual(prepared['partDesign']['generation'],2)
        self.assertNotIn('seeds',prepared['partDesign'])
        self.assertEqual(world_body(prepared,'finished'),'part')
        self.assertEqual(output_name(prepared,'finished'),'N0')
        for identity,native in [('outline','N1'),('slab','N2'),('bore','N3'),('part','N0')]:
            self.assertIsNone(world_body(prepared,identity));self.assertEqual(output_name(prepared,identity),native)
        for actual,expected in zip(frame(prepared,'part'),[.6,-.64,.48,7,.8,.48,-.36,-11,0,.6,.8,13,0,0,0,1]):
            self.assertAlmostEqual(actual,expected)
        facts=source_bridge.record(authored,prepared)
        self.assertEqual(facts['sourceFrame'],'bodyLocal');self.assertIn('bodyHistory',facts)
        self.assertNotIn('seedHistory',facts)

    def test_unframed_generation1_and_generation2_names_and_frames_stay_unchanged(self):
        for second in (False,True):
            authored=document();del authored['nodes'][0]['options']['frame']
            if not second:
                del authored['nodes'][-1]['options']['direction'];authored['nodes'][3]['options']['origin']=[0,0,0]
            prepared=_native_plan(authored)
            self.assertEqual(output_name(prepared,'finished'),'N4')
            self.assertIsNone(world_body(prepared,'finished'))
            self.assertNotIn('frame',prepared['nodes'][0]['options'])

    def test_other_body_frame_does_not_promote_selected_unframed_tip(self):
        authored=document();del authored['nodes'][0]['options']['frame']
        authored['nodes'].extend([
            {'id':'other','filter':'body','options':{'frame':copy.deepcopy(FRAME)}},
            {'id':'otherProfile','filter':'circle','inputs':{'body':'other'}},
            {'id':'otherTip','filter':'pad','inputs':{'body':'other','profile':'otherProfile'}}])
        prepared=_native_plan(authored)
        self.assertIsNone(world_body(prepared,'finished'));self.assertEqual(output_name(prepared,'finished'),'N4')
        self.assertEqual(world_body(prepared,'otherTip'),'other');self.assertEqual(output_name(prepared,'otherTip'),'N5')

    def test_invalid_frame_and_property_escape_still_refuse(self):
        for bad in ({**FRAME,'normal':[.6,.8,0]},{**FRAME,'xAxis':[1,1,0]},
                    {**FRAME,'expression':'other.Placement'}):
            authored=document();authored['nodes'][0]['options']['frame']=bad
            with self.subTest(frame=bad),self.assertRaises(SchemaxisError):_native_plan(authored)

    def test_admission_selects_local_witness_and_refuses_wrong_body_or_missing_witness(self):
        # Real fixture bytes with synthetic readback isolate witness selection.
        # Whole archive/native authority is NOT claimed by this host test.
        from test_freecad_assembly_sources import producer,AUXILIARIES
        with tempfile.TemporaryDirectory() as temporary:
            authored=document()
            def observations(receipt):
                receipt['partDesignObservations']['auxiliaries']={'part':{
                    k:{'name':n,'type':t} for k,(n,t) in AUXILIARIES.items()}}
                receipt['native'].update(volume=999,area=1000,bounds=[90,100,90,100,90,100])
                receipt['bodyLocalExportEvidence']={'frame':'bodyLocal','body':'N0','shape':{
                    'valid':True,'solids':1,'volume':240,'area':200,'bounds':[-12,12,-8,8,0,7]}}
            path=producer(Path(temporary)/'producer',authored,mutate=observations)
            with patch('schemaxis.adaptors.freecad.source_envelope.inspect',return_value={'expandedBytes':10}), \
                    patch('schemaxis.adaptors.freecad.part_design_saved.verify'):
                facts=assembly_sources.admit(str(path),'part.source')
                self.assertEqual(facts['volume'],240);self.assertEqual(facts['bounds'],[-12,12,-8,8,0,7])
                receipt=path.parent/'verification.json';original=receipt.read_text()
                for change in ('body','frame','missing'):
                    value=json.loads(original)
                    if change=='missing':del value['bodyLocalExportEvidence']
                    else:value['bodyLocalExportEvidence'][change]='N999' if change=='body' else 'world'
                    receipt.write_text(json.dumps(value))
                    with self.subTest(change=change),self.assertRaises(SchemaxisError):
                        assembly_sources.admit(str(path),'part.source')


if __name__=='__main__':unittest.main()
