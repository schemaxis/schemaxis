# Copyright (C) 2026 David L F Gaden
"""Generator rules that exclude unusable operations or withhold unsafe or inert properties."""
import json
from pathlib import Path
import unittest
from schemaxis.adaptors.paraview.catalogue import generated_declarations
from schemaxis.adaptors.paraview.catalogue_import import command_property, contract

PACKAGE = Path(__file__).resolve().parents[2] / 'src/schemaxis/adaptors/paraview/paraview_catalogue.json'


def inventory():
    return json.loads(PACKAGE.read_text())['inventory']


class GeneratorRuleTests(unittest.TestCase):
    def test_generic_dataset_only_inputs_are_excluded(self):
        generic = ['GenericClip', 'GenericContour', 'GenericGeometryFilter', 'GenericOutlineFilter',
                   'GenericCut', 'GenericStreamTracer', 'GenericTessellator']
        reasons = {key for key, item in inventory().items() if 'vtkGenericDataSet' in item.get('reason', '')}
        self.assertEqual(reasons, {'filters/' + name for name in generic})
        removed = ['pvClipGenericDataset', 'pvContourGenericDataset', 'pvExtractGenericDatasetSurface',
                   'pvOutlineGenericDataSet', 'pvSliceGenericDataset', 'pvStreamTracerForGenericDatasets',
                   'pvTessellateGenericDataset']
        for name in removed: self.assertNotIn(name, generated_declarations())

    def test_non_authorable_proxies_are_excluded(self):
        records = inventory()
        for key in ('filters/PointInterpolatorBase', 'filters/SPHInterpolatorBase'):
            self.assertEqual(records[key]['status'], 'unsupported')
            self.assertEqual(records[key]['reason'], 'no input property connects required port 0')
        self.assertEqual(records['sources/SelectionSourceBase']['status'], 'unsupported')
        # Variants add the port-0 Source through a proxy choice and stay declared.
        declarations = generated_declarations()
        for name in ('pvPointLineInterpolator', 'pvSPHVolumeInterpolator'): self.assertIn(name, declarations)
        for name in ('pvPointInterpolator', 'pvSPHInterpolator', 'pvSelectionSourceBase'):
            self.assertNotIn(name, declarations)

    def test_exact_hit_sets_of_new_rules(self):
        # Each rule must keep hitting only these; a new capture that changes a set needs review.
        records = inventory()
        by_reason = {}
        for key, item in records.items():
            by_reason.setdefault(item.get('reason'), set()).add(key)
        self.assertEqual(by_reason['no input property connects required port 0'],
                         {'filters/PointInterpolatorBase', 'filters/SPHInterpolatorBase'})
        self.assertEqual(by_reason['internal base proxy without a VTK class or output ports'],
                         {'sources/SelectionSourceBase'})
        def gaps(reason):
            return {(key, name) for key, item in records.items()
                    for name, text in item.get('propertyGaps', {}).items() if text == reason}
        self.assertEqual(gaps('no native command (GUI-only property)'),
                         {('writers/IOSSWriter', 'ChoosetheoutputblocksarraysfortheExodusEntityType')})
        self.assertEqual(gaps('domain-only input (no native command)'),
                         {('writers/OpenVDBWriter', 'DummyInput')})
        self.assertEqual(gaps('zero-element property with no usable native command'),
                         {('filters/ForceStaticMesh', 'ForceCacheComputation')})

    def test_unsafe_command_is_refused_at_assignment(self):
        from schemaxis.adaptors.paraview.selection_query import guard_native_value
        from schemaxis.core.faults import SchemaxisError
        with self.assertRaises(SchemaxisError) as caught:
            guard_native_value('SetDataSourceIO', ['0x1', 'x'], 'nodes[0].options.DataSourceIO')
        self.assertIn('UNSAFE_NATIVE_PROPERTY', str(caught.exception.__dict__) + str(caught.exception))
        self.assertEqual(guard_native_value('SetRadius', 1, 'x'), 1)

    def test_native_memory_address_property_is_a_gap(self):
        declarations = generated_declarations()
        for name in ('pvFidesReader', 'pvFidesJSONReader'):
            self.assertNotIn('DataSourceIO', declarations[name]['options'])
            self.assertIn('memory address', declarations[name]['coverage']['gaps']['DataSourceIO'])

    def test_gui_only_property_is_a_gap_but_resource_properties_remain(self):
        key = 'ChoosetheoutputblocksarraysfortheExodusEntityType'
        iossw = generated_declarations()['pvWriteIOSSWriter']
        self.assertNotIn(key, iossw['options'])
        self.assertIn(key, iossw['coverage']['gaps'])
        lookup = generated_declarations()['pvResourcePVLookupTable']
        self.assertIn('AutomaticRescaleRangeMode', lookup['options'])

    def test_csv_writers_manage_separate_time_steps(self):
        declarations = generated_declarations()
        for name in ('pvWriteCSVWriter', 'pvWriteDataSetCSVWriter'):
            self.assertNotIn('WriteTimeStepsSeparately', declarations[name]['options'])

    def test_zero_element_property_is_not_a_command(self):
        prop = {'class': 'vtkSMIntVectorProperty', 'numberOfElements': 0,
                'definition': {'attributes': {'command': 'SetX'}}}
        self.assertFalse(command_property(prop))
        self.assertTrue(command_property({'class': 'vtkSMProperty', 'definition': {'attributes': {'command': 'Go'}}}))
        static = generated_declarations()['pvForceStaticMesh']
        self.assertNotIn('commands', static)
        self.assertIn('ForceCacheComputation', static['coverage']['gaps'])

    def test_command_less_dummy_input_is_not_an_input(self):
        writer = generated_declarations()['pvWriteOpenVDBWriter']
        self.assertNotIn('DummyInput', writer['inputs'])
        self.assertIn('DummyInput', writer['coverage']['gaps'])
        self.assertIn('Input', writer['inputs'])
        # Linked and compound proxies have empty captured definitions and keep their inputs.
        self.assertIn('Input', generated_declarations()['pvNormalGlyphs']['inputs'])

    def test_composite_required_is_recorded(self):
        prop = {'definition': {'tag': 'InputProperty', 'children': [{'tag': 'DataTypeDomain', 'attributes': {
            'composite_data_supported': '1'}, 'children': [{'tag': 'DataType', 'attributes': {'value': 'vtkHyperTreeGrid'}}]}]}}
        self.assertTrue(contract(prop)['composite'] is True)
        self.assertEqual(contract(prop, composite_required=True)['composite'], 'required')
        htg = generated_declarations()['pvWriteSerialHTGMultiBlock']['inputs']['Input']['contract']
        self.assertEqual(htg['composite'], 'required')
        self.assertEqual(htg['nativeTypes'], ['vtkHyperTreeGrid'])


if __name__ == '__main__':
    unittest.main()
