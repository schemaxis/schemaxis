# Copyright (C) 2026 David L F Gaden
"""Independent binary STL geometry checks for a bounded polygon extrusion."""
import math
import struct
from collections import Counter, defaultdict
from schemaxis.errors import fail

TOL = 0.00004  # mm: float32 STL + CGAL fixed-point conversion, bounded coordinates.


def cross(a, b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def sub(a, b): return tuple(x-y for x, y in zip(a, b))
def dot(a, b): return sum(x*y for x, y in zip(a, b))
def orient(a, b, c): return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
def bad(message): fail('VERIFICATION_FAILED', message)


def contours(p):
    n=p['segments']
    def circle(x, y, r, clockwise=False):
        result=[(x+r*math.cos(2*math.pi*k/n),y+r*math.sin(2*math.pi*k/n)) for k in range(n)]
        return list(reversed(result)) if clockwise else result
    if p['operation']=='plate':
        q=p['plate'];w,d=q['width'],q['depth']
        return [[(0.,0.),(w,0.),(w,d),(0.,d)]]+[circle(h['centre'][0],h['centre'][1],h['diameter']/2,True) for h in q['holes']]
    q=p['spacer'];return [circle(0,0,q['outerDiameter']/2),circle(0,0,q['boreDiameter']/2,True)]


def expected(p):
    rings=contours(p);area=sum(sum(a[0]*b[1]-a[1]*b[0] for a,b in zip(r,r[1:]+r[:1]))/2 for r in rings)
    q=p[p['operation']];h=q['height'];t=p['translation'];xy=[v for r in rings for v in r]
    if p['operation']=='plate':ideal=(q['width']*q['depth']-sum(math.pi*(v['diameter']/2)**2 for v in q['holes']))*h
    else:ideal=math.pi*(q['outerDiameter']**2-q['boreDiameter']**2)/4*h
    return {'bounds':[[min(v[k] for v in xy)+t[k] for k in range(2)]+[t[2]],[max(v[k] for v in xy)+t[k] for k in range(2)]+[t[2]+h]],'volume':area*h,'idealVolume':ideal,'euler':2-2*(len(rings)-1),'boundaryVertices':2*len(xy)}


def stl(data):
    if len(data)<84:bad('binary STL header missing')
    count=struct.unpack_from('<I',data,80)[0]
    if not 4<=count<=20000 or len(data)!=84+50*count:bad('binary STL triangle count/byte length invalid')
    triangles=[]
    for i in range(count):
        values=struct.unpack_from('<12fH',data,84+50*i)
        if values[-1]!=0 or not all(math.isfinite(x) for x in values[:-1]):bad('STL attributes/nonfinite coordinates unsupported')
        n=values[:3];v=[values[j:j+3] for j in (3,6,9)];normal=cross(sub(v[1],v[0]),sub(v[2],v[0]));length=math.sqrt(dot(normal,normal))
        if length<1e-9:bad('degenerate triangle')
        if abs(math.sqrt(dot(n,n))-1)>2e-5 or dot(n,normal)/length<1-2e-5:bad('facet normal disagrees with vertex winding')
        triangles.append(v)
    return triangles


def canonical_triangles(data):
    """Exact oriented facet identity, independent of facet order and start vertex.

    The qualified native STL reopen preserves float32 coordinates and each
    triangle, although record order and cyclic vertex order are representation
    choices. Reversing winding or changing the triangulation stays distinguishable.
    """
    return sorted(min(tuple(tri[k:]+tri[:k]) for k in range(3)) for tri in stl(data))


def inspect(data,p):
    tris=stl(data);rings=contours(p);xy=[v for r in rings for v in r];t=p['translation'];h=p[p['operation']]['height'];want=expected(p)
    # Every vertex must be one declared contour corner at exactly one end of the
    # extrusion. Quantisation matching is bounded and unique by feature guards.
    canonical=[(x+t[0],y+t[1],z+t[2]) for z in (0,h) for x,y in xy]
    spatial=defaultdict(list)
    for index,v in enumerate(canonical):spatial[tuple(round(c/TOL) for c in v)].append(index)
    indexed=[];coordinates={};raw_vertices=[]
    for tri in tris:
        face=[]
        for v in tri:
            key=tuple(round(c/TOL) for c in v);matches=[]
            for dx in (-1,0,1):
                for dy in (-1,0,1):
                    for dz in (-1,0,1):
                        matches.extend(i for i in spatial.get((key[0]+dx,key[1]+dy,key[2]+dz),[]) if max(abs(a-b) for a,b in zip(v,canonical[i]))<=TOL)
            if len(matches)!=1:bad('vertex leaves declared cross-section or end plane')
            i=matches[0]
            if i in coordinates and v!=coordinates[i]:bad('inconsistent coordinates create a crack')
            coordinates[i]=v;face.append(i);raw_vertices.append(v)
        indexed.append(face)
    if set(coordinates)!=set(range(len(canonical))):bad('missing declared contour vertices')
    if len({tuple(sorted(f)) for f in indexed})!=len(indexed):bad('duplicate triangle')
    edges=Counter((a,b) for f in indexed for a,b in zip(f,f[1:]+f[:1]))
    if any(a==b or count!=1 or edges[(b,a)]!=1 for (a,b),count in edges.items()):bad('surface is not an oriented closed two-manifold')
    neighbours=defaultdict(set)
    for a,b in edges:neighbours[a].add(b)
    seen={0};todo=[0]
    while todo:
        for b in neighbours[todo.pop()]-seen:seen.add(b);todo.append(b)
    if len(seen)!=len(canonical):bad('surface is disconnected')
    euler=len(canonical)-len(edges)//2+len(indexed)
    if euler!=want['euler']:bad('through-hole topology differs')
    boundary=[];offset=0
    for r in rings:
        for j,a in enumerate(r):boundary.append((offset+j,offset+(j+1)%len(r),a,r[(j+1)%len(r)]))
        offset+=len(r)
    n=len(xy);side_area=defaultdict(float)
    side_segments={frozenset((a,b)):(a,b) for a,b,_,_ in boundary}
    # A fixed 16x16 index limits contour tests to the triangle's XY envelope.
    # This is an acceleration only: every overlapping segment is still tested.
    xmin=min(v[0] for v in xy);ymin=min(v[1] for v in xy)
    dx=(max(v[0] for v in xy)-xmin)/16;dy=(max(v[1] for v in xy)-ymin)/16
    def cells(points):
        lo=[math.floor((min(v[k] for v in points)-o)/step) for k,o,step in [(0,xmin,dx),(1,ymin,dy)]]
        hi=[math.floor((max(v[k] for v in points)-o)/step) for k,o,step in [(0,xmin,dx),(1,ymin,dy)]]
        return ((x,y) for x in range(lo[0],hi[0]+1) for y in range(lo[1],hi[1]+1))
    boundary_grid=defaultdict(set)
    for index,(_,_,u,v) in enumerate(boundary):
        for cell in cells((u,v)):boundary_grid[cell].add(index)
    for tri,face in zip(tris,indexed):
        zlevels={i//n for i in face};local=[xy[i%n] for i in face]
        normal=cross(sub(tri[1],tri[0]),sub(tri[2],tri[0]))
        if len(zlevels)==2:
            segment=frozenset(i%n for i in face);match=side_segments.get(segment)
            if match is None:bad('side triangle leaves a declared boundary facet')
            a,b=match;direction=(xy[b][1]-xy[a][1],xy[a][0]-xy[b][0],0)
            if dot(normal,direction)<=0:bad('side orientation is inward')
            side_area[(a,b)]+=math.sqrt(dot(normal,normal))/2
        else:
            if normal[2]*(1 if next(iter(zlevels)) else -1)<=0:bad('end face orientation is inward')
            # Additional crossing/enclosure checks complement directed edge
            # pairing, complete oriented walls and positive end-face winding.
            # These local tests alone do not exclude every triangle inside a hole.
            aa,bb,cc=local;sign=1 if orient(aa,bb,cc)>0 else -1
            candidates=set()
            for cell in cells(local):candidates.update(boundary_grid.get(cell,()))
            lx,hx=min(v[0] for v in local),max(v[0] for v in local)
            ly,hy=min(v[1] for v in local),max(v[1] for v in local)
            for index in candidates:
                a,b,u,v=boundary[index]
                if max(u[0],v[0])<lx or min(u[0],v[0])>hx or max(u[1],v[1])<ly or min(u[1],v[1])>hy:continue
                for x,y in zip(local,local[1:]+local[:1]):
                    if orient(x,y,u)*orient(x,y,v)<-1e-14 and orient(u,v,x)*orient(u,v,y)<-1e-14:bad('end face crosses a declared contour')
                if u not in local and min(sign*orient(aa,bb,u),sign*orient(bb,cc,u),sign*orient(cc,aa,u))>1e-10:bad('end face encloses a contour corner')
    for a,b,_,_ in boundary:
        area=math.dist(xy[a],xy[b])*h
        if not math.isclose(side_area[(a,b)],area,rel_tol=.001,abs_tol=1e-7):bad('boundary wall area differs')
    # Origin-relative determinant avoids cancellation from translated small parts.
    volume=sum(dot(sub(v[0],t),cross(sub(v[1],t),sub(v[2],t)))/6 for v in tris)
    bounds=[[min(v[k] for v in raw_vertices) for k in range(3)],[max(v[k] for v in raw_vertices) for k in range(3)]]
    if any(abs(a-b)>TOL for observed,desired in zip(bounds,want['bounds']) for a,b in zip(observed,desired)):bad('bounds differ')
    if not math.isclose(volume,want['volume'],rel_tol=.0002,abs_tol=1e-7):bad('faceted analytic volume differs')
    return {'units':'mm','volumeUnits':'mm^3','bounds':bounds,'volume':volume,'expectedFacetedVolume':want['volume'],'idealCircularVolume':want['idealVolume'],'facetingVolumeError':want['volume']-want['idealVolume'],'vertices':len(canonical),'triangles':len(tris),'eulerCharacteristic':euler,'connectedComponents':1,'closedOriented':True,'coordinateTolerance_mm':TOL,'volumeRelativeTolerance':.0002,'height':h,'segments':p['segments']}
