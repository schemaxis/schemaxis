"""Host-safe FreeCAD solid declarations, planning, dispatch and verification."""
import copy
import hashlib
import json
import math
import os
import time
from pathlib import Path
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.runners import Interpreter
from schemaxis.core.faults import SchemaxisError, Fault
from schemaxis.artifacts import atomic_json, runtime_archive
from schemaxis.dispatch import SubprocessRunner, cancellation_requested
from schemaxis.errors import fail, keys
from schemaxis.pipeline import name
from schemaxis.artifacts import file_digest

VECTOR = {'type': 'array', 'items': {'type': 'number'}, 'minItems': 3, 'maxItems': 3, 'default': [0, 0, 0]}
LENGTH = {'type': 'number', 'minimum': 0, 'exclusiveMinimum': True, 'maximum': 100000}

def declaration(native, options, inputs=()):
    return {'native': native, 'kinds': ['solid'],
            'options': {k: {'value': v} for k, v in options.items()},
            'inputs': {k: {'required': True, 'kind': 'solid'} for k in inputs}}

DECLARATIONS = {
    'box': declaration('Part::Box', {'length': {**LENGTH, 'default': 10}, 'width': {**LENGTH, 'default': 10},
                                    'height': {**LENGTH, 'default': 10}, 'origin': VECTOR}),
    'cylinder': declaration('Part::Cylinder', {'radius': {**LENGTH, 'default': 5}, 'height': {**LENGTH, 'default': 10},
                                             'origin': VECTOR, 'axis': {**VECTOR, 'default': [0, 0, 1]}}),
    'cut': declaration('Part::Cut', {}, ('base', 'tool')),
    'fuse': declaration('Part::Fuse', {}, ('base', 'tool')),
}
from .operations import extend, validate as validate_geometry
DECLARATIONS.update(extend(declaration, LENGTH, VECTOR))

FILES = [('model.step', 'cad'), ('model.stl', 'geometry'), ('model.FCStd', 'cadScene')]


def output_files(prepared):
    return FILES + ([('measurements.json', 'text')] if prepared.get('measurements') else [])


def artifact_units(kind):
    return 'per-measurement' if kind == 'text' else 'mm'


def plan(document, *, allow_profile=False):
    from schemaxis.documents import resolve_document
    document, _ = resolve_document(copy.deepcopy(document))
    keys(document, ('version', 'units', 'nodes', 'output', 'linearDeflection', 'dimensions', 'definitions', 'settings', 'measurements', 'designStudy'), '$')
    if document.get('version') != 'schemaxis.freecad/1':
        fail('UNSUPPORTED_VERSION', 'expected schemaxis.freecad/1')
    if document.get('units', 'mm') != 'mm':
        fail('UNSUPPORTED_UNITS', 'this CAD contract uses millimetres')
    nodes = document.get('nodes')
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 200:
        fail('INVALID_DOCUMENT', 'provide 1 to 200 CAD nodes')
    prepared, seen, kinds = [], set(), {}
    for node in nodes:
        keys(node, ('id', 'filter', 'options', 'inputs'), '$.nodes')
        identity = name(node.get('id'), '$.nodes.id')
        if identity in seen:
            fail('DUPLICATE_NODE', 'CAD node is duplicated', identity)
        operation = node.get('filter')
        if not isinstance(operation, str) or operation not in DECLARATIONS:
            fail('UNKNOWN_FILTER', 'unsupported CAD operation', identity)
        declaration = DECLARATIONS[operation]
        options = validate_arguments({k: v['value'] for k, v in declaration['options'].items()}, node.get('options', {}))
        validate_geometry(operation, options, identity)
        inputs = node.get('inputs', {})
        keys(inputs, tuple(declaration['inputs']), identity)
        if set(inputs) != set(declaration['inputs']):
            fail('INVALID_DEPENDENCY', 'CAD inputs require every declared port', identity)
        for port, value in inputs.items():
            spec = declaration['inputs'][port]
            sources = value if spec.get('multiple') else [value]
            if (not isinstance(sources, list) or not spec.get('minItems', 1) <= len(sources) <= spec.get('maxItems', 1)
                    or any(not isinstance(source, str) or source not in seen for source in sources)):
                fail('INVALID_DEPENDENCY', 'CAD inputs must reference earlier nodes within the declared port limits', identity, port=port)
            if len(set(sources)) != len(sources):
                fail('INVALID_DEPENDENCY', 'CAD list inputs must be distinct', identity, port=port)
            for source in sources:
                if kinds[source] != spec['kind']:
                    fail('TYPE_MISMATCH', 'CAD input kind differs', identity, port=port, actual=kinds[source])
        kinds[identity] = declaration['kinds'][0]
        prepared.append({'id': identity, 'filter': operation, 'options': options, 'inputs': inputs})
        seen.add(identity)
    output = document.get('output')
    if not isinstance(output, str) or output not in seen:
        fail('INVALID_SELECTION', 'output must name a CAD node')
    if kinds[output] != 'solid' and not (allow_profile and kinds[output] == 'profile'):
        fail('TYPE_MISMATCH', 'CAD output must select a solid, not a sketch', output)
    deflection = validate_arguments({'value': {'type': 'number', 'minimum': 0.001, 'maximum': 1, 'default': 0.1}},
                                    {'value': document.get('linearDeflection', 0.1)})['value']
    result = {'version': 'schemaxis.freecad.plan/1', 'units': 'mm', 'nodes': prepared,
            'output': output, 'linearDeflection': deflection, 'expectedPublications': 3 if kinds[output] == 'solid' else 1}
    if 'measurements' in document:
        from .measurements import prepare
        result['measurements'] = prepare(document['measurements'], kinds)
        result['expectedPublications'] += 1
    if 'designStudy' in document:
        from .design_study import prepare
        result['designStudy'] = prepare(document['designStudy'], document, result)
        result['expectedPublications'] += 2
    return result


def input_schema(ports):
    from schemaxis.schema import object_schema, NAME
    return object_schema({key: ({'type': 'array', 'items': NAME,
                                'minItems': spec['minItems'], 'maxItems': spec['maxItems'],
                                'uniqueItems': True} if spec.get('multiple') else NAME)
                          for key, spec in ports.items()}, list(ports))


def schema():
    from schemaxis.schema import object_schema, argument_schema, DRAFT, NAME, arguments_schema, json_value_schema
    from .measurements import DECLARATION as measurements
    from .design_study import ARGUMENTS as study
    alternatives = []
    for operation, definition in DECLARATIONS.items():
        options = arguments_schema({k: v['value'] for k, v in definition['options'].items()})
        alternatives.append(object_schema({'id': NAME, 'filter': {'const': operation},
            'options': options,
            'inputs': input_schema(definition['inputs'])},
            ['id', 'filter'] + (['inputs'] if definition['inputs'] else []) + (['options'] if options.get('required') else [])))
    return {'$schema': DRAFT, '$defs': {'json': json_value_schema()}, **object_schema({'version': {'const': 'schemaxis.freecad/1'}, 'units': {'const': 'mm'},
        'nodes': {'type': 'array', 'items': {'oneOf': alternatives}, 'minItems': 1, 'maxItems': 200},
        'output': NAME, 'linearDeflection': {'type': 'number', 'minimum': 0.001, 'maximum': 1},
        'measurements': argument_schema(measurements),
        'designStudy': arguments_schema(study),
        **{key: {'$ref': '#/$defs/json'} for key in ('definitions', 'dimensions', 'settings')}},
        ['version', 'nodes', 'output'])}


def run(document, directory, *, executable=None, timeout=300):
    prepared = plan(document)
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout <= 0:
        fail('INVALID_TIMEOUT', 'CAD timeout must be finite and positive')
    deadline = time.monotonic()+timeout
    executable = executable or os.environ.get('FREECAD_CMD')
    if not executable or not Path(executable).is_absolute() or not Path(executable).is_file():
        fail('INTERPRETER_NOT_FOUND', 'provide an absolute FreeCAD command-line executable with --freecad')
    if 'designStudy' in document:
        from .design_study import run as study
        return study(document, directory, executable=executable, timeout=timeout)
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink():
        fail('OUTPUT_EXISTS', 'choose a fresh output directory', str(directory))
    directory.mkdir(parents=True)
    atomic_json(directory/'authored.json', document)
    atomic_json(directory/'plan.json', prepared)
    atomic_json(directory/'result.json', {'status': 'incomplete', 'verified': False})
    sources = {}
    for node in prepared['nodes']:
        if node['filter'] != 'readSTEP':
            continue
        source = Path(node['options']['file']).absolute()
        if not source.is_file():
            fail('RESOURCE_NOT_FOUND', 'STEP input is absent', str(source))
        import shutil
        local = directory/('source-'+str(len(sources))+'.step')
        shutil.copyfile(source, local)
        digest = file_digest(local)
        if file_digest(source) != digest:
            fail('INPUT_CHANGED', 'STEP input changed during capture', str(source))
        sources[node['id']] = {'file':str(source),'retained':str(local),'sha256':digest}
    atomic_json(directory/'sources.json', sources)
    snapshot = runtime_archive()
    (directory/'runtime.zip').write_bytes(snapshot)
    runtime = Interpreter('freecad', str(Path(executable).resolve()))
    runner = SubprocessRunner(runtime, directory, timeout=timeout, environment={'QT_QPA_PLATFORM': 'offscreen'})
    try:
        for stage in ('build', 'reopen'):
            runner.timeout = deadline-time.monotonic()
            if runner.timeout <= 0: fail('RUNNER_TIMED_OUT', 'CAD execution exhausted its total timeout')
            source = (f'import sys\nsys.path.insert(0, {str(directory/"runtime.zip")!r})\n'
                      f'from schemaxis.adaptors.freecad.native import {stage}\n'
                      'from schemaxis.native_boundary import execute_guarded\n'
                      f'execute_guarded({stage}, {str(directory)!r})\n')
            report = runner(source)
            atomic_json(directory/(stage+'-submission.json'), report.to_dict())
            if (directory/'native-fault.json').exists():
                raise SchemaxisError(Fault(**json.loads((directory/'native-fault.json').read_text())))
        result = verify(directory, require_result=False)
        if cancellation_requested(): fail('RUNNER_CANCELLED', 'CAD publication cancelled')
        if time.monotonic() >= deadline: fail('RUNNER_TIMED_OUT', 'CAD verification exhausted its total timeout')
        result.update(status='succeeded', runtimeSha256=hashlib.sha256(snapshot).hexdigest())
        atomic_json(directory/'result.json', result)
        return result
    except Exception as error:
        if (directory/'native-fault.json').exists():
            error=SchemaxisError(Fault(**json.loads((directory/'native-fault.json').read_text())))
        atomic_json(directory/'result.json', {'status': 'failed', 'verified': False, 'fault': error.fault.to_dict() if isinstance(error,SchemaxisError) else {'message':str(error)}})
        raise error


def close(a, b):
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(close(x, y) for x, y in zip(a, b))
    return type(a) in (int, float) and type(b) in (int, float) and math.isfinite(a) and math.isfinite(b) and math.isclose(a, b, rel_tol=1e-7, abs_tol=1e-6)


def _verify(directory, require_result=True):
    directory = Path(directory).absolute()
    document = json.loads((directory/'authored.json').read_text())
    if 'designStudy' in document:
        from .design_study import verify as verify_study
        return verify_study(directory)
    prepared = plan(document)
    if json.loads((directory/'plan.json').read_text()) != prepared:
        fail('VERIFICATION_FAILED', 'CAD plan differs from input')
    if require_result and json.loads((directory/'result.json').read_text()).get('verified') is not True:
        fail('INCOMPLETE_EXECUTION', 'CAD job did not complete')
    imported = [n for n in prepared['nodes'] if n['filter'] == 'readSTEP']
    sources = json.loads((directory/'sources.json').read_text()) if (directory/'sources.json').exists() else {}
    if set(sources) != {n['id'] for n in imported}:
        fail('VERIFICATION_FAILED', 'STEP source membership differs')
    for index,node in enumerate(imported):
        source=sources[node['id']]
        retained=directory/('source-'+str(index)+'.step')
        if source.get('file') != str(Path(node['options']['file']).absolute()) or source.get('retained') != str(retained) or retained.resolve().parent != directory.resolve():
            fail('VERIFICATION_FAILED', 'STEP source provenance differs')
        if file_digest(retained) != source['sha256'] or file_digest(Path(source['file'])) != source['sha256']:
            fail('INPUT_CHANGED', 'STEP source or retained copy changed', node['id'])
    receipt = json.loads((directory/'verification.json').read_text())
    built = json.loads((directory/'built.json').read_text())
    if receipt.get('status') != 'succeeded' or receipt.get('units') != 'mm' or not receipt.get('freshProcess'):
        fail('VERIFICATION_FAILED', 'CAD reopening evidence is incomplete')
    if receipt.get('definition') != prepared or built.get('definition') != prepared:
        fail('VERIFICATION_FAILED', 'native CAD definition differs')
    from .selections import verify as verify_selections
    verify_selections(prepared, built.get('selections', {}), receipt.get('selections', {}))
    from .measurements import verify as verify_measurements, evaluate
    publication = (json.loads((directory/'measurements.json').read_text()) if prepared.get('measurements')
                   else evaluate(prepared, {}))
    verify_measurements(prepared, built.get('measurementObservations', {}),
                        receipt.get('measurementObservations', {}), publication)
    for key in ('native', 'step'):
        observed = receipt.get(key, {})
        if observed.get('valid') is not True or observed.get('solids') != 1 or observed.get('volume', 0) <= 0:
            fail('VERIFICATION_FAILED', 'CAD output must be one valid positive-volume solid')
        for measure in ('volume', 'area', 'bounds'):
            if not close(observed.get(measure), built['shape'].get(measure)):
                fail('VERIFICATION_FAILED', 'CAD export or reopening changed geometry', key, measure=measure)
    mesh = receipt.get('mesh', {})
    if mesh.get('solid') is not True or mesh.get('facets', 0) <= 0 or not math.isclose(mesh.get('volume', -1), built['shape']['volume'], rel_tol=0.005, abs_tol=1e-5):
        fail('VERIFICATION_FAILED', 'STL is not watertight or exceeds 0.5 percent volume tolerance')
    if not close(mesh.get('bounds'), built['shape']['bounds']):
        # Chordal meshes may miss extrema by at most the requested linear deflection.
        if not isinstance(mesh.get('bounds'), list) or len(mesh['bounds']) != 6 or any(not math.isfinite(a) or abs(a-b) > prepared['linearDeflection']*1.1+1e-5 for a,b in zip(mesh['bounds'],built['shape']['bounds'])):
            fail('VERIFICATION_FAILED', 'STL bounds exceed tessellation tolerance')
    artifacts = receipt.get('artifacts', [])
    files = output_files(prepared)
    if len(artifacts) != len(files):
        fail('VERIFICATION_FAILED', 'CAD artifact membership differs')
    for artifact, (filename, kind) in zip(artifacts, files):
        path = directory/filename
        if artifact.get('file') != str(path) or artifact.get('kind') != kind or artifact.get('units') != artifact_units(kind) or path.is_symlink() or path.resolve().parent != directory.resolve() or file_digest(path) != artifact.get('sha256'):
            fail('VERIFICATION_FAILED', 'CAD artifact path, units or digest differs', filename)
    return {'verified': True, 'artifacts': len(artifacts), 'volumeMM3': receipt['native']['volume'], 'runtime': receipt['runtime']}


def verify(directory, require_result=True):
    """Retained evidence failures use the public structured fault boundary."""
    try:
        return _verify(directory, require_result=require_result)
    except SchemaxisError:
        raise
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError) as error:
        fail('VERIFICATION_FAILED', 'Missing or malformed CAD evidence: ' + str(error), str(directory))


# Shared authored-input, analytic-visit and verification boundary.
from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
