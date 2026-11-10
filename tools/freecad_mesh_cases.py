"""Independent closed STL fixtures and analytic material oracles for Mesh→Part."""
import math,struct
from pathlib import Path


def stl(triangles, *, binary=False):
    if binary:
        return b'Independent mesh preparation fixture'.ljust(80,b' ')+struct.pack('<I',len(triangles))+b''.join(
            struct.pack('<12fH',0,0,0,*[v for p in triangle for v in p],0) for triangle in triangles)
    lines=['solid mesh_preparation']
    for triangle in triangles:
        lines.extend(['facet normal 0 0 0','outer loop',*['vertex '+' '.join(format(v,'.15g') for v in p) for p in triangle],'endloop','endfacet'])
    return ('\n'.join([*lines,'endsolid mesh_preparation'])+'\n').encode()


def voxel_bracket(dx=6,dy=4,dz=5):
    # Three non-overlapping analytic rectangular regions: base, rear wall and
    # side wall. Interior voxel faces are omitted, retaining a closed L bracket.
    cells={(i,j,k) for i in range(6) for j in range(4) for k in range(4) if k==0 or i==0 or j==0}
    surfaces=[((0,0,-1),[(0,0,0),(0,1,0),(1,1,0),(1,0,0)]),
              ((0,0,1),[(0,0,1),(1,0,1),(1,1,1),(0,1,1)]),
              ((0,-1,0),[(0,0,0),(1,0,0),(1,0,1),(0,0,1)]),
              ((1,0,0),[(1,0,0),(1,1,0),(1,1,1),(1,0,1)]),
              ((0,1,0),[(1,1,0),(0,1,0),(0,1,1),(1,1,1)]),
              ((-1,0,0),[(0,1,0),(0,0,0),(0,0,1),(0,1,1)])]
    triangles=[]
    for cell in sorted(cells):
        for neighbour,corners in surfaces:
            if tuple(cell[a]+neighbour[a] for a in range(3)) in cells:continue
            a,b,c,d=[tuple((cell[k]+p[k])*[dx,dy,dz][k] for k in range(3)) for p in corners]
            triangles.extend([(a,b,c),(a,c,d)])
    return triangles


def box(length,width,height,origin):
    points=[(0,0,0),(length,0,0),(length,width,0),(0,width,0),(0,0,height),(length,0,height),(length,width,height),(0,width,height)]
    points=[tuple(p[k]+origin[k] for k in range(3)) for p in points]
    faces=[(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),(1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]
    return [tuple(points[i] for i in face) for face in faces]


def bracket_document(file, *, variant=False):
    dx,dy,dz,radius=(7,5,6,3) if variant else (6,4,5,2.5)
    return {'version':'schemaxis.freecad/1','nodes':[
        {'id':'casting','filter':'importMesh','options':{'file':str(file),'units':'mm','refine':True}},
        {'id':'drill','filter':'cylinder','options':{'radius':radius,'height':6*dz,'origin':[3.5*dx,2.5*dy,-dz]}},
        {'id':'bracket','filter':'cut','inputs':{'base':'casting','tool':'drill'}}],'output':'bracket'}


def bracket_oracle(*,variant=False,drill_shift=0,casting_shift=0):
    dx,dy,dz,radius=(7,5,6,3) if variant else (6,4,5,2.5)
    regions=[(6*dx*4*dy*dz,[3*dx,2*dy,dz/2]),
             (6*dx*dy*3*dz,[3*dx,dy/2,2.5*dz]),
             (dx*3*dy*3*dz,[dx/2,2.5*dy,2.5*dz])]
    source=sum(v for v,_ in regions);hole=math.pi*radius**2*dz
    source_centre=[sum(v*p[k] for v,p in regions)/source for k in range(3)];source_centre[1]+=casting_shift
    cut_centre=[3.5*dx+drill_shift,2.5*dy,dz/2]
    return {'sourceVolume':source,'volume':source-hole,'centreOfMass':[(source*source_centre[k]-hole*cut_centre[k])/(source-hole) for k in range(3)],
            'bounds':[0,6*dx,casting_shift,4*dy+casting_shift,0,4*dz],
            'inside':[[dx/2,dy/2+casting_shift,2*dz],[2*dx,2*dy+casting_shift,dz/2]],
            'outside':[[cut_centre[0],cut_centre[1],dz/2],[3*dx,2*dy+casting_shift,2*dz]]}


def cavity_document(file):
    return {'version':'schemaxis.freecad/1','nodes':[{'id':'casting','filter':'importMesh','options':{
        'file':str(file),'units':'cm','reverseWinding':True,'refine':True,
        'orientation':{'z':'+Y','x':'-X'},'placement':{'position':[45,-20,13],'clocking':31}}}],'output':'casting'}


def cavity_triangles():
    outer=box(2,2,2,(-1,-1,-1));inner=box(.8,.9,.7,(-.3,-.4,-.2))
    return [(a,c,b) for a,b,c in outer]+inner  # Explicit global inversion.


def cavity_oracle(position=(45,-20,13)):
    outer,void=8000,8*9*7;volume=outer-void;local=[-void*x/volume for x in (1,.5,1.5)]
    c,s=math.cos(math.radians(31)),math.sin(math.radians(31))
    def frame(p):return [-c*p[0]-s*p[2]+position[0],-s*p[0]+c*p[2]+position[1],p[1]+position[2]]
    corners=[frame((x,y,z)) for x in (-10,10) for y in (-10,10) for z in (-10,10)]
    return {'volume':volume,'centreOfMass':frame(local),'bounds':[v for k in range(3) for v in (min(p[k] for p in corners),max(p[k] for p in corners))],
            'inside':[frame((8,0,0)),frame((0,0,8))],'outside':[frame((1,.5,1.5)),frame((30,0,0))]}


def write_examples(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    result={}
    for label,triangles,binary in [('bracket',voxel_bracket(),False),('variant',voxel_bracket(7,5,6),False),('cavity',cavity_triangles(),True)]:
        path=directory/(label+'.stl');path.write_bytes(stl(triangles,binary=binary));result[label]=path
    return result


def dense_box():
    """Exactly 20000 planar facets, including 400 interior triangle splits."""
    points=[];lookup={};faces=[];n=40
    def point(p):
        p=tuple(p)
        if p not in lookup:lookup[p]=len(points);points.append(p)
        return lookup[p]
    for base,u,v in [((0,0,0),(0,20,0),(10,0,0)),((0,0,30),(10,0,0),(0,20,0)),
                      ((0,0,0),(10,0,0),(0,0,30)),((10,0,0),(0,20,0),(0,0,30)),
                      ((10,20,0),(-10,0,0),(0,0,30)),((0,20,0),(0,-20,0),(0,0,30))]:
        for i in range(n):
            for j in range(n):
                a,b,c,d=[point([base[k]+u[k]*s/n+v[k]*t/n for k in range(3)]) for s,t in [(i,j),(i+1,j),(i+1,j+1),(i,j+1)]]
                faces.extend([(a,b,c),(a,c,d)])
    triangles=[]
    for index,face in enumerate(faces):
        a,b,c=[points[i] for i in face]
        if index<400:
            centre=tuple((a[k]+b[k]+c[k])/3 for k in range(3));triangles.extend([(a,b,centre),(b,c,centre),(c,a,centre)])
        else:triangles.append((a,b,c))
    assert len(triangles)==20000
    return triangles
