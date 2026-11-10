#!/usr/bin/env python3
"""Independent native acceptance of typed labelled Calc workbooks.

Expectations are hand-stated literals. The cell oracle below reads the native XLSX and
reopened ODS with its own small XML code, not the adaptor's reader, and every tamper case
refreshes the ordinary file hashes so that only a semantic check can reject it.
"""
import argparse
import copy
import hashlib
import json
import math
import re
import shutil
import threading
import unicodedata
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED
from schemaxis.adaptors.calc import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation
from schemaxis.workflow import execute, verify

ROOT = Path(__file__).resolve().parents[1]
MAIN = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
TABLE = '{urn:oasis:names:tc:opendocument:xmlns:table:1.0}'
OFFICE = '{urn:oasis:names:tc:opendocument:xmlns:office:1.0}'
TEXT = '{urn:oasis:names:tc:opendocument:xmlns:text:1.0}'
PARTS = [['Part ID', 'Mass (g)', 'Note', 'Length (mm)'],
         ['00123', 12.5, '=1+2', 100.25], ['00124', None, '+SUM(A1:A2)', 99.5], ['@part-7', 0.0, '-02', 101.0],
         ['café ☕', 13.75, None, 98.75], ['A-9  spaced', 11.0, 'ok', 100.0]]
PARTS_SUMMARY = [['Mass (g)', 4, 37.25, 9.3125, 0.0, 13.75, 6.309301995202533, 1, 'B'],
                 ['Length (mm)', 5, 499.5, 99.9, 98.75, 101.0, 0.8403868156985805, 0, 'D']]
METRICS = ['COUNT', 'SUM', 'AVERAGE', 'MIN', 'MAX', 'STDEV', 'COUNTBLANK']
LONG = 'x' * 1023 + 'é'
EDGE_IDS = ['é', 'é', ' nbsp', ' lead', 'trail ', 'a  b', '_x0041_', '_x005F_', '<a&b>"q\'', '😀 emoji', 'שלום', LONG,
            '=HYPERLINK("http://example.invalid/","x")', '=1+2', '+SUM(A1:A2)', '-02', '@part', 'true', '1e3', '#N/A', 'NA', 'null',
            '​zwsp', '﻿bom', '‮rlo', '\U00010000']
EDGE_NUMBERS = [0.0, 0.1, 1e100, -1.5e-300, 1 / 3, 2.0 ** 52, -7.25, 1e-7] + [float(i) for i in range(18)]


def cell_name(column, row):
    return 'ABCDEFGHIJKLMNOP'[column] + str(row)


def literal_cells(rows):
    return {cell_name(c, r + 1): value for r, row in enumerate(rows) for c, value in enumerate(row) if value is not None}


def unescape(text):
    return re.sub(r'_x([0-9A-Fa-f]{4})_', lambda match: chr(int(match[1], 16)), text)


def reference(text):
    letters, digits = re.fullmatch(r'([A-Z]+)([0-9]+)', text).groups()
    return letters, int(digits)


def xlsx_oracle(path):
    with ZipFile(path) as archive:
        names = archive.namelist()
        assert 'rPh' not in archive.read('xl/sharedStrings.xml').decode() if 'xl/sharedStrings.xml' in names else True
        strings = [unescape(''.join(t.text or '' for t in si.iter(MAIN + 't'))) for si in
                   ET.fromstring(archive.read('xl/sharedStrings.xml')).findall(MAIN + 'si')] if 'xl/sharedStrings.xml' in names else []
        workbook = ET.fromstring(archive.read('xl/workbook.xml'))
        targets = {r.get('Id'): r.get('Target') for r in ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
        sheets = {}
        for sheet in workbook.find(MAIN + 'sheets'):
            root = ET.fromstring(archive.read('xl/' + targets[sheet.get(REL)]))
            cells, formulas = {}, {}
            for cell in root.iter(MAIN + 'c'):
                value, kind, formula = cell.find(MAIN + 'v'), cell.get('t'), cell.find(MAIN + 'f')
                if formula is not None:
                    formulas[cell.get('r')] = formula.text
                if value is None:
                    continue
                cells[cell.get('r')] = strings[int(value.text)] if kind == 's' else float(value.text) if kind in (None, 'n') else ('?', kind)
            sheets[sheet.get('name')] = (cells, formulas, ET.tostring(root).decode())
        return sheets, names


def spaced(element):
    out = element.text or ''
    for child in element:
        out += ' ' * int(child.get(TEXT + 'c', '1')) if child.tag == TEXT + 's' else spaced(child) if child.tag == TEXT + 'span' else '\x00BAD'
        out += child.tail or ''
    return out


def ods_oracle(path):
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read('content.xml'))
        names = archive.namelist()
    sheets = {}
    for table in root.iter(TABLE + 'table'):
        cells, formulas, row_number = {}, {}, 0
        for row in table.findall(TABLE + 'table-row'):
            repeat = int(row.get(TABLE + 'number-rows-repeated', '1'))
            column, found = 0, {}
            for cell in row:
                span = int(cell.get(TABLE + 'number-columns-repeated', '1'))
                kind = cell.get(OFFICE + 'value-type')
                if kind == 'float':
                    value = float(cell.get(OFFICE + 'value'))
                elif kind == 'string':
                    value = '\n'.join(spaced(p) for p in cell.findall(TEXT + 'p'))
                else:
                    value = None if kind is None else ('?', kind)
                for offset in range(span if (value is not None or cell.get(TABLE + 'formula')) and span < 100 else 0):
                    if value is not None:
                        found[column + offset] = value
                    if cell.get(TABLE + 'formula'):
                        found[('f', column + offset)] = cell.get(TABLE + 'formula')
                column += span
            if found:
                for extra in range(repeat):
                    for key, value in found.items():
                        (formulas if isinstance(key, tuple) else cells)[cell_name(key[1] if isinstance(key, tuple) else key, row_number + extra + 1)] = value
            row_number += repeat
        sheets[table.get(TABLE + 'name')] = (cells, formulas, '')
    return sheets, names


def check_workbook(path, rows, summary, *, odf, data_rows=None):
    """Compare every native cell with literal rows; return the number of cells checked."""
    sheets, names = (ods_oracle if odf else xlsx_oracle)(path)
    assert list(sheets) == ['Data', 'Summary'], list(sheets)
    cells, formulas, _ = sheets['Data']
    expected = literal_cells(rows)
    assert set(cells) == set(expected), (path.name, sorted(set(cells) ^ set(expected)))
    assert not formulas, 'formula in Data'
    for ref, value in expected.items():
        got = cells[ref]
        if isinstance(value, str):
            assert type(got) is str and got == value and [ord(c) for c in got] == [ord(c) for c in value], (path.name, ref, got, value)
        else:
            assert type(got) is float and (got == value if value == 0 else math.isclose(got, value, rel_tol=1e-14, abs_tol=0)), (path.name, ref, got, value)
    count, cache, marks = len(rows) - 1, sheets['Summary'][0], sheets['Summary'][1]
    assert not any(isinstance(v, tuple) for v in cache.values()), 'unexpected Summary type'
    for index, line in enumerate(summary):
        row = index + 2
        assert cache.get(f'A{row}') == line[0], (path.name, 'summary label', row)
        column = line[8]
        for offset, metric in enumerate(METRICS):
            ref = 'BCDEFGH'[offset] + str(row)
            wanted = line[1 + offset]
            if metric in ('COUNT', 'COUNTBLANK'):
                assert cache[ref] == wanted, (path.name, ref, cache[ref], wanted)
            else:
                magnitude = max(abs(float(r['ABCDEFGH'.index(column)])) for r in rows[1:] if r['ABCDEFGH'.index(column)] is not None)
                assert math.isclose(cache[ref], wanted, rel_tol=1e-9, abs_tol=1e-12 * magnitude), (path.name, ref, cache[ref], wanted)
            text = marks[ref]
            if odf:
                assert text == f'of:={metric}([$Data.{column}2:.{column}{count + 1}])', (path.name, ref, text)
            else:
                assert text == f'{metric}(Data!{column}2:{column}{count + 1})', (path.name, ref, text)
    assert [cache[c + '1'] for c in 'ABCDEFGH'] == ['Column', *METRICS[:-1], 'MISSING'], 'summary header'
    assert len(marks) == 7 * len(summary) and set(cache) == {f'{c}{r}' for r in range(1, len(summary) + 2) for c in 'ABCDEFGH'}, 'summary cells'
    assert not any(n.endswith('.bin') or 'externalLink' in n or n.startswith(('Basic/', 'Scripts/')) for n in names)
    return len(cells) + len(cache)


def run_case(name, document, directory, executable):
    target = directory / name
    adaptor.run(document, target, executable=executable, timeout=120)
    adaptor.verify(target)
    return target


def refresh_hashes(target):
    """Make the ordinary receipt consistent with whatever bytes are now present."""
    record = json.loads((target / 'verification.json').read_text())
    for artifact in record['artifacts']:
        artifact['sha256'] = hashlib.sha256(Path(artifact['file']).read_bytes()).hexdigest()
    if 'typedSummarySHA256' in record:
        record['typedSummarySHA256'] = hashlib.sha256((target / 'typed-summary.json').read_bytes()).hexdigest()
    if 'requirementsSHA256' in record:
        record['requirementsSHA256'] = hashlib.sha256((target / 'requirements.json').read_bytes()).hexdigest()
    atomic_json(target / 'verification.json', record)


def rewrite(path, member, change):
    with ZipFile(path) as archive:
        members = [(i, archive.read(i.filename)) for i in archive.infolist()]
    with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
        for info, payload in members:
            archive.writestr(info.filename, change(payload.decode('utf-8')).encode('utf-8') if info.filename == member else payload)


def expect_fault(function, code, fragment=None):
    try:
        function()
    except SchemaxisError as error:
        if error.fault.code != code or (fragment and fragment not in error.fault.message):
            raise AssertionError(f'wrong fault {error.fault.code}: {error.fault.message}') from error
        return {'fault': error.fault.code, 'message': error.fault.message[:160], 'location': error.fault.location}
    raise AssertionError('expected a structured fault')


def tamper(target, file, change, fragment, results, label, *, refresh=True, member=None):
    path = target / file
    original = path.read_bytes()
    saved = {n: (target / n).read_bytes() for n in ('verification.json',)}
    try:
        if member:
            rewrite(path, member, change)
        else:
            path.write_bytes(change(original.decode('utf-8')).encode('utf-8'))
        assert path.read_bytes() != original, label + ': tamper did not change bytes'
        if refresh:
            refresh_hashes(target)
        results.append({'case': label, **expect_fault(lambda: adaptor.verify(target), 'VERIFICATION_FAILED', fragment)})
    finally:
        path.write_bytes(original)
        for n, payload in saved.items():
            (target / n).write_bytes(payload)
    adaptor.verify(target)


def cell_xml(refname, xml, replacement):
    updated, count = re.subn(r'<c r="%s"(?:[^>]*/>|[^>]*>.*?</c>)' % refname, replacement, xml, count=1, flags=re.S)
    assert count == 1, refname
    return updated


SQLITE_CSV = b'g0,row_count,total\n\\N,1,3\n-02,1,\\N\n00123,2,10\n=1+2,1,0\n@part-7,1,7\nZurich B,2,-4\n'
SQLITE_ROWS = [['g0', 'row_count', 'total'], [None, 1.0, 3.0], ['-02', 1.0, None], ['00123', 2.0, 10.0], ['=1+2', 1.0, 0.0],
               ['@part-7', 1.0, 7.0], ['Zurich B', 2.0, -4.0]]
# COUNT, SUM, AVERAGE, MIN, MAX, STDEV, MISSING stated by hand (STDEV is the sample deviation).
SQLITE_SUMMARY = [['row_count', 6, 8.0, 4 / 3, 1.0, 2.0, math.sqrt(4 / 15), 0, 'B'],
                  ['total', 5, 16.0, 3.2, -4.0, 10.0, math.sqrt(30.7), 1, 'C']]


def sqlite_workflow(directory, executable, sqlite):
    """SQLite writes summary.csv; Calc binds it as a generic file and re-validates it before native work."""
    work = directory / 'sqlite-inputs'
    work.mkdir()
    for name in ('sqlite-regions.json', 'sqlite-lines.json'):
        shutil.copyfile(ROOT / 'examples/schemaxis/fixtures/calc' / name, work / name)
    workflow = json.loads((ROOT / 'examples/schemaxis/calc-sqlite-typed-workflow.json').read_text())
    tables = workflow['operations'][0]['document']['tables']
    tables[0]['source'], tables[1]['source'] = str(work / 'sqlite-regions.json'), str(work / 'sqlite-lines.json')
    locations = {'calc': executable, 'sqlite': sqlite}

    def calc(document):
        return document['operations'][1]['document']['nodes'][0]['options']

    def faulted(label, mutate, code, fragment=None):
        case = copy.deepcopy(workflow)
        mutate(case)
        out = expect_fault(lambda: execute(case, directory / ('sqlite-bad-' + label), locations=locations, timeout=120), code, fragment)
        assert not list((directory / ('sqlite-bad-' + label)).rglob('analysis.xlsx')), 'workbook published for ' + label
        return {'case': label, **out}

    target = directory / 'sqlite-workflow'
    execute(workflow, target, locations=locations, timeout=120)
    assert verify(target)['verified']
    produced = sorted(target.joinpath('summary').glob('*/attempt-*/summary.csv'))
    assert len(produced) == 1 and produced[0].read_bytes() == SQLITE_CSV, produced
    consumer = sorted(target.joinpath('typed').glob('*/attempt-*/analysis.xlsx'))
    assert len(consumer) == 1
    folder = consumer[0].parent
    assert (folder / 'source.csv').read_bytes() == SQLITE_CSV, 'captured bytes differ from the SQLite file'
    assert (folder / 'data.csv').read_bytes().decode('utf-8') == ('"g0","row_count","total"\n\\N,1.0,3.0\n"-02",1.0,\\N\n"00123",2.0,10.0\n'
                                                                '"=1+2",1.0,0.0\n"@part-7",1.0,7.0\n"Zurich B",2.0,-4.0\n')
    cells = 0
    for extension, odf in (('xlsx', False), ('ods', True)):
        cells += check_workbook(folder / ('analysis.' + extension), SQLITE_ROWS, SQLITE_SUMMARY, odf=odf)
    resumed = execute(workflow, target, locations=locations, timeout=120, resume=True)
    assert all(job.get('reused') for job in resumed['jobs']), resumed['jobs']
    faults = [faulted('binary-sqlite-as-csv', lambda w: calc(w)['file'].update(index=0), 'INVALID_TABLE', 'UTF-8'),
              faulted('text-kind-json', lambda w: calc(w)['file'].update(index=1), 'TYPE_MISMATCH'),
              faulted('index-absent', lambda w: calc(w)['file'].update(index=99), 'INVALID_SELECTION'),
              faulted('producer-absent', lambda w: calc(w)['file'].update({'$artifact': 'nope'}), 'UNAVAILABLE_OPERATION'),
              faulted('header-differs', lambda w: calc(w)['columns'][0].update(name='label'), 'INVALID_TABLE', 'header'),
              faulted('number-kind-for-label', lambda w: calc(w)['columns'][0].update(kind='number'), 'INVALID_TABLE', 'number'),
              faulted('required-column-has-null', lambda w: calc(w)['columns'][2].update(nullable=False), 'INVALID_TABLE', 'null token')]
    empty = copy.deepcopy(workflow)
    regions = json.loads((work / 'sqlite-regions.json').read_text(encoding='utf-8'))
    regions[5]['label'] = ''
    (work / 'sqlite-regions-empty.json').write_text(json.dumps(regions))
    empty['operations'][0]['document']['tables'][0]['source'] = str(work / 'sqlite-regions-empty.json')
    faults.append({'case': 'sqlite-empty-label', **expect_fault(lambda: execute(empty, directory / 'sqlite-bad-empty', locations=locations, timeout=120), 'INVALID_TABLE', 'empty text')})
    lines = work / 'sqlite-lines.json'
    lines.write_text(lines.read_text().replace('"amount": 10', '"amount": 11'))
    rerun = execute(workflow, target, locations=locations, timeout=120, resume=True)
    assert not any(job.get('reused') for job in rerun['jobs']), 'stale reuse after the SQLite source changed'
    assert verify(target)['verified']
    changed = sorted(target.joinpath('summary').glob('*/attempt-*/summary.csv'))[-1].read_bytes()
    assert changed == SQLITE_CSV.replace(b'00123,2,10', b'00123,2,11') and b'00123,2,11' not in SQLITE_CSV, changed
    return {'verified': True, 'cells': cells, 'capturedBytesExact': True, 'reusedOnResume': True, 'changedSourceReran': True, 'faults': faults,
            'scope': 'Real SQLite summary.csv bound as a generic file artifact; Calc validates the CSV before native work. SQLite text is printable ASCII only; a SQLite text value equal to the null token is indistinguishable from NULL in its CSV.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True, type=Path)
    parser.add_argument('--output-directory', required=True, type=Path)
    parser.add_argument('--sqlite', type=Path, help='SQLite executable; runs the real SQLite -> Calc typed CSV file-artifact workflow')
    parser.add_argument('--legacy-control', type=Path, action='append', default=[],
                        help='retained numeric run produced before this change; verified read-only (repeatable)')
    args = parser.parse_args()
    directory = args.output_directory.absolute()
    directory.mkdir(parents=True, exist_ok=False)
    executable = str(args.executable.absolute())
    parts = json.loads((ROOT / 'examples/schemaxis/calc-typed-parts.json').read_text())
    report = {'verified': False, 'provider': 'calc', 'cases': [], 'tamper': [], 'faults': [], 'workflow': {}}
    checked = 0

    # 1. Declared rows with leading zeros, literal formulas, Unicode, blank and zero.
    target = run_case('parts', parts, directory, executable)
    for extension, odf in (('xlsx', False), ('ods', True)):
        checked += check_workbook(target / ('analysis.' + extension), PARTS, PARTS_SUMMARY, odf=odf)
    summary = json.loads((target / 'typed-summary.json').read_text())
    assert [c['missing'] for c in summary['columns']] == [0, 1, 1, 0] and summary['columns'][0]['distinct'] == 5
    assert (target / 'data.csv').read_text(encoding='utf-8') == (ROOT / 'examples/schemaxis/fixtures/calc/typed-parts.csv').read_text(encoding='utf-8')
    metadata = json.loads((target / 'data.csv.metadata.json').read_text())
    assert metadata['identity'] == {'kind': 'table', 'format': 'schemaxis.calc.typed-csv/1', 'nullToken': '\\N'} and metadata['losses'], metadata
    assert 'identity' not in json.loads((directory / 'parts' / 'analysis.xlsx.metadata.json').read_text())
    runtime = json.loads((target / 'runtime.json').read_text())['runtime']
    assert runtime.startswith('LibreOffice 26.8.'), runtime
    report['cases'].append({'case': 'parts', 'verified': True, 'runtime': runtime})
    assessment = json.loads((target / 'requirements.json').read_text())
    assert assessment['passed'] and assessment['formats']['xlsx']['checks'][1]['value'] == 1

    # 2. The same table from a captured typed CSV.
    csv_document = json.loads((ROOT / 'examples/schemaxis/calc-typed-csv.json').read_text())
    work = directory / 'inputs'
    work.mkdir()
    source = work / 'typed-parts.csv'
    shutil.copyfile(ROOT / 'examples/schemaxis/fixtures/calc/typed-parts.csv', source)
    csv_document['nodes'][0]['options']['file'] = str(source)
    csv_target = run_case('csv', csv_document, directory, executable)
    for extension, odf in (('xlsx', False), ('ods', True)):
        checked += check_workbook(csv_target / ('analysis.' + extension), PARTS, PARTS_SUMMARY, odf=odf)
    assert (csv_target / 'source.csv').read_bytes() == source.read_bytes()
    report['cases'].append({'case': 'csv', 'verified': True})

    # 3. Unicode and number edge cases through both native conversions.
    columns = [{'name': 'ID', 'kind': 'text'}, {'name': 'x', 'kind': 'number'}]
    rows = [[text, EDGE_NUMBERS[i % len(EDGE_NUMBERS)]] for i, text in enumerate(EDGE_IDS)]
    edge = {'version': 'schemaxis.calc/1', 'nodes': [{'id': 'edge', 'filter': 'fromTypedRows', 'options': {'columns': columns, 'rows': rows}}]}
    target = run_case('edge', edge, directory, executable)
    literal = [['ID', 'x']] + [list(r) for r in rows]
    xs = [r[1] for r in rows]
    mean = math.fsum(xs) / len(xs)
    stdev = math.sqrt(math.fsum((v - mean) ** 2 for v in xs) / (len(xs) - 1))
    for extension, odf in (('xlsx', False), ('ods', True)):
        checked += check_workbook(target / ('analysis.' + extension), literal,
                                  [['x', len(xs), math.fsum(xs), mean, min(xs), max(xs), stdev, 0, 'B']], odf=odf)
    assert unicodedata.normalize('NFC', 'é') != 'é'
    report['cases'].append({'case': 'edge', 'verified': True, 'texts': len(EDGE_IDS), 'longestCharacters': len(LONG)})

    # 4. Blank positions: first, adjacent, trailing and a fully populated neighbour row.
    blank_columns = [{'name': 'ID', 'kind': 'text'}, {'name': 'a', 'kind': 'number', 'nullable': True},
                     {'name': 'b', 'kind': 'number', 'nullable': True}, {'name': 'note', 'kind': 'text', 'nullable': True}]
    blank_rows = [['r1', None, 1.0, 'n'], ['r2', None, None, 'n'], ['r3', 2.0, 0.0, None], ['r4', 3.0, None, None], ['r5', 0.0, 4.0, None]]
    blanks = {'version': 'schemaxis.calc/1', 'nodes': [{'id': 'blanks', 'filter': 'fromTypedRows', 'options': {'columns': blank_columns, 'rows': blank_rows}}]}
    target = run_case('blanks', blanks, directory, executable)
    literal = [['ID', 'a', 'b', 'note']] + blank_rows
    summary_lines = [['a', 3, 5.0, 5 / 3, 0.0, 3.0, math.sqrt(((0 - 5 / 3) ** 2 + (2 - 5 / 3) ** 2 + (3 - 5 / 3) ** 2) / 2), 2, 'B'],
                     ['b', 3, 5.0, 5 / 3, 0.0, 4.0, math.sqrt(((1 - 5 / 3) ** 2 + (0 - 5 / 3) ** 2 + (4 - 5 / 3) ** 2) / 2), 2, 'C']]
    for extension, odf in (('xlsx', False), ('ods', True)):
        checked += check_workbook(target / ('analysis.' + extension), literal, summary_lines, odf=odf)
    report['cases'].append({'case': 'blanks', 'verified': True})

    # 4b. Tiny-magnitude, all-zero and mixed-sign columns: Summary is checked against the column's own scale.
    tiny_columns = [{'name': 'ID', 'kind': 'text'}, {'name': 'x', 'kind': 'number', 'nullable': True},
                    {'name': 'z', 'kind': 'number'}, {'name': 'm', 'kind': 'number'}]
    tiny_rows = [['t1', 1e-12, 0.0, 4e-12], ['t2', 3e-12, 0.0, -4e-12], ['t3', None, 0.0, 2.5e-12], ['t4', 2e-12, 0.0, -1e-12]]
    tiny_doc = {'version': 'schemaxis.calc/1', 'nodes': [{'id': 'tiny', 'filter': 'fromTypedRows', 'options': {'columns': tiny_columns, 'rows': tiny_rows}}]}
    tiny_target = run_case('tiny', tiny_doc, directory, executable)
    tiny_summary = [['x', 3, 6e-12, 2e-12, 1e-12, 3e-12, 1e-12, 1, 'B'],
                    ['z', 4, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 'C'],
                    ['m', 4, 1.5e-12, 3.75e-13, -4e-12, 4e-12, math.sqrt(38.6875 / 3) * 1e-12, 0, 'D']]
    for extension, odf in (('xlsx', False), ('ods', True)):
        checked += check_workbook(tiny_target / ('analysis.' + extension), [['ID', 'x', 'z', 'm']] + tiny_rows, tiny_summary, odf=odf)
    report['cases'].append({'case': 'tiny', 'verified': True, 'columns': ['tiny positive with a blank', 'all zero', 'mixed sign']})

    # 5. Native counterexamples with refreshed ordinary hashes still fail the semantic checks.
    base = directory / 'parts'
    sheet1, sheet2 = 'xl/worksheets/sheet1.xml', 'xl/worksheets/sheet2.xml'
    results = report['tamper']
    tamper(base, 'analysis.xlsx', lambda x: cell_xml('A2', x, '<c r="A2"><v>123</v></c>'), 'typed cell differs', results, 'xlsx id coerced to number', member=sheet1)
    tamper(base, 'analysis.xlsx', lambda x: cell_xml('A2', x, '<c r="A2"><f>1+2</f><v>3</v></c>'), 'typed cell differs', results, 'xlsx text replaced by a formula', member=sheet1)
    tamper(base, 'analysis.xlsx', lambda x: cell_xml('C2', x, '<c r="C2"><f>1+2</f><v>3</v></c>'), 'typed cell differs', results, 'xlsx formula-looking note evaluated', member=sheet1)
    tamper(base, 'analysis.xlsx', lambda x: x.replace('<c r="C3"', '<c r="B3"><v>0</v></c><c r="C3"', 1), 'typed cell differs', results, 'xlsx blank became zero', member=sheet1)
    tamper(base, 'analysis.xlsx', lambda x: cell_xml('B4', x, ''), 'typed cell differs', results, 'xlsx zero became blank', member=sheet1)
    tamper(base, 'analysis.xlsx', lambda x: re.sub(r'(<row r="2".*?)</row>', r'\1<c r="E2"><v>1</v></c></row>', x, count=1, flags=re.S), 'worksheet shape', results, 'xlsx extra column', member=sheet1)
    tamper(base, 'analysis.xlsx', lambda x: cell_xml('D2', x, ''), 'typed cell differs', results, 'xlsx missing cell', member=sheet1)
    tamper(base, 'analysis.xlsx', lambda x: x.replace('<v>12.5</v>', '<v>12.500000001</v>'), 'typed cell differs', results, 'xlsx measurement drift', member=sheet1)
    tamper(base, 'analysis.xlsx', lambda x: x.replace('</sheetData>', '</sheetData><hyperlinks><hyperlink ref="A2" location="Summary!A1"/></hyperlinks>', 1), 'links', results, 'xlsx hyperlink', member=sheet1)
    tamper(base, 'analysis.xlsx', lambda x: x.replace('SUM(', 'MAX(', 1), 'spreadsheet formula differs', results, 'xlsx summary formula changed', member=sheet2)
    tamper(base, 'analysis.xlsx', lambda x: x.replace('café', 'café'), 'typed cell differs', results, 'xlsx NFC became NFD', member='xl/sharedStrings.xml')
    ods_string = '<table:table-cell office:value-type="string" calcext:value-type="string"><text:p>%s</text:p></table:table-cell>'
    tamper(base, 'analysis.ods', lambda x: x.replace(ods_string % '00123', '<table:table-cell office:value-type="float" office:value="123" calcext:value-type="float"><text:p>123</text:p></table:table-cell>'),
           'typed cell differs', results, 'ods id coerced to number', member='content.xml')
    tamper(base, 'analysis.ods', lambda x: x.replace(ods_string % '=1+2', '<table:table-cell table:formula="of:=1+2" office:value-type="float" office:value="3" calcext:value-type="float"><text:p>3</text:p></table:table-cell>'),
           'typed cell differs', results, 'ods note evaluated', member='content.xml')
    tamper(base, 'analysis.ods', lambda x: x.replace('<text:p>=1+2</text:p>', '<text:p><text:a xlink:href="http://example.invalid/">=1+2</text:a></text:p>'),
           'hyperlink', results, 'ods hyperlink', member='content.xml')
    tamper(base, 'analysis.ods', lambda x: x.replace('café', 'café'), 'typed cell differs', results, 'ods NFC became NFD', member='content.xml')
    tamper(base, 'data.csv', lambda x: x.replace('\\N', '""', 1), 'published typed CSV', results, 'csv null replaced by empty text')
    tamper(base, 'data.csv', lambda x: x.replace('\\N', '0.0', 1), 'published typed CSV', results, 'csv null replaced by zero')
    tamper(base, 'data.csv', lambda x: x.replace('"00123"', '"0123"'), 'published typed CSV differs', results, 'csv id lost leading zero')
    tamper(base, 'typed-summary.json', lambda x: x.replace('"missing": 1', '"missing": 0', 1), 'typed summary differs', results, 'typed summary altered')
    tamper(base, 'analysis.xlsx', lambda x: x.replace('</cp:coreProperties>', ' </cp:coreProperties>'), 'digest differs', results, 'stale ordinary digest (semantics unchanged)', refresh=False, member='docProps/core.xml')
    # Tiny-column forgeries with ordinary hashes refreshed: native caches and the typed summary JSON.
    def xlsx_cache(ref, value):
        return lambda x: re.sub(r'(<c r="%s"[^>]*>(?:<f[^>]*>[^<]*</f>)?<v>)[^<]*(</v>)' % ref, lambda m: m[1] + value + m[2], x, count=1)

    def ods_cache(function, value):
        return lambda x: re.sub(r'(<table:table-cell table:formula="of:=%s\(\[\$Data\.%s[^"]*"[^>]*?office:value=")[^"]*(")' % function,
                                lambda m: m[1] + value + m[2], x, count=1)

    def summary_json(column, key, value):
        def change(x):
            data = json.loads(x)
            data['columns'][column][key] = value
            return json.dumps(data, indent=1, sort_keys=True) + '\n'
        return change
    for label, ref, value in (('sum zero', 'C2', '0'), ('stdev 1e-9', 'G2', '1E-9'), ('all-zero column stdev', 'G3', '1E-300'),
                              ('mixed-sign sum zero', 'C4', '0'), ('fractional count', 'B2', '3.0000001'), ('min zero', 'E2', '0')):
        tamper(tiny_target, 'analysis.xlsx', xlsx_cache(ref, value), 'typed cell differs', results, 'tiny xlsx cache: ' + label, member=sheet2)
    for label, function, value in (('sum zero', ('SUM', 'B'), '0'), ('stdev 1e-9', ('STDEV', 'B'), '1E-9'),
                                   ('all-zero column stdev', ('STDEV', 'C'), '1E-300'), ('mixed-sign sum zero', ('SUM', 'D'), '0')):
        tamper(tiny_target, 'analysis.ods', ods_cache(function, value), 'typed cell differs', results, 'tiny ods cache: ' + label, member='content.xml')
    for label, column, key, value in (('sum zero', 0, 'sum', 0.0), ('stdev 1e-9', 0, 'stdev', 1e-9), ('all-zero column stdev', 1, 'stdev', 1e-300),
                                      ('mixed-sign sum zero', 2, 'sum', 0.0), ('fractional present', 0, 'present', 3.0000001)):
        tamper(tiny_target, 'typed-summary.json', summary_json(column + 1, key, value),
               'typed summary differs', results, 'tiny typed summary: ' + label)
    for label, payload in (('truncated archive', None), ('not an archive', b'not a workbook')):
        path, saved = base / 'analysis.xlsx', (base / 'analysis.xlsx').read_bytes()
        record = (base / 'verification.json').read_bytes()
        try:
            path.write_bytes(saved[:len(saved) // 2] if payload is None else payload)
            refresh_hashes(base)
            results.append({'case': 'corrupted xlsx: ' + label, **expect_fault(lambda: adaptor.verify(base), 'VERIFICATION_FAILED', 'malformed workbook evidence')})
        finally:
            path.write_bytes(saved)
            (base / 'verification.json').write_bytes(record)
    adaptor.verify(base)
    original = (base / 'analysis.ods').read_bytes()
    try:
        (base / 'analysis.ods').unlink()
        results.append({'case': 'publication removed', **expect_fault(lambda: adaptor.verify(base), 'VERIFICATION_FAILED')})
    finally:
        (base / 'analysis.ods').write_bytes(original)
    authored_path, authored_bytes = base / 'authored.json', (base / 'authored.json').read_bytes()
    try:
        forged = json.loads(authored_bytes)
        forged['nodes'][0]['options']['nullToken'] = 'NA'
        atomic_json(authored_path, forged)
        results.append({'case': 'authored null token changed', **expect_fault(lambda: adaptor.verify(base), 'VERIFICATION_FAILED', 'plan differs')})
    finally:
        authored_path.write_bytes(authored_bytes)
    csv_run = directory / 'csv'
    captured = (csv_run / 'source.csv').read_bytes()
    try:
        (csv_run / 'source.csv').write_bytes(captured.replace(b'"00123"', b'"00124"'))
        results.append({'case': 'captured CSV altered', **expect_fault(lambda: adaptor.verify(csv_run), 'VERIFICATION_FAILED', 'captured CSV differs')})
    finally:
        (csv_run / 'source.csv').write_bytes(captured)
    source.write_bytes(b'overwritten after the run')
    adaptor.verify(csv_run)  # the retained capture, not the changed original, is the authority
    shutil.copyfile(ROOT / 'examples/schemaxis/fixtures/calc/typed-parts.csv', source)
    assert adaptor.reusableInputs(csv_document) == {str(source): hashlib.sha256(source.read_bytes()).hexdigest()}

    # 6. Bad inputs fail before native work with exact located faults.
    faults = report['faults']
    bad_csv = {'header': (b'"Part ID","Mass","Note","Length (mm)"\n"a",1,"n",1\n"b",2,"m",2\n', 'columns[1].name'),
               'null token in required column': (b'"Part ID","Mass (g)","Note","Length (mm)"\n\\N,1,"n",1\n"b",2,"m",2\n', 'rows[0][0]'),
               'empty text': (b'"Part ID","Mass (g)","Note","Length (mm)"\n"a",1,"",1\n"b",2,"m",2\n', 'rows[0][2]'),
               'padded number': (b'"Part ID","Mass (g)","Note","Length (mm)"\n"a", 1,"n",1\n"b",2,"m",2\n', 'rows[0][1]'),
               'corrupt UTF-8': (b'"Part ID","Mass (g)","Note","Length (mm)"\n"\xff",1,"n",1\n"b",2,"m",2\n', None)}
    for label, (payload, location) in bad_csv.items():
        broken = work / 'broken.csv'
        broken.write_bytes(payload)
        case = copy.deepcopy(csv_document)
        case['nodes'][0]['options']['file'] = str(broken)
        found = expect_fault(lambda: adaptor.run(case, directory / ('bad-' + re.sub(r'\W+', '-', label)), executable=executable, timeout=60), 'INVALID_TABLE')
        assert location is None or found['location'] == location, (label, found)
        faults.append({'case': label, **found})
    for label, code, mutate in [('boolean number', 'INVALID_ARGUMENT', lambda o: o['rows'][1].__setitem__(1, True)),
                                ('numeric string', 'INVALID_TABLE', lambda o: o['rows'][1].__setitem__(1, '12')),
                                ('coerced identifier', 'INVALID_TABLE', lambda o: o['rows'][1].__setitem__(0, 123)),
                                ('formula option', 'UNKNOWN_ARGUMENT', lambda o: o.__setitem__('formula', '=A1')),
                                ('unit column key', 'UNKNOWN_ARGUMENT', lambda o: o['columns'][1].__setitem__('unit', 'g')),
                                ('date kind', 'INVALID_ARGUMENT', lambda o: o['columns'][0].__setitem__('kind', 'date'))]:
        case = copy.deepcopy(parts)
        mutate(case['nodes'][0]['options'])
        faults.append({'case': label, **expect_fault(lambda: adaptor.plan(case), code)})
    assert not any((directory / ('bad-' + re.sub(r'\W+', '-', k))).joinpath('analysis.xlsx').exists() for k in bad_csv)

    # 7. Timeout and pre-launch cancellation.
    faults.append({'case': 'timeout', **expect_fault(lambda: adaptor.run(parts, directory / 'timeout', executable=executable, timeout=1e-9), 'RUNNER_TIMED_OUT')})
    cancel = threading.Event()
    cancel.set()
    with allocation({'threads': 1, 'ranks': 1}, cancel):
        faults.append({'case': 'cancelled', **expect_fault(lambda: adaptor.run(parts, directory / 'cancelled', executable=executable, timeout=60), 'RUNNER_CANCELLED')})

    # 8. Typed producer handoff, reuse, and invalidation by changed input.
    workflow = json.loads((ROOT / 'examples/schemaxis/calc-typed-handoff.json').read_text())
    target = directory / 'workflow'
    execute(workflow, target, locations={'calc': executable}, timeout=120)
    verify(target)
    resumed = execute(workflow, target, locations={'calc': executable}, timeout=120, resume=True)
    assert sum(bool(job.get('reused')) for job in resumed['jobs']) == 2, resumed['jobs']
    changed = copy.deepcopy(workflow)
    changed['operations'][0]['document']['nodes'][0]['options']['rows'][1][0] = '00199'
    report['workflow']['changedDocumentResume'] = expect_fault(lambda: execute(changed, target, locations={'calc': executable}, timeout=120, resume=True), 'RESUME_MISMATCH')
    fresh = directory / 'workflow-changed'
    execute(changed, fresh, locations={'calc': executable}, timeout=120)
    verify(fresh)
    consumer = [p for p in sorted(fresh.rglob('data.csv')) if 'consumer' in str(p)][0].read_text(encoding='utf-8')
    before = [p for p in sorted(target.rglob('data.csv')) if 'consumer' in str(p)][0].read_text(encoding='utf-8')
    assert '"00199"' in consumer and '"00124"' not in consumer and '"00124"' in before and '"00199"' not in before
    verify(target)
    standalone = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'file', 'document': csv_document}]}
    target = directory / 'workflow-file'
    execute(standalone, target, locations={'calc': executable}, timeout=120)
    first = execute(standalone, target, locations={'calc': executable}, timeout=120, resume=True)
    assert all(job.get('reused') for job in first['jobs'])
    source.write_bytes(source.read_bytes().replace(b'"00123"', b'"00133"'))
    rerun = execute(standalone, target, locations={'calc': executable}, timeout=120, resume=True)
    assert not any(job.get('reused') for job in rerun['jobs']), 'stale reuse after the CSV bytes changed'
    verify(target)
    source.write_bytes(source.read_bytes().replace(b'"Mass (g)"', b'"Mass"'))
    report['workflow']['changedHeaderResume'] = expect_fault(lambda: execute(standalone, target, locations={'calc': executable}, timeout=120, resume=True), 'INVALID_TABLE')
    report['workflow'].update(handoffReusedJobs=2, changedBytesReran=True, changedIdentifierDigestsDiffer=True)
    shutil.copyfile(ROOT / 'examples/schemaxis/fixtures/calc/typed-parts.csv', source)

    # 9b. Real SQLite producer -> Calc typed CSV through a generic `file` artifact.
    if args.sqlite:
        report['sqliteWorkflow'] = sqlite_workflow(directory, executable, str(args.sqlite.absolute()))
        checked += report['sqliteWorkflow'].pop('cells')
    else:
        report['sqliteWorkflow'] = {'skipped': 'no --sqlite executable supplied'}

    # 9. Numeric operations keep their grammar, summary width and receipts.
    numeric = json.loads((ROOT / 'examples/schemaxis/calc-balance.json').read_text())
    target = run_case('numeric', numeric, directory, executable)
    assert not (target / 'typed-summary.json').exists() and 'typedSummarySHA256' not in json.loads((target / 'verification.json').read_text())
    sheets, _ = xlsx_oracle(target / 'analysis.xlsx')
    assert sheets['Summary'][0]['C2'] == 150 and sheets['Summary'][0]['C3'] == 150 and 'H1' not in sheets['Summary'][0]
    report['numeric'] = {'verified': True, 'summaryColumns': 7}
    for control in (path.absolute() for path in args.legacy_control):
        before = {str(p.relative_to(control)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(control.rglob('*')) if p.is_file()}
        modes = {p: p.stat().st_mode for p in [control, *control.rglob('*')]}
        for p in modes:
            p.chmod(modes[p] & ~0o222)
        try:
            retained = adaptor.verify(control)
        finally:
            for p, mode in modes.items():
                p.chmod(mode)
        after = {str(p.relative_to(control)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(control.rglob('*')) if p.is_file()}
        assert before == after, 'legacy control bytes changed'
        report.setdefault('legacyControls', []).append({'name': control.name, 'verified': retained['verified'], 'readOnly': True,
                                                        'files': len(before), 'runtime': retained['runtime']})
    report.update(verified=True, cellsChecked=checked, runtime=runtime,
                  scope='Typed labelled tables through native LibreOffice ODS->XLSX->ODS: every native cell type/value read by an independent oracle, formula absence, blanks/zero/text, Unicode, tamper with refreshed hashes, bad inputs, timeout/cancellation, typed handoff, reuse and invalidation. No Excel or Google Sheets execution; no domain correctness claim.')
    atomic_json(directory / 'acceptance.json', report)
    print(json.dumps({k: report[k] for k in ('verified', 'runtime', 'cellsChecked')}, indent=2))


if __name__ == '__main__':
    main()
