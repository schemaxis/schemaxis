#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Reproduce CAD, mesh processing and two-way application bridge qualification."""
import argparse
import json
import math
from pathlib import Path
from schemaxis.artifacts import atomic_json
from schemaxis.workflow import execute,verify
from schemaxis.adaptors.freecad.adaptor import run as cad_run
from schemaxis.adaptors.blender.adaptor import run as blender_run
from schemaxis.core.faults import SchemaxisError


def receipts(directory):
    jobs=json.loads((directory/'result.json').read_text())['jobs']
    return {j['operation']:json.loads((Path(j['directory'])/'verification.json').read_text()) for j in jobs}


def expect(condition,message):
    if not condition:raise AssertionError(message)


def fixture_documents():
    box={'id':'box','filter':'box','options':{'length':30,'width':20,'height':10}}
    specimens={
        'sphere':([{'id':'out','filter':'sphere','options':{'radius':10}}],4/3*math.pi*10**3),
        'cone':([{'id':'out','filter':'cone','options':{'radius1':10,'radius2':5,'height':20,'axis':[1,0,0]}}],math.pi*20/3*(100+50+25)),
        'torus':([{'id':'out','filter':'torus','options':{'majorRadius':20,'minorRadius':5}}],2*math.pi**2*20*5**2),
        'fillet':([box,{'id':'out','filter':'fillet','inputs':{'base':'box'},'options':{'radius':2,'edges':list(range(1,13))}}],26*16*6+4*(26*16+26*6+16*6)+math.pi*4*(26+16+6)+4/3*math.pi*8),
        'chamfer':([box,{'id':'out','filter':'chamfer','inputs':{'base':'box'},'options':{'distance':1,'edges':list(range(1,13))}}],6000-2*(30+20+10)+16/3),
        'extrude':([{'id':'profile','filter':'polygon','options':{'points':[[0,0],[30,0],[30,8],[10,8],[10,20],[0,20]]}}, {'id':'out','filter':'extrude','inputs':{'profile':'profile'},'options':{'length':15}}],5400),
        'revolve':([{'id':'profile','filter':'polygon','options':{'plane':'XZ','points':[[10,0],[20,0],[20,15],[10,15]]}}, {'id':'out','filter':'revolve','inputs':{'profile':'profile'}}],math.pi*300*15),
        'common':([box,{'id':'second','filter':'box','options':{'length':30,'width':20,'height':10,'origin':[15,0,0]}},{'id':'out','filter':'common','inputs':{'base':'box','tool':'second'}}],3000),
    }
    return {key:({'version':'schemaxis.freecad/1','linearDeflection':0.02,'nodes':nodes,'output':'out'},volume) for key,(nodes,volume) in specimens.items()}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--freecad',required=True);parser.add_argument('--blender',required=True)
    parser.add_argument('--paraview-root',required=True);parser.add_argument('--output-directory',required=True)
    args=parser.parse_args();root=Path(args.output_directory).absolute();root.mkdir(exist_ok=False,parents=True)
    summary={'verified':False,'cad':{},'workflows':{},'negativeChecks':{}}
    for identity,(document,expected) in fixture_documents().items():
        target=root/identity
        actual=cad_run(document,target,executable=args.freecad)['volumeMM3']
        expect(math.isclose(actual,expected,rel_tol=1e-9,abs_tol=1e-6),identity+' analytic volume differs')
        summary['cad'][identity]={'expectedVolumeMM3':expected,'nativeVolumeMM3':actual,'directory':str(target)}
        print('CAD',identity,'passed',flush=True)
    for example in ('cad-direct-to-blender','blender-mesh-workshop','blender-to-paraview'):
        target=root/example
        document=json.loads(Path('examples/schemaxis/expanded',example+'.json').read_text())
        execute(document,target,freecad=args.freecad,blender=args.blender,roots=[args.paraview_root],timeout=300)
        summary['workflows'][example]={'directory':str(target),**verify(target)}
        print('WORKFLOW',example,'passed',flush=True)
    direct=receipts(root/'cad-direct-to-blender')
    for cad,render in [('ventedHousing','housingRender'),('rail','railRender'),('connector','connectorRender')]:
        source=direct[cad]['native'];actual=direct[render]['states'][0]['observations']['styled']
        expect(all(math.isclose(x,y*.001,abs_tol=4e-5) for x,y in zip(actual['bounds'],source['bounds'])),'direct STL bounds/units differ')
        expect(math.isclose(actual['signedVolume'],source['volume']*1e-9,rel_tol=.005),'direct STL signed volume differs')
    expect(direct['ventedHousing']['native']['volume']<direct['housing']['native']['volume'],'STEP edit did not remove material')
    workshop=receipts(root/'blender-mesh-workshop')
    welded=workshop['weld']['states'][0]['observations']
    expect(welded['out']['points']<welded['joined']['points'],'weld did not merge shared vertices')
    expect(welded['joined']['points']==16,'join membership differs')
    baked=workshop['twist']['states'][0]['observations']
    expect(all(math.isclose(a,b,abs_tol=1e-6) for a,b in zip(baked['tall']['bounds'],baked['baked']['bounds'])),'applyTransform changed world-space bounds')
    expect(math.isclose(baked['tall']['signedVolume'],baked['baked']['signedVolume'],rel_tol=1e-6),'applyTransform changed volume')
    expect(len(workshop['twist']['states'])==3,'analytic twist sweep missing states')
    expect(len({s['observations']['out']['geometrySha256'] for s in workshop['twist']['states']})==3,'twist sweep did not change geometry')
    expect(math.isclose(workshop['plyImport']['states'][0]['observations']['out']['signedVolume'],8/6,rel_tol=1e-6),'PLY scale/orientation differs')
    for label,source in [('bend','tall'),('voxelUnion','joined'),('shrinkwrap','grid')]:
        obs=workshop[label]['states'][0]['observations']
        expect(obs['out']['geometrySha256']!=obs[source]['geometrySha256'],label+' did not change geometry')
    # Native bounds guard must reject a resource explosion before modifier evaluation.
    bad=json.loads(Path('examples/schemaxis/expanded/blender-mesh-workshop.json').read_text())['operations'][4]['document']
    bad['nodes'][-1]['options']['voxelSize']=1e-7
    try:blender_run(bad,root/'rejected-voxel',executable=args.blender,timeout=30)
    except SchemaxisError as error:
        expect(error.fault.code=='RESOURCE_BUDGET_EXCEEDED','wrong voxel failure: '+str(error))
        summary['negativeChecks']['voxelBudget']=error.fault.code
    else:raise AssertionError('unbounded voxel request succeeded')
    bad={'version':'schemaxis.freecad/1','nodes':[{'id':'b','filter':'box'},{'id':'out','filter':'fillet','options':{'edges':[99]},'inputs':{'base':'b'}}],'output':'out'}
    try:cad_run(bad,root/'rejected-edge',executable=args.freecad,timeout=30)
    except SchemaxisError:
        fault=json.loads((root/'rejected-edge/native-fault.json').read_text())
        expect(fault['code']=='INVALID_EDGE','wrong edge-selection failure')
        summary['negativeChecks']['edgeSelection']=fault['code']
    else:raise AssertionError('absent edge succeeded')
    summary['verified']=True
    atomic_json(root/'qualification.json',summary)
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
