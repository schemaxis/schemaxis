"""Presentation intent decisions and independent literal rigid-motion checks."""
import copy
import math
import unittest

from schemaxis.adaptors.blender.production_intents import validate_intents, verify_intents
from schemaxis.core.faults import SchemaxisError


class PresentationIntentTest(unittest.TestCase):
    def raw(self):
        return {'id': 'housing', 'kind': 'turntable', 'objects': ['shell', 'lid'], 'angleDegrees': 180}

    def normal(self):
        return validate_intents([self.raw()], {'shell', 'lid'}, {'frameStart': 1, 'frameEnd': 3})

    def evidence(self):
        shell = [[1, 0, 0, 5], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        lid = [[1, 0, 0, 9], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        return [{'id': 'housing', 'control': 'SX_INTENT_housing', 'selected': ['shell', 'lid'],
            'parent': None, 'rotationMode': 'XYZ', 'scale': [1, 1, 1], 'pivot': [7, 0, 0],
            'beforeBounds': [4, 10, -1, 1, -1, 1], 'roots': ['shell', 'lid'],
            'rootParents': {'shell': 'SX_INTENT_housing', 'lid': 'SX_INTENT_housing'},
            'beforeWorld': {'shell': shell, 'lid': lid},
            'curves': [{'index': i, 'path': 'rotation_euler', 'muted': False, 'modifiers': 0,
                'extrapolation': 'CONSTANT', 'interpolation': ['LINEAR', 'LINEAR'],
                'keys': [[1, 0], [3, math.pi if i == 2 else 0]]} for i in range(3)],
            'samples': [
                {'frame': 1, 'world': {'shell': shell, 'lid': lid}},
                {'frame': 2, 'world': {
                    'shell': [[0, -1, 0, 7], [1, 0, 0, -2], [0, 0, 1, 0], [0, 0, 0, 1]],
                    'lid': [[0, -1, 0, 7], [1, 0, 0, 2], [0, 0, 1, 0], [0, 0, 0, 1]]}},
                {'frame': 3, 'world': {
                    'shell': [[-1, 0, 0, 9], [0, -1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
                    'lid': [[-1, 0, 0, 5], [0, -1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]}}]}]

    def test_defaults_lower_to_a_named_task_without_mutating_input(self):
        raw = self.raw()
        before = copy.deepcopy(raw)
        normal = validate_intents([raw], {'shell', 'lid'}, {'frameStart': 1, 'frameEnd': 3})[0]
        self.assertEqual(normal['pivot'], 'boundsCentre')
        self.assertEqual(normal['axis'], 'Z')
        self.assertEqual((normal['startFrame'], normal['endFrame']), (1, 3))
        self.assertEqual(raw, before)

    def test_task_references_and_numeric_boundaries_are_host_validated(self):
        for change in [{'objects': ['missing']}, {'objects': ['shell', 'shell']},
                       {'angleDegrees': True}, {'angleDegrees': 0}, {'angleDegrees': float('inf')},
                       {'startFrame': 3}, {'endFrame': 4}, {'axis': [0, 0, 1]},
                       {'pivot': [0, False, 0]}, {'id': '../object'}, {'python': 'pass'},
                       {'kind': 'nativeOperator'}]:
            with self.subTest(change=change), self.assertRaises(SchemaxisError):
                validate_intents([{**self.raw(), **change}], {'shell', 'lid'}, {'frameStart': 1, 'frameEnd': 3})

    def test_competing_tasks_and_generated_control_name_collision_are_rejected(self):
        with self.assertRaises(SchemaxisError):
            validate_intents([self.raw(), {**self.raw(), 'id': 'other'}], {'shell', 'lid'}, {'frameStart': 1, 'frameEnd': 3})
        with self.assertRaises(SchemaxisError):
            validate_intents([self.raw()], {'shell', 'lid', 'SX_INTENT_housing'}, {'frameStart': 1, 'frameEnd': 3})

    def test_literal_quarter_and_half_turn_geometry_checks(self):
        self.assertTrue(verify_intents(self.normal(), self.evidence()))

    def test_wrong_pivot_parent_channels_and_evaluation_cannot_be_claimed(self):
        valid = self.evidence()
        for key, value in [('pivot', [6, 0, 0]), ('parent', 'unexpected'), ('scale', [1, 2, 1]),
                           ('roots', ['other']), ('rootParents', {'shell': None, 'lid': None})]:
            with self.subTest(key=key), self.assertRaises(SchemaxisError):
                verify_intents(self.normal(), [{**valid[0], key: value}])
        forged = copy.deepcopy(valid)
        forged[0]['samples'][1]['world']['shell'][1][3] = 2
        with self.assertRaises(SchemaxisError):
            verify_intents(self.normal(), forged)

    def test_hidden_native_curve_changes_and_malformed_records_are_rejected(self):
        for field, value in [('muted', True), ('modifiers', 1), ('extrapolation', 'LINEAR'),
                             ('index', False), ('interpolation', ['BEZIER', 'BEZIER'])]:
            record = self.evidence()
            record[0]['curves'][0][field] = value
            with self.subTest(field=field), self.assertRaises(SchemaxisError):
                verify_intents(self.normal(), record)
        for malformed in [None, [None], [{'id': 'housing'}]]:
            with self.subTest(malformed=malformed), self.assertRaises(SchemaxisError):
                verify_intents(self.normal(), malformed)


if __name__ == '__main__':
    unittest.main()
