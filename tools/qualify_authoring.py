#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Native serial acceptance of shared source, console edits and agent plans."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
from qualify_agent_service import Client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    root = args.output_directory.resolve()
    root.mkdir(parents=True, exist_ok=False)
    workspace = root/'workspace'
    client = Client(workspace)
    records, report = [], {'scope': 'Two native serial FreeCAD executions; deterministic client, not a model evaluation.'}
    try:
        draft = client.call('create_draft', provider='freecad', name='Shared box')
        source = json.dumps({'version': 'schemaxis.freecad/1', 'nodes': [{'id': 'body', 'filter': 'box',
            'options': {'length': 20, 'width': 10, 'height': 5}}], 'output': 'body'}, indent=2)+'\n'
        draft = client.call('edit_draft', document_id=draft['document'], expected_revision=draft['revision'], source=source)
        task = client.call('create_task', objective='Shared authoring refinement to 1500 mm3', allowed_providers=['freecad'], budget={'maxAttempts': 2})
        plan = client.call('plan_draft', task_id=task['id'], expected_revision=0, document_id=draft['document'], draft_revision=draft['revision'])
        draft = client.call('edit_draft', document_id=draft['document'], expected_revision=draft['revision'], source='{\n"unfinished":')
        rejected = client.request('execute', plan_id=plan['id'], expected_revision=plan['revision'])
        assert rejected['fault']['code'] == 'STALE_REVISION'
        rejected = client.request('plan_draft', task_id=task['id'], expected_revision=plan['revision'], document_id=draft['document'], draft_revision=draft['revision'])
        assert rejected['fault']['code'] == 'INVALID_DRAFT'
        report['blockedInvalidDraft'] = draft
        report['task'] = task['id']
    finally:
        records.extend(client.records)
        client.close()
    # Recover the same invalid source under a new process owner.
    client = Client(workspace)
    try:
        recovered = client.call('draft', document_id=draft['document'], expected_revision=draft['revision'])
        assert recovered['source'] == draft['source'] and not recovered['valid']
        draft = client.call('undo_draft', document_id=draft['document'], expected_revision=draft['revision'])
        assert draft['source'] == source
        plan = client.call('plan_draft', task_id=task['id'], expected_revision=plan['revision'], document_id=draft['document'], draft_revision=draft['revision'])
        job = client.call('execute', plan_id=plan['id'], expected_revision=plan['revision'])
        job = client.wait(job)
        assert job['verified']
        verification = client.call('verify', job_id=job['id'])['value']
        assert math.isclose(verification['volumeMM3'], 1000, rel_tol=1e-8)
        report['first'] = {'job': job, 'verification': verification}
    finally:
        records.extend(client.records)
        client.close()
    # The real terminal console reopens and edits the very same document/history.
    result = subprocess.run([sys.executable, '-m', 'schemaxis', 'console', '--provider', 'freecad',
        '--workspace', str(workspace/'authoring'), '--command', 'set body height 7.5'], text=True, capture_output=True, check=True)
    (root/'console-edit.json').write_text(result.stdout)
    client = Client(workspace)
    try:
        drafts = client.call('list_drafts')['value']
        current = next(item for item in drafts if item['document'] == draft['document'])
        stale = client.request('execute', plan_id=plan['id'], expected_revision=plan['revision'])
        assert stale['fault']['code'] == 'STALE_REVISION'
        plan = client.call('plan_draft', task_id=task['id'], expected_revision=plan['revision'], document_id=current['document'], draft_revision=current['revision'])
        job = client.call('execute', plan_id=plan['id'], expected_revision=plan['revision'])
        job = client.wait(job)
        assert job['verified']
        verification = client.call('verify', job_id=job['id'])['value']
        assert math.isclose(verification['volumeMM3'], 1500, rel_tol=1e-8)
        assert client.call('task', task_id=task['id'])['attempts'] == 2
        report['refined'] = {'job': job, 'verification': verification}
        report['verified'] = True
    finally:
        records.extend(client.records)
        client.close()
    report['transport'] = {'requests': len(records), 'rejectedRequests': sum(not r['ok'] for r in records),
                           'responseBytes': sum(r['responseBytes'] for r in records),
                           'largestResponseBytes': max(r['responseBytes'] for r in records)}
    (root/'requests.json').write_text(json.dumps(records, indent=2)+'\n')
    (root/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
