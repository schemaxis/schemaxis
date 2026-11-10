"""Planning contracts for cylindrical wall groups, without native imports."""
import copy
import json
import math
from pathlib import Path
import unittest

from schemaxis.adaptors.gmsh import adaptor, groups
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]


def sleeve():
    return json.loads((ROOT/'examples/schemaxis/gmsh-named-sleeve.json').read_text())


def resolved(radius=2, axis='x', origin=(1, 2, 3)):
    d = sleeve(); d.pop('dimensions')
    d['nodes'][0]['options'].update(radius=4, innerRadius=radius, axis=axis, origin=list(origin))
    options = d['nodes'][1]['options']
    options['cylinderGroups'][0].update(radius=radius, axis=axis, centre=list(origin))
    options['cylinderGroups'][1].update(axis=axis, centre=list(origin), radius=4)
    return d


class CylinderPlanTests(unittest.TestCase):
    def fault(self, document):
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.plan(document)
        return caught.exception.fault

    def test_example_plans_with_four_tags_and_reference_driven_radius(self):
        plan = adaptor.plan(sleeve())
        options = plan['nodes'][1]['options']
        self.assertEqual(groups.tags(options), {'unassigned': 2, 'start': 3, 'end': 4, 'bore': 5, 'outer': 6})
        self.assertEqual(plan['nodes'][0]['options']['innerRadius'], 2)
        changed = sleeve(); changed['dimensions']['boreRadius'] = 2.5
        plan = adaptor.plan(changed)
        self.assertEqual(plan['nodes'][1]['options']['cylinderGroups'][0]['radius'], 2.5)
        self.assertEqual(plan['nodes'][0]['options']['innerRadius'], 2.5)

    def test_changed_axis_and_placement_keep_names_and_tags(self):
        for axis, origin in (('z', (-3, 5, 2)), ('y', (0, 7, 0))):
            options = adaptor.plan(resolved(axis=axis, origin=origin))['nodes'][1]['options']
            self.assertEqual([g['name'] for g in options['cylinderGroups']], ['bore', 'outer'])
            self.assertEqual(groups.tags(options)['bore'], 5)

    def test_stale_or_wrong_selectors_refuse_at_the_selector_before_native_start(self):
        stale = resolved(); stale['nodes'][0]['options']['innerRadius'] = 2.5
        for label, edit in (
                ('off radius', lambda d: d['nodes'][1]['options']['cylinderGroups'][0].update(radius=2.01)),
                ('wrong side', lambda d: d['nodes'][1]['options']['cylinderGroups'][0].update(side='outer')),
                ('wrong axis', lambda d: d['nodes'][1]['options']['cylinderGroups'][0].update(axis='y')),
                ('moved centre', lambda d: d['nodes'][1]['options']['cylinderGroups'][0].update(centre=[1, 2.5, 3])),
                ('stale literal', lambda d: d['nodes'][0]['options'].update(innerRadius=2.5)),
                ('duplicate', lambda d: d['nodes'][1]['options']['cylinderGroups'].append(
                    dict(d['nodes'][1]['options']['cylinderGroups'][0], name='twin')))):
            d = resolved(); edit(d)
            with self.subTest(label):
                fault = self.fault(d)
                self.assertEqual(fault.code, 'INVALID_SELECTION')
                self.assertTrue(fault.location.startswith('mesh.options.cylinderGroups['), fault.location)

    def test_one_cylinder_cannot_be_named_per_side_for_step_either(self):
        d = resolved(); d['nodes'][0] = {'id': 'solid', 'filter': 'readSTEP', 'options': {'file': '/data/part.step'}}
        groups_ = d['nodes'][1]['options']['cylinderGroups']
        groups_[1] = dict(groups_[0], name='twin', side='outer')
        fault = self.fault(d)
        self.assertEqual(fault.code, 'INVALID_SELECTION')
        self.assertEqual(fault.location, 'mesh.options.cylinderGroups[1]')
        self.assertIn('distinct cylinders', fault.message)

    def test_box_and_sphere_have_no_cylindrical_walls(self):
        for source in ({'id': 'solid', 'filter': 'box', 'options': {'size': [10, 10, 10]}},
                       {'id': 'solid', 'filter': 'sphere', 'options': {'radius': 5}}):
            d = resolved(); d['nodes'][0] = source
            self.assertEqual(self.fault(d).code, 'INVALID_SELECTION')

    def test_group_budget_names_and_remainder_references(self):
        d = resolved(); d['nodes'][1]['options']['faceGroups'] = [
            {'name': 'p'+str(i), 'axis': 'x', 'coordinate': i, 'areaTolerance': 0.02} for i in range(11)]
        self.assertEqual(self.fault(d).code, 'INVALID_ARGUMENT')
        d = resolved(); d['nodes'][1]['options']['cylinderGroups'][1]['name'] = 'bore'
        self.assertEqual(self.fault(d).code, 'INVALID_ARGUMENT')
        d = resolved(); d['nodes'][1]['options']['nearBoundaries'] = [{'boundary': 'unassigned', 'size': 0.5, 'distance': 1}]
        fault = self.fault(d)
        self.assertEqual(fault.code, 'INVALID_SELECTION')
        d['nodes'][1]['options']['faceGroups'].pop()
        adaptor.plan(d)
        d = resolved(); d['refinement'] = {'requirements': {'boundaryMaximumEdgeLength': [{'boundary': 'unassigned', 'maximum': 1}]}}
        self.assertEqual(self.fault(d).code, 'INVALID_SELECTION')

    def test_chord_deviation_requirement_accepts_only_cylinder_names(self):
        d = resolved(); d['refinement'] = {'requirements': {'boundaryMaximumChordDeviation': [{'boundary': 'bore', 'maximum': 0.05}]}}
        self.assertEqual(adaptor.plan(d)['refinement']['requirements']['boundaryMaximumChordDeviation'][0]['maximum'], 0.05)
        for boundary in ('start', 'unassigned', 'missing'):
            bad = copy.deepcopy(d)
            bad['refinement']['requirements']['boundaryMaximumChordDeviation'][0]['boundary'] = boundary
            with self.subTest(boundary), self.assertRaises(SchemaxisError):
                adaptor.plan(bad)

    def test_plans_without_cylinder_groups_are_unchanged(self):
        for name in ('gmsh-face-groups', 'gmsh-hollow-cylinder', 'gmsh-minimal'):
            plan = adaptor.plan(json.loads((ROOT/'examples/schemaxis'/(name+'.json')).read_text()))
            self.assertNotIn('cylinderGroups', plan['nodes'][1]['options'])
            self.assertFalse(any('cylinder groups' in text for text in plan['losses']))

    def test_remainder_stays_mandatory_without_cylinder_groups(self):
        from schemaxis.adaptors.gmsh import geometry
        source = {'filter': 'cylinder', 'options': {'origin': [0, 0, 0], 'axis': 'z', 'radius': 2, 'height': 4}}
        legacy = {'faceGroups': [{'axis': 'z', 'coordinate': 0, 'tolerance': 1e-6}, {'axis': 'z', 'coordinate': 4, 'tolerance': 1e-6}]}
        self.assertFalse(geometry.remainder_empty(source, legacy))
        full = dict(legacy, cylinderGroups=[{'axis': 'z', 'centre': [0, 0, 0], 'radius': 2, 'side': 'outer', 'tolerance': 1e-6}])
        self.assertTrue(geometry.remainder_empty(source, full))
        self.assertFalse(geometry.remainder_empty(source, dict(full, faceGroups=legacy['faceGroups'][:1])))


if __name__ == '__main__':
    unittest.main()
