# Copyright (C) 2026 David L F Gaden
"""Portable validation and opt-in serial builtin ParaView live acceptance."""
import os
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.paraview.live import LiveSession
from schemaxis.adaptors.paraview.live_native import Worker


def document(radius=1):
    return {'version': 'schemaxis/1', 'nodes': [
        {'id': 'ball', 'filter': 'sphere', 'options': {'radius': radius}}],
        'scenes': [{'id': 'preview', 'visible': {'ball': {}}, 'geometry': ['ball']}]}


class ParaViewLiveHostTests(unittest.TestCase):
    def test_input_inspection_prunes_unfinished_consumers_and_keeps_observation_dependencies(self):
        from schemaxis.adaptors.paraview.studio import inspection_document
        authored = document()
        authored['nodes'].extend([
            {'id': 'measure', 'filter': 'sphere'},
            {'id': 'scaled', 'filter': 'sphere', 'options': {'radius': {'$observe': 'measure', 'path': ['points']}}},
            {'id': 'unfinished', 'filter': 'extractBlock', 'inputs': {'input': 'ball'}}])
        prepared = inspection_document(authored, 'scaled')
        self.assertEqual([node['id'] for node in prepared['nodes']], ['measure', 'scaled'])
        self.assertEqual(prepared['scenes'], [])
        self.assertEqual(len(authored['nodes']), 4)
        with self.assertRaises(SchemaxisError): inspection_document(authored, 'absent')

    def test_plan_and_scene_limits_without_native_import(self):
        worker = Worker()
        prepared = worker.prepare(document())
        self.assertEqual(prepared[3], ['ball'])
        authored = document()
        authored['scenes'].append({'id': 'other', 'geometry': ['ball']})
        with self.assertRaises(SchemaxisError) as caught: worker.prepare(authored)
        self.assertEqual(caught.exception.fault.code, 'UNSUPPORTED_LIVE_INPUT')


@unittest.skipUnless(os.environ.get('SCHEMAXIS_LIVE_PARAVIEW'), 'Set SCHEMAXIS_LIVE_PARAVIEW for serial native acceptance')
class ParaViewNativeLiveTests(unittest.TestCase):
    def test_native_block_choices_are_valid_selectors_and_inspection_preserves_session(self):
        from schemaxis.adaptors.paraview.studio import inspect_input
        authored = document()
        authored['nodes'].extend([
            {'id': 'cone', 'filter': 'cone'},
            {'id': 'grouped', 'filter': 'group', 'inputs': {'input': ['ball', 'cone']}},
            {'id': 'unfinished', 'filter': 'extractBlock', 'inputs': {'input': 'grouped'}}])
        with tempfile.TemporaryDirectory() as root:
            result = inspect_input(authored, 'grouped', os.environ['SCHEMAXIS_LIVE_PARAVIEW'], Path(root) / 'inspect')
            blocks = result['assemblies']['Hierarchy']
            choice = next(block for block in blocks if block['label'] == 'cone')
            self.assertEqual(choice['selector'], '/Root/cone')
            authored['nodes'][-1]['options'] = {'selectors': [choice['selector']]}
            extracted = inspect_input(authored, 'unfinished', os.environ['SCHEMAXIS_LIVE_PARAVIEW'], Path(root) / 'extracted')
            self.assertGreater(extracted['observation']['cells'], 0)
            self.assertLess(extracted['observation']['cells'], result['observation']['cells'])
            with LiveSession(os.environ['SCHEMAXIS_LIVE_PARAVIEW'], Path(root) / 'live') as session:
                session.request('apply', document=document())
                before = session.request('status')
                with self.assertRaises(SchemaxisError): session.request('inspect', document=document(), node='ball', port=0)
                self.assertEqual(before, session.request('status'))

    def test_foam_filename_setup_reads_regions_arrays_and_an_available_time(self):
        import sys
        from schemaxis.adaptors.paraview.studio import inspect_input
        root = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(root / 'tools'))
        from benchmark_workflows import make_foam
        case = next(c for c in json.loads((root / 'examples/benchmarks/cases.json').read_text())['rounds']['initial'] if c['family'] == 'cfd')
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory); make_foam(case, directory / 'case')
            authored = {'version': 'schemaxis/1', 'nodes': [{'id': 'foam1', 'filter': 'foam',
                'options': {'file': str(directory / 'case/case.foam')}}], 'scenes': []}
            result = inspect_input(authored, 'foam1', os.environ['SCHEMAXIS_LIVE_PARAVIEW'], directory / 'prepare', prepare=True)
            self.assertEqual(result['value']['options']['caseType'], 'Reconstructed Case')
            self.assertIn('patch/walls', result['value']['options']['regions'])
            self.assertIn('U', result['value']['options']['cellArrays'])
            self.assertIn(result['times'][0], result['availableTimes'])
            self.assertEqual(set(authored['nodes'][0]['options']), {'file'})
            authored['nodes'] = [result['value']]; authored['times'] = result['times']
            blocks = inspect_input(authored, 'foam1', os.environ['SCHEMAXIS_LIVE_PARAVIEW'], directory / 'blocks')
            self.assertIn('walls', [block['label'] for block in blocks['assemblies']['Hierarchy']])
            authored['nodes'][0]['options']['regions'] = ['internalMesh']
            explicit = inspect_input(authored, 'foam1', os.environ['SCHEMAXIS_LIVE_PARAVIEW'], directory / 'explicit', prepare=True)
            self.assertEqual(explicit['value']['options']['regions'], ['internalMesh'])
            self.assertNotIn('times', explicit)

    def test_streamline_placement_example_publishes_viewer_compatible_lines(self):
        path = Path(__file__).resolve().parents[2] / 'examples/studio/streamline-placement.json'
        with tempfile.TemporaryDirectory() as root:
            with LiveSession(os.environ['SCHEMAXIS_LIVE_PARAVIEW'], Path(root) / 'session') as session:
                session.request('apply', document=json.loads(path.read_text()))
                geometry = session.request('geometry')
                self.assertEqual(geometry['observations']['seeds']['points'], 21)
                self.assertGreater(geometry['observations']['streamlines']['cells'], 0)
                for obj in geometry['objects']:
                    self.assertTrue(obj['edges'])
                    self.assertTrue(all(len(edge['points']) >= 2 for edge in obj['edges']))
                geometry_path = Path(root) / 'geometry.json'
                geometry_path.write_text(json.dumps(geometry))
                viewer = Path(__file__).resolve().parents[2] / 'src/schemaxis/studio_ui/viewers/geometry.mjs'
                result = subprocess.run(['node', '--input-type=module', '-e',
                    'import fs from "node:fs"; import {prepareGeometry} from ' + json.dumps(viewer.as_uri()) + ';'
                    'const mesh=prepareGeometry(JSON.parse(fs.readFileSync(process.argv[1],"utf8")));'
                    'if(!mesh.segmentCount) throw Error("No rendered line segments");', str(geometry_path)],
                    capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_native_worker_exits_when_host_is_terminated(self):
        from test_blender_live import qualify_owner_death
        qualify_owner_death(self, 'paraview', os.environ['SCHEMAXIS_LIVE_PARAVIEW'])

    def test_persistent_edit_geometry_image_and_invalid_edit(self):
        with tempfile.TemporaryDirectory() as root:
            with LiveSession(os.environ['SCHEMAXIS_LIVE_PARAVIEW'], Path(root) / 'session', timeout=120) as session:
                a = session.request('apply', document=document())
                first = session.request('geometry')
                self.assertGreater(len(first['objects'][0]['faces']), 0)
                b = session.request('apply', document=document(2))
                self.assertEqual(a['pid'], b['pid'])
                self.assertEqual(a['objects'], b['objects'])
                second = session.request('geometry')
                first_points = [v for f in first['objects'][0]['faces'] for v in f['vertices']]
                second_points = [v for f in second['objects'][0]['faces'] for v in f['vertices']]
                self.assertEqual(len(first_points), len(second_points))
                for before, after in zip(first_points, second_points):
                    for x, y in zip(before, after): self.assertAlmostEqual(x * 2, y)
                with self.assertRaises(SchemaxisError): session.request('apply', document=document(-1))
                self.assertEqual(session.request('geometry'), second)
                broken = document()
                broken['nodes'].append({'id': 'bad', 'filter': 'calculator', 'inputs': {'input': 'ball'},
                                        'options': {'expression': 'missingField', 'result': 'invalid'}})
                broken['scenes'][0] = {'id': 'preview', 'geometry': ['bad']}
                with self.assertRaises(SchemaxisError) as caught: session.request('apply', document=broken)
                self.assertTrue(caught.exception.fault.observed['rolledBack'])
                self.assertEqual(session.request('geometry'), second)
                image = session.image(Path(root) / 'preview.png')
                self.assertTrue(image['verified'])
                self.assertEqual(session.request('status')['pid'], a['pid'])
                saved = session.save(Path(root) / 'scene.pvsm')
                self.assertTrue(saved['verified'])
                self.assertFalse(saved['datasetsCopied'])
                self.assertEqual(saved['externalDependencies'], [])
                self.assertEqual(session.request('geometry'), second)
                session.request('apply', document=document(3))
                self.assertEqual(session.request('status')['pid'], a['pid'])
                process = session.process
            self.assertIsNotNone(process.poll())
            session.close()
            script = Path(root) / 'reopen.py'
            script.write_text(
                'import sys,json\nfrom types import SimpleNamespace\n'
                f'sys.path.insert(0,{str(session.directory / "runtime.zip")!r})\n'
                'from paraview import simple\nfrom schemaxis.adaptors.paraview.live_native import Worker\n'
                'from schemaxis.adaptors.paraview.native import ParaViewBackend\nfrom schemaxis.pipeline import digest\n'
                f'simple.LoadState({saved["file"]!r})\n'
                f'metadata=json.load(open({saved["receipt"]!r}))\n'
                'handles={n:simple.FindSource(n) for n in metadata["visible"]}\n'
                'for proxy in handles.values(): proxy.UpdatePipeline()\n'
                'worker=Worker(); worker.prepared=(None,None,None,metadata["visible"])\n'
                'worker.active=SimpleNamespace(handles=handles,backend=ParaViewBackend())\n'
                'assert digest(worker.geometry()) == metadata["geometryDigest"]\n')
            executable = Path(os.environ['SCHEMAXIS_LIVE_PARAVIEW'])
            if executable.is_dir(): executable = executable / 'bin/pvpython'
            result = subprocess.run([str(executable), '--force-offscreen-rendering', str(script)],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_composite_surface_ids_and_edges(self):
        with tempfile.TemporaryDirectory() as root:
            with LiveSession(os.environ['SCHEMAXIS_LIVE_PARAVIEW'], Path(root) / 'session') as session:
                authored = document()
                authored['nodes'].extend([
                    {'id': 'other', 'filter': 'sphere', 'options': {'centre': [3, 0, 0]}},
                    {'id': 'grouped', 'filter': 'group', 'inputs': {'input': ['ball', 'other']}}])
                authored['scenes'] = [{'id': 'preview', 'geometry': ['grouped']}]
                session.request('apply', document=authored)
                result = session.request('geometry')
                self.assertEqual(len(result['objects']), 2)
                self.assertEqual(len({o['id'] for o in result['objects']}), 2)
                for obj in result['objects']:
                    self.assertEqual(obj['node'], 'grouped')
                    self.assertTrue(obj['faces'])
                    for face in obj['faces']:
                        for tri in face['triangles']:
                            self.assertEqual(len(tri), 3)
                            self.assertTrue(all(0 <= i < len(face['vertices']) for i in tri))
                authored = {'version': 'schemaxis/1', 'nodes': [{'id': 'wire', 'filter': 'line'}],
                            'scenes': [{'id': 'preview', 'geometry': ['wire']}]}
                session.request('apply', document=authored)
                geometry = session.request('geometry')['objects'][0]
                self.assertFalse(geometry['faces'])
                self.assertTrue(geometry['edges'])
                self.assertTrue(all(len(edge['points']) >= 2 for edge in geometry['edges']))
                source = Path(__file__).resolve().parents[2] / 'examples/schemaxis/expanded/tetrahedron.ply'
                authored['nodes'] = [{'id': 'mesh', 'filter': 'readPLY', 'options': {'files': [str(source)]}}]
                authored['scenes'] = [{'id': 'preview', 'geometry': ['mesh']}]
                session.request('apply', document=authored)
                saved = session.save(Path(root) / 'external.pvsm')
                self.assertEqual(saved['externalDependencies'][0]['files'], [str(source)])
                self.assertFalse(saved['portable'])
                self.assertFalse(saved['datasetsCopied'])
