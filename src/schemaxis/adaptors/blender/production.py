"""Typed scene-production records shared by planning, schema and native execution.

A production composes named assets, hierarchy, motion, rigs and node graphs with
mesh DAG outputs. All property channels and constructors are finite reviewed IDs.
"""
import copy
import json
import math
from schemaxis.core.declarations import validate_arguments
from schemaxis.errors import fail, keys
from schemaxis.pipeline import name
from schemaxis.schema import object_schema, arguments_schema
from .node_catalogue import number, integer, vector, colour, choice, boolean, text, graph_schema, validate_graph
from .surface_compile import all_material_graphs

NAME={'type':'string','minLength':1,'maxLength':128}
def array(item,maximum=1024,minimum=0): return {'type':'array','items':item,'minItems':minimum,'maxItems':maximum}
def record(properties,required=()): return {'type':'object','properties':{k:{**{a:b for a,b in v.items() if a!='default' or not (k in required or v.get('required'))},**({'required':True} if k in required else {})} for k,v in properties.items()}}
TRANSFORM={'location':vector(),'rotation':vector(),'scale':vector((1,1,1))}
LIGHT={'type':choice('AREA',['AREA','POINT','SUN','SPOT']),'energy':number(1000,minimum=0,maximum=1e9),'colour':vector((1,1,1)),'size':number(1,minimum=0.000001),'angle':number(.785398,minimum=.000001,maximum=math.pi)}
CAMERA={'projection':choice('perspective',['perspective','orthographic']),'lens':number(50,minimum=1,maximum=1000),'orthographicSize':number(5,minimum=.000001),'clipStart':number(.01,minimum=.000001),'clipEnd':number(1000,minimum=.000002),'focusDistance':number(10,minimum=.000001),'aperture':number(2.8,minimum=.1,maximum=128),'depthOfField':boolean()}
CURVE={'points':array(vector(),4096,2),'closed':boolean(),'bevel':number(.02,minimum=0,maximum=10000),'resolution':integer(2,minimum=0,maximum=8)}
MESH={'vertices':array(vector(),100000,3),'faces':array(array({'type':'integer','minimum':0},1024,3),100000,1),'uv':array(array({'type':'array','items':{'type':'number'},'minItems':2,'maxItems':2},1024,3),100000),'smooth':boolean()}
OBJECT_BASE={'id':NAME,**TRANSFORM,'collection':text(),'material':text(),'hidden':boolean()}
from .spline import OPTIONS as SPLINE
from .render_policy import union,variant,rgb
DISPLAY_COLOUR=union([variant('inherit',{}),variant('colour',{'value':rgb((1,1,1))})],{'kind':'inherit'})
OBJECT_OPTIONS={
 'empty':{'displaySize':number(1,minimum=.000001)},
 'text':{'body':text('Label'),'size':number(1,minimum=.000001),'extrude':number(0,minimum=0),'align':choice('LEFT',['LEFT','CENTER','RIGHT','JUSTIFY','FLUSH'])},
 'curve':CURVE,'mesh':MESH,'light':LIGHT,'camera':CAMERA,
 'instance':{'source':{**NAME,'required':True},'linked':boolean(True)},
 'collectionInstance':{'source':{**NAME,'required':True}},
 'spline':SPLINE,
}
OBJECT_OPTIONS={kind:{**options,**({'displayColour':DISPLAY_COLOUR} if kind in ('text','curve','mesh','instance','spline') else {})} for kind,options in OBJECT_OPTIONS.items()}
CONSTRAINT_COMMON={'id':NAME,'object':NAME,'target':text(),'targetBone':text(),'bone':text(),'influence':number(1,minimum=0,maximum=1)}
CONSTRAINTS={
 'copyLocation':('COPY_LOCATION',{'axes':('use_xyz',{'type':'array','items':{'type':'boolean'},'minItems':3,'maxItems':3,'default':[True]*3}),'offset':('use_offset',boolean())}),
 'copyRotation':('COPY_ROTATION',{'mix':('mix_mode',choice('REPLACE',['REPLACE','ADD','BEFORE','AFTER','OFFSET']))}),
 'copyScale':('COPY_SCALE',{'offset':('use_offset',boolean())}),
 'copyTransforms':('COPY_TRANSFORMS',{'mix':('mix_mode',choice('REPLACE',['REPLACE','BEFORE_FULL','AFTER_FULL','BEFORE','AFTER']))}),
 'track':('TRACK_TO',{'trackAxis':('track_axis',choice('TRACK_NEGATIVE_Z',['TRACK_X','TRACK_Y','TRACK_Z','TRACK_NEGATIVE_X','TRACK_NEGATIVE_Y','TRACK_NEGATIVE_Z'])),'upAxis':('up_axis',choice('UP_Y',['UP_X','UP_Y','UP_Z']))}),
 'dampedTrack':('DAMPED_TRACK',{'trackAxis':('track_axis',choice('TRACK_Y',['TRACK_X','TRACK_Y','TRACK_Z','TRACK_NEGATIVE_X','TRACK_NEGATIVE_Y','TRACK_NEGATIVE_Z']))}),
 'childOf':('CHILD_OF',{}),
 'followPath':('FOLLOW_PATH',{'factor':('offset_factor',number(0,minimum=0,maximum=1)),'follow':('use_curve_follow',boolean(True))}),
 'inverseKinematics':('IK',{'chainLength':('chain_count',integer(0,minimum=0,maximum=64)),'iterations':('iterations',integer(64,minimum=1,maximum=1000)),'stretch':('use_stretch',boolean())}),
 'limitLocation':('LIMIT_LOCATION',{'minimum':('minimum',vector((-1,-1,-1))),'maximum':('maximum',vector((1,1,1)))}),
 'limitRotation':('LIMIT_ROTATION',{'minimum':('minimum',vector((-math.pi,)*3)),'maximum':('maximum',vector((math.pi,)*3))}),
 'limitScale':('LIMIT_SCALE',{'minimum':('minimum',vector((.1,)*3)),'maximum':('maximum',vector((10,)*3))}),
}
# Semantic animation channels have declared value shapes and trusted native paths.
CHANNELS={'location':('location',vector()),'rotation':('rotation_euler',vector()),'scale':('scale',vector((1,1,1))),
 'visibility':('hide_render',boolean()),'lightEnergy':('data.energy',number(1000,minimum=0)),
 'cameraLens':('data.lens',number(50,minimum=1,maximum=1000)),'cameraScale':('data.ortho_scale',number(5,minimum=.000001))}
TOP={'frameStart':integer(1,minimum=0,maximum=1000000),'frameEnd':integer(250,minimum=0,maximum=1000000),
 'fps':integer(24,minimum=1,maximum=240),'currentFrame':integer(1,minimum=0,maximum=1000000),
 'gravity':vector((0,0,-9.81)),'units':choice('metres',['metres','millimetres','centimetres','inches','feet']),
 'collections':array(record({'id':NAME,'parent':text()})),
 'hierarchy':array(record({'object':NAME,'parent':NAME,'keepWorld':boolean(True)},['object','parent'])),
 'materialBindings':array(record({'object':NAME,'material':NAME},['object','material'])),
 'geometryBindings':array(record({'object':NAME,'graph':NAME,'sourceObject':{**text(),'maxLength':128}},['object','graph'])),
 'images':array(record({'id':NAME,'file':{**text(),'required':True},'colourSpace':choice('sRGB',['sRGB','Non-Color']),'pack':boolean(True),'alphaMode':choice('straight',['straight','premultiplied','channelPacked','ignore'])},['id'])),
 'rigs':array(record({'id':NAME,'bones':array(record({'id':NAME,'head':vector(),'tail':vector((0,0,1)),'parent':text(),'connected':boolean(),'deform':boolean(True)},['id']),256,1)},['id','bones']),128),
 'skin':array(record({'object':NAME,'rig':NAME,'weights':array(record({'bone':NAME,'vertices':array({'type':'integer','minimum':0},100000,1),'weight':number(1,minimum=0,maximum=1)},['bone','vertices']),4096,1)},['object','rig','weights'])),
 'rigidBodies':array(record({'object':NAME,'type':choice('active',['active','passive']),'mass':number(1,minimum=.000001),'friction':number(.5,minimum=0,maximum=1),'restitution':number(0,minimum=0,maximum=1),'shape':choice('CONVEX_HULL',['BOX','SPHERE','CAPSULE','CYLINDER','CONE','CONVEX_HULL','MESH']),'kinematic':boolean()},['object'])),
 'cloth':array(record({'object':NAME,'quality':integer(5,minimum=1,maximum=80),'mass':number(.3,minimum=.000001),'tension':number(15,minimum=0,maximum=10000),'compression':number(15,minimum=0,maximum=10000),'shear':number(5,minimum=0,maximum=10000),'bending':number(.5,minimum=0,maximum=10000),'collision':boolean(True),'selfCollision':boolean(),'pinVertices':array({'type':'integer','minimum':0},100000)},['object'])),
 'collisionObjects':array(NAME),
 'simulationFrames':array({'type':'integer','minimum':0,'maximum':1000000},1000),
}


def schema():
    result=arguments_schema(TOP)
    variants=[]
    for kind,options in OBJECT_OPTIONS.items():
        s=arguments_schema({**OBJECT_BASE,**options});s['properties']['kind']={'const':kind};s.setdefault('required',[]).extend(['id','kind']);variants.append(s)
    result['properties']['objects']={'type':'array','maxItems':4096,'items':{'oneOf':variants}}
    for field,family in [('materialGraphs','material'),('geometryGraphs','geometry')]:result['properties'][field]={'type':'array','maxItems':128,'items':graph_schema(family,material_display=family=='material')}
    from .geometry_resources import schema_property as resource_schema
    result['properties']['geometryResources']=resource_schema()
    result['properties']['compositor']=graph_schema('compositor')
    tracks=[]
    for channel,(_,spec) in CHANNELS.items():
        s=object_schema({'object':NAME,'bone':NAME,'channel':{'const':channel},'interpolation':{'enum':['LINEAR','BEZIER','CONSTANT']},'keys':{'type':'array','minItems':1,'maxItems':4096,'items':object_schema({'frame':{'type':'integer','minimum':0,'maximum':1000000},'value':__import__('schemaxis.schema',fromlist=['argument_schema']).argument_schema(spec)},['frame','value'])}},['object','channel','keys']);tracks.append(s)
    result['properties']['tracks']={'type':'array','maxItems':4096,'items':{'oneOf':tracks}}
    variants=[]
    for kind,(_,options) in CONSTRAINTS.items():
        s=arguments_schema({**CONSTRAINT_COMMON,**{k:v[1] for k,v in options.items()}});s['properties']['kind']={'const':kind};s.setdefault('required',[]).extend(['id','object','kind']);variants.append(s)
    result['properties']['constraints']={'type':'array','maxItems':4096,'items':{'oneOf':variants}}
    from .production_assets import asset_schema_property
    result['properties']['assets']=asset_schema_property()
    from .production_intents import intent_schema_property
    result['properties']['intents']=intent_schema_property()
    from .production_outputs import output_schema_properties
    result['properties'].update(output_schema_properties())
    from .production_motion import schema_properties
    result['properties'].update(schema_properties())
    from .node_groups import schema_property
    result['properties']['nodeGroups']=schema_property()
    from .mesh_data import schema_property as mesh_schema
    result['properties']['meshData']=mesh_schema()
    from .mesh_edits import schema_property as edit_schema
    result['properties']['meshEdits']=edit_schema()
    from .material_assignments import schema_property as material_schema
    result['properties']['materialAssignments']=material_schema()
    from .surface_materials_schema import schema_property as surface_schema
    result['properties']['surfaceMaterials']=surface_schema()
    from .render_features import schema_properties as feature_properties
    result['properties'].update(feature_properties())
    return result


def _distinct(items,label,existing=()):
    found=set(existing)
    for i,item in enumerate(items):
        name(item.get('id'),f'{label}[{i}].id')
        if item['id'] in found:fail('DUPLICATE_ID','identity already exists',f'{label}[{i}].id')
        found.add(item['id'])
    return found


def _ordered(records,identity,parent,where,external=()):
    deps={r[identity]:({r[parent]} if r.get(parent) else set()) for r in records}
    known=set(deps)|set(external)
    if any(not d<=known for d in deps.values()):fail('UNKNOWN_REFERENCE','parent reference is absent',where)
    pending=set(deps);result=[]
    while pending:
        ready=sorted(n for n in pending if not deps[n]&pending)
        if not ready:fail('DEPENDENCY_CYCLE','parent relationships contain a cycle',where)
        result.extend(ready);pending.difference_update(ready)
    return result


def validate(value,graph_nodes,where='$.scenes[0].production'):
    if not isinstance(value,dict):fail('INVALID_PRODUCTION','production must be an object',where)
    from .render_features import FIELDS as feature_fields
    fields=(*TOP,'objects','materialGraphs','geometryGraphs','compositor','tracks','constraints','exports','renderFrames','camera','intents','assets','shapeKeys','clips','layers','nodeGroups','meshData','geometryResources','meshEdits','materialAssignments','surfaceMaterials',*feature_fields)
    keys(value,fields,where)
    for field in ('objects','materialGraphs','geometryGraphs','tracks','constraints'):
        if field in value and (not isinstance(value[field],list) or len(value[field])>4096):fail('INVALID_PRODUCTION','production collection must be a bounded array',where+'.'+field)
    literal={k:v for k,v in value.items() if k in TOP}
    if 'currentFrame' not in literal and 'frameStart' in literal:literal['currentFrame']=literal['frameStart']
    result=validate_arguments(TOP,literal,location=where)
    for field in TOP:
        if TOP[field]['type']=='array':result.setdefault(field,[])
    for field in ('objects','materialGraphs','geometryGraphs','tracks','constraints'):result[field]=[]
    for i,obj in enumerate(value.get('objects',[])):
        loc=f'{where}.objects[{i}]'
        if not isinstance(obj,dict) or obj.get('kind') not in OBJECT_OPTIONS:fail('UNSUPPORTED_OBJECT','choose a reviewed scene object kind',loc)
        kind=obj['kind'];options=validate_arguments({**OBJECT_BASE,**OBJECT_OPTIONS[kind]},{k:v for k,v in obj.items() if k!='kind'},location=loc)
        if any(type(x) not in (int,float) or x<=0 for x in options['scale']):fail('INVALID_TRANSFORM','scale components must be positive',loc+'.scale')
        if kind=='light':
            if options['type'] in ('AREA','POINT') and options['angle']!=LIGHT['angle']['default'] or options['type']=='SUN' and options['size']!=LIGHT['size']['default']:fail('UNSUPPORTED_OPTION','light option has no effect for chosen light type',loc)
            if any(not 0<=c<=1 for c in options['colour']):fail('INVALID_ARGUMENT','light colour components must be in0–1',loc+'.colour')
        if kind=='camera' and options['clipEnd']<=options['clipStart']:fail('INVALID_CAMERA','far clip must exceed near clip',loc)
        if kind=='mesh':
            options.setdefault('uv',[])
            for fi,face in enumerate(options['faces']):
                if max(face)>=len(options['vertices']) or len(set(face))!=len(face):fail('INVALID_GEOMETRY','face indices must be distinct existing vertices',f'{loc}.faces[{fi}]')
            uv=options.get('uv',[])
            if uv and (len(uv)!=len(options['faces']) or any(len(a)!=len(b) for a,b in zip(uv,options['faces']))):fail('INVALID_GEOMETRY','UV coordinates must match every face corner',loc+'.uv')
        if kind=='spline':
            from .spline import validate as validate_spline
            validate_spline(options,loc)
        result['objects'].append({'kind':kind,**options})
    if len(result['objects'])>4096:fail('RESOURCE_BUDGET_EXCEEDED','at most4096 production objects',where)
    materials={n for n,d in graph_nodes.items() if d['filter']=='material'}
    meshes=set(graph_nodes)-materials
    from .production_assets import validate_assets
    result['assets']=validate_assets(value.get('assets',[]),where)
    asset_ids=_distinct(result['assets'],where+'.assets',meshes)
    asset_ids-=meshes
    rigs=_distinct(result['rigs'],where+'.rigs',asset_ids)
    rigs-=asset_ids
    objects=_distinct(result['objects'],where+'.objects',meshes|rigs|asset_ids)
    collections=_distinct(result['collections'],where+'.collections')
    _ordered(result['collections'],'id','parent',where+'.collections')
    for asset in result['assets']:
        if asset['collection'] and asset['collection'] not in collections:fail('UNKNOWN_REFERENCE','asset target collection absent',where+'.assets')
    image_ids=_distinct(result['images'],where+'.images')
    from .node_groups import validate_groups
    result['nodeGroups']=validate_groups(value.get('nodeGroups',[]),where+'.nodeGroups')
    groups={g['id']:g for g in result['nodeGroups']}
    for field,family in [('materialGraphs','material'),('geometryGraphs','geometry')]:
        for i,g in enumerate(value.get(field,[])):result[field].append(validate_graph(g,family,f'{where}.{field}[{i}]',groups=groups,material_display=family=='material'))
        _distinct(result[field],where+'.'+field,materials if family=='material' else ())
    materials|={g['id'] for g in result['materialGraphs']}
    from .surface_materials import validate as validate_surfaces
    surfaces=validate_surfaces(value.get('surfaceMaterials',[]),result['images'],materials,where+'.surfaceMaterials')
    if surfaces:result['surfaceMaterials']=surfaces
    materials|={g['id'] for g in surfaces};geometries={g['id'] for g in result['geometryGraphs']}
    from .shader_budget import validate as validate_shader_budget
    # Active DAG material membership is resolved later by adaptor.plan.
    validate_shader_budget(result,{},where+'.materialGraphs')
    if 'compositor' in value:result['compositor']=validate_graph(value['compositor'],'compositor',where+'.compositor',groups=groups)
    for graph in all_material_graphs(result):
        texture=graph['displayTexture']
        if texture['kind']=='image' and texture['image'] not in image_ids:fail('UNKNOWN_REFERENCE','display texture must reference a captured production image',where+'.materialGraphs.'+graph['id']+'.displayTexture.image')
        for n in graph['nodes']:
            if n['kind']=='image' and n['properties']['image'] not in image_ids:fail('UNKNOWN_REFERENCE','image node must reference a production image',where+'.materialGraphs')
    for graph in result['geometryGraphs']:
        for n in graph['nodes']:
            if n['kind']=='setMaterial' and n['values'].get('material') not in materials:fail('UNKNOWN_REFERENCE','geometry material is absent',where+'.geometryGraphs')
    graph_ids={g['id'] for g in all_material_graphs(result)+result['geometryGraphs']}|({result['compositor']['id']} if 'compositor' in result else set())
    if set(groups)&graph_ids:fail('DUPLICATE_ID','reusable group identities must differ from production graph identities',where+'.nodeGroups')
    kinds={n:'mesh' for n in meshes}|{o['id']:o['kind'] for o in result['objects']}|{r:'rig' for r in rigs}|{a:'asset' for a in asset_ids}
    from .mesh_edits import validate as validate_edits,owned_plan
    result['meshEdits']=validate_edits(value.get('meshEdits',[]),kinds,where+'.meshEdits')
    edited=owned_plan(result['meshEdits'],result['objects'])
    topology_objects=[{**o,**({'vertices':edited[o['id']]['vertices'],'faces':edited[o['id']]['faces'],'uv':[]} if o['kind']=='mesh' and o['id'] in edited else {})} for o in result['objects']]
    topology_result={**result,'objects':topology_objects}
    from .mesh_data import validate as validate_mesh_data
    result['meshData']=validate_mesh_data(value,topology_result,kinds,where)
    from .material_assignments import validate as validate_materials
    result['materialAssignments']=validate_materials(value.get('materialAssignments',[]),kinds,materials,topology_result['objects'],where+'.materialAssignments')
    from .geometry_resources import validate as validate_resources
    result['geometryResources']=validate_resources(value.get('geometryResources',[]),kinds,collections,{a['id']:a for a in result['assets']},where+'.geometryResources')
    from .node_groups import references
    resource_ids={'material':materials,'object':objects|{r['id'] for r in result['geometryResources'] if r['kind']=='object'},'collection':collections|{r['id'] for r in result['geometryResources'] if r['kind'] in ('collection','asset')},'image':image_ids}
    graphs=[(g,g['family'],g) for g in result['nodeGroups']]+[(g,'material',None) for g in all_material_graphs(result)]+[(g,'geometry',None) for g in result['geometryGraphs']]
    if 'compositor' in result:graphs.append((result['compositor'],'compositor',None))
    for g,f,interface in graphs:
        for node in g['nodes']:
            if node['kind']=='setMaterial' and node['values']['material'] not in materials:fail('UNKNOWN_REFERENCE','material node needs a declared material',where+'.nodeGroups')
            if node['kind']=='image' and node['properties']['image'] not in image_ids:fail('UNKNOWN_REFERENCE','image node needs a declared production image',where+'.nodeGroups')
        refs=references(g,f,groups,interface)
        if interface:
            refs.extend((s['kind'],s.get('default')) for s in interface['inputs']+interface['outputs'] if s['kind'] in resource_ids and s.get('default') and not (f=='compositor' and s['kind']=='image'))
        for kind,ref in refs:
            if ref not in resource_ids[kind]:fail('UNKNOWN_REFERENCE','node interface resource is absent',where+'.nodeGroups',kind=kind,resource=ref)
    for o in result['objects']:
        loc=where+'.objects.'+o['id']
        if o.get('collection') and o['collection'] not in collections:fail('UNKNOWN_REFERENCE','object collection is absent',loc)
        if o.get('material') and o['material'] not in materials:fail('UNKNOWN_REFERENCE','object material is absent',loc)
        if o['kind']=='instance' and o['source'] not in objects:fail('UNKNOWN_REFERENCE','instance source object is absent',loc)
        if o['kind']=='instance' and o['displayColour']['kind']=='colour' and kinds[o['source']] in ('empty','light','camera','collectionInstance','rig'):
            fail('TYPE_MISMATCH','display colour requires a geometric prototype, not a hierarchy or collection carrier',loc+'.displayColour')
        if o['kind']=='collectionInstance' and o['source'] not in collections:fail('UNKNOWN_REFERENCE','instance collection is absent',loc)
    _ordered([{'id':o['id'],'source':o.get('source','') if o['kind']=='instance' else ''} for o in result['objects']],'id','source',where+'.objects',meshes|rigs|asset_ids)
    hierarchy=result['hierarchy']
    if len({h['object'] for h in hierarchy})!=len(hierarchy):fail('INVALID_HIERARCHY','object may have only one parent',where+'.hierarchy')
    if any(h['object'] not in objects or h['parent'] not in objects for h in hierarchy):fail('UNKNOWN_REFERENCE','hierarchy refers to absent object',where+'.hierarchy')
    _ordered(hierarchy,'object','parent',where+'.hierarchy',objects)
    for field,target,reference,allowed in [('materialBindings','object','material',materials),('geometryBindings','object','graph',geometries)]:
        identities={(b[target],b.get('sourceObject','')) if field=='geometryBindings' else b[target] for b in result[field]}
        if len(identities)!=len(result[field]):fail('INVALID_PRODUCTION','duplicate binding on object/source selector',where+'.'+field)
        for b in result[field]:
            if b[target] not in objects or b[reference] not in allowed:fail('UNKNOWN_REFERENCE','binding refers to absent object or resource',where+'.'+field)
            allowed_kinds=('mesh','instance','curve','spline','text','asset','empty','collectionInstance') if field=='materialBindings' else ('mesh','instance','curve','spline','text','asset')
            if kinds[b[target]] not in allowed_kinds:fail('TYPE_MISMATCH','binding needs a compatible geometric object/root',where+'.'+field)
            if field=='geometryBindings' and b['sourceObject'] and kinds[b[target]]!='asset':fail('INVALID_GEOMETRY_RESOURCE','sourceObject selects a captured asset member',where+'.geometryBindings')
    bones={}
    for rig in result['rigs']:
        names=_distinct(rig['bones'],where+'.rigs.'+rig['id']+'.bones');bones[rig['id']]=names
        _ordered(rig['bones'],'id','parent',where+'.rigs.'+rig['id']+'.bones')
        for b in rig['bones']:
            if math.dist(b['head'],b['tail'])<1e-9:fail('INVALID_RIG','bone endpoints must differ',where+'.rigs.'+rig['id'])
            if b['connected'] and b['parent']:
                parent=next(p for p in rig['bones'] if p['id']==b['parent'])
                if math.dist(b['head'],parent['tail'])>1e-7:fail('INVALID_RIG','connected bone head must equal parent tail',where+'.rigs.'+rig['id'])
            if b['connected'] and not b['parent']:fail('INVALID_RIG','connected bone requires a parent',where+'.rigs.'+rig['id'])
    for skin in result['skin']:
        if skin['object'] not in objects or kinds[skin['object']] not in ('mesh','instance') or skin['rig'] not in rigs:fail('UNKNOWN_REFERENCE','skin needs a mesh and existing rig',where+'.skin')
        if len({w['bone'] for w in skin['weights']})!=len(skin['weights']):fail('INVALID_SKIN','declare each bone weight group once',where+'.skin')
        for weight in skin['weights']:
            if len(set(weight['vertices']))!=len(weight['vertices']):fail('INVALID_SKIN','weight vertex indices must be distinct',where+'.skin')
            if weight['bone'] not in bones[skin['rig']]:fail('UNKNOWN_REFERENCE','skin bone is absent',where+'.skin')
    tracks=value.get('tracks',[])
    if not isinstance(tracks,list) or len(tracks)>4096:fail('INVALID_ANIMATION','tracks must be bounded array',where+'.tracks')
    track_ids=set()
    for i,track in enumerate(tracks):
        loc=f'{where}.tracks[{i}]';keys(track,('object','bone','channel','keys','interpolation'),loc)
        channel=track.get('channel')
        if channel not in CHANNELS:fail('UNSUPPORTED_CHANNEL','choose a semantic animation channel',loc+'.channel')
        obj=track.get('object');bone=track.get('bone','')
        if obj not in objects or bone and bone not in bones.get(obj,set()):fail('UNKNOWN_REFERENCE','animation target is absent',loc)
        if bone and channel not in ('location','rotation','scale'):fail('TYPE_MISMATCH','bone animation needs a transform channel',loc)
        if channel=='lightEnergy' and kinds[obj]!='light' or channel in ('cameraLens','cameraScale') and kinds[obj]!='camera':fail('TYPE_MISMATCH','channel incompatible with object kind',loc)
        identity=(obj,bone,channel)
        if identity in track_ids:fail('INVALID_ANIMATION','duplicate object channel track',loc)
        track_ids.add(identity)
        interpolation=validate_arguments({'interpolation':choice('LINEAR',['LINEAR','BEZIER','CONSTANT'])},{'interpolation':track.get('interpolation','LINEAR')},location=loc)['interpolation']
        keyframes=validate_arguments({'keys':array(record({'frame':integer(1,minimum=0,maximum=1000000),'value':CHANNELS[channel][1]},['frame','value']),4096,1)},{'keys':track.get('keys')},location=loc)['keys']
        frames=[k['frame'] for k in keyframes]
        if frames!=sorted(set(frames)):fail('INVALID_ANIMATION','keyframes must be strictly increasing',loc+'.keys')
        if channel=='scale' and any(min(k['value'])<=0 for k in keyframes):fail('INVALID_ANIMATION','scale keys must be positive',loc+'.keys')
        result['tracks'].append({'object':obj,'bone':bone,'channel':channel,'interpolation':interpolation,'keys':keyframes})
    for i,c in enumerate(value.get('constraints',[])):
        loc=f'{where}.constraints[{i}]'
        if not isinstance(c,dict) or c.get('kind') not in CONSTRAINTS:fail('UNSUPPORTED_CONSTRAINT','choose a reviewed constraint',loc)
        kind=c['kind'];opts=validate_arguments({**CONSTRAINT_COMMON,**{k:v[1] for k,v in CONSTRAINTS[kind][1].items()}},{k:v for k,v in c.items() if k!='kind'},location=loc)
        if opts.get('object') not in objects or opts.get('target') and opts['target'] not in objects:fail('UNKNOWN_REFERENCE','constraint target is absent',loc)
        if opts['targetBone'] and opts['targetBone'] not in bones.get(opts['target'],set()):fail('UNKNOWN_REFERENCE','constraint target bone is absent',loc+'.targetBone')
        if kind.startswith('limit') and any(a>b for a,b in zip(opts['minimum'],opts['maximum'])):fail('INVALID_CONSTRAINT','minimum must not exceed maximum',loc)
        if kind=='track' and opts['trackAxis'].replace('TRACK_NEGATIVE_','').replace('TRACK_','')==opts['upAxis'].replace('UP_',''):fail('INVALID_CONSTRAINT','tracking and up axes must differ',loc)
        if opts['bone'] and opts['bone'] not in bones.get(opts['object'],set()):fail('UNKNOWN_REFERENCE','constraint bone is absent',loc)
        if not kind.startswith('limit') and not opts['target']:fail('MISSING_ARGUMENT','constraint needs target',loc+'.target')
        if kind=='followPath' and kinds[opts['target']] not in ('curve','spline'):fail('TYPE_MISMATCH','path target must be curve',loc)
        if kind=='followPath' and kinds[opts['target']]=='spline' and not next(o for o in result['objects'] if o['id']==opts['target'])['path']['enabled']:fail('INVALID_SPLINE','followPath requires enabled path evaluation',loc)
        if kind=='inverseKinematics' and not opts['bone']:fail('TYPE_MISMATCH','IK requires pose bone target',loc)
        result['constraints'].append({'kind':kind,**opts})
    _distinct(result['constraints'],where+'.constraints')
    dependency_records=[{'id':o,'parents':set()} for o in objects]
    dependencies={r['id']:r['parents'] for r in dependency_records}
    for h in hierarchy:dependencies[h['object']].add(h['parent'])
    for c in result['constraints']:
        if c['target'] and not (c['object']==c['target'] and c['bone']):dependencies[c['object']].add(c['target'])
    from .spline import dependencies as spline_dependencies
    for identity,refs in spline_dependencies(result,kinds,where+'.objects').items():dependencies[identity].update(refs)
    pending=set(dependencies)
    while pending:
        ready={n for n in pending if not dependencies[n]&pending}
        if not ready:fail('DEPENDENCY_CYCLE','parent/constraint relationships contain a cycle',where+'.constraints')
        pending.difference_update(ready)
    if result['frameEnd']<result['frameStart'] or not result['frameStart']<=result['currentFrame']<=result['frameEnd']:fail('INVALID_TIMELINE','timeline requires start <= current <= end',where)
    for t in result['tracks']:
        if any(not result['frameStart']<=k['frame']<=result['frameEnd'] for k in t['keys']):fail('INVALID_TIMELINE','keyframe lies outside timeline',where+'.tracks')
    for field in ('rigidBodies','cloth'):
        if len({s['object'] for s in result[field]})!=len(result[field]):fail('INVALID_SIMULATION','duplicate simulation object',where+'.'+field)
        for s in result[field]:
            if field=='cloth':
                s.setdefault('pinVertices',[])
                if len(set(s['pinVertices']))!=len(s['pinVertices']):fail('INVALID_SIMULATION','pin vertex indices must be distinct',where+'.cloth')
            if s['object'] not in objects or kinds[s['object']] not in ('mesh','instance'):fail('TYPE_MISMATCH','simulation needs mesh object',where+'.'+field)
    if any(o not in objects for o in result['collisionObjects']):fail('UNKNOWN_REFERENCE','collision object absent',where+'.collisionObjects')
    frames=result['simulationFrames']
    if frames!=sorted(set(frames)) or any(not result['frameStart']<=f<=result['frameEnd'] for f in frames):fail('INVALID_SIMULATION','sample frames must be ordered distinct timeline frames',where+'.simulationFrames')
    if frames and frames[-1]-result['frameStart']>1000:fail('RESOURCE_BUDGET_EXCEEDED','simulation evaluation at most1000 frames',where+'.simulationFrames')
    from .production_intents import validate_intents
    result['intents']=validate_intents(value.get('intents',[]),objects,result,where+'.intents')
    from .production_motion import validate as validate_motion
    result.update(validate_motion(value,{**result,'objects':topology_objects},kinds,bones,where))
    from .production_outputs import validate_outputs
    if 'camera' in value and kinds.get(value['camera'])!='camera':fail('TYPE_MISMATCH','render camera must reference a camera object',where+'.camera')
    result.update(validate_outputs({**value,**{k:result[k] for k in ('frameStart','frameEnd','currentFrame')}},objects,where))
    from .render_features import normalize as normalize_features
    normalize_features(value,result,graph_nodes)
    return result


def input_files(production):
    return {i['id']:i['file'] for i in production.get('images',[])}


def verify_snapshot(spec,actual,directory):
    """Judge persisted native readback against authored semantics and motion math."""
    from .settings import matching
    from schemaxis.artifacts import file_digest
    if not isinstance(actual,dict):fail('VERIFICATION_FAILED','production readback missing')
    def same(found,expected,where):
        if not matching(found,expected):fail('VERIFICATION_FAILED','production native value differs',where)
    from .mesh_edits import verify as verify_edits
    edited_geometry=verify_edits(spec,actual)
    from .mesh_data import verify as verify_mesh_data
    verify_mesh_data(spec['meshData'],actual.get('meshData',[]))
    from .material_assignments import verify as verify_materials
    verify_materials(spec.get('materialAssignments',[]),actual.get('materialAssignments',[]))
    from .geometry_resources import verify as verify_resources
    verify_resources(spec.get('geometryResources',[]),actual.get('geometryResources',[]))
    units={'metres':1,'millimetres':.001,'centimetres':.01,'inches':.0254,'feet':.3048}
    same(actual.get('timeline'),{**{k:spec[k] for k in ('frameStart','frameEnd','fps','currentFrame','gravity')},'scaleLength':units[spec['units']]},'production.timeline')
    same(actual.get('collections'),spec['collections'],'production.collections')
    same(actual.get('parents'),{h['object']:h['parent'] for h in spec['hierarchy']},'production.hierarchy')
    for field in ('materialBindings','geometryBindings','tracks','skin','constraints','rigidBodies','cloth','collisionObjects'):
        same(actual.get(field),spec[field],'production.'+field)
    expected_rigs=[{'id':r['id'],'bones':sorted(r['bones'],key=lambda b:b['id'])} for r in spec['rigs']]
    actual_rigs=[{'id':r['id'],'bones':sorted(r['bones'],key=lambda b:b['id'])} for r in actual.get('rigs',[])]
    same(actual_rigs,expected_rigs,'production.rigs')
    same(actual.get('nodeGroups'),[{**g,'links':sorted(g['links'],key=lambda l:(l['to']['node'],l['to']['socket'],l['from']['node'],l['from']['socket']))} for g in spec['nodeGroups']],'production.nodeGroups')
    for field in ('materialGraphs','geometryGraphs'):
        expected=[{**g,'links':sorted(g['links'],key=lambda l:(l['to']['node'],l['to']['socket'],l['from']['node'],l['from']['socket']))} for g in (all_material_graphs(spec) if field=='materialGraphs' else spec[field])]
        same(actual.get(field),expected,'production.'+field)
    if 'compositor' in spec:
        g=spec['compositor'];same(actual.get('compositor'),{**g,'links':sorted(g['links'],key=lambda l:(l['to']['node'],l['to']['socket'],l['from']['node'],l['from']['socket']))},'production.compositor')
    sources=json.loads((directory/'sources.json').read_text()) if (directory/'sources.json').is_file() else {}
    expected_images=[{'id':i['id'],'sha256':sources['production:'+i['id']]['sha256'],'colourSpace':i['colourSpace'],'pack':i['pack'],'alphaMode':i['alphaMode']} for i in spec['images']]
    same(actual.get('images'),expected_images,'production.images')
    # Native object local transforms may be changed by world-preserving parenting
    # and animated tracks. Their actual evaluated effect is independently checked
    # at authored keys and midpoints below, not compared to static defaults.
    if len(actual.get('objects',[]))!=len(spec['objects']):fail('VERIFICATION_FAILED','production object membership differs')
    expected_assets=spec['assets'];asset_readback=actual.get('assets')
    if not isinstance(asset_readback,list) or len(asset_readback)!=len(expected_assets):fail('VERIFICATION_FAILED','asset membership differs')
    from .production_outputs import METRES
    for a,b in zip(expected_assets,asset_readback):
        from .asset_fidelity import check_version
        check_version(b.get('fidelity'),'production.assets.'+a['id']+'.fidelity')
        same({k:b.get(k) for k in ('id','format','sourceSha256','coordinateScale')},{'id':a['id'],'format':a['format'],'sourceSha256':sources['asset:'+a['id']]['sha256'],'coordinateScale':METRES[a['sourceUnits']]/METRES[spec['units']]},'production.assets.'+a['id'])
        from .production_assets import verify_selection
        verify_selection(a,b.get('selection'))
        members=b.get('members')
        if not isinstance(members,list) or not members or len(members)>4096 or any(not isinstance(m,dict) or not m.get('name','').startswith(a['id']+'--') for m in members):fail('VERIFICATION_FAILED','asset member records invalid',a['id'])
    from .production_motion_verify import verify as verify_motion
    verify_motion(spec,actual.get('motion'),actual.get('samples',[]),edited_geometry)
    parented={h['object'] for h in spec['hierarchy']}|{n for i in spec['intents'] for n in i['objects']}
    from .production_intents import verify_intents
    verify_intents(spec['intents'],actual.get('intents'))
    animated_fields={}
    channel_fields={'visibility':'hidden','lightEnergy':'energy','lightColour':'colour','cameraLens':'lens','cameraScale':'orthographicSize','cameraFocus':'focusDistance','cameraAperture':'aperture'}
    def animated_field(obj,track):
        if not track.get('bone') and track['channel'] not in ('shapeValue','morphProgress'):
            animated_fields.setdefault(obj,set()).add(channel_fields.get(track['channel'],track['channel']))
    for track in spec['tracks']:animated_field(track['object'],track)
    for layer in spec['layers']:
        bindings={b['target']:b['object'] for b in layer['bindings']}
        for track in next(c for c in spec['clips'] if c['id']==layer['clip'])['tracks']:
            animated_field(bindings[track['target']],track)
    # Later material bindings replace construction materials. Their actual slots
    # are checked above, including every resolved descendant of a bound root.
    rebound={b['object'] for b in spec['materialBindings']}
    changed=True
    while changed:
        previous=set(rebound)
        rebound.update(h['object'] for h in spec['hierarchy'] if h['parent'] in rebound)
        for o in spec['objects']:
            if o['kind']=='collectionInstance' and o['id'] in rebound:
                collection_ids={o['source']}
                growing=True
                while growing:
                    before=set(collection_ids)
                    collection_ids.update(c['id'] for c in spec['collections'] if c['parent'] in collection_ids)
                    growing=before!=collection_ids
                rebound.update(item['id'] for item in spec['objects'] if item['collection'] in collection_ids)
            if o['kind']=='instance' and o.get('linked',True):
                if o['source'] in rebound:rebound.add(o['id'])
                if o['id'] in rebound:rebound.add(o['source'])
        changed=rebound!=previous
    rebound.update(owner for record in actual.get('materialAssignments',[]) for owner in record['owners'])
    # Explicit mesh-data copies change the final sharing promised by instance
    # construction; judge this from intent rather than dropping the linked check.
    data_groups={n:('external',n) for n in {o['source'] for o in spec['objects'] if o['kind']=='instance'}}
    pending=list(spec['objects'])
    while pending:
        ready=[o for o in pending if o['kind']!='instance' or o['source'] not in {x['id'] for x in pending}]
        if not ready:fail('VERIFICATION_FAILED','instance dependency cycle')
        for o in ready:
            data_groups[o['id']]=data_groups.get(o['source'],('external',o['source'])) if o['kind']=='instance' and o['linked'] else ('object',o['id'])
            pending.remove(o)
    for channel in [*spec.get('meshEdits',[]),*spec['meshData'],*(s for s in spec.get('materialAssignments',[]) if s['kind']=='layout')]:
        if channel['sharing']=='copy' and not channel['sourceObject']:data_groups[channel['object']]=('copy',channel['object'])
    for expected,found in zip(spec['objects'],actual['objects']):
        if expected['kind']=='mesh' and expected['id'] in edited_geometry:
            geometry=edited_geometry[expected['id']];expected={**expected,'vertices':geometry['vertices'],'faces':geometry['faces'],'smooth':all(geometry['smooth']),'uv':[]}
        if expected['kind']=='instance':expected={**expected,'linked':data_groups[expected['id']]==data_groups[expected['source']]}
        ignore=set(animated_fields.get(expected['id'],()))
        if expected['id'] in parented:ignore|={'location','rotation','scale'}
        if expected['id'] in rebound:ignore.add('material')
        # Camera scale names the orthographic size, whereas object transforms
        # have a separate scale vector: the camera record uses objectScale.
        same({k:v for k,v in found.items() if k not in ignore},{k:v for k,v in expected.items() if k not in ignore},'production.objects.'+expected['id'])
    from .production_motion import frames as motion_frames
    frames=sorted(motion_frames(spec)|{k['frame'] for t in spec['tracks'] for k in t['keys']}|{(a['frame']+b['frame'])//2 for t in spec['tracks'] for a,b in zip(t['keys'],t['keys'][1:])}|set(spec['simulationFrames'])|{spec['currentFrame']})
    samples=actual.get('samples',[])
    if [s.get('frame') for s in samples]!=frames:fail('VERIFICATION_FAILED','production evaluated frame membership differs')
    def at(track,frame):
        keys_=track['keys']
        if frame<=keys_[0]['frame']:return keys_[0]['value']
        if frame>=keys_[-1]['frame']:return keys_[-1]['value']
        a,b=next((a,b) for a,b in zip(keys_,keys_[1:]) if a['frame']<=frame<=b['frame'])
        if frame==b['frame']:return b['value']
        if track['interpolation']=='CONSTANT' or track['channel']=='visibility':return a['value']
        if track['interpolation']=='BEZIER':return None
        fraction=(frame-a['frame'])/(b['frame']-a['frame'])
        if isinstance(a['value'],list):return [x+(y-x)*fraction for x,y in zip(a['value'],b['value'])]
        return a['value']+(b['value']-a['value'])*fraction
    for sample in samples:
        if len(sample.get('channels',[]))!=len(spec['tracks']):fail('VERIFICATION_FAILED','evaluated channel membership differs')
        for t,v in zip(spec['tracks'],sample['channels']):
            expectation=at(t,sample['frame'])
            if expectation is not None:same(v,expectation,'production.motion.'+t['object'])
        for identity,obj in sample.get('objects',{}).items():
            matrix=obj.get('matrix')
            if not isinstance(matrix,list) or len(matrix)!=4 or any(not isinstance(row,list) or len(row)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in row) for row in matrix):fail('VERIFICATION_FAILED','evaluated matrix malformed',identity)
            if 'geometrySha256' in obj and (not isinstance(obj['geometrySha256'],str) or len(obj['geometrySha256'])!=64):fail('VERIFICATION_FAILED','evaluated geometry hash malformed',identity)


def graph_references(spec,graph_nodes):
    """Select only mesh/material DAG dependencies actually used by production."""
    requested=set()
    for obj in spec['objects']:
        if obj['kind']=='instance':requested.add(obj['source'])
        if obj['material']:requested.add(obj['material'])
    for h in spec['hierarchy']:requested.update((h['object'],h['parent']))
    for field in ('tracks','skin','constraints','rigidBodies','cloth'):
        for entry in spec[field]:
            requested.add(entry['object'])
            if entry.get('target'):requested.add(entry['target'])
    for field,other in [('materialBindings','material'),('geometryBindings','graph')]:
        for entry in spec[field]:requested.update((entry['object'],entry[other]))
    requested.update(spec['collisionObjects'])
    requested.update(m['object'] for m in spec['shapeKeys'])
    requested.update(m['object'] for m in spec['meshData'])
    requested.update(m['object'] for m in spec.get('meshEdits',[]))
    for assignment in spec.get('materialAssignments',[]):
        requested.add(assignment['object']);requested.update(slot['material'] for slot in assignment['slots'])
    from .geometry_resources import public_dependencies
    requested.update(public_dependencies(spec))
    requested.update(b['object'] for l in spec['layers'] for b in l['bindings'])
    for entry in [*spec['exports'],*spec['intents']]:requested.update(entry['objects'])
    for graph in spec['geometryGraphs']:
        for node in graph['nodes']:
            if node['kind']=='setMaterial':requested.add(node['values']['material'])
    from .node_groups import references
    groups={g['id']:g for g in spec['nodeGroups']}
    for group in spec['nodeGroups']:
        requested.update(ref for kind,ref in references(group,group['family'],groups,group) if kind in ('material','object'))
        requested.update(s['default'] for s in group['inputs']+group['outputs'] if s['kind'] in ('material','object') and s.get('default'))
    for field,family in [('materialGraphs','material'),('geometryGraphs','geometry')]:
        for graph in (all_material_graphs(spec) if field=='materialGraphs' else spec[field]):requested.update(ref for kind,ref in references(graph,family,groups) if kind in ('material','object'))
    if 'compositor' in spec:requested.update(ref for kind,ref in references(spec['compositor'],'compositor',groups) if kind in ('material','object'))
    return sorted(requested&set(graph_nodes))
