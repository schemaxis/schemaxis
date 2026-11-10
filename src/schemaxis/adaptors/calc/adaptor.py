# Copyright (C) 2026 David L F Gaden
"""Native Calc round-trips with independently checked data, formulas and caches."""
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import hashlib
import time
from zipfile import BadZipFile
from xml.etree.ElementTree import ParseError
from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute
from schemaxis.dispatch import cancellation_requested
from schemaxis.tabular import validate, read_csv, write_csv, close, parse_csv, MAX_BYTES
from .workbook import write_ods, verify_workbook
from . import requirements, table as typed, typed_table, typed_workbook

# Typed labelled tables: explicit column kinds, one reserved null token, no coercion.
TYPED_CELL={'type':'union','options':[{'type':'enum','values':[None]},
                                      {'type':'number','minimum':-1e100,'maximum':1e100},
                                      {'type':'string','maxLength':typed_table.MAX_TEXT}]}
TYPED_COLUMNS={'type':'array','minItems':1,'maxItems':typed_table.MAX_COLUMNS,'required':True,'items':{'type':'object','properties':{
    'name':{'type':'string','minLength':1,'maxLength':128,'required':True},
    'kind':{'type':'enum','values':list(typed_table.KINDS),'required':True},
    'nullable':{'type':'boolean','default':False}}}}
NULL_TOKEN={'type':'string','minLength':1,'maxLength':16,'default':typed_table.NULL_TOKEN}
TYPED_OPS=('fromTypedRows','readTypedCSV')
CSV_OPS=('readCSV','readTypedCSV')

OPTIONS={
 'fromRows':{'columns':{'type':'array','items':{'type':'string','minLength':1,'maxLength':128},'minItems':1,'maxItems':64,'required':True},
             'rows':{'type':'array','items':{'type':'array','items':{'type':'number','minimum':-1e100,'maximum':1e100},'minItems':1,'maxItems':64},'minItems':2,'maxItems':10000,'required':True}},
 'readCSV':{'file':{'type':'string','minLength':1,'maxLength':4096,'required':True}},
 'fromTypedRows':{'columns':TYPED_COLUMNS,'nullToken':NULL_TOKEN,
                  'rows':{'type':'array','items':{'type':'array','items':TYPED_CELL,'minItems':1,'maxItems':typed_table.MAX_COLUMNS},
                          'minItems':1,'maxItems':10000,'required':True}},
 'readTypedCSV':{'file':{'type':'string','minLength':1,'maxLength':4096,'required':True},'columns':TYPED_COLUMNS,'nullToken':NULL_TOKEN}}
DECLARATIONS={op:{'native':'LibreOffice Calc','kinds':['spreadsheet'],'options':{k:{'value':v} for k,v in opts.items()},'inputs':{}} for op,opts in OPTIONS.items()}


def plan(document):
    keys(document,('version','nodes','requirements'),'$')
    if document.get('version')!='schemaxis.calc/1':fail('UNSUPPORTED_VERSION','expected schemaxis.calc/1')
    nodes=document.get('nodes')
    if not isinstance(nodes,list) or len(nodes)!=1:fail('INVALID_DOCUMENT','provide one table per workbook')
    node=nodes[0];keys(node,('id','filter','options'),'$.nodes[0]')
    identity=node.get('id');op=node.get('filter')
    if not isinstance(identity,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',identity):fail('INVALID_NAME','use a bounded ASCII node identifier')
    if not isinstance(op,str) or op not in OPTIONS:fail('UNKNOWN_FILTER','unknown Calc table source')
    options=validate_arguments(OPTIONS[op],node.get('options',{}),location=identity)
    if op=='fromRows':typed.check_labels(options['columns']);validate(options['columns'],options['rows'],minimum=2)
    elif op=='fromTypedRows':typed_table.validate(options['columns'],options['rows'],options['nullToken'])
    elif '\x00' in options['file'] or not Path(options['file']).is_absolute():fail('INVALID_RESOURCE','CSV input must be absolute without NUL')
    elif op=='readTypedCSV':
        typed_table.check_columns(options['columns'],typed_table.check_token(options['nullToken']))
    return {'version':'schemaxis.calc.plan/1','nodes':[{'id':identity,'filter':op,'options':options}],
            'sheets':['Data','Summary'],'expectedPublications':3,
            'requirements':requirements.prepare(document.get('requirements',[]),8 if op in TYPED_OPS else 7)}


def schema():
    from schemaxis.schema import DRAFT,object_schema,argument_schema
    variants=[]
    for op,options in OPTIONS.items():
        variants.append(object_schema({'id':{'type':'string','pattern':'^[A-Za-z][A-Za-z0-9_]{0,63}$'},'filter':{'const':op},
          'options':object_schema({k:argument_schema(v) for k,v in options.items()},[k for k,v in options.items() if v.get('required')])},['id','filter','options']))
    return {'$schema':DRAFT,**object_schema({'version':{'const':'schemaxis.calc/1'},'nodes':{'type':'array','minItems':1,'maxItems':1,'items':{'oneOf':variants}},
                                         'requirements':requirements.schema()},['version','nodes'])}


def reusableInputs(document):
    node=plan(document)['nodes'][0]
    return {node['options']['file']:hashlib.sha256(source_bytes(node['options']['file'])).hexdigest()} if node['filter'] in CSV_OPS else {}


def source_bytes(filename,limit=None):
    limit=MAX_BYTES if limit is None else limit
    try:
        if not stat.S_ISREG(Path(filename).stat().st_mode):fail('INVALID_RESOURCE','CSV source must be a regular file',filename)
        descriptor=os.open(filename,os.O_RDONLY|getattr(os,'O_NONBLOCK',0))
        with os.fdopen(descriptor,'rb') as stream:
            status=os.fstat(stream.fileno())
            if not stat.S_ISREG(status.st_mode):fail('INVALID_RESOURCE','CSV source must be a regular file',filename)
            if status.st_size>limit:fail('RESOURCE_LIMIT','file exceeds the bounded byte limit',filename,maximumBytes=limit)
            payload=stream.read(limit+1)
        if len(payload)>limit:fail('RESOURCE_LIMIT','file exceeds the bounded byte limit',filename,maximumBytes=limit)
        return payload
    except (OSError,ValueError) as error:fail('RESOURCE_NOT_FOUND',str(error),filename)


def parse_source_csv(payload,location='$'):
    return typed.parse_source_csv(payload,minimum=2,location=location)


def table_for(prepared,directory):
    node=prepared['nodes'][0]
    if node['filter']=='readTypedCSV':
        options=node['options'];return typed_table.parse_csv(source_bytes(str(directory/'source.csv')),options['columns'],options['nullToken'],'source.csv')
    if node['filter']=='fromTypedRows':
        options=node['options'];return typed_table.validate(options['columns'],options['rows'],options['nullToken'])
    return parse_csv(source_bytes(str(directory/'source.csv')),minimum=2) if node['filter']=='readCSV' else validate(node['options']['columns'],node['options']['rows'],minimum=2)


def manifest(directory,null_token=None):
    records=[{'file':str(directory/name),'kind':kind,'sha256':file_digest(directory/name)} for name,kind in
             [('analysis.xlsx','spreadsheet'),('analysis.ods','spreadsheet'),('data.csv','table')]]
    if null_token is not None:  # typed handoff: declare the format, token and losses beside the publication
        records[2].update(identity={'kind':'table','format':typed_table.CSV_FORMAT,'nullToken':null_token},losses=typed_table.LOSSES,
                          verificationScope='Header, text/number/null cells and exact values regenerated from the retained input; not a general CSV validator.')
    return records


def run(document,directory,*,executable=None,timeout=300):
    prepared=plan(document)
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=3600:fail('INVALID_TIMEOUT','timeout must be within 0 to 3600 seconds')
    executable=executable or os.environ.get('SCHEMAXIS_CALC') or shutil.which('soffice')
    if not executable or not Path(executable).is_file():fail('INTERPRETER_NOT_FOUND','configure LibreOffice soffice or pass --calc')
    directory=Path(directory).absolute()
    if directory.exists():fail('OUTPUT_EXISTS','choose a fresh output directory',str(directory))
    directory.mkdir(parents=True);deadline=time.monotonic()+timeout
    atomic_json(directory/'authored.json',document);atomic_json(directory/'plan.json',prepared)
    atomic_json(directory/'result.json',{'status':'incomplete','verified':False})
    try:
        node=prepared['nodes'][0];provenance={};is_typed=node['filter'] in TYPED_OPS
        if node['filter'] in CSV_OPS:
            source=Path(node['options']['file']);payload=source_bytes(str(source))
            if is_typed:typed_table.parse_csv(payload,node['options']['columns'],node['options']['nullToken'],str(source))
            else:parse_source_csv(payload,str(source))
            (directory/'source.csv').write_bytes(payload)
            provenance={'file':str(source),'sha256':hashlib.sha256(payload).hexdigest()}
        atomic_json(directory/'source.json',provenance)
        table=table_for(prepared,directory)
        if is_typed:(directory/'data.csv').write_bytes(typed_table.csv_bytes(table))
        else:write_csv(directory/'data.csv',table)
        write,check=(typed_workbook.write_ods,typed_workbook.verify_workbook) if is_typed else (write_ods,verify_workbook)
        (directory/'input').mkdir();(directory/'xlsx').mkdir();(directory/'ods').mkdir()
        write(directory/'input/analysis.ods',table)
        executable=str(Path(executable).absolute())
        execute([executable,'--version'],directory,'version',deadline-time.monotonic())
        runtime=(directory/'version.stdout').read_text().strip()
        if not re.fullmatch(r'LibreOffice(?:Dev)? \d+\.\d+\.\d+[^\n]*',runtime):fail('UNSUPPORTED_RUNTIME','native executable did not identify as LibreOffice')
        atomic_json(directory/'runtime.json',{'runtime':runtime})
        for extension,source in [('xlsx',directory/'input/analysis.ods'),('ods',directory/'xlsx/analysis.xlsx')]:
            profile=(directory/('profile-'+extension)).as_uri()
            execute([executable,'-env:UserInstallation='+profile,'--headless','--nologo','--nodefault','--nofirststartwizard',
                     '--convert-to',extension,'--outdir',str(directory/extension),str(source)],directory,extension,deadline-time.monotonic(),{'SAL_USE_VCLPLUGIN':'svp'})
            produced=directory/extension/('analysis.'+extension)
            check(produced,table)
            shutil.copyfile(produced,directory/('analysis.'+extension))
        result=verify(directory,require_result=False)
        if time.monotonic()>=deadline:fail('RUNNER_TIMED_OUT','Calc final verification exceeded the shared elapsed deadline')
        if cancellation_requested():fail('RUNNER_CANCELLED','Calc publication cancelled')
        result['status']='succeeded'
        atomic_json(directory/'result.json',result);return result
    except Exception as error:
        if not isinstance(error,SchemaxisError):
            try:fail('NATIVE_EXECUTION_FAILED',str(error),str(directory))
            except SchemaxisError as wrapped:error=wrapped
        atomic_json(directory/'result.json',{'status':'failed','verified':False,'fault':error.fault.to_dict()})
        raise error


def verify(directory,require_result=True):
    directory=Path(directory).absolute()
    def require(condition,message):
        if not condition:fail('VERIFICATION_FAILED',message,str(directory))
    try:
        prepared=plan(json.loads((directory/'authored.json').read_text()))
        require(json.loads((directory/'plan.json').read_text())==prepared,'plan differs from authored workbook')
        if require_result:require(json.loads((directory/'result.json').read_text()).get('verified') is True,'workbook did not complete')
        source=json.loads((directory/'source.json').read_text());node=prepared['nodes'][0];is_typed=node['filter'] in TYPED_OPS
        if node['filter'] in CSV_OPS:
            path=directory/'source.csv'
            require(not path.is_symlink() and source=={'file':node['options']['file'],'sha256':hashlib.sha256(source_bytes(str(path))).hexdigest()},'captured CSV differs')
        else:require(source=={},'unexpected source provenance')
        table=table_for(prepared,directory)
        for name in ('analysis.xlsx','analysis.ods','data.csv'):
            path=directory/name
            require(not path.is_symlink() and stat.S_ISREG(path.stat().st_mode),'publication must be a regular non-symlink file')
        if is_typed:
            try:published=typed_table.parse_csv(source_bytes(str(directory/'data.csv')),node['options']['columns'],node['options']['nullToken'],'data.csv')
            except SchemaxisError as error:fail('VERIFICATION_FAILED','published typed CSV is not valid under the declared columns: '+error.fault.message,str(directory))
            require(published==table,'published typed CSV differs')
            check=typed_workbook.verify_workbook
        else:
            require(close(parse_csv(source_bytes(str(directory/'data.csv')),minimum=2),table),'published CSV differs')
            check=verify_workbook
        observations={extension:check(directory/('analysis.'+extension),table,full=True) for extension in ('xlsx','ods')}
        if is_typed:
            summary_path=directory/'typed-summary.json';summary=typed_table.summary(table)
            if require_result:
                require(not summary_path.is_symlink(),'typed summary is a symlink')
                require(typed_table.summary_matches(json.loads(source_bytes(str(summary_path),limit=16*1024*1024)),json.loads(json.dumps(summary))),'typed summary differs from the verified table')
            else:atomic_json(summary_path,summary)
        requirement_report=requirements.report(prepared['requirements'],observations,8 if is_typed else 7)
        if prepared['requirements']:
            if require_result:
                report_path=directory/'requirements.json'
                require(not report_path.is_symlink(),'requirement evidence is a symlink')
                require(json.loads(source_bytes(str(report_path),limit=1024*1024))==requirement_report,'Calc requirement observations differ')
            else:atomic_json(directory/'requirements.json',requirement_report)
            requirements.enforce(requirement_report,str(directory/'requirements.json'))
        runtime=json.loads((directory/'runtime.json').read_text())['runtime']
        require(isinstance(runtime,str) and re.fullmatch(r'LibreOffice(?:Dev)? \d+\.\d+\.\d+[^\n]*',runtime) is not None,'native version is missing')
        records={'artifacts':manifest(directory,node['options']['nullToken'] if is_typed else None)}
        if is_typed:records['typedSummarySHA256']=file_digest(directory/'typed-summary.json')
        if prepared['requirements']:records.update({'requirementsSHA256':file_digest(directory/'requirements.json'),'requirementsPassed':True})
        if require_result:require(json.loads((directory/'verification.json').read_text())==records,'publication membership or digest differs')
        else:atomic_json(directory/'verification.json',records)
        return {'verified':True,'artifacts':3,'runtime':runtime,'rows':len(table['rows']),'columns':len(table['columns'])}
    except SchemaxisError:raise
    except (OSError,ValueError,TypeError,KeyError,IndexError,AttributeError,BadZipFile,ParseError) as error:
        fail('VERIFICATION_FAILED','missing or malformed workbook evidence: '+str(error),str(directory))


# Shared authored-input, analytic-visit and verification boundary.
from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
