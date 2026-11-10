"""Literal oracle and format-preserving attack controls; no native renderer."""
import copy
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('bundle_oracles', Path(__file__).resolve().parents[2]/'tools/blender_bundle_oracles.py')
O = importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(O)
FIXTURES = Path(__file__).resolve().parents[1]/'fixtures/blender-render-bundles'


def exr(path, channels, rows):
    """Tiny independent NONE/FLOAT scanline encoder, arbitrary channel order."""
    def attr(name, kind, data):return name.encode()+b'\0'+kind.encode()+b'\0'+struct.pack('<i',len(data))+data
    width = len(rows[0][0]);height = len(rows)
    declarations = b''.join(n.encode()+b'\0'+struct.pack('<iB3xii',2,0,1,1)for n in channels)+b'\0'
    box = struct.pack('<4i',0,0,width-1,height-1)
    header = struct.pack('<II',20000630,2)+attr('channels','chlist',declarations)+attr('compression','compression',b'\0')+attr('dataWindow','box2i',box)+attr('displayWindow','box2i',box)+attr('pixelAspectRatio','float',struct.pack('<f',1))+attr('lineOrder','lineOrder',b'\0')+b'\0'
    chunks = [struct.pack('<ii',y,4*width*len(channels))+b''.join(struct.pack('<'+'f'*width,*values)for values in row)for y,row in enumerate(rows)]
    offset = len(header)+8*height;offsets=[]
    for chunk in chunks:offsets.append(offset);offset+=len(chunk)
    path.write_bytes(header+struct.pack('<'+'Q'*height,*offsets)+b''.join(chunks))


class BundleOracles(unittest.TestCase):
    def test_invalid_literal_tolerance_or_nan_never_passes(self):
        for expected,tolerance in ((float('nan'),1),(1,float('nan')),(1,-1),(float('inf'),1)):
            with self.subTest(expected=expected,tolerance=tolerance),self.assertRaises(ValueError):O._near(1,expected,tolerance)

    def test_empty_duplicate_and_truncated_expectations_refuse(self):
        # All refuse before opening even an absent EXR, rather than vacuously passing.
        region={'id':'one','pixel':[0,0],'values':{'R':1},'tolerance':1e-6}
        for regions in ([],[region,copy.deepcopy(region)],[{**region,'pixel':[True,0]}],[{**region,'id':''}],[{'id':'empty','pixel':[0,0]}]):
            with self.subTest(regions=regions),self.assertRaises(ValueError):O.verify('absent.exr',{'regions':regions})
        geometry={'positionChannels':['X','Y','Z'],'normalChannels':['NX','NY','NZ'],'worldNormal':[0,0,1],'plane':{'normal':[0,0,1],'offset':0}}
        for target,key,value in (('geometry','normalChannels',['NX']),('geometry','positionChannels',['X','Y']),('geometry','worldNormal',[1]),('camera','origin',[0,float('nan'),1]),('camera','origin',[0,1])):
            expected={'regions':[{'id':'plane','pixel':[0,0],'geometry':copy.deepcopy(geometry)}],'camera':{'origin':[0,0,1]}}
            if target=='geometry':expected['regions'][0]['geometry'][key]=value
            else:expected['camera'][key]=value
            with self.subTest(target=target,key=key),self.assertRaises(ValueError):O.verify('absent.exr',expected)

    def test_top_down_oblique_plane_optical_z_and_world_basis(self):
        camera={'origin':[0,0,5],'right':[1,0,0],'up':[0,1,0],'forward':[0,0,-1],'halfWidth':1,'halfHeight':1}
        plane={'normal':[0,.6,.8],'offset':0}
        top=O.ray_plane(camera,[2,2],[0,0],plane)
        bottom=O.ray_plane(camera,[2,2],[0,1],plane)
        self.assertAlmostEqual(top['opticalZ'],8);[self.assertAlmostEqual(a,b) for a,b in zip(top['position'],[-4,4,-3])]
        self.assertAlmostEqual(bottom['opticalZ'],40/11)
        # World rotated about Z: x/right -> +Y, up -> -X; do not confuse world normal with camera normal.
        turned={**camera,'right':[0,1,0],'up':[-1,0,0]}
        rotated=O.ray_plane(turned,[2,2],[0,0],{'normal':[-.6,0,.8],'offset':0})
        [self.assertAlmostEqual(a,b) for a,b in zip(rotated['position'],[-4,-4,-3])]
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'plane.exr';names=['Z','PX','PY','PZ','NX','NY','NZ']
            exr(path,names,[[[8,8],[-4,4],[4,4],[-3,-3],[0,0],[.6,.6],[.8,.8]],[[40/11]*2,[-20/11,20/11],[-20/11]*2,[15/11]*2,[0,0],[.6,.6],[.8,.8]]])
            expected={'size':[2,2],'camera':camera,'regions':[{'id':'oblique','pixel':[0,0],'geometry':{'plane':plane,'positionChannels':['PX','PY','PZ'],'normalChannels':['NX','NY','NZ'],'worldNormal':[0,.6,.8],'depthChannel':'Z','tolerance':1e-5}}]}
            self.assertTrue(O.verify(path,expected)['verified'])
            mutant=Path(temporary)/'euclidean.exr';O.mutate_none_sample(path,mutant,'Z',[0,0],(96**.5))
            with self.assertRaises(ValueError):O.verify(mutant,expected)
            mutant=Path(temporary)/'off-ray.exr';O.mutate_none_sample(path,mutant,'PX',[0,0],-3)
            with self.assertRaises(ValueError):O.verify(mutant,expected)
            mutant=Path(temporary)/'normal.exr';O.mutate_none_sample(path,mutant,'NY',[0,0],-.6)
            with self.assertRaises(ValueError):O.verify(mutant,expected)

    def test_named_sample_mutation_is_not_tail_and_preserves_all_other_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            a,b=Path(temporary)/'a.exr',Path(temporary)/'b.exr'
            exr(a,['nonPrimary','World','last'],[[[2,3],[4,5],[6,7]],[[8,9],[10,11],[12,13]]])
            receipt=O.mutate_none_sample(a,b,'World',[0,0],99)
            before,after=a.read_bytes(),b.read_bytes();offset=receipt['byteOffset']
            self.assertEqual(before[:offset],after[:offset]);self.assertEqual(before[offset+4:],after[offset+4:]);self.assertLess(offset,len(before)-4)
            self.assertEqual(O.inspect(b,samples=[[0,0]])['samples']['0,0']['World']['value'],99)
            with self.assertRaises(ValueError):O.mutate_none_sample(a,b,'missing',[0,0],1)
            with self.assertRaises(ValueError):O.mutate_none_sample(a,a,'World',[0,0],1)

    def test_nonprimary_world_override_and_linear_light_recombination(self):
        with tempfile.TemporaryDirectory() as temporary:
            p=Path(temporary)/'regions.exr';exr(p,['B','lamp','environment','World','override'],[[[3,5],[1,2],[2,3],[.25,.75],[.9,.1]]])
            expected={'size':[2,1],'regions':[{'id':'secondary-material','pixel':[0,0],'values':{'World':.25,'override':.9},'tolerance':1e-6,'lightSums':[{'policy':'linear-radiance-complete-disjoint-groups','combined':'B','groups':['lamp','environment'],'tolerance':1e-6}]},{'id':'world-override','pixel':[1,0],'values':{'World':.75,'override':.1},'tolerance':1e-6}]}
            self.assertTrue(O.verify(p,expected)['verified'])
            bad=copy.deepcopy(expected);bad['regions'][0]['lightSums'][0]['groups']=['lamp']
            with self.assertRaises(ValueError):O.verify(p,bad)
            bad=copy.deepcopy(expected);bad['regions'][1]['values']['World']=.25
            with self.assertRaises(ValueError):O.verify(p,bad)

    def test_valid_same_size_manifest_membership_attack(self):
        source=FIXTURES/'scientific-crypto-float-zip.exr'
        with tempfile.TemporaryDirectory() as temporary:
            target=Path(temporary)/'manifest.exr'
            O.mutate_manifest_member(source,target,'CryptoObject','panel','hello','248bfa47')
            self.assertEqual(source.stat().st_size,target.stat().st_size)
            facts=O.inspect(target);self.assertEqual(facts['cryptomatte']['CryptoObject']['manifest'],{'object':'055ec73d','hello':'248bfa47'})
            expected={'size':facts['size'],'regions':[{'id':'literal-sample','pixel':[16,8],'values':{'depth.V':3},'tolerance':0}],'manifests':{'CryptoObject':{'object':'055ec73d','panel':'b6f5bb0a'}}}
            with self.assertRaises(ValueError):O.verify(target,expected)

    def test_rank_bits_and_coverage_are_bound_together(self):
        with tempfile.TemporaryDirectory() as temporary:
            p=Path(temporary)/'matte.exr';identifier=struct.unpack('<f',struct.pack('<I',0xb6f5bb0a))[0]
            exr(p,['rank.id','rank.coverage','secondary.id','secondary.coverage'],[[[identifier],[.75],[0],[.25]]])
            expected={'size':[1,1],'regions':[{'id':'two-material-boundary','pixel':[0,0],'matteRanks':[{'idChannel':'rank.id','coverageChannel':'rank.coverage','idBits':'b6f5bb0a','coverage':.75,'tolerance':1e-6}]}]}
            self.assertTrue(O.verify(p,expected)['verified'])
            bad=copy.deepcopy(expected);bad['regions'][0]['matteRanks'][0]['coverageChannel']='secondary.coverage'
            with self.assertRaises(ValueError):O.verify(p,bad)


if __name__=='__main__':unittest.main()
