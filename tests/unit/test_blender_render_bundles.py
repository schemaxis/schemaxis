"""Closed layer references and aggregate jobs must be admitted before native work."""
import copy
import unittest
from jsonschema import Draft202012Validator
from schemaxis.errors import SchemaxisError
from schemaxis.schema import arguments_schema
from schemaxis.adaptors.blender import render_bundles as bundles


def authored():
    return {'viewLayers':[{'id':'utility','passes':['combined','depth']}],
            'renderBundles':[{'id':'panel','outputs':[{'kind':'multilayer','id':'data','layers':[
                {'id':'beauty','source':{'kind':'pass','layer':'utility','pass':'combined'}},
                {'id':'depth','source':{'kind':'pass','layer':'utility','pass':'depth'}}]}]}]}


def validate(value):
    return bundles.validate(value,kinds={'lamp':'light','patch':'mesh','camera':'camera'},
                            materials={'finish'},collections={'product','background'},assets={'captured'},worlds={'studio'})


class RenderBundles(unittest.TestCase):
    def refuses(self,value,code):
        with self.assertRaises(SchemaxisError) as caught:validate(value)
        self.assertEqual(caught.exception.fault.code,code)

    def test_literal_schema_and_detached_default_timeline(self):
        value=authored();before=copy.deepcopy(value)
        self.assertEqual(list(Draft202012Validator(arguments_schema(bundles.OPTIONS)).iter_errors(value)),[])
        result=validate(value);self.assertEqual(value,before)
        self.assertEqual(result['renderBundles'][0]['frames'],[1])
        self.assertEqual(result['viewLayers'][0]['cryptomatte'],{'object':False,'material':False,'asset':False,'levels':6,'accurate':True})
        later=authored();later.update(frameStart=7,frameEnd=20)
        self.assertEqual(validate(later)['renderBundles'][0]['frames'],[7])
        self.assertEqual(validate(result),result)

    def test_collection_occurrences_and_object_resource_types(self):
        value=authored();layer=value['viewLayers'][0]
        layer.update(materialOverride='finish',worldOverride='studio',collections=[
            {'target':{'kind':'collection','collection':'background'},'mode':'exclude'},
            {'target':{'kind':'asset','asset':'captured','path':['assembly','body']},'mode':'holdout'}])
        self.assertEqual(validate(value)['viewLayers'][0]['collections'][1]['target']['path'],['assembly','body'])
        duplicate=copy.deepcopy(value);duplicate['viewLayers'][0]['collections'].append(layer['collections'][0]);self.refuses(duplicate,'INVALID_RENDER_BUNDLE')
        wrong=authored();wrong['renderLightgroups']=[{'id':'key','lights':['patch']}];self.refuses(wrong,'TYPE_MISMATCH')
        shared=authored();shared['renderLightgroups']=[{'id':'key','lights':['lamp']},{'id':'fill','lights':['lamp']}];self.refuses(shared,'INVALID_RENDER_BUNDLE')

    def test_omitted_png_encoding_matches_explicit_defaults_and_budget(self):
        value=authored();value['renderBundles'][0]['outputs']=[{
            'kind':'image','id':'preview',
            'source':{'kind':'pass','layer':'utility','pass':'combined'}}]
        original=copy.deepcopy(value);implicit=validate(value)
        explicit=copy.deepcopy(value)
        explicit['renderBundles'][0]['outputs'][0]['encoding']={'kind':'png'}
        self.assertEqual(implicit,validate(explicit))
        self.assertEqual(value,original)
        self.assertEqual(implicit['renderBundles'][0]['outputs'][0]['encoding'],
                         {'kind':'png','depth':'8','channels':'rgba','compression':15})
        self.assertEqual(bundles.budget(implicit,[32,16])['uncompressedOutputBytes'],32*16*4)
        self.assertEqual(validate(implicit),implicit)
        implicit['renderBundles'][0]['outputs'][0]['encoding']['channels']='rgb'
        self.assertEqual(validate(value)['renderBundles'][0]['outputs'][0]['encoding']['channels'],'rgba')

    def test_aov_matte_references_and_engine_availability(self):
        value=authored();value['renderAovs']=[{'id':'temperature','type':'value'}];layer=value['viewLayers'][0];layer['aovs']=['temperature']
        value['renderBundles'][0]['outputs'][0]['layers'].append({'id':'field','source':{'kind':'aov','layer':'utility','aov':'temperature'}})
        normalized=validate(value);bundles.validate_engine(normalized,'cycles');bundles.validate_engine(normalized,'eevee')
        with self.assertRaises(SchemaxisError):bundles.validate_engine(normalized,'workbench')
        unknown=copy.deepcopy(value);unknown['renderBundles'][0]['outputs'][0]['layers'][-1]['source']['aov']='other';self.refuses(unknown,'INVALID_RENDER_BUNDLE')
        reserved=authored();reserved['renderAovs']=[{'id':'Depth'}];self.refuses(reserved,'INVALID_RENDER_BUNDLE')
        odd=authored();odd['viewLayers'][0]['cryptomatte']={'object':True,'levels':3};self.refuses(odd,'INVALID_RENDER_BUNDLE')
        disabled=authored();disabled['viewLayers'][0]['enabled']=False;self.refuses(disabled,'INVALID_RENDER_BUNDLE')

    def test_missing_disabled_ports_and_output_path_names_refuse(self):
        source=authored();source['renderBundles'][0]['outputs'][0]['layers'][0]['source']['pass']='normal';self.refuses(source,'INVALID_RENDER_BUNDLE')
        no_layer=authored();no_layer['viewLayers']=[];self.refuses(no_layer,'INVALID_RENDER_BUNDLE')
        bad_name=authored();bad_name['renderBundles'][0]['outputs'][0]['id']='../escape';self.refuses(bad_name,'INVALID_NAME')
        arbitrary=authored();arbitrary['renderBundles'][0]['outputs'][0]['directory']='/tmp/out';self.refuses(arbitrary,'INVALID_ARGUMENT')

    def test_compositor_references_require_actual_curated_output_ports(self):
        value=authored();value['compositor']={'id':'comp','nodes':[{'id':'render','kind':'render'}]}
        value['renderBundles'][0]['outputs']=[{'kind':'image','id':'composite','source':{'kind':'compositor','node':'render','socket':'image'}}]
        validate(value)
        wrong=copy.deepcopy(value);wrong['renderBundles'][0]['outputs'][0]['source']['socket']='arbitraryNativeSocket';self.refuses(wrong,'TYPE_MISMATCH')
        missing=copy.deepcopy(value);missing.pop('compositor');self.refuses(missing,'UNKNOWN_REFERENCE')

    def test_small_known_panel_and_cross_layer_frame_output_costs(self):
        spec=validate(authored());cost=bundles.budget(spec,[32,16])
        self.assertEqual(cost,{'estimatedWorkingBytes':94208,'uncompressedOutputBytes':10240,'publications':1,'layerFrames':1})
        with self.assertRaises(SchemaxisError) as caught:bundles.budget(spec,[2048,2048])
        self.assertEqual(caught.exception.fault.code,'RESOURCE_BUDGET_EXCEEDED')
        huge=authored();huge['renderBundles'][0]['frames']=list(range(1,129));template=huge['renderBundles'][0]['outputs'][0]
        huge['renderBundles'][0]['outputs']=[{**copy.deepcopy(template),'id':'out'+str(i)} for i in range(64)]
        with self.assertRaises(SchemaxisError) as caught:bundles.budget(validate(huge),[32,16])
        self.assertEqual(caught.exception.fault.code,'RESOURCE_BUDGET_EXCEEDED');self.assertEqual(caught.exception.fault.observed['publications'],8192)

    def test_raw_cryptomatte_and_indices_keep_exact_float_identifiers(self):
        value=authored();value['viewLayers'][0]['cryptomatte']={'object':True}
        output=value['renderBundles'][0]['outputs'][0];output['layers'].append({'id':'crypto','source':{'kind':'cryptomatte','layer':'utility','matte':'object'}})
        bundles.budget(validate(value),[32,16]);output['precision']='half'
        with self.assertRaises(SchemaxisError) as caught:bundles.budget(validate(value),[32,16])
        self.assertEqual(caught.exception.fault.code,'INVALID_RENDER_BUNDLE')

    def test_identifier_data_cannot_escape_float_requirement_through_png(self):
        for kind in ('cryptomatte','objectIndex','materialIndex'):
            value=authored();layer=value['viewLayers'][0]
            if kind=='cryptomatte':
                layer['cryptomatte']={'object':True}
                source={'kind':'cryptomatte','layer':'utility','matte':'object'}
            else:
                layer['passes'].append(kind)
                source={'kind':'pass','layer':'utility','pass':kind}
            value['renderBundles'][0]['outputs']=[{'kind':'image','id':'identifiers','source':source}]
            with self.assertRaises(SchemaxisError) as caught:bundles.budget(validate(value),[32,16])
            self.assertEqual(caught.exception.fault.code,'INVALID_RENDER_BUNDLE')
            value['renderBundles'][0]['outputs'][0]['encoding']={'kind':'exr','precision':'float'}
            bundles.budget(validate(value),[32,16])

    def test_whole_matte_family_accounts_for_all_coverage_ranks(self):
        value=authored();value['viewLayers'][0]['cryptomatte']={'object':True,'levels':16}
        output=value['renderBundles'][0]['outputs'][0]
        source={'kind':'cryptomatte','layer':'utility','matte':'object'}
        output['layers']=[{'id':'objects','source':source}]
        spec=validate(value)
        self.assertEqual(bundles.source_components(spec,source),32)
        self.assertEqual(bundles.source_slots(spec,source),8)
        self.assertEqual(bundles.budget(spec,[32,16])['uncompressedOutputBytes'],32*16*32*4)
        # A rank selector could silently discard overlapping identities. The
        # typed family publishes every declared rank under one logical name.
        source['index']=0
        self.refuses(value,'INVALID_ARGUMENT')


if __name__=='__main__':unittest.main()
