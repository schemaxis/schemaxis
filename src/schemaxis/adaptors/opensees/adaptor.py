"""Editable planar elastic truss intent with independent structural verification."""
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
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail,keys
from schemaxis.native_command import execute
from schemaxis.tabular import write_csv,parse_csv
from . import mechanics

VERSION='schemaxis.opensees/1'
ID={'type':'string','minLength':1,'maxLength':32,'required':True}
NUMBER={'type':'number','minimum':-1e4,'maximum':1e4,'required':True}
PAIR={'type':'array','minItems':2,'maxItems':2,'items':NUMBER,'required':True}
OPTIONS={
 'nodes':{'type':'array','minItems':2,'maxItems':40,'required':True,'items':{'type':'object','properties':{'id':ID,'x_m':NUMBER,'y_m':NUMBER,'fixed':{'type':'array','minItems':2,'maxItems':2,'items':{'type':'boolean'},'default':[False,False]}}}},
 'members':{'type':'array','minItems':1,'maxItems':80,'required':True,'items':{'type':'object','properties':{'id':ID,'a':ID,'b':ID,'youngsModulus_Pa':{'type':'number','minimum':1e6,'maximum':1e12,'required':True},'area_m2':{'type':'number','minimum':1e-8,'maximum':1,'required':True}}}},
 'loads':{'type':'array','minItems':1,'maxItems':40,'required':True,'items':{'type':'object','properties':{'node':ID,'force_N':PAIR}}},
 'requirements':{'type':'array','maxItems':32,'default':[],'items':{'type':'object','properties':{'name':ID,'quantity':{'type':'enum','values':['displacement_m','force_N','stress_Pa'],'required':True},'target':ID,'maximum':{'type':'number','minimum':0,'maximum':1e12,'required':True}}}}
}
DECLARATIONS={'trussStatic':{'native':'openseespy.opensees: Elastic + Truss + Static','inputs':{},'kinds':['table','text'],'options':{k:{'value':v} for k,v in OPTIONS.items()}}}
FILES=[('model.json','text'),('displacements.csv','table'),('members.csv','table'),('truss-assessment.json','text')]
EVIDENCE=['authored.json','plan.json','worker.py','build.json','reopen.json','build.stdout','build.stderr','reopen.stdout','reopen.stderr','build-submission.json','reopen-submission.json']
LOSSES=['Planar pin-jointed small-strain elastic static trusses only; no bending, rotational degrees of freedom, buckling, yielding, cable slackening, prestress, dynamics, thermal effects, 3D or earthquake safety claim.',
        'Point loads and zero-translation Cartesian supports only; no settlements, imposed strains, distributed loads or multipoint constraints.',
        'Member stresses are uniform axial engineering stresses; compressive members retain elastic stiffness without stability or failure assessment.']
NODE_COLUMNS=['nodeIndex','ux_m','uy_m','rx_N','ry_N']
MEMBER_COLUMNS=['memberIndex','length_m','force_N','stress_Pa','strain']


def plan(document):
    keys(document,('version','operation',*OPTIONS),'$')
    if document.get('version')!=VERSION: fail('UNSUPPORTED_VERSION','expected '+VERSION)
    if document.get('operation')!='trussStatic': fail('UNKNOWN_FILTER','select trussStatic')
    p=validate_arguments(OPTIONS,{k:v for k,v in document.items() if k in OPTIONS},location='$')
    for group in ('nodes','members','requirements'):
        seen=set()
        for i,row in enumerate(p[group]):
            key='name' if group=='requirements' else 'id'; value=row[key]
            if not re.fullmatch('[a-z][a-z0-9_]{0,31}',value) or value in seen: fail('INVALID_TRUSS','use unique lowercase identifiers',f'$.{group}[{i}].{key}')
            seen.add(value)
    names={n['id'] for n in p['nodes']}; connected=set();edges=set()
    for i,m in enumerate(p['members']):
        if m['a'] not in names or m['b'] not in names or m['a']==m['b']: fail('INVALID_TRUSS','member endpoints must name two distinct declared nodes',f'$.members[{i}]')
        edge=tuple(sorted((m['a'],m['b'])))
        if edge in edges: fail('INVALID_TRUSS','combine parallel coincident members into one equivalent axial stiffness',f'$.members[{i}]')
        edges.add(edge);connected.update(edge)
    if connected!=names: fail('INVALID_TRUSS','every node must belong to a member','$.nodes')
    loaded=set()
    for i,load in enumerate(p['loads']):
        if load['node'] not in names or load['node'] in loaded: fail('INVALID_TRUSS','loads must reference unique declared nodes',f'$.loads[{i}].node')
        loaded.add(load['node'])
    if not any(any(l['force_N']) for l in p['loads']): fail('INVALID_TRUSS','provide at least one nonzero load','$.loads')
    for i,entry in enumerate(p['requirements']):
        targets=names if entry['quantity']=='displacement_m' else {m['id'] for m in p['members']}
        if entry['target'] not in targets: fail('INVALID_REQUIREMENT','target must name a node for displacement or a member for force/stress',f'$.requirements[{i}].target')
    mechanics.solve(p)
    return {'version':'schemaxis.opensees.plan/1','operation':'trussStatic',**p,'losses':LOSSES}


def schema():
    from schemaxis.schema import DRAFT,object_schema,argument_schema
    return {'$schema':DRAFT,**object_schema({'version':{'const':VERSION},'operation':{'const':'trussStatic'},**{k:argument_schema(v) for k,v in OPTIONS.items()}},['version','operation','nodes','members','loads'])}


def query(document): plan(document);return ['trussStatic'],{}
def reusableInputs(document): plan(document);return {}
def resources(document,spec,identity):
    if spec.get('threads',1)!=1: fail('INVALID_EXECUTION','serial trusses allocate one thread',identity)
    return {'threads':1}


def bounded(path):
    path=Path(path)
    if path.is_symlink(): fail('VERIFICATION_FAILED','evidence must be a bounded regular file',str(path))
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NONBLOCK',0))
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size>4*1024*1024: fail('VERIFICATION_FAILED','evidence must be a bounded regular file',str(path))
        data=stream.read(4*1024*1024+1)
        if len(data)>4*1024*1024: fail('VERIFICATION_FAILED','evidence exceeds byte budget')
        return data


def read(path): return json.loads(bounded(path))
def numeric_rows(value,width,*,integer=False):
    return isinstance(value,list) and all(isinstance(row,list) and len(row)==width and
        all(type(v) is int if integer else type(v) in (int,float) and math.isfinite(v) for v in row) for row in value)
def model(p): return {k:p[k] for k in OPTIONS}
def tables(results):
    return ([[i,*n['displacement_m'],*n['reaction_N']] for i,n in enumerate(results['nodes'],1)],[[i,m['length_m'],m['force_N'],m['stress_Pa'],m['strain']] for i,m in enumerate(results['members'],1)])
def assessment(p,results):
    checks=mechanics.check(p,results); requirements=[]
    for entry in p['requirements']:
        group='nodes' if entry['quantity']=='displacement_m' else 'members'
        row=next(v for v in results[group] if v['id']==entry['target']); value=row[entry['quantity']]
        measured=math.hypot(*value) if isinstance(value,list) else abs(value)
        requirements.append({**entry,'observed':measured,'margin':entry['maximum']-measured,'accepted':measured<=entry['maximum'], 'nextAction':'Accept this measured limit.' if measured<=entry['maximum'] else 'Revise load, bracing, E or area, or the explicit requirement; rerun a fresh attempt.'})
    return {'version':'schemaxis.opensees.assessment/1','accepted':all(e['accepted'] for e in requirements),'results':results,'checks':checks,'requirements':requirements,'losses':LOSSES}


def verify(directory,require_result=True):
    directory=Path(directory).absolute()
    try:
        p=plan(read(directory/'authored.json'))
        if read(directory/'plan.json')!=p or read(directory/'model.json')!=model(p): fail('VERIFICATION_FAILED','authored/effective/retained model binding differs')
        for name in EVIDENCE+[n for n,_ in FILES]: bounded(directory/name)
        if bounded(directory/'worker.py')!=Path(__file__).with_name('native.py').read_bytes(): fail('VERIFICATION_FAILED','trusted native worker differs')
        if require_result and (read(directory/'result.json').get('status')!='succeeded' or read(directory/'result.json').get('verified') is not True): fail('VERIFICATION_FAILED','execution is incomplete')
        built,reopened=(read(directory/(s+'.json')) for s in ('build','reopen'))
        if any(type(r['pid']) is not int or r['pid']<=0 for r in (built,reopened)) or built['pid']==reopened['pid']: fail('VERIFICATION_FAILED','native readback must use distinct positive process identities')
        for stage,record in (('build',built),('reopen',reopened)):
            if record['stage']!=stage or record['model']!=model(p) or record['runtime']['version']!='3.8.0' or record['runtime']['name']!='OpenSeesPy' or record['runtime']['packageVersion']!='3.8.0.0': fail('VERIFICATION_FAILED','native runtime/model identity differs')
            index={n['id']:i+1 for i,n in enumerate(p['nodes'])}
            if not numeric_rows(record['coordinates'],2) or not numeric_rows(record['connections'],2,integer=True) or record['coordinates']!=[[n['x_m'],n['y_m']] for n in p['nodes']] or record['connections']!=[[index[m['a']],index[m['b']]] for m in p['members']]: fail('VERIFICATION_FAILED','native geometry readback differs')
            if not isinstance(record['fixedDOFs'],list) or any(not isinstance(row,list) or any(type(v) is not int for v in row) for row in record['fixedDOFs']) or record['fixedDOFs']!=[[j+1 for j,v in enumerate(n['fixed']) if v] for n in p['nodes']]: fail('VERIFICATION_FAILED','native support readback differs')
            materials=record['materials']
            if not isinstance(materials,list) or len(materials)!=len(p['members']): fail('VERIFICATION_FAILED','native material shape differs')
            for observed,m in zip(materials,p['members']):
                if set(observed)!={'youngsModulus_Pa','area_m2'} or any(type(observed[k]) not in (int,float) or not math.isfinite(observed[k]) or not math.isclose(observed[k],m[k],rel_tol=1e-12) for k in observed): fail('VERIFICATION_FAILED','native material/area differs')
            mechanics.check(p,record['results'])
            submission=read(directory/(stage+'-submission.json'))
            command=[record['runtime']['executable'],str(directory/'worker.py'),str(directory),stage]
            source='import os\n'+f'os.chdir({str(directory)!r})\n'+f'command = {command!r}\n'+'os.execvpe(command[0], command, os.environ)\n'
            script=directory/'.dispatch'/stage/('replay-'+hashlib.sha256(source.encode()).hexdigest()[:16]+'.py')
            if submission['interpreter']!={'kind':'native','executable':sys.executable} or submission['scriptPath']!=str(script) or submission['command']!=[sys.executable,str(script)] or bounded(script)!=source.encode(): fail('VERIFICATION_FAILED','trusted native replay differs')
            if submission['nativeCommand']!=command or type(submission['exitCode']) is not int or submission['exitCode']!=0 or submission['stdout']!=bounded(directory/(stage+'.stdout')).decode() or submission['stderr']!=bounded(directory/(stage+'.stderr')).decode(): fail('VERIFICATION_FAILED','native command or log binding differs')
        if built['results']!=reopened['results'] or built['runtime']!=reopened['runtime']: fail('VERIFICATION_FAILED','reconstructed model readback differs')
        expected=assessment(p,built['results'])
        if read(directory/'truss-assessment.json')!=expected: fail('VERIFICATION_FAILED','measured assessment differs')
        for name,columns,rows in zip(('displacements.csv','members.csv'),(NODE_COLUMNS,MEMBER_COLUMNS),tables(built['results'])):
            table=parse_csv(bounded(directory/name))
            if table['columns']!=columns or table['rows']!=rows: fail('VERIFICATION_FAILED','published table differs')
        receipt={'artifacts':[{'file':str(directory/n),'kind':kind,'sha256':file_digest(directory/n)} for n,kind in FILES],'evidence':{n:file_digest(directory/n) for n in EVIDENCE},'runtime':built['runtime'],'assessment':expected}
        if read(directory/'verification.json')!=receipt: fail('VERIFICATION_FAILED','publication/evidence digest differs')
        if not expected['accepted']: fail('PERFORMANCE_NOT_MET','named measured requirements are unmet; inspect margins, revise explicit intent and rerun fresh')
        return {'verified':True,'artifacts':len(FILES),'runtime':{k:built['runtime'][k] for k in ('name','version','packageVersion')},'nodes':len(p['nodes']),'members':len(p['members'])}
    except SchemaxisError as error:
        if error.fault.code in ('VERIFICATION_FAILED','PERFORMANCE_NOT_MET'): raise
        fail('VERIFICATION_FAILED','invalid retained truss evidence: '+str(error))
    except (OSError,ValueError,KeyError,TypeError,IndexError,AttributeError,OverflowError) as error: fail('VERIFICATION_FAILED','missing or malformed truss evidence: '+str(error))


def run(document,directory,*,executable=None,timeout=300):
    p=plan(document);executable=executable or os.environ.get('OPENSEES_PYTHON')
    if not executable or not Path(executable).is_absolute() or not Path(executable).is_file() or not os.access(executable,os.X_OK): fail('INTERPRETER_NOT_FOUND','configure an absolute Python with OpenSeesPy3.8.0.0 via --opensees or OPENSEES_PYTHON')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=3600: fail('INVALID_ARGUMENT','timeout must be in (0,3600]')
    directory=Path(directory).absolute()
    if directory.exists() or directory.is_symlink(): fail('OUTPUT_EXISTS','choose a fresh output directory',str(directory))
    directory.mkdir(parents=True);atomic_json(directory/'authored.json',document);atomic_json(directory/'plan.json',p);atomic_json(directory/'model.json',model(p));atomic_json(directory/'result.json',{'status':'incomplete','verified':False})
    try:
        shutil.copyfile(Path(__file__).with_name('native.py'),directory/'worker.py'); deadline=time.monotonic()+timeout
        for stage in ('build','reopen'):
            try: execute([str(executable),str(directory/'worker.py'),str(directory),stage],directory,stage,deadline-time.monotonic(),{'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'})
            except SchemaxisError as error:
                if error.fault.code in ('RUNNER_TIMED_OUT','RUNNER_CANCELLED'): raise
                path=directory/'native-fault.json'
                if path.is_file():
                    record=read(path)
                    if record.get('code') in ('NATIVE_UNAVAILABLE','UNSUPPORTED_RUNTIME','NATIVE_EXECUTION_FAILED') and isinstance(record.get('message'),str): fail(record['code'],record['message']+'; inspect native logs and configure the pinned isolated Python, then rerun fresh')
                raise
        built=read(directory/'build.json'); summary=assessment(p,built['results'])
        for name,columns,rows in zip(('displacements.csv','members.csv'),(NODE_COLUMNS,MEMBER_COLUMNS),tables(built['results'])): write_csv(directory/name,{'columns':columns,'rows':rows})
        atomic_json(directory/'truss-assessment.json',summary)
        atomic_json(directory/'verification.json',{'artifacts':[{'file':str(directory/n),'kind':kind,'sha256':file_digest(directory/n)} for n,kind in FILES],'evidence':{n:file_digest(directory/n) for n in EVIDENCE},'runtime':built['runtime'],'assessment':summary})
        result=verify(directory,require_result=False)
        if cancellation_requested(): fail('RUNNER_CANCELLED','truss publication cancelled')
        result.update(status='succeeded');atomic_json(directory/'result.json',result);return result
    except Exception as error:
        if not isinstance(error,SchemaxisError):
            try: fail('NATIVE_EXECUTION_FAILED',str(error))
            except SchemaxisError as wrapped: error=wrapped
        atomic_json(directory/'result.json',{'status':'failed','verified':False,'fault':error.fault.to_dict()});raise error


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
