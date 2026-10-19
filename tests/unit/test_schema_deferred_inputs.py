"""Schema expansion must not invent native input paths for pending artifacts."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from schemaxis.adaptors import registry
from schemaxis.core.faults import SchemaxisError
from schemaxis.schema import expand_input
from schemaxis.workflow import dependencies

ROOT = Path(__file__).resolve().parents[2]


class DeferredInputExpansionTests(unittest.TestCase):
    def document(self):
        return json.loads((ROOT/'examples/schemaxis/aseprite-import-workflow.json').read_text())

    def test_consumer_stays_authored_and_concrete_producer_expands(self):
        document = self.document()
        native_plan = registry.plan
        planned = []
        def concrete_only(value, **kwargs):
            self.assertFalse(any(dependencies(value)), 'deferred consumer reached literal planner')
            planned.append(copy.deepcopy(value))
            return native_plan(value, **kwargs)
        with patch.object(registry, 'plan', side_effect=concrete_only), \
                patch('schemaxis.parallel.provisional', side_effect=AssertionError('fabricated input')):
            expanded = expand_input(document)
        self.assertEqual(expanded['operations'][1], document['operations'][1])
        self.assertEqual(len(planned), 1)
        self.assertIn('durationMS', expanded['operations'][0]['document']['nodes'][0]['options'])
        self.assertNotIn('durationMS', document['operations'][0]['document']['nodes'][0]['options'])

    def test_reference_order_and_shape_remain_checked(self):
        for replacement, fault in [({'$artifact': 'later', 'index': 1}, 'UNAVAILABLE_OPERATION'),
                                   ({'$artifact': 'icon', 'index': -1}, 'INVALID_SELECTION')]:
            document = self.document()
            document['operations'][1]['document']['nodes'][1]['options']['source'] = replacement
            with self.subTest(replacement=replacement), self.assertRaises(SchemaxisError) as caught:
                expand_input(document)
            self.assertEqual(caught.exception.fault.code, fault)

    def test_concrete_consumer_still_validates_file_type(self):
        document = self.document()['operations'][1]['document']
        document['nodes'][1]['options']['source'] = '/captured/image.txt'
        with self.assertRaises(SchemaxisError) as caught:
            expand_input(document)
        self.assertEqual(caught.exception.fault.code, 'INVALID_RESOURCE')
