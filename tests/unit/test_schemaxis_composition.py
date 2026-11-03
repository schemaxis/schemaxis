# Copyright (C) 2026 David L F Gaden
import unittest
from schemaxis.core.composition import evaluate
from schemaxis.core.documents import resolve_document
from schemaxis.core.faults import SchemaxisError


class NamedCompositionTests(unittest.TestCase):
    def test_merge_identity_order_and_conflict_policy(self):
        a = [{'name': 'b', 'options': {'x': 1, 'y': 2}}, {'name': 'a'}]
        b = [{'name': 'c'}, {'name': 'b', 'options': {'x': 3, 'z': 4}}]
        result = evaluate({'op': 'namedMerge', 'args': [a, b], 'conflict': 'right'}, '$')
        self.assertEqual([v['name'] for v in result], ['b', 'a', 'c'])
        self.assertEqual(result[0]['options'], {'x': 3, 'y': 2, 'z': 4})
        self.assertEqual(a[0]['options']['x'], 1)

    def test_duplicates_are_rejected_even_in_unused_named_entries(self):
        with self.assertRaises(SchemaxisError):
            evaluate({'op': 'namedGet', 'args': [[{'name': 'x'}, {'name': 'x'}], 'x']}, '$')

    def test_named_get_uses_name_not_numeric_position(self):
        result, _ = resolve_document({'definitions': [{'name': '2', 'value': 7}],
                                      'selected': {'$expr': {'op': 'namedGet', 'args': [
                                          {'$document': '/definitions'}, '2']}}})
        self.assertEqual(result['selected'], {'name': '2', 'value': 7})
        with self.assertRaises(SchemaxisError):
            evaluate({'op': 'namedGet', 'args': [[{'name': '2'}], 2]}, '$')

    def test_conflict_path_is_precise(self):
        with self.assertRaises(SchemaxisError) as caught:
            evaluate({'op': 'namedMerge', 'args': [[{'name': 'x', 'v': 1}], [{'name': 'x', 'v': 2}]],
                      'conflict': 'error'}, '$')
        self.assertEqual(caught.exception.fault.code, 'COMPOSITION_CONFLICT')
        self.assertEqual(caught.exception.fault.location, '$/x/v')
