"""Original native revolution's analytic angular Gauss--Green primitive.

For the exact SurfaceOfRevolution class, U rotates both position and physical
normal about its native direction. The five fields therefore have harmonics
of order zero, one and two. A native anchor preserves the original meridian,
parameter chart, derivatives and orientation; no sampled fit is performed.

The fixed OCCT 7.8.1 Geom_SurfaceOfRevolution public API defines this law:
https://github.com/Open-Cascade-SAS/OCCT/blob/V7_8_1/src/Geom/Geom_SurfaceOfRevolution.hxx
"""
import math
from .gauss_green import Unresolved, finite


def strip(face, u0, u, v, origin, reference, sign):
    point=face.valueAt(u0,v)
    du,dv=face.derivative1At(u0,v)
    normal=du.cross(dv)
    axis=list(face.Surface.Direction)
    size=finite(math.hypot(*axis))
    if size<=0:
        raise Unresolved('revolution axis must be finite and nonzero')
    axis=[x/size for x in axis]
    delta=u-u0
    integrals=[delta,math.sin(delta),2*math.sin(delta/2)**2,
               math.sin(2*delta)/2,math.sin(delta)**2]
    relative=[x-y for x,y in zip(point,origin)]

    def dot(a,b):return math.fsum(x*y for x,y in zip(a,b))
    def cross(a,b):
        return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],
                a[0]*b[1]-a[1]*b[0]]

    # Su=A cross D. Hence Dc=Su cross A and Ds=Su recover the
    # rotating radius without subtracting an arbitrary distant axis origin.
    ds=list(du)
    dc=cross(ds,axis)
    q0=[x-y for x,y in zip(relative,dc)]
    n=list(normal)
    parallel=[x*dot(axis,n) for x in axis]
    cosine=[x-y for x,y in zip(n,parallel)]
    sine=cross(axis,n)
    b=[math.fsum((dot(q0,parallel),dot(dc,cosine))),
       dot(q0,cosine),dot(q0,sine)]
    volume=sign*dot(b,integrals[:3])/3
    moments=[]
    for i in range(3):
        a=[q0[i],dc[i],ds[i]]
        coefficients=[math.fsum((a[0]*b[0],a[1]*b[1]/2,a[2]*b[2]/2)),
                      math.fsum((a[0]*b[1],a[1]*b[0])),
                      math.fsum((a[0]*b[2],a[2]*b[0])),
                      (a[1]*b[1]-a[2]*b[2])/2,
                      (a[1]*b[2]+a[2]*b[1])/2]
        moments.append(sign*dot(coefficients,integrals)/(4*reference))
    return [finite(x) for x in [normal.Length*delta,volume,*moments]]
