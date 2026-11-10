"""Curated discovery for typed Oracle Database workflows without importing the driver."""
import json
from importlib.resources import files


def catalogue():
    return {
        'application': {
            'label': 'Oracle Database',
            'purpose': 'Inspect, load, report on and change Oracle tables through typed relations, predicates, measures and transactions, '
                       'with exact NUMBER/Unicode/NULL semantics and every native result checked against an independent reference.',
            'keywords': ['Oracle Database', 'Oracle', 'relational', 'typed tables', 'SQL', 'NUMBER', 'transaction', 'schema', 'CLOB', 'BLOB', 'native JSON']},
        'searchCases': json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'requirements': ['A dedicated Python interpreter with python-oracledb (Thin mode) given to --oracle; the host never imports the driver.',
                         'Credentials are named host environment variables (SCHEMAXIS_ORACLE_<PROFILE>_USER, _PASSWORD, _DSN), never document values.',
                         'AL32UTF8 database; BOOLEAN needs Oracle Database 23 or later. No authored SQL, PL/SQL, packages or native reflection.'],
        'references': ['docs/oracle.md', 'docs/design/oracle-coverage.md', 'src/schemaxis/adaptors/oracle/readiness.json'],
        'operations': {
            'inspect': {
                'purpose': 'Take a reproducible snapshot of the connected schema (tables, columns, keys, indexes, views, sequences) and check it against declared tables for drift.',
                'keywords': ['schema inspection', 'data dictionary', 'metadata snapshot', 'drift', 'tables', 'columns', 'constraints', 'indexes', 'views', 'sequences', 'USER_TABLES'],
                'semantics': ['Two fresh connections must see the same snapshot; declared tables are compared column by column, key by key.',
                              'Check constraints are compared by count; their expressions are exercised by mutation tests, not parsed back.'],
                'examples': [{'reference': 'examples/schemaxis/oracle-inspect.json', 'purpose': 'Snapshot the tables and indexes named sales tables, when they exist in the connected schema.'}]},
            'load': {
                'purpose': 'Create declared tables with keys and constraints, import captured typed JSON or CSV rows, commit, and prove the rows and definitions from a fresh connection.',
                'keywords': ['import', 'load', 'bulk insert', 'CSV', 'JSON', 'create table', 'primary key', 'foreign key', 'unique', 'check constraint', 'row count', 'executemany', 'document storage', 'CLOB', 'BLOB', 'native JSON'],
                'semantics': ['CREATE TABLE and COMMENT commit implicitly in Oracle; the rows are committed once after loading.',
                              'Empty text is NULL in Oracle and is refused unless emptyText says null; NUMBER values are exact decimal text.'],
                'examples': [{'reference': 'examples/schemaxis/oracle-load.json', 'purpose': 'Load customers, orders and CSV order lines with a timestamp-with-time-zone column.'}]},
            'report': {
                'purpose': 'Join tables, filter with null-aware conditions, derive values, group and aggregate, rank with windows, combine selects and publish an exact ordered result.',
                'keywords': ['report', 'join', 'left join', 'outer join', 'group by', 'having', 'aggregate', 'count', 'sum', 'average', 'window', 'rank', 'union', 'intersect', 'distinct', 'order by', 'pagination', 'extract', 'SELECT', 'JSON scalar', 'JSON_VALUE', 'jsonNumber', 'jsonText', 'jsonBoolean'],
                'semantics': ['Conditions use SQL three-valued logic: comparisons with NULL are unknown and rows are kept only when TRUE.',
                              'Ties under limit/offset or row_number windows are refused rather than published in an arbitrary order.',
                              'Computed NUMBER results (division, average, sums) carry up to 40 digits natively and are compared at 36 significant digits; stored values are exact.'],
                'examples': [{'reference': 'examples/schemaxis/oracle-report-revenue.json', 'purpose': 'Order counts and revenue by customer region with a left join.'},
                             {'reference': 'examples/schemaxis/oracle-report-variant.json', 'purpose': 'The same grouping over a full outer join, exposing orders without customers.'},
                             {'reference': 'examples/schemaxis/oracle-report-lines.json', 'purpose': 'Three tables, a derived line total, HAVING and a rank window.'}]},
            'mutate': {
                'purpose': 'Run an atomic group of insert, update, delete and merge steps with savepoints and row-count expectations, then commit or roll back and verify both states from other sessions.',
                'keywords': ['transaction', 'commit', 'rollback', 'savepoint', 'insert', 'update', 'delete', 'merge', 'upsert', 'constraint violation', 'isolation', 'atomic', 'reconcile'],
                'semantics': ['Uncommitted work is checked to be invisible to a separate observer connection before it is finished.',
                              'The snapshot reference validates prospective assignments before DML and native rows before commit. A failed or timed-out step rolls uncommitted work back; an unreadable COMMIT is reported as outcome unknown and never replayed.'],
                'examples': [{'reference': 'examples/schemaxis/oracle-mutate-transfer.json', 'purpose': 'A balance transfer with a savepoint, insert, merge and a verifying check.'},
                             {'reference': 'examples/schemaxis/oracle-mutate-savepoint.json', 'purpose': 'Roll back to a savepoint inside a serializable transaction.'},
                             {'reference': 'examples/schemaxis/oracle-mutate-rollback.json', 'purpose': 'Finish by rolling back and confirm that nothing was committed.'}]}}
    }
