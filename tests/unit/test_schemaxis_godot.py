"""Host contract tests; optional native coverage uses GODOT_EXECUTABLE."""
import base64
import copy
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from schemaxis.core.faults import SchemaxisError, Fault
from schemaxis.adaptors.godot import DECLARATIONS, plan, run, schema, verify
from schemaxis.adaptors.godot import gltf
from schemaxis.adaptors.godot.adaptor import expected_bounds

ROOT = Path(__file__).resolve().parents[2]


def document():
    return {'version': 'schemaxis.godot/1', 'nodes': [
        {'id': 'paint', 'filter': 'material'},
        {'id': 'block', 'filter': 'box', 'inputs': {'material': 'paint'}},
        {'id': 'view', 'filter': 'camera'},
        {'id': 'sun', 'filter': 'directionalLight'}]}


def triangle():
    raw = struct.pack('<9f', -1, 0, 0, 2, 0, 0, 0, 3, 0)
    return {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}],
            'meshes': [{'primitives': [{'attributes': {'POSITION': 0}}]}],
            'buffers': [{'uri': 'data:application/octet-stream;base64,'+base64.b64encode(raw).decode(), 'byteLength': 36}],
            'bufferViews': [{'buffer': 0, 'byteLength': 36}],
            'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 3, 'type': 'VEC3'}]}


class GodotTests(unittest.TestCase):
    def test_host_safe_deterministic_planning_and_schema(self):
        source = document(); original = copy.deepcopy(source)
        prepared = plan(source)
        self.assertEqual(source, original)
        self.assertEqual(plan(source), prepared)
        self.assertEqual(prepared['expectedNodeCount'], 4)
        self.assertEqual(prepared['nodes'][1]['options']['size'], [1, 1, 1])
        self.assertEqual(schema()['properties']['version']['const'], 'schemaxis.godot/1')
        self.assertEqual(len(schema()['properties']['nodes']['items']['oneOf']), len(DECLARATIONS))
        for path in (ROOT/'examples/schemaxis').glob('godot-*.json'):
            json.dumps(plan(json.loads(path.read_text())), allow_nan=False)
        subprocess.run([sys.executable, '-c',
                        'from schemaxis.adaptors.godot import schema; import sys; schema(); '
                        'assert not any(x in sys.modules for x in ("godot", "bpy", "FreeCAD", "paraview"))'], check=True)

    def test_invalid_documents_and_script_injection_are_closed(self):
        for replacement in (None, [], {}, {'version': 'schemaxis.godot/2'}, {'version': 'schemaxis.godot/1', 'nodes': []},
                            {**document(), 'script': 'quit()'}, {**document(), 'units': 'mm'}):
            with self.subTest(replacement=replacement), self.assertRaises(SchemaxisError):
                plan(replacement)
        for node in ({'id': '../scene', 'filter': 'box'}, {'id': 'block', 'filter': []},
                     {'id': 'block', 'filter': 'script'}, {'id': 'block', 'filter': 'box'},
                     {'id': 'block', 'filter': 'box', 'inputs': {'material': 'later'}},
                     {'id': 'block', 'filter': 'box', 'inputs': {'material': []}},
                     {'id': 'paint', 'filter': 'material'}):
            value = document(); value['nodes'][1] = node
            with self.subTest(node=node), self.assertRaises(SchemaxisError): plan(value)
        value = document(); value['nodes'].append({'id': 'block2', 'filter': 'box', 'inputs': {'material': 'block'}})
        with self.assertRaises(SchemaxisError): plan(value)
        value = document(); value['nodes'] *= 40
        with self.assertRaises(SchemaxisError): plan(value)

    def test_numbers_and_camera_constraints(self):
        for preview in (1, None, {}, 'true'):
            with self.assertRaises(SchemaxisError): plan({**document(), 'preview': preview})
        self.assertEqual(plan({**document(), 'preview': True})['expectedPublications'], 3)
        for options in ({'size': [0, 1, 1]}, {'size': [True, 1, 1]}, {'size': [1, 2]},
                        {'size': [float('inf'), 1, 1]}, {'position': [float('nan'), 0, 0]},
                        {'position': [100001, 0, 0]}, {'size': {'$eval': '1+1'}}, {'script': 'bad'}):
            value = document(); value['nodes'][1]['options'] = options
            with self.subTest(options=options), self.assertRaises(SchemaxisError): plan(value)
        for options in ({'position': [0, 0, 0]}, {'position': [0, 1, 0]}, {'near': 10, 'far': 2}, {'fov': 180}, {'orbit': 1}):
            value = document(); value['nodes'][2]['options'] = options
            with self.subTest(options=options), self.assertRaises(SchemaxisError): plan(value)
        for extra in ({'id': 'view2', 'filter': 'camera'}, {'id': 'unused', 'filter': 'material'}):
            value = document(); value['nodes'].append(extra)
            with self.assertRaises(SchemaxisError): plan(value)
        value = document(); del value['nodes'][2]
        with self.assertRaises(SchemaxisError): plan(value)

    def test_glTF_boundaries_and_measures_from_bytes(self):
        original = triangle()
        self.assertEqual(gltf.inspect(json.dumps(original).encode()), {'bounds': [-1, 0, 0, 2, 3, 0], 'triangles': 1})
        mutations = [lambda d: d.update(extensionsUsed=['arbitrary']),
                     lambda d: d['buffers'][0].update(uri='../../private.bin'),
                     lambda d: d['buffers'][0].update(uri='https://example.com/file'),
                     lambda d: d['buffers'][0].update(byteLength=999),
                     lambda d: d['nodes'][0].update(translation=[1, 2, 3]),
                     lambda d: d['meshes'][0]['primitives'][0].update(material=0),
                     lambda d: d['meshes'][0]['primitives'][0].update(mode=1),
                     lambda d: d['accessors'][0].update(count=100001),
                     lambda d: d['accessors'][0].update(min=[-99, 0, 0]),
                     lambda d: d['accessors'][0].update(sparse={}),
                     lambda d: d['bufferViews'][0].update(byteLength=1)]
        for mutate in mutations:
            value = copy.deepcopy(original); mutate(value)
            with self.assertRaises(SchemaxisError): gltf.inspect(json.dumps(value).encode())
        for data in (b'no JSON', b'null', b'{}', b' '* (gltf.MAX_BYTES+1)):
            with self.assertRaises(SchemaxisError): gltf.inspect(data)
        value = document(); value['nodes'][1].update(filter='readGLTF', options={'file': 'relative.gltf'})
        with self.assertRaises(SchemaxisError): plan(value)

    def test_expected_bounds_have_independent_values(self):
        value = document(); value['nodes'][1]['options'] = {'position': [2, 3, 4], 'size': [2, 4, 6]}
        self.assertEqual(expected_bounds(plan(value)['nodes'][1], {}), [1, 1, 1, 3, 5, 7])

    def test_execution_errors_have_structured_faults(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(SchemaxisError) as caught:
                run(document(), root/'missing', '/no/such/godot')
            self.assertEqual(caught.exception.fault.code, 'INTERPRETER_NOT_FOUND')
            with self.assertRaises(SchemaxisError) as caught:
                run(document(), root, sys.executable)
            self.assertEqual(caught.exception.fault.code, 'OUTPUT_EXISTS')
            for timeout in (0, -1, True, float('nan'), 3601):
                with self.assertRaises(SchemaxisError): run(document(), root/'timeout', sys.executable, timeout)
            with patch('schemaxis.adaptors.godot.adaptor.SubprocessRunner.__call__',
                       side_effect=SchemaxisError(Fault('RUNNER_TIMED_OUT', 'timed out', '$', 'submission'))):
                with self.assertRaises(SchemaxisError) as caught: run(document(), root/'timeout', sys.executable, 1)
                self.assertEqual(caught.exception.fault.code, 'RUNNER_TIMED_OUT')
            self.assertFalse(json.loads((root/'timeout/result.json').read_text())['verified'])
            with patch('schemaxis.adaptors.godot.adaptor.dispatch_stage', side_effect=lambda c,d,s,t,e: (d/(s+'.log')).write_text('')):
                with self.assertRaises(SchemaxisError): run(document(), root/'false-success', sys.executable)
            with self.assertRaises(SchemaxisError): verify(root/'absent')

    @unittest.skipUnless(os.environ.get('GODOT_EXECUTABLE'), 'set GODOT_EXECUTABLE for native qualification')
    def test_native_readback_and_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)/'scene'
            result = run(document(), project, os.environ['GODOT_EXECUTABLE'], 30)
            self.assertTrue(result['verified'])
            self.assertTrue(verify(project)['verified'])
            receipt = json.loads((project/'reopened.json').read_text())
            built = json.loads((project/'built.json').read_text())
            # Alter both receipts: expected input readback must still reject them.
            mutations = [lambda r: r['scene'].update(nodeCount=99),
                         lambda r: r['scene']['nodes']['block']['material'].update(metallic=0.7),
                         lambda r: r['scene']['nodes']['block'].update(bounds=[0]*6),
                         lambda r: r['scene']['nodes']['view'].update(fov=110),
                         lambda r: r['scene']['nodes']['view'].update(orbit=False),
                         lambda r: r['scene']['nodes']['sun']['settings'].update(energy=9)]
            for mutate in mutations:
                for filename, original in [('built.json', built), ('reopened.json', receipt)]:
                    altered = copy.deepcopy(original); mutate(altered)
                    (project/filename).write_text(json.dumps(altered))
                with self.assertRaises(SchemaxisError): verify(project)
            for filename, original in [('built.json', built), ('reopened.json', receipt)]:
                (project/filename).write_text(json.dumps(original))
            (project/'scene.tscn').write_text('; replaced')
            with self.assertRaises(SchemaxisError): verify(project)

    @unittest.skipUnless(os.environ.get('GODOT_EXECUTABLE') and os.environ.get('GODOT_GRAPHICAL_TESTS'),
                         'set GODOT_EXECUTABLE and GODOT_GRAPHICAL_TESTS for Xvfb/software-OpenGL qualification')
    def test_graphical_preview_reloads_and_changes_with_material(self):
        from schemaxis.adaptors.godot.preview import inspect_png
        with tempfile.TemporaryDirectory() as temporary:
            first = document(); first['preview'] = True
            first['nodes'][0]['options'] = {'colour': [1, 0, 0]}
            project = Path(temporary)/'red'
            result = run(first, project, os.environ['GODOT_EXECUTABLE'], 30)
            self.assertEqual(result['artifacts'], 3)
            pixels = (project/'preview.png').read_bytes()
            self.assertEqual(inspect_png(pixels), [640, 480])
            evidence = json.loads((project/'rendered.json').read_text())
            self.assertEqual(evidence['image']['display'], 'X11')
            second = copy.deepcopy(first); second['nodes'][0]['options']['colour'] = [0, 1, 0]
            other = Path(temporary)/'green'
            run(second, other, os.environ['GODOT_EXECUTABLE'], 30)
            self.assertNotEqual(pixels, (other/'preview.png').read_bytes())
            for corrupted in (pixels[:-10], pixels[:40]+b'bad'+pixels[43:], b'not png'):
                with self.assertRaises(SchemaxisError): inspect_png(corrupted)
            (project/'preview.png').write_bytes((other/'preview.png').read_bytes())
            with self.assertRaises(SchemaxisError): verify(project)

    def test_unavailable_graphical_runtime_is_explicit(self):
        from schemaxis.adaptors.godot.adaptor import render_command
        with patch('schemaxis.adaptors.godot.adaptor.shutil.which', return_value=None):
            with self.assertRaises(SchemaxisError) as caught:
                render_command('/godot', '/unused')
        self.assertEqual(caught.exception.fault.code, 'PREVIEW_UNAVAILABLE')

    def test_dispatch_pre_cancel_and_shared_deadline(self):
        from schemaxis.dispatch import allocation
        cancel = threading.Event(); cancel.set()
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)/'cancelled'
            with allocation({}, cancel), self.assertRaises(SchemaxisError) as caught:
                run(document(), target, sys.executable)
            self.assertEqual(caught.exception.fault.code, 'RUNNER_CANCELLED')
            self.assertFalse(list(target.rglob('*.metrics.json')))
            self.assertEqual(json.loads((target/'result.json').read_text())['fault']['code'], 'RUNNER_CANCELLED')
            calls = []
            def completed_stage(command, directory, stage, timeout, environment):
                calls.append((stage, timeout))
                (directory/(stage+'.log')).write_text('')
            with patch('schemaxis.adaptors.godot.adaptor.time.monotonic', side_effect=[10, 11, 14]), \
                 patch('schemaxis.adaptors.godot.adaptor.dispatch_stage', side_effect=completed_stage), \
                 self.assertRaises(SchemaxisError) as caught:
                run(document(), Path(temporary)/'deadline', sys.executable, 3)
            self.assertEqual(calls, [('build', 2)])
            self.assertEqual(caught.exception.fault.code, 'RUNNER_TIMED_OUT')

    @unittest.skipUnless(os.environ.get('GODOT_EXECUTABLE') and os.environ.get('GODOT_GRAPHICAL_TESTS'),
                         'native cancellation includes the graphical render process')
    def test_native_cancellation_in_each_stage(self):
        from schemaxis.adaptors.godot.adaptor import dispatch_stage
        from schemaxis.dispatch import allocation
        # Delay native frames so cancellation is exercised in a live Godot process,
        # including the Xvfb wrapper, rather than merely before dispatch.
        with tempfile.TemporaryDirectory() as temporary:
            for target_stage in ('build', 'reopen', 'render'):
                cancel = threading.Event()
                project = Path(temporary)/target_stage
                def dispatch(command, directory, stage, timeout, environment):
                    if stage != target_stage:
                        return dispatch_stage(command, directory, stage, timeout, environment)
                    command = list(command)
                    index = command.index('--')
                    command[index:index] = ['--frame-delay', '1000']
                    stop = threading.Event()
                    def request_cancel():
                        deadline = time.monotonic()+5
                        while not stop.wait(0.01) and time.monotonic() < deadline:
                            for path in (directory/'.dispatch'/stage).glob('*.stdout.log'):
                                if 'Godot Engine' in path.read_text():
                                    cancel.set()
                                    return
                    monitor = threading.Thread(target=request_cancel)
                    monitor.start()
                    try:
                        return dispatch_stage(command, directory, stage, timeout, environment)
                    finally:
                        stop.set(); monitor.join()
                with self.subTest(stage=target_stage), allocation({'threads': 2}, cancel), \
                     patch('schemaxis.adaptors.godot.adaptor.dispatch_stage', side_effect=dispatch), \
                     self.assertRaises(SchemaxisError) as caught:
                    run({**document(), 'preview': True}, project, os.environ['GODOT_EXECUTABLE'], 20)
                self.assertEqual(caught.exception.fault.code, 'RUNNER_CANCELLED')
                self.assertEqual(json.loads((project/'result.json').read_text())['fault']['code'], 'RUNNER_CANCELLED')
                metrics = list((project/'.dispatch'/target_stage).glob('*.metrics.json'))
                self.assertEqual(len(metrics), 1)
                self.assertEqual(json.loads(metrics[0].read_text())['fault'], 'RUNNER_CANCELLED')
                self.assertFalse((project/'artifacts.json').exists())


class InputLimitFaultTests(unittest.TestCase):
    def test_combined_input_limit_names_png_sprites_and_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            executable = root/'godot'
            executable.write_text('#!/bin/sh\n'); executable.chmod(0o755)
            nodes = []
            for index in range(5):
                image = root/('s%d.png' % index)
                image.write_bytes(bytes(7 * 1024 * 1024))
                nodes.append({'id': 's%d' % index, 'filter': 'sprite3D', 'options': {'file': str(image)}})
            image_info = {'width': 1, 'height': 1, 'rgbaSHA256': '0'}
            with patch('schemaxis.adaptors.godot.adaptor.plan', return_value={'nodes': nodes}), \
                 patch('schemaxis.adaptors.godot.adaptor.image_info', return_value=image_info), \
                 self.assertRaises(SchemaxisError) as caught:
                run(document(), root/'out', str(executable), 20)
            fault = caught.exception.fault
            self.assertEqual(fault.code, 'RESOURCE_LIMIT')
            self.assertIn('PNG', fault.message)
            self.assertIn('glTF', fault.message)
            self.assertIn('sprite images', fault.recovery)


if __name__ == '__main__':
    unittest.main()
