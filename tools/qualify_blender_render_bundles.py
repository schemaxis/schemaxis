"""Public A/B/C bundle qualification with literal geometry and raw EXR oracles.

No expectations are learned from receipts or rendered output. Only file location
and the independent EXR decoder are shared with the production implementation.
"""
import argparse
import ast
import copy
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess

from schemaxis.adaptors.blender.adaptor import run, verify
from schemaxis.configuration import location_context
from schemaxis.adaptors.blender.exr_output import inspect
from blender_surface_evidence import identity, verify_identity
import blender_bundle_oracles as O

EXAMPLES = Path(__file__).resolve().parents[1]/'docs/examples'


def fixture(name, examples=EXAMPLES):
    return json.loads((Path(examples)/f'blender-render-bundles-{name}.json').read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def crypto_hash(text):
    """Independent MurmurHash3 x86/32, standard seed0 UTF-8 name convention."""
    data = text.encode(); mask = 0xffffffff; value = 0
    def rot(v, n): return ((v << n) | (v >> (32-n))) & mask
    padded = data + b'\0'*((-len(data)) % 4)
    words = list(struct.unpack('<'+'I'*(len(padded)//4), padded))
    for word in words[:len(data)//4]:
        word = rot(word*0xcc9e2d51 & mask, 15)*0x1b873593 & mask
        value = (rot(value ^ word, 13)*5+0xe6546b64) & mask
    if len(data) % 4:
        value ^= rot(words[-1]*0xcc9e2d51 & mask, 15)*0x1b873593 & mask
    value ^= len(data); value ^= value >> 16; value = value*0x85ebca6b & mask
    value ^= value >> 13; value = value*0xc2b2ae35 & mask; value ^= value >> 16
    return f'{value:08x}'


def rank(group, name):
    value = int(crypto_hash(name), 16)
    if (value >> 23) & 255 in (0, 255): value ^= 1 << 23
    return {'idChannel': group+'00.r', 'coverageChannel': group+'00.g',
            'idBits': f'{value:08x}', 'coverage': 1, 'tolerance': 2e-6}


def channels(**groups):
    return [name+'.'+suffix for name, suffixes in groups.items() for suffix in suffixes]


def material_manifest(*authored):
    # Fixed Cycles 5.2.3 enumerates ALL scene shaders, including its five
    # fallback shaders, rather than only surfaces with nonzero matte coverage.
    # Official intern/cycles/scene/shader.cpp:701-769,832-846. The adaptor also
    # declares its fixed AREA light even when energy is zero (native.configure).
    names = ('default_surface', 'default_volume', 'default_light',
             'default_background', 'default_empty', '__schemaxis_light', *authored)
    return {name: crypto_hash(name) for name in names}


def bundle(packet, identity, output, frame):
    packet = Path(packet).absolute()
    records = json.loads((packet/'verification.json').read_text())['artifacts']
    found = [r for r in records if r.get('kind') == 'renderBundle' and
             (r.get('bundle'), r.get('output'), r.get('frame')) == (identity, output, frame)]
    assert len(found) == 1, (identity, output, frame, found)
    path = Path(found[0]['file']); assert path.parent == packet/'renders/bundles'
    assert path.is_file() and not path.is_symlink()
    assert digest(path) == found[0]['sha256']
    return path


def analysis_expectations(frame):
    assert frame in (1, 12)
    n = math.sqrt(34); normal = [.5, 0, math.sqrt(3)/2]
    # Literal EulerY atan(5/3), not the old Z-up look-at fixture's basis.
    camera = {'origin': [5, 0, 3], 'right': [3/n, 0, -5/n], 'up': [0, 1, 0],
              'forward': [-5/n, 0, -3/n], 'halfWidth': 18/28, 'halfHeight': 18/28}
    plane = {'normal': normal, 'offset': normal[2]*(0 if frame == 1 else .5)}
    regions = []
    for index, pixel in enumerate(([64, 64], [70, 50], [40, 88])):
        regions.append({'id': 'interior-'+str(index), 'pixel': pixel,
            # 300 is constant at every source vertex. This prospective bound is
            # below eight float32 ULPs, allowing interpolation/filter accumulation.
            'values': {'temperature.V': 300}, 'tolerance': 2e-4,
            'geometry': {'plane': plane, 'worldNormal': normal,
                'positionChannels': ['position.'+c for c in 'XYZ'],
                'normalChannels': ['normal.'+c for c in 'XYZ'], 'depthChannel': 'depth.V',
                'tolerance': 2e-5, 'pixelRadius': 3},
            'matteRanks': [rank('objectMatte_matte', 'panel'), rank('materialMatte_matte', 'finish')]})
    return {'size': [128, 128], 'camera': camera, 'regions': regions,
        'channels': channels(combined='RGBA', depth='V', position='XYZ', normal='XYZ', temperature='V',
            objectMatte_matte00='rgba', objectMatte_matte01='rgba',
            materialMatte_matte00='rgba', materialMatte_matte01='rgba'),
        # Cycles exports a World background-light Object with its node type's
        # default name "object": blender/light.cpp:87-108, graph/node.cpp:18-28.
        'manifests': {'objectMatte_matte': {name: crypto_hash(name) for name in
                                           ('panel', '__schemaxis_light', 'object')},
                      'materialMatte_matte': material_manifest('finish')}}


def analysis_oracle(path, frame):
    expected = analysis_expectations(frame); result = O.verify(path, expected)
    samples = inspect(path, samples=[r['pixel'] for r in expected['regions']])['samples']
    details = []
    for region in expected['regions']:
        x, y = region['pixel']; point = samples[f'{x},{y}']
        position = [point['position.'+c]['value'] for c in 'XYZ']
        delta = [v-o for v, o in zip(position, expected['camera']['origin'])]
        optical = O.dot(delta, expected['camera']['forward']); depth = point['depth.V']['value']
        assert abs(depth-optical) < 1e-5
        for axis, value in zip('XYZ', expected['regions'][0]['geometry']['worldNormal']):
            assert abs(point['normal.'+axis]['value']-value) <= 1e-6
        # The original fixed-runtime evidence bounds filter support by the
        # explicit asymmetric raster interval [pixel-2,pixel+3], not a fitted
        # numerical epsilon. ray_plane takes pixel-centre coordinates.
        depths = [O.ray_plane(expected['camera'], expected['size'], [px-.5, py-.5],
                  region['geometry']['plane'])['opticalZ'] for px in (x-2, x+3) for py in (y-2, y+3)]
        assert min(depths)-1e-5 <= depth <= max(depths)+1e-5
        euclidean = math.sqrt(O.dot(delta, delta))
        if [x, y] == [40, 88]: assert euclidean-optical > .3
        details.append({'pixel': [x, y], 'opticalZ': optical, 'euclidean': euclidean,
                        'literalRayFootprint': [min(depths), max(depths)]})
    return {'decoded': result, 'geometry': details, 'literalExpectations': expected}


def artist_expectations():
    regions = []
    for name, pixel, roughness, material in [('paint', [48, 64], .375, 'finish'), ('trim', [144, 64], .75, 'accent')]:
        regions.append({'id': name, 'pixel': pixel,
            'values': {'roughness.V': roughness, 'overrideRoughness.V': .25}, 'tolerance': 2e-6,
            'matteRanks': [rank('materials_matte', material)],
            'lightSums': [{'policy': 'linear-radiance-complete-disjoint-groups',
                'combined': 'beauty.'+c, 'groups': ['key.'+c, 'world.'+c], 'tolerance': 2e-5} for c in 'RGB']})
    regions.append({'id': 'actual-World-background', 'pixel': [96, 8],
        'values': {'studioTag.V': .125, 'warmTag.V': .875, 'key.R': 0, 'key.G': 0, 'key.B': 0,
                   'world.R': .015, 'world.G': .02, 'world.B': .025}, 'tolerance': 2e-6,
        'lightSums': [{'policy': 'linear-radiance-complete-disjoint-groups',
            'combined': 'beauty.'+c, 'groups': ['key.'+c, 'world.'+c], 'tolerance': 2e-5} for c in 'RGB']})
    return {'size': [192, 128], 'regions': regions,
        'channels': channels(beauty='RGBA', roughness='V', overrideRoughness='V', studioTag='V', warmTag='V',
                             key='RGBA', world='RGBA', materials_matte00='rgba', materials_matte01='rgba'),
        # This matte belongs to beauty, whose effective owners are finish and
        # accent. The inspection layer's override is not a beauty-layer shader.
        'manifests': {'materials_matte': material_manifest('finish', 'accent', 'key')}}


def artist_oracle(path):
    expected = artist_expectations(); result = O.verify(path, expected)
    samples = inspect(path, samples=[[48, 64], [144, 64], [96, 8]])['samples']
    for pixel in ('48,64', '144,64'):
        # Separate positive surface regions and the World-only background make
        # a key/world swap observable; recombination alone would not.
        assert all(samples[pixel]['key.'+c]['value'] > 0 and samples[pixel]['world.'+c]['value'] > 0 for c in 'RGB')
    return {'decoded': result, 'literalExpectations': expected, 'positiveDisjointSurfaceGroups': True}


def sub(a, b): return [x-y for x, y in zip(a, b)]
def cross(a, b): return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def assembly_triangles(source, frame):
    triangles = []
    for asset, shift, angle in [('left', -1.75, 0), ('right', 1.75, 0 if frame == 1 else math.pi/6)]:
        cs, sn = math.cos(angle), math.sin(angle)
        for obj in source['production']['objects']:
            vertices = [[cs*x-sn*y+shift, sn*x+cs*y, z] for x, y, z in obj['vertices']]
            for face in obj['faces']:
                for i in range(1, len(face)-1):
                    a, b, c = [vertices[j] for j in (face[0], face[i], face[i+1])]
                    e, f = sub(b, a), sub(c, a); normal = cross(e, f); length = math.sqrt(O.dot(normal, normal))
                    if length:
                        n = math.sqrt(52)
                        projected = [(128+32*v[0]-.5, 64-32*(4*v[1]+6*v[2])/n-.5) for v in (a, b, c)]
                        box = (min(v[0] for v in projected), max(v[0] for v in projected),
                               min(v[1] for v in projected), max(v[1] for v in projected))
                        triangles.append((asset, obj['id'], a, e, f, [x/length for x in normal], box))
    return triangles


def assembly_hit(triangles, pixel, selected=False):
    n = math.sqrt(52); right, up, forward = [1, 0, 0], [0, 4/n, 6/n], [0, 6/n, -4/n]
    x, y = pixel; u = (x+.5-128)/32; v = (64-y-.5)/32
    origin = [o+u*r+v*t for o, r, t in zip([0, -6, 4], right, up)]
    best = None
    for asset, name, a, e, f, normal, box in triangles:
        if not box[0] <= x <= box[1] or not box[2] <= y <= box[3]: continue
        if selected and name == 'Shaft': continue  # exclude and indirectOnly both suppress camera surfaces
        h = cross(forward, f); denominator = O.dot(e, h)
        if abs(denominator) < 1e-12: continue
        delta = sub(origin, a); q = cross(delta, e); s = O.dot(delta, h)/denominator; t = O.dot(forward, q)/denominator
        if s < 0 or t < 0 or s+t > 1: continue
        distance = O.dot(f, q)/denominator
        if distance <= 0 or best and distance >= best['depth']: continue
        best = {'asset': asset, 'part': name, 'depth': distance, 'normal': normal,
                'alpha': 0 if selected and (asset, name) == ('right', 'Housing') else 1}
    return best


def assembly_regions(source, frame):
    triangles = assembly_triangles(source, frame); result = []
    wanted = {(asset, part) for asset in ('left', 'right') for part in ('Housing', 'Shaft', 'Flange')}
    # Pure ray/triangle intersections against the authored packet establish
    # interior masks independently of native output, receipts and manifests.
    for y in range(12, 105):
        if not wanted: break
        for x in range(20, 238):
            hit = assembly_hit(triangles, [x, y]); key = (hit['asset'], hit['part']) if hit else None
            if key not in wanted: continue
            neighbourhood = [assembly_hit(triangles, [x+dx, y+dy]) for dx, dy in ((-1.5, -1.5), (-1.5, 1.5), (1.5, -1.5), (1.5, 1.5))]
            if any(not h or (h['asset'], h['part']) != key for h in neighbourhood): continue
            selected = assembly_hit(triangles, [x, y], True)
            selected_neighbours = [assembly_hit(triangles, [x+dx, y+dy], True) for dx, dy in ((-1.5, -1.5), (-1.5, 1.5), (1.5, -1.5), (1.5, 1.5))]
            alpha = selected['alpha'] if selected else 0
            if any((h['alpha'] if h else 0) != alpha for h in selected_neighbours): continue
            # Demonstrate camera exclusion of both shafts, not a ray that merely
            # exposes an unrelated opaque surface behind the removed shaft.
            if hit['part'] == 'Shaft' and alpha != 0: continue
            result.append({'id': '-'.join(key), 'pixel': [x, y],
                'values': {'complete.A': 1, 'selected.A': alpha}, 'tolerance': 2e-6,
                'matteRanks': [rank('objectMatte_matte', key[0]+'--'+key[1])],
                'literalCompletePart': key, 'literalSelectedAlpha': alpha})
            wanted.remove(key)
    # The slender shaft need not contain a whole filter footprint. Its exact
    # Crypto identity plus positive coverage is a stronger honest witness than
    # inventing rank0 coverage1. The selected layer must still expose background
    # throughout that footprint; native exact mesh/source checks remain separate.
    for key in sorted(wanted):
        if key[1] != 'Shaft': continue
        found = False
        for y in range(12, 105):
            if found: break
            for x in range(20, 238):
                hit = assembly_hit(triangles, [x, y])
                if not hit or (hit['asset'], hit['part']) != key: continue
                selected = [assembly_hit(triangles, [x+dx, y+dy], True)
                            for dx, dy in ((0, 0), (-1.5, -1.5), (-1.5, 1.5), (1.5, -1.5), (1.5, 1.5))]
                if any(h and h['alpha'] != 0 for h in selected): continue
                result.append({'id': '-'.join(key), 'pixel': [x, y],
                    'values': {'selected.A': 0}, 'tolerance': 2e-6,
                    'literalCompletePart': key, 'literalSelectedAlpha': 0,
                    'positiveCryptoCoverage': rank('objectMatte_matte', key[0]+'--'+key[1])['idBits']})
                found = True; break
        if found: wanted.remove(key)
    assert not wanted, ('no geometric mask witness for assembly part', frame, wanted)
    return result


def assembly_oracle(path, source, frame):
    regions = assembly_regions(source, frame)
    result = O.verify(path, {'size': [256, 128], 'regions': regions})
    # An owner-wide tag applies to every user of the selected original material,
    # not only the right Shaft selector. The right part witnesses discriminate it.
    samples = inspect(path, samples=[r['pixel'] for r in regions])['samples']
    for region in regions:
        point = samples[','.join(map(str, region['pixel']))]
        if 'positiveCryptoCoverage' in region:
            expected = struct.pack('<I', int(region['positiveCryptoCoverage'], 16)).hex()
            assert point['complete.A']['value'] > 0
            assert any(point[f'objectMatte_matte{level:02d}.'+identity]['bits'] == expected and
                       point[f'objectMatte_matte{level:02d}.'+coverage]['value'] > 0
                       for level in (0, 1) for identity, coverage in (('r', 'g'), ('b', 'a')))
        if region['literalCompletePart'][0] == 'right':
            point = samples[','.join(map(str, region['pixel']))]
            assert abs(point['ownerTag.V']['value']-.75) <= 2e-6
    return {'decoded': result, 'literalRegions': regions, 'rightOwnerWideTag': .75}


def native(executable, code, folder, *, timeout=120):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=False)
    script = folder/'check.py'
    ast.parse(code, filename=str(script)); compile(code, str(script), 'exec')
    script.write_text(code)
    process = subprocess.run([executable, '--background', '--factory-startup', '--disable-autoexec', '--threads', '2',
        '--python-exit-code', '1', '--python', str(script)], capture_output=True, text=True, timeout=timeout)
    (folder/'stdout.log').write_text(process.stdout); (folder/'stderr.log').write_text(process.stderr)
    assert process.returncode == 0, (folder, process.returncode, process.stdout[-3000:], process.stderr[-3000:])


def assembly_native(executable, packet, source, folder):
    """Literal unflattened local geometry and owner sharing, not scalar metrics."""
    target = Path(folder)/'observed.json'; reference = {o['id']: o for o in source['production']['objects']}
    code = 'import bpy,json,math\n'+f'bpy.ops.wm.open_mainfile(filepath={str(Path(packet)/"0000.blend")!r},use_scripts=False)\n'+f'original={reference!r}\nrecords=[]\n'+'''
for asset in ('left','right'):
    owners=[bpy.data.objects.get(asset+'--'+part) for part in ('Housing','Shaft','Flange')]
    assert all(o is not None and o.type=='MESH' for o in owners)
    assert len({o.data for o in owners})==3
    assert len({o.data.materials[0] for o in owners})==1
    for obj,part in zip(owners,('Housing','Shaft','Flange')):
        expected=original[part]
        assert len(obj.data.vertices)==len(expected['vertices']) and len(obj.data.polygons)==len(expected['faces'])
        assert [list(p.vertices) for p in obj.data.polygons]==expected['faces']
        for vertex,point in zip(obj.data.vertices,expected['vertices']):
            assert all(abs(a-b)<=1e-6 for a,b in zip(vertex.co,point))
        records.append({'asset':asset,'part':part,'object':obj.name,'mesh':obj.data.name,'material':obj.data.materials[0].name})
'''+f'open({str(target)!r},"w").write(json.dumps(records))\n'
    native(executable, code, folder)
    return json.loads(target.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blender', required=True); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--examples', type=Path, default=EXAMPLES)
    parser.add_argument('--phase', choices=['all', 'analysis', 'artist', 'assembly'], default='all')
    parser.add_argument('--reuse-analysis', type=Path,
                        help='Freshly verify an unchanged current-runtime analysis packet instead of reproducing it')
    parser.add_argument('--reuse-artist', type=Path,
                        help='Freshly verify an unchanged current-runtime artist packet instead of reproducing it')
    args = parser.parse_args(); out = args.output.absolute(); out.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', **identity(out, args.blender), 'phase': args.phase, 'checks': [], 'fixtures': {},
              'fixtureFiles': {p.name: digest(p) for p in args.examples.glob('blender-render-bundles-*.json')}}
    target = out/'summary.json'
    def record(case, **value):
        report['checks'].append({'case': case, **value}); target.write_text(json.dumps(report, indent=2)+'\n'); print(case+' PASS', flush=True)
    def execute(name, document):
        packet = out/name; report['fixtures'][name] = hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()
        run(document, packet, executable=args.blender, timeout=300)
        with location_context({'blender': args.blender}): assert verify(packet)['verified']
        return packet
    try:
        assert crypto_hash('panel') == 'b6f5bb0a' and crypto_hash('hello') == '248bfa47' and crypto_hash('foo') == 'f6a5c420'
        if args.phase in ('all', 'analysis'):
            document = fixture('analysis', args.examples)
            if args.reuse_analysis:
                packet = args.reuse_analysis.absolute()
                assert json.loads((packet/'authored.json').read_text()) == document
                assert digest(packet/'runtime.zip') == report['runtimeArchiveSha256']
                with location_context({'blender': args.blender}): assert verify(packet)['verified']
                report['fixtures']['analysis'] = hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()
                report['reusedAnalysis'] = {'directory': str(packet),
                    'pins': {str(p.relative_to(packet)): digest(p) for p in packet.rglob('*') if p.is_file()}}
            else:
                packet = execute('analysis', document)
            for frame in (1, 12): record('analysis-'+str(frame), literal=analysis_oracle(bundle(packet, 'science', 'numeric', frame), frame))
        if args.phase in ('all', 'artist'):
            document = fixture('artist', args.examples)
            if args.reuse_artist:
                packet = args.reuse_artist.absolute()
                assert json.loads((packet/'authored.json').read_text()) == document
                assert digest(packet/'runtime.zip') == report['runtimeArchiveSha256']
                with location_context({'blender': args.blender}): assert verify(packet)['verified']
                report['fixtures']['artist'] = hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()
                report['reusedArtist'] = {'directory': str(packet),
                    'pins': {str(p.relative_to(packet)): digest(p) for p in packet.rglob('*') if p.is_file()}}
            else:
                packet = execute('artist', document)
            record('artist', literal=artist_oracle(bundle(packet, 'finishes', 'layers', 1)))
        if args.phase in ('all', 'assembly'):
            source = fixture('assembly-source', args.examples); producer = execute('assembly-source', source)
            saved_source = producer/'0000.blend'; original_sha = digest(saved_source)
            document = fixture('assembly', args.examples)
            for asset in document['production']['assets']:
                authored = Path(asset['file'])
                # Rebase the example's source directory without silently
                # repairing a wrong public publication filename.
                assert authored.name == saved_source.name, (authored, saved_source)
                asset['file'] = str(producer/authored.name)
            packet = execute('assembly', document)
            for frame in (1, 12): record('assembly-'+str(frame), literal=assembly_oracle(bundle(packet, 'assembly', 'parts', frame), source, frame))
            record('unflattened-assembly', native=assembly_native(args.blender, packet, source, out/'native-assembly'), sourceNativeSHA=original_sha)
            assert digest(saved_source) == original_sha
        verify_identity(report, args.blender); report['status'] = 'passed'
    finally:
        if report['status'] == 'running': report['status'] = 'failed'
        target.write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__': main()
