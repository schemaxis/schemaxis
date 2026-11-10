"""Independent host reference: literal relational and constraint semantics with Oracle rules.

Nothing here generates SQL or imports a driver. It evaluates the validated plan over
exact Python values (Decimal, str, datetime, bytes) with SQL three-valued logic, so a
native result is compared with a computation that does not share its code path.
"""
import copy
import csv
import io
import json
import re
from datetime import timedelta, timezone
from decimal import Context, Decimal, DivisionByZero, InvalidOperation, Overflow, ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_UP

from . import model, sql
from .model import CTX, ValueFault, canonical, from_native, parse_value, problem, sort_key

# Oracle NUMBER arithmetic carries 40 significant digits (observed natively: 1/3 -> .333... with 40 threes; 2/3 ends in 7), so
# the reference computes at 40 digits with half-up rounding and compares computed values at TOLERANCE_DIGITS.
CONTEXT = Context(prec=40, rounding=ROUND_HALF_UP, Emax=125, Emin=-130, traps=[InvalidOperation, DivisionByZero, Overflow])
TOLERANCE_DIGITS = 36


class Predicted(Exception):
    """The reference predicts that Oracle refuses this work (constraint, arithmetic or expectation)."""

    def __init__(self, kind, message, errors=(), **where):
        super().__init__(message)
        self.kind, self.errors, self.where = kind, tuple(errors), where


class Unverifiable(Exception):
    pass


class Ambiguous(Exception):
    pass


# --- source capture ---------------------------------------------------------------
def decode_json(data):
    def unique(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise ValueError('duplicate JSON key ' + k)
            out[k] = v
        return out

    def constant(name):
        raise ValueError('nonfinite JSON ' + name)
    return json.loads(data.decode('utf-8'), object_pairs_hook=unique, parse_float=Decimal, parse_constant=constant)


def parse_source(table, data, at):
    """Typed rows of one captured source, validated against the declared columns (no database needed)."""
    columns = table['columns']
    names = [c['name'] for c in columns]
    csv_mode = table['source']['format'] == 'csv'
    try:
        if csv_mode:
            reader = list(csv.reader(io.StringIO(data.decode('utf-8'), newline='')))
            if not reader or reader[0] != names:
                raise ValueFault('header', 'the CSV header must list exactly the declared columns in order: ' + ', '.join(names))
            records = reader[1:]
            if any(len(r) != len(names) for r in records):
                raise ValueFault('shape', 'every CSV row needs one field per declared column')
        else:
            records = decode_json(data)
            if not isinstance(records, list) or any(not isinstance(r, dict) or set(r) != set(names) for r in records):
                raise ValueFault('shape', 'a JSON source is an array of objects with exactly the declared columns')
    except (ValueError, UnicodeError) as error:
        reason = error.reason if isinstance(error, ValueFault) else 'malformed'
        problem('INVALID_ORACLE_SOURCE', 'the source is not valid typed data: ' + str(error), at, 'fix the file, then run again', table=table['name'], reason=reason)
    if len(records) > model.MAX_ROWS:
        problem('INVALID_ORACLE_SOURCE', f'a source holds at most {model.MAX_ROWS} rows', at, table=table['name'], reason='too-many-rows', rows=len(records))
    rows = []
    for number, record in enumerate(records):
        row = {}
        for index, column in enumerate(columns):
            raw = record[index] if csv_mode else record[column['name']]
            try:
                value = parse_value(column, raw, csv=csv_mode)
            except ValueFault as error:
                problem('INVALID_ORACLE_VALUE', str(error), at, 'correct the value for its declared column', table=table['name'], row=number, column=column['name'], reason=error.reason)
            if value is None and (not column['nullable'] or column['name'] in table['primaryKey']):
                problem('INVALID_ORACLE_VALUE', 'NULL (or empty text, which Oracle stores as NULL) in a not-null column', at, table=table['name'], row=number, column=column['name'], reason='null')
            row[column['name']] = value
        rows.append(row)
    return rows


def typed_row(table, columns, cells):
    by_name = {c['name']: c for c in table['columns']}
    row = {c['name']: None for c in table['columns']}
    for name, cell in zip(columns, cells):
        row[name] = parse_value(by_name[name], cell)
    return row


def table_rows_native(table, rows):
    return [{c['name']: from_native(c['type'], v) for c, v in zip(table['columns'], row)} for row in rows]


def table_rows_canonical(table, rows):
    kinds = {c['name']: c['type'] for c in table['columns']}
    ordered = sorted(rows, key=lambda r: tuple(sort_key(kinds[k], r[k]) for k in table['primaryKey']))
    return [[canonical(c['type'], r[c['name']]) for c in table['columns']] for r in ordered]


# --- expressions and conditions ---------------------------------------------------
def compare(a, b):
    if a is None or b is None:
        return None
    return (a > b) - (a < b)


def logic_and(values):
    if any(v is False for v in values):
        return False
    return None if any(v is None for v in values) else True


def logic_or(values):
    if any(v is True for v in values):
        return True
    return None if any(v is None for v in values) else False


def logic_not(value):
    return None if value is None else not value


class Evaluator:
    def __init__(self, derived=(), conditions=(), measures=None):
        self.derived = {d['name']: d for d in derived}
        self.conditions = {c['name']: c for c in conditions}
        self.measures = measures

    def operand(self, op, ctx):
        if 'column' in op:
            if ctx.get('keys') is not None:
                key = json.dumps({k: v for k, v in op.items() if k != 'kind'}, sort_keys=True)
                if key in ctx['keys']:
                    return ctx['keys'][key]
            alias, name = op['column'].split('.')
            row = ctx['rows'][alias]
            return None if row is None else row[name]
        if 'literal' in op:
            literal = op['literal']
            return None if literal['value'] is None else parse_value(model.LITERAL_COLUMN | {'type': literal['type']}, literal['value'])
        if 'derived' in op:
            if ctx.get('keys') is not None:
                key = json.dumps({k: v for k, v in op.items() if k != 'kind'}, sort_keys=True)
                if key in ctx['keys']:
                    return ctx['keys'][key]
            return self.derive(self.derived[op['derived']], ctx)
        return ctx['measures'][op['measure']]

    def condition(self, cond, ctx):
        values = [self.term(t, ctx) for t in cond['terms']]
        result = logic_and(values) if cond['combine'] == 'and' else logic_or(values)
        return logic_not(result) if cond['negate'] else result

    def term(self, term, ctx):
        if 'condition' in term:
            result = self.condition(self.conditions[term['condition']], ctx)
        else:
            op = term['operator']
            left = self.operand(term['left'], ctx)
            if op == 'isNull':
                result = left is None
            elif op == 'in':
                items = [self.operand(v, ctx) for v in term['values']]
                matches = [compare(left, i) == 0 for i in items]
                result = None if left is None else True if any(matches) else None if any(i is None for i in items) else False
            elif op == 'between':
                low, high = self.operand(term['right'], ctx), self.operand(term['upper'], ctx)
                lo, hi = compare(left, low), compare(left, high)
                result = logic_and([None if lo is None else lo >= 0, None if hi is None else hi <= 0])
            else:
                right = self.operand(term['right'], ctx)
                if left is None or right is None:
                    result = None
                elif op == 'startsWith':
                    result = left.startswith(right)
                elif op == 'contains':
                    result = right in left
                else:
                    c = compare(left, right)
                    result = {'equals': c == 0, 'notEquals': c != 0, 'lessThan': c < 0, 'lessOrEqual': c <= 0, 'greaterThan': c > 0, 'greaterOrEqual': c >= 0}[op]
        return logic_not(result) if term['negate'] else result

    def derive(self, d, ctx):
        f = d['function']
        if f == 'conditional':
            return self.operand(d['arguments'][0] if self.condition(d['when'], ctx) is True else d['arguments'][1], ctx)
        args = [self.operand(a, ctx) for a in d['arguments']]
        if f.startswith('json'):
            if args[0] is None:
                return None
            values = [json.loads(args[0], parse_float=Decimal, parse_int=Decimal)]
            for member, index in re.findall(r'\.([A-Za-z_][A-Za-z0-9_]*)|\[([0-9]+)\]', d['path'][1:]):
                found = []
                for value in values:
                    if member:
                        # Oracle lax paths unwrap one array level for a member step.
                        objects = value if isinstance(value, list) else [value]
                        found.extend(v[member] for v in objects if isinstance(v, dict) and member in v)
                    else:
                        array = value if isinstance(value, list) else [value]
                        if int(index) < len(array):
                            found.append(array[int(index)])
                values = found
            if not values:
                return None
            if len(values) != 1:
                raise Unverifiable('JSON scalar path matches multiple values')
            value = values[0]
            if value is None:
                return None
            if isinstance(value, (list, dict)):
                raise Unverifiable('JSON scalar extraction found an object or array')
            if f == 'jsonNumber':
                if isinstance(value, bool):
                    raise Unverifiable('JSON number extraction found a boolean')
                try:
                    return model.parse_decimal(value, {})
                except model.ValueFault as error:
                    raise Unverifiable(str(error)) from error
            if f == 'jsonBoolean':
                if isinstance(value, str) and value.lower() in ('true', 'false'):
                    return value.lower() == 'true'
                if not isinstance(value, bool):
                    raise Unverifiable('JSON boolean extraction requires a boolean or true/false text')
                return value
            text = model.number_text(value) if isinstance(value, Decimal) else ('true' if value is True else 'false' if value is False else value)
            if not text:
                return None  # Oracle VARCHAR2 empty-string semantics
            if len(text.encode('utf-8')) > 1000:
                raise Unverifiable('JSON text scalar exceeds 1000 UTF-8 bytes')
            return text
        if f == 'coalesce':
            return next((a for a in args if a is not None), None)
        if f == 'concat':
            return ''.join(a for a in args if a is not None) or None
        if any(a is None for a in args):
            return None
        a = args[0]
        try:
            if f in ('add', 'subtract', 'multiply', 'divide', 'modulo'):
                b = args[1]
                if f == 'divide':
                    if b == 0:
                        if d['zero'] == 'null':
                            return None
                        raise Predicted('arithmetic', 'division by zero', [1476])
                    return CONTEXT.divide(a, b)
                if f == 'modulo':
                    return a if b == 0 else CTX.remainder(a, b)
                return {'add': CONTEXT.add, 'subtract': CONTEXT.subtract, 'multiply': CONTEXT.multiply}[f](a, b)
            if f == 'negate':
                return CONTEXT.minus(a)
            if f == 'abs':
                return CONTEXT.abs(a)
            if f == 'floor':
                return a.to_integral_value(ROUND_FLOOR)
            if f == 'ceiling':
                return a.to_integral_value(ROUND_CEILING)
            if f in ('round', 'truncate'):
                return a.quantize(Decimal(1).scaleb(-d['digits']), rounding=ROUND_HALF_UP if f == 'round' else ROUND_DOWN, context=CTX)
        except (InvalidOperation, Overflow, DivisionByZero) as error:
            raise Predicted('arithmetic', 'NUMBER overflow or invalid operation: ' + type(error).__name__, [1426, 1476, 1438])
        if f in ('upper', 'lower'):
            if not a.isascii():
                raise Unverifiable(f'{f} of non-ASCII text depends on Oracle and Python case tables that differ')
            return (a.upper() if f == 'upper' else a.lower())
        if f == 'trim':
            return a.strip(' ') or None
        if f == 'substring':
            start, length = int(Decimal(args[1])), (int(Decimal(args[2])) if len(args) > 2 else None)
            return (a[start - 1:] if length is None else a[start - 1:start - 1 + length]) or None
        if f == 'length':
            return Decimal(len(a))
        if f == 'nullIf':
            return None if compare(a, args[1]) == 0 else a
        if f == 'addDays':
            days = args[1]
            if days != days.to_integral_value():
                raise Unverifiable('fractional days are not verified by the host reference')
            try:
                return a + timedelta(days=int(days))
            except OverflowError:
                raise Predicted('arithmetic', 'date out of range', [1841])
        if f == 'truncateDay':
            return a.replace(hour=0, minute=0, second=0, microsecond=0)
        return Decimal({'extractYear': a.year, 'extractMonth': a.month, 'extractDay': a.day}[f])


# --- relations ---------------------------------------------------------------------
def equal_keys(left_value, right_value):
    return left_value is not None and right_value is not None and left_value == right_value


def relation_rows(select, data):
    aliases = [select['from']['alias']]
    combos = [{select['from']['alias']: row} for row in data[select['from']['table']]]
    for join in select['joins']:
        alias, kind = join['alias'], join['type']
        right_rows = data[join['table']]
        matched_right, out = set(), []

        def keys_equal(combo, row):
            for k in join['on']:
                left_alias, left_column = k['left'].split('.')
                left_row = combo[left_alias]
                if not equal_keys(None if left_row is None else left_row[left_column], row[k['right'].split('.')[1]]):
                    return False
            return True
        for combo in combos:
            found = False
            for i, row in enumerate(right_rows):
                if keys_equal(combo, row):
                    out.append({**combo, alias: row})
                    matched_right.add(i)
                    found = True
            if not found and kind in ('left', 'full'):
                out.append({**combo, alias: None})
        if kind in ('right', 'full'):
            for i, row in enumerate(right_rows):
                if i not in matched_right:
                    out.append({**{a: None for a in aliases}, alias: row})
        aliases.append(alias)
        combos = out
    return combos


def run_select(select, data):
    evaluator = Evaluator(select['computed'], select['conditions'])
    conditions = {c['name']: c for c in select['conditions']}
    rows = []
    for combo in relation_rows(select, data):
        ctx = {'rows': combo}
        if select['where'] and evaluator.condition(conditions[select['where']], ctx) is not True:
            continue
        rows.append(ctx)
    if not select['grouped']:
        return [[evaluator.operand(c['operand'], ctx) for c in select['columns']] for ctx in rows]
    groups = {}
    for ctx in rows:
        values = tuple(evaluator.operand(k, ctx) for k in select['groupBy'])
        groups.setdefault(tuple(model_key(k['kind'], v) for k, v in zip(select['groupBy'], values)), (values, []))[1].append(ctx)
    if not select['groupBy'] and not groups:
        groups[()] = ((), [])
    result = []
    for values, members in groups.values():
        keys = {json.dumps({k: v for k, v in key.items() if k != 'kind'}, sort_keys=True): value for key, value in zip(select['groupBy'], values)}
        measures = {m['name']: measure(m, evaluator, members) for m in select['measures']}
        gctx = {'keys': keys, 'measures': measures, 'rows': {}}
        if select['having'] and evaluator.condition(conditions[select['having']], gctx) is not True:
            continue
        result.append([evaluator.operand(c['operand'], gctx) for c in select['columns']])
    return result


def model_key(kind, value):
    """Hashable identity under SQL equality: canonical text, or the instant for time-zone timestamps."""
    if value is None:
        return None
    if kind == 'timestampTz':
        return value.astimezone(timezone.utc).replace(tzinfo=None).isoformat()
    return canonical(kind, value)


def measure(m, evaluator, members):
    f = m['function']
    if f == 'countAll':
        return Decimal(len(members))
    values = [evaluator.operand(m['argument'], ctx) for ctx in members]
    values = [v for v in values if v is not None]
    if f == 'count':
        return Decimal(len(values))
    if f == 'countDistinct':
        return Decimal(len({model_key(m['argument']['kind'], v) for v in values}))
    if not values:
        return None
    if f in ('sum', 'average'):
        total = Decimal(0)
        for v in values:
            total = CONTEXT.add(total, v)
        return total if f == 'sum' else CONTEXT.divide(total, Decimal(len(values)))
    pick = min if f == 'minimum' else max
    return pick(values, key=lambda v: sort_key(m['kind'], v))


def row_key(kinds, row):
    return tuple(model_key(k, v) for k, v in zip(kinds, row))


def combine_rows(report, sets):
    kinds = [o['kind'] for o in report['outputs'][:len(report['selects'][0]['columns'])]]
    result = sets[0]
    for other in sets[1:]:
        if report['combine'] == 'unionAll':
            result = result + other
        elif report['combine'] == 'union':
            result = distinct(kinds, result + other)
        elif report['combine'] == 'intersect':
            wanted = {row_key(kinds, r) for r in other}
            result = distinct(kinds, [r for r in result if row_key(kinds, r) in wanted])
        else:
            removed = {row_key(kinds, r) for r in other}
            result = distinct(kinds, [r for r in result if row_key(kinds, r) not in removed])
    return result


def distinct(kinds, rows):
    seen, out = set(), []
    for r in rows:
        key = row_key(kinds, r)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def order_rows(rows, terms, kinds_by_index):
    """Stable multi-key ordering with explicit NULL placement."""
    for term in reversed(terms):
        index, descending = term['index'], term['direction'] == 'descending'
        null_rank = 1 if (term['nulls'] == 'last') != descending else 0
        kind = kinds_by_index[index]
        rows.sort(key=lambda r: (null_rank, sort_key(kind, r[index])) if r[index] is None else (1 - null_rank, sort_key(kind, r[index])), reverse=descending)
    return rows


def run_windows(report, rows, kinds):
    names = [o['name'] for o in report['outputs']][:len(kinds)]
    for window in report['windows']:
        order = [{**t, 'index': names.index(t['column'])} for t in window['orderBy']]
        part = [names.index(p) for p in window['partitionBy']]
        argument = names.index(window['argument']) if window['argument'] else None
        partitions = {}
        for position, row in enumerate(rows):
            partitions.setdefault(tuple(model_key(kinds[i], row[i]) for i in part), []).append(position)
        values = [None] * len(rows)
        for positions in partitions.values():
            ordered = order_rows([[*rows[p], p] for p in positions], [{**o, 'index': o['index']} for o in order], kinds)
            keys = [tuple(model_key(kinds[o['index']], r[o['index']]) for o in order) for r in ordered]
            rank = dense = 0
            running, count = None, 0
            for i, r in enumerate(ordered):
                tie = i > 0 and keys[i] == keys[i - 1]
                if not tie:
                    rank, dense = i + 1, dense + 1
                if window['function'] in ('rowNumber', 'runningSum', 'runningCount') and (tie or (i + 1 < len(keys) and keys[i + 1] == keys[i])):
                    raise Ambiguous(f'window {window["name"]} orders tied rows; add an orderBy key that makes the order total')
                if window['function'] == 'rowNumber':
                    out = Decimal(i + 1)
                elif window['function'] == 'rank':
                    out = Decimal(rank)
                elif window['function'] == 'denseRank':
                    out = Decimal(dense)
                else:
                    cell = r[argument] if argument is not None else True
                    if cell is not None:
                        running = cell if running is None else CONTEXT.add(running, cell) if window['function'] == 'runningSum' else running
                        count += 1
                    out = running if window['function'] == 'runningSum' else Decimal(count)
                values[r[-1]] = out
        rows = [[*row, v] for row, v in zip(rows, values)]
        kinds = kinds + ['number']
        names.append(window['name'])
    return rows, kinds


def run_report(report, data):
    kinds = [o['kind'] for o in report['outputs']]
    base = len(report['selects'][0]['columns'])
    rows = combine_rows(report, [run_select(s, data) for s in report['selects']])
    rows, kinds = run_windows(report, [list(r) for r in rows], kinds[:base])
    if report['distinct']:
        rows = distinct(kinds, rows)
    names = [o['name'] for o in report['outputs']]
    rows.sort(key=lambda r: tuple(sort_key(k, v) for k, v in zip(kinds, r)))
    terms = [{**t, 'index': names.index(t['column'])} for t in report['orderBy']]
    order_rows(rows, terms, kinds)
    if report['limit'] or report['offset']:
        start = report['offset']
        stop = start + (report['limit'] or len(rows))
        keys = [tuple(model_key(kinds[t['index']], r[t['index']]) for t in terms) for r in rows]
        for edge in (start, stop):
            if 0 < edge < len(rows) and keys[edge - 1] == keys[edge]:
                raise Ambiguous('rows tied on the orderBy keys straddle the limit/offset boundary; add a key that makes the order total')
        rows = rows[start:stop]
    if len(rows) > model.MAX_RESULT_ROWS:
        raise Predicted('size', f'the result exceeds {model.MAX_RESULT_ROWS} rows', [])
    return rows, kinds


def inexact(report):
    """True when any NUMBER output is computed (division, average, sum, derived arithmetic): Oracle computes with more
    digits than the 38 it stores, so computed results are compared at TOLERANCE_DIGITS; bare stored columns stay exact."""
    for select in report['selects']:
        if any(d['function'] in ('divide', 'multiply', 'add', 'subtract', 'modulo', 'round', 'truncate') for d in select['computed']):
            return True
        if any(m['function'] in ('sum', 'average') for m in select['measures']):
            return True
    return any(w['function'] == 'runningSum' for w in report['windows'])


def numbers_match(a, b, tolerant):
    if a == b:
        return True
    if a is None or b is None:
        return False
    if not tolerant:
        return False
    difference = CTX.subtract(a, b).copy_abs()
    bound = CTX.multiply(max(a.copy_abs(), b.copy_abs()), Decimal(1).scaleb(-TOLERANCE_DIGITS, context=CTX))
    return difference <= bound


def check_native_order(report, rows, kinds):
    """The sequence Oracle returned must already follow the declared orderBy (including NULL placement) before ties
    are settled; a generator or engine ordering defect must not be hidden by re-sorting both sides."""
    names = [o['name'] for o in report['outputs']]
    terms = [{**t, 'index': names.index(t['column'])} for t in report['orderBy']]
    for position in range(1, len(rows)):
        before, after = rows[position - 1], rows[position]
        for term in terms:
            x, y = before[term['index']], after[term['index']]
            if x is None and y is None:
                continue
            if (x is None) != (y is None):
                if (x is None) == (term['nulls'] == 'first'):
                    break
                return f'rows {position - 1} and {position} are out of order: NULL belongs {term["nulls"]} for {term["column"]}'
            kind = kinds[term['index']]
            low, high = sort_key(kind, x)[:2], sort_key(kind, y)[:2]
            if low == high:
                continue
            if (low < high) == (term['direction'] == 'ascending'):
                break
            return f'rows {position - 1} and {position} are out of order for {term["column"]} ({term["direction"]})'
    return None


def settle_rows(report, rows, kinds):
    """Deterministic published order: the declared orderBy, then every column (tolerance-stable for inexact numbers)."""
    tolerant = inexact(report)
    names = [o['name'] for o in report['outputs']]
    terms = [{**t, 'index': names.index(t['column'])} for t in report['orderBy']]
    rows = sorted((list(r) for r in rows), key=lambda r: tuple(sort_key(k, round_key(k, v, tolerant)) for k, v in zip(kinds, r)))
    return order_rows(rows, terms, kinds)


def compare_result(report, native_rows, expected_rows, kinds):
    """Pairwise comparison in canonical order; divisions and averages use the declared digit tolerance."""
    tolerant = inexact(report)
    if len(native_rows) != len(expected_rows):
        return f'native returned {len(native_rows)} rows; the reference computed {len(expected_rows)}'
    names = [o['name'] for o in report['outputs']]
    for i, (n, e) in enumerate(zip(settle_rows(report, native_rows, kinds), settle_rows(report, expected_rows, kinds))):
        for kind, name, a, b in zip(kinds, names, n, e):
            same = numbers_match(a, b, tolerant) if kind == 'number' else (a == b and (kind != 'timestampTz' or a is None or a.utcoffset() == b.utcoffset()))
            if not same or type(a) is not type(b):
                return f'row {i} column {name}: native {canonical(kind, a)!r} differs from the reference {canonical(kind, b)!r}'
    return None


def round_key(kind, value, tolerant):
    if tolerant and kind == 'number' and value is not None:
        return Decimal(format(value, '.28e'))
    return value


# --- constraints and mutation --------------------------------------------------------
def violations(tables, data):
    """First constraint violation in a deterministic table/constraint order, or None."""
    by_name = {t['name']: t for t in tables}
    for table in tables:
        rows = data[table['name']]
        for row in rows:
            for column in table['columns']:
                if row[column['name']] is None and (not column['nullable'] or column['name'] in table['primaryKey']):
                    return ('notNull', table['name'], column['name'], [1400, 1407])
        for key, label in [(table['primaryKey'], 'primary')] + [(u, 'unique') for u in table['unique']]:
            seen = set()
            for row in rows:
                values = [row[k] for k in key]
                if label == 'unique' and all(v is None for v in values):
                    continue
                token = tuple(None if v is None else model_key(next(c['type'] for c in table['columns'] if c['name'] == k), v) for k, v in zip(key, values))
                if token in seen:
                    return (label, table['name'], ','.join(key), [1])
                seen.add(token)
        evaluator = Evaluator((), table['checks'])
        for check in table['checks']:
            for row in rows:
                if evaluator.condition(check, {'rows': {table['name']: row}}) is False:
                    return ('check', table['name'], check['name'], [2290])
        for fk in table['foreignKeys']:
            parent = by_name.get(fk['table'])
            if parent is None or parent['name'] not in data:
                continue
            kinds = [next(c['type'] for c in parent['columns'] if c['name'] == r) for r in fk['references']]
            present = {tuple(model_key(k, r[ref]) for k, ref in zip(kinds, fk['references'])) for r in data[parent['name']]}
            for row in rows:
                values = [row[c] for c in fk['columns']]
                if any(v is None for v in values):
                    continue
                if tuple(model_key(k, v) for k, v in zip(kinds, values)) not in present:
                    return ('foreignKey', table['name'], ','.join(fk['columns']), [2291, 2292])
    return None


def apply_cascades(tables, data, removed):
    """Apply ON DELETE CASCADE / SET NULL for parent rows just removed, repeatedly."""
    by_name = {t['name']: t for t in tables}
    queue = list(removed)
    while queue:
        parent_name, row = queue.pop()
        for table in tables:
            for fk in table['foreignKeys']:
                if fk['table'] != parent_name or fk['onDelete'] == 'noAction':
                    continue
                parent = by_name[parent_name]
                kinds = [next(c['type'] for c in parent['columns'] if c['name'] == r) for r in fk['references']]
                token = tuple(model_key(k, row[r]) for k, r in zip(kinds, fk['references']))
                still = {tuple(model_key(k, r[ref]) for k, ref in zip(kinds, fk['references'])) for r in data[parent_name]}
                if token in still:
                    continue
                for child in list(data[table['name']]):
                    if tuple(None if child[c] is None else model_key(k, child[c]) for k, c in zip(kinds, fk['columns'])) == token:
                        if fk['onDelete'] == 'cascade':
                            data[table['name']] = [r for r in data[table['name']] if r is not child]
                            queue.append((table['name'], child))
                        else:
                            for c in fk['columns']:
                                child[c] = None


def matching(table, step, rows):
    if not step.get('where'):
        return list(rows)
    evaluator = Evaluator(step['computed'], step['conditions'])
    conditions = {c['name']: c for c in step['conditions']}
    return [r for r in rows if evaluator.condition(conditions[step['where']], {'rows': {table['name']: r}}) is True]


def expectation(step, observed, index):
    if 'expectRows' in step and step['expectRows'] != observed:
        raise Predicted('rowcount', f'step {index} affected {observed} rows; expectRows is {step["expectRows"]}', [], step=index, observed=observed)


def simulate(plan, data):
    """Apply the transaction to a deep copy; return per-step results and the final state, or raise Predicted."""
    tables = plan['tables']
    by_name = {t['name']: t for t in tables}
    state = copy.deepcopy(data)
    savepoints, results = {}, []
    for index, step in enumerate(plan['transaction']['steps']):
        kind = step['kind']
        if kind == 'savepoint':
            savepoints[step['name']] = copy.deepcopy(state)
            results.append({'kind': kind})
            continue
        if kind == 'rollbackTo':
            state = copy.deepcopy(savepoints[step['name']])
            results.append({'kind': kind})
            continue
        table = by_name[step['table']]
        rows = state[table['name']]
        if kind in ('insert', 'merge'):
            inserted = updated = 0
            for cells in step['rows']:
                row = typed_row(table, step['columns'], cells)
                if kind == 'insert':
                    rows.append(row)
                    inserted += 1
                else:
                    key = tuple(model_key(next(c['type'] for c in table['columns'] if c['name'] == k), row[k]) for k in step['keys'])
                    hit = next((r for r in rows if tuple(model_key(next(c['type'] for c in table['columns'] if c['name'] == k), r[k]) for k in step['keys']) == key), None)
                    if hit is not None and step['onMatched'] == 'update':
                        for c in step['columns']:
                            if c not in step['keys']:
                                hit[c] = row[c]
                        updated += 1
                    elif hit is None and step['onNotMatched'] == 'insert':
                        rows.append(row)
                        inserted += 1
                found = violations(tables, state)
                if found:
                    raise Predicted('constraint', f'step {index} violates {found[0]} on {found[1]} ({found[2]})', found[3], step=index, constraint=found[0], table=found[1])
            expectation(step, inserted + updated, index)
            results.append({'kind': kind, 'rows': inserted + updated, 'inserted': inserted, 'updated': updated})
            continue
        hit = matching(table, step, rows)
        if kind == 'check':
            expectation(step, len(hit), index)
            results.append({'kind': kind, 'rows': len(hit)})
            continue
        if kind == 'update':
            evaluator = Evaluator(step['computed'], step['conditions'])
            values = [{a['column']: evaluator.operand(a['value'], {'rows': {table['name']: r}}) for a in step['set']} for r in hit]
            by_column = {c['name']: c for c in table['columns']}
            for row, new in zip(hit, values):
                stored = {}
                for name, value in new.items():
                    try:
                        stored[name] = model.store_value(by_column[name], value)
                    except ValueFault as error:
                        raise Predicted('value', f'step {index} assigns a value that column {name} cannot store: {error}',
                                        {'precision': [1438], 'length': [12899]}.get(error.reason, []), step=index, column=name, reason=error.reason)
                row.update(stored)
        else:
            removed = [(table['name'], r) for r in hit]
            ids = {id(r) for r in hit}
            state[table['name']] = [r for r in rows if id(r) not in ids]
            apply_cascades(tables, state, removed)
        found = violations(tables, state)
        if found:
            raise Predicted('constraint', f'step {index} violates {found[0]} on {found[1]} ({found[2]})', found[3], step=index, constraint=found[0], table=found[1])
        expectation(step, len(hit), index)
        results.append({'kind': kind, 'rows': len(hit)})
    return results, state


# --- dictionary expectations -------------------------------------------------------------
def declared_catalog(table):
    names = sql.constraint_names(table)
    return {'name': table['name'], 'columns': [{k: c[k] for k in ('name', 'type', 'precision', 'scale', 'length', 'fraction')} | {'nullable': c['nullable'] and c['name'] not in table['primaryKey']} for c in table['columns']],
            'primaryKey': list(table['primaryKey']), 'unique': sorted(sorted(u) for u in table['unique']),
            'foreignKeys': sorted([{'columns': list(f['columns']), 'table': f['table'], 'references': list(f['references']), 'onDelete': f['onDelete']} for f in table['foreignKeys']], key=json.dumps),
            'checks': sorted(names['check'])}


def dictionary_name(value):
    return value.lower() if re.fullmatch(r'[A-Z][A-Z0-9_]*', value or '') else value


def snapshot(raw, schema, kinds=model.KINDS):
    """Canonical metadata snapshot from the fixed dictionary query results (rows are lists keyed by query columns)."""
    def rows(name):
        data = raw.get(name, {'columns': [], 'rows': []})
        return [dict(zip([c.lower() for c in data['columns']], r)) for r in data['rows']]
    comments = {r['table_name']: r['comments'] for r in rows('tables')}
    columns, constraints = {}, {}
    for r in rows('columns'):
        columns.setdefault(r['table_name'], []).append(r)
    for r in rows('constraints'):
        constraints.setdefault(r['table_name'], {}).setdefault(r['constraint_name'], {'type': r['constraint_type'], 'rule': r['delete_rule'], 'parent': r['parent_table'], 'columns': [], 'parents': []})
        if r['column_name'] is not None:
            constraints[r['table_name']][r['constraint_name']]['columns'].append(dictionary_name(r['column_name']))
        if r['parent_column'] is not None:
            constraints[r['table_name']][r['constraint_name']]['parents'].append(dictionary_name(r['parent_column']))
    views = {r['view_name'] for r in rows('views')}
    result = {'schema': dictionary_name(schema), 'tables': [], 'views': [], 'sequences': [], 'indexes': []}
    for name in sorted(comments):
        cols = [column_description(c) for c in columns.get(name, [])]
        info = constraints.get(name, {})
        result['tables'].append({
            'name': dictionary_name(name), 'managed': (comments[name] or '').startswith(sql.MARKER_PREFIX), 'owner': (comments[name] or '')[len(sql.MARKER_PREFIX):] if (comments[name] or '').startswith(sql.MARKER_PREFIX) else None, 'columns': cols,
            'primaryKey': next((c['columns'] for c in info.values() if c['type'] == 'P'), []),
            'unique': sorted(sorted(c['columns']) for c in info.values() if c['type'] == 'U'),
            'foreignKeys': sorted([{'columns': c['columns'], 'table': dictionary_name(c['parent']), 'references': c['parents'],
                                    'onDelete': {'CASCADE': 'cascade', 'SET NULL': 'setNull'}.get(c['rule'], 'noAction')} for c in info.values() if c['type'] == 'R'], key=json.dumps),
            'checks': sorted(dictionary_name(n) for n, c in info.items() if c['type'] == 'C')})
    if 'views' in kinds:
        result['views'] = [{'name': dictionary_name(v), 'columns': [column_description(c)['name'] for c in columns.get(v, [])]} for v in sorted(views)]
    if 'sequences' in kinds:
        result['sequences'] = [{'name': dictionary_name(r['sequence_name']), 'minimum': str(r['min_value']), 'maximum': str(r['max_value']), 'increment': str(r['increment_by']),
                                'cycle': r['cycle_flag'] == 'Y', 'ordered': r['order_flag'] == 'Y', 'cache': str(r['cache_size'])} for r in rows('sequences')]
    if 'indexes' in kinds:
        grouped = {}
        for r in rows('indexes'):
            grouped.setdefault((r['table_name'], r['index_name']), {'unique': r['uniqueness'] == 'UNIQUE', 'columns': []})['columns'].append(dictionary_name(r['column_name']))
        result['indexes'] = [{'name': dictionary_name(n), 'table': dictionary_name(t), **v} for (t, n), v in sorted(grouped.items())]
    if 'tables' not in kinds:
        result['tables'] = []
    return result


def column_description(c):
    kind = c['data_type']
    base = {'name': dictionary_name(c['column_name']), 'type': None, 'precision': None, 'scale': None, 'length': None, 'fraction': None, 'nullable': c['nullable'] == 'Y'}
    if kind == 'NUMBER':
        base.update(type='number', precision=None if c['data_precision'] is None else int(c['data_precision']), scale=None if c['data_precision'] is None or c['data_scale'] is None else int(c['data_scale']))
    elif kind == 'VARCHAR2':
        # BYTE-semantics columns count bytes, not characters: report them as a different type so drift names the difference.
        base.update(type='varchar2' if c.get('char_used') == 'C' else 'varchar2Byte', length=int(c['char_length']))
    elif kind in ('CLOB', 'BLOB', 'JSON'):
        base['type'] = kind.lower()
    elif kind == 'DATE':
        base['type'] = 'date'
    elif kind == 'RAW':
        base.update(type='raw', length=int(c['data_length']))
    elif kind == 'BOOLEAN':
        base['type'] = 'boolean'
    elif kind.startswith('TIMESTAMP'):
        digits = kind[kind.index('(') + 1:kind.index(')')]
        base.update(type='timestampTz' if 'WITH TIME ZONE' in kind and 'LOCAL' not in kind else 'timestamp', fraction=int(digits))
        if 'LOCAL' in kind:
            base['type'] = 'timestampLocal'
    else:
        base['type'] = kind
    return base


def relabel(snapshot, inverse):
    """The snapshot with run-unique physical table names replaced by the declared (logical) names."""
    if not inverse:
        return snapshot
    result = copy.deepcopy(snapshot)
    rename = lambda name: inverse.get(name, name)
    for table in result['tables']:
        table['name'] = rename(table['name'])
        for key in table['foreignKeys']:
            key['table'] = rename(key['table'])
        table['foreignKeys'].sort(key=json.dumps)
    result['tables'].sort(key=lambda t: t['name'])
    for index in result['indexes']:
        index['table'] = rename(index['table'])
    return result


def drift(tables, observed):
    """Differences between declared tables and an observed snapshot; each difference names its object and attribute."""
    found, by_name = [], {t['name']: t for t in observed['tables']}
    for table in tables:
        want = declared_catalog(table)
        have = by_name.get(table['name'])
        if have is None:
            found.append({'table': table['name'], 'difference': 'missing', 'declared': True})
            continue
        if table.get('external'):
            # A read-only use of an existing table needs only the columns and keys it relies on, not the whole definition.
            actual = {c['name']: c for c in have['columns']}
            missing = [c for c in want['columns'] if actual.get(c['name']) != c]
            if missing:
                found.append({'table': table['name'], 'difference': 'columns', 'declared': missing, 'observed': [actual.get(c['name']) for c in missing]})
            if have['primaryKey'] != want['primaryKey']:
                found.append({'table': table['name'], 'difference': 'primaryKey', 'declared': want['primaryKey'], 'observed': have['primaryKey']})
            for key in ('unique', 'foreignKeys'):
                absent = [w for w in want[key] if w not in have[key]]
                if absent:
                    found.append({'table': table['name'], 'difference': key, 'declared': absent, 'observed': have[key]})
            continue
        if have['columns'] != want['columns']:
            found.append({'table': table['name'], 'difference': 'columns', 'declared': want['columns'], 'observed': have['columns']})
        for key in ('primaryKey', 'unique', 'foreignKeys'):
            if have[key] != want[key]:
                found.append({'table': table['name'], 'difference': key, 'declared': want[key], 'observed': have[key]})
        if len(have['checks']) != len(want['checks']):
            found.append({'table': table['name'], 'difference': 'checks', 'declared': len(want['checks']), 'observed': len(have['checks'])})
    return found
