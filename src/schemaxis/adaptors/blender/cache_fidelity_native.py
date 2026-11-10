"""Native cache geometry observation and finite original physics fingerprints.

This is an internal kernel. Integration must establish source authority before
restoring a submitted .blend, then compare against a fresh constructor and bake.
"""
import math
import bpy
from schemaxis.errors import fail
from .cache_policy import fingerprint, MAX_FRAMES


def scalars(owner):
    result = {}
    for prop in owner.bl_rna.properties:
        if prop.identifier == 'rna_type' or prop.type not in ('BOOLEAN','INT','FLOAT','STRING','ENUM'):continue
        value = getattr(owner, prop.identifier)
        if getattr(prop,'is_array',False):value = list(value)
        elif isinstance(value, set):value = sorted(value)
        result[prop.identifier] = value
    return result


def inputs(scene):
    """Bind first-consumer parameters, topology, weights and initial transforms.

    Animated/constraint/other modifier consumers deliberately refuse until their
    dependency contracts exist; no extra physics family is implicitly admitted.
    """
    if sum(len(o.data.vertices) for o in scene.objects if o.type=='MESH')>100000:fail('RESOURCE_BUDGET_EXCEEDED','cache geometry exceeds 100000 vertices before observation')
    if sum(len(o.data.loops)+len(o.data.edges) for o in scene.objects if o.type=='MESH')>800000:fail('RESOURCE_BUDGET_EXCEEDED','cache topology exceeds finite input budget')
    if any(o.field and o.field.type!='NONE' for o in scene.objects):fail('UNSUPPORTED_CACHE','force-field dependency cache contract is still required')
    objects = []
    for obj in sorted(scene.objects, key=lambda o:o.name):
        cloth = [m for m in obj.modifiers if m.type=='CLOTH']
        collision = [m for m in obj.modifiers if m.type=='COLLISION']
        if obj.rigid_body is None and not cloth and not collision:continue
        if obj.type != 'MESH' or obj.animation_data or obj.constraints or obj.rigid_body_constraint or obj.parent:
            fail('UNSUPPORTED_CACHE', 'first cache consumers need static unparented unconstrained mesh inputs', obj.name)
        if any(m.type not in ('CLOTH','COLLISION') for m in obj.modifiers) or len(cloth)>1:
            fail('UNSUPPORTED_CACHE', 'cache modifier stack requires its finite consumer contract', obj.name)
        if obj.data.animation_data or obj.data.shape_keys:fail('UNSUPPORTED_CACHE', 'animated mesh/rest shapes need cache dependency support', obj.name)
        records=[]
        for mod in cloth:
            if mod.settings.rest_shape_key or mod.settings.effector_weights.collection or mod.collision_settings.collection:
                fail('UNSUPPORTED_CACHE', 'cloth dependency collections/rest shape need an explicit mapping', obj.name)
            records.append({'name':mod.name,'settings':scalars(mod.settings),'collision':scalars(mod.collision_settings),
                            'effectors':scalars(mod.settings.effector_weights)})
        objects.append({'name':obj.name,'matrix':[list(r) for r in obj.matrix_world],
                        'vertices':[list(v.co) for v in obj.data.vertices],
                        'faces':[list(f.vertices) for f in obj.data.polygons],
                        'edges':[list(e.vertices) for e in obj.data.edges],
                        'visibility':[obj.hide_viewport,obj.hide_render,obj.hide_get()],
                        'weights':[[[g.group,g.weight] for g in v.groups] for v in obj.data.vertices],
                        'groups':[g.name for g in obj.vertex_groups],
                        'rigidBody':scalars(obj.rigid_body) if obj.rigid_body else None,
                        'cloth':records,'collision':scalars(obj.collision) if collision else None})
    if not objects:fail('INVALID_CACHE', 'cache constructor has no physics consumers')
    if sum(len(o['vertices']) for o in objects)>100000:fail('RESOURCE_BUDGET_EXCEEDED','cache geometry exceeds 100000 vertices')
    world = scene.rigidbody_world
    if world and (world.constraints and world.constraints.objects or world.effector_weights.collection):
        fail('UNSUPPORTED_CACHE','joint/motor and external effector cache contracts are still required')
    value={'scene':scene.name,'fps':[scene.render.fps,scene.render.fps_base],'gravity':list(scene.gravity),'useGravity':scene.use_gravity,
           'units':scalars(scene.unit_settings),'objects':objects,
           'rigidWorld':{'settings':scalars(world),'effectors':scalars(world.effector_weights),
                         'members':sorted(o.name for o in world.collection.objects)} if world else None}
    return fingerprint(value)


def observe(scene, names, frames):
    if len(frames)>MAX_FRAMES or not frames:fail('INVALID_CACHE','cache observations need a finite nonempty frame list')
    vertex_count=sum(len(scene.objects[n].data.vertices) for n in names if n in scene.objects and scene.objects[n].type=='MESH')
    if vertex_count*len(frames)*24>64*1024**2:fail('RESOURCE_BUDGET_EXCEEDED','cache observation coordinates exceed 64 MiB')
    previous=scene.frame_current;result={}
    try:
        for frame in frames:
            scene.frame_set(frame);graph=bpy.context.evaluated_depsgraph_get();record={}
            for name in names:
                obj=scene.objects.get(name)
                if obj is None:fail('VERIFICATION_FAILED','cache consumer missing',name)
                evaluated=obj.evaluated_get(graph);mesh=evaluated.to_mesh()
                try:record[name]={'matrix':[list(row) for row in evaluated.matrix_world],
                                 'vertices':[list(evaluated.matrix_world@v.co) for v in mesh.vertices],
                                 'faces':[list(f.vertices) for f in mesh.polygons]}
                finally:evaluated.to_mesh_clear()
            result[str(frame)]=record
    finally:scene.frame_set(previous)
    return result


def compare(actual, fresh, *, tolerance=1e-6):
    """Complete indexed geometry at EVERY requested frame, not a scalar witness."""
    if not math.isfinite(tolerance) or not 0<=tolerance<=1e-4:fail('INVALID_CACHE','cache tolerance exceeds fixed finite contract')
    def check(a,b):
        if isinstance(b,dict):return isinstance(a,dict) and set(a)==set(b) and all(check(a[k],v) for k,v in b.items())
        if isinstance(b,list):return isinstance(a,list) and len(a)==len(b) and all(check(x,y)for x,y in zip(a,b))
        if type(b) is int:return type(a) is int and a==b
        if type(b) is float:return type(a) in (int,float) and math.isfinite(a) and math.isfinite(b) and abs(a-b)<=tolerance
        return a==b
    if not fresh or not check(actual,fresh):fail('VERIFICATION_FAILED','cache geometry differs from fresh trusted bake')
