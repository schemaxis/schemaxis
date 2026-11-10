"""Preserve per-tool footprints and depths in continuous flat-cutter replay."""
from schemaxis.errors import fail


def tracks(replay,tools):
    known={t['id']:t for t in tools};paths={};vertical={}
    for motion in replay['motions']:
        if motion['code']==0:continue
        identity=motion.get('tool')
        if identity not in known:fail('INVALID_NC','Cutting motion has no declared physical tool')
        a=motion['from'];b=motion['to'];z=min(a[2],b[2])
        if z>=0:continue
        if motion['code']==1 and all(abs(a[i]-b[i])<2e-6 for i in (0,1)):
            key=(identity,*a[:2]);vertical[key]=min(z,vertical.get(key,z));continue
        code=motion['code'] if motion['code'] in (2,3) else 1
        aa,bb=tuple(a[:2]),tuple(b[:2])
        if code==1:aa,bb=sorted((aa,bb))
        key=(identity,code,aa,bb,tuple(motion.get('centre',[])))
        if key not in paths or z<paths[key][0]:paths[key]=(z,motion)
    if len(paths)+len(vertical)>1000:
        fail('RESOURCE_LIMIT','Independent material replay exceeds 1000 distinct cutter tracks')
    return paths,vertical
