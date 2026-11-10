"""Label input boundary and unsupported-runtime ordering for the Inkscape adaptor."""
import copy
import json
from pathlib import Path
import stat
import tempfile
import unittest

from schemaxis.adaptors.inkscape import adaptor as app
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    return json.loads((ROOT / 'examples/schemaxis' / name).read_text())


class LabelBoundaryTests(unittest.TestCase):
    def error(self, function, code):
        with self.assertRaises(SchemaxisError) as caught: function()
        self.assertEqual(caught.exception.fault.code, code)
        return caught.exception.fault

    def test_blank_and_line_separator_labels_fail_before_native(self):
        for label in ('   ', ' ', ' ', 'a b', 'a b', 'a\x85b'):
            for name in ('inkscape-diagram.json', 'inkscape-flow.json'):
                document = load(name); document['boxes'][0]['label'] = label
                fault = self.error(lambda: app.plan(document), 'INVALID_LAYOUT')
                self.assertEqual(fault.location, '$.boxes[0].label', repr(label))
                self.assertIn('label', fault.message)

    def test_ordinary_labels_with_inner_and_edge_spaces_remain_valid(self):
        for label in ('Input stage', ' padded ', 'Δp [Pa]', 'a b'):
            document = load('inkscape-diagram.json'); document['boxes'][0]['label'] = label
            self.assertEqual(app.plan(document)['boxes'][0]['label'], label)

    def test_flow_label_fault_names_authored_not_derived_position(self):
        document = load('inkscape-flow.json')
        document['boxes'].reverse()  # derived order is rank/lane, not authored order
        identities = [box['id'] for box in document['boxes']]
        for index, identity in enumerate(identities):
            candidate = copy.deepcopy(document)
            candidate['boxes'][index]['label'] = 'two\nlines'
            fault = self.error(lambda: app.plan(candidate), 'INVALID_LAYOUT')
            self.assertEqual(fault.location, f'$.boxes[{index}].label', identity)

    def test_explicit_example_labels_still_plan(self):
        for name in ('inkscape-diagram.json', 'inkscape-diagram-variant.json',
                     'inkscape-flow.json', 'inkscape-flow-variant.json'):
            app.plan(load(name))


class UnsupportedRuntimeOrderingTests(unittest.TestCase):
    def launcher(self, directory, version):
        path = Path(directory) / 'inkscape'
        path.write_text('#!/bin/sh\ncase "$*" in\n  *--version*) echo "' + version + '";;\n'
                        '  *) echo "unsupported-output-that-is-not-a-query" ; echo "$*" >> "$0.calls";;\nesac\n')
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def test_unsupported_runtime_is_reported_before_query_or_export(self):
        for version in ('Inkscape 1.2.2 (fake)', 'Inkscape 0.92.5', 'Inkscape 1.5.0 (fake)', 'not inkscape at all'):
            with tempfile.TemporaryDirectory() as temp:
                launcher = self.launcher(temp, version)
                with self.assertRaises(SchemaxisError) as caught:
                    app.run(load('inkscape-diagram.json'), Path(temp) / 'out', executable=str(launcher), timeout=30)
                fault = caught.exception.fault
                self.assertEqual(fault.code, 'UNSUPPORTED_RUNTIME', version)
                self.assertIn(version.split(' (')[0], str(fault.observed))
                self.assertFalse((Path(temp) / 'inkscape.calls').exists(), 'query/export launched')
                out = Path(temp) / 'out'
                self.assertTrue((out / 'diagram.svg').is_file())  # editable evidence retained
                self.assertFalse((out / 'query-submission.json').exists())
                result = json.loads((out / 'result.json').read_text())
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['fault']['code'], 'UNSUPPORTED_RUNTIME')

    def test_supported_version_but_malformed_query_stays_a_verification_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            launcher = self.launcher(temp, 'Inkscape 1.4.4 (fake)')
            with self.assertRaises(SchemaxisError) as caught:
                app.run(load('inkscape-diagram.json'), Path(temp) / 'out', executable=str(launcher), timeout=30)
            self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')


if __name__ == '__main__':
    unittest.main()
