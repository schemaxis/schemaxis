#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Qualify bounded OpenSCAD geometry, lifecycle and declarative workflow reuse."""
import argparse
import copy
import json
import math
import os
import shutil
from pathlib import Path
import struct
import sys
import threading
import time
from unittest.mock import patch

from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation
from schemaxis.adaptors import registry
from schemaxis.adaptors.openscad import adaptor as a, geometry as g
ROOT=Path(__file__).resolve().parents[1]


def refused(action,code='VERIFICATION_FAILED'):
    try:action()
    except SchemaxisError as error:
        assert error.fault.code==code,error.fault.to_dict();return error.fault.to_dict()
    raise AssertionError('invalid CAD/evidence was accepted')


def refresh(directory,bindings=False):
    if bindings:
        for stage in ['construct','reopen']:
            atomic_json(directory/(stage+'-inputs.json'),{str(directory/n):a.digest(directory,n) for n in a.stage_inputs(stage)})
    receipt=a.read(directory,'verification.json');receipt['artifacts']=a.artifacts(directory);receipt['evidence']={n:a.digest(directory,n) for n in receipt['evidence']};atomic_json(directory/'verification.json',receipt)
    from schemaxis.publication_metadata import finalise
    finalise(directory)


def encode(triangles):
    data=bytearray(b'qualification adversary'.ljust(80,b'\0')+struct.pack('<I',len(triangles)))
    for tri in triangles:
        normal=g.cross(g.sub(tri[1],tri[0]),g.sub(tri[2],tri[0]));size=math.sqrt(g.dot(normal,normal));normal=[x/size for x in normal] if size else [0,0,0]
        data.extend(struct.pack('<12fH',*normal,*(x for v in tri for x in v),0))
    return bytes(data)


def hostile(directory):
    saved={p:p.read_bytes() for p in directory.rglob('*') if p.is_file()};report={}
    def restore():
        for p in directory.rglob('*'):
            if p.is_file() and p not in saved:p.unlink()
        for p,b in saved.items():p.write_bytes(b)
    tri=g.stl(saved[directory/'part.stl'])
    changes={
      'shift':lambda fs:[[(v[0]+.02,v[1],v[2]) for v in f] for f in fs],
      'wrongUnits':lambda fs:[[tuple(x*.001 for x in v) for v in f] for f in fs],
      'equalVolumeWrongOutline':lambda fs:[[(v[0]*1.25,v[1]*.8,v[2]) for v in f] for f in fs],
      'reflectedHoles':lambda fs:[[(40-v[0],v[1],v[2]) for v in reversed(f)] for f in fs],
      'inwardNormals':lambda fs:[list(reversed(f)) for f in fs],
      'missingTriangle':lambda fs:fs[:-1],
      'duplicateTriangle':lambda fs:fs+[fs[0]],
      'degenerateTriangle':lambda fs:[[fs[0][0]]*3]+fs[1:],
      'sideCrossing':lambda fs:[[fs[0][0],fs[-1][1],fs[0][2]]]+fs[1:]}
    for name,change in changes.items():
        try:
            raw=encode(change(tri))
            # Replace both native representations and their consumed-input hash,
            # proving semantic checks still reject refreshed-hash forgeries.
            (directory/'part.stl').write_bytes(raw);(directory/'reopened.stl').write_bytes(raw);refresh(directory,bindings=True)
            report[name]=refused(lambda:a.verify(directory))['code']
        finally:restore()
    for name,target,change in [('normalOnly','part.stl',lambda b:b[:84]+struct.pack('<3f',0,0,0)+b[96:]),('trustedSCAD','part.scad',lambda b:b+b'cube([1,1,1]);\n'),('summary','part-summary.json',lambda b:b.replace(b'"units": "mm"',b'"units": "cm"')),('trustedLauncher','construct-launcher.py',lambda b:b.replace(b"'binstl'",b"'asciistl'"))]:
        try:
            p=directory/target;b=p.read_bytes();changed=change(b);assert changed!=b,name;p.write_bytes(changed);refresh(directory,bindings=True);report[name]=refused(lambda:a.verify(directory))['code']
        finally:restore()
    try:
        (directory/'part-unlisted.stl').write_bytes(saved[directory/'part.stl']);refresh(directory);report['unexpectedPublication']=refused(lambda:a.verify(directory))['code']
    finally:restore()
    for name,change in [('missingEvidence',lambda r:r['evidence'].pop('construct.stdout')),('extraEvidence',lambda r:r['evidence'].update({'extra':'0'*64})),('publicationMembership',lambda r:r['artifacts'].pop()),('runtime',lambda r:r.update(runtime='OpenSCAD nightly'))]:
        try:
            receipt=a.read(directory,'verification.json');change(receipt);atomic_json(directory/'verification.json',receipt);report[name]=refused(lambda:a.verify(directory))['code']
        finally:restore()
    assert a.verify(directory)['verified'];return report


def representation_checks(directory,baseline):
    """Order-independent reopen, retained-path limits and a hole-chord adversary."""
    saved={p:p.read_bytes() for p in baseline.rglob('*') if p.is_file()}
    raw=saved[baseline/'reopened.stl'];blocks=[raw[k:k+50] for k in range(84,len(raw),50)]
    # Reverse facet records and cyclically rotate their vertex triples. Normals,
    # coordinates, winding and facet membership remain bit-for-bit identical.
    rotated=[]
    for block in reversed(blocks):
        rotated.append(block[:12]+block[24:48]+block[12:24]+block[48:])
    try:
        (baseline/'reopened.stl').write_bytes(raw[:84]+b''.join(rotated));refresh(baseline)
        assert a.verify(baseline)['verified']
    finally:
        for path,data in saved.items():path.write_bytes(data)
    document=a.plan(a.read(baseline,'authored.json'));triangles=g.stl(a.bounded(baseline/'part.stl'))
    vertices={v for face in triangles for v in face};contour=g.contours(document)[1]
    z=document['translation'][2]+document['plate']['height'];points=[]
    for x,y in contour[:3]:
        expected=(x+document['translation'][0],y+document['translation'][1],z)
        points.append(min(vertices,key=lambda v:math.dist(v,expected)))
    if g.cross(g.sub(points[1],points[0]),g.sub(points[2],points[0]))[2]<0:points.reverse()
    fault=refused(lambda:g.inspect(encode(triangles+[points]),document))
    assert 'oriented closed two-manifold' in fault['message'],fault
    relocated=directory/'relocated-evidence';shutil.copytree(baseline,relocated)
    moved=refused(lambda:a.verify(relocated))
    return {'facetOrderAndCyclicStartAccepted':True,'holeChordRejectedByDirectedEdges':True,
            'relocatedEvidenceRejected':moved,'relocationSupported':False}


def lifecycle(directory,document):
    wrapper=directory/'slow-runtime.py';marker=directory/'slow.pid'
    wrapper.write_text('#!'+sys.executable+'\nimport os,time\nfrom pathlib import Path\nPath('+repr(str(marker))+').write_text(str(os.getpid()))\ntime.sleep(30)\n');wrapper.chmod(0o700)
    report={}
    for action in ['timeout','cancel']:
        if marker.exists():marker.unlink()
        cancel=threading.Event()
        def trigger():
            deadline=time.monotonic()+5
            while not marker.exists() and time.monotonic()<deadline:time.sleep(.01)
            if marker.exists():cancel.set()
        thread=threading.Thread(target=trigger,daemon=True) if action=='cancel' else None
        if thread:thread.start()
        try:
            with allocation({'threads':1,'ranks':1},cancel):report[action]=refused(lambda:a.run(document,directory/('inflight-'+action),executable=str(wrapper),timeout=8 if thread else .4),'RUNNER_CANCELLED' if thread else 'RUNNER_TIMED_OUT')['code']
        finally:
            if thread:thread.join(6)
        assert marker.exists(),'owned child never started'
        try:os.kill(int(marker.read_text()),0)
        except ProcessLookupError:pass
        else:raise AssertionError('owned child survived '+action)
        assert a.read(directory/('inflight-'+action),'result.json')['status']=='failed'
    return report


def literal(directory,name):
    # Read actual binary triangles and sum a separately expanded determinant.
    # Literal fixture expectations do not consult host summary or plan formula.
    data=(directory/'part.stl').read_bytes();count=struct.unpack_from('<I',data,80)[0];points=[];terms=[]
    for i in range(count):
        values=struct.unpack_from('<12fH',data,84+50*i);u,v,w=[values[k:k+3] for k in (3,6,9)];points.extend([u,v,w])
        terms.append((u[0]*(v[1]*w[2]-v[2]*w[1])+u[1]*(v[2]*w[0]-v[0]*w[2])+u[2]*(v[0]*w[1]-v[1]*w[0]))/6)
    bounds=[[min(v[k] for v in points) for k in range(3)],[max(v[k] for v in points) for k in range(3)]]
    if name=='plate':expected_bounds=[[0,0,0],[40,30,3]];volume=3600-39*32*math.sin(math.pi/32)
    elif name=='plate-variant':expected_bounds=[[20,-10,5],[60,20,10]];volume=6000-65*16*math.sin(math.pi/16)
    else:expected_bounds=[[-10,-10,0],[10,10,10]];volume=840*32*math.sin(math.pi/32)
    assert bounds==expected_bounds,(name,bounds)
    measured=math.fsum(terms);assert math.isclose(measured,volume,rel_tol=2e-6),(name,measured,volume)
    return {'literalBounds':bounds,'measuredVolume':measured,'independentExpectedVolume':volume,'relativeError':abs(measured-volume)/volume}


def limits(directory,executable):
    base={'version':a.VERSION,'operation':'plate','units':'mm'}
    cases={'plain':{**base,'plate':{'width':2,'depth':3,'height':4}},
      'minimum-translated':{**base,'translation':[100,-100,100],'plate':{'width':.5,'depth':.5,'height':.5}},
      'maximum':{**base,'segments':256,'plate':{'width':100,'depth':100,'height':5,'holes':[{'centre':[x,y],'diameter':10} for x in [15,35,55,75] for y in [15,35,55,75]]}},
      'thin-wall-nonround':{'version':a.VERSION,'operation':'spacer','units':'mm','segments':256,'translation':[99.123,-88.321,50.789],'spacer':{'outerDiameter':199.123,'boreDiameter':198.123,'height':.531}},
      'small-coarse-bore':{'version':a.VERSION,'operation':'spacer','units':'mm','segments':16,'spacer':{'outerDiameter':1.5,'boreDiameter':.5,'height':.5}}}
    report={}
    for name,document in cases.items():
        start=time.monotonic();target=directory/name;result=a.run(document,target,executable=executable,timeout=120);assert result['verified'];summary=a.read(target,'part-summary.json')
        if name=='plain':assert summary['volume']==24
        if name=='minimum-translated':assert summary['volume']==.125
        report[name]={'seconds':time.monotonic()-start,'verified':True,'triangles':summary['triangles'],'volume':summary['volume'],'euler':summary['eulerCharacteristic']}
    return report


def workflow_checks(directory,document,executable):
    from schemaxis import workflow
    consumer=json.loads((ROOT/'examples/schemaxis/openscad-spacer.json').read_text());consumer['spacer']['height']={'$value':'producer','artifact':2,'path':'/height'}
    graph={'version':'schemaxis.workflow/1','operations':[{'id':'producer','document':document},{'id':'consumer','document':consumer}]};locations={'openscad':executable}
    first=workflow.execute(graph,directory/'workflow',locations=locations,timeout=60);assert workflow.verify(directory/'workflow')['verified']
    downstream=next(j for j in first['jobs'] if j['operation']=='consumer');assert a.read(Path(downstream['directory']),'part-summary.json')['height']==3
    second=workflow.execute(graph,directory/'workflow',locations=locations,timeout=60,resume=True);assert all(j['reused'] for j in second['jobs'])
    producer=next(j for j in second['jobs'] if j['operation']=='producer');cached=Path(producer['directory'])/'part.stl';cached.write_bytes(cached.read_bytes()+b'x')
    third=workflow.execute(graph,directory/'workflow',locations=locations,timeout=60,resume=True);assert not any(j['reused'] for j in third['jobs']);assert workflow.verify(directory/'workflow')['verified']
    graph['operations'][0]['document']['plate']['height']=4
    refused(lambda:workflow.execute(graph,directory/'workflow',locations=locations,timeout=60,resume=True),'RESUME_MISMATCH')
    changed=workflow.execute(graph,directory/'workflow-changed',locations=locations,timeout=60);assert workflow.verify(directory/'workflow-changed')['verified']
    downstream=next(j for j in changed['jobs'] if j['operation']=='consumer');assert a.read(Path(downstream['directory']),'part-summary.json')['height']==4
    study=copy.deepcopy(document);study['axes']=[{'name':'height','values':[2,4]}];study['plate']['height']={'$axis':'height'}
    result=a.run(study,directory/'study',executable=executable,timeout=60);assert a.verify(directory/'study')['verified'] and len(result['states'])==2
    return {'verifiedValueHandoff':True,'unchangedReused':True,'corruptCacheInvalidatedProducerAndConsumer':True,'changedAuthoredResumeRejected':True,'freshChangedHeight':4,'finiteStates':2}


def slicer_handoff(directory,executable,slicer):
    from schemaxis import workflow
    graph=json.loads((ROOT/'examples/schemaxis/openscad-to-prusaslicer.json').read_text())
    locations={'openscad':executable,'prusaslicer':slicer};target=directory/'prusaslicer-handoff'
    result=workflow.execute(graph,target,locations=locations,timeout=120);assert workflow.verify(target)['verified']
    job=next(j for j in result['jobs'] if j['operation']=='toolpath');summary=json.loads((Path(job['directory'])/'slice-summary.json').read_text())
    assert summary['accepted'] and summary['native']['layers']['count']==15 and summary['native']['model']['size_mm']==[40,30,3]
    repeat=workflow.execute(graph,target,locations=locations,timeout=120,resume=True);assert all(j['reused'] for j in repeat['jobs'])
    return {'verified':True,'nativeRuntime':summary['runtime'],'modelSize_mm':[40,30,3],'layers':15,'unchangedBothReused':True,'printerControl':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--openscad',type=Path,required=True);parser.add_argument('--output-directory',type=Path,required=True);parser.add_argument('--register',action='store_true');parser.add_argument('--prusaslicer',type=Path,help='Optional separately qualified PrusaSlicer console executable for actual STL handoff');parser.add_argument('--kernels-only',action='store_true',help='Exercise pending adaptor directly, without registered kit/workflow or qualification claim');args=parser.parse_args()
    directory=args.output_directory.resolve();directory.mkdir(parents=True,exist_ok=False);executable=str(args.openscad.resolve());report={'verified':False,'kernelsOnly':args.kernels_only}
    pending=ROOT/'src/schemaxis/adaptors/openscad/adaptor.json.pending'
    if args.kernels_only:
        assert not args.register,'pending kernels cannot register qualification'
        registration=patch.dict(registry.ADAPTORS,{'openscad':json.loads(pending.read_text())}) if pending.exists() else patch.dict(registry.ADAPTORS,{})
    else:registration=patch.dict(registry.ADAPTORS,{})
    with registration:
        try:
            document=json.loads((ROOT/'examples/schemaxis/openscad-plate.json').read_text())
            if args.kernels_only:
                cases_root=directory/'kernels'
                for name in ['plate','plate-variant','spacer']:
                    d=json.loads((ROOT/f'examples/schemaxis/openscad-{name}.json').read_text());a.run(d,cases_root/name,executable=executable,timeout=60)
            else:
                from schemaxis.adaptor_conformance import qualify,register
                cases_root=directory/'kit';receipt=qualify(a.VERSION,cases_root,native=True,root=ROOT,locations={'openscad':executable},timeout=60,wall_timeout=90)
                report['native']={'verified':receipt['verified'],'cases':[c['id'] for c in receipt['cases']],'runtimes':[c['runtime'] for c in receipt['cases']],'lifecycle':receipt['lifecycle']}
            report['literalNative']={name:literal(cases_root/name,name) for name in ['plate','plate-variant','spacer']}
            report['hostile']=hostile(cases_root/'plate');report['representation']=representation_checks(directory,cases_root/'plate');report['limits']=limits(directory,executable);report['inflightLifecycle']=lifecycle(directory,document)
            if not args.kernels_only:
                report['workflow']=workflow_checks(directory,document,executable)
                if args.prusaslicer:report['prusaslicer']=slicer_handoff(directory,executable,str(args.prusaslicer.resolve()))
                if args.register:register(cases_root/'qualification.json')
            report['verified']=True
        finally:atomic_json(directory/'acceptance.json',report)
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
