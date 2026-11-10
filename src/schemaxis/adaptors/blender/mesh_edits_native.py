"""Apply finite edits on isolated Mesh IDs; rebuild source proof on fresh reopen."""
import copy
import bpy
from schemaxis.errors import fail,SchemaxisError
from . import mesh_edits as e
from .mesh_data_native import target,restore


def geometry(mesh):
    if max(len(mesh.vertices),len(mesh.edges),len(mesh.polygons),len(mesh.loops))>e.LIMIT:fail('RESOURCE_BUDGET_EXCEEDED','source mesh exceeds bounded edit domains')
    return e.mesh([list(v.co) for v in mesh.vertices],[list(p.vertices) for p in mesh.polygons],
                  [list(edge.vertices) for edge in mesh.edges],[p.material_index for p in mesh.polygons],[p.use_smooth for p in mesh.polygons])


def admit_data(s,obj):
    mesh=obj.data
    if mesh.shape_keys or obj.vertex_groups:fail('UNSUPPORTED_MESH_EDIT_DATA','existing shape keys/vertex groups require reviewed topology propagation; edit before authoring new keys/skin')
    ignored={'position','material_index','sharp_face','sharp_edge','uv_seam','.select_vert','.select_edge','.select_poly'}
    extras=[a.name for a in mesh.attributes if a.name not in ignored and not a.is_internal and not a.is_required]
    has_data=bool(mesh.uv_layers or mesh.has_custom_normals or extras or any(edge.use_seam or edge.use_edge_sharp for edge in mesh.edges))
    if has_data and s['dataPolicy']!='discard':fail('UNSUPPORTED_MESH_EDIT_DATA','existing UV/custom/edge data needs explicit dataPolicy:discard; new fields follow edits',s['object'])


def build(specs,objects):
    plans=[];shared=set();baselines=[];bindings=[];total=0
    for s in specs:
        obj=target(s,objects);admit_data(s,obj);base=geometry(obj.data);owners=sorted(o.name for o in bpy.data.objects if o.data==obj.data)
        if s['sharing']=='refuse' and len(owners)>1:fail('SHARED_MESH_DATA','mesh editing needs explicit copy/shared ownership',s['object'])
        if s['sharing']!='copy':
            if obj.data in shared:fail('SHARED_MESH_DATA','combine shared Mesh edit declarations or isolate copies')
            shared.add(obj.data)
        for stage in s['steps']:
            if stage['kind']=='bisect' and stage['cap'] and stage['capMaterial']>=max(1,len(obj.data.materials)):fail('INVALID_MESH_EDIT','plane cap material slot is absent',s['object'])
        result,_=e.replay(base,s['steps']);total+=len(base['vertices'])+sum(map(len,base['faces']))+len(result['vertices'])+sum(map(len,result['faces']))
        if total>1000000:fail('RESOURCE_BUDGET_EXCEEDED','aggregate mesh edit source/result domains exceed one million elements')
        plans.append((s,obj,result))
        baselines.append({**{k:s[k] for k in e.COMMON},'nativeObject':obj.name,'owners':owners,'geometry':base})
    if len({obj.as_pointer() for _,obj,_ in plans})!=len(plans):fail('AMBIGUOUS_MESH_TARGET','mesh edit selectors resolve to the same native Object')
    # Complete semantic, data-loss and growth admission precedes every rebind.
    for s,obj,result in sorted(plans,key=lambda p:p[0]['sharing']!='copy'):
        original=obj.data;mesh=bpy.data.meshes.new(original.name+'-edited')
        mesh.from_pydata(result['vertices'],result['looseEdges'],result['faces'])
        for material in original.materials:mesh.materials.append(material)
        for face,material,smooth in zip(mesh.polygons,result['materials'],result['smooth']):face.material_index=material;face.use_smooth=smooth
        mesh.update()
        written=geometry(mesh)
        try:e.admit(written,require_area=True)
        except SchemaxisError:fail('NATIVE_VALUE_MISMATCH','native Mesh precision collapsed an edited face; recenter or rescale local geometry',s['object'])
        if not e.geometry_matches(written,result):fail('NATIVE_VALUE_MISMATCH','native Mesh coordinate rounding exceeds one millionth of its span; recenter or rescale local geometry',s['object'])
        owners=[o for o in bpy.data.objects if o.data==original] if s['sharing']=='shared' else [obj]
        for owner in owners:bindings.append((owner,owner.data));owner.data=mesh
    return bindings,baselines


def observe(spec,objects):
    records=[]
    for s in spec.get('meshEdits',[]):
        obj=target(s,objects);mesh=obj.data;allowed=set();seams=set()
        for channel in spec['meshData']:
            if target(channel,objects).data==mesh:
                allowed.update(c['name'] for c in channel['attributes']+channel['uvMaps'])
                for uv in channel['uvMaps']:
                    if uv['method']=='unwrap':seams.update(tuple(sorted(edge)) for edge in uv['seams'])
        ignored={'position','material_index','sharp_face','sharp_edge','uv_seam','.select_vert','.select_edge','.select_poly'}
        if any(a.name not in ignored|allowed and not a.is_internal and not a.is_required for a in mesh.attributes):fail('VERIFICATION_FAILED','edited mesh retains undeclared custom data',obj.name)
        if any(edge.use_edge_sharp or edge.use_seam!=(tuple(sorted(edge.vertices)) in seams) for edge in mesh.edges):fail('VERIFICATION_FAILED','edited edge flags differ from post-edit field/UV intent',obj.name)
        observed=geometry(obj.data);e.admit(observed,require_area=True)
        records.append({**{k:s[k] for k in e.COMMON},'nativeObject':obj.name,
                        'owners':sorted(o.name for o in bpy.data.objects if o.data==obj.data),'geometry':observed})
    return records


def source_baselines(master,selection,prepared,visit,sources):
    """Reconstruct constructors/captured sources; never trust a saved base witness.

    Called before opening each submitted native scene. Rebuild original sources,
    replay edits and reproduce field ownership/material binding; no authored
    deformation, motion or simulation is used as a source witness.
    """
    if not master.document['scenes'][0]['production'].get('meshEdits'):return []
    from .native import Backend,configure_render
    from .production_native import Production
    from schemaxis.pipeline import RuntimeClosure
    bpy.ops.wm.read_factory_settings(use_empty=True);scene=bpy.context.scene;configure_render(scene,prepared['renderSettings'])
    camera=bpy.data.objects.new('__schemaxis_camera',bpy.data.cameras.new('__schemaxis_camera'));scene.collection.objects.link(camera);scene.camera=camera
    active=RuntimeClosure(master,Backend(sources));active.activate(selection.roots);active.apply(visit)
    spec=copy.deepcopy(master.document['scenes'][0]['production'])
    for key in ('geometryResources','geometryGraphs','geometryBindings','tracks','skin','constraints','rigidBodies','cloth','collisionObjects','simulationFrames','shapeKeys','clips','layers','intents'):spec[key]=[]
    # Reproduce only field ownership before material binding. Numeric fields/UV
    # cannot change base topology; clearing their writes avoids solver work.
    spec['meshData']=[{**s,'attributes':[],'uvMaps':[],'activeUV':'','renderUV':''} for s in spec['meshData']]
    spec.pop('compositor',None);spec['nodeGroups']=[g for g in spec['nodeGroups'] if g['family']=='material']
    production=Production(spec,active.handles,sources)
    # JSON-compatible immutable values survive the later open_mainfile. No
    # staged datablock handle, source pointer or serialized witness is reused.
    return production.edit_baselines()
