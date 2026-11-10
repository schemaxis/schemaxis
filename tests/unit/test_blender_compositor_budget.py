"""Repeated compositor instances must not evade allocation/expansion admission."""
import unittest
from schemaxis.errors import SchemaxisError
from schemaxis.adaptors.blender.compositor_budget import validate,NativeBudget


class Tree:
    bl_idname='CompositorNodeTree'
    def __init__(self,name,nodes):self.name=name;self.nodes=nodes;self.links=[]


class Node:
    def __init__(self,child=None):
        self.node_tree=child;self.bl_idname='CompositorNodeGroup' if child is not None else 'CompositorNodeExposure'


class CompositorCost(unittest.TestCase):
    def test_small_reused_group_and_generated_pass_outputs(self):
        spec={'nodeGroups':[{'id':'grade','family':'compositor','nodes':[{'kind':'input'},{'kind':'exposure'},{'kind':'output'}]}],
              'compositor':{'nodes':[{'kind':'group','group':'grade'},{'kind':'group','group':'grade'},{'kind':'output'}]},
              'viewLayers':[{'id':'beauty'},{'id':'utility'}],
              'renderBundles':[{'outputs':[{'kind':'image'}]}]}
        self.assertEqual(validate(spec),{'distinctNodes':9,'expandedOccurrences':12,'groupDepth':1})

    def test_billion_leaf_graph_refuses_without_native_construction(self):
        groups=[{'id':'G0','family':'compositor','nodes':[{'kind':'exposure'}]}]
        for i in range(1,31):groups.append({'id':'G'+str(i),'family':'compositor','nodes':[{'kind':'group','group':'G'+str(i-1)}]*2})
        spec={'nodeGroups':groups,'compositor':{'nodes':[{'kind':'group','group':'G30'}]}}
        with self.assertRaises(SchemaxisError) as caught:validate(spec)
        self.assertEqual(caught.exception.fault.code,'RESOURCE_BUDGET_EXCEEDED')
        self.assertIn('compositor expansion',caught.exception.fault.message)

    def test_unreferenced_group_still_cannot_retain_an_expansion_bomb(self):
        groups=[{'id':'base','family':'compositor','nodes':[{'kind':'exposure'}]*256}]
        groups.append({'id':'large','family':'compositor','nodes':[{'kind':'group','group':'base'}]*64})
        with self.assertRaises(SchemaxisError):validate({'nodeGroups':groups})

    def test_generated_output_input_links_are_bounded_before_allocation(self):
        spec={'viewLayers':[{'id':'beauty'}],
              'renderBundles':[{'outputs':[{'kind':'multilayer','layers':[{}]*64}]*64}]*3}
        with self.assertRaises(SchemaxisError) as caught:validate(spec)
        self.assertEqual(caught.exception.fault.code,'RESOURCE_BUDGET_EXCEEDED')
        self.assertEqual(caught.exception.fault.observed['estimatedLinks'],12288)

    def test_native_identity_sharing_and_colliding_display_names(self):
        left=Tree('same',[Node()]);right=Tree('same',[Node(),Node()]);root=Tree('scene',[Node(left),Node(right)])
        self.assertEqual(NativeBudget().observe(root),{'distinctNodes':5,'expandedOccurrences':5,'groupDepth':1})
        shared=Tree('scene',[Node(left),Node(left)])
        self.assertEqual(NativeBudget().observe(shared),{'distinctNodes':3,'expandedOccurrences':4,'groupDepth':1})

    def test_native_nested_group_expansion_refuses_and_small_control_passes(self):
        child=Tree('leaf',[Node()])
        small=Tree('small',[Node(child),Node(child)])
        NativeBudget().observe(small)
        for i in range(20):child=Tree('G'+str(i),[Node(child),Node(child)])
        with self.assertRaises(SchemaxisError) as caught:NativeBudget().observe(child)
        self.assertEqual(caught.exception.fault.code,'RESOURCE_BUDGET_EXCEEDED')
        self.assertIn('compositor expansion',caught.exception.fault.message)


if __name__=='__main__':unittest.main()
