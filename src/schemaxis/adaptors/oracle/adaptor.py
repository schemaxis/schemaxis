"""Oracle Database adaptor: typed tables, relational reports, mutations and transactions.

The host plans, generates trusted SQL, captures sources and verifies every native
result against an independent reference. python-oracledb is imported only by the
worker process (``native_worker.py``) in the interpreter configured for this adaptor.
"""
import base64
import csv
from decimal import Decimal
import errno
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import time
import urllib.parse

from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail
from schemaxis.native_command import execute
from . import model, planning, reference, sql
from .model import DECLARATIONS, VERSION, canonical, problem

LIMIT = 4 * 1024 * 1024
READBACK_ROWS = 20000
STAGES = {'inspect': ('identify', 'readback')}
IMPLEMENTATION = ('adaptor.py', 'model.py', 'planning.py', 'sql.py', 'reference.py', 'native_worker.py')
MARKER_SQL = "SELECT comments FROM user_tab_comments WHERE table_name = :1 AND table_type = 'TABLE'"
NULL_TOKEN = '\\N'
NATIVE_CODES = {'ORACLE_DRIVER_UNAVAILABLE', 'ORACLE_CREDENTIALS_MISSING', 'ORACLE_AUTHENTICATION_FAILED', 'ORACLE_UNAVAILABLE', 'ORACLE_CALL_TIMEOUT',
                'ORACLE_PRIVILEGE_DENIED', 'ORACLE_OBJECT_EXISTS', 'ORACLE_OBJECT_MISSING', 'ORACLE_OBJECT_IN_USE', 'ORACLE_CONSTRAINT_VIOLATION',
                'ORACLE_ARITHMETIC_ERROR', 'ORACLE_ROWCOUNT_MISMATCH', 'ORACLE_RESULT_TOO_LARGE', 'ORACLE_COMMIT_OUTCOME_UNKNOWN', 'ORACLE_SERVER_ERROR',
                'ORACLE_PROGRAM_REFUSED', 'ORACLE_UNSUPPORTED_MODE', 'ORACLE_WORKER_ERROR', 'ORACLE_VALUE_NOT_STORABLE', 'ORACLE_SERIALIZATION_CONFLICT', 'ORACLE_PRECOMMIT_MISMATCH', 'ORACLE_UNDECLARED_EFFECTS'}
RECOVERY = {
    'ORACLE_DRIVER_UNAVAILABLE': 'install python-oracledb in the dedicated interpreter passed with --oracle; the host Python needs no driver',
    'ORACLE_CREDENTIALS_MISSING': 'export the named environment variables in the process that runs Schemaxis; their values are never written to documents or evidence',
    'ORACLE_AUTHENTICATION_FAILED': 'check the user and password held by the named variables for this profile; the failed values are not echoed',
    'ORACLE_UNAVAILABLE': 'start the database listener, check the service name in the DSN variable, then run again in a fresh output directory',
    'ORACLE_CALL_TIMEOUT': 'raise connection.callTimeoutSeconds, or reduce the work; uncommitted changes were abandoned by the session',
    'ORACLE_PRIVILEGE_DENIED': 'grant the connecting user CREATE TABLE and quota on its default tablespace, or use a schema that has them',
    'ORACLE_OBJECT_EXISTS': 'choose a free table name, or drop the table yourself; this adaptor never replaces or drops a table it did not create in the same run',
    'ORACLE_OBJECT_MISSING': 'create the table first (load) or declare it as created rather than external',
    'ORACLE_CONSTRAINT_VIOLATION': 'the transaction was rolled back; read observed.oracle, the step and the constraint, then correct the data or the step',
    'ORACLE_ARITHMETIC_ERROR': 'a division by zero or NUMBER overflow occurred; filter the rows, or set divide zero to null',
    'ORACLE_VALUE_NOT_STORABLE': 'an assigned value would lose digits or exceed the target column (scale, precision, length): round it explicitly in the step, widen the column, or set scalePolicy to round; nothing was changed',
    'ORACLE_ALREADY_APPLIED': 'this change is already recorded in the ledger: verify its effect with report or inspect; do not rerun it, and use a new key only for a genuinely new change',
    'ORACLE_IDEMPOTENCY_CONFLICT': 'the key was used for different work: choose a new key for this change, or restore the original document',
    'ORACLE_ROWCOUNT_MISMATCH':'the transaction was rolled back because expectRows differed from the rows affected; correct the where condition or the expectation',
    'ORACLE_RESULT_TOO_LARGE': 'add a filter, group the rows, or use limit so that the result has at most 10000 rows',
    'ORACLE_COMMIT_OUTCOME_UNKNOWN': 'do not rerun this transaction: inspect the tables with inspect/report first; observed.resolution shows what a fresh session saw',
    'ORACLE_UNDECLARED_EFFECTS': 'mutation was refused before DML: remove enabled triggers, virtual/default columns, function/domain indexes and row policies, and declare every incoming CASCADE/SET NULL child and its schema; use report/inspect for read-only work',
    'ORACLE_SERIALIZATION_CONFLICT': 'Oracle refused the serializable transaction and it was rolled back; inspect the ledger and current state before a fresh attempt. Fresh deferred-segment tables can also cause ORA-08177: provision the ledger with SEGMENT CREATION IMMEDIATE before using it',
    'ORACLE_PRECOMMIT_MISMATCH': 'the native transaction differed from its prospective reference and was rolled back; inspect the retained evidence and concurrent schema activity',
    'ORACLE_SERVER_ERROR': 'read observed.oracle for the Oracle error number and correct the declaration or the data',
    'ORACLE_PROGRAM_REFUSED': 'the worker refused a statement that did not match a generated shape; reinstall the adaptor',
    'ORACLE_UNSUPPORTED_MODE': 'this adaptor is qualified for python-oracledb Thin mode only',
    'ORACLE_WORKER_ERROR': 'inspect the retained stage stderr and fault files',
}


# --- planning hooks -------------------------------------------------------------
def plan(document):
    return planning.plan_document(document)


def schema():
    return model.document_schema()


def query(document):
    return [plan(document)['operation']], {}


def resources(document, execution, identity):
    if execution.get('threads', 1) != 1:
        fail('INVALID_EXECUTION', 'Oracle database workflows are serial', identity)
    return {'threads': 1}


def source_digests(document):
    """Digests of the captured local sources only. Deliberately NOT registered as a reuse hook: a live
    database's rows and schema change independently of these files, so no run is reusable by identity."""
    p = plan(document)
    return {t['name']: hashlib.sha256(source_bytes(t, i)).hexdigest() for i, t in enumerate(p['tables']) if t['source']}


# --- files ----------------------------------------------------------------------
SOURCE_REASONS = {'missing': 'the file does not exist', 'symlink': 'file symlinks are not accepted', 'not-regular': 'a regular file is required',
                  'too-large': 'the file exceeds its byte budget', 'unreadable': 'the file could not be read'}


def bounded(path, code='VERIFICATION_FAILED', limit=LIMIT, at=None, **context):
    reason = 'unreadable'
    try:
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        except FileNotFoundError:
            reason = 'missing'
            raise
        except OSError as error:
            if error.errno == errno.ELOOP:
                reason = 'symlink'
            raise
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                reason = 'not-regular'
                raise ValueError('not a regular file')
            if info.st_size > limit:
                reason = 'too-large'
                raise ValueError('byte budget exceeded')
        except BaseException:
            os.close(fd)
            raise
        with os.fdopen(fd, 'rb') as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            reason = 'too-large'
            raise ValueError('byte budget exceeded')
        return data
    except (ValueError, OSError) as error:
        if at is None:
            fail(code, 'select an intact bounded regular file: ' + str(error), str(path), reason=reason, **context)
        fail(code, 'select an intact bounded regular file: ' + SOURCE_REASONS[reason], at, reason=reason, limit=limit, **context)


def read(directory, name):
    try:
        return reference.decode_json(bounded(Path(directory) / name))
    except (ValueError, UnicodeError) as error:
        fail('VERIFICATION_FAILED', 'retained evidence is not valid JSON: ' + str(error), name)


def digest(directory, name):
    return hashlib.sha256(bounded(Path(directory) / name)).hexdigest()


def dumps(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def source_bytes(table, index):
    return bounded(table['source']['path'], 'INVALID_ORACLE_SOURCE', LIMIT, at=f'$.tables[{index}].source.path', table=table['name'])


def implementation():
    return {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in IMPLEMENTATION}


def worker_source():
    """Self-contained trusted worker, including the dependency-free prospective reference.

    The isolated interpreter need not have Schemaxis installed. Only repository sources,
    never authored code, enter this bundle; the verifier reconstructs these exact bytes.
    """
    root = Path(__file__).parents[2]
    modules = ('core.contracts', 'core.faults', 'core.declarations',
               'adaptors.oracle.model', 'adaptors.oracle.sql', 'adaptors.oracle.reference')
    sources = {f'schemaxis.{name}': (root / (name.replace('.', '/') + '.py')).read_text() for name in modules}
    bootstrap = "import sys, types\n"
    bootstrap += "for name in ('schemaxis', 'schemaxis.core', 'schemaxis.adaptors', 'schemaxis.adaptors.oracle'):\n    module = types.ModuleType(name); module.__path__ = []; sys.modules[name] = module\n"
    bootstrap += f"_trusted_sources = {sources!r}\n"
    bootstrap += "for name, source in _trusted_sources.items():\n    module = types.ModuleType(name); module.__package__ = name.rpartition('.')[0]; sys.modules[name] = module; exec(compile(source, '<trusted ' + name + '>', 'exec'), module.__dict__)\n"
    return bootstrap + Path(__file__).with_name('native_worker.py').read_text()


def stages(p):
    return STAGES.get(p['operation'], ('identify', 'apply', 'readback'))


def command(executable, stage):
    return [str(executable), '-I', '-B', 'native-worker.py', stage]


# --- capture and programs ---------------------------------------------------------
def capture(directory, p):
    """Copy each source into the run, validate typed rows and every declared constraint before any native work."""
    captures, data = {}, {}
    for i, table in enumerate(p['tables']):
        if table['external']:
            continue
        if table['source']:
            raw = source_bytes(table, i)
            name = f'source-{table["name"]}.{table["source"]["format"]}'
            (Path(directory) / name).write_bytes(raw)
            captures[table['name']] = {'source': table['source']['path'], 'file': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
            data[table['name']] = reference.parse_source(table, raw, f'$.tables[{i}].source')
        else:
            data[table['name']] = []
    return captures, data


def check_initial(p, data):
    managed = [t for t in p['tables'] if not t['external']]
    found = reference.violations(managed, data)
    if found:
        problem('INVALID_ORACLE_VALUE', f'the captured rows violate a {found[0]} constraint on {found[1]} ({found[2]})', '$.tables',
                'correct the source rows so that keys, references and checks hold before loading', table=found[1], constraint=found[0], reason='constraint')


def reload_data(directory, p):
    data = {}
    for i, table in enumerate(p['tables']):
        if table['external']:
            continue
        data[table['name']] = reference.parse_source(table, bounded(Path(directory) / f'source-{table["name"]}.{table["source"]["format"]}'), f'$.tables[{i}].source') if table['source'] else []
    return data


def physical_names(p, run_id):
    """Logical-to-physical table names. Scratch tables (setup.retain false) get a run-unique suffix, so two jobs that
    stage the same logical table never collide and cleanup can never reach another run's table. Retained tables keep their
    declared names (a person will look for them) and a taken name is refused. External tables are never renamed."""
    if p['operation'] == 'inspect' or p['setup']['retain'] or not run_id:
        return {}
    return {t['name']: f'{t["name"]}_{run_id[:5]}' for t in p['tables'] if not t['external']}


def physicalise(p, names):
    """A copy of the plan whose table references name the physical tables, for SQL generation only. Aliases, column
    references and every key that analysis uses stay logical."""
    if not names:
        return p
    q = json.loads(json.dumps(p))
    rename = lambda n: names.get(n, n)
    for t in q['tables']:
        t['name'] = rename(t['name'])
        for fk in t['foreignKeys']:
            fk['table'] = rename(fk['table'])
    q['order'] = [rename(n) for n in q['order']]
    for s in q.get('report', {}).get('selects', []):
        s['from']['table'] = rename(s['from']['table'])
        for j in s['joins']:
            j['table'] = rename(j['table'])
    for s in q.get('transaction', {}).get('steps', []):
        if 'table' in s:
            s['table'] = rename(s['table'])
    return q


def names_for(p, names=None):
    if p['operation'] == 'inspect':
        return p['inspection']['names']
    return [(names or {}).get(t['name'], t['name']) for t in p['tables']]


def identify_program(p, run_id=None):
    return {'identity': sql.identity_queries(), 'catalog': sql.catalog_queries(names_for(p, physical_names(p, run_id)))}


def table_queries(p, names=None):
    q = physicalise(p, names or {})
    return {t['name']: {'sql': sql.table_readback_sql(pt), 'binds': [], 'columns': [{'name': c['name'], 'kind': c['type']} for c in t['columns']], 'maxRows': READBACK_ROWS}
            for t, pt in zip(p['tables'], q['tables'])}


def created_tables(directory):
    """Tables whose CREATE this run completed: the worker's result, its partial result after a refusal, or (when the
    worker was killed before writing either) its synced journal."""
    for name in ('apply.json', 'apply-partial.json'):
        if (Path(directory) / name).is_file():
            return list(read(directory, name).get('created', []))
    return journal_state(directory)[0]


def readback_program(p, created=(), keep=False, run_id=None):
    """Cleanup drops only tables this run created, and the worker re-checks that each still carries THIS run's marker
    immediately before dropping it; never after an unknown commit outcome."""
    names = physical_names(p, run_id)
    cleanup = []
    if p['operation'] != 'inspect' and not p['setup']['retain'] and not keep:
        cleanup = [{'table': names.get(n, n).upper(), 'sql': sql.drop_sql(names.get(n, n))} for n in reversed(p['order']) if n in created]
    return {'catalog': sql.catalog_queries(names_for(p, names)), 'tables': {} if p['operation'] == 'inspect' else table_queries(p, names), 'cleanup': cleanup,
            'marker': {'sql': MARKER_SQL, 'value': sql.run_marker(run_id) if run_id else None}}


def ddl(identifier, text, creates=None):
    step = {'id': identifier, 'kind': 'ddl', 'sql': text}
    if creates:
        step['creates'] = creates
    return step


def mutation_steps(p, names=None):
    tx = p['transaction']
    physical = physicalise(p, names or {})['transaction']['steps']
    by_name = {t['name']: t for t in p['tables']}
    steps = [{'id': 'isolation', 'kind': 'control', 'action': 'serializable'}] if tx['isolation'] == 'serializable' else []
    # Existing tables: read their base state INSIDE the snapshot the changes will run in; the reference starts from this read.
    queries = table_queries(p, names)
    steps += [{'id': 'base:' + t['name'], 'kind': 'query', **queries[t['name']]} for t in p['tables']]
    steps.append({'id': 'prospective', 'kind': 'validate', 'plan': p})
    for i, (logical, step) in enumerate(zip(tx['steps'], physical)):
        identifier, kind = f'step:{i}', step['kind']
        if kind in ('savepoint', 'rollbackTo'):
            steps.append({'id': identifier, 'kind': 'control', 'action': kind, 'name': step['name']})
            continue
        table = by_name[logical['table']]
        kinds = {c['name']: c['type'] for c in table['columns']}
        if kind == 'insert':
            text, types = sql.insert_sql(step['table'], step['columns'], kinds)
            steps.append({'id': identifier, 'kind': 'insert', 'sql': text, 'types': types, 'rows': [sql.row_binds(step['columns'], kinds, r) for r in step['rows']], 'expectRows': step.get('expectRows')})
        elif kind == 'merge':
            text, types = sql.merge_sql(step, kinds)
            steps.append({'id': identifier, 'kind': 'dml', 'sql': text, 'types': types, 'rows': [sql.row_binds(step['columns'], kinds, r) for r in step['rows']], 'expectRows': step.get('expectRows')})
        elif kind == 'check':
            text, binds = sql.dml_sql(step)
            steps.append({'id': identifier, 'kind': 'query', 'sql': text, 'binds': binds, 'columns': [{'name': 'n', 'kind': 'number'}], 'expectCount': step['expectRows']})
        else:
            text, binds = sql.dml_sql(step)
            steps.append({'id': identifier, 'kind': 'dml', 'sql': text, 'binds': binds, 'expectRows': step.get('expectRows')})
    return steps


QUERY_ONLY_ACTIONS = ('serializable', 'commit')


def query_only(steps):
    """The report snapshot may contain only reads and the control steps that open and close its transaction."""
    for step in steps:
        if step['kind'] == 'query' and step['sql'].startswith('SELECT '):
            continue
        if step['kind'] == 'control' and step['action'] in QUERY_ONLY_ACTIONS:
            continue
        raise ValueError('a report snapshot may not contain ' + step['kind'] + ' step ' + step['id'])


def apply_program(p, data, run_id):
    names = physical_names(p, run_id)
    q = physicalise(p, names)
    by_name = {t['name']: t for t in p['tables']}
    physical = {t['name']: pt for t, pt in zip(p['tables'], q['tables'])}
    creating = [by_name[n] for n in p['order'] if not by_name[n]['external']]
    marker = sql.run_marker(run_id)
    steps = []
    if p['operation'] == 'mutate':
        steps.append({'id': 'effect-boundary', 'kind': 'boundary', 'queries': sql.mutation_boundary_queries([names.get(t['name'], t['name']) for t in p['tables']])})
    for t in creating:
        steps += [ddl('create:' + t['name'], sql.create_table_sql(physical[t['name']]), creates=t['name']), ddl('comment:' + t['name'], sql.comment_sql(physical[t['name']], marker))]
    for t in creating:
        rows = data[t['name']]
        if rows:
            columns = [c['name'] for c in t['columns']]
            kinds = {c['name']: c['type'] for c in t['columns']}
            text, types = sql.insert_sql(physical[t['name']]['name'], columns, kinds)
            steps.append({'id': 'load:' + t['name'], 'kind': 'insert', 'sql': text, 'types': types, 'expectRows': len(rows),
                          'rows': [sql.row_binds(columns, kinds, [canonical(kinds[c], r[c]) for c in columns]) for r in rows]})
    # The seed commit is as ambiguous as any other: a lost connection here is an unknown outcome, never "run again".
    steps.append({'id': 'commit:seed', 'kind': 'control', 'action': 'commit', 'final': True})
    queries = table_queries(p, names)
    if p['operation'] == 'report':
        # External rows and the report are read in ONE query-only SERIALIZABLE transaction: Oracle gives it a
        # transaction-level snapshot, so both see the same committed state even while another session writes. (Oracle's
        # READ ONLY mode is not used: observed natively, it fails with ORA-01466 straight after DDL.) The adaptor itself
        # guarantees that nothing after the seed commit writes; query_only() below checks it.
        steps.append({'id': 'snapshot', 'kind': 'control', 'action': 'serializable'})
        steps += [{'id': 'external:' + t['name'], 'kind': 'query', **queries[t['name']]} for t in p['tables'] if t['external']]
        text, binds, columns = sql.report_sql(q['report'])
        steps.append({'id': 'report', 'kind': 'query', 'sql': text, 'binds': binds, 'columns': columns, 'maxRows': model.MAX_RESULT_ROWS})
        steps.append({'id': 'snapshot:end', 'kind': 'control', 'action': 'commit'})
        query_only(steps[steps.index(next(s for s in steps if s['id'] == 'snapshot')):])
    elif p['operation'] == 'mutate':
        steps.append({'id': 'before', 'kind': 'observe', 'queries': queries})
        steps += mutation_steps(p, names)
        steps += [{'id': 'view:' + n, 'kind': 'query', **spec} for n, spec in queries.items()]
        steps.append({'id': 'during', 'kind': 'observe', 'queries': queries})
        steps.append({'id': 'precommit', 'kind': 'validate', 'plan': p, 'final': True})
        steps.append({'id': 'finish', 'kind': 'control', 'action': p['transaction']['finish'] == 'commit' and 'commit' or 'rollback', 'final': True})
        steps.append({'id': 'after', 'kind': 'observe', 'queries': queries})
    return {'steps': steps, 'resolve': queries}


# --- faults ------------------------------------------------------------------------
def mapped_fault(directory, stage, error, extra=None):
    path = Path(directory) / (stage + '-fault.json')
    if not path.is_file():
        raise error
    record = read(directory, stage + '-fault.json')
    try:
        code, message, details = record['code'], record['message'], record.get('details', {})
        if code not in NATIVE_CODES or not isinstance(message, str) or not isinstance(details, dict):
            raise ValueError('unknown refusal')
    except (KeyError, ValueError, TypeError) as invalid:
        fail('VERIFICATION_FAILED', 'native refusal record is malformed: ' + str(invalid), stage)
    observed = {**details, **(extra or {}), 'stage': stage}
    problem(code, message, '$', RECOVERY.get(code), **observed)


def predicted_fault(error, step_plan=None):
    code = {'constraint': 'ORACLE_CONSTRAINT_VIOLATION', 'rowcount': 'ORACLE_ROWCOUNT_MISMATCH', 'arithmetic': 'ORACLE_ARITHMETIC_ERROR', 'size': 'ORACLE_RESULT_TOO_LARGE',
            'value': 'ORACLE_VALUE_NOT_STORABLE'}[error.kind]
    problem(code, str(error) + ' (predicted by the host reference before the database was touched)', '$', RECOVERY[code], predicted=True, databaseTouched=False, **error.where)


def reference_report(p, data):
    try:
        return reference.run_report(p['report'], data)
    except reference.Predicted as error:
        predicted_fault(error)
    except reference.Ambiguous as error:
        problem('ORACLE_AMBIGUOUS_ORDER', str(error), '$.report', 'order by a unique key, or add one as the last orderBy term')
    except reference.Unverifiable as error:
        problem('ORACLE_UNVERIFIABLE_VALUE', str(error), '$.report', 'use ASCII text for case conversion, or whole-day offsets; the host cannot verify this value independently')


def reference_transaction(p, data):
    try:
        return reference.simulate(p, data), None
    except reference.Predicted as error:
        # Silent scale or fractional-second loss is not an Oracle error, so the database cannot be asked to refuse it:
        # the host refuses it under either enforcement mode, before the database is touched.
        host_only = error.kind == 'value' and error.where.get('reason') in ('scale', 'loss')
        if p['transaction']['enforcement'] == 'predict' or host_only:
            predicted_fault(error)
        return None, {'kind': error.kind, 'step': error.where.get('step'), 'errors': list(error.errors), 'constraint': error.where.get('constraint'), 'reason': error.where.get('reason')}
    except reference.Unverifiable as error:
        problem('ORACLE_UNVERIFIABLE_VALUE', str(error), '$.transaction', 'the host cannot verify this value independently')


# --- verification of native results -----------------------------------------------------
def canonical_rows(table, spec):
    return reference.table_rows_canonical(table, reference.table_rows_native(table, spec['rows']))


def mismatch(message, location='$', **observed):
    fail('VERIFICATION_FAILED', message, location, **observed)


def first_difference(want, have):
    for i, (a, b) in enumerate(zip(want, have)):
        if a != b:
            return {'row': i, 'expected': a, 'native': b}
    return {'rows': {'expected': len(want), 'native': len(have)}}


def table_state(p, readback):
    state = {}
    for table in p['tables']:
        spec = readback['tables'].get(table['name'])
        if spec is None or spec.get('missing'):
            mismatch('a declared table is absent from the fresh-connection readback', table['name'])
        state[table['name']] = spec
    return state


def compare_state(p, expected, observed, label, include_external=False):
    for table in p['tables']:
        if table['external'] and not include_external:
            continue
        want = reference.table_rows_canonical(table, expected[table['name']])
        have = canonical_rows(table, observed[table['name']])
        if want != have:
            mismatch(f'{label}: native rows differ from the independent reference', table['name'], **first_difference(want, have))


def csv_text(columns, rows):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, lineterminator='\n')
    writer.writerow([c['name'] for c in columns])
    for row in rows:
        if NULL_TOKEN in row:
            problem('ORACLE_AMBIGUOUS_CSV', 'a text value equals the reserved CSV null token \\N and cannot be told from NULL', '$', 'use report.json, or transform the value in the report')
        writer.writerow([NULL_TOKEN if v is None else ('true' if v is True else 'false' if v is False else v) for v in row])
    return stream.getvalue().encode()


def exact_float(value):
    """The double equal to ``value`` exactly (binary expansion included), or None. 0.1 has no such double."""
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if number == number and abs(number) != float('inf') and Decimal(number) == value else None


def json_cell(kind, value, mode, location):
    cell = canonical(kind, value)
    if mode == 'jsonNumber' and kind == 'number' and value is not None:
        if value == value.to_integral_value() and value.copy_abs() < 2 ** 53:
            return int(value)
        exact = exact_float(value)
        if exact is None:
            problem('ORACLE_LOSSY_NUMBER', 'a NUMBER value is not exactly representable as a JSON double', location, 'use numbers: decimalString, or round the value in the report', value=cell)
        return exact
    return cell


def analyse(directory, p, data):
    """Compare retained native results with the independent reference and render every publication."""
    identify = read(directory, 'identify.json')
    readback = read(directory, 'readback.json')
    schema_name = identify['session']['schema']
    operation = p['operation']
    kinds = p['inspection']['kinds'] if operation == 'inspect' else model.KINDS
    names = physical_names(p, read(directory, 'native-config.json').get('runId'))
    inverse = {physical: logical for logical, physical in names.items()}
    first = reference.snapshot(identify['catalog'], schema_name, kinds)
    # Scratch tables carry run-unique physical names; declarations and drift are expressed in the declared (logical) names.
    after = reference.relabel(reference.snapshot(readback['catalog'], schema_name, kinds), inverse)
    files, refusal = {}, None
    if operation == 'inspect':
        if first != after:
            mismatch('two fresh connections observed different dictionary snapshots; the schema changed during inspection')
        found = reference.drift(p['tables'], after) if p['tables'] else []
        files['snapshot.json'] = dumps({'version': 'schemaxis.oracle.snapshot/1', 'digest': hashlib.sha256(json.dumps(after, sort_keys=True).encode()).hexdigest(),
                                        'snapshot': after, 'declared': [t['name'] for t in p['tables']], 'drift': found})
        if found and p['inspection']['drift'] == 'fail':
            refusal = ('ORACLE_DRIFT', 'the database differs from the declared tables', {'drift': found})
        return files, refusal
    found = reference.drift(p['tables'], after)
    if found:
        mismatch('the native table definitions differ from the declarations', '$.tables', drift=found)
    observed = table_state(p, readback)
    full = dict(data)
    if operation == 'report':
        # External rows come from the same read-only transaction as the report, not from the later readback.
        outputs = read(directory, 'apply.json')['outputs']
        for table in p['tables']:
            if table['external']:
                full[table['name']] = reference.table_rows_native(table, outputs['external:' + table['name']]['rows'])
    made = created_tables(directory)
    wanted = [n for n in p['order'] if not next(t for t in p['tables'] if t['name'] == n)['external']]
    if sorted(made) != sorted(wanted):
        mismatch('the tables the worker reports creating differ from the declared tables', '$.tables', created=made, declared=wanted)
    if not p['setup']['retain']:
        # The records must name exactly this run's own PHYSICAL tables, in reverse creation order: neither a missing,
        # reordered, foreign nor logical-name record may be accepted as a successful cleanup.
        expected = [names.get(n, n).upper() for n in reversed(wanted)]
        observed_cleanup = readback['cleanup']
        if [c.get('table') for c in observed_cleanup] != expected:
            mismatch('the cleanup records do not name this run\'s own scratch tables in reverse creation order', '$.setup.retain',
                     expected=expected, observed=[c.get('table') for c in observed_cleanup])
        pending = [c for c in observed_cleanup if c.get('dropped') is not True or c.get('reason') != 'dropped']
        if pending:
            problem('ORACLE_CLEANUP_INCOMPLETE', 'tables created by this run could not be dropped', '$.setup.retain', 'drop the listed tables manually, then rerun', tables=[c.get('table') for c in pending])
    elif readback['cleanup']:
        mismatch('a retained run must not drop anything', '$.setup.retain', observed=[c.get('table') for c in readback['cleanup']])
    if operation == 'mutate':
        apply = read(directory, 'apply.json')
        outputs = apply['outputs']
        expected_steps = read(directory, 'program-apply.json')['steps']
        if [(e.get('id'), e.get('kind')) for e in apply['steps']] != [(e['id'], e['kind']) for e in expected_steps]:
            mismatch('native transaction step order or membership differs from the trusted program', '$.transaction')
        boundary = outputs.get('effect-boundary', {})
        expected_boundary = next(e['queries'] for e in expected_steps if e['kind'] == 'boundary')
        if set(boundary) != set(expected_boundary) or any(v.get('rows') != [] for v in boundary.values()):
            mismatch('native mutation boundary observations are missing or contain undeclared effects', '$.transaction')
        if any(e.get('validated') is not True for e in apply['steps'] if e['kind'] in ('boundary', 'validate')):
            mismatch('native transaction validation records are incomplete', '$.transaction')
        # Existing tables start from the base rows read inside the transaction's own snapshot; created tables from the captured sources.
        base = dict(data)
        for table in p['tables']:
            if table['external']:
                base[table['name']] = reference.table_rows_native(table, outputs['base:' + table['name']]['rows'])
        results_final, _ = reference_transaction(p, base)
        if results_final is None:
            mismatch('the database accepted a transaction that the independent reference predicts it must refuse', '$.transaction')
        results, final = results_final
        expected = final if p['transaction']['finish'] == 'commit' else base
        note = ' (a concurrent writer to an existing table is the usual cause)' if any(t['external'] for t in p['tables']) else ''
        for label, want in (('before', base), ('during', base), ('after', expected)):
            compare_state(p, want, outputs[label], 'observer ' + label + note, include_external=True)
        compare_state(p, final, {t['name']: outputs['view:' + t['name']] for t in p['tables']}, 'transaction view', include_external=True)
        compare_state(p, expected, observed, 'fresh readback' + note, include_external=True)
        entries = {e['id']: e for e in apply['steps']}
        for i, result in enumerate(results):
            entry = entries.get(f'step:{i}')
            if entry is None or ('rows' in result and entry.get('rows') != result['rows']):
                mismatch('a transaction step affected a different number of rows from the reference', f'$.transaction.steps[{i}]', expected=result.get('rows'), native=None if entry is None else entry.get('rows'))
        committed = p['transaction']['finish'] == 'commit'
        files['transaction.json'] = dumps({'version': 'schemaxis.oracle.transaction/1', 'outcome': 'committed' if committed else 'rolledBack', 'finish': p['transaction']['finish'],
                                           'isolation': p['transaction']['isolation'], 'enforcement': p['transaction']['enforcement'],
                                           'existingTables': [t['name'] for t in p['tables'] if t['external']], 'idempotency': p['transaction']['idempotency'],
                                           'steps': [{'index': i, **r} for i, r in enumerate(results)], 'visibleToOtherSessionsBeforeFinish': False,
                                           'boundaries': [e['id'] for e in apply['steps'] if e.get('committed')] + ['commit:seed']})
        files['state-after.json'] = dumps({'version': 'schemaxis.oracle.state/1', 'tables': {t['name']: {'columns': [{'name': c['name'], 'type': c['type']} for c in t['columns']],
                                           'rows': reference.table_rows_canonical(t, expected[t['name']])} for t in p['tables']}})
        return files, None
    compare_state(p, data, observed, 'fresh readback')
    if operation == 'load':
        created = [t for t in p['tables'] if not t['external']]
        files['load-summary.json'] = dumps({'version': 'schemaxis.oracle.load/1', 'retained': p['setup']['retain'],
                                            'tables': [{'name': t['name'], 'created': not t['external'], 'rows': len(observed[t['name']]['rows']),
                                                        'columns': [{'name': c['name'], 'type': c['type']} for c in t['columns']]} for t in p['tables']],
                                            'boundaries': 'CREATE TABLE and COMMENT statements commit implicitly in Oracle; rows were committed once after loading'})
        for t in created:
            files[f'table-{t["name"]}.csv'] = csv_text(t['columns'], reference.table_rows_canonical(t, data[t['name']]))
        return files, None
    apply = read(directory, 'apply.json')
    native = apply['outputs']['report']
    names = [o['name'] for o in p['report']['outputs']]
    kinds = [o['kind'] for o in p['report']['outputs']]
    if native['columns'] != names:
        mismatch('the native result columns differ from the declared outputs', '$.report', expected=names, native=native['columns'])
    # Computed NUMBER results may carry more digits than a stored NUMBER(38): decode them under the result policy.
    rows = [[model.from_native(k, v, result=True) for k, v in zip(kinds, r)] for r in native['rows']]
    disorder = reference.check_native_order(p['report'], rows, kinds)
    if disorder:
        mismatch('the native result does not follow the declared order: ' + disorder, '$.report.orderBy')
    expected_rows, _ = reference_report(p, full)
    difference = reference.compare_result(p['report'], rows, expected_rows, kinds)
    if difference:
        mismatch('the native report differs from the independent relational reference: ' + difference, '$.report')
    settled = reference.settle_rows(p['report'], rows, kinds)
    columns = [{'name': o['name'], 'type': o['kind']} for o in p['report']['outputs']]
    mode = p['report']['numbers']
    files['report.json'] = dumps({'version': 'schemaxis.oracle.result/1', 'columns': columns, 'numbers': mode, 'rowCount': len(settled),
                                  'rows': [[json_cell(k, v, mode, '$.report.numbers') for k, v in zip(kinds, r)] for r in settled]})
    files['report.csv'] = csv_text(columns, [[canonical(k, v) for k, v in zip(kinds, r)] for r in settled])
    return files, None


def publications(p):
    operation = p['operation']
    if operation == 'inspect':
        return [('snapshot.json', 'text')]
    if operation == 'load':
        return [('load-summary.json', 'text')] + [(f'table-{t["name"]}.csv', 'file') for t in p['tables'] if not t['external']]
    if operation == 'report':
        return [('report.json', 'text'), ('report.csv', 'file')]
    return [('transaction.json', 'text'), ('state-after.json', 'text')]


def evidence_names(p):
    names = {'authored.json', 'plan.json', 'captures.json', 'native-worker.py', 'native-config.json', 'implementation.json'}
    for stage in stages(p):
        names |= {f'program-{stage}.json', stage + '.json', stage + '-submission.json', stage + '.stdout', stage + '.stderr'}
    names |= {f'source-{t["name"]}.{t["source"]["format"]}' for t in p['tables'] if t['source'] and not t['external']}
    if p['operation'] == 'mutate':
        names.add('prediction.json')
    return names


def runtime(identify):
    return f'python-oracledb {identify["driver"]["version"]} (thin) / Oracle Database {identify["server"]["version"]}'


def gates(p, identify):
    major = identify['server'].get('major')
    driver = identify['driver']
    if not driver.get('thin') or str(driver['version']).split('.')[0] in ('0', '1') or not str(driver['version'])[:1].isdigit():
        problem('UNSUPPORTED_NATIVE_VERSION', 'this adaptor needs python-oracledb 2 or later in Thin mode', '$', 'install a current python-oracledb in the interpreter passed with --oracle', driver=driver)
    if identify['session']['characterSet'] != 'AL32UTF8':
        problem('ORACLE_UNSUPPORTED_CHARSET', 'the database character set is not AL32UTF8, so Unicode text cannot be stored exactly', '$', 'use a database created with the AL32UTF8 character set', characterSet=identify['session']['characterSet'])
    if any(c['type'] == 'json' for t in p['tables'] for c in t['columns']) and (major is None or major < 21):
        problem('UNSUPPORTED_NATIVE_VERSION', 'native JSON columns require Oracle Database 21 or later', '$.tables', 'use a current server', server=identify['server']['version'])
    if p['operation'] == 'report' and any(d['function'] == 'jsonBoolean' for select in p['report']['selects'] for d in select['computed']) and (major is None or major < 23):
        problem('UNSUPPORTED_NATIVE_VERSION', 'JSON BOOLEAN extraction requires Oracle Database 23 or later', '$.report', 'use a current server', server=identify['server']['version'])
    if any(c['type'] == 'boolean' for t in p['tables'] for c in t['columns']) and (major is None or major < 23):
        problem('UNSUPPORTED_NATIVE_VERSION', 'BOOLEAN columns need Oracle Database 23 or later', '$.tables', 'use a 23 or later server, or choose another column type', server=identify['server']['version'])


def existing_objects(p, snapshot, names=None):
    """Refuse before any change when a created table's (physical) name is taken, or an external table is missing or drifted."""
    names = names or {}
    present = {t['name']: t for t in snapshot['tables']}
    for i, table in enumerate(p['tables']):
        at = f'$.tables[{i}]'
        if table['external']:
            if table['name'] not in present:
                problem('ORACLE_OBJECT_MISSING', 'an external table does not exist in the connected schema', at, RECOVERY['ORACLE_OBJECT_MISSING'], table=table['name'])
            found = reference.drift([{**table, 'external': False} if p['operation'] == 'mutate' else table], snapshot)
            if found:
                problem('ORACLE_DRIFT', 'an external table differs from its declaration', at, 'correct the declaration, or run inspect to see the actual definition', drift=found)
        elif names.get(table['name'], table['name']) in present:
            # Never replace or drop: a name that is taken is refused before any change.
            problem('ORACLE_OBJECT_EXISTS', 'a table with this name already exists', at + '.name', RECOVERY['ORACLE_OBJECT_EXISTS'], table=table['name'])


SECRET_MINIMUM = 8


def secret_forms(value):
    """Byte forms under which a secret could be written: UTF-8/16, JSON and Python escapes, percent-encoding, base64."""
    forms = {value.encode('utf-8'), value.encode('utf-16-le'), value.encode('utf-16-be'), value.encode('unicode_escape'),
             urllib.parse.quote(value, safe='').encode(), base64.b64encode(value.encode('utf-8')), base64.urlsafe_b64encode(value.encode('utf-8'))}
    for ascii_only in (True, False):
        forms.add(json.dumps(value, ensure_ascii=ascii_only)[1:-1].encode('utf-8'))
    return {f for f in forms if f}


def secret_values(p):
    return [v for v in (os.environ.get(p['connection'][k]) for k in ('passwordVariable', 'dsnVariable')) if v]


def require_scannable_secrets(p):
    """Before any native side effect: a password or connect string too short to scan for cannot be proven absent from evidence."""
    for value in secret_values(p):
        if len(value) < SECRET_MINIMUM:
            problem('ORACLE_CREDENTIAL_UNSCANNABLE', f'the password and connect string must be at least {SECRET_MINIMUM} characters so that evidence can be scanned for them',
                    '$.connection', 'use a longer credential for this profile; the run was refused before any database work')


FAULT_VOCABULARY = frozenset(NATIVE_CODES | set(RECOVERY) | {
    'INVALID_ORACLE_CONNECTION', 'INVALID_ARGUMENT', 'VERIFICATION_FAILED',
    'INCOMPLETE_EXECUTION', 'NATIVE_EXECUTION_FAILED', 'RUNNER_CANCELLED', 'RUNNER_TIMED_OUT',
    'ORACLE_CREDENTIAL_UNSCANNABLE', 'ORACLE_CREDENTIAL_LEAK',
    'code', 'message', 'location', 'phase', 'retryable', 'observed', 'recovery',
    'databaseTouched', 'databaseWorkCompleted', 'outcome', 'outcomeUnknown',
    'rolledBack', 'rollbackVerified', 'sessionRollbackCompleted', 'createdTables',
    'tablesRetained', 'cleanupVerified', 'statusWriteFailed', 'statusWriteError',
    'priorFaultCode', 'resolution', 'files', 'status', 'verified', 'reason', 'pipeline', 'constraint',
    'seedCommitCompleted', 'nativeApplyCompleted',
    'committed', 'rolledBack', 'seed rows committed',
    'seed rows committed; report incomplete', 'read-only report incomplete',
    'read-only inspection completed', 'read-only report completed',
    'commit-outcome-unknown', 'unknown', 'seed', 'final', 'unexpected', 'base-state-unknown',
    'succeeded', 'failed', 'incomplete', 'running', 'commit', 'rollback'})


def require_noncolliding_credentials(p):
    """Reject publicly reserved protocol tokens before any run files or native work.

    A value equal to a required JSON key cannot be hidden in a structured fault
    containing that public key. This is a configuration refusal, never a licence
    to rename stable fault codes/keys or waive scanning after database work.
    """
    values = secret_values(p)
    forms = {form for value in values for form in secret_forms(value)}
    if not any(form in token.encode('utf-8') for form in forms for token in FAULT_VOCABULARY):
        return
    from schemaxis.core.faults import Fault
    codes = ('INVALID_ORACLE_CONNECTION', 'ORACLE_CREDENTIAL_UNSCANNABLE',
             'VERIFICATION_FAILED', 'NATIVE_EXECUTION_FAILED', 'INVALID_ARGUMENT')
    code = next((code for code in codes if not any(form in code.encode('utf-8') for form in forms)), codes[0])
    raise SchemaxisError(Fault(code, 'Profile refused: credential collides with public protocol vocabulary.',
                              '$', 'input', observed={'reason': 'credential-protocol-collision', 'databaseTouched': False},
                              recovery='Choose unrelated credentials before running.'))


def scan_secrets(directory, p):
    """Refuse and blank any retained file that contains the password or connect string in any scanned form.

    The user name is session identity (CURRENT_SCHEMA is normally the user), which the evidence records
    legitimately, so it is not scanned. A real leak blanks the file and fails the run.
    """
    forms = set()
    for value in secret_values(p):
        forms |= secret_forms(value)
    if not forms:
        return
    leaked = []
    for path in sorted(Path(directory).rglob('*')):
        if not path.is_file() or path.is_symlink():
            continue
        if any(f in path.read_bytes() for f in forms):
            path.write_bytes(b'')
            leaked.append(len(leaked) + 1)
    if leaked:
        problem('ORACLE_CREDENTIAL_LEAK', 'retained files contained a credential and were blanked', '$',
                'report this defect and rotate the exposed credential; database work that had completed before this check is not rolled back',
                files=leaked)


def finish(directory, p, payload):
    """Write the final status file and scan once more, so that no byte written by this run escapes the credential scan."""
    atomic_json(Path(directory) / 'result.json', payload)
    scan_secrets(directory, p)


# --- execution --------------------------------------------------------------------------
def run_stage(executable, directory, stage, deadline, program):
    atomic_json(Path(directory) / f'program-{stage}.json', program)
    try:
        execute(command(executable, stage), directory, stage, deadline - time.monotonic(), {'PYTHONDONTWRITEBYTECODE': '1'})
    except SchemaxisError as error:
        if error.fault.code != 'RUNNER_FAILED':
            raise
        mapped_fault(directory, stage, error)


def run(document, directory, *, executable=None, timeout=300):
    p = plan(document)
    require_noncolliding_credentials(p)
    executable = executable or os.environ.get('SCHEMAXIS_ORACLE')
    if not executable or not Path(executable).is_absolute() or not os.access(executable, os.X_OK):
        fail('INTERPRETER_NOT_FOUND', 'configure an absolute dedicated Python interpreter that has python-oracledb installed (--oracle)')
    if os.name != 'posix':
        fail('UNSUPPORTED_PLATFORM', 'the Oracle worker needs a POSIX host')
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
    completion = None
    try:
        require_scannable_secrets(p)
        captures, data = capture(directory, p)
        atomic_json(directory / 'captures.json', captures)
        check_initial(p, data)
        has_external = any(t['external'] for t in p['tables'])
        prediction = None
        if p['operation'] == 'report' and not has_external:
            reference_report(p, data)
        if p['operation'] == 'mutate':
            if not has_external:                      # existing tables: their rows are unknown until the in-transaction base read
                _, prediction = reference_transaction(p, data)
            atomic_json(directory / 'prediction.json', {'predictedFailure': prediction})
        (directory / 'native-worker.py').write_text(worker_source())
        run_id = secrets.token_hex(8)
        atomic_json(directory / 'native-config.json', {'connection': p['connection'], 'runId': run_id})
        atomic_json(directory / 'implementation.json', implementation())
        run_stage(executable, directory, 'identify', deadline, identify_program(p, run_id))
        identify = read(directory, 'identify.json')
        gates(p, identify)
        snapshot = reference.snapshot(identify['catalog'], identify['session']['schema'])
        if p['operation'] != 'inspect':
            existing_objects(p, snapshot, physical_names(p, run_id))
        failure = None
        if p['operation'] != 'inspect':
            try:
                run_stage(executable, directory, 'apply', deadline, apply_program(p, data, run_id))
                completion = completed_context(p)
            except SchemaxisError as error:
                failure = error
        # An unknown commit, a timeout or a cancellation keeps every table: dropping them would destroy the only
        # evidence of what the interrupted work did.
        if failure is not None and completion is None:
            completion = completed_from_partial(directory, p)
        unknown = failure is not None and (failure.fault.code == 'ORACLE_COMMIT_OUTCOME_UNKNOWN' or
                                           (failure.fault.code in UNKNOWN_OUTCOMES and completion is None))
        try:
            run_stage(executable, directory, 'readback', deadline, readback_program(p, created_tables(directory), keep=unknown, run_id=run_id))
            if p['operation'] == 'inspect':
                completion = completed_context(p)
            if completion is not None:
                cache_cleanup(directory, p, completion, run_id)
        except SchemaxisError:
            if failure is None:
                raise
        if failure is not None:
            raise annotate(failure, directory, p, data, prediction, unknown)
        files, refusal = analyse(directory, p, data)
        if completion is None and p['operation'] == 'inspect':
            completion = completed_context(p)
        completion['cleanupVerified'] = True
        completion['tablesRetained'] = bool(p.get('setup', {}).get('retain', False))
        for name, content in files.items():
            (directory / name).write_bytes(content)
        if refusal is not None:
            problem(refusal[0], refusal[1], '$.tables', 'run inspect without declared tables to see the actual schema', **refusal[2])
        atomic_json(directory / 'verification.json', {
            'artifacts': [{'file': str(directory / name), 'kind': kind, 'sha256': digest(directory, name)} for name, kind in publications(p)],
            'evidence': {name: digest(directory, name) for name in sorted(evidence_names(p))}, 'executable': str(executable), 'runtime': runtime(identify)})
        scan_secrets(directory, p)
        result = verify(directory, require_result=False)
        if cancellation_requested():
            fail('RUNNER_CANCELLED', 'Oracle publication cancelled')
        if time.monotonic() >= deadline:
            fail('RUNNER_TIMED_OUT', 'Oracle exhausted its total deadline')
        result['status'] = 'succeeded'
        finish(directory, p, result)
        return result
    except Exception as error:
        if not isinstance(error, SchemaxisError):
            try:
                fail('NATIVE_EXECUTION_FAILED', 'unexpected host failure: ' + type(error).__name__)
            except SchemaxisError as wrapped:
                error = wrapped
        completion = completion or completed_from_partial(directory, p)
        if completion is not None:
            error = annotate_completed(error, directory, p, completion)
        error = redact_fault(error, p)
        # At most two attempts: a scan refusal replaces the original fault, and
        # its path-free, redacted payload is itself written AND scanned.
        for attempt in range(2):
            try:
                finish(directory, p, {'status': 'failed', 'verified': False, 'fault': error.fault.to_dict()})
                break
            except Exception as final_error:
                if isinstance(final_error, SchemaxisError) and final_error.fault.code == 'ORACLE_CREDENTIAL_LEAK':
                    error = combine_faults(final_error, error)
                    if completion is not None:
                        error = annotate_completed(error, directory, p, completion)
                    error = redact_fault(error, p)
                    continue
                fault = error.fault
                try:
                    problem(fault.code, fault.message, fault.location, fault.recovery,
                            **{**fault.to_dict()['observed'], 'statusWriteFailed': True, 'statusWriteError': type(final_error).__name__})
                except SchemaxisError as status_error:
                    error = redact_fault(status_error, p)
                # A failing disk/status writer must not replace the structured
                # database outcome with a raw I/O exception or retain success.
                try:
                    (directory / 'result.json').write_bytes(b'')
                except Exception:
                    pass
                break
        raise error



UNKNOWN_OUTCOMES = ('ORACLE_COMMIT_OUTCOME_UNKNOWN', 'RUNNER_TIMED_OUT', 'RUNNER_CANCELLED')
REFUSALS = {'constraint': 'ORACLE_CONSTRAINT_VIOLATION', 'value': 'ORACLE_CONSTRAINT_VIOLATION', 'rowcount': 'ORACLE_ROWCOUNT_MISMATCH', 'arithmetic': 'ORACLE_ARITHMETIC_ERROR'}


def journal_state(directory):
    """DDL and commit steps the worker began and finished, from its synced journal (also present after a killed worker)."""
    created, in_flight = [], None
    path = Path(directory) / 'apply-journal.jsonl'
    if path.is_file():
        for line in bounded(path).decode('utf-8').splitlines():
            record = json.loads(line)
            if record['event'] == 'begin':
                in_flight = record
            else:
                in_flight = None
                if record.get('creates'):
                    created.append(record['creates'])
    return created, in_flight


def observed_state(p, data, directory):
    """Classify the fresh-connection readback: the seed state, the expected final state, something else, or missing tables."""
    if not (Path(directory) / 'readback.json').is_file():
        return None
    try:
        observed = table_state(p, read(directory, 'readback.json'))
    except SchemaxisError:
        return 'missing'
    # Existing tables have no captured seed: their pre-state is the in-transaction base read, if the worker got that far.
    data = dict(data)
    recorded = {}
    for name in ('apply.json', 'apply-partial.json'):
        if (Path(directory) / name).is_file():
            recorded = read(directory, name).get('outputs', {})
            break
    include = p['operation'] == 'mutate'
    for table in p['tables']:
        if table['external'] and include:
            if 'base:' + table['name'] not in recorded:
                return 'base-state-unknown'
            data[table['name']] = reference.table_rows_native(table, recorded['base:' + table['name']]['rows'])

    def matches(expected):
        try:
            compare_state(p, expected, observed, 'state', include_external=include)
            return True
        except SchemaxisError:
            return False
    if matches(data):
        return 'seed'
    if p['operation'] == 'mutate' and p['transaction']['finish'] == 'commit':
        try:
            if matches(reference.simulate(p, data)[1]):
                return 'final'
        except (reference.Predicted, reference.Unverifiable):
            pass
    return 'unexpected'


def prediction_mismatch(fault, prediction):
    """Under enforcement 'database' Oracle must refuse at the predicted step with a predicted error, not merely refuse."""
    observed = fault.observed
    wanted = REFUSALS.get(prediction['kind'])
    number = re.fullmatch(r'ORA-0*(\d+)', str(observed.get('oracle', '')))
    if fault.code != wanted:
        return f'the host predicted {wanted} but the database reported {fault.code}'
    if observed.get('step') != f'step:{prediction["step"]}':
        return f'the host predicted a refusal at step {prediction["step"]} but the database refused at {observed.get("step")}'
    if prediction['errors'] and (number is None or int(number.group(1)) not in prediction['errors']):
        return f'the host predicted Oracle error(s) {prediction["errors"]} but the database reported {observed.get("oracle")}'
    return None


def ledger_role(p, fault):
    """The idempotency role of the transaction step a row-count refusal came from, if any."""
    step = fault.observed.get('step')
    if fault.code != 'ORACLE_ROWCOUNT_MISMATCH' or p['operation'] != 'mutate' or not isinstance(step, str) or not step.startswith('step:') or not p['transaction'].get('idempotency'):
        return None
    index = int(step[5:])
    steps = p['transaction']['steps']
    role = steps[index].get('role') if index < len(steps) else None
    return role if role in ('ledger:conflict', 'ledger:applied') else None


def annotate(error, directory, p, data, prediction, unknown=False):
    """Attach independently observed state to a native failure: what was created or is in flight, whether the work
    landed or was rolled back, what cleanup did, and (for enforcement 'database') whether Oracle refused as predicted."""
    created = created_tables(directory)
    _, in_flight = journal_state(directory)
    extra = {'createdTables': created, 'tablesRetained': bool(p['setup']['retain']) or unknown}
    partial = Path(directory) / 'apply-partial.json'
    attempted = read(directory, 'apply-partial.json').get('attempted') if partial.is_file() else None
    if in_flight and in_flight.get('creates'):
        attempted = attempted or in_flight['creates']
    if attempted:
        # A CREATE interrupted in flight may or may not have taken effect; ownership cannot be proven, so it is reported, never dropped.
        extra['possiblyCreated'] = attempted
    if in_flight and in_flight.get('kind') == 'control':
        extra['inFlight'] = in_flight['id']
        unknown = True
    if unknown:
        extra['outcomeUnknown'] = True
        extra['cleanupSkipped'] = 'the outcome is unknown, so created tables were kept as evidence; inspect them before any rerun'
    cleanup = read(directory, 'readback.json').get('cleanup') if (Path(directory) / 'readback.json').is_file() else None
    if cleanup is not None:
        extra['cleanup'] = cleanup
    state = observed_state(p, data, directory)
    if state is not None:
        extra['observedState'] = state
        if p['operation'] == 'mutate':
            extra['rollbackVerified'] = state == 'seed'
            extra['commitLanded'] = state == 'final'
    role = ledger_role(p, error.fault)
    if role:
        applied = role == 'ledger:applied'
        code = 'ORACLE_ALREADY_APPLIED' if applied else 'ORACLE_IDEMPOTENCY_CONFLICT'
        message = ('this change was already applied under its idempotency key; nothing was changed' if applied else
                   'the idempotency key is recorded with a different change; nothing was changed')
        try:
            problem(code, message, '$.transaction.idempotency', RECOVERY[code], key=p['transaction']['idempotency']['key'], **{**dict(error.fault.observed), **extra})
        except SchemaxisError as ledger_error:
            return ledger_error
    if prediction is not None:
        extra['predictedFailure'] = prediction
        if p['transaction']['enforcement'] == 'database' and error.fault.code in REFUSALS.values():
            difference = prediction_mismatch(error.fault, prediction)
            if difference:
                try:
                    problem('VERIFICATION_FAILED', 'the database did not refuse as the independent reference predicted: ' + difference, '$.transaction', predicted=prediction,
                            native={k: error.fault.observed.get(k) for k in ('oracle', 'step', 'constraint')}, **{k: v for k, v in extra.items() if k != 'predictedFailure'})
                except SchemaxisError as mismatched:
                    return mismatched
    fault = error.fault
    try:
        problem(fault.code, fault.message, fault.location, fault.recovery, **{**dict(fault.observed), **extra})
    except SchemaxisError as annotated:
        return annotated


def completed_context(p):
    """Cache durable native facts before publication or scanning can fail."""
    operation = p['operation']
    created = [n for n in p.get('order', []) if not next(t for t in p['tables'] if t['name'] == n)['external']]
    if operation == 'mutate':
        outcome = 'committed' if p['transaction']['finish'] == 'commit' else 'rolledBack'
    elif operation == 'inspect':
        outcome = 'read-only inspection completed'
    else:
        outcome = 'seed rows committed' if created else 'read-only report completed'
    return {'databaseWorkCompleted': True, 'databaseTouched': True, 'createdTables': created,
            'tablesRetained': True if p.get('setup', {}).get('retain') else None,
            'cleanupVerified': False, 'outcome': outcome}


def cache_cleanup(directory, p, completion, run_id):
    """Cache only explicit, correctly bound successful cleanup observations."""
    records = read(directory, 'readback.json').get('cleanup', [])
    retain = bool(p.get('setup', {}).get('retain', False))
    names = physical_names(p, run_id)
    expected = [] if retain else [names.get(n, n).upper() for n in reversed(completion['createdTables'])]
    if [r.get('table') for r in records] == expected and all(r.get('dropped') is True and r.get('reason') == 'dropped' for r in records):
        completion.update(cleanupVerified=True, tablesRetained=retain)


def combine_faults(current, prior):
    """A credential refusal must retain the prior durable/unknown database state."""
    fault = current.fault
    observed = {**prior.fault.to_dict()['observed'], **fault.to_dict()['observed'], 'priorFaultCode': prior.fault.code}
    recovery = '; '.join(v for v in (prior.fault.recovery, fault.recovery) if v)
    try:
        problem(fault.code, fault.message, fault.location, recovery, **observed)
    except SchemaxisError as combined:
        return combined


def completed_from_partial(directory, p):
    """Recover acknowledged mutation finishes and load/report seed commits."""
    try:
        completed = set()
        for name in ('apply.json', 'apply-partial.json'):
            record = read(directory, name) if (Path(directory) / name).is_file() else {}
            completed.update(step.get('id') for step in record.get('steps', []) if step.get('kind') == 'control')
        journal = Path(directory) / 'apply-journal.jsonl'
        if journal.is_file():
            for line in bounded(journal).decode('utf-8').splitlines():
                record = json.loads(line)
                if record.get('event') == 'done' and record.get('kind') == 'control':
                    if record.get('id') == 'commit:seed' and record.get('action') == 'commit':
                        completed.add('commit:seed')
                    if p['operation'] == 'mutate' and record.get('id') == 'finish' and record.get('action') == p['transaction']['finish']:
                        completed.add('finish')
        if p['operation'] == 'mutate' and 'finish' in completed:
            return completed_context(p)
        if p['operation'] in ('load', 'report') and 'commit:seed' in completed:
            facts = completed_context(p)
            facts['seedCommitCompleted'] = True
            facts['nativeApplyCompleted'] = False
            if p['operation'] == 'report':
                facts['databaseWorkCompleted'] = False
                facts['outcome'] = 'seed rows committed; report incomplete' if facts['createdTables'] else 'read-only report incomplete'
            return facts
    except Exception:
        pass  # Missing/malformed evidence must never turn an unknown outcome into a known commit.
    return None


def redact_fault(error, p):
    """A returned/status fault must not echo credentials through paths or details."""
    tokens = set()
    for secret in secret_values(p):
        for form in secret_forms(secret):
            try:
                tokens.add(form.decode('utf-8'))
            except UnicodeError:
                pass
    def clean(value):
        if isinstance(value, str):
            for token in sorted(tokens, key=len, reverse=True):
                value = value.replace(token, '?')
            return value
        if isinstance(value, dict):
            # Required vocabulary is reserved before execution; arbitrary table,
            # column and diagnostic keys still need recursive credential redaction.
            return {(k if k in FAULT_VOCABULARY else clean(k)): clean(v) for k, v in value.items()}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value
    fault = error.fault.to_dict()
    try:
        problem(fault['code'], clean(fault['message']), clean(fault['location']),
                clean(fault.get('recovery')), **clean(fault['observed']))
    except SchemaxisError as redacted:
        return redacted


def annotate_completed(error, directory, p, completion=None):
    """Preserve durable native outcomes across every later host failure."""
    fault = error.fault
    facts = dict(completion or completed_context(p))
    observed = dict(fault.observed)
    # Richer unknown/observed outcomes take precedence over a planned finish.
    if fault.code == 'ORACLE_COMMIT_OUTCOME_UNKNOWN':
        observed.setdefault('outcomeUnknown', True)
        observed.setdefault('outcome', 'commit-outcome-unknown')
    if observed.get('outcomeUnknown') and 'outcome' not in observed:
        observed['outcome'] = 'unknown'
    extra = {**facts, **observed, 'databaseTouched': True}
    if not extra.get('outcomeUnknown'):
        extra['databaseWorkCompleted'] = facts['databaseWorkCompleted']
    if (extra['outcome'] == 'committed' or extra['outcome'].startswith('seed rows committed')) and observed.get('rolledBack'):
        extra['rolledBack'] = False
        extra['sessionRollbackCompleted'] = True
        if extra.get('rollbackVerified'):
            extra['rollbackVerified'] = False
    retained = ('the tables were kept' if extra.get('tablesRetained') is True else
                'scratch tables were dropped' if extra.get('cleanupVerified') and facts['createdTables'] else
                'cleanup/retention has not been verified' if not extra.get('cleanupVerified') else 'no run-created tables remain')
    progress = 'the native database work completed before this failure' if facts['databaseWorkCompleted'] else 'the seed commit completed before this failure; later report work is incomplete'
    note = f'{progress}; {retained}; recorded outcome: {extra["outcome"]}; do not rerun blindly; inspect the current tables and idempotency ledger before retrying'
    recovery = fault.recovery or ''
    if note not in recovery:
        recovery = (recovery + '; ' if recovery else '') + note
    try:
        problem(fault.code, fault.message, fault.location, recovery, **extra)
    except SchemaxisError as annotated:
        return annotated


def verify(directory, require_result=True):
    directory = Path(directory).absolute()
    try:
        p = plan(read(directory, 'authored.json'))
        if read(directory, 'plan.json') != json.loads(json.dumps(p)):
            fail('VERIFICATION_FAILED', 'effective plan differs')
        if require_result:
            status = read(directory, 'result.json')
            if status.get('status') != 'succeeded':
                recorded = status.get('fault')
                fail('INCOMPLETE_EXECUTION', 'the Oracle run did not complete; correct the cause, then run again in a fresh output directory', str(directory / 'result.json'),
                     status=status.get('status'), faultCode=recorded.get('code') if isinstance(recorded, dict) else None)
        if read(directory, 'implementation.json') != implementation():
            fail('VERIFICATION_FAILED', 'Oracle adaptor implementation changed; rerun to verify with current code')
        receipt = read(directory, 'verification.json')
        data = reload_data(directory, p)
        captures = {}
        for table in p['tables']:
            if table['source'] and not table['external']:
                name = f'source-{table["name"]}.{table["source"]["format"]}'
                raw = bounded(directory / name)
                captures[table['name']] = {'source': table['source']['path'], 'file': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
        if read(directory, 'captures.json') != captures:
            fail('VERIFICATION_FAILED', 'captured source bindings differ')
        check_initial(p, data)
        executable = receipt.get('executable')
        if not isinstance(executable, str) or not Path(executable).is_absolute():
            fail('VERIFICATION_FAILED', 'native executable identity must be absolute')
        config = read(directory, 'native-config.json')
        run_id = config.get('runId')
        if bounded(directory / 'native-worker.py').decode() != worker_source() or set(config) != {'connection', 'runId'} or config['connection'] != p['connection'] \
                or not isinstance(run_id, str) or not re.fullmatch(r'[0-9a-f]{16}', run_id):
            fail('VERIFICATION_FAILED', 'trusted worker or native configuration differs')
        for stage in stages(p):
            submission = read(directory, stage + '-submission.json')
            if submission.get('nativeCommand') != command(executable, stage) or type(submission.get('exitCode')) is not int or submission['exitCode'] != 0:
                fail('VERIFICATION_FAILED', 'native command or completion differs', stage)
        identify = read(directory, 'identify.json')
        gates(p, identify)
        if read(directory, 'program-identify.json') != json.loads(json.dumps(identify_program(p, run_id))):
            fail('VERIFICATION_FAILED', 'trusted identification program differs')
        if p['operation'] != 'inspect':
            if read(directory, 'program-apply.json') != json.loads(json.dumps(apply_program(p, data, run_id))):
                fail('VERIFICATION_FAILED', 'trusted apply program differs from the plan and captured rows')
        if read(directory, 'program-readback.json') != json.loads(json.dumps(readback_program(p, created_tables(directory), run_id=run_id))):
            fail('VERIFICATION_FAILED', 'trusted readback program differs')
        if receipt.get('runtime') != runtime(identify):
            fail('VERIFICATION_FAILED', 'native runtime identity differs')
        files, refusal = analyse(directory, p, data)
        if refusal is not None:
            problem(refusal[0], refusal[1], '$.tables', **refusal[2])
        expected = publications(p)
        if set(files) != {n for n, _ in expected}:
            fail('VERIFICATION_FAILED', 'publication membership differs')
        for name, content in files.items():
            if bounded(directory / name) != content:
                fail('VERIFICATION_FAILED', 'a publication differs from the verified native result', name)
        if not portable_artifacts(receipt.get('artifacts'), directory, p):
            fail('VERIFICATION_FAILED', 'publication membership or digests differ')
        if set(receipt.get('evidence', {})) != evidence_names(p):
            fail('VERIFICATION_FAILED', 'evidence membership differs')
        for name in evidence_names(p):
            if receipt['evidence'][name] != digest(directory, name):
                fail('VERIFICATION_FAILED', 'retained evidence differs', name)
        return {'verified': True, 'artifacts': len(receipt['artifacts']), 'runtime': runtime(identify), 'operation': p['operation']}
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeError, ArithmeticError, RecursionError) as error:
        fail('VERIFICATION_FAILED', 'invalid retained Oracle evidence: ' + str(error))


def portable_artifacts(recorded, directory, p):
    wanted = [{'kind': kind, 'sha256': digest(directory, name), 'name': name} for name, kind in publications(p)]
    if not isinstance(recorded, list) or len(recorded) != len(wanted):
        return False
    files = [item.get('file') if isinstance(item, dict) else None for item in recorded]
    if not all(isinstance(f, str) and Path(f).is_absolute() for f in files) or len({str(Path(f).parent) for f in files}) != 1:
        return False
    return all(item.get('kind') == w['kind'] and item.get('sha256') == w['sha256'] and Path(item['file']).name == w['name'] for item, w in zip(recorded, wanted))


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
