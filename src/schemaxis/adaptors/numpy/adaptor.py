"""Unit-aware principal component analysis with isolated NumPy and an independent verifier."""
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
from . import oracle

VERSION = 'schemaxis.numpy/1'
OPERATION = 'principalComponents'
RUNTIME = 'NumPy 2.5.4 / OpenBLAS 0.3.34'
NAME = {'type': 'string', 'minLength': 1, 'maxLength': 40, 'required': True}
UNIT = {'type': 'string', 'minLength': 1, 'maxLength': 32, 'required': True}
POSITIVE = {'type': 'number', 'minimum': 0, 'exclusiveMinimum': True}
FRACTION = {'type': 'number', 'minimum': 0, 'maximum': 1, 'exclusiveMinimum': True, 'exclusiveMaximum': True}
CHANNEL = {'type': 'object', 'properties': {'name': NAME, 'unit': UNIT, 'scale': POSITIVE}}
KEY = {'type': 'object', 'properties': {'name': NAME, 'unit': UNIT}}
RETENTION = {'type': 'object', 'required': True, 'properties': {
    'components': {'type': 'integer', 'minimum': 1, 'maximum': 10}, 'minimumExplainedVariance': FRACTION}}
RMS = {'type': 'object', 'properties': {'channel': NAME,
    'maximum': {'type': 'number', 'minimum': 0, 'exclusiveMinimum': True, 'maximum': 1e100, 'required': True}}}
REQUIREMENTS = {'type': 'object', 'properties': {'minimumExplainedVariance': FRACTION,
    'reconstructionRMS': {'type': 'array', 'items': RMS, 'maxItems': 32}}}
OPTIONS = {
    'source': {'type': 'string', 'minLength': 1, 'maxLength': 4096, 'required': True},
    'rowKey': KEY,
    'channels': {'type': 'array', 'items': CHANNEL, 'minItems': 2, 'maxItems': 32, 'required': True},
    'scaling': {'type': 'enum', 'values': ['none', 'standardise', 'declared'], 'required': True},
    'retention': RETENTION,
    'output': {'type': 'enum', 'values': ['components', 'subspace'], 'default': 'components'},
    'loadingTolerance': {'type': 'number', 'minimum': 1e-9, 'maximum': 1e-2, 'default': 1e-6},
    'requirements': REQUIREMENTS,
}
DECLARATIONS = {OPERATION: {
    'native': 'numpy.linalg.svd(full_matrices=False) on the centred, scaled data (LAPACK gesdd)',
    'kinds': ['table', 'text'], 'inputs': {}, 'options': {k: {'value': v} for k, v in OPTIONS.items()}}}
IDENTIFIER = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,39}')
UNIT_TEXT = re.compile(r'[A-Za-z0-9][A-Za-z0-9 ._()+/*^\-]{0,31}')
RESERVED = re.compile(r'row|component|channelIndex|PC[0-9]+')
LOSSES = [
    'Decimal input is parsed to IEEE binary64; the analysis is of the parsed values. No measurement or sampling-uncertainty claim.',
    'Only bounded numeric ASCII CSV: no quotes, missing values, imputation, dates, text columns or locale decimals.',
    'Repeated or near-repeated eigenvalues never publish an arbitrary per-component basis; use subspace output.',
    'Small eigenvalues are checked to accuracy relative to the total variance, not to their own relative precision.',
    'Qualification budgets are empirical and the a posteriori bounds are first-order engineering bounds, not interval proofs.',
    'Exactly NumPy 2.5.4 with OpenBLAS 0.3.34 is qualified; other builds are refused rather than assumed compatible.']
NATIVE_CODES = {'PCA_INVALID_CONTRACT', 'PCA_UNSUPPORTED_RUNTIME', 'PCA_RESOURCE_LIMIT', 'PCA_INVALID_CSV', 'PCA_HEADER_MISMATCH',
                'PCA_MISSING_VALUE', 'PCA_INVALID_NUMBER', 'PCA_VALUE_RANGE', 'PCA_ROW_KEY_ORDER', 'PCA_DIMENSIONS',
                'PCA_CHANNEL_SPREAD', 'PCA_SCALE_RANGE', 'PCA_RECONSTRUCTION_UNCERTIFIED', *oracle.SPECTRAL_CODES}
THREADS = {'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1', 'NUMEXPR_NUM_THREADS': '1',
           'VECLIB_MAXIMUM_THREADS': '1', 'LANG': 'C.UTF-8'}
STAGES = ('compute', 'readback')
WORKER_NAMES = ('adaptor.py', 'oracle.py', 'native_worker.py')


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
    if '\x00' in p['source'] or not source.is_absolute() or source.suffix.lower() != '.csv':
        fail('PCA_INVALID_SOURCE', 'select an absolute local regular ASCII .csv file', '$.source')
    seen = set()
    columns = ([('$.rowKey', p['rowKey'])] if 'rowKey' in p else []) + [(f'$.channels[{i}]', c) for i, c in enumerate(p['channels'])]
    for at, column in columns:
        name = column['name']
        if not IDENTIFIER.fullmatch(name) or RESERVED.fullmatch(name) or name in seen:
            located('PCA_INVALID_CONTRACT', 'names are distinct identifiers (letter then letters, digits or _; at most 40) '
                    'and not row, component, channelIndex or PC<n>', at + '.name', 'rename the CSV column and its declaration')
        if not UNIT_TEXT.fullmatch(column['unit']):
            located('PCA_INVALID_CONTRACT', 'units are plain text of at most 32 characters', at + '.unit')
        seen.add(name)
    mode = p['scaling']
    for i, channel in enumerate(p['channels']):
        if mode == 'declared' and 'scale' not in channel:
            located('PCA_INVALID_CONTRACT', 'declared scaling needs a positive scale for every channel', f'$.channels[{i}].scale',
                    'state the scale in the channel unit, for example a nominal range or resolution')
        if mode != 'declared' and 'scale' in channel:
            located('PCA_INVALID_CONTRACT', 'a channel scale is only used with declared scaling', f'$.channels[{i}].scale',
                    'remove the scale or select declared scaling')
        if 'scale' in channel and not 1e-300 <= channel['scale'] <= 1e300:
            located('PCA_INVALID_CONTRACT', 'declared scales must be finite positive values within [1e-300, 1e300]', f'$.channels[{i}].scale')
    units = sorted({c['unit'] for c in p['channels']})
    if mode == 'none' and len(units) != 1:
        located('PCA_UNIT_MISMATCH', 'unscaled covariance PCA needs one shared channel unit', '$.scaling',
                'convert the channels to one unit upstream, or choose standardise or declared scaling', units=units)
    retention = p['retention']
    if len(retention) != 1:
        located('PCA_INVALID_CONTRACT', 'retention needs exactly one of components or minimumExplainedVariance', '$.retention')
    if retention.get('components', 0) > len(p['channels']):
        located('PCA_INVALID_CONTRACT', 'cannot retain more components than channels', '$.retention.components')
    names = [c['name'] for c in p['channels']]
    requirements = p.get('requirements', {})
    required = set()
    for i, item in enumerate(requirements.get('reconstructionRMS', [])):
        if item['channel'] not in names or item['channel'] in required:
            located('PCA_INVALID_CONTRACT', 'each RMS requirement names a distinct declared channel',
                    f'$.requirements.reconstructionRMS[{i}].channel')
        required.add(item['channel'])
    config = native_config(p)
    return {'version': 'schemaxis.numpy.plan/1', 'operation': OPERATION, **p, 'header': config['header'],
            'publications': [name for name, _ in publications(p)], 'limits': oracle.LIMITS, 'runtime': RUNTIME,
            'losses': LOSSES}


def native_config(p):
    header = ([p['rowKey']['name']] if 'rowKey' in p else []) + [c['name'] for c in p['channels']]
    return {'header': header, 'keyed': 'rowKey' in p, 'channels': p['channels'], 'scaling': p['scaling'],
            'retention': p['retention'], 'output': p['output'], 'loadingTolerance': p['loadingTolerance'],
            'requirements': p.get('requirements', {})}


def publications(p):
    """Fixed publication order; indices are stable workflow handoff addresses for each output mode."""
    tables = (['loadings.csv', 'scores.csv'] if p['output'] == 'components' else ['projector.csv'])
    return ([('spectrum.csv', 'table')] + [(name, 'table') for name in tables] + [('reconstruction.csv', 'table'),
            ('pca-summary.json', 'text'), ('pca-verification.json', 'text')])


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
        fail('INVALID_EXECUTION', 'PCA uses one native BLAS/OpenMP thread', identity)
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


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def reusableInputs(document):
    p = plan(document)
    return {p['source']: hashlib.sha256(bounded(p['source'], 'PCA_INVALID_SOURCE', oracle.LIMITS['maxBytes'])).hexdigest()}


def retainedInputs(directory, document):
    """Original source path and digest, authenticated by the retained capture; never rereads the original.

    The framework calls this after ordinary verification succeeds. The retained bytes must agree with the
    authored document, the effective plan, the capture record, the native consumed-input binding and the
    host verification record. Any disagreement is a fault, never an empty or partial map.
    """
    directory = Path(directory).absolute()
    try:
        p = plan(document)
        if read(directory, 'authored.json') != json.loads(json.dumps(document)) or read(directory, 'plan.json') != json.loads(json.dumps(p)):
            fail('VERIFICATION_FAILED', 'retained input provenance belongs to a different document')
        data = bounded(directory / 'source.csv', limit=oracle.LIMITS['maxBytes'])
        sha = hashlib.sha256(data).hexdigest()
        if read(directory, 'capture.json') != {'source': p['source'], 'bytes': len(data), 'sha256': sha}:
            fail('VERIFICATION_FAILED', 'retained capture identity differs')
        if read(directory, 'compute-inputs.json').get('source.csv') != sha:
            fail('VERIFICATION_FAILED', 'native compute consumed different source bytes', 'compute')
        if read(directory, 'pca-verification.json')['bindings']['source'] != sha:
            fail('VERIFICATION_FAILED', 'host verification is bound to different source bytes')
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
    return ({'authored.json', 'plan.json', 'source.csv', 'capture.json', 'native-worker.py', 'native-config.json',
             'implementation.json', 'compute-inputs.json', 'readback-inputs.json', 'readback.json'}
            | {stage + suffix for stage in STAGES for suffix in ('.stdout', '.stderr', '-submission.json')})


def command(executable, stage):
    # Run-relative worker under the run cwd, so the exact command survives a portable export.
    return [str(executable), '-I', '-B', 'native-worker.py', stage]


def artifacts(directory, p):
    return [{'file': str(directory / name), 'kind': kind, 'sha256': digest(directory, name)} for name, kind in publications(p)]


def portable_artifacts(recorded, directory, p):
    """Compare publication order, names, kinds and current digests; the recorded run location may differ after export."""
    expected = artifacts(directory, p)
    if not isinstance(recorded, list) or len(recorded) != len(expected):
        return False
    files = [item.get('file') if isinstance(item, dict) else None for item in recorded]
    if not all(isinstance(f, str) and Path(f).is_absolute() for f in files) or len({str(Path(f).parent) for f in files}) != 1:
        return False
    return all(item == {**want, 'file': str(Path(f).parent / Path(want['file']).name)} for item, want, f in zip(recorded, expected, files))


def native_refusal(directory, stage, error, config, data):
    """Map a structured worker refusal to its located fault after an independent consistency check."""
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
    if code in oracle.SPECTRAL_CODES:
        prediction = oracle.predict(config, data)
        lam, total = details.get('eigenvalues'), details.get('totalVariance')
        tol = prediction['tol']
        if not (isinstance(lam, list) and len(lam) == len(prediction['values']) and all(type(x) in (int, float) and math.isfinite(x) for x in lam)
                and type(total) in (int, float) and abs(total - prediction['stats']['total']) <= tol['tauTotal']
                and max(abs(a - b) for a, b in zip(lam, prediction['values'])) <= tol['tauLambda']):
            fail('VERIFICATION_FAILED', 'native spectral refusal disagrees with the independent spectrum', '$.retention')
        native_tol = oracle.policy(prediction['stats']['n'], prediction['stats']['p'], total, config['loadingTolerance'])
        _, rule = oracle.decide(lam, config, native_tol, native_tol['band'])
        host_side = prediction['fault'][0] if prediction['fault'] else None
        if rule is None or rule[0] != code or not (host_side == code or oracle.within_band(prediction, config, 2 * tol['band'])):
            fail('VERIFICATION_FAILED', 'native spectral refusal is not reproduced by the declared rule', '$.retention')
    elif code not in ('PCA_VALUE_RANGE', 'PCA_RECONSTRUCTION_UNCERTIFIED', 'PCA_UNSUPPORTED_RUNTIME') or (
            code == 'PCA_VALUE_RANGE' and location.split(':')[0] not in ('intermediate', 'published')):
        fail('VERIFICATION_FAILED', 'native refused input that the host parser and contract accepted', location, nativeCode=code)
    recovery = {'PCA_RECONSTRUCTION_UNCERTIFIED': certification_recovery(details.get('ratio'), config['loadingTolerance']),
                'PCA_UNSUPPORTED_RUNTIME': 'configure an isolated Python with exactly NumPy 2.5.4 linked to OpenBLAS 0.3.34, or requalify another build'}
    located(code, message, location, recovery.get(code), **details)


def certification_recovery(ratio, eta):
    if type(ratio) not in (int, float) or not math.isfinite(ratio):
        return 'use standardise scaling or less extreme declared scales; the reconstruction uncertainty is not finite'
    return ('the validated reconstruction uncertainty is {:.3g} x loadingTolerance x sample deviation; use standardise scaling, '
            'less extreme declared scales, or a loadingTolerance of at least {:.3g} only if that accuracy is defensible').format(ratio, ratio * eta)


def bindings(directory, p, data, summary, submission):
    return {'source': hashlib.sha256(data).hexdigest(), 'parsedDigest': summary['parsedDigest'], 'plan': canonical(p),
            'publications': {name: digest(directory, name) for name, _ in publications(p) if name != 'pca-verification.json'},
            'runtime': {'identity': RUNTIME, 'observed': {k: summary['runtime'][k] for k in ('numpy', 'blas', 'python')},
                        # SHA-256 of the UTF-8 interpreter path string, not of executable bytes.
                        'executablePathDigest': hashlib.sha256(submission['nativeCommand'][0].encode()).hexdigest()},
            'implementation': implementation()}


def host_record(directory, p, data):
    """Independent host verification artefact: the sole final requirement/tolerance record."""
    config = native_config(p)
    summary = read(directory, 'pca-summary.json')
    tables = {name: bounded(directory / name) for name, kind in publications(p) if name.endswith('.csv')}
    assessment = oracle.assess(config, data, summary, tables)
    return {'version': 'schemaxis.numpy.verification/1',
            'bindings': bindings(directory, p, data, summary, read(directory, 'compute-submission.json')),
            'assessment': assessment}


def run(document, directory, *, executable=None, timeout=120):
    p = plan(document)
    executable = executable or os.environ.get('SCHEMAXIS_NUMPY')
    if not executable or not Path(executable).is_absolute() or not os.access(executable, os.X_OK):
        fail('INTERPRETER_NOT_FOUND', 'configure an absolute isolated Python containing NumPy 2.5.4 linked to OpenBLAS 0.3.34')
    if os.name != 'posix':
        fail('UNSUPPORTED_PLATFORM', 'qualified NumPy process resource caps require POSIX')
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
    config = native_config(p)
    try:
        data = bounded(p['source'], 'PCA_INVALID_SOURCE', oracle.LIMITS['maxBytes'])
        oracle.statistics(oracle.parse(data, config)[1], config)      # complete host validation before launch
        (directory / 'source.csv').write_bytes(data)
        atomic_json(directory / 'capture.json', {'source': p['source'], 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        (directory / 'native-worker.py').write_text(worker_source())
        atomic_json(directory / 'native-config.json', config)
        atomic_json(directory / 'implementation.json', implementation())
        for stage in STAGES:
            try:
                execute(command(executable, stage), directory, stage,
                        deadline - time.monotonic(), THREADS)
            except SchemaxisError as error:
                if error.fault.code != 'RUNNER_FAILED':
                    raise
                if stage == 'compute':
                    native_refusal(directory, stage, error, config, data)
                reason = read(directory, 'readback.json').get('reason', 'published values differ') if (directory / 'readback.json').is_file() else str(error)
                fail('VERIFICATION_FAILED', 'native readback rejected the publication: ' + str(reason), stage)
        if time.monotonic() >= deadline:
            fail('RUNNER_TIMED_OUT', 'NumPy PCA exhausted its total deadline')
        atomic_json(directory / 'pca-verification.json', host_record(directory, p, data))
        atomic_json(directory / 'verification.json', {'artifacts': artifacts(directory, p),
            'evidence': {name: digest(directory, name) for name in sorted(evidence_names())},
            'executable': str(executable), 'runtime': RUNTIME})
        result = verify(directory, require_result=False)
        if cancellation_requested():
            fail('RUNNER_CANCELLED', 'NumPy PCA publication cancelled')
        if time.monotonic() >= deadline:
            fail('RUNNER_TIMED_OUT', 'NumPy PCA exhausted its total deadline')
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


OUTCOME_CODES = {'uncertified': 'PCA_RECONSTRUCTION_UNCERTIFIED', 'requirementsUnmet': 'PCA_REQUIREMENT_NOT_MET',
                 'requirementsIndeterminate': 'PCA_REQUIREMENT_INDETERMINATE'}


def outcome_fault(p, assessment):
    """Refuse a verified publication whose certification or declared requirements are not satisfied."""
    outcome = assessment['outcome']
    if outcome == 'accepted':
        return
    names = [c['name'] for c in p['channels']]
    if outcome == 'uncertified':
        channel = assessment['certification']['uncertifiedChannels'][0]
        j = names.index(channel)
        ratio = assessment['certification']['ratio'][j]
        located('PCA_RECONSTRUCTION_UNCERTIFIED', 'the published reconstruction of this channel cannot be supported to loadingTolerance x its spread',
                f'$.channels[{j}]', certification_recovery(ratio, p['loadingTolerance']), channel=channel, ratio=ratio,
                certification=assessment['certification'])
    wanted = 'unmet' if outcome == 'requirementsUnmet' else 'indeterminate'
    requirements = assessment['requirements']
    key = next(k for k, v in requirements['status'].items() if v == wanted)
    if key == 'minimumExplainedVariance':
        at = '$.requirements.minimumExplainedVariance'
    else:
        items = p['requirements']['reconstructionRMS']
        at = f'$.requirements.reconstructionRMS[{next(i for i, x in enumerate(items) if "reconstructionRMS." + x["channel"] == key)}].maximum'
    if outcome == 'requirementsUnmet':
        located('PCA_REQUIREMENT_NOT_MET', 'the verified analysis does not meet a declared requirement', at,
                'inspect pca-verification.json; the evidence is retained but must not be used as an accepted deliverable',
                status=requirements['status'], overall=requirements['overall'])
    located('PCA_REQUIREMENT_INDETERMINATE', 'a declared requirement lies within the effective verification tolerance of its bound', at,
            'inspect pca-verification.json; move the bound beyond measured value +/- effective tolerance only if that is scientifically defensible',
            status=requirements['status'], overall=requirements['overall'])


def verify(directory, require_result=True):
    directory = Path(directory).absolute()
    try:
        p = plan(read(directory, 'authored.json'))
        if read(directory, 'plan.json') != json.loads(json.dumps(p)):
            fail('VERIFICATION_FAILED', 'effective plan differs')
        if read(directory, 'implementation.json') != implementation():
            fail('VERIFICATION_FAILED', 'NumPy adaptor implementation changed; rerun to verify with current code')
        result = read(directory, 'result.json') if require_result else None
        if result is not None and (result.get('status') != 'succeeded' or result.get('verified') is not True):
            code = result.get('fault', {}).get('code') if isinstance(result.get('fault'), dict) else None
            if code not in OUTCOME_CODES.values():
                fail('INCOMPLETE_EXECUTION', 'NumPy PCA did not complete')
        data = bounded(directory / 'source.csv', limit=oracle.LIMITS['maxBytes'])
        if read(directory, 'capture.json') != {'source': p['source'], 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}:
            fail('VERIFICATION_FAILED', 'captured source identity differs')
        receipt = read(directory, 'verification.json')
        executable = receipt.get('executable')
        if not isinstance(executable, str) or not Path(executable).is_absolute() or receipt.get('runtime') != RUNTIME:
            fail('VERIFICATION_FAILED', 'native runtime identity differs')
        config = native_config(p)
        if bounded(directory / 'native-worker.py').decode() != worker_source() or read(directory, 'native-config.json') != json.loads(json.dumps(config)):
            fail('VERIFICATION_FAILED', 'trusted worker or native configuration differs')
        for stage in STAGES:
            submission = read(directory, stage + '-submission.json')
            if submission.get('nativeCommand') != command(executable, stage) \
                    or type(submission.get('exitCode')) is not int or submission['exitCode'] != 0:
                fail('VERIFICATION_FAILED', 'native command or completion differs', stage)
        native_files = [name for name, _ in publications(p) if name != 'pca-verification.json']
        base = {name: digest(directory, name) for name in ('source.csv', 'native-config.json', 'native-worker.py')}
        if read(directory, 'compute-inputs.json') != base:
            fail('VERIFICATION_FAILED', 'native compute consumed different input bytes', 'compute')
        if read(directory, 'readback-inputs.json') != {**base, **{name: digest(directory, name) for name in native_files}}:
            fail('VERIFICATION_FAILED', 'native readback consumed different publication bytes', 'readback')
        readback = read(directory, 'readback.json')
        if readback.get('ok') is not True or readback.get('runtime', {}).get('numpy') != '2.5.4' \
                or readback.get('runtime', {}).get('blas') != 'OpenBLAS 0.3.34':
            fail('VERIFICATION_FAILED', 'native readback did not confirm the publication', 'readback')
        summary = read(directory, 'pca-summary.json')
        observed = summary.get('runtime', {})
        if observed.get('numpy') != '2.5.4' or observed.get('blas') != 'OpenBLAS 0.3.34':
            fail('VERIFICATION_FAILED', 'native runtime observation differs from ' + RUNTIME)
        if any(word in summary for word in ('status', 'overall', 'rmsTolerance')) or 'requirements' in summary:
            fail('VERIFICATION_FAILED', 'native summary must not contain requirement decisions')
        expected = host_record(directory, p, data)
        if read(directory, 'pca-verification.json') != json.loads(json.dumps(expected)):
            fail('VERIFICATION_FAILED', 'host verification record differs from recomputation (stale, foreign or altered)')
        if not portable_artifacts(receipt.get('artifacts'), directory, p):
            fail('VERIFICATION_FAILED', 'publication membership or digests differ')
        if set(receipt.get('evidence', {})) != evidence_names():
            fail('VERIFICATION_FAILED', 'evidence membership differs')
        for name in evidence_names():
            if receipt['evidence'][name] != digest(directory, name):
                fail('VERIFICATION_FAILED', 'retained evidence differs', name)
        assessment = expected['assessment']
        outcome_fault(p, assessment)
        if result is not None and result.get('status') != 'succeeded':
            fail('INCOMPLETE_EXECUTION', 'NumPy PCA did not complete')
        return {'verified': True, 'artifacts': len(receipt['artifacts']), 'runtime': RUNTIME,
                'retained': assessment['retained'], 'requirements': assessment['requirements']['overall']}
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeError, OverflowError, RecursionError,
            ArithmeticError, StopIteration) as error:
        fail('VERIFICATION_FAILED', 'invalid retained NumPy evidence: ' + str(error))


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
