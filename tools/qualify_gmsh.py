#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Gmsh native kit, FreeCAD/ParaView handoffs and public-context authoring proof.

Uses ordinary configured runtimes. No missing-runtime skip is a successful result.
The public loop is deterministic, not an autonomous-model evaluation.
"""
import argparse
import copy
import json
import math
import os
from pathlib import Path
import subprocess

from schemaxis.adaptor_conformance import qualify
from schemaxis.adaptors import registry
from schemaxis.configuration import locations
from schemaxis.core.faults import SchemaxisError
from schemaxis import workflow
from qualify_agent_service import Client
from qualify_adaptor_growth import context, example_document

ROOT = Path(__file__).resolve().parents[1]


def public_loop(directory, report):
    client = Client(directory)
    try:
        client.call('capabilities.browse')
        version = 'schemaxis.gmsh/1'
        provider, revision = context(client, version, '/provider')
        materials, _ = context(client, version, '/materials', revision)
        cases = materials['development']['cases']
        task = client.call('create_task',objective='Author and refine an independently checked tetrahedral box mesh',
                          allowed_providers=[provider],budget={'maxAttempts':len(cases),'maxElapsedSeconds':180})
        draft = client.call('create_draft',provider=provider,name='Meshed box')
        revision = 0
        report['publicCases'] = []
        for case in cases:
            example = next(e for e in materials['examples'] if e['id'] == case['example'])
            document = example_document(example, ROOT)
            draft = client.call('edit_draft',document_id=draft['document'],expected_revision=draft['revision'],source=json.dumps(document))
            if case['edits']:
                draft = client.call('patch_draft',document_id=draft['document'],expected_revision=draft['revision'],edits=case['edits'])
            plan = client.call('plan_draft',task_id=task['id'],expected_revision=revision,document_id=draft['document'],draft_revision=draft['revision'])
            revision = plan['revision']
            job = client.call('execute',plan_id=plan['id'],expected_revision=revision)
            assert client.wait(job)['status'] == 'succeeded', client.call('observe',job_id=job['id'],section='fault')
            assert client.call('verify',job_id=job['id'])['value']['verified']
            resources = client.call('observe',job_id=job['id'],section='resources')['value']
            summary = next(r for r in resources if Path(r['file']).name == 'mesh-summary.json')
            # Mesh quality diagnostics can exceed a bounded response. Inspect
            # the measurements used by this acceptance check explicitly.
            observed = {name: client.call('inspect_resource', resource_id=summary['id'],
                                          pointer='/'+name)['value']
                        for name in ('volume', 'units', 'minimumVolume')}
            expected = next(c['expected'] for c in case['checks'] if c['pointer'] == '/volume')
            assert math.isclose(observed['volume'],expected,abs_tol=1e-7)
            assert observed['units'] == 'mm' and observed['minimumVolume'] > 0
            report['publicCases'].append({'case':case['id'],'job':job['id'],'summary':observed})
        invalid = next(e for e in materials['examples'] if e.get('expect') == 'invalid')
        result = client.request('plan',task_id=task['id'],expected_revision=revision,document=example_document(invalid,ROOT))
        assert not result['ok'] and result['fault']['code'] == invalid['fault']
        report['publicInvalidFault'] = result['fault']['code']
    finally:
        client.close()
        report['transport'] = {'requests':len(client.records),'responseBytes':sum(r['responseBytes'] for r in client.records),'records':client.records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory',type=Path,required=True)
    parser.add_argument('--config',type=Path)
    args = parser.parse_args()
    if args.config: os.environ['SCHEMAXIS_CONFIG'] = str(args.config.resolve())
    directory = args.output_directory.resolve(); directory.mkdir(parents=True,exist_ok=False)
    report = {'verified':False,'workflows':[],'negative':[]}
    try:
        receipt = qualify('schemaxis.gmsh/1',directory/'native',native=True)
        assert receipt['verified'],receipt
        report['nativeReceipt'] = str(directory/'native/qualification.json')
        original = json.loads((ROOT/'examples/schemaxis/freecad-gmsh-faces-paraview.json').read_text())
        for height in (5,7):
            document = copy.deepcopy(original)
            document['operations'][0]['document']['nodes'][0]['options']['height'] = height
            target = directory/('handoff-'+str(height))
            result = workflow.execute(document,target,locations=locations(),timeout=180)
            assert workflow.verify(target)['verified']
            jobs = {j['operation']:j for j in result['jobs']}
            mesh_dir = Path(jobs['mesh']['directory'])
            summary = json.loads((mesh_dir/'mesh-summary.json').read_text())
            assert math.isclose(summary['volume'],20*10*height,abs_tol=1e-7)
            assert summary['bounds'] == [0,0,0,20,10,height]
            assert summary['groups'] == [{'dimension':2,'tag':2,'name':'outside'},
                {'dimension':2,'tag':3,'name':'fixed'},{'dimension':2,'tag':4,'name':'loaded'},
                {'dimension':3,'tag':1,'name':'part'}]
            for group in summary['boundaryGroups'][1:]:
                assert math.isclose(group['area'],10*height,abs_tol=1e-7)
                x = 0 if group['name'] == 'fixed' else 20
                assert group['bounds'] == [x,0,0,x,10,height]
            pv = json.loads((Path(jobs['inspect']['directory'])/'verification.json').read_text())
            observed = pv['states'][0]['observations']
            assert observed['volume']['cells'] == summary['tetrahedra']
            assert observed['surface']['cells'] == summary['triangles']
            assert observed['volume']['fields']['CELLS']['physicalTag']['range'] == [1,1]
            for metric in ('meanRatio', 'maximumEdgeLength', 'volume'):
                actual = observed['volume']['fields']['CELLS'][metric]['range']
                expected = [summary['quality'][metric][key] for key in ('minimum', 'maximum')]
                assert all(math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-8) for a,b in zip(actual,expected))
            assert observed['surface']['fields']['CELLS']['physicalTag']['range'] == [2,4]
            assert observed['volume']['bounds'] == [0,20,0,10,0,height]
            assert all(math.isclose(v,20*10*height,abs_tol=1e-7) for v in observed['integral']['fields']['CELLS']['Volume']['range'])
            resumed = workflow.execute(document,target,locations=locations(),timeout=180,resume=True)
            assert all(j['reused'] for j in resumed['jobs'] if j['operation'] in ('cad','mesh'))
            # The general ParaView file reader currently declines reuse.
            report['workflows'].append({'heightMM':height,'volumeMM3':summary['volume'],
                'tetrahedra':summary['tetrahedra'],'boundaryTriangles':summary['triangles'],
                'faceGroups':summary['boundaryGroups'],
                'cadAndMeshReused':True,'paraViewVolumeRange':observed['integral']['fields']['CELLS']['Volume']['range']})
            retained = mesh_dir/'source.step'; data = retained.read_bytes()
            try:
                retained.write_bytes(data+b'corrupt')
                try: registry.verify(mesh_dir)
                except SchemaxisError as error: assert error.fault.code == 'VERIFICATION_FAILED'
                else: raise AssertionError('corrupt captured STEP was accepted')
            finally: retained.write_bytes(data)
            assert registry.verify(mesh_dir)['verified']
        # Build a synthetic multi-solid STEP in the configured native environment.
        script = directory/'two-solids.py'
        script.write_text("import gmsh,sys\ngmsh.initialize([],readConfigFiles=False)\ngmsh.model.add('two')\ngmsh.model.occ.addBox(0,0,0,1,1,1)\ngmsh.model.occ.addBox(3,0,0,1,1,1)\ngmsh.model.occ.synchronize()\ngmsh.write(sys.argv[1])\ngmsh.finalize()\n")
        with (directory/'fixture.stdout').open('w') as out, (directory/'fixture.stderr').open('w') as err:
            subprocess.run([locations()['gmsh'],str(script),str(directory/'two.step')],check=True,timeout=30,stdout=out,stderr=err)
        document = copy.deepcopy(original['operations'][1]['document'])
        document['nodes'][0]['options']['file'] = str(directory/'two.step')
        try: registry.run(document,directory/'rejected-two-solids',locations=locations(),timeout=60)
        except SchemaxisError as error:
            assert error.fault.code == 'UNSUPPORTED_RESOURCE' and 'exactly one solid' in error.fault.message and error.fault.recovery,error
            report['negative'].append(error.fault.to_dict())
        else: raise AssertionError('multi-solid STEP was accepted')
        baseline = json.loads((ROOT/'examples/schemaxis/gmsh-face-groups.json').read_text())
        for label, groups in (
            ('empty',[{'name':'absent','axis':'x','coordinate':5}]),
            ('all',[{'name':axis+str(i),'axis':axis,'coordinate':x} for axis in 'xyz' for i,x in enumerate((0,10))]),
        ):
            bad = copy.deepcopy(baseline); bad['nodes'][1]['options']['faceGroups'] = groups
            try: registry.run(bad,directory/('rejected-'+label),locations=locations(),timeout=60)
            except SchemaxisError as error:
                assert error.fault.code == 'INVALID_SELECTION' and error.fault.recovery,error
                assert ('empty' if label == 'empty' else 'remainder') in error.fault.message,error
                report['negative'].append(error.fault.to_dict())
            else: raise AssertionError(label+' selection was accepted')
        public_loop(directory/'public',report)
        report['verified'] = True
    finally:
        (directory/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k != 'transport'},indent=2))


if __name__ == '__main__': main()
