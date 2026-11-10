#!/usr/bin/env python3
"""Qualify distinct authored CAM identities across native, GUI and reuse paths."""
import argparse
import copy
import json
from pathlib import Path
import shutil
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from schemaxis import workflow
from schemaxis.adaptors import registry
from schemaxis.adaptors.freecad import cam
from schemaxis.adaptors.freecad.cam_names import operation_names
from schemaxis.adaptors.freecad.cam_publication import publish
from schemaxis.adaptor_delivery import source_digest
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.configuration import location_context
from schemaxis.core.faults import SchemaxisError

ROOT=Path(__file__).resolve().parents[1]


def qualify(directory,executable,gui,legacy):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    report={'verified':False,'sourceDigest':source_digest('freecad'),'checks':{}}
    locations={'freecad':executable}
    def record(key,value):
        report['checks'][key]=value;atomic_json(directory/'report.json',report)
    try:
        with location_context(locations):
            envelope=json.loads((ROOT/'examples/schemaxis/freecad-cam-drilling-workflow.json').read_text())
            operations=envelope['operations'][1]['document']['operations']
            operations[0]['id']='pilot-hole';operations[1]['id']='pilot_hole'
            third=copy.deepcopy(operations[0]);third.update(id='SCX0',cycle={'kind':'feedRetract','return':'initial'});operations.append(third)
            atomic_json(directory/'authored-workflow.json',envelope)
            state=workflow.execute(envelope,directory/'workflow',locations=locations,timeout=240)
            record('workflow',workflow.verify(directory/'workflow'))
            target=Path(next(j['directory'] for j in state['jobs'] if j['operation']=='machining'))
            producer=Path(next(j['directory'] for j in state['jobs'] if j['operation']=='stock'))
            p=json.loads((target/'plan.json').read_text());names=operation_names(p)
            assert list(names.items())==[('pilot-hole','Op_SCX1'),('pilot_hole','Op_pilot_hole'),('SCX0','Op_SCX0')]
            for stage in ('built','reopened'):
                observed=json.loads((target/(stage+'.json')).read_text())
                assert observed['job']['operations']==list(names.values())
                assert [(o['id'],o['name']) for o in observed['operations']]==list(names.items())
                assert [o['tool'] for o in observed['operations']]==['Cutter0','Cutter1','Cutter0']
            replay=json.loads((target/'replay.json').read_text())
            assert [t['number'] for t in replay['toolChanges']]==[1,2,1]
            assert [c['code'] for c in replay['cycles']]==[81,83,85]
            material=json.loads((target/'material.json').read_text())
            import math
            assert abs(material['removedVolume']-24*math.pi)<1e-7
            record('identity-cycle-tool-material',{'mapping':names,'removedVolume':material['removedVolume'],'literalRemovedVolume':'24*pi','cycles':[81,83,85],'tools':[1,2,1]})
            resumed=workflow.execute(envelope,directory/'workflow',locations=locations,timeout=240,resume=True)
            assert all(j['reused'] for j in resumed['jobs']);record('reuse',resumed)
            kept={name:(target/name).read_bytes() for name in ('machining.FCStd','material.json','cam-project.zip','verification.json','preferences.cfg','built.json','reopened.json')}
            guards={}
            try:
                # Editable observations cannot reinterpret a sanitized alias as
                # the authored hyphen identity, even with both receipts forged.
                for stage in ('built','reopened'):
                    data=json.loads(kept[stage+'.json']);data['operations'][0]['name']='Op_pilot_hole';atomic_json(target/(stage+'.json'),data)
                try:cam._native_verify(target)
                except SchemaxisError as error:guards['coforged-native-alias']=error.fault.to_dict()
                else:raise AssertionError('Coforged alias accepted')
                for name,data in kept.items():(target/name).write_bytes(data)
                with ZipFile(target/'machining.FCStd') as archive:members={n:archive.read(n) for n in archive.namelist()}
                xml=ET.fromstring(members['Document.xml'])
                prop=xml.find("./ObjectData/Object[@name='Op_SCX1']/Properties/Property[@name='ToolController']")[0]
                prop.set('value','Cutter1')
                with ZipFile(target/'machining.FCStd','w') as archive:
                    for name,data in members.items():archive.writestr(name,ET.tostring(xml) if name=='Document.xml' else data)
                data=json.loads(kept['material.json']);data['nativeSha256']=file_digest(target/'machining.FCStd');atomic_json(target/'material.json',data);publish(target,'1.1.4')
                try:cam._native_verify(target)
                except SchemaxisError as error:guards['refreshed-wrong-tool-binding']=error.fault.to_dict()
                else:raise AssertionError('Changed compiled tool binding accepted')
            finally:
                for name,data in kept.items():(target/name).write_bytes(data)
            record('refusals',guards);record('restored',registry.verify(target))
            from qualify_freecad_cam import gui_edit
            portable=directory/'portable';portable.mkdir()
            with ZipFile(target/'cam-project.zip') as archive:archive.extractall(portable)
            shutil.copyfile(target/'plan.json',portable/'plan.json')
            gui_edit(portable,gui,'edit',worker='drilling',expected_sha=file_digest(portable/'machining.FCStd'))
            pin=file_digest(portable/'machining.FCStd');gui_edit(portable,gui,'reopen',worker='drilling',expected_sha=pin)
            assert file_digest(portable/'machining.FCStd')==pin
            a=json.loads((portable/'edit.json').read_text());b=json.loads((portable/'reopen.json').read_text());assert a['verified'] and b['verified'] and a['pid']!=b['pid']
            edited=json.loads((target/'authored.json').read_text());edited['tools'][1]['plunge']=105;edited['operations'][1]['cycle']['peck']=1.375
            registry.run(edited,directory/'edited-reference',locations=locations,timeout=240)
            assert (portable/'edit.ngc').read_bytes()==(portable/'reopen.ngc').read_bytes()==(directory/'edited-reference/program.ngc').read_bytes()
            record('GUI-edit-reopen-exact-repost',{'edit':a,'freshReopen':b,'typedReference':registry.verify(directory/'edited-reference')})
            native_sha=file_digest(target/'machining.FCStd');retired=directory/'retired-producer';producer.rename(retired)
            try:record('producer-retired-standalone',registry.verify(target));assert file_digest(target/'machining.FCStd')==native_sha
            finally:retired.rename(producer)
            legacy=Path(legacy).resolve();record('legacy-safe-historical-current',cam._native_verify(legacy))
            old=json.loads((legacy/'authored.json').read_text());assert len(old['operations'])==2
            old['source']['file']=str(legacy/json.loads((legacy/'plan.json').read_text())['source']['capture'])
            old['operations'][0]['id']='pilot-hole';old['operations'][1]['id']='pilot_hole'
            record('legacy-hyphen-current-build',registry.run(old,directory/'legacy-hyphen',locations=locations,timeout=240))
            record('legacy-hyphen-fresh',registry.verify(directory/'legacy-hyphen'))
        assert source_digest('freecad')==report['sourceDigest'];report['verified']=True
    finally:atomic_json(directory/'report.json',report)
    return report


def legacy_tail(directory,executable,legacy,prior):
    """Finish only the legacy case after an unrelated fixture-path failure.

    Preserve every prior report unchanged and require its exact provider pin.
    This is phase reuse, not relabelling a failed full invocation as passed.
    """
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    prior=Path(prior).resolve();old_report=json.loads((prior/'report.json').read_text())
    assert old_report['sourceDigest']==source_digest('freecad')
    required={'workflow','identity-cycle-tool-material','reuse','refusals','restored',
              'GUI-edit-reopen-exact-repost','producer-retired-standalone','legacy-safe-historical-current'}
    assert set(old_report['checks'])==required
    report={'verified':False,'sourceDigest':source_digest('freecad'),
            'retainedCompletedPhases':{'report':str(prior/'report.json'),'sha256':file_digest(prior/'report.json'),
                                      'keys':sorted(required),'originalAggregatePassed':False},'checks':{}}
    try:
        legacy=Path(legacy).resolve();authored=json.loads((legacy/'authored.json').read_text())
        authored['source']['file']=str(legacy/json.loads((legacy/'plan.json').read_text())['source']['capture'])
        assert len(authored['operations'])==2
        authored['operations'][0]['id']='pilot-hole';authored['operations'][1]['id']='pilot_hole'
        locations={'freecad':executable}
        with location_context(locations):
            report['checks']['legacy-hyphen-current-build']=registry.run(authored,directory/'legacy-hyphen',locations=locations,timeout=240)
            report['checks']['legacy-hyphen-fresh']=registry.verify(directory/'legacy-hyphen')
            observations=json.loads((directory/'legacy-hyphen/built.json').read_text())
            assert [(o['id'],o['name']) for o in observations['operations']]==[('pilot-hole','Op_SCX0'),('pilot_hole','Op_pilot_hole')]
        assert source_digest('freecad')==report['sourceDigest'];report['verified']=True
    finally:atomic_json(directory/'report.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory');parser.add_argument('--executable',required=True);parser.add_argument('--gui',required=True);parser.add_argument('--legacy',required=True);parser.add_argument('--legacy-tail-from')
    args=parser.parse_args();result=(legacy_tail(args.directory,args.executable,args.legacy,args.legacy_tail_from) if args.legacy_tail_from else qualify(args.directory,args.executable,args.gui,args.legacy));print(json.dumps({'verified':result['verified'],'sourceDigest':result['sourceDigest']}))
