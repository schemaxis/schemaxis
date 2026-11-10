#!/usr/bin/env python3
"""Bounded finite-depth/through-all machining qualification, independent of the producer."""
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
from schemaxis import workflow
ROOT=Path(__file__).resolve().parents[1]


def hostile(target):
    path=target/'model.FCStd';original=path.read_bytes();receipt_path=target/'verification.json';receipt_bytes=receipt_path.read_bytes()
    with ZipFile(path) as archive:entries={n:archive.read(n) for n in archive.namelist()}
    def prop(root,name,key):return root.find("./ObjectData/Object[@name='%s']/Properties/Property[@name='%s']"%(name,key))
    changes={
        'finite-to-throughAll':lambda r:prop(r,'N6','Type').find('Integer').set('value','1'),
        'wrong-depth':lambda r:prop(r,'N6','Length').find('Float').set('value','5'),
        'wrong-direction':lambda r:prop(r,'N6','Reversed').find('Bool').set('value','false'),
        'wrong-expression':lambda r:prop(r,'N6','ExpressionEngine').find('ExpressionEngine/Expression').set('expression','2 * SchemaxisParameters.dim_counterboreDepth + 0 mm'),
        'wrong-depth-type':lambda r:prop(r,'N6','Length').set('type','App::PropertyDistance'),
        'wrong-base':lambda r:prop(r,'N6','BaseFeature').find('Link').set('value','N2')}
    report={}
    for name,change in changes.items():
        if name=='wrong-expression' and prop(ET.fromstring(entries['Document.xml']),'N6','ExpressionEngine').find('ExpressionEngine/Expression') is None:continue
        try:
            root=ET.fromstring(entries['Document.xml']);change(root)
            with ZipFile(path,'w') as archive:
                for member,data in entries.items():archive.writestr(member,ET.tostring(root) if member=='Document.xml' else data)
            receipt=json.loads(receipt_bytes);receipt['artifacts'][2]['sha256']=file_digest(path);atomic_json(receipt_path,receipt)
            try:adaptor._verify(target)
            except SchemaxisError as error:
                assert error.fault.code=='VERIFICATION_FAILED' and 'digest' not in error.fault.message.lower();report[name]=error.fault.code
            else:raise AssertionError('saved finite-depth history forgery accepted: '+name)
        finally:path.write_bytes(original);receipt_path.write_bytes(receipt_bytes)
    assert registry.verify(target)['verified'];return report


def qualify(directory,executable):
    directory=Path(directory).absolute();directory.mkdir(parents=True,exist_ok=False)
    report={'verified':False,'sourceDigest':source_digest('freecad'),'checks':{}}
    base=json.loads((ROOT/'examples/schemaxis/freecad-counterbore.json').read_text())
    cases={name:json.loads((ROOT/('examples/schemaxis/'+file)).read_text()) for name,file in [('counterbore','freecad-counterbore.json'),('variant','freecad-counterbore-variant.json'),('blind','freecad-blind-pocket.json')]}
    beyond=copy.deepcopy(base);beyond['parameters']['counterboreDepth'].update(value=30,maximum=40);cases['length-through-stock']=beyond
    literal=copy.deepcopy(base)
    for node in literal['nodes']:
        for option,binding in node.pop('drive',{}).items():node.setdefault('options',{})[option]=base['parameters'][next(iter(binding['terms']))]['value']
    literal.pop('parameters');cases['literal']=literal
    cases['rectangle']={'version':'schemaxis.freecad/1','nodes':[
        {'id':'part','filter':'body'},
        {'id':'outline','filter':'rectangle','inputs':{'body':'part'},'options':{'width':80,'height':50}},
        {'id':'slab','filter':'pad','inputs':{'body':'part','profile':'outline'},'options':{'length':12}},
        {'id':'recess','filter':'rectangle','inputs':{'body':'part'},'options':{'width':20,'height':10}},
        {'id':'finished','filter':'pocket','inputs':{'base':'slab','profile':'recess'},'options':{'extent':'length','length':4}}],
        'output':'finished'}
    try:
        for name,doc in cases.items():
            target=directory/name;registry.run(doc,target,locations={'freecad':executable},timeout=90)
            report['checks'][name]=registry.verify(target);print(name+' verified',flush=True)
        for name in ('counterbore','literal'):report['checks']['hostile-'+name]=hostile(directory/name)
        worker=SubprocessRunner(Interpreter('freecad',executable),directory,timeout=90)
        for mode in ('edit','reopen'):
            script='import sys\nsys.path.insert(0,'+repr(str(directory/'counterbore/runtime.zip'))+')\nsys.path.insert(0,'+repr(str(ROOT/'tools'))+')\nfrom qualify_freecad_finite_pocket_native import main\nmain('+repr(str(directory))+','+repr(mode)+')\n'
            atomic_json(directory/('independent-'+mode+'-submission.json'),worker(script).to_dict())
            assert (directory/('independent-'+mode+'.json')).is_file(),'independent worker failed: '+mode
        a=json.loads((directory/'independent-edit.json').read_text());b=json.loads((directory/'independent-reopen.json').read_text())
        assert a['verified'] and b['verified'] and a['pid']!=b['pid'] and a['edited']==b['edited'] and a['expressions']==b['expressions']
        report['checks']['independent']={'verified':True,'runtime':a['runtime'],'driverEdits':list(a['perturbations']),'freshProcesses':True,'sameShapeWrongTypeRejected':a['wrongTypeRejected']}
        bad=copy.deepcopy(base);bad['nodes'][5]['options']['centre']=[400,400]
        try:registry.run(bad,directory/'no-intersection',locations={'freecad':executable},timeout=90)
        except SchemaxisError as error:
            assert error.fault.code=='INVALID_GEOMETRY';report['checks']['no-intersection']=error.fault.code
        else:raise AssertionError('non-removing Pocket accepted')
        # Preserve finite analytic batches and verified workflow reuse/invalidation.
        variants=copy.deepcopy(base);variants['parameters']['counterboreDepth']['value']={'$analytic':{'type':'values','values':[2,8]}}
        registry.run(variants,directory/'finite-variants',locations={'freecad':executable},timeout=90)
        report['checks']['finite-variants']=registry.verify(directory/'finite-variants')
        envelope=json.loads((ROOT/'examples/schemaxis/freecad-counterbore-workflow.json').read_text());target=directory/'workflow'
        workflow.execute(envelope,target,locations={'freecad':executable},timeout=90);workflow.verify(target)
        reused=workflow.execute(envelope,target,locations={'freecad':executable},timeout=90,resume=True)
        assert all(j['reused'] for j in reused['jobs'])
        changed=copy.deepcopy(envelope);changed['operations'][0]['document']['parameters']['counterboreDepth']['value']=8
        try:workflow.execute(changed,target,locations={'freecad':executable},timeout=90,resume=True)
        except SchemaxisError as error:assert error.fault.code=='RESUME_MISMATCH'
        else:raise AssertionError('changed machining intent resumed')
        cad=Path(next(j['directory'] for j in reused['jobs'] if j['operation']=='cad'))
        (cad/'model.FCStd').write_bytes(b'invalid finite-depth native history')
        updated=workflow.execute(envelope,target,locations={'freecad':executable},timeout=90,resume=True);workflow.verify(target)
        reuse={j['operation']:j['reused'] for j in updated['jobs']}
        assert reuse=={'cad':False,'consumer':False,'independent':True},reuse
        workflow.execute(changed,directory/'changed-workflow',locations={'freecad':executable},timeout=90);workflow.verify(directory/'changed-workflow')
        report['checks']['workflow']={'initialReused':len(reused['jobs']),'afterInvalidHistory':reuse,'changedInput':'requires fresh run'}
        assert report['sourceDigest']==source_digest('freecad'),'source changed during qualification'
        report['verified']=True
    finally:atomic_json(directory/'report.json',report)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',required=True);p.add_argument('--executable',required=True);a=p.parse_args()
    result=qualify(a.directory,a.executable);print(json.dumps(result,indent=2))
