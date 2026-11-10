"""Prepare and independently check the editable ParaView state bundle example.

``prepare WORK`` writes a small synthetic VTK XML surface (a warped plate with
a point pressure field), adopts it with ``schemaxis input adopt`` and writes
``WORK/workflow.json``: captured surface -> clip (nondefault origin/normal) ->
styled scene (pressure colouring, titled legend) with ``"stateBundle": true``.
Run it with ``schemaxis run WORK/workflow.json OUT``.

``check OUT`` independently rereads the retained evidence: the bundle holds
exactly state.pvsm, bundle.json and one pinned capture (resource.json plus the
copied dataset) per reader; digests and the capture manifest match; the run
rebound the reader to that capture before the image; the .pvsm names only the
bundle copy; and the fresh-process reload of a relocated copy, with the original
bundle withheld and data search restricted to the copy, reproduced the pipeline,
the nondefault clip plane, observations, appearance, lookup-table points,
legend, view size, view time and camera. It then prints the GUI steps.
"""
import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

NX, NY = 13, 9


def surface():
    points, pressure, polys = [], [], []
    for j in range(NY):
        for i in range(NX):
            x, y = i / (NX - 1) * 2 - 1, j / (NY - 1) - 0.5
            z = 0.15 * math.sin(math.pi * x) * math.cos(math.pi * y)
            points.append(f'{x:.6f} {y:.6f} {z:.6f}')
            pressure.append(f'{101325 + 500 * x * x - 300 * y:.3f}')
    for j in range(NY - 1):
        for i in range(NX - 1):
            a = j * NX + i
            polys.append(f'{a} {a + 1} {a + NX + 1} {a + NX}')
    offsets = ' '.join(str(4 * (k + 1)) for k in range(len(polys)))
    return f'''<?xml version="1.0"?>
<VTKFile type="PolyData" version="1.0" byte_order="LittleEndian">
  <PolyData>
    <Piece NumberOfPoints="{len(points)}" NumberOfPolys="{len(polys)}">
      <PointData Scalars="pressure">
        <DataArray type="Float64" Name="pressure" format="ascii">{' '.join(pressure)}</DataArray>
      </PointData>
      <Points>
        <DataArray type="Float64" NumberOfComponents="3" format="ascii">{' '.join(points)}</DataArray>
      </Points>
      <Polys>
        <DataArray type="Int64" Name="connectivity" format="ascii">{' '.join(polys)}</DataArray>
        <DataArray type="Int64" Name="offsets" format="ascii">{offsets}</DataArray>
      </Polys>
    </Piece>
  </PolyData>
</VTKFile>
'''


def workflow(reference):
    return {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'post', 'document': {
        'version': 'schemaxis/1',
        'nodes': [{'id': 'plate', 'filter': 'readSurface', 'options': {'files': [reference]}},
                  {'id': 'half', 'filter': 'clip', 'inputs': {'input': 'plate'},
                   'options': {'origin': [0.1, 0, 0], 'normal': [1, 0, 0]}}],
        'scenes': [{'id': 'editable',
                    'visible': {'half': {'field': ['POINTS', 'pressure'], 'preset': 'Cool to Warm',
                                         'legend': True, 'legendTitle': 'pressure (units unknown)',
                                         'representation': 'Surface With Edges'}},
                    'images': [{'id': 'view', 'size': [480, 360],
                                'cameras': [{'direction': [0.4, -1, 0.8], 'up': [0, 0, 1]}]}],
                    'stateBundle': True}]}}]}


def prepare(work):
    work = Path(work)
    (work / 'source').mkdir(parents=True)
    source = work / 'source' / 'plate.vtp'
    source.write_text(surface())
    adopted = json.loads(subprocess.run(
        [sys.executable, '-m', 'schemaxis', 'input', 'adopt', str(source), str(work / 'snapshot')],
        check=True, capture_output=True, text=True).stdout)
    reference = {**adopted['reference'], 'origin': 'synthetic warped plate written by check_state_bundle.py'}
    (work / 'workflow.json').write_text(json.dumps(workflow(reference), indent=2) + '\n')
    return {'workflow': str(work / 'workflow.json'), 'snapshot': adopted['snapshot'], 'digest': adopted['digest']}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def close(a, b):
    return all(abs(x - y) <= 1e-9 * max(1, abs(y)) for x, y in zip(a, b)) and len(a) == len(b)


def check(result):
    operation = Path(result) / 'post'
    receipt = json.loads((operation / 'verification.json').read_text())
    assert receipt['status'] == 'succeeded' and receipt['verified'] is True
    bundles = [a for a in receipt['artifacts'] if a['identity']['kind'] == 'state-bundle']
    image = next(a for a in receipt['artifacts'] if a['identity']['kind'] == 'image')
    assert len(bundles) == 1, bundles
    artifact = bundles[0]
    state = Path(artifact['file'])
    bundle = state.parent
    manifest = json.loads((bundle / 'bundle.json').read_text())
    member, = manifest['members']
    # Publication metadata companions are allowed only where the committed
    # publication manifest lists them, and only beside state.pvsm/bundle.json.
    published = json.loads((operation / 'publication-metadata.json').read_text())['publications']
    companions = {(operation / entry['metadata']).resolve() for entry in published}
    entries = list(bundle.rglob('*'))
    assert not any(p.is_symlink() for p in entries)
    found = {p.relative_to(bundle).as_posix() for p in entries if p.is_file() and p.resolve() not in companions}
    assert all(c.parent == bundle.resolve() for c in companions if c.is_relative_to(bundle.resolve()))
    assert found == {'state.pvsm', 'bundle.json', 'data/plate/resource.json', 'data/plate/data/plate.vtp'}, found
    assert member['path'] == 'data/plate/data/plate.vtp' and member['resource'] == 'data/plate', member
    assert sha(state) == manifest['stateSha256'] == artifact['sha256']
    assert sha(bundle / 'bundle.json') == artifact['manifestSha256']
    assert [f['path'] for f in artifact['files']] == ['bundle.json']
    assert artifact['capturedInputs'] == [{k: member[k] for k in ('node', 'resource', 'resourceSha256',
                                           'resourceDigest', 'path', 'sha256', 'bytes')}]
    # The pinned capture uses the shared resource manifest format.
    resource = json.loads((bundle / 'data/plate/resource.json').read_text())
    assert sha(bundle / 'data/plate/resource.json') == member['resourceSha256']
    assert resource['version'] == 'schemaxis.resource/1' and resource['kind'] == 'file'
    assert resource['digest'] == member['resourceDigest']
    assert resource['files'] == [{'path': 'plate.vtp', 'size': member['bytes'], 'sha256': member['sha256']}]
    assert sha(bundle / member['path']) == member['sha256']
    assert '/snapshot/data/' in member['origin']
    # The reader was rebound to the capture before any publication consumed it.
    visit = receipt['states'][0]
    assert visit['inputRebinding']['plate']['captured'] == str(bundle / member['path'])
    assert visit['inputRebinding']['plate']['origin'] == member['origin'] == visit['effective']['plate']['files'][0]
    text = state.read_text()
    assert member['origin'] not in text
    assert str(bundle / member['path']) in text
    assert list(manifest['pipeline']) == ['plate', 'half']
    half = manifest['pipeline']['half']
    assert half['xmlName'] == 'Clip' and half['inputs'] == ['Input=plate:0'], half
    assert manifest['pipeline']['plate']['xmlName'] == 'XMLPolyDataReader'
    plane = {entry['option']: entry['value'] for entry in half['properties']}
    assert close(plane['origin'], [0.1, 0, 0]) and close(plane['normal'], [1, 0, 0]), plane
    assert manifest['units'] == 'unknown' and manifest['frame'] == 'unknown'
    assert manifest['camera'] == image['camera']
    assert manifest['viewSize'] == image['dimensions'][:2] == [480, 360]
    assert manifest['appearance']['half']['representation'] == 'Surface With Edges'
    assert manifest['appearance']['half']['colour'] == ['POINTS', 'pressure']
    colour = manifest['presentation']['half']
    assert colour['legendVisible'] is True and colour['legendTitle'] == 'pressure (units unknown)'
    assert colour['logScale'] is False
    pressure = manifest['observations']['half']['fields']['POINTS']['pressure']['range']
    assert close([colour['points'][0], colour['points'][-4]], pressure), (colour['points'], pressure)
    proof = json.loads(bundle.with_name(bundle.name + '.reload.json').read_text())
    assert proof['status'] == 'succeeded' and proof['verified'] is True
    assert proof['withheld'] == {'path': str(bundle), 'absentDuringReload': True}
    for pid in (proof['processId'], manifest['processId']):
        assert type(pid) is int and pid > 0
    assert proof['processId'] != manifest['processId']
    relocated = Path(proof['relocatedBundle'])
    assert relocated != bundle and not relocated.exists(), 'relocated copy should be disposed of'
    assert proof['loadOptions'] == {'dataDirectory': str(relocated / 'data'), 'restrictToDataDirectory': True}
    assert proof['pipeline']['plate']['fileProperties'] == {'FileName': [str(relocated / member['path'])]}
    assert proof['pipeline']['half']['fileProperties'] == {}
    assert proof['pipeline']['half']['xmlName'] == 'Clip' and proof['pipeline']['half']['inputs'] == ['Input=plate:0']
    reloaded = {entry['option']: entry['value'] for entry in proof['pipeline']['half']['properties']}
    assert close(reloaded['origin'], plane['origin']) and close(reloaded['normal'], plane['normal']), reloaded
    for node, observed in manifest['observations'].items():
        loaded = proof['observations'][node]
        assert loaded['points'] == observed['points'] and loaded['cells'] == observed['cells'], node
        assert close(loaded['bounds'], observed['bounds'])
        assert loaded['fields'].keys() == observed['fields'].keys()
    assert manifest['observations']['plate']['points'] == NX * NY
    assert 0 < manifest['observations']['half']['points'] < NX * NY
    assert proof['appearance'] == manifest['appearance']
    assert proof['presentation']['half']['legendVisible'] is True
    assert proof['presentation']['half']['legendTitle'] == colour['legendTitle']
    assert close(proof['presentation']['half']['points'], colour['points'])
    assert proof['viewSize'] == manifest['viewSize']
    # Bind the saved scene and time to the authored scene, the visited time and the image, not to each other.
    assert manifest['scene'] == artifact['identity']['scene'] == visit['scene'] == 'editable', manifest['scene']
    planned = visit['visit']['time']
    for observed in (manifest['time'], manifest['viewTime'], image['viewTime'], proof['viewTime']):
        assert abs(observed - planned) <= 1e-9 * max(1, abs(planned)), (observed, planned)
    assert all(close(proof['camera'][key], manifest['camera'][key]) for key in ('position', 'focalPoint', 'up'))
    assert proof['runtimeIdentity']['version'] == manifest['runtimeIdentity']['version']
    return {'verified': True, 'bundle': str(bundle), 'runtime': manifest['runtimeIdentity'].get('version'),
            'points': {k: v['points'] for k, v in manifest['observations'].items()},
            'clip': plane, 'colourRange': [colour['points'][0], colour['points'][-4]],
            'viewSize': proof['viewSize'], 'viewTime': proof['viewTime'],
            'processes': {'saved': manifest['processId'], 'reloaded': proof['processId']},
            'openInParaView': manifest['openInParaView']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('action', choices=('prepare', 'check'))
    parser.add_argument('directory')
    args = parser.parse_args()
    print(json.dumps(prepare(args.directory) if args.action == 'prepare' else check(args.directory), indent=2))
