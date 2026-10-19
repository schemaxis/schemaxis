#!/usr/bin/env python3
"""Qualify meshio with a literal oracle, hostile artifacts and workflow lifecycle."""
import argparse
import copy
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time

from schemaxis import workflow
from schemaxis.adaptor_conformance import qualify, register
from schemaxis.adaptors.meshio import adaptor, reference
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation

ROOT = Path(__file__).resolve().parents[1]


def refused(action, code='VERIFICATION_FAILED'):
    try: action()
    except SchemaxisError as error:
        assert error.fault.code == code, error.fault.to_dict()
        return code
    raise AssertionError('invalid input/evidence accepted')


def literal(directory, extension, scale):
    # Independent literal expectations: never derive these from native summaries.
    mesh = reference.parse((directory/('mesh.'+extension)).read_bytes(), extension)
    expected = {
        'points': [[10*scale,20*scale,30*scale],[12*scale,20*scale,30*scale],[10*scale,23*scale,30*scale],[10*scale,20*scale,34*scale],[12*scale,23*scale,30*scale]],
        'cells': [['triangle',[0,1,2]],['tetra',[0,1,2,3]],['triangle',[1,4,2]]],
        'pointData': {'node_id': [[101],[203],[307],[409],[503]], 'displacement': [[1,2,3],[-1,0,1],[.5,.25,-.5],[3,2,1],[0,0,0]]},
        'cellData': {'region': [[7],[9],[11]], 'direction': [[1,0,0],[0,1,0],[0,0,-1]]}}
    reference.compare(expected, mesh)
    return {'points': 5, 'orderedCells': 3, 'pointArrays': 2, 'cellArrays': 2, 'expectedVolume': 4*scale**3}


def refresh(directory):
    receipt = adaptor.read(directory, 'verification.json')
    prepared = adaptor._native_plan(adaptor.read(directory, 'authored.json'))
    receipt['artifacts'] = adaptor.artifacts(directory, prepared)
    receipt['evidence'] = {name: adaptor.digest(directory, name) for name in receipt['evidence']}
    atomic_json(directory/'verification.json', receipt)
    from schemaxis.publication_metadata import finalise
    finalise(directory)


def hostile(directory):
    saved = {p:p.read_bytes() for p in directory.rglob('*') if p.is_file()}; report = {}
    def restore():
        for path in directory.glob('mesh*'):
            if path not in saved: path.unlink()
        for path, data in saved.items(): path.write_bytes(data)
    def change_text(name, before, after):
        path=directory/name; content=path.read_text(); assert before in content; path.write_text(content.replace(before,after,1))
    def change_native():
        for name in ('convert.stdout','readback.stdout'):
            value=adaptor.read(directory,name);value['mesh']['pointData']['node_id'][0][0]=999;atomic_json(directory/name,value)
    def bind_source():
        path=directory/'source.vtu';path.write_bytes(path.read_bytes()+b'\n')
        data=adaptor.read(directory,'capture.json');data.update(bytes=path.stat().st_size,sha256=adaptor.digest(directory,'source.vtu'));atomic_json(directory/'capture.json',data)
    changes = {
        'changed-output-field-refreshed': lambda: change_text('mesh.vtk','101','999'),
        'changed-output-topology-refreshed': lambda: change_text('mesh.vtk','3\n0\n1\n2','3\n1\n0\n2'),
        'changed-both-native-fields-refreshed': change_native,
        'source-rebound-refreshed': bind_source,
        'unexpected-mesh-publication': lambda: (directory/'mesh.extra').write_text('extra'),
        'unexpected-metadata-sidecar': lambda: (directory/'mesh.extra.metadata.json').write_text('{}'),
        'trusted-worker-refreshed': lambda: (directory/'native-worker.py').write_text(adaptor.worker_source()+'\n# altered\n'),
    }
    for name, action in changes.items():
        try:
            action();refresh(directory);report[name]=refused(lambda:adaptor.verify(directory))
        finally:restore()
    assert adaptor.verify(directory)['verified']
    return report


def input_probes(directory, document, executable):
    source=Path(document['source']).read_bytes();report={}
    replacements={
        'inverted-tetra': (b'0 1 2 0 1 2 3 1 4 2',b'0 1 2 1 0 2 3 1 4 2'),
        'compressed-payload': (b'format="ascii"',b'format="binary"'),
        'unsupported-topology': (b'5 10 5',b'5 12 5'),
        'extra-metadata': (b'</Piece>',b'<FieldData/></Piece>'),
        'entity-declaration': (b'<VTKFile',b'<!DOCTYPE VTKFile [<!ENTITY x "boom">]><VTKFile'),
        'integer-storage-overflow': (b'Name="types" format="ascii">5',b'Name="types" format="ascii">261'),
    }
    for name,(a,b) in replacements.items():
        path=directory/(name+'.vtu');path.write_bytes(source.replace(a,b))
        report[name]=refused(lambda:adaptor.run({**document,'source':str(path)},directory/(name+'-run'),executable=executable),'INVALID_MESH_CONTENT')
    # A host-readable source with a numeric value meshio cannot silently change:
    # Float32 rounding is independently interpreted at declared IEEE precision.
    path=directory/'float32.vtu';path.write_bytes(source.replace(b'type="Float64" Name="displacement"',b'type="Float32" Name="displacement"').replace(b'1 2 3 -1',b'0.1 2 3 -1'))
    result=adaptor.run({**document,'source':str(path),'targetFormat':'vtu'},directory/'float32-run',executable=executable)
    assert result['verified'];report['float32-declared-precision']='verified'
    # Deliberately nonround double values plus a large nonzero origin exercise
    # meshio's ~12-significant-digit ASCII VTU writer. Geometry remains several
    # units wide so loss of tiny geometry at large origins is not disguised.
    import xml.etree.ElementTree as ET
    tree=ET.fromstring(source)
    positions=[[1234567.891234567,20,30],[1234569.891234567,20,30],[1234567.891234567,23,30],[1234567.891234567,20,34],[1234569.891234567,23,30]]
    tree.find('.//Points/DataArray').text=' '.join(str(v) for row in positions for v in row)
    tree.find('.//PointData/DataArray[@Name="displacement"]').text='1.23456789012345 2 3 -1 0 1 0.5 0.25 -0.5 3 2 1 0 0 0'
    tree.find('.//CellData/DataArray[@Name="direction"]').text='1.23456789012345 0 0 0 1 0 0 0 -1'
    path=directory/'precision.vtu';path.write_bytes(ET.tostring(tree))
    result=adaptor.run({**document,'source':str(path),'targetFormat':'vtu','targetUnits':'mm'},directory/'precision-run',executable=executable)
    assert result['verified']
    output=reference.vtu((directory/'precision-run/mesh.vtu').read_bytes())
    expected=reference.vtu(path.read_bytes());reference.compare(expected,output)
    assert output['pointData']['displacement'][0][0] != expected['pointData']['displacement'][0][0]
    report['nonround-large-origin-precision']={'verified':True,'relativeTolerance':1e-11,'absoluteTolerance':1e-14,'largestCoordinateError':max(abs(a-b) for pa,pb in zip(expected['points'],output['points']) for a,b in zip(pa,pb))}
    # Deliberately exercise the real native parser separately, bypassing host
    # preflight only in this qualification fixture. This is not authored API.
    for name,data in [('native-malformed',b'<not-a-vtu>'),('native-unsupported',source.replace(b'5 10 5',b'5 9 5'))]:
        work=directory/name;work.mkdir();(work/'source.vtu').write_bytes(data)
        (work/'native-worker.py').write_text(adaptor.worker_source())
        atomic_json(work/'native-config.json',{'sourceFormat':'vtu','targetFormat':'vtk','factor':.001})
        process=subprocess.run([executable,'-I',str(work/'native-worker.py'),'convert'],cwd=work,capture_output=True,timeout=15,env={'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','PATH':'/usr/bin:/bin'})
        assert process.returncode != 0 and not (work/'mesh.vtk').exists()
        (work/'stdout').write_bytes(process.stdout);(work/'stderr').write_bytes(process.stderr)
        report[name]={'exitCode':process.returncode,'outputAbsent':True}
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--meshio',type=Path,required=True);parser.add_argument('--output-directory',type=Path,required=True)
    parser.add_argument('--register',action='store_true');args=parser.parse_args()
    directory=args.output_directory.resolve();directory.mkdir(parents=True,exist_ok=False)
    # Preserve the venv symlink path: resolving python itself would escape it.
    executable=str(args.meshio.absolute());locations={'meshio':executable};report={'verified':False}
    try:
        receipt=qualify(adaptor.VERSION,directory/'kit',native=True,root=ROOT,locations=locations,timeout=30,wall_timeout=60)
        report['kit']={'verified':receipt['verified'],'lifecycle':receipt['lifecycle'],'cases':[c['id'] for c in receipt['cases']]}
        report['literal']=[literal(directory/'kit/millimetres-to-metres','vtk',.001),literal(directory/'kit/metres-to-millimetres','vtu',1)]
        report['hostile']=hostile(directory/'kit/millimetres-to-metres')
        document=json.loads((ROOT/'examples/schemaxis/meshio-convert.json').read_text());document['source']=str(ROOT/'examples/schemaxis/fixtures/meshio/mixed.vtu')
        report['inputs']=input_probes(directory,document,executable)
        cancel=threading.Event();active=directory/'active-cancel';observed=[]
        import xml.etree.ElementTree as ET
        tree=ET.fromstring(Path(document['source']).read_bytes());piece=tree.find('.//Piece')
        count=50000;piece.set('NumberOfCells',str(count))
        piece.find('Cells/DataArray[@Name="connectivity"]').text='0 1 2 '*count
        piece.find('Cells/DataArray[@Name="offsets"]').text=' '.join(str(3*i) for i in range(1,count+1))
        piece.find('Cells/DataArray[@Name="types"]').text='5 '*count
        piece.find('CellData/DataArray[@Name="region"]').text='7 '*count
        piece.find('CellData/DataArray[@Name="direction"]').text='1 0 0 '*count
        active_source=directory/'active-source.vtu';active_source.write_bytes(ET.tostring(tree))
        def trigger():
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                if (active/'convert-inputs.json').exists():observed.append('native process consumed inputs');cancel.set();return
                time.sleep(.001)
            cancel.set()
        thread=threading.Thread(target=trigger);thread.start()
        try:
            with allocation({'threads':1,'ranks':1},cancel):
                report['activeCancellation']=refused(lambda:adaptor.run({**document,'source':str(active_source)},active,executable=executable,timeout=20),'RUNNER_CANCELLED')
        finally:thread.join(timeout=11)
        assert observed
        source=directory/'workflow-source.vtu';shutil.copyfile(document['source'],source);document['source']=str(source)
        graph={'version':'schemaxis.workflow/1','operations':[{'id':'outbound','document':document},{'id':'return','document':{**document,'source':{'$artifact':'outbound','index':0},'sourceFormat':'vtk','targetFormat':'vtu','sourceUnits':'m','targetUnits':'mm'}}]}
        first=workflow.execute(graph,directory/'workflow',locations=locations,timeout=30);assert workflow.verify(directory/'workflow')['verified']
        second=workflow.execute(graph,directory/'workflow',locations=locations,timeout=30,resume=True);assert all(job['reused'] for job in second['jobs'])
        source.write_bytes(source.read_bytes()+b'\n')
        changed=workflow.execute(graph,directory/'workflow',locations=locations,timeout=30,resume=True);assert not changed['jobs'][0]['reused'];assert workflow.verify(directory/'workflow')['verified']
        report['workflow']={'baseline':first['status'],'unchangedReused':True,'samePathChangedBytesReused':False,'handoff':'Verified VTK artifact consumed by reverse VTU conversion.'}
        study=copy.deepcopy(document);study['axes']=[{'name':'unit','values':['m','cm']}];study['targetUnits']={'$axis':'unit'}
        study['definitions']={'format':'vtk'};study['targetFormat']={'$document':'/definitions/format'}
        result=adaptor.run(study,directory/'study',executable=executable,timeout=30);assert len(result['states'])==2 and adaptor.verify(directory/'study')['verified']
        report['composition']={'states':2,'verified':True}
        if args.register:register(directory/'kit/qualification.json')
        report['verified']=True
    finally:atomic_json(directory/'acceptance.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
