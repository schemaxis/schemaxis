#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Qualify persistent affine length drivers with native edits and independent oracles."""
import argparse
import copy
import json
import math
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from schemaxis.adaptors import registry
from schemaxis.adaptors.freecad import parameters, adaptor
from schemaxis.adaptor_delivery import source_digest
from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.core.faults import SchemaxisError
from schemaxis.core.runners import Interpreter
from schemaxis.dispatch import SubprocessRunner
from schemaxis import workflow
ROOT=Path(__file__).resolve().parents[1]


def hostile_saved(target):
    plan=json.loads((target/'plan.json').read_text());source=target/'model.FCStd';report={}
    with ZipFile(source) as z:original={n:z.read(n) for n in z.namelist()}
    def modify(name,change):
        root=ET.fromstring(original['Document.xml']);change(root)
        path=target/('hostile-'+name+'.FCStd')
        with ZipFile(path,'w') as z:
            for n,data in original.items():z.writestr(n,ET.tostring(root) if n=='Document.xml' else data)
        try:parameters.verify_saved(plan,path)
        except SchemaxisError as error:assert error.fault.code=='VERIFICATION_FAILED';report[name]=error.fault.code
        else:raise AssertionError('same-value native forgery accepted: '+name)
        # Exercise the production semantic verifier with a refreshed artifact hash;
        # rejection must not depend only on stale content digests.
        receipt_path=target/'verification.json';receipt_bytes=receipt_path.read_bytes();source_bytes=source.read_bytes()
        try:
            source.write_bytes(path.read_bytes());receipt=json.loads(receipt_bytes)
            receipt['artifacts'][2]['sha256']=file_digest(source);atomic_json(receipt_path,receipt)
            try:adaptor._verify(target)
            except SchemaxisError as error:
                assert error.fault.code=='VERIFICATION_FAILED' and 'digest' not in error.fault.message.lower()
            else:raise AssertionError('refreshed-hash native forgery accepted: '+name)
        finally:source.write_bytes(source_bytes);receipt_path.write_bytes(receipt_bytes)
    engine=lambda r:r.find("./ObjectData/Object[@name='N0']/Properties/Property[@name='ExpressionEngine']/ExpressionEngine")
    modify('missing-expression',lambda r:engine(r).remove(engine(r).find('Expression')))
    modify('wrong-expression-same-value',lambda r:engine(r).find('Expression').set('expression','0.5 * SchemaxisParameters.dim_thickness + 2.5 mm'))
    modify('extra-expression',lambda r:ET.SubElement(engine(r),'Expression',{'path':'Width','expression':'50 mm'}))
    modify('unknown-object',lambda r:ET.SubElement(r.find('Objects'),'Object',{'name':'OtherParameters','type':'App::VarSet'}))
    props=lambda r:r.find("./ObjectData/Object[@name='SchemaxisParameters']/Properties")
    modify('unknown-property',lambda r:ET.SubElement(props(r),'Property',{'name':'dim_unknown','type':'App::PropertyLength'}))
    modify('wrong-unit-type',lambda r:props(r).find("Property[@name='dim_thickness']").set('type','App::PropertyFloat'))
    modify('clamped-driver',lambda r:props(r).find("Property[@name='dim_thickness']/Float").set('value','0'))
    modify('duplicate-driver-value',lambda r:ET.SubElement(props(r).find("Property[@name='dim_thickness']"),'Float',{'value':'5'}))
    modify('duplicate-engine',lambda r:ET.SubElement(r.find("./ObjectData/Object[@name='N0']/Properties/Property[@name='ExpressionEngine']"),'ExpressionEngine',{'count':'0'}))
    modify('malformed-visibility',lambda r:props(r).find("Property[@name='Visibility']/Bool").set('value','nonsense'))
    return report


def independent(target, executable):
    runner=SubprocessRunner(Interpreter('freecad',executable),target,timeout=90)
    worker=ROOT/'tools/qualify_freecad_parameters_native.py'
    for mode in (('edit','reopen','hostile') if json.loads((target/'plan.json').read_text())['output']=='plate' else ('edit','reopen')):
        source='import sys\nsys.path.insert(0,'+repr(str(worker.parent))+')\nfrom qualify_freecad_parameters_native import main\nmain('+repr(str(target))+','+repr(mode)+')\n'
        submitted=runner(source);atomic_json(target/('independent-'+mode+'-submission.json'),submitted.to_dict())
        assert (target/('independent-'+mode+'.json')).is_file(),'native script must produce structured evidence'
    edit=json.loads((target/'independent-edit.json').read_text());reopen=json.loads((target/'independent-reopen.json').read_text())
    assert edit['pid']!=reopen['pid'] and edit['edited']==reopen['edited'] and edit['expressions']==reopen['expressions']
    if (target/'independent-hostile.json').exists():edit['nativeRejections']=json.loads((target/'independent-hostile.json').read_text())
    return edit


def qualify(directory, executable):
    directory=Path(directory).absolute();directory.mkdir(parents=True,exist_ok=False)
    locations={'freecad':executable};report={'verified':False,'sourceDigest':source_digest('freecad'),'checks':{}}
    def read(name):return json.loads((ROOT/'examples/schemaxis'/name).read_text())
    def run(name,document):
        target=directory/name;registry.run(document,target,locations=locations,timeout=90)
        report['checks'][name]=registry.verify(target);print(name+' verified',flush=True);return target
    try:
        baseline=run('plate',read('freecad-parameters.json'))
        report['checks']['plate-native-edit']=independent(baseline,executable)
        report['checks']['same-value-hostile']=hostile_saved(baseline)
        extrude=run('extrude',read('freecad-parameters-extrude.json'))
        report['checks']['extrude-native-edit']=independent(extrude,executable)
        long_name='thickness_'+('x'*54);assert len(long_name)==64
        multi={'version':'schemaxis.freecad/1','parameters':{
            long_name:{'kind':'length','value':5,'minimum':2,'maximum':10},
            'gap':{'kind':'length','value':3,'minimum':1,'maximum':4}},
            'nodes':[{'id':'body','filter':'box','options':{'width':10},'drive':{
                'length':{'terms':{long_name:1,'gap':2},'offset':1},
                'height':{'terms':{long_name:-.1,'gap':.2},'offset':10}}}], 'output':'body'}
        target=run('multi-driver',multi);report['checks']['multi-driver-native-edit']=independent(target,executable)
        precision=copy.deepcopy(multi)
        precision['parameters'][long_name].update(value=.12345678901234568,minimum=.10000000000000003,maximum=.9999999999999999)
        precision['nodes'][0]['drive']['length']={'terms':{long_name:1.2345678901234567e-3,'gap':-2.345678901234567e-2},'offset':10.123456789012346}
        target=run('precision',precision);report['checks']['precision-native-edit']=independent(target,executable)
        variants=run('variants',read('freecad-parameters-variant.json'))
        for index,h in enumerate((5,8)):
            receipt=json.loads((variants/('state-%05d'%index)/'verification.json').read_text())
            assert math.isclose(receipt['native']['volume'],(4000-9*math.pi)*h,rel_tol=1e-10)
        envelope=read('freecad-parameters-workflow.json');target=directory/'workflow'
        workflow.execute(envelope,target,locations=locations,timeout=90);workflow.verify(target)
        reused=workflow.execute(envelope,target,locations=locations,timeout=90,resume=True)
        assert all(j['reused'] for j in reused['jobs'])
        changed=copy.deepcopy(envelope);changed['operations'][0]['document']['parameters']['thickness']['value']=8
        try:workflow.execute(changed,target,locations=locations,timeout=90,resume=True)
        except SchemaxisError as error:assert error.fault.code=='RESUME_MISMATCH'
        else:raise AssertionError('changed authored workflow resumed')
        cad=Path(next(j['directory'] for j in reused['jobs'] if j['operation']=='cad'))
        (cad/'model.FCStd').write_bytes(b'invalid native parameter document')
        updated=workflow.execute(envelope,target,locations=locations,timeout=90,resume=True);workflow.verify(target)
        reuse={j['operation']:j['reused'] for j in updated['jobs']}
        assert reuse=={'cad':False,'consumer':False,'independent':True},reuse
        fresh=workflow.execute(changed,directory/'changed-workflow',locations=locations,timeout=90);workflow.verify(directory/'changed-workflow')
        assert all(not j['reused'] for j in fresh['jobs'])
        report['checks']['workflow']={'initialReused':len(reused['jobs']),'afterInvalidNativeEvidence':reuse,'changedInput':'requires fresh run'}
        for name in ('freecad-bracket.json','freecad-semantic-fillet.json','freecad-measurements.json'):
            run('regression-'+name.removesuffix('.json'),read(name))
        assert report['sourceDigest']==source_digest('freecad'),'source changed during qualification'
        report['verified']=True
    finally:atomic_json(directory/'report.json',report)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',required=True);p.add_argument('--executable',required=True);args=p.parse_args()
    print(json.dumps(qualify(args.directory,args.executable),indent=2))
