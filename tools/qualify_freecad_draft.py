#!/usr/bin/env python3
"""Qualify typed mould-release histories, native edits and retained assembly sources."""
import argparse,copy,json,math,shutil
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile,ZIP_DEFLATED
from unittest.mock import patch
from schemaxis.adaptor_delivery import source_digest
from schemaxis.adaptors import registry
from schemaxis.adaptors.freecad import adaptor,assembly
from schemaxis.adaptors.freecad.process import SubprocessRunner
from schemaxis.artifacts import atomic_json,file_digest,runtime_archive
from schemaxis.configuration import location_context
from schemaxis.core.faults import SchemaxisError,Fault
from schemaxis.core.runners import Interpreter
from schemaxis import workflow
from freecad_draft_cases import load,tilted,oracle,changed
ROOT=Path(__file__).resolve().parents[1]


def changed_xml(original, root):
    """Keep FreeCAD's fixed declaration/comment while mutating saved semantics."""
    prefix=original.split(b'<Document ',1)[0]
    assert prefix and original.startswith(prefix+b'<Document ')
    return prefix+ET.tostring(root)


def attacks(target):
    path=target/'model.FCStd';receiptpath=target/'verification.json';original=path.read_bytes();receiptbytes=receiptpath.read_bytes()
    document=json.loads((target/'authored.json').read_text());name='N'+str(next(i for i,n in enumerate(document['nodes']) if n['id']=='release'))
    with ZipFile(path) as archive:members={n:archive.read(n) for n in archive.namelist()}
    def prop(root,key):return root.find("./ObjectData/Object[@name='%s']/Properties/Property[@name='%s']"%(name,key))
    changes={'angle':lambda r:prop(r,'Angle').find('Float').set('value','7'),
      'angle-type':lambda r:prop(r,'Angle').set('type','App::PropertyFloat'),
      'reverse':lambda r:prop(r,'Reversed').find('Bool').set('value','true'),
      'suppressed':lambda r:prop(r,'Suppressed').find('Bool').set('value','true'),
      'support-transform':lambda r:prop(r,'SupportTransform').find('Bool').set('value','true'),
      'fuzzy-tolerance':lambda r:prop(r,'FuzzyTolerance').find('Float').set('value','0.1'),
      'base-face':lambda r:prop(r,'Base').find('LinkSub/Sub').set('value','Face5'),
      'neutral-plane':lambda r:prop(r,'NeutralPlane').find('LinkSub').set('value','N2'),
      'pull-reference':lambda r:prop(r,'PullDirection').find('LinkSub').set('value','N2'),
      'base-history':lambda r:prop(r,'BaseFeature').find('Link').set('value','N1')}
    report={}
    for label,mutate in changes.items():
        try:
            root=ET.fromstring(members['Document.xml']);before=ET.tostring(root);mutate(root);assert ET.tostring(root)!=before,label
            with ZipFile(path,'w',ZIP_DEFLATED) as archive:
                for n,data in members.items():archive.writestr(n,changed_xml(data,root) if n=='Document.xml' else data)
            receipt=json.loads(receiptbytes);receipt['artifacts'][2]['sha256']=file_digest(path);atomic_json(receiptpath,receipt)
            try:adaptor._verify(target)
            except SchemaxisError as error:
                assert error.fault.code=='VERIFICATION_FAILED' and not any(word in error.fault.message.lower() for word in ('digest','hash')),error.fault.to_dict()
                report[label]=error.fault.to_dict()
            else:raise AssertionError('saved Draft mutation accepted: '+label)
        finally:path.write_bytes(original);receiptpath.write_bytes(receiptbytes)
    assert registry.verify(target)['verified'];report['unchangedControl']=True
    return report


def source_attacks(target,source):
    authored=json.loads((target/'authored.json').read_text())
    path=source/'model.FCStd';receiptpath=source/'verification.json';original=path.read_bytes();receiptbytes=receiptpath.read_bytes()
    with ZipFile(path) as archive:members={n:archive.read(n) for n in archive.namelist()}
    report={}
    for label,kind,tag,attributes in (
        ('foreignDraftProperty','App::PropertyBool','Bool',{'value':'true'}),
        ('foreignDraftPythonProperty','App::PropertyPythonObject','Python',{'value':'untrusted-proxy-marker','encoded':'no'})):
        try:
            root=ET.fromstring(members['Document.xml'])
            props=root.find("./ObjectData/Object[@name='N3']/Properties")
            added=ET.SubElement(props,'Property',{'name':'ForbiddenProbe','type':kind})
            ET.SubElement(added,tag,attributes)
            props.set('Count',str(int(props.get('Count'))+1))
            with ZipFile(path,'w',ZIP_DEFLATED) as archive:
                for n,data in members.items():archive.writestr(n,changed_xml(data,root) if n=='Document.xml' else data)
            receipt=json.loads(receiptbytes);receipt['artifacts'][2]['sha256']=file_digest(path);atomic_json(receiptpath,receipt)
            with patch('subprocess.Popen',side_effect=AssertionError('source admission launched a native process')) as launch:
                try:assembly._native_plan(authored)
                except SchemaxisError as error:
                    assert error.fault.code=='UNSUPPORTED_SOURCE',error.fault.to_dict()
                    if tag=='Python':
                        assert error.fault.observed.get('element')=='Python',error.fault.to_dict()
                        assert 'vocabulary' in error.fault.message,error.fault.to_dict()
                    else:assert 'propert' in error.fault.message.lower(),error.fault.to_dict()
                    report[label]=error.fault.to_dict()
                else:raise AssertionError('foreign Draft restore property admitted')
                launch.assert_not_called()
        finally:path.write_bytes(original);receiptpath.write_bytes(receiptbytes)
    assembly._native_plan(authored);report['unchangedControl']=True
    return report


def forged_witness_attack(target):
    """Refresh all mutable transport records while forging both face witnesses."""
    files=('model.FCStd','built.json','verification.json','model.FCStd.metadata.json','publication-metadata.json')
    original={name:(target/name).read_bytes() for name in files}
    authored=json.loads((target/'authored.json').read_text())
    name='N'+str(next(i for i,n in enumerate(authored['nodes']) if n['id']=='release'))
    built=json.loads(original['built.json']);receipt=json.loads(original['verification.json'])
    feature=built['partDesignObservations']['features']['release'];before=list(feature['base'][1])
    chosen=int(before[0][4:]);unused=next(f['index'] for f in feature['faceInventory'] if 'Face'+str(f['index']) not in before)
    try:
        for observations in (built['partDesignObservations'],receipt['partDesignObservations']):
            record=observations['features']['release'];record['base'][1][0]='Face'+str(unused)
            inventory=record['faceInventory'];left=copy.deepcopy(inventory[chosen-1]);right=copy.deepcopy(inventory[unused-1])
            inventory[chosen-1]={**right,'index':chosen};inventory[unused-1]={**left,'index':unused}
        with ZipFile(target/'model.FCStd') as archive:members={n:archive.read(n) for n in archive.namelist()}
        root=ET.fromstring(members['Document.xml'])
        sub=root.find("./ObjectData/Object[@name='%s']/Properties/Property[@name='Base']/LinkSub/Sub"%name)
        assert sub.get('value')=='Face'+str(chosen);sub.set('value','Face'+str(unused))
        with ZipFile(target/'model.FCStd','w',ZIP_DEFLATED) as archive:
            for n,data in members.items():archive.writestr(n,changed_xml(data,root) if n=='Document.xml' else data)
        digest=file_digest(target/'model.FCStd');receipt['artifacts'][2]['sha256']=digest
        atomic_json(target/'built.json',built);atomic_json(target/'verification.json',receipt)
        metadata=json.loads(original['model.FCStd.metadata.json']);metadata['artifact']['sha256']=digest
        metadata['size']['bytes']=(target/'model.FCStd').stat().st_size;atomic_json(target/'model.FCStd.metadata.json',metadata)
        index=json.loads(original['publication-metadata.json'])
        for publication in index['publications']:publication['sha256']=file_digest(target/publication['metadata'])
        atomic_json(target/'publication-metadata.json',index)
        try:adaptor.verify(target)
        except SchemaxisError as error:
            assert error.fault.code=='VERIFICATION_FAILED' and 'freshly measured' in error.fault.message,error.fault.to_dict()
            result={'chosen':chosen,'unused':unused,'fault':error.fault.to_dict()}
        else:raise AssertionError('coforged saved Draft link and both measured witnesses accepted')
    finally:
        for filename,data in original.items():(target/filename).write_bytes(data)
    assert adaptor.verify(target)['verified'];result['unchangedControl']=True
    return result


def assembly_snapshot(snapshot,document):
    expected=oracle(document);height=document['parameters']['height']['value'];wall=document['parameters']['wall']['value']
    assert snapshot['badStates']=={} and snapshot['externalLinks']==[]
    components=snapshot['components'];assert components['housing']['linked']==components['spareHousing']['linked']
    def near(a,b):assert math.isclose(a,b,rel_tol=1e-8,abs_tol=1e-6),(a,b)
    for identity,offset in (('housing',0),('spareHousing',80)):
        shape=components[identity]['shape'];near(shape['volume'],expected['volume'])
        for a,b in zip(shape['centreOfMass'],[expected['centre'][0]+offset,*expected['centre'][1:]]):near(a,b)
    near(components['lid']['shape']['volume'],expected['lidVolume'])
    for a,b in zip(components['lid']['shape']['centreOfMass'],[0,0,height+wall/2]):near(a,b)
    for a,b in zip([components['lid']['matrix'][i] for i in (3,7,11)],[-60,0,height]):near(a,b)


def qualify(directory,executable):
    directory=Path(directory).absolute();directory.mkdir(parents=True,exist_ok=False)
    report={'verified':False,'sourceDigest':source_digest('freecad'),'runtime':'1.1.4','checks':{},
            'qualifierSha256':file_digest(Path(__file__)),'oracleSha256':file_digest(ROOT/'tools/freecad_draft_cases.py'),
            'nativeInspectorSha256':file_digest(ROOT/'tools/qualify_freecad_draft_native.py')}
    locations={'freecad':executable};worker=SubprocessRunner(Interpreter('freecad',executable),directory,timeout=180)
    archive=directory/'trusted-runtime.zip';archive.write_bytes(runtime_archive());report['runtimeArchiveSha256']=file_digest(archive)
    def native(function,filename):
        code='import sys\nsys.path.insert(0,'+repr(str(archive))+')\nsys.path.insert(0,'+repr(str(ROOT/'tools'))+')\nfrom qualify_freecad_draft_native import '+function+'\nfrom schemaxis.native_boundary import execute_guarded\nexecute_guarded('+function+','+repr(str(directory))+')\n'
        atomic_json(directory/filename,worker(code).to_dict())
        if (directory/'native-fault.json').is_file():raise SchemaxisError(Fault(**json.loads((directory/'native-fault.json').read_text())))
    def native_assembly(target,stage,request):
        atomic_json(target/('edit-request.json' if stage=='edit_probe' else 'inspect-request.json'),request)
        code='import sys\nsys.path.insert(0,'+repr(str(archive))+')\nfrom schemaxis.adaptors.freecad.assembly_sources_native import '+stage+'\nfrom schemaxis.native_boundary import execute_guarded\nexecute_guarded('+stage+','+repr(str(target))+')\n'
        atomic_json(target/(stage+'-submission.json'),SubprocessRunner(Interpreter('freecad',executable),target,timeout=180)(code).to_dict())
        if (target/'native-fault.json').is_file():raise SchemaxisError(Fault(**json.loads((target/'native-fault.json').read_text())))
    try:
        with location_context(locations):
            docs={'enclosure':load('enclosure'),'cup':load('cup'),'tilted':tilted()}
            requests=[]
            for name,document in docs.items():
                target=directory/name;registry.run(document,target,locations=locations,timeout=180);assert registry.verify(target)['verified']
                requests.append({'id':name,'native':str(target/'model.FCStd'),'sha256':file_digest(target/'model.FCStd'),
                    'step':str(target/'model.step'),'document':document,'oracle':oracle(document)})
                report['checks'][name]={'verified':True,'oracle':oracle(document)};print(name+' native route verified',flush=True)
            atomic_json(directory/'independent-request.json',{'cases':requests});native('main','independent-submission.json')
            independent=json.loads((directory/'independent.json').read_text());assert independent['verified'];report['checks']['independentGeometry']=independent
            report['checks']['savedMutations']=attacks(directory/'enclosure')
            report['checks']['coforgedSelectorWitness']=forged_witness_attack(directory/'enclosure')
            source=directory/'enclosure/model.FCStd';edit_report={}
            for number in (1,2):
                document=changed(docs['enclosure'],number);target=directory/('edit'+str(number)+'.FCStd')
                for editing in (True,False):
                    label=('edit' if editing else 'reopen')+str(number)
                    atomic_json(directory/'edit-request.json',{'id':label,'source':str(source if editing else target),
                        'sourceSha256':file_digest(source if editing else target),'target':str(target),
                        'edit':editing,'document':document,'oracle':oracle(document)})
                    native('edit',label+'-submission.json');record=json.loads((directory/(label+'.json')).read_text());assert record['verified'];edit_report[label]=record
                assert edit_report['edit'+str(number)]['pid']!=edit_report['reopen'+str(number)]['pid'];source=target
            report['checks']['nativeEdits']=edit_report
            from qualify_freecad_history_assembly import document as assembly_project
            envelope=assembly_project(shelled=True);envelope['definitions']['partParameters']=docs['enclosure']['parameters'];envelope['definitions']['partHistory']=docs['enclosure']['nodes']
            wf=directory/'workflow';workflow.execute(envelope,wf,locations=locations,timeout=300);assert workflow.verify(wf)['verified']
            resumed=workflow.execute(envelope,wf,locations=locations,timeout=300,resume=True);assert all(j['reused'] for j in resumed['jobs'])
            job=Path(next(j['directory'] for j in resumed['jobs'] if j['operation']=='assembly'))
            built=json.loads((job/'built.json').read_text());plan=json.loads((job/'plan.json').read_text())
            persisted=json.loads((job/'verification.json').read_text())['snapshots']['persisted'];assembly_snapshot(persisted,docs['enclosure'])
            sourcejob=Path(next(j['directory'] for j in resumed['jobs'] if j['operation']=='housing'))
            report['checks']['preOpenSourceGuard']=source_attacks(job,sourcejob)
            report['checks']['assemblySourceCopy']={'verified':True,'directory':str(job),'parts':len(plan['parts']),'renames':built['renames']}
            copied=directory/'assembly-edits';copied.mkdir()
            for filename in ('model.FCStd','built.json','plan.json'):shutil.copyfile(job/filename,copied/filename)
            report['checks']['copiedHistoryEdits']={}
            for height in (22,24):
                native_assembly(copied,'edit_probe',{'part':'housingPart','parameter':'height','value':height,'output':'edited.FCStd'})
                edited=json.loads((copied/'edit.json').read_text());variant=copy.deepcopy(docs['enclosure']);variant['parameters']['height']['value']=height
                for stage in ('recomputed','solved','probed'):assembly_snapshot(edited['snapshots'][stage],variant)
                native_assembly(copied,'inspect_copy',{'file':str(copied/'edited.FCStd'),'receipt':'inspected.json'})
                inspected=json.loads((copied/'inspected.json').read_text());assert edited['pid']!=inspected['pid']
                for stage in ('persisted','solved'):assembly_snapshot(inspected['snapshots'][stage],variant)
                shutil.copyfile(copied/'edited.FCStd',copied/'model.FCStd')
                report['checks']['copiedHistoryEdits'][str(height)]={'editedPid':edited['pid'],'reopenedPid':inspected['pid']}
            standalone=directory/'standalone';standalone.mkdir()
            for filename in ('model.FCStd','built.json','plan.json'):shutil.copyfile(job/filename,standalone/filename)
            hidden=directory/'workflow-hidden';wf.rename(hidden)
            try:native_assembly(standalone,'inspect_copy',{'file':str(standalone/'model.FCStd'),'receipt':'standalone.json'})
            finally:hidden.rename(wf)
            inspected=json.loads((standalone/'standalone.json').read_text())
            for stage in ('persisted','solved'):assembly_snapshot(inspected['snapshots'][stage],docs['enclosure'])
            report['checks']['nativeSourceRemoval']=True
            (job/'model.FCStd').write_bytes(b'corrupt Draft assembly output')
            rebuilt=workflow.execute(envelope,wf,locations=locations,timeout=300,resume=True);assert workflow.verify(wf)['verified']
            states={j['operation']:j['reused'] for j in rebuilt['jobs']};assert states=={'housing':True,'lid':True,'assembly':False},states
            report['checks']['workflow']={'verifiedReuse':True,'afterAssemblyDamage':states}
            # Refusing changed authored intent is distinct from reusing an old run.
            altered=copy.deepcopy(envelope);release=next(n for n in altered['definitions']['partHistory'] if n['id']=='release');release['options']['angle']=4
            try:workflow.execute(altered,wf,locations=locations,timeout=300,resume=True)
            except SchemaxisError as error:assert error.fault.code=='RESUME_MISMATCH';report['checks']['changedIntentRefused']=True
            else:raise AssertionError('changed Draft source reused an old run')
            assert report['sourceDigest']==source_digest('freecad'),'source changed during qualification';report['verified']=True
    finally:atomic_json(directory/'report.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',required=True);parser.add_argument('--executable',required=True)
    args=parser.parse_args();print(json.dumps(qualify(args.directory,args.executable),indent=2))
