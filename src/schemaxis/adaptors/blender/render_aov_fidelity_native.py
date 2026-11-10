"""Fresh full AOV Material/World signatures, not stored proof authorization.

Public verification constructs expected bindings from trusted intent and
original resources BEFORE submitted open.
The existing asset/shader readers keep their ordinary admission unchanged.
"""
import json

import bpy

from schemaxis.errors import fail
from .asset_fidelity import matching
from .production_asset_snapshot import Snapshot, NODE_TYPES, MAX_BYTES
from .shader_fidelity_native import ShaderSnapshot, SHADER_NODES


WORLD_NODES = {'ShaderNodeBackground', 'ShaderNodeOutputWorld', 'ShaderNodeTexEnvironment'}
AOV_NODES = {'ShaderNodeOutputAOV'}
# Existing importer-only constructors remain closed native classes, not authored
# property paths. AOV authoring and World resource construction have separate
# typed compilers and cannot select arbitrary members of this set.
SHADER_CLASSES = SHADER_NODES | WORLD_NODES | AOV_NODES | {
    'ShaderNodeLightPath', 'ShaderNodeTangent', 'ShaderNodeVolumeAbsorption',
    'ShaderNodeSeparateColor', 'ShaderNodeCombineColor', 'ShaderNodeMix',
    'ShaderNodeVertexColor', 'ShaderNodeUVMap', 'ShaderNodeAttribute'}


class AovSnapshot(Snapshot):
    node_types = NODE_TYPES | WORLD_NODES | AOV_NODES

    def __init__(self, images, objects=(), shader_budget=None):
        if shader_budget is not None:self._shader_budget = shader_budget
        if images and not isinstance(images, dict):
            fail('TYPE_MISMATCH', 'AOV declared images require trusted logical-ID to native-handle bindings')
        self.declared_image_handles = set(images.values()) if images else set()
        self.images = {image.name for image in self.declared_image_handles}
        self.objects = set(objects);self.allowed = set(self.objects)
        self.records = {};self.embedded_owners = {};self.ids = set()
        self.active = set();self.items = 0;self.bytes = 0
        self.world_trees = set()

    def tree(self, tree):
        if tree.bl_idname == 'ShaderNodeTree':
            if any(n.bl_idname not in SHADER_CLASSES for n in tree.nodes):
                self.reject('AOV fidelity requires reviewed shader classes', tree.name)
        elif tree.bl_idname != 'GeometryNodeTree':
            self.reject('AOV shader dependencies require shader or geometry trees', tree.name)
        result = Snapshot.tree(self, tree)
        if tree in self.world_trees:
            # World editor image selection is not a material texture-preview
            # input. World graph outputs/defaults/images remain fully bound.
            result.pop('activeImage', None)
        return result

    def dependency(self, owner):
        if owner.library is not None:
            self.reject('AOV dependencies require local original resources', owner.name)
        if isinstance(owner, bpy.types.Image) and owner in self.declared_image_handles:
            # Declared images already have captured-byte/interpretation checks,
            # including the existing explicit pack:false resource policy.
            return ShaderSnapshot.dependency(self, owner)
        if isinstance(owner, bpy.types.Action) and owner.is_action_legacy:
            self.reject('AOV animation needs reviewed layered action channels', owner.name)
        if not isinstance(owner, bpy.types.World):
            return Snapshot.dependency(self, owner)
        if owner.override_library is not None:
            self.reject('World library overrides require a typed override contract', owner.name)
        identity = 'World:' + owner.name
        if identity in self.records or identity in self.active:
            return identity
        self.ids.add(owner);self.budget();self.active.add(identity)
        try:
            tree = owner.node_tree
            if tree is not None:
                if tree.bl_idname != 'ShaderNodeTree' or not tree.is_embedded_data:
                    self.reject('World requires its reviewed embedded shader tree', owner.name)
                self.embedded_owners[tree] = '@embedded:' + json.dumps(
                    ['World', owner.name, 'node_tree'], separators=(',', ':'))
                self.world_trees.add(tree)
            # The budget keys actual native owners, so a Material and a World
            # sharing a display name remain distinct roots in the aggregate.
            self.shader_budget().material(owner)
            record = {'name': owner.name, 'type': 'World',
                      'settings': self.primitive(owner), 'animation': self.animation(owner),
                      'customProperties': self.custom(owner),
                      'tree': self.dependency(tree) if tree is not None else None}
            for key, kind in (('cycles', 'CyclesWorldSettings'),
                              ('cycles_visibility', 'CyclesVisibilitySettings'),
                              ('mist_settings', 'WorldMistSettings'),
                              ('light_settings', 'WorldLighting')):
                native = getattr(owner, key, None)
                if native is None or native.bl_rna.identifier != kind:
                    self.reject('World settings require their reviewed native class', key)
                record[key] = {'settings': self.primitive(native), 'references': self.pointers(native)}
            metadata = owner.asset_data
            record['assetMetadata'] = None if metadata is None else {
                'settings': self.primitive(metadata), 'tags': [self.primitive(t) for t in metadata.tags]}
            self.records[identity] = record
        finally:
            self.active.discard(identity)
        return identity


def observe(shading_plan, *, images=(), shader_budget=None):
    effective = shading_plan.observe()
    owners = shading_plan.owners
    reader = AovSnapshot(images, shading_plan.object_ids, shader_budget)
    bindings = {}
    for identity, owner in sorted(owners.items()):
        if not isinstance(owner, (bpy.types.Material, bpy.types.World)):
            fail('TYPE_MISMATCH', 'AOV fidelity owner must be a Material or World', identity)
        bindings[identity] = {'kind': 'World' if isinstance(owner, bpy.types.World) else 'Material',
                              'name': owner.name, 'dependency': reader.dependency(owner)}
    result = {'version': 'schemaxis.blender.aov-fidelity/1', 'bindings': bindings,
              'effectiveShading': effective,
              'dependencies': dict(sorted(reader.records.items()))}
    if len(json.dumps(result, allow_nan=False).encode()) > MAX_BYTES:
        reader.reject('AOV shader fidelity exceeds 64 MiB', 'materialAovs')
    return result


def current(expected, shading_plan, *, images=(), shader_budget=None):
    """Resolve only identities nominated by a fresh trusted reference.

    This function is internal: expected must not come from submitted input or a
    persisted witness. Object/slot membership has its independent fresh binder.
    """
    shading_plan.complete()
    if set(shading_plan.owners) != set(expected['bindings']):
        fail('VERIFICATION_FAILED', 'current effective Material/World owner membership differs from fresh source')
    for identity, binding in expected['bindings'].items():
        pool = {'Material': bpy.data.materials, 'World': bpy.data.worlds}.get(binding['kind'])
        owner = pool.get(binding['name']) if pool is not None else None
        if owner is None or owner != shading_plan.owners[identity]:
            fail('VERIFICATION_FAILED', 'freshly nominated AOV owner is absent', identity)
    return observe(shading_plan, images=images, shader_budget=shader_budget)


def verify(actual, expected):
    if not matching(actual, expected):
        fail('VERIFICATION_FAILED', 'AOV shader state differs from trusted source reconstruction',
             recovery='Preserve the packet and rerun trusted authored/original inputs into a NEW output for deliberate edits; do not resnapshot submitted state as its source.')
