#!/usr/bin/env python3
"""Bounded native planar-truss acceptance; literal witnesses precede observed output."""
import argparse
import copy
import json
import os
import venv
from unittest.mock import patch
from pathlib import Path
import shutil
from schemaxis import workflow
from schemaxis.adaptors import registry
from schemaxis.adaptors.opensees import adaptor as a
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.core.faults import SchemaxisError
ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--executable',required=True);parser.add_argument('--output-directory',required=True);args=parser.parse_args()
    out=Path(args.output_directory).absolute();out.mkdir(parents=True,exist_ok=False);records=[]
    locations={'opensees':args.executable}
    for name in ('triangle','stiffness','reverse','redundant','double-pin'):
        doc=json.loads((ROOT/f'examples/schemaxis/opensees-{name}.json').read_text());target=out/name
        result=registry.run(doc,target,locations=locations,timeout=30);assert result['verified'];assert a.verify(target)['verified']
        summary=json.loads((target/'truss-assessment.json').read_text());assert summary['accepted']
        if name in ('triangle','stiffness'):
            factor=1 if name=='triangle' else .5
            assert abs(summary['results']['nodes'][2]['displacement_m'][1]+9.571067811865475e-6*factor)<1e-12
            assert abs(summary['results']['members'][1]['force_N']+707.1067811865476)<1e-6
        if name=='double-pin':
            assert summary['results']['members'][0]['force_N']==0
            assert abs(json.loads((target/'build.json').read_text())['materials'][0]['area_m2']-.001234567891)<1e-15
        records.append({'case':name,'runtime':result['runtime'],'nodes':result['nodes'],'members':result['members']})
    target=out/'triangle'
    def refusal(label,mutate):
        backup={p:p.read_bytes() for p in target.rglob('*') if p.is_file() and not p.is_symlink()}
        try:
            mutate()
            try:a.verify(target)
            except SchemaxisError as error:
                assert error.fault.code in (('VERIFICATION_FAILED','INVALID_SCHEMA_SNAPSHOT') if label=='evidence-authored.json' else ('VERIFICATION_FAILED',)),(label,error.fault.code)
                records.append({'negative':label,'fault':error.fault.code});return
            raise AssertionError('tamper accepted: '+label)
        finally:
            for path,data in backup.items():path.write_bytes(data)
    for name,_ in a.FILES:
        refusal('publication-'+name,lambda name=name:(target/name).write_text('{}'))
    for name in ('authored.json','plan.json','build.json','reopen.json','worker.py','build-submission.json'):
        refusal('evidence-'+name,lambda name=name:(target/name).write_text('{}'))
    def forged():
        # Rewrite both native responses and native evidence digests: independent mechanics must refuse before publication comparison.
        for name in ('build.json','reopen.json'):
            value=json.loads((target/name).read_text());value['results']['members'][0]['force_N']+=1;atomic_json(target/name,value)
        record=json.loads((target/'verification.json').read_text())
        record['evidence']={name:file_digest(target/name) for name in a.EVIDENCE};atomic_json(target/'verification.json',record)
    refusal('native-force-with-refreshed-hashes',forged)
    def forged_type(kind):
        for name in ('build.json','reopen.json'):
            value=json.loads((target/name).read_text())
            if kind=='pid':value['pid']=True if name=='build.json' else False
            elif kind=='coordinates':value[kind][0][0]=False
            elif kind=='connections':value[kind][0][0]=True
            elif kind=='fixedDOFs':value[kind][0][0]=True
            atomic_json(target/name,value)
        if kind=='exitCode':
            value=json.loads((target/'build-submission.json').read_text());value['exitCode']=False;atomic_json(target/'build-submission.json',value)
        record=json.loads((target/'verification.json').read_text());record['evidence']={name:file_digest(target/name) for name in a.EVIDENCE};atomic_json(target/'verification.json',record)
    for kind in ('pid','coordinates','connections','fixedDOFs','exitCode'):
        refusal('boolean-'+kind+'-with-refreshed-hashes',lambda kind=kind:forged_type(kind))
    doc=json.loads((ROOT/'examples/schemaxis/opensees-unmet.json').read_text())
    try:registry.run(doc,out/'unmet',locations=locations,timeout=30)
    except SchemaxisError as error:assert error.fault.code=='PERFORMANCE_NOT_MET';records.append({'negative':'unmet','fault':error.fault.code})
    else:raise AssertionError('unmet requirement accepted')
    doc=json.loads((ROOT/'examples/schemaxis/opensees-triangle.json').read_text())
    try:registry.run(doc,out/'timeout',locations=locations,timeout=.000001)
    except SchemaxisError as error:assert error.fault.code=='RUNNER_TIMED_OUT';records.append({'negative':'timeout','fault':error.fault.code})
    else:raise AssertionError('timeout accepted')
    # These are trusted qualification fixtures, never an authored module/package selector.
    empty=out/'empty-python';venv.EnvBuilder(with_pip=False).create(empty)
    try:registry.run(doc,out/'unavailable',locations={'opensees':str(empty/'bin/python')},timeout=30)
    except SchemaxisError as error:assert error.fault.code=='NATIVE_UNAVAILABLE';records.append({'negative':'unavailable-package','fault':error.fault.code})
    else:raise AssertionError('missing native package accepted')
    fixture=out/'wrong-version-fixture';package=fixture/'openseespy';package.mkdir(parents=True)
    (package/'__init__.py').write_text('')
    (package/'opensees.py').write_text('def version(): return "0.0.0"\n')
    with patch.dict(os.environ,{'PYTHONPATH':str(fixture)+os.pathsep+os.environ.get('PYTHONPATH','')}):
        try:registry.run(doc,out/'unsupported',locations=locations,timeout=30)
        except SchemaxisError as error:assert error.fault.code=='UNSUPPORTED_RUNTIME';records.append({'negative':'unsupported-engine','fault':error.fault.code})
        else:raise AssertionError('wrong native version accepted')
    flow=json.loads((ROOT/'examples/schemaxis/opensees-workflow.json').read_text());flowdir=out/'workflow'
    first=workflow.execute(flow,flowdir,locations=locations,timeout=30);assert workflow.verify(flowdir)['verified']
    resumed=workflow.execute(flow,flowdir,locations=locations,timeout=30,resume=True);assert all(j['reused'] for j in resumed['jobs'])
    records.append({'workflow':'unchanged-native-reuse','reused':True})
    job=Path(resumed['jobs'][0]['directory']);(job/'members.csv').write_text('corrupt\n')
    recovered=workflow.execute(flow,flowdir,locations=locations,timeout=30,resume=True);assert all(not j['reused'] for j in recovered['jobs']);assert workflow.verify(flowdir)['verified']
    records.append({'workflow':'corrupt-evidence-recomputed','reused':False})
    changed=copy.deepcopy(flow);changed['operations'][0]['document']['loads'][0]['force_N'][1]=-500
    try:workflow.execute(changed,flowdir,locations=locations,timeout=30,resume=True)
    except SchemaxisError as error:assert error.fault.code=='RESUME_MISMATCH';records.append({'negative':'changed-authored-resume','fault':error.fault.code})
    else:raise AssertionError('changed authored workflow reused')
    # Canonical conformance supplies prelaunch cancellation and all-publication lifecycle controls.
    atomic_json(out/'acceptance.json',{'status':'passed','records':records});print(json.dumps({'status':'passed','checks':len(records),'evidence':str(out/'acceptance.json')}))


if __name__=='__main__':main()
