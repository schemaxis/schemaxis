"""Typed AOV taps compiled into closed, owner-local shader extensions.

Public production routes compile descriptors from trusted normalized intent,
never a saved native tag or readback.
"""
import copy
import hashlib

from schemaxis.core.declarations import validate_arguments
from schemaxis.errors import fail
from .node_catalogue import colour, number, integer, choice
from .node_groups import descriptor
from .spline import array, record, union, variant
from .render_bundles import ID, REFERENCE


TARGET = union([
    variant('material', {'material': {**REFERENCE, 'required': True}}),
    variant('world', {'world': {**REFERENCE, 'required': True}}),
    variant('captured', {'asset': {**REFERENCE, 'required': True},
                         'sourceObject': {**REFERENCE, 'required': True},
                         'sourceSlot': {**integer(0, minimum=0, maximum=63), 'required': True}}),
])
SURFACE_CHANNELS = {
    'baseColour': ('colour', 'colour'), 'roughness': ('roughness', 'number'),
    'metallic': ('metallic', 'number'), 'ior': ('ior', 'number'),
    'coverage': ('alpha', 'number'), 'transmission': ('transmission', 'number'),
    'coat': ('coat', 'number'), 'coatRoughness': ('coatRoughness', 'number'),
    'emissionColour': ('emission', 'colour'), 'emissionStrength': ('emissionStrength', 'number'),
}
SOURCE = union([
    variant('value', {'value': {**number(), 'required': True}}),
    variant('colour', {'value': {**colour(), 'required': True}}),
    variant('attribute', {'name': {**REFERENCE, 'required': True},
                          'channel': choice('factor', ['factor', 'alpha', 'colour', 'vector']),
                          'missing': choice('error', ['error', 'zero'])}),
    variant('graphOutput', {'node': {**REFERENCE, 'required': True},
                            'socket': {**REFERENCE, 'required': True}}),
    variant('surfaceChannel', {'channel': {**choice('baseColour', list(SURFACE_CHANNELS)), 'required': True}}),
])
WRITER = record({'id': ID, 'aov': ID, 'target': TARGET, 'source': SOURCE},
                ['id', 'aov', 'target', 'source'])
OPTIONS = {'materialAovs': {**array(WRITER, 4096), 'default': []}}

# Cycles v5.2.3 Attribute::name_standard resolves these names as built-ins,
# before generic geometry attributes. A same-named Mesh field is not a reliable
# source for a scientific tap, even when the native field readback is correct.
# intern/cycles/scene/attribute.cpp:423-511; shader_nodes.cpp:5777-5786.
RESERVED_ATTRIBUTES = frozenset({
    'P', 'radius', 'N', 'uv', 'generated', 'generated_transform', 'tangent',
    'tangent_sign', 'undisplaced_tangent', 'undisplaced_tangent_sign',
    'vertex_color', 'undeformed', 'undisplaced', 'undisplaced_N', 'particle',
    'curve_intercept', 'curve_length', 'curve_random', 'point_random',
    'ptex_face_id', 'ptex_uv', 'density', 'color', 'flame', 'heat',
    'temperature', 'velocity', 'velocity_x', 'velocity_y', 'velocity_z',
    'pointiness', 'random_per_island', 'shadow_transparency',
})


def _attribute_source(source, location):
    if source['kind'] == 'attribute' and source['name'] in RESERVED_ATTRIBUTES:
        fail('RESERVED_AOV_ATTRIBUTE',
             'generic AOV field name collides with a reserved Cycles attribute',
             location + '.source.name', name=source['name'],
             recovery='Rename the stored geometry field and this source together '
                      '(for example sx_temperature); the logical AOV pass name '
                      'can stay unchanged. Rerun trusted intent into a NEW output.')


def schema_properties():
    from schemaxis.schema import arguments_schema
    return arguments_schema(OPTIONS)['properties']


def target_key(target):
    if target['kind'] == 'captured':
        return ('captured', target['asset'], target['sourceObject'], target['sourceSlot'])
    return (target['kind'], target[target['kind']])


def _compatible(kind, aov, location):
    expected = {'value': {'number', 'integer'}, 'colour': {'colour', 'vector'}}[aov['type']]
    if kind not in expected:
        fail('TYPE_MISMATCH', 'AOV tap and declared pass have different component types', location,
             observed=kind, expected=sorted(expected))


def endpoint(writer, graphs, surfaces, groups):
    """Resolve a graph tap without guessing native names or duplicating samplers."""
    target, source = writer['target'], writer['source']
    if target['kind'] != 'material':
        fail('INVALID_AOV_TAP', 'graph and artist taps require their declared material owner', writer['id'])
    graph = graphs.get(target['material'])
    if graph is None:
        fail('UNKNOWN_REFERENCE', 'AOV tap requires a declared material graph', writer['id'])
    nodes = {n['id']: n for n in graph['nodes']}
    if source['kind'] == 'graphOutput':
        node = nodes.get(source['node'])
        if node is None:
            fail('UNKNOWN_REFERENCE', 'AOV graph source node is absent', writer['id'])
        ports = descriptor(node, 'material', groups)['outputs']
        port = ports.get(source['socket'])
        if port is None:
            fail('UNKNOWN_SOCKET', 'AOV graph source port is absent', writer['id'])
        return {'kind': port['kind'], 'from': {'node': node['id'], 'socket': source['socket']}}
    if target['material'] not in surfaces:
        fail('INVALID_AOV_TAP', 'artist channel needs an artist surface material', writer['id'])
    shaders = [n for n in graph['nodes'] if n['kind'] == 'principled']
    if len(shaders) != 1:
        fail('INVALID_AOV_TAP', 'artist compiler must provide one unambiguous Principled owner', writer['id'])
    key, kind = SURFACE_CHANNELS[source['channel']]
    node = shaders[0]
    links = [link['from'] for link in graph['links']
             if link['to'] == {'node': node['id'], 'socket': key}]
    if len(links) == 1:
        return {'kind': kind, 'from': copy.deepcopy(links[0])}
    if links or key not in node['values']:
        fail('INVALID_AOV_TAP', 'artist channel lacks its compiled input source', writer['id'])
    return {'kind': kind, 'value': copy.deepcopy(node['values'][key])}


def validate(value, *, aovs, materials, graphs=(), surfaces=(), groups=(), assets=(), worlds=()):
    """Validate semantic ownership before allocating or reading native owners."""
    writers = validate_arguments(OPTIONS, {'materialAovs': value}, location='production')['materialAovs']
    aovs = {a['id']: a for a in aovs}
    graphs = {g['id']: g for g in graphs}
    groups = {g['id']: g for g in groups}
    surfaces = set(surfaces)
    identities, owners = set(), set()
    from schemaxis.pipeline import name
    for writer in writers:
        location = 'production.materialAovs.' + writer['id']
        name(writer['id'], location)
        if writer['id'] in identities:
            fail('DUPLICATE_ID', 'AOV writer identities must be distinct', location)
        identities.add(writer['id'])
        aov = aovs.get(writer['aov'])
        if aov is None:
            fail('UNKNOWN_REFERENCE', 'AOV writer pass is not declared', location)
        target = writer['target']
        ref = target.get(target['kind'], target.get('asset'))
        known = {'material': materials, 'world': worlds, 'captured': assets}[target['kind']]
        if ref not in known:
            fail('UNKNOWN_REFERENCE', 'AOV writer owner is absent', location)
        key = (target_key(target), writer['aov'])
        if key in owners:
            fail('DUPLICATE_AOV_WRITER', 'one owner may write each AOV only once', location)
        owners.add(key)
        source = writer['source'];kind = source['kind']
        _attribute_source(source, location)
        if kind in ('graphOutput', 'surfaceChannel'):
            _compatible(endpoint(writer, graphs, surfaces, groups)['kind'], aov, location)
        else:
            component = 'number' if kind == 'value' or kind == 'attribute' and source['channel'] in ('factor', 'alpha') else 'colour'
            _compatible(component, aov, location)
    return writers


def extension(writer, *, graphs=(), surfaces=(), groups=()):
    """Produce expected auxiliary topology for a reviewed owner-local builder.

    The generated IDs are not persisted authorization. Callers must reject an
    actual name collision and compare the descriptor from fresh authored input.
    """
    source = writer['source'];kind = source['kind']
    _attribute_source(source, 'production.materialAovs.' + writer['id'])
    identity = 'SXAov-' + hashlib.sha256(writer['id'].encode()).hexdigest()[:24]
    sink = {'id': identity, 'kind': 'aov', 'properties': {'name': writer['aov']}, 'values': {}}
    nodes, links = [sink], []
    if kind in ('graphOutput', 'surfaceChannel'):
        value = endpoint(writer, {g['id']: g for g in graphs}, set(surfaces), {g['id']: g for g in groups})
    elif kind == 'attribute':
        attribute = {'id': identity + '-input', 'kind': 'attribute',
                     'properties': {'name': source['name']}, 'values': {}}
        nodes.append(attribute)
        value = {'kind': 'number' if source['channel'] in ('factor', 'alpha') else 'colour',
                 'from': {'node': attribute['id'], 'socket': source['channel']}}
    else:
        value = {'kind': 'number' if kind == 'value' else 'colour', 'value': copy.deepcopy(source['value'])}
    socket = 'value' if value['kind'] in ('number', 'integer') else 'colour'
    if 'from' in value:
        links.append({'from': value['from'], 'to': {'node': identity, 'socket': socket}})
    else:
        sink['values'][socket] = value['value']
    return {'nodes': nodes, 'links': links,
            'requiredAttribute': source['name'] if kind == 'attribute' and source['missing'] == 'error' else None}


def planned_cost(writers):
    """Conservative generated allocation; group expansion is charged separately."""
    return sum(1 + (w['source']['kind'] == 'attribute') for w in writers)


def bind_owner_graphs(writers, owners, graphs):
    """Bind logical graph intent to actual fresh owners, never display names.

    A native import can occupy an authored graph's preferred material name.
    Blender may suffix the new material, so owner.name cannot identify intent.
    """
    graphs = {graph['id']: graph for graph in graphs}
    result = {}
    for writer in writers:
        target = writer['target'];owner = owners[writer['id']]
        graph = graphs.get(target['material']) if target['kind'] == 'material' else None
        if writer['source']['kind'] in ('graphOutput', 'surfaceChannel') and graph is None:
            fail('UNKNOWN_REFERENCE', 'AOV tap lacks its logical compiled material graph', writer['id'])
        if owner in result and result[owner] != graph:
            fail('AMBIGUOUS_AOV_OWNER', 'one actual shader owner cannot represent conflicting logical graph bindings', writer['id'])
        result[owner] = graph
    return result
