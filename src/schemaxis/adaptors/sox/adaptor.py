# Copyright (C) 2026 David L F Gaden
"""Bounded sample-frame edit decisions and speech conform; SoX runs in isolated native processes."""
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import sys
import time
import wave

from schemaxis.adaptors.sox import conform, mix, normalise
from schemaxis.artifacts import atomic_json
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute

VERSION = 'schemaxis.sox/1'
LIMIT = 4 * 1024 * 1024
SAMPLE_BUDGET = 1048576
INPUT_FAULTS={'INVALID_AUDIO_DATA','AUDIO_FORMAT_MISMATCH','AUDIO_SOURCE_BOUNDS','AUDIO_CLIPPING','AUDIO_RESOURCE_LIMIT','INVALID_AUDIO_SOURCE','AUDIO_CHANNEL_POLICY','AUDIO_SILENT_SOURCE','AUDIO_GAIN_LIMIT'}
FRAME = {'type':'integer','minimum':0,'maximum':262144,'default':0}
CLIP = {'type':'object','properties':{
    'source':{'type':'string','minLength':1,'maxLength':4096,'required':True},
    'startFrame':FRAME,
    'frameCount':{'type':'integer','minimum':1,'maximum':262144,'required':True},
    'gain':{'type':'number','minimum':0,'maximum':4,'default':1},
    'fadeInFrames':FRAME,'fadeOutFrames':FRAME}}
OPTIONS = {'clips':{'type':'array','items':CLIP,'minItems':1,'maxItems':8,'required':True}}
CONFORM_OPTIONS = {'source':{'type':'string','minLength':1,'maxLength':4096,'required':True},
    'channelPolicy':{'type':'enum','values':list(conform.POLICIES),'required':True}}
NORMALISE_OPTIONS = {'source':CONFORM_OPTIONS['source'],
    'targetPeak':{'type':'integer','minimum':1,'maximum':normalise.FULL_SCALE,'required':True},
    'maxGain':{'type':'number','minimum':1,'maximum':16,'required':True}}
TRACK = {'type':'object','properties':{
    'source':{'type':'string','minLength':1,'maxLength':4096,'required':True},
    'gain':{'type':'number','minimum':0,'maximum':4,'default':1},
    'offsetFrames':{'type':'integer','minimum':0,'maximum':mix.MAX_FRAMES,'default':0}}}
MIX_OPTIONS = {'narration':dict(TRACK,required=True),'background':dict(TRACK,required=True),
    'durationPolicy':{'type':'enum','values':list(mix.POLICIES),'required':True}}
DECLARATIONS = {'assemble':{'native':'sox trim STARTs COUNTs vol GAIN fade t INs COUNTs OUTs; sox --combine concatenate',
    'kinds':['file','text'],'inputs':{},'options':{k:{'value':v} for k,v in OPTIONS.items()}},
    'conform':{'native':'sox -D --single-threaded -t wav IN -t wav -e signed-integer -b 16 OUT remix SPEC rate -v 16000',
    'kinds':['file','text'],'inputs':{},'options':{k:{'value':v} for k,v in CONFORM_OPTIONS.items()}},
    'normalise':{'native':'sox -D --single-threaded -t wav IN -t wav -e signed-integer -b 16 OUT vol GAIN',
    'kinds':['file','text'],'inputs':{},'options':{k:{'value':v} for k,v in NORMALISE_OPTIONS.items()}},
    'mix':{'native':'sox ... IN pad OFFSETs 0; sox -m -v GAIN PADDED -v GAIN PADDED OUT [trim 0 FRAMEs]',
    'kinds':['file','text'],'inputs':{},'options':{k:{'value':v} for k,v in MIX_OPTIONS.items()}}}
LOSSES = ['Signed 16-bit little-endian PCM WAV only, mono or stereo, common 8000–192000 Hz rate; no resampling/channel conversion/compressed audio.',
    'Integer sample frames specify half-open cuts. Fade-in frame i uses i/N; fade-out uses (count-i)/N, so the last stored frame is 1/N rather than zero.',
    'Linear amplitude gain precedes nonoverlapping linear fades. Dither and automatic normalisation are disabled. Potential pre-fade gain clipping is refused.',
    'Per-clip processing quantises once to PCM16; concatenation preserves those integer samples exactly. Metadata retention or stripping is outside the verified contract; this is not an anonymisation tool.',
    'Eight clips maximum; aggregate source bytes <=4MiB and combined source/output scalar samples <=1048576; no playback, mix, crossfade, arbitrary effects or scripts.']


def conform_plan(document):
    keys(document,('version','operation',*CONFORM_OPTIONS),'$')
    if 'channelPolicy' not in document: fail('MISSING_ARGUMENT','channelPolicy is required: choose '+', '.join(conform.POLICIES),'$.channelPolicy')
    if document['channelPolicy'] not in conform.POLICIES: fail('INVALID_ARGUMENT','channelPolicy must be one of '+', '.join(conform.POLICIES),'$.channelPolicy')
    p=validate_arguments(CONFORM_OPTIONS,{k:v for k,v in document.items() if k in CONFORM_OPTIONS})
    path=Path(p['source'])
    if not path.is_absolute() or path.suffix.lower()!='.wav': fail('INVALID_AUDIO_SOURCE','select an absolute regular local PCM16 .wav file','$.source')
    return {'version':'schemaxis.sox.plan/1','operation':'conform',**p,'target':{'rate':conform.RATE,'channels':1,'encoding':'signed-integer','bits':16},'losses':conform.LOSSES}


def normalise_plan(document):
    keys(document,('version','operation',*NORMALISE_OPTIONS),'$')
    p=validate_arguments(NORMALISE_OPTIONS,{k:v for k,v in document.items() if k in NORMALISE_OPTIONS})
    path=Path(p['source'])
    if not path.is_absolute() or path.suffix.lower()!='.wav': fail('INVALID_AUDIO_SOURCE','select an absolute regular local PCM16 .wav file','$.source')
    return {'version':'schemaxis.sox.plan/1','operation':'normalise',**p,'target':{'peakPCM16':p['targetPeak'],'encoding':'signed-integer','bits':16},'losses':normalise.LOSSES}


def mix_plan(document):
    keys(document,('version','operation',*MIX_OPTIONS),'$')
    for role in mix.ROLES:
        if role in document: keys(document[role],('source','gain','offsetFrames'),'$.'+role)
    if 'durationPolicy' not in document: fail('MISSING_ARGUMENT','durationPolicy is required: choose '+', '.join(mix.POLICIES),'$.durationPolicy')
    p=validate_arguments(MIX_OPTIONS,{k:v for k,v in document.items() if k in MIX_OPTIONS})
    for role in mix.ROLES:
        path=Path(p[role]['source'])
        if not path.is_absolute() or path.suffix.lower()!='.wav': fail('INVALID_AUDIO_SOURCE','select an absolute regular local PCM16 .wav file',f'$.{role}.source')
        mix.gain_scaled(p[role]['gain'],f'$.{role}.gain')
    return {'version':'schemaxis.sox.plan/1','operation':'mix',**p,'losses':mix.LOSSES}


def plan(document):
    keys(document,('version','operation',*OPTIONS,*CONFORM_OPTIONS,*NORMALISE_OPTIONS,*MIX_OPTIONS),'$')
    if document.get('version') != VERSION: fail('UNSUPPORTED_VERSION','expected '+VERSION)
    if document.get('operation')=='conform': return conform_plan(document)
    if document.get('operation')=='normalise': return normalise_plan(document)
    if document.get('operation')=='mix': return mix_plan(document)
    if document.get('operation') != 'assemble': fail('UNKNOWN_FILTER','select assemble, conform, normalise or mix')
    keys(document,('version','operation',*OPTIONS),'$')
    p=validate_arguments(OPTIONS,{k:v for k,v in document.items() if k in OPTIONS})
    for i,c in enumerate(p['clips']):
        at=f'$.clips[{i}]';path=Path(c['source'])
        if not path.is_absolute() or path.suffix.lower()!='.wav': fail('INVALID_AUDIO_SOURCE','select an absolute regular local PCM16 .wav file',at+'.source')
        if c['fadeInFrames']+c['fadeOutFrames']>c['frameCount']: fail('INVALID_AUDIO_FADE','fade lengths must not overlap; their sum cannot exceed frameCount',at)
    if sum(c['frameCount'] for c in p['clips'])>262144: fail('AUDIO_RESOURCE_LIMIT','combined output exceeds 262144 frames','$.clips')
    return {'version':'schemaxis.sox.plan/1','operation':'assemble',**p,'losses':LOSSES}


def schema():
    from schemaxis.schema import DRAFT,argument_schema,object_schema
    assemble=object_schema({'version':{'const':VERSION},'operation':{'const':'assemble'},
        **{k:argument_schema(v) for k,v in OPTIONS.items()}},['version','operation','clips'])
    speech=object_schema({'version':{'const':VERSION},'operation':{'const':'conform'},
        **{k:argument_schema(v) for k,v in CONFORM_OPTIONS.items()}},['version','operation','source','channelPolicy'])
    headroom=object_schema({'version':{'const':VERSION},'operation':{'const':'normalise'},
        **{k:argument_schema(v) for k,v in NORMALISE_OPTIONS.items()}},['version','operation','source','targetPeak','maxGain'])
    overlay=object_schema({'version':{'const':VERSION},'operation':{'const':'mix'},
        **{k:argument_schema(v) for k,v in MIX_OPTIONS.items()}},['version','operation','narration','background','durationPolicy'])
    properties={**assemble['properties'],**speech['properties'],**headroom['properties'],**overlay['properties'],'operation':{'enum':['assemble','conform','normalise','mix']}}
    return {'$schema':DRAFT,**object_schema(properties,['version','operation']),'oneOf':[assemble,speech,headroom,overlay]}


def query(document): return [plan(document)['operation']],{}


def resources(document,execution,identity):
    if execution.get('threads',1)!=1: fail('INVALID_EXECUTION','audio assembly supports one serial thread',identity)
    return {'threads':1}


def bounded(path,code='VERIFICATION_FAILED',limit=LIMIT):
    try:
        fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
        with os.fdopen(fd,'rb') as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size>limit: raise ValueError('not a bounded regular file')
            data=stream.read(limit+1)
        if len(data)>limit: raise ValueError('file byte budget exceeded')
        return data
    except (OSError,ValueError) as error: fail(code,'select an intact regular file within the byte budget: '+str(error),str(path))


def pcm(data,code='INVALID_AUDIO_DATA',at='$.clips',canonical=False):
    """Strict RIFF boundary inspection precedes independent wave/struct decoding.

    `canonical` additionally requires exactly a 16-byte `fmt ` chunk followed by
    `data`, the 44-byte header observed from native SoX 14.4.2 output."""
    try:
        if len(data)<44 or data[:4]!=b'RIFF' or data[8:12]!=b'WAVE' or struct.unpack_from('<I',data,4)[0]+8!=len(data): raise ValueError('RIFF size/header mismatch')
        chunks={};order=[];offset=12
        while offset<len(data):
            if offset+8>len(data): raise ValueError('truncated chunk header')
            name=data[offset:offset+4];size=struct.unpack_from('<I',data,offset+4)[0];end=offset+8+size
            if end+(size&1)>len(data) or name in chunks: raise ValueError('duplicate or truncated chunk')
            if name not in (b'fmt ',b'data',b'LIST',b'JUNK'): raise ValueError('unsupported WAV chunk')
            if size&1 and data[end:end+1]!=b'\0': raise ValueError('nonzero chunk padding byte')
            chunks[name]=data[offset+8:end];order.append(name);offset=end+(size&1)
        if b'fmt ' not in chunks or b'data' not in chunks: raise ValueError('fmt/data required')
        if order.index(b'fmt ')>order.index(b'data'): raise ValueError('fmt chunk must precede data')
        if canonical and order!=[b'fmt ',b'data']: raise ValueError('native output must have only fmt and data chunks')
        if len(chunks[b'fmt '])!=16: raise ValueError('canonical 16-byte PCM fmt required')
        encoding,channels,rate,byte_rate,align,bits=struct.unpack('<HHIIHH',chunks[b'fmt '])
        if encoding!=1 or bits!=16 or channels not in (1,2) or not 8000<=rate<=192000 or align!=2*channels or byte_rate!=rate*align: raise ValueError('require PCM16 mono/stereo with consistent format/rate')
        if not chunks[b'data'] or len(chunks[b'data'])%align: raise ValueError('nonempty integral sample frames required')
        with wave.open(io.BytesIO(data),'rb') as stream:
            if stream.getnframes()*align!=len(chunks[b'data']): raise ValueError('sample count mismatch')
            payload=stream.readframes(stream.getnframes()+1)
        if payload!=chunks[b'data']: raise ValueError('WAV decoder/data mismatch')
        return {'rate':rate,'channels':channels,'frames':len(payload)//align},list(struct.unpack('<'+'h'*(len(payload)//2),payload))
    except (ValueError,struct.error,wave.Error,EOFError) as error: fail(code,'use canonical bounded PCM16 WAV: '+str(error),at)


def inputs(p,loader):
    """Whole-job budgets include repeated sources and decoded output scalar samples."""
    loaded=[];byte_count=0;scalar_count=0;common=None
    for i,c in enumerate(p['clips']):
        data=loader(i,c);byte_count+=len(data)
        if byte_count>LIMIT: fail('AUDIO_RESOURCE_LIMIT','aggregate WAV captures exceed 4MiB','$.clips')
        info,samples=pcm(data,at=f'$.clips[{i}].source');identity=(info['rate'],info['channels'])
        if common is not None and common!=identity: fail('AUDIO_FORMAT_MISMATCH','all clips must have the same sample rate and channel count',f'$.clips[{i}].source')
        common=identity
        if c['startFrame']+c['frameCount']>info['frames']: fail('AUDIO_SOURCE_BOUNDS','half-open trim extends beyond source frames',f'$.clips[{i}].frameCount')
        scalar_count+=len(samples)+c['frameCount']*info['channels']
        if scalar_count>SAMPLE_BUDGET: fail('AUDIO_RESOURCE_LIMIT','combined source/output exceeds 1048576 scalar samples','$.clips')
        start=c['startFrame']*info['channels'];end=start+c['frameCount']*info['channels']
        if any(not -32768<=v*c['gain']<=32767 for v in samples[start:end]): fail('AUDIO_CLIPPING','gain would clip before fade; reduce gain or source amplitude',f'$.clips[{i}].gain')
        loaded.append((data,info,samples[start:end]))
    return loaded


def source_limit(p): return conform.SOURCE_LIMIT if p['operation'] in ('conform','normalise') else LIMIT


def conform_source(p,data,at='$.source'):
    info,_,_,_=conform.info_of(data,at=at);conform.check_source(p,data,info,at);return info


def normalise_source(p,data,at='$.source'):
    """Header, duration and peak/gain decisions on the captured bytes, before any native process."""
    info,start,size,_=conform.info_of(data,at=at);normalise.check_source(info,at);normalise.decide(p,normalise.scan(data,start,size,info['channels']));return info


def mix_inputs(p,loader):
    """Both captured recordings under whole-job budgets, with identical format, layout and exact no-clipping decided before any native process."""
    loaded=[];byte_count=0
    for i,role in enumerate(mix.ROLES):
        data=loader(i,p[role]);byte_count+=len(data)
        if byte_count>LIMIT: fail('AUDIO_RESOURCE_LIMIT','aggregate WAV captures exceed 4MiB','$')
        info,samples=pcm(data,at=f'$.{role}.source');loaded.append((data,info,samples))
    for role,(_,info,_) in zip(mix.ROLES[1:],loaded[1:]):
        if (info['rate'],info['channels'])!=(loaded[0][1]['rate'],loaded[0][1]['channels']): fail('AUDIO_FORMAT_MISMATCH','both recordings must have the same sample rate and channel count; conform one first',f'$.{role}.source')
    tracks,total=mix.layout(p,[l[1] for l in loaded])
    if sum(len(l[2]) for l in loaded)+max(t['end'] for t in tracks)*loaded[0][1]['channels']>SAMPLE_BUDGET: fail('AUDIO_RESOURCE_LIMIT','combined source/output exceeds 1048576 scalar samples','$')
    mix.exact_values(p,tracks,[l[2] for l in loaded],loaded[0][1]['channels'])
    return loaded


def reusableInputs(document):
    p=plan(document)
    if p['operation']=='mix':
        return {str(i):hashlib.sha256(data).hexdigest() for i,(data,_,_) in enumerate(mix_inputs(p,lambda i,t:bounded(t['source'],'INVALID_AUDIO_SOURCE')))}
    if p['operation']=='normalise':
        data=bounded(p['source'],'INVALID_AUDIO_SOURCE',conform.SOURCE_LIMIT);normalise_source(p,data);return {'0':hashlib.sha256(data).hexdigest()}
    if p['operation']=='conform':
        data=bounded(p['source'],'INVALID_AUDIO_SOURCE',conform.SOURCE_LIMIT);conform_source(p,data);return {'0':hashlib.sha256(data).hexdigest()}
    loaded=inputs(p,lambda i,c:bounded(c['source'],'INVALID_AUDIO_SOURCE'))
    return {str(i):hashlib.sha256(data).hexdigest() for i,(data,_,_) in enumerate(loaded)}


def ideal(c,info,samples):
    """Analytic edit envelope in PCM16 units, independent of native effects."""
    values=[];n=c['frameCount'];channels=info['channels']
    for frame in range(n):
        envelope=1
        if frame<c['fadeInFrames']: envelope=frame/c['fadeInFrames']
        elif c['fadeOutFrames'] and frame>=n-c['fadeOutFrames']: envelope=(n-frame)/c['fadeOutFrames']
        values.extend(v*c['gain']*envelope for v in samples[frame*channels:(frame+1)*channels])
    return values


def measured_gain(directory,p):
    """Native `vol` argument for a normalise run, derived from the retained captured source; None for other operations."""
    if p['operation']=='mix': return p['narration']['offsetFrames']+pcm(bounded(directory/'captured-0.wav'),'VERIFICATION_FAILED','captured-0.wav')[0]['frames']
    if p['operation']!='normalise': return None
    data=bounded(directory/'captured-0.wav',limit=normalise.SOURCE_LIMIT);info,start,size,_=conform.info_of(data,'VERIFICATION_FAILED','captured-0.wav')
    return normalise.native_gain(normalise.decide(p,normalise.scan(data,start,size,info['channels']))[1])


def retained_gain(directory,p):
    try: return measured_gain(directory,p)
    except SchemaxisError as error:
        if error.fault.code not in INPUT_FAULTS: raise
        fail('VERIFICATION_FAILED','retained captured audio no longer satisfies the planned edit ('+error.fault.code+'): '+error.fault.message,error.fault.location)


def commands(executable,p,gain=None):
    result={'version':[executable,'--version']}
    if p['operation']=='mix':
        for i,role in enumerate(mix.ROLES):
            result[f'pad-{i}']=[executable,'-D','--single-threaded','-t','wav',f'captured-{i}.wav','-t','wav','-e','signed-integer','-b','16',f'pad-{i}.wav','pad',str(p[role]['offsetFrames'])+'s','0']
        result['mix']=[executable,'-D','--single-threaded','-m',*[x for i,role in enumerate(mix.ROLES) for x in ('-v',mix.native_gain(p[role]['gain']),f'pad-{i}.wav')],
            '-t','wav','-e','signed-integer','-b','16','audio.wav',*([] if p['durationPolicy']=='longest' else ['trim','0',str(gain or 'FRAMES')+'s'])]
        return result
    if p['operation']=='normalise':
        result['normalise']=[executable,'-D','--single-threaded','-t','wav','captured-0.wav','-t','wav','-e','signed-integer','-b','16','audio.wav','vol',gain or 'GAIN']
        return result
    if p['operation']=='conform':
        result['conform']=[executable,'-D','--single-threaded','-t','wav','captured-0.wav','-t','wav','-e','signed-integer','-b','16','audio.wav',
            'remix',conform.REMIX[p['channelPolicy']],'rate','-v',str(conform.RATE)]
        return result
    for i,c in enumerate(p['clips']):
        result[f'clip-{i}']=[executable,'-D','--single-threaded','-t','wav',f'captured-{i}.wav','-t','wav','-e','signed-integer','-b','16',f'clip-{i}.wav',
            'trim',str(c['startFrame'])+'s',str(c['frameCount'])+'s','vol',format(c['gain'],'.17g'),
            'fade','t',str(c['fadeInFrames'])+'s',str(c['frameCount'])+'s',str(c['fadeOutFrames'])+'s']
    result['assemble']=[executable,'-D','--single-threaded','--combine','concatenate',*[f'clip-{i}.wav' for i in range(len(p['clips']))],'-t','wav','-e','signed-integer','-b','16','audio.wav']
    return result


def stage_inputs(stage,p):
    if p['operation']=='mix': return {'pad-0':['captured-0.wav'],'pad-1':['captured-1.wav'],'mix':['pad-0.wav','pad-1.wav']}.get(stage,[])
    if p['operation'] in ('conform','normalise'): return ['captured-0.wav'] if stage==p['operation'] else []
    if stage.startswith('clip-'): return ['captured-'+stage[5:]+'.wav']
    if stage=='assemble': return [f'clip-{i}.wav' for i in range(len(p['clips']))]
    return []


def launcher(directory,stage,command,p):
    limit,fsize={'assemble':(LIMIT,8388608),'mix':(LIMIT,8388608),'normalise':(normalise.SOURCE_LIMIT,normalise.OUTPUT_LIMIT)}.get(p['operation'],(conform.SOURCE_LIMIT,conform.OUTPUT_LIMIT))
    return ('import hashlib,json,os,resource,stat\nfrom pathlib import Path\n'
        +f'command={command!r}\npaths={[str(directory/n) for n in stage_inputs(stage,p)]!r}\nbindings={{}}\n'
        +f'resource.setrlimit(resource.RLIMIT_AS,(536870912,536870912))\nresource.setrlimit(resource.RLIMIT_FSIZE,({fsize},{fsize}))\nresource.setrlimit(resource.RLIMIT_CPU,(30,30))\n'
        +'for name in paths:\n    fd=os.open(name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_NONBLOCK",0))\n    with os.fdopen(fd,"rb") as stream:\n        info=os.fstat(stream.fileno())\n'
        +f'        if not stat.S_ISREG(info.st_mode) or info.st_size>{limit}: raise ValueError("invalid native input")\n        data=stream.read({limit+1})\n'
        +'    bindings[name]=hashlib.sha256(data).hexdigest()\n'
        +f'Path({str(directory/(stage+"-inputs.json"))!r}).write_text(json.dumps(bindings,sort_keys=True))\n'
        +'os.execvpe(command[0],command,dict(os.environ,OMP_NUM_THREADS="1",SOX_OPTS=""))\n')


def qualified_runtime(directory,executable,code='UNSUPPORTED_NATIVE_VERSION'):
    runtime=bounded(directory/'version.stdout').decode().strip()
    if not re.fullmatch(re.escape(executable)+r':\s+SoX v14\.4\.2',runtime):
        fail(code,'configure the qualified SoX 14.4.2 executable','version')
    return "SoX v14.4.2"


def read(directory,name): return json.loads(bounded(directory/name))
def digest(directory,name,limit=LIMIT): return hashlib.sha256(bounded(directory/name,limit=limit)).hexdigest()


TIMELINE=('Output time zero is the first frame of audio.wav and intervals are half-open [start,end) sample frames. Excluded source frames are removed and '
    'clips are concatenated without gaps or resampling, so timestamps measured on an original recording do not survive in the output. '
    'Map output frame f inside a segment to source frame sourceStartFrame+(f-outputStartFrame) of that segment source; transcript times are seconds '
    'from output frame 0, i.e. frame/rate, and need this map to return to original time.')


MIX_TIMELINE=('Output time zero is the first frame of audio.wav and intervals are half-open [start,end) sample frames. Track frame k of the narration or background appears at output frame '
    'offsetFrames+k; the rate is shared and nothing is resampled, so a transcript time of the narration is (output frame - narration offsetFrames)/rate seconds in the narration recording. '
    'Frames before a track starts, after it ends or cut by durationPolicy narration are not that track.')


def conform_inspect(directory,p,executable):
    source=bounded(directory/'captured-0.wav',limit=conform.SOURCE_LIMIT);output=bounded(directory/'audio.wav',limit=conform.OUTPUT_LIMIT)
    info,start,size,_=conform.info_of(source,'VERIFICATION_FAILED','captured-0.wav');conform.check_source(p,source,info,'captured-0.wav')
    if bounded(directory/'conform.stdout'): fail('VERIFICATION_FAILED','native conform wrote unexpected standard output','conform.stdout')
    out_start=conform.canonical_info(output,'VERIFICATION_FAILED','audio.wav')[1]
    return conform.summarise(p,source,info,start,size,output,out_start,len(output)-out_start,bounded(directory/'conform.stderr').decode('utf-8','replace'),executable)


def normalise_inspect(directory,p):
    source=bounded(directory/'captured-0.wav',limit=normalise.SOURCE_LIMIT);output=bounded(directory/'audio.wav',limit=normalise.OUTPUT_LIMIT)
    info,start,size,_=conform.info_of(source,'VERIFICATION_FAILED','captured-0.wav');normalise.check_source(info,'captured-0.wav')
    out_info,out_start,out_size=conform.canonical_info(output,'VERIFICATION_FAILED','audio.wav',normalise.OUTPUT_LIMIT)
    return normalise.summarise(p,source,info,start,size,output,out_info,out_start,out_size,bounded(directory/'normalise.stdout'),bounded(directory/'normalise.stderr'))


def mix_inspect(directory,p):
    """Reopen both captures, both padded intermediates and the mixed output; every sample uses exact integer arithmetic independent of SoX."""
    loaded=mix_inputs(p,lambda i,t:bounded(directory/f'captured-{i}.wav'));info=loaded[0][1];channels=info['channels']
    tracks,total=mix.layout(p,[l[1] for l in loaded]);values=mix.exact_values(p,tracks,[l[2] for l in loaded],channels)
    for stage in commands('',p):
        if stage!='version' and (bounded(directory/(stage+'.stdout')) or bounded(directory/(stage+'.stderr'))): fail('VERIFICATION_FAILED','native mix stages must write nothing to standard output or error (SoX warns on clipping)',stage)
    for i,t in enumerate(tracks):
        pad_info,pad=pcm(bounded(directory/f'pad-{i}.wav'),'VERIFICATION_FAILED',f'pad-{i}.wav',True)
        if pad_info!={**info,'frames':t['end']} or pad!=[0]*(t['offset']*channels)+loaded[i][2]: fail('VERIFICATION_FAILED','native placement must be exactly the offset silence followed by the captured samples',f'pad-{i}.wav')
    out_info,actual=pcm(bounded(directory/'audio.wav'),'VERIFICATION_FAILED','audio.wav',True)
    if out_info!={**info,'frames':total}: fail('VERIFICATION_FAILED','native mix rate/channels/frame count differs from the declared duration policy','audio.wav')
    worst=mix.reopen(values[:total*channels],actual,total*channels)
    if worst is None: fail('VERIFICATION_FAILED','a mixed sample is not the nearest PCM16 integer to its exact gained sum','audio.wav')
    summaries=[];ends=[]
    for i,(role,t,(data,_,samples)) in enumerate(zip(mix.ROLES,tracks,loaded)):
        end=min(t['end'],total);included=max(0,end-t['offset']);ends.append((t['offset'],end))
        summaries.append({'role':role,'sourceSha256':hashlib.sha256(data).hexdigest(),'sourceFrames':t['frames'],'gain':p[role]['gain'],'gainExact':mix.gain_text(p[role]['gain']),
            'offsetFrames':t['offset'],'outputStartFrame':t['offset'],'outputEndFrame':end,'includedSourceFrames':included,'truncatedSourceFrames':t['frames']-included,
            'leadingSilenceFrames':t['offset'],'trailingSilenceFrames':total-end,'sourcePeakPCM16':max(abs(v) for v in samples)})
    overlap=max(0,min(e for _,e in ends)-max(s for s,_ in ends))
    covered=sum(max(0,e-s) for s,e in ends)-overlap
    return {**out_info,'durationSeconds':total/info['rate'],'durationExact':mix.exact_seconds(total,info['rate']),'durationPolicy':p['durationPolicy'],'tracks':summaries,
        'overlapFrames':overlap,'overlapStartFrame':max(s for s,_ in ends) if overlap else None,'uncoveredFrames':total-covered,
        'peakPCM16':max(abs(v) for v in actual),'samplesCompared':total*channels,
        'maxMixErrorExact':mix.error_text(worst),
        'rounding':'nearest PCM16 integer to the exact gained sum; exact ties may go either way','clipping':'refused before native processing; no sample is clipped',
        'timeline':{'originalTimestampsPreserved':False,'explanation':MIX_TIMELINE},'limits':mix.LIMITS}


def inspect(directory,p,executable=None):
    if p['operation']=='mix': return mix_inspect(directory,p)
    if p['operation']=='normalise': return normalise_inspect(directory,p)
    if p['operation']=='conform': return conform_inspect(directory,p,executable)
    loaded=inputs(p,lambda i,c:bounded(directory/f'captured-{i}.wav'));joined=[];max_error=0;segments=[];origin=0
    for i,(c,(source,info,samples)) in enumerate(zip(p['clips'],loaded)):
        segments.append({'clip':i,'sourceSha256':hashlib.sha256(source).hexdigest(),'sourceFrames':info['frames'],
            'sourceStartFrame':c['startFrame'],'sourceEndFrame':c['startFrame']+c['frameCount'],
            'outputStartFrame':origin,'outputEndFrame':origin+c['frameCount'],'gain':c['gain'],'fadeInFrames':c['fadeInFrames'],'fadeOutFrames':c['fadeOutFrames']})
        origin+=c['frameCount']
        expected=ideal(c,info,samples);actual_info,actual=pcm(bounded(directory/f'clip-{i}.wav'),'VERIFICATION_FAILED',f'clip-{i}.wav',True)
        if actual_info!={**info,'frames':c['frameCount']}: fail('VERIFICATION_FAILED','native clip rate/channels/frame count differs',f'clip-{i}.wav')
        error=max(abs(a-b) for a,b in zip(actual,expected));max_error=max(max_error,error)
        # One PCM16 quantisation <=0.5 LSB; two internal PCM32 effect truncations
        # contribute <2/65536 LSB. No tolerance growth for concatenation.
        if error>.5001: fail('VERIFICATION_FAILED','native clip samples differ from analytic trim/gain/fade by more than 0.5001 PCM16 LSB',f'clip-{i}.wav')
        joined.extend(actual)
    info,actual=pcm(bounded(directory/'audio.wav'),'VERIFICATION_FAILED','audio.wav',True)
    wanted={**loaded[0][1],'frames':sum(c['frameCount'] for c in p['clips'])}
    if info!=wanted or actual!=joined: fail('VERIFICATION_FAILED','concatenation must preserve every processed clip sample exactly','audio.wav')
    divisor=math.gcd(info['frames'],info['rate'])
    return {**info,'durationSeconds':info['frames']/info['rate'],'durationExact':{'numerator':info['frames']//divisor,'denominator':info['rate']//divisor},
        'clips':len(p['clips']),'peakPCM16':max(abs(v) for v in actual),'maxQuantisationErrorLSB':max_error,'sampleToleranceLSB':.5001,
        'timeline':{'originalTimestampsPreserved':False,'explanation':TIMELINE},'segments':segments}


def artifacts(directory,limit=LIMIT):
    return [{'file':str(directory/n),'kind':kind,'sha256':digest(directory,n,limit)} for n,kind in [('audio.wav','file'),('audio-summary.json','text')]]


def evidence_names(p):
    if p['operation']=='mix':
        return {'authored.json','plan.json','captures.json','captured-0.wav','captured-1.wav','pad-0.wav','pad-1.wav',*[s+x for s in commands('',p) for x in ('-launcher.py','-inputs.json','-submission.json','.stdout','.stderr')]}
    if p['operation'] in ('conform','normalise'):
        return {'authored.json','plan.json','captures.json','captured-0.wav',*[s+x for s in commands('',p) for x in ('-launcher.py','-inputs.json','-submission.json','.stdout','.stderr')]}
    return {'authored.json','plan.json','captures.json',*[f'captured-{i}.wav' for i in range(len(p['clips']))],*[f'clip-{i}.wav' for i in range(len(p['clips']))],
        *[s+x for s in commands('',p) for x in ('-launcher.py','-inputs.json','-submission.json','.stdout','.stderr')]}


def unreferenced(directory,p):
    """Exact top-level membership, including only declared framework sidecars."""
    known=evidence_names(p)|{'audio.wav','audio-summary.json','verification.json','result.json',
        'schema.snapshot.json','publication-metadata.json','job.json',
        'audio.wav.metadata.json','audio-summary.json.metadata.json'}
    extra=[]
    for path in directory.iterdir():
        if path.name=='.dispatch':
            if path.is_symlink() or not path.is_dir(): extra.append(path.name)
        elif path.name not in known or path.is_symlink() or not path.is_file(): extra.append(path.name)
    return sorted(extra)


def same_json(actual,expected):
    """Preserve JSON number/boolean types instead of Python's loose equality."""
    return json.dumps(actual,sort_keys=True,allow_nan=False)==json.dumps(expected,sort_keys=True,allow_nan=False)


def sources(p): return [p['narration']['source'],p['background']['source']] if p['operation']=='mix' else [p['source']] if p['operation'] in ('conform','normalise') else [c['source'] for c in p['clips']]


def capture(p):
    """Bounded source bytes and header facts; sample lists never outlive this call."""
    if p['operation']=='mix': return [(data,info) for data,info,_ in mix_inputs(p,lambda i,t:bounded(t['source'],'INVALID_AUDIO_SOURCE'))]
    if p['operation']=='normalise':
        data=bounded(p['source'],'INVALID_AUDIO_SOURCE',conform.SOURCE_LIMIT);return [(data,normalise_source(p,data))]
    if p['operation']=='conform':
        data=bounded(p['source'],'INVALID_AUDIO_SOURCE',conform.SOURCE_LIMIT);return [(data,conform_source(p,data))]
    return [(data,info) for data,info,_ in inputs(p,lambda i,c:bounded(c['source'],'INVALID_AUDIO_SOURCE'))]


def run(document,directory,*,executable=None,timeout=300):
    p=plan(document);executable=executable or os.environ.get('SCHEMAXIS_SOX') or shutil.which('sox')
    if not executable or not Path(executable).is_absolute() or not os.access(executable,os.X_OK): fail('INTERPRETER_NOT_FOUND','configure an absolute SoX 14.4.2 executable')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=3600: fail('INVALID_ARGUMENT','timeout must be finite in (0,3600]')
    deadline=time.monotonic()+timeout;directory=Path(directory).absolute()
    if directory.exists() or directory.is_symlink(): fail('OUTPUT_EXISTS','select a fresh output directory',str(directory))
    directory.mkdir(parents=True);atomic_json(directory/'authored.json',document);atomic_json(directory/'plan.json',p)
    atomic_json(directory/'result.json',{'status':'incomplete','verified':False})
    try:
        loaded=capture(p);captures=[];limit=source_limit(p)
        for i,(data,info) in enumerate(loaded):
            (directory/f'captured-{i}.wav').write_bytes(data);captures.append({'source':sources(p)[i],'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'info':info})
        del loaded
        atomic_json(directory/'captures.json',captures)
        for stage,command in commands(str(executable),p,measured_gain(directory,p)).items():
            path=directory/(stage+'-launcher.py');path.write_text(launcher(directory,stage,command,p))
            execute([sys.executable,str(path)],directory,stage,deadline-time.monotonic(),{'LANG':'C.UTF-8','OMP_NUM_THREADS':'1','SOX_OPTS':''})
            if stage=='version': qualified_runtime(directory,str(executable))
        atomic_json(directory/'audio-summary.json',inspect(directory,p,str(executable)));runtime=qualified_runtime(directory,str(executable))
        atomic_json(directory/'verification.json',{'executable':str(executable),'runtime':runtime,'artifacts':artifacts(directory,limit),'evidence':{n:digest(directory,n,limit) for n in evidence_names(p)}})
        result=verify(directory,require_result=False)
        if cancellation_requested(): fail('RUNNER_CANCELLED','audio publication cancelled')
        if time.monotonic()>=deadline: fail('RUNNER_TIMED_OUT','audio exhausted its total deadline')
        result['status']='succeeded';atomic_json(directory/'result.json',result);return result
    except Exception as error:
        if not isinstance(error,SchemaxisError):
            try: fail('NATIVE_EXECUTION_FAILED',str(error))
            except SchemaxisError as wrapped: error=wrapped
        atomic_json(directory/'result.json',{'status':'failed','verified':False,'fault':error.fault.to_dict()});raise error


def verify(directory,require_result=True):
    directory=Path(directory).absolute()
    try:
        p=plan(read(directory,'authored.json'));receipt=read(directory,'verification.json')
        if not same_json(read(directory,'plan.json'),p): fail('VERIFICATION_FAILED','effective audio plan differs')
        if require_result and read(directory,'result.json').get('status')!='succeeded': fail('INCOMPLETE_EXECUTION','audio did not complete')
        captures=[];limit=source_limit(p)
        for i,source in enumerate(sources(p)):
            data=bounded(directory/f'captured-{i}.wav',limit=limit)
            info=conform.info_of(data,'VERIFICATION_FAILED',f'captured-{i}.wav')[0] if p['operation'] in ('conform','normalise') else pcm(data,'VERIFICATION_FAILED')[0]
            captures.append({'source':source,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'info':info})
        if not same_json(read(directory,'captures.json'),captures): fail('VERIFICATION_FAILED','WAV source/capture binding differs')
        if not isinstance(receipt,dict) or set(receipt)!={'executable','runtime','artifacts','evidence'} or not isinstance(receipt['evidence'],dict): fail('VERIFICATION_FAILED','native receipt fields differ')
        extra=unreferenced(directory,p)
        if extra: fail('VERIFICATION_FAILED','unreferenced audio or native evidence files: '+', '.join(extra))
        executable=receipt['executable']
        if not isinstance(executable,str) or not Path(executable).is_absolute(): fail('VERIFICATION_FAILED','native executable identity must be absolute')
        for stage,command in commands(executable,p,retained_gain(directory,p)).items():
            submission=read(directory,stage+'-submission.json');interpreter=submission.get('interpreter',{}).get('executable');path=directory/(stage+'-launcher.py')
            if not isinstance(interpreter,str) or not Path(interpreter).is_absolute() or submission.get('nativeCommand')!=[interpreter,str(path)] or type(submission.get('exitCode')) is not int or submission['exitCode']!=0: fail('VERIFICATION_FAILED','native command/completion differs',stage)
            if bounded(path).decode()!=launcher(directory,stage,command,p): fail('VERIFICATION_FAILED','trusted native launcher differs',stage)
            if read(directory,stage+'-inputs.json')!={str(directory/n):digest(directory,n,limit) for n in stage_inputs(stage,p)}: fail('VERIFICATION_FAILED','native audio input binding differs',stage)
        runtime=qualified_runtime(directory,executable,'VERIFICATION_FAILED')
        if receipt['runtime']!=runtime: fail('VERIFICATION_FAILED','require qualified SoX v14.4.2 runtime identity')
        try: summary=inspect(directory,p,executable)
        except SchemaxisError as error:
            if error.fault.code not in INPUT_FAULTS: raise
            fail('VERIFICATION_FAILED','retained captured audio no longer satisfies the planned edit ('+error.fault.code+'): '+error.fault.message,error.fault.location)
        saved_summary=read(directory,'audio-summary.json')
        # Before the optional timeline extension, /1 published exactly this
        # smaller summary. Reopen its samples with every current check, then
        # compare only that explicitly recognised assertion set. Do not invent
        # a timeline claim for an older receipt or accept partially lost fields.
        legacy={'rate','channels','frames','durationSeconds','clips','peakPCM16','maxQuantisationErrorLSB','sampleToleranceLSB'}
        if isinstance(saved_summary,dict) and set(saved_summary)==legacy:
            summary={k:summary[k] for k in legacy}
        same=normalise.same if p['operation']=='normalise' else same_json
        if not same(saved_summary,summary): fail('VERIFICATION_FAILED','audio summary differs')
        if receipt['artifacts']!=artifacts(directory,limit): fail('VERIFICATION_FAILED','audio publication membership/digest differs')
        if set(receipt['evidence'])!=evidence_names(p): fail('VERIFICATION_FAILED','native evidence membership differs')
        for n in evidence_names(p):
            if digest(directory,n,limit)!=receipt['evidence'][n]: fail('VERIFICATION_FAILED','retained native evidence differs',n)
        fresh={'verified':True,'artifacts':2,'runtime':runtime,**summary}
        if require_result:
            saved=read(directory,'result.json')
            if not same(saved,{**fresh,'status':'succeeded'}): fail('VERIFICATION_FAILED','retained result summary differs from independent reopening')
        return fresh
    except (OSError,ValueError,KeyError,TypeError,IndexError,AttributeError) as error: fail('VERIFICATION_FAILED','invalid retained audio evidence: '+str(error))


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
