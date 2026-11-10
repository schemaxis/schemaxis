"""Closed typed labelled tables: declared text/number columns, explicit nulls, no guessing.

A typed table is declared column by column (name, kind ``text`` or ``number``, nullable)
and filled from JSON rows or a captured CSV. Nothing is inferred: a number column never
accepts text, a text column never accepts a number, and booleans are neither. A null is
one explicit value that becomes a blank workbook cell. Empty text is rejected because the
native ODS reopen collapses it into a blank, which would silently conflate the two.
"""
import hashlib
import json
import math
import re
import statistics
from schemaxis.tabular import MAX_BYTES, MAX_ROWS, LIMIT
from .table import DECIMAL, fail, unsafe

MAX_COLUMNS = 64
MAX_CELLS = 100000
MAX_TEXT = 1024
MAX_TEXT_BYTES = 4 * 1024 * 1024
MAX_EXACT_INTEGER = 2 ** 53
NULL_TOKEN = '\\N'
KINDS = ('text', 'number')
SUMMARY_VERSION = 'schemaxis.calc.typed-summary/1'
CSV_FORMAT = 'schemaxis.calc.typed-csv/1'
LOSSES = ['Empty text is rejected and null is the only missing value: native reopening turns empty text into a blank.',
          'Workbook numbers keep 15 significant digits; this CSV keeps the exact binary64 value and stores negative zero as zero.',
          'The null token is reserved and cannot be present text; no types, dates, currency, time zones or units are inferred.',
          'Text keeps exact code points; control characters, line separators and unpaired surrogates are rejected.']
TOKEN_RECOVERY = ('choose a short token without spaces, commas, quotes or control characters that is not a decimal '
                  'number, and do not use it as text')
CSV_RECORD = re.compile(r'(?:"((?:[^"]|"")*)"|([^",\r\n"]*))(,|\r\n|\n|\Z)')


def control(character):
    """C0/C1 controls, DEL and Unicode line/paragraph separators cannot be kept as exact cell text."""
    code = ord(character)
    return code < 32 or 0x7F <= code <= 0x9F or code in (0x2028, 0x2029)


def check_token(token, location='nullToken'):
    if (not isinstance(token, str) or not 1 <= len(token) <= 16 or DECIMAL.fullmatch(token) or
            any(unsafe(c) or control(c) or c.isspace() or c in '",' for c in token)):
        fail('INVALID_TABLE', 'null token must be 1 to 16 visible characters, not a decimal number', location,
             value=token if isinstance(token, str) else None, recovery=TOKEN_RECOVERY)
    return token


def check_columns(columns, null_token, location='columns'):
    if not isinstance(columns, list) or not 1 <= len(columns) <= MAX_COLUMNS:
        fail('INVALID_TABLE', f'declare 1 to {MAX_COLUMNS} columns', location)
    names = set()
    for index, column in enumerate(columns):
        at = f'{location}[{index}]'
        name = column['name']
        if not name or len(name) > 128 or any(control(c) or unsafe(c) for c in name):
            fail('INVALID_TABLE', 'column name must be 1 to 128 characters without control characters or text '
                 'that workbook XML cannot represent', at + '.name', column=index,
                 recovery='rename the column; a leading = + - @ is allowed and stays literal text')
        if name in names:
            fail('INVALID_TABLE', 'column names must be distinct', at + '.name', column=name,
                 recovery='give every column a unique name')
        if name == null_token:
            fail('INVALID_TABLE', 'a column name cannot equal the reserved null token', at + '.name', column=name,
                 recovery='rename the column or choose another nullToken')
        names.add(name)
    return [{'name': c['name'], 'kind': c['kind'], 'nullable': bool(c.get('nullable', False))} for c in columns]


def check_text(value, null_token, at, *, record=None, name=None, source=None):
    context = {k: v for k, v in (('record', record), ('column', name), ('source', source)) if v is not None}
    if value == '':
        fail('INVALID_TABLE', 'empty text cannot be told apart from a blank cell in the reopened workbook', at,
             value='', recovery='mark a missing value as null (or the null token in CSV) and give present text at '
             'least one character', **context)
    if value == null_token:
        fail('INVALID_TABLE', 'text equals the reserved null token', at, value=value[:64],
             recovery='choose a different nullToken; the token cannot also be present text', **context)
    if len(value) > MAX_TEXT:
        fail('INVALID_TABLE', f'text is longer than {MAX_TEXT} characters', at, characters=len(value),
             recovery='shorten the text or keep the long note outside the workbook', **context)
    for character in value:
        if unsafe(character) or control(character):
            fail('INVALID_TABLE', 'text contains a control character, line separator or text workbook XML '
                 'cannot represent', at, codePoint='U+%04X' % ord(character), value=value[:64],
                 recovery='remove tabs, line breaks and control characters from the text', **context)
    return value


def check_number(value, at, *, record=None, name=None, source=None):
    context = {k: v for k, v in (('record', record), ('column', name), ('source', source)) if v is not None}
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > LIMIT:
        fail('INVALID_TABLE', 'number cells must be finite numbers within +/-1e100', at, value=value if
             type(value) in (int, float) and math.isfinite(value) else str(value)[:64],
             recovery='use a finite JSON number within +/-1e100; booleans and numeric strings are not numbers',
             **context)
    if type(value) is int and abs(value) > MAX_EXACT_INTEGER:
        fail('INVALID_TABLE', 'integer exceeds 2^53 and would not be stored exactly as a number', at, value=value,
             recovery='declare identifiers and other exact integers as text columns', **context)
    return float(value) + 0.0  # -0.0 becomes 0.0: workbook numbers do not preserve a negative-zero sign


def check_rows(columns, cells, *, minimum=1, location='rows'):
    """Final table-level rules shared by JSON and CSV ingestion."""
    if not minimum <= len(cells) <= MAX_ROWS:
        fail('INVALID_TABLE', f'table must contain {minimum} to {MAX_ROWS} records', location, records=len(cells))
    if len(cells) * len(columns) > MAX_CELLS:
        fail('RESOURCE_LIMIT', f'typed table is limited to {MAX_CELLS} cells', location,
             cells=len(cells) * len(columns), recovery='split the table into smaller workbooks')
    text_bytes = 0
    for index, row in enumerate(cells):
        if all(value is None for value in row):
            fail('INVALID_TABLE', 'every record needs at least one present cell', f'{location}[{index}]',
                 recovery='remove the all-blank record')
        text_bytes += sum(len(v.encode('utf-8')) for v in row if isinstance(v, str))
    if text_bytes > MAX_TEXT_BYTES:
        fail('RESOURCE_LIMIT', 'text in the table exceeds 4 MiB', location, bytes=text_bytes)
    for index, column in enumerate(columns):
        if column['kind'] == 'number':
            present = sum(1 for row in cells if row[index] is not None)
            if present < 2:
                fail('INVALID_TABLE', 'a number column needs at least two present values for COUNT, mean and STDEV',
                     f'columns[{index}]', column=column['name'], present=present,
                     recovery='supply more measurements or declare the column as text')


def validate(columns, rows, null_token=NULL_TOKEN):
    """Validate declared JSON rows without coercion; returns an independent normalized table."""
    null_token = check_token(null_token)
    columns = check_columns(columns, null_token)
    if not isinstance(rows, list):
        fail('INVALID_TABLE', 'rows must be an array of records', 'rows')
    cells = []
    for i, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != len(columns):
            fail('INVALID_TABLE', 'record width differs from the declared columns', f'rows[{i}]',
                 expectedCells=len(columns), cells=len(row) if isinstance(row, list) else None,
                 recovery='give every record exactly one cell per declared column; use null for a missing value')
        out = []
        for j, (column, value) in enumerate(zip(columns, row)):
            at = f'rows[{i}][{j}]'
            if value is None:
                if not column['nullable']:
                    fail('INVALID_TABLE', 'null in a column declared nullable: false', at, column=column['name'],
                         recovery='declare the column nullable or supply a value')
                out.append(None)
            elif column['kind'] == 'number':
                if type(value) is str or type(value) is bool:
                    fail('INVALID_TABLE', 'a number column accepts JSON numbers only; text and booleans are not '
                         'converted', at, column=column['name'], value=str(value)[:64],
                         recovery='write the number without quotes or declare the column as text')
                out.append(check_number(value, at, name=column['name']))
            else:
                if not isinstance(value, str):
                    fail('INVALID_TABLE', 'a text column accepts strings only; numbers and booleans are not '
                         'converted', at, column=column['name'], value=str(value)[:64],
                         recovery='quote the value as a JSON string to keep it exactly, for example "00123"')
                out.append(check_text(value, null_token, at, name=column['name']))
        cells.append(out)
    check_rows(columns, cells)
    return {'columns': columns, 'rows': cells, 'nullToken': null_token}


def records(payload, location):
    """Tokenize the closed CSV grammar: UTF-8, comma, LF/CRLF, double-quoted cells, no BOM."""
    if len(payload) > MAX_BYTES:
        fail('RESOURCE_LIMIT', 'CSV exceeds 8 MiB', location, maximumBytes=MAX_BYTES)
    try:
        text = payload.decode('utf-8')
    except UnicodeError as error:
        fail('INVALID_TABLE', 'CSV must be UTF-8: ' + str(error), location, recovery='save the file as UTF-8')
    if text.startswith('﻿'):
        fail('INVALID_TABLE', 'CSV must not start with a byte-order mark', location,
             recovery='save as UTF-8 without a BOM')
    result, row, position = [], [], 0
    while position < len(text):
        match = CSV_RECORD.match(text, position)
        if not match:
            fail('INVALID_TABLE', 'malformed CSV: stray quote, unterminated quote or bare carriage return', location,
                 record=len(result) + 1, offset=position,
                 recovery='quote whole cells, double any quote inside text and end records with LF or CRLF')
        quoted, bare, end = match.groups()
        row.append(bare if quoted is None else quoted.replace('""', '"'))
        position = match.end()
        if len(row) > MAX_COLUMNS:
            fail('INVALID_TABLE', f'a CSV record has more than {MAX_COLUMNS} cells', location, record=len(result) + 1,
                 recovery='declare at most 64 columns and give every record that many cells')
        if end != ',':
            result.append(row)
            row = []
        if len(result) > MAX_ROWS + 1:
            fail('INVALID_TABLE', f'table must contain at most {MAX_ROWS} records', location)
    if row:
        fail('INVALID_TABLE', 'CSV ends after a delimiter', location, record=len(result) + 1,
             recovery='finish the last record or remove the trailing comma')
    return result


def parse_csv(payload, columns, null_token=NULL_TOKEN, location='$'):
    """Parse a captured typed CSV against the declared header, kinds and null policy."""
    null_token = check_token(null_token)
    columns = check_columns(columns, null_token)
    found = records(payload, location)
    if not found:
        fail('INVALID_TABLE', 'CSV needs a header and at least one record', location)
    header = found[0]
    if len(header) != len(columns):
        fail('INVALID_TABLE', 'CSV header width differs from the declared columns', 'columns', record=1,
             expectedCells=len(columns), cells=len(header), source=location,
             recovery='declare every CSV column, in file order')
    for j, (column, label) in enumerate(zip(columns, header)):
        if label != column['name']:
            fail('INVALID_TABLE', 'CSV header differs from the declared column name', f'columns[{j}].name', record=1,
                 expected=column['name'], found=label[:64], source=location,
                 recovery='declare columns in file order with the exact header text')
    cells = []
    for i, record in enumerate(found[1:]):
        if len(record) != len(columns):
            fail('INVALID_TABLE', 'CSV record width differs from the header', f'rows[{i}]', record=i + 2,
                 expectedCells=len(columns), cells=len(record), source=location,
                 recovery='give every record one cell per column; remove blank lines')
        out = []
        for j, (column, text) in enumerate(zip(columns, record)):
            at = f'rows[{i}][{j}]'
            where = {'record': i + 2, 'name': column['name'], 'source': location}
            if text == null_token:
                if not column['nullable']:
                    fail('INVALID_TABLE', 'null token in a column declared nullable: false', at, record=i + 2,
                         column=column['name'], source=location,
                         recovery='declare the column nullable or supply a value')
                out.append(None)
            elif column['kind'] == 'text':
                out.append(check_text(text, null_token, at, **where))
            else:
                if not DECIMAL.fullmatch(text):
                    fail('INVALID_TABLE', 'CSV number cell is not a plain ASCII decimal (spaces, separators, '
                         'currency, percent and words are not accepted)', at, record=i + 2, column=column['name'],
                         value=text[:64], source=location,
                         recovery='use digits with an optional sign, fraction and exponent, or the null token')
                if text.lstrip('+-').isdigit() and abs(int(text)) > MAX_EXACT_INTEGER:
                    fail('INVALID_TABLE', 'integer exceeds 2^53 and would not be stored exactly as a number', at,
                         record=i + 2, column=column['name'], value=text[:64], source=location,
                         recovery='declare identifiers and other exact integers as text columns')
                out.append(check_number(float(text), at, **where))
        cells.append(out)
    check_rows(columns, cells)
    return {'columns': columns, 'rows': cells, 'nullToken': null_token}


def quote(text):
    return '"' + text.replace('"', '""') + '"'


def csv_bytes(table):
    """Canonical handoff: text and labels always quoted, numbers shortest round-trip, null token bare."""
    token = table['nullToken']
    lines = [','.join(quote(c['name']) for c in table['columns'])]
    for row in table['rows']:
        lines.append(','.join(token if v is None else quote(v) if isinstance(v, str) else repr(v) for v in row))
    payload = ('\n'.join(lines) + '\n').encode('utf-8')
    if len(payload) > MAX_BYTES:
        fail('RESOURCE_LIMIT', 'typed CSV publication exceeds 8 MiB', 'data.csv')
    return payload


DIGIT_TOLERANCE = 1e-14  # Data cells and MIN/MAX: LibreOffice writes numbers with 15 significant digits
SUMMARY_RELATIVE = 2e-8  # SUM, AVERAGE and STDEV: relative term
SUMMARY_ABSOLUTE = 1e-12  # ...plus this fraction of the column's largest present magnitude
DERIVED_METRICS = ('sum', 'mean', 'stdev')
COPIED_METRICS = ('min', 'max')


def column_scale(present):
    """Largest present magnitude of a number column; 0.0 when every present value is zero."""
    return max((abs(v) for v in present), default=0.0)


def metric_close(observed, wanted, scale, *, derived):
    """One rule for Summary workbook cells and typed-summary.json metric values.

    MIN and MAX copy a Data value, so they carry the Data precision (relative 1e-14, no absolute term).
    SUM, AVERAGE and STDEV allow relative 2e-8 plus 1e-12 of the column's largest magnitude, which absorbs
    cancellation and summation order but never lets a tiny column match zero: an all-zero column has scale 0
    and must match exactly. Observed values must be finite real floats; booleans and integers are not accepted.
    """
    if type(observed) is not float or type(wanted) is not float or not math.isfinite(observed) \
            or not math.isfinite(wanted) or not math.isfinite(scale):
        return False
    if derived:
        return math.isclose(observed, wanted, rel_tol=SUMMARY_RELATIVE, abs_tol=SUMMARY_ABSOLUTE * scale)
    return math.isclose(observed, wanted, rel_tol=DIGIT_TOLERANCE, abs_tol=0.0)


def summary_matches(observed, wanted):
    """Strict structural comparison of typed-summary.json; only the float metrics of number columns use tolerance."""
    if not isinstance(observed, dict) or not isinstance(wanted, dict) or observed.keys() != wanted.keys():
        return False
    for key, value in wanted.items():
        if key != 'columns':
            if type(observed[key]) is not type(value) or observed[key] != value:
                return False
            continue
        got = observed[key]
        if not isinstance(got, list) or len(got) != len(value):
            return False
        for have, want in zip(got, value):
            if not isinstance(have, dict) or have.keys() != want.keys():
                return False
            scale = max(abs(want['min']), abs(want['max'])) if want['kind'] == 'number' else 0.0
            for name, expected in want.items():
                actual = have[name]
                if want['kind'] == 'number' and name in DERIVED_METRICS + COPIED_METRICS:
                    if not metric_close(actual, expected, scale, derived=name in DERIVED_METRICS):
                        return False
                elif type(actual) is not type(expected) or actual != expected:
                    return False
    return True


def numeric_columns(table):
    return [i for i, c in enumerate(table['columns']) if c['kind'] == 'number']


def summary(table):
    """Host-side semantic summary: counts, blanks, exact-content digests and numeric statistics."""
    columns = []
    for index, column in enumerate(table['columns']):
        values = [row[index] for row in table['rows']]
        present = [v for v in values if v is not None]
        item = {'name': column['name'], 'kind': column['kind'], 'nullable': column['nullable'],
                'present': len(present), 'missing': len(values) - len(present),
                'valuesSHA256': hashlib.sha256(json.dumps(values, ensure_ascii=True, allow_nan=False,
                                                          separators=(',', ':')).encode('ascii')).hexdigest()}
        if column['kind'] == 'number':
            item.update(sum=math.fsum(present), mean=statistics.fmean(present), min=min(present), max=max(present),
                        stdev=statistics.stdev(present))
        else:
            item.update(distinct=len(set(present)), unique=len(set(present)) == len(present))
        columns.append(item)
    return {'version': SUMMARY_VERSION, 'rows': len(table['rows']), 'nullToken': table['nullToken'],
            'columns': columns,
            'semantics': 'COUNT counts present numbers; MISSING counts blank cells; AVERAGE, MIN, MAX and sample STDEV '
                         'ignore blanks. Text columns never enter numeric arithmetic. Blank, empty text and zero are '
                         'distinct; empty text is rejected.'}
