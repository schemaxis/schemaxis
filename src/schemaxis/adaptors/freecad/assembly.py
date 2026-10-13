"""Host-safe planning and verified execution of bounded native fixed assemblies.

The contract uses box/cylinder part definitions, App::Link component instances,
exactly one grounded component and an acyclic, connected fixed-joint tree.
Named top/bottom planar faces and parent-frame offsets keep placement analytics
independent of the native solver. No authored source, native property reflection,
arbitrary FCStd loading, motion, collision analysis or dynamics is exposed.
"""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time

from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError, Fault
from schemaxis.core.runners import Interpreter
from schemaxis.artifacts import atomic_json, runtime_archive
from schemaxis.dispatch import SubprocessRunner
from schemaxis.documents import resolve_document
from schemaxis.errors import fail, keys
from schemaxis.pipeline import name
from .adaptor import close

VERSION = 'schemaxis.freecad.assembly/1'
MAX_COMPONENTS = 32
LENGTH = {'type': 'number', 'minimum': 0.01, 'maximum': 10000}
VECTOR = {'type': 'array', 'items': {'type': 'number', 'minimum': -100000, 'maximum': 100000},
          'minItems': 3, 'maxItems': 3, 'default': [0, 0, 0]}
ANGLE = {'type': 'number', 'minimum': -360, 'maximum': 360, 'default': 0}
PART_OPTIONS = {'box': {'length': {**LENGTH, 'default': 10}, 'width': {**LENGTH, 'default': 10},
                        'height': {**LENGTH, 'default': 10}},
                'cylinder': {'radius': {**LENGTH, 'default': 5}, 'height': {**LENGTH, 'default': 10}}}


def _array(value, minimum, maximum, location):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        fail('ASSEMBLY_LIMIT', f'Provide {minimum} to {maximum} items', location)
    return value


def plan(document):
    document, _ = resolve_document(copy.deepcopy(document))
    keys(document, ('version', 'units', 'parts', 'components', 'grounded', 'joints',
                    'dimensions', 'definitions', 'settings'), '$')
    if document.get('version') != VERSION:
        fail('UNSUPPORTED_VERSION', 'expected '+VERSION)
    if document.get('units', 'mm') != 'mm':
        fail('UNSUPPORTED_UNITS', 'Assembly dimensions are millimetres')
    parts, components, joints = [], [], []
    part_ids, component_ids, joint_ids = set(), set(), set()
    for item in _array(document.get('parts'), 1, MAX_COMPONENTS, '$.parts'):
        keys(item, ('id', 'type', 'options'), '$.parts')
        identity = name(item.get('id'), '$.parts.id')
        if identity in part_ids:
            fail('DUPLICATE_PART', 'Part ID is duplicated', identity)
        kind = item.get('type')
        if not isinstance(kind, str) or kind not in PART_OPTIONS:
            fail('UNSUPPORTED_PART', 'Assembly parts support box or cylinder constructors', identity)
        options = validate_arguments(PART_OPTIONS[kind], item.get('options', {}))
        parts.append({'id': identity, 'type': kind, 'options': options})
        part_ids.add(identity)
    used = set()
    for item in _array(document.get('components'), 2, MAX_COMPONENTS, '$.components'):
        keys(item, ('id', 'part', 'position', 'rotation'), '$.components')
        identity = name(item.get('id'), '$.components.id')
        if identity in component_ids:
            fail('DUPLICATE_COMPONENT', 'Component ID is duplicated', identity)
        part = item.get('part')
        if not isinstance(part, str) or part not in part_ids:
            fail('UNKNOWN_PART', 'Component must reference a declared part', identity)
        values = validate_arguments({'position': VECTOR, 'rotation': ANGLE},
            {k: item[k] for k in ('position', 'rotation') if k in item})
        components.append({'id': identity, 'part': part, **values})
        used.add(part)
        component_ids.add(identity)
    if used != part_ids:
        fail('UNUSED_PART', 'Every part definition must have a component instance')
    grounded = document.get('grounded')
    if not isinstance(grounded, str) or grounded not in component_ids:
        fail('INVALID_GROUND', 'grounded must name exactly one component')
    children = set()
    for item in _array(document.get('joints'), 1, MAX_COMPONENTS-1, '$.joints'):
        keys(item, ('id', 'type', 'parent', 'child', 'offset'), '$.joints')
        identity = name(item.get('id'), '$.joints.id')
        if identity in joint_ids:
            fail('DUPLICATE_JOINT', 'Joint ID is duplicated', identity)
        if item.get('type') != 'fixed':
            fail('UNSUPPORTED_JOINT', 'Only fixed joints are qualified; no revolute motion contract', identity)
        ends = {}
        for end in ('parent', 'child'):
            endpoint = item.get(end)
            keys(endpoint, ('component', 'face'), identity+'.'+end)
            component, face = endpoint.get('component'), endpoint.get('face')
            if not isinstance(component, str) or component not in component_ids:
                fail('UNKNOWN_COMPONENT', 'Joint references an undeclared component', identity+'.'+end)
            if face not in ('top', 'bottom'):
                fail('UNSUPPORTED_FACE', 'Use the named top or bottom planar face', identity+'.'+end)
            ends[end] = {'component': component, 'face': face}
        child, parent = ends['child']['component'], ends['parent']['component']
        if child == parent or child == grounded or child in children:
            fail('INVALID_JOINT_TREE', 'Each non-ground component must have exactly one parent', identity)
        offset = validate_arguments({'offset': VECTOR}, {'offset': item['offset']} if 'offset' in item else {})['offset']
        joints.append({'id': identity, 'type': 'fixed', **ends, 'offset': offset})
        children.add(child)
        joint_ids.add(identity)
    if children != component_ids-{grounded}:
        fail('INVALID_JOINT_TREE', 'Fixed joints must connect every component to the ground')
    # Topologically order the tree, accepting authored joints in any order.
    ordered, seen, pending = [], {grounded}, list(joints)
    while pending:
        available = [j for j in pending if j['parent']['component'] in seen]
        if not available:
            fail('INVALID_JOINT_TREE', 'The joint tree contains a disconnected cycle')
        for joint in available:
            ordered.append(joint)
            seen.add(joint['child']['component'])
            pending.remove(joint)
    prepared = {'version': 'schemaxis.freecad.assembly.plan/1', 'units': 'mm', 'parts': parts,
                'components': components, 'grounded': grounded, 'joints': ordered,
                'expectedDegreesOfFreedom': 0, 'expectedPublications': 1}
    prepared['expected'] = analytic(prepared)
    return prepared


def face_centre(part, face):
    options = part['options']
    xy = [options['length']/2, options['width']/2] if part['type'] == 'box' else [0, 0]
    return [*xy, options['height'] if face == 'top' else 0]


def rotate(point, degrees):
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return [c*point[0]-s*point[1], s*point[0]+c*point[1], point[2]]


def analytic(prepared):
    """Independent closed-form rigid placements for the supported planar tree."""
    parts = {p['id']: p for p in prepared['parts']}
    components = {c['id']: c for c in prepared['components']}
    root = components[prepared['grounded']]
    expected = {root['id']: {'position': root['position'], 'rotation': root['rotation']}}
    for joint in prepared['joints']:
        parent, child = joint['parent']['component'], joint['child']['component']
        a = face_centre(parts[components[parent]['part']], joint['parent']['face'])
        b = face_centre(parts[components[child]['part']], joint['child']['face'])
        delta = rotate([a[i]+joint['offset'][i]-b[i] for i in range(3)], expected[parent]['rotation'])
        expected[child] = {'position': [expected[parent]['position'][i]+delta[i] for i in range(3)],
                           'rotation': expected[parent]['rotation']}
    for identity, entry in expected.items():
        part = parts[components[identity]['part']]
        options, position = part['options'], entry['position']
        if part['type'] == 'box':
            corners = [rotate([x, y, z], entry['rotation']) for x in (0, options['length'])
                       for y in (0, options['width']) for z in (0, options['height'])]
            entry['bounds'] = [position[i]+value for i in range(3)
                               for value in (min(p[i] for p in corners), max(p[i] for p in corners))]
            entry['volume'] = options['length']*options['width']*options['height']
        else:
            r, h = options['radius'], options['height']
            entry['bounds'] = [position[0]-r, position[0]+r, position[1]-r, position[1]+r, position[2], position[2]+h]
            entry['volume'] = math.pi*r*r*h
        entry['xAxis'] = rotate([1, 0, 0], entry['rotation'])
        entry['zAxis'] = [0, 0, 1]
    return expected


def schema():
    from schemaxis.schema import object_schema, argument_schema, DRAFT, json_value_schema
    identity = {'type': 'string', 'pattern': '^[A-Za-z][A-Za-z0-9_-]*$'}
    endpoint = object_schema({'component': identity, 'face': {'enum': ['top', 'bottom']}}, ['component', 'face'])
    part_types = [object_schema({'id': identity, 'type': {'const': kind},
                  'options': object_schema({k: argument_schema(v) for k, v in options.items()}, [])}, ['id', 'type'])
                  for kind, options in PART_OPTIONS.items()]
    component = object_schema({'id': identity, 'part': identity, 'position': argument_schema(VECTOR),
                               'rotation': argument_schema(ANGLE)}, ['id', 'part'])
    joint = object_schema({'id': identity, 'type': {'const': 'fixed'}, 'parent': endpoint,
                           'child': endpoint, 'offset': argument_schema(VECTOR)}, ['id', 'type', 'parent', 'child'])
    return {'$schema': DRAFT, '$defs': {'json': json_value_schema()}, **object_schema({'version': {'const': VERSION}, 'units': {'const': 'mm'},
        'parts': {'type': 'array', 'items': {'oneOf': part_types}, 'minItems': 1, 'maxItems': MAX_COMPONENTS},
        'components': {'type': 'array', 'items': component, 'minItems': 2, 'maxItems': MAX_COMPONENTS},
        'grounded': identity, 'joints': {'type': 'array', 'items': joint, 'minItems': 1, 'maxItems': MAX_COMPONENTS-1},
        **{k: {'$ref': '#/$defs/json'} for k in ('dimensions', 'definitions', 'settings')}}, ['version', 'parts', 'components', 'grounded', 'joints'])}


def gui_stage(executable, directory, timeout, *, stage='gui_finish'):
    """Optional native GUI decoration/capture, with owned process cancellation."""
    from schemaxis.dispatch import cancellation_requested, terminate_tree
    executable = Path(executable)
    if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
        fail('INTERPRETER_NOT_FOUND', 'Provide an absolute executable FreeCAD GUI launcher')
    if stage not in ('gui_finish', 'gui_reopen'):
        fail('UNSUPPORTED_STAGE', 'Unsupported native GUI stage')
    receipt_name = 'gui' if stage == 'gui_finish' else 'gui-reopened'
    macro = directory/(receipt_name+'.FCMacro')
    macro.write_text('import sys\nsys.path.insert(0,'+repr(str(directory/'runtime.zip'))+')\n'
        'import FreeCAD as App, FreeCADGui as Gui\n'
        'from schemaxis.adaptors.freecad.assembly_native import '+stage+'\n'
        'from schemaxis.native_boundary import execute_guarded\n'
        'try:\n execute_guarded('+stage+','+repr(str(directory))+')\n'
        'except Exception:\n'
        ' for name in list(App.listDocuments()): App.closeDocument(name)\n'
        ' Gui.getMainWindow().close()\n')
    environment = os.environ.copy()
    for key in ('PYTHONHOME', 'PYTHONPATH', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'LD_PRELOAD'):
        environment.pop(key, None)
    with (directory/(receipt_name+'.log')).open('wb') as log:
        process = subprocess.Popen([str(executable), str(macro)], stdout=log, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, start_new_session=True, env=environment)
        started = time.monotonic()
        try:
            while process.poll() is None:
                if (directory/'native-fault.json').exists():
                    raise SchemaxisError(Fault(**json.loads((directory/'native-fault.json').read_text())))
                if cancellation_requested():
                    fail('RUNNER_CANCELLED', 'Assembly GUI stage cancelled')
                if time.monotonic()-started > timeout:
                    fail('RUNNER_TIMED_OUT', 'Assembly GUI stage exceeded timeout')
                time.sleep(0.05)
        finally:
            terminate_tree(process, {})
    if process.returncode != 0 or not (directory/(receipt_name+'.json')).is_file():
        fail('GUI_PUBLICATION_FAILED', 'Native assembly GUI stage failed; inspect gui.log')


def run(document, directory, *, executable=None, timeout=120, gui_executable=None):
    prepared = plan(document)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        fail('INVALID_EXECUTION', 'Assembly timeout must be finite and positive')
    executable = executable or os.environ.get('FREECAD_CMD')
    if not executable or not Path(executable).is_absolute() or not Path(executable).is_file() or not os.access(executable, os.X_OK):
        fail('INTERPRETER_NOT_FOUND', 'Provide an absolute executable FreeCAD command-line launcher')
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink():
        fail('OUTPUT_EXISTS', 'Choose a fresh assembly output directory', str(directory))
    directory.mkdir(parents=True)
    atomic_json(directory/'authored.json', document)
    atomic_json(directory/'plan.json', prepared)
    atomic_json(directory/'result.json', {'status': 'incomplete', 'verified': False})
    snapshot = runtime_archive()
    (directory/'runtime.zip').write_bytes(snapshot)
    runner = SubprocessRunner(Interpreter('freecad', str(Path(executable).resolve())), directory, timeout=timeout)
    try:
        for stage in ('build', 'reopen'):
            source = ('import sys\nsys.path.insert(0,'+repr(str(directory/'runtime.zip'))+')\n'
                'from schemaxis.adaptors.freecad.assembly_native import '+stage+'\n'
                'from schemaxis.native_boundary import execute_guarded\n'
                'execute_guarded('+stage+','+repr(str(directory))+')\n')
            report = runner(source)
            atomic_json(directory/(stage+'-submission.json'), report.to_dict())
            if (directory/'native-fault.json').exists():
                raise SchemaxisError(Fault(**json.loads((directory/'native-fault.json').read_text())))
            if stage == 'build' and gui_executable:
                gui_stage(gui_executable, directory, timeout)
        result = verify(directory, require_result=False)
        result.update(status='succeeded', runtimeSha256=hashlib.sha256(snapshot).hexdigest())
        atomic_json(directory/'result.json', result)
        return result
    except Exception as error:
        if (directory/'native-fault.json').exists():
            error = SchemaxisError(Fault(**json.loads((directory/'native-fault.json').read_text())))
        atomic_json(directory/'result.json', {'status': 'failed', 'verified': False,
            'fault': error.fault.to_dict() if isinstance(error, SchemaxisError) else {'message': str(error)}})
        raise error


def _verify(directory, require_result=True):
    directory = Path(directory).absolute()
    prepared = plan(json.loads((directory/'authored.json').read_text()))
    def require(condition, message):
        if not condition:
            fail('VERIFICATION_FAILED', message, str(directory))
    require(json.loads((directory/'plan.json').read_text()) == prepared, 'Assembly plan differs from authored input')
    if require_result:
        require(json.loads((directory/'result.json').read_text()).get('verified') is True, 'Assembly execution is incomplete')
    build = json.loads((directory/'built.json').read_text())
    reopened = json.loads((directory/'verification.json').read_text())
    require(build.get('pid') != reopened.get('pid') and all(type(r.get('pid')) is int for r in (build, reopened)),
            'Build and reopening must use separate native processes')
    for receipt, stage in ((build, 'build'), (reopened, 'reopen')):
        require(receipt.get('stage') == stage and receipt.get('definition') == prepared, 'Native assembly definition differs')
        require(receipt.get('assemblyType') == 'Assembly::AssemblyObject' and receipt.get('jointGroupType') == 'Assembly::JointGroup',
                'Missing native Assembly objects')
        require(receipt.get('grounded') == prepared['grounded'], 'Native ground differs')
        require(receipt.get('groundCount') == 1 and receipt.get('jointCount') == len(prepared['joints']), 'Native joint membership differs')
        require(receipt.get('parts') == prepared['parts'], 'Native part properties differ')
        components = receipt.get('components', [])
        require([c.get('id') for c in components] == [c['id'] for c in prepared['components']], 'Component membership differs')
        for observed, declared in zip(components, prepared['components']):
            expected = prepared['expected'][declared['id']]
            require(observed.get('type') == 'App::Link' and observed.get('part') == declared['part'], 'Component source link differs')
            require(observed.get('valid') is True and observed.get('solids') == 1, 'Native component geometry is invalid')
            for measure in ('position', 'xAxis', 'zAxis', 'bounds', 'volume'):
                require(close(observed.get(measure), expected[measure]), 'Native component differs from analytic '+measure)
        native_joints = receipt.get('joints', [])
        require(len(native_joints) == len(prepared['joints']), 'Joint evidence is incomplete')
        for observed, declared in zip(native_joints, prepared['joints']):
            for key in ('id', 'type', 'parent', 'child', 'offset'):
                require(observed.get(key) == declared[key], 'Native joint settings differ')
            require(observed.get('nativeType') == 'Fixed' and observed.get('suppressed') is False
                    and observed.get('detached') == [False, False], 'Native joint is not an active attached Fixed joint')
            require(close(observed.get('translationResidual'), 0) and close(observed.get('rotationResidual'), 0), 'Joint connectors do not coincide')
        solver = receipt.get('solver', {})
        require(type(solver.get('returnCode')) is int and solver['returnCode'] == 0, 'Native assembly solver failed')
        require(solver.get('displaced') is True and solver.get('restored') is True, 'Solver did not restore deliberately displaced components')
        require(solver.get('displacedComponents') == [c['id'] for c in prepared['components'] if c['id'] != prepared['grounded']],
                'Solver perturbation membership differs')
        for phase in ('before', 'perturbed', 'after'):
            require(set(solver.get(phase, {})) == set(prepared['expected']), 'Solver pose evidence is incomplete')
            for identity, expected in prepared['expected'].items():
                pose = solver[phase][identity]
                if phase != 'perturbed' or identity == prepared['grounded']:
                    for measure in ('position', 'xAxis', 'zAxis'):
                        require(close(pose.get(measure), expected[measure]), 'Solver '+phase+' pose differs from analytic '+measure)
                else:
                    position = pose.get('position')
                    require(isinstance(position, list) and len(position) == 3
                            and all(type(x) in (int, float) and math.isfinite(x) for x in position)
                            and not close(position, expected['position']), 'Solver perturbation did not displace the body')
    artifact = reopened.get('artifact', {})
    if 'artifacts' in reopened:
        require(reopened['artifacts'] == [artifact], 'Assembly publication membership differs')
    path = directory/'model.FCStd'
    require(path.is_file() and path.resolve().parent == directory.resolve(), 'Native assembly file is absent or escaped')
    require(artifact.get('file') == str(path) and artifact.get('kind') == 'cadScene' and artifact.get('units') == 'mm', 'Assembly artifact metadata differs')
    require(artifact.get('sha256') == hashlib.sha256(path.read_bytes()).hexdigest(), 'Native assembly file changed')
    return {'verified': True, 'artifacts': 1, 'components': len(prepared['components']), 'joints': len(prepared['joints']),
            'expectedDegreesOfFreedom': 0, 'runtime': reopened['runtime'], 'solver': 'FreeCAD built-in Assembly',
            'nativeFile': str(path)}


def verify(directory, require_result=True):
    """Retained evidence failures use the public structured fault boundary."""
    try:
        return _verify(directory, require_result=require_result)
    except SchemaxisError:
        raise
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError) as error:
        fail('VERIFICATION_FAILED', 'Missing or malformed CAD evidence: ' + str(error), str(directory))


def reusableInputs(document):
    """The bounded assembly contract has no external input files."""
    plan(document)
    return {}


# Shared authored-input, analytic-visit and verification boundary.
from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
