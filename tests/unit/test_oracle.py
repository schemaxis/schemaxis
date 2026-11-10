"""Planning, value codec, SQL generation and the independent host reference for the Oracle adaptor.

These tests exercise host code only. They prove the contract and the reference semantics;
they do not prove any Oracle server behaviour (see test_oracle_native_double.py and the
native qualification tool for that distinction).
"""
import copy
from decimal import Decimal
import json
from pathlib import Path
import re
import unittest

from schemaxis.adaptors.oracle import model, planning, reference, sql
from schemaxis.core.declarations import validate_specification
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'examples/schemaxis/fixtures/oracle'
CONNECTION = {'profile': 'free_local'}


def example(name):
    document = json.loads((ROOT / 'examples/schemaxis' / f'oracle-{name}.json').read_text())
    for table in document.get('tables', []):
        if 'source' in table:
            table['source']['path'] = str(FIXTURES / Path(table['source']['path']).name)
    return document


def data_for(p):
    return {t['name']: reference.parse_source(t, Path(t['source']['path']).read_bytes(), '$') if t['source'] else [] for t in p['tables'] if not t['external']}


def cells(kinds, rows):
    return [[model.canonical(k, v) for k, v in zip(kinds, row)] for row in rows]


def items_document(report=None, rows=None, extra_columns=None):
    """One small table used to probe expressions and conditions."""
    columns = [{'name': 'id', 'type': 'number', 'precision': 6, 'scale': 0},
               {'name': 'name', 'type': 'varchar2', 'length': 20, 'nullable': True},
               {'name': 'qty', 'type': 'number', 'precision': 12, 'scale': 3, 'nullable': True}] + (extra_columns or [])
    return {'version': model.VERSION, 'operation': 'report', 'connection': CONNECTION,
            'tables': [{'name': 'items', 'columns': columns, 'primaryKey': ['id']}], 'report': report}


def select(columns, where=None, conditions=(), computed=(), **more):
    body = {'from': {'table': 'items'}, 'computed': list(computed), 'conditions': list(conditions), 'columns': columns, **more}
    if where:
        body['where'] = where
    return body


def column(name, operand=None):
    return {'name': name, 'operand': operand or {'column': 'items.' + name}}


def number(value):
    return {'literal': {'type': 'number', 'value': value}}


def text(value):
    return {'literal': {'type': 'varchar2', 'value': value}}


def term(left, operator, right=None, **more):
    body = {'left': left, 'operator': operator, **more}
    if right is not None:
        body['right'] = right
    return body


def run_items(report, rows):
    p = planning.plan_document(items_document(report))
    table = p['tables'][0]
    data = {'items': [reference.typed_row(table, ['id', 'name', 'qty'], r) for r in rows]}
    result, kinds = reference.run_report(p['report'], data)
    return cells(kinds, result)


class Base(unittest.TestCase):
    def fault(self, action, code):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault


class PlanningContract(Base):
    def test_examples_plan_deterministically_without_changing_the_document(self):
        for name in ('report-revenue', 'report-variant', 'report-lines', 'load', 'inspect', 'mutate-transfer', 'mutate-savepoint', 'mutate-rollback', 'mutate-violation'):
            document = example(name)
            original = copy.deepcopy(document)
            first = planning.plan_document(document)
            self.assertEqual(document, original)
            self.assertEqual(first, planning.plan_document(document))
            self.assertEqual(first['connection']['userVariable'], 'SCHEMAXIS_ORACLE_FREE_LOCAL_USER')
            # The plan names credential variables; it must not contain credential values, wherever they come from.
            import os
            from unittest.mock import patch
            with patch.dict(os.environ, {'SCHEMAXIS_ORACLE_FREE_LOCAL_PASSWORD': 'Sentinel-Plan-Secret-1', 'SCHEMAXIS_ORACLE_FREE_LOCAL_DSN': 'sentinel.invalid:1/SVC'}):
                text = json.dumps(planning.plan_document(document))
            self.assertNotIn('Sentinel-Plan-Secret-1', text)
            self.assertNotIn('sentinel.invalid', text)
            self.assertEqual(first['connection']['passwordVariable'], 'SCHEMAXIS_ORACLE_FREE_LOCAL_PASSWORD')

    def test_defaults_are_explicit_in_the_plan(self):
        p = planning.plan_document(example('report-revenue'))
        orders = p['tables'][1]
        self.assertFalse(orders['columns'][0]['nullable'])
        self.assertEqual(orders['columns'][0]['emptyText'], 'reject')
        self.assertEqual(p['order'], ['customers', 'orders'])
        self.assertEqual(p['setup'], {'retain': False})
        self.assertEqual(planning.plan_document(example('load'))['setup'], {'retain': True})
        self.assertEqual(p['report']['numbers'], 'decimalString')

    def test_declaration_schema_parity_and_hoisted_records(self):
        for name, spec in model.OPTIONS.items():
            validate_specification(spec, name)
        schema = model.document_schema()
        self.assertEqual(set(schema['properties']), {'version', 'operation', *model.OPTIONS})
        self.assertEqual(set(schema['$defs']), set(model.NAMES.values()))
        self.assertEqual(schema['properties']['tables']['items'], {'$ref': '#/$defs/table'})
        self.assertEqual(schema['$defs']['operand']['additionalProperties'], False)
        self.assertEqual(set(model.DECLARATIONS), set(model.OPERATIONS))

    def test_unknown_fields_authored_sql_and_wrong_operation_fields_are_refused(self):
        for key in ('sql', 'script', 'plsql', 'dsn', 'password'):
            document = example('report-revenue')
            document[key] = 'x'
            self.fault(lambda: planning.plan_document(document), 'UNKNOWN_ARGUMENT')
        document = example('report-revenue')
        document['tables'][0]['sql'] = 'DROP TABLE x'
        self.fault(lambda: planning.plan_document(document), 'UNKNOWN_ARGUMENT')
        document = example('load')
        document['report'] = {'selects': []}
        self.fault(lambda: planning.plan_document(document), 'INVALID_ORACLE_OPERATION')
        document = example('inspect')
        document['tables'] = example('load')['tables']
        self.fault(lambda: planning.plan_document(document), 'INVALID_ORACLE_TABLE')
        self.fault(lambda: planning.plan_document({**example('inspect'), 'operation': 'ddl'}), 'UNKNOWN_FILTER')
        self.fault(lambda: planning.plan_document({**example('inspect'), 'version': 'schemaxis.oracle/2'}), 'UNSUPPORTED_VERSION')
        document = example('report-revenue')
        del document['report']
        self.fault(lambda: planning.plan_document(document), 'MISSING_ARGUMENT')

    def test_connection_references_names_never_values(self):
        document = example('inspect')
        document['connection'] = {'profile': 'prod_db', 'userVariable': 'SCHEMAXIS_ORACLE_A', 'passwordVariable': 'SCHEMAXIS_ORACLE_B', 'dsnVariable': 'SCHEMAXIS_ORACLE_C'}
        p = planning.plan_document(document)
        self.assertEqual((p['connection']['userVariable'], p['connection']['dsnVariable']), ('SCHEMAXIS_ORACLE_A', 'SCHEMAXIS_ORACLE_C'))
        # Long enough to pass the generic length rule, so the semantic prefix rule is what refuses it.
        self.assertGreaterEqual(len('HOME_DIRECTORY_SECRET_NAME'), 18)
        for bad in ({'profile': 'x', 'passwordVariable': 'HOME_DIRECTORY_SECRET_NAME'}, {'profile': 'Upper'}, {'profile': 'x', 'userVariable': 'SCHEMAXIS_ORACLE_A', 'passwordVariable': 'SCHEMAXIS_ORACLE_A'},
                    {'profile': 'x', 'dsnVariable': 'user/pass@host:1521/svc'}):
            document['connection'] = bad
            self.fault(lambda: planning.plan_document(document), 'INVALID_ORACLE_CONNECTION')
        for too_short in ({'profile': 'x', 'passwordVariable': 'HOME_SECRET'}, {'profile': 'x', 'callTimeoutSeconds': 0}):
            document['connection'] = too_short
            self.fault(lambda: planning.plan_document(document), 'INVALID_ARGUMENT')

    def test_identifier_injection_and_keywords_are_refused(self):
        for name in ('Orders', 'a; DROP TABLE x', 'x"y', 'select a', 'user', 'dual', '1abc', 'a' * 25, 'é'):
            document = example('report-revenue')
            document['tables'][0]['name'] = name
            self.fault(lambda: planning.plan_document(document), 'INVALID_ORACLE_NAME' if len(name) <= 24 else 'INVALID_ARGUMENT')

    def test_table_semantics(self):
        def mutate(edit, code='INVALID_ORACLE_TABLE'):
            document = example('report-revenue')
            edit(document)
            return self.fault(lambda: planning.plan_document(document), code)
        mutate(lambda d: d['tables'][0].update(primaryKey=['missing']))
        mutate(lambda d: d['tables'][0]['columns'][0].update(nullable=True))
        mutate(lambda d: d['tables'][0].update(columns=d['tables'][0]['columns'] + [{'name': 'flag', 'type': 'boolean'}], primaryKey=['flag']))
        mutate(lambda d: d['tables'][0]['columns'][1].pop('length'))
        mutate(lambda d: d['tables'][0]['columns'][1].update(length=1001))
        mutate(lambda d: d['tables'][0]['columns'][0].pop('precision'))
        mutate(lambda d: d['tables'][0]['columns'][1].update(precision=5))
        mutate(lambda d: d['tables'][0]['columns'][0].update(scale=11))
        mutate(lambda d: d['tables'][0]['columns'][2].update(fraction=3))
        mutate(lambda d: d['tables'][0]['columns'].append({'name': 'id', 'type': 'date'}))
        mutate(lambda d: d['tables'][1]['foreignKeys'][0].update(table='nowhere'))
        mutate(lambda d: d['tables'][1]['foreignKeys'][0].update(references=['name']))
        mutate(lambda d: d['tables'][1]['foreignKeys'][0].update(columns=['placed']))
        mutate(lambda d: d['tables'][1]['foreignKeys'][0].update(onDelete='setNull', columns=['id']))
        mutate(lambda d: d['tables'][0].update(external=True))
        mutate(lambda d: d['tables'][0].update(unique=[{'columns': ['id']}]))
        mutate(lambda d: d['tables'].append(copy.deepcopy(d['tables'][0])))
        mutate(lambda d: d['tables'][0]['checks'][0]['terms'][0]['left'].update(column='customers.nope'), 'INVALID_ORACLE_QUERY')

    def test_foreign_key_cycles_and_dependency_order(self):
        document = example('report-lines')
        p = planning.plan_document(document)
        self.assertEqual(p['order'], ['customers', 'orders', 'order_lines'])
        document['tables'].reverse()
        self.assertEqual(planning.plan_document(document)['order'], ['customers', 'orders', 'order_lines'])
        document['tables'][2]['foreignKeys'] = [{'columns': ['id'], 'table': 'order_lines', 'references': ['id']}]
        self.fault(lambda: planning.plan_document(document), 'INVALID_ORACLE_TABLE')

    def test_source_declarations_are_absolute_local_files_of_the_declared_format(self):
        for path in ('relative.json', 'https://example.org/x.json', '/tmp/x.csv'):
            document = example('load')
            document['tables'][0]['source']['path'] = path
            self.fault(lambda: planning.plan_document(document), 'INVALID_ORACLE_SOURCE')

    def test_query_semantics(self):
        def mutate(edit, code='INVALID_ORACLE_QUERY'):
            document = example('report-lines')
            edit(document)
            return self.fault(lambda: planning.plan_document(document), code)
        select_ = lambda d: d['report']['selects'][0]
        self.assertEqual(self.fault(lambda: planning.plan_document(example('bad-join')), 'INVALID_ORACLE_QUERY').location, '$.report.selects[0].joins[0].on[0]')
        mutate(lambda d: select_(d)['joins'][0].update(table='nowhere'))
        mutate(lambda d: select_(d)['joins'][0].update(alias='o'))
        mutate(lambda d: select_(d)['joins'][0]['on'][0].update(left='l.order_id', right='o.id'))
        mutate(lambda d: select_(d)['columns'][0].update(operand={'column': 'z.id'}))
        mutate(lambda d: select_(d)['columns'][0].update(operand={'column': 'o.nope'}))
        mutate(lambda d: select_(d)['columns'][0].update(operand={'column': 'o.id', 'measure': 'lines'}))
        mutate(lambda d: select_(d)['columns'].append({'name': 'extra', 'operand': {'column': 'o.total'}}))
        def where_on_measure(d):
            select_(d).pop('having')
            select_(d)['where'] = 'big'
        mutate(where_on_measure)
        def having_without_grouping(d):
            select_(d).update(groupBy=[], measures=[], columns=select_(d)['columns'][:1])
        mutate(having_without_grouping)
        mutate(lambda d: select_(d)['measures'][1].update(function='average', argument={'column': 'l.sku'}))
        mutate(lambda d: select_(d)['measures'][0].update(argument={'column': 'l.id'}))
        mutate(lambda d: select_(d)['measures'].append({'name': 'tz', 'function': 'maximum', 'argument': {'column': 'l.packed_at'}}))
        mutate(lambda d: select_(d)['groupBy'].append({'column': 'l.packed_at'}))
        mutate(lambda d: select_(d)['computed'].append({'name': 'bad', 'function': 'upper', 'arguments': [{'column': 'l.quantity'}]}))
        mutate(lambda d: select_(d)['computed'].append({'name': 'bad', 'function': 'add', 'arguments': [{'column': 'l.quantity'}]}))
        mutate(lambda d: select_(d)['computed'].append({'name': 'line_total', 'function': 'negate', 'arguments': [{'column': 'l.quantity'}]}))
        mutate(lambda d: select_(d)['computed'].append({'name': 'bad', 'function': 'negate', 'arguments': [{'derived': 'later'}]}))
        mutate(lambda d: select_(d)['computed'].append({'name': 'bad', 'function': 'negate', 'arguments': [{'column': 'l.quantity'}], 'zero': 'null'}))
        mutate(lambda d: d['report']['windows'][0].update(orderBy=[]))
        mutate(lambda d: d['report']['windows'][0].update(function='runningSum'))
        mutate(lambda d: d['report']['windows'][0].update(function='rowNumber', argument='amount'))
        mutate(lambda d: d['report']['windows'][0].update(partitionBy=['nope']))
        mutate(lambda d: d['report']['windows'][0].update(name='amount'))
        mutate(lambda d: d['report'].update(orderBy=[{'column': 'nope'}]))
        mutate(lambda d: d['report'].update(orderBy=[], limit=5))
        def shorter_second_select(d):
            second = copy.deepcopy(select_(d))
            second['columns'].pop()
            d['report']['selects'].append(second)
        mutate(shorter_second_select)
        mutate(lambda d: select_(d)['conditions'][0]['terms'][0].update(operator='isNull', right=number('1')))
        mutate(lambda d: select_(d)['conditions'][0]['terms'][0].update(right=text('x')))
        mutate(lambda d: select_(d)['conditions'][0]['terms'][0].update(right={'literal': {'type': 'number', 'value': None}}))
        mutate(lambda d: select_(d)['conditions'][0]['terms'][0].update(right={'literal': {'type': 'number', 'value': 'abc'}}), 'INVALID_ORACLE_VALUE')

    def test_empty_text_literal_is_refused_with_isnull_recovery(self):
        report = {'selects': [select([column('id')], where='w', conditions=[{'name': 'w', 'terms': [term({'column': 'items.name'}, 'equals', text(''))]}])]}
        fault = self.fault(lambda: planning.plan_document(items_document(report)), 'INVALID_ORACLE_VALUE')
        self.assertIn('isNull', fault.recovery)

    def test_transaction_semantics(self):
        def mutate(edit, code='INVALID_ORACLE_TRANSACTION'):
            document = example('mutate-transfer')
            edit(document)
            return self.fault(lambda: planning.plan_document(document), code)
        steps = lambda d: d['transaction']['steps']
        def whole_table_update(d):
            steps(d)[0].pop('expectRows')
            steps(d)[0].pop('where')
        mutate(whole_table_update)
        mutate(lambda d: steps(d).insert(2, {'kind': 'rollbackTo', 'name': 'never_made'}))
        mutate(lambda d: steps(d)[3].update(table='nowhere'))
        mutate(lambda d: steps(d)[3].update(rows=[[4, 'dave']]))
        mutate(lambda d: steps(d)[3].update(columns=['id', 'owner']))
        mutate(lambda d: steps(d)[3].update(rows=[[4, None, '1.00']]), 'INVALID_ORACLE_VALUE')
        mutate(lambda d: steps(d)[3].update(rows=[[4, 'dave', '1.001']]), 'INVALID_ORACLE_VALUE')
        mutate(lambda d: steps(d)[3].update(rows=[[4, '', '1.00']]), 'INVALID_ORACLE_VALUE')
        mutate(lambda d: steps(d)[3].update(rows=[[4, 'dave', 1.5]]), 'INVALID_ARGUMENT')
        mutate(lambda d: steps(d)[3].update(where='x'))
        mutate(lambda d: steps(d)[4].update(keys=['owner']))
        mutate(lambda d: steps(d)[4].update(keys=['id', 'owner']))
        mutate(lambda d: steps(d)[4].update(onMatched='ignore', onNotMatched='ignore'))
        mutate(lambda d: steps(d)[0]['set'][0].update(column='id'))
        mutate(lambda d: steps(d)[0]['set'].append({'column': 'balance', 'value': number('1')}))
        mutate(lambda d: steps(d)[0]['set'][0].update(value=text('x')))
        mutate(lambda d: steps(d)[0]['set'][0].update(value={'literal': {'type': 'number', 'value': None}}))
        mutate(lambda d: steps(d)[5].pop('expectRows'))
        def external_table(d):
            d['tables'][0].pop('source')
            d['tables'][0]['external'] = True
        mutate(external_table, 'INVALID_ORACLE_TRANSACTION')
        mutate(lambda d: d['transaction'].update(steps=[]), 'INVALID_ARGUMENT')

    def test_savepoints_follow_oracle_discard_rules(self):
        document = example('mutate-savepoint')
        steps = document['transaction']['steps']
        steps.insert(4, {'kind': 'savepoint', 'name': 'later_point'})
        steps.insert(5, {'kind': 'rollbackTo', 'name': 'after_debit'})
        steps.insert(6, {'kind': 'rollbackTo', 'name': 'later_point'})
        self.fault(lambda: planning.plan_document(document), 'INVALID_ORACLE_TRANSACTION')

    def test_live_database_runs_are_never_reusable_by_input_identity(self):
        import hashlib
        from schemaxis.adaptors import registry
        from schemaxis.adaptors.oracle import adaptor
        digests = adaptor.source_digests(example('report-revenue'))
        self.assertEqual(set(digests), {'customers', 'orders'})
        self.assertEqual(digests['customers'], hashlib.sha256((FIXTURES / 'customers.json').read_bytes()).hexdigest())
        # The route registers no reuse hook, so the shared service cannot treat a historical result as current.
        for operation in ('inspect', 'load', 'report-revenue', 'mutate-transfer'):
            document = example(operation)
            self.assertIsNone(registry.route_hook(document, 'reusableInputs'))


class ValueCodec(Base):
    def column(self, kind, **more):
        base = {'name': 'c', 'type': kind, 'precision': None, 'scale': None, 'length': None, 'fraction': None, 'nullable': True, 'emptyText': 'reject', 'scalePolicy': 'reject'}
        return {**base, **more}

    def parse(self, kind, raw, **more):
        return model.parse_value(self.column(kind, **more), raw)

    def refused(self, kind, raw, reason, **more):
        with self.assertRaises(model.ValueFault) as caught:
            self.parse(kind, raw, **more)
        self.assertEqual(caught.exception.reason, reason, str(caught.exception))

    def test_number_exactness_scale_and_precision(self):
        self.assertEqual(self.parse('number', '0.1'), Decimal('0.1'))
        self.assertEqual(self.parse('number', 12), Decimal(12))
        self.assertEqual(self.parse('number', '-0'), Decimal(0))
        self.assertEqual(model.canonical('number', self.parse('number', '80.00')), '80')
        self.assertEqual(model.canonical('number', self.parse('number', '1E+3')), '1000')
        self.assertEqual(model.canonical('number', self.parse('number', '0.000')), '0')
        big = '9' * 38
        self.assertEqual(model.canonical('number', self.parse('number', big)), big)
        self.refused('number', '9' * 39, 'precision')
        self.refused('number', 1.5, 'type')
        self.refused('number', True, 'type')
        self.refused('number', 'abc', 'type')
        self.refused('number', 'NaN', 'type')
        self.refused('number', '1.005', 'scale', precision=10, scale=2)
        self.assertEqual(self.parse('number', '1.005', precision=10, scale=2, scalePolicy='round'), Decimal('1.01'))
        self.assertEqual(self.parse('number', '-1.005', precision=10, scale=2, scalePolicy='round'), Decimal('-1.01'))
        self.refused('number', '100000000', 'precision', precision=10, scale=2)
        self.assertEqual(self.parse('number', '99999999.99', precision=10, scale=2), Decimal('99999999.99'))
        self.refused('number', '1000', 'precision', precision=3, scale=0)

    def test_exact_range_checks_do_not_depend_on_the_ambient_decimal_context(self):
        import decimal
        edge = '9999999999999999999999999999.9999999999'
        column = {'precision': 38, 'scale': 10}
        expected = Decimal(edge)
        for ambient in (28, 5, 80):
            with decimal.localcontext() as ctx:
                ctx.prec = ambient
                self.assertEqual(self.parse('number', edge, **column), expected)
                self.assertEqual(self.parse('number', '-' + edge, **column), expected.copy_negate())
                self.assertEqual(model.canonical('number', self.parse('number', edge, **column)), edge)
                self.assertEqual(model.canonical('number', self.parse('number', '0.0000000001', **column)), '0.0000000001')
                self.refused('number', '10000000000000000000000000000', 'precision', **column)
                self.refused('number', '-10000000000000000000000000000', 'precision', **column)
                self.refused('number', '1.00000000005', 'scale', **column)
                # Rounding that carries into a new leading digit overflows the declared precision.
                self.refused('number', '9999999999999999999999999999.99999999995', 'precision', scalePolicy='round', **column)
        self.refused('number', '1E+999999', 'precision')
        self.refused('number', '1E-999999', 'precision')
        self.refused('number', '1E+999999', 'precision', precision=5, scale=2)

    def test_text_unicode_empty_string_and_reserved_values(self):
        self.assertEqual(self.parse('varchar2', 'Zoë Café', length=10), 'Zoë Café')
        self.assertEqual(self.parse('varchar2', '😀' * 5, length=5), '😀' * 5)
        self.refused('varchar2', '😀' * 6, 'length', length=5)
        self.refused('varchar2', '', 'empty-text', length=5)
        self.assertIsNone(self.parse('varchar2', '', length=5, emptyText='null'))
        self.assertIsNone(self.parse('varchar2', None, length=5))
        self.refused('varchar2', 'a\x00b', 'text', length=5)
        self.refused('varchar2', 'a\ud800', 'text', length=5)
        self.refused('varchar2', '\\N', 'reserved', length=5)
        self.refused('varchar2', 5, 'type', length=5)
        hostile = "x'); DROP TABLE t;--"
        self.assertEqual(self.parse('varchar2', hostile, length=40), hostile)

    def test_temporal_policies(self):
        self.assertEqual(model.canonical('date', self.parse('date', '2026-02-03')), '2026-02-03T00:00:00')
        self.refused('date', '2026-02-03T10:00:00.5', 'loss')
        self.refused('date', '2026-02-03T10:00:00Z', 'loss')
        self.refused('date', '2026-02-30', 'range')
        self.refused('date', '03/02/2026', 'format')
        self.assertEqual(model.canonical('timestamp', self.parse('timestamp', '2026-02-03T10:00:00.120000', fraction=3)), '2026-02-03T10:00:00.12')
        self.refused('timestamp', '2026-02-03T10:00:00.1234', 'loss', fraction=3)
        self.assertEqual(model.canonical('timestamp', self.parse('timestamp', '2026-02-03T10:00:00.1230', fraction=3)), '2026-02-03T10:00:00.123')
        self.refused('timestamp', '2026-02-03T10:00:00+01:00', 'zone', fraction=3)
        self.assertEqual(model.canonical('timestampTz', self.parse('timestampTz', '2026-02-03T08:00:00Z', fraction=3)), '2026-02-03T08:00:00+00:00')
        self.assertEqual(model.canonical('timestampTz', self.parse('timestampTz', '2026-01-06T11:30:00.5+01:00', fraction=3)), '2026-01-06T11:30:00.5+01:00')
        self.refused('timestampTz', '2026-02-03T08:00:00', 'zone', fraction=3)
        self.refused('timestampTz', '2026-02-03T08:00:00Europe/London', 'format', fraction=3)
        self.refused('timestampTz', '2026-02-03T08:00:00+15:00', 'range', fraction=3)
        self.refused('timestampTz', '2026-02-03', 'zone', fraction=3)

    def test_raw_and_boolean_and_csv_null_conventions(self):
        self.assertEqual(self.parse('raw', '00FFab', length=4), bytes([0, 255, 171]))
        self.assertEqual(model.canonical('raw', bytes([0, 255, 171])), '00ffab')
        self.refused('raw', '', 'format', length=4)
        self.refused('raw', '0f0f0f0f0f', 'length', length=4)
        self.refused('raw', 'xyz', 'format', length=4)
        self.assertIs(self.parse('boolean', True), True)
        self.refused('boolean', 1, 'type')
        self.refused('boolean', 'true', 'type')
        self.assertIsNone(model.parse_value(self.column('varchar2', length=4), '', csv=True))
        self.assertIs(model.parse_value(self.column('boolean'), 'false', csv=True), False)
        self.assertEqual(model.parse_value(self.column('number'), '3.14', csv=True), Decimal('3.14'))

    def test_computed_results_may_exceed_the_38_digit_storage_limit(self):
        wide = '0.' + '3' * 40
        self.assertEqual(model.from_native('number', wide, result=True), Decimal(wide))
        self.assertEqual(model.number_text(model.from_native('number', wide, result=True)), wide)
        self.assertEqual(model.from_native('number', Decimal('1E-10'), result=True), Decimal('1E-10'))
        with self.assertRaises(model.ValueFault):
            model.from_native('number', wide)                 # storage policy still refuses 40 digits
        for refused in ('9' * 41, '9' * 81, '1.' + '0' * 5 + '7' * 40, 'NaN', 'abc', '1E+9999'):
            with self.assertRaises(model.ValueFault):
                model.from_native('number', refused, result=True)

    def test_result_digit_limit_is_counted_before_any_rounding_whatever_the_ambient_context(self):
        import decimal
        self.assertEqual(model.significant_digits(Decimal('9' * 81)), 81)
        self.assertEqual(model.significant_digits(Decimal('1.500')), 2)
        self.assertEqual(model.significant_digits(Decimal('100')), 1)
        self.assertEqual(model.significant_digits(Decimal(0)), 0)
        for ambient in (5, 28, 40, 80, 200):
            with decimal.localcontext() as ctx:
                ctx.prec = ambient
                forty, forty_one = '9' * 40, '9' * 41
                self.assertEqual(model.from_native('number', forty, result=True), Decimal(forty))
                with self.assertRaises(model.ValueFault) as caught:
                    model.from_native('number', forty_one, result=True)
                self.assertEqual(caught.exception.reason, 'precision')
                with self.assertRaises(model.ValueFault):            # 81 digits must not round down to a legal 80 first
                    model.from_native('number', '9' * 81, result=True)

    def test_storing_a_computed_value_rounds_to_38_digits_then_applies_the_column(self):
        unconstrained = self.column('number')
        self.assertEqual(model.store_value(unconstrained, Decimal('0.' + '3' * 40)), Decimal('0.' + '3' * 38))
        self.assertEqual(model.store_value(unconstrained, Decimal('0.' + '6' * 39 + '7')), Decimal('0.' + '6' * 37 + '7'))
        scaled = self.column('number', precision=12, scale=2)
        for value, reason in ((Decimal('99.985'), 'scale'), (Decimal('1E+10'), 'precision')):
            with self.assertRaises(model.ValueFault) as caught:
                model.store_value(scaled, value)
            self.assertEqual(caught.exception.reason, reason)
        rounding = self.column('number', precision=12, scale=2, scalePolicy='round')
        self.assertEqual(model.store_value(rounding, Decimal('99.985')), Decimal('99.99'))
        self.assertEqual(model.store_value(rounding, Decimal('99.995')), Decimal(100))      # Oracle stores 100 for CAST(99.995 AS NUMBER(12,2))
        self.assertEqual(model.store_value(rounding, Decimal('-99.985')), Decimal('-99.99'))
        text_column = self.column('varchar2', length=3)
        self.assertEqual(model.store_value(text_column, 'abc'), 'abc')
        with self.assertRaises(model.ValueFault) as caught:
            model.store_value(text_column, 'abcd')
        self.assertEqual(caught.exception.reason, 'length')
        self.assertIsNone(model.store_value(text_column, None))
        stamp = self.column('timestamp', fraction=3)
        with self.assertRaises(model.ValueFault):
            model.store_value(stamp, model.parse_stamp('2026-01-01T00:00:00.123456', 'timestamp', 6))

    def test_bc_dates_are_refused_and_oracle_sign_and_padding_forms_are_read(self):
        self.assertEqual(model.from_native('date', ' 2026-02-03T00:00:00').year, 2026)
        with self.assertRaises(model.ValueFault) as caught:
            model.from_native('date', '-0001-01-01T00:00:00')
        self.assertEqual(caught.exception.reason, 'range')
        self.assertEqual(model.canonical('date', model.parse_stamp('0005-03-04', 'date', 0)), '0005-03-04T00:00:00')
        self.assertEqual(model.canonical('date', model.parse_stamp('0999-12-31', 'date', 0)), '0999-12-31T00:00:00')

    def test_native_text_decodes_to_the_same_values(self):
        self.assertEqual(model.from_native('number', '.5'), Decimal('0.5'))
        self.assertEqual(model.from_native('number', '-12.250'), Decimal('-12.25'))
        stamp = model.from_native('timestampTz', '2026-01-06T11:30:00.500000+01:00')
        self.assertEqual(model.canonical('timestampTz', stamp), '2026-01-06T11:30:00.5+01:00')
        self.assertEqual(model.from_native('date', '2026-02-03T00:00:00').year, 2026)
        self.assertEqual(model.from_native('raw', 'ff'), b'\xff')

    def test_sort_key_orders_nulls_last_and_time_zones_by_instant(self):
        values = [model.from_native('timestampTz', '2026-01-01T01:00:00.000000+02:00'), model.from_native('timestampTz', '2025-12-31T23:30:00.000000+00:00'), None]
        ordered = sorted(values, key=lambda v: model.sort_key('timestampTz', v))
        # 01:00+02:00 is 23:00Z, which precedes 23:30Z; NULL sorts last.
        self.assertEqual([model.canonical('timestampTz', v) for v in ordered[:2]], ['2026-01-01T01:00:00+02:00', '2025-12-31T23:30:00+00:00'])
        self.assertIsNone(ordered[2])


class SourceCapture(Base):
    def table(self, fmt='json'):
        p = planning.plan_document(example('report-lines'))
        table = copy.deepcopy(p['tables'][0])
        table['source'] = {'path': '/x.' + fmt, 'format': fmt}
        return table

    def parse(self, data, fmt='json'):
        return reference.parse_source(self.table(fmt), data, '$.tables[0].source')

    def test_fixture_rows_are_typed_and_exact(self):
        rows = self.parse((FIXTURES / 'customers.json').read_bytes())
        self.assertEqual([r['credit'] for r in rows], [Decimal('1500.5'), Decimal(200), Decimal(0), Decimal('75.25')])
        self.assertIsNone(rows[3]['region'])
        self.assertEqual(rows[2]['name'], '東京商事')

    def test_hostile_json_and_csv_sources(self):
        good = {'id': 1, 'name': 'a', 'region': None, 'credit': '1'}
        dump = lambda **change: json.dumps([{**good, **change}]).encode()
        refused = [
            (b'[{"id":1,"id":2,"name":"a","region":null,"credit":"1"}]', 'INVALID_ORACLE_SOURCE'),
            (b'[{"id":1,"name":"a","region":null,"credit":NaN}]', 'INVALID_ORACLE_SOURCE'),
            (b'{"id":1}', 'INVALID_ORACLE_SOURCE'), (b'[1]', 'INVALID_ORACLE_SOURCE'), (b'\xff\xfe', 'INVALID_ORACLE_SOURCE'),
            (dump(extra=1), 'INVALID_ORACLE_SOURCE'),
            (json.dumps([{k: v for k, v in good.items() if k != 'name'}]).encode(), 'INVALID_ORACLE_SOURCE'),
            (dump(id=1.5), 'INVALID_ORACLE_VALUE'), (dump(id=True), 'INVALID_ORACLE_VALUE'), (dump(name=None), 'INVALID_ORACLE_VALUE'),
            (dump(name=''), 'INVALID_ORACLE_VALUE'), (dump(credit='1.234'), 'INVALID_ORACLE_VALUE'), (dump(name='\\N'), 'INVALID_ORACLE_VALUE')]
        for data, code in refused:
            self.fault(lambda: self.parse(data), code)
        self.fault(lambda: self.parse(b'id,name,region,credit\n1,a,,5,6\n', 'csv'), 'INVALID_ORACLE_SOURCE')
        self.fault(lambda: self.parse(b'id,name\n1,a\n', 'csv'), 'INVALID_ORACLE_SOURCE')
        self.fault(lambda: self.parse(b'', 'csv'), 'INVALID_ORACLE_SOURCE')
        rows = self.parse(b'id,name,region,credit\n1,"a,b",,5\n', 'csv')
        self.assertEqual((rows[0]['name'], rows[0]['region']), ('a,b', None))
        too_many = json.dumps([{**good, 'id': i} for i in range(model.MAX_ROWS + 1)]).encode()
        self.assertEqual(self.fault(lambda: self.parse(too_many), 'INVALID_ORACLE_SOURCE').observed['reason'], 'too-many-rows')

    def test_value_faults_name_table_row_and_column(self):
        data = json.dumps([{'id': 1, 'name': 'a', 'region': None, 'credit': '1'}, {'id': 2, 'name': 'b', 'region': None, 'credit': '1.234'}]).encode()
        fault = self.fault(lambda: self.parse(data), 'INVALID_ORACLE_VALUE')
        self.assertEqual((fault.observed['table'], fault.observed['row'], fault.observed['column'], fault.observed['reason']), ('customers', 1, 'credit', 'scale'))

    def test_captured_rows_that_break_constraints_are_found_before_native_work(self):
        from schemaxis.adaptors.oracle import adaptor
        p = planning.plan_document(example('report-lines'))
        data = data_for(p)
        adaptor.check_initial(p, data)
        orphan = copy.deepcopy(data)
        orphan['order_lines'][0]['order_id'] = Decimal(999)
        self.fault(lambda: adaptor.check_initial(p, orphan), 'INVALID_ORACLE_VALUE')
        duplicate = copy.deepcopy(data)
        duplicate['customers'].append(dict(duplicate['customers'][0]))
        self.fault(lambda: adaptor.check_initial(p, duplicate), 'INVALID_ORACLE_VALUE')
        negative = planning.plan_document(example('report-revenue'))
        bad = data_for(negative)
        bad['customers'][0]['credit'] = Decimal('-1')
        self.assertEqual(self.fault(lambda: adaptor.check_initial(negative, bad), 'INVALID_ORACLE_VALUE').observed['constraint'], 'check')


class SqlGeneration(Base):
    def test_values_are_binds_in_text_order_and_never_spliced(self):
        hostile = "x'); DROP TABLE items;--"
        report = {'selects': [select([column('id')], where='w', conditions=[{'name': 'w', 'combine': 'or', 'terms': [
            term({'column': 'items.name'}, 'equals', text(hostile)), term({'column': 'items.qty'}, 'between', number('1'), upper=number('9')),
            term({'column': 'items.name'}, 'startsWith', text('ab')), term({'column': 'items.id'}, 'in', values=[number('1'), number('2')])]}])]}
        p = planning.plan_document(items_document(report))
        text_, binds, columns = sql.report_sql(p['report'])
        self.assertNotIn('DROP TABLE', text_)
        self.assertNotIn(hostile, text_)
        self.assertEqual([int(n) for n in re.findall(r':(\d+)', text_)], list(range(1, len(binds) + 1)))
        self.assertEqual(binds[0], {'t': 'varchar', 'v': hostile})
        self.assertEqual(len(binds), 7)
        self.assertEqual(columns, [{'name': 'id', 'kind': 'number'}])
        self.assertEqual(binds[1], {'t': 'number', 'v': '1'})

    def test_grouped_selects_aggregate_over_aliased_keys_so_binds_are_never_repeated_in_group_by(self):
        p = planning.plan_document(example('report-lines'))
        text_, binds, _ = sql.report_sql(p['report'])
        self.assertIn('GROUP BY "G"."K1"', text_)
        self.assertIn('HAVING', text_)
        self.assertIn('RANK() OVER (ORDER BY "Q"."AMOUNT" DESC NULLS LAST)', text_)
        self.assertEqual([int(n) for n in re.findall(r':(\d+)', text_)], list(range(1, len(binds) + 1)))
        self.assertEqual(binds, [{'t': 'number', 'v': '90'}])
        self.assertTrue(text_.startswith('SELECT '))

    def test_outputs_are_textualised_with_fixed_masks_and_ordering_is_explicit(self):
        report = {'selects': [select([column('id'), column('name'), column('qty')])], 'orderBy': [{'column': 'qty', 'direction': 'descending', 'nulls': 'first'}], 'limit': 5, 'offset': 2}
        text_, _, _ = sql.report_sql(planning.plan_document(items_document(report))['report'])
        self.assertIn('ORDER BY "R"."QTY" DESC NULLS FIRST OFFSET 2 ROWS FETCH NEXT 5 ROWS ONLY', text_)
        p = planning.plan_document(example('load'))
        self.assertIn("TO_CHAR(\"PLACED\", 'SYYYY-MM-DD\"T\"HH24:MI:SS')", sql.table_readback_sql(p['tables'][1]))
        self.assertIn("TO_DATE(:1, 'YYYY-MM-DD\"T\"HH24:MI:SS')", sql.wrap('date', ':1'))
        self.assertIn('TZH:TZM', sql.table_readback_sql(p['tables'][2]))

    def test_ddl_declares_constraints_with_deterministic_names(self):
        p = planning.plan_document(example('report-lines'))
        customers = sql.create_table_sql(p['tables'][0])
        self.assertTrue(customers.startswith('CREATE TABLE "CUSTOMERS" ("ID" NUMBER(10,0) NOT NULL, "NAME" VARCHAR2(40 CHAR) NOT NULL, "REGION" VARCHAR2(12 CHAR), "CREDIT" NUMBER(12,2) NOT NULL'))
        self.assertIn('CONSTRAINT "CUSTOMERS_PK" PRIMARY KEY ("ID")', customers)
        lines = sql.create_table_sql(p['tables'][2])
        self.assertIn('"PACKED_AT" TIMESTAMP(3) WITH TIME ZONE', lines)
        self.assertIn('CONSTRAINT "ORDER_LINES_FK1" FOREIGN KEY ("ORDER_ID") REFERENCES "ORDERS" ("ID") ON DELETE CASCADE', lines)
        checked = sql.create_table_sql(planning.plan_document(example('report-revenue'))['tables'][0])
        self.assertIn('CONSTRAINT "CUSTOMERS_C1" CHECK (("CREDIT" >= 0))', checked)
        marker = sql.run_marker('0123456789abcdef')
        self.assertEqual(marker, 'schemaxis-oracle:run:0123456789abcdef')
        self.assertEqual(sql.comment_sql(p['tables'][0], marker), "COMMENT ON TABLE \"CUSTOMERS\" IS 'schemaxis-oracle:run:0123456789abcdef'")
        self.assertNotEqual(sql.comment_sql(p['tables'][0], sql.run_marker('f' * 16)), sql.comment_sql(p['tables'][0], marker))
        self.assertEqual(sql.drop_sql('customers'), 'DROP TABLE "CUSTOMERS" PURGE')

    def test_inline_ddl_literals_escape_quotes_and_refuse_control_characters(self):
        document = example('report-revenue')
        document['tables'][0]['checks'] = [{'name': 'tame', 'terms': [{'left': {'column': 'customers.name'}, 'operator': 'notEquals', 'right': text("O'Brien; DROP")}]}]
        statement = sql.create_table_sql(planning.plan_document(document)['tables'][0])
        self.assertIn("<> 'O''Brien; DROP'", statement)
        self.assertRaises(ValueError, sql.quote_text, 'a\nb')

    def test_dml_statements_and_typed_bind_wrappers(self):
        p = planning.plan_document(example('mutate-transfer'))
        steps = p['transaction']['steps']
        kinds = {c['name']: c['type'] for c in p['tables'][0]['columns']}
        text_, types = sql.insert_sql('accounts', ['id', 'owner', 'balance'], kinds)
        self.assertEqual((text_, types), ('INSERT INTO "ACCOUNTS" ("ID", "OWNER", "BALANCE") VALUES (:1, :2, :3)', ['number', 'varchar', 'number']))
        merge, types = sql.merge_sql(steps[4], kinds)
        self.assertIn('MERGE INTO "ACCOUNTS" "TGT$" USING (SELECT :1 AS "ID", :2 AS "OWNER", :3 AS "BALANCE" FROM DUAL) "SRC$" ON ("TGT$"."ID" = "SRC$"."ID")', merge)
        self.assertIn('WHEN MATCHED THEN UPDATE SET "TGT$"."OWNER" = "SRC$"."OWNER", "TGT$"."BALANCE" = "SRC$"."BALANCE"', merge)
        update, binds = sql.dml_sql(steps[0])
        self.assertEqual(update, 'UPDATE "ACCOUNTS" SET "BALANCE" = ("ACCOUNTS"."BALANCE" - :1) WHERE (("ACCOUNTS"."ID" = :2))')
        self.assertEqual(binds, [{'t': 'number', 'v': '25'}, {'t': 'number', 'v': '1'}])
        count, _ = sql.dml_sql(steps[5])
        self.assertTrue(count.startswith('SELECT COUNT(*) AS "N" FROM "ACCOUNTS" WHERE'))
        self.assertEqual(sql.row_binds(['id', 'balance'], kinds, ['4', '10']), ['4', '10'])
        self.assertEqual(sql.bind_text('timestampTz', '2026-01-06T11:30:00.5+01:00'), '2026-01-06T11:30:00.500000+01:00')
        self.assertEqual(sql.wrap('raw', ':1'), 'HEXTORAW(:1)')

    def test_dictionary_queries_bind_names_and_never_splice_them(self):
        queries = sql.catalog_queries(['customers', "x'; drop"])
        for query in queries.values():
            # The hostile name is data: it is bound (upper-cased) and never appears in the statement text.
            self.assertNotIn("X'; DROP", query['sql'].upper())
            self.assertNotIn(';', query['sql'])
            self.assertEqual(len(query['binds']), 2)
            self.assertEqual(query['binds'][1]['v'], "X'; DROP")
        self.assertEqual(sql.catalog_queries([])['tables']['binds'], [])


class Reference(Base):
    def report(self, name):
        p = planning.plan_document(example(name))
        rows, kinds = reference.run_report(p['report'], data_for(p))
        return cells(kinds, rows)

    def test_left_join_group_and_null_semantics(self):
        self.assertEqual(self.report('report-revenue'), [['north', '3', '350.5'], ['south', '1', '80'], [None, '0', None]])

    def test_full_outer_join_keeps_unmatched_rows_on_both_sides(self):
        self.assertEqual(self.report('report-variant'), [['north', '3', '350.5'], ['south', '1', '80'], [None, '1', '5.55']])

    def test_three_table_join_derived_value_having_and_rank_window(self):
        self.assertEqual(self.report('report-lines'), [['11', '1', '10', '250.4', '1'], ['10', '2', '3', '100.1', '2']])

    def test_inner_join_omits_unmatched_and_right_join_keeps_them(self):
        document = example('report-variant')
        select_ = document['report']['selects'][0]
        select_['joins'][0]['type'] = 'inner'
        p = planning.plan_document(document)
        rows, kinds = reference.run_report(p['report'], data_for(p))
        self.assertEqual(cells(kinds, rows), [['north', '3', '350.5'], ['south', '1', '80']])
        select_['joins'][0]['type'] = 'right'
        p = planning.plan_document(document)
        rows, kinds = reference.run_report(p['report'], data_for(p))
        self.assertEqual(cells(kinds, rows), [['north', '3', '350.5'], ['south', '1', '80'], [None, '0', None]])

    def test_three_valued_logic(self):
        rows = [[1, 'abc', '1'], [2, None, None], [3, 'abd', '2'], [4, 'x', '5']]
        ids = lambda where, *conds: [r[0] for r in run_items({'selects': [select([column('id')], where='w', conditions=[{'name': 'w', **where}])]}, rows)]
        eq1 = term({'column': 'items.qty'}, 'equals', number('1'))
        self.assertEqual(ids({'terms': [eq1]}), ['1'])
        self.assertEqual(ids({'terms': [{**eq1, 'negate': True}]}), ['3', '4'])
        self.assertEqual(ids({'terms': [term({'column': 'items.qty'}, 'notEquals', number('1'))]}), ['3', '4'])
        self.assertEqual(ids({'terms': [term({'column': 'items.qty'}, 'isNull')]}), ['2'])
        self.assertEqual(ids({'terms': [{**term({'column': 'items.qty'}, 'isNull'), 'negate': True}]}), ['1', '3', '4'])
        self.assertEqual(ids({'combine': 'or', 'terms': [eq1, term({'column': 'items.name'}, 'startsWith', text('abd'))]}), ['1', '3'])
        self.assertEqual(ids({'terms': [term({'column': 'items.qty'}, 'in', values=[number('1'), number('2')])]}), ['1', '3'])
        self.assertEqual(ids({'terms': [term({'column': 'items.qty'}, 'between', number('2'), upper=number('5'))]}), ['3', '4'])
        self.assertEqual(ids({'terms': [term({'column': 'items.name'}, 'contains', text('b'))]}), ['1', '3'])
        self.assertEqual(ids({'negate': True, 'terms': [eq1]}), ['3', '4'])
        self.assertEqual(ids({'combine': 'or', 'terms': [{**term({'column': 'items.qty'}, 'in', values=[number('7')]), 'negate': True}]}), ['1', '3', '4'])

    def test_named_condition_references_and_conditional_values(self):
        rows = [[1, 'abc', '1'], [2, None, None], [3, 'abd', '2']]
        report = {'selects': [select(
            [column('id'), {'name': 'label', 'operand': {'derived': 'label'}}],
            computed=[{'name': 'label', 'function': 'conditional', 'arguments': [text('big'), text('small')],
                       'when': {'name': 'big_qty', 'terms': [term({'column': 'items.qty'}, 'greaterThan', number('1'))]}}])]}
        self.assertEqual(run_items(report, rows), [['1', 'small'], ['2', 'small'], ['3', 'big']])
        chained = {'selects': [select([column('id')], where='both', conditions=[
            {'name': 'has_qty', 'terms': [{**term({'column': 'items.qty'}, 'isNull'), 'negate': True}]},
            {'name': 'both', 'terms': [{'condition': 'has_qty'}, term({'column': 'items.name'}, 'startsWith', text('ab'))]}])]}
        self.assertEqual(run_items(chained, rows), [['1'], ['3']])

    def test_derived_functions_follow_oracle_null_and_empty_string_rules(self):
        rows = [[1, '  ', '7.5'], [2, None, '-7'], [3, 'ab', '0'], [4, 'Zoë', '2.5']]
        derived = lambda name, function, *args, **more: {'name': name, 'function': function, 'arguments': list(args), **more}
        name, qty = {'column': 'items.name'}, {'column': 'items.qty'}
        report = {'selects': [select([column('id')] + [{'name': n, 'operand': {'derived': n}} for n in ('trimmed', 'joined', 'size', 'part', 'twice', 'rounded', 'cut', 'modded', 'floored', 'ceiled', 'absolute', 'neg')],
            computed=[derived('trimmed', 'trim', name), derived('joined', 'concat', name, text('!')), derived('size', 'length', name), derived('part', 'substring', name, number('2'), number('2')),
                      derived('twice', 'multiply', qty, number('2')), derived('rounded', 'round', qty, digits=0), derived('cut', 'truncate', qty, digits=0),
                      derived('modded', 'modulo', qty, number('2')), derived('floored', 'floor', qty), derived('ceiled', 'ceiling', qty), derived('absolute', 'abs', qty), derived('neg', 'negate', qty)])]}
        result = run_items(report, rows)
        # Columns: id, trimmed, joined, size, part, twice, rounded, cut, modded, floored, ceiled, absolute, neg.
        self.assertEqual(result[0], ['1', None, '  !', '2', ' ', '15', '8', '7', '1.5', '7', '8', '7.5', '-7.5'])
        self.assertEqual(result[1], ['2', None, '!', None, None, '-14', '-7', '-7', '-1', '-7', '-7', '7', '7'])
        self.assertEqual(result[2], ['3', 'ab', 'ab!', '2', 'b', '0', '0', '0', '0', '0', '0', '0', '0'])
        self.assertEqual(result[3], ['4', 'Zoë', 'Zoë!', '3', 'oë', '5', '3', '2', '0.5', '2', '3', '2.5', '-2.5'])

    def test_round_half_away_from_zero_negative_digits_and_modulo_by_zero(self):
        rows = [[1, 'a', '2.5'], [2, 'a', '-2.5'], [3, 'a', '1250']]
        report = {'selects': [select([column('id'), {'name': 'r', 'operand': {'derived': 'r'}}, {'name': 't', 'operand': {'derived': 't'}}, {'name': 'm', 'operand': {'derived': 'm'}}],
            computed=[{'name': 'r', 'function': 'round', 'arguments': [{'column': 'items.qty'}], 'digits': -2}, {'name': 't', 'function': 'round', 'arguments': [{'column': 'items.qty'}]},
                      {'name': 'm', 'function': 'modulo', 'arguments': [{'column': 'items.qty'}, number('0')]}])]}
        self.assertEqual(run_items(report, rows), [['1', '0', '3', '2.5'], ['2', '0', '-3', '-2.5'], ['3', '1300', '1250', '1250']])

    def test_division_policy_and_38_digit_precision(self):
        rows = [[1, 'a', '1'], [2, 'a', '0']]
        for zero, expected in (('error', None), ('null', [['1', '1'], ['2', None]])):
            report = {'selects': [select([column('id'), {'name': 'q', 'operand': {'derived': 'q'}}], computed=[{'name': 'q', 'function': 'divide', 'arguments': [number('1'), {'column': 'items.qty'}], 'zero': zero}])]}
            if expected is None:
                with self.assertRaises(reference.Predicted) as caught:
                    run_items(report, rows)
                self.assertEqual(caught.exception.errors, (1476,))
            else:
                self.assertEqual(run_items(report, rows), expected)
        report = {'selects': [select([{'name': 'third', 'operand': {'derived': 'third'}}], computed=[{'name': 'third', 'function': 'divide', 'arguments': [number('1'), number('3')]}])]}
        # Native Oracle: TO_CHAR(1/3) = .3333333333333333333333333333333333333333 (40 digits); 2/3 ends in ...67 at digit 40.
        self.assertEqual(run_items(report, [[1, 'a', '1']]), [['0.' + '3' * 40]])
        report['selects'][0]['computed'][0]['arguments'] = [number('2'), number('3')]
        self.assertEqual(run_items(report, [[1, 'a', '1']]), [['0.' + '6' * 39 + '7']])

    def test_text_case_conversion_is_refused_when_not_verifiable(self):
        report = {'selects': [select([{'name': 'u', 'operand': {'derived': 'u'}}], computed=[{'name': 'u', 'function': 'upper', 'arguments': [{'column': 'items.name'}]}])]}
        self.assertEqual(run_items(report, [[1, 'abc', None]]), [['ABC']])
        with self.assertRaises(reference.Unverifiable):
            run_items(report, [[1, 'straße', None]])

    def test_date_functions(self):
        columns = [{'name': 'due', 'type': 'date', 'nullable': True}]
        document = items_document(None, extra_columns=columns)
        document['report'] = {'selects': [select([column('id'), {'name': 'later', 'operand': {'derived': 'later'}}, {'name': 'year', 'operand': {'derived': 'year'}}, {'name': 'day', 'operand': {'derived': 'day'}},
            {'name': 'start', 'operand': {'derived': 'start'}}], computed=[
            {'name': 'later', 'function': 'addDays', 'arguments': [{'column': 'items.due'}, number('30')]}, {'name': 'year', 'function': 'extractYear', 'arguments': [{'column': 'items.due'}]},
            {'name': 'day', 'function': 'extractDay', 'arguments': [{'column': 'items.due'}]}, {'name': 'start', 'function': 'truncateDay', 'arguments': [{'column': 'items.due'}]}])]}
        p = planning.plan_document(document)
        row = reference.typed_row(p['tables'][0], ['id', 'due'], [1, '2026-01-31T13:45:10'])
        rows, kinds = reference.run_report(p['report'], {'items': [row]})
        self.assertEqual(cells(kinds, rows), [['1', '2026-03-02T13:45:10', '2026', '31', '2026-01-31T00:00:00']])

    def test_group_measures_distinct_and_global_aggregates(self):
        rows = [[1, 'a', '1.5'], [2, 'a', '2.5'], [3, 'b', None], [4, None, '4'], [5, None, '4']]
        measures = [{'name': n, 'function': f, 'argument': {'column': 'items.qty'}} for n, f in (('c', 'count'), ('d', 'countDistinct'), ('s', 'sum'), ('a', 'average'), ('lo', 'minimum'), ('hi', 'maximum'))]
        measures.append({'name': 'rows', 'function': 'countAll'})
        grouped = {'selects': [select([column('name')] + [{'name': m['name'], 'operand': {'measure': m['name']}} for m in measures], groupBy=[{'column': 'items.name'}], measures=measures)], 'orderBy': [{'column': 'name'}]}
        self.assertEqual(run_items(grouped, rows), [['a', '2', '2', '4', '2', '1.5', '2.5', '2'], ['b', '0', '0', None, None, None, None, '1'], [None, '2', '1', '8', '4', '4', '4', '2']])
        grouped_all = {'selects': [select([{'name': 'n', 'operand': {'measure': 'rows'}}, {'name': 's', 'operand': {'measure': 's'}}], measures=measures)]}
        self.assertEqual(run_items(grouped_all, rows), [['5', '12']])
        self.assertEqual(run_items(grouped_all, []), [['0', None]])
        keyed_empty = {'selects': [select([column('name'), {'name': 'n', 'operand': {'measure': 'rows'}}], groupBy=[{'column': 'items.name'}], measures=measures)]}
        self.assertEqual(run_items(keyed_empty, []), [])

    def test_average_uses_40_digits_and_tolerance_only_for_inexact_reports(self):
        rows = [[1, 'a', '1'], [2, 'a', '0'], [3, 'a', '0']]
        measures = [{'name': 'a', 'function': 'average', 'argument': {'column': 'items.qty'}}]
        report = {'selects': [select([{'name': 'a', 'operand': {'measure': 'a'}}], measures=measures)]}
        self.assertEqual(run_items(report, rows), [['0.' + '3' * 40]])
        p = planning.plan_document(items_document(report))
        want = [[Decimal('0.' + '3' * 40)]]
        near = [[Decimal('0.' + '3' * 36 + '4' * 2)]]
        self.assertIsNone(reference.compare_result(p['report'], near, want, ['number']))
        self.assertIn('differs', reference.compare_result(p['report'], [[Decimal('0.34')]], want, ['number']))
        exact = planning.plan_document(items_document({'selects': [select([column('qty')])]}))
        self.assertIn('differs', reference.compare_result(exact['report'], [[Decimal('1.0000000000000000000000000000000000001')]], [[Decimal(1)]], ['number']))

    def test_computed_results_beyond_38_digits_compare_at_tolerance_but_stored_values_stay_exact(self):
        third = Decimal('0.' + '3' * 38)
        forty = Decimal('0.' + '3' * 40)
        average = planning.plan_document(items_document({'selects': [select([{'name': 'a', 'operand': {'measure': 'a'}}], measures=[{'name': 'a', 'function': 'average', 'argument': {'column': 'items.qty'}}])]}))
        self.assertTrue(reference.inexact(average['report']))
        self.assertIsNone(reference.compare_result(average['report'], [[forty]], [[third]], ['number']))
        total = planning.plan_document(items_document({'selects': [select([{'name': 's', 'operand': {'measure': 's'}}], measures=[{'name': 's', 'function': 'sum', 'argument': {'column': 'items.qty'}}])]}))
        self.assertTrue(reference.inexact(total['report']))
        self.assertIn('differs', reference.compare_result(total['report'], [[Decimal('350.6')]], [[Decimal('350.5')]], ['number']))
        for expression in ('multiply', 'add', 'subtract', 'divide'):
            document = items_document({'selects': [select([{'name': 'v', 'operand': {'derived': 'v'}}], computed=[{'name': 'v', 'function': expression, 'arguments': [{'column': 'items.qty'}, number('2')]}])]})
            self.assertTrue(reference.inexact(planning.plan_document(document)['report']), expression)
        bare = planning.plan_document(items_document({'selects': [select([column('qty')])]}))
        self.assertFalse(reference.inexact(bare['report']))

    def test_reference_results_ignore_the_ambient_decimal_context(self):
        import decimal
        rows = [[1, 'a', '1'], [2, 'a', '0'], [3, 'a', '0']]
        report = {'selects': [select([{'name': 'a', 'operand': {'measure': 'a'}}], measures=[{'name': 'a', 'function': 'average', 'argument': {'column': 'items.qty'}}])]}
        with decimal.localcontext() as ctx:
            ctx.prec = 5
            ctx.rounding = decimal.ROUND_DOWN
            self.assertEqual(run_items(report, rows), [['0.' + '3' * 40]])
            p = planning.plan_document(items_document(report))
            near = [[Decimal('0.' + '3' * 36 + '44')]]
            self.assertIsNone(reference.compare_result(p['report'], near, [[Decimal('0.' + '3' * 40)]], ['number']))
            self.assertTrue(reference.numbers_match(Decimal('9' * 38), Decimal('9' * 38), True))
            self.assertFalse(reference.numbers_match(Decimal('9' * 37 + '8'), Decimal('1'), True))

    def test_native_row_order_is_verified_including_null_placement(self):
        def check(rows, **order):
            report = planning.plan_document(items_document({'selects': [select([column('id'), column('qty')])], 'orderBy': [{'column': 'qty', **order}]}))['report']
            return reference.check_native_order(report, [[Decimal(i), None if q is None else Decimal(q)] for i, q in rows], ['number', 'number'])
        self.assertIsNone(check([(1, 1), (2, 5), (3, 5), (4, None)]))                                   # ascending, NULLs last (the default)
        self.assertIn('out of order', check([(1, 5), (2, 1)]))
        self.assertIn('NULL belongs last', check([(1, None), (2, 1)]))
        self.assertIsNone(check([(1, None), (2, 9), (3, 5)], direction='descending', nulls='first'))
        self.assertIn('NULL belongs first', check([(1, 9), (2, None)], direction='descending', nulls='first'))
        self.assertIn('descending', check([(1, 5), (2, 9)], direction='descending'))
        self.assertIsNone(check([]))
        report = planning.plan_document(items_document({'selects': [select([column('id'), column('qty')])]}))['report']
        self.assertIsNone(reference.check_native_order(report, [[Decimal(2), Decimal(1)], [Decimal(1), Decimal(2)]], ['number', 'number']))   # no orderBy: nothing to verify

    def test_set_operations_distinct_and_ordering(self):
        rows = [[1, 'a', '1'], [2, 'b', '2'], [3, 'a', '3'], [4, None, '3']]
        part = lambda cond: select([column('name')], where='w', conditions=[{'name': 'w', 'terms': [term({'column': 'items.qty'}, *cond)]}])
        low = part(('lessOrEqual', number('2')))
        high = part(('greaterOrEqual', number('3')))
        for combine, expected in (('unionAll', [['a'], ['a'], ['b'], [None]]), ('union', [['a'], ['b'], [None]]), ('intersect', [['a']]), ('except', [['b']])):
            report = {'selects': [low, high], 'combine': combine, 'orderBy': [{'column': 'name'}]}
            self.assertEqual(run_items(report, rows), expected, combine)
        self.assertEqual(run_items({'selects': [select([column('name')])], 'distinct': True, 'orderBy': [{'column': 'name', 'direction': 'descending', 'nulls': 'first'}]}, rows), [[None], ['b'], ['a']])
        self.assertEqual(run_items({'selects': [select([column('name')])], 'distinct': True, 'orderBy': [{'column': 'name', 'nulls': 'last'}]}, rows), [['a'], ['b'], [None]])

    def test_windows_ties_paging_and_ambiguity(self):
        rows = [[1, 'a', '5'], [2, 'a', '5'], [3, 'b', '1'], [4, 'b', '9']]
        base = lambda function, **more: {'selects': [select([column('id'), column('qty')])], 'windows': [{'name': 'w', 'function': function, 'orderBy': [{'column': 'qty', 'direction': 'descending'}], **more}], 'orderBy': [{'column': 'id'}]}
        self.assertEqual([r[2] for r in run_items(base('rank'), rows)], ['2', '2', '4', '1'])
        self.assertEqual([r[2] for r in run_items(base('denseRank'), rows)], ['2', '2', '3', '1'])
        for function in ('rowNumber', 'runningSum', 'runningCount'):
            extra = {'argument': 'qty'} if function == 'runningSum' else {}
            with self.assertRaises(reference.Ambiguous):
                run_items(base(function, **extra), rows)
        unique = [[1, 'a', '5'], [2, 'a', '6'], [3, 'b', '1'], [4, 'b', '9']]
        sums = {'selects': [select([column('id'), column('name'), column('qty')])], 'windows': [{'name': 'run', 'function': 'runningSum', 'argument': 'qty', 'partitionBy': ['name'], 'orderBy': [{'column': 'qty'}]}], 'orderBy': [{'column': 'id'}]}
        self.assertEqual([r[3] for r in run_items(sums, unique)], ['5', '11', '1', '10'])
        paging = lambda **more: {'selects': [select([column('id'), column('qty')])], 'orderBy': [{'column': 'qty'}, {'column': 'id'}], **more}
        self.assertEqual([r[0] for r in run_items(paging(limit=2, offset=1), rows)], ['1', '2'])
        tied = {'selects': [select([column('id'), column('qty')])], 'orderBy': [{'column': 'qty'}], 'limit': 2}
        with self.assertRaises(reference.Ambiguous):
            run_items(tied, rows)
        tied['limit'] = 3
        self.assertEqual(len(run_items(tied, rows)), 3)

    def test_decimal_and_text_ordering_is_numeric_and_binary(self):
        rows = [[1, 'b', '10'], [2, 'B', '9'], [3, 'a', '100'], [4, 'é', '1']]
        self.assertEqual([r[0] for r in run_items({'selects': [select([column('id'), column('qty')])], 'orderBy': [{'column': 'qty'}]}, rows)], ['4', '2', '1', '3'])
        self.assertEqual([r[1] for r in run_items({'selects': [select([column('id'), column('name')])], 'orderBy': [{'column': 'name'}]}, rows)], ['B', 'a', 'b', 'é'])


class Transactions(Base):
    def simulate(self, name):
        p = planning.plan_document(example(name))
        data = data_for(p)
        results, final = reference.simulate(p, data)
        return p, data, results, final

    def state(self, p, state):
        return {t['name']: reference.table_rows_canonical(t, state[t['name']]) for t in p['tables']}

    def test_transfer_commits_expected_state_and_counts(self):
        p, data, results, final = self.simulate('mutate-transfer')
        self.assertEqual(self.state(p, final)['accounts'], [['1', 'alice', '75'], ['2', 'bob', '75'], ['3', 'carol', '5'], ['4', 'dave', '10'], ['5', 'erin', '1']])
        self.assertEqual([r.get('rows') for r in results], [1, None, 1, 1, 2, 5])
        self.assertEqual((results[4]['inserted'], results[4]['updated']), (1, 1))
        self.assertEqual(self.state(p, data)['accounts'][0], ['1', 'alice', '100'])

    def test_rollback_to_savepoint_discards_later_steps_only(self):
        p, _, _, final = self.simulate('mutate-savepoint')
        self.assertEqual(self.state(p, final)['accounts'], [['1', 'alice', '75'], ['2', 'bob', '50'], ['3', 'carol', '0']])

    def test_violations_are_predicted_with_oracle_error_numbers(self):
        p = planning.plan_document(example('mutate-violation'))
        with self.assertRaises(reference.Predicted) as caught:
            reference.simulate(p, data_for(p))
        self.assertEqual((caught.exception.kind, caught.exception.errors, caught.exception.where['step']), ('constraint', (1,), 1))

    def test_check_not_null_and_expectation_failures(self):
        document = example('mutate-transfer')
        steps = document['transaction']['steps']
        steps[0]['set'][0]['value'] = number('-5')
        p = planning.plan_document(document)
        with self.assertRaises(reference.Predicted) as caught:
            reference.simulate(p, data_for(p))
        self.assertEqual((caught.exception.errors, caught.exception.where['constraint']), ((2290,), 'check'))
        document = example('mutate-transfer')
        document['transaction']['steps'][0]['expectRows'] = 2
        p = planning.plan_document(document)
        with self.assertRaises(reference.Predicted) as caught:
            reference.simulate(p, data_for(p))
        self.assertEqual(caught.exception.kind, 'rowcount')

    def single_update(self, literal, function='subtract', **column_change):
        document = example('mutate-transfer')
        document['transaction']['steps'] = document['transaction']['steps'][:1]
        step = document['transaction']['steps'][0]
        step['computed'][0]['function'] = function
        step['computed'][0]['arguments'][1]['literal']['value'] = literal
        document['tables'][0]['columns'][2].update(column_change)
        return planning.plan_document(document)

    def test_assignments_must_fit_the_target_column_before_anything_commits(self):
        # Oracle would silently round 100 - 0.015 to 99.99 in NUMBER(12,2); the host refuses unless rounding is declared.
        p = self.single_update('0.015')
        with self.assertRaises(reference.Predicted) as caught:
            reference.simulate(p, data_for(p))
        self.assertEqual((caught.exception.kind, caught.exception.where['reason'], caught.exception.errors, caught.exception.where['step']), ('value', 'scale', (), 0))
        rounded = self.single_update('0.015', scalePolicy='round')
        self.assertEqual(self.state(rounded, reference.simulate(rounded, data_for(rounded))[1])['accounts'][0], ['1', 'alice', '99.99'])
        half = self.single_update('0.005', scalePolicy='round')
        self.assertEqual(self.state(half, reference.simulate(half, data_for(half))[1])['accounts'][0], ['1', 'alice', '100'])
        fits = self.single_update('0.01')
        self.assertEqual(self.state(fits, reference.simulate(fits, data_for(fits))[1])['accounts'][0], ['1', 'alice', '99.99'])
        wide = self.single_update('100000000', function='multiply')           # 100 * 1e8 = 1e10 needs 11 integer digits
        with self.assertRaises(reference.Predicted) as caught:
            reference.simulate(wide, data_for(wide))
        self.assertEqual((caught.exception.where['reason'], caught.exception.errors), ('precision', (1438,)))

    def test_assigned_text_that_exceeds_the_column_is_predicted_as_ora_12899(self):
        document = example('mutate-transfer')
        step = document['transaction']['steps'][0]
        step['computed'] = [{'name': 'longer', 'function': 'concat', 'arguments': [{'column': 'accounts.owner'}, {'literal': {'type': 'varchar2', 'value': 'x' * 18}}]}]
        step['set'] = [{'column': 'owner', 'value': {'derived': 'longer'}}]
        document['transaction']['steps'] = [step]
        p = planning.plan_document(document)
        with self.assertRaises(reference.Predicted) as caught:
            reference.simulate(p, data_for(p))
        self.assertEqual((caught.exception.where['reason'], caught.exception.errors), ('length', (12899,)))

    def test_literal_assignments_are_checked_against_the_target_column_at_planning(self):
        document = example('mutate-transfer')
        document['transaction']['steps'][0]['set'] = [{'column': 'balance', 'value': number('0.015')}]
        fault = self.fault(lambda: planning.plan_document(document), 'INVALID_ORACLE_VALUE')
        self.assertEqual((fault.observed['column'], fault.observed['reason']), ('balance', 'scale'))
        document['transaction']['steps'][0]['set'] = [{'column': 'balance', 'value': number('0.01')}]
        planning.plan_document(document)
        document['transaction']['steps'][0]['set'] = [{'column': 'owner', 'value': text('y' * 21)}]
        self.fault(lambda: planning.plan_document(document), 'INVALID_ORACLE_VALUE')

    def test_foreign_key_cascade_set_null_and_no_action(self):
        document = example('load')
        document['operation'] = 'mutate'
        document.pop('setup')
        step = lambda table, key: {'kind': 'delete', 'table': table, 'computed': [], 'conditions': [{'name': 'target', 'terms': [{'left': {'column': f'{table}.id'}, 'operator': 'equals', 'right': number(str(key))}]}], 'where': 'target', 'expectRows': 1}
        document['transaction'] = {'steps': [step('orders', 10), step('customers', 1)]}
        p = planning.plan_document(document)
        results, final = reference.simulate(p, data_for(p))
        state = self.state(p, final)
        self.assertEqual([r[0] for r in state['order_lines']], ['102', '103'])
        self.assertEqual([(r[0], r[1]) for r in state['orders']], [('11', None), ('12', '2'), ('13', None), ('14', '3')])
        self.assertEqual([r[0] for r in state['customers']], ['2', '3', '4'])
        document['tables'][1]['foreignKeys'][0]['onDelete'] = 'noAction'
        document['transaction'] = {'steps': [step('customers', 1)]}
        p = planning.plan_document(document)
        with self.assertRaises(reference.Predicted) as caught:
            reference.simulate(p, data_for(p))
        self.assertEqual(caught.exception.errors, (2291, 2292))

    def test_unique_keys_treat_all_null_rows_as_distinct_but_partial_nulls_as_equal(self):
        columns = [{'name': 'id', 'type': 'number', 'precision': 5, 'scale': 0}, {'name': 'a', 'type': 'number', 'precision': 5, 'scale': 0, 'nullable': True},
                   {'name': 'b', 'type': 'number', 'precision': 5, 'scale': 0, 'nullable': True}]
        document = {'version': model.VERSION, 'operation': 'load', 'connection': CONNECTION, 'tables': [{'name': 't', 'columns': columns, 'primaryKey': ['id'], 'unique': [{'columns': ['a', 'b']}]}]}
        table = planning.plan_document(document)['tables'][0]
        row = lambda i, a, b: reference.typed_row(table, ['id', 'a', 'b'], [i, a, b])
        self.assertIsNone(reference.violations([table], {'t': [row(1, None, None), row(2, None, None), row(3, 1, None), row(4, 2, None)]}))
        found = reference.violations([table], {'t': [row(1, 1, None), row(2, 1, None)]})
        self.assertEqual((found[0], found[3]), ('unique', [1]))
        self.assertIsNone(reference.violations([table], {'t': [row(1, 1, 2), row(2, 1, 3)]}))


class DictionaryContract(Base):
    def test_declared_catalog_and_snapshot_agree_for_every_declared_type(self):
        columns = [{'name': 'id', 'type': 'number', 'precision': 10, 'scale': 0}, {'name': 'free', 'type': 'number', 'nullable': True},
                   {'name': 'label', 'type': 'varchar2', 'length': 30, 'nullable': True}, {'name': 'day', 'type': 'date', 'nullable': True},
                   {'name': 'at', 'type': 'timestamp', 'fraction': 3, 'nullable': True}, {'name': 'tz', 'type': 'timestampTz', 'nullable': True},
                   {'name': 'bytes', 'type': 'raw', 'length': 16, 'nullable': True}, {'name': 'flag', 'type': 'boolean', 'nullable': True}]
        document = {'version': model.VERSION, 'operation': 'load', 'connection': CONNECTION,
                    'tables': [{'name': 'wide', 'columns': columns, 'primaryKey': ['id'], 'unique': [{'columns': ['label']}], 'checks': [{'name': 'ok', 'terms': [term({'column': 'wide.id'}, 'greaterThan', number('0'))]}]},
                               {'name': 'child', 'columns': [{'name': 'id', 'type': 'number', 'precision': 5, 'scale': 0}, {'name': 'wide_id', 'type': 'number', 'precision': 10, 'scale': 0, 'nullable': True}],
                                'primaryKey': ['id'], 'foreignKeys': [{'columns': ['wide_id'], 'table': 'wide', 'references': ['id'], 'onDelete': 'cascade'}]}]}
        p = planning.plan_document(document)
        raw = fake_dictionary(p['tables'])
        snapshot = reference.snapshot(raw, 'TESTER')
        self.assertEqual(reference.drift(p['tables'], snapshot), [])
        self.assertTrue(all(t['managed'] for t in snapshot['tables']))
        self.assertEqual(snapshot['schema'], 'tester')
        wide = next(t for t in snapshot['tables'] if t['name'] == 'wide')
        self.assertEqual(wide['columns'][1], {'name': 'free', 'type': 'number', 'precision': None, 'scale': None, 'length': None, 'fraction': None, 'nullable': True})
        self.assertEqual(wide['columns'][5]['type'], 'timestampTz')

    def test_drift_names_the_table_and_attribute(self):
        p = planning.plan_document(example('load'))
        raw = fake_dictionary(p['tables'])
        raw['columns']['rows'][1][8] = 'Y'
        raw['columns']['rows'][2][3] = '99'
        found = reference.drift(p['tables'], reference.snapshot(raw, 'T'))
        self.assertEqual([(d['table'], d['difference']) for d in found], [('customers', 'columns')])
        raw = fake_dictionary(p['tables'][:1])
        self.assertEqual([(d['table'], d['difference']) for d in reference.drift(p['tables'], reference.snapshot(raw, 'T'))], [('orders', 'missing'), ('order_lines', 'missing')])
        raw = fake_dictionary(p['tables'])
        raw['constraints']['rows'] = [r for r in raw['constraints']['rows'] if r[2] != 'R']
        self.assertEqual({d['difference'] for d in reference.drift(p['tables'], reference.snapshot(raw, 'T'))}, {'foreignKeys'})

    def external(self, names, columns=None):
        document = planning.plan_document(example('load'))
        tables = copy.deepcopy(document['tables'])
        for table in tables:
            table['external'] = True
            table['source'] = None
        if columns is not None:
            tables[0]['columns'] = [c for c in tables[0]['columns'] if c['name'] in columns]
        return [t for t in tables if t['name'] in names], document['tables']

    def test_an_existing_table_with_generated_constraint_names_is_not_drift(self):
        declared, full = self.external(['customers', 'orders'])
        raw = fake_dictionary(full)
        for row in raw['constraints']['rows']:
            row[1] = 'SYS_C00' + str(abs(hash(row[1])) % 100000)      # inline constraints get system-generated names
        self.assertEqual(reference.drift(declared, reference.snapshot(raw, 'T')), [])
        query = sql.catalog_queries([])['constraints']['sql']
        self.assertNotIn('generated', query.lower())
        self.assertIn("NOT LIKE '%IS NOT NULL'", query)

    def test_read_only_external_use_needs_only_the_declared_columns_and_keys(self):
        declared, full = self.external(['customers'], columns=('id', 'region'))
        snapshot = reference.snapshot(fake_dictionary(full), 'T')
        self.assertEqual(reference.drift(declared, snapshot), [])
        wrong = copy.deepcopy(declared)
        wrong[0]['columns'][1]['length'] = 99
        self.assertEqual([(d['table'], d['difference']) for d in reference.drift(wrong, snapshot)], [('customers', 'columns')])
        raw = fake_dictionary(full)
        raw['constraints']['rows'] = [r for r in raw['constraints']['rows'] if not (r[0] == 'CUSTOMERS' and r[2] == 'P')]
        self.assertEqual([d['difference'] for d in reference.drift(declared, reference.snapshot(raw, 'T'))], ['primaryKey'])
        strict = copy.deepcopy(declared)
        strict[0]['external'] = False
        self.assertEqual(reference.drift(strict, snapshot)[0]['difference'], 'columns')    # a created-table declaration must match completely

    def test_byte_semantics_text_columns_are_not_mistaken_for_character_columns(self):
        declared, full = self.external(['customers'])
        raw = fake_dictionary(full)
        for row in raw['columns']['rows']:
            if row[1] == 'NAME':
                row[5] = 'B'
        found = reference.drift(declared, reference.snapshot(raw, 'T'))
        self.assertEqual([d['difference'] for d in found], ['columns'])
        self.assertEqual(found[0]['observed'][0]['type'], 'varchar2Byte')

    def test_snapshot_filters_kinds(self):
        p = planning.plan_document(example('load'))
        raw = fake_dictionary(p['tables'])
        raw['views'] = {'columns': ['view_name'], 'rows': [['V1']]}
        self.assertEqual(reference.snapshot(raw, 'T', ('views',))['tables'], [])
        self.assertEqual([v['name'] for v in reference.snapshot(raw, 'T', ('tables', 'views'))['views']], ['v1'])


def fake_dictionary(tables, managed=True):
    """Dictionary rows an Oracle schema would return for these declared tables (the shape the worker publishes)."""
    names = lambda *c: {'columns': list(c), 'rows': []}
    raw = {'tables': names('table_name', 'comments'), 'columns': names('table_name', 'column_name', 'data_type', 'data_length', 'char_length', 'char_used', 'data_precision', 'data_scale', 'nullable', 'column_id'),
           'constraints': names('table_name', 'constraint_name', 'constraint_type', 'delete_rule', 'column_name', 'position', 'parent_table', 'parent_column'),
           'indexes': names('table_name', 'index_name', 'uniqueness', 'column_name', 'column_position'), 'views': names('view_name'),
           'sequences': names('sequence_name', 'min_value', 'max_value', 'increment_by', 'cycle_flag', 'order_flag', 'cache_size')}
    for t in tables:
        upper = t['name'].upper()
        raw['tables']['rows'].append([upper, sql.run_marker('0' * 16) if managed else None])
        for i, c in enumerate(t['columns'], 1):
            kind = {'number': 'NUMBER', 'varchar2': 'VARCHAR2', 'date': 'DATE', 'raw': 'RAW', 'boolean': 'BOOLEAN',
                    'timestamp': f'TIMESTAMP({c["fraction"]})', 'timestampTz': f'TIMESTAMP({c["fraction"]}) WITH TIME ZONE'}[c['type']]
            raw['columns']['rows'].append([upper, c['name'].upper(), kind, str(c['length'] or 22), str(c['length']) if c['type'] == 'varchar2' else '0', 'C' if c['type'] == 'varchar2' else None,
                                           None if c['precision'] is None else str(c['precision']), None if c['scale'] is None else str(c['scale']),
                                           'Y' if c['nullable'] and c['name'] not in t['primaryKey'] else 'N', str(i)])
        names_ = sql.constraint_names(t)
        for position, col in enumerate(t['primaryKey'], 1):
            raw['constraints']['rows'].append([upper, names_['primary'].upper(), 'P', None, col.upper(), str(position), None, None])
        raw['indexes']['rows'] += [[upper, names_['primary'].upper(), 'UNIQUE', col.upper(), str(i)] for i, col in enumerate(t['primaryKey'], 1)]
        for n, cols in zip(names_['unique'], t['unique']):
            raw['constraints']['rows'] += [[upper, n.upper(), 'U', None, col.upper(), str(i), None, None] for i, col in enumerate(cols, 1)]
        for n, fk in zip(names_['foreign'], t['foreignKeys']):
            rule = {'noAction': 'NO ACTION', 'cascade': 'CASCADE', 'setNull': 'SET NULL'}[fk['onDelete']]
            raw['constraints']['rows'] += [[upper, n.upper(), 'R', rule, c.upper(), str(i), fk['table'].upper(), r.upper()] for i, (c, r) in enumerate(zip(fk['columns'], fk['references']), 1)]
        for n in names_['check']:
            raw['constraints']['rows'].append([upper, n.upper(), 'C', None, t['columns'][0]['name'].upper(), '1', None, None])
    return raw


def renamed(tables, names):
    """Plan tables with their physical names (what the database holds when scratch names are run-unique)."""
    result = copy.deepcopy(tables)
    for table in result:
        table['name'] = names.get(table['name'], table['name'])
        for key in table['foreignKeys']:
            key['table'] = names.get(key['table'], key['table'])
    return result


def existing_state(p, ledger_rows=()):
    """Base rows for the existing tables of the existing-table example: accounts from the fixture, the ledger as given."""
    state = {}
    for table in p['tables']:
        if table['name'] == 'accounts':
            source = {'path': str(FIXTURES / 'accounts.json'), 'format': 'json'}
            state['accounts'] = reference.parse_source({**table, 'source': source}, (FIXTURES / 'accounts.json').read_bytes(), '$')
        else:
            state[table['name']] = [reference.typed_row(table, ['idempotency_key', 'plan_digest'], list(r)) for r in ledger_rows]
    return state


class ExistingTables(Base):
    def document(self, **edit):
        document = example('mutate-existing')
        for key, value in edit.items():
            document['transaction'][key] = value
        return document

    def test_the_plan_wraps_the_changes_in_ledger_checks_and_a_ledger_record(self):
        p = planning.plan_document(example('mutate-existing'))
        steps = p['transaction']['steps']
        self.assertEqual([s['kind'] for s in steps], ['check', 'check', 'update', 'insert'])
        self.assertEqual([s.get('role') for s in steps], ['ledger:conflict', 'ledger:applied', None, 'ledger:record'])
        ledger = p['transaction']['idempotency']
        self.assertRegex(ledger['digest'], r'^[0-9a-f]{64}$')
        self.assertEqual((ledger['table'], ledger['key'], ledger['keyColumn'], ledger['digestColumn']), ('change_ledger', 'transfer-2026-11-alice-debit', 'idempotency_key', 'plan_digest'))
        self.assertEqual(steps[3]['rows'], [[ledger['key'], ledger['digest']]])
        self.assertEqual(planning.plan_document(example('mutate-existing')), p)
        changed = example('mutate-existing')
        changed['transaction']['steps'][0]['expectRows'] = 2
        self.assertNotEqual(planning.plan_document(changed)['transaction']['idempotency']['digest'], ledger['digest'])
        self.assertTrue(all(t['external'] for t in p['tables']))
        self.assertEqual(p['order'], ['accounts', 'change_ledger'])

    def test_a_transaction_on_existing_tables_must_be_serializable_database_enforced_and_idempotent(self):
        self.fault(lambda: planning.plan_document(self.document(isolation='readCommitted')), 'INVALID_ORACLE_TRANSACTION')
        self.fault(lambda: planning.plan_document(self.document(enforcement='predict')), 'INVALID_ORACLE_TRANSACTION')
        document = example('mutate-existing')
        del document['transaction']['idempotency']
        self.assertEqual(self.fault(lambda: planning.plan_document(document), 'MISSING_ARGUMENT').location, '$.transaction.idempotency')
        created = example('mutate-transfer')
        created['transaction']['idempotency'] = {'table': 'accounts', 'key': 'k'}
        self.fault(lambda: planning.plan_document(created), 'INVALID_ORACLE_TRANSACTION')

    def test_the_ledger_must_be_an_existing_table_with_a_primary_key_key_column_and_room_for_the_digest(self):
        def edit(change, code='INVALID_ORACLE_TRANSACTION'):
            document = example('mutate-existing')
            change(document)
            return self.fault(lambda: planning.plan_document(document), code)
        edit(lambda d: d['transaction']['idempotency'].update(table='accounts', keyColumn='id'))                         # not a varchar2 key
        edit(lambda d: d['transaction']['idempotency'].update(table='nowhere'))
        edit(lambda d: d['tables'][1]['columns'][1].update(length=40))                                                   # no room for a 64-character digest
        edit(lambda d: d['tables'][1]['columns'][0].update(length=10))                                                   # key longer than the column
        edit(lambda d: d['tables'][1]['columns'][1].update(nullable=True))
        edit(lambda d: d['tables'][1].update(primaryKey=['plan_digest']))
        edit(lambda d: d['tables'][1]['columns'].append({'name': 'applied_by', 'type': 'varchar2', 'length': 20}))        # an extra NOT NULL column has no value
        edit(lambda d: d['transaction']['idempotency'].update(digestColumn='missing_column'))
        edit(lambda d: d['tables'][1].update(external=False))
        document = example('mutate-existing')
        document['tables'][1]['columns'].append({'name': 'applied_by', 'type': 'varchar2', 'length': 20, 'nullable': True})
        planning.plan_document(document)                                                                                   # an extra nullable column is fine

    def test_the_reference_applies_the_change_once_and_records_the_key(self):
        p = planning.plan_document(example('mutate-existing'))
        results, final = reference.simulate(p, existing_state(p))
        self.assertEqual([r.get('rows') for r in results], [0, 0, 1, 1])
        accounts = reference.table_rows_canonical(p['tables'][0], final['accounts'])
        self.assertEqual(accounts[0], ['1', 'alice', '75'])
        ledger = p['transaction']['idempotency']
        self.assertEqual(reference.table_rows_canonical(p['tables'][1], final['change_ledger']), [[ledger['key'], ledger['digest']]])

    def test_a_recorded_key_is_refused_as_already_applied_or_as_a_conflict(self):
        p = planning.plan_document(example('mutate-existing'))
        key, digest = p['transaction']['idempotency']['key'], p['transaction']['idempotency']['digest']
        with self.assertRaises(reference.Predicted) as caught:
            reference.simulate(p, existing_state(p, [(key, digest)]))
        self.assertEqual((caught.exception.kind, caught.exception.where['step'], p['transaction']['steps'][1]['role']), ('rowcount', 1, 'ledger:applied'))
        with self.assertRaises(reference.Predicted) as caught:
            reference.simulate(p, existing_state(p, [(key, 'f' * 64)]))
        self.assertEqual((caught.exception.where['step'], p['transaction']['steps'][0]['role']), (0, 'ledger:conflict'))
        results, _ = reference.simulate(p, existing_state(p, [('another-change', digest)]))
        self.assertEqual(results[2]['rows'], 1)                                                                            # a different key does not interfere

    def test_mutation_requires_complete_schema_while_reports_can_project_a_subset(self):
        from schemaxis.adaptors.oracle import adaptor
        p=planning.plan_document(example('mutate-existing'))
        actual=copy.deepcopy(p['tables'])
        extra=model.plan_column({'name':'extra','type':'varchar2','length':10,'nullable':True,'emptyText':'reject','scalePolicy':'reject'}, '$')
        actual[0]['columns'].append(extra)
        snapshot=reference.snapshot(fake_dictionary(actual), 'TEST')
        self.fault(lambda: adaptor.existing_objects(p,snapshot), 'ORACLE_DRIFT')
        self.assertEqual(reference.drift(p['tables'],snapshot), [])

    def test_the_program_reads_the_base_state_in_the_snapshot_and_never_creates_or_drops_anything(self):
        from schemaxis.adaptors.oracle import adaptor
        p = planning.plan_document(example('mutate-existing'))
        steps = adaptor.apply_program(p, {}, '0123456789abcdef')['steps']
        ids = [s['id'] for s in steps]
        self.assertEqual(ids[:7], ['effect-boundary', 'commit:seed', 'before', 'isolation', 'base:accounts', 'base:change_ledger', 'prospective'])
        self.assertEqual(steps[3]['action'], 'serializable')
        self.assertFalse([s for s in steps if s['kind'] == 'ddl'])
        self.assertTrue(all('"ACCOUNTS"' in s['sql'] or '"CHANGE_LEDGER"' in s['sql'] for s in steps if s['kind'] in ('query', 'insert', 'dml') and 'sql' in s and not s['id'].startswith('view')))
        self.assertEqual(adaptor.readback_program(p, [], run_id='0123456789abcdef')['cleanup'], [])
        conflict = next(s for s in steps if s['id'] == 'step:0')
        self.assertEqual((conflict['kind'], conflict['expectCount']), ('query', 0))
        self.assertEqual([b['v'] for b in conflict['binds']], ['transfer-2026-11-alice-debit', p['transaction']['idempotency']['digest']])
        self.assertEqual(adaptor.physical_names(p, '0123456789abcdef'), {})


class PhysicalNames(Base):
    RUN = '0123456789abcdef'

    def test_scratch_tables_get_run_unique_names_and_everything_else_keeps_its_name(self):
        from schemaxis.adaptors.oracle import adaptor
        scratch = planning.plan_document(example('report-lines'))
        names = adaptor.physical_names(scratch, self.RUN)
        self.assertEqual(names, {'customers': 'customers_01234', 'orders': 'orders_01234', 'order_lines': 'order_lines_01234'})
        self.assertNotEqual(names, adaptor.physical_names(scratch, 'fedcba9876543210'))
        self.assertEqual(adaptor.physical_names(planning.plan_document(example('load')), self.RUN), {})            # retained: declared names
        self.assertEqual(adaptor.physical_names(planning.plan_document(example('inspect')), self.RUN), {})
        self.assertEqual(adaptor.physical_names(scratch, None), {})
        document = example('report-revenue')
        document['tables'][0]['name'] = 'c' * 24
        document['tables'][0]['checks'] = []
        document['report']['selects'][0]['from']['table'] = 'c' * 24
        document['tables'][1]['foreignKeys'][0]['table'] = 'c' * 24
        longest = adaptor.physical_names(planning.plan_document(document), self.RUN)['c' * 24]
        self.assertEqual(len(longest), 30)                                                            # the longest legal name still fits
        external = example('report-revenue')
        for table in external['tables']:
            table['external'] = True
            table.pop('source')
        self.assertEqual(adaptor.physical_names(planning.plan_document(external), self.RUN), {})

    def test_physical_plans_rename_table_references_only_and_never_mutate_the_plan(self):
        from schemaxis.adaptors.oracle import adaptor
        p = planning.plan_document(example('report-lines'))
        before = json.dumps(p, sort_keys=True)
        names = adaptor.physical_names(p, self.RUN)
        q = adaptor.physicalise(p, names)
        self.assertEqual(json.dumps(p, sort_keys=True), before)
        self.assertEqual([t['name'] for t in q['tables']], ['customers_01234', 'orders_01234', 'order_lines_01234'])
        self.assertEqual(q['tables'][2]['foreignKeys'][0]['table'], 'orders_01234')
        self.assertEqual(q['order'], ['customers_01234', 'orders_01234', 'order_lines_01234'])
        statement = sql.create_table_sql(q['tables'][2])
        self.assertIn('CREATE TABLE "ORDER_LINES_01234"', statement)
        self.assertIn('REFERENCES "ORDERS_01234" ("ID")', statement)
        report, _, _ = sql.report_sql(q['report'])
        self.assertIn('FROM "ORDERS_01234" "O" INNER JOIN "ORDER_LINES_01234" "L" ON "O"."ID" = "L"."ORDER_ID"', report)
        self.assertNotIn('"ORDERS"', report)
        self.assertIs(adaptor.physicalise(p, {}), p)

    def test_programs_use_only_physical_names_but_are_keyed_by_the_declared_names(self):
        from schemaxis.adaptors.oracle import adaptor
        p = planning.plan_document(example('mutate-transfer'))
        def statements(program):
            found = []
            for step in program['steps']:
                found += [step['sql']] if 'sql' in step else [spec['sql'] for spec in step.get('queries', {}).values()]
            return found
        steps = adaptor.apply_program(p, data_for(p), self.RUN)
        texts = statements(steps)
        self.assertTrue(any('"ACCOUNTS_01234"' in t for t in texts))
        self.assertFalse([t for t in texts if '"ACCOUNTS"' in t])
        self.assertEqual(sorted(next(s for s in steps['steps'] if s['id'] == 'before')['queries']), ['accounts'])           # keys stay logical
        self.assertEqual(adaptor.readback_program(p, ['accounts'], run_id=self.RUN)['cleanup'], [{'table': 'ACCOUNTS_01234', 'sql': 'DROP TABLE "ACCOUNTS_01234" PURGE'}])
        retained = planning.plan_document({**example('mutate-transfer'), 'setup': {'retain': True}})
        retained_texts = statements(adaptor.apply_program(retained, data_for(retained), self.RUN))
        self.assertTrue(any('"ACCOUNTS"' in t for t in retained_texts))
        self.assertFalse([t for t in retained_texts if 'ACCOUNTS_01234' in t])

    def test_the_snapshot_maps_back_to_the_declared_names_so_drift_and_keys_still_agree(self):
        from schemaxis.adaptors.oracle import adaptor
        p = planning.plan_document(example('report-lines'))
        names = adaptor.physical_names(p, self.RUN)
        snapshot = reference.snapshot(fake_dictionary(renamed(p['tables'], names)), 'T')
        self.assertEqual({t['name'] for t in snapshot['tables']}, set(names.values()))
        relabelled = reference.relabel(snapshot, {v: k for k, v in names.items()})
        self.assertEqual(reference.drift(p['tables'], relabelled), [])
        self.assertEqual([t['name'] for t in relabelled['tables']], sorted(names))
        self.assertTrue(reference.drift(p['tables'], snapshot))                       # without relabelling, the declared names are missing
        self.assertIs(reference.relabel(snapshot, {}), snapshot)

    def test_an_existing_table_with_a_scratch_tables_logical_name_is_untouched_by_the_scratch_run(self):
        from schemaxis.adaptors.oracle import adaptor
        p = planning.plan_document(example('report-revenue'))
        names = adaptor.physical_names(p, self.RUN)
        snapshot = reference.snapshot(fake_dictionary(planning.plan_document(example('load'))['tables'][:1]), 'T')       # an unrelated CUSTOMERS
        adaptor.existing_objects(p, snapshot, names)                                                                       # no collision: the scratch name differs
        retained = planning.plan_document({**example('report-revenue'), 'setup': {'retain': True}})
        fault = self.fault(lambda: adaptor.existing_objects(retained, snapshot, adaptor.physical_names(retained, self.RUN)), 'ORACLE_OBJECT_EXISTS')
        self.assertEqual(fault.observed['table'], 'customers')


class DocumentsAndJson(Base):
    def document(self):
        return example('report-documents')

    def test_document_families_plan_load_report_and_exact_scalar_reference(self):
        p = planning.plan_document(self.document())
        data = data_for(p)
        rows, kinds = reference.run_report(p['report'], data)
        self.assertEqual(kinds, ['number', 'clob', 'blob', 'json', 'number', 'varchar2', 'boolean'])
        self.assertEqual(rows[0][2], bytes.fromhex('0001ff80'))
        self.assertEqual(rows[0][4:], [Decimal('12.5'), 'café', True])
        self.assertEqual(rows[1][4:], [Decimal('2'), None, False])
        self.assertEqual(rows[2][4:], [None, None, None])
        self.assertIn('JSON_VALUE', sql.report_sql(p['report'])[0])
        planning.plan_document(example('load-documents'))

    def test_json_canonicalisation_is_exact_and_key_order_independent(self):
        self.assertEqual(model.canonical_json('{"z":1.2300,"a":[true,null,"😀"]}'), '{"a":[true,null,"😀"],"z":1.23}')
        for raw in ('{"a":1,"a":2}', 'NaN', 'Infinity', '[1,]', '[' * 40 + '0' + ']' * 40, '{"n":1e9999}', '{"x":"\\ud800"}', '\ud800'):
            with self.subTest(raw=raw[:30]):
                with self.assertRaises(model.ValueFault):
                    model.canonical_json(raw)

    def test_lob_values_have_explicit_null_empty_and_size_policies(self):
        for kind, raw, result in [('clob', '😀text', '😀text'), ('blob', '00ABff', b'\x00\xab\xff')]:
            self.assertEqual(model.parse_value({'type': kind}, raw), result)
            self.assertIsNone(model.parse_value({'type': kind}, None))
            with self.assertRaises(model.ValueFault):
                model.parse_value({'type': kind}, '')
            with self.assertRaises(model.ValueFault):
                model.parse_value({'type': kind}, 'a' * (model.LARGE_LIMIT * 2 + 2))

    def test_lob_json_keys_comparison_grouping_and_set_operations_are_refused(self):
        d = self.document()
        d['tables'][0]['primaryKey'] = ['metadata']
        self.fault(lambda: planning.plan_document(d), 'INVALID_ORACLE_TABLE')
        for field, value in [('distinct', True), ('orderBy', [{'column': 'note'}])]:
            d = self.document(); d['report'][field] = value
            self.fault(lambda: planning.plan_document(d), 'INVALID_ORACLE_QUERY')
        d = self.document(); d['report']['selects'] *= 2
        self.fault(lambda: planning.plan_document(d), 'INVALID_ORACLE_QUERY')
        d = self.document(); d['report']['selects'][0]['conditions'] = [{'name': 'bad', 'terms': [{'left': {'column':'d.metadata'}, 'operator':'equals', 'right': {'literal': {'type':'json','value':'{}'}}}]}]
        self.fault(lambda: planning.plan_document(d), 'INVALID_ORACLE_QUERY')

    def test_json_lax_shapes_and_boolean_text_match_observed_oracle_semantics(self):
        samples = [('{"a":[{"x":2}]}', '$.a.x', 'jsonNumber', Decimal(2)),
                   ('{"a":[]}', '$.a.x', 'jsonNumber', None), ('1', '$[0]', 'jsonNumber', Decimal(1)),
                   ('{"a":1}', '$[0].a', 'jsonNumber', Decimal(1)),
                   ('[[{"a":2}]]', '$.a', 'jsonNumber', None),
                   ('{"a":"FALSE"}', '$.a', 'jsonBoolean', False)]
        for raw, path, function, expected in samples:
            d=self.document(); derived=d['report']['selects'][0]['computed'][0]
            derived.update(path=path,function=function)
            p=planning.plan_document(d); data=data_for(p)
            data['documents'][0]['metadata']=model.canonical_json(raw)
            evaluator=reference.Evaluator(p['report']['selects'][0]['computed'])
            self.assertEqual(evaluator.derive(p['report']['selects'][0]['computed'][0], {'rows':{'d':data['documents'][0]}}), expected)
        data['documents'][0]['metadata']='{"a":[{"x":1},{"x":2}]}'
        derived=p['report']['selects'][0]['computed'][0] | {'function':'jsonNumber','path':'$.a.x'}
        with self.assertRaises(reference.Unverifiable):
            evaluator.derive(derived, {'rows':{'d':data['documents'][0]}})

    def test_only_closed_json_paths_are_allowed_and_missing_is_null(self):
        for path in ('$.x[*]', '$..x', '$.x?(@.a)', "$.x' RETURNING NUMBER)", '$[000]', '$.a;DROP'):
            d=self.document(); d['report']['selects'][0]['computed'][0]['path']=path
            self.fault(lambda: planning.plan_document(d), 'INVALID_ORACLE_QUERY')
        d=self.document(); d['report']['selects'][0]['computed'][0]['path']='$.absent[0]'
        p=planning.plan_document(d)
        self.assertTrue(all(r[4] is None for r in reference.run_report(p['report'],data_for(p))[0]))


class DiscoveryAndStudio(Base):
    def test_registered_route_plans_and_declares_every_operation(self):
        from schemaxis.adaptors import registry
        document = example('report-revenue')
        self.assertEqual(registry.plan(document)['operation'], 'report')
        self.assertEqual(set(registry.declarations('oracle')), set(model.OPERATIONS))
        self.assertEqual(registry.resolve(document)[0], 'oracle')

    def test_studio_starters_plan_and_report_nested_placeholders(self):
        from schemaxis.studio_library import instantiate_item, load_library, plan_item
        from schemaxis.unfilled import find_unfilled
        library = load_library('oracle')
        self.assertEqual({t['id'] for t in library['templates']}, {'revenue-report', 'balance-transaction', 'typed-load', 'schema-snapshot'})
        for item in library['templates']:
            plan_item(instantiate_item(library, item, provider='oracle'))
            draft = instantiate_item(library, item, provider='oracle', filled=False)
            expected = find_unfilled(draft)
            if expected:
                fault = self.fault(lambda: plan_item(draft), 'UNFILLED_VALUES')
                self.assertEqual(fault.observed['pointers'], [v['pointer'] for v in expected])

    def test_guidance_and_actual_capability_matching(self):
        from schemaxis.capabilities import CapabilityCatalogue
        from schemaxis.search_acceptance import check_cases
        from schemaxis.studio_guidance import audit
        self.assertTrue(check_cases(CapabilityCatalogue(providers=['oracle']), 'oracle')['complete'])
        self.assertTrue(audit('oracle')['complete'])

    def test_every_example_in_readiness_exists_and_valid_ones_plan(self):
        bundle = json.loads((ROOT / 'src/schemaxis/adaptors/oracle/readiness.json').read_text())
        for entry in bundle['routes']['schemaxis.oracle/1']['examples']:
            document = json.loads((ROOT / entry['reference']).read_text())
            if entry.get('expect') == 'invalid':
                self.fault(lambda: planning.plan_document(document), entry['fault'])
            else:
                planning.plan_document(document)
        for case in bundle['routes']['schemaxis.oracle/1']['development']['cases']:
            for path in case['resources'].values():
                self.assertTrue((ROOT / path).is_file(), path)

    def test_calc_handoff_example_declares_reuse_and_value_dependency(self):
        workflow = json.loads((ROOT / 'examples/schemaxis/oracle-calc-typed-workflow.json').read_text())
        report = workflow['operations'][1]['document']
        self.assertEqual(report['report']['limit']['artifact'], 0)
        self.assertEqual(report['tables'][0]['columns']['operation'], 'load')
        self.assertEqual(workflow['operations'][2]['document']['nodes'][0]['options']['file']['index'], 1)


if __name__ == '__main__':
    unittest.main()
