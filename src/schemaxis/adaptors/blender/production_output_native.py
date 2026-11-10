"""Frame exports through finite reviewed Blender 5.2 public operators.

Native only. Mesh copies bake evaluated geometry in world coordinates in a
temporary scene. Export/readback never replaces the editable source objects.
"""
from contextlib import contextmanager
import hashlib
from pathlib import Path

import bpy

from schemaxis.errors import fail
from .production_outputs import (output_jobs, triangle_metrics, matching_metrics,
                                 file_geometry, image_snapshot, METRES)


def _resolved_geometry(objects):
    """Resolve named roots once, including evaluated collection instances.

    A set of selected roots/children does not duplicate shared descendants.
    Distinct instances intentionally remain distinct world-space geometry.
    """
    closure = set()
    for obj in objects:
        closure.update([obj, *obj.children_recursive])
    graph = bpy.context.evaluated_depsgraph_get()
    count = 0
    for instance in graph.object_instances:
        obj = instance.object
        owner = instance.parent.original if instance.is_instance and instance.parent else obj.original
        if owner not in closure or obj.type not in ('MESH', 'CURVE', 'SURFACE', 'FONT', 'META'):
            continue
        # Blender5.2 exposes a legacy Curve/Font/Surface/Meta object's mesh
        # component again as an evaluated MESH instance. Consume that component
        # once; to_mesh on both records duplicates the same native geometry.
        # Unbevelled centreline curves without a mesh retain their point bounds.
        if obj.type in ('CURVE','SURFACE','FONT','META') and obj.evaluated_geometry().mesh is not None:
            continue
        count += 1
        if count > 10000:
            fail('RESOURCE_BUDGET_EXCEEDED', 'frame export exceeds ten thousand evaluated objects')
        # Instance IDs are transient. Callers must consume geometry before the
        # depsgraph iterator advances; a materialized list can retain invalid IDs.
        yield obj, instance.matrix_world.copy()
    if not count:
        fail('INVALID_PUBLICATION', 'selected objects contain no evaluated mesh geometry')



def geometry_snapshot(objects, scale=1.0):
    graph = bpy.context.evaluated_depsgraph_get()
    def triangles():
        for evaluated, world in _resolved_geometry(objects):
            mesh = evaluated.to_mesh()
            try:
                mesh.calc_loop_triangles()
                for face in mesh.loop_triangles:
                    yield [[x*scale for x in world @ mesh.vertices[i].co] for i in face.vertices]
            finally:
                evaluated.to_mesh_clear()
    return triangle_metrics(triangles())


@contextmanager
def _temporary_scene():
    original = bpy.context.window.scene
    # Importers/exporters can allocate supporting resources as well as objects.
    pools = [bpy.data.objects, bpy.data.meshes, bpy.data.curves, bpy.data.materials,
             bpy.data.images, bpy.data.actions, bpy.data.collections]
    before = [set(pool) for pool in pools]
    scene = bpy.data.scenes.new('__schemaxis_exchange')
    bpy.context.window.scene = scene
    scene.unit_settings.system = 'NONE'
    scene.unit_settings.scale_length = 1.0
    try:
        yield scene
    finally:
        bpy.context.window.scene = original
        bpy.data.scenes.remove(scene)
        for pool, prior in zip(pools, before):
            for item in list(set(pool) - prior):
                if pool == bpy.data.objects:
                    pool.remove(item, do_unlink=True)
                elif item.users == 0:
                    pool.remove(item)


def _bake(objects, scale):
    from mathutils import Matrix
    graph = bpy.context.evaluated_depsgraph_get()
    meshes = []
    for evaluated, world in _resolved_geometry(objects):
        mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=graph)
        mesh.transform(Matrix.Scale(scale, 4) @ world)
        meshes.append((evaluated.original.name, mesh))
    return meshes


def _export(format, path):
    common = {'filepath': str(path), 'check_existing': False}
    axes = {'forward_axis': 'Y', 'up_axis': 'Z', 'global_scale': 1.0}
    if format == 'stl':
        return bpy.ops.wm.stl_export(**common, **axes, ascii_format=False,
            export_selected_objects=True, apply_modifiers=True, use_scene_unit=False)
    if format == 'obj':
        return bpy.ops.wm.obj_export(**common, **axes, export_selected_objects=True,
            apply_modifiers=True, apply_transform=True, export_uv=True,
            export_normals=True, export_materials=False, export_triangulated_mesh=True)
    if format == 'ply':
        return bpy.ops.wm.ply_export(**common, **axes, export_selected_objects=True,
            apply_modifiers=True, ascii_format=True, export_uv=False,
            export_normals=False, export_colors='NONE', export_attributes=False,
            export_triangulated_mesh=True)
    if format == 'glb':
        return bpy.ops.export_scene.gltf(**common, export_format='GLB', use_selection=True, use_active_scene=True,
            export_apply=True, export_animations=False, export_current_frame=True,
            export_cameras=False, export_lights=False, export_materials='EXPORT',
            export_skins=False, export_morph=False, will_save_settings=False)
    if format == 'usd':
        return bpy.ops.wm.usd_export(**common, selected_objects_only=True,
            export_animation=False, export_materials=False, export_armatures=False,
            export_shapekeys=False, export_lights=False, export_cameras=False,
            export_curves=False, export_points=False, export_volumes=False,
            triangulate_meshes=True, convert_orientation=False,
            convert_scene_units='METERS', meters_per_unit=1.0)
    fail('UNSUPPORTED_PUBLICATION', 'unknown exchange format', format)


def _import(format, path):
    if format == 'stl':
        return bpy.ops.wm.stl_import(filepath=str(path), forward_axis='Y', up_axis='Z',
            global_scale=1, use_scene_unit=False, use_mesh_validate=True)
    if format == 'obj':
        return bpy.ops.wm.obj_import(filepath=str(path), forward_axis='Y', up_axis='Z',
            global_scale=1, use_split_objects=True, use_split_groups=False, validate_meshes=True)
    if format == 'ply':
        return bpy.ops.wm.ply_import(filepath=str(path), forward_axis='Y', up_axis='Z',
            global_scale=1, use_scene_unit=False, merge_verts=False)
    if format == 'glb':
        return bpy.ops.import_scene.gltf(filepath=str(path), import_pack_images=True)
    if format == 'usd':
        return bpy.ops.wm.usd_import(filepath=str(path), set_frame_range=False,
            import_cameras=False, import_lights=False, import_materials=False,
            import_skeletons=False, import_blendshapes=False, import_visible_only=False,
            apply_unit_conversion_scale=True)
    fail('UNSUPPORTED_PUBLICATION', 'unknown exchange format', format)


def _readback(format, path):
    if format == 'png':
        return image_snapshot(path)
    with _temporary_scene() as scene:
        if _import(format, path) != {'FINISHED'}:
            fail('VERIFICATION_FAILED', 'native exchange importer did not finish', str(path))
        objects = [o for o in scene.objects if o.type == 'MESH']
        if not objects:
            fail('VERIFICATION_FAILED', 'native exchange importer produced no geometry', str(path))
        return geometry_snapshot(objects)


def readback_outputs(records):
    return [_readback(r['format'], Path(r['file'])) for r in records]


def publish_outputs(scene, objects, production, directory, prefix):
    directory, records = Path(directory).resolve(), []
    original_frame, original_camera = scene.frame_current, scene.camera
    original_filepath = scene.render.filepath
    settings = scene.render.image_settings
    original_image = settings.file_format, settings.color_mode, settings.color_depth
    try:
        if 'camera' in production:
            camera = objects[production['camera']]
            if camera.type != 'CAMERA':
                fail('INVALID_REFERENCE', 'production camera must name a camera object', production['camera'])
            scene.camera = camera
        for job in output_jobs(production, prefix):
            scene.frame_set(job['frame'])
            bpy.context.view_layer.update()
            path = directory / job['name']
            record = {k: job[k] for k in ('id', 'format', 'frame', 'kind')}
            record.update(file=str(path), productionOutput=True)
            if job['format'] == 'png':
                if scene.camera is None:
                    fail('INVALID_REFERENCE', 'frame rendering needs a camera')
                settings.file_format, settings.color_mode, settings.color_depth = 'PNG', 'RGBA', '8'
                scene.render.filepath = str(path)
                from .render_writers_native import suppress
                with suppress(scene):
                    if bpy.ops.render.render(write_still=True) != {'FINISHED'}:
                        fail('PUBLICATION_FAILED', 'frame rendering did not finish')
                record['after'] = image_snapshot(path)
            else:
                source = [objects[n] for n in job['objects']]
                source_units = production.get('units', 'metres')
                if source_units not in METRES:
                    fail('INVALID_UNIT', 'production exports require declared physical units', source_units)
                physical = job['format'] in ('glb', 'usd')
                scale = METRES[source_units] if physical else 1.0
                expected = geometry_snapshot(source, scale)
                # Evaluate in the source scene before switching scenes.
                baked = _bake(source, scale)
                try:
                    with _temporary_scene() as export_scene:
                        for name, mesh in baked:
                            obj = bpy.data.objects.new(name + '-exchange', mesh)
                            export_scene.collection.objects.link(obj)
                            obj.select_set(True)
                            bpy.context.view_layer.objects.active = obj
                        if _export(job['format'], path) != {'FINISHED'}:
                            fail('PUBLICATION_FAILED', 'native exchange exporter did not finish', job['id'])
                finally:
                    for _, mesh in baked:
                        if mesh.name in bpy.data.meshes and mesh.users == 0:
                            bpy.data.meshes.remove(mesh)
                actual = _readback(job['format'], path)
                independently_decoded = file_geometry(path, job['format'])
                if (not matching_metrics(expected, actual)
                        or independently_decoded is not None and not matching_metrics(expected, independently_decoded)):
                    fail('VERIFICATION_FAILED', 'exchange geometry changed beyond the float32/ASCII budget', job['id'])
                record.update(objects=job['objects'], before=expected, after=actual,
                    selectionSemantics='selected roots, descendants and evaluated collection instances; shared descendants once',
                    comparison='triangles and geometric moments; 2e-5 relative and 2e-6 model-scale dimensional absolute budget',
                    sourceUnits=source_units, units='metres' if physical else source_units, coordinateScale=scale,
                    losses=['procedural history', 'constraints', 'animation', 'rigs',
                            'object hierarchy', 'full shader graphs', 'arbitrary attributes'],
                    appearance='glb may approximate supported materials; other formats publish geometry only')
            record['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            records.append(record)
    finally:
        scene.frame_set(original_frame)
        scene.camera = original_camera
        scene.render.filepath = original_filepath
        settings.file_format, settings.color_mode, settings.color_depth = original_image
        bpy.context.view_layer.update()
    return records
