#!/usr/bin/env python3
"""Cantera native kit, numeric workbook handoffs and public/human reuse acceptance."""
import argparse
import copy
import json
import math
import os
from pathlib import Path
import subprocess
import sys

from schemaxis.adaptor_conformance import qualify
from schemaxis.adaptors import registry
from schemaxis.configuration import locations
from schemaxis.core.faults import SchemaxisError
from schemaxis.tabular import read_csv, close
from schemaxis import workflow
from qualify_agent_service import Client
from qualify_adaptor_growth import context, example_document

ROOT = Path(__file__).resolve().parents[1]
R = 8314.46261815324


def public_loop(directory,report):
    records = []; client = Client(directory)
    try:
        client.call('capabilities.browse')
        provider,stamp = context(client,'schemaxis.cantera/1','/provider')
        materials,_ = context(client,'schemaxis.cantera/1','/materials',stamp)
        cases = materials['development']['cases']
        task = client.call('create_task',objective='Verify and refine thermochemistry through shared authoring',
                          allowed_providers=[provider],budget={'maxAttempts':len(cases)+2,'maxElapsedSeconds':300})
        draft = client.call('create_draft',provider=provider,name='Gas table')
        revision = 0; report['publicCases'] = []
        def run_draft(draft,revision):
            planned = client.call('plan_draft',task_id=task['id'],expected_revision=revision,document_id=draft['document'],draft_revision=draft['revision'])
            job = client.call('execute',plan_id=planned['id'],expected_revision=planned['revision'])
            assert client.wait(job)['status'] == 'succeeded',client.call('observe',job_id=job['id'],section='fault')
            assert client.call('verify',job_id=job['id'])['value']['verified']
            resources = client.call('observe',job_id=job['id'],section='resources')['value']
            table = next(r for r in resources if Path(r['file']).name == 'results.csv')
            summary = next(r for r in resources if Path(r['file']).name == 'chemistry-summary.json')
            observed = client.call('inspect_resource',resource_id=table['id'],max_bytes=65536)['value']
            def summary_value(pointer):
                return client.call('inspect_resource',resource_id=summary['id'],pointer=pointer)['value']
            run_draft.summary = summary_value
            return planned,[[float(v) for v in row] for row in observed['rows']]
        for case in cases:
            example = next(e for e in materials['examples'] if e['id'] == case['example'])
            draft = client.call('edit_draft',document_id=draft['document'],expected_revision=draft['revision'],source=json.dumps(example_document(example,ROOT)))
            if case['edits']:
                draft = client.call('patch_draft',document_id=draft['document'],expected_revision=draft['revision'],edits=case['edits'])
            planned,rows = run_draft(draft,revision); revision = planned['revision']
            for check in case['checks']:
                if check['file'] == 'chemistry-summary.json':
                    value = run_draft.summary(check['pointer'])
                else:
                    _,_,r,c = check['pointer'].split('/'); value = rows[int(r)][int(c)]
                assert math.isclose(value,check['expected'],rel_tol=check.get('relative',0),abs_tol=check.get('absolute',0)),(case['id'],check,value)
            report['publicCases'].append({'case':case['id'],'rows':len(rows),'temperature_K':[r[1] for r in rows]})
        invalid = next(e for e in materials['examples'] if e.get('expect') == 'invalid')
        rejected = client.request('plan',task_id=task['id'],expected_revision=revision,document=example_document(invalid,ROOT))
        assert not rejected['ok'] and rejected['fault']['code'] == invalid['fault']
        # Leave the baseline in the same durable draft for a real console edit.
        draft = client.call('edit_draft',document_id=draft['document'],expected_revision=draft['revision'],source=(ROOT/'examples/schemaxis/cantera-minimal.json').read_text())
        planned,rows = run_draft(draft,revision); revision = planned['revision']; first_density=rows[0][3]
    finally:
        records.extend(client.records); client.close()
    result = subprocess.run([sys.executable,'-m','schemaxis','console','--provider','cantera','--workspace',str(directory/'authoring'),
                             '--command','set gas pressure 202650'],text=True,capture_output=True,check=True,timeout=30)
    (directory/'console-edit.json').write_text(result.stdout)
    client = Client(directory)
    try:
        current = next(d for d in client.call('list_drafts')['value'] if d['document'] == draft['document'])
        stale = client.request('execute',plan_id=planned['id'],expected_revision=revision)
        assert not stale['ok'] and stale['fault']['code'] == 'STALE_REVISION'
        _,rows = run_draft(current,revision)
        assert math.isclose(rows[0][3],2*first_density,rel_tol=1e-10)
        report['humanReuse']={'sameDraft':current['document'],'initialDensity_kg_m3':first_density,'refinedDensity_kg_m3':rows[0][3],'stalePlanRejected':True}
    finally:
        records.extend(client.records); client.close()
        report['transport']={'requests':len(records),'responseBytes':sum(r['responseBytes'] for r in records),'records':records}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory',type=Path,required=True);parser.add_argument('--config',type=Path)
    args=parser.parse_args()
    if args.config: os.environ['SCHEMAXIS_CONFIG']=str(args.config.resolve())
    directory=args.output_directory.resolve();directory.mkdir(parents=True,exist_ok=False)
    report={'verified':False,'workflows':[],'negative':[]}
    try:
        receipt=qualify('schemaxis.cantera/1',directory/'native',native=True)
        assert receipt['verified'],receipt
        original=json.loads((ROOT/'examples/schemaxis/cantera-to-calc.json').read_text())
        for pressure in (101325,202650):
            doc=copy.deepcopy(original);doc['operations'][0]['document']['nodes'][0]['options']['pressure']=pressure
            target=directory/('handoff-'+str(pressure))
            result=workflow.execute(doc,target,locations=locations(),timeout=120)
            assert workflow.verify(target)['verified']
            jobs={j['operation']:j for j in result['jobs']}
            table=read_csv(Path(jobs['chemistry']['directory'])/'results.csv')
            workbook=read_csv(Path(jobs['workbook']['directory'])/'data.csv')
            assert close(table,workbook)
            for row in table['rows']:
                assert math.isclose(row[3],pressure*39.95/(R*row[1]),rel_tol=1e-10)
            resumed=workflow.execute(doc,target,locations=locations(),timeout=120,resume=True)
            assert all(j['reused'] for j in resumed['jobs'])
            report['workflows'].append({'pressure_Pa':pressure,'rows':len(table['rows']),'columns':len(table['columns']),'allReused':True})
        # Mechanism identity must survive a forged digest refresh in the manifest.
        target=Path(jobs['chemistry']['directory']);path=target/'mechanism.yaml';saved=path.read_bytes()
        verification=target/'verification.json'; original_verification=verification.read_bytes()
        try:
            from schemaxis.artifacts import file_digest
            path.write_bytes(saved+b'\n# modified mechanism\n')
            v=json.loads(original_verification);v['evidence']['mechanism.yaml']=file_digest(path)
            verification.write_text(json.dumps(v))
            try: registry.verify(target)
            except SchemaxisError as error:
                assert error.fault.code == 'VERIFICATION_FAILED';report['negative'].append({'changedMechanism':error.fault.code})
            else: raise AssertionError('modified mechanism accepted')
        finally:
            path.write_bytes(saved);verification.write_bytes(original_verification)
        assert registry.verify(target)['verified']
        # A verified reactor history crosses the same numeric-table handoff.
        reactor=json.loads((ROOT/'examples/schemaxis/cantera-reactor.json').read_text())
        for model in ('constantPressure','constantVolume'):
            doc=copy.deepcopy(original);doc['operations'][0]['document']=copy.deepcopy(reactor)
            doc['operations'][0]['document']['nodes'][1]['options']['model']=model
            target=directory/('reactor-handoff-'+model)
            result=workflow.execute(doc,target,locations=locations(),timeout=300)
            assert workflow.verify(target)['verified']
            jobs={j['operation']:j for j in result['jobs']}
            table=read_csv(Path(jobs['chemistry']['directory'])/'results.csv')
            workbook=read_csv(Path(jobs['workbook']['directory'])/'data.csv')
            assert close(table,workbook) and table['columns'][0] == 'time_s'
            times=reactor['nodes'][1]['options']['times']
            assert [row[0] for row in table['rows']] == times
            density=table['rows'][0][3]
            for row in table['rows']:
                if model == 'constantPressure': assert math.isclose(row[2],101325,rel_tol=1e-10)
                else: assert math.isclose(row[3],density,rel_tol=1e-10)
            resumed=workflow.execute(doc,target,locations=locations(),timeout=300,resume=True)
            assert all(j['reused'] for j in resumed['jobs'])
            report['workflows'].append({'reactor':model,'rows':len(table['rows']),'finalTemperature_K':table['rows'][-1][1],'allReused':True})
        public_loop(directory/'public',report)
        report['verified']=True
    finally:
        (directory/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k != 'transport'},indent=2))


if __name__ == '__main__':main()
