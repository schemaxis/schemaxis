"""Bind mesh/curve material ownership to fresh typed source construction.

Native imports can retain materials without an authored Material DAG node.
Those local trees and packed images use the reviewed captured dependency reader;
authored material images retain their separate declared-resource contract.
"""
import json
import bpy
from schemaxis.errors import fail
from .production_asset_snapshot import Snapshot, MAX_BYTES, MAX_ITEMS
from .shader_fidelity_native import ShaderSnapshot
from .material_inputs_native import MeshInputs,animation_owners


class ImportedShaders(MeshInputs,ShaderSnapshot):
    def budget(self,size=1):
        self.items+=1;self.bytes+=size
        if self.items>MAX_ITEMS or self.bytes>MAX_BYTES:
            fail('RESOURCE_BUDGET_EXCEEDED','object material evidence exceeds 2 million items or 64 MiB',getattr(self,'location','materials'))

    def tree(self, tree):
        if tree.bl_idname not in ('ShaderNodeTree','GeometryNodeTree'):
            self.reject('material inputs need reviewed shader or geometry trees',tree.name)
        return Snapshot.tree(self,tree)

    def dependency(self, owner):
        if isinstance(owner,bpy.types.Image):
            if owner.name in self.images:
                return ShaderSnapshot.dependency(self,owner)
            # The glTF reader accepts embedded source bytes only. The native
            # importer must retain their image payload, not an external path.
            return Snapshot.dependency(self,owner)
        return super().dependency(owner)


def materials(objects):
    for obj in objects:
        if not isinstance(obj,bpy.types.Object) or obj.data is None:continue
        for material in getattr(obj.data,'materials',()):
            if material:yield material.original if material.is_evaluated else material
        for slot in obj.material_slots:
            if slot.material:yield slot.material.original if slot.material.is_evaluated else slot.material


def admit_objects(objects,budget):
    for material in materials(objects):budget.material(material)


def observe(objects,authored_names,shader_budget,images=(),selection_objects=None,features=None):
    authored=set()
    for name in authored_names:
        material=features.production.materials.get(name) if features is not None else bpy.data.materials.get(name)
        if material is None:fail('VERIFICATION_FAILED','declared shader material is absent',name)
        authored.add(material)
    snapshot=ImportedShaders(images,shader_budget=shader_budget,features=features)
    snapshot.input_owners,snapshot.input_actions=animation_owners(list(objects.values()))
    data_peers={}
    for name,obj in objects.items():
        if obj.data is not None and hasattr(obj.data,'materials'):
            data_peers.setdefault(obj.data,[]).append(name)
    def identity(material):
        if material is None:return None
        if material.is_evaluated:material=material.original
        shader_budget.material(material)
        if material in authored:return 'declared:'+material.name
        snapshot.location=material.name
        return snapshot.dependency(material)
    bindings={}
    graph=bpy.context.evaluated_depsgraph_get()
    for name,obj in sorted(objects.items()):
        if obj.data is None or not hasattr(obj.data,'materials'):continue
        record={'dataPeers':sorted(data_peers[obj.data]),
                'dataMaterials':[identity(m) for m in obj.data.materials],
                'slots':[{'link':s.link,'material':identity(s.material)} for s in obj.material_slots]}
        snapshot.location=name
        record['inputs']=snapshot.input_object(obj,graph)
        if obj.type=='MESH':
            record['faceSlots']=snapshot.payload(p.material_index for p in obj.data.polygons)
        if obj.type in ('MESH','CURVE','SURFACE','FONT'):
            evaluated=obj.evaluated_get(graph);mesh=evaluated.to_mesh()
            try:
                record['evaluatedMaterials']=[identity(m) for m in mesh.materials]
                record['evaluatedFaceSlots']=snapshot.payload(p.material_index for p in mesh.polygons)
            finally:evaluated.to_mesh_clear()
        bindings[name]=record
    from .selection_inputs_native import objects as selection_members,observe as observe_selections
    selections,attributes=observe_selections(selection_members() if selection_objects is None else selection_objects,snapshot,graph)
    result={'bindings':bindings,'dependencies':dict(sorted(snapshot.records.items())),
            'selectionInputs':selections,'attributeInputs':attributes}
    if len(json.dumps(result,allow_nan=False).encode())>MAX_BYTES:
        fail('RESOURCE_BUDGET_EXCEEDED','object material source evidence exceeds 64 MiB')
    return result


def current(expected,authored_names,shader_budget,images=(),features=None):
    objects={}
    for name in expected['bindings']:
        obj=bpy.data.objects.get(name)
        if obj is None:fail('VERIFICATION_FAILED','material-bearing source object is absent',name)
        objects[name]=obj
    selection_objects={}
    for name in expected['selectionInputs']:
        obj=bpy.data.objects.get(name)
        if obj is None:fail('VERIFICATION_FAILED','material selection source object is absent',name)
        selection_objects[name]=obj
    return observe(objects,authored_names,shader_budget,images,selection_objects,features=features)
