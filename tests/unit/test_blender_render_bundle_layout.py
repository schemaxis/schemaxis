"""Logical render data expands to bounded, deterministic native file layouts."""
import copy
import unittest

from schemaxis.errors import SchemaxisError
from schemaxis.adaptors.blender import render_bundle_layout as layout
from test_blender_render_bundles import authored, validate


class BundleLayout(unittest.TestCase):
    def test_depth_beauty_planes_and_frame_membership_are_literal(self):
        value=authored();value['renderBundles'][0]['frames']=[1,12]
        spec=validate(value);before=copy.deepcopy(spec)
        files=layout.jobs(spec,'0002')
        self.assertEqual([f['file'] for f in files],['0002-bundle-panel-data-0001.exr','0002-bundle-panel-data-0012.exr'])
        self.assertEqual(layout.channels(files[0]),{
            'beauty.R':{'scientific':False,'identifiers':False},'beauty.G':{'scientific':False,'identifiers':False},
            'beauty.B':{'scientific':False,'identifiers':False},'beauty.A':{'scientific':False,'identifiers':False},
            'depth.V':{'scientific':True,'identifiers':False}})
        self.assertEqual(files[0]['slots'][1]['source'],{'kind':'layer','layer':'utility','socket':'Depth'})
        self.assertEqual(spec,before)
        files[0]['encoding']['precision']='half'
        self.assertEqual(spec,before)

    def test_crypto_alias_keeps_all_rank_pairs_and_separate_layer_identity(self):
        value=authored();value['viewLayers'][0]['cryptomatte']={'object':True,'levels':6}
        second=copy.deepcopy(value['viewLayers'][0]);second['id']='alternate';value['viewLayers'].append(second)
        value['renderBundles'][0]['outputs'][0]['layers']=[
            {'id':'left','source':{'kind':'cryptomatte','layer':'utility','matte':'object'}},
            {'id':'right','source':{'kind':'cryptomatte','layer':'alternate','matte':'object'}}]
        definition=layout.definitions(validate(value))[0]
        self.assertEqual([s['id'] for s in definition['slots']],['left_matte00','left_matte01','left_matte02','right_matte00','right_matte01','right_matte02'])
        self.assertEqual(len(layout.channels(definition)),24)
        self.assertIn('left_matte00.r',layout.channels(definition))
        self.assertNotIn('left_matte00.R',layout.channels(definition))
        self.assertEqual([s['source']['layer'] for s in definition['slots']],['utility']*3+['alternate']*3)
        self.assertEqual([s['source']['socket'] for s in definition['slots']],['CryptoObject00','CryptoObject01','CryptoObject02']*2)
        self.assertTrue(all(s['scientific'] and s['identifiers'] for s in definition['slots']))

    def test_expanded_rank_name_collision_is_refused_before_native_nodes(self):
        value=authored();value['viewLayers'][0]['cryptomatte']={'object':True}
        value['renderBundles'][0]['outputs'][0]['layers']=[
            {'id':'objects','source':{'kind':'cryptomatte','layer':'utility','matte':'object'}},
            {'id':'objects_matte00','source':{'kind':'pass','layer':'utility','pass':'depth'}}]
        with self.assertRaises(SchemaxisError) as caught:layout.definitions(validate(value))
        self.assertEqual(caught.exception.fault.code,'OUTPUT_SLOT_COLLISION')

    def test_motion_has_four_components_and_png_has_an_owned_image_suffix(self):
        value=authored();value['viewLayers'][0]['passes'].append('motion')
        value['renderBundles'][0]['outputs']=[
            {'id':'vectors','kind':'image','encoding':{'kind':'exr'},'source':{'kind':'pass','layer':'utility','pass':'motion'}},
            {'id':'preview','kind':'image','source':{'kind':'pass','layer':'utility','pass':'combined'}}]
        files=layout.jobs(validate(value))
        self.assertEqual(set(layout.channels(files[0])),{'image.X','image.Y','image.Z','image.W'})
        self.assertEqual(files[0]['slots'][0]['socketType'],'VECTOR')
        self.assertEqual(files[0]['slots'][0]['components'],4)
        self.assertEqual(files[1]['file'],'0000-bundle-panel-preview-0001image.png')
        self.assertFalse(any(s['scientific'] for s in files[1]['slots']))
        for prefix in ('../old','a/b','/absolute','name#frame','x'*65):
            with self.assertRaises(SchemaxisError):layout.jobs(validate(value),prefix)


if __name__=='__main__':unittest.main()
