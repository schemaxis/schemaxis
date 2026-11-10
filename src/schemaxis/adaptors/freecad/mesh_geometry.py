"""Bind a freshly measured faceted BREP to admitted STL vertices and winding.

The 64 ULP allowance only covers binary coordinate serialization. It cannot
admit a different facet, edge, face winding or native topology inventory.
"""
import itertools
import math
from schemaxis.errors import fail
from .step_source import checkpoint


def verify_inventory(inventory, points, faces, location):
    def require(condition,message):
        if not condition:fail('VERIFICATION_FAILED',message,location)
    require(isinstance(inventory,dict) and set(inventory)=={'vertices','faces'},'Mesh BREP inventory differs')
    vertices=inventory['vertices'];measured=inventory['faces']
    require(isinstance(vertices,list) and len(vertices)==len(points) and isinstance(measured,list) and len(measured)==len(faces),
            'Mesh BREP vertex or facet count differs from its captured STL')
    extent=max(1,*(abs(v) for p in points for v in p));step=64*math.ulp(extent)
    def bucket(point):return tuple(math.floor(v/step) for v in point)
    grid={}
    for index,point in enumerate(points):grid.setdefault(bucket(point),[]).append(index)
    offsets=list(itertools.product((-1,0,1),repeat=3))
    def match(point):
        require(isinstance(point,list) and len(point)==3 and all(type(v) in (int,float) and math.isfinite(v) and abs(v)<=100000 for v in point),
                'Mesh BREP contains an invalid vertex')
        home=bucket(point);found=[]
        for delta in offsets:
            for index in grid.get(tuple(home[k]+delta[k] for k in range(3)),[]):
                expected=points[index]
                if all(abs(a-b)<=64*max(math.ulp(a),math.ulp(b),math.ulp(1.0)) for a,b in zip(point,expected)):found.append(index)
        require(len(found)==1,'Mesh BREP vertex does not uniquely match its captured STL')
        return found[0]
    mapped=[]
    for index,point in enumerate(vertices):
        if index%1024==0:checkpoint()
        mapped.append(match(point))
    require(len(set(mapped))==len(points),'Mesh BREP vertex inventory is not a bijection to its captured STL')
    expected={tuple(sorted(face)):face for face in faces};seen=set()
    for index,record in enumerate(measured):
        if index%1024==0:checkpoint()
        require(isinstance(record,dict) and set(record)=={'vertices','normal','planar','straight','edges','wires'},'Mesh BREP facet inventory differs')
        require(record['planar'] is True and record['straight'] is True and type(record['edges']) is int and record['edges']==3
                and type(record['wires']) is int and record['wires']==1,'Mesh BREP must retain one planar straight-edged triangle per STL facet')
        ids=record['vertices'];normal=record['normal']
        require(isinstance(ids,list) and len(ids)==3 and all(type(i) is int and 0<=i<len(vertices) for i in ids),
                'Mesh BREP facet vertex links differ')
        key=tuple(sorted(mapped[i] for i in ids))
        require(key in expected and key not in seen,'Mesh BREP facets are not a bijection to captured STL triangles')
        seen.add(key)
        require(isinstance(normal,list) and len(normal)==3 and all(type(v) in (int,float) and math.isfinite(v) for v in normal),
                'Mesh BREP facet normal differs')
        a,b,c=[points[i] for i in expected[key]];u=[b[k]-a[k] for k in range(3)];v=[c[k]-a[k] for k in range(3)]
        cross=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
        require(sum(x*y for x,y in zip(cross,normal))>0,'Mesh BREP facet winding differs from its captured STL')
    checkpoint()


def verify_placement(actual, expected, location):
    """Bind the BREP's top-level Location before measuring its local vertices."""
    if (not isinstance(actual,list) or len(actual)!=12 or len(expected)!=12
            or not all(type(a) in (int,float) and math.isfinite(a) and type(b) in (int,float) and math.isfinite(b)
                       and abs(a-b)<=64*max(math.ulp(a),math.ulp(b),math.ulp(1.0)) for a,b in zip(actual,expected))):
        fail('VERIFICATION_FAILED','Saved mesh BREP Placement differs from the authored frame',location)
