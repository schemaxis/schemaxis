# Copyright (C) 2026 David L F Gaden
"""PCM edit decisions, exact semantic failures and strict source bounds."""
import copy
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

from schemaxis.adaptors import registry
from schemaxis.adaptors.sox import adaptor as a
from schemaxis.core.faults import SchemaxisError

ROOT=Path(__file__).resolve().parents[2]


def wav(values,channels=1,rate=8000):
    stream=io.BytesIO()
    with wave.open(stream,'wb') as w:
        w.setparams((channels,2,rate,0,'NONE','not compressed'));w.writeframes(struct.pack('<'+'h'*len(values),*values))
    return stream.getvalue()


class SoxContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=ROOT/'src/schemaxis/adaptors/sox/adaptor.json.pending'
        cls.registration=patch.dict(registry.ADAPTORS,{'sox':json.loads(path.read_text())}) if path.exists() else patch.dict(registry.ADAPTORS,{})
        cls.registration.start()

    @classmethod
    def tearDownClass(cls):cls.registration.stop()

    def doc(self,name='assembly'):return json.loads((ROOT/f'examples/schemaxis/sox-{name}.json').read_text())

    def fault(self,action,code):
        with self.assertRaises(SchemaxisError) as caught:action()
        self.assertEqual(caught.exception.fault.code,code,caught.exception.fault.to_dict())
        return caught.exception.fault

    def test_common_host_conformance_and_discovery(self):
        from schemaxis.adaptor_conformance import host
        from schemaxis.capabilities import CapabilityCatalogue
        from schemaxis.search_acceptance import check_cases
        from schemaxis.studio_guidance import audit
        self.assertTrue(host(a.VERSION)['verified'])
        self.assertTrue(check_cases(CapabilityCatalogue(providers=['sox']),'sox')['complete'])
        self.assertTrue(audit('sox')['complete'])

    def test_immutable_deterministic_defaults(self):
        d=self.doc();d['clips'][0]={'source':'/recording.wav','frameCount':100};before=copy.deepcopy(d)
        p=a.plan(d);self.assertEqual(d,before);self.assertEqual(p,a.plan(d))
        self.assertEqual(p['clips'][0],dict(source='/recording.wav',frameCount=100,startFrame=0,gain=1,fadeInFrames=0,fadeOutFrames=0))
        self.assertEqual(a.query(d)[0],['assemble'])

    def test_exact_cross_field_faults(self):
        self.assertEqual(self.fault(lambda:a.plan(self.doc('fade-invalid')),'INVALID_AUDIO_FADE').location,'$.clips[0]')
        d=self.doc();d['clips']=[dict(source='/recording.wav',frameCount=262144)]*2
        self.fault(lambda:a.plan(d),'AUDIO_RESOURCE_LIMIT')
        for source in ('relative.wav','https://example.org/a.wav','/recording.mp3'):
            d=self.doc();d['clips'][0]['source']=source;self.fault(lambda:a.plan(d),'INVALID_AUDIO_SOURCE')
        for name in ('command','script','effects','options'):
            d=self.doc();d[name]='arbitrary';self.fault(lambda:a.plan(d),'UNKNOWN_ARGUMENT')

    def test_wave_payload_integrity(self):
        data=wav([100,-100,200,-200]);info,values=a.pcm(data);self.assertEqual(values,[100,-100,200,-200]);self.assertEqual(info,dict(rate=8000,channels=1,frames=4))
        def sized(data):return data[:4]+struct.pack('<I',len(data)-8)+data[8:]
        malformed=[data[:-1],data+b'\0',b'RF64'+data[4:],data[:20]+struct.pack('<H',3)+data[22:],data[:32]+struct.pack('<H',3)+data[34:]]
        malformed+=[sized(data+data[12:36]),sized(data+data[36:]),sized(data[:36]+b'data'+struct.pack('<I',7)+data[44:-1]+b'\0'),sized(data+b'X'),sized(data[:36]+b'data'+struct.pack('<I',100)+data[44:])]
        for value in malformed:self.fault(lambda:a.pcm(value),'INVALID_AUDIO_DATA')

    def test_independent_literal_envelope(self):
        p=a.plan(self.doc('endpoint'));c=p['clips'][0];data=(ROOT/'examples/schemaxis/fixtures/sox/endpoint.wav').read_bytes();info,samples=a.pcm(data)
        self.assertEqual(a.ideal(c,info,samples),[0,-6000,12000,-12000,12000,-9000,6000,-3000])
        c.update(fadeInFrames=0,fadeOutFrames=1);self.assertEqual(a.ideal(c,info,samples),samples)
        c.update(fadeInFrames=1,fadeOutFrames=0);self.assertEqual(a.ideal(c,info,samples),[0,*samples[1:]])

    def test_source_bounds_format_and_prefade_clipping(self):
        p=a.plan(self.doc('endpoint'));good=wav([1000,-1000]*4)
        self.assertEqual(a.inputs(p,lambda i,c:good)[0][1]['frames'],8)
        p['clips'][0]['startFrame']=1;self.assertEqual(self.fault(lambda:a.inputs(p,lambda i,c:good),'AUDIO_SOURCE_BOUNDS').location,'$.clips[0].frameCount')
        p=a.plan(self.doc('endpoint'));p['clips'][0]['gain']=4
        self.fault(lambda:a.inputs(p,lambda i,c:wav([20000]*8)),'AUDIO_CLIPPING')
        p=a.plan(self.doc('assembly'))
        self.fault(lambda:a.inputs(p,lambda i,c:wav([0]*4096,rate=8000 if i==0 else 16000)),'AUDIO_FORMAT_MISMATCH')
        self.fault(lambda:a.inputs(p,lambda i,c:wav([0]*4096,channels=1 if i==0 else 2)),'AUDIO_FORMAT_MISMATCH')
        self.fault(lambda:a.inputs(p,lambda i,c:wav([0]*600000)),'AUDIO_RESOURCE_LIMIT')

    def test_regular_file_bounds_and_byte_reuse(self):
        with tempfile.TemporaryDirectory() as name:
            directory=Path(name);path=directory/'clip.wav';path.write_bytes(wav([100,-100]*4));d=self.doc('endpoint');d['clips'][0]['source']=str(path)
            before=a.reusableInputs(d);path.write_bytes(wav([200,-200]*4));self.assertNotEqual(before,a.reusableInputs(d))
            link=directory/'link.wav';link.symlink_to(path);self.fault(lambda:a.bounded(link,'INVALID_AUDIO_SOURCE'),'INVALID_AUDIO_SOURCE')
            if hasattr(os,'mkfifo'):
                fifo=directory/'fifo.wav';os.mkfifo(fifo);self.fault(lambda:a.bounded(fifo,'INVALID_AUDIO_SOURCE'),'INVALID_AUDIO_SOURCE')
            self.fault(lambda:a.bounded(directory,'INVALID_AUDIO_SOURCE'),'INVALID_AUDIO_SOURCE')
            path.write_bytes(b'0'*(a.LIMIT+1));self.fault(lambda:a.reusableInputs(d),'INVALID_AUDIO_SOURCE')

    def test_unsuitable_runtime_rejected_before_clip_processing(self):
        with tempfile.TemporaryDirectory() as name:
            directory=Path(name);executable=directory/'wrong-sox.py';marker=directory/'processed'
            executable.write_text('#!'+sys.executable+'\nimport sys\nfrom pathlib import Path\nif sys.argv[1:]==["--version"]: print(sys.argv[0]+": SoX v14.4.1")\nelse: Path('+repr(str(marker))+').touch()\n')
            executable.chmod(0o700);d=self.doc('endpoint');d['clips'][0]['source']=str(ROOT/'examples/schemaxis/fixtures/sox/endpoint.wav')
            self.fault(lambda:a.run(d,directory/'result',executable=str(executable),timeout=10),'UNSUPPORTED_NATIVE_VERSION')
            self.assertFalse(marker.exists());self.assertTrue((directory/'result/version-submission.json').exists())
            self.assertFalse((directory/'result/clip-0-submission.json').exists())

    def test_trusted_native_mapping(self):
        p=a.plan(self.doc('endpoint'));commands=a.commands('/native/sox',p)
        self.assertEqual(commands['clip-0'][-10:],['trim','0s','8s','vol','1','fade','t','2s','8s','4s'])
        self.assertIn('--combine',commands['assemble']);self.assertIn('-D',commands['clip-0'])


if __name__=='__main__':unittest.main()
