# Copyright (C) 2026 David L F Gaden
"""Pure, declared spatial helpers shared by authoring and runtime expressions."""
import math
from schemaxis.core.directions import DIRECTION_ARGUMENT, resolve_direction
from .camera import CAMERA

NUMBER = {'type': 'number'}
VECTOR = {'type': 'array', 'items': NUMBER, 'minItems': 3, 'maxItems': 3}
BOUNDS = {'type': 'object', 'properties': {
    'min': {**VECTOR, 'required': True}, 'max': {**VECTOR, 'required': True}}}
ASPECT = {'type': 'array', 'items': {'type': 'number', 'minimum': 0, 'exclusiveMinimum': True}, 'minItems': 2, 'maxItems': 2}


def check(bounds):
    if any(a >= b for a, b in zip(bounds['min'], bounds['max'])):
        raise ValueError('bounds must have positive extent along all three axes')
    return bounds


def centre(bounds):
    check(bounds)
    return [a / 2 + b / 2 for a, b in zip(bounds['min'], bounds['max'])]


def extent(bounds):
    check(bounds)
    return [b-a for a,b in zip(bounds['min'], bounds['max'])]


def extend(bounds, before, after):
    size = extent(bounds)
    return check({'min': [a-b*s for a,b,s in zip(bounds['min'],before,size)],
                  'max': [a+b*s for a,b,s in zip(bounds['max'],after,size)]})


def union(bounds):
    for box in bounds: check(box)
    return {'min': [min(b['min'][i] for b in bounds) for i in range(3)],
            'max': [max(b['max'][i] for b in bounds) for i in range(3)]}


def frame(bounds, before, after, floor, aspect):
    box = extend(bounds, before, after)
    if floor > box['min'][2]:
        raise ValueError('floor must be at or below the input bounds')
    box['min'][2] = floor
    box['max'][2] = max(box['max'][2], floor + extent(box)[1] * aspect[1]/aspect[0])
    return check(box)


def slices(bounds, axis, count):
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
    return {'direction': list(d), 'up': list(u), 'focalPoint': centre(bounds),
            'bounds': [v for pair in zip(bounds['min'],bounds['max']) for v in pair],
            'parallel': parallel, 'scale': max(height,width*aspect[1]/aspect[0])*0.5*(1+padding),
            'distance': math.hypot(*size)*distanceScale}


def orbit(bounds, count, elevation, aspect, padding, parallel, distanceScale):
    return [camera(bounds, {'azimuth': i*360/count, 'elevation': elevation}, 'z+',
                   aspect,padding,parallel,distanceScale) for i in range(count)]


def register(registry):
    required = lambda spec: {**spec, 'required': True}
    box = {'bounds': required(BOUNDS)}
    margins = {'before': {**VECTOR,'default':[0,0,0]}, 'after': {**VECTOR,'default':[0,0,0]}}
    view = {'aspect': {**ASPECT,'default':[16,9]}, 'padding': {'type':'number','minimum':0,'default':0.15},
            'parallel': {'type':'boolean','default':True},
            'distanceScale': {'type':'number','minimum':0,'exclusiveMinimum':True,'default':2}}
    camera_result = {'type':'object','properties':CAMERA}
    registry.register('directionVector', {'direction': required(DIRECTION_ARGUMENT),
        'length': {'type':'number','minimum':0,'default':1}}, VECTOR,
        lambda direction,length: [length*x for x in resolve_direction(direction).vector])
    registry.register('boundsCentre3D',box,VECTOR,centre)
    registry.register('boundsSize',box,VECTOR,extent)
    registry.register('boundsExtend',{**box,**margins},BOUNDS,extend)
    registry.register('boundsUnion',{'bounds':required({'type':'array','items':BOUNDS,'minItems':1})},BOUNDS,union)
    registry.register('boundsFrame',{**box,**margins,'floor':required(NUMBER),'aspect':{**ASPECT,'default':[16,9]}},BOUNDS,frame)
    registry.register('slicePositions',{**box,'axis':{'type':'enum','values':['x','y','z'],'required':True},
        'count':{'type':'integer','minimum':1,'maximum':10000,'default':9}},
        {'type':'array','items':VECTOR},slices)
    registry.register('fitCamera',{**box,**view,'direction':{**DIRECTION_ARGUMENT,'default':'x+'},
        'up':{**DIRECTION_ARGUMENT,'default':'z+'}},camera_result,camera)
    registry.register('orbitCameras',{**box,**view,'count':{'type':'integer','minimum':1,'maximum':10000,'default':12},
        'elevation':{'type':'number','minimum':-89,'maximum':89,'default':25}},
        {'type':'array','items':camera_result},orbit)
