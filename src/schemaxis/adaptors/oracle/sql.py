"""Trusted Oracle SQL generation from validated plans.

Values travel as positional binds, never as spliced text; the only inline
literals are those inside generated CHECK constraints (DDL cannot bind), which
are rendered by the same escaping function and validated again by the worker.
Placeholders are numbered in the order they appear in the statement text.
"""
import json

from . import model

MARKER_PREFIX = 'schemaxis-oracle:run:'
MASKS = {'date': 'YYYY-MM-DD"T"HH24:MI:SS', 'timestamp': 'YYYY-MM-DD"T"HH24:MI:SS.FF6',
         'timestampTz': 'YYYY-MM-DD"T"HH24:MI:SS.FF6TZH:TZM'}
SQL_OPERATORS = {'equals': '=', 'notEquals': '<>', 'lessThan': '<', 'lessOrEqual': '<=', 'greaterThan': '>', 'greaterOrEqual': '>='}
AGGREGATES = {'count': 'COUNT({})', 'countDistinct': 'COUNT(DISTINCT {})', 'sum': 'SUM({})', 'average': 'AVG({})', 'minimum': 'MIN({})', 'maximum': 'MAX({})'}
WINDOW_SQL = {'rowNumber': 'ROW_NUMBER()', 'rank': 'RANK()', 'denseRank': 'DENSE_RANK()'}


def q(name):
    return '"' + name.upper() + '"'


def bind_type(kind):
    return {'number': 'number', 'boolean': 'boolean', 'clob': 'clob', 'blob': 'blob', 'json': 'clob'}.get(kind, 'varchar')


def bind_text(kind, value):
    """Canonical cell to the exact text/bool a bind carries (fixed 6-digit fractions for TO_TIMESTAMP masks)."""
    if value is None or kind in ('number', 'varchar2', 'boolean', 'raw', 'clob', 'blob', 'json'):
        return value
    if kind == 'date':
        return value
    typed = model.parse_stamp(value, kind, 6)
    text = typed.strftime('%Y-%m-%dT%H:%M:%S.%f')
    if kind == 'timestampTz':
        minutes = int(typed.utcoffset().total_seconds() // 60)
        text += '%s%02d:%02d' % ('-' if minutes < 0 else '+', abs(minutes) // 60, abs(minutes) % 60)
    return text


def wrap(kind, placeholder):
    if kind == 'json':
        return f'JSON({placeholder})'
    if kind == 'date':
        return f"TO_DATE({placeholder}, '{MASKS['date']}')"
    if kind == 'timestamp':
        return f"TO_TIMESTAMP({placeholder}, '{MASKS['timestamp']}')"
    if kind == 'timestampTz':
        return f"TO_TIMESTAMP_TZ({placeholder}, '{MASKS['timestampTz']}')"
    if kind == 'raw':
        return f'HEXTORAW({placeholder})'
    return placeholder


def quote_text(value):
    if any(ord(c) < 32 for c in value):
        raise ValueError('control characters cannot be spliced into DDL')
    return "'" + value.replace("'", "''") + "'"


class Renderer:
    def __init__(self, inline=False):
        self.inline = inline
        self.binds = []

    def literal(self, kind, value):
        if value is None:
            return 'NULL'
        if self.inline:
            if kind == 'number':
                return value
            if kind == 'boolean':
                return 'TRUE' if value else 'FALSE'
            return wrap(kind, quote_text(bind_text(kind, value)))
        self.binds.append({'t': bind_type(kind), 'v': bind_text(kind, value)})
        return wrap(kind, ':%d' % len(self.binds))

    def value(self, kind, value):
        """One positional bind for a row cell inside an already wrapped statement."""
        self.binds.append({'t': bind_type(kind), 'v': bind_text(kind, value)})
        return wrap(kind, ':%d' % len(self.binds))


class Expressions:
    """Render operands/derived values/conditions for one scope; every use re-renders so binds stay in text order."""

    def __init__(self, renderer, derived=(), conditions=(), measures=(), column=None, keys=None, bare=False):
        self.r = renderer
        self.derived = {d['name']: d for d in derived}
        self.conditions = {c['name']: c for c in conditions}
        self.measures = {m['name']: m for m in measures}
        self.column = column or (lambda ref: (q(ref.split('.')[1]) if bare else q(ref.split('.')[0]) + '.' + q(ref.split('.')[1])))
        self.keys = keys

    def operand(self, op):
        if self.keys is not None and ('column' in op or 'derived' in op):
            alias = self.keys.get(json.dumps({k: v for k, v in op.items() if k != 'kind'}, sort_keys=True))
            if alias is not None:
                return alias
        if 'column' in op:
            return self.column(op['column'])
        if 'literal' in op:
            return self.r.literal(op['literal']['type'], op['literal']['value'])
        if 'derived' in op:
            return self.derive(self.derived[op['derived']])
        return self.measure(self.measures[op['measure']])

    def measure(self, m):
        if m['function'] == 'countAll':
            return 'COUNT(*)'
        return AGGREGATES[m['function']].format(self.operand(m['argument']))

    def derive(self, d):
        f, args = d['function'], d['arguments']
        if f.startswith('json'):
            returning = {'jsonNumber': 'NUMBER', 'jsonText': 'VARCHAR2(1000)', 'jsonBoolean': 'BOOLEAN'}[f]
            return f'JSON_VALUE({self.operand(args[0])}, {quote_text(d["path"])} RETURNING {returning} ERROR ON ERROR NULL ON EMPTY)'
        if f == 'conditional':
            condition = self.condition(d['when'])
            return f'(CASE WHEN {condition} THEN {self.operand(args[0])} ELSE {self.operand(args[1])} END)'
        parts = [self.operand(a) for a in args]
        if f in ('add', 'subtract', 'multiply', 'addDays'):
            return '(' + parts[0] + {'add': ' + ', 'subtract': ' - ', 'multiply': ' * ', 'addDays': ' + '}[f] + parts[1] + ')'
        if f == 'divide':
            return f'({parts[0]} / NULLIF({parts[1]}, 0))' if d['zero'] == 'null' else f'({parts[0]} / {parts[1]})'
        if f == 'negate':
            return f'(-{parts[0]})'
        if f == 'concat':
            return '(' + ' || '.join(parts) + ')'
        if f in ('round', 'truncate'):
            return f'{"ROUND" if f == "round" else "TRUNC"}({parts[0]}, {int(d["digits"])})'
        call = {'modulo': 'MOD', 'abs': 'ABS', 'floor': 'FLOOR', 'ceiling': 'CEIL', 'upper': 'UPPER', 'lower': 'LOWER', 'trim': 'TRIM', 'substring': 'SUBSTR',
                'length': 'LENGTH', 'coalesce': 'COALESCE', 'nullIf': 'NULLIF', 'truncateDay': 'TRUNC'}.get(f)
        if call:
            return f'{call}({", ".join(parts)})'
        return f'EXTRACT({f[7:].upper()} FROM {parts[0]})'

    def condition(self, c):
        joiner = ' AND ' if c['combine'] == 'and' else ' OR '
        inner = joiner.join(self.term(t) for t in c['terms'])
        return f'(NOT ({inner}))' if c['negate'] else f'({inner})'

    def term(self, t):
        if 'condition' in t:
            body = self.condition(self.conditions[t['condition']])
            return f'(NOT {body})' if t['negate'] else body
        op = t['operator']
        left = self.operand(t['left'])
        if op in SQL_OPERATORS:
            body = f'{left} {SQL_OPERATORS[op]} {self.operand(t["right"])}'
        elif op == 'between':
            low = self.operand(t['right'])
            body = f'{left} BETWEEN {low} AND {self.operand(t["upper"])}'
        elif op == 'in':
            body = f'{left} IN ({", ".join(self.operand(v) for v in t["values"])})'
        elif op == 'isNull':
            body = f'{left} IS NULL'
        elif op == 'startsWith':
            first, second = self.operand(t['right']), self.operand(t['right'])
            body = f'SUBSTR({left}, 1, LENGTH({first})) = {second}'
        else:
            body = f'INSTR({left}, {self.operand(t["right"])}) > 0'
        return f'(NOT ({body}))' if t['negate'] else f'({body})'


# --- relations ---------------------------------------------------------------
def from_clause(select):
    text = f'FROM {q(select["from"]["table"])} {q(select["from"]["alias"])}'
    for join in select['joins']:
        kind = {'inner': 'INNER JOIN', 'left': 'LEFT OUTER JOIN', 'right': 'RIGHT OUTER JOIN', 'full': 'FULL OUTER JOIN'}[join['type']]
        keys = ' AND '.join(f'{q(k["left"].split(".")[0])}.{q(k["left"].split(".")[1])} = {q(k["right"].split(".")[0])}.{q(k["right"].split(".")[1])}' for k in join['on'])
        text += f' {kind} {q(join["table"])} {q(join["alias"])} ON {keys}'
    return text


def select_sql(select, renderer):
    conditions = {c['name']: c for c in select['conditions']}
    if not select['grouped']:
        ex = Expressions(renderer, select['computed'], select['conditions'], select['measures'])
        fields = ', '.join(f'{ex.operand(c["operand"])} AS {q(c["name"])}' for c in select['columns'])
        sql = f'SELECT {fields} {from_clause(select)}'
        if select['where']:
            sql += ' WHERE ' + ex.condition(conditions[select['where']])
        return sql
    keys, alias_of = {}, []
    for i, key in enumerate(select['groupBy'], 1):
        keys[json.dumps({k: v for k, v in key.items() if k != 'kind'}, sort_keys=True)] = f'"G"."K{i}"'
        alias_of.append((f'K{i}', key))
    arguments = {}
    for i, m in enumerate(select['measures'], 1):
        if m['argument'] is not None:
            signature = json.dumps({k: v for k, v in m['argument'].items() if k != 'kind'}, sort_keys=True)
            if signature not in keys and signature not in arguments:
                arguments[signature] = f'"G"."A{i}"'
                alias_of.append((f'A{i}', m['argument']))
    outer = Expressions(renderer, select['computed'], select['conditions'], select['measures'], keys={**keys, **arguments})
    fields = ', '.join(f'{outer.operand(c["operand"])} AS {q(c["name"])}' for c in select['columns'])
    inner_ex = Expressions(renderer, select['computed'], select['conditions'], select['measures'])
    # The inner relation is rendered after the outer list so placeholder numbers follow the statement text.
    inner_parts = [f'{inner_ex.operand(operand)} AS "{alias}"' for alias, operand in alias_of] or ['1 AS "ONE"']
    inner = f'SELECT {", ".join(inner_parts)} {from_clause(select)}'
    if select['where']:
        inner += ' WHERE ' + inner_ex.condition(conditions[select['where']])
    sql = f'SELECT {fields} FROM ({inner}) "G"'
    if select['groupBy']:
        sql += ' GROUP BY ' + ', '.join(f'"G"."K{i}"' for i in range(1, len(select['groupBy']) + 1))
    if select['having']:
        sql += ' HAVING ' + outer.condition(conditions[select['having']])
    return sql


def order_sql(terms, prefix):
    return ', '.join(f'{prefix}.{q(t["column"])} {"ASC" if t["direction"] == "ascending" else "DESC"} NULLS {t["nulls"].upper()}' for t in terms)


def textual(kind, ref):
    if kind in MASKS:
        # SYYYY prints a BC year with a minus sign; YYYY would silently show it as an AD year. The reader refuses negative years.
        return f"TO_CHAR({ref}, '{MASKS[kind].replace('YYYY', 'SYYYY', 1)}')"
    if kind == 'json':
        return f'JSON_SERIALIZE({ref} RETURNING CLOB ERROR ON ERROR)'
    if kind == 'raw':
        return f'RAWTOHEX({ref})'
    return ref


def report_sql(report):
    """One SELECT over layered, aliased subqueries: combine, windows, distinct, then text-safe output."""
    renderer = Renderer()
    selects = [select_sql(s, renderer) for s in report['selects']]
    if report['combine']:
        operator = {'unionAll': 'UNION ALL', 'union': 'UNION', 'intersect': 'INTERSECT', 'except': 'MINUS'}[report['combine']]
        sql = f' {operator} '.join(f'({s})' for s in selects)
    else:
        sql = selects[0]
    if report['windows']:
        extra = []
        for w in report['windows']:
            over = ''
            if w['partitionBy']:
                over += 'PARTITION BY ' + ', '.join(f'"Q".{q(p)}' for p in w['partitionBy']) + ' '
            over += 'ORDER BY ' + order_sql(w['orderBy'], '"Q"')
            if w['function'] in WINDOW_SQL:
                expr = f'{WINDOW_SQL[w["function"]]} OVER ({over})'
            else:
                argument = f'"Q".{q(w["argument"])}' if w['argument'] else '*'
                func = 'SUM' if w['function'] == 'runningSum' else 'COUNT'
                expr = f'{func}({argument}) OVER ({over} ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)'
            extra.append(f'{expr} AS {q(w["name"])}')
        sql = f'SELECT "Q".*, {", ".join(extra)} FROM ({sql}) "Q"'
    if report['distinct']:
        sql = f'SELECT DISTINCT "D".* FROM ({sql}) "D"'
    outputs = report['outputs']
    fields = ', '.join('%s AS %s' % (textual(o['kind'], '"R".' + q(o['name'])), q(o['name'])) for o in outputs)
    sql = f'SELECT {fields} FROM ({sql}) "R"'
    if report['orderBy']:
        sql += ' ORDER BY ' + order_sql(report['orderBy'], '"R"')
    if report['offset']:
        sql += f' OFFSET {int(report["offset"])} ROWS'
    if report['limit']:
        sql += f' FETCH NEXT {int(report["limit"])} ROWS ONLY'
    return sql, renderer.binds, [{'name': o['name'], 'kind': o['kind']} for o in outputs]


# --- DDL and DML --------------------------------------------------------------
def column_type(column):
    kind = column['type']
    if kind in model.LARGE_TYPES:
        return kind.upper()
    if kind == 'number':
        return 'NUMBER' if column['precision'] is None else f'NUMBER({column["precision"]},{column["scale"]})'
    if kind == 'varchar2':
        return f'VARCHAR2({column["length"]} CHAR)'
    if kind == 'raw':
        return f'RAW({column["length"]})'
    if kind == 'date':
        return 'DATE'
    if kind == 'boolean':
        return 'BOOLEAN'
    return f'TIMESTAMP({column["fraction"]})' + (' WITH TIME ZONE' if kind == 'timestampTz' else '')


def constraint_names(table):
    name = table['name']
    return {'primary': f'{name}_pk', 'unique': [f'{name}_u{i}' for i, _ in enumerate(table['unique'], 1)],
            'foreign': [f'{name}_fk{i}' for i, _ in enumerate(table['foreignKeys'], 1)], 'check': [f'{name}_c{i}' for i, _ in enumerate(table['checks'], 1)]}


def create_table_sql(table):
    names = constraint_names(table)
    parts = [f'{q(c["name"])} {column_type(c)}' + ('' if c['nullable'] and c['name'] not in table['primaryKey'] else ' NOT NULL') for c in table['columns']]
    parts.append(f'CONSTRAINT {q(names["primary"])} PRIMARY KEY ({", ".join(map(q, table["primaryKey"]))})')
    for n, cols in zip(names['unique'], table['unique']):
        parts.append(f'CONSTRAINT {q(n)} UNIQUE ({", ".join(map(q, cols))})')
    for n, fk in zip(names['foreign'], table['foreignKeys']):
        rule = {'noAction': '', 'cascade': ' ON DELETE CASCADE', 'setNull': ' ON DELETE SET NULL'}[fk['onDelete']]
        parts.append(f'CONSTRAINT {q(n)} FOREIGN KEY ({", ".join(map(q, fk["columns"]))}) REFERENCES {q(fk["table"])} ({", ".join(map(q, fk["references"]))}){rule}')
    for n, check in zip(names['check'], table['checks']):
        ex = Expressions(Renderer(inline=True), (), table['checks'], (), bare=True)
        parts.append(f'CONSTRAINT {q(n)} CHECK {ex.condition(check)}')
    return f'CREATE TABLE {q(table["name"])} ({", ".join(parts)}) SEGMENT CREATION IMMEDIATE'


def run_marker(run_id):
    """Ownership marker bound to one run: a table carrying it was created by exactly that run."""
    return MARKER_PREFIX + run_id


def comment_sql(table, marker):
    return f"COMMENT ON TABLE {q(table['name'])} IS '{marker}'"


def drop_sql(name):
    return f'DROP TABLE {q(name)} PURGE'


def insert_sql(table, columns, kinds):
    renderer = Renderer()
    values = ', '.join(renderer.value(kinds[c], None) for c in columns)
    return f'INSERT INTO {q(table)} ({", ".join(map(q, columns))}) VALUES ({values})', [b['t'] for b in renderer.binds]


def row_binds(columns, kinds, row):
    return [bind_text(kinds[c], v) for c, v in zip(columns, row)]


def merge_sql(step, kinds):
    renderer = Renderer()
    source = ', '.join(f'{renderer.value(kinds[c], None)} AS {q(c)}' for c in step['columns'])
    keys = step['keys']
    on = ' AND '.join(f'"TGT$".{q(k)} = "SRC$".{q(k)}' for k in keys)
    sql = f'MERGE INTO {q(step["table"])} "TGT$" USING (SELECT {source} FROM DUAL) "SRC$" ON ({on})'
    updates = [c for c in step['columns'] if c not in keys]
    if step['onMatched'] == 'update' and updates:
        sql += ' WHEN MATCHED THEN UPDATE SET ' + ', '.join(f'"TGT$".{q(c)} = "SRC$".{q(c)}' for c in updates)
    if step['onNotMatched'] == 'insert':
        inserted = ', '.join('"SRC$".' + q(c) for c in step['columns'])
        sql += f' WHEN NOT MATCHED THEN INSERT ({", ".join(map(q, step["columns"]))}) VALUES ({inserted})'
    return sql, [b['t'] for b in renderer.binds]


def where_sql(step, renderer, table):
    ex = Expressions(renderer, step['computed'], step['conditions'], (), column=lambda ref: f'{q(table)}.{q(ref.split(".")[1])}')
    return ex, {c['name']: c for c in step['conditions']}


def dml_sql(step):
    """Statement text and binds for a set-based update, delete or count check."""
    renderer = Renderer()
    table = step['table']
    ex, conditions = where_sql(step, renderer, table)
    if step['kind'] == 'update':
        assignments = ', '.join(f'{q(a["column"])} = {ex.operand(a["value"])}' for a in step['set'])
        sql = f'UPDATE {q(table)} SET {assignments}'
    elif step['kind'] == 'delete':
        sql = f'DELETE FROM {q(table)}'
    else:
        sql = f'SELECT COUNT(*) AS "N" FROM {q(table)}'
    if step['where']:
        sql += ' WHERE ' + ex.condition(conditions[step['where']])
    return sql, renderer.binds


def table_readback_sql(table):
    fields = ', '.join(f'{textual(c["type"], q(c["name"]))} AS {q(c["name"])}' for c in table['columns'])
    order = ', '.join(q(k) for k in table['primaryKey'])
    return f'SELECT {fields} FROM {q(table["name"])} ORDER BY {order}'


# --- dictionary ---------------------------------------------------------------
def catalog_queries(names):
    """Fixed dictionary queries for the connected schema; names optionally restrict table-like objects."""
    marks = ', '.join(f':{i}' for i in range(1, len(names) + 1))
    filt = lambda column: f' AND {column} IN ({marks})' if names else ''
    binds = [{'t': 'varchar', 'v': n.upper()} for n in names]
    queries = {
        'tables': ('SELECT t.table_name, c.comments FROM user_tables t LEFT JOIN user_tab_comments c ON c.table_name = t.table_name AND c.table_type = \'TABLE\' '
                   'WHERE t.temporary = \'N\' AND t.secondary = \'N\' AND t.dropped = \'NO\'' + filt('t.table_name') + ' ORDER BY t.table_name', binds),
        'columns': ('SELECT table_name, column_name, data_type, data_length, char_length, char_used, data_precision, data_scale, nullable, column_id FROM user_tab_cols '
                    'WHERE hidden_column = \'NO\'' + filt('table_name') + ' ORDER BY table_name, column_id', binds),
        'constraints': ('SELECT c.table_name, c.constraint_name, c.constraint_type, c.delete_rule, cc.column_name, cc.position, p.table_name AS parent_table, pc.column_name AS parent_column '
                        'FROM user_constraints c LEFT JOIN user_cons_columns cc ON cc.constraint_name = c.constraint_name LEFT JOIN user_constraints p ON p.constraint_name = c.r_constraint_name '
                        'LEFT JOIN user_cons_columns pc ON pc.constraint_name = p.constraint_name AND pc.position = cc.position '
                        'WHERE c.constraint_type IN (\'P\', \'U\', \'R\', \'C\') AND (c.constraint_type <> \'C\' OR c.search_condition_vc IS NULL OR c.search_condition_vc NOT LIKE \'%IS NOT NULL\')'
                        + filt('c.table_name') + ' ORDER BY c.table_name, c.constraint_name, cc.position', binds),
        'indexes': ('SELECT i.table_name, i.index_name, i.uniqueness, ic.column_name, ic.column_position FROM user_indexes i JOIN user_ind_columns ic ON ic.index_name = i.index_name '
                    'WHERE 1 = 1' + filt('i.table_name') + ' ORDER BY i.table_name, i.index_name, ic.column_position', binds),
        'views': ('SELECT view_name FROM user_views WHERE 1 = 1' + filt('view_name') + ' ORDER BY view_name', binds),
        'sequences': ('SELECT sequence_name, min_value, max_value, increment_by, cycle_flag, order_flag, cache_size FROM user_sequences WHERE 1 = 1' + filt('sequence_name') + ' ORDER BY sequence_name', binds),
    }
    return {k: {'sql': sql, 'binds': b} for k, (sql, b) in queries.items()}


def identity_queries():
    return {'session': {'sql': "SELECT SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') AS schema_name, SYS_CONTEXT('USERENV', 'CON_NAME') AS container_name FROM DUAL", 'binds': []},
            'charset': {'sql': "SELECT value FROM nls_database_parameters WHERE parameter = 'NLS_CHARACTERSET'", 'binds': []},
            'version': {'sql': 'SELECT banner_full FROM v$version WHERE ROWNUM = 1', 'binds': []}}


def mutation_boundary_queries(names):
    """Metadata only: refuse database mechanisms whose effects escape declared rows."""
    marks = ', '.join(':' + str(i) for i in range(1, len(names) + 1))
    binds = [{'t': 'varchar', 'v': name.upper()} for name in names]
    specs = {
        'triggers': f"SELECT table_name, trigger_name FROM user_triggers WHERE status = 'ENABLED' AND table_name IN ({marks}) ORDER BY table_name, trigger_name",
        'virtualColumns': f"SELECT table_name, column_name FROM user_tab_cols WHERE virtual_column = 'YES' AND table_name IN ({marks}) ORDER BY table_name, column_name",
        'defaults': f"SELECT table_name, column_name FROM user_tab_cols WHERE default_length > 0 AND table_name IN ({marks}) ORDER BY table_name, column_name",
        'indexes': f"SELECT table_name, index_name, index_type FROM user_indexes WHERE index_type NOT IN ('NORMAL', 'NORMAL/REV', 'BITMAP', 'IOT - TOP') AND table_name IN ({marks}) ORDER BY table_name, index_name",
        'referenceGrants': f"SELECT table_name, grantee FROM user_tab_privs_made WHERE privilege = 'REFERENCES' AND table_name IN ({marks}) ORDER BY table_name, grantee",
        'columnReferenceGrants': f"SELECT table_name, column_name, grantee FROM user_col_privs_made WHERE privilege = 'REFERENCES' AND table_name IN ({marks}) ORDER BY table_name, column_name, grantee",
        'policies': f"SELECT object_name, policy_name FROM all_policies WHERE object_owner = SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') AND enable = 'YES' AND object_name IN ({marks}) ORDER BY object_name, policy_name",
        'incomingActions': ("SELECT c.owner, c.table_name, c.constraint_name, c.delete_rule FROM all_constraints c JOIN all_constraints p "
                            "ON p.owner = c.r_owner AND p.constraint_name = c.r_constraint_name "
                            "WHERE c.constraint_type = 'R' AND c.status = 'ENABLED' AND c.delete_rule IN ('CASCADE', 'SET NULL') "
                            "AND p.owner = SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') "
                            f"AND p.table_name IN ({marks}) AND (c.owner <> p.owner OR c.table_name NOT IN ({', '.join(':' + str(i) for i in range(len(names) + 1, 2 * len(names) + 1))})) "
                            "ORDER BY c.owner, c.table_name, c.constraint_name"),
    }
    return {key: {'sql': text, 'binds': binds + binds if key == 'incomingActions' else binds} for key, text in specs.items()}
