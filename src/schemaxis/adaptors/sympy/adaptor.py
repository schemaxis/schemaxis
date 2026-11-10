"""Exact real-root isolation of rational polynomials with isolated SymPy and an independent host verifier."""
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
from . import oracle

VERSION = 'schemaxis.sympy/1'
OPERATION = 'isolateRealRoots'
REQUIRED = '1.14.0'
RUNTIME = 'SymPy ' + REQUIRED
LITERAL = {'type': 'string', 'minLength': 1, 'maxLength': 82}
OPTIONS = {
    'coefficients': {'type': 'array', 'items': LITERAL, 'minItems': 2, 'maxItems': 13, 'required': True},
    'maximumIntervalWidth': {'type': 'string', 'minLength': 1, 'maxLength': 82, 'default': '1/1000'},
}
DECLARATIONS = {OPERATION: {
    'native': 'sympy.intervals([Poly(list of Rational, x, domain=QQ)], eps=Rational, strict=True)',
    'kinds': ['table', 'text'], 'inputs': {}, 'options': {k: {'value': v} for k, v in OPTIONS.items()}}}
PUBLICATIONS = [('real-roots.csv', 'table'), ('roots-summary.json', 'text'), ('roots-verification.json', 'text')]
NATIVE_PUBLICATIONS = ('real-roots.csv', 'roots-summary.json')
STAGES = ('compute', 'readback')
WORKER_NAMES = ('adaptor.py', 'oracle.py', 'native_worker.py')
ENVIRONMENT = {'LANG': 'C.UTF-8', 'SYMPY_USE_CACHE': 'no', 'PYTHONHASHSEED': '0', 'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1'}
NATIVE_CODES = {'SYMPY_UNSUPPORTED_RUNTIME', 'SYMPY_RUNTIME_UNAVAILABLE', 'SYMPY_NATIVE_RESULT_INVALID', 'SYMPY_RESOURCE_LIMIT', 'SYMPY_INVALID_CONTRACT'}
RUNTIME_RECOVERY = 'configure an absolute isolated Python (--sympy or SCHEMAXIS_SYMPY) that imports exactly SymPy ' + REQUIRED
REFUSAL_RECOVERY = {
    'SYMPY_UNSUPPORTED_RUNTIME': RUNTIME_RECOVERY,
    'SYMPY_RUNTIME_UNAVAILABLE': RUNTIME_RECOVERY + ' and mpmath; the configured interpreter could not import them',
    'SYMPY_NATIVE_RESULT_INVALID': 'the retained compute evidence is not an accepted result; rerun once and report the polynomial and '
                                   'SymPy release if it repeats',
}
LOSSES = [
    'Only literal exact rational coefficients are accepted; there is no expression parser, decimal, symbol, float or radical input.',
    'Real roots only, as closed rational isolating intervals with multiplicity; complex roots are counted, never located.',
    'Intervals are not decimal approximations: an exact point interval means the root is that rational number.',
    'The certificate proves isolation, completeness, width and multiplicity for the stated polynomial; it states nothing about '
    'the numerical conditioning of the source problem that produced the coefficients.',
    'Degree 1 to 12, coefficient numerators and denominators of at most 40 digits, width within [1e-30, 1].',
    'Exactly SymPy 1.14.0 is qualified; other releases are refused rather than assumed compatible.']


def located(code, message, location, recovery=None, **observed):
    oracle.raise_fault(code, message, location, recovery, **observed)


def parse(document):
    """Validated exact rational coefficients (descending powers) and width; plain data, no evaluation anywhere."""
    p = validate_arguments(OPTIONS, {k: v for k, v in document.items() if k in OPTIONS}, location='$')
    coefficients = [oracle.literal(c, f'$.coefficients[{i}]', 'SYMPY_INVALID_COEFFICIENT') for i, c in enumerate(p['coefficients'])]
    if coefficients[0] == 0:
        located('SYMPY_ZERO_LEADING_COEFFICIENT', 'the first coefficient is the highest power and must be nonzero',
                '$.coefficients[0]', 'drop leading zeros so that the list length is degree + 1, in descending powers')
    width = oracle.literal(p['maximumIntervalWidth'], '$.maximumIntervalWidth', 'SYMPY_INVALID_WIDTH')
    if not oracle.MIN_WIDTH <= width <= oracle.MAX_WIDTH:
        located('SYMPY_INVALID_WIDTH', 'maximumIntervalWidth must be within [1/10^30, 1]', '$.maximumIntervalWidth',
                'use an exact fraction such as 1/1000000', width=oracle.text(width))
    return coefficients, width


def plan(document):
    keys(document, ('version', 'operation', *OPTIONS), '$')
    if document.get('version') != VERSION:
        fail('UNSUPPORTED_VERSION', 'select ' + VERSION, '$.version')
    if document.get('operation') != OPERATION:
        fail('UNKNOWN_FILTER', 'select ' + OPERATION, '$.operation')
    coefficients, width = parse(document)
    return {'version': 'schemaxis.sympy.plan/1', 'operation': OPERATION, 'coefficients': [oracle.text(c) for c in coefficients],
            'coefficientOrder': 'descending powers: first entry multiplies x^degree', 'degree': len(coefficients) - 1,
            'maximumIntervalWidth': oracle.text(width), 'publications': [name for name, _ in PUBLICATIONS],
            'limits': dict(oracle.LIMITS), 'runtime': RUNTIME, 'losses': LOSSES}


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
        fail('INVALID_EXECUTION', 'root isolation uses one serial native process', identity)
    return {'threads': 1}


def reusableInputs(document):
    plan(document)
    return {}


def bounded(path, code='VERIFICATION_FAILED', limit=4 * 1024 * 1024):
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
    return json.loads(data, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON ' + value)))


def read(directory, name):
    return strict(bounded(Path(directory) / name))


def digest(directory, name):
    return hashlib.sha256(bounded(Path(directory) / name)).hexdigest()


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def retainedInputs(directory, document):
    """No external input files: the saved map is empty, and only after the retained evidence matches the document."""
    directory = Path(directory).absolute()
    try:
        p = plan(document)
        if read(directory, 'authored.json') != json.loads(json.dumps(document)) or read(directory, 'plan.json') != json.loads(json.dumps(p)):
            fail('VERIFICATION_FAILED', 'retained input provenance belongs to a different document')
        if read(directory, 'native-config.json') != native_config(p):
            fail('VERIFICATION_FAILED', 'native configuration belongs to a different document')
        return {}
    except SchemaxisError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError, UnicodeError, RecursionError) as error:
        fail('VERIFICATION_FAILED', 'invalid retained input provenance: ' + str(error))


def native_config(p):
    return {'coefficients': list(p['coefficients']), 'maximumIntervalWidth': p['maximumIntervalWidth']}


def worker_source():
    return Path(__file__).with_name('native_worker.py').read_text()


def implementation():
    return {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in WORKER_NAMES}


def evidence_names():
    return ({'authored.json', 'plan.json', 'native-worker.py', 'native-config.json', 'implementation.json', 'compute-inputs.json',
             'readback-inputs.json', 'readback.json'} | {stage + suffix for stage in STAGES for suffix in ('.stdout', '.stderr', '-submission.json')})


def command(executable, stage):
    # Run-relative worker under the run cwd, so the exact command survives a portable export.
    return [str(executable), '-I', '-B', 'native-worker.py', stage]


def artifacts(directory):
    return [{'file': str(directory / name), 'kind': kind, 'sha256': digest(directory, name)} for name, kind in PUBLICATIONS]


def portable_artifacts(recorded, directory):
    expected = artifacts(directory)
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
        details = fault.get('details', {})
        if code not in NATIVE_CODES or not all(isinstance(x, str) for x in (message, location)) or not isinstance(details, dict):
            raise ValueError('unknown native refusal')
    except (KeyError, ValueError, TypeError) as invalid:
        fail('VERIFICATION_FAILED', 'native refusal record is malformed: ' + str(invalid), stage)
    if code in ('SYMPY_INVALID_CONTRACT', 'SYMPY_RESOURCE_LIMIT'):
        fail('VERIFICATION_FAILED', 'native refused input that the host contract accepted', location, nativeCode=code)
    located(code, message, location, REFUSAL_RECOVERY[code], **details)


def assessment(directory, p):
    """Independent host certification of the published table; uses only coefficients, width and the published intervals."""
    coefficients = [oracle.literal(c, '$.coefficients', 'VERIFICATION_FAILED') for c in p['coefficients']]
    width = oracle.literal(p['maximumIntervalWidth'], '$.maximumIntervalWidth', 'VERIFICATION_FAILED')
    intervals = oracle.parse_table(bounded(directory / 'real-roots.csv'))
    return oracle.certify(coefficients, width, intervals)


def bindings(directory, p, summary, submission):
    return {'plan': canonical(p), 'publications': {name: digest(directory, name) for name in NATIVE_PUBLICATIONS},
            'runtime': {'identity': RUNTIME, 'observed': {k: summary['runtime'][k] for k in ('sympy', 'mpmath', 'python')},
                        # SHA-256 of the UTF-8 interpreter path string, not of executable bytes.
                        'executablePathDigest': hashlib.sha256(submission['nativeCommand'][0].encode()).hexdigest()},
            'implementation': implementation()}


def host_record(directory, p):
    summary = read(directory, 'roots-summary.json')
    return {'version': 'schemaxis.sympy.verification/1',
            'bindings': bindings(directory, p, summary, read(directory, 'compute-submission.json')),
            'assessment': assessment(directory, p)}


def run(document, directory, *, executable=None, timeout=60):
    p = plan(document)
    executable = executable or os.environ.get('SCHEMAXIS_SYMPY')
    if not executable or not Path(executable).is_absolute() or not os.access(executable, os.X_OK):
        fail('INTERPRETER_NOT_FOUND', 'configure an absolute isolated Python containing SymPy ' + REQUIRED)
    if os.name != 'posix':
        fail('UNSUPPORTED_PLATFORM', 'qualified SymPy process resource caps require POSIX')
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
        (directory / 'native-worker.py').write_text(worker_source())
        atomic_json(directory / 'native-config.json', native_config(p))
        atomic_json(directory / 'implementation.json', implementation())
        for stage in STAGES:
            try:
                execute(command(executable, stage), directory, stage, deadline - time.monotonic(), ENVIRONMENT)
            except SchemaxisError as error:
                if error.fault.code != 'RUNNER_FAILED':
                    raise
                if stage == 'compute':
                    native_refusal(directory, stage, error)
                reason = read(directory, 'readback.json').get('reason', 'published values differ') if (directory / 'readback.json').is_file() else str(error)
                fail('VERIFICATION_FAILED', 'native readback rejected the publication: ' + str(reason), stage)
        if time.monotonic() >= deadline:
            fail('RUNNER_TIMED_OUT', 'SymPy root isolation exhausted its total deadline')
        atomic_json(directory / 'roots-verification.json', host_record(directory, p))
        atomic_json(directory / 'verification.json', {'artifacts': artifacts(directory),
            'evidence': {name: digest(directory, name) for name in sorted(evidence_names())},
            'executable': str(executable), 'runtime': RUNTIME})
        result = verify(directory, require_result=False)
        if cancellation_requested():
            fail('RUNNER_CANCELLED', 'SymPy root isolation publication cancelled')
        if time.monotonic() >= deadline:
            fail('RUNNER_TIMED_OUT', 'SymPy root isolation exhausted its total deadline')
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
            fail('VERIFICATION_FAILED', 'SymPy adaptor implementation changed; rerun to verify with current code')
        if require_result:
            result = read(directory, 'result.json')
            if result.get('status') != 'succeeded' or result.get('verified') is not True:
                fail('INCOMPLETE_EXECUTION', 'SymPy root isolation did not complete')
        receipt = read(directory, 'verification.json')
        executable = receipt.get('executable')
        if not isinstance(executable, str) or not Path(executable).is_absolute() or receipt.get('runtime') != RUNTIME:
            fail('VERIFICATION_FAILED', 'native runtime identity differs')
        if bounded(directory / 'native-worker.py').decode() != worker_source() or read(directory, 'native-config.json') != native_config(p):
            fail('VERIFICATION_FAILED', 'trusted worker or native configuration differs')
        for stage in STAGES:
            submission = read(directory, stage + '-submission.json')
            if submission.get('nativeCommand') != command(executable, stage) \
                    or type(submission.get('exitCode')) is not int or submission['exitCode'] != 0:
                fail('VERIFICATION_FAILED', 'native command or completion differs', stage)
        base = {name: digest(directory, name) for name in ('native-config.json', 'native-worker.py')}
        if read(directory, 'compute-inputs.json') != base:
            fail('VERIFICATION_FAILED', 'native compute consumed different input bytes', 'compute')
        if read(directory, 'readback-inputs.json') != {**base, **{name: digest(directory, name) for name in NATIVE_PUBLICATIONS}}:
            fail('VERIFICATION_FAILED', 'native readback consumed different publication bytes', 'readback')
        readback = read(directory, 'readback.json')
        if readback.get('ok') is not True or readback.get('runtime', {}).get('sympy') != REQUIRED:
            fail('VERIFICATION_FAILED', 'native readback did not confirm the publication', 'readback')
        summary = read(directory, 'roots-summary.json')
        if summary.get('runtime', {}).get('sympy') != REQUIRED or summary.get('files') != {'real-roots.csv': digest(directory, 'real-roots.csv')}:
            fail('VERIFICATION_FAILED', 'native runtime observation or file binding differs from ' + RUNTIME)
        if any(word in summary for word in ('status', 'verified', 'certified', 'outcome')):
            fail('VERIFICATION_FAILED', 'native summary must not contain decisions')
        expected = host_record(directory, p)
        listed = [(i.get('lower'), i.get('upper'), i.get('multiplicity')) for i in summary.get('intervals', [])]
        table = oracle.parse_table(bounded(directory / 'real-roots.csv'))
        if listed != [(oracle.text(a), oracle.text(b), m) for a, b, m in table]:
            fail('VERIFICATION_FAILED', 'native summary intervals differ from the published table')
        if read(directory, 'roots-verification.json') != json.loads(json.dumps(expected)):
            fail('VERIFICATION_FAILED', 'host verification record differs from recomputation (stale, foreign or altered)')
        if not portable_artifacts(receipt.get('artifacts'), directory):
            fail('VERIFICATION_FAILED', 'publication membership or digests differ')
        if set(receipt.get('evidence', {})) != evidence_names():
            fail('VERIFICATION_FAILED', 'evidence membership differs')
        for name in evidence_names():
            if receipt['evidence'][name] != digest(directory, name):
                fail('VERIFICATION_FAILED', 'retained evidence differs', name)
        found = expected['assessment']
        return {'verified': True, 'artifacts': len(receipt['artifacts']), 'runtime': RUNTIME,
                'distinctRealRoots': found['distinctRealRoots'], 'realRootsWithMultiplicity': found['realRootsWithMultiplicity']}
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeError, OverflowError, RecursionError,
            ArithmeticError, StopIteration) as error:
        fail('VERIFICATION_FAILED', 'invalid retained SymPy evidence: ' + str(error))


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
