"""Native applicability of typed surface coordinates on actual rendered data."""
import bpy
from schemaxis.errors import fail
from .surface_compile import compile_surface


def uv_requirements(spec):
    required={}
    for surface in spec.get('surfaceMaterials',[]):
        names=set()
        for node in compile_surface(surface,spec.get('images',[]))['nodes']:
            kind=node['kind'];props=node['properties']
            if kind=='uvMap':names.add(props['name'])
            elif kind=='normalMap' and props.get('space','TANGENT')=='TANGENT':names.add(props.get('uvMap',''))
            elif kind=='tangent' and props['direction']=='UV_MAP':names.add(props.get('uvMap',''))
        required[surface['id']]=names
    return required


def validate_uvs(spec):
    required=uv_requirements(spec)
    if not any(required.values()):return
    graph=bpy.context.evaluated_depsgraph_get()
    for obj in bpy.data.objects:
        if obj.type not in ('MESH','CURVE','SURFACE','FONT'):continue
        native=obj.evaluated_get(graph);mesh=native.to_mesh()
        try:
            used=set()
            for face in mesh.polygons:
                index=face.material_index
                material=mesh.materials[index] if index<len(mesh.materials) else None
                if index<len(obj.material_slots) and obj.material_slots[index].link=='OBJECT':material=obj.material_slots[index].material
                if material:used.add(material.name)
            for material in used:
                for name in required.get(material,()):
                    exists=name in mesh.uv_layers if name else any(u.active_render for u in mesh.uv_layers)
                    if not exists:fail('MISSING_SURFACE_UV','used surface sampling and tangent basis require an existing evaluated UV set',
                                       obj.name,material=material,uvMap=name or '<render-active>')
        finally:native.to_mesh_clear()
