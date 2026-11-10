#!/usr/bin/env python3
"""Qualify native milling, independent material replay and durable workflow controls."""
import argparse
import base64
import copy
import json
from pathlib import Path
import shutil
import os
import select
import subprocess
import time
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from schemaxis.adaptors import registry
from schemaxis.adaptors.freecad import cam
from schemaxis.adaptor_delivery import source_digest
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.core.faults import SchemaxisError
from schemaxis.core.runners import Interpreter
from schemaxis.adaptors.freecad.process import SubprocessRunner
from schemaxis import workflow
ROOT=Path(__file__).resolve().parents[1]


def hostile(target):
    target=Path(target);native=target/'machining.FCStd';original=native.read_bytes();material=target/'material.json';receipt=material.read_bytes();report={}
    def reject(name,message=None):
        try:cam._native_verify(target)
        except SchemaxisError as error:
            if message is not None:assert message in error.fault.message,(name,error.fault.message)
            report[name]=error.fault.code
        else:raise AssertionError(name+' tamper accepted')
    with ZipFile(native) as archive:members={n:archive.read(n) for n in archive.namelist()}
    for name,obj,prop,attr,value in [('feed','Cutter','HorizFeed','value','999'),('diameter','Endmill','Diameter','value','4'),('step-down','Op_cavity','StepDown','value','7'),('target-face','Op_cavity','Base','sub','Face1'),('tool-proxy','Endmill','Proxy','module','hostile.tool')]:
        try:
            root=ET.fromstring(members['Document.xml']);p=root.find("./ObjectData/Object[@name='"+obj+"']/Properties/Property[@name='"+prop+"']")
            node=p[0][0] if prop=='Base' else p[0];node.set(attr,value)
            with ZipFile(native,'w') as archive:
                for n,payload in members.items():archive.writestr(n,ET.tostring(root) if n=='Document.xml' else payload)
            m=json.loads(receipt);m['nativeSha256']=file_digest(native);atomic_json(material,m);reject(name)
        finally:native.write_bytes(original);material.write_bytes(receipt)
    for name,obj,change in [
        ('proxy-encoding','Machining',lambda n:n.set('encoded','no')),
        ('proxy-null-state','Machining',lambda n:n.set('value',base64.b64encode(b'{"foreign":true}').decode())),
        ('proxy-child','Cutter',lambda n:ET.SubElement(n,'Foreign')),
        ('tool-shape-path','Endmill',lambda n:state_change(n,'_obj_data','shape','../../foreign.fcstd')),
        ('tool-shape-id','Endmill',lambda n:state_change(n,'_shape_data','id','../../foreign')),
        ('tool-state-diameter','Endmill',lambda n:state_change(n,'_obj_data','parameter',{'Diameter':'4.00 mm'})),
        ('tool-state-uuid','Endmill',lambda n:state_change(n,'_obj_data','id','foreign-uuid')),
    ]:
        try:
            root=ET.fromstring(members['Document.xml']);node=root.find("./ObjectData/Object[@name='"+obj+"']/Properties/Property[@name='Proxy']/Python");change(node)
            with ZipFile(native,'w') as archive:
                for member,payload in members.items():archive.writestr(member,ET.tostring(root) if member=='Document.xml' else payload)
            m=json.loads(receipt);m['nativeSha256']=file_digest(native);atomic_json(material,m);reject(name,'Saved native proxy')
        finally:native.write_bytes(original);material.write_bytes(receipt)
    program=target/'program.ngc';nc=program.read_bytes()
    try:
        changed=re.sub(r'(?m)^(G[23] .*?\bI)([-+0-9.]+)',lambda m:m.group(1)+format(float(m.group(2))+1e-5,'.8f'),nc.decode(),count=1)
        assert changed!=nc.decode(),'Off-radius adversary did not change program'
        program.write_text(changed);m=json.loads(receipt);m['programSha256']=file_digest(program);atomic_json(material,m)
        reject('off-radius-arc','arc endpoints do not share a radius')
    finally:program.write_bytes(nc);material.write_bytes(receipt)
    try:
        root=ET.fromstring(members['Document.xml']);node=root.find("./ObjectData/Object[@name='Op_cavity']/Properties/Property[@name='Path']/Path")
        member=node.get('file');path=members[member].decode()
        changed=re.sub(r'(?m)^(G[23] .*?)\bK[-+0-9.]+',r'\1K0.001',path,count=1)
        if changed==path:changed=re.sub(r'(?m)^(G[23] .*)$',r'\1 K0.001',path,count=1)
        assert changed!=path,'Nonzero-K adversary did not change native path'
        with ZipFile(native,'w') as archive:
            for name,payload in members.items():archive.writestr(name,changed.encode() if name==member else payload)
        m=json.loads(receipt);m['nativeSha256']=file_digest(native);atomic_json(material,m)
        reject('native-nonzero-K','Saved native XY path has nonzero K')
    finally:native.write_bytes(original);material.write_bytes(receipt)
    try:
        program.write_text(nc.decode().replace('F300.000000','F999.000000').replace('F300','F999'));m=json.loads(receipt);m['programSha256']=file_digest(program);atomic_json(material,m);reject('posted-feed')
    finally:program.write_bytes(nc);material.write_bytes(receipt)
    for reset in ('G40','G80','G61','G92.1'):
        try:
            program.write_text(nc.decode().replace(reset,''));m=json.loads(receipt);m['programSha256']=file_digest(program);atomic_json(material,m)
            reject('removed-'+reset,'Motion requires explicit cutter/cycle cancellation')
        finally:program.write_bytes(nc);material.write_bytes(receipt)
    try:
        m=json.loads(receipt);m['residualVolume']=0;m['assessedResidualVolume']=0;atomic_json(material,m);reject('forged-material-summary')
    finally:material.write_bytes(receipt)
    try:
        root=ET.fromstring(members['Document.xml']);properties=root.find("./ObjectData/Object[@name='Source']/Properties")
        prop=ET.SubElement(properties,'Property',{'name':'Injected','type':'App::PropertyPythonObject'});ET.SubElement(prop,'Python',{'module':'hostile.module','class':'Executable','encoded':'yes','value':'e30='});properties.set('Count',str(len(properties)))
        with ZipFile(native,'w') as archive:
            for name,payload in members.items():archive.writestr(name,ET.tostring(root) if name=='Document.xml' else payload)
        m=json.loads(receipt);m['nativeSha256']=file_digest(native);atomic_json(material,m)
        try:cam._native_verify(target)
        except SchemaxisError as error:
            assert 'Saved CAM property membership or types differ' in error.fault.message;report['foreign-python-property']=error.fault.code
        else:raise AssertionError('foreign native Python property accepted')
    finally:native.write_bytes(original);material.write_bytes(receipt)
    profile=target/'preferences.cfg';original_profile=profile.read_bytes()
    try:profile.write_bytes(original_profile.replace(b'0.00001',b'0.01'));reject('regeneration-profile')
    finally:profile.write_bytes(original_profile)
    bundle=target/'cam-project.zip';original_bundle=bundle.read_bytes()
    try:
        with ZipFile(bundle,'a') as archive:archive.writestr('unexpected.py','raise RuntimeError()')
        reject('foreign-bundle-member')
    finally:bundle.write_bytes(original_bundle)
    report.update(tool_hostile(target))
    return report


def tool_hostile(target):
    """Actual product verification; refresh companion bundle/digests per edit."""
    from schemaxis.adaptors.freecad.cam_publication import publish
    target=Path(target);native=target/'machining.FCStd';material=target/'material.json'
    retained={name:(target/name).read_bytes() for name in ('machining.FCStd','material.json','cam-project.zip','verification.json','preferences.cfg')}
    with ZipFile(native) as archive:members={name:archive.read(name) for name in archive.namelist()}
    report={}
    def prop(root,obj,key):return root.find("./ObjectData/Object[@name='"+obj+"']/Properties/Property[@name='"+key+"']")
    def parameter(root,obj,key,value):prop(root,obj,key)[0].set('value',value)
    def expression(root):
        node=prop(root,'Sketch','ExpressionEngine')[0];node[0].set('expression','<<Attributes>>.Diameter')
    def extension(root):
        obj=root.find("./ObjectData/Object[@name='Source']");obj.set('Extensions','True');node=ET.Element('Extensions',{'Count':'1'});ET.SubElement(node,'Extension',{'type':'App::GroupExtensionPython','name':'Foreign'});obj.insert(0,node)
    def external_link(root):
        props=root.find("./ObjectData/Object[@name='Source']/Properties");node=ET.SubElement(props,'Property',{'name':'Foreign','type':'App::PropertyXLink'});ET.SubElement(node,'XLink',{'file':'foreign.FCStd','name':'Object'});props.set('Count',str(int(props.get('Count'))+1))
    for name,change,expected,native_guard in [
        ('tool-attribute-graph',lambda root:parameter(root,'PropertyBag','Diameter','4'),'Saved editable tool property or dependency graph differs',True),
        ('tool-revolution-graph',lambda root:parameter(root,'Revolution','Angle','180'),'Saved editable tool property or dependency graph differs',True),
        ('tool-expression-graph',expression,'Saved CAM expression dependencies differ',False),
        ('foreign-native-extension',extension,'Saved CAM object or extension structure differs',False),
        ('foreign-external-link',external_link,'Saved CAM property membership or types differ',False),
    ]:
        try:
            root=ET.fromstring(members['Document.xml']);change(root)
            with ZipFile(native,'w') as archive:
                for member,payload in members.items():archive.writestr(member,ET.tostring(root) if member=='Document.xml' else payload)
            data=json.loads(retained['material.json']);data['nativeSha256']=file_digest(native);atomic_json(material,data);publish(target,'1.1.4')
            try:cam._native_verify(target)
            except SchemaxisError as error:
                message=error.fault.observed.get('fault',{}).get('message','') if native_guard else error.fault.message
                assert expected in message,(name,error.fault.to_dict());report[name]=error.fault.code
            else:raise AssertionError(name+' modified editable native graph accepted')
        finally:
            for filename,payload in retained.items():(target/filename).write_bytes(payload)
    for name,member,transform,expected in [
        ('tool-brep-geometry','Endmill.Shape.brp',lambda payload:payload.replace(b'1.50000000000000000',b'1.60000000000000000',1),'Saved editable tool BREP differs'),
        ('tool-map-owner','Endmill.Shape.Map.txt',lambda payload:payload.replace(b' 1622 ',b' 1602 ').replace(b';:H656,',b';:H642,'),'Saved editable tool topological map differs'),
    ]:
        # Owner IDs depend on native allocation, so derive this map mutation
        # from the actual named objects rather than a fixture-specific number.
        if name=='tool-map-owner':
            root=ET.fromstring(members['Document.xml']);ids={o.get('name'):int(o.get('id')) for o in root.findall('./Objects/Object')}
            transform=lambda payload:payload.replace((' '+str(ids['Body'])+' ').encode(),(' '+str(ids['Source'])+' ').encode()).replace((';:H'+format(ids['Body'],'x')+',').encode(),(';:H'+format(ids['Source'],'x')+',').encode())
        try:
            changed=transform(members[member]);assert changed!=members[member],name+' adversary did not change payload'
            with ZipFile(native,'w') as archive:
                for item,payload in members.items():archive.writestr(item,changed if item==member else payload)
            data=json.loads(retained['material.json']);data['nativeSha256']=file_digest(native);atomic_json(material,data);publish(target,'1.1.4')
            try:cam._native_verify(target)
            except SchemaxisError as error:
                message=error.fault.observed.get('fault',{}).get('message','');assert expected in message,(name,error.fault.to_dict());report[name]=error.fault.code
            else:raise AssertionError(name+' modified native payload accepted')
        finally:
            for filename,payload in retained.items():(target/filename).write_bytes(payload)
    try:
        with ZipFile(native,'a') as archive:archive.writestr('GuiDocument.xml','<Document><ForeignProxy/></Document>')
        data=json.loads(retained['material.json']);data['nativeSha256']=file_digest(native);atomic_json(material,data);publish(target,'1.1.4')
        try:cam._native_verify(target)
        except SchemaxisError as error:
            assert 'Published CAM contains foreign GUI state or archive payloads' in error.fault.message;report['foreign-gui-state']=error.fault.code
        else:raise AssertionError('Foreign GUI state accepted')
    finally:
        for filename,payload in retained.items():(target/filename).write_bytes(payload)
    assert cam._native_verify(target)['verified'],'Unchanged companion refresh/restore control failed'
    report['unchanged-tool-graph-control']=True
    return report


def state_change(node,section,key,value):
    state=json.loads(base64.b64decode(node.get('value')))
    if isinstance(value,dict):state[section][key].update(value)
    else:state[section][key]=value
    node.set('value',base64.b64encode(json.dumps(state).encode()).decode())


def gui_edit(directory,executable,stage,*,worker='milling',expected_sha=None):
    from schemaxis.dispatch import terminate_tree,cancellation_requested
    modules={'milling':'qualify_freecad_cam_native','drilling':'qualify_freecad_cam_drilling_native',
             'physical':'qualify_freecad_cam_physical_native',
             'physical-launcher':'qualify_freecad_cam_portable_native'}
    if worker not in modules:raise ValueError('unknown finite CAM qualification worker')
    pinned=worker in ('drilling','physical','physical-launcher')
    if pinned:assert expected_sha and file_digest(Path(directory)/'machining.FCStd')==expected_sha
    if worker=='physical-launcher':
        from schemaxis.adaptors.freecad.cam_reduced import FILENAME,LAUNCHER_NAME,LAUNCHER,module_bytes
        assert (Path(directory)/FILENAME).read_bytes()==module_bytes()
        assert (Path(directory)/LAUNCHER_NAME).read_bytes()==LAUNCHER
    directory=Path(directory);macro=directory/(stage+'.FCMacro');settings=directory/(stage+'-settings');settings.mkdir()
    macro.write_text('import sys\nfrom pathlib import Path\nsys.path.insert(0,'+repr(str(ROOT/'tools'))+')\nsys.path.insert(0,'+repr(str(ROOT/'src'))+')\nimport FreeCAD as App, FreeCADGui as Gui\nphase=Path('+repr(str(directory/(stage+'-phase.txt')))+')\nphase.write_text("macro entered")\ntry:\n from PySide import QtCore,QtGui\n application=QtGui.QApplication.instance()\n widget=application.activeModalWidget() or Gui.getMainWindow()\n for kind in (QtCore.QEvent.KeyPress,QtCore.QEvent.KeyRelease):application.sendEvent(widget,QtGui.QKeyEvent(kind,QtCore.Qt.Key_Escape,QtCore.Qt.NoModifier))\n Gui.activateWorkbench("CAMWorkbench")\n phase.write_text("CAM activated")\n from '+modules[worker]+' import edit\n edit('+repr(str(directory))+','+repr(stage)+(','+repr(expected_sha) if pinned else '')+')\n phase.write_text("edit completed")\nfinally:\n for name in list(App.listDocuments()):App.closeDocument(name)\n Gui.getMainWindow().close()\n')
    xvfb=shutil.which('Xvfb');dbus=shutil.which('dbus-run-session')
    assert xvfb and dbus,'GUI CAM qualification requires Xvfb and a private D-Bus session'
    env=os.environ.copy()
    for key in ('PYTHONHOME','PYTHONPATH','QT_PLUGIN_PATH','QT_QPA_PLATFORM_PLUGIN_PATH','LD_PRELOAD','DISPLAY','WAYLAND_DISPLAY','DBUS_SESSION_BUS_ADDRESS','SESSION_MANAGER','XAUTHORITY'):env.pop(key,None)
    for key,name in (('FREECAD_USER_HOME','home'),('FREECAD_USER_DATA','data'),('FREECAD_USER_TEMP','temp'),('XDG_CONFIG_HOME','config'),('XDG_DATA_HOME','xdg-data'),('XDG_CACHE_HOME','cache'),('XDG_RUNTIME_DIR','runtime')):
        path=settings/name;path.mkdir(mode=0o700);env[key]=str(path)
    env.update(TMPDIR=str(settings/'temp'),TMP=str(settings/'temp'),TEMP=str(settings/'temp'))
    env.update(QT_QPA_PLATFORM='xcb',OMP_NUM_THREADS='1',LIBGL_ALWAYS_SOFTWARE='1',PYTHONDONTWRITEBYTECODE='1')
    read,write=os.pipe();server=None;process=None
    try:
        with (directory/(stage+'-xvfb.log')).open('wb') as log:server=subprocess.Popen([xvfb,'-displayfd',str(write),'-screen','0','1280x960x24','-nolisten','tcp'],pass_fds=(write,),stdout=log,stderr=log,start_new_session=True)
        os.close(write);write=None
        assert select.select([read],[],[],10)[0],'Xvfb did not provide an isolated display'
        display=os.read(read,100).decode().strip();assert display.isdigit(),'Xvfb provided an invalid display'
        env['DISPLAY']=':'+display
        scripts=([str(directory/LAUNCHER_NAME)] if worker=='physical-launcher' else [])+[str(macro)]
        command=[dbus,'--',executable,'--user-cfg',str(directory/'preferences.cfg'),'--system-cfg',str(settings/'system.cfg'),*scripts]
        with (directory/(stage+'.log')).open('wb') as log:
            process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True,env=env,cwd=directory);start=time.monotonic()
            atomic_json(directory/(stage+'-process.json'),{'command':command,'guiGroupPid':process.pid,'xvfbPid':server.pid,'display':env['DISPLAY'],'settings':{key:value for key,value in env.items() if key.startswith(('FREECAD_USER_','XDG_'))},'privateDBus':True})
            while process.poll() is None:
                if cancellation_requested():raise RuntimeError('GUI CAM edit cancelled')
                if time.monotonic()-start>480:raise RuntimeError('GUI CAM edit timed out')
                time.sleep(.05)
    finally:
        if process is not None:terminate_tree(process,{})
        if server is not None:terminate_tree(server,{})
        os.close(read)
        if write is not None:os.close(write)
    assert process.returncode==0 and (directory/(stage+'.json')).is_file(),'Native GUI CAM edit failed; inspect '+str(directory/(stage+'.log'))


def qualify(directory,executable,gui=None,construction_seed=None):
    from schemaxis.configuration import executable as configured
    gui=gui or configured('freecad_gui')
    assert gui and Path(gui).is_absolute() and Path(gui).is_file(),'Configure FreeCAD GUI for carried-profile edit qualification'
    directory=Path(directory).absolute();directory.mkdir(parents=True,exist_ok=False);report={'verified':False,'sourceDigest':source_digest('freecad'),'checks':{}};locations={'freecad':executable}
    runner=SubprocessRunner(Interpreter('freecad',executable),directory,timeout=120)
    def independent(stage,path):
        function='source' if stage=='source' else 'edit';script='import sys\nsys.path.insert(0,'+repr(str(ROOT/'tools'))+')\nfrom qualify_freecad_cam_native import '+function+'\n'+function+'('+repr(str(path))+('' if stage=='source' else ','+repr(stage))+')\n'
        atomic_json(directory/(stage+'-submission.json'),runner(script).to_dict())
    try:
        if construction_seed:
            seed=Path(construction_seed).resolve()
            report['reusedConstruction']={'directory':str(seed),'sourcePolicy':'Historical native construction; current host guards, portable profile, fresh geometry replay and lifecycle tail only are requalified here.','cases':{}}
            for filename in ('source-oracles.json','enclosure.FCStd','enclosure.step','variant.FCStd','variant.step','sharp.FCStd','sharp.step'):
                shutil.copyfile(seed/filename,directory/filename)
            for name in ('native','step','variant'):
                old=seed/name;target=directory/name;target.mkdir()
                # Copy only owned durable output data, never an executable
                # runtime snapshot or a worktree. New replay uses current code.
                for path in old.iterdir():
                    if path.is_file() and path.suffix not in ('.zip','.py') and not path.name.startswith('replay-'):
                        shutil.copyfile(path,target/path.name)
                report['reusedConstruction']['cases'][name]={'builtSha256':file_digest(old/'built.json'),'nativeSha256':file_digest(old/'machining.FCStd'),'programSha256':file_digest(old/'program.ngc')}
                authored=json.loads((target/'authored.json').read_text());plan=json.loads((target/'plan.json').read_text())
                authored['source']['file']=str(directory/Path(authored['source']['file']).name);plan['source']['file']=authored['source']['file']
                atomic_json(target/'authored.json',authored);atomic_json(target/'plan.json',plan)
                from schemaxis.adaptors.freecad.cam_publication import publish
                publish(target,'1.1.4')
                report['checks'][name]=cam._native_verify(target)
                print(name+' historical construction passes current host and fresh geometry verification',flush=True)
            target=directory/'native';base=json.loads((target/'authored.json').read_text());oracles=json.loads((directory/'source-oracles.json').read_text())
        else:
            independent('source',directory);oracles=json.loads((directory/'source-oracles.json').read_text())
            base=json.loads((ROOT/'examples/schemaxis/freecad-cam-enclosure.json').read_text());base['source'].update(file=str(directory/'enclosure.FCStd'),object='enclosure');base['source']['expect']={k:oracles['enclosure'][k] for k in ('volume','bounds','centreOfMass')}
            target=directory/'native';registry.run(base,target,locations=locations,timeout=240);report['checks']['native']=registry.verify(target);print('native millable enclosure verified',flush=True)
            step=copy.deepcopy(base);step['source'].update(file=str(directory/'enclosure.step'));step['source'].pop('object');step['tool'].update(feed=420,plunge=120,rpm=12000);registry.run(step,directory/'step',locations=locations,timeout=240);report['checks']['step']=registry.verify(directory/'step');print('STEP and cutting-data variant verified',flush=True)
            variant=copy.deepcopy(base);variant['source'].update(file=str(directory/'variant.FCStd'),object='variant',expect={k:oracles['variant'][k] for k in ('volume','bounds','centreOfMass')});variant['operations'][1]['floor']=oracles['variant']['floor'];variant['tool'].update(diameter=4,shankDiameter=4,cuttingLength=30,length=60);variant['operations'][1]['stepDown']=3
            registry.run(variant,directory/'variant',locations=locations,timeout=240);report['checks']['variant']=registry.verify(directory/'variant');print('held-out geometry/tool variant verified',flush=True)
        report['checks']['hostile']=hostile(target)
        portable=directory/'portable';portable.mkdir()
        with ZipFile(target/'cam-project.zip') as bundle:bundle.extractall(portable)
        for filename in ('plan.json','source.FCStd','source.brep'):shutil.copyfile(target/filename,portable/filename)
        gui_edit(portable,gui,'edit');gui_edit(portable,gui,'reopen');a=json.loads((portable/'edit.json').read_text());b=json.loads((portable/'reopen.json').read_text());assert a['verified'] and b['verified'] and a['pid']!=b['pid'] and a['areaAccuracy']==b['areaAccuracy']==1e-5
        plan=json.loads((portable/'plan.json').read_text());plan['operations'][1]['stepDown']=1.25;atomic_json(portable/'plan.json',plan)
        from schemaxis.adaptors.freecad.cam_checks import compare_saved_paths
        compare_saved_paths(portable,plan)
        assert file_digest(portable/'program.ngc')!=file_digest(target/'program.ngc'),'Native edit did not change posted program'
        assert a['programSha256']==b['programSha256']==file_digest(portable/'program.ngc'),'Fresh reopen/repost changed edited program'
        script='import sys\nsys.path.insert(0,'+repr(str(ROOT/'src'))+')\nfrom schemaxis.adaptors.freecad.cam_material import material\nfrom schemaxis.native_boundary import execute_guarded\nexecute_guarded(material,'+repr(str(portable))+')\n';runner(script)
        assert not (portable/'native-fault.json').exists(),'Edited material replay refused outputs'
        edited=json.loads((portable/'material.json').read_text());assert edited['verified']
        from schemaxis.adaptors.freecad.cam_verify import fresh_material
        current=fresh_material(portable)
        assert current['pid']!=edited['pid'] and {k:v for k,v in current.items() if k!='pid'}=={k:v for k,v in edited.items() if k!='pid'},'Fresh edited-program replay differs'
        report['checks']['portable-edit']={'verified':True,'separateProcesses':True,'guiWorkbenchProfileApplied':True,'savedPathBound':True,'programChanged':True,'unchangedReopenRepost':True,'freshEditedMaterial':True,'editedMaterial':edited}
        sharp=copy.deepcopy(base);sharp['source'].update(file=str(directory/'sharp.FCStd'),object='sharp',expect={k:oracles['sharp'][k] for k in ('volume','bounds','centreOfMass')})
        try:registry.run(sharp,directory/'sharp-rejected',locations=locations,timeout=240)
        except SchemaxisError as error:assert error.fault.code=='UNFINISHED_MATERIAL';report['checks']['unreachable-sharp-corners']=error.fault.code
        else:raise AssertionError('finite cutter claimed to finish sharp cavity corners')
        envelope=json.loads((ROOT/'examples/schemaxis/freecad-cam-workflow.json').read_text());wf=directory/'workflow';workflow.execute(envelope,wf,locations=locations,timeout=240);workflow.verify(wf);reused=workflow.execute(envelope,wf,locations=locations,timeout=240,resume=True);assert all(j['reused'] for j in reused['jobs']);job=Path(next(j['directory'] for j in reused['jobs'] if j['operation']=='machining'));(job/'program.ngc').write_text('corrupted NC');updated=workflow.execute(envelope,wf,locations=locations,timeout=240,resume=True);workflow.verify(wf);state={j['operation']:j['reused'] for j in updated['jobs']};assert state=={'enclosure':True,'machining':False};report['checks']['workflow']={'resume':True,'afterNCDamage':state}
        for file in ('enclosure.FCStd','enclosure.step'): (directory/file).unlink()
        assert cam._native_verify(target)['verified'] and cam._native_verify(directory/'step')['verified'];report['checks']['source-removal']={'verified':True};assert report['sourceDigest']==source_digest('freecad'),'source changed during qualification';report['verified']=True
    finally:atomic_json(directory/'report.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',required=True);parser.add_argument('--executable',required=True);parser.add_argument('--gui');parser.add_argument('--construction-seed');args=parser.parse_args();print(json.dumps(qualify(args.directory,args.executable,args.gui,args.construction_seed),indent=2))
