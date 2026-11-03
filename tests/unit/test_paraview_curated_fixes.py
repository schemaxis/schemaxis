# Copyright (C) 2026 David L F Gaden
"""Pins for curated ParaView operations that must follow the bundled native contract."""
import json
from pathlib import Path
import types
import unittest
from schemaxis.adaptors.paraview.filters import catalogue
from schemaxis.adaptors.paraview.traits import paraview_traits
from schemaxis.bindings import validate_options
from schemaxis.core.faults import SchemaxisError
from schemaxis.data_contracts import assess


def rejected(test, name, options):
    with test.assertRaises(SchemaxisError) as caught:
        validate_options(catalogue()[name], options, 'node')
    return caught.exception.fault


class DeprecatedAliasTests(unittest.TestCase):
    def test_curated_operations_bind_current_native_names(self):
        declarations = catalogue()
        self.assertEqual(declarations['generateIds']['native'], 'PointAndCellIds')
        self.assertEqual(declarations['normals']['native'], 'SurfaceNormals')

    def test_replacement_keeps_option_paths_and_defaults(self):
        # GenerateIdScalars and PolyDataNormals inherit every property from these proxies.
        declarations = catalogue()
        for curated, generated in (('generateIds', 'pvPointAndCellIds'), ('normals', 'pvSurfaceNormals')):
            native = {item['path'][0] for item in declarations[generated]['options'].values()}
            used = {item['path'][0] for item in declarations[curated]['options'].values()}
            self.assertLessEqual(used, native, curated)
        defaults = {k: v['value'].get('default') for k, v in declarations['generateIds']['options'].items()}
        self.assertEqual(defaults, {'pointIds': True, 'cellIds': True, 'pointName': 'pointIds', 'cellName': 'cellIds'})
        self.assertEqual({declarations['generateIds']['options'][k]['path'][0] for k in ('pointName', 'cellName')},
                         {'PointIdsArrayName', 'CellIdsArrayName'})

    def test_curated_inputs_take_the_replacement_contract(self):
        generated = catalogue()['pvPointAndCellIds']['inputs']['Input']['contract']
        self.assertEqual(catalogue()['generateIds']['inputs']['input']['contract'], generated)


class CurvatureAndBoundsTests(unittest.TestCase):
    def test_curvature_type_is_the_native_enumeration(self):
        self.assertEqual(catalogue()['curvature']['options']['type']['value']['values'], ['Gaussian', 'Mean'])
        for value in ('Maximum', 'Minimum'):
            with self.subTest(value=value):
                rejected(self, 'curvature', {'type': value})
        validate_options(catalogue()['curvature'], {'type': 'Gaussian'}, 'node')

    def test_cone_and_cylinder_resolution_stops_at_the_vtk_clamp(self):
        for name in ('cone', 'cylinder'):
            with self.subTest(name=name):
                validate_options(catalogue()[name], {'resolution': 512}, 'node')
                self.assertEqual(rejected(self, name, {'resolution': 513}).code, 'INVALID_ARGUMENT')

    def test_studio_snippets_match_the_declared_limits(self):
        studio = json.loads((Path(__file__).parents[2] / 'src/schemaxis/adaptors/paraview/studio.json').read_text())
        snippets = {item['id']: item for item in studio['snippets']} if isinstance(studio.get('snippets'), list) \
            else studio['snippets']
        for name in ('cone', 'cylinder'):
            self.assertEqual(snippets[name]['fields']['resolution']['maximum'], 512)
        self.assertEqual(snippets['curvature']['fields']['type']['values'], ['Gaussian', 'Mean'])
        for name, key in (('warpScalar', 'fieldAssociation'), ('warpVector', 'vectorsAssociation')):
            self.assertEqual(snippets[name]['fields'][key]['values'], ['POINTS'])


class WarpAssociationTests(unittest.TestCase):
    def test_cell_arrays_are_rejected_at_planning_with_recovery(self):
        for name, option in (('warpScalar', 'field'), ('warpVector', 'vectors')):
            with self.subTest(name=name):
                fault = rejected(self, name, {option: ['CELLS', 'x']})
                self.assertEqual(fault.code, 'INVALID_ASSOCIATION')
                self.assertEqual(fault.location, 'node.' + option + '[0]')
                self.assertIn('cellToPoint', fault.recovery)
                validate_options(catalogue()[name], {option: ['POINTS', 'x']}, 'node')

    def test_planner_rejects_a_literal_cell_association(self):
        from schemaxis.pipeline import DefinitionGraph
        document = {'version': 'schemaxis/1', 'nodes': [
            {'id': 'source', 'filter': 'wavelet'},
            {'id': 'warp', 'filter': 'warpScalar', 'inputs': {'input': 'source'},
             'options': {'field': ['CELLS', 'RTData']}}]}
        with self.assertRaises(SchemaxisError) as caught:
            DefinitionGraph(document, catalogue())
        self.assertEqual(caught.exception.fault.code, 'INVALID_ASSOCIATION')
        self.assertEqual(caught.exception.fault.location, 'warp.field[0]')
        document['nodes'][1]['options']['field'][0] = 'POINTS'
        DefinitionGraph(document, catalogue())

    def test_malformed_values_are_left_to_type_validation(self):
        for value in ('CELLS', {}, [], 5):
            with self.subTest(value=value), self.assertRaises(SchemaxisError) as caught:
                validate_options(catalogue()['warpVector'], {'vectors': value}, 'node')
            self.assertNotEqual(caught.exception.fault.code, 'INVALID_ASSOCIATION')

    def test_stream_tracer_keeps_cell_vectors(self):
        validate_options(catalogue()['streamTracer'], {'vectors': ['CELLS', 'U']}, 'node')


class SliceHyperTreeGridTests(unittest.TestCase):
    def contract(self):
        return catalogue()['slice']['inputs']['input']['contract']

    def test_contract_excludes_hyper_tree_grids(self):
        contract = self.contract()
        self.assertEqual(contract['nativeTypes'], ['vtkDataSet'])
        self.assertIn('pvSlice', contract['recovery'])
        for data_class in ('vtkPolyData', 'vtkUnstructuredGrid', 'vtkImageData', 'vtkStructuredGrid', 'vtkRectilinearGrid'):
            with self.subTest(data_class=data_class):
                result = assess(contract['requirements'], paraview_traits(data_class))
                self.assertEqual(result['compatibility'], 'supported')
        for data_class in ('vtkHyperTreeGrid', 'vtkUniformHyperTreeGrid'):
            with self.subTest(data_class=data_class):
                result = assess(contract['requirements'], paraview_traits(data_class))
                self.assertEqual(result['compatibility'], 'unsupported')
        # Composite inputs are not judged by their container class.
        self.assertNotEqual(assess(contract['requirements'], paraview_traits('vtkMultiBlockDataSet'))['compatibility'],
                            'unsupported')

    def test_narrowing_must_stay_inside_the_native_contract(self):
        from copy import deepcopy
        from unittest.mock import patch
        from schemaxis.adaptors.paraview import catalogue as module
        declarations = {'x': {'id': 'x', 'native': 'Slice', 'inputs': {'input': {
            'native': 'Input', 'contract': {'nativeTypes': ['vtkDataSet', 'vtkTable']}}}}}
        with self.assertRaises(SchemaxisError) as caught:
            module.enrich_curated(deepcopy(declarations))
        self.assertEqual(caught.exception.fault.code, 'INVALID_DATA_CONTRACT')
        narrowed = deepcopy(declarations)
        narrowed['x']['inputs']['input']['contract'] = {'nativeTypes': ['vtkDataSet'], 'requirements': {'family': ['spatial']}}
        base = module._package()['declarations']['pvSlice']['inputs']['Input']['contract']
        merged = module.enrich_curated(narrowed)['x']['inputs']['input']['contract']
        self.assertEqual(merged['requirements'], {**base['requirements'], 'family': ['spatial']})

    def test_pv_slice_still_admits_hyper_tree_grids(self):
        self.assertIn('vtkHyperTreeGrid', catalogue()['pvSlice']['inputs']['Input']['contract']['nativeTypes'])
        self.assertEqual(catalogue()['pvSlice']['inputs']['Input']['contract']['requirements'], {})

    def test_backend_refuses_a_hyper_tree_grid_input(self):
        from schemaxis.adaptors.paraview.native import ParaViewBackend

        class Information:
            def __init__(self, name): self.name = name
            def GetDataClassName(self): return self.name

        class Source:
            def __init__(self, name): self.information = Information(name)
            def GetDataInformation(self): return self.information

        declaration = catalogue()['slice']
        backend = ParaViewBackend.__new__(ParaViewBackend)
        proxy = types.SimpleNamespace()
        backend.records = {id(proxy): {'node': 'cut', 'declaration': declaration, 'options': {},
                                       'inputs': {'input': Source('vtkHyperTreeGrid')}}}
        with self.assertRaises(SchemaxisError) as caught:
            backend.update(proxy, 0)
        fault = caught.exception.fault
        self.assertEqual(fault.code, 'INPUT_TRAIT_MISMATCH')
        self.assertEqual(fault.location, 'cut.input')
        self.assertEqual(fault.recovery, declaration['inputs']['input']['contract']['recovery'])
        self.assertEqual(fault.observed['dataClass'], 'vtkHyperTreeGrid')


if __name__ == '__main__':
    unittest.main()
