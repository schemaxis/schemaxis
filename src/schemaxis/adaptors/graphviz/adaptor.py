# Copyright (C) 2026 David L F Gaden
"""Declared directed topology, trusted DOT, and independent geometry inspection."""
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
from .inspection import inspect

VERSION = 'schemaxis.graphviz/1'
LIMIT = 4*1024*1024
IDENT = {'type':'string','minLength':1,'maxLength':32,'required':True}
NODE = {'type':'object','properties':{'id':IDENT,'label':{'type':'string','minLength':1,'maxLength':24,'required':True}}}
EDGE = {'type':'object','properties':{'source':IDENT,'target':IDENT}}
OPTIONS = {'nodes':{'type':'array','items':NODE,'minItems':2,'maxItems':200,'required':True},
    'edges':{'type':'array','items':EDGE,'minItems':1,'maxItems':500,'required':True},
    'rankDirection':{'type':'enum','values':['TB','LR'],'default':'TB'},
    'graphPolicy':{'type':'enum','values':['dag','cyclic'],'default':'dag'}}
DECLARATIONS = {'layout':{'native':'dot -Kdot -Tplain -Tsvg; digraph, rankdir, node.label, directed edge',
    'kinds':['image','text'],'inputs':{},'options':{k:{'value':v} for k,v in OPTIONS.items()}}}
LOSSES = ['Directed simple graphs only: 2–200 nodes, 1–500 unique edges; no self-edges, parallel edges, clusters, ports, edge labels or authored DOT.',
    'Fixed 2.5 by 0.5 inch boxes, monochrome cubic splines and arrowheads. Plain layout geometry is inches from lower left; SVG uses 72 points per inch and inverted y.',
    'Labels are 1–24 ASCII letters/digits/spaces and ._:/()+-; HTML, quotes, backslashes and arbitrary native attributes are excluded.',
    'DAG mode requires an acyclic graph and checks every edge follows TB/LR. Cyclic mode allows cycles without promising monotone ranks.',
    'Topology, literal labels, positive finite bounds, box separation, spline endpoint attachment and SVG/plain coordinate coherence are checked; no optimal layout, crossing minimisation, font metrics or rendered typography correctness claim.']


def topology(p):
    names=[n['id'] for n in p['nodes']];incoming={n:0 for n in names};outgoing={n:[] for n in names}
    for e in p['edges']:incoming[e['target']]+=1;outgoing[e['source']].append(e['target'])
    queue=sorted(n for n in names if incoming[n]==0);order=[]
    while queue:
        name=queue.pop(0);order.append(name)
        for target in outgoing[name]:
            incoming[target]-=1
            if incoming[target]==0:queue.append(target);queue.sort()
    return {'acyclic':len(order)==len(names),'topologicalOrder':order if len(order)==len(names) else [],
        'nodeIds':names,'edgePairs':[[e['source'],e['target']] for e in p['edges']]}


def plan(document):
    keys(document,('version','operation',*OPTIONS),'$')
    if document.get('version')!=VERSION:fail('UNSUPPORTED_VERSION','expected '+VERSION,'$.version')
    if document.get('operation')!='layout':fail('UNKNOWN_FILTER','select layout','$.operation')
    p=validate_arguments(OPTIONS,{k:v for k,v in document.items() if k in OPTIONS});names=set();pairs=set()
    for i,n in enumerate(p['nodes']):
        at=f'$.nodes[{i}]'
        if not re.fullmatch('[a-z][a-z0-9_]{0,31}',n['id']) or n['id'] in names:fail('INVALID_GRAPH_NODE','choose unique lowercase ASCII node IDs',at+'.id')
        if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9 ._:/()+-]{0,23}',n['label']):fail('INVALID_GRAPH_LABEL','use 1–24 plain ASCII characters; start with a letter or digit; no DOT escapes/HTML',at+'.label')
        names.add(n['id'])
    for i,e in enumerate(p['edges']):
        at=f'$.edges[{i}]';pair=(e['source'],e['target'])
        if any(x not in names for x in pair):fail('INVALID_GRAPH_EDGE','edge endpoints must name declared nodes',at)
        if pair[0]==pair[1] or pair in pairs:fail('INVALID_GRAPH_EDGE','no self-edges or duplicate directed edges',at)
        pairs.add(pair)
    if p['graphPolicy']=='dag' and not topology(p)['acyclic']:fail('GRAPH_CYCLE','remove the cycle or explicitly choose graphPolicy cyclic','$.graphPolicy')
    return {'version':'schemaxis.graphviz.plan/1','operation':'layout',**p,'losses':LOSSES}


def schema():
    from schemaxis.schema import DRAFT,argument_schema,object_schema
    return {'$schema':DRAFT,**object_schema({'version':{'const':VERSION},'operation':{'const':'layout'},**{k:argument_schema(v) for k,v in OPTIONS.items()}},['version','operation','nodes','edges'])}


def query(document):plan(document);return ['layout'],{}
def resources(document,execution,identity):
    if execution.get('threads',1)!=1:fail('INVALID_EXECUTION','Graphviz layout is serial',identity)
    return {'threads':1}
def reusableInputs(document):plan(document);return {}


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
def read(directory,name):
    data=bounded(directory/name)
    try:return json.loads(data,object_pairs_hook=unique_object,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite JSON '+x)))
    except RecursionError:fail('VERIFICATION_FAILED','retained JSON nesting exceeds the readable limit; rerun into a fresh directory',str(directory/name))
def digest(directory,name):return hashlib.sha256(bounded(directory/name)).hexdigest()


def dot(p):
    # All user tokens already passed a restrictive grammar; no author-controlled
    # DOT attributes, reflection, HTML, resource locators or escape sequences.
    text='digraph G {\n  graph [rankdir='+p['rankDirection']+', pad=0, nodesep=0.25, ranksep=0.5];\n'
    text+='  node [shape=box, fixedsize=true, width=2.5, height=0.5, fontname="Courier", fontsize=10];\n'
    text+='  edge [color=black, arrowhead=normal];\n'
    text+=''.join('  '+json.dumps(n['id'])+' [label="'+n['label']+'"];\n' for n in p['nodes'])
    text+=''.join('  '+json.dumps(e['source'])+' -> '+json.dumps(e['target'])+';\n' for e in p['edges'])
    return text+'}\n'


def commands(executable,directory):
    return {'version':[executable,'-V'],'layout':[executable,'-Kdot','-Tplain','-o',str(directory/'graph.plain'),'-Tsvg','-o',str(directory/'graph.svg'),str(directory/'graph.dot')]}
def stage_inputs(stage):return ['graph.dot'] if stage=='layout' else []
def launcher(directory,stage,command):
    return ('import hashlib,json,os,resource,stat\nfrom pathlib import Path\n'+f'command={command!r}\npaths={[str(directory/n) for n in stage_inputs(stage)]!r}\nbindings={{}}\n'
        +'resource.setrlimit(resource.RLIMIT_AS,(536870912,536870912))\nresource.setrlimit(resource.RLIMIT_FSIZE,(8388608,8388608))\nresource.setrlimit(resource.RLIMIT_CPU,(30,30))\n'
        +'for name in paths:\n    fd=os.open(name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_NONBLOCK",0))\n    with os.fdopen(fd,"rb") as stream:\n        info=os.fstat(stream.fileno())\n'
        +f'        if not stat.S_ISREG(info.st_mode) or info.st_size>{LIMIT}: raise ValueError("invalid native input")\n        data=stream.read({LIMIT+1})\n'
        +'    bindings[name]=hashlib.sha256(data).hexdigest()\n'
        +f'Path({str(directory/(stage+"-inputs.json"))!r}).write_text(json.dumps(bindings,sort_keys=True))\n'
        +'os.execve(command[0],command,{"LANG":"C","HOME":str(Path.cwd())})\n')
def artifacts(directory):
    return [{'file':str(directory/n),'kind':kind,'sha256':digest(directory,n)} for n,kind in [('graph.svg','image'),('graph.dot','text'),('graph.plain','text'),('layout.json','text')]]
def evidence_names():return {'authored.json','plan.json',*[s+x for s in ('version','layout') for x in ('-launcher.py','-inputs.json','-submission.json','.stdout','.stderr')]}
IDENTITY=re.compile(r'dot - graphviz version ([0-9]+\.[0-9]+\.[0-9]+) \([^\r\n]+\)')
def runtime_identity(directory,retained=False):
    """Run time: any non-16.1.0 executable is unsupported. On reopen, evidence that is
    not a well-formed Graphviz identity is malformed; only a well-formed other
    version is unsupported (requalify or use the retained release)."""
    unsupported=lambda:fail('UNSUPPORTED_NATIVE_VERSION','configure Graphviz dot 16.1.0; requalify other versions before execution')
    text=bounded(directory/'version.stderr').decode().strip();found=IDENTITY.fullmatch(text)
    if bounded(directory/'version.stdout') or found is None:
        if retained:fail('VERIFICATION_FAILED','retained Graphviz version evidence is malformed; rerun into a fresh directory','version.stderr')
        unsupported()
    if found.group(1)!='16.1.0':unsupported()
    return text


def run(document,directory,*,executable=None,timeout=300):
    p=plan(document);executable=executable or os.environ.get('SCHEMAXIS_GRAPHVIZ') or shutil.which('dot')
    if not executable or not Path(executable).is_absolute() or not os.access(executable,os.X_OK):fail('INTERPRETER_NOT_FOUND','configure an absolute Graphviz dot 16.1.0 executable')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=3600:fail('INVALID_ARGUMENT','timeout must be finite in (0,3600]')
    directory=Path(directory).absolute()
    if directory.exists() or directory.is_symlink():fail('OUTPUT_EXISTS','select a fresh output directory',str(directory))
    directory.mkdir(parents=True);atomic_json(directory/'authored.json',document);atomic_json(directory/'plan.json',p);atomic_json(directory/'result.json',{'status':'incomplete','verified':False});deadline=time.monotonic()+timeout
    try:
        (directory/'graph.dot').write_text(dot(p))
        for stage,command in commands(str(executable),directory).items():
            path=directory/(stage+'-launcher.py');path.write_text(launcher(directory,stage,command))
            execute([sys.executable,str(path)],directory,stage,deadline-time.monotonic(),{'LANG':'C','HOME':str(directory)})
            if stage=='version':runtime_identity(directory)
        if bounded(directory/'layout.stdout') or bounded(directory/'layout.stderr'):fail('NATIVE_LAYOUT_WARNING','Graphviz emitted unexpected output/warnings; inspect retained logs')
        summary=inspect(directory,p,bounded,topology);atomic_json(directory/'layout.json',summary)
        atomic_json(directory/'verification.json',{'executable':str(executable),'runtime':runtime_identity(directory),'artifacts':artifacts(directory),'evidence':{n:digest(directory,n) for n in evidence_names()}})
        result=verify(directory,require_result=False)
        if cancellation_requested():fail('RUNNER_CANCELLED','Graphviz publication cancelled')
        if time.monotonic()>=deadline:fail('RUNNER_TIMED_OUT','Graphviz exhausted total deadline')
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
        if read(directory,'plan.json')!=p:fail('VERIFICATION_FAILED','effective graph plan differs')
        if require_result and read(directory,'result.json').get('status')!='succeeded':fail('INCOMPLETE_EXECUTION','Graphviz did not complete')
        if bounded(directory/'graph.dot').decode()!=dot(p):fail('VERIFICATION_FAILED','trusted DOT differs from declared graph')
        executable=receipt['executable']
        if not isinstance(executable,str) or not Path(executable).is_absolute():fail('VERIFICATION_FAILED','native executable identity must be absolute')
        for stage,command in commands(executable,directory).items():
            submission=read(directory,stage+'-submission.json');interpreter=submission.get('interpreter',{}).get('executable');path=directory/(stage+'-launcher.py')
            if not isinstance(interpreter,str) or not Path(interpreter).is_absolute() or submission.get('nativeCommand')!=[interpreter,str(path)] or type(submission.get('exitCode')) is not int or submission['exitCode']!=0:fail('VERIFICATION_FAILED','native command/completion differs',stage)
            if bounded(path).decode()!=launcher(directory,stage,command):fail('VERIFICATION_FAILED','trusted native launcher differs',stage)
            if read(directory,stage+'-inputs.json')!={str(directory/n):digest(directory,n) for n in stage_inputs(stage)}:fail('VERIFICATION_FAILED','native inputs differ',stage)
        # Classify a retained version only after checking its receipt binding.
        for n in ('version.stderr','version.stdout'):
            if digest(directory,n)!=receipt['evidence'][n]:fail('VERIFICATION_FAILED','retained version evidence differs',n)
        if bounded(directory/'version.stderr').decode().strip()!=receipt['runtime']:fail('VERIFICATION_FAILED','native Graphviz runtime identity differs')
        runtime=runtime_identity(directory,retained=True)
        if receipt['runtime']!=runtime:fail('VERIFICATION_FAILED','native Graphviz runtime identity differs')
        if bounded(directory/'layout.stdout') or bounded(directory/'layout.stderr'):fail('VERIFICATION_FAILED','native layout warning/output differs')
        expected=inspect(directory,p,bounded,topology)
        if json.dumps(read(directory,'layout.json'),sort_keys=True)!=json.dumps(expected,sort_keys=True):fail('VERIFICATION_FAILED','published geometry differs from independent inspection')
        if receipt['artifacts']!=artifacts(directory):fail('VERIFICATION_FAILED','publication membership/digests differ')
        if set(receipt['evidence'])!=evidence_names():fail('VERIFICATION_FAILED','evidence membership differs')
        for n in evidence_names():
            if digest(directory,n)!=receipt['evidence'][n]:fail('VERIFICATION_FAILED','retained native evidence differs',n)
        return {'verified':True,'artifacts':4,'runtime':runtime,'nodes':len(p['nodes']),'edges':len(p['edges'])}
    except (OSError,ValueError,KeyError,TypeError,IndexError,AttributeError,RecursionError) as e:fail('VERIFICATION_FAILED','invalid retained graph evidence: '+str(e))

from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
