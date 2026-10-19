#!/usr/bin/env python3
"""Qualify inspectable mechanical-part history, native edits and semantic negatives."""
import argparse
import copy
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from schemaxis.adaptors import registry
from schemaxis.adaptors.freecad import adaptor
from schemaxis.adaptor_delivery import source_digest
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.core.faults import SchemaxisError
from schemaxis.core.runners import Interpreter
from schemaxis.dispatch import SubprocessRunner
ROOT=Path(__file__).resolve().parents[1]


def independent(target,executable):
    runner=SubprocessRunner(Interpreter('freecad',executable),target,timeout=90)
    for mode in ('edit','reopen'):
        script='import sys\nsys.path.insert(0,'+repr(str(target/'runtime.zip'))+')\nsys.path.insert(0,'+repr(str(ROOT/'tools'))+')\nfrom qualify_freecad_part_design_native import main\nmain('+repr(str(target))+','+repr(mode)+')\n'
        atomic_json(target/('independent-'+mode+'-submission.json'),runner(script).to_dict())
        assert (target/('independent-'+mode+'.json')).is_file(),'native worker did not produce success evidence'
    first=json.loads((target/'independent-edit.json').read_text());second=json.loads((target/'independent-reopen.json').read_text())
    assert first['verified'] and second['verified'] and first['pid']!=second['pid']
    assert first['edited']==second['edited'] and first['expressions']==second['expressions']
    return first


def hostile(target):
    path=target/'model.FCStd';original=path.read_bytes();receipt_path=target/'verification.json';receipt_bytes=receipt_path.read_bytes()
    with ZipFile(path) as z:entries={n:z.read(n) for n in z.namelist()}
    report={}
    def prop(root,name,key):return root.find("./ObjectData/Object[@name='%s']/Properties/Property[@name='%s']"%(name,key))
    changes={
        'throughAll-to-same-shape-length':lambda r:prop(r,'N4','Type').find('Integer').set('value','0'),
        'wrong-direction':lambda r:prop(r,'N4','Reversed').find('Bool').set('value','false'),
        'translated-body':lambda r:prop(r,'N0','Placement').find('PropertyPlacement').set('Px','10'),
        'wrong-tip':lambda r:prop(r,'N0','Tip').find('Link').set('value','N2'),
        'wrong-profile':lambda r:prop(r,'N4','Profile').find('LinkSub').set('value','N1'),
        'wrong-base':lambda r:prop(r,'N4','BaseFeature').find('Link').set('value','N0'),
        'wrong-support':lambda r:prop(r,'N3','AttachmentSupport').find('LinkSubList/Link').set('obj','XZ_Plane'),
        'missing-group-member':lambda r:prop(r,'N0','Group').find('LinkList').remove(prop(r,'N0','Group').find('LinkList/Link')),
        'duplicate-origin-role':lambda r:prop(r,'XZ_Plane','Role').find('String').set('value','XY_Plane'),
        'unknown-helper':lambda r:ET.SubElement(r.find('Objects'),'Object',{'name':'Extra','type':'App::Plane'}),
        'extra-pocket-expression':lambda r:ET.SubElement(prop(r,'N4','ExpressionEngine').find('ExpressionEngine'),'Expression',{'path':'Length','expression':'5 mm'}),
        'wrong-unbound-centre':lambda r:prop(r,'N3','Constraints').find("ConstraintList/Constrain[@Name='centreX']").set('Value','16'),
        'wrong-constraint-type':lambda r:prop(r,'N3','Constraints').find("ConstraintList/Constrain[@Name='centreX']").set('Type','8'),
        'wrong-constraint-name':lambda r:prop(r,'N3','Constraints').find("ConstraintList/Constrain[@Name='centreX']").set('Name','centreOther'),
        'wrong-constraint-endpoint':lambda r:prop(r,'N3','Constraints').find("ConstraintList/Constrain[@Name='centreX']").set('FirstPos','1'),
        'inactive-driven-radius':lambda r:prop(r,'N3','Constraints').find("ConstraintList/Constrain[@Name='radius']").set('IsActive','0')}
    for label,change in changes.items():
        try:
            root=ET.fromstring(entries['Document.xml']);change(root)
            with ZipFile(path,'w') as z:
                for name,data in entries.items():z.writestr(name,ET.tostring(root) if name=='Document.xml' else data)
            receipt=json.loads(receipt_bytes);receipt['artifacts'][2]['sha256']=file_digest(path);atomic_json(receipt_path,receipt)
            try:adaptor._verify(target)
            except SchemaxisError as error:
                assert error.fault.code=='VERIFICATION_FAILED' and 'digest' not in error.fault.message.lower()
                report[label]=error.fault.code
            else:raise AssertionError('saved native history forgery accepted: '+label)
        finally:path.write_bytes(original);receipt_path.write_bytes(receipt_bytes)
    assert registry.verify(target)['verified'];return report


def hostile_gui(target):
    path=target/'model.FCStd';original=path.read_bytes();receipt_path=target/'verification.json';receipt_bytes=receipt_path.read_bytes()
    with ZipFile(path) as z:entries={n:z.read(n) for n in z.namelist()}
    report={}
    for label in ('missing','duplicate-file','hidden-tip','missing-member','duplicate-member','wrong-type','duplicate-bool','malformed-bool'):
        try:
            root=ET.fromstring(entries['GuiDocument.xml']);data=root.find('ViewProviderData')
            tip=data.find("ViewProvider[@name='N4']");prop=tip.find('Properties/Property')
            if label=='hidden-tip':prop.find('Bool').set('value','false')
            elif label=='missing-member':data.remove(tip)
            elif label=='duplicate-member':data.append(copy.deepcopy(tip))
            elif label=='wrong-type':prop.set('type','App::PropertyString')
            elif label=='duplicate-bool':prop.append(copy.deepcopy(prop[0]))
            elif label=='malformed-bool':prop[0].set('value','1')
            with ZipFile(path,'w') as z:
                for name,entry in entries.items():
                    if name!='GuiDocument.xml':z.writestr(name,entry)
                if label!='missing':z.writestr('GuiDocument.xml',ET.tostring(root))
                if label=='duplicate-file':z.writestr('GuiDocument.xml',ET.tostring(root))
            receipt=json.loads(receipt_bytes);receipt['artifacts'][2]['sha256']=file_digest(path);atomic_json(receipt_path,receipt)
            try:adaptor._verify(target)
            except SchemaxisError as error:
                assert error.fault.code=='VERIFICATION_FAILED' and 'digest' not in error.fault.message.lower()
                report[label]=error.fault.code
            else:raise AssertionError('saved GUI state forgery accepted: '+label)
        finally:path.write_bytes(original);receipt_path.write_bytes(receipt_bytes)
    assert registry.verify(target)['verified'];return report


def corrupt_literal(target):
    path=target/'model.FCStd';original=path.read_bytes()
    receipt_path=target/'verification.json';receipt_bytes=receipt_path.read_bytes();report={}
    for label,data in [('invalid-zip',b'not an FCStd archive'),('truncated-zip',original[:len(original)//2])]:
        try:
            path.write_bytes(data);receipt=json.loads(receipt_bytes)
            receipt['artifacts'][2]['sha256']=file_digest(path);atomic_json(receipt_path,receipt)
            try:adaptor._verify(target)
            except SchemaxisError as error:
                assert error.fault.code=='VERIFICATION_FAILED' and 'digest' not in error.fault.message.lower()
                report[label]=error.fault.code
            else:raise AssertionError('corrupt literal Body accepted')
        finally:path.write_bytes(original);receipt_path.write_bytes(receipt_bytes)
    assert registry.verify(target)['verified'];return report


def qualify(directory,executable):
    directory=Path(directory).absolute();directory.mkdir(parents=True,exist_ok=False)
    doc=json.loads((ROOT/'examples/schemaxis/freecad-part-design.json').read_text())
    locations={'freecad':executable};report={'verified':False,'sourceDigest':source_digest('freecad'),'checks':{}}
    def run(name,d):
        target=directory/name;registry.run(d,target,locations=locations,timeout=90)
        report['checks'][name]=registry.verify(target);print(name+' verified',flush=True);return target
    try:
        target=run('mechanical-part',doc);report['checks']['independent']=independent(target,executable)
        report['checks']['hostile']=hostile(target);report['checks']['hostile-gui']=hostile_gui(target)
        from schemaxis.adaptors.freecad.inspection import inspect
        for node,volume in [('slab',20000),('finished',(4000-9*3.141592653589793)*5)]:
            inspection=inspect(doc,node,directory/('inspect-'+node),executable=executable,timeout=90)
            assert abs(inspection['shape']['volume']-volume)<1e-6
            assert inspection['verified'] and inspection['edges'] and inspection['faces']
            report['checks']['inspect-'+node]={'verified':True,'volume':inspection['shape']['volume']}
        for shape,option,value in [('rectangle','width',20),('circle','radius',4)]:
            unowned={'version':'schemaxis.freecad/1','parameters':{'size':{'kind':'length','value':value,'minimum':2,'maximum':30}},
                     'nodes':[{'id':'sketch','filter':shape,'options':{'height':10} if shape=='rectangle' else {},'drive':{option:{'terms':{'size':1}}}},
                              {'id':'solid','filter':'extrude','inputs':{'profile':'sketch'},'options':{'length':5}}], 'output':'solid'}
            unowned_target=run('unowned-driven-'+shape,unowned)
            observed=json.loads((unowned_target/'verification.json').read_text())['native']['volume']
            expected=20*10*5 if shape=='rectangle' else 3.141592653589793*16*5
            assert abs(observed-expected)<1e-6
        empty={'version':'schemaxis.freecad/1','nodes':[{'id':'part','filter':'body'},{'id':'stock','filter':'box'}],'output':'stock'}
        target=run('empty-body',empty)
        obs=json.loads((target/'verification.json').read_text())['partDesignObservations']
        assert obs['body']['tip'] is None and len(obs['auxiliaries'])==8 and obs['visibility']['N1'] and not obs['visibility']['N0']
        unused=copy.deepcopy(doc);unused['nodes'].append({'id':'unused','filter':'circle','inputs':{'body':'part'},'options':{'centre':[-10,0]}})
        target=run('unused-profile',unused)
        obs=json.loads((target/'verification.json').read_text())['partDesignObservations']
        assert obs['body']['tip']=='N4' and obs['body']['group'][-1]=='N5' and not obs['visibility']['N5']
        plain=copy.deepcopy(doc);plain.pop('parameters')
        for node in plain['nodes']:
            if node['id']=='outline':node['options']['width']=80
            if node['id']=='slab':node['options']={'length':5}
            if node['id']=='bore':node['options']['radius']=3
            node.pop('drive',None)
        target=run('literal-body',plain);report['checks']['corrupt-literal-body']=corrupt_literal(target)
        variant=copy.deepcopy(doc);variant['parameters']['thickness']['value']={'$analytic':{'type':'values','values':[5,20]}}
        run('finite-variants',variant)
        precision=copy.deepcopy(doc);precision['parameters']['thickness']['value']=5.123456789012345
        precision['nodes'][2]['drive']['length']={'terms':{'thickness':.12345678901234567},'offset':2.1234567890123457}
        run('precision-pad',precision)
        assert report['sourceDigest']==source_digest('freecad'),'source changed during native qualification'
        report['verified']=True
    finally:atomic_json(directory/'report.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',required=True);parser.add_argument('--executable',required=True);args=parser.parse_args()
    print(json.dumps(qualify(args.directory,args.executable),indent=2))
