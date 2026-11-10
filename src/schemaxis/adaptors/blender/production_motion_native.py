"""Native motion/morph execution and independent persisted descriptor readback."""
import json
import bpy
from mathutils import Vector
from schemaxis.errors import fail
from .production_motion import CHANNELS,influence_keys,native_name,action_name


def channel(objects,track,objid):
    obj=objects[objid];domain,path,_,width=CHANNELS[track['channel']]
    if domain=='keys':
        owner=obj.data.shape_keys
        if track['channel']=='shapeValue':path='key_blocks['+json.dumps(track['shape'])+'].value'
    elif domain=='data':owner=obj.data
    else:
        owner=obj
        if track['bone']:path='pose.bones['+json.dumps(track['bone'])+'].'+path
    return owner,path,width


def value(owner,path):
    v=owner.path_resolve(path)
    return list(v) if hasattr(v,'__len__') and not isinstance(v,str) else v


def _curves(action,slot):
    curves=[]
    for layer in action.layers:
        for strip in layer.strips:
            if strip.type!='KEYFRAME':fail('VERIFICATION_FAILED','clip has an unexpected native strip')
            bag=strip.channelbag(slot)
            if bag:curves.extend(bag.fcurves)
    return curves


def _action(identity,owner,tracks,objects,objid):
    action=bpy.data.actions.new(identity);slot=action.slots.new(owner.id_type,identity)
    action.use_fake_user=True
    layer=action.layers.new('Motion');bag=layer.strips.new(type='KEYFRAME').channelbags.new(slot)
    for track in tracks:
        _,path,width=channel(objects,track,objid)
        for component in range(width):
            curve=bag.fcurves.new(path,index=component)
            factor=(len(owner.key_blocks)-1)*10 if track['channel']=='morphProgress' else 1
            for key in track['keys']:
                v=key['value'][component] if width>1 else key['value']
                p=curve.keyframe_points.insert(key['frame'],v*factor);p.interpolation=track['interpolation']
            curve.extrapolation='CONSTANT'
    return action,slot


def _parts(clip):
    return sorted({(t['target'],CHANNELS[t['channel']][0]) for t in clip['tracks']})


def _tracks(clip,target,domain):return [t for t in clip['tracks'] if t['target']==target and CHANNELS[t['channel']][0]==domain]


def build(spec,objects):
    for morph in spec['shapeKeys']:
        obj=objects[morph['object']]
        if obj.data.shape_keys:fail('UNSUPPORTED_OPTION','morph authoring requires a mesh without existing shape keys',obj.name)
        if len(obj.data.vertices)*(len(morph['keys'])+1)>2_000_000:fail('RESOURCE_BUDGET_EXCEEDED','materialised morph coordinates exceed two million vertices',obj.name)
        basis=obj.shape_key_add(name='Basis',from_mix=False);data=obj.data.shape_keys;data.use_relative=morph['mode']=='relative'
        for key in morph['keys']:
            block=obj.shape_key_add(name=key['id'],from_mix=False);block.interpolation='KEY_LINEAR'
            coordinates=key['coordinates'] or [list(p.co) for p in basis.data]
            if len(coordinates)!=len(basis.data):fail('INVALID_MORPH','full coordinates must match mesh vertex count',obj.name)
            for p,co in zip(block.data,coordinates):p.co=co
            for entry in key['offsets']:
                for index in entry['vertices']:
                    if index>=len(block.data):fail('INVALID_MORPH','offset vertex index outside mesh',obj.name)
                    block.data[index].co=basis.data[index].co+Vector(entry['offset'])
            block.relative_key=data.key_blocks[key['relativeTo']]
            block.slider_min=min(0,key['minimum']);block.slider_max=max(1,key['maximum'])
            block.slider_min=key['minimum'];block.slider_max=key['maximum'];block.value=key['value']
            if key['mask']:
                group=obj.vertex_groups.new(name=native_name('SXMorph',key['id']))
                for entry in key['mask']:
                    if max(entry['vertices'])>=len(basis.data):fail('INVALID_MORPH','mask vertex index outside mesh',obj.name)
                    group.add(entry['vertices'],entry['weight'],'REPLACE')
                block.vertex_group=group.name
        if not data.use_relative:data.eval_time=morph['progress']*10*len(morph['keys'])
    clips={c['id']:c for c in spec['clips']};actions={};owners={}
    for layer in spec['layers']:
        clip=clips[layer['clip']];bindings={b['target']:b['object'] for b in layer['bindings']}
        for target,domain in _parts(clip):
            objid=bindings[target];tracks=_tracks(clip,target,domain);owner,_,_=channel(objects,tracks[0],objid)
            identity=(objid,domain);owners.setdefault(identity,{'owner':owner,'tracks':{}})
            for t in tracks:owners[identity]['tracks'][(t['bone'],t['shape'],t['channel'])]=t
    # Explicit reference actions make weighted/additive layers independent of RNA
    # defaults and preserve the declared static pose as a deterministic base.
    for (objid,domain),record in owners.items():
        owner=record['owner'];owner.animation_data_create()
        if owner.animation_data.action or owner.animation_data.nla_tracks:fail('UNSUPPORTED_OPTION','clip layers require an unowned animation domain',owner.name)
        tracks=[]
        for t in record['tracks'].values():
            _,path,_=channel(objects,t,objid);v=value(owner,path)
            if t['channel']=='morphProgress':v/=10*(len(owner.key_blocks)-1)
            tracks.append({**t,'interpolation':'CONSTANT','keys':[{'frame':spec['frameStart'],'value':v},{'frame':spec['frameEnd'],'value':v}]})
        action,slot=_action(native_name('SXRest',objid,domain),owner,tracks,objects,objid)
        track=owner.animation_data.nla_tracks.new();track.name='SXRest'
        strip=track.strips.new('SXRest',spec['frameStart'],action);strip.action_slot=slot;strip.extrapolation='HOLD';strip.influence=1
    for l in spec['layers']:
        clip=clips[l['clip']];bindings={b['target']:b['object'] for b in l['bindings']}
        for target,domain in _parts(clip):
            objid=bindings[target];tracks=_tracks(clip,target,domain);owner,_,_=channel(objects,tracks[0],objid)
            identity=action_name(spec,clip,target,domain,objid)
            if identity not in actions:actions[identity]=_action(identity,owner,tracks,objects,objid)
            action,slot=actions[identity]
            track=owner.animation_data.nla_tracks.new();track.name=native_name('SXLayer',l['id'],target)
            strip=track.strips.new(l['id'],l['start'],action);strip.action_slot=slot
            strip.action_frame_start=l['sourceStart'];strip.action_frame_end=l['sourceEnd'];strip.scale=l['scale'];strip.repeat=l['repeat']
            strip.use_reverse=l['reverse'];strip.blend_type=l['blend'];strip.influence=l['influence'];strip.extrapolation=l['extrapolation']
            strip.use_sync_length=False;strip.use_auto_blend=False;strip.blend_in=0;strip.blend_out=0
            strip.use_animated_influence=True
            for k in influence_keys(l):
                strip.influence=k['value'];strip.keyframe_insert('influence',frame=k['frame'])
            for curve in strip.fcurves:
                for point in curve.keyframe_points:point.interpolation='LINEAR'

    return [record['owner'] for record in owners.values()]


def _read_action(action,slot,tracks,objects,objid):
    if action is None or slot is None or len(action.layers)!=1 or len(action.layers[0].strips)!=1 or len(action.slots)!=1 or action.slots[0]!=slot or action.use_cyclic or action.use_frame_range:fail('VERIFICATION_FAILED','clip action or slot membership differs')
    curves=_curves(action,slot);expected=set();observed=[]
    for t in tracks:
        owner,path,width=channel(objects,t,objid);keys=[]
        selected=[]
        for component in range(width):
            found=[c for c in curves if c.data_path==path and c.array_index==component]
            if len(found)!=1 or found[0].modifiers or found[0].sampled_points or found[0].mute or found[0].group is not None or found[0].extrapolation!='CONSTANT':fail('VERIFICATION_FAILED','clip curve ownership or evaluation differs',path)
            selected.append(found[0]);expected.add((path,component))
        if any(len(c.keyframe_points)!=len(t['keys']) for c in selected):fail('VERIFICATION_FAILED','clip key membership differs',path)
        for i in range(len(t['keys'])):
            ps=[c.keyframe_points[i] for c in selected]
            if len({p.co.x for p in ps})!=1 or any(p.interpolation!=t['interpolation'] for p in ps):fail('VERIFICATION_FAILED','clip components or declared per-key interpolation differ',path)
            factor=(len(owner.key_blocks)-1)*10 if t['channel']=='morphProgress' else 1
            vs=[p.co.y/factor for p in ps];keys.append({'frame':ps[0].co.x,'value':vs if width>1 else vs[0]})
        observed.append({**{k:t[k] for k in ('target','bone','shape','channel')},'interpolation':selected[0].keyframe_points[0].interpolation,'keys':keys})
    if {(c.data_path,c.array_index) for c in curves}!=expected or len(curves)!=len(expected):fail('VERIFICATION_FAILED','clip contains unexpected curves')
    return observed


def read_influence(strip):
    if strip.blend_in or strip.blend_out or len(strip.fcurves)!=1:fail('VERIFICATION_FAILED','influence curve membership differs')
    curve=strip.fcurves[0]
    if curve.data_path!='influence' or curve.array_index!=0 or curve.mute or curve.modifiers or curve.sampled_points or curve.extrapolation!='CONSTANT' or any(p.interpolation!='LINEAR' for p in curve.keyframe_points):fail('VERIFICATION_FAILED','influence curve evaluation differs')
    return [{'frame':p.co.x,'value':p.co.y} for p in curve.keyframe_points]


def observe(spec,objects):
    morphs=[]
    for authored in spec['shapeKeys']:
        obj=objects[authored['object']];data=obj.data.shape_keys
        if not data or [b.name for b in data.key_blocks]!=['Basis']+[k['id'] for k in authored['keys']]:fail('VERIFICATION_FAILED','morph membership differs',obj.name)
        blocks=[]
        for block in data.key_blocks:
            weights=[]
            if block.vertex_group:
                group=obj.vertex_groups.get(block.vertex_group)
                if not group:fail('VERIFICATION_FAILED','morph mask group is absent',obj.name)
                weights=[[v.index,g.weight] for v in obj.data.vertices for g in v.groups if g.group==group.index]
            blocks.append({'id':block.name,'coordinates':[list(p.co) for p in block.data],'relativeTo':block.relative_key.name,'value':block.value,'minimum':block.slider_min,'maximum':block.slider_max,'mask':weights,'position':block.frame,'interpolation':block.interpolation,'mute':block.mute})
        morphs.append({'object':obj.name,'mode':'relative' if data.use_relative else 'absolute','progress':data.eval_time/(10*len(authored['keys'])),'keys':blocks})
    clips={c['id']:c for c in spec['clips']};observed_layers=[];owner_tracks={};rest=[]
    for l in spec['layers']:
        clip=clips[l['clip']];bindings={b['target']:b['object'] for b in l['bindings']}
        for target,domain in _parts(clip):
            objid=bindings[target];ts=_tracks(clip,target,domain);owner,_,_=channel(objects,ts[0],objid)
            animation=owner.animation_data
            if not animation or animation.action or animation.drivers or animation.use_tweak_mode or not animation.use_nla:fail('VERIFICATION_FAILED','clip owner contains undeclared animation',objid)
            owner_tracks.setdefault((objid,domain),{'owner':owner,'names':['SXRest'],'tracks':{}})
            record=owner_tracks[(objid,domain)];record['names'].append(native_name('SXLayer',l['id'],target))
            for t in ts:record['tracks'][(t['bone'],t['shape'],t['channel'])]=t
            track=animation.nla_tracks.get(native_name('SXLayer',l['id'],target))
            if track is None or track.mute or track.is_solo or len(track.strips)!=1:fail('VERIFICATION_FAILED','clip NLA track differs',objid)
            s=track.strips[0]
            if s.type!='CLIP' or s.mute or s.modifiers or not s.use_animated_influence or s.use_animated_time or s.use_auto_blend or s.use_sync_length:fail('VERIFICATION_FAILED','clip strip contains undeclared evaluation',objid)
            observed_layers.append({'id':l['id'],'target':target,'object':objid,'domain':domain,'clip':clip['id'],'action':s.action.name,'start':s.frame_start,'end':s.frame_end,'sourceStart':s.action_frame_start,'sourceEnd':s.action_frame_end,'scale':s.scale,'repeat':s.repeat,'reverse':s.use_reverse,'blend':s.blend_type,'influenceKeys':read_influence(s),'extrapolation':s.extrapolation,'tracks':_read_action(s.action,s.action_slot,ts,objects,objid)})
    for (objid,domain),record in sorted(owner_tracks.items()):
        animation=record['owner'].animation_data
        if [t.name for t in animation.nla_tracks]!=record['names']:fail('VERIFICATION_FAILED','NLA track order or membership differs',objid)
        track=animation.nla_tracks[0]
        if track.mute or track.is_solo or len(track.strips)!=1:fail('VERIFICATION_FAILED','reference pose track differs',objid)
        s=track.strips[0]
        if s.type!='CLIP' or s.mute or s.modifiers or s.use_animated_influence or s.use_animated_time or s.blend_type!='REPLACE' or s.influence!=1 or s.blend_in or s.blend_out or s.use_reverse or s.use_auto_blend or not s.use_sync_length or s.scale!=1 or s.repeat!=1 or s.extrapolation!='HOLD':fail('VERIFICATION_FAILED','reference pose strip differs',objid)
        ts=[{**t,'interpolation':'CONSTANT','keys':[{},{}]} for t in record['tracks'].values()]
        rest.append({'object':objid,'domain':domain,'action':s.action.name,'start':s.frame_start,'end':s.frame_end,'sourceStart':s.action_frame_start,'sourceEnd':s.action_frame_end,'tracks':_read_action(s.action,s.action_slot,ts,objects,objid)})
    return {'shapeKeys':morphs,'layers':observed_layers,'rest':rest}


def sample(spec,objects):
    clips={c['id']:c for c in spec['clips']};channels={}
    for l in spec['layers']:
        bindings={b['target']:b['object'] for b in l['bindings']}
        for t in clips[l['clip']]['tracks']:
            objid=bindings[t['target']];owner,path,_=channel(objects,t,objid);v=value(owner,path)
            if t['channel']=='morphProgress':v/=10*(len(owner.key_blocks)-1)
            channels[(objid,t['bone'],t['shape'],t['channel'])]=v
    return [{'object':k[0],'bone':k[1],'shape':k[2],'channel':k[3],'value':v} for k,v in sorted(channels.items())]
