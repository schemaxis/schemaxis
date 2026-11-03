# Copyright (C) 2026 David L F Gaden
"""Independent static assembly contract and hostile hierarchy cases."""
import copy
import json
import math
from pathlib import Path
import unittest

from schemaxis.adaptors.godot import plan, schema
from schemaxis.adaptors.godot.adaptor import expected_bounds, group_bounds, world_transform, transformed
from schemaxis.adaptors.godot.integration import reusableInputs
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]


def assembly():
    return json.loads((ROOT/'examples/schemaxis/godot-hierarchy.json').read_text())


class HierarchyTests(unittest.TestCase):
    def test_forward_parents_stable_flat_and_immutable(self):
        source = assembly(); original = copy.deepcopy(source)
        prepared = plan(source)
        self.assertEqual(source, original)
        self.assertEqual([n['id'] for n in prepared['nodes']],
                         ['paint', 'assembly', 'arm', 'block', 'empty', 'view', 'sun', 'marker'])
        flat = json.loads((ROOT/'examples/schemaxis/godot-primitives.json').read_text())
        self.assertEqual([n['id'] for n in plan(flat)['nodes']], [n['id'] for n in flat['nodes']])
        self.assertEqual(plan(source), prepared)

    def test_independent_nonuniform_rotated_composition_and_bounds(self):
        nodes = {n['id']: n for n in plan(assembly())['nodes']}
        a = math.sqrt(0.5)
        position, basis = world_transform(nodes['block'], nodes)
        for actual, expected in zip(position, [10-3*a, 2-6*a, 0]):
            self.assertAlmostEqual(actual, expected)
        for actual, expected in zip(sum(basis, []), [-a, 2*a, 0, -3*a, -6*a, 0, 0, 0, 1]):
            self.assertAlmostEqual(actual, expected)
        # Non-orthogonal columns demonstrate real shear; a rotation/scale sum is wrong.
        self.assertAlmostEqual(sum(x*y for x,y in zip(basis[0],basis[1])), -4.5)
        expected = [10-7*a, 2-14*a, -2, 10+a, 2+2*a, 2]
        for actual, value in zip(expected_bounds(nodes['block'], {}, nodes), expected):
            self.assertAlmostEqual(actual, value)
        for actual, value in zip(group_bounds('assembly', nodes, {}), [10-7*a, -10, -2, 11, 2+2*a, 2]):
            self.assertAlmostEqual(actual, value)
        self.assertEqual(group_bounds('arm', nodes, {}), expected_bounds(nodes['block'], {}, nodes))
        self.assertIsNone(group_bounds('empty', nodes, {}))

    def test_yxz_degrees_apply_scale_z_x_y_then_translation(self):
        actual = transformed([1,2,3], {'position':[1,2,3], 'rotation':[90,90,90], 'scale':[2,3,4]})
        for value, expected in zip(actual,[3,-10,9]):
            self.assertAlmostEqual(value,expected)

    def test_fault_codes_locations_and_cycle(self):
        cases = [('missing', 'INVALID_DEPENDENCY'), (None, 'INVALID_DEPENDENCY'),
                 ([], 'INVALID_DEPENDENCY'), ('paint', 'TYPE_MISMATCH'), ('block', 'TYPE_MISMATCH')]
        for parent, code in cases:
            source = assembly(); source['nodes'][2]['inputs']['parent'] = parent
            with self.subTest(parent=parent), self.assertRaises(SchemaxisError) as caught: plan(source)
            self.assertEqual(caught.exception.fault.code, code)
            self.assertEqual(caught.exception.fault.location, '$.nodes[2].inputs.parent')
        for parent in ('arm','assembly'):
            source = assembly(); source['nodes'][3]['inputs'] = {'parent':parent}
            with self.assertRaises(SchemaxisError) as caught: plan(source)
            self.assertEqual(caught.exception.fault.code,'DEPENDENCY_CYCLE')

    def test_scale_depth_and_composed_limits(self):
        for scale in ([0,1,1], [-1,1,1], [True,1,1], [1001,1,1]):
            source=assembly(); source['nodes'][2]['options']['scale']=scale
            with self.subTest(scale=scale), self.assertRaises(SchemaxisError): plan(source)
        source=assembly()
        source['nodes'][2]['options']['scale']=[1000]*3
        source['nodes'][3]['options']['scale']=[1000]*3
        with self.assertRaises(SchemaxisError) as caught: plan(source)
        self.assertEqual(caught.exception.fault.code,'RESOURCE_LIMIT')
        source=assembly()
        source['nodes'][3]['inputs']={'parent':'g0'}
        source['nodes'].extend({'id':'g'+str(i),'filter':'transformGroup',
          **({'inputs':{'parent':'g'+str(i+1)}} if i<16 else {})} for i in range(17))
        with self.assertRaises(SchemaxisError) as caught: plan(source)
        self.assertEqual(caught.exception.fault.code,'RESOURCE_LIMIT')

    def test_root_only_camera_light_sprite_and_material(self):
        for index in (0,5,6):
            source=assembly(); source['nodes'][index]['inputs']={'parent':'assembly'}
            with self.assertRaises(SchemaxisError): plan(source)

    def test_schema_and_shared_authored_binding_reuse(self):
        alternatives = schema()['properties']['nodes']['items']['oneOf']
        group = next(n for n in alternatives if n['properties']['filter']['const']=='transformGroup')
        self.assertNotIn('inputs',group['required'])
        self.assertNotIn('required',group['properties']['inputs'])
        source=assembly(); expected=plan(source)
        source['definitions']={'parent':'arm','placement':[10,0,0]}
        source['nodes'][1]['inputs']['parent']={'$document':'/definitions/parent'}
        source['nodes'][3]['options']['position']={'$document':'/definitions/placement'}
        self.assertEqual(plan(source), expected)
        self.assertEqual(reusableInputs(source), {})
