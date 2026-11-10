#!/usr/bin/env python3
"""Qualify meaningful enclosure drawing workflows and independent lifecycle controls."""
import argparse
import copy
import json
import math
from pathlib import Path
import shutil
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from schemaxis.adaptors import registry
from schemaxis.adaptors.freecad import drawing
from schemaxis.adaptor_delivery import source_digest
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.core.faults import SchemaxisError
from schemaxis.core.runners import Interpreter
from schemaxis.adaptors.freecad.process import SubprocessRunner
from schemaxis import workflow
ROOT=Path(__file__).resolve().parents[1]


def hostile(target):
    path=target/'drawing.FCStd';original=path.read_bytes();receiptpath=target/'verification.json';receiptbytes=receiptpath.read_bytes()
    with ZipFile(path) as z:members={n:z.read(n) for n in z.namelist()}
    def prop(r,name,key):return r.find("./ObjectData/Object[@name='%s']/Properties/Property[@name='%s']"%(name,key))
    changes={'source-placement':lambda r:prop(r,'Source','Placement').find('PropertyPlacement').set('Px','1'),
      'view-scale':lambda r:prop(r,'View_top','Scale').find('Float').set('value','3'),
      'source-link':lambda r:prop(r,'View_top','Source').find('LinkList/Link').set('value','View_front'),
      'view-direction':lambda r:prop(r,'View_top','Direction').find('PropertyVector').set('valueZ','-1'),
      'dimension-type':lambda r:prop(r,'Dimension_wall','Type').find('Integer').set('value','2'),
      'dimension-mode':lambda r:prop(r,'Dimension_wall','Arbitrary').find('Bool').set('value','true'),
      'dimension-measure':lambda r:prop(r,'Dimension_wall','MeasureType').find('Integer').set('value','0'),
      'annotation':lambda r:prop(r,'Title','Text').find('StringList/String').set('value','Wrong model'),
      'sheet-width':lambda r:prop(r,'Template','Width').find('Float').set('value','100')}
    report={}
    for label,change in changes.items():
        try:
            root=ET.fromstring(members['Document.xml']);change(root)
            with ZipFile(path,'w') as z:
                for n,data in members.items():z.writestr(n,ET.tostring(root) if n=='Document.xml' else data)
            receipt=json.loads(receiptbytes);receipt['artifacts'][0]['sha256']=file_digest(path);atomic_json(receiptpath,receipt)
            try:drawing._native_verify(target)
            except SchemaxisError as error:
                assert error.fault.code=='VERIFICATION_FAILED' and 'bytes differ' not in error.fault.message;report[label]=error.fault.code
            else:raise AssertionError('saved drawing tamper accepted: '+label)
        finally:path.write_bytes(original);receiptpath.write_bytes(receiptbytes)
    # Publication has its own content check even when its refreshed hash matches.
    svg=target/'drawing.svg';before=svg.read_bytes()
    try:
        svg.write_text(before.decode().replace('2.000 mm','9.000 mm'))
        receipt=json.loads(receiptbytes);receipt['artifacts'][1]['sha256']=file_digest(svg);atomic_json(receiptpath,receipt)
        try:drawing._native_verify(target)
        except SchemaxisError as error:assert error.fault.code=='VERIFICATION_FAILED';report['svg-measurement']=error.fault.code
        else:raise AssertionError('wrong published wall dimension accepted')
    finally:svg.write_bytes(before);receiptpath.write_bytes(receiptbytes)
    assert registry.verify(target)['verified'];return report


def qualify(directory,executable,gui):
    directory=Path(directory).absolute();directory.mkdir(parents=True,exist_ok=False);report={'verified':False,'sourceDigest':source_digest('freecad'),'checks':{}}
    locations={'freecad':executable,'freecad_gui':gui};runner=SubprocessRunner(Interpreter('freecad',executable),directory,timeout=120)
    def isolated(target):
        launch=json.loads((target/'publish-launch.json').read_text())
        transport=json.loads((target/'publish-transport.json').read_text())
        assert transport['completed'] is True
        values=transport['isolation'];root=Path(launch['privateSettings']).resolve()
        for key in ('FREECAD_USER_HOME','FREECAD_USER_DATA','FREECAD_USER_TEMP','XDG_CONFIG_HOME',
                    'XDG_DATA_HOME','XDG_CACHE_HOME','XDG_RUNTIME_DIR','TMPDIR','userParameter','systemParameter','userAppData'):
            assert Path(values[key]).resolve().is_relative_to(root),(key,values[key])
        assert values['display']==launch['display'] and values['display'].startswith(':')
        assert values['migrationOffer']=='v1-1'
        assert values['userParameter']==launch['userParameter'] and values['systemParameter']==launch['systemParameter']
        return {'completed':True,'isolation':values,'guiPid':launch['guiPid']}
    def independent(stage,path):
        source='import sys\nsys.path.insert(0,'+repr(str(ROOT/'tools'))+')\nfrom qualify_freecad_drawing_native import '+stage.split('-')[0]+'\n'
        source+=('source('+repr(str(path))+')\n') if stage=='source' else ('edit('+repr(str(path))+','+repr(stage.split('-')[1])+')\n')
        atomic_json(directory/(stage+'-submission.json'),runner(source).to_dict())
    try:
        independent('source',directory);oracle=json.loads((directory/'source-oracle.json').read_text());assert oracle['verified']
        expected={k:oracle[k] for k in ('volume','bounds','centreOfMass')}
        base={'version':drawing.VERSION,'source':{'file':str(directory/'enclosure.FCStd'),'object':'enclosure','units':'mm','expect':expected},'sheet':{'title':'Parametric enclosure - manufacturing drawing','revision':'A'},'views':['front','top','right','isometric'],'notes':['Wall and floor thickness 2 mm','4 mounting bores diameter 4 mm'],
          'dimensioning':[{'id':'width','view':'top','type':'overallWidth'},{'id':'depth','view':'right','type':'overallHeight'},
          {'id':'wall','view':'top','type':'horizontal','from':{'point':[0,0,30]},'to':{'point':[2,2,30]}},
          {'id':'mount','view':'top','type':'horizontal','from':{'point':[0,0,30]},'to':{'point':[10,10,2],'on':'circleCentre','radius':2}}]}
        target=directory/'native';registry.run(base,target,locations=locations,timeout=120);report['checks']['native']=registry.verify(target);report['checks']['gui-isolation']=[isolated(target)];print('enclosure FCStd source verified',flush=True)
        step=copy.deepcopy(base);step['source'].update(file=str(directory/'enclosure.step'));step['source'].pop('object');step['sheet'].update(size='A3',scale=.5);step['views']=['front','top','left','rear','bottom'];step['dimensioning']=[base['dimensioning'][0],base['dimensioning'][2]]
        registry.run(step,directory/'step',locations=locations,timeout=120);report['checks']['step']=registry.verify(directory/'step');report['checks']['gui-isolation'].append(isolated(directory/'step'));print('STEP source and sheet/view variant verified',flush=True)
        for name,expected,dimensions in [('cylinder',{'volume':300*math.pi,'bounds':[-5,5,-5,5,0,12],'centreOfMass':[0,0,6]},[{'id':'diameter','view':'top','type':'diameter','radius':5},{'id':'radius','view':'top','type':'radius','radius':5}]),('triangle',{'volume':2100,'bounds':[0,30,0,20,0,7],'centreOfMass':[10,20/3,3.5]},[{'id':'edge','view':'top','type':'edgeLength','length':30},{'id':'diagonal','view':'top','type':'distance','from':{'point':[0,0,0]},'to':{'point':[30,0,0]}},{'id':'height','view':'top','type':'vertical','from':{'point':[0,0,0]},'to':{'point':[0,20,0]}}])]:
            doc={'version':drawing.VERSION,'source':{'file':str(directory/(name+'.FCStd')),'object':name,'units':'mm','expect':expected},'sheet':{'title':name+' measured drawing'},'views':['front','top','right'],'dimensioning':dimensions}
            registry.run(doc,directory/name,locations=locations,timeout=120);report['checks'][name]=registry.verify(directory/name);report['checks']['gui-isolation'].append(isolated(directory/name));print(name+' measured geometry verified',flush=True)
        report['checks']['hostile']=hostile(target)
        portable=directory/'portable';portable.mkdir();shutil.copyfile(target/'drawing.FCStd',portable/'drawing.FCStd')
        independent('edit-edit',portable);independent('edit-reopen',portable)
        a=json.loads((portable/'edit.json').read_text());b=json.loads((portable/'reopen.json').read_text());assert a['verified'] and b['verified'] and a['pid']!=b['pid'];report['checks']['portable-edit']={'verified':True,'separateProcesses':True,'templateAndGeometryEmbedded':True}
        wrong=copy.deepcopy(base);wrong['source']['expect']['volume']+=10
        try:registry.run(wrong,directory/'wrong-geometry',locations=locations,timeout=120)
        except SchemaxisError as error:assert error.fault.code=='EXPECTATION_FAILED';report['checks']['wrong-geometry']=error.fault.code
        else:raise AssertionError('wrong geometry expectation accepted')
        ambiguous=copy.deepcopy(base);ambiguous['dimensioning']=[{'id':'ambiguous','view':'top','type':'diameter','radius':2}]
        try:registry.run(ambiguous,directory/'ambiguous',locations=locations,timeout=120)
        except SchemaxisError as error:assert error.fault.code=='AMBIGUOUS_SELECTION';report['checks']['ambiguous']=error.fault.code
        else:raise AssertionError('ambiguous mounting hole accepted')
        # Workflow adopts editable CAD publication and independently authored
        # dimensions; an unrelated branch stays reusable after drawing corruption.
        envelope={'version':'schemaxis.workflow/1','operations':[{'id':'model','document':{'version':'schemaxis.freecad/1','nodes':[{'id':'stock','filter':'box','options':{'length':40,'width':30,'height':10}}],'output':'stock'}},
          {'id':'drawing','document':{'version':drawing.VERSION,'source':{'file':{'$artifact':'model','index':2},'object':'stock','units':'mm','expect':{'volume':12000,'bounds':[0,40,0,30,0,10],'centreOfMass':[20,15,5]}},'sheet':{'title':'Manufacturing stock'},'views':['front','top','right'],'dimensioning':[{'id':'length','view':'front','type':'overallWidth'}]}},
          {'id':'independent','document':{'version':'schemaxis.freecad/1','nodes':[{'id':'body','filter':'box'}],'output':'body'}}]}
        wf=directory/'workflow';workflow.execute(envelope,wf,locations=locations,timeout=120);workflow.verify(wf)
        reused=workflow.execute(envelope,wf,locations=locations,timeout=120,resume=True);assert all(j['reused'] for j in reused['jobs'])
        drawjob=Path(next(j['directory'] for j in reused['jobs'] if j['operation']=='drawing'));(drawjob/'drawing.svg').write_text('wrong published drawing')
        updated=workflow.execute(envelope,wf,locations=locations,timeout=120,resume=True);workflow.verify(wf);state={j['operation']:j['reused'] for j in updated['jobs']};assert state=={'model':True,'drawing':False,'independent':True};report['checks']['workflow']={'resume':True,'afterDrawingDamage':state}
        # Retained verification does not need the original supplier geometry.
        for path in (directory/'enclosure.FCStd',directory/'enclosure.step'):path.unlink()
        assert registry.verify(target)['verified'] and registry.verify(directory/'step')['verified'];report['checks']['source-removal']={'verified':True}
        assert report['sourceDigest']==source_digest('freecad'),'source changed during qualification';report['verified']=True
    finally:atomic_json(directory/'report.json',report)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',required=True);p.add_argument('--executable',required=True);p.add_argument('--gui',required=True);args=p.parse_args();print(json.dumps(qualify(args.directory,args.executable,args.gui),indent=2))
