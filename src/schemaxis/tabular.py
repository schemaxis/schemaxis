# Copyright (C) 2026 David L F Gaden
"""Bounded numeric tables exchanged across analysis and spreadsheet applications."""
import csv
import io
import math
from pathlib import Path
from .errors import fail

MAX_ROWS = 10000
MAX_BYTES = 8 * 1024 * 1024
LIMIT = 1e100


def numeric(value, location='$'):
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > LIMIT:
        fail('INVALID_TABLE', 'table values must be finite numbers within +/-1e100', location)
    return float(value)


def validate(columns, rows, *, minimum=1):
    if (not isinstance(columns, list) or not 1 <= len(columns) <= 64 or
            any(not isinstance(c, str) or not c or len(c) > 128 or any(ord(ch) < 32 for ch in c) for c in columns) or
            len(set(columns)) != len(columns)):
        fail('INVALID_TABLE', 'table column names must be nonempty, distinct text without control characters')
    if not isinstance(rows, list) or not minimum <= len(rows) <= MAX_ROWS:
        fail('INVALID_TABLE', f'table must contain {minimum} to {MAX_ROWS} rows')
    result = []
    for index, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != len(columns):
            fail('INVALID_TABLE', 'table row width differs from columns', str(index))
        result.append([numeric(value, f'rows[{index}][{col}]') for col, value in enumerate(row)])
    return {'columns': list(columns), 'rows': result}


def read_csv(path, *, minimum=1):
    path = Path(path)
    with path.open('rb') as stream: payload = stream.read(MAX_BYTES+1)
    if len(payload) > MAX_BYTES: fail('RESOURCE_LIMIT', 'CSV exceeds 8 MiB', str(path))
    return parse_csv(payload, minimum=minimum, location=str(path))


def parse_csv(payload, *, minimum=1, location='$'):
    """Parse the exact bounded bytes whose publication digest was verified."""
    if len(payload) > MAX_BYTES: fail('RESOURCE_LIMIT', 'CSV exceeds 8 MiB', location)
    try:
        rows = list(csv.reader(io.StringIO(payload.decode('utf-8-sig')), strict=True))
        if not rows: fail('INVALID_TABLE', 'CSV needs a header and numeric rows', location)
        return validate(rows[0], [[float(value) for value in row] for row in rows[1:]], minimum=minimum)
    except (UnicodeError, ValueError, csv.Error) as error:
        fail('INVALID_TABLE', 'CSV must have a UTF-8 header and finite numeric cells: '+str(error), location)


def write_csv(path, table):
    table = validate(table['columns'], table['rows'])
    with Path(path).open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream, lineterminator='\n')
        writer.writerow(table['columns'])
        writer.writerows([[format(value, '.17g') for value in row] for row in table['rows']])
    if Path(path).stat().st_size > MAX_BYTES:
        fail('RESOURCE_LIMIT', 'numeric CSV publication exceeds 8 MiB', str(path))


def close(actual, expected, *, rel=2e-8, absolute=2e-9):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and actual.keys() == expected.keys() and all(close(actual[k], v, rel=rel, absolute=absolute) for k,v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual)==len(expected) and all(close(a,b,rel=rel,absolute=absolute) for a,b in zip(actual,expected))
    if type(expected) in (int,float):
        return type(actual) in (int,float) and math.isfinite(actual) and math.isclose(actual, expected, rel_tol=rel, abs_tol=absolute)
    return type(actual) is type(expected) and actual==expected
