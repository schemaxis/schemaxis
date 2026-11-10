"""Import complete GLB or append local packed blend assets without running scripts."""
import json
from collections import Counter
from pathlib import Path
import bpy
from mathutils import Matrix
from schemaxis.errors import fail
from schemaxis.artifacts import file_digest
from .production_outputs import METRES


def load_asset(spec,scene,sources,collections,production_units,shader_budget=None,*,original_materials=None,projection_sources=None):
    source=Path(sources['asset:'+spec['id']]['retained']);before=set(bpy.data.objects);before_images=set(bpy.data.images);before_materials=set(bpy.data.materials);before_groups=set(bpy.data.node_groups)
    asset_collection=bpy.data.collections.new(spec['id']+'-asset')
    (collections[spec['collection']] if spec['collection'] else scene.collection).children.link(asset_collection)
    ownership=None;source_objects=[];source_collisions=[]
    if spec['format']=='blend':
        with bpy.data.libraries.load(str(source),link=False) as (available,selected):
            source_objects=list(available.objects)
            source_collisions=sorted(set(source_objects)&{o.name for o in before})
        from .production_asset_collections import load_scene
        ownership=load_scene(source,spec,capture_collection_paths=projection_sources is not None);imported=ownership['objects']
        pools=[bpy.data.objects,bpy.data.meshes,bpy.data.materials,bpy.data.images,bpy.data.actions,bpy.data.collections,bpy.data.node_groups,bpy.data.armatures,bpy.data.curves,bpy.data.cameras,bpy.data.lights,bpy.data.worlds]
        if any(d.library is not None for pool in pools for d in pool):fail('UNSUPPORTED_ASSET_DEPENDENCY','linked native libraries must be made local before asset reuse',spec['id'])
        for library in list(bpy.data.libraries):bpy.data.libraries.remove(library)
    else:
        # Import physical GLB into a metre staging scene, then place it using an
        # explicit source-to-production scale; current scene scale cannot guess.
        if spec['format'] in ('glb','gltf'):
            from .production_assets import require_embedded_gltf
            source_document=require_embedded_gltf(source,spec['format'])
            nodes=source_document.get('nodes',[])
            if not isinstance(nodes,list) or len(nodes)>4096:fail('RESOURCE_BUDGET_EXCEEDED','glTF asset must contain at most4096 source nodes',spec['id'])
            source_objects=[n['name'] for n in source_document.get('nodes',[]) if isinstance(n,dict) and 'mesh' in n and isinstance(n.get('name'),str) and n['name']]
            all_names=[n['name'] for n in source_document.get('nodes',[]) if isinstance(n,dict) and isinstance(n.get('name'),str)]
            counts=Counter(all_names)
            source_collisions=sorted(set(source_objects)&{o.name for o in before}|{n for n in source_objects if counts[n]>1})
        if spec['format']=='obj' and any(line.lstrip().startswith('mtllib ') for line in source.read_text().splitlines()):fail('UNSUPPORTED_ASSET_DEPENDENCY','OBJ material libraries require explicit captured dependencies; use self-contained GLB or geometry-only OBJ',spec['id'])
        if spec['format']=='usd':
            from .production_outputs import file_geometry
            file_geometry(source,'usd')
        original=bpy.context.window.scene;stage=bpy.data.scenes.new('__schemaxis_asset_import');stage.unit_settings.scale_length=1
        bpy.context.window.scene=stage
        try:
            if spec['format']=='gltf':outcome=bpy.ops.import_scene.gltf(filepath=str(source),import_pack_images=True)
            else:
                from .production_output_native import _import
                outcome=_import(spec['format'],source)
            if outcome!={'FINISHED'}:fail('IMPORT_FAILED','GLB importer did not finish',spec['id'])
            imported=sorted(set(bpy.data.objects)-before,key=lambda o:o.name)
            for obj in imported:
                for c in list(obj.users_collection):c.objects.unlink(obj)
        finally:
            bpy.context.window.scene=original;bpy.data.scenes.remove(stage)
    if not imported or len(imported)>4096:fail('UNSUPPORTED_ASSET','asset must contain1–4096 objects',spec['id'])
    for image in (() if ownership else set(bpy.data.images)-before_images):
        # Imported source projects must be self-contained, rather than reading
        # arbitrary workstation files during rendering or future verification.
        if image.source not in ('FILE','GENERATED'):fail('UNSUPPORTED_ASSET_DEPENDENCY','movie/sequence/render-result image dependencies need an explicit captured media workflow',image.name)
        if image.source=='FILE' and not image.packed_file:fail('UNSUPPORTED_ASSET_DEPENDENCY','pack image dependencies before native asset reuse',image.name)
    trees=[] if ownership else [m.node_tree for m in set(bpy.data.materials)-before_materials if m.node_tree]+list(set(bpy.data.node_groups)-before_groups)
    for tree in trees:
        if any(n.bl_idname in ('ShaderNodeScript','GeometryNodeSimulationInput','GeometryNodeSimulationOutput','GeometryNodeBake') for n in tree.nodes):fail('UNSUPPORTED_ASSET_DEPENDENCY','script shaders and stateful node caches require a captured qualified dependency workflow',tree.name)
    for obj in imported:
        if obj.instance_type=='COLLECTION' and not ownership:fail('UNSUPPORTED_ASSET_DEPENDENCY','native collection-instance asset dependencies require a captured collection ownership workflow',obj.name)
        animation=obj.animation_data
        if animation and any(not d.driver.is_simple_expression for d in animation.drivers):fail('UNSUPPORTED_ASSET_DEPENDENCY','native project assets cannot execute driver scripts; use supported simple expressions or bake motion',obj.name)
        if obj.type=='FONT':
            for font in (obj.data.font,obj.data.font_bold,obj.data.font_italic,obj.data.font_bold_italic):
                if font and not font.packed_file and font.filepath!='<builtin>':fail('UNSUPPORTED_ASSET_DEPENDENCY','pack external font dependencies before project reuse',font.name)
    # Reserve the public root identity even when a non-visible dependency has
    # the same source name. Namespace all appended objects before making it.
    source_names={obj:obj.name for obj in ownership['importedIds']['objects']} if ownership else {}
    for obj,name in source_names.items():obj.name=spec['id']+'--'+name
    root=bpy.data.objects.new(spec['id'],None);asset_collection.objects.link(root)
    scale=METRES[spec['sourceUnits']]/METRES[production_units]
    if ownership and ownership['carrier']:
        root.instance_type='COLLECTION';root.instance_collection=ownership['carrier']
    root.location=spec['location'];root.rotation_mode='XYZ';root.rotation_euler=spec['rotation'];root.scale=[x*scale for x in spec['scale']]
    bpy.context.view_layer.update()
    imported_set=set(imported);members=[]
    for obj in imported:
        original_name=source_names.get(obj,obj.name)
        if not ownership:obj.name=spec['id']+'--'+original_name
        if not (ownership and ownership['carrier']):
            for c in list(obj.users_collection):c.objects.unlink(obj)
            asset_collection.objects.link(obj)
        if not (ownership and ownership['carrier']) and obj.parent not in imported_set:
            matrix=obj.matrix_world.copy();obj.parent=root;obj.matrix_parent_inverse=Matrix.Identity(4);obj.matrix_basis=matrix
        if obj.type=='LIGHT' and not spec['includeLights']:obj.hide_render=True
        members.append({'name':obj.name,'sourceName':original_name,'type':obj.type})
        # Local modifier caches and external scene/sequence references are not
        # silently treated as a portable asset. Static/procedural/rigged models
        # remain available while those dependency families are implemented.
        if obj.rigid_body:fail('UNSUPPORTED_ASSET_DEPENDENCY','rigid-body scene dependencies need an explicit reproducible simulation handoff',obj.name)
        for modifier in obj.modifiers:
            if modifier.type in ('FLUID','CLOTH','SOFT_BODY','MESH_CACHE','MESH_SEQUENCE_CACHE','PARTICLE_SYSTEM','OCEAN'):
                fail('UNSUPPORTED_ASSET_DEPENDENCY','bake or remove external/stateful simulation dependencies before reuse',obj.name,modifier=modifier.type)
    # A source may already contain an object with the consumer's asset ID.
    # Namespacing imported members releases that identity for the carrier.
    root.name=spec['id']
    root['schemaxisAssetSourceObjects']=json.dumps(source_objects)
    root['schemaxisAssetSourceCollisions']=json.dumps(source_collisions)
    root['schemaxisAssetMembers']=json.dumps(members,sort_keys=True)
    if ownership:
        root['schemaxisAssetSelection']=json.dumps(ownership['selection'],sort_keys=True)
    from .production_asset_snapshot import Snapshot
    proof=Snapshot(root,shader_budget=shader_budget)
    for member in proof.members:proof.object(member)
    if root.instance_type=='COLLECTION':proof.dependency(root.instance_collection)
    projection_collections={native:identity for native,identity in ownership['sourceCollections'].items() if native in proof.ids} if ownership and projection_sources is not None else {}
    if ownership:
        from .production_asset_collections import prune_imported
        prune_imported(ownership,proof.ids)
    root['schemaxisAssetSha256']=file_digest(source)
    root['schemaxisAssetFormat']=spec['format'];root['schemaxisAssetScale']=scale
    if original_materials is not None:
        # Process-local output of this trusted import, before any consumer
        # palette/assignment. Do not reconstruct it from saved ownership tags.
        if spec['id'] in original_materials:
            fail('DUPLICATE_ID','original asset material provenance already exists',spec['id'])
        originals={}
        for obj in imported:
            source_name=source_names.get(obj,obj.name.removeprefix(spec['id']+'--'))
            if source_name in originals:
                fail('AMBIGUOUS_ASSET_SELECTION','source object material provenance is ambiguous',source_name)
            originals[source_name]={'object':obj,'slots':tuple(
                (slot.link,slot.material) for slot in obj.material_slots)}
        original_materials[spec['id']]=originals
    created=sorted(ownership['importedIds']['objects'] & proof.ids,key=lambda o:o.name) if ownership else imported
    if projection_sources is not None:
        if ownership is None or not ownership['carrier']:
            fail('UNSUPPORTED_RENDER_PROJECTION','nested projection needs a captured native scene collection hierarchy',spec['id'])
        projection_sources[spec['id']]={'root':root,'carrier':ownership['carrier'],
          'container':asset_collection,'objects':tuple(imported),'dependencies':tuple(created),
          'sourceCollections':projection_collections}
    return root,[*created,root],asset_collection


def observe_asset(spec,objects,shader_budget=None,features=None):
    from .production_native import evaluated
    root=objects[spec['id']]
    if root.type!='EMPTY':fail('VERIFICATION_FAILED','asset root type differs',root.name)
    records=[]
    from .production_asset_collections import asset_members
    for obj in asset_members(root):
        records.append({'name':obj.name,'type':obj.type,'parent':obj.parent.name if obj.parent else '', 'materials':[m.name if m else None for m in obj.data.materials] if obj.data and hasattr(obj.data,'materials') else [],'modifiers':[{'name':m.name,'type':m.type} for m in obj.modifiers],'geometry':evaluated(obj,groups=root.instance_type!='COLLECTION')})
    if not records:fail('VERIFICATION_FAILED','asset members absent',root.name)
    from .production_asset_snapshot import snapshot_asset_members
    fidelity=snapshot_asset_members(root,shader_budget=shader_budget,features=features)
    return {'selection':json.loads(root.get('schemaxisAssetSelection','null')),'fidelity':fidelity,'id':root.name,'format':root.get('schemaxisAssetFormat'),'sourceSha256':root.get('schemaxisAssetSha256'),'coordinateScale':root.get('schemaxisAssetScale'),'members':records}
