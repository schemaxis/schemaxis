import copy
import unittest
from schemaxis.adaptors.blender.asset_fidelity import matching, check_version, VERSION
from schemaxis.errors import SchemaxisError


class AssetFidelity(unittest.TestCase):
    def test_obsolete_receipt_requires_trusted_input_requalification(self):
        with self.assertRaises(SchemaxisError) as caught:
            check_version({'version':'schemaxis.blender.asset-fidelity/1'},'asset')
        fault = caught.exception.fault
        self.assertEqual(fault.code,'RERUN_REQUIRED')
        self.assertIn('NEW output',fault.recovery)
        self.assertIn('trusted original',fault.recovery)
        self.assertIn('Do not resnapshot',fault.recovery)
        check_version({'version':VERSION},'asset')

    def test_missing_or_unknown_versions_never_downgrade(self):
        for value in (None, [], {}, {'version':None}, {'version':1},
                      {'version':'schemaxis.blender.asset-fidelity/3'}):
            with self.subTest(value=value), self.assertRaises(SchemaxisError) as caught:
                check_version(value,'asset')
            self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')

    def test_integral_identifiers_counts_and_types_are_exact(self):
        for changed in (1000001, 1000000.0, True):
            self.assertFalse(matching({'count': changed}, {'count': 1000000}))
        self.assertTrue(matching({'count': 1000000}, {'count': 1000000}))

    def test_custom_metadata_preserves_nested_values_and_types(self):
        reference = {'customProperties': {'part': [1000000, 1000000.125, {'valid': True}]}}
        self.assertTrue(matching(copy.deepcopy(reference), reference))
        for index, changed in ((0, 1000001), (0, 1000000.0), (1, 1000000.126), (2, {'valid': 1})):
            actual = copy.deepcopy(reference)
            actual['customProperties']['part'][index] = changed
            self.assertFalse(matching(actual, reference))

    def test_native_float_rounding_remains_tolerated(self):
        self.assertTrue(matching({'position': [.10000000149]}, {'position': [.1]}))
        self.assertFalse(matching({'position': [.2]}, {'position': [.1]}))
        self.assertFalse(matching({'position': [1]}, {'position': [1.0]}))

    def test_requested_shader_numeric_inputs_do_not_use_geometry_tolerance(self):
        expected={'attributeInputs':{'scene':{'code':1000000.125}}}
        self.assertTrue(matching(copy.deepcopy(expected),expected))
        self.assertFalse(matching({'attributeInputs':{'scene':{'code':1000000.126}}},expected))

    def test_membership_and_container_types_remain_exact(self):
        for actual in ({'a': 1, 'b': 2}, {}, {'a': [1]}, {'a': True}):
            self.assertFalse(matching(actual, {'a': 1}))


if __name__ == '__main__':
    unittest.main()
