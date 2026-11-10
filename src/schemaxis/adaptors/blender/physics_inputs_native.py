"""Fresh finite physics inputs which can change an existing rendered scene.

This binds native defaults and retained channels; it exposes no new authored
physics controls and does not claim general force/soft-body/cache support.
"""
from schemaxis.errors import fail


def dependencies(native,expected):
    actual={p.identifier for p in native.bl_rna.properties
            if p.type in ('POINTER','COLLECTION') and p.identifier!='rna_type'}
    if actual!=set(expected):
        fail('VERIFICATION_FAILED','physics input dependencies need a reviewed native mapping',native.bl_rna.identifier)


def settings(reader,native,kind):
    if native is None:return None
    if native.bl_rna.identifier!=kind:
        fail('VERIFICATION_FAILED','physics input needs its reviewed native class',kind)
    return reader.primitive(native)


def weights(reader,native,identity):
    value=settings(reader,native,'EffectorWeights');dependencies(native,{'collection'})
    return {'settings':value,'collection':identity(native.collection)}


def cache(reader,native):
    value=settings(reader,native,'PointCache');dependencies(native,{'point_caches'})
    if (native.is_baked or native.use_disk_cache or native.use_external) and native not in getattr(reader,'cache_handles',set()):
        fail('VERIFICATION_FAILED','baked, disk and external simulation caches need a typed cache contract')
    return {'settings':value,'slots':[settings(reader,item,'PointCacheItem') for item in native.point_caches]}


def world_collections(scene):
    world=scene.rigidbody_world
    return [c for c in (world.collection,world.constraints,world.effector_weights.collection) if c is not None] if world else []


def world(reader,scene,identity):
    native=scene.rigidbody_world
    if native is None:return None
    value=settings(reader,native,'RigidBodyWorld')
    dependencies(native,{'collection','constraints','point_cache','effector_weights'})
    return {'settings':value,'collection':identity(native.collection),'constraints':identity(native.constraints),
            'effectors':weights(reader,native.effector_weights,identity),'cache':cache(reader,native.point_cache)}


def object_inputs(reader,obj,identity):
    result={}
    if obj.soft_body is not None or obj.rigid_body_constraint is not None:
        fail('VERIFICATION_FAILED','soft bodies and rigid-body constraints need a typed physics contract',obj.name)
    if obj.field is not None:
        native=obj.field;value=settings(reader,native,'FieldSettings');dependencies(native,{'texture','source_object'})
        # These dependencies require texture/force-source geometry mappings;
        # do not silently preserve only a local display name or current mode.
        if native.texture is not None or native.source_object is not None:
            fail('VERIFICATION_FAILED','texture and source-object force fields need a typed dependency contract',obj.name)
        result['field']=value
    else:result['field']=None
    result['rigidBody']=settings(reader,obj.rigid_body,'RigidBodyObject')
    if obj.rigid_body is not None:dependencies(obj.rigid_body,set())
    result['collision']=settings(reader,obj.collision,'CollisionSettings')
    if obj.collision is not None:dependencies(obj.collision,set())
    result['cloth']=[]
    for modifier in obj.modifiers:
        if modifier.type!='CLOTH':continue
        native=modifier.settings;collision=modifier.collision_settings
        value=settings(reader,native,'ClothSettings');dependencies(native,{'effector_weights','rest_shape_key'})
        if native.rest_shape_key is not None:
            fail('VERIFICATION_FAILED','cloth rest-shape overrides need a typed shape dependency contract',obj.name)
        coll=settings(reader,collision,'ClothCollisionSettings');dependencies(collision,{'collection'})
        result['cloth'].append({'modifier':modifier.name,'settings':value,
            'effectors':weights(reader,native.effector_weights,identity),
            'collision':{'settings':coll,'collection':identity(collision.collection)},
            'cache':cache(reader,modifier.point_cache)})
    return result
