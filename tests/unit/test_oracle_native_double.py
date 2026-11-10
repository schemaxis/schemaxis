"""Host orchestration, evidence verification and worker protocol, with test doubles.

A double is not an Oracle server. These tests prove how the host plans stages, refuses unsafe
or tampered evidence and maps native refusals; they say nothing about database behaviour.
Real-server behaviour is established only by tools/qualify_oracle.py against a live database.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptors.oracle import adaptor, model, native_worker as worker, planning, reference, sql
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.errors import fail

try:
    from test_oracle import FIXTURES, ROOT, data_for, example, fake_dictionary, renamed
except ImportError:  # run as a package
    from tests.unit.test_oracle import FIXTURES, ROOT, data_for, example, fake_dictionary, renamed

PASSWORD = 'Sentinel-Passw0rd-Value'
DSN = 'db.example.invalid:1521/SENTINELSERVICE'
USER = 'tester'


def native_cell(kind, value):
    if value is None:
        return None
    if kind == 'number':
        return format(value, 'f')
    if kind in ('date', 'timestamp', 'timestampTz'):
        return sql.bind_text(kind, model.canonical(kind, value))
    return value.hex() if kind == 'raw' else value


def table_spec(table, rows):
    kinds = {c['name']: c['type'] for c in table['columns']}
    ordered = sorted(rows, key=lambda r: tuple(model.sort_key(kinds[k], r[k]) for k in table['primaryKey']))
    return {'columns': [c['name'] for c in table['columns']], 'rows': [[native_cell(c['type'], r[c['name']]) for c in table['columns']] for r in ordered]}


class ProspectiveMutation(unittest.TestCase):
    def inputs(self, amount='25'):
        from test_oracle import existing_state
        document = example('mutate-existing')
        document['transaction']['steps'][0]['computed'][0]['arguments'][1]['literal']['value'] = amount
        p = adaptor.plan(document)
        state = existing_state(p)
        outputs = {'base:' + t['name']: table_spec(t, state[t['name']]) for t in p['tables']}
        return p, outputs

    def test_fractional_external_assignment_is_refused_before_any_mutation(self):
        p, outputs = self.inputs('0.015')
        with self.assertRaises(worker.Refusal) as caught:
            worker.validate_transaction({'plan': p}, outputs)
        self.assertEqual(caught.exception.code, 'ORACLE_VALUE_NOT_STORABLE')
        self.assertTrue(caught.exception.details['databaseTouched'])
        self.assertFalse(caught.exception.details['mutationStarted'])

    def test_native_discrepancy_is_refused_before_commit(self):
        p, outputs = self.inputs()
        worker.validate_transaction({'plan': p}, outputs)
        from test_oracle import existing_state
        _, final = reference.simulate(p, existing_state(p))
        outputs.update({'view:' + t['name']: table_spec(t, final[t['name']]) for t in p['tables']})
        worker.validate_transaction({'plan': p, 'final': True}, outputs)
        outputs['view:accounts']['rows'][0][2] = '74.99'
        with self.assertRaises(worker.Refusal) as caught:
            worker.validate_transaction({'plan': p, 'final': True}, outputs)
        self.assertEqual(caught.exception.code, 'ORACLE_PRECOMMIT_MISMATCH')

    def test_effect_boundary_refuses_before_dml_and_records_the_mechanism(self):
        from types import SimpleNamespace
        step = {'id': 'effect-boundary', 'kind': 'boundary', 'queries': {}}
        session = SimpleNamespace(driver=object())
        for kind in ('triggers', 'virtualColumns', 'defaults', 'indexes', 'policies', 'referenceGrants', 'columnReferenceGrants', 'incomingActions'):
            with self.subTest(kind=kind), patch.object(worker, 'dictionary', return_value={kind: {'columns': ['name'], 'rows': [['unsafe']]}}):
                with self.assertRaises(worker.Refusal) as caught:
                    worker.execute_step(session, object(), step, {})
                self.assertEqual(caught.exception.code, 'ORACLE_UNDECLARED_EFFECTS')
                self.assertFalse(caught.exception.details['mutationStarted'])
        with patch.object(worker, 'dictionary', return_value={'triggers': {'columns': ['name'], 'rows': []}}):
            self.assertTrue(worker.execute_step(session, object(), step, {})['validated'])

    def test_deferred_segment_serialization_conflict_has_a_specific_fault(self):
        self.assertEqual(worker.FAULT_CODES[8177], 'ORACLE_SERIALIZATION_CONFLICT')


class FakeOracle:
    """Stands in for the worker process: writes the files a real stage would, computed by the reference."""

    def __init__(self, existing=(), managed=True, major=23, charset='AL32UTF8', thin=True, fault=None, leak=None, after_tamper=None, drifted=None, reverse=False):
        self.reverse = reverse
        self.existing, self.managed, self.major, self.charset, self.thin = list(existing), managed, major, charset, thin
        self.fault, self.leak, self.after_tamper, self.drifted = fault, leak, after_tamper, drifted
        self.stages = []

    def __call__(self, command, directory, stage, timeout, environment=None):
        directory = Path(directory)
        self.stages.append(stage)
        p = planning.plan_document(adaptor.read(directory, 'authored.json'))
        data = adaptor.reload_data(directory, p)
        for table in p['tables']:
            if table['external']:
                source = {'path': str(FIXTURES / (table['name'] + '.json')), 'format': 'json'}
                data[table['name']] = reference.parse_source({**table, 'source': source}, Path(source['path']).read_bytes(), '$')
        atomic_json(directory / (stage + '-submission.json'), {'nativeCommand': list(map(str, command)), 'exitCode': 0})
        (directory / (stage + '.stdout')).write_bytes(b'')
        (directory / (stage + '.stderr')).write_bytes(self.leak.encode() if self.leak and stage == 'apply' else b'')
        if self.fault and self.fault['stage'] == stage:
            if 'partial' in self.fault:
                atomic_json(directory / (stage + '-partial.json'), self.fault['partial'])
            if 'journal' in self.fault:
                (directory / (stage + '-journal.jsonl')).write_text(''.join(json.dumps(r) + '\n' for r in self.fault['journal']))
            if 'raise' in self.fault:                 # the host killed the worker: no fault file, no partial result
                fail(self.fault['raise'], 'the worker was interrupted', stage)
            atomic_json(directory / (stage + '-fault.json'), {'code': self.fault['code'], 'message': self.fault.get('message', 'refused'), 'location': stage, 'details': self.fault.get('details', {})})
            fail('RUNNER_FAILED', 'native job failed', stage)
        getattr(self, stage)(directory, p, data)

    def tables(self, p, names):
        return [t for t in p['tables'] if t['name'] in names]

    def dictionary(self, tables, managed):
        raw = fake_dictionary(tables, managed)
        if self.drifted and raw['columns']['rows']:
            raw['columns']['rows'][0][8] = 'Y'
        return raw

    def identify(self, directory, p, data):
        existing = self.existing if p['operation'] != 'inspect' else [t['name'] for t in p['tables']]
        raw = self.dictionary(self.tables(p, existing), self.managed)
        atomic_json(directory / 'identify.json', {
            'driver': {'name': 'python-oracledb', 'version': '3.0.0', 'thin': self.thin}, 'server': {'version': '23.26.3.0.0', 'major': self.major, 'banner': 'Test banner'},
            'session': {'schema': USER.upper(), 'container': 'TESTPDB', 'characterSet': self.charset}, 'catalog': raw})

    def final_state(self, p, data):
        if p['operation'] != 'mutate':
            return data, None
        results, final = reference.simulate(p, data)
        return (final if p['transaction']['finish'] == 'commit' else data), (results, final)

    def apply(self, directory, p, data):
        program = adaptor.read(directory, 'program-apply.json')
        state, simulated = self.final_state(p, data)
        by_name = {t['name']: t for t in p['tables']}
        outputs, steps = {}, []
        for step in program['steps']:
            entry = {'id': step['id'], 'kind': step['kind']}
            if step['kind'] in ('boundary', 'validate'):
                entry['validated'] = True
            if step['kind'] == 'boundary':
                outputs[step['id']] = {key: {'columns': [], 'rows': []} for key in step['queries']}
            if step['kind'] == 'ddl':
                entry['committed'] = True
            if step['id'].startswith('load:'):
                entry['rows'] = len(step['rows'])
            if step['id'].startswith('step:') and simulated and 'rows' in simulated[0][int(step['id'][5:])]:
                entry['rows'] = simulated[0][int(step['id'][5:])]['rows']
            if step['id'] == 'report':
                rows, kinds = reference.run_report(p['report'], data)
                native_rows = [[native_cell(k, v) for k, v in zip(kinds, r)] for r in rows]
                outputs['report'] = {'columns': [o['name'] for o in p['report']['outputs']], 'rows': native_rows[::-1] if self.reverse else native_rows}
            elif step['kind'] == 'observe':
                shown = data if step['id'] in ('before', 'during') else state
                outputs[step['id']] = {t: table_spec(by_name[t], shown[t]) for t in step['queries']}
            elif step['id'].startswith('external:'):
                outputs[step['id']] = table_spec(by_name[step['id'][9:]], data[step['id'][9:]])
            elif step['id'].startswith('view:'):
                name = step['id'][5:]
                outputs[step['id']] = table_spec(by_name[name], simulated[1][name])
            steps.append(entry)
        atomic_json(directory / 'apply.json', {'status': 'succeeded', 'steps': steps, 'outputs': outputs, 'created': [s['creates'] for s in program['steps'] if s.get('creates')]})

    def readback(self, directory, p, data):
        program = adaptor.read(directory, 'program-readback.json')
        state, _ = self.final_state(p, data) if not (self.fault and self.fault['stage'] == 'apply') else (data, None)
        if self.after_tamper:
            state = self.after_tamper(copy.deepcopy(state))
        names = [t['name'] for t in p['tables']]
        if p['operation'] == 'inspect':
            raw = self.dictionary(self.tables(p, names), self.managed)
        else:
            # Scratch tables exist under run-unique physical names; the host maps them back to the declared names.
            names = adaptor.physical_names(p, adaptor.read(directory, 'native-config.json')['runId'])
            raw = fake_dictionary(renamed(p['tables'], names), True)
        by_name = {t['name']: t for t in p['tables']}
        atomic_json(directory / 'readback.json', {'catalog': raw, 'tables': {n: table_spec(by_name[n], state[n]) for n in program['tables']},
                                                  'cleanup': [{'table': c['table'], 'dropped': True, 'reason': 'dropped'} for c in program['cleanup']]})


def forbid_host_effects(case):
    """No test in this module may start a host subprocess or open a network connection."""
    for target in ('subprocess.Popen', 'socket.socket.connect', 'socket.create_connection'):
        patcher = patch(target, side_effect=AssertionError('a test double must not reach ' + target))
        patcher.start()
        case.addCleanup(patcher.stop)


class Base(unittest.TestCase):
    def setUp(self):
        forbid_host_effects(self)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.counter = 0
        patcher = patch.dict(os.environ, {'SCHEMAXIS_ORACLE_FREE_LOCAL_USER': USER, 'SCHEMAXIS_ORACLE_FREE_LOCAL_PASSWORD': PASSWORD, 'SCHEMAXIS_ORACLE_FREE_LOCAL_DSN': DSN})
        patcher.start()
        self.addCleanup(patcher.stop)

    def fault(self, action, code):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    def run_with(self, document, fake):
        """Return (directory, action); the double is patched for the whole duration of the action, not only its creation."""
        self.counter += 1
        directory = Path(self.temp.name) / f'run{self.counter}'

        def action():
            with patch.object(adaptor, 'execute', fake):
                return adaptor.run(document, directory, executable=sys.executable, timeout=60)
        return directory, action

    def succeed(self, name, fake=None, edit=None):
        document = example(name)
        if edit:
            edit(document)
        fake = fake or FakeOracle()
        directory, action = self.run_with(document, fake)
        return directory, action(), fake

    def refresh(self, directory):
        receipt = adaptor.read(directory, 'verification.json')
        p = planning.plan_document(adaptor.read(directory, 'authored.json'))
        receipt['evidence'] = {n: adaptor.digest(directory, n) for n in receipt['evidence'] if (directory / n).is_file()}
        for item in receipt['artifacts']:
            item['sha256'] = adaptor.digest(directory, Path(item['file']).name)
        atomic_json(directory / 'verification.json', receipt)


class SuccessfulRuns(Base):
    def test_report_publishes_verified_exact_rows_and_verify_repeats_it(self):
        directory, result, fake = self.succeed('report-revenue')
        self.assertEqual((result['verified'], result['status'], result['operation']), (True, 'succeeded', 'report'))
        document = json.loads((directory / 'result.json').read_text())
        self.assertEqual(adaptor.read(directory, 'report.json')['rows'], [['north', '3', '350.5'], ['south', '1', '80'], [None, '0', None]])
        self.assertEqual((directory / 'report.csv').read_text(), 'region,orders,revenue\nnorth,3,350.5\nsouth,1,80\n\\N,0,\\N\n')
        self.assertEqual(fake.stages, ['identify', 'apply', 'readback'])
        self.assertTrue(adaptor.verify(directory)['verified'])
        self.assertIn('Oracle Database 23.26.3.0.0', result['runtime'])
        self.assertEqual(document['status'], 'succeeded')

    def test_normal_identity_equal_to_the_user_name_does_not_trigger_the_credential_scan(self):
        directory, result, _ = self.succeed('report-revenue')
        self.assertEqual(adaptor.read(directory, 'identify.json')['session']['schema'], USER.upper())
        self.assertTrue(result['verified'])
        for path in directory.rglob('*'):
            if path.is_file():
                content = path.read_bytes()
                self.assertNotIn(PASSWORD.encode(), content)
                self.assertNotIn(DSN.encode(), content)

    def test_load_publishes_row_accounting_and_typed_csv(self):
        directory, _, fake = self.succeed('load')
        summary = adaptor.read(directory, 'load-summary.json')
        self.assertEqual([(t['name'], t['rows']) for t in summary['tables']], [('customers', 4), ('orders', 5), ('order_lines', 4)])
        lines = (directory / 'table-order_lines.csv').read_text().splitlines()
        self.assertEqual(lines[0], 'id,order_id,sku,quantity,unit_price,packed_at')
        self.assertEqual(lines[2], '101,10,B-2,1,50,2026-01-06T11:30:00.5+01:00')
        self.assertEqual(lines[3], '102,11,A-1,10,25.04,\\N')
        program = adaptor.read(directory, 'program-apply.json')
        self.assertEqual([s['id'] for s in program['steps'][:3]], ['create:customers', 'comment:customers', 'create:orders'])
        # The seed commit is flagged final: a lost connection there is an unknown outcome, never a rerun instruction.
        self.assertEqual(program['steps'][-1], {'id': 'commit:seed', 'kind': 'control', 'action': 'commit', 'final': True})
        self.assertEqual(adaptor.read(directory, 'program-readback.json')['cleanup'], [])

    def test_scratch_tables_are_dropped_children_first_when_not_retained(self):
        directory, _, _ = self.succeed('report-lines')
        cleanup = adaptor.read(directory, 'program-readback.json')['cleanup']
        suffix = adaptor.read(directory, 'native-config.json')['runId'][:5].upper()
        self.assertEqual([c['table'] for c in cleanup], [f'ORDER_LINES_{suffix}', f'ORDERS_{suffix}', f'CUSTOMERS_{suffix}'])
        self.assertEqual(adaptor.read(directory, 'report.json')['rows'][0], ['11', '1', '10', '250.4', '1'])

    def test_transactions_publish_outcome_and_final_state(self):
        directory, _, _ = self.succeed('mutate-transfer')
        self.assertEqual(adaptor.read(directory, 'transaction.json')['outcome'], 'committed')
        self.assertEqual(adaptor.read(directory, 'state-after.json')['tables']['accounts']['rows'][4], ['5', 'erin', '1'])
        directory, _, _ = self.succeed('mutate-rollback')
        self.assertEqual(adaptor.read(directory, 'transaction.json')['outcome'], 'rolledBack')
        self.assertEqual(len(adaptor.read(directory, 'state-after.json')['tables']['accounts']['rows']), 3)
        directory, _, _ = self.succeed('mutate-savepoint')
        program = adaptor.read(directory, 'program-apply.json')
        self.assertEqual(program['steps'][program['steps'].index(next(s for s in program['steps'] if s['id'] == 'isolation'))]['action'], 'serializable')
        self.assertEqual([s['id'] for s in program['steps'] if s['kind'] == 'observe'], ['before', 'during', 'after'])

    def test_json_number_exchange_is_refused_when_not_exact(self):
        def edit(document):
            document['report']['numbers'] = 'jsonNumber'
        directory, _, _ = self.succeed('report-revenue', edit=edit)
        self.assertEqual(adaptor.read(directory, 'report.json')['rows'][0], ['north', 3, 350.5])
        self.assertEqual(adaptor.json_cell('number', model.Decimal('0.5'), 'jsonNumber', '$'), 0.5)
        self.assertEqual(adaptor.json_cell('number', model.Decimal('-1024'), 'jsonNumber', '$'), -1024)
        self.assertIsNone(adaptor.exact_float(model.Decimal('0.1')))                       # 0.1 has no exactly equal double
        self.assertEqual(adaptor.exact_float(model.Decimal('0.1000000000000000055511151231257827021181583404541015625')), 0.1)
        self.fault(lambda: adaptor.json_cell('number', model.Decimal('0.1'), 'jsonNumber', '$'), 'ORACLE_LOSSY_NUMBER')
        self.fault(lambda: adaptor.json_cell('number', model.Decimal('0.1000000000000000055511151231257827'), 'jsonNumber', '$'), 'ORACLE_LOSSY_NUMBER')

    def test_unresolved_inspect_drift_and_snapshot_digest(self):
        document = example('inspect')
        document['tables'] = example('load')['tables']
        for table in document['tables']:
            table.pop('source')
        directory, _, _ = self.succeed('inspect', edit=lambda d: d.update(tables=document['tables'], inspection={'kinds': ['tables'], 'names': []}))
        snapshot = adaptor.read(directory, 'snapshot.json')
        self.assertEqual(snapshot['drift'], [])
        self.assertEqual(len(snapshot['digest']), 64)
        self.assertEqual([t['name'] for t in snapshot['snapshot']['tables']], ['customers', 'orders', 'order_lines'])
        fake = FakeOracle(drifted=True)
        directory, action = self.run_with({**example('inspect'), 'tables': document['tables'], 'inspection': {'kinds': ['tables'], 'names': []}}, fake)
        fault = self.fault(action, 'ORACLE_DRIFT')
        self.assertEqual(fault.observed['drift'][0]['difference'], 'columns')
        self.assertTrue((directory / 'snapshot.json').is_file())
        document['inspection'] = {'kinds': ['tables'], 'names': [], 'drift': 'report'}
        directory, action = self.run_with({**example('inspect'), 'tables': document['tables'], 'inspection': document['inspection']}, FakeOracle(drifted=True))
        self.assertTrue(action()['verified'])
        self.assertEqual(adaptor.read(directory, 'snapshot.json')['drift'][0]['table'], 'customers')


class RefusalsBeforeChange(Base):
    def planned(self, name='report-revenue'):
        return planning.plan_document(example(name))

    def test_a_taken_table_name_is_refused_and_nothing_is_ever_replaced_or_dropped(self):
        document = example('report-revenue')
        document['setup'] = {'retain': True}                 # retained tables keep their declared names, so a taken name is a conflict
        for managed in (True, False):
            fake = FakeOracle(existing=['customers'], managed=managed)
            directory, action = self.run_with(document, fake)
            self.assertEqual(self.fault(action, 'ORACLE_OBJECT_EXISTS').observed['table'], 'customers')
            self.assertEqual(fake.stages, ['identify'])
            self.assertFalse((directory / 'program-apply.json').exists())
        self.fault(lambda: planning.plan_document({**document, 'setup': {'existing': 'replace'}}), 'UNKNOWN_ARGUMENT')
        # A scratch run never collides with, replaces or drops a same-named table that is already there.
        fake = FakeOracle(existing=['customers', 'orders'], managed=False)
        directory, _, fake = self.succeed('report-revenue', fake)
        self.assertEqual(fake.stages, ['identify', 'apply', 'readback'])
        suffix = adaptor.read(directory, 'native-config.json')['runId'][:5]
        self.assertTrue(all(f'_{suffix}' in c['table'].lower() for c in adaptor.read(directory, 'program-readback.json')['cleanup']))
        directory, _, _ = self.succeed('report-revenue')
        apply_steps = adaptor.read(directory, 'program-apply.json')['steps']
        # Decode the structured program: no step of any kind drops anything, and every DDL step creates or marks a declared table.
        self.assertEqual([s['id'] for s in apply_steps if s['kind'] == 'ddl'], ['create:customers', 'comment:customers', 'create:orders', 'comment:orders'])
        self.assertFalse([s for s in apply_steps if s['kind'] == 'ddl' and s['sql'].startswith('DROP')])
        readback = adaptor.read(directory, 'program-readback.json')
        run_id = adaptor.read(directory, 'native-config.json')['runId']
        suffix = run_id[:5]
        self.assertEqual([(c['table'], c['sql']) for c in readback['cleanup']],
                         [(f'ORDERS_{suffix}'.upper(), f'DROP TABLE "ORDERS_{suffix}" PURGE'.upper()), (f'CUSTOMERS_{suffix}'.upper(), f'DROP TABLE "CUSTOMERS_{suffix}" PURGE'.upper())])
        self.assertEqual(readback['marker']['value'], sql.run_marker(run_id))
        comments = [s['sql'] for s in apply_steps if s['id'].startswith('comment:')]
        self.assertTrue(all(c.endswith(f"IS '{sql.run_marker(run_id)}'") for c in comments), comments)
        self.assertTrue(all(f'_{suffix.upper()}"' in s['sql'].split(' (')[0] for s in apply_steps if s['id'].startswith('create:')))

    def test_every_run_binds_its_own_marker_so_another_runs_tables_are_never_cleaned_up(self):
        first, _, _ = self.succeed('report-revenue')
        second, _, _ = self.succeed('report-revenue')
        ids = [adaptor.read(d, 'native-config.json')['runId'] for d in (first, second)]
        self.assertNotEqual(*ids)
        self.assertRegex(ids[0], r'^[0-9a-f]{16}$')
        self.assertNotEqual(adaptor.read(first, 'program-readback.json')['marker'], adaptor.read(second, 'program-readback.json')['marker'])
        self.assertNotEqual(adaptor.read(first, 'program-apply.json'), adaptor.read(second, 'program-apply.json'))
        record = adaptor.read(first, 'native-config.json')
        record['runId'] = 'not-a-run-id'
        atomic_json(first / 'native-config.json', record)
        self.fault(lambda: adaptor.verify(first), 'VERIFICATION_FAILED')

    def test_cleanup_drops_only_tables_this_run_created(self):
        partial = {'status': 'running', 'steps': [], 'outputs': {}, 'created': ['customers'], 'attempted': 'orders'}
        fault = {'stage': 'apply', 'code': 'ORACLE_SERVER_ERROR', 'message': 'ORA-01950: no privileges', 'details': {'oracle': 'ORA-01950'}, 'partial': partial}
        directory, action = self.run_with(example('report-revenue'), FakeOracle(fault=fault))
        error = self.fault(action, 'ORACLE_SERVER_ERROR')
        self.assertEqual([c['table'] for c in adaptor.read(directory, 'program-readback.json')['cleanup']],
                         ['CUSTOMERS_' + adaptor.read(directory, 'native-config.json')['runId'][:5].upper()])
        self.assertEqual((error.observed['createdTables'], error.observed['possiblyCreated']), (['customers'], 'orders'))

    def test_unknown_commit_keeps_every_table_as_evidence(self):
        partial = {'status': 'unknown', 'steps': [], 'outputs': {}, 'created': ['accounts'], 'attempted': None}
        fault = {'stage': 'apply', 'code': 'ORACLE_COMMIT_OUTCOME_UNKNOWN', 'message': 'lost', 'details': {'resolution': {}}, 'partial': partial}
        directory, action = self.run_with(example('mutate-transfer'), FakeOracle(fault=fault))
        error = self.fault(action, 'ORACLE_COMMIT_OUTCOME_UNKNOWN')
        self.assertEqual(adaptor.read(directory, 'program-readback.json')['cleanup'], [])
        self.assertTrue(error.observed['tablesRetained'])
        self.assertIn('kept', error.observed['cleanupSkipped'])

    def test_a_retained_run_leaves_its_tables_after_a_failure(self):
        fault = {'stage': 'apply', 'code': 'ORACLE_SERVER_ERROR', 'message': 'x', 'details': {}, 'partial': {'created': ['customers', 'orders'], 'attempted': None}}
        document = example('report-revenue')
        document['setup'] = {'retain': True}
        directory, action = self.run_with(document, FakeOracle(fault=fault))
        error = self.fault(action, 'ORACLE_SERVER_ERROR')
        self.assertEqual(adaptor.read(directory, 'program-readback.json')['cleanup'], [])
        self.assertEqual((error.observed['tablesRetained'], error.observed['createdTables']), (True, ['customers', 'orders']))

    def test_external_tables_must_exist_and_match(self):
        document = example('report-revenue')
        for table in document['tables']:
            table['external'] = True
            table.pop('source')
        fake = FakeOracle(existing=[])
        self.fault(self.run_with(document, fake)[1], 'ORACLE_OBJECT_MISSING')
        fake = FakeOracle(existing=['customers', 'orders'], drifted=True)
        self.assertEqual(self.fault(self.run_with(document, fake)[1], 'ORACLE_DRIFT').observed['drift'][0]['table'], 'customers')
        self.assertEqual(fake.stages, ['identify'])
        directory, result, fake = self.succeed('report-revenue', FakeOracle(existing=['customers', 'orders']), edit=lambda d: [t.update(external=True) or t.pop('source') for t in d['tables']])
        self.assertTrue(result['verified'])

    def test_server_driver_and_character_set_gates(self):
        self.fault(self.run_with(example('report-revenue'), FakeOracle(charset='WE8MSWIN1252'))[1], 'ORACLE_UNSUPPORTED_CHARSET')
        self.fault(self.run_with(example('report-revenue'), FakeOracle(thin=False))[1], 'UNSUPPORTED_NATIVE_VERSION')
        flags = {'version': model.VERSION, 'operation': 'inspect', 'connection': {'profile': 'free_local'},
                 'tables': [{'name': 'flags', 'columns': [{'name': 'id', 'type': 'number', 'precision': 5, 'scale': 0}, {'name': 'flag', 'type': 'boolean', 'nullable': True}], 'primaryKey': ['id']}]}
        fake = FakeOracle(major=19)
        self.fault(self.run_with(flags, fake)[1], 'UNSUPPORTED_NATIVE_VERSION')
        self.assertEqual(fake.stages, ['identify'])

    def test_invalid_inputs_never_reach_the_database(self):
        document = example('report-revenue')
        document['tables'][1]['source']['path'] = str(Path(self.temp.name) / 'missing.json')
        fake = FakeOracle()
        self.fault(self.run_with(document, fake)[1], 'INVALID_ORACLE_SOURCE')
        self.assertEqual(fake.stages, [])
        document = example('mutate-violation')
        document['transaction']['enforcement'] = 'predict'
        fake = FakeOracle()
        fault = self.fault(self.run_with(document, fake)[1], 'ORACLE_CONSTRAINT_VIOLATION')
        self.assertEqual((fault.observed['predicted'], fault.observed['databaseTouched']), (True, False))
        self.assertEqual(fake.stages, [])
        self.fault(lambda: adaptor.run(example('inspect'), Path(self.temp.name) / 'nox', executable='relative-python'), 'INTERPRETER_NOT_FOUND')
        existing = Path(self.temp.name) / 'taken'
        existing.mkdir()
        self.fault(lambda: adaptor.run(example('inspect'), existing, executable=sys.executable), 'OUTPUT_EXISTS')


class NativeRefusals(Base):
    def test_constraint_refusal_reports_independently_verified_rollback(self):
        fault = {'stage': 'apply', 'code': 'ORACLE_CONSTRAINT_VIOLATION', 'message': 'ORA-00001: unique constraint violated', 'details': {'oracle': 'ORA-00001', 'constraint': 'unique', 'step': 'step:1', 'rolledBack': True}}
        directory, action = self.run_with(example('mutate-violation'), FakeOracle(fault=fault))
        error = self.fault(action, 'ORACLE_CONSTRAINT_VIOLATION')
        self.assertEqual((error.observed['rollbackVerified'], error.observed['oracle'], error.observed['predictedFailure']['errors']), (True, 'ORA-00001', [1]))
        self.assertEqual(adaptor.read(directory, 'result.json')['status'], 'failed')
        self.assertTrue((directory / 'readback.json').is_file())
        self.fault(lambda: adaptor.verify(directory), 'INCOMPLETE_EXECUTION')

        def altered(state):
            state['accounts'][0]['balance'] = model.Decimal(1)
            return state
        directory, action = self.run_with(example('mutate-violation'), FakeOracle(fault=fault, after_tamper=altered))
        self.assertFalse(self.fault(action, 'ORACLE_CONSTRAINT_VIOLATION').observed['rollbackVerified'])

    def test_stage_failures_map_to_stable_codes_with_recovery(self):
        for stage, code in (('identify', 'ORACLE_AUTHENTICATION_FAILED'), ('identify', 'ORACLE_CREDENTIALS_MISSING'), ('identify', 'ORACLE_DRIVER_UNAVAILABLE'),
                            ('apply', 'ORACLE_ROWCOUNT_MISMATCH'), ('apply', 'ORACLE_COMMIT_OUTCOME_UNKNOWN'), ('apply', 'ORACLE_OBJECT_EXISTS')):
            error = self.fault(self.run_with(example('mutate-transfer'), FakeOracle(fault={'stage': stage, 'code': code, 'details': {'resolution': {'before': 'state'}}}))[1], code)
            self.assertTrue(error.recovery)
            self.assertEqual(error.observed['stage'], stage)
        bad = FakeOracle(fault={'stage': 'identify', 'code': 'MADE_UP', 'details': {}})
        self.fault(self.run_with(example('report-revenue'), bad)[1], 'VERIFICATION_FAILED')

    def test_failed_commit_outcome_is_reported_not_replayed(self):
        fault = {'stage': 'apply', 'code': 'ORACLE_COMMIT_OUTCOME_UNKNOWN', 'message': 'connection lost', 'details': {'resolution': {'after': 'rows'}}}
        fake = FakeOracle(fault=fault)
        directory, action = self.run_with(example('mutate-transfer'), fake)
        error = self.fault(action, 'ORACLE_COMMIT_OUTCOME_UNKNOWN')
        self.assertIn('do not rerun', error.recovery)
        self.assertEqual(error.observed['resolution'], {'after': 'rows'})
        self.assertEqual(fake.stages.count('apply'), 1)


class AssignmentFit(Base):
    def document(self, literal='0.015', mode='predict', **column_change):
        document = example('mutate-transfer')
        document['transaction']['steps'] = document['transaction']['steps'][:1]
        document['transaction']['steps'][0]['computed'][0]['arguments'][1]['literal']['value'] = literal
        document['transaction']['enforcement'] = mode
        document['tables'][0]['columns'][2].update(column_change)
        return document

    def test_scale_loss_is_refused_before_the_database_under_either_enforcement_mode(self):
        for mode in ('predict', 'database'):
            fake = FakeOracle()
            directory, action = self.run_with(self.document(mode=mode), fake)
            fault = self.fault(action, 'ORACLE_VALUE_NOT_STORABLE')
            self.assertEqual((fault.observed['predicted'], fault.observed['databaseTouched'], fault.observed['reason'], fault.observed['column']), (True, False, 'scale', 'balance'))
            self.assertEqual(fake.stages, [])
            self.assertFalse((directory / 'identify.json').exists())
            self.assertTrue(fault.recovery)

    def test_an_explicit_rounding_policy_models_the_stored_value(self):
        directory, result, _ = self.succeed('mutate-transfer', edit=lambda d: (d['transaction'].update(steps=d['transaction']['steps'][:1]),
                                                                              d['transaction']['steps'][0]['computed'][0]['arguments'][1]['literal'].update(value='0.015'),
                                                                              d['tables'][0]['columns'][2].update(scalePolicy='round')))
        self.assertEqual(adaptor.read(directory, 'state-after.json')['tables']['accounts']['rows'][0], ['1', 'alice', '99.99'])

    def test_precision_overflow_is_predicted_as_ora_01438_and_must_match_under_database_enforcement(self):
        document = self.document(literal='100000000', mode='database')
        document['transaction']['steps'][0]['computed'][0]['function'] = 'multiply'
        fake = FakeOracle(fault={'stage': 'apply', 'code': 'ORACLE_CONSTRAINT_VIOLATION', 'message': 'ORA-01438', 'details': {'oracle': 'ORA-01438', 'constraint': 'precision', 'step': 'step:0'}})
        directory, action = self.run_with(document, fake)
        error = self.fault(action, 'ORACLE_CONSTRAINT_VIOLATION')               # predicted by the host and refused by the database
        self.assertEqual(error.observed['predictedFailure']['errors'], [1438])
        self.assertEqual(error.observed['rollbackVerified'], True)
        fake = FakeOracle(fault={'stage': 'apply', 'code': 'ORACLE_CONSTRAINT_VIOLATION', 'message': 'ORA-12899', 'details': {'oracle': 'ORA-12899', 'constraint': 'length', 'step': 'step:0'}})
        mismatch = self.fault(self.run_with(document, fake)[1], 'VERIFICATION_FAILED')
        self.assertIn('did not refuse as the independent reference predicted', mismatch.message)


class OutcomeReporting(Base):
    def test_database_enforcement_requires_the_predicted_step_code_and_error_number(self):
        def refusal(**details):
            return FakeOracle(fault={'stage': 'apply', 'code': details.pop('code', 'ORACLE_CONSTRAINT_VIOLATION'), 'message': 'refused', 'details': details})
        right = refusal(oracle='ORA-00001', constraint='unique', step='step:1')
        self.assertEqual(self.fault(self.run_with(example('mutate-violation'), right)[1], 'ORACLE_CONSTRAINT_VIOLATION').observed['rollbackVerified'], True)
        for wrong in (refusal(oracle='ORA-00001', constraint='unique', step='step:0'), refusal(oracle='ORA-02290', constraint='check', step='step:1'),
                      refusal(oracle='ORA-01403', step='step:1', code='ORACLE_ROWCOUNT_MISMATCH')):
            error = self.fault(self.run_with(example('mutate-violation'), wrong)[1], 'VERIFICATION_FAILED')
            self.assertEqual(error.observed['predicted']['step'], 1)
            self.assertIn('native', error.observed)

    def test_a_failure_after_the_work_completed_reports_what_the_database_holds(self):
        def corrupt(state):
            state['accounts'][0]['balance'] = model.Decimal('1')
            return state
        document = example('mutate-transfer')
        document['setup'] = {'retain': True}
        directory, action = self.run_with(document, FakeOracle(after_tamper=corrupt))
        error = self.fault(action, 'VERIFICATION_FAILED')
        self.assertEqual((error.observed['databaseWorkCompleted'], error.observed['outcome'], error.observed['tablesRetained'], error.observed['createdTables']), (True, 'committed', True, ['accounts']))
        self.assertIn('do not rerun blindly', error.recovery)
        directory, action = self.run_with(example('report-revenue'), FakeOracle(after_tamper=lambda state: {**state, 'customers': state['customers'][:1]}))
        error = self.fault(action, 'VERIFICATION_FAILED')
        self.assertEqual((error.observed['databaseWorkCompleted'], error.observed['tablesRetained']), (True, False))
        self.assertIn('scratch tables were dropped', error.recovery)

    def test_a_killed_worker_is_reported_from_its_journal_and_nothing_is_dropped(self):
        journal = [{'event': 'begin', 'id': 'create:customers', 'kind': 'ddl', 'creates': 'customers', 'action': None}, {'event': 'done', 'id': 'create:customers', 'kind': 'ddl', 'creates': 'customers', 'action': None},
                   {'event': 'begin', 'id': 'comment:customers', 'kind': 'ddl', 'creates': None, 'action': None}, {'event': 'done', 'id': 'comment:customers', 'kind': 'ddl', 'creates': None, 'action': None},
                   {'event': 'begin', 'id': 'create:orders', 'kind': 'ddl', 'creates': 'orders', 'action': None}]
        directory, action = self.run_with(example('report-revenue'), FakeOracle(fault={'stage': 'apply', 'raise': 'RUNNER_TIMED_OUT', 'journal': journal}))
        error = self.fault(action, 'RUNNER_TIMED_OUT')
        self.assertEqual((error.observed['outcomeUnknown'], error.observed['createdTables'], error.observed['possiblyCreated']), (True, ['customers'], 'orders'))
        self.assertEqual(adaptor.read(directory, 'program-readback.json')['cleanup'], [])
        self.assertIn('kept as evidence', error.observed['cleanupSkipped'])

    def test_a_commit_in_flight_when_the_worker_died_is_unknown(self):
        journal = [{'event': 'begin', 'id': 'finish', 'kind': 'control', 'creates': None, 'action': 'commit'}]
        directory, action = self.run_with(example('mutate-transfer'), FakeOracle(fault={'stage': 'apply', 'raise': 'RUNNER_CANCELLED', 'journal': journal}))
        error = self.fault(action, 'RUNNER_CANCELLED')
        self.assertEqual((error.observed['inFlight'], error.observed['outcomeUnknown']), ('finish', True))

    def test_the_seed_commit_is_treated_like_any_other_commit(self):
        directory, _, _ = self.succeed('load')
        steps = adaptor.read(directory, 'program-apply.json')['steps']
        self.assertEqual(next(s for s in steps if s['id'] == 'commit:seed')['final'], True)

    def test_a_report_reads_external_rows_and_the_result_in_one_query_only_serializable_transaction(self):
        document = example('report-revenue')
        for table in document['tables']:
            table['external'] = True
            table.pop('source')
        fake = FakeOracle(existing=['customers', 'orders'])
        directory, action = self.run_with(document, fake)
        action()
        steps = adaptor.read(directory, 'program-apply.json')['steps']
        self.assertEqual([s['id'] for s in steps], ['commit:seed', 'snapshot', 'external:customers', 'external:orders', 'report', 'snapshot:end'])
        # Oracle's READ ONLY mode fails with ORA-01466 straight after DDL; a SERIALIZABLE transaction gives the same stable snapshot.
        self.assertEqual((steps[1]['action'], steps[-1]['action']), ('serializable', 'commit'))
        self.assertNotIn('readonly', json.dumps(steps))
        self.assertEqual([s['sql'].split(' FROM ')[1].split(' ')[0] for s in steps if s['id'].startswith('external:')], ['"CUSTOMERS"', '"ORDERS"'])
        snapshot = steps[1:]
        adaptor.query_only(snapshot)                                          # only reads and the transaction's own control steps follow the seed commit
        for forbidden in ({'id': 'x', 'kind': 'dml', 'sql': 'DELETE FROM "T"', 'binds': []}, {'id': 'x', 'kind': 'insert', 'sql': 'INSERT INTO "T" ("A") VALUES (:1)'},
                          {'id': 'x', 'kind': 'ddl', 'sql': 'DROP TABLE "T" PURGE'}, {'id': 'x', 'kind': 'control', 'action': 'rollbackTo', 'name': 'a'},
                          {'id': 'x', 'kind': 'query', 'sql': 'DELETE FROM "T"'}):
            with self.assertRaises(ValueError):
                adaptor.query_only(snapshot + [forbidden])
        report = planning.plan_document(example('report-lines'))
        scratch = adaptor.apply_program(report, data_for(report), 'a' * 16)['steps']
        after_seed = scratch[[s['id'] for s in scratch].index('commit:seed') + 1:]
        self.assertEqual([s['id'] for s in after_seed], ['snapshot', 'report', 'snapshot:end'])
        self.assertTrue(all(s['kind'] in ('control', 'query') for s in after_seed))

    def test_a_result_in_the_wrong_native_order_is_refused_even_when_the_rows_are_right(self):
        error = self.fault(self.run_with(example('report-revenue'), FakeOracle(reverse=True))[1], 'VERIFICATION_FAILED')
        self.assertIn('does not follow the declared order', error.message)
        self.assertTrue(error.observed['databaseWorkCompleted'])


class CompletionBoundaries(Base):
    def retained(self, finish='commit'):
        document = example('mutate-transfer')
        document['setup'] = {'retain': True}
        document['transaction']['finish'] = finish
        return document

    def assert_completed(self, directory, fault, outcome='committed'):
        self.assertTrue(fault.observed['databaseTouched'])
        self.assertTrue(fault.observed['databaseWorkCompleted'])
        self.assertEqual(fault.observed['outcome'], outcome)
        self.assertIn('do not rerun blindly', fault.recovery)
        saved = adaptor.read(directory, 'result.json')
        self.assertEqual(saved['status'], 'failed')
        self.assertEqual(saved['fault']['observed']['outcome'], outcome)
        self.assertTrue(saved['fault']['observed']['databaseTouched'])

    def test_publication_cancellation_keeps_commit_and_rollback_facts(self):
        for finish, outcome in (('commit', 'committed'), ('rollback', 'rolledBack')):
            directory, action = self.run_with(self.retained(finish), FakeOracle())
            with patch.object(adaptor, 'cancellation_requested', return_value=True):
                fault = self.fault(action, 'RUNNER_CANCELLED')
            self.assert_completed(directory, fault, outcome)

    def test_final_deadline_preserves_the_completed_commit(self):
        directory, action = self.run_with(self.retained(), FakeOracle())
        now = [0.0]
        original = adaptor.verify
        def verified(*args, **kwargs):
            result = original(*args, **kwargs)
            now[0] = 1000.0
            return result
        with patch.object(adaptor.time, 'monotonic', side_effect=lambda: now[0]), patch.object(adaptor, 'verify', side_effect=verified):
            fault = self.fault(action, 'RUNNER_TIMED_OUT')
        self.assert_completed(directory, fault)

    def test_readback_analysis_verification_and_scan_failures_keep_commit_facts(self):
        for stage in ('readback', 'analyse', 'verify', 'scan_secrets'):
            with self.subTest(stage=stage):
                fake = FakeOracle(fault={'stage':'readback','code':'ORACLE_UNAVAILABLE'}) if stage == 'readback' else FakeOracle()
                directory, action = self.run_with(self.retained(), fake)
                if stage == 'readback':
                    fault = self.fault(action, 'ORACLE_UNAVAILABLE')
                else:
                    original = getattr(adaptor, stage)
                    called = [False]
                    def refuse_once(*args, **kwargs):
                        if not called[0]:
                            called[0] = True
                            fail('VERIFICATION_FAILED', 'injected post-native refusal')
                        return original(*args, **kwargs)
                    with patch.object(adaptor, stage, side_effect=refuse_once):
                        fault = self.fault(action, 'VERIFICATION_FAILED')
                self.assert_completed(directory, fault)

    def test_failure_of_the_success_status_scan_is_rewritten_and_rescanned_with_commit_facts(self):
        directory, action=self.run_with(self.retained(),FakeOracle())
        original=adaptor.scan_secrets
        calls=[0]
        def final_scan(*args,**kwargs):
            calls[0]+=1
            if calls[0]==2:
                model.problem('ORACLE_CREDENTIAL_LEAK','final scan refused','$',files=[1])
            return original(*args,**kwargs)
        with patch.object(adaptor,'scan_secrets',side_effect=final_scan):
            fault=self.fault(action,'ORACLE_CREDENTIAL_LEAK')
        self.assert_completed(directory,fault)
        self.assertEqual(calls[0],3)

    def test_publication_and_final_status_io_errors_do_not_escape_as_raw_exceptions(self):
        original_bytes, original_json = Path.write_bytes, adaptor.atomic_json
        for stage in ('publication', 'status'):
            directory, action = self.run_with(self.retained(), FakeOracle())
            def write_bytes(path, content):
                if stage == 'publication' and path.name == 'transaction.json':
                    raise OSError('injected publication write refusal')
                return original_bytes(path, content)
            def write_json(path, content):
                if stage == 'status' and Path(path).name == 'result.json' and content.get('status') == 'succeeded':
                    raise OSError('injected status write refusal')
                return original_json(path, content)
            with patch.object(Path, 'write_bytes', write_bytes), patch.object(adaptor, 'atomic_json', side_effect=write_json):
                fault = self.fault(action, 'NATIVE_EXECUTION_FAILED')
            self.assert_completed(directory, fault)

    def test_unwritable_failure_status_keeps_the_structured_database_outcome(self):
        directory, action = self.run_with(self.retained(), FakeOracle())
        original = adaptor.atomic_json
        def refuse_status(path, value):
            if Path(path).name == 'result.json' and value.get('status') != 'incomplete':
                raise OSError('status writer unavailable')
            return original(path, value)
        with patch.object(adaptor, 'cancellation_requested', return_value=True), patch.object(adaptor, 'atomic_json', side_effect=refuse_status):
            fault = self.fault(action, 'RUNNER_CANCELLED')
        self.assertEqual(fault.observed['outcome'], 'committed')
        self.assertTrue(fault.observed['databaseTouched'])
        self.assertTrue(fault.observed['statusWriteFailed'])
        self.assertEqual((directory / 'result.json').read_bytes(), b'')

    def test_a_journalled_finish_after_worker_loss_preserves_the_known_commit(self):
        journal = [{'event':'begin','id':'finish','kind':'control','creates':None,'action':'commit'},
                   {'event':'done','id':'finish','kind':'control','creates':None,'action':'commit'}]
        fake = FakeOracle(fault={'stage':'apply','raise':'RUNNER_CANCELLED','journal':journal})
        directory, action = self.run_with(self.retained(), fake)
        fault = self.fault(action, 'RUNNER_CANCELLED')
        self.assert_completed(directory, fault)
        self.assertFalse(fault.observed.get('outcomeUnknown',False))

    def test_a_post_finish_observer_failure_cannot_relabel_a_commit_as_rollback(self):
        class AfterFinish(FakeOracle):
            def apply(self, directory, p, data):
                super().apply(directory, p, data)
                native = adaptor.read(directory, 'apply.json')
                end = next(i for i, e in enumerate(native['steps']) if e['id'] == 'finish')
                native['steps'] = native['steps'][:end + 1]
                atomic_json(directory / 'apply-partial.json', native)
                (directory / 'apply.json').unlink()
                atomic_json(directory / 'apply-fault.json', {'code':'ORACLE_UNAVAILABLE', 'message':'post-finish observer failed', 'details':{'rolledBack':True,'oracle':'ORA-03113'}})
                fail('RUNNER_FAILED', 'worker failed')
        directory, action = self.run_with(self.retained(), AfterFinish())
        fault = self.fault(action, 'ORACLE_UNAVAILABLE')
        self.assert_completed(directory, fault)
        self.assertFalse(fault.observed['rolledBack'])
        self.assertTrue(fault.observed['sessionRollbackCompleted'])
        self.assertFalse(fault.observed['rollbackVerified'])

    def test_acknowledged_report_seed_is_preserved_without_claiming_query_completion(self):
        class AfterSeed(FakeOracle):
            def apply(self,directory,p,data):
                super().apply(directory,p,data)
                native=adaptor.read(directory,'apply.json')
                end=next(i for i,e in enumerate(native['steps']) if e['id']=='commit:seed')
                native['steps']=native['steps'][:end+1]
                atomic_json(directory/'apply-partial.json',native)
                (directory/'apply.json').unlink()
                atomic_json(directory/'apply-fault.json',{'code':'ORACLE_SERVER_ERROR','message':'report query refused after seed commit','details':{'rolledBack':True}})
                fail('RUNNER_FAILED','worker failed')
        document=example('report-revenue');document['setup']={'retain':True}
        directory,action=self.run_with(document,AfterSeed())
        fault=self.fault(action,'ORACLE_SERVER_ERROR')
        self.assertEqual(fault.observed['outcome'],'seed rows committed; report incomplete')
        self.assertTrue(fault.observed['seedCommitCompleted'])
        self.assertFalse(fault.observed['databaseWorkCompleted'])
        self.assertFalse(fault.observed['nativeApplyCompleted'])
        self.assertFalse(fault.observed['rolledBack'])
        self.assertTrue(fault.observed['sessionRollbackCompleted'])
        self.assertIn('do not rerun blindly',fault.recovery)
        self.assertEqual(adaptor.read(directory,'result.json')['fault']['observed']['outcome'],'seed rows committed; report incomplete')

    def test_journalled_load_seed_commit_survives_lost_worker_result(self):
        journal=[{'event':'done','id':'commit:seed','kind':'control','creates':None,'action':'commit'}]
        document=example('load');document['setup']={'retain':True}
        directory,action=self.run_with(document,FakeOracle(fault={'stage':'apply','raise':'RUNNER_CANCELLED','journal':journal}))
        fault=self.fault(action,'RUNNER_CANCELLED')
        self.assert_completed(directory,fault,'seed rows committed')
        self.assertTrue(fault.observed['seedCommitCompleted'])

    def test_unknown_outcomes_are_preserved_when_a_later_secret_scan_refuses(self):
        fake = FakeOracle(fault={'stage':'apply','code':'ORACLE_COMMIT_OUTCOME_UNKNOWN','message':'exposed ' + PASSWORD,'details':{'outcomeUnknown':True,'outcome':'commit-outcome-unknown'}})
        directory, action = self.run_with(self.retained(), fake)
        fault = self.fault(action, 'ORACLE_CREDENTIAL_LEAK')
        self.assertTrue(fault.observed['outcomeUnknown'])
        self.assertEqual(fault.observed['outcome'], 'commit-outcome-unknown')
        self.assertNotIn(PASSWORD, json.dumps(fault.to_dict()))
        self.assertEqual(adaptor.read(directory,'result.json')['fault']['observed']['outcome'], 'commit-outcome-unknown')

    def test_inspection_cancellation_does_not_invent_seed_commits_or_require_setup(self):
        directory, action = self.run_with(example('inspect'), FakeOracle())
        with patch.object(adaptor, 'cancellation_requested', return_value=True):
            fault = self.fault(action, 'RUNNER_CANCELLED')
        self.assert_completed(directory, fault, 'read-only inspection completed')
        self.assertEqual(fault.observed['createdTables'], [])


class CredentialHandling(Base):
    def test_a_real_leak_fails_the_run_blanks_the_file_and_never_echoes_the_value(self):
        fake = FakeOracle(leak='password was ' + PASSWORD)
        directory, action = self.run_with(example('report-revenue'), fake)
        with self.assertRaises(SchemaxisError) as caught:
            action()
        error = caught.exception.fault
        self.assertEqual(error.code, 'ORACLE_CREDENTIAL_LEAK')
        self.assertTrue(error.observed['databaseWorkCompleted'])
        self.assertNotIn(PASSWORD, json.dumps(error.to_dict()))
        self.assertEqual((directory / 'apply.stderr').read_bytes(), b'')
        self.assertEqual(adaptor.read(directory, 'result.json')['status'], 'failed')
        self.assertNotIn(PASSWORD, (directory / 'result.json').read_text())

    def test_dsn_leak_is_also_refused(self):
        directory, action = self.run_with(example('report-revenue'), FakeOracle(leak='connecting to ' + DSN))
        self.fault(action, 'ORACLE_CREDENTIAL_LEAK')

    def test_short_credentials_are_refused_before_any_native_work_not_silently_waived(self):
        for variable in ('PASSWORD', 'DSN'):
            with patch.dict(os.environ, {f'SCHEMAXIS_ORACLE_FREE_LOCAL_{variable}': 'Zq9!x'}):
                fake = FakeOracle()
                directory, action = self.run_with(example('report-revenue'), fake)
                error = self.fault(action, 'ORACLE_CREDENTIAL_UNSCANNABLE')
                self.assertEqual(fake.stages, [])
                self.assertNotIn('Zq9!x', json.dumps(error.to_dict()))
                self.assertFalse((directory / 'identify.json').exists())
                self.assertEqual(adaptor.read(directory, 'result.json')['status'], 'failed')

    def test_every_encoded_form_of_a_secret_is_found_and_ordinary_data_is_not_blanked(self):
        import base64
        import urllib.parse
        secret = 'pä"ss\\word-12345'
        p = planning.plan_document(example('inspect'))
        forms = {'utf8': secret.encode(), 'utf16le': secret.encode('utf-16-le'), 'utf16be': secret.encode('utf-16-be'), 'json': json.dumps(secret).encode(),
                 'json-unescaped': json.dumps(secret, ensure_ascii=False).encode(), 'percent': urllib.parse.quote(secret, safe='').encode(),
                 'base64': base64.b64encode(secret.encode()), 'urlsafe-base64': base64.urlsafe_b64encode(secret.encode()), 'escape': secret.encode('unicode_escape')}
        with patch.dict(os.environ, {'SCHEMAXIS_ORACLE_FREE_LOCAL_PASSWORD': secret}):
            for name, content in forms.items():
                with tempfile.TemporaryDirectory() as temp:
                    (Path(temp) / 'evidence.bin').write_bytes(b'prefix ' + content + b' suffix')
                    (Path(temp) / 'rows.json').write_text(json.dumps([{'owner': USER, 'name': 'Zoë', 'note': 'password'}]))
                    error = self.fault(lambda: adaptor.scan_secrets(temp, p), 'ORACLE_CREDENTIAL_LEAK')
                    self.assertEqual(error.observed['files'], [1], name)
                    self.assertEqual((Path(temp) / 'rows.json').read_text(), json.dumps([{'owner': USER, 'name': 'Zoë', 'note': 'password'}]))
            with tempfile.TemporaryDirectory() as temp:
                (Path(temp) / 'clean.txt').write_text('no secret here')
                adaptor.scan_secrets(temp, p)

    def test_the_final_status_write_is_scanned_and_all_leaking_files_are_blanked(self):
        fault = {'stage': 'identify', 'code': 'ORACLE_SERVER_ERROR', 'message': 'driver said ' + PASSWORD, 'details': {}}
        directory, action = self.run_with(example('report-revenue'), FakeOracle(fault=fault))
        error = self.fault(action, 'ORACLE_CREDENTIAL_LEAK')
        self.assertTrue(error.observed['files'])
        self.assertTrue(all(type(n) is int for n in error.observed['files']))
        status = (directory / 'result.json').read_text()
        self.assertNotIn(PASSWORD, status)
        self.assertEqual(json.loads(status)['fault']['code'], 'ORACLE_CREDENTIAL_LEAK')
        for path in directory.rglob('*'):
            if path.is_file():
                self.assertNotIn(PASSWORD.encode(), path.read_bytes())

    def test_protocol_identifier_credentials_refuse_before_native_work_without_renaming_faults(self):
        for secret in ('ORACLE_CREDENTIAL_LEAK', 'databaseWorkCompleted', 'observed'):
            with self.subTest(secret=secret), patch.dict(os.environ, {'SCHEMAXIS_ORACLE_FREE_LOCAL_PASSWORD':secret}):
                fake=FakeOracle()
                directory, action=self.run_with(example('report-revenue'),fake)
                fault=self.fault(action,'INVALID_ORACLE_CONNECTION')
                self.assertEqual(fake.stages,[])
                self.assertFalse(directory.exists())
                self.assertEqual(fault.observed['reason'],'credential-protocol-collision')
                self.assertFalse(fault.observed['databaseTouched'])
                self.assertNotIn('?',fault.code)
                self.assertNotIn(secret,fault.message)
                self.assertNotIn(secret,fault.recovery)

    def test_required_outcome_and_status_credentials_refuse_before_commit_or_run_files(self):
        for secret in ('committed','rolledBack','rows committed','seed rows committed','read-only report completed','succeeded','incomplete'):
            with self.subTest(secret=secret),patch.dict(os.environ,{'SCHEMAXIS_ORACLE_FREE_LOCAL_PASSWORD':secret}):
                fake=FakeOracle()
                document=example('mutate-transfer');document['setup']={'retain':True}
                directory,action=self.run_with(document,fake)
                with patch.object(adaptor,'cancellation_requested',return_value=True):
                    fault=self.fault(action,'INVALID_ORACLE_CONNECTION')
                self.assertFalse(directory.exists())
                self.assertEqual(fake.stages,[])
                self.assertFalse(fault.observed['databaseTouched'])
                self.assertEqual(fault.observed['reason'],'credential-protocol-collision')

    def test_static_constraint_identifier_collision_refuses_before_diagnostic_fault(self):
        with patch.dict(os.environ,{'SCHEMAXIS_ORACLE_FREE_LOCAL_PASSWORD':'constraint'}):
            fake=FakeOracle(fault={'stage':'identify','code':'ORACLE_SERVER_ERROR','message':'driver refused','details':{'constraint':'unique'}})
            directory,action=self.run_with(example('report-revenue'),fake)
            fault=self.fault(action,'INVALID_ORACLE_CONNECTION')
            self.assertEqual(fake.stages,[])
            self.assertFalse(directory.exists())
            self.assertNotIn('constraint',json.dumps(fault.to_dict()))

    def test_arbitrary_nested_diagnostic_keys_are_redacted_without_renaming_required_facts(self):
        secret='diagnostic-key-725'
        with patch.dict(os.environ,{'SCHEMAXIS_ORACLE_FREE_LOCAL_PASSWORD':secret}):
            fake=FakeOracle(fault={'stage':'identify','code':'ORACLE_SERVER_ERROR','message':'driver refused','details':{secret:{'nested':[{secret:'private label'}]}}})
            directory,action=self.run_with(example('report-revenue'),fake)
            fault=self.fault(action,'ORACLE_CREDENTIAL_LEAK')
            self.assertEqual(fault.code,'ORACLE_CREDENTIAL_LEAK')
            self.assertNotIn(secret,json.dumps(fault.to_dict()))
            self.assertIn('priorFaultCode',fault.observed)
            self.assertIn('files',fault.observed)
            status=adaptor.read(directory,'result.json')
            self.assertEqual(status['status'],'failed')
            self.assertNotIn(secret,json.dumps(status))
            for path in directory.rglob('*'):
                if path.is_file():
                    self.assertNotIn(secret.encode(),path.read_bytes())
        # With an ordinary profile the durable facts remain named and exact.
        document=example('mutate-transfer');document['setup']={'retain':True}
        directory,action=self.run_with(document,FakeOracle())
        with patch.object(adaptor,'cancellation_requested',return_value=True):
            fault=self.fault(action,'RUNNER_CANCELLED')
        self.assertEqual(fault.observed['outcome'],'committed')
        self.assertTrue(fault.observed['databaseWorkCompleted'])
        self.assertTrue(fault.observed['databaseTouched'])

    def test_credential_equal_to_a_retained_filename_never_echoes_from_scan_fault(self):
        with patch.dict(os.environ, {'SCHEMAXIS_ORACLE_FREE_LOCAL_PASSWORD':'result.json'}):
            fake=FakeOracle(fault={'stage':'identify','code':'ORACLE_SERVER_ERROR','message':'driver said result.json','details':{}})
            directory, action=self.run_with(example('report-revenue'), fake)
            fault=self.fault(action,'ORACLE_CREDENTIAL_LEAK')
            self.assertNotIn('result.json', json.dumps(fault.to_dict()))
            self.assertTrue(all(type(n) is int for n in fault.observed['files']))
            self.assertNotIn('databaseWorkCompleted',fault.observed)
            status=adaptor.read(directory,'result.json')
            self.assertEqual(status['status'],'failed')
            for path in directory.rglob('*'):
                if path.is_file():
                    self.assertNotIn(b'result.json',path.read_bytes())

    def test_plans_and_documents_hold_only_variable_names(self):
        p = planning.plan_document(example('report-revenue'))
        text = json.dumps(p)
        for value in (PASSWORD, DSN):
            self.assertNotIn(value, text)
        self.assertEqual(p['connection']['passwordVariable'], 'SCHEMAXIS_ORACLE_FREE_LOCAL_PASSWORD')


class Tampering(Base):
    def test_native_transaction_validation_cannot_be_removed_from_refreshed_evidence(self):
        for kind in ('boundary', 'validate'):
            directory, _, _ = self.succeed('mutate-transfer')
            native = adaptor.read(directory, 'apply.json')
            next(e for e in native['steps'] if e['kind'] == kind).pop('validated')
            atomic_json(directory / 'apply.json', native)
            self.refresh(directory)
            self.fault(lambda: adaptor.verify(directory), 'VERIFICATION_FAILED')


    def test_altered_published_and_retained_evidence_is_refused(self):
        directory, _, _ = self.succeed('report-revenue')
        saved = {p: p.read_bytes() for p in directory.rglob('*') if p.is_file()}

        def restore():
            for path, content in saved.items():
                path.write_bytes(content)

        def attempt(name, edit, refresh=False):
            try:
                edit()
                if refresh:
                    self.refresh(directory)
                self.fault(lambda: adaptor.verify(directory), 'VERIFICATION_FAILED')
            finally:
                restore()
        attempt('published rows', lambda: (directory / 'report.json').write_bytes((directory / 'report.json').read_bytes().replace(b'350.5', b'351.5')))
        attempt('published rows, receipt refreshed', lambda: (directory / 'report.json').write_bytes((directory / 'report.json').read_bytes().replace(b'350.5', b'351.5')), True)
        attempt('csv null token', lambda: (directory / 'report.csv').write_bytes((directory / 'report.csv').read_bytes().replace(b'\\N', b'')), True)
        attempt('native rows, receipt refreshed', lambda: (directory / 'apply.json').write_bytes((directory / 'apply.json').read_bytes().replace(b'"350.5"', b'"351.5"')), True)
        attempt('readback rows, receipt refreshed', lambda: (directory / 'readback.json').write_bytes((directory / 'readback.json').read_bytes().replace(b'1500.5', b'1500.6')), True)
        attempt('injected statement', lambda: atomic_json(directory / 'program-apply.json', {**adaptor.read(directory, 'program-apply.json'), 'steps': adaptor.read(directory, 'program-apply.json')['steps'] + [{'id': 'x', 'kind': 'ddl', 'sql': 'DROP TABLE "SALES" PURGE'}]}), True)
        attempt('source capture', lambda: (directory / 'source-customers.json').write_bytes((directory / 'source-customers.json').read_bytes().replace(b'Acme', b'Acne')), True)
        attempt('worker', lambda: (directory / 'native-worker.py').write_text((directory / 'native-worker.py').read_text() + '\n# changed\n'), True)
        attempt('forged executable', lambda: atomic_json(directory / 'apply-submission.json', {'nativeCommand': ['/forged/python', '-I'], 'exitCode': 0}), True)
        attempt('runtime identity', lambda: atomic_json(directory / 'verification.json', {**adaptor.read(directory, 'verification.json'), 'runtime': 'python-oracledb 9 (thin) / Oracle Database 99'}))
        attempt('evidence membership', lambda: atomic_json(directory / 'verification.json', {**adaptor.read(directory, 'verification.json'), 'evidence': {**adaptor.read(directory, 'verification.json')['evidence'], 'extra.json': '0' * 64}}))
        attempt('missing publication', lambda: (directory / 'report.csv').unlink())
        attempt('missing evidence', lambda: (directory / 'identify.json').unlink())
        attempt('plan', lambda: atomic_json(directory / 'plan.json', {**adaptor.read(directory, 'plan.json'), 'losses': []}))
        self.assertTrue(adaptor.verify(directory)['verified'])

    def test_verification_needs_the_current_implementation(self):
        directory, _, _ = self.succeed('report-revenue')
        record = adaptor.read(directory, 'implementation.json')
        record['sql.py'] = '0' * 64
        atomic_json(directory / 'implementation.json', record)
        self.fault(lambda: adaptor.verify(directory), 'VERIFICATION_FAILED')

    def test_cleanup_records_are_bound_to_this_runs_physical_names_order_and_marker(self):
        directory, result, _ = self.succeed('report-revenue')
        suffix = adaptor.read(directory, 'native-config.json')['runId'][:5].upper()
        cleanup = adaptor.read(directory, 'readback.json')['cleanup']
        self.assertEqual([(c['table'], c['dropped'], c['reason']) for c in cleanup], [(f'ORDERS_{suffix}', True, 'dropped'), (f'CUSTOMERS_{suffix}', True, 'dropped')])
        saved = {p: p.read_bytes() for p in directory.rglob('*') if p.is_file()}

        def attempt(edit, code='VERIFICATION_FAILED'):
            try:
                record = adaptor.read(directory, 'readback.json')
                edit(record['cleanup'])
                atomic_json(directory / 'readback.json', record)
                self.refresh(directory)
                self.fault(lambda: adaptor.verify(directory), code)
            finally:
                for path, content in saved.items():
                    path.write_bytes(content)
        attempt(lambda c: c.reverse())                                                       # wrong order
        attempt(lambda c: [r.update(table=r['table'].split('_')[0]) for r in c])              # logical names, no run suffix
        attempt(lambda c: c[0].update(table=c[0]['table'][:-5] + 'FFFFF'))                    # another run's suffix
        attempt(lambda c: c[0].update(table='ACCOUNTS_' + suffix))                            # a table this run never created
        attempt(lambda c: c.pop())                                                           # a record missing
        attempt(lambda c: c.append(dict(c[0])))                                              # a record duplicated
        attempt(lambda c: c[0].update(dropped=False), 'ORACLE_CLEANUP_INCOMPLETE')           # genuinely not dropped
        attempt(lambda c: c[0].update(reason='skipped'), 'ORACLE_CLEANUP_INCOMPLETE')
        program = adaptor.read(directory, 'program-readback.json')
        for edit in (lambda p: p['marker'].update(value=sql.run_marker('f' * 16)), lambda p: p['cleanup'].reverse(), lambda p: p['cleanup'][0].update(sql='DROP TABLE "CUSTOMERS" PURGE')):
            try:
                changed = adaptor.read(directory, 'program-readback.json')
                edit(changed)
                atomic_json(directory / 'program-readback.json', changed)
                self.refresh(directory)
                self.fault(lambda: adaptor.verify(directory), 'VERIFICATION_FAILED')
            finally:
                for path, content in saved.items():
                    path.write_bytes(content)
        self.assertTrue(adaptor.verify(directory)['verified'])
        self.assertEqual(program['marker']['value'], sql.run_marker(adaptor.read(directory, 'native-config.json')['runId']))

    def test_a_native_run_that_reports_logical_cleanup_names_is_not_a_successful_cleanup(self):
        class Logical(FakeOracle):
            def readback(self, directory, p, data):
                super().readback(directory, p, data)
                record = adaptor.read(directory, 'readback.json')
                for item in record['cleanup']:
                    item['table'] = item['table'].split('_')[0]
                atomic_json(directory / 'readback.json', record)
        error = self.fault(self.run_with(example('report-revenue'), Logical())[1], 'VERIFICATION_FAILED')
        self.assertIn('own scratch tables', error.message)
        self.assertEqual(error.observed['expected'][0].split('_')[0], 'ORDERS')

    def test_cleanup_failure_is_a_visible_fault(self):
        class Leaky(FakeOracle):
            def readback(self, directory, p, data):
                super().readback(directory, p, data)
                record = adaptor.read(directory, 'readback.json')
                record['cleanup'][0]['dropped'] = False
                atomic_json(directory / 'readback.json', record)
        self.fault(self.run_with(example('report-revenue'), Leaky())[1], 'ORACLE_CLEANUP_INCOMPLETE')


class FakeInfo:
    def __init__(self, code, full_code=None, message='boom'):
        self.code, self.full_code, self.message = code, full_code, message


class FakeError(Exception):
    pass


class FakeCursor:
    def __init__(self, connection):
        self.connection, self.arraysize, self.description, self.rowcount, self._rows = connection, 100, None, 0, []

    def execute(self, statement, binds=None):
        self.connection.log.append(('execute', statement, binds))
        self.connection.react(statement, self)

    def executemany(self, statement, rows):
        self.connection.log.append(('executemany', statement, rows))
        self.connection.react(statement, self)
        self.rowcount = len(rows) if self.rowcount == 0 else self.rowcount

    def setinputsizes(self, *sizes):
        self.connection.log.append(('sizes', sizes))

    def fetchmany(self, n):
        return self._rows[:n]

    def fetchall(self):
        return self._rows

    def var(self, *args, **kwargs):
        return ('var', args)

    def close(self):
        pass


class FakeConnection:
    thin = True
    version = '23.26.3.0.0'

    def __init__(self, driver):
        self.driver, self.log, self.committed, self.rolled = driver, [], 0, 0
        self.call_timeout = None

    def cursor(self):
        return FakeCursor(self)

    def react(self, statement, cursor):
        outcome = self.driver.script(statement)
        if isinstance(outcome, Exception):
            raise outcome
        columns, rows = outcome if outcome else (['x'], [])
        cursor.description = [(c,) for c in columns]
        cursor._rows = rows

    def commit(self):
        self.committed += 1
        if self.driver.commit_error:
            raise self.driver.commit_error

    def rollback(self):
        self.rolled += 1

    def close(self):
        pass


class FakeDriver:
    Error = FakeError
    DB_TYPE_NUMBER, DB_TYPE_VARCHAR, DB_TYPE_BOOLEAN = 'N', 'V', 'B'
    __version__ = '3.0.0'

    def __init__(self, script=None, commit_error=None, thin=True, connect_error=None):
        self.script = script or (lambda statement: None)
        self.commit_error, self.thin, self.connect_error = commit_error, thin, connect_error
        self.connections = []

    def connect(self, **kwargs):
        if self.connect_error:
            raise self.connect_error
        self.kwargs = kwargs
        connection = FakeConnection(self)
        connection.thin = self.thin
        self.connections.append(connection)
        return connection


def violation():
    return FakeError(FakeInfo(1, 'ORA-00001', 'ORA-00001: unique constraint (TESTER.ACCOUNTS_U1) violated'))


class WorkerProtocol(unittest.TestCase):
    config = {'connection': {'userVariable': 'SCHEMAXIS_ORACLE_T_USER', 'passwordVariable': 'SCHEMAXIS_ORACLE_T_PASSWORD', 'dsnVariable': 'SCHEMAXIS_ORACLE_T_DSN', 'connectTimeout': 5, 'callTimeout': 7}}

    def setUp(self):
        forbid_host_effects(self)
        patcher = patch.dict(os.environ, {'SCHEMAXIS_ORACLE_T_USER': USER, 'SCHEMAXIS_ORACLE_T_PASSWORD': PASSWORD, 'SCHEMAXIS_ORACLE_T_DSN': DSN})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.journal = Path(self.temp.name) / 'journal.jsonl'
        self.config = {**WorkerProtocol.config, 'journal': str(self.journal)}      # never write into the process working directory

    def records(self):
        return [json.loads(line) for line in self.journal.read_text().splitlines()] if self.journal.exists() else []

    def refused(self, code, action):
        with self.assertRaises(worker.Refusal) as caught:
            action()
        self.assertEqual(caught.exception.code, code, str(caught.exception))
        return caught.exception

    def test_every_generated_statement_matches_the_worker_allow_list(self):
        names = ('report-revenue', 'report-variant', 'report-lines', 'load', 'mutate-transfer', 'mutate-savepoint', 'mutate-rollback')
        count = 0
        for name in names:
            p = planning.plan_document(example(name))
            data = data_for(p)
            programs = [adaptor.apply_program(p, data, 'a' * 16), adaptor.identify_program(p), adaptor.readback_program(p, [t['name'] for t in p['tables']], run_id='a' * 16)]
            for step in programs[0]['steps']:
                if step['kind'] in ('ddl', 'insert', 'dml', 'query'):
                    worker.check_statement(step['kind'], step['sql'])
                    count += 1
                if step['kind'] == 'observe':
                    for spec in step['queries'].values():
                        worker.check_statement('query', spec['sql'])
            for spec in {**programs[1]['identity'], **programs[1]['catalog'], **programs[2]['tables']}.values():
                worker.check_statement('query', spec['sql'])
            for item in programs[2]['cleanup']:
                worker.check_statement('ddl', item['sql'])
            worker.check_statement('query', adaptor.MARKER_SQL)
        self.assertGreater(count, 30)

    def test_hostile_statements_are_refused(self):
        for kind, text in [('ddl', 'DROP USER scott CASCADE'), ('ddl', 'CREATE TABLE "T" ("A" NUMBER); DROP TABLE "U"'), ('ddl', 'DROP TABLE "t" PURGE'), ('ddl', 'DROP TABLE "A B" PURGE'),
                           ('ddl', 'GRANT DBA TO scott'), ('ddl', 'ALTER SYSTEM KILL SESSION \'1,2\''), ('dml', 'UPDATE "T" SET "A" = 1; COMMIT'), ('dml', 'BEGIN NULL; END;'),
                           ('dml', 'UPDATE "T" SET "A" = 1 -- x'), ('query', 'SELECT 1 FROM DUAL; SELECT 2 FROM DUAL'), ('query', 'SELECT "A" INTO :x FROM "T"'),
                           ('query', 'SELECT * FROM "T" FOR UPDATE'), ('query', 'SELECT DBMS_RANDOM.VALUE FROM DUAL'), ('query', 'DELETE FROM "T"'), ('insert', 'INSERT INTO t VALUES (1)'),
                           ('query', 'SELECT 1\nFROM DUAL'), ('script', 'SELECT 1 FROM DUAL'), ('query', None)]:
            self.refused('ORACLE_PROGRAM_REFUSED', lambda: worker.check_statement(kind, text))
        worker.check_statement('ddl', "CREATE TABLE \"T\" (\"A\" NUMBER, CONSTRAINT \"T_C1\" CHECK ((\"A\" <> 'x; DROP TABLE y')))")

    def test_redaction_removes_values_fragments_and_descriptors(self):
        text = f'login {USER}/{PASSWORD}@{DSN} failed (DESCRIPTION=(ADDRESS=(HOST=db.example.invalid)))'
        redacted = worker.redact(text, [USER, PASSWORD, DSN])
        for value in (PASSWORD, DSN, 'db.example.invalid', 'SENTINELSERVICE', 'Sentinel-Passw0rd'):
            self.assertNotIn(value, redacted)
        self.assertLessEqual(len(worker.redact('x' * 5000, [])), worker.MAX_MESSAGE)
        self.assertEqual(worker.scrub({'a': [PASSWORD, 3]}, [PASSWORD]), {'a': ['<redacted>', 3]})

    def test_native_errors_classify_to_stable_codes(self):
        for code, full, expected, kind in [(1, 'ORA-00001', 'ORACLE_CONSTRAINT_VIOLATION', 'unique'), (2291, 'ORA-02291', 'ORACLE_CONSTRAINT_VIOLATION', 'foreignKey'), (1400, 'ORA-01400', 'ORACLE_CONSTRAINT_VIOLATION', 'notNull'),
                                           (1017, 'ORA-01017', 'ORACLE_AUTHENTICATION_FAILED', None), (942, 'ORA-00942', 'ORACLE_OBJECT_MISSING', None), (955, 'ORA-00955', 'ORACLE_OBJECT_EXISTS', None),
                                           (1476, 'ORA-01476', 'ORACLE_ARITHMETIC_ERROR', None), (1031, 'ORA-01031', 'ORACLE_PRIVILEGE_DENIED', None), (99999, 'ORA-99999', 'ORACLE_SERVER_ERROR', None),
                                           (None, 'DPY-4024', 'ORACLE_CALL_TIMEOUT', None), (None, 'DPY-6005', 'ORACLE_UNAVAILABLE', None)]:
            fault, oracle, message, constraint = worker.classify(FakeError(FakeInfo(code, full, f'{full} text {PASSWORD}')), [PASSWORD])
            self.assertEqual((fault, oracle, constraint), (expected, full, kind))
            self.assertNotIn(PASSWORD, message)
        self.assertEqual(worker.classify(FakeError('plain'))[0], 'ORACLE_SERVER_ERROR')

    def test_value_conversion_is_exact(self):
        self.assertEqual(worker.convert_bind('number', '0.1'), worker.Decimal('0.1'))
        self.assertIsNone(worker.convert_bind('varchar', None))
        self.assertEqual(worker.convert_bind('varchar', "x'); DROP"), "x'); DROP")
        self.assertEqual(worker.encode_cell('number', worker.Decimal('1E+3')), '1000')
        self.assertEqual(worker.encode_cell('number', worker.Decimal('0.50')), '0.50')
        self.assertEqual(worker.encode_cell('varchar2', 'a\u0000b'), 'a\u0000b')
        self.assertEqual(worker.encode_cell('raw', b'\xff'), 'ff')
        self.assertIs(worker.encode_cell('boolean', 1), True)

    def test_connection_policy_thin_only_timeouts_and_missing_credentials(self):
        driver = FakeDriver()
        session = worker.Session(driver, self.config)
        connection = session.connect()
        self.assertEqual((connection.call_timeout, driver.kwargs['tcp_connect_timeout']), (7000, 5.0))
        self.assertIn("NLS_COMP = 'BINARY'", connection.log[0][1])
        self.refused('ORACLE_UNSUPPORTED_MODE', lambda: worker.Session(FakeDriver(thin=False), self.config).connect())
        error = self.refused('ORACLE_AUTHENTICATION_FAILED', lambda: worker.Session(FakeDriver(connect_error=FakeError(FakeInfo(1017, 'ORA-01017', f'invalid {PASSWORD} for {USER}'))), self.config).connect())
        self.assertNotIn(PASSWORD, str(error))
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('SCHEMAXIS_ORACLE_T_PASSWORD')
            error = self.refused('ORACLE_CREDENTIALS_MISSING', lambda: worker.Session(FakeDriver(), self.config))
            self.assertEqual(error.details['variable'], 'SCHEMAXIS_ORACLE_T_PASSWORD')

    def program(self, *steps):
        return {'steps': list(steps), 'resolve': {}}

    def test_apply_rolls_back_on_server_refusal_and_on_unmet_expectations(self):
        driver = FakeDriver(script=lambda statement: violation() if statement.startswith('INSERT') else None)
        insert = {'id': 'step:0', 'kind': 'insert', 'sql': 'INSERT INTO "T" ("A") VALUES (:1)', 'types': ['number'], 'rows': [['1']]}
        error = self.refused('ORACLE_CONSTRAINT_VIOLATION', lambda: worker.stage_apply(worker.Session(driver, self.config), self.program(insert)))
        self.assertEqual((error.details['constraint'], error.details['rolledBack'], error.details['step']), ('unique', True, 'step:0'))
        self.assertEqual(driver.connections[0].rolled, 1)
        driver = FakeDriver()
        counted = {'id': 'step:0', 'kind': 'dml', 'sql': 'DELETE FROM "T"', 'binds': [], 'expectRows': 3}
        error = self.refused('ORACLE_ROWCOUNT_MISMATCH', lambda: worker.stage_apply(worker.Session(driver, self.config), self.program(counted)))
        self.assertEqual((error.details['observed'], error.details['expected'], error.details['rolledBack']), (0, 3, True))
        self.assertEqual(driver.connections[0].rolled, 1)
        driver = FakeDriver()
        self.refused('ORACLE_PROGRAM_REFUSED', lambda: worker.stage_apply(worker.Session(driver, self.config), self.program({'id': 'x', 'kind': 'ddl', 'sql': 'DROP USER x'})))
        self.assertEqual(driver.connections[0].rolled, 1)

    def test_a_failed_commit_is_reported_unknown_with_a_fresh_session_observation(self):
        driver = FakeDriver(commit_error=FakeError(FakeInfo(3113, 'ORA-03113', 'end-of-file on communication channel')),
                            script=lambda statement: (['n'], [[worker.Decimal(3)]]) if statement.startswith('SELECT') else None)
        program = {'steps': [{'id': 'finish', 'kind': 'control', 'action': 'commit', 'final': True}],
                   'resolve': {'t': {'sql': 'SELECT COUNT(*) AS "N" FROM "T"', 'binds': [], 'columns': [{'name': 'n', 'kind': 'number'}]}}}
        error = self.refused('ORACLE_COMMIT_OUTCOME_UNKNOWN', lambda: worker.stage_apply(worker.Session(driver, self.config), program))
        self.assertEqual(error.details['resolution'], {'t': {'columns': ['n'], 'rows': [['3']]}})
        self.assertEqual(error.details['partial']['status'], 'unknown')
        self.assertEqual(driver.connections[0].committed, 1)

    def test_savepoint_names_are_validated_and_queries_decode_exactly(self):
        driver = FakeDriver(script=lambda statement: (['id', 'amount'], [[worker.Decimal('1'), worker.Decimal('2.50')]]) if statement.startswith('SELECT') else None)
        session = worker.Session(driver, self.config)
        steps = [{'id': 'a', 'kind': 'control', 'action': 'savepoint', 'name': 'after_debit'}, {'id': 'q', 'kind': 'query', 'sql': 'SELECT "ID", "AMOUNT" FROM "T"', 'binds': [],
                 'columns': [{'name': 'id', 'kind': 'number'}, {'name': 'amount', 'kind': 'number'}]}]
        result = worker.stage_apply(session, self.program(*steps))
        self.assertEqual(result['outputs']['q'], {'columns': ['id', 'amount'], 'rows': [['1', '2.50']]})
        self.assertIn('SAVEPOINT "AFTER_DEBIT"', [e[1] for e in driver.connections[0].log if e[0] == 'execute'])
        self.refused('ORACLE_PROGRAM_REFUSED', lambda: worker.stage_apply(worker.Session(FakeDriver(), self.config), self.program({'id': 'a', 'kind': 'control', 'action': 'savepoint', 'name': 'x"; DROP'})))

    def test_oversized_results_are_refused_and_missing_tables_are_reported_in_readback(self):
        driver = FakeDriver(script=lambda statement: (['n'], [[1]] * 11) if 'BIG' in statement else (FakeError(FakeInfo(942, 'ORA-00942', 'missing')) if 'GONE' in statement else None))
        session = worker.Session(driver, self.config)
        cursor = session.connect().cursor()
        self.refused('ORACLE_RESULT_TOO_LARGE', lambda: worker.run_query(session, cursor, {'sql': 'SELECT 1 FROM "BIG"', 'binds': [], 'columns': [{'name': 'n', 'kind': 'number'}]}, 10))
        program = {'catalog': {}, 'tables': {'gone': {'sql': 'SELECT 1 FROM "GONE"', 'binds': [], 'columns': [{'name': 'n', 'kind': 'number'}]}}, 'cleanup': [],
                   'marker': {'sql': adaptor.MARKER_SQL, 'value': sql.run_marker('a' * 16)}}
        self.assertEqual(worker.stage_readback(worker.Session(driver, self.config), program)['tables'], {'gone': {'missing': True}})

    def test_the_journal_records_each_ddl_and_commit_before_and_after_it_runs(self):
        driver = FakeDriver()
        steps = [{'id': 'create:t', 'kind': 'ddl', 'sql': 'CREATE TABLE "T" ("A" NUMBER)', 'creates': 't'}, {'id': 'seed', 'kind': 'control', 'action': 'commit', 'final': True}]
        result = worker.stage_apply(worker.Session(driver, self.config), self.program(*steps))
        self.assertEqual(result['created'], ['t'])
        self.assertEqual([(r['event'], r['id']) for r in self.records()], [('begin', 'create:t'), ('done', 'create:t'), ('begin', 'seed'), ('done', 'seed')])

    def test_a_failed_ddl_leaves_a_begin_without_done_so_the_host_can_report_it(self):
        def script(statement):
            return FakeError(FakeInfo(1950, 'ORA-01950', 'no privileges on tablespace')) if statement.startswith('CREATE') else None
        error = self.refused('ORACLE_PRIVILEGE_DENIED', lambda: worker.stage_apply(worker.Session(FakeDriver(script=script), self.config),
                             self.program({'id': 'create:t', 'kind': 'ddl', 'sql': 'CREATE TABLE "T" ("A" NUMBER)', 'creates': 't'})))
        self.assertEqual(error.details['partial']['created'], [])
        self.assertEqual(error.details['partial']['attempted'], 't')
        self.assertEqual([(r['event'], r['creates']) for r in self.records()], [('begin', 't')])

    def test_a_lost_seed_commit_is_an_unknown_outcome_not_a_rerun_instruction(self):
        driver = FakeDriver(commit_error=FakeError(FakeInfo(3113, 'ORA-03113', 'end-of-file')))
        program = {'steps': [{'id': 'commit:seed', 'kind': 'control', 'action': 'commit', 'final': True}], 'resolve': {}}
        self.refused('ORACLE_COMMIT_OUTCOME_UNKNOWN', lambda: worker.stage_apply(worker.Session(driver, self.config), program))
        self.assertEqual([r['event'] for r in self.records()], ['begin'])

    def test_serializable_snapshot_control_and_bounded_dictionary_reads(self):
        driver = FakeDriver(script=lambda statement: (['n'], [[1]] * (worker.DICTIONARY_ROWS + 1)) if 'user_tables' in statement else None)
        result = worker.stage_apply(worker.Session(driver, self.config), self.program({'id': 'snapshot', 'kind': 'control', 'action': 'serializable'}))
        self.assertIn('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE', [e[1] for e in driver.connections[0].log if e[0] == 'execute'])
        self.refused('ORACLE_PROGRAM_REFUSED', lambda: worker.stage_apply(worker.Session(FakeDriver(), self.config), self.program({'id': 'x', 'kind': 'control', 'action': 'readonly'})))
        self.assertEqual(result['status'], 'succeeded')
        session = worker.Session(driver, self.config)
        cursor = session.connect().cursor()
        error = self.refused('ORACLE_RESULT_TOO_LARGE', lambda: worker.dictionary(session, cursor, {'tables': {'sql': 'SELECT x FROM user_tables', 'binds': []}}))
        self.assertIn('inspection.names', str(error))

    def test_redaction_never_rewrites_structured_resolution_rows(self):
        details = {'oracle': f'ORA-1 {PASSWORD}', 'resolution': {'t': {'columns': ['owner'], 'rows': [[USER, DSN]]}}, 'partial': {'created': [USER]}}
        scrubbed = worker.scrub(details, [USER, PASSWORD, DSN])
        self.assertNotIn(PASSWORD, scrubbed['oracle'])
        self.assertEqual(scrubbed['resolution'], details['resolution'])            # row data belongs to the table, not to error text
        self.assertEqual(scrubbed['partial'], details['partial'])

    def test_cleanup_drops_only_tables_carrying_this_runs_marker(self):
        driver = FakeDriver()
        mine, other = sql.run_marker('a' * 16), sql.run_marker('b' * 16)
        answers = iter([(['comments'], [[mine]]), (['comments'], [[other]]), (['comments'], [['someone else']]), (['comments'], [])])
        driver.script = lambda statement: next(answers) if statement == adaptor.MARKER_SQL else None
        program = {'catalog': {}, 'tables': {}, 'marker': {'sql': adaptor.MARKER_SQL, 'value': mine},
                   'cleanup': [{'table': 'MINE', 'sql': 'DROP TABLE "MINE" PURGE'}, {'table': 'OTHERRUN', 'sql': 'DROP TABLE "OTHERRUN" PURGE'},
                               {'table': 'THEIRS', 'sql': 'DROP TABLE "THEIRS" PURGE'}, {'table': 'GONE', 'sql': 'DROP TABLE "GONE" PURGE'}]}
        result = worker.stage_readback(worker.Session(driver, self.config), program)
        self.assertEqual([(c['table'], c['dropped']) for c in result['cleanup']], [('MINE', True), ('OTHERRUN', False), ('THEIRS', False), ('GONE', False)])
        executed = [e[1] for e in driver.connections[0].log if e[0] == 'execute']
        self.assertEqual([s for s in executed if s.startswith('DROP')], ['DROP TABLE "MINE" PURGE'])

    def test_main_reports_a_missing_driver_and_writes_redacted_fault_files(self):
        with tempfile.TemporaryDirectory() as temp:
            previous = os.getcwd()
            os.chdir(temp)
            try:
                with patch.dict(sys.modules, {'oracledb': None}):
                    self.assertEqual(worker.main(['worker', 'identify']), 4)
                self.assertEqual(json.loads(Path('identify-fault.json').read_text())['code'], 'ORACLE_DRIVER_UNAVAILABLE')
                self.assertEqual(worker.main(['worker', 'bogus']), 64)
                atomic_json(Path('native-config.json'), self.config)
                atomic_json(Path('program-identify.json'), {'identity': {}, 'catalog': {}})
                failing = FakeDriver(connect_error=FakeError(FakeInfo(1017, 'ORA-01017', f'bad {PASSWORD}')))
                self.assertEqual(worker.run('identify', failing), 2)
                fault = json.loads(Path('identify-fault.json').read_text())
                self.assertEqual(fault['code'], 'ORACLE_AUTHENTICATION_FAILED')
                self.assertNotIn(PASSWORD, json.dumps(fault))
            finally:
                os.chdir(previous)


class FakeObserve:
    def __init__(self, schema='SANDBOX', present=(), comments=None):
        self.schema, self.present, self.statements = schema, [p.upper() for p in present], []
        self.comments = {k.upper(): v for k, v in (comments or {}).items()}

    def __call__(self, *statements):
        import re
        self.statements += statements
        results = []
        for statement in statements:
            if statement.startswith('DROP TABLE '):
                name = statement.split()[2].upper()
                if name in self.present:
                    self.present.remove(name)
                results.append([])
            elif 'CURRENT_SCHEMA' in statement:
                results.append([[self.schema]])
            elif 'user_tab_comments' in statement:
                name = re.search(r"table_name = '([^']+)'", statement).group(1)
                results.append([[self.comments.get(name)]] if name in self.present else [])
            else:
                results.append([])
        return results

    def exact(self, *names):
        return [t for t in sorted(self.present) if t in {n.upper() for n in names}]

    def tables(self, *names):
        import re
        pattern = re.compile('^(%s)(_[0-9A-F]{5})?$' % '|'.join(re.escape(n.upper()) for n in names))      # the real observer's rule
        return [t for t in sorted(self.present) if pattern.match(t)]


class QualificationHarness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location('qualify_oracle_tool', ROOT / 'tools/qualify_oracle.py')
        cls.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.tool)

    def test_the_dedicated_interpreter_path_is_absolute_but_never_dereferenced(self):
        with tempfile.TemporaryDirectory() as temp:
            bin_directory = Path(temp) / 'venv' / 'bin'
            bin_directory.mkdir(parents=True)
            link = bin_directory / 'python'
            link.symlink_to(sys.executable)
            self.assertEqual(self.tool.interpreter_path(link), str(link))
            self.assertEqual(self.tool.interpreter_path(bin_directory / '..' / 'bin' / 'python'), str(link))
            self.assertNotEqual(self.tool.interpreter_path(link), os.path.realpath(link))        # resolve() would lose the venv's packages
            self.assertTrue(os.path.isabs(self.tool.interpreter_path('venv/bin/python')))

    def test_the_harness_refuses_unconfirmed_mismatched_or_occupied_schemas_without_dropping_anything(self):
        for observe, schema, confirmed in ((FakeObserve(), 'SANDBOX', False), (FakeObserve(), None, True), (FakeObserve(schema='OTHER'), 'SANDBOX', True),
                                           (FakeObserve(present=['customers']), 'SANDBOX', True)):
            with self.assertRaises(SystemExit):
                self.tool.preflight(observe, schema, confirmed)
            self.assertFalse([s for s in observe.statements if s.startswith('DROP')])
        # A scratch-looking leftover from another job is not a name collision and is never evidence of ownership.
        observe = FakeObserve(present=['customers_abcde'])
        self.tool.preflight(observe, 'sandbox', True)
        self.assertFalse([s for s in observe.statements if s.startswith('DROP')])
        self.assertTrue(FakeObserve(present=['customers_abcde']).tables('customers'))
        self.assertFalse(FakeObserve(present=['customers_abcdefg']).tables('customers'))

    def make_run(self, root, name, document, run_id):
        directory = Path(root) / name
        directory.mkdir(parents=True)
        atomic_json(directory / 'authored.json', document)
        atomic_json(directory / 'native-config.json', {'connection': {}, 'runId': run_id})
        return directory

    def test_cleanup_drops_only_tables_carrying_the_exact_marker_of_the_run_that_created_them(self):
        a_marker, b_marker, c_marker = (sql.run_marker(c * 16) for c in 'abc')
        with tempfile.TemporaryDirectory() as root:
            self.make_run(root, 'a-lines', example('report-lines'), 'a' * 16)
            self.make_run(root, 'b-revenue', example('report-revenue'), 'b' * 16)
            self.make_run(root, 'c-load', example('load'), 'c' * 16)
            self.make_run(root, 'd-inspect', example('inspect'), 'd' * 16)
            broken = Path(root) / 'e-broken'
            broken.mkdir()
            (broken / 'authored.json').write_text('{not json')
            atomic_json(broken / 'native-config.json', {'runId': 'e' * 16})
            owned = self.tool.owned_tables(root)
            self.assertEqual([name for name, _ in owned[:3]], ['ORDER_LINES_AAAAA', 'ORDERS_AAAAA', 'CUSTOMERS_AAAAA'])        # children first, run-unique names
            self.assertEqual([name for name, _ in owned[3:5]], ['ORDERS_BBBBB', 'CUSTOMERS_BBBBB'])
            self.assertEqual([name for name, _ in owned[5:]], ['ORDER_LINES', 'ORDERS', 'CUSTOMERS'])                         # a retained load keeps declared names
            self.assertEqual({marker for name, marker in owned if name.endswith('AAAAA')}, {a_marker})
            observe = FakeObserve(
                present=['order_lines_aaaaa', 'orders_aaaaa', 'customers_aaaaa', 'orders_bbbbb', 'customers_bbbbb', 'customers_ccccc', 'unrelated', 'order_lines', 'customers'],
                comments={'order_lines_aaaaa': a_marker, 'orders_aaaaa': a_marker, 'customers_aaaaa': a_marker, 'orders_bbbbb': b_marker, 'customers_bbbbb': a_marker,
                          'customers_ccccc': c_marker, 'order_lines': c_marker, 'customers': 'schemaxis-oracle:run:' + 'e' * 16})
            result = self.tool.cleanup(observe, root)
            self.assertEqual(result['dropped'], ['order_lines_aaaaa', 'orders_aaaaa', 'customers_aaaaa', 'orders_bbbbb', 'order_lines'])
            self.assertEqual(result['leftUntouched'], ['CUSTOMERS_BBBBB', 'CUSTOMERS'])                   # another run's marker: not ours to drop
            self.assertEqual(sorted(observe.present), ['CUSTOMERS', 'CUSTOMERS_BBBBB', 'CUSTOMERS_CCCCC', 'UNRELATED'])      # foreign and unrelated tables survive
            self.assertEqual([s for s in observe.statements if s.startswith('DROP')],
                             ['DROP TABLE ORDER_LINES_AAAAA PURGE', 'DROP TABLE ORDERS_AAAAA PURGE', 'DROP TABLE CUSTOMERS_AAAAA PURGE', 'DROP TABLE ORDERS_BBBBB PURGE', 'DROP TABLE ORDER_LINES PURGE'])
            self.assertEqual(self.tool.cleanup(FakeObserve(), root), {'dropped': [], 'leftUntouched': []})   # absent tables are skipped, never dropped

    def test_a_table_without_any_marker_or_with_a_forged_name_is_left_alone(self):
        with tempfile.TemporaryDirectory() as root:
            self.make_run(root, 'a', example('report-revenue'), 'a' * 16)
            observe = FakeObserve(present=['orders_aaaaa', 'customers_aaaaa'], comments={})                      # created, but no marker: cannot prove ownership
            result = self.tool.cleanup(observe, root)
            self.assertEqual((result['dropped'], result['leftUntouched']), ([], ['ORDERS_AAAAA', 'CUSTOMERS_AAAAA']))
            self.assertFalse([s for s in observe.statements if s.startswith('DROP')])
            self.assertFalse(self.tool.IDENTIFIER.match('ORDERS"; DROP TABLE X'))
            self.assertTrue(self.tool.IDENTIFIER.match('ORDER_LINES_AAAAA'))

    def test_the_time_budget_is_bounded_and_inputs_live_in_a_self_cleaning_directory(self):
        self.assertLessEqual(self.tool.WORK_SECONDS + 6 * self.tool.OBSERVER_SECONDS, 2400)
        self.tool.DEADLINE[0] = __import__('time').monotonic() + 100
        self.assertLessEqual(self.tool.limit(240), 98)
        self.assertEqual(self.tool.limit(10), 10)
        self.tool.DEADLINE[0] = __import__('time').monotonic() + 3
        with self.assertRaises(SystemExit):
            self.tool.limit(10)
        text = (ROOT / 'tools/qualify_oracle.py').read_text()
        self.assertIn("scratch = tempfile.TemporaryDirectory(prefix='oracle-qualify-')", text)
        self.assertNotIn("directory / 'wide.json'", text)


if __name__ == '__main__':
    unittest.main()
