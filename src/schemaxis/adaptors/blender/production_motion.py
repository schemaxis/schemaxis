"""Finite reusable motion and morph contracts; no authored native property paths."""
import math
from schemaxis.core.declarations import validate_arguments
from schemaxis.errors import fail, keys
from schemaxis.schema import arguments_schema, object_schema, argument_schema
from .node_catalogue import number, integer, vector, choice, boolean, text

NAME={'type':'string','minLength':1,'maxLength':128}
def array(item,limit=1024,minimum=0):return {'type':'array','items':item,'minItems':minimum,'maxItems':limit}
def record(properties,required=()):return {'type':'object','properties':{k:{**{a:b for a,b in v.items() if a!='default' or k not in required},**({'required':True} if k in required else {})} for k,v in properties.items()}}
# owner domain, trusted path, value declaration, number of components.
CHANNELS={
 'location':('object','location',vector(),3), 'rotation':('object','rotation_euler',vector(),3),
 'scale':('object','scale',vector((1,1,1)),3),
 'lightEnergy':('data','energy',number(1000,minimum=0),1),
 'lightColour':('data','color',vector((1,1,1)),3),
 'cameraLens':('data','lens',number(50,minimum=1,maximum=1000),1),
 'cameraScale':('data','ortho_scale',number(5,minimum=.000001),1),
 'cameraFocus':('data','dof.focus_distance',number(10,minimum=.000001),1),
 'cameraAperture':('data','dof.aperture_fstop',number(2.8,minimum=.1,maximum=128),1),
 'shapeValue':('keys','value',number(0,minimum=-10,maximum=10),1),
 'morphProgress':('keys','eval_time',number(0,minimum=0,maximum=1),1),
}
LAYER={'id':{**NAME,'required':True},'clip':{**NAME,'required':True},'bindings':array(record({'target':NAME,'object':NAME},['target','object']),256,1),
 'start':integer(1,minimum=0,maximum=1000000),'sourceStart':number(0,minimum=0,maximum=1000000),
 'sourceEnd':number(1,minimum=0,maximum=1000000),'scale':number(1,minimum=.001,maximum=1000),
 'repeat':integer(1,minimum=1,maximum=100),'reverse':boolean(),
 'blend':choice('REPLACE',['REPLACE','ADD','SUBTRACT','MULTIPLY']),
 'influence':number(1,minimum=0,maximum=1),'fadeIn':number(0,minimum=0),'fadeOut':number(0,minimum=0),
 'extrapolation':choice('NOTHING',['NOTHING','HOLD','HOLD_FORWARD'])}
LAYER['bindings']['required']=True
KEY={'id':NAME,'coordinates':array(vector(),100000),'offsets':array(record({'vertices':array({'type':'integer','minimum':0},100000,1),'offset':vector()},['vertices','offset']),4096),
 'relativeTo':text('Basis'),'mask':array(record({'vertices':array({'type':'integer','minimum':0},100000,1),'weight':number(1,minimum=0,maximum=1)},['vertices']),4096),
 'value':number(0,minimum=-10,maximum=10),'minimum':number(0,minimum=-10,maximum=10),'maximum':number(1,minimum=-10,maximum=10)}
MORPH={'object':{**NAME,'required':True},'mode':choice('relative',['relative','absolute']),'progress':number(0,minimum=0,maximum=1),'keys':array(record(KEY,['id']),128,1)}

MORPH['keys']['required']=True


def track_schema():
    return {'oneOf':[object_schema({'target':NAME,'bone':{'type':'string','maxLength':128},'shape':{'type':'string','maxLength':128},'channel':{'const':channel},
      'interpolation':{'enum':['LINEAR','CONSTANT']},'keys':array(object_schema({'frame':{'type':'integer','minimum':0,'maximum':1000000},'value':argument_schema(spec)},['frame','value']),4096,2)},['target','channel','keys']) for channel,(_,_,spec,_) in CHANNELS.items()]}


def schema_properties():
    return {'shapeKeys':array(argument_schema(record(MORPH,['object','keys'])),256),
      'clips':array(object_schema({'id':NAME,'tracks':array(track_schema(),4096,1)},['id','tracks']),256),
      'layers':array(argument_schema(record(LAYER,['id','clip','bindings'])),1024)}


def _collection(value,where,limit):
    if not isinstance(value,list) or len(value)>limit:fail('INVALID_ANIMATION','expected a bounded array',where)
    return value


def _identity(records,where):
    from schemaxis.pipeline import name
    seen=set()
    for record_ in records:
        if not isinstance(record_,dict):fail('INVALID_ANIMATION','expected an object',where)
        name(record_.get('id'),where)
        if record_['id'] in seen:fail('DUPLICATE_ID','identity already exists',where)
        seen.add(record_['id'])
    return seen


def validate(value,result,kinds,bones,where):
    morphs=[]
    for i,m in enumerate(_collection(value.get('shapeKeys',[]),where+'.shapeKeys',256)):
        loc=f'{where}.shapeKeys[{i}]';r=validate_arguments(MORPH,m,location=loc)
        if kinds.get(r['object'])!='mesh':fail('TYPE_MISMATCH','morph authoring requires an owned mesh object',loc)
        _identity(r['keys'],loc+'.keys')
        if any(k['id']=='Basis' for k in r['keys']):fail('DUPLICATE_ID','Basis is reserved for the undeformed mesh',loc)
        known={'Basis'}
        owned=next((o for o in result['objects'] if o['id']==r['object']),None)
        count=len(owned['vertices']) if owned else None
        for k in r['keys']:
            k.setdefault('coordinates',[]);k.setdefault('offsets',[]);k.setdefault('mask',[])
            if bool(k['coordinates'])==bool(k['offsets']):fail('INVALID_MORPH','declare either full coordinates or sparse offsets',loc)
            if k['relativeTo'] not in known:fail('UNKNOWN_REFERENCE','relative shape must precede this shape',loc)
            if k['minimum']>k['maximum'] or not k['minimum']<=k['value']<=k['maximum']:fail('INVALID_MORPH','value must lie in the declared slider range',loc)
            if r['mode']=='absolute' and (k['relativeTo']!='Basis' or k['mask'] or k['value'] or k['minimum']!=0 or k['maximum']!=1):fail('UNSUPPORTED_OPTION','absolute morphs use ordered equally spaced shapes and progress',loc)
            for field in ('offsets','mask'):
                indices=[v for item in k[field] for v in item['vertices']]
                if len(indices)!=len(set(indices)):fail('INVALID_MORPH','vertex selections must be disjoint',loc+'.'+field)
            if count is not None:
                if k['coordinates'] and len(k['coordinates'])!=count:fail('INVALID_MORPH','coordinates must match mesh vertex count',loc)
                if any(v>=count for field in ('offsets','mask') for item in k[field] for v in item['vertices']):fail('INVALID_MORPH','vertex index outside mesh',loc)
            known.add(k['id'])
        if r['mode']=='relative' and r['progress']:fail('UNSUPPORTED_OPTION','progress belongs to absolute morphs',loc)
        morphs.append(r)
    if len({m['object'] for m in morphs})!=len(morphs):fail('INVALID_MORPH','declare each object once',where+'.shapeKeys')
    morph_by={m['object']:m for m in morphs}
    # Linked meshes would share one Key ID and make per-object authoring ambiguous.
    instances=[o for o in result['objects'] if o['kind']=='instance' and o['linked']]
    if any(o['source'] in morph_by for o in instances):fail('UNSUPPORTED_OPTION','morphed mesh instances must use independent mesh data',where+'.shapeKeys')
    clips=[]
    for i,c in enumerate(_collection(value.get('clips',[]),where+'.clips',256)):
        loc=f'{where}.clips[{i}]';keys(c,('id','tracks'),loc);_identity([c],loc)
        tracks=[];seen=set()
        for j,t in enumerate(_collection(c.get('tracks'),loc+'.tracks',4096)):
            loc_t=f'{loc}.tracks[{j}]';keys(t,('target','bone','shape','channel','keys','interpolation'),loc_t)
            channel=t.get('channel')
            if channel not in CHANNELS:fail('UNSUPPORTED_CHANNEL','choose a semantic clip channel',loc_t)
            d=validate_arguments({'target':{**NAME,'required':True},'bone':text(),'shape':text(),'interpolation':choice('LINEAR',['LINEAR','CONSTANT']),
              'keys':array(record({'frame':integer(1,minimum=0,maximum=1000000),'value':CHANNELS[channel][2]},['frame','value']),4096,2)}, {k:v for k,v in t.items() if k!='channel'},location=loc_t)
            d['channel']=channel
            fs=[k['frame'] for k in d['keys']]
            if fs!=sorted(set(fs)):fail('INVALID_ANIMATION','clip keys must be strictly increasing',loc_t)
            if d['bone'] and channel not in ('location','rotation','scale') or bool(d['shape'])!=(channel=='shapeValue'):fail('TYPE_MISMATCH','bone and shape selectors must match their semantic channels',loc_t)
            if channel=='scale' and any(min(k['value'])<=0 for k in d['keys']):fail('INVALID_ANIMATION','scale keys must be positive',loc_t)
            if channel=='lightColour' and any(any(not 0<=v<=1 for v in k['value']) for k in d['keys']):fail('INVALID_ANIMATION','light colour must lie in zero to one',loc_t)
            identity=(d['target'],d['bone'],d['shape'],channel)
            if identity in seen:fail('INVALID_ANIMATION','duplicate clip channel',loc_t)
            seen.add(identity);tracks.append(d)
        if not tracks:fail('INVALID_ANIMATION','clip needs at least one track',loc)
        clips.append({'id':c['id'],'tracks':tracks})
    _identity(clips,where+'.clips');clip_by={c['id']:c for c in clips}
    layers=[];domains=set()
    for i,l in enumerate(_collection(value.get('layers',[]),where+'.layers',1024)):
        loc=f'{where}.layers[{i}]'
        if not isinstance(l,dict):fail('INVALID_ANIMATION','layer must be an object',loc)
        if l.get('clip') not in clip_by:fail('UNKNOWN_REFERENCE','layer clip is absent',loc)
        c=clip_by[l['clip']];low=min(k['frame'] for t in c['tracks'] for k in t['keys']);high=max(k['frame'] for t in c['tracks'] for k in t['keys'])
        r=validate_arguments(LAYER,{'sourceStart':low,'sourceEnd':high,**l},location=loc)
        binding={b['target']:b['object'] for b in r['bindings']};roles={t['target'] for t in c['tracks']}
        if len(binding)!=len(r['bindings']) or set(binding)!=roles or any(o not in kinds for o in binding.values()):fail('UNKNOWN_REFERENCE','bind every clip target exactly once to an existing object',loc)
        if not low<=r['sourceStart']<r['sourceEnd']<=high:fail('INVALID_ANIMATION','trim range must lie inside the clip',loc)
        duration=(r['sourceEnd']-r['sourceStart'])*r['scale']*r['repeat'];end=r['start']+duration
        if not result['frameStart']<=r['start']<end<=result['frameEnd'] or r['fadeIn']+r['fadeOut']>duration:fail('INVALID_TIMELINE','layer and fade duration must fit the timeline',loc)
        bound=set()
        for t in c['tracks']:
            obj=binding[t['target']];ch=t['channel'];domain=CHANNELS[ch][0]
            if t['bone'] and t['bone'] not in bones.get(obj,set()):fail('UNKNOWN_REFERENCE','bound rig lacks the requested bone',loc)
            if ch.startswith('light') and kinds[obj]!='light' or ch.startswith('camera') and kinds[obj]!='camera':fail('TYPE_MISMATCH','bound object has incompatible channel type',loc)
            if ch in ('shapeValue','morphProgress'):
                m=morph_by.get(obj)
                if not m or ch=='shapeValue' and (m['mode']!='relative' or t['shape'] not in {k['id'] for k in m['keys']}) or ch=='morphProgress' and m['mode']!='absolute':fail('UNKNOWN_REFERENCE','bound morph channel is absent or has a different mode',loc)
                if ch=='shapeValue':
                    key=next(k for k in m['keys'] if k['id']==t['shape'])
                    if any(not key['minimum']<=k['value']<=key['maximum'] for k in t['keys']):fail('INVALID_ANIMATION','shape keys exceed slider limits',loc)
            identity=(obj,t['bone'],t['shape'],ch)
            if identity in bound:fail('INVALID_ANIMATION','two clip targets alias one channel',loc)
            bound.add(identity);domains.add((obj,domain))
        layers.append(r)
    _identity(layers,where+'.layers')
    for t in result['tracks']:
        domain='data' if t['channel'].startswith(('light','camera')) else 'object'
        if (t['object'],domain) in domains:fail('UNSUPPORTED_OPTION','direct tracks and clip layers cannot own the same animation domain',where+'.tracks')
    # Turntable creates an independent action on roots; enforce single ownership.
    if any((o,'object') in domains for intent in result.get('intents',[]) for o in intent['objects']):fail('UNSUPPORTED_OPTION','turntable and clip layers require separate parent objects',where+'.layers')
    normalized={'shapeKeys':morphs,'clips':clips,'layers':layers}
    budget=sum(len(k['coordinates'])+sum(len(e['vertices']) for f in ('offsets','mask') for e in k[f]) for m in morphs for k in m['keys'])
    budget+=sum(len(t['keys'])*CHANNELS[t['channel']][3] for c in clips for t in c['tracks'])
    if budget>2_000_000:fail('RESOURCE_BUDGET_EXCEEDED','motion and morph authoring exceeds two million records',where)
    frames({**result,**normalized})
    return normalized


def frames(spec):
    fs={spec['currentFrame']}
    for l in spec['layers']:
        duration=(l['sourceEnd']-l['sourceStart'])*l['scale']*l['repeat'];end=l['start']+duration
        fs.update(int(f) for f in (l['start'],end,(l['start']+end)/2,l['start']+l['fadeIn']/2,end-l['fadeOut']/2) if f==int(f))
        for t in next(c for c in spec['clips'] if c['id']==l['clip'])['tracks']:
            for repeat in range(l['repeat']):
                for k in t['keys']:
                    f=l['start']+(repeat*(l['sourceEnd']-l['sourceStart'])+(l['sourceEnd']-k['frame'] if l['reverse'] else k['frame']-l['sourceStart']))*l['scale']
                    if l['start']<=f<=end and f==int(f):fs.add(int(f))
                    if len(fs)>2048:fail('RESOURCE_BUDGET_EXCEEDED','motion readback exceeds 2048 sampled frames')
    if len(fs)>2048:fail('RESOURCE_BUDGET_EXCEEDED','motion readback exceeds 2048 sampled frames')
    return fs


def influence_keys(layer):
    end=layer['start']+(layer['sourceEnd']-layer['sourceStart'])*layer['scale']*layer['repeat']
    points={layer['start']:layer['influence'],end:layer['influence']}
    if layer['fadeIn']:
        points[layer['start']]=0;points[layer['start']+layer['fadeIn']]=layer['influence']
    if layer['fadeOut']:
        points[end]=0;points[end-layer['fadeOut']]=layer['influence']
    return [{'frame':f,'value':v} for f,v in sorted(points.items())]


def native_name(prefix,*parts):
    import hashlib
    name=prefix+'--'+'--'.join(parts)
    if len(name.encode('utf-8'))<=63:return name
    return prefix+'--'+hashlib.sha256(name.encode()).hexdigest()[:32]


def action_name(spec,clip,target,domain,objid):
    suffix=[]
    if any(t['target']==target and t['channel']=='morphProgress' for t in clip['tracks']):
        suffix=[str(len(next(m for m in spec['shapeKeys'] if m['object']==objid)['keys']))]
    return native_name('SXClip',clip['id'],target,domain,*suffix)
