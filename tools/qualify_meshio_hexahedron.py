#!/usr/bin/env python3
"""Bounded hex-volume acceptance with literal oracles and an optional Gmsh consumer."""
import argparse
import copy
import json
from pathlib import Path
import subprocess

from schemaxis.adaptor_conformance import qualify, register
from schemaxis.adaptors.meshio import adaptor, reference
from schemaxis.artifacts import atomic_json
from schemaxis import workflow
from qualify_meshio import refresh, refused

ROOT = Path(__file__).resolve().parents[1]


def literal(directory, extension, warped=False):
    points = [[10,20,30],[12,20,30],[12,23,30],[10,23,30],
              [10.5,20,34],[12.5,20,34],[12.5,23,34],[10.5,23,34],
              [30,20,30],[32,20,30],[30,23,30],[30,20,34]]
    if warped:
        for p in points[4:8]:p[0]-=.5
        points[6][2]=35
    else:
        points = [[v*.001 for v in p] for p in points]
    expected = {'points':points,'cells':[['hexahedron',list(range(8))],['triangle',[0,1,2]],['tetra',[8,9,10,11]]],
                'pointData':{'node_id':[[101+2*i] for i in range(12)],'displacement':[[i,-i,.5*i] for i in range(12)]},
                'cellData':{'region':[[7],[9],[11]],'direction':[[1,0,0],[0,1,0],[0,0,-1]]}}
    mesh = reference.parse((directory/('mesh.'+extension)).read_bytes(),extension)
    reference.compare(expected,mesh)
    volume=reference.summary(mesh)['hexahedronVolumes'][0]
    target=25.5 if warped else 24e-9
    assert abs(volume-target) <= abs(target)*1e-11
    return {'orderedPoints':12,'orderedCells':3,'hexahedronVolume':volume,'literalExpectedVolume':target,'fieldsUnscaled':True}


def controls(directory,document,executable):
    from xml.etree import ElementTree as ET
    source=Path(document['source']).read_bytes();report={}
    for label in ('inverted','twisted','near-degenerate','folded','high-order','voxel','malformed'):
        tree=ET.fromstring(source)
        connectivity=tree.find('.//Cells/DataArray[@Name="connectivity"]')
        positions=tree.find('.//Points/DataArray')
        if label=='inverted':connectivity.text='1 0 3 2 5 4 7 6 0 1 2 8 9 10 11'
        elif label=='twisted':connectivity.text='0 1 2 3 4 6 5 7 0 1 2 8 9 10 11'
        elif label in ('near-degenerate','folded'):
            xyz=list(map(float,positions.text.split()))
            if label=='folded':xyz[6*3+2]=29
            else:
                for i in range(4,8):xyz[i*3+2]=30+1e-13
            positions.text=' '.join(map(str,xyz))
        elif label in ('high-order','voxel'):tree.find('.//Cells/DataArray[@Name="types"]').text=('25' if label=='high-order' else '11')+' 5 10'
        data=b'<not-a-mesh>' if label=='malformed' else ET.tostring(tree)
        path=directory/(label+'.vtu');path.write_bytes(data)
        report[label]=refused(lambda:adaptor.run({**document,'source':str(path)},directory/(label+'-run'),executable=executable),'INVALID_MESH_CONTENT')
        assert not (directory/(label+'-run')/'convert-inputs.json').exists()
    # Exercise the native rejection independently of preflight; authored input
    # never exposes this bypass. Higher-order geometry must not silently convert.
    work=directory/'native-high-order';work.mkdir();(work/'source.vtu').write_bytes(source.replace(b'>12 5 10<',b'>25 5 10<'))
    (work/'native-worker.py').write_text(adaptor.worker_source());atomic_json(work/'native-config.json',{'sourceFormat':'vtu','targetFormat':'vtk','factor':.001})
    result=subprocess.run([executable,'-I',str(work/'native-worker.py'),'convert'],cwd=work,capture_output=True,timeout=20,env={'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','PATH':'/usr/bin:/bin'})
    (work/'stdout').write_bytes(result.stdout);(work/'stderr').write_bytes(result.stderr)
    assert result.returncode != 0 and not (work/'mesh.vtk').exists()
    report['native-high-order']={'exitCode':result.returncode,'outputAbsent':True}
    return report


def tamper(directory):
    saved={p:p.read_bytes() for p in directory.rglob('*') if p.is_file()};report={}
    def restore():
        for p,b in saved.items():p.write_bytes(b)
    def change(kind):
        path=directory/'mesh.vtk';raw=path.read_text()
        if kind=='ordered-topology':
            # A valid cyclic rotation still violates the retained ordered topology.
            raw=raw.replace('8\n0\n1\n2\n3\n4\n5\n6\n7','8\n1\n2\n3\n0\n5\n6\n7\n4',1)
            assert raw != path.read_text();path.write_text(raw)
        elif kind=='field-association':
            raw=raw.replace('101 103','999 103',1);assert raw != path.read_text();path.write_text(raw)
        else:
            d=adaptor.read(directory,'readback.stdout');d['mesh']['points'][6][2]+=.00001;atomic_json(directory/'readback.stdout',d)
    for kind in ('ordered-topology','field-association','native-geometry'):
        try:
            change(kind);refresh(directory);report[kind+'-refreshed']=refused(lambda:adaptor.verify(directory))
        finally:restore()
    assert adaptor.verify(directory)['verified'];return report


GMSH_CONSUMER = r'''
import json, math, sys
import gmsh
gmsh.initialize();gmsh.option.setNumber('General.Terminal',0)
try:
    gmsh.open(sys.argv[1])
    tags,coordinates,_=gmsh.model.mesh.getNodes()
    assert len(tags)==12
    xyz={int(t):list(coordinates[3*i:3*i+3]) for i,t in enumerate(tags)}
    types,element_tags,connectivity=gmsh.model.mesh.getElements()
    assert {int(t):len(ids) for t,ids in zip(types,element_tags)}=={2:1,4:1,5:1}
    index=list(types).index(5);hex_nodes=list(connectivity[index])
    expected=[[.01,.02,.03],[.012,.02,.03],[.012,.023,.03],[.01,.023,.03],
              [.0105,.02,.034],[.0125,.02,.034],[.0125,.023,.034],[.0105,.023,.034]]
    assert all(math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-15) for t,p in zip(hex_nodes,expected) for a,b in zip(xyz[int(t)],p))
    local,weights=gmsh.model.mesh.getIntegrationPoints(5,'Gauss2')
    _,determinants,_=gmsh.model.mesh.getJacobians(5,local)
    volume=sum(float(w*d) for w,d in zip(weights,determinants))
    assert math.isclose(volume,24e-9,rel_tol=1e-11)
    print(json.dumps({'runtime':gmsh.__version__,'nodes':len(tags),'elements':3,'hexahedronVolume':volume,'expectedVolume':24e-9,
                      'scope':'Independent Gmsh VTK import, element/node order and Gauss-integrated volume. Gmsh field/group preservation is not claimed.'}))
finally:gmsh.finalize()
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--meshio',type=Path,required=True);parser.add_argument('--gmsh',type=Path);parser.add_argument('--output-directory',type=Path,required=True);parser.add_argument('--register',action='store_true');args=parser.parse_args()
    directory=args.output_directory.absolute();directory.mkdir(parents=True,exist_ok=False)
    executable=str(args.meshio.absolute());locations={'meshio':executable};report={'verified':False}
    try:
        receipt=qualify(adaptor.VERSION,directory/'kit',native=True,root=ROOT,locations=locations,timeout=40,wall_timeout=120)
        assert receipt['verified'];report['cases']=[c['id'] for c in receipt['cases']]
        baseline=directory/'kit/hex-affine-mm-to-m';variant=directory/'kit/hex-warped-cm-to-mm'
        report['literal']=[literal(baseline,'vtk'),literal(variant,'vtu',True)]
        report['tamper']=tamper(baseline)
        document=json.loads((ROOT/'examples/schemaxis/meshio-hex-convert.json').read_text());document['source']=str(ROOT/'examples/schemaxis/fixtures/meshio/hex-affine.vtu')
        report['controls']=controls(directory,document,executable)
        graph={'version':'schemaxis.workflow/1','operations':[{'id':'metres','document':document},{'id':'centimetres','document':{**document,'source':{'$artifact':'metres','index':0},'sourceFormat':'vtk','targetFormat':'vtu','sourceUnits':'m','targetUnits':'cm'}}]}
        result=workflow.execute(graph,directory/'workflow',locations=locations,timeout=40);assert result['status']=='succeeded' and workflow.verify(directory/'workflow')['verified']
        resumed=workflow.execute(graph,directory/'workflow',locations=locations,timeout=40,resume=True);assert all(j['reused'] for j in resumed['jobs'])
        report['workflow']={'verified':True,'handoff':'Verified metre VTK artifact to centimetre VTU','unchangedReused':True}
        if args.gmsh:
            script=directory/'gmsh-consumer.py';script.write_text(GMSH_CONSUMER)
            result=subprocess.run([str(args.gmsh.absolute()),'-I',str(script),str(baseline/'mesh.vtk')],capture_output=True,timeout=30)
            (directory/'gmsh.stdout').write_bytes(result.stdout);(directory/'gmsh.stderr').write_bytes(result.stderr)
            assert result.returncode==0,result.stderr.decode();report['gmshConsumer']=json.loads(result.stdout)
        else:report['gmshConsumer']={'status':'not-run','reason':'Provide an isolated Gmsh Python interpreter for independent consumer verification.'}
        if args.register:register(directory/'kit/qualification.json')
        report['verified']=True
    finally:atomic_json(directory/'acceptance.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
