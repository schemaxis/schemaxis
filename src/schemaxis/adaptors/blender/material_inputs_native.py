"""Finite source-owned geometry inputs to material evaluation.

Stored UVs, attributes, split normals and texture space are authored inputs.
Evaluated geometry is observed with all data layers; loop tangents are derived
from these positions, corner normals and UVs by the fixed native runtime. No
submitted readback, cache or caller-supplied hash supplies the reference.
"""
import bpy
from .production_asset_snapshot import Snapshot,MODIFIERS

# Reserved editor selections are bound separately when a material names them.
# Other dot-prefixed/custom attributes remain source-bound; keep this set finite.
SELECTION_ATTRIBUTES = {'.selection', '.select_vert', '.select_edge', '.select_poly',
                        '.uv_select_vert', '.uv_select_edge', '.uv_select_face'}
OBJECT_SETTINGS = ('color', 'pass_index', 'add_rest_position_attribute',
    'show_instancer_for_render', 'visible_camera', 'visible_diffuse',
    'visible_glossy', 'visible_transmission', 'visible_volume_scatter',
    'visible_shadow', 'is_holdout', 'is_shadow_catcher', 'lightgroup',
    'shadow_terminator_normal_offset', 'shadow_terminator_geometry_offset',
    'shadow_terminator_shading_offset', 'show_only_shape_key',
    'active_shape_key_index')


def animation_owners(objects):
    """Only actions actually owned by reconstructed object/mesh/key channels."""
    owners=set(objects)
    for obj in objects:
        if obj.data is not None:
            owners.add(obj.data)
            key=getattr(obj.data,'shape_keys',None)
            if key is not None:owners.add(key)
    actions=set()
    for owner in owners:
        data=getattr(owner,'animation_data',None)
        if data is None:continue
        if data.action is not None:actions.add(data.action)
        for track in data.nla_tracks:
            for strip in track.strips:
                if strip.action is not None:actions.add(strip.action)
    return owners,actions


class MeshInputs:
    """Mixin for the reviewed imported-shader snapshot, not authored RNA."""
    def animation(self,owner):
        data=getattr(owner,'animation_data',None)
        if data is not None and data.drivers:
            self.reject('material geometry input drivers require a typed channel contract',owner.name)
        return super().animation(owner)

    def dependency(self,owner):
        if isinstance(owner,(bpy.types.Object,bpy.types.Collection)):
            if owner.library is not None:
                self.reject('material geometry references must be local',owner.name)
            # Native ID names are unique within these pools. The source-built
            # reference fixes the target; declared objects/assets/collections
            # retain their independent geometry and ownership verifiers.
            return owner.bl_rna.identifier+':'+owner.name
        if isinstance(owner,bpy.types.VectorFont):
            # The shared reader admits only built-in or source-packed fonts.
            return Snapshot.dependency(self,owner)
        if isinstance(owner,(bpy.types.Key,bpy.types.Action)):
            if owner.bl_rna.identifier not in ('Key','Action') or owner not in self.input_owners|self.input_actions:
                self.reject('material geometry animation needs an owned reviewed Key or Action',owner.name)
            if isinstance(owner,bpy.types.Key):
                if owner.user not in self.input_owners:
                    self.reject('shape key owner is outside material geometry inputs',owner.name)
            elif owner.is_action_legacy:
                self.reject('legacy material geometry actions need a reviewed channel mapping',owner.name)
            return Snapshot.dependency(self,owner)
        return super().dependency(owner)

    def mesh(self,data,*,evaluated=False):
        # Texture/ORCO mesh pointers are separate geometry dependencies, not
        # interchangeable with this object's UVs or caller-writable witnesses.
        if data.texture_mesh is not None or data.texco_mesh is not None:
            self.reject('texture/ORCO mesh overrides need an explicit geometry dependency contract',data.name)
        if data.bl_rna.identifier!='Mesh' or data.cycles.bl_rna.identifier!='CyclesMeshSettings':
            self.reject('material mesh input requires the reviewed native Mesh class',data.name)
        # to_mesh can own a temporary copied Key datablock. Its evaluated
        # positions are the result; the original stored Key and Action above
        # own channel authority, never that temporary evaluated dependency.
        result=Snapshot.mesh(self,data,exclude_attributes=SELECTION_ATTRIBUTES,
                             include_shape_keys=not evaluated)
        result.update(textureSpace={'automatic':data.use_auto_texspace,
            'location':list(data.texspace_location),'size':list(data.texspace_size)},
            colourSelectors={'active':data.color_attributes.active_color_name,
                             'renderDefault':data.color_attributes.default_color_name},
            normalDomain=data.normals_domain,hasCustomNormals=data.has_custom_normals,
            cornerNormals=self.payload(list(n.vector) for n in data.corner_normals),
            weights=self.payload([[g.group,g.weight] for g in vertex.groups] for vertex in data.vertices),
            cycles=self.primitive(data.cycles))
        return result

    def input_object(self,obj,graph):
        self.location=obj.name
        if obj.bl_rna.identifier!='Object' or obj.cycles.bl_rna.identifier!='CyclesObjectSettings':
            self.reject('material object input requires the reviewed native Object class',obj.name)
        result={'matrixWorld':[list(row) for row in obj.matrix_world],
                'settings':{key:self.value(getattr(obj,key)) for key in OBJECT_SETTINGS},
                'customProperties':self.custom(obj),
                'animation':self.animation(obj),
                'cycles':self.primitive(obj.cycles),
                'vertexGroups':[self.primitive(group) for group in obj.vertex_groups],
                'modifiers':[]}
        for modifier in obj.modifiers:
            if modifier.type not in MODIFIERS|{'CLOTH','COLLISION'}:
                self.reject('material geometry modifier needs a reviewed mapping',modifier.type)
            # Renderer flags, subdivision render levels and graph socket
            # IDProperties must not be inferred from a viewport mesh alone.
            result['modifiers'].append({'type':modifier.type,
                'settings':self.primitive(modifier,exclude={'show_expanded','show_on_cage','show_in_editmode'}),
                'references':self.pointers(modifier),'interfaceValues':self.custom(modifier)})
        if obj.type=='MESH':
            result['stored']=self.mesh(obj.data)
            result['dataAnimation']=self.animation(obj.data)
        elif obj.type in ('CURVE','FONT','SURFACE'):
            result['stored']=self.curve_data(obj)
        if obj.type in ('MESH','CURVE','SURFACE','FONT'):
            evaluated=obj.evaluated_get(graph)
            mesh=evaluated.to_mesh(preserve_all_data_layers=True,depsgraph=graph)
            try:
                result['evaluated']=self.mesh(mesh,evaluated=True)
                result['evaluatedMatrixWorld']=[list(row) for row in evaluated.matrix_world]
            finally:evaluated.to_mesh_clear()
        return result
