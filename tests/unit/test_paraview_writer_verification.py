"""Writer verifiers must match what the native ParaView 5.13.3 writers emit.

Houdini samples are literal texts built from the print statements of
PV5.13.3:VTK/IO/Geometry/vtkHoudiniPolyDataWriter.cxx (line numbers cited per case).
Native objects are replaced by small stand-ins; no ParaView is imported.
"""
import copy
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.paraview import writers
from schemaxis.adaptors.paraview.job import plan
from schemaxis.adaptors.paraview.writers import LOSSES


# ---------------------------------------------------------------- stand-ins
class Points:
    def __init__(self): self.points = []
    def SetDataTypeToDouble(self): pass
    def InsertNextPoint(self, x, y, z): self.points.append((x, y, z))


class Cells:
    def __init__(self): self.cells = []
    def InsertNextCell(self, count): self.cells.append([])
    def InsertCellPoint(self, i): self.cells[-1].append(i)


class PolyData:
    def SetPoints(self, value): self.points = value.points
    def SetPolys(self, value): self.polys = value.cells
    def SetVerts(self, value): self.verts = value.cells
    def SetLines(self, value): self.lines = value.cells


def fake_vtk():
    core = types.ModuleType('vtkmodules.vtkCommonCore'); core.vtkPoints = Points
    model = types.ModuleType('vtkmodules.vtkCommonDataModel')
    model.vtkCellArray = Cells; model.vtkPolyData = PolyData
    package = types.ModuleType('vtkmodules')
    return mock.patch.dict(sys.modules, {'vtkmodules': package, 'vtkmodules.vtkCommonCore': core,
                                         'vtkmodules.vtkCommonDataModel': model})


class Array:
    def __init__(self, name, rows, kind=11, strings=False):
        self.name, self.rows, self.kind = name, [tuple(r) if isinstance(r, (list, tuple)) else (r,) for r in rows], kind
        self.strings = strings
    def GetName(self): return self.name
    def GetNumberOfComponents(self): return len(self.rows[0]) if self.rows else 1
    def GetNumberOfTuples(self): return len(self.rows)
    def GetDataType(self): return 13 if self.strings else self.kind  # 11 double, 3 uchar, 2 char
    def GetDataTypeAsString(self): return {11: 'double', 3: 'unsigned char', 2: 'char'}.get(self.kind, 'other')
    def GetComponent(self, i, c): return self.rows[i][c]
    def GetValue(self, i):
        width = self.GetNumberOfComponents()
        value = self.rows[i // width][i % width]
        return chr(value) if self.kind == 2 and not self.strings else value  # char -> str under VTK wrapping


class Fields:
    def __init__(self, *arrays): self.arrays = list(arrays)
    def GetNumberOfArrays(self): return len(self.arrays)
    def GetAbstractArray(self, i): return self.arrays[i]
    def GetArray(self, key):
        if isinstance(key, int): return self.arrays[key]
        return next((a for a in self.arrays if a.name == key), None)
    def GetNumberOfTuples(self): return self.arrays[0].GetNumberOfTuples() if self.arrays else 0


class Data:
    def __init__(self, kinds, point=(), cell=(), row=(), field=(), dims=(2, 2, 1), points=4):
        self.kinds, self.dims, self.count = set(kinds), dims, points
        self.point, self.cell, self.row, self.field = Fields(*point), Fields(*cell), Fields(*row), Fields(*field)
    def IsA(self, name): return name in self.kinds
    def GetPointData(self): return self.point
    def GetCellData(self): return self.cell
    def GetRowData(self): return self.row
    def GetFieldData(self): return self.field
    def GetDimensions(self): return self.dims
    def GetOrigin(self): return (0.0, 0.0, 0.0)
    def GetSpacing(self): return (1.0, 1.0, 1.0)
    def GetNumberOfPoints(self): return self.count
    def GetBounds(self): return (0.0, 100.0, -3.0, 2.0, 0.0, 0.0)


def document(writer, **export):
    return {'version': 'schemaxis/1', 'nodes': [{'id': 'sphere', 'filter': 'pvSphere'}],
            'scenes': [{'id': 'export', 'exports': [{'id': 'out', 'node': 'sphere', 'writer': writer, **export}]}]}


def planned(writer, **export):
    return plan(document(writer, **export))


def fault_code(callable_, *args, **kwargs):
    with unittest.TestCase().assertRaises(SchemaxisError) as caught:
        callable_(*args, **kwargs)
    return caught.exception.fault


# ---------------------------------------------------------------- Houdini grammar
# vtkHoudiniPolyDataWriter.cxx:326-333 header, 374-392 points, 553-554 trailer.
POLYS_WITH_POINT_ATTRIBUTES = """PGEOMETRY V2
NPoints 4 NPrims 2
NPointGroups 0 NPrimGroups 0
NPointAttrib 1 NVertexAttrib 0 NPrimAttrib 0 NAttrib 0
PointAttrib
Normals 3 float 0 0 0
0 0 0 1 (0 0 1)
1 0 0 1 (0 0 1)
1 1 0 1 (0 0 1)
0 1 0 1 (0 0 1)
Run 2 Poly
3 < 0 1 2
3 < 0 2 3
beginExtra
endExtra
"""

# Every primitive family with one cell array: verts 420-453, lines 455-481, polys 483-509,
# strips 511-551 (a 3-point strip is the single line 'Poly 3 < ...', a 5-point strip is
# 'Run 3 Poly' plus three triangles), NPrims = 2 + 1 + 1 + 1 + 3 (309-323).
ALL_FAMILIES_WITH_CELL_ATTRIBUTES = """PGEOMETRY V2
NPoints 6 NPrims 8
NPointGroups 0 NPrimGroups 0
NPointAttrib 0 NVertexAttrib 0 NPrimAttrib 1 NAttrib 0
0 0 0 1
1 0 0 1
2 0 0 1
0 1 0 1
1 1 0 1
2 1 0 1
PrimitiveAttrib
Id 1 int 48
Run 2 Part
1 0 [7]
1 1 [8]
Run 1 Poly
3 : 0 1 2 [9]
Run 1 Poly
3 < 2 3 4 [10]
Poly 3 < 3 4 5 [11]
Run 3 Poly
3 < 0 1 2 [12]
3 < 2 1 3 [12]
3 < 2 3 4 [12]
beginExtra
endExtra
"""

SINGLE_VERTEX = """PGEOMETRY V2
NPoints 1 NPrims 1
NPointGroups 0 NPrimGroups 0
NPointAttrib 0 NVertexAttrib 0 NPrimAttrib 0 NAttrib 0
-1.5e-05 2.25 1e+06 1
Part 1 0
beginExtra
endExtra
"""


class HoudiniReaderTests(unittest.TestCase):
    def read(self, text):
        with tempfile.TemporaryDirectory() as folder, fake_vtk():
            path = Path(folder) / 'data.geo'; path.write_text(text)
            return writers.read_houdini(path)

    def test_polygons_with_point_attribute_brackets(self):
        mesh = self.read(POLYS_WITH_POINT_ATTRIBUTES)
        self.assertEqual(len(mesh.points), 4)
        self.assertEqual(mesh.polys, [[0, 1, 2], [0, 2, 3]])
        self.assertEqual((mesh.verts, mesh.lines), ([], []))

    def test_every_primitive_family_cell_attributes_and_strips(self):
        mesh = self.read(ALL_FAMILIES_WITH_CELL_ATTRIBUTES)
        self.assertEqual(mesh.verts, [[0], [1]])
        self.assertEqual(mesh.lines, [[0, 1, 2]])
        # the polygon, the 3-point strip's triangle and the 5-point strip's three triangles
        self.assertEqual(mesh.polys, [[2, 3, 4], [3, 4, 5], [0, 1, 2], [2, 1, 3], [2, 3, 4]])

    def test_single_particle_and_scientific_coordinates(self):
        mesh = self.read(SINGLE_VERTEX)
        self.assertEqual(mesh.verts, [[0]])
        self.assertEqual(mesh.points, [(-1.5e-05, 2.25, 1e6)])

    def test_nprims_must_count_emitted_primitives(self):
        text = ALL_FAMILIES_WITH_CELL_ATTRIBUTES.replace('NPrims 8', 'NPrims 6')  # input cells, not triangles
        self.assertEqual(fault_code(self.read, text).code, 'UNSUPPORTED_FORMAT')

    def test_unknown_or_truncated_records_are_structured_faults(self):
        for label, text in {
            'unknown primitive': SINGLE_VERTEX.replace('Part 1 0', 'Sphere 1 0'),
            'degenerate strip glues Poly onto the next record': SINGLE_VERTEX.replace('Part 1 0', 'Poly beginExtra'),
            'missing trailer': SINGLE_VERTEX.replace('endExtra\n', ''),
            'bad connectivity': SINGLE_VERTEX.replace('Part 1 0', 'Part 1 5'),
            'short point attribute block': POLYS_WITH_POINT_ATTRIBUTES.replace('PointAttrib\n', ''),
            'wrong magic': SINGLE_VERTEX.replace('V2', 'V3'),
        }.items():
            with self.subTest(label):
                self.assertIn(fault_code(self.read, text).code, ('UNSUPPORTED_FORMAT', 'INVALID_ARTIFACT'))


class HoudiniPrecisionTests(unittest.TestCase):
    def test_minimum_tolerance_is_half_a_unit_in_the_sixth_digit(self):
        self.assertAlmostEqual(writers.houdini_minimum_tolerance(0.479746), 0.5e-6)
        self.assertAlmostEqual(writers.houdini_minimum_tolerance(100.0), 0.5e-3)
        self.assertEqual(writers.houdini_minimum_tolerance(0), 0.0)

    def test_zero_tolerance_is_rejected_at_planning(self):
        kwargs = dict(acceptLosses=LOSSES['geometry'])
        self.assertEqual(fault_code(planned, 'pvWriteHoudiniWriter', **kwargs).code, 'INVALID_TOLERANCE')
        self.assertIn('recovery', fault_code(planned, 'pvWriteHoudiniWriter', **kwargs).observed)
        self.assertEqual(planned('pvWriteHoudiniWriter', tolerance=1e-6, **kwargs)[1][0]['exports'][0]['tolerance'], 1e-6)

    def test_houdini_requires_the_geometry_contract(self):
        self.assertEqual(fault_code(planned, 'pvWriteHoudiniWriter', comparison='exact').code, 'INVALID_VERIFICATION')

    def test_publication_rejects_a_tolerance_below_the_coordinate_rounding(self):
        settings = {'tolerance': 1e-6, 'comparison': 'geometry'}
        fault = fault_code(writers.check_input_contract, 'HoudiniWriter', Data({'vtkPolyData'}), {}, settings, 'out')
        self.assertEqual(fault.code, 'TOLERANCE_BELOW_WRITER_PRECISION')
        self.assertAlmostEqual(fault.observed['minimum'], 0.5e-3)
        settings['tolerance'] = 1e-3
        writers.check_input_contract('HoudiniWriter', Data({'vtkPolyData'}), {}, settings, 'out')


# ---------------------------------------------------------------- CSV
class FakeProperty:
    def __init__(self, value): self.SMProperty = types.SimpleNamespace(GetElement=lambda index: value)


class FakeWriter:
    def __init__(self, **values): self.values = values
    def GetProperty(self, key): return FakeProperty(self.values[key]) if key in self.values else None


class CsvTests(unittest.TestCase):
    def verify(self, data, text, effective=None, suffix='.csv', tolerance=0.0, **override):
        base = {'FieldAssociation': 'Point Data', 'FieldDelimiter': ',', 'StringDelimiter': '"', 'UseStringDelimiter': True}
        if effective is not None: base = effective
        base = {**base, **override}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ('data' + suffix); path.write_text(text)
            return writers.verify_csv(data, path, base, tolerance)

    def points(self):
        return Data({'vtkDataSet'}, point=[Array('T', [1.0, 2.0])], points=2)

    def test_association_texts_are_the_field_data_domain_entries(self):
        self.assertEqual(sorted(writers.FIELD_ASSOCIATIONS.values()),
                         ['Cell Data', 'Edge Data', 'Field Data', 'Point Data', 'Row Data', 'Vertex Data'])

    def test_effective_association_text_selects_the_arrays(self):
        data = Data({'vtkDataSet'}, point=[Array('P', [1.0, 2.0, 3.0])], cell=[Array('C', [5.0, 6.0])], points=3)
        self.assertEqual(self.verify(data, 'C\n5\n6\n', FieldAssociation='Cell Data')['association'], 'Cell Data')
        self.assertEqual(self.verify(data, 'P\n1\n2\n3\n', FieldAssociation='Point Data')['association'], 'Point Data')
        table = Data({'vtkTable'}, row=[Array('R', [1.0])])
        self.assertEqual(self.verify(table, 'R\n1\n', FieldAssociation='Row Data')['association'], 'Row Data')

    def test_unknown_and_unverifiable_associations_fault_without_guessing(self):
        for value in (0, 'Points', 'point data'):
            with self.subTest(value=value):
                self.assertEqual(fault_code(self.verify, self.points(), 'T\n1\n2\n', FieldAssociation=value).code,
                                 'INVALID_ASSOCIATION')
        for value in ('Field Data', 'Vertex Data', 'Edge Data'):
            fault = fault_code(self.verify, self.points(), 'T\n1\n2\n', FieldAssociation=value)
            self.assertEqual(fault.code, 'UNSUPPORTED_ASSOCIATION')
            self.assertEqual(fault.observed['supported'], ['Point Data', 'Cell Data', 'Row Data'])

    def test_read_back_settings_are_required(self):
        for key in ('FieldAssociation', 'FieldDelimiter', 'StringDelimiter', 'UseStringDelimiter'):
            effective = {'FieldAssociation': 'Point Data', 'FieldDelimiter': ',', 'StringDelimiter': '"', 'UseStringDelimiter': True}
            del effective[key]
            with self.subTest(key=key):
                fault = fault_code(self.verify, self.points(), 'T\n1\n2\n', effective)
                self.assertEqual((fault.code, fault.observed['missing']), ('MISSING_EFFECTIVE_SETTINGS', [key]))
        self.assertEqual(fault_code(self.verify, self.points(), 'T\n1\n2\n', {}).code, 'MISSING_EFFECTIVE_SETTINGS')

    def test_settings_come_from_the_writer_proxy(self):
        data = Data({'vtkDataSet'}, point=[Array('P', [1.0, 2.0])], cell=[Array('C', [5.0, 6.0])], points=2)
        effective = writers.effective_csv_settings(FakeWriter(FieldAssociation=1, FieldDelimiter=',',
                                                              UseStringDelimiter=1, StringDelimiter='"'))
        self.assertEqual(effective['FieldAssociation'], 'Cell Data')
        self.assertEqual(self.verify(data, 'C\n5\n6\n', effective)['association'], 'Cell Data')
        self.assertEqual(fault_code(writers.effective_csv_settings, FakeWriter(FieldAssociation=3)).code, 'INVALID_ASSOCIATION')

    def test_tsv_is_verified_with_the_tab_read_back_from_paraview(self):
        data = Data({'vtkDataSet'}, point=[Array('T', [1.0, 2.0]), Array('U', [3.0, 4.0])], points=2)
        effective = writers.effective_csv_settings(FakeWriter(FieldAssociation=0, FieldDelimiter='\t',
                                                              UseStringDelimiter=1, StringDelimiter='"'))
        result = self.verify(data, 'T\tU\n1\t3\n2\t4\n', effective, suffix='.tsv')
        self.assertEqual((result['delimiter'], result['verifiedColumns']), ('\t', ['T', 'U']))

    def test_multi_character_delimiters_are_structured_faults(self):
        self.assertEqual(fault_code(self.verify, self.points(), 'T\n1\n2\n', FieldDelimiter='::').code, 'UNSUPPORTED_DELIMITER')
        self.assertEqual(fault_code(self.verify, self.points(), 'T\n1\n2\n', StringDelimiter="''").code, 'UNSUPPORTED_DELIMITER')

    def test_string_delimiter_settings_are_honoured(self):
        data = Data({'vtkDataSet'}, point=[Array('N', ['a,b', 'c'], strings=True)], points=2)
        self.verify(data, '"N"\n"a,b"\n"c"\n')
        self.verify(Data({'vtkDataSet'}, point=[Array('N', ['ab', 'c'], strings=True)], points=2), 'N\nab\nc\n',
                    UseStringDelimiter=False)

    def test_composite_input_is_a_structured_fault(self):
        data = Data({'vtkCompositeDataSet'})
        fault = fault_code(self.verify, data, 'x\n')
        self.assertEqual(fault.code, 'UNSUPPORTED_DATA_TYPE')
        self.assertIn('pvMergeBlocks', fault.observed['recovery'])
        self.assertEqual(fault_code(writers.check_input_contract, 'CSVWriter', data, {}, {'comparison': 'table'}, 'out').code,
                         'UNSUPPORTED_DATA_TYPE')

    def test_unverifiable_associations_are_rejected_at_planning(self):
        kwargs = dict(acceptLosses=LOSSES['table'])
        for writer in ('pvWriteCSVWriter', 'pvWriteDataSetCSVWriter'):
            for text in ('Field Data', 'Vertex Data', 'Edge Data'):
                with self.subTest(writer=writer, association=text):
                    fault = fault_code(planned, writer, options={'FieldAssociation': text}, **kwargs)
                    self.assertEqual(fault.code, 'UNSUPPORTED_ASSOCIATION')
            for text in ('Point Data', 'Cell Data', 'Row Data'):  # Row Data depends on the input type, which publication checks
                self.assertTrue(planned(writer, options={'FieldAssociation': text}, **kwargs))
            # The schema offers ParaView's entry texts only, so integer codes never reach the verifier.
            self.assertNotEqual(fault_code(planned, writer, options={'FieldAssociation': 0}, **kwargs).code, 'UNSUPPORTED_ASSOCIATION')
        for text in ('Field Data', 'Vertex Data', 'Edge Data'):
            self.assertEqual(fault_code(writers.check_csv_association, {'FieldAssociation': text}, 'o').code, 'UNSUPPORTED_ASSOCIATION')
        writers.check_csv_association({'FieldAssociation': 'Row Data'}, 'o')
        writers.check_csv_association({'FieldAssociation': {'$observe': 'x'}}, 'o')


# ---------------------------------------------------------------- JPEG
class JpegTests(unittest.TestCase):
    def test_zero_tolerance_is_rejected_at_planning(self):
        kwargs = dict(acceptLosses=LOSSES['pixels'])
        fault = fault_code(planned, 'pvWriteJPEGWriter', **kwargs)
        self.assertEqual(fault.code, 'INVALID_TOLERANCE')
        self.assertIn('PNG', fault.observed['recovery'])
        self.assertEqual(planned('pvWriteJPEGWriter', tolerance=3, **kwargs)[1][0]['exports'][0]['tolerance'], 3)

    def test_jpeg_requires_the_pixels_contract(self):
        self.assertEqual(fault_code(planned, 'pvWriteJPEGWriter', comparison='exact').code, 'INVALID_VERIFICATION')

    def test_only_unsigned_char_scalars_are_accepted(self):
        def image(scalars):
            data = Data({'vtkImageData'}, point=[scalars] if scalars else [])
            data.point.GetScalars = lambda: scalars
            return data
        settings = {'comparison': 'pixels', 'tolerance': 3.0}
        writers.check_input_contract('JPEGWriter', image(Array('RGB', [(1, 2, 3)], kind=3)), {}, settings, 'out')
        for scalars in (Array('s', [1.5], kind=11), None):
            fault = fault_code(writers.check_input_contract, 'JPEGWriter', image(scalars), {}, settings, 'out')
            self.assertEqual(fault.code, 'UNSUPPORTED_DATA_TYPE')
            self.assertIn('unsigned char', fault.observed['recovery'])


# ---------------------------------------------------------------- JSON image
class JsonImageTests(unittest.TestCase):
    def image(self, *arrays, dims=(2, 2, 2)):
        return Data({'vtkImageData'}, point=arrays, dims=dims, points=dims[0] * dims[1] * dims[2])

    def verify(self, data, content, options=None, tolerance=0.0):
        document = {'dimensions': list(data.GetDimensions()), 'origin': [0, 0, 0], 'spacing': [1, 1, 1], **content}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'data.json'; path.write_text(json.dumps(document))
            return writers.verify_json_image(data, path, tolerance, options)

    def setUp(self):
        self.a = Array('a', list(range(8)))
        self.b = Array('b', [10 * i for i in range(8)])

    def test_default_verifies_every_scalar_array(self):
        result = self.verify(self.image(self.a, self.b), {'a': list(range(8)), 'b': [10 * i for i in range(8)]})
        self.assertEqual(result['fields'], ['a', 'b'])

    def test_array_name_restricts_to_that_array_and_requires_it(self):
        data = self.image(self.a, self.b)
        self.assertEqual(self.verify(data, {'b': [10 * i for i in range(8)]}, {'ArrayName': 'b'})['fields'], ['b'])
        self.assertEqual(fault_code(self.verify, data, {'a': list(range(8))}, {'ArrayName': 'b'}).code, 'VERIFICATION_FAILED')
        self.assertEqual(fault_code(self.verify, data, {}, {'ArrayName': 'missing'}).code, 'VERIFICATION_FAILED')

    def test_slice_keeps_full_dimensions_but_one_plane_of_values(self):
        data = self.image(self.a)
        result = self.verify(data, {'a': [4, 5, 6, 7]}, {'Slice': 1})
        self.assertEqual((result['slice'], result['dimensions']), (1, [2, 2, 2]))
        self.assertEqual(fault_code(self.verify, data, {'a': list(range(8))}, {'Slice': 1}).code, 'VERIFICATION_FAILED')

    def test_slice_is_bound_checked(self):
        data = self.image(self.a)
        fault = fault_code(writers.check_json_image_options, data, {'Slice': 2})
        self.assertEqual(fault.code, 'INVALID_SLICE')
        self.assertEqual(fault_code(writers.check_input_contract, 'JSONImageWriter', data, {'Slice': 9}, {'comparison': 'pixels'}, 'o').code,
                         'INVALID_SLICE')
        writers.check_json_image_options(data, {'Slice': 1})
        writers.check_json_image_options(data, {'Slice': -1})

    def test_vector_arrays_and_the_valid_point_mask_are_not_written(self):
        vector = Array('v', [(i, i, i) for i in range(8)])
        mask = Array('vtkValidPointMask', [1] * 8, kind=2)
        data = self.image(self.a, vector, mask)
        result = self.verify(data, {'a': list(range(8))})
        self.assertEqual((result['fields'], result['omittedFields']), (['a'], ['v', 'vtkValidPointMask']))

    def test_receipt_records_the_arrays_and_planes_left_out_by_options(self):
        data = self.image(self.a, self.b)
        result = self.verify(data, {'b': [40, 50, 60, 70]}, {'ArrayName': 'b', 'Slice': 1})
        self.assertEqual((result['omittedFields'], result['omittedSlices']), (['a'], 1))

    def test_masked_points_are_null_and_only_there(self):
        mask = Array('vtkValidPointMask', [1, 0, 1, 1, 1, 1, 0, 1], kind=2)
        data = self.image(self.a, mask)
        expected = [0, None, 2, 3, 4, 5, None, 7]
        result = self.verify(data, {'a': expected})
        self.assertEqual(result['maskedPoints'], 2)
        self.assertEqual(fault_code(self.verify, data, {'a': list(range(8))}).code, 'VERIFICATION_FAILED')
        self.assertEqual(fault_code(self.verify, data, {'a': [0, None, 2, 3, 4, 5, 6, 7]}).code, 'VERIFICATION_FAILED')

    def test_mask_applies_by_global_index_within_a_slice(self):
        mask = Array('vtkValidPointMask', [1, 1, 1, 1, 1, 0, 1, 1], kind=2)
        self.assertEqual(self.verify(self.image(self.a, mask), {'a': [4, None, 6, 7]}, {'Slice': 1})['maskedPoints'], 1)

    def test_a_non_char_mask_does_not_mask(self):  # the writer down-casts to vtkCharArray (cxx:71-72)
        mask = Array('vtkValidPointMask', [0] * 8, kind=11)
        self.assertEqual(self.verify(self.image(self.a, mask), {'a': list(range(8))})['fields'], ['a'])


# ---------------------------------------------------------------- selection constraints
class SelectionConstraintTests(unittest.TestCase):
    """ChooseArraysToWrite/ChooseBlocksToWrite make the file smaller than its node."""

    def rejected(self, writer, option, **export):
        fault = fault_code(planned, writer, options={option: True}, **export)
        return fault

    def test_array_selection_is_rejected_for_exact_semantic_and_table_comparisons(self):
        cases = {'exact': ('pvWriteXMLPolyDataWriter', {}),
                 'semantic': ('pvWriteExodusIIWriter', {'acceptLosses': LOSSES['semantic']}),
                 'table': ('pvWriteCSVWriter', {'acceptLosses': LOSSES['table']})}
        for comparison, (writer, extra) in cases.items():
            with self.subTest(comparison):
                fault = self.rejected(writer, 'ChooseArraysToWrite', **extra)
                self.assertEqual(fault.code, 'ARRAY_SELECTION_UNVERIFIABLE')
                self.assertEqual(fault.observed['recovery'], 'filter arrays with pvPassArrays and export that node')
                self.assertEqual(fault.observed['comparison'], comparison)
                self.assertTrue(planned(writer, **extra))  # unselected arrays stay accepted

    def test_array_selection_stays_available_to_geometry_comparisons(self):
        scenes = planned('pvWritePPLYWriter', options={'ChooseArraysToWrite': True},
                         acceptLosses=LOSSES['geometry'], tolerance=1e-6)[1]
        self.assertTrue(scenes[0]['exports'][0]['options']['ChooseArraysToWrite'])

    def test_block_selection_is_rejected_for_every_comparison(self):
        writer = 'pvWriteXMLMultiBlockDataWriter'
        for comparison, losses in (('exact', []), ('semantic', LOSSES['semantic']), ('geometry', LOSSES['geometry'])):
            with self.subTest(comparison):
                fault = self.rejected(writer, 'ChooseBlocksToWrite', comparison=comparison, acceptLosses=losses,
                                      **({'tolerance': 1e-6} if comparison != 'exact' else {}))
                self.assertEqual(fault.code, 'BLOCK_SELECTION_UNVERIFIABLE')
                self.assertIn('pvExtractBlock', fault.observed['recovery'])

    def test_deferred_values_are_checked_again_once_resolved(self):
        writers.check_verifiable_selection({'ChooseArraysToWrite': {'$observe': 'x'}}, 'exact', 'out')
        self.assertEqual(fault_code(writers.check_verifiable_selection, {'ChooseArraysToWrite': True}, 'exact', 'out').code,
                         'ARRAY_SELECTION_UNVERIFIABLE')


# ---------------------------------------------------------------- IOSS time (needs native probe)
class IossTimeRangeTests(unittest.TestCase):
    """Native pvbatch probe (5.13.3): [k, k+1] with stride 2 writes exactly step k; a default export writes every step."""

    def test_range_selects_exactly_the_scheduled_step(self):
        steps = [0.0, 0.5, 1.0, 1.5]
        for index, value in enumerate(steps):
            managed = writers.ioss_single_step_range(steps, value)
            self.assertEqual(managed, {'TimeStepRange': [index, index + 1], 'TimeStepStride': 2})
            # model of PV5.13.3:VTK/IO/IOSS/vtkIOSSWriter.cxx:244-257
            first, last = managed['TimeStepRange']
            written = list(range(max(first, 0), min(last + 1, len(steps)), managed['TimeStepStride']))
            self.assertEqual(written, [index])

    def test_single_step_inputs_need_no_range_and_unknown_times_fault(self):
        self.assertIsNone(writers.ioss_single_step_range([0.0], 0.0))
        self.assertIsNone(writers.ioss_single_step_range(None, 0.0))
        self.assertEqual(fault_code(writers.ioss_single_step_range, [0.0, 1.0], 0.25).code, 'TIME_NOT_IN_INPUT')

    def test_apply_sets_the_managed_properties(self):
        writer = types.SimpleNamespace()
        writers.apply_ioss_single_step(writer, [0.0, 1.0, 2.0], 1.0, 'out')
        self.assertEqual((writer.TimeStepRange, writer.TimeStepStride), ([1, 2], 2))
        bare = types.SimpleNamespace()
        self.assertIsNone(writers.apply_ioss_single_step(bare, [0.0], 0.0, 'out'))
        self.assertFalse(hasattr(bare, 'TimeStepRange'))

    def test_the_two_settings_are_no_longer_authorable(self):
        self.assertTrue(writers.managed_property('TimeStepRange') and writers.managed_property('TimeStepStride'))
        value = document('pvWriteIOSSWriter', acceptLosses=LOSSES['semantic'], options={'TimeStepRange': [0, 1]})
        self.assertEqual(fault_code(plan, value).code, 'UNKNOWN_ARGUMENT')


if __name__ == '__main__':
    unittest.main()
