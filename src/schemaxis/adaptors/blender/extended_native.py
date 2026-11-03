# Copyright (C) 2026 David L F Gaden
"""Explicit native mesh import and assembly, without authored Python callbacks."""
import math
from pathlib import Path
import bpy
from mathutils import Matrix
from schemaxis.errors import fail
from schemaxis.artifacts import file_digest


def import_mesh(identity,kind,options,sources):
    path=Path(sources.get(identity,{}).get('retained',options['file']))
    if not path.is_file():fail('RESOURCE_NOT_FOUND','mesh input is absent',str(path))
    before=set(bpy.data.objects)
    arguments={'filepath':str(path),'global_scale':options['scale'],'use_scene_unit':False,'forward_axis':'Y','up_axis':'Z'}
    outcome=bpy.ops.wm.stl_import(**arguments) if kind=='readSTL' else bpy.ops.wm.ply_import(**arguments)
    imported=set(bpy.data.objects)-before
    if outcome!={'FINISHED'} or len(imported)!=1 or next(iter(imported)).type!='MESH':
        fail('UNSUPPORTED_RESOURCE','mesh import must create exactly one mesh',identity)
    obj=next(iter(imported));obj.name=identity
    if not obj.data.polygons:fail('UNSUPPORTED_RESOURCE','mesh import requires polygon faces',identity)
    obj['schemaxisSourceSha256']=file_digest(path)
    return obj


def join_meshes(obj,sources):
    graph=bpy.context.evaluated_depsgraph_get()
    points,faces,indices,materials,smooth=[],[],[],[],[]
    for source in sources:
        evaluated=source.evaluated_get(graph);mesh=evaluated.to_mesh()
        try:
            offset=len(points)
            points.extend(tuple(evaluated.matrix_world@v.co) for v in mesh.vertices)
            local=[]
            for material in mesh.materials:
                material=material.original if material and material.is_evaluated else material
                if material not in materials:materials.append(material)
                local.append(materials.index(material))
            for face in mesh.polygons:
                faces.append(tuple(offset+i for i in face.vertices))
                indices.append(local[face.material_index] if local else 0)
                smooth.append(face.use_smooth)
        finally:evaluated.to_mesh_clear()
    replacement=bpy.data.meshes.new(obj.name+'-joined');replacement.from_pydata(points,[],faces)
    for material in materials:replacement.materials.append(material)
    for face,index,flag in zip(replacement.polygons,indices,smooth):face.material_index=index;face.use_smooth=flag
    old=obj.data;obj.data=replacement;obj.matrix_world=Matrix.Identity(4)
    if old.users==0:bpy.data.meshes.remove(old)


def check_voxel_budget(mesh,size):
    if not mesh.vertices:fail('INVALID_GEOMETRY','voxel remeshing needs nonempty geometry')
    lengths=[max(v.co[i] for v in mesh.vertices)-min(v.co[i] for v in mesh.vertices) for i in range(3)]
    ratios=[length/size for length in lengths]
    if any(not math.isfinite(ratio) or ratio>8_000_000 for ratio in ratios):
        fail('RESOURCE_BUDGET_EXCEEDED','voxel size is too small for source bounds; increase voxelSize')
    estimate=math.prod(math.ceil(ratio)+4 for ratio in ratios)
    if estimate>8_000_000:fail('RESOURCE_BUDGET_EXCEEDED','voxel remesh exceeds 8 million bounding-grid cells; increase voxelSize',estimatedCells=estimate)
