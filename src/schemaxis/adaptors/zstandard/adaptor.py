"""Typed durable compression, dictionaries and frame workflows through Zstandard.

Host discovery/planning imports no codec library. Native commands receive captured
regular files and fixed argument arrays; decoded bytes and frame checksums are
independently compared with the requested content in a fresh process.
"""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys
import tempfile
import time

from schemaxis.artifacts import atomic_json
from schemaxis.configuration import executable as configured
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import execution_deadline, remaining_timeout
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute
from . import frames
from . import compression_options
from . import benchmark
from . import file_sets

VERSION='schemaxis.zstandard/1'
MAX_BYTES=64*1024*1024
MAX_COMPRESSED=72*1024*1024
FORMATS=('zstd','gzip','xz','lzma','lz4')
TEXT_PUBLICATIONS={'summary.json','profiles.json','benchmark.json','benchmark.txt','dictionary.json','files.json'}
PATH={'type':'string','minLength':1,'maxLength':4096}
FIELDS={
 'source':PATH,
 'sources':{'type':'array','items':PATH,'minItems':1,'maxItems':32},
 'samples':{'type':'array','items':PATH,'minItems':8,'maxItems':128},
 'dictionary':PATH,'reference':PATH,
 'dictionaryMode':{'type':'enum','values':['trained','raw'],'default':'trained'},
 'sparseOutput':{'type':'boolean','default':True},
 'format':{'type':'enum','values':list(FORMATS),'default':'zstd'},
 'level':{'type':'integer','minimum':1,'maximum':22,'default':3},
 'fast':{'type':'integer','minimum':0,'maximum':100,'default':0},
 'threads':{'type':'integer','minimum':1,'maximum':2,'default':1},
 'singleThread':{'type':'boolean','default':False},
 'checksum':{'type':'boolean','default':True},
 'dictionaryID':{'type':'boolean','default':True},
 'longWindowLog':{'type':'integer','minimum':0,'maximum':27,'default':0},
 'rsyncable':{'type':'boolean','default':False},
 'literals':{'type':'enum','values':['automatic','compressed','raw'],'default':'automatic'},
 'chunkBytes':{'type':'integer','minimum':0,'maximum':MAX_BYTES,'default':0},
 'streamInput':{'type':'boolean','default':False},
 'tuning':{'type':'object','default':{},'properties':{
     'windowLog':{'type':'integer','minimum':10,'maximum':27},
     'chainLog':{'type':'integer','minimum':6,'maximum':26},
     'hashLog':{'type':'integer','minimum':6,'maximum':25},
     'searchLog':{'type':'integer','minimum':1,'maximum':20},
     'minMatch':{'type':'integer','minimum':3,'maximum':7},
     'targetLength':{'type':'integer','minimum':0,'maximum':999},
     'strategy':{'type':'enum','values':['fast','doubleFast','greedy','lazy','lazy2','btlazy2','btopt','btultra','btultra2']}}},
 'maxDecodedBytes':{'type':'integer','minimum':0,'maximum':MAX_BYTES,'default':MAX_BYTES},
 'algorithm':{'type':'enum','values':['fastCover','cover','legacy'],'default':'fastCover'},
 'maxDictionaryBytes':{'type':'integer','minimum':256,'maximum':1024*1024,'default':16384},
 'id':{'type':'integer','minimum':1,'maximum':4294967295,'default':32768},
 'segmentSize':{'type':'integer','minimum':0,'maximum':2048,'default':0},
 'dmerSize':{'type':'integer','minimum':0,'maximum':16,'default':0},
 'steps':{'type':'integer','minimum':1,'maximum':64,'default':4},
 'frequencyLog':{'type':'integer','minimum':10,'maximum':23,'default':20},
 'acceleration':{'type':'integer','minimum':1,'maximum':10,'default':1},
 'trainingFraction':{'type':'number','minimum':0.1,'maximum':1,'default':.75},
 'shrink':{'type':'boolean','default':False},
 'selectivity':{'type':'integer','minimum':1,'maximum':20,'default':9},
 'trainingLevel':{'type':'integer','minimum':1,'maximum':19,'default':3},
 'sampleBlockBytes':{'type':'integer','minimum':0,'maximum':1024*1024,'default':0},
 'shrinkRegression':{'type':'integer','minimum':1,'maximum':100,'default':1},
 'profiles':{'type':'array','minItems':1,'maxItems':4,'items':{'type':'object','properties':{
     'id':{'type':'string','minLength':1,'maxLength':32,'required':True},
     'format':{'type':'enum','values':list(FORMATS),'default':'zstd'},
     'level':{'type':'integer','minimum':1,'maximum':19,'default':3}}}},
}
FIELDS.update(compression_options.FIELDS)
FIELDS.update(benchmark.FIELDS)
FIELDS['fileSet']=file_sets.FIELD
FIELDS['tuning']['properties'].update(compression_options.TUNING)
COMPRESSION=('source','format','level','fast','threads','singleThread','checksum','dictionaryID','longWindowLog','rsyncable','literals','chunkBytes','streamInput','tuning','dictionary','dictionaryMode',*compression_options.FIELDS)
OPTIONS={
 'compress':COMPRESSION,
 'restore':('source','dictionary','dictionaryMode','reference','maxDecodedBytes','sparseOutput'),
 'inspect':('source','dictionary','dictionaryMode','reference','maxDecodedBytes','sparseOutput'),
 'trainDictionary':('samples','algorithm','maxDictionaryBytes','id','segmentSize','dmerSize','steps','frequencyLog','acceleration','trainingFraction','shrink','shrinkRegression','selectivity','trainingLevel','sampleBlockBytes'),
 'encodeDelta':(*COMPRESSION,'reference'),
 'concatenate':('sources','dictionary','dictionaryMode','maxDecodedBytes'),
 'compareProfiles':('source','profiles'),
 'benchmark':('source','firstLevel','lastLevel','minimumSeconds','benchmarkBlockBytes','threads','dictionary','dictionaryMode','tuning','longWindowLog'),
 'benchmarkDecode':('source','minimumSeconds','dictionary','dictionaryMode'),
 'inspectDictionary':('source','dictionaryMode'),
 'compressFiles':('fileSet',*[key for key in COMPRESSION if key not in ('source','pledgedBytes')]),
 'restoreFiles':('fileSet','dictionary','dictionaryMode','maxDecodedBytes','sparseOutput'),
}
REQUIRED={'compress':('source',),'restore':('source',),'inspect':('source',),
          'trainDictionary':('samples',),'encodeDelta':('source','reference'),
          'concatenate':('sources',),'compareProfiles':('source','profiles'),'benchmark':('source',),'benchmarkDecode':('source',),'inspectDictionary':('source',),
          'compressFiles':('fileSet',),'restoreFiles':('fileSet',)}
DECLARATIONS={name:{'native':{'compress':'zstd format/level/fast/long/dictionary/chunk-frame compression',
 'restore':'zstd --decompress --no-pass-through --memory=256MB',
 'inspect':'independent Zstandard frame headers, block boundaries and XXH64; fresh zstd decode',
 'trainDictionary':'zstd --train-fastcover / --train-cover / --train-legacy --maxdict --dictID',
 'encodeDelta':'zstd --patch-from=REFERENCE',
 'concatenate':'complete Zstandard frame concatenation and fresh decoded-content verification',
 'compareProfiles':'bounded zstd profile compress/decode comparisons with measured wall time',
 'benchmark':'zstd -b/-e/-i/-B native in-memory compression/decompression benchmark',
 'benchmarkDecode':'zstd -b -d -i native in-memory decompression benchmark',
 'inspectDictionary':'host dictionary header/identity and fresh native dictionary load, empty-frame creation and decode',
 'compressFiles':'captured recursive/named file selection with collision-checked per-file native compression',
 'restoreFiles':'captured recursive/named file selection with aggregate-bounded per-file native restoration'}[name],
 'kinds':['file','text'],'inputs':{},'options':{key:{'value':{**FIELDS[key],**({'required':True} if key in REQUIRED[name] else {})}} for key in options}}
 for name,options in OPTIONS.items()}


def plan(document):
    if not isinstance(document,dict):fail('INVALID_ZSTANDARD_DOCUMENT','The authored document must be an object','$')
    operation=document.get('operation')
    if not isinstance(operation,str) or operation not in OPTIONS:fail('UNKNOWN_FILTER','Choose one of '+', '.join(OPTIONS),'$.operation')
    keys(document,('version','operation',*OPTIONS[operation]),'$')
    if document.get('version')!=VERSION:fail('UNSUPPORTED_VERSION','Expected '+VERSION,'$.version')
    specs={key:{**FIELDS[key],**({'required':True} if key in REQUIRED[operation] else {})} for key in OPTIONS[operation]}
    values=validate_arguments(specs,{key:value for key,value in document.items() if key in specs},location='$')
    for key in ('source','dictionary','reference','sources','samples'):
        paths=values.get(key,[])
        if isinstance(paths,str):paths=[paths]
        for index,value in enumerate(paths):
            if '\x00' in value or not Path(value).is_absolute():fail('INVALID_ZSTANDARD_SOURCE','Use an absolute local file path','$.%s[%s]'%(key,index))
    for key in ('sources','samples'):
        if len(set(values.get(key,[])))!=len(values.get(key,[])):fail('INVALID_ZSTANDARD_SOURCE','List each input path once','$.%s'%key)
    if 'dictionary' in values and 'reference' in values:
        fail('INVALID_ZSTANDARD_OPTION','Choose a dictionary or a delta reference, not both')
    if 'dictionaryMode' in document and 'dictionary' not in values and operation!='inspectDictionary':
        fail('INVALID_ZSTANDARD_OPTION','Dictionary mode requires an actual dictionary','$.dictionaryMode')
    if operation in ('compressFiles','restoreFiles'):
        file_sets.validate({**values,'operation':operation},document)
        if operation=='compressFiles':
            single={key:value for key,value in document.items() if key!='fileSet'}
            single.update(operation='compress',source='/captured/file-set-member')
            if values['streamInput'] and values['contentSize']=='require':single['pledgedBytes']=0
            plan(single)
    if operation in ('compress','encodeDelta'):
        fmt=values['format']
        if values['fast'] and 'level' in document:fail('INVALID_ZSTANDARD_OPTION','Choose either fast acceleration or a compression level','$.fast')
        if fmt!='zstd':
            for key in ('fast','longWindowLog','rsyncable','chunkBytes'):
                if values[key]:fail('INVALID_ZSTANDARD_OPTION',key+' requires the zstd format','$.%s'%key)
            if 'dictionary' in values or not values['dictionaryID'] or not values['checksum'] or values['literals']!='automatic' or values['tuning']:
                fail('INVALID_ZSTANDARD_OPTION','Dictionary, checksum and literal overrides require zstd format')
            if values['level']>9:fail('INVALID_ZSTANDARD_OPTION','Compatibility format levels range from 1 to 9','$.level')
        if values['longWindowLog'] and values['longWindowLog']<10:fail('INVALID_ZSTANDARD_OPTION','Long window log is zero or 10–27','$.longWindowLog')
        if values['singleThread'] and (values['threads']!=1 or values['rsyncable']):fail('INVALID_ZSTANDARD_OPTION','Single-thread I/O requires one worker and disables rsyncable mode')
        if values['longWindowLog'] and 'windowLog' in values['tuning'] and values['longWindowLog']!=values['tuning']['windowLog']:
            fail('INVALID_ZSTANDARD_OPTION','Long-distance and tuned window sizes must agree','$.tuning.windowLog')
        if operation=='encodeDelta' and (fmt!='zstd' or 'dictionary' in values or values['chunkBytes']):
            fail('INVALID_ZSTANDARD_OPTION','Delta encoding uses one zstd frame and a reference, without a separate dictionary')
        if operation=='encodeDelta' and (values['longWindowLog'] or 'windowLog' in values['tuning'] or values['jobBytes']):
            fail('INVALID_ZSTANDARD_OPTION','Delta mode derives its native window from captured sizes; omit explicit window and job-size overrides','$.operation')
        compression_options.validate(values,document)
    if operation=='trainDictionary':
        if abs(values['trainingFraction']*100-round(values['trainingFraction']*100))>1e-9:
            fail('INVALID_ZSTANDARD_OPTION','Training fraction must specify a whole percentage','$.trainingFraction')
        if int(len(values['samples'])*values['trainingFraction'])<5:
            fail('INVALID_ZSTANDARD_OPTION','At least five samples must enter the training partition','$.trainingFraction')
        if values['algorithm']=='legacy' and any(key in document for key in ('segmentSize','dmerSize','steps','frequencyLog','acceleration','trainingFraction','shrink','shrinkRegression')):
            fail('INVALID_ZSTANDARD_OPTION','Legacy training uses selectivity, not Cover parameters')
        if values['algorithm']=='cover' and any(key in document for key in ('frequencyLog','acceleration','selectivity')):
            fail('INVALID_ZSTANDARD_OPTION','Cover training has no FastCover hash frequency or acceleration control')
        if values['algorithm']=='fastCover' and ('selectivity' in document or values['shrink']):
            fail('INVALID_ZSTANDARD_OPTION','FastCover has no legacy selectivity; shrink is available with Cover training')
        if 'shrinkRegression' in document and not values['shrink']:
            fail('INVALID_ZSTANDARD_OPTION','A shrink regression budget requires Cover shrink mode')
        if values['sampleBlockBytes'] and values['sampleBlockBytes']<64:
            fail('INVALID_ZSTANDARD_OPTION','Sample blocks are zero or at least 64 bytes')
        if values['segmentSize'] and not values['dmerSize']:fail('INVALID_ZSTANDARD_OPTION','Explicit segmentSize requires dmerSize')
        if values['segmentSize'] and values['segmentSize']<values['dmerSize']:fail('INVALID_ZSTANDARD_OPTION','segmentSize must be at least dmerSize')
        if values['algorithm']=='fastCover' and values['dmerSize'] not in (0,6,8):fail('INVALID_ZSTANDARD_OPTION','FastCover dmerSize is 6 or 8, or zero for automatic')
    if operation=='compareProfiles':
        identities=[profile['id'] for profile in values['profiles']]
        if len(set(identities))!=len(identities):fail('INVALID_ZSTANDARD_OPTION','Profile IDs must be distinct','$.profiles')
        if any(profile['format']!='zstd' and profile['level']>9 for profile in values['profiles']):fail('INVALID_ZSTANDARD_OPTION','Compatibility profile levels range from 1 to 9')
    if operation in ('benchmark','benchmarkDecode'):
        values['benchmarkMode']='decode' if operation=='benchmarkDecode' else 'roundTrip'
        if operation=='benchmarkDecode':values.update(firstLevel=1,lastLevel=1,benchmarkBlockBytes=0,threads=1,tuning={},longWindowLog=0)
        benchmark.validate(values,document)
        if values['benchmarkMode']=='roundTrip':
            plan({'version':VERSION,'operation':'compress','source':values['source'],'level':values['firstLevel'],
                  'threads':values['threads'],'tuning':values['tuning'],'longWindowLog':values['longWindowLog']})
    return {'version':'schemaxis.zstandard.plan/1','operation':operation,**values}


def schema():
    from schemaxis.schema import DRAFT,argument_schema,object_schema
    variants=[]
    authored_fields=set().union(*OPTIONS.values())
    for operation,options in OPTIONS.items():
        branch=object_schema({'version':{'const':VERSION},'operation':{'const':operation},
            **{key:argument_schema(FIELDS[key]) for key in options}},['version','operation',*REQUIRED[operation]])
        # The root publishes the full parser envelope for shared authoring.
        # Each selected task still refuses fields belonging to other tasks.
        branch.pop('additionalProperties')
        excluded=sorted(authored_fields-set(options))
        if excluded:branch['not']={'anyOf':[{'required':[key]} for key in excluded]}
        variants.append(branch)
    result=object_schema({'version':{'const':VERSION},'operation':{'enum':list(OPTIONS)},
        **{key:argument_schema(spec) for key,spec in FIELDS.items() if key in authored_fields}},['version','operation'])
    result.update({'$schema':DRAFT,'oneOf':variants})
    return result


def query(document):return [plan(document)['operation']],{}


def _digest(data):return hashlib.sha256(data).hexdigest()


def _read(path,limit=MAX_BYTES):
    path=Path(path)
    if str(path.resolve())!=str(path) or not path.is_absolute():fail('INVALID_ZSTANDARD_SOURCE','Input must not use symbolic links',str(path))
    try:
        descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(descriptor,'rb') as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size>limit:fail('ZSTANDARD_BUDGET','Input is not a bounded regular file',str(path))
            data=stream.read(limit+1)
            if len(data)>limit:fail('ZSTANDARD_BUDGET','Input grew beyond its byte budget',str(path))
            return data
    except OSError as error:fail('RESOURCE_NOT_FOUND','Cannot read the selected input',str(path),detail=str(error))


def reusableInputs(document):
    prepared=plan(document)
    result={path:_digest(_read(path,MAX_COMPRESSED if key in ('source','sources') else MAX_BYTES))
        for key in ('source','sources','samples','dictionary','reference') for path in ([prepared[key]] if isinstance(prepared.get(key),str) else prepared.get(key,[]))}
    if 'fileSet' in prepared:
        limit=MAX_BYTES if prepared['operation']=='compressFiles' else MAX_COMPRESSED
        result.update({item['source']:_digest(_read(item['source'],limit)) for item in file_sets.selection(prepared)})
    return result


def resources(document,execution,operation_id):
    p=plan(document)
    requested=execution.get('threads',p.get('threads',1))
    if type(requested) is not int or requested<p.get('threads',1):
        fail('INVALID_EXECUTION','Reserve at least the authored number of compression workers',operation_id)
    return {'threads':p.get('threads',1)}


def _json(path,limit=4*1024*1024):
    def pairs(values):
        result={}
        for key,value in values:
            if key in result:raise ValueError('Repeated JSON property '+key)
            result[key]=value
        return result
    def number(value):
        result=float(value)
        if not math.isfinite(result):raise ValueError('Non-finite JSON number')
        return result
    def constant(value):raise ValueError('Non-finite JSON constant '+value)
    return json.loads(_read(path,limit).decode('utf-8'),object_pairs_hook=pairs,parse_float=number,parse_constant=constant)


def _native(executable,directory,stage,args,limit=MAX_COMPRESSED,*,stdin=None):
    # RLIMIT_FSIZE bounds the actual native output, including unknown-size frames
    # and sparse decompression. No unbounded stdout or shell is involved.
    launcher=directory/'native-launch.py'
    launcher.write_text('import os,resource,sys\nresource.setrlimit(resource.RLIMIT_FSIZE,('+str(limit)+','+str(limit)+'))\n'
        'resource.setrlimit(resource.RLIMIT_AS,(2147483648,2147483648))\n'
        +('fd=os.open('+repr(str(stdin))+',os.O_RDONLY|os.O_NOFOLLOW)\nos.dup2(fd,0)\nif fd!=0:os.close(fd)\n' if stdin else '')+
        'env=dict(os.environ)\nfor key in ("ZSTD_CLEVEL","ZSTD_NBTHREADS"):env.pop(key,None)\n'
        'env["LC_ALL"]="C"\n'
        'os.execvpe(sys.argv[1],sys.argv[1:],env)\n')
    try:
        return execute([sys.executable,str(launcher),executable,*map(str,args)],directory,stage,remaining_timeout(180))
    except SchemaxisError as error:
        if error.fault.code in ('RUNNER_CANCELLED','RUNNER_TIMED_OUT'):
            raise
        # The pinned CLI may handle EFBIG, print strerror and delete its
        # incomplete output. Absence of that file does not undo the OS limit.
        code='ZSTANDARD_BUDGET' if (error.fault.observed.get('exitCode') in (-25,153)
            or ': File too large' in error.fault.observed.get('stderr','')) else 'ZSTANDARD_NATIVE_FAILED'
        fail(code,'Zstandard could not complete the requested stage',stage,
             detail=error.fault.observed.get('stderr','')[-2000:],
             recovery='Check the corpus size, dictionary/reference and configured runtime; reduce output or memory needs if a budget was reached')


def _executable(value=None):
    result=value or configured('zstandard')
    if not result:fail('VERIFICATION_RUNTIME_REQUIRED','Configure the trusted Zstandard 1.5.7 executable','zstandard')
    return str(Path(result).expanduser().resolve())


def _identity(executable,directory):
    _native(executable,directory,'version',['--version'])
    text=(directory/'version.stdout').read_text()
    if 'v1.5.7' not in text or 'Zstandard' not in text:fail('UNSUPPORTED_RUNTIME','Expected Zstandard 1.5.7',observed=text[:200])
    return '1.5.7'


def _compression(p):
    args=['--quiet','--no-progress','--keep','--format='+p['format']]
    args+=['--single-thread'] if p['singleThread'] else ['-T'+str(p['threads'])]
    args+=['--fast='+str(p['fast'])] if p['fast'] else (["--ultra"] if p['level']>19 else [])+['-'+str(p['level'])]
    if p['format']=='zstd':
        args+=['--check' if p['checksum'] else '--no-check']
        if not p['dictionaryID']:args+=['--no-dictID']
        if p['longWindowLog']:args+=['--long='+str(p['longWindowLog'])]
        if p['rsyncable']:args+=['--rsyncable']
        if p['literals']!='automatic':args+=['--compress-literals' if p['literals']=='compressed' else '--no-compress-literals']
        mapping={'windowLog':'wlog','chainLog':'clog','hashLog':'hlog','searchLog':'slog','minMatch':'mml','targetLength':'tlen','strategy':'strat'}
        mapping.update(overlapLog='ovlog',ldmHashRateLog='lhrlog',ldmHashLog='lhlog',ldmMinMatch='lmml',ldmBucketSizeLog='lblog')
        parameters=[]
        for key,value in p['tuning'].items():
            if key=='strategy':value=FIELDS['tuning']['properties']['strategy']['values'].index(value)+1
            parameters.append(mapping[key]+'='+str(value))
        if parameters:args+=['--zstd='+','.join(parameters)]
        args+=compression_options.arguments(p)
    return args


def _codec(executable,directory,stage,source,output,p,*,decode=False,dictionary=None,reference=None):
    args=['--quiet','--no-progress','--decompress','--no-pass-through','--memory=256MB'] if decode else _compression(p)
    if decode:args+=['--sparse' if p.get('sparseOutput',True) else '--no-sparse']
    if dictionary is not None:args+=['-D',str(dictionary)]
    if reference is not None:args+=['--patch-from='+str(reference)]
    streamed=not decode and p.get('streamInput',False)
    # The CLI recognises '-' as stdin only before its end-of-options marker.
    # Captured paths use '--'; the fixed stdin token is never authored input.
    args+=['-o',str(output),*(['-'] if streamed else ['--',str(source)])]
    limit=p.get('maxDecodedBytes',MAX_BYTES) if decode else MAX_COMPRESSED
    try:_native(executable,directory,stage,args,limit,stdin=source if streamed else None)
    except SchemaxisError as error:
        # Sparse skip error 92 is bound to the actual file at its byte cap;
        # other I/O errors retain their native failure diagnosis.
        detail=error.fault.observed.get('detail','')
        if (decode and error.fault.code=='ZSTANDARD_NATIVE_FAILED' and output.is_file()
                and output.stat().st_size==limit
                and any(message in detail for message in ('Sparse skip error','Write error'))):
            fail('ZSTANDARD_BUDGET','Native decoding reached the actual output-file limit',stage,limitBytes=limit)
        raise
    return _read(output,MAX_BYTES if decode else MAX_COMPRESSED)


def _format(data):
    if len(data)>=4 and (data[:4]==b'\x28\xb5\x2f\xfd' or 0x184d2a50<=int.from_bytes(data[:4],'little')<=0x184d2a5f):return 'zstd'
    if data.startswith(b'\x1f\x8b'):return 'gzip'
    if data.startswith(b'\xfd7zXZ\x00'):return 'xz'
    if data.startswith(b'\x04\x22\x4d\x18'):return 'lz4'
    # LZMA-alone has no magic: the property byte and dictionary size have a
    # finite native interpretation; fresh native decoding is still mandatory.
    if len(data)>=13 and data[0]<225:
        dictionary=int.from_bytes(data[1:5],'little')
        if 4096<=dictionary<=frames.MAX_WINDOW:return 'lzma'
    fail('INVALID_ZSTANDARD_STREAM','Unrecognised compressed frame; uncompressed pass-through is disabled')


def _decode_checked(executable,directory,source,p,*,dictionary=None,reference=None,stage='decode'):
    data=_read(source,MAX_COMPRESSED);kind=_format(data);limit=p.get('maxDecodedBytes',MAX_BYTES)
    records=frames.inspect(data,max_decoded=limit) if kind=='zstd' else None
    output=directory/(stage+'.raw')
    decoded=_codec(executable,directory,stage,source,output,p,decode=True,dictionary=dictionary,reference=reference)
    metadata={'format':kind,'decodedBytes':len(decoded),'decodedSha256':_digest(decoded)}
    if kind=='zstd':
        pieces=[];total=0
        for index,record in enumerate(records):
            remaining_timeout()
            if record['kind']=='skippable':continue
            fragment=directory/(stage+'-frame-'+str(index)+'.zst')
            fragment.write_bytes(data[record['offset']:record['offset']+record['bytes']])
            piece=_codec(executable,directory,stage+'-frame-'+str(index),fragment,
                directory/(stage+'-frame-'+str(index)+'.raw'),{**p,'maxDecodedBytes':limit-total},
                decode=True,dictionary=dictionary,reference=reference)
            total+=len(piece)
            if total>limit:fail('ZSTANDARD_BUDGET','Decoded frames exceed the output budget')
            frames.check_content(record,piece);pieces.append(piece)
        if b''.join(pieces)!=decoded:fail('VERIFICATION_FAILED','Whole-stream decoding differs from independently bounded frame decoding')
        metadata['frames']=records
    return decoded,metadata


def _capture(prepared,directory):
    result=[];total=0
    selection=file_sets.selection(prepared) if 'fileSet' in prepared else []
    if selection:
        file_sets.destination(prepared,selection,directory)
        atomic_json(directory/'selection.json',selection)
    file_bytes=0
    for key in ('source','sources','samples','dictionary','reference','files'):
        values=[item['source'] for item in selection] if key=='files' else prepared.get(key,[])
        if isinstance(values,str):values=[values]
        for index,value in enumerate(values):
            raw=prepared['operation'] in ('compress','encodeDelta','compareProfiles','compressFiles') or prepared['operation']=='benchmark' and prepared['benchmarkMode']=='roundTrip'
            limit=MAX_COMPRESSED if key in ('source','sources','files') and not raw else MAX_BYTES
            data=_read(value,limit);total+=len(data)
            if key=='files':
                file_bytes+=len(data)
                if file_bytes>(MAX_BYTES if raw else MAX_COMPRESSED):fail('ZSTANDARD_BUDGET','Captured file-set bytes exceed the aggregate raw/compressed limit')
            if key=='source' and 'pledgedBytes' in prepared and prepared['pledgedBytes']!=len(data):
                fail('INVALID_ZSTANDARD_OPTION','Exact stream pledge differs from captured source bytes','$.pledgedBytes')
            if total>128*1024*1024:fail('ZSTANDARD_BUDGET','Captured inputs exceed 128 MiB total')
            filename='captured-'+key+'-'+str(index)+'.bin'
            (directory/filename).write_bytes(data)
            result.append({'role':key,'index':index,'source':value,'file':filename,'bytes':len(data),'sha256':_digest(data)})
    atomic_json(directory/'inputs.json',result)
    return result


def _inputs(directory,prepared):
    result=_json(directory/'inputs.json')
    selection=file_sets.retained(prepared,_json(directory/'selection.json')) if 'fileSet' in prepared else []
    expected=[(key,index,value) for key in ('source','sources','samples','dictionary','reference','files')
              for index,value in enumerate([item['source'] for item in selection] if key=='files' else [prepared[key]] if isinstance(prepared.get(key),str) else prepared.get(key,[]))]
    if not isinstance(result,list) or len(result)!=len(expected):fail('VERIFICATION_FAILED','Captured input membership differs')
    paths={};total=0;file_bytes=0
    for record,(role,index,value) in zip(result,expected):
        filename='captured-'+role+'-'+str(index)+'.bin'
        if (not isinstance(record,dict) or record.keys()!=set(('role','index','source','file','bytes','sha256'))
                or type(record.get('index')) is not int or type(record.get('bytes')) is not int
                or (record['role'],record['index'],record['source'],record['file'])!=(role,index,value,filename)):
            fail('VERIFICATION_FAILED','Captured input identity or path differs')
        raw=prepared['operation'] in ('compress','encodeDelta','compareProfiles','compressFiles') or prepared['operation']=='benchmark' and prepared['benchmarkMode']=='roundTrip'
        limit=MAX_COMPRESSED if role in ('source','sources','files') and not raw else MAX_BYTES
        data=_read(directory/filename,limit);total+=len(data)
        if role=='files':
            file_bytes+=len(data)
            if file_bytes>(MAX_BYTES if raw else MAX_COMPRESSED):fail('ZSTANDARD_BUDGET','Captured file-set bytes exceed the aggregate raw/compressed limit')
        if total>128*1024*1024:fail('ZSTANDARD_BUDGET','Captured inputs exceed 128 MiB total')
        if len(data)!=record['bytes'] or _digest(data)!=record['sha256']:fail('VERIFICATION_FAILED','Captured input bytes differ')
        paths[(role,index)]=directory/filename
    return paths


def _training(p):
    if p['algorithm']=='legacy':option='--train-legacy=s='+str(p['selectivity'])
    else:
        # The CLI accepts an integer percentage; the domain model uses a
        # fraction. Passing 0.75 directly would be parsed as zero by zstd.
        parameters={'steps':p['steps'],'split':round(100*p['trainingFraction'])}
        if p['segmentSize']:parameters['k']=p['segmentSize']
        if p['dmerSize']:parameters['d']=p['dmerSize']
        if p['algorithm']=='fastCover':parameters.update(f=p['frequencyLog'],accel=p['acceleration'])
        values=[key+'='+str(value) for key,value in parameters.items()]
        if p['shrink']:values.append('shrink='+str(p['shrinkRegression']))
        option=('--train-fastcover=' if p['algorithm']=='fastCover' else '--train-cover=')+','.join(values)
    return ['--quiet',option,'--maxdict='+str(p['maxDictionaryBytes']),'--dictID='+str(p['id']),
            '-'+str(p['trainingLevel']),*(['-B'+str(p['sampleBlockBytes'])] if p['sampleBlockBytes'] else [])]


def _dictionary(path,p):
    data=_read(path,1024*1024)
    if p.get('dictionaryMode','trained')=='trained':return frames.dictionary_id(data)
    if not data or data.startswith(b'\x37\xa4\x30\xec'):
        fail('INVALID_ZSTANDARD_DICTIONARY','A raw dictionary must be nonempty history bytes, without a trained dictionary header')
    return 0


def _benchmark(p,directory,executable,paths,stage):
    source=paths[('source',0)];dictionary=paths.get(('dictionary',0))
    encoded=_read(source,MAX_COMPRESSED)
    if p['benchmarkMode']=='decode':
        raw,_=_decode_checked(executable,directory,source,{},dictionary=dictionary,stage=stage+'-input')
    else:raw=encoded
    if not raw:fail('INVALID_ZSTANDARD_SOURCE','Benchmarking requires nonempty decoded content')
    if p['benchmarkBlockBytes'] and math.ceil(len(raw)/p['benchmarkBlockBytes'])>256:
        fail('ZSTANDARD_BUDGET','Benchmarking permits at most 256 independently encoded blocks')
    args=benchmark.arguments(p)
    if p['benchmarkMode']=='roundTrip':
        profile=plan({'version':VERSION,'operation':'compress','source':str(source),'level':p['firstLevel'],
            'threads':p['threads'],'tuning':p['tuning'],'longWindowLog':p['longWindowLog']})
        args+=[arg for arg in _compression(profile) if arg.startswith(('--zstd=','--long='))]
    if dictionary:args+=['-D',str(dictionary)]
    _native(executable,directory,stage,[*args,'--',str(source)],65536)
    text=_read(directory/(stage+'.stdout'),65536).decode('utf-8')
    if _read(directory/(stage+'.stderr'),65536).strip():fail('INVALID_ZSTANDARD_BENCHMARK','Unexpected native benchmark diagnostics')
    return benchmark.parse(text,p,len(encoded),len(raw),source.name),text,raw


def _inspect_dictionary(p,directory,executable,source,stage):
    data=_read(source,1024*1024);identity=_dictionary(source,p)
    # A header alone cannot establish valid trained entropy tables. Load the
    # exact bytes through the native compressor and a separate fresh decoder.
    # The empty literal is an independent expected payload, not a receipt.
    empty=directory/(stage+'.empty');empty.write_bytes(b'')
    profile=plan({'version':VERSION,'operation':'compress','source':str(empty),
                  'dictionary':str(source),'dictionaryMode':p['dictionaryMode']})
    output=directory/(stage+'.zst')
    _codec(executable,directory,stage+'-encode',empty,output,profile,dictionary=source)
    raw,meta=_decode_checked(executable,directory,output,{'maxDecodedBytes':0},dictionary=source,stage=stage+'-decode')
    if raw or len(meta['frames'])!=1 or meta['frames'][0]['dictionaryID']!=identity:
        fail('VERIFICATION_FAILED','Dictionary load probe differs from the empty literal or requested dictionary identity')
    return {'representation':p['dictionaryMode'],'dictionaryID':identity,'dictionaryBytes':len(data),
            'dictionarySha256':_digest(data),'nativeLoadVerified':True,
            'scope':'Exact dictionary bytes loaded for fresh compression and decoding; no corpus-specific compression gain is asserted'}


def _produce(prepared,directory,executable,paths):
    p=prepared;operation=p['operation'];source=paths.get(('source',0));dictionary=paths.get(('dictionary',0));reference=paths.get(('reference',0))
    outputs=[]
    if dictionary:_dictionary(dictionary,p)
    if operation in ('compressFiles','restoreFiles'):
        return file_sets.produce(p,directory,executable,paths,file_sets.retained(p,_json(directory/'selection.json')))
    if operation in ('compress','encodeDelta'):
        data=_read(source);size=p['chunkBytes'] or max(1,len(data));pieces=[]
        if 'pledgedBytes' in p and p['pledgedBytes']!=len(data):fail('INVALID_ZSTANDARD_OPTION','Exact stream pledge differs from the captured source byte count','$.pledgedBytes')
        # Empty input is one valid empty frame, not an empty compressed file.
        positions=range(0,len(data),size) if data else [0]
        if len(positions)>256:fail('ZSTANDARD_BUDGET','Chunking would create more than 256 frames','$.chunkBytes')
        for index,at in enumerate(positions):
            part=directory/('chunk-'+str(index)+'.raw');part.write_bytes(data[at:at+size])
            encoded=_codec(executable,directory,'compress-'+str(index),part,directory/('chunk-'+str(index)+'.encoded'),p,dictionary=dictionary,reference=reference)
            pieces.append(encoded)
            if sum(map(len,pieces))>MAX_COMPRESSED:fail('ZSTANDARD_BUDGET','Encoded chunks exceed the output budget')
        target=directory/('payload.'+{'zstd':'zst','gzip':'gz','xz':'xz','lzma':'lzma','lz4':'lz4'}[p['format']])
        target.write_bytes(b''.join(pieces));outputs=[target]
    elif operation=='restore':
        decoded,_=_decode_checked(executable,directory,source,p,dictionary=dictionary,reference=reference)
        # Preserve the native output's sparse-file policy on this filesystem;
        # rewriting its decoded byte array would silently densify the result.
        target=directory/'restored.bin';(directory/'decode.raw').replace(target);outputs=[target]
    elif operation=='inspect':
        _decode_checked(executable,directory,source,p,dictionary=dictionary,reference=reference)
    elif operation=='trainDictionary':
        target=directory/'dictionary.zdict'
        _native(executable,directory,'train',_training(p)+['-o',str(target),'--',*[str(paths[('samples',i)]) for i in range(len(p['samples']))]],p['maxDictionaryBytes'])
        data=_read(target,p['maxDictionaryBytes'])
        if frames.dictionary_id(data)!=p['id']:fail('VERIFICATION_FAILED','Trained dictionary ID differs')
        outputs=[target]
    elif operation=='concatenate':
        chunks=[_read(paths[('sources',i)],MAX_COMPRESSED) for i in range(len(p['sources']))]
        for chunk in chunks:frames.inspect(chunk,max_decoded=p['maxDecodedBytes'])
        if sum(map(len,chunks))>MAX_COMPRESSED:fail('ZSTANDARD_BUDGET','Concatenated frames exceed the compressed-file budget')
        target=directory/'payload.zst';target.write_bytes(b''.join(chunks));outputs=[target]
    elif operation in ('benchmark','benchmarkDecode'):
        observed,text,_=_benchmark(p,directory,executable,paths,'benchmark-native')
        atomic_json(directory/'benchmark.json',observed);(directory/'benchmark.txt').write_text(text)
        outputs=[directory/'benchmark.json',directory/'benchmark.txt']
    elif operation=='inspectDictionary':
        atomic_json(directory/'dictionary.json',_inspect_dictionary(p,directory,executable,source,'dictionary-probe'))
        outputs=[directory/'dictionary.json']
    else:
        profiles=[]
        for index,profile in enumerate(p['profiles']):
            options=plan({'version':VERSION,'operation':'compress','source':p['source'],'format':profile['format'],'level':profile['level']})
            output=directory/('profile-'+str(index)+'.compressed');start=time.monotonic()
            data=_codec(executable,directory,'profile-'+str(index),source,output,options)
            seconds=time.monotonic()-start
            recovered,_=_decode_checked(executable,directory,output,{},stage='profile-check-'+str(index))
            if recovered!=_read(source):fail('VERIFICATION_FAILED','Comparison profile changes decoded bytes')
            profiles.append({'id':profile['id'],'format':profile['format'],'level':profile['level'],'compressedBytes':len(data),
                             'sourceBytes':source.stat().st_size,'elapsedSeconds':seconds})
            outputs.append(output)
        atomic_json(directory/'profiles.json',profiles);outputs.append(directory/'profiles.json')
    return outputs


def _check(prepared,directory,executable,paths,outputs):
    p=prepared;operation=p['operation'];dictionary=paths.get(('dictionary',0));reference=paths.get(('reference',0))
    if dictionary:_dictionary(dictionary,p)
    if operation in ('compressFiles','restoreFiles'):
        return file_sets.check(p,directory,executable,paths,outputs,file_sets.retained(p,_json(directory/'selection.json')))
    if operation in ('compress','encodeDelta'):
        raw,metadata=_decode_checked(executable,directory,outputs[0],p,dictionary=dictionary,reference=reference,stage='verify-compressed')
        if raw!=_read(paths[('source',0)]):fail('VERIFICATION_FAILED','Compressed publication changes captured input bytes')
        if metadata['format']!=p['format']:fail('VERIFICATION_FAILED','Published compression format differs')
        if p['format']=='zstd':
            records=[f for f in metadata['frames'] if f['kind']=='zstandard']
            size=p['chunkBytes'] or max(1,len(raw))
            lengths=[len(raw[at:at+size]) for at in (range(0,len(raw),size) if raw else [0])]
            declared=compression_options.declared_sizes(p,lengths)
            if len(metadata['frames'])!=len(lengths) or [f['contentBytes'] for f in records]!=declared:
                fail('VERIFICATION_FAILED','Frame partition differs from the requested chunking')
            expected_dictionary=_dictionary(dictionary,p) if dictionary and p['dictionaryID'] else 0
            if any((f['checksum'] is not None)!=p['checksum'] or f['dictionaryID']!=expected_dictionary for f in records):
                fail('VERIFICATION_FAILED','Frame checksum or dictionary ID policy differs')
        # Decode proves content; a separate fresh reconstruction also binds
        # controls (level, strategy, window and threading) not encoded as flags
        # in the frame format. Neither command logs nor receipts are authority.
        if 'adaptive' in p:
            # Upstream explicitly makes adaptation non-reproducible. Check
            # content and frame policies, while exposing this historical
            # scheduling limit rather than falsely authenticating level history.
            metadata['adaptiveLevelHistoryVerified']=False
        else:
            with tempfile.TemporaryDirectory(prefix='schemaxis-zstd-intent-') as temporary:
                expected=_produce(p,Path(temporary),executable,paths)
                if _read(expected[0],MAX_COMPRESSED)!=_read(outputs[0],MAX_COMPRESSED):
                    fail('VERIFICATION_FAILED','Compressed bytes differ from current compression controls')
        return metadata
    if operation in ('restore','inspect'):
        raw,metadata=_decode_checked(executable,directory,paths[('source',0)],p,dictionary=dictionary,reference=reference,stage='verify-restored')
        if operation=='restore' and raw!=_read(outputs[0]):fail('VERIFICATION_FAILED','Restored publication differs from captured compressed content')
        return metadata
    if operation=='trainDictionary':
        expected=directory/'expected.zdict'
        _native(executable,directory,'verify-training',_training(p)+['-o',str(expected),'--',*[str(paths[('samples',i)]) for i in range(len(p['samples']))]],p['maxDictionaryBytes'])
        raw=_read(outputs[0],p['maxDictionaryBytes'])
        if raw!=_read(expected,p['maxDictionaryBytes']):fail('VERIFICATION_FAILED','Dictionary differs from current training intent and captured samples')
        return {'dictionaryID':frames.dictionary_id(raw),'dictionaryBytes':len(raw),'sampleBytes':sum(paths[('samples',i)].stat().st_size for i in range(len(p['samples'])))}
    if operation=='concatenate':
        # Bound aggregate output before separately decoding any input. Retain
        # only the joined bytes and one bounded input, rather than up to 32
        # independently maximum-sized decoded buffers.
        raw,metadata=_decode_checked(executable,directory,outputs[0],p,dictionary=dictionary,stage='verify-joined')
        offset=0
        for index in range(len(p['sources'])):
            piece,_=_decode_checked(executable,directory,paths[('sources',index)],{**p,'maxDecodedBytes':p['maxDecodedBytes']-offset},dictionary=dictionary,stage='verify-input-'+str(index))
            if piece!=raw[offset:offset+len(piece)]:fail('VERIFICATION_FAILED','Concatenated frame order or content differs')
            offset+=len(piece)
        if offset!=len(raw):fail('VERIFICATION_FAILED','Concatenated content length differs')
        return metadata
    if operation in ('benchmark','benchmarkDecode'):
        current,_,raw=_benchmark(p,directory,executable,paths,'benchmark-current')
        recorded=benchmark.parse(_read(directory/'benchmark.txt',65536).decode('utf-8'),p,
            paths[('source',0)].stat().st_size,len(raw),paths[('source',0)].name)
        if _json(directory/'benchmark.json')!=recorded:fail('VERIFICATION_FAILED','Benchmark JSON differs from its bounded native text')
        stable=lambda value:[(row['level'],row['compressedBytes'],row['ratio']) for row in value['levels']]
        if stable(current)!=stable(recorded):fail('VERIFICATION_FAILED','Benchmark sizes differ from current native execution')
        if p['benchmarkMode']=='roundTrip':
            for row in recorded['levels']:
                options=plan({'version':VERSION,'operation':'compress','source':str(paths[('source',0)]),
                    'level':row['level'],'checksum':False,'threads':p['threads'],'chunkBytes':p['benchmarkBlockBytes'],
                    'longWindowLog':p['longWindowLog'],'tuning':p['tuning'],
                    **({'dictionary':str(dictionary),'dictionaryMode':p['dictionaryMode']} if dictionary else {})})
                with tempfile.TemporaryDirectory(prefix='schemaxis-zstd-benchmark-') as temporary:
                    scratch=Path(temporary);expected=_produce(options,scratch,executable,paths)
                    decoded,_=_decode_checked(executable,scratch,expected[0],{},dictionary=dictionary,stage='reference-decode')
                    if decoded!=raw or expected[0].stat().st_size!=row['compressedBytes']:
                        fail('VERIFICATION_FAILED','Benchmark size differs from independent CLI frame creation and exact restoration')
        elif recorded['levels'][0]['compressedBytes']!=paths[('source',0)].stat().st_size:
            fail('VERIFICATION_FAILED','Decode benchmark compressed size differs from captured stream')
        return recorded
    if operation=='inspectDictionary':
        current=_inspect_dictionary(p,directory,executable,paths[('source',0)],'dictionary-current')
        if _json(directory/'dictionary.json')!=current:fail('VERIFICATION_FAILED','Dictionary inspection differs from current captured bytes and native loading')
        return current
    recorded=_json(directory/'profiles.json')
    if not isinstance(recorded,list) or len(recorded)!=len(p['profiles']):fail('VERIFICATION_FAILED','Profile comparison membership differs')
    for index,(record,profile) in enumerate(zip(recorded,p['profiles'])):
        output=directory/('profile-'+str(index)+'.compressed');raw,metadata=_decode_checked(executable,directory,output,{},stage='verify-profile-'+str(index))
        if (not isinstance(record,dict) or record.keys()!=set(('id','format','level','compressedBytes','sourceBytes','elapsedSeconds'))
            or record['id']!=profile['id'] or record['format']!=profile['format'] or record['level']!=profile['level']
            or record['compressedBytes']!=output.stat().st_size or record['sourceBytes']!=len(raw)
            or metadata['format']!=profile['format']
            or type(record['elapsedSeconds']) not in (int,float) or not math.isfinite(record['elapsedSeconds']) or not 0<=record['elapsedSeconds']<=180
            or raw!=_read(paths[('source',0)])):
            fail('VERIFICATION_FAILED','Comparison observations differ from actual profile outputs')
        options=plan({'version':VERSION,'operation':'compress','source':p['source'],'format':profile['format'],'level':profile['level']})
        with tempfile.TemporaryDirectory(prefix='schemaxis-zstd-profile-') as temporary:
            expected=_produce(options,Path(temporary),executable,paths)
            if _read(expected[0],MAX_COMPRESSED)!=_read(output,MAX_COMPRESSED):fail('VERIFICATION_FAILED','Profile bytes differ from current format and level')
    return {'profiles':recorded,'timingVerified':False,'timingScope':'Recorded producer wall time; later verification proves content and size, not historical timing'}


def _output_names(p,directory=None):
    operation=p['operation']
    if 'fileSet' in p:return file_sets.output_names(p,file_sets.retained(p,_json(directory/'selection.json')))
    if operation in ('compress','encodeDelta'):return ['payload.'+{'zstd':'zst','gzip':'gz','xz':'xz','lzma':'lzma','lz4':'lz4'}[p['format']]]
    if operation=='restore':return ['restored.bin']
    if operation=='trainDictionary':return ['dictionary.zdict']
    if operation=='concatenate':return ['payload.zst']
    if operation=='compareProfiles':return ['profile-'+str(i)+'.compressed' for i in range(len(p['profiles']))]+['profiles.json']
    if operation in ('benchmark','benchmarkDecode'):return ['benchmark.json','benchmark.txt']
    if operation=='inspectDictionary':return ['dictionary.json']
    return []


def _artifact_kind(path,directory):
    # Restored file-set members are opaque bytes, even under .json/.txt names.
    return 'text' if path.relative_to(directory).as_posix() in TEXT_PUBLICATIONS else 'file'


def _verify(directory,require_result=True,*,executable=None):
    directory=Path(directory).absolute();authored=_json(directory/'authored.json');p=plan(authored)
    if p!=_json(directory/'plan.json'):fail('VERIFICATION_FAILED','Retained plan differs from authored intent')
    paths=_inputs(directory,p);stored=_json(directory/'verification.json')
    names=_output_names(p,directory);actual=[directory/name for name in names]
    if 'fileSet' in p:file_sets.admit_outputs(p,actual[:-1])
    expected=[{'file':str(path),'kind':_artifact_kind(path,directory),'sha256':_digest(_read(path,MAX_COMPRESSED))} for path in actual]
    summary=directory/'summary.json';expected.append({'file':str(summary),'kind':'text','sha256':_digest(_read(summary,16*1024*1024))})
    if stored!={'version':'schemaxis.zstandard.verification/1','artifacts':expected}:fail('VERIFICATION_FAILED','Publication membership or digest differs')
    with tempfile.TemporaryDirectory(prefix='schemaxis-zstandard-verify-') as temporary:
        scratch=Path(temporary)
        # These captured immutable inputs, not their original paths, cross into
        # the fresh verification workspace. Native code never follows receipts.
        copied={}
        if 'fileSet' in p:atomic_json(scratch/'selection.json',file_sets.retained(p,_json(directory/'selection.json')))
        for key,path in paths.items():
            target=scratch/path.name;target.write_bytes(_read(path,MAX_COMPRESSED));copied[key]=target
        targets=[]
        for path in actual:
            target=scratch/path.relative_to(directory);target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(_read(path,MAX_COMPRESSED));targets.append(target)
        trusted=_executable(executable);_identity(trusted,scratch)
        observations=_check(p,scratch,trusted,copied,targets)
    if _json(summary,16*1024*1024)!={'version':'schemaxis.zstandard.summary/1','runtime':'1.5.7','operation':p['operation'],'observations':observations}:
        fail('VERIFICATION_FAILED','Summary differs from independent current-byte verification')
    if require_result:
        result=_json(directory/'result.json')
        if not isinstance(result,dict) or result.get('verified') is not True or result.get('status')!='succeeded':fail('VERIFICATION_FAILED','Successful result is absent')
    remaining_timeout()
    return {'verified':True,'runtime':'1.5.7','operation':p['operation'],'artifacts':expected,'observations':observations}


def verify(directory):
    if os.name!='posix':fail('UNSUPPORTED_PLATFORM','Native output and memory limits currently require POSIX')
    try:
        with execution_deadline(600):return _verify(directory)
    except SchemaxisError:raise
    except (OSError,ValueError,KeyError,TypeError,IndexError,RecursionError) as error:
        fail('VERIFICATION_FAILED','Malformed Zstandard run evidence',str(directory),detail=str(error))


def run(document,directory,*,executable=None,timeout=600):
    p=plan(document)
    if os.name!='posix':fail('UNSUPPORTED_PLATFORM','Native output and memory limits currently require POSIX')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=3600:fail('INVALID_ARGUMENT','Timeout must be finite and in (0,3600]')
    directory=Path(directory).absolute()
    if 'fileSet' in p and 'root' in p['fileSet'] and directory.resolve().is_relative_to(Path(p['fileSet']['root']).resolve()):
        fail('INVALID_ZSTANDARD_FILE_SET','Publish outside the selected source directory to keep capture independent of generated outputs')
    if directory.exists() or directory.is_symlink():fail('OUTPUT_EXISTS','Choose a fresh publication directory',str(directory))
    directory.mkdir(parents=True)
    atomic_json(directory/'result.json',{'verified':False,'status':'incomplete'})
    with execution_deadline(timeout):
        atomic_json(directory/'authored.json',document);atomic_json(directory/'plan.json',p)
        try:
            _capture(p,directory);paths=_inputs(directory,p);trusted=_executable(executable);_identity(trusted,directory)
            outputs=_produce(p,directory,trusted,paths)
            # Produce summary through the same fresh observer boundary used by
            # later verification; caller-facing verification repeats it anew.
            observations=_check(p,directory,trusted,paths,outputs)
            atomic_json(directory/'summary.json',{'version':'schemaxis.zstandard.summary/1','runtime':'1.5.7','operation':p['operation'],'observations':observations})
            artifacts=[{'file':str(path),'kind':_artifact_kind(path,directory),'sha256':_digest(_read(path,MAX_COMPRESSED))} for path in [*outputs,directory/'summary.json']]
            atomic_json(directory/'verification.json',{'version':'schemaxis.zstandard.verification/1','artifacts':artifacts})
            result=_verify(directory,False,executable=trusted);result['status']='succeeded';atomic_json(directory/'result.json',result)
            return result
        except Exception as error:
            fault=error.fault.to_dict() if isinstance(error,SchemaxisError) else {'code':'ZSTANDARD_FAILED','message':str(error)}
            atomic_json(directory/'result.json',{'verified':False,'status':'failed','fault':fault})
            if isinstance(error,(OSError,UnicodeError)):
                fail('ZSTANDARD_FAILED','Cannot capture or publish the requested files',str(directory),detail=str(error))
            raise


from schemaxis.adaptor_runtime import bind as _bind_runtime  # noqa: E402
_bind_runtime(globals())
