# Copyright (C) 2026 David L F Gaden
"""Independent Arrow host semantics and malformed closed-Parquet rejection."""
import calendar
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

from schemaxis.adaptors.apachearrow import adaptor as a, parquet as p, reference as r
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'tests/fixtures/apachearrow-flat.parquet'


def unsigned(number):
    out = bytearray()
    while number >= 128:
        out.append((number & 127) | 128)
        number >>= 7
    return bytes(out + bytes([number]))


def encode(kind, value):
    """Test-only metadata encoder to change semantics while keeping valid framing."""
    if kind in (1, 2): return b''
    if kind in (4, 5, 6): return unsigned(value * 2 if value >= 0 else -value * 2 - 1)
    if kind == 8: return unsigned(len(value)) + value
    if kind == 9:
        element, values = value
        header = bytes([(min(len(values), 15) << 4) | element])
        if len(values) >= 15: header += unsigned(len(values))
        return header + b''.join(encode(element, item) for item in values)
    if kind == 12:
        out, previous = b'', 0
        for identifier, (wire, item) in value.items():
            delta = identifier - previous
            out += bytes([(delta << 4) | wire]) if 0 < delta < 16 else bytes([wire]) + encode(4, identifier)
            out += encode(wire, item)
            previous = identifier
        return out + b'\0'
    raise ValueError('unknown test wire type')


def changed_footer(data, change):
    size = struct.unpack('<I', data[-8:-4])[0]
    start = len(data) - size - 8
    metadata = p.Reader(data[start:-8]).value(12)
    change(metadata)
    new = encode(12, metadata)
    return data[:start] + new + struct.pack('<I', len(new)) + b'PAR1'


class ArrowTests(unittest.TestCase):
    def setUp(self):
        self.doc = json.loads((ROOT / 'examples/schemaxis/apachearrow-measurements.json').read_text())
        self.doc['source'] = str(ROOT / 'examples/schemaxis/fixtures/apachearrow/measurements.csv')
        self.plan = a.plan(self.doc)
        self.data = Path(self.doc['source']).read_bytes()
        self.rows = r.source(self.data, self.plan['columns'])

    def fault(self, document, code):
        with self.assertRaises(SchemaxisError) as caught: a.plan(document)
        self.assertEqual(caught.exception.fault.code, code)

    def test_planning_is_immutable_and_semantics_located(self):
        before = copy.deepcopy(self.doc)
        self.assertEqual(a.plan(self.doc), self.plan)
        self.assertEqual(self.doc, before)
        self.assertEqual(self.plan['where'], [])
        d = copy.deepcopy(self.doc);d['columns'][1]['name'] = 'id';self.fault(d, 'INVALID_ARROW_COLUMN')
        d = copy.deepcopy(self.doc);d['select'][0]['cast'] = 'int64';self.fault(d, 'INVALID_ARROW_SELECTION')
        d = copy.deepcopy(self.doc);d['select'][0]['fillNull'] = '0';self.fault(d, 'INVALID_ARROW_SELECTION')
        d = copy.deepcopy(self.doc);d['where'] = [{'column': 'label', 'test': 'lt', 'value': 'z'}];self.fault(d, 'INVALID_ARROW_PREDICATE')
        d['where'] = [{'column': 'id', 'test': 'isNull', 'value': '0'}];self.fault(d, 'INVALID_ARROW_PREDICATE')
        d['where'] = [{'column': 'id', 'test': 'eq'}];self.fault(d, 'INVALID_ARROW_PREDICATE')
        d['where'] = [{'column': 'id', 'test': 'eq', 'value': '9223372036854775808'}];self.fault(d, 'INVALID_ARROW_LITERAL')
        self.fault({**self.doc, 'source': 'relative.csv'}, 'INVALID_ARROW_SOURCE')
        for key in ('metadata', 'unit', 'python'):
            with self.assertRaises(SchemaxisError): a.plan({**self.doc, key: 'unsupported'})
        for key in ('metadata', 'unit'):
            d = copy.deepcopy(self.doc);d['columns'][0][key] = 'unsupported'
            with self.assertRaises(SchemaxisError): a.plan(d)

    def test_exact_source_and_report_oracle(self):
        self.assertEqual(self.rows, [[9007199254740993, -2147483648, -0.0, True, '', -1],
            [9223372036854775807, 2147483647, 1.5, False, 'NA', 951782400000001],
            [-9223372036854775808, 0, None, None, None, None], [4, 1, .1, True, 'café, snow 雪', 0]])
        self.assertEqual(struct.pack('<d', self.rows[0][2]).hex(), '0000000000000080')
        report = r.report(self.plan, self.rows, 'sha')
        self.assertEqual(report['rows'][0][0], '9007199254740993')
        self.assertEqual(report['rows'][0][-1], '1969-12-31T23:59:59.999999Z')
        self.assertEqual(report['nullCounts'], [0, 0, 1, 1, 1, 1])
        d = copy.deepcopy(self.doc);d['where'] = [{'column': 'label', 'test': 'isNull'}]
        d['select'] = [{'column': 'label', 'name': 'name', 'fillNull': 'unknown'}, {'column': 'small', 'name': 'wide', 'cast': 'int64'}]
        columns, rows, indices = r.transform(a.plan(d), self.rows)
        self.assertEqual(rows, [['unknown', 0]]);self.assertEqual(indices, [2])
        self.assertEqual(columns, [{'name': 'name', 'type': 'utf8', 'nullable': False}, {'name': 'wide', 'type': 'int64', 'nullable': False}])
        self.assertFalse(r.equal([[True]], [[1]]));self.assertFalse(r.equal([[-0.0]], [[0.0]]))

    def test_lexical_extremes_and_refusals(self):
        for raw in ['+1', '01', '-0', ' 1', '1 ', '1.0', '9223372036854775808', '-9223372036854775809']:
            with self.subTest(raw=raw), self.assertRaises(ValueError): r.scalar(raw, 'int64')
        for raw in ['NaN', 'inf', 'Infinity', '1e309', '1e-400', '0x1p0', '1,2', '.5']:
            with self.subTest(raw=raw), self.assertRaises(ValueError): r.scalar(raw, 'float64')
        for raw in ['1970-01-01T00:00:00', '1970-01-01T00:00:00-01:00', '1970-01-01T00:00:00.0000000Z', '2001-02-29T00:00:00Z', '2000-01-01T00:00:60Z']:
            with self.subTest(raw=raw), self.assertRaises(ValueError): r.scalar(raw, 'timestamp_us_utc')
        self.assertEqual(r.scalar('0001-01-01T00:00:00Z', 'timestamp_us_utc'), -62135596800000000)
        self.assertEqual(r.scalar('5e-324', 'float64'), 5e-324)
        columns = [{'name': 'text', 'type': 'utf8', 'nullable': True}]
        self.assertEqual(r.source(b'text\n""\n"\\N"\n"line\nnext"\n"a""b"\n', columns), [[''], [None], ['line\nnext'], ['a"b']])
        for raw in [b'text\nfoo"bar\n', b'text\n"a"x\n', b'text\n"open\n', b'text\rabc\r', b'\xef\xbb\xbftext\n', b'text\n\xff', b'text\n\x00', b'text\na,b\n', b'text\n' + b'a' * 4097 + b'\n']:
            with self.subTest(raw=raw[:40]), self.assertRaises((ValueError, UnicodeError)): r.source(raw, columns)

    def test_subsecond_grammar_is_host_independent(self):
        # Before Python 3.11 datetime.fromisoformat accepts only 3 or 6 fractional
        # digits (https://docs.python.org/3.10/library/datetime.html). No such
        # interpreter ran here: require that the parser is never asked and that the
        # datetime constructor receives canonical, explicit components instead.
        received = []
        class Recording(datetime):
            def __new__(cls, *args):
                received.append(args)
                return super().__new__(cls, *args)
            @classmethod
            def fromisoformat(cls, text):
                raise AssertionError('fraction grammar must not depend on fromisoformat: ' + text)
        base = calendar.timegm((2026, 1, 1, 0, 0, 0)) * 1000000
        original, r.datetime = r.datetime, Recording
        try:
            for zone in ('Z', '+00:00'):
                for digits in range(7):
                    fraction = '123456'[:digits]
                    text = '2026-01-01T00:00:00' + ('.' + fraction if fraction else '') + zone
                    with self.subTest(text=text):
                        received.clear()
                        self.assertEqual(r.scalar(text, 'timestamp_us_utc'), base + int(fraction.ljust(6, '0') or 0))
                        self.assertEqual(received, [(2026, 1, 1, 0, 0, 0, int(fraction.ljust(6, '0') or 0), timezone.utc)])
            received.clear()
            self.assertEqual(r.scalar('1969-12-31T23:59:59.5Z', 'timestamp_us_utc'), -500000)
            self.assertEqual(r.scalar('0001-01-01T00:00:00.1+00:00', 'timestamp_us_utc'), -62135596799900000)
            self.assertEqual(r.scalar('9999-12-31T23:59:59.99999Z', 'timestamp_us_utc'), 253402300799999990)
            self.assertEqual(r.scalar('2024-02-29T12:30:45.05Z', 'timestamp_us_utc'), calendar.timegm((2024, 2, 29, 12, 30, 45)) * 1000000 + 50000)
            for raw in ['1970-01-01T00:00:00.1234567Z', '1970-01-01T00:00:00.0000000+00:00', '1970-01-01T00:00:00.Z', '1970-01-01T00:00:00.+00:00',
                        '1970-01-01T00:00:00,5Z', '1970-01-01T00:00:00.5', '1970-01-01T00:00:00.5+01:00', '1970-01-01T00:00:00.5-00:00',
                        '1970-01-01T00:00:00.5+00:00:00', '1970-01-01T00:00:00.5+0000', '1970-01-01T00:00:00.5z', '1970-01-01t00:00:00.5Z',
                        '1970-01-01 00:00:00.5Z', '1970-01-01T00:00.5Z', '1970-01-01T00:00:00.5ZZ', '1970-01-01T00:00:00.5Z\n',
                        ' 1970-01-01T00:00:00.5Z', '1970-01-01T00:00:00.\u0665Z', '\u0661970-01-01T00:00:00Z', '1970-1-1T00:00:00.5Z',
                        '1970-13-01T00:00:00.5Z', '1970-00-01T00:00:00.5Z', '1970-01-00T00:00:00.5Z', '1970-02-30T00:00:00.5Z',
                        '1900-02-29T00:00:00.5Z', '1970-01-01T24:00:00.5Z', '1970-01-01T00:60:00.5Z', '1970-01-01T00:00:60.5Z',
                        '0000-01-01T00:00:00.5Z']:
                with self.subTest(raw=raw), self.assertRaises(ValueError): r.scalar(raw, 'timestamp_us_utc')
        finally:
            r.datetime = original

    def test_subsecond_literals_rows_and_retained_evidence(self):
        document = {'version': a.VERSION, 'operation': 'prepareTable', 'source': self.doc['source'],
                    'columns': [{'name': 'id', 'type': 'int32', 'nullable': False}, {'name': 'seen', 'type': 'timestamp_us_utc', 'nullable': True}],
                    'where': [{'column': 'seen', 'test': 'ge', 'value': '2026-01-01T00:00:00.12345+00:00'}],
                    'select': [{'column': 'id', 'name': 'id'}, {'column': 'seen', 'name': 'seen', 'fillNull': '2026-01-01T00:00:00.5Z'}]}
        planned = a.plan(document)
        for value in ('2026-01-01T00:00:00.1Z', '2026-01-01T00:00:00.1234Z'):
            a.plan({**document, 'where': [{'column': 'seen', 'test': 'eq', 'value': value}]})
        for value in ('2026-01-01T00:00:00.1234567Z', '2026-01-01T00:00:00.5+01:00', '2026-01-01T00:00:00.Z'):
            d = {**document, 'where': [{'column': 'seen', 'test': 'eq', 'value': value}]}
            with self.assertRaises(SchemaxisError) as caught: a.plan(d)
            self.assertEqual((caught.exception.fault.code, caught.exception.fault.location), ('INVALID_ARROW_LITERAL', '$.where[0].value'))
        with self.assertRaises(SchemaxisError) as caught:
            a.plan({**document, 'select': [{'column': 'seen', 'name': 'seen', 'fillNull': '2026-01-01T00:00:00.1234567Z'}]})
        self.assertEqual((caught.exception.fault.code, caught.exception.fault.location), ('INVALID_ARROW_LITERAL', '$.select[0].fillNull'))
        data = ('id,seen\n1,2026-01-01T00:00:00.1Z\n2,2026-01-01T00:00:00.12345Z\n3,2026-01-01T00:00:00.123456+00:00\n'
                '4,\\N\n5,2026-01-01T00:00:00.5Z\n6,2026-01-01T00:00:00.123Z\n').encode()
        rows = a.source_rows(data, planned)
        base = calendar.timegm((2026, 1, 1, 0, 0, 0)) * 1000000
        self.assertEqual([row[1] for row in rows], [base + 100000, base + 123450, base + 123456, None, base + 500000, base + 123000])
        report = r.report(planned, rows, 'sha')
        self.assertEqual(report['sourceRowIndices'], [1, 2, 4])
        self.assertEqual(report['rows'], [[2, '2026-01-01T00:00:00.123450Z'], [3, '2026-01-01T00:00:00.123456Z'], [5, '2026-01-01T00:00:00.500000Z']])
        self.assertEqual(r.wire_rows(planned['columns'], rows)[1], [2, str(base + 123450)])
        # A row-level fault stays located by row and column.
        with self.assertRaises(SchemaxisError) as caught:
            a.source_rows(b'id,seen\n1,2026-01-01T00:00:00.1234567Z\n', planned)
        self.assertEqual((caught.exception.fault.code, caught.exception.fault.location), ('INVALID_ARROW_DATA', '$.source'))
        self.assertIn('row 0, column seen', caught.exception.fault.message)
        # The reference implementation is part of the retained fingerprint, so older
        # retained runs are refused and must be rerun with the current code.
        fingerprint = a.implementation()
        self.assertEqual(fingerprint['reference.py'], hashlib.sha256(Path(r.__file__).read_bytes()).hexdigest())
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            (run / 'authored.json').write_text(json.dumps(document));(run / 'plan.json').write_text(json.dumps(planned))
            (run / 'verification.json').write_text('{}')
            (run / 'implementation.json').write_text(json.dumps({**fingerprint, 'reference.py': '0' * 64}))
            with self.assertRaises(SchemaxisError) as caught: a.verify(run)
            self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')
            self.assertIn('implementation changed', caught.exception.fault.message)

    def test_independent_native_parquet_fixture(self):
        decoded = p.read(FIXTURE.read_bytes(), self.plan['outputColumns'])
        self.assertTrue(r.equal(decoded, self.rows))
        with self.assertRaisesRegex(ValueError, 'schema'): p.read(FIXTURE.read_bytes(), list(reversed(self.plan['outputColumns'])))

    def test_metadata_tampering_after_valid_reserialisation(self):
        data = FIXTURE.read_bytes()
        # Access the first group's first chunk metadata without changing any offsets.
        def first(meta): return meta[4][1][1][0][1][1][1][0][3][1]
        changes = {
            'opaqueArrowSchema': lambda x: x.update({5: (9, (12, [{1: (8, b'ARROW:schema'), 2: (8, b'opaque')}]))}),
            'wrongRowWireType': lambda x: x.update({3: (5, 4)}),
            'wrongRows': lambda x: x.update({3: (6, 5)}),
            'wrongTimestampUTC': lambda x: x[2][1][1][-1][10][1][8][1].update({1: (2, False)}),
            'wrongNullable': lambda x: x[2][1][1][1].update({3: (5, 1)}),
            'externalFile': lambda x: x[4][1][1][0][1][1][1][0].update({1: (8, b'foreign.parquet')}),
            'offsetOverlap': lambda x: first(x).update({9: (6, 3)}),
            'offsetBeyond': lambda x: first(x).update({9: (6, len(data))}),
            'negativeSize': lambda x: first(x).update({7: (6, -1)}),
            'compressed': lambda x: first(x).update({4: (5, 1)}),
            'dictionaryOffset': lambda x: first(x).update({11: (6, 4)}),
            'badPageCount': lambda x: first(x)[13][1][1][0].update({3: (5, 9)}),
        }
        for name, change in changes.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                p.read(changed_footer(data, change), self.plan['outputColumns'])

    def test_compact_and_payload_corruption(self):
        for raw in (b'\x15\x00\x05\x02\x00', b'\x15' + b'\x80' * 10, b'\x15\x80\x00\x00', b'\x1b\x00', b'\x19\xf5\xff\xff\xff\x7f'):
            with self.subTest(raw=raw), self.assertRaises(ValueError): p.Reader(raw).value(12)
        data = FIXTURE.read_bytes()
        for bad in (data[:-1], b'NOPE' + data[4:], data[:-8] + b'\xff' * 4 + b'PAR1'):
            with self.assertRaises(ValueError): p.read(bad, self.plan['outputColumns'])
        page_reader = p.Reader(data[4:]);page_reader.value(12)
        altered = bytearray(data);altered[4 + page_reader.pos] ^= 1
        self.assertFalse(r.equal(p.read(altered, self.plan['outputColumns']), self.rows))
        for stream in (b'\x00', b'\x04\x02', b'\x02\x01\x02\x00', b'\x03\xff'):
            with self.assertRaises(ValueError): p.definitions(p.Reader(struct.pack('<I', len(stream)) + stream), 1, True)
        with self.assertRaises(ValueError): p.plain(p.Reader(b'\x80'), 0, 1)

    def test_bounded_files_and_current_source_reuse(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'input.csv';source.write_bytes(self.data)
            doc = {**self.doc, 'source': str(source)}
            before = a.reusableInputs(doc)
            source.write_bytes(self.data.replace(b'9007199254740993', b'9007199254740994'))
            self.assertNotEqual(a.reusableInputs(doc), before)
            link = Path(folder) / 'link.csv';link.symlink_to(source)
            with self.assertRaises(SchemaxisError): a.bounded(link)
            with self.assertRaises(SchemaxisError): a.bounded(source, limit=1)

    def test_host_import_boundary_and_schema(self):
        code = 'import sys;from schemaxis.adaptors.apachearrow import adaptor;adaptor.schema();assert not any(x.startswith(("pyarrow","numpy","pandas")) for x in sys.modules)'
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(a.schema()['additionalProperties'])
        self.assertEqual(set(a.schema()['properties']), {'version', 'operation', *a.OPTIONS})

    def test_full_source_validation_and_fill_budget_before_native(self):
        doc = copy.deepcopy(self.doc)
        doc['where'] = [{'column': 'id', 'test': 'eq', 'value': '4'}]
        with self.assertRaises(SchemaxisError) as caught:
            a.source_rows(self.data.replace(b'1.5,false', b'NaN,false'), a.plan(doc))
        self.assertEqual(caught.exception.fault.code, 'INVALID_ARROW_DATA')
        doc = {'version': a.VERSION, 'operation': 'prepareTable', 'source': '/tmp/input.csv',
               'columns': [{'name': 'label', 'type': 'utf8', 'nullable': True}],
               'select': [{'column': 'label', 'name': 'label', 'fillNull': 'x' * 4096}]}
        with self.assertRaises(SchemaxisError) as caught:
            a.source_rows(b'label\n' + b'\\N\n' * 2100, a.plan(doc))
        self.assertEqual(caught.exception.fault.code, 'INVALID_ARROW_DATA')

    def csv_document(self, **changes):
        return {**copy.deepcopy(self.doc), 'publishCSV': True, **changes}

    def test_publish_option_is_closed_and_absent_equals_false(self):
        legacy = a.plan(self.doc)
        self.assertNotIn('publishCSV', legacy)
        self.assertEqual(a.plan({**self.doc, 'publishCSV': False}), legacy)
        self.assertEqual(a.config(legacy), {key: legacy[key] for key in ('columns', 'where', 'select', 'outputColumns')})
        self.assertEqual([name for name, _ in a.publications(legacy)], ['table.parquet', 'table-report.json'])
        self.assertEqual(a.evidence_names(legacy), a.evidence_names({'publishCSV': False}))
        self.assertFalse(any('csv' in name and name != 'source.csv' for name in a.evidence_names(legacy)))
        published = a.plan(self.csv_document())
        self.assertIs(published['publishCSV'], True)
        self.assertEqual(published['outputColumns'], legacy['outputColumns'])
        self.assertEqual(published['losses'][:len(legacy['losses'])], legacy['losses'])
        self.assertGreater(len(published['losses']), len(legacy['losses']))
        self.assertIs(a.config(published)['publishCSV'], True)
        self.assertEqual([item for item in a.publications(published)], [('table.parquet', 'file'), ('table-report.json', 'text'), ('table.csv', 'file')])
        self.assertTrue({'csvreadback' + suffix for suffix in ('.stdout', '.stderr', '-inputs.json', '-submission.json')} <= a.evidence_names(published))
        schema = a.schema()['properties']['publishCSV']
        self.assertEqual(schema['type'], 'boolean');self.assertIs(schema['default'], False)
        for value in ('yes', 'true', 1, 0, None, [], {}):
            with self.subTest(value=value), self.assertRaises(SchemaxisError) as caught:
                a.plan({**self.doc, 'publishCSV': value})
            self.assertEqual((caught.exception.fault.code, caught.exception.fault.location), ('INVALID_ARGUMENT', '$.publishCSV'))
            self.assertTrue(caught.exception.fault.recovery)
        # No arbitrary writer option can be supplied.
        for key in ('csvOptions', 'nullString', 'delimiter', 'quoting', 'eol', 'includeHeader', 'compression'):
            with self.subTest(key=key), self.assertRaises(SchemaxisError): a.plan({**self.doc, key: ','})

    def test_canonical_csv_bytes_literal_oracle(self):
        columns, rows, _ = r.transform(a.plan(self.csv_document()), self.rows)
        expected = ('id,small,reading,enabled,label,observed\n'
                    '9007199254740993,-2147483648,-0,true,"","1969-12-31T23:59:59.999999Z"\n'
                    '9223372036854775807,2147483647,1.5,false,"NA","2000-02-29T00:00:00.000001Z"\n'
                    '-9223372036854775808,0,\\N,\\N,\\N,\\N\n'
                    '4,1,0.1,true,"café, snow 雪","1970-01-01T00:00:00.000000Z"\n').encode()
        self.assertEqual(r.csv_encode(columns, rows), expected)
        self.assertEqual(a.csv_bytes(a.plan(self.csv_document()), self.rows), expected)
        # The declared-schema consumer reads exactly the prepared table, signed zero included.
        self.assertTrue(r.equal(r.source(expected, columns), rows))
        self.assertEqual(struct.pack('<d', r.source(expected, columns)[0][2]).hex(), '0000000000000080')
        # An empty result still carries the header.
        self.assertEqual(r.csv_encode(columns, []), b'id,small,reading,enabled,label,observed\n')
        self.assertEqual(r.source(b'id,small,reading,enabled,label,observed\n', columns), [])

    def test_float_text_layout_and_exact_roundtrip(self):
        # Layouts below were observed from Arrow C++ 26.0.0 on a native probe (tools/qualify_apachearrow.py
        # repeats the comparison natively); here they are independent literals.
        cases = [(0.0, '0'), (-0.0, '-0'),
                 (5e-324, '5e-324'),
                 (-5e-324, '-5e-324'),
                 (2.2250738585072014e-308, '2.2250738585072014e-308'),
                 (1.7976931348623157e308, '1.7976931348623157e+308'),
                 (0.1, '0.1'),
                 (1.5, '1.5'),
                 (100.0, '100'),
                 (1e-6, '0.000001'),
                 (1.5e-6, '0.0000015'),
                 (1e-7, '1e-7'),
                 (1.5e-7, '1.5e-7'),
                 (1e9, '1000000000'),
                 (1e10, '1e+10'),
                 (1.5e10, '1.5e+10'),
                 (12345678.9, '12345678.9'),
                 (1234567.8900000001, '1234567.8900000001'),
                 (12345678900.0, '1.23456789e+10'),
                 (1e21, '1e+21'),
                 (1e22, '1e+22'),
                 (1.0000000000000001e23, '1.0000000000000001e+23'),
                 (123456789.0, '123456789'),
                 (0.30000000000000004, '0.30000000000000004'),
                 (9007199254740993.0, '9.007199254740992e+15'),
                 ]
        for value, text in cases:
            with self.subTest(text=text):
                self.assertEqual(r.float_text(value), text)
                self.assertEqual(struct.pack('<d', r.scalar(text, 'float64')), struct.pack('<d', value))
        import random
        generator = random.Random(65)
        for _ in range(3000):
            value = struct.unpack('<d', struct.pack('<Q', generator.getrandbits(64)))[0]
            if value == value and abs(value) != float('inf'):
                text = r.float_text(value)
                self.assertEqual(struct.pack('<d', r.scalar(text, 'float64')), struct.pack('<d', value), text)

    def test_text_quoting_unicode_and_formula_values_are_literal(self):
        columns = [{'name': 'text', 'type': 'utf8', 'nullable': True}, {'name': 'n', 'type': 'int32', 'nullable': False}]
        values = ['', ' ', ' lead', 'trail ', 'a,b', 'say "hi"', '"', 'line one\nline two', 'cr\rcr', 'crlf\r\nnext', 'tab\t', 'NA', 'null',
                  '=1+1', '+SUM(A1)', '@cmd', '-1', '\\', '\\Nx', 'x\\N', 'café 雪 😀', '\u2028', '\x01', None]
        rows = [[v, i] for i, v in enumerate(values)]
        data = r.csv_encode(columns, rows)
        self.assertTrue(data.endswith(b'\n') and not data.startswith(b'\xef\xbb\xbf'))
        self.assertIn(b'\n"=1+1",13\n', data)       # formula-looking text is carried literally, never prefixed
        self.assertIn(b'"say ""hi""",5\n', data)
        self.assertIn(b'\\N,23\n', data)               # null is bare; a quoted text cell can never be the token
        self.assertTrue(r.equal(r.source(data, columns), rows))
        for text in ('\\N', ):
            with self.assertRaises(r.NullCollision) as caught: r.csv_encode(columns, [['ok', 0], [text, 1]])
            self.assertEqual((caught.exception.row, caught.exception.column), (1, 'text'))

    def test_null_collision_and_byte_budget_fail_before_native_work(self):
        launched = []
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            marker = folder / 'launched'
            fake = folder / 'python'
            fake.write_text('#!/bin/sh\ntouch ' + str(marker) + '\n');fake.chmod(0o700)
            # Planning already refuses the reserved token as a replacement, with or without publication.
            for option in (False, True):
                d = {**self.csv_document(publishCSV=option)};d['select'][4]['fillNull'] = '\\N'
                self.fault(d, 'INVALID_ARROW_LITERAL')
            # Defence in depth: should any nonnull text equal \\N reach the encoder, publication refuses it.
            plan = a.plan(self.csv_document())
            original = r.transform
            def collide(p, rows):
                columns, output, indices = original(p, rows)
                output = [list(row) for row in output]
                output[1][4] = '\\N'
                return columns, output, indices
            r.transform = collide
            try:
                with self.assertRaises(SchemaxisError) as caught: a.source_rows(self.data, plan)
                fault = caught.exception.fault
                self.assertEqual((fault.code, fault.location), ('INVALID_ARROW_CSV_NULL_COLLISION', '$.publishCSV'))
                self.assertEqual((fault.observed['row'], fault.observed['column']), (1, 'label'))
                self.assertIn('publishCSV false', fault.message)
                # Not opted in: nothing is published as CSV and the same table is not refused.
                a.source_rows(self.data, a.plan(self.doc))
                with self.assertRaises(SchemaxisError) as caught:
                    a.run(self.csv_document(), folder / 'collision', executable=str(fake), timeout=5)
                self.assertEqual(caught.exception.fault.code, 'INVALID_ARROW_CSV_NULL_COLLISION')
            finally:
                r.transform = original
            self.assertFalse(marker.exists())
            result = json.loads((folder / 'collision/result.json').read_text())
            self.assertEqual((result['status'], result['fault']['code']), ('failed', 'INVALID_ARROW_CSV_NULL_COLLISION'))
            self.assertFalse((folder / 'collision/source.csv').exists())
            # Fill growth: 1100 null cells replaced by 4096 quote characters is 4.4 MiB of text,
            # but 9.0 MB of canonical CSV once every quote is doubled and the cell is quoted.
            doc = {'version': a.VERSION, 'operation': 'prepareTable', 'source': str(folder / 'in.csv'),
                   'columns': [{'name': 'label', 'type': 'utf8', 'nullable': True}],
                   'select': [{'column': 'label', 'name': 'label', 'fillNull': '"' * 4096}]}
            big = b'label\n' + b'\\N\n' * 1100
            a.source_rows(big, a.plan(doc))
            with self.assertRaises(SchemaxisError) as caught: a.source_rows(big, a.plan({**doc, 'publishCSV': True}))
            fault = caught.exception.fault
            self.assertEqual((fault.code, fault.location), ('INVALID_ARROW_CSV_BUDGET', '$.publishCSV'))
            self.assertEqual(fault.observed['limit'], 8 * 1024**2)
            self.assertIn('publishCSV false', fault.message)
            (folder / 'in.csv').write_bytes(big)
            with self.assertRaises(SchemaxisError) as caught:
                a.run({**doc, 'publishCSV': True}, folder / 'budget', executable=str(fake), timeout=5)
            self.assertEqual(caught.exception.fault.code, 'INVALID_ARROW_CSV_BUDGET')
            self.assertFalse(marker.exists())
        # The limit itself is exact: one byte over is refused.
        columns = [{'name': 'a', 'type': 'utf8', 'nullable': False}]
        self.assertEqual(len(r.csv_encode(columns, [['x' * 95]], limit=100)), 100)
        with self.assertRaises(r.CSVBudget): r.csv_encode(columns, [['x' * 96]], limit=100)

    def fake_evidence(self, folder, document):
        """Native-free evidence directory: fixture Parquet plus host-built native snapshots."""
        p = a.plan(document)
        columns, rows, _ = r.transform(p, self.rows)
        (folder / 'source.csv').write_bytes(self.data)
        (folder / 'table.parquet').write_bytes(FIXTURE.read_bytes())
        (folder / 'table.csv').write_bytes(r.csv_encode(columns, rows))
        for stage, wanted_columns, wanted_rows in (('convert', p['columns'], self.rows), ('readback', columns, rows), ('csvreadback', columns, rows)):
            snapshot = {'runtime': '26.0.0', 'cpp': '26.0.0', 'table': {'columns': wanted_columns, 'rows': r.wire_rows(wanted_columns, wanted_rows)}}
            (folder / (stage + '.stdout')).write_text(json.dumps(snapshot))
        return p

    def test_csv_verification_checks_every_cell_and_the_canonical_form(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder);p = self.fake_evidence(folder, self.csv_document())
            report = a.inspect(folder, p)
            data = (folder / 'table.csv').read_bytes()
            self.assertEqual(report['csv'], {'file': 'table.csv', 'format': r.CSV_FORMAT, 'bytes': len(data),
                                             'sha256': hashlib.sha256(data).hexdigest(), 'nullToken': '\\N'})
            self.assertEqual(report['rows'][0][:4], ['9007199254740993', -2147483648, -0.0, True])
            edits = {
                'changedInt64': (b'9007199254740993', b'9007199254740994'),
                'signedZeroErased': (b',-0,true', b',0,true'),
                'zeroLayout': (b',-0,true', b',-0.0,true'),
                'equalNumberOtherLayout': (b'1.5,false', b'1.50,false'),
                'nullBecomesEmptyText': (b',\\N,\\N,\\N,\\N\n', b',\\N,\\N,"",\\N\n'),
                'nullQuoted': (b',\\N,\\N,\\N,\\N\n', b',\\N,\\N,\\N,"\\N"\n'),
                'emptyTextBecomesNull': (b'-0,true,"","1969', b'-0,true,\\N,"1969'),
                'textUnquoted': (b',"NA",', b',NA,'),
                'timestampUnquoted': (b'"1970-01-01T00:00:00.000000Z"', b'1970-01-01T00:00:00.000000Z'),
                'timestampShortFraction': (b'"1970-01-01T00:00:00.000000Z"', b'"1970-01-01T00:00:00Z"'),
                'unicodeChanged': ('雪'.encode(), '雲'.encode()),
                'headerRenamed': (b'id,small,', b'ID,small,'),
                'headerQuoted': (b'id,small,', b'"id",small,'),
                'headerReordered': (b'id,small,reading', b'small,id,reading'),
                'crlf': (b'\n', b'\r\n'),
                'bom': (b'id,', b'\xef\xbb\xbfid,'),
                'finalNewlineMissing': (b'0.000000Z"\n', b'0.000000Z"'),
                'extraBlankRecord': (b'0.000000Z"\n', b'0.000000Z"\n\n'),
                'extraRow': (b'0.000000Z"\n', b'0.000000Z"\n5,1,2,true,"","1970-01-01T00:00:00.000000Z"\n'),
                'boolCase': (b',true,"",', b',True,"",'),
                'delimiter': (b'id,small,', b'id;small,'),
            }
            for name, (old, new) in edits.items():
                with self.subTest(name=name):
                    self.assertIn(old, data)
                    (folder / 'table.csv').write_bytes(data.replace(old, new, 1))
                    with self.assertRaises(SchemaxisError) as caught: a.inspect(folder, p)
                    self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')
            for name, shrink in (('truncated', data[:-7]), ('empty', b''), ('oversize', b'x' * (r.MAX_CSV + 1))):
                with self.subTest(name=name):
                    (folder / 'table.csv').write_bytes(shrink)
                    with self.assertRaises(SchemaxisError): a.inspect(folder, p)
            (folder / 'table.csv').write_bytes(data)
            # Native reopen snapshots of the CSV are checked against the independent table too.
            snapshot = json.loads((folder / 'csvreadback.stdout').read_text())
            snapshot['table']['rows'][0][0] = '9007199254740994'
            (folder / 'csvreadback.stdout').write_text(json.dumps(snapshot))
            with self.assertRaises(SchemaxisError) as caught: a.inspect(folder, p)
            self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')
            self.assertEqual(caught.exception.fault.location, 'csvreadback')
        # Not opted in: no CSV is read, required or reported.
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder);p = self.fake_evidence(folder, self.doc)
            (folder / 'table.csv').unlink();(folder / 'csvreadback.stdout').unlink()
            self.assertNotIn('csv', a.inspect(folder, p))

    def test_studio_template_edit_and_undo(self):
        from schemaxis.adaptors import registry
        from schemaxis.console_session import AdaptorConsoleSession
        from schemaxis.studio_library import instantiate_item, load_library, apply_inserts
        library = load_library('apachearrow');before = copy.deepcopy(library)
        for item in library['templates']:
            filled = instantiate_item(library, item, provider='apachearrow')
            self.assertEqual(registry.plan(filled)['operation'], 'prepareTable')
            with self.assertRaises(SchemaxisError):
                registry.plan(instantiate_item(library, item, provider='apachearrow', filled=False))
            changed = apply_inserts(filled, [{'at': '', 'merge': {'where': []}}])
            self.assertEqual(registry.plan(changed)['where'], [])
        self.assertEqual(library, before)
        with tempfile.TemporaryDirectory() as folder:
            session = AdaptorConsoleSession(folder, provider='apachearrow')
            try:
                original = session.document;draft = session.draft()
                changed = {**original, 'where': [{'column': 'label', 'test': 'isValid'}]}
                result = session.edit_source(json.dumps(changed), session.active_document, draft['revision'])
                self.assertFalse(result.get('diagnostics'))
                self.assertEqual(session.document['where'], changed['where'])
                session.undo();self.assertEqual(session.document, original)
            finally: session.close()


if __name__ == '__main__': unittest.main()
