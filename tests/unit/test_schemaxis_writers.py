# Copyright (C) 2026 David L F Gaden
"""Writer plans must retain explicit fidelity and publication ownership."""
import copy
import unittest
from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.paraview.job import plan, identities, schedule
from schemaxis.adaptors.paraview.writers import LOSSES


def document():
    return {'version':'schemaxis/1','nodes':[{'id':'sphere','filter':'pvSphere'}],
            'scenes':[{'id':'export','exports':[{'id':'mesh','node':'sphere',
                                               'writer':'pvWriteXMLPolyDataWriter'}]}]}


class WriterTests(unittest.TestCase):
    def test_writer_resources_are_typed_dependencies(self):
        value=document()
        value['nodes'].append({'id':'colours','filter':'pvResourcePVLookupTable'})
        export=value['scenes'][0]['exports'][0]
        export.update(writer='pvWritePPLYWriter',resources={'LookupTable':'colours'},acceptLosses=LOSSES['geometry'])
        master,scenes,_=plan(value)
        self.assertIn('colours',scenes[0]['selection']['order'])
        export['resources']['LookupTable']='sphere'
        with self.assertRaises(SchemaxisError) as caught:plan(value)
        self.assertEqual(caught.exception.fault.code,'TYPE_MISMATCH')

    def test_time_metadata_injection_is_disabled_unless_requested(self):
        from schemaxis.adaptors.paraview.writers import preserve_field_data
        class Writer:
            WriteTimeValue = 1
            def ListProperties(self): return ['WriteTimeValue']
        writer=Writer()
        preserve_field_data(writer,{})
        self.assertEqual(writer.WriteTimeValue,0)
        writer.WriteTimeValue=1
        preserve_field_data(writer,{'WriteTimeValue':True})
        self.assertEqual(writer.WriteTimeValue,1)

    def test_exports_keep_dependency_and_schedule_identity(self):
        master,scenes,result=plan(document())
        self.assertEqual(result['expectedPublications'],1)
        self.assertEqual(scenes[0]['selection']['order'],['sphere'])
        ordered=[identity for scene,visit in schedule(master,scenes) for identity in identities(scene,visit)]
        self.assertEqual(ordered[0]['kind'],'export')
        self.assertEqual(ordered[0]['writer'],'mesh')

    def test_lossy_exports_require_explicit_acceptance(self):
        value=document(); export=value['scenes'][0]['exports'][0]
        export['writer']='pvWritePSTLWriter'
        with self.assertRaises(SchemaxisError) as caught:plan(value)
        self.assertEqual(caught.exception.fault.code,'LOSS_NOT_ACCEPTED')
        export['acceptLosses']=LOSSES['geometry'];export['tolerance']=1e-6
        self.assertEqual(plan(value)[1][0]['exports'][0]['comparison'],'geometry')

    def test_writer_cannot_be_a_pipeline_node(self):
        value=document();value['nodes'][0]['filter']='pvWriteXMLPolyDataWriter'
        with self.assertRaises(SchemaxisError) as caught:plan(value)
        self.assertEqual(caught.exception.fault.code,'INVALID_OPERATION_ROLE')

    def test_managed_filename_series_and_invalid_verification_are_rejected(self):
        for change in [{'options':{'FileName':'outside.vtp'}}, {'options':{'WriteTimeSteps':True}},
                       {'extension':'../outside'}, {'tolerance':-1}, {'tolerance':float('nan')},
                       {'tolerance':1e-6}, {'comparison':'unverified'}, {'acceptLosses':'fields'}]:
            value=document();value['scenes'][0]['exports'][0].update(change)
            with self.subTest(change=change),self.assertRaises(SchemaxisError):plan(value)

    def test_json_cannot_claim_exact_fidelity(self):
        value=document();value['scenes'][0]['exports'][0].update(
            writer='pvWriteJSONImageWriter',comparison='exact')
        with self.assertRaises(SchemaxisError) as caught:plan(value)
        self.assertEqual(caught.exception.fault.code,'INVALID_VERIFICATION')

    def test_secondary_file_lists_cannot_redirect_a_readback(self):
        cases=[('pvExodusIIReader',{'FilePattern':'%s.%04d','FilePrefix':'in'}),
               ('pvPLOT3DReader',{'QFileName':['other.q']}),
               ('pvSLACDataReader',{'ModeFileName':['other.mod']}),
               ('pvRTXMLPolyDataReader',{'Location':'other'})]
        for operation,options in cases:
            value=document();value['scenes'][0]['exports'][0]['readback']={'operation':operation,'options':options}
            with self.subTest(operation=operation),self.assertRaises(SchemaxisError) as caught:plan(value)
            self.assertEqual(caught.exception.fault.code,'MANAGED_FILENAME')

    def test_readback_schema_has_no_file_list_option(self):
        from schemaxis.adaptors.paraview.catalogue import generated_declarations
        from schemaxis.adaptors.paraview.schema import scene_schema
        declarations=generated_declarations();definitions={}
        scene_schema(declarations,definitions)
        variants=definitions['readback']['anyOf'][1]['oneOf']
        seen=set()
        for variant in variants:
            name=variant['properties']['operation']['const'];seen.add(name)
            managed={k for k,v in declarations[name]['options'].items() if 'vtkSMFileListDomain' in v['nativeDomains']}
            offered=set(variant['properties'].get('options',{}).get('properties',{}))
            self.assertFalse(managed&offered,name)
        self.assertIn('pvExodusIIReader',seen)

    def test_readback_filename_is_owned_by_publication(self):
        value=document();value['scenes'][0]['exports'][0]['readback']={
            'operation':'pvXMLPolyDataReader','options':{'FileName':['outside.vtp']}}
        with self.assertRaises(SchemaxisError) as caught:plan(value)
        self.assertEqual(caught.exception.fault.code,'MANAGED_FILENAME')
