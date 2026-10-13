#!/usr/bin/env python3
"""Reproducible native numeric, spreadsheet and optional Blender CSV qualification."""
import argparse
import json
import math
from pathlib import Path
from schemaxis.artifacts import atomic_json
from schemaxis.adaptors.octave import adaptor as octave
from schemaxis.adaptors.calc import adaptor as calc
from schemaxis.workflow import execute,verify
from schemaxis.core.faults import SchemaxisError


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--octave',required=True);parser.add_argument('--calc',required=True)
    parser.add_argument('--blender');parser.add_argument('--output-directory',required=True)
    args=parser.parse_args();root=Path(args.output_directory).absolute();root.mkdir(parents=True,exist_ok=False)
    examples=Path(__file__).resolve().parents[1]/'examples/schemaxis/analysis'
    summary={'verified':False,'runs':{},'negativeChecks':[]}
    for name,adaptor,runtime in [('octave-signal',octave,args.octave),('octave-regression',octave,args.octave),('octave-calibration',octave,args.octave),('calc-summary',calc,args.calc)]:
        document=json.loads((examples/(name+'.json')).read_text());target=root/name
        summary['runs'][name]=adaptor.run(document,target,executable=runtime)
        adaptor.verify(target)
        print(name,'passed',flush=True)
    nodes=json.loads((root/'octave-signal/native.json').read_text())['nodes'];spectrum=nodes['spectrum']
    assert spectrum['x'][8]==8 and math.isclose(spectrum['y'][8],2,rel_tol=1e-10)
    fit=json.loads((root/'octave-regression/native.json').read_text())['nodes']['fit']['metadata']
    assert math.isclose(fit['slope'],2,rel_tol=1e-10) and math.isclose(fit['intercept'],1,rel_tol=1e-10)
    locations={'octave':args.octave,'calc':args.calc,'blender':args.blender}
    for name in ['octave-to-calc']+(['octave-to-blender'] if args.blender else []):
        target=root/name;execute(json.loads((examples/(name+'.json')).read_text()),target,locations=locations)
        summary['runs'][name]=verify(target)
        print(name,'passed',flush=True)
    path=root/'octave-regression/fit.csv';original=path.read_bytes()
    try:
        path.write_text('x,y\n0,999\n1,888\n')
        try:octave.verify(path.parent)
        except SchemaxisError:summary['negativeChecks'].append('changed numeric publication rejected')
        else:raise AssertionError('changed publication passed')
    finally:path.write_bytes(original)
    summary['verified']=True
    summary['scope']='Bounded CPU numeric pipelines, formula round-trips and optional data-curve rendering; no native Excel or MATLAB qualification.'
    atomic_json(root/'qualification.json',summary);print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
