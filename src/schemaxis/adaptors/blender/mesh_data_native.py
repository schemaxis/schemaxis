"""Finite mesh-channel writes and isolated UV editing, with current-byte readback."""
import json
import bpy
from schemaxis.errors import fail
from .mesh_data import CHANNELS,edges_for,values_for,validate_topology,projection,transform_uv


def target(spec,objects,*,mesh_only=True):
    root=objects[spec['object']]
    if root.type=='MESH' or not mesh_only and not spec['sourceObject']:return root
    if 'schemaxisAssetMembers' not in root:fail('TYPE_MISMATCH','selected Object has no mesh data',spec['object'])
    from .production_asset_collections import asset_members
    members=[o for o in asset_members(root) if not mesh_only or o.type=='MESH']
    if spec['sourceObject']:
        if root.get('schemaxisAssetFormat') not in ('blend','glb','gltf'):fail('AMBIGUOUS_MESH_TARGET','sourceObject requires a native or unique glTF mesh-node identity; use a single-mesh asset or adopt a native project',spec['object'])
        requested=spec['sourceObject']
        available=json.loads(root.get('schemaxisAssetSourceObjects','[]'));collisions=json.loads(root.get('schemaxisAssetSourceCollisions','[]'))
        if requested not in available or requested in collisions:fail('AMBIGUOUS_MESH_TARGET','source object identity was absent or collided during append; rename the source or use a unique source library',requested)
        records=json.loads(root['schemaxisAssetMembers']);names={r['name'] for r in records if r['sourceName']==requested}
        members=[o for o in members if o.name in names]
    if len(members)!=1:fail('AMBIGUOUS_MESH_TARGET','select one native mesh sourceObject, or provide an asset containing exactly one mesh',spec['object'])
    return members[0]


def _topology(mesh):return [list(v.co) for v in mesh.vertices],[list(f.vertices) for f in mesh.polygons]


def _ordered(mesh,domain):
    if domain!='EDGE':return list(range(len({'POINT':mesh.vertices,'FACE':mesh.polygons,'CORNER':mesh.loops}[domain])))
    return [i for _,i in sorted((tuple(sorted(e.vertices)),e.index) for e in mesh.edges)]


def _coordinates(mesh,uv):return [[list(uv.data[i].uv) for i in f.loop_indices] for f in mesh.polygons]


def _write_uv(mesh,uv,coords):
    for face,points in zip(mesh.polygons,coords):
        for index,point in zip(face.loop_indices,points):uv.data[index].uv=point


def _operator_uv(obj,spec):
    # Native operators get a private scene containing the SAME Object/data. Its
    # source collection membership and parent/instance identity remain untouched.
    original=bpy.context.window.scene;stage=bpy.data.scenes.new('__schemaxis_uv_stage')
    stage.collection.objects.link(obj);bpy.context.window.scene=stage
    try:
        bpy.context.view_layer.objects.active=obj;obj.select_set(True)
        for p in obj.data.polygons:p.select=True
        if spec['pack'] and spec['method'] not in ('unwrap','smart'):
            uv=obj.data.uv_layers.active;points=[list(p.uv) for p in uv.data]
            low=[min(p[i] for p in points) for i in (0,1)];span=max(max(p[i] for p in points)-low[i] for i in (0,1))
            if not span:fail('UV_MAPPING_FAILED','packing needs non-degenerate texture coordinates',obj.name)
            for p in uv.data:p.uv=[(p.uv[i]-low[i])/span for i in (0,1)]
        bpy.ops.object.mode_set(mode='EDIT');bpy.ops.mesh.select_all(action='SELECT')
        if spec['method']=='unwrap':
            outcome=bpy.ops.uv.unwrap(method=spec['methodNative'],fill_holes=spec['fillHoles'],correct_aspect=False,margin=0,iterations=spec['iterations'])
        elif spec['method']=='smart':
            outcome=bpy.ops.uv.smart_project(angle_limit=spec['angle'],area_weight=spec['areaWeight'],correct_aspect=False,island_margin=0)
        else:outcome={'FINISHED'}
        if outcome!={'FINISHED'}:fail('UV_MAPPING_FAILED','native UV mapping did not finish',obj.name)
        if spec['pack']:
            # FRACTION means tile-space separation. A conservative minimum
            # dimension guarantees at least the requested gap on both axes.
            margin=spec['paddingPixels']/min(spec['textureSize'])
            outcome=bpy.ops.uv.pack_islands(udim_source='CLOSEST_UDIM',rotate=spec['rotate'],rotate_method='ANY',scale=True,merge_overlap=False,margin_method='FRACTION',margin=margin,pin=False,shape_method='CONCAVE')
            if outcome!={'FINISHED'}:fail('UV_MAPPING_FAILED','native UV packing did not finish',obj.name)
        bpy.ops.object.mode_set(mode='OBJECT')
    finally:
        if obj.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
        bpy.context.window.scene=original;bpy.data.scenes.remove(stage)


def build(specs,objects):
    plans=[];shared={};restore=[]
    # Resolve and admit the entire write set BEFORE changing any mesh.
    for s in specs:
        obj=target(s,objects);mesh=obj.data;vertices,faces=_topology(mesh);validate_topology(s,vertices,faces,edges=[list(e.vertices) for e in mesh.edges])
        owners=[o for o in bpy.data.objects if o.data==mesh]
        if len(owners)>1 and s['sharing']=='refuse':fail('SHARED_MESH_DATA','mesh has multiple Object owners; choose copy or shared explicitly',s['object'])
        if s['sharing']!='copy':
            if mesh in shared:fail('SHARED_MESH_DATA','multiple declarations would write one shared Mesh; combine or explicitly copy targets',s['object'])
            shared[mesh]=s
        for a in s['attributes']:
            existing=mesh.attributes.get(a['name'])
            if existing and (existing.is_internal or existing.is_required):fail('INVALID_MESH_DATA','built-in mesh attributes cannot be overwritten',a['name'])
            if existing and a['name'] in mesh.uv_layers:fail('INVALID_MESH_DATA','UV maps must use the dedicated coordinate abstraction',a['name'])
        names=set(mesh.uv_layers.keys())
        for u in s['uvMaps']:
            if u['method']=='copy' and u['source'] not in names:fail('UNKNOWN_REFERENCE','UV copy source is absent from the original mesh and earlier declarations',u['source'])
            names.add(u['name'])
        if len(names)>8:fail('RESOURCE_BUDGET_EXCEEDED','original and declared UV sets together exceed the native eight-map limit',s['object'])
        plans.append((s,obj,owners))
    if len({obj.as_pointer() for _,obj,_ in plans})!=len(plans):fail('AMBIGUOUS_MESH_TARGET','different selectors resolved to the same native Object; combine channels')
    for s,obj,owners in sorted(plans,key=lambda p:p[0]['sharing']!='copy'):
        # A fresh data ID makes production cleanup restore upstream DAG state.
        # Explicit shared writes rebind every native Object owner atomically.
        original=obj.data;mesh=original.copy();selected=[o for o in bpy.data.objects if o.data==original] if s['sharing']=='shared' else [obj]
        for owner in selected:restore.append((owner,owner.data));owner.data=mesh
        for c in s['attributes']:
            old=mesh.attributes.get(c['name'])
            if old:mesh.attributes.remove(old)
            native,member,_,_=CHANNELS[c['kind']];a=mesh.attributes.new(c['name'],native,c['domain'])
            if a.name!=c['name']:fail('INVALID_MESH_DATA','mesh channel name collided with an existing native channel',c['name'])
            values=values_for(c,len(a.data));indices=_ordered(mesh,c['domain'])
            for i,v in zip(indices,values):setattr(a.data[i],member,[x/255 for x in v] if c['kind']=='byteColour' else v)
        vertices,faces=_topology(mesh)
        for u in s['uvMaps']:
            source=_coordinates(mesh,mesh.uv_layers[u['source']]) if u['method']=='copy' else None
            uv=mesh.uv_layers.get(u['name']) or mesh.uv_layers.new(name=u['name'])
            if uv.name!=u['name']:fail('INVALID_MESH_DATA','UV name collides with a mesh attribute',u['name'])
            mesh.uv_layers.active=uv
            if u['method']=='coordinates':_write_uv(mesh,uv,u['coordinates'])
            elif u['method']=='copy':_write_uv(mesh,uv,source)
            elif u['method'] in ('planar','box'):_write_uv(mesh,uv,projection(u,vertices,faces))
            elif u['method']=='unwrap':
                seams={tuple(sorted(e)) for e in u['seams']}
                for edge in mesh.edges:edge.use_seam=tuple(sorted(edge.vertices)) in seams
            if u['method'] in ('unwrap','smart') or u['pack']:
                native_spec={**u}
                if u['method']=='unwrap':native_spec['methodNative']=u['unwrapMethod']
                _operator_uv(obj,native_spec)
            if 'transform' in u:_write_uv(mesh,uv,transform_uv(_coordinates(mesh,uv),u['transform']))
        if s['uvMaps']:
            mesh.uv_layers.active=mesh.uv_layers[s['activeUV'] or s['uvMaps'][0]['name']]
            mesh.uv_layers[s['renderUV'] or s['uvMaps'][0]['name']].active_render=True
        colours=[a['name'] for a in s['attributes'] if a['kind'] in ('colour','byteColour')]
        if colours:
            mesh.color_attributes.active_color_index=mesh.color_attributes.find(s['activeColour'] or colours[0])
            mesh.color_attributes.render_color_index=mesh.color_attributes.find(s['renderColour'] or colours[0])
        mesh.update()
    return restore


def restore(bindings):
    for obj,mesh in reversed(bindings):
        current=obj.data;obj.data=mesh
        if current.users==0:bpy.data.meshes.remove(current)


def observe(specs,objects):
    out=[]
    for s in specs:
        obj=target(s,objects);m=obj.data;vertices,faces=_topology(m);attributes=[]
        for c in s['attributes']:
            a=m.attributes.get(c['name']);native,member,_,_=CHANNELS[c['kind']]
            if a is None or (a.data_type,a.domain)!=(native,c['domain']):fail('VERIFICATION_FAILED','mesh channel identity/type/domain differs',c['name'])
            values=[]
            for i in _ordered(m,c['domain']):
                v=getattr(a.data[i],member);v=list(v) if hasattr(v,'__len__') else v
                if c['kind']=='byteColour':v=[round(x*255) for x in v]
                values.append(v)
            attributes.append({'name':a.name,'kind':c['kind'],'domain':a.domain,'values':values})
        maps=[]
        for u in s['uvMaps']:
            uv=m.uv_layers.get(u['name'])
            if uv is None:fail('VERIFICATION_FAILED','named UV map is missing',u['name'])
            maps.append({'name':uv.name,'coordinates':_coordinates(m,uv),'seams':[list(v) for v in sorted(tuple(sorted(e.vertices)) for e in m.edges if e.use_seam)]})
        out.append({'object':s['object'],'sourceObject':s['sourceObject'],'sharing':s['sharing'],'nativeObject':obj.name,
            'owners':sorted(o.name for o in bpy.data.objects if o.data==m),'vertices':vertices,'faces':faces,'edges':[list(e) for e in sorted(tuple(sorted(e.vertices)) for e in m.edges)],'attributes':attributes,'uvMaps':maps,
            'activeUV':m.uv_layers.active.name if m.uv_layers.active else '', 'renderUV':next((u.name for u in m.uv_layers if u.active_render),''),
            'activeColour':m.color_attributes.active_color.name if m.color_attributes.active_color else '',
            'renderColour':m.color_attributes[m.color_attributes.render_color_index].name if 0<=m.color_attributes.render_color_index<len(m.color_attributes) else ''})
    return out
