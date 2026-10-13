"""Real-case submission through the slice provider and its existing runner."""
import hashlib
import json
import math
from pathlib import Path

from schemaxis.core.contracts import Artifact
from schemaxis.core.executor import ProviderResult
from schemaxis.core.faults import SchemaxisError, Fault
from schemaxis.core.iteration import Axis, expand
from schemaxis.adaptors.paraview.mvp.runners import PARAVIEW_OFFSCREEN, require_paraview
from schemaxis.core.runners import SubprocessRunner


def embedded_helpers():
    """Snapshot the small pure-Python dependencies in the exact replay.

    Relative imports resolve in an isolated package; no installed Schemaxis is needed
    inside ParaView, and replay keeps the helper versions that actually ran.
    """
    root = Path(__file__).parents[3] / 'core'
    source = 'import sys, types\n_schemaxis = types.ModuleType("_schemaxis_replay")\n_schemaxis.__path__ = []\nsys.modules[_schemaxis.__name__] = _schemaxis\n'
    for name in ('contracts', 'faults', 'declarations', 'times', 'iteration'):
        code = (root / (name + '.py')).read_text(encoding='utf-8')
        source += (f'_module = types.ModuleType("_schemaxis_replay.{name}")\n'
                   'sys.modules[_module.__name__] = _module\n'
                   f'exec(compile({code!r}, "retained/schemaxis.core/{name}.py", "exec"), _module.__dict__)\n')
    return source


def fail(code, message, location, observed=None):
    raise SchemaxisError(Fault(code, message, location, 'verification', observed=observed or {}))


def validate_case(config):
    case = config['case']
    if config['crinkle'] or 'sweep' in config or config['origin'] != [0, 0, 0]:
        fail('INVALID_CASE_OPTIONS', 'Real cases use planar bounds-derived fractions; crinkle, sweep and nonzero origin are unsupported', 'case')
    if len(case['fractions']) > config['maxSlices']:
        fail('EXPANSION_TOO_LARGE', 'Too many slice fractions', 'case.fractions')
    if len(set(case['appearances'])) != len(case['appearances']):
        fail('INVALID_CASE_OPTIONS', 'Appearances must be distinct to prevent overwriting images', 'case.appearances')
    names = [writer['name'] for writer in case['writers']]
    if len(names) != len(set(names)) or any(not name.isidentifier() for name in names):
        fail('INVALID_CASE_OPTIONS', 'Writer names must be distinct identifiers', 'case.writers')
    for writer in case['writers']:
        if not writer.get('cameras'):
            fail('INVALID_CAMERA', 'Each writer requires its own camera samples', 'case.writers')
        for camera in writer['cameras']:
            direction, up = camera['direction'], camera['up']
            cross = [direction[1]*up[2]-direction[2]*up[1], direction[2]*up[0]-direction[0]*up[2], direction[0]*up[1]-direction[1]*up[0]]
            if not all(math.isfinite(x) for x in cross) or math.hypot(*cross) == 0:
                fail('INVALID_CAMERA', 'Camera direction and up must be finite, nonzero and nonparallel', 'case.writers.cameras')
    file = Path(case['file']).expanduser().absolute()
    if not file.is_file():
        fail('INVALID_CASE', 'Case marker is not a file', str(file))
    return {**case, 'file': str(file)}


def verify_complete(evidence):
    """Check the ordered semantic receipt, including each writer's camera nest."""
    if evidence.get('verified') is not True or evidence.get('status') != 'succeeded':
        fail('VERIFICATION_FAILED', 'Run is incomplete', 'verification', evidence)
    visits = evidence.get('visits', [])
    selected = evidence.get('timeSelection', {}).get('times', [])
    if not selected:
        fail('VERIFICATION_FAILED', 'No resolved times were evidenced', 'verification.timeSelection')
    expected_visits = [visit.to_dict() for visit in expand([
        Axis.of('time', [item['value'] for item in selected]),
        Axis.of('position', evidence['config']['fractions'])], limit=evidence['config']['maxPublications'])]
    if visits != expected_visits:
        fail('VERIFICATION_FAILED', 'Geometry visits differ from resolved time and position axes', 'verification.visits')
    states = evidence.get('states', [])
    if not visits or len(visits) != len(states):
        fail('VERIFICATION_FAILED', 'Geometry states are incomplete', 'verification')
    expected = []
    for visit, state in zip(visits, states):
        ordinal = visit['ordinal']
        if state['visit'] != visit or state['proxyIds'] != evidence['proxyIds'] or state['live'] != state['reopened'] or not state['live']['cells']:
            fail('VERIFICATION_FAILED', 'State order, reuse or reopen verification differs', 'verification')
        expected += [{'kind': 'update', 'state': ordinal, 'changed': visit['changed']},
                     {'kind': 'geometry', 'state': ordinal}]
        for appearance in evidence['config']['appearances'] if evidence['config']['writers'] else []:
            expected.append({'kind': 'appearance', 'state': ordinal, 'field': appearance,
                             'colours': {'slice': appearance, 'context': appearance, 'outline': [0, 0, 0]}})
            for writer in evidence['config']['writers']:
                for camera in range(len(writer['cameras'])):
                    expected.append({'kind': 'image', 'state': ordinal, 'field': appearance,
                                     'writer': writer['name'], 'camera': camera})
    if expected != evidence.get('events'):
        fail('VERIFICATION_FAILED', 'Publication order or coverage differs from the requested nest', 'verification.events')
    images = evidence.get('images', [])
    image_events = [event for event in expected if event['kind'] == 'image']
    if len(images) != len(image_events) or any(item['event'] != event or not item.get('verified') for item, event in zip(images, image_events)):
        fail('VERIFICATION_FAILED', 'Image verification is incomplete', 'verification.images')
    writers = {writer['name']: writer for writer in evidence['config']['writers']}
    names = [state['file'] for state in states] + [item['file'] for item in images]
    if len(set(names)) != len(names):
        fail('VERIFICATION_FAILED', 'Publications share a destination', 'verification')
    for item in images:
        writer = writers[item['event']['writer']]
        if item['dimensions'] != writer['size'] + [1]:
            fail('VERIFICATION_FAILED', 'Image dimensions differ from its writer', 'verification.images')


def run_case(config, normal, step_id):
    case = validate_case(config)
    directory = Path(config['outputDirectory']).expanduser().absolute()
    if directory.exists() or directory.is_symlink():
        fail('OUTPUT_EXISTS', 'Output directory already exists; retained evidence cannot be overwritten', str(directory))
    interpreter = require_paraview()
    try:
        directory.mkdir()
    except OSError as error:
        fail('INVALID_OUTPUT_PATH', str(error), str(directory))
    runtime = Path(__file__).with_name('foam_runtime.py').read_text(encoding='utf-8')
    source = embedded_helpers() + '\n' + runtime + '\nrun_foam(' + repr(case) + ', ' + repr(normal) + ', ' + repr(str(directory)) + ', ' + repr({key: config[key] for key in ('triangulate', 'pointMergeMethod')}) + ')\n'
    receipt = directory / 'verification.json'
    receipt.write_text(json.dumps({'verified': False, 'status': 'running', 'states': [], 'images': []}) + '\n')
    try:
        report = SubprocessRunner(interpreter, directory, PARAVIEW_OFFSCREEN, config['timeout'])(source)
    except SchemaxisError as error:
        (directory / 'submission-fault.json').write_text(json.dumps(error.fault.to_dict(), indent=2) + '\n')
        if receipt.is_file():
            evidence = json.loads(receipt.read_text())
            if 'fault' in evidence:
                fault = evidence['fault']
                fail(fault['code'], fault['message'], str(receipt), {**fault.get('observed', {}), 'submission': error.fault.to_dict()})
        raise
    (directory / 'submission.json').write_text(json.dumps(report.to_dict(), indent=2) + '\n')
    if not receipt.is_file():
        fail('VERIFICATION_FAILED', 'Native run returned no receipt', str(receipt))
    evidence = json.loads(receipt.read_text())
    verify_complete(evidence)
    paths = [(state['file'], 'application/vnd.vtk.vtp', 'output') for state in evidence['states']]
    paths += [(item['file'], 'image/png', 'output') for item in evidence['images']]
    paths += [(Path(report.script_path).name, 'text/x-python', 'replay'), ('verification.json', 'application/json', 'verification'), ('submission.json', 'application/json', 'verification')]
    from schemaxis.publication_metadata import publish_artifacts, receipt_artifacts
    publish_artifacts(directory, receipt_artifacts(directory) +
        [{'file': str(directory/name), 'kind': role} for name, _, role in paths if role != 'output'])
    artifacts = []
    for index, (name, media, role) in enumerate(paths):
        path = directory / name
        if not path.is_file() or not path.stat().st_size:
            fail('VERIFICATION_FAILED', 'Publication is missing or empty', str(path))
        artifacts.append(Artifact(f'{step_id}-{index:04d}', path.as_uri(), media, role,
                                  hashlib.sha256(path.read_bytes()).hexdigest(), step_id))
    return ProviderResult(observations={'verification': evidence, 'submission': report.to_dict()}, artifacts=tuple(artifacts))
