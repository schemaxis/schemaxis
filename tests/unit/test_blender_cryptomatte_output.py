"""Cryptomatte IDs retain integer bits and canonical embedded source metadata."""
import json
from pathlib import Path
import unittest

from schemaxis.errors import SchemaxisError
from schemaxis.adaptors.blender.cryptomatte_output import name_hash, pixel_bits, layer_identifier, metadata
from schemaxis.adaptors.blender.exr_output import inspect


def attributes(manifest=None, name='CryptoObject'):
    values={'name':name,'hash':'MurmurHash3_32','conversion':'uint32_to_float32',
            'manifest':manifest if manifest is not None else json.dumps({'panel':'b6f5bb0a'})}
    return {'cryptomatte/'+layer_identifier(name)+'/'+k:('string',v.encode('utf-8')) for k,v in values.items()}


class CryptomatteOutput(unittest.TestCase):
    def test_standard_hash_vectors_native_names_and_exponent_repair(self):
        self.assertEqual([name_hash(x) for x in ('','foo','hello','panel','left')],
                         [0,0xf6a5c420,0x248bfa47,0xb6f5bb0a,0xa94a3318])
        self.assertEqual(layer_identifier('CryptoObject'),'3ae39a5')
        self.assertEqual([pixel_bits(x) for x in (0,0x007fffff,0x7f800001,0xff800001,0xb6f5bb0a)],
                         [0x00800000,0x00ffffff,0x7f000001,0xff000001,0xb6f5bb0a])

    def test_actual_native_float_file_has_source_named_manifest_and_id_bits(self):
        path=Path(__file__).resolve().parents[1]/'fixtures/blender-render-bundles/scientific-crypto-float-zip.exr'
        facts=inspect(path,samples=[(16,8)])
        manifest=facts['cryptomatte']['CryptoObject']['manifest']
        self.assertEqual(manifest,{'object':'055ec73d','panel':'b6f5bb0a'})
        sample=facts['samples']['16,8']
        self.assertEqual(sample['CryptoObject00.r']['bits'],pixel_bits(name_hash('panel')).to_bytes(4,'little').hex())
        self.assertEqual(sample['CryptoObject00.g']['value'],1)
        self.assertEqual(sample['depth.V']['value'],3)
        self.assertEqual(sample['normal.Z']['value'],1)
        self.assertEqual(sample['field.V']['value'],.375)

    def test_duplicate_or_coforged_manifest_does_not_become_source_authority(self):
        self.assertEqual(metadata(attributes())['CryptoObject']['manifest'],{'panel':'b6f5bb0a'})
        for text in ('{"panel":"b6f5bb0a","panel":"b6f5bb0a"}',
                     '{"panel":"b6f5bb0b"}', '{"panel":42}', '[]', '['*2000+'0'+']'*2000):
            with self.assertRaises(SchemaxisError):metadata(attributes(text))
        # Missing, unknown and external-manifest fields cannot trigger I/O.
        for field in ('manifest','name','hash','conversion'):
            altered=attributes();altered.pop('cryptomatte/'+layer_identifier('CryptoObject')+'/'+field)
            with self.assertRaises(SchemaxisError):metadata(altered)
        for field in ('manif_file','unknown'):
            altered=attributes();altered['cryptomatte/'+layer_identifier('CryptoObject')+'/'+field]=('string',b'/outside.json')
            with self.assertRaises(SchemaxisError):metadata(altered)

    def test_name_prefix_and_encoding_are_semantic_metadata(self):
        for field,value in [('name','Different'),('hash','SHA256'),('conversion','float64')]:
            altered=attributes();altered['cryptomatte/'+layer_identifier('CryptoObject')+'/'+field]=('string',value.encode())
            with self.assertRaises(SchemaxisError):metadata(altered)


if __name__=='__main__':unittest.main()
