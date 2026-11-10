# Copyright (C) 2026 David L F Gaden
"""PCM edit decisions, exact semantic failures and strict source bounds."""
import copy
import hashlib
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
from fractions import Fraction

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


FAKE_SOX="""#!%(python)s
import struct,sys,wave
def read(name):
    with wave.open(name,'rb') as w:
        return w.getnchannels(),w.getframerate(),list(struct.unpack('<'+'h'*(w.getnframes()*w.getnchannels()),w.readframes(w.getnframes())))
def write(name,channels,rate,values):
    with wave.open(name,'wb') as w:
        w.setparams((channels,2,rate,0,'NONE','not compressed'));w.writeframes(struct.pack('<'+'h'*len(values),*values))
a=sys.argv
if a[1:]==['--version']: print(a[0]+':      SoX v14.4.2')
elif '--combine' in a:
    names=a[a.index('concatenate')+1:a.index('-t')];joined=[]
    for n in names:
        channels,rate,values=read(n);joined+=values
    write(a[-1],channels,rate,joined)
else:
    channels,rate,values=read(a[5]);i=a.index('trim');start=int(a[i+1][:-1]);count=int(a[i+2][:-1]);gain=float(a[a.index('vol')+1])
    fi,_,fo=(int(a[a.index('fade')+k][:-1]) for k in (2,3,4))
    out=[]
    for f in range(count):
        e=1
        if f<fi:e=f/fi
        elif fo and f>=count-fo:e=(count-f)/fo
        out+=[int(round(v*gain*e)) for v in values[(start+f)*channels:(start+f+1)*channels]]
    write(a[-2] if False else a[a.index('-b')+2],channels,rate,out)
"""


def pad(chunk):return chunk+(b'\0' if len(chunk)&1 else b'')


def riff(*chunks):
    body=b''.join(chunks);return b'RIFF'+struct.pack('<I',4+len(body))+b'WAVE'+body


def fmt(channels=1,rate=8000,bits=16,encoding=1,align=None,byte_rate=None):
    align=align if align is not None else channels*bits//8
    return b'fmt '+struct.pack('<IHHIIHH',16,encoding,channels,rate,byte_rate if byte_rate is not None else rate*align,align,bits)


def data(values):
    raw=struct.pack('<'+'h'*len(values),*values);return b'data'+struct.pack('<I',len(raw))+raw


class SoxMalformedAndEvidence(unittest.TestCase):
    """Contract holes that survive ordinary hash refresh; native SoX is stood in by a stdlib analytic stub."""
    @classmethod
    def setUpClass(cls):
        cls.temporary=tempfile.TemporaryDirectory();root=Path(cls.temporary.name);cls.root=root
        exe=root/'sox';exe.write_text(FAKE_SOX%{'python':sys.executable});exe.chmod(0o700)
        source=root/'source.wav';source.write_bytes(wav([(i*371)%20001-10000 for i in range(64)]));cls.source=source
        cls.document={'version':a.VERSION,'operation':'assemble','clips':[
            {'source':str(source),'startFrame':3,'frameCount':20,'gain':.5,'fadeInFrames':4,'fadeOutFrames':5},
            {'source':str(source),'startFrame':40,'frameCount':24,'gain':1,'fadeInFrames':0,'fadeOutFrames':0}]}
        cls.directory=root/'run';cls.result=a.run(cls.document,cls.directory,executable=str(exe),timeout=60)

    @classmethod
    def tearDownClass(cls):cls.temporary.cleanup()

    def setUp(self):self.saved={p:p.read_bytes() for p in self.directory.rglob('*') if p.is_file()}

    def tearDown(self):
        for path in list(self.directory.rglob('*')):
            if path.is_file() and path not in self.saved:path.unlink()
        for path,content in self.saved.items():path.write_bytes(content)

    def fault(self,action,code='VERIFICATION_FAILED'):
        with self.assertRaises(SchemaxisError) as caught:action()
        self.assertEqual(caught.exception.fault.code,code,caught.exception.fault.to_dict());return caught.exception.fault

    def refresh(self):
        """Mimic a forger who repairs every ordinary artifact/evidence digest."""
        d=self.directory;receipt=a.read(d,'verification.json');receipt['artifacts']=a.artifacts(d)
        receipt['evidence']={n:a.digest(d,n) for n in receipt['evidence']};a.atomic_json(d/'verification.json',receipt)
        from schemaxis.publication_metadata import finalise
        finalise(d)

    def rebind(self,stage,name):
        d=self.directory;bindings=a.read(d,stage+'-inputs.json');bindings[str(d/name)]=a.digest(d,name);a.atomic_json(d/(stage+'-inputs.json'),bindings)

    def test_baseline_reopens_and_states_exact_handoff(self):
        self.assertTrue(a.verify(self.directory)['verified'])
        r=self.result;self.assertEqual((r['rate'],r['channels'],r['frames']),(8000,1,44))
        self.assertEqual(Fraction(r['durationExact']['numerator'],r['durationExact']['denominator']),Fraction(44,8000))
        self.assertIs(r['timeline']['originalTimestampsPreserved'],False);self.assertIn('do not survive',r['timeline']['explanation'])
        source_hash=hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.assertEqual(r['segments'],[
            dict(clip=0,sourceSha256=source_hash,sourceFrames=64,sourceStartFrame=3,sourceEndFrame=23,outputStartFrame=0,outputEndFrame=20,gain=.5,fadeInFrames=4,fadeOutFrames=5),
            dict(clip=1,sourceSha256=source_hash,sourceFrames=64,sourceStartFrame=40,sourceEndFrame=64,outputStartFrame=20,outputEndFrame=44,gain=1,fadeInFrames=0,fadeOutFrames=0)])
        self.assertEqual(json.loads((self.directory/'result.json').read_text())['segments'],r['segments'])

    def test_legacy_summary_reopens_without_inventing_timeline_claims(self):
        legacy={'rate','channels','frames','durationSeconds','clips','peakPCM16','maxQuantisationErrorLSB','sampleToleranceLSB'}
        d=self.directory
        summary={k:v for k,v in a.read(d,'audio-summary.json').items() if k in legacy}
        a.atomic_json(d/'audio-summary.json',summary)
        result=a.read(d,'result.json')
        for key in ('durationExact','timeline','segments'): result.pop(key)
        a.atomic_json(d/'result.json',result);self.refresh()
        checked=a.verify(d);self.assertTrue(checked['verified']);self.assertNotIn('timeline',checked)
        summary['frames']+=1;a.atomic_json(d/'audio-summary.json',summary);self.refresh()
        self.fault(lambda:a.verify(d))

    def test_output_wav_must_be_canonical_native_form_even_with_refreshed_hashes(self):
        """A valid-sample WAV with injected LIST metadata passes the permissive source parser but not as native output."""
        d=self.directory;original=(d/'audio.wav').read_bytes();header=original[:36];payload=original[36:]
        info=b'INFOICMT'+struct.pack('<I',8)+b'injected'
        injected=riff(header[12:],pad(b'LIST'+struct.pack('<I',len(info))+info),payload);a.pcm(injected)
        (d/'audio.wav').write_bytes(injected);self.refresh();self.fault(lambda:a.verify(d))
        (d/'audio.wav').write_bytes(original)
        clip=(d/'clip-0.wav').read_bytes();(d/'clip-0.wav').write_bytes(riff(clip[12:36],pad(b'JUNK'+struct.pack('<I',3)+b'abc'),clip[36:]))
        self.rebind('assemble','clip-0.wav');self.refresh();self.fault(lambda:a.verify(d))

    def test_unreferenced_audio_and_native_stage_files_are_membership_failures(self):
        d=self.directory
        for name in ('clip-2.wav','audio-copy.wav','clip-0-launcher.py.bak.wav','extra-submission.json','extra.stderr','audio.WAV','audio.flac','notes.json','orphan.metadata.json'):
            (d/name).write_bytes(b'x');self.refresh();self.fault(lambda:a.verify(d));(d/name).unlink()
        self.assertTrue(a.verify(d)['verified'])

    def test_receipt_and_retained_result_cannot_be_forged_without_reopening(self):
        d=self.directory;receipt=a.read(d,'verification.json')
        for name,mutation in [('extra',lambda r:r.update(claimed='qualified')),('evidenceType',lambda r:r.update(evidence=[])),('missing',lambda r:r.pop('runtime'))]:
            forged=copy.deepcopy(receipt);mutation(forged);a.atomic_json(d/'verification.json',forged);self.fault(lambda:a.verify(d))
            (d/'verification.json').write_bytes(self.saved[d/'verification.json'])
        for key,value in [('claimedTranscript','invented'),('verified',1),('frames',44.0),('frames',45),('durationSeconds',9.0),('rate',16000),('segments',[]),('timeline',{'originalTimestampsPreserved':True})]:
            forged=a.read(d,'result.json');forged[key]=value;a.atomic_json(d/'result.json',forged);self.fault(lambda:a.verify(d))
            (d/'result.json').write_bytes(self.saved[d/'result.json'])
        self.assertTrue(a.verify(d)['verified'])

    def test_forged_timebase_summary_or_capture_with_refreshed_hashes(self):
        d=self.directory
        for key,value in [('rate',16000),('frames',43),('durationExact',{'numerator':1,'denominator':1}),('segments',[])]:
            summary=a.read(d,'audio-summary.json');summary[key]=value;a.atomic_json(d/'audio-summary.json',summary);self.refresh();self.fault(lambda:a.verify(d))
            (d/'audio-summary.json').write_bytes(self.saved[d/'audio-summary.json'])
        summary=a.read(d,'audio-summary.json');summary['segments'][1]['sourceStartFrame']=39;summary['segments'][1]['sourceEndFrame']=63
        a.atomic_json(d/'audio-summary.json',summary);self.refresh();self.fault(lambda:a.verify(d));(d/'audio-summary.json').write_bytes(self.saved[d/'audio-summary.json'])
        wrong=(d/'audio.wav').read_bytes();wrong=wrong[:24]+struct.pack('<II',16000,32000)+wrong[32:]
        (d/'audio.wav').write_bytes(wrong);self.refresh();self.fault(lambda:a.verify(d));(d/'audio.wav').write_bytes(self.saved[d/'audio.wav'])
        shortened=a.pcm((d/'audio.wav').read_bytes())[1][:-1];(d/'audio.wav').write_bytes(wav(shortened,rate=8000));self.refresh();self.fault(lambda:a.verify(d))
        (d/'audio.wav').write_bytes(self.saved[d/'audio.wav'])
        captured=(d/'captured-0.wav').read_bytes();(d/'captured-0.wav').write_bytes(captured[:24]+struct.pack('<II',16000,32000)+captured[32:])
        captures=a.read(d,'captures.json');captures[0]['sha256']=a.digest(d,'captured-0.wav');captures[0]['info']['rate']=16000;a.atomic_json(d/'captures.json',captures)
        self.rebind('clip-0','captured-0.wav');self.refresh();self.fault(lambda:a.verify(d))

    def test_forged_submission_and_launcher_with_refreshed_hashes(self):
        d=self.directory
        submission=a.read(d,'clip-1-submission.json');submission['exitCode']=1;a.atomic_json(d/'clip-1-submission.json',submission);self.refresh();self.fault(lambda:a.verify(d))
        (d/'clip-1-submission.json').write_bytes(self.saved[d/'clip-1-submission.json'])
        launcher=(d/'assemble-launcher.py').read_text().replace('concatenate','concatenate ');(d/'assemble-launcher.py').write_text(launcher);self.refresh();self.fault(lambda:a.verify(d))

    def test_malformed_pcm_header_variants_are_rejected_before_native_use(self):
        good=[100,-100,200,-200]
        cases={'nonzero pad':riff(fmt(),pad(b'LIST'+struct.pack('<I',3)+b'abc')[:-1]+b'\1',data(good)),
            'data before fmt':riff(data(good),fmt()),'fact chunk':riff(fmt(),b'fact'+struct.pack('<II',4,4),data(good)),
            'duplicate JUNK':riff(pad(b'JUNK'+struct.pack('<I',2)+b'ab'),pad(b'JUNK'+struct.pack('<I',2)+b'ab'),fmt(),data(good)),
            'extensible':riff(fmt(encoding=0xFFFE),data(good)),'float':riff(fmt(encoding=3),data(good)),'8-bit':riff(fmt(bits=8,align=1),data(good)),
            '24-bit':riff(fmt(bits=24,align=3),data(good)),'three channels':riff(fmt(channels=3,align=6),data(good*3)),'zero channels':riff(fmt(channels=0,align=0),data(good)),
            'rate low':riff(fmt(rate=7999),data(good)),'rate high':riff(fmt(rate=192001),data(good)),'align':riff(fmt(align=4),data(good)),
            'byte rate':riff(fmt(byte_rate=1),data(good)),'empty data':riff(fmt(),data([])),'partial stereo frame':riff(fmt(channels=2,align=4),data([1,2,3])),
            'big endian':b'RIFX'+riff(fmt(),data(good))[4:],'wave tag':riff(fmt(),data(good))[:8]+b'WAVX'+riff(fmt(),data(good))[12:]}
        for name,value in cases.items():
            with self.subTest(name):self.fault(lambda:a.pcm(value),'INVALID_AUDIO_DATA')
        info,values=a.pcm(riff(pad(b'JUNK'+struct.pack('<I',3)+b'abc'),fmt(),pad(b'LIST'+struct.pack('<I',3)+b'abc'),data(good)));self.assertEqual(values,good)
        self.fault(lambda:a.pcm(riff(pad(b'JUNK'+struct.pack('<I',3)+b'abc'),fmt(),data(good)),canonical=True),'INVALID_AUDIO_DATA')
        self.assertEqual(a.pcm(riff(fmt(),data(good)),canonical=True)[1],good)


if __name__=='__main__':unittest.main()
