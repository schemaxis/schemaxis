#!/usr/bin/env python3
"""Typed sweep/path acceptance: independent geometry, edits and hostile histories."""
import argparse,copy,json,math
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from schemaxis.adaptors import registry
from schemaxis.adaptors.freecad import adaptor
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.adaptor_delivery import source_digest
from schemaxis.core.faults import SchemaxisError
from schemaxis.core.runners import Interpreter
from schemaxis.dispatch import SubprocessRunner
from freecad_sweep_cases import cases,elbow,flanged,straight


def hostile(target,kind='sweep'):
    path=target/'model.FCStd';original=path.read_bytes();rp=target/'verification.json';rb=rp.read_bytes()
    with ZipFile(path) as z:entries={n:z.read(n) for n in z.namelist()}
    plan=json.loads((target/'plan.json').read_text());names={n['id']:'N'+str(i) for i,n in enumerate(plan['nodes'])}
    def prop(r,identity,key):return r.find("./ObjectData/Object[@name='%s']/Properties/Property[@name='%s']"%(names[identity],key))
    def change(identity,key,tag,value):return lambda r:prop(r,identity,key).find(tag).set('value',str(value))
    if kind=='sweep':
        changes={'mode':change('stock','Mode','Integer',1),'transition':change('stock','Transition','Integer',1),
            'transformation':change('stock','Transformation','Integer',2),'spine-tangent':change('stock','SpineTangent','Bool','true'),
            'auxiliary-tangent':change('stock','AuxiliarySpineTangent','Bool','true'),'auxiliary-equivalence':change('stock','AuxiliaryCurvilinear','Bool','false'),
            'midplane':change('stock','Midplane','Bool','true'),'reversed':change('stock','Reversed','Bool','true'),
            'binormal':lambda r:prop(r,'stock','Binormal').find('PropertyVector').set('valueX','1'),
            'property-type':lambda r:prop(r,'stock','Mode').set('type','App::PropertyInteger'),
            'profile':lambda r:prop(r,'stock','Profile').find('LinkSub').set('value',names['inner']),
            'spine':lambda r:prop(r,'stock','Spine').find('LinkSub').set('value',names['inner']),
            'construction':lambda r:prop(r,'bend','Geometry').find('GeometryList')[0].find('Construction').set('value','0'),
            'bend-radius':lambda r:next(c for c in prop(r,'bend','Constraints').find('ConstraintList') if c.get('Name')=='bendRadius').set('Value','11'),
            'bend-angle':lambda r:next(c for c in prop(r,'bend','Constraints').find('ConstraintList') if c.get('Name')=='sweep').set('Value','1'),
            'native-arc':lambda r:prop(r,'bend','Geometry').find('GeometryList')[2].find('ArcOfCircle').set('Radius','11')}
    elif kind=='centroid':
        changes={'centroid-mode-downgrade':change('outletProfile','MapMode','Integer',5),
            'centroid-engine-downgrade':change('outletProfile','AttacherType','String','Attacher::AttachEnginePlane'),
            'centroid-offset':lambda r:prop(r,'outletProfile','AttachmentOffset').find('PropertyPlacement').set('Pz','1'),
            'centroid-support':lambda r:prop(r,'outletProfile','AttachmentSupport').find('LinkSubList/Link').set('obj',names['stock'])}
    elif kind=='sections':changes={'section-link':lambda r:prop(r,'finished','Sections').find('LinkSubList/Link').set('obj',names['profile'])}
    elif kind=='auxiliary':changes={'auxiliary-link':lambda r:prop(r,'stock','AuxiliarySpine').find('LinkSub').set('value',names['bend']),
        'guide-correspondence':change('stock','AuxiliaryCurvilinear','Bool','false')}
    else:raise ValueError(kind)
    report={}
    for name,mutate in changes.items():
        try:
            xml=ET.fromstring(entries['Document.xml']);before=ET.tostring(xml);mutate(xml);assert ET.tostring(xml)!=before,name
            with ZipFile(path,'w') as z:
                for member,data in entries.items():z.writestr(member,ET.tostring(xml) if member=='Document.xml' else data)
            receipt=json.loads(rb);receipt['artifacts'][2]['sha256']=file_digest(path);atomic_json(rp,receipt)
            try:adaptor._verify(target)
            except SchemaxisError as e:
                assert e.fault.code=='VERIFICATION_FAILED' and 'digest' not in e.fault.message.lower(),e.fault;report[name]=e.fault.code
            else:raise AssertionError('refreshed sweep forgery accepted: '+name)
        finally:path.write_bytes(original);rp.write_bytes(rb)
    assert registry.verify(target)['verified'];return report


def qualify(directory,executable):
    root=Path(directory).absolute();root.mkdir(parents=True,exist_ok=False);report={'verified':False,'sourceDigest':source_digest('freecad'),'checks':{}}
    locations={'freecad':executable}
    for name,d,e in cases():
        registry.run(d,root/name,locations=locations,timeout=120);r=registry.verify(root/name)
        assert math.isclose(r['volumeMM3'],e['volume'],rel_tol=1e-8,abs_tol=1e-6),(name,r['volumeMM3'],e['volume'])
        report['checks'][name]={'verified':True,'expected':e};atomic_json(root/'qualification.json',report);print(name+' verified',flush=True)
    report['savedAttacks']={kind:hostile(root/name,kind) for name,kind in [('hollow-normal','sweep'),('flanged-elbow','centroid'),('multisection','sections'),('auxiliary-true','auxiliary')]}
    worker=SubprocessRunner(Interpreter('freecad',executable),root,timeout=180)
    for stage in ['neutral','edit1','edit2','reopen']:
        code='import sys,traceback\nsys.path.insert(0,'+repr(str(Path(__file__).resolve().parents[1]/'src'))+')\nsys.path.insert(0,'+repr(str(Path(__file__).resolve().parent))+')\nfrom qualify_freecad_sweep_native import main\ntry:\n main('+repr(str(root))+','+repr(stage)+')\nexcept BaseException as e:\n traceback.print_exc();print(getattr(e,"fault",None));raise\n'
        atomic_json(root/(stage+'-submission.json'),worker(code).to_dict());assert json.loads((root/('independent-neutral.json' if stage=='neutral' else stage+'.json')).read_text())['verified'];print(stage+' verified',flush=True)
    report['nativeEditReopen']=json.loads((root/'reopen.json').read_text())
    from schemaxis import workflow
    envelope={'version':'schemaxis.workflow/1','operations':[{'id':'cad','document':flanged()}]};target=root/'workflow'
    workflow.execute(envelope,target,locations=locations,timeout=120);workflow.verify(target)
    reused=workflow.execute(envelope,target,locations=locations,timeout=120,resume=True);assert all(j['reused'] for j in reused['jobs'])
    changed=copy.deepcopy(envelope);changed['operations'][0]['document']['parameters']['bendRadius']['value']=11
    try:workflow.execute(changed,target,locations=locations,timeout=120,resume=True)
    except SchemaxisError as e:assert e.fault.code=='RESUME_MISMATCH'
    else:raise AssertionError('changed bend intent resumed')
    (Path(reused['jobs'][0]['directory'])/'model.FCStd').write_bytes(b'invalid sweep history')
    rebuilt=workflow.execute(envelope,target,locations=locations,timeout=120,resume=True);workflow.verify(target);assert not rebuilt['jobs'][0]['reused']
    report['workflow']={'verifiedReuse':True,'changedIntentRejected':True,'corruptHistoryRebuilt':True}
    disconnected=straight();disconnected['nodes'][2]['options']['geometry'].append({'id':'island','kind':'line','start':[30,30],'end':[40,40]})
    open_section=straight();open_section['nodes'][1].update(filter='sketch',options={'geometry':[{'id':'open','kind':'line','start':[-2,0],'end':[2,0]}]})
    kink=straight();kink['nodes'][2]['options']['geometry'].append({'id':'corner','kind':'line','start':[0,20],'end':[20,20]})
    rounded=copy.deepcopy(kink);rounded['nodes'][-1]['options']={'transition':'rounded'}
    no_removal=straight(subtractive=True);no_removal['nodes'][1]['options']['origin']=[50,0,0]
    report['nativeNegatives']={}
    for name,d,code in [('disconnected-path',disconnected,'INVALID_SWEEP_PATH'),('open-section',open_section,'INVALID_SWEEP_SECTION'),('transformed-corner',kink,'INVALID_SWEEP_TRANSITION'),('rounded-corner-export-loss',rounded,'VERIFICATION_FAILED'),('missed-removal',no_removal,'INVALID_GEOMETRY')]:
        try:registry.run(d,root/name,locations=locations,timeout=120)
        except SchemaxisError as e:assert e.fault.code==code,(name,e.fault);report['nativeNegatives'][name]=code
        else:raise AssertionError('invalid sweep admitted: '+name)
    assert report['sourceDigest']==source_digest('freecad');report['verified']=True;atomic_json(root/'qualification.json',report);return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory');p.add_argument('--freecad',required=True);a=p.parse_args();qualify(a.directory,a.freecad)
