# Copyright (C) 2026 David L F Gaden
"""Bounded sample-frame edit decisions; SoX runs in isolated native processes."""
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

from schemaxis.artifacts import atomic_json
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute

VERSION = 'schemaxis.sox/1'
LIMIT = 4 * 1024 * 1024
SAMPLE_BUDGET = 1048576
FRAME = {'type':'integer','minimum':0,'maximum':262144,'default':0}
CLIP = {'type':'object','properties':{
    'source':{'type':'string','minLength':1,'maxLength':4096,'required':True},
    'startFrame':FRAME,
    'frameCount':{'type':'integer','minimum':1,'maximum':262144,'required':True},
    'gain':{'type':'number','minimum':0,'maximum':4,'default':1},
    'fadeInFrames':FRAME,'fadeOutFrames':FRAME}}
OPTIONS = {'clips':{'type':'array','items':CLIP,'minItems':1,'maxItems':8,'required':True}}
DECLARATIONS = {'assemble':{'native':'sox trim STARTs COUNTs vol GAIN fade t INs COUNTs OUTs; sox --combine concatenate',
    'kinds':['file','text'],'inputs':{},'options':{k:{'value':v} for k,v in OPTIONS.items()}}}
LOSSES = ['Signed 16-bit little-endian PCM WAV only, mono or stereo, common 8000–192000 Hz rate; no resampling/channel conversion/compressed audio.',
    'Integer sample frames specify half-open cuts. Fade-in frame i uses i/N; fade-out uses (count-i)/N, so the last stored frame is 1/N rather than zero.',
    'Linear amplitude gain precedes nonoverlapping linear fades. Dither and automatic normalisation are disabled. Potential pre-fade gain clipping is refused.',
    'Per-clip processing quantises once to PCM16; concatenation preserves those integer samples exactly. Metadata retention or stripping is outside the verified contract; this is not an anonymisation tool.',
    'Eight clips maximum; aggregate source bytes <=4MiB and combined source/output scalar samples <=1048576; no playback, mix, crossfade, arbitrary effects or scripts.']


def plan(document):
    keys(document,('version','operation',*OPTIONS),'$')
    if document.get('version') != VERSION: fail('UNSUPPORTED_VERSION','expected '+VERSION)
    if document.get('operation') != 'assemble': fail('UNKNOWN_FILTER','select assemble')
    p=validate_arguments(OPTIONS,{k:v for k,v in document.items() if k in OPTIONS})
    for i,c in enumerate(p['clips']):
        at=f'$.clips[{i}]';path=Path(c['source'])
        if not path.is_absolute() or path.suffix.lower()!='.wav': fail('INVALID_AUDIO_SOURCE','select an absolute regular local PCM16 .wav file',at+'.source')
        if c['fadeInFrames']+c['fadeOutFrames']>c['frameCount']: fail('INVALID_AUDIO_FADE','fade lengths must not overlap; their sum cannot exceed frameCount',at)
    if sum(c['frameCount'] for c in p['clips'])>262144: fail('AUDIO_RESOURCE_LIMIT','combined output exceeds 262144 frames','$.clips')
    return {'version':'schemaxis.sox.plan/1','operation':'assemble',**p,'losses':LOSSES}


def schema():
    from schemaxis.schema import DRAFT,argument_schema,object_schema
    return {'$schema':DRAFT,**object_schema({'version':{'const':VERSION},'operation':{'const':'assemble'},
        **{k:argument_schema(v) for k,v in OPTIONS.items()}},['version','operation','clips'])}


def query(document): plan(document);return ['assemble'],{}


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


def pcm(data,code='INVALID_AUDIO_DATA',at='$.clips'):
    """Strict RIFF boundary inspection precedes independent wave/struct decoding."""
    try:
        if len(data)<44 or data[:4]!=b'RIFF' or data[8:12]!=b'WAVE' or struct.unpack_from('<I',data,4)[0]+8!=len(data): raise ValueError('RIFF size/header mismatch')
        chunks={};offset=12
        while offset<len(data):
            if offset+8>len(data): raise ValueError('truncated chunk header')
            name=data[offset:offset+4];size=struct.unpack_from('<I',data,offset+4)[0];end=offset+8+size
            if end+(size&1)>len(data) or name in chunks: raise ValueError('duplicate or truncated chunk')
            if name not in (b'fmt ',b'data',b'LIST',b'JUNK'): raise ValueError('unsupported WAV chunk')
            chunks[name]=data[offset+8:end];offset=end+(size&1)
        if set(chunks)<{b'fmt ',b'data'} or b'fmt ' not in chunks or b'data' not in chunks: raise ValueError('fmt/data required')
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


def reusableInputs(document):
    p=plan(document);loaded=inputs(p,lambda i,c:bounded(c['source'],'INVALID_AUDIO_SOURCE'))
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


def commands(executable,p):
    result={'version':[executable,'--version']}
    for i,c in enumerate(p['clips']):
        result[f'clip-{i}']=[executable,'-D','--single-threaded','-t','wav',f'captured-{i}.wav','-t','wav','-e','signed-integer','-b','16',f'clip-{i}.wav',
            'trim',str(c['startFrame'])+'s',str(c['frameCount'])+'s','vol',format(c['gain'],'.17g'),
            'fade','t',str(c['fadeInFrames'])+'s',str(c['frameCount'])+'s',str(c['fadeOutFrames'])+'s']
    result['assemble']=[executable,'-D','--single-threaded','--combine','concatenate',*[f'clip-{i}.wav' for i in range(len(p['clips']))],'-t','wav','-e','signed-integer','-b','16','audio.wav']
    return result


def stage_inputs(stage,p):
    if stage.startswith('clip-'): return ['captured-'+stage[5:]+'.wav']
    if stage=='assemble': return [f'clip-{i}.wav' for i in range(len(p['clips']))]
    return []


def launcher(directory,stage,command,p):
    return ('import hashlib,json,os,resource,stat\nfrom pathlib import Path\n'
        +f'command={command!r}\npaths={[str(directory/n) for n in stage_inputs(stage,p)]!r}\nbindings={{}}\n'
        +'resource.setrlimit(resource.RLIMIT_AS,(536870912,536870912))\nresource.setrlimit(resource.RLIMIT_FSIZE,(8388608,8388608))\nresource.setrlimit(resource.RLIMIT_CPU,(30,30))\n'
        +'for name in paths:\n    fd=os.open(name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_NONBLOCK",0))\n    with os.fdopen(fd,"rb") as stream:\n        info=os.fstat(stream.fileno())\n'
        +f'        if not stat.S_ISREG(info.st_mode) or info.st_size>{LIMIT}: raise ValueError("invalid native input")\n        data=stream.read({LIMIT+1})\n'
        +'    bindings[name]=hashlib.sha256(data).hexdigest()\n'
        +f'Path({str(directory/(stage+"-inputs.json"))!r}).write_text(json.dumps(bindings,sort_keys=True))\n'
        +'os.execvpe(command[0],command,dict(os.environ,OMP_NUM_THREADS="1",SOX_OPTS=""))\n')


def qualified_runtime(directory,executable,code='UNSUPPORTED_NATIVE_VERSION'):
    runtime=bounded(directory/'version.stdout').decode().strip()
    if not re.fullmatch(re.escape(executable)+r':\s+SoX v14\.4\.2',runtime):
        fail(code,'configure the qualified SoX 14.4.2 executable','version')
    return "SoX v14.4.2"


def read(directory,name): return json.loads(bounded(directory/name))
def digest(directory,name): return hashlib.sha256(bounded(directory/name)).hexdigest()


def inspect(directory,p):
    loaded=inputs(p,lambda i,c:bounded(directory/f'captured-{i}.wav'));joined=[];max_error=0
    for i,(c,(_,info,samples)) in enumerate(zip(p['clips'],loaded)):
        expected=ideal(c,info,samples);actual_info,actual=pcm(bounded(directory/f'clip-{i}.wav'),'VERIFICATION_FAILED',f'clip-{i}.wav')
        if actual_info!={**info,'frames':c['frameCount']}: fail('VERIFICATION_FAILED','native clip rate/channels/frame count differs',f'clip-{i}.wav')
        error=max(abs(a-b) for a,b in zip(actual,expected));max_error=max(max_error,error)
        # One PCM16 quantisation <=0.5 LSB; two internal PCM32 effect truncations
        # contribute <2/65536 LSB. No tolerance growth for concatenation.
        if error>.5001: fail('VERIFICATION_FAILED','native clip samples differ from analytic trim/gain/fade by more than 0.5001 PCM16 LSB',f'clip-{i}.wav')
        joined.extend(actual)
    info,actual=pcm(bounded(directory/'audio.wav'),'VERIFICATION_FAILED','audio.wav')
    wanted={**loaded[0][1],'frames':sum(c['frameCount'] for c in p['clips'])}
    if info!=wanted or actual!=joined: fail('VERIFICATION_FAILED','concatenation must preserve every processed clip sample exactly','audio.wav')
    return {**info,'durationSeconds':info['frames']/info['rate'],'clips':len(p['clips']),'peakPCM16':max(abs(v) for v in actual),'maxQuantisationErrorLSB':max_error,'sampleToleranceLSB':.5001}


def artifacts(directory):
    return [{'file':str(directory/n),'kind':kind,'sha256':digest(directory,n)} for n,kind in [('audio.wav','file'),('audio-summary.json','text')]]


def evidence_names(p):
    return {'authored.json','plan.json','captures.json',*[f'captured-{i}.wav' for i in range(len(p['clips']))],*[f'clip-{i}.wav' for i in range(len(p['clips']))],
        *[s+x for s in commands('',p) for x in ('-launcher.py','-inputs.json','-submission.json','.stdout','.stderr')]}


def run(document,directory,*,executable=None,timeout=300):
    p=plan(document);executable=executable or os.environ.get('SCHEMAXIS_SOX') or shutil.which('sox')
    if not executable or not Path(executable).is_absolute() or not os.access(executable,os.X_OK): fail('INTERPRETER_NOT_FOUND','configure an absolute SoX 14.4.2 executable')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=3600: fail('INVALID_ARGUMENT','timeout must be finite in (0,3600]')
    deadline=time.monotonic()+timeout;directory=Path(directory).absolute()
    if directory.exists() or directory.is_symlink(): fail('OUTPUT_EXISTS','select a fresh output directory',str(directory))
    directory.mkdir(parents=True);atomic_json(directory/'authored.json',document);atomic_json(directory/'plan.json',p)
    atomic_json(directory/'result.json',{'status':'incomplete','verified':False})
    try:
        loaded=inputs(p,lambda i,c:bounded(c['source'],'INVALID_AUDIO_SOURCE'));captures=[]
        for i,(data,info,_) in enumerate(loaded):
            (directory/f'captured-{i}.wav').write_bytes(data);captures.append({'source':p['clips'][i]['source'],'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'info':info})
        del loaded
        atomic_json(directory/'captures.json',captures)
        for stage,command in commands(str(executable),p).items():
            path=directory/(stage+'-launcher.py');path.write_text(launcher(directory,stage,command,p))
            execute([sys.executable,str(path)],directory,stage,deadline-time.monotonic(),{'LANG':'C.UTF-8','OMP_NUM_THREADS':'1','SOX_OPTS':''})
            if stage=='version': qualified_runtime(directory,str(executable))
        atomic_json(directory/'audio-summary.json',inspect(directory,p));runtime=qualified_runtime(directory,str(executable))
        atomic_json(directory/'verification.json',{'executable':str(executable),'runtime':runtime,'artifacts':artifacts(directory),'evidence':{n:digest(directory,n) for n in evidence_names(p)}})
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
        if read(directory,'plan.json')!=p: fail('VERIFICATION_FAILED','effective audio plan differs')
        if require_result and read(directory,'result.json').get('status')!='succeeded': fail('INCOMPLETE_EXECUTION','audio did not complete')
        captures=[]
        for i,c in enumerate(p['clips']):
            data=bounded(directory/f'captured-{i}.wav');info,_=pcm(data,'VERIFICATION_FAILED')
            captures.append({'source':c['source'],'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'info':info})
        if read(directory,'captures.json')!=captures: fail('VERIFICATION_FAILED','WAV source/capture binding differs')
        executable=receipt['executable']
        if not isinstance(executable,str) or not Path(executable).is_absolute(): fail('VERIFICATION_FAILED','native executable identity must be absolute')
        for stage,command in commands(executable,p).items():
            submission=read(directory,stage+'-submission.json');interpreter=submission.get('interpreter',{}).get('executable');path=directory/(stage+'-launcher.py')
            if not isinstance(interpreter,str) or not Path(interpreter).is_absolute() or submission.get('nativeCommand')!=[interpreter,str(path)] or type(submission.get('exitCode')) is not int or submission['exitCode']!=0: fail('VERIFICATION_FAILED','native command/completion differs',stage)
            if bounded(path).decode()!=launcher(directory,stage,command,p): fail('VERIFICATION_FAILED','trusted native launcher differs',stage)
            if read(directory,stage+'-inputs.json')!={str(directory/n):digest(directory,n) for n in stage_inputs(stage,p)}: fail('VERIFICATION_FAILED','native audio input binding differs',stage)
        runtime=qualified_runtime(directory,executable,'VERIFICATION_FAILED')
        if receipt['runtime']!=runtime: fail('VERIFICATION_FAILED','require qualified SoX v14.4.2 runtime identity')
        summary=inspect(directory,p)
        if read(directory,'audio-summary.json')!=summary: fail('VERIFICATION_FAILED','audio summary differs')
        if receipt['artifacts']!=artifacts(directory): fail('VERIFICATION_FAILED','audio publication membership/digest differs')
        if set(receipt['evidence'])!=evidence_names(p): fail('VERIFICATION_FAILED','native evidence membership differs')
        for n in evidence_names(p):
            if digest(directory,n)!=receipt['evidence'][n]: fail('VERIFICATION_FAILED','retained native evidence differs',n)
        return {'verified':True,'artifacts':2,'runtime':runtime,**summary}
    except (OSError,ValueError,KeyError,TypeError,IndexError,AttributeError) as error: fail('VERIFICATION_FAILED','invalid retained audio evidence: '+str(error))


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
