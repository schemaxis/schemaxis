#!/usr/bin/env python3
"""Bounded CAD target search with scientific oracles and cross-adaptor use."""
import argparse
import copy
import json
import math
from pathlib import Path
from schemaxis.adaptors import registry
from schemaxis.adaptors.freecad import design_study
from schemaxis.adaptor_delivery import source_digest
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis import workflow
from schemaxis.tabular import read_csv
ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True)
    p.add_argument('--output-directory',type=Path,required=True);args=p.parse_args()
    locations=json.loads(args.config.read_text())['locations'];output=args.output_directory.absolute();output.mkdir(parents=True,exist_ok=False)
    doc=json.loads((ROOT/'examples/schemaxis/freecad-design-target.json').read_text())
    report={'verified':False,'sourceDigest':source_digest('freecad'),'checks':{},
        'scope':'One bounded resolved CAD length, a named scalar target and declared sampled response direction; no general constraint solver or global optimisation claim.'}
    def run(name,document):
        target=output/name;registry.run(document,target,locations=locations,timeout=180)
        report['checks'][name]=registry.verify(target);print(name,report['checks'][name],flush=True);return target
    def unmet(name,document,reason):
        target=output/name
        try:registry.run(document,target,locations=locations,timeout=180)
        except SchemaxisError as error:assert error.fault.code=='STUDY_REQUIREMENTS_NOT_MET',error.to_dict()
        else:raise AssertionError(name+' unexpectedly succeeded')
        result=design_study.verify(target,require_acceptance=False)
        assert not result['accepted'] and result['reason']==reason,result
        receipt=json.loads((target/'verification.json').read_text());assert len(receipt['artifacts'])==2
        assert all(Path(a['file']).parent==target for a in receipt['artifacts'])
        report['checks'][name]=result
    def oracle(target,requested=1000):
        summary=json.loads((target/'study-summary.json').read_text());assert summary['accepted']
        for attempt in summary['attempts']:
            nodes=attempt['document']['nodes'];height=nodes[0]['options']['height'];radius=nodes[1]['options']['radius']
            expected=(200-(4-math.pi)*radius**2)*height
            assert math.isclose(attempt['observation']['value'],expected,rel_tol=1e-9,abs_tol=1e-7)
        last=summary['attempts'][-1]
        assert abs(last['observation']['value']-requested)<=.1
        return {'height':last['document']['nodes'][0]['options']['height'],
                'volume':last['observation']['value'],'attempts':len(summary['attempts'])}
    try:
        baseline=run('increasing',doc);report['selected']=oracle(baseline)
        decreasing=copy.deepcopy(doc);decreasing['designStudy']['parameter']={'node':'rounded','option':'radius','minimum':.5,'maximum':1.5}
        decreasing['designStudy'].update(response='decreasing',maxIterations=4)
        decreasing['designStudy']['target']['value']=(200-(4-math.pi))*5
        target=run('decreasing',decreasing);oracle(target,decreasing['designStudy']['target']['value'])
        profile={'version':'schemaxis.freecad/1','nodes':[{'id':'profile','filter':'rectangle','options':{'width':10,'height':10}},
            {'id':'body','filter':'extrude','inputs':{'profile':'profile'},'options':{'length':5}}],'output':'body',
            'measurements':[{'id':'volume','node':'body','quantity':'volume'}],
            'designStudy':{'parameter':{'node':'profile','option':'width','minimum':10,'maximum':30},
                'target':{'measurement':'volume','value':1000,'tolerance':.01,'units':'mm^3'},'response':'increasing','maxIterations':4}}
        target=run('linked-profile',profile);summary=json.loads((target/'study-summary.json').read_text())
        assert len(summary['attempts'])==3
        assert summary['attempts'][-1]['document']['nodes'][0]['options']['width']==20
        assert math.isclose(summary['attempts'][-1]['observation']['value'],1000,abs_tol=1e-8)
        bad=copy.deepcopy(doc);bad['designStudy']['target']['value']=2000
        unmet('unbracketed',bad,'target_not_bracketed')
        bad=copy.deepcopy(doc);bad['designStudy']['response']='decreasing'
        unmet('wrong-response',bad,'response_assumption_violated')
        bad=copy.deepcopy(doc);bad['designStudy']['maxIterations']=2
        unmet('iteration-limit',bad,'iteration_limit')
        bad=copy.deepcopy(doc);bad['designStudy']['minimumStep']=10
        unmet('parameter-limit',bad,'parameter_limit')
        bad=copy.deepcopy(decreasing);bad['designStudy']['parameter']['maximum']=6
        try:registry.run(bad,output/'invalid-geometry',locations=locations,timeout=180)
        except SchemaxisError as error:
            assert error.fault.code!='STUDY_REQUIREMENTS_NOT_MET',error.to_dict()
            report['checks']['invalid-geometry']=error.to_dict()
        else:raise AssertionError('invalid geometry became a valid search sample')
        result=json.loads((output/'invalid-geometry'/'result.json').read_text())
        assert result['status']=='failed' and not result['verified'] and len(result['attempts'])==1
        analytic=copy.deepcopy(doc);analytic['designStudy']['parameter']['maximum']=7
        analytic['designStudy']['target']['value']={'$analytic':{'type':'values','values':[1000,1200]}}
        target=run('analytic-targets',analytic)
        oracle(target/'state-00000',1000);oracle(target/'state-00001',1200)
        for relative in ('result.json','study-summary.json','study.html','attempt-00000/measurements.json'):
            path=baseline/relative;original=path.read_bytes()
            try:
                path.write_bytes(b'{}')
                try:registry.verify(baseline)
                except SchemaxisError:pass
                else:raise AssertionError('altered study evidence accepted: '+relative)
            finally:path.write_bytes(original)
        registry.verify(baseline);report['checks']['corruption']='rejected'
        envelope=json.loads((ROOT/'examples/schemaxis/freecad-measured-workflow.json').read_text())
        envelope['operations'][0]['document']=doc
        target=output/'workflow';workflow.execute(envelope,target,locations=locations,timeout=240)
        report['checks']['workflow']=workflow.verify(target)
        jobs={j['operation']:j for j in json.loads((target/'result.json').read_text())['jobs']}
        cad=Path(jobs['cad']['directory']);receipt=json.loads((cad/'verification.json').read_text())
        quantity=json.loads(Path(receipt['artifacts'][3]['file']).read_text())['measurements']['finishedVolume']['value']
        assert abs(quantity-1000)<=.1
        receipt=json.loads((Path(jobs['table']['directory'])/'verification.json').read_text())
        table=read_csv(next(a['file'] for a in receipt['artifacts'] if a['kind']=='table'))
        assert math.isclose(table['rows'][0][1],quantity,rel_tol=1e-12)
        resumed=workflow.execute(envelope,target,locations=locations,timeout=240,resume=True)
        assert all(j['reused'] for j in resumed['jobs']);workflow.verify(target)
        report['checks']['reusedJobs']=len(resumed['jobs'])
        envelope['operations'][0]['document']=copy.deepcopy(doc);envelope['operations'][0]['document']['designStudy']['maxIterations']=2
        try:workflow.execute(envelope,output/'unmet-workflow',locations=locations,timeout=180)
        except SchemaxisError:pass
        else:raise AssertionError('unmet design study published to consumers')
        failed=json.loads((output/'unmet-workflow'/'result.json').read_text())
        assert not any(j.get('status')=='succeeded' for j in failed['jobs'])
        report['checks']['unmetWorkflow']='consumers blocked'
        assert report['sourceDigest']==source_digest('freecad'),'source changed during qualification'
        report['verified']=True
    finally:atomic_json(output/'report.json',report)
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
