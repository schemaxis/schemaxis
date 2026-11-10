"""Artist surface planning, channel semantics and namespace boundaries."""
import copy
import unittest
from schemaxis.adaptors.blender.adaptor import plan
from schemaxis.adaptors.blender.surface_compile import all_material_graphs
from schemaxis.errors import SchemaxisError


def document(surface):
    return {'version':'schemaxis.blender.production/1','prepareOnly':True,
            'production':{'surfaceMaterials':[surface],
                'objects':[{'id':'panel','kind':'mesh','vertices':[[0,0,0],[1,0,0],[0,1,0]],
                            'faces':[[0,1,2]],'material':surface['id']}]}}


class Surfaces(unittest.TestCase):
    def test_replanning_preserves_artist_intent(self):
        prepared=plan(document({'id':'finish'}))
        self.assertIsNotNone(prepared)
        from schemaxis.adaptors.blender.production import validate
        intent=validate(document({'id':'finish'})['production'],{})
        again=validate(copy.deepcopy(intent),{})
        self.assertEqual(intent,again)
        self.assertEqual(intent['materialGraphs'],[])
        compiled=all_material_graphs(intent)
        self.assertEqual([g['id'] for g in compiled],['finish'])
        shader=next(n for n in compiled[0]['nodes'] if n['kind']=='principled')
        self.assertEqual(shader['values']['ior'],1.5)
        self.assertEqual(shader['values']['roughness'],.5)

    def test_packed_scalar_requires_data_colour_space(self):
        value=document({'id':'finish','samplers':[{'id':'orm','image':'texture'}],
                        'roughness':{'kind':'sample','sampler':'orm','channel':'green'}})
        value['production']['images']=[{'id':'texture','file':'texture.png'}]
        with self.assertRaises(SchemaxisError) as caught:plan(value)
        self.assertEqual(caught.exception.fault.code,'INVALID_SURFACE_IMAGE')
        value['production']['images'][0]['colourSpace']='Non-Color'
        self.assertIsNotNone(plan(value))

    def test_surface_and_graph_share_namespace(self):
        value=document({'id':'finish'})
        value['production']['materialGraphs']=[{'id':'finish','nodes':[{'id':'out','kind':'output'}],'links':[]}]
        with self.assertRaises(SchemaxisError) as caught:plan(value)
        self.assertEqual(caught.exception.fault.code,'DUPLICATE_ID')

    def test_colour_association_is_independent_of_other_alpha_consumers(self):
        from schemaxis.adaptors.blender.production import validate
        value=document({'id':'finish','samplers':[{'id':'colour','image':'texture'}],
                        'emission':{'colour':{'kind':'sample','sampler':'colour'}}})['production']
        value['images']=[{'id':'texture','file':'texture.png'}]
        for sampled in (False,True):
            current=copy.deepcopy(value)
            if sampled:current['surfaceMaterials'][0]['coverage']={'kind':'sample','sampler':'colour','channel':'alpha'}
            graph=all_material_graphs(validate(current,{}))[0]
            image=next(n for n in graph['nodes'] if n['kind']=='image')
            self.assertTrue(any(l['from']=={'node':image['id'],'socket':'alpha'} for l in graph['links']))
            self.assertTrue(any(n['kind']=='math' and n['properties']['operation']=='GREATER_THAN' for n in graph['nodes']))

    def test_schema_and_optional_expert_controls_preserve_old_graph(self):
        from jsonschema import Draft202012Validator
        from schemaxis.adaptors.blender.production import validate,schema
        from schemaxis.adaptors.blender.node_catalogue import validate_graph
        value=document({'id':'finish','normal':{'kind':'heightBump'},'subsurface':{'kind':'skin'},
                        'specular':{'tangent':{'kind':'radial'}}})['production']
        normalized=validate(value,{})
        self.assertEqual(list(Draft202012Validator(schema()).iter_errors(value)),[])
        self.assertEqual(list(Draft202012Validator(schema()).iter_errors(normalized)),[])
        old=validate_graph({'id':'old','nodes':[{'id':'surface','kind':'principled'},{'id':'out','kind':'output'}],
                            'links':[]},'material','test')
        self.assertEqual(len(old['nodes'][0]['values']),10)
        self.assertEqual(old['nodes'][0]['properties'],{})
        for node in ({'id':'s','kind':'principled','values':{'subsurfaceIor':1.4}},
                     {'id':'s','kind':'image','properties':{'projectionBlend':.5}},
                     {'id':'s','kind':'normalMap','properties':{'space':'WORLD','uvMap':'Named'}}):
            with self.assertRaises(SchemaxisError):
                validate_graph({'id':'invalid','nodes':[node,{'id':'out','kind':'output'}],'links':[]},'material','test')

    def test_ineffective_engine_and_thin_wall_layers(self):
        value=document({'id':'finish','thinFilm':{'thicknessNanometres':{'kind':'constant','value':250}}})
        value['render']={'renderer':{'kind':'eevee'}}
        with self.assertRaises(SchemaxisError) as caught:plan(value)
        self.assertEqual(caught.exception.fault.code,'UNSUPPORTED_SURFACE_RENDERER')

    def test_smart_filter_requires_builtin_osl_on_both_authoring_routes(self):
        artist=document({'id':'finish','samplers':[{'id':'colour','image':'texture','filter':'smart'}],
                         'emission':{'colour':{'kind':'sample','sampler':'colour'}}})
        artist['production']['images']=[{'id':'texture','file':'texture.png'}]
        expert=copy.deepcopy(artist);expert['production'].pop('surfaceMaterials')
        expert['production']['materialGraphs']=[{'id':'finish','nodes':[
            {'id':'image','kind':'image','properties':{'image':'texture','interpolation':'Smart'}},
            {'id':'out','kind':'output'}],'links':[]}]
        for value in (artist,expert):
            with self.assertRaises(SchemaxisError) as caught:plan(value)
            self.assertEqual(caught.exception.fault.code,'UNSUPPORTED_SHADER_BACKEND')
            value['render']={'renderer':{'kind':'cycles','shadingSystem':'osl'}}
            self.assertIsNotNone(plan(value))

    def test_thin_thickness_is_connected_and_screen_requires_tracing(self):
        from schemaxis.adaptors.blender.production import validate
        intent=validate(document({'id':'finish','wall':'thin'})['production'],{})
        graph=all_material_graphs(intent)[0]
        output=next(n for n in graph['nodes'] if n['kind']=='output')
        thickness=next(l for l in graph['links'] if l['to']=={'node':output['id'],'socket':'thickness'})
        source=next(n for n in graph['nodes'] if n['id']==thickness['from']['node'])
        self.assertEqual(source['kind'],'value');self.assertEqual(source['properties']['value'],0)
        self.assertEqual(graph['surfacePolicy']['thickness'],'SLAB')
        value=document({'id':'finish','realtime':{'transmission':'screen'}})
        value['render']={'renderer':{'kind':'eevee'}}
        with self.assertRaises(SchemaxisError) as caught:plan(value)
        self.assertEqual(caught.exception.fault.code,'INEFFECTIVE_SURFACE_SOURCE')
        value['render']['renderer']['rayTracing']={'kind':'screen'}
        self.assertIsNotNone(plan(value))
        value=document({'id':'finish','wall':'thin','subsurface':{'kind':'skin'}})
        with self.assertRaises(SchemaxisError) as caught:plan(value)
        self.assertEqual(caught.exception.fault.code,'INEFFECTIVE_SURFACE_SOURCE')
        value=document({'id':'finish','samplers':[{'id':'data','image':'texture','filter':'smart'}],
                        'emission':{'colour':{'kind':'sample','sampler':'data'}}})
        value['production']['images']=[{'id':'texture','file':'texture.png'}]
        value['render']={'renderer':{'kind':'eevee'}}
        with self.assertRaises(SchemaxisError) as caught:plan(value)
        self.assertEqual(caught.exception.fault.code,'UNSUPPORTED_SURFACE_RENDERER')


if __name__=='__main__':unittest.main()
