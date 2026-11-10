"""AOV taps preserve typed source endpoints and complete post-edit costs."""
import copy
import unittest
from types import SimpleNamespace

from schemaxis.adaptors.blender import render_aovs as aovs
from schemaxis.adaptors.blender.shader_budget_native import ShaderBudget
from schemaxis.errors import SchemaxisError


def writer(source=None, target=None):
    return {'id':'roughnessField','aov':'field',
            'target':target or {'kind':'material','material':'finish'},
            'source':source or {'kind':'value','value':.375}}


def validate(records, **options):
    return aovs.validate(records,aovs=[{'id':'field','type':'value'},{'id':'tint','type':'colour'}],
                         materials={'finish'},assets={'model'},worlds={'studio'},**options)


class RenderAovs(unittest.TestCase):
    def test_defaulted_attribute_and_owner_selection_are_detached(self):
        value=[writer({'kind':'attribute','name':'sx_temperature'})];before=copy.deepcopy(value)
        result=validate(value)
        self.assertEqual(result[0]['source'],{'kind':'attribute','name':'sx_temperature','channel':'factor','missing':'error'})
        self.assertEqual(value,before)
        extension=aovs.extension(result[0]);self.assertEqual(extension['requiredAttribute'],'sx_temperature')
        self.assertEqual(len(extension['nodes']),2)
        self.assertEqual(extension['links'][0]['from']['socket'],'factor')
        self.assertEqual(aovs.planned_cost(result),2)
        self.assertEqual(validate(result),result)

    def test_generic_field_taps_refuse_cycles_builtin_namespace_for_every_owner(self):
        for target in ({'kind':'material','material':'finish'},
                       {'kind':'world','world':'studio'},
                       {'kind':'captured','asset':'model','sourceObject':'Body','sourceSlot':0}):
            for name in ('temperature', 'N', 'uv', 'color', 'generated', 'velocity'):
                for missing in ('error', 'zero'):
                    with self.subTest(target=target,name=name,missing=missing):
                        with self.assertRaises(SchemaxisError) as caught:
                            validate([writer({'kind':'attribute','name':name,'missing':missing},target)])
                        fault=caught.exception.fault
                        self.assertEqual(fault.code,'RESERVED_AOV_ATTRIBUTE')
                        self.assertEqual(fault.location,'production.materialAovs.roughnessField.source.name')
                        self.assertIn('Rename',fault.observed['recovery'])
        # The source restriction does not reserve the output pass namespace.
        result=aovs.validate([{**writer({'kind':'attribute','name':'sx_temperature'}),'aov':'temperature'}],
                             aovs=[{'id':'temperature','type':'value'}],materials={'finish'})
        self.assertEqual(result[0]['aov'],'temperature')

    def test_known_owners_types_and_single_writer_per_owner_are_required(self):
        attacks=[
            [writer(target={'kind':'material','material':'missing'})],
            [writer({'kind':'colour','value':[.2,.3,.4,1]})],
            [writer(),{**writer(),'id':'second'}],
            [{**writer(),'aov':'missing'}],
            [writer(target={'kind':'captured','asset':'model','sourceObject':'Mesh'})],
        ]
        for records in attacks:
            with self.subTest(records=records),self.assertRaises(SchemaxisError):validate(records)
        value=writer(target={'kind':'world','world':'studio'})
        self.assertEqual(validate([value])[0]['target'],value['target'])

    def test_artist_tap_reuses_existing_compiled_link_without_sampler_copy(self):
        graph={'id':'finish','nodes':[
            {'id':'sample','kind':'value','values':{},'properties':{'value':.25}},
            {'id':'surface','kind':'principled','values':{'metallic':.7},'properties':{}},
            {'id':'output','kind':'output','values':{},'properties':{}}],
            'links':[{'from':{'node':'sample','socket':'value'},'to':{'node':'surface','socket':'roughness'}}]}
        source=writer({'kind':'surfaceChannel','channel':'roughness'});before=copy.deepcopy(graph)
        records=validate([source],graphs=[graph],surfaces={'finish'})
        extension=aovs.extension(records[0],graphs=[graph],surfaces={'finish'})
        self.assertEqual(len(extension['nodes']),1)
        self.assertEqual(extension['links'][0]['from'],{'node':'sample','socket':'value'})
        self.assertEqual(graph,before)
        constant=writer({'kind':'surfaceChannel','channel':'metallic'})
        constant=validate([constant],graphs=[graph],surfaces={'finish'})[0]
        self.assertEqual(aovs.extension(constant,graphs=[graph],surfaces={'finish'})['nodes'][0]['values'],{'value':.7})
        with self.assertRaises(SchemaxisError):validate([source],graphs=[graph])

    def test_graph_output_is_semantic_and_missing_or_shader_ports_refuse(self):
        graph={'id':'finish','nodes':[{'id':'field','kind':'value','values':{},'properties':{'value':.2}}],'links':[]}
        source=writer({'kind':'graphOutput','node':'field','socket':'value'})
        result=validate([source],graphs=[graph]);extension=aovs.extension(result[0],graphs=[graph])
        self.assertEqual(extension['links'][0]['from'],{'node':'field','socket':'value'})
        source['source']['socket']='arbitrary_native_input'
        with self.assertRaises(SchemaxisError):validate([source],graphs=[graph])
        shader={'id':'finish','nodes':[{'id':'shader','kind':'emission','values':{},'properties':{}}],'links':[]}
        with self.assertRaises(SchemaxisError):
            validate([writer({'kind':'graphOutput','node':'shader','socket':'shader'})],graphs=[shader])

    def test_captured_slot_provenance_is_explicit_and_does_not_guess_aliases(self):
        target={'kind':'captured','asset':'model','sourceObject':'Body','sourceSlot':1}
        first=writer(target=target);second={**writer(target={**target,'sourceObject':'Other'}),'id':'other'}
        result=validate([first,second])
        self.assertNotEqual(aovs.target_key(result[0]['target']),aovs.target_key(result[1]['target']))
        # Native actual-ID alias detection remains a separate required guard.
        self.assertEqual(aovs.planned_cost(result),2)
        with self.assertRaises(SchemaxisError):
            validate([writer({'kind':'graphOutput','node':'guessed','socket':'value'},target)])

    def test_rebuilt_budget_counts_mutated_cached_owner_and_new_world_together(self):
        class Tree:
            def __init__(self,name,count):
                self.name=name;self.is_embedded_data=True
                self.nodes=[SimpleNamespace(bl_idname='ShaderNodeValue') for _ in range(count)]
        class Owner:
            def __init__(self,name,count):self.name=name;self.node_tree=Tree(name,count)
        material=Owner('same',2);world=Owner('same',2)
        budget=ShaderBudget();budget.material(material)
        material.node_tree.nodes.append(SimpleNamespace(bl_idname='ShaderNodeOutputAOV'))
        budget.material(material);self.assertEqual(budget.nodes,2)
        fresh=budget.rebuilt(owners=[material,world])
        self.assertEqual(fresh.nodes,5);self.assertEqual(len(fresh.material_ids),2)
        self.assertEqual(budget.nodes,2)
        world.node_tree.nodes=[SimpleNamespace(bl_idname='ShaderNodeValue') for _ in range(8190)]
        with self.assertRaises(SchemaxisError) as caught:budget.rebuilt(owners=[world])
        self.assertEqual(caught.exception.fault.code,'RESOURCE_BUDGET_EXCEEDED')
        self.assertEqual(budget.nodes,2)

    def test_owner_graph_binding_uses_logical_target_despite_native_name_collision(self):
        class Owner:
            def __init__(self,name):self.name=name
        imported=Owner('finish');authored=Owner('finish.001')
        graph={'id':'finish','nodes':[{'id':'field','kind':'value'}],'links':[]}
        tap=writer({'kind':'graphOutput','node':'field','socket':'value'})
        original=writer(target={'kind':'captured','asset':'model','sourceObject':'Body','sourceSlot':0})
        original['id']='captured'
        result=aovs.bind_owner_graphs([tap,original],{'roughnessField':authored,'captured':imported},[graph])
        self.assertIs(result[authored],graph)
        self.assertIsNone(result[imported])
        # The same native ID cannot masquerade as a different authored graph,
        # even if both declarations happen to use the same node identifiers.
        other={**copy.deepcopy(tap),'id':'other','target':{'kind':'material','material':'other'}}
        with self.assertRaises(SchemaxisError) as caught:
            aovs.bind_owner_graphs([tap,other],{'roughnessField':authored,'other':authored},
                                  [graph,{**graph,'id':'other'}])
        self.assertEqual(caught.exception.fault.code,'AMBIGUOUS_AOV_OWNER')


if __name__=='__main__':unittest.main()
