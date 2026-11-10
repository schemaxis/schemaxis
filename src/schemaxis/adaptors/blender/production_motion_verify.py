"""Independent host judgement of persisted motion and deterministic layer math."""
import math
from schemaxis.errors import fail
from .production_motion import CHANNELS,influence_keys,native_name,action_name
from .settings import matching


def base(spec,objid,track):
    obj=next((o for o in spec['objects'] if o['id']==objid),{})
    ch=track['channel']
    if track['bone']:return [1,1,1] if ch=='scale' else [0,0,0]
    if ch in ('location','rotation','scale'):return obj.get(ch,[1,1,1] if ch=='scale' else [0,0,0])
    fields={'lightEnergy':'energy','lightColour':'colour','cameraLens':'lens','cameraScale':'orthographicSize','cameraFocus':'focusDistance','cameraAperture':'aperture'}
    if ch in fields:return obj[fields[ch]]
    morph=next(m for m in spec['shapeKeys'] if m['object']==objid)
    if ch=='morphProgress':return morph['progress']
    return next(k['value'] for k in morph['keys'] if k['id']==track['shape'])


def at(track,frame):
    ks=track['keys']
    if frame<=ks[0]['frame']:return ks[0]['value']
    if frame>=ks[-1]['frame']:return ks[-1]['value']
    a,b=next((a,b) for a,b in zip(ks,ks[1:]) if a['frame']<=frame<b['frame'])
    f=0 if track['interpolation']=='CONSTANT' else (frame-a['frame'])/(b['frame']-a['frame'])
    if isinstance(a['value'],list):return [x+(y-x)*f for x,y in zip(a['value'],b['value'])]
    return a['value']+(b['value']-a['value'])*f


def evaluate(spec,frame):
    clips={c['id']:c for c in spec['clips']};result={}
    for l in spec['layers']:
        bindings={b['target']:b['object'] for b in l['bindings']};clip=clips[l['clip']]
        length=l['sourceEnd']-l['sourceStart'];end=l['start']+length*l['scale']*l['repeat']
        active=not (frame<l['start'] and l['extrapolation']!='HOLD' or frame>end and l['extrapolation']=='NOTHING')
        f=min(end,max(l['start'],frame));elapsed=(f-l['start'])/l['scale']
        phase=length if math.isclose(elapsed,length*l['repeat'],abs_tol=1e-7) else elapsed%length
        source=l['sourceEnd']-phase if l['reverse'] else l['sourceStart']+phase
        weight=l['influence']
        if l['fadeIn']:weight*=min(1,max(0,(f-l['start'])/l['fadeIn']))
        if l['fadeOut']:weight*=min(1,max(0,(end-f)/l['fadeOut']))
        if not active:weight=0
        for t in clip['tracks']:
            objid=bindings[t['target']];identity=(objid,t['bone'],t['shape'],t['channel'])
            previous=result.setdefault(identity,base(spec,objid,t));new=at(t,source)
            def blend(a,b):
                if l['blend']=='REPLACE':return a*(1-weight)+b*weight
                if l['blend']=='ADD':return a+b*weight
                if l['blend']=='SUBTRACT':return a-b*weight
                return a*((1-weight)+b*weight)
            result[identity]=[blend(a,b) for a,b in zip(previous,new)] if isinstance(previous,list) else blend(previous,new)
    return result


def verify(spec,actual,samples,edited_geometry=None):
    def same(a,b,where):
        if not matching(a,b):fail('VERIFICATION_FAILED','motion or morph native value differs',where)
    if not isinstance(actual,dict):fail('VERIFICATION_FAILED','motion readback is absent')
    clips={c['id']:c for c in spec['clips']};expected=[];owners={}
    for l in spec['layers']:
        c=clips[l['clip']];bindings={b['target']:b['object'] for b in l['bindings']}
        for target,domain in sorted({(t['target'],CHANNELS[t['channel']][0]) for t in c['tracks']}):
            objid=bindings[target];tracks=[t for t in c['tracks'] if t['target']==target and CHANNELS[t['channel']][0]==domain]
            expected.append({**{k:v for k,v in l.items() if k not in ('bindings','influence','fadeIn','fadeOut')},'target':target,'object':objid,'domain':domain,'action':action_name(spec,c,target,domain,objid),
              'influenceKeys':influence_keys(l),'end':l['start']+(l['sourceEnd']-l['sourceStart'])*l['scale']*l['repeat'],'tracks':tracks})
            owner=owners.setdefault((objid,domain),{})
            for t in tracks:owner[(t['bone'],t['shape'],t['channel'])]=t
    same(actual.get('layers'),expected,'production.layers')
    rest=[]
    for (objid,domain),tracks in sorted(owners.items()):
        rest.append({'object':objid,'domain':domain,'action':native_name('SXRest',objid,domain),'start':spec['frameStart'],'end':spec['frameEnd'],'sourceStart':spec['frameStart'],'sourceEnd':spec['frameEnd'],
          'tracks':[{**t,'interpolation':'CONSTANT','keys':[{'frame':f,'value':base(spec,objid,t)} for f in (spec['frameStart'],spec['frameEnd'])]} for t in tracks.values()]})
    same(actual.get('rest'),rest,'production.referencePose')
    for sample in samples:
        values=evaluate(spec,sample['frame'])
        expected_channels=[{'object':k[0],'bone':k[1],'shape':k[2],'channel':k[3],'value':v} for k,v in sorted(values.items())]
        same(sample.get('motionChannels'),expected_channels,'production.evaluatedLayers')
    found=actual.get('shapeKeys')
    if not isinstance(found,list) or len(found)!=len(spec['shapeKeys']):fail('VERIFICATION_FAILED','morph object membership differs')
    values=evaluate(spec,spec['currentFrame'])
    for m,n in zip(spec['shapeKeys'],found):
        obj=next((o for o in spec['objects'] if o['id']==m['object']),None)
        basis=n['keys'][0]['coordinates']
        # DAG meshes have their own independently verified graph geometry; owned
        # mesh coordinates are literal and can also bind Basis directly here.
        if obj:same(basis,(edited_geometry or {}).get(m['object'],{}).get('vertices',obj['vertices']),'production.morph.Basis')
        expected_keys=[{'id':'Basis','coordinates':basis,'relativeTo':'Basis','value':1,'minimum':0,'maximum':1,'mask':[],'position':0,'interpolation':'KEY_LINEAR','mute':False}]
        for i,k in enumerate(m['keys']):
            co=[p[:] for p in k['coordinates']] if k['coordinates'] else [p[:] for p in basis]
            for entry in k['offsets']:
                for index in entry['vertices']:
                    if index>=len(co):fail('VERIFICATION_FAILED','morph offset outside current mesh')
                    co[index]=[a+b for a,b in zip(basis[index],entry['offset'])]
            mask=sorted([[v,e['weight']] for e in k['mask'] for v in e['vertices']])
            expected_keys.append({'id':k['id'],'coordinates':co,'relativeTo':k['relativeTo'],'value':values.get((m['object'],'',k['id'],'shapeValue'),k['value']),
              'minimum':k['minimum'],'maximum':k['maximum'],'mask':mask,'position':10*(i+1),'interpolation':'KEY_LINEAR','mute':False})
        same(n,{'object':m['object'],'mode':m['mode'],'progress':values.get((m['object'],'','','morphProgress'),m['progress']),'keys':expected_keys},'production.morphs')
