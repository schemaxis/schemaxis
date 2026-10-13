"""Generator typing rules of the ParaView catalogue importer (field-data enums, optional
file lists, pair-list tuples, VTK clamp bounds, uncaptured output ports)."""
import unittest
from schemaxis.adaptors.paraview.catalogue import generated_declarations
from schemaxis.adaptors.paraview.catalogue_import import (INDEX_PAIR_PROPERTIES, OPTIONAL_FILE_PROPERTIES,
                                                          VTK_LIMITS, output_ports)
from schemaxis.adaptors.paraview.schema import scene_schema
from schemaxis.bindings import validate_options
from schemaxis.core.declarations import validate_value
from schemaxis.core.faults import SchemaxisError

FIELD_DATA = {
    'pvFieldDatatoAttribute': 'OutputFieldType', 'pvCalculator': 'AttributeType',
    'pvMergeVectorComponents': 'AttributeType', 'pvSelectionQuerySource': 'ElementType',
    'pvContingencyStatistics': 'AttributeMode', 'pvDescriptiveStatistics': 'AttributeMode',
    'pvKMeans': 'AttributeMode', 'pvMulticorrelativeStatistics': 'AttributeMode',
    'pvPrincipalComponentAnalysis': 'AttributeMode',
    'pvWriteCSVWriter': 'FieldAssociation', 'pvWriteDataSetCSVWriter': 'FieldAssociation'}
BASIC = ['Point Data', 'Cell Data', 'Vertex Data', 'Edge Data', 'Row Data']


def code_of(test, operation, options):
    with test.assertRaises(SchemaxisError) as caught:
        validate_options(operation, options, 'x')
    return caught.exception.fault.code


class FieldDataEnumTests(unittest.TestCase):
    def test_every_field_data_option_is_an_enum_of_entry_texts(self):
        found = {}
        for name, declaration in generated_declarations().items():
            for key, binding in declaration['options'].items():
                if 'vtkSMFieldDataDomain' in binding['nativeDomains']:
                    found[name] = key
                    spec = binding['value']
                    self.assertEqual(spec['type'], 'enum', (name, key))
                    self.assertEqual(spec['values'][:5], BASIC)
                    self.assertIn(len(spec['values']), (5, 6))
        self.assertEqual(found, FIELD_DATA)

    def test_texts_validate_and_integers_do_not(self):
        declarations = generated_declarations()
        for name, key in FIELD_DATA.items():
            with self.subTest(name=name):
                spec = declarations[name]['options'][key]['value']
                self.assertEqual(validate_value('Cell Data', spec, 'x'), 'Cell Data')
                with self.assertRaises(SchemaxisError) as caught:
                    validate_value(1, spec, 'x')
                self.assertEqual(caught.exception.fault.code, 'INVALID_ARGUMENT')

    def test_field_data_entry_is_native_only_where_captured(self):
        declarations = generated_declarations()
        self.assertIn('Field Data', declarations['pvKMeans']['options']['AttributeMode']['value']['values'])
        self.assertNotIn('Field Data', declarations['pvCalculator']['options']['AttributeType']['value']['values'])

    def test_curated_calculator_uses_the_same_texts(self):
        from schemaxis.adaptors.paraview.filters import CALCULATOR
        texts = CALCULATOR['options']['association']['value']['values']
        generated = generated_declarations()['pvCalculator']['options']['AttributeType']['value']['values']
        self.assertTrue(set(texts) <= set(generated))

    def test_a_narrowed_domain_is_a_structured_fault(self):
        from schemaxis.adaptors.paraview.native import _configure_binding
        binding = generated_declarations()['pvCalculator']['options']['AttributeType']

        class Property:
            class SMProperty:
                @staticmethod
                def GetCommand(): return 'SetAttributeMode'

        class Proxy:
            def ListProperties(self): return ['AttributeType']
            def GetProperty(self, name): return Property
            def __setattr__(self, name, value): raise ValueError('"Row Data" is not a valid entry')
        with self.assertRaises(SchemaxisError) as caught:
            _configure_binding(Proxy(), binding, 'Row Data', 'Row Data', 'x.AttributeType')
        fault = caught.exception.fault
        self.assertEqual((fault.code, fault.location), ('NATIVE_DOMAIN_MISMATCH', 'x.AttributeType'))
        self.assertTrue(fault.recovery)


class FileListTests(unittest.TestCase):
    SECONDARY = {'pvPLOT3DReader': ['FunctionFileName', 'QFileName'], 'pvSLACDataReader': ['ModeFileName'],
                 'pvRTXMLPolyDataReader': ['Location'],
                 'pvExodusIIReader': ['FilePattern', 'FilePrefix', 'XMLFileName'],
                 'pvRestartedSimExodusReader': ['FilePattern', 'FilePrefix', 'XMLFileName']}

    def constructors(self, declaration):
        return sorted(k for k, v in declaration['options'].items()
                      if v.get('constructor') and 'vtkSMFileListDomain' in v['nativeDomains'])

    def test_secondary_file_lists_are_optional_non_constructor_options(self):
        declarations = generated_declarations()
        for name, keys in self.SECONDARY.items():
            for key in keys:
                binding = declarations[name]['options'][key]
                self.assertNotIn('constructor', binding, (name, key))
                self.assertFalse(binding['value'].get('required'), (name, key))
            self.assertEqual(len(self.constructors(declarations[name])), 1, name)
        self.assertEqual(len(OPTIONAL_FILE_PROPERTIES), 10)

    def test_primary_file_stays_required(self):
        declarations = generated_declarations()
        for name, primary in [('pvPLOT3DReader', 'FileName'), ('pvSLACDataReader', 'MeshFileName'),
                              ('pvRTXMLPolyDataReader', 'FileName'), ('pvExodusIIReader', 'FileName'),
                              ('pvRestartedSimExodusReader', 'FileName')]:
            self.assertEqual(self.constructors(declarations[name]), [primary])

    def test_grid_only_plot3d_and_mesh_only_slac_plan(self):
        declarations = generated_declarations()
        validate_options(declarations['pvPLOT3DReader'], {'FileName': 'grid.xyz'}, 'x')
        validate_options(declarations['pvSLACDataReader'], {'MeshFileName': 'mesh.ncdf'}, 'x')
        validate_options(declarations['pvExodusIIReader'], {'FileName': ['a.e']}, 'x')
        # When supplied, an optional file name must still be non-empty.
        self.assertEqual(code_of(self, declarations['pvPLOT3DReader'], {'FileName': 'g', 'QFileName': ['']}),
                         'INVALID_ARGUMENT')

    def test_camm_connectivity_file_stays_required(self):
        reader = generated_declarations()['pvNetCDFCAMreader']
        self.assertEqual(self.constructors(reader), ['ConnectivityFileName', 'FileName'])
        self.assertEqual(code_of(self, reader, {'FileName': ['a.nc']}), 'MISSING_ARGUMENT')

    def test_these_readers_are_now_readback_eligible(self):
        definitions = {}
        scene_schema(generated_declarations(), definitions)
        offered = {variant['properties']['operation']['const']
                   for variant in definitions['readback']['anyOf'][1]['oneOf']}
        self.assertTrue(set(self.SECONDARY) <= offered)
        self.assertNotIn('pvNetCDFCAMreader', offered)


class TupleTests(unittest.TestCase):
    PAIRS = {'pvRenameArrays': ['PointArrays', 'CellArrays', 'FieldArrays', 'VertexArrays', 'EdgeArrays', 'RowArrays'],
             'pvYoungsMaterialInterface': ['NormalArrays', 'OrderingArrays']}

    def test_array_list_pair_properties_have_tuple_size_two(self):
        declarations = generated_declarations()
        found = {}
        for name, declaration in declarations.items():
            for key, binding in declaration['options'].items():
                if 'vtkSMArrayListDomain' in binding['nativeDomains'] and binding.get('tupleSize'):
                    found.setdefault(name, []).append(key)
                    self.assertEqual(binding['tupleSize'], 2)
        self.assertEqual({k: sorted(v) for k, v in found.items()},
                         {k: sorted(v) for k, v in self.PAIRS.items()})

    def test_odd_length_is_rejected_at_planning(self):
        declarations = generated_declarations()
        self.assertEqual(code_of(self, declarations['pvYoungsMaterialInterface'], {'NormalArrays': ['a', 'n', 'b']}),
                         'INVALID_LENGTH')
        self.assertEqual(code_of(self, declarations['pvRenameArrays'], {'PointArrays': ['p']}), 'INVALID_LENGTH')
        validate_options(declarations['pvRenameArrays'], {'PointArrays': ['p', 'pressure']}, 'x')

    def test_selection_domain_lists_stay_flat(self):
        sized = {(n, k) for n, d in generated_declarations().items() for k, b in d['options'].items()
                 if b.get('tupleSize') and any('SelectionDomain' in x for x in b['nativeDomains'])}
        self.assertEqual(sized, {('pvNetCDFMPASreader', 'ExtraDimensionIndices')})

    def test_mpas_index_pairs_are_name_and_digit_string(self):
        reader = generated_declarations()['pvNetCDFMPASreader']
        binding = reader['options']['ExtraDimensionIndices']
        self.assertEqual((binding['tupleSize'], binding['tupleElementTypes']), (2, ['string', 'index']))
        self.assertEqual(INDEX_PAIR_PROPERTIES, {('sources/MPASReader', 'ExtraDimensionIndices')})
        options = {'FileName': 'a.nc'}
        validate_options(reader, {**options, 'ExtraDimensionIndices': ['nVertLevels', '5']}, 'x')
        self.assertEqual(code_of(self, reader, {**options, 'ExtraDimensionIndices': ['nVertLevels', 'x']}),
                         'INVALID_ARGUMENT')
        self.assertEqual(code_of(self, reader, {**options, 'ExtraDimensionIndices': ['5', '5', 'n']}),
                         'INVALID_LENGTH')
        self.assertEqual(code_of(self, reader, {**options, 'ExtraDimensionIndices': ['nVertLevels', '-1']}),
                         'INVALID_ARGUMENT')


class ClampBoundTests(unittest.TestCase):
    def test_refinement_ratio_minimum_is_the_vtk_clamp(self):
        declaration = generated_declarations()['pvImageDataToAMR']
        self.assertEqual(declaration['options']['RefinementRatio']['value']['minimum'], 2)
        validate_options(declaration, {'RefinementRatio': 2}, 'x')
        self.assertEqual(code_of(self, declaration, {'RefinementRatio': 1}), 'INVALID_ARGUMENT')

    def test_projection_axes_are_zero_to_three(self):
        declaration = generated_declarations()['pvMandelbrot']
        validate_options(declaration, {'ProjectionAxes': [0, 1, 3]}, 'x')
        for axes in ([0, 1, 4], [-1, 1, 2]):
            self.assertEqual(code_of(self, declaration, {'ProjectionAxes': axes}), 'INVALID_ARGUMENT')
        self.assertEqual(set(VTK_LIMITS), {('filters/ImageDataToAMR', 'RefinementRatio'),
                                           ('sources/ImageMandelbrotSource', 'ProjectionAxes')})


class OutputPortTests(unittest.TestCase):
    def test_uncaptured_zero_is_null_but_writers_keep_their_genuine_zero(self):
        self.assertIsNone(output_ports({'outputPorts': 0}, False))
        self.assertIsNone(output_ports({}, False))
        self.assertEqual(output_ports({'outputPorts': 0}, True), 0)
        self.assertEqual(output_ports({'outputPorts': 2}, False), 2)

    def test_no_pipeline_declaration_reports_zero_ports(self):
        for name, declaration in generated_declarations().items():
            ports = declaration['coverage']['outputPorts']
            if declaration.get('role') == 'writer':
                self.assertEqual(ports, 0, name)
            else:
                self.assertNotEqual(ports, 0, name)


if __name__ == '__main__':
    unittest.main()
