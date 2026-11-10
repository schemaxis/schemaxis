"""Hostile saved-state controls and linked drafting workflow qualification."""
import copy,json,os,struct,threading,time
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile,ZIP_DEFLATED
from schemaxis.adaptors import registry
from schemaxis.artifacts import atomic_json,file_digest,runtime_archive
from schemaxis.core.faults import SchemaxisError
from schemaxis import workflow
from freecad_draft_profile_cases import oracle
from qualify_freecad_mesh import refresh


def reference_lifecycle(directory,target,saved):
    from schemaxis.adaptors.freecad.process import SubprocessRunner
    from schemaxis.dispatch import allocation,execution_deadline
    original_call=SubprocessRunner.__call__;results=[]
    names=('model.FCStd','verification.json','model.FCStd.metadata.json','publication-metadata.json')
    original={n:(target/n).read_bytes() for n in names}
    try:
        (target/'model.FCStd').write_bytes(saved.read_bytes());refresh(target)
        assert registry.verify(target)['verified']
        for mode in ('timeout','cancel'):
            marker=directory/(mode+'-reference-pid.txt');cancel=threading.Event();thread=None
            def slow(self,code):
                if 'part_reference_native import resave' in code:
                    code=('import os,time\nfrom pathlib import Path\nPath('+repr(str(marker))+').write_text(str(os.getpid()))\ntime.sleep(20)\n')+code
                return original_call(self,code)
            def stop():
                end=time.monotonic()+12
                while not marker.exists() and time.monotonic()<end:time.sleep(.05)
                cancel.set()
            try:
                with patch.object(SubprocessRunner,'__call__',slow):
                    if mode=='cancel':thread=threading.Thread(target=stop);thread.start()
                    with allocation({},cancel=cancel),execution_deadline(12 if mode=='timeout' else 18):registry.verify(target)
            except SchemaxisError as error:
                assert error.fault.code==('RUNNER_TIMED_OUT' if mode=='timeout' else 'RUNNER_CANCELLED'),error.fault
            else:raise AssertionError('reference lifecycle control completed')
            finally:
                if thread:thread.join(timeout=13)
            assert marker.exists(),'second trusted native worker did not start';pid=int(marker.read_text())
            try:os.kill(pid,0)
            except ProcessLookupError:pass
            else:raise AssertionError('trusted reference worker remains alive')
            results.append({'mode':mode,'pid':pid,'stopped':True})
        assert registry.verify(target)['verified']
    finally:
        for name,payload in original.items():(target/name).write_bytes(payload)
    assert registry.verify(target)['verified'];return results


def alterations(directory,resaved,replacement):
    files=('model.FCStd','built.json','verification.json','model.FCStd.metadata.json','publication-metadata.json')
    original={n:(directory/n).read_bytes() for n in files}
    with ZipFile(directory/'model.FCStd') as archive:members={n:archive.read(n) for n in archive.namelist()}
    with ZipFile(resaved) as archive:saved={n:archive.read(n) for n in archive.namelist()}
    def prop(root,name,obj='N0'):return root.find("./ObjectData/Object[@name='%s']/Properties/Property[@name='%s']"%(obj,name))
    def points(root,data):
        value=bytearray(data['Points']);assert struct.unpack_from('<I',value)[0]==6
        struct.pack_into('<d',value,4,.25);data['Points']=bytes(value)
    def proxy(root,data):prop(root,'Proxy')[0].set('module','foreign.untrusted')
    def transient(root,data):
        p=root.find("./ObjectData/Object[@name='N0']/Properties");p.set('TransientCount','2')
        ET.SubElement(p,'_Property',name='HiddenCode',type='App::PropertyPythonObject',status='234881024')
    def extension(root,data):ET.SubElement(root.find("./ObjectData/Object[@name='N0']/Extensions"),'Extension',type='App::ForeignExtensionPython')
    def role(root,data):p=prop(root,'Points');p.set('status',str(int(p.get('status'))^4))
    def engine(root,data):
        p=prop(root,'ExpressionEngine')[0];p.set('count','1');ET.SubElement(p,'Expression',path='FilletRadius',expression='1')
    def geometry(root,data):data[prop(root,'Shape').find('Part').get('file')]=replacement
    def mixed_map(root,data):
        member=prop(root,'Shape','N3').find('ElementMap2').get('file')
        old,new=data[member],saved[member];assert old!=new
        # Half of a legitimate save-state transition is not either complete
        # trusted reference. Preserve syntax and all related existing SIDs.
        a,b=old.splitlines(True),new.splitlines(True);assert len(a)==len(b)
        changed=[i for i,(x,y) in enumerate(zip(a,b)) if x!=y];assert len(changed)>=2
        a[changed[0]]=b[changed[0]];data[member]=b''.join(a)
    def unused_sid(root,data):
        member=root.find('StringHasher2').get('file');lines=data[member].decode().splitlines()
        head=lines[0].split();head[-1]=str(int(head[-1])+1);lines[0]=' '.join(head)
        lines.append('-1.0 0:UnreferencedForgedName');data[member]=('\n'.join(lines)+'\n').encode()
    def gui_python(root,data):
        r=ET.fromstring(data['GuiDocument.xml']);p=r.find('./ViewProviderData/ViewProvider/Properties')
        p.set('Count','2');q=ET.SubElement(p,'Property',name='Proxy',type='App::PropertyPythonObject')
        ET.SubElement(q,'Python',module='foreign.untrusted',value='e30=',encoded='yes',**{'class':'Bad'})
        data['GuiDocument.xml']=ET.tostring(r,encoding='utf-8',xml_declaration=True)
    changes=[('native-points',points),('python-proxy',proxy),('foreign-transient',transient),('foreign-extension',extension),
        ('persistence-role',role),('expression-engine',engine),('saved-brep',geometry),('mixed-reference-map',mixed_map),
        ('unused-string-id',unused_sid),('foreign-gui-python',gui_python),
        ('closed',lambda r,d:prop(r,'Closed')[0].set('value','false')),
        ('face-policy',lambda r,d:prop(r,'MakeFace')[0].set('value','false')),
        ('fillet-policy',lambda r,d:prop(r,'FilletRadius')[0].set('value','0.1')),
        ('subdivision-policy',lambda r,d:prop(r,'Subdivisions')[0].set('value','1')),
        ('profile-placement',lambda r,d:prop(r,'Placement')[0].set('Px','1')),
        ('base-link',lambda r,d:prop(r,'Base')[0].set('value','N2')),
        ('cached-cut-link',lambda r,d:prop(r,'Tool','N3')[0].set('value','N1')),
        ('unreferenced-payload',lambda r,d:d.update({'UnusedGeometry.brp':replacement}))]
    results=[]
    try:
        for label,change in changes:
            for name,payload in original.items():(directory/name).write_bytes(payload)
            data=dict(members);root=ET.fromstring(data['Document.xml']);change(root,data)
            data['Document.xml']=ET.tostring(root,encoding='utf-8',xml_declaration=True)
            with ZipFile(directory/'model.FCStd','w',compression=ZIP_DEFLATED) as archive:
                for name,payload in data.items():archive.writestr(name,payload)
            refresh(directory)
            try:registry.verify(directory)
            except SchemaxisError as error:
                assert error.fault.code=='VERIFICATION_FAILED',(label,error.fault)
                results.append({'case':label,'code':error.fault.code,'observed':error.fault.to_dict()['observed']})
            else:raise AssertionError('altered Draft state accepted: '+label)
            atomic_json(directory/'saved-guard-results.json',results)
        for name,payload in original.items():(directory/name).write_bytes(payload)
        assert registry.verify(directory)['verified'];results.append({'case':'restored-positive','verified':True})
        from schemaxis.adaptors.freecad.assembly_sources import admit
        with patch('subprocess.Popen',side_effect=AssertionError('unsupported source reached native execution')):
            try:admit(str(directory/'model.FCStd'),'draft-profile')
            except SchemaxisError as error:assert error.fault.code=='UNSUPPORTED_SOURCE';results.append({'case':'unsupported-history-source-before-spawn','code':error.fault.code})
            else:raise AssertionError('Draft Part graph admitted as a Body history source')
        atomic_json(directory/'saved-guard-results.json',results)
    finally:
        for name,payload in original.items():(directory/name).write_bytes(payload)
    return results


def first_open(directory,target,gui):
    from schemaxis.adaptors.freecad.gui_process import run
    assert registry.verify(target)['verified'];directory.mkdir()
    atomic_json(directory/'part-gui-request.json',{'file':str(target/'model.FCStd'),'sha256':file_digest(target/'model.FCStd'),
        'prepared':json.loads((target/'plan.json').read_text())})
    (directory/'runtime.zip').write_bytes(runtime_archive())
    result=run(directory,gui,'inspect',family='part',timeout=120)
    assert result['completed'] and result['observed']['output']=='N3'
    assert (directory/'part-first-open.png').stat().st_size>1000
    return result


def linked_workflow(directory,document,locations):
    facts=oracle();drawing={'version':'schemaxis.freecad.drawing/1','source':{
        'file':{'$artifact':'part','index':2},'object':'bracket','units':'mm',
        'expect':{k:facts[k] for k in ('volume','bounds','centreOfMass')}},
        'sheet':{'title':'Editable Draft profile bracket','revision':'A'},'views':['front','top','right','isometric'],
        'dimensioning':[{'id':'length','view':'front','type':'overallWidth'},
                        {'id':'depth','view':'top','type':'overallHeight'},
                        {'id':'bore','view':'top','type':'diameter','radius':.5}],
        'notes':['Dimensions in millimetres','Editable polygon profile and native drilling']}
    envelope={'version':'schemaxis.workflow/1','execution':{'maxWorkers':1,'cpus':2,'memoryMB':4096,'gpus':0},
        'operations':[{'id':'part','document':document},{'id':'drawing','document':drawing},
                      {'id':'independent','document':{'version':'schemaxis.freecad/1','nodes':[{'id':'stock','filter':'box','options':{'length':10,'width':5,'height':2}}],'output':'stock'}}]}
    target=directory/'workflow';workflow.execute(envelope,target,locations=locations,timeout=600);assert workflow.verify(target)['verified']
    reused=workflow.execute(envelope,target,locations=locations,timeout=600,resume=True);assert all(j['reused'] for j in reused['jobs'])
    drawjob=Path(next(j['directory'] for j in reused['jobs'] if j['operation']=='drawing'))
    (drawjob/'drawing.svg').write_text('damaged drawing publication')
    rebuilt=workflow.execute(envelope,target,locations=locations,timeout=600,resume=True);assert workflow.verify(target)['verified']
    state={j['operation']:j['reused'] for j in rebuilt['jobs']};assert state=={'part':True,'drawing':False,'independent':True},state
    drawjob=Path(next(j['directory'] for j in rebuilt['jobs'] if j['operation']=='drawing'))
    changed=copy.deepcopy(envelope);changed['operations'][0]['document']['nodes'][2]['options']['radius']=.6
    try:workflow.execute(changed,target,locations=locations,timeout=600,resume=True)
    except SchemaxisError as error:assert error.fault.code=='RESUME_MISMATCH'
    else:raise AssertionError('changed Draft machining intent reused old workflow')
    # Drawing retains its frozen source after the standalone producer is moved.
    producer=Path(next(j['directory'] for j in rebuilt['jobs'] if j['operation']=='part'));hidden=producer.with_name(producer.name+'-hidden')
    producer.rename(hidden)
    try:assert registry.verify(drawjob)['verified']
    finally:hidden.rename(producer)
    assert workflow.verify(target)['verified']
    return {'verified':True,'reuse':True,'afterDamage':state,'changedIntentRefused':True,'producerRemoval':True,'drawingDirectory':str(drawjob)}
