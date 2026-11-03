# Copyright (C) 2026 David L F Gaden
"""Blender policies exposed through the shared adaptor contract."""
import copy
import os
from pathlib import Path
from schemaxis.errors import fail
from schemaxis.artifacts import file_digest


def resources(document, spec, identity):
    if document.get('version') == 'schemaxis.blender.render/1':
        from .render_job import plan
        render = plan(document)['render']
    else:
        from .adaptor import plan
        render = plan(document)[2]['renderSettings']
    return _render_resources(render, spec, identity)


def _render_resources(render, spec, identity, unknown=()):
    result = {}
    if 'threads' not in unknown:
        threads = render['threads']
        if spec.get('threads', threads) != threads:
            fail('INVALID_EXECUTION', 'Blender allocation threads must equal render threads', identity)
        result['threads'] = threads
    if 'device' not in unknown:
        result['gpus'] = int(render['device'] != 'CPU')
    if spec.get('ranks', 1) > 1:
        fail('UNSUPPORTED_EXECUTION', 'Blender does not accept MPI ranks', identity)
    return result


def provisionalResources(document, spec, identity):
    """Reserve known render requirements without fabricating scene/mesh files.

    Producer-derived settings remain unknown; literal and finite local settings
    can establish reservations independently of the future geometry. The full
    planner/resources hook still validates the resolved document before dispatch.
    """
    from schemaxis.adaptor_runtime import InputProgram, output_reference, walk
    from schemaxis.workflow import dependencies
    from .settings import render_settings
    if document.get('version') == 'schemaxis.blender.render/1':
        raw = document.get('render', {})
    else:
        scenes = document.get('scenes')
        if output_reference(scenes):
            return {}
        if not isinstance(scenes, list) or len(scenes) != 1 or not isinstance(scenes[0], dict):
            fail('INVALID_SCENE', 'initial Blender adaptor requires one scene')
        if output_reference(scenes[0]):
            return {}
        raw = scenes[0].get('render', {})
    if output_reference(raw):
        return {}
    if not isinstance(raw, dict):
        return render_settings(raw)  # Preserve the settings validator's fault.
    unknown = {key for key, value in raw.items() if any(dependencies(value))}
    axes = document.get('axes', [])
    if any(dependencies(axes)):
        unknown.update(key for key, value in raw.items()
                       if any('$axis' in marker for _, marker in walk(value)))
        axes = []
    projection = {'render': {key: value for key, value in raw.items() if key not in unknown},
                  'axes': axes, 'maxStates': document.get('maxStates', 10000)}
    result = {}
    for visit in InputProgram(projection).visits():
        known = visit['document']['render']
        render = render_settings(known)
        for key, value in _render_resources(render, spec, identity, unknown).items():
            result[key] = max(result.get(key, 0), value)
    return result


def reusableInputs(document):
    if document.get('version') == 'schemaxis.blender.render/1': paths = [document['sceneFile']]
    else:
        from .adaptor import plan
        master, selection, _ = plan(document)
        paths = [master.nodes[node]['options']['file'] for node in selection.order
                 if master.nodes[node]['filter'] in ('readGltf', 'readSTL', 'readPLY', 'curveFromCSV')]
    return {str(Path(path).absolute()): file_digest(path) for path in paths}


def validateHandoff(producer, consumer, identity):
    meshes = producer.get('version') == 'schemaxis.blender/1' and any(s.get('meshes') for s in producer.get('scenes', []))
    from schemaxis.adaptors import registry
    image_consumer = 'image' in registry.resolve(consumer, legacy=True)[1].get('acceptedArtifacts', [])
    if consumer.get('version') != 'schemaxis.blender.render/1' and not meshes and not image_consumer:
        fail('UNSUPPORTED_HANDOFF', 'Blender scene handoffs require a saved-scene render consumer', identity)


def query(document):
    if document.get('version') == 'schemaxis.blender.render/1':
        from .render_job import plan
        provisional = copy.deepcopy(document)
        if isinstance(provisional.get('sceneFile'), dict) and '$artifact' in provisional['sceneFile']:
            provisional['sceneFile'] = '/unresolved-scene.blend'
        plan(provisional)
        return [], {'savedSceneRendering': True}
    from schemaxis.schema import expand_input
    nodes = expand_input(document).get('nodes', [])
    if not isinstance(nodes, list) or any(not isinstance(n, dict) or not isinstance(n.get('filter'), str) for n in nodes):
        fail('INVALID_DOCUMENT', 'nodes require declared filter names')
    return [n['filter'] for n in nodes], {}


def inspectionSetup(document, locations):
    from .adaptor import plan
    from schemaxis.core.runners import Interpreter
    executable = locations.get('blender') or os.environ.get('SCHEMAXIS_BLENDER')
    if not executable: fail('INTERPRETER_NOT_FOUND', 'set SCHEMAXIS_BLENDER or pass --blender')
    interpreter = Interpreter('blender', str(Path(executable).resolve())).probe()
    return plan(document)[0], interpreter, ('--background', '--factory-startup', '--python-exit-code', '1', '--python')


def nativeInspection(document):
    import bpy
    from .adaptor import plan
    from .native import Backend
    bpy.ops.wm.read_factory_settings(use_empty=True)
    return plan(document)[0], Backend()


def liveGraph(document):
    from schemaxis.live_transport import fault
    from .adaptor import plan
    master, selection, _ = plan(document)
    scene = master.document['scenes'][0]
    visible = scene['visible']
    return master, selection, scene, visible
