"""Production-owned staged render-bundle publication kernel.

The kernel never executes destinations inherited from a source project. Every
enabled writer belongs to a typed job and is temporarily directed to its fresh
staging directory. Editable saved writers retain deterministic relative paths.
"""
import hashlib
from pathlib import Path

import bpy

from schemaxis.errors import fail
from . import render_bundle_layout as layout
from .compositor_budget import NativeBudget, validate as validate_budget
from .node_native import port
from .render_writers_native import suppress


class Writers:
    def __init__(self, spec, prefix='0000'):
        self.spec, self.prefix = spec, prefix
        self.definitions = layout.definitions(spec, prefix)
        self.scene = bpy.context.scene
        self.original_tree = self.scene.compositing_node_group
        self.tree = self.original_tree
        self.created, self.files, self.layer_nodes = [], {}, {}
        self.owned_tree = False
        if not self.definitions:
            return
        validate_budget(spec)
        try:
            self._build()
        except BaseException:
            self.close()
            raise

    def node(self, kind, identity):
        # Logical IDs can be longer than native node names. A short stable
        # stem plus a collision discriminator preserves exact native identity.
        stem = 'SXBundle-' + identity[:24] + '-' + hashlib.sha256(identity.encode()).hexdigest()[:12]
        name, index = stem, 0
        while self.tree.nodes.get(name) is not None:
            index += 1
            name = stem + '-' + str(index)
        native = self.tree.nodes.new(kind)
        self.created.append(native)
        native.name = name
        if native.name != name:
            fail('UNSUPPORTED_NATIVE_NAME', 'runtime changed generated compositor node identity', identity)
        return native

    def _build(self):
        if self.tree is None:
            self.tree = bpy.data.node_groups.new('SXRenderBundles', 'CompositorNodeTree')
            self.owned_tree = True
            self.tree.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
            self.scene.compositing_node_group = self.tree
        NativeBudget().observe(self.tree)
        generated = len(self.definitions) + len(self.spec['viewLayers']) + int(self.owned_tree)
        if len(self.tree.nodes) + generated > 2048:
            fail('RESOURCE_BUDGET_EXCEEDED', 'generated compositor exceeds 2048 root nodes')
        for layer in self.spec['viewLayers']:
            if self.scene.view_layers.get(layer['id']) is None:
                fail('UNKNOWN_REFERENCE', 'construct declared native view layers before output writers', layer['id'])
            native = self.node('CompositorNodeRLayers', 'layer-' + layer['id'])
            native.layer = layer['id']
            self.layer_nodes[layer['id']] = native
        if self.owned_tree:
            output = self.node('NodeGroupOutput', 'preview')
            first = next(layer for layer in self.spec['viewLayers'] if layer['enabled'])
            self.tree.links.new(self.layer_nodes[first['id']].outputs['Image'], output.inputs['Image'])
        for definition in self.definitions:
            native = self.node('CompositorNodeOutputFile', definition['bundle'] + ':' + definition['output'])
            native.directory = '//renders/bundles'
            native.file_name = definition['stem'] + '-####'
            encoding = definition['encoding']
            png = definition['format'] == 'png'
            native.format.media_type = 'IMAGE' if png else 'MULTI_LAYER_IMAGE'
            native.format.file_format = 'PNG' if png else 'OPEN_EXR_MULTILAYER'
            native.format.color_mode = encoding['channels'].upper() if png else 'RGBA'
            native.format.color_depth = encoding['depth'] if png else '16' if encoding['precision'] == 'half' else '32'
            native.format.color_management = 'FOLLOW_SCENE'
            native.save_as_render = png
            if png:
                native.format.compression = encoding['compression']
            else:
                native.format.exr_codec = encoding['compression'].upper()
                native.format.use_exr_interleave = True
                native.format.linear_colorspace_settings.name = 'Linear Rec.709'
            for slot in definition['slots']:
                item = native.file_output_items.new(slot['socketType'], slot['id'])
                item.override_node_format = False
                item.save_as_render = png
                if slot['socketType'] == 'VECTOR':
                    item.vector_socket_dimensions = slot['components']
                source = slot['source']
                if source['kind'] == 'layer':
                    owner = self.layer_nodes[source['layer']]
                else:
                    owner = self.tree.nodes.get(source['node'])
                    if owner is None or owner.bl_idname != source['type']:
                        fail('VERIFICATION_FAILED', 'typed compositor source identity differs', source['node'])
                output = port(owner.outputs, source['socket'])
                if not output.enabled:
                    fail('UNSUPPORTED_RENDER_PASS', 'declared render source has no enabled native socket', slot['id'])
                self.tree.links.new(output, native.inputs[slot['id']])
            self.files[(definition['bundle'], definition['output'])] = native
        NativeBudget().observe(self.tree)

    def render(self, bundle_id, frame, directory, objects, prepare_frame=None):
        bundle = next((b for b in self.spec['renderBundles'] if b['id'] == bundle_id), None)
        if bundle is None or frame not in bundle['frames']:
            fail('INVALID_RENDER_BUNDLE', 'render job is not in the declared frame set', bundle_id)
        jobs = [job for job in layout.jobs(self.spec, self.prefix) if job['bundle'] == bundle_id and job['frame'] == frame]
        directory = Path(directory).absolute()
        if directory.exists():
            fail('OUTPUT_EXISTS', 'render job needs a fresh private staging directory', str(directory))
        directory.mkdir()
        scene = self.scene
        original_frame, original_subframe, camera = scene.frame_current, scene.frame_subframe, scene.camera
        directories = []
        try:
            if bundle['camera']:
                target = objects.get(bundle['camera'])
                if target is None or target.type != 'CAMERA':
                    fail('TYPE_MISMATCH', 'bundle camera is not its declared native Camera', bundle['camera'])
                scene.camera = target
            if scene.camera is None:
                fail('INVALID_REFERENCE', 'render bundle requires a camera', bundle_id)
            if prepare_frame is None:
                scene.frame_set(frame)
                bpy.context.view_layer.update()
            else:
                prepare_frame(frame)
            with suppress(scene):
                for job in jobs:
                    native = self.files[(bundle_id, job['output'])]
                    directories.append((native, native.directory))
                    native.directory, native.mute = str(directory), False
                if bpy.ops.render.render(write_still=False) != {'FINISHED'}:
                    fail('PUBLICATION_FAILED', 'render bundle did not finish', bundle_id)
            names = {job['file'] for job in jobs}
            files = list(directory.rglob('*'))
            if any(not path.is_file() or path.is_symlink() for path in files) or {path.name for path in files} != names:
                fail('PUBLICATION_FAILED', 'render bundle file membership differs from its typed plan', bundle_id)
            return [{**job, 'path': str(directory / job['file'])} for job in jobs]
        finally:
            for native, original in reversed(directories):
                native.directory = original
            scene.camera = camera
            scene.frame_set(original_frame, subframe=original_subframe)
            bpy.context.view_layer.update()

    def close(self):
        if self.tree is not None:
            for node in reversed(self.created):
                self.tree.nodes.remove(node)
            self.created.clear()
        if self.owned_tree:
            self.scene.compositing_node_group = self.original_tree
            bpy.data.node_groups.remove(self.tree)
            self.owned_tree = False
