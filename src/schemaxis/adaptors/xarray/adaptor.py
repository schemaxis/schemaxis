"""Named-coordinate profile reduction of one classic NetCDF cube with isolated xarray and an independent verifier."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time

from schemaxis.artifacts import atomic_json
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute
from . import cdf, oracle

VERSION = 'schemaxis.xarray/1'
OPERATION = 'reduceProfile'
REQUIRED = {'xarray': '2026.9.0', 'scipy': '1.18.1', 'numpy': '2.5.4'}
RUNTIME = 'xarray 2026.9.0 / SciPy 1.18.1 (engine scipy) / NumPy 2.5.4'
NAME = {'type': 'string', 'minLength': 1, 'maxLength': 40, 'required': True}
UNIT = {'type': 'string', 'minLength': 1, 'maxLength': 32, 'required': True}
NUMBER = {'type': 'number', 'minimum': -1e100, 'maximum': 1e100, 'required': True}
RANGE = {'type': 'object', 'properties': {'minimum': NUMBER, 'maximum': NUMBER}}
DIMENSION = {'type': 'object', 'properties': {'name': NAME, 'unit': UNIT, 'range': RANGE}}
VARIABLE = {'type': 'object', 'required': True, 'properties': {'name': NAME, 'unit': UNIT}}
MISSING = {'type': 'object', 'required': True, 'properties': {
    'value': NUMBER, 'policy': {'type': 'enum', 'values': list(oracle.POLICIES), 'required': True},
    'minimumValid': {'type': 'integer', 'minimum': 1, 'maximum': 262144}}}
OPTIONS = {
    'source': {'type': 'string', 'minLength': 1, 'maxLength': 4096, 'required': True},
    'variable': VARIABLE,
    'coordinates': {'type': 'array', 'items': DIMENSION, 'minItems': 2, 'maxItems': 4, 'required': True},
    'retain': NAME,
    'missing': MISSING,
}
DECLARATIONS = {OPERATION: {
    'native': 'xarray.open_dataset(engine="scipy"), Dataset/DataArray.sel(slice), DataArray.where, DataArray.mean(dim, skipna), '
              'Dataset.to_netcdf(format="NETCDF3_CLASSIC")',
    'kinds': ['file', 'table', 'text'], 'inputs': {}, 'options': {k: {'value': v} for k, v in OPTIONS.items()}}}
IDENTIFIER = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,39}')
UNIT_TEXT = re.compile(r'[A-Za-z0-9][A-Za-z0-9 ._()+/*^\-]{0,31}')
RESERVED = {'validCount', 'missingCount'}
LOSSES = [
    'One local classic NetCDF CDF-1 file with fixed dimensions: no record dimension, NetCDF-4/HDF5, 64-bit offset, CDF-5, Zarr, '
    'compression, remote or Dask input.',
    'One double data variable plus its double coordinate variables, strictly increasing finite numeric coordinates with declared '
    'units; no calendars or epochs, geospatial or CF interpretation, packing, strings or categories.',
    'Attribute allowlist only: units, _FillValue and long_name on variables, title globally. Any other attribute, variable or '
    'dimension is refused, never dropped.',
    'Unweighted arithmetic mean of the cells inside inclusive coordinate ranges; not area, volume or time weighted; no '
    'alignment, merge or interpolation; no measurement or sampling uncertainty.',
    'Native means are verified within the first-order bound (n + 1) * 2^-53 * mean(|x|) (second-order terms dropped; no floor, so '
    'when the bound rounds to zero, means must equal the nearest-rounded reference); ill-conditioned (cancelling) means are refused above 1e-9 relative.',
    'Exactly xarray 2026.9.0 with SciPy 1.18.1 and NumPy 2.5.4 is the qualified native runtime; other builds are refused.']
NATIVE_CODES = {'XR_UNSUPPORTED_RUNTIME', 'XR_SOURCE_CHANGED', 'XR_RESOURCE_LIMIT', 'XR_DIMENSION_ORDER', 'XR_UNITS_MISMATCH',
                'XR_TYPE_UNSUPPORTED', 'XR_MISSING_VALUES', 'XR_INSUFFICIENT_VALID', 'XR_NONFINITE_VALUE'}
THREADS = {'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1', 'NUMEXPR_NUM_THREADS': '1',
           'LANG': 'C.UTF-8', 'HDF5_USE_FILE_LOCKING': 'FALSE'}
STAGES = ('compute', 'readback')
WORKER_NAMES = ('adaptor.py', 'oracle.py', 'cdf.py', 'native_worker.py')
PUBLICATIONS = (('profile.nc', 'file'), ('profile.csv', 'table'), ('xarray-summary.json', 'text'))


def located(code, message, location, recovery=None, **observed):
    oracle.raise_fault(code, message, location, recovery, **observed)


def plan(document):
    keys(document, ('version', 'operation', *OPTIONS), '$')
    if document.get('version') != VERSION:
        fail('UNSUPPORTED_VERSION', 'select ' + VERSION, '$.version')
    if document.get('operation') != OPERATION:
        fail('UNKNOWN_FILTER', 'select ' + OPERATION, '$.operation')
    p = validate_arguments(OPTIONS, {k: v for k, v in document.items() if k in OPTIONS}, location='$')
    source = Path(p['source'])
    if '\x00' in p['source'] or not source.is_absolute() or source.suffix.lower() != '.nc':
        fail('XR_INVALID_SOURCE', 'select an absolute local regular classic NetCDF .nc file', '$.source')
    name = p['variable']['name']
    if not IDENTIFIER.fullmatch(name) or name in RESERVED:
        located('XR_INVALID_CONTRACT', 'the variable name is an identifier (letter then letters, digits or _) other than '
                'validCount or missingCount', '$.variable.name')
    if not UNIT_TEXT.fullmatch(p['variable']['unit']):
        located('XR_INVALID_CONTRACT', 'units are plain text of at most 32 characters', '$.variable.unit')
    seen = set()
    for i, d in enumerate(p['coordinates']):
        at = '$.coordinates[%d]' % i
        if not IDENTIFIER.fullmatch(d['name']) or d['name'] in seen or d['name'] in RESERVED or d['name'] == name:
            located('XR_INVALID_CONTRACT', 'dimension names are distinct identifiers, not the variable name, validCount or '
                    'missingCount', at + '.name')
        if not UNIT_TEXT.fullmatch(d['unit']):
            located('XR_INVALID_CONTRACT', 'units are plain text of at most 32 characters', at + '.unit')
        seen.add(d['name'])
        rng = d.get('range')
        if rng is not None:
            if set(rng) != {'minimum', 'maximum'} or rng['minimum'] > rng['maximum']:
                located('XR_INVALID_CONTRACT', 'a range states both bounds with minimum <= maximum (inclusive)', at + '.range',
                        'omit range to use the whole axis')
    if p['retain'] not in seen:
        located('XR_INVALID_CONTRACT', 'retain names one declared dimension', '$.retain')
    m = p['missing']
    if set(m) - {'value', 'policy', 'minimumValid'} or 'value' not in m or 'policy' not in m:
        located('XR_INVALID_CONTRACT', 'missing needs value and policy', '$.missing')
    if 'minimumValid' in m and m['policy'] != 'skip':
        located('XR_INVALID_CONTRACT', 'minimumValid is only used with the skip policy', '$.missing.minimumValid',
                'remove it or select skip')
    m.setdefault('minimumValid', 1)
    return {'version': 'schemaxis.xarray.plan/1', 'operation': OPERATION, **p,
            'publications': [n for n, _ in PUBLICATIONS], 'limits': oracle.LIMITS, 'runtime': RUNTIME, 'losses': LOSSES}


def native_config(p, source_sha):
    return {'coordinates': p['coordinates'], 'variable': p['variable'], 'retain': p['retain'], 'missing': p['missing'],
            'sourceSha256': source_sha,
            'outputAttributes': {'schemaxis_source_sha256': source_sha,
                                 'schemaxis_selection_sha256': oracle.canonical(oracle.selection_record(p)),
                                 'schemaxis_reduction': oracle.reduction_text(p)}}


def publications(p):
    return list(PUBLICATIONS)


def schema():
    from schemaxis.schema import DRAFT, argument_schema, object_schema
    return {'$schema': DRAFT, **object_schema({'version': {'const': VERSION}, 'operation': {'const': OPERATION},
        **{k: argument_schema(v) for k, v in OPTIONS.items()}},
        ['version', 'operation', *[k for k, v in OPTIONS.items() if v.get('required')]])}


def query(document):
    plan(document)
    return [OPERATION], {}


def resources(document, execution, identity):
    if execution.get('threads', 1) != 1:
        fail('INVALID_EXECUTION', 'xarray reduction uses one serial native thread', identity)
    return {'threads': 1}


def bounded(path, code='VERIFICATION_FAILED', limit=32 * 1024 * 1024):
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise ValueError('not a bounded regular file')
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError('byte budget exceeded')
        return data
    except (OSError, ValueError) as error:
        fail(code, 'select an intact bounded regular file: ' + str(error), str(path))


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key ' + key)
        result[key] = value
    return result


def strict(data):
    return json.loads(data, object_pairs_hook=unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON ' + value)))


def read(directory, name):
    return strict(bounded(Path(directory) / name))


def digest(directory, name):
    return hashlib.sha256(bounded(Path(directory) / name)).hexdigest()


def load_cube(p, data):
    """Complete host validation of the source bytes: decode, bind to the declaration, reduce exactly."""
    try:
        parsed = cdf.parse(data)
    except cdf.CdfError as error:
        oracle.cdf_fault(error)
    cube = oracle.bind(p, parsed)
    cube['sourceSha256'] = hashlib.sha256(data).hexdigest()
    return cube, oracle.reduce_profile(p, cube)


def reusableInputs(document):
    p = plan(document)
    return {p['source']: hashlib.sha256(bounded(p['source'], 'XR_INVALID_SOURCE', oracle.LIMITS['maxBytes'])).hexdigest()}


def retainedInputs(directory, document):
    """Original source path and digest, authenticated by the retained capture; never rereads the original."""
    directory = Path(directory).absolute()
    try:
        p = plan(document)
        if read(directory, 'authored.json') != json.loads(json.dumps(document)) or read(directory, 'plan.json') != json.loads(json.dumps(p)):
            fail('VERIFICATION_FAILED', 'retained input provenance belongs to a different document')
        data = bounded(directory / 'source.nc', limit=oracle.LIMITS['maxBytes'])
        sha = hashlib.sha256(data).hexdigest()
        if read(directory, 'capture.json') != {'source': p['source'], 'bytes': len(data), 'sha256': sha}:
            fail('VERIFICATION_FAILED', 'retained capture identity differs')
        if read(directory, 'compute-inputs.json').get('source.nc') != sha:
            fail('VERIFICATION_FAILED', 'native compute consumed different source bytes', 'compute')
        if read(directory, 'xarray-summary.json')['source']['sha256'] != sha:
            fail('VERIFICATION_FAILED', 'summary is bound to different source bytes')
        return {p['source']: sha}
    except SchemaxisError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError, UnicodeError, RecursionError) as error:
        fail('VERIFICATION_FAILED', 'invalid retained input provenance: ' + str(error))


def worker_source():
    return Path(__file__).with_name('native_worker.py').read_text()


def implementation():
    return {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in WORKER_NAMES}


def evidence_names():
    return ({'authored.json', 'plan.json', 'source.nc', 'capture.json', 'native-worker.py', 'native-config.json',
             'implementation.json', 'compute-inputs.json', 'readback-inputs.json', 'readback.json', 'native-result.json'}
            | {stage + suffix for stage in STAGES for suffix in ('.stdout', '.stderr', '-submission.json')})


def command(executable, stage):
    return [str(executable), '-I', '-B', 'native-worker.py', stage]


def artifacts(directory, p):
    return [{'file': str(directory / name), 'kind': kind, 'sha256': digest(directory, name)} for name, kind in publications(p)]


def portable_artifacts(recorded, directory, p):
    expected = artifacts(directory, p)
    if not isinstance(recorded, list) or len(recorded) != len(expected):
        return False
    files = [item.get('file') if isinstance(item, dict) else None for item in recorded]
    if not all(isinstance(f, str) and Path(f).is_absolute() for f in files) or len({str(Path(f).parent) for f in files}) != 1:
        return False
    return all(item == {**want, 'file': str(Path(f).parent / Path(want['file']).name)} for item, want, f in zip(recorded, expected, files))


def native_refusal(directory, stage, error):
    path = directory / (stage + '-fault.json')
    if not path.is_file():
        raise error
    try:
        fault = read(directory, stage + '-fault.json')
        code, message, location = fault['code'], fault['message'], fault['location']
        if code not in NATIVE_CODES or not all(isinstance(x, str) for x in (message, location)):
            raise ValueError('unknown native refusal')
    except (KeyError, ValueError, TypeError) as invalid:
        fail('VERIFICATION_FAILED', 'native refusal record is malformed: ' + str(invalid), stage)
    if code != 'XR_UNSUPPORTED_RUNTIME':
        fail('VERIFICATION_FAILED', 'native refused input that the independent host reader and contract accepted', location, nativeCode=code)
    located(code, message, location, 'configure an isolated Python with exactly xarray 2026.9.0, SciPy 1.18.1 and NumPy 2.5.4',
            **fault.get('details', {}))


def runtime_summary(directory):
    runtime = read(directory, 'native-result.json').get('runtime', {})
    return {k: runtime.get(k) for k in ('xarray', 'scipy', 'numpy', 'python', 'loaders')}


def build_summary(directory, p, data, cube, points):
    nc, csv_bytes = bounded(directory / 'profile.nc'), bounded(directory / 'profile.csv')
    verified = oracle.verify_profile(p, cube, points, nc, csv_bytes)
    return oracle.summary(p, cube, points, verified, nc, csv_bytes, data, runtime_summary(directory))


def run(document, directory, *, executable=None, timeout=120):
    p = plan(document)
    executable = executable or os.environ.get('SCHEMAXIS_XARRAY')
    if not executable or not Path(executable).is_absolute() or not os.access(executable, os.X_OK):
        fail('INTERPRETER_NOT_FOUND', 'configure an absolute isolated Python containing xarray 2026.9.0, SciPy 1.18.1 and NumPy 2.5.4')
    if os.name != 'posix':
        fail('UNSUPPORTED_PLATFORM', 'qualified xarray process resource caps require POSIX')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        fail('INVALID_ARGUMENT', 'timeout must be finite in (0,3600]')
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink():
        fail('OUTPUT_EXISTS', 'select a fresh output directory', str(directory))
    directory.mkdir(parents=True)
    deadline = time.monotonic() + timeout
    atomic_json(directory / 'authored.json', document)
    atomic_json(directory / 'plan.json', p)
    atomic_json(directory / 'result.json', {'status': 'incomplete', 'verified': False})
    try:
        data = bounded(p['source'], 'XR_INVALID_SOURCE', oracle.LIMITS['maxBytes'])
        cube, points = load_cube(p, data)          # complete independent host validation before launch
        sha = hashlib.sha256(data).hexdigest()
        (directory / 'source.nc').write_bytes(data)
        atomic_json(directory / 'capture.json', {'source': p['source'], 'bytes': len(data), 'sha256': sha})
        (directory / 'native-worker.py').write_text(worker_source())
        atomic_json(directory / 'native-config.json', native_config(p, sha))
        atomic_json(directory / 'implementation.json', implementation())
        for stage in STAGES:
            try:
                execute(command(executable, stage), directory, stage, deadline - time.monotonic(), THREADS)
            except SchemaxisError as error:
                if error.fault.code != 'RUNNER_FAILED':
                    raise
                if stage == 'compute':
                    native_refusal(directory, stage, error)
                reason = read(directory, 'readback.json').get('reason', 'published values differ') if (directory / 'readback.json').is_file() else str(error)
                fail('VERIFICATION_FAILED', 'native readback rejected the publication: ' + str(reason), stage)
        if time.monotonic() >= deadline:
            fail('RUNNER_TIMED_OUT', 'xarray reduction exhausted its total deadline')
        atomic_json(directory / 'xarray-summary.json', build_summary(directory, p, data, cube, points))
        atomic_json(directory / 'verification.json', {'artifacts': artifacts(directory, p),
            'evidence': {name: digest(directory, name) for name in sorted(evidence_names())},
            'executable': str(executable), 'runtime': RUNTIME})
        result = verify(directory, require_result=False)
        if cancellation_requested():
            fail('RUNNER_CANCELLED', 'xarray reduction cancelled')
        if time.monotonic() >= deadline:
            fail('RUNNER_TIMED_OUT', 'xarray reduction exhausted its total deadline')
        result['status'] = 'succeeded'
        atomic_json(directory / 'result.json', result)
        return result
    except Exception as error:
        if not isinstance(error, SchemaxisError):
            try:
                fail('NATIVE_EXECUTION_FAILED', str(error))
            except SchemaxisError as wrapped:
                error = wrapped
        atomic_json(directory / 'result.json', {'status': 'failed', 'verified': False, 'fault': error.fault.to_dict()})
        raise error


def verify(directory, require_result=True):
    directory = Path(directory).absolute()
    try:
        p = plan(read(directory, 'authored.json'))
        if read(directory, 'plan.json') != json.loads(json.dumps(p)):
            fail('VERIFICATION_FAILED', 'effective plan differs')
        if read(directory, 'implementation.json') != implementation():
            fail('VERIFICATION_FAILED', 'xarray adaptor implementation changed; rerun to verify with current code')
        result = read(directory, 'result.json') if require_result else None
        if result is not None and (result.get('status') != 'succeeded' or result.get('verified') is not True):
            fail('INCOMPLETE_EXECUTION', 'xarray reduction did not complete')
        data = bounded(directory / 'source.nc', limit=oracle.LIMITS['maxBytes'])
        sha = hashlib.sha256(data).hexdigest()
        if read(directory, 'capture.json') != {'source': p['source'], 'bytes': len(data), 'sha256': sha}:
            fail('VERIFICATION_FAILED', 'captured source identity differs')
        receipt = read(directory, 'verification.json')
        executable = receipt.get('executable')
        if not isinstance(executable, str) or not Path(executable).is_absolute() or receipt.get('runtime') != RUNTIME:
            fail('VERIFICATION_FAILED', 'native runtime identity differs')
        config = native_config(p, sha)
        if bounded(directory / 'native-worker.py').decode() != worker_source() or read(directory, 'native-config.json') != json.loads(json.dumps(config)):
            fail('VERIFICATION_FAILED', 'trusted worker or native configuration differs')
        for stage in STAGES:
            submission = read(directory, stage + '-submission.json')
            if submission.get('nativeCommand') != command(executable, stage) \
                    or type(submission.get('exitCode')) is not int or submission['exitCode'] != 0:
                fail('VERIFICATION_FAILED', 'native command or completion differs', stage)
        base = {name: digest(directory, name) for name in ('source.nc', 'native-config.json', 'native-worker.py')}
        if read(directory, 'compute-inputs.json') != base:
            fail('VERIFICATION_FAILED', 'native compute consumed different input bytes', 'compute')
        wanted = {**base, **{name: digest(directory, name) for name in ('native-result.json', 'profile.nc', 'profile.csv')}}
        if read(directory, 'readback-inputs.json') != wanted:
            fail('VERIFICATION_FAILED', 'native readback consumed different publication bytes', 'readback')
        readback = read(directory, 'readback.json')
        native = read(directory, 'native-result.json')
        for record in (readback.get('runtime', {}), native.get('runtime', {})):
            if any(record.get(k) != v for k, v in REQUIRED.items()):
                fail('VERIFICATION_FAILED', 'native runtime observation differs from ' + RUNTIME)
        if readback.get('ok') is not True or native.get('engine') != 'scipy' or native.get('source') != sha:
            fail('VERIFICATION_FAILED', 'native readback did not confirm the publication', 'readback')
        cube, points = load_cube(p, data)
        expected = build_summary(directory, p, data, cube, points)
        if read(directory, 'xarray-summary.json') != json.loads(json.dumps(expected)):
            fail('VERIFICATION_FAILED', 'summary differs from independent recomputation (stale, foreign or altered)')
        if not portable_artifacts(receipt.get('artifacts'), directory, p):
            fail('VERIFICATION_FAILED', 'publication membership or digests differ')
        if set(receipt.get('evidence', {})) != evidence_names():
            fail('VERIFICATION_FAILED', 'evidence membership differs')
        for name in evidence_names():
            if receipt['evidence'][name] != digest(directory, name):
                fail('VERIFICATION_FAILED', 'retained evidence differs', name)
        return {'verified': True, 'artifacts': len(receipt['artifacts']), 'runtime': RUNTIME,
                'points': expected['profile']['points'], 'validCells': expected['totals']['validCells'],
                'missingCells': expected['totals']['missingCells']}
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeError, OverflowError, RecursionError,
            ArithmeticError, StopIteration) as error:
        fail('VERIFICATION_FAILED', 'invalid retained xarray evidence: ' + str(error))


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
