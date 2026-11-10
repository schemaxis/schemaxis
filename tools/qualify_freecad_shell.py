#!/usr/bin/env python3
"""Uniform-wall native family qualification and independent offset integrals."""
import argparse,json,math,copy
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from schemaxis.adaptors import registry
from schemaxis.adaptors.freecad import adaptor
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptor_delivery import source_digest
from schemaxis.core.runners import Interpreter
from schemaxis.dispatch import SubprocessRunner
from freecad_shell_cases import cases,part


def attacks(target):
    path=target/'model.FCStd';original=path.read_bytes();rp=target/'verification.json';rb=rp.read_bytes()
    with ZipFile(path) as z:entries={n:z.read(n) for n in z.namelist()}
    def prop(r,key):return r.find("./ObjectData/Object[@name='N3']/Properties/Property[@name='%s']"%key)
    changes={
        'wall-value':lambda r:prop(r,'Value').find('Float').set('value','2'),
        'wall-property-type':lambda r:prop(r,'Value').set('type','App::PropertyFloat'),
        'side':lambda r:prop(r,'Reversed').find('Bool').set('value','false'),
        'corner-join':lambda r:prop(r,'Join').find('Integer').set('value','0'),
        'mode':lambda r:prop(r,'Mode').find('Integer').set('value','1'),
        'intersection':lambda r:prop(r,'Intersection').find('Bool').set('value','true'),
        'opening-face':lambda r:prop(r,'Base').find('LinkSub/Sub').set('value','Face1'),
        'base-history':lambda r:prop(r,'BaseFeature').find('Link').set('value','N1')}
    results={}
    for name,change in changes.items():
        try:
            xml=ET.fromstring(entries['Document.xml']);before=ET.tostring(xml);change(xml);assert ET.tostring(xml)!=before
            with ZipFile(path,'w') as z:
                for member,data in entries.items():z.writestr(member,ET.tostring(xml) if member=='Document.xml' else data)
            receipt=json.loads(rb);receipt['artifacts'][2]['sha256']=file_digest(path);atomic_json(rp,receipt)
            try:adaptor._verify(target)
            except SchemaxisError as e:
                assert e.fault.code=='VERIFICATION_FAILED' and 'digest' not in e.fault.message.lower();results[name]=e.fault.code
            else:raise AssertionError('refreshed shell forgery accepted: '+name)
        finally:path.write_bytes(original);rp.write_bytes(rb)
    assert registry.verify(target)['verified'];return results


def qualify(directory,executable):
    root=Path(directory).absolute();root.mkdir(parents=True,exist_ok=False);report={'verified':False,'sourceDigest':source_digest('freecad'),'checks':{}}
    enclosure=json.loads((Path(__file__).resolve().parents[1]/'examples/schemaxis/freecad-shell-enclosure.json').read_text())
    for name,document,expected in [*cases(),('enclosure',enclosure,{'volume':10128+60*math.pi,'positions':[[-14,-9],[14,-9],[-14,9],[14,9]],'axis':'Z','voidSample':5,'diameter':2})]:
        target=root/name;registry.run(document,target,locations={'freecad':executable},timeout=120);r=registry.verify(target)
        assert math.isclose(r['volumeMM3'],expected['volume'],rel_tol=1e-8,abs_tol=1e-6),(name,r['volumeMM3'],expected['volume'])
        report['checks'][name]={'verified':True,'expected':expected};atomic_json(root/'qualification.json',report);print(name+' verified',flush=True)
    report['savedAttacks']=attacks(root/'inward-sharp')
    worker=SubprocessRunner(Interpreter('freecad',executable),root,timeout=180)
    for stage in ['neutral','edit1','edit2','reopen']:
        code='import sys\nsys.path.insert(0,'+repr(str(Path(__file__).resolve().parents[1]/'src'))+')\nsys.path.insert(0,'+repr(str(Path(__file__).resolve().parent))+')\nfrom qualify_freecad_shell_native import main\nmain('+repr(str(root))+','+repr(stage)+')\n'
        atomic_json(root/(stage+'-submission.json'),worker(code).to_dict());assert json.loads((root/('independent-neutral.json' if stage=='neutral' else stage+'.json')).read_text())['verified']
    report['nativeEditReopen']=json.loads((root/'reopen.json').read_text())
    # Identical verified input reuses its result; altered intent and corrupted
    # saved history cannot reuse that successful native evidence.
    from schemaxis import workflow
    envelope={'version':'schemaxis.workflow/1','operations':[{'id':'cad','document':enclosure}]};target=root/'workflow';locations={'freecad':executable}
    workflow.execute(envelope,target,locations=locations,timeout=120);workflow.verify(target)
    reused=workflow.execute(envelope,target,locations=locations,timeout=120,resume=True);assert all(j['reused'] for j in reused['jobs'])
    changed=copy.deepcopy(envelope);changed['operations'][0]['document']['parameters']['wall']['value']=2.5
    try:workflow.execute(changed,target,locations=locations,timeout=120,resume=True)
    except SchemaxisError as e:assert e.fault.code=='RESUME_MISMATCH'
    else:raise AssertionError('changed wall intent resumed')
    (Path(reused['jobs'][0]['directory'])/'model.FCStd').write_bytes(b'invalid shell history')
    rebuilt=workflow.execute(envelope,target,locations=locations,timeout=120,resume=True);workflow.verify(target);assert not rebuilt['jobs'][0]['reused']
    report['workflow']={'verifiedReuse':True,'changedIntentRejected':True,'corruptHistoryRebuilt':True}
    invalid=part({'openings':[{'face':'right'}]},circle=True)
    alias=part({'openings':[{'face':'top'},{'face':'top','position':'innermost'}]})
    ambiguous=part();ambiguous['nodes'].pop();ambiguous['nodes'][2]['options']['length']=5
    for number,x in [(1,-8),(2,8)]:
        base='stock' if number==1 else 'boss1'
        ambiguous['nodes'].extend([{'id':'profile'+str(number),'filter':'circle','options':{'radius':3,'centre':[x,0],'onFace':{'face':'top','position':'innermost'}},'inputs':{'body':'body','support':base}},
            {'id':'boss'+str(number),'filter':'pad','options':{'length':3},'inputs':{'body':'body','base':base,'profile':'profile'+str(number)}}])
    ambiguous['nodes'].append({'id':'housing','filter':'shell','options':{'openings':[{'face':'top'}]},'inputs':{'base':'boss2'}})
    report['selectionNegatives']={}
    for name,document,code in [('no-planar-opening',invalid,'EMPTY_SELECTION'),('duplicate-resolved-face',alias,'INVALID_SHELL_OPENINGS'),('ambiguous-opening',ambiguous,'AMBIGUOUS_SELECTION')]:
        try:registry.run(document,root/name,locations=locations,timeout=120)
        except SchemaxisError as e:assert e.fault.code==code,(name,e.fault);report['selectionNegatives'][name]=code
        else:raise AssertionError('invalid opening accepted: '+name)
    assert report['sourceDigest']==source_digest('freecad');report['verified']=True;atomic_json(root/'qualification.json',report);return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory');p.add_argument('--freecad',required=True);a=p.parse_args();qualify(a.directory,a.freecad)
