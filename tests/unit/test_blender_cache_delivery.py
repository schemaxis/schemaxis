"""Finite public simulation-cache intent and supplied delivery examples."""
import copy
import json
from pathlib import Path
import sys
import unittest
from schemaxis.adaptors.blender import cache_policy as C
from schemaxis.core.faults import SchemaxisError

ROOT=Path(__file__).resolve().parents[2]


class CacheDelivery(unittest.TestCase):
    def normalize(self,value):
        return C.validate_public(value,kinds={'Sheet':'mesh','Body':'mesh'},rigid_bodies=[{'object':'Body'}],cloth=[{'object':'Sheet'}],frame_start=1,frame_end=10)

    def test_public_intent_excludes_authority_and_binds_full_consumer_timeline(self):
        raw={'id':'fall','kind':'rigidBody','frameStart':1,'frameEnd':10,'storage':'packed'}
        found=self.normalize([raw]);self.assertEqual(found[0]['object'],'');self.assertNotIn('bpy',sys.modules)
        self.assertEqual(C.schema_property()['maxItems'],32)
        for change in ({'constructor':{}},{'sourceFingerprint':'a'*64},{'scene':'guessed-native-name'},{'frameEnd':9},{'storage':'disk'}):
            with self.subTest(change=change),self.assertRaises(SchemaxisError):self.normalize([{**raw,**change}])
        for change in ({'id':'other'},{'id':'fall'}):
            with self.subTest(change=change),self.assertRaises(SchemaxisError):self.normalize([raw,{**raw,**change}])
        cloth={**raw,'id':'cloth','kind':'cloth','object':'Sheet','storage':'disk'}
        self.assertEqual(self.normalize([raw,cloth])[1]['object'],'Sheet')
        with self.assertRaises(SchemaxisError):self.normalize([{**cloth,'object':'Body'}])

    def test_three_supplied_safe_modes_have_literal_distinct_physical_projects(self):
        modes=[]
        for suffix in ('rigid-packed','cloth-packed','cloth-disk'):
            path=ROOT/'examples/schemaxis'/('blender-simulation-cache-'+suffix+'.json')
            doc=json.loads(path.read_text());self.assertEqual(doc['version'],'schemaxis.blender.production/1');self.assertTrue(doc['prepareOnly'])
            production=doc['production'];request=production['simulationCaches'];kinds={o['id']:o['kind']for o in production['objects']}
            records=C.validate_public(request,kinds=kinds,rigid_bodies=production.get('rigidBodies',[]),cloth=production.get('cloth',[]),frame_start=production['frameStart'],frame_end=production['frameEnd'])
            modes.append((records[0]['kind'],records[0]['storage']))
            self.assertEqual(production['simulationFrames'],list(range(1,11)))
            if suffix.startswith('cloth'):
                self.assertEqual(production['cloth'][0]['pinVertices'],[0,2,6,8]);self.assertEqual(len(production['objects'][0]['vertices']),9)
            else:self.assertEqual(production['objects'][0]['location'],[0,0,5]);self.assertEqual(production['rigidBodies'][1]['type'],'passive')
        self.assertEqual(modes,[('rigidBody','packed'),('cloth','packed'),('cloth','disk')])

    def test_literal_oracle_refuses_missing_frames_and_nonfinite_geometry(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('cache_literal_oracle',ROOT/'tools/qualify_blender_caches_native.py')
        helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
        points=[[x,y,2]for y in (-1,0,1)for x in (-1,0,1)];points[4][2]=1.99
        item={'matrix':[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],'vertices':points,
              'faces':[[0,1,4,3],[1,2,5,4],[3,4,7,6],[4,5,8,7]]}
        records={str(i):{'Sheet':copy.deepcopy(item)}for i in range(1,11)}
        helper.literal_geometry(records,'cloth')
        missing=copy.deepcopy(records);missing.pop('7')
        with self.assertRaises(ValueError):helper.literal_geometry(missing,'cloth')
        records['7']['Sheet']['vertices'][0][2]=float('nan')
        with self.assertRaises(ValueError):helper.literal_geometry(records,'cloth')

    def test_public_route_plans_all_three_examples_without_native_import(self):
        from schemaxis.adaptors import registry
        for suffix in ('rigid-packed','cloth-packed','cloth-disk'):
            doc=json.loads((ROOT/'examples/schemaxis'/('blender-simulation-cache-'+suffix+'.json')).read_text())
            # Route semantic planning must understand the field, not just its isolated schema.
            from schemaxis.adaptors.blender.production_job import lower
            lowered=lower(doc)
            self.assertEqual(len(lowered['scenes'][0]['production']['simulationCaches']),1)
        self.assertNotIn('bpy',sys.modules)

if __name__=='__main__':unittest.main()
