# Copyright (C) 2026 David L F Gaden
"""Planning, retained native submission and independent receipt checks."""
import copy
import io
import json
import hashlib
from pathlib import Path
from schemaxis.artifacts import atomic_json, runtime_archive
from schemaxis.core.faults import SchemaxisError
from schemaxis.documents import resolve_document
from schemaxis.core.declarations import validate_value
from schemaxis.core.times import TIMES_ARGUMENT, resolve_times
from schemaxis.adaptors.paraview.mvp.runners import require_paraview, PARAVIEW_OFFSCREEN
from schemaxis.dispatch import SubprocessRunner
from schemaxis.errors import fail, keys
from .parallel_files import file_digest, verify_manifest, verify_piece_evidence, verify_reduction_evidence
from schemaxis.adaptors.paraview.filters import catalogue, validate_options
from schemaxis.pipeline import DefinitionGraph, markers, evaluate, digest
from schemaxis.adaptors.paraview.publication import scenes, style, camera_values, scene_bounds, default_distance


def plan(document):
    master = DefinitionGraph(document, catalogue())
    outputs = scenes(master)
    return master, outputs, {'pipeline': master.to_dict(), 'scenes': outputs,
                             'expectedPublications': sum(s['publications'] for s in outputs)}


def schedule(master, outputs):
    for time_index, _ in enumerate(master.times):
        for scene in outputs:
            selected = master.select(scene['selection']['roots'])
            for visit in selected.visits():
                if visit['timeIndex'] == time_index:
                    yield scene, visit


def identities(scene, visit):
    common = {'scene': scene['id'], 'timeIndex': visit['timeIndex'], 'indices': visit['indices']}
    for index, node in enumerate(scene['geometry']):
        yield {**common, 'kind': 'geometry', 'output': index, 'node': node}
    for index, item in enumerate(scene['measurements']):
        yield {**common, 'kind': 'measurement', 'output': index, 'node': item['node']}
    for index, item in enumerate(scene.get('exports', [])):
        yield {**common, 'kind': 'export', 'output': index, 'node': item['node'], 'writer': item['id']}
    for appearance in range(len(scene['appearances'])):
        if scene['gltf']:
            yield {**common, 'kind': 'gltf', 'appearance': appearance}
        for writer in scene['images']:
            for camera in range(len(writer['cameras'])):
                yield {**common, 'kind': 'image', 'appearance': appearance,
                       'writer': writer['id'], 'camera': camera}
    if scene.get('stateBundle'):
        yield {**common, 'kind': 'state-bundle'}




def verify_default_distance(artifact, camera, size, scene, state, directory):
    """Check that a default perspective camera was placed at the aspect-aware distance."""
    import math
    try:
        bounds = camera.get('bounds') or scene_bounds(scene, state['observations'])
        position, focal = artifact['camera']['position'], artifact['camera']['focalPoint']
        diagonal = math.dist(bounds[0::2], bounds[1::2])
        actual = math.dist(position, focal)
    except (KeyError, TypeError, ValueError, SchemaxisError):
        fail('VERIFICATION_FAILED', 'default perspective camera distance evidence is absent', str(directory))
    if not math.isclose(actual, default_distance(diagonal, size, False), rel_tol=1e-6):
        fail('VERIFICATION_FAILED', 'default perspective camera distance differs from the aspect-aware framing', str(directory),
             expected=default_distance(diagonal, size, False), actual=actual)


def verify_receipt(directory, master, outputs):
    from schemaxis.artifact_names import VERSION as NAMING_VERSION, stem
    directory = Path(directory).resolve()
    receipt = json.loads((directory / 'verification.json').read_text())
    naming = receipt.get('artifactNamingVersion')
    if naming is not None and naming != NAMING_VERSION:
        fail('VERIFICATION_FAILED', 'unsupported artifact naming version', str(directory))
    if receipt.get('status') != 'succeeded' or not receipt.get('verified'):
        fail('INCOMPLETE_EXECUTION', 'native execution did not complete verification', str(directory),
             nativeFault=receipt.get('fault'))
    expected_plan = master.to_dict()
    legacy = receipt.get('planVersion', 'schemaxis.plan/1') == 'schemaxis.plan/1'
    if legacy:
        # Earlier receipts predate inclusion of presentation in the plan digest.
        payload = {k: v for k, v in expected_plan.items() if k not in ('digest', 'document')}
        payload['version'] = 'schemaxis.plan/1'
        expected_digest = digest(payload)
    else:
        expected_digest = expected_plan['digest']
    if receipt.get('planDigest') != expected_digest:
        fail('VERIFICATION_FAILED', 'native plan differs from submitted plan', str(directory))
    if 'cameraFramingVersion' in receipt and (type(receipt['cameraFramingVersion']) is not int or receipt['cameraFramingVersion'] != 1):
        fail('VERIFICATION_FAILED', 'unsupported camera framing version', str(directory))
    expected = [identity for scene, visit in schedule(master, outputs) for identity in identities(scene, visit)]
    artifacts = receipt.get('artifacts', [])
    if [a.get('identity') for a in artifacts] != expected:
        fail('VERIFICATION_FAILED', 'publication order or membership differs from plan', str(directory))
    planned_states = list(schedule(master, outputs))
    states = receipt.get('states', [])
    if len(states) != len(planned_states):
        fail('VERIFICATION_FAILED', 'state count differs from plan', str(directory))
    previous, previous_time, previous_ids, previous_values = set(), None, {}, {}
    expected_events = []
    for state, (scene, visit) in zip(states, planned_states):
        order = scene['selection']['order']
        selected = set(order)
        if state.get('scene') != scene['id'] or state.get('visit') != visit:
            fail('VERIFICATION_FAILED', 'visited state differs from requested state', str(directory))
        if any(set(state.get(k, {})) != selected for k in ('proxyIds', 'effective', 'observations')):
            fail('VERIFICATION_FAILED', 'active object membership differs from dependency closure', str(directory))
        def sampled_value(source, association, field, index, component, block):
            request = {'node': source, 'association': association, 'field': field, 'index': index,
                       'component': component, 'block': block}
            for item in state.get('samples', []):
                if all(item.get(k) == v for k, v in request.items()):
                    return item['value']
            fail('VERIFICATION_FAILED', 'runtime sample evidence is missing', source)
        for key in order:
            node = master.nodes[key]
            expected_options = evaluate(node['options'], visit['axes'], state['observations'], visit['time'], key, sampled_value)
            expected_options = validate_options(master.declarations[node['filter']], expected_options, key)
            if state['effective'][key] != expected_options:
                fail('VERIFICATION_FAILED', 'effective options differ from authored values and observations', key)
        for key in previous & selected:
            if previous_ids[key] != state['proxyIds'][key]:
                fail('VERIFICATION_FAILED', 'a surviving native object was rebuilt', key)
        for key in reversed(master.order):
            if key in previous - selected:
                expected_events.append({'event': 'delete', 'node': key})
        for key in order:
            if key not in previous:
                expected_events.append({'event': 'create', 'node': key})
        dirty = {k for k in order if k not in previous or previous_values.get(k) != state['effective'][k]}
        dirty.update(k for k in order if master.nodes[k].get('onVisit'))
        if previous_time != visit['time']:
            dirty.update(order)
        for key in order:
            if set(master.nodes[key]['dependencies']) & dirty:
                dirty.add(key)
        if state.get('updated') != [k for k in order if k in dirty]:
            fail('VERIFICATION_FAILED', 'dependency invalidation differs from observed effective changes', str(directory))
        for key in order:
            if key in dirty:
                expected_events.extend({'event':'command','node':key,'command':command,'time':visit['time']}
                                       for command in master.nodes[key].get('onVisit', []))
                expected_events.append({'event':'update','node':key,'time':visit['time']})
        previous, previous_time = selected, visit['time']
        previous_ids, previous_values = state['proxyIds'], state['effective']
    expected_events.extend({'event': 'delete', 'node': k} for k in reversed(master.order) if k in previous)
    if receipt.get('events') != expected_events:
        fail('VERIFICATION_FAILED', 'native lifecycle event sequence differs from plan', str(directory))
    by_state = {(s['id'], v['timeIndex'], tuple(sorted(v['indices'].items()))): (s, v, state)
                for state, (s, v) in zip(states, planned_states)}
    seen = set()
    for artifact in artifacts:
        if artifact['identity']['kind'] == 'export':
            identity = artifact['identity']
            scene, visit, state = by_state[(identity['scene'], identity['timeIndex'], tuple(sorted(identity['indices'].items())))]
            expected = scene['exports'][identity['output']]
            def export_sample(source, association, field, index, component, block):
                for item in state.get('samples', []):
                    if (item['node'], item['association'], item['field'], item['index'], item['component'], item['block']) == (source, association, field, index, component, block):
                        return item['value']
                fail('VERIFICATION_FAILED', 'export sample evidence is absent', source)
            values = evaluate(expected['options'], visit['axes'], state['observations'], visit['time'], expected['id'], export_sample)
            effective = validate_options(master.declarations[expected['writer']], values, expected['id'])
            if artifact.get('effectiveOptions') != effective or any(artifact.get(k) != expected[k] for k in ('writer','comparison','tolerance','readback')) or artifact.get('acceptedLosses') != expected['acceptLosses']:
                fail('VERIFICATION_FAILED', 'export settings differ from authored settings', str(directory))
            resources=expected.get('resources',{})
            if (artifact.get('resources',{})!=resources or artifact.get('resourceProxyIds',{})!=
                    {key:state['proxyIds'][node] for key,node in resources.items()}):
                fail('VERIFICATION_FAILED','writer resources differ from the planned native identities',str(directory))
            from .export_integrity import verify_export_evidence
            basename = 'data'
            if naming is not None:
                ordinal = Path(artifact['file']).parent.name
                if len(ordinal) != 6 or not ordinal.isascii() or not ordinal.isdigit():
                    fail('VERIFICATION_FAILED', 'indexed export directory must be a six-digit ordinal', str(directory))
                basename = stem(int(ordinal), {'kind': 'export', 'scene': identity['scene'],
                                               'name': expected['id'], 'time': visit['time']})
            verify_export_evidence(directory, artifact, expected, master.declarations[expected['writer']]['native'],
                                   f"{identity['scene']}.exports[{identity['output']}]", basename=basename)
        if artifact['identity']['kind'] == 'image' and not legacy:
            identity = artifact['identity']
            scene, visit, state = by_state[(identity['scene'], identity['timeIndex'], tuple(sorted(identity['indices'].items())))]
            if receipt.get('renderTimeVersion') == 1 and artifact.get('viewTime') != visit['time']:
                fail('VERIFICATION_FAILED', 'render view time differs from scheduled time', str(directory))
            def sample(source, association, field, index, component, block):
                for item in state.get('samples', []):
                    if (item['node'], item['association'], item['field'], item['index'], item['component'], item['block']) == (source, association, field, index, component, block):
                        return item['value']
                fail('VERIFICATION_FAILED', 'presentation sample evidence is absent', source)
            def resolve(value):
                return evaluate(value, visit['axes'], state['observations'], visit['time'], scene['id'], sample)
            text = scene.get('text', [])
            appearance = {k: style(resolve(v), scene['id'] + '.' + k, text=k in text)
                          for k, v in scene['appearances'][identity['appearance']].items()}
            annotations = artifact.get('annotations', {}) if receipt.get('renderTimeVersion') == 1 else None
            if annotations is not None and (sorted(annotations) != text or any(
                    not isinstance(item, dict) or not isinstance(item.get('text'), str) or not item['text']
                    or item.get('viewTime') != visit['time'] or item.get('fontSize') != appearance[node]['fontSize']
                    or item.get('bold') != appearance[node]['bold'] or item.get('italic') != appearance[node]['italic']
                    for node, item in annotations.items())):
                fail('VERIFICATION_FAILED', 'rendered text annotation evidence differs from authored settings', str(directory))
            writer = next(w for w in scene['images'] if w['id'] == identity['writer'])
            camera = camera_values(resolve(writer['cameras'][identity['camera']]), writer['id'])
            if artifact.get('effectiveAppearance') != appearance or artifact.get('effectiveCamera') != camera:
                fail('VERIFICATION_FAILED', 'effective presentation differs from authored settings', str(directory))
            background = {k: writer[k] for k in ('background', 'transparentBackground')}
            if receipt.get('backgroundVersion') == 1:
                observed = artifact.get('background', {})
                if (artifact.get('effectiveBackground') != background
                        or observed.get('transparent') != background['transparentBackground']
                        or any(abs(a - b) > 1e-12 for a, b in zip(observed.get('colour', []), background['background']))
                        or len(observed.get('colour', [])) != 3):
                    fail('VERIFICATION_FAILED', 'image background differs from authored settings', str(directory))
            elif background != {'background': [1, 1, 1], 'transparentBackground': False}:
                # Runtimes before backgroundVersion 1 always rendered opaque white.
                fail('VERIFICATION_FAILED', 'receipt predates image backgrounds', str(directory))
            if receipt.get('cameraFramingVersion') == 1 and not camera['parallel'] and 'distance' not in camera:
                verify_default_distance(artifact, camera, writer['size'], scene, state, directory)
        if artifact['identity']['kind'] == 'state-bundle':
            from .handback import verify_artifact
            identity = artifact['identity']
            scene, visit, state = by_state[(identity['scene'], identity['timeIndex'], tuple(sorted(identity['indices'].items())))]
            image = next((a for a in artifacts if a['identity'] == {**identity, 'kind': 'image', 'appearance': 0,
                          'writer': scene['images'][0]['id'], 'camera': 0}), None)
            verify_artifact(directory, artifact, master, scene, state, image)
        if receipt.get('distributedPublicationVersion') == 1:
            kind = artifact['identity']['kind']
            if kind == 'geometry' and artifact.get('publicationMode') != 'native-distributed':
                fail('VERIFICATION_FAILED', 'distributed geometry publication is missing')
            if kind == 'measurement' and 'reductionEvidence' not in artifact:
                fail('VERIFICATION_FAILED', 'distributed reduction evidence is missing')
        if artifact.get('publicationMode') == 'native-distributed':
            verify_piece_evidence(artifact, receipt.get('ranks', 1))
        path = Path(artifact['file']).resolve()
        if not path.is_relative_to(directory) or path in seen or not artifact.get('verified'):
            fail('VERIFICATION_FAILED', 'artifact path, uniqueness or verification is invalid', str(path))
        seen.add(path)
        if 'reductionEvidence' in artifact:
            verify_reduction_evidence(artifact, receipt.get('ranks', 1))
        if artifact.get('publicationMode') == 'native-distributed':
            verify_manifest(artifact)
        if file_digest(path) != artifact['sha256']:
            fail('VERIFICATION_FAILED', 'artifact digest no longer matches', str(path))
        for member in artifact.get('files', []):
            child = Path(member['file']).resolve()
            if not child.is_relative_to(directory) or file_digest(child) != member['sha256']:
                fail('VERIFICATION_FAILED', 'artifact member digest differs', str(child))
    return receipt




def run(document, directory, *, roots=None, timeout=300):
    authored = copy.deepcopy(document)
    document, resolution = resolve_document(copy.deepcopy(document))
    if not isinstance(document, dict):
        fail('INVALID_DOCUMENT', 'pipeline input must be an object')
    time_request = document.get('times') if isinstance(document.get('times'), dict) else None
    if time_request is not None:
        keys(time_request, ('source', 'select'), '$.times')
        validate_value(time_request.get('select'), TIMES_ARGUMENT, '$.times.select')
        provisional = {**document, 'times': [0.0]}
        master, outputs, resolved = plan(provisional)
        source = time_request.get('source')
        if (not isinstance(source, str) or source not in master.nodes
                or master.nodes[source]['inputs']):
            fail('INVALID_TIME_SOURCE', 'time selection requires a source without connected inputs', '$.times.source')
        if list(markers(master.nodes[source]['options'])):
            fail('INVALID_TIME_SOURCE', 'time-inspection source settings must be constant', source)
    else:
        master, outputs, resolved = plan(document)
    directory = Path(directory).expanduser().absolute()
    if directory.exists() or directory.is_symlink():
        fail('OUTPUT_EXISTS', 'choose a new output directory', str(directory))
    interpreter = require_paraview(roots)
    directory.mkdir()  # Deliberately does not invent missing parents.
    atomic_json(directory / 'authored.json', authored)
    atomic_json(directory / 'document-resolution.json', resolution)
    atomic_json(directory / 'verification.json', {'status': 'incomplete', 'verified': False, 'artifacts': []})
    snapshot = runtime_archive()
    (directory / 'runtime.zip').write_bytes(snapshot)
    from schemaxis.artifact_names import run_root
    runner = SubprocessRunner(interpreter, directory, arguments=PARAVIEW_OFFSCREEN, timeout=timeout,
                              environment={'PYTHONDONTWRITEBYTECODE': '1',
                                           'SCHEMAXIS_OUTPUT_RUN_ROOT': str(run_root(directory))})
    try:
        prefix = f'import sys, json\nsys.path.insert(0, {str(directory / "runtime.zip")!r})\n'
        if time_request is not None:
            inspection_source = (prefix + 'from schemaxis.adaptors.paraview.native_inspect import inspect_time_source\n' +
                                 f'inspect_time_source(json.loads({json.dumps(master.document)!r}), '
                                 f'{time_request["source"]!r}, {str(directory)!r})\n')
            inspection_submission = runner(inspection_source)
            atomic_json(directory / 'inspection-submission.json', inspection_submission.to_dict())
            inspection = json.loads((directory / 'inspection.json').read_text())
            if inspection.get('fault'):
                from schemaxis.core.faults import Fault
                raise SchemaxisError(Fault(**inspection['fault']))
            selected = resolve_times(time_request['select'], inspection['times'])
            atomic_json(directory / 'time-selection.json', selected.to_dict())
            document['times'] = list(selected.values)
            master, outputs, resolved = plan(document)
        atomic_json(directory / 'analytic-bindings.json', master.analytic_bindings)
        atomic_json(directory / 'input.json', master.document)
        atomic_json(directory / 'plan.json', resolved)
        source = (prefix + 'from schemaxis.adaptors.paraview.native_run import execute\n' +
                  f'execute(json.loads({json.dumps(master.document)!r}), {str(directory)!r})\n')
        submission = runner(source)
        atomic_json(directory / 'submission.json', submission.to_dict())
        if any(scene.get('stateBundle') for scene in outputs):
            # Independent proof: a fresh process loads a relocated copy of each bundle.
            from .handback import reload as reload_bundles
            reload_bundles(directory, json.loads((directory / 'verification.json').read_text()),
                           lambda code: runner(prefix + code))
        receipt = verify_receipt(directory, master, outputs)
        result = {'status': 'succeeded', 'verified': True, 'directory': str(directory),
                  'artifacts': len(receipt['artifacts']), 'planDigest': master.to_dict()['digest'],
                  'runtimeSha256': hashlib.sha256(snapshot).hexdigest()}
        from .integration import compatibility
        result['compatibility'] = compatibility(directory, receipt)
        atomic_json(directory / 'result.json', result)
        return result
    except SchemaxisError as error:
        atomic_json(directory / 'submission-fault.json', error.to_dict())
        # A native structured error is more actionable than a process exit code.
        receipt = json.loads((directory / 'verification.json').read_text())
        if receipt.get('fault'):
            from schemaxis.core.faults import Fault
            atomic_json(directory / 'result.json', {'status': 'failed', 'verified': False,
                        'directory': str(directory), 'fault': receipt['fault']})
            raise SchemaxisError(Fault(**receipt['fault'])) from error
        atomic_json(directory / 'result.json', {'status': 'failed', 'verified': False,
                    'directory': str(directory), 'fault': error.fault.to_dict()})
        raise


# Shared authored-input, analytic-visit and verification boundary.
from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
