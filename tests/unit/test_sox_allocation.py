"""Retained effective-plan and capture evidence keep exact JSON types.

Native SoX is stood in by the analytic stdlib stub from test_sox; every probe
refreshes ordinary digests so only the contract itself can reject the forgery."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

from test_sox import FAKE_SOX, wav

from schemaxis.adaptors.sox import adaptor as a
from schemaxis.core.faults import SchemaxisError
from schemaxis.publication_metadata import finalise


class SoxRetainedEvidenceTypes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary=tempfile.TemporaryDirectory();root=Path(cls.temporary.name)
        exe=root/'sox';exe.write_text(FAKE_SOX%{'python':sys.executable});exe.chmod(0o700)
        source=root/'source.wav';source.write_bytes(wav([(i*371)%20001-10000 for i in range(64)]))
        cls.document={'version':a.VERSION,'operation':'assemble','clips':[
            {'source':str(source),'startFrame':3,'frameCount':20,'gain':.5,'fadeInFrames':4,'fadeOutFrames':5},
            {'source':str(source),'startFrame':40,'frameCount':24,'gain':1,'fadeInFrames':0,'fadeOutFrames':0}]}
        cls.directory=root/'run';cls.result=a.run(cls.document,cls.directory,executable=str(exe),timeout=60)

    @classmethod
    def tearDownClass(cls):cls.temporary.cleanup()

    def setUp(self):self.saved={p:p.read_bytes() for p in self.directory.rglob('*') if p.is_file()}

    def tearDown(self):
        for path,content in self.saved.items():path.write_bytes(content)

    def refresh(self):
        d=self.directory;receipt=a.read(d,'verification.json');receipt['artifacts']=a.artifacts(d)
        receipt['evidence']={n:a.digest(d,n) for n in receipt['evidence']};a.atomic_json(d/'verification.json',receipt);finalise(d)

    def forge(self,name,edit):
        document=a.read(self.directory,name);edit(document);a.atomic_json(self.directory/name,document);self.refresh()

    def rejected(self,name,edit):
        self.forge(name,edit)
        with self.assertRaises(SchemaxisError) as caught:a.verify(self.directory)
        self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED',caught.exception.fault.to_dict())
        return caught.exception.fault

    def test_unchanged_retained_evidence_reopens(self):
        self.forge('plan.json',lambda p:None);self.forge('captures.json',lambda c:None)
        self.assertTrue(a.verify(self.directory)['verified'])

    def test_effective_plan_values_must_keep_json_types(self):
        for label,edit in [
                ('fade-in integer as boolean',lambda p:p['clips'][1].__setitem__('fadeInFrames',False)),
                ('gain integer as boolean',lambda p:p['clips'][1].__setitem__('gain',True)),
                ('start frame as float',lambda p:p['clips'][1].__setitem__('startFrame',40.0)),
                ('frame count as float',lambda p:p['clips'][0].__setitem__('frameCount',20.0))]:
            with self.subTest(label):
                self.rejected('plan.json',edit)
                for path,content in self.saved.items():path.write_bytes(content)

    def test_capture_binding_values_must_keep_json_types(self):
        for label,edit in [
                ('byte count as float',lambda c:c[0].__setitem__('bytes',float(c[0]['bytes']))),
                ('rate as float',lambda c:c[0]['info'].__setitem__('rate',8000.0)),
                ('channels as boolean',lambda c:c[1]['info'].__setitem__('channels',True)),
                ('frames as float',lambda c:c[1]['info'].__setitem__('frames',float(c[1]['info']['frames'])))]:
            with self.subTest(label):
                fault=self.rejected('captures.json',edit)
                self.assertIn('capture',fault.message)
                for path,content in self.saved.items():path.write_bytes(content)

    def test_wrong_values_are_still_reported_not_merely_types(self):
        fault=self.rejected('plan.json',lambda p:p['clips'][0].__setitem__('gain',.75))
        self.assertIn('plan',fault.message)
        for path,content in self.saved.items():path.write_bytes(content)
        fault=self.rejected('captures.json',lambda c:c[0]['info'].__setitem__('rate',16000))
        self.assertIn('capture',fault.message)


if __name__=='__main__':unittest.main()
