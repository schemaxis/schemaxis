"""Typed labelled Calc tables: closed grammar, honest missingness and independent workbook readback.

Expectations are stated as literals. The workbook fixtures below are assembled by hand from the
public ODF/OOXML element names so they share no code with the reader under test.
"""
import copy
import json
import os
from pathlib import Path
import random
import re
import tempfile
import unittest
from unittest.mock import patch
from zipfile import BadZipFile, ZipFile, ZIP_DEFLATED
from schemaxis.adaptors.calc import adaptor, requirements, typed_table, typed_workbook
from schemaxis.core.faults import SchemaxisError

COLUMNS = [{'name': 'Part ID', 'kind': 'text'}, {'name': 'Mass (g)', 'kind': 'number', 'nullable': True},
           {'name': 'Note', 'kind': 'text', 'nullable': True}]
ROWS = [['00123', 1.5, '=1+2'], ['café', None, '+SUM(A1:A2)'], ['@part', 0, '-02'], ['N° 7  b', 4.5, None]]


def document(columns=COLUMNS, rows=ROWS, **options):
    return {'version': 'schemaxis.calc/1', 'nodes': [{'id': 'parts', 'filter': 'fromTypedRows', 'options': {
        'columns': copy.deepcopy(columns), 'rows': copy.deepcopy(rows), **options}}]}


def csv_document(path, columns=COLUMNS, **options):
    return {'version': 'schemaxis.calc/1', 'nodes': [{'id': 'parts', 'filter': 'readTypedCSV', 'options': {
        'file': str(path), 'columns': copy.deepcopy(columns), **options}}]}


def table():
    return adaptor.plan(document())['nodes'][0]['options']


def typed():
    options = table()
    return typed_table.validate(options['columns'], options['rows'], options['nullToken'])


class Base(unittest.TestCase):
    def fault(self, call, *args, **kwargs):
        with self.assertRaises(SchemaxisError) as caught:
            call(*args, **kwargs)
        return caught.exception.fault


class TypedRowsGrammarTests(Base):
    def test_valid_table_is_planned_without_mutating_the_authored_input(self):
        authored = document()
        before = copy.deepcopy(authored)
        planned = adaptor.plan(authored)
        self.assertEqual(authored, before)
        options = planned['nodes'][0]['options']
        self.assertEqual(options['nullToken'], '\\N')
        self.assertEqual([c['nullable'] for c in options['columns']], [False, True, True])
        self.assertEqual(options['rows'][1], ['café', None, '+SUM(A1:A2)'])
        planned['nodes'][0]['options']['rows'][0][0] = 'changed'
        self.assertEqual(authored, before)

    def test_exact_located_faults_for_invalid_cells(self):
        cases = [('boolean as number', lambda r: r[0].__setitem__(1, True), 'INVALID_ARGUMENT', 'rows[0][1]'),
                 ('boolean as text', lambda r: r[0].__setitem__(0, False), 'INVALID_ARGUMENT', 'rows[0][0]'),
                 ('text in number column', lambda r: r[2].__setitem__(1, '5'), 'INVALID_TABLE', 'rows[2][1]'),
                 ('coerced identifier', lambda r: r[1].__setitem__(0, 123), 'INVALID_TABLE', 'rows[1][0]'),
                 ('empty text', lambda r: r[1].__setitem__(2, ''), 'INVALID_TABLE', 'rows[1][2]'),
                 ('null in required column', lambda r: r[3].__setitem__(0, None), 'INVALID_TABLE', 'rows[3][0]'),
                 ('control character', lambda r: r[0].__setitem__(2, 'a\tb'), 'INVALID_TABLE', 'rows[0][2]'),
                 ('line separator', lambda r: r[0].__setitem__(2, 'a\u2028b'), 'INVALID_TABLE', 'rows[0][2]'),
                 ('lone surrogate', lambda r: r[0].__setitem__(2, 'a\ud800'), 'INVALID_TABLE', 'rows[0][2]'),
                 ('noncharacter', lambda r: r[0].__setitem__(2, 'a\uffff'), 'INVALID_TABLE', 'rows[0][2]'),
                 ('nonfinite', lambda r: r[0].__setitem__(1, float('inf')), 'INVALID_ARGUMENT', 'rows[0][1]'),
                 ('too large', lambda r: r[0].__setitem__(1, 1e101), 'INVALID_ARGUMENT', 'rows[0][1]'),
                 ('inexact integer', lambda r: r[0].__setitem__(1, 2 ** 53 + 1), 'INVALID_TABLE', 'rows[0][1]'),
                 ('object cell', lambda r: r[0].__setitem__(1, {'v': 1}), 'INVALID_ARGUMENT', 'rows[0][1]'),
                 ('short record', lambda r: r.__setitem__(2, ['x', 1]), 'INVALID_TABLE', 'rows[2]'),
                 ('token collision', lambda r: r[0].__setitem__(2, '\\N'), 'INVALID_TABLE', 'rows[0][2]'),
                 ('null in first column of a record', lambda r: r.__setitem__(3, [None, None, None]), 'INVALID_TABLE', 'rows[3][0]')]
        for name, mutate, code, location in cases:
            with self.subTest(name):
                authored = document()
                mutate(authored['nodes'][0]['options']['rows'])
                fault = self.fault(adaptor.plan, authored)
                self.assertEqual(fault.code, code)
                self.assertTrue(fault.location.endswith(location), fault.location)
                if code == 'INVALID_TABLE':
                    self.assertTrue(fault.recovery)

    def test_closed_declaration_grammar(self):
        for name, mutate in [('unknown column key', lambda o: o['columns'][0].update(unit='kg')),
                             ('unknown option', lambda o: o.update(locale='fr')),
                             ('date kind', lambda o: o['columns'][0].update(kind='date')),
                             ('boolean kind', lambda o: o['columns'][0].update(kind='boolean')),
                             ('missing kind', lambda o: o['columns'][0].pop('kind')),
                             ('string nullable', lambda o: o['columns'][1].update(nullable='yes')),
                             ('formula option', lambda o: o.update(formula='=A1'))]:
            with self.subTest(name):
                authored = document()
                mutate(authored['nodes'][0]['options'])
                self.assertIn(self.fault(adaptor.plan, authored).code, ('UNKNOWN_ARGUMENT', 'INVALID_ARGUMENT', 'MISSING_ARGUMENT'))
        authored = document()
        authored['nodes'][0]['unexpected'] = 1
        self.assertEqual(self.fault(adaptor.plan, authored).code, 'UNKNOWN_ARGUMENT')

    def test_column_and_token_rules(self):
        duplicate = document(columns=[COLUMNS[0], {**COLUMNS[1], 'name': 'Part ID'}, COLUMNS[2]])
        self.assertEqual(self.fault(adaptor.plan, duplicate).location, 'columns[1].name')
        named_like_token = document(columns=[{**COLUMNS[0], 'name': '\\N'}, *COLUMNS[1:]])
        self.assertEqual(self.fault(adaptor.plan, named_like_token).location, 'columns[0].name')
        for token in ('12', '-1e3', 'a,b', 'a b', '"q"', 'tab\t', 'x' * 17):
            with self.subTest(token=token):
                authored = document(nullToken=token)
                self.assertIn(self.fault(adaptor.plan, authored).code, ('INVALID_TABLE', 'INVALID_ARGUMENT'))
        alternative = adaptor.plan(document(rows=[['a', 1, 'NA'], ['b', 2, None]], nullToken='-'))
        self.assertEqual(alternative['nodes'][0]['options']['nullToken'], '-')
        self.assertEqual(self.fault(adaptor.plan, document(rows=[['a', 1, '-'], ['b', 2, None]], nullToken='-')).location, 'rows[0][2]')

    def test_leading_formula_characters_are_ordinary_text_labels_and_cells(self):
        labels = [{'name': '=ID', 'kind': 'text'}, {'name': '+mass', 'kind': 'number'}, {'name': '@note', 'kind': 'text', 'nullable': True}]
        rows = [['=1+2', 1, '-02'], ['+SUM(A1)', 2, None]]
        planned = adaptor.plan(document(columns=labels, rows=rows))['nodes'][0]['options']
        self.assertEqual(planned['rows'], rows)

    def test_a_record_without_any_present_cell_is_rejected(self):
        columns = [{'name': 'a', 'kind': 'text', 'nullable': True}, {'name': 'b', 'kind': 'number', 'nullable': True}]
        authored = document(columns=columns, rows=[['x', 1], [None, None], ['y', 2]])
        fault = self.fault(adaptor.plan, authored)
        self.assertEqual((fault.code, fault.location), ('INVALID_TABLE', 'rows[1]'))

    def test_number_columns_need_two_present_values_text_only_tables_do_not(self):
        thin = document(rows=[['a', None, 'x'], ['b', 1, 'y']])
        fault = self.fault(adaptor.plan, thin)
        self.assertEqual((fault.code, fault.location), ('INVALID_TABLE', 'columns[1]'))
        self.assertEqual(fault.observed['present'], 1)
        only_text = document(columns=[COLUMNS[0]], rows=[['solo']])
        self.assertTrue(adaptor.plan(only_text))

    def test_bounds_are_enforced_before_native_work(self):
        with patch.object(typed_table, 'MAX_CELLS', 5):
            self.assertEqual(self.fault(adaptor.plan, document()).code, 'RESOURCE_LIMIT')
        with patch.object(typed_table, 'MAX_TEXT_BYTES', 8):
            self.assertEqual(self.fault(adaptor.plan, document()).code, 'RESOURCE_LIMIT')
        self.assertEqual(self.fault(adaptor.plan, document(rows=[['x' * 1025, 1, None], ['y', 2, None]])).code, 'INVALID_ARGUMENT')


class TypedCsvGrammarTests(Base):
    def parse(self, text, columns=COLUMNS, token='\\N'):
        return typed_table.parse_csv(text.encode('utf-8') if isinstance(text, str) else text, columns_for(columns), token, 'in.csv')

    def test_closed_grammar_accepts_quoted_text_and_both_line_endings(self):
        header = '"Part ID","Mass (g)","Note"'
        parsed = self.parse(header + '\r\n"00123",1.5,"a ""q"", b"\r\n"x",\\N,\\N\r\n"y",2,"z"')
        self.assertEqual(parsed['rows'], [['00123', 1.5, 'a "q", b'], ['x', None, None], ['y', 2.0, 'z']])
        # A quoted token is the token, exactly as in the Arrow source dialect.
        self.assertEqual(self.parse(header + '\n"x","\\N","\\N"\n"y",2,z\n"w",3,"v"\n')['rows'][0], ['x', None, None])
        self.assertEqual(self.parse(header + '\n' + '"x",+.5e1,"n"\n"y",-2,"m"\n')['rows'][0][1], 5.0)

    def test_every_deviation_is_a_located_fault(self):
        header = '"Part ID","Mass (g)","Note"\n'
        cases = [('bom', '\ufeff' + header + 'a,1,b\nc,2,d\n', 'INVALID_TABLE', 'in.csv'),
                 ('bare carriage return', header.replace('\n', '\r') + 'a,1,b\n', 'INVALID_TABLE', 'in.csv'),
                 ('stray quote', header + 'a"b,1,c\nd,2,e\n', 'INVALID_TABLE', 'in.csv'),
                 ('unterminated quote', header + '"a,1,c\n', 'INVALID_TABLE', 'in.csv'),
                 ('trailing comma', header + 'a,1,\n', 'INVALID_TABLE', 'rows[0][2]'),
                 ('embedded newline', header + '"a\nb",1,c\nd,2,e\n', 'INVALID_TABLE', 'rows[0][0]'),
                 ('blank line', header + 'a,1,b\n\nd,2,e\n', 'INVALID_TABLE', 'rows[1]'),
                 ('short record', header + 'a,1\nd,2,e\n', 'INVALID_TABLE', 'rows[0]'),
                 ('empty text', header + 'a,1,\\N\n"",2,e\n', 'INVALID_TABLE', 'rows[1][0]'),
                 ('padded number', header + 'a, 1,b\nc,2,d\n', 'INVALID_TABLE', 'rows[0][1]'),
                 ('thousands', header + 'a,"1,000",b\nc,2,d\n', 'INVALID_TABLE', 'rows[0][1]'),
                 ('underscore', header + 'a,1_0,b\nc,2,d\n', 'INVALID_TABLE', 'rows[0][1]'),
                 ('arabic digits', header + 'a,١٢,b\nc,2,d\n', 'INVALID_TABLE', 'rows[0][1]'),
                 ('nan', header + 'a,nan,b\nc,2,d\n', 'INVALID_TABLE', 'rows[0][1]'),
                 ('range', header + 'a,1e101,b\nc,2,d\n', 'INVALID_TABLE', 'rows[0][1]'),
                 ('overflow', header + 'a,1e999,b\nc,2,d\n', 'INVALID_TABLE', 'rows[0][1]'),
                 ('inexact integer', header + 'a,9007199254740993,b\nc,2,d\n', 'INVALID_TABLE', 'rows[0][1]'),
                 ('header name', '"Part ID","Mass","Note"\na,1,b\nc,2,d\n', 'INVALID_TABLE', 'columns[1].name'),
                 ('header order', '"Mass (g)","Part ID","Note"\n1,a,b\n2,c,d\n', 'INVALID_TABLE', 'columns[0].name'),
                 ('header width', '"Part ID","Mass (g)"\na,1\nc,2\n', 'INVALID_TABLE', 'columns'),
                 ('no records', header, 'INVALID_TABLE', 'rows'),
                 ('empty file', '', 'INVALID_TABLE', 'in.csv')]
        for name, text, code, location in cases:
            with self.subTest(name):
                fault = self.fault(self.parse, text)
                self.assertEqual((fault.code, fault.location), (code, location))
                if location.startswith('rows['):
                    self.assertIn('record', fault.observed)

    def test_invalid_utf8_and_null_in_required_column_are_faults(self):
        self.assertEqual(self.fault(self.parse, b'\xff\xfe').code, 'INVALID_TABLE')
        required = [{'name': 'a', 'kind': 'text'}, {'name': 'b', 'kind': 'number'}]
        fault = self.fault(self.parse, '"a","b"\nx,1\n\\N,2\n', required)
        self.assertEqual(fault.location, 'rows[1][0]')
        self.assertEqual(fault.observed['record'], 3)

    def test_record_width_is_bounded_while_tokenizing(self):
        fault = self.fault(typed_table.records, b',' * 4096, 'in.csv')
        self.assertEqual((fault.code, fault.observed['record']), ('INVALID_TABLE', 1))

    def test_csv_size_bound_applies_before_parsing(self):
        with patch.object(typed_table, 'MAX_BYTES', 10):
            self.assertEqual(self.fault(self.parse, '"Part ID","Mass (g)","Note"\n').code, 'RESOURCE_LIMIT')

    def test_published_csv_round_trips_tricky_text_exactly(self):
        # Deterministic fuzz: any admissible text must survive publish -> parse unchanged.
        rng = random.Random(64)
        alphabet = ['0', '1', 'a', ' ', ',', '"', '=', '+', '-', '@', 'é', 'e\u0301', '\u00a0', '\U0001F600', 'ש', '_', '\\', 'N', "'", ';']
        columns = [{'name': 'id', 'kind': 'text'}, {'name': 'v', 'kind': 'number', 'nullable': True}]
        cells = []
        for _ in range(200):
            text = ''.join(rng.choice(alphabet) for _ in range(rng.randint(1, 12)))
            if text == '\\N':
                text = '\\NN'
            cells.append([text, rng.choice([None, 0.0, rng.uniform(-1e6, 1e6), 1e100, -2.5e-300, 0.1 + 0.2])])
        built = typed_table.validate(columns, cells)
        again = typed_table.parse_csv(typed_table.csv_bytes(built), built['columns'], built['nullToken'])
        self.assertEqual(again, built)

    def test_published_csv_marks_text_with_quotes_and_missing_with_the_bare_token(self):
        payload = typed_table.csv_bytes(typed()).decode('utf-8')
        self.assertEqual(payload.splitlines(), ['"Part ID","Mass (g)","Note"', '"00123",1.5,"=1+2"',
                                                '"café",\\N,"+SUM(A1:A2)"', '"@part",0.0,"-02"', '"N° 7  b",4.5,\\N'])

    def test_arrow_source_dialect_reads_the_published_csv_identically(self):
        # Compatibility with the Arrow adaptor's host CSV oracle, checked from the test only.
        try:
            from schemaxis.adaptors.apachearrow import reference
        except ImportError:
            self.skipTest('Arrow reference unavailable')
        columns = [{'name': 'part_id', 'kind': 'text'}, {'name': 'mass', 'kind': 'number', 'nullable': True},
                   {'name': 'note', 'kind': 'text', 'nullable': True}]
        built = typed_table.validate(columns, [['00123', 1.5, '=1+2'], ['café', None, 'a "q", b'], ['@part', 0, 'é']])
        payload = typed_table.csv_bytes(built)
        declared = [{'name': c['name'], 'type': 'float64' if c['kind'] == 'number' else 'utf8', 'nullable': c.get('nullable', False)}
                    for c in columns]
        self.assertEqual(reference.source(payload, declared), [['00123', 1.5, '=1+2'], ['café', None, 'a "q", b'], ['@part', 0.0, 'é']])


def columns_for(columns):
    return [{'name': c['name'], 'kind': c['kind'], 'nullable': bool(c.get('nullable', False))} for c in columns]


class TypedSummaryTests(Base):
    def test_numeric_summaries_ignore_blanks_and_exclude_text(self):
        wanted = typed_workbook.expected(typed())
        self.assertEqual(wanted['Data'][0], ['Part ID', 'Mass (g)', 'Note'])
        self.assertEqual(wanted['Data'][2], ['café', None, '+SUM(A1:A2)'])
        self.assertEqual(wanted['Data'][3], ['@part', 0.0, '-02'])
        self.assertEqual(wanted['Summary'][0], ['Column', 'COUNT', 'SUM', 'AVERAGE', 'MIN', 'MAX', 'STDEV', 'MISSING'])
        self.assertEqual(len(wanted['Summary']), 2)  # only the one numeric column
        name, count, total, mean, low, high, stdev, missing = wanted['Summary'][1]
        self.assertEqual((name, count, total, mean, low, high, missing), ('Mass (g)', 3, 6.0, 2.0, 0.0, 4.5, 1))
        self.assertAlmostEqual(stdev, 5.25 ** 0.5, places=12)

    def test_zero_blank_and_text_are_three_different_things(self):
        wanted = typed_workbook.expected(typed())['Data']
        self.assertIsNone(wanted[2][1])
        self.assertIs(type(wanted[3][1]), float)
        self.assertEqual(wanted[3][1], 0.0)
        self.assertEqual(wanted[1][0], '00123')
        summary = typed_table.summary(typed())
        mass = summary['columns'][1]
        self.assertEqual((mass['present'], mass['missing'], mass['min']), (3, 1, 0.0))
        ids = summary['columns'][0]
        self.assertEqual((ids['present'], ids['distinct'], ids['unique']), (4, 4, True))
        self.assertNotIn('sum', ids)

    def test_summary_digests_bind_exact_text_unicode_and_missingness(self):
        base = typed_table.summary(typed())
        digest = lambda s, i: s['columns'][i]['valuesSHA256']
        for index, mutate in [(0, lambda r: r[0].__setitem__(0, '0123')), (0, lambda r: r[1].__setitem__(0, 'cafe\u0301')),
                              (1, lambda r: r[1].__setitem__(1, 0)), (2, lambda r: r[3].__setitem__(2, '-')),
                              (1, lambda r: r[2].__setitem__(1, 1e-12))]:
            rows = copy.deepcopy(ROWS)
            mutate(rows)
            changed = typed_table.summary(typed_table.validate(columns_for(COLUMNS), rows))
            self.assertNotEqual(digest(changed, index), digest(base, index))
        nfd = typed_table.summary(typed_table.validate(columns_for(COLUMNS), [['cafe\u0301', 1, None], ['x', 2, None]]))
        nfc = typed_table.summary(typed_table.validate(columns_for(COLUMNS), [['caf\u00e9', 1, None], ['x', 2, None]]))
        self.assertNotEqual(digest(nfd, 0), digest(nfc, 0))

    def test_formula_text_is_literal_in_the_authored_native_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'input.ods'
            typed_workbook.write_ods(path, typed())
            content = ZipFile(path).read('content.xml').decode('utf-8')
        data = content[content.index('table:name="Data"'):content.index('table:name="Summary"')]
        self.assertNotIn('table:formula', data)
        for literal in ('=1+2', '+SUM(A1:A2)', '-02', '@part', '00123'):
            self.assertRegex(data, r'office:value-type="string"[^>]*><text:p>' + re.escape(literal) + '</text:p>')
        self.assertEqual(content.count('table:formula='), 7)  # seven fixed Summary formulas for one numeric column
        self.assertIn('COUNTBLANK', content)


class WorkbookFixtureMixin:
    """Hand-built native-like ODS/XLSX files with cached Summary values."""
    SUMMARY = ['Mass (g)', 3, 6.0, 2.0, 0.0, 4.5, 5.25 ** 0.5, 1]
    XLSX_FORMULAS = ['COUNT(Data!B2:B5)', 'SUM(Data!B2:B5)', 'AVERAGE(Data!B2:B5)', 'MIN(Data!B2:B5)', 'MAX(Data!B2:B5)',
                     'STDEV(Data!B2:B5)', 'COUNTBLANK(Data!B2:B5)']
    ODS_FORMULAS = ['of:=COUNT([$Data.B2:.B5])', 'of:=SUM([$Data.B2:.B5])', 'of:=AVERAGE([$Data.B2:.B5])',
                    'of:=MIN([$Data.B2:.B5])', 'of:=MAX([$Data.B2:.B5])', 'of:=STDEV([$Data.B2:.B5])',
                    'of:=COUNTBLANK([$Data.B2:.B5])']

    def data_rows(self):
        return [['Part ID', 'Mass (g)', 'Note'], ['00123', 1.5, '=1+2'], ['café', None, '+SUM(A1:A2)'],
                ['@part', 0.0, '-02'], ['N° 7  b', 4.5, None]]

    def summary_rows(self):
        return [['Column', 'COUNT', 'SUM', 'AVERAGE', 'MIN', 'MAX', 'STDEV', 'MISSING'], list(self.SUMMARY)]

    @staticmethod
    def column(index):
        return 'ABCDEFGH'[index]

    def build_xlsx(self, path, data=None, summary=None, formulas=None, styles=None, sheet_extra='', relationships='',
                   shared_rich=False, shared_phonetic=False, bad_kind=None):
        data = self.data_rows() if data is None else data
        summary = self.summary_rows() if summary is None else summary
        formulas = self.XLSX_FORMULAS if formulas is None else formulas
        strings = []

        def index(text):
            if text not in strings:
                strings.append(text)
            return strings.index(text)

        def sheet(rows, formula_cells=False):
            out = []
            for r, row in enumerate(rows, 1):
                cells = []
                for c, value in enumerate(row):
                    ref = f'{self.column(c)}{r}'
                    if value is None:
                        continue
                    if formula_cells and r > 1 and c > 0:
                        cells.append(f'<c r="{ref}"><f>{formulas[c - 1]}</f><v>{value!r}</v></c>')
                    elif isinstance(value, str):
                        cells.append(f'<c r="{ref}" t="s"><v>{index(value)}</v></c>')
                    else:
                        cells.append(f'<c r="{ref}"><v>{value!r}</v></c>')
                out.append(f'<row r="{r}">{"".join(cells)}</row>')
            return ''.join(out)

        ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        sheet1 = f'<worksheet {ns}><sheetData>{sheet(data)}</sheetData>{sheet_extra}</worksheet>'
        sheet2 = f'<worksheet {ns}><sheetData>{sheet(summary, True)}</sheetData></worksheet>'
        escape = lambda t: t.replace('&', '&amp;').replace('<', '&lt;').replace('_x', '_x005F_x')
        items = ''.join(f'<si><r><rPr><sz val="10"/></rPr><t xml:space="preserve">{escape(s)}</t></r></si>' if shared_rich else
                        f'<si><t xml:space="preserve">{escape(s)}</t><rPh sb="0" eb="1"><t>hidden</t></rPh></si>' if shared_phonetic else
                        f'<si><t xml:space="preserve">{escape(s)}</t></si>' for s in strings)
        styles = styles or f'<styleSheet {ns}><numFmts count="1"><numFmt numFmtId="164" formatCode="General"/></numFmts><cellXfs count="1"><xf numFmtId="164"/></cellXfs></styleSheet>'
        files = {'xl/workbook.xml': f'<workbook {ns} xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Data" sheetId="1" r:id="rId3"/><sheet name="Summary" sheetId="2" r:id="rId4"/></sheets></workbook>',
                 'xl/_rels/workbook.xml.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId3" Target="worksheets/sheet1.xml"/><Relationship Id="rId4" Target="worksheets/sheet2.xml"/></Relationships>',
                 'xl/worksheets/sheet1.xml': sheet1, 'xl/worksheets/sheet2.xml': sheet2, 'xl/styles.xml': styles,
                 'xl/sharedStrings.xml': f'<sst {ns}>{items}</sst>'}
        if relationships:
            files['xl/worksheets/_rels/sheet1.xml.rels'] = relationships
        with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
            for name, payload in files.items():
                archive.writestr(name, payload)

    def ods_cell(self, value, formula=None, repeated=1):
        repeat = f' table:number-columns-repeated="{repeated}"' if repeated > 1 else ''
        if formula is not None:
            return f'<table:table-cell table:formula="{formula}" office:value-type="float" office:value="{value!r}"/>'
        if value is None:
            return f'<table:table-cell{repeat}/>'
        if isinstance(value, str):
            body = re.sub(r' {2,}| $|^ ', lambda m: f'<text:s text:c="{len(m[0])}"/>', value.replace('&', '&amp;').replace('<', '&lt;'))
            return f'<table:table-cell{repeat} office:value-type="string"><text:p>{body}</text:p></table:table-cell>'
        return f'<table:table-cell{repeat} office:value-type="float" office:value="{value!r}"><text:p>{value!r}</text:p></table:table-cell>'

    def build_ods(self, path, data=None, summary=None, formulas=None, cell_hook=None, extra_namespace='', members=None):
        data = self.data_rows() if data is None else data
        summary = self.summary_rows() if summary is None else summary
        formulas = self.ODS_FORMULAS if formulas is None else formulas

        def sheet(name, rows, formula_cells=False):
            body = []
            for r, row in enumerate(rows, 1):
                cells = []
                for c, value in enumerate(row):
                    cells.append(self.ods_cell(value, formulas[c - 1] if formula_cells and r > 1 and c > 0 else None))
                body.append('<table:table-row>' + ''.join(cells) + '</table:table-row>')
            return f'<table:table table:name="{name}">' + ''.join(body) + '</table:table>'
        content = ('<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
                   'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
                   'xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
                   'xmlns:number="urn:oasis:names:tc:opendocument:xmlns:datastyle:1.0" xmlns:calcext="urn:org:documentfoundation:names:experimental:calc:xmlns:calcext:1.0">'
                   '<office:scripts/><office:body><office:spreadsheet>' + sheet('Data', data) + sheet('Summary', summary, True) +
                   '</office:spreadsheet></office:body></office:document-content>')
        if cell_hook:
            content = cell_hook(content)
        with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
            archive.writestr('mimetype', 'application/vnd.oasis.opendocument.spreadsheet')
            archive.writestr('content.xml', content)
            for name, payload in (members or {}).items():
                archive.writestr(name, payload)


class WorkbookReadbackTests(WorkbookFixtureMixin, Base):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def check(self, kind, **options):
        path = self.root / ('book.' + kind)
        getattr(self, 'build_' + ('xlsx' if kind == 'xlsx' else 'ods'))(path, **options)
        return typed_workbook.verify_workbook(path, typed(), full=True)

    def test_literal_native_like_files_verify_in_both_formats_and_keep_types(self):
        for kind in ('xlsx', 'ods'):
            with self.subTest(kind):
                values = self.check(kind)
                self.assertEqual(values['Data'][1], ['00123', 1.5, '=1+2'])
                self.assertEqual(values['Data'][2], ['café', None, '+SUM(A1:A2)'])
                self.assertIs(type(values['Data'][3][1]), float)
                self.assertEqual(values['Data'][4], ['N° 7  b', 4.5, None])  # double space and degree sign kept
                self.assertEqual(values['Summary'][1][7], 1.0)

    def test_text_and_formula_counterexamples_fail_semantic_checks(self):
        def with_data(row, column, value):
            rows = self.data_rows()
            rows[row][column] = value
            return rows
        shape = 'worksheet shape'
        cases = {'identifier coerced to a number': (dict(data=with_data(1, 0, 123.0)), 'Data.A2'),
                 'identifier lost leading zero': (dict(data=with_data(1, 0, '123')), 'Data.A2'),
                 'formula text evaluated to its result': (dict(data=with_data(1, 2, 3.0)), 'Data.C2'),
                 'formula text mutated': (dict(data=with_data(1, 2, '=1+3')), 'Data.C2'),
                 'blank became zero': (dict(data=with_data(2, 1, 0.0)), 'Data.B3'),
                 'blank became empty text': (dict(data=with_data(2, 1, '')), 'Data.B3'),
                 'zero became blank': (dict(data=with_data(3, 1, None)), 'Data.B4'),
                 'text became blank': (dict(data=with_data(4, 2, '')), 'Data.C5'),
                 'NFC became NFD': (dict(data=with_data(2, 0, 'cafe\u0301')), 'Data.A3'),
                 'spaces collapsed': (dict(data=with_data(4, 0, 'N° 7 b')), 'Data.A5'),
                 'trailing space added': (dict(data=with_data(1, 0, '00123 ')), 'Data.A2'),
                 'extra column': (dict(data=[row + ['x'] for row in self.data_rows()]), shape),
                 'missing row': (dict(data=self.data_rows()[:-1]), shape),
                 'extra row': (dict(data=self.data_rows() + [['z', 1.0, 'n']]), shape),
                 'swapped columns': (dict(data=[[r[1], r[0], r[2]] for r in self.data_rows()]), 'Data.A1'),
                 'header changed': (dict(data=with_data(0, 1, 'Mass')), 'Data.B1'),
                 'relative 1e-12 measurement drift': (dict(data=with_data(1, 1, 1.5 * (1 + 1e-12))), 'Data.B2'),
                 'summary cache altered': (dict(summary=[self.summary_rows()[0], [*self.SUMMARY[:2], 6.5, *self.SUMMARY[3:]]]), 'Summary.C2'),
                 'missing count altered': (dict(summary=[self.summary_rows()[0], [*self.SUMMARY[:7], 0]]), 'Summary.H2'),
                 'text column summarised': (dict(summary=self.summary_rows() + [['Part ID', 4, 0.0, 0.0, 0.0, 0.0, 0.0, 0]]), shape)}
        for name, (options, where) in cases.items():
            for kind in ('xlsx', 'ods'):
                with self.subTest(name, kind=kind):
                    fault = self.fault(self.check, kind, **options)
                    self.assertEqual(fault.code, 'VERIFICATION_FAILED')
                    if where == shape:
                        self.assertIn(shape, fault.message)
                    else:
                        self.assertEqual(fault.observed.get('cell'), where, fault.message)

    def test_formula_counterexamples_with_matching_caches_still_fail(self):
        wrong = list(self.XLSX_FORMULAS)
        wrong[1] = 'MAX(Data!B2:B5)'
        self.assertEqual(self.fault(self.check, 'xlsx', formulas=wrong).code, 'VERIFICATION_FAILED')
        wrong = list(self.ODS_FORMULAS)
        wrong[6] = 'of:=COUNTA([$Data.B2:.B5])'
        self.assertEqual(self.fault(self.check, 'ods', formulas=wrong).code, 'VERIFICATION_FAILED')
        wrong = list(self.XLSX_FORMULAS)
        wrong[0] = 'COUNT(Data!B2:B4)'  # range shortened by one row
        self.assertEqual(self.fault(self.check, 'xlsx', formulas=wrong).code, 'VERIFICATION_FAILED')

    def test_formula_in_a_data_cell_is_rejected_even_when_the_value_matches(self):
        def inject(content):
            return content.replace('<table:table-cell office:value-type="float" office:value="1.5"><text:p>1.5</text:p></table:table-cell>',
                                   '<table:table-cell table:formula="of:=1.5" office:value-type="float" office:value="1.5"/>', 1)
        self.assertEqual(self.fault(self.check, 'ods', cell_hook=inject).code, 'VERIFICATION_FAILED')
        path = self.root / 'f.xlsx'
        self.build_xlsx(path)
        with ZipFile(path) as archive:
            members = {n: archive.read(n) for n in archive.namelist()}
        members['xl/worksheets/sheet1.xml'] = members['xl/worksheets/sheet1.xml'].replace(b'<c r="B2"><v>1.5</v></c>', b'<c r="B2"><f>1.5</f><v>1.5</v></c>')
        with ZipFile(path, 'w') as archive:
            for name, payload in members.items():
                archive.writestr(name, payload)
        self.assertEqual(self.fault(typed_workbook.verify_workbook, path, typed()).code, 'VERIFICATION_FAILED')

    def rejects(self, kind, reason, **options):
        fault = self.fault(self.check, kind, **options)
        self.assertEqual(fault.code, 'VERIFICATION_FAILED')
        self.assertIn(reason, fault.message)

    def test_unsupported_rich_content_links_and_types_are_rejected(self):
        link = lambda c: c.replace('<text:p>=1+2</text:p>', '<text:p><text:a xlink:href="http://example.invalid/">=1+2</text:a></text:p>')
        self.rejects('ods', 'hyperlink', cell_hook=link)
        tab = lambda c: c.replace('<text:p>=1+2</text:p>', '<text:p>=1<text:tab/>+2</text:p>')
        self.rejects('ods', 'rich content', cell_hook=tab)
        href = lambda c: c.replace('<table:table-cell office:value-type="string"><text:p>@part', '<table:table-cell xlink:href="x" office:value-type="string"><text:p>@part', 1)
        self.rejects('ods', 'hyperlink', cell_hook=href)
        boolean = lambda c: c.replace('office:value-type="float" office:value="0.0"', 'office:value-type="boolean" office:boolean-value="true"', 1)
        self.rejects('ods', 'cell type', cell_hook=boolean)
        date_style = lambda c: c.replace('<office:scripts/>', '<office:scripts/><number:date-style number:name="N1"/>')
        self.rejects('ods', 'data-style', cell_hook=date_style)
        script = lambda c: c.replace('<office:scripts/>', '<office:scripts><x:script xmlns:x="urn:oasis:names:tc:opendocument:xmlns:script:1.0"/></office:scripts>')
        self.rejects('ods', 'script', cell_hook=script)
        self.rejects('ods', 'macros', members={'Basic/script.xml': b'<x/>'})
        self.rejects('xlsx', 'phonetic', shared_phonetic=True)
        self.rejects('xlsx', 'links', sheet_extra='<hyperlinks><hyperlink ref="A2" location="Summary!A1"/></hyperlinks>')
        external = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="x" Target="http://example.invalid/" TargetMode="External"/></Relationships>'
        self.rejects('xlsx', 'external relationship', relationships=external)
        percent = '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cellXfs count="1"><xf numFmtId="14"/></cellXfs></styleSheet>'
        self.rejects('xlsx', 'number format', styles=percent)

    def test_font_fallback_runs_are_formatting_not_content(self):
        # LibreOffice splits text such as U+FEFF + "bom" into runs with different fonts.
        for kind in ('xlsx',):
            self.assertEqual(self.check(kind, shared_rich=True)['Data'][1][0], '00123')

    def test_oversized_xml_members_are_rejected_before_parsing(self):
        for kind in ('xlsx', 'ods'):
            with self.subTest(kind), patch.object(typed_workbook, 'MAX_XML', 100):
                self.rejects(kind, 'bound')

    def test_corrupt_archives_are_not_workbooks(self):
        path = self.root / 'bad.xlsx'
        for payload in (b'', b'PK\x03\x04', b'not a zip'):
            path.write_bytes(payload)
            with self.assertRaises(BadZipFile):
                typed_workbook.verify_workbook(path, typed())

    def test_ooxml_underscore_escapes_decode_to_the_exact_text(self):
        columns = [{'name': 'id', 'kind': 'text'}, {'name': 'v', 'kind': 'number'}]
        built = typed_table.validate(columns, [['_x0041_', 1], ['_x005F_', 2]])
        path = self.root / 'u.xlsx'
        self.SUMMARY = ['v', 2, 3.0, 1.5, 1.0, 2.0, 0.5 ** 0.5, 0]
        self.build_xlsx(path, data=[['id', 'v'], ['_x0041_', 1.0], ['_x005F_', 2.0]], summary=self.summary_rows(),
                        formulas=[f.replace('B2:B5', 'B2:B3') for f in self.XLSX_FORMULAS])
        self.assertEqual(typed_workbook.verify_workbook(path, built, full=True)['Data'][1][0], '_x0041_')

    def test_sparse_cells_repeated_rows_and_trailing_blanks_are_positioned_correctly(self):
        rows = self.data_rows()
        rows[1][2] = None
        short = typed_table.validate(columns_for(COLUMNS), [['00123', 1.5, None], *[list(r) for r in ROWS[1:]]])
        path = self.root / 'sparse.ods'
        self.build_ods(path, data=rows)
        values = typed_workbook.verify_workbook(path, short, full=True)
        self.assertEqual(values['Data'][1], ['00123', 1.5, None])
        self.assertEqual(len(values['Data'][1]), 3)

    def test_fixed_number_tolerance_is_tighter_than_the_old_table_tolerance(self):
        self.assertLess(typed_workbook.DIGIT_TOLERANCE, 2e-8)
        # 15 significant digits, as LibreOffice writes into XLSX, is within tolerance.
        data = self.data_rows()
        data[1][1] = float('%.15g' % (1 / 3))
        columns = columns_for(COLUMNS)
        built = typed_table.validate(columns, [['00123', 1 / 3, '=1+2'], ['café', None, '+SUM(A1:A2)'], ['@part', 0, '-02'], ['N° 7  b', 4.5, None]])
        sums = [3, 1 / 3 + 4.5, (1 / 3 + 4.5) / 3, 0.0, 4.5]
        wanted = typed_workbook.expected(built)['Summary'][1]
        self.SUMMARY = wanted
        path = self.root / 'digits.xlsx'
        self.build_xlsx(path, data=data, summary=self.summary_rows())
        self.assertTrue(typed_workbook.verify_workbook(path, built))
        del sums


TINY_COLUMNS = [{'name': 'ID', 'kind': 'text'}, {'name': 'Reading', 'kind': 'number', 'nullable': True}]


class SummaryPrecisionMixin(WorkbookFixtureMixin):
    """Summary cells are checked against the column's own magnitude, so tiny measurements cannot match forged statistics."""
    VALUES = [1e-12, 3e-12]

    def tiny_table(self, values=None):
        values = self.VALUES if values is None else values
        return typed_table.validate(columns_for(TINY_COLUMNS), [[f'p{i}', v] for i, v in enumerate(values)])

    def data_rows(self):
        return [['ID', 'Reading']] + [[f'p{i}', v] for i, v in enumerate(self.VALUES)]

    def formulas(self, ods=False):
        last = len(self.VALUES) + 1
        return [f.replace('B2:B5', f'B2:B{last}').replace(':.B5', f':.B{last}') for f in (self.ODS_FORMULAS if ods else self.XLSX_FORMULAS)]

    def honest(self, values=None):
        return typed_workbook.expected(self.tiny_table(values))['Summary'][1]

    def write(self, path, summary_row):
        """Hand-built native-like workbook whose Summary cache is exactly summary_row."""
        self.SUMMARY = list(summary_row)
        if path.suffix == '.xlsx':
            self.build_xlsx(path, formulas=self.formulas())
        else:
            self.build_ods(path, formulas=self.formulas(ods=True))

    def verify(self, kind, summary_row, values=None):
        path = self.root / ('book.' + kind)
        self.write(path, summary_row)
        return typed_workbook.verify_workbook(path, self.tiny_table(values))

    def forged(self, kind, index, value, values=None):
        row = self.honest(values)
        row[index] = value
        return self.verify(kind, row, values)


class SummaryPrecisionTests(SummaryPrecisionMixin, Base):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def test_honest_tiny_all_zero_and_underflow_columns_verify_in_both_formats(self):
        for kind in ('xlsx', 'ods'):
            for values in ([1e-12, 3e-12], [0.0, 0.0], [5e-324, 1e-323], [-2e-12, 2e-12], [1e-12, -3e-12, 5e-12]):
                self.VALUES = values
                with self.subTest(kind=kind, values=values):
                    self.assertEqual(self.verify(kind, self.honest(values), values)[1], self.honest(values))

    def test_native_style_fifteen_digit_rounding_of_tiny_statistics_is_accepted(self):
        for kind in ('xlsx', 'ods'):
            row = [float('%.15g' % v) if isinstance(v, float) else v for v in self.honest()]
            with self.subTest(kind):
                self.assertTrue(self.verify(kind, row))

    def test_forged_tiny_column_statistics_fail_in_both_formats(self):
        # SUM, AVERAGE, STDEV and MIN/MAX for [1e-12, 3e-12]: true values 4e-12, 2e-12, 1.414e-12, 1e-12, 3e-12.
        for kind in ('xlsx', 'ods'):
            for label, index, value in [('sum zero', 2, 0.0), ('sum doubled', 2, 8e-12), ('average zero', 3, 0.0),
                                        ('stdev 1e-9', 6, 1e-9), ('stdev zero', 6, 0.0), ('min zero', 4, 0.0),
                                        ('max 1e-9', 5, 1e-9), ('max off by 1e-6 relative', 5, 3e-12 * (1 + 1e-6))]:
                with self.subTest(kind=kind, forgery=label):
                    with self.assertRaises(SchemaxisError) as caught:
                        self.forged(kind, index, value)
                    self.assertIn('typed cell differs', caught.exception.fault.message)

    def test_all_zero_column_accepts_only_exact_zero_statistics(self):
        self.VALUES = [0.0, 0.0, 0.0]
        for kind in ('xlsx', 'ods'):
            for index in (2, 3, 4, 5, 6):
                for value in (1e-300, -1e-300, 5e-324, 1e-12):
                    with self.subTest(kind=kind, index=index, value=value):
                        with self.assertRaises(SchemaxisError):
                            self.forged(kind, index, value)

    def test_underflow_scale_does_not_accept_a_materially_nonzero_forgery(self):
        self.VALUES = [5e-324, 1e-323]
        for kind in ('xlsx', 'ods'):
            for index, value in [(2, 0.0), (2, 1e-322), (3, 0.0), (6, 1e-300)]:
                with self.subTest(kind=kind, index=index, value=value):
                    with self.assertRaises(SchemaxisError):
                        self.forged(kind, index, value)

    def test_counts_stay_whole_numbers_and_statistics_must_be_finite_reals(self):
        for kind in ('xlsx', 'ods'):
            for label, index, value in [('fractional count', 1, 2.0000000001), ('count 2.5', 1, 2.5), ('fractional missing', 7, 1e-9),
                                        ('infinite sum', 2, float('inf')), ('nan stdev', 6, float('nan'))]:
                with self.subTest(kind=kind, forgery=label):
                    with self.assertRaises((SchemaxisError, ValueError)):
                        self.forged(kind, index, value)

    def test_a_boolean_cell_is_not_a_number_in_the_summary(self):
        path = self.root / 'bool.xlsx'
        self.write(path, self.honest())
        from zipfile import ZipFile as Z
        with Z(path) as source:
            members = {n: source.read(n) for n in source.namelist()}
        sheet = members['xl/worksheets/sheet2.xml'].decode()
        self.assertEqual(sheet.count('<c r="B2"><f>COUNT(Data!B2:B3)</f><v>2</v></c>'), 1)
        members['xl/worksheets/sheet2.xml'] = sheet.replace('<c r="B2"><f>COUNT(Data!B2:B3)</f><v>2</v></c>',
                                                           '<c r="B2" t="b"><f>COUNT(Data!B2:B3)</f><v>1</v></c>').encode()
        with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
            for name, payload in members.items():
                archive.writestr(name, payload)
        with self.assertRaises(SchemaxisError):
            typed_workbook.verify_workbook(path, self.tiny_table())

    def test_cancellation_across_large_magnitudes_is_bounded_by_the_largest_value(self):
        # [1e9, 0.25, -1e9] sums to 0.25; a different summation order may differ by well under 1e-12 of 1e9.
        self.VALUES = [1e9, 0.25, -1e9]
        for kind in ('xlsx', 'ods'):
            with self.subTest(kind=kind, case='summation noise'):
                self.assertTrue(self.forged(kind, 2, 0.25 + 1e-5))
            for label, value in [('zero', 0.0), ('tenth off', 0.35), ('negated', -0.25)]:
                with self.subTest(kind=kind, case=label):
                    with self.assertRaises(SchemaxisError):
                        self.forged(kind, 2, value)
        self.VALUES = [-4e-12, -1e-12]  # all-negative tiny column: sign matters
        for kind in ('xlsx', 'ods'):
            with self.subTest(kind=kind, case='negative column'):
                self.assertTrue(self.verify(kind, self.honest()))
                with self.assertRaises(SchemaxisError):
                    self.forged(kind, 2, 5e-12)

    def test_one_rule_serves_workbook_cells_and_typed_summary_json(self):
        wanted = json.loads(json.dumps(typed_table.summary(self.tiny_table())))
        self.assertTrue(typed_table.summary_matches(copy.deepcopy(wanted), wanted))
        digits = copy.deepcopy(wanted)
        for key in ('sum', 'mean', 'min', 'max', 'stdev'):
            digits['columns'][1][key] = float('%.15g' % digits['columns'][1][key])
        self.assertTrue(typed_table.summary_matches(digits, wanted))
        for label, mutate in [('sum zero', lambda s: s['columns'][1].update(sum=0.0)),
                              ('stdev 1e-9', lambda s: s['columns'][1].update(stdev=1e-9)),
                              ('mean zero', lambda s: s['columns'][1].update(mean=0.0)),
                              ('max huge', lambda s: s['columns'][1].update(max=1e-9)),
                              ('min zero', lambda s: s['columns'][1].update(min=0.0)),
                              ('sum as integer zero', lambda s: s['columns'][1].update(sum=0)),
                              ('sum as boolean', lambda s: s['columns'][1].update(sum=False)),
                              ('sum nan', lambda s: s['columns'][1].update(sum=float('nan'))),
                              ('fractional present', lambda s: s['columns'][1].update(present=2.0000000001)),
                              ('present float', lambda s: s['columns'][1].update(present=2.0)),
                              ('present boolean', lambda s: s['columns'][1].update(present=True)),
                              ('missing one', lambda s: s['columns'][1].update(missing=1)),
                              ('rows', lambda s: s.update(rows=3)),
                              ('digest', lambda s: s['columns'][0].update(valuesSHA256='0' * 64)),
                              ('kind', lambda s: s['columns'][1].update(kind='text')),
                              ('extra key', lambda s: s['columns'][1].update(extra=1)),
                              ('removed metric', lambda s: s['columns'][1].pop('stdev')),
                              ('columns not list', lambda s: s.update(columns={}))]:
            with self.subTest(label):
                changed = copy.deepcopy(wanted)
                mutate(changed)
                self.assertFalse(typed_table.summary_matches(changed, wanted))

    def test_all_zero_summary_json_accepts_only_exact_zero(self):
        wanted = json.loads(json.dumps(typed_table.summary(self.tiny_table([0.0, 0.0]))))
        self.assertTrue(typed_table.summary_matches(copy.deepcopy(wanted), wanted))
        for key in ('sum', 'mean', 'min', 'max', 'stdev'):
            changed = copy.deepcopy(wanted)
            changed['columns'][1][key] = 1e-300
            with self.subTest(key):
                self.assertFalse(typed_table.summary_matches(changed, wanted))

    def test_data_cells_keep_the_one_in_1e14_precision_while_summary_has_its_own_rule(self):
        # Data: relative 1e-14 only. 1e-12 -> 1.0000001e-12 is a data forgery even though Summary-scale noise is allowed.
        path = self.root / 'data.xlsx'
        data = self.data_rows()
        data[1][1] = 1e-12 * (1 + 1e-9)
        self.SUMMARY = self.honest()
        self.build_xlsx(path, data=data, formulas=self.formulas())
        with self.assertRaises(SchemaxisError) as caught:
            typed_workbook.verify_workbook(path, self.tiny_table())
        self.assertIn('Data.B2', caught.exception.fault.context['cell'] if hasattr(caught.exception.fault, 'context') else str(caught.exception.fault))


class TinySummaryEvidenceTests(SummaryPrecisionMixin, Base):
    """Host forgeries of published evidence with every ordinary digest refreshed to match the forged bytes."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def evidence(self, values=None):
        from schemaxis.artifacts import file_digest
        self.VALUES = values or self.VALUES
        authored = document(TINY_COLUMNS, [[f'p{i}', v] for i, v in enumerate(self.VALUES)])
        TypedRunEvidenceTests.fixture(self, self.root, authored)
        self.write(self.root / 'analysis.xlsx', self.honest())
        self.write(self.root / 'analysis.ods', self.honest())
        adaptor._native_verify(self.root, require_result=False)
        self.assertEqual(adaptor._native_verify(self.root)['rows'], len(self.VALUES))
        return file_digest

    def refresh(self, file_digest):
        from schemaxis.artifacts import atomic_json
        records = {'artifacts': adaptor.manifest(self.root, '\\N'),
                   'typedSummarySHA256': file_digest(self.root / 'typed-summary.json')}
        atomic_json(self.root / 'verification.json', records)

    def forbidden(self):
        self.assertEqual(self.fault(adaptor._native_verify, self.root).code, 'VERIFICATION_FAILED')

    def test_forged_workbook_summary_caches_with_refreshed_digests_are_rejected(self):
        file_digest = self.evidence()
        for kind in ('xlsx', 'ods'):
            for label, index, value in [('sum zero', 2, 0.0), ('stdev 1e-9', 6, 1e-9)]:
                with self.subTest(kind=kind, forgery=label):
                    row = self.honest()
                    row[index] = value
                    self.write(self.root / ('analysis.' + kind), row)
                    self.refresh(file_digest)
                    self.forbidden()
                    self.write(self.root / ('analysis.' + kind), self.honest())
                    self.refresh(file_digest)
                    adaptor._native_verify(self.root)

    def test_forged_typed_summary_json_with_refreshed_digests_is_rejected(self):
        file_digest = self.evidence()
        pristine = json.loads((self.root / 'typed-summary.json').read_text())
        for label, mutate in [('sum zero', lambda s: s['columns'][1].update(sum=0.0)),
                              ('stdev 1e-9', lambda s: s['columns'][1].update(stdev=1e-9)),
                              ('fractional present', lambda s: s['columns'][1].update(present=2.0000000001))]:
            with self.subTest(label):
                changed = copy.deepcopy(pristine)
                mutate(changed)
                (self.root / 'typed-summary.json').write_text(json.dumps(changed))
                self.refresh(file_digest)
                self.forbidden()
                (self.root / 'typed-summary.json').write_text(json.dumps(pristine))
                self.refresh(file_digest)
                adaptor._native_verify(self.root)

    def test_all_zero_evidence_rejects_a_nonzero_forged_summary_json(self):
        file_digest = self.evidence([0.0, 0.0])
        changed = json.loads((self.root / 'typed-summary.json').read_text())
        changed['columns'][1]['stdev'] = 1e-9
        (self.root / 'typed-summary.json').write_text(json.dumps(changed))
        self.refresh(file_digest)
        self.forbidden()


class RequirementTests(WorkbookFixtureMixin, Base):
    def test_summary_width_differs_by_route_and_blank_is_missing_not_text(self):
        select = [{'name': 'blanks', 'type': 'cellBounds', 'cell': {'sheet': 'Summary', 'cell': 'H2'}, 'minimum': 1, 'maximum': 1}]
        authored = document()
        authored['requirements'] = select
        self.assertEqual(adaptor.plan(authored)['requirements'][0]['cell']['cell'], 'H2')
        numeric = {'version': 'schemaxis.calc/1', 'nodes': [{'id': 'n', 'filter': 'fromRows', 'options': {'columns': ['a'], 'rows': [[1], [2]]}}],
                   'requirements': select}
        self.assertEqual(self.fault(adaptor.plan, numeric).code, 'INVALID_SELECTOR')
        self.assertEqual(self.fault(adaptor.plan, {**authored, 'requirements': [{**select[0], 'cell': {'sheet': 'Summary', 'cell': 'I2'}}]}).code, 'INVALID_SELECTOR')

    def test_data_selectors_distinguish_blank_text_and_zero_without_coercion(self):
        values = typed_workbook.expected(typed())
        picks = {'B3': 'missing', 'A2': 'non-numeric', 'C2': 'non-numeric', 'B4': None, 'B2': None}
        for cell, condition in picks.items():
            prepared = requirements.prepare([{'name': 'pick', 'type': 'cellBounds', 'cell': {'sheet': 'Data', 'cell': cell}, 'minimum': -1}], 8)
            check = requirements.evaluate(prepared, values, 8)['checks'][0]
            if condition is None:
                self.assertEqual((check['status'], check['value']), ('passed', values['Data'][int(cell[1:]) - 1][1]))
            else:
                self.assertEqual(check['conditions'][0]['condition'], condition)
        zero = requirements.prepare([{'name': 'zero', 'type': 'cellBounds', 'cell': {'sheet': 'Data', 'cell': 'B4'}, 'minimum': 0, 'maximum': 0}], 8)
        self.assertTrue(requirements.evaluate(zero, values, 8)['passed'])


class TypedRunEvidenceTests(Base):
    def fixture(self, root, authored):
        from schemaxis.artifacts import atomic_json
        prepared = adaptor.plan(authored)
        for name, value in [('authored.json', authored), ('plan.json', prepared), ('result.json', {'verified': True}),
                            ('runtime.json', {'runtime': 'LibreOffice 26.8.1.1'})]:
            atomic_json(root / name, value)
        node = prepared['nodes'][0]
        if node['filter'] == 'readTypedCSV':
            payload = Path(node['options']['file']).read_bytes()
            (root / 'source.csv').write_bytes(payload)
            import hashlib
            atomic_json(root / 'source.json', {'file': node['options']['file'], 'sha256': hashlib.sha256(payload).hexdigest()})
        else:
            atomic_json(root / 'source.json', {})
        built = adaptor.table_for(prepared, root)
        (root / 'data.csv').write_bytes(typed_table.csv_bytes(built))
        for name in ('analysis.xlsx', 'analysis.ods'):
            (root / name).write_bytes(b'host-only placeholder')
        return built

    def test_typed_evidence_is_regenerated_independently_and_every_member_is_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            built = self.fixture(root, document())
            observed = typed_workbook.expected(built)
            with patch.object(typed_workbook, 'verify_workbook', return_value=observed):
                result = adaptor._native_verify(root, require_result=False)
                self.assertEqual((result['rows'], result['columns']), (4, 3))
                adaptor._native_verify(root)
                record = json.loads((root / 'verification.json').read_text())
                self.assertIn('typedSummarySHA256', record)
                self.assertEqual(len(record['artifacts']), 3)
                pristine = {name: (root / name).read_bytes() for name in ('typed-summary.json', 'data.csv', 'verification.json')}
                summary = json.loads(pristine['typed-summary.json'])
                for name, mutate in [('summary count', lambda s: s['columns'][1].update(present=4)),
                                     ('summary digest', lambda s: s['columns'][0].update(valuesSHA256='0' * 64)),
                                     ('summary token', lambda s: s.update(nullToken='NA')),
                                     ('summary extra key', lambda s: s.update(note='x')),
                                     ('summary column removed', lambda s: s['columns'].pop())]:
                    with self.subTest(name):
                        changed = copy.deepcopy(summary)
                        mutate(changed)
                        (root / 'typed-summary.json').write_text(json.dumps(changed))
                        self.assertEqual(self.fault(adaptor._native_verify, root).code, 'VERIFICATION_FAILED')
                (root / 'typed-summary.json').write_bytes(pristine['typed-summary.json'])
                for name, payload in [('altered id', pristine['data.csv'].replace(b'"00123"', b'"0123"')),
                                      ('blank to zero', pristine['data.csv'].replace(b'\\N', b'0.0', 1)),
                                      ('token loss', pristine['data.csv'].replace(b'\\N', b'""', 1)),
                                      ('truncated', pristine['data.csv'][:-12])]:
                    with self.subTest(name):
                        (root / 'data.csv').write_bytes(payload)
                        self.assertEqual(self.fault(adaptor._native_verify, root).code, 'VERIFICATION_FAILED')
                (root / 'data.csv').write_bytes(pristine['data.csv'])
                record['typedSummarySHA256'] = '0' * 64
                (root / 'verification.json').write_text(json.dumps(record))
                self.assertEqual(self.fault(adaptor._native_verify, root).code, 'VERIFICATION_FAILED')
                (root / 'verification.json').write_bytes(pristine['verification.json'])
                (root / 'typed-summary.json').unlink()
                (root / 'typed-summary.json').symlink_to(root / 'data.csv')
                self.assertEqual(self.fault(adaptor._native_verify, root).code, 'VERIFICATION_FAILED')
                (root / 'typed-summary.json').unlink()
                (root / 'typed-summary.json').write_bytes(pristine['typed-summary.json'])
                adaptor._native_verify(root)

    def test_typed_handoff_declares_its_format_and_the_numeric_manifest_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('analysis.xlsx', 'analysis.ods', 'data.csv'):
                (root / name).write_bytes(b'x')
            numeric = adaptor.manifest(root)
            self.assertEqual([set(a) for a in numeric], [{'file', 'kind', 'sha256'}] * 3)
            typed_records = adaptor.manifest(root, '\\N')
            self.assertEqual(typed_records[:2], numeric[:2])
            handoff = typed_records[2]
            self.assertEqual(handoff['kind'], 'table')
            self.assertEqual(handoff['identity'], {'kind': 'table', 'format': 'schemaxis.calc.typed-csv/1', 'nullToken': '\\N'})
            self.assertTrue(any('Empty text' in loss for loss in handoff['losses']))

    def test_captured_csv_staleness_and_edits_are_detected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'in.csv'
            source.write_bytes(typed_table.csv_bytes(typed()))
            run = root / 'run'
            run.mkdir()
            built = self.fixture(run, csv_document(source))
            observed = typed_workbook.expected(built)
            with patch.object(typed_workbook, 'verify_workbook', return_value=observed):
                adaptor._native_verify(run, require_result=False)
                adaptor._native_verify(run)
                # The original may change or vanish: the retained capture is the authority.
                source.write_bytes(b'garbage')
                adaptor._native_verify(run)
                source.unlink()
                adaptor._native_verify(run)
                captured = (run / 'source.csv').read_bytes()
                (run / 'source.csv').write_bytes(captured.replace(b'"00123"', b'"00124"'))
                self.assertEqual(self.fault(adaptor._native_verify, run).code, 'VERIFICATION_FAILED')
                (run / 'source.csv').write_bytes(captured)
                provenance = json.loads((run / 'source.json').read_text())
                provenance['sha256'] = '0' * 64
                (run / 'source.json').write_text(json.dumps(provenance))
                self.assertEqual(self.fault(adaptor._native_verify, run).code, 'VERIFICATION_FAILED')

    def test_fingerprints_change_with_source_bytes_and_authored_identity_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'in.csv'
            source.write_bytes(typed_table.csv_bytes(typed()))
            authored = csv_document(source)
            first = adaptor.reusableInputs(authored)
            self.assertEqual(list(first), [str(source)])
            self.assertEqual(adaptor.reusableInputs(authored), first)
            source.write_bytes(source.read_bytes().replace(b'"00123"', b'"00124"'))
            self.assertNotEqual(adaptor.reusableInputs(authored), first)
            self.assertEqual(adaptor.reusableInputs(document()), {})
            plans = [adaptor.plan(a) for a in (document(), document(nullToken='NA'),
                                               document(rows=[['00124', 1.5, '=1+2'], *ROWS[1:]]),
                                               document(rows=[ROWS[0], ['café', 0, '+SUM(A1:A2)'], *ROWS[2:]]))]
            digests = {json.dumps(p, sort_keys=True) for p in plans}
            self.assertEqual(len(digests), 4)

    def test_typed_csv_faults_precede_any_native_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'bad.csv'
            source.write_text('"Part ID","Mass (g)","Note"\n"a",x,"n"\n"b",2,"m"\n')
            with patch.object(adaptor, 'execute', side_effect=AssertionError('native must not launch')):
                fault = self.fault(adaptor.run, csv_document(source), root / 'attempt', executable=__import__('sys').executable)
            self.assertEqual((fault.code, fault.location), ('INVALID_TABLE', 'rows[0][1]'))
            self.assertEqual(fault.observed['record'], 2)
            self.assertEqual(fault.observed['column'], 'Mass (g)')
            self.assertEqual(json.loads((root / 'attempt' / 'result.json').read_text())['status'], 'failed')

    def test_deadline_and_cancellation_block_typed_publication(self):
        import sys
        for cancelled in (False, True):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / 'attempt'
                clock = [0]

                def native(command, directory, name, *args, **kwargs):
                    if name == 'version':
                        (directory / 'version.stdout').write_text('LibreOffice 26.8.1.1')
                    else:
                        (directory / name / ('analysis.' + name)).write_bytes(b'host-only placeholder')

                def verified(*args, **kwargs):
                    clock[0] = 0 if cancelled else 2
                    return {'verified': True}
                with patch.object(adaptor, 'execute', side_effect=native), patch.object(typed_workbook, 'verify_workbook'), \
                        patch.object(adaptor, 'verify', side_effect=verified), \
                        patch.object(adaptor.time, 'monotonic', side_effect=lambda: clock[0]), \
                        patch.object(adaptor, 'cancellation_requested', return_value=cancelled):
                    fault = self.fault(adaptor._native_run, document(), root, executable=sys.executable, timeout=1)
                self.assertEqual(fault.code, 'RUNNER_CANCELLED' if cancelled else 'RUNNER_TIMED_OUT')
                self.assertEqual(json.loads((root / 'result.json').read_text())['status'], 'failed')


class ContractTests(Base):
    def test_authored_schema_matches_the_declared_operations(self):
        variants = adaptor.schema()['properties']['nodes']['items']['oneOf']
        required = {v['properties']['filter']['const']: v['properties']['options']['required'] for v in variants}
        self.assertEqual(required, {'fromRows': ['columns', 'rows'], 'readCSV': ['file'],
                                    'fromTypedRows': ['columns', 'rows'], 'readTypedCSV': ['file', 'columns']})
        options = {v['properties']['filter']['const']: v['properties']['options']['properties'] for v in variants}
        self.assertEqual(options['fromTypedRows']['nullToken']['default'], '\\N')
        cell = options['fromTypedRows']['rows']['items']['items']
        self.assertEqual(len(cell['anyOf']), 3)
        self.assertIn({'enum': [None]}, cell['anyOf'])
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            return
        validator = Draft202012Validator(adaptor.schema())
        self.assertTrue(validator.is_valid(document()))
        for broken in (document(columns=[{'name': 'a', 'kind': 'date'}], rows=[['x']]), {**document(), 'extra': 1}):
            self.assertFalse(validator.is_valid(broken))

    def test_packaged_typed_examples_plan_and_the_fixture_is_canonical(self):
        root = Path(__file__).resolve().parents[2] / 'examples' / 'schemaxis'
        for name in ('calc-typed-parts.json', 'calc-typed-parts-variant.json'):
            planned = adaptor.plan(json.loads((root / name).read_text(encoding='utf-8')))
            self.assertEqual(planned['nodes'][0]['filter'], 'fromTypedRows')
        fault = self.fault(adaptor.plan, json.loads((root / 'calc-typed-parts-invalid.json').read_text(encoding='utf-8')))
        self.assertEqual((fault.code, fault.location), ('INVALID_TABLE', 'rows[0][0]'))
        baseline = adaptor.plan(json.loads((root / 'calc-typed-parts.json').read_text(encoding='utf-8')))['nodes'][0]['options']
        built = typed_table.validate(baseline['columns'], baseline['rows'], baseline['nullToken'])
        fixture = (root / 'fixtures' / 'calc' / 'typed-parts.csv').read_bytes()
        self.assertEqual(fixture, typed_table.csv_bytes(built))
        self.assertEqual(typed_table.parse_csv(fixture, baseline['columns'], baseline['nullToken'])['rows'], built['rows'])

    def test_a_different_declared_token_does_not_reinterpret_the_file(self):
        payload = b'"id","v"\n"a",1\n"b",\\N\n"c",3\n'
        required = [{'name': 'id', 'kind': 'text'}, {'name': 'v', 'kind': 'number', 'nullable': True}]
        self.assertEqual(typed_table.parse_csv(payload, required)['rows'][1], ['b', None])
        fault = self.fault(typed_table.parse_csv, payload, required, 'NA')
        self.assertEqual((fault.code, fault.location), ('INVALID_TABLE', 'rows[1][1]'))
        text_only = [{'name': 'id', 'kind': 'text'}, {'name': 'v', 'kind': 'text', 'nullable': True}]
        self.assertEqual(typed_table.parse_csv(b'"id","v"\n"a","\\N"\n', text_only, 'NA')['rows'][0], ['a', '\\N'])

    def test_sqlite_style_summary_csv_dialect_is_readable_by_explicit_path(self):
        # Shape of the SQLite adaptor's summary.csv: csv.writer defaults (CRLF, minimal quoting) and a bare \N null.
        payload = 'g0,row_count,total\r\nnorth,2,15\r\n\\N,1,\\N\r\n"a, ""b""",3,-4\r\n'.encode()
        columns = [{'name': 'g0', 'kind': 'text', 'nullable': True}, {'name': 'row_count', 'kind': 'number'},
                   {'name': 'total', 'kind': 'number', 'nullable': True}]
        parsed = typed_table.parse_csv(payload, columns)
        self.assertEqual(parsed['rows'], [['north', 2.0, 15.0], [None, 1.0, None], ['a, "b"', 3.0, -4.0]])


class NumericPathUnchangedTests(Base):
    def test_numeric_operations_keep_their_closed_numeric_grammar(self):
        numeric = {'version': 'schemaxis.calc/1', 'nodes': [{'id': 'n', 'filter': 'fromRows',
                   'options': {'columns': ['a', 'b'], 'rows': [[1, 2], [3, 4]]}}]}
        self.assertEqual(adaptor.plan(numeric)['sheets'], ['Data', 'Summary'])
        for bad in ([1, None], [1, '2'], [1, True]):
            numeric['nodes'][0]['options']['rows'][1] = bad
            self.assertTrue(self.fault(adaptor.plan, numeric).code)
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'n.csv'
            source.write_bytes(b'a,b\n1,\n3,4\n')
            numeric = {'version': 'schemaxis.calc/1', 'nodes': [{'id': 'n', 'filter': 'readCSV', 'options': {'file': str(source)}}]}
            self.assertEqual(self.fault(adaptor.parse_source_csv, source.read_bytes()).code, 'INVALID_TABLE')
            self.assertTrue(adaptor.plan(numeric))
        # The typed null token must never leak into numeric CSV coercion.
        self.assertEqual(self.fault(adaptor.parse_source_csv, b'a,b\n1,\\N\n3,4\n').code, 'INVALID_TABLE')

    def test_numeric_route_has_no_typed_sidecar_fields(self):
        self.assertNotIn('nullToken', adaptor.OPTIONS['fromRows'])
        self.assertNotIn('nullToken', adaptor.OPTIONS['readCSV'])
        self.assertEqual(set(adaptor.OPTIONS), {'fromRows', 'readCSV', 'fromTypedRows', 'readTypedCSV'})


class GenericFileProducerTests(Base):
    """A producer that publishes a regular CSV `file` artifact (for example SQLite summary.csv) can bind readTypedCSV."""
    COLUMNS = [{'name': 'g0', 'kind': 'text', 'nullable': True}, {'name': 'row_count', 'kind': 'number'},
               {'name': 'total', 'kind': 'number', 'nullable': True}]
    # Exactly the dialect csv.writer(lineterminator='\\n') produces: unquoted text, \\N for NULL, no number formatting.
    SQLITE = b'g0,row_count,total\n\\N,1,3\n-02,1,\\N\n00123,2,10\n=1+2,1,0\n@part-7,1,7\nZurich B,2,-4\n'

    def test_route_accepts_table_and_generic_file_but_no_other_kind(self):
        from schemaxis.adaptors import registry
        accepted = registry.resolve({'version': 'schemaxis.calc/1'}, legacy=True)[1]['acceptedArtifacts']
        self.assertEqual(sorted(accepted), ['file', 'table'])
        for kind in ('text', 'image', 'spreadsheet', 'geometry'):
            self.assertNotIn(kind, accepted)

    def test_producer_csv_is_read_as_exact_typed_rows(self):
        parsed = typed_table.parse_csv(self.SQLITE, self.COLUMNS)
        self.assertEqual(parsed['rows'], [[None, 1.0, 3.0], ['-02', 1.0, None], ['00123', 2.0, 10.0], ['=1+2', 1.0, 0.0],
                                          ['@part-7', 1.0, 7.0], ['Zurich B', 2.0, -4.0]])
        self.assertTrue(all(type(r[1]) is float for r in parsed['rows']))

    def test_file_kind_does_not_make_the_content_trusted(self):
        executable = os.path.realpath('/bin/sh')
        hostile = {'binary': b'SQLite format 3\x00\x99\xff' * 4, 'empty label': b'g0,row_count,total\n,1,3\n',
                   'padded number': b'g0,row_count,total\na, 1,3\n', 'quoted number': b'g0,row_count,total\na,"1,000",3\n',
                   'null in required': b'g0,row_count,total\na,\\N,3\n', 'renamed header': b'label,row_count,total\na,1,3\n',
                   'extra column': b'g0,row_count,total\na,1,3,4\n', 'header only': b'g0,row_count,total\n'}
        for label, payload in hostile.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as temporary:
                source = Path(temporary) / 'summary.csv'
                source.write_bytes(payload)
                out = Path(temporary) / 'out'
                fault = self.fault(adaptor.run, csv_document(source, self.COLUMNS), out, executable=executable)
                self.assertEqual(fault.code, 'INVALID_TABLE', label)
                self.assertFalse(list(out.rglob('analysis.*')) if out.exists() else [], 'no native work before validation')

    def test_binary_file_fault_names_the_encoding_problem(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'summary.sqlite'
            source.write_bytes(b'SQLite format 3\x00' + bytes(range(128, 200)))
            fault = self.fault(adaptor.run, csv_document(source, self.COLUMNS), Path(temporary) / 'out', executable=os.path.realpath('/bin/sh'))
            self.assertIn('UTF-8', fault.message)

    def test_changed_producer_bytes_change_the_reusable_input_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'summary.csv'
            source.write_bytes(self.SQLITE)
            first = adaptor.reusableInputs(csv_document(source, self.COLUMNS))
            source.write_bytes(self.SQLITE.replace(b'00123,2,10', b'00123,2,11'))
            second = adaptor.reusableInputs(csv_document(source, self.COLUMNS))
            self.assertEqual(list(first), list(second))
            self.assertNotEqual(first, second)


if __name__ == '__main__':
    unittest.main()
