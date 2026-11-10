"""Cache manifests cannot substitute for fresh intent and physical byte closure."""
import copy
import importlib.util
import sys
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
import unittest
from pathlib import Path
from schemaxis.adaptors.blender import cache_policy as C
from schemaxis.core.faults import SchemaxisError


def constructor():return {'version':'schemaxis.blender.cache-constructor/1','intent':{'gravity':[0,0,-9.81],'mass':1},'dependencies':[{'id':'mesh','sha256':'a'*64,'bytes':32}],'runtime':{'version':[5,2,3],'build':'e13b728c6880'}}
def request():return {'id':'fall','kind':'rigidBody','object':'','scene':'CacheScene','frameStart':1,'frameEnd':12,'storage':'packed'}


class CachePolicy(unittest.TestCase):
    def test_fingerprint_binds_parameter_dependency_and_runtime(self):
        base=C.plan(request(),constructor());self.assertEqual(C.validate(base),base)
        with self.assertRaises(SchemaxisError):C.validate({'version':C.VERSION})
        changed=constructor();changed['intent']['mass']=2
        self.assertNotEqual(C.plan(request(),changed)['sourceFingerprint'],base['sourceFingerprint'])
        changed=constructor();changed['dependencies'][0]['sha256']='b'*64
        self.assertNotEqual(C.plan(request(),changed)['sourceFingerprint'],base['sourceFingerprint'])
        forged=copy.deepcopy(base);forged['constructor']['intent']['mass']=2
        with self.assertRaises(SchemaxisError):C.validate(forged)
        changed=constructor();changed['runtime']['build']='unknown'
        with self.assertRaises(SchemaxisError):C.plan(request(),changed)

    def test_owners_storage_ranges_and_unknown_families_refuse(self):
        for key,value in [('frameStart',True),('frameEnd',1002),('storage','external'),('kind','fluid'),('object','Cube'),('id','../escape')]:
            bad=request();bad[key]=value
            with self.subTest(key=key),self.assertRaises(SchemaxisError):C.plan(bad,constructor())
        with self.assertRaises(SchemaxisError):C.plan({**request(),'storage':'disk'},constructor())
        cloth={**request(),'kind':'cloth','object':'Sheet','storage':'disk'}
        self.assertEqual(C.plan(cloth,constructor())['nativeType'],'CLOTH')
        bad=constructor();bad['dependencies']*=2
        with self.assertRaises(SchemaxisError):C.plan(request(),bad)

    def test_actual_cache_inventory_vs_fresh_bytes_not_mutable_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);a=root/'submitted';b=root/'fresh';a.mkdir();b.mkdir()
            for p in (a,b):(p/'fall_000001_00.bphys').write_bytes(b'BPHYSICS\0original')
            self.assertTrue(C.verify_files(a,b,storage='disk'))
            for content in (b'BPHYSICS\0modified',b''):
                (a/'fall_000001_00.bphys').write_bytes(content)
                with self.assertRaises(SchemaxisError):C.verify_files(a,b,storage='disk')
            (a/'fall_000001_00.bphys').unlink()
            with self.assertRaises(SchemaxisError):C.verify_files(a,b,storage='disk')
            (a/'fall_000001_00.bphys').symlink_to(b/'fall_000001_00.bphys')
            with self.assertRaises(SchemaxisError):C.verify_files(a,b,storage='disk')

    def test_complete_indexed_geometry_membership_and_order_are_required(self):
        # Native observation comparison is pure Python; bpy is not executed here.
        path=Path(__file__).resolve().parents[2]/'src/schemaxis/adaptors/blender/cache_fidelity_native.py'
        spec=importlib.util.spec_from_file_location('schemaxis.adaptors.blender._cache_fidelity_test',path)
        module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'bpy':SimpleNamespace()}):spec.loader.exec_module(module)
        reference={'1':{'Sheet':{'vertices':[[0.,0.,1.],[1.,0.,1.]],'faces':[[0,1]]}},'4':{'Sheet':{'vertices':[[0.,0.,.9],[1.,0.,1.]],'faces':[[0,1]]}}}
        module.compare(copy.deepcopy(reference),reference)
        for kind in ('frame','vertex','topology','nonfinite'):
            changed=copy.deepcopy(reference)
            if kind=='frame':changed.pop('4')
            elif kind=='vertex':changed['4']['Sheet']['vertices'].reverse()
            elif kind=='topology':changed['4']['Sheet']['faces']=[[1,0]]
            else:changed['4']['Sheet']['vertices'][0][2]=float('nan')
            with self.subTest(kind=kind),self.assertRaises(SchemaxisError):module.compare(changed,reference)

    def test_only_common_verified_exact_payload_companions_are_excluded(self):
        import json
        from schemaxis.publication_metadata import finalise
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);folder=root/'blendcache_0000';folder.mkdir()
            payload=folder/'physics_000001_00.bphys';payload.write_bytes(b'native solver bytes')
            artifacts=[{'kind':'simulationCache','file':str(payload)}]
            (root/'verification.json').write_text(json.dumps({'artifacts':artifacts}))
            expected=C.inventory(folder);finalise(root)
            with self.assertRaises(SchemaxisError):C.inventory(folder)
            self.assertEqual(C.inventory(folder,publication_directory=root),expected)
            orphan=folder/'unknown.bphys.metadata.json';orphan.write_text('{}')
            with self.assertRaises(SchemaxisError):C.inventory(folder,publication_directory=root)
            orphan.unlink();companion=payload.with_name(payload.name+'.metadata.json')
            companion.write_text('{}')
            with self.assertRaises(SchemaxisError):C.inventory(folder,publication_directory=root)

    def test_packed_owns_no_external_payload_and_dependency_bytes_are_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            a=Path(directory)/'a';b=Path(directory)/'b';a.mkdir();b.mkdir()
            self.assertEqual(C.verify_files(a,b,storage='packed'),{})
            with self.assertRaises(SchemaxisError):C.verify_files(a,b,storage='disk')
        bad=constructor();bad['dependencies'][0]['bytes']=C.MAX_BYTES+1
        with self.assertRaises(SchemaxisError):C.plan(request(),bad)

if __name__=='__main__':unittest.main()
