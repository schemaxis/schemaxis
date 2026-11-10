# Copyright (C) 2026 David L F Gaden
"""Native readback and pre-write checks observed in bounded ParaView 5.13.3 probes (2026-10-12).

Native objects are replaced by small stand-ins; no ParaView is imported.
"""
import unittest

from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.paraview.native import _configure_binding, retained_value
import sys
import types
from unittest import mock
from schemaxis.adaptors.paraview.writers import check_ioss_global_ids, input_time_steps
from schemaxis.adaptors.paraview.publication import observed_slice_plane


class SlicePlaneMetadataTests(unittest.TestCase):
    def test_curated_slice_pins_a_single_zero_offset_before_publication(self):
        from schemaxis.adaptors.paraview.filters import catalogue
        self.assertEqual(catalogue()['slice']['fixed']['SliceOffsetValues'], [0])

    def proxy(self, *, native='Cut', implicit='Plane', crinkle=False, offsets=None):
        return types.SimpleNamespace(
            SMProxy=types.SimpleNamespace(GetXMLName=lambda: native), Crinkleslice=crinkle,
            SliceType=types.SimpleNamespace(SMProxy=types.SimpleNamespace(GetXMLName=lambda: implicit),
                                           Origin=[2,3,4], Normal=[1,0,0]),
            ListProperties=lambda: ['SliceOffsetValues'] if offsets is not None else [],
            SliceOffsetValues=offsets)

    def test_single_native_plane_records_observed_coordinates(self):
        for offsets in (None, [0.0]):
            self.assertEqual(observed_slice_plane(self.proxy(offsets=offsets)),
                             {'origin': [2,3,4], 'normal': [1,0,0]})

    def test_ambiguous_or_nonplanar_cuts_do_not_claim_a_texture_plane(self):
        for settings in ({'native': 'SphereSource'}, {'implicit': 'Sphere'}, {'crinkle': True},
                         {'offsets': []}, {'offsets': [0,1]}, {'offsets': [2]}):
            with self.subTest(settings=settings):
                self.assertIsNone(observed_slice_plane(self.proxy(**settings)))


class ComponentProxy:
    """An EnumerationProperty whose domain has component names, as once the upstream array exists."""

    def __init__(self, names):
        object.__setattr__(self, 'stored', None)
        object.__setattr__(self, 'names', names)

    def __setattr__(self, name, value):
        object.__setattr__(self, 'stored', value)

    def ListProperties(self): return ['Component']

    def __getattr__(self, name):
        proxy = self

        class Wrapper:
            @staticmethod
            def GetData(): return proxy.names[proxy.stored]
        return Wrapper()

    def GetProperty(self, name):
        proxy = self

        class Property:
            class SMProperty:
                @staticmethod
                def GetNumberOfElements(): return 1

                @staticmethod
                def GetElement(index): return proxy.stored

                @staticmethod
                def GetCommand(): return 'SetComponent'
        return Property()


class IntegerReadbackTests(unittest.TestCase):
    binding = {'path': ['Component'], 'value': {'type': 'integer'}, 'nativeDomains': ['vtkSMNumberOfComponentsDomain']}

    def test_component_name_readback_compares_the_stored_integer(self):
        # Probe: Histogram.Component = 1 reads back 'Y' once the upstream vector array exists.
        _configure_binding(ComponentProxy(['X', 'Y', 'Z']), self.binding, 1, 1, 'h.Component')

    def test_a_different_stored_integer_still_fails(self):
        proxy = ComponentProxy(['X', 'Y', 'Z'])
        object.__setattr__(proxy, 'GetProperty', lambda name: type('P', (), {'SMProperty': type('S', (), {
            'GetNumberOfElements': staticmethod(lambda: 1), 'GetElement': staticmethod(lambda i: 2),
            'GetCommand': staticmethod(lambda: 'SetComponent')})})())
        with self.assertRaises(SchemaxisError) as caught:
            _configure_binding(proxy, self.binding, 1, 1, 'h.Component')
        self.assertEqual(caught.exception.fault.code, 'NATIVE_VALUE_MISMATCH')

    def test_backend_reconfiguration_uses_the_same_readback(self):
        # ParaViewBackend.configure re-reads every changed option through retained_value.
        proxy = ComponentProxy(['X', 'Y', 'Z'])
        object.__setattr__(proxy, 'stored', 2)
        self.assertEqual(retained_value(proxy, self.binding, 2), 2)

    def test_text_bindings_keep_comparing_text(self):
        binding = {'path': ['Component'], 'value': {'type': 'string'}, 'nativeDomains': []}
        with self.assertRaises(SchemaxisError):
            _configure_binding(ComponentProxy(['X', 'Y']), binding, 1, 1, 'h.Component')


class Ids:
    def __init__(self, low, high): self.low, self.high = low, high
    def GetNumberOfTuples(self): return 4
    def GetRange(self, component): return (self.low, self.high)


class Grid:
    def __init__(self, ids): self.ids = ids
    def IsA(self, name): return name == 'vtkDataSet'
    def GetNumberOfPoints(self): return 4
    def GetPointData(self):
        grid = self

        class PointData:
            @staticmethod
            def GetGlobalIds(): return grid.ids
        return PointData()


class IossGlobalIdTests(unittest.TestCase):
    def fault(self, data, steps):
        with self.assertRaises(SchemaxisError) as caught:
            check_ioss_global_ids(data, steps, 'export')
        return caught.exception.fault

    def test_time_dependent_input_without_positive_ids_is_refused(self):
        self.assertEqual(self.fault(Grid(None), [0.0, 0.5]).code, 'UNSUPPORTED_INPUT')
        # pvGlobalPointAndCellIds numbers from 0, which the writer also aborts on.
        self.assertEqual(self.fault(Grid(Ids(0, 3)), [0.0, 0.5]).observed['globalIds'], [0, 3])

    def test_offset_global_ids_admits_zero_based_ids(self):
        # Probe: OffsetGlobalIds = 1 let the writer export Tetrahedralize(TimeSource) for one step.
        check_ioss_global_ids(Grid(Ids(0, 3)), [0.0, 0.5], 'export', offset=True)
        self.assertEqual(self.fault(Grid(None), [0.0, 0.5]).observed['offsetGlobalIds'], False)

    def test_static_input_and_positive_ids_pass(self):
        check_ioss_global_ids(Grid(None), [0.0], 'export')
        check_ioss_global_ids(Grid(None), None, 'export')
        check_ioss_global_ids(Grid(Ids(1, 4)), [0.0, 0.5], 'export')


class InputTimeStepTests(unittest.TestCase):
    def test_reader_values_and_filter_pipeline_information(self):
        class Reader:
            TimestepValues = [0.0, 0.5]
            def ListProperties(self): return ['FileName', 'TimestepValues']
        self.assertEqual(input_time_steps(Reader()), [0.0, 0.5])

        class Information:
            def Has(self, key): return key == 'TIME_STEPS'
            def Get(self, key): return (0.0, 0.25, 0.5)

        class Filter:
            # Probe: a filter proxy has no TimestepValues property.
            def ListProperties(self): return ['Input']
            def UpdatePipelineInformation(self): pass
            def GetClientSideObject(self):
                return types.SimpleNamespace(GetOutputInformation=lambda port: Information())
        pipeline = types.SimpleNamespace(TIME_STEPS=lambda: 'TIME_STEPS')
        module = types.SimpleNamespace(vtkStreamingDemandDrivenPipeline=pipeline)
        with mock.patch.dict(sys.modules, {'vtkmodules': types.SimpleNamespace(),
                                           'vtkmodules.vtkCommonExecutionModel': module}):
            self.assertEqual(input_time_steps(Filter()), [0.0, 0.25, 0.5])


if __name__ == '__main__':
    unittest.main()
