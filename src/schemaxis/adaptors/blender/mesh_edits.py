"""Finite base-mesh editing recipes and deterministic, native-free replay.

Selections refer to the current stage's local coordinates and canonical edges.
The saved result is editable geometry; the recipe is not a native feature tree.
"""
import copy
import itertools
import math
from schemaxis.core.declarations import validate_arguments
from schemaxis.errors import fail, keys
from schemaxis.schema import arguments_schema
from .mesh_data import NAME,array,edges_for
from .node_catalogue import number,integer,boolean,choice,text,vector

LIMIT=100000
def required(spec):return {**{k:v for k,v in spec.items() if k!='default'},'required':True}
SELECT_COMMON={'domain':choice('FACE',['POINT','EDGE','FACE']),'invert':boolean()}
SELECTORS={
 'all':{},
 'indices':{'indices':{**array({'type':'integer','minimum':0},LIMIT,1),'required':True}},
 'box':{'minimum':required(vector()),'maximum':required(vector()),'test':choice('center',['center','contained'])},
 'normal':{'direction':{**vector((0,0,1))},'angle':number(0,minimum=0,maximum=math.pi)},
 'boundary':{},
 'material':{'slots':{**array({'type':'integer','minimum':0,'maximum':32767},32768,1),'required':True}},
}
OPERATIONS={
 'transform':{'translation':vector(),'rotation':vector(),'scale':vector((1,1,1)),'pivot':vector()},
 'extrudeFaces':{'offset':{**vector((0,0,1))},'keepBase':boolean()},
 'insetFaces':{'distance':required(number(.1,minimum=1e-12))},
 'splitFaces':{},'triangulate':{},
 'bridgeLoops':{'twist':integer(0,minimum=0,maximum=99999),'smooth':boolean()},
 'bisect':{'point':vector(),'normal':vector((0,0,1)),'side':choice('positive',['positive','negative']),'cap':boolean(True),'capMaterial':integer(0,minimum=0,maximum=32767),'tolerance':number(1e-8,minimum=1e-12,maximum=1)},
 'mergeVertices':{'distance':number(.001,minimum=1e-12)},
 'delete':{'deleteOrphans':boolean(True)},
 'normals':{'mode':choice('consistent',['consistent','outward','flip'])},
 'shade':{'smooth':boolean(True)},
}
COMMON={'object':{**NAME,'required':True},'sourceObject':text(),
 'sharing':choice('refuse',['refuse','copy','shared']),
 'dataPolicy':choice('refuse',['refuse','discard'])}


def union(variants,common=None):
    out=[]
    for kind,props in variants.items():
        branch=arguments_schema({**(common or {}),**props})
        branch['properties']['kind']={'const':kind};branch.setdefault('required',[]).append('kind');out.append(branch)
    return {'oneOf':out}


def schema_property():
    steps=[]
    for kind,props in OPERATIONS.items():
        select={'oneOf':[]}
        for selected,options in SELECTORS.items():
            common={**SELECT_COMMON,'domain':choice(selection_domain(kind,selected),['POINT','EDGE','FACE'])}
            select['oneOf'].extend(union({selected:options},common)['oneOf'])
        branch=arguments_schema({'id':{**NAME,'required':True},**props})
        branch['properties'].update(kind={'const':kind},selection=select)
        branch.setdefault('required',[]).extend(['kind','selection']);steps.append(branch)
    target=arguments_schema(COMMON);target['properties']['steps']=array({'oneOf':steps},64,1);target.setdefault('required',[]).append('steps')
    return array(target,256)


def selection_domain(operation,selection):
    if selection=='boundary':return 'EDGE'
    if selection in ('normal','material'):return 'FACE'
    return 'POINT' if operation=='mergeVertices' else 'EDGE' if operation=='bridgeLoops' else 'FACE'


def validate(value,kinds,where='production.meshEdits'):
    if not isinstance(value,list) or len(value)>256:fail('INVALID_MESH_EDIT','meshEdits must contain at most256 target records',where)
    out=[];seen=set()
    for i,item in enumerate(value):
        loc=f'{where}[{i}]';keys(item,(*COMMON,'steps'),loc)
        target=validate_arguments(COMMON,{k:v for k,v in item.items() if k in COMMON},location=loc)
        if kinds.get(target['object']) not in ('mesh','instance','asset'):fail('TYPE_MISMATCH','mesh editing requires a mesh or captured asset part',loc)
        if target['sourceObject'] and kinds[target['object']]!='asset':fail('INVALID_MESH_EDIT','sourceObject selects a captured asset member',loc)
        identity=(target['object'],target['sourceObject'])
        if identity in seen:fail('INVALID_MESH_EDIT','combine one target into one ordered edit recipe',loc)
        seen.add(identity);steps=item.get('steps');target['steps']=[];ids=set()
        if not isinstance(steps,list) or not 1<=len(steps)<=64:fail('INVALID_MESH_EDIT','provide one to64 finite edit stages',loc)
        for j,step in enumerate(steps):
            here=f'{loc}.steps[{j}]';kind=step.get('kind') if isinstance(step,dict) else None
            if kind not in OPERATIONS:fail('INVALID_MESH_EDIT','choose a reviewed mesh edit operation',here)
            keys(step,('id','kind','selection',*OPERATIONS[kind]),here)
            normalized=validate_arguments({'id':{**NAME,'required':True},**OPERATIONS[kind]},{k:v for k,v in step.items() if k not in ('kind','selection')},location=here)
            if normalized['id'] in ids:fail('DUPLICATE_ID','edit stage IDs must be distinct',here)
            ids.add(normalized['id']);s=step.get('selection');sk=s.get('kind') if isinstance(s,dict) else None
            if sk not in SELECTORS:fail('INVALID_MESH_EDIT','choose a reviewed element selection',here)
            common={**SELECT_COMMON,'domain':choice(selection_domain(kind,sk),['POINT','EDGE','FACE'])}
            selected=validate_arguments({**common,**SELECTORS[sk]},{k:v for k,v in s.items() if k!='kind'},location=here+'.selection')
            if sk in ('normal','material') and selected['domain']!='FACE' or sk=='boundary' and selected['domain']!='EDGE':fail('INVALID_MESH_EDIT','normal/material select faces; boundary selects edges',here)
            if sk=='indices' and len(set(selected['indices']))!=len(selected['indices']):fail('INVALID_MESH_EDIT','selection indices must be distinct',here)
            if sk=='material' and len(set(selected['slots']))!=len(selected['slots']):fail('INVALID_MESH_EDIT','material slots must be distinct',here)
            if sk=='box' and any(a>b for a,b in zip(selected['minimum'],selected['maximum'])):fail('INVALID_MESH_EDIT','box minimum must not exceed maximum',here)
            if sk=='normal' and not dot(selected['direction'],selected['direction']):fail('INVALID_MESH_EDIT','normal direction must be nonzero',here)
            required='FACE' if kind in ('extrudeFaces','insetFaces','splitFaces','triangulate','normals','shade','bisect') else 'EDGE' if kind=='bridgeLoops' else 'POINT' if kind=='mergeVertices' else None
            if required and selected['domain']!=required:fail('INVALID_MESH_EDIT','operation needs '+required+' selection',here)
            if kind=='transform' and any(x==0 for x in normalized['scale']):fail('INVALID_MESH_EDIT','transform scale must be nonsingular',here)
            if kind=='bisect' and not normalized['cap'] and normalized['capMaterial']!=0:fail('INVALID_MESH_EDIT','cap material requires capped bisect',here)
            if kind=='bisect' and not dot(normalized['normal'],normalized['normal']):fail('INVALID_MESH_EDIT','bisect plane normal must be nonzero',here)
            if kind=='extrudeFaces' and not dot(normalized['offset'],normalized['offset']):fail('INVALID_MESH_EDIT','extrusion offset must be nonzero',here)
            target['steps'].append({'kind':kind,**normalized,'selection':{'kind':sk,**selected}})
        out.append(target)
    return out


def dot(a,b):return sum(x*y for x,y in zip(a,b))
def sub(a,b):return [x-y for x,y in zip(a,b)]
def cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
def length(a):return math.hypot(*a)
def unit(a):
    n=length(a)
    if not n or not math.isfinite(n):fail('INVALID_MESH_EDIT','selected polygon or edge is degenerate or exceeds finite geometry arithmetic')
    return [x/n for x in a]


def normal(points):
    return unit([sum((p[(i+1)%3]-q[(i+1)%3])*(p[(i+2)%3]+q[(i+2)%3]) for p,q in zip(points,points[1:]+points[:1])) for i in range(3)])


def mesh(vertices,faces,edges=None,materials=None,smooth=None):
    faces=copy.deepcopy(faces);vertices=copy.deepcopy(vertices);boundary=set(edges_for(faces));loose=sorted({tuple(sorted(e)) for e in edges or []}-boundary)
    result={'vertices':vertices,'faces':faces,'looseEdges':[list(e) for e in loose],
            'materials':list(materials) if materials is not None else [0]*len(faces),
            'smooth':list(smooth) if smooth is not None else [False]*len(faces)}
    admit(result);return result


def admit(m,require_area=False):
    vertices=m['vertices'];faces=m['faces']
    if max(len(vertices),len(faces),sum(map(len,faces)))>LIMIT:fail('RESOURCE_BUDGET_EXCEEDED','mesh editing exceeds100000 vertices/faces/corners')
    face_edges=set(edges_for(faces));m['looseEdges']=[list(edge) for edge in sorted({tuple(sorted(e)) for e in m['looseEdges']}-face_edges)]
    edges=all_edges(m)
    if len(edges)>LIMIT:fail('RESOURCE_BUDGET_EXCEEDED','mesh editing exceeds100000 vertices/edges/faces/corners')
    if len(m['materials'])!=len(faces) or len(m['smooth'])!=len(faces):fail('INVALID_MESH_EDIT','face data membership differs')
    if any(len(p)!=3 or any(not math.isfinite(x) for x in p) for p in vertices):fail('INVALID_MESH_EDIT','mesh positions must remain finite3D coordinates')
    for f in faces:
        if len(f)<3 or len(set(f))!=len(f) or any(type(i) is not int or not 0<=i<len(vertices) for i in f):fail('INVALID_MESH_EDIT','polygon indices are invalid or duplicated')
    if require_area:
        for f in faces:normal([vertices[i] for i in f])
    for e in edges:
        if len(e)!=2 or e[0]==e[1] or any(type(i) is not int or not 0<=i<len(vertices) for i in e):fail('INVALID_MESH_EDIT','edge endpoints are invalid')


def geometry_matches(actual,expected):
    """Exact topology/data; float32 positions use mesh span, never large origin."""
    if not isinstance(actual,dict) or actual.keys()!=expected.keys() or any(actual[k]!=expected[k] for k in expected if k!='vertices'):return False
    a,b=actual['vertices'],expected['vertices']
    if not isinstance(a,list) or len(a)!=len(b):return False
    span=max((max(p[i] for p in b)-min(p[i] for p in b) for i in range(3)),default=0) if b else 0
    tolerance=span*1e-6
    return all(isinstance(x,list) and len(x)==len(y)==3 and all(type(v) in (int,float) and math.isfinite(v) and abs(v-w)<=tolerance for v,w in zip(x,y)) for x,y in zip(a,b))


def all_edges(m):return sorted(set(edges_for(m['faces']))|{tuple(e) for e in m['looseEdges']})


def select(m,s):
    domain=s['domain'];elements=[[i] for i in range(len(m['vertices']))] if domain=='POINT' else all_edges(m) if domain=='EDGE' else m['faces'];kind=s['kind'];result=[]
    if kind=='indices' and max(s['indices'])>=len(elements):fail('INVALID_MESH_SELECTION','selection index exceeds current stage topology',domain)
    degrees={}
    if kind=='boundary':
        for f in m['faces']:
            for e in zip(f,f[1:]+f[:1]):e=tuple(sorted(e));degrees[e]=degrees.get(e,0)+1
    direction=unit(s['direction']) if kind=='normal' else None;indexed=set(s.get('indices',[]));slots=set(s.get('slots',[]))
    for i,element in enumerate(elements):
        points=[m['vertices'][v] for v in element]
        if kind=='all':chosen=True
        elif kind=='indices':chosen=i in indexed
        elif kind=='material':chosen=m['materials'][i] in slots
        elif kind=='boundary':chosen=degrees.get(tuple(element),0)<=1
        elif kind=='normal':chosen=dot(normal(points),direction)>=math.cos(s['angle'])-1e-12
        else:
            tested=points if s['test']=='contained' else [[sum(p[a] for p in points)/len(points) for a in range(3)]]
            chosen=all(all(lo<=x<=hi for x,lo,hi in zip(p,s['minimum'],s['maximum'])) for p in tested)
        if chosen!=s['invert']:result.append(i)
    if not result:fail('EMPTY_MESH_SELECTION','selection matches no elements in the current edit stage')
    return result


def selected_vertices(m,s,indices):
    if s['domain']=='POINT':return indices
    elements=all_edges(m) if s['domain']=='EDGE' else m['faces']
    return sorted({v for i in indices for v in elements[i]})


def compact(m,removed=(),orphans=False):
    removed=set(removed)
    if orphans:removed|=set(range(len(m['vertices'])))-{v for f in m['faces'] for v in f}-{v for e in m['looseEdges'] for v in e}
    mapping={v:i for i,v in enumerate(v for v in range(len(m['vertices'])) if v not in removed)}
    m['vertices']=[p for i,p in enumerate(m['vertices']) if i in mapping]
    m['faces']=[[mapping[v] for v in f] for f in m['faces']];m['looseEdges']=[sorted(mapping[v] for v in e) for e in m['looseEdges']]


def face_records(m):return list(zip(m['faces'],m['materials'],m['smooth']))
def set_faces(m,records):
    m['faces']=[list(f) for f,_,_ in records];m['materials']=[a for _,a,_ in records];m['smooth']=[s for _,_,s in records]


def transform(p,s):
    p=[(x-c)*scale for x,c,scale in zip(p,s['pivot'],s['scale'])]
    for axis,angle in enumerate(s['rotation']):
        a,b=((1,2),(2,0),(0,1))[axis];x,y=p[a],p[b];p[a]=math.cos(angle)*x-math.sin(angle)*y;p[b]=math.sin(angle)*x+math.cos(angle)*y
    return [x+c+t for x,c,t in zip(p,s['pivot'],s['translation'])]


def planar(points):
    """Project a nondegenerate planar polygon to its own orthonormal basis."""
    n=normal(points);u=unit(sub(points[1],points[0]));v=cross(n,u);span=max(length(sub(p,points[0])) for p in points)
    if any(abs(dot(sub(p,points[0]),n))>max(span,1e-30)*1e-6 for p in points):fail('INVALID_MESH_EDIT','operation requires planar polygons')
    projected=[[dot(sub(p,points[0]),u),dot(sub(p,points[0]),v)] for p in points]
    simple_polygon(projected)
    return projected,u,v


def orient(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def simple_polygon(points):
    """Refuse crossing/touching nonadjacent boundaries before polygon operations."""
    count=len(points)
    if count*(count-3)//2>1000000:fail('RESOURCE_BUDGET_EXCEEDED','polygon boundary intersection check exceeds bounded work')
    def on_segment(a,b,p):return min(a[0],b[0])<=p[0]<=max(a[0],b[0]) and min(a[1],b[1])<=p[1]<=max(a[1],b[1])
    for i,(a,b) in enumerate(zip(points,points[1:]+points[:1])):
        if a==b:fail('INVALID_MESH_EDIT','polygon has a zero-length boundary')
        for j in range(i+1,count):
            if j==i+1 or i==0 and j==count-1:continue
            c,d=points[j],points[(j+1)%count];ab_c=orient(a,b,c);ab_d=orient(a,b,d);cd_a=orient(c,d,a);cd_b=orient(c,d,b)
            proper=(ab_c>0 and ab_d<0 or ab_c<0 and ab_d>0) and (cd_a>0 and cd_b<0 or cd_a<0 and cd_b>0)
            touching=any(value==0 and on_segment(x,y,p) for value,x,y,p in ((ab_c,a,b,c),(ab_d,a,b,d),(cd_a,c,d,a),(cd_b,c,d,b)))
            if proper or touching:fail('INVALID_MESH_EDIT','polygon boundary crosses, overlaps or touches a nonadjacent edge')


def triangles(m,face):
    if len(face)==3:return [face]
    points,_,_=planar([m['vertices'][i] for i in face]);remaining=list(range(len(face)));out=[];work=0
    while len(remaining)>3:
        found=False
        for at,b in enumerate(remaining):
            a=remaining[at-1];c=remaining[(at+1)%len(remaining)];work+=len(remaining)
            if work>1000000:fail('RESOURCE_BUDGET_EXCEEDED','polygon triangulation exceeds bounded search work')
            if orient(points[a],points[b],points[c])<=0:continue
            if any(all(orient(points[x],points[y],points[p])>=0 for x,y in ((a,b),(b,c),(c,a))) for p in remaining if p not in (a,b,c)):continue
            out.append([face[a],face[b],face[c]]);remaining.pop(at);found=True;break
        if not found:fail('INVALID_MESH_EDIT','triangulation needs a simple planar polygon without overlapping edges')
    out.append([face[i] for i in remaining]);return out


def inset(m,face,distance):
    if len(face)>256:fail('RESOURCE_BUDGET_EXCEEDED','individual inset polygons have at most256corners')
    points,u,v=planar([m['vertices'][i] for i in face]);lines=[]
    for a,b in zip(points,points[1:]+points[:1]):
        edge=sub(b,a);n=length(edge)
        if not n:fail('INVALID_MESH_EDIT','inset polygon has a zero-length boundary')
        direction=[x/n for x in edge];left=[-direction[1],direction[0]]
        lines.append(([a[j]+distance*left[j] for j in (0,1)],direction))
    if any(orient(points[i-1],points[i],points[(i+1)%len(points)])<=0 for i in range(len(points))):fail('INVALID_MESH_EDIT','individual distance inset currently requires convex polygons')
    inner=[]
    for previous,current in zip(lines[-1:]+lines[:-1],lines):
        a,d=previous;b,e=current;det=d[0]*e[1]-d[1]*e[0]
        if not det:fail('INVALID_MESH_EDIT','inset boundaries are parallel or degenerate')
        delta=sub(b,a);t=(delta[0]*e[1]-delta[1]*e[0])/det;point=[a[j]+t*d[j] for j in (0,1)]
        if any(orient(origin,[origin[j]+direction[j] for j in (0,1)],point)<-distance*1e-6 for origin,direction in lines):fail('INVALID_MESH_EDIT','inset distance collapses or crosses its polygon')
        inner.append([m['vertices'][face[0]][j]+point[0]*u[j]+point[1]*v[j] for j in range(3)])
    if any(length(sub(a,b))<=distance*1e-9 for a,b in zip(inner,inner[1:]+inner[:1])):fail('INVALID_MESH_EDIT','inset distance collapses its polygon')
    return inner


def weld(m,selected,distance):
    # Select the earliest existing representative within distance, using a
    # bounded spatial search. Do not infer transitive merging across a chain.
    buckets={};mapping={i:i for i in range(len(m['vertices']))};work=0
    for i in selected:
        p=m['vertices'][i]
        if any(not math.isfinite(x/distance) for x in p):fail('INVALID_MESH_EDIT','merge coordinate/radius ratio exceeds finite spatial arithmetic')
        cell=tuple(math.floor(x/distance) for x in p);candidates=[]
        for delta in itertools.product((-1,0,1),repeat=3):
            candidates.extend(buckets.get(tuple(a+b for a,b in zip(cell,delta)),[]))
        work+=len(candidates)
        if work>1000000:fail('RESOURCE_BUDGET_EXCEEDED','merge proximity exceeds bounded comparison work')
        near=[j for j in candidates if length(sub(p,m['vertices'][j]))<=distance]
        if near:mapping[i]=min(near)
        else:buckets.setdefault(cell,[]).append(i)
    records=[]
    for face,material,smooth in face_records(m):
        remapped=[mapping[i] for i in face];clean=[v for at,v in enumerate(remapped) if v!=remapped[at-1]]
        if len(set(clean))<3:continue
        if len(set(clean))!=len(clean):fail('INVALID_MESH_EDIT','merge creates a pinched polygon; split or delete it explicitly')
        records.append((clean,material,smooth))
    set_faces(m,records);m['looseEdges']=[list(e) for e in sorted({tuple(sorted(mapping[i] for i in edge)) for edge in m['looseEdges']}) if e[0]!=e[1]]
    compact(m,{i for i,v in mapping.items() if i!=v})


def recalculate(m,selected,outward):
    selected=set(selected);edges={};adjacency={i:[] for i in selected}
    for i in selected:
        face=m['faces'][i]
        for a,b in zip(face,face[1:]+face[:1]):edges.setdefault(tuple(sorted((a,b))),[]).append((i,a<b))
    if any(len(owners)>2 for owners in edges.values()):fail('INVALID_MESH_EDIT','normal consistency requires a manifold selected surface')
    for owners in edges.values():
        if len(owners)==2:
            (a,da),(b,db)=owners;adjacency[a].append((b,da==db));adjacency[b].append((a,da==db))
    visited={}
    for seed in sorted(selected):
        if seed in visited:continue
        visited[seed]=False;pending=[seed];component=[]
        while pending:
            current=pending.pop();component.append(current)
            for other,opposite in adjacency[current]:
                flip=visited[current]^opposite
                if other in visited:
                    if visited[other]!=flip:fail('INVALID_MESH_EDIT','selected surface is not consistently orientable')
                else:visited[other]=flip;pending.append(other)
        for i in component:
            if visited[i]:m['faces'][i].reverse()
        if outward:
            component_edges={tuple(sorted(e)) for i in component for e in zip(m['faces'][i],m['faces'][i][1:]+m['faces'][i][:1])}
            if any(len(edges[e])!=2 for e in component_edges):fail('INVALID_MESH_EDIT','outward normals require a closed selected component')
            volume=0
            for i in component:
                f=m['faces'][i];a=m['vertices'][f[0]]
                for b,c in zip(f[1:],f[2:]):volume+=dot(a,cross(m['vertices'][b],m['vertices'][c]))/6
            if not volume:fail('INVALID_MESH_EDIT','outward normals require nonzero enclosed volume')
            if volume<0:
                for i in component:m['faces'][i].reverse()


def apply(m,stage):
    s=stage['selection'];selected=select(m,s);chosen=set(selected);kind=stage['kind'];faces=face_records(m)
    if kind=='transform':
        for i in selected_vertices(m,s,selected):m['vertices'][i]=transform(m['vertices'][i],stage)
    elif kind=='extrudeFaces':
        verts=selected_vertices(m,s,selected);count=sum(len(faces[i][0]) for i in selected)
        if len(m['vertices'])+len(verts)>LIMIT or sum(map(len,m['faces']))+4*count>LIMIT:fail('RESOURCE_BUDGET_EXCEEDED','extrusion exceeds mesh domain budget before allocation')
        links={}
        for i in selected:
            f=faces[i][0]
            for a,b in zip(f,f[1:]+f[:1]):links.setdefault(tuple(sorted((a,b))),[]).append((a,b,i))
        if any(len(v)>2 or len(v)==2 and v[0][:2]!=tuple(reversed(v[1][:2])) for v in links.values()):fail('INVALID_MESH_EDIT','region extrusion requires consistently oriented manifold selection')
        boundary=[v[0] for v in links.values() if len(v)==1]
        if not boundary:fail('INVALID_MESH_EDIT','region extrusion requires a surface boundary')
        if stage['keepBase']:
            all_counts={}
            for face in m['faces']:
                for edge in zip(face,face[1:]+face[:1]):edge=tuple(sorted(edge));all_counts[edge]=all_counts.get(edge,0)+1
            if any(all_counts[tuple(sorted((a,b)))]!=1 for a,b,_ in boundary):fail('INVALID_MESH_EDIT','keepBase requires an isolated surface boundary; it would create nonmanifold edges')
        remap={v:len(m['vertices'])+i for i,v in enumerate(verts)}
        m['vertices'].extend([[x+d for x,d in zip(m['vertices'][v],stage['offset'])] for v in verts])
        records=[r for i,r in enumerate(faces) if i not in chosen]
        if stage['keepBase']:records.extend((list(reversed(f)),a,sm) for i,(f,a,sm) in enumerate(faces) if i in chosen)
        records.extend(([remap[v] for v in f],a,sm) for i,(f,a,sm) in enumerate(faces) if i in chosen)
        records.extend(([a,b,remap[b],remap[a]],faces[i][1],faces[i][2]) for a,b,i in boundary);set_faces(m,records)
    elif kind in ('insetFaces','splitFaces'):
        corners=sum(len(faces[i][0]) for i in selected)
        if len(m['vertices'])+corners>LIMIT or kind=='insetFaces' and sum(map(len,m['faces']))+4*corners>LIMIT:fail('RESOURCE_BUDGET_EXCEEDED','face editing exceeds mesh domain budget before allocation')
        records=[]
        for i,(f,a,sm) in enumerate(faces):
            if i not in chosen:records.append((f,a,sm));continue
            points=inset(m,f,stage['distance']) if kind=='insetFaces' else [list(m['vertices'][v]) for v in f]
            new=list(range(len(m['vertices']),len(m['vertices'])+len(f)));m['vertices'].extend(points);records.append((new,a,sm))
            if kind=='insetFaces':records.extend(([x,y,new[(at+1)%len(f)],new[at]],a,sm) for at,(x,y) in enumerate(zip(f,f[1:]+f[:1])))
        set_faces(m,records)
    elif kind=='triangulate':
        set_faces(m,[(part,a,sm) for i,(f,a,sm) in enumerate(faces) for part in (triangles(m,f) if i in chosen else [f])])
    elif kind=='bridgeLoops':bridge(m,selected,stage)
    elif kind=='bisect':bisect(m,selected,stage)
    elif kind=='mergeVertices':weld(m,selected,stage['distance'])
    elif kind=='delete':
        removed=set(selected) if s['domain']=='POINT' else set();edge_list=all_edges(m);removed_edges={tuple(edge_list[i]) for i in selected} if s['domain']=='EDGE' else set()
        def retained(i,f):return not (s['domain']=='FACE' and i in chosen or removed&set(f) or any(tuple(sorted(e)) in removed_edges for e in zip(f,f[1:]+f[:1])))
        set_faces(m,[r for i,r in enumerate(faces) if retained(i,r[0])]);m['looseEdges']=[e for e in m['looseEdges'] if not removed&set(e) and tuple(e) not in removed_edges];compact(m,removed,stage['deleteOrphans'])
    elif kind=='normals':
        if stage['mode']=='flip':
            for i in selected:m['faces'][i].reverse()
        else:recalculate(m,selected,stage['mode']=='outward')
    elif kind=='shade':
        for i in selected:m['smooth'][i]=stage['smooth']
    admit(m,require_area=True);return {'id':stage['id'],'kind':kind,'selected':len(selected),'vertices':len(m['vertices']),'faces':len(m['faces']),'edges':len(all_edges(m))}


def replay(base,stages):
    m=copy.deepcopy(base);admit(m);history=[]
    for stage in stages:history.append(apply(m,stage))
    return m,history


def owned_geometry(objects,targets=None):
    """Resolve ownership first; materialize only edited constructor groups."""
    groups={};constructors={};pending=list(objects)
    while pending:
        ready=[o for o in pending if o['kind']!='instance' or o['source'] not in {x['id'] for x in pending}]
        if not ready:fail('DEPENDENCY_CYCLE','instance constructor dependency cycle')
        for o in ready:
            identity=o['id'];kind=o['kind']
            if kind=='mesh':groups[identity]=identity;constructors[identity]=o
            elif kind=='instance' and o['source'] in groups:
                source=groups[o['source']];group=source if o['linked'] else identity;groups[identity]=group;constructors[group]=constructors[source]
            pending.remove(o)
    selected=set(groups.values()) if targets is None else {groups[t] for t in targets if t in groups}
    geometry={};uv={};total=0
    for group in sorted(selected):
        o=constructors[group];total+=len(o['vertices'])+sum(map(len,o['faces']))
        if total>1000000:fail('RESOURCE_BUDGET_EXCEEDED','aggregate edited constructor domains exceed one million elements')
        geometry[group]=mesh(o['vertices'],o['faces'],smooth=[o['smooth']]*len(o['faces']));uv[group]=bool(o.get('uv'))
    return groups,geometry,uv


def owned_plan(edits,objects):
    if not edits:return {}
    groups,geometry,uv=owned_geometry(objects,[s['object'] for s in edits]);shared=set();out={}
    for target in edits:
        identity=target['object']
        if identity not in groups:continue
        group=groups[identity]
        if target['sharing']=='refuse' and sum(g==group for g in groups.values())>1:fail('SHARED_MESH_DATA','mesh editing needs explicit copy/shared ownership')
        if target['sharing']!='copy':
            if group in shared:fail('SHARED_MESH_DATA','multiple edit declarations would write one shared Mesh')
            shared.add(group)
        for stage in target['steps']:
            if stage['kind']=='bisect' and stage['cap'] and stage['capMaterial']!=0:fail('INVALID_MESH_EDIT','owned constructors have only material slot zero')
        if uv[group] and target['dataPolicy']!='discard':fail('UNSUPPORTED_MESH_EDIT_DATA','existing UV maps need explicit dataPolicy:discard before topology editing')
    for target in sorted(edits,key=lambda s:s['sharing']!='copy'):
        identity=target['object']
        if identity not in groups:continue
        group=groups[identity];owners=[o for o,g in groups.items() if g==group]
        if target['sharing']=='refuse' and len(owners)>1:fail('SHARED_MESH_DATA','mesh editing needs explicit copy/shared ownership')
        if target['sharing']=='copy':
            new=('edit-copy',identity);geometry[new]=copy.deepcopy(geometry[group]);uv[new]=uv[group];groups[identity]=group=new;owners=[identity]
        geometry[group],_=replay(geometry[group],target['steps']);uv[group]=False
        for owner in owners:out[owner]=geometry[group]
    return out


def verify(spec,actual):
    edits=spec.get('meshEdits',[]);records=actual.get('meshEdits',[]);baselines=actual.get('meshEditBaselines',[])
    if not isinstance(records,list) or len(records)!=len(edits) or not isinstance(baselines,list) or len(baselines)!=len(edits):fail('VERIFICATION_FAILED','mesh edit/readback baseline membership differs')
    if not edits:return {}
    initial_groups,initial_geometry,_=owned_geometry(spec['objects'],[s['object'] for s in edits]);groups={};current={};target_names={};expected={}
    for s,b,r in zip(edits,baselines,records):
        identity={k:s[k] for k in COMMON}
        if {k:b.get(k) for k in COMMON}!=identity or {k:r.get(k) for k in COMMON}!=identity or b.get('nativeObject')!=r.get('nativeObject'):fail('VERIFICATION_FAILED','mesh edit target/baseline identity differs')
        name=b['nativeObject'];owners=b.get('owners')
        if not isinstance(owners,list) or owners!=sorted(set(owners)) or name not in owners:fail('VERIFICATION_FAILED','mesh edit source ownership is malformed')
        base=b['geometry'];admit(base)
        if s['object'] in initial_groups and not geometry_matches(base,initial_geometry[initial_groups[s['object']]]):fail('VERIFICATION_FAILED','mesh edit baseline differs from original constructor')
        group=tuple(owners)
        for owner in owners:
            if owner in groups and groups[owner]!=group:fail('VERIFICATION_FAILED','mesh edit source ownership groups conflict')
            groups[owner]=group
        if group in current and not geometry_matches(current[group],base):fail('VERIFICATION_FAILED','shared mesh edit baselines disagree')
        current[group]=base;target_names[(s['object'],s['sourceObject'])]=name
    if len(set(target_names.values()))!=len(target_names):fail('VERIFICATION_FAILED','mesh edit selectors resolve to one Object twice')
    for s in sorted(edits,key=lambda s:s['sharing']!='copy'):
        name=target_names[(s['object'],s['sourceObject'])];group=groups[name];owners=[o for o,g in groups.items() if g==group]
        if s['sharing']=='refuse' and len(owners)>1:fail('VERIFICATION_FAILED','mesh editing changed shared data without ownership intent')
        if s['sharing']=='copy':
            new=('copy',name);current[new]=current[group];groups[name]=group=new;owners=[name]
        current[group],_=replay(current[group],s['steps'])
        for owner in owners:expected[owner]=current[group]
    # Field copy-on-write can split a final ownership group without changing
    # the edited topology. Field readback resolves its native target separately.
    for s,r in zip(spec['meshData'],actual['meshData']):
        if s['sharing']=='copy' and r['nativeObject'] in groups:groups[r['nativeObject']]=('field-copy',r['nativeObject'])
    assignments=list(zip(spec.get('materialAssignments',[]),actual.get('materialAssignments',[])))
    for s,r in assignments:
        if s['kind']=='layout' and s['sharing']=='copy' and r['nativeObject'] in groups:groups[r['nativeObject']]=('material-copy',r['nativeObject'])
    for s,b,r in zip(edits,baselines,records):
        name=target_names[(s['object'],s['sourceObject'])];owners=sorted(o for o,g in groups.items() if g==groups[name])
        geometry=expected[name]
        if type(b.get('materialOverride')) is not bool:fail('VERIFICATION_FAILED','mesh edit material-binding proof is malformed')
        if b['materialOverride']:geometry={**geometry,'materials':[0]*len(geometry['faces'])};expected[name]=geometry
        from .material_assignments import indices as material_indices
        for assignment,readback in assignments:
            if assignment['kind']=='layout' and name in readback['owners']:
                geometry={**geometry,'materials':material_indices(assignment,'FACE',len(geometry['faces']),geometry)};expected[name]=geometry
        if not geometry_matches(r['geometry'],geometry) or r.get('owners')!=owners:fail('VERIFICATION_FAILED','edited geometry or final sharing differs from trusted source replay')
    return expected


def loops_from_edges(edges):
    adjacency={}
    for a,b in edges:adjacency.setdefault(a,set()).add(b);adjacency.setdefault(b,set()).add(a)
    if any(len(v)!=2 for v in adjacency.values()):fail('INVALID_MESH_EDIT','selected boundaries must form disjoint closed loops')
    loops=[];visited=set()
    for seed in sorted(adjacency):
        if seed in visited:continue
        loop=[seed];visited.add(seed);previous=seed;current=min(adjacency[seed])
        while current!=seed:
            if current in visited:fail('INVALID_MESH_EDIT','selected boundary crosses or repeats a vertex')
            loop.append(current);visited.add(current);following=adjacency[current]-{previous};previous,current=current,next(iter(following))
        if len(loop)<3:fail('INVALID_MESH_EDIT','boundary loops need at least three vertices')
        loops.append(loop)
    return loops


def edge_owners(m):
    owners={}
    for i,face in enumerate(m['faces']):
        for a,b in zip(face,face[1:]+face[:1]):owners.setdefault(tuple(sorted((a,b))),[]).append((i,a,b))
    return owners


def bridge(m,selected,stage):
    edges=all_edges(m);selected_edges=[edges[i] for i in selected];loops=loops_from_edges(selected_edges);owners=edge_owners(m)
    if len(loops)!=2 or len(loops[0])!=len(loops[1]):fail('INVALID_MESH_EDIT','bridge requires exactly two closed loops with equal vertex counts')
    if any(len(owners.get(edge,[]))>1 for edge in selected_edges):fail('INVALID_MESH_EDIT','bridge edges must be surface boundaries or loose loops')
    count=len(loops[0])
    if stage['twist']>=count:fail('INVALID_MESH_EDIT','bridge twist exceeds loop correspondence count')
    if sum(map(len,m['faces']))+4*count>LIMIT:fail('RESOURCE_BUDGET_EXCEEDED','bridge exceeds mesh corner budget before allocation')
    def oriented(loop,follow):
        existing=[(a,b,owners[tuple(sorted((a,b)))][0]) for a,b in zip(loop,loop[1:]+loop[:1]) if owners.get(tuple(sorted((a,b))))]
        if existing:
            a,b,(_,x,y)=existing[0]
            if ((a,b)==(x,y))!=follow:loop=[loop[0],*reversed(loop[1:])]
            if any(((a,b)==tuple(owners[tuple(sorted((a,b)))][0][1:]))!=follow for a,b in zip(loop,loop[1:]+loop[:1]) if owners.get(tuple(sorted((a,b))))):fail('INVALID_MESH_EDIT','bridge boundary winding is inconsistent; recalculate normals first')
        return loop
    first=oriented(loops[0],True);second=oriented(loops[1],False);second=second[stage['twist']:]+second[:stage['twist']]
    adjacent=owners.get(tuple(sorted(first[:2])),[]);material=m['materials'][adjacent[0][0]] if adjacent else 0
    records=face_records(m)
    for i in range(count):records.append(([first[(i+1)%count],first[i],second[i],second[(i+1)%count]],material,stage['smooth']))
    set_faces(m,records)


def component_volume(m,faces):
    result=0
    for index in faces:
        f=m['faces'][index];a=m['vertices'][f[0]]
        for b,c in zip(f[1:],f[2:]):result+=dot(a,cross(m['vertices'][b],m['vertices'][c]))/6
    return result


def bisect(m,selected,stage):
    chosen=set(selected);owners=edge_owners(m);adjacency={i:set() for i in selected}
    for edge,records in owners.items():
        active=[i for i,_,_ in records if i in chosen]
        if active and (len(records)>2 or len(active)!=len(records)):fail('INVALID_MESH_EDIT','bisect selects complete manifold face components')
        if not active:continue
        if stage['cap'] and (len(records)!=2 or records[0][1:]!=tuple(reversed(records[1][1:]))):fail('INVALID_MESH_EDIT','capped bisect requires closed consistently oriented source components')
        for i in active:adjacency[i].update(j for j in active if j!=i)
    if stage['cap']:
        visited=set()
        for seed in sorted(chosen):
            if seed in visited:continue
            pending=[seed];visited.add(seed);component=[]
            while pending:
                current=pending.pop();component.append(current)
                for other in adjacency[current]-visited:visited.add(other);pending.append(other)
            if component_volume(m,component)<=0:fail('INVALID_MESH_EDIT','capped bisect requires outward nonzero-volume source components')
    n=unit(stage['normal']);sign=1 if stage['side']=='positive' else -1;epsilon=stage['tolerance'];point=stage['point']
    distances={i:sign*dot(sub(p,point),n) for i,p in enumerate(m['vertices'])};intersections={};records=[];active_faces=set()
    def intersection(a,b):
        if abs(distances[a])<=epsilon:return a
        if abs(distances[b])<=epsilon:return b
        edge=tuple(sorted((a,b)))
        if edge not in intersections:
            if len(m['vertices'])>=LIMIT:fail('RESOURCE_BUDGET_EXCEEDED','bisect exceeds mesh vertex budget before allocation')
            t=distances[a]/(distances[a]-distances[b]);index=len(m['vertices']);m['vertices'].append([x+t*(y-x) for x,y in zip(m['vertices'][a],m['vertices'][b])]);distances[index]=0;intersections[edge]=index
        return intersections[edge]
    for i,(face,material,smooth) in enumerate(face_records(m)):
        if i not in chosen:records.append((face,material,smooth));continue
        inside=[distances[v]>=-epsilon for v in face]
        if all(inside):active_faces.add(len(records));records.append((face,material,smooth));continue
        if not any(inside):continue
        points,_,_=planar([m['vertices'][v] for v in face]);convex=all(orient(points[j-1],points[j],points[(j+1)%len(points)])>=0 for j in range(len(points)))
        for polygon in ([face] if convex else triangles(m,face)):
            clipped=[]
            for a,b in zip(polygon[-1:]+polygon[:-1],polygon):
                ia=distances[a]>=-epsilon;ib=distances[b]>=-epsilon
                if ia!=ib:clipped.append(intersection(a,b))
                if ib:clipped.append(b)
            clipped=[v for at,v in enumerate(clipped) if v!=clipped[at-1]]
            if len(set(clipped))>=3:
                if len(set(clipped))!=len(clipped):fail('INVALID_MESH_EDIT','plane clipping creates a pinched polygon')
                active_faces.add(len(records));records.append((clipped,material,smooth))
    set_faces(m,records)
    if stage['cap']:
        boundaries=[edge for edge,records in edge_owners(m).items() if len(records)==1 and records[0][0] in active_faces and all(abs(distances[v])<=epsilon for v in edge)]
        loops=loops_from_edges(boundaries) if boundaries else []
        if loops:
            # Nested loops require a reviewed cap-with-holes policy. Filling
            # each separately would silently close a cavity and change volume.
            origin=m['vertices'][loops[0][0]];u=unit(sub(m['vertices'][loops[0][1]],origin));v=cross(n,u)
            projected=[[[dot(sub(m['vertices'][i],origin),u),dot(sub(m['vertices'][i],origin),v)] for i in loop] for loop in loops]
            work=sum(len(a)*len(b) for i,a in enumerate(projected) for b in projected[i+1:])
            if work>1000000:fail('RESOURCE_BUDGET_EXCEEDED','cap loop containment exceeds bounded work')
            def contains(p,polygon):
                inside=False
                for a,b in zip(polygon,polygon[1:]+polygon[:1]):
                    if (a[1]>p[1])!=(b[1]>p[1]) and p[0]<(b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0]:inside=not inside
                return inside
            if any(contains(a[0],b) or contains(b[0],a) for i,a in enumerate(projected) for b in projected[i+1:]):fail('UNSUPPORTED_MESH_EDIT_DATA','nested plane-cut cap loops require reviewed hole-preserving filling; use cap:false')
            records=face_records(m)
            for loop in loops:
                if dot(normal([m['vertices'][i] for i in loop]),n)*sign>0:loop=list(reversed(loop))
                active_faces.add(len(records));records.append((loop,stage['capMaterial'],False))
            set_faces(m,records)
    if stage['cap'] and active_faces:
        # A cut tangent to a solid can leave two coincident faces. Demand actual
        # closed, consistently oriented, positive-volume result components.
        adjacency={i:set() for i in active_faces}
        for edge,records in edge_owners(m).items():
            active=[i for i,_,_ in records if i in active_faces]
            if not active:continue
            if len(records)!=2 or len(active)!=2 or records[0][1:]!=tuple(reversed(records[1][1:])):fail('INVALID_MESH_EDIT','plane cap did not produce a closed consistently oriented surface')
            for i in active:adjacency[i].update(j for j in active if j!=i)
        visited=set()
        for seed in sorted(active_faces):
            if seed in visited:continue
            component=[];pending=[seed];visited.add(seed)
            while pending:
                current=pending.pop();component.append(current)
                for other in adjacency[current]-visited:visited.add(other);pending.append(other)
            if component_volume(m,component)<=0:fail('INVALID_MESH_EDIT','plane cut leaves a zero-thickness or inverted capped component')
    compact(m,orphans=True)
