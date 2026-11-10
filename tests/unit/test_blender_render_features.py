"""Public feature composition, independent of native module imports."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from schemaxis.adaptors.blender.adaptor import plan
from schemaxis.adaptors.blender.render_features import verify_cache_publications
from schemaxis.errors import SchemaxisError


ROOT = Path(__file__).resolve().parents[2]


class RenderFeaturesTests(unittest.TestCase):
    def example(self, name):
        return json.loads((ROOT/'examples/schemaxis'/name).read_text())

    def test_unextended_production_keeps_historical_shape(self):
        doc = self.example('blender-freestyle-plate.json')
        del doc['production']['npr'];del doc['production']['viewLayers']
        master,_,_=plan(doc)
        spec=master.document['scenes'][0]['production']
        self.assertNotIn('worlds',spec)
        self.assertNotIn('viewLayers',spec)
        self.assertNotIn('simulationCaches',spec)

    def test_npr_namespace_and_layer_reference_survive_double_lowering(self):
        doc=self.example('blender-freestyle-plate.json')
        master,_,_=plan(doc)
        normalized=master.document['scenes'][0]['production']
        again,_,_=plan({**doc,'production':copy.deepcopy(normalized)})
        self.assertEqual(normalized,again.document['scenes'][0]['production'])
        doc['production']['npr']['layers'][0]['layer']='absent'
        with self.assertRaises(SchemaxisError):plan(doc)

    def test_cache_frame_membership_is_declared_not_receipt_count(self):
        spec={'simulationCaches':[{'id':'cloth_1','storage':'disk','frameStart':1,'frameEnd':2}]}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            records=[{'cacheId':'cloth_1','file':str(root/'blendcache_0000'/f'cloth_1_{frame:06d}_00.bphys'),
                      'relativePath':f'blendcache_0000/cloth_1_{frame:06d}_00.bphys'} for frame in (1,2)]
            verify_cache_publications(spec,records,root,0)
            with self.assertRaises(SchemaxisError):verify_cache_publications(spec,records[:1],root,0)
            altered=copy.deepcopy(records);altered[1]['file']=str(root/'blendcache_0000'/'cloth_1_000003_00.bphys')
            altered[1]['relativePath']='blendcache_0000/cloth_1_000003_00.bphys'
            with self.assertRaises(SchemaxisError):verify_cache_publications(spec,altered,root,0)
            with self.assertRaises(SchemaxisError):verify_cache_publications(spec,records+records[:1],root,0)


if __name__=='__main__':unittest.main()
