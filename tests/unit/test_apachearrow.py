"""Independent Arrow host semantics and malformed closed-Parquet rejection."""
import copy
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
