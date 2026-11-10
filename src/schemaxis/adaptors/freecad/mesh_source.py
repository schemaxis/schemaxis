"""Bounded STL geometry admission before any native topology construction.

STL normals and colour attributes do not establish geometry; vertex winding does.
Closed directed edges and vertex links are checked independently of the kernel.
Self-intersection and shell nesting still require the native solid/BOP checks.
"""
import hashlib
import io
import math
import re
import struct
from schemaxis.errors import fail
from .step_source import checkpoint

MAX_BYTES = 32*1024*1024
MAX_FACETS = 20000  # Initial conversion envelope; qualify before increasing.
NUMBER = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?')


def _number(token, location):
    if len(token)>128 or NUMBER.fullmatch(token) is None:
        fail('INVALID_MESH','STL contains a malformed numeric token',location)
    value=float(token)
    if not math.isfinite(value):fail('INVALID_MESH','STL contains a nonfinite coordinate or normal',location)
    return value


def _ascii(data, location):
    try:text=data.decode('utf-8-sig')
    except UnicodeDecodeError:fail('INVALID_MESH','Use binary STL or UTF-8 ASCII STL',location)
    stream=io.StringIO(text,newline=None);line_count=0
    def line():
        nonlocal line_count
        for value in stream:
            line_count+=1
            if line_count%2048==0:checkpoint()
            if len(value)>1024:fail('INVALID_MESH','ASCII STL line exceeds 1024 characters',location)
            value=value.strip()
            if value:return value
        return None
    header=line()
    if header is None or len(header)>256 or header.split(maxsplit=1)[0].lower()!='solid':
        fail('INVALID_MESH','ASCII STL must start with solid',location)
    result=[]
    while True:
        value=line()
        if value is None:fail('INVALID_MESH','ASCII STL lacks endsolid',location)
        words=value.split()
        if words[0].lower()=='endsolid':
            if len(value)>256 or line() is not None:fail('INVALID_MESH','ASCII STL has trailing or oversized solid data',location)
            return result
        if len(result)>=MAX_FACETS:fail('INVALID_MESH','ASCII STL exceeds the conversion facet limit',location,limit=MAX_FACETS)
        if len(words)!=5 or [w.lower() for w in words[:2]]!=['facet','normal']:
            fail('INVALID_MESH','Expected an STL facet normal',location)
        for token in words[2:]:_number(token,location)
        value=line()
        if value is None or value.lower().split()!=['outer','loop']:
            fail('INVALID_MESH','Expected an STL outer loop',location)
        triangle=[]
        for _ in range(3):
            value=line();words=value.split() if value is not None else []
            if len(words)!=4 or words[0].lower()!='vertex':fail('INVALID_MESH','Each STL facet requires three vertices',location)
            triangle.append(tuple(_number(token,location) for token in words[1:]))
        endloop,endfacet=line(),line()
        if endloop is None or endfacet is None or endloop.lower()!='endloop' or endfacet.lower()!='endfacet':
            fail('INVALID_MESH','STL facet termination is malformed',location)
        result.append(tuple(triangle))


def triangles(data, location):
    if not isinstance(data,bytes) or not 1<=len(data)<=MAX_BYTES:
        fail('INVALID_MESH','STL must contain at most 32 MiB of data',location)
    if len(data)>=84:
        count=struct.unpack_from('<I',data,80)[0]
        # A binary header may begin with "solid". Exact binary size wins.
        if len(data)==84+50*count:
            if not 4<=count<=MAX_FACETS:fail('INVALID_MESH','STL facet count is outside the conversion envelope',location,facets=count,limit=MAX_FACETS)
            result=[]
            for index,record in enumerate(struct.iter_unpack('<12fH',memoryview(data)[84:])):
                if index%2048==0:checkpoint()
                if not all(math.isfinite(v) for v in record[:12]):fail('INVALID_MESH','STL contains nonfinite coordinates or normals',location)
                result.append((tuple(record[3:6]),tuple(record[6:9]),tuple(record[9:12])))
            return 'binary',result
    return 'ascii',_ascii(data,location)


def admit(data, location, *, scale=1, reverse=False):
    """Return independent mesh facts plus dense safe native points/indices."""
    try:valid_scale=type(scale) in (int,float) and math.isfinite(scale) and scale>0
    except OverflowError:valid_scale=False
    if not valid_scale or type(reverse) is not bool:
        fail('INVALID_MESH','Use a positive finite scale and explicit winding direction',location)
    encoding,raw=triangles(data,location)
    if not 4<=len(raw)<=MAX_FACETS:fail('INVALID_MESH','A closed mesh needs at least four facets',location)
    vertices=[];lookup={};faces=[];seen=set();directed={};links={};areas=[]
    low=[math.inf]*3;high=[-math.inf]*3
    for index,triangle in enumerate(raw):
        if index%2048==0:checkpoint()
        ids=[]
        for point in triangle:
            p=tuple(v*scale for v in point)
            if not all(math.isfinite(v) and abs(v)<=100000 for v in p):
                fail('INVALID_MESH','Converted mesh coordinates must be finite and within 100000 mm',location)
            if p not in lookup:lookup[p]=len(vertices);vertices.append(p)
            ids.append(lookup[p])
            for k in range(3):low[k]=min(low[k],p[k]);high[k]=max(high[k],p[k])
        if reverse:ids[1],ids[2]=ids[2],ids[1]
        a,b,c=ids;key=tuple(sorted(ids))
        if len(set(ids))!=3 or key in seen:fail('INVALID_MESH','Mesh has a degenerate or duplicate facet',location)
        seen.add(key);p,q,r=(vertices[i] for i in ids)
        u=[q[k]-p[k] for k in range(3)];v=[r[k]-p[k] for k in range(3)]
        cross=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
        area=math.hypot(*cross)/2
        if not math.isfinite(area) or area<=0:fail('INVALID_MESH','Mesh contains a collinear or nonfinite facet',location)
        areas.append(area);faces.append(tuple(ids))
        for x,y in [(a,b),(b,c),(c,a)]:
            if (x,y) in directed:fail('INVALID_MESH','Mesh has inconsistent winding or a nonmanifold edge',location)
            directed[x,y]=index
        for x,y,z in [(a,b,c),(b,c,a),(c,a,b)]:links.setdefault(x,[]).append((y,z))
    if any((b,a) not in directed for a,b in directed):
        fail('INVALID_MESH','Mesh must have closed, consistently oriented edges',location)
    for vertex,edges in links.items():
        onward=dict(edges)
        if len(onward)!=len(edges) or len({b for a,b in edges})!=len(edges):fail('INVALID_MESH','Mesh has a nonmanifold vertex',location)
        start=next(iter(onward));current=start;visited=set()
        while current not in visited:
            if current not in onward:fail('INVALID_MESH','Mesh vertex link is open',location)
            visited.add(current);current=onward[current]
        if current!=start or len(visited)!=len(edges):fail('INVALID_MESH','Mesh has disconnected fans at a vertex',location)
    origin=[(a+b)/2 for a,b in zip(low,high)];volumes=[];moments=[[],[],[]]
    for index,face in enumerate(faces):
        if index%2048==0:checkpoint()
        a,b,c=[[vertices[i][k]-origin[k] for k in range(3)] for i in face]
        value=(a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0]))/6
        volumes.append(value)
        for k in range(3):moments[k].append(value*(a[k]+b[k]+c[k])/4)
    volume=math.fsum(volumes)
    if not math.isfinite(volume) or volume<=0:
        fail('INVALID_MESH','Mesh winding must enclose positive material volume; explicitly reverse globally inverted winding',location)
    centre=[math.fsum(axis)/volume+origin[k] for k,axis in enumerate(moments)]
    if not all(math.isfinite(v) for v in centre):
        fail('INVALID_MESH','Mesh mass integrals are nonfinite or uninformative',location)
    facts={'format':'stl.'+encoding,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),
           'vertices':len(vertices),'facets':len(faces),'volume':volume,'area':math.fsum(areas),
           'centreOfMass':centre,'bounds':[value for pair in zip(low,high) for value in pair]}
    checkpoint()
    return facts,vertices,faces
