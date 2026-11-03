# Copyright (C) 2026 David L F Gaden
"""Host-safe Godot declarations, bounded process execution and receipt verification."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import time

from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.core.runners import Interpreter
from schemaxis.artifacts import atomic_json
from schemaxis.dispatch import SubprocessRunner, cancellation_requested
from schemaxis.errors import keys
from .errors import fault
from . import gltf
from .scripts import WORKER, ORBIT, PROJECT


def number(default, low, high):
    return {'type': 'number', 'minimum': low, 'maximum': high, 'default': default}


def vector(default, low=-100000, high=100000):
    return {'type': 'array', 'items': {'type': 'number', 'minimum': low, 'maximum': high},
            'minItems': len(default), 'maxItems': len(default), 'default': default}


def declaration(native, kind, options, inputs=None):
    return {'native': native, 'kinds': [kind], 'options': {k: {'value': v} for k, v in options.items()},
            'inputs': inputs or {}}


POSITION = vector([0, 0, 0])
PARENT = {'parent': {'required': False, 'kind': 'group'}}
MATERIAL = {'material': {'required': True, 'kind': 'material'}}
DECLARATIONS = {
    'material': declaration('StandardMaterial3D', 'material', {
        'colour': vector([0.3, 0.6, 0.9], 0, 1), 'roughness': number(0.6, 0, 1), 'metallic': number(0, 0, 1)}),
    'box': declaration('BoxMesh', 'geometry', {'position': POSITION, 'size': vector([1, 1, 1], 0.001, 10000)}, MATERIAL),
    'sphere': declaration('SphereMesh', 'geometry', {'position': POSITION, 'radius': number(0.5, 0.001, 10000)}, MATERIAL),
    'cylinder': declaration('CylinderMesh', 'geometry', {'position': POSITION, 'radius': number(0.5, 0.001, 10000),
                                                      'height': number(1, 0.001, 10000)}, MATERIAL),
    'plane': declaration('PlaneMesh', 'geometry', {'position': POSITION, 'size': vector([10, 10], 0.001, 10000)}, MATERIAL),
    'readGLTF': declaration('GLTFDocument', 'geometry', {'position': POSITION,
        'file': {'type': 'string', 'required': True, 'minLength': 1, 'maxLength': 4096}}, MATERIAL),
    'sprite3D': declaration('Sprite3D', 'image', {'position': POSITION,
        'file': {'type': 'string', 'required': True, 'minLength': 1, 'maxLength': 4096},
        'pixelSize': number(0.01, 0.00001, 10)}),
    'camera': declaration('Camera3D', 'camera', {'position': vector([5, 4, 7]), 'target': POSITION,
        'fov': number(55, 10, 120), 'near': number(0.05, 0.001, 100), 'far': number(1000, 1, 100000),
        'orbit': {'type': 'boolean', 'default': True}}),
    'directionalLight': declaration('DirectionalLight3D', 'light', {
        'rotation': vector([-45, -30, 0], -180, 180), 'colour': vector([1, 1, 1], 0, 1),
        'energy': number(1, 0, 16)}),
}


DECLARATIONS.update({
    'capsule': declaration('CapsuleMesh', 'geometry', {'position': POSITION,
        'radius': number(0.5, 0.001, 10000), 'height': number(2, 0.002, 10000)}, MATERIAL),
    'torus': declaration('TorusMesh', 'geometry', {'position': POSITION,
        'innerRadius': number(0.5, 0.001, 10000), 'outerRadius': number(1, 0.002, 10000)}, MATERIAL),
    'omniLight': declaration('OmniLight3D', 'light', {'position': POSITION,
        'colour': vector([1, 1, 1], 0, 1), 'energy': number(1, 0, 16),
        'range': number(5, 0.001, 100000), 'attenuation': number(1, 0.001, 16),
        'shadows': {'type': 'boolean', 'default': False}}),
    'spotLight': declaration('SpotLight3D', 'light', {'position': POSITION,
        'rotation': vector([0, 0, 0], -180, 180), 'colour': vector([1, 1, 1], 0, 1),
        'energy': number(1, 0, 16), 'range': number(5, 0.001, 100000),
        'attenuation': number(1, 0.001, 16), 'angle': number(45, 1, 89),
        'angleAttenuation': number(1, 0.001, 16), 'shadows': {'type': 'boolean', 'default': False}}),
})
DECLARATIONS['transformGroup'] = declaration('Node3D', 'group', {'position': POSITION,
    'rotation': vector([0, 0, 0], -180, 180),
    'scale': vector([1, 1, 1], 0.001, 1000)}, PARENT)
for definition in DECLARATIONS.values():
    if definition['kinds'] == ['geometry']:
        definition['inputs'] = {**definition['inputs'], **PARENT}
        definition['options'].update(rotation={'value': vector([0, 0, 0], -180, 180)},
                                     scale={'value': vector([1, 1, 1], 0.001, 1000)})


def transformed(point, options):
    """Godot's intrinsic YXZ Euler order: scale, Z, X, Y, translation."""
    x, y, z = [v*s for v, s in zip(point, options.get('scale', [1, 1, 1]))]
    rx, ry, rz = map(math.radians, options.get('rotation', [0, 0, 0]))
    x, y = math.cos(rz)*x-math.sin(rz)*y, math.sin(rz)*x+math.cos(rz)*y
    y, z = math.cos(rx)*y-math.sin(rx)*z, math.sin(rx)*y+math.cos(rx)*z
    x, z = math.cos(ry)*x+math.sin(ry)*z, -math.sin(ry)*x+math.cos(ry)*z
    return [v+p for v, p in zip((x, y, z), options['position'])]


def expected_basis(options):
    origin = transformed([0, 0, 0], options)
    return [[v-p for v, p in zip(transformed(point, options), origin)]
            for point in ([1, 0, 0], [0, 1, 0], [0, 0, 1])]


def world_point(point, node, nodes):
    """Compose full affine transforms, never decompose the resulting shear."""
    point = transformed(point, node['options'])
    parent = node.get('inputs', {}).get('parent')
    return world_point(point, nodes[parent], nodes) if parent else point


def world_transform(node, nodes):
    # Use zero translations for basis columns: avoid cancellation at large origins.
    origin = world_point([0, 0, 0], node, nodes)
    basis = expected_basis({**node['options'], 'position': [0, 0, 0]})
    parent = node.get('inputs', {}).get('parent')
    while parent:
        ancestor = nodes[parent]
        options = {**ancestor['options'], 'position': [0, 0, 0]}
        basis = [transformed(column, options) for column in basis]
        parent = ancestor.get('inputs', {}).get('parent')
    return origin, basis


def order_hierarchy(prepared):
    """Stable dependency traversal; flat documents retain their original order."""
    nodes = {n['id']: n for n in prepared}
    locations = {n['id']: f'$.nodes[{i}].inputs.parent' for i, n in enumerate(prepared)}
    for node in prepared:
        if 'parent' not in node['inputs']:
            continue
        parent = node['inputs']['parent']
        if not isinstance(parent, str) or parent not in nodes:
            fault('INVALID_DEPENDENCY', 'Parent must name a declared transformGroup.', locations[node['id']],
                  'Declare the group and use its exact id, or omit parent for the scene root.')
        if nodes[parent]['filter'] != 'transformGroup':
            fault('TYPE_MISMATCH', 'Parent must be a transformGroup, not geometry or a resource.', locations[node['id']])
    ordered, active, visited = [], set(), set()
    def visit(node):
        identity = node['id']
        if identity in active:
            fault('DEPENDENCY_CYCLE', 'Transform parent links form a cycle.', locations[identity],
                  'Remove a parent link so every group eventually reaches the scene root.')
        if identity in visited:
            return
        active.add(identity)
        for source in node['inputs'].values():
            visit(nodes[source])
        active.remove(identity)
        visited.add(identity)
        ordered.append(node)
    for node in prepared:
        visit(node)
    for node in ordered:
        if 'parent' not in node['inputs']:
            continue
        ancestor, depth = node, 0
        while ancestor['inputs'].get('parent'):
            depth += 1
            ancestor = nodes[ancestor['inputs']['parent']]
        origin, basis = world_transform(node, nodes)
        if depth > 16 or max(map(abs, origin)) > 1000000 or any(
                not 0.000001 <= math.hypot(*column) <= 10000 for column in basis):
            fault('RESOURCE_LIMIT', 'Hierarchy exceeds 16 parent links, 1000000 m world position or world basis lengths [0.000001, 10000].',
                  locations[node['id']], 'Reduce nesting, ancestor offsets or accumulated scaling.')
    return ordered


def group_bounds(identity, nodes, sources):
    bounds = []
    for node in nodes.values():
        if DECLARATIONS[node['filter']]['kinds'] != ['geometry']:
            continue
        parent = node['inputs'].get('parent')
        while parent:
            if parent == identity:
                bounds.append(expected_bounds(node, sources, nodes))
                break
            parent = nodes[parent]['inputs'].get('parent')
    return ([min(b[i] for b in bounds) for i in range(3)] +
            [max(b[i] for b in bounds) for i in range(3, 6)]) if bounds else None


def plan(document):
    document = copy.deepcopy(document)
    keys(document, ('version', 'units', 'nodes', 'preview'), '$')
    if 'preview' in document and type(document['preview']) is not bool:
        fault('INVALID_ARGUMENT', 'preview must be a Boolean.', '$.preview')
    if document.get('version') != 'schemaxis.godot/1':
        fault('UNSUPPORTED_VERSION', 'Expected schemaxis.godot/1.')
    if document.get('units', 'm') != 'm':
        fault('UNSUPPORTED_UNITS', 'Godot scenes use metres.')
    nodes = document.get('nodes')
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 128:
        fault('INVALID_DOCUMENT', 'Provide 1 to 128 declared nodes.', '$.nodes')
    prepared, kinds = [], {}
    for i, node in enumerate(nodes):
        location = f'$.nodes[{i}]'
        keys(node, ('id', 'filter', 'options', 'inputs'), location)
        identity = node.get('id')
        if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', identity):
            fault('INVALID_NAME', 'Node ids must be ASCII identifiers of at most 64 characters.', location+'.id')
        if identity in kinds:
            fault('DUPLICATE_NODE', 'Node id is repeated.', location+'.id')
        operation = node.get('filter')
        if not isinstance(operation, str) or operation not in DECLARATIONS:
            fault('UNKNOWN_FILTER', 'Unsupported Godot operation.', location+'.filter')
        definition = DECLARATIONS[operation]
        options = validate_arguments({k: v['value'] for k, v in definition['options'].items()},
                                     node.get('options', {}), location=location+'.options')
        inputs = node.get('inputs', {})
        keys(inputs, tuple(definition['inputs']), location+'.inputs')
        if not {p for p, spec in definition['inputs'].items() if spec.get('required')} <= set(inputs):
            fault('INVALID_DEPENDENCY', 'Supply every required input port.', location+'.inputs')
        for port, source in inputs.items():
            if port == 'parent':
                continue  # Forward group links are validated after all names are known.
            if not isinstance(source, str) or source not in kinds:
                fault('INVALID_DEPENDENCY', 'Inputs must refer to earlier nodes.', location+'.inputs.'+port)
            if kinds[source] != definition['inputs'][port]['kind']:
                fault('TYPE_MISMATCH', 'Input kind differs from the declared port.', location+'.inputs.'+port)
        if operation == 'capsule' and options['height'] < 2*options['radius']:
            fault('INVALID_ARGUMENT', 'Capsule height must be at least twice its radius.', location)
        if operation == 'torus' and options['innerRadius'] >= options['outerRadius']:
            fault('INVALID_ARGUMENT', 'Torus inner radius must be smaller than outer radius.', location)
        if operation == 'camera':
            delta = [a-b for a, b in zip(options['position'], options['target'])]
            if math.hypot(delta[0], delta[2]) < 0.001 or not 0.01 <= math.hypot(*delta) <= 100000:
                fault('INVALID_ARGUMENT', 'Camera must be separated from its target and not parallel to the Y up axis.', location)
            if options['near'] >= options['far']:
                fault('INVALID_ARGUMENT', 'Camera near must be less than far.', location)
        if operation == 'readGLTF' and (not Path(options['file']).is_absolute() or (Path(options['file']).suffix.lower() != '.gltf' and options['file'].startswith('/unresolved-artifact') is False)):
            fault('UNSUPPORTED_RESOURCE', 'readGLTF requires an absolute .gltf path; GLB is not supported.', location)
        if operation == 'sprite3D' and not Path(options['file']).is_absolute():
            fault('UNSUPPORTED_RESOURCE', 'sprite3D requires an absolute PNG path.', location)
        kinds[identity] = definition['kinds'][0]
        prepared.append({'id': identity, 'filter': operation, 'options': options, 'inputs': inputs})
    if list(kinds.values()).count('camera') != 1 or not any(k in ('geometry', 'image') for k in kinds.values()):
        fault('INVALID_SELECTION', 'Declare exactly one camera and at least one geometry node.')
    prepared = order_hierarchy(prepared)
    used = {source for n in prepared for source in n['inputs'].values()}
    if any(kind == 'material' and identity not in used for identity, kind in kinds.items()):
        fault('INVALID_SELECTION', 'Every material must be used by geometry so it can be saved and verified.')
    return {'version': 'schemaxis.godot.plan/1', 'units': 'm', 'nodes': prepared,
            **({'preview': document['preview']} if 'preview' in document else {}),
            'expectedNodeCount': 1 + sum(kind != 'material' for kind in kinds.values()),
            'expectedPublications': 3 if document.get('preview', False) else 2}


def schema():
    from schemaxis.schema import object_schema, argument_schema, DRAFT
    alternatives = []
    for operation, definition in DECLARATIONS.items():
        alternatives.append(object_schema({
            'id': {'type': 'string', 'pattern': '^[A-Za-z][A-Za-z0-9_]{0,63}$'}, 'filter': {'const': operation},
            'options': object_schema({k: argument_schema(v['value']) for k, v in definition['options'].items()},
                                     [k for k, v in definition['options'].items() if v['value'].get('required')]),
            'inputs': object_schema({k: {'type': 'string'} for k in definition['inputs']}, [k for k, spec in definition['inputs'].items() if spec.get('required')])},
            ['id', 'filter'] + (['inputs'] if any(s.get('required') for s in definition['inputs'].values()) else []) + (['options'] if operation in ('readGLTF', 'sprite3D') else [])))
    return {'$schema': DRAFT, **object_schema({'version': {'const': 'schemaxis.godot/1'}, 'units': {'const': 'm'},
        'preview': {'type': 'boolean', 'default': False},
        'nodes': {'type': 'array', 'minItems': 1, 'maxItems': 128, 'items': {'oneOf': alternatives}}}, ['version', 'nodes'])}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as error:
        fault('INCOMPLETE_EXECUTION', 'Missing or invalid evidence: '+str(error), str(path), 'Run the complete adaptor in a fresh directory.')


def close(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(close(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(close(x, y) for x, y in zip(a, b))
    if type(a) in (int, float) and type(b) in (int, float):
        return math.isfinite(a) and math.isfinite(b) and math.isclose(a, b, rel_tol=1e-5, abs_tol=1e-5)
    return type(a) is type(b) and a == b


def expected_bounds(node, sources, nodes=None):
    options, operation = node['options'], node['filter']
    if operation == 'readGLTF':
        local = sources[node['id']]['bounds']
    else:
        if operation == 'box':
            size = options['size']
        elif operation == 'torus':
            size = [2*options['outerRadius'], options['outerRadius']-options['innerRadius'], 2*options['outerRadius']]
        elif operation == 'plane':
            size = [options['size'][0], 0, options['size'][1]]
        else:
            diameter = 2 * options['radius']
            size = [diameter, options.get('height', diameter), diameter]
        local = [-x/2 for x in size] + [x/2 for x in size]
    from itertools import product
    points = [world_point(point, node, nodes or {}) for point in product(*[(local[i], local[i+3]) for i in range(3)])]
    return [operation(point[i] for point in points) for operation in (min, max) for i in range(3)]


def verify(directory, require_result=True):
    """Validate retained native evidence and artifacts, without launching Godot."""
    try:
        return _verify(directory, require_result)
    except SchemaxisError:
        raise
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError) as error:
        fault('VERIFICATION_FAILED', 'Malformed or unavailable evidence: '+str(error), str(directory),
              'Preserve the evidence and rerun the adaptor in a fresh directory.')


def _verify(directory, require_result=True):
    """Offline integrity/readback verification; run() performs the fresh native reopen."""
    directory = Path(directory).absolute()
    prepared = plan(read_json(directory/'authored.json'))
    def check(condition, message):
        if not condition:
            fault('VERIFICATION_FAILED', message, str(directory), 'Preserve this evidence and rerun in a fresh directory.')
    check(read_json(directory/'plan.json') == prepared, 'Plan differs from authored document.')
    result = read_json(directory/'result.json')
    if require_result:
        check(result.get('verified') is True and result.get('status') == 'succeeded', 'Execution did not complete.')
    sources = read_json(directory/'sources.json')
    imports = [n for n in prepared['nodes'] if n['filter'] in ('readGLTF', 'sprite3D')]
    check(set(sources) == {n['id'] for n in imports}, 'Imported source membership differs.')
    for node in imports:
        source = sources[node['id']]
        retained = directory/('source_'+node['id']+('.png' if node['filter'] == 'sprite3D' else '.gltf'))
        check(not retained.is_symlink() and retained.is_file(), 'Retained glTF is absent or escaped.')
        check(source['sha256'] == digest(retained) and source['file'] == node['options']['file'], 'glTF provenance differs.')
        measured = image_info(retained.read_bytes()) if node['filter'] == 'sprite3D' else gltf.inspect(retained.read_bytes())
        check(close(measured, {k: source[k] for k in measured}), 'Source measures differ.')
    built, receipt = read_json(directory/'built.json'), read_json(directory/'reopened.json')
    check(built.get('stage') == 'build' and receipt.get('stage') == 'reopen' and
          type(built.get('pid')) is int and type(receipt.get('pid')) is int and built['pid'] != receipt['pid'],
          'Fresh-process evidence is incomplete.')
    check(built.get('definition') == prepared and receipt.get('definition') == prepared, 'Native definition differs.')
    check(isinstance(receipt.get('runtime'), str) and receipt['runtime'].startswith('4.') and
          built.get('runtime') == receipt['runtime'], 'Runtime evidence differs.')
    check(close(built.get('scene'), receipt.get('scene')), 'Saved scene differs after native reopening.')
    scene = receipt.get('scene', {})
    check(scene.get('nodeCount') == prepared['expectedNodeCount'], 'Native node count differs.')
    nodes = {n['id']: n for n in prepared['nodes']}
    observed = scene.get('nodes', {})
    check(set(observed) == {n['id'] for n in prepared['nodes'] if n['filter'] != 'material'}, 'Native scene membership differs.')
    for identity, record in observed.items():
        node = nodes[identity]; options = node['options']; operation = node['filter']
        check(record.get('owned') is True and record.get('owner') == '.', 'Node ownership differs: '+identity)
        check(record.get('parent') == node['inputs'].get('parent'), 'Node parent differs: '+identity)
        if operation == 'transformGroup' or DECLARATIONS[operation]['kinds'] == ['geometry']:
            origin, basis = world_transform(node, nodes)
            check(close(record.get('worldPosition'), origin) and close(record.get('worldBasis'), basis),
                  'Global transform differs: '+identity)
            check(record.get('topLevel') is False, 'Transform inheritance differs: '+identity)
        if operation == 'transformGroup':
            check(record.get('class') == 'Node3D' and close(record.get('position'), options['position'])
                  and close(record.get('basis'), expected_basis(options)), 'Group local transform differs: '+identity)
            check(close(record.get('bounds'), group_bounds(identity, nodes, sources)), 'Group bounds differ: '+identity)
            continue
        if DECLARATIONS[operation]['kinds'] == ['geometry']:
            check(record.get('class') == 'MeshInstance3D' and record.get('mesh') ==
                  ('ArrayMesh' if operation == 'readGLTF' else DECLARATIONS[operation]['native']), 'Mesh type differs: '+identity)
            check(close(record.get('position'), options['position']) and close(record.get('bounds'), expected_bounds(node, sources, nodes)), 'Geometry bounds differ: '+identity)
            check(close(record.get('basis'), expected_basis(options)), 'Geometry transform differs: '+identity)
            check(close(record.get('material'), nodes[node['inputs']['material']]['options']), 'Material readback differs: '+identity)
            if operation == 'readGLTF':
                check(record.get('triangles') == sources[identity]['triangles'], 'Imported triangle count differs.')
            else:
                if operation in ('box', 'plane'):
                    parameters = {'size': options['size']}
                elif operation == 'torus':
                    parameters = {'innerRadius': options['innerRadius'], 'outerRadius': options['outerRadius'], 'rings': 32, 'ringSegments': 16}
                elif operation in ('sphere', 'capsule'):
                    parameters = {'radius': options['radius'], 'height': options.get('height', 2*options['radius']),
                                  'radialSegments': 32, 'rings': 15 if operation == 'sphere' else 8}
                else:
                    parameters = {'topRadius': options['radius'], 'bottomRadius': options['radius'],
                                  'height': options['height'], 'radialSegments': 32, 'rings': 1}
                check(close(record.get('parameters'), parameters), 'Native primitive parameters differ: '+identity)
                expected_triangles = {'box': 12, 'plane': 2, 'sphere': 1024, 'cylinder': 192, 'torus': 1024, 'capsule': 1728}
                check(record.get('triangles') == expected_triangles[operation], 'Native primitive tessellation differs: '+identity)
        elif operation == 'sprite3D':
            check(record.get('class') == 'Sprite3D' and close(record.get('position'), options['position'])
                  and close(record.get('pixelSize'), options['pixelSize'])
                  and record.get('image') == {k: sources[identity][k] for k in ('width', 'height', 'rgbaSHA256')},
                  'Sprite texture readback differs: '+identity)
        elif operation == 'camera':
            delta = [b-a for a, b in zip(options['position'], options['target'])]
            direction = [x/math.hypot(*delta) for x in delta]
            check(record.get('class') == 'Camera3D' and record.get('current') is True and
                  close(record.get('position'), options['position']) and close(record.get('forward'), direction), 'Camera pose differs.')
            for field in ('fov', 'near', 'far', 'orbit'):
                check(close(record.get(field), options[field]), 'Camera setting differs: '+field)
            check(close(record.get('target'), options['target']), 'Orbit target differs.')
        else:
            check(record.get('class') == DECLARATIONS[operation]['native'] and close(record.get('settings'), options), 'Light readback differs.')
    manifest = read_json(directory/'artifacts.json')
    names = ['project.godot', 'scene.tscn', 'orbit.gd', 'worker.gd'] + ['source_'+n['id']+('.png' if n['filter'] == 'sprite3D' else '.gltf') for n in imports]
    if prepared.get('preview'):
        names.append('preview.png')
        render = read_json(directory/'rendered.json')
        check(render.get('stage') == 'render' and render.get('pid') not in (built['pid'], receipt['pid'])
              and type(render.get('pid')) is int and render.get('definition') == prepared
              and render.get('runtime') == receipt['runtime'] and close(render.get('scene'), scene),
              'Rendered scene differs from verified scene.')
        image = render.get('image', {})
        check(image.get('size') == [640, 480] and image.get('reloaded') is True
              and image.get('display') == 'X11' and image.get('frames') == 3
              and isinstance(image.get('renderer'), str) and bool(image['renderer'])
              and image.get('sha256') == digest(directory/'preview.png'), 'Graphical PNG evidence differs.')
        from .preview import inspect_png
        check(inspect_png((directory/'preview.png').read_bytes()) == [640, 480], 'PNG dimensions differ.')
    check(isinstance(manifest, dict) and set(manifest) == set(names), 'Artifact membership differs.')
    for filename in names:
        path = directory/filename
        check(path.is_file() and not path.is_symlink() and digest(path) == manifest[filename], 'Artifact changed: '+filename)
    check((directory/'orbit.gd').read_text() == ORBIT and (directory/'worker.gd').read_text() == WORKER
          and (directory/'project.godot').read_text() == PROJECT, 'Trusted generated assets differ.')
    check(read_json(directory/'verification.json') == {'artifacts': artifact_manifest(directory, prepared)}, 'Workflow publication manifest differs.')
    return {'verified': True, 'artifacts': prepared['expectedPublications'], 'nodeCount': scene['nodeCount'], 'runtime': receipt['runtime'],
            **({'preview': str(directory/'preview.png')} if prepared.get('preview') else {}),
            'project': str(directory/'project.godot'), 'scene': str(directory/'scene.tscn')}


def run(document, directory, executable=None, timeout=120):
    prepared = plan(document)
    executable = executable or os.environ.get('GODOT_EXECUTABLE')
    if not executable or not Path(executable).is_absolute() or not Path(executable).is_file() or not os.access(executable, os.X_OK):
        fault('INTERPRETER_NOT_FOUND', 'Provide an absolute Godot 4 executable.', '$.executable', 'Set executable or GODOT_EXECUTABLE to Godot 4.')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0 or timeout > 3600:
        fault('INVALID_ARGUMENT', 'Timeout must be finite and in (0, 3600] seconds.', '$.timeout')
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink():
        fault('OUTPUT_EXISTS', 'Output directory already exists.', str(directory), 'Choose a new output directory.')
    sources, captured = {}, {}
    for node in prepared['nodes']:
        if node['filter'] in ('readGLTF', 'sprite3D'):
            path = Path(node['options']['file'])
            try:
                with path.open('rb') as stream:
                    data = stream.read(gltf.MAX_BYTES+1)
            except OSError as error:
                fault('RESOURCE_NOT_FOUND', str(error), str(path), 'Provide a readable glTF or PNG file.')
            measured = image_info(data) if node['filter'] == 'sprite3D' else gltf.inspect(data)
            sources[node['id']] = {**measured, 'file': str(path), 'sha256': hashlib.sha256(data).hexdigest()}
            captured['source_'+node['id']+('.png' if node['filter'] == 'sprite3D' else '.gltf')] = data
            if sum(len(value) for value in captured.values()) > 32 * 1024 * 1024:
                fault('RESOURCE_LIMIT', 'Combined glTF and PNG inputs exceed 32 MiB.', '$.nodes', 'Reduce imported geometry or sprite images.')
    try:
        directory.mkdir(parents=True)
    except OSError as error:
        fault('OUTPUT_UNAVAILABLE', str(error), str(directory), 'Choose a writable fresh output directory.')
    try:
        atomic_json(directory/'result.json', {'status': 'incomplete', 'verified': False})
        atomic_json(directory/'authored.json', document)
        atomic_json(directory/'plan.json', prepared)
        atomic_json(directory/'sources.json', sources)
        for filename, data in captured.items():
            (directory/filename).write_bytes(data)
        for filename, content in [('project.godot', PROJECT), ('worker.gd', WORKER), ('orbit.gd', ORBIT)]:
            (directory/filename).write_text(content)
        deadline = time.monotonic() + timeout
        for stage in ('build', 'reopen') + (('render',) if prepared.get('preview') else ()):
            command = [str(executable), '--headless', '--path', str(directory), '--script', 'res://worker.gd', '--', stage]
            environment = None
            if stage == 'render':
                command, environment = render_command(executable, directory)
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                fault('RUNNER_TIMED_OUT', 'Godot exhausted the total execution timeout before '+stage+'.', stage,
                      'Inspect stage logs and increase the total timeout.')
            stage_error = None
            try:
                dispatch_stage(command, directory, stage, remaining, environment)
            except SchemaxisError as error:
                if error.fault.code in ('RUNNER_CANCELLED', 'RUNNER_TIMED_OUT'):
                    raise
                stage_error = error
            native_fault = directory/'native-fault.json'
            if native_fault.exists():
                report = read_json(native_fault)
                fault(report['code'], report['message'], report.get('location', stage), 'Inspect native logs and correct the scene or input geometry.')
            if stage_error is not None:
                raise stage_error
            log_text = (directory/(stage+'.log')).read_text(errors='replace')
            if 'SCRIPT ERROR:' in log_text or 'ERROR:' in log_text:
                fault('NATIVE_EXECUTION_FAILED', 'Godot failed; inspect '+stage+'.log.', stage, 'Correct native errors before retrying.')
        names = ['project.godot', 'scene.tscn', 'orbit.gd', 'worker.gd'] + list(captured)
        if prepared.get('preview'):
            names.append('preview.png')
        atomic_json(directory/'artifacts.json', {n: digest(directory/n) for n in names})
        atomic_json(directory/'verification.json', {'artifacts': artifact_manifest(directory, prepared)})
        result = verify(directory, require_result=False)
        if cancellation_requested():
            fault('RUNNER_CANCELLED', 'Execution cancelled before publishing the result.', str(directory), 'Run again when ready.')
        result['status'] = 'succeeded'
        atomic_json(directory/'result.json', result)
        return result
    except Exception as error:
        if not isinstance(error, SchemaxisError):
            try:
                fault('NATIVE_EXECUTION_FAILED', str(error), str(directory), 'Inspect retained logs and rerun in a fresh directory.')
            except SchemaxisError as wrapped:
                error = wrapped
        atomic_json(directory/'result.json', {'status': 'failed', 'verified': False, 'fault': error.fault.to_dict()})
        raise error


def render_command(executable, directory):
    """Return bounded graphical command/environment for the shared dispatcher."""
    xvfb = shutil.which('xvfb-run')
    if not xvfb:
        fault('PREVIEW_UNAVAILABLE', 'PNG preview requires xvfb-run and an X11/OpenGL Godot build.', '$.preview',
              'Install Xvfb and Mesa software OpenGL, or set preview to false.')
    command = [xvfb, '-a', '-s', '-screen 0 640x480x24', str(executable), '--display-driver', 'x11',
               '--rendering-method', 'gl_compatibility', '--rendering-driver', 'opengl3',
               '--audio-driver', 'Dummy', '--resolution', '640x480', '--path', str(directory),
               '--script', 'res://worker.gd', '--', 'render']
    return command, {'LIBGL_ALWAYS_SOFTWARE': '1', 'LP_NUM_THREADS': '2'}


def dispatch_stage(command, directory, stage, timeout, environment=None):
    """Exec fixed native argv through the shared Python replay dispatcher.

    exec preserves the tracked PID/session. The dispatcher owns cancellation,
    timeout, allocation hints and descendant cleanup, including xvfb-run children.
    No authored source is executed; argv strings are Python literals, never shell.
    """
    directory = Path(directory)
    source = 'import os\ncommand = '+repr(command)+'\nos.execvpe(command[0], command, os.environ)\n'
    workspace = directory/'.dispatch'/stage
    script = workspace/('replay-'+hashlib.sha256(source.encode()).hexdigest()[:16]+'.py')
    runner = SubprocessRunner(Interpreter('godot', sys.executable), workspace,
                              timeout=timeout, environment=environment)
    try:
        report = runner(source)
        atomic_json(directory/(stage+'-submission.json'), {**report.to_dict(), 'nativeCommand': command})
        return report
    finally:
        # Keep stage logs while retaining full dispatcher logs and metrics.
        texts = [p.read_text(errors='replace') for p in
                 (script.with_suffix('.stdout.log'), script.with_suffix('.stderr.log')) if p.is_file()]
        (directory/(stage+'.log')).write_text('\n'.join(texts))


def artifact_manifest(directory, prepared):
    names = [('project.godot', 'project'), ('scene.tscn', 'scene')]
    if prepared.get('preview'):
        names.append(('preview.png', 'image'))
    return [{'file': str(directory/name), 'kind': kind, 'sha256': digest(directory/name)} for name, kind in names]


def image_info(data):
    from schemaxis.png import decode
    width, height, pixels = decode(data)
    return {'width': width, 'height': height, 'rgbaSHA256': hashlib.sha256(pixels).hexdigest()}


# Shared authored-input, analytic-visit and verification boundary.
from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
