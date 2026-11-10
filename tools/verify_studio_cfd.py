#!/usr/bin/env python3
# Copyright (C) 2026 David L. F. Gaden
"""Bounded serial native acceptance for CFD authoring; uses a generated one-cell case."""
import argparse
import json
from pathlib import Path
from schemaxis.adaptors.paraview.studio import inspect_input, peek_input


def create_case(case):
    mesh = case / 'constant/polyMesh'; mesh.mkdir(parents=True, exist_ok=True)
    def write(path, kind, body):
        path.write_text('FoamFile\n{\nversion 2.0; format ascii; class ' + kind + '; object ' + path.name + ';\n}\n' + body + '\n')
    write(mesh / 'points', 'vectorField', '8\n(\n(0 0 0) (1 0 0) (1 1 0) (0 1 0)\n(0 0 1) (1 0 1) (1 1 1) (0 1 1)\n)')
    write(mesh / 'faces', 'faceList', '6\n(\n4(0 3 2 1)\n4(4 5 6 7)\n4(0 1 5 4)\n4(1 2 6 5)\n4(2 3 7 6)\n4(3 0 4 7)\n)')
    write(mesh / 'owner', 'labelList', '6\n(0 0 0 0 0 0)')
    write(mesh / 'neighbour', 'labelList', '0\n(\n)')
    write(mesh / 'boundary', 'polyBoundaryMesh', '1\n(\nwalls\n{ type wall; nFaces 6; startFace 0; }\n)')
    for time in ('0', '1'):
        folder = case / time; folder.mkdir(exist_ok=True)
        for name, kind, dimensions, value in [('U', 'volVectorField', '[0 1 -1 0 0 0 0]', '(1 0 0)'), ('p', 'volScalarField', '[0 2 -2 0 0 0 0]', '2')]:
            write(folder / name, kind, f'dimensions {dimensions};\ninternalField uniform {value};\nboundaryField {{ walls {{ type zeroGradient; }} }}')
    marker = case / 'case.foam'; marker.touch()
    return marker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    marker = create_case(args.output / 'case')
    document = {'version': 'schemaxis/1', 'nodes': [
        {'id': 'case', 'filter': 'foam', 'options': {'file': str(marker.resolve()), 'regions': {'select': 'all'}, 'cellArrays': {'pattern': '^(U|p)$'}}},
        {'id': 'unfinished', 'filter': 'slice', 'options': {'$document': '/notReady'}}], 'scenes': []}
    peek = peek_input(document, 'case')
    assert peek['cellArrays'] == ['U', 'p'] and 'patch/walls' in peek['regions'], peek
    metadata = inspect_input(document, 'case', args.executable, args.output / 'metadata', prepare=True)
    assert set(metadata['cellArrays']) >= {'U', 'p'} and 'internalMesh' in metadata['regions'], metadata
    live = inspect_input(document, 'case', args.executable, args.output / 'live', geometry=True)
    assert live['observation']['cells'] > 0 and live['geometry']['objects'], live
    assert live['observation']['bounds'] == [0, 1, 0, 1, 0, 1], live['observation']
    assert document['nodes'][1]['options'] == {'$document': '/notReady'}, 'Inspection mutated the draft'
    result = {'verified': True, 'scope': 'Serial one-cell OpenFOAM case; metadata-only peek, native reader names, deferred selections and live tessellation with invalid downstream input.',
              'peek': peek, 'metadata': metadata, 'live': {k: v for k, v in live.items() if k != 'geometry'},
              'geometryObjects': len(live['geometry']['objects'])}
    (args.output / 'acceptance.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'verified': True, 'geometryObjects': result['geometryObjects'], 'output': str(args.output)}))


if __name__ == '__main__': main()
