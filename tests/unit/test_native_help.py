# Copyright (C) 2026 David L F Gaden
import json
from pathlib import Path
import subprocess
import sys
import unittest

from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.paraview.mvp.native_help import option_help
from schemaxis.adaptors.paraview.mvp.slice_options import SLICE_COVERAGE, SLICE_OPTIONS
from schemaxis.adaptors.paraview.mvp.slice_export import SliceExport


class NativeHelpTests(unittest.TestCase):
    def test_every_native_slice_property_has_a_disposition(self):
        snapshot = json.loads((Path(__file__).resolve().parents[2] /
            'src/schemaxis/adaptors/paraview/mvp/native/slice-5.13.3.json').read_text())
        self.assertEqual(set(SLICE_COVERAGE), set(snapshot['proxies'][snapshot['root']]['properties']))
        self.assertGreater(len(snapshot['proxies']), 1)
        self.assertEqual(snapshot['gaps'], [])

    def test_upstream_help_is_preserved_and_versioned_for_all_name_forms(self):
        expected = option_help('crinkle')
        self.assertIn('entire cells', expected['documentation']['description'])
        self.assertIn('5.13.3', expected['version'])
        for name in ('Crinkleslice', 'PreserveInputCells', 'Crinkle slice'):
            self.assertEqual(option_help(name), expected)
        self.assertEqual(option_help('UseDual')['adaptor']['status'], 'unsupported')

    def test_unknown_property_reports_available_native_names(self):
        with self.assertRaises(SchemaxisError) as caught:
            option_help('doesNotExist')
        self.assertEqual(caught.exception.fault.code, 'UNKNOWN_NATIVE_PROPERTY')
        self.assertIn('Crinkleslice', caught.exception.fault.observed['available'])

    def test_help_does_not_import_paraview(self):
        source = """import sys
from schemaxis.adaptors.paraview.mvp.native_help import option_help
option_help('crinkle')
assert not any(name == 'paraview' or name.startswith('paraview.') for name in sys.modules)
"""
        subprocess.run([sys.executable, '-c', source], check=True)

    def test_reviewed_mappings_supply_the_capability_arguments(self):
        declaration = SliceExport.describe()
        for name, option in SLICE_OPTIONS.items():
            self.assertEqual(declaration['arguments'][name], option['argument'])
            self.assertEqual(option_help(name)['adaptor']['argument'], name)


if __name__ == '__main__':
    unittest.main()
