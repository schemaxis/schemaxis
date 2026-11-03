# Copyright (C) 2026 David L F Gaden
"""Trusted Blender main-thread worker. Host import does not import bpy."""
import hashlib
import json
from pathlib import Path

from schemaxis.live_runtime import GraphWorker, MAX_FACES, MAX_VERTICES
from schemaxis.live_transport import fault, serve


class Worker(GraphWorker):

    provider = 'blender'

    def backend(self):
        from .native import Backend
        return Backend()

    def reset_native(self):
        import bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def present(self, prepared):
        import bpy
        visible = prepared[3]
        for identity, obj in self.active.handles.items():
            if isinstance(obj, bpy.types.Object):
                obj.hide_render = identity not in visible

    def object_ids(self):
        return [{'id': identity, 'label': obj.name, 'nativeId': str(obj.as_pointer())}
                for identity, obj in self.active.handles.items()]

    def geometry(self):
        import bpy
        graph = bpy.context.evaluated_depsgraph_get()
        objects, face_count, vertex_count = [], 0, 0
        for identity in self.prepared[3]:
            obj = self.active.handles[identity]
            if obj.type != 'MESH':
                fault('UNSUPPORTED_GEOMETRY', 'Live geometry requires evaluated meshes', node=identity)
            evaluated = obj.evaluated_get(graph)
            mesh = evaluated.to_mesh()
            try:
                face_count += len(mesh.polygons)
                vertex_count += sum(len(p.vertices) for p in mesh.polygons)
                if face_count > MAX_FACES or vertex_count > MAX_VERTICES:
                    fault('LIVE_LIMIT', 'Evaluated mesh exceeds live tessellation budget')
                mesh.calc_loop_triangles()
                faces, maps = [], []
                for polygon in mesh.polygons:
                    indices = list(polygon.vertices)
                    maps.append({native: local for local, native in enumerate(indices)})
                    faces.append({'id': 'Face' + str(polygon.index),
                                  'vertices': [list(evaluated.matrix_world @ mesh.vertices[i].co) for i in indices],
                                  'triangles': []})
                for triangle in mesh.loop_triangles:
                    index = triangle.polygon_index
                    faces[index]['triangles'].append([maps[index][i] for i in triangle.vertices])
                objects.append({'id': identity, 'label': obj.name, 'faces': faces})
            finally:
                evaluated.to_mesh_clear()
        return objects

    def image(self, path):
        import bpy
        from .native import frame
        from schemaxis.camera import camera_values
        observations = self.active.observations
        boxes = [observations[n]['bounds'] for n in self.prepared[3] if observations[n]['points']]
        if not boxes:
            fault('EMPTY_SCENE', 'Cannot frame an empty live scene')
        bounds = [min(b[i] for b in boxes) if i % 2 == 0 else max(b[i] for b in boxes) for i in range(6)]
        scene = bpy.context.scene
        camera = bpy.data.objects.new('__live_camera', bpy.data.cameras.new('__live_camera'))
        scene.collection.objects.link(camera)
        scene.camera = camera
        try:
            # CPU Cycles preview is independent of batch render settings and never
            # selects a GPU. A white world illuminates the bounded preview.
            scene.render.engine = 'CYCLES'
            scene.cycles.device = 'CPU'
            scene.cycles.samples = 8
            scene.render.threads_mode = 'FIXED'
            scene.render.threads = 4
            scene.world = scene.world or bpy.data.worlds.new('__live_world')
            scene.world.use_nodes = True
            scene.world.node_tree.nodes['Background'].inputs['Color'].default_value = (1, 1, 1, 1)
            scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.8
            frame(camera, camera_values({'direction': [1, -1, 1]}, 'live.camera'), bounds, [640, 480])
            scene.render.image_settings.file_format = 'PNG'
            scene.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
            image = bpy.data.images.load(str(path), check_existing=False)
            try:
                if list(image.size) != [640, 480] or len(set(list(image.pixels)[::4])) < 2:
                    fault('VERIFICATION_FAILED', 'Native image is empty or has incorrect dimensions')
            finally:
                bpy.data.images.remove(image)
            return {'file': str(path), 'verified': True, 'dimensions': [640, 480],
                    'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                    'scope': 'live geometry preview with fixed camera and CPU lighting'}
        finally:
            scene.camera = None
            data = camera.data
            bpy.data.objects.remove(camera, do_unlink=True)
            bpy.data.cameras.remove(data)

    def save(self, path):
        import bpy
        metadata = self.save_metadata()
        metadata['runtime'] = bpy.app.version_string
        dependencies = [{'kind': 'image', 'file': bpy.path.abspath(image.filepath), 'copied': False}
                        for image in bpy.data.images if image.source == 'FILE' and image.filepath and not image.packed_file]
        bpy.context.scene['schemaxisLiveReceipt'] = json.dumps(metadata, allow_nan=False)
        expected_objects = {obj.name for obj in self.active.handles.values() if isinstance(obj, bpy.types.Object)}
        expected_materials = {obj.name for obj in self.active.handles.values() if isinstance(obj, bpy.types.Material)}
        result = bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True)
        if result != {'FINISHED'}:
            fault('SAVE_FAILED', 'Blender did not finish saving the native scene')
        # Native library parsing validates the saved container without replacing
        # the live scene or invalidating its retained handles. No data is appended.
        with bpy.data.libraries.load(str(path), link=False) as (source, destination):
            if not expected_objects.issubset(source.objects) or not expected_materials.issubset(source.materials):
                fault('VERIFICATION_FAILED', 'Saved Blender library is missing declared objects or materials')
        return self.save_receipt(path, {'kind': 'scene', 'format': 'blend', 'verified': True,
            'verificationScope': 'native Blender library parse and declared object/material membership; geometry replay is not independently verified',
            'externalDependencies': dependencies, 'datasetsCopied': False}, metadata)


def start(directory, parent_pid=None, parent_start=None):
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)
    serve(directory, Worker(), parent_pid=parent_pid, parent_start=parent_start)
