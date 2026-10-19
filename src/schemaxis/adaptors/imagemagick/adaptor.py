"""Closed PNG preparation recipes, isolated ImageMagick, independent exact pixels."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import time
from collections import Counter
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from schemaxis.artifacts import atomic_json
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail,keys
from schemaxis.native_command import execute
from . import png

VERSION='schemaxis.imagemagick/1'
INT={'type':'integer','minimum':0,'maximum':4096}
RGB={'type':'array','items':{'type':'integer','minimum':0,'maximum':255},'minItems':3,'maxItems':3}
CROP={'type':'object','properties':{'x':{**INT,'required':True},'y':{**INT,'required':True},'width':{**INT,'minimum':1,'required':True},'height':{**INT,'minimum':1,'required':True}}}
ITEM={'type':'object','properties':{'id':{'type':'string','minLength':1,'maxLength':40,'required':True},'source':{'type':'string','minLength':1,'maxLength':4096,'required':True},'crop':CROP,'scale':{'type':'integer','minimum':1,'maximum':8,'default':1},'quarterTurns':{'type':'integer','minimum':0,'maximum':3,'default':0}}}
SHEET={'type':'object','properties':{'columns':{'type':'integer','minimum':1,'maximum':8,'default':2},'padding':{'type':'integer','minimum':0,'maximum':64,'default':8},'background':{**RGB,'default':[255,255,255]}}}
OPTIONS={'images':{'type':'array','items':ITEM,'minItems':1,'maxItems':8,'required':True},'colourPolicy':{'type':'enum','values':['require-srgb','assume-srgb'],'default':'require-srgb'},'alpha':{'type':'enum','values':['preserve','flatten'],'default':'preserve'},'background':{**RGB,'default':[255,255,255]},'sheet':SHEET}
DECLARATIONS={'raster':{'native':'magick: -crop +repage -sample -rotate -alpha remove; -compose Copy -composite; PNG coder','kinds':['image','text'],'inputs':{},'options':{k:{'value':v} for k,v in OPTIONS.items()}}}
LOSSES=['RGB/RGBA8 non-interlaced PNG only; no palette/greyscale/16-bit, APNG, ICC, compressed metadata or non-sRGB colour declarations.',
    'No colour conversion: preserve sRGB encoded channel samples, or explicitly assume untagged samples are sRGB; metadata and physical pixel resolution are stripped.',
    'Crop is exact top-left pixels; magnification is integer nearest-neighbour; rotation is clockwise quarter turns. No interpolation, downsampling or arbitrary angles.',
    'Preserve retains every RGBA sample including RGB beneath zero alpha. Flatten blends encoded sRGB channels, not linear light: round((channel*alpha+background*(255-alpha))/255).',
    'Optional sheet copies tiles including alpha, at top-left of equal cells on an opaque background. Index/IDs/positions are in raster-summary.json; there are no visual labels or typography.',
    'One serial isolated native process at a time; no arbitrary options, scripts, expressions, formats, delegates or network inputs.']


def plan(document):
    keys(document,('version','operation',*OPTIONS),'$')
    if document.get('version')!=VERSION: fail('UNSUPPORTED_VERSION','expected '+VERSION)
    if document.get('operation')!='raster': fail('UNKNOWN_FILTER','select raster','$.operation')
    p=validate_arguments(OPTIONS,{k:v for k,v in document.items() if k in OPTIONS})
    ids=set();pixels=0
    for i,item in enumerate(p['images']):
        at=f'$.images[{i}]';name=item['id'];source=item['source']
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,39}',name) or name in ids: fail('INVALID_RASTER_ID','use distinct ASCII identifiers beginning with a letter',at+'.id')
        ids.add(name)
        if not Path(source).is_absolute() or Path(source).suffix.lower()!='.png' or '\0' in source: fail('INVALID_RASTER_SOURCE','select an absolute local regular .png file; no URLs or format prefixes',at+'.source')
        if 'crop' in item:
            c=item['crop'];w=c['width']*item['scale'];h=c['height']*item['scale']
            if w>4096 or h>4096: fail('RASTER_PIXEL_BUDGET','scaled crop exceeds 4096 per side',at+'.scale')
            pixels+=w*h
    if pixels>png.PIXELS: fail('RASTER_PIXEL_BUDGET','combined output pixel budget is 1048576','$.images')
    if 'sheet' in p and p['sheet']['columns']>len(p['images']): fail('INVALID_RASTER_SHEET','columns cannot exceed the image count','$.sheet.columns')
    if p['alpha']=='preserve' and p['background']!=[255,255,255]: fail('INVALID_RASTER_ALPHA','background only affects flatten; omit it when preserving alpha','$.background')
    return {'version':'schemaxis.imagemagick.plan/1','operation':'raster',**p,'losses':LOSSES}


def schema():
    from schemaxis.schema import DRAFT,argument_schema,object_schema
    return {'$schema':DRAFT,**object_schema({'version':{'const':VERSION},'operation':{'const':'raster'},**{k:argument_schema(v) for k,v in OPTIONS.items()}},['version','operation','images'])}


def query(document): plan(document);return ['raster'],{}


def resources(document,execution,identity):
    if execution.get('threads',1)!=1: fail('INVALID_EXECUTION','raster preparation supports one serial thread',identity)
    return {'threads':1}


def bounded(path,code='VERIFICATION_FAILED',limit=png.BYTES):
    try:
        fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
        with os.fdopen(fd,'rb') as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size>limit: raise ValueError('not a bounded regular file')
            data=stream.read(limit+1)
        if len(data)>limit: raise ValueError('byte budget exceeded')
        return data
    except (OSError,ValueError) as error: fail(code,'select an intact regular file within 8MiB: '+str(error),str(path))


def source_image(data,p,at):
    im=png.decode(data)
    if p['colourPolicy']=='require-srgb' and im[3].startswith('untagged'): fail('RASTER_COLOUR_REQUIRED','PNG needs sRGB or standard gAMA+cHRM; explicitly choose assume-srgb for untagged encoded samples',at)
    return im


def reusableInputs(document):
    p=plan(document);result={};total=0
    for i,item in enumerate(p['images']):
        data=bounded(item['source'],'INVALID_RASTER_SOURCE');im=source_image(data,p,f'$.images[{i}].source');total+=im[0]*im[1]
        if total>png.PIXELS: fail('RASTER_PIXEL_BUDGET','combined input pixel budget is 1048576','$.images')
        result[item['source']]=hashlib.sha256(data).hexdigest()
    return result


def expected(directory,p):
    images=[];observations=[];total=0
    for i,item in enumerate(p['images']):
        data=bounded(directory/f'captured-{i:02}.png');im=source_image(data,p,f'$.images[{i}].source');total+=im[0]*im[1]
        if total>png.PIXELS: fail('RASTER_PIXEL_BUDGET','combined input pixel budget exceeded')
        try: transformed=png.transform(im,item,p['alpha'],p['background'])
        except SchemaxisError as error:
            if error.fault.code=='RASTER_CROP_OUTSIDE': fail(error.fault.code,error.fault.message,f'$.images[{i}].crop')
            raise
        images.append(transformed)
        observations.append({'index':i,'id':item['id'],'file':f'image-{i:02}.png','source':item['source'],'inputDimensions':[im[0],im[1]],'colourDeclaration':im[3],'dimensions':[transformed[0],transformed[1]],'rgbaSha256':hashlib.sha256(transformed[2]).hexdigest()})
    combined=sum(im[0]*im[1] for im in images);sheet=None;places=[];canvas=None
    if 'sheet' in p:
        sheet,places,canvas=png.layout(images,p['sheet']);combined+=sheet[0]*sheet[1]
    if combined>png.PIXELS: fail('RASTER_PIXEL_BUDGET','all image publications plus sheet together exceed 1048576 pixels','$.images')
    return images,sheet,canvas,{'images':observations,'sheet':None if sheet is None else {'file':'sheet.png','dimensions':[sheet[0],sheet[1]],'placements':places,'rgbaSha256':hashlib.sha256(sheet[2]).hexdigest()},'outputPixels':combined,'alpha':p['alpha'],'colourPolicy':p['colourPolicy'],'verification':'Independent stdlib PNG decode and exact comparison of every RGBA sample; no ImageMagick readback oracle.'}


def policy(directory,p):
    names=[f'captured-{i:02}.png' for i in range(len(p['images']))]+[f'image-{i:02}.png' for i in range(len(p['images']))]
    if 'sheet' in p:names+=['canvas.png','sheet.png']
    lines=['<policymap>','<policy domain="delegate" rights="none" pattern="*"/>','<policy domain="filter" rights="none" pattern="*"/>',
        '<policy domain="module" rights="none" pattern="*"/>','<policy domain="module" rights="read|write" pattern="PNG"/>',
        '<policy domain="coder" rights="none" pattern="*"/>','<policy domain="coder" rights="read|write" pattern="PNG"/>',
        '<policy domain="path" rights="none" pattern="*"/>']
    lines += ['<policy domain="path" rights="'+('read' if n.startswith('captured-') or n=='canvas.png' else 'read|write')+'" pattern="'+escape(str(directory/n),{'"':'&quot;'})+'"/>' for n in names]
    for name,value in [('thread','1'),('time','60'),('memory','128MiB'),('map','0'),('disk','0'),('width','4096'),('height','4096'),('list-length','10')]:
        lines.append(f'<policy domain="resource" name="{name}" value="{value}"/>')
    lines+=['<policy domain="system" name="max-profile-size" value="64KiB"/>','</policymap>']
    return '\n'.join(lines)+'\n'


def commands(executable,directory,p,summary):
    args=lambda name:str(directory/name)
    output=['-strip','-set','colorspace','sRGB','-depth','8','-define','png:color-type=6','-define','png:exclude-chunk=all']
    result={'version':[executable,'-version'],'policy':[executable,'-list','policy']}
    for i,item in enumerate(p['images']):
        command=[executable,args(f'captured-{i:02}.png')]
        if 'crop' in item:
            c=item['crop'];command+=['-crop',f'{c["width"]}x{c["height"]}+{c["x"]}+{c["y"]}','+repage']
        if item['scale']!=1:command+=['-sample',f'{item["scale"]*100}%']
        if item['quarterTurns']:command+=['-rotate',str(item['quarterTurns']*90)]
        if p['alpha']=='flatten':command+=['-background','#'+''.join(f'{c:02x}' for c in p['background']),'-alpha','remove','-alpha','off']
        result[f'prepare-{i:02}']=command+['-alpha','on']+output+[args(f'image-{i:02}.png')]
    if summary['sheet']:
        command=[executable,args('canvas.png')]
        for place in summary['sheet']['placements']:
            command += [args(f'image-{place["index"]:02}.png'),'-geometry',f'+{place["x"]}+{place["y"]}','-compose','Copy','-composite']
        result['sheet']=command+output+[args('sheet.png')]
    return result


def inputs(stage,p):
    names=['config/policy.xml']
    if stage.startswith('prepare-'):names.append('captured-'+stage[-2:]+'.png')
    if stage=='sheet':names+=['canvas.png']+[f'image-{i:02}.png' for i in range(len(p['images']))]
    return names


def launcher(directory,stage,command,p):
    # A minimal child environment prevents per-user MAGICK_* path/module overrides.
    env={'LANG':'C','LC_ALL':'C','HOME':str(directory/'config'),'XDG_CONFIG_HOME':str(directory/'config'),'MAGICK_CONFIGURE_PATH':str(directory/'config'),'MAGICK_TEMPORARY_PATH':str(directory/'config'),'MAGICK_THREAD_LIMIT':'1'}
    return ('import hashlib,json,os,resource,stat\nfrom pathlib import Path\n'+f'command={command!r}\npaths={[str(directory/n) for n in inputs(stage,p)]!r}\nbindings={{}}\n'
        +'resource.setrlimit(resource.RLIMIT_AS,(1073741824,1073741824))\nresource.setrlimit(resource.RLIMIT_FSIZE,(16777216,16777216))\nresource.setrlimit(resource.RLIMIT_CPU,(60,60))\n'
        +'for name in paths:\n    fd=os.open(name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_NONBLOCK",0))\n    with os.fdopen(fd,"rb") as stream:\n        info=os.fstat(stream.fileno())\n'
        +f'        if not stat.S_ISREG(info.st_mode) or info.st_size>{png.BYTES}: raise ValueError("invalid captured native input")\n        data=stream.read({png.BYTES+1})\n'
        +'    bindings[name]=hashlib.sha256(data).hexdigest()\n'+f'Path({str(directory/(stage+"-inputs.json"))!r}).write_text(json.dumps(bindings,sort_keys=True))\nos.execve(command[0],command,{env!r})\n')


def check_policy_listing(directory,p,listing):
    """Reject later external overrides, extra native permissions or omitted rules."""
    observed=[];origin=None;current=None
    for line in listing.splitlines():
        if line.startswith('Path: '):
            origin=line[6:];current=None
        elif line.startswith('  Policy: '):
            current={'domain':line[10:].lower(),'origin':origin};observed.append(current)
        elif line.startswith('    ') and ': ' in line and current is not None:
            key,value=line.strip().split(': ',1);current[key]=value.strip()
        elif line.strip():fail('VERIFICATION_FAILED','unrecognized native policy listing')
    wanted=[]
    for node in ET.fromstring(policy(directory,p)):
        item={**node.attrib,'origin':str(directory/'config/policy.xml')}
        if 'rights' in item:item['rights']=' '.join(s.title() for s in item['rights'].split('|'))
        wanted.append(item)
    wanted.append({'domain':'undefined','origin':'[built-in]','rights':'None'})
    canonical=lambda items:Counter(tuple(sorted(item.items())) for item in items)
    if canonical(observed)!=canonical(wanted):fail('VERIFICATION_FAILED','native policy permissions or origins differ from exact PNG-only policy')


def check_runtime(runtime):
    if not re.match(r'Version: ImageMagick 7\.\d+\.\d+-\d+ Q(?:8|16|32|64)(?:-HDRI)? ',runtime):
        fail('VERIFICATION_FAILED','require an observed ImageMagick 7 runtime identity')
    return runtime


def read(directory,name): return json.loads(bounded(directory/name))
def digest(directory,name): return hashlib.sha256(bounded(directory/name)).hexdigest()


def inspect(directory,p):
    images,sheet,canvas,summary=expected(directory,p)
    for n,expected_im in [(f'image-{i:02}.png',im) for i,im in enumerate(images)]+([('sheet.png',sheet)] if sheet else []):
        actual=png.decode(bounded(directory/n),output=True)
        if actual[:3]!=expected_im[:3]: fail('VERIFICATION_FAILED','native image differs from independent exact RGBA sample oracle',n)
    if sheet and bounded(directory/'canvas.png')!=png.encode(sheet[0],sheet[1],canvas):fail('VERIFICATION_FAILED','contact-sheet input canvas differs')
    return summary


def artifacts(directory,p):
    names=[(f'image-{i:02}.png','image') for i in range(len(p['images']))]
    if 'sheet' in p:names.append(('sheet.png','image'))
    names.append(('raster-summary.json','text'))
    return [{'file':str(directory/n),'kind':kind,'sha256':digest(directory,n)} for n,kind in names]


def evidence_names(p,cmds):
    return {'authored.json','plan.json','captures.json','config/policy.xml',*[f'captured-{i:02}.png' for i in range(len(p['images']))],*(['canvas.png'] if 'sheet' in p else []),*[stage+suffix for stage in cmds for suffix in ('-launcher.py','-inputs.json','-submission.json','.stdout','.stderr')]}


def run(document,directory,*,executable=None,timeout=300):
    p=plan(document);executable=executable or os.environ.get('SCHEMAXIS_IMAGEMAGICK') or shutil.which('magick')
    if not executable or not Path(executable).is_absolute() or not os.access(executable,os.X_OK): fail('INTERPRETER_NOT_FOUND','configure an absolute ImageMagick 7 magick executable with built-in PNG support')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=3600:fail('INVALID_ARGUMENT','timeout must be finite in (0,3600]')
    directory=Path(directory).absolute()
    if any(c in str(directory) for c in '*?[]{}'):
        fail('INVALID_ARGUMENT','output directory cannot contain native policy glob metacharacters',str(directory))
    if directory.exists() or directory.is_symlink():fail('OUTPUT_EXISTS','select a fresh output directory',str(directory))
    directory.mkdir(parents=True);atomic_json(directory/'authored.json',document);atomic_json(directory/'plan.json',p);atomic_json(directory/'result.json',{'status':'incomplete','verified':False});deadline=time.monotonic()+timeout
    try:
        captures=[]
        for i,item in enumerate(p['images']):
            data=bounded(item['source'],'INVALID_RASTER_SOURCE');source_image(data,p,f'$.images[{i}].source');(directory/f'captured-{i:02}.png').write_bytes(data)
            captures.append({'source':item['source'],'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)})
        atomic_json(directory/'captures.json',captures)
        images,sheet,canvas,summary=expected(directory,p)
        if sheet:(directory/'canvas.png').write_bytes(png.encode(sheet[0],sheet[1],canvas))
        (directory/'config').mkdir();(directory/'config/policy.xml').write_text(policy(directory,p))
        cmds=commands(str(executable),directory,p,summary)
        for stage,command in cmds.items():
            path=directory/(stage+'-launcher.py');path.write_text(launcher(directory,stage,command,p));execute([sys.executable,str(path)],directory,stage,deadline-time.monotonic())
            if stage=='version':check_runtime(bounded(directory/'version.stdout').decode().strip())
            if stage=='policy':check_policy_listing(directory,p,bounded(directory/'policy.stdout').decode())
        atomic_json(directory/'raster-summary.json',inspect(directory,p));runtime=bounded(directory/'version.stdout').decode().strip()
        atomic_json(directory/'verification.json',{'executable':str(executable),'runtime':runtime,'artifacts':artifacts(directory,p),'evidence':{n:digest(directory,n) for n in evidence_names(p,cmds)}})
        result=verify(directory,require_result=False)
        if cancellation_requested():fail('RUNNER_CANCELLED','raster publication cancelled')
        if time.monotonic()>=deadline:fail('RUNNER_TIMED_OUT','raster exhausted its total deadline')
        result['status']='succeeded';atomic_json(directory/'result.json',result);return result
    except Exception as error:
        if not isinstance(error,SchemaxisError):
            try:fail('NATIVE_EXECUTION_FAILED',str(error))
            except SchemaxisError as wrapped:error=wrapped
        atomic_json(directory/'result.json',{'status':'failed','verified':False,'fault':error.fault.to_dict()});raise error


def verify(directory,require_result=True):
    directory=Path(directory).absolute()
    try:
        p=plan(read(directory,'authored.json'));receipt=read(directory,'verification.json')
        if read(directory,'plan.json')!=p:fail('VERIFICATION_FAILED','effective raster plan differs')
        if require_result and read(directory,'result.json').get('status')!='succeeded':fail('INCOMPLETE_EXECUTION','raster did not complete')
        captures=[{'source':item['source'],'sha256':digest(directory,f'captured-{i:02}.png'),'bytes':len(bounded(directory/f'captured-{i:02}.png'))} for i,item in enumerate(p['images'])]
        if read(directory,'captures.json')!=captures:fail('VERIFICATION_FAILED','PNG source/capture binding differs')
        summary=inspect(directory,p)
        if read(directory,'raster-summary.json')!=summary:fail('VERIFICATION_FAILED','raster summary differs')
        if bounded(directory/'config/policy.xml').decode()!=policy(directory,p):fail('VERIFICATION_FAILED','isolated native security policy differs')
        executable=receipt['executable']
        if not isinstance(executable,str) or not Path(executable).is_absolute():fail('VERIFICATION_FAILED','native executable identity must be absolute')
        cmds=commands(executable,directory,p,summary)
        for stage,command in cmds.items():
            submission=read(directory,stage+'-submission.json');interpreter=submission.get('interpreter',{}).get('executable');path=directory/(stage+'-launcher.py')
            if not isinstance(interpreter,str) or not Path(interpreter).is_absolute() or submission.get('nativeCommand')!=[interpreter,str(path)] or type(submission.get('exitCode')) is not int or submission['exitCode']!=0:fail('VERIFICATION_FAILED','native command/completion differs',stage)
            if bounded(path).decode()!=launcher(directory,stage,command,p):fail('VERIFICATION_FAILED','trusted native launcher differs',stage)
            if read(directory,stage+'-inputs.json')!={str(directory/n):digest(directory,n) for n in inputs(stage,p)}:fail('VERIFICATION_FAILED','native raster input binding differs',stage)
        runtime=bounded(directory/'version.stdout').decode().strip()
        check_runtime(runtime)
        if receipt['runtime']!=runtime:fail('VERIFICATION_FAILED','ImageMagick 7 runtime identity differs')
        listing=bounded(directory/'policy.stdout').decode()
        check_policy_listing(directory,p,listing)
        if receipt['artifacts']!=artifacts(directory,p):fail('VERIFICATION_FAILED','raster publication membership/digest differs')
        names=evidence_names(p,cmds)
        if set(receipt['evidence'])!=names:fail('VERIFICATION_FAILED','native evidence membership differs')
        for n in names:
            if digest(directory,n)!=receipt['evidence'][n]:fail('VERIFICATION_FAILED','retained native evidence differs',n)
        return {'verified':True,'artifacts':len(receipt['artifacts']),'runtime':runtime,'images':len(p['images']),'outputPixels':summary['outputPixels']}
    except (OSError,ValueError,KeyError,TypeError,IndexError,AttributeError) as error:fail('VERIFICATION_FAILED','invalid retained raster evidence: '+str(error))


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
