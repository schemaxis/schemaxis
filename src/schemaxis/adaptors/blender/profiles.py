# Copyright (C) 2026 David L F Gaden
"""Deterministic, bounded rotational profiles without native application imports."""
import math
from schemaxis.errors import fail


def check_lathe_profile(profile,segments,caps,location='$',**observed):
    """Raise INVALID_PROFILE for a profile the lathe cannot build; shared by planning and native construction."""
    if (not isinstance(profile,list) or not 2<=len(profile)<=128 or
        type(segments) is not int or not 3<=segments<=256 or type(caps) is not bool or
        any(not isinstance(point,list) or len(point)!=2 or
            any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>100000 for v in point) or point[0]<=0 for point in profile)):
        fail('INVALID_PROFILE','lathe needs 2 to 128 [positive radius, height] pairs and 3 to 256 segments',location,**observed)
    if any(b[1]<=a[1] for a,b in zip(profile,profile[1:])):
        fail('INVALID_PROFILE','lathe profile heights must strictly increase',location,**observed)


def lathe_mesh(profile,segments,caps):
    check_lathe_profile(profile,segments,caps)
    points=[(r*math.cos(2*math.pi*j/segments),r*math.sin(2*math.pi*j/segments),z)
            for r,z in profile for j in range(segments)]
    faces=[(i*segments+j,i*segments+(j+1)%segments,(i+1)*segments+(j+1)%segments,(i+1)*segments+j)
           for i in range(len(profile)-1) for j in range(segments)]
    if caps:faces.extend([tuple(reversed(range(segments))),tuple(range((len(profile)-1)*segments,len(profile)*segments))])
    return points,faces
