# Copyright (C) 2026 David L F Gaden
"""PNG byte/mode boundaries and exact raster semantics, with literal expectations."""
import copy
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

from schemaxis.adaptors import registry
from schemaxis.adaptors.imagemagick import adaptor,png
from schemaxis.core.faults import SchemaxisError

ROOT=Path(__file__).resolve().parents[2]


def chunk(kind,value):return struct.pack('>I',len(value))+kind+value+struct.pack('>I',zlib.crc32(kind+value)&0xffffffff)


def image(raw,width=2,height=5,depth=8,colour=6,interlace=0,extra=b''):
    return png.SIGNATURE+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,depth,colour,0,0,interlace))+extra+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')


class ImageMagickContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pending=ROOT/'src/schemaxis/adaptors/imagemagick/adaptor.json.pending'
        cls.registration=patch.dict(registry.ADAPTORS,{'imagemagick':json.loads(pending.read_text())} if pending.exists() else {})
        cls.registration.start()

    @classmethod
    def tearDownClass(cls):cls.registration.stop()

    def document(self,name='baseline'):
        return json.loads((ROOT/f'examples/schemaxis/imagemagick-{name}.json').read_text())

    def fault(self,action,code):
        with self.assertRaises(SchemaxisError) as caught:action()
        self.assertEqual(caught.exception.fault.code,code,caught.exception.fault.to_dict());return caught.exception.fault

    def test_host_contract_guidance_and_curated_search(self):
        from schemaxis.adaptor_conformance import host
        from schemaxis.capabilities import CapabilityCatalogue
        from schemaxis.search_acceptance import check_cases
        from schemaxis.studio_guidance import audit
        self.assertTrue(host(adaptor.VERSION)['verified'])
        self.assertTrue(audit('imagemagick')['complete'])
        self.assertTrue(check_cases(CapabilityCatalogue(providers=['imagemagick']),'imagemagick')['complete'])

    def test_immutable_defaults_and_closed_intent(self):
        d=self.document();before=copy.deepcopy(d);p=adaptor.plan(d)
        self.assertEqual(before,d);self.assertEqual(p,adaptor.plan(d));self.assertEqual(p['background'],[255,255,255])
        self.assertEqual(adaptor.query(d)[0],['raster'])
        for key in ['command','format','script','options']:
            bad=copy.deepcopy(d);bad[key]='anything';self.fault(lambda:adaptor.plan(bad),'UNKNOWN_ARGUMENT')
        for source in ['relative.png','https://example.org/image.png','SVG:/tmp/file.svg','/tmp/image.jpg']:
            bad=copy.deepcopy(d);bad['images'][0]['source']=source
            self.assertEqual(self.fault(lambda:adaptor.plan(bad),'INVALID_RASTER_SOURCE').location,'$.images[0].source')
        d=self.document('invalid-id');self.assertEqual(self.fault(lambda:adaptor.plan(d),'INVALID_RASTER_ID').location,'$.images[0].id')
        d=self.document();d['images']*=2;self.fault(lambda:adaptor.plan(d),'INVALID_RASTER_ID')
        d=self.document();d['sheet']={};self.fault(lambda:adaptor.plan(d),'INVALID_RASTER_SHEET')
        d=self.document();d['background']=[0,0,0];self.fault(lambda:adaptor.plan(d),'INVALID_RASTER_ALPHA')

    def test_all_five_png_filters_and_rgb_alpha(self):
        raw=b'\x00'+bytes([10,20,30,40])*2+b'\x01'+bytes([10,20,30,40,0,0,0,0])+b'\x02'+bytes(8)+b'\x03'+bytes([5,10,15,20,0,0,0,0])+b'\x04'+bytes(8)
        w,h,pixels,colour=png.decode(image(raw));self.assertEqual((w,h),(2,5));self.assertEqual(pixels,bytes([10,20,30,40])*10)
        self.assertEqual(png.decode(image(b'\0\x10\x20\x30',width=1,height=1,colour=2))[2],bytes([16,32,48,255]))
        self.fault(lambda:png.decode(image(b'\0\x10\x20\x30',width=1,height=1,colour=2),output=True),'VERIFICATION_FAILED')
        tagged=image(b'\0'+bytes(8),height=1,extra=chunk(b'sRGB',b'\0'))
        self.fault(lambda:png.decode(tagged,output=True),'VERIFICATION_FAILED')

    def test_png_malformed_metadata_and_decompression_boundaries(self):
        good=image(b'\0'+bytes(8),height=1)
        for bad in [good[:-1],good+b'x',good.replace(b'IDAT',b'JUNK'),good[:-12],good[:-12]+chunk(b'IDAT',b'x')+good[-12:],image(b'\0'+bytes(9),height=1),image(b'\5'+bytes(8),height=1),image(b'\0'+bytes(8),height=1,depth=16),image(b'\0'+bytes(8),height=1,colour=3),image(b'\0'+bytes(8),height=1,interlace=1),image(b'',width=4096,height=4096)]:
            self.fault(lambda:png.decode(bad),'INVALID_RASTER_PNG')
        for kind,value in [(b'iCCP',b'ICC\0\0bad'),(b'acTL',bytes(8)),(b'zTXt',b'bad'),(b'tRNS',bytes(6)),(b'gAMA',struct.pack('>I',100000)),(b'gAMA',struct.pack('>I',45455)),(b'sRGB',b'\4')]:
            self.fault(lambda:png.decode(image(b'\0'+bytes(8),height=1,extra=chunk(kind,value))),'INVALID_RASTER_PNG')
        self.assertEqual(png.decode(image(b'\0'+bytes(8),height=1,extra=chunk(b'sRGB',b'\0')))[3],'sRGB chunk')
        # Valid zlib stream with excessive output must stop at the expected row budget.
        self.fault(lambda:png.decode(image(b'\0'+bytes(1024*1024),height=1)),'INVALID_RASTER_PNG')

    def test_literal_rotation_hidden_rgb_flatten_and_sheet(self):
        im=png.decode((ROOT/'examples/schemaxis/fixtures/imagemagick/grid.png').read_bytes())
        p=adaptor.plan(self.document('variant'));out=png.transform(im,p['images'][0],p['alpha'],p['background'])
        self.assertEqual(out[:2],(2,2));self.assertEqual(out[2],bytes([255,255,0,64,0,255,0,128,0,255,255,255,17,33,65,0]))
        p=adaptor.plan(self.document('flatten'));out=png.transform(im,p['images'][0],p['alpha'],p['background'])
        self.assertEqual(out[2],bytes([20,40,60,255,0,255,255,255,10,148,30,255,79,94,45,255]))
        s,places,canvas=png.layout([out,out],{'columns':2,'padding':1,'background':[240,240,240]})
        self.assertEqual(s[:2],(7,4));self.assertEqual([(p['x'],p['y']) for p in places],[(1,1),(4,1)])
        self.assertEqual(s[2][:4],bytes([240,240,240,255]));self.assertEqual(s[2][4*(7+1):4*(7+1)+8],out[2][:8])
        bad=copy.deepcopy(p['images'][0]);bad['crop']['x']=2
        self.fault(lambda:png.transform(im,bad,p['alpha'],p['background']),'RASTER_CROP_OUTSIDE')

    def test_sources_are_regular_bounded_and_byte_current(self):
        d=self.document();data=(ROOT/'examples/schemaxis/fixtures/imagemagick/grid.png').read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'grid.png';path.write_bytes(data);d['images'][0]['source']=str(path);first=adaptor.reusableInputs(d)
            path.write_bytes((ROOT/'examples/schemaxis/fixtures/imagemagick/grid-changed.png').read_bytes());self.assertNotEqual(first,adaptor.reusableInputs(d))
            link=Path(tmp)/'link.png';link.symlink_to(path);self.fault(lambda:adaptor.bounded(link,'INVALID_RASTER_SOURCE'),'INVALID_RASTER_SOURCE')
            if hasattr(os,'mkfifo'):
                fifo=Path(tmp)/'fifo.png';os.mkfifo(fifo);self.fault(lambda:adaptor.bounded(fifo,'INVALID_RASTER_SOURCE'),'INVALID_RASTER_SOURCE')
            path.write_bytes(b'x'*(png.BYTES+1));self.fault(lambda:adaptor.reusableInputs(d),'INVALID_RASTER_SOURCE')
            path.write_bytes(png.encode(1,1,bytes([1,2,3,255])));self.fault(lambda:adaptor.reusableInputs(d),'RASTER_COLOUR_REQUIRED');d['colourPolicy']='assume-srgb';self.assertTrue(adaptor.reusableInputs(d))

    def test_runtime_and_policy_prerequisites_stop_before_prepare(self):
        d=self.document();d['images'][0]['source']=str(ROOT/'examples/schemaxis/fixtures/imagemagick/grid.png')
        with tempfile.TemporaryDirectory() as tmp:
            for label,runtime,expected_stages in [('runtime','Version: ImageMagick 6.9.0 Q16 ',['version']),('policy','Version: ImageMagick 7.1.2-34 Q16-HDRI x86_64',['version','policy'])]:
                stages=[]
                def fake(command,directory,stage,timeout):
                    stages.append(stage);(directory/(stage+'.stdout')).write_text(runtime if stage=='version' else 'Path: [built-in]\n  Policy: Undefined\n    rights: None\n')
                with patch.object(adaptor,'execute',side_effect=fake):
                    self.fault(lambda:adaptor.run(d,Path(tmp)/label,executable=sys.executable),'VERIFICATION_FAILED')
                self.assertEqual(stages,expected_stages)


if __name__=='__main__':unittest.main()
