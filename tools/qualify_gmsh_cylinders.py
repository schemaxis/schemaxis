#!/usr/bin/env python3
"""Bounded real-Gmsh acceptance of named cylindrical walls.

Covers the fully named sleeve, reference-driven changes, a FreeCAD STEP plate with
two equal bores, deviation-driven refinement, adopted STEP inputs, a native FreeCAD
revision, a meshio consumer and adversaries whose native evidence is rehashed.
Expected values are literals derived from the authored dimensions, not producer
output. This is source qualification: its membership and deviation arithmetic is
separate from the verifier but reads meshes with the product's MSH parser; the
independent readers are the meshio leg and a reviewer's separate oracle.
"""
import argparse
import copy
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
from collections import Counter

from schemaxis import workflow
from schemaxis.adaptors.gmsh import adaptor, mesh
from schemaxis.adaptors.gmsh.quality import assess
from schemaxis.artifacts import file_digest
from schemaxis.configuration import locations
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[1]
PI = math.pi
EXAMPLES = ROOT/'examples/schemaxis'


def load(name):
    return json.loads((EXAMPLES/name).read_text())


def partition(data, planes, cylinders, remainder=2):
    """Classify every boundary triangle by plain arithmetic; return counts per expected tag."""
    counts = Counter()
    for dimension, tag, vertices in data['cells']:
        if dimension != 2:
            continue
        points = [data['nodes'][n] for n in vertices]
        expected = remainder
        for plane_tag, axis, coordinate in planes:
            if all(abs(p['xyz'.index(axis)]-coordinate) < 1e-6 for p in points):
                expected = plane_tag; break
        else:
            for wall_tag, axis, centre, radius in cylinders:
                a = 'xyz'.index(axis); i, j = [k for k in range(3) if k != a]
                if (all(abs(math.hypot(p[i]-centre[i], p[j]-centre[j])-radius) < 1e-6 for p in points)
                        and max(p[a] for p in points)-min(p[a] for p in points) > 1e-6):
                    expected = wall_tag; break
        assert tag == expected, ('triangle tag', tag, 'expected', expected)
        counts[tag] += 1
    return counts


def rim_count(data, tag, axis, coordinate):
    a = 'xyz'.index(axis)
    nodes = {n for d, t, v in data['cells'] if d == 2 and t == tag for n in v if abs(data['nodes'][n][a]-coordinate) < 1e-6}
    return len(nodes)


def sampled_deviation(data, tag, axis, centre, radius, grid=24):
    """Largest radius-minus-nearest-approach over barycentric samples of each wall triangle."""
    a = 'xyz'.index(axis); i, j = [k for k in range(3) if k != a]
    worst = 0.0
    for dimension, physical, vertices in data['cells']:
        if dimension != 2 or physical != tag:
            continue
        p = [data['nodes'][n] for n in vertices]
        nearest = min(math.hypot(sum(w*p[m][i] for m, w in enumerate(b))-centre[i], sum(w*p[m][j] for m, w in enumerate(b))-centre[j])
                      for b in ((u/grid, v/grid, 1-(u+v)/grid) for u in range(grid+1) for v in range(grid+1-u)))
        worst = max(worst, radius-nearest)
    return worst


def summary_of(directory):
    return json.loads((Path(directory)/'mesh-summary.json').read_text())


def plate_cad(radius=4, thickness=8, holes=((15, 20), (45, 20))):
    nodes = [{'id': 'plate', 'filter': 'box', 'options': {'length': 60, 'width': 40, 'height': thickness}}]
    base = 'plate'
    for index, (x, y) in enumerate(holes):
        nodes.append({'id': 'hole%d' % index, 'filter': 'cylinder', 'options': {'radius': radius, 'height': thickness+2, 'origin': [x, y, -1]}})
        nodes.append({'id': 'cut%d' % index, 'filter': 'cut', 'inputs': {'base': base, 'tool': 'hole%d' % index}})
        base = 'cut%d' % index
    return {'version': 'schemaxis.freecad/1', 'units': 'mm', 'nodes': nodes, 'output': base}


def plate_workflow(radius=4, thickness=8, selector_radius=None):
    document = load('freecad-gmsh-bores.json')
    document['operations'][0]['document'] = plate_cad(radius, thickness)
    for group in document['operations'][1]['document']['nodes'][1]['options']['cylinderGroups']:
        group['radius'] = selector_radius or radius
    return document


def cli(*arguments):
    """Run the public CLI in the caller's Python and environment; an installed package is used when it is importable."""
    return subprocess.run([sys.executable, '-m', 'schemaxis', *arguments], check=True, capture_output=True, text=True, timeout=1200).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', required=True, type=Path)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--legacy', type=Path, help='directory of result directories produced by the baseline source')
    args = parser.parse_args()
    if args.config:
        os.environ['SCHEMAXIS_CONFIG'] = str(args.config.resolve())
    target = args.output_directory.resolve(); target.mkdir(parents=True, exist_ok=False)
    where = locations(); gmsh = where['gmsh']
    report = {'verified': False, 'cases': [], 'refusals': [], 'adversaries': []}

    def run(document, name, timeout=300):
        result = adaptor.run(document, target/name, executable=gmsh, timeout=timeout)
        assert adaptor.verify(target/name)['verified']
        return result

    def refuse(document, name, code, location=None, native=False, executor=None):
        try:
            (executor or (lambda: adaptor.run(document, target/name, executable=gmsh, timeout=300)))()
        except SchemaxisError as error:
            fault = error.fault
            assert fault.code == code, fault.to_dict()
            if location: assert fault.location.startswith(location), fault.to_dict()
            assert native or not (target/name).exists(), 'plan-time refusal must not start the native process'
            report['refusals'].append({'case': name, 'code': fault.code, 'location': fault.location})
            return fault
        raise AssertionError(name+' unexpectedly accepted')

    def sleeve_case(name, bore, outer, height, axis, origin, size):
        a = 'xyz'.index(axis)
        document = load('gmsh-named-sleeve.json'); document.pop('dimensions')
        solid, options = document['nodes'][0]['options'], document['nodes'][1]['options']
        solid.update(radius=outer, innerRadius=bore, height=height, axis=axis, origin=origin)
        for group in options['cylinderGroups']:
            group.update(axis=axis, centre=origin)
        options['cylinderGroups'][0]['radius'] = bore
        options['cylinderGroups'][1]['radius'] = outer
        options['size'] = size
        low, high = origin[a], origin[a]+height
        options['faceGroups'][0].update(axis=axis, coordinate=low)
        options['faceGroups'][1].update(axis=axis, coordinate=high)
        result = run(document, name)
        directory = target/name; data = mesh.read(directory/'result.msh'); s = summary_of(directory)
        assert s['groups'] == [{'dimension': 2, 'tag': t, 'name': n} for t, n in ((3, 'start'), (4, 'end'), (5, 'bore'), (6, 'outer'))]+[{'dimension': 3, 'tag': 1, 'name': 'sleeve'}]
        counts = partition(data, [(3, axis, low), (4, axis, high)], [(5, axis, origin, bore), (6, axis, origin, outer)])
        assert set(counts) == {3, 4, 5, 6}
        literal = PI*(outer**2-bore**2)*height
        assert abs(s['cadVolume']-literal) <= 1e-9*literal and abs(s['volume']-literal) <= 0.02*literal
        walls = {c['name']: c for c in s['cylinderChecks']}
        for wall, radius, side in (('bore', bore, 'inner'), ('outer', outer, 'outer')):
            lateral = 2*PI*radius*height
            assert walls[wall]['side'] == side and abs(walls[wall]['cadArea']-lateral) <= 1e-9*lateral
            assert abs(walls[wall]['unrolledArea']-lateral) <= 1e-9*lateral and walls[wall]['maximumVertexResidual'] < 1e-9
            assert walls[wall]['axialRange'] == [low, high] or all(abs(x-y) < 1e-6 for x, y in zip(walls[wall]['axialRange'], [low, high]))
            assert abs(sampled_deviation(data, 5 if wall == 'bore' else 6, axis, origin, radius)-walls[wall]['maximumChordDeviation']) < 5e-4
        cap = PI*(outer**2-bore**2)
        assert all(abs(g['area']-cap)/cap < 0.02 for g in s['boundaryGroups'] if g['name'] in ('start', 'end'))
        assert 2 not in {g['tag'] for g in s['groups'] if g['dimension'] == 2}
        report['cases'].append({'case': name, 'volume': s['cadVolume'], 'walls': walls, 'triangles': dict(counts), 'result': result['verified']})
        return directory

    try:
        a1 = sleeve_case('a1-sleeve', 2, 4, 8, 'x', [1, 2, 3], 0.7)
        assert math.isclose(summary_of(a1)['cadVolume'], 96*PI, rel_tol=1e-10)
        sleeve_case('a2-changed-radius', 2.5, 4, 8, 'x', [1, 2, 3], 0.7)
        assert math.isclose(summary_of(target/'a2-changed-radius')['cadVolume'], 78*PI, rel_tol=1e-10)
        sleeve_case('a2-changed-axis-placement', 2, 4, 8, 'z', [-3, 5, 2], 0.7)

        base = load('gmsh-named-sleeve.json'); base.pop('dimensions')
        base['nodes'][0]['options'].update(radius=4, innerRadius=2); [g.update(radius=r) for g, r in zip(base['nodes'][1]['options']['cylinderGroups'], (2, 4))]
        def edit(function):
            document = copy.deepcopy(base); function(document); return document
        cg = lambda d: d['nodes'][1]['options']['cylinderGroups']
        for label, function, code in (
                ('off-radius', lambda d: cg(d)[0].update(radius=2.01), 'INVALID_SELECTION'),
                ('wrong-side', lambda d: cg(d)[0].update(side='outer'), 'INVALID_SELECTION'),
                ('duplicate', lambda d: cg(d).append(dict(cg(d)[0], name='twin')), 'INVALID_SELECTION'),
                ('stale-literal', lambda d: d['nodes'][0]['options'].update(innerRadius=2.5), 'INVALID_SELECTION'),
                ('empty-remainder-reference', lambda d: d['nodes'][1]['options'].update(nearBoundaries=[{'boundary': 'unassigned', 'size': 0.5, 'distance': 1}]), 'INVALID_SELECTION')):
            document = edit(function)
            refuse(document, 'r-'+label, code)

        plate = target/'a3-plate'
        parent = workflow.execute(load('freecad-gmsh-bores.json'), plate, locations=where, timeout=600)
        assert workflow.verify(plate)['verified']
        jobs = {j['operation']: j for j in parent['jobs']}
        mesh_dir = Path(jobs['mesh']['directory']); data = mesh.read(mesh_dir/'result.msh'); s = summary_of(mesh_dir)
        literal = 19200-256*PI
        assert abs(s['cadVolume']-literal) <= 1e-9*literal
        walls = {c['name']: c for c in s['cylinderChecks']}
        for name in ('fixedBore', 'loadBore'):
            assert walls[name]['side'] == 'inner' and abs(walls[name]['cadArea']-64*PI) <= 1e-9*64*PI
        groups = {g['name']: g for g in s['boundaryGroups']}
        for name, centre in (('fixedBore', 15), ('loadBore', 45)):
            low, high = groups[name]['bounds'][:3], groups[name]['bounds'][3:]
            envelope = [centre-4, 16, 0, centre+4, 24, 8]
            assert all(e-1e-6 <= v for v, e in zip(low, envelope[:3])) and all(v <= e+1e-6 for v, e in zip(high, envelope[3:]))
            assert abs((low[0]+high[0])/2-centre) < 0.5 and low[2] == 0 and abs(high[2]-8) < 1e-6 and high[0]-low[0] > 7
        counts = partition(data, [(3, 'z', 0)], [(4, 'z', [15, 20, 0], 4), (5, 'z', [45, 20, 0], 4)], remainder=2)
        assert set(counts) == {2, 3, 4, 5}
        tags = {g['name']: g['tag'] for g in s['groups'] if g['dimension'] == 2}
        rims = {n: (rim_count(data, tags[n], 'z', 0), rim_count(data, tags[n], 'z', 8)) for n in ('fixedBore', 'loadBore')}
        edges = {b['name']: b['maximumEdgeLength']['maximum'] for b in s['quality']['boundaries']}
        sixteen = 4*(1-math.cos(PI/16))
        assert min(rims['loadBore']) >= 16 and walls['loadBore']['maximumChordDeviation'] <= sixteen, (rims, walls['loadBore'])
        assert min(rims['loadBore']) > max(rims['fixedBore']) and edges['loadBore'] < edges['fixedBore']
        assert walls['fixedBore']['maximumChordDeviation'] > sixteen
        assert 'base' in groups and abs(groups['base']['area']-(2400-32*PI)) <= 0.02*(2400-32*PI)
        surfaces = {(x['type'], x.get('axis'), x.get('radius'), x.get('coordinate')) for x in s['cadSurfaces']['surfaces']}
        assert ('cylinder', 'z', 4.0, None) in surfaces and ('plane', 'z', None, 0.0) in surfaces
        assert all('tag' not in x for x in s['cadSurfaces']['surfaces'])
        report['cases'].append({'case': 'a3-plate', 'volume': s['cadVolume'], 'rimEdgesBySide': rims,
                                'achievedMaximumEdge': edges, 'chordSegments': {k: v['chordSegmentsEquivalent'] for k, v in walls.items()}})

        before = {str(p.relative_to(plate)): file_digest(p) for p in sorted(plate.rglob('*')) if p.is_file()}
        changed = plate_workflow(radius=3.5, selector_radius=4)
        fault = refuse(changed, 'a3-stale-selector', 'INVALID_SELECTION', native=True,
                       executor=lambda: workflow.execute(changed, target/'a3-stale-selector', locations=where, timeout=600))
        assert any(abs(c['radius']-3.5) < 1e-9 for c in fault.observed['candidates']), fault.to_dict()
        fixed = plate_workflow(radius=3.5)
        recovered = target/'a3-recovered'
        done = workflow.execute(fixed, recovered, locations=where, timeout=600)
        assert workflow.verify(recovered)['verified']
        s2 = summary_of(next(j['directory'] for j in done['jobs'] if j['operation'] == 'mesh'))
        assert abs(s2['cadVolume']-(19200-196*PI)) <= 1e-9*19200
        assert all(abs(c['cadArea']-56*PI) <= 1e-9*56*PI for c in s2['cylinderChecks'])

        refine = load('freecad-gmsh-bores.json')
        options = refine['operations'][1]['document']['nodes'][1]['options']; options.pop('nearBoundaries'); options['size'] = 4
        refine['operations'][1]['document']['refinement'] = {'maxIterations': 6, 'reductionFactor': 0.7, 'minimumSize': 0.8, 'maxTetrahedra': 60000,
            'requirements': {'boundaryMaximumChordDeviation': [{'boundary': 'loadBore', 'maximum': 0.08}]}}
        refined = target/'a4-refined'
        done = workflow.execute(refine, refined, locations=where, timeout=900)
        assert workflow.verify(refined)['verified']
        study_dir = Path(next(j['directory'] for j in done['jobs'] if j['operation'] == 'mesh'))
        study = json.loads((study_dir/'study-summary.json').read_text())
        deviations = [next(c for c in summary_of(study_dir/a['directory'])['cylinderChecks'] if c['name'] == 'loadBore')['maximumChordDeviation'] for a in study['attempts']]
        chosen = study['selected']
        assert study['accepted'] and chosen > 0 and deviations[chosen] <= 0.08 < deviations[chosen-1], deviations
        for a, deviation in zip(study['attempts'], deviations):
            attempt = study_dir/a['directory']
            tag = next(g['tag'] for g in summary_of(attempt)['groups'] if g['name'] == 'loadBore')
            parsed = mesh.read(attempt/'result.msh')
            rim = min(rim_count(parsed, tag, 'z', 0), rim_count(parsed, tag, 'z', 8))
            assert deviation >= 4*(1-math.cos(PI/rim))*(1-1e-9), (deviation, rim)
        data = mesh.read(study_dir/study['attempts'][chosen]['directory']/'result.msh')
        loadtag = next(g['tag'] for g in summary_of(study_dir/study['attempts'][chosen]['directory'])['groups'] if g['name'] == 'loadBore')
        assert abs(sampled_deviation(data, loadtag, 'z', [45, 20, 0], 4)-deviations[chosen]) < 5e-4
        report['cases'].append({'case': 'a4-refined-plate', 'attemptDeviations': deviations, 'selected': chosen})

        rod = {'version': 'schemaxis.gmsh/1', 'units': 'mm', 'nodes': [
            {'id': 'solid', 'filter': 'cylinder', 'options': {'origin': [0, 0, 0], 'axis': 'z', 'radius': 3, 'height': 10}},
            {'id': 'mesh', 'filter': 'tetrahedral', 'inputs': {'input': 'solid'}, 'options': {
                'size': 1.0, 'algorithm': 'hxt', 'volumeName': 'rod', 'boundaryName': 'ends', 'volumeTolerance': 0.02,
                'cylinderGroups': [{'name': 'shaft', 'axis': 'z', 'centre': [0, 0, 0], 'radius': 3, 'side': 'outer'}]}}], 'output': 'mesh'}
        attempts = {}
        for limit in (0.05, 0.02):
            document = copy.deepcopy(rod)
            document['refinement'] = {'maxIterations': 8, 'reductionFactor': 0.7, 'minimumSize': 0.3, 'maxTetrahedra': 100000,
                'requirements': {'boundaryMaximumChordDeviation': [{'boundary': 'shaft', 'maximum': limit}]}}
            result = adaptor.run(document, target/('rod-%g' % limit), executable=gmsh, timeout=600)
            study = json.loads((target/('rod-%g' % limit)/'study-summary.json').read_text())
            shafts = [next(c for c in summary_of(target/('rod-%g' % limit)/a['directory'])['cylinderChecks'])['maximumChordDeviation'] for a in study['attempts']]
            chosen = study['selected']
            assert study['accepted'] and shafts[chosen] <= limit and (chosen == 0 or shafts[chosen-1] > limit), shafts
            for a, deviation in zip(study['attempts'], shafts):
                attempt = target/('rod-%g' % limit)/a['directory']
                parsed = mesh.read(attempt/'result.msh'); tag = next(g['tag'] for g in summary_of(attempt)['groups'] if g['name'] == 'shaft')
                rim = min(rim_count(parsed, tag, 'z', 0), rim_count(parsed, tag, 'z', 10))
                assert deviation >= 3*(1-math.cos(PI/rim))*(1-1e-9), (deviation, rim)
            attempts[limit] = len(study['attempts'])
        assert attempts[0.02] > attempts[0.05]
        report['cases'].append({'case': 'rod-hxt-deviation', 'attemptsByLimit': attempts})

        consumer = target/'consume.py'
        consumer.write_text('import json,sys,meshio\n'
            'm=meshio.read(sys.argv[1]); tag=m.cell_data.get("gmsh:physical") or m.cell_data.get("physicalTag")\n'
            'out={}\n'
            'for i,block in enumerate(m.cells):\n'
            '    out.setdefault(block.type,[]).extend([int(tag[i][k]),[m.points[n].tolist() for n in cell]] for k,cell in enumerate(block.data))\n'
            'json.dump(out,sys.stdout)\n')
        meshio_python = where.get('meshio')
        assert meshio_python, 'configure meshio for the independent consumer check'
        chosen_dir = Path(next(j['directory'] for j in done['jobs'] if j['operation'] == 'mesh'))
        study = json.loads((chosen_dir/'study-summary.json').read_text())
        pick = chosen_dir/study['attempts'][study['selected']]['directory']
        expected = mesh.read(pick/'result.msh')

        def consume(path):
            return json.loads(subprocess.run([meshio_python, str(consumer), str(path)], check=True, capture_output=True, text=True, timeout=120).stdout)
        def cells_by_type(dimension):
            names = {2: 'triangle', 3: 'tetra'}
            return {names[dimension]: [[t, [list(expected['nodes'][n]) for n in v]] for d, t, v in expected['cells'] if d == dimension]}
        msh, vtu = consume(pick/'result.msh'), consume(pick/'boundary.vtu')
        assert msh['triangle'] == cells_by_type(2)['triangle'] and msh['tetra'] == cells_by_type(3)['tetra'], 'meshio cell, tag or connectivity differs'
        assert vtu == cells_by_type(2), 'meshio boundary.vtu differs'
        volume = consume(pick/'volume.vtu')
        assert volume['tetra'] == cells_by_type(3)['tetra'], 'meshio volume.vtu differs'
        tri = len(msh['triangle']); tet = len(msh['tetra'])
        tags = sorted({t for t, _ in msh['triangle']}|{t for t, _ in msh['tetra']})
        report['cases'].append({'case': 'meshio-consumer', 'triangles': tri, 'tetrahedra': tet, 'tags': tags,
                                'checked': 'every cell: type, physical tag, vertex coordinates in file order; msh, boundary.vtu, volume.vtu'})

        template = json.loads((ROOT/'src/schemaxis/adaptors/gmsh/templates/bore-roundness-mesh.json').read_text())
        template['refinement']['requirements']['boundaryMaximumChordDeviation'][0]['maximum'] = 0.05
        adaptor.run(template, target/'template-bore-roundness', executable=gmsh, timeout=600)
        assert adaptor.verify(target/'template-bore-roundness')['verified']
        study = json.loads((target/'template-bore-roundness/study-summary.json').read_text())
        bore = [next(c for c in summary_of(target/'template-bore-roundness'/a['directory'])['cylinderChecks'] if c['name'] == 'bore')['maximumChordDeviation'] for a in study['attempts']]
        assert study['accepted'] and bore[study['selected']] <= 0.05, bore
        report['cases'].append({'case': 'template-bore-roundness', 'attemptDeviations': bore})

        adopt = target/'adopt'; adopt.mkdir()
        source = next(Path(jobs['cad']['directory']).glob('model.step'))
        step = adopt/'part.step'; step.write_bytes(source.read_bytes())
        adopted = json.loads(cli('input', 'adopt', str(step), str(adopt/'snap')))['reference']
        child = {'version': 'schemaxis.workflow/1', 'operations': [load('freecad-gmsh-bores.json')['operations'][1]]}
        child['operations'][0]['document']['nodes'][0]['options']['file'] = adopted
        out = target/'adopt-child'
        workflow.execute(child, out, locations=where, timeout=600)
        assert workflow.verify(out)['verified']
        assert {str(p.relative_to(plate)): file_digest(p) for p in sorted(plate.rglob('*')) if p.is_file()} == before, 'parent changed'
        snapshot = next((adopt/'snap'/'data').glob('part.step')); original = snapshot.read_bytes()
        try:
            snapshot.chmod(0o644); snapshot.write_bytes(original+b' ')
            for call in (lambda: workflow.verify(out), lambda: workflow.execute(child, target/'adopt-tampered', locations=where, timeout=300)):
                try: call()
                except SchemaxisError as error: report['refusals'].append({'case': 'captured-bytes-changed', 'code': error.fault.code})
                else: raise AssertionError('changed captured STEP accepted')
        finally:
            snapshot.write_bytes(original)
        assert workflow.verify(out)['verified']
        result_msh = next(Path(out).rglob('result.msh')); original = result_msh.read_bytes()
        try:
            result_msh.write_bytes(original.replace(b'$Nodes', b'$Nodes ', 1))
            try: workflow.verify(out)
            except SchemaxisError as error: report['refusals'].append({'case': 'corrupt-mesh-evidence', 'code': error.fault.code})
            else: raise AssertionError('corrupt mesh evidence accepted')
        finally: result_msh.write_bytes(original)
        try:
            adaptor.run(base, target/'timeout-a', executable=gmsh, timeout=0.01)
        except SchemaxisError as error:
            report['refusals'].append({'case': 'native-timeout', 'code': error.fault.code})
            assert not json.loads((target/'timeout-a/result.json').read_text())['verified']
        else: raise AssertionError('timeout not enforced')
        retry = copy.deepcopy(base); retry['nodes'][1]['options']['size'] = 0.8
        run(retry, 'timeout-recovered')

        shutil.move(adopt/'snap', adopt/'snap-away')
        try:
            try: workflow.verify(out)
            except SchemaxisError as error: report['refusals'].append({'case': 'missing-capture', 'code': error.fault.code})
            else: raise AssertionError('missing capture accepted')
        finally: shutil.move(adopt/'snap-away', adopt/'snap')
        assert workflow.verify(out)['verified']

        script = target/'fixtures.py'
        script.write_text(
            "import gmsh,sys\n"
            "def build(name,make):\n"
            "    gmsh.initialize([],readConfigFiles=False);gmsh.model.add(name);make();gmsh.model.occ.synchronize();gmsh.write(sys.argv[1]+'/'+name+'.step');gmsh.finalize()\n"
            "build('cone',lambda:gmsh.model.occ.addCone(0,0,0,0,0,8,4,1))\n"
            "build('oblique',lambda:gmsh.model.occ.addCylinder(0,0,0,3,0,8,3))\n")
        with (target/'fixtures.log').open('w') as log:
            subprocess.run([gmsh, str(script), str(target)], check=True, timeout=60, stdout=log, stderr=subprocess.STDOUT)

        def step_doc(name, size, groups, faces=()):
            return {'version': 'schemaxis.gmsh/1', 'units': 'mm', 'nodes': [
                {'id': 'solid', 'filter': 'readSTEP', 'options': {'file': str(target/(name+'.step'))}},
                {'id': 'mesh', 'filter': 'tetrahedral', 'inputs': {'input': 'solid'}, 'options': {
                    'size': size, 'volumeTolerance': 0.02, 'faceGroups': list(faces), 'cylinderGroups': groups}}], 'output': 'mesh'}
        wall = [{'name': 'wall', 'axis': 'z', 'centre': [0, 0, 0], 'radius': 4, 'side': 'outer'}]
        refuse(step_doc('cone', 1, wall), 'x-cone', 'INVALID_SELECTION', 'mesh.options.cylinderGroups[0]', native=True)
        refuse(step_doc('oblique', 1, [dict(wall[0], radius=3)]), 'x-oblique', 'INVALID_SELECTION', 'mesh.options.cylinderGroups[0]', native=True)
        inventory = run(step_doc('oblique', 0.6, []), 'x-oblique-inventory')
        listed = summary_of(target/'x-oblique-inventory')['cadSurfaces']['surfaces']
        assert any(x['type'] == 'cylinder' and x['axis'] is None and not x['selectable'] for x in listed)

        def refreshed(name, mutate_msh=None, mutate_authored=None, source=None):
            """Copy a verified run, mutate it and refresh every dependent publication and hash."""
            shutil.copytree(source or target/'a1-sleeve', target/name)
            directory = target/name
            if mutate_msh:
                lines = (directory/'result.msh').read_text().splitlines(); mutate_msh(lines); (directory/'result.msh').write_text('\n'.join(lines)+'\n')
            data = mesh.read(directory/'result.msh'); observed = mesh.inspect(data); quality = assess(data)
            for item in ('built.json', 'reopened.json'):
                value = json.loads((directory/item).read_text())
                value['snapshot'].update({k: observed[k] for k in ('volume', 'minimumVolume', 'bounds')})
                value['snapshot'].update(minimumEdgeLength=quality['minimumEdgeLength']['minimum'], maximumEdgeLength=quality['maximumEdgeLength']['maximum'],
                                         boundaryCounts={str(g['tag']): g['triangles'] for g in observed['boundaryGroups']})
                if mutate_authored: mutate_authored(value['plan'])
                (directory/item).write_text(json.dumps(value))
            if mutate_authored:
                for item in ('authored.json', 'plan.json'):
                    value = json.loads((directory/item).read_text())
                    mutate_authored(value if item == 'plan.json' else {'nodes': value['nodes']})
                    (directory/item).write_text(json.dumps(value))
            for dimension, vtu in ((3, 'volume.vtu'), (2, 'boundary.vtu')): mesh.write_vtu(directory/vtu, data, dimension)
            built = json.loads((directory/'built.json').read_text())
            walls = None
            try: walls = adaptor.wall_reports(built['plan'], built, data, built['plan']['nodes'][0])
            except SchemaxisError: pass
            (directory/'mesh-summary.json').write_text(json.dumps(adaptor.summary(built['plan'], observed, built['cad'], data, built['faceAreas'], walls, built.get('cadSurfaces'))))
            (directory/'verification.json').write_text(json.dumps({'artifacts': adaptor.manifest(directory), 'evidence': {n: file_digest(directory/n) for n in adaptor.EVIDENCE}}))
            return directory

        def retag(lines, wanted, new):
            start = lines.index('$Elements')+2
            for k in range(start, lines.index('$EndElements')):
                words = lines[k].split()
                if words[1] == '2' and int(words[3]) == wanted:
                    words[3] = str(new); lines[k] = ' '.join(words); return
        def radial_move(lines):
            data = mesh.read(a1/'result.msh')
            tag = next(t for t, p in data['nodes'].items() if abs(math.hypot(p[1]-2, p[2]-3)-2) < 1e-9 and 1 < p[0] < 9)
            start = lines.index('$Nodes')+2
            for k in range(start, lines.index('$EndNodes')):
                words = lines[k].split()
                if int(words[0]) == tag:
                    x, y, z = map(float, words[1:]); scale = 1-1e-3/2
                    lines[k] = ' '.join([words[0], repr(x), repr(2+(y-2)*scale), repr(3+(z-3)*scale)]); return
        def swap(lines):
            start = lines.index('$Elements')+2
            for k in range(start, lines.index('$EndElements')):
                words = lines[k].split()
                if words[1] == '2' and words[3] in ('5', '6'):
                    words[3] = '6' if words[3] == '5' else '5'; lines[k] = ' '.join(words)
        for label, kwargs, fragment in (
                ('retag-bore-to-start-cap', {'mutate_msh': lambda l: retag(l, 5, 3)}, 'physical face tag differs'),
                ('swap-wall-tags', {'mutate_msh': swap}, 'physical face tag differs'),
                ('radial-vertex-moved', {'mutate_msh': radial_move}, 'physical face tag differs')):
            directory = refreshed('adv-'+label, **kwargs)
            try: adaptor.verify(directory)
            except SchemaxisError as error:
                assert error.fault.code == 'VERIFICATION_FAILED' and fragment in error.fault.message, error.fault.to_dict()
                report['adversaries'].append({'case': label, 'message': error.fault.message})
            else: raise AssertionError(label+' accepted')

        standalone = copy.deepcopy(load('freecad-gmsh-bores.json')['operations'][1]['document'])
        standalone['nodes'][0]['options']['file'] = str(mesh_dir/'source.step')
        run(standalone, 'plate-standalone')
        hard = copy.deepcopy(standalone); hard['nodes'][1]['options'].pop('nearBoundaries'); hard['nodes'][1]['options']['size'] = 4
        hard['refinement'] = {'maxIterations': 8, 'reductionFactor': 0.7, 'minimumSize': 0.3, 'maxTetrahedra': 200000,
            'requirements': {'boundaryMaximumChordDeviation': [{'boundary': 'loadBore', 'maximum': 0.02}]}}
        fault = refuse(hard, 'x-unmet-deviation', 'STUDY_REQUIREMENTS_NOT_MET', native=True)
        assert fault.observed['reason'] == 'work_estimate_limit', fault.to_dict()
        wrong = copy.deepcopy(standalone); wrong['nodes'][1]['options']['cylinderGroups'][0]['side'] = 'outer'
        fault = refuse(wrong, 'x-step-wrong-side', 'INVALID_SELECTION', 'mesh.options.cylinderGroups[0]', native=True)
        assert 'other material side' in fault.message, fault.message
        directory = refreshed('adv-retag-wall-to-remainder', mutate_msh=lambda l: retag(l, 5, 2), source=target/'plate-standalone')
        try: adaptor.verify(directory)
        except SchemaxisError as error:
            assert error.fault.code == 'VERIFICATION_FAILED' and 'physical face tag differs' in error.fault.message, error.fault.to_dict()
            report['adversaries'].append({'case': 'retag-wall-to-remainder', 'message': error.fault.message})
        else: raise AssertionError('wall retagged to remainder accepted')
        flip = target/'adv-side-flip'
        shutil.copytree(target/'plate-standalone', flip)
        for name in ('authored.json', 'plan.json', 'built.json', 'reopened.json'):
            value = json.loads((flip/name).read_text())
            nodes = value['nodes'] if 'nodes' in value else value['plan']['nodes']
            nodes[1]['options']['cylinderGroups'][1]['side'] = 'outer'
            (flip/name).write_text(json.dumps(value))
        (flip/'verification.json').write_text(json.dumps({'artifacts': adaptor.manifest(flip), 'evidence': {n: file_digest(flip/n) for n in adaptor.EVIDENCE}}))
        try: adaptor.verify(flip)
        except SchemaxisError as error:
            assert error.fault.code == 'VERIFICATION_FAILED' and 'material side' in error.fault.message, error.fault.to_dict()
            report['adversaries'].append({'case': 'authored-side-flipped', 'code': error.fault.code, 'message': error.fault.message})
        else: raise AssertionError('flipped side accepted')

        rev = target/'revision'; rev.mkdir()
        parent_tree = lambda: {str(p.relative_to(plate)): file_digest(p) for p in sorted(plate.rglob('*')) if p.is_file()}
        parent_before = parent_tree()
        pointer = '/nodes/0/options/file'
        cli('revision', 'checkout', str(plate), '--consumer', 'mesh', '--pointer', pointer, '--destination', str(rev/'work.step'))
        retained = next(Path(jobs['cad']['directory']).glob('model.step'))
        assert (rev/'work.step').read_bytes() == retained.read_bytes(), 'checkout is not a copy of the producer artifact'
        edit = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'cad', 'document': {
            'version': 'schemaxis.freecad/1', 'units': 'mm', 'nodes': [
                {'id': 'part', 'filter': 'importSTEP', 'options': {'file': str(rev/'work.step'), 'units': 'mm', 'expect': {
                    'volume': {'value': 19200-256*PI, 'relativeTolerance': 1e-6}, 'centreOfMass': {'value': [30, 20, 4], 'tolerance': 0.01},
                    'bounds': {'value': [0, 60, 0, 40, 0, 8], 'tolerance': 0.01}}}},
                {'id': 'top', 'filter': 'box', 'options': {'length': 80, 'width': 60, 'height': 2, 'origin': [-10, -10, 6]}},
                {'id': 'edited', 'filter': 'cut', 'inputs': {'base': 'part', 'tool': 'top'}}], 'output': 'edited'}}]}
        saved = workflow.execute(edit, rev/'edit-in-freecad', locations=where, timeout=600)
        shutil.copyfile(next(Path(j['directory']) for j in saved['jobs'] if j['operation'] == 'cad')/'model.step', rev/'edited.step')
        assert (rev/'edited.step').read_bytes() != (rev/'work.step').read_bytes()
        cli('revision', 'prepare', str(plate), '--consumer', 'mesh', '--pointer', pointer, '--replacement', str(rev/'edited.step'),
            '--snapshot', str(rev/'snap'), '--reason', 'top 2 mm removed', '--output', str(rev/'revision.json'))
        cli('plan', str(rev/'revision.json'))
        cli('run', str(rev/'revision.json'), '--output-directory', str(rev/'child'), '--backend', 'native')
        cli('verify', str(rev/'child'))
        child = summary_of(next((rev/'child').rglob('mesh-summary.json')).parent)
        assert abs(child['cadVolume']-(14400-192*PI)) <= 1e-9*14400, child['cadVolume']
        assert all(abs(c['cadArea']-48*PI) <= 1e-9*48*PI and c['side'] == 'inner' for c in child['cylinderChecks'])
        assert parent_tree() == parent_before, 'revision changed the parent'
        cli('verify', str(plate))
        saved = next((rev/'snap').rglob('*.step')); original = saved.read_bytes()
        try:
            saved.chmod(0o644); saved.write_bytes(original+b' ')
            try: cli('verify', str(rev/'child'))
            except subprocess.CalledProcessError as error:
                code = json.loads(error.stdout[error.stdout.index('{'):])['fault']['code']
                assert code.startswith(('RESOURCE_', 'REVISION_')), code
                report['refusals'].append({'case': 'revision-snapshot-changed', 'code': code})
            else: raise AssertionError('changed revision snapshot accepted')
        finally: saved.write_bytes(original)
        cli('verify', str(rev/'child'))
        report['cases'].append({'case': 'revision-top-removed-plate', 'volume': child['cadVolume'], 'bores': [c['cadArea'] for c in child['cylinderChecks']]})

        if args.legacy:
            from schemaxis.adaptors import registry as shared
            for legacy in sorted(p for p in args.legacy.resolve().iterdir() if (p/'authored.json').is_file()):
                assert shared.verify(legacy)['verified'], legacy
                report['cases'].append({'case': 'legacy-reverified', 'directory': legacy.name})
            face = args.legacy.resolve()/'face-groups'
            shutil.copytree(args.legacy.resolve()/'schemas', target/'schemas', dirs_exist_ok=True)
            retagged = refreshed('adv-legacy-retag', mutate_msh=lambda l: retag(l, 3, 2), source=face)
            try: adaptor.verify(retagged)
            except SchemaxisError as error:
                assert error.fault.code == 'VERIFICATION_FAILED' and 'physical face tag differs' in error.fault.message, error.fault.to_dict()
                report['adversaries'].append({'case': 'legacy-retag', 'message': error.fault.message})
            else: raise AssertionError('retagged legacy run accepted')
        report['verified'] = True
    finally:
        (target/'report.json').write_text(json.dumps(report, indent=2, default=str)+'\n')
    print(json.dumps({'verified': report['verified'], 'cases': len(report['cases']), 'refusals': len(report['refusals']), 'adversaries': len(report['adversaries'])}))


if __name__ == '__main__':
    main()
