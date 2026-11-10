"""Typed editable classic splines, swept profiles and path dependencies.

This module has no native imports. It validates intent before native geometry is
allocated; modern Curves, Surface and implicit Metaball data are separate families.
"""
import math
from schemaxis.core.declarations import validate_arguments
from schemaxis.errors import fail
from schemaxis.pipeline import name
from .node_catalogue import number, integer, vector, boolean, choice, text

NAME={'type':'string','minLength':1,'maxLength':128}
def array(item,maximum=4096,minimum=0):return {'type':'array','items':item,'minItems':minimum,'maxItems':maximum}
def record(fields,required=()):return {'type':'object','properties':{k:{**{a:b for a,b in v.items() if a!='default' or not (k in required or v.get('required'))},**({'required':True} if k in required else {})} for k,v in fields.items()}}
def variant(kind,fields):return record({'kind':{'type':'enum','values':[kind]},**fields},['kind'])
def union(options,default=None):return {'type':'union','options':options,**({'default':default} if default is not None else {})}
def settings(fields):return {**record(fields),'default':validate_arguments(fields,{})}

HANDLE=union([variant(k,{'position':{**vector(),'required':True}} if k in ('FREE','ALIGNED') else {}) for k in ('AUTO','VECTOR','FREE','ALIGNED')],{'kind':'AUTO'})
POINT={'position':{**vector(),'required':True},'radius':number(1,minimum=0,maximum=10000),'tilt':number(0,minimum=-100000,maximum=100000)}
COMMON={'id':{**NAME,'required':True},'closed':boolean(),'reverse':boolean(),'smooth':boolean(True)}
SAMPLING={'sampling':integer(0,minimum=0,maximum=1024)}
INTERPOLATION={'radiusInterpolation':choice('LINEAR',['LINEAR','CARDINAL','BSPLINE','EASE']),'tiltInterpolation':choice('LINEAR',['LINEAR','CARDINAL','BSPLINE','EASE'])}
SPLINES=union([variant('POLY',{**COMMON,'points':{**array(record(POINT),4096,2),'required':True}}),
 variant('BEZIER',{**COMMON,**SAMPLING,**INTERPOLATION,'points':{**array(record({**POINT,'left':HANDLE,'right':HANDLE}),4096,2),'required':True}}),
 variant('NURBS',{**COMMON,**SAMPLING,'points':{**array(record({**POINT,'weight':number(1,minimum=0,exclusiveMinimum=True,maximum=1000000)}),4096,2),'required':True},
 'order':integer(3,minimum=2,maximum=6),'endpoint':boolean(True),'bezierKnots':boolean()})])
PROFILE_POINT=record({'position':{'type':'array','items':{'type':'number','minimum':0,'maximum':1},'minItems':2,'maxItems':2,'required':True},'handle':choice('AUTO',['AUTO','VECTOR'])})
DEPTH={'depth':number(.02,minimum=0,exclusiveMinimum=True,maximum=10000),'resolution':integer(4,minimum=0,maximum=32)}
BEVEL=union([variant('none',{}),variant('round',DEPTH),variant('object',{'object':{**NAME,'required':True}}),
 variant('profile',{**DEPTH,'points':{**array(PROFILE_POINT,128,2),'default':[{'position':[1,0],'handle':'AUTO'},{'position':[0,1],'handle':'AUTO'}]},
 'evenLengths':boolean(),'straightEdges':boolean()})],{'kind':'none'})
OPTIONS={'splines':{**array(SPLINES,128,1),'required':True},'dimensions':choice('3D',['3D','2D']),
 'fill':choice('AUTO',['AUTO','FULL','HALF','NONE','BOTH','BACK','FRONT']),
 'fillRule':choice('EVEN_ODD',['EVEN_ODD','NONZERO']),'fillSolver':choice('SWEEP_LINE',['SWEEP_LINE','CDT']),
 'offset':number(0,minimum=-10000,maximum=10000),'extrude':number(0,minimum=0,maximum=10000),
 'sampling':settings({'preview':integer(12,minimum=1,maximum=1024),'render':integer(0,minimum=0,maximum=1024)}),
 'bevel':BEVEL,'caps':boolean(),'twist':choice('MINIMUM',['MINIMUM','Z_UP','TANGENT']),'twistSmooth':number(0,minimum=0,maximum=64),
 'trim':settings({'start':number(0,minimum=0,maximum=1),'end':number(1,minimum=0,maximum=1),
 'startMapping':choice('RESOLUTION',['RESOLUTION','SEGMENTS','SPLINE']),'endMapping':choice('RESOLUTION',['RESOLUTION','SEGMENTS','SPLINE'])}),
 'taper':settings({'object':text(),'mode':choice('OVERRIDE',['OVERRIDE','MULTIPLY','ADD']),'mapTrim':boolean()}),
 'path':settings({'enabled':boolean(True),'duration':integer(100,minimum=1,maximum=1048574),'follow':boolean(True),'radius':boolean(True),'stretch':boolean(),'bounds':boolean()})}


def fill_mode(o):return ('BOTH' if o['dimensions']=='2D' else 'FULL') if o['fill']=='AUTO' else o['fill']


def validate(o,where):
    allowed=('NONE','BOTH','BACK','FRONT') if o['dimensions']=='2D' else ('FULL','HALF','BACK','FRONT')
    if fill_mode(o) not in allowed:fail('INVALID_SPLINE','fill mode is incompatible with curve dimensions',where+'.fill')
    if o['dimensions']=='3D' and o['offset']:fail('INVALID_SPLINE','outline offset requires a planar curve',where+'.offset')
    if o['trim']['start']>o['trim']['end']:fail('INVALID_SPLINE','trim start must not exceed end',where+'.trim')
    if o['bevel']['kind']=='none' and (o['caps'] or o['trim']!=OPTIONS['trim']['default']):fail('INVALID_SPLINE','caps and trim require swept bevel geometry',where)
    if not o['taper']['object'] and o['taper']!=OPTIONS['taper']['default']:fail('INVALID_SPLINE','taper options require a taper curve',where+'.taper')
    if o['bevel']['kind']=='none' and o['taper']['object']:fail('INVALID_SPLINE','taper requires swept bevel geometry',where+'.taper')
    if o['dimensions']=='3D' and (o['fillRule']!='EVEN_ODD' or o['fillSolver']!='SWEEP_LINE'):fail('INVALID_SPLINE','fill rule and solver choices require planar contours',where)
    if o['bevel']['kind']=='profile':
        controls=o['bevel']['points'];positions=[tuple(p['position']) for p in controls]
        if positions[0]!=(1,0) or positions[-1]!=(0,1) or len(set(positions))!=len(positions):fail('INVALID_SPLINE','quarter profile needs distinct ordered controls from (1,0) to (0,1)',where+'.bevel.points')
    if o['fillRule']=='NONZERO' and o['fillSolver']!='CDT':fail('INVALID_SPLINE','nonzero winding fill requires the CDT solver',where+'.fillSolver')
    if fill_mode(o)=='NONE' and (o['fillRule']!='EVEN_ODD' or o['fillSolver']!='SWEEP_LINE'):fail('INVALID_SPLINE','fill solver/rule choices require planar filling',where)
    seen=set();total=0
    for i,s in enumerate(o['splines']):
        loc=f'{where}.splines[{i}]';name(s['id'],loc+'.id')
        if s['id'] in seen:fail('DUPLICATE_ID','spline local identities must be distinct',loc+'.id')
        seen.add(s['id']);points=s['points'];total+=len(points)
        if (o['trim']['start']>0 or o['trim']['end']<1) and any(p['radius']!=points[0]['radius'] for p in points):fail('INVALID_SPLINE','Blender5.2 partial trim loses varying endpoint radii; use constant point radii or author shortened controls before sweeping',loc+'.points')
        if s['closed'] and len(points)<3:fail('INVALID_SPLINE','closed spline requires at least three controls',loc)
        if any(math.dist(a['position'],b['position'])==0 for a,b in zip(points,points[1:]+([points[0]] if s['closed'] else []))):fail('INVALID_SPLINE','consecutive spline controls must differ',loc)
        if o['dimensions']=='2D' and any(p['position'][2]!=0 or any(h.get('position',[0,0,0])[2]!=0 for h in (p.get('left',{}),p.get('right',{}))) for p in points):fail('INVALID_SPLINE','planar controls and handles use local XY with z zero',loc)
        if s['kind']=='NURBS':
            if s['order']>len(points):fail('INVALID_SPLINE','NURBS order cannot exceed control count',loc+'.order')
            if s['closed'] and (s['endpoint'] or s['bezierKnots']):fail('INVALID_SPLINE','cyclic NURBS uses periodic knots; disable endpoint and Bezier knots',loc)
            if s['bezierKnots'] and (s['order'] not in (3,4) or (len(points)-1)%(s['order']-1)):fail('INVALID_SPLINE','Bezier knots require quadratic or cubic complete spans',loc)
        if s['kind']=='BEZIER':
            for p in points:
                if p['left']['kind']=='ALIGNED' or p['right']['kind']=='ALIGNED':
                    if {p['left']['kind'],p['right']['kind']}-{'FREE','ALIGNED'}:fail('INVALID_SPLINE','aligned handles need two explicit positions',loc)
                    a=[x-y for x,y in zip(p['left']['position'],p['position'])];b=[x-y for x,y in zip(p['right']['position'],p['position'])]
                    cross=[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];norm=math.sqrt(sum(x*x for x in a)*sum(x*x for x in b))
                    if not norm or math.sqrt(sum(x*x for x in cross))>norm*1e-7 or sum(x*y for x,y in zip(a,b))>=0:fail('INVALID_SPLINE','aligned handles must be nonzero, opposite and collinear',loc)
    if total>16384:fail('RESOURCE_BUDGET_EXCEEDED','one curve permits at most16384 controls across its splines',where)


def dependencies(spec,kinds,where):
    """Resolve public identities; native admission proves types, cycles and cost."""
    aliases={r['id']:r for r in spec['geometryResources'] if r['kind']=='object'};result={}
    for o in spec['objects']:
        if o['kind']!='spline':continue
        refs=([o['bevel']['object']] if o['bevel']['kind']=='object' else [])+([o['taper']['object']] if o['taper']['object'] else [])
        for ref in refs:
            original=aliases.get(ref,{}).get('object',ref)
            if original not in kinds:fail('UNKNOWN_REFERENCE','profile/taper needs a declared curve Object or object geometry-resource alias',where+'.'+o['id'])
            if kinds[original] not in ('spline','curve','asset','instance'):fail('TYPE_MISMATCH','profile/taper needs classic Curve data',where+'.'+o['id'])
            result.setdefault(o['id'],set()).add(original)
    return result
