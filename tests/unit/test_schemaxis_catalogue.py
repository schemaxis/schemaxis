# Copyright (C) 2026 David L F Gaden
"""Catalogue contracts must not confuse metadata generation with native support."""
import copy
import json
from pathlib import Path
import unittest
from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.paraview.catalogue import coverage, generated_declarations
from schemaxis.adaptors.paraview.catalogue_import import compile_catalogue
from schemaxis.bindings import validate_options
from schemaxis.data_contracts import assess, paraview_traits
from schemaxis.schema import export_schema


class CatalogueTests(unittest.TestCase):
    def test_string_array_fidelity_includes_component_shape(self):
        from schemaxis.adaptors.paraview.data import array_record
        class Strings:
            def __init__(self, components): self.components=components
            def GetDataType(self): return 13
            def GetNumberOfValues(self): return 2
            def GetNumberOfTuples(self): return 2//self.components
            def GetNumberOfComponents(self): return self.components
            def GetValue(self, i): return ['one','two'][i]
        self.assertNotEqual(array_record(Strings(1)),array_record(Strings(2)))

    def test_nested_choices_validate_branch_properties(self):
        clip = generated_declarations()['pvClip']
        validate_options(clip, {'ClipType':{'type':'Plane','options':{'Normal':[0,0,1]}}}, 'clip')
        for value in [{'type':'NoSuchShape'}, {'type':'Plane','options':{'Radius':1}},
                      {'type':'Plane','options':{'Normal':[1,2]}}, {'type':'Sphere','options':{'Radius':'large'}}]:
            with self.subTest(value=value), self.assertRaises(SchemaxisError):
                validate_options(clip, {'ClipType':value}, 'clip')

    def test_native_scalar_ranges_and_vector_shapes(self):
        sphere = generated_declarations()['pvSphere']
        for value in [{'ThetaResolution':2}, {'Center':[0,0]}, {'Radius':-1}, {'Radius':True}]:
            with self.subTest(value=value), self.assertRaises(SchemaxisError):
                validate_options(sphere,value,'sphere')

    def test_file_arguments_are_explicit_and_required(self):
        reader=generated_declarations()['pvCSVReader']
        for value in [{}, {'FileName':[]}, {'FileName':['']}]:
            with self.subTest(value=value), self.assertRaises(SchemaxisError):
                validate_options(reader,value,'reader')
        self.assertTrue(reader['options']['FileName']['constructor'])

    def test_metadata_is_not_qualification(self):
        data=coverage()
        self.assertGreater(data['counts']['declared'],400)
        self.assertTrue(all(v['qualification']=='not-run' for v in data['inventory'].values()))
        for key,item in data['inventory'].items():
            if key == 'writers/XMLPVAnimationWriter' or 'Programmable' in key:
                self.assertEqual(item['status'],'unsupported')
                self.assertIn('reason',item)
        writers=[d for d in generated_declarations().values() if d.get('role')=='writer']
        self.assertEqual(len(writers),44)
        self.assertTrue(all('FileName' not in d['options'] for d in writers))

    def test_defensive_copies(self):
        first=generated_declarations(); first['pvSphere']['options'].clear()
        self.assertIn('Radius',generated_declarations()['pvSphere']['options'])

    def test_optional_native_inputs_and_output_port_count(self):
        statistics=generated_declarations()['pvDescriptiveStatistics']
        self.assertFalse(statistics['inputs']['ModelInput']['required'])
        self.assertTrue(statistics['inputs']['Input']['required'])
        self.assertEqual(statistics['coverage']['outputPorts'],2)

    def test_zero_length_scalar_properties_use_declared_shape_evidence(self):
        declarations=generated_declarations()
        selector=declarations['pvCellGridProbe']['options']['CellGridAttribute']
        # A zero-element property pushes no message in ParaView 5.13.3, so it is a gap, not a command.
        self.assertNotIn('commands',declarations['pvForceStaticMesh'])
        self.assertIn('ForceCacheComputation',declarations['pvForceStaticMesh']['coverage']['gaps'])
        self.assertNotIn('ForceCacheComputation',declarations['pvForceStaticMesh']['options'])
        self.assertEqual(selector['value']['type'],'string')
        self.assertEqual(selector['initialiseElements'],1)

    def test_control_points_require_complete_native_tuples(self):
        declarations=generated_declarations()
        for operation,option,size in [('pvResourcePVLookupTable','RGBPoints',4),
                                      ('pvResourceTransferFunction2D','Boxes',8)]:
            with self.subTest(operation=operation),self.assertRaises(SchemaxisError) as caught:
                validate_options(declarations[operation],{option:[0]*(size-1)},operation)
            self.assertEqual(caught.exception.fault.code,'INVALID_LENGTH')
            validate_options(declarations[operation],{option:[0]*size},operation)

    def test_schema_exposes_qualification_and_identity(self):
        schema=export_schema(operation='pvSphere')
        self.assertEqual(schema['x-schemaxis-coverage']['qualification'],'not-run')
        self.assertIn('x-schemaxis-nativeIdentity',schema)

    def test_unknown_traits_are_not_support(self):
        result=assess({'indexing':['random-access']},{'indexing':'unknown'})
        self.assertEqual(result['compatibility'],'unknown')
        self.assertEqual(result['performance']['rating'],'unknown')
        self.assertEqual(assess({'indexing':['random-access']},{'indexing':'sequential'})['compatibility'],'unsupported')

    def test_cost_evidence_is_conditional(self):
        cost={'rating':'slow','basis':'linear traversal to find index','conditions':{'indexing':['sequential']}}
        self.assertEqual(assess({}, {'indexing':'sequential'},cost)['performance']['rating'],'slow')
        self.assertEqual(assess({}, {'indexing':'random-access'},cost)['performance']['rating'],'unknown')
        with self.assertRaises(SchemaxisError): assess({}, {}, {'rating':'fast'})

    def test_semantic_traits_do_not_invent_storage_layout(self):
        image=paraview_traits('vtkImageData')
        self.assertEqual(image['coordinates'],'implicit')
        self.assertEqual(image['contiguity'],'unknown')
        self.assertEqual(paraview_traits('vtkTable')['indexing'],'row-column')
        self.assertEqual(paraview_traits('unrecognised')['family'],'unknown')


if __name__ == '__main__': unittest.main()


class ExtensionTests(unittest.TestCase):
    def test_extension_cannot_override_a_standard_binding(self):
        import tempfile
        from unittest.mock import patch
        from schemaxis.adaptors.paraview.catalogue import _package
        base = copy.deepcopy(_package())
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'paraview_extensions').mkdir()
            base['declarations']={'pvSphere':base['declarations']['pvSphere']}
            (root/'paraview_extensions'/'duplicate.json').write_text(json.dumps(base))
            with patch('schemaxis.adaptors.paraview.catalogue.files',return_value=root):
                with self.assertRaises(SchemaxisError) as caught: generated_declarations()
            self.assertEqual(caught.exception.fault.code,'DUPLICATE_FILTER')

    def test_modified_native_dependency_fails_before_loading(self):
        from schemaxis.adaptors.paraview.native import ParaViewBackend
        backend=ParaViewBackend.__new__(ParaViewBackend)
        backend.loaded_dependencies=set()
        declaration={'nativeDependencies':[{'kind':'xml','xml':'changed','sha256':'0'*64}]}
        with self.assertRaises(SchemaxisError) as caught:
            backend.create('test',declaration,{}, {})
        self.assertEqual(caught.exception.fault.code,'DEPENDENCY_MISMATCH')
