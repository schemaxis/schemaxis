# Copyright (C) 2026 David L F Gaden
"""Native evaluated-mesh STL export with native import and host-verifiable triangles."""
import bpy
from .stl import triangle, digest, file_snapshot, LIMIT
from schemaxis.errors import fail
from schemaxis.artifacts import file_digest


def snapshot(obj):
    graph=bpy.context.evaluated_depsgraph_get();evaluated=obj.evaluated_get(graph);mesh=evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        if len(mesh.loop_triangles)>LIMIT:fail('RESOURCE_BUDGET_EXCEEDED','STL triangle budget exceeded')
        return digest([triangle([tuple(evaluated.matrix_world@mesh.vertices[i].co) for i in t.vertices]) for t in mesh.loop_triangles])
    finally:evaluated.to_mesh_clear()


def readback(path):
    before=set(bpy.data.objects)
    result=bpy.ops.wm.stl_import(filepath=str(path),forward_axis='Y',up_axis='Z',global_scale=1,use_scene_unit=False,use_mesh_validate=True)
    imported=set(bpy.data.objects)-before
    try:
        if result!={'FINISHED'} or len(imported)!=1:fail('VERIFICATION_FAILED','STL readback object membership differs')
        return snapshot(next(iter(imported)))
    finally:
        for obj in imported:
            mesh=obj.data;bpy.data.objects.remove(obj,do_unlink=True)
            if mesh.users==0:bpy.data.meshes.remove(mesh)


def publish(obj,path):
    expected=snapshot(obj)
    bpy.ops.object.select_all(action='DESELECT');obj.select_set(True);bpy.context.view_layer.objects.active=obj
    result=bpy.ops.wm.stl_export(filepath=str(path),check_existing=False,ascii_format=False,export_selected_objects=True,apply_modifiers=True,forward_axis='Y',up_axis='Z',global_scale=1,use_scene_unit=False)
    if result!={'FINISHED'}:fail('PUBLICATION_FAILED','native STL exporter failed')
    actual=file_snapshot(path)
    reopened=readback(path)
    if expected!=actual or expected!=reopened:fail('VERIFICATION_FAILED','STL round trip changed oriented float32 triangles')
    return {'file':str(path),'sha256':file_digest(path),'kind':'geometry','format':'stl','comparison':'oriented-float32-triangles',
            'losses':['materials','normals','UVs','attributes','units metadata'], 'before':expected,'after':reopened}
