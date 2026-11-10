# Copyright (C) 2026 David L F Gaden
"""Blender policies exposed through the shared adaptor contract."""
import copy
import os
import stat
from pathlib import Path
from schemaxis.core.faults import Fault, SchemaxisError
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
    if not {'device','renderer'} & set(unknown):
        # Graphics engines require a graphics context independently of Cycles'
        # CPU/CUDA/OptiX selection. Reserve one graphics slot conservatively.
        result['gpus'] = int(render['renderer']['kind'] != 'cycles' or render['device'] != 'CPU')
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
    if document.get('version') in ('schemaxis.blender.render/1','schemaxis.blender.production/1'):
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
        paths.extend(i['file'] for i in master.document['scenes'][0].get('production',{}).get('images',[]))
        paths.extend(i['file'] for i in master.document['scenes'][0].get('production',{}).get('assets',[]))
    return {str(Path(path).absolute()): _input_digest(path) for path in paths}


def _input_digest(path):
    """Hash one scheduled input, keeping absent, invalid and unreadable states distinct."""
    location = str(Path(path).absolute())
    try:
        if not stat.S_ISREG(Path(path).stat().st_mode):
            raise IsADirectoryError("input is not a regular file")
        return file_digest(path)
    except FileNotFoundError:
        code, message, recovery = ('RESOURCE_NOT_FOUND', 'Blender input file is absent',
                                   'Restore the file or correct the path, then rerun.')
    except (IsADirectoryError, NotADirectoryError):
        code, message, recovery = ('INVALID_RESOURCE', 'Blender input must be a regular file',
                                   'Select a regular file (not a directory, FIFO or device).')
    except OSError:
        code, message, recovery = ('RESOURCE_UNREADABLE', 'Blender input cannot be read',
                                   'Check the file permissions and storage, then rerun.')
    raise SchemaxisError(Fault(code, message, location, 'pipeline', recovery=recovery))


def validateHandoff(producer, consumer, identity):
    if producer.get('version')=='schemaxis.blender.production/1':
        # Handoff planning precedes verified path resolution. Project only the
        # publication controls; never lower future asset references as files.
        producer={'version':'schemaxis.blender/1','scenes':[{'prepareOnly':producer.get('prepareOnly',False),
                  'production':producer.get('production',{})}]}
    from schemaxis.adaptors import registry
    image_consumer = 'image' in registry.resolve(consumer, legacy=True)[1].get('acceptedArtifacts', [])
    render_consumer = consumer.get('version') == 'schemaxis.blender.render/1'
    scenes = producer.get('scenes') if producer.get('version') == 'schemaxis.blender/1' else None
    # Unresolved or absent scene declarations are validated by the producer's own plan.
    known = isinstance(scenes, list) and all(isinstance(s, dict) for s in scenes)
    meshes = known and any(s.get('meshes') for s in scenes)
    if producer.get('version') == 'schemaxis.blender.render/1' and render_consumer:
        _unsupported('A Blender render job publishes images only, not a saved scene', identity,
                     'Render from the scene published by the schemaxis.blender/1 operation that built it.')
    if known and scenes and not meshes and image_consumer and all(s.get('prepareOnly') is True
            and not s.get('production',{}).get('renderFrames') for s in scenes):
        _unsupported('A prepareOnly Blender scene publishes no images', identity,
                     'Remove prepareOnly, or render the scene with a schemaxis.blender.render/1 operation first.')
    if not render_consumer and not meshes and not image_consumer:
        fail('UNSUPPORTED_HANDOFF', 'Blender scene handoffs require a saved-scene render consumer', identity)


def _unsupported(message, identity, recovery):
    raise SchemaxisError(Fault('UNSUPPORTED_HANDOFF', message, identity, 'pipeline', recovery=recovery))


def query(document):
    if document.get('version')=='schemaxis.blender.production/1':
        from .adaptor import plan
        plan(document)
        return [],{'sceneProduction':True}
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
