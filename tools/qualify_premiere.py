#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Opt-in installed Premiere acceptance; never substitutes mocks for native execution."""
import argparse
import copy
import json
from pathlib import Path
import sys
import threading
import time
from schemaxis.adaptors.premiere import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bridge',required=True,type=Path)
    parser.add_argument('--project-path',required=True)
    parser.add_argument('--source-path',required=True)
    parser.add_argument('--output-directory',required=True,type=Path)
    parser.add_argument('--timeout',type=float,default=300)
    args=parser.parse_args()
    if sys.platform not in ('win32','darwin'):
        parser.error('Installed Premiere native acceptance requires Windows/macOS; Linux cannot qualify this integration')
    directory=args.output_directory.absolute();directory.mkdir(parents=True,exist_ok=False)
    base=json.loads((ROOT/'examples/schemaxis/premiere-sequence.json').read_text())
    base['projectPath']=args.project_path
    cases=[]
    for identity,sequence,ranges,literal in [
        ('trim-reorder','Schemaxis Colours',[(3,3),(0,2)],[('0','30481920000','30481920000','60963840000'),('30481920000','50803200000','0','20321280000')]),
        ('repeat-range','Schemaxis Repeat',[(1,2),(1,2)],[('0','20321280000','10160640000','30481920000'),('20321280000','40642560000','10160640000','30481920000')])]:
        document=copy.deepcopy(base);document['sequenceName']=sequence
        document['clips']=[{'sourcePath':args.source_path,'startFrame':start,'frameCount':count} for start,count in ranges]
        target=directory/identity
        print('Activate native sequence '+sequence+'. Select its fresh job folder when printed.',flush=True)
        stop=threading.Event()
        def show_job():
            deadline=time.monotonic()+args.timeout
            while not stop.is_set() and time.monotonic()<deadline:
                file=target/'bridge-job.json'
                if file.exists():
                    try: print('Select job folder: '+json.loads(file.read_text())['jobDirectory'],flush=True);return
                    except (ValueError,KeyError): pass
                stop.wait(.1)
        monitor=threading.Thread(target=show_job,daemon=True);monitor.start()
        try: adaptor.run(document,target,bridge=args.bridge.absolute(),timeout=args.timeout)
        finally: stop.set();monitor.join(timeout=1)
        checked=adaptor.verify(target)
        observation=json.loads((target/'observation.json').read_text())
        actual=[tuple(c[k] for k in ('startTicks','endTicks','inTicks','outTicks')) for c in observation['clips']]
        if actual!=literal: raise AssertionError('native observed ranges differ from independent literal ticks')
        if observation['project']['path']!=args.project_path or observation['sequence']['name']!=sequence:
            raise AssertionError('independent native identities differ')
        mutations=[]
        for filename in ('request.json','response.json','observation.json','verification.json'):
            path=target/filename;original=path.read_bytes()
            try:
                path.write_text('{}')
                try: adaptor.verify(target)
                except SchemaxisError as error: mutations.append({'file':filename,'fault':error.fault.code})
                else: raise AssertionError('changed evidence was accepted')
            finally:path.write_bytes(original)
        adaptor.verify(target)
        cases.append({'id':identity,'verified':True,'frames':checked['frames'],'runtime':checked['runtime'],'literalRanges':literal,'mutations':mutations})
    report={'verified':True,'nativeExecution':True,'provider':'premiere','cases':cases,'scope':'Read-only native sequence structure and source identities; no source-content, effects, export or pixel proof. Human-mediated lifecycle beyond these cases remains unqualified.'}
    atomic_json(directory/'acceptance.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__': main()
