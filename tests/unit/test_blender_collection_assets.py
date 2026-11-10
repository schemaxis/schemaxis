"""Host contracts for explicit native scene selection and finite ownership."""
import copy
import unittest
from schemaxis.adaptors.blender.production_assets import validate_assets,verify_selection
from schemaxis.adaptors.blender.production import schema
from schemaxis.adaptors.blender.adaptor import plan
from schemaxis.core.faults import SchemaxisError


class CollectionAssets(unittest.TestCase):
    def spec(self,**values):return validate_assets([{'id':'model','file':'assembly.blend','format':'blend',**values}],'$.production')[0]
    def observation(self):return {'mode':'scene','scene':'Assembly','viewLayer':'Main','excluded':[['Hidden']],'projections':[],'sourceFps':24.0,'sourceFrameRange':[1,11]}
    def test_selectors_survive_both_public_routes_without_native_imports(self):
        asset={'id':'model','file':'assembly.blend','format':'blend','scene':'Assembly','viewLayer':'Main'}
        for doc in ({'version':'schemaxis.blender.production/1','production':{'assets':[asset]}},{'version':'schemaxis.blender/1','nodes':[{'id':'base','filter':'material'}],'scenes':[{'id':'scene','visible':['model'],'images':[{'id':'preview','size':[32,32],'cameras':[{'direction':[1,-2,1]}]}],'production':{'assets':[asset]}}]}):
            before=copy.deepcopy(doc);master,_,_=plan(doc);actual=master.document['scenes'][0]['production']['assets'][0]
            self.assertEqual((actual['scene'],actual['viewLayer']),('Assembly','Main'));self.assertEqual(doc,before)
        self.assertIn('viewLayer',schema()['properties']['assets']['items']['properties'])
    def test_exchange_assets_cannot_claim_native_selection(self):
        for fmt in ('glb','obj','stl','usd'):
            with self.subTest(fmt=fmt),self.assertRaises(SchemaxisError):self.spec(format=fmt,scene='Assembly')
    def test_explicit_selectors_bind_readback(self):
        spec=self.spec(scene='Assembly',viewLayer='Main');verify_selection(spec,self.observation())
        for key,value in [('scene','Other'),('viewLayer','All'),('mode','objectLibrary'),('sourceFps',float('nan')),('sourceFrameRange',[1,False]),('excluded',None)]:
            observed=self.observation();observed[key]=value
            with self.subTest(key=key),self.assertRaises(SchemaxisError):verify_selection(spec,observed)
    def test_inference_is_observable_but_not_an_arbitrary_selector(self):
        spec=self.spec();verify_selection(spec,self.observation());verify_selection(spec,{'mode':'objectLibrary','scene':'','viewLayer':''})
        for observed in (None,{}, {'mode':'scene','scene':'','viewLayer':'Main'}):
            with self.subTest(observed=observed),self.assertRaises(SchemaxisError):verify_selection(spec,observed)
        with self.assertRaises(SchemaxisError):verify_selection(self.spec(scene='Assembly'),{'mode':'objectLibrary','scene':'','viewLayer':''})

if __name__=='__main__':unittest.main()
