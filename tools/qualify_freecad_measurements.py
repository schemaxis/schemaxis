#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Named CAD quantities, public value handoffs and persistent measurements."""
import argparse
import copy
import json
import math
from pathlib import Path
from schemaxis.adaptors import registry
from schemaxis.adaptor_delivery import source_digest
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.core.faults import SchemaxisError
from schemaxis import workflow
from schemaxis.tabular import read_csv
ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True)
    p.add_argument('--output-directory',type=Path,required=True);p.add_argument('--freecad-gui',type=Path)
    args=p.parse_args();locations=json.loads(args.config.read_text())['locations']
    output=args.output_directory.absolute();output.mkdir(parents=True,exist_ok=False)
    doc=json.loads((ROOT/'examples/schemaxis/freecad-measurements.json').read_text())
    report={'verified':False,'sourceDigest':source_digest('freecad'),
            'scope':'Native geometric quantities in mm-derived units; selected solid/edge observations; no material or manufacturing properties.', 'checks':{}}
    def oracle(publication,height,origin=(0,0,0)):
        measured=publication['measurements'];area=200-(4-math.pi);perimeter=60-8+2*math.pi
        expected={'finishedVolume':area*height,'finishedArea':2*area+perimeter*height,'height':height,'verticalEdgeLength':4*height}
        for key,value in expected.items():assert math.isclose(measured[key]['value'],value,rel_tol=1e-9,abs_tol=1e-7),(key,measured[key])
        assert measured['finishedVolume']['units']=='mm^3' and measured['finishedArea']['units']=='mm^2'
        assert all(math.isclose(v,w,abs_tol=1e-8) for v,w in zip(measured['centre']['value'],[origin[0]+10,origin[1]+5,origin[2]+height/2]))
    try:
        baseline=output/'measurements';registry.run(doc,baseline,locations=locations,timeout=120)
        report['checks']['baseline']=registry.verify(baseline);oracle(json.loads((baseline/'measurements.json').read_text()),5)
        assert report['checks']['baseline']['artifacts']==4
        variant=copy.deepcopy(doc);variant['nodes'][0]['options'].update(height=7,origin=[-3,4,5])
        target=output/'translated';registry.run(variant,target,locations=locations,timeout=120)
        report['checks']['translated']=registry.verify(target);oracle(json.loads((target/'measurements.json').read_text()),7,(-3,4,5))
        publication=baseline/'measurements.json';receipt=baseline/'verification.json'
        original=publication.read_bytes();saved=receipt.read_bytes()
        try:
            changed=json.loads(original);changed['measurements']['finishedVolume']['value']=123
            atomic_json(publication,changed)
            changed_receipt=json.loads(saved);changed_receipt['artifacts'][3]['sha256']=file_digest(publication)
            atomic_json(receipt,changed_receipt)
            try:registry.verify(baseline)
            except SchemaxisError as error:assert error.fault.code=='VERIFICATION_FAILED';report['checks']['tamperedValue']='rejected even with updated publication hash'
            else:raise AssertionError('forged measurement was accepted')
        finally:publication.write_bytes(original);receipt.write_bytes(saved)
        registry.verify(baseline)
        try:
            changed_receipt=json.loads(saved);changed_receipt['measurementObservations']['rounded']['shape']['volume']=123
            atomic_json(receipt,changed_receipt)
            try:registry.verify(baseline)
            except SchemaxisError as error:assert error.fault.code=='VERIFICATION_FAILED';report['checks']['tamperedReadback']='rejected'
            else:raise AssertionError('altered native measurement was accepted')
        finally:receipt.write_bytes(saved)
        envelope=json.loads((ROOT/'examples/schemaxis/freecad-measured-workflow.json').read_text())
        target=output/'workflow';workflow.execute(envelope,target,locations=locations,timeout=240)
        report['checks']['workflow']=workflow.verify(target)
        outer=json.loads((target/'result.json').read_text());assert len(outer['states'])==2
        for state,height in zip(outer['states'],(5,7)):
            child=target/state['directory'];jobs={j['operation']:j for j in json.loads((child/'result.json').read_text())['jobs']}
            cad=Path(jobs['cad']['directory']);measurement=json.loads((cad/'measurements.json').read_text());oracle(measurement,height)
            mesh=Path(jobs['mesh']['directory'])
            mesh_receipt=json.loads((mesh/'verification.json').read_text())
            # Common expression execution may wrap one resolved native visit.
            # Follow the published summary rather than assuming its directory.
            mesh=Path(mesh_receipt['artifacts'][3]['file']).parent
            plan=json.loads((mesh/'plan.json').read_text())
            assert math.isclose(plan['nodes'][1]['options']['size'],height*.4,abs_tol=1e-12)
            mesh_summary=json.loads((mesh/'mesh-summary.json').read_text())
            assert math.isclose(mesh_summary['cadVolume'],measurement['measurements']['finishedVolume']['value'],rel_tol=1e-9)
            table=json.loads((Path(jobs['table']['directory'])/'verification.json').read_text())
            csv=read_csv(next(a['file'] for a in table['artifacts'] if a['kind']=='table'))
            expected=[measurement['measurements']['finishedVolume']['value'],4*height,measurement['measurements']['finishedVolume']['value']*.001]
            assert all(math.isclose(row[1],value,rel_tol=1e-12) for row,value in zip(csv['rows'],expected))
        resumed=workflow.execute(envelope,target,locations=locations,timeout=240,resume=True)
        for state in resumed['states']:
            jobs=json.loads((target/state['directory']/'result.json').read_text())['jobs'];assert all(j['reused'] for j in jobs)
        workflow.verify(target);report['checks']['reusedJobs']=6
        bad=copy.deepcopy(doc);bad['measurements'][-1]['edges']['expect']=1
        rejected={'version':'schemaxis.workflow/1','operations':[{'id':'cad','document':bad},copy.deepcopy(envelope['operations'][2])]}
        try:workflow.execute(rejected,output/'unmet-selection',locations=locations,timeout=120)
        except SchemaxisError:pass
        else:raise AssertionError('unmet measurement producer was accepted')
        jobs=json.loads((output/'unmet-selection'/'result.json').read_text())['jobs']
        assert not any(j.get('status')=='succeeded' for j in jobs)
        report['checks']['unmetMeasurement']='consumer blocked'
        if args.freecad_gui:
            from schemaxis.adaptors.freecad.live import LiveSession
            with LiveSession(str(args.freecad_gui),output/'live',timeout=30,startup_timeout=30) as session:
                first=session.request('apply',document=doc);oracle(session.request('geometry')['measurements'],5)
                second=session.request('apply',document=variant);before=session.request('geometry');oracle(before['measurements'],7,(-3,4,5))
                assert first['objects']==second['objects'] and first['pid']==second['pid']
                bad=copy.deepcopy(variant);bad['measurements'][-1]['edges']['expect']=1
                try:session.request('apply',document=bad)
                except SchemaxisError as error:assert error.fault.code=='AMBIGUOUS_SELECTION'
                else:raise AssertionError('invalid live measurement accepted')
                assert session.request('geometry')==before and session.request('status')['revision']==second['revision']
                report['checks']['live']={'verified':True,'reusedObjects':True,'measurementFailureRolledBack':True}
        from qualify_agent_service import Client
        from qualify_adaptor_growth import context
        client=Client(output/'public',config=args.config)
        try:
            provider,_=context(client,'schemaxis.freecad/1','/provider')
            task=client.call('create_task',objective='Measure a rounded part in declared units',allowed_providers=[provider])
            planned=client.call('plan',task_id=task['id'],expected_revision=0,document=doc)
            job=client.call('execute',plan_id=planned['id'],expected_revision=planned['revision'])
            assert client.wait(job)['status']=='succeeded'
            assert client.call('verify',job_id=job['id'])['value']['verified']
            resources=client.call('observe',job_id=job['id'],section='resources')['value']
            resource=next(r for r in resources if Path(r['file']).name=='measurements.json')
            value=client.call('inspect_resource',resource_id=resource['id'],pointer='/measurements/finishedVolume')['value']
            assert value['units']=='mm^3' and math.isclose(value['value'],(200-(4-math.pi))*5,abs_tol=1e-7)
            report['checks']['publicInspection']=value
        finally:client.close()
        assert report['sourceDigest']==source_digest('freecad'),'source changed during qualification'
        report['verified']=True
    finally:atomic_json(output/'report.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
