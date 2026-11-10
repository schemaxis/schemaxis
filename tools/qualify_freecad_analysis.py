#!/usr/bin/env python3
"""CAD-to-FEM qualification: analytic controls, enclosure/refinement and attacks."""
import argparse
import copy
import json
import math
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from schemaxis.adaptors import registry
from schemaxis.adaptors.freecad import analysis
from schemaxis.adaptor_delivery import source_digest
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.core.faults import SchemaxisError
ROOT=Path(__file__).resolve().parents[1]


def bar(source):
    return {'version':analysis.VERSION,'source':{'file':str(source),'units':'mm','expect':{'volume':320,'bounds':[0,20,0,4,0,4],'centreOfMass':[10,2,2]}},
        'material':{'name':'Elastic control','youngModulusMPa':70000,'poissonRatio':0,'densityKgPerM3':2700},'mesh':{'sizeMM':2},
        'supports':[{'id':'clamp','face':{'face':'left'}}],'loads':[{'id':'pull','kind':'force','face':{'face':'right'},'forceN':[100,0,0]}],
        'limits':[{'id':'deflection','quantity':'maxDisplacementMM','maximum':.002}]}


def hostile(target):
    path=target/'analysis.FCStd';saved=path.read_bytes();receipts={name:(target/name).read_bytes() for name in ('reopen.json','verification.json')}
    with ZipFile(path) as archive:entries={n:archive.read(n) for n in archive.namelist()}
    def prop(r,n,p):return r.find("./ObjectData/Object[@name='%s']/Properties/Property[@name='%s']"%(n,p))
    attacks={
        'material':lambda r:prop(r,'Material','Material').find("Map/Item[@key='YoungsModulus']").set('value','140000 MPa'),
        'support':lambda r:prop(r,'Support0','xDisplacement').find('Float').set('value','1'),
        'load':lambda r:prop(r,'Load0','Force').find('Float').set('value','200000'),
        'face-reference':lambda r:prop(r,'Load0','References').find('LinkSubList/Link').set('sub','Face1'),
        'solver':lambda r:prop(r,'Solver','GeometricalNonlinearity').find('Integer').set('value','1'),
        'mesh-order':lambda r:prop(r,'Mesh','ElementOrder').find('Integer').set('value','0'),
        'proxy-class':lambda r:prop(r,'Material','Proxy').find('Python').set('module','untrusted_authored_module'),
        'proxy-state':lambda r:prop(r,'Material','Proxy').find('Python').set('value','e30=')}
    report={}
    for identity,change in attacks.items():
        try:
            root=ET.fromstring(entries['Document.xml']);change(root)
            with ZipFile(path,'w') as archive:
                for n,data in entries.items():archive.writestr(n,ET.tostring(root) if n=='Document.xml' else data)
            for n,data in receipts.items():
                r=json.loads(data);r['artifacts'][0]['sha256']=file_digest(path);atomic_json(target/n,r)
            try:analysis.verify(target)
            except SchemaxisError as error:
                assert error.fault.code=='VERIFICATION_FAILED' and 'digest' not in error.fault.message.lower(),str(error)
                report[identity]=error.fault.code
            else:raise AssertionError('Saved analysis attack accepted: '+identity)
        finally:
            path.write_bytes(saved)
            for n,data in receipts.items():(target/n).write_bytes(data)
    for identity,filename,old,new in [('deck-material','Mesh.inp','70000','71000'),('dat-field','Mesh.dat','1.785714E-03','1.885714E-03')]:
        p=target/filename;original=p.read_bytes();text=original.decode();assert old in text,(filename,old)
        try:
            p.write_text(text.replace(old,new,1))
            for n,data in receipts.items():
                r=json.loads(data);next(a for a in r['artifacts'] if a['file']==str(p))['sha256']=file_digest(p);atomic_json(target/n,r)
            try:analysis.verify(target)
            except SchemaxisError as error:report[identity]=error.fault.code
            else:raise AssertionError('Solver field attack accepted: '+identity)
        finally:
            p.write_bytes(original)
            for n,data in receipts.items():(target/n).write_bytes(data)
    # Forge FRD stresses and both cached native observations consistently. The
    # independent constitutive extrapolation envelope must still reject them.
    originals={n:(target/n).read_bytes() for n in ('Mesh.frd','build.json','reopen.json','verification.json')}
    try:
        lines=[];stress=False
        for line in originals['Mesh.frd'].decode().splitlines():
            if line.startswith(' -4'):stress=line[5:17].strip()=='STRESS'
            if stress and line.startswith(' -1'):line=line[:13]+''.join(f'{0.:12.5E}' for _ in range(6))
            lines.append(line)
        (target/'Mesh.frd').write_text('\n'.join(lines)+'\n')
        for n in ('build.json','reopen.json','verification.json'):
            r=json.loads(originals[n]);r['observed']['result']['stresses']={k:[0.]*6 for k in r['observed']['result']['stresses']}
            for artifact in r.get('artifacts',[]):
                if artifact['file']==str(target/'Mesh.frd'):artifact['sha256']=file_digest(target/'Mesh.frd')
            atomic_json(target/n,r)
        try:analysis.verify(target)
        except SchemaxisError as error:
            assert 'constitutive' in error.fault.message.lower(),str(error);report['coforged-stress-and-cache']=error.fault.code
        else:raise AssertionError('Co-forged zero solver stress and native caches accepted')
    finally:
        for n,data in originals.items():(target/n).write_bytes(data)
    assert registry.verify(target)['verified'];return report


def qualify_workflow(directory,executable):
    from schemaxis import workflow
    directory=Path(directory);stock={'version':'schemaxis.freecad/1','units':'mm','nodes':[{'id':'stock','filter':'box','options':{'length':20,'width':4,'height':4}}],'output':'stock'}
    d=bar('placeholder.step');d['source']['file']={'$artifact':'stock','index':0}
    envelope={'version':'schemaxis.workflow/1','execution':{'maxWorkers':1,'cpus':2,'memoryMB':4096,'gpus':0},'operations':[{'id':'stock','document':stock},{'id':'analysis','document':d}]}
    workflow.execute(envelope,directory,locations={'freecad':executable},timeout=300);workflow.verify(directory)
    reused=workflow.execute(envelope,directory,locations={'freecad':executable},timeout=300,resume=True);assert all(j['reused'] for j in reused['jobs'])
    changed=copy.deepcopy(envelope);changed['operations'][1]['document']['loads'][0]['forceN']=[200,0,0]
    try:workflow.execute(changed,directory,locations={'freecad':executable},timeout=300,resume=True)
    except SchemaxisError as error:assert error.fault.code=='RESUME_MISMATCH'
    else:raise AssertionError('Changed load resumed unchanged calculation')
    producer=Path(next(j['directory'] for j in reused['jobs'] if j['operation']=='stock'));(producer/'model.step').write_text('invalid changed source')
    updated=workflow.execute(envelope,directory,locations={'freecad':executable},timeout=300,resume=True);workflow.verify(directory)
    reuse={j['operation']:j['reused'] for j in updated['jobs']};assert reuse=={'stock':False,'analysis':False},reuse
    return {'initialReused':2,'afterInvalidCAD':reuse,'changedLoad':'requires fresh run'}


def qualify(directory,executable):
    directory=Path(directory).absolute();directory.mkdir(parents=True,exist_ok=False)
    report={'verified':False,'sourceDigest':source_digest('freecad'),'checks':{}}
    def run(identity,d):
        target=directory/identity;registry.run(d,target,locations={'freecad':executable},timeout=300)
        r=registry.verify(target)['analysis'];report['checks'][identity]=r;atomic_json(directory/'qualification.json',report);print(identity+' verified',flush=True);return r
    stock={'version':'schemaxis.freecad/1','units':'mm','nodes':[{'id':'stock','filter':'box','options':{'length':20,'width':4,'height':4}}],'output':'stock'}
    registry.run(stock,directory/'bar-cad',locations={'freecad':executable},timeout=120)
    base=bar(directory/'bar-cad/model.step')
    for identity,order,size,kind,sign in [('axial-quadratic',2,2,'force',1),('axial-refined',2,1.3,'force',1),('axial-linear',1,2,'force',1),('pressure-compression',2,2,'pressure',-1)]:
        d=copy.deepcopy(base);d['mesh'].update(order=order,sizeMM=size)
        if kind=='pressure':d['loads']=[{'id':'pressure','kind':'pressure','face':{'face':'right'},'pressureMPa':6.25}]
        r=run(identity,d)
        assert math.isclose(r['maxDisplacementMM'],100*20/(16*70000),rel_tol=3e-5)
        assert math.isclose(r['maxVonMisesMPa'],6.25,rel_tol=5e-5)
        assert math.isclose(r['strainEnergyNMM'],.5*100**2*20/(16*70000),rel_tol=3e-5)
        assert math.isclose(r['reactionForceN'][0],-sign*100,rel_tol=1e-5)
    d=copy.deepcopy(base);d['material']['poissonRatio']=.3;d['loads'][0]['forceN']=[200,0,0];d['limits'][0]['maximum']=.00001
    r=run('poisson-serviceability-unmet',d);assert r['limitsSatisfied'] is False
    d=copy.deepcopy(base);prescribed=2*100*20/(16*70000)
    d['supports'].append({'id':'end-displacement','face':{'face':'right'},'displacementMM':[prescribed,None,None]})
    d['limits']=[];r=run('prescribed-displacement-work',d)
    assert math.isclose(r['maxDisplacementMM'],prescribed,rel_tol=3e-5)
    assert math.isclose(r['strainEnergyNMM'],.5*200*prescribed,rel_tol=3e-5)
    enclosure=json.loads((ROOT/'examples/schemaxis/freecad-parametric-enclosure.json').read_text())
    registry.run(enclosure,directory/'enclosure-cad',locations={'freecad':executable},timeout=120)
    volume=10128+60*math.pi
    source={'file':str(directory/'enclosure-cad/model.step'),'units':'mm','expect':{'volume':volume,'bounds':[-20,20,-15,15,0,20],'centreOfMass':[0,0,(80472+414*math.pi)/volume]}}
    d=copy.deepcopy(base);d['source']=source;d['material']['poissonRatio']=.3;d['limits']=[];d['supports'][0]['face']={'face':'bottom'};d['loads']=[{'id':'rim-pressure','kind':'pressure','face':{'face':'top'},'pressureMPa':.1}]
    coarse=None
    for identity,size in [('enclosure-coarse',3),('enclosure-refined',2)]:
        d['mesh'].update(sizeMM=size,volumeTolerance=.003);r=run(identity,d)
        assert math.isclose(r['appliedForceN'][2],-(40*30-34*24)*.1,rel_tol=.003)
        if coarse is not None:
            delta=abs(r['maxDisplacementMM']-coarse['maxDisplacementMM'])/r['maxDisplacementMM'];assert delta<.1,delta
            report['checks']['enclosure-response-refinement']={'relativeDisplacementChange':delta,'criterion':.1,'stressCertification':False}
        coarse=r
    from schemaxis.core.runners import Interpreter
    from schemaxis.dispatch import SubprocessRunner
    worker=SubprocessRunner(Interpreter('freecad',executable),directory,timeout=240)
    for stage in ('edit1','edit2','reopen'):
        code='import sys\nsys.path.insert(0,'+repr(str(directory/'axial-quadratic/runtime.zip'))+')\nsys.path.insert(0,'+repr(str(ROOT/'tools'))+')\nfrom qualify_freecad_analysis_native import main\nmain('+repr(str(directory))+','+repr(stage)+')\n'
        atomic_json(directory/('edit-'+stage+'-submission.json'),worker(code).to_dict())
        expected=directory/('edit-reopened.json' if stage=='reopen' else stage+'/edited.json')
        assert expected.is_file(),'Native FEM edit lifecycle did not finish: '+stage
    report['checks']['edit-save-fresh-reopen-second-solve']=json.loads((directory/'edit-reopened.json').read_text())
    report['checks']['saved-attacks']=hostile(directory/'axial-quadratic')
    source=directory/'bar-cad/model.step';temporary=directory/'source-hidden.step';source.rename(temporary)
    try:assert registry.verify(directory/'axial-quadratic')['verified']
    finally:temporary.rename(source)
    report['checks']['source-removal']={'verified':True}
    report['checks']['workflow']=qualify_workflow(directory/'workflow',executable)
    assert report['sourceDigest']==source_digest('freecad'),'Adaptor source changed during analysis qualification'
    report['verified']=True;atomic_json(directory/'qualification.json',report);return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory');p.add_argument('--freecad',required=True);a=p.parse_args();qualify(a.directory,a.freecad)
