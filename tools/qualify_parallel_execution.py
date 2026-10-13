#!/usr/bin/env python3
"""Bounded native acceptance: timings, equivalence, and failed-worker recovery."""
import argparse
import copy
import json
from pathlib import Path
import statistics
from unittest.mock import patch
from schemaxis.artifacts import atomic_json
from schemaxis.parallel import execute, verify, run_native


def semantics(result):
    values = []
    for job in result['jobs']:
        receipt = json.loads((Path(job['directory'])/'verification.json').read_text())
        values.append({'id': job['id'], 'timeIndices': job['timeIndices'],
                       'states': [{'visit': s['visit'], 'effective': s['effective'], 'observations': s['observations']}
                                  for s in receipt['states']],
                       'artifacts': [{'identity': a['identity'], 'dataDigest': a.get('dataDigest'), 'sha256': a['sha256']}
                                     for a in receipt['artifacts']]})
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--paraview-root', required=True)
    parser.add_argument('--output-directory', required=True)
    args = parser.parse_args()
    root = Path(args.output_directory).absolute()
    root.mkdir(parents=True, exist_ok=False)
    document = json.loads(Path('examples/schemaxis/parallel-timesteps.json').read_text())
    document['operations'][0]['execution']['timeChunkSize'] = 1
    results, baseline = [], None
    for index, workers in enumerate([1, 2, 2, 1]):
        authored = copy.deepcopy(document)
        authored['execution']['maxWorkers'] = workers
        target = root/f'benchmark-{index}-{workers}-workers'
        result = execute(authored, target, roots=[args.paraview_root])
        verify(target)
        observed = semantics(result)
        if baseline is None:
            baseline = observed
        assert observed == baseline, 'parallel results differ from serial baseline'
        metrics = [json.loads(path.read_text()) for path in target.rglob('*.metrics.json')]
        results.append({'workers': workers, 'seconds': result['seconds'],
                        'directory': str(target), 'nativeDispatchSeconds': sum(m['seconds'] for m in metrics),
                        'maxSampledWorkerRssBytes': max(m.get('sampledPeakTreeRssBytes', m['sampledPeakGroupRssBytes']) for m in metrics)})
    recovery = copy.deepcopy(document)
    recovery['execution']['maxWorkers'] = 1
    target = root/'recovery'
    calls = 0
    def fail_second(*arguments, **keywords):
        nonlocal calls
        calls += 1
        if calls == 2:
            # Actual native success followed by a lost worker completion: keep evidence but no job receipt.
            run_native(*arguments, **keywords)
            raise RuntimeError('qualification: deliberate worker failure before completion receipt')
        return run_native(*arguments, **keywords)
    with patch('schemaxis.parallel.run_native', side_effect=fail_second):
        try:
            execute(recovery, target, roots=[args.paraview_root])
        except RuntimeError as error:
            assert 'deliberate worker failure' in str(error)
        else:
            raise AssertionError('expected worker failure')
    resumed = execute(recovery, target, roots=[args.paraview_root], resume=True)
    verify(target)
    assert resumed['jobs'][0]['reused'] and not resumed['jobs'][1]['reused']
    assert semantics(resumed) == baseline
    assert (target/'surfaces/batch-1/attempt-0001').exists()
    assert (target/'surfaces/batch-1/attempt-0002').exists()
    serial = statistics.median(r['seconds'] for r in results if r['workers'] == 1)
    parallel = statistics.median(r['seconds'] for r in results if r['workers'] == 2)
    summary = {'verified': True, 'runs': results, 'medianSpeedup': serial/parallel,
               'serialMedianSeconds': serial, 'parallelMedianSeconds': parallel,
               'equivalence': 'exact geometry digests, hashes, effective values and observations',
               'recovery': {'verified': True, 'reusedJobs': sum(j['reused'] for j in resumed['jobs']),
                            'directory': str(target)}}
    atomic_json(root/'qualification.json', summary)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
