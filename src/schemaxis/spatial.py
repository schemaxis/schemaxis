# Copyright (C) 2026 David L F Gaden
"""Pure, declared spatial helpers shared by authoring and runtime expressions."""
import math
from schemaxis.core.directions import DIRECTION_ARGUMENT, resolve_direction
from .camera import CAMERA
from .expr import boxes

NUMBER = {'type': 'number'}
VECTOR = {'type': 'array', 'items': NUMBER, 'minItems': 3, 'maxItems': 3}
CORNERS = {'type': 'object', 'title': 'min and max corners', 'properties': {
    'min': {**VECTOR, 'required': True}, 'max': {**VECTOR, 'required': True}}}
EXTENTS = {'type': 'array', 'title': 'xmin, xmax, ymin, ymax, zmin, zmax', 'items': NUMBER,
           'minItems': 6, 'maxItems': 6}
BOUNDS = {'type': 'union', 'title': 'box', 'summary': 'A box as min and max corners, or as six extents',
          'options': [CORNERS, EXTENTS]}
ASPECT = {'type': 'array', 'items': {'type': 'number', 'minimum': 0, 'exclusiveMinimum': True}, 'minItems': 2, 'maxItems': 2}


def check(bounds):
    """Return the box as min and max corners; a flat box is valid."""
    if isinstance(bounds, (list, tuple)):
        bounds = {'min': list(bounds[0::2]), 'max': list(bounds[1::2])}
    if any(a > b for a, b in zip(bounds['min'], bounds['max'])):
        raise ValueError('bounds are invalid: min is above max on at least one axis')
    return bounds


def box(bounds):
    bounds = check(bounds)
    return boxes.Box(bounds['min'], bounds['max'])


def corners(value):
    if not value.valid:
        raise ValueError('the resulting bounds are invalid: min is above max on at least one axis')
    return {'min': list(value.min), 'max': list(value.max)}


def centre(bounds):
    return list(boxes.middle(box(bounds)))


def extent(bounds):
    return list(boxes.size(box(bounds)))


def extend(bounds, before, after):
    bounds = check(bounds)
    size = extent(bounds)
    return check({'min': [a-b*s for a,b,s in zip(bounds['min'],before,size)],
                  'max': [a+b*s for a,b,s in zip(bounds['max'],after,size)]})


def union(bounds):
    return corners(boxes.union(*[box(item) for item in bounds]))


def frame(bounds, before, after, floor, aspect):
    result = extend(bounds, before, after)
    if floor > result['min'][2]:
        raise ValueError('floor must be at or below the input bounds')
    result['min'][2] = floor
    result['max'][2] = max(result['max'][2], floor + extent(result)[1] * aspect[1]/aspect[0])
    return check(result)


def slices(bounds, axis, count):
    bounds = check(bounds)
    i = 'xyz'.index(axis)
    middle = centre(bounds)
    result = []
    for n in range(count):
        point = middle.copy()
        fraction = n/(count-1) if count > 1 else 0.5
        point[i] = (1-fraction)*bounds['min'][i] + fraction*bounds['max'][i]
        result.append(point)
    return result


def camera(bounds, direction, up, aspect, padding, parallel, distanceScale):
    bounds = check(bounds)
    size = extent(bounds)
    d = resolve_direction(direction).vector
    u = resolve_direction(up).vector
    right = [u[1]*d[2]-u[2]*d[1], u[2]*d[0]-u[0]*d[2], u[0]*d[1]-u[1]*d[0]]
    norm = math.hypot(*right)
    if norm < 1e-10: raise ValueError('camera direction and up must be nonparallel')
    right = [x/norm for x in right]
    vertical = [d[1]*right[2]-d[2]*right[1],d[2]*right[0]-d[0]*right[2],d[0]*right[1]-d[1]*right[0]]
    width = sum(abs(a)*b for a,b in zip(right,size))
    height = sum(abs(a)*b for a,b in zip(vertical,size))
    scale = max(height,width*aspect[1]/aspect[0])*0.5*(1+padding)
    distance = math.hypot(*size)*distanceScale
    if scale == 0 or distance == 0:
        raise ValueError('bounds have no extent in this view')
    return {'direction': list(d), 'up': list(u), 'focalPoint': centre(bounds),
            'bounds': [v for pair in zip(bounds['min'],bounds['max']) for v in pair],
            'parallel': parallel, 'scale': scale, 'distance': distance}


def orbit(bounds, count, elevation, aspect, padding, parallel, distanceScale):
    return [camera(bounds, {'azimuth': i*360/count, 'elevation': elevation}, 'z+',
                   aspect,padding,parallel,distanceScale) for i in range(count)]



def bounds_from_extents(extents):
    return check(extents)


def bounds_point(bounds, x, y, z):
    bounds = check(bounds)
    mid = centre(bounds)
    return [bounds['min'][i] if token == 'min' else bounds['max'][i] if token == 'max' else mid[i]
            for i, token in enumerate((x, y, z))]


def required(specification):
    return {**specification, 'required': True}


def direction_vector(direction, length):
    return [length*x for x in resolve_direction(direction).vector]


def register(registry):
    arguments = {'bounds': required(BOUNDS)}
    margins = {'before': {**VECTOR,'default':[0,0,0]}, 'after': {**VECTOR,'default':[0,0,0]}}
    view = {'aspect': {**ASPECT,'default':[16,9]}, 'padding': {'type':'number','minimum':0,'default':0.15},
            'parallel': {'type':'boolean','default':True},
            'distanceScale': {'type':'number','minimum':0,'exclusiveMinimum':True,'default':2}}
    camera_result = {'type':'object','properties':CAMERA}
    registry.register('directionVector', {'direction': required(DIRECTION_ARGUMENT),
        'length': {'type':'number','minimum':0,'default':1}}, VECTOR, direction_vector)
    registry.register('boundsFromExtents', {'extents': required(BOUNDS)}, CORNERS, bounds_from_extents)
    registry.register('boundsPoint', {**arguments, **{axis: {'type': 'enum', 'values': ['min', 'mid', 'max'], 'default': 'mid'} for axis in 'xyz'}}, VECTOR, bounds_point)
    registry.register('boundsCentre3D',arguments,VECTOR,centre)
    registry.register('boundsSize',arguments,VECTOR,extent)
    registry.register('boundsExtend',{**arguments,**margins},CORNERS,extend)
    registry.register('boundsUnion',{'bounds':required({'type':'array','items':BOUNDS,'minItems':1})},CORNERS,union)
    registry.register('boundsFrame',{**arguments,**margins,'floor':required(NUMBER),'aspect':{**ASPECT,'default':[16,9]}},CORNERS,frame)
    registry.register('slicePositions',{**arguments,'axis':{'type':'enum','values':['x','y','z'],'required':True},
        'count':{'type':'integer','minimum':1,'maximum':10000,'default':9}},
        {'type':'array','items':VECTOR},slices)
    registry.register('fitCamera',{**arguments,**view,'direction':{**DIRECTION_ARGUMENT,'default':'x+'},
        'up':{**DIRECTION_ARGUMENT,'default':'z+'}},camera_result,camera)
    registry.register('orbitCameras',{**arguments,**view,'count':{'type':'integer','minimum':1,'maximum':10000,'default':12},
        'elevation':{'type':'number','minimum':-89,'maximum':89,'default':25}},
        {'type':'array','items':camera_result},orbit)
