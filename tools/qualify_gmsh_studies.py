#!/usr/bin/env python3
"""Native mesh intent, feedback, refusal, tamper and cross-adaptor acceptance."""
import argparse
import copy
import json
import math
from pathlib import Path

from schemaxis.adaptors import registry
from schemaxis.adaptors.gmsh import mesh, refinement
from schemaxis.adaptor_delivery import source_digest
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis import workflow
from schemaxis.tabular import read_csv

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    locations = json.loads(args.config.read_text())['locations']
    output = args.output_directory.absolute(); output.mkdir(parents=True, exist_ok=False)
    report = {'verified': False, 'scope': 'Serial Gmsh meshing intent and bounded feedback; Octave value handoff. No solver convergence or optimum claim.',
              'sourceDigest': source_digest('gmsh'), 'checks': {}}
    def example(name): return json.loads((ROOT/'examples/schemaxis'/name).read_text())
    def run(name, document):
        target = output/name
        registry.run(document, target, locations=locations, timeout=180)
        report['checks'][name] = registry.verify(target)
        print(name, report['checks'][name], flush=True)
        return target
    def rejected(name, document, reason):
        target = output/name
        try: registry.run(document, target, locations=locations, timeout=180)
        except SchemaxisError as error: assert error.fault.code == 'STUDY_REQUIREMENTS_NOT_MET', error.to_dict()
        else: raise AssertionError('unmet study published success')
        verified = refinement.verify(target, require_acceptance=False)
        assert not verified['accepted'] and verified['reason'] == reason, verified
        receipt = json.loads((target/'verification.json').read_text())
        assert all(a['kind'] == 'text' and Path(a['file']).parent == target for a in receipt['artifacts'])
        report['checks'][name] = verified
        print(name, verified, flush=True)
    try:
        baseline = run('uniform', example('gmsh-face-groups.json'))
        local = run('boundary-sizing', example('gmsh-boundary-sizing.json'))
        def boundary_max(path, name):
            summary = json.loads((path/'mesh-summary.json').read_text())
            return next(b['maximumEdgeLength']['maximum'] for b in summary['quality']['boundaries'] if b['name'] == name)
        assert boundary_max(local, 'fixed') < .6*boundary_max(baseline, 'fixed')
        assert boundary_max(local, 'loaded') > 1.5*boundary_max(local, 'fixed')
        report['boundaryResolution'] = {'uniformFixed': boundary_max(baseline,'fixed'),
            'localFixed': boundary_max(local,'fixed'), 'localLoaded': boundary_max(local,'loaded')}

        refined = run('refinement', example('gmsh-refinement.json'))
        summary = json.loads((refined/'study-summary.json').read_text())
        assert 2 <= len(summary['attempts']) <= 4 and summary['accepted']
        assert all(not a['decision']['accepted'] for a in summary['attempts'][:-1])
        chosen = refined/summary['attempts'][-1]['directory']
        data = mesh.read(chosen/'result.msh')
        longest = max(math.dist(data['nodes'][nodes[i]],data['nodes'][nodes[j]])
                      for dim,_,nodes in data['cells'] if dim == 3 for i in range(4) for j in range(i+1,4))
        assert longest <= 3 and sum(dim==3 for dim,_,_ in data['cells']) <= 20000
        report['independentSelectedMaximumEdgeLength'] = longest
        run('boundary-refinement', example('gmsh-boundary-refinement.json'))

        # Analytic visits prepare references/expressions before each feedback
        # policy. Each visit must retain its own accepted mesh and history.
        analytic = run('analytic-refinement', example('gmsh-analytic-refinement.json'))
        states = json.loads((analytic/'result.json').read_text())['states']
        assert len(states) == 2
        for state, requested, attempts in zip(states, (4.5, 3), (2, 3)):
            child = analytic/state['directory']
            study = json.loads((child/'study-summary.json').read_text())
            assert study['accepted'] and len(study['attempts']) == attempts
            assert study['policy']['requirements']['maximumEdgeLength'] == requested
            assert study['attempts'][-1]['observation']['quality']['maximumEdgeLength']['maximum'] <= requested
        report['checks']['analytic-refinement']['attemptsPerState'] = [2, 3]

        # Challenge declarations, decisions, rejected attempts and the human report.
        report['corruptionFaults'] = []
        for relative in ('authored.json', 'result.json', 'study-summary.json', 'study.html',
                         'attempt-00000/mesh-summary.json', 'attempt-00000/volume.vtu'):
            path = refined/relative; original = path.read_bytes()
            try:
                path.write_bytes(b'{}' if path.suffix == '.json' else b'changed')
                try: registry.verify(refined)
                except SchemaxisError as error: report['corruptionFaults'].append({'file': relative, 'code': error.fault.code})
                else: raise AssertionError('corruption accepted: '+relative)
            finally: path.write_bytes(original)
        registry.verify(refined)
        limited = example('gmsh-refinement.json'); limited['refinement']['maxIterations'] = 1
        rejected('iteration-limit', limited, 'iteration_limit')
        limited = example('gmsh-refinement.json'); limited['refinement']['maxTetrahedra'] = 1
        rejected('cell-budget', limited, 'cell_budget_exceeded')
        limited = example('gmsh-refinement.json'); limited['refinement']['minimumSize'] = 3
        rejected('size-floor', limited, 'parameter_limit')

        # No consumer may run after a producer exhausts its requirements.
        rejected_workflow = {'version':'schemaxis.workflow/1','operations':[{'id':'mesh','document':limited},
            {'id':'measurement','document':{'version':'schemaxis.octave/1','nodes':[{'id':'samples','filter':'samples',
                'options':{'x':[0,1],'y':[{'$value':'mesh','artifact':3,'path':'/volume'},1]}}],'outputs':['samples']}}]}
        try: workflow.execute(rejected_workflow, output/'rejected-workflow', locations=locations, timeout=180)
        except SchemaxisError: pass
        else: raise AssertionError('unmet producer was accepted by workflow')
        failed = json.loads((output/'rejected-workflow'/'result.json').read_text())
        assert not any(job.get('status') == 'succeeded' for job in failed['jobs'])
        accepted_workflow = copy.deepcopy(rejected_workflow)
        accepted_workflow['operations'][0]['document'] = example('gmsh-refinement.json')
        accepted_workflow['operations'][1]['document']['nodes'][0]['options']['y'][0]['path'] = '/quality/maximumEdgeLength/maximum'
        target = output/'accepted-workflow'
        workflow.execute(accepted_workflow, target, locations=locations, timeout=180)
        report['checks']['accepted-workflow'] = workflow.verify(target)
        saved = json.loads((target/'result.json').read_text())
        producer = Path(saved['jobs'][0]['directory'])
        receipt = json.loads((producer/'verification.json').read_text())
        selected = json.loads(Path(receipt['artifacts'][3]['file']).read_text())['quality']['maximumEdgeLength']['maximum']
        consumer = Path(saved['jobs'][1]['directory'])
        receipt = json.loads((consumer/'verification.json').read_text())
        table = read_csv(next(a['file'] for a in receipt['artifacts'] if a['kind']=='table'))
        assert math.isclose(table['rows'][0][1], selected, rel_tol=1e-12)
        saved = workflow.execute(accepted_workflow, target, locations=locations, timeout=180, resume=True)
        assert all(job['reused'] for job in saved['jobs'])
        workflow.verify(target)
        report['checks']['accepted-workflow']['reusedJobs'] = len(saved['jobs'])
        assert report['sourceDigest'] == source_digest('gmsh'), 'source changed during qualification'
        report['verified'] = True
    finally:
        atomic_json(output/'report.json', report)
    print('All Gmsh study checks passed.', flush=True)


if __name__ == '__main__': main()
