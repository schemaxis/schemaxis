"""Typed reusable node groups preserve domains, ordering and bounded topology."""
import copy
import unittest
from schemaxis.errors import SchemaxisError
from schemaxis.adaptors.blender.node_groups import validate_groups
from schemaxis.adaptors.blender.node_catalogue import validate_graph,geometry_budget
from schemaxis.adaptors.blender.production import validate,schema
try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator=None


def group():return {'id':'lift','family':'geometry','inputs':[{'id':'shape','kind':'geometry'},{'id':'offset','kind':'vector','default':[0,0,2]}],'outputs':[{'id':'shape','kind':'geometry'}], 'nodes':[{'id':'input','kind':'input'},{'id':'move','kind':'transform'},{'id':'output','kind':'output'}],'links':[{'from':{'node':'input','socket':'shape'},'to':{'node':'move','socket':'geometry'}},{'from':{'node':'input','socket':'offset'},'to':{'node':'move','socket':'translation'}},{'from':{'node':'move','socket':'geometry'},'to':{'node':'output','socket':'shape'}}]}


class NodeGroupContracts(unittest.TestCase):
    def test_normalized_immutable_idempotent_hostsafe(self):
        d={'nodeGroups':[group()]};before=copy.deepcopy(d);r=validate(d,{})
        self.assertEqual(d,before);self.assertEqual(validate(r,{}),r);schema()
    @unittest.skipIf(Draft202012Validator is None,'optional schema developer package unavailable')
    def test_complete_example_authored_and_normalized_schema(self):
        import json
        from pathlib import Path
        d=json.loads((Path(__file__).resolve().parents[2]/'examples/schemaxis/blender-node-groups.json').read_text())['production']
        validator=Draft202012Validator(schema())
        self.assertEqual(list(validator.iter_errors(d)),[])
        self.assertEqual(list(validator.iter_errors(validate(d,{}))),[])
    def test_named_group_values_reject_unknown_paths(self):
        groups={g['id']:g for g in validate_groups([group()],'groups')}
        d={'id':'scene','nodes':[{'id':'in','kind':'input'},{'id':'g','kind':'group','group':'lift','values':{'offset':[0,0,3]}},{'id':'out','kind':'output'}],'links':[{'from':{'node':'in','socket':'geometry'},'to':{'node':'g','socket':'shape'}},{'from':{'node':'g','socket':'shape'},'to':{'node':'out','socket':'geometry'}}]}
        r=validate_graph(d,'geometry','g',groups);self.assertEqual(next(n for n in r['nodes'] if n['id']=='g')['values'],{'offset':[0,0,3]})
        for patch in ({'values':{'native.path':2}},{'group':'absent'},{'values':{'offset':'not a vector'}}):
            bad=copy.deepcopy(d);next(n for n in bad['nodes'] if n['id']=='g').update(patch)
            with self.subTest(patch=patch),self.assertRaises(SchemaxisError):validate_graph(bad,'geometry','g',groups)
    def test_link_only_group_inputs_cannot_hide_native_literal_defaults(self):
        groups={g['id']:g for g in validate_groups([group()],'groups')}
        d={'id':'outer','nodes':[{'id':'g','kind':'group','group':'lift'},{'id':'out','kind':'output'}],'links':[{'from':{'node':'g','socket':'shape'},'to':{'node':'out','socket':'geometry'}}]}
        with self.assertRaises(SchemaxisError):validate_graph(d,'geometry','outer',groups)
    def test_recursive_and_cross_domain_references_fail(self):
        d=group();d['nodes'].append({'id':'self','kind':'group','group':'lift'})
        with self.assertRaises(SchemaxisError):validate_groups([d],'groups')
        groups={g['id']:g for g in validate_groups([group()],'groups')}
        d={'id':'paint','nodes':[{'id':'g','kind':'group','group':'lift'},{'id':'out','kind':'output'}],'links':[]}
        with self.assertRaises(SchemaxisError):validate_graph(d,'material','paint',groups)
    def test_domain_types_bounds_and_names_are_finite(self):
        for patch in ({'kind':'shader'},{'kind':'arbitraryRNA'},{'id':'shape'},{'default':[1,2]},{'minimum':1}):
            d=group();d['inputs'][1].update(patch)
            with self.subTest(patch=patch),self.assertRaises(SchemaxisError):validate_groups([d],'groups')
    def test_geometry_expansion_inside_nested_groups_is_bounded(self):
        d=group();d['nodes'][1]={'id':'move','kind':'subdivide','values':{'level':4}};d['links']=[{'from':{'node':'input','socket':'shape'},'to':{'node':'move','socket':'mesh'}},{'from':{'node':'move','socket':'mesh'},'to':{'node':'output','socket':'shape'}}]
        groups={g['id']:g for g in validate_groups([d],'groups')}
        graph=validate_graph({'id':'outer','nodes':[{'id':'in','kind':'input'},{'id':'g','kind':'group','group':'lift'},{'id':'out','kind':'output'}],'links':[{'from':{'node':'in','socket':'geometry'},'to':{'node':'g','socket':'shape'}},{'from':{'node':'g','socket':'shape'},'to':{'node':'out','socket':'geometry'}}]},'geometry','outer',groups)
        with self.assertRaises(SchemaxisError):geometry_budget(graph,2000,groups=groups)
    def test_group_interface_cannot_drive_unbounded_topology_counts(self):
        d=group();d['inputs']=[{'id':'count','kind':'integer','default':3}];d['nodes'][1]={'id':'move','kind':'grid'};d['links']=[{'from':{'node':'input','socket':'count'},'to':{'node':'move','socket':'xVertices'}},{'from':{'node':'move','socket':'geometry'},'to':{'node':'output','socket':'shape'}}]
        with self.assertRaises(SchemaxisError):validate_groups([d],'groups')
    def test_named_resource_defaults_are_validated_before_execution(self):
        d=group();d['inputs'].append({'id':'model','kind':'object','default':'missing'})
        with self.assertRaises(SchemaxisError):validate({'nodeGroups':[d]}, {})

if __name__=='__main__':unittest.main()
