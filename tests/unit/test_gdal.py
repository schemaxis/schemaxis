"""Independent GeoTIFF reader, pixel oracle and declarative host contract."""
import copy
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

from schemaxis.adaptors.gdal import adaptor, reference
from schemaxis.core.faults import SchemaxisError
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('gdal_fixtures',ROOT/'tools/qualify_gdal_fixtures.py')
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)


def edit_tag(data,tag,value):
    out=bytearray(data);offset=struct.unpack_from('<I',out,4)[0];n=struct.unpack_from('<H',out,offset)[0]
    for i in range(n):
        p=offset+2+i*12
        if struct.unpack_from('<H',out,p)[0]==tag:
            struct.pack_into('<I',out,p+8,value);return bytes(out)
    raise AssertionError('tag absent')


class GdalTests(unittest.TestCase):
    def setUp(self):
        self.document=json.loads((ROOT/'examples/schemaxis/gdal-window-variant.json').read_text())
        self.document['source']=str(ROOT/'examples/schemaxis/fixtures/gdal/elevation.tif')
        self.source=Path(self.document['source']).read_bytes()

    def test_immutable_typed_plan(self):
        original=copy.deepcopy(self.document);adaptor._native_plan(self.document);self.assertEqual(original,self.document)
        for change in ({'x':True},{'x':-1},{'source':'relative.tif'},{'resampling':'bilinear'},{'epsg':32614},{'units':'guess'},{'outputWidth':4096,'outputHeight':4096},{'nativeFlags':[]},{'nodata':float('nan')}):
            with self.subTest(change=change),self.assertRaises(SchemaxisError):adaptor._native_plan({**self.document,**change})
        for key in adaptor.OPTIONS:
            with self.subTest(key=key),self.assertRaises(SchemaxisError):adaptor._native_plan({k:v for k,v in self.document.items() if k!=key})

    def test_literal_nearest_and_corners(self):
        raster=reference.parse(self.source);out=reference.expected(raster,adaptor._native_plan(self.document))
        self.assertEqual(out['pixels'],[21,23,24,41,43,-9999])
        self.assertEqual(reference.summary(out)['corners'],[[500010,5499980],[500050,5499920]])
        self.assertEqual(reference.summary(out)['mean'],30.4)
        self.assertEqual(reference.summary(out)['nodataCount'],1)
        for change in ({'epsg':4326},{'units':'K'},{'nodata':0},{'x':5}):
            with self.assertRaises(ValueError):reference.expected(raster,{**self.document,**change})

    def test_endian_dtype_all_nodata(self):
        for dtype,nodata in [('UInt16',65535),('Int16',-9999),('Float32',-9999)]:
            for endian in ('<','>'):
                raster=reference.parse(fixtures.tiff([nodata]*30,dtype=dtype,nodata=nodata,endian=endian))
                summary=reference.summary(raster)
                self.assertEqual(summary['nodataCount'],30);self.assertEqual(summary['validCount'],0)
                self.assertIsNone(summary['mean']);self.assertIsNone(summary['minimum']);self.assertIsNone(summary['maximum'])
        raster=reference.parse((ROOT/'examples/schemaxis/fixtures/gdal/temperature.tif').read_bytes())
        self.assertEqual(raster['pixels'][-1],280.5);self.assertEqual(raster['geotransform'],[-97.5,.1,0,50.5,0,-.2])

    def test_strict_hostile_tiff(self):
        bad=[b'not TIFF',self.source[:-1],edit_tag(self.source,259,5),edit_tag(self.source,277,2),edit_tag(self.source,273,2),edit_tag(self.source,279,99999),edit_tag(self.source,256,999999),edit_tag(self.source,258,8),self.source.replace(b'UNITTYPE',b'FOOBARRY')]
        offset=struct.unpack_from('<I',self.source,4)[0];n=struct.unpack_from('<H',self.source,offset)[0]
        extra=bytearray(self.source);struct.pack_into('<I',extra,offset+2+12*n,8);bad.append(bytes(extra))
        point=bytearray(self.source)
        for i in range(n):
            tag,kind,count,start=struct.unpack_from('<HHII',point,offset+2+12*i)
            if tag==34735:
                for j in range((count-4)//4):
                    key=struct.unpack_from('<H',point,start+8+j*8)[0]
                    if key==1025:struct.pack_into('<H',point,start+8+j*8+6,2)
        bad.append(bytes(point))
        bad.append(edit_tag(self.source,273,offset))  # pixel payload cannot alias metadata
        for data in bad:
            with self.subTest(length=len(data)),self.assertRaises((ValueError,UnicodeError)):reference.parse(data)
        with self.assertRaises(ValueError):reference.parse(fixtures.tiff([float('nan')]*30,dtype='Float32'))
        for key in ('pixels','geotransform','epsg','nodata','units'):
            a=reference.parse(self.source);b=copy.deepcopy(a)
            if isinstance(b[key],list):b[key][0]+=1
            elif isinstance(b[key],str):b[key]='changed'
            else:b[key]+=1
            with self.assertRaises(ValueError):reference.compare(a,b)

    def test_affine_conditioning_and_closed_snapshot_types(self):
        for origin,spacing in [((1e15,1e15),(.1,.1)),((500000,5500000),(1e-10,1e-10))]:
            with self.assertRaisesRegex(ValueError,'unresolvable affine'):
                reference.parse(fixtures.tiff([1]*30,origin=origin,spacing=spacing))
        source=reference.parse(fixtures.tiff([1]*30))
        bad=copy.deepcopy(source);bad['geotransform'][0]+=source['geotransform'][1]/1000
        with self.assertRaisesRegex(ValueError,'geotransform differs'):reference.compare(source,bad)
        huge=reference.parse(fixtures.tiff([1]*30,origin=(1e12,1e12),spacing=(1,1)))
        changed=copy.deepcopy(huge);changed['geotransform'][0]+=.01
        with self.assertRaisesRegex(ValueError,'geotransform differs'):reference.compare(huge,changed)
        for key in ('band','width','height','epsg','nodata'):
            invalid=copy.deepcopy(source);invalid[key]=True
            with self.subTest(key=key),self.assertRaises(ValueError):reference.compare(source,invalid)
        invalid=copy.deepcopy(source);invalid['pixels'][0]=True
        with self.assertRaises(ValueError):reference.compare(source,invalid)
        invalid=copy.deepcopy(source);invalid['geotransform'][2]=False
        with self.assertRaises(ValueError):reference.compare(source,invalid)
        invalid=copy.deepcopy(source);invalid['pixels'][0]=10**1000
        with self.assertRaises(ValueError):reference.compare(source,invalid)
        # A double-valued strip offset used to reach unpack with a float index.
        invalid=bytearray(self.source);off=struct.unpack_from('<I',invalid,4)[0];n=struct.unpack_from('<H',invalid,off)[0]
        for i in range(n):
            p=off+2+i*12
            if struct.unpack_from('<H',invalid,p)[0]==273:struct.pack_into('<H',invalid,p+2,12)
        with self.assertRaisesRegex(ValueError,'kind/count mismatch'):reference.parse(bytes(invalid))

    def test_studio_source_fill_insert_edit_and_undo(self):
        from schemaxis.adaptors import registry
        from schemaxis.console_session import AdaptorConsoleSession
        from schemaxis.studio_library import instantiate_item, load_library, apply_inserts
        library=load_library('gdal');original=copy.deepcopy(library)
        for item in library['templates']:
            filled=instantiate_item(library,item,provider='gdal')
            self.assertEqual(registry.plan(filled)['operation'],'window')
            with self.assertRaises(SchemaxisError):registry.plan(instantiate_item(library,item,provider='gdal',filled=False))
            altered=apply_inserts(filled,[{'at':'','merge':{'outputWidth':2}}])
            self.assertEqual(registry.plan(altered)['outputWidth'],2)
        self.assertEqual(library,original)
        with tempfile.TemporaryDirectory() as folder:
            session=AdaptorConsoleSession(folder,provider='gdal')
            try:
                before=session.document;draft=session.draft()
                result=session.edit_source(json.dumps({**before,'outputWidth':2}),session.active_document,draft['revision'])
                self.assertFalse(result.get('diagnostics'));self.assertEqual(session.document['outputWidth'],2)
                session.undo();self.assertEqual(session.document,before)
            finally:session.close()

    def test_bounded_regular_files(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'source.tif';p.write_bytes(self.source)
            self.assertEqual(adaptor.bounded(p),self.source)
            link=Path(folder)/'link.tif';link.symlink_to(p)
            with self.assertRaises(SchemaxisError):adaptor.bounded(link)
            with self.assertRaises(SchemaxisError):adaptor.bounded(p,limit=4)
            import os
            pipe=Path(folder)/'pipe.tif';os.mkfifo(pipe)
            with self.assertRaises(SchemaxisError):adaptor.bounded(pipe)


if __name__=='__main__':unittest.main()
