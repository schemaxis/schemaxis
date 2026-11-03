#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Qualify native PCM edits, analytic sample oracle, evidence and workflow lifecycle."""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import threading
import time
import wave

from schemaxis.adaptor_conformance import qualify, register
from schemaxis.adaptor_delivery import case_document,route_materials
from schemaxis.adaptors.sox import adaptor as a
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation
from schemaxis import workflow

ROOT=Path(__file__).resolve().parents[1]


def refused(action,code='VERIFICATION_FAILED'):
    try:action()
    except SchemaxisError as error:
        assert error.fault.code==code,error.fault.to_dict()
        return error.fault.to_dict()
    raise AssertionError('invalid audio/evidence accepted')


def wave_samples(path):
    """Independent qualification reader does not call the adaptor's PCM parser."""
    with wave.open(str(path),'rb') as stream:
        info=(stream.getframerate(),stream.getnchannels(),stream.getnframes())
        assert stream.getsampwidth()==2 and stream.getcomptype()=='NONE'
        raw=stream.readframes(stream.getnframes()+1)
    return info,list(struct.unpack('<'+'h'*(len(raw)//2),raw))


def sample_oracle(directory,document):
    all_samples=[];maximum=0;count=0
    for index,clip in enumerate(document['clips']):
        (rate,channels,frames),source=wave_samples(directory/f'captured-{index}.wav')
        (_,output_channels,output_frames),output=wave_samples(directory/f'clip-{index}.wav')
        assert (output_channels,output_frames)==(channels,clip['frameCount'])
        for j,actual in enumerate(output):
            frame=j//channels;value=source[(clip['startFrame']+frame)*channels+j%channels]*clip['gain']
            if frame<clip['fadeInFrames']:value*=frame/clip['fadeInFrames']
            if clip['fadeOutFrames'] and frame>=clip['frameCount']-clip['fadeOutFrames']:value*=(clip['frameCount']-frame)/clip['fadeOutFrames']
            assert abs(actual-value)<=.5001,(index,j,actual,value)
            maximum=max(maximum,abs(actual-value));count+=1
        all_samples+=output
    final_info,final=wave_samples(directory/'audio.wav');assert final==all_samples
    return {'scalarSamplesChecked':count,'maxErrorPCM16LSB':maximum,'exactConcatenation':True,'rateChannelsFrames':list(final_info)}


def refresh(directory):
    receipt=a.read(directory,'verification.json');receipt['artifacts']=a.artifacts(directory)
    receipt['evidence']={n:a.digest(directory,n) for n in receipt['evidence']};atomic_json(directory/'verification.json',receipt)
    from schemaxis.publication_metadata import finalise
    finalise(directory)


def negative(directory):
    report={};saved={p:p.read_bytes() for p in directory.rglob('*') if p.is_file()}
    def restore():
        for path,data in saved.items():path.write_bytes(data)
    def mutate_sample(data,delta=100,sample_offset=24):
        offset=data.index(b'data')+8;value=struct.unpack_from('<h',data,offset+sample_offset)[0]
        return data[:offset+sample_offset]+struct.pack('<h',value+delta)+data[offset+sample_offset+2:]
    for name,target,mutate in [('outputSample','audio.wav',mutate_sample),('processedClipSample','clip-0.wav',mutate_sample),
        ('riffSize','audio.wav',lambda b:b[:4]+struct.pack('<I',len(b)-9)+b[8:]),
        ('duplicateDataChunk','audio.wav',lambda b:b[:4]+struct.pack('<I',len(b)+len(b[b.index(b'data'):])-8)+b[8:]+b[b.index(b'data'):]),
        ('summaryFrameCount','audio-summary.json',lambda b:b.replace(b'"frames": 1536',b'"frames": 1535'))]:
        try:
            path=directory/target;before=path.read_bytes();after=mutate(before);assert after!=before,name;path.write_bytes(after)
            # Rebind the clip consumed by concatenation, so semantic checks, not
            # an ordinary stale input hash, must detect a forged clip.
            if target=='clip-0.wav':
                bindings=a.read(directory,'assemble-inputs.json');bindings[str(path)]=a.digest(directory,target);atomic_json(directory/'assemble-inputs.json',bindings)
            refresh(directory);report[name+'WithRefreshedHashes']=refused(lambda:a.verify(directory))['code']
        finally:restore()
    try:
        p=a.read(directory,'plan.json');path=directory/'captured-0.wav';path.write_bytes(mutate_sample(path.read_bytes(),400,200))
        captures=a.read(directory,'captures.json');captures[0]['sha256']=a.digest(directory,path.name);atomic_json(directory/'captures.json',captures)
        bindings=a.read(directory,'clip-0-inputs.json');bindings[str(path)]=a.digest(directory,path.name);atomic_json(directory/'clip-0-inputs.json',bindings)
        refresh(directory);report['changedCapturedPCMWithRefreshedBindings']=refused(lambda:a.verify(directory))['code']
    finally:restore()
    for name,mutation in [('missingEvidence',lambda r:r['evidence'].pop('assemble.stdout')),
            ('extraEvidence',lambda r:r['evidence'].update({'extra.json':'0'*64})),
            ('publicationMembership',lambda r:r['artifacts'].pop()),('runtimeIdentity',lambda r:r.update(runtime='SoX v99.9.9'))]:
        try:
            receipt=a.read(directory,'verification.json');mutation(receipt);atomic_json(directory/'verification.json',receipt)
            report[name]=refused(lambda:a.verify(directory))['code']
        finally:restore()
    try:
        submission=a.read(directory,'assemble-submission.json');submission['nativeCommand']=['/forged/command'];atomic_json(directory/'assemble-submission.json',submission);refresh(directory)
        report['forgedNativeCommandWithRefreshedHashes']=refused(lambda:a.verify(directory))['code']
    finally:restore()
    assert a.verify(directory)['verified'];return report


def interrupted_processes(directory,document):
    """Deterministic lifecycle wrappers are not counted as native audio evidence."""
    wrapper=directory/'slow-runtime.py';marker=directory/'slow.pid'
    wrapper.write_text('#!'+sys.executable+'\nimport os,time\nfrom pathlib import Path\nPath('+repr(str(marker))+').write_text(str(os.getpid()))\ntime.sleep(30)\n');wrapper.chmod(0o700)
    outcomes={}
    for action in ['timeout','cancel']:
        if marker.exists():marker.unlink()
        cancel=threading.Event()
        def trigger():
            deadline=time.monotonic()+5
            while not marker.exists() and time.monotonic()<deadline:time.sleep(.01)
            if marker.exists():cancel.set()
        thread=threading.Thread(target=trigger,daemon=True) if action=='cancel' else None
        if thread:thread.start()
        try:
            with allocation({'threads':1,'ranks':1},cancel):
                outcomes[action]=refused(lambda:a.run(document,directory/('inflight-'+action),executable=str(wrapper),timeout=8 if thread else .4),'RUNNER_CANCELLED' if thread else 'RUNNER_TIMED_OUT')['code']
        finally:
            if thread:thread.join(6)
        assert marker.exists(),'lifecycle probe did not launch owned child'
        pid=int(marker.read_text())
        try:os.kill(pid,0)
        except ProcessLookupError:pass
        else:raise AssertionError('owned process survived '+action)
    return outcomes


def rate_boundaries(directory,executable):
    """Explicit supported-range boundaries/common rates; no exhaustive rate claim."""
    results=[]
    for rate in [8000,11025,12345,16000,22050,32000,44100,48000,96000,192000]:
        source=directory/f'rate-{rate}.wav'
        values=[-32768,32767,-101,101,0,1,-1,32766]*8
        with wave.open(str(source),'wb') as stream:
            stream.setparams((1,2,rate,0,'NONE','not compressed'));stream.writeframes(struct.pack('<64h',*values))
        document={'version':a.VERSION,'operation':'assemble','clips':[
            {'source':str(source),'startFrame':0,'frameCount':16,'gain':.5,'fadeInFrames':8,'fadeOutFrames':8},
            {'source':str(source),'startFrame':63,'frameCount':1,'gain':1,'fadeInFrames':0,'fadeOutFrames':0}]}
        target=directory/f'rate-{rate}';a.run(document,target,executable=executable,timeout=10)
        result=sample_oracle(target,a.plan(document));info,samples=wave_samples(target/'audio.wav')
        assert info==(rate,1,17) and samples[-1]==32766
        results.append({'rate':rate,'verified':True,'frames':17,'lastSourceFrameRetainedExactly':True,**result})
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--sox',required=True,type=Path);parser.add_argument('--output-directory',required=True,type=Path);parser.add_argument('--register',action='store_true')
    args=parser.parse_args();directory=args.output_directory.resolve();directory.mkdir(parents=True,exist_ok=False)
    locations={'sox':str(args.sox.resolve())};report={'verified':False}
    try:
        receipt=qualify(a.VERSION,directory/'kit',native=True,root=ROOT,locations=locations,timeout=30,wall_timeout=45)
        report['native']={'verified':receipt['verified'],'cases':[c['id'] for c in receipt['cases']],'runtimes':[c['runtime'] for c in receipt['cases']],'lifecycle':receipt['lifecycle']}
        _,_,entry=route_materials(a.VERSION)
        report['independentSamples']={}
        for case in entry['development']['cases']:
            doc=case_document(entry,case,ROOT);report['independentSamples'][case['id']]=sample_oracle(directory/'kit'/case['id'],a.plan(doc))
        _,literal=wave_samples(directory/'kit/fade-endpoints/audio.wav')
        assert literal==[0,-6000,12000,-12000,12000,-9000,6000,-3000];report['literalFadeEndpoints']=literal
        _,extrema=wave_samples(directory/'kit/boundary-extrema/audio.wav')
        assert extrema[:4]==[0,0,-12,0] and extrema[4000:4002]==[32767,-32768]
        report['literalStereoExtrema']={'firstTwoFrames':extrema[:4],'touchingFadeFrame2000':extrema[4000:4002]}
        document=case_document(entry,entry['development']['cases'][0],ROOT);baseline=directory/'kit/mono-sequence';report['negative']=negative(baseline)
        for name,update,code in [('sourceBounds',{'startFrame':4090},'AUDIO_SOURCE_BOUNDS'),('overlap',{'fadeInFrames':1024,'fadeOutFrames':1},'INVALID_AUDIO_FADE'),('prefadeClipping',{'gain':4},'AUDIO_CLIPPING')]:
            bad=copy.deepcopy(document);bad['clips'][0].update(update);target=directory/name
            report['negative'][name]=refused(lambda:a.run(bad,target,executable=locations['sox']),code)['code'];assert not (target/'version-submission.json').exists()
        source=directory/'mutable.wav';shutil.copyfile(document['clips'][0]['source'],source)
        for c in document['clips']:c['source']=str(source)
        graph={'version':'schemaxis.workflow/1','operations':[{'id':'audio','document':document}]}
        first=workflow.execute(graph,directory/'workflow',locations=locations,timeout=30);assert workflow.verify(directory/'workflow')['verified']
        second=workflow.execute(graph,directory/'workflow',locations=locations,timeout=30,resume=True);assert second['jobs'][0]['reused']
        raw=bytearray(source.read_bytes());offset=raw.index(b'data')+8+40;struct.pack_into('<h',raw,offset,struct.unpack_from('<h',raw,offset)[0]+100);source.write_bytes(raw)
        third=workflow.execute(graph,directory/'workflow',locations=locations,timeout=30,resume=True);assert not third['jobs'][0]['reused'];assert workflow.verify(directory/'workflow')['verified']
        report['workflow']={'status':first['status'],'unchangedReused':True,'changedSamePathPCMReused':False}
        consumer={'version':a.VERSION,'operation':'assemble','clips':[{'source':{'$artifact':'producer','index':0},'startFrame':11,'frameCount':300,'gain':.5,'fadeInFrames':20,'fadeOutFrames':30}]}
        handoff={'version':'schemaxis.workflow/1','operations':[{'id':'producer','document':document},{'id':'consumer','document':consumer}]}
        passed=workflow.execute(handoff,directory/'handoff',locations=locations,timeout=30);assert workflow.verify(directory/'handoff')['verified'];report['handoff']={'status':passed['status'],'verified':True}
        # Remove original input after execution: captures alone must reopen correctly.
        source.unlink()
        for job in passed['jobs']: assert a.verify(Path(job['directory']))['verified']
        report['handoff']['standaloneCapturesReopenAfterOriginalRemoved']=True
        report['handoff']['workflowRequiresCurrentOriginalSource']=refused(lambda:workflow.verify(directory/'handoff'),'INVALID_AUDIO_SOURCE')['code']
        study=case_document(entry,entry['development']['cases'][0],ROOT);study['definitions']={'level':.25};study['clips'][0]['gain']={'$document':'/definitions/level'};study['axes']=[{'name':'level','values':[.25,.5]}];study['clips'][1]['gain']={'$axis':'level'}
        result=a.run(study,directory/'study',executable=locations['sox'],timeout=30);assert a.verify(directory/'study')['verified'];assert len(result['states'])==2;report['composition']={'states':2,'verified':True}
        report['sampleRateBoundaries']=rate_boundaries(directory,locations['sox'])
        report['inflightLifecycle']=interrupted_processes(directory,case_document(entry,entry['development']['cases'][0],ROOT))
        if args.register:register(directory/'kit/qualification.json')
        report['verified']=True
    finally:atomic_json(directory/'acceptance.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
