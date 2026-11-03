# Copyright (C) 2026 David L F Gaden
"""Bounded native catalogue qualification in isolated processes.

Each receipt describes the tested fixture only; it is not all-options coverage.
Use --paraview PATH/TO/pvbatch --output-directory NEW_DIRECTORY.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def fixtures():
    cases = []
    sources = {
        'Sphere': {'Radius':2}, 'Cone': {'Resolution':16}, 'Cylinder': {'Resolution':16},
        'Box': {}, 'Disk': {}, 'Plane': {}, 'Line': {}, 'Arrow': {}, 'Axes': {},
        'Ellipse': {}, 'PointSource': {'NumberOfPoints':20}, 'Superquadric': {},
        'Wavelet': {'WholeExtent':[-3,3,-3,3,-3,3]}, 'OutlineSource': {},
        'Mandelbrot': {'WholeExtent':[0,8,0,8,0,8]}, 'a2DGlyph': {}, 'a3DText': {'Text':'Schemaxis'},
    }
    for operation, options in sources.items():
        cases.append({'id':operation, 'nodes':[{'id':'result','filter':'pv'+operation,'options':options}]})
    filters = {
        'Shrink': {'ShrinkFactor':0.7}, 'Elevation': {}, 'ExtractSurface': {},
        'GenerateSurfaceNormals': {}, 'Triangulate': {}, 'Clean': {}, 'FeatureEdges': {'ManifoldEdges':True, 'FeatureEdges':False},
        'ExtractEdges': {}, 'Outline': {}, 'OutlineCorners': {}, 'Smooth': {}, 'Decimate': {},
        'CellSize': {}, 'Connectivity': {}, 'Delaunay3D': {}, 'Delaunay2D': {},
        'GenerateIds': {}, 'Curvature': {}, 'MeshQuality': {}, 'CellCenters': {},
        'CellDatatoPointData': {}, 'PointDatatoCellData': {},
        'IntegrateVariables': {}, 'Tessellate': {}, 'LoopSubdivision': {'NumberofSubdivisions':1},
        'Subdivide': {'NumberofSubdivisions':1},
        'Clip': {'ClipType':{'type':'Sphere','options':{'Center':[0,0,0],'Radius':1.5}},'Invert':False},
        'Slice': {'SliceType':{'type':'Plane','options':{'Normal':[0,0,1]}}},
        'Calculator': {'Function':'coordsX','ResultArrayName':'x'},
    }
    for operation, options in filters.items():
        cases.append({'id':operation, 'nodes':[
            {'id':'source','filter':'pvSphere','options':{'Radius':2,'ThetaResolution':16,'PhiResolution':16}},
            {'id':'result','filter':'pv'+operation,'inputs':{'Input':'source'},'options':options}]})
    for case in cases:
        if case['id'] == 'CellDatatoPointData':
            case['nodes'].insert(1, {'id':'cells','filter':'pvPointDatatoCellData','inputs':{'Input':'source'}})
            case['nodes'][-1]['inputs']['Input'] = 'cells'
    return cases


def native(case, destination, runtime):
    sys.path.insert(0, str(runtime))
    from schemaxis.adaptors.paraview.filters import catalogue, validate_options
    from schemaxis.adaptors.paraview.native import ParaViewBackend, geometry
    declarations = catalogue()
    backend = ParaViewBackend()
    handles = {}
    observations = {}
    try:
        for node in case['nodes']:
            declaration = declarations[node['filter']]
            values = validate_options(declaration, node.get('options',{}), node['id'])
            inputs = {p:handles[v] for p,v in node.get('inputs',{}).items()}
            constructors = {k:v for k,v in values.items() if declaration['options'][k].get('constructor')}
            handle = backend.create(node['id'], declaration, inputs, constructors)
            handles[node['id']] = handle
            backend.configure(handle, declaration, values)
            backend.update(handle, 0)
            observations[node['id']] = backend.observe(handle)
        artifact = geometry(backend, handles['result'], destination/'result')
        return {'status':'passed', 'fixture':case, 'observations':observations, 'artifact':artifact,
                'scope':'specified options, native readback and numeric geometry round trip; serial only'}
    finally:
        for handle in reversed(list(handles.values())): backend.delete(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--paraview')
    parser.add_argument('--output-directory',type=Path,required=True)
    parser.add_argument('--case',type=Path)
    parser.add_argument('--runtime',type=Path)
    args=parser.parse_args()
    if args.case:
        result=native(json.loads(args.case.read_text()),args.output_directory,args.runtime)
        (args.output_directory/'receipt.json').write_text(json.dumps(result,indent=2)+'\n')
        return
    args.output_directory.mkdir(exist_ok=False)
    sys.path.insert(0, str(ROOT/'src'))
    from schemaxis.artifacts import runtime_archive
    runtime=args.output_directory/'runtime.zip'
    runtime.write_bytes(runtime_archive())
    runtime_hash=hashlib.sha256(runtime.read_bytes()).hexdigest()
    results=[]
    for case in fixtures():
        directory=args.output_directory/case['id']; directory.mkdir()
        path=directory/'case.json'; path.write_text(json.dumps(case))
        command=[args.paraview,'--force-offscreen-rendering',str(Path(__file__).resolve()),
                 '--case',str(path.resolve()),'--runtime',str(runtime.resolve()),'--output-directory',str(directory.resolve())]
        try:
            run=subprocess.run(command, capture_output=True,text=True,timeout=45)
            (directory/'stdout.log').write_text(run.stdout)
            (directory/'stderr.log').write_text(run.stderr)
            receipt=directory/'receipt.json'
            result={'id':case['id'],'status':'passed' if run.returncode==0 and receipt.exists() else 'failed',
                    'exitCode':run.returncode,'fixture':case,'runtimeSHA256':runtime_hash}
            if receipt.exists(): result['receiptSHA256']=hashlib.sha256(receipt.read_bytes()).hexdigest()
        except subprocess.TimeoutExpired:
            result={'id':case['id'],'status':'timeout','fixture':case}
        results.append(result)
        (args.output_directory/'summary.json').write_text(json.dumps(results,indent=2)+'\n')
        print(case['id'],result['status'],flush=True)

if __name__ == '__main__': main()
