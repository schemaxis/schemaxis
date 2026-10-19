"""Declarative dimensioned plates/spacers with independently checked solids."""
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

from schemaxis.artifacts import atomic_json
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute
from . import geometry

VERSION='schemaxis.openscad/1'
LIMIT=4*1024*1024
DIM={'type':'number','minimum':.5,'maximum':200,'required':True}
COORD={'type':'number','minimum':-100,'maximum':200}
HOLE={'type':'object','properties':{'centre':{'type':'array','items':COORD,'minItems':2,'maxItems':2,'required':True},'diameter':DIM}}
PLATE={'type':'object','required':True,'properties':{'width':DIM,'depth':DIM,'height':{**DIM,'maximum':100},'holes':{'type':'array','items':HOLE,'maxItems':16,'default':[]}}}
SPACER={'type':'object','required':True,'properties':{'outerDiameter':DIM,'boreDiameter':DIM,'height':{**DIM,'maximum':100}}}
COMMON={'units':{'type':'enum','values':['mm'],'required':True},'segments':{'type':'integer','minimum':16,'maximum':256,'default':64},'translation':{'type':'array','items':{'type':'number','minimum':-100,'maximum':100},'minItems':3,'maxItems':3,'default':[0,0,0]}}
OPTIONS={'plate':{**COMMON,'plate':PLATE},'spacer':{**COMMON,'spacer':SPACER}}
DECLARATIONS={name:{'native':native,'kinds':['geometry','text'],'inputs':{},'options':{k:{'value':v} for k,v in OPTIONS[name].items()}} for name,native in [('plate','difference / cube / translated cylinder through-holes'),('spacer','difference / concentric cylinders')]}
LOSSES=['All dimensions are millimetres; STL itself carries no units. Explicit mm handoff is required.',
 'Circular walls are inscribed regular polygons with 16–256 segments divisible by four. Bore across-flats diameter is diameter*cos(pi/segments); nominal diameter is across vertices. No exact circles or machining tolerance claim.',
 'Plate holes are strictly interior and separated by at least 0.5 mm; spacer radial wall is at least 0.5 mm. No tangency, blind holes, chamfers, arbitrary CSG, SCAD input, scripts, libraries or imported geometry.',
 'One connected closed genus-N polygon extrusion is checked: allowed contour corners/facets, planar crossings, directed edge pairing, outward normals, bounds and faceted volume. This is geometry evidence, not strength, manufacturing or printer suitability certification.',
 'Absolute coordinate magnitude is at most 300 mm with minimum 0.5 mm features. Native CGAL and float32 export approximation is checked at 0.00004 mm coordinates and 0.0002 relative volume. Ideal circle error is reported separately.']


def plan(document):
    if document.get('version')!=VERSION:fail('UNSUPPORTED_VERSION','select '+VERSION,'$.version')
    operation=document.get('operation')
    if operation not in OPTIONS:fail('UNKNOWN_FILTER','select plate or spacer','$.operation')
    opts=OPTIONS[operation];keys(document,('version','operation',*opts),'$')
    p=validate_arguments(opts,{k:v for k,v in document.items() if k in opts},location='$')
    if p['segments']%4:fail('INVALID_CAD_RESOLUTION','segments must be divisible by four for cardinal bounds','$.segments')
    q=p[operation]
    if operation=='plate':
        for i,h in enumerate(q['holes']):
            x,y=h['centre'];r=h['diameter']/2;at=f'$.plate.holes[{i}]'
            if min(x-r,y-r,q['width']-x-r,q['depth']-y-r)<.5:fail('INVALID_CAD_CLEARANCE','keep each nominal hole at least 0.5 mm inside every plate edge',at)
            for other in q['holes'][:i]:
                if math.dist(h['centre'],other['centre'])-(h['diameter']+other['diameter'])/2<.5:fail('INVALID_CAD_CLEARANCE','keep nominal circular holes separated by at least 0.5 mm',at)
    elif q['outerDiameter']-q['boreDiameter']<1:fail('INVALID_CAD_CLEARANCE','outer diameter must exceed bore diameter by at least 1 mm','$.spacer.boreDiameter')
    return {'version':'schemaxis.openscad.plan/1','operation':operation,**p,'losses':LOSSES}


def schema():
    from schemaxis.schema import DRAFT,argument_schema,object_schema
    props={'version':{'const':VERSION},'operation':{'enum':['plate','spacer']},**{k:argument_schema(v) for k,v in COMMON.items()},'plate':argument_schema(PLATE),'spacer':argument_schema(SPACER)}
    branches=[{'properties':{'operation':{'const':n}},'required':[n],'not':{'required':[other]}} for n,other in [('plate','spacer'),('spacer','plate')]]
    return {'$schema':DRAFT,**object_schema(props,['version','operation','units']),'oneOf':branches}


def query(document):p=plan(document);return [p['operation']],{}
def reusableInputs(document):plan(document);return {}
def resources(document,execution,identity):
    if execution.get('threads',1)!=1:fail('INVALID_EXECUTION','OpenSCAD constructive part generation is serial',identity)
    return {'threads':1}


def bounded(path,limit=LIMIT):
    try:
        fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
        with os.fdopen(fd,'rb') as f:
            info=os.fstat(f.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size>limit:raise ValueError('not a bounded regular file')
            data=f.read(limit+1)
        if len(data)>limit:raise ValueError('byte budget exceeded')
        return data
    except (ValueError,OSError) as e:fail('VERIFICATION_FAILED','intact bounded regular evidence required: '+str(e),str(path))
def unique_object(pairs):
    result={}
    for k,v in pairs:
        if k in result:raise ValueError('duplicate JSON key '+k)
        result[k]=v
    return result
def read(directory,name):return json.loads(bounded(directory/name),object_pairs_hook=unique_object,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite JSON '+x)))
def digest(directory,name):return hashlib.sha256(bounded(directory/name)).hexdigest()


def scad(p):
    # Only validated numeric literals enter trusted templates. No authored code,
    # filenames, names, expressions, flags or native reflection cross this boundary.
    j=lambda v:json.dumps(v,allow_nan=False,separators=(',',':'))
    q=p[p['operation']];h=q['height'];result='translate('+j(p['translation'])+') difference() {\n'
    if p['operation']=='plate':
        result+='cube('+j([q['width'],q['depth'],h])+');\n'
        for hole in q['holes']:result+='translate('+j([*hole['centre'],-1])+') cylinder(h='+j(h+2)+',d='+j(hole['diameter'])+',$fn='+str(p['segments'])+');\n'
    else:
        result+='cylinder(h='+j(h)+',d='+j(q['outerDiameter'])+',$fn='+str(p['segments'])+');\n'
        result+='translate([0,0,-1]) cylinder(h='+j(h+2)+',d='+j(q['boreDiameter'])+',$fn='+str(p['segments'])+');\n'
    return result+'}\n'

REOPEN='import("part.stl",convexity=10);\n'
def commands(executable,directory):
    return {'version':[executable,'--version'],**{stage:[executable,'--hardwarnings','--export-format','binstl','-o',str(directory/out),str(directory/source)] for stage,out,source in [('construct','part.stl','part.scad'),('reopen','reopened.stl','reopen.scad')]}}
def stage_inputs(stage):return [] if stage=='version' else ['part.scad'] if stage=='construct' else ['part.stl','reopen.scad']
def launcher(directory,stage,command):
    return ('import hashlib,json,os,resource,stat\nfrom pathlib import Path\n'+f'command={command!r}\npaths={[str(directory/n) for n in stage_inputs(stage)]!r}\nbindings={{}}\n'
        +'resource.setrlimit(resource.RLIMIT_AS,(2147483648,2147483648))\nresource.setrlimit(resource.RLIMIT_FSIZE,(4194304,4194304))\nresource.setrlimit(resource.RLIMIT_CPU,(60,60))\n'
        +'for name in paths:\n    fd=os.open(name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_NONBLOCK",0))\n    with os.fdopen(fd,"rb") as stream:\n        info=os.fstat(stream.fileno())\n'
        +f'        if not stat.S_ISREG(info.st_mode) or info.st_size>{LIMIT}: raise ValueError("invalid native input")\n        data=stream.read({LIMIT+1})\n'
        +'    bindings[name]=hashlib.sha256(data).hexdigest()\n'
        +f'Path({str(directory/(stage+"-inputs.json"))!r}).write_text(json.dumps(bindings,sort_keys=True))\n'
        +'os.execve(command[0],command,{"LANG":"C","HOME":str(Path.cwd()),"QT_QPA_PLATFORM":"offscreen","PATH":"/usr/bin:/bin"})\n')
def artifacts(directory):return [{'file':str(directory/n),'kind':kind,'sha256':digest(directory,n)} for n,kind in [('part.stl','geometry'),('part.scad','text'),('part-summary.json','text')]]
def evidence_names():return {'authored.json','plan.json','reopen.scad','reopened.stl',*[s+x for s in ('version','construct','reopen') for x in ('-launcher.py','-inputs.json','-submission.json','.stdout','.stderr')]}
def runtime_identity(directory):
    if bounded(directory/'version.stdout') or bounded(directory/'version.stderr').decode().strip()!='OpenSCAD version 2021.01':fail('UNSUPPORTED_NATIVE_VERSION','configure stable OpenSCAD 2021.01; requalify other versions before execution')
    return 'OpenSCAD 2021.01'
def inspect(directory,p):
    allowed={'part.stl','part.scad','part-summary.json'}
    allowed|={name+'.metadata.json' for name in allowed}
    if {path.name for path in directory.glob('part*')}-allowed:fail('VERIFICATION_FAILED','unexpected part publication')
    source=bounded(directory/'part.stl');reopened=bounded(directory/'reopened.stl')
    result=geometry.inspect(source,p);other=geometry.inspect(reopened,p)
    for key in ('bounds','vertices','eulerCharacteristic'):
        if result[key]!=other[key]:fail('VERIFICATION_FAILED','fresh native reopen changed geometry: '+key)
    # Summation order can change the last bits, especially on Python 3.10/3.11.
    # Both representations already passed the independent analytic-volume check;
    # this much tighter bound accommodates arithmetic, never a shape tolerance.
    if not math.isclose(result['volume'],other['volume'],rel_tol=1e-12,abs_tol=1e-12):
        fail('VERIFICATION_FAILED','fresh native reopen changed geometry: volume')
    if geometry.canonical_triangles(source)!=geometry.canonical_triangles(reopened):
        fail('VERIFICATION_FAILED','fresh native reopen changed oriented triangle surface')
    for stage in ('construct','reopen'):
        if bounded(directory/(stage+'.stdout')) or re.search(r'WARNING|ERROR|DEPRECATED',bounded(directory/(stage+'.stderr')).decode(errors='strict')):fail('VERIFICATION_FAILED','native warning or unexpected standard output')
    return {**result,'operation':p['operation'],'losses':LOSSES}


def run(document,directory,*,executable=None,timeout=300):
    p=plan(document);executable=executable or os.environ.get('SCHEMAXIS_OPENSCAD') or shutil.which('openscad')
    if not executable or not Path(executable).is_absolute() or not os.access(executable,os.X_OK):fail('INTERPRETER_NOT_FOUND','configure an absolute OpenSCAD 2021.01 executable')
    if os.name!='posix':fail('UNSUPPORTED_PLATFORM','this qualified route requires POSIX resource caps')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=3600:fail('INVALID_ARGUMENT','timeout must be finite in (0,3600]')
    directory=Path(directory).absolute()
    if directory.exists() or directory.is_symlink():fail('OUTPUT_EXISTS','select a fresh output directory',str(directory))
    directory.mkdir(parents=True);atomic_json(directory/'authored.json',document);atomic_json(directory/'plan.json',p);atomic_json(directory/'result.json',{'status':'incomplete','verified':False});deadline=time.monotonic()+timeout
    try:
        (directory/'part.scad').write_text(scad(p));(directory/'reopen.scad').write_text(REOPEN)
        for stage,command in commands(str(executable),directory).items():
            path=directory/(stage+'-launcher.py');path.write_text(launcher(directory,stage,command))
            execute([sys.executable,str(path)],directory,stage,deadline-time.monotonic(),{'LANG':'C','HOME':str(directory)})
            if stage=='version':runtime_identity(directory)
        atomic_json(directory/'part-summary.json',inspect(directory,p))
        atomic_json(directory/'verification.json',{'executable':str(executable),'runtime':runtime_identity(directory),'artifacts':artifacts(directory),'evidence':{n:digest(directory,n) for n in evidence_names()}})
        result=verify(directory,require_result=False)
        if cancellation_requested():fail('RUNNER_CANCELLED','OpenSCAD publication cancelled')
        if time.monotonic()>=deadline:fail('RUNNER_TIMED_OUT','OpenSCAD exhausted total deadline')
        result['status']='succeeded';atomic_json(directory/'result.json',result);return result
    except Exception as e:
        if not isinstance(e,SchemaxisError):
            try:fail('NATIVE_EXECUTION_FAILED',str(e))
            except SchemaxisError as wrapped:e=wrapped
        atomic_json(directory/'result.json',{'status':'failed','verified':False,'fault':e.fault.to_dict()});raise e


def verify(directory,require_result=True):
    directory=Path(directory).absolute()
    try:
        p=plan(read(directory,'authored.json'));receipt=read(directory,'verification.json')
        if read(directory,'plan.json')!=p:fail('VERIFICATION_FAILED','effective CAD plan differs')
        if require_result and read(directory,'result.json').get('status')!='succeeded':fail('INCOMPLETE_EXECUTION','OpenSCAD did not complete')
        if bounded(directory/'part.scad').decode()!=scad(p) or bounded(directory/'reopen.scad').decode()!=REOPEN:fail('VERIFICATION_FAILED','trusted native source differs from declared part')
        executable=receipt['executable']
        if not isinstance(executable,str) or not Path(executable).is_absolute():fail('VERIFICATION_FAILED','native executable identity must be absolute')
        for stage,command in commands(executable,directory).items():
            submission=read(directory,stage+'-submission.json');interpreter=submission.get('interpreter',{}).get('executable');path=directory/(stage+'-launcher.py')
            if not isinstance(interpreter,str) or not Path(interpreter).is_absolute() or submission.get('nativeCommand')!=[interpreter,str(path)] or type(submission.get('exitCode')) is not int or submission['exitCode']!=0:fail('VERIFICATION_FAILED','native command/completion differs',stage)
            if bounded(path).decode()!=launcher(directory,stage,command):fail('VERIFICATION_FAILED','trusted native launcher differs',stage)
            if read(directory,stage+'-inputs.json')!={str(directory/n):digest(directory,n) for n in stage_inputs(stage)}:fail('VERIFICATION_FAILED','native input binding differs',stage)
        runtime=runtime_identity(directory)
        if receipt['runtime']!=runtime:fail('VERIFICATION_FAILED','native runtime identity differs')
        if read(directory,'part-summary.json')!=inspect(directory,p):fail('VERIFICATION_FAILED','summary differs from independent inspection')
        if receipt['artifacts']!=artifacts(directory):fail('VERIFICATION_FAILED','publication membership/digests differ')
        if set(receipt['evidence'])!=evidence_names():fail('VERIFICATION_FAILED','evidence membership differs')
        for n in evidence_names():
            if digest(directory,n)!=receipt['evidence'][n]:fail('VERIFICATION_FAILED','retained native evidence differs',n)
        return {'verified':True,'artifacts':3,'runtime':runtime}
    except (OSError,ValueError,KeyError,TypeError,IndexError,AttributeError) as e:fail('VERIFICATION_FAILED','invalid retained CAD evidence: '+str(e))

from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
