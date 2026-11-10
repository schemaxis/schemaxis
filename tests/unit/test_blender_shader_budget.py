import copy
import unittest
from unittest.mock import patch
from schemaxis.errors import SchemaxisError
from schemaxis.adaptors.blender.shader_budget import admit
from schemaxis.adaptors.blender.production import validate
from schemaxis.adaptors.blender.adaptor import run
from schemaxis.adaptors.blender.adaptor import plan


def nested(level):
    groups={'g0':[None,None]}
    for i in range(1,level+1):groups['g'+str(i)]=['g'+str(i-1),'g'+str(i-1),None,None]
    return groups


class ShaderBudgets(unittest.TestCase):
    def test_pure_dag_and_empty_production_apply_active_material_bound(self):
        d={'version':'schemaxis.blender/1','nodes':[], 'scenes':[{'id':'materials',
            'visible':[],'prepareOnly':True,'images':[{'id':'view','size':[32,32],
                'cameras':[{'direction':[0,0,1],'up':[0,1,0]}]}]}]}
        for i in range(4097):
            d['nodes'].extend([{'id':'m'+str(i),'filter':'material'},
                {'id':'o'+str(i),'filter':'cube','inputs':{'material':'m'+str(i)}}])
            d['scenes'][0]['visible'].append('o'+str(i))
        for production in (False,True):
            value=copy.deepcopy(d)
            if production:value['scenes'][0]['production']={}
            with self.assertRaises(SchemaxisError) as caught:plan(value)
            self.assertEqual(caught.exception.fault.code,'RESOURCE_BUDGET_EXCEEDED')
            self.assertEqual(caught.exception.fault.observed['estimatedNodes'],8194)
        # Unused DAG declarations do not allocate native materials.
        d['scenes'][0]['visible']=['o0']
        self.assertEqual(sum(plan(d)[0].nodes[n]['filter']=='material'
                             for n in plan(d)[1].order),1)
        d['scenes'][0]['production']={}
        self.assertEqual(sum(plan(d)[0].nodes[n]['filter']=='material'
                             for n in plan(d)[1].order),1)

    def test_one_native_budget_deduplicates_actual_ids_and_sums_owners(self):
        from schemaxis.adaptors.blender.shader_budget_native import ShaderBudget
        class Tree:
            bl_idname='ShaderNodeTree';is_embedded_data=False
            def __init__(self,name,nodes):self.name=name;self.nodes=nodes
        class Node:
            def __init__(self,tree=None):
                self.bl_idname='ShaderNodeGroup' if tree is not None else 'ShaderNodeEmission'
                self.node_tree=tree
        class Material:
            def __init__(self,name,tree):self.name=name;self.node_tree=tree
        child=Tree('g0',[Node(),Node()])
        for i in range(1,11):child=Tree('g'+str(i),[Node(child),Node(child),Node(),Node()])
        # Embedded tree display names are deliberately identical.
        first=Material('a',Tree('Shader Nodetree',[Node(child),Node()]))
        second=Material('b',Tree('Shader Nodetree',[Node(child),Node()]))
        budget=ShaderBudget();budget.material(first);budget.material(first)
        self.assertEqual(len(budget.roots),1)
        with self.assertRaises(SchemaxisError) as caught:budget.material(second)
        self.assertEqual(caught.exception.fault.code,'RESOURCE_BUDGET_EXCEEDED')
        self.assertIn('aggregate',caught.exception.fault.message)
    def test_repeated_instances_count_expanded_occurrences(self):
        # E0=2, En=4+2*E(n-1): E10=6140, E11=12284.
        result=admit({'paint':['g10',None]},nested(10))
        self.assertEqual(result['expandedOccurrences'],6142)
        self.assertEqual(result['distinctNodes'],44)
        with self.assertRaises(SchemaxisError) as caught:
            admit({'paint':['g11',None]},nested(11))
        self.assertEqual(caught.exception.fault.code,'RESOURCE_BUDGET_EXCEEDED')
        self.assertEqual(caught.exception.fault.location,'g11')

    def test_aggregate_roots_and_unique_allocations_are_separate(self):
        self.assertEqual(admit({'a':['g9'],'b':['g9']},nested(9))['expandedOccurrences'],6138)
        with self.assertRaises(SchemaxisError):admit({'a':['g10'],'b':['g10']},nested(10))
        with self.assertRaises(SchemaxisError):admit({'a':[None]*8193},{})
        self.assertEqual(admit({'a':[None]*8192},{})['distinctNodes'],8192)

    def test_depth_limit_applies_to_unused_definitions_too(self):
        groups={'g0':[None]}
        for i in range(1,32):groups['g'+str(i)]=['g'+str(i-1)]
        self.assertEqual(admit({},groups)['groupDepth'],32)
        groups['g32']=['g31']
        with self.assertRaises(SchemaxisError):admit({},groups)

    def test_cycle_and_absent_group_never_become_zero_cost(self):
        for groups in ({'x':['x']},{'x':['y'],'y':['x']},{'x':['absent']}):
            with self.assertRaises(SchemaxisError):admit({'paint':['x']},groups)

    def test_production_expansion_refuses_before_native_submission(self):
        def link(a,port,b,target):return {'from':{'node':a,'socket':port},'to':{'node':b,'socket':target}}
        groups=[]
        for i in range(31):
            if i==0:
                nodes=[{'id':'colour','kind':'emission'},{'id':'out','kind':'output'}]
                links=[link('colour','shader','out','surface')]
            else:
                nodes=[{'id':'left','kind':'group','group':'g'+str(i-1)},
                       {'id':'right','kind':'group','group':'g'+str(i-1)},
                       {'id':'mix','kind':'mixShader'},{'id':'out','kind':'output'}]
                links=[link('left','surface','mix','a'),link('right','surface','mix','b'),link('mix','shader','out','surface')]
            groups.append({'id':'g'+str(i),'family':'material','inputs':[],
                'outputs':[{'id':'surface','kind':'shader'}],'nodes':nodes,'links':links})
        spec={'nodeGroups':groups}
        original=copy.deepcopy(spec)
        with self.assertRaises(SchemaxisError) as caught:validate(spec,{})
        self.assertEqual(caught.exception.fault.code,'RESOURCE_BUDGET_EXCEEDED')
        self.assertEqual(spec,original)
        with patch('schemaxis.adaptors.blender.adaptor.Interpreter') as native:
            with self.assertRaises(SchemaxisError):
                run({'version':'schemaxis.blender.production/1','prepareOnly':True,'production':spec},'never-created')
            native.assert_not_called()


if __name__=='__main__':unittest.main()
