# Copyright (C) 2026 David L F Gaden
"""Bounded Blender adaptor using the shared graph, lookup and analytics engine."""
import copy
from schemaxis.core.faults import SchemaxisError
import hashlib
import json
import math
import os
from pathlib import Path
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.runners import Interpreter
from schemaxis.dispatch import SubprocessRunner
from schemaxis.errors import fail, keys
from schemaxis.pipeline import DefinitionGraph, name
from schemaxis.artifacts import atomic_json, runtime_archive

N = {'type': 'number'}
V = {'type': 'array', 'items': N, 'minItems': 3, 'maxItems': 3}


def option(value, default):
    return {'value': {**value, 'default': default}, 'path': []}


MATERIAL = {'id': 'material', 'native': 'material', 'kinds': ['material'], 'inputs': {}, 'options': {
    'colour': option({'type': 'array', 'items': {'type': 'number', 'minimum': 0, 'maximum': 1},
                      'minItems': 4, 'maxItems': 4}, [0.1, 0.4, 0.8, 1]),
}}
CUBE = {'id': 'cube', 'native': 'cube', 'inputs': {
    'material': {'native': 'material', 'kind': 'material', 'required': True}}, 'options': {
    'size': option({'type': 'number', 'minimum': 0, 'exclusiveMinimum': True}, 2),
    'centre': option(V, [0, 0, 0]),
}}
BEVEL = {'id': 'bevel', 'native': 'bevel', 'inputs': {
    'input': {'native': 'input', 'required': True}}, 'options': {
    'width': option({'type': 'number', 'minimum': 0}, 0.1),
    'segments': option({'type': 'integer', 'minimum': 1, 'maximum': 12}, 3),
}}
GLTF = {'id': 'readGltf', 'native': 'readGltf', 'inputs': {}, 'options': {
    'file': {'value': {'type': 'string', 'minLength': 1, 'required': True}, 'path': [], 'constructor': True},
}}
from schemaxis.adaptors.blender.operations import declarations as mesh_declarations
MATERIAL['options'].update({
    'roughness': option({'type': 'number', 'minimum': 0, 'maximum': 1}, .5),
    'metallic': option({'type': 'number', 'minimum': 0, 'maximum': 1}, 0),
    'transmission': option({'type': 'number', 'minimum': 0, 'maximum': 1}, 0),
    'coat': option({'type': 'number', 'minimum': 0, 'maximum': 1}, 0),
    'coatRoughness': option({'type': 'number', 'minimum': 0, 'maximum': 1}, .03),
    'emissionColour': option({'type': 'array', 'items': {'type': 'number', 'minimum': 0, 'maximum': 1}, 'minItems': 3, 'maxItems': 3}, [0, 0, 0]),
    'emissionStrength': option({'type': 'number', 'minimum': 0, 'maximum': 10000}, 0),
    'ior': option({'type': 'number', 'minimum': 1, 'maximum': 4}, 1.5),
})
DECLARATIONS = {**{d['id']: d for d in (MATERIAL, CUBE, BEVEL, GLTF)}, **mesh_declarations()}


def plan(document, declarations=None):
    keys(document, ('version', 'nodes', 'axes', 'times', 'scenes', 'maxStates', 'maxPublications', 'definitions', 'dimensions', 'views', 'settings'), '$')
    if document.get('version') != 'schemaxis.blender/1':
        fail('UNSUPPORTED_VERSION', 'expected schemaxis.blender/1')
    graph = copy.deepcopy(document)
    graph['version'] = 'schemaxis/1'
    master = DefinitionGraph(graph, declarations if declarations is not None else DECLARATIONS)
    output = master.document.get('scenes')
    if not isinstance(output, list) or len(output) != 1:
        fail('INVALID_SCENE', 'initial Blender adaptor requires one scene')
    scene = output[0]
    keys(scene, ('id', 'visible', 'images', 'render', 'prepareOnly', 'meshes'), '$.scenes')
    if type(scene.get('prepareOnly', False)) is not bool:
        fail('INVALID_SCENE', 'prepareOnly must be boolean')
    from schemaxis.adaptors.blender.settings import render_settings
    render = render_settings(scene.get('render', {}))
    name(scene.get('id'), '$.scenes.id')
    visible = scene.get('visible')
    if not isinstance(visible, list) or not visible or any(not isinstance(x, str) for x in visible):
        fail('INVALID_SCENE', 'visible must list mesh node identities')
    meshes=scene.get('meshes',[])
    if not isinstance(meshes,list) or any(not isinstance(n,str) for n in meshes) or len(set(meshes))!=len(meshes):
        fail('INVALID_PUBLICATION','meshes must list distinct mesh node identities')
    selection = master.select([*visible,*meshes])
    for node in [*visible,*meshes]:
        if master.nodes[node]['filter'] == 'material':
            fail('TYPE_MISMATCH', 'visible nodes must be meshes', node)
    images = scene.get('images')
    if not isinstance(images, list) or len(images) != 1:
        fail('INVALID_PUBLICATION', 'initial Blender adaptor requires one image writer')
    writer = images[0]
    keys(writer, ('id', 'size', 'cameras'), '$.images')
    name(writer.get('id'), '$.images.id')
    from schemaxis.camera import camera_values
    cameras = writer.get('cameras')
    if not isinstance(cameras, list) or not cameras:
        fail('INVALID_CAMERA', 'camera sequence must be nonempty')
    # Bounds, focal point and direction can query the current native observations.
    late = []
    from schemaxis.pipeline import markers
    for camera in cameras:
        late.extend(markers(camera))
        camera_values(camera, 'camera', deferred=True)
    master._check_markers(late, 'camera')
    selection = master.select(list(dict.fromkeys([*visible, *meshes, *(m['$observe'] for m in late if '$observe' in m)])))
    for marker in late:
        if '$sample' in marker:
            fail('UNSUPPORTED_EXPRESSION', 'Blender field sampling is not declared', 'camera')
        if '$observe' in marker and marker['$observe'] not in selection.order:
            fail('UNKNOWN_REFERENCE', 'camera observation must belong to the active graph', 'camera')
        if '$axis' in marker and marker['$axis'] not in selection.axes:
            fail('UNKNOWN_AXIS', 'camera references an inactive axis', 'camera')
    size = validate_arguments({'size': {'type': 'array', 'items': {'type': 'integer', 'minimum': 32, 'maximum': 2048},
                                      'minItems': 2, 'maxItems': 2, 'default': [320, 240]}},
                              {'size': writer['size']} if 'size' in writer else {})['size']
    writer['size'] = size
    for node in master.nodes.values():
        if any('$sample' in marker for marker in markers(node['options'])):
            fail('UNSUPPORTED_EXPRESSION', 'Blender field sampling is not declared', node['id'])
    maximum = master.document.get('maxPublications', 10000)
    if type(maximum) is not int or maximum < 1:
        fail('INVALID_LIMIT', 'maxPublications must be a positive integer')
    publications = selection.count * ((1 if scene.get('prepareOnly') else 1 + len(cameras)) + len(meshes))
    if publications > maximum:
        fail('EXPANSION_TOO_LARGE', 'Blender publication budget exceeded')
    _check_lathe_profiles(master, selection, document)
    return master, selection, {'provider': 'blender', 'pipeline': master.to_dict(),
                              'selection': selection.to_dict(), 'expectedPublications': publications, 'renderSettings': render,
                              'verificationScope': 'mesh/material/camera state, fresh-process blend reopen and decoded PNGs'}


def run(document, directory, *, executable=None, timeout=300):
    master, selection, prepared = plan(document)
    executable = executable or os.environ.get('SCHEMAXIS_BLENDER')
    if not executable:
        fail('INTERPRETER_NOT_FOUND', 'set SCHEMAXIS_BLENDER or pass --blender to an explicit executable')
    runtime = Interpreter('blender', str(Path(executable).resolve())).probe()
    if runtime.version != '5.2.2':
        fail('UNSUPPORTED_RUNTIME', 'Blender adaptor requires the qualified 5.2.2 release', version=runtime.version)
    directory = Path(directory).expanduser().absolute()
    if directory.exists() or directory.is_symlink():
        fail('OUTPUT_EXISTS', 'choose a new output directory', str(directory))
    directory.mkdir()
    atomic_json(directory / 'authored.json', document)
    atomic_json(directory / 'plan.json', prepared)
    atomic_json(directory / 'analytic-bindings.json', master.analytic_bindings)
    # Retain the lowered graph in the adaptor's public version for replay.
    lowered = {**master.document, 'version': 'schemaxis.blender/1'}
    atomic_json(directory / 'input.json', lowered)
    from .resources import capture
    capture(master,selection,directory)
    snapshot = runtime_archive()
    (directory / 'runtime.zip').write_bytes(snapshot)
    atomic_json(directory / 'result.json', {'status': 'incomplete', 'verified': False})
    runner = SubprocessRunner(runtime, directory,
        arguments=('--background', '--factory-startup', '--disable-autoexec', '--python-exit-code', '1', '--python'), timeout=timeout,
        environment={'PYTHONDONTWRITEBYTECODE': '1'})
    prefix = f'import sys\nsys.path.insert(0, {str(directory / "runtime.zip")!r})\n'
    try:
        submission = runner(prefix + 'from schemaxis.adaptors.blender.native import execute\nfrom schemaxis.native_boundary import execute_guarded\n' + f'execute_guarded(execute, {str(directory)!r})\n')
        atomic_json(directory / 'submission.json', submission.to_dict())
        reopen = runner(prefix + 'from schemaxis.adaptors.blender.native import reopen\nfrom schemaxis.native_boundary import execute_guarded\n' + f'execute_guarded(reopen, {str(directory)!r})\n')
        atomic_json(directory / 'reopen-submission.json', reopen.to_dict())
        result = verify(directory, require_result=False)
        result.update(status='succeeded', runtime=runtime.to_dict(), runtimeSha256=hashlib.sha256(snapshot).hexdigest())
        atomic_json(directory / 'result.json', result)
        return result
    except Exception as error:
        from schemaxis.core.faults import SchemaxisError, Fault
        atomic_json(directory / 'submission-fault.json', error.to_dict() if hasattr(error, 'to_dict') else {'message': str(error)})
        if (directory / 'native-fault.json').exists():
            error = SchemaxisError(Fault(**json.loads((directory / 'native-fault.json').read_text())))
        atomic_json(directory / 'result.json', {'status': 'failed', 'verified': False,
                    'fault': error.fault.to_dict() if isinstance(error, SchemaxisError) else {'message': str(error)}})
        raise error


def verify(directory, require_result=True):
    try:
        return _verify(directory, require_result)
    except SchemaxisError:
        raise
    except (OSError, ValueError, TypeError, KeyError, IndexError) as error:
        fail('VERIFICATION_FAILED', 'Missing or malformed native evidence: ' + str(error), str(directory))


def _verify(directory, require_result=True):
    directory = Path(directory).resolve()
    saved = json.loads((directory / 'plan.json').read_text())
    master, selection, prepared = plan(json.loads((directory / 'authored.json').read_text()), saved['pipeline']['declarations'])
    from .resources import verify as verify_sources
    verify_sources(master,selection,directory)
    if require_result:
        result = json.loads((directory / 'result.json').read_text())
        if result.get('status') != 'succeeded' or result.get('verified') is not True:
            fail('INCOMPLETE_EXECUTION', 'Blender run is incomplete')
    receipt = json.loads((directory / 'verification.json').read_text())
    if receipt.get('sourceCaptureVersion')==1 and not (directory/'sources.json').is_file():
        fail('VERIFICATION_FAILED','retained source manifest is absent')
    reopened = json.loads((directory / 'reopened.json').read_text())
    if receipt.get('planDigest') != prepared['pipeline']['digest'] or receipt.get('status') != 'succeeded':
        fail('VERIFICATION_FAILED', 'Blender plan or status differs')
    if reopened.get('states') != [state['snapshot'] for state in receipt['states']]:
        fail('VERIFICATION_FAILED', 'fresh-process scene state differs')
    if receipt.get('receiptVersion', 1) >= 3:
        from schemaxis.adaptors.blender.settings import matching
        expected_render = prepared['renderSettings']
        if receipt.get('renderSettings') != expected_render:
            fail('VERIFICATION_FAILED', 'Blender render settings differ')
        devices = receipt.get('devices', [])
        if expected_render['device'] != 'CPU' and (not devices or any(
                d.get('type') != expected_render['device'] for d in devices)):
            fail('VERIFICATION_FAILED', 'requested GPU backend was not evidenced')
        for state in receipt['states']:
            if not matching(state['snapshot'].get('render'), expected_render):
                fail('VERIFICATION_FAILED', 'saved native render settings differ')
    visits = list(selection.visits())
    if [state['visit'] for state in receipt['states']] != visits:
        fail('VERIFICATION_FAILED', 'Blender visit sequence differs')
    from schemaxis.pipeline import evaluate
    from schemaxis.bindings import validate_options
    for state, visit in zip(receipt['states'], visits):
        for node in selection.order:
            options = evaluate(master.nodes[node]['options'], visit['axes'], state['observations'], visit['time'], node)
            expected = validate_options(master.declarations[master.nodes[node]['filter']], options, node)
            if state['effective'][node] != expected:
                fail('VERIFICATION_FAILED', 'Blender effective options differ', node)
    if receipt.get('receiptVersion', 1) >= 2:
        events = [{'event': 'create', 'node': node} for node in selection.order]
        prior_values, prior_time, identities = {}, None, None
        for state, visit in zip(receipt['states'], visits):
            current_ids = state.get('objectIds', {})
            if set(current_ids) != set(selection.order) or len(set(current_ids.values())) != len(selection.order):
                fail('VERIFICATION_FAILED', 'Blender object identities differ from active graph')
            if identities is not None and current_ids != identities:
                fail('VERIFICATION_FAILED', 'Blender replaced a shared object unexpectedly')
            identities = current_ids
            dirty = {node for node in selection.order if node not in prior_values or state['effective'][node] != prior_values[node]}
            if visit['time'] != prior_time:
                dirty.update(selection.order)
            for node in selection.order:
                if set(master.nodes[node]['dependencies']) & dirty:
                    dirty.add(node)
            expected_updates = [node for node in selection.order if node in dirty]
            if state.get('updated') != expected_updates:
                fail('VERIFICATION_FAILED', 'Blender dependency invalidation differs')
            events.extend({'event': 'update', 'node': node, 'time': visit['time']} for node in expected_updates)
            prior_values, prior_time = state['effective'], visit['time']
        events.extend({'event': 'delete', 'node': node} for node in reversed(selection.order))
        if receipt.get('events') != events:
            fail('VERIFICATION_FAILED', 'Blender lifecycle sequence differs')
    artifacts = receipt.get('artifacts', [])
    if len(artifacts) != prepared['expectedPublications']:
        fail('VERIFICATION_FAILED', 'Blender publication count differs')
    writer = master.document['scenes'][0]['images'][0]
    expected_order = [(index, 'image', ci) for index in range(len(visits)) for ci in range(len(writer['cameras']))]
    if master.document['scenes'][0].get('prepareOnly'):
        expected_order = []
    actual_order = [(a.get('state'), a.get('kind'), a.get('cameraIndex')) for a in artifacts if a.get('kind') == 'image']
    if actual_order != expected_order or [(a.get('state'), a.get('kind')) for a in artifacts if a.get('kind') == 'scene'] != [(i, 'scene') for i in range(len(visits))]:
        fail('VERIFICATION_FAILED', 'Blender image/scene membership differs')
    meshes=master.document['scenes'][0].get('meshes',[])
    expected_meshes=[(i,node) for i in range(len(visits)) for node in meshes]
    if [(a.get('state'),a.get('node')) for a in artifacts if a.get('kind')=='geometry']!=expected_meshes:
        fail('VERIFICATION_FAILED','Blender mesh publication membership differs')
    if reopened.get('meshes',[]) != [a['after'] for a in artifacts if a.get('kind')=='geometry']:
        fail('VERIFICATION_FAILED','fresh-process STL reopening differs')
    from schemaxis.camera import camera_values
    seen = set()
    for artifact in artifacts:
        if artifact.get('kind') == 'image':
            state = receipt['states'][artifact['state']]
            visit = state['visit']
            expected = camera_values(evaluate(writer['cameras'][artifact['cameraIndex']], visit['axes'], state['observations'], visit['time'], 'camera'), 'camera')
            if expected != artifact.get('effectiveCamera'):
                fail('VERIFICATION_FAILED', 'Blender camera settings differ')
            data = [state['observations'][node]['bounds'] for node in master.document['scenes'][0]['visible']]
            bounds = expected.get('bounds', [min(b[i] for b in data) if i%2 == 0 else max(b[i] for b in data) for i in range(6)])
            centre = expected.get('focalPoint', [(bounds[i]+bounds[i+1])/2 for i in (0,2,4)])
            diagonal = math.hypot(*(bounds[i+1]-bounds[i] for i in (0,2,4)))
            length = math.hypot(*expected['direction'])
            direction = [v/length for v in expected['direction']]
            position = [c+d*expected.get('distance', diagonal*2) for c,d in zip(centre,direction)]
            actual = artifact['camera']
            if receipt.get('framingVersion',1)>=3:
                from .settings import clipping, matching
                near,far=clipping(diagonal,expected.get('distance',diagonal*2))
                if not matching(actual.get('clipStart'),near) or not matching(actual.get('clipEnd'),far):
                    fail('VERIFICATION_FAILED','camera depth clipping differs from model scale')
            if any(abs(a-b)>1e-5*max(1,abs(b)) for a,b in zip(actual['position'],position)) or any(abs(a+b)>1e-5 for a,b in zip(actual['forward'],direction)):
                fail('VERIFICATION_FAILED', 'Blender native camera differs from authored framing')
            if actual['parallel'] != expected['parallel'] or not math.isclose(actual['scale'], expected.get('scale', diagonal*(1+expected['padding'])*(max(1,writer['size'][0]/writer['size'][1]) if receipt.get('framingVersion', 1) >= 2 else 1)), rel_tol=1e-5):
                fail('VERIFICATION_FAILED', 'Blender native projection differs')
        if artifact.get('kind')=='geometry':
            from .stl import file_snapshot
            path=directory/f"{artifact['state']:04d}-{artifact['node']}.stl"
            if artifact.get('file')!=str(path) or artifact.get('format')!='stl' or artifact.get('before')!=artifact.get('after') or file_snapshot(path)!=artifact.get('before'):
                fail('VERIFICATION_FAILED','STL evidence or triangle data differs')
        path = Path(artifact['file']).resolve()
        if not path.is_relative_to(directory) or path in seen or hashlib.sha256(path.read_bytes()).hexdigest() != artifact['sha256']:
            fail('VERIFICATION_FAILED', 'Blender artifact membership/hash differs', str(path))
        seen.add(path)
    return {'verified': True, 'artifacts': len(artifacts), 'states': len(visits), 'runtime': json.loads((directory/'submission.json').read_text())['interpreter']}


# Shared authored-input, analytic-visit and verification boundary.
from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())


def _check_lathe_profiles(master, selection, document):
    """Apply the native lathe profile checks at planning wherever the values are known host-side."""
    from schemaxis.adaptors.blender.profiles import check_lathe_profile
    from schemaxis.pipeline import evaluate, markers
    authored = {n.get('id'): i for i, n in enumerate(document.get('nodes', [])) if isinstance(n, dict)}
    for key in selection.order:
        node = master.nodes[key]
        if node['filter'] != 'lathe' or 'profile' not in node['options']:
            continue
        options = node['options']
        pending = [options[k] for k in ('profile', 'segments', 'caps') if k in options]
        if any('$observe' in m or '$sample' in m for value in pending for m in markers(value)):
            continue  # needs native observations; the native check remains the backstop
        # Inline $create nodes are lifted into the graph and have no authored index.
        location, where = ('$.nodes[%d].options.profile' % authored[key], {}) if key in authored else ('$.nodes', {'node': key})
        visits = selection.visits() if any(True for value in pending for _ in markers(value)) else [{'axes': {}, 'time': None}]
        for visit in visits:
            values = {k: evaluate(options[k], visit['axes'], {}, visit['time'], key + '.' + k) for k in ('profile', 'segments', 'caps') if k in options}
            check_lathe_profile(values['profile'], values.get('segments', 64), values.get('caps', True), location, **where)
