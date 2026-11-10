"""Isolated scene-production executor and fresh-process readback.

Only trusted descriptors select native constructors/properties. Durable named
objects, node trees, keyframes, rigs and simulation settings remain editable.
"""
import hashlib
import json
from pathlib import Path
import bpy
from .surface_compile import all_material_graphs
from mathutils import Matrix
from schemaxis.errors import fail
from schemaxis.artifacts import file_digest
from .production import CHANNELS,CONSTRAINTS,_ordered
from .node_native import build as build_graph,observe as observe_graph
from .settings import matching


def fcurves(obj):
    if not obj.animation_data or not obj.animation_data.action:return []
    action=obj.animation_data.action;curves=[]
    for layer in action.layers:
        for strip in layer.strips:
            bag=strip.channelbag(obj.animation_data.action_slot)
            if bag:curves.extend(bag.fcurves)
    return curves


def _path(track):
    path=CHANNELS[track['channel']][0].removeprefix('data.')
    return 'pose.bones['+json.dumps(track['bone'])+'].'+path if track['bone'] else path


def _channel(obj,track):
    target=obj.pose.bones[track['bone']] if track['bone'] else obj
    path=CHANNELS[track['channel']][0]
    if path.startswith('data.'):target=target.data;path=path[5:]
    return target,path


class Production:
    def __init__(self,spec,graph_handles,sources):
        self.spec=spec;self.scene=bpy.context.scene
        self.objects={k:v for k,v in graph_handles.items() if isinstance(v,bpy.types.Object)}
        self.materials={k:v for k,v in graph_handles.items() if isinstance(v,bpy.types.Material)}
        from .shader_budget_native import ShaderBudget
        self.shader_budget=ShaderBudget()
        for material in self.materials.values():self.shader_budget.material(material)
        from .object_materials_native import admit_objects
        admit_objects(self.objects.values(),self.shader_budget)
        self.original={k:{'matrix':o.matrix_world.copy(),'parent':o.parent,'materials':list(o.data.materials),'animation':o.animation_data.action if o.animation_data else None,'modifiers':set(o.modifiers),'constraints':set(o.constraints)} for k,o in self.objects.items()}
        self.owned_pools=[bpy.data.materials,bpy.data.node_groups,bpy.data.meshes,bpy.data.curves,bpy.data.armatures,bpy.data.lights,bpy.data.cameras,bpy.data.actions,bpy.data.images,bpy.data.fonts,bpy.data.collections,bpy.data.worlds,bpy.data.linestyles]
        self.pool_before=[set(p) for p in self.owned_pools]
        self.created=[];self.collections={};self.images={};self.graphs=[];self.added_materials=[];self.simulations=[]
        self.original_materials={};self.projection_sources={};self.features=None;self.caches=None
        self.previous_rigidbody_world=self.scene.rigidbody_world
        self._build(sources)
        from .render_features_native import Features,enabled
        if enabled(spec):self.features=Features(self)

    def _build(self,sources):
        spec=self.spec;scene=self.scene
        scene.frame_start=spec['frameStart'];scene.frame_end=spec['frameEnd'];scene.render.fps=spec['fps'];scene.gravity=spec['gravity']
        scene.unit_settings.system='METRIC' if spec['units'] not in ('inches','feet') else 'IMPERIAL'
        scene.unit_settings.scale_length={'metres':1,'millimetres':.001,'centimetres':.01,'inches':.0254,'feet':.3048}[spec['units']]
        for identity in _ordered(spec['collections'],'id','parent','collections'):
            c=next(c for c in spec['collections'] if c['id']==identity);native=bpy.data.collections.new(identity);self.collections[identity]=native
            (self.collections[c['parent']] if c['parent'] else scene.collection).children.link(native)
        image_pixels=0
        for image in spec['images']:
            source=sources['production:'+image['id']]['retained'];native=bpy.data.images.load(source,check_existing=False);native.name=image['id']
            from .image_assets_native import configure as configure_image
            image_pixels=configure_image(native,image,image_pixels)
            native.use_fake_user=True
            native['schemaxisSourceSha256']=file_digest(source);self.images[image['id']]=native
        self.group_specs={g['id']:g for g in spec['nodeGroups']};self.native_groups={}
        for group in spec['nodeGroups']:
            if group['family']=='material':
                tree=build_graph(group,'material',self.images,self.materials,self.group_specs,self.native_groups,group)
                self.native_groups[group['id']]=tree;self.graphs.append(tree)
                self.shader_budget.group(tree)
        for graph in all_material_graphs(spec):
            material=build_graph(graph,'material',self.images,self.materials,self.group_specs,self.native_groups);self.materials[graph['id']]=material;self.added_materials.append(material)
            self.shader_budget.material(material)
        for rig in spec['rigs']:
            data=bpy.data.armatures.new(rig['id']);obj=bpy.data.objects.new(rig['id'],data);scene.collection.objects.link(obj);self.created.append(obj);self.objects[rig['id']]=obj
            bpy.context.view_layer.objects.active=obj;obj.select_set(True);bpy.ops.object.mode_set(mode='EDIT')
            for identity in _ordered(rig['bones'],'id','parent','bones'):
                bone=next(b for b in rig['bones'] if b['id']==identity);native=data.edit_bones.new(identity);native.head=bone['head'];native.tail=bone['tail'];native.use_deform=bone['deform']
                if bone['parent']:native.parent=data.edit_bones[bone['parent']];native.use_connect=bone['connected']
            bpy.ops.object.mode_set(mode='OBJECT');obj.select_set(False)
            for b in obj.pose.bones:b.rotation_mode='XYZ'
        from .production_asset_native import load_asset
        from .render_projection_native import requested
        projection_assets=requested(spec)
        for asset in spec['assets']:
            root,created,collection=load_asset(asset,scene,sources,self.collections,spec['units'],shader_budget=self.shader_budget,original_materials=self.original_materials,projection_sources=self.projection_sources if asset['id'] in projection_assets else None)
            self.created.extend(created);self.objects[asset['id']]=root;self.collections[collection.name]=collection
        order=_ordered([{'id':o['id'],'source':o.get('source','') if o['kind']=='instance' else ''} for o in spec['objects']],'id','source','objects',self.objects)
        for identity in order:
            o=next(o for o in spec['objects'] if o['id']==identity);kind=o['kind'];data=None
            if kind=='text':
                data=bpy.data.curves.new(identity,'FONT');data.body=o['body'];data.size=o['size'];data.extrude=o['extrude'];data.align_x=o['align']
            elif kind=='curve':
                data=bpy.data.curves.new(identity,'CURVE');data.dimensions='3D';data.bevel_depth=o['bevel'];data.bevel_resolution=o['resolution'];spline=data.splines.new('POLY');spline.points.add(len(o['points'])-1)
                for native,p in zip(spline.points,o['points']):native.co=(*p,1)
                spline.use_cyclic_u=o['closed']
            elif kind=='spline':
                from .spline_native import create as create_spline
                data=create_spline(o,self.materials)
            elif kind=='mesh':
                data=bpy.data.meshes.new(identity);data.from_pydata(o['vertices'],[],o['faces']);data.update()
                for face in data.polygons:face.use_smooth=o['smooth']
                if o.get('uv'):
                    uv=data.uv_layers.new(name='UVMap')
                    for face,coords in zip(data.polygons,o['uv']):
                        for index,p in zip(face.loop_indices,coords):uv.data[index].uv=p
            elif kind=='light':
                data=bpy.data.lights.new(identity,o['type']);data.energy=o['energy'];data.color=o['colour']
                if o['type']=='AREA':data.size=o['size']
                elif o['type'] in ('POINT','SPOT'):data.shadow_soft_size=o['size']
                if o['type']=='SPOT':data.spot_size=o['angle']
                elif o['type']=='SUN':data.angle=o['angle']
            elif kind=='camera':
                data=bpy.data.cameras.new(identity);data.type='PERSP' if o['projection']=='perspective' else 'ORTHO';data.lens=o['lens'];data.ortho_scale=o['orthographicSize'];data.clip_start=o['clipStart'];data.clip_end=o['clipEnd'];data.dof.use_dof=o['depthOfField'];data.dof.focus_distance=o['focusDistance'];data.dof.aperture_fstop=o['aperture']
            elif kind=='instance':
                source=self.objects[o['source']];data=source.data if o['linked'] else (source.data.copy() if source.data else None)
            if kind=='instance':
                obj=source.copy();obj.name=identity;obj.data=data;obj.parent=None;obj.animation_data_clear()
                obj.constraints.clear()
            else:obj=bpy.data.objects.new(identity,data)
            self.created.append(obj);self.objects[identity]=obj
            (self.collections[o['collection']] if o['collection'] else scene.collection).objects.link(obj)
            obj.location=o['location'];obj.rotation_mode='XYZ';obj.rotation_euler=o['rotation'];obj.scale=o['scale'];obj.hide_render=o['hidden']
            if o.get('displayColour',{}).get('kind')=='colour':
                if obj.type not in ('MESH','CURVE','SURFACE','FONT','META'):fail('TYPE_MISMATCH','display colour requires a geometric prototype, not an asset or collection carrier',identity+'.displayColour')
                obj.color=(*o['displayColour']['value'],1)
            if kind=='empty':obj.empty_display_size=o['displaySize']
            elif kind=='collectionInstance':obj.instance_type='COLLECTION';obj.instance_collection=self.collections[o['source']]
            if o['material']:
                if not data or not hasattr(data,'materials'):fail('TYPE_MISMATCH','material needs geometric object',identity)
                data.materials.clear();data.materials.append(self.materials[o['material']])
        from .mesh_edits_native import build as build_mesh_edits
        self.mesh_edit_bindings,self.mesh_edit_baselines=build_mesh_edits(spec.get('meshEdits',[]),self.objects)
        from .geometry_resource_native import resolve as resolve_resources
        resource_objects,resource_collections,_=resolve_resources(spec,self.objects,self.collections)
        from .spline_native import bind as bind_splines
        bind_splines(spec,self.objects,resource_objects)
        from .geometry_resource_native import admit as admit_resources
        # UV operators can evaluate the whole scene, including unrelated curves.
        # Admit source/profile expansion before any edit-mode mesh-data operator.
        admit_resources(spec,self.objects,resource_objects,resource_collections)
        from .mesh_data_native import build as build_mesh_data
        from .mesh_data_native import target as mesh_target
        legacy_uv={self.objects[o['id']] for o in spec['objects'] if o['kind']=='mesh' and o.get('uv') and 'UVMap' in self.objects[o['id']].data.uv_layers}
        for channel in spec['meshData']:
            if any(uv['name']=='UVMap' for uv in channel['uvMaps']):
                target=mesh_target(channel,self.objects)
                affected={o for o in bpy.data.objects if o.data==target.data} if channel['sharing']=='shared' else {target}
                if affected & legacy_uv:fail('INVALID_MESH_DATA','a mesh constructor owns UVMap; choose another map or remove its original uv array',channel['object'])
        self.mesh_bindings=build_mesh_data(spec['meshData'],self.objects)
        for group in spec['nodeGroups']:
            if group['family']!='material':
                tree=build_graph(group,group['family'],self.images,self.materials,self.group_specs,self.native_groups,group,resource_objects,resource_collections)
                self.native_groups[group['id']]=tree;self.graphs.append(tree)
        for graph in spec['geometryGraphs']:
            tree=build_graph(graph,'geometry',self.images,self.materials,self.group_specs,self.native_groups,objects=resource_objects,collections=resource_collections);self.graphs.append(tree)
        if 'compositor' in spec:
            tree=build_graph(spec['compositor'],'compositor',self.images,self.materials,self.group_specs,self.native_groups,objects=resource_objects,collections=resource_collections);self.graphs.append(tree);scene.compositing_node_group=tree
        for identity in _ordered(spec['hierarchy'],'object','parent','hierarchy',self.objects):
            h=next(h for h in spec['hierarchy'] if h['object']==identity);obj=self.objects[identity];world=obj.matrix_world.copy();obj.parent=self.objects[h['parent']]
            if h['keepWorld']:obj.matrix_world=world
        # Recheck after hierarchy transforms, before material resolution requests
        # the depsgraph. Attach modifiers only after material ownership is set.
        admitted_resources=admit_resources(spec,self.objects,resource_objects,resource_collections)
        self.mesh_edit_material_overrides=set()
        for b in spec['materialBindings']:
            obj=self.objects[b['object']]
            from .production_output_native import _resolved_geometry
            targets={native.original for native,_ in _resolved_geometry([obj])}
            for target in targets:
                self.mesh_edit_material_overrides.add(target.data)
                target.data.materials.clear();target.data.materials.append(self.materials[b['material']])
        from .material_assignments_native import build as build_material_assignments
        self.material_bindings=build_material_assignments(spec,self.objects,self.materials,self.mesh_edit_material_overrides)
        for b,obj in admitted_resources:
            mod=obj.modifiers.new('schemaxis-geometry-'+b['graph'],'NODES');mod.node_group=bpy.data.node_groups[b['graph']]
        for skin in spec['skin']:
            obj=self.objects[skin['object']]
            for weight in skin['weights']:
                if max(weight['vertices'])>=len(obj.data.vertices):fail('INVALID_SKIN','weight vertex index outside mesh',skin['object'])
                group=obj.vertex_groups.get(weight['bone']) or obj.vertex_groups.new(name=weight['bone']);group.add(weight['vertices'],weight['weight'],'REPLACE')
            mod=obj.modifiers.new('schemaxis-skin','ARMATURE');mod.object=self.objects[skin['rig']];mod.use_vertex_groups=True
        for c in spec['constraints']:
            obj=self.objects[c['object']];owner=obj.pose.bones[c['bone']] if c['bone'] else obj
            con=owner.constraints.new(CONSTRAINTS[c['kind']][0]);con.name=c['id'];con.influence=c['influence']
            if c['target']:con.target=self.objects[c['target']]
            if c['targetBone']:
                if not hasattr(con,'subtarget'):fail('UNSUPPORTED_CONSTRAINT','constraint does not support bone target',c['id'])
                con.subtarget=c['targetBone']
            if c['kind']=='followPath':con.use_fixed_location=True
            for semantic,(prop,_) in CONSTRAINTS[c['kind']][1].items():
                if prop=='use_xyz':
                    for axis,v in zip('xyz',c[semantic]):setattr(con,'use_'+axis,v)
                elif prop in ('minimum','maximum'):
                    con.owner_space='LOCAL'
                    for axis,v in zip('xyz',c[semantic]):
                        flag='use_limit_' if c['kind']=='limitRotation' else ('use_min_' if prop=='minimum' else 'use_max_')
                        setattr(con,flag+axis,True);setattr(con,('min_' if prop=='minimum' else 'max_')+axis,v)
                else:setattr(con,prop,c[semantic])
        from .production_motion_native import build as build_motion
        self.motion_owners=build_motion(spec,self.objects)
        for track in spec['tracks']:
            obj=self.objects[track['object']];target,path=_channel(obj,track)
            for key in track['keys']:
                setattr(target,path,key['value']);target.keyframe_insert(data_path=path,frame=key['frame'],group=track['bone'] or 'Motion')
            for curve in fcurves(obj.data if CHANNELS[track['channel']][0].startswith('data.') else obj):
                if curve.data_path==_path(track):
                    for key in curve.keyframe_points:key.interpolation=track['interpolation']
        for body in spec['rigidBodies']:
            obj=self.objects[body['object']];bpy.context.view_layer.objects.active=obj;obj.select_set(True);bpy.ops.rigidbody.object_add();obj.select_set(False);native=obj.rigid_body
            native.type=body['type'].upper();native.mass=body['mass'];native.friction=body['friction'];native.restitution=body['restitution'];native.collision_shape=body['shape'];native.kinematic=body['kinematic']
        for identity in spec['collisionObjects']:self.objects[identity].modifiers.new('schemaxis-collision','COLLISION')
        for cloth in spec['cloth']:
            obj=self.objects[cloth['object']];mod=obj.modifiers.new('schemaxis-cloth','CLOTH');settings=mod.settings
            for semantic,prop in [('quality','quality'),('mass','mass'),('tension','tension_stiffness'),('compression','compression_stiffness'),('shear','shear_stiffness'),('bending','bending_stiffness')]:setattr(settings,prop,cloth[semantic])
            mod.collision_settings.use_collision=cloth['collision'];mod.collision_settings.use_self_collision=cloth['selfCollision']
            if cloth.get('pinVertices'):
                if max(cloth['pinVertices'])>=len(obj.data.vertices):fail('INVALID_SIMULATION','pin vertex index outside mesh',cloth['object'])
                group=obj.vertex_groups.new(name='schemaxis-pins');group.add(cloth['pinVertices'],1,'REPLACE');settings.vertex_group_mass=group.name
            mod.point_cache.frame_start=spec['frameStart'];mod.point_cache.frame_end=spec['frameEnd']
        if scene.rigidbody_world:
            scene.rigidbody_world.point_cache.frame_start=spec['frameStart'];scene.rigidbody_world.point_cache.frame_end=spec['frameEnd']
        from .production_intent_native import apply_intents
        intent_result=apply_intents(spec['intents'],self.objects)
        self.created.extend(intent_result['created'])
        scene['schemaxisProduction']=json.dumps(spec,sort_keys=True)
        scene.frame_set(spec['currentFrame']);bpy.context.view_layer.update()
        from .surface_native import validate_uvs
        validate_uvs(spec)

    def edit_baselines(self):
        import copy
        from .mesh_data_native import target
        records=copy.deepcopy(self.mesh_edit_baselines)
        for s,b in zip(self.spec.get('meshEdits',[]),records):b['materialOverride']=target(s,self.objects).data in self.mesh_edit_material_overrides
        return records

    def prepare_caches(self,sources,project_path,event=None):
        if not self.spec.get('simulationCaches'):return
        from .cache_integration_native import FeatureCaches
        self.caches=FeatureCaches(self.spec,self.objects,sources,project_path,event=event)
        self.features.caches=self.caches

    def snapshot(self):
        result=observe(self.spec,self.objects,shader_budget=self.shader_budget,features=self.features);result['meshEditBaselines']=self.edit_baselines();return result

    def close(self):
        # Restore DAG-owned objects before another analytic state; saved files retain production.
        if self.features is not None:self.features.close()
        self.scene.compositing_node_group=None
        for owner in self.motion_owners:
            if owner.animation_data:
                for track in list(owner.animation_data.nla_tracks):owner.animation_data.nla_tracks.remove(track)
        from .mesh_data_native import restore as restore_mesh_data
        from .material_assignments_native import restore as restore_material_assignments
        restore_material_assignments(self.material_bindings)
        restore_mesh_data(self.mesh_bindings)
        restore_mesh_data(self.mesh_edit_bindings)
        morph_objects={m['object'] for m in self.spec['shapeKeys']}
        for identity,original in self.original.items():
            obj=self.objects[identity]
            for mod in list(obj.modifiers):
                if mod not in original['modifiers']:obj.modifiers.remove(mod)
            for con in list(obj.constraints):
                if con not in original['constraints']:obj.constraints.remove(con)
            obj.parent=original['parent'];obj.matrix_world=original['matrix'];obj.data.materials.clear()
            for m in original['materials']:obj.data.materials.append(m)
            if obj.animation_data:obj.animation_data.action=original['animation']
            if identity in morph_objects:obj.shape_key_clear()
            obj.vertex_groups.clear()
            if obj.rigid_body:
                bpy.context.view_layer.objects.active=obj;obj.select_set(True);bpy.ops.rigidbody.object_remove();obj.select_set(False)
        for obj in reversed(self.created):
            data=obj.data;bpy.data.objects.remove(obj,do_unlink=True)
            if data and data.users==0:
                if isinstance(data,bpy.types.Mesh):bpy.data.meshes.remove(data)
                elif isinstance(data,bpy.types.Curve):bpy.data.curves.remove(data)
                elif isinstance(data,bpy.types.Light):bpy.data.lights.remove(data)
                elif isinstance(data,bpy.types.Camera):bpy.data.cameras.remove(data)
                elif isinstance(data,bpy.types.Armature):bpy.data.armatures.remove(data)
        if self.previous_rigidbody_world is None and self.scene.rigidbody_world is not None:
            # Destroy process-local solver state after saving; free_bake would
            # delete already-published disk payloads and is deliberately unused.
            bpy.ops.rigidbody.world_remove()
        for collection in reversed(list(self.collections.values())):bpy.data.collections.remove(collection)
        for tree in reversed(self.graphs):bpy.data.node_groups.remove(tree)
        for material in self.added_materials:bpy.data.materials.remove(material)
        for image in self.images.values():bpy.data.images.remove(image)
        for pool,before in zip(self.owned_pools,self.pool_before):
            for item in list(set(pool)-before):
                if item.users==0 or item.use_fake_user:pool.remove(item)
        if 'schemaxisProduction' in self.scene:del self.scene['schemaxisProduction']


def evaluated(obj, *, groups=True):
    graph=bpy.context.evaluated_depsgraph_get();native=obj.evaluated_get(graph)
    result={'matrix':[list(r) for r in native.matrix_world]}
    if obj.type in ('MESH','CURVE','FONT'):
        mesh=native.to_mesh()
        try:
            points=[list(native.matrix_world@v.co) for v in mesh.vertices]
            result.update(vertices=len(points),faces=len(mesh.polygons),bounds=[f(p[i] for p in points) for i in range(3) for f in (min,max)] if points else [0]*6,geometrySha256=hashlib.sha256(json.dumps({'points':points,'faces':[list(f.vertices) for f in mesh.polygons]},sort_keys=True).encode()).hexdigest())
        finally:native.to_mesh_clear()
    if groups and obj.type=='EMPTY' and (obj.children or obj.instance_type=='COLLECTION'):
        result.update(group_observation(obj))
    return result


def group_observation(obj):
    from .production_output_native import _resolved_geometry
    points=[];faces=0;volume=0
    for native,world in _resolved_geometry([obj]):
        mesh=native.to_mesh()
        try:
            if len(points)+len(mesh.vertices)>2_000_000:fail('RESOURCE_BUDGET_EXCEEDED','group observation exceeds two million vertices',obj.name)
            points.extend(list(world@v.co) for v in mesh.vertices);faces+=len(mesh.polygons)
        finally:native.to_mesh_clear()
    if not points:fail('TYPE_MISMATCH','selected scene root has no evaluated geometry',obj.name)
    return {'kind':'asset','points':len(points),'cells':faces,'bounds':[f(p[i] for p in points) for i in range(3) for f in (min,max)],'transform':[list(r) for r in obj.matrix_world],'geometrySha256':hashlib.sha256(json.dumps(points).encode()).hexdigest()}


def material_binding(binding,objects):
    from .production_output_native import _resolved_geometry
    names={tuple(m.name if m else None for m in native.original.data.materials) for native,_ in _resolved_geometry([objects[binding['object']]])}
    if len(names)!=1 or len(next(iter(names)))!=1:fail('VERIFICATION_FAILED','group material binding membership differs',binding['object'])
    return {'object':binding['object'],'material':next(iter(names))[0]}


def observe(spec,objects=None,shader_budget=None,features=None):
    if shader_budget is None:
        from .shader_budget_native import ShaderBudget
        shader_budget=ShaderBudget()
    for graph in all_material_graphs(spec):
        material=features.production.materials.get(graph['id']) if features is not None else bpy.data.materials.get(graph['id'])
        if material is None:fail('VERIFICATION_FAILED','declared shader material is absent',graph['id'])
        shader_budget.material(material)
    for group in spec['nodeGroups']:
        if group['family']=='material':
            tree=bpy.data.node_groups.get(group['id'])
            if tree is None:fail('VERIFICATION_FAILED','declared shader group is absent',group['id'])
            shader_budget.group(tree)
    scene=bpy.context.scene
    if objects is None:
        identities=set(json.loads(scene['schemaxisNodes']))|{o['id'] for o in spec['objects']}|{r['id'] for r in spec['rigs']}|{a['id'] for a in spec['assets']}
        objects={o.name:o for o in scene.objects if o.name in identities}
    from .geometry_resource_native import resolve as resolve_resources,observe_bindings
    resource_objects,resource_collections,resource_records=resolve_resources(spec,objects,{c['id']:bpy.data.collections[c['id']] for c in spec['collections']})
    records=[]
    for authored in spec['objects']:
        obj=objects[authored['id']];kind=authored['kind'];data=obj.data
        expected_type={'empty':'EMPTY','text':'FONT','curve':'CURVE','spline':'CURVE','mesh':'MESH','light':'LIGHT','camera':'CAMERA','collectionInstance':'EMPTY'}.get(kind)
        if expected_type and obj.type!=expected_type:fail('VERIFICATION_FAILED','production object type differs',obj.name)
        actual={'id':obj.name,'kind':kind,'location':list(obj.location),'rotation':list(obj.rotation_euler),'scale':list(obj.scale),'hidden':obj.hide_render,'collection':authored['collection'] if authored['collection'] in [c.name for c in obj.users_collection] else '', 'material':data.materials[0].name if data and hasattr(data,'materials') and data.materials and authored['material'] else ''}
        if 'displayColour' in authored:
            display=authored['displayColour']
            if display['kind']=='colour':
                if obj.color[3]!=1:fail('VERIFICATION_FAILED','display colour alpha changed',obj.name)
                actual['displayColour']={'kind':'colour','value':list(obj.color)[:3]}
            else:
                expected=objects[authored['source']].color if kind=='instance' else (1,1,1,1)
                if not matching(list(obj.color),list(expected)):fail('VERIFICATION_FAILED','inherited display colour changed',obj.name)
                actual['displayColour']={'kind':'inherit'}
        if kind=='light':
            from .render_policy_native import verify_light_tree
            verify_light_tree(data)
        if kind=='empty':actual['displaySize']=obj.empty_display_size
        elif kind=='text':actual.update(body=data.body,size=data.size,extrude=data.extrude,align=data.align_x)
        elif kind=='curve':actual.update(points=[list(p.co)[:3] for p in data.splines[0].points],closed=data.splines[0].use_cyclic_u,bevel=data.bevel_depth,resolution=data.bevel_resolution)
        elif kind=='spline':
            from .spline_native import observe as observe_spline
            from .material_assignments_native import expected_spline_indices
            actual.update(observe_spline(authored,obj,objects,resource_objects,expected_spline_indices(spec,objects,obj)))
        elif kind=='mesh':
            actual.update(vertices=[list(v.co) for v in data.vertices],faces=[list(p.vertices) for p in data.polygons],smooth=all(p.use_smooth for p in data.polygons),uv=[[list(data.uv_layers['UVMap'].data[i].uv) for i in p.loop_indices] for p in data.polygons] if authored.get('uv') and 'UVMap' in data.uv_layers else [])
        elif kind=='light':actual.update(type=data.type,energy=data.energy,colour=list(data.color),size=data.size if data.type=='AREA' else data.shadow_soft_size if data.type in ('POINT','SPOT') else authored['size'],angle=data.spot_size if data.type=='SPOT' else data.angle if data.type=='SUN' else authored['angle'])
        elif kind=='camera':actual.update(projection='perspective' if data.type=='PERSP' else 'orthographic',lens=data.lens,orthographicSize=data.ortho_scale,clipStart=data.clip_start,clipEnd=data.clip_end,focusDistance=data.dof.focus_distance,aperture=data.dof.aperture_fstop,depthOfField=data.dof.use_dof)
        elif kind=='instance':actual.update(source=authored['source'],linked=data==objects[authored['source']].data)
        elif kind=='collectionInstance':actual.update(source=obj.instance_collection.name if obj.instance_type=='COLLECTION' else '')
        records.append(actual)
    group_specs={g['id']:g for g in spec['nodeGroups']}
    graphs={field:[observe_graph(g,family,group_specs,objects=resource_objects,collections=resource_collections,features=features) for g in (all_material_graphs(spec) if field=='materialGraphs' else spec[field])] for field,family in [('materialGraphs','material'),('geometryGraphs','geometry')]}
    if 'compositor' in spec:
        if scene.compositing_node_group is None or scene.compositing_node_group.name!=spec['compositor']['id']:fail('VERIFICATION_FAILED','compositor ownership differs')
        graphs['compositor']=observe_graph(spec['compositor'],'compositor',group_specs,objects=resource_objects,collections=resource_collections,features=features)
    tracks=[]
    for track in spec['tracks']:
        owner=objects[track['object']];owner=owner.data if CHANNELS[track['channel']][0].startswith('data.') else owner
        curves=[c for c in fcurves(owner) if c.data_path==_path(track)];keys=[]
        width=3 if track['channel'] in ('location','rotation','scale') else 1
        if len(curves)!=width:fail('VERIFICATION_FAILED','animation channel component count differs',track['object'])
        for i in range(len(track['keys'])):
            points=[next(c for c in curves if c.array_index==component).keyframe_points[i] for component in range(width)]
            if len({p.co.x for p in points})!=1 or len({p.interpolation for p in points})!=1:fail('VERIFICATION_FAILED','animation components disagree')
            values=[p.co.y for p in points];value=values if width==3 else bool(values[0]) if track['channel']=='visibility' else values[0]
            keys.append({'frame':int(points[0].co.x),'value':value})
        if any(len(c.keyframe_points)!=len(keys) for c in curves):fail('VERIFICATION_FAILED','unexpected animation keyframe')
        tracks.append({'object':track['object'],'bone':track['bone'],'channel':track['channel'],'interpolation':curves[0].keyframe_points[0].interpolation,'keys':keys})
    rigs=[]
    for rig in spec['rigs']:
        obj=objects[rig['id']];rigs.append({'id':obj.name,'bones':[{'id':b.name,'head':list(b.head_local),'tail':list(b.tail_local),'parent':b.parent.name if b.parent else '', 'connected':b.use_connect,'deform':b.use_deform} for b in obj.data.bones]})
    constraints=[]
    for c in spec['constraints']:
        obj=objects[c['object']];owner=obj.pose.bones[c['bone']] if c['bone'] else obj;native=owner.constraints[c['id']]
        if native.type!=CONSTRAINTS[c['kind']][0]:fail('VERIFICATION_FAILED','constraint type differs',c['id'])
        actual={k:c[k] for k in ('object','bone','kind')};actual.update(id=native.name,target=native.target.name if hasattr(native,'target') and native.target else '',targetBone=native.subtarget if hasattr(native,'subtarget') else '',influence=native.influence)
        for semantic,(prop,_) in CONSTRAINTS[c['kind']][1].items():
            if prop=='use_xyz':actual[semantic]=[getattr(native,'use_'+a) for a in 'xyz']
            elif prop in ('minimum','maximum'):
                if native.owner_space!='LOCAL' or not all(getattr(native,('use_limit_' if c['kind']=='limitRotation' else ('use_min_' if prop=='minimum' else 'use_max_'))+a) for a in 'xyz'):fail('VERIFICATION_FAILED','constraint extent mode differs')
                actual[semantic]=[getattr(native,('min_' if prop=='minimum' else 'max_')+a) for a in 'xyz']
            else:actual[semantic]=getattr(native,prop)
        constraints.append(actual)
    bodies=[]
    for b in spec['rigidBodies']:
        n=objects[b['object']].rigid_body
        if n is None:fail('VERIFICATION_FAILED','rigid body absent',b['object'])
        bodies.append({'object':b['object'],'type':n.type.lower(),'mass':n.mass,'friction':n.friction,'restitution':n.restitution,'shape':n.collision_shape,'kinematic':n.kinematic})
    cloth=[]
    for c in spec['cloth']:
        obj=objects[c['object']];mod=obj.modifiers['schemaxis-cloth'];n=mod.settings
        actual={'object':obj.name,**{semantic:getattr(n,prop) for semantic,prop in [('quality','quality'),('mass','mass'),('tension','tension_stiffness'),('compression','compression_stiffness'),('shear','shear_stiffness'),('bending','bending_stiffness')]},'collision':mod.collision_settings.use_collision,'selfCollision':mod.collision_settings.use_self_collision,'pinVertices':[]}
        if n.vertex_group_mass:
            group=obj.vertex_groups[n.vertex_group_mass]
            for v in obj.data.vertices:
                if any(g.group==group.index and g.weight==1 for g in v.groups):actual['pinVertices'].append(v.index)
        cloth.append(actual)
    skin=[]
    for s in spec['skin']:
        obj=objects[s['object']];mod=obj.modifiers['schemaxis-skin']
        if mod.type!='ARMATURE' or not mod.use_vertex_groups or mod.object.name!=s['rig']:fail('VERIFICATION_FAILED','skin rig binding differs',obj.name)
        weights=[]
        for w in s['weights']:
            group=obj.vertex_groups[w['bone']];indices=[];values=[]
            for v in obj.data.vertices:
                for g in v.groups:
                    if g.group==group.index:indices.append(v.index);values.append(g.weight)
            if values and max(values)-min(values)>1e-7:fail('VERIFICATION_FAILED','skin weight values differ')
            weights.append({'bone':group.name,'vertices':indices,'weight':values[0] if values else 0})
        skin.append({'object':obj.name,'rig':mod.object.name,'weights':weights})
    images=[];image_pixels=0
    from .image_assets_native import observe as observe_image,admit as admit_image
    for i in spec['images']:
        native=features.production.images.get(i['id']) if features is not None else bpy.data.images.get(i['id'])
        if native is None:fail('VERIFICATION_FAILED','declared captured image is absent',i['id'])
        image_pixels=admit_image(native,image_pixels)
        images.append({**observe_image(native),'id':i['id']} if features is not None else observe_image(native))
    # Independent frame evaluation; native animation and simulations are evaluated,
    # rather than reporting only authored keyframe/property values.
    from .production_motion import frames as motion_frames
    from .production_motion_native import observe as observe_motion, sample as sample_motion
    motion=observe_motion(spec,objects)
    current=scene.frame_current;samples=[]
    frames=sorted(motion_frames(spec)|{k['frame'] for t in spec['tracks'] for k in t['keys']}|{(a['frame']+b['frame'])//2 for t in spec['tracks'] for a,b in zip(t['keys'],t['keys'][1:])}|set(spec['simulationFrames'])|{spec['currentFrame']})
    if spec['simulationFrames']:
        frames_set=set(frames);frames=range(spec['frameStart'],max(frames)+1)
    else:frames_set=set(frames)
    for f in frames:
        scene.frame_set(f);bpy.context.view_layer.update()
        if f not in frames_set:continue
        from .surface_native import validate_uvs
        validate_uvs(spec)
        channels=[]
        for t in spec['tracks']:
            target,path=_channel(objects[t['object']],t);value=getattr(target,path);channels.append(list(value) if hasattr(value,'__len__') and not isinstance(value,str) else value)
        samples.append({'frame':f,'channels':channels,'motionChannels':sample_motion(spec,objects),'objects':{n:evaluated(o) for n,o in sorted(objects.items())}})
    scene.frame_set(current);bpy.context.view_layer.update()
    from .production_intent_native import observe_intents
    intents=observe_intents(spec['intents'],objects)
    from .production_asset_native import observe_asset
    assets=[observe_asset(a,objects,shader_budget=shader_budget,features=features) for a in spec['assets']]
    from .mesh_data_native import observe as observe_mesh_data
    from .material_assignments_native import observe as observe_material_assignments
    from .mesh_edits_native import observe as observe_mesh_edits
    return {'materialAssignments':observe_material_assignments(spec,objects),'meshEdits':observe_mesh_edits(spec,objects),'geometryResources':resource_records,'meshData':observe_mesh_data(spec['meshData'],objects),'nodeGroups':[observe_graph(g,g['family'],group_specs,g,resource_objects,resource_collections,features=features) for g in spec['nodeGroups']],'motion':motion,'assets':assets,'intents':intents,'objects':records,'collections':[{'id':c['id'],'parent':next((p.name for p in bpy.data.collections if bpy.data.collections[c['id']].name in p.children),'')} for c in spec['collections']], 'parents':{h['object']:objects[h['object']].parent.name if objects[h['object']].parent else '' for h in spec['hierarchy']},'materialBindings':[material_binding(b,objects) for b in spec['materialBindings']], 'geometryBindings':observe_bindings(spec,objects), 'tracks':tracks,'rigs':rigs,'skin':skin,'constraints':constraints,'rigidBodies':bodies,'cloth':cloth,'collisionObjects':[n for n in spec['collisionObjects'] if any(m.type=='COLLISION' for m in objects[n].modifiers)],'images':images,'samples':samples,'timeline':{'frameStart':scene.frame_start,'frameEnd':scene.frame_end,'fps':scene.render.fps,'currentFrame':scene.frame_current,'gravity':list(scene.gravity),'scaleLength':scene.unit_settings.scale_length},**graphs,**({'renderFeatures':features.observation()} if features is not None else {})}
