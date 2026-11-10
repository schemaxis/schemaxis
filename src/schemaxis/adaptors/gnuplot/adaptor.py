# Copyright (C) 2026 David L F Gaden
"""Declared numeric plots; captured CSV and trusted Gnuplot commands only."""
import csv
import hashlib
import io
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
from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute

VERSION = 'schemaxis.gnuplot/1'
LIMIT = 8 * 1024 * 1024
TEXT = {'type':'string','minLength':1,'maxLength':80,'required':True}
NUMBER = {'type':'number','minimum':-1e100,'maximum':1e100}
AXIS = {'type':'object','properties':{
    'label':TEXT,'unit':TEXT,
    'range':{'type':'array','items':NUMBER,'minItems':2,'maxItems':2,'required':True},
    'scale':{'type':'enum','values':['linear','log10'],'default':'linear'}}}
COLUMN = {'type':'object','properties':{'name':TEXT,'unit':TEXT}}
SERIES = {'type':'object','properties':{'label':TEXT,'x':TEXT,'y':TEXT,
    'error':{**TEXT,'required':False},
    'bounds':{'type':'object','required':False,'properties':{'lower':TEXT,'upper':TEXT}},
    'colour':{'type':'enum','values':['red','blue','green','purple'],'default':'red'}}}
OPTIONS = {'title':TEXT,'source':{**TEXT,'maxLength':4096},
    'columns':{'type':'array','items':COLUMN,'minItems':2,'maxItems':12,'required':True},
    'series':{'type':'array','items':SERIES,'minItems':1,'maxItems':4,'required':True},
    'xAxis':{**AXIS,'required':True},'yAxis':{**AXIS,'required':True},
    'width':{'type':'integer','minimum':640,'maximum':1600,'default':800},
    'height':{'type':'integer','minimum':480,'maximum':1200,'default':600}}
DECLARATIONS = {'plot':{'native':'plot using x:y[:dy] with linespoints/yerrorlines, or x:lower:upper with filledcurves plus x:y with linespoints; set xrange/yrange/logscale; set style fill transparent solid 0.2 noborder; svg/png terminals',
    'kinds':['image','text','file'],'inputs':{},'options':{k:{'value':v} for k,v in OPTIONS.items()}}}
BAND_LOSS='A bounds series draws a piecewise-linear shaded envelope (fixed 20 percent opacity) through ASSERTED lower and upper columns around the central curve; it computes no quantile, distribution, confidence level, simultaneous coverage or model validity, and interpolation between rows is display only. One linear-axis envelope per plot, each row at least 24 pixels tall.'
COLOURS = {'red':'#d62728','blue':'#1f77b4','green':'#2ca02c','purple':'#9467bd'}
LOSSES = ['Only numeric rectangular CSV, 2–2048 rows, 2–12 named columns and 1–4 series; no missing values, dates or expressions.',
    'Each column declares a unit; axis units must match mapped columns. No conversion or physical dimensional inference.',
    'Symmetric absolute y uncertainty only; linear or base-10 log axes, explicit ranges include all samples/error endpoints.',
    'Fixed plot margins, typography, connected samples and solid circular markers; no fits, smoothing, 3D, animation or arbitrary commands.',
    'SVG geometry and PNG series pixels are independently checked; typography, complete raster equivalence and accessibility are not certified.']


def label(value, at):
    # Closed ASCII alphabet also excludes Gnuplot backticks, quoting, enhanced text,
    # control characters and printf placeholders, even when a terminal changes.
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 ._()+/\-]*',value) or value != value.strip():
        fail('INVALID_PLOT_LABEL','use ASCII letters/numbers, spaces and ._()+/-; begin with a letter/number',at)


def plan(document):
    keys(document,('version','operation',*OPTIONS),'$')
    if document.get('version')!=VERSION: fail('UNSUPPORTED_VERSION','expected '+VERSION)
    if document.get('operation')!='plot': fail('UNKNOWN_FILTER','select plot')
    p=validate_arguments(OPTIONS,{k:v for k,v in document.items() if k in OPTIONS})
    label(p['title'],'$.title')
    source=Path(p['source'])
    if not source.is_absolute() or source.suffix.lower()!='.csv': fail('INVALID_PLOT_SOURCE','select an absolute regular local CSV path','$.source')
    units={}
    for i,column in enumerate(p['columns']):
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,39}',column['name']) or column['name'] in units:
            fail('INVALID_PLOT_COLUMNS','column names must be distinct ASCII identifiers of at most 40 characters',f'$.columns[{i}].name')
        label(column['unit'],f'$.columns[{i}].unit');units[column['name']]=column['unit']
    for key in ('xAxis','yAxis'):
        axis=p[key];label(axis['label'],'$.'+key+'.label');label(axis['unit'],'$.'+key+'.unit')
        lo,hi=axis['range']
        if lo>=hi or hi-lo<max(abs(lo),abs(hi),1e-100)*1e-10 or axis['scale']=='log10' and lo<=0:
            fail('INVALID_PLOT_RANGE','use increasing, numerically separated finite ranges; log10 bounds must be positive','$.'+key+'.range')
    labels=set();colours=set()
    for i,s in enumerate(p['series']):
        at=f'$.series[{i}]';label(s['label'],at+'.label')
        if s['label'] in labels or s['colour'] in colours: fail('INVALID_PLOT_SERIES','series labels and colours must be distinct',at)
        labels.add(s['label']);colours.add(s['colour'])
        for role in ('x','y','error'):
            if role not in s: continue
            if s[role] not in units: fail('INVALID_PLOT_COLUMNS','map each series role to a declared column',at+'.'+role)
            axis=p['xAxis' if role=='x' else 'yAxis']
            if units[s[role]]!=axis['unit']: fail('PLOT_UNIT_MISMATCH','mapped column unit must equal its axis unit; convert data explicitly',at+'.'+role)
        if 'bounds' in s:
            b=s['bounds']
            if 'error' in s: fail('INVALID_PLOT_BOUNDS','a series is either a symmetric error or an asserted lower/upper envelope, not both',at+'.bounds')
            if len(p['series'])!=1: fail('PLOT_BOUNDS_UNSUPPORTED','an asserted envelope must be the only series of its plot; overlapping envelopes cannot be verified',at+'.bounds')
            for key in ('xAxis','yAxis'):
                if p[key]['scale']!='linear': fail('PLOT_BOUNDS_UNSUPPORTED','an asserted envelope supports linear axes only',f'$.{key}.scale')
            if len({s['y'],b['lower'],b['upper']})!=3: fail('INVALID_PLOT_BOUNDS','y, lower and upper must be three distinct declared columns',at+'.bounds')
            for role in ('lower','upper'):
                if b[role] not in units: fail('INVALID_PLOT_COLUMNS','map each bound to a declared column',f'{at}.bounds.{role}')
                if units[b[role]]!=p['yAxis']['unit']: fail('PLOT_UNIT_MISMATCH','bound column unit must equal the y-axis unit; convert data explicitly',f'{at}.bounds.{role}')
    extra=[BAND_LOSS] if any('bounds' in s for s in p['series']) else []
    return {'version':'schemaxis.gnuplot.plan/1','operation':'plot',**p,'losses':LOSSES+extra}


def schema():
    from schemaxis.schema import DRAFT,argument_schema,object_schema
    return {'$schema':DRAFT,**object_schema({'version':{'const':VERSION},'operation':{'const':'plot'},
        **{k:argument_schema(v) for k,v in OPTIONS.items()}},['version','operation',*[k for k,v in OPTIONS.items() if v.get('required')]])}


def query(document): plan(document);return ['plot'],{}


def resources(document,execution,identity):
    if execution.get('threads',1)!=1: fail('INVALID_EXECUTION','plotting supports one serial thread',identity)
    return {'threads':1}


def bounded(path,code='VERIFICATION_FAILED',limit=LIMIT):
    try:
        fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
        with os.fdopen(fd,'rb') as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size>limit: raise ValueError('not a bounded regular file')
            data=stream.read(limit+1)
        if len(data)>limit: raise ValueError('file byte budget exceeded')
        return data
    except (OSError,ValueError) as error: fail(code,'select an intact regular file within the byte budget: '+str(error),str(path))


def table(data,p):
    try:
        rows=list(csv.reader(io.StringIO(data.decode('ascii')),strict=True))
        names=[c['name'] for c in p['columns']]
        if not rows or rows[0]!=names or not 2<=len(rows)-1<=2048: raise ValueError('header must exactly match declared column order; require 2–2048 data rows')
        values=[]
        for row in rows[1:]:
            if len(row)!=len(names) or any(not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]{1,3})?',v) for v in row):
                raise ValueError('rectangular finite numeric cells required, without whitespace or missing values')
            numbers=list(map(float,row))
            if any(not math.isfinite(v) or abs(v)>1e100 for v in numbers): raise ValueError('numeric magnitude exceeds 1e100')
            values.append(dict(zip(names,numbers)))
        for i,s in enumerate(p['series']):
            last=None
            for j,row in enumerate(values):
                x,y=row[s['x']],row[s['y']];dy=row[s['error']] if 'error' in s else 0
                if dy<0: fail('INVALID_PLOT_DATA','absolute symmetric y uncertainty cannot be negative',f'$.series[{i}].error row {j+2}')
                if last is not None and x<=last: fail('INVALID_PLOT_DATA','x samples must increase strictly in each series',f'$.series[{i}].x row {j+2}')
                last=x
                for axis,points in ((p['xAxis'],[x]),(p['yAxis'],[y-dy,y+dy])):
                    if axis['scale']=='log10' and any(v<=0 for v in points): fail('INVALID_LOG_DATA','all log samples and uncertainty endpoints must be positive',f'$.series[{i}] row {j+2}')
                    if any(v<axis['range'][0] or v>axis['range'][1] for v in points): fail('PLOT_DATA_OUTSIDE_RANGE','explicit ranges must contain every sample and uncertainty endpoint',f'$.series[{i}] row {j+2}')
            if 'bounds' in s: band(i,s,p,values)
        return values
    except (ValueError,UnicodeError,csv.Error,OverflowError) as error: fail('INVALID_PLOT_DATA','use a bounded numeric CSV: '+str(error),'$.source')


def band(i,s,p,values):
    """Every asserted bound is checked exactly; nothing is clipped, sorted or imputed."""
    lo,hi=s['bounds']['lower'],s['bounds']['upper'];at=f'$.series[{i}]'
    for j,row in enumerate(values):
        l,c,u=row[lo],row[s['y']],row[hi]
        if not l<=c<=u: fail('INVALID_PLOT_BOUNDS','require lower <= representative <= upper in every row',f'{at}.bounds row {j+2}')
        if l>=u: fail('INVALID_PLOT_BOUNDS','require lower < upper in every row; use a point series for a zero-width interval',f'{at}.bounds row {j+2}')
        if any(v<p['yAxis']['range'][0] or v>p['yAxis']['range'][1] for v in (l,u)): fail('PLOT_DATA_OUTSIDE_RANGE','explicit y range must contain every lower and upper bound',f'{at}.bounds row {j+2}')
    from .inspection import band_samples
    try: band_samples(p,s,values)
    except ValueError as error: fail('PLOT_BAND_UNVERIFIABLE',str(error),f'{at}.bounds')


def reusableInputs(document):
    p=plan(document);data=bounded(p['source'],'INVALID_PLOT_SOURCE',1024*1024);table(data,p)
    return {'csv':hashlib.sha256(data).hexdigest()}


def script(p):
    lines=['# Trusted generated script; edits require a new declared Schemaxis run.','reset session',
        'set encoding utf8','set datafile separator comma','set lmargin at screen 0.15',
        'set rmargin at screen 0.95','set bmargin at screen 0.2','set tmargin at screen 0.9',
        'set key outside bottom center horizontal','set border linewidth 1','set bars 1',
        "set format x '%g'","set format y '%g'",
        "set title '"+p['title']+"' noenhanced"]
    for key,native in [('xAxis','x'),('yAxis','y')]:
        a=p[key];lines += [f'set {native}range [{a["range"][0]:.17g}:{a["range"][1]:.17g}]',f"set {native}label '{a['label']} ({a['unit']})' noenhanced"]
        if a['scale']=='log10': lines.append(f'set logscale {native} 10')
    names=[c['name'] for c in p['columns']];parts=[]
    for s in p['series']:
        if 'bounds' in s:
            index=lambda k:str(names.index(k)+1)
            parts.append(f"'captured.csv' every ::1 using {index(s['x'])}:{index(s['bounds']['lower'])}:{index(s['bounds']['upper'])} with filledcurves lc rgb '{COLOURS[s['colour']]}' title '{s['label']} range'")
            parts.append(f"'captured.csv' every ::1 using {index(s['x'])}:{index(s['y'])} with linespoints lw 2 pt 7 ps 0.7 lc rgb '{COLOURS[s['colour']]}' title '{s['label']}'")
            continue
        columns=':'.join(str(names.index(s[k])+1) for k in ('x','y','error') if k in s)
        style='yerrorlines' if 'error' in s else 'linespoints'
        parts.append(f"'captured.csv' every ::1 using {columns} with {style} lw 2 pt 7 ps 0.7 lc rgb '{COLOURS[s['colour']]}' title '{s['label']}'")
    if any('bounds' in s for s in p['series']): lines.append('set style fill transparent solid 0.2 noborder')
    lines += [f'set terminal svg size {p["width"]},{p["height"]} noenhanced',"set output 'plot.svg'",'plot '+', '.join(parts),
        f'set terminal png truecolor size {p["width"]},{p["height"]} noenhanced',"set output 'plot.png'",'replot','unset output']
    return '\n'.join(lines)+'\n'


def producing_directory(directory):
    # An export's origin is only a location hint: every retained byte is still read
    # from the selected directory and every recorded path must match exactly.
    from schemaxis.run_paths import recorded_directory
    return recorded_directory(directory) or directory


def moved(message,location,observed=None):
    raise SchemaxisError(Fault('VERIFICATION_FAILED',message,location,'pipeline',observed=observed or {},
        recovery='Verify the run in its original directory, or copy it with schemaxis export so '
                 'publication-metadata.json records its origin; do not move files by hand. '
                 'If retained bytes were edited, restore the intact evidence or render a fresh run.'))


def read(directory,name): return json.loads(bounded(directory/name))
def digest(directory,name): return hashlib.sha256(bounded(directory/name)).hexdigest()
def commands(executable): return {'version':[executable,'-d','--version'],'render':[executable,'-d','plot.gp']}
def stage_inputs(stage): return ['captured.csv','plot.gp'] if stage=='render' else []


def launcher(directory,stage,command):
    return ('import hashlib,json,os,resource,stat\nfrom pathlib import Path\n'
        +f'command={command!r}\npaths={[str(directory/n) for n in stage_inputs(stage)]!r}\nbindings={{}}\n'
        +'resource.setrlimit(resource.RLIMIT_AS,(536870912,536870912))\nresource.setrlimit(resource.RLIMIT_FSIZE,(16777216,16777216))\nresource.setrlimit(resource.RLIMIT_CPU,(60,60))\n'
        +'for name in paths:\n    fd=os.open(name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_NONBLOCK",0))\n    with os.fdopen(fd,"rb") as stream:\n        info=os.fstat(stream.fileno())\n'
        +f'        if not stat.S_ISREG(info.st_mode) or info.st_size>{LIMIT}: raise ValueError("invalid native input")\n        data=stream.read({LIMIT+1})\n'
        +'    bindings[name]=hashlib.sha256(data).hexdigest()\n'
        +f'Path({str(directory/(stage+"-inputs.json"))!r}).write_text(json.dumps(bindings,sort_keys=True))\n'
        +'os.execvpe(command[0],command,os.environ)\n')


def artifacts(directory,recorded=None):
    # Bytes always come from `directory`; receipts name the producing location.
    return [{'file':str((recorded or directory)/n),'kind':kind,'sha256':digest(directory,n)} for n,kind in
        [('plot.svg','image'),('plot.png','image'),('plot.gp','text'),('captured.csv','file'),('plot-summary.json','text')]]


def inspect(directory,p):
    from .inspection import inspect_plot
    values=table(bounded(directory/'captured.csv',limit=1024*1024),p)
    return inspect_plot(bounded(directory/'plot.svg'),bounded(directory/'plot.png'),p,values)


def evidence_names():
    return {'authored.json','plan.json','captures.json','captured.csv','plot.gp',*[s+x for s in ('version','render') for x in ('-launcher.py','-inputs.json','-submission.json','.stdout','.stderr')]}


def run(document,directory,*,executable=None,timeout=300):
    p=plan(document);executable=executable or os.environ.get('SCHEMAXIS_GNUPLOT') or shutil.which('gnuplot')
    if not executable or not Path(executable).is_absolute() or not os.access(executable,os.X_OK): fail('INTERPRETER_NOT_FOUND','configure an absolute Gnuplot executable with svg and png terminals')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=3600: fail('INVALID_ARGUMENT','timeout must be finite in (0,3600]')
    directory=Path(directory).absolute()
    if directory.exists() or directory.is_symlink(): fail('OUTPUT_EXISTS','select a fresh output directory',str(directory))
    directory.mkdir(parents=True);atomic_json(directory/'authored.json',document);atomic_json(directory/'plan.json',p)
    atomic_json(directory/'result.json',{'status':'incomplete','verified':False});deadline=time.monotonic()+timeout
    try:
        data=bounded(p['source'],'INVALID_PLOT_SOURCE',1024*1024);table(data,p)
        (directory/'captured.csv').write_bytes(data);atomic_json(directory/'captures.json',{'source':p['source'],'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)})
        (directory/'plot.gp').write_text(script(p))
        for stage,command in commands(str(executable)).items():
            path=directory/(stage+'-launcher.py');path.write_text(launcher(directory,stage,command))
            execute([sys.executable,str(path)],directory,stage,deadline-time.monotonic(),{'LANG':'C.UTF-8','GNUPLOT_LIB':str(directory),'GNUPLOT_PS_DIR':str(directory)})
        atomic_json(directory/'plot-summary.json',inspect(directory,p))
        runtime=bounded(directory/'version.stdout').decode().strip()
        atomic_json(directory/'verification.json',{'executable':str(executable),'runtime':runtime,'artifacts':artifacts(directory),'evidence':{n:digest(directory,n) for n in evidence_names()}})
        result=verify(directory,require_result=False)
        if cancellation_requested(): fail('RUNNER_CANCELLED','plot publication cancelled')
        if time.monotonic()>=deadline: fail('RUNNER_TIMED_OUT','plot exhausted its total deadline')
        result['status']='succeeded';atomic_json(directory/'result.json',result);return result
    except Exception as error:
        if not isinstance(error,SchemaxisError):
            try: fail('NATIVE_EXECUTION_FAILED',str(error))
            except SchemaxisError as wrapped: error=wrapped
        atomic_json(directory/'result.json',{'status':'failed','verified':False,'fault':error.fault.to_dict()});raise error


def verify(directory,require_result=True):
    directory=Path(directory).absolute();origin=producing_directory(directory)
    try:
        p=plan(read(directory,'authored.json'));receipt=read(directory,'verification.json')
        if read(directory,'plan.json')!=p: fail('VERIFICATION_FAILED','effective plot plan differs')
        if require_result and read(directory,'result.json').get('status')!='succeeded': fail('INCOMPLETE_EXECUTION','plot did not complete')
        data=bounded(directory/'captured.csv',limit=1024*1024)
        if read(directory,'captures.json')!={'source':p['source'],'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}: fail('VERIFICATION_FAILED','CSV source/capture binding differs')
        if bounded(directory/'plot.gp').decode()!=script(p): fail('VERIFICATION_FAILED','trusted plot script differs')
        executable=receipt['executable']
        if not isinstance(executable,str) or not Path(executable).is_absolute(): fail('VERIFICATION_FAILED','native executable identity must be absolute')
        for stage,command in commands(executable).items():
            submission=read(directory,stage+'-submission.json');interpreter=submission.get('interpreter',{}).get('executable');path=directory/(stage+'-launcher.py')
            if not isinstance(interpreter,str) or not Path(interpreter).is_absolute() or type(submission.get('exitCode')) is not int or submission['exitCode']!=0: fail('VERIFICATION_FAILED','native command/completion differs',stage)
            if submission.get('nativeCommand')!=[interpreter,str(origin/path.name)]: moved('native command/completion differs',stage)
            if bounded(path).decode()!=launcher(origin,stage,command): moved('trusted native launcher differs',stage)
            if read(directory,stage+'-inputs.json')!={str(origin/n):digest(directory,n) for n in stage_inputs(stage)}: moved('native plot input binding differs',stage)
        runtime=bounded(directory/'version.stdout').decode().strip()
        if not re.fullmatch(r'gnuplot [0-9]+\.[0-9]+ patchlevel [0-9]+',runtime) or receipt['runtime']!=runtime: fail('VERIFICATION_FAILED','Gnuplot runtime identity differs')
        summary=inspect(directory,p)
        if read(directory,'plot-summary.json')!=summary: fail('VERIFICATION_FAILED','plot summary differs')
        if receipt['artifacts']!=artifacts(directory,origin): moved('plot publication membership/digest differs','verification.json')
        if set(receipt['evidence'])!=evidence_names(): fail('VERIFICATION_FAILED','native evidence membership differs')
        for n in evidence_names():
            if digest(directory,n)!=receipt['evidence'][n]: fail('VERIFICATION_FAILED','retained native evidence differs',n)
        return {'verified':True,'artifacts':5,'runtime':runtime,'rows':summary['rows'],'series':summary['series']}
    except (OSError,ValueError,KeyError,TypeError,IndexError,AttributeError) as error: fail('VERIFICATION_FAILED','invalid retained plot evidence: '+str(error))


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
