#!/usr/bin/env python3
"""Exercise actual saved-BREP Draft measurement deadline and cancellation."""
import argparse,json,subprocess,threading,time
from pathlib import Path
from unittest.mock import patch
from schemaxis.adaptor_delivery import source_digest
from schemaxis.adaptors.freecad import adaptor,draft_verify
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.configuration import location_context
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation,execution_deadline


def qualify(directory,source,executable):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    source=Path(source).resolve();prepared=adaptor.plan(json.loads((source/'authored.json').read_text()))
    report={'verified':False,'sourceDigest':source_digest('freecad'),'sourceNativeSha256':file_digest(source/'model.FCStd'),
        'qualifierSha256':file_digest(Path(__file__)),'checks':{}}
    real_popen=subprocess.Popen
    try:
        with location_context({'freecad':executable}):
            start=time.monotonic();positive_launch=[]
            def observe_positive(*args,**kwargs):
                process=real_popen(*args,**kwargs);positive_launch.append(time.monotonic()-start);return process
            with patch('schemaxis.dispatch.subprocess.Popen',side_effect=observe_positive),execution_deadline(180):
                positive=draft_verify.fresh_inventories(source/'model.FCStd',prepared)
            positive_seconds=time.monotonic()-start
            assert len(positive_launch)==1
            assert set(positive)=={n['inputs']['base'] for n in prepared['nodes'] if n['filter']=='bodyDraft'}
            report['checks']['unchangedGeometry']={'seconds':positive_seconds,'launchDelay':positive_launch[0],
                'faces':{k:len(v) for k,v in positive.items()}}
            for control in ('timeout','cancel'):
                launched=threading.Event();cancel=threading.Event();processes=[];commands=[]
                def launch(*args,**kwargs):
                    process=real_popen(*args,**kwargs);processes.append(process);commands.append(list(args[0]));launched.set();return process
                def request_cancel():
                    if launched.wait(10):cancel.set()
                thread=threading.Thread(target=request_cancel,daemon=True) if control=='cancel' else None
                if thread:thread.start()
                budget=(positive_launch[0]+positive_seconds)/2 if control=='timeout' else 15
                start=time.monotonic()
                try:
                    with patch('schemaxis.dispatch.subprocess.Popen',side_effect=launch),allocation({},cancel),execution_deadline(budget):
                        draft_verify.fresh_inventories(source/'model.FCStd',prepared)
                except SchemaxisError as error:
                    assert error.fault.code==('RUNNER_TIMED_OUT' if control=='timeout' else 'RUNNER_CANCELLED'),error.fault.to_dict()
                    assert len(processes)==1 and commands[0][0]==executable,commands
                    assert processes[0].poll() is not None,'native geometry reader remains live'
                    report['checks'][control]={'fault':error.fault.to_dict(),'nativePid':processes[0].pid,
                        'stopped':True,'budget':budget,'elapsed':time.monotonic()-start,'command':commands[0]}
                else:raise AssertionError('actual Draft geometry '+control+' control did not refuse publication')
                finally:
                    cancel.set()
                    if thread:thread.join(11)
            assert report['sourceDigest']==source_digest('freecad'),'source changed during qualification'
            report['verified']=True
    finally:atomic_json(directory/'report.json',report)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',required=True)
    p.add_argument('--source',required=True);p.add_argument('--executable',required=True)
    a=p.parse_args();print(json.dumps(qualify(a.directory,a.source,a.executable),indent=2))
