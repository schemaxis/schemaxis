#!/usr/bin/env python3
"""Qualify public physical CAM, exact native authority and editable reduced tools.

Run from the checkout with PYTHONPATH=src, trusted FreeCAD1.1.4 CLI/GUI and an
outer bounded resource envelope. Only this programme's generated native packets
enter controlled GUI edits; this is not general edited-CAM adoption.
"""
import argparse
import copy
import json
import math
from pathlib import Path
import shutil
import threading
from zipfile import ZipFile
from schemaxis import workflow
from schemaxis.adaptors import registry
from schemaxis.adaptor_delivery import source_digest
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.configuration import location_context
from schemaxis.core.faults import SchemaxisError
from schemaxis.core.runners import Interpreter
from schemaxis.dispatch import allocation
from schemaxis.adaptors.freecad.process import SubprocessRunner
from schemaxis.adaptors.freecad import cam_publication
from qualify_freecad_cam import gui_edit
from qualify_freecad_cam_physical_guards import hostile
ROOT=Path(__file__).resolve().parents[1]


def portable_launcher(packet,directory,gui):
    """Execute the actual carried macro after complete installed admission."""
    packet=Path(packet);directory=Path(directory);checked=file_digest(packet/'machining.FCStd')
    assert registry.verify(packet)['verified']
    p=json.loads((packet/'plan.json').read_text());cam_publication.verify(packet,p)
    assert file_digest(packet/'machining.FCStd')==checked
    expected={'machining.FCStd':(packet/'machining.FCStd').read_bytes(),**cam_publication.contents(p)}
    directory.mkdir(parents=True,exist_ok=False)
    with ZipFile(packet/'cam-project.zip') as archive:
        assert tuple(archive.namelist())==tuple(expected)
        for name,data in expected.items():
            # Check the read snapshot again before staging, rather than trust
            # a second read of the publication after its earlier admission.
            assert archive.read(name)==data
            if name.endswith('/'):(directory/name).mkdir()
            else:(directory/name).write_bytes(data)
    assert file_digest(directory/'machining.FCStd')==checked
    atomic_json(directory/'plan.json',p)
    gui_edit(directory,gui,'portable-launcher',worker='physical-launcher',expected_sha=checked)
    result=json.loads((directory/'portable-launcher.json').read_text());assert result['verified']
    assert file_digest(packet/'machining.FCStd')==checked and registry.verify(packet)['verified']
    return result


def source_regimes(directory,run):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False);records=[]
    # Cone radius is u over height1: integrate pi*u^2 on its stock-clipped span.
    # Cylinder radius1 spans the positive-height remainder above its junction.
    # These expectations are independent of the saved native/STEP shape.
    for label,apex,reference,cycle in (
            ('blind',-6.,'tip',{'kind':'drill','return':'initial'}),
            ('clippedCone',-10.5,'fullDiameter',{'kind':'peck','peck':.193,'return':'retract'}),
            ('spot',-.5,'tip',{'kind':'dwell','dwell':.375,'return':'initial'}),
            ('through',-11.5,'fullDiameter',{'kind':'feedRetract','return':'initial'})):
        junction=apex+1.;low=max(0.,-10.-apex);high=min(1.,-apex)
        cone=(high**3-low**3)/3 if high>low else 0.
        cone_m=apex*cone+(high**4-low**4)/4 if high>low else 0.
        bottom=max(-10.,junction);height=max(0.,-bottom)
        removed=math.pi*(cone+height);moment=math.pi*(cone_m-height*height/2)
        producer={'version':'schemaxis.freecad/1','units':'mm','nodes':[
            {'id':'blank','filter':'box','options':{'length':20,'width':20,'height':10,'origin':[-10,-10,-10]}},
            {'id':'cone','filter':'cone','options':{'radius1':1,'radius2':0,'height':1,'origin':[0,0,junction],'axis':[0,0,-1]}},
            {'id':'cylinder','filter':'cylinder','options':{'radius':1,'height':2-junction,'origin':[0,0,junction]}},
            {'id':'void','filter':'fuse','inputs':{'base':'cone','tool':'cylinder'}},
            {'id':'finished','filter':'cut','inputs':{'base':'blank','tool':'void'}}],'output':'finished'}
        case=directory/label;case.mkdir();run(producer,case/'producer')
        op={'id':'bore','operation':'drill','tool':'point','locations':{'kind':'explicit','centres':[[0,0]]},
            'bottom':apex if reference=='tip' else junction,'depthReference':reference,'cycle':cycle}
        if apex<-10:op['throughClearance']=2
        d={'version':'schemaxis.freecad.cam/1','source':{'file':str(case/'producer/model.FCStd'),'object':'finished','units':'mm',
            'expect':{'volume':4000-removed,'bounds':[-10,10,-10,10,-10,0],'centreOfMass':[0,0,(-20000-moment)/(4000-removed)]}},
            'stock':{'top':0},'tools':[{'id':'point','kind':'drill','diameter':2,'tipAngle':90,'cuttingReach':20,'length':40,
                'rpm':6000,'feed':300,'plunge':100,'holder':{'stickOut':25,'steps':[{'diameter':4,'length':20}]}}],
            'operations':[op],'setup':{'toolClearance':{'kind':'aboveBlank','axialClearance':1}}}
        run(d,case/'job');m=json.loads((case/'job/material.json').read_text())
        assert abs(m['removedVolume']-removed)<1e-7 and abs(m['removedCentreOfMass'][2]-moment/removed)<1e-7
        assert m['assessedResidualVolume']<1e-5 and m['assessedGougeVolume']<1e-5
        p=json.loads((case/'job/plan.json').read_text());assert p['operations'][0]['sourceRegime']['kind']==label
        records.append({'case':label,'removedVolume':removed,'removedCentreZ':moment/removed,'sourceRegime':p['operations'][0]['sourceRegime'],'verified':True})
        atomic_json(directory/'source-regimes.json',{'verified':False,'checks':records})
    atomic_json(directory/'source-regimes.json',{'verified':True,'checks':records});return records


def qualify_regimes(directory,executable):
    directory=Path(directory).absolute();directory.mkdir(parents=True,exist_ok=False)
    report={"verified":False,"sourceDigest":source_digest("freecad"),"qualifierSha256":file_digest(Path(__file__)),"scope":"Affected four public source-regime controls only; not a full qualifier rerun."}
    def run(document,target):
        result=registry.run(document,target,locations={"freecad":executable},timeout=240)
        assert result["verified"] and registry.verify(target)["verified"];return result
    try:
        report["checks"]=source_regimes(directory/"cases",run)
        assert report["sourceDigest"]==source_digest("freecad")
        report["verified"]=True
    finally:atomic_json(directory/"report.json",report)
    return report



def reduced_cycles(directory,run):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False);records=[]
    for name,cycle,code in (
        ('peck',{'kind':'peck','peck':.193,'return':'retract'},83),
        ('chipBreak',{'kind':'chipBreak','peck':.193,'return':'initial'},73),
        ('dwell',{'kind':'dwell','dwell':.375,'return':'retract'},82),
        ('feedRetract',{'kind':'feedRetract','return':'initial'},85)):
        document=json.loads((ROOT/'examples/schemaxis/freecad-cam-pointed.json').read_text())
        document['operations'][0]['cycle']=cycle
        run(document,directory/name)
        m=json.loads((directory/name/'material.json').read_text())
        replay=json.loads((directory/name/'replay.json').read_text())
        assert len(replay['cycles'])==1 and replay['cycles'][0]['code']==code
        assert abs(m['removedVolume']-22*math.pi/3)<1e-7 and abs(m['removedCentreOfMass'][2]+323/88)<1e-7
        assert m['minimumObservedGuardGap']>=.25 and m['assessedResidualVolume']<1e-5 and m['assessedGougeVolume']<1e-5
        records.append({'case':name,'verified':True,'cycles':replay['cycles'],'motions':m['motions'],'work':m['work'],'minimumObservedGuardGap':m['minimumObservedGuardGap']})
        atomic_json(directory/'reduced-cycles.json',{'verified':False,'checks':records})
    atomic_json(directory/'reduced-cycles.json',{'verified':True,'checks':records});return records


def qualify_cycles(directory,executable):
    directory=Path(directory).absolute();directory.mkdir(parents=True,exist_ok=False)
    report={'verified':False,'sourceDigest':source_digest('freecad'),'qualifierSha256':file_digest(Path(__file__)),'scope':'Affected reduced-profile G83/G73/G82/G85 phase; original full G81 proof remains source-labelled.'}
    def run(document,target):
        result=registry.run(document,target,locations={'freecad':executable},timeout=240)
        assert result['verified'] and registry.verify(target)['verified'];return result
    try:
        report['checks']=reduced_cycles(directory/'cases',run)
        assert report['sourceDigest']==source_digest('freecad');report['verified']=True
    finally:atomic_json(directory/'report.json',report)
    return report


def qualify(directory,executable,gui):
    directory=Path(directory).absolute();directory.mkdir(parents=True,exist_ok=False)
    report={'verified':False,'sourceDigest':source_digest('freecad'),
            'qualifierSha256':file_digest(Path(__file__)),'checks':{}}
    locations={'freecad':executable,'freecad_gui':gui}
    def record(name,value):report['checks'][name]=value;atomic_json(directory/'report.json',report)
    def run(document,target):
        result=registry.run(document,target,locations=locations,timeout=240)
        assert result['verified'] and registry.verify(target)['verified'];return result
    def worker(function):
        code='import sys\nsys.path.insert(0,'+repr(str(ROOT/'src'))+')\nsys.path.insert(1,'+repr(str(ROOT/'tools'))+')\nfrom qualify_freecad_cam_physical_guards import '+function+'\nfrom schemaxis.native_boundary import execute_guarded\nexecute_guarded('+function+','+repr(str(directory))+')\n'
        runner=SubprocessRunner(Interpreter('freecad',executable),directory,timeout=180)
        atomic_json(directory/(function+'-submission.json'),runner(code).to_dict())
        assert not (directory/'native-fault.json').exists(),(directory/'native-fault.json').read_text()
    try:
        envelope=json.loads((ROOT/'examples/schemaxis/freecad-cam-pointed-workflow.json').read_text())
        record('primary-producer',run(envelope['operations'][0]['document'],directory/'producer'))
        base=copy.deepcopy(envelope['operations'][1]['document'])
        base['source']['file']=str(directory/'producer/model.FCStd')
        packet=directory/'packet';record('public-reduced-native',run(base,packet))
        m=json.loads((packet/'material.json').read_text())
        assert abs(m['removedVolume']-22*math.pi/3)<1e-7
        assert abs(m['removedCentreOfMass'][2]+323/88)<1e-7
        assert m['temporalCredits']>0 and m['minimumObservedGuardGap']>=.25
        record('literal-material',m)
        normal=copy.deepcopy(base);normal['tools'][0].pop('shankDiameter')
        normal['tools'][0].update(cuttingReach=12,length=24,holder={'stickOut':15,'steps':[{'diameter':4,'length':12}]})
        normal['setup']['toolClearance']={'kind':'aboveBlank','axialClearance':1}
        record('unchanged-standard-native-drill',run(normal,directory/'standard'))
        record('four-public-source-regimes',source_regimes(directory/'source-regimes',run))
        record('reduced-profile-other-cycles',reduced_cycles(directory/'reduced-cycles',run))
        # Legacy named flat cycle and milling policies still execute unchanged.
        for name,filename in [('legacy-flat-cycles','freecad-cam-cycles.json'),('legacy-flat-milling','freecad-cam-enclosure.json')]:
            record(name,run(json.loads((ROOT/'examples/schemaxis'/filename).read_text()),directory/name))
        worker('necessary_credit');record('current-needed-credit-and-real-shank-negative',json.loads((directory/'necessary-credit.json').read_text()))
        record('refreshed-public-attacks',hostile(packet))
        worker('native_guards');record('native-zero-open-attacks',json.loads((directory/'native-guards.json').read_text()))
        # Full source/Job/bundle admission precedes native copy/import/open.
        checked=file_digest(packet/'machining.FCStd');assert registry.verify(packet)['verified']
        cam_publication.verify(packet,json.loads((packet/'plan.json').read_text()))
        assert file_digest(packet/'machining.FCStd')==checked
        portable=directory/'portable';portable.mkdir();(portable/'cam-assets').mkdir()
        for name in ('machining.FCStd','plan.json','preferences.cfg'):shutil.copyfile(packet/name,portable/name)
        assert file_digest(portable/'machining.FCStd')==checked
        stages=[]
        for stage in ('reduced-initial','reduced-edit','reduced-reopen','reduced-return','reduced-final'):
            pin=file_digest(portable/'machining.FCStd');gui_edit(portable,gui,stage,worker='physical',expected_sha=pin)
            observed=json.loads((portable/(stage+'.json')).read_text());assert observed['verified']
            stages.append(observed)
        assert len({s['pid'] for s in stages})==5
        assert file_digest(packet/'machining.FCStd')==checked and registry.verify(packet)['verified']
        record('private-GUI-repeated-edits',{'verified':True,'stages':stages,'scope':'Controlled owned GUI edits only, not general edited-CAM adoption.'})
        record('actual-carried-native-launcher',portable_launcher(packet,directory/'portable-launcher',gui))
        wf=directory/'workflow';workflow.execute(envelope,wf,locations=locations,timeout=240);assert workflow.verify(wf)['verified']
        reused=workflow.execute(envelope,wf,locations=locations,timeout=240,resume=True);assert all(j['reused'] for j in reused['jobs'])
        machined=Path(next(j['directory'] for j in reused['jobs'] if j['operation']=='machining'))
        (machined/'program.ngc').write_bytes(b'damaged NC')
        recovered=workflow.execute(envelope,wf,locations=locations,timeout=240,resume=True)
        state={j['operation']:j['reused'] for j in recovered['jobs']};assert state=={'stock':True,'machining':False}
        assert workflow.verify(wf)['verified'];record('workflow-reuse-damage-recovery',state)
        machined=Path(next(j['directory'] for j in recovered['jobs'] if j['operation']=='machining'))
        producer=Path(next(j['directory'] for j in recovered['jobs'] if j['operation']=='stock'))
        source=Path(json.loads((machined/'plan.json').read_text())['source']['file']);pin=file_digest(machined/'machining.FCStd');moves=[]
        try:
            retired=directory/'retired-producer';producer.rename(retired);moves.append((retired,producer))
            if source.exists():
                hidden=source.with_name(source.name+'.retired');source.rename(hidden);moves.append((hidden,source))
            assert not producer.exists() and not source.exists()
            assert registry.verify(machined)['verified'] and file_digest(machined/'machining.FCStd')==pin
            record('standalone-producer-original-retired',{'verified':True,'nativeSha256':pin,'source':str(source)})
        finally:
            for before,after in reversed(moves):before.rename(after)
        assert workflow.verify(wf)['verified']
        step=copy.deepcopy(json.loads((ROOT/'examples/schemaxis/freecad-cam-pointed.json').read_text()))
        original=directory/'original.step';shutil.copyfile(ROOT/step['source']['file'],original);step['source']['file']=str(original)
        record('public-STEP-starter',run(step,directory/'step'))
        retired=directory/'original.retired';original.rename(retired)
        try:assert registry.verify(directory/'step')['verified'];record('original-STEP-retired',True)
        finally:retired.rename(original)
        for label,timeout,token in [('timeout',.03,None),('cancel',240,threading.Event())]:
            timer=threading.Timer(.1,token.set) if token else None
            if timer:timer.start()
            try:
                with allocation({},token):registry.run(step,directory/label,locations=locations,timeout=timeout)
            except SchemaxisError as error:
                assert error.fault.code==('RUNNER_TIMED_OUT' if label=='timeout' else 'RUNNER_CANCELLED'),error.fault
                record(label,error.fault.to_dict())
            else:raise AssertionError('Actual native '+label+' was not refused')
            finally:
                if timer:timer.cancel();timer.join()
        record('recovery-after-interruption',run(step,directory/'recovered'))
        assert report['sourceDigest']==source_digest('freecad'),'Source changed during qualification'
        report['verified']=True
    finally:atomic_json(directory/'report.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',required=True);parser.add_argument('--executable',required=True);parser.add_argument('--gui',required=True);parser.add_argument('--source-regimes-only',action='store_true',help='Run only the four prospective analytic source-regime controls');parser.add_argument('--reduced-cycles-only',action='store_true',help='Run only the four reduced-profile cycle variants');args=parser.parse_args()
    if args.source_regimes_only and args.reduced_cycles_only:parser.error('Choose one affected phase or the complete qualifier')
    with location_context({'freecad':args.executable,'freecad_gui':args.gui}):
        print(json.dumps(qualify_regimes(args.directory,args.executable) if args.source_regimes_only else qualify_cycles(args.directory,args.executable) if args.reduced_cycles_only else qualify(args.directory,args.executable,args.gui),indent=2))
