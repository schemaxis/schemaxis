"""Strategic scene-production contracts: references, motion, rigging and nodes."""
import copy
import json
from pathlib import Path
import unittest
from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.blender.production import validate,schema
from schemaxis.adaptors.blender.node_catalogue import CATALOGUES,validate_graph
from schemaxis.adaptors.blender.adaptor import plan
ROOT=Path(__file__).resolve().parents[2]
GRAPH={'paint':{'filter':'material'},'box':{'filter':'cube'}}


class ProductionContracts(unittest.TestCase):
    def reject(self,prod,code=None):
        with self.assertRaises(SchemaxisError) as caught:validate(prod,GRAPH)
        if code:self.assertEqual(caught.exception.fault.code,code)
    def test_empty_defaults_are_complete_and_immutable(self):
        value={};found=validate(value,GRAPH);self.assertEqual(value,{})
        self.assertEqual((found['frameStart'],found['frameEnd'],found['currentFrame']),(1,250,1));self.assertEqual(found['objects'],[])
        self.assertEqual(validate(found,GRAPH),found)
    def test_schema_and_catalogue_are_host_safe(self):
        import sys
        json.dumps(schema());self.assertNotIn('bpy',sys.modules)
        self.assertGreaterEqual(sum(len(c) for c in CATALOGUES.values()),60)
    def test_connected_example_plan_counts_all_outputs(self):
        value=json.loads((ROOT/'examples/schemaxis/blender-production.json').read_text());before=copy.deepcopy(value)
        master,selected,prepared=plan(value);self.assertEqual(value,before)
        self.assertEqual(prepared['expectedPublications'],6)
        self.assertEqual(master.document['scenes'][0]['production']['currentFrame'],6)
    def test_wrong_scalar_types_fail(self):
        for key,value in [('objects',True),('tracks',{}),('constraints',3),('materialGraphs','x'),('frameStart',True),('gravity',[0,0,float('nan')])]:
            with self.subTest(key=key):self.reject({key:value})
    def test_unknown_scene_and_object_properties_fail(self):
        self.reject({'python':'print(1)'},'UNKNOWN_ARGUMENT')
        self.reject({'objects':[{'id':'a','kind':'empty','nativePath':'bpy.context'}]},'UNKNOWN_ARGUMENT')
    def test_duplicate_and_missing_refs_fail(self):
        cases=[{'objects':[{'id':'box','kind':'empty'}]}, {'objects':[{'id':'a','kind':'instance','source':'missing'}]}, {'objects':[{'id':'a','kind':'empty','collection':'absent'}]}, {'hierarchy':[{'object':'box','parent':'missing'}]}, {'materialBindings':[{'object':'box','material':'missing'}]}, {'geometryBindings':[{'object':'box','graph':'missing'}]}]
        for value in cases:
            with self.subTest(value=value):self.reject(value)
    def test_cycles_fail(self):
        cases=[{'collections':[{'id':'a','parent':'b'},{'id':'b','parent':'a'}]}, {'objects':[{'id':'a','kind':'instance','source':'b'},{'id':'b','kind':'instance','source':'a'}]}, {'objects':[{'id':'a','kind':'empty'}],'hierarchy':[{'object':'box','parent':'a'},{'object':'a','parent':'box'}]}]
        for value in cases:
            with self.subTest(value=value):self.reject(value,'DEPENDENCY_CYCLE')
    def test_native_specific_irrelevant_light_options_fail(self):
        self.reject({'objects':[{'id':'lamp','kind':'light','type':'AREA','angle':1}]},'UNSUPPORTED_OPTION')
        self.reject({'objects':[{'id':'lamp','kind':'light','type':'SUN','size':2}]},'UNSUPPORTED_OPTION')
    def test_mesh_topology_and_uv_are_semantic(self):
        mesh={'id':'triangle','kind':'mesh','vertices':[[0,0,0],[1,0,0],[0,1,0]],'faces':[[0,1,2]],'uv':[[[0,0],[1,0],[0,1]]]}
        found=validate({'objects':[mesh]},GRAPH);self.assertEqual(found['objects'][0]['uv'],mesh['uv'])
        for change in ({'faces':[[0,1,3]]},{'faces':[[0,1,1]]},{'uv':[[[0,0],[1,0]]]}):
            with self.subTest(change=change):self.reject({'objects':[{**mesh,**change}]})
    def test_keyframes_and_channel_types(self):
        track={'object':'box','channel':'location','keys':[{'frame':1,'value':[0,0,0]},{'frame':11,'value':[1,2,3]}]}
        found=validate({'tracks':[track]},GRAPH);self.assertEqual(found['tracks'][0]['interpolation'],'LINEAR')
        for bad in ({'channel':'data.path'}, {'channel':'lightEnergy'}, {'keys':list(reversed(track['keys']))}, {'keys':[{'frame':1,'value':[0,0,0]},{'frame':1,'value':[1,2,3]}]}, {'keys':[{'frame':251,'value':[0,0,0]}]}):
            with self.subTest(bad=bad):self.reject({'tracks':[{**track,**bad}]})
        self.reject({'tracks':[track,track]},'INVALID_ANIMATION')
    def test_timeline_bounds_and_scale(self):
        self.reject({'frameStart':10,'frameEnd':1},'INVALID_TIMELINE')
        self.reject({'frameStart':10,'currentFrame':1},'INVALID_TIMELINE')
        self.reject({'objects':[{'id':'empty','kind':'empty','scale':[1,0,1]}]},'INVALID_TRANSFORM')
    def test_rig_structure_and_bindings(self):
        rig={'id':'rig','bones':[{'id':'root','head':[0,0,0],'tail':[0,0,1]}]}
        found=validate({'rigs':[rig],'skin':[{'object':'box','rig':'rig','weights':[{'bone':'root','vertices':[0,1],'weight':1}]}]},GRAPH)
        self.assertEqual(found['rigs'][0]['bones'][0]['deform'],True)
        for change in ({'head':[0,0,1]}, {'parent':'missing'}, {'connected':True}):
            with self.subTest(change=change):self.reject({'rigs':[{**rig,'bones':[{**rig['bones'][0],**change}]}]})
        self.reject({'rigs':[rig],'skin':[{'object':'box','rig':'rig','weights':[{'bone':'missing','vertices':[0],'weight':1}]}]},'UNKNOWN_REFERENCE')
    def test_constraint_targets_and_mode_semantics(self):
        self.reject({'constraints':[{'id':'c','object':'box','kind':'copyLocation'}]},'MISSING_ARGUMENT')
        self.reject({'constraints':[{'id':'c','object':'box','kind':'followPath','target':'box'}]},'TYPE_MISMATCH')
        self.reject({'constraints':[{'id':'c','object':'box','kind':'inverseKinematics','target':'box'}]},'TYPE_MISMATCH')
    def test_simulation_bounds(self):
        self.reject({'objects':[{'id':'empty','kind':'empty'}],'rigidBodies':[{'object':'empty'}]},'TYPE_MISMATCH')
        self.reject({'simulationFrames':[11,1]},'INVALID_SIMULATION')
        self.reject({'frameEnd':2000,'simulationFrames':[2000]},'RESOURCE_BUDGET_EXCEEDED')


class AssetAndProductionRoute(unittest.TestCase):
    def test_gltf_external_dependencies_fail_before_native_import(self):
        import struct
        import tempfile
        from schemaxis.adaptors.blender.production_assets import require_embedded_gltf
        with tempfile.TemporaryDirectory() as temp:
            for format in ('glb','gltf'):
                path=Path(temp)/('source.'+format)
                for field in ('buffers','images'):
                    for uri in ('data:application/octet-stream;base64,AA==','outside.bin'):
                        value={'asset':{'version':'2.0'},field:[{'uri':uri}]}
                        payload=json.dumps(value).encode()
                        if format=='glb':
                            payload+=b' '*((-len(payload))%4)
                            path.write_bytes(struct.pack('<5I',0x46546c67,2,20+len(payload),len(payload),0x4e4f534a)+payload)
                        else:path.write_bytes(payload)
                        if uri.startswith('data:'):require_embedded_gltf(path,format)
                        else:
                            with self.assertRaises(SchemaxisError) as caught:require_embedded_gltf(path,format)
                            self.assertEqual(caught.exception.fault.code,'UNSUPPORTED_ASSET_DEPENDENCY')
    def test_full_asset_id_is_visible_without_authored_graph(self):
        value={'version':'schemaxis.blender.production/1','production':{'assets':[{'id':'model','file':'model.glb'}]}}
        before=copy.deepcopy(value);master,selected,prepared=plan(value)
        self.assertEqual(value,before);self.assertEqual(master.document['scenes'][0]['visible'],['model']);self.assertEqual(len(selected.order),1)
        self.assertEqual(prepared['expectedPublications'],2)
    def test_native_asset_source_units_and_formats_are_closed(self):
        for format in ('glb','gltf','blend','stl','ply','obj','usd'):
            found=validate({'assets':[{'id':'model','file':'asset.'+format,'format':format}]},GRAPH)
            self.assertEqual(found['assets'][0]['format'],format)
        for asset in ({'id':'a','file':'a.glb','sourceUnits':'millimetres'}, {'id':'a','file':'a','format':'python'}, {'id':'a','file':'a','scale':[1,-1,1]}):
            with self.subTest(asset=asset),self.assertRaises(SchemaxisError):validate({'assets':[asset]},GRAPH)
    def test_asset_references_cannot_alias_mesh_or_rig_ids(self):
        for p in ({'assets':[{'id':'box','file':'x'}]}, {'assets':[{'id':'a','file':'x'}],'rigs':[{'id':'a','bones':[{'id':'root'}]}]}):
            with self.subTest(p=p),self.assertRaises(SchemaxisError):validate(p,GRAPH)
    def test_production_route_rejects_unknown_controls(self):
        value={'version':'schemaxis.blender.production/1','production':{'assets':[{'id':'model','file':'model.glb'}]}}
        for changes in ({'python':'x'}, {'production':{'objects':True}}, {'visible':['missing']}):
            with self.subTest(changes=changes),self.assertRaises(SchemaxisError):plan({**value,**changes})
    def test_private_lowering_anchor_does_not_collide(self):
        from schemaxis.adaptors.blender.production_job import lower
        value={'version':'schemaxis.blender.production/1','production':{'assets':[{'id':'SXProductionMaterial','file':'a.glb'}]}}
        lowered=lower(value);self.assertEqual(lowered['nodes'][0]['id'],'SXProductionMaterialX')

    def test_future_asset_handoff_reserves_render_resources_without_lowering_files(self):
        from schemaxis.adaptors.blender.integration import provisionalResources,validateHandoff
        value={'version':'schemaxis.blender.production/1','render':{'threads':2},'prepareOnly':True,
               'production':{'assets':[{'id':'model','file':{'$artifact':'cad','index':1},'format':'stl',
                                        'sourceUnits':'millimetres'}],'renderFrames':[1]}}
        before=copy.deepcopy(value)
        self.assertEqual(provisionalResources(value,{},'image'),{'threads':2,'gpus':0})
        self.assertIsNone(validateHandoff(value,{'version':'schemaxis.blender.render/1'},'render'))
        self.assertIsNone(validateHandoff(value,{'version':'schemaxis.ffmpeg/1'},'video'))
        self.assertEqual(value,before)
        with self.assertRaises(SchemaxisError) as caught:provisionalResources(value,{'threads':1},'image')
        self.assertEqual(caught.exception.fault.code,'INVALID_EXECUTION')
        value['production']['renderFrames']=[]
        with self.assertRaises(SchemaxisError) as caught:validateHandoff(value,{'version':'schemaxis.ffmpeg/1'},'video')
        self.assertEqual(caught.exception.fault.code,'UNSUPPORTED_HANDOFF')


class NodeGraphContracts(unittest.TestCase):
    def graph(self):return {'id':'finish','nodes':[{'id':'surface','kind':'principled'},{'id':'out','kind':'output'}],'links':[{'from':{'node':'surface','socket':'shader'},'to':{'node':'out','socket':'surface'}}]}
    def reject(self,g,code):
        with self.assertRaises(SchemaxisError) as caught:validate_graph(g,'material','graph')
        self.assertEqual(caught.exception.fault.code,code)
    def test_graph_defaults_and_immutability(self):
        g=self.graph();before=copy.deepcopy(g);v=validate_graph(g,'material','graph');self.assertEqual(g,before);self.assertEqual(v['nodes'][0]['values']['roughness'],.5)
    def test_no_arbitrary_constructors_or_properties(self):
        g=self.graph();g['nodes'][0]['kind']='bpy.ops.wm.open_mainfile';self.reject(g,'UNSUPPORTED_NODE')
        g=self.graph();g['nodes'][0]['properties']={'__class__':'x'};self.reject(g,'UNKNOWN_ARGUMENT')
    def test_links_reject_missing_ids_socket_types_and_duplicates(self):
        for field,value,code in [('node','absent','UNKNOWN_REFERENCE'),('socket','arbitrary','UNKNOWN_SOCKET')]:
            g=self.graph();g['links'][0]['from'][field]=value;self.reject(g,code)
        g=self.graph();g['links']*=2;self.reject(g,'INVALID_NODE_GRAPH')
        g=self.graph();g['nodes'].insert(0,{'id':'math','kind':'math'});g['links'][0]['from']={'node':'math','socket':'value'};self.reject(g,'TYPE_MISMATCH')
    def test_graph_cycles(self):
        g=self.graph();g['nodes']=[{'id':'a','kind':'math'},{'id':'b','kind':'math'},g['nodes'][1]];g['links']=[{'from':{'node':'a','socket':'value'},'to':{'node':'b','socket':'a'}},{'from':{'node':'b','socket':'value'},'to':{'node':'a','socket':'a'}}];self.reject(g,'DEPENDENCY_CYCLE')

if __name__=='__main__':unittest.main()
