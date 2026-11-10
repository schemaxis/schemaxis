"""Reusable motion validates ownership and independently composes layer maths."""
import copy
import unittest
from schemaxis.errors import SchemaxisError
from schemaxis.adaptors.blender.production import validate,schema,graph_references
from schemaxis.adaptors.blender.production_motion_verify import evaluate
try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator=None


def clip():return {'id':'walk','tracks':[{'target':'part','channel':'location','keys':[{'frame':1,'value':[0,0,0]},{'frame':11,'value':[4,0,0]}]}]}
def doc():return {'frameEnd':41,'objects':[{'id':'part','kind':'empty','location':[10,0,0]}],'clips':[clip()],'layers':[{'id':'walk','clip':'walk','bindings':[{'target':'part','object':'part'}]}]}


class MotionContracts(unittest.TestCase):
    def test_defaults_immutable_idempotent_and_schema_hostsafe(self):
        d=doc();before=copy.deepcopy(d);r=validate(d,{})
        self.assertEqual(d,before);self.assertEqual(validate(r,{}),r)
        self.assertEqual(r['layers'][0]['sourceEnd'],11)
        self.assertIn('clips',schema()['properties'])
    @unittest.skipIf(Draft202012Validator is None,'optional schema developer package unavailable')
    def test_authored_and_normalized_motion_match_the_public_schema(self):
        d=doc();validator=Draft202012Validator(schema())
        self.assertEqual(list(validator.iter_errors(d)),[])
        self.assertEqual(list(validator.iter_errors(validate(d,{}))),[])
    def test_reusable_clip_bindings_and_additive_reference_pose(self):
        d=doc();d['layers'][0].update(blend='ADD',influence=.5)
        r=validate(d,{});self.assertEqual(evaluate(r,6)[('part','','','location')],[11,0,0])
    def test_reverse_repeat_trim_and_scale(self):
        d=doc();d['layers'][0].update(reverse=True,repeat=2,scale=2)
        r=validate(d,{})
        for frame,x in [(1,4),(11,2),(21,4),(31,2),(41,0)]:self.assertEqual(evaluate(r,frame)[('part','','','location')],[x,0,0])
    def test_layer_math_and_fades(self):
        d=doc();d['layers'][0].update(blend='REPLACE',fadeIn=4,fadeOut=4)
        r=validate(d,{})
        self.assertEqual(evaluate(r,3)[('part','','','location')],[5.4,0,0])
        self.assertEqual(evaluate(r,1)[('part','','','location')],[10,0,0])
        for blend,x in [('ADD',12),('SUBTRACT',8),('MULTIPLY',20),('REPLACE',2)]:
            d=doc();d['layers'][0]['blend']=blend
            self.assertEqual(evaluate(validate(d,{}),6)[('part','','','location')],[x,0,0])
    def test_invalid_channels_bindings_ranges_and_ownership(self):
        for change in ({'bindings':[]},{'clip':'absent'},{'sourceEnd':30},{'scale':0},{'start':40},{'fadeIn':11},{'blend':'CUSTOM'}):
            d=doc();d['layers'][0].update(change)
            with self.subTest(change=change),self.assertRaises(SchemaxisError):validate(d,{})
        d=doc();d['clips'][0]['tracks'][0]['channel']='data.arbitrary'
        with self.assertRaises(SchemaxisError):validate(d,{})
        d=doc();d['tracks']=[{'object':'part','channel':'location','keys':[{'frame':1,'value':[0,0,0]}]}]
        with self.assertRaises(SchemaxisError):validate(d,{})
    def test_morph_sparse_masks_and_dependency_order(self):
        mesh={'id':'part','kind':'mesh','vertices':[[0,0,0],[1,0,0],[0,1,0]],'faces':[[0,1,2]]}
        morph={'object':'part','keys':[{'id':'lift','offsets':[{'vertices':[1],'offset':[0,0,2]}],'mask':[{'vertices':[1],'weight':.5}]},{'id':'more','relativeTo':'lift','coordinates':[[0,0,0],[1,0,4],[0,1,0]]}]}
        r=validate({'objects':[mesh],'shapeKeys':[morph]},{});self.assertEqual(r['shapeKeys'][0]['keys'][1]['relativeTo'],'lift')
        for changes in ({'relativeTo':'missing'},{'coordinates':mesh['vertices']},{'offsets':[{'vertices':[1,1],'offset':[0,0,2]}]},{'maximum':-.1}):
            bad=copy.deepcopy(morph);bad['keys'][0].update(changes)
            with self.subTest(changes=changes),self.assertRaises(SchemaxisError):validate({'objects':[mesh],'shapeKeys':[bad]}, {})
    def test_absolute_progress_and_role_types_are_validated(self):
        d=doc();d['clips'][0]['tracks'][0]['channel']='morphProgress';d['clips'][0]['tracks'][0]['keys']=[{'frame':1,'value':0},{'frame':11,'value':1}]
        with self.assertRaises(SchemaxisError):validate(d,{})
    def test_unselected_graph_targets_still_get_built(self):
        d=doc();d['objects']=[];d['layers'][0]['bindings'][0]['object']='graphMesh'
        r=validate(d,{'graphMesh':{'filter':'cube'}})
        self.assertEqual(graph_references(r,{'graphMesh':{}}),['graphMesh'])

if __name__=='__main__':unittest.main()
