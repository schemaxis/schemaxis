#!/usr/bin/env python3
"""Fresh native GetDP conduction qualification plus adversarial physics probes."""
import argparse
import copy
import json
import os
from pathlib import Path
from schemaxis.adaptor_conformance import qualify
from schemaxis.adaptors.getdp import adaptor
from schemaxis.artifacts import file_digest
from schemaxis.core.faults import SchemaxisError

ROOT=Path(__file__).resolve().parents[1]


def public_reuse(directory,report):
    import shlex
    import subprocess
    import sys
    from qualify_agent_service import Client
    client=Client(directory);records=[]
    try:
        context=client.call('adaptor_context',version=adaptor.VERSION)
        task=client.call('create_task',objective='Assess and refine layered wall conductivity',allowed_providers=['getdp'],budget={'maxAttempts':3,'maxElapsedSeconds':180})
        draft=client.call('create_draft',provider='getdp',name='Layered wall')
        document=json.loads((ROOT/'examples/schemaxis/getdp-baseline.json').read_text())
        draft=client.call('edit_draft',document_id=draft['document'],expected_revision=draft['revision'],source=json.dumps(document))
        def execute(draft,revision):
            plan=client.call('plan_draft',task_id=task['id'],expected_revision=revision,document_id=draft['document'],draft_revision=draft['revision'])
            job=client.call('execute',plan_id=plan['id'],expected_revision=plan['revision']);assert client.wait(job)['status']=='succeeded'
            assert client.call('verify',job_id=job['id'])['value']['verified']
            resources=client.call('observe',job_id=job['id'],section='resources')['value'];summary=next(r for r in resources if Path(r['file']).name=='conduction-summary.json')
            observed=client.call('inspect_resource',resource_id=summary['id'])['value'];return plan,observed
        plan,first=execute(draft,0);assert abs(first['rightOutflowTotal']-5000)<1e-6
    finally:records.extend(client.records);client.close()
    edits=[{'op':'replace','path':'/layers/0/conductivity','value':5}]
    changed=subprocess.run([sys.executable,'-m','schemaxis','console','--provider','getdp','--workspace',str(directory/'authoring'),'--command','patch '+shlex.quote(json.dumps(edits))],capture_output=True,text=True,timeout=30,check=True)
    (directory/'console-edit.json').write_text(changed.stdout)
    client=Client(directory)
    try:
        draft=next(d for d in client.call('list_drafts')['value'] if d['document']==draft['document'])
        stale=client.request('execute',plan_id=plan['id'],expected_revision=plan['revision']);assert not stale['ok'] and stale['fault']['code']=='STALE_REVISION'
        plan,second=execute(draft,plan['revision']);assert abs(second['rightOutflowTotal']-2500)<1e-6
        invalid=copy.deepcopy(document);invalid['left']=invalid['right']={'kind':'flux','value':0}
        rejected=client.request('plan',task_id=task['id'],expected_revision=plan['revision'],document=invalid);assert not rejected['ok'] and rejected['fault']['code']=='UNANCHORED_FIELD'
        report['publicHumanReuse']={'baselineOutflow_W':first['rightOutflowTotal'],'editedOutflow_W':second['rightOutflowTotal'],'stalePlanRejected':True,'unanchoredRejected':True,'sameDraft':draft['document']}
    finally:records.extend(client.records);client.close()
    report['publicTransport']={'requests':len(records),'responseBytes':sum(r['responseBytes'] for r in records)}


def workflow_and_study(directory,report,with_calc=False):
    from schemaxis import workflow
    from schemaxis.tabular import read_csv,close
    document=json.loads((ROOT/'examples/schemaxis/getdp-to-calc.json').read_text())
    if not with_calc:document['operations']=document['operations'][:1]
    result=workflow.execute(document,directory/'workflow',timeout=120);assert workflow.verify(directory/'workflow')['verified']
    if with_calc:
        jobs={j['operation']:j for j in result['jobs']}
        assert close(read_csv(Path(jobs['wall']['directory'])/'field.csv'),read_csv(Path(jobs['workbook']['directory'])/'data.csv'))
    resumed=workflow.execute(document,directory/'workflow',timeout=120,resume=True);assert all(j['reused'] for j in resumed['jobs'])
    report['workflow']={'fieldToCalc':with_calc,'allReused':True,'calcScope':'Optional --with-calc requires a separately configured working LibreOffice runtime.'}
    study=json.loads((ROOT/'examples/schemaxis/getdp-conductivity-study.json').read_text());result=adaptor.run(study,directory/'study');assert adaptor.verify(directory/'study')['verified'];assert len(result['states'])==3
    report['study']={'conductivities':[5,10,20],'verifiedStates':3}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output-directory',required=True,type=Path);parser.add_argument('--getdp');parser.add_argument('--with-calc',action='store_true',help='Also qualify field CSV handoff with an independently configured Calc runtime');args=parser.parse_args()
    if args.getdp:os.environ['GETDP_EXECUTABLE']=args.getdp
    directory=args.output_directory.absolute();directory.mkdir(parents=True,exist_ok=False)
    receipt=qualify(adaptor.VERSION,directory/'native',native=True,timeout=120)
    if not receipt['verified']:raise AssertionError(receipt)
    report={'verified':False,'nativeKit':True,'negative':[],'additional':[]}
    # Both convection ends and a current-flux end independently exercise anchoring/signs.
    doc=json.loads((ROOT/'examples/schemaxis/getdp-baseline.json').read_text())
    doc['left']={'kind':'convection','coefficient':100,'ambient':400};doc['right']={'kind':'convection','coefficient':100,'ambient':300}
    target=directory/'two-convection';adaptor.run(doc,target);summary=json.loads((target/'conduction-summary.json').read_text())
    assert abs(summary['rightOutflowTotal']-5000/3)<1e-6;report['additional'].append('both-convection exact series resistance')
    doc=json.loads((ROOT/'examples/schemaxis/getdp-current.json').read_text());doc['right']={'kind':'flux','value':1000}
    target=directory/'current-flux';adaptor.run(doc,target);summary=json.loads((target/'conduction-summary.json').read_text());assert abs(summary['minimumField']-9)<1e-7
    # Literal authored limits reject a small but real excess, even inside physics tolerance.
    doc['limits']={'maximumField':9.99999999}
    try:adaptor.run(doc,directory/'unmet')
    except SchemaxisError as error:assert error.fault.code=='PERFORMANCE_NOT_MET';report['negative'].append('literal sampled bound violation')
    else:raise AssertionError('unmet literal limit accepted')
    # Refreshing producer digests must not conceal changed native solution or output.
    for name,old,new in [('model.res',b'9.9',b'8.9'),('native-field.pos',b'{10,',b'{11,'),('model.msh',b'2.2 0 8',b'2.1 0 8'),('model.res',b'$Solution',b'$SolutiXX'),('model.pre',b'$DofData',b'$DofDaXX')]:
        path=target/name;saved=path.read_bytes();verification=target/'verification.json';saved_receipt=verification.read_bytes()
        try:
            if old in saved:changed=saved.replace(old,new,1)
            else:changed=saved+b'\nforged\n'
            path.write_bytes(changed);v=json.loads(saved_receipt)
            if name in v['evidence']:v['evidence'][name]=file_digest(path)
            for artifact in v['artifacts']:
                if Path(artifact['file']).name==name:artifact['sha256']=file_digest(path)
            verification.write_text(json.dumps(v))
            try:adaptor.verify(target)
            except SchemaxisError as error:assert error.fault.code=='VERIFICATION_FAILED';report['negative'].append(name+' refreshed-digest tamper')
            else:raise AssertionError('tamper accepted: '+name)
        finally:path.write_bytes(saved);verification.write_bytes(saved_receipt)
        assert adaptor.verify(target)['verified']
    public_reuse(directory/'public',report)
    workflow_and_study(directory,report,args.with_calc)
    report['verified']=True;(directory/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
