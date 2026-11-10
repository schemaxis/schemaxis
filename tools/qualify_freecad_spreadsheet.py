#!/usr/bin/env python3
"""Qualify unitful engineering tables, native edits and copied Body histories."""
import argparse,copy,json,math,shutil
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile,ZIP_DEFLATED
from schemaxis import workflow
from schemaxis.adaptor_delivery import source_digest
from schemaxis.adaptors import registry
from schemaxis.adaptors.freecad import adaptor,assembly
from schemaxis.adaptors.freecad.process import SubprocessRunner
from schemaxis.artifacts import atomic_json,file_digest,runtime_archive
from schemaxis.configuration import location_context
from schemaxis.core.faults import SchemaxisError,Fault
from schemaxis.core.runners import Interpreter
from freecad_spreadsheet_cases import enclosure,turned,changed,oracle
ROOT=Path(__file__).resolve().parents[1]


def assembly_document(source):
    return {'version':'schemaxis.freecad.assembly/1',
        'parts':[{'id':'part','source':source,'mounts':{'base':{},'spare':{'position':[80,0,{'terms':{'rise':1}}]}}}],
        'components':[{'id':'housing','part':'part'},{'id':'spare','part':'part'}],'grounded':'housing',
        'joints':[{'id':'copy','type':'fixed','parent':{'component':'housing','mount':'spare'},'child':{'component':'spare','mount':'base'}}]}


def project(document):
    return {'version':'schemaxis.workflow/1','execution':{'maxWorkers':1,'cpus':2,'memoryMB':4096,'gpus':0},
        'operations':[{'id':'housing','document':document},
                      {'id':'independent','document':{'version':'schemaxis.freecad/1','nodes':[{'id':'stock','filter':'box'}],'output':'stock'}},
                      {'id':'assembly','document':assembly_document({'$artifact':'housing','index':2})}]}


def refresh(target):
    digest=file_digest(target/'model.FCStd');receipt=json.loads((target/'verification.json').read_text())
    receipt['artifacts'][2]['sha256']=digest;atomic_json(target/'verification.json',receipt)
    metadata=json.loads((target/'model.FCStd.metadata.json').read_text());metadata['artifact']['sha256']=digest
    metadata['size']['bytes']=(target/'model.FCStd').stat().st_size;atomic_json(target/'model.FCStd.metadata.json',metadata)
    index=json.loads((target/'publication-metadata.json').read_text())
    for publication in index['publications']:publication['sha256']=file_digest(target/publication['metadata'])
    atomic_json(target/'publication-metadata.json',index)


def attacks(target):
    names=('model.FCStd','built.json','verification.json','model.FCStd.metadata.json','publication-metadata.json')
    original={name:(target/name).read_bytes() for name in names};authored=json.loads((target/'authored.json').read_text())
    prepared=adaptor.plan(authored);span=prepared['spreadsheet']['cells']['span'];width=prepared['spreadsheet']['cells']['width']
    with ZipFile(target/'model.FCStd') as archive:members={name:archive.read(name) for name in archive.namelist()}
    def props(root):return root.find("./ObjectData/Object[@name='SchemaxisParameters']/Properties")
    def cell(root,address):return props(root).find("./Property[@name='cells']/Cells/Cell[@address='%s']"%address)
    def hidden(root):
        cells=props(root).find("./Property[@name='cells']/Cells");cells.set('Count',str(int(cells.get('Count'))+1))
        ET.SubElement(cells,'Cell',address='Z99',content='=OtherDocument#Object.Value')
    def engine(root):
        item=props(root).find("./Property[@name='ExpressionEngine']/ExpressionEngine");item.set('count','1')
        ET.SubElement(item,'Expression',path='Visibility',expression='1')
    def foreign(root):
        parent=props(root);parent.set('Count',str(int(parent.get('Count'))+1))
        child=ET.SubElement(parent,'Property',name='Proxy',type='App::PropertyPythonObject');ET.SubElement(child,'Python',value='untrusted-marker',encoded='no')
    def transient(root):
        parent=props(root);parent.set('TransientCount','1')
        child=ET.SubElement(parent,'_Property',name='Unexpected',type='App::PropertyPythonObject',status='1')
        ET.SubElement(child,'Python',value='untrusted-marker',encoded='no')
    def extension(root):
        obj=root.find("./ObjectData/Object[@name='SchemaxisParameters']");obj.set('Extensions','True')
        parent=ET.SubElement(obj,'Extensions',Count='1');ET.SubElement(parent,'Extension',type='App::DocumentObjectExtensionPython',name='Injected')
    controls={
      'formula-same-current-value':lambda r:cell(r,span).set('content','=2 * dim_width + -26 mm'),
      'formula-foreign-reference':lambda r:cell(r,span).set('content','=OtherDocument#Object.Length'),
      'formula-function':lambda r:cell(r,span).set('content','=sin(dim_width)'),
      'formula-comment':lambda r:cell(r,span).set('content',cell(r,span).get('content')+' # hidden'),
      'input-expression':lambda r:cell(r,width).set('content','=3 cm + 0 mm'),
      'display-unit':lambda r:cell(r,width).set('displayUnit','m'),
      'alias':lambda r:cell(r,span).set('alias','dim_width'),
      'hidden-cell':hidden,'expression-engine':engine,'foreign-python-property':foreign,
      'transient-python-property':transient,'object-extension':extension,
      'property-persistence-role':lambda r:props(r).find("./Property[@name='cells']").set('status','0')}
    report={}
    for label,mutate in controls.items():
        for forged in ([False,True] if label=='formula-same-current-value' else [False]):
            key=label+('-coforged-native-witnesses' if forged else '')
            try:
                root=ET.fromstring(members['Document.xml']);before=ET.tostring(root);mutate(root);assert ET.tostring(root)!=before
                prefix=members['Document.xml'].split(b'<Document ',1)[0];assert prefix
                with ZipFile(target/'model.FCStd','w',ZIP_DEFLATED) as archive:
                    for name,data in members.items():archive.writestr(name,prefix+ET.tostring(root) if name=='Document.xml' else data)
                if forged:
                    for filename in ('built.json','verification.json'):
                        record=json.loads(original[filename]);record['parameterObservations']['spreadsheet']['cells'][span]['contents']=cell(root,span).get('content')
                        atomic_json(target/filename,record)
                refresh(target)
                with patch('subprocess.Popen',side_effect=AssertionError('untrusted Sheet verification opened a native process')) as launch:
                    try:adaptor.verify(target)
                    except SchemaxisError as error:
                        assert error.fault.code=='VERIFICATION_FAILED',error.fault.to_dict()
                        assert not any(word in error.fault.message.lower() for word in ('hash','digest')),error.fault.to_dict()
                        report[key]=error.fault.to_dict()
                    else:raise AssertionError('saved spreadsheet attack accepted: '+key)
                    launch.assert_not_called()
                # Admission must reject the same archive before a source restore.
                with patch('subprocess.Popen',side_effect=AssertionError('source admission opened a native process')) as launch:
                    try:assembly._native_plan(assembly_document(str(target/'model.FCStd')))
                    except SchemaxisError as error:assert error.fault.code=='UNSUPPORTED_SOURCE',error.fault.to_dict()
                    else:raise AssertionError('untrusted spreadsheet source admitted: '+key)
                    launch.assert_not_called()
                report[key]['sourceRefusedBeforeOpen']=True
            finally:
                for name,data in original.items():(target/name).write_bytes(data)
    assert adaptor.verify(target)['verified'];assembly._native_plan(assembly_document(str(target/'model.FCStd')))
    report['unchangedControl']=True
    return report


def copied_geometry(snapshot,document):
    expected=oracle(document);H=expected['dimensions']['height']
    assert snapshot['badStates']=={} and snapshot['externalLinks']==[]
    components=snapshot['components'];assert components['housing']['linked']==components['spare']['linked']
    def near(a,b):assert math.isclose(a,b,rel_tol=1e-8,abs_tol=1e-6),(a,b)
    for identity,shift in [('housing',[0,0,0]),('spare',[80,0,H])]:
        shape=components[identity]['shape'];near(shape['volume'],expected['volume'])
        for actual,wanted,offset in zip(shape['centreOfMass'],expected['centre'],shift):near(actual,wanted+offset)
        for actual,wanted in zip([components[identity]['matrix'][i] for i in (3,7,11)],shift):near(actual,wanted)



def distinct_tables(directory,documents,executable,native):
    """Overlapping aliases in two definitions must remain independent after edits."""
    first,second=documents['enclosure'],documents['enclosureVariant']
    document={'version':'schemaxis.freecad.assembly/1','parts':[
        {'id':'first','source':str(directory/'enclosure/model.FCStd'),'mounts':{
            'base':{},'seam':{'position':[0,0,{'terms':{'rise':1}}]}}},
        {'id':'second','source':str(directory/'enclosureVariant/model.FCStd'),'mounts':{'base':{}}}],
        'components':[{'id':'first','part':'first'},{'id':'second','part':'second'}],'grounded':'first',
        'joints':[{'id':'stack','type':'fixed','parent':{'component':'first','mount':'seam'},'child':{'component':'second','mount':'base'}}]}
    target=directory/'distinct-tables';registry.run(document,target,locations={'freecad':executable},timeout=300)
    assert registry.verify(target)['verified']
    def check(snapshot,height=24):
        assert snapshot['badStates']=={} and snapshot['externalLinks']==[]
        variant=copy.deepcopy(second);variant['spreadsheet']['inputs']['height']['value']=height
        for identity,authored,offset in [('first',first,0),('second',variant,22)]:
            expected=oracle(authored);shape=snapshot['components'][identity]['shape']
            assert math.isclose(shape['volume'],expected['volume'],rel_tol=1e-8,abs_tol=1e-6),(identity,shape,expected)
            for axis,(actual,wanted) in enumerate(zip(shape['centreOfMass'],expected['centre'])):
                assert math.isclose(actual,wanted+(offset if axis==2 else 0),rel_tol=1e-8,abs_tol=1e-6)
        assert snapshot['sources']['first']['parameters']['dim_height']==20
        assert snapshot['sources']['second']['parameters']['dim_height']==height
    check(json.loads((target/'verification.json').read_text())['snapshots']['persisted'])
    # Keep the verified product packet immutable; native edits are new designs
    # and intentionally cannot reuse its original authored receipt.
    edits=directory/'distinct-table-edits';edits.mkdir()
    for filename in ('model.FCStd','built.json','plan.json'):shutil.copyfile(target/filename,edits/filename)
    report={}
    for height in (21,27):
        native(edits,'edit_probe',{'part':'second','parameter':'height','value':height,'output':'edited.FCStd'})
        edited=json.loads((edits/'edit.json').read_text())
        for phase in ('recomputed','solved','probed'):check(edited['snapshots'][phase],height)
        native(edits,'inspect_copy',{'file':str(edits/'edited.FCStd'),'receipt':'inspected.json'})
        reopened=json.loads((edits/'inspected.json').read_text());assert edited['pid']!=reopened['pid']
        for phase in ('persisted','solved'):check(reopened['snapshots'][phase],height)
        shutil.copyfile(edits/'edited.FCStd',edits/'model.FCStd')
        report[str(height)]={'editedPid':edited['pid'],'reopenedPid':reopened['pid'],'otherTableUnchanged':True}
    assert registry.verify(target)['verified'],'native edits changed the original distinct-table product packet'
    return report

def qualify(directory,executable):
    directory=Path(directory).absolute();directory.mkdir(parents=True,exist_ok=False)
    report={'verified':False,'sourceDigest':source_digest('freecad'),'checks':{}}
    archive=directory/'trusted-runtime.zip';archive.write_bytes(runtime_archive());report['runtimeArchiveSha256']=file_digest(archive)
    def native(stage,filename):
        code='import sys\nsys.path.insert(0,'+repr(str(archive))+')\nsys.path.insert(0,'+repr(str(ROOT/'tools'))+')\nfrom qualify_freecad_spreadsheet_native import '+stage+'\nfrom schemaxis.native_boundary import execute_guarded\nexecute_guarded('+stage+','+repr(str(directory))+')\n'
        atomic_json(directory/filename,SubprocessRunner(Interpreter('freecad',executable),directory,timeout=180)(code).to_dict())
        if (directory/'native-fault.json').exists():raise SchemaxisError(Fault(**json.loads((directory/'native-fault.json').read_text())))
    def assembly_native(target,stage,request):
        atomic_json(target/('edit-request.json' if stage=='edit_probe' else 'inspect-request.json'),request)
        code='import sys\nsys.path.insert(0,'+repr(str(archive))+')\nfrom schemaxis.adaptors.freecad.assembly_sources_native import '+stage+'\nfrom schemaxis.native_boundary import execute_guarded\nexecute_guarded('+stage+','+repr(str(target))+')\n'
        SubprocessRunner(Interpreter('freecad',executable),target,timeout=180)(code)
        if (target/'native-fault.json').exists():raise SchemaxisError(Fault(**json.loads((target/'native-fault.json').read_text())))
    try:
        with location_context({'freecad':executable}):
            documents={'enclosure':enclosure(),'enclosureVariant':changed(enclosure(),1),'turned':turned()};requests=[]
            for name,document in documents.items():
                target=directory/name;registry.run(document,target,locations={'freecad':executable},timeout=180);assert registry.verify(target)['verified']
                requests.append({'id':name,'native':str(target/'model.FCStd'),'sha256':file_digest(target/'model.FCStd'),
                                 'step':str(target/'model.step'),'document':document,'oracle':oracle(document)})
                print(name+' typed table verified',flush=True)
            atomic_json(directory/'independent-request.json',{'cases':requests});native('inspect','independent-submission.json')
            report['checks']['independentGeometry']=json.loads((directory/'independent.json').read_text())
            report['checks']['refreshedSavedAttacks']=attacks(directory/'enclosure')
            edits={}
            for name in ('enclosure','turned'):
                document=documents[name]
                source=directory/name/'model.FCStd'
                for number in (1,2):
                    variant=changed(document,number);target=directory/(name+'-edit'+str(number)+'.FCStd')
                    for editing in (True,False):
                        label=name+('-edit' if editing else '-reopen')+str(number)
                        path=source if editing else target
                        atomic_json(directory/'edit-request.json',{'id':label,'source':str(path),'sha256':file_digest(path),
                            'target':str(target),'edit':editing,'document':variant,'oracle':oracle(variant)})
                        native('edit',label+'-submission.json');edits[label]=json.loads((directory/(label+'.json')).read_text());assert edits[label]['verified']
                    assert edits[name+'-edit'+str(number)]['pid']!=edits[name+'-reopen'+str(number)]['pid'];source=target
            report['checks']['nativeEdits']=edits
            report['checks']['distinctTables']=distinct_tables(directory,documents,executable,assembly_native)
            envelope=project(documents['enclosure']);wf=directory/'workflow'
            workflow.execute(envelope,wf,locations={'freecad':executable},timeout=300);assert workflow.verify(wf)['verified']
            resumed=workflow.execute(envelope,wf,locations={'freecad':executable},timeout=300,resume=True);assert all(j['reused'] for j in resumed['jobs'])
            job=Path(next(j['directory'] for j in resumed['jobs'] if j['operation']=='assembly'))
            copied_geometry(json.loads((job/'verification.json').read_text())['snapshots']['persisted'],documents['enclosure'])
            copied=directory/'copied';copied.mkdir()
            for filename in ('model.FCStd','built.json','plan.json'):shutil.copyfile(job/filename,copied/filename)
            copy_edits={}
            for height in (24,18):
                assembly_native(copied,'edit_probe',{'part':'part','parameter':'height','value':height,'output':'edited.FCStd'})
                edited=json.loads((copied/'edit.json').read_text());variant=copy.deepcopy(documents['enclosure']);variant['spreadsheet']['inputs']['height']['value']=height
                for phase in ('recomputed','solved','probed'):copied_geometry(edited['snapshots'][phase],variant)
                assembly_native(copied,'inspect_copy',{'file':str(copied/'edited.FCStd'),'receipt':'inspected.json'})
                reopened=json.loads((copied/'inspected.json').read_text());assert edited['pid']!=reopened['pid']
                for phase in ('persisted','solved'):copied_geometry(reopened['snapshots'][phase],variant)
                shutil.copyfile(copied/'edited.FCStd',copied/'model.FCStd');copy_edits[str(height)]={'editedPid':edited['pid'],'reopenedPid':reopened['pid']}
            report['checks']['copiedHistoryEdits']=copy_edits
            standalone=directory/'standalone';standalone.mkdir()
            for filename in ('model.FCStd','built.json','plan.json'):shutil.copyfile(job/filename,standalone/filename)
            hidden=directory/'workflow-hidden';wf.rename(hidden)
            try:assembly_native(standalone,'inspect_copy',{'file':str(standalone/'model.FCStd'),'receipt':'standalone.json'})
            finally:hidden.rename(wf)
            for phase in ('persisted','solved'):copied_geometry(json.loads((standalone/'standalone.json').read_text())['snapshots'][phase],documents['enclosure'])
            report['checks']['nativeSourceRemoval']=True
            (job/'model.FCStd').write_bytes(b'damaged Spreadsheet assembly')
            rebuilt=workflow.execute(envelope,wf,locations={'freecad':executable},timeout=300,resume=True);assert workflow.verify(wf)['verified']
            states={j['operation']:j['reused'] for j in rebuilt['jobs']};assert states=={'housing':True,'independent':True,'assembly':False},states
            altered=copy.deepcopy(envelope);altered['operations'][0]['document']['spreadsheet']['inputs']['height']['value']=21
            try:workflow.execute(altered,wf,locations={'freecad':executable},timeout=300,resume=True)
            except SchemaxisError as error:assert error.fault.code=='RESUME_MISMATCH'
            else:raise AssertionError('changed authored table reused old workflow')
            report['checks']['workflow']={'verifiedReuse':True,'afterDamage':states,'changedIntentRefused':True}
            assert report['sourceDigest']==source_digest('freecad'),'source changed during Spreadsheet proof'
            report['verified']=True
    finally:atomic_json(directory/'report.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',required=True);parser.add_argument('--executable',required=True)
    args=parser.parse_args();print(json.dumps(qualify(args.directory,args.executable),indent=2))
