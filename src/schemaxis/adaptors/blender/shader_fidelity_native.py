"""Source-derived behaviour of reviewed shader classes, without authoring RNA.

The descriptor readback is a useful semantic view, but does not own unexposed
native socket defaults or material settings. These signatures are reconstructed
from trusted inputs before any submitted native project is opened.
"""
import json
import bpy
from schemaxis.errors import fail
from .asset_fidelity import matching
from .node_catalogue import MATERIAL
from .production_asset_snapshot import Snapshot, MAX_BYTES

SHADER_NODES = {desc['native'] for desc in MATERIAL.values()} | {
    'ShaderNodeGroup', 'NodeGroupInput', 'NodeGroupOutput', 'NodeReroute', 'NodeFrame'}
MATERIAL_UI = {'paint_active_slot', 'paint_clone_slot', 'preview_render_type', 'use_preview_world'}


class ShaderSnapshot(Snapshot):
    def __init__(self, images, shader_budget=None,features=None):
        if shader_budget is not None:self._shader_budget=shader_budget
        self.images = {image.name for image in features.production.images.values()} if features is not None else set(images)
        self.features=features
        if features is not None:self.node_types=Snapshot.node_types|{'ShaderNodeOutputAOV'}
        self.records = {}; self.embedded_owners = {}
        self.ids = set(); self.objects = set(); self.allowed = set()
        self.active = set(); self.items = 0; self.bytes = 0

    def primitive(self, native, *, exclude=()):
        if isinstance(native, bpy.types.Material):
            exclude = set(exclude) | MATERIAL_UI
        return super().primitive(native, exclude=exclude)

    def tree(self, tree):
        classes=SHADER_NODES|({'ShaderNodeOutputAOV'} if self.features is not None else set())
        if tree.bl_idname!='ShaderNodeTree' or any(n.bl_idname not in classes for n in tree.nodes):
            self.reject('shader signature needs reviewed shader classes', tree.name)
        return super().tree(tree)

    def dependency(self, owner):
        if owner.library is not None:
            self.reject('shader dependency must be local', owner.name)
        if isinstance(owner, bpy.types.Image):
            # Captured resource bytes/interpretation/dirty state have their own
            # production-image verifier, including the supported pack:false path.
            # Here bind the actual node pointer to that declared resource ID.
            if owner.name not in self.images or bpy.data.images.get(owner.name)!=owner:
                self.reject('shader image is not a declared captured resource', owner.name)
            self.ids.add(owner); self.budget()
            identity = 'Image:'+owner.name
            self.records[identity] = {'name':owner.name, 'type':'Image', 'capturedResource':True}
            return identity
        if not isinstance(owner, (bpy.types.Material, bpy.types.NodeTree)):
            self.reject('authored shader dependency requires a reviewed resource mapping', owner.name)
        if owner.animation_data:
            self.reject('authored shader animation needs a typed channel contract', owner.name)
        return super().dependency(owner)


def observe(material_names, group_names, images, shader_budget=None,features=None):
    snapshot = ShaderSnapshot(images,shader_budget=shader_budget,features=features)
    roots = []
    for index,(pool, names) in enumerate(((bpy.data.materials, material_names), (bpy.data.node_groups, group_names))):
        for name in sorted(names):
            owner = features.production.materials.get(name) if features is not None and index==0 else pool.get(name)
            if owner is None:
                fail('VERIFICATION_FAILED', 'declared shader owner is absent', name)
            roots.append(snapshot.dependency(owner))
    result = {'version':'schemaxis.blender.shader-fidelity/1', 'roots':roots,
              'dependencies':dict(sorted(snapshot.records.items()))}
    if len(json.dumps(result, allow_nan=False).encode())>MAX_BYTES:
        snapshot.reject('serialized shader fidelity exceeds 64 MiB', 'shader')
    return result


def verify(actual, expected):
    if not matching(actual, expected):
        fail('VERIFICATION_FAILED', 'shader state differs from trusted authored-source reconstruction',
             recovery='Preserve this packet and its original inputs. For a deliberate edit or changed constructor/runtime, rerun trusted authored intent into a NEW output; explicitly adopt retained trusted original inputs when needed. Do not resnapshot or relabel this submitted consumer as its source.')
