#!/usr/bin/env python3
"""Bounded native thermal-reactor, offline integrity and shared authoring acceptance."""
import argparse
import copy
import json
import math
import os
from pathlib import Path
import shutil

from schemaxis.adaptors.cantera import adaptor, thermo
from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.core.faults import SchemaxisError
from schemaxis import workflow
from qualify_agent_service import Client
from qualify_adaptor_growth import context

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cantera',required=True);parser.add_argument('--output-directory',type=Path,required=True)
    args=parser.parse_args();directory=args.output_directory.resolve();directory.mkdir(parents=True,exist_ok=False)
    doc=json.loads((ROOT/'examples/schemaxis/cantera-thermal-reactor.json').read_text())
    report={'verified':False,'cases':[],'negative':[]}
    # Shared tools read the same installed interpreter; this does not change PATH.
    os.environ['CANTERA_PYTHON']=args.cantera
    def run(d,name):
        target=directory/name;adaptor._native_run(d,target,executable=args.cantera,timeout=120)
        assert adaptor._native_verify(target)['verified']
        built=json.loads((target/'built.json').read_text());summary=json.loads((target/'chemistry-summary.json').read_text())
        report['cases'].append({'name':name,'finalTemperature_K':built['rows'][-1][1],
            'delay_s':summary['ignition']['delay_s'],'maxEnergyError_J_kg':max(c['energyError_J_kg'] for c in summary['checks'])})
        return target,built,summary
    try:
        for model in ('constantPressure','constantVolume'):
            for bath in (500,1500):
                d=copy.deepcopy(doc);d['nodes'][0]['options']['composition']=[{'species':'AR','amount':1}]
                s=d['nodes'][1]['options'];s.update(model=model,bathTemperature=bath,times=[0,0.01,0.1,1])
                target,built,summary=run(d,'argon-'+model+'-'+str(bath))
                state=thermo.properties(1000,101325,[0]*8+[1,0]);c=state[6 if model == 'constantPressure' else 7];mass=state[2]
                for row in built['rows']:
                    expected=bath+(1000-bath)*math.exp(-1000*row[0]/(mass*c))
                    assert math.isclose(row[1],expected,abs_tol=2e-5),(row[0],row[1],expected)
                    assert math.isclose(row[4 if model == 'constantPressure' else 5]-built['rows'][0][4 if model == 'constantPressure' else 5],summary['checks'][built['rows'].index(row)]['independentHeatInput_J_kg'],abs_tol=0.01)
                assert (summary['ignition']['delay_s'] is not None) == (bath == 1500)
                if bath == 1500:
                    analytic=mass*c/1000*math.log((bath-1000)/(bath-1400))
                    assert math.isclose(summary['ignition']['delay_s'],analytic,rel_tol=0.001)
                if model == 'constantPressure':assert built['reactor']['samples'][-1]['volume'] != 1
                else:assert built['reactor']['samples'][-1]['volume'] == 1
            for conductance in (0,1000,200000):
                d=copy.deepcopy(doc);d['nodes'][1]['options'].update(model=model,thermalConductance=conductance)
                if conductance == 200000: d['nodes'][1]['options']['absoluteTolerance']=1e-18
                target,built,summary=run(d,'reactive-'+model+'-'+str(conductance))
                if conductance == 0:
                    assert summary['ignition']['delay_s'] is not None;adiabatic=summary
                elif conductance == 1000:
                    assert summary['ignition']['delay_s'] > adiabatic['ignition']['delay_s']
                else:assert summary['ignition']['delay_s'] is None and built['rows'][-1][1] < 600
        # Tamper, including a forged digest refresh, must fail offline.
        thermal=directory/'reactive-constantPressure-1000';bad=directory/'forged';shutil.copytree(thermal,bad)
        evidence=json.loads((bad/'built.json').read_text());evidence['reactor']['samples'][-1]['heatRateOut_W']=0
        atomic_json(bad/'built.json',evidence);v=json.loads((bad/'verification.json').read_text());v['evidence']['built.json']=file_digest(bad/'built.json');atomic_json(bad/'verification.json',v)
        try:adaptor._native_verify(bad)
        except SchemaxisError as error:assert error.fault.code == 'VERIFICATION_FAILED';report['negative'].append('forged heat-flow evidence rejected offline')
        else:raise AssertionError('forged wall heat accepted')
        invalid=copy.deepcopy(doc);invalid['nodes'][1]['options']['thermalConductance']=-1
        try:adaptor._native_run(invalid,directory/'invalid',executable=args.cantera)
        except SchemaxisError as error:assert error.fault.code == 'INVALID_ARGUMENT' and not (directory/'invalid').exists();report['negative'].append('invalid thermal input rejected before native assignment')
        else:raise AssertionError('invalid conductance accepted')
        try:adaptor._native_run(doc,directory/'timeout',executable=args.cantera,timeout=1e-5)
        except SchemaxisError as error:
            assert error.fault.code in ('RUNNER_TIMED_OUT',);assert not (directory/'timeout/results.csv').exists();report['negative'].append('timeout produced no publication')
        else:raise AssertionError('tiny deadline accepted')
        # Thermal source survives shared workflow reuse as a durable verified artefact.
        # Use an established workflow envelope, retaining its resource semantics.
        original=json.loads((ROOT/'examples/schemaxis/cantera-to-calc.json').read_text());wf=copy.deepcopy(original)
        wf['operations']=wf['operations'][:1];wf['operations'][0]['document']=doc
        wf.pop('output',None)
        result=workflow.execute(wf,directory/'workflow',locations={'cantera':args.cantera},timeout=120)
        assert workflow.verify(directory/'workflow')['verified']
        resumed=workflow.execute(wf,directory/'workflow',locations={'cantera':args.cantera},timeout=120,resume=True)
        assert all(j['reused'] for j in resumed['jobs']);report['workflowReuse']=True
        client=Client(directory/'public')
        try:
            provider,_=context(client,'schemaxis.cantera/1','/provider')
            task=client.call('create_task',objective='Compare fixed-bath hydrogen reactor heat loss',allowed_providers=[provider],budget={'maxAttempts':3,'maxElapsedSeconds':120})
            draft=client.call('create_draft',provider=provider,name='Thermal reactor')
            draft=client.call('edit_draft',document_id=draft['document'],expected_revision=draft['revision'],source=json.dumps(doc))
            revision=0
            for conductance in (1000,200000):
                draft=client.call('patch_draft',document_id=draft['document'],expected_revision=draft['revision'],edits=[{'op':'replace','path':'/nodes/1/options/thermalConductance','value':conductance}])
                planned=client.call('plan_draft',task_id=task['id'],expected_revision=revision,document_id=draft['document'],draft_revision=draft['revision'])
                revision=planned['revision'];job=client.call('execute',plan_id=planned['id'],expected_revision=revision)
                assert client.wait(job)['status'] == 'succeeded',client.call('observe',job_id=job['id'],section='fault')
                assert client.call('verify',job_id=job['id'])['value']['verified']
            report['publicAuthoring']={'sameDraftEdited':True,'conductances_W_K':[1000,200000]}
        finally:client.close()
        report['verified']=True
    finally:(directory/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__ == '__main__':main()
