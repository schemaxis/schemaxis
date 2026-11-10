"""Native Oracle worker. Runs in its own interpreter and imports python-oracledb only here.

The host generates and hash-binds ``program.json``; this worker executes it step by step
in thin mode after a structural allow-list check, and never reads anything but the
credential variables named in ``native-config.json``. Credential values, DSNs and host
names are redacted from every error before it is written.
"""
import json
import os
import re
import sys
from decimal import Decimal

STAGES = ('identify', 'apply', 'readback')
MAX_MESSAGE = 400
NAME = re.compile(r'[A-Z][A-Z0-9_]{0,23}')
SESSION_SETTINGS = ("ALTER SESSION SET NLS_COMP = 'BINARY' NLS_SORT = 'BINARY' NLS_NUMERIC_CHARACTERS = '.,' "
                    "NLS_LANGUAGE = 'AMERICAN' NLS_TERRITORY = 'AMERICA' NLS_CALENDAR = 'GREGORIAN'")
CONSTRAINT_ERRORS = {1: 'unique', 2290: 'check', 2291: 'foreignKey', 2292: 'foreignKey', 1400: 'notNull', 1407: 'notNull', 1438: 'precision', 12899: 'length'}
FAULT_CODES = {8177: 'ORACLE_SERIALIZATION_CONFLICT', 1017: 'ORACLE_AUTHENTICATION_FAILED', 1031: 'ORACLE_PRIVILEGE_DENIED', 1950: 'ORACLE_PRIVILEGE_DENIED', 942: 'ORACLE_OBJECT_MISSING',
               955: 'ORACLE_OBJECT_EXISTS', 2449: 'ORACLE_OBJECT_IN_USE', 1476: 'ORACLE_ARITHMETIC_ERROR', 1426: 'ORACLE_ARITHMETIC_ERROR',
               12541: 'ORACLE_UNAVAILABLE', 12514: 'ORACLE_UNAVAILABLE', 12154: 'ORACLE_UNAVAILABLE', 12170: 'ORACLE_UNAVAILABLE', 3113: 'ORACLE_UNAVAILABLE',
               3114: 'ORACLE_UNAVAILABLE', 3135: 'ORACLE_UNAVAILABLE', 28000: 'ORACLE_AUTHENTICATION_FAILED', 28001: 'ORACLE_AUTHENTICATION_FAILED'}
DRIVER_CODES = {'DPY-6005': 'ORACLE_UNAVAILABLE', 'DPY-6000': 'ORACLE_UNAVAILABLE', 'DPY-4011': 'ORACLE_UNAVAILABLE', 'DPY-4024': 'ORACLE_CALL_TIMEOUT',
                'DPY-6001': 'ORACLE_UNAVAILABLE', 'DPY-6003': 'ORACLE_AUTHENTICATION_FAILED'}


class Refusal(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details


def redact(text, secrets):
    """Remove credential values, DSN fragments and connection descriptors from a message."""
    text = str(text)
    for token in secret_tokens(secrets):
        text = text.replace(token, '<redacted>')
    text = re.sub(r'\(DESCRIPTION=.*', '<redacted connection descriptor>', text)
    return text[:MAX_MESSAGE]


def secret_tokens(secrets):
    """Whole secret values plus, for a connect string, its host, host:port and service name. No arbitrary fragments:
    redaction applies to error text only and must not corrupt structured row data."""
    tokens = set()
    for secret in secrets:
        if not secret:
            continue
        tokens.add(secret)
        match = re.fullmatch(r'(?:[A-Za-z]+://)?([^/:?#@\s]+)(?::(\d+))?(?:/(\S+))?', secret)
        if match and ('/' in secret or ':' in secret):
            host, port, service = match.groups()
            tokens.update(t for t in (host, service, f'{host}:{port}' if port else None) if t and len(t) >= 4)
    return sorted(tokens, key=len, reverse=True)


def error_info(error):
    info = error.args[0] if error.args else None
    return getattr(info, 'code', None), getattr(info, 'full_code', None), str(getattr(info, 'message', None) or error)


def classify(error, secrets=()):
    """(host fault code, oracle code text, redacted message, constraint kind or None)."""
    code, full, message = error_info(error)
    oracle = full or (f'ORA-{int(code):05d}' if isinstance(code, int) else None)
    if code in CONSTRAINT_ERRORS:
        fault = 'ORACLE_CONSTRAINT_VIOLATION'
    elif full in DRIVER_CODES:
        fault = DRIVER_CODES[full]
    else:
        fault = FAULT_CODES.get(code, 'ORACLE_SERVER_ERROR')
    return fault, oracle, redact(message, secrets), CONSTRAINT_ERRORS.get(code)


QUOTED = re.compile(r"'(?:[^']|'')*'|\"[^\"]*\"")
SAFE_IDENTIFIER = re.compile(r'[A-Z_][A-Z0-9_$]*')


def stripped(sql):
    """Replace text literals by '' and quoted identifiers by "X"; refuse identifiers that are not plain upper-case names."""
    def replace(match):
        token = match.group(0)
        if token[0] == "'":
            return "''"
        if not SAFE_IDENTIFIER.fullmatch(token[1:-1]):
            raise Refusal('ORACLE_PROGRAM_REFUSED', 'a quoted identifier is not a plain upper-case name')
        return '"X"'
    return QUOTED.sub(replace, sql)


STATEMENTS = {
    'ddl': [re.compile(r'CREATE TABLE "X" \(.*\)(?: SEGMENT CREATION IMMEDIATE)?'), re.compile(r"COMMENT ON TABLE \"X\" IS ''"), re.compile(r'DROP TABLE "X" PURGE')],
    'insert': [re.compile(r'INSERT INTO "X" \(.*\) VALUES \(.*\)')],
    'dml': [re.compile(r'(UPDATE "X" SET |DELETE FROM "X"|MERGE INTO "X" ).*')],
    'query': [re.compile(r'SELECT .*')],
}


def check_statement(kind, sql):
    """Refuse anything that is not one of the generated statement shapes for its step kind."""
    if kind not in STATEMENTS or not isinstance(sql, str) or len(sql) > 200000:
        raise Refusal('ORACLE_PROGRAM_REFUSED', 'unknown step kind or statement size', kind=str(kind)[:20])
    plain = stripped(sql)
    if ';' in plain or '--' in plain or '/*' in plain or '\n' in plain:
        raise Refusal('ORACLE_PROGRAM_REFUSED', 'statement contains a terminator, comment or line break', kind=kind)
    if not any(p.fullmatch(plain) for p in STATEMENTS[kind]):
        raise Refusal('ORACLE_PROGRAM_REFUSED', 'statement does not match a generated shape for its kind', kind=kind)
    if kind == 'query' and re.search(r'\b(INTO|FOR UPDATE|DBMS_\w+|UTL_\w+)\b', plain):
        raise Refusal('ORACLE_PROGRAM_REFUSED', 'queries cannot select into variables, lock rows or call packages', kind=kind)


def convert_bind(kind, value):
    if value is None:
        return None
    if kind == 'number':
        return Decimal(value)
    if kind == 'boolean':
        return bool(value)
    if kind == 'blob':
        return bytes.fromhex(value)
    return str(value)


STRUCTURED = ('resolution', 'partial')


def scrub(value, secrets):
    """Redact error-text fields only; keys that carry observed table rows are structured data and are left intact."""
    if isinstance(value, str):
        return redact(value, secrets)
    if isinstance(value, dict):
        return {k: (v if k in STRUCTURED else scrub(v, secrets)) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v, secrets) for v in value]
    return value


def encode_cell(kind, value):
    if value is None:
        return None
    if hasattr(value, 'read') and hasattr(value, 'size'):
        if value.size() > 262144:
            raise Refusal('ORACLE_RESULT_TOO_LARGE', 'a LOB cell exceeds 262144 characters or bytes')
        value = value.read()
    if isinstance(value, Decimal) or kind == 'number':
        return format(value if isinstance(value, Decimal) else Decimal(str(value)), 'f')
    if kind == 'boolean':
        return bool(value)
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).hex()
    return str(value)


def environment(config):
    values = {}
    for key in ('userVariable', 'passwordVariable', 'dsnVariable'):
        name = config['connection'][key]
        value = os.environ.get(name)
        if not value:
            raise Refusal('ORACLE_CREDENTIALS_MISSING', f'the host environment variable {name} is not set', variable=name)
        values[key] = value
    return values


class Session:
    def __init__(self, driver, config):
        self.driver, self.config, self.values = driver, config, environment(config)
        self.secrets = list(self.values.values())
        self.connection = None

    def connect(self):
        d = self.driver
        try:
            connection = d.connect(user=self.values['userVariable'], password=self.values['passwordVariable'], dsn=self.values['dsnVariable'],
                                   tcp_connect_timeout=float(self.config['connection']['connectTimeout']))
        except d.Error as error:
            code, oracle, message, _ = classify(error, self.secrets)
            raise Refusal(code, message, oracle=oracle)
        if not getattr(connection, 'thin', True):
            connection.close()
            raise Refusal('ORACLE_UNSUPPORTED_MODE', 'this adaptor is qualified for python-oracledb Thin mode only; a Thick connection was refused')
        connection.call_timeout = int(self.config['connection']['callTimeout']) * 1000
        connection.outputtypehandler = self.number_handler
        cursor = connection.cursor()
        cursor.execute(SESSION_SETTINGS)
        cursor.close()
        self.connection = connection
        return connection

    def number_handler(self, cursor, metadata):
        if metadata.type_code is self.driver.DB_TYPE_NUMBER:
            return cursor.var(self.driver.DB_TYPE_VARCHAR, 80, cursor.arraysize, outconverter=Decimal)
        return None

    def close(self):
        if self.connection is not None:
            try:
                self.connection.close()
            except Exception:
                pass
            self.connection = None


def sizes(driver, kinds):
    return [({'number': driver.DB_TYPE_NUMBER, 'boolean': driver.DB_TYPE_BOOLEAN}.get(k, 4000) if k not in ('clob', 'blob') else getattr(driver, 'DB_TYPE_' + k.upper())) for k in kinds]


def run_query(session, cursor, spec, limit=None):
    check_statement('query', spec['sql'])
    kinds = [b['t'] for b in spec['binds']]
    if kinds:
        cursor.setinputsizes(*sizes(session.driver, kinds))
    cursor.arraysize = 500
    cursor.execute(spec['sql'], [convert_bind(b['t'], b['v']) for b in spec['binds']])
    names = [d[0].lower() for d in cursor.description]
    rows = cursor.fetchmany(limit + 1) if limit else cursor.fetchall()
    if limit and len(rows) > limit:
        raise Refusal('ORACLE_RESULT_TOO_LARGE', f'the query returns more than {limit} rows', limit=limit)
    types = [c['kind'] for c in spec['columns']] if spec.get('columns') else ['text'] * len(names)
    if len(types) != len(names):
        raise Refusal('ORACLE_PROGRAM_REFUSED', 'result shape differs from the declared columns', declared=len(types), observed=len(names))
    return {'columns': names, 'rows': [[encode_cell(k, v) for k, v in zip(types, row)] for row in rows]}


DICTIONARY_ROWS = 5000


def dictionary(session, cursor, queries):
    """Fixed dictionary queries, bounded so that a very large schema fails clearly instead of producing oversized evidence."""
    result = {}
    for key, spec in queries.items():
        fixed = {'sql': spec['sql'], 'binds': spec['binds'], 'columns': None}
        try:
            result[key] = run_query(session, cursor, fixed, DICTIONARY_ROWS)
        except Refusal as refusal:
            if refusal.code == 'ORACLE_RESULT_TOO_LARGE':
                raise Refusal('ORACLE_RESULT_TOO_LARGE', f'the {key} dictionary query returns more than {DICTIONARY_ROWS} rows; restrict the snapshot with inspection.names', limit=DICTIONARY_ROWS)
            raise
        # dictionary numbers arrive as decimal text; data types and names are text already
    return result


def expect_rows(step, entry):
    if step.get('expectRows') is not None and entry['rows'] != step['expectRows']:
        raise Refusal('ORACLE_ROWCOUNT_MISMATCH', f'step {step["id"]} affected {entry["rows"]} rows; {step["expectRows"]} were expected', step=step['id'],
                      observed=entry['rows'], expected=step['expectRows'])


def execute_step(session, cursor, step, outputs):
    kind, driver = step['kind'], session.driver
    entry = {'id': step['id'], 'kind': kind}
    if kind == 'ddl':
        check_statement('ddl', step['sql'])
        cursor.execute(step['sql'])
        entry['committed'] = True
        if step.get('creates'):
            entry['creates'] = step['creates']
    elif kind == 'insert':
        check_statement('insert', step['sql'])
        cursor.setinputsizes(*sizes(driver, step['types']))
        rows = [[convert_bind(t, v) for t, v in zip(step['types'], row)] for row in step['rows']]
        cursor.executemany(step['sql'], rows)
        entry['rows'] = cursor.rowcount
        expect_rows(step, entry)
    elif kind == 'dml':
        check_statement('dml', step['sql'])
        if step.get('rows') is not None:
            cursor.setinputsizes(*sizes(driver, step['types']))
            cursor.executemany(step['sql'], [[convert_bind(t, v) for t, v in zip(step['types'], row)] for row in step['rows']])
        else:
            if step['binds']:
                cursor.setinputsizes(*sizes(driver, [b['t'] for b in step['binds']]))
            cursor.execute(step['sql'], [convert_bind(b['t'], b['v']) for b in step['binds']])
        entry['rows'] = cursor.rowcount
        expect_rows(step, entry)
    elif kind == 'query':
        outputs[step['id']] = run_query(session, cursor, step, step.get('maxRows'))
        entry['rows'] = len(outputs[step['id']]['rows'])
        if 'expectCount' in step:
            entry['rows'] = int(Decimal(outputs[step['id']]['rows'][0][0]))
            expect_rows({'id': step['id'], 'expectRows': step['expectCount']}, entry)
    elif kind == 'control':
        action, name = step['action'], step.get('name')
        if action in ('savepoint', 'rollbackTo') and not (isinstance(name, str) and NAME.fullmatch(name.upper())):
            raise Refusal('ORACLE_PROGRAM_REFUSED', 'savepoint names are simple identifiers')
        if action == 'savepoint':
            cursor.execute(f'SAVEPOINT "{name.upper()}"')
        elif action == 'rollbackTo':
            cursor.execute(f'ROLLBACK TO SAVEPOINT "{name.upper()}"')
        elif action == 'serializable':
            cursor.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
        elif action == 'commit':
            session.connection.commit()
        elif action == 'rollback':
            session.connection.rollback()
        else:
            raise Refusal('ORACLE_PROGRAM_REFUSED', 'unknown control action', action=str(action)[:20])
    elif kind == 'boundary':
        result = dictionary(session, cursor, step['queries'])
        outputs[step['id']] = result
        effects = {key: value['rows'] for key, value in result.items() if value['rows']}
        if effects:
            raise Refusal('ORACLE_UNDECLARED_EFFECTS', 'database mechanisms can change or execute work outside declared rows', effects=effects, databaseTouched=True, mutationStarted=False)
        entry['validated'] = True
    elif kind == 'validate':
        validate_transaction(step, outputs)
        entry['validated'] = True
    elif kind == 'observe':
        outputs[step['id']] = observe(session, step['queries'])
    else:
        raise Refusal('ORACLE_PROGRAM_REFUSED', 'unknown step kind', kind=str(kind)[:20])
    return entry


def validate_transaction(step, outputs):
    """Validate prospective assignments in the same snapshot, before the first DML.

    The reference is bundled trusted Python. A second check compares the uncommitted
    native state to that reference before COMMIT can make a discrepancy durable.
    Oracle still enforces constraints and row counts in database enforcement mode.
    """
    from schemaxis.adaptors.oracle import reference
    plan = step['plan']
    data = {t['name']: reference.table_rows_native(t, outputs['base:' + t['name']]['rows']) for t in plan['tables']}
    try:
        _, expected = reference.simulate(plan, data)
    except reference.Predicted as error:
        if error.kind == 'value' and error.where.get('reason') in ('scale', 'loss'):
            raise Refusal('ORACLE_VALUE_NOT_STORABLE', str(error), predicted=True,
                          databaseTouched=True, mutationStarted=False, **error.where)
        if step.get('final'):
            raise Refusal('ORACLE_PRECOMMIT_MISMATCH', 'Oracle accepted work the prospective reference expected to refuse',
                          predictedKind=error.kind, **error.where)
        return
    except reference.Unverifiable as error:
        raise Refusal('ORACLE_PRECOMMIT_MISMATCH', str(error), mutationStarted=False)
    if step.get('final'):
        for table in plan['tables']:
            name = table['name']
            observed = reference.table_rows_native(table, outputs['view:' + name]['rows'])
            if reference.table_rows_canonical(table, expected[name]) != reference.table_rows_canonical(table, observed):
                raise Refusal('ORACLE_PRECOMMIT_MISMATCH', 'uncommitted native rows differ from the prospective reference', table=name)


def observe(session, queries):
    """Read through a separate connection so uncommitted work is invisible to it."""
    other = Session(session.driver, session.config)
    connection = other.connect()
    try:
        cursor = connection.cursor()
        return {key: run_query(other, cursor, spec, spec.get('maxRows')) for key, spec in queries.items()}
    finally:
        other.close()


def stage_identify(session, program):
    connection = session.connect()
    cursor = connection.cursor()
    identity = dictionary(session, cursor, program['identity'])
    banner = identity['version']['rows'][0][0] if identity['version']['rows'] else None
    major = re.search(r'(\d+)\.(\d+)', str(connection.version))
    return {'driver': {'name': 'python-oracledb', 'version': session.driver.__version__, 'thin': bool(getattr(connection, 'thin', True))},
            'server': {'version': str(connection.version), 'major': int(major.group(1)) if major else None, 'banner': banner},
            'session': {'schema': identity['session']['rows'][0][0], 'container': identity['session']['rows'][0][1], 'characterSet': identity['charset']['rows'][0][0]},
            'catalog': dictionary(session, cursor, program['catalog'])}


def unknown_outcome(session, program, result, error):
    """A failed COMMIT cannot be replayed blindly: record what a fresh session observes and report the outcome as unknown."""
    oracle = None
    if isinstance(error, session.driver.Error):
        _, oracle, message, _ = classify(error, session.secrets)
    else:
        message = redact(error, session.secrets)
    session.close()
    try:
        resolution = observe(session, program['resolve'])
    except Exception:
        resolution = None
    result.update(status='unknown', outcome='commit-outcome-unknown')
    return Refusal('ORACLE_COMMIT_OUTCOME_UNKNOWN', message, oracle=oracle, resolution=resolution, partial=result)


def journal(event, step, path='apply-journal.jsonl'):
    """Append-and-sync progress record for DDL and commit steps (the steps whose effect cannot be undone)."""
    record = {'event': event, 'id': step['id'], 'kind': step['kind'], 'creates': step.get('creates'), 'action': step.get('action')}
    with open(path, 'a', encoding='utf-8') as stream:
        stream.write(json.dumps(record, sort_keys=True) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def stage_apply(session, program):
    connection = session.connect()
    cursor = connection.cursor()
    done, outputs = [], {}
    created = []
    result = {'status': 'running', 'steps': done, 'outputs': outputs, 'created': created}
    try:
        for step in program['steps']:
            durable = step['kind'] == 'ddl' or (step['kind'] == 'control' and step['action'] in ('commit', 'rollback'))
            path = session.config.get('journal', 'apply-journal.jsonl')
            if durable:
                journal('begin', step, path)      # flushed to disk first: a killed worker still leaves evidence of what was in flight
            if step['kind'] == 'control' and step['action'] == 'commit' and step.get('final'):
                try:
                    done.append(execute_step(session, cursor, step, outputs))
                except Exception as error:
                    raise unknown_outcome(session, program, result, error)
                journal('done', step, path)
                continue
            result['attempted'] = step.get('creates')
            entry = execute_step(session, cursor, step, outputs)
            result['attempted'] = None
            if durable:
                journal('done', step, path)
            done.append(entry)
            if entry.get('creates'):
                created.append(entry['creates'])
    except Refusal as refusal:
        if refusal.code == 'ORACLE_COMMIT_OUTCOME_UNKNOWN':
            raise
        try:
            connection.rollback()
            refusal.details.update(rolledBack=True, partial=result)
        except Exception:
            refusal.details.update(rolledBack=False, partial=result)
        raise
    except session.driver.Error as error:
        code, oracle, message, constraint = classify(error, session.secrets)
        try:
            connection.rollback()
            rolled = True
        except Exception:
            rolled = False
        raise Refusal(code, message, oracle=oracle, constraint=constraint, step=(program['steps'][len(done)]['id'] if len(done) < len(program['steps']) else None), rolledBack=rolled, partial=result)
    result['status'] = 'succeeded'
    return result


def stage_readback(session, program):
    connection = session.connect()
    cursor = connection.cursor()
    result = {'catalog': dictionary(session, cursor, program['catalog']), 'tables': {}, 'cleanup': []}
    for name, spec in program['tables'].items():
        try:
            result['tables'][name] = run_query(session, cursor, spec, spec.get('maxRows'))
        except session.driver.Error as error:
            code, _, _, _ = classify(error, session.secrets)
            if code != 'ORACLE_OBJECT_MISSING':
                raise
            result['tables'][name] = {'missing': True}
    for item in program['cleanup']:
        row = run_query(session, cursor, {'sql': program['marker']['sql'], 'binds': [{'t': 'varchar', 'v': item['table']}], 'columns': None})
        managed = bool(row['rows']) and row['rows'][0][0] == program['marker']['value']
        if managed:
            check_statement('ddl', item['sql'])
            cursor.execute(item['sql'])
        result['cleanup'].append({'table': item['table'], 'dropped': managed, 'reason': 'dropped' if managed else 'not managed by this adaptor or already absent'})
    return result


def write(path, value):
    with open(path, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, indent=1)


def run(stage, driver):
    with open('native-config.json', encoding='utf-8') as stream:
        config = json.load(stream)
    with open(f'program-{stage}.json', encoding='utf-8') as stream:
        program = json.load(stream)
    session = None
    try:
        session = Session(driver, config)
        runner = {'identify': stage_identify, 'apply': stage_apply, 'readback': stage_readback}[stage]
        write(stage + '.json', runner(session, program))
        return 0
    except Refusal as refusal:
        details = dict(refusal.details)
        partial = details.pop('partial', None)
        secrets = session.secrets if session else []
        write(stage + '-fault.json', {'code': refusal.code, 'message': redact(refusal, secrets), 'location': stage, 'details': scrub(details, secrets)})
        if partial is not None:
            write(stage + '-partial.json', partial)
        return 2
    except Exception as error:
        secrets = session.secrets if session else []
        write(stage + '-fault.json', {'code': 'ORACLE_WORKER_ERROR', 'message': redact(f'{type(error).__name__}: {error}', secrets), 'location': stage, 'details': {}})
        return 3
    finally:
        if session is not None:
            session.close()


def main(argv):
    if len(argv) != 2 or argv[1] not in STAGES:
        sys.stderr.write('usage: native_worker.py identify|apply|readback\n')
        return 64
    try:
        import oracledb
    except ImportError:
        write(argv[1] + '-fault.json', {'code': 'ORACLE_DRIVER_UNAVAILABLE', 'message': 'python-oracledb is not installed in this interpreter', 'location': argv[1], 'details': {}})
        return 4
    return run(argv[1], oracledb)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
