import copy
import unittest
from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.blender.settings import render_settings
from schemaxis.adaptors.blender.production import validate,schema
from schemaxis.adaptors.blender.integration import _render_resources,provisionalResources
from schemaxis.adaptors.blender.node_catalogue import validate_graph


class RenderPolicy(unittest.TestCase):
    def test_builtin_osl_has_explicit_applicability_and_stable_defaults(self):
        baseline=render_settings({})
        self.assertEqual(render_settings({'renderer':{'kind':'cycles','shadingSystem':'svm'}}),baseline)
        for device in ('CPU','OPTIX'):
            value=render_settings({'device':device,'renderer':{'kind':'cycles','shadingSystem':'osl'}})
            self.assertEqual(value['renderer'],{'kind':'cycles','shadingSystem':'osl'})
            self.assertEqual(render_settings(value),value)
        with self.assertRaises(SchemaxisError) as error:
            render_settings({'device':'CUDA','renderer':{'kind':'cycles','shadingSystem':'osl'}})
        self.assertEqual(error.exception.fault.code,'UNSUPPORTED_SHADER_BACKEND')
    def test_engine_defaults_are_complete_and_idempotent(self):
        for kind in ('cycles','eevee','workbench'):
            value={'renderer':{'kind':kind}};original=copy.deepcopy(value)
            normalized=render_settings(value)
            self.assertEqual(value,original)
            self.assertEqual(render_settings(normalized),normalized)
            self.assertEqual(normalized['colourManagement']['view'],{'kind':'agx','contrast':'base'})
            self.assertEqual(_render_resources(normalized,{},'test')['gpus'],int(kind!='cycles'))
    def test_inactive_legacy_and_rotation_controls_are_refused(self):
        for kind,option,value in [('eevee','samples',7),('eevee','denoise',True),('workbench','worldStrength',1),('workbench','lightPosition',[1,2,3]),('workbench','device','CUDA')]:
            with self.assertRaises(SchemaxisError) as error:render_settings({'renderer':{'kind':kind},option:value})
            self.assertEqual(error.exception.fault.code,'INEFFECTIVE_RENDER_SETTING')
        with self.assertRaises(SchemaxisError):render_settings({'renderer':{'kind':'workbench','lighting':{'kind':'studio','rotation':1}}})
    def test_shadow_direction_normalizes_without_overflow(self):
        for vector in ([1,1,1],[1e308,1e308,0],[1e-310,0,0]):
            settings=render_settings({'renderer':{'kind':'workbench','shadows':{'kind':'on','direction':vector}}})
            self.assertEqual(render_settings(settings),settings)
            self.assertAlmostEqual(sum(x*x for x in settings['renderer']['shadows']['direction']),1)
        with self.assertRaises(SchemaxisError):render_settings({'renderer':{'kind':'workbench','shadows':{'kind':'on','direction':[0,0,0]}}})
    def test_typed_view_limits_and_nested_filter_controls(self):
        with self.assertRaises(SchemaxisError):render_settings({'colourManagement':{'gamma':1e-100}})
        for value in ({'renderer':{'kind':'eevee','fastGI':{'kind':'ambient'}}},{'renderer':{'kind':'eevee','rayTracing':{'kind':'screen'},'fastGI':{'kind':'global','roughnessThreshold':1}}},{'colourManagement':{'gamma':0}},{'colourManagement':{'view':{'kind':'standard','contrast':'punchy'}}},{'renderer':{'kind':'eevee','rayTracing':{'kind':'screen','denoise':{'kind':'filtered','spatial':False,'temporal':False,'bilateral':False}}}}):
            with self.assertRaises(SchemaxisError):render_settings(value)
        result=render_settings({'renderer':{'kind':'eevee','rayTracing':{'kind':'screen','denoise':{'kind':'none'}}},'colourManagement':{'view':{'kind':'aces20'},'whiteBalance':{'kind':'on','temperature':4500}}})
        self.assertEqual(result['renderer']['rayTracing']['denoise'],{'kind':'none'})
    def test_colour_selectors_need_declared_colour_channels(self):
        mesh={'id':'patch','kind':'mesh','vertices':[[0,0,0],[1,0,0],[0,1,0]],'faces':[[0,1,2]]}
        data={'object':'patch','activeColour':'paint','renderColour':'paint','attributes':[{'name':'paint','kind':'colour','mode':'constant','value':[.2,.3,.4,1]}]}
        normalized=validate({'objects':[mesh],'meshData':[data]},{});self.assertEqual(validate(normalized,{}),normalized)
        data['activeColour']='missing'
        with self.assertRaises(SchemaxisError):validate({'objects':[mesh],'meshData':[data]}, {})
    def test_unknown_renderer_never_fabricates_cpu_reservation(self):
        document={'version':'schemaxis.blender.production/1','render':{'renderer':{'$value':'previous','path':'result'}}}
        self.assertNotIn('gpus',provisionalResources(document,{},'test'))
    def test_display_colours_are_distinct_from_shader_graph_values(self):
        graph={'id':'surface','nodes':[{'id':'emit','kind':'emission'},{'id':'out','kind':'output'}],'links':[{'from':{'node':'emit','socket':'shader'},'to':{'node':'out','socket':'surface'}}],'viewportColour':[.1,.2,.3]}
        spec={'materialGraphs':[graph],'objects':[{'id':'solid','kind':'curve','points':[[0,0,0],[1,1,0]],'displayColour':{'kind':'colour','value':[.3,.2,.1]}},{'id':'copy','kind':'instance','source':'solid'}]}
        normalized=validate(spec,{})
        self.assertEqual(normalized['materialGraphs'][0]['viewportColour'],[.1,.2,.3])
        self.assertEqual(normalized['objects'][1]['displayColour'],{'kind':'inherit'})
        self.assertEqual(validate(normalized,{}),normalized)
        with self.assertRaises(SchemaxisError):validate_graph(graph,'material','group')
        with self.assertRaises(SchemaxisError):validate({'objects':[{'id':'helper','kind':'empty'},{'id':'copy','kind':'instance','source':'helper','displayColour':{'kind':'colour'}}]}, {})
        self.assertIn('viewportColour',schema()['properties']['materialGraphs']['items']['properties'])


if __name__=='__main__':unittest.main()
