"""One trusted construction supplies immutable asset/material/shader references."""
import copy
import json
import bpy


def construct(master, selection, prepared, visit, sources):
    from .native import Backend, configure_render
    from .production_native import Production
    from schemaxis.pipeline import RuntimeClosure
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    configure_render(scene, {**prepared['renderSettings'], 'device':'CPU'})
    camera = bpy.data.objects.new('__schemaxis_camera', bpy.data.cameras.new('__schemaxis_camera'))
    scene.collection.objects.link(camera); scene.camera = camera
    active = RuntimeClosure(master, Backend(sources))
    active.activate(selection.roots); active.apply(visit)
    scene['schemaxisNodes']=json.dumps(selection.order)
    scene['schemaxisVisible']=json.dumps(master.document['scenes'][0]['visible'])
    for name,obj in active.handles.items():
        if isinstance(obj,bpy.types.Object):obj.hide_render=name not in master.document['scenes'][0]['visible']
    spec = master.document['scenes'][0].get('production')
    production = Production(copy.deepcopy(spec), active.handles, sources) if spec is not None else None
    return active, production


def shader_names(master, selection):
    scene = master.document['scenes'][0]; spec = scene.get('production', {})
    dag = {n['id']:n['filter'] for n in master.document['nodes']}
    materials = [name for name in selection.order if dag[name]=='material']
    from .surface_compile import all_material_graphs
    materials += [g['id'] for g in all_material_graphs(spec)]
    groups = [g['id'] for g in spec.get('nodeGroups', []) if g['family']=='material']
    return materials, groups, [i['id'] for i in spec.get('images', [])]


def references(master, selection, prepared, visit, sources, *, reference_directory=None, state_index=0):
    spec = master.document['scenes'][0].get('production', {})
    names = shader_names(master, selection)
    active, production = construct(master, selection, prepared, visit, sources)
    if production and production.spec.get('simulationCaches'):
        if reference_directory is None:
            from schemaxis.errors import fail
            fail('VERIFICATION_CONTEXT_REQUIRED','fresh cache reconstruction needs its owned reference directory')
        from pathlib import Path
        production.prepare_caches(sources,Path(reference_directory)/f'{state_index:04d}.blend')
    from .shader_budget_native import ShaderBudget
    budget=production.shader_budget if production else ShaderBudget()
    objects=production.objects if production else {n:o for n,o in active.handles.items() if isinstance(o,bpy.types.Object)}
    # Recreate the final authored writer camera, including expression inputs,
    # before observing Attribute inputs that may read scene/camera RNA values.
    from .native import Backend,frame
    from .production_native import group_observation
    from schemaxis.camera import camera_values
    from schemaxis.pipeline import evaluate
    observations={name:Backend().observe(obj) for name,obj in active.handles.items()}
    scene_spec=master.document['scenes'][0]
    for name in scene_spec['visible']:
        if name not in observations:
            obj=objects[name]
            observations[name]=group_observation(obj) if obj.type in ('EMPTY','ARMATURE') else Backend().observe(obj)
    data=[observations[name]['bounds'] for name in scene_spec['visible']]
    bounds=[min(b[i] for b in data) if i%2==0 else max(b[i] for b in data) for i in range(6)]
    writer=scene_spec['images'][0]
    for authored in writer['cameras']:
        settings=camera_values(evaluate(authored,visit['axes'],observations,visit['time'],'camera'),'camera')
        frame(bpy.context.scene.camera,settings,bounds,writer['size'])
    if production and production.features:
        production.features.prefix=f'{state_index:04d}'
        production.features.prepare_shading()
        if production.spec.get('renderBundles'):
            if reference_directory is None:
                from schemaxis.errors import fail
                fail('VERIFICATION_CONTEXT_REQUIRED','render data requires its fresh owned reference directory')
            bundle_records=production.features.publish(reference_directory)
        else:bundle_records=[]
    else:bundle_records=[]
    # Execute frames writer cameras before its simulation/readback warmup.
    # Match that order so automatic framing uses the same cold geometry.
    if production:production.snapshot()
    if production:budget=production.shader_budget
    from .object_materials_native import observe as observe_objects
    object_materials=observe_objects(objects,names[0],budget,names[2],features=production.features if production else None)
    from .production_asset_snapshot import snapshot_asset_members
    from .material_assignments_native import observe as observe_materials
    from .shader_fidelity_native import observe as observe_shaders
    from .render_context_native import observe as observe_render_context
    return {
        'assets':{a['id']:snapshot_asset_members(production.objects[a['id']],shader_budget=production.shader_budget,features=production.features) for a in spec['assets']} if spec.get('assets') else None,
        'materials':observe_materials(spec, production.objects) if spec.get('materialAssignments') else None,
        'shaders':observe_shaders(*names,shader_budget=budget,features=production.features if production else None) if any(names[:2]) else None,
        'objectMaterials':object_materials,'renderContext':observe_render_context(features=production.features if production else None),
        'featureBindings':production.features.bindings() if production and production.features else None,
        'caches':production.caches if production else None,'bundles':bundle_records,
        'featureShading':production.features.fidelity() if production and production.features and production.features.needs_shading else None}
