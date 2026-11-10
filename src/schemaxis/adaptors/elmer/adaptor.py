"""Intent-level solid conduction through an isolated ElmerSolver process."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import time
from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import keys
from schemaxis.native_command import execute
from schemaxis.tabular import read_csv, write_csv, close
from . import physics, formats


RECOVERY={
    'INVALID_BOUNDARY':'Supply kind and value for value/flux, or kind, coefficient and ambient for convection; remove fields from the other family.',
    'INVALID_TEMPERATURE':'Use nonnegative kelvin and reduce cooling or revise the end temperatures; interior continuum extrema are checked.',
    'ILL_CONDITIONED_FIELD':'Reduce conductivity/element-length contrast or choose physically appropriate layer scales.',
    'RESOURCE_LIMIT':'Reduce cell count or rescale the physical problem within the declared bounds.',
    'INVALID_LAYERS':'Give every ordered material layer a distinct readable name.',
    'UNANCHORED_FIELD':'Set at least one end to a fixed temperature or positive convection film.',
    'INVALID_LIMITS':'Set minimumField no greater than maximumField.',
    'EXPORT_PRECISION_LOSS':'Rescale the geometry or reduce mesh refinement so every exported coordinate remains distinct at eight significant digits.',
    'INTERPRETER_NOT_FOUND':'Configure an absolute stable ElmerSolver executable or pass --elmer.',
    'RUNTIME_UNAVAILABLE':'Inspect version stdout/stderr and configure a complete runnable ElmerSolver installation with its shared libraries.',
    'UNSUPPORTED_RUNTIME':'Use the qualified stable ElmerSolver 26.2 family built from release 26.2.1 and retain source provenance.',
    'NATIVE_EXECUTION_FAILED':'Inspect retained solve/reopen stdout/stderr, correct the thermal input or runtime installation, and retry in a fresh output directory.',
    'VERIFICATION_FAILED':'Restore complete original evidence or rerun into a fresh directory; do not edit or refresh result hashes.',
    'PERFORMANCE_NOT_MET':'Inspect thermal-summary.json signed sampled margins, revise the design or authored criterion, and run in a fresh directory.'}


def fail(code,message,location='$',**observed):
    raise SchemaxisError(Fault(code,message,location,'pipeline',observed=observed,
        recovery=RECOVERY.get(code,'Correct the declared input and retry in a fresh output directory.')))


def command(command,d,stage,timeout,environment):
    try:return execute(command,d,stage,timeout,environment)
    except SchemaxisError as error:
        if error.fault.code in ('RUNNER_TIMED_OUT','RUNNER_CANCELLED'):raise
        code='RUNTIME_UNAVAILABLE' if stage=='version' else 'NATIVE_EXECUTION_FAILED'
        fail(code,'Elmer process could not complete '+stage,stage,cause=error.fault.to_dict())


def evidence_files(d,observed):
    names=list(EVIDENCE)
    for stage,args in [('version',['--version']),('solve',['model.sif']),('reopen',['reopen.sif'])]:
        native_command=[observed['executable'],*args]
        source='import os\n'+f'os.chdir({str(d)!r})\n'+f'command = {native_command!r}\n'+'os.execvpe(command[0], command, os.environ)\n'
        script=Path('.dispatch')/stage/('replay-'+hashlib.sha256(source.encode()).hexdigest()[:16]+'.py')
        names.extend(str(script.with_suffix(suffix)) for suffix in ('.py','.stdout.log','.stderr.log'))
    return names


def verify_commands(d,observed):
    for stage,args in [('version',['--version']),('solve',['model.sif']),('reopen',['reopen.sif'])]:
        expected=[observed['executable'],*args]
        source='import os\n'+f'os.chdir({str(d)!r})\n'+f'command = {expected!r}\n'+'os.execvpe(command[0], command, os.environ)\n'
        script=d/'.dispatch'/stage/('replay-'+hashlib.sha256(source.encode()).hexdigest()[:16]+'.py')
        physics.check(script.read_text()==source,'trusted replay source differs: '+stage)
        report=json.loads((d/(stage+'-submission.json')).read_text())
        stdout=(d/(stage+'.stdout')).read_text();stderr=(d/(stage+'.stderr')).read_text()
        physics.check(type(report['exitCode']) is int and report['exitCode']==0 and report['nativeCommand']==expected and report['scriptPath']==str(script),'native submission command/status differs: '+stage)
        interpreter=report['interpreter']
        physics.check(interpreter['kind']=='native' and Path(interpreter['executable']).is_absolute() and report['command']==[interpreter['executable'],str(script)],'owned replay interpreter differs: '+stage)
        physics.check(report['stdout']==stdout and report['stderr']==stderr and script.with_suffix('.stdout.log').read_text()==stdout and script.with_suffix('.stderr.log').read_text()==stderr,'retained native logs differ: '+stage)
        physics.check(type(report['seconds']) in (int,float) and math.isfinite(report['seconds']) and report['seconds']>=0,'invalid native duration')
        if stage!='version':physics.check('*** Elmer Solver: ALL DONE ***' in stdout,'native stage did not finish: '+stage)
        if stage=='solve':physics.check('Solving the energy equation for temperature' in stdout,'native HeatSolver did not execute')
        if stage=='reopen':physics.check('LoadRestartFile: All done' in stdout and 'Solving the energy equation' not in stdout,'reopen did not load saved temperature without recomputing')

VERSION='schemaxis.elmer/1'
NUMBER={'type':'number','minimum':-1e8,'maximum':1e8}
BOUNDARY={'type':'object','required':True,'properties':{
    'kind':{'type':'enum','values':['value','flux','convection'],'required':True},
    'value':NUMBER,'coefficient':{'type':'number','minimum':1e-6,'maximum':1e8},'ambient':NUMBER}}
OPTIONS={
    'layers':{'type':'array','required':True,'minItems':1,'maxItems':16,'items':{'type':'object','properties':{
        'name':{'type':'string','minLength':1,'maxLength':48,'required':True},
        'thickness_m':{'type':'number','minimum':1e-5,'maximum':1e3,'required':True},
        'conductivity_W_mK':{'type':'number','minimum':1e-5,'maximum':1e8,'required':True},
        'heatGeneration_W_m3':{**NUMBER,'default':0},
        'cells':{'type':'integer','minimum':2,'maximum':128,'default':16}}}},
    'left':BOUNDARY,'right':BOUNDARY,'area_m2':{'type':'number','minimum':1e-8,'maximum':1e6,'default':1},
    'limits':{'type':'object','default':{},'properties':{
        'minimumField':NUMBER,'maximumField':NUMBER,'maxAbsFlux':{'type':'number','minimum':0,'maximum':1e12}}}}
DECLARATIONS={'steadyHeat':{'native':'Elmer HeatSolve HeatSolver','inputs':{},'kinds':['table','text'],
    'options':{k:{'value':v} for k,v in OPTIONS.items()}}}
FILES=[('temperature.csv','table'),('heat-flux.csv','table'),('thermal-summary.json','text'),('model.sif','text'),('mesh/thermal.result','text'),('mesh/native_t0001.vtu','text')]
MESH=['mesh.header','mesh.nodes','mesh.elements','mesh.boundary']
EVIDENCE=['reopen.sif','mesh/reopened_t0001.vtu','runtime.json','version.stdout','version.stderr',*[stage+suffix for stage in ('version','solve','reopen') for suffix in ('.stdout','.stderr','-submission.json') if stage+suffix not in ('version.stdout','version.stderr')],*('mesh/'+n for n in MESH)]
LOSSES=['One-dimensional constant-area solid layers; constant isotropic properties, uniform volumetric source and perfect thermal contact.',
    'Linear finite elements; derived flux is the element-midpoint Fourier flux, with source correction at ends/interfaces.',
    'VTU ASCII exports retain eight significant digits; tables and physics checks use the full-precision native ASCII restart.',
    'Bounds apply to mesh-node temperatures and element-midpoint heat flux; no certification of continuum extrema or mesh convergence.',
    'No fluid flow/CFD, transient, radiation, 2D/3D, nonlinear or coupled physics, imported decks/meshes, scripting or MPI.']


def plan(document):
    keys(document,('version','operation',*OPTIONS),'$')
    if document.get('version')!=VERSION:fail('UNSUPPORTED_VERSION','expected '+VERSION)
    if document.get('operation')!='steadyHeat':fail('UNKNOWN_FILTER','select steadyHeat for serial solid conduction')
    p={'version':'schemaxis.elmer.plan/1','operation':'steadyHeat',**validate_arguments(OPTIONS,{k:v for k,v in document.items() if k not in ('version','operation')},location='$')}
    names=set()
    for i,layer in enumerate(p['layers']):
        if layer['name'] in names:fail('INVALID_LAYERS','layer names must be unique',f'$.layers[{i}].name')
        names.add(layer['name'])
    if sum(l['cells'] for l in p['layers'])>512:fail('RESOURCE_LIMIT','use at most 512 line elements','$.layers')
    stiffness=[l['conductivity_W_mK']*l['cells']/l['thickness_m'] for l in p['layers']]
    if max(stiffness)/min(stiffness)>1e8:fail('ILL_CONDITIONED_FIELD','conductivity/element-length contrast must not exceed 1e8','$.layers')
    for side in ('left','right'):
        b=p[side];expected={'kind','coefficient','ambient'} if b['kind']=='convection' else {'kind','value'}
        if set(b)!=expected:fail('INVALID_BOUNDARY','value/flux requires value only; convection requires coefficient and ambient only','$.'+side)
        if (b['kind']=='value' and b['value']<0) or (b['kind']=='convection' and b['ambient']<0):fail('INVALID_TEMPERATURE','temperature and ambient use nonnegative kelvin','$.'+side)
    limits=p['limits']
    if 'minimumField' in limits and 'maximumField' in limits and limits['minimumField']>limits['maximumField']:fail('INVALID_LIMITS','minimumField must not exceed maximumField','$.limits')
    coordinates=physics.mesh(p)[0];exported=[float(f'{x:.7e}') for x in coordinates]
    if any(b<=a for a,b in zip(exported,exported[1:])):fail('EXPORT_PRECISION_LOSS','neighbouring mesh nodes collapse at native VTU ASCII coordinate precision','$.layers')
    physics.exact(p);p['losses']=LOSSES;return p


def schema():
    from schemaxis.schema import DRAFT,object_schema,argument_schema
    return {'$schema':DRAFT,**object_schema({'version':{'const':VERSION},'operation':{'const':'steadyHeat'},**{k:argument_schema(v) for k,v in OPTIONS.items()}},['version','operation','layers','left','right'])}


def query(document):return [plan(document)['operation']],{}
def reusableInputs(document):plan(document);return {}
def resources(document,spec,identity):
    if spec.get('threads',1)!=1:fail('INVALID_EXECUTION','Elmer solid conduction uses one thread',identity)
    return {'threads':1}


def runtime(text):
    found=re.search(r'Version:\s*(26\.2)(?:[-\s]|$)',text)
    if not found or re.search(r'Version:.*(?:devel|master|main)',text,re.IGNORECASE):fail('UNSUPPORTED_RUNTIME','configure ElmerSolver 26.2 from stable 26.2.1 source; development releases are unqualified')
    return {'name':'ElmerSolver','version':found[1],'versionPrecision':'upstream binary reports major.minor; patch source provenance is separate'}


def publications(p,nodes):
    x,elements=physics.mesh(p)
    flux=[-p['layers'][m]['conductivity_W_mK']*(nodes[i+1]-nodes[i])/(x[i+1]-x[i]) for i,m in enumerate(elements)]
    return ({'columns':['x_m','temperature_K'],'rows':[[v,t] for v,t in zip(x,nodes)]},
        {'columns':['xMid_m','heatFlux_W_m2','layerIndex'],'rows':[[(x[i]+x[i+1])/2,q,m+1] for i,(q,m) in enumerate(zip(flux,elements))]},flux)


def summary(p,nodes):
    flux=publications(p,nodes)[2]
    result={'version':'schemaxis.elmer.summary/1','operation':'steadyHeat',**physics.inspect(p,nodes,flux),
        'layers':p['layers'],'area_m2':p['area_m2'],'units':{'field':'K','flux':'W/m2','total':'W'},'losses':LOSSES}
    margins={k:(result[k]-v if k=='minimumField' else v-result[k]) for k,v in p['limits'].items()}
    result['limits']={'bounds':p['limits'],'margins':margins,'accepted':all(v>=0 for v in margins.values())}
    return result


def regular(d,name):
    path=d/name
    return (not d.is_symlink() and path.is_file() and path.resolve().is_relative_to(d.resolve())
        and not any(p.is_symlink() for p in (path,*path.parents) if p==d or d in p.parents)
        and path.stat().st_size<=8*1024*1024)


def manifest(d):return [{'file':str(d/n),'kind':k,'sha256':file_digest(d/n)} for n,k in FILES]


def run(document,directory,*,executable=None,timeout=300):
    p=plan(document);executable=executable or os.environ.get('ELMER_EXECUTABLE') or shutil.which('ElmerSolver')
    if not executable or not Path(executable).is_absolute() or not Path(executable).is_file() or not os.access(executable,os.X_OK):fail('INTERPRETER_NOT_FOUND','configure an absolute stable ElmerSolver executable or pass --elmer')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=3600:fail('INVALID_ARGUMENT','timeout must be in (0,3600]')
    d=Path(directory).absolute()
    if d.exists() or d.is_symlink():fail('OUTPUT_EXISTS','choose a fresh output directory',str(d))
    d.mkdir(parents=True);atomic_json(d/'authored.json',document);atomic_json(d/'plan.json',p);atomic_json(d/'result.json',{'status':'incomplete','verified':False})
    try:
        for name,content in formats.sources(p).items():
            target=d/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(content)
        deadline=time.monotonic()+timeout;env={'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'}
        command([executable,'--version'],d,'version',deadline-time.monotonic(),env)
        observed=runtime((d/'version.stdout').read_text()+(d/'version.stderr').read_text());observed['executable']=str(executable);atomic_json(d/'runtime.json',observed)
        command([executable,'model.sif'],d,'solve',deadline-time.monotonic(),env)
        command([executable,'reopen.sif'],d,'reopen',deadline-time.monotonic(),env)
        nodes=formats.read_result(d/'mesh/thermal.result',p);field,flux,_=publications(p,nodes)
        write_csv(d/'temperature.csv',field);write_csv(d/'heat-flux.csv',flux);atomic_json(d/'thermal-summary.json',summary(p,nodes))
        atomic_json(d/'verification.json',{'artifacts':manifest(d),'evidence':{n:file_digest(d/n) for n in evidence_files(d,observed)}})
        result=verify(d,False)
        if cancellation_requested():fail('RUNNER_CANCELLED','thermal publication cancelled')
        if time.monotonic()>=deadline:fail('RUNNER_TIMED_OUT','thermal verification exhausted total timeout')
        result['status']='succeeded';atomic_json(d/'result.json',result);return result
    except Exception as error:
        if not isinstance(error,SchemaxisError):
            try:fail('NATIVE_EXECUTION_FAILED',str(error))
            except SchemaxisError as wrapped:error=wrapped
        atomic_json(d/'result.json',{'status':'failed','verified':False,'fault':error.fault.to_dict()});raise error


def verify(directory,require_result=True):
    d=Path(directory).absolute()
    try:
        def read(n):return json.loads((d/n).read_text())
        for n in [n for n,_ in FILES]+EVIDENCE+['authored.json','plan.json','verification.json','result.json']:
            physics.check(regular(d,n),'missing/excessive regular evidence: '+n)
        p=plan(read('authored.json'));physics.check(p==read('plan.json'),'effective plan differs from authored thermal model')
        if require_result:physics.check(read('result.json').get('status')=='succeeded' and read('result.json').get('verified') is True,'execution incomplete')
        for n,content in formats.sources(p).items():physics.check((d/n).read_text()==content,'generated native input differs: '+n)
        for n in evidence_files(d,read('runtime.json')):
            physics.check(regular(d,n),'missing/excessive regular command evidence: '+n)
        physics.check(read('verification.json')=={'artifacts':manifest(d),'evidence':{n:file_digest(d/n) for n in evidence_files(d,read('runtime.json'))}},'publication/native evidence digest differs')
        identity=runtime((d/'version.stdout').read_text()+(d/'version.stderr').read_text());observed=read('runtime.json')
        physics.check(all(observed[k]==v for k,v in identity.items()) and Path(observed['executable']).is_absolute(),'native runtime identity differs')
        verify_commands(d,observed)
        nodes=formats.read_result(d/'mesh/thermal.result',p);exported=formats.read_vtu(d/'mesh/native_t0001.vtu',p);reread=formats.read_vtu(d/'mesh/reopened_t0001.vtu',p)
        physics.check(close(exported,reread,rel=1e-13,absolute=1e-12),'fresh native restart readback differs')
        physics.check(close([float(f'{v:.7e}') for v in nodes],exported,rel=1e-13,absolute=1e-12),'ASCII VTU export differs from independently parsed full-precision native restart solution')
        field,flux,_=publications(p,nodes)
        physics.check(close(read_csv(d/'temperature.csv'),field,rel=1e-12,absolute=1e-12) and close(read_csv(d/'heat-flux.csv'),flux,rel=1e-12,absolute=1e-12),'published tables differ from native temperature')
        details=summary(p,nodes);physics.check(read('thermal-summary.json')==details,'summary differs from independent solid conduction balance')
        if not details['limits']['accepted']:fail('PERFORMANCE_NOT_MET','verified sampled temperatures/flux exceed declared bounds; inspect margins and revise inputs or limits','$.limits',assessment=details['limits'])
        return {'verified':True,'artifacts':len(FILES),'runtime':observed,'operation':'steadyHeat','nodes':len(nodes),'elements':len(nodes)-1}
    except SchemaxisError as error:
        if error.fault.code in ('VERIFICATION_FAILED','PERFORMANCE_NOT_MET'):raise
        fail('VERIFICATION_FAILED','retained thermal evidence cannot be reconstructed',cause=error.fault.to_dict())
    except (OSError,ValueError,KeyError,TypeError,IndexError,OverflowError) as error:fail('VERIFICATION_FAILED','missing or invalid thermal evidence: '+str(error))

from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
