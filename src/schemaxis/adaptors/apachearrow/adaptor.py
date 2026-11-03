# Copyright (C) 2026 David L F Gaden
"""Typed nullable table preparation with native Arrow and independent Parquet checks."""
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
from . import parquet, reference

VERSION = 'schemaxis.apachearrow/1'
IDENT = {'type': 'string', 'minLength': 1, 'maxLength': 40, 'required': True}
LITERAL = {'type': 'string', 'maxLength': 4096}
COLUMN = {'type': 'object', 'properties': {'name': IDENT,
    'type': {'type': 'enum', 'values': reference.TYPES, 'required': True},
    'nullable': {'type': 'boolean', 'default': False}}}
PREDICATE = {'type': 'object', 'properties': {'column': IDENT,
    'test': {'type': 'enum', 'values': ['eq', 'ne', 'lt', 'le', 'gt', 'ge', 'isNull', 'isValid'], 'required': True},
    'value': LITERAL}}
SELECT = {'type': 'object', 'properties': {'column': IDENT, 'name': IDENT,
    'cast': {'type': 'enum', 'values': ['int64']}, 'fillNull': LITERAL}}
OPTIONS = {'source': {'type': 'string', 'minLength': 1, 'maxLength': 4096, 'required': True},
    'columns': {'type': 'array', 'items': COLUMN, 'minItems': 1, 'maxItems': 32, 'required': True},
    'where': {'type': 'array', 'items': PREDICATE, 'maxItems': 8, 'default': []},
    'select': {'type': 'array', 'items': SELECT, 'minItems': 1, 'maxItems': 32, 'required': True}}
DECLARATIONS = {'prepareTable': {'native': 'pyarrow.csv.read_csv / compute / Table / parquet.write_table',
    'kinds': ['file', 'text'], 'inputs': {}, 'options': {k: {'value': v} for k, v in OPTIONS.items()}}}
LOSSES = ['CSV formatting and UTC offset spelling are normalised; source row order and typed values are checked.',
    'Only the reserved CSV cell \\N means null, including quoted cells; empty text and NA remain text.',
    'Finite decimal input rounds to IEEE binary64; signed zero is preserved. No decimal-exact arithmetic.',
    'Only flat bool/int32/int64/float64/utf8/UTC-microsecond timestamps; no inferred types, metadata or units.',
    'Parquet is uncompressed PLAIN with no Arrow schema metadata, dictionaries, partitions or general Parquet input.',
    'No SQL, joins, aggregates, arbitrary expressions, narrowing casts, timezone conversion or unit conversion.']


def identifier(value, at):
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,39}', value):
        fail('INVALID_ARROW_COLUMN', 'use unique lower-case ASCII column identifiers, at most 40 characters', at)


def literal(value, kind, at):
    try:
        reference.scalar(value, kind)
    except (ValueError, OverflowError, UnicodeError) as error:
        fail('INVALID_ARROW_LITERAL', 'correct the typed nonnull literal: ' + str(error), at)


def plan(document):
    keys(document, ('version', 'operation', *OPTIONS), '$')
    if document.get('version') != VERSION:
        fail('UNSUPPORTED_VERSION', 'select ' + VERSION, '$.version')
    if document.get('operation') != 'prepareTable':
        fail('UNKNOWN_FILTER', 'select prepareTable', '$.operation')
    p = validate_arguments(OPTIONS, {k: v for k, v in document.items() if k in OPTIONS}, location='$')
    path = Path(p['source'])
    if not path.is_absolute() or path.suffix.lower() != '.csv' or '\x00' in str(path):
        fail('INVALID_ARROW_SOURCE', 'select an absolute local regular UTF-8 .csv file', '$.source')
    columns = {}
    for i, column in enumerate(p['columns']):
        at = f'$.columns[{i}]'
        identifier(column['name'], at + '.name')
        if column['name'] in columns:
            fail('INVALID_ARROW_COLUMN', 'source names must be unique', at + '.name')
        columns[column['name']] = column
    for i, predicate in enumerate(p['where']):
        at = f'$.where[{i}]'
        column = columns.get(predicate['column'])
        if column is None:
            fail('INVALID_ARROW_PREDICATE', 'filter a declared source column', at + '.column')
        has_value = predicate['test'] not in ('isNull', 'isValid')
        if has_value != ('value' in predicate):
            fail('INVALID_ARROW_PREDICATE', 'comparisons require value; isNull/isValid omit value', at)
        if column['type'] in ('bool', 'utf8') and predicate['test'] in ('lt', 'le', 'gt', 'ge'):
            fail('INVALID_ARROW_PREDICATE', 'boolean/text columns support eq, ne, isNull and isValid', at + '.test')
        if has_value:
            literal(predicate['value'], column['type'], at + '.value')
    seen, names = set(), set()
    for i, item in enumerate(p['select']):
        at = f'$.select[{i}]'
        column = columns.get(item['column'])
        identifier(item['name'], at + '.name')
        if column is None or item['column'] in seen or item['name'] in names:
            fail('INVALID_ARROW_SELECTION', 'select distinct source columns and unique output names', at)
        seen.add(item['column']); names.add(item['name'])
        if 'cast' in item and column['type'] != 'int32':
            fail('INVALID_ARROW_SELECTION', 'only int32 to int64 widening is supported', at + '.cast')
        if 'fillNull' in item:
            if not column['nullable']:
                fail('INVALID_ARROW_SELECTION', 'fillNull applies only to a nullable source', at + '.fillNull')
            literal(item['fillNull'], item.get('cast', column['type']), at + '.fillNull')
    return {'version': 'schemaxis.apachearrow.plan/1', 'operation': 'prepareTable', **p,
            'outputColumns': reference.output_columns(p), 'losses': LOSSES}


def schema():
    from schemaxis.schema import DRAFT, argument_schema, object_schema
    return {'$schema': DRAFT, **object_schema({'version': {'const': VERSION},
        'operation': {'const': 'prepareTable'}, **{k: argument_schema(v) for k, v in OPTIONS.items()}},
        ['version', 'operation', *[k for k, v in OPTIONS.items() if v.get('required')]])}


def query(document):
    plan(document)
    return ['prepareTable'], {}


def resources(document, execution, identity):
    if execution.get('threads', 1) != 1:
        fail('INVALID_EXECUTION', 'Arrow table preparation uses one CPU/I/O thread', identity)
    return {'threads': 1}


def bounded(path, code='VERIFICATION_FAILED', limit=parquet.MAX_FILE):
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


def read(directory, name):
    return json.loads(bounded(directory / name), object_pairs_hook=unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON ' + value)))


def digest(directory, name):
    return hashlib.sha256(bounded(directory / name)).hexdigest()


def source_rows(data, p):
    try:
        rows = reference.source(data, p['columns'])
        columns, output, _ = reference.transform(p, rows)
        if sum(len(value.encode('utf-8')) for row in output for value in row if isinstance(value, str)) > reference.MAX_SOURCE:
            raise ValueError('null replacement exceeds 8 MiB output text budget')
        # Check escaped JSON sizes before starting native work, including a fill
        # that expands a mostly-null table. Reserve structural/report whitespace.
        for values in (reference.wire_rows(p['columns'], rows), reference.wire_rows(columns, output)):
            budget = sum(len(json.dumps(value, ensure_ascii=True)) + 16 for row in values for value in row)
            if budget > parquet.MAX_FILE - 1024**2:
                raise ValueError('table exceeds bounded JSON snapshot/report budget')
        return rows
    except (ValueError, UnicodeError, OverflowError) as error:
        fail('INVALID_ARROW_DATA', 'correct the complete typed CSV: ' + str(error), '$.source')


def reusableInputs(document):
    p = plan(document)
    return {'table': hashlib.sha256(bounded(p['source'], 'INVALID_ARROW_SOURCE', reference.MAX_SOURCE)).hexdigest()}


def worker_source():
    return Path(__file__).with_name('native_worker.py').read_text()


def implementation():
    return {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ('adaptor.py', 'reference.py', 'parquet.py', 'native_worker.py')}


def config(p):
    return {key: p[key] for key in ('columns', 'where', 'select', 'outputColumns')}


def inspect(directory, p):
    rows = source_rows(bounded(directory / 'source.csv', limit=reference.MAX_SOURCE), p)
    columns, expected, _ = reference.transform(p, rows)
    actual = parquet.read(bounded(directory / 'table.parquet'), columns)
    if not reference.equal(actual, expected):
        fail('VERIFICATION_FAILED', 'Parquet values/types/null masks differ from captured CSV and declared transformations')
    for stage, wanted_columns, wanted_rows in [('convert', p['columns'], rows), ('readback', columns, expected)]:
        expected_snapshot = {'runtime': '26.0.0', 'cpp': '26.0.0',
            'table': {'columns': wanted_columns, 'rows': reference.wire_rows(wanted_columns, wanted_rows)}}
        if not reference.equal(read(directory, stage + '.stdout'), expected_snapshot):
            fail('VERIFICATION_FAILED', 'native CSV/readback types or exact values differ from independent reference', stage)
    return reference.report(p, rows, digest(directory, 'source.csv'))


def artifacts(directory):
    return [{'file': str(directory / name), 'kind': kind, 'sha256': digest(directory, name)}
            for name, kind in [('table.parquet', 'file'), ('table-report.json', 'text')]]


def evidence_names():
    return {'authored.json', 'plan.json', 'source.csv', 'capture.json', 'native-worker.py', 'native-config.json', 'implementation.json'} | {
        stage + suffix for stage in ('convert', 'readback')
        for suffix in ('.stdout', '.stderr', '-inputs.json', '-submission.json')}


def run(document, directory, *, executable=None, timeout=60):
    p = plan(document)
    executable = executable or os.environ.get('SCHEMAXIS_APACHEARROW')
    if not executable or not Path(executable).is_absolute() or not os.access(executable, os.X_OK):
        fail('INTERPRETER_NOT_FOUND', 'configure an absolute isolated Python >=3.11 containing PyArrow 26.0.0')
    if os.name != 'posix':
        fail('UNSUPPORTED_PLATFORM', 'qualified Arrow process resource caps require POSIX')
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
        data = bounded(p['source'], 'INVALID_ARROW_SOURCE', reference.MAX_SOURCE)
        source_rows(data, p)
        (directory / 'source.csv').write_bytes(data)
        atomic_json(directory / 'capture.json', {'source': p['source'], 'bytes': len(data),
                                               'sha256': hashlib.sha256(data).hexdigest()})
        (directory / 'native-worker.py').write_text(worker_source())
        atomic_json(directory / 'native-config.json', config(p))
        atomic_json(directory / 'implementation.json', implementation())
        for stage in ('convert', 'readback'):
            execute([str(executable), '-I', str(directory / 'native-worker.py'), stage], directory,
                    stage, deadline - time.monotonic(), {'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'LANG': 'C.UTF-8'})
        atomic_json(directory / 'table-report.json', inspect(directory, p))
        atomic_json(directory / 'verification.json', {'artifacts': artifacts(directory),
            'evidence': {name: digest(directory, name) for name in sorted(evidence_names())},
            'executable': str(executable), 'runtime': 'PyArrow 26.0.0 / Arrow C++ 26.0.0'})
        result = verify(directory, require_result=False)
        if cancellation_requested():
            fail('RUNNER_CANCELLED', 'Arrow publication cancelled')
        if time.monotonic() >= deadline:
            fail('RUNNER_TIMED_OUT', 'Arrow exhausted its total deadline')
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
        receipt = read(directory, 'verification.json')
        if not reference.equal(read(directory, 'plan.json'), p):
            fail('VERIFICATION_FAILED', 'effective table plan differs')
        if read(directory, 'implementation.json') != implementation():
            fail('VERIFICATION_FAILED', 'Arrow implementation changed; requalify retained output with current code')
        if require_result:
            result = read(directory, 'result.json')
            if result.get('status') != 'succeeded' or result.get('verified') is not True:
                fail('INCOMPLETE_EXECUTION', 'Arrow preparation did not complete')
        data = bounded(directory / 'source.csv', limit=reference.MAX_SOURCE)
        if read(directory, 'capture.json') != {'source': p['source'], 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}:
            fail('VERIFICATION_FAILED', 'captured source identity differs')
        executable = receipt['executable']
        if not isinstance(executable, str) or not Path(executable).is_absolute() or receipt['runtime'] != 'PyArrow 26.0.0 / Arrow C++ 26.0.0':
            fail('VERIFICATION_FAILED', 'native runtime identity differs')
        if bounded(directory / 'native-worker.py').decode() != worker_source() or not reference.equal(read(directory, 'native-config.json'), config(p)):
            fail('VERIFICATION_FAILED', 'trusted worker or native configuration differs')
        for stage in ('convert', 'readback'):
            submission = read(directory, stage + '-submission.json')
            if submission.get('nativeCommand') != [executable, '-I', str(directory / 'native-worker.py'), stage] or type(submission.get('exitCode')) is not int or submission['exitCode'] != 0:
                fail('VERIFICATION_FAILED', 'native command/completion differs', stage)
            consumed = 'source.csv' if stage == 'convert' else 'table.parquet'
            if read(directory, stage + '-inputs.json') != {name: digest(directory, name) for name in (consumed, 'native-config.json', 'native-worker.py')}:
                fail('VERIFICATION_FAILED', 'native consumed-input binding differs', stage)
        if not reference.equal(read(directory, 'table-report.json'), inspect(directory, p)):
            fail('VERIFICATION_FAILED', 'published report differs from independent table')
        present = {path.name for path in directory.glob('table*') if not path.name.endswith('.metadata.json')}
        if present != {'table.parquet', 'table-report.json'} or receipt['artifacts'] != artifacts(directory):
            fail('VERIFICATION_FAILED', 'publication membership/digests differ')
        if set(receipt['evidence']) != evidence_names():
            fail('VERIFICATION_FAILED', 'evidence membership differs')
        for name in evidence_names():
            if receipt['evidence'][name] != digest(directory, name):
                fail('VERIFICATION_FAILED', 'retained evidence differs', name)
        return {'verified': True, 'artifacts': 2, 'runtime': receipt['runtime'],
                'rows': read(directory, 'table-report.json')['outputRows']}
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeError, OverflowError, RecursionError) as error:
        fail('VERIFICATION_FAILED', 'invalid retained Arrow evidence: ' + str(error))


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
