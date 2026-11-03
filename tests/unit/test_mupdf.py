# Copyright (C) 2026 David L F Gaden
"""Host-only MuPDF contract/oracle checks; native acceptance is a separate tool."""
import copy
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from schemaxis.adaptors.mupdf import adaptor
from schemaxis.adaptors.mupdf.inspection import png
from schemaxis.adaptors.mupdf.native_source import source
from schemaxis.core.faults import SchemaxisError

ROOT=Path(__file__).resolve().parents[2]


def rgb_png(w,h,data):
    def chunk(kind,body):return struct.pack('>I',len(body))+kind+body+struct.pack('>I',zlib.crc32(kind+body))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(data))+chunk(b'IEND',b'')


class MuPDFHost(unittest.TestCase):
    def setUp(self):
        self.document=json.loads((ROOT/'examples/schemaxis/mupdf-review.json').read_text())

    def fault(self,document,code,location=None):
        with self.assertRaises(SchemaxisError) as raised:adaptor._native_plan(document)
        self.assertEqual(raised.exception.fault.code,code)
        if location:self.assertEqual(raised.exception.fault.location,location)

    def test_deterministic_immutable_defaults_and_variant(self):
        original=copy.deepcopy(self.document)
        self.assertEqual(adaptor._native_plan(self.document),adaptor._native_plan(self.document))
        self.assertEqual(self.document,original)
        self.document.pop('dpi');self.document.pop('rotation')
        p=adaptor._native_plan(self.document);self.assertEqual((p['dpi'],p['rotation']),(72,0))
        variant=json.loads((ROOT/'examples/schemaxis/mupdf-review-variant.json').read_text())
        self.assertNotEqual(p,adaptor._native_plan(variant))

    def test_duplicates_urls_missing_and_unknown_fields(self):
        self.fault({**self.document,'pages':[2,2]},'INVALID_PDF_PAGES','$.pages')
        self.fault({**self.document,'source':'https://invalid.example/in.pdf'},'INVALID_PDF_SOURCE','$.source')
        self.fault({**self.document,'source':'relative.pdf'},'INVALID_PDF_SOURCE','$.source')
        self.fault({**self.document,'extra':False},'UNKNOWN_ARGUMENT')
        for key in ('pages','source'):
            doc={k:v for k,v in self.document.items() if k!=key}
            with self.assertRaises(SchemaxisError):adaptor._native_plan(doc)

    def test_bounded_ordered_geometry_and_rounding(self):
        p=adaptor._native_plan(self.document)
        def geometry(meta,prepared):
            for item in meta.get('pages',[]):
                item.update(mediaBox=[0,0,300,300],cropBox=None,userUnit=1,inheritedRotation=0)
            return adaptor.geometry(meta,prepared)
        meta={'pageCount':3,'pages':[{'page':2,'bounds':[0,0,216,144]}, {'page':1,'bounds':[0,0,180,120]}, {'page':3,'bounds':[0,0,144,96]}]}
        self.assertEqual(geometry(meta,p)[0],([0,0,216,144],216,144))
        self.assertEqual(geometry(meta,{**p,'rotation':90,'dpi':144})[0],([-288,0,0,432],288,432))
        with self.assertRaises(SchemaxisError):geometry({**meta,'pages':meta['pages'][::-1]},p)
        with self.assertRaises(SchemaxisError):geometry({'pageCount':129,'pages':meta['pages']},p)
        with self.assertRaises(SchemaxisError):geometry({'pageCount':1,'pages':[{'page':1,'bounds':[0,0,10000,10000]}]},{**p,'pages':[1]})
        many={'pageCount':16,'pages':[{'page':i,'bounds':[0,0,4096,4096]} for i in range(1,17)]}
        with self.assertRaises(SchemaxisError):geometry(many,{**p,'pages':list(range(1,17))})
        tiny={'pageCount':1,'pages':[{'page':1,'bounds':[0,0,10.00001,9.99999]}]}
        self.assertEqual(geometry(tiny,{**p,'pages':[1]})[0],([0,0,10,10],10,10))

    def test_closed_native_metadata_and_true_numeric_types(self):
        prepared=adaptor._native_plan({**self.document,'pages':[1]})
        page={'page':1,'bounds':[0,0,10,20],'mediaBox':[0,0,10,20],'cropBox':None,'inheritedRotation':-450,'userUnit':1}
        meta={'pageCount':1,'pages':[page]}
        adaptor.metadata(meta,prepared)
        for change in ({'page':True},{'bounds':[0,False,10,20]},{'mediaBox':[0,0,float('nan'),20]},{'inheritedRotation':45},{'userUnit':True},{'extra':1}):
            with self.assertRaises(SchemaxisError):adaptor.metadata({'pageCount':1,'pages':[{**page,**change}]},prepared)
        with self.assertRaises(SchemaxisError):adaptor.metadata({'pageCount':1,'pages':[]},prepared)
        with self.assertRaises(SchemaxisError):adaptor.metadata({'pageCount':1,'pages':[page,page]},prepared)

    def test_input_capture_regular_limit_and_digest_invalidation(self):
        with tempfile.TemporaryDirectory() as raw:
            directory=Path(raw);pdf=directory/'input.pdf';pdf.write_bytes(b'%PDF-literal fixture')
            doc={**self.document,'source':str(pdf)}
            with patch.object(adaptor,'plan',adaptor._native_plan):
                before=adaptor.reusableInputs(doc);pdf.write_bytes(b'%PDF-changed fixture')
                self.assertNotEqual(before,adaptor.reusableInputs(doc))
            link=directory/'link.pdf';link.symlink_to(pdf)
            with self.assertRaises(SchemaxisError):adaptor.bounded(link)
            with self.assertRaises(SchemaxisError):adaptor.bounded(pdf,limit=3)
            with self.assertRaises(SchemaxisError):adaptor.bounded(directory)

    def test_trusted_script_has_fixed_path_and_passive_calls(self):
        script=source(adaptor._native_plan(self.document),'render')
        self.assertNotIn(self.document['source'],script)
        self.assertNotIn('enableJS',script)
        self.assertNotIn('executeAction',script)
        self.assertIn('getTrailer().get("Encrypt")',script)
        self.assertIn('"source.pdf"',script)
        self.assertIn('total>16777216',script)

    def test_png_decode_filters_crc_and_decompression_bound(self):
        data=rgb_png(2,1,b'\0\xff\0\0\0\xff\0')
        self.assertEqual(png(data),(2,1,b'\xff\0\0\0\xff\0'))
        # Sub filtering: red, then green relative to the red pixel.
        self.assertEqual(png(rgb_png(2,1,b'\x01\xff\0\0\x01\xff\0')),(2,1,b'\xff\0\0\0\xff\0'))
        def chunk(kind,body):return struct.pack('>I',len(body))+kind+body+struct.pack('>I',zlib.crc32(kind+body))
        late_density=data[:-12]+chunk(b'pHYs',struct.pack('>IIB',2835,2835,1))+data[-12:]
        with self.assertRaises(SchemaxisError):png(late_density,72)
        with self.assertRaises(SchemaxisError):png(data,72)
        corrupted=bytearray(data);corrupted[-1]^=1
        with self.assertRaises(SchemaxisError):png(corrupted)
        with self.assertRaises(SchemaxisError):png(rgb_png(1,1,b'\0'+b'x'*1000000))

    def test_fixture_matches_independent_literal_builder(self):
        spec=importlib.util.spec_from_file_location('mupdf_fixture',ROOT/'tools/qualify_mupdf_fixtures.py')
        oracle=importlib.util.module_from_spec(spec);spec.loader.exec_module(oracle)
        self.assertEqual(oracle.FIXTURE.read_bytes(),oracle.fixture())
        self.assertIn(b'/CropBox [100 200 244 416]',oracle.fixture())
        self.assertIn(b'/Rotate 90',oracle.fixture())


if __name__=='__main__':unittest.main()
