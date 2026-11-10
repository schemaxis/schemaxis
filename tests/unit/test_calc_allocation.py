"""Typed CSV cells and XML-representable labels are rejected at Calc admission."""
import json
from pathlib import Path
import tempfile
import unittest
from schemaxis.adaptors.calc import adaptor
from schemaxis.core.faults import SchemaxisError


def rows_document(columns=('a', 'b'), rows=((1, 2), (3, 4))):
    return {'version': 'schemaxis.calc/1', 'nodes': [{'id': 't', 'filter': 'fromRows', 'options': {
        'columns': list(columns), 'rows': [list(row) for row in rows]}}]}


def csv_document(path):
    return {'version': 'schemaxis.calc/1', 'nodes': [{'id': 't', 'filter': 'readCSV', 'options': {'file': str(path)}}]}


class CalcTypedInputTests(unittest.TestCase):
    def fault(self, call, *args, **kwargs):
        with self.assertRaises(SchemaxisError) as caught:
            call(*args, **kwargs)
        return caught.exception.fault

    def run_csv(self, payload):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / 'in.csv'
            source.write_bytes(payload)
            fake = root / 'soffice'
            fake.write_text('#!/bin/sh\nexit 1\n')
            fake.chmod(0o755)
            return self.fault(adaptor.run, csv_document(source), root / 'out', executable=str(fake), timeout=10)

    def test_csv_cells_must_be_plain_ascii_decimal_numbers(self):
        cases = {'underscore': b'a,b\n1,2\n1_000,4\n', 'arabic-indic': 'a,b\n1,2\n١٢,4\n'.encode(),
                 'hex': b'a,b\n1,2\n0x10,4\n', 'empty': b'a,b\n1,2\n,4\n', 'currency': b'a,b\n1,2\n$5,4\n'}
        for name, payload in cases.items():
            with self.subTest(name):
                fault = self.run_csv(payload)
                self.assertEqual(fault.code, 'INVALID_TABLE')
                self.assertEqual(fault.location, 'rows[1][0]')
                self.assertEqual(fault.observed['record'], 3)
                self.assertEqual(fault.observed['column'], 'a')
                self.assertTrue(fault.recovery)

    def test_csv_fault_names_the_offending_column_label(self):
        fault = self.run_csv(b'income,expense\n1,2\n3,5%\n')
        self.assertEqual((fault.code, fault.location), ('INVALID_TABLE', 'rows[1][1]'))
        self.assertEqual(fault.observed['column'], 'expense')
        self.assertEqual(fault.observed['value'], '5%')

    def test_ragged_csv_record_is_located(self):
        fault = self.run_csv(b'a,b\n1,2\n3\n')
        self.assertEqual((fault.code, fault.location), ('INVALID_TABLE', 'rows[1]'))
        self.assertEqual((fault.observed['record'], fault.observed['expectedCells'], fault.observed['cells']), (3, 2, 1))

    def test_ordinary_csv_decimals_remain_accepted(self):
        for text, value in (('1', 1.0), ('-2.5', -2.5), ('+.5', 0.5), ('3.', 3.0), ('1e3', 1000.0), ('-1.25E-2', -0.0125), (' 7 ', 7.0)):
            with self.subTest(text):
                self.assertEqual(adaptor.parse_source_csv(f'a,b\n{text},1\n2,3\n'.encode())['rows'][0][0], value)

    def test_labels_must_be_representable_in_workbook_xml(self):
        for label in ('bad\ud800', 'bad￾', 'bad￿'):
            with self.subTest(repr(label)):
                fault = self.fault(adaptor.plan, rows_document(columns=(label, 'b')))
                self.assertEqual((fault.code, fault.location), ('INVALID_TABLE', 'columns[0]'))

    def test_csv_header_noncharacter_is_malformed_input(self):
        fault = self.run_csv('a,b\uffff\n1,2\n3,4\n'.encode())
        self.assertEqual((fault.code, fault.location), ('INVALID_TABLE', 'columns[1]'))

    def test_surrogate_label_is_not_reported_as_native_failure(self):
        # A CSV header cannot carry a surrogate, but fromRows JSON can; planning must stop first.
        fault = self.fault(adaptor.plan, rows_document(columns=('a', 'b\udfff')))
        self.assertEqual(fault.code, 'INVALID_TABLE')

    def test_overflow_and_range_faults_keep_cell_context(self):
        for token in ('1e101', '1e999'):
            with self.subTest(token=token):
                fault = self.run_csv(f'a,b\n{token},2\n3,4\n'.encode())
                self.assertEqual(fault.code, 'INVALID_TABLE')
                self.assertEqual(fault.location, 'rows[0][0]')
                self.assertEqual(fault.observed['record'], 2)
                self.assertEqual(fault.observed['column'], 'a')
                self.assertTrue(fault.recovery)

    def test_legacy_lenient_source_still_verifies_through_shared_parser(self):
        # Retained receipts re-read the captured source with the original parser.
        legacy = b'a,b\n1_000,2\n3,4\n'
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            (directory / 'source.csv').write_bytes(legacy)
            prepared = {'nodes': [{'filter': 'readCSV'}]}
            table = adaptor.table_for(prepared, directory)
        self.assertEqual(table['rows'][0], [1000.0, 2.0])


if __name__ == '__main__':
    unittest.main()
