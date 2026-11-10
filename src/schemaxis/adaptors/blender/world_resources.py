"""Reusable constant/HDRI World intent for the render-bundle family.

Public production uses finite constructors, full shader authority and managed
resources. Procedural skies and World volumes remain unfinished variants.
"""
from schemaxis.core.declarations import validate_arguments
from schemaxis.errors import fail
from schemaxis.pipeline import name
from schemaxis.schema import arguments_schema
from .node_specs import number, integer, vector, boolean, choice, text
from .spline import array, record, settings, union, variant
from .render_bundles import ID, REFERENCE


RGB = {'type': 'array', 'items': {'type': 'number', 'minimum': 0, 'maximum': 1},
       'minItems': 3, 'maxItems': 3, 'default': [.05, .05, .05]}
LIGHTING = union([
    variant('colour', {'colour': RGB, 'strength': number(1, minimum=0, maximum=1000000)}),
    variant('environment', {'image': {**REFERENCE, 'required': True},
                            'strength': number(1, minimum=0, maximum=1000000),
                            'rotation': vector(),
                            'projection': choice('equirectangular', ['equirectangular', 'mirrorBall']),
                            'interpolation': choice('linear', ['nearest', 'linear', 'cubic'])}),
])
LIGHTING['default'] = validate_arguments({'lighting': LIGHTING}, {'lighting': {'kind': 'colour'}})['lighting']
VISIBILITY = settings({key: boolean(True) for key in ('camera', 'diffuse', 'glossy', 'transmission', 'shadow', 'scatter')})
MIST = union([
    variant('none', {}),
    variant('distance', {'start': number(5, minimum=0, maximum=1000000000),
                         'depth': number(25, minimum=.000001, maximum=1000000000),
                         'height': number(0, minimum=0, maximum=100),
                         'falloff': choice('quadratic', ['quadratic', 'linear', 'inverseQuadratic'])}),
])
MIST['default'] = {'kind': 'none'}
WORLD = record({'id': ID, 'lighting': LIGHTING, 'visibility': VISIBILITY, 'mist': MIST,
                'sampling': choice('automatic', ['automatic', 'manual', 'none']),
                'samplingResolution': integer(1024, minimum=4, maximum=8192)}, ['id'])
OPTIONS = {'worlds': {**array(WORLD, 32), 'default': []}, 'sceneWorld': text()}


def schema_properties():
    return arguments_schema(OPTIONS)['properties']


def validate(value, *, images, scene_world=''):
    worlds = validate_arguments(OPTIONS, {'worlds': value}, location='production')['worlds']
    identities = set();working = 0
    for world in worlds:
        location = 'production.worlds.' + world['id'];name(world['id'], location)
        if world['id'] in identities:fail('DUPLICATE_ID', 'World resource IDs must be distinct', location)
        identities.add(world['id']);lighting = world['lighting']
        if lighting['kind'] == 'environment' and lighting['image'] not in images:
            fail('UNKNOWN_REFERENCE', 'World environment requires a declared captured image', location)
        # Conservative importance-map working storage for every declared World,
        # including overrides; referenced image decode has its shared own bound.
        if world['sampling'] != 'none':
            resolution = world['samplingResolution'];working += resolution * ((resolution + 1)//2) * 8
    if working > 256 * 1024 * 1024:
        fail('RESOURCE_BUDGET_EXCEEDED', 'World importance maps exceed 256 MiB aggregate',
             'production.worlds', estimatedBytes=working)
    if scene_world and scene_world not in identities:
        fail('UNKNOWN_REFERENCE', 'scene World resource is absent', 'production.sceneWorld')
    return worlds


def validate_engine(worlds, engine):
    if worlds and engine == 'workbench':
        fail('UNSUPPORTED_RENDER_WORLD', 'World illumination resources require Cycles or EEVEE')
    if engine != 'cycles':
        for world in worlds:
            if not all(world['visibility'].values()):
                fail('UNSUPPORTED_RENDER_WORLD', 'per-ray World visibility requires Cycles', world['id'])
