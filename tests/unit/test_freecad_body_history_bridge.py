"""Portable typed history identity and generation boundaries without native imports."""
import copy
from contextlib import nullcontext
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptors.freecad.adaptor import _native_plan
from schemaxis.adaptors.freecad import source_bridge as bridge
from schemaxis.core.faults import SchemaxisError


def pure(second=False):
    d={'version':'schemaxis.freecad/1','nodes':[
        {'id':'part','filter':'body'},
        {'id':'outline','filter':'rectangle','inputs':{'body':'part'},'options':{'width':24,'height':16}},
        {'id':'pad','filter':'pad','inputs':{'body':'part','profile':'outline'},'options':{'length':7}}],
        'output':'pad'}
    if second:d['nodes'][2]['options']['direction']='forward'
    return d


class BodyHistoryBridge(unittest.TestCase):
    def test_both_generations_recompile_without_original_producer_or_assets(self):
        for second in (False,True):
            authored=pure(second);prepared=_native_plan(authored);saved=bridge.record(authored,prepared)
            self.assertEqual(prepared['partDesign'].get('generation',1),2 if second else 1)
            self.assertEqual(bridge.capability(saved),'bodyHistory')
            self.assertEqual(saved['bodyHistory']['version'],bridge.BODY_HISTORY)
            with patch('schemaxis.adaptors.freecad.source_envelope.read_members',return_value={}):
                self.assertEqual(bridge.definition('retired-producer.FCStd',saved),prepared)
            authored['nodes'][2]['options']['length']=9
            self.assertEqual(saved['bodyHistory']['authored']['nodes'][2]['options']['length'],7)

    def test_only_full_compiled_generation1_body_history_opts_into_copy_regeneration(self):
        authored=pure();prepared=_native_plan(authored);facts=bridge.record(authored,prepared)
        self.assertTrue(bridge.requires_copy_regeneration(facts))
        self.assertFalse(bridge.requires_copy_regeneration({'profile':'rectangle'}))
        self.assertTrue(bridge.requires_copy_regeneration({'generation':2}))
        for kind in ('definition','authored','version','frame','extra','dual','generation','bool'):
            changed=copy.deepcopy(facts)
            if kind=='definition':changed['bodyHistory']['definition']['output']='outline'
            elif kind=='authored':changed['bodyHistory']['authored']['nodes'][2]['options']['length']=8
            elif kind=='version':changed['bodyHistory']['version']='future'
            elif kind=='frame':changed['sourceFrame']='world'
            elif kind=='extra':changed['bodyHistory']['extra']='receipt override'
            elif kind=='dual':changed['seedHistory']=copy.deepcopy(changed['bodyHistory'])
            elif kind=='generation':changed['bodyHistory']=bridge.record(pure(True),_native_plan(pure(True)))['bodyHistory']
            else:changed['generation']=True
            with self.subTest(kind=kind),self.assertRaises(SchemaxisError):bridge.requires_copy_regeneration(changed)

    def test_generation1_copy_requires_full_fresh_binder_before_payload_delegation(self):
        from schemaxis.adaptors.freecad import assembly_payloads
        from xml.etree import ElementTree as ET
        authored=pure();facts=bridge.record(authored,_native_plan(authored))
        prepared={'parts':[{'id':'typed','source':facts}]}
        root=ET.fromstring('<Document><StringHasher2 file="table"/><Objects/><ObjectData/></Document>')
        members={'Document.xml':b'host XML supplied separately','GuiDocument.xml':b'host view',
                 'table':b'StringTableStart v1 0\n'}
        with patch.object(assembly_payloads,'read_members',return_value=members):
            with self.assertRaisesRegex(ValueError,'fresh native regeneration'):
                assembly_payloads.bind(prepared,'submitted.FCStd',root,{}, {},lambda n:None)
            marker=object()
            with patch('schemaxis.adaptors.freecad.history_copy_verify.bind_regenerated',
                       side_effect=ValueError('full unused dictionary or payload differs')) as bind:
                with self.assertRaisesRegex(ValueError,'full unused dictionary or payload differs'):
                    assembly_payloads.bind(prepared,'submitted.FCStd',root,{}, {},lambda n:None,marker)
                bind.assert_called_once_with('submitted.FCStd',root,marker)

    def test_authored_compiled_version_and_frame_coforgeries_do_not_select_history(self):
        d=pure();p=_native_plan(d);saved=bridge.record(d,p)
        for kind in ('intent','definition','version','extra','frame','dual'):
            changed=copy.deepcopy(saved)
            if kind=='intent':changed['bodyHistory']['authored']['nodes'][2]['options']['length']=9
            elif kind=='definition':changed['bodyHistory']['definition']['output']='outline'
            elif kind=='version':changed['bodyHistory']['version']='future'
            elif kind=='extra':changed['bodyHistory']['property']='arbitrary'
            elif kind=='frame':changed['sourceFrame']='world'
            else:changed['seedHistory']={'authored':d,'definition':p}
            with self.subTest(kind=kind),patch('schemaxis.adaptors.freecad.source_envelope.read_members',return_value={}):
                with self.assertRaises(SchemaxisError):bridge.definition('captured.FCStd',changed)

    def test_ordinary_history_does_not_gain_included_file_or_import_roles(self):
        d=pure();p=_native_plan(d);saved=bridge.record(d,p)
        properties={'PartDesign::Body':{'Shape':'Part::PropertyPartShape'}};extensions={};transient={};vocabulary={}
        with patch('schemaxis.adaptors.freecad.source_envelope.read_members',return_value={}):
            actual=bridge.policy('capture.FCStd',saved,properties,extensions,transient,vocabulary)
        self.assertIs(actual[1],properties);self.assertNotIn('FileIncluded',actual[4]);self.assertNotIn('Part::Feature',actual[1])

    def test_legacy_imported_seed_keeps_exact_original_record(self):
        d={'version':'schemaxis.freecad/1','nodes':[
            {'id':'stock','filter':'importMesh','options':{'file':'examples/schemaxis/freecad-body-stock.stl','units':'mm'}},
            {'id':'part','filter':'body'},{'id':'seed','filter':'bodySeed','inputs':{'body':'part','source':'stock'}}],'output':'seed'}
        p=_native_plan(d)
        self.assertEqual(bridge.record(d,p),{'sourceFrame':'bodyLocal','seedHistory':{'authored':d,'definition':p}})

    def test_primitive_seed_is_new_body_history_not_legacy_import_permission(self):
        d={'version':'schemaxis.freecad/1','nodes':[
            {'id':'stock','filter':'box'},{'id':'part','filter':'body'},
            {'id':'seed','filter':'bodySeed','inputs':{'body':'part','source':'stock'}}],'output':'seed'}
        p=_native_plan(d);saved=bridge.record(d,p)
        self.assertEqual(bridge.capability(saved),'bodyHistory')
        with patch('schemaxis.adaptors.freecad.source_envelope.read_members',return_value={}):
            _,properties,_,_,vocabulary=bridge.policy('capture.FCStd',{'generation':2,**saved},{},{},{},{})
        self.assertIn('Part::Box',properties);self.assertNotIn('FileIncluded',vocabulary)

    def test_nonfinal_or_foreign_generation_does_not_receive_replay_capability(self):
        p=_native_plan(pure())
        for change in ('tip','generation'):
            changed=copy.deepcopy(p)
            if change=='tip':changed['output']='outline'
            else:changed['partDesign']['generation']=9
            with self.subTest(change=change),self.assertRaises(SchemaxisError):bridge.record(pure(),changed)

    def test_old_pure_and_mixed_captures_require_recapture_without_consulting_old_paths(self):
        for others in ([],[{'id':'new','source':bridge.record(pure(),_native_plan(pure()))}]):
            saved={'sourced':True,'parts':[{'id':'old','source':{'file':'/retired/model.FCStd'}},*others]}
            with patch('schemaxis.adaptors.freecad.assembly.plan') as old_paths:
                with self.assertRaises(SchemaxisError) as error:bridge.replay_plan('run',{},saved)
                self.assertEqual(error.exception.fault.code,'RERUN_REQUIRED');old_paths.assert_not_called()

    def test_preopen_requests_explicit_local_authority_never_unwraps_export_dictionary(self):
        d=pure();p=_native_plan(d);facts={**bridge.record(d,p),'volume':12,'area':20,'bounds':[0,2,0,2,0,3]}
        local={'frame':'bodyLocal','body':'N0','shape':{k:facts[k] for k in ('volume','area','bounds')}}
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'capture.FCStd';path.write_bytes(b'qualified boundary fixture')
            facts.update(bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            with patch.object(bridge,'definition',return_value=p),patch.object(bridge,'originals',return_value=nullcontext({})),\
                    patch('schemaxis.adaptors.freecad.part_reconstruction.verify',return_value=local) as verify:
                bridge.verify_before_open(path,facts)
            verify.assert_called_once_with(path,p,{},body_local=True)
            with patch.object(bridge,'definition',return_value=p),patch.object(bridge,'originals',return_value=nullcontext({})),\
                    patch('schemaxis.adaptors.freecad.part_reconstruction.verify',return_value={'bodyLocalExportEvidence':local,'exportEvidence':{}}):
                with self.assertRaises(SchemaxisError):bridge.verify_before_open(path,facts)
            def concurrent_change(*args,**kwargs):
                # Same size: the checked digest, not a size-only gate, must fail.
                path.write_bytes(b'Qualified boundary fixture');return local
            with patch.object(bridge,'definition',return_value=p),patch.object(bridge,'originals',return_value=nullcontext({})),\
                    patch('schemaxis.adaptors.freecad.part_reconstruction.verify',side_effect=concurrent_change):
                with self.assertRaises(SchemaxisError) as error:bridge.verify_before_open(path,facts)
                self.assertEqual(error.exception.fault.code,'INPUT_CHANGED')


if __name__=='__main__':unittest.main()
