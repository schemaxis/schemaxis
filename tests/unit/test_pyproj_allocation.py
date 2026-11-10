"""Authored numeric options beyond binary64 are refused with located faults, never an unstructured crash."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from schemaxis.adaptors.pyproj import adaptor, contract
from schemaxis.core.faults import SchemaxisError

HUGE = 10 ** 400


def document(**extra):
    doc = {'version': adaptor.VERSION, 'operation': adaptor.OPERATION, 'source': '/abs/route.csv', 'ellipsoid': 'WGS84',
           'coordinateOrder': 'lonLat', 'spacing_m': 1000}
    doc.update(extra)
    return doc


class NumericRangeTests(unittest.TestCase):
    def refusal(self, doc, call=adaptor.plan):
        with self.assertRaises(SchemaxisError) as caught:
            call(doc)
        return caught.exception.fault

    def locations(self):
        return {
            '$.spacing_m': lambda value: document(spacing_m=value),
            '$.requirements.totalLength_m.minimum': lambda value: document(requirements={'totalLength_m': {'minimum': value}}),
            '$.requirements.totalLength_m.maximum': lambda value: document(requirements={'totalLength_m': {'maximum': value}}),
            '$.requirements.endpointGap_m.maximum': lambda value: document(requirements={'endpointGap_m': {'maximum': value}}),
        }

    def test_integers_beyond_binary64_are_located_faults(self):
        for location, build in self.locations().items():
            for value in (HUGE, -HUGE):
                with self.subTest(location=location, sign=value > 0):
                    doc = build(value)
                    before = copy.deepcopy(doc)
                    fault = self.refusal(doc)
                    self.assertEqual((fault.code, fault.location), ('INVALID_ARGUMENT', location))
                    self.assertTrue(fault.recovery)
                    self.assertEqual(doc, before)

    def test_every_planning_entry_point_refuses_the_same_way(self):
        doc = document(spacing_m=HUGE)
        for call in (adaptor.query, adaptor.reusableInputs, contract.validate):
            with self.subTest(call=call.__name__):
                fault = self.refusal(doc, call)
                self.assertEqual((fault.code, fault.location), ('INVALID_ARGUMENT', '$.spacing_m'))

    def test_run_refuses_before_creating_output(self):
        with tempfile.TemporaryDirectory() as root:
            out = Path(root) / 'out'
            with self.assertRaises(SchemaxisError) as caught:
                adaptor.run(document(spacing_m=HUGE), out, executable='/nonexistent/python', timeout=10)
            self.assertEqual(caught.exception.fault.code, 'INVALID_ARGUMENT')
            self.assertFalse(out.exists())

    def test_ordinary_values_are_unchanged(self):
        self.assertEqual(self.refusal(document(spacing_m=1e300)).location, '$.spacing_m')
        self.assertEqual(self.refusal(document(spacing_m=True)).code, 'INVALID_ARGUMENT')
        self.assertEqual(self.refusal(document(spacing_m=float('nan'))).code, 'INVALID_ARGUMENT')
        plan = adaptor.plan(document(spacing_m=1000, requirements={'totalLength_m': {'minimum': 5, 'maximum': 10 ** 7}}))
        self.assertEqual(plan['spacing_m'], 1000.0)
        self.assertEqual(plan['requirements']['totalLength_m'], {'minimum': 5.0, 'maximum': 1e7})
        # the largest integer that still converts to binary64 reaches the ordinary range check
        largest = int(1.7976931348623157e308)
        self.assertEqual(self.refusal(document(spacing_m=largest)).location, '$.spacing_m')
        json.dumps(plan)


if __name__ == '__main__':
    unittest.main()
