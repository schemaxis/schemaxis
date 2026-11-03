# Copyright (C) 2026 David L F Gaden
"""Execute a verified publication schedule inside serial pvbatch."""
from pathlib import Path
import time as clock
from schemaxis.core.faults import SchemaxisError, Fault
from schemaxis.adaptors.paraview.job import plan, schedule, identities, atomic_json
from schemaxis.pipeline import RuntimeClosure, evaluate
from schemaxis.adaptors.paraview.native import ParaViewBackend, geometry, measurement
from schemaxis.adaptors.paraview.publication import Renderer, style, camera_values


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
    backend = ParaViewBackend()
    active = RuntimeClosure(master, backend)
    renderer = None
    current_scene = None
    receipt = {'status': 'incomplete', 'verified': False, 'planDigest': master.to_dict()['digest'],
               'planVersion': master.to_dict()['version'], 'renderTimeVersion': 1,
               'executionMode': 'MPI pvbatch' if rank_count > 1 else 'serial pvbatch', 'ranks': rank_count, 'states': [], 'artifacts': [], 'events': []}

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
        for state_index, (scene, visit) in enumerate(schedule(master, scenes)):
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
            prefix = f'{state_index:06d}-{scene["id"]}'
            for index, node in enumerate(scene['geometry']):
                artifact = geometry(backend, active.handles[node], directory / f'{prefix}-geometry-{index}')
                record(artifact, next(expected))
            for index, output in enumerate(scene['measurements']):
                artifact = measurement(backend, active.handles[output['node']],
                                       directory / f'{prefix}-measurement-{index}', output['association'])
                record(artifact, next(expected))
            for index, output in enumerate(scene.get('exports', [])):
                from .writers import publish
                def export_sample(source, association, field, index, component, block):
                    value = backend.sample(active.handles[source], association, field, index, component, block)
                    state['samples'].append({'node': source, 'association': association, 'field': field,
                                             'index': index, 'component': component, 'block': block, 'value': value})
                    return value
                settings = {**output, 'options': evaluate(output['options'], visit['axes'], state['observations'], visit['time'], output['id'], export_sample)}
                artifact = publish(backend, active.handles[output['node']], master.declarations[output['writer']],
                                   settings, directory / f'{prefix}-export-{index}', visit['time'], master.declarations,
                                   {key:active.handles[node] for key,node in output.get('resources',{}).items()})
                record(artifact, next(expected))
            if scene['images'] or scene['gltf']:
                if renderer is None:
                    renderer = Renderer(backend)
                bounds_list = [state['observations'][k]['bounds'] for k in scene['visible']
                               if state['observations'][k]['points'] > 0]
                if not bounds_list:
                    from schemaxis.errors import fail
                    fail('EMPTY_SCENE', 'no visible nonempty data')
                bounds = [min(b[i] for b in bounds_list) if i % 2 == 0 else max(b[i] for b in bounds_list)
                          for i in range(6)]
                for appearance_index, appearance in enumerate(scene['appearances']):
                    def sample(source, association, field, index, component, block):
                        value = backend.sample(active.handles[source], association, field, index, component, block)
                        state['samples'].append({'node': source, 'association': association, 'field': field,
                                                 'index': index, 'component': component, 'block': block, 'value': value})
                        return value
                    def resolved(value):
                        return evaluate(value, visit['axes'], state['observations'], visit['time'], scene['id'], sample)
                    effective_appearance = {k: style(resolved(v), scene['id'] + '.' + k) for k, v in appearance.items()}
                    observed = renderer.prepare(active.handles, effective_appearance, time=visit['time'])
                    if scene['gltf']:
                        path = directory / f'{prefix}-appearance-{appearance_index}.gltf'
                        record(renderer.gltf(path, bounds), next(expected))
                    for writer in scene['images']:
                        for camera_index, camera in enumerate(writer['cameras']):
                            path = directory / f'{prefix}-appearance-{appearance_index}-{writer["id"]}-{camera_index}.png'
                            effective_camera = camera_values(resolved(camera), writer['id'])
                            artifact = renderer.write(path, writer, effective_camera, bounds)
                            if len(scene['visible']) == 1:
                                proxy = active.handles[next(iter(scene['visible']))]
                                if (proxy.SMProxy.GetXMLName() == 'Cut' and not bool(proxy.Crinkleslice)
                                        and proxy.SliceType.SMProxy.GetXMLName() == 'Plane'):
                                    artifact['slicePlane'] = {'origin': list(proxy.SliceType.Origin),
                                                              'normal': list(proxy.SliceType.Normal)}
                            artifact['appearance'] = observed
                            artifact['effectiveCamera'] = effective_camera
                            artifact['effectiveAppearance'] = effective_appearance
                            record(artifact, next(expected))
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
