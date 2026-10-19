"""Declared numeric regression, native R models and independently measured intent."""
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

from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute
from schemaxis.tabular import close, parse_csv, write_csv
from . import reference

VERSION='schemaxis.r/1'
MAX_BYTES=8*1024*1024
NUMBER={'type':'number','minimum':-1e9,'maximum':1e9}
LABEL={'type':'string','minLength':1,'maxLength':32,'required':True}
VARIABLE={'type':'object','properties':{'name':LABEL,'unit':LABEL},'required':True}
ROWS={'type':'array','items':{'type':'array','items':NUMBER,'minItems':2,'maxItems':9},'minItems':4,'maxItems':512,'required':True}
REQUIREMENT={'type':'object','properties':{
    'name':{'type':'string','minLength':1,'maxLength':64,'required':True},
    'scope':{'type':'enum','values':['training','heldout'],'required':True},
    'metric':{'type':'enum','values':['rmse','maxAbsoluteError','prediction','coefficientInterval'],'required':True},
    'term':{'type':'string','minLength':1,'maxLength':32},
    'sampleIndex':{'type':'integer','minimum':0,'maximum':511},
    'minimum':{'type':'number','minimum':-1e18,'maximum':1e18},
    'maximum':{'type':'number','minimum':-1e18,'maximum':1e18}}}
OPTIONS={'predictors':{'type':'array','items':VARIABLE,'minItems':1,'maxItems':8,'required':True},
    'response':VARIABLE,'training':ROWS,'heldout':{**ROWS,'minItems':1,'required':False},
    'intercept':{'type':'boolean','default':True},
    'inference':{'type':'object','properties':{'level':{'type':'number','minimum':0.5,'maximum':0.999,'default':0.95}}},
    'requirements':{'type':'array','items':REQUIREMENT,'minItems':1,'maxItems':32}}
DECLARATIONS={'linearRegression':{'native':'stats::lm / base::saveRDS / stats::predict / stats::summary.lm / stats::confint',
    'kinds':['table','text'],'inputs':{},'options':{key:{'value':value} for key,value in OPTIONS.items()}}}
LOSSES=['Unweighted numeric additive ordinary least squares only; no categorical, interaction, polynomial or authored formula terms',
    'Declared units are retained labels, not unit conversion or physical calibration',
    'Finite training/held-out rows only; no causal inference or future-generalisation guarantee',
    'Optional coefficient inference assumes a correct additive mean, independent homoscedastic normal errors and fixed predictors; it is not a prediction interval, model selection or multiplicity-adjusted test',
    'RDS is retained native replay evidence, not a cross-machine interchange or imported arbitrary model']


def plan(document):
    keys(document,('version','operation',*OPTIONS),'$')
    if document.get('version')!=VERSION:fail('UNSUPPORTED_VERSION','expected '+VERSION)
    if document.get('operation')!='linearRegression':fail('UNKNOWN_FILTER','select linearRegression')
    prepared=validate_arguments(OPTIONS,{key:value for key,value in document.items() if key not in ('version','operation')})
    variables=[*prepared['predictors'],prepared['response']]
    names=[value['name'] for value in variables]
    if len(set(names))!=len(names) or 'intercept' in names or any(re.fullmatch(r'[a-z][a-z0-9_]{0,31}',name) is None for name in names):
        fail('INVALID_NAME','predictor/response names must be distinct bounded lowercase identifiers','$.predictors')
    if any(any(ord(char)<32 for char in value['unit']) for value in variables):
        fail('INVALID_UNIT','unit labels must be plain text without control characters','$.predictors')
    width=len(variables)
    for scope in ('training','heldout'):
        for index,row in enumerate(prepared.get(scope,[])):
            if len(row)!=width:fail('INVALID_TABLE','each row needs predictors in declared order followed by the response',f'$.{scope}[{index}]')
    count=len(prepared['training']);coefficients=len(prepared['predictors'])+int(prepared['intercept'])
    if count<=coefficients:fail('INSUFFICIENT_DATA','training rows must exceed coefficient count','$.training')
    independent=reference.decompose(prepared['training'],prepared['intercept'])
    scales=independent['scales'][int(prepared['intercept']):]
    for scope in ('training','heldout'):
        for index,row in enumerate(prepared.get(scope,[])):
            scaled=[value/scale for value,scale in zip(row[:-1],scales)]
            if any(not math.isfinite(value) or abs(value)>1e100 for value in scaled):
                fail('INVALID_PREDICTION','scaled numeric input exceeds the representable table budget',f'$.{scope}[{index}]')
            prediction=reference.predicted(prepared,row,independent['coefficients'])
            if not math.isfinite(prediction) or abs(prediction)>1e100 or abs(row[-1]-prediction)>1e100:
                fail('INVALID_PREDICTION','projected prediction/residual exceeds the numeric table budget',f'$.{scope}[{index}]')
    if 'inference' in prepared:reference.residual_variance(prepared,independent)
    terms=(['intercept'] if prepared['intercept'] else [])+[p['name'] for p in prepared['predictors']]
    seen=set()
    for index,requirement in enumerate(prepared.get('requirements',[])):
        at=f'$.requirements[{index}]';name=requirement['name'];metric=requirement['metric']
        if name in seen or re.fullmatch(r'[a-z][a-z0-9_]{0,63}',name) is None:
            fail('INVALID_REQUIREMENT','requirement names must be unique lowercase identifiers',at+'.name')
        seen.add(name)
        if requirement['scope']=='heldout' and 'heldout' not in prepared and metric!='coefficientInterval':
            fail('INVALID_REQUIREMENT','held-out requirements need explicit held-out observed rows',at+'.scope')
        if metric!='coefficientInterval' and 'term' in requirement:
            fail('INVALID_REQUIREMENT','term applies only to coefficientInterval',at+'.term')
        if metric=='coefficientInterval':
            if 'inference' not in prepared:fail('INVALID_REQUIREMENT','coefficientInterval needs declared inference and its confidence level','$.inference')
            if requirement['scope']!='training':fail('INVALID_REQUIREMENT','coefficient intervals come from the training fit; use scope training',at+'.scope')
            if requirement.get('term') not in terms:fail('INVALID_REQUIREMENT','term must name intercept (when enabled) or a declared predictor',at+'.term')
            if 'sampleIndex' in requirement:fail('INVALID_REQUIREMENT','coefficientInterval does not select a sample',at+'.sampleIndex')
            if not any(bound in requirement for bound in ('minimum','maximum')):
                fail('INVALID_REQUIREMENT','coefficientInterval needs an inclusive lower or upper bound on the confidence limits',at)
            if requirement.get('minimum',-math.inf)>requirement.get('maximum',math.inf):
                fail('INVALID_REQUIREMENT','minimum must not exceed maximum',at)
        elif metric=='prediction':
            if 'sampleIndex' not in requirement or requirement['sampleIndex']>=len(prepared[requirement['scope']]):
                fail('INVALID_REQUIREMENT','prediction needs a valid zero-based declared sample index',at+'.sampleIndex')
            if not any(bound in requirement for bound in ('minimum','maximum')):
                fail('INVALID_REQUIREMENT','prediction needs an inclusive lower or upper bound',at)
            if requirement.get('minimum',-math.inf)>requirement.get('maximum',math.inf):
                fail('INVALID_REQUIREMENT','minimum must not exceed maximum',at)
        elif 'maximum' not in requirement or requirement['maximum']<0 or any(key in requirement for key in ('minimum','sampleIndex')):
            fail('INVALID_REQUIREMENT','error metric needs only a nonnegative maximum bound',at)
    return {'version':'schemaxis.r.plan/1','operation':'linearRegression',**prepared,
            'scales':independent['scales'],'scaledInfinityCondition':independent['scaledInfinityCondition'],
            'rank':independent['rank'],'residualDF':independent['residualDF'],'losses':LOSSES}


def schema():
    from schemaxis.schema import DRAFT,argument_schema,object_schema
    fields={'version':{'const':VERSION},'operation':{'const':'linearRegression'},
        **{key:argument_schema(value) for key,value in OPTIONS.items()}}
    for variable in (fields['predictors']['items'],fields['response']):
        variable['properties']['name']['pattern']='^[a-z][a-z0-9_]{0,31}$'
    item=fields['requirements']['items'];properties=item['properties'];properties['name']['pattern']='^[a-z][a-z0-9_]{0,63}$'
    common={key:properties[key] for key in ('name','scope')}
    error=object_schema({**common,'metric':{'enum':['rmse','maxAbsoluteError']},
        'maximum':{**properties['maximum'],'minimum':0}},['name','scope','metric','maximum'])
    prediction=object_schema({**common,'metric':{'const':'prediction'},
        **{key:properties[key] for key in ('sampleIndex','minimum','maximum')}},['name','scope','metric','sampleIndex'])
    prediction['anyOf']=[{'required':['minimum']},{'required':['maximum']}]
    interval=object_schema({'name':properties['name'],'scope':{'const':'training'},'metric':{'const':'coefficientInterval'},
        'term':{**properties['term'],'pattern':'^[a-z][a-z0-9_]{0,31}$'},**{key:properties[key] for key in ('minimum','maximum')}},['name','scope','metric','term'])
    interval['anyOf']=[{'required':['minimum']},{'required':['maximum']}]
    fields['requirements']['items']={'oneOf':[error,prediction,interval]}
    return {'$schema':DRAFT,**object_schema(fields,['version','operation','predictors','response','training'])}


def query(document):
    prepared=plan(document)
    return list(dict.fromkeys(visit['plan']['operation'] for visit in prepared['visits'])) if 'visits' in prepared else [prepared['operation']],{}


def reusableInputs(document):
    plan(document);return {}


def resources(document,execution,identity):
    if execution.get('threads',1)!=1:fail('INVALID_EXECUTION','this bounded regression uses one thread',identity)
    return {'threads':1}


def regular(directory,name,limit=MAX_BYTES):
    path=directory/name
    if path.is_symlink() or not path.is_file() or path.stat().st_size>limit:
        fail('VERIFICATION_FAILED','required bounded regular evidence is absent or excessive',name)
    return path


def payload(directory,name,limit=MAX_BYTES):
    path=regular(directory,name,limit)
    descriptor=os.open(path,os.O_RDONLY|getattr(os,'O_NONBLOCK',0)|getattr(os,'O_NOFOLLOW',0))
    with os.fdopen(descriptor,'rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size>limit:
            fail('VERIFICATION_FAILED','required bounded regular descriptor differs',name)
        data=stream.read(limit+1)
    if len(data)>limit:fail('VERIFICATION_FAILED','retained evidence byte budget exceeded',name)
    return data


def digest(directory,name):
    return hashlib.sha256(payload(directory,name)).hexdigest()


def read_table(directory,name):
    return parse_csv(payload(directory,name),location=name)


def read(directory,name):
    value=json.loads(payload(directory,name))
    if not isinstance(value,dict):fail('VERIFICATION_FAILED','expected evidence object',name)
    return value


def sources(prepared,directory):
    width=len(prepared['predictors']);scales=prepared['scales'][int(prepared['intercept']):]
    for scope in ('training','heldout'):
        if scope in prepared:
            write_csv(directory/(scope+'-input.csv'),{'columns':[f'x{i+1}' for i in range(width)]+['y'],
                'rows':[[value/scale for value,scale in zip(row[:-1],scales)]+[row[-1]] for row in prepared[scope]]})


def commands(executable,directory,prepared):
    common=[executable,'--vanilla','--default-packages=stats,utils',str(directory/'worker.R')]
    options=[str(len(prepared['predictors'])),str(int(prepared['intercept'])),str(int('heldout' in prepared)),
        repr(float(prepared['inference']['level'])) if 'inference' in prepared else 'none']
    return {stage:common+[stage,*options] for stage in ('fit','reopen')}


def stage_inputs(directory,prepared,stage):
    names=['worker.R','training-input.csv']+(['heldout-input.csv'] if 'heldout' in prepared else [])
    if stage=='reopen':names+=['model.rds']
    return [directory/name for name in names]


def launcher(directory,prepared,stage,command):
    paths=[str(path) for path in stage_inputs(directory,prepared,stage)]
    return ('import hashlib,json,os,stat\nfrom pathlib import Path\n'
        +f'paths={paths!r}\ncommand={command!r}\nbindings={{}}\n'
        +'for filename in paths:\n'
        +'    path=Path(filename)\n'
        +f'    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode) or path.stat().st_size>{MAX_BYTES}: raise ValueError("invalid bounded native input")\n'
        +'    digest=hashlib.sha256()\n'
        +'    descriptor=os.open(path,os.O_RDONLY|getattr(os,"O_NONBLOCK",0)|getattr(os,"O_NOFOLLOW",0))\n'
        +'    with os.fdopen(descriptor,"rb") as stream:\n'
        +f'        info=os.fstat(stream.fileno())\n        if not stat.S_ISREG(info.st_mode) or info.st_size>{MAX_BYTES}: raise ValueError("invalid bounded native descriptor")\n'
        +'        size=0\n'
        +'        for block in iter(lambda:stream.read(1048576),b""):\n'
        +'            size+=len(block)\n'
        +f'            if size>{MAX_BYTES}: raise ValueError("native input byte budget exceeded")\n'
        +'            digest.update(block)\n'
        +'    bindings[filename]=digest.hexdigest()\n'
        +f'Path({str(directory/(stage+"-inputs.json"))!r}).write_text(json.dumps(bindings,sort_keys=True))\n'
        +'os.execvpe(command[0],command,os.environ)\n')


def native_tables(directory,prepared,stage):
    result={scope:read_table(directory,stage+'-'+scope+'.csv') for scope in ('training','heldout') if scope in prepared}
    metadata=read_table(directory,stage+'-metadata.csv')
    if metadata!={'columns':['rank','residualDF'],'rows':[[prepared['rank'],prepared['residualDF']]]}:
        fail('VERIFICATION_FAILED','native model rank or residual degrees of freedom differs',stage)
    scaled=read_table(directory,stage+'-coefficients.csv')
    if scaled['columns']!=['coefficientIndex','scaledCoefficient'] or len(scaled['rows'])!=prepared['rank']:
        fail('VERIFICATION_FAILED','native coefficient dimensions differ',stage)
    independent=reference.decompose(prepared['training'],prepared['intercept'])
    # Response-scale roundoff bound; zero response uses the smallest float ULP,
    # not a unit-dependent fixed voltage/error floor.
    tolerance=reference.response_tolerance(prepared['training'],prepared['scaledInfinityCondition'])
    for i,(row,expected) in enumerate(zip(scaled['rows'],independent['scaledCoefficients'])):
        if row[0]!=i or not math.isclose(row[1],expected,rel_tol=1e-10,abs_tol=tolerance):
            fail('VERIFICATION_FAILED','native coefficient differs from independent Householder QR',stage)
    coefficients=[row[1]/scale for row,scale in zip(scaled['rows'],prepared['scales'])]
    for scope,table in result.items():
        columns=['sample','observed','prediction','residual']+(['fitted','fitResidual'] if scope=='training' else [])
        if table['columns']!=columns or len(table['rows'])!=len(prepared[scope]):
            fail('VERIFICATION_FAILED','native observation table dimensions differ',stage+'-'+scope)
        for i,(native,authored) in enumerate(zip(table['rows'],prepared[scope])):
            predicted=reference.predicted(prepared,authored,independent['coefficients'])
            residual=authored[-1]-predicted
            expected=[i,authored[-1],predicted,residual]+([predicted,residual] if scope=='training' else [])
            if native[0]!=i or not math.isclose(native[1],authored[-1],rel_tol=1e-14,abs_tol=128*math.ulp(abs(authored[-1]))) or not close(native[2:],expected[2:],rel=1e-10,absolute=tolerance):
                fail('VERIFICATION_FAILED','native prediction/residual differs from independent model',stage+'-'+scope)
    return coefficients,result,native_inference(directory,prepared,stage,independent,tolerance)


INFERENCE_COLUMNS=['coefficientIndex','scaledEstimate','scaledStandardError','tStatistic','pValue','scaledLower','scaledUpper']
STATISTICS_COLUMNS=['level','residualDF','criticalValue','sigma','rSquared','adjustedRSquared','fStatistic','fNumeratorDF','fDenominatorDF','fPValue']


def native_inference(directory,prepared,stage,independent,tolerance):
    """Check native summary.lm/confint values against independent QR inference."""
    if 'inference' not in prepared:return None
    table=read_table(directory,stage+'-inference.csv');statistics=read_table(directory,stage+'-statistics.csv')
    if table['columns']!=INFERENCE_COLUMNS or len(table['rows'])!=prepared['rank'] or statistics['columns']!=STATISTICS_COLUMNS or len(statistics['rows'])!=1:
        fail('VERIFICATION_FAILED','native inference table dimensions differ',stage)
    if [row[0] for row in table['rows']]!=list(range(prepared['rank'])):fail('VERIFICATION_FAILED','native inference coefficient order differs',stage)
    native={**dict(zip(STATISTICS_COLUMNS,statistics['rows'][0])),'coefficients':[dict(zip(INFERENCE_COLUMNS[1:],row[1:])) for row in table['rows']]}
    expected=reference.inference(prepared,independent)
    differing=reference.compare_inference(native,expected,tolerance)
    if differing:fail('VERIFICATION_FAILED','native '+differing+' differs from independent QR inference',stage+'-inference')
    native.update({key:expected[key] for key in ('residualDF','fNumeratorDF','fDenominatorDF')})  # exactly equal counts
    terms=(['intercept'] if prepared['intercept'] else [])+[p['name'] for p in prepared['predictors']]
    coefficients=[{'term':term,'units':unit,'estimate':item['scaledEstimate']/scale,'standardError':item['scaledStandardError']/scale,
        'tStatistic':item['tStatistic'],'pValue':item['pValue'],'lower':item['scaledLower']/scale,'upper':item['scaledUpper']/scale}
        for term,unit,item,scale in zip(terms,reference.coefficient_units(prepared),native['coefficients'],prepared['scales'])]
    return {**{key:native[key] for key in STATISTICS_COLUMNS},'coefficients':coefficients}


def inference_summary(prepared,inferred):
    intercept=prepared['intercept']
    return {'version':'schemaxis.r.inference/1','method':'Classical ordinary least-squares t and F inference: stats::summary.lm, stats::confint and stats::pf',
        'level':inferred['level'],'residualDF':inferred['residualDF'],'criticalValue':inferred['criticalValue'],
        'residualStandardError':{'value':inferred['sigma'],'units':prepared['response']['unit']},
        'rSquared':inferred['rSquared'],'adjustedRSquared':inferred['adjustedRSquared'],
        'rSquaredBasis':'centred on the mean response' if intercept else 'uncentred (about zero); not comparable with an intercept model',
        'fTest':{'statistic':inferred['fStatistic'],'numeratorDF':inferred['fNumeratorDF'],'denominatorDF':inferred['fDenominatorDF'],'pValue':inferred['fPValue'],
            'hypothesis':'all predictor coefficients are zero (intercept retained)' if intercept else 'all coefficients are zero (no intercept)'},
        'coefficients':inferred['coefficients'],
        'assumptions':['The declared additive linear mean is correct for the training rows.',
            'Errors are independent, have constant variance and are normally distributed; exact t/F levels depend on normality.',
            'Predictor values are fixed and measured without error; rows are not replicated pseudo-observations.'],
        'tolerance':{'relative':reference.INFERENCE_RELATIVE,'distributionRelative':reference.DISTRIBUTION_RELATIVE,
            'minimumResidualStandardErrorRatio':reference.VARIANCE_RATIO,'pValues':'native value within the independent image of the t/F tolerance interval'},
        'limits':'Per-coefficient two-sided tests and intervals are not adjusted for multiple comparisons, are not prediction intervals for new observations and do not establish causality or validate the model choice.'}


def summaries(prepared,coefficients,tables,inferred=None):
    names=(['intercept'] if prepared['intercept'] else [])+[p['name'] for p in prepared['predictors']]
    details={'version':'schemaxis.r.summary/1','operation':prepared['operation'],
        'predictors':prepared['predictors'],'response':prepared['response'],'intercept':prepared['intercept'],
        'coefficients':[{'term':name,'estimate':value} for name,value in zip(names,coefficients)],
        'rank':prepared['rank'],'residualDF':prepared['residualDF'],
        'scaledInfinityCondition':prepared['scaledInfinityCondition'],'maximumScaledInfinityCondition':reference.CONDITION_LIMIT,
        'metrics':{scope:reference.metrics(table['rows']) for scope,table in tables.items()},
        'verificationTolerance':{'relative':1e-10,'absoluteResponseUnits':reference.response_tolerance(prepared['training'],prepared['scaledInfinityCondition'])},'losses':LOSSES}
    if inferred is not None:details['inference']=inference_summary(prepared,inferred)
    if 'requirements' in prepared:details['acceptance']=reference.assess(prepared,tables,inferred)
    return details


def publications(prepared):
    # Opt-in inference is appended so existing artifact indices never move.
    return ([('coefficients.csv','table'),('training.csv','table')]+([('heldout.csv','table')] if 'heldout' in prepared else [])
        +[('regression-summary.json','text')]+([('inference.csv','table')] if 'inference' in prepared else []))


def inference_table(inferred):
    return {'columns':['coefficientIndex','estimate','standardError','tStatistic','pValue','lower','upper'],
        'rows':[[i,item['estimate'],item['standardError'],item['tStatistic'],item['pValue'],item['lower'],item['upper']] for i,item in enumerate(inferred['coefficients'])]}


def manifest(directory,prepared):
    return [{'file':str(directory/name),'kind':kind,'sha256':digest(directory,name)} for name,kind in publications(prepared)]


def evidence_names(prepared):
    names=['worker.R','model.rds','training-input.csv']+(['heldout-input.csv'] if 'heldout' in prepared else [])
    for stage in ('fit','reopen'):
        names += [stage+'-'+scope+'.csv' for scope in ('training','heldout') if scope in prepared]
        names += [stage+'-coefficients.csv',stage+'-metadata.csv',stage+'-runtime.txt',stage+'-launcher.py',stage+'-inputs.json',stage+'-submission.json',stage+'.stdout',stage+'.stderr']
        names += [stage+'-inference.csv',stage+'-statistics.csv'] if 'inference' in prepared else []
    return names


def run(document,directory,*,executable=None,timeout=300):
    prepared=plan(document)
    executable=executable or os.environ.get('SCHEMAXIS_R') or shutil.which('Rscript')
    if not executable or not Path(executable).is_absolute() or not os.access(executable,os.X_OK):
        fail('INTERPRETER_NOT_FOUND','provide an absolute qualified Rscript executable')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=3600:
        fail('INVALID_ARGUMENT','timeout must be in (0,3600]')
    directory=Path(directory).absolute()
    if directory.exists() or directory.is_symlink():fail('OUTPUT_EXISTS','choose a fresh execution directory',str(directory))
    try:
        directory.mkdir(parents=True)
        atomic_json(directory/'authored.json',document);atomic_json(directory/'plan.json',prepared)
        atomic_json(directory/'result.json',{'status':'incomplete','verified':False})
    except (OSError,ValueError) as error:fail('INVALID_RESOURCE','cannot create bounded execution location: '+str(error),str(directory))
    deadline=time.monotonic()+timeout
    try:
        sources(prepared,directory)
        from .worker import WORKER
        (directory/'worker.R').write_text(WORKER)
        native=commands(str(executable),directory,prepared)
        for stage in ('fit','reopen'):
            script=directory/(stage+'-launcher.py');script.write_text(launcher(directory,prepared,stage,native[stage]))
            execute([sys.executable,str(script)],directory,stage,deadline-time.monotonic(),
                {'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','LC_ALL':'C'})
        coefficients,tables,inferred=native_tables(directory,prepared,'reopen')
        write_csv(directory/'coefficients.csv',{'columns':['coefficientIndex','estimate'],
            'rows':[[i,value] for i,value in enumerate(coefficients)]})
        for scope,table in tables.items():write_csv(directory/(scope+'.csv'),{'columns':table['columns'][:4],'rows':[row[:4] for row in table['rows']]})
        atomic_json(directory/'regression-summary.json',summaries(prepared,coefficients,tables,inferred))
        if inferred is not None:write_csv(directory/'inference.csv',inference_table(inferred))
        runtime=payload(directory,'fit-runtime.txt').decode().strip()
        atomic_json(directory/'verification.json',{'artifacts':manifest(directory,prepared),'runtime':runtime,
            'evidence':{name:digest(directory,name) for name in evidence_names(prepared)}})
        result=verify(directory,require_result=False)
        if cancellation_requested():fail('RUNNER_CANCELLED','regression publication cancelled')
        if time.monotonic()>=deadline:fail('RUNNER_TIMED_OUT','regression verification exhausted total timeout')
        result.update(status='succeeded');atomic_json(directory/'result.json',result);return result
    except Exception as error:
        if not isinstance(error,SchemaxisError):
            try:fail('NATIVE_EXECUTION_FAILED',str(error),str(directory))
            except SchemaxisError as wrapped:error=wrapped
        atomic_json(directory/'result.json',{'status':'failed','verified':False,'fault':error.fault.to_dict()})
        raise error


def verify(directory,require_result=True):
    directory=Path(directory).absolute()
    try:
        prepared=plan(read(directory,'authored.json'));receipt=read(directory,'verification.json')
        if read(directory,'plan.json')!=prepared:fail('VERIFICATION_FAILED','effective plan differs from authored regression')
        if require_result:
            result=read(directory,'result.json')
            if result.get('status')!='succeeded' or result.get('verified') is not True:fail('INCOMPLETE_EXECUTION','regression did not complete')
        from .worker import WORKER
        if payload(directory,'worker.R').decode()!=WORKER:fail('VERIFICATION_FAILED','trusted native worker differs')
        for scope in ('training','heldout'):
            if scope not in prepared:continue
            scales=prepared['scales'][int(prepared['intercept']):]
            expected={'columns':[f'x{i+1}' for i in range(len(prepared['predictors']))]+['y'],
                'rows':[[value/scale for value,scale in zip(row[:-1],scales)]+[row[-1]] for row in prepared[scope]]}
            if read_table(directory,scope+'-input.csv')!=expected:fail('VERIFICATION_FAILED','captured input differs from declared numeric rows',scope)
        submissions={stage:read(directory,stage+'-submission.json') for stage in ('fit','reopen')}
        # The trusted native command is embedded literally in the generated launcher.
        import ast
        tree=ast.parse(payload(directory,'fit-launcher.py').decode())
        command=next(ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='command' for t in node.targets))
        if not isinstance(command,list) or not command or not isinstance(command[0],str) or not Path(command[0]).is_absolute():
            fail('VERIFICATION_FAILED','missing absolute Rscript command evidence')
        native=commands(command[0],directory,prepared)
        for stage,submission in submissions.items():
            script=regular(directory,stage+'-launcher.py');interpreter=submission.get('interpreter')
            interpreter=interpreter.get('executable') if isinstance(interpreter,dict) else None
            if payload(directory,stage+'-launcher.py').decode()!=launcher(directory,prepared,stage,native[stage]):fail('VERIFICATION_FAILED','native launcher differs',stage)
            if not isinstance(interpreter,str) or not Path(interpreter).is_absolute() or submission.get('nativeCommand')!=[interpreter,str(script)] or type(submission.get('exitCode'))is not int or submission['exitCode']!=0:
                fail('VERIFICATION_FAILED','native command or completion differs',stage)
            bindings={str(path):digest(directory,path.name) for path in stage_inputs(directory,prepared,stage)}
            if read(directory,stage+'-inputs.json')!=bindings:fail('VERIFICATION_FAILED','native stage consumed different input/model bytes',stage)
        coefficients,tables,inferred=native_tables(directory,prepared,'fit');reopened,reopened_tables,reinferred=native_tables(directory,prepared,'reopen')
        if not close(coefficients,reopened,rel=1e-12,absolute=1e-12) or not close(tables,reopened_tables,rel=1e-12,absolute=1e-12):
            fail('VERIFICATION_FAILED','fresh native model reopen differs')
        if not close(inferred,reinferred,rel=1e-12,absolute=1e-300):fail('VERIFICATION_FAILED','fresh native model reopen inference differs')
        details=summaries(prepared,reopened,reopened_tables,reinferred)
        if read(directory,'regression-summary.json')!=details:fail('VERIFICATION_FAILED','summary differs from independently checked native model')
        coefficient_table={'columns':['coefficientIndex','estimate'],'rows':[[i,value] for i,value in enumerate(reopened)]}
        if read_table(directory,'coefficients.csv')!=coefficient_table:fail('VERIFICATION_FAILED','published coefficients differ')
        for scope,table in reopened_tables.items():
            if read_table(directory,scope+'.csv')!={'columns':table['columns'][:4],'rows':[row[:4] for row in table['rows']]}:
                fail('VERIFICATION_FAILED','published prediction table differs',scope)
        if reinferred is not None and read_table(directory,'inference.csv')!=inference_table(reinferred):
            fail('VERIFICATION_FAILED','published inference table differs')
        runtime=payload(directory,'fit-runtime.txt').decode().strip()
        if not re.fullmatch(r'R version \d+\.\d+\.\d+[^\r\n]*',runtime) or payload(directory,'reopen-runtime.txt').decode().strip()!=runtime:
            fail('VERIFICATION_FAILED','native R runtime identity differs')
        expected={'artifacts':manifest(directory,prepared),'runtime':runtime,
            'evidence':{name:digest(directory,name) for name in evidence_names(prepared)}}
        if receipt!=expected:fail('VERIFICATION_FAILED','native/publication evidence digest differs')
        if 'acceptance' in details and not details['acceptance']['accepted']:
            fail('FIT_REQUIREMENT_NOT_MET','verified regression does not meet the named finite fit requirements','$.requirements',assessment=details['acceptance'])
        result={'verified':True,'artifacts':len(expected['artifacts']),'runtime':runtime,'rank':prepared['rank'],'metrics':details['metrics']}
        if 'inference' in details:result['inference']={'level':details['inference']['level'],'residualDF':details['inference']['residualDF']}
        if 'acceptance' in details:result['acceptance']=details['acceptance']
        return result
    except (OSError,ValueError,KeyError,TypeError,IndexError,StopIteration,SyntaxError,OverflowError) as error:
        fail('VERIFICATION_FAILED','missing or invalid regression evidence: '+str(error))


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
