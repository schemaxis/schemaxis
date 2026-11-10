# Copyright (C) 2026 David L F Gaden
"""Standard-library CSV semantics and row oracle, independent of Arrow compute."""
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import io
import math
import re
import struct

TYPES = ['bool', 'int32', 'int64', 'float64', 'utf8', 'timestamp_us_utc']
NULL = '\\N'
MAX_SOURCE = 8 * 1024**2
# An opted-in table.csv is bounded by the typed CSV source limit, so that every
# published table can itself be declared as an Arrow source.
MAX_CSV = MAX_SOURCE
CSV_FORMAT = 'schemaxis.apachearrow.table-csv/1'
INTEGER = re.compile(r'(?:0|-[1-9][0-9]*|[1-9][0-9]*)\Z')
NUMBER = re.compile(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z')
UTC = re.compile(r'(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(?:Z|\+00:00)\Z', re.ASCII)
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def scalar(text, kind):
    if not isinstance(text, str) or len(text.encode('utf-8')) > 4096 or '\x00' in text or text == NULL:
        raise ValueError('require a nonnull literal of at most 4096 UTF-8 bytes; \\N is reserved')
    if kind == 'utf8':
        return text
    if kind == 'bool':
        if text not in ('true', 'false'):
            raise ValueError('boolean spelling must be true or false')
        return text == 'true'
    if kind in ('int32', 'int64'):
        bits = 32 if kind == 'int32' else 64
        if not INTEGER.fullmatch(text) or len(text) > 20:
            raise ValueError('require canonical base-ten integer without leading zeroes or plus sign')
        value = int(text)
        if not -(1 << (bits - 1)) <= value < 1 << (bits - 1):
            raise ValueError('integer outside signed ' + str(bits) + '-bit range')
        return value
    if kind == 'float64':
        if not NUMBER.fullmatch(text):
            raise ValueError('require JSON-number decimal spelling')
        value = float(text)
        try:
            underflow = value == 0 and Decimal(text) != 0
        except InvalidOperation as error:
            raise ValueError('decimal exponent outside supported parsing range') from error
        if not math.isfinite(value) or underflow:
            raise ValueError('float overflow, nonfinite value or nonzero underflow to zero')
        return value
    if kind == 'timestamp_us_utc':
        match = UTC.fullmatch(text)
        if not match:
            raise ValueError('require UTC YYYY-MM-DDTHH:MM:SS[.ffffff]Z or +00:00')
        # Explicit components: datetime.fromisoformat accepts only 3 or 6 fractional
        # digits before Python 3.11, so the 1-6 digit grammar must not depend on it.
        # The constructor still rejects impossible dates, hour 24 and leap seconds.
        *whole, fraction = match.groups()
        civil = datetime(*map(int, whole), int((fraction or '').ljust(6, '0')), timezone.utc)
        delta = civil - EPOCH
        return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
    raise ValueError('unsupported declared type')


def source(data, columns):
    if len(data) > MAX_SOURCE:
        raise ValueError('CSV exceeds 8 MiB')
    text = data.decode('utf-8')
    if text.startswith('\ufeff') or '\x00' in text:
        raise ValueError('CSV BOM and NUL are unsupported')
    # csv.reader(strict=True) still accepts a quote inside an unquoted cell.
    # Constrain the lexical dialect before either independent reader sees it.
    state, index = 'start', 0
    while index < len(text):
        char = text[index]
        if state == 'quoted':
            if char == '"':
                state = 'closed'
        elif state == 'closed' and char == '"':
            state = 'quoted'
        elif char in '\r\n':
            if char == '\r':
                if index + 1 >= len(text) or text[index + 1] != '\n':
                    raise ValueError('CSV records require LF or CRLF')
                index += 1
            state = 'start'
        elif char == ',':
            state = 'start'
        elif char == '"' and state == 'start':
            state = 'quoted'
        elif state == 'closed' or char == '"':
            raise ValueError('quote must enclose a complete CSV cell')
        else:
            state = 'unquoted'
        index += 1
    if state == 'quoted':
        raise ValueError('unterminated quoted CSV cell')
    records = csv.reader(io.StringIO(text, newline=''), strict=True)
    try:
        if next(records, None) != [c['name'] for c in columns]:
            raise ValueError('CSV header must match all declared names in order')
        rows, text_bytes = [], 0
        for i, record in enumerate(records):
            if i >= 10000 or (i + 1) * len(columns) > 200000:
                raise ValueError('CSV row/cell budget exceeded')
            if len(record) != len(columns):
                raise ValueError('row ' + str(i) + ': exact declared cell count required')
            row = []
            for column, raw in zip(columns, record):
                try:
                    if raw == NULL:
                        if not column['nullable']:
                            raise ValueError('null in nonnullable field')
                        value = None
                    else:
                        value = scalar(raw, column['type'])
                    if isinstance(value, str):
                        text_bytes += len(value.encode('utf-8'))
                    row.append(value)
                except (ValueError, OverflowError) as error:
                    raise ValueError(f'row {i}, column {column["name"]}: {error}') from error
            if text_bytes > MAX_SOURCE:
                raise ValueError('aggregate decoded text budget exceeded')
            rows.append(row)
        return rows
    except csv.Error as error:
        raise ValueError('invalid bounded CSV: ' + str(error)) from error


def output_columns(plan):
    by_name = {c['name']: c for c in plan['columns']}
    return [{'name': item['name'], 'type': item.get('cast', by_name[item['column']]['type']),
             'nullable': by_name[item['column']]['nullable'] and 'fillNull' not in item}
            for item in plan['select']]


def transform(plan, rows):
    """Literal ordered row comparisons, not native operation generation/replay."""
    indices = {c['name']: i for i, c in enumerate(plan['columns'])}
    columns = output_columns(plan)
    comparisons = []
    for predicate in plan['where']:
        index = indices[predicate['column']]
        literal = scalar(predicate['value'], plan['columns'][index]['type']) if 'value' in predicate else None
        comparisons.append((index, predicate['test'], literal))
    selected, result = [], []
    for row_index, row in enumerate(rows):
        keep = True
        for index, test, literal in comparisons:
            value = row[index]
            if test == 'isNull':
                match = value is None
            elif test == 'isValid':
                match = value is not None
            elif value is None:
                match = False
            else:
                match = {'eq': lambda: value == literal, 'ne': lambda: value != literal,
                         'lt': lambda: value < literal, 'le': lambda: value <= literal,
                         'gt': lambda: value > literal, 'ge': lambda: value >= literal}[test]()
            if not match:
                keep = False
                break
        if keep:
            output = []
            for item, column in zip(plan['select'], columns):
                value = row[indices[item['column']]]
                if value is None and 'fillNull' in item:
                    value = scalar(item['fillNull'], column['type'])
                output.append(value)
            result.append(output)
            selected.append(row_index)
    return columns, result, selected


def wire_rows(columns, rows):
    """Exact native snapshot encoding; every double uses its IEEE bit pattern."""
    return [[None if v is None else struct.pack('<d', v).hex() if c['type'] == 'float64'
             else str(v) if c['type'] in ('int64', 'timestamp_us_utc') else v
             for c, v in zip(columns, row)] for row in rows]


def equal(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, float):
        return struct.pack('<d', left) == struct.pack('<d', right)
    if isinstance(left, list):
        return len(left) == len(right) and all(equal(a, b) for a, b in zip(left, right))
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(equal(left[k], right[k]) for k in left)
    return left == right


def timestamp_text(value):
    civil = EPOCH + timedelta(microseconds=value)
    return f'{civil.year:04d}-{civil.month:02d}-{civil.day:02d}T{civil.hour:02d}:{civil.minute:02d}:{civil.second:02d}.{civil.microsecond:06d}Z'


def report(plan, rows, source_sha256):
    columns, output, selected = transform(plan, rows)
    published = []
    for row in output:
        values = []
        for column, value in zip(columns, row):
            if value is not None and column['type'] == 'int64':
                value = str(value)
            elif value is not None and column['type'] == 'timestamp_us_utc':
                value = timestamp_text(value)
            values.append(value)
        published.append(values)
    return {'format': 'schemaxis.apachearrow.table-report/1', 'sourceSha256': source_sha256,
            'inputRows': len(rows), 'outputRows': len(output), 'sourceRowIndices': selected,
            'columns': columns, 'nullCounts': [sum(row[i] is None for row in output) for i in range(len(columns))],
            'rows': published}


class NullCollision(ValueError):
    """A nonnull text value spelled like the reserved null token."""

    def __init__(self, row, column):
        super().__init__(f'row {row}, column {column}: nonnull text \\N would be read back as null')
        self.row, self.column = row, column


class CSVBudget(ValueError):
    """The encoded table.csv would exceed the publication byte budget."""


def float_text(value):
    """Shortest round-trip binary64 text in the layout Arrow C++ 26.0.0 writes.

    Plain decimal when the decimal point falls after 1-10 digits or at most five
    zeros before the first digit; otherwise d[.ddd]e+x/e-x with no padding. Digits
    are Python's shortest round-trip digits. Signed zero prints as 0 or -0.
    """
    if value == 0:
        return '-0' if math.copysign(1, value) < 0 else '0'
    parts = Decimal(repr(abs(value))).normalize().as_tuple()
    digits = ''.join(map(str, parts.digits))
    point = len(digits) + parts.exponent
    if 0 < point <= 10:
        body = digits + '0' * (point - len(digits)) if point >= len(digits) else digits[:point] + '.' + digits[point:]
    elif -6 < point <= 0:
        body = '0.' + '0' * -point + digits
    else:
        exponent = point - 1
        body = digits[0] + ('.' + digits[1:] if len(digits) > 1 else '') + 'e' + ('+' if exponent >= 0 else '-') + str(abs(exponent))
    return ('-' if value < 0 else '') + body


def csv_cell(kind, value):
    """Canonical lexical cell: null is bare \\N, text and timestamps are quoted, others bare."""
    if value is None:
        return NULL
    if kind == 'bool':
        return 'true' if value else 'false'
    if kind in ('int32', 'int64'):
        return str(value)
    if kind == 'float64':
        return float_text(value)
    quoted = timestamp_text(value) if kind == 'timestamp_us_utc' else value
    return '"' + quoted.replace('"', '""') + '"'


def csv_encode(columns, rows, limit=MAX_CSV):
    """Canonical table.csv bytes: UTF-8, no BOM, LF records, bare header, comma delimiter."""
    lines = [','.join(c['name'] for c in columns) + '\n']
    size = len(lines[0])
    for index, row in enumerate(rows):
        for column, value in zip(columns, row):
            if column['type'] == 'utf8' and value == NULL:
                raise NullCollision(index, column['name'])
        line = ','.join(csv_cell(c['type'], v) for c, v in zip(columns, row)) + '\n'
        size += len(line.encode('utf-8'))
        if size > limit:
            raise CSVBudget(f'encoded CSV exceeds {limit} bytes at output row {index}')
        lines.append(line)
    return ''.join(lines).encode('utf-8')
