# Copyright (C) 2026 David L F Gaden
"""Bounded image and captured video sources with full native RGB readback, and verified AAC audio extraction."""
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys
import time

from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.errors import fail, keys
from schemaxis.dispatch import cancellation_requested, execution_deadline
from schemaxis.native_command import execute
from schemaxis.png import decode, MAX_BYTES
from . import video

PATH = {'type': 'string', 'minLength': 1, 'maxLength': 4096, 'required': True}
COMMON = {'fps': {'type': 'integer', 'minimum': 1, 'maximum': 120, 'default': 25},
          'codec': {'type': 'enum', 'values': ['h264', 'ffv1'], 'default': 'h264'},
          'threads': {'type': 'integer', 'minimum': 1, 'maximum': 16, 'default': 1}}
REVIEW_STATUS = ['machineDraft', 'declaredHumanReviewed']
DECLARATIONS = {op: {'native': 'ffmpeg', 'kinds': ['video'], 'inputs': {},
    'options': {k: {'value': v} for k, v in {**(COMMON if op not in ('muxReview', 'extractAudio', 'encodeAudio') else {'threads': COMMON['threads']}), **options}.items()}}
    for op, options in {
        'encodeFrames': {'files': {'type': 'array', 'items': {k:v for k,v in PATH.items() if k != 'required'},
                                   'minItems': 1, 'maxItems': 600, 'required': True}},
        'encodeSheet': {'file': PATH, 'metadata': PATH},
        'encodeVideo': {'file': PATH,
                        'startFrame': {'type': 'integer', 'minimum': 0, 'maximum': 599, 'default': 0},
                        'endFrame': {'type': 'integer', 'minimum': 1, 'maximum': 600, 'required': True}},
        'muxReview': {'video': PATH, 'audio': PATH, 'captions': PATH,
                      'captionStatus': {'type': 'enum', 'values': REVIEW_STATUS, 'default': 'machineDraft'}},
        'extractAudio': {'file': PATH, 'streamIndex': {'type': 'integer', 'minimum': 0, 'maximum': 15, 'required': True}},
        'encodeAudio': {'file': PATH, 'bitrateKbps': {'type': 'enum', 'values': [64, 96, 128, 192], 'required': True},
                        'maxBytes': {'type': 'integer', 'minimum': 1, 'maximum': 32 * 1024 * 1024, 'required': True},
                        'maxMeanPCMError': {'type': 'number', 'minimum': 0, 'maximum': 65535, 'required': True}},
    }.items()}
MAX_RGB = 192 * 1024 * 1024
H264_COLOUR = ['-colorspace', 'smpte170m', '-color_range', 'tv']
DELIVERABLE = {
    'width': {'type': 'integer', 'minimum': 1, 'maximum': 4096},
    'height': {'type': 'integer', 'minimum': 1, 'maximum': 4096},
    'frames': {'type': 'integer', 'minimum': 1, 'maximum': 600},
    'durationSeconds': {'type': 'number', 'minimum': 1/120, 'maximum': 600},
    'durationToleranceSeconds': {'type': 'number', 'minimum': 0, 'maximum': 1},
    'maxBytes': {'type': 'integer', 'minimum': 1, 'maximum': 1024*1024*1024},
    'maxMeanRGBError': {'type': 'number', 'minimum': 0, 'maximum': 16},
}


def deliverable_policy(value):
    policy = validate_arguments(DELIVERABLE, value, location='$.deliverable')
    if not policy or set(policy) == {'durationToleranceSeconds'}:
        fail('INVALID_ARGUMENT', 'declare at least one deliverable requirement', '$.deliverable')
    if 'durationToleranceSeconds' in policy and 'durationSeconds' not in policy:
        fail('INVALID_ARGUMENT', 'duration tolerance requires a target duration', '$.deliverable.durationToleranceSeconds')
    if 'durationSeconds' in policy:
        policy.setdefault('durationToleranceSeconds', 0.002)
    return policy


def plan(document):
    keys(document, ('version', 'nodes', 'deliverable'), '$')
    if document.get('version') != 'schemaxis.ffmpeg/1': fail('UNSUPPORTED_VERSION', 'expected schemaxis.ffmpeg/1')
    nodes = document.get('nodes')
    if not isinstance(nodes, list) or len(nodes) != 1: fail('INVALID_DOCUMENT', 'declare exactly one video publication')
    node = nodes[0]
    keys(node, ('id', 'filter', 'options'), '$.nodes[0]')
    from schemaxis.pipeline import name
    identity = name(node.get('id'), '$.nodes[0].id')
    op = node.get('filter')
    if not isinstance(op, str) or op not in DECLARATIONS: fail('UNKNOWN_FILTER', 'expected encodeFrames, encodeSheet, encodeVideo, muxReview, extractAudio or encodeAudio')
    options = validate_arguments({k:v['value'] for k,v in DECLARATIONS[op]['options'].items()}, node.get('options', {}), location='$.nodes[0].options')
    if op == 'extractAudio':
        from . import audio
        return audio.plan(document, identity, options)
    if op == 'encodeAudio':
        from . import publish_audio
        return publish_audio.plan(document, identity, options)
    paths = video.source_paths({'filter': op, 'options': options})
    if op == 'encodeVideo':
        if options['startFrame'] >= options['endFrame']:
            fail('INVALID_FRAME_RANGE', 'startFrame must be less than exclusive endFrame', '$.nodes[0].options.endFrame')
        if Path(options['file']).suffix.lower() not in ('.mp4', '.mkv'):
            fail('UNSUPPORTED_VIDEO', 'use an absolute .mp4 or .mkv source path', '$.nodes[0].options.file')
    if any('\0' in p for p in paths): fail('INVALID_RESOURCE', 'input paths must not contain NUL')
    if any(not Path(p).is_absolute() for p in paths): fail('INVALID_RESOURCE', 'input paths must be absolute')
    if op == 'muxReview':
        for name, suffix, code in (('video', '.mkv', 'UNSUPPORTED_VIDEO'), ('audio', '.wav', 'UNSUPPORTED_AUDIO'),
                                   ('captions', '.srt', 'UNSUPPORTED_CAPTIONS')):
            if Path(options[name]).suffix.lower() != suffix:
                fail(code, f'use an absolute {suffix} path for {name}', f'$.nodes[0].options.{name}')
        if 'deliverable' in document:
            fail('INVALID_ARGUMENT', 'muxReview verifies its own alignment policy; deliverable is not accepted', '$.deliverable')
        from . import review
        return {'version': 'schemaxis.ffmpeg.plan/1', 'nodes': [{'id': identity, 'filter': op, 'options': options}],
                'output': review.OUTPUT, 'losses': review.LOSSES, 'policy': review.POLICY}
    prepared = {'version': 'schemaxis.ffmpeg.plan/1', 'nodes': [{'id': identity, 'filter': op, 'options': options}],
            'output': 'video.mp4' if options['codec'] == 'h264' else 'video.mkv',
            'losses': (['source decoded presentation RGB; fps retimes selected frames'] if op == 'encodeVideo'
                       else ['alpha composited on black']) + ['no audio', 'constant frame rate'] +
                      (['H.264 lossy RGB to YUV420 conversion; maximum per-frame mean RGB error 16/255'] if options['codec']=='h264' else [])}
    if 'deliverable' in document:
        prepared['deliverable'] = deliverable_policy(document['deliverable'])
    return prepared


def schema():
    from schemaxis.schema import DRAFT, object_schema, argument_schema, NAME
    variants = [object_schema({'id': NAME, 'filter': {'const': op}, 'options': object_schema(
        {k:argument_schema(v['value']) for k,v in decl['options'].items()},
        [k for k,v in decl['options'].items() if v['value'].get('required')])}, ['id','filter','options']) for op,decl in DECLARATIONS.items()]
    return {'$schema': DRAFT, **object_schema({'version': {'const': 'schemaxis.ffmpeg/1'},
        'nodes': {'type':'array','minItems':1,'maxItems':1,'items':{'oneOf':variants}},
        'deliverable': {**object_schema({k: argument_schema(v) for k,v in DELIVERABLE.items()}),
            'minProperties': 1, 'dependentRequired': {'durationToleranceSeconds': ['durationSeconds']}}}, ['version','nodes'])}


def assess_deliverable(policy, width, height, count, fps, byte_count, errors, duration_seconds=None):
    """Replayable media acceptance; native correctness is checked separately."""
    observed = {'width': width, 'height': height, 'frames': count,
                'durationSeconds': count/fps if duration_seconds is None else duration_seconds,
                'framesPerSecond': fps, 'bytes': byte_count,
                'maximumMeanRGBError': max(errors)}
    checks = []
    actions = {'width': 'Render or supply source PNGs at the requested width.',
               'height': 'Render or supply source PNGs at the requested height.',
               'frames': 'Correct the ordered frame list or sprite durations.',
               'durationSeconds': 'Adjust fps or frame count to match the requested duration.',
               'maxBytes': 'Use H.264, reduce source dimensions/frame count, or revise the byte budget.',
               'maxMeanRGBError': 'Use FFV1 for lossless RGB or revise the declared error budget.'}
    for key in ('width', 'height', 'frames', 'durationSeconds', 'maxBytes', 'maxMeanRGBError'):
        if key not in policy:
            continue
        actual = observed[{'maxBytes': 'bytes', 'maxMeanRGBError': 'maximumMeanRGBError'}.get(key, key)]
        target = policy[key]
        if key == 'durationSeconds':
            passed = math.isclose(actual, target, rel_tol=0,
                                  abs_tol=policy['durationToleranceSeconds'])
        elif key.startswith('max'):
            passed = actual <= target
        else:
            passed = actual == target
        check = {'requirement': key, 'expected': target, 'observed': actual,
                 'passed': passed, 'nextAction': 'Accept this requirement.' if passed else actions[key]}
        if key == 'durationSeconds':
            check['absoluteToleranceSeconds'] = policy['durationToleranceSeconds']
        checks.append(check)
    return {'accepted': all(check['passed'] for check in checks),
            'observed': observed, 'checks': checks}


def native_commands(executable, directory, prepared, width, height):
    """One trusted command recipe shared by execution and offline evidence checks."""
    o = prepared['nodes'][0]['options']; output = directory/prepared['output']
    prefix = [executable, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-filter_threads', '1']
    encode = prefix + ['-f', 'rawvideo', '-pixel_format', 'rgb24', '-video_size', f'{width}x{height}',
        '-framerate', str(o['fps']), '-i', str(directory/'frames.rgb'), '-an', '-threads', str(o['threads'])]
    # Explicit FFV1 version 1 uses a single whole-frame slice for both tiny and
    # larger images. Version 3 rejects a forced single slice on some dimensions;
    # its automatic slicing has also lost pixels on tiny images in native tests.
    # H.264 output declares the BT.601 limited-range YUV conversion swscale applies,
    # so players need not guess a matrix from the frame size.
    encode += (['-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p', *H264_COLOUR, '-movflags', '+faststart']
               if o['codec'] == 'h264' else ['-c:v', 'ffv1', '-level', '1', '-pix_fmt', 'bgr0'])
    return {
        'encode': encode + [str(output)],
        'decode': prefix + ['-threads', str(o['threads']), '-i', str(output), '-map', '0:v:0', '-an',
            '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'rgb24', str(directory/'decoded.rgb')],
        'probe': [str(Path(executable).with_name('ffprobe')), '-v', 'error', '-count_frames',
            '-show_streams', '-show_format', '-of', 'json', str(output)],
        'version': [executable, '-version'],
    }


def source_bytes(path):
    """Reject devices/FIFOs before opening; recheck the descriptor against races."""
    try:
        info=Path(path).stat()
        if not stat.S_ISREG(info.st_mode):
            fail('INVALID_RESOURCE', 'input must be a regular file', str(path))
        if info.st_size>MAX_BYTES:fail('RESOURCE_LIMIT','input byte budget exceeded',str(path))
        descriptor=os.open(path,os.O_RDONLY|getattr(os,'O_NONBLOCK',0))
        with os.fdopen(descriptor,'rb') as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):fail('INVALID_RESOURCE','input must be a regular file',str(path))
            if info.st_size>MAX_BYTES:fail('RESOURCE_LIMIT','input byte budget exceeded',str(path))
            data=stream.read(MAX_BYTES+1)
        if len(data)>MAX_BYTES:fail('RESOURCE_LIMIT','input byte budget exceeded',str(path))
        return data
    except (OSError,ValueError) as error:fail('RESOURCE_NOT_FOUND',str(error),str(path))


def reusableInputs(document):
    node = plan(document)['nodes'][0]; o=node['options']
    if node['filter']=='extractAudio':
        from . import audio
        return audio.reusable(o)
    if node['filter']=='encodeAudio':
        from . import publish_audio
        return publish_audio.reusable(o)
    paths = video.source_paths(node)
    total=0;digests={}
    for path in paths:
        data=source_bytes(path);total+=len(data)
        if total>MAX_RGB:fail('RESOURCE_LIMIT','input byte budget exceeded',path)
        digests[path]=hashlib.sha256(data).hexdigest()
    return digests


def resources(document, spec, identity):
    from schemaxis.parallel import provisional
    threads = plan(provisional(document))['nodes'][0]['options']['threads']
    if spec.get('threads', threads) != threads: fail('INVALID_EXECUTION', 'allocation must match encoder threads', identity)
    return {'threads':threads}


def read_sources(directory, prepared, capture=False):
    node=prepared['nodes'][0]; o=node['options']
    paths = video.source_paths(node)
    records=[]; payloads=[]
    total=0
    for index,path in enumerate(paths):
        target=directory/f'input-{index:04d}'
        data=source_bytes(Path(path) if capture else target)
        total+=len(data)
        if len(data)>MAX_BYTES or total>MAX_RGB: fail('RESOURCE_LIMIT','input byte budget exceeded',path)
        if capture: target.write_bytes(data)
        records.append({'file':path,'retained':target.name,'sha256':hashlib.sha256(data).hexdigest()})
        payloads.append(data)
    return records,payloads


def matte(data):
    """RGBA over black, rounded: the exact RGB bytes every encoder input and readback comparison is judged against."""
    result=bytearray(len(data)//4*3)
    for i in range(0,len(data),4):
        a=data[i+3]
        result[i//4*3:i//4*3+3]=bytes((data[i+j]*a+127)//255 for j in range(3))
    return bytes(result)


def frames(prepared, payloads, directory=None):
    node=prepared['nodes'][0]; o=node['options']; output=[]
    # encodeFrames decodes and mattes each distinct held PNG once per call. The key is the held bytes themselves, so a hit is a
    # full byte comparison, never a path, stat or digest alone; the table dies with the call and never spans run, verify or fresh.
    prepared_frames={}
    if node['filter']=='encodeVideo':
        if directory is None: fail('VERIFICATION_FAILED', 'captured native video readback is required')
        return video.read(directory, prepared)
    if node['filter']=='encodeFrames':
        size=None
        for data in payloads:
            key=data if type(data) is bytes else bytes(data)
            held=prepared_frames.get(key)
            if held is None: w,h,pixels=decode(data)
            else: w,h,pixels=held
            if size is not None and size!=(w,h): fail('INVALID_IMAGE','all sequence frames must have equal dimensions')
            size=(w,h)
            if (len(output)+1)*w*h*4>MAX_RGB: fail('RESOURCE_LIMIT','decoded frame budget exceeded')
            if held is None:
                pixels=matte(pixels)
                prepared_frames[key]=(w,h,pixels)
            output.append(pixels)
    else:
        w,h,pixels=decode(payloads[0])
        try: metadata=json.loads(payloads[1])
        except (ValueError,UnicodeError): fail('INVALID_RESOURCE','invalid sprite sheet JSON')
        keys(metadata,('version','width','height','frames','tags'),'metadata')
        if metadata.get('version')!='schemaxis.aseprite.sheet/1' or metadata.get('width')!=w or metadata.get('height')!=h:
            fail('INVALID_RESOURCE','sprite sheet dimensions/version differ')
        entries=metadata.get('frames')
        if not isinstance(entries,list) or not 1<=len(entries)<=600: fail('INVALID_RESOURCE','invalid sprite frame list')
        size=None
        for entry in entries:
            keys(entry,('x','y','width','height','durationMS'),'frame')
            if set(entry)!={'x','y','width','height','durationMS'} or any(type(v)is not int for v in entry.values()):
                fail('INVALID_RESOURCE','sprite frame needs integer rectangle and duration')
            x,y,fw,fh,d=(entry[k] for k in ('x','y','width','height','durationMS'))
            if min(x,y)<0 or min(fw,fh,d)<=0 or x+fw>w or y+fh>h: fail('INVALID_RESOURCE','sprite frame exceeds sheet')
            if d*o['fps']%1000: fail('UNSUPPORTED_TIMING','frame durations must be exact multiples of 1000/fps milliseconds')
            count=d*o['fps']//1000
            if count+len(output)>600 or (count+len(output))*fw*fh*4>MAX_RGB: fail('RESOURCE_LIMIT','video exceeds 600 frames')
            if size is not None and size!=(fw,fh): fail('INVALID_IMAGE','sprite frames need equal dimensions')
            size=(fw,fh)
            frame=b''.join(pixels[((y+row)*w+x)*4:((y+row)*w+x+fw)*4] for row in range(fh))
            output.extend([frame]*count)
    w,h=size
    if len(output)*w*h*3>MAX_RGB: fail('RESOURCE_LIMIT','decoded video exceeds 192 MiB')
    if o['codec']=='h264' and (w%2 or h%2): fail('INVALID_IMAGE','H.264 YUV420 requires even frame dimensions')
    return w,h,output if node['filter']=='encodeFrames' else [matte(frame) for frame in output]


def compare(expected, raw, codec):
    if len(raw)!=sum(map(len,expected)): fail('VERIFICATION_FAILED','decoded frame count or dimensions differ')
    errors=[]; offset=0
    for frame in expected:
        actual=raw[offset:offset+len(frame)];offset+=len(frame)
        error=sum(abs(a-b) for a,b in zip(frame,actual))/len(frame)
        if error>(0 if codec=='ffv1' else 16): fail('VERIFICATION_FAILED','decoded frame differs from requested pixels', meanError=error)
        errors.append(error)
    return errors


def readback_launcher(directory, prepared, stage, command):
    """Adaptor-owned stage input binding, executed under the shared owned PID."""
    source_stage = stage.startswith('source-')
    output=str(directory/('input-0000' if source_stage else prepared['output']))
    limits = ('import resource\nresource.setrlimit(resource.RLIMIT_AS, (2147483648,2147483648))\n'
              + f'resource.setrlimit(resource.RLIMIT_FSIZE, ({video.MAX_PROBE if stage == "source-probe" else MAX_RGB + 4*1024*1024},)*2)\n'
              if source_stage and os.name == 'posix' else '')
    return ('import hashlib, json, os, stat\nfrom pathlib import Path\n' + limits
        +f'path=Path({output!r})\ncommand={command!r}\n'
        +'if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode): raise ValueError("native input is not regular")\n'
        +f'if path.stat().st_size>{1024*1024*1024}: raise ValueError("native input byte budget exceeded")\n'
        +'digest=hashlib.sha256()\n'
        +'with path.open("rb") as stream:\n'
        +'    for block in iter(lambda:stream.read(1048576), b""): digest.update(block)\n'
        +f'Path({str(directory/(stage+"-inputs.json"))!r}).write_text(json.dumps({{str(path):digest.hexdigest()}},sort_keys=True))\n'
        +'os.execvpe(command[0],command,os.environ)\n')


def readback_evidence(directory,prepared,commands,submissions,stages=('decode','probe'),load=json.loads):
    evidence={}
    for stage in stages:
        launcher=directory/(stage+'-launcher.py');binding=directory/(stage+'-inputs.json')
        for path in (launcher,binding):
            if path.is_symlink() or not path.is_file() or path.stat().st_size>1024*1024:
                fail('VERIFICATION_FAILED','required bounded native readback evidence is absent',stage)
        if launcher.read_text()!=readback_launcher(directory,prepared,stage,commands[stage]):
            fail('VERIFICATION_FAILED','native readback launcher differs',stage)
        record=submissions[stage].get('interpreter')
        interpreter=record.get('executable') if isinstance(record,dict) else None
        if not isinstance(interpreter,str) or not Path(interpreter).is_absolute() or submissions[stage]['nativeCommand']!=[interpreter,str(launcher)]:
            fail('VERIFICATION_FAILED','native readback wrapper differs',stage)
        bound_input = directory/('input-0000' if stage.startswith('source-') else prepared['output'])
        if load(binding.read_text())!={str(bound_input):file_digest(bound_input)}:
            fail('VERIFICATION_FAILED','native readback consumed different encoded bytes',stage)
        output_name = {'decode': 'decoded.rgb', 'probe': 'probe.stdout',
                       'source-decode': 'source-decoded.rgb', 'source-probe': 'source-probe.stdout'}[stage]
        evidence[stage]={'launcherSHA256':file_digest(launcher),'inputBindingSHA256':file_digest(binding),
            'outputSHA256':file_digest(directory/output_name)}
    return evidence


def trusted_runtime(prepared, executable):
    """The one FFmpeg and sibling ffprobe a run may launch: explicit, stored/invocation configuration, then
    FFMPEG_EXECUTABLE, exactly as verification resolves them. PATH is never consulted."""
    from . import fresh, review
    resolve = review.trusted if prepared['nodes'][0]['filter']=='muxReview' else fresh.trusted
    try: return resolve(executable)
    except SchemaxisError as error:
        fault=error.fault
        recovery=(fault.recovery or '').replace('Pass executable= to verify','Pass executable= (--executable or --ffmpeg) to run or verify',1)
        raise SchemaxisError(Fault(fault.code,fault.message,fault.location,fault.phase,fault.retryable,fault.to_dict()['observed'],recovery)) from None


def run(document,directory,*,executable=None,timeout=300):
    prepared=plan(document); o=prepared['nodes'][0]['options']
    if prepared['nodes'][0]['filter']=='extractAudio':
        from . import audio
        return audio.run(document,prepared,directory,executable,timeout)
    if prepared['nodes'][0]['filter']=='encodeAudio':
        from . import publish_audio
        return publish_audio.run(document,prepared,directory,executable,timeout)
    # Refuse before the output directory or any native process exists; PATH never supplies the runtime.
    executable=trusted_runtime(prepared,executable)['ffmpeg']
    if type(timeout)not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=3600: fail('INVALID_ARGUMENT','timeout must be in (0,3600]')
    directory=Path(directory).absolute()
    if directory.exists() or directory.is_symlink():fail('OUTPUT_EXISTS','choose a fresh directory',str(directory))
    directory.mkdir(parents=True)
    atomic_json(directory/'authored.json',document);atomic_json(directory/'plan.json',prepared)
    atomic_json(directory/'result.json',{'status':'incomplete','verified':False})
    deadline=time.monotonic()+timeout
    try:
        if prepared['nodes'][0]['filter']=='muxReview':
            from . import review
            return review.run(prepared,directory,str(executable),deadline)
        sources,payloads=read_sources(directory,prepared,True)
        source_commands = {}
        if prepared['nodes'][0]['filter']=='encodeVideo':
            video.check_source(payloads[0],o['file'])
            source_commands = video.commands(str(executable), directory, prepared)
            for stage in ('source-probe', 'source-decode'):
                launcher=directory/(stage+'-launcher.py')
                launcher.write_text(readback_launcher(directory,prepared,stage,source_commands[stage]))
                execute([sys.executable,str(launcher)],directory,stage,deadline-time.monotonic())
                video.check_diagnostics(directory,stage)
                if stage == 'source-probe':
                    if (directory/'source-probe.stdout').stat().st_size>video.MAX_PROBE:
                        fail('RESOURCE_LIMIT','source probe exceeded byte budget')
                    video.inspect(json.loads((directory/'source-probe.stdout').read_text()))
        w,h,pixels=frames(prepared,payloads,directory)
        (directory/'frames.rgb').write_bytes(b''.join(pixels))
        output=directory/prepared['output']
        commands=native_commands(str(executable),directory,prepared,w,h)
        execute(commands['encode'],directory,'encode',deadline-time.monotonic())
        # Fresh native decode: verify actual pixels, order and count, not container existence.
        for stage in ('decode','probe'):
            launcher=directory/(stage+'-launcher.py')
            launcher.write_text(readback_launcher(directory,prepared,stage,commands[stage]))
            execute([sys.executable,str(launcher)],directory,stage,deadline-time.monotonic())
        probe_data=json.loads((directory/'probe.stdout').read_text())
        validate_probe(probe_data,w,h,len(pixels),o,tagged=True)
        decoded=directory/'decoded.rgb'
        if decoded.stat().st_size>MAX_RGB:fail('RESOURCE_LIMIT','native decoder exceeded byte budget')
        errors=compare(pixels,decoded.read_bytes(),o['codec'])
        execute(commands['version'],directory,'version',deadline-time.monotonic())
        receipt={'artifacts':[{'file':str(output),'kind':'video','sha256':file_digest(output), 'frames':len(pixels),
            'duration':len(pixels)/o['fps'], 'dimensions':[w,h]}],
            'sources':sources,'width':w,'height':h,'frames':len(pixels),'fps':o['fps'],
            'duration':len(pixels)/o['fps'],'codec':o['codec'],'meanErrors':errors,
            'decodedSHA256':file_digest(decoded),'framesSHA256':file_digest(directory/'frames.rgb'),
            'runtime':(directory/'version.stdout').read_text().splitlines()[0],'losses':prepared['losses']}
        submissions={stage:json.loads((directory/(stage+'-submission.json')).read_text()) for stage in ('decode','probe')}
        receipt['nativeReadback']=readback_evidence(directory,prepared,commands,submissions)
        if source_commands:
            source_submissions={stage:json.loads((directory/(stage+'-submission.json')).read_text()) for stage in source_commands}
            receipt['sourceReadback']=readback_evidence(directory,prepared,source_commands,source_submissions,tuple(source_commands))
        if 'deliverable' in prepared:
            receipt['deliverable']=assess_deliverable(prepared['deliverable'],w,h,len(pixels),o['fps'],
                output.stat().st_size,errors,float(probe_data['format']['duration']))
        atomic_json(directory/'verification.json',receipt)
        result={'status':'succeeded','verified':True,'artifacts':1,'video':str(output)}
        if 'deliverable' in receipt:result['deliverable']=receipt['deliverable']
        verify(directory, require_result=False, executable=str(executable), deadline=deadline)
        if cancellation_requested():fail('RUNNER_CANCELLED','video publication cancelled')
        if time.monotonic()>=deadline:fail('RUNNER_TIMED_OUT','video verification exhausted the total timeout')
        atomic_json(directory/'result.json',result)
        return result
    except Exception as error:
        if not isinstance(error,SchemaxisError):
            try: fail('NATIVE_EXECUTION_FAILED',str(error),str(directory))
            except SchemaxisError as wrapped: error=wrapped
        atomic_json(directory/'result.json',{'status':'failed','verified':False,'fault':error.fault.to_dict() if isinstance(error,SchemaxisError) else {'message':str(error)}})
        raise error


def verify(directory, require_result=True, *, executable=None, deadline=None):
    """``muxReview`` and the three single-video operations all decode the published bytes again with a trusted FFmpeg
    and its sibling ffprobe, taken from ``executable``, stored/invocation configuration or ``FFMPEG_EXECUTABLE`` (never PATH,
    receipts or submissions). ``run`` resolves the same choice before creating its output directory. See review.verify and fresh.observe; retained readbacks are strict consistency diagnostics."""
    from . import review
    directory=Path(directory).absolute()
    try:
        with execution_deadline(review.VERIFY_TIMEOUT):
            def read(name):
                path=directory/name
                if path.is_symlink() or not path.is_file():fail('VERIFICATION_FAILED','required regular file is absent',name)
                value=review.strict_json(review.bounded_bytes(path,video.MAX_PROBE,name),name)
                if not isinstance(value,dict):fail('VERIFICATION_FAILED','expected an evidence object',name)
                return value
            prepared=plan(read('authored.json'))
            if prepared['nodes'][0]['filter']=='muxReview':
                return review.verify(directory,prepared,require_result=require_result,executable=executable,deadline=deadline)
            if prepared['nodes'][0]['filter']=='extractAudio':
                from . import audio
                return audio.verify(directory,prepared,require_result=require_result,executable=executable,deadline=deadline)
            if prepared['nodes'][0]['filter']=='encodeAudio':
                from . import publish_audio
                return publish_audio.verify(directory,prepared,require_result=require_result,executable=executable,deadline=deadline)
            return verify_single(directory,prepared,read,require_result,executable,deadline)
    except (OSError,ValueError,KeyError,IndexError,TypeError,UnicodeError,RecursionError) as error:
        fail('VERIFICATION_FAILED','missing or invalid video evidence: %s %s'%(type(error).__name__,str(error)[:80]))


def verify_single(directory,prepared,read,require_result,executable,deadline):
    from . import fresh, review
    receipt=read('verification.json');result=read('result.json')
    if require_result and (result.get('status')!='succeeded' or result.get('verified')is not True):fail('INCOMPLETE_EXECUTION','video did not complete')
    if not review.same_json(read('plan.json'),prepared):fail('VERIFICATION_FAILED','plan differs')
    paths=fresh.trusted(executable)
    required=['authored.json','plan.json','result.json','verification.json','frames.rgb','decoded.rgb',
              'probe.stdout','version.stdout',prepared['output']]
    node=prepared['nodes'][0];options=node['options']
    count=len(video.source_paths(node))
    if node['filter']=='encodeVideo':
        required += ['source-probe.stdout','source-decoded.rgb']
    required += [f'input-{i:04d}' for i in range(count)]
    for name in required:
        path=directory/name
        if path.is_symlink() or not path.is_file():fail('VERIFICATION_FAILED','required regular file is absent',name)
    output=directory/prepared['output']
    published=review.bounded_bytes(output,fresh.MAX_PUBLICATION,prepared['output'])
    published_digest=hashlib.sha256(published).hexdigest()
    # The captured sources are held once; the retained and the fresh pass both judge these bytes.
    sources,payloads=read_sources(directory,prepared)
    if node['filter']=='encodeVideo':
        review.strict_json(review.bounded_bytes(directory/'source-probe.stdout',video.MAX_PROBE,'source-probe.stdout'),'source-probe.stdout')
    w,h,pixels=frames(prepared,payloads,directory)
    decoded=directory/'decoded.rgb'
    if decoded.stat().st_size>MAX_RGB:fail('VERIFICATION_FAILED','decoded video exceeds bound')
    errors=compare(pixels,decoded.read_bytes(),options['codec'])
    probe_data=read('probe.stdout')
    runtime=(directory/'version.stdout').read_text().splitlines()[0]
    expected={'artifacts':[{'file':str(output),'kind':'video','sha256':published_digest,'frames':len(pixels),
        'duration':len(pixels)/options['fps'],'dimensions':[w,h]}],
        'sources':sources,'width':w,'height':h,'frames':len(pixels),'fps':options['fps'],'duration':len(pixels)/options['fps'],
        'codec':options['codec'],'meanErrors':errors,'decodedSHA256':file_digest(decoded),
        'framesSHA256':hashlib.sha256(b''.join(pixels)).hexdigest(),'runtime':runtime,'losses':prepared['losses']}
    if 'deliverable' in prepared:
        expected['deliverable']=assess_deliverable(prepared['deliverable'],w,h,len(pixels),options['fps'],
            len(published),errors,float(probe_data['format']['duration']))
    stages=['encode','decode','probe','version']
    if node['filter']=='encodeVideo': stages += ['source-probe','source-decode']
    submissions={stage:read(stage+'-submission.json') for stage in stages}
    command=submissions['encode'].get('nativeCommand')
    if not isinstance(command,list) or not command or not isinstance(command[0],str) or not Path(command[0]).is_absolute():
        fail('VERIFICATION_FAILED','missing absolute FFmpeg command evidence','encode')
    # Recorded commands are inert data that only reconstruct the retained command text; they are never executed.
    commands=native_commands(command[0],directory,prepared,w,h)
    if node['filter']=='encodeVideo':
        commands.update(video.commands(command[0],directory,prepared))
    # Retained runs from before explicit colour tagging used the untagged recipe.
    tagged=submissions['encode'].get('nativeCommand')==commands['encode']
    validate_probe(probe_data,w,h,len(pixels),options,tagged=tagged)
    for stage,submission in submissions.items():
        accepted_commands=[commands[stage]]
        if ('nativeReadback' in receipt and stage in ('decode','probe')) or stage.startswith('source-'):
            record=submission.get('interpreter')
            interpreter=record.get('executable') if isinstance(record,dict) else None
            accepted_commands=[[interpreter,str(directory/(stage+'-launcher.py'))]]
        if stage=='encode' and options['codec']=='ffv1':
            # Exact historical recipe remains valid evidence for runs whose version-3 encoding and full decode succeeded.
            legacy=list(commands[stage]);index=legacy.index('-level')
            legacy[index:index+2]=['-level','3','-slices','1'];accepted_commands.append(legacy)
        if stage=='encode' and options['codec']=='h264':
            legacy=list(commands[stage]);index=legacy.index('-colorspace')
            del legacy[index:index+4];accepted_commands.append(legacy)
        if stage=='decode' and 'nativeReadback' not in receipt:
            # Retained runs from before FFmpeg removed -vsync; new execution always uses -fps_mode.
            legacy=list(commands[stage]);index=legacy.index('-fps_mode')
            legacy[index:index+2]=['-vsync','0'];accepted_commands.append(legacy)
        if type(submission.get('exitCode'))is not int or submission['exitCode']!=0 or submission.get('nativeCommand')not in accepted_commands:
            fail('VERIFICATION_FAILED','native stage command or completion differs',stage)
    if 'nativeReadback' in receipt:
        expected['nativeReadback']=readback_evidence(directory,prepared,commands,submissions,load=review.strict_text)
    if node['filter']=='encodeVideo':
        expected['sourceReadback']=readback_evidence(directory,prepared,commands,submissions,('source-probe','source-decode'),review.strict_text)
    if not review.same_json(receipt,expected) or file_digest(directory/'frames.rgb')!=expected['framesSHA256']:
        fail('VERIFICATION_FAILED','video evidence differs')
    retained={'runtime':runtime,'width':w,'height':h,'frames':len(pixels),'fps':options['fps'],'codec':options['codec'],
              'publication':published_digest,'duration':float(probe_data['format']['duration']),'errors':errors,'decodedSHA256':expected['decodedSHA256'],'framesSHA256':expected['framesSHA256']}
    if node['filter']=='encodeVideo':retained['sourceDecodedSHA256']=file_digest(directory/'source-decoded.rgb')
    # Fresh decision: the held published bytes decoded again by the trusted runtime, judged against the held captured sources.
    def decide():
        found=fresh.observe(prepared,payloads,published,paths,deadline,tagged)
        fresh.bind(retained,found,probe_data,tagged)
        return found
    found=review.observed_fresh(decide)
    if (file_digest(output)!=published_digest
            or [hashlib.sha256(source_bytes(directory/record['retained'])).hexdigest() for record in sources]!=[record['sha256'] for record in sources]):
        fail('VERIFICATION_FAILED','the published video or a captured source changed while it was being verified',prepared['output'])
    verdict=None
    if 'deliverable' in prepared:
        # Both the retained assessment and the one rebuilt from the fresh observation must accept; the fresh one is reported.
        verdict=assess_deliverable(prepared['deliverable'],w,h,len(pixels),options['fps'],len(published),found['errors'],found['duration'])
        for assessment in (expected['deliverable'],verdict):
            if not assessment['accepted']:
                fail('DELIVERABLE_NOT_MET','video is correct but does not meet the authored media requirements',
                     '$.deliverable',assessment=assessment)
    claims={'status':'succeeded','verified':True,'artifacts':1,'video':str(output)}
    if verdict is not None:claims['deliverable']=expected['deliverable']
    if require_result and not review.same_json(result,claims):
        fail('VERIFICATION_FAILED','retained result claims differ from the verified outcome','result.json')
    answer={'verified':True,'artifacts':1,'frames':found['frames'],'duration':found['frames']/found['fps'],'runtime':receipt['runtime'],
            'nativeReadbackBound':'nativeReadback' in receipt,'freshNativeVerification':True,'freshRuntime':found['runtime'],
            'colourTagged':tagged}
    if verdict is not None:answer['deliverable']=verdict
    return answer


def validate_probe(probe, width, height, count, options, tagged=True):
    from fractions import Fraction
    try:
        if not isinstance(probe,dict): raise ValueError('expected a probe object')
        streams=probe['streams']
        if not isinstance(streams,list) or len(streams)!=1: raise ValueError('expected exactly one video stream')
        stream=streams[0]
        if not isinstance(stream,dict) or not isinstance(probe['format'],dict):raise ValueError('malformed stream or format object')
        if (stream['codec_type']!='video' or stream['codec_name']!=options['codec']
            or stream['pix_fmt']!=('yuv420p' if options['codec']=='h264' else 'bgr0')
            or type(stream['width'])is not int or type(stream['height'])is not int
            or not isinstance(stream['nb_read_frames'],str)
            or stream['width']!=width or stream['height']!=height
            or int(stream['nb_read_frames'])!=count
            or Fraction(stream['avg_frame_rate'])!=options['fps']
            or not math.isclose(float(probe['format']['duration']),count/options['fps'],abs_tol=0.002)):
            raise ValueError('video stream dimensions, codec, pixel format, frame count, rate or duration differ')
        if options['codec']=='h264' and tagged and (stream.get('color_space'),stream.get('color_range'))!=('smpte170m','tv'):
            raise ValueError('H.264 stream does not declare BT.601 limited-range colour (color_space smpte170m, color_range tv)')
    except (KeyError,ValueError,TypeError,ZeroDivisionError) as error:
        fail('VERIFICATION_FAILED',str(error))


# Shared authored-input, analytic-visit and verification boundary.
from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
