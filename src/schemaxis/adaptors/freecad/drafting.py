"""Finite editable Draft profiles with independent planar polygon authority."""
import math
from schemaxis.errors import fail

LIMIT=256


def declaration(factory):
    value=factory('Part::FeaturePython',{
        'points':{'type':'array','minItems':3,'maxItems':LIMIT,'required':True,
                  'items':{'type':'array','items':{'type':'number','minimum':-100000,'maximum':100000},'minItems':2,'maxItems':2}},
        'plane':{'type':'enum','values':['XY','XZ','YZ'],'default':'XY'},
        'origin':{'type':'array','items':{'type':'number','minimum':-100000,'maximum':100000},'minItems':3,'maxItems':3,'default':[0,0,0]},
        'angle':{'type':'number','minimum':-36000,'maximum':36000,'default':0}})
    value['kinds']=['profile'];return value


def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def validate(options,location):
    points=options['points'];edges=list(zip(points,points[1:]+points[:1]))
    if len({tuple(p) for p in points})!=len(points):fail('INVALID_DRAFT_PROFILE','Profile vertices must be distinct; omit the repeated closing point',location)
    def on(a,b,c):return cross(a,b,c)==0 and all(min(a[i],b[i])<=c[i]<=max(a[i],b[i]) for i in (0,1))
    for i,(a,b) in enumerate(edges):
        from .step_source import checkpoint
        checkpoint()
        for j in range(i+1,len(edges)):
            c,d=edges[j]
            if j==i+1 or i==0 and j==len(edges)-1:
                # Consecutive collinear segments may continue straight, but
                # cannot double back and overlap at their shared vertex.
                common=b if j==i+1 else a;left=a if j==i+1 else b;right=d if j==i+1 else c
                if cross(left,common,right)==0 and sum((left[k]-common[k])*(right[k]-common[k]) for k in (0,1))>0:
                    fail('INVALID_DRAFT_PROFILE','Adjacent profile edges overlap',location)
                continue
            ab,cd=(cross(a,b,c),cross(a,b,d)),(cross(c,d,a),cross(c,d,b))
            if (ab[0]*ab[1]<0 and cd[0]*cd[1]<0) or on(a,b,c) or on(a,b,d) or on(c,d,a) or on(c,d,b):
                fail('INVALID_DRAFT_PROFILE','Profile edges cross or touch away from a shared endpoint',location)
    if facts(points)['area']==0:fail('INVALID_DRAFT_PROFILE','Profile encloses no planar area',location)


def facts(points):
    # Shift before shoelace integration to avoid large-origin cancellation.
    x,y=points[0];local=[(a-x,b-y) for a,b in points]
    terms=[a[0]*b[1]-b[0]*a[1] for a,b in zip(local,local[1:]+local[:1])]
    signed=math.fsum(terms)/2
    return {'area':abs(signed),'winding':1 if signed>0 else -1,
            'perimeter':math.fsum(math.dist(a,b) for a,b in zip(points,points[1:]+points[:1]))}


def prepare(node):
    o=node['options'];r=math.radians(o['angle']);c,s=math.cos(r),math.sin(r)
    bases={'XY':[[1,0,0],[0,1,0],[0,0,1]],'XZ':[[1,0,0],[0,0,-1],[0,1,0]],'YZ':[[0,0,1],[1,0,0],[0,1,0]]}
    base=bases[o['plane']];spin=[[c,-s,0],[s,c,0],[0,0,1]]
    node['profile']={**facts(o['points']),'frame':{'rotation':[[sum(base[i][k]*spin[k][j] for k in range(3)) for j in range(3)] for i in range(3)],'translation':list(o['origin'])}}


def placement(node):
    f=node['profile']['frame'];r=f['rotation'];t=f['translation']
    return [*r[0],t[0],*r[1],t[1],*r[2],t[2]]


def verify_inventory(record,node):
    """Bind all fresh local vertices, straight boundary edges and face winding."""
    def require(value,message):
        if not value:fail('VERIFICATION_FAILED',message,node['id'])
    require(isinstance(record,dict) and set(record)=={'vertices','edges','normal','planar','faces','wires','area','perimeter'},'Draft profile geometry inventory differs')
    points=[[x,y,0] for x,y in node['options']['points']];vertices=record['vertices'];edges=record['edges']
    require(isinstance(vertices,list) and len(vertices)==len(points) and isinstance(edges,list) and len(edges)==len(points),'Draft profile topology count differs')
    require(record['planar'] is True and type(record['faces']) is int and record['faces']==1 and type(record['wires']) is int and record['wires']==1,'Draft profile must retain one planar face and one closed boundary')
    mapped=[]
    for point in vertices:
        require(isinstance(point,list) and len(point)==3 and all(type(v) in (int,float) and math.isfinite(v) for v in point),'Draft profile vertex is invalid')
        candidates=[i for i,p in enumerate(points) if all(abs(a-b)<=64*max(math.ulp(a),math.ulp(b),math.ulp(1.0)) for a,b in zip(point,p))]
        require(len(candidates)==1,'Draft profile vertex does not uniquely match its typed polygon');mapped.append(candidates[0])
    require(len(set(mapped))==len(points),'Draft profile vertices are not a bijection')
    expected={tuple(sorted((i,(i+1)%len(points)))) for i in range(len(points))};seen=set()
    for edge in edges:
        require(isinstance(edge,dict) and set(edge)=={'vertices','straight'} and edge['straight'] is True,'Draft profile boundary is not straight')
        ids=edge['vertices'];require(isinstance(ids,list) and len(ids)==2 and all(type(i) is int and 0<=i<len(points) for i in ids),'Draft profile edge vertex link differs')
        key=tuple(sorted(mapped[i] for i in ids));require(key in expected and key not in seen,'Draft profile edges do not match its typed polygon');seen.add(key)
    normal=record['normal'];require(isinstance(normal,list) and len(normal)==3 and all(type(v) in (int,float) and math.isfinite(v) for v in normal),'Draft profile normal is invalid')
    require(abs(normal[0])<=64*math.ulp(1.) and abs(normal[1])<=64*math.ulp(1.) and abs(normal[2]-node['profile']['winding'])<=64*math.ulp(1.),'Draft profile face winding differs')
    from .adaptor import close
    require(close(record['area'],node['profile']['area']) and close(record['perimeter'],node['profile']['perimeter']),'Draft profile area or perimeter differs from its independent polygon')
