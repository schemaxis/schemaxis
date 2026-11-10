"""Closed capture grammar and worker ordering before any planner/native parser."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptors.paraview import captured_xml
from schemaxis.core.faults import SchemaxisError
from schemaxis.execution_inputs import CapturedInput, InputBindings, bindings_record
from schemaxis.mcp_admission import FileAdmission
from schemaxis.storage import encoded

XML = b'''<?xml version="1.0" encoding="UTF-8"?>
<VTKFile type="RectilinearGrid" version="0.1" byte_order="LittleEndian"><RectilinearGrid WholeExtent="0 1 0 1 0 1"><Piece Extent="0 1 0 1 0 1"><Coordinates><DataArray type="Float64" format="ascii">0 1</DataArray><DataArray type="Float64" format="ascii">0 1</DataArray><DataArray type="Float64" format="ascii">0 1</DataArray></Coordinates></Piece></RectilinearGrid></VTKFile>'''


class CapturedXmlTests(unittest.TestCase):
    def check(self, raw, *, suffix='.vtr', vtk_type='RectilinearGrid'):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/('capture'+suffix)
            path.write_bytes(raw)
            original_open = os.open
            with patch.object(captured_xml.os, 'open', wraps=original_open) as opened:
                try:
                    return captured_xml.validate_leaf(path, vtk_type=vtk_type)
                finally:
                    self.assertEqual([args.args[0] for args in opened.call_args_list], [path])

    def denied(self, raw, **kwargs):
        with self.assertRaises(SchemaxisError) as error:
            self.check(raw, **kwargs)
        self.assertEqual(error.exception.fault.code, 'INPUT_CONTENT_UNSUPPORTED')

    def test_numeric_self_contained_leaf_and_exact_type(self):
        result = self.check(XML)
        self.assertEqual((result['format'], result['numericValues']), ('RectilinearGrid', 6))
        self.denied(XML.replace(b'type="RectilinearGrid"', b'type="vtkMultiBlockDataSet"'))

    def test_external_entities_references_binary_and_unrecognised_elements_never_open_targets(self):
        for raw in (
            b'<!DOCTYPE VTKFile [<!ENTITY x SYSTEM "file:///outside/secret">]>'+XML,
            b'<?xml-stylesheet href="file:///outside/secret"?>'+XML,
            XML.replace(b'<Piece Extent=', b'<Piece Source="/outside/secret" Extent='),
            XML.replace(b'<Coordinates>', b'<Coordinates><DataSet file="/outside/secret"/>'),
            XML.replace(b'format="ascii"', b'format="appended"'),
            XML.replace(b'format="ascii"', b'format="binary"'),
            XML.replace(b'</VTKFile>', b'<AppendedData encoding="raw">_data</AppendedData></VTKFile>'),
            XML.replace(b'0 1</DataArray>', b'NaN 1</DataArray>'),
            XML.replace(b'0 1</DataArray>', b'1e999 1</DataArray>'),
            XML.replace(b'0 1</DataArray>', b'/outside/secret</DataArray>'),
        ):
            with self.subTest(raw=raw[:80]):
                self.denied(raw)

    def test_element_depth_and_value_work_bounds_are_enforced(self):
        for name, limit in (('MAX_ELEMENTS', 3), ('MAX_DEPTH', 2), ('MAX_VALUES', 3)):
            with self.subTest(name=name), patch.object(captured_xml, name, limit):
                self.denied(XML)

    def test_structural_dimensions_rows_and_array_agreement_are_bounded(self):
        for raw in (
            XML.replace(b'0 1 0 1 0 1', b'0 99999999999999999 0 1 0 1'),
            XML.replace(b'0 1 0 1 0 1', b'0 4095 0 4095 0 4095'),
            XML.replace(b'0 1</DataArray>', b'0 1 2</DataArray>'),
            XML.replace(b'format="ascii"', b'format="ascii" NumberOfTuples="3"'),
            XML.replace(b'<Coordinates>', b'<Coordinates><DataArray type="Float64" format="ascii">0 1</DataArray>'),
            XML.replace(b'type="Float64"', b'type="UInt8"').replace(b'0 1</DataArray>', b'0 256</DataArray>'),
        ):
            with self.subTest(raw=raw[:100]):
                self.denied(raw)
        table = b'<VTKFile type="Table"><Table><Piece NumberOfRows="100000000000"><RowData/></Piece></Table></VTKFile>'
        self.denied(table, suffix='.vtt', vtk_type='Table')

    def candidate_admission(self):
        # A small synthetic slot bound for byte-ordering and corruption tests.
        policies = copy.deepcopy(FileAdmission().policies)
        policy = policies['schemaxis/1']
        if 'pvXMLRectilinearGridReader' not in policy['operations']:
            policy['operations'].append('pvXMLRectilinearGridReader')
        policy['fileSlots'] = [slot for slot in policy['fileSlots']
            if slot.get('when') != {'/nodes/*/filter': 'pvXMLRectilinearGridReader'}]
        policy['fileSlots'].append({'pointer': '/nodes/*/options/FileName/*',
            'suffixes': ['.vtr'], 'maxBytes': 1024,
            'when': {'/nodes/*/filter': 'pvXMLRectilinearGridReader'},
            'contentPolicy': 'hook',
            'contentHook': 'schemaxis.adaptors.paraview.captured_xml:validate_leaf',
            'contentOptions': {'vtk_type': 'RectilinearGrid'}})
        declared = {k: v for k, v in policy.items() if k != 'contractDigest'}
        policy['contractDigest'] = 'sha256:'+hashlib.sha256(json.dumps(declared, sort_keys=True,
            separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        return FileAdmission(policies)

    def test_every_contained_phase_refuses_hostile_bytes_before_any_planner_hook(self):
        from schemaxis import container_worker
        from schemaxis.capabilities import digest
        admission = self.candidate_admission()
        original_read = Path.read_text
        for action, phase, tampered in (('plan', 'capture', False), ('plan', 'stale-check', False), ('run', None, False), ('verify', None, False), ('run', None, True)):
            with self.subTest(action=action, phase=phase), tempfile.TemporaryDirectory() as temporary:
                volume = Path(temporary).resolve()
                source = volume/'input.vtr'
                source.write_bytes(XML.replace(b'<Piece Extent=', b'<Piece Source="/outside/secret" Extent='))
                source.chmod(0o444)
                info = source.stat()
                capture = CapturedInput('input', source, 'sha256:'+hashlib.sha256(source.read_bytes()).hexdigest(),
                                        info.st_size, info.st_dev, info.st_ino)
                inputs = InputBindings('task', (capture,), (('/nodes/0/options/FileName/0', 'input'),))
                document = {'version': 'schemaxis/1', 'nodes': [{'id': 'data',
                    'filter': 'pvXMLRectilinearGridReader', 'options': {'FileName': [str(source)]}}],
                    'scenes': [{'id': 'view', 'geometry': ['data']}]}
                header = {'action': action, 'planningPhase': phase, 'document': document,
                    'documentDigest': digest(document), 'plan': {}, 'planDigest': hashlib.sha256(encoded({})).hexdigest(),
                    'volume': str(volume), 'directory': str(volume/'run'),
                    'limits': {'disk_bytes': 65536, 'inodes': 64}, 'inputs': bindings_record(inputs),
                    'capturedContentPolicy': admission.captured_content_policy(document, inputs)}
                if tampered:
                    header['capturedContentPolicy']['contracts'] = []
                def read(path, *args, **kwargs):
                    if str(path) == '/proc/self/mountinfo':
                        return '1 0 0:0 / '+str(source)+' ro - tmpfs tmpfs ro\n'
                    return original_read(path, *args, **kwargs)
                with patch('schemaxis.mcp_admission.FileAdmission', return_value=admission), \
                     patch.object(container_worker, 'enforced_limits', return_value={}), \
                     patch.object(Path, 'cwd', return_value=volume), patch.object(Path, 'read_text', read), \
                     patch.dict(os.environ, {'HOME': str(volume/'.home'), 'TMPDIR': str(volume/'.tmp'),
                                              'XDG_CACHE_HOME': str(volume/'.cache')}), \
                     patch('schemaxis.adaptors.registry.plan') as planner, \
                     self.assertRaises(SchemaxisError) as error:
                    container_worker.perform(header, b'')
                self.assertEqual(error.exception.fault.code, 'MCP_POLICY_DENIED' if tampered else 'INPUT_CONTENT_UNSUPPORTED')
                planner.assert_not_called()

    def test_missing_or_foreign_content_contract_refuses_before_import(self):
        admission = self.candidate_admission()
        document = {'version': 'schemaxis/1', 'nodes': [{'id': 'data',
            'filter': 'pvXMLRectilinearGridReader', 'options': {'FileName': ['/capture/input.vtr']}}],
            'scenes': [{'id': 'view', 'geometry': ['data']}]}
        capture = CapturedInput('input', Path('/capture/input.vtr'), 'sha256:'+'a'*64, 32, 1, 2)
        inputs = InputBindings('task', (capture,), (('/nodes/0/options/FileName/0', 'input'),))
        for change in ({'contentPolicy': None}, {'contentHook': 'foreign.module:execute'}):
            policies = copy.deepcopy(admission.policies)
            policy = policies['schemaxis/1']
            policy['fileSlots'][-1].update(change)
            declared = {key: value for key, value in policy.items() if key != 'contractDigest'}
            policy['contractDigest'] = 'sha256:'+hashlib.sha256(json.dumps(declared, sort_keys=True,
                separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
            with self.subTest(change=change), \
                 patch('schemaxis.adaptors.registry.binding', side_effect=AssertionError('foreign hook imported')), \
                 self.assertRaises(SchemaxisError) as error:
                FileAdmission(policies).validate_captured_content(document, inputs)
            self.assertEqual(error.exception.fault.code, 'MCP_POLICY_DENIED')

    def test_managed_readback_context_never_grants_reader_node_usage(self):
        admission = FileAdmission()
        policy = {'catalogueGenerated': True, 'operations': ['managedReader'],
            'operationSelectors': ['/nodes/*/filter', '/scenes/*/exports/*/readback/operation'],
            'operationContexts': {'managedReader': ['/scenes/*/exports/*/readback/operation']},
            'fileSlots': []}
        self.assertEqual(admission._slots({'scenes': [{'exports': [{'readback': {
            'operation': 'managedReader'}}]}]}, policy), {})
        with self.assertRaises(SchemaxisError) as error:
            admission._slots({'nodes': [{'filter': 'managedReader'}]}, policy)
        self.assertEqual(error.exception.fault.code, 'MCP_POLICY_DENIED')

    def test_pure_admission_never_invokes_content_hooks(self):
        admission = self.candidate_admission()
        document = {'version': 'schemaxis/1', 'nodes': [{'id': 'data',
            'filter': 'pvXMLRectilinearGridReader', 'options': {'FileName': ['input']}}],
            'scenes': [{'id': 'view', 'geometry': ['data']}]}
        with patch('schemaxis.adaptors.registry.binding', side_effect=AssertionError('content hook imported')):
            self.assertEqual(admission.input_slots(document)[0].pointer, '/nodes/0/options/FileName/0')


if __name__ == '__main__':
    unittest.main()
