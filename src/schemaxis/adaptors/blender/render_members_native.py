"""Bounded renderer participation and camera/light inputs from fresh intent.

Native reflection only reads these reviewed classes. It cannot author settings.
Object/collection IDs are local identities; their reachable render configuration
and action channels are captured separately rather than trusted by display name.
"""
import json
import bpy
from schemaxis.errors import fail
from .object_materials_native import ImportedShaders
from .material_inputs_native import animation_owners
from .production_asset_snapshot import Snapshot

ID_PRESENTATION={'use_fake_user','use_extra_user','is_runtime_data','tag'}
# World/local matrices and dimensions are derived solver/evaluation caches.
# Their writable setters update the bound TRS/basis channels; parent inverse,
# constraints and owned animation also remain source-bound. Native reload may
# reset a rigid body's cached world matrix before the declared warmup.
DERIVED_OBJECT_VALUES={'matrix_world','matrix_local','dimensions'}
OBJECT_PRESENTATION=ID_PRESENTATION|{'active_material_index','lock_location','lock_rotation',
    'lock_rotation_w','lock_rotations_4d','lock_scale','empty_display_type','empty_display_size',
    'hide_select','hide_surface_pick','show_instancer_for_viewport','visible_raycast',
    'display_type','show_bounds','display_bounds_type','show_name','show_axis','show_texture_space',
    'show_wire','show_all_edges','show_transparent','show_in_front','use_shape_key_edit_mode',
    'use_mesh_mirror_x','use_mesh_mirror_y','use_mesh_mirror_z','active_selection_set'}
CAMERA_PRESENTATION=ID_PRESENTATION|{'passepartout_alpha','display_size','show_limits','show_mist',
    'show_passepartout','show_safe_areas','show_safe_center','show_name','show_sensor',
    'show_background_images','lens_unit','composition_guide_color',
    'show_composition_center','show_composition_center_diagonal','show_composition_thirds',
    'show_composition_golden','show_composition_golden_tria_a','show_composition_golden_tria_b',
    'show_composition_harmony_tri_a','show_composition_harmony_tri_b'}
MAX_MEMBERS=16384


class RenderMembers(ImportedShaders):
    def dependency(self,owner):
        if isinstance(owner,(bpy.types.Object,bpy.types.Collection,bpy.types.Scene,
                             bpy.types.World,bpy.types.Camera,bpy.types.Light,bpy.types.Material,bpy.types.Mesh,
                             bpy.types.Curve,bpy.types.Armature)):
            if owner.library is not None:
                self.reject('renderer dependencies require local identities',owner.name)
            return owner.bl_rna.identifier+':'+owner.name
        return super().dependency(owner)

    def tree(self,tree):
        if tree.bl_idname!='CompositorNodeTree':
            self.reject('renderer compositor needs reviewed compositor classes',tree.name)
        return Snapshot.tree(self,tree)


def observe(features=None):
    scene=bpy.context.scene;reader=RenderMembers([])
    reader.cache_handles=features.cache_handles() if features is not None else set()
    if scene.background_set is not None or scene.animation_data:
        fail('VERIFICATION_FAILED','background scenes and scene animation need a typed render contract')
    from .physics_inputs_native import world_collections,world as physics_world,object_inputs
    objects=set(scene.objects);collections={scene.collection};pending=[scene.collection,*world_collections(scene)]
    # Include instanced/linking collections even if they are not in the scene's
    # ordinary layer tree; these sets can change illumination and visibility.
    processed=set()
    while pending or objects-processed:
        while pending:
            collection=pending.pop()
            if collection not in collections:collections.add(collection)
            if len(collections)+len(objects)>MAX_MEMBERS:
                fail('RESOURCE_BUDGET_EXCEEDED','renderer participation exceeds 16384 object/collection members')
            objects.update(collection.objects)
            for child in collection.children:
                if child not in collections:collections.add(child);pending.append(child)
        for obj in list(objects-processed):
            processed.add(obj)
            if len(collections)+len(objects)>MAX_MEMBERS:
                fail('RESOURCE_BUDGET_EXCEEDED','renderer participation exceeds 16384 object/collection members')
            if obj.parent:objects.add(obj.parent)
            for owner in (obj,obj.data):
                data=getattr(owner,'animation_data',None)
                if data is not None:
                    for curve in data.drivers:
                        for variable in curve.driver.variables:
                            for target in variable.targets:
                                if isinstance(target.id,bpy.types.Object):objects.add(target.id)
            for constraint in obj.constraints:
                for prop in constraint.bl_rna.properties:
                    if prop.type=='POINTER' and not prop.is_readonly:
                        target=getattr(constraint,prop.identifier)
                        if isinstance(target,bpy.types.Object):objects.add(target)
            for collection in (obj.instance_collection,obj.light_linking.receiver_collection,
                               obj.light_linking.blocker_collection):
                if collection is not None and collection not in collections:
                    collections.add(collection);pending.append(collection)
    reader.input_owners,reader.input_actions=animation_owners(list(objects))
    for collection in collections:
        reader.input_owners.add(collection)
        data=getattr(collection,'animation_data',None)
        if data is not None:
            if data.action is not None:reader.input_actions.add(data.action)
            for track in data.nla_tracks:
                for strip in track.strips:
                    if strip.action is not None:reader.input_actions.add(strip.action)
    def settings(value,kind,exclude=()):
        if value is None or value.bl_rna.identifier!=kind:
            fail('VERIFICATION_FAILED','renderer member needs a reviewed native settings class',kind)
        return reader.primitive(value,exclude=exclude)
    def identity(value):return reader.dependency(value) if value is not None else None
    def collection_id(value):return '@scene-root' if value==scene.collection else identity(value)
    result={'sceneObjects':sorted(o.name for o in scene.objects),'camera':identity(scene.camera),
            'activeViewLayer':bpy.context.view_layer.name,'physicsWorld':physics_world(reader,scene,collection_id),
            'objects':{},'collections':{},'viewLayers':{},'compositor':None}
    for obj in sorted(objects,key=lambda o:o.name):
        if obj.bl_rna.identifier!='Object':reader.reject('renderer needs reviewed Object class',obj.name)
        presentation=OBJECT_PRESENTATION
        if scene.render.engine=='BLENDER_WORKBENCH':
            presentation=presentation-{'show_in_front','display_type'}
        record={'type':obj.type,'data':identity(obj.data),
                'settings':reader.primitive(obj,exclude=presentation|DERIVED_OBJECT_VALUES),
                'physicsInputs':object_inputs(reader,obj,collection_id),
                'parent':identity(obj.parent),'instanceCollection':collection_id(obj.instance_collection) if obj.instance_collection else None,
                'animation':reader.animation(obj),'constraints':reader.constraints(obj.constraints),
                'cycles':settings(obj.cycles,'CyclesObjectSettings'),
                'lightLinking':{'settings':settings(obj.light_linking,'ObjectLightLinking'),
                    'receiver':collection_id(obj.light_linking.receiver_collection) if obj.light_linking.receiver_collection else None,
                    'blocker':collection_id(obj.light_linking.blocker_collection) if obj.light_linking.blocker_collection else None}}
        if scene.render.engine=='BLENDER_WORKBENCH':
            record['display']=settings(obj.display,'ObjectDisplay')
        if obj.type=='LIGHT':
            light=obj.data
            if light.bl_rna.identifier not in {'PointLight','SunLight','SpotLight','AreaLight'}:
                reader.reject('renderer light needs a reviewed native class',light.name)
            from .render_policy_native import verify_light_tree
            if light.node_tree is not None:verify_light_tree(light)
            record['light']={'name':light.name,'settings':reader.primitive(light,exclude=ID_PRESENTATION),
                'cycles':settings(light.cycles,'CyclesLightSettings'),'animation':reader.animation(light),
                'hasNodeTree':light.node_tree is not None}
        elif obj.type=='CAMERA':
            data=obj.data
            if data.custom_shader is not None or data.type=='CUSTOM':
                reader.reject('custom camera shaders need a typed camera contract',data.name)
            record['camera']={'name':data.name,'settings':settings(data,'Camera',CAMERA_PRESENTATION),
                'dof':{'settings':settings(data.dof,'CameraDOFSettings'),'focus':identity(data.dof.focus_object)},
                'stereo':settings(data.stereo,'CameraStereoData'),
                'cyclesCustom':settings(data.cycles_custom,'CyclesCustomCameraSettings'),
                'animation':reader.animation(data)}
        result['objects'][obj.name]=record
    for collection in sorted(collections,key=lambda c:collection_id(c)):
        record={'settings':reader.primitive(collection,exclude=ID_PRESENTATION|{'hide_select','color_tag','active_exporter_index'}),
                'objects':sorted(o.name for o in collection.objects),
                'children':sorted(collection_id(c) for c in collection.children),
                'animation':reader.animation(collection),
                'objectLinks':sorted([{'object':o.name,'settings':reader.primitive(link),'lightLinking':reader.primitive(link.light_linking)} for o,link in zip(collection.objects,collection.collection_objects)],key=lambda r:r['object']),
                'childLinks':sorted([{'collection':collection_id(c),'settings':reader.primitive(link),'lightLinking':reader.primitive(link.light_linking)} for c,link in zip(collection.children,collection.collection_children)],key=lambda r:r['collection'])}
        result['collections'][collection_id(collection)]=record
    def layer_tree(layer,depth=0):
        if depth>128:fail('RESOURCE_BUDGET_EXCEEDED','renderer layer tree exceeds 128 levels')
        return {'collection':collection_id(layer.collection),
                'settings':reader.primitive(layer,exclude={'hide_viewport'}),
                'children':sorted([layer_tree(c,depth+1) for c in layer.children],key=lambda r:r['collection'])}
    if len(scene.view_layers)>128:fail('RESOURCE_BUDGET_EXCEEDED','renderer exceeds 128 view layers')
    for layer in scene.view_layers:
        if features is None and (len(layer.aovs) or len(layer.lightgroups) or (scene.render.use_freestyle and layer.use_freestyle)):
            reader.reject('AOV, lightgroup and Freestyle layers need a typed render contract',layer.name)
        result['viewLayers'][layer.name]={'settings':reader.primitive(layer,exclude={'active_aov_index','active_lightgroup_index'}),
            'materialOverride':identity(layer.material_override),'worldOverride':identity(layer.world_override),
            'cycles':settings(layer.cycles,'CyclesRenderLayerSettings'),
            'eevee':settings(layer.eevee,'ViewLayerEEVEE'),'tree':layer_tree(layer.layer_collection)}
    if features is not None:result['renderFeatures']=features.observation()
    tree=scene.compositing_node_group
    if tree is not None:
        from .compositor_budget import NativeBudget
        NativeBudget().observe(tree)
        result['compositor']={'name':tree.name,'tree':reader.tree(tree),'animation':reader.animation(tree)}
    result['dependencies']=dict(sorted(reader.records.items()))
    from .production_asset_snapshot import MAX_BYTES
    if len(json.dumps(result,allow_nan=False).encode())>MAX_BYTES:
        fail('RESOURCE_BUDGET_EXCEEDED','renderer participation evidence exceeds 64 MiB')
    return result
