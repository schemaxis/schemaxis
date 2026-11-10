#!/usr/bin/env python3
"""Actual CAM fresh-replay timeout/cancellation and unchanged positive control."""
import argparse
import json
from pathlib import Path
import subprocess
import threading
import time
from unittest.mock import patch

from schemaxis.adaptor_delivery import source_digest
from schemaxis.adaptors.freecad import cam_verify
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.configuration import location_context
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation,execution_deadline


def qualify(directory,cam_directory,executable):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    cam_directory=Path(cam_directory).resolve()
    report={'verified':False,'sourceDigest':source_digest('freecad'),'qualifierSha256':file_digest(Path(__file__)),
            'sourceNativeSha256':file_digest(cam_directory/'machining.FCStd'),'checks':{}}
    real_popen=subprocess.Popen
    try:
        with location_context({'freecad':executable}):
            start=time.monotonic()
            with execution_deadline(180):positive=cam_verify.fresh_material(cam_directory)
            positive_seconds=time.monotonic()-start
            assert positive['verified'] is True
            report['runtime']=positive['runtime']
            report['checks']['unchangedFreshReplay']={'verified':True,'pid':positive['pid'],'seconds':positive_seconds,
                'programSha256':positive['programSha256'],'nativeSha256':positive['nativeSha256']}
            for control in ('timeout','cancel'):
                launched=threading.Event();cancel=threading.Event();processes=[];commands=[]
                def launch(*args,**kwargs):
                    # Observe the real product launch; never substitute a process,
                    # its result, native output or fault.
                    process=real_popen(*args,**kwargs);processes.append(process)
                    commands.append(list(args[0]));launched.set();return process
                def request_cancel():
                    if launched.wait(10):time.sleep(.25)
                    cancel.set()
                thread=None
                if control=='cancel':
                    thread=threading.Thread(target=request_cancel,daemon=True);thread.start()
                budget=min(2,max(.5,positive_seconds/4)) if control=='timeout' else 15
                start=time.monotonic()
                try:
                    with patch('schemaxis.dispatch.subprocess.Popen',side_effect=launch),allocation({},cancel),execution_deadline(budget):
                        cam_verify.fresh_material(cam_directory)
                except SchemaxisError as error:
                    expected='RUNNER_TIMED_OUT' if control=='timeout' else 'RUNNER_CANCELLED'
                    assert error.fault.code==expected,error.fault.to_dict()
                    assert len(processes)==1 and commands[0][0]==executable,commands
                    assert processes[0].poll() is not None,'native worker remains live'
                    report['checks'][control]={'verified':True,'fault':error.fault.to_dict(),'nativePid':processes[0].pid,
                        'nativeProcessStopped':True,'budget':budget,'elapsed':time.monotonic()-start,'command':commands[0]}
                else:raise AssertionError('actual CAM '+control+' control did not refuse publication')
                finally:
                    cancel.set()
                    if thread is not None:thread.join(11)
            assert report['sourceDigest']==source_digest('freecad'),'source changed during qualification'
            report['verified']=True
    finally:atomic_json(directory/'report.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',required=True);parser.add_argument('--cam-directory',required=True);parser.add_argument('--executable',required=True)
    args=parser.parse_args();print(json.dumps(qualify(args.directory,args.cam_directory,args.executable),indent=2))
