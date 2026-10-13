#!/usr/bin/env python3
"""Check migrated delivery context and shared authoring through public agent tools.

Independent native values are checked by adaptor conform; this client checks the
published procedure, source/property edits, verification and bounded resource access.
It does not claim autonomous-model quality or interpret binary geometry as text.
"""
import argparse
import copy
import json
from pathlib import Path
from qualify_agent_service import Client
from qualify_adaptor_growth import context, example_document

VERSIONS = ('schemaxis/1', 'schemaxis.blender/1', 'schemaxis.blender.render/1',
            'schemaxis.calc/1', 'schemaxis.godot/1', 'schemaxis.aseprite/1', 'schemaxis.qgis/1')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--config', type=Path)
    args = parser.parse_args()
    root = args.output_directory.resolve()
    root.mkdir(parents=True, exist_ok=False)
    repository = Path(__file__).resolve().parents[1]
    client = Client(root/'workspace', config=args.config)
    report = {'verified': False, 'scope': 'Deterministic published-context procedure on migrated routes; native expectations are checked by the separate conformance receipts.', 'routes': []}
    try:
        client.call('capabilities.browse')
        for version in VERSIONS:
            provider, revision = context(client, version, '/provider')
            materials, _ = context(client, version, '/materials', revision)
            cases, examples = materials['development']['cases'], materials['examples']
            execute = version in VERSIONS
            row = {'version': version, 'mode': 'native' if execute else 'host-only', 'cases': []}
            report['routes'].append(row)
            draft = client.call('create_draft', provider=provider, name=version+' migration')
            task = client.call('create_task', objective='Reuse the published '+version+' procedure', allowed_providers=[provider],
                               budget={'maxAttempts': len(cases), 'maxElapsedSeconds': 300})
            task_revision = 0
            for case in cases:
                example = next(e for e in examples if e['id'] == case['example'])
                document = example_document(example, repository)
                draft = client.call('edit_draft', document_id=draft['document'], expected_revision=draft['revision'], source=json.dumps(document))
                edits = copy.deepcopy(case.get('edits', []))
                for pointer, reference in case.get('resources', {}).items():
                    path = (repository/reference).resolve()
                    assert path.is_relative_to(repository) and path.is_file()
                    edits.append({'op':'replace', 'path':pointer, 'value':str(path)})
                if edits:
                    draft = client.call('patch_draft', document_id=draft['document'], expected_revision=draft['revision'], edits=edits)
                plan = client.call('plan_draft', task_id=task['id'], expected_revision=task_revision,
                                   document_id=draft['document'], draft_revision=draft['revision'])
                task_revision = plan['revision']
                observation = client.call('observe', plan_id=plan['id'], section='document')
                assert observation['mode'] == 'value'
                result = {'case':case['id'], 'plan':plan['id']}
                if execute:
                    job = client.call('execute', plan_id=plan['id'], expected_revision=task_revision)
                    status = client.wait(job)
                    assert status['status']=='succeeded', client.call('observe',job_id=job['id'],section='fault')
                    verification = client.call('verify',job_id=job['id'])
                    assert verification['value']['verified']
                    resources = client.call('observe',job_id=job['id'],section='resources')['value']
                    assert resources
                    samples=[]
                    for resource in resources:
                        sample=client.call('resource',resource_id=resource['id'],length=1024)
                        assert 0<sample['returnedBytes']<=1024
                        samples.append({'kind':resource['kind'],'bytes':sample['returnedBytes'],'sha256':resource['sha256']})
                    result.update(job=job['id'],verification=verification['value'],samples=samples)
                row['cases'].append(result)
            invalid=next(e for e in examples if e.get('expect')=='invalid')
            rejected=client.request('plan',task_id=task['id'],expected_revision=task_revision,document=example_document(invalid,repository))
            assert not rejected['ok'] and rejected['fault']['code']==invalid['fault'],rejected
            row['invalidFault']=rejected['fault']['code']
        report['verified']=True
    finally:
        client.close()
        report['transport']={'requests':len(client.records),'responseBytes':sum(r['responseBytes'] for r in client.records),
            'contextRequests':sum(r['method']=='adaptor_context' for r in client.records),
            'contextBytes':sum(r['responseBytes'] for r in client.records if r['method']=='adaptor_context'),
            'contextMemberWalks':getattr(client,'context_member_walks',0),'records':client.records}
        (root/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'verified':report['verified'],'routes':len(report['routes']),
                      'requests':len(client.records)},indent=2))


if __name__=='__main__':
    main()
