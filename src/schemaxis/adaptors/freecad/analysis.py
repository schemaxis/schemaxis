"""Typed CAD-to-static-elasticity workflow, host-safe and dependency-free."""
import copy
import json
import math
import os
import time
from pathlib import Path
from schemaxis.core.declarations import validate_arguments
from schemaxis.errors import fail,keys
from schemaxis.artifacts import atomic_json,file_digest,runtime_archive
from schemaxis.core.runners import Interpreter
from .process import SubprocessRunner
from schemaxis.core.faults import SchemaxisError,Fault
from . import faces

VERSION='schemaxis.freecad.analysis/1'
POSITIVE={'type':'number','minimum':0,'exclusiveMinimum':True,'maximum':1e12}
NUMBER={'type':'number','minimum':-1e9,'maximum':1e9}
VECTOR={'type':'array','items':NUMBER,'minItems':3,'maxItems':3}
DISPLACEMENT={'type':'array','items':{'type':'union','options':[NUMBER,{'type':'enum','values':[None]}]},'minItems':3,'maxItems':3}
SUPPORT={'type':'object','properties':{'id':{'type':'string','required':True},'face':{**faces.ARGUMENT,'required':True},'displacementMM':{**DISPLACEMENT,'default':[0,0,0]}}}
LOAD={'type':'union','options':[
    {'type':'object','properties':{'id':{'type':'string','required':True},'kind':{'type':'enum','values':['force'],'required':True},'face':{**faces.ARGUMENT,'required':True},'forceN':{**VECTOR,'required':True}}},
    {'type':'object','properties':{'id':{'type':'string','required':True},'kind':{'type':'enum','values':['pressure'],'required':True},'face':{**faces.ARGUMENT,'required':True},'pressureMPa':{**NUMBER,'required':True}}}]}
LIMIT={'type':'object','properties':{'id':{'type':'string','required':True},'quantity':{'type':'enum','values':['maxDisplacementMM','maxVonMisesMPa'],'required':True},'maximum':{**POSITIVE,'required':True}}}
ARGUMENTS={
 'material':{'type':'object','required':True,'properties':{'name':{'type':'string','minLength':1,'maxLength':120,'default':'Isotropic solid'},
    'youngModulusMPa':{**POSITIVE,'required':True},'poissonRatio':{'type':'number','minimum':-1,'exclusiveMinimum':True,'maximum':.5,'exclusiveMaximum':True,'required':True},
    'densityKgPerM3':{**POSITIVE,'required':True}}},
 'mesh':{'type':'object','required':True,'properties':{'sizeMM':{'type':'number','minimum':.01,'maximum':100000,'required':True},
    'order':{'type':'enum','values':[1,2],'default':2},'maxNodes':{'type':'integer','minimum':20,'maximum':100000,'default':50000},
    'maxElements':{'type':'integer','minimum':10,'maximum':500000,'default':200000},'volumeTolerance':{'type':'number','minimum':1e-6,'maximum':.05,'default':.01}}},
 'supports':{'type':'array','items':SUPPORT,'minItems':1,'maxItems':16,'required':True},
 'loads':{'type':'array','items':LOAD,'minItems':1,'maxItems':16,'required':True},
 'limits':{'type':'array','items':LIMIT,'maxItems':32,'default':[]}}
FILES=[('analysis.FCStd','cadScene'),('Mesh.inp','text'),('Mesh.dat','text'),('Mesh.frd','text'),('analysis.json','text')]


def plan(document,*,captured=None,unread=False):
    from schemaxis.documents import resolve_document
    from schemaxis.pipeline import name
    from .solid_source import source_record
    document,_=resolve_document(copy.deepcopy(document))
    keys(document,('version','source',*ARGUMENTS,'definitions','dimensions','settings'),'$')
    if document.get('version')!=VERSION:fail('UNSUPPORTED_VERSION','Expected '+VERSION)
    source=source_record(document.get('source'),captured=captured,unread=unread)
    data=validate_arguments(ARGUMENTS,{k:document[k] for k in ARGUMENTS if k in document})
    ids=set()
    for group in ('supports','loads','limits'):
        for record in data[group]:
            identity=name(record['id'],'$.'+group+'.id')
            if identity in ids:fail('INVALID_ANALYSIS','Analysis record names must be unique across supports, loads and limits',identity)
            ids.add(identity)
    for support in data['supports']:
        if all(v is None for v in support['displacementMM']):fail('INVALID_ANALYSIS','Support must constrain at least one displacement component',support['id'])
        if support['face'].get('offset',0)!=0:fail('INVALID_ANALYSIS','Support/load face selection has no geometric offset',support['id'])
    for load in data['loads']:
        if load['face'].get('offset',0)!=0:fail('INVALID_ANALYSIS','Support/load face selection has no geometric offset',load['id'])
        if load['kind']=='force' and math.hypot(*load['forceN'])==0 or load['kind']=='pressure' and load['pressureMPa']==0:
            fail('INVALID_ANALYSIS','Load must have a nonzero physical magnitude',load['id'])
    return {'version':'schemaxis.freecad.analysis.plan/1','units':{'length':'mm','force':'N','stress':'MPa','density':'kg/m^3'},
            'analysis':'linearStaticIsotropicSolid','source':source,**data,'expectedPublications':len(FILES)}


def schema():
    from schemaxis.schema import object_schema,arguments_schema,DRAFT,json_value_schema
    # The shared frozen-solid source vocabulary is the same in drawings and FEM.
    positive={'type':'number','exclusiveMinimum':0,'maximum':1e18}
    vec={'type':'array','items':{'type':'number'},'minItems':3,'maxItems':3}
    source=object_schema({'file':{'type':'string','minLength':1},'object':{'type':'string','minLength':1},'units':{'enum':['mm','cm','m','inch']},
        'expect':object_schema({'volume':positive,'bounds':{'type':'array','items':{'type':'number'},'minItems':6,'maxItems':6},'centreOfMass':vec},['volume','bounds','centreOfMass'])},['file','units','expect'])
    options=arguments_schema(ARGUMENTS)
    return {'$schema':DRAFT,'$defs':{'json':json_value_schema()},**object_schema({'version':{'const':VERSION},'source':source,
        **options['properties'],**{k:{'$ref':'#/$defs/json'} for k in ('definitions','dimensions','settings')}},['version','source',*options['required']])}


def resources(document,spec=None,identity=None):
    from schemaxis.parallel import provisional
    plan(provisional(document),unread=True);return {}

def reusableInputs(document):
    record=plan(document)['source'];return {record['file']:record['sha256']}


def retainedInputs(directory,document):
    from .saved_checks import read_json
    p=Path(directory);stored=read_json(p,'plan.json');prepared=_native_plan(document,captured=p/stored['source']['capture'])
    if prepared!=stored:fail('VERIFICATION_FAILED','Retained CAD input does not belong to this analysis')
    return {prepared['source']['file']:prepared['source']['sha256']}


def script(directory,stage):
    return 'import sys\nsys.path.insert(0,'+repr(str(directory/'runtime.zip'))+')\nfrom schemaxis.adaptors.freecad.analysis_native import main\nmain('+repr(str(directory))+','+repr(stage)+')\n'


def run(document,directory,*,executable=None,timeout=300):
    from schemaxis.dispatch import execution_deadline
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0:fail('INVALID_TIMEOUT','Provide a finite positive analysis deadline')
    with execution_deadline(timeout):return _run(document,directory,executable,timeout,time.monotonic()+timeout)


def _run(document,directory,executable,timeout,deadline):
    from .solid_source import capture_source
    prepared=plan(document);directory=Path(directory).absolute();executable=executable or os.environ.get('FREECAD_CMD')
    if not executable or not Path(executable).is_absolute() or not Path(executable).is_file():fail('INTERPRETER_NOT_FOUND','Provide an absolute FreeCAD executable')
    if directory.exists() or directory.is_symlink():fail('OUTPUT_EXISTS','Choose a fresh analysis run directory',str(directory))
    directory.mkdir(parents=True);atomic_json(directory/'authored.json',document);atomic_json(directory/'plan.json',prepared);atomic_json(directory/'result.json',{'status':'incomplete','verified':False})
    try:
        capture_source(prepared['source'],directory);(directory/'runtime.zip').write_bytes(runtime_archive())
        for stage in ('build','reopen'):
            remaining=deadline-time.monotonic()
            if remaining<=0:fail('TIMEOUT','Analysis total deadline expired')
            worker=SubprocessRunner(Interpreter('freecad',str(Path(executable).resolve())),directory,timeout=remaining)
            atomic_json(directory/(stage+'-submission.json'),worker(script(directory,stage)).to_dict())
            if (directory/'native-fault.json').exists():raise SchemaxisError(Fault(**json.loads((directory/'native-fault.json').read_text())))
            if not (directory/(stage+'.json')).is_file():fail('NATIVE_EXECUTION_FAILED','FreeCAD analysis stage did not produce its record',stage)
        result=_verify(directory,False);result.update(status='succeeded',runtimeSha256=file_digest(directory/'runtime.zip'));atomic_json(directory/'result.json',result);return result
    except Exception as error:
        if (directory/'native-fault.json').exists():error=SchemaxisError(Fault(**json.loads((directory/'native-fault.json').read_text())))
        atomic_json(directory/'result.json',{'status':'failed','verified':False,'fault':error.fault.to_dict() if isinstance(error,SchemaxisError) else {'message':str(error)}});raise error


def _verify(directory,require_result=True):
    from .saved_checks import read_json
    from .analysis_results import verify as verify_results
    from .analysis_saved import verify as verify_saved
    from .history import equivalent
    directory=Path(directory).absolute();authored=read_json(directory,'authored.json');stored=read_json(directory,'plan.json')
    prepared=plan(authored,captured=directory/stored['source']['capture'])
    if prepared!=stored:fail('VERIFICATION_FAILED','Analysis plan differs from retained authored source')
    if require_result and read_json(directory,'result.json').get('verified') is not True:fail('INCOMPLETE_EXECUTION','Analysis has no successful result')
    first,second=read_json(directory,'build.json'),read_json(directory,'reopen.json')
    if read_json(directory,'verification.json')!=second:fail('VERIFICATION_FAILED','Analysis publication receipt differs from fresh reopen evidence')
    if first.get('definition')!=prepared or second.get('definition')!=prepared or first.get('pid')==second.get('pid'):fail('VERIFICATION_FAILED','Independent native analysis stages are not bound to this definition')
    for observed in (first,second):verify_observation(prepared,observed['observed'])
    if not equivalent(first['observed'],second['observed']):fail('VERIFICATION_FAILED','Analysis settings, mesh or results changed after fresh reopening')
    verify_saved(prepared,directory/'analysis.FCStd',second['observed'],first.get('savedPayloads'))
    result=verify_results(prepared,directory,second['observed']);publication=read_json(directory,'analysis.json')
    if not equivalent(publication,result):fail('VERIFICATION_FAILED','Published analysis summary differs from independent verification')
    artifacts=second.get('artifacts')
    if not isinstance(artifacts,list) or len(artifacts)!=len(FILES):fail('VERIFICATION_FAILED','Analysis publication membership differs')
    for record,(filename,kind) in zip(artifacts,FILES):
        if record.get('file')!=str(directory/filename) or record.get('kind')!=kind or file_digest(directory/filename)!=record.get('sha256'):fail('VERIFICATION_FAILED','Analysis artifact path/kind/digest differs',filename)
    from schemaxis.dispatch import remaining_timeout
    remaining_timeout()
    return {'verified':True,'artifacts':artifacts,'runtime':second['runtime'],'values':{
        'maxDisplacement':{'value':result['maxDisplacementMM'],'units':'mm'},'maxVonMises':{'value':result['maxVonMisesMPa'],'units':'MPa'},
        'strainEnergy':{'value':result['strainEnergyNMM'],'units':'N*mm'},'limitsSatisfied':{'value':result['limitsSatisfied'],'units':'1'}},'analysis':result}


def verify(directory,require_result=True):
    try:return _verify(directory,require_result)
    except SchemaxisError:raise
    except (OSError,ValueError,TypeError,KeyError,IndexError,AttributeError,OverflowError) as error:fail('VERIFICATION_FAILED','Analysis evidence is malformed',str(directory),detail=str(error))


def verify_observation(prepared,observed):
    from .adaptor import close
    from .faces import resolve
    expected={'objects','analysisGroup','material','mesh','meshNodes','meshCells','supports','loads','solver','faces','shape','result'}
    if not isinstance(observed,dict) or set(observed)!=expected:fail('VERIFICATION_FAILED','Analysis observation membership differs')
    shape=observed['shape'];source=prepared['source']
    if shape.get('valid') is not True or shape.get('solids')!=1 or any(not close(shape.get(k),source[v]) for k,v in [('volume','volume'),('bounds','bounds'),('centreOfMass','centreOfMass')]):fail('VERIFICATION_FAILED','Captured CAD geometry differs from independent authored facts')
    material=prepared['material'];wanted={'Name':material['name'],'YoungsModulus':str(material['youngModulusMPa'])+' MPa','PoissonRatio':str(material['poissonRatio']),'Density':str(material['densityKgPerM3'])+' kg/m^3'}
    if observed['material']!=wanted:fail('VERIFICATION_FAILED','Native isotropic material values/units differ')
    mesh=observed['mesh'];wanted={'shape':'Solid','sizeMM':prepared['mesh']['sizeMM'],'order':'2nd' if prepared['mesh']['order']==2 else '1st','dimension':'3D','straightMidsides':True,'nodes':mesh.get('nodes'),'elements':mesh.get('elements')}
    if mesh!=wanted or type(mesh['nodes']) is not int or type(mesh['elements']) is not int or not 1<=mesh['nodes']<=prepared['mesh']['maxNodes'] or not 1<=mesh['elements']<=prepared['mesh']['maxElements']:fail('VERIFICATION_FAILED','Native mesh settings or resource count differs')
    if observed['solver']!={'analysis':'static','geometry':'linear','material':'linear','space':'3D','split':False}:fail('VERIFICATION_FAILED','Native solver physics differs')
    expected_supports={};expected_loads={}
    for index,support in enumerate(prepared['supports']):
        face=resolve(support['face'],observed['faces'],support['id']);expected_supports['Support'+str(index)]={'id':support['id'],'references':[['Solid',['Face'+str(face['index'])]]],'displacementMM':support['displacementMM'],'suppressed':False}
    for index,load in enumerate(prepared['loads']):
        face=resolve(load['face'],observed['faces'],load['id']);expected_loads['Load'+str(index)]={'id':load['id'],'references':[['Solid',['Face'+str(face['index'])]]],'kind':load['kind'],'forceN':load['forceN']} if load['kind']=='force' else {'id':load['id'],'references':[['Solid',['Face'+str(face['index'])]]],'kind':'pressure','pressureMPa':load['pressureMPa']}
    from .history import equivalent
    if not equivalent(observed['supports'],expected_supports) or not equivalent(observed['loads'],expected_loads):fail('VERIFICATION_FAILED','Native supports/loads differ from geometric intent')
    wanted_types={'Solid':'Part::Feature','Analysis':'Fem::FemAnalysis','Material':'App::MaterialObjectPython','Mesh':'Fem::FemMeshShapeBaseObjectPython','Solver':'Fem::FemSolverObjectPython',
        'CCX_Results':'Fem::FemResultObjectPython','CCX_Results_Mesh':'Fem::FemMeshObjectPython','Pipeline_CCX_Results':'Fem::FemPostPipeline','ccx_dat_file':'App::TextDocument',
        **{'Support'+str(i):'Fem::ConstraintDisplacement' for i in range(len(prepared['supports']))},**{'Load'+str(i):'Fem::ConstraintForce' if x['kind']=='force' else 'Fem::ConstraintPressure' for i,x in enumerate(prepared['loads'])}}
    if observed['objects']!=wanted_types:fail('VERIFICATION_FAILED','Native analysis object membership/type differs')
    group={'Material','Mesh','Solver','CCX_Results','Pipeline_CCX_Results','ccx_dat_file',*expected_supports,*expected_loads}
    if set(observed['analysisGroup'])!=group or len(observed['analysisGroup'])!=len(group):fail('VERIFICATION_FAILED','Native analysis group membership differs')


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
