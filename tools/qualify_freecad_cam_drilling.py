#!/usr/bin/env python3
"""Qualify named flat-tool drilling, controller state and durable CAM workflows.

Run from the checkout root with PYTHONPATH=src and the trusted FreeCAD1.1.4 CLI
and GUI. Only synthetic programme-generated native projects are restored. The
GUI edit output is pinned by the host for its controlled separate reopen; this
is not a general edited-CAM-project adoption contract.
"""
import argparse
import base64
import copy
import json
import math
import re
from pathlib import Path
import shutil
import threading
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from schemaxis import workflow
from schemaxis.adaptor_delivery import source_digest
from schemaxis.adaptors import registry
from schemaxis.adaptors.freecad import cam
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.configuration import location_context
from schemaxis.core.faults import SchemaxisError
from schemaxis.core.runners import Interpreter
from schemaxis.dispatch import allocation
from schemaxis.adaptors.freecad.process import SubprocessRunner

ROOT=Path(__file__).resolve().parents[1]


def hostile(target):
    """Provider boundary: refresh every native/publication companion hash.

    Outer runtime metadata is a separate gate. These attacks deliberately reach
    the provider instead of claiming that a stale outer hash proved authority.
    """
    from schemaxis.adaptors.freecad.cam_publication import publish
    names=('machining.FCStd','material.json','cam-project.zip','verification.json','preferences.cfg','built.json','reopened.json','program.ngc','replay.json','plan.json','source.brep')
    original={n:(target/n).read_bytes() for n in names};report={}
    with ZipFile(target/'machining.FCStd') as archive:members={n:archive.read(n) for n in archive.namelist()}
    def prop(root,obj,name):
        value=root.find("./ObjectData/Object[@name='"+obj+"']/Properties/Property[@name='"+name+"']")
        assert value is not None,(obj,name)
        return value
    def attribute(root,obj,name,key,value):prop(root,obj,name)[0].set(key,value)
    def proxy(root):
        node=prop(root,'MillingTool1','Proxy')[0];state=json.loads(base64.b64decode(node.get('value')))
        state['_obj_data']['parameter']['Diameter']='2.01 mm'
        node.set('value',base64.b64encode(json.dumps(state).encode()).decode())
    changes=[('tool-number',lambda r:attribute(r,'Cutter1','ToolNumber','value','9')),
             ('selected-tool',lambda r:attribute(r,'Op_small','ToolController','value','Cutter0')),
             ('peck',lambda r:attribute(r,'Op_small','PeckDepth','value','1.5')),
             ('proxy-module',lambda r:attribute(r,'MillingTool1','Proxy','module','foreign.module')),
             ('proxy-geometry-state',proxy),
             ('persistent-role',lambda r:prop(r,'Op_small','PeckDepth').set('status','4')),
             ('missing-target',lambda r:prop(r,'Op_small','Base')[0].remove(prop(r,'Op_small','Base')[0][0]))]
    def reject(label):
        try:cam._native_verify(target)
        except SchemaxisError as e:
            report[label]=e.fault.to_dict();atomic_json(target/'hostile.json',report)
        else:raise AssertionError(label+' modified CAM2 accepted')
    try:
        for label,change in changes:
            root=ET.fromstring(members['Document.xml']);change(root)
            with ZipFile(target/'machining.FCStd','w') as archive:
                for name,data in members.items():archive.writestr(name,ET.tostring(root) if name=='Document.xml' else data)
            material=json.loads(original['material.json']);material['nativeSha256']=file_digest(target/'machining.FCStd');atomic_json(target/'material.json',material);publish(target,'1.1.4')
            reject(label)
            for name,data in original.items():(target/name).write_bytes(data)
        for label,member,data in [('extra-native-resource','foreign.bin',b'foreign'),('foreign-gui-state','GuiDocument.xml',b'<Document SchemaVersion="1"><ViewProviderData Count="0"/></Document>')]:
            with ZipFile(target/'machining.FCStd','a') as archive:archive.writestr(member,data)
            material=json.loads(original['material.json']);material['nativeSha256']=file_digest(target/'machining.FCStd');atomic_json(target/'material.json',material);publish(target,'1.1.4');reject(label)
            for name,data in original.items():(target/name).write_bytes(data)
        for label,postfix in [('unused-map-foreign-owner',';:H7fffffff,F'),
                              ('unused-map-foreign-string','#7fffffff'),
                              ('unused-map-literal','unused-owner-proof')]:
            member='Clone.Shape.Map.txt';lines=members[member].decode('ascii').splitlines()
            header=re.fullmatch(r'(\d+) PostfixCount (\d+)',lines[1]);assert header
            count=int(header[2]);lines[1]=header[1]+' PostfixCount '+str(count+1);lines.insert(2+count,postfix)
            with ZipFile(target/'machining.FCStd','w') as archive:
                for name,data in members.items():archive.writestr(name,('\n'.join(lines)+'\n').encode() if name==member else data)
            material=json.loads(original['material.json']);material['nativeSha256']=file_digest(target/'machining.FCStd');atomic_json(target/'material.json',material);publish(target,'1.1.4');reject(label)
            for name,data in original.items():(target/name).write_bytes(data)
        # Refresh the witness and companions after a changed actual program;
        # typed peck intent and complete fresh reconstruction remain authority.
        nc=original['program.ngc'];changed=nc.replace(b'Q2.25000000',b'Q1.50000000');assert changed!=nc
        (target/'program.ngc').write_bytes(changed)
        material=json.loads(original['material.json']);material['programSha256']=file_digest(target/'program.ngc');atomic_json(target/'material.json',material);publish(target,'1.1.4');reject('changed-posted-peck')
        for name,data in original.items():(target/name).write_bytes(data)
        plan=json.loads(original['plan.json']);plan['operations'][1]['cycle']['peck']=1.5;atomic_json(target/'plan.json',plan);reject('coforged-plan')
        for name,data in original.items():(target/name).write_bytes(data)
        material=json.loads(original['material.json']);material['assessedResidualVolume']=.001;atomic_json(target/'material.json',material);reject('coforged-material')
        for name,data in original.items():(target/name).write_bytes(data)
        material=json.loads(original['material.json']);material['tracks']=float(material['tracks']);atomic_json(target/'material.json',material);reject('coforged-count-type')
        for name,data in original.items():(target/name).write_bytes(data)
        (target/'source.brep').write_bytes(original['source.brep']+b'\nforeign');reject('replaced-working-source')
    finally:
        for name,data in original.items():(target/name).write_bytes(data)
    assert cam._native_verify(target)['verified'];report['unchanged-restored-control']=True
    return report


def qualify(directory,executable,gui):
    directory=Path(directory).absolute();directory.mkdir(parents=True,exist_ok=False)
    locations={'freecad':executable};report={'verified':False,'sourceDigest':source_digest('freecad'),'checks':{}}
    def record(name,value):report['checks'][name]=value;atomic_json(directory/'report.json',report)
    runner=SubprocessRunner(Interpreter('freecad',executable),directory,timeout=90)
    def run(document,target):
        result=registry.run(document,target,locations=locations,timeout=240)
        assert registry.verify(target)['verified'];return result
    try:
        code='import sys\nsys.path.insert(0,'+repr(str(ROOT/'tools'))+')\nsys.path.insert(0,'+repr(str(ROOT/'src'))+')\nfrom qualify_freecad_cam_drilling_native import source\nfrom schemaxis.native_boundary import execute_guarded\nexecute_guarded(source,'+repr(str(directory))+')\n'
        atomic_json(directory/'source-submission.json',runner(code).to_dict())
        assert not (directory/'native-fault.json').exists()
        oracles=json.loads((directory/'source-oracles.json').read_text())
        base=json.loads((ROOT/'examples/schemaxis/freecad-cam-counterbore.json').read_text());base['source'].update(file=str(directory/'counterbore.FCStd'),object='Solid')
        assert abs(base['source']['expect']['volume']-oracles['counterbore']['volume'])<1e-7
        assert max(abs(a-b) for a,b in zip(base['source']['expect']['centreOfMass'],oracles['counterbore']['centreOfMass']))<1e-7
        assert base['source']['expect']['bounds']==oracles['counterbore']['bounds']
        target=directory/'baseline';record('baseline',run(base,target))
        material=json.loads((target/'material.json').read_text());assert abs(material['removedVolume']-24*math.pi)<1e-7 and material['tracks']==2
        expected={(-12,-8):720,(-8,-2):720-math.pi,(-2,0):720-9*math.pi}
        assert all(abs(s['remainingArea']-expected[(s['bottom'],s['top'])])<1e-7 for s in material['slabs'])
        record('independent-concentric-sections',{'removedVolume':material['removedVolume'],'expected':24*math.pi,'tracks':2,'slabs':material['slabs']})
        variant=json.loads((ROOT/'examples/schemaxis/freecad-cam-cycles.json').read_text());variant['source']['file']=str(directory/'counterbore.step')
        record('three-cycle-tool-return',run(variant,directory/'cycles'))
        replay=json.loads((directory/'cycles/replay.json').read_text())
        assert [t['number'] for t in replay['toolChanges']]==[2,1,2]
        assert [(c['code'],c['returnZ']) for c in replay['cycles']]==[(82,3),(73,5),(85,5)]
        assert replay['cycles'][0]['dwell']==.375
        peck=[m for m in replay['motions'] if m.get('cycle')==1]
        assert any(m['code']==0 and abs(m['to'][2]-3.117)<1e-12 for m in peck)
        depths=[m['to'][2] for m in peck if m['code']==1]
        assert len(depths)==81 and abs(depths[-2]+7.96)<1e-12 and depths[-1]==-8
        assert [m['to'][2] for m in replay['motions'] if m.get('cycle')==2 and m['code']==1]==[-2,3]
        ring=copy.deepcopy(base);ring.pop('tools');ring['tool']={k:v for k,v in base['tools'][1].items() if k not in ('id','kind')};ring['tool'].update(diameter=3.175,shankDiameter=3.175,plunge=112.5)
        ring['source'].update(file=str(directory/'ring.FCStd'),expect=oracles['ring'])
        ring['operations']=[{'id':'ring','operation':'drill','locations':{'kind':'pitchCircle','count':4,'radius':7,'phase':30,'centre':[3,18]},'bottom':5.75,'cycle':{'kind':'peck','peck':1.7,'return':'retract'}}]
        record('fractional-ring-single-tool',run(ring,directory/'ring-job'))
        m=json.loads((directory/'ring-job/material.json').read_text());assert abs(m['removedVolume']-25*math.pi*1.5875**2)<1e-7
        record('refreshed-attacks',hostile(target))
        # Actual private GUI editing of only the controlled current baseline.
        from qualify_freecad_cam import gui_edit
        portable=directory/'portable';portable.mkdir()
        with ZipFile(target/'cam-project.zip') as archive:archive.extractall(portable)
        shutil.copyfile(target/'plan.json',portable/'plan.json')
        pin=file_digest(portable/'machining.FCStd');gui_edit(portable,gui,'edit',worker='drilling',expected_sha=pin)
        pin=file_digest(portable/'machining.FCStd');gui_edit(portable,gui,'reopen',worker='drilling',expected_sha=pin)
        a=json.loads((portable/'edit.json').read_text());b=json.loads((portable/'reopen.json').read_text());assert a['pid']!=b['pid'] and file_digest(portable/'machining.FCStd')==pin
        edited=copy.deepcopy(base);edited['tools'][1]['plunge']=105;edited['operations'][1]['cycle']['peck']=1.375
        record('typed-native-edit-reference',run(edited,directory/'edited-reference'))
        assert (portable/'edit.ngc').read_bytes()==(portable/'reopen.ngc').read_bytes()==(directory/'edited-reference/program.ngc').read_bytes()
        assert a['programSha256']==b['programSha256']==file_digest(portable/'edit.ngc')
        geometric=('Source.Shape.brp','Clone.Shape.brp','MillingTool0.Shape.brp','MillingTool1.Shape.brp')
        with ZipFile(target/'machining.FCStd') as original,ZipFile(portable/'machining.FCStd') as saved:
            assert all(original.read(name)==saved.read(name) for name in geometric)
        record('private-GUI-edit-reopen-exact-repost',{'verified':True,'edit':a,'freshReopen':b,'exactFreshTypedProgram':True,'exactUnchangedSourceAndCutterBREPs':list(geometric),'scope':'Controlled generated GUI output only; no arbitrary edited-CAM adoption or GUI archive admission.'})
        envelope=json.loads((ROOT/'examples/schemaxis/freecad-cam-drilling-workflow.json').read_text());wf=directory/'workflow'
        workflow.execute(envelope,wf,locations=locations,timeout=240);assert workflow.verify(wf)['verified']
        reused=workflow.execute(envelope,wf,locations=locations,timeout=240,resume=True);assert all(j['reused'] for j in reused['jobs'])
        native_job=Path(next(j['directory'] for j in reused['jobs'] if j['operation']=='machining'));(native_job/'program.ngc').write_text('damaged program')
        recovered=workflow.execute(envelope,wf,locations=locations,timeout=240,resume=True);state={j['operation']:j['reused'] for j in recovered['jobs']};assert state=={'stock':True,'machining':False};assert workflow.verify(wf)['verified']
        record('workflow-reuse-damage-recovery',state)
        native_job=Path(next(j['directory'] for j in recovered['jobs'] if j['operation']=='machining'))
        producer=Path(next(j['directory'] for j in recovered['jobs'] if j['operation']=='stock'))
        retired_producer=directory/'retired-stock-producer';producer.rename(retired_producer)
        try:assert registry.verify(native_job)['verified']
        finally:retired_producer.rename(producer)
        record('standalone-CAM-producer-packet-removal',True)
        # Retirement of producer/native original does not remove captured source authority.
        source=directory/'counterbore.FCStd';retired=directory/'counterbore.retired';source.rename(retired)
        try:assert registry.verify(target)['verified']
        finally:retired.rename(source)
        record('original-source-removal',True)
        for label,timeout,token in [('timeout',.03,None),('cancel',240,threading.Event())]:
            timer=threading.Timer(.1,token.set) if token else None
            if timer:timer.start()
            try:
                with allocation({},token):registry.run(base,directory/label,locations=locations,timeout=timeout)
            except SchemaxisError as error:
                assert error.fault.code==('RUNNER_TIMED_OUT' if label=='timeout' else 'RUNNER_CANCELLED'),error.fault
                record(label,error.fault.to_dict())
            else:raise AssertionError('actual native '+label+' was not refused')
            finally:
                if timer:timer.cancel();timer.join()
        record('recovery-after-interruption',run(base,directory/'recovered'))
        assert report['sourceDigest']==source_digest('freecad'),'Source changed during qualification'
        report['verified']=True
    finally:atomic_json(directory/'report.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',required=True);parser.add_argument('--executable',required=True);parser.add_argument('--gui',required=True);args=parser.parse_args()
    with location_context({'freecad':args.executable,'freecad_gui':args.gui}):
        print(json.dumps(qualify(args.directory,args.executable,args.gui),indent=2))
