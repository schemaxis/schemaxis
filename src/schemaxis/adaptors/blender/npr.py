"""Finite Freestyle intent using logical scene identities, without bpy imports.

The finite public production route validates, constructs and freshly verifies it.
Freestyle is not Grease Pencil Line Art; that stroke-data workflow remains open.
"""
import copy
import math

from schemaxis.core.declarations import validate_arguments
from schemaxis.errors import fail
from schemaxis.pipeline import name
from schemaxis.schema import arguments_schema
from .node_catalogue import boolean, choice, colour, integer, number
from .spline import array, record, union, variant


VERSION = 'schemaxis.blender.freestyle/1'
ID = {'type': 'string', 'minLength': 1, 'maxLength': 48}
REFERENCE = {'type': 'string', 'minLength': 1, 'maxLength': 128}
EDGES = {'silhouette': 'silhouette', 'crease': 'crease', 'border': 'border',
         'contour': 'contour', 'externalContour': 'external_contour',
         'materialBoundary': 'material_boundary', 'edgeMark': 'edge_mark',
         'suggestiveContour': 'suggestive_contour', 'ridgeValley': 'ridge_valley'}
SCOPE = union([
    variant('all', {}),
    variant('objects', {'objects': {**array(REFERENCE, 1024, 1), 'required': True}, 'invert': boolean()}),
    variant('collection', {'collection': {**REFERENCE, 'required': True}, 'invert': boolean()}),
])
VISIBILITY = union([
    variant('visible', {}), variant('hidden', {}),
    variant('range', {'minimum': integer(0, minimum=0, maximum=64, required=True),
                      'maximum': integer(1, minimum=0, maximum=64, required=True)}),
])
STYLE = record({'id': ID, 'colour': colour((0, 0, 0, 1)),
    'colourSource': choice('constant', ['constant', 'materialLine']),
    'width': number(1, minimum=.1, maximum=64), 'caps': choice('butt', ['butt', 'round', 'square']),
    'chaining': choice('plain', ['plain', 'individual']), 'sameObject': boolean(True),
    'dash': array(record({'length': integer(1, minimum=1, maximum=1024),
                          'gap': integer(1, minimum=1, maximum=1024)}, ['length', 'gap']), 3)}, ['id'])
LINE_SET = record({'id': ID, 'style': REFERENCE,
    'edges': {**array({'type': 'enum', 'values': list(EDGES)}, 9, 1), 'required': True},
    'edgeMatch': choice('any', ['any', 'all']), 'invertEdges': boolean(),
    'visibility': {**VISIBILITY, 'required': True}, 'scope': {**SCOPE, 'required': True}}, ['id', 'style'])
LAYER = record({'layer': REFERENCE, 'creaseAngle': number(math.radians(134.43), minimum=0, maximum=math.pi),
    'culling': boolean(), 'smoothness': boolean(True),
    'lineSets': {**array(LINE_SET, 16, 1), 'required': True}}, ['layer'])
MATERIAL = record({'material': REFERENCE, 'colour': colour((0, 0, 0, 1)),
                   'priority': integer(0, minimum=0, maximum=32767)}, ['material'])
OPTIONS = {'styles': {**array(STYLE, 32, 1), 'required': True},
           'layers': {**array(LAYER, 16, 1), 'required': True},
           'materials': array(MATERIAL, 256)}


PUBLIC_EDGES = ('silhouette', 'border', 'materialBoundary')


def schema_property(*, public=True):
    schema = arguments_schema({'npr': record(OPTIONS, ['styles', 'layers'])})['properties']['npr']
    if public:
        # Restrict the public catalogue to the actually rendered finite slice.
        # The broader private compiler remains available for development proofs.
        schema = copy.deepcopy(schema)
        style = schema['properties']['styles']['items']['properties']
        style['caps']['enum'] = ['butt']; style['chaining']['enum'] = ['plain']
        style['sameObject']['const'] = True; style['dash']['maxItems'] = 1
        layer = schema['properties']['layers']['items']['properties']
        layer['culling']['const'] = False; layer['smoothness']['const'] = True
        line_set = layer['lineSets']['items']['properties']
        line_set['edges']['items']['enum'] = list(PUBLIC_EDGES)
        line_set['edges']['maxItems'] = len(PUBLIC_EDGES)
        line_set['edgeMatch']['enum'] = ['any']; line_set['invertEdges']['const'] = False
        line_set['scope']['anyOf'] = [variant for variant in line_set['scope']['anyOf']
            if variant['properties']['kind']['enum'][0] in ('objects', 'collection')]
        for variant in line_set['scope']['anyOf']:
            variant['properties']['invert']['const'] = False
    return schema


def _distinct(records, field, location):
    result = {}
    for item in records:
        identity = item[field]
        name(identity, location+'.'+identity)
        if identity in result:
            fail('DUPLICATE_ID', 'Freestyle identities must be distinct in their scope', location)
        result[identity] = item
    return result


def validate(value, *, layers, objects, collections, materials, kinds=None, where='production.npr'):
    """Resolve only logical declared references; do not trust submitted owner tags.

    Native integration supplies maps compiled from fresh authored scene intent.
    Mesh/instance geometry is checked again after evaluation in the native layer.
    """
    result = validate_arguments(OPTIONS, value, location=where)
    result.setdefault('materials', [])
    styles = _distinct(result['styles'], 'id', where+'.styles')
    declared_layers = _distinct(result['layers'], 'layer', where+'.layers')
    material_records = _distinct(result['materials'], 'material', where+'.materials')
    if set(declared_layers)-set(layers):
        fail('UNKNOWN_REFERENCE', 'Freestyle layer must be a declared logical view layer', where+'.layers')
    if set(material_records)-set(materials):
        fail('UNKNOWN_REFERENCE', 'Freestyle material must be a declared logical material', where+'.materials')
    used_styles = set()
    total_sets = total_objects = 0
    for layer in result['layers']:
        loc = where+'.layers.'+layer['layer']
        line_sets = _distinct(layer['lineSets'], 'id', loc+'.lineSets')
        total_sets += len(line_sets)
        if total_sets > 64:
            fail('RESOURCE_BUDGET_EXCEEDED', 'Freestyle exceeds sixty-four aggregate line sets', where)
        for line_set in layer['lineSets']:
            loc_set = loc+'.lineSets.'+line_set['id']
            if line_set['style'] not in styles:
                fail('UNKNOWN_REFERENCE', 'Line set style must name a declared reusable style', loc_set+'.style')
            used_styles.add(line_set['style'])
            if len(set(line_set['edges'])) != len(line_set['edges']):
                fail('DUPLICATE_ID', 'Feature edge types must be distinct', loc_set+'.edges')
            visibility = line_set['visibility']
            if visibility['kind'] == 'range' and visibility['minimum'] > visibility['maximum']:
                fail('INVALID_NPR', 'Quantitative invisibility range must increase', loc_set+'.visibility')
            scope = line_set['scope']
            if scope['kind'] == 'collection' and scope['collection'] not in collections:
                fail('UNKNOWN_REFERENCE', 'Line collection must name a declared logical collection', loc_set+'.scope')
            if scope['kind'] == 'objects':
                refs = scope['objects']
                if len(set(refs)) != len(refs):
                    fail('DUPLICATE_ID', 'Line scope object references must be distinct', loc_set+'.scope')
                if set(refs)-set(objects):
                    fail('UNKNOWN_REFERENCE', 'Line scope object is absent from declared scene intent', loc_set+'.scope')
                if kinds and any(kinds.get(ref) in ('camera', 'light', 'empty', 'rig') for ref in refs):
                    fail('TYPE_MISMATCH', 'Freestyle object scope needs faced geometry', loc_set+'.scope')
                total_objects += len(refs)
                if total_objects > 4096:
                    fail('RESOURCE_BUDGET_EXCEEDED', 'Freestyle exceeds4096 aggregate object-scope links', where)
    if set(styles) != used_styles:
        fail('INVALID_NPR', 'Every declared line style must be used by a line set', where+'.styles')
    for style in styles.values():
        style.setdefault('dash', [])
        if any(not 0 <= channel <= 1 for channel in style['colour']):
            fail('INVALID_NPR', 'Freestyle colour channels must lie in zero to one', where+'.styles.'+style['id'])
        if style['chaining'] == 'individual' and not style['sameObject']:
            fail('INVALID_NPR', 'sameObject false is meaningful only for plain chaining', where+'.styles.'+style['id'])
        if style['colourSource'] == 'materialLine' and not material_records:
            fail('INVALID_NPR', 'Material line colour needs explicit logical material line settings', where+'.materials')
    for material in material_records.values():
        if any(not 0 <= channel <= 1 for channel in material['colour']):
            fail('INVALID_NPR', 'Material line colour channels must lie in zero to one', where+'.materials')
    return {'version': VERSION, **result}


def validate_public(value, *, renderer, layers, objects, collections, materials, kinds=None,
                    where='production.npr'):
    """Return idempotent schema-valid public payload, without the private version.

    Geometry/effective-owner admission remains mandatory in the native hook.
    Cycles is the qualified raster engine; wider private catalogue is not public.
    """
    if renderer != 'cycles':
        fail('UNSUPPORTED_NPR_ENGINE', 'Public Freestyle currently requires Cycles', where)
    result = validate(value, layers=layers, objects=objects, collections=collections,
                      materials=materials, kinds=kinds, where=where)
    for style in result['styles']:
        if (style['caps'] != 'butt' or style['chaining'] != 'plain' or not style['sameObject']
                or len(style['dash']) > 1):
            fail('UNQUALIFIED_NPR_VARIANT', 'Public line styles use butt caps, plain same-object chaining and one dash/gap pair', where+'.styles')
    for layer in result['layers']:
        if layer['culling'] or not layer['smoothness']:
            fail('UNQUALIFIED_NPR_VARIANT', 'Public Freestyle keeps the qualified complete smooth view map', where+'.layers')
        for item in layer['lineSets']:
            if (set(item['edges'])-set(PUBLIC_EDGES) or item['edgeMatch'] != 'any' or item['invertEdges']
                    or item['scope']['kind'] not in ('objects', 'collection') or item['scope'].get('invert', False)):
                fail('UNQUALIFIED_NPR_VARIANT', 'Choose qualified silhouette/border/material-boundary edges and an inclusive logical object/collection scope', where+'.layers')
    result.pop('version')
    return result
