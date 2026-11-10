# Copyright (C) 2026 David L F Gaden
"""Typed captured tables and closed relational intentions, never authored SQL."""
import csv
import errno
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import sys
import time

from schemaxis.artifacts import atomic_json
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute

VERSION = 'schemaxis.sqlite/1'
LIMIT = 8*1024*1024
IDENT = {'type':'string','minLength':1,'maxLength':40,'required':True}
REF = {'type':'string','minLength':3,'maxLength':81,'required':True}
COLUMN = {'type':'object','properties':{'name':IDENT,'type':{'type':'enum','values':['INTEGER','TEXT'],'required':True},'nullable':{'type':'boolean','default':False}}}
FOREIGN = {'type':'object','properties':{'column':IDENT,'table':IDENT,'target':IDENT}}
TABLE = {'type':'object','properties':{'name':IDENT,'source':{'type':'string','minLength':1,'maxLength':4096,'required':True},'columns':{'type':'array','items':COLUMN,'minItems':1,'maxItems':12,'required':True},'primaryKey':IDENT,'foreignKeys':{'type':'array','items':FOREIGN,'maxItems':4,'default':[]}}}
OPTIONS = {'tables':{'type':'array','items':TABLE,'minItems':1,'maxItems':4,'required':True},'from':IDENT,
    'join':{'type':'object','properties':{'table':IDENT,'local':IDENT,'remote':IDENT}},
    'where':{'type':'object','properties':{'column':REF,'minimum':{'type':'integer','minimum':-10**9,'maximum':10**9,'required':True}}},
    'groupBy':{'type':'array','items':REF,'minItems':1,'maxItems':3,'uniqueItems':True,'required':True},'sum':REF}
DECLARATIONS = {'summarise':{'native':'CREATE TABLE STRICT; INSERT; SELECT INNER JOIN WHERE GROUP BY COUNT SUM ORDER BY',
    'kinds':['file','text'],'inputs':{},'options':{k:{'value':v} for k,v in OPTIONS.items()}}}
LOSSES = ['Only bounded local JSON row arrays with INTEGER/TEXT cells; no floats, dates, blobs, expressions, arbitrary SQL or existing database inputs.',
    'One inner join from the base table through a declared foreign key to a unique primary key; no left join or many-to-many expansion.',
    'Filter is integer >=; grouping uses binary collation with null first; sum ignores null and is null for all-null groups; count includes every surviving row.',
    'Integers are exact in [-1000000000,1000000000]; text is printable ASCII (at most 256 characters), excluding the reserved CSV null token \\N.',
    'CSV represents null as \\N; empty strings stay empty. JSON/database preserve integer, text and null types; no units or decimal arithmetic are inferred.']


def identifier(value, at):
    if not re.fullmatch('[a-z][a-z0-9_]{0,39}',value) or value in {'rowid','oid','_rowid_'} or value.startswith('sqlite_'):
        fail('INVALID_TABLE_IDENTIFIER','use lower-case ASCII identifiers, excluding SQLite internal names',at)


def plan(document):
    keys(document,('version','operation',*OPTIONS),'$')
    if document.get('version')!=VERSION: fail('UNSUPPORTED_VERSION','expected '+VERSION,'$.version')
    if document.get('operation')!='summarise': fail('UNKNOWN_FILTER','select summarise','$.operation')
    p=validate_arguments(OPTIONS,{k:v for k,v in document.items() if k in OPTIONS})
    tables={}
    for i,t in enumerate(p['tables']):
        at=f'$.tables[{i}]';identifier(t['name'],at+'.name')
        if t['name'] in tables: fail('INVALID_TABLE_IDENTIFIER','table names must be unique',at+'.name')
        source=Path(t['source'])
        if not source.is_absolute() or source.suffix.lower()!='.json': fail('INVALID_TABLE_SOURCE','select an absolute local JSON row-array file',at+'.source')
        cols={}
        for j,c in enumerate(t['columns']):
            identifier(c['name'],at+f'.columns[{j}].name')
            if c['name'] in cols: fail('INVALID_TABLE_IDENTIFIER','column names must be unique',at+f'.columns[{j}].name')
            cols[c['name']]=c
        if t['primaryKey'] not in cols or cols[t['primaryKey']]['nullable']: fail('INVALID_TABLE_KEY','primaryKey must name a declared nonnullable column',at+'.primaryKey')
        seen=set()
        for j,fk in enumerate(t['foreignKeys']):
            loc=at+f'.foreignKeys[{j}]'
            if fk['column'] in seen: fail('INVALID_TABLE_KEY','one foreign key per local column',loc+'.column')
            seen.add(fk['column'])
            parent=tables.get(fk['table'])
            if fk['column'] not in cols or parent is None or fk['target']!=parent['primaryKey']:
                fail('INVALID_TABLE_KEY','foreign key must reference an earlier table primary key',loc)
            target=next(c for c in parent['columns'] if c['name']==fk['target'])
            if cols[fk['column']]['type']!=target['type']: fail('INVALID_TABLE_KEY','foreign key and primary key types must agree',loc+'.column')
        tables[t['name']]=t
    if p['from'] not in tables: fail('INVALID_TABLE_QUERY','from must name an imported table','$.from')
    active={p['from']}
    if 'join' in p:
        j=p['join'];base=tables[p['from']]
        if j['table']==p['from'] or not any(f=={'column':j['local'],'table':j['table'],'target':j['remote']} for f in base['foreignKeys']):
            fail('INVALID_TABLE_QUERY','join must follow a declared base-table foreign key to a primary key','$.join')
        active.add(j['table'])
    def column(ref,at):
        parts=ref.split('.')
        if len(parts)!=2 or parts[0] not in active: fail('INVALID_TABLE_QUERY','use table.column from the base or joined table',at)
        found=next((c for c in tables[parts[0]]['columns'] if c['name']==parts[1]),None)
        if found is None: fail('INVALID_TABLE_QUERY','query column is not declared',at)
        return found
    for i,g in enumerate(p['groupBy']):column(g,f'$.groupBy[{i}]')
    if column(p['sum'],'$.sum')['type']!='INTEGER': fail('INVALID_TABLE_QUERY','sum requires an INTEGER column','$.sum')
    if 'where' in p and column(p['where']['column'],'$.where.column')['type']!='INTEGER': fail('INVALID_TABLE_QUERY','minimum filter requires an INTEGER column','$.where.column')
    return {'version':'schemaxis.sqlite.plan/1','operation':'summarise',**p,'losses':LOSSES}


def schema():
    from schemaxis.schema import DRAFT,argument_schema,object_schema
    return {'$schema':DRAFT,**object_schema({'version':{'const':VERSION},'operation':{'const':'summarise'},**{k:argument_schema(v) for k,v in OPTIONS.items()}},['version','operation',*[k for k,v in OPTIONS.items() if v.get('required')]])}


def query(document):plan(document);return ['summarise'],{}
def resources(document,execution,identity):
    if execution.get('threads',1)!=1:fail('INVALID_EXECUTION','SQLite summaries are serial',identity)
    return {'threads':1}


SOURCE_REASONS = {'missing':'the file does not exist','symlink':'file symlinks are not accepted','not-regular':'a regular file is required',
    'too-large':'the file exceeds its byte budget','unreadable':'the file could not be read'}


def bounded(path,code='VERIFICATION_FAILED',limit=LIMIT,at=None,**context):
    """Read a bounded regular file; ``at`` replaces the path in the fault location and keeps it out of public text."""
    reason='unreadable'
    try:
        try:fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
        except FileNotFoundError:reason='missing';raise
        except OSError as e:
            if e.errno==errno.ELOOP:reason='symlink'
            raise
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):reason='not-regular';raise ValueError('not a regular file')
            if info.st_size>limit:reason='too-large';raise ValueError('byte budget exceeded')
        except BaseException:os.close(fd);raise
        with os.fdopen(fd,'rb') as f:data=f.read(limit+1)
        if len(data)>limit:reason='too-large';raise ValueError('byte budget exceeded')
        return data
    except (ValueError,OSError) as e:
        if at is None:fail(code,'select an intact bounded regular file: '+str(e),str(path),reason=reason,**context)
        fail(code,'select an intact bounded regular file: '+SOURCE_REASONS[reason],at,reason=reason,limit=limit,**context)


def unique_object(pairs):
    result={}
    for k,v in pairs:
        if k in result:raise ValueError('duplicate JSON key '+k)
        result[k]=v
    return result


def decode(data):
    return json.loads(data,object_pairs_hook=unique_object,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite JSON '+x)))
def read(directory,name):return decode(bounded(directory/name))
def digest(directory,name):return hashlib.sha256(bounded(directory/name)).hexdigest()


class RowFault(ValueError):
    def __init__(self,reason,message,**where):super().__init__(message);self.reason=reason;self.where=where


def rows(data,t,at):
    try:
        try:values=decode(data)
        except (ValueError,UnicodeError) as e:raise RowFault('malformed-json','not valid unique-key JSON: '+str(e))
        if not isinstance(values,list) or len(values)>2048:raise RowFault('invalid-shape','require at most 2048 JSON row objects')
        names={c['name'] for c in t['columns']};seen=set()
        for i,row in enumerate(values):
            if not isinstance(row,dict) or set(row)!=names:raise RowFault('invalid-shape',f'row {i}: exact declared columns required',row=i)
            for c in t['columns']:
                v=row[c['name']];where={'row':i,'column':c['name']}
                if v is None:
                    if not c['nullable']:raise RowFault('invalid-cell',f'row {i} {c["name"]}: null forbidden',**where)
                elif c['type']=='INTEGER':
                    if type(v) is not int or abs(v)>10**9:raise RowFault('invalid-cell',f'row {i} {c["name"]}: exact bounded integer required; booleans are not integers',**where)
                elif not isinstance(v,str) or len(v)>256 or v=='\\N' or any(ord(x)<32 or ord(x)>126 for x in v):
                    raise RowFault('invalid-cell',f'row {i} {c["name"]}: printable ASCII text excluding \\N required',**where)
            key=row[t['primaryKey']]
            if key in seen:raise RowFault('duplicate-key',f'row {i}: duplicate primary key',row=i,column=t['primaryKey'])
            seen.add(key)
        return values
    except RowFault as e:fail('INVALID_TABLE_DATA','correct typed JSON rows: '+str(e),at,table=t['name'],reason=e.reason,**e.where)


def captured(directory,p):
    result={t['name']:rows(bounded(directory/('table-'+t['name']+'.json')),t,'$.tables['+str(i)+'].source') for i,t in enumerate(p['tables'])}
    for i,t in enumerate(p['tables']):
        for j,f in enumerate(t['foreignKeys']):
            allowed={r[f['target']] for r in result[f['table']]}
            for n,r in enumerate(result[t['name']]):
                if r[f['column']] is not None and r[f['column']] not in allowed:
                    fail('INVALID_TABLE_DATA',f'row {n}: non-null foreign key has no matching parent primary key; add the parent row or correct the value',f'$.tables[{i}].foreignKeys[{j}]',
                        table=t['name'],column=f['column'],row=n,value=r[f['column']],parent=f['table'],reason='orphan-foreign-key')
    return result


def oracle(p,data):
    """Literal row-by-row semantics, deliberately independent from generated SQL."""
    combined=[]
    for base in data[p['from']]:
        left={p['from']+'.'+k:v for k,v in base.items()}
        if 'join' not in p:combined.append(left);continue
        j=p['join']
        for other in data[j['table']]:
            if base[j['local']] is not None and base[j['local']]==other[j['remote']]:
                combined.append({**left,**{j['table']+'.'+k:v for k,v in other.items()}})
    groups={}
    for row in combined:
        if 'where' in p:
            v=row[p['where']['column']]
            if v is None or v<p['where']['minimum']:continue
        key=tuple(row[g] for g in p['groupBy']);groups.setdefault(key,[]).append(row[p['sum']])
    result=[]
    for key in sorted(groups,key=lambda k:tuple((v is not None,v if v is not None else '') for v in k)):
        values=groups[key];nonnull=[v for v in values if v is not None]
        total=sum(nonnull) if nonnull else None
        if total is not None and abs(total)>2**53:fail('INVALID_TABLE_DATA','aggregate exceeds exact interchange integer budget','$.sum')
        result.append([*key,len(values),total])
    return {'columns':[*['g'+str(i) for i in range(len(p['groupBy']))],'row_count','total'],'rows':result}


def qi(value):return '"'+value.replace('"','""')+'"'
def literal(v):return 'NULL' if v is None else str(v) if type(v) is int else "'"+v.replace("'","''")+"'"
def ref(value):return '.'.join(qi(x) for x in value.split('.'))


def ddl(p):
    parts=[]
    for t in p['tables']:
        columns=[qi(c['name'])+' '+c['type']+('' if c['nullable'] else ' NOT NULL') for c in t['columns']]
        columns+=['PRIMARY KEY ('+qi(t['primaryKey'])+')']
        columns+=['FOREIGN KEY ('+qi(f['column'])+') REFERENCES '+qi(f['table'])+' ('+qi(f['target'])+')' for f in t['foreignKeys']]
        parts.append('CREATE TABLE '+qi(t['name'])+' ('+', '.join(columns)+') STRICT;')
    return '\n'.join(parts)+'\n'


def select(p):
    fields=[ref(g)+' AS '+qi('g'+str(i)) for i,g in enumerate(p['groupBy'])]
    sql='SELECT '+', '.join([*fields,'COUNT(*) AS row_count','SUM('+ref(p['sum'])+') AS total'])+' FROM '+qi(p['from'])
    if 'join' in p:
        j=p['join'];sql+=' INNER JOIN '+qi(j['table'])+' ON '+ref(p['from']+'.'+j['local'])+' = '+ref(j['table']+'.'+j['remote'])
    if 'where' in p:sql+=' WHERE '+ref(p['where']['column'])+' >= '+str(p['where']['minimum'])
    return sql+' GROUP BY '+', '.join(ref(g) for g in p['groupBy'])+' ORDER BY '+', '.join(ref(g)+' COLLATE BINARY ASC' for g in p['groupBy'])+';\n'


def import_sql(p,data):
    sql='PRAGMA trusted_schema=OFF;\nPRAGMA foreign_keys=ON;\nPRAGMA journal_mode=OFF;\nPRAGMA max_page_count=4096;\nBEGIN;\n'+ddl(p)
    for t in p['tables']:
        names=[c['name'] for c in t['columns']]
        for row in data[t['name']]:sql+='INSERT INTO '+qi(t['name'])+' ('+', '.join(map(qi,names))+') VALUES ('+', '.join(literal(row[n]) for n in names)+');\n'
    return sql+'COMMIT;\n'


def csv_bytes(result):
    f=io.StringIO(newline='');w=csv.writer(f,lineterminator='\n');w.writerow(result['columns'])
    w.writerows([['\\N' if v is None else v for v in r] for r in result['rows']]);return f.getvalue().encode()


def inspect(directory,p):
    data=captured(directory,p);expected=oracle(p,data)
    # Observe every row and schema of the independently reopened database. No
    # application-generated totals or SQL replay supplies the expected answer.
    path=directory/'summary.sqlite';bounded(path)
    uri=path.as_uri()+'?mode=ro&immutable=1'
    with sqlite3.connect(uri,uri=True) as db:
        db.execute('PRAGMA trusted_schema=OFF');db.execute('PRAGMA query_only=ON')
        if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)] or db.execute('PRAGMA foreign_key_check').fetchall():fail('VERIFICATION_FAILED','database integrity/foreign-key check failed')
        native_schema=db.execute("SELECT sql FROM sqlite_schema WHERE type='table' ORDER BY name").fetchall()
        wanted=sorted([(s[:-1],) for s in ddl(p).splitlines()])
        if sorted(native_schema)!=wanted:fail('VERIFICATION_FAILED','native typed table schema differs')
        objects=db.execute("SELECT type,name FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
        if objects!=[('table',name) for name in sorted(data)]:fail('VERIFICATION_FAILED','unexpected database object membership')
        for t in p['tables']:
            names=[c['name'] for c in t['columns']]
            observed=db.execute('SELECT '+', '.join(map(qi,names))+' FROM '+qi(t['name'])+' ORDER BY '+qi(t['primaryKey'])+' COLLATE BINARY').fetchall()
            wanted=[tuple(r[n] for n in names) for r in sorted(data[t['name']],key=lambda r:r[t['primaryKey']])]
            if observed!=wanted:fail('VERIFICATION_FAILED','native table rows differ from capture',t['name'])
    native=read(directory,'query.stdout') if bounded(directory/'query.stdout').strip() else []
    if not isinstance(native,list) or any(not isinstance(r,dict) or list(r)!=expected['columns'] for r in native):fail('VERIFICATION_FAILED','native query columns differ')
    observed=[[r[c] for c in expected['columns']] for r in native]
    if observed!=expected['rows'] or any(type(a)!=type(b) for r,s in zip(observed,expected['rows']) for a,b in zip(r,s)):
        fail('VERIFICATION_FAILED','native join/filter/group output differs from literal oracle')
    if json.dumps(read(directory,'summary.json'),sort_keys=True)!=json.dumps(expected,sort_keys=True) or bounded(directory/'summary.csv')!=csv_bytes(expected):fail('VERIFICATION_FAILED','published summary differs from native result/oracle')
    return expected


def commands(executable,directory):
    common=[executable,'-batch','-bail','-init','/dev/null','-safe']
    return {'version':[executable,'--version'],'import':[*common,str(directory/'summary.sqlite')],
        'query':[*common,'-json','-readonly',str(directory/'summary.sqlite')]}


def stage_inputs(stage,p):
    if stage=='import':return ['import.sql',*['table-'+t['name']+'.json' for t in p['tables']]]
    return ['query.sql','summary.sqlite'] if stage=='query' else []


def launcher(directory,stage,command,p):
    sql=directory/('import.sql' if stage=='import' else 'query.sql')
    return ('import hashlib,json,os,resource,stat\nfrom pathlib import Path\n'+f'command={command!r}\npaths={[str(directory/n) for n in stage_inputs(stage,p)]!r}\nbindings={{}}\n'
        +'resource.setrlimit(resource.RLIMIT_AS,(536870912,536870912))\nresource.setrlimit(resource.RLIMIT_FSIZE,(16777216,16777216))\nresource.setrlimit(resource.RLIMIT_CPU,(30,30))\n'
        +'for name in paths:\n    fd=os.open(name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_NONBLOCK",0))\n    with os.fdopen(fd,"rb") as stream:\n        info=os.fstat(stream.fileno())\n'
        +f'        if not stat.S_ISREG(info.st_mode) or info.st_size>{LIMIT}: raise ValueError("invalid native input")\n        data=stream.read({LIMIT+1})\n'
        +'    bindings[name]=hashlib.sha256(data).hexdigest()\n'
        +f'Path({str(directory/(stage+"-inputs.json"))!r}).write_text(json.dumps(bindings,sort_keys=True))\n'
        +(f'fd=os.open({str(sql)!r},os.O_RDONLY|os.O_NOFOLLOW)\nos.dup2(fd,0)\nos.close(fd)\n' if stage!='version' else '')
        +'os.execve(command[0],command,{"LANG":"C","HOME":str(Path.cwd()),"SQLITE_HISTORY":"/dev/null"})\n')


def artifacts(directory):
    return [{'file':str(directory/n),'kind':kind,'sha256':digest(directory,n)} for n,kind in [('summary.sqlite','file'),('summary.json','text'),('summary.csv','file'),('schema.sql','text')]]
def evidence_names(p):
    return {'authored.json','plan.json','captures.json','import.sql','query.sql',*['table-'+t['name']+'.json' for t in p['tables']],*[s+x for s in ('version','import','query') for x in ('-launcher.py','-inputs.json','-submission.json','.stdout','.stderr')]}


def source_bytes(t,i):return bounded(t['source'],'INVALID_TABLE_SOURCE',1024*1024,at=f'$.tables[{i}].source',table=t['name'])


def reusableInputs(document):
    p=plan(document)
    return {t['name']:hashlib.sha256(source_bytes(t,i)).hexdigest() for i,t in enumerate(p['tables'])}


def run(document,directory,*,executable=None,timeout=300):
    p=plan(document);executable=executable or os.environ.get('SCHEMAXIS_SQLITE') or shutil.which('sqlite3')
    if not executable or not Path(executable).is_absolute() or not os.access(executable,os.X_OK):fail('INTERPRETER_NOT_FOUND','configure an absolute sqlite3 CLI executable')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=3600:fail('INVALID_ARGUMENT','timeout must be finite in (0,3600]')
    directory=Path(directory).absolute()
    if directory.exists() or directory.is_symlink():fail('OUTPUT_EXISTS','select a fresh output directory',str(directory))
    directory.mkdir(parents=True);atomic_json(directory/'authored.json',document);atomic_json(directory/'plan.json',p);atomic_json(directory/'result.json',{'status':'incomplete','verified':False});deadline=time.monotonic()+timeout
    try:
        captures={}
        for i,t in enumerate(p['tables']):
            data=source_bytes(t,i);rows(data,t,f'$.tables[{i}].source');name='table-'+t['name']+'.json';(directory/name).write_bytes(data)
            captures[t['name']]={'source':t['source'],'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
        atomic_json(directory/'captures.json',captures);data=captured(directory,p);expected=oracle(p,data)
        (directory/'schema.sql').write_text(ddl(p));(directory/'import.sql').write_text(import_sql(p,data));(directory/'query.sql').write_text('PRAGMA trusted_schema=OFF;\n'+select(p))
        for stage,command in commands(str(executable),directory).items():
            path=directory/(stage+'-launcher.py');path.write_text(launcher(directory,stage,command,p))
            execute([sys.executable,str(path)],directory,stage,deadline-time.monotonic(),{'LANG':'C','HOME':str(directory),'SQLITE_HISTORY':'/dev/null'})
            if stage=='version':
                runtime=bounded(directory/'version.stdout').decode().strip()
                if not re.fullmatch(r'3\.54\.1 [0-9 :\-]+ [0-9a-f]{64} \(64-bit\)',runtime):fail('UNSUPPORTED_NATIVE_VERSION','select SQLite 3.54.1 x64 CLI; requalify other releases before importing data')
        native=read(directory,'query.stdout') if bounded(directory/'query.stdout').strip() else []
        output={'columns':expected['columns'],'rows':[[r[c] for c in expected['columns']] for r in native]}
        atomic_json(directory/'summary.json',output);(directory/'summary.csv').write_bytes(csv_bytes(output));inspect(directory,p)
        runtime=bounded(directory/'version.stdout').decode().strip()
        if not re.match(r'^3\.54\.1 ',runtime):fail('UNSUPPORTED_NATIVE_VERSION','this route is qualified for SQLite 3.54.1; requalify other releases')
        atomic_json(directory/'verification.json',{'executable':str(executable),'runtime':runtime,'artifacts':artifacts(directory),'evidence':{n:digest(directory,n) for n in evidence_names(p)}})
        result=verify(directory,require_result=False)
        if cancellation_requested():fail('RUNNER_CANCELLED','SQLite publication cancelled')
        if time.monotonic()>=deadline:fail('RUNNER_TIMED_OUT','SQLite exhausted total deadline')
        result['status']='succeeded';atomic_json(directory/'result.json',result);return result
    except Exception as e:
        if not isinstance(e,SchemaxisError):
            try:fail('NATIVE_EXECUTION_FAILED',str(e))
            except SchemaxisError as wrapped:e=wrapped
        atomic_json(directory/'result.json',{'status':'failed','verified':False,'fault':e.fault.to_dict()});raise e


def verify(directory,require_result=True):
    directory=Path(directory).absolute()
    try:
        p=plan(read(directory,'authored.json'))
        if require_result:
            status=read(directory,'result.json')
            if status.get('status')!='succeeded':
                # A recorded failed or interrupted run is honest evidence of incompleteness, not tampering.
                recorded=status.get('fault');recorded=recorded.get('code') if isinstance(recorded,dict) else None
                fail('INCOMPLETE_EXECUTION','SQLite did not complete; correct the cause, then run again in a fresh output directory',str(directory/'result.json'),status=status.get('status'),faultCode=recorded)
        receipt=read(directory,'verification.json')
        if read(directory,'plan.json')!=p:fail('VERIFICATION_FAILED','effective relational plan differs')
        captures={t['name']:{'source':t['source'],'sha256':digest(directory,'table-'+t['name']+'.json'),'bytes':len(bounded(directory/('table-'+t['name']+'.json')))} for t in p['tables']}
        if read(directory,'captures.json')!=captures:fail('VERIFICATION_FAILED','source capture bindings differ')
        data=captured(directory,p)
        if bounded(directory/'schema.sql').decode()!=ddl(p) or bounded(directory/'import.sql').decode()!=import_sql(p,data) or bounded(directory/'query.sql').decode()!='PRAGMA trusted_schema=OFF;\n'+select(p):fail('VERIFICATION_FAILED','trusted schema/import/query differs')
        executable=receipt['executable']
        if not isinstance(executable,str) or not Path(executable).is_absolute():fail('VERIFICATION_FAILED','native executable identity must be absolute')
        for stage,command in commands(executable,directory).items():
            submission=read(directory,stage+'-submission.json');interpreter=submission.get('interpreter',{}).get('executable');path=directory/(stage+'-launcher.py')
            if not isinstance(interpreter,str) or not Path(interpreter).is_absolute() or submission.get('nativeCommand')!=[interpreter,str(path)] or type(submission.get('exitCode')) is not int or submission['exitCode']!=0:fail('VERIFICATION_FAILED','native command/completion differs',stage)
            if bounded(path).decode()!=launcher(directory,stage,command,p):fail('VERIFICATION_FAILED','trusted native launcher differs',stage)
            if read(directory,stage+'-inputs.json')!={str(directory/n):digest(directory,n) for n in stage_inputs(stage,p)}:fail('VERIFICATION_FAILED','native inputs differ',stage)
        runtime=bounded(directory/'version.stdout').decode().strip()
        if not re.fullmatch(r'3\.54\.1 [0-9 :\-]+ [0-9a-f]{64} \(64-bit\)',runtime) or receipt['runtime']!=runtime:fail('VERIFICATION_FAILED','native SQLite runtime identity differs')
        expected=inspect(directory,p)
        if receipt['artifacts']!=artifacts(directory):fail('VERIFICATION_FAILED','publication membership/digests differ')
        if set(receipt['evidence'])!=evidence_names(p):fail('VERIFICATION_FAILED','evidence membership differs')
        for n in evidence_names(p):
            if digest(directory,n)!=receipt['evidence'][n]:fail('VERIFICATION_FAILED','retained native evidence differs',n)
        return {'verified':True,'artifacts':4,'runtime':runtime,'groups':len(expected['rows'])}
    except (OSError,ValueError,KeyError,TypeError,IndexError,AttributeError,sqlite3.Error) as e:fail('VERIFICATION_FAILED','invalid retained relational evidence: '+str(e))

from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
