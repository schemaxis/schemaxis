# Copyright (C) 2026 David L F Gaden
from copy import deepcopy
import unittest

from schemaxis.core.documents import resolve_document
from schemaxis.core.faults import SchemaxisError


def expr(op, *args, **options):
    return {'$expr': {'op': op, 'args': list(args), **options}}


class CompositionTests(unittest.TestCase):
    def value(self, value):
        return resolve_document({'value': value})[0]['value']

    def fault(self, value, code):
        with self.assertRaises(SchemaxisError) as caught:
            self.value(value)
        self.assertEqual(caught.exception.fault.code, code)
        return caught.exception.fault

    def test_overlay_replaces_whole_nested_values_and_does_not_mutate(self):
        value = expr('overlay', {'a': {'x': 1, 'y': 2}, 'keep': True}, {'a': {'x': 3}})
        original = deepcopy(value)
        self.assertEqual(self.value(value), {'a': {'x': 3}, 'keep': True})
        self.assertEqual(value, original)

    def test_recursive_merge_conflict_policies_and_atomic_arrays(self):
        for policy, expected in [('left', 1), ('right', 2)]:
            result = self.value(expr('merge', {'n': {'x': 1}, 'a': [1, 2]}, {'n': {'x': 2, 'y': 3}, 'a': [4]}, conflict=policy))
            self.assertEqual(result['n'], {'x': expected, 'y': 3})
            self.assertEqual(result['a'], [1, 2] if policy == 'left' else [4])
        self.assertEqual(self.value(expr('merge', {'x': 1}, {'x': 2})), {'x': 1})

    def test_conflict_location_and_json_types(self):
        fault = self.fault(expr('merge', {'n': {'a/b': True}}, {'n': {'a/b': 1}}, conflict='error'), 'COMPOSITION_CONFLICT')
        self.assertEqual(fault.location, '$/value/n/a~1b')
        self.fault(expr('merge', {'a': [True]}, {'a': [1]}, conflict='error'), 'COMPOSITION_CONFLICT')
        self.assertEqual(self.value(expr('merge', {'a': None}, {'a': None}, conflict='error')), {'a': None})
        self.assertEqual(self.value(expr('merge', {'a': 1}, {'a': 1.0}, conflict='error')), {'a': 1})

    def test_null_is_a_value_and_omit_uses_direct_keys(self):
        self.assertEqual(self.value(expr('overlay', {'a': 1}, {'a': None})), {'a': None})
        self.assertEqual(self.value(expr('omit', {'a': 1, 'b': {'a': 2}}, {'a': False, 'missing': 0})), {'b': {'a': 2}})

    def test_definition_scope_is_resolved_before_composition(self):
        document = {'templates': {'number': 4, 'base': {'x': {'$document': '../number'}}},
                    'value': expr('overlay', {'$document': '/templates/base'}, {'y': 2})}
        result, evidence = resolve_document(document)
        self.assertEqual(result['value'], {'x': 4, 'y': 2})
        self.assertTrue(any(item.get('operation') == 'overlay' for item in evidence))

    def test_lookup_expression_key_and_distinct_array_index(self):
        self.assertEqual(self.value(expr('get', {'a': 5}, expr('get', ['a'], 0))), 5)
        self.assertEqual(self.value(expr('get', {'0': 3}, '0')), 3)
        self.fault(expr('get', [3], '0'), 'INVALID_EXPRESSION')
        self.fault(expr('get', [3], True), 'INVALID_EXPRESSION')

    def test_arithmetic_and_invalid_values(self):
        self.assertEqual(self.value(expr('multiply', expr('add', 1, 2), expr('divide', 6, 2))), 9)
        for value in [expr('divide', 1, 0), expr('multiply', 1e308, 1e308), expr('add', True, 1), expr('__import__', 'os', 'system'), expr('get', {}, 'missing'), expr('overlay', {}, {}, conflict='right')]:
            self.fault(value, 'INVALID_EXPRESSION')

    def test_cycle_through_composition(self):
        document = {'value': expr('overlay', {'$document': '/value'}, {})}
        with self.assertRaises(SchemaxisError) as caught:
            resolve_document(document)
        self.assertEqual(caught.exception.fault.code, 'DOCUMENT_CYCLE')

    def test_expansion_limit_applies_to_expression_operands(self):
        document = {'a': [1]*50, 'value': expr('get', {'$document': '/a'}, 0)}
        with self.assertRaises(SchemaxisError) as caught:
            resolve_document(document, max_values=80)
        self.assertEqual(caught.exception.fault.code, 'DOCUMENT_LIMIT')


if __name__ == '__main__':
    unittest.main()
