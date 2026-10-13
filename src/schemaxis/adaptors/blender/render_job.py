"""Render verified saved Schemaxis scenes without reconstructing their geometry."""
import hashlib
import json
import math
import os
from pathlib import Path
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.runners import Interpreter
from schemaxis.artifacts import atomic_json, runtime_archive
from schemaxis.camera import camera_values
from schemaxis.dispatch import SubprocessRunner
from schemaxis.core.faults import SchemaxisError
from schemaxis.errors import fail, keys
from .settings import render_settings, matching


def plan(document):
    keys(document, ('version', 'sceneFile', 'cameras', 'size', 'render'), '$')
    if document.get('version') != 'schemaxis.blender.render/1':
        fail('UNSUPPORTED_VERSION', 'expected schemaxis.blender.render/1')
    if not isinstance(document.get('sceneFile'), str) or not document['sceneFile']:
        fail('INVALID_RESOURCE', 'sceneFile must identify a saved Schemaxis blend scene')
    cameras = document.get('cameras')
    if not isinstance(cameras, list) or not 1 <= len(cameras) <= 1000:
        fail('INVALID_CAMERA', 'provide from 1 to 1000 literal cameras')
    cameras = [camera_values(camera, 'cameras') for camera in cameras]
    size = validate_arguments({'size': {'type': 'array', 'items': {'type': 'integer', 'minimum': 32, 'maximum': 2048},
        'minItems': 2, 'maxItems': 2, 'default': [320, 240]}}, {'size': document.get('size', [320, 240])})['size']
    return {'sceneFile': document['sceneFile'], 'cameras': cameras, 'size': size,
            'render': render_settings(document.get('render', {})), 'expectedPublications': len(cameras)}


def run(document, directory, *, executable=None, timeout=300):
    prepared = plan(document)
    source = Path(prepared['sceneFile']).absolute()
    if not source.is_file():
        fail('RESOURCE_NOT_FOUND', 'saved scene is absent', str(source))
    executable = executable or os.environ.get('SCHEMAXIS_BLENDER')
    if not executable:
        fail('INTERPRETER_NOT_FOUND', 'provide a Blender executable')
    runtime = Interpreter('blender', str(Path(executable).resolve())).probe()
    if runtime.version != '5.2.2':
        fail('UNSUPPORTED_RUNTIME', 'saved scene rendering requires Blender 5.2.2')
    directory = Path(directory).absolute()
    if directory.exists():
        fail('OUTPUT_EXISTS', 'choose a fresh output directory', str(directory))
    directory.mkdir()
    atomic_json(directory/'authored.json', document)
    atomic_json(directory/'plan.json', prepared)
    # An immutable local copy lets retries and later verification avoid mutable scene inputs.
    payload = source.read_bytes()
    (directory/'source.blend').write_bytes(payload)
    atomic_json(directory/'source.json', {'file': str(source), 'sha256': hashlib.sha256(payload).hexdigest()})
    snapshot = runtime_archive()
    (directory/'runtime.zip').write_bytes(snapshot)
    atomic_json(directory/'result.json', {'status': 'incomplete', 'verified': False})
    runner = SubprocessRunner(runtime, directory,
        arguments=('--background', '--factory-startup', '--disable-autoexec', '--python-exit-code', '1', '--python'), timeout=timeout)
    source_code = (f'import sys\nsys.path.insert(0, {str(directory/"runtime.zip")!r})\n'
                   'from schemaxis.adaptors.blender.render_native import execute\n'
                   'from schemaxis.native_boundary import execute_guarded\n'
                   f'execute_guarded(execute, {str(directory)!r})\n')
    try:
        submission = runner(source_code)
        atomic_json(directory/'submission.json', submission.to_dict())
        result = verify(directory, require_result=False)
        result.update(status='succeeded', runtime=runtime.to_dict(), runtimeSha256=hashlib.sha256(snapshot).hexdigest())
        atomic_json(directory/'result.json', result)
        return result
    except Exception as error:
        atomic_json(directory/'result.json', {'status': 'failed', 'verified': False, 'fault': str(error)})
        raise


def verify(directory, require_result=True):
    try:
        return _verify(directory, require_result)
    except SchemaxisError:
        raise
    except (OSError, ValueError, TypeError, KeyError, IndexError) as error:
        fail('VERIFICATION_FAILED', 'Missing or malformed native evidence: ' + str(error), str(directory))


def _verify(directory, require_result=True):
    directory = Path(directory).absolute()
    prepared = plan(json.loads((directory/'authored.json').read_text()))
    if json.loads((directory/'plan.json').read_text()) != prepared:
        fail('VERIFICATION_FAILED', 'render plan differs')
    if require_result and json.loads((directory/'result.json').read_text()).get('verified') is not True:
        fail('INCOMPLETE_EXECUTION', 'render job did not complete')
    source = json.loads((directory/'source.json').read_text())
    digest = hashlib.sha256((directory/'source.blend').read_bytes()).hexdigest()
    # Detect changed external input on resume as well as retained copy corruption.
    if source['sha256'] != digest or hashlib.sha256(Path(prepared['sceneFile']).read_bytes()).hexdigest() != digest:
        fail('VERIFICATION_FAILED', 'saved scene source changed')
    receipt = json.loads((directory/'verification.json').read_text())
    if receipt.get('status') != 'succeeded' or receipt.get('sourceSha256') != digest:
        fail('VERIFICATION_FAILED', 'source receipt differs')
    if receipt.get('before') != receipt.get('after') or not receipt.get('before'):
        fail('VERIFICATION_FAILED', 'rendering changed saved geometry or materials')
    if not matching(receipt.get('render'), prepared['render']):
        fail('VERIFICATION_FAILED', 'native render settings differ')
    if prepared['render']['device'] != 'CPU' and (not receipt.get('devices') or any(d.get('type') != prepared['render']['device'] for d in receipt['devices'])):
        fail('VERIFICATION_FAILED', 'requested GPU backend was not evidenced')
    artifacts = receipt.get('artifacts', [])
    if len(artifacts) != prepared['expectedPublications']:
        fail('VERIFICATION_FAILED', 'render publication count differs')
    for index, (artifact, camera) in enumerate(zip(artifacts, prepared['cameras'])):
        path = directory/f'{index:04d}.png'
        if artifact.get('file') != str(path) or artifact.get('cameraIndex') != index or artifact.get('kind') != 'image':
            fail('VERIFICATION_FAILED', 'render publication membership differs')
        if hashlib.sha256(path.read_bytes()).hexdigest() != artifact.get('sha256') or artifact.get('size') != prepared['size']:
            fail('VERIFICATION_FAILED', 'render image differs')
        bounds = camera.get('bounds', receipt['bounds'])
        centre = camera.get('focalPoint', [(bounds[i]+bounds[i+1])/2 for i in (0, 2, 4)])
        diagonal = math.hypot(*(bounds[i+1]-bounds[i] for i in (0, 2, 4)))
        norm = math.hypot(*camera['direction'])
        direction = [v/norm for v in camera['direction']]
        position = [c+d*camera.get('distance', diagonal*2) for c, d in zip(centre, direction)]
        actual = artifact['camera']
        if receipt.get('framingVersion',1)>=3:
            from .settings import clipping
            near,far=clipping(diagonal,camera.get('distance',diagonal*2))
            if not matching(actual.get('clipStart'),near) or not matching(actual.get('clipEnd'),far):
                fail('VERIFICATION_FAILED','saved-scene camera depth clipping differs')
        scale = camera.get('scale', diagonal*(1+camera['padding'])*max(1, prepared['size'][0]/prepared['size'][1]))
        if not matching(actual['position'], position) or not matching(actual['forward'], [-d for d in direction]) or not matching(actual['scale'], scale) or actual['parallel'] != camera['parallel']:
            fail('VERIFICATION_FAILED', 'native camera differs')
    return {'verified': True, 'artifacts': len(artifacts), 'runtime': json.loads((directory/'submission.json').read_text())['interpreter']}


# Shared authored-input, analytic-visit and verification boundary.
from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
