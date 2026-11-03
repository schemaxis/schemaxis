# Copyright (C) 2026 David L F Gaden
"""Captured passive PDF review with retained, source-bound native readback."""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import stat
import sys
import time

from schemaxis.artifacts import atomic_json
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute
from .native_source import source
from .inspection import png, pnm, pixel_digest

VERSION='schemaxis.mupdf/1'
MAX_BYTES=64*1024*1024
OPTIONS={
 'source': {'type':'string','minLength':1,'maxLength':4096,'required':True},
 'pages': {'type':'array','items':{'type':'integer','minimum':1,'maximum':128},'minItems':1,'maxItems':16,'required':True},
 'dpi': {'type':'integer','minimum':36,'maximum':300,'default':72},
 'rotation': {'type':'enum','values':[0,90,180,270],'default':0}}
DECLARATIONS={'review':{'native':'PDFDocument / PDFPage.getBounds, toPixmap, toStructuredText; Pixmap.saveAsPNG/saveAsPNM',
 'kinds':['image','text'],'inputs':{},'options':{k:{'value':v} for k,v in OPTIONS.items()}}}
LOSSES=[
 'PNG is an opaque 8-bit DeviceRGB raster of the effective CropBox and View appearances; no vectors, layers, links, forms or editability.',
 'Inherited PDF rotation and UserUnit are applied before the requested clockwise output rotation. No authored crop or media-box override.',
 'Text is native content-order UTF-8 extraction; font mappings determine Unicode, and reading order, OCR, layout and accessibility are not certified.',
 'Document actions, PDF JavaScript, links and attachments are never executed or followed. This passive rendering integration is not a PDF sanitizer or malware isolation boundary.',
 'Offline verification checks retained native source/command/readback consistency. Independent correctness is qualified on the known fixture, not every PDF.']


def plan(document):
    keys(document,('version','operation',*OPTIONS),'$')
    if document.get('version')!=VERSION: fail('UNSUPPORTED_VERSION','select '+VERSION,'$.version')
    if document.get('operation')!='review': fail('UNKNOWN_FILTER','select review','$.operation')
    prepared=validate_arguments(OPTIONS,{k:v for k,v in document.items() if k in OPTIONS},location='$')
    path=Path(prepared['source'])
    if not path.is_absolute() or path.suffix.lower()!='.pdf' or '\x00' in prepared['source']:
        fail('INVALID_PDF_SOURCE','select an absolute local .pdf regular file; URLs are unsupported','$.source')
    if len(set(prepared['pages']))!=len(prepared['pages']):
        fail('INVALID_PDF_PAGES','list distinct one-based page numbers in desired output order','$.pages')
    return {'version':'schemaxis.mupdf.plan/1','operation':'review',**prepared,'losses':LOSSES}


def schema():
    from schemaxis.schema import DRAFT,argument_schema,object_schema
    return {'$schema':DRAFT,**object_schema({'version':{'const':VERSION},'operation':{'const':'review'},
        **{k:argument_schema(v) for k,v in OPTIONS.items()}},['version','operation','source','pages'])}


def query(document):
    plan(document);return ['review'],{}


def resources(document,execution,identity):
    if execution.get('threads',1)!=1: fail('INVALID_EXECUTION','PDF review uses one serial native process',identity)
    return {'threads':1}


def bounded(path,code='VERIFICATION_FAILED',limit=MAX_BYTES):
    try:
        fd=os.open(path,os.O_RDONLY|getattr(os,'O_NONBLOCK',0)|getattr(os,'O_NOFOLLOW',0))
        with os.fdopen(fd,'rb') as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size>limit: raise ValueError('not a bounded regular file')
            data=stream.read(limit+1)
        if len(data)>limit: raise ValueError('file byte budget exceeded')
        return data
    except (ValueError,OSError) as error:
        fail(code,'select intact bounded regular evidence: '+str(error),str(path))


def reusableInputs(document):
    prepared=plan(document)
    return {'pdf':hashlib.sha256(bounded(prepared['source'],'INVALID_PDF_SOURCE',16*1024*1024)).hexdigest()}


def read(directory,name): return json.loads(bounded(directory/name))
def digest(directory,name): return hashlib.sha256(bounded(directory/name)).hexdigest()


def commands(executable):
    return {'version':[executable,'-v'],**{stage:[executable,'run',stage+'.js'] for stage in ('inspect','render','readback')}}


def launcher(directory,stage,command):
    names=[] if stage=='version' else ['source.pdf',stage+'.js']
    return ('import hashlib,json,os,stat,resource\nfrom pathlib import Path\n'
      'resource.setrlimit(resource.RLIMIT_AS,(1073741824,1073741824))\n'
      'resource.setrlimit(resource.RLIMIT_FSIZE,(67108864,67108864))\n'
      'resource.setrlimit(resource.RLIMIT_CPU,(120,120))\n'
      +f'names={names!r}\ncommand={command!r}\nbindings={{}}\n'
      +'for name in names:\n'
      +'    fd=os.open(name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_NONBLOCK",0))\n'
      +'    with os.fdopen(fd,"rb") as stream:\n'
      +'        info=os.fstat(stream.fileno())\n'
      +'        if not stat.S_ISREG(info.st_mode) or info.st_size>16777216: raise ValueError("invalid native PDF input")\n'
      +'        data=stream.read(16777217)\n'
      +'    if len(data)>16777216: raise ValueError("native input limit")\n'
      +'    bindings[name]=hashlib.sha256(data).hexdigest()\n'
      +f'Path({(stage+"-inputs.json")!r}).write_text(json.dumps(bindings,sort_keys=True))\n'
      +'os.execvpe(command[0],command,os.environ)\n')


def launch(directory,stage,command,deadline):
    path=directory/(stage+'-launcher.py');path.write_text(launcher(directory,stage,command))
    try:
        execute([sys.executable,str(path)],directory,stage,deadline-time.monotonic(),{'LANG':'C.UTF-8'})
    except SchemaxisError:
        stderr=bounded(directory/(stage+'.stderr')).decode('utf-8','replace') if (directory/(stage+'.stderr')).exists() else ''
        for token,message,location in [
          ('ENCRYPTED_PDF','encrypted PDFs are unsupported; supply an authorized unencrypted copy','$.source'),
          ('PDF_TEXT_LIMIT','select fewer pages or a smaller PDF: text <=1048576 characters per page and4194304 combined','$.pages'),
          ('PDF_REPAIRED','native PDF repair is unsupported; supply a structurally intact source PDF','$.source'),
          ('PDF_PAGE_RANGE','a selected page exceeds the actual document page count','$.pages'),
          ('PDF_PAGE_LIMIT','PDF must contain 1–128 pages','$.source'),
          ('PDF_GEOMETRY_LIMIT','effective crop dimensions must be finite and within 14400 points','$.source'),
          ('PDF_PIXEL_LIMIT','reduce DPI or page selection: dimensions <=4096 and combined pixels <=16777216','$.dpi')]:
            if token in stderr: fail(token,message,location)
        raise


def metadata(meta,prepared,rendered=False):
    basic={'page','bounds','mediaBox','cropBox','userUnit','inheritedRotation'}
    expected=basic|({'pixelBounds','resolution','text'} if rendered else set())
    if not isinstance(meta,dict) or set(meta)!={'pageCount','pages'} or type(meta['pageCount']) is not int or not 1<=meta['pageCount']<=128 or not isinstance(meta['pages'],list) or len(meta['pages'])!=len(prepared['pages']):
        fail('VERIFICATION_FAILED','native PDF page membership differs')
    text_count=0
    for number,page in zip(prepared['pages'],meta['pages']):
        if not isinstance(page,dict) or set(page)!=expected or type(page['page']) is not int or page['page']!=number or number>meta['pageCount']:
            fail('VERIFICATION_FAILED','native page fields/order/types differ')
        for key in ('bounds','mediaBox','cropBox'):
            box=page[key]
            if key!='bounds' and box is None:continue
            if not isinstance(box,list) or len(box)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in box):
                fail('VERIFICATION_FAILED','native raw/effective boxes must be finite four-number arrays',key)
        if type(page['inheritedRotation']) is not int or page['inheritedRotation']%90 or abs(page['inheritedRotation'])>36000:
            fail('VERIFICATION_FAILED','native inherited rotation must be a bounded integer quarter turn')
        if type(page['userUnit']) not in (int,float) or not math.isfinite(page['userUnit']) or not 0<page['userUnit']<=75000:
            fail('VERIFICATION_FAILED','native UserUnit must be finite and positive')
        if rendered:
            if not isinstance(page['resolution'],list) or len(page['resolution'])!=2 or any(type(v) is not int or v!=prepared['dpi'] for v in page['resolution']):fail('VERIFICATION_FAILED','native raster density differs')
            if not isinstance(page['pixelBounds'],list) or len(page['pixelBounds'])!=4 or any(type(v) is not int for v in page['pixelBounds']):
                fail('VERIFICATION_FAILED','native pixel bounds must be four integers')
            if not isinstance(page['text'],str) or len(page['text'])>1048576:fail('VERIFICATION_FAILED','native text must fit one million characters per page')
            text_count+=len(page['text'])
    if text_count>4194304:fail('VERIFICATION_FAILED','combined native text exceeds four million characters')


def geometry(meta,prepared):
    metadata(meta,prepared)
    total=0; dimensions=[]
    matrices=[(1,0,0,1),(0,1,-1,0),(-1,0,0,-1),(0,-1,1,0)]
    a,b,c,d=matrices[prepared['rotation']//90];s=prepared['dpi']/72
    for expected,page in zip(prepared['pages'],meta['pages']):
        if page['page']!=expected or expected>meta['pageCount']: fail('VERIFICATION_FAILED','native page order differs')
        bounds=page['bounds']
        if len(bounds)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in bounds): fail('VERIFICATION_FAILED','finite crop bounds required')
        x0,y0,x1,y1=bounds
        if not 0<x1-x0<=14400 or not 0<y1-y0<=14400: fail('PDF_GEOMETRY_LIMIT','crop dimensions exceed review bounds','$.source')
        corners=[(s*(a*x+c*y),s*(b*x+d*y)) for x in (x0,x1) for y in (y0,y1)]
        pixel=[math.floor(min(p[0] for p in corners)+.001),math.floor(min(p[1] for p in corners)+.001),
               math.ceil(max(p[0] for p in corners)-.001),math.ceil(max(p[1] for p in corners)-.001)]
        w,h=pixel[2]-pixel[0],pixel[3]-pixel[1];total+=w*h
        if not 1<=w<=4096 or not 1<=h<=4096 or total>16777216: fail('PDF_PIXEL_LIMIT','reduce DPI/page selection to fit combined RGB budget','$.dpi')
        dimensions.append((pixel,w,h))
    return dimensions


def inspect(directory,prepared):
    before=read(directory,'inspect.stdout'); produced=read(directory,'render.stdout'); reopened=read(directory,'readback.stdout')
    dimensions=geometry(before,prepared)
    metadata(produced,prepared,True);metadata(reopened,prepared,True)
    if produced!=reopened or produced['pageCount']!=before['pageCount']: fail('VERIFICATION_FAILED','fresh native source readback differs')
    summaries=[]
    for i,(original,page,dimension) in enumerate(zip(before['pages'],produced['pages'],dimensions),1):
        if {k:page[k] for k in original}!=original: fail('VERIFICATION_FAILED','metadata differs from preflight')
        pixel,w,h=dimension
        if page['pixelBounds']!=pixel or not isinstance(page['text'],str): fail('VERIFICATION_FAILED','native geometry/text differs')
        name=f'page-{i:03d}';decoded=png(bounded(directory/(name+'.png')),prepared['dpi'])
        if decoded!=pnm(bounded(directory/(name+'.pnm'))) or decoded[:2]!=(w,h): fail('VERIFICATION_FAILED','PNG differs from fresh native RGB readback',name)
        if bounded(directory/(name+'.txt')).decode('utf-8')!=page['text']: fail('VERIFICATION_FAILED','extracted text differs from fresh source readback',name)
        summaries.append({**original,**pixel_digest(decoded),'textCharacters':len(page['text'])})
    required={f'page-{i:03d}{ext}' for i in range(1,len(dimensions)+1) for ext in ('.png','.pnm','.txt')}
    sidecars={name+'.metadata.json' for name in required if name.endswith(('.png','.txt'))}
    if {p.name for p in directory.glob('page-*') if p.name not in sidecars}!=required: fail('VERIFICATION_FAILED','unexpected or missing page output')
    return {'pageCount':before['pageCount'],'selectedPages':len(dimensions),'dpi':prepared['dpi'],'rotation':prepared['rotation'],
        'sourceSha256':digest(directory,'source.pdf'),'pages':summaries,'losses':LOSSES}


def artifacts(directory,prepared):
    names=[(f'page-{i:03d}'+ext,kind) for i in range(1,len(prepared['pages'])+1) for ext,kind in (('.png','image'),('.txt','text'))]
    names.append(('review-summary.json','text'))
    return [{'file':str(directory/name),'kind':kind,'sha256':digest(directory,name)} for name,kind in names]


def evidence_names(prepared):
    names={'authored.json','plan.json','source.pdf','capture.json'}
    for stage in ('version','inspect','render','readback'):
        names.update(stage+suffix for suffix in ('-launcher.py','-inputs.json','-submission.json','.stdout','.stderr'))
        if stage!='version': names.add(stage+'.js')
    names.update(f'page-{i:03d}.pnm' for i in range(1,len(prepared['pages'])+1))
    return names


def run(document,directory,*,executable=None,timeout=300):
    prepared=plan(document)
    executable=executable or os.environ.get('SCHEMAXIS_MUPDF') or shutil.which('mutool')
    if not executable or not Path(executable).is_absolute() or not os.access(executable,os.X_OK): fail('INTERPRETER_NOT_FOUND','configure an absolute MuPDF 1.28.5 mutool executable')
    if os.name!='posix': fail('UNSUPPORTED_PLATFORM','this qualification requires POSIX native resource caps')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=3600: fail('INVALID_ARGUMENT','timeout must be finite and in (0,3600]')
    directory=Path(directory).absolute()
    if directory.exists() or directory.is_symlink(): fail('OUTPUT_EXISTS','select a fresh PDF review directory',str(directory))
    directory.mkdir(parents=True);atomic_json(directory/'authored.json',document);atomic_json(directory/'plan.json',prepared)
    atomic_json(directory/'result.json',{'status':'incomplete','verified':False});deadline=time.monotonic()+timeout
    try:
        data=bounded(prepared['source'],'INVALID_PDF_SOURCE',16*1024*1024)
        if not data.startswith(b'%PDF-'): fail('INVALID_PDF_SOURCE','select a PDF file with its standard header','$.source')
        (directory/'source.pdf').write_bytes(data)
        atomic_json(directory/'capture.json',{'source':prepared['source'],'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
        native=commands(str(executable));launch(directory,'version',native['version'],deadline)
        runtime=(bounded(directory/'version.stdout')+bounded(directory/'version.stderr')).decode().strip()
        if runtime!='mutool version 1.28.5': fail('UNSUPPORTED_RUNTIME','this route is qualified against MuPDF 1.28.5; configure that stable runtime')
        for stage in ('inspect','render','readback'):
            (directory/(stage+'.js')).write_text(source(prepared,stage));launch(directory,stage,native[stage],deadline)
            if stage=='inspect': geometry(read(directory,'inspect.stdout'),prepared)
        for i,page in enumerate(read(directory,'render.stdout')['pages'],1):
            (directory/f'page-{i:03d}.txt').write_text(page['text'],encoding='utf-8')
        atomic_json(directory/'review-summary.json',inspect(directory,prepared))
        atomic_json(directory/'verification.json',{'artifacts':artifacts(directory,prepared),'evidence':{name:digest(directory,name) for name in sorted(evidence_names(prepared))},
            'executable':str(executable),'runtime':runtime})
        result=verify(directory,require_result=False)
        if cancellation_requested(): fail('RUNNER_CANCELLED','PDF review publication cancelled')
        if time.monotonic()>=deadline: fail('RUNNER_TIMED_OUT','PDF review exhausted its total deadline')
        result['status']='succeeded';atomic_json(directory/'result.json',result);return result
    except Exception as error:
        if not isinstance(error,SchemaxisError):
            try: fail('NATIVE_EXECUTION_FAILED',str(error))
            except SchemaxisError as wrapped:error=wrapped
        atomic_json(directory/'result.json',{'status':'failed','verified':False,'fault':error.fault.to_dict()});raise error


def verify(directory,require_result=True):
    directory=Path(directory).absolute()
    try:
        prepared=plan(read(directory,'authored.json'));receipt=read(directory,'verification.json')
        if read(directory,'plan.json')!=prepared: fail('VERIFICATION_FAILED','effective PDF plan differs')
        if require_result and read(directory,'result.json').get('status')!='succeeded': fail('INCOMPLETE_EXECUTION','PDF review did not complete')
        data=bounded(directory/'source.pdf',limit=16*1024*1024)
        if read(directory,'capture.json')!={'source':prepared['source'],'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}:
            fail('VERIFICATION_FAILED','captured PDF source binding differs')
        executable=receipt['executable']
        if not isinstance(executable,str) or not Path(executable).is_absolute(): fail('VERIFICATION_FAILED','absolute executable identity required')
        runtime=(bounded(directory/'version.stdout')+bounded(directory/'version.stderr')).decode().strip()
        if runtime!='mutool version 1.28.5' or receipt['runtime']!=runtime: fail('VERIFICATION_FAILED','MuPDF runtime identity differs')
        for stage,command in commands(executable).items():
            script=directory/(stage+'-launcher.py');submission=read(directory,stage+'-submission.json')
            interpreter=submission.get('interpreter',{}).get('executable')
            if not isinstance(interpreter,str) or not Path(interpreter).is_absolute() or submission.get('nativeCommand')!=[interpreter,str(script)] or type(submission.get('exitCode'))is not int or submission['exitCode']!=0:
                fail('VERIFICATION_FAILED','native command/completion differs',stage)
            if bounded(script).decode()!=launcher(directory,stage,command): fail('VERIFICATION_FAILED','trusted native launcher differs',stage)
            names=[] if stage=='version' else ['source.pdf',stage+'.js']
            if read(directory,stage+'-inputs.json')!={name:digest(directory,name) for name in names}: fail('VERIFICATION_FAILED','consumed source/script binding differs',stage)
            if stage!='version' and bounded(directory/(stage+'.js')).decode()!=source(prepared,stage): fail('VERIFICATION_FAILED','trusted native script differs',stage)
        if read(directory,'review-summary.json')!=inspect(directory,prepared): fail('VERIFICATION_FAILED','review summary differs')
        if receipt['artifacts']!=artifacts(directory,prepared): fail('VERIFICATION_FAILED','publication membership/digest differs')
        if set(receipt['evidence'])!=evidence_names(prepared): fail('VERIFICATION_FAILED','native evidence membership differs')
        for name in evidence_names(prepared):
            if digest(directory,name)!=receipt['evidence'][name]: fail('VERIFICATION_FAILED','retained native evidence differs',name)
        return {'verified':True,'artifacts':len(receipt['artifacts']),'runtime':runtime,'selectedPages':len(prepared['pages'])}
    except (OSError,ValueError,KeyError,TypeError,IndexError,AttributeError,UnicodeError) as error:
        fail('VERIFICATION_FAILED','invalid retained PDF evidence: '+str(error))


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
