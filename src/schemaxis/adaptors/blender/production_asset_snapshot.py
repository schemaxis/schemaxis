"""Bounded read-only fidelity evidence for local editable asset dependencies.

RNA inspection here observes native configuration; authored input cannot select
properties, constructors, import paths or code. Only the reviewed object, node,
modifier and constraint classes below enter the snapshot. Geometry and image
payloads are hashed independently of their user-writable custom properties.
"""
import array
import hashlib
import json
import math
import struct
from collections.abc import Mapping

import bpy
from schemaxis.errors import fail
from .node_catalogue import CATALOGUES

MAX_ITEMS = 2_000_000
MAX_BYTES = 64*1024*1024
OBJECT_TYPES = {'EMPTY', 'MESH', 'CURVE', 'FONT', 'SURFACE', 'ARMATURE', 'CAMERA', 'LIGHT'}
MODIFIERS = {'ARMATURE', 'SUBSURF', 'BEVEL', 'MIRROR', 'ARRAY', 'SOLIDIFY', 'DECIMATE',
             'TRIANGULATE', 'WELD', 'SMOOTH', 'LAPLACIANSMOOTH', 'WEIGHTED_NORMAL',
             'NORMAL_EDIT', 'DISPLACE', 'SIMPLE_DEFORM', 'BOOLEAN', 'NODES', 'CURVE',
             'LATTICE', 'CAST', 'WARP', 'SHRINKWRAP', 'EDGE_SPLIT', 'REMESH'}
CONSTRAINTS = {'COPY_LOCATION', 'COPY_ROTATION', 'COPY_SCALE', 'COPY_TRANSFORMS',
               'TRACK_TO', 'DAMPED_TRACK', 'CHILD_OF', 'FOLLOW_PATH', 'IK',
               'LIMIT_LOCATION', 'LIMIT_ROTATION', 'LIMIT_SCALE', 'STRETCH_TO',
               'TRANSFORM', 'LOCKED_TRACK', 'MAINTAIN_VOLUME', 'SHRINKWRAP'}
NODE_TYPES = {d['native'] for c in CATALOGUES.values() for d in c.values()} | {
    'ShaderNodeGroup', 'GeometryNodeGroup', 'CompositorNodeGroup', 'NodeGroupInput', 'NodeGroupOutput',
    'NodeReroute', 'NodeFrame', 'ShaderNodeSeparateColor', 'ShaderNodeCombineColor',
    'ShaderNodeMix', 'ShaderNodeUVMap', 'ShaderNodeVertexColor', 'ShaderNodeAttribute'}
# Fixed-runtime glTF unlit, textured anisotropy and absorption constructors.
# These built-in source dependencies have only the reviewed scalar/socket/link
# fidelity mapping; this does not expose authored reflection or node execution.
NODE_TYPES |= {'ShaderNodeLightPath','ShaderNodeTangent','ShaderNodeVolumeAbsorption'}
# Read-only format mapping does not authorize a FileOutput's filesystem paths.
# Public execution separately owns all generated output destinations and slots.
NODE_TYPES |= {'CompositorNodeOutputFile'}
# Presentation and transient editor state do not affect preserved asset intent.
UI_PROPERTIES = {'name', 'name_full', 'rna_type', 'bl_rna', 'select', 'location', 'location_absolute',
                 'width', 'width_hidden', 'height', 'dimensions', 'color',
                 'use_custom_color', 'show_options', 'show_preview',
                 'hide', 'label', 'parent', 'warning_propagation'}


class Snapshot:
    # A reviewed reader may extend its own closed class set. The ordinary
    # asset reader's admission remains exactly NODE_TYPES.
    node_types = NODE_TYPES

    def __init__(self, root, shader_budget=None,features=None):
        if features is not None:self.node_types=type(self).node_types|{'ShaderNodeOutputAOV'}
        if shader_budget is not None:self._shader_budget=shader_budget
        from .production_asset_collections import asset_members
        self.members = asset_members(root)
        if not self.members or len(self.members)>4096:
            self.reject('asset requires 1–4096 owned descendants', root.name)
        self.objects = {root, *self.members}
        self.allowed = set(self.objects)
        self.records = {}
        self.embedded_owners = {}
        self.ids=set(self.allowed)
        self.active = set()
        self.items = 0
        self.bytes = 0
        for obj in self.objects:
            if obj.data:
                self.allowed.add(obj.data)
                self.allowed.update(m for m in getattr(obj.data, 'materials', ()) if m)
                self.allowed.update(slot.material for slot in obj.material_slots if slot.material)

    def reject(self, message, where):
        fail('UNSUPPORTED_ASSET_DEPENDENCY', message, where)

    def budget(self, size=1):
        self.items += 1
        self.bytes += size
        if self.items>MAX_ITEMS or self.bytes>MAX_BYTES:
            self.reject('asset fidelity evidence exceeds its bounded geometry/dependency budget', 'asset')

    def value(self, value):
        if value is None or isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                self.reject('non-finite native asset configuration', 'asset')
            return value
        if isinstance(value, bpy.types.ID):
            return self.dependency(value)
        if isinstance(value, Mapping) or hasattr(value, 'items'):
            return {str(key):self.value(item) for key,item in value.items()}
        if isinstance(value, (set, frozenset)):
            return sorted(self.value(item) for item in value)
        try:
            return [self.value(item) for item in value]
        except TypeError:
            self.reject('native configuration value requires an explicit fidelity mapping', type(value).__name__)

    def primitive(self, native, *, exclude=()):
        """Read scalar/array settings of an already admitted native class."""
        self.budget()
        result = {}
        for prop in native.bl_rna.properties:
            key = prop.identifier
            if key in exclude or prop.is_readonly or prop.type not in ('BOOLEAN', 'INT', 'FLOAT', 'STRING', 'ENUM'):
                continue
            result[key] = self.value(getattr(native, key))
        return result

    def pointers(self, native):
        result = {}
        for prop in native.bl_rna.properties:
            if prop.type=='POINTER' and not prop.is_readonly:
                value = getattr(native, prop.identifier)
                if isinstance(value, bpy.types.ID):
                    result[prop.identifier] = self.dependency(value)
        return result

    def custom(self, native):
        try:
            names=sorted(native.keys())
        except TypeError:
            # Fixed native structs expose keys() but cannot own IDProperties.
            return {}
        return {key:self.value(native[key]) for key in names}

    def payload(self, rows):
        digest = hashlib.sha256()
        count = 0
        for row in rows:
            encoded = json.dumps(self.value(row), separators=(',', ':'), allow_nan=False).encode()
            self.budget(len(encoded))
            digest.update(struct.pack('<I', len(encoded)))
            digest.update(encoded)
            count += 1
        return {'count': count, 'sha256': digest.hexdigest()}

    def animation(self, owner):
        data = getattr(owner, 'animation_data', None)
        if not data:
            return None
        result = {'settings': self.primitive(data), 'action': self.dependency(data.action) if data.action else None,
                  'slot': data.action_slot.identifier if data.action_slot else None, 'drivers': [], 'nla': []}
        if data.use_tweak_mode:
            self.reject('asset NLA tweak mode must be exited before capture', owner.name)
        for track in data.nla_tracks:
            strips=[]
            for strip in track.strips:
                if strip.type!='CLIP' or strip.use_animated_time or strip.use_animated_time_cyclic:
                    self.reject('NLA asset import admits action clips with ordinary timing only', owner.name)
                if not strip.action or not strip.action_slot or strip.action_slot not in list(strip.action.slots):
                    self.reject('NLA clip needs an owned action and a valid action slot', owner.name)
                if strip.modifiers:
                    self.reject('NLA strip modifiers require reviewed fidelity support', owner.name)
                strips.append({'settings':self.primitive(strip),
                    'action':self.dependency(strip.action),'slot':strip.action_slot.identifier,
                    'curves':[self.curve(curve) for curve in strip.fcurves]})
            result['nla'].append({'settings':self.primitive(track),'strips':strips})
        for curve in data.drivers:
            driver = curve.driver
            if not driver.is_simple_expression:
                self.reject('asset driver scripts are not admitted', owner.name)
            variables = []
            for variable in driver.variables:
                targets = []
                for target in variable.targets:
                    targets.append({'settings': self.primitive(target), 'id': self.dependency(target.id) if target.id else None})
                variables.append({'settings': self.primitive(variable), 'targets': targets})
            result['drivers'].append({'curve': self.curve(curve), 'settings': self.primitive(driver), 'variables': variables})
        return result

    def curve(self, curve):
        for modifier in curve.modifiers:
            if modifier.type not in {'GENERATOR','FNGENERATOR','CYCLES','NOISE','LIMITS','STEPPED'}:
                self.reject('curve modifier requires reviewed fidelity support', modifier.type)
        return {'settings': self.primitive(curve),
                'keys': self.payload(self.primitive(key) for key in curve.keyframe_points),
                'samples': self.payload(list(point.co) for point in curve.sampled_points),
                'modifiers': [{'type':modifier.type,'settings':self.primitive(modifier)} for modifier in curve.modifiers]}

    def constraints(self, constraints):
        result = []
        for constraint in constraints:
            if constraint.type not in CONSTRAINTS:
                self.reject('constraint type needs reviewed asset fidelity support', constraint.type)
            result.append({'type': constraint.type, 'settings': self.primitive(constraint),
                           'references': self.pointers(constraint)})
        return result

    def tree(self, tree):
        if tree.bl_idname=='ShaderNodeTree':self.shader_budget().group(tree)
        if len(tree.nodes)>2048 or len(tree.links)>8192:
            self.reject('asset node graph exceeds its bounds', tree.name)
        nodes = []
        for node in sorted(tree.nodes, key=lambda n: n.name):
            if node.bl_idname not in self.node_types:
                self.reject('node type needs reviewed asset fidelity/dependency support', node.bl_idname)
            sockets = {}
            for side in ('inputs', 'outputs'):
                sockets[side] = [{'id': socket.identifier, 'type': socket.bl_idname,
                                  'enabled': socket.enabled,
                                  'default': self.value(socket.default_value) if hasattr(socket, 'default_value') else None}
                                 for socket in getattr(node, side)]
            presentation = UI_PROPERTIES | ({'active_item_index'} if node.bl_idname == 'CompositorNodeOutputFile' else set())
            record = {'name': node.name, 'type': node.bl_idname, 'settings': self.primitive(node, exclude=presentation),
                      'references': self.pointers(node), 'sockets': sockets}
            for key in ('texture_mapping', 'color_mapping', 'image_user'):
                if hasattr(node, key):
                    record[key] = self.primitive(getattr(node, key))
                    if hasattr(getattr(node, key), 'color_ramp'):
                        ramp=getattr(node, key).color_ramp
                        record[key]['ramp']={'settings':self.primitive(ramp),
                                             'elements':[self.primitive(item) for item in ramp.elements]}
            if hasattr(node, 'color_ramp'):
                record['ramp'] = {'settings': self.primitive(node.color_ramp),
                                  'elements': [self.primitive(item) for item in node.color_ramp.elements]}
            if node.bl_idname == 'CompositorNodeOutputFile':
                from .render_output_snapshot_native import node_snapshot
                record['fileOutput'] = node_snapshot(self, node)
            nodes.append(record)
        interface = [{'settings':self.primitive(item),'references':self.pointers(item)} for item in tree.interface.items_tree]
        links = sorted([[link.from_node.name, link.from_socket.identifier, link.to_node.name,
                         link.to_socket.identifier, link.is_muted] for link in tree.links])
        result = {'type': tree.bl_idname, 'nodes': nodes, 'links': links, 'interface': interface,
                  'animation': self.animation(tree)}
        if tree in self.embedded_owners:
            # An active image selects a material's technical texture preview.
            # Selecting ordinary shader nodes remains presentation-only state.
            active = tree.nodes.active
            result['activeImage'] = active.name if active and active.bl_idname=='ShaderNodeTexImage' else None
        return result

    def dependency(self, owner):
        self.ids.add(owner)
        if owner.library is not None:
            self.reject('linked asset dependency is not local', owner.name)
        if isinstance(owner, bpy.types.Material) and owner.node_tree:
            # Embedded material trees routinely all have the SAME native name.
            # Their owner, not that display name, supplies their identity.
            self.embedded_owners[owner.node_tree] = '@embedded:'+json.dumps(
                [owner.bl_rna.identifier, owner.name, 'node_tree'], separators=(',', ':'))
        if isinstance(owner,bpy.types.Material):self.shader_budget().material(owner)
        if isinstance(owner, bpy.types.NodeTree) and owner.is_embedded_data and owner not in self.embedded_owners:
            self.reject('embedded node tree requires its admitted material owner', owner.name)
        identity = self.embedded_owners.get(owner, owner.bl_rna.identifier+':'+owner.name)
        if identity in self.records or identity in self.active:
            return identity
        self.budget()
        self.active.add(identity)
        record = {'name': owner.name, 'type': owner.bl_rna.identifier}
        if hasattr(owner, 'keys'):
            record['customProperties']=self.custom(owner)
        if isinstance(owner, bpy.types.Object):
            if owner in self.objects:
                record['ownedObject']=True
            else:
                # A local parent, constraint target or node resource may be a
                # dependency without being a visible carrier member. Preserve
                # it as a complete finite object record rather than displaying it.
                self.objects.add(owner);self.allowed.add(owner)
                if owner.data:self.allowed.add(owner.data)
                record['dependencyObject']=self.object(owner)
        elif isinstance(owner,bpy.types.Collection):
            from .production_asset_collections import collection_closure
            collection_closure(owner)
            if owner.is_embedded_data:
                self.reject('embedded scene-master collection references require an explicit scene dependency workflow',owner.name)
            record.update(settings=self.primitive(owner),animation=self.animation(owner),
              objects=[self.dependency(o) for o in sorted(owner.objects,key=lambda o:o.name)],
              children=[self.dependency(c) for c in sorted(owner.children,key=lambda c:c.name)],
              objectLinks=sorted([{'object':o.name,'settings':self.primitive(link),'lightLinking':self.primitive(link.light_linking)} for o,link in zip(owner.objects,owner.collection_objects)],key=lambda r:r['object']),
              childLinks=sorted([{'collection':c.name,'settings':self.primitive(link),'lightLinking':self.primitive(link.light_linking)} for c,link in zip(owner.children,owner.collection_children)],key=lambda r:r['collection']))
        elif isinstance(owner, bpy.types.NodeTree):
            record.update(self.tree(owner))
        elif isinstance(owner, bpy.types.Material):
            record.update(settings=self.primitive(owner), animation=self.animation(owner),
                          tree=self.dependency(owner.node_tree) if owner.node_tree else None)
            # Renderer settings live in explicit non-ID structs and are absent
            # from both Material scalar RNA and ordinary ID custom properties.
            for key,kind in (('cycles','CyclesMaterialSettings'),('lineart','MaterialLineArt'),
                             ('grease_pencil','MaterialGPencilStyle')):
                native=getattr(owner,key)
                if native is not None and native.bl_rna.identifier!=kind:
                    self.reject('material settings require their reviewed native struct',key)
                record[key]=({'settings':self.primitive(native,exclude={'name'}),
                              'references':self.pointers(native)} if native is not None else None)
            if owner.override_library is not None:
                self.reject('material library overrides need a captured override contract',owner.name)
            metadata=owner.asset_data
            record['assetMetadata']=None if metadata is None else {
                'settings':self.primitive(metadata),'tags':[self.primitive(t) for t in metadata.tags]}
            # preview is editor-only. library_weak_reference is append/reuse
            # provenance; all actual local payload pointers are bound above.
        elif isinstance(owner, bpy.types.Image):
            if owner.source not in ('FILE', 'GENERATED') or owner.source=='FILE' and not owner.packed_file:
                self.reject('asset image must be generated or packed', owner.name)
            if len(owner.packed_files)>1:
                self.reject('multiview image dependency requires explicit fidelity support', owner.name)
            # Packed bytes own the dependency. Blender may rebase its unused
            # original pathname when the complete project is saved elsewhere.
            record.update(settings=self.primitive(owner, exclude={'filepath', 'filepath_raw'}), colourSpace=self.primitive(owner.colorspace_settings),
                          size=list(owner.size), alphaMode=owner.alpha_mode)
            if owner.packed_file:
                raw=owner.packed_file.data; self.budget(len(raw))
                record['packedSha256']=hashlib.sha256(raw).hexdigest()
            else:
                if len(owner.pixels)*4>MAX_BYTES:
                    self.reject('generated image exceeds fidelity budget', owner.name)
                pixels=array.array('f', owner.pixels); self.budget(len(pixels)*4)
                record['pixelSha256']=hashlib.sha256(pixels.tobytes()).hexdigest()
        elif isinstance(owner, bpy.types.Action):
            record.update(settings=self.primitive(owner), slots=[self.primitive(slot) for slot in owner.slots], layers=[])
            for layer in owner.layers:
                strips=[]
                for strip in layer.strips:
                    if strip.type!='KEYFRAME':
                        self.reject('action strip type requires reviewed fidelity support', strip.type)
                    strips.append({'settings':self.primitive(strip), 'bags':[
                        {'slot': bag.slot_handle, 'curves':[self.curve(curve) for curve in bag.fcurves]}
                        for bag in strip.channelbags]})
                record['layers'].append({'settings':self.primitive(layer), 'strips':strips})
        elif isinstance(owner, bpy.types.VectorFont):
            if owner.filepath!='<builtin>' and not owner.packed_file:
                self.reject('font dependency must be packed', owner.name)
            if owner.packed_file:
                raw=owner.packed_file.data; self.budget(len(raw))
                record['packedSha256']=hashlib.sha256(raw).hexdigest()
            else:
                record['builtin']=True
        elif isinstance(owner, bpy.types.Key):
            record.update(settings=self.primitive(owner), animation=self.animation(owner), blocks=[])
            for block in owner.key_blocks:
                record['blocks'].append({'name':block.name,'settings':self.primitive(block),
                    'relative':block.relative_key.name if block.relative_key else None,
                    'coordinates':self.payload(list(point.co) for point in block.data)})
        elif owner in self.allowed:
            record['ownedData']=True
        else:
            self.reject('dependency type requires an explicit asset mapping', owner.bl_rna.identifier)
        self.records[identity]=record
        self.active.remove(identity)
        return identity

    def shader_budget(self):
        if not hasattr(self,'_shader_budget'):
            from .shader_budget_native import ShaderBudget
            self._shader_budget=ShaderBudget()
        return self._shader_budget

    def mesh(self, data, *, exclude_attributes=('.selection', '.select_vert', '.select_edge', '.select_poly'), include_shape_keys=True):
        result={'vertices':self.payload(list(v.co) for v in data.vertices),
                'edges':self.payload([*edge.vertices, edge.use_edge_sharp] for edge in data.edges),
                'polygons':self.payload([list(face.vertices), face.material_index, face.use_smooth] for face in data.polygons),
                'uvs':[], 'attributes':[],
                'activeUV':data.uv_layers.active.name if data.uv_layers.active else '',
                'activeColour':data.color_attributes.active_color.name if data.color_attributes.active_color else '',
                'renderColour':data.color_attributes[data.color_attributes.render_color_index].name if 0<=data.color_attributes.render_color_index<len(data.color_attributes) else ''}
        for uv in data.uv_layers:
            result['uvs'].append({'name':uv.name,'activeRender':uv.active_render,
                                  'values':self.payload(list(item.uv) for item in uv.data)})
        for attribute in data.attributes:
            if attribute.name in exclude_attributes:
                continue  # Native selection/edit caches; topology/UVs are explicit above.
            field={'FLOAT':'value','INT':'value','BOOLEAN':'value','FLOAT_VECTOR':'vector',
                   'FLOAT_COLOR':'color','BYTE_COLOR':'color','FLOAT2':'vector',
                   'INT8':'value','INT16':'value','INT16_2D':'value','INT32_2D':'value','QUATERNION':'value'}.get(attribute.data_type)
            if field is None:
                self.reject('mesh attribute type needs reviewed fidelity support', attribute.data_type)
            result['attributes'].append({'name':attribute.name,'type':attribute.data_type,'domain':attribute.domain,
                'values':self.payload(getattr(item, field) for item in attribute.data)})
        if include_shape_keys and data.shape_keys:
            result['shapeKeys']=self.dependency(data.shape_keys)
        return result

    def curve_data(self, obj):
        """Complete reviewed legacy Curve/Font inputs, including render-only data."""
        data=obj.data
        expected={'CURVE':'Curve','FONT':'TextCurve','SURFACE':'SurfaceCurve'}.get(obj.type)
        if expected is None or data.bl_rna.identifier!=expected:
            self.reject('curve inputs need their reviewed native data class',obj.name)
        if data.shape_keys is not None:
            self.reject('curve shape-key dependencies need a reviewed shape contract',obj.name)
        record={'name':data.name,'settings':self.primitive(data),'references':self.pointers(data),
                'animation':self.animation(data),'customProperties':self.custom(data),
                'materials':[self.dependency(m) if m else None for m in data.materials]}
        record['splines']=[{'settings':self.primitive(spline),
            'points':self.payload(self.primitive(point) for point in spline.points),
            'bezier':self.payload(self.primitive(point) for point in spline.bezier_points)} for spline in data.splines]
        if obj.type=='FONT':
            # Character formatting owns material indices, style and
            # kerning; text boxes own layout. Neither collection is a
            # scalar TextCurve setting or a generated spline record.
            record['bodyFormat']=self.payload(
                self.primitive(item, exclude={'select'}) for item in data.body_format)
            record['textBoxes']=self.payload(
                self.primitive(item) for item in data.text_boxes)
        if data.bevel_profile:
            profile=data.bevel_profile
            if any(point.handle_type_1 not in ('AUTO','VECTOR') or point.handle_type_2 not in ('AUTO','VECTOR') for point in profile.points):self.reject('free/aligned profile handle coordinates need a reviewed native fidelity mapping',obj.name)
            record['bevelProfile']={'settings':self.primitive(profile),'points':[self.primitive(point,exclude={'select'}) for point in profile.points]}
        return record

    def object(self, obj):
        if obj.type not in OBJECT_TYPES:
            self.reject('object type needs reviewed asset fidelity support', obj.type)
        record={'name':obj.name,'type':obj.type,'parent':obj.parent.name if obj.parent else None,
                'settings':self.primitive(obj),'parentInverse':[list(row) for row in obj.matrix_parent_inverse],
                'customProperties':self.custom(obj),'references':self.pointers(obj),
                'animation':self.animation(obj),'constraints':self.constraints(obj.constraints),'modifiers':[],
                'materialSlots':[{'link':slot.link,'material':self.dependency(slot.material) if slot.material else None} for slot in obj.material_slots]}
        if obj.rigid_body or obj.rigid_body_constraint:self.reject('rigid-body scene dependencies require a qualified simulation handoff',obj.name)
        if hasattr(obj,'light_linking'):record['lightLinking']={'settings':self.primitive(obj.light_linking),'references':self.pointers(obj.light_linking)}
        for modifier in obj.modifiers:
            if modifier.type not in MODIFIERS:
                self.reject('modifier needs reviewed portable asset fidelity support', modifier.type)
            custom=self.custom(modifier)
            record['modifiers'].append({'type':modifier.type,'settings':self.primitive(modifier),
                                       'references':self.pointers(modifier),'interfaceValues':custom})
        if obj.data:
            data=obj.data
            if obj.type in ('CURVE','FONT','SURFACE'):
                record['data']=self.curve_data(obj)
            else:
                record['data']={'name':data.name,'settings':self.primitive(data),'references':self.pointers(data),'animation':self.animation(data),
                                'customProperties':self.custom(data),
                                'materials':[self.dependency(m) if m else None for m in getattr(data,'materials',())]}
            if obj.type=='MESH':
                record['data'].update(self.mesh(data))
                record['weights']=self.payload([[g.group,g.weight] for g in vertex.groups] for vertex in data.vertices)
                record['vertexGroups']=[self.primitive(group) for group in obj.vertex_groups]
            elif obj.type=='ARMATURE':
                record['data']['bones']=[{'name':bone.name,'settings':self.primitive(bone),
                    'parent':bone.parent.name if bone.parent else None,'restMatrix':[list(row) for row in bone.matrix_local],
                    'bendHandles':[bone.bbone_custom_handle_start.name if bone.bbone_custom_handle_start else None,
                                   bone.bbone_custom_handle_end.name if bone.bbone_custom_handle_end else None],
                    'head':list(bone.head_local),'tail':list(bone.tail_local)} for bone in data.bones]
                record['pose']=[{'name':bone.name,'settings':self.primitive(bone),
                                  'customProperties':self.custom(bone),'references':self.pointers(bone),
                                  'constraints':self.constraints(bone.constraints)} for bone in obj.pose.bones]
            elif obj.type=='CAMERA':
                record['data']['dof']={'settings':self.primitive(data.dof),'references':self.pointers(data.dof)}
        return record


def snapshot_asset_members(root, shader_budget=None,features=None):
    from .asset_fidelity import VERSION
    snapshot=Snapshot(root,shader_budget=shader_budget,features=features)
    objects=[snapshot.object(obj) for obj in snapshot.members]
    carrier=snapshot.dependency(root.instance_collection) if root.instance_type=='COLLECTION' else None
    result={'version':VERSION,'objects':objects,
            'dependencies':dict(sorted(snapshot.records.items())),'carrier':carrier}
    if len(json.dumps(result,allow_nan=False).encode())>MAX_BYTES:
        snapshot.reject('serialized asset fidelity evidence exceeds 64 MiB', root.name)
    return result
