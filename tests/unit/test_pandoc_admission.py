"""Host report semantics, discovery, schema agreement and bounded evidence."""
import copy
import json
import hashlib
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from schemaxis.adaptors import registry
from schemaxis.adaptors.pandoc import adaptor
from schemaxis.adaptor_conformance import host
from schemaxis.capabilities import CapabilityCatalogue
from schemaxis.core.faults import SchemaxisError
from schemaxis.search_acceptance import check_cases
from schemaxis.studio_guidance import audit

ROOT=Path(__file__).resolve().parents[2]


class PandocAdmission(unittest.TestCase):
    def document(self): return json.loads((ROOT/'examples/schemaxis/pandoc-report.json').read_text())
    def fault(self,document,code):
        with self.assertRaises(SchemaxisError) as caught: adaptor.plan(document)
        self.assertEqual(caught.exception.fault.code,code)
        return caught.exception.fault

    def test_host_contract_and_discovery(self):
        self.assertTrue(host(adaptor.VERSION)['verified'])
        self.assertTrue(check_cases(CapabilityCatalogue(providers=['pandoc']),'pandoc')['complete'])
        self.assertTrue(audit('pandoc')['complete'])
        self.assertEqual(adaptor.query(self.document())[0],['report'])

    def test_immutable_deterministic_defaults(self):
        document=self.document();document['sections'][0].pop('level');document['sections'][1]['content'][1].pop('widthMm');before=copy.deepcopy(document)
        prepared=adaptor.plan(document)
        self.assertEqual(document,before);self.assertEqual(adaptor.plan(document),prepared)
        self.assertEqual(prepared['sections'][0]['level'],1);self.assertEqual(prepared['sections'][1]['content'][1]['widthMm'],80)

    def test_semantic_faults_are_located(self):
        document=self.document();document['sections'][1]['content'][0]['rows'][1]=['10']
        self.assertIn('sections[1]',self.fault(document,'INVALID_REPORT_TABLE').location)
        document=self.document();document['sections'][0]['level']=2
        self.assertEqual(self.fault(document,'INVALID_HEADING_ORDER').location,'$.sections[0].level')
        for text in ('line\nbreak','two  spaces',' edge','a\tb','a\u00a0b','bad\x7ftext','bad\ud800text'):
            document=self.document();document['title']=text
            self.fault(document,'INVALID_REPORT_TEXT')
        for source in ('relative.png','https://example.org/image.png','/tmp/test.svg'):
            document=self.document();document['sections'][1]['content'][1]['source']=source
            self.fault(document,'INVALID_REPORT_IMAGE')

    def test_closed_structure_and_literal_text(self):
        document=self.document();document['script']='print(1)'
        self.fault(document,'UNKNOWN_ARGUMENT')
        document=self.document();document['sections'][0]['content'][0]['text']='<script>alert("literal")</script> & text'
        self.assertEqual(adaptor.plan(document)['sections'][0]['content'][0]['text'],document['sections'][0]['content'][0]['text'])
        document=self.document();document['sections']*=11
        self.fault(document,'INVALID_ARGUMENT')

    def test_png_bytes_limits_and_safe_descriptor(self):
        path=ROOT/'examples/schemaxis/fixtures/pandoc/calibration.png'; data=path.read_bytes()
        self.assertEqual(adaptor.png(data,'fixture')['width'],48)
        for changed in (data[:-1],data+b'x',data[:50]+b'\x00'+data[51:]):
            with self.assertRaises(SchemaxisError): adaptor.png(changed,'fixture')
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'link.png';target.symlink_to(path)
            with self.assertRaises(SchemaxisError): adaptor.bounded(target,'INVALID_REPORT_IMAGE')
            if hasattr(os,'mkfifo'):
                fifo=Path(temp)/'fifo.png';os.mkfifo(fifo)
                with self.assertRaises(SchemaxisError): adaptor.bounded(fifo,'INVALID_REPORT_IMAGE')

    def test_html_misleading_active_and_duplicate_attributes(self):
        from schemaxis.adaptors.pandoc.inspection import html_report
        model=[{'kind':'heading','level':1,'text':'Result'},{'kind':'paragraph','text':'Literal <value> & units'}]
        source='<html><head><title>Report</title><style>p {margin: 0}</style></head><body><header><h1>Report</h1></header><h1>Result</h1><p>Literal &lt;value&gt; &amp; units</p></body></html>'
        # The native acceptance verifies the actual qualified stylesheet. Use a
        # small approved stylesheet here to exercise the independent host parser.
        approved=hashlib.sha256(b'p {margin: 0}').hexdigest()
        with patch('schemaxis.adaptors.pandoc.inspection.QUALIFIED_STYLESHEET_SHA256',approved):
            self.check_html_probes(html_report,source,model)

    def check_html_probes(self,html_report,source,model):
        html_report(source,'Report',model)
        for old,new in [('<p>','<p hidden="hidden">'),('<body>','<body onload="alert(1)">'),
                        ('<head>','<head><meta http-equiv="refresh" content="0;url=https://invalid.example" />'),
                        ('<head>','<head><style>@import "https://invalid.example/a";</style>'),
                        ('</style>','body {display:none}</style>'),
                        ('</style>','p {opacity:0}</style>'),
                        ('<style>p {margin: 0}</style>',''),
                        ('<h1>Result','<h1 id="bad" id="good">Result')]:
            with self.assertRaises(SchemaxisError):html_report(source.replace(old,new,1),'Report',model)

    def test_source_bytes_invalidate_reuse(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'figure.png';data=(ROOT/'examples/schemaxis/fixtures/pandoc/calibration.png').read_bytes();target.write_bytes(data)
            document=self.document();document['sections'][1]['content'][1]['source']=str(target)
            first=adaptor.reusableInputs(document);target.write_bytes(data+b'changed')
            self.assertNotEqual(first,adaptor.reusableInputs(document))


if __name__=='__main__': unittest.main()
