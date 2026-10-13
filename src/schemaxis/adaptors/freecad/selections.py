"""Bounded geometric edge intent, resolved afresh for each native topology.

This module is host-safe. Native edge descriptors are ordinary measured data;
selection predicates and cardinality checks are replayed without FreeCAD imports.
"""
import math
from schemaxis.errors import fail

INDEX_LIST = {'type': 'array', 'items': {'type': 'integer', 'minimum': 1},
              'minItems': 1, 'maxItems': 1000, 'uniqueItems': True}
SELECTOR = {'type': 'object', 'properties': {
    'where': {'type': 'object', 'required': True, 'properties': {
        'curve': {'type': 'enum', 'values': ['line', 'circle']},
        'parallelTo': {'type': 'array', 'items': {'type': 'number', 'minimum': -1e6, 'maximum': 1e6},
                       'minItems': 3, 'maxItems': 3},
        'onPlane': {'type': 'object', 'properties': {
            'axis': {'type': 'enum', 'values': ['x', 'y', 'z'], 'required': True},
            'coordinate': {'type': 'number', 'required': True}}},
        'length': {'type': 'object', 'properties': {
            'minimum': {'type': 'number', 'minimum': 0, 'required': True},
            'maximum': {'type': 'number', 'minimum': 0, 'required': True}}}}},
    'expect': {'type': 'integer', 'minimum': 1, 'maximum': 1000, 'required': True},
    'tolerance': {'type': 'number', 'minimum': 1e-9, 'maximum': .01, 'default': 1e-6},
    'angularTolerance': {'type': 'number', 'minimum': 1e-9, 'maximum': .01, 'default': 1e-6}}}
EDGES = {'type': 'union', 'options': [INDEX_LIST, SELECTOR], 'default': [1]}


def validate(value, location):
    if isinstance(value, list): return
    where = value['where']
    if not where: fail('INVALID_SELECTION', 'declare at least one geometric edge predicate', location)
    if 'parallelTo' in where:
        if math.hypot(*where['parallelTo']) <= 1e-12:
            fail('INVALID_SELECTION', 'parallelTo requires a nonzero direction', location)
        if where.get('curve', 'line') != 'line':
            fail('INVALID_SELECTION', 'parallelTo selects straight edges only', location)
    if 'length' in where and where['length']['minimum'] > where['length']['maximum']:
        fail('INVALID_SELECTION', 'edge length interval is reversed', location)


def native_edges(shape):
    """Measure world-coordinate geometry; invoke only on a native shape."""
    if len(shape.Edges) > 10000:
        fail('RESOURCE_BUDGET_EXCEEDED', 'semantic selection is limited to 10000 source edges')
    result = []
    for index, edge in enumerate(shape.Edges):
        b = edge.optimalBoundingBox(False, False)
        result.append({'index': index+1, 'curve': type(edge.Curve).__name__,
                       'lengthMM': edge.Length, 'centreMM': list(edge.CenterOfMass),
                       'boundsMM': [b.XMin, b.XMax, b.YMin, b.YMax, b.ZMin, b.ZMax],
                       'verticesMM': [list(v.Point) for v in edge.Vertexes]})
    return result


def resolve(selector, edges, location='$'):
    """Conjoin predicates; never rank or silently choose among ambiguous matches."""
    if not isinstance(edges, list) or not 1 <= len(edges) <= 10000:
        fail('VERIFICATION_FAILED', 'missing or oversized edge inventory', location)
    for index, edge in enumerate(edges):
        if (not isinstance(edge,dict) or set(edge) != {'index', 'curve', 'lengthMM', 'centreMM', 'boundsMM', 'verticesMM'}
                or type(edge['index']) is not int or edge['index'] != index+1 or not isinstance(edge['curve'], str)
                or type(edge['lengthMM']) not in (int,float) or not math.isfinite(edge['lengthMM']) or edge['lengthMM'] <= 0):
            fail('VERIFICATION_FAILED', 'invalid edge measurement', location)
        arrays = [(edge['centreMM'], 3), (edge['boundsMM'], 6)]
        if not isinstance(edge['verticesMM'], list) or len(edge['verticesMM']) > 2:
            fail('VERIFICATION_FAILED', 'invalid edge vertices', location)
        arrays += [(point, 3) for point in edge['verticesMM']]
        if any(not isinstance(a,list) or len(a)!=n or any(type(v) not in (int,float) or not math.isfinite(v) for v in a) for a,n in arrays):
            fail('VERIFICATION_FAILED', 'invalid edge coordinates', location)
        if any(edge['boundsMM'][i] > edge['boundsMM'][i+1] for i in (0,2,4)):
            fail('VERIFICATION_FAILED', 'invalid edge bounds', location)
    if isinstance(selector, list):
        if any(index > len(edges) for index in selector): fail('INVALID_EDGE', 'edge index exceeds source topology', location)
        return list(selector)
    where, tolerance = selector['where'], selector['tolerance']
    selected = []
    for edge in edges:
        if 'curve' in where and edge['curve'] != {'line':'Line', 'circle':'Circle'}[where['curve']]: continue
        if 'onPlane' in where:
            plane = where['onPlane']; axis = 2*'xyz'.index(plane['axis'])
            if any(abs(edge['boundsMM'][k]-plane['coordinate']) > tolerance for k in (axis,axis+1)): continue
        if 'length' in where and not where['length']['minimum']-tolerance <= edge['lengthMM'] <= where['length']['maximum']+tolerance: continue
        if 'parallelTo' in where:
            if edge['curve'] != 'Line' or len(edge['verticesMM']) != 2: continue
            direction = [b-a for a,b in zip(*edge['verticesMM'])]
            norm = math.hypot(*direction)
            if norm <= 0: fail('VERIFICATION_FAILED', 'zero-length line direction', location)
            direction = [v/norm for v in direction]
            axis = where['parallelTo']; norm = math.hypot(*axis); axis = [v/norm for v in axis]
            sine = math.hypot(*(direction[i]*axis[j]-direction[j]*axis[i] for i,j in ((0,1),(1,2),(2,0))))
            if sine > selector['angularTolerance']: continue
        selected.append(edge['index'])
    if len(selected) != selector['expect']:
        code = 'EMPTY_SELECTION' if not selected else 'AMBIGUOUS_SELECTION' if len(selected) > selector['expect'] else 'SELECTION_COUNT_MISMATCH'
        fail(code, 'geometric edge selection must match the declared count; inspect predicates and source topology', location,
             expected=selector['expect'], matched=len(selected), indices=selected[:20], selector=selector)
    return selected


def native_evidence(doc, prepared):
    records = {}
    objects = {n['id']: doc.getObject('N'+str(i)) for i,n in enumerate(prepared['nodes'])}
    for node in prepared['nodes']:
        if node['filter'] not in ('fillet','chamfer') or not isinstance(node['options']['edges'], dict): continue
        edges = native_edges(objects[node['inputs']['base']].Shape)
        records[node['id']] = {'source': node['inputs']['base'], 'edges': edges,
            'indices': resolve(node['options']['edges'], edges, node['id']),
            'applied': [list(item) for item in objects[node['id']].Edges]}
    return records


def equivalent(a, b):
    if isinstance(a,dict): return isinstance(b,dict) and a.keys()==b.keys() and all(equivalent(v,b[k]) for k,v in a.items())
    if isinstance(a,list): return isinstance(b,list) and len(a)==len(b) and all(equivalent(x,y) for x,y in zip(a,b))
    if type(a) is float: return type(b) in (int,float) and math.isfinite(a) and math.isfinite(b) and math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-9)
    if type(a) is int: return type(b) in (int,float) and a==b
    return type(a) is type(b) and a==b


def verify(prepared, built, reopened):
    nodes = {n['id']:n for n in prepared['nodes'] if n['filter'] in ('fillet','chamfer') and isinstance(n['options']['edges'],dict)}
    if not isinstance(built,dict) or set(built)!=set(nodes) or not equivalent(built,reopened):
        fail('VERIFICATION_FAILED', 'semantic selection evidence differs after native reopening')
    for identity,node in nodes.items():
        record = built[identity]
        if set(record) != {'source','edges','indices','applied'} or record['source'] != node['inputs']['base']:
            fail('VERIFICATION_FAILED', 'semantic selection source differs', identity)
        selected = resolve(node['options']['edges'],record['edges'],identity)
        radius = node['options']['radius' if node['filter']=='fillet' else 'distance']
        if selected != record['indices'] or not equivalent([[i,radius,radius] for i in selected],record['applied']):
            fail('VERIFICATION_FAILED', 'native finishing edges differ from geometric intent', identity)
