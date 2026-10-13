#!/usr/bin/env python3
"""Exercise published delivery context through the public agent protocol.

A deterministic acceptance client, not a language-model evaluation. Native paths
come from ordinary local configuration. No implementation modules are imported.
"""
import argparse
import copy
import json
import math
from pathlib import Path
from qualify_agent_service import Client


def context(client, version, pointer, revision=None):
    """Follow exact bounded members without truncating context or bypassing budgets."""
    page = client.call('adaptor_context', version=version, pointer=pointer,
                       max_bytes=4096, revision=revision)
    stamp = page['revision']
    if page['mode'] == 'value':
        return page['value'], stamp
    client.context_member_walks = getattr(client, 'context_member_walks', 0) + 1
    result = {} if page['container'] == 'object' else []
    while True:
        for item in page['items']:
            value = item['value'] if 'value' in item else context(client, version, item['pointer'], stamp)[0]
            if isinstance(result, dict):
                result[item['key']] = value
            else:
                result.append(value)
        offset = page['page']['nextOffset']
        if offset is None:
            return result, stamp
        page = client.call('adaptor_context', version=version, pointer=pointer,
                           max_bytes=4096, revision=stamp, offset=offset)


def example_document(example, repository):
    if 'document' in example:
        return copy.deepcopy(example['document'])
    path = (repository/example['reference']).resolve()
    assert path.is_relative_to(repository), 'example reference escaped the repository'
    return json.loads(path.read_text())


def inspect(client, job, case, version):
    verification = client.call('verify', job_id=job['id'])['value']
    assert verification['verified']
    observations = []
    resources = client.call('observe', job_id=job['id'], section='resources')['value']
    for check in case['checks']:
        expected = check['expected']
        # These are acceptance observations for the named pilot cases, not routing
        # rules or a new observation contract. All reads use public service tools.
        if check['format'] == 'csv':
            resource = next(r for r in resources if Path(r['file']).name == check['file'])
            table = client.call('inspect_resource', resource_id=resource['id'])['value']
            observed = [[float(v) for v in row] for row in table['rows']]
            assert len(observed) == len(expected)
            assert all(len(a) == len(b) and all(math.isclose(x, y, rel_tol=check.get('relative', 0),
                abs_tol=check.get('absolute', 0)) for x, y in zip(a, b)) for a, b in zip(observed, expected))
        elif check['pointer'] == '/native/volume':
            observed = verification['volumeMM3']
            assert math.isclose(observed, expected, rel_tol=check['relative'], abs_tol=check['absolute'])
        elif check['pointer'] == '/jointCount':
            observed = verification['joints']
            assert observed == expected and verification['expectedDegreesOfFreedom'] == 0
        elif check['pointer'] == '/frames':
            observed = verification['frames']
            assert observed == expected
        elif check['pointer'] == '/fps':
            observed = verification['frames']/verification['duration']
            assert math.isclose(observed, expected)
        else:
            # Full per-case assertions (including native solids, assembly thickness
            # and decoded pixel errors) are exercised by adaptor conform --native.
            continue
        observations.append({'pointer': check['pointer'], 'observed': observed, 'expected': expected})
    assert observations, (version, case['id'])
    return {'case': case['id'], 'job': job['id'], 'verification': verification,
            'observations': observations, 'resources': len(resources)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--config', type=Path)
    args = parser.parse_args()
    root = args.output_directory.resolve()
    root.mkdir(parents=True, exist_ok=False)
    repository = Path(__file__).resolve().parents[1]
    report = {'verified': False, 'scope': 'Deterministic public protocol, published context and serial pilot cases; no model, MPI or exhaustive profile qualification.',
              'routes': [], 'negativeChecks': [], 'unexpectedRetries': 0}
    client = Client(root/'workspace', config=args.config)
    try:
        client.call('methods')
        client.call('capabilities.browse')
        for version in ('schemaxis.octave/1', 'schemaxis.freecad/1', 'schemaxis.freecad.assembly/1', 'schemaxis.ffmpeg/1'):
            provider, stamp = context(client, version, '/provider')
            materials, _ = context(client, version, '/materials', stamp)
            guidance, examples = materials['context'], materials['examples']
            cases, authoring = materials['development']['cases'], materials['development']['authoring']
            assert all(guidance[k] for k in ('purpose', 'assumptions', 'constraints', 'inspection', 'recovery'))
            route = {'version': version, 'contextRevision': stamp, 'authoring': authoring['model'], 'cases': []}
            report['routes'].append(route)
            draft = client.call('create_draft', provider=provider, name='Published '+version)
            task = client.call('create_task', objective='Execute and refine the published acceptance cases for '+version,
                               allowed_providers=[provider], budget={'maxAttempts': len(cases), 'maxElapsedSeconds': 300})
            revision = 0
            for case in cases:
                example = next(e for e in examples if e['id'] == case['example'])
                document = example_document(example, repository)
                draft = client.call('edit_draft', document_id=draft['document'], expected_revision=draft['revision'],
                                    source=json.dumps(document, indent=2)+'\n')
                edits = copy.deepcopy(case.get('edits', []))
                for pointer, reference in case.get('resources', {}).items():
                    path = (repository/reference).resolve()
                    assert path.is_relative_to(repository) and path.is_file()
                    edits.append({'op': 'replace', 'path': pointer, 'value': str(path)})
                if edits:
                    draft = client.call('patch_draft', document_id=draft['document'], expected_revision=draft['revision'], edits=edits)
                plan = client.call('plan_draft', task_id=task['id'], expected_revision=revision,
                                   document_id=draft['document'], draft_revision=draft['revision'])
                revision = plan['revision']
                client.call('observe', plan_id=plan['id'], section='plan')
                job = client.call('execute', plan_id=plan['id'], expected_revision=revision)
                status = client.wait(job)
                assert status['status'] == 'succeeded', client.call('observe', job_id=job['id'], section='fault')
                route['cases'].append(inspect(client, job, case, version))
            invalid = next(e for e in examples if e.get('expect') == 'invalid')
            rejected = client.request('plan', task_id=task['id'], expected_revision=revision,
                                      document=example_document(invalid, repository))
            assert not rejected['ok'] and rejected['fault']['code'] == invalid['fault'], rejected
            report['negativeChecks'].append({'version': version, 'invalidExample': invalid['id'], 'fault': rejected['fault']['code']})
        unavailable = client.request('adaptor_context', version='schemaxis.unregistered/1')
        assert not unavailable['ok'] and unavailable['fault']['code'] == 'UNSUPPORTED_VERSION', unavailable
        report['negativeChecks'].append({'unregisteredRoute': unavailable['fault']['code']})
    finally:
        client.close()
        report['context'] = {'budgetBytes': 4096, 'memberWalks': getattr(client, 'context_member_walks', 0),
            'requests': sum(r['method'] == 'adaptor_context' for r in client.records),
            'responseBytes': sum(r['responseBytes'] for r in client.records if r['method'] == 'adaptor_context'),
            'largestResponseBytes': max(r['responseBytes'] for r in client.records if r['method'] == 'adaptor_context')}
        report['transport'] = {'requests': len(client.records), 'responseBytes': sum(r['responseBytes'] for r in client.records),
            'largestResponseBytes': max((r['responseBytes'] for r in client.records), default=0),
            'rejectedRequests': sum(not r['ok'] for r in client.records), 'records': client.records}
        (root/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    # Availability is tested in a separate configuration, without changing the user's.
    config = root/'unavailable.json'
    config.write_text(json.dumps({'version': 1, 'locations': {'octave': str(root/'absent-octave')}}))
    absent = Client(root/'unavailable-workspace', config=config)
    try:
        examples, _ = context(absent, 'schemaxis.octave/1', '/materials/examples')
        example = next(e for e in examples if e.get('expect', 'valid') == 'valid')
        task = absent.call('create_task', objective='Check unavailable runtime recovery', allowed_providers=['octave'])
        plan = absent.call('plan', task_id=task['id'], expected_revision=0, document=example_document(example, repository))
        job = absent.call('execute', plan_id=plan['id'], expected_revision=plan['revision'])
        status = absent.wait(job)
        assert status['status'] == 'failed', status
        fault = absent.call('observe', job_id=job['id'], section='fault')['value']
        assert fault['code'] == 'INTERPRETER_NOT_FOUND', fault
        report['negativeChecks'].append({'unavailableRuntime': fault['code'], 'retained': True})
        report['verified'] = True
    finally:
        absent.close()
        report['unavailableTransport'] = absent.records
        (root/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('transport', 'unavailableTransport')}, indent=2))


if __name__ == '__main__':
    main()
