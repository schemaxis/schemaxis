"""Additional literal CAD contracts and topology-independent input checks."""
import math
from schemaxis.errors import fail


def extend(declaration, length, vector):
    positive = lambda default: {**length, 'default': default}
    origin = {'origin': vector}
    axial = {**origin, 'axis': {**vector, 'default': [0, 0, 1]}}
    from .selections import EDGES
    edges = EDGES
    polygon = declaration('Sketcher::SketchObject', {
        'points': {'type': 'array', 'items': {'type':'array','items':{'type':'number'},'minItems':2,'maxItems':2}, 'minItems':3,'maxItems':100,'required':True},
        'plane': {'type':'enum','values':['XY','XZ','YZ'],'default':'XY'}, **origin})
    polygon['kinds'] = ['profile']
    rectangle = declaration('Sketcher::SketchObject', {
        'width': positive(80), 'height': positive(50),
        'plane': {'type':'enum','values':['XY','XZ','YZ'],'default':'XY'}, **origin})
    circle = declaration('Sketcher::SketchObject', {
        'radius': positive(5),
        'plane': {'type':'enum','values':['XY','XZ','YZ'],'default':'XY'}, **origin})
    rectangle['kinds'] = circle['kinds'] = ['profile']
    for profile in (rectangle,circle):profile['inputs']['body']={'required':False,'kind':'body'}
    circle['options']['centre']={'value':{'type':'array','items':{'type':'number','minimum':-100000,'maximum':100000},'minItems':2,'maxItems':2}}
    result = {
        'sphere': declaration('Part::Sphere', {'radius': positive(10), **origin}),
        'cone': declaration('Part::Cone', {'radius1': positive(10), 'radius2': {'type':'number','minimum':0,'maximum':100000,'default':5}, 'height': positive(20), **axial}),
        'torus': declaration('Part::Torus', {'majorRadius': positive(20), 'minorRadius': positive(5), **axial}),
        'common': declaration('Part::Common', {}, ('base','tool')),
        'polygon': polygon,
        'rectangle': rectangle,
        'circle': circle,
        'extrude': declaration('Part::Extrusion', {'length':positive(10), 'direction':{**vector,'default':[0,0,1]}}, ('profile',)),
        'revolve': declaration('Part::Revolution', {'angle':{'type':'number','minimum':0,'exclusiveMinimum':True,'maximum':360,'default':360}, **axial}, ('profile',)),
        'fillet': declaration('Part::Fillet', {'radius':positive(1), 'edges':edges}, ('base',)),
        'chamfer': declaration('Part::Chamfer', {'distance':positive(1), 'edges':edges}, ('base',)),
        'readSTEP': declaration('Part::Feature', {'file':{'type':'string','minLength':1,'required':True}}),
    }
    result['loft'] = declaration('Part::Loft', {'ruled': {'type': 'boolean', 'default': False}}, ('sections',))
    result['loft']['inputs']['sections'].update(kind='profile', multiple=True, minItems=2, maxItems=32)
    result['multiFuse'] = declaration('Part::MultiFuse', {'refine': {'type': 'boolean', 'default': True}}, ('shapes',))
    result['multiFuse']['inputs']['shapes'].update(multiple=True, minItems=2, maxItems=32)
    for op in ('extrude','revolve'):
        result[op]['inputs']['profile']['kind']='profile'
    from .part_design import declarations
    result.update(declarations(declaration,length))
    from .step_import import declaration as import_declaration
    result['importSTEP'] = import_declaration(declaration)
    return result


def extra_objects(prepared):
    """Native objects beyond one N<index> per node: the parametric refine of an import."""
    return {'N'+str(i)+'Refined': 'Part::Refine' for i, node in enumerate(prepared['nodes'])
            if node['filter'] == 'importSTEP' and node['options']['refine']}


def output_names(prepared):
    """Native object carrying each node's result shape."""
    return {node['id']: 'N'+str(i)+('Refined' if node['filter'] == 'importSTEP' and node['options']['refine'] else '')
            for i, node in enumerate(prepared['nodes'])}


def validate(operation, options, identity):
    if operation in ('fillet', 'chamfer'):
        from .selections import validate as validate_selection
        validate_selection(options['edges'], identity+'.edges')
    for field in ('axis','direction'):
        if field in options and math.hypot(*options[field]) < 1e-12:
            fail('INVALID_AXIS', 'CAD direction must be nonzero', identity)
    if operation == 'torus' and options['minorRadius'] >= options['majorRadius']:
        fail('INVALID_GEOMETRY', 'torus minor radius must be smaller than major radius', identity)
    if operation != 'polygon':
        return
    points=options['points']
    if len({tuple(p) for p in points}) != len(points):
        fail('INVALID_PROFILE', 'polygon vertices must be unique; closure is automatic', identity)
    area=sum(a[0]*b[1]-a[1]*b[0] for a,b in zip(points,points[1:]+points[:1]))/2
    if abs(area) < 1e-9:
        fail('INVALID_PROFILE', 'polygon must enclose nonzero area', identity)
    def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    def on(a,b,c):return abs(cross(a,b,c))<1e-10 and all(min(a[k],b[k])-1e-10<=c[k]<=max(a[k],b[k])+1e-10 for k in (0,1))
    def intersects(a,b,c,d):
        return (cross(a,b,c)*cross(a,b,d)<0 and cross(c,d,a)*cross(c,d,b)<0) or on(a,b,c) or on(a,b,d) or on(c,d,a) or on(c,d,b)
    segments=list(zip(points,points[1:]+points[:1]))
    for i,(a,b) in enumerate(segments):
        for j,(c,d) in enumerate(segments):
            if j>i+1 and not (i==0 and j==len(segments)-1) and intersects(a,b,c,d):
                fail('INVALID_PROFILE', 'polygon must not self-intersect or touch nonadjacent edges', identity)
