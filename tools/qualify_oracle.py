#!/usr/bin/env python3
"""Qualify the Oracle adaptor against a real, disposable Oracle schema.

Needs a dedicated interpreter with python-oracledb (--oracle) and the profile's credentials in the
environment (SCHEMAXIS_ORACLE_<PROFILE>_USER, _PASSWORD, _DSN). Credential values are never printed or
stored by this tool; the run directory is scanned for them at the end. Use only a schema whose
contents may be dropped. Evidence applies to the observed driver/server only.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from schemaxis import workflow
from schemaxis.adaptor_conformance import qualify, register
from schemaxis.adaptors.oracle import adaptor as a
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError

if not __debug__:
    raise SystemExit('run without -O: this harness reports its observations as assertions')

ROOT = Path(__file__).resolve().parents[1]
WORK_SECONDS = 1800          # all adaptor work; observer calls and final cleanup run after it, well inside a 2400 s ceiling
OBSERVER_SECONDS = 30
DEADLINE = [None]


def limit(cap):
    """A per-call timeout that never exceeds what is left of the harness's total budget."""
    remaining = DEADLINE[0] - time.monotonic()
    if remaining < 5:
        raise SystemExit('the harness time budget is exhausted; cleanup still runs')
    return min(cap, remaining - 2)


def interpreter_path(path):
    """Absolute path of the dedicated interpreter WITHOUT following symlinks: a virtual environment's bin/python is a
    link to the base interpreter, and resolving it would lose the environment's installed python-oracledb."""
    return os.path.abspath(os.fspath(path))
FIXTURES = ROOT / 'examples/schemaxis/fixtures/oracle'
MASK = "'TM9', 'NLS_NUMERIC_CHARACTERS=''.,'''"
OBSERVER = '''
import json, os, sys, oracledb
prefix = sys.argv[1]
connection = oracledb.connect(user=os.environ[prefix + "_USER"], password=os.environ[prefix + "_PASSWORD"], dsn=os.environ[prefix + "_DSN"])
cursor = connection.cursor()
result = []
for statement in json.loads(sys.argv[2]):
    try:
        cursor.execute(statement)
        result.append([[None if v is None else str(v) for v in row] for row in cursor.fetchall()] if cursor.description else [])
    except oracledb.Error as error:
        result.append({"error": str(error.args[0].code)})
print(json.dumps(result))
'''


def example(name):
    document = json.loads((ROOT / 'examples/schemaxis' / f'oracle-{name}.json').read_text())
    for table in document.get('tables', []):
        if 'source' in table:
            table['source']['path'] = str(FIXTURES / Path(table['source']['path']).name)
    return document


def refused(action, *codes):
    try:
        action()
    except SchemaxisError as error:
        assert error.fault.code in codes, error.fault.to_dict()
        return error.fault
    raise AssertionError('expected a refusal ' + '/'.join(codes))


class Observer:
    """Direct driver queries in the dedicated interpreter, independent of the adaptor's code."""

    def __init__(self, interpreter, profile):
        self.interpreter, self.prefix = interpreter, 'SCHEMAXIS_ORACLE_' + profile.upper()

    def __call__(self, *statements):
        done = subprocess.run([self.interpreter, '-I', '-c', OBSERVER, self.prefix, json.dumps(statements)], capture_output=True, text=True, timeout=OBSERVER_SECONDS, env=os.environ)
        assert done.returncode == 0, 'observer failed: ' + done.stderr[-300:].replace(os.environ.get(self.prefix + '_PASSWORD', '\0'), '<redacted>')
        return json.loads(done.stdout)

    def tables(self, *names):
        """Tables named exactly like one of ``names`` or carrying the run-unique scratch suffix (_ plus five hex digits)."""
        pattern = re.compile('^(%s)(_[0-9A-F]{5})?$' % '|'.join(re.escape(n.upper()) for n in names))
        return [r[0] for r in self('SELECT table_name FROM user_tables ORDER BY 1')[0] if pattern.match(r[0])]

    def exact(self, *names):
        wanted = {n.upper() for n in names}
        return [r[0] for r in self('SELECT table_name FROM user_tables ORDER BY 1')[0] if r[0] in wanted]


OWNED_NAMES = ('order_lines', 'orders', 'customers', 'accounts', 'wide', 'documents', 'change_ledger', 'sx_deferred_ledger', 'sx_effect_audit', 'sx_effect_child')   # dependency order: children first


def preflight(observe, schema, confirmed):
    """Refuse to start unless the operator named and confirmed the schema and none of the declared table names is
    taken. A scratch leftover from some earlier job is NOT evidence of ownership and is never touched."""
    if not confirmed or not schema:
        raise SystemExit('refusing to run: pass --schema NAME --confirm-disposable to state that this schema may be filled and cleaned')
    current = observe("SELECT SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') FROM DUAL")[0][0][0]
    if current.upper() != schema.upper():
        raise SystemExit('refusing to run: the connected schema is not the one named by --schema')
    taken = [n for n in observe.exact(*OWNED_NAMES)]
    if taken:
        raise SystemExit('refusing to run: these tables already exist and are not owned by this harness: ' + ', '.join(taken))


IDENTIFIER = re.compile('^[A-Z][A-Z0-9_]{0,29}$')


def owned_tables(root):
    """Every table that a run recorded under ``root`` created or may have created, as (physical name, that run's
    ownership marker): derived from each run's own plan and runId, never from a wildcard on names."""
    found = []
    for config in sorted(Path(root).rglob('native-config.json')):
        run = config.parent
        try:
            p = a.plan(a.read(run, 'authored.json'))
            run_id = a.read(run, 'native-config.json')['runId']
        except (SchemaxisError, OSError, KeyError):
            continue
        if p['operation'] == 'inspect':
            continue
        names = a.physical_names(p, run_id)
        by_name = {t['name']: t for t in p['tables']}
        for logical in reversed(p['order']):
            if not by_name[logical]['external']:
                found.append((names.get(logical, logical).upper(), a.sql.run_marker(run_id)))
    return found


def cleanup(observe, root):
    """Drop only tables whose dictionary comment equals the exact marker of the run that created them (children first
    within each run). A table with another marker, no marker, or an unexpected name is reported and left alone."""
    dropped, left = [], []
    for name, marker in owned_tables(root):
        if not IDENTIFIER.match(name):
            left.append(name)
            continue
        rows = observe("SELECT comments FROM user_tab_comments WHERE table_name = '%s' AND table_type = 'TABLE'" % name)[0]
        if not rows:
            continue                                                   # never created, or already dropped
        if rows[0][0] != marker:
            left.append(name)
            continue
        observe('DROP TABLE %s PURGE' % name)
        dropped.append(name.lower())
    return {'dropped': dropped, 'leftUntouched': left}


def bounded_run(document, path, *, executable, timeout):
    return a.run(document, path, executable=executable, timeout=limit(timeout))


def inject(data):
    program = json.loads(data)
    program['steps'].append({'id': 'x', 'kind': 'ddl', 'sql': 'DROP TABLE "CUSTOMERS" PURGE'})
    return json.dumps(program).encode()


def hostile(directory):
    """Coherent tampering of a native run must be refused even when digests are refreshed."""
    saved = {p: p.read_bytes() for p in directory.rglob('*') if p.is_file()}
    report = {}

    def refresh():
        receipt = a.read(directory, 'verification.json')
        receipt['evidence'] = {n: a.digest(directory, n) for n in receipt['evidence']}
        for item in receipt['artifacts']:
            item['sha256'] = a.digest(directory, Path(item['file']).name)
        atomic_json(directory / 'verification.json', receipt)
    for name, target, change in [('publishedRows', 'report.json', lambda b: b.replace(b'350.5', b'351.5')), ('nativeRows', 'apply.json', lambda b: b.replace(b'"350.5"', b'"351.5"')),
                                 ('readbackRows', 'readback.json', lambda b: b.replace(b'1500.5', b'1500.6')), ('injectedStatement', 'program-apply.json', inject),
                                 ('capturedSource', 'source-customers.json', lambda b: b.replace(b'Acme', b'Acne')), ('identity', 'identify.json', lambda b: b.replace(b'AL32UTF8', b'WE8ISO8859P1'))]:
        try:
            path = directory / target
            changed = change(path.read_bytes())
            assert changed != path.read_bytes(), name
            path.write_bytes(changed)
            refresh()
            report[name] = refused(lambda: a.verify(directory), 'VERIFICATION_FAILED', 'ORACLE_UNSUPPORTED_CHARSET').code
        finally:
            for p, b in saved.items():
                p.write_bytes(b)
    assert a.verify(directory)['verified']
    return report


def qualify_relations(directory, interpreter, profile, scratch):
    table = copy.deepcopy(example('mutate-transfer')['tables'][0])
    column = lambda name: {'column': 'a.' + name}
    select = {'from': {'table': 'accounts', 'alias': 'a'}, 'columns': [{'name': 'id', 'operand': column('id')}]}
    document = {'version': a.VERSION, 'operation': 'report', 'connection': {'profile': profile}, 'tables': [table], 'report': {'selects': [select], 'orderBy': [{'column': 'id'}]}}
    results = {}
    def run_case(name, change, expected):
        bounded_run(change, directory / name, executable=interpreter, timeout=120)
        assert a.read(directory / name, 'report.json')['rows'] == expected, name
        results[name] = expected
    left, right = copy.deepcopy(select), copy.deepcopy(select)
    for spec, ids in ((left, ['1', '2']), (right, ['2', '3'])):
        spec['conditions'] = [{'name': 'chosen', 'terms': [{'left': column('id'), 'operator': 'in', 'values': [{'literal': {'type': 'number', 'value': v}} for v in ids]}]}]
        spec['where'] = 'chosen'
    for combine, expected in [('unionAll', [['1'], ['2'], ['2'], ['3']]), ('union', [['1'], ['2'], ['3']]), ('intersect', [['2']]), ('except', [['1']])]:
        change = copy.deepcopy(document); change['report'].update(selects=[left, right], combine=combine)
        run_case('relational-' + combine, change, expected)
    change = copy.deepcopy(document); change['report'].update(selects=[left, right], combine='unionAll', distinct=True)
    run_case('relational-distinct', change, [['1'], ['2'], ['3']])
    change = copy.deepcopy(document); change['report'].update(offset=1, limit=1)
    run_case('relational-offset', change, [['2']])
    change = copy.deepcopy(document)
    change['report']['selects'][0]['columns'].append({'name': 'balance', 'operand': column('balance')})
    change['report']['windows'] = [{'name': 'row_index', 'function': 'rowNumber', 'orderBy': [{'column': 'id'}]}, {'name': 'running', 'function': 'runningSum', 'argument': 'balance', 'orderBy': [{'column': 'id'}]}]
    run_case('relational-running', change, [['1', '100', '1', '100'], ['2', '50', '2', '150'], ['3', '0', '3', '150']])
    source = Path(scratch) / 'typed-values.json'
    source.write_text(json.dumps([{'id': 1, 'token': '00ff', 'enabled': True}, {'id': 2, 'token': 'deadbeef', 'enabled': False}, {'id': 3, 'token': None, 'enabled': None}]))
    typed = {'name': 'typed_values', 'columns': [{'name': 'id', 'type': 'number', 'precision': 5, 'scale': 0}, {'name': 'token', 'type': 'raw', 'length': 8, 'nullable': True}, {'name': 'enabled', 'type': 'boolean', 'nullable': True}], 'primaryKey': ['id'], 'source': {'path': str(source)}}
    change = copy.deepcopy(document); change['tables'] = [typed]
    change['report']['selects'] = [{'from': {'table': 'typed_values', 'alias': 't'}, 'columns': [{'name': c, 'operand': {'column': 't.' + c}} for c in ('id', 'token', 'enabled')]}]
    run_case('relational-raw-boolean', change, [['1', '00ff', True], ['2', 'deadbeef', False], ['3', None, None]])
    change['report']['selects'][0].update(conditions=[{'name': 'active', 'terms': [{'left': {'column': 't.enabled'}, 'operator': 'equals', 'right': {'literal': {'type': 'boolean', 'value': True}}}]}], where='active')
    run_case('relational-boolean-filter', change, [['1', '00ff', True]])
    return results


def qualify_documents(directory, scratch, interpreter, observe, profile):
    """The same document records cross captured input, load, external reads and mutation."""
    document = example('report-documents')
    document['connection']['profile'] = profile
    source = Path(scratch) / 'documents.json'
    source.write_bytes((FIXTURES / 'documents.json').read_bytes())
    document['tables'][0]['source']['path'] = str(source)
    bounded_run(document, directory / 'documents', executable=interpreter, timeout=120)
    first = a.read(directory / 'documents', 'report.json')['rows']
    assert first[0][2] == '0001ff80' and first[0][4:] == ['12.5', 'café', True]
    assert first[1][4:] == ['2', None, False] and first[2][4:] == [None, None, None]
    assert len(first[0][1]) > 4000 and '😀' in first[0][1]
    # A changed source produces a changed result; prior captured evidence remains valid.
    rows = json.loads(source.read_text())
    rows[0]['note'] = 'changed Unicode 測定 😀'
    rows[0]['payload'] = 'aabb00'
    rows[0]['metadata'] = '{"samples":[{"value":19.125}],"name":"changed","approved":false}'
    source.write_text(json.dumps(rows))
    bounded_run(document, directory / 'documents-changed', executable=interpreter, timeout=120)
    assert a.verify(directory / 'documents')['verified']
    changed = a.read(directory / 'documents-changed', 'report.json')['rows']
    assert changed[0][1:3] == ['changed Unicode 測定 😀', 'aabb00'] and changed[0][4:] == ['19.125', 'changed', False]
    # Refresh ordinary digests; the independent semantic comparison must still refuse.
    target = directory / 'documents-changed'
    saved = {p: p.read_bytes() for p in target.iterdir() if p.is_file()}
    tampered = []
    for name in ('report.json', 'apply.json', 'readback.json'):
        try:
            path = target / name
            raw = path.read_bytes()
            assert b'aabb00' in raw
            path.write_bytes(raw.replace(b'aabb00', b'aabb01'))
            receipt = a.read(target, 'verification.json')
            receipt['evidence'] = {n: a.digest(target, n) for n in receipt['evidence']}
            for item in receipt['artifacts']:
                item['sha256'] = a.digest(target, Path(item['file']).name)
            atomic_json(target / 'verification.json', receipt)
            refused(lambda: a.verify(target), 'VERIFICATION_FAILED')
            tampered.append(name)
        finally:
            for p, data in saved.items():
                p.write_bytes(data)
    assert a.verify(target)['verified']
    # Persisted objects, then external report: dictionary/LOB data are read again.
    load = copy.deepcopy(document)
    load['operation'] = 'load'; load.pop('report'); load['setup'] = {'retain': True}
    bounded_run(load, directory / 'documents-load', executable=interpreter, timeout=120)
    external = copy.deepcopy(document)
    external['tables'][0].pop('source'); external['tables'][0]['external'] = True
    bounded_run(external, directory / 'documents-external', executable=interpreter, timeout=120)
    assert a.read(directory / 'documents-external', 'report.json')['rows'] == changed
    assert observe('SELECT DBMS_LOB.GETLENGTH(note), RAWTOHEX(DBMS_LOB.SUBSTR(payload, 3, 1)) FROM documents WHERE id=1')[0] == [[str(len(rows[0]['note']) + 1), 'AABB00']]
    # Mutate LOB and JSON values through ordinary typed steps; verify before COMMIT.
    mutation = copy.deepcopy(load)
    mutation['operation'] = 'mutate'
    mutation['transaction'] = {'steps': [{'kind': 'update', 'table': 'documents', 'conditions': [{'name': 'first', 'terms': [{'left': {'column': 'documents.id'}, 'operator': 'equals', 'right': {'literal': {'type': 'number', 'value': '1'}}}]}], 'where': 'first', 'expectRows': 1,
                                         'set': [{'column': 'note', 'value': {'literal': {'type': 'clob', 'value': 'reconciled 測定 😀'}}}, {'column': 'payload', 'value': {'literal': {'type': 'blob', 'value': '1234ff'}}}, {'column': 'metadata', 'value': {'literal': {'type': 'json', 'value': '{"changed":true}'}}}]}]}
    mutation['setup'] = {'retain': False}
    bounded_run(mutation, directory / 'documents-mutate', executable=interpreter, timeout=120)
    final = a.read(directory / 'documents-mutate', 'state-after.json')['tables']['documents']['rows'][0]
    assert final[1:] == ['reconciled 測定 😀', '1234ff', '{"changed":true}']
    # Oracle's closed paths still have lax array wrapping/unwrapping semantics.
    shape_cases = [('{"items":[{"value":1}]}', '$.items.value', 'jsonNumber', '1'),
                   ('{"items":[]}', '$.items.value', 'jsonNumber', None),
                   ('1', '$[0]', 'jsonNumber', '1'), ('{"a":1}', '$[0].a', 'jsonNumber', '1'),
                   ('[[{"a":2}]]', '$.a', 'jsonNumber', None),
                   ('{"x":"true"}', '$.x', 'jsonBoolean', True), ('{"x":"FALSE"}', '$.x', 'jsonBoolean', False)]
    shape_results = []
    for index, (text, path, function, expected) in enumerate(shape_cases):
        source.write_text(json.dumps([{'id': 1, 'note': None, 'payload': None, 'metadata': text}]))
        shape = copy.deepcopy(document)
        select = shape['report']['selects'][0]
        select['computed'] = [{'name': 'value', 'function': function, 'arguments': [{'column': 'd.metadata'}], 'path': path}]
        select['columns'] = [{'name': 'id', 'operand': {'column': 'd.id'}}, {'name': 'value', 'operand': {'derived': 'value'}}]
        bounded_run(shape, directory / ('json-shape-' + str(index)), executable=interpreter, timeout=120)
        assert a.read(directory / ('json-shape-' + str(index)), 'report.json')['rows'] == [['1', expected]]
        shape_results.append({'path': path, 'function': function, 'expected': expected})
    for index, (text, function) in enumerate([('{"items":[{"value":1},{"value":2}]}', 'jsonNumber'), ('{"items":{"value":1}}', 'jsonBoolean')]):
        source.write_text(json.dumps([{'id': 1, 'note': None, 'payload': None, 'metadata': text}]))
        shape['report']['selects'][0]['computed'][0].update(function=function, path='$.items.value')
        fault = refused(lambda: bounded_run(shape, directory / ('json-invalid-' + str(index)), executable=interpreter, timeout=120), 'ORACLE_UNVERIFIABLE_VALUE')
        assert not (directory / ('json-invalid-' + str(index)) / 'identify.json').exists()
    return {'boundedUnicodeClob': True, 'binaryBlob': True, 'nativeJson': True, 'typedScalars': True, 'closedLaxPathCases': shape_results, 'multiMatchAndBooleanNumberRefusedBeforeDatabase': True, 'missingAndNull': True,
            'changedSource': True, 'capturedEvidenceSurvivesSourceChange': True, 'externalLoadReadback': True, 'typedMutation': True, 'refreshedDigestTampering': tampered}


def qualify_effect_boundary(directory, interpreter, observe, document):
    """An autonomous trigger and undeclared child must never see mutation DML."""
    audit, child, trigger = 'sx_effect_audit', 'sx_effect_child', 'sx_effect_trigger'
    marker = 'schemaxis-effect-boundary-fixture'
    assert not observe.exact(audit, child)
    assert observe("SELECT COUNT(*) FROM user_triggers WHERE trigger_name='SX_EFFECT_TRIGGER'")[0] == [['0']]
    created, made_trigger = [], False
    def unchanged():
        assert observe('SELECT TO_CHAR(balance, %s) FROM accounts WHERE id=1' % MASK, 'SELECT COUNT(*) FROM change_ledger', 'SELECT COUNT(*) FROM sx_effect_audit') == [[['70']], [['2']], [['0']]]
    try:
        assert observe('CREATE TABLE sx_effect_audit (value NUMBER)')[0] == []
        created.append(audit)
        assert observe("COMMENT ON TABLE sx_effect_audit IS '" + marker + "'")[0] == []
        trigger_creation = observe('CREATE TRIGGER sx_effect_trigger BEFORE UPDATE ON accounts FOR EACH ROW DECLARE PRAGMA AUTONOMOUS_TRANSACTION; BEGIN /*' + marker + '*/ INSERT INTO sx_effect_audit VALUES (1); COMMIT; END;')[0]
        assert trigger_creation == [], trigger_creation
        made_trigger = True
        assert observe("SELECT status FROM user_objects WHERE object_name='SX_EFFECT_TRIGGER' AND object_type='TRIGGER'")[0] == [['VALID']]
        change = copy.deepcopy(document); change['transaction']['idempotency']['key'] = 'trigger-refusal'
        fault = refused(lambda: bounded_run(change, directory / 'effect-trigger', executable=interpreter, timeout=120), 'ORACLE_UNDECLARED_EFFECTS')
        assert fault.observed['mutationStarted'] is False and 'triggers' in fault.observed['effects']
        unchanged()
        report = {'version': a.VERSION, 'operation': 'report', 'connection': document['connection'], 'tables': [document['tables'][0]], 'report': {'selects': [{'from': {'table': 'accounts', 'alias': 'a'}, 'columns': [{'name': 'id', 'operand': {'column': 'a.id'}}]}], 'orderBy': [{'column': 'id'}]}}
        bounded_run(report, directory / 'effect-trigger-read', executable=interpreter, timeout=120)
        unchanged()
        assert observe('DROP TRIGGER sx_effect_trigger')[0] == []
        made_trigger = False
        for rule in ('CASCADE', 'SET NULL'):
            assert observe('CREATE TABLE sx_effect_child (id NUMBER PRIMARY KEY, parent_id NUMBER REFERENCES accounts(id) ON DELETE ' + rule + ')')[0] == []
            created.append(child)
            assert observe("COMMENT ON TABLE sx_effect_child IS '" + marker + "'")[0] == []
            # Observer uses a fresh connection per call; DDL following INSERT commits this fixture seed.
            assert observe('INSERT INTO sx_effect_child VALUES (1, 1)', "COMMENT ON TABLE sx_effect_child IS '" + marker + "'")[0] == []
            deletion = copy.deepcopy(document)
            deletion['transaction']['idempotency']['key'] = 'child-' + rule.replace(' ', '-')
            deletion['transaction']['steps'] = [{'kind': 'delete', 'table': 'accounts', 'conditions': [{'name': 'first', 'terms': [{'left': {'column': 'accounts.id'}, 'operator': 'equals', 'right': {'literal': {'type': 'number', 'value': '1'}}}]}], 'where': 'first', 'expectRows': 1}]
            fault = refused(lambda: bounded_run(deletion, directory / ('effect-child-' + rule.replace(' ', '-').lower()), executable=interpreter, timeout=120), 'ORACLE_UNDECLARED_EFFECTS')
            assert fault.observed['mutationStarted'] is False and 'incomingActions' in fault.observed['effects']
            unchanged()
            assert observe('SELECT id, parent_id FROM sx_effect_child')[0] == [['1', '1']]
            assert observe('DROP TABLE sx_effect_child PURGE')[0] == []
            created.remove(child)
        return {'autonomousTriggerRefusedBeforeDml': True, 'readOnlyReportWithOrdinaryTrigger': True, 'undeclaredCascadeRefusedBeforeDml': True, 'undeclaredSetNullRefusedBeforeDml': True, 'auditChildAccountLedgerUnchanged': True}
    finally:
        if made_trigger:
            assert observe("SELECT COUNT(*) FROM user_source WHERE name='SX_EFFECT_TRIGGER' AND type='TRIGGER' AND text LIKE '%" + marker + "%'")[0] != [['0']]
            observe('DROP TRIGGER sx_effect_trigger')
        for name in reversed(created):
            assert observe("SELECT comments FROM user_tab_comments WHERE table_name='" + name.upper() + "'")[0] == [[marker]]
            assert observe('DROP TABLE ' + name + ' PURGE')[0] == []


def qualify_existing(directory, interpreter, observe, profile):
    cleanup(observe, directory)
    document = example('mutate-existing'); document['connection']['profile'] = profile
    load = {'version': a.VERSION, 'operation': 'load', 'connection': document['connection'], 'setup': {'retain': True}, 'tables': copy.deepcopy(document['tables'])}
    for table in load['tables']:
        table['external'] = False
    load['tables'][0]['source'] = {'path': str(FIXTURES / 'accounts.json')}
    bounded_run(load, directory / 'existing-setup', executable=interpreter, timeout=120)
    assert observe("SELECT segment_created FROM user_tables WHERE table_name='CHANGE_LEDGER'")[0] == [['YES']]
    def state():
        return observe('SELECT TO_CHAR(balance, %s) FROM accounts WHERE id=1' % MASK, 'SELECT COUNT(*) FROM change_ledger')
    cases = []
    cases.append(('existing-commit', copy.deepcopy(document), None, '75', '1'))
    cases.append(('existing-replay', copy.deepcopy(document), 'ORACLE_ALREADY_APPLIED', '75', '1'))
    conflict = copy.deepcopy(document); conflict['transaction']['steps'][0]['computed'][0]['arguments'][1]['literal']['value'] = '5'
    cases.append(('existing-conflict', copy.deepcopy(conflict), 'ORACLE_IDEMPOTENCY_CONFLICT', '75', '1'))
    rollback = copy.deepcopy(conflict); rollback['transaction']['idempotency']['key'] = 'rollback'; rollback['transaction']['finish'] = 'rollback'
    cases.append(('existing-rollback', rollback, None, '75', '1'))
    mismatch = copy.deepcopy(conflict); mismatch['transaction']['idempotency']['key'] = 'rowcount'; mismatch['transaction']['steps'][0]['expectRows'] = 2
    cases.append(('existing-rowcount', mismatch, 'ORACLE_ROWCOUNT_MISMATCH', '75', '1'))
    loss = copy.deepcopy(conflict); loss['transaction']['idempotency']['key'] = 'loss'; loss['transaction']['steps'][0]['computed'][0]['arguments'][1]['literal']['value'] = '0.015'
    cases.append(('existing-scale-loss', loss, 'ORACLE_VALUE_NOT_STORABLE', '75', '1'))
    next_change = copy.deepcopy(conflict); next_change['transaction']['idempotency']['key'] = 'next'
    cases.append(('existing-next', next_change, None, '70', '2'))
    results = {}
    for name, change, code, balance, count in cases:
        if code:
            fault = refused(lambda: bounded_run(change, directory / name, executable=interpreter, timeout=120), code)
            assert fault.observed['rollbackVerified'] is True, fault.to_dict()
            if code == 'ORACLE_VALUE_NOT_STORABLE':
                assert fault.observed['databaseTouched'] is True and fault.observed['mutationStarted'] is False and fault.observed['commitLanded'] is False, fault.to_dict()
        else:
            bounded_run(change, directory / name, executable=interpreter, timeout=120)
        assert state() == [[[balance]], [[count]]], (name, state())
        results[name] = code or 'verified'
    results['effectBoundary'] = qualify_effect_boundary(directory, interpreter, observe, document)
    # Fresh external deferred-segment ledger: refuse honestly, without replay or effects.
    name = 'sx_deferred_ledger'
    assert not observe.exact(name)
    marker = 'schemaxis-qualification-deferred-ledger'
    try:
        assert observe('CREATE TABLE sx_deferred_ledger (idempotency_key VARCHAR2(64 CHAR) NOT NULL PRIMARY KEY, plan_digest VARCHAR2(64 CHAR) NOT NULL) SEGMENT CREATION DEFERRED')[0] == []
        assert observe("COMMENT ON TABLE sx_deferred_ledger IS '" + marker + "'")[0] == []
        deferred = copy.deepcopy(next_change)
        deferred['tables'][1]['name'] = name; deferred['transaction']['idempotency']['table'] = name; deferred['transaction']['idempotency']['key'] = 'deferred'
        fault = refused(lambda: bounded_run(deferred, directory / 'existing-deferred', executable=interpreter, timeout=120), 'ORACLE_SERIALIZATION_CONFLICT')
        assert fault.observed['oracle'] == 'ORA-08177' and fault.observed['rollbackVerified'] is True
        assert state() == [[['70']], [['2']]]
        assert observe('SELECT COUNT(*) FROM sx_deferred_ledger')[0] == [['0']]
        results['existing-deferred'] = fault.code
    finally:
        comments = observe("SELECT comments FROM user_tab_comments WHERE table_name='SX_DEFERRED_LEDGER'")[0]
        if comments == [[marker]]:
            assert observe('DROP TABLE sx_deferred_ledger PURGE')[0] == []
        else:
            raise AssertionError('deferred fixture ownership changed; left untouched')
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--oracle', required=True, type=Path, help='dedicated interpreter with python-oracledb')
    parser.add_argument('--profile', default='free_local')
    parser.add_argument('--schema', help='name of the dedicated schema the profile connects to')
    parser.add_argument('--confirm-disposable', action='store_true', help='state that this schema may be filled with test tables and cleaned')
    parser.add_argument('--output-directory', required=True, type=Path)
    parser.add_argument('--register', action='store_true', help='register the successful native receipt')
    args = parser.parse_args()
    directory = args.output_directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    DEADLINE[0] = time.monotonic() + WORK_SECONDS
    scratch = tempfile.TemporaryDirectory(prefix='oracle-qualify-')        # generated inputs live here, not in the evidence directory
    interpreter = interpreter_path(args.oracle)
    locations = {'oracle': interpreter}
    observe = Observer(interpreter, args.profile)
    prefix = observe.prefix
    report = {'verified': False}
    try:
        for suffix in ('_USER', '_PASSWORD', '_DSN'):
            assert os.environ.get(prefix + suffix), 'set ' + prefix + suffix
        preflight(observe, args.schema, args.confirm_disposable)
        report['preflight'] = 'passed'
        receipt = qualify(a.VERSION, directory / 'kit', native=True, root=ROOT, locations=locations, timeout=limit(60), wall_timeout=limit(120))
        report['native'] = {'verified': receipt['verified'], 'cases': [c['id'] for c in receipt['cases']], 'runtimes': sorted({c['runtime'] for c in receipt['cases']}), 'lifecycle': receipt['lifecycle']}
        identify = a.read(directory / 'kit' / 'baseline', 'identify.json')
        report['identity'] = {'driver': identify['driver'], 'server': {k: identify['server'][k] for k in ('version', 'banner')}, 'characterSet': identify['session']['characterSet']}
        report['hostile'] = hostile(directory / 'kit' / 'baseline')

        # Exact NUMBER(38,10) extremes, Unicode, empty-string-is-NULL and time-zone offsets, observed directly.
        source = Path(scratch.name) / 'wide.json'                  # the run captures its own copy into its evidence
        source.write_text(json.dumps([{'id': 1, 'big': '9999999999999999999999999999.9999999999', 'label': '😀 Zoë 東京'}, {'id': 2, 'big': '-9999999999999999999999999999.9999999999', 'label': None},
                                      {'id': 3, 'big': '0.0000000001', 'label': ''}]))
        wide = {'version': a.VERSION, 'operation': 'load', 'connection': {'profile': args.profile}, 'setup': {'retain': True},
                'tables': [{'name': 'wide', 'columns': [{'name': 'id', 'type': 'number', 'precision': 5, 'scale': 0}, {'name': 'big', 'type': 'number', 'precision': 38, 'scale': 10},
                                                        {'name': 'label', 'type': 'varchar2', 'length': 40, 'nullable': True, 'emptyText': 'null'}], 'primaryKey': ['id'], 'source': {'path': str(source)}}]}
        lines = example('load')
        lines['tables'][0]['source']['path'] = str(FIXTURES / 'customers.json')
        try:
            bounded_run(wide, directory / 'wide', executable=interpreter, timeout=120)
            bounded_run(lines, directory / 'lines', executable=interpreter, timeout=120)
            seen = observe('SELECT id, TO_CHAR(big, %s), label, LENGTH(label) FROM wide ORDER BY id' % MASK,
                           'SELECT COUNT(*) FROM wide WHERE label IS NULL',
                           "SELECT TO_CHAR(packed_at, 'YYYY-MM-DD\"T\"HH24:MI:SS.FF3TZH:TZM') FROM order_lines WHERE id = 101",
                           'SELECT COUNT(*) FROM customers', "SELECT comments FROM user_tab_comments WHERE table_name = 'WIDE'")
            assert seen[0] == [['1', '9999999999999999999999999999.9999999999', '😀 Zoë 東京', '8'], ['2', '-9999999999999999999999999999.9999999999', None, None], ['3', '.0000000001', None, None]], seen[0]
            assert seen[1] == [['2']] and seen[2] == [['2026-01-06T11:30:00.500+01:00']] and seen[3] == [['4']] and seen[4][0][0].startswith('schemaxis-oracle:run:'), seen
            report['exactValues'] = {'decimal38Extremes': True, 'unicodeSupplementaryRoundTrip': True, 'emptyTextBecameNull': True, 'timeZoneOffsetPreserved': True, 'markerComment': True}
            inspect = {'version': a.VERSION, 'operation': 'inspect', 'connection': {'profile': args.profile}, 'inspection': {'kinds': ['tables'], 'names': ['wide']},
                       'tables': [{k: v for k, v in wide['tables'][0].items() if k != 'source'}]}
            bounded_run(inspect, directory / 'inspect', executable=interpreter, timeout=120)
            snapshot = a.read(directory / 'inspect', 'snapshot.json')
            assert snapshot['drift'] == [] and snapshot['snapshot']['tables'][0]['managed'] is True
            report['inspectDrift'] = 'declared table matches dictionary'
            # A second load must refuse an existing table and must not touch it.
            refused(lambda: bounded_run(wide, directory / 'exists', executable=interpreter, timeout=120), 'ORACLE_OBJECT_EXISTS')
            assert observe('SELECT COUNT(*) FROM wide')[0] == [['3']]
            # Computed NUMBER results: non-terminating division and AVG may carry more than 38 digits natively.
            column = lambda name: {'column': 'w.' + name}
            third = {'version': a.VERSION, 'operation': 'report', 'connection': {'profile': args.profile},
                     'tables': [{**{k: v for k, v in wide['tables'][0].items() if k != 'source'}, 'external': True}],
                     'report': {'selects': [{'from': {'table': 'wide', 'alias': 'w'}, 'computed': [{'name': 'third', 'function': 'divide', 'arguments': [column('big'), {'literal': {'type': 'number', 'value': '3'}}]}],
                                             'columns': [{'name': 'id', 'operand': column('id')}, {'name': 'third', 'operand': {'derived': 'third'}}]}], 'orderBy': [{'column': 'id'}]}}
            bounded_run(third, directory / 'divide', executable=interpreter, timeout=120)
            average = copy.deepcopy(third)
            average['report'] = {'selects': [{'from': {'table': 'wide', 'alias': 'w'}, 'measures': [{'name': 'mean', 'function': 'average', 'argument': column('big')}],
                                              'columns': [{'name': 'mean', 'operand': {'measure': 'mean'}}]}]}
            bounded_run(average, directory / 'average', executable=interpreter, timeout=120)
            digits = [len(v.replace('-', '').replace('.', '').lstrip('0')) for v in (a.read(directory / 'divide', 'report.json')['rows'][0][1], a.read(directory / 'average', 'report.json')['rows'][0][0])]
            report['computedNumbers'] = {'verifiedAgainstReference': True, 'resultSignificantDigits': digits}
            # Committed and rolled-back transactions, observed from a separate direct session.
            cleanup(observe, directory)
            transfer = example('mutate-transfer')
            transfer['setup'] = {'retain': True}
            bounded_run(transfer, directory / 'transfer', executable=interpreter, timeout=120)
            assert observe('SELECT id, owner, TO_CHAR(balance, %s) FROM accounts ORDER BY id' % MASK)[0] == [['1', 'alice', '75'], ['2', 'bob', '75'], ['3', 'carol', '5'], ['4', 'dave', '10'], ['5', 'erin', '1']]
            cleanup(observe, directory)
            rollback = example('mutate-rollback')
            rollback['setup'] = {'retain': True}
            bounded_run(rollback, directory / 'rollback', executable=interpreter, timeout=120)
            assert observe('SELECT COUNT(*), MIN(id) FROM accounts')[0] == [['3', '1']]
            cleanup(observe, directory)
            violation = example('mutate-violation')
            violation['setup'] = {'retain': True}
            fault = refused(lambda: bounded_run(violation, directory / 'violation', executable=interpreter, timeout=120), 'ORACLE_CONSTRAINT_VIOLATION')
            assert fault.observed['rollbackVerified'] is True and fault.observed['oracle'] == 'ORA-00001', fault.to_dict()
            assert observe('SELECT COUNT(*) FROM accounts')[0] == [['3']]
            cleanup(observe, directory)
            # Assignment must fit the target column: silent scale loss is refused before any native work, and an explicit
            # round policy models Oracle's half-away-from-zero storage rounding (99.985 -> 99.99), observed directly.
            unstorable = example('mutate-transfer')
            unstorable['transaction']['steps'] = unstorable['transaction']['steps'][:1]
            unstorable['transaction']['steps'][0]['computed'][0]['arguments'][1]['literal']['value'] = '0.015'
            for mode in ('predict', 'database'):
                unstorable['transaction']['enforcement'] = mode
                loss = refused(lambda: bounded_run(unstorable, directory / ('unstorable-' + mode), executable=interpreter, timeout=120), 'ORACLE_VALUE_NOT_STORABLE')
                assert loss.observed['databaseTouched'] is False and not observe.tables('accounts'), loss.to_dict()
            rounding = copy.deepcopy(unstorable)
            rounding['transaction']['enforcement'] = 'predict'
            rounding['tables'][0]['columns'][2]['scalePolicy'] = 'round'
            rounding['setup'] = {'retain': True}
            bounded_run(rounding, directory / 'rounded', executable=interpreter, timeout=120)
            assert observe('SELECT id, owner, TO_CHAR(balance, %s) FROM accounts ORDER BY id' % MASK)[0] == [['1', 'alice', '99.99'], ['2', 'bob', '50'], ['3', 'carol', '0']]
            report['assignmentFit'] = {'scaleLossRefusedBeforeDatabase': True, 'explicitRoundingMatchesOracle': True}
            report['transactions'] = {'commitVisibleToSeparateSession': True, 'rollbackLeavesRowsUnchanged': True, 'databaseEnforcedUniqueViolationRolledBack': True, 'oracleError': fault.observed['oracle']}

            cleanup(observe, directory)
            report['relationalMatrix'] = qualify_relations(directory, interpreter, args.profile, scratch.name)
            report['documents'] = qualify_documents(directory, scratch.name, interpreter, observe, args.profile)
            report['existingTables'] = qualify_existing(directory, interpreter, observe, args.profile)
            # Failures: wrong password and unreachable DSN are redacted and change nothing.
            secret = os.environ[prefix + '_PASSWORD']
            with patch.dict(os.environ, {prefix + '_PASSWORD': secret + 'x'}):
                bad = refused(lambda: bounded_run(example('inspect'), directory / 'badpassword', executable=interpreter, timeout=60), 'ORACLE_AUTHENTICATION_FAILED')
            with patch.dict(os.environ, {prefix + '_DSN': 'localhost:1/NOSUCHSERVICE'}):
                refused(lambda: bounded_run(example('inspect'), directory / 'baddsn', executable=interpreter, timeout=60), 'ORACLE_UNAVAILABLE', 'ORACLE_CALL_TIMEOUT')
            assert secret not in json.dumps(bad.to_dict())
            report['failureHandling'] = {'authenticationFailureRedacted': True, 'unreachableServerClassified': True}

            # Live state is never reused: the identical workflow re-executes on resume.
            cleanup(observe, directory)
            # Two scratch reports: each creates and drops its own tables, so a resume can only reuse by identity, never by state.
            graph = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'revenue', 'document': example('report-revenue')}, {'id': 'variant', 'document': example('report-variant')}]}
            first = workflow.execute(graph, directory / 'workflow', locations=locations, timeout=limit(240))
            assert workflow.verify(directory / 'workflow')['verified']
            second = workflow.execute(graph, directory / 'workflow', locations=locations, timeout=limit(240), resume=True)
            assert not any(j['reused'] for j in second['jobs']), 'a live database result was reused'
            report['workflow'] = {'status': first['status'], 'scratchReportsResumed': True, 'liveStateNeverReused': True}

            # An in-flight timeout must report every table it may have left behind (from the worker's synced journal).
            before = observe.exact(*OWNED_NAMES)
            assert not before, before
            reported, outcome = set(), 'completed'
            try:
                bounded_run(example('report-lines'), directory / 'timeout', executable=interpreter, timeout=0.5)
            except SchemaxisError as error:
                outcome = error.fault.code
                seen_by_run = error.fault.observed
                reported = set(seen_by_run.get('createdTables', [])) | ({seen_by_run['possiblyCreated']} if seen_by_run.get('possiblyCreated') else set())
            left = set(observe.tables(*OWNED_NAMES))
            logical_left = {re.sub('_[0-9A-F]{5}$', '', n).lower() for n in left}
            assert not left or logical_left <= reported, ('tables left behind were not reported', left, reported)
            report['timeout'] = {'outcome': outcome, 'tablesLeftBehind': sorted(left), 'reported': sorted(reported)}
        finally:
            report['cleanup'] = cleanup(observe, directory)
            scratch.cleanup()
        forms = set()
        for suffix in ('_PASSWORD', '_DSN'):
            forms |= a.secret_forms(os.environ[prefix + suffix])
        leaked = [str(p.relative_to(directory)) for p in directory.rglob('*') if p.is_file() and any(f in p.read_bytes() for f in forms)]
        assert not leaked, 'credential values found in ' + ', '.join(leaked)
        report['credentialValuesAbsentFromEvidence'] = True
        if args.register:
            register(directory / 'kit' / 'qualification.json')
        report['verified'] = bool(report['native']['verified'])
    finally:
        if report.get('preflight') == 'passed' and 'cleanup' not in report:
            report['cleanup'] = cleanup(observe, directory)         # a failure before the main block must not leave kit tables behind
        scratch.cleanup()
        atomic_json(directory / 'acceptance.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
