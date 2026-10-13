#!/usr/bin/env python3
"""Native sampled requirements, changed components, forgery and handoff gates."""
import argparse
import copy
import json
from pathlib import Path

from schemaxis import workflow
from schemaxis.adaptors.ngspice import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.publication_metadata import finalise

ROOT=Path(__file__).resolve().parents[1]


def example(name):
    return json.loads((ROOT/f'examples/schemaxis/ngspice-{name}-requirements.json').read_text())


def fault(callback,code):
    try:callback()
    except SchemaxisError as error:
        assert error.fault.code==code,error.fault.to_dict()
        return error.fault.to_dict()
    raise AssertionError('expected '+code)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable',required=True)
    parser.add_argument('--calc',help='Optional native Calc runtime for accepted table handoff and resume')
    parser.add_argument('--output-directory',type=Path,required=True)
    parser.add_argument('--timeout',type=float,default=60)
    args=parser.parse_args();root=args.output_directory.absolute();root.mkdir(parents=True,exist_ok=False)
    report={'version':'schemaxis.ngspice.performance-qualification/1','verified':False,
        'scope':'Named finite DC/AC/RC samples and explicit component variants on observed ngspice47. '
                'No continuous operating envelope, all-tolerance coverage or physical device guarantee.',
        'accepted':{},'unmet':{},'negative':{},'workflows':{}}
    def run_case(name,document,accepted):
        output=root/name
        if accepted:
            adaptor.run(document,output,executable=args.executable,timeout=args.timeout)
            observed=adaptor.verify(output);assert observed['performance']['accepted']
            report['accepted'][name]=observed
        else:
            failure=fault(lambda:adaptor.run(document,output,executable=args.executable,timeout=args.timeout),'PERFORMANCE_NOT_MET')
            details=json.loads((output/'circuit-summary.json').read_text())
            assert details['performance']['accepted'] is False
            assert json.loads((output/'result.json').read_text())['verified'] is False
            replay=fault(lambda:adaptor.verify(output,require_result=False),'PERFORMANCE_NOT_MET')
            report['unmet'][name]={'fault':failure['code'],'independentReplay':replay['code'],
                'maximumVoltageError_V':details['maximumVoltageError_V'],'assessment':details['performance']}
        return output
    for kind in ('dc','ac','step'):run_case(kind,example(kind),True)
    dc=example('dc');dc['circuit']['resistors'][0]['resistance']=1100;run_case('dc-resistance-pass',dc,True)
    dc=example('dc');dc['circuit']['resistors'][0]['resistance']=500;run_case('dc-resistance-unmet',dc,False)
    negative=example('dc');negative.update(start=-5,stop=0)
    negative['requirements'][0].update(window=[-5,0],minimum=-3.4,maximum=0)
    run_case('negative-dc-pass',negative,True)
    negative['requirements'][0]['minimum']=-3
    run_case('negative-dc-unmet',negative,False)
    ac=example('ac');ac['circuit']['capacitors'][0]['capacitance']=.98e-6;run_case('capacitance-pass',ac,True)
    ac=example('ac');ac['circuit']['capacitors'][0]['capacitance']=2e-6;run_case('capacitance-unmet',ac,False)
    ac=example('ac');ac['amplitude']=-2;ac['requirements']=ac['requirements'][:1]
    run_case('negative-source-gain',ac,True)
    step=example('step');step['circuit']['resistors'][0]['resistance']=2000;run_case('slow-settling-unmet',step,False)
    study=json.loads((ROOT/'examples/schemaxis/ngspice-capacitance-study.json').read_text())
    failure=fault(lambda:adaptor.run(study,root/'analytic-study',executable=args.executable,timeout=args.timeout),
        'PERFORMANCE_NOT_MET')
    report['unmet']['analytic-study']={'fault':failure['code'],'scope':'Finite 0.98,1,2 uF visits; third is unmet.'}
    # Refresh every ordinary publication digest/metadata after forging acceptance.
    # The domain verifier must still reject a summary that contradicts native rows.
    output=root/'dc';authored=output/'authored.json';prepared=output/'plan.json';summary=output/'circuit-summary.json'
    saved={path:path.read_bytes() for path in (authored,prepared,summary,output/'verification.json')}
    try:
        document=json.loads(saved[authored]);document['requirements'][0]['maximum']=3
        atomic_json(authored,document);atomic_json(prepared,adaptor.plan(document))
        details=json.loads(saved[summary]);entry=details['performance']['requirements'][0]
        entry['maximum']=3;entry['checks'][1].update(expected=3,passed=True,margin=.1)
        atomic_json(summary,details)
        receipt=json.loads(saved[output/'verification.json']);receipt['artifacts']=adaptor.manifest(output)
        atomic_json(output/'verification.json',receipt);finalise(output)
        report['negative']['forgedAssessmentWithRefreshedPublicationMetadata']=fault(lambda:adaptor.verify(output),'VERIFICATION_FAILED')['code']
    finally:
        for path,data in saved.items():path.write_bytes(data)
        finalise(output)
    assert adaptor.verify(output)['verified']
    locations={'ngspice':args.executable}
    accepted_workflow={'version':'schemaxis.workflow/1','operations':[{'id':'circuit','document':example('dc')}]}
    target=root/'accepted-workflow';workflow.execute(accepted_workflow,target,locations=locations,timeout=args.timeout)
    assert workflow.verify(target)['verified']
    resumed=workflow.execute(accepted_workflow,target,locations=locations,timeout=args.timeout,resume=True)
    assert all(job['reused'] for job in resumed['jobs'])
    report['workflows']['acceptedProducerReuse']=True
    blocked=json.loads((ROOT/'examples/schemaxis/ngspice-to-calc.json').read_text())
    blocked['operations'][0]['document']=example('dc');blocked['operations'][0]['document']['requirements'][0]['maximum']=3
    target=root/'blocked-consumer'
    for attempt in (1,2):
        failure=fault(lambda:workflow.execute(blocked,target,locations={**locations,'calc':'/bin/true'},
            timeout=args.timeout,resume=attempt==2),'PERFORMANCE_NOT_MET')
        result=json.loads((target/'result.json').read_text())
        assert result['status']=='failed' and not result['verified']
        assert len(result['jobs'])==1 and result['jobs'][0]['operation']=='circuit' and result['jobs'][0]['status']=='failed'
        assert any(job.startswith('workbook') for job in result['pendingJobs'])
        assert not list((target/'workbook').glob('batch-*/attempt-*'))
    assert len(list((target/'circuit'/'batch-0').glob('attempt-*')))==2
    report['workflows']['unmetConsumerBlockedAndNotReused']={'fault':failure['code'],'freshFailedAttempts':2,'consumerAttempts':0}
    if args.calc:
        handoff=json.loads((ROOT/'examples/schemaxis/ngspice-to-calc.json').read_text());handoff['operations'][0]['document']=example('dc')
        target=root/'accepted-handoff';workflow.execute(handoff,target,locations={**locations,'calc':args.calc},timeout=args.timeout)
        assert workflow.verify(target)['verified']
        resumed=workflow.execute(handoff,target,locations={**locations,'calc':args.calc},timeout=args.timeout,resume=True)
        assert all(job['reused'] for job in resumed['jobs'])
        report['workflows']['acceptedCalcHandoffReuse']=True
    else:report['workflows']['acceptedCalcHandoffReuse']='not run; --calc required'
    report['verified']=True;atomic_json(root/'qualification.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
