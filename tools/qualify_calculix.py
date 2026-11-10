#!/usr/bin/env python3
# Copyright (C) 2026 David L. F. Gaden
"""Native six-resultant members, measured limits, changed intent and evidence controls."""
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
    report = {'verified':False,'scope':'Bounded serial six-resultant rectangular members: literal axial/biaxial bending/torsion/reaction witnesses, clamped and pure-axial sliding restraints, independent refinement and interior normal/torsional stress, native measured translation/twist/von Mises limits, exact deck readback, semantic/status/shear tamper rejection, torque sign reversal and changed stiffness. No general FEA or peak/failure certification.'}
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
        report['analyticMeanUz_m'] = values
        combined = json.loads((ROOT/'examples/schemaxis/calculix-combined.json').read_text())
        for name,quantity,maximum in [('twist-unmet','absTipTwist_rad',.0001),('equivalent-stress-unmet','maxInteriorSampleVonMises_Pa',1e6)]:
            document=copy.deepcopy(combined);document['requirements']=[{'name':'bounded_measurement','quantity':quantity,'maximum':maximum}]
            report[name]=rejection(lambda:run(document,directory/name,**options),'PERFORMANCE_NOT_MET')
            retained=json.loads((directory/name/'beam-assessment.json').read_text())
            if retained['accepted'] or retained['requirements'][0]['margin']>=0:raise AssertionError('lost measured '+name)
            report[name+'Blocked']=rejection(lambda:verify(directory/name),'INCOMPLETE_EXECUTION')
        torsion=json.loads((ROOT/'examples/schemaxis/calculix-torsion.json').read_text())
        reversal=copy.deepcopy(torsion);reversal['load']['tipMomentX_Nm']=-1
        run(reversal,directory/'torque-reversed',**options); reversed_result=verify(directory/'torque-reversed')
        positive=verify(directory/'native/torsion')['native']['fine']['tipTwist_rad']
        negative=reversed_result['native']['fine']['tipTwist_rad']
        if abs(negative/positive+1)>1e-5:raise AssertionError('native twist did not reverse with torque')
        stiffer=copy.deepcopy(torsion);stiffer['material']['youngsModulus_Pa']=420e9
        run(stiffer,directory/'torsion-stiffer',**options);stiff_result=verify(directory/'torsion-stiffer')
        stiff=stiff_result['native']['fine']['tipTwist_rad']
        if abs(stiff/positive-.5)>1e-5:raise AssertionError('native torsional stiffness did not scale with shear modulus')
        report['changedIntent']={'positiveTwist_rad':positive,'reversedTwist_rad':negative,'doubleETwist_rad':stiff}
        target=directory/'native/combined';path=target/'fine/beam.dat';original=path.read_bytes()
        try:
            lines=original.decode('ascii').splitlines();index=next(i for i,line in enumerate(lines) if line.strip().startswith('stresses'))+1
            for i in range(index,len(lines)):
                row=lines[i].split()
                if len(row)==8:row[5]=str(float(row[5])*2);row[6]=str(float(row[6])*2);lines[i]=' '.join(row)
            path.write_text('\n'.join(lines)+'\n')
            report['nativeShearTamper']=rejection(lambda:verify(target),'NUMERICAL_ACCEPTANCE_FAILED')
        finally:path.write_bytes(original)
        verify(target)
        unsupported=copy.deepcopy(torsion);unsupported['support']='axialSlide'
        report['unsupportedRestraint']=rejection(lambda:run(unsupported,directory/'unsupported-restraint',**options),'INVALID_BEAM')
        if (directory/'unsupported-restraint').exists():raise AssertionError('invalid physical intent launched a native attempt')
        report['verified']=True
    finally:atomic_json(directory/'qualification.json',report)
    print(json.dumps({'verified':report['verified'],'directory':str(directory)},indent=2))


if __name__=='__main__':main()
