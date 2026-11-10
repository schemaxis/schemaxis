"""Intent-level layered thermal/electrical conduction through isolated GetDP."""
import json
import math
import os
from pathlib import Path
import re
import shutil
import time
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.core.declarations import validate_arguments
from schemaxis.errors import fail,keys
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.native_command import execute
from schemaxis.tabular import write_csv,read_csv,close
from . import physics

VERSION='schemaxis.getdp/1'
NUM={'type':'number','minimum':-1e8,'maximum':1e8}
BC={'type':'object','required':True,'properties':{'kind':{'type':'enum','values':['value','flux','convection'],'required':True},
    'value':NUM,'coefficient':{'type':'number','minimum':1e-6,'maximum':1e8},'ambient':NUM}}
OPTIONS={'layers':{'type':'array','required':True,'minItems':1,'maxItems':16,'items':{'type':'object','properties':{
    'name':{'type':'string','minLength':1,'maxLength':48,'required':True},
    'thickness_m':{'type':'number','minimum':1e-5,'maximum':1e3,'required':True},
    'conductivity':{'type':'number','minimum':1e-5,'maximum':1e8,'required':True},
    'source':{**NUM,'default':0},'cells':{'type':'integer','minimum':2,'maximum':128,'default':16}}}},
    'left':BC,'right':BC,'area_m2':{'type':'number','minimum':1e-8,'maximum':1e6,'default':1},
    'limits':{'type':'object','default':{},'properties':{'minimumField':NUM,'maximumField':NUM,'maxAbsFlux':{'type':'number','minimum':0,'maximum':1e12}}}}
DECLARATIONS={op:{'native':'GetDP Form0 scalar diffusion FemEquation','inputs':{},'kinds':['table','text'],
    'options':{k:{'value':v} for k,v in OPTIONS.items()}} for op in ('steadyHeat','steadyCurrent')}
FILES=[('field.csv','table'),('flux.csv','table'),('conduction-summary.json','text'),('model.pro','text'),('model.msh','text')]
EVIDENCE=['reopen.pro','native-field.pos','native-flux.pos','reopened-field.pos','reopened-flux.pos','model.pre','model.res','runtime.json','version.stdout','version.stderr']
LOSSES=['One-dimensional constant-area layers with perfect contact, constant isotropic conductivity and constant volumetric source.',
        'Linear nodal finite elements; flux values are element-midpoint values. Source-corrected end/interface fluxes enforce conservation.',
        'No 2D/3D geometry, imported scripts/meshes, transient, radiation, nonlinear/coupled electrothermal, electromagnetics, circuits or MPI.',
        'Limits concern mesh-node fields and element-midpoint flux only; internal continuum extrema are not certified.']


def plan(document):
    keys(document,('version','operation',*OPTIONS),'$')
    if document.get('version')!=VERSION:fail('UNSUPPORTED_VERSION','expected '+VERSION)
    if not isinstance(document.get('operation'),str) or document['operation'] not in DECLARATIONS:fail('UNKNOWN_FILTER','select steadyHeat or steadyCurrent')
    p={'version':'schemaxis.getdp.plan/1','operation':document['operation'],**validate_arguments(OPTIONS,{k:v for k,v in document.items() if k not in ('version','operation')})}
    names=set()
    for i,l in enumerate(p['layers']):
        if l['name'] in names:fail('INVALID_LAYERS','layer names must be unique',f'$.layers[{i}].name')
        names.add(l['name'])
    if sum(l['cells'] for l in p['layers'])>512:fail('RESOURCE_LIMIT','use at most 512 line elements','$.layers')
    ks=[l['conductivity'] for l in p['layers']];hs=[l['thickness_m']/l['cells'] for l in p['layers']]
    stiffness=[k/h for k,h in zip(ks,hs)]
    if max(stiffness)/min(stiffness)>1e8:fail('ILL_CONDITIONED_FIELD','conductivity/element-length contrast must not exceed 1e8','$.layers')
    for side in ('left','right'):
        bc=p[side];expected={'kind','coefficient','ambient'} if bc['kind']=='convection' else {'kind','value'}
        if set(bc)!=expected:fail('INVALID_BOUNDARY','value/flux needs value only; convection needs coefficient and ambient only','$.'+side)
        if bc['kind']=='convection' and p['operation']!='steadyHeat':fail('UNSUPPORTED_BOUNDARY','convection is thermal only; electrical ends use potential or outward current density','$.'+side)
        if p['operation']=='steadyHeat' and ((bc['kind']=='value' and bc['value']<0) or (bc['kind']=='convection' and bc['ambient']<0)):
            fail('INVALID_TEMPERATURE','thermal values and ambient use nonnegative kelvin','$.'+side)
    limits=p['limits']
    if 'minimumField' in limits and 'maximumField' in limits and limits['minimumField']>limits['maximumField']:fail('INVALID_LIMITS','minimumField must not exceed maximumField','$.limits')
    physics.exact(p);p['losses']=LOSSES;return p


def schema():
    from schemaxis.schema import DRAFT,object_schema,argument_schema
    return {'$schema':DRAFT,**object_schema({'version':{'const':VERSION},'operation':{'enum':list(DECLARATIONS)},**{k:argument_schema(v) for k,v in OPTIONS.items()}},['version','operation','layers','left','right'])}


def query(document):return [plan(document)['operation']],{}
def reusableInputs(document):plan(document);return {}
def resources(document,spec,identity):
    if spec.get('threads',1)!=1:fail('INVALID_EXECUTION','GetDP conduction uses one thread',identity)
    return {'threads':1}


def sources(p,reopen=False):
    x,elements=physics.mesh(p);n=len(x)
    msh=['$MeshFormat','2.2 0 8','$EndMeshFormat','$Nodes',str(n)]+[f'{i+1} {v:.17g} 0 0' for i,v in enumerate(x)]+['$EndNodes','$Elements',str(len(elements)+2),f'1 15 2 1001 1001 1',f'2 15 2 1002 1002 {n}']
    msh += [f'{i+3} 1 2 {m+1} {m+1} {i+1} {i+2}' for i,m in enumerate(elements)]+['$EndElements']
    groups=' '.join(f'L{i+1}=Region[{i+1}];' for i in range(len(p['layers'])))
    constants=' '.join(f'k[L{i+1}]={l["conductivity"]:.17g}; s[L{i+1}]={l["source"]:.17g};' for i,l in enumerate(p['layers']))
    constraints=[];terms=[]
    for side,region in [('left','Left'),('right','Right')]:
        bc=p[side]
        if bc['kind']=='value':constraints.append(f'{{Region {region}; Value {bc["value"]:.17g};}}')
        elif bc['kind']=='flux':terms.append(f'Integral {{ [ {bc["value"]:.17g}, {{u}} ]; In {region}; Jacobian J; Integration I; }}')
        else:
            h=bc['coefficient'];ambient=bc['ambient']
            terms.extend([f'Integral {{ [ {h:.17g} * Dof{{u}}, {{u}} ]; In {region}; Jacobian J; Integration I; }}',f'Integral {{ [ {-h*ambient:.17g}, {{u}} ]; In {region}; Jacobian J; Integration I; }}'])
    prefix='reopened' if reopen else 'native'
    pro=f'''// Generated bounded Schemaxis conduction model. No authored code.
Group {{ {groups} Domain=Region[{{{','.join(str(i+1) for i in range(len(p['layers'])))}}}]; Left=Region[1001]; Right=Region[1002]; AllDomain=Region[{{Domain,Left,Right}}]; }}
Function {{ {constants} }}
Constraint {{ {{ Name Fixed; Type Assign; Case {{ {' '.join(constraints)} }} }} }}
Jacobian {{ {{Name J; Case {{ {{Region All; Jacobian Vol;}} }} }} }}
Integration {{ {{Name I; Case {{ {{Type Gauss; Case {{ {{GeoElement Line; NumberOfPoints 2;}} {{GeoElement Point; NumberOfPoints 1;}} }} }} }} }} }}
FunctionSpace {{ {{Name H; Type Form0; BasisFunction {{ {{Name sn; NameOfCoef un; Function BF_Node; Support AllDomain; Entity NodesOf[All];}} }} Constraint {{ {{NameOfCoef un; EntityType NodesOf; NameOfConstraint Fixed;}} }} }} }}
Formulation {{ {{Name Conduction; Type FemEquation; Quantity {{ {{Name u; Type Local; NameOfSpace H;}} }} Equation {{
Integral {{ [ k[] * Dof{{d u}}, {{d u}} ]; In Domain; Jacobian J; Integration I; }}
Integral {{ [ -s[], {{u}} ]; In Domain; Jacobian J; Integration I; }}
{' '.join(terms)}
}} }} }}
Resolution {{ {{Name Solve; System {{ {{Name A; NameOfFormulation Conduction;}} }} Operation {{ Generate[A]; Solve[A]; SaveSolution[A]; }} }} }}
PostProcessing {{ {{Name Fields; NameOfFormulation Conduction; Quantity {{
{{Name Field; Value {{Local {{ [ {{u}} ]; In Domain; Jacobian J; }} }} }}
{{Name Flux; Value {{Local {{ [ -k[] * {{d u}} ]; In Domain; Jacobian J; }} }} }}
}} }} }}
PostOperation {{ {{Name Export; NameOfPostProcessing Fields; Operation {{
Print[Field, OnElementsOf Domain, File "{prefix}-field.pos", Format Gmsh];
Print[Flux, OnElementsOf Domain, File "{prefix}-flux.pos", Format Gmsh];
}} }} }}
'''
    return '\n'.join(msh)+'\n',pro


def runtime(text):
    found=re.search(r'(?m)^3\.5\.0\s*$',text.strip())
    if not found:fail('UNSUPPORTED_RUNTIME','configure stable GetDP 3.5.0; development releases are unqualified')
    return {'name':'GetDP','version':'3.5.0'}


def publications(p,nodes,flux):
    x,elements=physics.mesh(p);heat=p['operation']=='steadyHeat'
    return ({'columns':['x_m','temperature_K' if heat else 'potential_V'],'rows':[[v,t] for v,t in zip(x,nodes)]},
            {'columns':['xMid_m','heatFlux_W_m2' if heat else 'currentDensity_A_m2','layerIndex'],'rows':[[(x[i]+x[i+1])/2,q,m+1] for i,(q,m) in enumerate(zip(flux,elements))]})


def summary(p,nodes,flux):
    result={'version':'schemaxis.getdp.summary/1','operation':p['operation'],**physics.inspect(p,nodes,flux),'layers':p['layers'],
            'area_m2':p['area_m2'],'units':{'field':'K' if p['operation']=='steadyHeat' else 'V','flux':'W/m2' if p['operation']=='steadyHeat' else 'A/m2','total':'W' if p['operation']=='steadyHeat' else 'A'},'losses':LOSSES}
    margins={k:(result[k]-v if k=='minimumField' else v-result[k]) for k,v in p['limits'].items()}
    result['limits']={'bounds':p['limits'],'margins':margins,'accepted':all(v>=0 for v in margins.values())}
    return result


def manifest(d):return [{'file':str(d/n),'kind':k,'sha256':file_digest(d/n)} for n,k in FILES]


def run(document,directory,*,executable=None,timeout=300):
    p=plan(document);executable=executable or os.environ.get('GETDP_EXECUTABLE') or shutil.which('getdp')
    if not executable or not Path(executable).is_absolute() or not Path(executable).is_file() or not os.access(executable,os.X_OK):fail('INTERPRETER_NOT_FOUND','configure an absolute GetDP 3.5.0 executable or pass --getdp')
    if type(timeout) not in (float,int) or not math.isfinite(timeout) or not 0<timeout<=3600:fail('INVALID_ARGUMENT','timeout must be in (0,3600]')
    d=Path(directory).absolute()
    if d.exists() or d.is_symlink():fail('OUTPUT_EXISTS','choose a fresh output directory',str(d))
    d.mkdir(parents=True);atomic_json(d/'authored.json',document);atomic_json(d/'plan.json',p);atomic_json(d/'result.json',{'status':'incomplete','verified':False})
    try:
        msh,pro=sources(p);(d/'model.msh').write_text(msh);(d/'model.pro').write_text(pro)
        deadline=time.monotonic()+timeout;env={'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'}
        execute([executable,'-version'],d,'version',deadline-time.monotonic(),env)
        observed=runtime((d/'version.stdout').read_text()+(d/'version.stderr').read_text());observed['executable']=str(executable);atomic_json(d/'runtime.json',observed)
        execute([executable,'model.pro','-msh','model.msh','-solve','Solve','-pos','Export','-v','3'],d,'solve',deadline-time.monotonic(),env)
        # Fresh process reloads the retained native pre/res files and postprocesses again.
        (d/'reopen.pro').write_text(sources(p,True)[1])
        execute([executable,'reopen.pro','-name','model','-msh','model.msh','-pos','Export','-v','3'],d,'reopen',deadline-time.monotonic(),env)
        nodes=physics.read_pos(d/'native-field.pos',p);flux=physics.read_pos(d/'native-flux.pos',p,True)
        field,ftable=publications(p,nodes,flux);write_csv(d/'field.csv',field);write_csv(d/'flux.csv',ftable);atomic_json(d/'conduction-summary.json',summary(p,nodes,flux))
        atomic_json(d/'verification.json',{'artifacts':manifest(d),'evidence':{n:file_digest(d/n) for n in EVIDENCE}})
        result=verify(d,False)
        if cancellation_requested():fail('RUNNER_CANCELLED','conduction publication cancelled')
        if time.monotonic()>=deadline:fail('RUNNER_TIMED_OUT','conduction verification exhausted total timeout')
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
            f=d/n;physics.check(f.is_file() and not f.is_symlink() and f.stat().st_size<=8*1024*1024,'missing/excessive regular evidence: '+n)
        p=plan(read('authored.json'));physics.check(p==read('plan.json'),'effective plan differs from authored conduction')
        if require_result:physics.check(read('result.json').get('status')=='succeeded' and read('result.json').get('verified') is True,'execution incomplete')
        physics.check(read('verification.json')=={'artifacts':manifest(d),'evidence':{n:file_digest(d/n) for n in EVIDENCE}},'publication/native evidence digest differs')
        msh,pro=sources(p);physics.check((d/'model.msh').read_text()==msh and (d/'model.pro').read_text()==pro and (d/'reopen.pro').read_text()==sources(p,True)[1],'generated mesh/formulation differs')
        identity=runtime((d/'version.stdout').read_text()+(d/'version.stderr').read_text());observed=read('runtime.json')
        physics.check(all(observed[k]==v for k,v in identity.items()) and Path(observed['executable']).is_absolute(),'native runtime identity differs')
        nodes=physics.read_pos(d/'native-field.pos',p);flux=physics.read_pos(d/'native-flux.pos',p,True)
        physics.check(close(nodes,physics.read_pos(d/'reopened-field.pos',p),rel=1e-10,absolute=1e-9) and close(flux,physics.read_pos(d/'reopened-flux.pos',p,True),rel=1e-10,absolute=1e-9),'fresh native solution readback differs')
        physics.check(close(nodes,physics.read_solution(d,p),rel=1e-10,absolute=1e-9),'independently parsed native pre/res solution differs')
        field,ftable=publications(p,nodes,flux)
        physics.check(close(read_csv(d/'field.csv'),field,rel=1e-12,absolute=1e-12) and close(read_csv(d/'flux.csv'),ftable,rel=1e-12,absolute=1e-12),'published tables differ from native fields')
        details=summary(p,nodes,flux);physics.check(read('conduction-summary.json')==details,'summary differs from independent conduction balance')
        if not details['limits']['accepted']:fail('PERFORMANCE_NOT_MET','native sampled field/flux exceeds declared limits; inspect retained margins and revise input or limits','$.limits',assessment=details['limits'])
        return {'verified':True,'artifacts':len(FILES),'runtime':observed,'operation':p['operation'],'nodes':len(nodes),'elements':len(flux)}
    except (OSError,ValueError,KeyError,TypeError,IndexError,OverflowError) as error:fail('VERIFICATION_FAILED','missing or invalid conduction evidence: '+str(error))

from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
