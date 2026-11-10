"""Typed location and cycle intent; no authored native indices or NC words.

This compiler is an internal CAM2 component. Registration follows complete native
construction, source binding and independent material qualification.
"""
import math
from schemaxis.errors import fail,keys
from .solid_source import number as cad_number,vector as cad_vector

CYCLES={'drill':81,'dwell':82,'peck':83,'chipBreak':73,'feedRetract':85}
DIALECT='linuxcnc-2.9.4-mm-default-cycles'
RAPID_BACKOFF=.254  # Pinned LinuxCNC2.9.4: G83_RAPID_DELTA=.010 inch.


def number(value,path,low=-100000,high=100000):
    return cad_number(value,path,low,high,code='INVALID_MACHINING')


def count(value,path,low=1,high=64):
    if type(value) is not int or not low<=value<=high:
        fail('INVALID_MACHINING','Provide a bounded integer location count',path)
    return value


def locations(raw,path):
    """Source-frame XY centres, independent of native hole traversal order."""
    if not isinstance(raw,dict):fail('INVALID_MACHINING','Declare an explicit, grid or pitchCircle layout',path)
    kind=raw.get('kind')
    if kind=='explicit':
        keys(raw,('kind','centres'),path);points=raw.get('centres')
        if not isinstance(points,list) or not 1<=len(points)<=256:
            fail('INVALID_MACHINING','Explicit drilling contains one to 256 centres',path+'.centres')
        points=[cad_vector(p,2,path+'.centres['+str(i)+']',code='INVALID_MACHINING') for i,p in enumerate(points)]
    elif kind in ('grid','pitchCircle'):
        allowed=('kind','columns','rows','xPitch','yPitch','centre') if kind=='grid' else ('kind','count','radius','phase','centre')
        keys(raw,allowed,path);centre=cad_vector(raw.get('centre',[0,0]),2,path+'.centre',code='INVALID_MACHINING')
        from .drilling import centres
        if kind=='grid':
            options={k:count(raw.get(k,2),path+'.'+k) for k in ('columns','rows')}
            options.update({k:number(raw.get(k),path+'.'+k,.001,100000) for k in ('xPitch','yPitch')})
        else:
            options={'count':count(raw.get('count',4),path+'.count',2),
                     'radius':number(raw.get('radius'),path+'.radius',.001,100000),
                     'phase':number(raw.get('phase',0),path+'.phase',-180,180)}
        options['centre']=centre
        if kind=='grid' and options['columns']*options['rows']>256:
            fail('RESOURCE_LIMIT','Drilling layouts contain at most 256 centres',path)
        points=centres('boltGrid' if kind=='grid' else 'boltCircle',options)
    else:fail('INVALID_MACHINING','Choose explicit, grid or pitchCircle locations',path+'.kind')
    if any(abs(v)>100000 for p in points for v in p):fail('INVALID_MACHINING','Generated drilling centres exceed the coordinate range',path)
    if any(math.dist(a,b)<1e-7 for i,a in enumerate(points) for b in points[i+1:]):
        fail('INVALID_MACHINING','Drilling centres must be distinct',path)
    # This is a set of geometric targets. Native CAM may traverse it in a
    # nearest-neighbour order; later checks bind every point and its cardinality.
    return sorted(points)


def compile_cycle(raw,finish,setup,path):
    keys(raw,('kind','dwell','peck','return'),path);kind=raw.get('kind','drill')
    if kind not in CYCLES:fail('INVALID_MACHINING','Choose drill, dwell, peck, chipBreak or feedRetract',path+'.kind')
    required={'dwell'} if kind=='dwell' else {'peck'} if kind in ('peck','chipBreak') else set()
    if {k for k in raw if k in ('dwell','peck')}!=required:
        fail('INVALID_MACHINING','Declare exactly the dimensions used by this drilling cycle',path)
    mode=raw.get('return','initial')
    if mode not in ('initial','retract'):fail('INVALID_MACHINING','Return to the actual initial plane or the retract plane',path+'.return')
    result={'kind':kind,'code':CYCLES[kind],'return':mode,'dwell':0,'peck':0,'retract':setup['safe']}
    if kind=='dwell':result['dwell']=number(raw['dwell'],path+'.dwell',.001,3600)
    if kind in ('peck','chipBreak'):
        result['peck']=number(raw['peck'],path+'.peck',.001,1000)
        if math.ceil((setup['safe']-finish)/result['peck'])>1000:
            fail('RESOURCE_LIMIT','One drilling cycle contains at most 1000 pecks',path+'.peck')
    return result


def operation(raw,tool,bounds,origin,setup,path):
    """Compile source-space geometric intent, retaining full blank reach policy."""
    keys(raw,('id','operation','tool','locations','bottom','cycle'),path)
    points=locations(raw.get('locations'),path+'.locations')
    bottom=number(raw.get('bottom'),path+'.bottom',bounds[4],bounds[5])
    if bottom>=bounds[5]-1e-5:fail('INVALID_MACHINING','Drilling must extend below the source top plane',path+'.bottom')
    radius=tool['diameter']/2
    if any(not(bounds[0]+radius<x<bounds[1]-radius and bounds[2]+radius<y<bounds[3]-radius) for x,y in points):
        fail('INVALID_MACHINING','Each complete cutter footprint must lie inside the pre-sized blank',path+'.locations')
    if any(math.dist(a,b)<tool['diameter']+1e-7 for i,a in enumerate(points) for b in points[i+1:]):
        fail('INVALID_MACHINING','One drilling layout must contain separated cylindrical holes',path+'.locations')
    finish=bottom-origin[2]
    return {'locations':points,'centres':[[x-origin[0],y-origin[1]] for x,y in points],
            'bottom':bottom,'start':bounds[5]-origin[2],'finish':finish,
            'cycle':compile_cycle(raw.get('cycle',{}),finish,setup,path+'.cycle')}
