"""Automatic writer readback must inspect fields that readers disable by default."""
import hashlib
import tempfile
import sys
import types
import unittest
import weakref
from pathlib import Path
from unittest import mock

from schemaxis.adaptors.paraview import writers
from schemaxis.core.faults import SchemaxisError


class Array:
    def __init__(self, name, value): self.name, self.value = name, value
    def GetName(self): return self.name
    def GetNumberOfComponents(self): return 1
    def GetNumberOfTuples(self): return 1
    def GetDataType(self): return 11
    def GetDataTypeAsString(self): return 'double'
    def GetTuple(self, index): return (self.value,)
    def GetComponent(self, index, component): return self.value


class Fields:
    def __init__(self, values=()): self.arrays = [Array(*item) for item in values]
    def GetNumberOfArrays(self): return len(self.arrays)
    def GetArrayName(self, index): return self.arrays[index].name
    def GetAbstractArray(self, key):
        if isinstance(key, int): return self.arrays[key]
        return next((array for array in self.arrays if array.name == key), None)


class Data:
    def __init__(self, point=(), cell=()): self.point, self.cell = Fields(point), Fields(cell)
    def IsA(self, name): return name in ('vtkDataSet', 'vtkUnstructuredGrid')
    def GetFieldData(self): return Fields()
    def GetPointData(self): return self.point
    def GetCellData(self): return self.cell
    def GetNumberOfPoints(self): return 1
    def GetNumberOfCells(self): return 1
    def GetPoint(self, index): return (0., 0., 0.)
    def GetCell(self, index): return self
    def GetCellType(self): return 1
    def GetPointId(self, index): return 0


class Window:
    def __init__(self): self.observers = {}
    def AddObserver(self, event, callback):
        key = len(self.observers) + 1; self.observers[key] = callback; return key
    def RemoveObserver(self, key): self.observers.pop(key)
    def error(self):
        for callback in list(self.observers.values()): callback()


class Selection:
    def __init__(self, owner, available, retained=True):
        self.owner, self.available, self.selected, self.retained = owner, available, [], retained
    @property
    def Available(self):
        if not self.owner.information_updates: raise RuntimeError('metadata has not been refreshed')
        return self.available
    def SetData(self, values):
        if self.retained: self.selected = list(values)
        if self.owner.assignment_error: self.owner.window.error()
    def GetData(self): return list(self.selected)


class Reader:
    def __init__(self, aliases=False, available=True, retained=True, selectors=True,
                 metadata_error=False, assignment_error=False):
        self.information_updates, self.window = 0, Window()
        self.metadata_error, self.assignment_error = metadata_error, assignment_error
        self.point_key, self.cell_key = (('PointArrays', 'CellArrays') if aliases
                                         else ('PointArrayStatus', 'CellArrayStatus'))
        self.properties = {'Bases': Selection(self, ['a-subset-that-must-stay-disabled'])}
        if selectors:
            self.properties.update({self.point_key: Selection(self, ['RTData'] if available else [], retained),
                                    self.cell_key: Selection(self, ['pressure'], retained)})
    def UpdatePipelineInformation(self):
        self.information_updates += 1
        if self.metadata_error: self.window.error()
    def ListProperties(self): return list(self.properties)
    def GetProperty(self, name): return self.properties[name]
    def fields(self, value):
        point = self.properties[self.point_key].GetData() if self.point_key in self.properties else ['RTData']
        cell = self.properties[self.cell_key].GetData() if self.cell_key in self.properties else ['pressure']
        return Data([(name, value) for name in point], [(name, 2.) for name in cell])


class Writer:
    def __init__(self, filename, finalize=False): self.filename, self.finalize = filename, finalize
    def __del__(self):
        if self.finalize and Path(self.filename).parent.is_dir():
            Path(self.filename).write_bytes(b'finalized writer fixture')
    def GetXMLGroup(self): return 'writers'
    def GetXMLName(self): return 'CGNSWriter'
    def ListProperties(self): return []
    def GetClientSideObject(self): return None
    def GetProperty(self, key):
        return types.SimpleNamespace(SMProperty=types.SimpleNamespace(FindDomain=lambda name: None))


class Backend:
    def __init__(self, reader, value=1., finalize_writer=False, finalize_reader=False):
        self.reader, self.value, self.records, self.deleted = reader, value, {}, []
        self.finalize_writer, self.finalize_reader = finalize_writer, finalize_reader
        self.pv = types.SimpleNamespace(CGNSWriter=lambda Input, FileName: self.writer(FileName),
            OpenDataFile=self.open_file, Delete=self.delete_native)
    def writer(self, filename):
        writer = Writer(filename, self.finalize_writer)
        self.writer_ref = weakref.ref(writer)
        return writer
    def open_file(self, filename):
        self.filename = Path(filename)
        self.reader_opened_after_writer_release = self.writer_ref() is None
        return self.reader
    def delete_native(self, proxy):
        self.deleted.append(id(proxy))
        if proxy is self.reader and self.finalize_reader:
            self.filename.write_bytes(self.filename.read_bytes()+b' finalized reader metadata')
    def fetch(self, proxy):
        return self.reader.fields(self.value) if proxy is self.reader else Data([('RTData', 1.)], [('pressure', 2.)])
    def load_dependencies(self, identity, declaration): pass
    def update(self, proxy, time):
        if isinstance(proxy, Writer): Path(proxy.filename).write_bytes(b'fixed writer fixture')
    def create(self, identity, declaration, inputs, options): return self.reader
    def configure(self, proxy, declaration, options): pass
    def delete(self, proxy): self.delete_native(proxy)


class AutomaticReadbackTests(unittest.TestCase):
    def publish(self, reader=None, *, value=1., authored=False, finalize_writer=False, finalize_reader=False):
        reader = reader or Reader()
        backend = Backend(reader, value, finalize_writer, finalize_reader)
        declaration = {'native': 'CGNSWriter', 'nativeIdentity': 'writers/CGNSWriter',
                       'options': {}, 'inputs': {}}
        settings = {'id': 'export', 'writer': 'pvWriteCGNSWriter', 'extension': 'cgns',
                    'options': {}, 'comparison': 'semantic', 'acceptLosses': writers.LOSSES['semantic'],
                    'tolerance': 0, 'readback': None}
        declarations = {}
        if authored:
            settings['readback'] = {'operation': 'reader', 'options': {}}
            declarations['reader'] = {'options': {'FileNames': {'constructor': True,
                'nativeDomains': ['vtkSMFileListDomain'],
                'value': {'type': 'array', 'items': {'type': 'string'}}}}}
        with tempfile.TemporaryDirectory() as temporary:
            module = types.ModuleType('vtkmodules.vtkCommonCore')
            module.vtkOutputWindow = types.SimpleNamespace(GetInstance=lambda: reader.window)
            with mock.patch.dict(sys.modules, {'vtkmodules.vtkCommonCore': module}), mock.patch.object(
                    writers, 'checked_update', new=lambda owner, proxy, time, location: owner.update(proxy, time)):
                result = writers.publish(backend, object(), declaration, settings,
                    Path(temporary)/'export', 0, declarations)
                backend.final_file_hash = hashlib.sha256(Path(result['file']).read_bytes()).hexdigest()
        return result, backend

    def test_automatic_readback_preserves_disabled_point_and_cell_fields(self):
        reader = Reader()
        result, backend = self.publish(reader)
        self.assertEqual(result['verification']['associations'],
            {'point': {'fields': ['RTData'], 'records': 1}, 'cell': {'fields': ['pressure'], 'records': 1}})
        self.assertEqual(result['verification']['tolerance'], 0)
        self.assertEqual(reader.information_updates, 1)
        self.assertEqual(reader.properties['Bases'].GetData(), [])
        self.assertIn(id(reader), backend.deleted)

    def test_writer_reference_is_released_before_readback_and_hashes_are_final(self):
        result, backend = self.publish(finalize_writer=True, finalize_reader=True)
        self.assertTrue(backend.reader_opened_after_writer_release)
        self.assertEqual(result['sha256'], backend.final_file_hash)
        self.assertEqual(result['files'][0]['sha256'], backend.final_file_hash)

    def test_python_property_aliases_have_the_same_roundtrip(self):
        result, _ = self.publish(Reader(aliases=True))
        self.assertTrue(result['verified'])
        self.assertEqual(result['verification']['associations']['point']['fields'], ['RTData'])

    def test_a_reader_without_array_selectors_keeps_its_loaded_fields(self):
        reader = Reader(selectors=False)
        result, _ = self.publish(reader)
        self.assertTrue(result['verified'])
        self.assertEqual(reader.properties['Bases'].GetData(), [])

    def test_native_errors_during_metadata_or_assignment_are_refused(self):
        for arguments in ({'metadata_error': True}, {'assignment_error': True}):
            with self.subTest(arguments=arguments):
                reader = Reader(**arguments)
                with self.assertRaises(SchemaxisError) as caught:
                    self.publish(reader)
                self.assertEqual(caught.exception.fault.code, 'NATIVE_PIPELINE_ERROR')
                self.assertEqual(reader.window.observers, {})

    def test_a_missing_written_array_still_fails_semantic_comparison(self):
        with self.assertRaises(SchemaxisError) as caught:
            self.publish(Reader(available=False))
        self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')
        self.assertEqual(caught.exception.fault.observed['field'], 'RTData')

    def test_a_changed_written_value_still_fails_at_zero_tolerance(self):
        with self.assertRaises(SchemaxisError) as caught:
            self.publish(value=1.000001)
        self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')

    def test_a_reader_that_ignores_array_selection_is_refused(self):
        with self.assertRaises(SchemaxisError) as caught:
            self.publish(Reader(retained=False))
        self.assertEqual(caught.exception.fault.code, 'NATIVE_VALUE_MISMATCH')

    def test_authored_readback_defaults_do_not_get_automatic_selection(self):
        reader = Reader()
        with self.assertRaises(SchemaxisError) as caught:
            self.publish(reader, authored=True)
        self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')
        self.assertEqual(reader.properties[reader.point_key].GetData(), [])
        self.assertEqual(reader.information_updates, 0)


if __name__ == '__main__': unittest.main()
