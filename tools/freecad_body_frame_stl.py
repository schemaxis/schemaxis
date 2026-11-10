"""Independent binary-STL Body-frame pose and prismatic material checks.

The rounding budget is derived from binary32 coordinate storage, not fitted to
observations. It is only a qualifier codec bound; adaptor tolerances are unchanged.
"""
from collections import Counter
import math
from pathlib import Path
import struct


def inspect(path,frame,thickness=7):
    data=Path(path).read_bytes()
    assert len(data)>=84
    count=struct.unpack_from('<I',data,80)[0]
    assert 4<=count<=100000 and len(data)==84+50*count
    triangles=[struct.unpack_from('<12f',data,84+50*i)[3:] for i in range(count)]
    vertices=[[list(row[k:k+3]) for k in (0,3,6)] for row in triangles]
    maximum=max(abs(v) for tri in vertices for p in tri for v in p)
    # Each stored coordinate differs by at most half an ULP. Orthogonal inverse
    # transforms preserve Euclidean error. The extra factor covers projection
    # onto a plane/circle; the double term encloses our arithmetic, prospectively.
    ulp32=math.ldexp(1,max(-149,math.frexp(maximum)[1]-24))
    error=2*math.sqrt(3)*ulp32+64*math.ulp(max(1.,maximum))
    x,n=frame['xAxis'],frame['normal'];y=[n[1]*x[2]-n[2]*x[1],n[2]*x[0]-n[0]*x[2],n[0]*x[1]-n[1]*x[0]]
    def profile(point):
        q=[a-b for a,b in zip(point,frame['origin'])]
        local=[sum(a*b for a,b in zip(axis,q)) for axis in (x,y,n)]
        # Profile basis is (world local+Y, local+Z, local+X), origin(3,4,5).
        return [local[1]-4,local[2]-5,local[0]-3]
    faces=[[profile(p) for p in tri] for tri in vertices]
    edge_counts=Counter();directed=Counter();rings=[];boundary=Counter();signed=[]
    for native,tri in zip(vertices,faces):
        for i in range(3):
            a,b=tuple(native[i]),tuple(native[(i+1)%3]);assert a!=b
            edge_counts[tuple(sorted((a,b)))]+=1;directed[(a,b)]+=1
        classes=[]
        for p in tri:
            a,b,z=p;radius=math.hypot(a-3,b-2)
            assert -12-error<=a<=12+error and -8-error<=b<=8+error and -error<=z<=thickness+error
            assert radius>=2-error
            tags={name for name,value in [('left',a+12),('right',a-12),('front',b+8),('back',b-8),('bottom',z),('top',z-thickness),('bore',radius-2)] if abs(value)<=error}
            assert tags,(p,error)
            classes.append(tags)
            if 'top' in tags and 'bore' in tags:rings.append((a,b))
        shared=set.intersection(*classes);assert len(shared)==1,(tri,shared)
        boundary[next(iter(shared))]+=1
        a,b,c=native
        signed.append(sum(a[i]*(b[(i+1)%3]*c[(i+2)%3]-b[(i+2)%3]*c[(i+1)%3]) for i in range(3))/6)
    assert set(boundary)=={'left','right','front','back','bottom','top','bore'}
    assert all(n==2 for n in edge_counts.values())
    assert all(directed[(b,a)]==n for (a,b),n in directed.items())
    # Float32 corner copies are byte-identical in this native closed mesh.
    ring=sorted(set(rings),key=lambda p:math.atan2(p[1]-2,p[0]-3))
    assert len(ring)>=8
    polygon_area=abs(math.fsum(ring[i][0]*ring[(i+1)%len(ring)][1]-ring[(i+1)%len(ring)][0]*ring[i][1] for i in range(len(ring))))/2
    volume=math.fsum(signed);assert volume>0
    expected=(384-polygon_area)*thickness
    surface=2*(384-math.pi*4)+(80+math.pi*4)*thickness
    # The native mesh is the rectangle-minus-observed-polygon prism. A vertex
    # rounding displacement changes this prism inside its boundary slab. Include
    # the second/third-order rectangular dilation and summation roundoff terms.
    volume_bound=surface*error+4*(40+thickness)*error**2+8*error**3+64*math.ulp(max(1.,math.fsum(abs(v) for v in signed)))
    assert abs(volume-expected)<=volume_bound,(volume,expected,volume_bound)
    return {'triangles':count,'float32CoordinateBoundMM':error,'volumeMM3':volume,
            'polygonPrismVolumeMM3':expected,'volumeRoundingBoundMM3':volume_bound,
            'boundaryTriangleCounts':dict(boundary),'borePolygonVertices':len(ring)}
