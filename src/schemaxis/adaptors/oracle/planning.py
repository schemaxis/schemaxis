"""Relational, mutation and inspection planning over the typed Oracle records."""
import hashlib
import json

from schemaxis.core.declarations import validate_arguments
from . import model
from .model import (ORDERED, PLAN_VERSION, VERSION, OPERATION_OPTIONS, OPERATIONS, OPTIONS, Scope, ValueFault, canonical, identifier,
                    parse_value, plan_connection, plan_tables, problem)

LOSSES = [
    'Types: NUMBER (exact decimal, up to 38 digits), VARCHAR2(n CHAR), DATE, TIMESTAMP(0-6), TIMESTAMP WITH TIME ZONE(0-6), RAW and BOOLEAN. Bounded CLOB/BLOB and native JSON with exact scalar extraction. No FLOAT/BINARY_DOUBLE, intervals, XML, object, spatial or vector values yet.',
    'NUMBER values are exact decimal strings or integers; fractional digits beyond a column scale are refused unless scalePolicy is round. Oracle NUMBER does not remember trailing zeros, so published numbers are canonical decimal text.',
    'Oracle stores empty text and empty RAW as NULL: empty values are refused unless emptyText is null. Text compares by binary (code point) order.',
    'DATE is a whole-second wall-clock value; TIMESTAMP is wall-clock to microseconds; TIMESTAMP WITH TIME ZONE keeps a fixed numeric offset (no region names, no daylight-saving rules) and compares by instant.',
    'Stored NUMBER values have at most 38 significant digits and are compared exactly. Computed results (division, average, sum, derived arithmetic) carry up to 40 digits natively and are compared at 36 significant digits; assigning a computed value to a column rounds it to 38 digits and then to the column scale, which the host refuses unless scalePolicy is round.',
    'DATE and TIMESTAMP values are read with a signed year mask and a BC (negative-year) value is refused; the adaptor holds years 1 to 9999.',
    'Result and table data are bounded (5000 rows per table, 10000 result rows, 4 MiB per source) and are not streamed.',
]
ORDER_DIRECTIONS = {'ascending': 'ASC', 'descending': 'DESC'}


def uses_measure(select_conditions, name, measures_seen):
    cond = select_conditions[name]
    for term in cond['terms']:
        if 'condition' in term:
            if uses_measure(select_conditions, term['condition'], measures_seen):
                return True
            continue
        for key in ('left', 'right', 'upper'):
            if key in term and 'measure' in term[key]:
                return True
        if any('measure' in v for v in term.get('values', [])):
            return True
    return False


def operand_key(operand):
    return json.dumps({k: v for k, v in operand.items() if k != 'kind'}, sort_keys=True)


def plan_select(select, at, tables):
    aliases, scope = {}, None

    def attach(reference, where):
        table = reference['table']
        if table not in tables:
            problem('INVALID_ORACLE_QUERY', 'the relation names a table that is not declared in tables', where + '.table', 'declare the table (use external for existing ones)', table=table, declared=sorted(tables))
        alias = identifier(reference.get('alias', table), where + '.alias')
        if alias in aliases:
            problem('INVALID_ORACLE_QUERY', 'aliases must be unique within a select (self-joins need distinct aliases)', where + '.alias', alias=alias)
        aliases[alias] = tables[table]
        return {'table': table, 'alias': alias}
    base = attach(select['from'], at + '.from')
    scope = Scope(aliases, list(aliases))
    joins = []
    for i, join in enumerate(select['joins']):
        where = f'{at}.joins[{i}]'
        earlier = list(aliases)
        planned = attach(join, where)
        scope.aliases = list(aliases)
        keys = []
        for j, key in enumerate(join['on']):
            left, right = key['left'], key['right']
            lcol = scope.column(left, f'{where}.on[{j}].left')
            rcol = scope.column(right, f'{where}.on[{j}].right')
            if left.split('.')[0] not in earlier or right.split('.')[0] != planned['alias']:
                problem('INVALID_ORACLE_QUERY', 'each join key pairs an earlier alias (left) with the joined alias (right)', f'{where}.on[{j}]', left=left, right=right)
            if lcol['type'] != rcol['type'] or lcol['type'] not in model.KEY_TYPES:
                problem('INVALID_ORACLE_QUERY', 'join keys must have the same orderable or raw type', f'{where}.on[{j}]', left=lcol['type'], right=rcol['type'])
            keys.append({'left': left, 'right': right, 'kind': lcol['type']})
        joins.append({'type': join['type'], **planned, 'on': keys})
    computed = [scope.derive(d, f'{at}.computed[{i}]') for i, d in enumerate(select['computed'])]
    measures = []
    for i, m in enumerate(select['measures']):
        where = f'{at}.measures[{i}]'
        name = identifier(m['name'], where + '.name')
        if name in scope.measures:
            problem('INVALID_ORACLE_QUERY', 'measure names must be unique', where + '.name', name=name)
        function = m['function']
        if function == 'countAll':
            if 'argument' in m:
                problem('INVALID_ORACLE_QUERY', 'countAll counts rows and takes no argument', where + '.argument')
            argument, kind = None, 'number'
        else:
            if 'argument' not in m:
                problem('INVALID_ORACLE_QUERY', f'{function} needs an argument', where + '.argument')
            argument = scope.operand(m['argument'], where + '.argument', ('column', 'derived'))
            if argument['kind'] in model.LARGE_TYPES:
                problem('INVALID_ORACLE_QUERY', 'aggregate extracted JSON scalars or ordinary columns, not LOB/JSON values', where)
            kind = 'number' if function in ('count', 'countDistinct') else argument['kind']
            if function in ('sum', 'average') and argument['kind'] != 'number':
                problem('INVALID_ORACLE_QUERY', f'{function} needs a number', where + '.argument', kind=argument['kind'])
            if function in ('minimum', 'maximum') and (argument['kind'] not in ORDERED or argument['kind'] == 'timestampTz'):
                problem('INVALID_ORACLE_QUERY', f'{function} cannot summarise {argument["kind"]} values deterministically', where + '.argument',
                        'time zone offsets of equal instants make the representative value unspecified')
        scope.measures[name] = kind
        measures.append({'name': name, 'function': function, 'argument': argument, 'kind': kind})
    grouped = bool(select['groupBy'] or measures)
    group_by = []
    for i, key in enumerate(select['groupBy']):
        planned = scope.operand(key, f'{at}.groupBy[{i}]', ('column', 'derived'))
        if planned['kind'] in model.NO_EQUALITY_GROUPING:
            problem('INVALID_ORACLE_QUERY', 'grouping by a time-zone timestamp leaves the representative offset unspecified', f'{at}.groupBy[{i}]', 'group by a derived date part, or a timestamp column')
        group_by.append(planned)
    conditions = {}
    planned_conditions = []
    scope.conditions = {}
    for i, cond in enumerate(select['conditions']):
        planned = scope.condition(cond, f'{at}.conditions[{i}]', allow_measure=grouped)
        conditions[planned['name']] = planned
        planned_conditions.append(planned)
    for label, forbid in (('where', True), ('having', False)):
        name = select.get(label)
        if name is None:
            continue
        if name not in conditions:
            problem('INVALID_ORACLE_QUERY', f'{label} names a condition defined in this select', f'{at}.{label}', 'define it in conditions first', name=name, defined=sorted(conditions))
        measure_dependent = uses_measure(conditions, name, set())
        if forbid and measure_dependent:
            problem('INVALID_ORACLE_QUERY', 'where filters rows before aggregation and cannot use measures', f'{at}.where', 'use having for conditions on measures')
        if label == 'having':
            if not grouped:
                problem('INVALID_ORACLE_QUERY', 'having needs groupBy or measures', f'{at}.having')
            keys = {operand_key(g) for g in group_by}
            for ref in condition_operands(conditions, name):
                if 'measure' not in ref and 'literal' not in ref and operand_key(ref) not in keys:
                    problem('INVALID_ORACLE_QUERY', 'having may use measures, literals and group keys only', f'{at}.having', operand=ref)
    columns, seen = [], set()
    keys = {operand_key(g) for g in group_by}
    for i, out in enumerate(select['columns']):
        where = f'{at}.columns[{i}]'
        name = identifier(out['name'], where + '.name')
        if name in seen:
            problem('INVALID_ORACLE_QUERY', 'output column names must be unique', where + '.name', name=name)
        seen.add(name)
        operand = scope.operand(out['operand'], where + '.operand', ('column', 'literal', 'derived', 'measure'))
        if grouped and 'measure' not in operand and 'literal' not in operand and operand_key(operand) not in keys:
            problem('INVALID_ORACLE_QUERY', 'a grouped select outputs group keys and measures only', where + '.operand', 'add this operand to groupBy, or aggregate it with a measure')
        if not grouped and 'measure' in operand:
            problem('INVALID_ORACLE_QUERY', 'a measure needs measures to be declared', where + '.operand')
        columns.append({'name': name, 'operand': operand, 'kind': operand['kind']})
    return {'from': base, 'joins': joins, 'computed': computed, 'measures': measures, 'conditions': planned_conditions, 'where': select.get('where'),
            'groupBy': group_by, 'having': select.get('having'), 'columns': columns, 'grouped': grouped}


def condition_operands(conditions, name):
    found = []
    for term in conditions[name]['terms']:
        if 'condition' in term:
            found += condition_operands(conditions, term['condition'])
            continue
        for key in ('left', 'right', 'upper'):
            if key in term:
                found.append(term[key])
        found += term.get('values', [])
    return found


def plan_report(report, at, tables):
    selects = [plan_select(s, f'{at}.selects[{i}]', tables) for i, s in enumerate(report['selects'])]
    first = selects[0]['columns']
    for i, other in enumerate(selects[1:], 1):
        if [c['kind'] for c in other['columns']] != [c['kind'] for c in first]:
            problem('INVALID_ORACLE_QUERY', 'every select in a combination yields the same column types in the same order', f'{at}.selects[{i}].columns',
                    expected=[c['kind'] for c in first], observed=[c['kind'] for c in other['columns']])
    if len(selects) > 1 and any(c['kind'] in model.LARGE_TYPES for c in first):
        problem('INVALID_ORACLE_QUERY', 'LOB/JSON projection uses one select; combine scalar projections instead', at)
    combine = report['combine'] if len(selects) > 1 else None
    outputs = [{'name': c['name'], 'kind': c['kind']} for c in first]
    if (combine in ('union', 'intersect', 'except') or report['distinct']) and any(c['kind'] in model.NO_EQUALITY_GROUPING for c in first):
        problem('INVALID_ORACLE_QUERY', 'distinct and set operations on time-zone timestamps leave the representative offset unspecified', at, 'convert the value to a date part, or use unionAll without distinct')
    names = {o['name']: o['kind'] for o in outputs}
    columns = dict(names)
    windows = []
    for i, w in enumerate(report['windows']):
        where = f'{at}.windows[{i}]'
        name = identifier(w['name'], where + '.name')
        if name in names:
            problem('INVALID_ORACLE_QUERY', 'window names must differ from output columns and each other', where + '.name', name=name)
        function = w['function']
        argument = w.get('argument')
        if function in ('rowNumber', 'rank', 'denseRank') and argument is not None:
            problem('INVALID_ORACLE_QUERY', f'{function} ranks rows and takes no argument', where + '.argument')
        if function == 'runningSum' and (argument is None or columns.get(argument) != 'number'):
            problem('INVALID_ORACLE_QUERY', 'runningSum needs a number output column as argument', where + '.argument', argument=argument)
        if argument is not None and argument not in columns:
            problem('INVALID_ORACLE_QUERY', 'argument names an output column', where + '.argument', argument=argument, outputs=sorted(columns))
        if not w['orderBy']:
            problem('INVALID_ORACLE_QUERY', f'{function} needs an orderBy within each partition', where + '.orderBy')
        for j, p in enumerate(w['partitionBy']):
            if p not in columns or columns[p] in model.NO_EQUALITY_GROUPING:
                problem('INVALID_ORACLE_QUERY', 'partitionBy names a comparable output column', f'{where}.partitionBy[{j}]', column=p)
        order = plan_order(w['orderBy'], columns, where + '.orderBy')
        windows.append({'name': name, 'function': function, 'argument': argument, 'partitionBy': list(w['partitionBy']), 'orderBy': order})
        names[name] = 'number'
    order = plan_order(report['orderBy'], names, at + '.orderBy')
    if ('limit' in report or 'offset' in report) and not order:
        problem('INVALID_ORACLE_QUERY', 'limit and offset need an orderBy so that the page is well defined', at + '.orderBy')
    return {'selects': selects, 'combine': combine, 'outputs': outputs + [{'name': w['name'], 'kind': 'number'} for w in windows], 'windows': windows,
            'distinct': report['distinct'], 'orderBy': order, 'limit': report.get('limit'), 'offset': report.get('offset', 0), 'numbers': report['numbers']}


def plan_order(terms, names, at):
    planned = []
    for i, term in enumerate(terms):
        if term['column'] not in names or names[term['column']] not in ORDERED:
            problem('INVALID_ORACLE_QUERY', 'order by an orderable output or window column', f'{at}[{i}].column', column=term['column'], outputs=sorted(names))
        planned.append({'column': term['column'], 'direction': term['direction'], 'nulls': term['nulls']})
    return planned


def plan_inspection(inspection, at, tables):
    return {'kinds': list(inspection['kinds']), 'names': [identifier(n, f'{at}.names[{i}]') for i, n in enumerate(inspection['names'])], 'drift': inspection['drift']}


def ledger_steps(transaction, at, tables):
    """Idempotency by ledger: a conflict check, an applied check and a ledger insert in the SAME transaction as the work,
    written as ordinary typed steps so that the reference simulates them and the database enforces them."""
    spec = transaction['idempotency']
    where = at + '.idempotency'
    ledger = tables.get(spec['table'])
    if ledger is None or not ledger['external']:
        problem('INVALID_ORACLE_TRANSACTION', 'the idempotency ledger is an existing table declared external', where + '.table',
                'create the ledger table yourself (a key column and a 64-character digest column), then declare it external', table=spec['table'])
    columns = {c['name']: c for c in ledger['columns']}
    key, digest = spec['keyColumn'], spec['digestColumn']
    for name, need in ((key, len(spec['key'])), (digest, 64)):
        column = columns.get(name)
        if column is None or column['type'] != 'varchar2' or column['nullable'] or column['length'] < need:
            problem('INVALID_ORACLE_TRANSACTION', f'ledger column {name} must be a NOT NULL varchar2 of at least {need} characters', where, column=name)
    if ledger['primaryKey'] != [key]:
        problem('INVALID_ORACLE_TRANSACTION', 'the ledger primary key must be exactly the key column, so a repeated key is also refused by the database', where + '.keyColumn', primaryKey=ledger['primaryKey'])
    body = json.dumps({'steps': transaction['steps'], 'finish': transaction['finish']}, sort_keys=True)
    plan_digest = hashlib.sha256(body.encode()).hexdigest()
    literal = lambda kind, value: {'literal': {'type': kind, 'value': value}}
    column_of = lambda name: {'column': f'{spec["table"]}.{name}'}
    term = lambda name, operator, value: {'left': column_of(name), 'operator': operator, 'right': literal('varchar2', value), 'negate': False}

    def check(label, terms):
        return {'kind': 'check', 'table': spec['table'], 'computed': [], 'conditions': [{'name': label, 'combine': 'and', 'terms': terms, 'negate': False}], 'where': label, 'expectRows': 0,
                'onMatched': 'update', 'onNotMatched': 'insert'}
    before = [check('ledger_conflict', [term(key, 'equals', spec['key']), term(digest, 'notEquals', plan_digest)]), check('ledger_applied', [term(key, 'equals', spec['key'])])]
    after = [{'kind': 'insert', 'table': spec['table'], 'columns': [key, digest], 'rows': [[spec['key'], plan_digest]], 'expectRows': 1, 'computed': [], 'conditions': [],
              'onMatched': 'update', 'onNotMatched': 'insert'}]
    return before, after, {'table': spec['table'], 'keyColumn': key, 'digestColumn': digest, 'key': spec['key'], 'digest': plan_digest}


def plan_transaction(transaction, at, tables):
    steps, savepoints = [], []
    ledger = None
    authored = list(transaction['steps'])
    shift = 0
    if 'idempotency' in transaction:
        before, after, ledger = ledger_steps(transaction, at, tables)
        authored, shift = before + authored + after, len(before)
    for i, step in enumerate(authored):
        where = f'{at}.steps[{i - shift}]' if shift <= i < shift + len(transaction['steps']) else f'{at}.idempotency'
        kind = step['kind']
        allowed = {'insert': ('table', 'columns', 'rows', 'expectRows'), 'update': ('table', 'set', 'computed', 'conditions', 'where', 'expectRows'),
                   'delete': ('table', 'computed', 'conditions', 'where', 'expectRows'),
                   'merge': ('table', 'columns', 'rows', 'keys', 'onMatched', 'onNotMatched', 'expectRows'), 'savepoint': ('name',), 'rollbackTo': ('name',),
                   'check': ('table', 'computed', 'conditions', 'where', 'expectRows')}[kind]
        defaults = {'computed': [], 'conditions': [], 'onMatched': 'update', 'onNotMatched': 'insert'}
        extra = [k for k in step if k != 'kind' and k not in allowed and step[k] != defaults.get(k, object())]
        if extra:
            problem('INVALID_ORACLE_TRANSACTION', f'a {kind} step does not accept: {", ".join(extra)}', where, 'remove the unsupported fields', unexpected=extra)
        planned = {'kind': kind}
        if kind in ('savepoint', 'rollbackTo'):
            if 'name' not in step:
                problem('INVALID_ORACLE_TRANSACTION', f'{kind} needs a name', where + '.name')
            name = identifier(step['name'], where + '.name')
            if kind == 'savepoint':
                savepoints = savepoints[:savepoints.index(name)] + [name] if name in savepoints else savepoints + [name]
            elif name not in savepoints:
                problem('INVALID_ORACLE_TRANSACTION', 'rollbackTo names a savepoint that is active at this point', where + '.name',
                        'savepoints created after an earlier rollbackTo are discarded by Oracle', name=name, active=list(savepoints))
            else:
                savepoints = savepoints[:savepoints.index(name) + 1]
            planned['name'] = name
            steps.append(planned)
            continue
        table = tables.get(step.get('table'))
        if table is None:
            problem('INVALID_ORACLE_TRANSACTION', 'the step names a table that is not declared in tables', where + '.table', declared=sorted(tables), table=step.get('table'))
        planned['table'] = table['name']
        by_col = {c['name']: c for c in table['columns']}
        if 'expectRows' in step:
            planned['expectRows'] = step['expectRows']
        if kind in ('insert', 'merge'):
            planned.update(plan_rows(step, table, by_col, where))
            if kind == 'merge':
                keys = step.get('keys')
                if not keys or set(keys) != set(table['primaryKey']):
                    problem('INVALID_ORACLE_TRANSACTION', 'merge keys are exactly the table primary key', where + '.keys', table=table['name'], primaryKey=table['primaryKey'])
                if any(k not in planned['columns'] for k in keys):
                    problem('INVALID_ORACLE_TRANSACTION', 'merge columns include every key column', where + '.columns')
                if step['onNotMatched'] == 'ignore' and step['onMatched'] == 'ignore':
                    problem('INVALID_ORACLE_TRANSACTION', 'a merge that ignores both matches and misses does nothing', where)
                if not set(planned['columns']) - set(keys) and step['onMatched'] == 'update':
                    problem('INVALID_ORACLE_TRANSACTION', 'merge updates non-key columns: supply at least one, or set onMatched to ignore', where + '.columns')
                planned.update(keys=list(keys), onMatched=step['onMatched'], onNotMatched=step['onNotMatched'])
        else:
            scope = Scope({table['name']: table}, [table['name']])
            planned['computed'] = [scope.derive(d, f'{where}.computed[{j}]') for j, d in enumerate(step['computed'])]
            conds = {}
            planned['conditions'] = []
            for j, c in enumerate(step['conditions']):
                p = scope.condition(c, f'{where}.conditions[{j}]', allow_measure=False)
                conds[p['name']] = p
                planned['conditions'].append(p)
            name = step.get('where')
            if name is not None and name not in conds:
                problem('INVALID_ORACLE_TRANSACTION', 'where names a condition defined in this step', where + '.where', name=name, defined=sorted(conds))
            planned['where'] = name
            if name is None and kind in ('update', 'delete') and 'expectRows' not in step:
                problem('INVALID_ORACLE_TRANSACTION', f'a {kind} without where changes every row: state the expected row count', where + '.expectRows', 'add where, or expectRows to confirm the whole-table intent')
            if kind == 'check' and 'expectRows' not in step:
                problem('INVALID_ORACLE_TRANSACTION', 'check compares a row count: add expectRows', where + '.expectRows')
            if kind == 'update':
                if 'set' not in step:
                    problem('INVALID_ORACLE_TRANSACTION', 'update needs set', where + '.set')
                assigned, planned['set'] = set(), []
                for j, a in enumerate(step['set']):
                    column = a['column']
                    if column not in by_col or column in table['primaryKey'] or column in assigned:
                        problem('INVALID_ORACLE_TRANSACTION', 'set names each non-key column of the table once', f'{where}.set[{j}].column', column=column)
                    assigned.add(column)
                    value = scope.operand(a['value'], f'{where}.set[{j}].value', ('column', 'literal', 'derived'))
                    if value['kind'] != by_col[column]['type']:
                        problem('INVALID_ORACLE_TRANSACTION', 'the assigned value has a different Oracle type from the column', f'{where}.set[{j}].value', column=by_col[column]['type'], value=value['kind'])
                    if 'literal' in value and value['literal']['value'] is None and not by_col[column]['nullable']:
                        problem('INVALID_ORACLE_TRANSACTION', 'NULL cannot be assigned to a not-null column', f'{where}.set[{j}].value')
                    if 'literal' in value and value['literal']['value'] is not None:
                        try:
                            parse_value(by_col[column], value['literal']['value'])
                        except ValueFault as error:
                            problem('INVALID_ORACLE_VALUE', str(error), f'{where}.set[{j}].value', 'a literal must fit the target column: its scale, precision, length and empty-text policy',
                                    column=column, reason=error.reason)
                    planned['set'].append({'column': column, 'value': value})
        steps.append(planned)
    if ledger:
        for index, role in ((0, 'ledger:conflict'), (1, 'ledger:applied'), (len(steps) - 1, 'ledger:record')):
            steps[index]['role'] = role
    return {'steps': steps, 'finish': transaction['finish'], 'isolation': transaction['isolation'], 'enforcement': transaction['enforcement'], 'idempotency': ledger}


def plan_rows(step, table, by_col, where):
    columns = step.get('columns')
    rows = step.get('rows')
    if not columns or not rows:
        problem('INVALID_ORACLE_TRANSACTION', f'{step["kind"]} needs columns and rows', where, 'list the column order, then one array of cells per row')
    for j, name in enumerate(columns):
        if name not in by_col:
            problem('INVALID_ORACLE_TRANSACTION', 'column is not declared in this table', f'{where}.columns[{j}]', column=name, declared=sorted(by_col))
    missing = [c['name'] for c in table['columns'] if not c['nullable'] and c['name'] not in columns]
    if missing:
        problem('INVALID_ORACLE_TRANSACTION', 'every not-null column needs a value (the adaptor declares no column defaults)', where + '.columns', missing=missing)
    planned = []
    for r, row in enumerate(rows):
        if len(row) != len(columns):
            problem('INVALID_ORACLE_TRANSACTION', 'each row has one cell per listed column', f'{where}.rows[{r}]', expected=len(columns), observed=len(row))
        cells = []
        for c, (name, cell) in enumerate(zip(columns, row)):
            column = by_col[name]
            try:
                value = parse_value(column, cell)
            except ValueFault as error:
                problem('INVALID_ORACLE_VALUE', str(error), f'{where}.rows[{r}][{c}]', 'correct the cell for its declared column type', column=name, reason=error.reason)
            if value is None and (not column['nullable'] or name in table['primaryKey']):
                problem('INVALID_ORACLE_VALUE', 'NULL for a not-null column', f'{where}.rows[{r}][{c}]', column=name, reason='null')
            cells.append(canonical(column['type'], value))
        planned.append(cells)
    return {'columns': list(columns), 'rows': planned}


def plan_document(document):
    from schemaxis.errors import keys
    keys(document, ('version', 'operation', *OPTIONS), '$')
    if document.get('version') != VERSION:
        problem('UNSUPPORTED_VERSION', 'expected ' + VERSION, '$.version')
    operation = document.get('operation')
    if operation not in OPERATIONS:
        problem('UNKNOWN_FILTER', 'select inspect, load, report or mutate', '$.operation', operation=str(operation)[:40])
    allowed = OPERATION_OPTIONS[operation]
    stray = [k for k in document if k in OPTIONS and k not in allowed]
    if stray:
        problem('INVALID_ORACLE_OPERATION', f'{", ".join(stray)} does not apply to {operation}', '$.' + stray[0], f'{operation} accepts: {", ".join(allowed)}', unexpected=stray)
    options = validate_arguments({k: OPTIONS[k] for k in allowed}, {k: v for k, v in document.items() if k in allowed})
    plan = {'version': PLAN_VERSION, 'operation': operation, 'connection': plan_connection(options['connection'])}
    raw_tables = options.get('tables')
    if raw_tables is None:
        if operation != 'inspect':
            problem('MISSING_ARGUMENT', f'{operation} needs tables', '$.tables', 'declare the tables, with source files for the rows to load')
        tables, order = [], []
    else:
        tables, order = plan_tables(raw_tables)
    plan['tables'], plan['order'] = tables, order
    by_name = {t['name']: t for t in tables}
    if operation == 'inspect':
        if any(t['source'] for t in tables):
            problem('INVALID_ORACLE_TABLE', 'inspect compares declarations with the database and loads nothing', '$.tables', 'remove source from inspect tables')
        plan['inspection'] = plan_inspection(options['inspection'] if 'inspection' in options else validate_arguments({'i': OPTIONS['inspection']}, {'i': {}})['i'], '$.inspection', by_name)
    else:
        setup = options.get('setup', {})
        # A run only ever creates tables whose names are free; it never replaces or drops anything it did not create.
        plan['setup'] = {'retain': setup.get('retain', operation == 'load')}
        if not any(not t['external'] for t in tables) and operation == 'load':
            problem('INVALID_ORACLE_TABLE', 'load creates at least one table; every table is marked external', '$.tables', 'set external to false for the tables to create')
        if operation == 'report':
            if 'report' not in options:
                problem('MISSING_ARGUMENT', 'report needs a report definition', '$.report')
            plan['report'] = plan_report(options['report'], '$.report', by_name)
        elif operation == 'mutate':
            if 'transaction' not in options:
                problem('MISSING_ARGUMENT', 'mutate needs a transaction', '$.transaction')
            external = [i for i, t in enumerate(tables) if t['external']]
            tx = options['transaction']
            if external:
                # An existing table's state is not known from a captured source, so the reference takes its base state from a read
                # inside the transaction itself. That needs a stable snapshot, the database's own refusal of bad work, and a ledger.
                if tx['isolation'] != 'serializable':
                    problem('INVALID_ORACLE_TRANSACTION', 'a transaction on existing tables runs SERIALIZABLE so that its base read and its changes see one snapshot', '$.transaction.isolation',
                            'set isolation to serializable')
                if tx['enforcement'] != 'database':
                    problem('INVALID_ORACLE_TRANSACTION', 'the host cannot predict refusals for tables whose rows it does not hold; the database must refuse them', '$.transaction.enforcement',
                            'set enforcement to database')
                if 'idempotency' not in tx:
                    problem('MISSING_ARGUMENT', 'a transaction on existing tables needs an idempotency key and ledger so that a retry cannot apply it twice', '$.transaction.idempotency',
                            'declare an external ledger table and a unique key for this change')
            elif 'idempotency' in tx:
                problem('INVALID_ORACLE_TRANSACTION', 'idempotency applies to transactions on existing tables; created tables are fresh in every run', '$.transaction.idempotency')
            plan['transaction'] = plan_transaction(options['transaction'], '$.transaction', by_name)
    plan['losses'] = LOSSES
    return json.loads(json.dumps(plan))
