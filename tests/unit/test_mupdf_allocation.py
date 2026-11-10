"""Live-run preflight classification of source-derived PDF page geometry (host only)."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptors.mupdf import adaptor
from schemaxis.core.faults import SchemaxisError
from schemaxis.errors import fail

ROOT=Path(__file__).resolve().parents[2]
RUNTIME='mutool version 1.28.5'


def page(**change):
    return {'page':1,'bounds':[0,0,100,200],'mediaBox':[0,0,100,200],'cropBox':None,'userUnit':1,'inheritedRotation':0,**change}


class PreflightGeometry(unittest.TestCase):
    def setUp(self):
        self.document={**json.loads((ROOT/'examples/schemaxis/mupdf-review.json').read_text()),'pages':[1]}
        self.prepared=adaptor._native_plan(self.document)

    def run_with(self,inspected):
        """Run with a fake native launcher that returns *inspected* for the inspect stage."""
        reached=[]
        def launch(directory,stage,command,deadline):
            if stage=='version':(directory/'version.stdout').write_text(RUNTIME);(directory/'version.stderr').write_text('')
            elif stage=='inspect':(directory/'inspect.stdout').write_text(json.dumps(inspected))
            else:reached.append(stage);fail('REACHED_RENDER','preflight accepted the page geometry')
        with tempfile.TemporaryDirectory() as raw,patch.object(adaptor,'launch',launch),patch.object(adaptor,'plan',adaptor._native_plan):
            pdf=Path(raw)/'in.pdf';pdf.write_bytes(b'%PDF-1.4 literal fixture')
            out=Path(raw)/'out'
            with self.assertRaises(SchemaxisError) as raised:
                adaptor.run({**self.document,'source':str(pdf)},out,executable=sys.executable)
            failure=json.loads((out/'result.json').read_text())
        return raised.exception.fault,failure,reached

    def refused(self,inspected,key,index=0):
        fault,result,reached=self.run_with({'pageCount':1,'pages':[inspected] if isinstance(inspected,dict) else inspected})
        self.assertEqual(fault.code,'PDF_GEOMETRY_INVALID',fault.message)
        self.assertEqual(fault.location,f'$.pages[{index}]')
        self.assertIn(key,fault.message);self.assertIn('PDF page 1',fault.message)
        self.assertEqual(result['fault']['code'],'PDF_GEOMETRY_INVALID');self.assertEqual(reached,[])

    def test_non_quarter_turn_rotate_is_a_source_fault(self):
        # Native 1.27.0 reported /Rotate 45 raw while rendering 90 degrees; 90.5 likewise.
        self.refused(page(bounds=[0,0,200,100],inheritedRotation=45),'/Rotate')
        self.refused(page(bounds=[0,0,200,100],inheritedRotation=90.5),'/Rotate')

    def test_nonpositive_or_invalid_user_unit_is_a_source_fault(self):
        # Native: UserUnit -2 scaled by magnitude; a string UserUnit read as 0.
        self.refused(page(bounds=[0,0,200,400],userUnit=-2),'/UserUnit')
        self.refused(page(userUnit=0),'/UserUnit')

    def test_missing_or_empty_media_box_is_not_silently_letter(self):
        # Native substituted US Letter for both and reported null / zero-area raw boxes.
        self.refused(page(bounds=[0,0,612,792],mediaBox=None),'/MediaBox')
        self.refused(page(bounds=[0,0,612,792],mediaBox=[0,0,0,0]),'/MediaBox')

    def test_crop_box_disjoint_from_media_box_is_refused(self):
        self.refused(page(bounds=[0,0,612,792],cropBox=[500,500,600,600]),'/CropBox')
        self.refused(page(bounds=[0,0,612,792],cropBox=[10,10,10,50]),'/CropBox')

    def test_location_names_the_selected_page_position(self):
        self.document['pages']=[2,1];self.prepared=adaptor._native_plan(self.document)
        fault,_,_=self.run_with({'pageCount':2,'pages':[page(page=2),page(page=1,mediaBox=None)]})
        self.assertEqual((fault.code,fault.location),('PDF_GEOMETRY_INVALID','$.pages[1]'))
        self.assertIn('PDF page 1',fault.message)

    def test_valid_geometry_still_reaches_render(self):
        for changed in (page(),page(mediaBox=[-20,-40,140,180],cropBox=[0,-20,96,124],bounds=[0,0,192,288],userUnit=2),
                        page(mediaBox=[100,200,0,0],bounds=[0,0,100,200]),            # reversed corners
                        page(cropBox=[50,100,500,900],bounds=[0,0,50,100]),            # partial overlap
                        page(inheritedRotation=-450,bounds=[0,0,200,100]),
                        page(bounds=[0,0,200,100],inheritedRotation=90)):
            fault,_,reached=self.run_with({'pageCount':1,'pages':[changed]})
            self.assertEqual((fault.code,reached),('REACHED_RENDER',['render']),changed)

    def test_structural_evidence_faults_stay_verification_failures(self):
        for inspected in ({'pageCount':1,'pages':[]},{'pageCount':1,'pages':[page(extra=1)]},{'pageCount':True,'pages':[page()]},
                          {'pageCount':1,'pages':[page(page=True)]},{'pageCount':1,'pages':[page(bounds=[0,0,float('inf'),1])]}):
            fault,_,reached=self.run_with(inspected)
            self.assertEqual((fault.code,reached),('VERIFICATION_FAILED',[]),inspected)

    def test_retained_evidence_checks_are_not_reclassified(self):
        # Legacy retained evidence that earlier releases accepted must keep verifying offline.
        legacy=[page(mediaBox=None,bounds=[0,0,612,792]),page(cropBox=[500,500,600,600],bounds=[0,0,612,792])]
        for item in legacy:
            adaptor.metadata({'pageCount':1,'pages':[item]},self.prepared)
            self.assertEqual(adaptor.geometry({'pageCount':1,'pages':[item]},self.prepared)[0][1:],(612,792))
        with self.assertRaises(SchemaxisError) as raised:
            adaptor.metadata({'pageCount':1,'pages':[page(inheritedRotation=45)]},self.prepared)
        self.assertEqual(raised.exception.fault.code,'VERIFICATION_FAILED')


if __name__=='__main__':unittest.main()
