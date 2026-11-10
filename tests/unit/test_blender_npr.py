"""Logical Freestyle admission; independent of native Blender imports."""
import copy
import unittest

from schemaxis.adaptors.blender import npr
from schemaxis.core.faults import SchemaxisError


def intent():
    return {'styles': [{'id': 'visible', 'width': 2, 'colour': [.1, .2, .3, 1]},
                       {'id': 'hidden', 'width': 1, 'dash': [{'length': 7, 'gap': 3}]}],
            'layers': [{'layer': 'drawing', 'lineSets': [
                {'id': 'outline', 'style': 'visible', 'edges': ['silhouette', 'border'],
                 'visibility': {'kind': 'visible'}, 'scope': {'kind': 'objects', 'objects': ['plate', 'shaft']}},
                {'id': 'hidden_edges', 'style': 'hidden', 'edges': ['crease'],
                 'visibility': {'kind': 'range', 'minimum': 1, 'maximum': 2},
                 'scope': {'kind': 'collection', 'collection': 'assembly', 'invert': False}}]}]}


def validate(value):
    return npr.validate(value, layers=['drawing', 'preview'], objects=['plate', 'shaft', 'camera'],
                        collections=['assembly'], materials=['steel', 'paint'],
                        kinds={'plate': 'mesh', 'shaft': 'mesh', 'camera': 'camera'})


class FreestyleIntent(unittest.TestCase):
    def refused(self, value, code=None):
        with self.assertRaises(SchemaxisError) as raised:
            validate(value)
        if code:
            self.assertEqual(raised.exception.fault.code, code)

    def test_detached_complete_default_intent_and_material_owner_scope(self):
        value = intent(); before = copy.deepcopy(value)
        result = validate(value)
        self.assertEqual(value, before)
        self.assertEqual(result['version'], npr.VERSION)
        self.assertEqual(result['styles'][0]['caps'], 'butt')
        self.assertEqual(result['styles'][0]['dash'], [])
        self.assertEqual(result['layers'][0]['lineSets'][0]['scope']['invert'], False)
        self.assertEqual(result['materials'], [])
        value['styles'][0]['colourSource'] = 'materialLine'
        value['materials'] = [{'material': 'steel', 'colour': [.8, .1, .2, 1], 'priority': 7}]
        self.assertEqual(validate(value)['materials'][0]['priority'], 7)

    def test_shared_style_is_logical_not_native_name(self):
        value = intent()
        value['layers'].append({'layer': 'preview', 'lineSets': [copy.deepcopy(value['layers'][0]['lineSets'][0])]})
        result = validate(value)
        self.assertEqual(result['layers'][1]['lineSets'][0]['style'], 'visible')
        value['styles'][0]['id'] = '__native_style'
        self.refused(value)

    def test_unknown_layer_style_object_collection_and_material_refuse(self):
        mutations = [lambda v: v['layers'][0].update(layer='missingLayer'),
                     lambda v: v['layers'][0]['lineSets'][0].update(style='missing'),
                     lambda v: v['layers'][0]['lineSets'][0]['scope'].update(objects=['missing']),
                     lambda v: v['layers'][0]['lineSets'][1]['scope'].update(collection='missingCollection'),
                     lambda v: v.update(materials=[{'material': 'missingMaterial'}])]
        for mutate in mutations:
            value = intent(); mutate(value)
            self.refused(value, 'UNKNOWN_REFERENCE')

    def test_duplicate_id_and_reference_closure(self):
        mutations = [lambda v: v['styles'].append(copy.deepcopy(v['styles'][0])),
                     lambda v: v['layers'].append(copy.deepcopy(v['layers'][0])),
                     lambda v: v['layers'][0]['lineSets'].append(copy.deepcopy(v['layers'][0]['lineSets'][0])),
                     lambda v: v['layers'][0]['lineSets'][0].update(edges=['border', 'border']),
                     lambda v: v['layers'][0]['lineSets'][0]['scope'].update(objects=['plate', 'plate'])]
        for mutate in mutations:
            value = intent(); mutate(value)
            self.refused(value, 'DUPLICATE_ID')

    def test_visibility_qi_range_and_non_geometry_scope(self):
        value = intent(); value['layers'][0]['lineSets'][0]['visibility'] = {'kind': 'hidden'}
        self.assertEqual(validate(value)['layers'][0]['lineSets'][0]['visibility'], {'kind': 'hidden'})
        value['layers'][0]['lineSets'][0]['scope']['objects'] = ['camera']
        self.refused(value, 'TYPE_MISMATCH')
        for minimum, maximum in ((3, 2), (True, 2), (-1, 2), (1, 65)):
            value = intent()
            value['layers'][0]['lineSets'][0]['visibility'] = {'kind': 'range', 'minimum': minimum, 'maximum': maximum}
            self.refused(value)

    def test_unused_styles_and_unbound_material_colour_refuse(self):
        value = intent(); value['styles'].append({'id': 'unused'})
        self.refused(value, 'INVALID_NPR')
        value = intent(); value['styles'][0]['colourSource'] = 'materialLine'
        self.refused(value, 'INVALID_NPR')

    def test_numeric_colour_width_and_dash_are_finite_and_bounded(self):
        for patch in ({'width': 0}, {'width': 65}, {'width': True}, {'width': float('inf')},
                      {'colour': [1, 0, 0, 2]}, {'colour': [True, 0, 0, 1]},
                      {'dash': [{'length': 0, 'gap': 2}]}, {'dash': [{'length': 1, 'gap': -1}]},
                      {'dash': [{'length': 1, 'gap': 1}]*4}):
            value = intent(); value['styles'][0].update(patch)
            self.refused(value)

    def test_no_raw_properties_module_script_or_native_names(self):
        for key, data in (('script', 'import bpy'), ('rna', {'select_by_visibility': False}),
                          ('nativeName', 'LineSet'), ('modules', ['custom.py'])):
            value = intent(); value[key] = data
            self.refused(value)
            value = intent(); value['styles'][0][key] = data
            self.refused(value)

    def test_aggregate_line_set_budget_is_not_only_per_layer(self):
        value = intent(); value['styles'] = [value['styles'][0]]; value['layers'] = []
        for layer in range(5):
            sets = [{'id': 'line'+str(i), 'style': 'visible', 'edges': ['silhouette'],
                     'visibility': {'kind': 'visible'}, 'scope': {'kind': 'all'}} for i in range(16)]
            value['layers'].append({'layer': 'layer'+str(layer), 'lineSets': sets})
        with self.assertRaises(SchemaxisError) as raised:
            npr.validate(value, layers=['layer'+str(i) for i in range(5)], objects=[], collections=[], materials=[])
        self.assertEqual(raised.exception.fault.code, 'RESOURCE_BUDGET_EXCEEDED')
