# Copyright (C) 2026 David L F Gaden
"""Host-safe numerical contracts, provenance capture and independent verification."""
import copy
import json
import os
import math
from pathlib import Path
import re
import shutil
from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute
from schemaxis.tabular import read_csv, close
from .reference import evaluate

NUMBER={'type':'number','minimum':-1e100,'maximum':1e100}
ARRAY={'type':'array','items':NUMBER,'minItems':2,'maxItems':10000,'required':True}
COUNT={'type':'integer','minimum':2,'maximum':10000,'default':101}
PATH={'type':'string','minLength':1,'maxLength':4096,'required':True}
OPTIONS={
 'samples':{'x':ARRAY,'y':ARRAY},
 'readCSV':{'file':PATH,'xColumn':{'type':'string','default':'x','minLength':1},'yColumn':{'type':'string','default':'y','minLength':1}},
 'sequence':{'start':{**NUMBER,'default':0},'stop':{**NUMBER,'default':1},'count':COUNT},
 'wave':{'start':{**NUMBER,'default':0},'step':{'type':'number','minimum':1e-12,'maximum':1e12,'default':0.01},'count':COUNT,
         'shape':{'type':'enum','values':['sine','cosine'],'default':'sine'},
         'amplitude':{**NUMBER,'default':1},'frequency':{'type':'number','minimum':0,'maximum':1e12,'default':1},
         'phase':{'type':'number','minimum':-100000,'maximum':100000,'default':0},'offset':{**NUMBER,'default':0}},
 'scale':{'factor':{'type':'number','minimum':-1e6,'maximum':1e6,'default':1},'offset':{**NUMBER,'default':0}},
 'resample':{'count':COUNT},
 'movingMean':{'window':{'type':'integer','minimum':1,'maximum':1001,'default':5}},
 'derivative':{},'integral':{'initial':{**NUMBER,'default':0}},'linearFit':{},'fft':{},
}
SOURCES={'samples','readCSV','sequence','wave'}
DECLARATIONS={name:{'native':name,'kinds':['table'], 'options':{key:{'value':value} for key,value in options.items()},
                    'inputs':{} if name in SOURCES else {'input':{'kind':'table','required':True}}}
              for name,options in OPTIONS.items()}


def plan(document):
    keys(document,('version','nodes','outputs'),'$')
    if document.get('version')!='schemaxis.octave/1':fail('UNSUPPORTED_VERSION','expected schemaxis.octave/1')
    nodes=document.get('nodes')
    if not isinstance(nodes,list) or not 1<=len(nodes)<=64:fail('INVALID_DOCUMENT','provide 1 to 64 numerical nodes')
    prepared=[];seen=set()
    for node in nodes:
        keys(node,('id','filter','inputs','options'),'$.nodes')
        identity=node.get('id');op=node.get('filter')
        if not isinstance(identity,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',identity):fail('INVALID_NAME','node id must be a bounded ASCII identifier')
        if identity in seen:fail('DUPLICATE_NODE','repeated numerical node',identity)
        if not isinstance(op,str) or op not in OPTIONS:fail('UNKNOWN_FILTER','unknown numerical operation',identity)
        options=validate_arguments(OPTIONS[op],node.get('options',{}),location=identity)
        inputs=node.get('inputs',{})
        keys(inputs,() if op in SOURCES else ('input',),identity)
        if op not in SOURCES and (not isinstance(inputs.get('input'),str) or inputs['input'] not in seen):fail('INVALID_DEPENDENCY','input must reference an earlier table',identity)
        if op=='samples' and len(options['x'])!=len(options['y']):fail('INVALID_TABLE','x and y lengths differ',identity)
        if op=='movingMean' and options['window']%2!=1:fail('INVALID_ARGUMENT','moving mean window must be odd',identity)
        if op=='readCSV' and not Path(options['file']).is_absolute():fail('INVALID_RESOURCE','CSV input path must be absolute',identity)
        prepared.append({'id':identity,'filter':op,'inputs':copy.deepcopy(inputs),'options':options});seen.add(identity)
    outputs=document.get('outputs')
    if not isinstance(outputs,list) or not outputs or any(not isinstance(v,str) or v not in seen for v in outputs) or len(set(outputs))!=len(outputs):
        fail('INVALID_SELECTION','outputs must name distinct declared tables')
    return {'version':'schemaxis.octave.plan/1','nodes':prepared,'outputs':list(outputs),'expectedPublications':len(outputs)+1}


def schema():
    from schemaxis.schema import DRAFT,object_schema,argument_schema
    name={'type':'string','pattern':'^[A-Za-z][A-Za-z0-9_]{0,63}$'}
    variants=[]
    for op,decl in DECLARATIONS.items():
        opts=object_schema({k:argument_schema(v) for k,v in OPTIONS[op].items()},[k for k,v in OPTIONS[op].items() if v.get('required')])
        variants.append(object_schema({'id':name,'filter':{'const':op},'options':opts,
                                      'inputs':object_schema({k:name for k in decl['inputs']},list(decl['inputs']))},
                                     ['id','filter']+(['inputs'] if decl['inputs'] else [])+(['options'] if opts.get('required') else [])))
    return {'$schema':DRAFT,**object_schema({'version':{'const':'schemaxis.octave/1'},
        'nodes':{'type':'array','minItems':1,'maxItems':64,'items':{'oneOf':variants}},
        'outputs':{'type':'array','minItems':1,'maxItems':64,'uniqueItems':True,'items':name}},['version','nodes','outputs'])}


def reusableInputs(document):
    return {n['options']['file']:file_digest(n['options']['file']) for n in plan(document)['nodes'] if n['filter']=='readCSV'}


def _sources(prepared,directory):
    return {node['id']:read_csv(directory/('source-'+node['id']+'.csv'),minimum=2) for node in prepared['nodes'] if node['filter']=='readCSV'}


def manifest(directory,prepared):
    names=[(identity+'.csv','table') for identity in prepared['outputs']]+[('statistics.json','analysis')]
    return [{'file':str(directory/name),'kind':kind,'sha256':file_digest(directory/name)} for name,kind in names]


def run(document,directory,*,executable=None,timeout=300):
    prepared=plan(document)
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=3600:fail('INVALID_TIMEOUT','timeout must be within 0 to 3600 seconds')
    executable=executable or os.environ.get('SCHEMAXIS_OCTAVE') or shutil.which('octave-cli')
    if not executable or not Path(executable).is_file():fail('INTERPRETER_NOT_FOUND','configure GNU Octave or pass --octave')
    directory=Path(directory).absolute()
    if directory.exists():fail('OUTPUT_EXISTS','choose a fresh output directory',str(directory))
    directory.mkdir(parents=True)
    atomic_json(directory/'authored.json',document);atomic_json(directory/'plan.json',prepared)
    atomic_json(directory/'result.json',{'status':'incomplete','verified':False})
    try:
        provenance={}
        for node in prepared['nodes']:
            if node['filter']!='readCSV':continue
            source=Path(node['options']['file']);target=directory/('source-'+node['id']+'.csv')
            # Read and validate the bounded source before retaining bytes.
            read_csv(source,minimum=2)
            before=file_digest(source);shutil.copyfile(source,target)
            if file_digest(target)!=before or file_digest(source)!=before:fail('INPUT_CHANGED','CSV changed during capture',str(source))
            provenance[node['id']]={'file':str(source),'sha256':before}
        atomic_json(directory/'sources.json',provenance)
        sources=_sources(prepared,directory)
        evaluate(prepared,sources)  # reject invalid sampling/budgets before launching native code
        from .worker import WORKER
        (directory/'worker.m').write_text(WORKER)
        atomic_json(directory/'request.json',{'plan':prepared,'sources':sources})
        execute([str(Path(executable).absolute()),'--no-init-file','--no-site-file','--no-history','--quiet',str(directory/'worker.m')],directory,'analysis',timeout,
                {'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','OCTAVE_HISTFILE':os.devnull})
        result=verify(directory,require_result=False)
        result.update(status='succeeded')
        atomic_json(directory/'result.json',result)
        return result
    except Exception as error:
        atomic_json(directory/'result.json',{'status':'failed','verified':False,'message':str(error)})
        raise


def verify(directory,require_result=True):
    directory=Path(directory).absolute()
    try:
        prepared=plan(json.loads((directory/'authored.json').read_text()))
        def require(condition,message):
            if not condition:fail('VERIFICATION_FAILED',message,str(directory))
        require(json.loads((directory/'plan.json').read_text())==prepared,'plan differs from authored analysis')
        if require_result:require(json.loads((directory/'result.json').read_text()).get('verified') is True,'analysis did not complete')
        provenance=json.loads((directory/'sources.json').read_text())
        imports=[node for node in prepared['nodes'] if node['filter']=='readCSV']
        require(set(provenance)=={n['id'] for n in imports},'source membership differs')
        for node in imports:
            path=directory/('source-'+node['id']+'.csv')
            require(not path.is_symlink() and provenance[node['id']]=={'file':node['options']['file'],'sha256':file_digest(path)},'captured input changed')
        sources=_sources(prepared,directory)
        require(json.loads((directory/'request.json').read_text())=={'plan':prepared,'sources':sources},'native request differs from authored analysis')
        expected=evaluate(prepared,sources)
        native=json.loads((directory/'native.json').read_text())
        require(isinstance(native.get('runtime'),str) and re.fullmatch(r'\d+\.\d+\.\d+',native['runtime']) is not None,'Octave runtime version is missing')
        require(close(native.get('nodes'),expected),'native numerical results differ from independent reference')
        for identity in prepared['outputs']:
            path=directory/(identity+'.csv')
            table={'columns':['x','y'],'rows':[list(row) for row in zip(expected[identity]['x'],expected[identity]['y'])]}
            require(not path.is_symlink() and close(read_csv(path,minimum=2),table),'published CSV differs: '+identity)
        require(not (directory/'statistics.json').is_symlink(),'statistics publication is a symlink')
        stats={identity:expected[identity]['statistics'] for identity in prepared['outputs']}
        require(close(json.loads((directory/'statistics.json').read_text()),stats),'published statistics differ')
        require(not (directory/'worker.m').is_symlink(),'native worker is a symlink')
        records={'artifacts':manifest(directory,prepared),'workerSha256':file_digest(directory/'worker.m')}
        if require_result:require(json.loads((directory/'verification.json').read_text())==records,'artifact membership or digest differs')
        else:atomic_json(directory/'verification.json',records)
        return {'verified':True,'artifacts':len(records['artifacts']),'runtime':native['runtime'],'tables':prepared['outputs']}
    except SchemaxisError:raise
    except (OSError,ValueError,TypeError,KeyError,IndexError,AttributeError,OverflowError) as error:
        fail('VERIFICATION_FAILED','missing or malformed numerical evidence: '+str(error),str(directory))


# Shared authored-input, analytic-visit and verification boundary.
from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
