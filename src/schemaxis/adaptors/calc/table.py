"""Strict typed ingestion for Calc numeric tables: plain decimal cells and XML-safe labels."""
import csv
import io
import math
import re
from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis.tabular import MAX_BYTES, LIMIT, validate

DECIMAL = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?')
RECOVERY = ('use plain ASCII decimal numbers such as 12, -3.5 or 1.2e3 without thousands separators, '
            'units, currency, percent signs or blanks, then retry in a fresh output directory')


def fail(code, message, location='$', *, recovery=None, **observed):
    raise SchemaxisError(Fault(code, message, location, 'pipeline', observed=observed, recovery=recovery))


def unsafe(character):
    """True for text that XLSX/ODS XML cannot represent (surrogates and U+FFFE/U+FFFF)."""
    code = ord(character)
    return 0xD800 <= code <= 0xDFFF or code in (0xFFFE, 0xFFFF)


def check_labels(columns, location='columns'):
    if isinstance(columns, list):
        for index, label in enumerate(columns):
            if isinstance(label, str) and any(unsafe(character) for character in label):
                fail('INVALID_TABLE', 'column label contains text that workbook XML cannot represent '
                     '(unpaired surrogate or noncharacter)', f'{location}[{index}]', column=index,
                     recovery='remove or replace the unsupported character in the label')


def parse_source_csv(payload, *, minimum=2, location='$'):
    """Parse bounded CSV bytes for a new run; every cell must be a plain finite decimal."""
    if len(payload) > MAX_BYTES:
        fail('RESOURCE_LIMIT', 'CSV exceeds 8 MiB', location, maximumBytes=MAX_BYTES)
    try:
        records = list(csv.reader(io.StringIO(payload.decode('utf-8-sig')), strict=True))
    except (UnicodeError, csv.Error) as error:
        fail('INVALID_TABLE', 'CSV must be well-formed UTF-8: ' + str(error), location,
             recovery='save the file as UTF-8 CSV with a header row and numeric records')
    if not records:
        fail('INVALID_TABLE', 'CSV needs a header and numeric rows', location)
    header = records[0]
    check_labels(header)
    rows = []
    for index, record in enumerate(records[1:]):
        if len(record) != len(header):
            fail('INVALID_TABLE', 'CSV record width differs from the header', f'rows[{index}]', record=index + 2,
                 expectedCells=len(header), cells=len(record), source=location,
                 recovery='make every record the same width as the header; remove blank lines')
        row = []
        for column, text in enumerate(record):
            stripped = text.strip(' \t')
            if not DECIMAL.fullmatch(stripped):
                fail('INVALID_TABLE', 'CSV cell is not a plain ASCII decimal number', f'rows[{index}][{column}]',
                     record=index + 2, column=header[column], value=text[:64], source=location, recovery=RECOVERY)
            value = float(stripped)
            if not math.isfinite(value) or abs(value) > LIMIT:
                fail('INVALID_TABLE', 'CSV cell must be finite and within +/-1e100', f'rows[{index}][{column}]',
                     record=index+2, column=header[column], value=text[:64], source=location,
                     recovery='replace the cell with a finite number within +/-1e100, then retry')
            row.append(value)
        rows.append(row)
    return validate(header, rows, minimum=minimum)
