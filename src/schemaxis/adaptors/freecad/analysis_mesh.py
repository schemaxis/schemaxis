"""Dependency-free linear tetrahedral elasticity and traction checks.

CalculiX element numbering follows its documented C3D4/C3D10 convention.
Quadratic elements use straight geometry midsides in this route, so the four
point tetrahedron rule integrates quadratic strain energy exactly.
"""
import math
from collections import Counter
from schemaxis.errors import fail

def checkpoint():
    from schemaxis.dispatch import remaining_timeout
    remaining_timeout()

EDGES=((0,1),(1,2),(2,0),(0,3),(1,3),(2,3))
FACES=((0,1,2),(0,3,1),(1,3,2),(2,3,0))
QUADRATURE=[([a if n==k else b for n in range(4)],.25) for k in range(4)
            for a,b in [((5+3*math.sqrt(5))/20,(5-math.sqrt(5))/20)]]


def dot(a,b):return math.fsum(x*y for x,y in zip(a,b))
def sub(a,b):return [x-y for x,y in zip(a,b)]
def cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
def det(a):return dot(a[0],cross(a[1],a[2]))


def inverse(a):
    d=det(a)
    if not math.isfinite(d) or d<=1e-15:fail('INVALID_MESH','Tetrahedron has a nonpositive or unresolvable Jacobian')
    c=[cross(a[1],a[2]),cross(a[2],a[0]),cross(a[0],a[1])]
    return [[c[j][i]/d for j in range(3)] for i in range(3)],d


def shape_gradients(barycentric,count):
    g=[[-1,-1,-1],[1,0,0],[0,1,0],[0,0,1]]
    if count==4:return g
    result=[[(4*barycentric[n]-1)*v for v in g[n]] for n in range(4)]
    result.extend([[4*(barycentric[a]*g[b][j]+barycentric[b]*g[a][j]) for j in range(3)] for a,b in EDGES])
    return result


def volume_and_energy(nodes,cells,displacements,material):
    e,nu=material['youngModulusMPa'],material['poissonRatio'];mu=e/(2*(1+nu));lam=e*nu/((1+nu)*(1-2*nu))
    volume=energy=maxstress=maxstrain=0.;seen=set()
    for serial,(identity,conn) in enumerate(cells.items()):
        if serial%256==0:checkpoint()
        if len(conn) not in (4,10) or len(set(conn))!=len(conn) or any(n not in nodes for n in conn):fail('INVALID_MESH','Cell connectivity is not a distinct C3D4/C3D10 tetrahedron',str(identity))
        if tuple(sorted(conn)) in seen:fail('INVALID_MESH','Duplicate tetrahedral connectivity',str(identity))
        seen.add(tuple(sorted(conn)));p=[nodes[n] for n in conn]
        j=[[p[c+1][r]-p[0][r] for c in range(3)] for r in range(3)];inv,d=inverse(j);v=d/6
        if len(conn)==10:
            for mid,(a,b) in zip(p[4:],EDGES):
                if math.dist(mid,[(x+y)/2 for x,y in zip(p[a],p[b])])>max(1e-6,max(math.dist(p[a],p[b]),1)*1e-6):fail('INVALID_MESH','Quadratic geometry midsides must be straight in this analysis contract',str(identity))
        volume+=v
        for bary,w in QUADRATURE if len(conn)==10 else [([.25]*4,1.)]:
            ref=shape_gradients(bary,len(conn));grad=[[sum(row[k]*inv[k][c] for k in range(3)) for c in range(3)] for row in ref]
            h=[[sum(displacements[n][r]*g[c] for n,g in zip(conn,grad)) for c in range(3)] for r in range(3)]
            strain=[[(h[r][c]+h[c][r])/2 for c in range(3)] for r in range(3)];trace=sum(strain[k][k] for k in range(3))
            stress=[[2*mu*strain[r][c]+(lam*trace if r==c else 0) for c in range(3)] for r in range(3)]
            density=.5*sum(strain[r][c]*stress[r][c] for r in range(3) for c in range(3));energy+=v*w*density
            vm=math.sqrt(max(0,((stress[0][0]-stress[1][1])**2+(stress[1][1]-stress[2][2])**2+(stress[2][2]-stress[0][0])**2)/2+3*(stress[0][1]**2+stress[0][2]**2+stress[1][2]**2)))
            maxstress=max(maxstress,vm);maxstrain=max(maxstrain,*(abs(x) for row in strain for x in row))
    return {'meshVolumeMM3':volume,'strainEnergyNMM':energy,'maxVonMisesMPa':maxstress,'maxStrain':maxstrain}


def boundary_faces(cells):
    faces={};counts=Counter()
    for serial,(identity,conn) in enumerate(cells.items()):
        if serial%256==0:checkpoint()
        for side,indices in enumerate(FACES,1):
            corners=[conn[i] for i in indices];key=tuple(sorted(corners));counts[key]+=1
            if counts[key]>2:fail('INVALID_MESH','Mesh has a nonmanifold tetrahedral face',str(identity))
            mids=[]
            if len(conn)==10:
                mids=[conn[4+EDGES.index(tuple(sorted((a,b))))] if tuple(sorted((a,b))) in EDGES else conn[4+next(n for n,(x,y) in enumerate(EDGES) if {x,y}=={a,b})] for a,b in zip(indices,indices[1:]+indices[:1])]
            faces[key]=(identity,side,corners+mids)
    return [faces[k] for k,c in counts.items() if c==1]


def face_weights(nodes,cells,face):
    """Consistent constant-traction nodal areas on one selected planar CAD face."""
    normal,centre=face['normal'],face['centre'];coordinate=dot(normal,centre);weights={};sides=[];area=0.
    for serial,(identity,side,conn) in enumerate(boundary_faces(cells)):
        if serial%2048==0:checkpoint()
        if not all(abs(dot(normal,nodes[n])-coordinate)<=1e-5 for n in conn):continue
        a,b,c=[nodes[n] for n in conn[:3]];triangle_area=math.hypot(*cross(sub(b,a),sub(c,a)))/2
        if triangle_area<=0:fail('INVALID_MESH','Boundary triangle is degenerate')
        area+=triangle_area;sides.append((identity,side))
        for n in conn:weights.setdefault(n,0.)
        for n in conn if len(conn)==3 else conn[3:]:weights[n]+=triangle_area/3
    if not sides or area<=0:fail('INVALID_MESH','Selected face has no boundary mesh coverage')
    if abs(area-face['area'])>max(1e-5,face['area']*.02):fail('INVALID_MESH','Selected face mesh area differs by more than 2%; refine the mesh')
    return weights,area,sides


def connectivity_key(conn):
    """Orientation-independent tetrahedron identity with exact midside ownership.

    FreeCAD's writer reverses native tetrahedral orientation where necessary;
    accepting that permutation must preserve which edge owns each midside node.
    """
    if not isinstance(conn,list) or len(conn) not in (4,10) or len(set(conn))!=len(conn):
        fail('INVALID_MESH','Native/solver tetrahedron connectivity is malformed')
    return (tuple(sorted(conn[:4])),tuple(sorted((tuple(sorted((conn[a],conn[b]))),n) for (a,b),n in zip(EDGES,conn[4:]))))


def verify_stress_field(nodes,cells,displacements,material,fields):
    """Bound averaged nodal solver stress by incident constitutive extrapolates.

    For affine T4/T10 geometry, the displacement-gradient stress is constant or
    linear. Extrapolating the four integration stresses to corners/midsides is
    therefore equivalent to evaluating that polynomial there. Native averaging
    must stay within the incident element component envelope. This checks the
    actual six-component field without claiming a particular smoothing weight.
    """
    e,nu=material['youngModulusMPa'],material['poissonRatio'];mu=e/(2*(1+nu));lam=e*nu/((1+nu)*(1-2*nu));bounds={};scale=0.
    for serial,conn in enumerate(cells.values()):
        if serial%256==0:checkpoint()
        p=[nodes[n] for n in conn];j=[[p[c+1][r]-p[0][r] for c in range(3)] for r in range(3)];inv,_=inverse(j)
        bary=[[int(k==i) for k in range(4)] for i in range(4)]
        if len(conn)==10:bary.extend([[.5 if k in edge else 0 for k in range(4)] for edge in EDGES])
        for n,b in zip(conn,bary):
            grad=[[sum(row[k]*inv[k][c] for k in range(3)) for c in range(3)] for row in shape_gradients(b,len(conn))]
            h=[[sum(displacements[node][r]*g[c] for node,g in zip(conn,grad)) for c in range(3)] for r in range(3)]
            trace=sum(h[k][k] for k in range(3));stress=[[mu*(h[r][c]+h[c][r])+(lam*trace if r==c else 0) for c in range(3)] for r in range(3)]
            vector=[stress[r][c] for r,c in ((0,0),(1,1),(2,2),(0,1),(1,2),(0,2))];scale=max(scale,*(abs(v) for v in vector))
            lo,hi=bounds.setdefault(n,([math.inf]*6,[-math.inf]*6))
            for k,v in enumerate(vector):lo[k]=min(lo[k],v);hi[k]=max(hi[k],v)
    tolerance=max(1e-7,scale*1e-4)
    if set(fields)!=set(nodes):fail('VERIFICATION_FAILED','Constitutive stress check has foreign or missing result nodes')
    for n,(lo,hi) in bounds.items():
        if len(fields[n])!=6 or any(not math.isfinite(v) or v<a-tolerance or v>b+tolerance for v,a,b in zip(fields[n],lo,hi)):
            fail('VERIFICATION_FAILED','Solver stress field is outside independently extrapolated constitutive bounds',str(n),observed=fields[n],minimum=lo,maximum=hi,toleranceMPa=tolerance)
