"""Trusted isolated Gmsh worker; never imported during host discovery/planning."""
import json
import math
import os
from pathlib import Path
import sys


def main(directory, stage):
    import gmsh
    prepared = json.loads((directory/'plan.json').read_text())
    gmsh.initialize([], readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.NumThreads', 1)
        gmsh.option.setNumber('General.Terminal', 1)
        if gmsh.__version__.split('.')[:2] != ['4', '15']:
            raise ValueError('this adaptor supports Gmsh 4.15.x; qualify a new runtime before extending it')
        if stage == 'build':
            gmsh.model.add('Schemaxis')
            source, mesh = prepared['nodes']
            options = source['options']; settings = mesh['options']
            if source['filter'] == 'box':
                tag = gmsh.model.occ.addBox(*options['origin'], *options['size'])
            else:
                gmsh.option.setString('Geometry.OCCTargetUnit', 'MM')
                imported = gmsh.model.occ.importShapes(str(directory/'source.step'), highestDimOnly=True, format='step')
                if len(imported) != 1 or imported[0][0] != 3:
                    raise ValueError('STEP input must contain exactly one solid volume')
                tag = imported[0][1]
            gmsh.model.occ.synchronize()
            if gmsh.model.getEntities(3) != [(3, tag)]:
                raise ValueError('expected exactly one OCC volume')
            cad = {'volume': gmsh.model.occ.getMass(3, tag),
                   'bounds': list(gmsh.model.getBoundingBox(3, tag))}
            if not math.isfinite(cad['volume']) or cad['volume'] <= 0:
                raise ValueError('CAD volume is not positive')
            b = cad['bounds']; h = settings['size']
            minimum = min([h]+[rule['size'] for rule in settings['nearBoundaries']])
            estimate = 6 * math.prod((b[i+3]-b[i])/minimum+1 for i in range(3))
            if estimate > 200000:
                raise ValueError('requested mesh size exceeds the 200000-cell work estimate; increase size')
            surfaces = sorted({abs(t) for d,t in gmsh.model.getBoundary([(3,tag)], oriented=False) if d == 2})
            if not surfaces:
                raise ValueError('volume has no boundary')
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
                    raise ValueError('face selector '+group['name']+' is empty or overlaps another group; select disjoint whole planar faces')
                remaining.difference_update(selected)
                physical = index+3
                gmsh.model.addPhysicalGroup(2, selected, tag=physical, name=group['name'])
                face_areas[str(physical)] = math.fsum(gmsh.model.occ.getMass(2,t) for t in selected)
            if not remaining:
                raise ValueError('leave at least one face for the remainder boundary group')
            gmsh.model.addPhysicalGroup(2, sorted(remaining), tag=2, name=settings['boundaryName'])
            for key, value in {'Mesh.MeshSizeMin': minimum, 'Mesh.MeshSizeMax': h,
                               'Mesh.MeshSizeFromPoints': 0, 'Mesh.MeshSizeFromCurvature': 0,
                               'Mesh.MeshSizeExtendFromBoundary': 0, 'Mesh.Algorithm3D': 1,
                               'Mesh.ElementOrder': 1, 'Mesh.MshFileVersion': 2.2,
                               'Mesh.Binary': 0, 'Mesh.SaveAll': 0}.items():
                gmsh.option.setNumber(key, value)
            sizing = {'rules': [], 'minimum': gmsh.option.getNumber('Mesh.MeshSizeMin'),
                      'maximum': gmsh.option.getNumber('Mesh.MeshSizeMax'),
                      'combinedType': None, 'combinedFields': []}
            names = {settings['boundaryName']: 2, **{g['name']: i+3 for i,g in enumerate(settings['faceGroups'])}}
            field = gmsh.model.mesh.field
            for index, rule in enumerate(settings['nearBoundaries']):
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
            raise ValueError('actual mesh exceeds node/cell bounds')
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
            receipt['sizing'] = sizing
        (directory/('built.json' if stage == 'build' else 'reopened.json')).write_text(json.dumps(receipt, indent=2, allow_nan=False))
    finally:
        gmsh.finalize()


if __name__ == '__main__':
    directory, stage = Path(sys.argv[1]), sys.argv[2]
    try:
        main(directory, stage)
    except Exception as error:
        (directory/'native-fault.json').write_text(json.dumps({'code':'NATIVE_EXECUTION_FAILED','message':str(error)}))
        raise
