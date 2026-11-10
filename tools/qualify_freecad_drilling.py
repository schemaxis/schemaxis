#!/usr/bin/env python3
"""Native drilling family qualification with independent mechanical oracles."""
import argparse
import json
import math
import copy
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from schemaxis.adaptors import registry
from schemaxis.adaptors.freecad import adaptor
from schemaxis.adaptor_delivery import source_digest
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.core.faults import SchemaxisError
from freecad_drilling_cases import cases,driven_grid,expected_volume


def hostile(target,layout='grid'):
    """Changed native semantics must fail even after publication digest refresh."""
    path=target/'model.FCStd';original=path.read_bytes();rp=target/'verification.json';rb=rp.read_bytes()
    with ZipFile(path) as z:entries={n:z.read(n) for n in z.namelist()}
    plan=json.loads((target/'plan.json').read_text());names={n['id']:'N'+str(i) for i,n in enumerate(plan['nodes'])}
    def prop(r,identity,key):return r.find("./ObjectData/Object[@name='%s']/Properties/Property[@name='%s']"%(names[identity],key))
    def change_value(identity,key,tag,value):return lambda r:prop(r,identity,key).find(tag).set('value',str(value))
    changes={
        'diameter':change_value('holes','Diameter','Float',4),
        'extent':change_value('holes','DepthType','Integer',0),
        'reverse':change_value('holes','Reversed','Bool','true'),
        'tip':change_value('holes','DrillPoint','Integer',1),
        'threaded':change_value('holes','Threaded','Bool','true'),
        'model-thread':change_value('holes','ModelThread','Bool','true'),
        'tapered':change_value('holes','Tapered','Bool','true'),
        'custom-recess':change_value('holes','HoleCutCustomValues','Bool','false'),
        'profile-link':lambda r:prop(r,'holes','Profile').find('LinkSub').set('value',names['outline']),
        'construction-location':lambda r:prop(r,'locations','Geometry').find('GeometryList')[2].find('Construction').set('value','1')}
    constraint='xPitch' if layout=='grid' else 'phase'
    changes['layout-dimension']=lambda r:next(c for c in prop(r,'locations','Constraints').find('ConstraintList') if c.get('Name')==constraint).set('Value','3')
    changes['layout-expression']=lambda r:prop(r,'locations','ExpressionEngine').find('ExpressionEngine/Expression').set('expression','0 mm')
    if layout=='grid':
        changes.update({'recess-type':change_value('holes','HoleCutType','Integer',0),
            'recess-diameter':change_value('holes','HoleCutDiameter','Float',7),
            'recess-depth':change_value('holes','HoleCutDepth','Float',3)})
    report={}
    for name,change in changes.items():
        try:
            xml=ET.fromstring(entries['Document.xml']);before=ET.tostring(xml);change(xml);assert ET.tostring(xml)!=before,name
            with ZipFile(path,'w') as z:
                for member,data in entries.items():z.writestr(member,ET.tostring(xml) if member=='Document.xml' else data)
            receipt=json.loads(rb);receipt['artifacts'][2]['sha256']=file_digest(path);atomic_json(rp,receipt)
            try:adaptor._verify(target)
            except SchemaxisError as error:
                assert error.fault.code=='VERIFICATION_FAILED' and 'digest' not in error.fault.message.lower(),error
                report[name]=error.fault.code
            else:raise AssertionError('refreshed native drilling forgery accepted: '+name)
        finally:path.write_bytes(original);rp.write_bytes(rb)
    assert registry.verify(target)['verified'];return report


def qualify(directory,executable):
    directory=Path(directory).absolute();directory.mkdir(parents=True,exist_ok=False)
    report={'verified':False,'sourceDigest':source_digest('freecad'),'checks':{}}
    enclosure=json.loads((Path(__file__).resolve().parents[1]/'examples/schemaxis/freecad-drilled-enclosure.json').read_text())
    for name,document,expected in [*cases(),('driven-grid',driven_grid(),{'volume':expected_volume(4,3,recess_diameter=6,recess_depth=2),'positions':[[-8,-7],[8,-7],[-8,7],[8,7]],'axis':'Z','voidSample':5,'diameter':3}),
        ('enclosure',enclosure,{'volume':10128+60*math.pi,'positions':[[-14,-9],[14,-9],[-14,9],[14,9]],'axis':'Z','voidSample':5,'diameter':2})]:
        target=directory/name;registry.run(document,target,locations={'freecad':executable},timeout=120);result=registry.verify(target)
        assert math.isclose(result['volumeMM3'],expected['volume'],rel_tol=1e-8,abs_tol=1e-6),(name,result['volumeMM3'],expected)
        report['checks'][name]={'verified':True,'volumeMM3':result['volumeMM3'],'expected':expected}
        atomic_json(directory/'qualification.json',report);print(name+' verified',flush=True)
    report['savedAttacks']={'grid':hostile(directory/'driven-grid'),'circle':hostile(directory/'bolt-circle-6','circle')}
    from schemaxis import workflow
    envelope={'version':'schemaxis.workflow/1','operations':[{'id':'cad','document':driven_grid()}]}
    target=directory/'workflow';workflow.execute(envelope,target,locations={'freecad':executable},timeout=120);workflow.verify(target)
    reused=workflow.execute(envelope,target,locations={'freecad':executable},timeout=120,resume=True);assert all(j['reused'] for j in reused['jobs'])
    changed=copy.deepcopy(envelope);changed['operations'][0]['document']['parameters']['drill']['value']=3.5
    try:workflow.execute(changed,target,locations={'freecad':executable},timeout=120,resume=True)
    except SchemaxisError as error:assert error.fault.code=='RESUME_MISMATCH'
    else:raise AssertionError('changed drilling intent resumed')
    cad=Path(reused['jobs'][0]['directory']);(cad/'model.FCStd').write_bytes(b'invalid native drilling history')
    rebuilt=workflow.execute(envelope,target,locations={'freecad':executable},timeout=120,resume=True);workflow.verify(target);assert not rebuilt['jobs'][0]['reused']
    report['workflow']={'verifiedReuse':True,'changedIntentRejected':True,'invalidSavedHistoryRebuilt':True}
    invalid=driven_grid();invalid.pop('parameters');invalid['nodes'][-2].pop('drive');invalid['nodes'][-2]['options'].update(xPitch=100,yPitch=100);invalid['nodes'][-1].pop('drive');invalid['nodes'][-1]['options'].update(diameter=3,recessDepth=2)
    try:registry.run(invalid,directory/'missed-material',locations={'freecad':executable},timeout=120)
    except SchemaxisError as error:report['missedMaterialRejected']=error.fault.code
    else:raise AssertionError('drilling locations outside stock accepted')
    from schemaxis.core.runners import Interpreter
    from schemaxis.dispatch import SubprocessRunner
    worker=SubprocessRunner(Interpreter('freecad',executable),directory,timeout=180)
    code='import sys\nsys.path.insert(0,'+repr(str(Path(__file__).resolve().parents[1]/'src'))+')\nsys.path.insert(0,'+repr(str(Path(__file__).resolve().parent))+')\nfrom qualify_freecad_drilling_native import main\nmain('+repr(str(directory))+')\n'
    atomic_json(directory/'independent-submission.json',worker(code).to_dict())
    independent=json.loads((directory/'independent-neutral.json').read_text());assert independent['verified'];report['independentGeometry']=independent
    for stage in ('edit1','edit2','reopen'):
        code='import sys\nsys.path.insert(0,'+repr(str(Path(__file__).resolve().parents[1]/'src'))+')\nsys.path.insert(0,'+repr(str(Path(__file__).resolve().parent))+')\nfrom qualify_freecad_drilling_native import main\nmain('+repr(str(directory))+','+repr(stage)+')\n'
        atomic_json(directory/(stage+'-submission.json'),worker(code).to_dict())
        path=directory/('native-reopened.json' if stage=='reopen' else 'native-'+stage+'/edited.json');assert json.loads(path.read_text())['verified']
    report['nativeEditReopen']=json.loads((directory/'native-reopened.json').read_text())
    assert report['sourceDigest']==source_digest('freecad'),'provider changed during qualification'
    report['verified']=True;atomic_json(directory/'qualification.json',report);return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory');p.add_argument('--freecad',required=True);a=p.parse_args();qualify(a.directory,a.freecad)
