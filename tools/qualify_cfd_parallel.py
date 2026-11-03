#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Qualify local native ParaView MPI on a user-supplied decomposed OpenFOAM case.

The case is read-only. All writes go under a fresh evidence directory. No cluster access.
"""
import argparse
import copy
import json
import math
from pathlib import Path
from schemaxis.parallel import execute, verify
from schemaxis.artifacts import atomic_json


def receipts(result):
    return [json.loads((Path(job['directory'])/'verification.json').read_text()) for job in result['jobs']]


def reduced(receipt):
    artifact = next(a for a in receipt['artifacts'] if a['identity']['kind'] == 'measurement')
    return dict(zip(artifact['columns'][1:], artifact['values'][0][1:]))


def comparison(left, right):
    if left.keys() != right.keys():
        raise AssertionError('reduction field membership differs')
    errors = {}
    for key in left:
        if not math.isclose(left[key], right[key], rel_tol=1e-8, abs_tol=1e-7):
            raise AssertionError(f'{key}: {left[key]} != {right[key]}')
        errors[key] = abs(left[key]-right[key])
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, required=True)
    parser.add_argument('--paraview-root', required=True)
    parser.add_argument('--mpiexec', required=True)
    parser.add_argument('--ranks', type=int, default=2)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=600)
    args = parser.parse_args()
    root = args.output_directory.absolute()
    root.mkdir(parents=True, exist_ok=False)
    workflow = json.loads(Path('examples/schemaxis/foam-native-parallel.json').read_text())
    workflow['execution']['cpus'] = args.ranks
    workflow['operations'][0]['document']['nodes'][0]['options']['file'] = str(args.case.absolute())
    for operation in workflow['operations']:
        operation['execution'].update(ranks=args.ranks, mpiexec=str(Path(args.mpiexec).absolute()))
    parallel = execute(workflow, root/'parallel', roots=[args.paraview_root], timeout=args.timeout)
    verify(root/'parallel')
    first, handoff = receipts(parallel)
    handoff_errors = comparison(reduced(first), reduced(handoff))
    geometry = [a for a in first['artifacts'] if a['identity']['kind'] == 'geometry']
    assert all(a['publicationMode'] == 'native-distributed' for a in geometry)
    assert all(a['verification']['gatheredGeometry'] is False for a in geometry)
    volume = geometry[0]
    partition_cells = [record.get('data', {}).get('cells', 0) for record in volume['verification']['before']]
    assert sum(n > 0 for n in partition_cells) == args.ranks, 'not all allocated ranks contributed volume cells'
    assert sum(partition_cells) == first['states'][0]['observations']['speed']['cells']
    # A serial baseline uses the same source, filters and reductions. Skip full-volume
    # publication to avoid the old serial verifier's bulk Python snapshot cost.
    serial_document = copy.deepcopy(workflow)
    serial_document['operations'] = serial_document['operations'][:1]
    serial_document['operations'][0]['execution'] = {'threads': 1, 'memoryMB': 12000}
    serial_document['operations'][0]['document']['scenes'][0]['geometry'] = ['cut']
    serial = execute(serial_document, root/'serial', roots=[args.paraview_root], timeout=args.timeout)
    verify(root/'serial')
    baseline = receipts(serial)[0]
    numerical_errors = comparison(reduced(baseline), reduced(first))
    for node in ('mesh', 'speed', 'cut'):
        a, b = baseline['states'][0]['observations'][node], first['states'][0]['observations'][node]
        assert a['cells'] == b['cells'], (node, a['cells'], b['cells'])
        assert all(math.isclose(x, y, rel_tol=1e-8, abs_tol=1e-7) for x, y in zip(a['bounds'], b['bounds']))
    metrics = {}
    for name, result in [('serial', serial), ('parallel', parallel)]:
        job = result['jobs'][0]
        metric = [json.loads(p.read_text()) for p in Path(job['directory']).glob('*.metrics.json')]
        metrics[name] = {'operationSeconds': job['seconds'],
            'peakSampledTreeRssBytes': max(m['sampledPeakTreeRssBytes'] for m in metric),
            'timings': receipts(result)[0]['states'][0].get('timings')}
    summary = {'verified': True, 'case': str(args.case.absolute()), 'ranks': args.ranks,
               'cells': sum(partition_cells), 'cellsPerRank': partition_cells,
               'nativeOutputs': [a['file'] for a in geometry],
               'noGeometryGather': True, 'handoffAbsoluteErrors': handoff_errors,
               'serialParallelAbsoluteErrors': numerical_errors,
               'tolerance': {'relative': 1e-8, 'absolute': 1e-7}, 'metrics': metrics,
               'timingScope': 'serial omits full-volume publication; not an equal-work speedup benchmark',
               'parallelDirectory': str(root/'parallel'), 'serialDirectory': str(root/'serial')}
    atomic_json(root/'qualification.json', summary)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
