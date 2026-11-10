"""Typed source identity, authoring parity and preallocation resource budgets."""
import copy
import unittest
from schemaxis.adaptors.blender.production_job import lower
from schemaxis.adaptors.blender.node_catalogue import validate_graph,geometry_budget
from schemaxis.core.faults import SchemaxisError


def document():
    return {'version':'schemaxis.blender.production/1','prepareOnly':True,'production':{'objects':[{'id':'source','kind':'mesh','vertices':[[0,0,0],[2,0,0],[0,1,0]],'faces':[[0,1,2]]},{'id':'target','kind':'mesh','vertices':[[0,0,0],[1,0,0],[0,1,0]],'faces':[[0,1,2]]}],'collections':[{'id':'parts'}]}}


def graph(kind='objectInfo',values=None):
    return {'id':'copy','nodes':[{'id':'source','kind':kind,'values':values or {'object':'source'}},{'id':'out','kind':'output'}],'links':[{'from':{'node':'source','socket':'geometry' if kind=='objectInfo' else 'instances'},'to':{'node':'out','socket':'geometry'}}]}


class GeometryResources(unittest.TestCase):
    def refuses(self,doc,code):
        with self.assertRaises(SchemaxisError) as caught:lower(doc)
        self.assertEqual(caught.exception.fault.code,code)

    def test_closed_aliases_resolve_finite_object_collection_and_asset_kinds(self):
        d=document();s=d['production'];s['assets']=[{'id':'cad','file':'/tmp/source.glb','format':'glb'}]
        s['geometryResources']=[{'id':'one','kind':'object','object':'cad','sourceObject':'housing'},{'id':'many','kind':'collection','collection':'parts'},{'id':'whole','kind':'asset','asset':'cad'}]
        p=lower(d)['scenes'][0]['production'];self.assertEqual(p['geometryResources'],s['geometryResources'])

    def test_source_part_alias_cannot_select_arbitrary_rna_or_nonasset(self):
        for change in ({'id':'one','kind':'object','object':'source','sourceObject':'hidden'},{'id':'one','kind':'object','object':'missing'},{'id':'one','kind':'collection','collection':'missing'},{'id':'one','kind':'object','object':'source','rna':'data'}):
            d=document();d['production']['geometryResources']=[change]
            with self.subTest(change=change),self.assertRaises(SchemaxisError):lower(d)

    def test_alias_cannot_shadow_public_identity(self):
        for identity in ('source','parts'):
            d=document();d['production']['geometryResources']=[{'id':identity,'kind':'object','object':'source'}];self.refuses(d,'DUPLICATE_ID')

    def test_object_and_collection_sockets_refuse_wrong_kind(self):
        d=document();s=d['production'];s['geometryResources']=[{'id':'many','kind':'collection','collection':'parts'}];s['geometryGraphs']=[graph(values={'object':'many'})];self.refuses(d,'UNKNOWN_REFERENCE')

    def test_modifier_source_selector_is_asset_only(self):
        d=document();s=d['production'];s['geometryGraphs']=[graph()];s['geometryBindings']=[{'object':'target','graph':'copy','sourceObject':'part'}];self.refuses(d,'INVALID_GEOMETRY_RESOURCE')

    def test_resource_vertices_are_not_zero_cost(self):
        g=validate_graph(graph(),'geometry','$.graph')
        self.assertEqual(geometry_budget(g,3,resource_counts={('object','source'):97})['out'],97)
        with self.assertRaises(SchemaxisError) as caught:geometry_budget(g,3,resource_counts={('object','source'):2_000_001})
        self.assertEqual(caught.exception.fault.code,'RESOURCE_BUDGET_EXCEEDED')

    def test_instance_expansion_includes_resource_geometry(self):
        g=graph();g['nodes'].insert(1,{'id':'points','kind':'grid','values':{'xVertices':100,'yVertices':100}});g['nodes'].insert(2,{'id':'copies','kind':'instanceOnPoints'});g['links']=[{'from':{'node':'points','socket':'geometry'},'to':{'node':'copies','socket':'points'}},{'from':{'node':'source','socket':'geometry'},'to':{'node':'copies','socket':'instance'}},{'from':{'node':'copies','socket':'instances'},'to':{'node':'out','socket':'geometry'}}]
        p=validate_graph(g,'geometry','$.graph')
        with self.assertRaises(SchemaxisError) as caught:geometry_budget(p,3,resource_counts={('object','source'):1000})
        self.assertEqual(caught.exception.fault.code,'RESOURCE_BUDGET_EXCEEDED')

    def test_resampling_bounds_every_input_curve_not_only_one(self):
        g={'id':'many','nodes':[{'id':'in','kind':'input'},{'id':'sample','kind':'resampleCurve','values':{'count':4096}},{'id':'out','kind':'output'}],'links':[{'from':{'node':'in','socket':'geometry'},'to':{'node':'sample','socket':'curve'}},{'from':{'node':'sample','socket':'curve'},'to':{'node':'out','socket':'geometry'}}]}
        p=validate_graph(g,'geometry','$.graph')
        with self.assertRaises(SchemaxisError) as caught:geometry_budget(p,1000)
        self.assertEqual(caught.exception.fault.code,'RESOURCE_BUDGET_EXCEEDED')
