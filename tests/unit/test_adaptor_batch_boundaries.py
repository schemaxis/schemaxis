"""Shared host boundaries discovered by the bounded adaptor investigations."""
import unittest
from schemaxis.adaptors import registry
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError

class SharedBoundaries(unittest.TestCase):
    def test_huge_bounded_number_is_a_located_fault(self):
        with self.assertRaises(SchemaxisError) as caught:
            validate_arguments({'distance': {'type':'number','maximum':100}}, {'distance':10**1000})
        self.assertEqual((caught.exception.fault.code,caught.exception.fault.location),('INVALID_ARGUMENT','$.arguments.distance'))
    def test_unbounded_integer_does_not_require_binary64_conversion(self):
        self.assertEqual(validate_arguments({'count':{'type':'integer'}},{'count':10**1000})['count'],10**1000)
    def test_unprintable_numeric_version_is_still_unsupported(self):
        with self.assertRaises(SchemaxisError) as caught:
            registry.resolve({'version':10**10000})
        self.assertEqual(caught.exception.fault.code,'UNSUPPORTED_VERSION')
        self.assertIsInstance(caught.exception.fault.observed['version'],str)

    def test_protocol_detector_reports_excessive_retained_nesting(self):
        import tempfile
        from pathlib import Path
        from schemaxis.adaptor_runtime import is_common
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'result.json'
            path.write_text('['*100000+']'*100000)
            with self.assertRaises(SchemaxisError) as caught:
                is_common(root)
            self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')
            self.assertEqual(caught.exception.fault.location,str(path))
