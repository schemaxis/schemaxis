# Copyright (C) 2026 David L F Gaden
"""Application-owned scene and settings schemas; host-safe."""
from schemaxis.schema import NAME, DRAFT, object_schema, arguments_schema, argument_schema, option_schema, graph_document_schema
from schemaxis.camera import CAMERA
from .settings import RENDER_OPTIONS


def scene_schema(catalogue, definitions):
    image = object_schema({'id': NAME, 'size': {'type': 'array', 'items': {'type': 'integer',
        'minimum': 32, 'maximum': 2048}, 'minItems': 2, 'maxItems': 2,
        'default': [320, 240]},
        'cameras': {'type': 'array', 'minItems': 1, 'items': arguments_schema(CAMERA, dynamic=True)}}, ['id', 'cameras'])
    images = {'type': 'array', 'items': image}
    images.update(minItems=1, maxItems=1)
    from .production import schema as production_schema
    scene = object_schema({'id': NAME, 'visible': {'type': 'array', 'items': NAME, 'minItems': 1},
        'production': production_schema(),
        'render': arguments_schema(RENDER_OPTIONS), 'prepareOnly': {'type': 'boolean'}, 'meshes':{'type':'array','items':NAME,'uniqueItems':True}, 'images': images}, ['id', 'visible', 'images'])
    return scene


def document_schema():
    return graph_document_schema('blender', scene_schema, max_scenes=1)


def render_schema():
    return arguments_schema(RENDER_OPTIONS)


def saved_scene_schema():
    return object_schema({
        'version': {'const': 'schemaxis.blender.render/1'},
        'sceneFile': {'type': 'string', 'minLength': 1},
        'cameras': {'type': 'array', 'minItems': 1, 'maxItems': 1000, 'items': arguments_schema(CAMERA)},
        'render': arguments_schema(RENDER_OPTIONS),
        'size': {'type': 'array', 'minItems': 2, 'maxItems': 2,
                 'items': {'type': 'integer', 'minimum': 32, 'maximum': 2048}}},
        ['version', 'sceneFile', 'cameras'])
