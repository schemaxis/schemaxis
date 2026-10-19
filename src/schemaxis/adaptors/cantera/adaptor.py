"""Bounded ideal-gas thermodynamics, equilibrium and reactor histories in isolated Cantera."""
import csv
import json
import math
import os
from pathlib import Path
import shutil
import time

from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute
from . import kinetics, thermo

VERSION = 'schemaxis.cantera/1'
TEMPERATURES = {'type':'array','minItems':2,'maxItems':100,
                'items':{'type':'number','minimum':300,'maximum':3500},'default':[300,600,900]}
OPTIONS = {
    'gas':{
        'pressure':{'type':'number','minimum':1000,'maximum':10000000,'default':101325},
        'basis':{'type':'enum','values':['mole','mass'],'default':'mole'},
        'composition':{'type':'array','minItems':1,'maxItems':10,'required':True,'items':{
            'type':'object','properties':{
                'species':{'type':'enum','values':list(thermo.SPECIES),'required':True},
                'amount':{'type':'number','minimum':0,'maximum':1e6,'required':True}}}}},
    'thermoSweep':{'temperatures':TEMPERATURES},
    'equilibrate':{'temperatures':{**TEMPERATURES,'default':[1000,1500,2000]},
                   'mode':{'type':'enum','values':['TP','HP'],'default':'TP'}},
    'reactorHistory':{
        'model':{'type':'enum','values':list(kinetics.MODELS),'default':'constantPressure'},
        'temperature':{'type':'number','minimum':300,'maximum':3500,'default':1000},
        'times':{'type':'array','minItems':2,'maxItems':100,'items':{'type':'number','minimum':0,'maximum':1},
                 'default':[0,0.0001,0.0002,0.0003,0.0004,0.0005,0.001]},
        'relativeTolerance':{'type':'number','minimum':1e-12,'maximum':1e-8,'default':1e-9},
        'absoluteTolerance':{'type':'number','minimum':1e-20,'maximum':1e-12,'default':1e-15},
        'maxSteps':{'type':'integer','minimum':100,'maximum':100000,'default':20000},
        'ignitionTemperatureRise':{'type':'number','minimum':10,'maximum':1000,'default':400}},
}
DECLARATIONS = {name:{'native':{'gas':'cantera.Solution','thermoSweep':'cantera.ThermoPhase',
    'equilibrate':'cantera.ThermoPhase.equilibrate','reactorHistory':'cantera.ReactorNet'}[name],
    'kinds':['gas' if name == 'gas' else 'table'],
    'options':{k:{'value':v} for k,v in options.items()},
    'inputs':{} if name == 'gas' else {'input':{'kind':'gas','required':True}}}
    for name,options in OPTIONS.items()}
FILES = [('results.csv','table'),('chemistry-summary.json','text')]
EVIDENCE = ['built.json','reopened.json','mechanism.yaml','worker.py']
LOSSES = ['Only the ten-species h2o2.yaml ideal-gas ohmech phase; N2 and Ar are inert, no NOx or carbon chemistry',
          'No liquid/solid phases, nonideal equation of state, transport, kinetics or ignition-delay claim',
          'CSV is a numeric state table; retain summary for units, species, basis, mechanism and verification scope']
REACTOR_COLUMNS = ['time_s']+thermo.COLUMNS[1:]
REACTOR_LOSSES = ['Only the ten-species h2o2.yaml ideal-gas ohmech phase and its 29 reactions; N2 and Ar are inert colliders, no NOx or carbon chemistry',
                  'One closed, adiabatic, homogeneous reactor: no walls, heat loss, inlets, surfaces, mixing, transport or spatial structure',
                  'Sampled states only; the ignition delay is the declared temperature-rise criterion, not a measured or universal ignition definition',
                  'CSV is a numeric time-history table; retain summary for model, tolerances, ignition criterion and verification scope']


def plan(document):
    from schemaxis.pipeline import name
    keys(document,('version','nodes','output'),'$')
    if document.get('version') != VERSION: fail('UNSUPPORTED_VERSION','expected '+VERSION)
    nodes = document.get('nodes')
    if not isinstance(nodes,list) or len(nodes) != 2:
        fail('INVALID_DOCUMENT','provide one gas source followed by one thermoSweep, equilibrate or reactorHistory node')
    prepared = []; seen = set()
    for index,node in enumerate(nodes):
        keys(node,('id','filter','options','inputs'),'$.nodes['+str(index)+']')
        identity = name(node.get('id'),'node.id'); op = node.get('filter')
        if identity in seen: fail('DUPLICATE_NODE','node identifier is repeated',identity)
        if not isinstance(op,str) or op not in OPTIONS: fail('UNKNOWN_FILTER','unsupported chemistry operation',identity)
        if (index == 0 and op != 'gas') or (index == 1 and op == 'gas'):
            fail('INVALID_DEPENDENCY','gas must precede the table operation',identity)
        options = validate_arguments(OPTIONS[op],node.get('options',{}),location=identity+'.options')
        inputs = node.get('inputs',{}); expected = {} if index == 0 else {'input':prepared[0]['id']}
        keys(inputs,tuple(expected),identity+'.inputs')
        if inputs != expected: fail('INVALID_DEPENDENCY','reference the preceding gas source',identity)
        if op == 'gas':
            species = [c['species'] for c in options['composition']]
            if len(set(species)) != len(species): fail('INVALID_COMPOSITION','species must appear once',identity)
            if math.fsum(c['amount'] for c in options['composition']) <= 0:
                fail('INVALID_COMPOSITION','composition must contain a positive amount',identity)
        if op == 'reactorHistory' and any(b <= a for a,b in zip(options['times'],options['times'][1:])):
            fail('INVALID_TIMES','sample times must increase strictly',identity+'.options.times')
        prepared.append({'id':identity,'filter':op,'options':options,'inputs':inputs}); seen.add(identity)
    if document.get('output') != prepared[-1]['id']: fail('INVALID_SELECTION','output must select the table node')
    result = {'version':'schemaxis.cantera.plan/1','nodes':prepared,'output':document['output'],
              'mechanism':{'name':'h2o2.yaml','phase':'ohmech','sha256':thermo.DATA['mechanismSHA256']},
              'columns':thermo.COLUMNS,'limits':{'rows':100,'temperature_K':[300,3500],
                  'pressure_Pa':[1000,10000000]},'losses':LOSSES}
    if prepared[1]['filter'] == 'reactorHistory':
        model = prepared[1]['options']['model']
        result.update(columns=REACTOR_COLUMNS,losses=REACTOR_LOSSES,
                      reactor={'native':'cantera.'+kinetics.MODELS[model],'network':'cantera.ReactorNet',
                               'closed':True,'adiabatic':True,'volume_m3':1.0,
                               'held':'pressure' if model == 'constantPressure' else 'volume'})
        result['limits'].update(time_s=[0,1],ignitionPassSteps=200000)
    return result


def schema():
    from schemaxis.schema import DRAFT, NAME, object_schema, arguments_schema
    variants = []
    for op,decl in DECLARATIONS.items():
        options = arguments_schema(OPTIONS[op])
        variants.append(object_schema({'id':NAME,'filter':{'const':op},'options':options,
            'inputs':object_schema({k:NAME for k in decl['inputs']},list(decl['inputs']))},
            ['id','filter']+(['options'] if options.get('required') else [])+(['inputs'] if decl['inputs'] else [])))
    return {'$schema':DRAFT,**object_schema({'version':{'const':VERSION},
        'nodes':{'type':'array','minItems':2,'maxItems':2,'items':{'oneOf':variants}},'output':NAME},['version','nodes','output'])}


def reusableInputs(document):
    plan(document)
    return {}


def resources(document,spec,identity):
    if spec.get('threads',1) != 1: fail('INVALID_EXECUTION','this chemistry slice allocates one thread',identity)
    return {'threads':1}


def manifest(directory):
    return [{'file':str(directory/name),'kind':kind,'sha256':file_digest(directory/name)} for name,kind in FILES]


def summary(prepared,rows,native=None,reopened=None):
    reactor = prepared['nodes'][1]['filter'] == 'reactorHistory'
    if reactor:
        errors,ignition,independent = kinetics.verify_history(prepared,rows,native,reopened)
    else:
        errors = thermo.verify_rows(prepared,rows)
    result = {'version':'schemaxis.cantera.summary/1','mechanism':prepared['mechanism'],
              'species':list(thermo.SPECIES),'basis':prepared['nodes'][0]['options']['basis'],
              'normalisedInitialMoleFractions':thermo.fractions(prepared['nodes'][0]['options']),
              'operation':prepared['nodes'][1]['filter'],'settings':prepared['nodes'][1]['options'],
              'columns':prepared['columns'],'rows':len(rows),'checks':errors,
              'temperatureRange_K':[min(r[1] for r in rows),max(r[1] for r in rows)],
              'losses':prepared['losses']}
    if reactor:
        t0,pressure,x0,_ = kinetics.initial(prepared)
        state = native['reactor']
        result.update(timeRange_s=[rows[0][0],rows[-1][0]],ignition=ignition,
                      reactor={**prepared['reactor'],'initialTemperature_K':t0,'initialPressure_Pa':pressure,
                               'initialDensity_kg_m3':thermo.properties(t0,pressure,x0)[2],'mass_kg':state['initial']['mass'],
                               'solver':state['solver'],'solverStats':state['solverStats'],'ignitionPassSteps':len(state['steps'])-1},
                      independent={**independent,'method':'Four-stage L-stable Rosenbrock (Shampine), forward-difference Jacobian, host Python',
                                   'relativeTolerance':kinetics.RTOL,'absoluteTolerance_K':kinetics.ATOL[0],
                                   'absoluteToleranceMassFraction':kinetics.ATOL[1]},
                      tolerances=kinetics.TOLERANCES)
    return result


def same_summary(saved,expected):
    """Exact summary agreement except host-integrator floats, compared at 1e-6."""
    saved,expected = dict(saved),dict(expected)
    a,b = saved.pop('independent',None),expected.pop('independent',None)
    if saved != expected or (a is None) != (b is None): return False
    if a is None: return True
    if set(a) != set(b): return False
    for key,value in a.items():
        other = b[key]
        if isinstance(value,float) and isinstance(other,float):
            if not math.isclose(value,other,rel_tol=1e-6,abs_tol=1e-12): return False
        elif value != other: return False
    return True


def run(document,directory,*,executable=None,timeout=300):
    prepared = plan(document)
    executable = executable or os.environ.get('CANTERA_PYTHON')
    if not executable or not Path(executable).is_absolute() or not os.path.isfile(executable) or not os.access(executable,os.X_OK):
        fail('INTERPRETER_NOT_FOUND','configure an absolute Python executable with Cantera 3.2.x using --cantera or CANTERA_PYTHON')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        fail('INVALID_ARGUMENT','timeout must be in (0,3600]')
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink(): fail('OUTPUT_EXISTS','choose a fresh directory',str(directory))
    directory.mkdir(parents=True)
    atomic_json(directory/'authored.json',document); atomic_json(directory/'plan.json',prepared)
    atomic_json(directory/'result.json',{'status':'incomplete','verified':False})
    try:
        shutil.copyfile(Path(__file__).with_name('native.py'),directory/'worker.py')
        deadline = time.monotonic()+timeout
        for stage in ('build','reopen'):
            try:
                execute([executable,str(directory/'worker.py'),str(directory),stage],directory,stage,deadline-time.monotonic(),
                        {'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'})
            except SchemaxisError:
                if (directory/'native-fault.json').is_file():
                    fault = json.loads((directory/'native-fault.json').read_text()); fail(fault['code'],fault['message'])
                raise
            if stage == 'build':
                built = json.loads((directory/'built.json').read_text()); rows = built['rows']
                result_summary = summary(prepared,rows,built)
                with (directory/'results.csv').open('w',newline='') as stream:
                    writer = csv.writer(stream); writer.writerow(prepared['columns']); writer.writerows(rows)
                atomic_json(directory/'chemistry-summary.json',result_summary)
        atomic_json(directory/'verification.json',{'artifacts':manifest(directory),'evidence':{n:file_digest(directory/n) for n in EVIDENCE}})
        result = verify(directory,require_result=False)
        if cancellation_requested(): fail('RUNNER_CANCELLED','chemistry publication cancelled')
        result.update(status='succeeded'); atomic_json(directory/'result.json',result)
        return result
    except Exception as error:
        if not isinstance(error,SchemaxisError):
            try: fail('NATIVE_EXECUTION_FAILED',str(error))
            except SchemaxisError as wrapped: error = wrapped
        atomic_json(directory/'result.json',{'status':'failed','verified':False,'fault':error.fault.to_dict()})
        raise error


def numeric_table(rows,count,width,name):
    """Exact row count and width with finite real cells, before any cellwise comparison."""
    thermo.check(isinstance(rows,list) and len(rows) == count and all(
        isinstance(row,list) and len(row) == width and all(type(v) in (int,float) and math.isfinite(v) for v in row)
        for row in rows),name+' table shape or values differ from the plan')


def verify(directory,require_result=True):
    directory = Path(directory).absolute()
    try:
        def read(name): return json.loads((directory/name).read_text())
        required = [name for name,_ in FILES]+EVIDENCE+['authored.json','plan.json','result.json','verification.json']
        for name in required:
            path = directory/name
            thermo.check(path.is_file() and not path.is_symlink() and path.stat().st_size <= 4*1024*1024,'missing or excessive regular evidence: '+name)
        prepared = plan(read('authored.json'))
        thermo.check(prepared == read('plan.json'),'effective plan differs from authored input')
        if require_result:
            thermo.check(read('result.json').get('status') == 'succeeded' and read('result.json').get('verified') is True,'execution incomplete')
        thermo.check(read('verification.json') == {'artifacts':manifest(directory),'evidence':{n:file_digest(directory/n) for n in EVIDENCE}},'publication/native evidence digest differs')
        thermo.check(file_digest(directory/'mechanism.yaml') == prepared['mechanism']['sha256'],'retained mechanism differs from qualified source')
        built,reopened = read('built.json'),read('reopened.json')
        thermo.check(built['stage'] == 'build' and reopened['stage'] == 'reopen' and built['pid'] != reopened['pid'],'missing fresh-process native readback')
        thermo.check(built['runtime'] == reopened['runtime'] and reopened['runtime']['version'].split('.')[:2] == ['3','2'],'unsupported native runtime')
        with (directory/'results.csv').open(newline='') as stream:
            reader = csv.reader(stream)
            thermo.check(next(reader) == prepared['columns'],'table column contract differs')
            rows = [list(map(float,r)) for r in reader]
        reactor = prepared['nodes'][1]['filter'] == 'reactorHistory'
        count = len(prepared['nodes'][1]['options']['times' if reactor else 'temperatures'])
        for name,table in (('results.csv',rows),('built.json',built['rows']),('reopened.json',reopened['rows'])):
            numeric_table(table,count,len(prepared['columns']),name)
        result_summary = summary(prepared,rows,built,reopened['rates'] if reactor else None)
        for evidence in (built,reopened):
            thermo.check(evidence['plan'] == prepared and evidence['species'] == list(thermo.SPECIES) and evidence['phase'] == 'ohmech','native plan/species/phase differs')
            thermo.check(evidence['mechanismSHA256'] == prepared['mechanism']['sha256'],'native mechanism digest differs')
            if not reactor: thermo.verify_rows(prepared,evidence['rows'])
            thermo.check(all(thermo.close(a,b) for row,native in zip(rows,evidence['rows']) for a,b in zip(row,native)),'native table readback differs')
        thermo.check(same_summary(read('chemistry-summary.json'),result_summary),'summary differs from independently checked rows')
        return {'verified':True,'artifacts':len(FILES),'runtime':reopened['runtime'],'rows':len(rows),'species':len(thermo.SPECIES)}
    except (OSError,ValueError,KeyError,TypeError,AttributeError,IndexError,OverflowError,StopIteration) as error:
        fail('VERIFICATION_FAILED','missing or invalid chemistry evidence: '+str(error))


# Shared authored-input, analytic-visit and verification boundary.
from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
