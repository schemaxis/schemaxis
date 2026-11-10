#!/usr/bin/env python3
"""Bounded real-Gmsh acceptance for primitives, cap budgets and meshing decisions."""
import argparse
import copy
import json
import math
from pathlib import Path
import subprocess

from schemaxis.adaptors.gmsh import adaptor, mesh
from schemaxis.adaptors.gmsh.quality import assess
from schemaxis.adaptor_conformance import assertions
from schemaxis.adaptor_delivery import case_document
from schemaxis.artifacts import file_digest
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gmsh',required=True,help='Absolute Gmsh 4.15.x Python interpreter')
    parser.add_argument('--output-directory',required=True,type=Path)
    args=parser.parse_args();target=args.output_directory.resolve();target.mkdir(parents=True,exist_ok=False)
    report={'verified':False,'cases':[],'refusals':[],'tamper':[]}
    entry=json.loads((ROOT/'src/schemaxis/adaptors/gmsh/readiness.json').read_text())['routes'][adaptor.VERSION]
    def run(document,name):
        result=adaptor.run(document,target/name,executable=args.gmsh,timeout=120)
        assert adaptor.verify(target/name)['verified']
        return result
    def refusal(document,name,fragment):
        try:run(document,name)
        except SchemaxisError as error:
            assert error.fault.code=='VERIFICATION_FAILED',error
            assert fragment in error.fault.message,error
            record=json.loads((target/name/'result.json').read_text())
            assert record['status']=='failed' and not record['verified']
            report['refusals'].append({'case':name,'code':error.fault.code,'message':error.fault.message})
        else:raise AssertionError(name+' unexpectedly accepted')
    try:
        for case in entry['development']['cases']:
            if not case['id'].startswith(('cylinder-','hollow-cylinder-','sphere-')):continue
            document=case_document(entry,case,ROOT)
            result=run(document,case['id']);checks=assertions(target/case['id'],case['checks'])
            report['cases'].append({'case':case['id'],'result':result,'checks':checks})
        original=json.loads((ROOT/'examples/schemaxis/gmsh-cylinder.json').read_text())
        strict=copy.deepcopy(original)
        for group in strict['nodes'][1]['options']['faceGroups']:del group['areaTolerance']
        refusal(strict,'strict-circular-caps','areaTolerance')
        tight=copy.deepcopy(original);tight['nodes'][1]['options']['faceGroups'][0]['areaTolerance']=0.0001
        refusal(tight,'tight-cap-budget','areaTolerance')
        tight=copy.deepcopy(original);tight['nodes'][1]['options']['volumeTolerance']=1e-8
        refusal(tight,'tight-volume-budget','volume differs')
        # Reproduce the circular-cap bug on captured STEP, not just new primitives.
        fixture=target/'cylinder.step';script=target/'make-step.py'
        script.write_text("import gmsh,sys\ngmsh.initialize([],readConfigFiles=False)\ngmsh.model.add('cap-regression')\ngmsh.model.occ.addCylinder(2,-1,3,0,0,8,3)\ngmsh.model.occ.synchronize()\ngmsh.write(sys.argv[1])\ngmsh.finalize()\n")
        with (target/'fixture.log').open('w') as log:
            subprocess.run([args.gmsh,str(script),str(fixture)],check=True,timeout=30,stdout=log,stderr=subprocess.STDOUT)
        step=copy.deepcopy(original);step['nodes'][0]={'id':'solid','filter':'readSTEP','options':{'file':str(fixture)}}
        result=run(step,'step-circular-caps');summary=json.loads((target/'step-circular-caps/mesh-summary.json').read_text())
        assert math.isclose(summary['cadVolume'],226.1946710584651,rel_tol=1e-10)
        assert all(math.isclose(g['cadArea'],28.274333882308138,rel_tol=1e-10) and 0<g['relativeError']<0.02 for g in summary['boundaryAreaChecks'])
        report['cases'].append({'case':'step-circular-caps','result':result})
        for group in step['nodes'][1]['options']['faceGroups']:del group['areaTolerance']
        refusal(step,'strict-step-circular-caps','areaTolerance')
        # Rehash native evidence deliberately: independent intent checks must still refuse it.
        directory=target/'cylinder-baseline';built_path=directory/'built.json';receipt_path=directory/'verification.json'
        originals={path:path.read_bytes() for path in (built_path,receipt_path)}
        for label,mutate,fragment in (
            ('meshing-choice',lambda b:b['meshing'].update(algorithm=10),'meshing decision'),
            ('cad-volume',lambda b:b['cad'].update(volume=b['cad']['volume']*1.01),'analytic primitive'),
            ('cad-cap-area',lambda b:b['faceAreas'].update({'3':b['faceAreas']['3']*1.001}),'analytic primitive')):
            built=json.loads(originals[built_path]);mutate(built);built_path.write_text(json.dumps(built))
            receipt=json.loads(originals[receipt_path]);receipt['evidence']['built.json']=file_digest(built_path);receipt_path.write_text(json.dumps(receipt))
            try:adaptor.verify(directory)
            except SchemaxisError as error:
                assert error.fault.code=='VERIFICATION_FAILED' and fragment in error.fault.message,error
                report['tamper'].append({'case':label,'code':error.fault.code,'message':error.fault.message})
            else:raise AssertionError('rehash concealed '+label)
            finally:
                for path,data in originals.items():path.write_bytes(data)
            assert adaptor.verify(directory)['verified']
        # Dent a lateral boundary vertex inward while preserving envelope and
        # volume budgets. Refresh all reported snapshots, VTU, summary and hashes
        # to prove the analytic boundary oracle adds an independent constraint.
        paths=[directory/name for name in ('result.msh','built.json','reopened.json',
               'volume.vtu','boundary.vtu','mesh-summary.json','verification.json')]
        originals={path:path.read_bytes() for path in paths}
        try:
            data=mesh.read(directory/'result.msh')
            tag=next(tag for tag,p in data['nodes'].items()
                     if 4<p[2]<10 and abs(math.hypot(p[0]-2,p[1]+1)-3)<1e-8)
            lines=(directory/'result.msh').read_text().splitlines();start=lines.index('$Nodes')+2
            end=lines.index('$EndNodes')
            for index in range(start,end):
                words=lines[index].split()
                if int(words[0])==tag:
                    point=[float(v) for v in words[1:]]
                    point[0]=2+(point[0]-2)*0.999;point[1]=-1+(point[1]+1)*0.999
                    lines[index]=str(tag)+' '+' '.join(map(str,point));break
            (directory/'result.msh').write_text('\n'.join(lines)+'\n')
            data=mesh.read(directory/'result.msh');observed=mesh.inspect(data);quality=assess(data)
            for name in ('built.json','reopened.json'):
                value=json.loads((directory/name).read_text())
                value['snapshot'].update({key:observed[key] for key in ('volume','minimumVolume','bounds')})
                value['snapshot'].update(minimumEdgeLength=quality['minimumEdgeLength']['minimum'],
                                         maximumEdgeLength=quality['maximumEdgeLength']['maximum'])
                (directory/name).write_text(json.dumps(value))
            for dim,name in ((3,'volume.vtu'),(2,'boundary.vtu')):mesh.write_vtu(directory/name,data,dim)
            built=json.loads((directory/'built.json').read_text())
            (directory/'mesh-summary.json').write_text(json.dumps(adaptor.summary(built['plan'],observed,built['cad'],data,built['faceAreas'])))
            receipt={'artifacts':adaptor.manifest(directory),'evidence':{name:file_digest(directory/name) for name in adaptor.EVIDENCE}}
            (directory/'verification.json').write_text(json.dumps(receipt))
            try:adaptor.verify(directory)
            except SchemaxisError as error:
                assert error.fault.code=='VERIFICATION_FAILED' and 'analytic primitive surface' in error.fault.message,error
                report['tamper'].append({'case':'rehashed-boundary-dent-with-refreshed-snapshots','code':error.fault.code,'message':error.fault.message})
            else:raise AssertionError('refreshed evidence concealed an inward boundary dent')
        finally:
            for path,data in originals.items():path.write_bytes(data)
        assert adaptor.verify(directory)['verified']
        report['verified']=True
    finally:(target/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'verified':report['verified'],'cases':len(report['cases']),'refusals':len(report['refusals']),'tamper':len(report['tamper'])}))


if __name__=='__main__':main()
