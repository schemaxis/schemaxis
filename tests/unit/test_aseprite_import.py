"""Captured artwork contract, independent sample expectations and hostile inputs."""
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from schemaxis.adaptors.aseprite import plan, run, verify, schema
from schemaxis.adaptors.aseprite.adaptor import expected
from schemaxis.adaptors.aseprite.inputs import capture, inspect, source_bytes
from schemaxis.adaptors.aseprite.integration import reusableInputs
from schemaxis.adaptors.aseprite.png import decode
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT/'examples/schemaxis/fixtures/aseprite'


def document(label='import'):
    result = json.loads((ROOT/f'examples/schemaxis/aseprite-{label}.json').read_text())
    for n in result['nodes']:
        if n['filter'] == 'importImage':
            n['options']['source'] = str(FIXTURES/Path(n['options']['source']).name)
    return result


def chunk(kind, payload):
    return struct.pack('>I', len(payload))+kind+payload+struct.pack('>I', zlib.crc32(kind+payload)&0xffffffff)


def image(raw, mode=6, depth=8, interlace=0, extra=b'', width=1, height=1):
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB',width,height,depth,mode,0,0,interlace))
            +extra+chunk(b'IDAT', zlib.compress(raw))+chunk(b'IEND',b''))


class ImportTests(unittest.TestCase):
    def assert_fault(self, code, fn, *args, **kwargs):
        with self.assertRaises(SchemaxisError) as caught: fn(*args, **kwargs)
        self.assertEqual(caught.exception.fault.code, code)
        self.assertTrue(caught.exception.fault.location)

    def test_plan_defaults_schema_and_purity(self):
        d=document(); before=copy.deepcopy(d); p=plan(d)
        self.assertEqual(before,d)
        self.assertEqual(p,plan(d))
        self.assertEqual(p['nodes'][4]['options']['frame'],1)
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            Draft202012Validator = None
        if Draft202012Validator: Draft202012Validator(schema()).validate(d)
        self.assert_fault('INVALID_DRAW',plan,document('import-clipping-invalid'))
        for key,value in [('source','relative.png'),('source','/tmp/bad\0.png'),('source','/tmp/a.jpg'),
                          ('x',True),('height',0),('frame',2),('layer','missing')]:
            bad=copy.deepcopy(d);bad['nodes'][4]['options'][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(SchemaxisError):plan(bad)
        bad=copy.deepcopy(d);bad['nodes'][4]['options']['script']='arbitrary()'
        self.assert_fault('UNKNOWN_ARGUMENT',plan,bad)

    def test_decode_literal_samples_and_hidden_rgb(self):
        result=decode((FIXTURES/'badge.png').read_bytes())
        self.assertEqual((result['width'],result['height']),(3,2))
        self.assertEqual(result['pixels'],'ff0000ff0000000000ff00ff0000ffffffff00ff00000000')
        original=(FIXTURES/'badge.png').read_bytes()
        self.assertEqual(original,(FIXTURES/'badge.png').read_bytes())

    def test_all_png_row_filters(self):
        rows=[bytes([10,20,30,255,80,90,100,255]),bytes([40,60,80,255,160,180,200,255])]
        target=b''.join(rows).hex()
        for method in range(5):
            encoded=bytearray();previous=bytes(8)
            for row in rows:
                encoded.append(method)
                for i,value in enumerate(row):
                    a=row[i-4] if i>=4 else 0;b=previous[i];c=previous[i-4] if i>=4 else 0
                    q=a+b-c; ds=[abs(q-a),abs(q-b),abs(q-c)]
                    predictor=[0,a,b,(a+b)//2,[a,b,c][ds.index(min(ds))]][method]
                    encoded.append((value-predictor)&255)
                previous=row
            self.assertEqual(decode(image(bytes(encoded),width=2,height=2))['pixels'],target)

    def test_png_loss_and_hostile_payloads_rejected(self):
        rgba=b'\0\x01\x02\x03\xff'
        for data in [image(rgba,mode=2),image(rgba,mode=0),image(rgba,depth=16),image(rgba,interlace=1),
                     image(b'\0\x01\x02\x03\x80'),image(rgba,extra=chunk(b'sRGB',b'\0')),
                     image(rgba,extra=chunk(b'acTL',struct.pack('>II',1,0))),
                     image(rgba,extra=chunk(b'iCCP',b'profile')),image(rgba)+b'x',image(rgba)[:-1],
                     image(b'\5\x01\x02\x03\xff'),image(b'\0'+b'\0'*1000000),image(rgba,width=257),
                     image(rgba)[:20]+b'bad'+image(rgba)[23:]]:
            with self.subTest(length=len(data)):
                self.assert_fault('UNSUPPORTED_IMAGE',decode,data)
        rgb=image(b'\0\x01\x02\x03',mode=2)
        self.assertEqual(decode(rgb,source=False)['pixels'],'010203ff')

    def test_replacement_and_layer_compositing_literal_expectations(self):
        p=plan(document());sources,_=inspect(p);native,preview,sheet,meta=expected(p,sources)
        self.assertEqual(native['durationsMS'],[80,160])
        def pixel(r,w,x,y):return bytes.fromhex(r)[(y*w+x)*4:(y*w+x+1)*4]
        # Transparent input erased earlier white in art cel, lower blue remains visible.
        self.assertEqual(pixel(native['cels'][1][0],6,2,1),bytes(4))
        self.assertEqual(pixel(preview['pixels'],6,2,1),bytes([20,40,80,255]))
        self.assertEqual(pixel(preview['pixels'],6,1,1),bytes([255,0,0,255]))
        self.assertEqual(pixel(preview['pixels'],6,2,2),bytes([255,255,0,255]))
        # Second frame has no copied lower background, but retains later procedural highlight.
        self.assertEqual(pixel(sheet['pixels'],12,9,0),bytes(4))
        self.assertEqual(pixel(sheet['pixels'],12,11,3),bytes([255]*4))
        self.assertEqual(meta['frames'][1],{'x':6,'y':0,'width':6,'height':4,'durationMS':160})
        v=plan(document('import-variant')); vs,_=inspect(v)
        self.assertNotEqual(preview,expected(v,vs)[1])
        self.assertEqual(expected(v,vs)[0]['durationsMS'],[80,240])

    def test_overlapping_import_replaces_same_cel_and_preserves_outside(self):
        d=document();d['nodes'][5:]=[]
        d['nodes'].append({'id':'overlap','filter':'importImage','inputs':{'sprite':'import'},
            'options':{'source':str(FIXTURES/'badge-variant.png'),'width':3,'height':2,'x':2,'y':1,'layer':'art'}})
        d['output']='overlap';p=plan(d);sources,_=inspect(p)
        c=bytes.fromhex(expected(p,sources)[0]['cels'][1][0])
        self.assertEqual(c[(1*6+1)*4:(1*6+2)*4],bytes([255,0,0,255]))
        self.assertEqual(c[(1*6+2)*4:(1*6+3)*4],bytes([255,0,255,255]))
        self.assertEqual(c[(2*6+2)*4:(2*6+3)*4],bytes(4))

    def test_capture_retains_exact_bytes_and_reuse_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);source=base/'source.png';source.write_bytes((FIXTURES/'badge.png').read_bytes())
            d=document()
            for n in d['nodes']:
                if n['filter']=='importImage':n['options']['source']=str(source)
            p=plan(d);before=reusableInputs(d);out=base/'capture';out.mkdir()
            captured,manifest=capture(p,out)
            self.assertEqual((out/manifest[0]['retained']).read_bytes(),source.read_bytes())
            source.write_bytes((FIXTURES/'badge-variant.png').read_bytes())
            self.assertNotEqual(before,reusableInputs(d));source.unlink()
            self.assertEqual(captured,inspect(p,out)[0])
            self.assertEqual(reusableInputs(d),None)
            (out/manifest[0]['retained']).unlink()
            self.assert_fault('INVALID_RESOURCE',inspect,p,out)

    def test_dimensions_symlink_fifo_and_prelaunch_rejection(self):
        d=document();d['nodes'][4]['options']['width']=2
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with patch('schemaxis.adaptors.aseprite.adaptor.SubprocessRunner') as runner:
                self.assert_fault('IMAGE_DIMENSIONS',run,d,root/'bad','/bin/true')
                runner.assert_not_called()
            self.assertEqual(json.loads((root/'bad/result.json').read_text())['fault']['code'],'IMAGE_DIMENSIONS')
            symlink=root/'linked.png';symlink.symlink_to(FIXTURES/'badge.png')
            self.assert_fault('INVALID_RESOURCE',source_bytes,symlink)
            fifo=root/'pipe.png';os.mkfifo(fifo)
            self.assert_fault('INVALID_RESOURCE',source_bytes,fifo)
            self.assert_fault('INVALID_RESOURCE',source_bytes,root)

    def test_discovery_guidance_and_studio(self):
        from schemaxis.capabilities import CapabilityCatalogue
        from schemaxis.search_acceptance import check_cases
        checks=check_cases(CapabilityCatalogue(),'aseprite')
        self.assertTrue(checks['complete'],checks)
        from schemaxis.studio_library import load_library
        library=load_library('aseprite')
        snippet=next(s for s in library['snippets'] if s['id']=='import-png')
        from schemaxis.studio_library import instantiate_item
        starter=instantiate_item(library,snippet,provider='aseprite')
        self.assertEqual(plan(starter)['nodes'][-1]['filter'],'importImage')

    def legacy_evidence(self, base):
        """Synthetic old receipt; binary is a host fixture, never native proof."""
        from schemaxis.adaptors.aseprite.adaptor import artifact_manifest, digest, FILES
        from schemaxis.adaptors.aseprite.native_source import LEGACY_PROCEDURAL_WORKER_SHA256
        from schemaxis.artifacts import atomic_json
        d=document('icon');p=plan(d);native,preview,sheet,metadata=expected(p)
        base.mkdir()
        atomic_json(base/'authored.json',d);atomic_json(base/'plan.json',p)
        (base/'worker.lua').write_bytes((FIXTURES/'legacy-procedural-worker.lua').read_bytes())
        self.assertEqual(digest(base/'worker.lua'),LEGACY_PROCEDURAL_WORKER_SHA256)
        (base/'sprite.aseprite').write_bytes(b'HOST FIXTURE, NOT NATIVE QUALIFICATION')
        for filename,raster in [('preview.png',preview),('sheet.png',sheet)]:
            raw=bytes.fromhex(raster['pixels']);stride=raster['width']*4
            rows=b''.join(b'\0'+raw[y*stride:(y+1)*stride] for y in range(raster['height']))
            (base/filename).write_bytes(image(rows,width=raster['width'],height=raster['height']))
        atomic_json(base/'sheet.json',metadata)
        atomic_json(base/'verification.json',{'freshProcess':True,'runtime':'historical-host-fixture',
            'native':native,'preview':preview,'sheet':sheet,'artifacts':artifact_manifest(base)})
        result={'status':'succeeded','verified':True,'sha256':{
            f:digest(base/f) for f in (*FILES,'verification.json','worker.lua')}}
        atomic_json(base/'result.json',result)
        from schemaxis.publication_metadata import finalise
        finalise(base)
        return result

    def test_pre_capture_procedural_receipt_remains_readable(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)/'legacy';self.legacy_evidence(base)
            self.assertTrue(verify(base)['verified'])
            self.assertFalse((base/'input-manifest.json').exists())

    def test_legacy_compatibility_never_waives_current_capture_contract(self):
        from schemaxis.adaptors.aseprite.native_source import WORKER
        from schemaxis.adaptors.aseprite.adaptor import digest
        from schemaxis.artifacts import atomic_json
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)/'legacy';result=self.legacy_evidence(base)
            (base/'input-manifest.json').write_text('{malformed')
            self.assert_fault('VERIFICATION_FAILED',verify,base)
            (base/'input-manifest.json').unlink()
            (base/'worker.lua').write_text(WORKER)
            result['sha256']['worker.lua']=digest(base/'worker.lua');atomic_json(base/'result.json',result)
            self.assert_fault('VERIFICATION_FAILED',verify,base)
            # A known old worker also cannot downgrade an import document.
            (base/'worker.lua').write_bytes((FIXTURES/'legacy-procedural-worker.lua').read_bytes())
            d=document();atomic_json(base/'authored.json',d);atomic_json(base/'plan.json',plan(d))
            self.assert_fault('INVALID_RESOURCE',verify,base)

    def test_altered_old_worker_rejected_even_with_coherent_hash(self):
        from schemaxis.adaptors.aseprite.adaptor import digest
        from schemaxis.artifacts import atomic_json
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)/'legacy';result=self.legacy_evidence(base)
            with (base/'worker.lua').open('a') as stream:stream.write('\n-- changed trusted source')
            result['sha256']['worker.lua']=digest(base/'worker.lua');atomic_json(base/'result.json',result)
            self.assert_fault('VERIFICATION_FAILED',verify,base)

    @unittest.skipUnless(os.environ.get('ASEPRITE_EXE'),'set ASEPRITE_EXE for native acceptance')
    def test_native_import_variant_and_legacy(self):
        with tempfile.TemporaryDirectory() as temp:
            for label in ['import','import-variant','icon']:
                d=document(label)
                target=Path(temp)/label
                self.assertTrue(run(d,target,os.environ['ASEPRITE_EXE'])['verified'])
                self.assertTrue(verify(target)['verified'])
