#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Native elastic-beam kit, serviceability recovery and semantic tamper rejection."""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from schemaxis.adaptor_conformance import qualify
from schemaxis.adaptors.calculix.adaptor import plan,run,verify
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.core.faults import SchemaxisError


def rejection(action,code):
    try: action()
    except SchemaxisError as error:
        if error.fault.code != code: raise
        return error.fault.to_dict()
    raise AssertionError('expected '+code)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory',required=True,type=Path)
    parser.add_argument('--executable',type=Path)
    parser.add_argument('--timeout',default=120,type=float)
    args = parser.parse_args()
    directory = args.output_directory.resolve();directory.mkdir(parents=True,exist_ok=False)
    locations = {'calculix':str(args.executable.resolve())} if args.executable else {}
    options = {'executable':locations.get('calculix'),'timeout':args.timeout}
    report = {'verified':False,'scope':'Bounded serial C3D20R elastic cantilevers: independent literal signed beam/reaction witnesses, separate mesh refinements, interior Gauss normal stress, fresh exact-deck readback, serviceability failure/recovery, semantic/status tamper rejection and common force analytics. No general FEA or root/surface peak-stress certification.'}
    try:
        report['conformance'] = qualify('schemaxis.calculix/1',directory/'native',native=True,locations=locations,timeout=args.timeout)
        baseline = json.loads((ROOT/'examples/schemaxis/calculix-beam.json').read_text())
        unmet = json.loads((ROOT/'examples/schemaxis/calculix-beam-unmet.json').read_text());plan(unmet)
        report['unmet'] = rejection(lambda:run(unmet,directory/'unmet',**options),'PERFORMANCE_NOT_MET')
        report['unmetBlocked'] = rejection(lambda:verify(directory/'unmet'),'INCOMPLETE_EXECUTION')
        assessment = json.loads((directory/'unmet/beam-assessment.json').read_text())
        if assessment['accepted'] or assessment['requirements'][0]['margin'] >= 0: raise AssertionError('unmet native requirement lost measured failure')
        run(baseline,directory/'recovered',**options);report['recovery'] = verify(directory/'recovered')
        target = directory/'recovered';deck_path = target/'beam.inp';receipt_path = target/'verification.json'
        original_deck = deck_path.read_bytes();original_receipt = receipt_path.read_bytes()
        try:
            deck_path.write_bytes(original_deck.replace(b'210000000000,0.3',b'105000000000,0.3'))
            altered = json.loads(original_receipt);altered['artifacts'][0]['sha256']=file_digest(deck_path);atomic_json(receipt_path,altered)
            report['semanticTamper'] = rejection(lambda:verify(target),'VERIFICATION_FAILED')
        finally: deck_path.write_bytes(original_deck);receipt_path.write_bytes(original_receipt)
        submission = target/'fine/solve-submission.json';original_submission = submission.read_bytes()
        try:
            altered = json.loads(original_submission);altered['exitCode']=1;atomic_json(submission,altered)
            report['statusTamper'] = rejection(lambda:verify(target),'VERIFICATION_FAILED')
        finally: submission.write_bytes(original_submission)
        verify(target)
        analytic = copy.deepcopy(baseline);analytic['load']['tipForceZ_N']={'$analytic':{'type':'values','values':[-100,-50]}}
        run(analytic,directory/'force-analytic',**options);report['analytic']=verify(directory/'force-analytic')
        if report['analytic'].get('states') != 2: raise AssertionError('expected two independent native force states')
        values = [json.loads((directory/'force-analytic'/f'state-{i:05d}'/'verification.json').read_text())['native']['fine']['tipAreaMeanDisplacement_m'][2] for i in range(2)]
        if abs(values[1]/values[0]-.5)>1e-6: raise AssertionError('native force-compliance scaling differs')
        report['analyticMeanUz_m'] = values;report['verified']=True
    finally:atomic_json(directory/'qualification.json',report)
    print(json.dumps({'verified':report['verified'],'directory':str(directory)},indent=2))


if __name__=='__main__':main()
