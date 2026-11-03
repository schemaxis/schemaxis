# Copyright (C) 2026 David L F Gaden
"""Bounds and verification regressions for the expanded native adaptors."""
import copy
import json
from pathlib import Path
import unittest
from schemaxis.core.faults import SchemaxisError
from schemaxis.blender_adaptor import plan as blender_plan
from schemaxis.blender_settings import matching, render_settings
from schemaxis.filters import catalogue, validate_options
from schemaxis.native import snapshot


class ExpansionTests(unittest.TestCase):
    def test_gpu_settings_are_explicit_and_cpu_remains_default(self):
        self.assertEqual(render_settings({})['device'], 'CPU')
        document = json.loads(Path('examples/schemaxis/blender-gallery.json').read_text())
        self.assertEqual(blender_plan(document)[2]['renderSettings']['device'], 'OPTIX')

    def test_invalid_render_settings_fail_before_native_execution(self):
        for value in [{'device':'GPU'}, {'samples':0}, {'samples':True}, {'lightSize':0},
                      {'worldColour':[2,0,0]}, {'threads':65}, {'unknown':1}]:
            with self.subTest(value=value), self.assertRaises(SchemaxisError):
                render_settings(value)

    def test_render_comparison_rejects_changed_or_missing_evidence(self):
        expected = render_settings({})
        self.assertTrue(matching(copy.deepcopy(expected), expected))
        for key, value in [('samples', 9), ('device','OPTIX'), ('denoise',1)]:
            altered = {**expected, key:value}
            self.assertFalse(matching(altered, expected))
        self.assertFalse(matching({}, expected))
        self.assertFalse(matching({**expected, 'extra':0}, expected))

    def test_blender_expansion_rejects_unbounded_or_invalid_inputs(self):
        from schemaxis.blender_adaptor import DECLARATIONS
        for operation, options in [('uvSphere',{'segments':10000}),
                                   ('subdivision',{'levels':5}), ('array',{'count':0}),
                                   ('transform',{'scale':[1,0,1]}),
                                   ('mirror',{'axes':[1,0,0]}),
                                   ('material',{'metallic':2}), ('wireframe',{'thickness':0}),
                                   ('wireframe',{'offset':2}), ('wireframe',{'replace':1})]:
            with self.subTest(operation=operation), self.assertRaises(SchemaxisError):
                validate_options(DECLARATIONS[operation], options, operation)

    def test_wireframe_bridge_plans_two_states_and_typed_material_dependency(self):
        document = json.loads(Path('examples/schemaxis/paraview-blender-wireframe.json').read_text())
        document = document['operations'][1]['document']
        document['nodes'][0]['options']['file'] = '/tmp/source.gltf'
        master, selection, prepared = blender_plan(document)
        self.assertEqual(selection.count, 2)
        self.assertEqual(prepared['expectedPublications'], 4)
        self.assertLess(selection.order.index('paint'), selection.order.index('styled'))
        bad = copy.deepcopy(document)
        bad['nodes'][2]['inputs']['material'] = 'imported'
        with self.assertRaises(SchemaxisError):
            blender_plan(bad)

    def test_paraview_readers_require_one_filename(self):
        declarations = catalogue()
        for name in ['readSTL','readPLY','readImageData','readStructuredGrid',
                     'readUnstructuredGrid','readRectilinearGrid','readMultiBlock']:
            for files in [[], ['a','b'], ['']]:
                with self.subTest(name=name,files=files), self.assertRaises(SchemaxisError):
                    validate_options(declarations[name], {'files':files}, name)

    def test_disk_radius_order_is_validated(self):
        with self.assertRaises(SchemaxisError):
            validate_options(catalogue()['disk'], {'innerRadius':2,'outerRadius':1}, 'disk')

    def test_rectilinear_snapshot_ignores_fetch_padding_but_checks_coordinates(self):
        class Array:
            def __init__(self, values): self.values = values
            def GetDataType(self): return 11
            def GetDataTypeAsString(self): return 'double'
            def GetNumberOfComponents(self): return 1
            def GetNumberOfTuples(self): return len(self.values)
            def GetTuple(self, i): return (self.values[i],)
            def GetName(self): return 'coordinate'
        class Empty:
            def GetNumberOfArrays(self): return 0
        class Grid:
            def __init__(self, values): self.array = Array(values)
            def IsA(self, name): return name == 'vtkRectilinearGrid'
            def GetClassName(self): return 'vtkRectilinearGrid'
            def GetNumberOfPoints(self): return 8
            def GetNumberOfCells(self): return 1
            def GetExtent(self): return [0,1,0,1,0,1]
            def GetDimensions(self): return [2,2,2]
            def GetXCoordinates(self): return self.array
            GetYCoordinates = GetZCoordinates = GetXCoordinates
            def GetPointData(self): return Empty()
            GetCellData = GetPointData
        clean = snapshot(Grid([0,1]))
        self.assertEqual(clean, snapshot(Grid([0,1,float('nan'),99])))
        self.assertNotEqual(clean, snapshot(Grid([0,2])))
        with self.assertRaises(SchemaxisError): snapshot(Grid([0]))
        with self.assertRaises(SchemaxisError): snapshot(Grid([0,float('nan')]))
