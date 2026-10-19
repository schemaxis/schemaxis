"""Verified geodesic route chainage: isolated pyproj execution with an independent host verifier."""
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import time

from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import cancellation_requested, remaining_timeout
from schemaxis.errors import fail
from schemaxis.native_command import execute
from . import contract, verifier
from .contract import GAP, OPERATION, OPTIONS, RUNTIME, VERSION, located

DECLARATIONS = {OPERATION: {
    'native': "pyproj.Geod(ellps='WGS84').inv per leg (and requested endpoint gap); Geod.fwd per fixed station",
    'kinds': ['table', 'geospatialVector', 'text'], 'inputs': {},
    'options': {k: {'value': v} for k, v in OPTIONS.items()}}}
STAGES = ('compute', 'readback')
NATIVE_PUBLICATIONS = contract.PUBLICATIONS
PUBLICATIONS = [('stations.csv', 'table'), ('legs.csv', 'table'), ('stations.geojson', 'geospatialVector'),
                ('route.geojson', 'geospatialVector'), ('route-summary.json', 'text'), ('route-verification.json', 'text')]
IMPLEMENTATION = ('adaptor.py', 'contract.py', 'geodesy.py', 'verifier.py', 'native_worker.py')
OBSERVED = {'pyproj': '3.8.0', 'proj': '9.9.0', 'python': '3.12.15', 'a': 6378137.0, 'f': 1 / 298.257223563, 'network': False}
HOME = '.native-home'
THREADS = {'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1', 'LANG': 'C.UTF-8'}
DOMAIN_REFUSALS = {'ROUTE_LEG_TOO_LONG', 'ROUTE_LEG_TOO_SHORT', 'ROUTE_LATITUDE_EXCURSION', 'ROUTE_TOTAL_TOO_LONG',
                   'ROUTE_ROW_LIMIT', 'ENDPOINT_GAP_OUTSIDE_DOMAIN'}
OUTCOME_CODES = {'requirementsUnmet': 'ROUTE_REQUIREMENT_NOT_MET', 'requirementsIndeterminate': 'ROUTE_REQUIREMENT_INDETERMINATE'}
SOURCE_LIMIT = 16 * 1024 * 1024


def plan(document):
    p = contract.validate(document)
    return {'version': 'schemaxis.pyproj.plan/1', 'operation': OPERATION, **p,
            'limits': dict(contract.LIMITS), 'runtime': RUNTIME, 'publications': [name for name, _ in PUBLICATIONS],
            'numericalModel': contract.NUMERICAL_MODEL, 'losses': contract.LOSSES}


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
        fail('INVALID_EXECUTION', 'route chainage uses one serial native process', identity)
    return {'threads': 1}


def bounded(path, code='VERIFICATION_FAILED', limit=SOURCE_LIMIT):
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


def strict(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key ' + key)
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique, parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON ' + value)))


def read(directory, name):
    return strict(bounded(Path(directory) / name))


def digest(directory, name):
    return hashlib.sha256(bounded(Path(directory) / name)).hexdigest()


def canonical_digest(value):
    return hashlib.sha256(contract.canonical(value).encode()).hexdigest()


def reusableInputs(document):
    """Current source bytes participate in reuse identity; same-path edits or removal invalidate."""
    p = plan(document)
    return {p['source']: hashlib.sha256(bounded(p['source'], 'INVALID_ROUTE_SOURCE')).hexdigest()}


def retainedInputs(directory, document):
    """Original-path/digest provenance authenticated by the retained capture (never rereads originals).

    Called by the framework after successful native verification. The capture is rechecked against
    the effective document, the retained bytes and the host verification binding before it is
    returned; any inconsistency is a fault, not an empty map.
    """
    directory = Path(directory).absolute()
    try:
        p = plan(document)
        if read(directory, 'authored.json') != document:
            fail('VERIFICATION_FAILED', 'retained input provenance belongs to a different document')
        data = bounded(directory / 'source.csv')
        sha = hashlib.sha256(data).hexdigest()
        if read(directory, 'capture.json') != {'source': p['source'], 'bytes': len(data), 'sha256': sha}:
            fail('VERIFICATION_FAILED', 'retained capture identity differs')
        if read(directory, 'route-verification.json')['bindings']['source'] != sha:
            fail('VERIFICATION_FAILED', 'host verification is bound to different source bytes')
        return {p['source']: sha}
    except SchemaxisError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        fail('VERIFICATION_FAILED', 'invalid retained input provenance: ' + str(error))


def worker_source():
    return Path(__file__).with_name('native_worker.py').read_text()


def implementation():
    return {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in IMPLEMENTATION}


def evidence_names():
    return ({'authored.json', 'plan.json', 'source.csv', 'capture.json', 'native-worker.py', 'native-config.json',
             'implementation.json', 'compute-inputs.json', 'readback-inputs.json', 'native-result.json', 'readback.json'}
            | {stage + suffix for stage in STAGES for suffix in ('.stdout', '.stderr', '-submission.json')})


def command(executable, stage):
    # Run-relative trusted worker under the run working directory: the exact command survives export.
    return [str(executable), '-I', '-B', 'native-worker.py', stage]


def environment(directory):
    home = str(Path(directory) / HOME)
    return {**THREADS, 'PROJ_NETWORK': 'OFF', 'HOME': home, 'XDG_DATA_HOME': home + '/data', 'XDG_CACHE_HOME': home + '/cache',
            'XDG_CONFIG_HOME': home + '/config', 'PROJ_USER_WRITABLE_DIRECTORY': home + '/proj'}


def artifacts(directory):
    return [{'file': str(Path(directory) / name), 'kind': kind, 'sha256': digest(directory, name)} for name, kind in PUBLICATIONS]


def portable_artifacts(recorded, directory):
    """Same order, names, kinds and current digests; the recorded run location may differ after export."""
    expected = artifacts(directory)
    if not isinstance(recorded, list) or len(recorded) != len(expected):
        return False
    files = [item.get('file') if isinstance(item, dict) else None for item in recorded]
    if not all(isinstance(f, str) and Path(f).is_absolute() for f in files) or len({str(Path(f).parent) for f in files}) != 1:
        return False
    return all(item == {**want, 'file': str(Path(f).parent / Path(want['file']).name)} for item, want, f in zip(recorded, expected, files))


def checkpointer(deadline=None):
    """Cancellation and the whole-run deadline also bound host verification (no per-stage reset)."""
    def check():
        remaining_timeout(3600)
        if cancellation_requested():
            fail('RUNNER_CANCELLED', 'route chainage cancelled')
        if deadline is not None and time.monotonic() >= deadline:
            fail('RUNNER_TIMED_OUT', 'route chainage exhausted its total deadline, including host verification')
    return check


def captured(p, data):
    points, names = contract.parse_waypoints(data)
    return points, names, contract.native_config(p, points, names)


def route_points(config):
    points = [list(x) for x in config['waypoints']]
    names = list(config['names'])
    if config['closed']:
        points.append(points[0])
        names.append(names[0])
    return points, names


def native_result(directory):
    """Strict shape of the native compute record; runtime identity must be exact."""
    record = read(directory, 'native-result.json')
    runtime = record.get('runtime') if isinstance(record, dict) else None
    result = record.get('result') if isinstance(record, dict) else None
    if set(record) != {'runtime', 'result'} or not isinstance(runtime, dict) or not isinstance(result, dict):
        fail('VERIFICATION_FAILED', 'native compute record is malformed', 'native-result.json')
    if {k: runtime.get(k) for k in OBSERVED} != OBSERVED or set(runtime) != set(OBSERVED) | {'pid'} or type(runtime['pid']) is not int:
        fail('VERIFICATION_FAILED', 'native runtime observation differs from ' + RUNTIME + ' with network disabled', 'native-result.json')
    if set(result) != {'legs', 'rows', 'names', 'total', 'gap', 'deflection', 'closed', 'spacing'}:
        fail('VERIFICATION_FAILED', 'native compute result fields differ', 'native-result.json')
    deflection = result['deflection']
    if not isinstance(deflection, dict) or any(type(v) is not float or not math.isfinite(v) for v in deflection.values()):
        fail('VERIFICATION_FAILED', 'native deflections must be finite numbers', 'native-result.json')
    return runtime, result


def readback_record(directory, rows, legs):
    """Native readback is self-consistency only; its record is validated strictly and never trusted further."""
    record = read(directory, 'readback.json')
    expected = {'runtime', 'rows', 'legs', 'publicationsExact', 'consecutiveInverseWorstRatio', 'scope'}
    ratio = record.get('consecutiveInverseWorstRatio') if isinstance(record, dict) else None
    if (not isinstance(record, dict) or set(record) != expected or record['publicationsExact'] is not True
            or type(record['rows']) is not int or record['rows'] != rows or type(record['legs']) is not int or record['legs'] != legs
            or type(ratio) is not float or not 0 <= ratio <= 1 or record['scope'] != 'native self-consistency only'
            or not isinstance(record['runtime'], dict) or {k: record['runtime'].get(k) for k in OBSERVED} != OBSERVED):
        fail('VERIFICATION_FAILED', 'native readback record is malformed or not exact', 'readback.json')


def host_record(directory, p, data, checkpoint):
    """Independent host summary and verification record: the sole final decision, fully recomputable."""
    directory = Path(directory)
    points, names, config = captured(p, data)
    if read(directory, 'native-config.json') != json.loads(json.dumps(config)):
        fail('VERIFICATION_FAILED', 'native configuration differs from the captured route')
    route, route_names = route_points(config)
    runtime, result = native_result(directory)
    stations = contract.parse_table(bounded(directory / 'stations.csv'), contract.STATION_COLUMNS, 'stations.csv')
    legs = contract.parse_table(bounded(directory / 'legs.csv'), contract.LEG_COLUMNS, 'legs.csv')
    geo = {name: read(directory, name) for name in ('stations.geojson', 'route.geojson')}
    readback_record(directory, len(stations), len(legs))
    verifier.structural(stations, legs, geo, p, route, route_names)
    evidence = verifier.independent(stations, legs, p, route, checkpoint)
    decision = verifier.decide(p, stations, legs, result['gap'], evidence)
    submission = read(directory, 'compute-submission.json')
    sha = hashlib.sha256(data).hexdigest()
    summary = {'version': 'schemaxis.pyproj.summary/1', 'operation': OPERATION,
               'ellipsoid': {'name': 'WGS84', 'a_m': 6378137.0, 'inverseFlattening': 298.257223563},
               'coordinateOrder': 'lonLat', 'coordinateInterpretation': 'captured decimal text retained; arithmetic on its correctly rounded binary64 values',
               'units': {'distance': 'm', 'angle': 'deg', 'azimuth': 'clockwise from geodetic north in [0, 360)', 'deflection': 'positive clockwise (right turn)'},
               'waypoints': len(config['waypoints']), 'closed': p['closed'], 'legs': len(legs), 'rows': len(stations),
               'fixedStations': sum(s['kind'] in (1, 3) for s in stations), 'spacing_m': p['spacing_m'], **decision,
               'deflection_deg': result['deflection'], 'numericalModel': contract.NUMERICAL_MODEL,
               'consumers': {'scope': 'host contracts only; no native consumer was run by this route',
                             'calcStationsTable': True, 'calcLegsTable': len(legs) >= 2,
                             'gnuplotChainageProfiles': 2 <= len(stations) <= 2048, 'gnuplotMap': False, 'qgisVector': len(stations) <= 10000},
               'sourceSha256': sha, 'losses': contract.LOSSES}
    bindings = {'source': sha, 'parsedDigest': canonical_digest({'waypoints': points, 'names': names}),
                'plan': canonical_digest(p), 'nativeConfig': canonical_digest(config),
                'native': {name: digest(directory, name) for name in (*NATIVE_PUBLICATIONS, 'native-result.json', 'readback.json')},
                'runtime': {'identity': RUNTIME, 'observed': {k: runtime[k] for k in OBSERVED},
                            # SHA-256 of the UTF-8 interpreter path string, not of executable bytes.
                            'executablePathDigest': hashlib.sha256(submission['nativeCommand'][0].encode()).hexdigest()},
                'implementation': implementation(), 'summary': canonical_digest(summary)}
    record = {'version': 'schemaxis.pyproj.verification/1', 'bindings': bindings, 'oracle': evidence,
              'decision': {k: decision[k] for k in ('requirements', 'overall', 'outcome')},
              'scope': 'Independent standard-library evaluation of the same ellipsoidal theory with executable adequacy checks; '
                       'numerical agreement only; qualified on the producing host and libm.'}
    return summary, record


def native_refusal(directory, stage, error, p, config):
    """Map a structured worker refusal; a domain refusal must be reproduced by the independent oracle."""
    path = Path(directory) / (stage + '-fault.json')
    if not path.is_file():
        observed = error.fault.observed if isinstance(error.fault.observed, dict) else {}
        fail('NATIVE_EXECUTION_FAILED', 'native worker failed without a structured refusal; see ' + stage + '.stderr', stage,
             exitCode=observed.get('exitCode'))
    try:
        fault = read(directory, stage + '-fault.json')
        code, message, location = fault['code'], fault['message'], fault['location']
        if not all(isinstance(x, str) for x in (code, message, location)):
            raise ValueError('fault fields must be text')
    except (KeyError, ValueError, TypeError) as invalid:
        fail('VERIFICATION_FAILED', 'native refusal record is malformed: ' + str(invalid), stage)
    if stage == 'readback':
        fail('VERIFICATION_FAILED', 'native readback self-consistency failed: ' + message, location, nativeCode=code)
    if code in DOMAIN_REFUSALS:
        route, _ = route_points(config)
        verifier.confirm_refusal(code, location, p, route)
        located(code, message, location)
    if code == 'UNSUPPORTED_GEOD_RUNTIME':
        located(code, message, location, 'configure an isolated Python with exactly pyproj 3.8.0 and PROJ 9.9.0; network must stay disabled')
    fail('NATIVE_EXECUTION_FAILED', 'native worker failed: ' + message, location, nativeCode=code)


def run(document, directory, *, executable=None, timeout=120):
    p = plan(document)
    executable = executable or os.environ.get('SCHEMAXIS_PYPROJ')
    if not executable or not Path(executable).is_absolute() or not os.access(executable, os.X_OK):
        fail('INTERPRETER_NOT_FOUND', 'configure an absolute isolated Python containing pyproj 3.8.0 with PROJ 9.9.0 (--pyproj)')
    if os.name != 'posix':
        fail('UNSUPPORTED_PLATFORM', 'qualified pyproj process resource caps require POSIX')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        fail('INVALID_ARGUMENT', 'timeout must be finite in (0, 3600]')
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink():
        fail('OUTPUT_EXISTS', 'select a fresh output directory', str(directory))
    directory.mkdir(parents=True)
    deadline = time.monotonic() + timeout
    checkpoint = checkpointer(deadline)
    atomic_json(directory / 'authored.json', document)
    atomic_json(directory / 'plan.json', p)
    atomic_json(directory / 'result.json', {'status': 'incomplete', 'verified': False})
    try:
        data = bounded(p['source'], 'INVALID_ROUTE_SOURCE')
        _points, _names, config = captured(p, data)     # every conclusive host refusal before launch
        (directory / 'source.csv').write_bytes(data)
        atomic_json(directory / 'capture.json', {'source': p['source'], 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        (directory / 'native-worker.py').write_text(worker_source())
        atomic_json(directory / 'native-config.json', config)
        atomic_json(directory / 'implementation.json', implementation())
        (directory / HOME).mkdir()
        for stage in STAGES:
            checkpoint()
            budget = min(deadline - time.monotonic(), remaining_timeout(timeout))
            try:
                execute(command(executable, stage), directory, stage, budget, environment(directory))
            except SchemaxisError as error:
                if error.fault.code != 'RUNNER_FAILED':
                    raise
                native_refusal(directory, stage, error, p, config)
        checkpoint()
        summary, record = host_record(directory, p, data, checkpoint)
        atomic_json(directory / 'route-summary.json', summary)
        atomic_json(directory / 'route-verification.json', record)
        atomic_json(directory / 'verification.json', {'artifacts': artifacts(directory),
            'evidence': {name: digest(directory, name) for name in sorted(evidence_names())},
            'executable': str(executable), 'runtime': RUNTIME})
        result = _verify(directory, False, checkpoint)
        checkpoint()                                     # nothing is published as succeeded after expiry
        result['status'] = 'succeeded'
        atomic_json(directory / 'result.json', result)
        return result
    except Exception as error:
        if not isinstance(error, SchemaxisError):
            try:
                fail('VERIFICATION_FAILED', 'unexpected ' + type(error).__name__ + ': ' + str(error))
            except SchemaxisError as wrapped:
                error = wrapped
        atomic_json(directory / 'result.json', {'status': 'failed', 'verified': False, 'fault': error.fault.to_dict()})
        raise error


def outcome_fault(summary):
    """A verified publication whose requirements are unmet or indeterminate is not an accepted deliverable."""
    outcome = summary['outcome']
    if outcome == 'accepted':
        return
    wanted = 'unmet' if outcome == 'requirementsUnmet' else 'indeterminate'
    key = next(k for k, v in summary['requirements'].items() if v['state'] == wanted)
    states = {k: v['state'] for k, v in summary['requirements'].items()}
    if outcome == 'requirementsUnmet':
        located(OUTCOME_CODES[outcome], 'the verified route does not meet a declared requirement', '$.requirements.' + key,
                'inspect route-summary.json; the evidence is retained but is not an accepted deliverable', states=states)
    located(OUTCOME_CODES[outcome], 'a declared requirement lies within the numerical band of its bound', '$.requirements.' + key,
            'inspect route-summary.json; only move the bound beyond value +/- numerical band if that is defensible', states=states)


def verify(directory, require_result=True):
    return _verify(directory, require_result, checkpointer())


def _verify(directory, require_result, checkpoint):
    directory = Path(directory).absolute()
    try:
        p = plan(read(directory, 'authored.json'))
        if read(directory, 'plan.json') != json.loads(json.dumps(p)):
            fail('VERIFICATION_FAILED', 'effective plan differs')
        if read(directory, 'implementation.json') != implementation():
            fail('VERIFICATION_FAILED', 'pyproj adaptor implementation changed; rerun to verify with current code')
        saved = read(directory, 'result.json') if require_result else None
        if saved is not None and (saved.get('status') != 'succeeded' or saved.get('verified') is not True):
            code = saved.get('fault', {}).get('code') if isinstance(saved.get('fault'), dict) else None
            if code not in OUTCOME_CODES.values():
                fail('INCOMPLETE_EXECUTION', 'route chainage did not complete')
        data = bounded(directory / 'source.csv', limit=contract.LIMITS['maxSourceBytes'])
        if read(directory, 'capture.json') != {'source': p['source'], 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}:
            fail('VERIFICATION_FAILED', 'captured source identity differs')
        receipt = read(directory, 'verification.json')
        executable = receipt.get('executable')
        if not isinstance(executable, str) or not Path(executable).is_absolute() or receipt.get('runtime') != RUNTIME:
            fail('VERIFICATION_FAILED', 'native runtime identity differs')
        if bounded(directory / 'native-worker.py').decode() != worker_source():
            fail('VERIFICATION_FAILED', 'trusted native worker differs')
        for stage in STAGES:
            submission = read(directory, stage + '-submission.json')
            if submission.get('nativeCommand') != command(executable, stage) \
                    or type(submission.get('exitCode')) is not int or submission['exitCode'] != 0:
                fail('VERIFICATION_FAILED', 'native command or completion differs', stage)
        base = {name: digest(directory, name) for name in ('native-config.json', 'native-worker.py')}
        if read(directory, 'compute-inputs.json') != base:
            fail('VERIFICATION_FAILED', 'native compute consumed different input bytes', 'compute')
        consumed = {**base, **{name: digest(directory, name) for name in ('native-result.json', *NATIVE_PUBLICATIONS)}}
        if read(directory, 'readback-inputs.json') != consumed:
            fail('VERIFICATION_FAILED', 'native readback consumed different publication bytes', 'readback')
        home = directory / HOME
        if home.is_symlink() or not home.is_dir() or any(home.rglob('*')):
            fail('VERIFICATION_FAILED', 'the private native home must remain an empty run-local directory', HOME)
        summary, record = host_record(directory, p, data, checkpoint)
        if read(directory, 'route-summary.json') != json.loads(json.dumps(summary)):
            fail('VERIFICATION_FAILED', 'route summary differs from recomputation (stale, foreign or altered)')
        if read(directory, 'route-verification.json') != json.loads(json.dumps(record)):
            fail('VERIFICATION_FAILED', 'host verification record differs from recomputation (stale, foreign or altered)')
        if not portable_artifacts(receipt.get('artifacts'), directory):
            fail('VERIFICATION_FAILED', 'publication membership or digests differ')
        if set(receipt.get('evidence', {})) != evidence_names():
            fail('VERIFICATION_FAILED', 'evidence membership differs')
        for name in evidence_names():
            if receipt['evidence'][name] != digest(directory, name):
                fail('VERIFICATION_FAILED', 'retained evidence differs', name)
        outcome_fault(summary)
        if saved is not None and saved.get('status') != 'succeeded':
            fail('INCOMPLETE_EXECUTION', 'route chainage did not complete')
        return {'verified': True, 'artifacts': len(PUBLICATIONS), 'runtime': RUNTIME, 'rows': summary['rows'],
                'totalLength_m': summary['totalLength_m'], 'requirements': summary['overall']}
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeError, RecursionError,
            ArithmeticError, StopIteration) as error:
        fail('VERIFICATION_FAILED', 'invalid retained route evidence: ' + type(error).__name__ + ': ' + str(error))


from schemaxis.adaptor_runtime import bind as _bind_runtime  # noqa: E402
_bind_runtime(globals())
