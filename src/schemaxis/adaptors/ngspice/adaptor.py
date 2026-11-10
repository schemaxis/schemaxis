# Copyright (C) 2026 David L F Gaden
"""Bounded declared linear circuits executed by an isolated ngspice process."""
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
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute
from schemaxis.tabular import read_csv, write_csv, close
from . import circuit,performance

VERSION='schemaxis.ngspice/1'
NODE={'type':'string','minLength':1,'maxLength':32}
COMPONENT={'name':{**NODE,'required':True},'a':{**NODE,'required':True},'b':{**NODE,'required':True}}
CIRCUIT={'type':'object','required':True,'properties':{
    'source':{**NODE,'default':'in'},
    'resistors':{'type':'array','minItems':1,'maxItems':64,'required':True,'items':{'type':'object','properties':{
        **COMPONENT,'resistance':{'type':'number','minimum':0.001,'maximum':1e9,'required':True}}}},
    'capacitors':{'type':'array','maxItems':64,'default':[],'items':{'type':'object','properties':{
        **COMPONENT,'capacitance':{'type':'number','minimum':1e-12,'maximum':1,'required':True}}}},
    'probes':{'type':'array','minItems':1,'maxItems':16,'uniqueItems':True,'items':NODE,'default':['out']}}}
AC_CIRCUIT={**CIRCUIT,'properties':{**CIRCUIT['properties'],
    'inductors':{'type':'array','maxItems':64,'default':[],'items':{'type':'object','properties':{
        **COMPONENT,'inductance':{'type':'number','minimum':1e-9,'maximum':1e3,'required':True}}}},
    'probes':{**CIRCUIT['properties']['probes'],'maxItems':15},
    'branchProbes':{'type':'array','maxItems':8,'uniqueItems':True,'default':[],'items':NODE}}}
POINTS={'type':'integer','minimum':2,'maximum':512,'default':101}
AMPLITUDE={'type':'number','minimum':-1000,'maximum':1000,'default':1}
OPTIONS={
    'dcSweep':{'circuit':CIRCUIT,'start':{**AMPLITUDE,'default':0},'stop':{**AMPLITUDE,'default':5},'points':POINTS},
    'acSweep':{'circuit':AC_CIRCUIT,'start':{'type':'number','minimum':0.001,'maximum':1e9,'default':1},
               'stop':{'type':'number','minimum':0.001,'maximum':1e9,'default':10000},'points':{**POINTS,'minimum':3},'amplitude':AMPLITUDE,
               'spacing':{'type':'enum','values':['linear','decade','octave'],'default':'linear'},
               'portMetrics':{'type':'boolean','default':False},
               'amplitudeConvention':{'type':'enum','values':['peak','rms'],'default':'peak'}},
    'rcStep':{'circuit':CIRCUIT,'stop':{'type':'number','minimum':1e-9,'maximum':1e6,'default':0.005},'points':POINTS,'amplitude':AMPLITUDE}}
DECLARATIONS={op:{'native':{'dcSweep':'ngspice dc','acSweep':'ngspice ac lin/dec/oct','rcStep':'ngspice tran/linearize'}[op],
    'kinds':['table'],'inputs':{},'options':{k:{'value':v} for k,v in opts.items()}} for op,opts in OPTIONS.items()}
FILES=[('results.csv','table'),('circuit-summary.json','text'),('circuit.cir','text')]
EVIDENCE=['native.dat','reopened.dat','result.raw','reopen.cir','runtime.json','version.stdout','version.stderr']
LOSSES=['Only ideal resistors, capacitors, AC-only uncoupled inductors and one grounded ideal voltage source; no semiconductors, models, subcircuits or imported scripts',
        'DC treats capacitors as open circuits; AC is a linear phasor response with exp(+j*omega*t) convention',
        'Transient support is one initially uncharged series-R/shunt-C step response; no general transient circuit claim',
        'AC branch currents and powers derive from verified terminal voltages and ideal constitutive laws; portMetrics also checks native source current and publishes input impedance/power',
        'Finite frequency/time samples do not prove continuous extrema or all component tolerances; retain topology and assumptions with CSV']


RESERVED_GROUND_ALIAS='gnd'


def refuse_ground_alias(network):
    """Refuse every authored node token that ngspice would silently rewrite to ground.

    ngspice lowercases the deck, then replaces a whole delimited ``gnd`` token on
    each card after the first token with node 0 (inpcom.c inp_fix_gnd_name, unless
    no_auto_gnd is set). The generated netlist would then describe a different
    circuit from the planned one, so the alias is refused rather than normalised.
    """
    positions=[('$.circuit.source',network['source'])]
    for kind in ('resistors','capacitors','inductors'):
        for index,component in enumerate(network.get(kind,[])):
            positions.extend((f'$.circuit.{kind}[{index}].{terminal}',component[terminal]) for terminal in ('a','b'))
    positions.extend((f'$.circuit.probes[{index}]',probe) for index,probe in enumerate(network['probes']))
    for location,value in positions:
        if isinstance(value,str) and value.lower()==RESERVED_GROUND_ALIAS:
            raise SchemaxisError(Fault('INVALID_CIRCUIT',
                "node name 'gnd' is reserved: ngspice rewrites it to ground node 0, which would change the simulated circuit",
                location,'pipeline',observed={'node':value,'reservedAlias':RESERVED_GROUND_ALIAS,'ngspiceNode':'0'},
                recovery="Use 0 for ground, or choose another node name such as gnd1 or ground; names are matched case-insensitively."))


def plan(document):
    keys(document,('version','operation','circuit','start','stop','points','amplitude','spacing','portMetrics','amplitudeConvention','requirements'),'$')
    if document.get('version')!=VERSION:fail('UNSUPPORTED_VERSION','expected '+VERSION)
    operation=document.get('operation')
    if not isinstance(operation,str) or operation not in OPTIONS:fail('UNKNOWN_FILTER','select dcSweep, acSweep or rcStep')
    options=validate_arguments(OPTIONS[operation],{k:v for k,v in document.items() if k not in ('version','operation','requirements')})
    network=options['circuit'];drive=network['source']
    refuse_ground_alias(network)
    def node(value):
        return isinstance(value,str) and (value=='0' or re.fullmatch(r'[a-z][a-z0-9_]{0,31}',value) is not None)
    if not node(drive) or drive=='0':fail('INVALID_CIRCUIT','source must name a lowercase non-ground node')
    names=set();nodes={drive};edges={}
    for kind in ('resistors','capacitors','inductors'):
        for component in network.get(kind,[]):
            label=component['name'];a,b=component['a'],component['b']
            if not node(label) or label=='0' or label in names:fail('INVALID_CIRCUIT','component names must be unique lowercase identifiers')
            if not node(a) or not node(b) or a==b:fail('INVALID_CIRCUIT','each component needs two distinct bounded node names')
            names.add(label);nodes.update((a,b))
            if kind in ('resistors','inductors'):
                edges.setdefault(a,set()).add(b);edges.setdefault(b,set()).add(a)
    nodes.discard('0')
    if len(nodes)>16:fail('RESOURCE_LIMIT','use at most sixteen non-ground nodes')
    reached={'0',drive};pending=list(reached)
    while pending:
        for other in edges.get(pending.pop(),set())-reached:
            reached.add(other);pending.append(other)
    if not nodes<=reached:fail('FLOATING_CIRCUIT','every node needs a resistor/inductor path to ground or the driven source')
    # Ngspice computes a DC operating point before AC. Inductors are shorts
    # there: a loop of ideal inductors/source leaves branch currents undefined.
    parents={n:n for n in nodes|{'0'}};parents[drive]='0'
    def root(n):
        while parents[n]!=n:n=parents[n]
        return n
    for component in network.get('inductors',[]):
        a,b=root(component['a']),root(component['b'])
        if a==b:fail('UNSUPPORTED_CIRCUIT','AC requires no ideal-inductor loops or inductive short across the voltage source')
        parents[a]=b
    if any(not node(p) or p=='0' or p not in nodes for p in network['probes']):fail('INVALID_SELECTION','probes must name present non-ground nodes')
    if operation!='rcStep' and options['stop']<=options['start']:fail('INVALID_SWEEP','stop must exceed start')
    if operation=='acSweep' and options['amplitude']==0:fail('INVALID_ARGUMENT','AC amplitude must be nonzero')
    result={'version':'schemaxis.ngspice.plan/1','operation':operation,**options,'nodes':sorted(nodes),'losses':LOSSES}
    axis=circuit.samples(result)
    if not 3<=len(axis)<=512 and operation=='acSweep':
        fail('RESOURCE_LIMIT','AC needs 3–512 actual frequency samples; adjust range or points density','$.points')
    if operation=='acSweep':
        if any(name not in names for name in network['branchProbes']):
            fail('INVALID_SELECTION','branchProbes must name declared components','$.circuit.branchProbes')
        columns=1+4*len(network['probes'])+6*len(network['branchProbes'])+10*options['portMetrics']
        if columns>64:fail('RESOURCE_LIMIT','selected voltage, branch and port metrics exceed 64 output columns; select fewer probes','$.circuit')
    if any(b<=a for a,b in zip(axis,axis[1:])):
        fail('INVALID_SWEEP','sample spacing must be representable; widen the interval or reduce points')
    if operation=='rcStep':
        if len(network['resistors'])!=1 or len(network['capacitors'])!=1 or len(nodes)!=2:
            fail('UNSUPPORTED_CIRCUIT','rcStep needs exactly one series resistor and one grounded capacitor')
        response=next(n for n in nodes if n!=drive);r=network['resistors'][0];c=network['capacitors'][0]
        if {r['a'],r['b']}!={drive,response} or {c['a'],c['b']}!={response,'0'}:
            fail('UNSUPPORTED_CIRCUIT','rcStep topology is source--R--response--C--ground')
        tau=r['resistance']*c['capacitance']
        if not 0.01<=options['stop']/tau<=20:fail('RESOURCE_LIMIT','rcStep stop must lie between 0.01 and 20 RC time constants')
        if options['amplitude']==0:fail('INVALID_ARGUMENT','step amplitude must be nonzero')
        result.update(responseNode=response,timeConstant=tau)
    else:
        # Reject singular/ill-conditioned systems before native assignment.
        for value in axis:
            values=circuit.voltages(result,value)
            if result.get('portMetrics'):circuit.port_impedance(result,value,values)
    if 'requirements' in document:result['requirements']=performance.validate(result,document['requirements'])
    return result


def schema():
    from schemaxis.schema import DRAFT,object_schema,argument_schema
    variants=[]
    for op,options in OPTIONS.items():
        fields={'version':{'const':VERSION},'operation':{'const':op},**{k:argument_schema(v) for k,v in options.items()}}
        fields['requirements']=performance.requirement_schema(op)
        variants.append(object_schema(fields,['version','operation','circuit']))
    # Keep the common object envelope explicit for discovery; each closed
    # operation variant remains authoritative for its required fields/bounds.
    fields={}
    for variant in variants:
        for key,value in variant['properties'].items():
            if value not in fields.setdefault(key,[]):fields[key].append(value)
    properties={key:(values[0] if len(values)==1 else {'anyOf':values}) for key,values in fields.items()}
    return {'$schema':DRAFT,**object_schema(properties,['version','operation','circuit']),'oneOf':variants}


def query(document):
    prepared=plan(document)
    operations=list(dict.fromkeys(visit['plan']['operation'] for visit in prepared['visits'])) if 'visits' in prepared else [prepared['operation']]
    return operations,{}


def reusableInputs(document):
    plan(document);return {}


def resources(document,spec,identity):
    if spec.get('threads',1)!=1:fail('INVALID_EXECUTION','this circuit slice uses one thread',identity)
    return {'threads':1}


def expressions(prepared):
    if prepared['operation']=='acSweep':
        return ' '.join(f'real(v({n})) imag(v({n}))' for n in prepared['nodes'])+(' real(i(vdrive)) imag(i(vdrive))' if prepared.get('portMetrics') else '')
    return ' '.join(f'v({n})' for n in prepared['nodes'])


def netlists(prepared):
    operation=prepared['operation'];network=prepared['circuit'];drive=network['source']
    amplitude=prepared.get('amplitude',prepared.get('start',0))
    lines=['Schemaxis declared linear circuit',f'Vdrive {drive} 0 DC {amplitude:.17g} AC {amplitude:.17g}']
    for component in network['resistors']:
        lines.append(f"R_{component['name']} {component['a']} {component['b']} {component['resistance']:.17g}")
    for component in network['capacitors']:
        lines.append(f"C_{component['name']} {component['a']} {component['b']} {component['capacitance']:.17g}")
    for component in network.get('inductors',[]):
        lines.append(f"L_{component['name']} {component['a']} {component['b']} {component['inductance']:.17g}")
    if operation=='rcStep':lines.append(f".ic v({prepared['responseNode']})=0")
    lines.append('.options reltol=1e-9 abstol=1e-13 vntol=1e-11')
    control=['.control','set noaskquit','set filetype=ascii','set numdgt=17','set wr_singlescale','set wr_vecnames']
    if operation=='dcSweep':
        step=(prepared['stop']-prepared['start'])/(prepared['points']-1)
        commands=[f"dc Vdrive {prepared['start']:.17g} {prepared['stop']:.17g} {step:.17g}"]
    elif operation=='acSweep':
        kind={'linear':'lin','decade':'dec','octave':'oct'}[prepared['spacing']]
        commands=[f"ac {kind} {prepared['points']} {prepared['start']:.17g} {prepared['stop']:.17g}"]
    else:
        step=prepared['stop']/(prepared['points']-1);maximum=min(step,prepared['timeConstant']/1000)
        commands=[f"tran {step:.17g} {prepared['stop']:.17g} 0 {maximum:.17g}",
                  'linearize '+' '.join(f'v({n})' for n in prepared['nodes'])]
    saved=' '.join(f'v({n})' for n in prepared['nodes'])+(' i(vdrive)' if prepared.get('portMetrics') else '')
    build='\n'.join(lines+control+commands+['write result.raw '+saved,'wrdata native.dat '+expressions(prepared),'quit','.endc','.end'])+'\n'
    reopen='\n'.join(['Schemaxis raw-data readback']+control+['load result.raw','wrdata reopened.dat '+expressions(prepared),'quit','.endc','.end'])+'\n'
    return build,reopen


def manifest(directory):
    return [{'file':str(directory/name),'kind':kind,'sha256':file_digest(directory/name)} for name,kind in FILES]


def summary(prepared,rows):
    error=circuit.inspect(prepared,rows)
    details={'version':'schemaxis.ngspice.summary/1','operation':prepared['operation'],'circuit':prepared['circuit'],
            'samples':len(rows),'firstRow':circuit.publication(prepared,rows)['rows'][0],
            'lastRow':circuit.publication(prepared,rows)['rows'][-1],'columns':circuit.publication(prepared,rows)['columns'],
            'maximumVoltageError_V':error,'timeConstant_s':prepared.get('timeConstant'),
            'convention':'exp(+j*omega*t); branch current a to b; input current enters network; capacitor voltage starts at zero in rcStep',
            'amplitudeConvention':prepared.get('amplitudeConvention'),
            'complexPowerFactor':(.5 if prepared.get('amplitudeConvention')=='peak' else 1) if prepared['operation']=='acSweep' else None,'losses':LOSSES}
    if prepared.get('portMetrics'):
        details['maximumSourceCurrentError_A']=circuit.current_error(prepared,rows)
    if prepared['operation']=='acSweep':details['frequencyGrid']={'spacing':prepared['spacing'],'pointsMeaning':'total samples' if prepared['spacing']=='linear' else 'nominal samples per '+prepared['spacing'],'actualSamples':len(rows),'lastFrequency_Hz':rows[-1][0]}
    if 'requirements' in prepared:details['performance']=performance.assess(prepared,rows)
    return details


def runtime(text):
    found=re.search(r'\bngspice-(\d+(?:\.\d+)*)\s*:',text)
    if not found or found[1]!='47':fail('UNSUPPORTED_RUNTIME','expected qualified ngspice-47 executable')
    return {'name':'ngspice','version':found[1]}


def run(document,directory,*,executable=None,timeout=300):
    prepared=plan(document)
    executable=executable or os.environ.get('NGSPICE_EXECUTABLE') or shutil.which('ngspice')
    if not executable or not Path(executable).is_absolute() or not Path(executable).is_file() or not os.access(executable,os.X_OK):
        fail('INTERPRETER_NOT_FOUND','configure an absolute ngspice-47 executable or pass --ngspice')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=3600:fail('INVALID_ARGUMENT','timeout must be in (0,3600]')
    directory=Path(directory).absolute()
    if directory.exists() or directory.is_symlink():fail('OUTPUT_EXISTS','choose a fresh output directory',str(directory))
    directory.mkdir(parents=True);atomic_json(directory/'authored.json',document);atomic_json(directory/'plan.json',prepared)
    atomic_json(directory/'result.json',{'status':'incomplete','verified':False})
    try:
        build,reopen=netlists(prepared);(directory/'circuit.cir').write_text(build);(directory/'reopen.cir').write_text(reopen)
        deadline=time.monotonic()+timeout
        environment={'OMP_NUM_THREADS':'1'}
        execute([executable,'-n','--version'],directory,'version',deadline-time.monotonic(),environment)
        observed=runtime((directory/'version.stdout').read_text());observed['executable']=executable
        atomic_json(directory/'runtime.json',observed)
        for stage,name in [('build','circuit.cir'),('reopen','reopen.cir')]:
            execute([executable,'-n','-b',name],directory,stage,deadline-time.monotonic(),environment)
        width=circuit.row_width(prepared)
        rows=circuit.read_table(directory/'native.dat',width,len(circuit.samples(prepared)))
        details=summary(prepared,rows);write_csv(directory/'results.csv',circuit.publication(prepared,rows));atomic_json(directory/'circuit-summary.json',details)
        atomic_json(directory/'verification.json',{'artifacts':manifest(directory),'evidence':{n:file_digest(directory/n) for n in EVIDENCE}})
        result=verify(directory,require_result=False)
        if cancellation_requested():fail('RUNNER_CANCELLED','circuit publication cancelled')
        if time.monotonic()>=deadline:fail('RUNNER_TIMED_OUT','circuit verification exhausted the total timeout')
        result.update(status='succeeded');atomic_json(directory/'result.json',result);return result
    except Exception as error:
        if not isinstance(error,SchemaxisError):
            try:fail('NATIVE_EXECUTION_FAILED',str(error))
            except SchemaxisError as wrapped:error=wrapped
        atomic_json(directory/'result.json',{'status':'failed','verified':False,'fault':error.fault.to_dict()});raise error


def verify(directory,require_result=True):
    directory=Path(directory).absolute()
    try:
        def read(name):return json.loads((directory/name).read_text())
        for name in [n for n,_ in FILES]+EVIDENCE+['authored.json','plan.json','result.json','verification.json']:
            p=directory/name;circuit.check(p.is_file() and not p.is_symlink() and p.stat().st_size<=4*1024*1024,'missing/excessive regular evidence: '+name)
        prepared=plan(read('authored.json'));circuit.check(prepared==read('plan.json'),'effective plan differs from authored circuit')
        if require_result:circuit.check(read('result.json').get('status')=='succeeded' and read('result.json').get('verified') is True,'execution incomplete')
        circuit.check(read('verification.json')=={'artifacts':manifest(directory),'evidence':{n:file_digest(directory/n) for n in EVIDENCE}},'publication/native evidence digest differs')
        build,reopen=netlists(prepared)
        circuit.check((directory/'circuit.cir').read_text()==build and (directory/'reopen.cir').read_text()==reopen,'generated netlist differs')
        observed=read('runtime.json');identity=runtime((directory/'version.stdout').read_text())
        circuit.check(observed['name']==identity['name'] and observed['version']==identity['version'] and Path(observed['executable']).is_absolute(),'native runtime identity differs')
        width=circuit.row_width(prepared)
        rows=circuit.read_table(directory/'native.dat',width,len(circuit.samples(prepared)))
        circuit.inspect(prepared,rows)
        reread=circuit.read_table(directory/'reopened.dat',width,len(circuit.samples(prepared)))
        circuit.inspect(prepared,reread);circuit.check(close(rows,reread,rel=1e-12,absolute=1e-12),'fresh native raw-data readback differs')
        raw=circuit.read_raw(directory/'result.raw',prepared)
        circuit.inspect(prepared,raw);circuit.check(close(rows,raw,rel=1e-12,absolute=1e-12),'independent raw parser differs')
        circuit.check(close(read_csv(directory/'results.csv'),circuit.publication(prepared,rows),rel=1e-12,absolute=1e-12),'published table differs from native values')
        details=summary(prepared,rows)
        circuit.check(read('circuit-summary.json')==details,'summary differs from independently checked circuit')
        if 'performance' in details and not details['performance']['accepted']:
            fail('PERFORMANCE_NOT_MET','verified circuit response does not meet the named sampled requirements',
                '$.requirements',assessment=details['performance'])
        result={'verified':True,'artifacts':len(FILES),'runtime':observed,'samples':len(rows),'operation':prepared['operation']}
        if 'performance' in details:result['performance']=details['performance']
        return result
    except (OSError,ValueError,KeyError,TypeError,AttributeError,IndexError,OverflowError) as error:
        fail('VERIFICATION_FAILED','missing or invalid circuit evidence: '+str(error))


# Shared authored-input, analytic-visit and verification boundary.
from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
