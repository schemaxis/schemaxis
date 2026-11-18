# Copyright (C) 2026 David L. F. Gaden.
"""Bounded serial qualification of the ordinary nodes produced by multi-mode."""
import json
from pathlib import Path
import tempfile
import unittest
from schemaxis.adaptors.paraview.job import run
from schemaxis.adaptors.paraview.mvp.runners import find_paraview
from schemaxis.identity_rename import rename_identity
from schemaxis.storage import digest


@unittest.skipUnless(find_paraview(), 'set SCHEMAXIS_PARAVIEW_ROOTS to a ParaView installation')
class ElementMultiMode(unittest.TestCase):
    def test_four_independent_named_extracts_and_grouped_selection(self):
        names = ['internalMesh', 'WT_wall_XP', 'WT_wall_XM', 'Inlet']
        sources = [{'id': '004_031_9d_case' if i == 0 else 'part' + str(i),
                    'filter': 'sphere', 'options': {'centre': [i * 4, 0, 0]}}
                   for i in range(4)]
        extracts = [{'id': 'extractBlock_' + name, 'filter': 'extractBlock',
                     'inputs': {'input': 'allRegions'}, 'options': {'selectors': ['//' + name]}}
                    for name in names]
        grouped = {'id': 'bothWalls', 'filter': 'extractBlock', 'inputs': {'input': 'allRegions'},
                   'options': {'selectors': ['//WT_wall_XP', '//WT_wall_XM']}}
        document = {'version': 'schemaxis/1', 'nodes': sources + [
            {'id': 'allRegions', 'filter': 'group', 'inputs': {'input': [node['id'] for node in sources]},
             'options': {'names': names}}] + extracts + [grouped],
            'scenes': [{'id': 'parts', 'geometry': [node['id'] for node in extracts] + ['bothWalls']}]}
        # Exercise the pure shared transaction before native execution. Source,
        # producer and published extract references must all survive independently.
        for index, new_name in ((0, '004_renamed'), (4, 'renamedRegions'), (5, 'renamed_internalMesh')):
            document = rename_identity(document, '/nodes/' + str(index) + '/id', new_name,
                                       digest(document))['input']
        extracts = document['nodes'][5:9]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'result'
            result = run(document, directory, timeout=120)
            self.assertTrue(result['verified'])
            receipt = json.loads((directory / 'verification.json').read_text())
            artifacts = receipt['artifacts']
            self.assertEqual(len(artifacts), 5)
            # Independent fresh-file verification is part of job.run; inspect the
            # actual receipt's spatial evidence in addition to its success flag.
            evidence = json.dumps(receipt)
            for node in extracts:
                self.assertIn(node['id'], evidence)
            self.assertNotIn('extractBlock_internalMesh', evidence)
            self.assertTrue(all(artifact['identity']['node'] in [node['id'] for node in extracts] + ['bothWalls']
                                for artifact in artifacts), artifacts)
            for index, name in enumerate(names):
                self.assertEqual(artifacts[index]['data']['names'], [name])
                self.assertTrue(artifacts[index]['verified'])
            self.assertEqual(artifacts[-1]['data']['names'], names[1:3])
            observations = receipt['states'][0]['observations']
            cells = [observations[node['id']]['cells'] for node in extracts]
            self.assertTrue(all(count > 0 for count in cells), cells)
            self.assertEqual(observations['bothWalls']['cells'], cells[1] + cells[2])
            for index, node in enumerate(extracts):
                bounds = observations[node['id']]['bounds']
                self.assertAlmostEqual((bounds[0] + bounds[1]) / 2, index * 4, places=5)

    def test_generated_filter_siblings_construct_from_separate_inputs(self):
        nodes = [
            {'id': 'shortLine', 'filter': 'line', 'options': {'start': [0, 0, 0], 'end': [1, 0, 0]}},
            {'id': 'longLine', 'filter': 'line', 'options': {'start': [3, 0, 0], 'end': [7, 0, 0]}},
            {'id': 'shortArc', 'filter': 'pvAppendArcLength', 'inputs': {'Input': 'shortLine'}},
            {'id': 'longArc', 'filter': 'pvAppendArcLength', 'inputs': {'Input': 'longLine'}},
        ]
        document = {'version': 'schemaxis/1', 'nodes': nodes,
                    'scenes': [{'id': 'arcs', 'geometry': ['shortArc', 'longArc']}]}
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'result'
            self.assertTrue(run(document, directory, timeout=120)['verified'])
            observations = json.loads((directory / 'verification.json').read_text())['states'][0]['observations']
            self.assertEqual(observations['shortArc']['bounds'][:2], [0, 1])
            self.assertEqual(observations['longArc']['bounds'][:2], [3, 7])

    def test_ordinary_threshold_siblings_keep_shared_field_and_separate_ranges(self):
        nodes = [
            {'id': 'source', 'filter': 'sphere', 'options': {'radius': 2}},
            {'id': 'field', 'filter': 'calculator', 'inputs': {'input': 'source'},
             'options': {'expression': 'coordsX', 'result': 'positionX'}},
            {'id': 'left', 'filter': 'threshold', 'inputs': {'input': 'field'},
             'options': {'field': ['POINTS', 'positionX'], 'lower': -2, 'upper': -0.25}},
            {'id': 'right', 'filter': 'threshold', 'inputs': {'input': 'field'},
             'options': {'field': ['POINTS', 'positionX'], 'lower': 0.25, 'upper': 2}},
        ]
        document = {'version': 'schemaxis/1', 'nodes': nodes,
                    'scenes': [{'id': 'ranges', 'geometry': ['left', 'right']}]}
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'result'
            self.assertTrue(run(document, directory, timeout=120)['verified'])
            receipt = json.loads((directory / 'verification.json').read_text())
            by_node = {artifact['identity']['node']: artifact for artifact in receipt['artifacts']}
            self.assertEqual(set(by_node), {'left', 'right'})
            self.assertTrue(all(artifact['verified'] for artifact in by_node.values()))
            observations = receipt['states'][0]['observations']
            self.assertGreater(observations['left']['cells'], 0)
            self.assertGreater(observations['right']['cells'], 0)
            self.assertLessEqual(observations['left']['bounds'][1], -0.25)
            self.assertGreaterEqual(observations['right']['bounds'][0], 0.25)

    def test_generated_extract_uses_full_paths_in_the_inherited_hierarchy(self):
        nodes = [
            {'id': 'left', 'filter': 'sphere', 'options': {'centre': [-4, 0, 0]}},
            {'id': 'right', 'filter': 'sphere', 'options': {'centre': [4, 0, 0]}},
            {'id': 'parts', 'filter': 'group', 'inputs': {'input': ['left', 'right']},
             'options': {'names': ['Left', 'Right']}},
            {'id': 'leftPart', 'filter': 'pvExtractBlock', 'inputs': {'Input': 'parts'},
             'options': {'Assembly': 'Hierarchy', 'Selectors': ['/Root/Left']}},
            {'id': 'rightPart', 'filter': 'pvExtractBlock', 'inputs': {'Input': 'parts'},
             'options': {'Assembly': 'Hierarchy', 'Selectors': ['/Root/Right']}},
        ]
        document = {'version': 'schemaxis/1', 'nodes': nodes,
                    'scenes': [{'id': 'partsScene', 'geometry': ['leftPart', 'rightPart']}]}
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'result'
            self.assertTrue(run(document, directory, timeout=120)['verified'])
            receipt = json.loads((directory / 'verification.json').read_text())
            names = {artifact['identity']['node']: artifact['data']['names']
                     for artifact in receipt['artifacts']}
            self.assertEqual(names, {'leftPart': ['Left'], 'rightPart': ['Right']})

    def test_generated_reader_reports_available_names_separately_from_active_arrays(self):
        from schemaxis.adaptors.paraview.studio import inspect_input

        fixture = Path(__file__).resolve().parents[2] / 'examples/schemaxis/fixtures/meshio/hex-affine.vtu'
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'input.vtu'
            source.write_bytes(fixture.read_bytes().replace(b"encoding='ascii'", b"encoding='UTF-8'", 1))
            document = {'version': 'schemaxis/1', 'nodes': [
                {'id': 'reader', 'filter': 'pvXMLUnstructuredGridReader',
                 'options': {'FileName': [str(source)], 'PointArrayStatus': ['node_id']}},
            ]}
            result = inspect_input(document, 'reader', find_paraview()[0].executable, Path(temporary) / 'inspect')
        self.assertEqual(set(result['readerChoices']['PointArrayStatus']), {'node_id', 'displacement'})
        self.assertEqual(set(result['readerChoices']['CellArrayStatus']), {'region', 'direction'})
        self.assertIn('node_id', result['observation']['fields']['POINTS'])
        self.assertNotIn('displacement', result['observation']['fields']['POINTS'])

    def test_managed_writer_siblings_publish_distinct_verified_files(self):
        nodes = [
            {'id': 'left', 'filter': 'sphere', 'options': {'centre': [-4, 0, 0]}},
            {'id': 'right', 'filter': 'sphere', 'options': {'centre': [4, 0, 0]}},
        ]
        exports = [
            {'id': 'saved', 'node': 'left', 'writer': 'pvWriteXMLPolyDataWriter'},
            {'id': 'export_right', 'node': 'right', 'writer': 'pvWriteXMLPolyDataWriter'},
        ]
        document = {'version': 'schemaxis/1', 'nodes': nodes,
                    'scenes': [{'id': 'delivery', 'exports': exports}]}
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'output'
            self.assertTrue(run(document, directory, timeout=120)['verified'])
            receipt = json.loads((directory / 'verification.json').read_text())
            artifacts = [item for item in receipt['artifacts'] if item['identity']['kind'] == 'export']
            self.assertEqual({item['identity']['writer'] for item in artifacts}, {'saved', 'export_right'})
            self.assertEqual(len({item['file'] for item in artifacts}), 2)
            self.assertTrue(all(item['verified'] for item in artifacts))
