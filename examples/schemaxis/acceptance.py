# Copyright (C) 2026 David L F Gaden
"""Repeatable schemaxis acceptance. Run with PYTHONPATH=src; outputs must be new.

Each native run retains source, input, receipts, exact runtime and artifacts.
The final acceptance receipt is written only after positive and negative checks.
"""
import argparse
import copy
import csv
import json
from pathlib import Path
import sys
from schemaxis.core.faults import SchemaxisError
from schemaxis.job import run, atomic_json


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', required=True)
    parser.add_argument('--paraview-root', required=True)
    parser.add_argument('--case', action='append', default=[])
    args = parser.parse_args()
    output = Path(args.output_directory).absolute()
    output.mkdir()
    examples = Path(__file__).parent
    report = {'status': 'incomplete', 'verified': False, 'runs': [], 'failures': [], 'checks': []}
    save = lambda: atomic_json(output / 'acceptance.json', report)
    save()

    def execute(name, document):
        print('Running ' + name, flush=True)
        result = run(document, output / name, roots=[args.paraview_root], timeout=300)
        report['runs'].append({'name': name, **result})
        save()
        return json.loads((output / name / 'verification.json').read_text())

    def negative(name, document, code, **options):
        print('Expected failure ' + name, flush=True)
        try:
            run(document, output / name, roots=[args.paraview_root], **options)
        except SchemaxisError as error:
            check(error.fault.code == code, f'{name}: expected {code}, got {error.fault.code}')
            report['failures'].append({'name': name, 'expected': code, 'observed': error.fault.code})
            save()
        else:
            raise AssertionError(name + ' unexpectedly succeeded')

    try:
        coverage_document = json.loads((examples / 'extended-coverage.json').read_text())
        coverage = execute('filters', coverage_document)
        measurements = [a for a in coverage['artifacts'] if a['identity']['kind'] == 'measurement']
        with open(measurements[0]['file'], newline='') as stream:
            row = next(csv.DictReader(stream))
        check(abs(float(row['velocity[0]']) - 400) < 1e-8, 'unit-vector area integral must equal 400')
        check(abs(float(row['positionX[0]'])) < 1e-8, 'symmetric linear-field area integral must be zero')
        with open(measurements[1]['file'], newline='') as stream:
            rows = list(csv.DictReader(stream))
        check(len(rows) == 9, 'probe must contain nine samples')
        check(all(abs(float(row['positionX[0]']) - (-4 + i)) < 1e-8 for i, row in enumerate(rows)),
              'linear field samples must match their x coordinates')
        report['checks'].extend(['analytic unit-vector integral: 400', 'odd linear-field integral: 0',
                                 'nine linear-field samples: -4 through 4'])
        branch_document = json.loads((examples / 'branching.json').read_text())
        branch_document['scenes'][0]['visible']['iso']['colour'] = 'xkcd:orange'
        branching = execute('branching', branch_document)
        check(len(branching['artifacts']) == 24, 'branching publication count')
        check(all('unused' not in s['proxyIds'] for s in branching['states']), 'unused branch must be absent')
        check([s['visit']['indices'] for s in branching['states']] == [
            {'level': 0, 'height': 0}, {'level': 0, 'height': 1},
            {'level': 1, 'height': 0}, {'level': 1, 'height': 1}], 'odometer order')
        for state in branching['states']:
            height = state['effective']['cut']['origin'][2]
            check(all(abs(state['observations']['cut']['bounds'][i] - height) < 1e-8 for i in (4, 5)),
                  'slice must lie on the requested plane')
            level = state['effective']['iso']['values'][0]
            check(all(abs(state['observations']['iso']['bounds'][i] - level) < 1e-8 for i in (0, 1)),
                  'linear-field isosurface must lie at requested x')
        report['checks'].extend(['independent odometer carry', 'slice plane geometry', 'analytic isosurface location',
                                 'unused branch absent', 'geometry not multiplied by camera/appearance'])
        sample = execute('runtime-sample', json.loads((examples / 'runtime-sample.json').read_text()))
        check([s['effective']['sampledSphere']['radius'] for s in sample['states']] == [1, 2], 'runtime field samples')
        report['checks'].append('hidden runtime field samples determine radii 1 and 2')
        execute('gltf', json.loads((examples / 'scene-gltf.json').read_text()))
        switching = copy.deepcopy(branch_document)
        switching['axes'][0]['values'] = [[0, 0, 0]]
        switching['axes'][1]['values'] = [[2]]
        switching['scenes'] = [{'id': 'cut', 'geometry': ['cut']}, {'id': 'source', 'geometry': ['source']},
                               {'id': 'cutAgain', 'geometry': ['cut']}]
        switched = execute('scene-switching', switching)
        check(len({s['proxyIds']['source'] for s in switched['states']}) == 1, 'shared source must survive scene switches')
        check(switched['states'][0]['proxyIds']['cut'] != switched['states'][2]['proxyIds']['cut'],
              'pruned filter must be recreated when selected again')
        report['checks'].append('native scene switching preserves shared source and retires unused filters')
        for i, case in enumerate(args.case):
            foam = json.loads((examples / 'foam.json').read_text())
            foam['nodes'][0]['options']['file'] = str(Path(case).absolute())
            result = execute(f'foam-{i}', foam)
            check(len(result['artifacts']) == 12, 'real-case output count')
            check(len({s['visit']['time'] for s in result['states']}) == 2, 'latest two times must be selected')
            check(result['states'][0]['observations']['mesh']['cells'] > 100000, 'real case cell inventory')
        missing = copy.deepcopy(branch_document)
        missing['nodes'][4]['options']['field'] = ['POINTS', 'absent']
        negative('missing-field', missing, 'MISSING_FIELD')
        empty = copy.deepcopy(branch_document)
        empty['axes'][0]['values'] = [[0, 0, 1000]]
        negative('empty-slice', empty, 'EMPTY_GEOMETRY')
        cycle = copy.deepcopy(branch_document)
        cycle['nodes'][0]['options'] = {'centre': {'$observe': 'cut', 'path': ['bounds']}}
        negative('cycle', cycle, 'PIPELINE_CYCLE')
        bad = copy.deepcopy(branch_document)
        bad['nodes'][3]['options']['normal'] = [0, 0, 0]
        negative('zero-normal', bad, 'DEGENERATE_DIRECTION')
        limit = copy.deepcopy(branch_document)
        limit['maxPublications'] = 1
        negative('expansion', limit, 'EXPANSION_TOO_LARGE')
        occupied = output / 'existing'
        occupied.mkdir()
        negative('existing', branch_document, 'OUTPUT_EXISTS')
        negative('timeout', branch_document, 'RUNNER_TIMED_OUT', timeout=0.001)
        receipt = json.loads((output / 'timeout/verification.json').read_text())
        check(not receipt.get('verified') and receipt['status'] != 'succeeded', 'timeout must retain incomplete evidence')
        report.update(status='succeeded', verified=True)
        save()
        print(json.dumps({'verified': True, 'runs': len(report['runs']), 'failures': len(report['failures']),
                          'checks': len(report['checks']), 'receipt': str(output / 'acceptance.json')}, indent=2))
    except Exception as error:
        report.update(status='failed', verified=False, error=str(error))
        save()
        raise


if __name__ == '__main__':
    main()
