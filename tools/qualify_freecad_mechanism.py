#!/usr/bin/env python3
"""Bounded prescribed-motion acceptance with independent native/lifecycle controls."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import zipfile
from xml.etree import ElementTree as ET

from schemaxis import workflow
from schemaxis.adaptors.freecad import mechanism,gui_process
from schemaxis.artifacts import atomic_json,runtime_archive
from schemaxis.adaptor_delivery import source_digest
from schemaxis.core.faults import SchemaxisError


def close(actual,wanted):
    assert len(actual)==len(wanted)
    assert all(abs(a-b)<1e-8 for a,b in zip(actual,wanted)),(actual,wanted)


def endpoint(result,wanted):
    p=result['motion']['samples'][-1]['placements']['arm']
    close([p[i] for i in (3,7,11)],wanted)


def members(path):
    with zipfile.ZipFile(path) as archive:return {n:archive.read(n) for n in archive.namelist()}


def write_archive(path,records):
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in records.items():archive.writestr(name,data)


def edited(source,directory,document,gui):
    directory.mkdir();shutil.copyfile(source/'model.FCStd',directory/'model.FCStd')
    prepared=mechanism.plan(document);atomic_json(directory/'plan.json',prepared)
    (directory/'trusted-runtime.zip').write_bytes(runtime_archive())
    record=gui_process.run(directory,gui,'edit',timeout=180)
    mechanism.check_observation(prepared,record['observed'])
    reopened=gui_process.run(directory,gui,'reopen',timeout=180)
    mechanism.check_observation(prepared,reopened['observed'])
    assert record['observed']['pid']!=reopened['observed']['pid']
    return {'pid':record['observed']['pid'],'reopenedPid':reopened['observed']['pid'],
            'duration':prepared['durationSeconds'],'endpoints':prepared['motions']}


def attacks(directory,trusted,*,full=False):
    """Refresh artifact hashes; target exact saved-state guards, never companion faults."""
    original=(directory/'model.FCStd').read_bytes();receipt=(directory/'verification.json').read_bytes()
    records=members(directory/'model.FCStd');root=ET.fromstring(records['Document.xml'])
    mutations={}
    def xml_change(label,action,gui=False):
        name='GuiDocument.xml' if gui else 'Document.xml';xml=ET.fromstring(records[name]);action(xml)
        mutations[label]={name:ET.tostring(xml,encoding='utf-8',xml_declaration=True)}
    def prop(xml,name):
        result=xml.find('.//Property[@name="'+name+'"]')
        assert result is not None,name
        return result
    xml_change('formula',lambda x:prop(x,'Formula')[0].set('value','0*time'))
    xml_change('motionType',lambda x:prop(x,'MotionType')[0].set('value','1'))
    xml_change('simulationEnd',lambda x:prop(x,'bTimeEnd')[0].set('value','999'))
    xml_change('jointEndpoint',lambda x:prop(x,'Reference1')[0].set('value','Component1'))
    xml_change('motionJoint',lambda x:prop(x,'Joint')[0].set('name','Ground'))
    xml_change('nativeProxy',lambda x:next(e for e in x.iter('Python') if e.get('module')=='CommandCreateSimulation').set('module','untrusted_proxy_module'))
    xml_change('initialPose',lambda x:x.find('./ObjectData/Object[@name="Component1"]/Properties/Property[@name="Placement"]/PropertyPlacement').set('Px','123'))
    xml_change('guiProxy',lambda x:next(e for e in x.iter('Python') if e.get('module')=='CommandCreateSimulation').set('module','untrusted_gui_module'),True)
    xml_change('guiTreeRank',lambda x:next(e for e in x.iter('ViewProvider') if 'treeRank' in e.attrib).set('treeRank','999999'),True)
    xml_change('guiCamera',lambda x:x.find('Camera').set('settings','OrthographicCamera { height 999999 }'),True)
    xml_change('guiVisibility',lambda x:next(x.iter('Bool')).set('value','false' if next(x.iter('Bool')).get('value')=='true' else 'true'),True)
    mutations['guiDoctype']={'GuiDocument.xml':records['GuiDocument.xml'].replace(b'<Document ',b'<!DOCTYPE Document []>\n<Document ',1)}
    shape=next(n for n in records if n.endswith('.brp') and records[n]);mutations['shapePayload']={shape:b'not a BREP'}
    gui=ET.fromstring(records['GuiDocument.xml']);payload=next(e.get('file') for e in gui.iter() if e.get('file'))
    mutations['guiPayload']={payload:records[payload]+b'forged'}
    hasher=root.find('StringHasher2')
    if hasher is not None:
        name=hasher.get('file');lines=records[name].splitlines();header=lines[0].split();header[-1]=str(int(header[-1])+1).encode();lines[0]=b' '.join(header);lines.append(b'-1.0 qualifier-unused-string')
        mutations['unusedSID']={name:b'\n'.join(lines)+b'\n'}
        mapname=next(n for n in records if n.endswith('.Map.txt'))
        mutations['topologyMap']={mapname:records[mapname]+b'forged\n'}
    results={}
    try:
        mechanism.compare_saved(directory/'model.FCStd',trusted)
        for label,replacements in mutations.items():
            assert all(records[n]!=data for n,data in replacements.items()),label+' is a NOOP'
            changed={**records,**replacements};write_archive(directory/'model.FCStd',changed)
            publication=json.loads(receipt);publication['artifacts'][0]['sha256']=hashlib.sha256((directory/'model.FCStd').read_bytes()).hexdigest();atomic_json(directory/'verification.json',publication)
            try:mechanism.compare_saved(directory/'model.FCStd',trusted)
            except (ValueError,SchemaxisError) as error:results[label]={'rejected':True,'message':str(error)}
            else:raise AssertionError('semantic saved attack accepted: '+label)
            if full and label in ('formula','guiDoctype'):
                try:mechanism._verify(directory,require_result=True)
                except SchemaxisError as error:results[label]['fullFault']=error.fault.to_dict()
                except ValueError as error:results[label]['fullNativeGuard']=str(error)
                else:raise AssertionError('full native verifier accepted '+label)
    finally:
        (directory/'model.FCStd').write_bytes(original);(directory/'verification.json').write_bytes(receipt)
    assert mechanism._native_verify(directory)['verified']
    return results


def qualify(directory,executable,gui,serial_source=None):
    directory.mkdir(parents=True,exist_ok=False)
    report={'verified':False,'sourceDigest':source_digest('freecad'),'runtime':'1.1.4','checks':{}}
    root=Path(__file__).resolve().parents[1]
    fixture=root/'tests/fixtures/freecad-mechanism-source'
    report['fixtureDigests']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in fixture.iterdir() if p.is_file()}
    try:
        baseline=json.loads((root/'examples/schemaxis/freecad-mechanism.json').read_text());baseline['source']=str(root/baseline['source'])
        slider=json.loads((root/'examples/schemaxis/freecad-mechanism-slider.json').read_text());slider['source']=baseline['source']
        for label,document,wanted in [('hinge',baseline,[-2,16,19]),('slider',slider,[-2,6,31.5])]:
            result=mechanism.run(document,directory/label,executable=executable,gui_executable=gui,timeout=480)
            endpoint(result,wanted);report['checks'][label]={'verified':True,'endpoint':wanted,'samples':result['samples']}
        # Native two-step edit/save/fresh-reopen checks use the finite typed plan.
        change=copy.deepcopy(baseline);change['durationSeconds']=3;change['motions'][0]['end']=-90
        report['checks']['edit1']=edited(directory/'hinge',directory/'edit1',change,gui)
        change['durationSeconds']=1.5;change['motions'][0]['end']=45
        report['checks']['edit2']=edited(directory/'edit1',directory/'edit2',change,gui)
        trusted=directory/'trusted-hinge';mechanism.prepare_directory(trusted,mechanism.plan(baseline))
        gui_process.run(trusted,gui,'build',timeout=180)
        report['checks']['hingeAttacks']=attacks(directory/'hinge',trusted/'model.FCStd',full=True)
        # Prove constructor source admission rejects a proxy mutation before GUI launch.
        source=Path(baseline['source']).parent;forged=directory/'forged-source';forged.mkdir()
        for name in ('model.FCStd','authored.json','plan.json','built.json','verification.json','result.json'):shutil.copyfile(source/name,forged/name)
        records=members(forged/'model.FCStd');xml=ET.fromstring(records['Document.xml']);python=next(xml.iter('Python'));old=python.get('module');python.set('module','untrusted_constructor_proxy');assert old!=python.get('module');records['Document.xml']=ET.tostring(xml);write_archive(forged/'model.FCStd',records)
        receipt=json.loads((forged/'verification.json').read_text());receipt['artifact']['sha256']=hashlib.sha256((forged/'model.FCStd').read_bytes()).hexdigest()
        if 'artifacts' in receipt:receipt['artifacts']=[receipt['artifact']]
        atomic_json(forged/'verification.json',receipt)
        document={**baseline,'source':str(forged/'model.FCStd')}
        from unittest.mock import patch
        with patch.object(gui_process,'run',side_effect=AssertionError('untrusted source reached GUI')):
            try:mechanism.run(document,directory/'must-not-open',executable=executable,gui_executable=gui,timeout=180)
            except SchemaxisError as error:
                assert error.fault.code=='UNSUPPORTED_SOURCE';report['checks']['preOpenProxy']=error.fault.to_dict()
            else:raise AssertionError('untrusted constructor proxy admitted')
        assert not (directory/'must-not-open').exists()
        if serial_source:
            document={'version':mechanism.VERSION,'source':str(serial_source),'durationSeconds':2,'intervals':12,'motions':[{'joint':'closure','kind':'rotation','end':120},{'joint':'sparePlacement','kind':'translation','end':-10}]}
            result=mechanism.run(document,directory/'serial',executable=executable,gui_executable=gui,timeout=600)
            # Held-out literal endpoints derive separately from the known
            # Rz25 ground, (Y,Z,X) mount basis, Rz155 hinge and serial offset.
            # B=(10,-5,8)+Rz25*(5,4,17); lid=B-60*x155;
            # spare=B+4*y155-8*z155. No producer values set these constants.
            observed=json.loads((directory/'serial/build.json').read_text())['observed']['frames'][-1]
            close([observed['lid'][i] for i in (3,7,11)],[-10.140267405348887,50.021950747446276,-.3570957044419707])
            close([observed['spareHousing'][i] for i in (3,7,11)],[6.305028372554173,-4.174712523313454,21.3747688518534])
            report['checks']['serial']={'verified':True,'samples':result['samples'],'independentLiteralNativeEndpoints':True,
                'initialPose':result['motion']['initialPose'],'endPose':result['motion']['samples'][-1]['placements']}
            trusted=directory/'trusted-serial';mechanism.prepare_directory(trusted,mechanism.plan(document));gui_process.run(trusted,gui,'build',timeout=180)
            report['checks']['serialAttacks']=attacks(directory/'serial',trusted/'model.FCStd')
        authored=json.loads((root/'examples/schemaxis/freecad-mechanism-workflow.json').read_text())
        first=workflow.execute(authored,directory/'workflow',locations={'freecad':executable,'freecad_gui':gui},timeout=600)
        assert workflow.verify(directory/'workflow')['verified']
        fixed=next(Path(j['directory']) for j in first['jobs'] if j['operation']=='fixed')
        isolation=json.loads((fixed/'gui_finish-transport.json').read_text())
        assert isolation['completed'] and isolation['isolation']['migrationOffer']=='v1-1'
        report['checks']['configuredAssemblyGuiIsolation']=isolation
        # A legitimate GUI-decorated source is rebuilt with matching private
        # GUI intent. A refreshed-hash hostile GUI proxy must fail before the
        # mechanism stage; only the trusted constructor rebuild may open.
        forged=directory/'forged-gui-source';forged.mkdir()
        for name in ('model.FCStd','authored.json','plan.json','built.json','verification.json','result.json'):shutil.copyfile(fixed/name,forged/name)
        records=members(forged/'model.FCStd');xml=ET.fromstring(records['GuiDocument.xml']);proxy=next(xml.iter('Python'));old=proxy.get('module');proxy.set('module','untrusted_source_gui_proxy');assert old!=proxy.get('module');records['GuiDocument.xml']=ET.tostring(xml);write_archive(forged/'model.FCStd',records)
        receipt=json.loads((forged/'verification.json').read_text());receipt['artifact']['file']='model.FCStd';receipt['artifact']['sha256']=hashlib.sha256((forged/'model.FCStd').read_bytes()).hexdigest()
        if 'artifacts' in receipt:receipt['artifacts']=[receipt['artifact']]
        atomic_json(forged/'verification.json',receipt)
        original_gui=gui_process.run;allowed=[]
        def private_source_only(path,executable,stage,**options):
            assert options.get('family')=='assembly' and Path(path).name=='assembly','untrusted source reached mechanism GUI'
            allowed.append(str(path));return original_gui(path,executable,stage,**options)
        document={**baseline,'source':str(forged/'model.FCStd')}
        with patch.object(gui_process,'run',side_effect=private_source_only):
            try:mechanism.run(document,directory/'must-not-open-gui',executable=executable,gui_executable=gui,timeout=240)
            except SchemaxisError as error:
                assert error.fault.code=='UNSUPPORTED_SOURCE' and allowed;report['checks']['preOpenGuiProxy']=error.fault.to_dict()
            else:raise AssertionError('hostile source GUI proxy admitted')
        second=workflow.execute(authored,directory/'workflow',locations={'freecad':executable,'freecad_gui':gui},timeout=600,resume=True)
        assert all(j['reused'] for j in second['jobs']);report['checks']['workflowReuse']=True
        target=next(Path(j['directory'])/'model.FCStd' for j in second['jobs'] if j['operation']=='motion');target.write_bytes(b'broken')
        third=workflow.execute(authored,directory/'workflow',locations={'freecad':executable,'freecad_gui':gui},timeout=600,resume=True)
        assert any(not j['reused'] and j['operation']=='motion' for j in third['jobs']);report['checks']['workflowDamageRebuild']=True
        assert source_digest('freecad')==report['sourceDigest'],'source changed during qualification'
        report['verified']=True
        return report
    finally:atomic_json(directory/'report.json',report)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',required=True,type=Path)
    parser.add_argument('--executable',required=True);parser.add_argument('--gui-executable',required=True);parser.add_argument('--serial-source',type=Path)
    args=parser.parse_args();print(json.dumps(qualify(args.directory.absolute(),args.executable,args.gui_executable,args.serial_source),indent=2))
