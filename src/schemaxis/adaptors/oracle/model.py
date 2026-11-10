"""Typed Oracle domain records, declaration grammar, value codec and semantic planning.

This module is host-safe: it never imports the Oracle driver and never reads a
credential. Authored documents describe intent (tables, relations, predicates,
measures, mutations, transactions); trusted SQL is generated elsewhere.
"""
import copy
import json
from decimal import Context, Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime, timedelta, timezone
import re

from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import Fault, SchemaxisError

VERSION = 'schemaxis.oracle/1'
PLAN_VERSION = 'schemaxis.oracle.plan/1'
OPERATIONS = ('inspect', 'load', 'report', 'mutate')
TYPES = ('number', 'varchar2', 'date', 'timestamp', 'timestampTz', 'raw', 'boolean', 'clob', 'blob', 'json')
KEY_TYPES = ('number', 'varchar2', 'date', 'timestamp', 'timestampTz', 'raw')
ORDERED = ('number', 'varchar2', 'date', 'timestamp', 'timestampTz')
LARGE_TYPES = ('clob', 'blob', 'json')
LARGE_LIMIT = 262144
NO_EQUALITY_GROUPING = ('timestampTz', *LARGE_TYPES)
ENV_PREFIX = 'SCHEMAXIS_ORACLE_'
MAX_ROWS = 5000
MAX_RESULT_ROWS = 10000
CTX = Context(prec=80)
NUMBER_DIGITS = 38
RESULT_DIGITS = 40
NATIVE_MASKS ={'date': 'YYYY-MM-DD"T"HH24:MI:SS', 'timestamp': 'YYYY-MM-DD"T"HH24:MI:SS.FF6',
                'timestampTz': 'YYYY-MM-DD"T"HH24:MI:SS.FF6TZH:TZM'}
IDENTIFIER = re.compile(r'[a-z][a-z0-9_]{0,23}')
PROFILE = re.compile(r'[a-z][a-z0-9_]{0,31}')
ENV_NAME = re.compile(ENV_PREFIX + r'[A-Z0-9_]{1,60}')
REFERENCE = re.compile(r'([a-z][a-z0-9_]{0,23})\.([a-z][a-z0-9_]{0,23})')
RESERVED_NAMES = frozenset({'dual', 'null', 'sys', 'system', 'rowid', 'rownum', 'sysdate', 'systimestamp', 'user'})


def problem(code, message, location='$', recovery=None, **observed):
    raise SchemaxisError(Fault(code, message, location, 'pipeline', observed=observed, recovery=recovery))


# ---------------------------------------------------------------------------
# Declaration grammar. Shared records are hoisted into ``$defs`` of the schema.
# ---------------------------------------------------------------------------
NAMES = {}


def record(name, properties):
    NAMES[id(properties)] = name
    return {'type': 'object', 'properties': properties}


def required(spec):
    return {**spec, 'required': True}


def text(low, high):
    return {'type': 'string', 'minLength': low, 'maxLength': high}


def listing(items, low=0, high=64, **extra):
    return {'type': 'array', 'items': items, 'minItems': low, 'maxItems': high, **extra}


def choice(*values, **extra):
    return {'type': 'enum', 'values': list(values), **extra}


IDENT = text(1, 24)
REF = text(3, 49)
ENV = text(len(ENV_PREFIX) + 1, 80)
CELL = {'type': 'union', 'options': [
    {'type': 'enum', 'values': [None]}, {'type': 'boolean'},
    {'type': 'integer', 'minimum': -10 ** 38, 'maximum': 10 ** 38}, {'type': 'string', 'maxLength': 524288}]}
FUNCTIONS = ('add', 'subtract', 'multiply', 'divide', 'modulo', 'negate', 'abs', 'floor', 'ceiling', 'round', 'truncate',
             'upper', 'lower', 'trim', 'concat', 'substring', 'length', 'coalesce', 'nullIf', 'conditional',
             'addDays', 'truncateDay', 'extractYear', 'extractMonth', 'extractDay', 'jsonNumber', 'jsonText', 'jsonBoolean')
OPERATORS = ('equals', 'notEquals', 'lessThan', 'lessOrEqual', 'greaterThan', 'greaterOrEqual', 'between', 'in',
             'isNull', 'startsWith', 'contains')
MEASURES = ('count', 'countAll', 'countDistinct', 'sum', 'average', 'minimum', 'maximum')
WINDOWS = ('rowNumber', 'rank', 'denseRank', 'runningSum', 'runningCount')
STEPS = ('insert', 'update', 'delete', 'merge', 'savepoint', 'rollbackTo', 'check')

LITERAL = record('literal', {'type': required(choice(*TYPES)), 'value': required(CELL)})
OPERAND = record('operand', {'column': REF, 'literal': LITERAL, 'derived': IDENT, 'measure': IDENT})
TERM = record('term', {'left': OPERAND, 'operator': choice(*OPERATORS), 'right': OPERAND, 'upper': OPERAND,
                       'values': listing(OPERAND, 1, 16), 'negate': {'type': 'boolean', 'default': False}, 'condition': IDENT})
CONDITION = record('condition', {'name': required(IDENT), 'combine': choice('and', 'or', default='and'),
                                 'terms': required(listing(TERM, 1, 16)), 'negate': {'type': 'boolean', 'default': False}})
DERIVED = record('derived', {'name': required(IDENT), 'function': required(choice(*FUNCTIONS)),
                             'arguments': required(listing(OPERAND, 1, 4)), 'digits': {'type': 'integer', 'minimum': -30, 'maximum': 30, 'default': 0},
                             'zero': choice('error', 'null', default='error'), 'when': CONDITION, 'path': text(1, 256)})
COLUMN = record('column', {'name': required(IDENT), 'type': required(choice(*TYPES)),
                           'precision': {'type': 'integer', 'minimum': 1, 'maximum': 38}, 'scale': {'type': 'integer', 'minimum': 0, 'maximum': 38},
                           'length': {'type': 'integer', 'minimum': 1, 'maximum': 2000}, 'fraction': {'type': 'integer', 'minimum': 0, 'maximum': 6},
                           'nullable': {'type': 'boolean', 'default': False}, 'emptyText': choice('reject', 'null', default='reject'),
                           'scalePolicy': choice('reject', 'round', default='reject')})
UNIQUE = record('unique', {'columns': required(listing(IDENT, 1, 8, uniqueItems=True))})
FOREIGN = record('foreignKey', {'columns': required(listing(IDENT, 1, 8, uniqueItems=True)), 'table': required(IDENT),
                                'references': required(listing(IDENT, 1, 8, uniqueItems=True)),
                                'onDelete': choice('noAction', 'cascade', 'setNull', default='noAction')})
SOURCE = record('source', {'path': required(text(1, 4096)), 'format': choice('json', 'csv', default='json')})
TABLE = record('table', {'name': required(IDENT), 'external': {'type': 'boolean', 'default': False},
                         'columns': required(listing(COLUMN, 1, 32)), 'primaryKey': required(listing(IDENT, 1, 8, uniqueItems=True)),
                         'unique': {**listing(UNIQUE, 0, 8), 'default': []}, 'foreignKeys': {**listing(FOREIGN, 0, 8), 'default': []},
                         'checks': {**listing(CONDITION, 0, 8), 'default': []}, 'source': SOURCE})
CONNECTION = record('connection', {'profile': required(text(1, 32)), 'userVariable': ENV, 'passwordVariable': ENV, 'dsnVariable': ENV,
                                   'connectTimeoutSeconds': {'type': 'integer', 'minimum': 1, 'maximum': 120, 'default': 20},
                                   'callTimeoutSeconds': {'type': 'integer', 'minimum': 1, 'maximum': 900, 'default': 60}})
SETUP = record('setup', {'retain': {'type': 'boolean'}})
KINDS = ('tables', 'views', 'sequences', 'indexes')
INSPECTION = record('inspection', {'kinds': {**listing(choice(*KINDS), 1, 4, uniqueItems=True), 'default': list(KINDS)},
                                   'names': {**listing(IDENT, 0, 64, uniqueItems=True), 'default': []}, 'drift': choice('report', 'fail', default='fail')})
TABLEREF = record('tableReference', {'table': required(IDENT), 'alias': IDENT})
JOINKEY = record('joinKey', {'left': required(REF), 'right': required(REF)})
JOIN = record('join', {'type': choice('inner', 'left', 'right', 'full', default='inner'), 'table': required(IDENT), 'alias': IDENT,
                       'on': required(listing(JOINKEY, 1, 4))})
MEASURE = record('measure', {'name': required(IDENT), 'function': required(choice(*MEASURES)), 'argument': OPERAND})
OUTPUT = record('output', {'name': required(IDENT), 'operand': required(OPERAND)})
SELECT = record('select', {'from': required(TABLEREF), 'joins': {**listing(JOIN, 0, 6), 'default': []},
                           'computed': {**listing(DERIVED, 0, 16), 'default': []}, 'conditions': {**listing(CONDITION, 0, 16), 'default': []},
                           'where': IDENT, 'groupBy': {**listing(OPERAND, 0, 6), 'default': []}, 'measures': {**listing(MEASURE, 0, 8), 'default': []},
                           'having': IDENT, 'columns': required(listing(OUTPUT, 1, 16))})
ORDERTERM = record('orderTerm', {'column': required(IDENT), 'direction': choice('ascending', 'descending', default='ascending'),
                                 'nulls': choice('first', 'last', default='last')})
WINDOW = record('window', {'name': required(IDENT), 'function': required(choice(*WINDOWS)), 'argument': IDENT,
                           'partitionBy': {**listing(IDENT, 0, 4), 'default': []}, 'orderBy': {**listing(ORDERTERM, 0, 4), 'default': []}})
REPORT = record('report', {'selects': required(listing(SELECT, 1, 4)), 'combine': choice('unionAll', 'union', 'intersect', 'except', default='unionAll'),
                           'windows': {**listing(WINDOW, 0, 4), 'default': []}, 'distinct': {'type': 'boolean', 'default': False},
                           'orderBy': {**listing(ORDERTERM, 0, 6), 'default': []}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': MAX_RESULT_ROWS},
                           'offset': {'type': 'integer', 'minimum': 0, 'maximum': 1000000}, 'numbers': choice('decimalString', 'jsonNumber', default='decimalString')})
ASSIGNMENT = record('assignment', {'column': required(IDENT), 'value': required(OPERAND)})
STEP = record('step', {'kind': required(choice(*STEPS)), 'table': IDENT, 'name': IDENT, 'columns': listing(IDENT, 1, 32, uniqueItems=True),
                       'rows': listing(listing(CELL, 1, 32), 1, 1000), 'set': listing(ASSIGNMENT, 1, 16),
                       'computed': {**listing(DERIVED, 0, 8), 'default': []}, 'conditions': {**listing(CONDITION, 0, 8), 'default': []},
                       'where': IDENT, 'keys': listing(IDENT, 1, 8, uniqueItems=True), 'onMatched': choice('update', 'ignore', default='update'),
                       'onNotMatched': choice('insert', 'ignore', default='insert'), 'expectRows': {'type': 'integer', 'minimum': 0, 'maximum': 1000000}})
IDEMPOTENCY = record('idempotency', {'table': required(IDENT), 'key': required(text(1, 64)), 'keyColumn': {**IDENT, 'default': 'idempotency_key'},
                                     'digestColumn': {**IDENT, 'default': 'plan_digest'}})
TRANSACTION = record('transaction', {'steps': required(listing(STEP, 1, 64)), 'finish': choice('commit', 'rollback', default='commit'),
                                     'isolation': choice('readCommitted', 'serializable', default='readCommitted'),
                                     'enforcement': choice('predict', 'database', default='predict'), 'idempotency': IDEMPOTENCY})
TABLES = listing(TABLE, 1, 8)
OPTIONS = {'connection': required(CONNECTION), 'tables': TABLES, 'setup': SETUP, 'inspection': INSPECTION, 'report': REPORT, 'transaction': TRANSACTION}
OPERATION_OPTIONS = {'inspect': ('connection', 'tables', 'inspection'), 'load': ('connection', 'tables', 'setup'),
                     'report': ('connection', 'tables', 'setup', 'report'), 'mutate': ('connection', 'tables', 'setup', 'transaction')}
NATIVE = {'inspect': 'USER_TABLES/USER_TAB_COLS/USER_CONSTRAINTS/USER_IND_COLUMNS/USER_VIEWS/USER_SEQUENCES queries',
          'load': 'CREATE TABLE; COMMENT; INSERT executemany; COMMIT; fresh-connection SELECT',
          'report': 'SELECT JOIN/WHERE/GROUP BY/HAVING/UNION/analytic functions/ORDER BY/FETCH',
          'mutate': 'INSERT/UPDATE/DELETE/MERGE; SAVEPOINT; ROLLBACK TO; COMMIT/ROLLBACK; observer connection'}
DECLARATIONS = {op: {'native': NATIVE[op], 'kinds': ['text'] if op == 'inspect' else ['table', 'text'], 'inputs': {},
                     'options': {k: {'value': OPTIONS[k]} for k in names}} for op, names in OPERATION_OPTIONS.items()}


def _decorate(result, spec):
    for key in ('default', 'title'):
        if key in spec:
            result[key] = spec[key]
    if 'summary' in spec:
        result['description'] = spec['summary']
    return result


def to_schema(spec, defs):
    """Project the grammar to JSON Schema, hoisting every named record into ``defs`` once."""
    kind = spec['type']
    if kind == 'object':
        properties = spec['properties']
        name = NAMES.get(id(properties))
        if name is not None:
            if name not in defs:
                defs[name] = None
                defs[name] = _object(spec, defs)
            return _decorate({'$ref': '#/$defs/' + name}, spec)
        return _decorate(_object(spec, defs), spec)
    if kind == 'union':
        return _decorate({'anyOf': [to_schema(option, defs) for option in spec['options']]}, spec)
    if kind == 'enum':
        return _decorate({'enum': list(spec['values'])}, spec)
    result = {'type': kind}
    if kind == 'array':
        result['items'] = to_schema(spec['items'], defs)
    for key in ('minLength', 'maxLength', 'minItems', 'maxItems', 'uniqueItems'):
        if key in spec:
            result[key] = spec[key]
    for bound in ('minimum', 'maximum'):
        if bound in spec:
            result['exclusive' + bound.title() if spec.get('exclusive' + bound.title()) else bound] = spec[bound]
    return _decorate(result, spec)


def _object(spec, defs):
    properties = {k: to_schema(v, defs) for k, v in spec['properties'].items()}
    result = {'type': 'object', 'properties': properties, 'additionalProperties': False}
    needed = [k for k, v in spec['properties'].items() if v.get('required')]
    if needed:
        result['required'] = needed
    return result


def document_schema():
    from schemaxis.schema import DRAFT
    defs = {}
    properties = {'version': {'const': VERSION}, 'operation': {'enum': list(OPERATIONS)}}
    properties.update({k: to_schema(v, defs) for k, v in OPTIONS.items()})
    return {'$schema': DRAFT, '$defs': defs, 'type': 'object', 'properties': properties, 'additionalProperties': False,
            'required': ['version', 'operation', 'connection']}


# ---------------------------------------------------------------------------
# Value codec. Host and native worker use independent implementations.
# ---------------------------------------------------------------------------
class ValueFault(ValueError):
    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


DECIMAL = re.compile(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?')
STAMP = re.compile(r'(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?)?(Z|[+-]\d{2}:\d{2})?')
LITERAL_COLUMN = {'name': 'literal', 'precision': None, 'scale': None, 'length': 1000, 'fraction': 6, 'nullable': True,
                  'emptyText': 'reject', 'scalePolicy': 'reject'}


def parse_decimal(raw, column):
    if isinstance(raw, bool):
        raise ValueFault('type', 'a NUMBER cell must be an integer or exact decimal text, not a boolean')
    if isinstance(raw, int):
        value = Decimal(raw)
    elif isinstance(raw, Decimal):
        value = raw
    elif isinstance(raw, str) and DECIMAL.fullmatch(raw):
        try:
            value = Decimal(raw)
        except InvalidOperation:
            raise ValueFault('number', 'not a decimal number')
    else:
        raise ValueFault('type', 'a NUMBER cell must be an integer or exact decimal text; floats lose exactness')
    if not value.is_finite():
        raise ValueFault('number', 'NUMBER values must be finite')
    # Every operation below passes the controlled context CTX (or is exact), so the caller's
    # ambient decimal precision can never round a 38-digit value before it is checked.
    if value != 0 and not -200 <= value.adjusted() <= 200:
        raise ValueFault('precision', 'value is outside the Oracle NUMBER exponent range')
    scale, precision = column.get('scale'), column.get('precision')
    if scale is not None:
        try:
            rounded = value.quantize(Decimal(1).scaleb(-scale, context=CTX), rounding=ROUND_HALF_UP, context=CTX)
        except InvalidOperation:
            raise ValueFault('precision', f'value cannot be represented with {scale} fractional digits')
        if rounded != value:
            if column.get('scalePolicy') != 'round':
                raise ValueFault('scale', f'value has more than {scale} fractional digits; Oracle would round it silently (set scalePolicy to round to accept that loss)')
            value = rounded
        if precision is not None and value.copy_abs() >= Decimal(1).scaleb(precision - scale, context=CTX):
            raise ValueFault('precision', f'value exceeds NUMBER({precision},{scale})')
    elif precision is not None:
        if value.copy_abs() >= Decimal(1).scaleb(precision, context=CTX):
            raise ValueFault('precision', f'value exceeds NUMBER({precision})')
    if significant_digits(value) > NUMBER_DIGITS or (value != 0 and not -130 <= value.adjusted() <= 125):
        raise ValueFault('precision', 'value exceeds Oracle NUMBER precision (38 digits) or exponent range')
    return Decimal(0) if value == 0 else CTX.normalize(value)


def store_value(column, value):
    """The value Oracle holds after assigning a computed value to a column, or ValueFault when it cannot hold it
    without silent loss (scale, fractional seconds) or at all (precision, length)."""
    if value is None:
        return None
    kind = column['type']
    if kind == 'number':
        return store_number(column, value)
    if kind in ('varchar2', 'raw') and len(value) > column['length']:
        raise ValueFault('length', f'the value has {len(value)} {"characters" if kind == "varchar2" else "bytes"}; the column allows {column["length"]}')
    if kind in ('timestamp', 'timestampTz') and value.microsecond % (10 ** (6 - column.get('fraction', 6))):
        raise ValueFault('loss', f'fractional seconds beyond {column.get("fraction", 6)} digits would be rounded by Oracle')
    return value


def parse_stamp(raw, kind, fraction):
    if not isinstance(raw, str):
        raise ValueFault('type', f'a {kind} cell must be ISO 8601 text')
    match = STAMP.fullmatch(raw)
    if not match:
        raise ValueFault('format', f'a {kind} cell must look like YYYY-MM-DDTHH:MM:SS' + ('.ffffff' if kind != 'date' else '') + ('+HH:MM' if kind == 'timestampTz' else ''))
    year, month, day, hour, minute, second, frac, zone = match.groups()
    if kind == 'date' and (frac or zone):
        raise ValueFault('loss', 'a DATE has whole-second wall-clock precision and no time zone')
    if kind == 'timestamp' and zone:
        raise ValueFault('zone', 'a zone designator needs a timestampTz column; a plain timestamp is wall-clock time')
    if kind == 'timestampTz' and (zone is None or hour is None):
        raise ValueFault('zone', 'a timestampTz cell needs a time and an explicit Z or +HH:MM offset; region names are not accepted')
    if frac and len(frac) > fraction and frac[fraction:].strip('0'):
        raise ValueFault('loss', f'fractional seconds beyond {fraction} digits would be rounded by Oracle; refuse instead')
    micro = int((frac or '').ljust(9, '0')[:6])
    try:
        value = datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0), int(second or 0), micro)
    except ValueError as error:
        raise ValueFault('range', str(error))
    if zone:
        if zone == 'Z':
            offset = timedelta(0)
        else:
            sign = -1 if zone[0] == '-' else 1
            hours, minutes = int(zone[1:3]), int(zone[4:6])
            if minutes > 59 or hours * 60 + minutes > 14 * 60:
                raise ValueFault('range', 'time zone offsets run from -14:00 to +14:00')
            offset = sign * timedelta(hours=hours, minutes=minutes)
        value = value.replace(tzinfo=timezone(offset))
    return value


def canonical_json(raw):
    """Exact, bounded standard JSON text; duplicate keys and nonfinite values refuse."""
    try:
        if not isinstance(raw, str) or len(raw.encode('utf-8')) > LARGE_LIMIT:
            raise ValueFault('json', 'a JSON cell is standard JSON text of at most 262144 UTF-8 bytes')
    except UnicodeError as error:
        raise ValueFault('json', 'JSON contains invalid Unicode') from error
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueFault('json', 'duplicate JSON object key')
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_float=Decimal, parse_int=Decimal,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueFault('json', 'nonfinite JSON number')))
        count = [0]
        def encode(item, depth=0):
            count[0] += 1
            if depth > 32 or count[0] > 10000:
                raise ValueFault('json', 'JSON nesting exceeds 32 levels or 10000 values')
            if isinstance(item, Decimal):
                return number_text(parse_decimal(item, {}))
            if isinstance(item, dict):
                return '{' + ','.join(json.dumps(k, ensure_ascii=False) + ':' + encode(v, depth + 1) for k, v in sorted(item.items())) + '}'
            if isinstance(item, list):
                return '[' + ','.join(encode(v, depth + 1) for v in item) + ']'
            return json.dumps(item, ensure_ascii=False, allow_nan=False)
        result = encode(value)
        result.encode('utf-8')
        return result
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, ValueFault):
            raise
        raise ValueFault('json', 'invalid standard JSON text') from error


def parse_value(column, raw, csv=False):
    """Convert one authored/captured cell to its exact typed value; None is SQL NULL."""
    kind = column['type']
    if raw is None:
        return None
    if csv:
        if raw == '':
            return None
        if kind == 'boolean':
            if raw not in ('true', 'false'):
                raise ValueFault('type', 'CSV booleans are true or false')
            return raw == 'true'
    if kind == 'json':
        return canonical_json(raw)
    if kind == 'clob':
        if not isinstance(raw, str) or not raw or raw == '\\N':
            raise ValueFault('text', 'a CLOB is non-empty Unicode text; use null for SQL NULL; the CSV null token is reserved')
        try:
            raw.encode('utf-8')
        except UnicodeError:
            raise ValueFault('text', 'CLOB contains invalid Unicode')
        if len(raw.encode('utf-16-le')) // 2 > LARGE_LIMIT:
            raise ValueFault('length', 'CLOB exceeds 262144 UTF-16 code units')
        return raw
    if kind == 'blob':
        if not isinstance(raw, str) or not re.fullmatch(r'(?:[0-9a-fA-F]{2})+', raw) or len(raw) > LARGE_LIMIT * 2:
            raise ValueFault('binary', 'a BLOB is non-empty hexadecimal text of at most 262144 bytes')
        return bytes.fromhex(raw)
    if kind == 'number':
        return parse_decimal(raw, column)
    if kind == 'varchar2':
        if not isinstance(raw, str):
            raise ValueFault('type', 'a varchar2 cell must be text')
        if raw == '':
            if column.get('emptyText') == 'null':
                return None
            raise ValueFault('empty-text', 'Oracle stores empty text as NULL; use null, or set emptyText to null to accept that conversion')
        if '\x00' in raw:
            raise ValueFault('text', 'adaptor policy: NUL characters are refused so that text stays portable through JSON, CSV and tools (the database itself can hold them)')
        if raw == '\\N':
            raise ValueFault('reserved', 'the text \\N is the reserved CSV null token and would be indistinguishable from NULL in published tables')
        try:
            raw.encode('utf-8')
        except UnicodeEncodeError:
            raise ValueFault('text', 'text is not valid Unicode (lone surrogate)')
        if len(raw) > column['length']:
            raise ValueFault('length', f'text has {len(raw)} characters; the column allows {column["length"]}')
        return raw
    if kind in ('date', 'timestamp', 'timestampTz'):
        return parse_stamp(raw, kind, 0 if kind == 'date' else column.get('fraction', 6))
    if kind == 'raw':
        if not isinstance(raw, str) or not re.fullmatch(r'(?:[0-9a-fA-F]{2})+', raw):
            raise ValueFault('format', 'a raw cell is non-empty hexadecimal text; Oracle stores an empty RAW as NULL')
        if len(raw) // 2 > column['length']:
            raise ValueFault('length', f'raw value has {len(raw) // 2} bytes; the column allows {column["length"]}')
        return bytes.fromhex(raw)
    if not isinstance(raw, bool):
        raise ValueFault('type', 'a boolean cell must be true or false')
    return raw


def number_text(value):
    if value == 0:
        return '0'
    return format(CTX.normalize(value), 'f')


def canonical(kind, value):
    """JSON-safe exact form of a typed value (the published interchange representation)."""
    if value is None:
        return None
    if kind == 'number':
        return number_text(value)
    if kind in ('varchar2', 'boolean', 'clob', 'json'):
        return value
    if kind in ('raw', 'blob'):
        return value.hex()
    text_value = '%04d-%02d-%02dT%02d:%02d:%02d' % (value.year, value.month, value.day, value.hour, value.minute, value.second)
    if kind != 'date' and value.microsecond:
        text_value += ('.%06d' % value.microsecond).rstrip('0')
    if kind == 'timestampTz':
        minutes = int(value.utcoffset().total_seconds() // 60)
        text_value += '%s%02d:%02d' % ('-' if minutes < 0 else '+', abs(minutes) // 60, abs(minutes) % 60)
    return text_value


def significant_digits(value):
    """Significant digits of a finite Decimal, counted from its digit tuple so that no context can round the count."""
    digits = value.as_tuple().digits
    end = len(digits)
    while end > 1 and digits[end - 1] == 0:
        end -= 1
    return 0 if value == 0 else end


def parse_result_decimal(raw):
    """Decode a computed NUMBER (AVG, division, sums, products).

    Storage is limited to 38 significant digits, but Oracle computes with 20 base-100 digits, so a computed
    value such as 1/3 carries 40 significant digits (observed natively: ``.3333333333333333333333333333333333333333``).
    RESULT_DIGITS is that computation limit, not an arbitrary bound; more digits mean the value is not an Oracle
    computed NUMBER and are refused. Digits are counted before any rounding."""
    if isinstance(raw, Decimal):
        value = raw
    elif isinstance(raw, str) and DECIMAL.fullmatch(raw):
        value = Decimal(raw)
    else:
        raise ValueFault('type', 'a computed NUMBER must be decimal text')
    if not value.is_finite():
        raise ValueFault('number', 'a computed NUMBER must be finite')
    if significant_digits(value) > RESULT_DIGITS:
        raise ValueFault('precision', f'a computed NUMBER has more than {RESULT_DIGITS} significant digits, the most Oracle computes')
    if value != 0 and not -130 <= value.adjusted() <= 125:
        raise ValueFault('number', 'a computed NUMBER is outside the Oracle exponent range')
    return Decimal(0) if value == 0 else CTX.normalize(value)


STORE_CONTEXT = Context(prec=NUMBER_DIGITS, rounding=ROUND_HALF_UP, traps=[])


def store_number(column, value):
    """The value Oracle would store when a computed NUMBER is assigned to a column: rounded to 38 significant
    digits, then held to the column's scale policy and precision (raises ValueFault: scale, precision)."""
    return parse_decimal(STORE_CONTEXT.plus(value), column)


def from_native(kind, value, result=False):
    """Decode a worker cell (decimal text, TO_CHAR text, hex, bool). ``result`` selects the computed-NUMBER policy."""
    if value is None:
        return None
    if kind == 'number':
        return parse_result_decimal(value) if result else parse_decimal(value, {})
    if kind in ('date', 'timestamp', 'timestampTz'):
        text_value = value.strip()
        if text_value.startswith('-'):
            raise ValueFault('range', 'a BC (negative-year) date is not supported; the adaptor holds years 1 to 9999')
        return parse_stamp(text_value, kind, 6)
    if kind == 'json':
        return canonical_json(value)
    if kind == 'clob':
        return parse_value({'type': 'clob'}, value)
    if kind in ('raw', 'blob'):
        return bytes.fromhex(value)
    return value


def sort_key(kind, value):
    """Deterministic total order: NULLs last, instants for timestampTz, code points for text."""
    if value is None:
        return (1,)
    if kind == 'raw':
        return (0, value)
    if kind == 'boolean':
        return (0, int(value))
    if kind == 'timestampTz':
        return (0, value.astimezone(timezone.utc).replace(tzinfo=None), value.utcoffset())
    return (0, value)


# ---------------------------------------------------------------------------
# Semantic planning
# ---------------------------------------------------------------------------
def identifier(value, at, code='INVALID_ORACLE_NAME'):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value) or value in RESERVED_NAMES:
        problem(code, 'use a lower-case ASCII identifier of at most 24 characters that is not an Oracle keyword', at,
                'letters, digits and underscores starting with a letter; Oracle stores the upper-case name', value=str(value)[:40])
    return value


def plan_connection(connection):
    at = '$.connection'
    profile = connection['profile']
    if not PROFILE.fullmatch(profile):
        problem('INVALID_ORACLE_CONNECTION', 'a profile is a lower-case label of at most 32 characters', at + '.profile',
                'choose a label such as free_local; credentials stay in host environment variables', profile=profile[:40])
    default = ENV_PREFIX + profile.upper()
    names = {}
    for key, suffix in (('userVariable', '_USER'), ('passwordVariable', '_PASSWORD'), ('dsnVariable', '_DSN')):
        name = connection.get(key, default + suffix)
        if not ENV_NAME.fullmatch(name):
            problem('INVALID_ORACLE_CONNECTION', f'credential variables are referenced by name and must start with {ENV_PREFIX}', f'{at}.{key}',
                    'name an upper-case host environment variable; never put credential values in a document', name=name[:40])
        names[key] = name
    if len(set(names.values())) != 3:
        problem('INVALID_ORACLE_CONNECTION', 'user, password and DSN need three different variable names', at)
    return {'profile': profile, **names, 'connectTimeout': connection['connectTimeoutSeconds'], 'callTimeout': connection['callTimeoutSeconds']}


def plan_column(column, at):
    name, kind = identifier(column['name'], at + '.name'), column['type']
    result = {'name': name, 'type': kind, 'precision': None, 'scale': None, 'length': None, 'fraction': None, 'nullable': column['nullable'],
              'emptyText': column['emptyText'], 'scalePolicy': column['scalePolicy']}
    allowed = {'number': ('precision', 'scale', 'scalePolicy'), 'varchar2': ('length', 'emptyText'), 'raw': ('length',),
               'timestamp': ('fraction',), 'timestampTz': ('fraction',), 'date': (), 'boolean': (), 'clob': (), 'blob': (), 'json': ()}[kind]
    for key in ('precision', 'scale', 'length', 'fraction'):
        if key in column:
            if key not in allowed:
                problem('INVALID_ORACLE_TABLE', f'{key} does not apply to a {kind} column', f'{at}.{key}', f'remove {key}, or choose a type that uses it')
            result[key] = column[key]
    for key, default in (('emptyText', 'reject'), ('scalePolicy', 'reject')):
        if key not in allowed and column[key] != default:
            problem('INVALID_ORACLE_TABLE', f'{key} does not apply to a {kind} column', f'{at}.{key}')
    if kind in ('varchar2', 'raw'):
        if result['length'] is None:
            problem('INVALID_ORACLE_TABLE', f'a {kind} column needs a length', at + '.length', 'declare characters for varchar2 (at most 1000) or bytes for raw (at most 2000)')
        if kind == 'varchar2' and result['length'] > 1000:
            problem('INVALID_ORACLE_TABLE', 'varchar2 length is at most 1000 characters so that the 4000-byte Oracle limit always holds', at + '.length')
    if kind == 'number':
        if result['scale'] is not None and result['precision'] is None:
            problem('INVALID_ORACLE_TABLE', 'a NUMBER scale needs a precision', at + '.scale')
        if result['precision'] is not None:
            result['scale'] = result['scale'] or 0
            if result['scale'] > result['precision']:
                problem('INVALID_ORACLE_TABLE', 'scale cannot exceed precision', at + '.scale')
    if kind in ('timestamp', 'timestampTz') and result['fraction'] is None:
        result['fraction'] = 6
    return result


def plan_table(table, at, previous):
    name = identifier(table['name'], at + '.name')
    if name in previous:
        problem('INVALID_ORACLE_TABLE', 'table names must be unique', at + '.name', name=name)
    columns, seen = [], set()
    for i, column in enumerate(table['columns']):
        planned = plan_column(column, f'{at}.columns[{i}]')
        if planned['name'] in seen:
            problem('INVALID_ORACLE_TABLE', 'column names must be unique within a table', f'{at}.columns[{i}].name', column=planned['name'])
        seen.add(planned['name'])
        columns.append(planned)
    by_name = {c['name']: c for c in columns}

    def members(names, where, kinds=None):
        for j, n in enumerate(names):
            if n not in by_name:
                problem('INVALID_ORACLE_TABLE', 'column is not declared in this table', f'{where}[{j}]', column=n, declared=sorted(by_name))
            if kinds and by_name[n]['type'] not in kinds:
                problem('INVALID_ORACLE_TABLE', f'a {by_name[n]["type"]} column cannot be used here', f'{where}[{j}]', kinds=list(kinds))
        return list(names)
    key = members(table['primaryKey'], at + '.primaryKey', KEY_TYPES)
    for n in key:
        if by_name[n]['nullable']:
            problem('INVALID_ORACLE_TABLE', 'primary-key columns cannot be nullable', at + '.primaryKey', column=n)
    uniques = [members(u['columns'], f'{at}.unique[{i}].columns', KEY_TYPES) for i, u in enumerate(table['unique'])]
    if any(set(u) == set(key) for u in uniques) or len({tuple(sorted(u)) for u in uniques}) != len(uniques):
        problem('INVALID_ORACLE_TABLE', 'duplicate key declaration: a unique key repeats the primary key or another unique key', at + '.unique')
    if table['external'] and 'source' in table:
        problem('INVALID_ORACLE_TABLE', 'an external table already exists in the database and cannot also load a source', at + '.source',
                'remove source, or set external to false to create and load the table')
    source = None
    if 'source' in table:
        path = table['source']['path']
        suffix = '.' + table['source']['format']
        if not path.startswith('/') or not path.lower().endswith(suffix):
            problem('INVALID_ORACLE_SOURCE', f'select an absolute local {suffix} file matching the declared format', at + '.source.path')
        source = {'path': path, 'format': table['source']['format']}
    return {'name': name, 'external': table['external'], 'columns': columns, 'primaryKey': key, 'unique': uniques, 'foreignKeys': [],
            'checks': [], 'source': source, '_declared': table}


def plan_tables(raw_tables):
    tables, by_name = [], {}
    for i, raw in enumerate(raw_tables):
        planned = plan_table(raw, f'$.tables[{i}]', by_name)
        by_name[planned['name']] = planned
        tables.append(planned)
    for i, table in enumerate(tables):
        declared = table.pop('_declared')
        at = f'$.tables[{i}]'
        by_col = {c['name']: c for c in table['columns']}
        for j, fk in enumerate(declared['foreignKeys']):
            where = f'{at}.foreignKeys[{j}]'
            parent = by_name.get(fk['table'])
            if parent is None:
                problem('INVALID_ORACLE_TABLE', 'a foreign key must reference a table declared in this document', where + '.table', table=fk['table'])
            if len(fk['columns']) != len(fk['references']):
                problem('INVALID_ORACLE_TABLE', 'columns and references must pair up', where)
            if any(c not in by_col for c in fk['columns']):
                problem('INVALID_ORACLE_TABLE', 'foreign-key column is not declared in this table', where + '.columns')
            parent_cols = {c['name']: c for c in parent['columns']}
            if any(c not in parent_cols for c in fk['references']):
                problem('INVALID_ORACLE_TABLE', 'referenced column is not declared in the parent table', where + '.references')
            if set(fk['references']) not in [set(parent['primaryKey'])] + [set(u) for u in parent['unique']]:
                problem('INVALID_ORACLE_TABLE', 'a foreign key must reference the parent primary key or a unique key', where + '.references')
            for a, b in zip(fk['columns'], fk['references']):
                if by_col[a]['type'] != parent_cols[b]['type']:
                    problem('INVALID_ORACLE_TABLE', 'foreign-key and referenced column types must agree', where + '.columns', column=a)
            if fk['onDelete'] == 'setNull' and any(not by_col[c]['nullable'] for c in fk['columns']):
                problem('INVALID_ORACLE_TABLE', 'setNull needs nullable foreign-key columns', where + '.onDelete')
            table['foreignKeys'].append({'columns': list(fk['columns']), 'table': fk['table'], 'references': list(fk['references']), 'onDelete': fk['onDelete']})
        scope = Scope({table['name']: table}, [table['name']])
        for j, check in enumerate(declared['checks']):
            if check['name'] in [c['name'] for c in table['checks']]:
                problem('INVALID_ORACLE_TABLE', 'check names must be unique', f'{at}.checks[{j}].name')
            table['checks'].append(scope.condition(check, f'{at}.checks[{j}]', allow_measure=False))
    order, state = [], {}

    def visit(table, trail):
        if state.get(table['name']) == 'done':
            return
        if state.get(table['name']) == 'active':
            problem('INVALID_ORACLE_TABLE', 'foreign keys form a cycle between tables', '$.tables', cycle=trail)
        state[table['name']] = 'active'
        for fk in table['foreignKeys']:
            if fk['table'] != table['name']:
                visit(by_name[fk['table']], trail + [fk['table']])
        state[table['name']] = 'done'
        order.append(table['name'])
    for table in tables:
        visit(table, [table['name']])
    return tables, order


class Scope:
    """Static typing for operands, derived values and named conditions within one relation."""

    def __init__(self, tables, aliases):
        self.tables = tables
        self.aliases = list(aliases)
        self.derived, self.measures, self.conditions, self.group_keys = {}, {}, {}, None

    def column(self, ref, at):
        match = REFERENCE.fullmatch(ref) if isinstance(ref, str) else None
        if not match or match.group(1) not in self.aliases:
            problem('INVALID_ORACLE_QUERY', 'use alias.column with an alias from this relation', at, f'available aliases: {", ".join(self.aliases)}', reference=str(ref)[:60])
        found = next((c for c in self.tables[match.group(1)]['columns'] if c['name'] == match.group(2)), None)
        if found is None:
            problem('INVALID_ORACLE_QUERY', 'column is not declared in that table', at, 'declared columns: ' + ', '.join(c['name'] for c in self.tables[match.group(1)]['columns']), reference=ref)
        return found

    def operand(self, op, at, allow=('column', 'literal', 'derived', 'measure')):
        present = [k for k in OPERAND['properties'] if k in op]
        if len(present) != 1:
            problem('INVALID_ORACLE_QUERY', 'an operand names exactly one of column, literal, derived or measure', at, 'keep one member', present=present)
        key = present[0]
        if key not in allow:
            problem('INVALID_ORACLE_QUERY', f'a {key} operand is not allowed here', at, 'allowed here: ' + ', '.join(allow))
        if key == 'column':
            return {'column': op['column'], 'kind': self.column(op['column'], at + '.column')['type']}
        if key == 'literal':
            literal = op['literal']
            if literal['value'] is None:
                return {'literal': {'type': literal['type'], 'value': None}, 'kind': literal['type']}
            try:
                value = parse_value(LITERAL_COLUMN | {'type': literal['type']}, literal['value'])
            except ValueFault as error:
                problem('INVALID_ORACLE_VALUE', str(error), at + '.literal.value', 'an empty text literal is NULL in Oracle: use the isNull operator', reason=error.reason)
            return {'literal': {'type': literal['type'], 'value': canonical(literal['type'], value)}, 'kind': literal['type']}
        table = {'derived': self.derived, 'measure': self.measures}[key]
        if op[key] not in table:
            problem('INVALID_ORACLE_QUERY', f'no earlier {key} has this name', f'{at}.{key}', 'define it before use; names resolve in order', name=op[key], defined=sorted(table))
        return {key: op[key], 'kind': table[op[key]]}

    def condition(self, cond, at, allow_measure):
        name = identifier(cond['name'], at + '.name')
        if name in self.conditions:
            problem('INVALID_ORACLE_QUERY', 'condition names must be unique', at + '.name', name=name)
        allow = ('column', 'literal', 'derived') + (('measure',) if allow_measure else ())
        terms = []
        for i, term in enumerate(cond['terms']):
            terms.append(self.term(term, f'{at}.terms[{i}]', allow))
        planned = {'name': name, 'combine': cond['combine'], 'negate': cond['negate'], 'terms': terms}
        self.conditions[name] = 'boolean'
        return planned

    def term(self, term, at, allow):
        if 'condition' in term:
            extra = [k for k in term if k not in ('condition', 'negate')]
            if extra or term['condition'] not in self.conditions:
                problem('INVALID_ORACLE_QUERY', 'a term references an earlier named condition on its own', at, 'use only condition (and optionally negate), naming an earlier condition',
                        condition=term['condition'], defined=sorted(self.conditions))
            return {'condition': term['condition'], 'negate': term['negate']}
        operator = term.get('operator')
        if operator is None or 'left' not in term:
            problem('INVALID_ORACLE_QUERY', 'a term needs left and operator, or a condition reference', at)
        shape = {'between': ('left', 'right', 'upper'), 'in': ('left', 'values'), 'isNull': ('left',)}.get(operator, ('left', 'right'))
        extras = [k for k in ('left', 'right', 'upper', 'values') if k in term and k not in shape]
        missing = [k for k in shape if k not in term]
        if extras or missing:
            problem('INVALID_ORACLE_QUERY', f'operator {operator} takes exactly: {", ".join(shape)}', at, missing=missing, unexpected=extras)
        planned = {'operator': operator, 'negate': term['negate'], 'left': self.operand(term['left'], at + '.left', allow)}
        kind = planned['left']['kind']
        for key in ('right', 'upper'):
            if key in term:
                planned[key] = self.operand(term[key], f'{at}.{key}', allow)
        if 'values' in term:
            planned['values'] = [self.operand(v, f'{at}.values[{i}]', allow) for i, v in enumerate(term['values'])]
        others = [planned[k]['kind'] for k in ('right', 'upper') if k in planned] + [v['kind'] for v in planned.get('values', [])]
        if kind in LARGE_TYPES and operator != 'isNull':
            problem('INVALID_ORACLE_QUERY', 'LOB and JSON values support only isNull conditions; extract a JSON scalar first', at)
        if operator in ('startsWith', 'contains') and kind != 'varchar2':
            problem('INVALID_ORACLE_QUERY', f'{operator} compares text', at + '.left', kind=kind)
        if operator not in ('isNull',) and any(o != kind for o in others):
            problem('INVALID_ORACLE_QUERY', 'operands must have the same Oracle type; there is no implicit conversion', at, 'declare matching typed literals or columns', kinds=[kind, *others])
        if operator in ('lessThan', 'lessOrEqual', 'greaterThan', 'greaterOrEqual', 'between') and kind not in ORDERED:
            problem('INVALID_ORACLE_QUERY', f'{kind} values cannot be ordered here', at + '.left', 'use equals or isNull for raw and boolean values')
        for value in [planned.get(k) for k in ('right', 'upper')] + planned.get('values', []):
            if value is not None and 'literal' in value and value['literal']['value'] is None:
                problem('INVALID_ORACLE_QUERY', 'comparing with a NULL literal is never true; use the isNull operator', at, 'isNull tests for NULL; every other comparison with NULL is unknown')
        return planned

    def derive(self, derived, at):
        name = identifier(derived['name'], at + '.name')
        if name in self.derived:
            problem('INVALID_ORACLE_QUERY', 'derived names must be unique', at + '.name', name=name)
        function = derived['function']
        low, high = ARITY[function]
        arguments = derived['arguments']
        if not low <= len(arguments) <= high:
            problem('INVALID_ORACLE_QUERY', f'{function} takes {low}' + (f'-{high}' if high != low else '') + ' arguments', at + '.arguments')
        when = None
        if function == 'conditional':
            if 'when' not in derived:
                problem('INVALID_ORACLE_QUERY', 'conditional needs a when condition: arguments are the value for TRUE and the value for FALSE or unknown', at + '.when')
            when = self.condition(derived['when'], at + '.when', allow_measure=False)
        elif 'when' in derived:
            problem('INVALID_ORACLE_QUERY', 'only conditional takes a when condition', at + '.when')
        planned_args = [self.operand(a, f'{at}.arguments[{i}]', ('column', 'literal', 'derived')) for i, a in enumerate(arguments)]
        kinds = [a['kind'] for a in planned_args]
        result = result_kind(function, kinds, planned_args, at)
        for key, default in (('digits', 0), ('zero', 'error')):
            if key in derived and derived[key] != default and (key, function) not in (('digits', 'round'), ('digits', 'truncate'), ('zero', 'divide')):
                problem('INVALID_ORACLE_QUERY', f'{key} does not apply to {function}', f'{at}.{key}')
        path = derived.get('path')
        if function.startswith('json'):
            if not isinstance(path, str) or not re.fullmatch(r'\$(?:\.[A-Za-z_][A-Za-z0-9_]*|\[(?:0|[1-9][0-9]{0,3})\])*', path):
                problem('INVALID_ORACLE_QUERY', 'a JSON path uses only $.member and [index] steps, without wildcards or SQL', at + '.path')
        elif path is not None:
            problem('INVALID_ORACLE_QUERY', 'path applies only to JSON scalar extraction', at + '.path')
        self.derived[name] = result
        return {'name': name, 'function': function, 'arguments': planned_args, 'digits': derived['digits'], 'zero': derived['zero'], 'when': when, 'kind': result, **({'path': path} if path is not None else {})}


ARITY = {'jsonNumber': (1, 1), 'jsonText': (1, 1), 'jsonBoolean': (1, 1), 'add': (2, 2), 'subtract': (2, 2), 'multiply': (2, 2), 'divide': (2, 2), 'modulo': (2, 2), 'negate': (1, 1), 'abs': (1, 1), 'floor': (1, 1),
         'ceiling': (1, 1), 'round': (1, 1), 'truncate': (1, 1), 'upper': (1, 1), 'lower': (1, 1), 'trim': (1, 1), 'concat': (2, 4),
         'substring': (2, 3), 'length': (1, 1), 'coalesce': (2, 4), 'nullIf': (2, 2), 'conditional': (2, 2), 'addDays': (2, 2),
         'truncateDay': (1, 1), 'extractYear': (1, 1), 'extractMonth': (1, 1), 'extractDay': (1, 1)}
INEXACT = ('divide',)


def result_kind(function, kinds, arguments, at):
    def need(expected, positions=None):
        for i, kind in enumerate(kinds):
            if (positions is None or i in positions) and kind not in expected:
                problem('INVALID_ORACLE_QUERY', f'{function} argument {i + 1} must be {" or ".join(expected)}, not {kind}', f'{at}.arguments[{i}]',
                        'Oracle conversions are never implicit; use a matching column or typed literal')
    if function.startswith('json'):
        need(('json',))
        return {'jsonNumber': 'number', 'jsonText': 'varchar2', 'jsonBoolean': 'boolean'}[function]
    if any(k in LARGE_TYPES for k in kinds):
        problem('INVALID_ORACLE_QUERY', 'LOB and JSON values are projected directly or JSON scalars are extracted', at)
    if function in ('add', 'subtract', 'multiply', 'divide', 'modulo', 'negate', 'abs', 'floor', 'ceiling', 'round', 'truncate'):
        need(('number',))
        return 'number'
    if function in ('upper', 'lower', 'trim', 'concat'):
        need(('varchar2',))
        return 'varchar2'
    if function == 'length':
        need(('varchar2',))
        return 'number'
    if function == 'substring':
        need(('varchar2',), (0,))
        need(('number',), (1, 2))
        for i, a in enumerate(arguments[1:], 1):
            value = a.get('literal', {}).get('value')
            if 'literal' not in a or value is None or Decimal(value) != int(Decimal(value)) or int(Decimal(value)) < 1:
                problem('INVALID_ORACLE_QUERY', 'substring start and length are positive integer literals', f'{at}.arguments[{i}]',
                        'zero, negative and fractional positions have Oracle-specific meanings that are not supported; state a whole number from 1')
        return 'varchar2'
    if function in ('coalesce', 'nullIf', 'conditional'):
        if len(set(kinds)) != 1:
            problem('INVALID_ORACLE_QUERY', f'{function} arguments must share one type', at + '.arguments', kinds=kinds)
        return kinds[0]
    if function == 'addDays':
        need(('date',), (0,))
        need(('number',), (1,))
        return 'date'
    if function == 'truncateDay':
        need(('date',))
        return 'date'
    need(('date', 'timestamp'))
    return 'number'
