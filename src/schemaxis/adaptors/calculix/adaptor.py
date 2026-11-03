# Copyright (C) 2026 David L F Gaden
"""Intent-to-mesh elastic cantilevers; no authored decks or native commands."""
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
from schemaxis.errors import fail,keys
from schemaxis.native_command import execute
from schemaxis.tabular import parse_csv,write_csv
from . import beam
from .faults import fault

VERSION = 'schemaxis.calculix/1'
NUMBER = {'type':'number','required':True}
OPTIONS = {
    'beam':{'type':'object','required':True,'properties':{
        'length_m':{**NUMBER,'minimum':.001,'maximum':10},
        'width_m':{**NUMBER,'minimum':.00001,'maximum':1},
        'height_m':{**NUMBER,'minimum':.00001,'maximum':1}}},
    'material':{'type':'object','required':True,'properties':{
        'youngsModulus_Pa':{**NUMBER,'minimum':1e6,'maximum':1e12},
        'poissonRatio':{**NUMBER,'minimum':0,'maximum':.35}}},
    'load':{'type':'object','required':True,'properties':{
        'tipForceZ_N':{**NUMBER,'minimum':-1e8,'maximum':1e8}}},
    'mesh':{'type':'object','default':{'lengthCells':12,'sectionCells':2},'properties':{
        'lengthCells':{'type':'integer','minimum':12,'maximum':24,'default':12},
        'sectionCells':{'type':'integer','minimum':2,'maximum':3,'default':2}}},
    'requirements':{'type':'array','maxItems':16,'default':[],'items':{'type':'object','properties':{
        'name':{'type':'string','minLength':1,'maxLength':64,'required':True},
        'quantity':{'type':'enum','values':['absTipAreaMeanUz_m','maxInteriorSampleNormalStress_Pa'],'required':True},
        'maximum':{**NUMBER,'minimum':0,'maximum':1e12}}}}
}
DECLARATIONS = {'cantileverBeam':{'native':'CalculiX C3D20R linear static','inputs':{},'kinds':['table','text'],
    'options':{key:{'value':value} for key,value in OPTIONS.items()}}}
FILES = [('beam.inp','text'),('interior-stress.csv','table'),('beam-assessment.json','text')]
STAGES = ('coarse','axial','fine','reopened')
MAX_BYTES = 16*1024*1024
HEADER = ['element','integrationPoint','x_m','y_m','z_m','sxx_Pa','syy_Pa','szz_Pa','sxy_Pa','sxz_Pa','syz_Pa']
LOSSES = ['Linear isotropic static rectangular cantilever only; no plasticity, buckling, dynamics, contact, thermal or general FEA claim.',
          'Interior stress samples cover x/L in [0.3, 0.7] at native Gauss points; no root/surface peak stress, yield or fatigue certification.',
          'Euler-Bernoulli comparison has fixed tolerances for the declared slender/small-deformation domain; tested corners do not prove its whole continuous domain.',
          'The generated editable deck is retained and reopened; arbitrary imported CalculiX decks are unsupported.']
# CalculiX 2.23's public -v prints a version then exits 201. The trusted driver
# normalises only that exact documented-observed response, within the shared
# process-tree deadline; authored input cannot influence the script or arguments.
VERSION_DRIVER = "import subprocess,sys\nr=subprocess.run([sys.argv[1],'-v'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)\nsys.stdout.buffer.write(r.stdout)\nsys.stderr.buffer.write(r.stderr)\nsys.exit(0 if r.returncode==201 and r.stdout.strip()==b'This is Version 2.23' else 1)\n"
SOLVE_DRIVER = "import hashlib,os,stat,sys\nfd=os.open('beam.inp',os.O_RDONLY|getattr(os,'O_NONBLOCK',0))\nwith os.fdopen(fd,'rb') as f:\n info=os.fstat(f.fileno())\n if not stat.S_ISREG(info.st_mode) or info.st_size>16777216: raise SystemExit('invalid bounded deck')\n data=f.read(16777217)\nif len(data)>16777216 or hashlib.sha256(data).hexdigest()!=sys.argv[2]: raise SystemExit('deck differs from trusted binding')\nos.execvpe(sys.argv[1],[sys.argv[1],'-i','beam'],os.environ)\n"


def plan(document):
    keys(document,('version','operation',*OPTIONS),'$')
    if document.get('version') != VERSION: fail('UNSUPPORTED_VERSION','expected '+VERSION)
    if document.get('operation') != 'cantileverBeam': fail('UNKNOWN_FILTER','select cantileverBeam')
    options = validate_arguments(OPTIONS,{k:v for k,v in document.items() if k not in ('version','operation')})
    L,b,h = (options['beam'][k] for k in ('length_m','width_m','height_m'))
    E = options['material']['youngsModulus_Pa']; F = options['load']['tipForceZ_N']
    slenderness = L/max(b,h); aspect = b/h
    if not 20 <= slenderness <= 40 or not .5 <= aspect <= 2:
        fault('INVALID_BEAM','require length/max(section) in [20, 40] and width/height in [0.5, 2]','$.beam',slenderness=slenderness,sectionAspect=aspect)
    if abs(F) < .01: fault('INVALID_BEAM','absolute tip force must be at least 0.01 N','$.load.tipForceZ_N')
    inertia = b*h**3/12; tip = F*L**3/(3*E*inertia); root_stress = abs(F)*L*(h/2)/inertia
    if abs(tip)/L > .01 or root_stress/E > .001:
        fault('INVALID_BEAM','linear slice requires |theory tip|/length<=0.01 and engineering root stress/E<=0.001','$.load',tipFraction=abs(tip)/L,strainScale=root_stress/E)
    mesh = options['mesh']; cell_aspect = (L/mesh['lengthCells'])/min(b/mesh['sectionCells'],h/mesh['sectionCells'])
    if cell_aspect > 10: fault('INVALID_BEAM','axial cell length must not exceed 10 times the smallest transverse cell','$.mesh',cellAspect=cell_aspect)
    names = set()
    for i,entry in enumerate(options['requirements']):
        if not re.fullmatch('[a-z][a-z0-9_]{0,63}',entry['name']) or entry['name'] in names:
            fault('INVALID_REQUIREMENT','use unique lowercase requirement names',f'$.requirements[{i}].name')
        names.add(entry['name'])
    return {'version':'schemaxis.calculix.plan/1','operation':'cantileverBeam',**options,
            'theory':{'secondMoment_m4':inertia,'tipDeflection_m':tip,'engineeringRootStress_Pa':root_stress},
            'slenderness':slenderness,'sectionAspect':aspect,'tolerances':beam.TOLERANCES,'losses':LOSSES}


def schema():
    from schemaxis.schema import DRAFT,object_schema,argument_schema
    fields = {'version':{'const':VERSION},'operation':{'const':'cantileverBeam'},
              **{key:argument_schema(value) for key,value in OPTIONS.items()}}
    fields['requirements']['items']['properties']['name']['pattern'] = '^[a-z][a-z0-9_]{0,63}$'
    return {'$schema':DRAFT,**object_schema(fields,['version','operation','beam','material','load'])}


def query(document):
    prepared = plan(document)
    return list(dict.fromkeys(v['plan']['operation'] for v in prepared['visits'])) if 'visits' in prepared else [prepared['operation']],{}


def reusableInputs(document):
    plan(document); return {}


def resources(document,spec,identity):
    if spec.get('threads',1) != 1: fail('INVALID_EXECUTION','bounded beam solves use one thread',identity)
    return {'threads':1}


def bounded(path):
    path = Path(path)
    if path.is_symlink(): fault('VERIFICATION_FAILED','evidence must be a bounded regular file',str(path))
    fd = os.open(path,os.O_RDONLY|getattr(os,'O_NONBLOCK',0))
    with os.fdopen(fd,'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
            fault('VERIFICATION_FAILED','evidence must be a bounded regular file',str(path))
        data = stream.read(MAX_BYTES+1)
        if len(data)>MAX_BYTES: fault('VERIFICATION_FAILED','evidence exceeds byte budget',str(path))
        return data


def read_json(path):
    return json.loads(bounded(path))


def assessment(prepared,native):
    fine = native['fine']; requirements = []
    quantities = {'absTipAreaMeanUz_m':abs(fine['tipAreaMeanDisplacement_m'][2]),
                  'maxInteriorSampleNormalStress_Pa':fine['maxInteriorSampleNormalStress_Pa']}
    for entry in prepared['requirements']:
        measured = quantities[entry['quantity']]; margin = entry['maximum']-measured
        requirements.append({**entry,'observed':measured,'margin':margin,'accepted':margin>=0,
            'nextAction':'Accept this measured requirement.' if margin>=0 else 'Increase stiffness/section or reduce force, or revise the serviceability bound; rerun a fresh attempt.'})
    return {'version':'schemaxis.calculix.assessment/1','accepted':all(e['accepted'] for e in requirements),
            'units':{'length':'m','force':'N','stress':'Pa','moment':'N m'},'theory':prepared['theory'],
            'native':native,'requirements':requirements,'losses':LOSSES}


def checked(directory,prepared):
    if bounded(directory/'beam.inp') != beam.deck(prepared,'fine'):
        fault('VERIFICATION_FAILED','retained editable deck differs from authored beam intent')
    runtime = bounded(directory/'version.stdout').decode('ascii').strip()
    if runtime != 'This is Version 2.23': fault('UNSUPPORTED_RUNTIME','target stable CalculiX 2.23',observed=runtime)
    if bounded(directory/'version.stderr').strip(): fault('VERIFICATION_FAILED','native version probe emitted errors')
    native = {}; rows = None
    for stage in STAGES:
        target = directory/stage
        if target.is_symlink() or not target.is_dir(): fault('VERIFICATION_FAILED','native stage directory differs',stage)
        if bounded(target/'beam.inp') != beam.deck(prepared,stage): fault('VERIFICATION_FAILED','native stage deck differs from intended mesh',stage)
        if b'Job finished' not in bounded(target/'solve.stdout') or bounded(target/'solve.stderr').strip():
            fault('VERIFICATION_FAILED','solver completion or stderr differs',stage)
        if not re.fullmatch(r'SUMMARY OF JOB INFORMATION\s+STEP\s+INC\s+ATT\s+ITRS\s+TOT TIME\s+STEP TIME\s+INC TIME\s+1\s+1\s+1\s+1\s+0\.100000E\+01\s+0\.100000E\+01\s+0\.100000E\+01\s*',bounded(target/'beam.sta').decode('ascii')):
            fault('VERIFICATION_FAILED','expected one converged linear static increment',stage)
        frd = bounded(target/'beam.frd')
        if not re.search(rb'^    1UVERSION\s+Version 2\.23\s*$',frd,re.M): fault('UNSUPPORTED_RUNTIME','native result version differs',stage)
        native[stage],samples = beam.assess(prepared,stage,bounded(target/'beam.dat').decode('ascii'))
        if stage == 'fine': rows = samples
    coarse = native['coarse']['tipAreaMeanDisplacement_m'][2]; axial = native['axial']['tipAreaMeanDisplacement_m'][2]; fine = native['fine']['tipAreaMeanDisplacement_m'][2]
    scale = abs(prepared['theory']['tipDeflection_m'])
    convergence = {'axialRelativeChange':abs(axial-coarse)/scale,'transverseRelativeChange':abs(fine-axial)/scale}
    if convergence['axialRelativeChange'] > .01 or convergence['transverseRelativeChange'] > .01:
        fault('NUMERICAL_ACCEPTANCE_FAILED','separate axial and transverse mesh refinement must each change tip deflection by<=1% of beam theory',observed=convergence)
    if native['fine'] != native['reopened'] or bounded(directory/'fine/beam.dat') != bounded(directory/'reopened/beam.dat'):
        fault('VERIFICATION_FAILED','fresh readback of the exact editable fine deck differs')
    native['convergence'] = convergence
    return native,rows,assessment(prepared,native),runtime


def receipt(directory,prepared):
    native,rows,summary,runtime = checked(directory,prepared)
    if read_json(directory/'beam-assessment.json') != summary: fault('VERIFICATION_FAILED','published beam assessment differs')
    table = parse_csv(bounded(directory/'interior-stress.csv'))
    if table['columns'] != HEADER or table['rows'] != rows: fault('VERIFICATION_FAILED','published interior stress samples differ from checked native values')
    evidence = ['authored.json','plan.json','version.stdout','version.stderr','version-submission.json']
    evidence += [stage+'/'+name for stage in STAGES for name in ['beam.inp','beam.dat','beam.frd','beam.sta','solve.stdout','solve.stderr','solve-submission.json']]
    return {'artifacts':[{'file':str(directory/name),'kind':kind,'sha256':hashlib.sha256(bounded(directory/name)).hexdigest()} for name,kind in FILES],
            'evidence':{name:hashlib.sha256(bounded(directory/name)).hexdigest() for name in evidence},
            'native':native,'assessment':summary,'runtime':runtime,'losses':LOSSES}


def command(executable,stage,prepared=None):
    return [sys.executable,'-c',VERSION_DRIVER,executable] if stage == 'version' else [sys.executable,'-c',SOLVE_DRIVER,executable,hashlib.sha256(beam.deck(prepared,stage)).hexdigest()]


def checked_submission(directory,stage,native_command):
    submission = read_json(directory/(stage+'-submission.json'))
    source = 'import os\n'+f'os.chdir({str(directory)!r})\n'+f'command = {list(map(str,native_command))!r}\n'+'os.execvpe(command[0], command, os.environ)\n'
    script = directory/'.dispatch'/stage/('replay-'+hashlib.sha256(source.encode()).hexdigest()[:16]+'.py')
    if not isinstance(submission,dict) or submission.get('nativeCommand') != native_command or type(submission.get('exitCode')) is not int or submission['exitCode'] != 0:
        fault('VERIFICATION_FAILED','native submission recipe or exit status differs',stage)
    if submission.get('interpreter') != {'kind':'native','executable':sys.executable} or submission.get('scriptPath') != str(script) or submission.get('command') != [sys.executable,str(script)] or bounded(script) != source.encode():
        fault('VERIFICATION_FAILED','trusted replay source or command binding differs',stage)
    if submission.get('stdout') != bounded(directory/(stage+'.stdout')).decode() or submission.get('stderr') != bounded(directory/(stage+'.stderr')).decode():
        fault('VERIFICATION_FAILED','native submission log bindings differ',stage)
    seconds = submission.get('seconds')
    if type(seconds) not in (int,float) or not math.isfinite(seconds) or seconds<0:
        fault('VERIFICATION_FAILED','native duration is malformed',stage)


def run(document,directory,*,executable=None,timeout=300):
    prepared = plan(document)
    if executable is None: executable = os.environ.get('CALCULIX_EXECUTABLE') or shutil.which('ccx')
    try: usable = isinstance(executable,(str,os.PathLike)) and Path(executable).is_absolute() and Path(executable).is_file() and os.access(executable,os.X_OK)
    except (ValueError,OSError): usable = False
    if not usable:
        fault('INTERPRETER_NOT_FOUND','provide an absolute usable CalculiX 2.23 executable')
    executable = os.fspath(executable)
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        fail('INVALID_ARGUMENT','timeout must be in (0, 3600]')
    try: directory = Path(directory).absolute()
    except (TypeError,ValueError,OSError): fail('INVALID_ARGUMENT','output directory must be a usable filesystem path')
    if directory.exists() or directory.is_symlink(): fail('OUTPUT_EXISTS','choose a fresh output directory',str(directory))
    try:
        directory.mkdir(parents=True)
        atomic_json(directory/'authored.json',document);atomic_json(directory/'plan.json',prepared)
        atomic_json(directory/'result.json',{'status':'incomplete','verified':False})
    except (OSError,ValueError) as error: fault('OUTPUT_WRITE_FAILED','cannot create retained attempt: '+str(error),str(directory))
    deadline = time.monotonic()+timeout
    try:
        execute(command(executable,'version'),directory,'version',deadline-time.monotonic())
        (directory/'beam.inp').write_bytes(beam.deck(prepared,'fine'))
        for stage in STAGES:
            target = directory/stage;target.mkdir()
            # Fresh readback is bound to the retained editable publication,
            # checked before launching its independent native process.
            data = bounded(directory/'beam.inp') if stage == 'reopened' else beam.deck(prepared,stage)
            if data != beam.deck(prepared,stage): fault('VERIFICATION_FAILED','editable deck changed before fresh native readback',stage)
            (target/'beam.inp').write_bytes(data)
            execute(command(executable,stage,prepared),target,'solve',deadline-time.monotonic(),
                    environment={'OMP_NUM_THREADS':'1','CCX_NPROC_RESULTS':'1','CCX_NPROC_EQUATION_SOLVER':'1'})
        native,rows,summary,runtime = checked(directory,prepared)
        atomic_json(directory/'beam-assessment.json',summary);write_csv(directory/'interior-stress.csv',{'columns':HEADER,'rows':rows})
        atomic_json(directory/'verification.json',receipt(directory,prepared))
        verify(directory,require_result=False)
        if not summary['accepted']: fault('PERFORMANCE_NOT_MET','declared beam serviceability requirements were not met','$.requirements',requirements=summary['requirements'])
        if cancellation_requested(): fail('RUNNER_CANCELLED','beam calculation cancelled')
        if time.monotonic()>deadline: fail('RUNNER_TIMED_OUT','beam calculation exhausted total timeout')
        result = {'status':'succeeded','verified':True,'artifacts':len(FILES)}
        atomic_json(directory/'result.json',result);return result
    except Exception as error:
        if not isinstance(error,SchemaxisError):
            try: fault('NATIVE_EXECUTION_FAILED',str(error),str(directory))
            except SchemaxisError as converted: error = converted
        atomic_json(directory/'result.json',{'status':'failed','verified':False,'fault':error.fault.to_dict()})
        raise error


def verify(directory,require_result=True):
    directory = Path(directory).absolute()
    try:
        result = read_json(directory/'result.json')
        if not isinstance(result,dict): fault('VERIFICATION_FAILED','result must be an object')
        if require_result and (result.get('status') != 'succeeded' or result.get('verified') is not True):
            fail('INCOMPLETE_EXECUTION','beam did not complete with accepted requirements')
        prepared = plan(read_json(directory/'authored.json'))
        if read_json(directory/'plan.json') != prepared: fault('VERIFICATION_FAILED','saved beam plan differs')
        submission = read_json(directory/'version-submission.json'); native_command = submission.get('nativeCommand')
        if not isinstance(native_command,list) or len(native_command)!=4 or not isinstance(native_command[-1],str) or not Path(native_command[-1]).is_absolute():
            fault('VERIFICATION_FAILED','native executable identity differs')
        executable = native_command[-1]
        checked_submission(directory,'version',command(executable,'version'))
        for stage in STAGES:
            checked_submission(directory/stage,'solve',command(executable,stage,prepared))
        expected = receipt(directory,prepared)
        if read_json(directory/'verification.json') != expected: fault('VERIFICATION_FAILED','saved native/publication evidence differs')
        if not expected['assessment']['accepted']: fault('PERFORMANCE_NOT_MET','beam requirements are not accepted','$.requirements',requirements=expected['assessment']['requirements'])
        return {'verified':True,'artifacts':len(FILES),'runtime':expected['runtime'],'native':expected['native'],'assessment':expected['assessment']}
    except (OSError,ValueError,KeyError,TypeError,IndexError,AttributeError) as error:
        fault('VERIFICATION_FAILED','missing or malformed beam evidence: '+str(error))


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
