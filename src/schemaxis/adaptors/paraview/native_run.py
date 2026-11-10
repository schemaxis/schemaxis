# Copyright (C) 2026 David L F Gaden
"""Execute a verified publication schedule inside serial pvbatch."""
from pathlib import Path
import time as clock
from schemaxis.core.faults import SchemaxisError, Fault
from schemaxis.adaptors.paraview.job import plan, schedule, identities, atomic_json
from schemaxis.pipeline import RuntimeClosure, evaluate
from schemaxis.adaptors.paraview.native import ParaViewBackend, geometry, measurement
from schemaxis.adaptors.paraview.publication import Renderer, style, camera_values, scene_bounds, observed_slice_plane
from schemaxis.artifact_names import OutputSequence, VERSION as NAMING_VERSION
from schemaxis.adaptors.paraview.output_names import image_properties


def runtime_identity():
    """Self-reported ParaView release, build and platform; never fails the run."""
    try:
        import platform
        from paraview import servermanager
        from paraview.simple import GetParaViewSourceVersion
        manager = servermanager.vtkSMProxyManager
        version = '.'.join(str(part()) for part in (manager.GetVersionMajor, manager.GetVersionMinor,
                                                    manager.GetVersionPatch))
        return {'application': 'paraview', 'version': version, 'build': GetParaViewSourceVersion(),
                'platform': {'system': platform.system(), 'machine': platform.machine(),
                             'python': platform.python_version()},
                'source': 'paraview.servermanager.vtkSMProxyManager'}
    except Exception as error:
        return {'application': 'paraview', 'fault': type(error).__name__ + ': ' + str(error)}


def execute(document, directory):
    directory = Path(directory)
    master, scenes, planned = plan(document)
    import os
    from vtkmodules.vtkParallelCore import vtkMultiProcessController
    controller = vtkMultiProcessController.GetGlobalController()
    rank_count = controller.GetNumberOfProcesses() if controller else 1
    rank = controller.GetLocalProcessId() if controller else 0
    from schemaxis.errors import fail
    if rank != 0:
        fail('UNSUPPORTED_EXECUTION', 'symmetric Python execution is not supported')
    if rank_count != int(os.environ.get('SCHEMAXIS_EXPECTED_RANKS', '1')):
        fail('MPI_SIZE_MISMATCH', 'native MPI size differs from allocation', actual=rank_count)
    if rank_count > 1 and any(scene.get('stateBundle') for scene in scenes):
        fail('UNSUPPORTED_STATE_BUNDLE', 'editable state bundles are saved only by serial pvbatch')
    sequence = OutputSequence(os.environ.get('SCHEMAXIS_OUTPUT_RUN_ROOT', directory))
    backend = ParaViewBackend()
    active = RuntimeClosure(master, backend)
    renderer = None
    current_scene = None
    receipt = {'status': 'incomplete', 'verified': False, 'planDigest': master.to_dict()['digest'],
               'planVersion': master.to_dict()['version'], 'renderTimeVersion': 1, 'backgroundVersion': 1, 'cameraFramingVersion': 1,
               'executionMode': 'MPI pvbatch' if rank_count > 1 else 'serial pvbatch', 'ranks': rank_count, 'states': [], 'artifacts': [], 'events': [],
               'runtimeIdentity': runtime_identity(), 'artifactNamingVersion': NAMING_VERSION}

    if rank_count > 1:
        receipt['distributedPublicationVersion'] = 1

    def save():
        receipt['events'] = list(active.events)
        atomic_json(directory / 'verification.json', receipt)

    def record(artifact, identity):
        receipt['artifacts'].append({**artifact, 'identity': identity})
        save()

    try:
        save()
        for scene, visit in schedule(master, scenes):
            if current_scene != scene['id']:
                if renderer:
                    renderer.clear()
                active.activate(scene['selection']['roots'])
                current_scene = scene['id']
            started = clock.monotonic()
            state = active.apply(visit)
            state['timings'] = {'applySeconds': clock.monotonic()-started}
            publication_started = clock.monotonic()
            state.update(scene=scene['id'], proxyIds={k: str(v.SMProxy.GetGlobalIDAsString()) for k, v in active.handles.items()})
            receipt['states'].append(state)
            save()
            expected = iter(identities(scene, visit))
            if scene.get('stateBundle'):
                # Pin reader inputs before any publication, so the image and the bundle consume one copy.
                from .handback_native import capture_inputs
                bundle = sequence.path(directory, {'kind': 'stateBundle', 'scene': scene['id'], 'time': visit['time']})
                state['inputRebinding'] = capture_inputs(active, master, scene, visit, state, bundle)
                save()
            for node in scene['geometry']:
                path = sequence.path(directory, {'kind': 'geometry', 'scene': scene['id'], 'node': node, 'time': visit['time']})
                artifact = geometry(backend, active.handles[node], path)
                record(artifact, next(expected))
            for output in scene['measurements']:
                path = sequence.path(directory, {'kind': 'table', 'scene': scene['id'], 'node': output['node'],
                                                 'association': output['association'], 'time': visit['time']})
                artifact = measurement(backend, active.handles[output['node']], path, output['association'])
                record(artifact, next(expected))
            for output in scene.get('exports', []):
                from .writers import publish
                def export_sample(source, association, field, index, component, block):
                    value = backend.sample(active.handles[source], association, field, index, component, block)
                    state['samples'].append({'node': source, 'association': association, 'field': field,
                                             'index': index, 'component': component, 'block': block, 'value': value})
                    return value
                settings = {**output, 'options': evaluate(output['options'], visit['axes'], state['observations'], visit['time'], output['id'], export_sample)}
                export_path = sequence.path(directory, {'kind': 'export', 'scene': scene['id'],
                                                        'name': output['id'], 'time': visit['time']})
                artifact = publish(backend, active.handles[output['node']], master.declarations[output['writer']],
                                   settings, directory / export_path.name[:6], visit['time'], master.declarations,
                                   {key:active.handles[node] for key,node in output.get('resources',{}).items()},
                                   basename=export_path.name)
                record(artifact, next(expected))
            if scene['images'] or scene['gltf']:
                if renderer is None:
                    renderer = Renderer(backend)
                text = set(scene.get('text', ()))
                bounds = scene_bounds(scene, state['observations'])
                for appearance_index, appearance in enumerate(scene['appearances']):
                    def sample(source, association, field, index, component, block):
                        value = backend.sample(active.handles[source], association, field, index, component, block)
                        state['samples'].append({'node': source, 'association': association, 'field': field,
                                                 'index': index, 'component': component, 'block': block, 'value': value})
                        return value
                    def resolved(value):
                        return evaluate(value, visit['axes'], state['observations'], visit['time'], scene['id'], sample)
                    effective_appearance = {k: style(resolved(v), scene['id'] + '.' + k, text=k in text)
                                            for k, v in appearance.items()}
                    observed = renderer.prepare(active.handles, effective_appearance, time=visit['time'], text=text)
                    plane = None
                    if len(scene['visible']) == 1:
                        proxy = active.handles[next(iter(scene['visible']))]
                        plane = observed_slice_plane(proxy)
                    cuts = [(node, observed_slice_plane(active.handles[node])) for node, settings in effective_appearance.items()
                            if node not in text and settings.get('opacity', 1) > 0]
                    slice_planes = [cut for _, cut in cuts if cut is not None]
                    naming_plane = slice_planes[0] if len(slice_planes) == 1 else None
                    properties = image_properties(scene, effective_appearance, naming_plane, visit['time'], appearance_index)
                    if naming_plane is not None:
                        properties['model'] = 'on' if any(cut is None for _, cut in cuts) else 'off'
                    if scene['gltf']:
                        path = sequence.path(directory, {**properties, 'kind': 'scene'}, '.gltf')
                        record(renderer.gltf(path, bounds), next(expected))
                    for writer in scene['images']:
                        for camera_index, camera in enumerate(writer['cameras']):
                            fields = {**properties, 'view': camera_index}
                            if len(scene['images']) > 1:
                                fields['writer'] = writer['id']
                            path = sequence.path(directory, fields, '.png')
                            effective_camera = camera_values(resolved(camera), writer['id'])
                            artifact = renderer.write(path, writer, effective_camera, bounds)
                            if plane is not None:
                                artifact['slicePlane'] = plane
                            artifact['appearance'] = observed
                            artifact['effectiveCamera'] = effective_camera
                            artifact['effectiveBackground'] = {k: writer[k] for k in ('background', 'transparentBackground')}
                            artifact['effectiveAppearance'] = effective_appearance
                            record(artifact, next(expected))
            if scene.get('stateBundle'):
                from .handback_native import save_bundle
                image = receipt['artifacts'][-1]
                record(save_bundle(backend, renderer, active, master, scene, visit, state, image,
                                   bundle, receipt['runtimeIdentity']), next(expected))
            state['timings']['publicationSeconds'] = clock.monotonic()-publication_started
        if renderer:
            renderer.close()
            renderer = None
        active.close()
        if len(receipt['artifacts']) != planned['expectedPublications']:
            from schemaxis.errors import fail
            fail('VERIFICATION_FAILED', 'publication count mismatch')
        receipt.update(status='succeeded', verified=True)
        save()
    except Exception as error:
        fault = error.fault if isinstance(error, SchemaxisError) else Fault(
            'NATIVE_EXECUTION_FAILED', str(error) or type(error).__name__, '$', 'native',
            observed={'exceptionType': type(error).__name__})
        receipt.update(status='failed', verified=False, fault=fault.to_dict())
        save()
        raise
    finally:
        # Cleanup must not hide the original diagnostic or erase partial evidence.
        errors = []
        if renderer:
            try:
                renderer.close()
            except Exception as error:
                errors.append(str(error))
        if not active.closed:
            try:
                active.close()
            except Exception as error:
                errors.append(str(error))
        if errors:
            receipt['cleanupErrors'] = errors
            receipt.update(status='failed', verified=False)
            save()
