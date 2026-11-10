# Copyright (C) 2026 David L F Gaden
"""Trusted isolated Gmsh worker; never imported during host discovery/planning."""
import json
import math
import os
from pathlib import Path
import sys

SUPPORTED = ['4', '15']


class NativeFault(Exception):
    """A deliberate worker refusal with a stable code; the host allow-lists these codes."""
    def __init__(self, code, message, recovery, location='$', **observed):
        super().__init__(message)
        self.fault = {'code': code, 'message': message, 'location': location, 'phase': 'native',
                      'retryable': False, 'observed': observed, 'recovery': recovery}


def aligned(direction):
    """Index of the world axis a unit direction is parallel to (either sign), else None."""
    for k in range(3):
        if abs(abs(direction[k])-1) <= 1e-9 and all(abs(direction[m]) <= 1e-9 for m in range(3) if m != k):
            return k
    return None


def clean(value):
    return round(value, 9)+0.0


def wall_side(gmsh, volume, tag, values):
    """'outer', 'inner' or 'unknown', by testing points just either side of a point on the trimmed face."""
    low, high = gmsh.model.getParametrizationBounds(2, tag)
    point, direction, radius = values[0:3], values[3:6], values[6]
    for fu, fv in ((.5, .5), (.25, .5), (.75, .5), (.5, .25), (.5, .75), (.25, .25), (.75, .75), (.1, .9), (.9, .1)):
        uv = [low[0]+(high[0]-low[0])*fu, low[1]+(high[1]-low[1])*fv]
        if not gmsh.model.isInside(2, tag, uv, True):
            continue
        xyz = gmsh.model.getValue(2, tag, uv)
        offset = [xyz[k]-point[k] for k in range(3)]
        along = sum(offset[k]*direction[k] for k in range(3))
        radial = [offset[k]-along*direction[k] for k in range(3)]
        length = math.sqrt(sum(v*v for v in radial))
        for step in (max(1e-5, 1e-4*radius), max(1e-6, 1e-5*radius), 1e-7):
            inside = [gmsh.model.isInside(3, volume, [xyz[k]+sign*step*radial[k]/length for k in range(3)]) for sign in (-1, 1)]
            if inside == [1, 0]:
                return 'outer'
            if inside == [0, 1]:
                return 'inner'
    return 'unknown'


def read_surfaces(gmsh, volume):
    """Typed analytic readback of every boundary face; tags are used internally only.

    A cylinder's material side comes from classifying two probe points a small
    step either side of the wall with the solid itself, not from face orientation
    flags, which differ between CAD sources.
    """
    records = {}
    for tag in sorted({abs(t) for d, t in gmsh.model.getBoundary([(3, volume)], oriented=False) if d == 2}):
        kind = gmsh.model.getEntityType(2, tag)
        record = {'type': kind, 'area': gmsh.model.occ.getMass(2, tag),
                  'values': [float(v) for v in gmsh.model.getEntityProperties(2, tag)[1]]}
        if kind == 'Cylinder':
            record['side'] = wall_side(gmsh, volume, tag, record['values'])
        records[tag] = record
    return records


def cylinder_match(record, group):
    """Whole-face match to an authored cylinder: typed Cylinder, parallel axis, axis line and radius within tolerance."""
    values = record['values']
    axis = 'xyz'.index(group['axis'])
    if record['type'] != 'Cylinder' or aligned(values[3:6]) != axis:
        return False
    transverse = [k for k in range(3) if k != axis]
    offset = math.hypot(*[values[k]-group['centre'][k] for k in transverse])
    return offset+abs(values[6]-group['radius']) <= group['tolerance']


def inventory(records):
    """Aggregated advisory inventory of planes, cylinders and other surfaces, without native tags."""
    merged = {}
    for record in records.values():
        kind, values = record['type'], record['values']
        if kind == 'Plane':
            k = aligned(values[0:3])
            if k is not None:
                key = ('plane', 'xyz'[k], clean(-values[3]/values[k]))
                entry = {'type': 'plane', 'axis': 'xyz'[k], 'coordinate': key[2], 'selectable': True}
            else:
                length = math.sqrt(sum(v*v for v in values[0:3]))
                entry = {'type': 'plane', 'axis': None, 'normal': [clean(v/length) for v in values[0:3]], 'offset': clean(values[3]/length), 'selectable': False}
                key = ('plane', None, tuple(entry['normal']), entry['offset'])
        elif kind == 'Cylinder':
            k = aligned(values[3:6])
            if k is not None:
                centre = [0.0 if m == k else clean(values[m]) for m in range(3)]
                key = ('cylinder', 'xyz'[k], tuple(centre), clean(values[6]), record['side'])
                entry = {'type': 'cylinder', 'axis': 'xyz'[k], 'centre': centre, 'radius': clean(values[6]), 'side': record['side'], 'selectable': record['side'] != 'unknown'}
            else:
                entry = {'type': 'cylinder', 'axis': None, 'direction': [clean(v) for v in values[3:6]],
                         'centre': [clean(v) for v in values[0:3]], 'radius': clean(values[6]), 'side': record['side'], 'selectable': False}
                key = ('cylinder', None, tuple(entry['direction']), tuple(entry['centre']), entry['radius'], record['side'])
        else:
            entry = {'type': kind.lower(), 'selectable': False}
            key = (kind.lower(),)
        item = merged.setdefault(key, {**entry, 'faces': 0, 'area': 0.0})
        item['faces'] += 1
        item['area'] += record['area']
    ordered = sorted(merged.values(), key=lambda e: json.dumps({k: v for k, v in e.items() if k not in ('faces', 'area')}, sort_keys=True))
    for item in ordered:
        item['area'] = clean(item['area'])
    return {'surfaces': ordered[:64], 'truncated': len(ordered) > 64}


def candidates(items, kind, limit=1200):
    """Compact selectable surfaces of one kind for a fault, bounded to fit the host's record limit."""
    chosen = [{k: v for k, v in item.items() if k not in ('selectable', 'faces', 'type')}
              for item in items['surfaces'] if item['type'] == kind and item['selectable']]
    while chosen and len(json.dumps(chosen)) > limit:
        chosen.pop()
    return chosen


def main(directory, stage):
    try:
        import gmsh
    except ImportError as error:
        raise NativeFault('NATIVE_UNAVAILABLE', 'the configured Python cannot import the gmsh module',
                          'configure an absolute Python executable with Gmsh 4.15.x installed, using --gmsh or GMSH_PYTHON',
                          module='gmsh', importError=str(error)) from error
    prepared = json.loads((directory/'plan.json').read_text())
    where = (prepared['nodes'][0]['id']+'.options'+('.file' if prepared['nodes'][0]['filter'] == 'readSTEP' else ''),
             prepared['nodes'][1]['id']+'.options.')
    gmsh.initialize([], readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.NumThreads', 1)
        gmsh.option.setNumber('General.Terminal', 1)
        if gmsh.__version__.split('.')[:2] != SUPPORTED:
            raise NativeFault('UNSUPPORTED_RUNTIME', 'this adaptor supports Gmsh 4.15.x; qualify a new runtime before extending it',
                              'configure a Python with Gmsh 4.15.x; a different version needs its own bounded native acceptance first',
                              version=str(gmsh.__version__), supported='4.15.x')
        if stage == 'build':
            gmsh.model.add('Schemaxis')
            source, mesh = prepared['nodes']
            options = source['options']; settings = mesh['options']
            if source['filter'] == 'box':
                tag = gmsh.model.occ.addBox(*options['origin'], *options['size'])
            elif source['filter'] in ('cylinder','hollowCylinder'):
                delta = [options['height'] if a == options['axis'] else 0 for a in 'xyz']
                tag = gmsh.model.occ.addCylinder(*options['origin'], *delta, options['radius'])
                if source['filter'] == 'hollowCylinder':
                    bore = gmsh.model.occ.addCylinder(*options['origin'], *delta, options['innerRadius'])
                    cut, _ = gmsh.model.occ.cut([(3,tag)],[(3,bore)],removeObject=True,removeTool=True)
                    if len(cut) != 1 or cut[0][0] != 3:
                        raise NativeFault('UNSUPPORTED_RESOURCE','hollow cylinder did not produce one solid',
                                          'increase wall thickness and retry',source['id']+'.options.innerRadius')
                    tag = cut[0][1]
            elif source['filter'] == 'sphere':
                tag = gmsh.model.occ.addSphere(*options['centre'],options['radius'])
            else:
                gmsh.option.setString('Geometry.OCCTargetUnit', 'MM')
                imported = gmsh.model.occ.importShapes(str(directory/'source.step'), highestDimOnly=True, format='step')
                if len(imported) != 1 or imported[0][0] != 3:
                    raise NativeFault('UNSUPPORTED_RESOURCE', 'STEP input must contain exactly one solid volume',
                                      'export one fused solid (no assemblies, shells or multiple bodies) and retry',
                                      where[0], volumes=sum(d == 3 for d, _ in imported), entities=len(imported))
                tag = imported[0][1]
            gmsh.model.occ.synchronize()
            if gmsh.model.getEntities(3) != [(3, tag)]:
                raise NativeFault('UNSUPPORTED_RESOURCE', 'expected exactly one OCC volume',
                                  'provide geometry that synchronizes to a single volume', where[0])
            cad = {'volume': gmsh.model.occ.getMass(3, tag),
                   'bounds': list(gmsh.model.getBoundingBox(3, tag))}
            if not math.isfinite(cad['volume']) or cad['volume'] <= 0:
                raise NativeFault('INVALID_RESOURCE', 'CAD volume is not positive',
                                  'repair or re-export the solid so OpenCASCADE reports a positive finite volume', where[0])
            b = cad['bounds']; h = settings['size']
            minimum = min([h]+[rule['size'] for rule in settings['nearBoundaries']])
            estimate = 6 * math.prod((b[i+3]-b[i])/minimum+1 for i in range(3))
            if estimate > 200000:
                raise NativeFault('RESOURCE_LIMIT', 'requested mesh size exceeds the 200000-cell work estimate; increase size',
                                  'increase the global or boundary mesh size, or mesh a smaller solid',
                                  where[1]+'size', estimate=round(estimate), limit=200000, minimumSize=minimum)
            records = read_surfaces(gmsh, tag)
            surfaces = sorted(records)
            listing = inventory(records)
            if not surfaces:
                raise NativeFault('UNSUPPORTED_RESOURCE', 'volume has no boundary',
                                  'provide a bounded solid volume', where[0])
            gmsh.model.addPhysicalGroup(3, [tag], tag=1, name=settings['volumeName'])
            remaining = set(surfaces); face_areas = {}
            for index, group in enumerate(settings['faceGroups']):
                axis = 'xyz'.index(group['axis'])
                selected = []
                for surface in surfaces:
                    bounds = gmsh.model.getBoundingBox(2,surface)
                    if all(abs(bounds[k]-group['coordinate']) <= group['tolerance'] for k in (axis,axis+3)):
                        selected.append(surface)
                if not selected or not set(selected) <= remaining:
                    raise NativeFault('INVALID_SELECTION', 'face selector '+group['name']+' is empty or overlaps another group; select disjoint whole planar faces',
                                      'compare axis/coordinate with cadBounds from a successful run or the CAD model, and select disjoint whole planar faces',
                                      where[1]+'faceGroups['+str(index)+']', name=group['name'], axis=group['axis'],
                                      coordinate=group['coordinate'], matched=len(selected),
                                      candidates=candidates(listing, 'plane'))
                remaining.difference_update(selected)
                physical = index+3
                gmsh.model.addPhysicalGroup(2, selected, tag=physical, name=group['name'])
                face_areas[str(physical)] = math.fsum(gmsh.model.occ.getMass(2,t) for t in selected)
            cylinder_areas = {}
            for index, group in enumerate(settings.get('cylinderGroups', [])):
                physical = len(settings['faceGroups'])+index+3
                geometric = [t for t in surfaces if cylinder_match(records[t], group)]
                selected = [t for t in geometric if records[t]['side'] == group['side']]
                unknown = [t for t in geometric if records[t]['side'] == 'unknown']
                opposite = [t for t in geometric if records[t]['side'] not in (group['side'], 'unknown')]
                claimed = [t for t in selected if t not in remaining]
                reason = None
                if not geometric:
                    reason = 'matches no whole analytic cylinder'
                elif unknown and not selected:
                    reason = 'matches a wall whose material side could not be determined'
                elif opposite and not selected:
                    reason = 'matches only walls on the other material side'
                elif opposite:
                    reason = 'is also met by a wall on the other material side of the same cylinder, which cannot be separated'
                elif claimed:
                    reason = 'overlaps faces already assigned to another group'
                if reason:
                    curved = {}
                    for r in records.values():
                        if r['type'] not in ('Plane', 'Cylinder'):
                            curved[r['type']] = curved.get(r['type'], 0)+1
                    raise NativeFault('INVALID_SELECTION', 'cylinder selector '+group['name']+' '+reason+'; select whole analytic cylindrical faces',
                                      'use axis, centre, radius and side from the candidates or the cadSurfaces inventory of a successful run; only typed analytic cylinders with a world-axis direction are selectable',
                                      where[1]+'cylinderGroups['+str(index)+']', name=group['name'], axis=group['axis'],
                                      radius=group['radius'], side=group['side'], matched=len(selected),
                                      unknownSide=len(unknown), otherSide=len(opposite),
                                      obliqueCylinders=sum(1 for r in records.values() if r['type'] == 'Cylinder' and aligned(r['values'][3:6]) is None),
                                      otherCurved=curved, candidates=candidates(listing, 'cylinder'))
                remaining.difference_update(selected)
                gmsh.model.addPhysicalGroup(2, selected, tag=physical, name=group['name'])
                cylinder_areas[str(physical)] = math.fsum(records[t]['area'] for t in selected)
            if remaining:
                gmsh.model.addPhysicalGroup(2, sorted(remaining), tag=2, name=settings['boundaryName'])
            elif not settings.get('cylinderGroups'):
                raise NativeFault('INVALID_SELECTION', 'leave at least one face for the remainder boundary group',
                                  'remove or narrow a face group so some boundary face stays in the remainder group',
                                  where[1]+'faceGroups', groups=len(settings['faceGroups']))
            for key, value in {'Mesh.MeshSizeMin': minimum, 'Mesh.MeshSizeMax': h,
                               'Mesh.MeshSizeFromPoints': 0, 'Mesh.MeshSizeFromCurvature': 0,
                               'Mesh.MeshSizeExtendFromBoundary': 0,
                               'Mesh.Algorithm3D': {'delaunay':1,'hxt':10}[settings['algorithm']],
                               'Mesh.Optimize': int(settings['optimise']),
                               'Mesh.ElementOrder': 1, 'Mesh.MshFileVersion': 2.2,
                               'Mesh.Binary': 0, 'Mesh.SaveAll': 0}.items():
                gmsh.option.setNumber(key, value)
            sizing = {'rules': [], 'minimum': gmsh.option.getNumber('Mesh.MeshSizeMin'),
                      'maximum': gmsh.option.getNumber('Mesh.MeshSizeMax'),
                      'combinedType': None, 'combinedFields': []}
            names = {g['name']: i+3 for i,g in enumerate(settings['faceGroups'])}
            names.update({g['name']: len(settings['faceGroups'])+i+3 for i,g in enumerate(settings.get('cylinderGroups', []))})
            if remaining: names[settings['boundaryName']] = 2
            field = gmsh.model.mesh.field
            for index, rule in enumerate(settings['nearBoundaries']):
                if rule['boundary'] not in names:
                    raise NativeFault('INVALID_SELECTION', 'sizing rule names the remainder boundary, which is empty',
                                      'name a declared group, or leave a face in the remainder',
                                      where[1]+'nearBoundaries['+str(index)+'].boundary', boundary=rule['boundary'])
                physical = names[rule['boundary']]
                entities = sorted(int(t) for t in gmsh.model.getEntitiesForPhysicalGroup(2, physical))
                distance = field.add('Distance', tag=2*index+1)
                field.setNumbers(distance, 'SurfacesList', entities)
                field.setNumber(distance, 'Sampling', 20)
                threshold = field.add('Threshold', tag=2*index+2)
                options = {'InField': distance, 'SizeMin': rule['size'], 'SizeMax': h,
                           'DistMin': 0, 'DistMax': rule['distance'], 'StopAtDistMax': 0}
                for key,value in options.items(): field.setNumber(threshold, key, value)
                sizing['rules'].append({'boundary': rule['boundary'], 'physicalTag': physical,
                    'entities': entities, 'distanceSurfaces': [int(t) for t in field.getNumbers(distance, 'SurfacesList')],
                    'distanceType': field.getType(distance), 'thresholdType': field.getType(threshold),
                    'sampling': field.getNumber(distance, 'Sampling'),
                    'threshold': {key: field.getNumber(threshold, key) for key in options}})
            if sizing['rules']:
                combined = field.add('Min', tag=2*len(sizing['rules'])+1)
                field.setNumbers(combined, 'FieldsList', [2*i+2 for i in range(len(sizing['rules']))])
                field.setAsBackgroundMesh(combined)
                sizing['combinedType'] = field.getType(combined)
                sizing['combinedFields'] = [int(t) for t in field.getNumbers(combined, 'FieldsList')]
            meshing = {key:gmsh.option.getNumber(option) for key, option in {
                'algorithm':'Mesh.Algorithm3D','optimise':'Mesh.Optimize',
                'elementOrder':'Mesh.ElementOrder','threads':'General.NumThreads'}.items()}
            gmsh.model.mesh.generate(3)
            gmsh.write(str(directory/'result.msh'))
        elif stage == 'reopen':
            gmsh.open(str(directory/'result.msh'))
            cad = None
        else:
            raise ValueError('unknown native stage')
        node_tags, xyz, _ = gmsh.model.mesh.getNodes()
        _, triangles = gmsh.model.mesh.getElementsByType(2)
        tet_tags, _ = gmsh.model.mesh.getElementsByType(4)
        if len(node_tags) > 50000 or len(triangles)//3 + len(tet_tags) > 200000:
            raise NativeFault('RESOURCE_LIMIT', 'actual mesh exceeds node/cell bounds',
                              'increase the mesh size or mesh a smaller solid', where[1]+'size',
                              nodes=len(node_tags), cells=len(triangles)//3 + len(tet_tags), nodeLimit=50000, cellLimit=200000)
        volumes = gmsh.model.mesh.getElementQualities(tet_tags, 'volume')
        if not len(volumes) or not all(math.isfinite(v) and v > 0 for v in volumes):
            raise ValueError('empty or inverted native tetrahedra')
        snapshot = {'nodes': len(node_tags), 'triangles': len(triangles)//3,
                    'minimumEdgeLength': min(gmsh.model.mesh.getElementQualities(tet_tags, 'minEdge')),
                    'maximumEdgeLength': max(gmsh.model.mesh.getElementQualities(tet_tags, 'maxEdge')),
                    'tetrahedra': len(tet_tags), 'volume': math.fsum(volumes),
                    'minimumVolume': min(volumes),
                    'bounds': [f(xyz[k::3]) for f in (min,max) for k in range(3)],
                    'groups': [{'dimension':d,'tag':t,'name':gmsh.model.getPhysicalName(d,t)}
                               for d,t in sorted(gmsh.model.getPhysicalGroups())],
                    'boundaryCounts': {str(t):sum(len(gmsh.model.mesh.getElementsByType(2,int(e))[0])
                        for e in gmsh.model.getEntitiesForPhysicalGroup(2,t)) for d,t in gmsh.model.getPhysicalGroups(2)}}
        receipt = {'stage': stage, 'pid': os.getpid(), 'plan': prepared, 'snapshot': snapshot,
                   'runtime': {'name': 'Gmsh', 'version': gmsh.__version__, 'executable': sys.executable}}
        if cad is not None:
            receipt['cad'] = cad
            receipt['faceAreas'] = face_areas
            receipt['cylinderAreas'] = cylinder_areas
            receipt['cadSurfaces'] = listing
            receipt['sizing'] = sizing
            receipt['meshing'] = meshing
        (directory/('built.json' if stage == 'build' else 'reopened.json')).write_text(json.dumps(receipt, indent=2, allow_nan=False))
    finally:
        gmsh.finalize()


if __name__ == '__main__':
    directory, stage = Path(sys.argv[1]), sys.argv[2]
    try:
        main(directory, stage)
    except Exception as error:
        fault = getattr(error, 'fault', None) if isinstance(error, NativeFault) else {
            'code': 'NATIVE_EXECUTION_FAILED', 'message': str(error) or type(error).__name__, 'location': '$',
            'phase': 'native', 'retryable': False, 'observed': {'exceptionType': type(error).__name__, 'stage': stage},
            'recovery': 'inspect the retained build/reopen logs; check that the input is a valid single solid and the mesh size is feasible'}
        (directory/'native-fault.json').write_text(json.dumps(fault))
        raise
