"""Exact physical track identities for the separate mixed solid-sweep engine."""
from schemaxis.errors import fail
from .cam_mixed_budget import LIMITS


def tracks(replay,tools):
    known={tool['id']:tool for tool in tools};vertical={};horizontal={}
    for motion in replay['motions']:
        if motion['code']==0:continue
        identity=motion.get('tool')
        if identity not in known:fail('INVALID_NC','Cutting motion needs its declared physical tool')
        a,b=motion['from'],motion['to'];z=min(a[2],b[2])
        if z>=0:continue
        if motion['code']==1 and a[:2]==b[:2]:
            key=(identity,*a[:2]);vertical[key]=min(z,vertical.get(key,z))
            if len(vertical)+len(horizontal)>LIMITS['pieces']:
                fail('RESOURCE_LIMIT','Mixed physical replay exceeds 512 exact cutter tracks')
            continue
        if known[identity]['kind']=='drill':
            fail('UNSUPPORTED_TOOLPATH','Pointed cutters admit only actual vertical drilling sweeps')
        if a[2]!=b[2]:
            fail('UNSUPPORTED_TOOLPATH','Nonplanar or ramped cutting needs a qualified physical sweep')
        if motion['code'] not in (1,2,3):fail('UNSUPPORTED_TOOLPATH','Unknown mixed physical cutting motion')
        aa,bb=tuple(a[:2]),tuple(b[:2]);code=motion['code']
        if code==1:aa,bb=sorted((aa,bb))
        key=(identity,code,aa,bb,tuple(motion.get('centre',[])))
        if key not in horizontal or z<horizontal[key][0]:horizontal[key]=(z,motion)
        # Count each arc's region pieces before native geometry allocation;
        # this first count also bounds dictionary growth.
        if len(vertical)+len(horizontal)>LIMITS['pieces']:
            fail('RESOURCE_LIMIT','Mixed physical replay exceeds 512 exact cutter tracks')
    if len(vertical)+len(horizontal)>LIMITS['pieces']:
        fail('RESOURCE_LIMIT','Mixed physical replay exceeds 512 exact cutter tracks')
    return horizontal,vertical
