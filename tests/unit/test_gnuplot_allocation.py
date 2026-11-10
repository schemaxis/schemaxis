"""Exported gnuplot evidence keeps its verified handoff; host-only, no native process.

A small stand-in executable writes placeholder SVG/PNG bytes and the independent
geometry inspection is replaced with a constant, so these tests cover only the
retained-path boundary (launcher, input bindings, command and publication paths).
Real SVG/PNG inspection is unchanged and still exercised by qualification.
"""
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import tempfile
import textwrap
import unittest
from unittest.mock import patch
import zlib

from schemaxis.adaptors.gnuplot import adaptor
from schemaxis.core.faults import SchemaxisError
from schemaxis.schema_store import export_run

ROOT=Path(__file__).resolve().parents[2]


def png():
    def chunk(kind,body): return struct.pack('>I',len(body))+kind+body+struct.pack('>I',zlib.crc32(kind+body))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0\0\0\0'))+chunk(b'IEND',b'')


FAKE=textwrap.dedent('''\
    #!{python}
    import sys
    if sys.argv[1:]==['-d','--version']: print('gnuplot 6.0 patchlevel 5')
    else:
        open('plot.svg','w').write('<svg xmlns="http://www.w3.org/2000/svg"/>')
        open('plot.png','wb').write({png!r})
    ''')


class ExportedGnuplotEvidence(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        fake=self.root/'gnuplot';fake.write_text(FAKE.format(python=__import__('sys').executable,png=png()))
        fake.chmod(fake.stat().st_mode|stat.S_IXUSR)
        source=self.root/'data.csv';shutil.copy(ROOT/'examples/schemaxis/fixtures/gnuplot/calibration.csv',source)
        document=json.loads((ROOT/'examples/schemaxis/gnuplot-calibration.json').read_text());document['source']=str(source)
        summary=patch.object(adaptor,'inspect',lambda directory,p:{'rows':3,'series':1});summary.start();self.addCleanup(summary.stop)
        self.original=self.root/'original';adaptor.run(document,self.original,executable=str(fake))

    def refused(self,directory):
        with self.assertRaises(SchemaxisError) as caught: adaptor.verify(directory)
        self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')
        return caught.exception.fault

    def test_control_in_place_verifies(self):
        self.assertTrue(adaptor.verify(self.original)['verified'])

    def test_exported_copy_verifies_without_rewriting_receipt(self):
        moved=self.root/'moved';export_run(self.original,moved)
        before=(moved/'verification.json').read_bytes();self.assertEqual(before,(self.original/'verification.json').read_bytes())
        self.assertTrue(adaptor.verify(moved)['verified']);self.assertEqual((moved/'verification.json').read_bytes(),before)
        self.assertTrue(adaptor.verify(self.original)['verified'])
        again=self.root/'again';export_run(moved,again);self.assertTrue(adaptor.verify(again)['verified'])

    def test_hand_copy_is_refused_with_actionable_recovery(self):
        copied=self.root/'plain';shutil.copytree(self.original,copied)
        fault=self.refused(copied);self.assertIn('schemaxis export',fault.recovery)

    def test_export_origin_does_not_hide_tampering(self):
        for name,change in {
            'script':lambda d:(d/'plot.gp').write_text('# edited\n'),
            'image':lambda d:(d/'plot.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"><g/></svg>'),
            'captured':lambda d:(d/'captured.csv').write_bytes((d/'captured.csv').read_bytes().replace(b'1,2,0.5',b'1,2,0.4')),
            'launcher':lambda d:(d/'render-launcher.py').write_text((d/'render-launcher.py').read_text()+'\n'),
        }.items():
            moved=self.root/('moved-'+name);export_run(self.original,moved);change(moved)
            self.refused(moved)

    def test_origin_cannot_redirect_to_an_unrelated_directory(self):
        moved=self.root/'moved';export_run(self.original,moved)
        manifest=moved/'publication-metadata.json';value=json.loads(manifest.read_text());value['recordedDirectory']=str(self.root/'elsewhere')
        manifest.write_text(json.dumps(value));self.refused(moved)


if __name__=='__main__':unittest.main()
