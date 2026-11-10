# Copyright (C) 2026 David L F Gaden
"""Unit-explicit, source-bound mesh interchange with independent format readers."""
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import time

from schemaxis.artifacts import atomic_json
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute
from . import reference

VERSION = 'schemaxis.meshio/1'
UNITS = {'m': 1.0, 'cm': .01, 'mm': .001, 'in': .0254}
OPTIONS = {
    'source': {'type': 'string', 'minLength': 1, 'maxLength': 4096, 'required': True},
    'sourceFormat': {'type': 'enum', 'values': ['vtu', 'vtk'], 'required': True},
    'targetFormat': {'type': 'enum', 'values': ['vtu', 'vtk'], 'required': True},
    'sourceUnits': {'type': 'enum', 'values': list(UNITS), 'required': True},
    'targetUnits': {'type': 'enum', 'values': list(UNITS), 'required': True},
    'lossPolicy': {'type': 'enum', 'values': ['strict'], 'required': True},
}
DECLARATIONS = {'convert': {'native': 'meshio.read / Mesh.points / meshio.write(binary=False)', 'kinds': ['geometry', 'text'], 'inputs': {}, 'options': {k: {'value': v} for k, v in OPTIONS.items()}}}
LOSSES = [
    'ASCII formatting and numeric storage dtype are not preserved; finite numeric values are checked at relative 1e-11/absolute 1e-14, and integer source values exactly.',
    'Coordinates alone are converted between declared length units. Point/cell scalar and vector arrays keep their values and associations; their physical units are not inferred or transformed.',
    'Point order and flattened cell order/connectivity are preserved exactly. Cell-block boundaries are representation details and may coalesce.',
    'Strict subset rejects metadata, unsupported topology, compressed/binary/appended payloads and extra arrays/sections rather than dropping them. No repair, merging, remeshing or solver formats.',
]


def plan(document):
    keys(document, ('version', 'operation', *OPTIONS), '$')
    if document.get('version') != VERSION: fail('UNSUPPORTED_VERSION', 'select '+VERSION, '$.version')
    if document.get('operation') != 'convert': fail('UNKNOWN_FILTER', 'select convert', '$.operation')
    prepared = validate_arguments(OPTIONS, {k: v for k, v in document.items() if k in OPTIONS}, location='$')
    path = Path(prepared['source'])
    if not path.is_absolute() or path.suffix.lower() != '.'+prepared['sourceFormat'] or '\x00' in str(path):
        fail('INVALID_MESH_SOURCE', 'select an absolute local .vtu/.vtk file matching sourceFormat', '$.source')
    return {'version': 'schemaxis.meshio.plan/1', 'operation': 'convert', **prepared, 'factor': UNITS[prepared['sourceUnits']]/UNITS[prepared['targetUnits']], 'losses': LOSSES}


def schema():
    from schemaxis.schema import DRAFT, argument_schema, object_schema
    return {'$schema': DRAFT, **object_schema({'version': {'const': VERSION}, 'operation': {'const': 'convert'}, **{k: argument_schema(v) for k, v in OPTIONS.items()}}, ['version', 'operation', *OPTIONS])}


def query(document):
    plan(document); return ['convert'], {}


def resources(document, execution, identity):
    if execution.get('threads', 1) != 1: fail('INVALID_EXECUTION', 'mesh conversion uses one serial process', identity)
    return {'threads': 1}


def bounded(path, code='VERIFICATION_FAILED', limit=32*1024**2):
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit: raise ValueError('not a bounded regular file')
            data = stream.read(limit+1)
        if len(data) > limit: raise ValueError('file exceeds byte budget')
        return data
    except (OSError, ValueError) as error:
        fail(code, 'select an intact bounded regular file: '+str(error), str(path))


def reusableInputs(document):
    prepared = plan(document)
    return {'mesh': hashlib.sha256(bounded(prepared['source'], 'INVALID_MESH_SOURCE', 16*1024**2)).hexdigest()}


def read(directory, name): return json.loads(bounded(directory/name))
def digest(directory, name): return hashlib.sha256(bounded(directory/name)).hexdigest()
def worker_source(): return Path(__file__).with_name('native_worker.py').read_text()
def config(prepared): return {k: prepared[k] for k in ('sourceFormat', 'targetFormat', 'factor')}


def inspect(directory, prepared):
    source = reference.parse(bounded(directory/('source.'+prepared['sourceFormat']), limit=16*1024**2), prepared['sourceFormat'])
    expected = reference.scaled(source, prepared['factor'])
    output = reference.parse(bounded(directory/('mesh.'+prepared['targetFormat'])), prepared['targetFormat'])
    native = read(directory, 'convert.stdout'); reopen = read(directory, 'readback.stdout')
    for stage in (native, reopen):
        if set(stage) != {'runtime', 'numpy', 'mesh'} or stage['runtime'] != '5.3.5' or not isinstance(stage['numpy'], str):
            fail('VERIFICATION_FAILED', 'native runtime/snapshot fields differ')
    if native['numpy'] != reopen['numpy']: fail('VERIFICATION_FAILED', 'native NumPy identity changed between stages')
    reference.compare(source, native['mesh'])
    reference.compare(expected, output)
    reference.compare(output, reopen['mesh'])
    expected_names = {'mesh.'+prepared['targetFormat'], 'mesh-summary.json'}
    sidecars = {name+'.metadata.json' for name in expected_names}
    present = {p.name for p in directory.glob('mesh*') if p.name not in sidecars}
    if present - expected_names: fail('VERIFICATION_FAILED', 'unexpected mesh publication')
    return {**reference.summary(output), 'sourceUnits': prepared['sourceUnits'], 'targetUnits': prepared['targetUnits'], 'coordinateFactor': prepared['factor'], 'volumeUnits': prepared['targetUnits']+'^3', 'sourceSha256': digest(directory, 'source.'+prepared['sourceFormat']), 'losses': LOSSES}


def artifacts(directory, prepared):
    return [{'file': str(directory/name), 'kind': kind, 'sha256': digest(directory, name)} for name, kind in [('mesh.'+prepared['targetFormat'], 'geometry'), ('mesh-summary.json', 'text')]]


def evidence_names(prepared):
    return {'authored.json', 'plan.json', 'source.'+prepared['sourceFormat'], 'capture.json', 'native-worker.py', 'native-config.json'} | {stage+suffix for stage in ('convert', 'readback') for suffix in ('.stdout', '.stderr', '-inputs.json', '-submission.json')}


def run(document, directory, *, executable=None, timeout=300):
    prepared = plan(document)
    executable = executable or os.environ.get('SCHEMAXIS_MESHIO')
    if not executable or not Path(executable).is_absolute() or not os.access(executable, os.X_OK):
        fail('INTERPRETER_NOT_FOUND', 'configure an absolute isolated Python interpreter containing meshio 5.3.5 and NumPy')
    if os.name != 'posix': fail('UNSUPPORTED_PLATFORM', 'POSIX resource caps are required')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600: fail('INVALID_ARGUMENT', 'timeout must be finite in (0,3600]')
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink(): fail('OUTPUT_EXISTS', 'select a fresh conversion directory', str(directory))
    directory.mkdir(parents=True); deadline = time.monotonic()+timeout
    atomic_json(directory/'authored.json', document); atomic_json(directory/'plan.json', prepared)
    atomic_json(directory/'result.json', {'status': 'incomplete', 'verified': False})
    try:
        data = bounded(prepared['source'], 'INVALID_MESH_SOURCE', 16*1024**2)
        try:
            reference.scaled(reference.parse(data, prepared['sourceFormat']), prepared['factor'])
        except (ValueError, UnicodeError, IndexError, KeyError) as error:
            fail('INVALID_MESH_CONTENT', 'supply supported intact ASCII triangle/tetra/hexahedron mesh: '+str(error), '$.source')
        name = 'source.'+prepared['sourceFormat']; (directory/name).write_bytes(data)
        atomic_json(directory/'capture.json', {'source': prepared['source'], 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        (directory/'native-worker.py').write_text(worker_source()); atomic_json(directory/'native-config.json', config(prepared))
        for stage in ('convert', 'readback'):
            execute([str(executable), '-I', str(directory/'native-worker.py'), stage], directory, stage, deadline-time.monotonic(), {'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'LANG': 'C.UTF-8'})
        atomic_json(directory/'mesh-summary.json', inspect(directory, prepared))
        atomic_json(directory/'verification.json', {'artifacts': artifacts(directory, prepared), 'evidence': {name: digest(directory, name) for name in sorted(evidence_names(prepared))}, 'executable': str(executable), 'runtime': 'meshio 5.3.5'})
        result = verify(directory, require_result=False)
        if cancellation_requested(): fail('RUNNER_CANCELLED', 'mesh publication cancelled')
        if time.monotonic() >= deadline: fail('RUNNER_TIMED_OUT', 'conversion exceeded its total deadline')
        result['status'] = 'succeeded'; atomic_json(directory/'result.json', result); return result
    except Exception as error:
        if not isinstance(error, SchemaxisError):
            try: fail('NATIVE_EXECUTION_FAILED', str(error))
            except SchemaxisError as wrapped: error = wrapped
        atomic_json(directory/'result.json', {'status': 'failed', 'verified': False, 'fault': error.fault.to_dict()}); raise error


def verify(directory, require_result=True):
    directory = Path(directory).absolute()
    try:
        prepared = plan(read(directory, 'authored.json')); receipt = read(directory, 'verification.json')
        if read(directory, 'plan.json') != prepared: fail('VERIFICATION_FAILED', 'effective mesh plan differs')
        if require_result and read(directory, 'result.json').get('status') != 'succeeded': fail('INCOMPLETE_EXECUTION', 'mesh conversion did not complete')
        source = 'source.'+prepared['sourceFormat']; data = bounded(directory/source, limit=16*1024**2)
        if read(directory, 'capture.json') != {'source': prepared['source'], 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}:
            fail('VERIFICATION_FAILED', 'captured source identity differs')
        executable = receipt['executable']
        if not isinstance(executable, str) or not Path(executable).is_absolute() or receipt['runtime'] != 'meshio 5.3.5': fail('VERIFICATION_FAILED', 'native identity differs')
        if bounded(directory/'native-worker.py').decode() != worker_source() or read(directory, 'native-config.json') != config(prepared):
            fail('VERIFICATION_FAILED', 'trusted native worker/configuration differs')
        for stage in ('convert', 'readback'):
            submission = read(directory, stage+'-submission.json')
            if submission.get('nativeCommand') != [executable, '-I', str(directory/'native-worker.py'), stage] or type(submission.get('exitCode')) is not int or submission['exitCode'] != 0:
                fail('VERIFICATION_FAILED', 'native command/completion differs', stage)
            consumed = source if stage == 'convert' else 'mesh.'+prepared['targetFormat']
            if read(directory, stage+'-inputs.json') != {name: digest(directory, name) for name in (consumed, 'native-config.json', 'native-worker.py')}:
                fail('VERIFICATION_FAILED', 'native consumed-input binding differs', stage)
        if read(directory, 'mesh-summary.json') != inspect(directory, prepared): fail('VERIFICATION_FAILED', 'mesh summary differs')
        if receipt['artifacts'] != artifacts(directory, prepared): fail('VERIFICATION_FAILED', 'publication membership/digest differs')
        if set(receipt['evidence']) != evidence_names(prepared): fail('VERIFICATION_FAILED', 'evidence membership differs')
        for name in evidence_names(prepared):
            if digest(directory, name) != receipt['evidence'][name]: fail('VERIFICATION_FAILED', 'retained evidence differs', name)
        return {'verified': True, 'artifacts': len(receipt['artifacts']), 'runtime': receipt['runtime'], 'cells': read(directory, 'mesh-summary.json')['cells']}
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeError) as error:
        fail('VERIFICATION_FAILED', 'invalid retained mesh evidence: '+str(error))


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
