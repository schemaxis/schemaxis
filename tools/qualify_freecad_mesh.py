#!/usr/bin/env python3
"""Qualify checked STL preparation, native Part edits and saved reconstruction."""
import argparse,copy,json,math,os,re,shutil,threading,time
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile,ZIP_DEFLATED
from schemaxis.adaptors import registry
from schemaxis.adaptors.freecad import adaptor
from schemaxis.adaptors.freecad.process import SubprocessRunner
from schemaxis.artifacts import atomic_json,file_digest,runtime_archive
from schemaxis.adaptor_delivery import source_digest
from schemaxis.configuration import location_context
from schemaxis.core.faults import SchemaxisError,Fault
from schemaxis.core.runners import Interpreter
from schemaxis.dispatch import allocation,execution_deadline
from schemaxis import workflow
from freecad_mesh_cases import write_examples,bracket_document,bracket_oracle,cavity_document,cavity_oracle,dense_box,stl
ROOT=Path(__file__).resolve().parents[1]


def oracle(variant=False,drill_shift=0,casting_shift=0):
    result=bracket_oracle(variant=variant,drill_shift=drill_shift,casting_shift=casting_shift)
    dx,dy,dz,radius=(7,5,6,3) if variant else (6,4,5,2.5)
    result['sections']=[[dz/2,[6*dx*4*dy,math.pi*radius**2]],[2.5*dz,[9*dx*dy]]]
    return result


def native(directory,executable,function,request_name,request):
    directory.mkdir(parents=True,exist_ok=True);atomic_json(directory/request_name,request)
    archive=directory/'trusted-runtime.zip';archive.write_bytes(runtime_archive())
    code=('import sys\nsys.path.insert(0,'+repr(str(archive))+')\nsys.path.insert(1,'+repr(str(ROOT/'tools'))+')\n'
          'from qualify_freecad_mesh_native import '+function+'\nfrom schemaxis.native_boundary import execute_guarded\n'
          'execute_guarded('+function+','+repr(str(directory))+')\n')
    SubprocessRunner(Interpreter('freecad',executable),directory,timeout=240)(code)
    if (directory/'native-fault.json').exists():raise SchemaxisError(Fault(**json.loads((directory/'native-fault.json').read_text())))


def refresh(directory):
    receipt=json.loads((directory/'verification.json').read_text());digest=file_digest(directory/'model.FCStd')
    receipt['artifacts'][2]['sha256']=digest;atomic_json(directory/'verification.json',receipt)
    meta=json.loads((directory/'model.FCStd.metadata.json').read_text());meta['artifact']['sha256']=digest;meta['size']['bytes']=(directory/'model.FCStd').stat().st_size
    atomic_json(directory/'model.FCStd.metadata.json',meta)
    index=json.loads((directory/'publication-metadata.json').read_text())
    for entry in index['publications']:entry['sha256']=file_digest(directory/entry['metadata'])
    atomic_json(directory/'publication-metadata.json',index)


def alterations(directory,replacement):
    files=('model.FCStd','built.json','verification.json','model.FCStd.metadata.json','publication-metadata.json')
    original={n:(directory/n).read_bytes() for n in files}
    with ZipFile(directory/'model.FCStd') as archive:members={n:archive.read(n) for n in archive.namelist()}
    def prop(root,name):return root.find("./ObjectData/Object[@name='N0']/Properties/Property[@name='%s']"%name)
    def radius(root,data):root.find("./ObjectData/Object[@name='N1']/Properties/Property[@name='Radius']/Float").set('value','3')
    def transient(root,data):
        p=root.find("./ObjectData/Object[@name='N0']/Properties");p.set('TransientCount',str(int(p.get('TransientCount'))+1))
        ET.SubElement(p,'_Property',name='HiddenMarker',type='App::PropertyString',status='234881024')
    def extension(root,data):ET.SubElement(root.find("./ObjectData/Object[@name='N0']"),'Extensions',Count='0')
    def role(root,data):p=prop(root,'SourceSHA256');p.set('status',str(int(p.get('status'))^4))
    def engine(root,data):
        p=prop(root,'ExpressionEngine')[0];p.set('count','1');ET.SubElement(p,'Expression',path='Visibility',expression='1')
    def placement(root,data):prop(root,'Placement')[0].set('Px','1')
    def hasher(root,data):root.find('StringHasher').set('count','1')
    def geometry(root,data):data[prop(root,'Shape').find('Part').get('file')]=replacement
    def face_flag(root,data):
        name=prop(root,'Shape').find('Part').get('file')
        pattern=re.compile(rb'(?m)(^Fa\n[^\n]+\n\n[01]{3})([01])([01]{3}\n)')
        data[name],count=pattern.subn(lambda m:m[1]+(b'0' if m[2]==b'1' else b'1')+m[3],data[name],count=1)
        assert count==1
    def alias(root,data):
        name=root.find("./ObjectData/Object[@name='N2']/Properties/Property[@name='Shape']/ElementMap2").get('file')
        data[name]=data[name].replace(b'PostfixCount ',b'PostfixCount 999',1)
    def source_link(root,data):root.find("./ObjectData/Object[@name='N2']/Properties/Property[@name='Base']/Link").set('value','N1')
    def extra(root,data):data['UnusedGeometry.brp']=replacement
    controls=[('cached-tool-radius',radius),('hidden-transient',transient),('object-extension',extension),('persistence-role',role),
              ('source-expression',engine),('xml-placement',placement),('unused-inline-string',hasher),('saved-source-geometry',geometry),
              ('source-face-orientability',face_flag),('native-map-record',alias),('cached-boolean-link',source_link),('unreferenced-member',extra)]
    results=[]
    try:
        for label,change in controls:
            for name,payload in original.items():(directory/name).write_bytes(payload)
            data=dict(members);root=ET.fromstring(data['Document.xml']);change(root,data);data['Document.xml']=ET.tostring(root,encoding='utf-8',xml_declaration=True)
            with ZipFile(directory/'model.FCStd','w',compression=ZIP_DEFLATED) as archive:
                for name,payload in data.items():archive.writestr(name,payload)
            refresh(directory)
            try:registry.verify(directory)
            except SchemaxisError as error:assert error.fault.code=='VERIFICATION_FAILED',(label,error.fault);results.append({'case':label,'code':error.fault.code})
            else:raise AssertionError('saved-state alteration accepted: '+label)
        for name,payload in original.items():(directory/name).write_bytes(payload)
        assert registry.verify(directory)['verified'];results.append({'case':'restored-positive','verified':True})
    finally:
        for name,payload in original.items():(directory/name).write_bytes(payload)
    return results


def unchanged_save(directory,target,executable):
    source=target/'model.FCStd';saved=directory/'model.FCStd'
    request={'id':'same-state','source':str(source),'sha256':file_digest(source),'output':'bracket','target':str(saved),
             'mode':'save','before':oracle(),'after':oracle()}
    native(directory,executable,'edit','edit-request.json',request)
    files=('model.FCStd','verification.json','model.FCStd.metadata.json','publication-metadata.json')
    original={name:(target/name).read_bytes() for name in files}
    try:
        (target/'model.FCStd').write_bytes(saved.read_bytes());refresh(target);assert registry.verify(target)['verified']
    finally:
        for name,payload in original.items():(target/name).write_bytes(payload)
    assert registry.verify(target)['verified']
    return json.loads((directory/'same-state.json').read_text())


def edited(directory,target,executable,kind):
    source=target/'model.FCStd';original={n:(target/n).read_bytes() for n in ('model.FCStd','model.step','model.stl')};records=[]
    before=oracle() if kind=='bracket' else cavity_oracle()
    stages=[('drill',24,oracle(drill_shift=3)),('casting',2,oracle(drill_shift=3,casting_shift=2))] if kind=='bracket' else [
        ('placement',[50,-20,13],cavity_oracle((50,-20,13))),('placement',[50,-17,13],cavity_oracle((50,-17,13)))]
    for number,(mode,value,after) in enumerate(stages,1):
        path=directory/(kind+'-stage'+str(number)+'.FCStd');identity=kind+'-edit'+str(number)
        request={'id':identity,'source':str(source),'sha256':file_digest(source),'output':'bracket' if kind=='bracket' else 'casting',
                 'target':str(path),'mode':mode,'value':value,'before':before,'after':after}
        native(directory,executable,'edit','edit-request.json',request);record=json.loads((directory/(identity+'.json')).read_text());assert record['verified'];records.append(record)
        request.update(id=identity+'-reopen',source=str(path),sha256=file_digest(path),target=str(path),mode='reopen',before=after)
        native(directory,executable,'edit','edit-request.json',request);record=json.loads((directory/(request['id']+'.json')).read_text());assert record['verified'];records.append(record)
        source=path;before=after
    assert all((target/n).read_bytes()==payload for n,payload in original.items());assert registry.verify(target)['verified']
    return records


def lifecycle(directory,target):
    # Hold a trusted test worker after its actual PID is recorded. The public
    # verifier's own shared deadline/cancellation boundary must stop that worker.
    original=SubprocessRunner.__call__;results=[]
    for mode in ('timeout','cancel'):
        marker=directory/(mode+'-pid.txt');cancel=threading.Event();timer=None
        def slow(self,code):
            pause=('import os,time\nfrom pathlib import Path\nPath('+repr(str(marker))+').write_text(str(os.getpid()))\ntime.sleep(20)\n')
            return original(self,pause+code)
        def stop():
            end=time.monotonic()+5
            while not marker.exists() and time.monotonic()<end:time.sleep(.05)
            cancel.set()
        try:
            with patch.object(SubprocessRunner,'__call__',slow):
                if mode=='cancel':timer=threading.Thread(target=stop);timer.start()
                with allocation({},cancel=cancel),execution_deadline(1.5 if mode=='timeout' else 8):
                    registry.verify(target)
        except SchemaxisError as error:assert error.fault.code==('RUNNER_TIMED_OUT' if mode=='timeout' else 'RUNNER_CANCELLED'),error.fault
        else:raise AssertionError('mesh verification lifecycle control completed')
        finally:
            if timer:timer.join(timeout=6)
        assert marker.exists(),'native worker did not start';pid=int(marker.read_text())
        try:os.kill(pid,0)
        except ProcessLookupError:pass
        else:raise AssertionError('native verification worker remains alive: '+str(pid))
        results.append({'mode':mode,'pid':pid,'stopped':True})
    assert registry.verify(target)['verified'];return results


def maximum_facets(directory,executable):
    source=directory/'maximum.stl';source.write_bytes(stl(dense_box()))
    document={'version':'schemaxis.freecad/1','nodes':[{'id':'dense','filter':'importMesh','options':{'file':str(source),'units':'mm'}}],'output':'dense'}
    started=time.monotonic();result=registry.run(document,directory/'maximum',locations={'freecad':executable},timeout=600)
    assert result['verified'] and math.isclose(result['volumeMM3'],6000,rel_tol=1e-7,abs_tol=1e-6)
    expected={'volume':6000,'centreOfMass':[5,10,15],'bounds':[0,10,0,20,0,30],'inside':[[5,10,15]],'outside':[[20,10,15]]}
    native(directory/'maximum-independent',executable,'inspect','inspect-request.json',{'cases':[{'id':'maximum',
        'file':str(directory/'maximum/model.FCStd'),'sha256':file_digest(directory/'maximum/model.FCStd'),
        'step':str(directory/'maximum/model.step'),'output':'dense','oracle':expected}]})
    return {'verified':True,'facets':20000,'sourceSha256':file_digest(source),'elapsedSeconds':time.monotonic()-started}


def linked_workflow(directory,document,locations):
    facts=oracle();drawing={'version':'schemaxis.freecad.drawing/1','source':{
        'file':{'$artifact':'casting','index':2},'object':'bracket','units':'mm',
        'expect':{k:facts[k] for k in ('volume','bounds','centreOfMass')}},
        'sheet':{'title':'Prepared mesh bracket','revision':'A'},'views':['front','top','right','isometric'],
        'dimensioning':[{'id':'length','view':'front','type':'overallWidth'},
                        {'id':'depth','view':'top','type':'overallHeight'},
                        {'id':'bore','view':'top','type':'diameter','radius':2.5}],
        'notes':['Dimensions in millimetres','Faceted STL preparation; retained native drilling']}
    envelope={'version':'schemaxis.workflow/1','execution':{'maxWorkers':1,'cpus':2,'memoryMB':4096,'gpus':0},
        'operations':[{'id':'casting','document':document},{'id':'drawing','document':drawing},
                      {'id':'independent','document':{'version':'schemaxis.freecad/1','nodes':[{'id':'stock','filter':'box','options':{'length':10,'width':5,'height':2}}],'output':'stock'}}]}
    target=directory/'workflow';workflow.execute(envelope,target,locations=locations,timeout=600);assert workflow.verify(target)['verified']
    reused=workflow.execute(envelope,target,locations=locations,timeout=600,resume=True);assert all(j['reused'] for j in reused['jobs'])
    drawjob=Path(next(j['directory'] for j in reused['jobs'] if j['operation']=='drawing'))
    dimensions=json.loads((drawjob/'verification.json').read_text())
    (drawjob/'drawing.svg').write_text('damaged drawing publication')
    rebuilt=workflow.execute(envelope,target,locations=locations,timeout=600,resume=True);assert workflow.verify(target)['verified']
    state={j['operation']:j['reused'] for j in rebuilt['jobs']};assert state=={'casting':True,'drawing':False,'independent':True},state
    changed=copy.deepcopy(envelope);changed['operations'][0]['document']['nodes'][1]['options']['radius']=3
    try:workflow.execute(changed,target,locations=locations,timeout=600,resume=True)
    except SchemaxisError as error:assert error.fault.code=='RESUME_MISMATCH'
    else:raise AssertionError('changed machining intent reused old workflow')
    return {'verified':True,'reuse':True,'afterDrawingDamage':state,'changedIntentRefused':True,'drawingDirectory':str(drawjob)}


def qualify(directory,executable,gui_executable):
    directory=Path(directory).absolute();directory.mkdir(parents=True,exist_ok=False);sources=write_examples(directory/'inputs')
    report={'verified':False,'sourceDigest':source_digest('freecad'),'checks':{},'tools':{p.name:file_digest(p) for p in [Path(__file__),ROOT/'tools/qualify_freecad_mesh_native.py',ROOT/'tools/freecad_mesh_cases.py']}}
    docs={'bracket':bracket_document(sources['bracket']),'variant':bracket_document(sources['variant'],variant=True),'cavity':cavity_document(sources['cavity'])}
    try:
        with location_context({'freecad':executable,'freecad_gui':gui_executable}):
            for label,document in docs.items():
                result=registry.run(document,directory/label,locations={'freecad':executable},timeout=300);assert result['verified']
                report['checks'][label]={'verified':True,'volume':result['volumeMM3'],'source':file_digest(sources[label])};atomic_json(directory/'report.json',report)
            requests=[]
            for label,document in docs.items():
                target=directory/label;requests.append({'id':label,'file':str(target/'model.FCStd'),'sha256':file_digest(target/'model.FCStd'),
                    'step':str(target/'model.step'),'output':document['output'],'oracle':cavity_oracle() if label=='cavity' else oracle(label=='variant')})
            native(directory/'independent',executable,'inspect','inspect-request.json',{'cases':requests})
            independent=json.loads((directory/'independent/independent.json').read_text());assert independent['verified'];report['checks']['independent']=independent
            report['checks']['sameStateSave']=unchanged_save(directory/'same-state',directory/'bracket',executable)
            edits=directory/'edits';edits.mkdir();report['checks']['bracketEdits']=edited(edits,directory/'bracket',executable,'bracket');report['checks']['cavityEdits']=edited(edits,directory/'cavity',executable,'cavity')
            captured=json.loads((directory/'bracket/sources.json').read_text())['casting'];node=adaptor.plan(docs['bracket'])['nodes'][0]
            native(directory/'shift',executable,'shifted_source','shift-request.json',{'source':captured['retained'],'sha256':captured['sha256'],'options':node['options']})
            report['checks']['savedState']=alterations(directory/'bracket',(directory/'shift/shifted-source.brp').read_bytes())
            report['checks']['deadlineCancellation']=lifecycle(directory,directory/'bracket')
            report['stage']='maximum-facets';atomic_json(directory/'report.json',report)
            report['checks']['maximumFacets']=maximum_facets(directory,executable)
            report['stage']='linked-workflow';atomic_json(directory/'report.json',report)
            report['checks']['workflow']=linked_workflow(directory,docs['bracket'],{'freecad':executable,'freecad_gui':gui_executable})
            hidden=directory/'original-inputs-removed';(directory/'inputs').rename(hidden)
            try:
                assert all(registry.verify(directory/label)['verified'] for label in docs)
                assert workflow.verify(directory/'workflow')['verified']
                native(directory/'without-originals',executable,'inspect','inspect-request.json',{'cases':requests})
                report['checks']['originalSourceRemoval']=True
            finally:hidden.rename(directory/'inputs')
            assert report['sourceDigest']==source_digest('freecad'),'source changed during qualification';report['stage']='complete';report['verified']=True
    finally:atomic_json(directory/'report.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',required=True);parser.add_argument('--executable',required=True);parser.add_argument('--gui-executable',required=True)
    args=parser.parse_args();print(json.dumps(qualify(args.directory,args.executable,args.gui_executable),indent=2))
