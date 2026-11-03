#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Bounded native static assembly, independent affine literals and tamper probes."""
import argparse
import copy
import json
import math
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from schemaxis.adaptors.godot import run, verify
from schemaxis.adaptors.godot.adaptor import dispatch_stage
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation


def qualify(executable, directory, timeout=30):
    target=Path(directory).resolve(); target.mkdir(parents=True,exist_ok=False)
    examples=Path(__file__).resolve().parents[1]/'examples/schemaxis'
    doc=json.loads((examples/'godot-hierarchy.json').read_text())
    results={}
    a=math.sqrt(0.5)
    # Derivation: local box p=(x,y,z), arm=(a*x-3*a*(y+1)+1,
    # a*x+3*a*(y+1),z), assembly=(10-arm.y,2*arm.x,arm.z).
    expected={'baseline': {'position':[10-3*a,2-6*a,0],
        'basis':[[-a,2*a,0],[-3*a,-6*a,0],[0,0,1]],
        'bounds':[10-7*a,2-14*a,-2,10+a,2+2*a,2],
        'aggregate':[10-7*a,-10,-2,11,2+2*a,2]},
        'variant': {'position':[20-6*a,1-3*a,0],
        'basis':[[-2*a,a,0],[-6*a,-3*a,0],[0,0,1]],
        'bounds':[20-14*a,1-7*a,-2,20+2*a,1+a,2],
        'aggregate':[20-14*a,-5,-2,22,1+a,2]},
        'yxz-order': {'position':[10,2,3], 'basis':[[0,2,0],[0,0,3],[1,0,0]],
        'bounds':[8,0,0,12,4,6], 'aggregate':[8,-10,-1,12,4,6]}}
    for label in ('baseline','variant','yxz-order'):
        source=copy.deepcopy(doc)
        if label=='variant': source['nodes'][3]['options'].update(position=[20,0,0],scale=[1,2,1])
        if label=='yxz-order': source['nodes'][2]['options']['rotation']=[90,90,90]
        results[label]=run(source,target/label,executable,timeout)
        records=json.loads((target/label/'reopened.json').read_text())['scene']['nodes']
        block=records['block']; want=expected[label]
        for key,value in [('worldPosition',want['position']),('worldBasis',want['basis']),('bounds',want['bounds'])]:
            actual=block[key]
            if key=='worldBasis': actual=sum(actual,[]);value=sum(value,[])
            assert len(actual)==len(value) and all(math.isclose(x,y,abs_tol=1e-5,rel_tol=1e-5) for x,y in zip(actual,value)),(label,key,actual,value)
        assert block['parent']=='arm' and records['arm']['parent']=='assembly'
        assert records['empty']['bounds'] is None
        assert all(record['owner']=='.' and record['owned'] for record in records.values())
        for group in ('assembly','arm'):
            assert all(math.isclose(x,y,abs_tol=1e-5,rel_tol=1e-5) for x,y in zip(records[group]['bounds'],want['aggregate'] if group=='assembly' else want['bounds']))
    flat=json.loads((examples/'godot-primitives.json').read_text())
    results['legacyFlat']=run(flat,target/'legacy-flat',executable,timeout)
    receipts={n:json.loads((target/'baseline'/n).read_text()) for n in ('built.json','reopened.json')}
    mutations={
        'parent':lambda r:r['scene']['nodes']['block'].update(parent='assembly'),
        'owner':lambda r:r['scene']['nodes']['block'].update(owner='assembly'),
        'ownership':lambda r:r['scene']['nodes']['arm'].update(owned=False),
        'worldTransform':lambda r:r['scene']['nodes']['block'].update(worldBasis=[[1,0,0],[0,1,0],[0,0,1]]),
        'localTransform':lambda r:r['scene']['nodes']['arm'].update(position=[0,0,0]),
        'worldBounds':lambda r:r['scene']['nodes']['block'].update(bounds=[0]*6),
        'groupBounds':lambda r:r['scene']['nodes']['assembly'].update(bounds=[0]*6),
        'emptyBounds':lambda r:r['scene']['nodes']['empty'].update(bounds=[0]*6),
        'inheritance':lambda r:r['scene']['nodes']['block'].update(topLevel=True),
        'nodeMembership':lambda r:r['scene']['nodes'].pop('empty'),
    }
    rejected=[]
    for name,mutate in mutations.items():
        try:
            for file,original in receipts.items():
                altered=copy.deepcopy(original);mutate(altered);atomic_json(target/'baseline'/file,altered)
            try: verify(target/'baseline')
            except SchemaxisError as error:
                assert error.fault.code=='VERIFICATION_FAILED';rejected.append(name)
            else: raise AssertionError('Jointly forged receipts accepted: '+name)
        finally:
            for file,original in receipts.items(): atomic_json(target/'baseline'/file,original)
    verify(target/'baseline')
    retained=[]
    for mode in ('cancel','timeout'):
        event=threading.Event()
        def delayed(command,directory,stage,budget,environment):
            if stage!='build': return dispatch_stage(command,directory,stage,budget,environment)
            command=list(command);command[command.index('--'):command.index('--')]=['--frame-delay','1000']
            stop=threading.Event()
            def monitor():
                end=time.monotonic()+5
                while not stop.wait(0.01) and time.monotonic()<end:
                    for log in (directory/'.dispatch'/stage).glob('*.stdout.log'):
                        if 'Godot Engine' in log.read_text(): event.set();return
            thread=threading.Thread(target=monitor) if mode=='cancel' else None
            if thread: thread.start()
            try: return dispatch_stage(command,directory,stage,budget,environment)
            finally:
                stop.set()
                if thread: thread.join()
        with allocation({'threads':2},event),patch('schemaxis.adaptors.godot.adaptor.dispatch_stage',side_effect=delayed):
            try: run(doc,target/mode,executable,0.2 if mode=='timeout' else timeout)
            except SchemaxisError as error:
                wanted='RUNNER_CANCELLED' if mode=='cancel' else 'RUNNER_TIMED_OUT'
                assert error.fault.code==wanted,(mode,error.fault)
            else: raise AssertionError('Expected bounded failure')
        failed=json.loads((target/mode/'result.json').read_text())
        assert failed['verified'] is False and failed['fault']['code']==wanted
        assert (target/mode/'build.log').exists() and not (target/mode/'artifacts.json').exists()
        retained.append(wanted)
    # Exercise the common authored/effective input boundary and native workflow reuse.
    from schemaxis import workflow
    authored=copy.deepcopy(doc)
    authored['definitions']={'parent':'arm','placement':[10,0,0]}
    authored['nodes'][1]['inputs']['parent']={'$document':'/definitions/parent'}
    authored['nodes'][3]['options']['position']={'$document':'/definitions/placement'}
    binding=run(authored,target/'binding',executable,timeout)
    assert binding['verified'] and verify(target/'binding')['verified']
    assert json.loads((target/'binding'/'authored.json').read_text())==authored
    effective=json.loads((target/'binding'/'state-00000'/'authored.json').read_text())
    assert effective['nodes'][1]['inputs']['parent']=='arm'
    assert effective['nodes'][3]['options']['position']==[10,0,0]
    wf={'version':'schemaxis.workflow/1','operations':[{'id':'assembly','document':authored}]}
    first=workflow.execute(wf,target/'workflow',locations={'godot':executable},timeout=timeout)
    resumed=workflow.execute(wf,target/'workflow',locations={'godot':executable},timeout=timeout,resume=True)
    assert first['verified'] and resumed['verified']
    assert first['jobs'][0]['reused'] is False and resumed['jobs'][0]['reused'] is True
    assert first['jobs'][0]['directory']==resumed['jobs'][0]['directory']
    summary={'verified':True,'runtime':results['baseline']['runtime'],'results':results,
             'authoredEffectiveBinding':True,'workflowVerifiedReuse':True,
             'literalExpectations':expected,'jointReceiptTamperingRejected':rejected,
             'liveFailureRetention':retained,
             'limits':'Static geometry/group hierarchy only; no animation, physics, sprites/lights/camera parenting or graphical qualification.'}
    atomic_json(target/'qualification.json',summary)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable',required=True)
    parser.add_argument('--directory',required=True)
    parser.add_argument('--timeout',type=float,default=30)
    args=parser.parse_args()
    print(json.dumps(qualify(args.executable,args.directory,args.timeout),indent=2))
