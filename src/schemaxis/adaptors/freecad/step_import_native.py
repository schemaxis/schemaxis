# Copyright (C) 2026 David L F Gaden
"""Native importSTEP realisation; imported only inside FreeCAD's interpreter.

The source Part::Feature holds the file-frame solid in millimetres and carries the
editable Placement (placement times orientation). An optional Part::Refine output
follows that source with identity placement. Expectations are measured in the
part frame (orientation only) on the exact B-rep, never on a mesh.
"""
import math
import FreeCAD as App
import Part
from schemaxis.errors import fail


def matrix(rotation, translation=(0, 0, 0)):
    r = rotation
    return App.Matrix(r[0][0], r[0][1], r[0][2], translation[0], r[1][0], r[1][1], r[1][2], translation[1],
                      r[2][0], r[2][1], r[2][2], translation[2], 0, 0, 0, 1)


def placement_values(placement):
    m = placement.toMatrix()
    return [m.A11, m.A12, m.A13, m.A14, m.A21, m.A22, m.A23, m.A24, m.A31, m.A32, m.A33, m.A34]


def expected_placement(node):
    frame = node['frame']
    r, t = frame['worldFromFile'], frame['translation']
    return [r[0][0], r[0][1], r[0][2], t[0], r[1][0], r[1][1], r[1][2], t[1], r[2][0], r[2][1], r[2][2], t[2]]


def facts(shape):
    box = shape.optimalBoundingBox(False, False)
    solids = shape.Solids
    volume = sum(s.Volume for s in solids)
    return {'type': shape.ShapeType, 'valid': bool(shape.isValid()), 'solids': len(solids), 'shells': len(shape.Shells),
            'shellsClosed': [bool(s.isClosed()) for s in shape.Shells], 'faces': len(shape.Faces), 'volume': volume,
            'area': shape.Area, 'bounds': [box.XMin, box.XMax, box.YMin, box.YMax, box.ZMin, box.ZMax],
            'centreOfMass': [sum(s.Volume*getattr(s.CenterOfMass, a) for s in solids)/volume for a in 'xyz'] if volume > 0 else None}


def configure(obj, node, sources):
    record = sources[node['id']]
    shape = Part.Shape()
    try:
        shape.read(record['retained'])
    except Exception as error:
        fail('INVALID_GEOMETRY', 'FreeCAD could not read the retained STEP copy', node['id'], detail=str(error)[:300])
    read = facts(shape)
    # Success flags and check() are not evidence: require one valid solid whose shells are all closed.
    if read['solids'] != 1 or not read['valid'] or not read['shellsClosed'] or not all(read['shellsClosed']) or read['volume'] <= 0:
        fail('INVALID_GEOMETRY', 'importSTEP requires exactly one valid solid with closed shells; no repair is attempted',
             node['id'], observed={k: read[k] for k in ('type', 'valid', 'solids', 'shells', 'shellsClosed', 'faces')})
    obj.Shape = shape.Solids[0]
    obj.Placement = App.Placement(matrix(node['frame']['worldFromFile'], node['frame']['translation']))
    obj.addProperty('App::PropertyString', 'SourceSHA256', 'Schemaxis')
    obj.SourceSHA256 = record['sha256']
    return read


def attach_refine(doc, obj, node, index):
    if not node['options']['refine']:
        return obj
    refined = doc.addObject('Part::Refine', 'N'+str(index)+'Refined')
    refined.Source = obj
    refined.Label = node['id']+' refined'
    return refined


def _point(solid, point, guard):
    """Exact surface distance first; an on-surface or near-surface point is never evidence."""
    try:
        # A solid's own distance is zero for every interior point; measure to its boundary faces.
        distance = float(Part.Compound(solid.Faces).distToShape(Part.Vertex(App.Vector(*point)))[0])
        if not math.isfinite(distance) or distance < guard:
            return {'distance': distance if math.isfinite(distance) else None, 'inside': None}
        return {'distance': distance, 'inside': bool(solid.isInside(App.Vector(*point), guard/2, True))}
    except Exception as error:
        return {'distance': None, 'inside': None, 'error': str(error)[:200]}


def observe(doc, node, index, sha256):
    """Build and fresh-reopen observation of one import node (exact native B-rep)."""
    from .step_import import evaluate
    obj = doc.getObject('N'+str(index))
    def require(condition, message, **detail):
        if not condition:
            fail('VERIFICATION_FAILED', message, node['id'], **detail)
    require(obj is not None and obj.TypeId == 'Part::Feature' and getattr(obj, 'SourceSHA256', None) == sha256,
            'Imported source object or its source digest differs')
    actual = placement_values(obj.Placement)
    require(all(abs(a-b) <= 1e-9*(1+abs(b)) for a, b in zip(actual, expected_placement(node))),
            'Imported source placement differs from the authored orientation and placement', placement=actual)
    file_frame = obj.Shape.copy(); file_frame.Placement = App.Placement()
    part = obj.Shape.copy(); part.Placement = App.Placement(matrix(node['frame']['partFromFile']))
    part_facts = facts(part)
    points = node['options']['expect'].get('points')
    observed = {**{k: part_facts[k] for k in ('volume', 'centreOfMass', 'bounds')},
                'points': {side: [_point(part.Solids[0], p, points['guard']) for p in points[side]]
                           for side in ('inside', 'outside')} if points else {}}
    evaluate(node['options']['expect'], observed, node['id']+'.options.expect')
    source_placed = facts(obj.Shape)
    record = {'sourceObject': obj.Name, 'sourceSHA256': obj.SourceSHA256, 'placement': actual,
              'fileFrame': facts(file_frame), 'part': observed, 'source': source_placed, 'refine': None}
    output = obj
    if node['options']['refine']:
        refined = doc.getObject('N'+str(index)+'Refined')
        require(refined is not None and refined.TypeId == 'Part::Refine' and refined.Source == obj,
                'Refine output is not linked to its imported source')
        require(refined.Placement.isIdentity(), 'Refine output must keep identity placement; edit the source placement')
        refined_facts = facts(refined.Shape)
        expect = node['options']['expect']
        tolerance = expect['centreOfMass']['tolerance'] if 'centreOfMass' in expect else 1e-6*(1+math.dist(
            source_placed['bounds'][0::2], source_placed['bounds'][1::2]))
        if (refined_facts['solids'] != 1 or not refined_facts['valid']
                or abs(refined_facts['volume']-source_placed['volume']) > expect['volume']['relativeTolerance']*source_placed['volume']
                or math.dist(refined_facts['centreOfMass'], source_placed['centreOfMass']) > tolerance
                or refined_facts['faces'] > source_placed['faces']):
            fail('PREPARATION_CHANGED_GEOMETRY', 'Refine changed the imported geometry instead of only merging faces',
                 node['id']+'.options.refine', before={k: source_placed[k] for k in ('volume', 'centreOfMass', 'faces')},
                 after={k: refined_facts[k] for k in ('volume', 'centreOfMass', 'faces')})
        record['refine'] = {'object': refined.Name, 'source': refined.Source.Name,
                            'placement': placement_values(refined.Placement), **{'output': refined_facts}}
        output = refined
    record['output'] = facts(output.Shape)
    record['outputObject'] = output.Name
    return record
