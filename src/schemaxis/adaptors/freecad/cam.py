"""Checked three-axis milling intent, frozen solid admission and durable execution."""
import copy
import json
import os
from pathlib import Path
from schemaxis.artifacts import atomic_json,runtime_archive
from schemaxis.core.faults import SchemaxisError,Fault
from schemaxis.core.runners import Interpreter
from .process import SubprocessRunner
from schemaxis.documents import resolve_document
from schemaxis.errors import fail,keys
from schemaxis.pipeline import name
from .solid_source import source_record,capture_source,digest,number as cad_number,vector as cad_vector
VERSION='schemaxis.freecad.cam/1'

def number(*a,**kw):return cad_number(*a,**kw,code='INVALID_MACHINING')
def vector(*a,**kw):return cad_vector(*a,**kw,code='INVALID_MACHINING')


def plan(document,*,captured=None,unread=False):
    document,_=resolve_document(copy.deepcopy(document));keys(document,('version','source','stock','tool','tools','operations','setup','quality','definitions','settings'),'$')
    raw_ops=document.get('operations')
    if isinstance(document.get('setup'),dict) and 'toolClearance' in document['setup']:
        from .cam_plan3 import plan as physical
        return physical(document,captured=captured,unread=unread)
    declared=document.get('tools',[]) if 'tools' in document else [document.get('tool')]
    if isinstance(declared,list) and any(isinstance(t,dict) and (t.get('kind')=='drill' or 'holder' in t) for t in declared):
        fail('UNSUPPORTED_TOOL_REACH','Pointed tools and holder envelopes require an explicit setup.toolClearance policy','$.setup.toolClearance')
    if 'tools' in document or isinstance(raw_ops,list) and any(isinstance(op,dict) and op.get('operation')=='drill' for op in raw_ops):
        from .cam_plan2 import plan as extended
        return extended(document,captured=captured,unread=unread)
    if document.get('version')!=VERSION:fail('UNSUPPORTED_VERSION','Expected '+VERSION)
    source=source_record(document.get('source'),captured=captured,unread=unread);bounds=source['bounds'];height=bounds[5]-bounds[4]
    stock=document.get('stock',{});keys(stock,('top','sides','bottom'),'$.stock')
    stock={k:number(stock.get(k,v),'$.stock.'+k,0,1000) for k,v in (('top',2),('sides',0),('bottom',0))}
    # A fixed pre-sized blank preserves a supported clamping base. Detaching an
    # external profile requires an explicit holding contract in a later family.
    if stock['sides'] or stock['bottom']:fail('UNSUPPORTED_HOLDING','This milling workflow uses a pre-sized blank with zero side and bottom allowance; external profiling needs a qualified holding strategy','$.stock')
    origin=[(bounds[0]+bounds[1])/2,(bounds[2]+bounds[3])/2,bounds[5]+stock['top']]
    stock_bounds=[bounds[0]-origin[0],bounds[1]-origin[0],bounds[2]-origin[1],bounds[3]-origin[1],bounds[4]-origin[2],0]
    tool=document.get('tool');keys(tool,('diameter','cuttingLength','length','shankDiameter','flutes','rpm','feed','plunge'),'$.tool')
    tool={k:number(tool.get(k,v),'$.tool.'+k,lo,hi) for k,v,lo,hi in (('diameter',None,.1,100),('cuttingLength',None,.1,1000),('length',None,.1,2000),('shankDiameter',None,.1,100),('flutes',2,1,12),('rpm',None,1,100000),('feed',None,.01,100000),('plunge',None,.01,100000))}
    if int(tool['flutes'])!=tool['flutes']:fail('INVALID_MACHINING','Flute count must be an integer','$.tool.flutes')
    if tool['cuttingLength']<height+stock['top'] or tool['length']<=tool['cuttingLength'] or tool['shankDiameter']>tool['diameter']:fail('UNSUPPORTED_TOOL_REACH','Use a centre-cutting straight endmill with cutting length reaching the entire blank, a longer overall length and shank no wider than the cutter','$.tool')
    setup=document.get('setup',{});keys(setup,('clearance','safe'),'$.setup');setup={k:number(setup.get(k,v),'$.setup.'+k,.1,1000) for k,v in (('clearance',5),('safe',3))}
    if setup['clearance']<setup['safe']:fail('INVALID_MACHINING','Clearance must be at or above the safe traverse plane','$.setup')
    quality=document.get('quality',{});keys(quality,('residualVolume','gougeVolume'),'$.quality')
    quality={k:number(quality.get(k,v),'$.quality.'+k,1e-5,1) for k,v in (('residualVolume',.1),('gougeVolume',.01))}
    raw=document.get('operations');operations=[];ids=set();faced=not stock['top']
    if not isinstance(raw,list) or not 1<=len(raw)<=16:fail('INVALID_MACHINING','Declare one to sixteen ordered milling operations','$.operations')
    for i,item in enumerate(raw):
        path='$.operations['+str(i)+']';keys(item,('id','operation','floor','stepDown','stepOver'),path);identity=name(item.get('id'),path+'.id');kind=item.get('operation')
        if identity in ids:fail('INVALID_MACHINING','Operation identities must be unique',path)
        ids.add(identity)
        if kind not in ('faceStock','pocket'):fail('INVALID_MACHINING','Choose faceStock or a closed flat-floor pocket',path+'.operation')
        op={'id':identity,'operation':kind,'stepDown':number(item.get('stepDown',min(tool['diameter']/2,2)),path+'.stepDown',.01,min(tool['diameter'],height+stock['top'])),'stepOver':number(item.get('stepOver',.5),path+'.stepOver',.05,.8)}
        if kind=='faceStock':
            if faced or i!=0 or 'floor' in item:fail('INVALID_MACHINING','Face the top allowance once, before pockets; the target is the source top plane',path)
            op.update(start=0,finish=-stock['top']);faced=True
        else:
            if not faced:fail('INVALID_MACHINING','Face the top stock allowance before pocketing',path)
            floor=vector(item.get('floor'),3,path+'.floor')
            if not bounds[4]+1e-5<floor[2]<bounds[5]-1e-5 or not bounds[0]<floor[0]<bounds[1] or not bounds[2]<floor[1]<bounds[3]:fail('INVALID_MACHINING','Select an interior point on an upward-facing pocket floor above the clamping base',path+'.floor')
            op.update(floor=floor,start=-stock['top'],finish=floor[2]-origin[2])
        operations.append(op)
    return {'version':'schemaxis.freecad.cam.plan/1','source':source,'stock':stock,'origin':origin,'stockBounds':stock_bounds,'tool':tool,'setup':setup,'quality':quality,'operations':operations,'postprocessor':'linuxcnc','units':'mm','frame':'stockTopCentre'}


def schema():
    from schemaxis.schema import object_schema as obj,DRAFT,json_value_schema
    from .drawing import schema as drawing_schema
    n={'type':'number'}
    base={'$schema':DRAFT,'$defs':{'json':json_value_schema()},**obj({'version':{'const':VERSION},'source':drawing_schema()['properties']['source'],
      'stock':obj({k:{'type':'number','minimum':0,'maximum':1000,'default':v} for k,v in (('top',2),('sides',0),('bottom',0))},[]),
      'tool':obj({k:{'type':'number','exclusiveMinimum':0,'maximum':v} for k,v in (('diameter',100),('cuttingLength',1000),('length',2000),('shankDiameter',100),('rpm',100000),('feed',100000),('plunge',100000))}|{'flutes':{'type':'integer','minimum':1,'maximum':12,'default':2}},['diameter','cuttingLength','length','shankDiameter','rpm','feed','plunge']),
      'setup':obj({k:{'type':'number','minimum':.1,'maximum':1000,'default':v} for k,v in (('clearance',5),('safe',3))},[]),
      'quality':obj({k:{'type':'number','minimum':1e-5,'maximum':1,'default':v} for k,v in (('residualVolume',.1),('gougeVolume',.01))},[]),
      'operations':{'type':'array','minItems':1,'maxItems':16,'items':obj({'id':{'type':'string','pattern':'^[A-Za-z][A-Za-z0-9_-]*$'},'operation':{'enum':['faceStock','pocket']},'floor':{'type':'array','items':n,'minItems':3,'maxItems':3},'stepDown':{'type':'number','minimum':.01},'stepOver':{'type':'number','minimum':.05,'maximum':.8,'default':.5}},['id','operation'])},**{k:{'$ref':'#/$defs/json'} for k in ('definitions','settings')}},['version','source','tool','operations'])}
    from .cam_schema2 import expand
    from .cam_schema3 import expand as physical
    return physical(expand(base))


def resources(document,spec,identity):
    from schemaxis.parallel import provisional
    _native_plan(provisional(document),unread=True);return {}
def reusableInputs(document):
    s=plan(document)['source'];return {s['file']:s['sha256']}
def retainedInputs(directory,document):
    directory=Path(directory);p=json.loads((directory/'plan.json').read_text())
    if p.get('version') in ('schemaxis.freecad.cam.plan/2','schemaxis.freecad.cam.plan/3'):
        from .cam_state2 import admit
        from .cam_evidence2 import same
        expected,_,_=admit(directory,p)
        if not same(plan(document,captured=directory/expected['source']['capture']),expected):
            fail('VERIFICATION_FAILED','Captured machining source or typed intent differs from current authored document')
        return {expected['source']['file']:expected['source']['sha256']}
    # Derive the legacy capture from the current caller's typed intent, never
    # an unchecked receipt filename. This remains independent of the retired
    # original source path and does not restore a native document.
    source=plan(document,unread=True)['source']['file']
    capture='source.FCStd' if Path(source).suffix.lower()=='.fcstd' else 'source.step'
    if plan(document,captured=directory/capture)!=p:fail('VERIFICATION_FAILED','Captured machining source differs from authored intent')
    return {p['source']['file']:p['source']['sha256']}


def run(document,directory,*,executable=None,timeout=240):
    prepared=plan(document)
    if not executable or not Path(executable).is_absolute() or not Path(executable).is_file() or not os.access(executable,os.X_OK):fail('INTERPRETER_NOT_FOUND','Provide an absolute FreeCAD command executable')
    directory=Path(directory).absolute()
    if directory.exists() or directory.is_symlink():fail('OUTPUT_EXISTS','Choose a fresh machining output directory',str(directory))
    directory.mkdir(parents=True);atomic_json(directory/'authored.json',document);atomic_json(directory/'plan.json',prepared);atomic_json(directory/'result.json',{'status':'incomplete','verified':False});capture_source(prepared['source'],directory)
    snapshot=runtime_archive();(directory/'runtime.zip').write_bytes(snapshot)
    runner=SubprocessRunner(Interpreter('freecad',str(Path(executable).resolve())),directory,timeout=timeout)
    try:
        for stage in ('build','reopen','material'):
            if prepared['version']=='schemaxis.freecad.cam.plan/3':
                module='cam_material3' if stage=='material' else 'cam_native3'
            else:module='cam_material' if stage=='material' else 'cam_native2' if prepared['version']=='schemaxis.freecad.cam.plan/2' else 'cam_native'
            report=runner('import sys\nsys.path.insert(0,'+repr(str(directory/'runtime.zip'))+')\nfrom schemaxis.adaptors.freecad.'+module+' import '+stage+'\nfrom schemaxis.native_boundary import execute_guarded\nexecute_guarded('+stage+','+repr(str(directory))+')\n')
            atomic_json(directory/(stage+'-submission.json'),report.to_dict())
            expected=directory/({'build':'built','reopen':'reopened','material':'material'}[stage]+'.json')
            if (directory/'native-fault.json').exists():raise SchemaxisError(Fault(**json.loads((directory/'native-fault.json').read_text())))
            if not expected.is_file():fail('NATIVE_EXECUTION_FAILED','Native machining stage did not produce its required record',stage)
        from .cam_publication import publish
        publish(directory,json.loads((directory/'built.json').read_text())['runtime'],prepared)
        from .cam_checks import verify as check
        result=check(directory,False,fresh=False);result.update(status='succeeded',runtimeSha256=digest(snapshot));atomic_json(directory/'result.json',result);return result
    except Exception as error:
        atomic_json(directory/'result.json',{'status':'failed','verified':False,'fault':error.fault.to_dict() if isinstance(error,SchemaxisError) else {'message':str(error)}});raise


def verify(directory,require_result=True):
    from .cam_checks import verify as check
    try:return check(Path(directory).absolute(),require_result)
    except SchemaxisError:raise
    except Exception as error:fail('VERIFICATION_FAILED','Missing or malformed machining evidence: '+str(error),str(directory))

from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
