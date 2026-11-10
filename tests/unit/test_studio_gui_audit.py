# Copyright (C) 2026 David L. F. Gaden
"""Regressions for unfinished CFD authoring and deferred reader selection."""
import copy
import gzip
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from schemaxis.adaptors.paraview.studio import inspection_document, peek_input
from schemaxis.adaptors.paraview.reader_choices import resolve_selection
from schemaxis.adaptors.paraview.filters import FOAM, EXTRACT, validate_options
from schemaxis.adaptors.paraview.block_choices import resolve_blocks
from schemaxis.documents import resolve_document
from schemaxis.core.faults import SchemaxisError


class StudioGuiAuditTests(unittest.TestCase):
    def test_only_selected_dependencies_resolve_with_original_document_addresses(self):
        document = {'version': 'schemaxis/1', 'settings': {'input': 'source', 'bad': {'$document': '/missing'}},
                    'nodes': [{'id': 'unfinished', 'filter': 'slice', 'options': {'$document': '/missing'}},
                              {'id': 'source', 'filter': 'sphere', 'options': {'radius': 2}},
                              {'id': 'cut', 'filter': 'slice', 'inputs': {'input': {'$document': '/settings/input'}},
                               'options': {'origin': [0, 0, 0], 'normal': 'x+'}}],
                    'scenes': [{'id': {'$fill': 'scene'}}]}
        before = copy.deepcopy(document)
        result = inspection_document(document, 'cut')
        self.assertEqual([n['id'] for n in result['nodes']], ['source', 'cut'])
        self.assertEqual(result['nodes'][1]['inputs']['input'], 'source')
        self.assertEqual(result['scenes'], [])
        self.assertEqual(document, before)
        document['nodes'][2]['inputs']['input'] = 'missing'
        with self.assertRaises(SchemaxisError): inspection_document(document, 'cut')

    def test_deferred_names_validate_then_resolve_at_reader_domain(self):
        for value in ({'select': 'all'}, {'pattern': '^(U|p)$'}, ['U', 'p']):
            self.assertEqual(validate_options(FOAM, {'file': 'case.foam', 'cellArrays': value}, 'reader')['cellArrays'], value)
        self.assertEqual(resolve_selection({'select': 'all'}, ['U', 'p', 'nut'], 'arrays'), ['U', 'p', 'nut'])
        self.assertEqual(resolve_selection({'pattern': '^(U|p)$'}, ['U', 'p', 'nut'], 'arrays'), ['U', 'p'])
        for value in ({'pattern': '['}, {'pattern': '^missing$'}):
            with self.assertRaises(SchemaxisError): resolve_selection(value, ['U', 'p'], 'arrays')
        with self.assertRaises(SchemaxisError): validate_options(FOAM, {'file': 'a.foam', 'regions': {'select': 'ALL'}}, 'reader')
        with self.assertRaises(SchemaxisError): validate_options(FOAM, {'file': 'a.foam', 'regions': {'pattern': '['}}, 'reader')

    def test_entry_lists_mix_exact_names_and_patterns(self):
        mixed = ['internalMesh', {'pattern': '^patch/wheels_'}]
        self.assertEqual(validate_options(FOAM, {'file': 'case.foam', 'regions': mixed}, 'reader')['regions'], mixed)
        available = ['internalMesh', 'patch/wheels_FL', 'patch/body', 'patch/wheels_RR']
        self.assertEqual(resolve_selection(mixed, available, 'regions'), ['internalMesh', 'patch/wheels_FL', 'patch/wheels_RR'])
        self.assertEqual(resolve_selection([{'pattern': 'wheels'}, 'patch/wheels_FL', {'pattern': 'body'}], available, 'regions'),
                         ['patch/wheels_FL', 'patch/wheels_RR', 'patch/body'])
        self.assertEqual(resolve_selection(['absent'], available, 'regions'), ['absent'])
        with self.assertRaises(SchemaxisError) as raised: resolve_selection(['internalMesh', {'pattern': '^none$'}], available, 'regions')
        self.assertEqual((raised.exception.fault.code, raised.exception.fault.location), ('EMPTY_SELECTION', 'regions[1]'))
        with self.assertRaises(SchemaxisError): validate_options(FOAM, {'file': 'a.foam', 'regions': ['internalMesh', {'pattern': '['}]}, 'reader')
        with self.assertRaises(SchemaxisError): validate_options(FOAM, {'file': 'a.foam', 'regions': [{'select': 'all'}]}, 'reader')

    def test_block_selection_adds_patterns_and_removes_exclusions(self):
        blocks = [{'selector': '/Root/internalMesh', 'label': 'internalMesh'}] + [
            {'selector': '/Root/boundary/' + name, 'label': name} for name in (
                'WT_inlet', 'WT_floor', 'wheels_FL_Tyre', 'wheels_FL_movingPatch', 'body_upper', 'procBoundary0to2', 'underfloor_floor')]
        mixed = ['internalMesh', {'pattern': '^wheels_[FR][RL]_T'}, {'exclude': 'Mesh$'}]
        options = validate_options(EXTRACT, {'selectors': mixed}, 'extract')
        self.assertEqual(options['selectors'], mixed)
        self.assertEqual(resolve_blocks(['internalMesh', '/Root/boundary/WT_floor'], blocks, 'selectors'),
                         ['//internalMesh', '/Root/boundary/WT_floor'])
        self.assertEqual(resolve_blocks(mixed, blocks, 'selectors'), ['/Root/boundary/wheels_FL_Tyre'])
        self.assertEqual(resolve_blocks([{'exclude': '^(WT_|wheels_|procBoundary|internalMesh$|underfloor_floor$)'}], blocks, 'selectors'),
                         ['/Root/boundary/body_upper'])
        with self.assertRaises(SchemaxisError) as raised: resolve_blocks(['internalMesh', {'pattern': '^none$'}], blocks, 'selectors')
        self.assertEqual((raised.exception.fault.code, raised.exception.fault.location), ('EMPTY_SELECTION', 'selectors[1]'))
        with self.assertRaises(SchemaxisError): resolve_blocks([{'exclude': '.'}], blocks, 'selectors')
        with self.assertRaises(SchemaxisError): validate_options(EXTRACT, {'selectors': [{'pattern': '['}]}, 'extract')
        with self.assertRaises(SchemaxisError): validate_options(EXTRACT, {'selectors': [{'select': 'all'}]}, 'extract')

    def test_saved_files_open_into_the_workspace_and_save_as_asks_before_replacing(self):
        from schemaxis.console_session import AdaptorConsoleSession
        from schemaxis.studio_server import StudioApplication
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'case').mkdir()
            saved = root / 'case' / 'wing.json'
            saved.write_text('{"version": "schemaxis/1", "nodes": [], "scenes": []}')
            app = StudioApplication(AdaptorConsoleSession(root / 'workspace', 'paraview'))
            try:
                opened = app.documents({'action': 'open', 'file': str(saved)})
                self.assertEqual((opened['name'], opened['provider'], opened['file']), ('wing', 'paraview', str(saved)))
                again = app.documents({'action': 'open', 'file': str(saved)})
                self.assertEqual(again['id'], opened['id'])
                self.assertEqual(len([d for d in app.light_state()['documents'] if d['file'] == str(saved)]), 1)
                with self.assertRaises(SchemaxisError): app.documents({'action': 'open', 'file': str(root / 'absent.json')})
                (root / 'other.json').write_text('{"version": "not-a-version/9"}')
                count = len(app.light_state()['documents'])
                with self.assertRaises(SchemaxisError): app.documents({'action': 'open', 'file': str(root / 'other.json')})
                self.assertEqual(len(app.light_state()['documents']), count)
                target = root / 'case' / 'copy.json'; target.write_text('{}')
                request = {'action': 'write', 'document': opened['id'], 'revision': opened['revision'], 'filename': str(target)}
                with self.assertRaises(SchemaxisError) as raised: app.author(request)
                self.assertEqual(raised.exception.fault.code, 'OUTPUT_EXISTS')
                self.assertEqual(target.read_text(), '{}')
                self.assertEqual(app.author({**request, 'overwrite': True})['saved'], str(target))
                self.assertEqual(app.document(opened['id'])['file'], str(target))
                self.assertIn('schemaxis/1', target.read_text())
            finally:
                app.session.close() if hasattr(app.session, 'close') else None

    def test_header_preview_does_not_launch_native_or_read_mesh(self):
        with tempfile.TemporaryDirectory() as folder:
            case = Path(folder); (case / 'constant/polyMesh').mkdir(parents=True); (case / '1').mkdir()
            (case / 'case.foam').touch()
            (case / 'constant/polyMesh/boundary').write_text('FoamFile {class polyBoundaryMesh;}\n2\n(\ninlet {type patch; nFaces 4; startFace 0;}\nwall {nFaces 8;}\n)')
            (case / '1/U').write_text('FoamFile {class volVectorField; object U;}')
            with gzip.open(case / '1/p.gz', 'wt') as stream: stream.write('FoamFile {class volScalarField; object p;}')
            document = {'version': 'schemaxis/1', 'settings': {'path': str(case / 'case.foam'), 'bad': {'$document': '/missing'}},
                        'nodes': [{'id': 'case', 'filter': 'foam', 'options': {'file': {'$document': '/settings/path'}}},
                                  {'id': 'cut', 'filter': 'slice'}]}
            with patch('subprocess.Popen', side_effect=AssertionError('metadata must remain host-only')):
                result = peek_input(document, 'case')
            self.assertEqual(result['regions'], ['internalMesh', 'patch/inlet', 'patch/wall'])
            self.assertEqual(result['cellArrays'], ['U', 'p'])
            self.assertEqual(result['availableTimes'], [1])

    def test_unavailable_metadata_is_a_typed_preview_result(self):
        from schemaxis.studio_server import StudioApplication
        app = StudioApplication.__new__(StudioApplication)
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / 'empty.foam'; marker.touch()
            request = {'provider': 'paraview', 'node': 'case', 'input': {'version': 'schemaxis/1',
                       'nodes': [{'id': 'case', 'filter': 'foam', 'options': {'file': str(marker)}}]}}
            with patch('subprocess.Popen', side_effect=AssertionError('metadata must remain host-only')):
                result = app.peek_input_request(request)
            self.assertFalse(result['available'])
            self.assertEqual(result['code'], 'UNAVAILABLE_METADATA')
            self.assertIn('live data', result['scope'])

    def test_aabb_mixed_points_inflation_components_and_camera(self):
        root = {'dimensions': {'box': {'min': [0, -1, 0], 'max': [4, 1, 2]}, 'distance': 3},
                'point': {'$value': 'boundsPoint', 'args': {'bounds': {'$document': '/dimensions/box'}, 'x': 'max', 'y': 'mid', 'z': 'min'}},
                'vector': [{'$document': '/dimensions/distance'}, 0, {'$document': '/dimensions/box/max/2'}],
                'expanded': {'$value': 'boundsExtend', 'args': {'bounds': {'$document': '/dimensions/box'}, 'before': [.5, .5, .5], 'after': [2.5, .5, .5]}},
                'volume': {'$value': 'boundsFromExtents', 'args': {'extents': [0, 4, -1, 1, 0, 2]}}}
        resolved, _ = resolve_document(root)
        self.assertEqual(resolved['point'], [4, 0, 0]); self.assertEqual(resolved['vector'], [3, 0, 2])
        self.assertEqual(resolved['expanded'], {'min': [-2, -2, -1], 'max': [14, 2, 3]})
        self.assertEqual(resolved['volume'], root['dimensions']['box'])
