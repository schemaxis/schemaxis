#!/usr/bin/env python3
"""GDAL zonalSummary through the public local agent transport: discover, author, edit, plan, run, inspect and verify.

This is a deterministic client, not an evaluation of a language model. Every expected value is hand-stated from the
elevation fixture's pixel values (see tools/qualify_gdal_fixtures.py), never read from native or product output.
"""
import argparse
import json
import math
from pathlib import Path

from qualify_agent_service import Client
from qualify_adaptor_growth import context, example_document

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'schemaxis.gdal/1'
HEADER = ['zone', 'valid', 'missing', 'coverage', 'minimum', 'maximum', 'sum', 'mean']
# Fixture rows (6 x 5, Int16, -9999 is nodata):
#   10 11 12 13 14 15 / 20 21 -- 23 24 25 / 30 31 32 33 34 35 / 40 41 42 43 -- 45 / 50 51 52 53 54 55
# Expected CSV rows, hand-computed: [zone, valid, missing, coverage, minimum, maximum, sum, mean].
BASELINE = [['007', 5, 1, 5/6, 11, 23, 80, 16], ['=1+2', 0, 1, 0, None, None, None, None],
            ['north', 6, 0, 1, 10, 15, 75, 12.5], ['south', 11, 1, 11/12, 40, 55, 526, 526/11]]
TALLER = [BASELINE[0], BASELINE[1], ['north', 11, 1, 11/12, 10, 25, 188, 188/11], BASELINE[3]]
EAST = [*BASELINE, ['east', 9, 1, 0.9, 14, 55, 301, 301/9]]
NULL = '\\N'


def snapshot_rows(client, resource, limit):
    """Page the revision-bound table snapshot; every page must carry the same revision and a consistent cursor."""
    snapshot = client.call('snapshot_resource', resource_id=resource['id'], kind='table')
    rows, offset, pages = [], 0, 0
    while offset is not None:
        page = client.call('inspect_snapshot', resource_id=snapshot['id'], revision=snapshot['revision'], view='table', offset=offset, limit=limit)
        assert page['revision'] == snapshot['revision'] and not page['stale'] and page['columns'] == HEADER, page
        assert page['offset'] == offset and len(page['rows']) <= limit, page
        rows.extend(page['rows']); offset = page['nextOffset']; pages += 1
    assert [r['row'] for r in rows] == list(range(len(rows))) and len(rows) == page['totalRows']
    return snapshot, [r['values'] for r in rows], pages


def same(row, expected):
    """Hand-stated integers must appear as exactly their canonical integer text (never a bool, never a tolerance); only non-integral literals use a tight relative tolerance."""
    assert row[0] == expected[0], (row, expected)
    for text, value in zip(row[1:], expected[1:]):
        if value is None:
            assert text == NULL, (row, expected)
        elif type(value) is int:
            assert text == str(value), (row, expected)
        else:
            assert type(value) is float and math.isclose(float(text), value, rel_tol=1e-13, abs_tol=0), (row, expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gdal', type=Path, required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    root = args.output_directory.resolve(); root.mkdir(parents=True, exist_ok=False)
    config = root/'config.json'; config.write_text(json.dumps({'version': 1, 'locations': {'gdal': str(args.gdal.absolute())}}))
    report = {'verified': False, 'scope': 'Deterministic public agent-service loop for GDAL zonalSummary; serial local native GDAL only, no model evaluation.', 'cases': []}
    client = Client(root/'workspace', config=config)
    try:
        client.call('methods')
        # Discovery: the declared operation is found by a natural request and exposes its closed schema before authoring.
        found = client.call('capabilities.search', query='mean per zone')
        assert 'zonalSummary' in json.dumps(found), found
        provider, stamp = context(client, VERSION, '/provider')
        materials, _ = context(client, VERSION, '/materials', stamp)
        guidance = materials['context']
        assert all(guidance[k] for k in ('purpose', 'assumptions', 'constraints', 'inspection', 'recovery')) and 'zonalSummary' in guidance['purpose']
        cases = {c['id']: c for c in materials['development']['cases']}
        examples = {e['id']: e for e in materials['examples']}
        assert {'zonal', 'zonal-taller-north', 'zonal-added-east', 'zonal-geographic'} <= set(cases), sorted(cases)
        task = client.call('create_task', objective='Author, edit and verify rectangular raster zone summaries', allowed_providers=[provider],
                          budget={'maxAttempts': 12, 'maxElapsedSeconds': 600})
        draft = client.call('create_draft', provider=provider, name='Zonal summary'); revision = 0
        state = {'revision': 0, 'draft': draft}

        def author(case_id, edits=()):
            case = cases[case_id]; document = example_document(examples[case['example']], ROOT)
            state['draft'] = client.call('edit_draft', document_id=state['draft']['document'], expected_revision=state['draft']['revision'], source=json.dumps(document, indent=2)+'\n')
            patches = [*case.get('edits', []), *edits]
            for pointer, reference in case.get('resources', {}).items():
                path = (ROOT/reference).resolve(); assert path.is_relative_to(ROOT) and path.is_file()
                patches.append({'op': 'replace', 'path': pointer, 'value': str(path)})
            if patches:
                state['draft'] = client.call('patch_draft', document_id=state['draft']['document'], expected_revision=state['draft']['revision'], edits=patches)
            return case

        def plan(case_id=None):
            planned = client.call('plan_draft', task_id=task['id'], expected_revision=state['revision'], document_id=state['draft']['document'], draft_revision=state['draft']['revision'])
            state['revision'] = planned['revision']
            return planned

        def run(planned):
            job = client.call('execute', plan_id=planned['id'], expected_revision=state['revision']); return job, client.wait(job)

        def check_json(job, resources, case):
            by_name = {Path(r['file']).name: r for r in resources}
            observed = []
            for check in case['checks']:
                value = client.call('inspect_resource', resource_id=by_name[check['file']]['id'], pointer=check['pointer'])['value']
                expected = check['expected']
                if isinstance(expected, (int, float)) and not isinstance(expected, bool):
                    assert math.isclose(value, expected, rel_tol=check.get('relative', 0), abs_tol=check.get('absolute', 0)), (case['id'], check, value)
                else:
                    assert value == expected, (case['id'], check, value)
                observed.append(check['pointer'])
            return observed

        # Baseline plus meaningful edits, each from the adaptor-published editable case and checked against hand-stated literals.
        for case_id, rows in (('zonal', BASELINE), ('zonal-taller-north', TALLER), ('zonal-added-east', EAST)):
            case = author(case_id)
            planned = plan(); client.call('observe', plan_id=planned['id'], section='plan')
            job, status = run(planned)
            assert status['status'] == 'succeeded', client.call('observe', job_id=job['id'], section='fault')
            verification = client.call('verify', job_id=job['id'])['value']; assert verification['verified'], verification
            resources = client.call('observe', job_id=job['id'], section='resources')['value']
            observed = check_json(job, resources, case)
            table = next(r for r in resources if Path(r['file']).name == 'zones-summary.csv')
            snapshot, values, pages = snapshot_rows(client, table, limit=2)
            assert len(values) == len(rows) and pages == math.ceil(len(rows)/2), (case_id, len(values), pages)
            for row, expected in zip(values, rows):
                same(row, expected)
            if case_id == 'zonal':
                # A wrong snapshot revision is refused with the public fault; the genuine revision still pages afterwards.
                wrong = client.request('inspect_snapshot', resource_id=snapshot['id'], revision='0'*64, view='table', offset=0, limit=2)
                assert not wrong['ok'] and (wrong['fault']['code'], wrong['fault']['location']) == ('STALE_RESOURCE', '$'), wrong
                assert client.call('inspect_snapshot', resource_id=snapshot['id'], revision=snapshot['revision'], view='table', offset=0, limit=2)['revision'] == snapshot['revision']
                report['wrongRevisionSnapshot'] = {'fault': wrong['fault']['code'], 'location': wrong['fault']['location']}
            metadata = client.call('inspect_resource_metadata', resource_id=table['id'], limit=5)
            report['cases'].append({'case': case_id, 'job': job['id'], 'zones': [r[0] for r in values], 'csvPages': pages, 'jsonPointersChecked': len(observed), 'snapshotRevision': snapshot['revision'],
                                    'metadataPageKeys': sorted(metadata) if isinstance(metadata, dict) else None})
        # A failed native acceptance is a failed job with a structured fault and no verified publication.
        author('zonal', [{'op': 'replace', 'path': '/missing', 'value': 'refuse'}])
        planned = plan(); job, status = run(planned)
        assert status['status'] == 'failed', status
        fault = client.call('observe', job_id=job['id'], section='fault')['value']
        assert (fault['code'], fault['location']) == ('ZONE_MISSING_VALUES', '$.zones[0]'), fault
        assert not client.call('observe', job_id=job['id'], section='resources')['value']
        report['refusedMissing'] = {'fault': fault['code'], 'location': fault.get('location'), 'publications': 0}
        # Stale plan: an edit after planning blocks execution of the captured plan.
        author('zonal'); stale = plan()
        state['draft'] = client.call('patch_draft', document_id=state['draft']['document'], expected_revision=state['draft']['revision'], edits=[{'op': 'replace', 'path': '/zones/0/id', 'value': 'changed'}])
        refused = client.request('execute', plan_id=stale['id'], expected_revision=state['revision'])
        assert not refused['ok'] and refused['fault']['code'] == 'STALE_REVISION' and refused['fault']['location'] == '$', refused
        report['stalePlan'] = {'fault': refused['fault']['code'], 'location': refused['fault']['location']}
        # Invalid authored input is rejected at planning, before any native process.
        invalid = examples['zonal-duplicate-id-invalid']
        rejected = client.request('plan', task_id=task['id'], expected_revision=state['revision'], document=example_document(invalid, ROOT))
        assert not rejected['ok'] and (rejected['fault']['code'], rejected['fault']['location']) == ('INVALID_ZONE', '$.zones[1]') and invalid['fault'] == 'INVALID_ZONE', rejected
        report['invalidPlan'] = {'fault': rejected['fault']['code'], 'location': rejected['fault'].get('location')}
        absent = client.request('adaptor_context', version='schemaxis.unregistered/1')
        assert not absent['ok'] and absent['fault']['code'] == 'UNSUPPORTED_VERSION'
        report['verified'] = True
    finally:
        records = client.records
        try: client.close()
        finally:
            report['transport'] = {'requests': len(records), 'responseBytes': sum(r['responseBytes'] for r in records), 'largestResponseBytes': max((r['responseBytes'] for r in records), default=0),
                                   'rejectedRequests': sum(not r['ok'] for r in records)}
            (root/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
