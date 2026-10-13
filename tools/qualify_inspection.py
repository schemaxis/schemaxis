#!/usr/bin/env python3
"""Verify native numerical publications through typed snapshot/reference tools."""
import argparse
import json
from pathlib import Path
from qualify_agent_service import Client


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory',type=Path,required=True)
    root=parser.parse_args().output_directory.resolve()
    root.mkdir(parents=True,exist_ok=False)
    client=Client(root/'workspace')
    try:
        task=client.call('create_task',objective='Inspect a native five-sample scaled series',allowed_providers=['octave'],budget={'maxAttempts':1})
        document={'version':'schemaxis.octave/1','nodes':[
            {'id':'samples','filter':'sequence','options':{'start':0,'stop':4,'count':5}},
            {'id':'scaled','filter':'scale','inputs':{'input':'samples'},'options':{'factor':2}}], 'outputs':['scaled']}
        plan=client.call('plan',task_id=task['id'],expected_revision=0,document=document)
        job=client.wait(client.call('execute',plan_id=plan['id'],expected_revision=plan['revision']))
        assert job['verified']
        verification=client.call('verify',job_id=job['id'])['value']
        resources=client.call('observe',job_id=job['id'],section='resources')['value']
        publication=next(r for r in resources if r['name']=='scaled.csv')
        snapshot=client.call('snapshot_resource',resource_id=publication['id'],kind='table')
        view=client.call('inspect_snapshot',resource_id=snapshot['id'],revision=snapshot['revision'],view='series',x_column=0,y_column=1)
        assert [(p['x'],p['y']) for p in view['points']]==[(float(i),float(2*i)) for i in range(5)]
        ref=client.call('reference_snapshot',resource_id=snapshot['id'],revision=snapshot['revision'],kind='series-interval',selection={'rowStart':1,'rowEnd':4,'xColumn':0,'yColumn':1})
        selection=client.call('inspect_selection',reference_id=ref['id'])['value']
        assert selection['evidence']['points']==[[1,2],[2,4],[3,6]]
        assert not selection['stale'] and not ref['replayable']
        for preset in ('text-inspection','table-analysis','geometry-study'):
            client.call('inspection_workspace',preset=preset,resource_id=snapshot['id'])
        assert client.call('job',job_id=job['id'])['verified']
        report={'verified':True,'scope':'One native GNU Octave execution with typed historical inspection; no extraction or MPI qualification.',
                'job':job,'verification':verification,'snapshot':snapshot,'series':view,'selection':selection,
                'transport':{'requests':len(client.records),'responseBytes':sum(r['responseBytes'] for r in client.records),
                             'largestResponseBytes':max(r['responseBytes'] for r in client.records)}}
        (root/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))
    finally:client.close()


if __name__=='__main__':main()
