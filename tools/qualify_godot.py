#!/usr/bin/env python3
"""Small CPU-only native qualification; writes results to a fresh directory."""
import argparse
import base64
import copy
import json
import math
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.godot import run, verify
from schemaxis.artifacts import atomic_json


def triangle():
    """Asymmetric, indexed triangle with independently known metre bounds."""
    raw = struct.pack('<9f3H', -1, 0, 0, 2, 0, 0, 0, 3, 0, 0, 1, 2)
    return {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}],
            'nodes': [{'mesh': 0}], 'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1}]}],
            'buffers': [{'uri': 'data:application/octet-stream;base64,'+base64.b64encode(raw).decode(), 'byteLength': len(raw)}],
            'bufferViews': [{'buffer': 0, 'byteLength': 36}, {'buffer': 0, 'byteOffset': 36, 'byteLength': 6}],
            'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 3, 'type': 'VEC3',
                           'min': [-1, 0, 0], 'max': [2, 3, 0]},
                          {'bufferView': 1, 'componentType': 5123, 'count': 3, 'type': 'SCALAR'}]}


def qualify(executable, directory, timeout=60, preview=False):
    directory = Path(directory).absolute()
    directory.mkdir(parents=True, exist_ok=False)
    examples = Path(__file__).resolve().parents[1]/'examples/schemaxis'
    primitives = json.loads((examples/'godot-primitives.json').read_text())
    if preview:
        primitives['preview'] = True
    results = {'primitives': run(primitives, directory/'primitives', executable, timeout)}
    source = directory/'triangle.gltf'
    atomic_json(source, triangle())
    imported = json.loads((examples/'godot-gltf.json').read_text())
    imported['nodes'][1]['options'].update(file=str(source), position=[2, 1, -3])
    results['gltf'] = run(imported, directory/'gltf', executable, timeout)
    readback = json.loads((directory/'gltf/reopened.json').read_text())['scene']['nodes']['imported']
    if not all(math.isclose(a, b, rel_tol=1e-5, abs_tol=2e-5)
               for a, b in zip(readback['bounds'], [1, 1, -3, 4, 4, -3])) or readback['triangles'] != 1:
        raise AssertionError('Independent glTF bounds/triangle check failed')
    fixed = copy.deepcopy(primitives)
    next(n for n in fixed['nodes'] if n['filter'] == 'camera')['options']['orbit'] = False
    results['fixedCamera'] = run(fixed, directory/'fixed-camera', executable, timeout)
    rejected = []
    project = directory/'primitives'
    receipt_path = project/'reopened.json'
    original = json.loads(receipt_path.read_text())
    mutations = {
        'bounds': lambda r: r['scene']['nodes']['block']['bounds'].__setitem__(0, -99),
        'nodeCount': lambda r: r['scene'].update(nodeCount=999),
        'material': lambda r: r['scene']['nodes']['block']['material'].update(roughness=0.123),
        'camera': lambda r: r['scene']['nodes']['view'].update(fov=10),
        'freshProcess': lambda r: r.update(pid=json.loads((project/'built.json').read_text())['pid']),
    }
    for label, mutate in mutations.items():
        altered = copy.deepcopy(original)
        mutate(altered)
        atomic_json(receipt_path, altered)
        try:
            verify(project)
        except SchemaxisError:
            rejected.append(label)
        else:
            raise AssertionError('Altered evidence accepted: '+label)
        finally:
            atomic_json(receipt_path, original)
    # The project can run its actual main scene with the trusted orbit script.
    import subprocess
    with (directory/'playback.log').open('w') as log:
        result = subprocess.run([str(executable), '--headless', '--path', str(project), '--quit-after', '3'],
                                stdout=log, stderr=subprocess.STDOUT, timeout=timeout, check=False)
    if result.returncode or 'ERROR:' in (directory/'playback.log').read_text():
        raise AssertionError('Main-scene playback failed; see playback.log')
    summary = {'verified': True, 'runtime': results['primitives']['runtime'], 'results': results,
               'rejectedTampering': rejected, 'mainScenePlayback': True,
               'graphicalPreview': preview,
               'limits': 'CPU construction/reopen/playback; optional Xvfb/Mesa PNG readback. No GUI interaction qualification.'}
    atomic_json(directory/'qualification.json', summary)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True)
    parser.add_argument('--directory', required=True, help='Fresh evidence directory')
    parser.add_argument('--timeout', type=float, default=60)
    parser.add_argument('--preview', action='store_true', help='Also qualify actual X11/software-OpenGL PNG rendering')
    arguments = parser.parse_args()
    print(json.dumps(qualify(arguments.executable, arguments.directory, arguments.timeout, arguments.preview), indent=2))
