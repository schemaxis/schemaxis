import json
from pathlib import Path
import subprocess
import sys
import unittest

from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.paraview.mvp.hierarchy import help_at, roots


class HierarchyTests(unittest.TestCase):
    def test_scoped_names_and_old_alias_resolve_to_same_property(self):
        expected = help_at('slice.crinkleSlice')
        for path in ('Slice.Crinkleslice', 'slice.crinkle', 'slice.PreserveInputCells'):
            self.assertEqual(help_at(path), expected)
        self.assertIn('entire cells', expected['documentation']['description'])
        self.assertEqual(expected['adaptor']['status'], 'supported')

    def test_nested_choices_retain_help_and_version(self):
        result = help_at('slice.sliceType.plane.origin')
        self.assertEqual(result['nativeName'], 'Origin')
        self.assertIn('5.13.3', result['version'])
        self.assertTrue(result['documentation']['description'])
        self.assertEqual(result['adaptor']['status'], 'inventoried')

    def test_native_groups_and_functions_are_not_execution_capabilities(self):
        result = help_at('groups.filters.Cut.PreserveInputCells')
        self.assertEqual(result['adaptor']['status'], 'inventoried')
        function = help_at('functions.SaveData')
        self.assertTrue(function['signature'])
        self.assertTrue(function['documentation']['description'])

    def test_unknown_or_expression_paths_fail_with_available_children(self):
        for path in ('slice.__dict__', 'slice.sliceType()', 'slice..origin'):
            with self.assertRaises(SchemaxisError) as caught:
                help_at(path)
            self.assertEqual(caught.exception.fault.code, 'UNKNOWN_HELP_PATH')
            self.assertIn('available', caught.exception.fault.observed)

    def test_every_listed_canonical_child_is_unique(self):
        def visit(nodes):
            names = [n['name'].casefold() for n in nodes]
            self.assertEqual(len(names), len(set(names)))
            for node in nodes:
                visit(node['children'])
        visit(roots())

    def test_recursive_inventory_is_complete_and_scoped(self):
        groups = help_at('groups', recursive=True)['children']
        self.assertEqual(sum(row['depth'] == 0 for row in groups), 73)
        self.assertEqual(sum(row['depth'] == 1 for row in groups), 978)
        self.assertEqual(sum(row['depth'] == 2 for row in groups), 7891)
        self.assertEqual(len(help_at('functions', recursive=True)['children']), 680)
        subset = help_at('slice.sliceType.plane', recursive=True)['children']
        self.assertTrue(all(row['path'].startswith('slice.sliceType.plane.') for row in subset))

    def test_cli_browsing_does_not_import_runtime(self):
        script = """import sys
from schemaxis.adaptors.paraview.mvp.hierarchy import help_at
help_at('slice.crinkleSlice')
assert not any(k == 'paraview' or k.startswith('paraview.') for k in sys.modules)
"""
        subprocess.run([sys.executable, '-c', script], check=True)
        result = subprocess.run([sys.executable, '-m', 'schemaxis.adaptors.paraview.mvp', 'list', 'slice', '--json'],
                                check=True, capture_output=True, text=True)
        self.assertIn('slice.crinkleSlice', [c['path'] for c in json.loads(result.stdout)['children']])


if __name__ == '__main__':
    unittest.main()
