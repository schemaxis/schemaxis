#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Native serial proof of workflow draft/graph/source parity over agent tools."""
import argparse
import copy
import json
from pathlib import Path
from qualify_agent_service import Client
from schemaxis.workflow_authoring import example


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory',type=Path,required=True)
    root=parser.parse_args().output_directory.resolve();root.mkdir(parents=True,exist_ok=False)
    client=Client(root/'workspace')
    try:
        document=example()
        alternate=copy.deepcopy(document['operations'][0]);alternate['id']='alternate'
        alternate['document']['nodes'][0]['options'].update(start=10,stop=14)
        document['operations'].insert(1,alternate)
        draft=client.call('create_draft',provider='workflow',name='Workflow handoff refinement')
        draft=client.call('edit_draft',document_id=draft['document'],expected_revision=draft['revision'],source=json.dumps(document))
        identity=draft['document']
        view=client.call('workflow_graph',document_id=identity,expected_revision=draft['revision'])['value']
        task=client.call('create_task',objective='Inspect and change a declared numerical handoff',allowed_providers=['octave'],budget={'maxAttempts':1})
        plan=client.call('plan_draft',task_id=task['id'],expected_revision=0,document_id=identity,draft_revision=draft['revision'])
        pointer=view['edges'][0]['pointer']
        rejected=client.request('rewire_workflow',document_id=identity,expected_revision=draft['revision'],pointer=pointer,source='scaled',artifact_index=0)
        assert rejected['fault']['code']=='UNAVAILABLE_OPERATION'
        ref=client.call('reference_workflow',document_id=identity,expected_revision=draft['revision'],operation_id='scaled')
        draft=client.call('rewire_workflow',document_id=identity,expected_revision=draft['revision'],pointer=pointer,source='alternate',artifact_index=0)
        stale=client.request('execute',plan_id=plan['id'],expected_revision=plan['revision'])
        assert stale['fault']['code']=='STALE_REVISION'
        assert next(r for r in client.call('selections')['value'] if r['id']==ref['id'])['stale']
        view=client.call('workflow_graph',document_id=identity,expected_revision=draft['revision'])['value']
        assert view['edges'][0]['source']=='alternate'
        location=client.call('locate_draft',document_id=identity,expected_revision=draft['revision'],pointer=pointer)
        assert location['value']=={'$artifact':'alternate','index':0}
        plan=client.call('plan_draft',task_id=task['id'],expected_revision=plan['revision'],document_id=identity,draft_revision=draft['revision'])
        job=client.wait(client.call('execute',plan_id=plan['id'],expected_revision=plan['revision']))
        assert job['verified'],job
        verification=client.call('verify',job_id=job['id'])['value']
        resources=client.call('observe',job_id=job['id'],section='resources')['value']
        resource=next(r for r in resources if r['operation']=='scaled/0' and r['name']=='result.csv')
        snapshot=client.call('snapshot_resource',resource_id=resource['id'],kind='table')
        series=client.call('inspect_snapshot',resource_id=snapshot['id'],revision=snapshot['revision'],view='series',x_column=0,y_column=1)
        assert [p['y'] for p in series['points']]==[20,22,24,26,28],series
        report={'verified':True,'scope':'One serial scheduled workflow, three GNU Octave operations; deterministic client, no MPI or model evaluation.',
                'graph':view,'sourceLocation':location,'job':job,'verification':verification,'series':series,
                'rejections':[rejected['fault']['code'],stale['fault']['code']],
                'transport':{'requests':len(client.records),'responseBytes':sum(r['responseBytes'] for r in client.records),'largestResponseBytes':max(r['responseBytes'] for r in client.records)}}
        (root/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        (root/'requests.json').write_text(json.dumps(client.records,indent=2)+'\n')
        print(json.dumps(report,indent=2))
    finally:client.close()


if __name__=='__main__':main()
