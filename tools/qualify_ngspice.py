#!/usr/bin/env python3
"""Native linear-circuit kit, Calc handoff and shared document/console reuse."""
import argparse
import copy
import json
import math
import os
from pathlib import Path
import shlex
import subprocess
import sys

from schemaxis.adaptor_conformance import qualify
from schemaxis.adaptors import registry
from schemaxis.artifacts import file_digest
from schemaxis.configuration import locations
from schemaxis.core.faults import SchemaxisError
from schemaxis.tabular import read_csv, close
from schemaxis import workflow
from qualify_agent_service import Client
from qualify_adaptor_growth import context, example_document

ROOT=Path(__file__).resolve().parents[1]


def public_loop(directory,report):
    client=Client(directory);records=[]
    try:
        client.call('capabilities.browse')
        provider,stamp=context(client,'schemaxis.ngspice/1','/provider')
        materials,_=context(client,'schemaxis.ngspice/1','/materials',stamp)
        assert materials['development']['authoring']['model']=='document'
        cases=materials['development']['cases']
        task=client.call('create_task',objective='Verify and refine linear circuit responses',allowed_providers=[provider],budget={'maxAttempts':len(cases)+2,'maxElapsedSeconds':300})
        draft=client.call('create_draft',provider=provider,name='Circuit response');revision=0
        report['publicCases']=[]
        def run_draft(draft,revision):
            planned=client.call('plan_draft',task_id=task['id'],expected_revision=revision,document_id=draft['document'],draft_revision=draft['revision'])
            job=client.call('execute',plan_id=planned['id'],expected_revision=planned['revision'])
            assert client.wait(job)['status']=='succeeded',client.call('observe',job_id=job['id'],section='fault')
            assert client.call('verify',job_id=job['id'])['value']['verified']
            resources=client.call('observe',job_id=job['id'],section='resources')['value']
            resource=next(r for r in resources if Path(r['file']).name=='circuit-summary.json')
            observed=client.call('inspect_resource',resource_id=resource['id'])['value']
            return planned,observed
        for case in cases:
            example=next(e for e in materials['examples'] if e['id']==case['example'])
            draft=client.call('edit_draft',document_id=draft['document'],expected_revision=draft['revision'],source=json.dumps(example_document(example,ROOT)))
            if case['edits']:draft=client.call('patch_draft',document_id=draft['document'],expected_revision=draft['revision'],edits=case['edits'])
            planned,observed=run_draft(draft,revision);revision=planned['revision']
            for check in case['checks']:
                value=observed
                for part in check['pointer'].split('/')[1:]:value=value[int(part)] if isinstance(value,list) else value[part.replace('~1','/').replace('~0','~')]
                assert close(value,check['expected'],rel=check.get('relative',0),absolute=check.get('absolute',0))
            report['publicCases'].append({'case':case['id'],'summary':observed})
        invalid=next(e for e in materials['examples'] if e.get('expect')=='invalid')
        rejected=client.request('plan',task_id=task['id'],expected_revision=revision,document=example_document(invalid,ROOT))
        assert not rejected['ok'] and rejected['fault']['code']==invalid['fault']
        draft=client.call('edit_draft',document_id=draft['document'],expected_revision=draft['revision'],source=(ROOT/'examples/schemaxis/ngspice-rlc-resonance.json').read_text())
        planned,observed=run_draft(draft,revision);revision=planned['revision'];first=observed['firstRow'][1:3]
    finally:
        records.extend(client.records);client.close()
    edits=[{'op':'replace','path':'/circuit/inductors/0/inductance','value':2}]
    result=subprocess.run([sys.executable,'-m','schemaxis','console','--provider','ngspice','--workspace',str(directory/'authoring'),
        '--command','patch '+shlex.quote(json.dumps(edits))],text=True,capture_output=True,check=True,timeout=30)
    (directory/'console-edit.json').write_text(result.stdout)
    client=Client(directory)
    try:
        current=next(d for d in client.call('list_drafts')['value'] if d['document']==draft['document'])
        stale=client.request('execute',plan_id=planned['id'],expected_revision=revision)
        assert not stale['ok'] and stale['fault']['code']=='STALE_REVISION'
        _,observed=run_draft(current,revision)
        assert close(first,[0,-1],absolute=1e-8) and close(observed['firstRow'][1:3],[-.5,-.5],absolute=1e-8)
        report['humanReuse']={'sameDraft':current['document'],'initialPhasor_V':first,'refinedPhasor_V':observed['firstRow'][1:3],'inductance_H':[1,2],'stalePlanRejected':True}
    finally:
        records.extend(client.records);client.close()
        report['transport']={'requests':len(records),'responseBytes':sum(r['responseBytes'] for r in records),'records':records}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory',type=Path,required=True);parser.add_argument('--config',type=Path)
    args=parser.parse_args()
    if args.config:os.environ['SCHEMAXIS_CONFIG']=str(args.config.resolve())
    directory=args.output_directory.resolve();directory.mkdir(parents=True,exist_ok=False)
    report={'verified':False,'workflows':[],'negative':[]}
    try:
        receipt=qualify('schemaxis.ngspice/1',directory/'native',native=True)
        assert receipt['verified'],receipt
        original=json.loads((ROOT/'examples/schemaxis/ngspice-to-calc.json').read_text())
        for resistance in (1000,2000):
            doc=copy.deepcopy(original);doc['operations'][0]['document']['circuit']['resistors'][0]['resistance']=resistance
            target=directory/('handoff-'+str(resistance));result=workflow.execute(doc,target,locations=locations(),timeout=120)
            assert workflow.verify(target)['verified']
            jobs={j['operation']:j for j in result['jobs']}
            table=read_csv(Path(jobs['circuit']['directory'])/'results.csv');workbook=read_csv(Path(jobs['workbook']['directory'])/'data.csv')
            assert close(table,workbook)
            assert all(math.isclose(row[1],row[0]*2000/(resistance+2000),abs_tol=1e-8) for row in table['rows'])
            resumed=workflow.execute(doc,target,locations=locations(),timeout=120,resume=True)
            assert all(j['reused'] for j in resumed['jobs'])
            report['workflows'].append({'resistance_ohm':resistance,'endpointVoltage_V':table['rows'][-1][1],'allReused':True})
        original=json.loads((ROOT/'examples/schemaxis/ngspice-rlc-to-calc.json').read_text())
        for inductance in (1,2):
            doc=copy.deepcopy(original);doc['operations'][0]['document']['circuit']['inductors'][0]['inductance']=inductance
            target=directory/('rlc-handoff-'+str(inductance));result=workflow.execute(doc,target,locations=locations(),timeout=120)
            assert workflow.verify(target)['verified']
            jobs={j['operation']:j for j in result['jobs']}
            table=read_csv(Path(jobs['circuit']['directory'])/'results.csv');workbook=read_csv(Path(jobs['workbook']['directory'])/'data.csv')
            assert close(table,workbook)
            for row in table['rows']:
                x=2*math.pi*row[0]/1000
                expected=1/(1-inductance*x*x+1j*x)
                assert abs(complex(row[1],row[2])-expected)<1e-8
                assert math.isclose(row[3],abs(expected),abs_tol=1e-8)
            resumed=workflow.execute(doc,target,locations=locations(),timeout=120,resume=True)
            assert all(j['reused'] for j in resumed['jobs'])
            report['workflows'].append({'inductance_H':inductance,'firstPhasor_V':table['rows'][0][1:3],'allReused':True})
        # Even a refreshed raw-file digest cannot hide data/header corruption.
        target=Path(jobs['circuit']['directory']);path=target/'result.raw';saved=path.read_bytes()
        verification=target/'verification.json';saved_verification=verification.read_bytes()
        try:
            path.write_bytes(saved.replace(b'v(out)',b'v(bad)'))
            v=json.loads(saved_verification);v['evidence']['result.raw']=file_digest(path);verification.write_text(json.dumps(v))
            try:registry.verify(target)
            except SchemaxisError as error:
                assert error.fault.code=='VERIFICATION_FAILED';report['negative'].append({'rawCorruptionWithRefreshedDigest':error.fault.code})
            else:raise AssertionError('corrupt raw file accepted')
        finally:path.write_bytes(saved);verification.write_bytes(saved_verification)
        assert registry.verify(target)['verified']
        public_loop(directory/'public',report)
        report['verified']=True
    finally:(directory/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='transport'},indent=2))


if __name__=='__main__':main()
