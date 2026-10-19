#!/usr/bin/env python3
"""Qualify exact native SQLite tables, relational semantics and workflow reuse."""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import threading
import time
from unittest.mock import patch

from schemaxis.adaptor_conformance import qualify, register
from schemaxis.adaptor_delivery import case_document, route_materials
from schemaxis.adaptors.sqlite import adaptor as a
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation
from schemaxis import workflow

ROOT=Path(__file__).resolve().parents[1]


def refused(action,code='VERIFICATION_FAILED'):
    try:action()
    except SchemaxisError as e:
        assert e.fault.code==code,e.fault.to_dict();return e.fault.to_dict()
    raise AssertionError('hostile input/evidence was accepted')


def refresh(directory):
    receipt=a.read(directory,'verification.json');receipt['artifacts']=a.artifacts(directory)
    receipt['evidence']={n:a.digest(directory,n) for n in receipt['evidence']}
    atomic_json(directory/'verification.json',receipt)
    from schemaxis.publication_metadata import finalise
    finalise(directory)


def hostile(directory):
    saved={p:p.read_bytes() for p in directory.rglob('*') if p.is_file()};report={}
    def restore():
        for p,b in saved.items():p.write_bytes(b)
    mutations=[('rawQueryRows','query.stdout',lambda b:b.replace(b'300',b'301')),
        ('forgedTypedSummary','summary.json',lambda b:b.replace(b'300',b'301')),
        ('boolCountInSummary','summary.json',lambda b:b.replace(b'"",\n      1,',b'"",\n      true,')),
        ('csvNullConflation','summary.csv',lambda b:b.replace(b'\\N',b'')),
        ('schemaKeyChange','schema.sql',lambda b:b.replace(b'PRIMARY KEY ("id")',b'PRIMARY KEY ("region")',1)),
        ('authoredSQLInjection','import.sql',lambda b:b+b'\nDROP TABLE sales;\n'),
        ('queryFilterTamper','query.sql',lambda b:b.replace(b'>= 1',b'>= 6')),
        ('nativeLauncherCommand','query-launcher.py',lambda b:b.replace(b"'-readonly'",b"'-readwrite'"))]
    for name,target,mutation in mutations:
        try:
            p=directory/target;b=p.read_bytes();changed=mutation(b);assert changed!=b,name;p.write_bytes(changed);refresh(directory)
            report[name]=refused(lambda:a.verify(directory))['code']
        finally:restore()
    try:
        # Refresh raw hashes AND the readonly CLI input hash. The independent
        # every-row comparison must still catch a coherent mutated database.
        with sqlite3.connect(directory/'summary.sqlite') as db:db.execute('UPDATE sales SET amount=101 WHERE id=1')
        bindings=a.read(directory,'query-inputs.json');bindings[str(directory/'summary.sqlite')]=a.digest(directory,'summary.sqlite');atomic_json(directory/'query-inputs.json',bindings);refresh(directory)
        report['databaseChangedWithRefreshedBindings']=refused(lambda:a.verify(directory))['code']
    finally:restore()
    try:
        # Capture/import remain internally coherent, but native rows are stale.
        p=a.plan(a.read(directory,'authored.json'));capture=directory/'table-sales.json';values=json.loads(capture.read_text());values[0]['amount']=999;capture.write_text(json.dumps(values))
        captures=a.read(directory,'captures.json');captures['sales']['sha256']=a.digest(directory,capture.name);captures['sales']['bytes']=capture.stat().st_size;atomic_json(directory/'captures.json',captures)
        (directory/'import.sql').write_text(a.import_sql(p,a.captured(directory,p)))
        bindings={str(directory/n):a.digest(directory,n) for n in a.stage_inputs('import',p)};atomic_json(directory/'import-inputs.json',bindings);refresh(directory)
        report['capturedValueChangedWithRefreshedBindings']=refused(lambda:a.verify(directory))['code']
    finally:restore()
    for name,mutation in [('missingEvidence',lambda r:r['evidence'].pop('query.stdout')),('extraEvidence',lambda r:r['evidence'].update({'extra.json':'0'*64})),('publicationMembership',lambda r:r['artifacts'].pop()),('runtimeIdentity',lambda r:r.update(runtime='3.54.1 forged'))]:
        try:
            r=a.read(directory,'verification.json');mutation(r);atomic_json(directory/'verification.json',r)
            report[name]=refused(lambda:a.verify(directory))['code']
        finally:restore()
    try:
        r=a.read(directory,'query-submission.json');r['nativeCommand']=['/forged/sqlite3'];atomic_json(directory/'query-submission.json',r);refresh(directory)
        report['commandBinding']=refused(lambda:a.verify(directory))['code']
    finally:restore()
    assert a.verify(directory)['verified'];return report


def lifecycle(directory,document):
    """Deterministic owned-child probes; these wrappers are not SQLite evidence."""
    wrapper=directory/'slow-runtime.py';marker=directory/'slow.pid'
    wrapper.write_text('#!'+sys.executable+'\nimport os,time\nfrom pathlib import Path\nPath('+repr(str(marker))+').write_text(str(os.getpid()))\ntime.sleep(30)\n');wrapper.chmod(0o700)
    report={}
    for action in ['timeout','cancel']:
        if marker.exists():marker.unlink()
        cancel=threading.Event()
        def trigger():
            deadline=time.monotonic()+5
            while not marker.exists() and time.monotonic()<deadline:time.sleep(.01)
            if marker.exists():cancel.set()
        thread=threading.Thread(target=trigger,daemon=True) if action=='cancel' else None
        if thread:thread.start()
        try:
            with allocation({'threads':1,'ranks':1},cancel):
                report[action]=refused(lambda:a.run(document,directory/('inflight-'+action),executable=str(wrapper),timeout=8 if thread else .4),'RUNNER_CANCELLED' if thread else 'RUNNER_TIMED_OUT')['code']
        finally:
            if thread:thread.join(6)
        assert marker.exists(),'owned child not launched'
        try:os.kill(int(marker.read_text()),0)
        except ProcessLookupError:pass
        else:raise AssertionError('child survived '+action)
    return report



def native_safety(directory,document,executable):
    """Run quoted hostile TEXT cells and an actively poisoned startup file."""
    d=copy.deepcopy(document);source=directory/'quoted-departments.json'
    source.write_text(json.dumps([{'id':1,'region':"x'); DROP TABLE sales;--"},{'id':2,'region':'.load /untrusted/extension'},{'id':3,'region':''},{'id':4,'region':None}]))
    d['tables'][0]['source']=str(source);target=directory/'quoted-and-startup'
    native_execute=a.execute
    def with_poison(command,output,stage,timeout,environment=None):
        # HOME for the actual native process is this fresh output directory.
        # If default startup were read, safe mode would reject this directive
        # or the marker would appear; either outcome fails the acceptance.
        (Path(output)/'.sqliterc').write_text('.shell touch STARTUP_WAS_READ\n')
        return native_execute(command,output,stage,timeout,environment)
    with patch.object(a,'execute',with_poison):
        result=a.run(d,target,executable=executable,timeout=30)
    assert result['verified'] and a.verify(target)['verified'];assert not (target/'STARTUP_WAS_READ').exists()
    raw=json.loads((target/'query.stdout').read_text());assert [r['g0'] for r in raw]==[None,'','.load /untrusted/extension',"x'); DROP TABLE sales;--"]
    with sqlite3.connect((target/'summary.sqlite').as_uri()+'?mode=ro',uri=True) as db:
        assert db.execute('SELECT COUNT(*) FROM sales').fetchone()==(7,)
    numeric=copy.deepcopy(document);numeric.pop('join');numeric.pop('where');numeric['groupBy']=['sales.amount']
    numeric_target=directory/'null-zero-groups';a.run(numeric,numeric_target,executable=executable,timeout=30)
    expected=[[None,2,None],[-30,1,-30],[0,1,0],[50,1,50],[100,1,100],[200,1,200]]
    assert a.read(numeric_target,'summary.json')['rows']==expected
    maximum=copy.deepcopy(document);large=directory/'large-integer-sales.json'
    large.write_text(json.dumps([{'id':i,'department':1,'amount':1000000000} for i in range(1,2049)]))
    maximum['tables'][1]['source']=str(large);large_target=directory/'large-integer-total';a.run(maximum,large_target,executable=executable,timeout=30)
    assert a.read(large_target,'summary.json')['rows']==[['North',2048,2048000000000]]
    raw=a.read(large_target,'query.stdout');assert raw==[{'g0':'North','row_count':2048,'total':2048000000000}] and type(raw[0]['total']) is int
    return {'quotedSQLTextRemainsData':True,'dotCommandTextRemainsData':True,'poisonedDefaultStartupIgnored':True,'nullAndZeroGroupingDistinct':True,'maximumIntegerTotalExact':2048000000000}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--sqlite',required=True,type=Path);parser.add_argument('--output-directory',required=True,type=Path);parser.add_argument('--register',action='store_true');args=parser.parse_args()
    directory=args.output_directory.resolve();directory.mkdir(parents=True,exist_ok=False);locations={'sqlite':str(args.sqlite.resolve())};report={'verified':False}
    try:
        receipt=qualify(a.VERSION,directory/'kit',native=True,root=ROOT,locations=locations,timeout=30,wall_timeout=45)
        report['native']={'verified':receipt['verified'],'cases':[c['id'] for c in receipt['cases']],'runtimes':[c['runtime'] for c in receipt['cases']],'lifecycle':receipt['lifecycle']}
        baseline=directory/'kit/baseline';literal=[[None,1,None],['',1,0],['North',3,300],['South',1,-30]]
        # Literal expectations inspect native stdout, not adaptor summary output.
        raw=json.loads((baseline/'query.stdout').read_text());assert [[r['g0'],r['row_count'],r['total']] for r in raw]==literal
        with sqlite3.connect((baseline/'summary.sqlite').as_uri()+'?mode=ro',uri=True) as db:
            assert db.execute('SELECT id,department,amount FROM sales ORDER BY id').fetchall()==[(1,1,100),(2,1,None),(3,2,-30),(4,None,50),(5,3,0),(6,1,200),(7,4,None)]
        report['literalNativeRows']=literal;report['hostile']=hostile(baseline)
        _,_,entry=route_materials(a.VERSION);document=case_document(entry,entry['development']['cases'][0],ROOT)
        report['nativeSafety']=native_safety(directory,document,locations['sqlite'])
        source=directory/'sales.json';shutil.copyfile(document['tables'][1]['source'],source);document['tables'][1]['source']=str(source)
        consumer=copy.deepcopy(document);consumer['where']={'column':'sales.amount','minimum':{'$value':'report','artifact':1,'path':'/rows/3/2'}}
        graph={'version':'schemaxis.workflow/1','operations':[{'id':'report','document':document},{'id':'qualified','document':consumer}]}
        first=workflow.execute(graph,directory/'workflow',locations=locations,timeout=30);assert workflow.verify(directory/'workflow')['verified']
        downstream=next(j for j in first['jobs'] if j['operation']=='qualified')
        assert a.read(Path(downstream['directory']),'summary.json')['rows']==[['',1,0],['North',2,300],['South',1,-30]]
        second=workflow.execute(graph,directory/'workflow',locations=locations,timeout=30,resume=True);assert all(j['reused'] for j in second['jobs'])
        source.write_bytes(source.read_bytes()+b'\n')
        third=workflow.execute(graph,directory/'workflow',locations=locations,timeout=30,resume=True);assert not any(j['reused'] for j in third['jobs']);assert workflow.verify(directory/'workflow')['verified']
        report['workflow']={'status':first['status'],'verifiedValueHandoff':True,'unchangedReused':True,'samePathByteEditReused':False}
        study=copy.deepcopy(document);study['axes']=[{'name':'minimum','values':[1,3]}];study['where']['minimum']={'$axis':'minimum'}
        result=a.run(study,directory/'study',executable=locations['sqlite'],timeout=30);assert a.verify(directory/'study')['verified'];assert len(result['states'])==2;report['composition']={'states':2,'verified':True}
        report['inflightLifecycle']=lifecycle(directory,document)
        if args.register:register(directory/'kit/qualification.json')
        report['verified']=True
    finally:atomic_json(directory/'acceptance.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
