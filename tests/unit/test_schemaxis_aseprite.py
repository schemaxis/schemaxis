# Copyright (C) 2026 David L F Gaden
"""Host contract tests; optional native checks use ASEPRITE_EXE explicitly."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from schemaxis.core.faults import SchemaxisError, Fault
from schemaxis.adaptors.aseprite import DECLARATIONS, plan, run, schema, verify
from schemaxis.adaptors.aseprite.adaptor import expected
from schemaxis.dispatch import SubprocessRunner, allocation

ROOT = Path(__file__).resolve().parents[2]


def example(label='animation'):
    return json.loads((ROOT/'examples'/'schemaxis'/f'aseprite-{label}.json').read_text())


class AsepriteTests(unittest.TestCase):
    def rejects(self, document, code=None):
        with self.assertRaises(SchemaxisError) as caught:
            plan(document)
        if code: self.assertEqual(caught.exception.fault.code, code)

    def test_examples_and_independent_pixels(self):
        document = example()
        before = copy.deepcopy(document)
        prepared = plan(document)
        self.assertEqual(document, before)
        self.assertEqual(json.loads(json.dumps(prepared)), prepared)
        native, preview, sheet, metadata = expected(prepared)
        self.assertEqual(native['layers'], ['base', 'orb'])
        self.assertEqual(native['durationsMS'], [120, 200])
        self.assertEqual(sheet['width'], 32)
        self.assertEqual(metadata['frames'][1]['x'], 16)
        pixels = bytes.fromhex(preview['pixels'])
        self.assertEqual(pixels[(7*16+4)*4:(7*16+4)*4+4], bytes([255]*4))
        self.assertEqual(pixels[:4], bytes([20,40,80,255]))
        icon = expected(plan(example('icon')))[1]
        self.assertEqual(bytes.fromhex(icon['pixels'])[(3*8+3)*4:(3*8+3)*4+4], bytes(4))

    def test_declarations_schema(self):
        from schemaxis.core.declarations import validate_specifications
        self.assertEqual(set(DECLARATIONS), {'sprite','layer','frame','palette','pixel','rect','circle','tag','importImage'})
        for decl in DECLARATIONS.values():
            validate_specifications({k:v['value'] for k,v in decl['options'].items()}, '$')
        self.assertEqual(schema()['properties']['version']['const'], 'schemaxis.aseprite/1')
        self.assertEqual(len(schema()['properties']['nodes']['items']['oneOf']), 9)

    def test_version_unknown_and_script_rejected(self):
        for field, value in [('version','schemaxis.aseprite/2'), ('script','os.execute("bad")')]:
            d=example(); d[field]=value; self.rejects(d)
        for value in [None, [], {}, True, 'executeLua']:
            d=example(); d['nodes'][0]['filter']=value; self.rejects(d, 'UNKNOWN_FILTER')
        self.rejects([])

    def test_typed_bounds(self):
        for value in [True, 0, 257, 1.5, '16', float('nan')]:
            d=example(); d['nodes'][0]['options']['width']=value; self.rejects(d, 'INVALID_ARGUMENT')
        for colour in [[1,2,3,100], [1,0,0,0], [1,2,3], [False,0,0,255]]:
            d=example(); d['nodes'][2]['options']['colour']=colour; self.rejects(d)

    def test_dependencies_and_selection(self):
        d=example(); d['nodes'][2]['inputs']['sprite']='canvas'; self.rejects(d, 'INVALID_DEPENDENCY')
        d=example(); d['nodes'][1]['id']='canvas'; self.rejects(d, 'DUPLICATE_NODE')
        d=example(); d['output']='canvas'; self.rejects(d, 'INVALID_SELECTION')
        d=example(); d['nodes'][1]['inputs']={}; self.rejects(d, 'INVALID_DEPENDENCY')

    def test_geometry_frame_layer_tag_and_budget(self):
        for index, key, value in [(4,'radius',7), (4,'layer','absent'), (4,'frame',2),
                                  (2,'width',17), (3,'name','base'), (9,'toFrame',3),
                                  (9,'fromFrame',2)]:
            d=example(); d['nodes'][index]['options'][key]=value
            if index == 9 and key == 'fromFrame': d['nodes'][index]['options']['toFrame']=1
            self.rejects(d)
        d=example(); d['nodes'][0]['options'].update(width=256,height=256)
        d['nodes'].append({'id':'third','filter':'frame','inputs':{'sprite':'bounce'}})
        d['output']='third'; self.rejects(d, 'RESOURCE_LIMIT')

    def test_no_authored_code_in_generated_source(self):
        d=example('icon')
        suspicious='"; os.execute("touch /tmp/not-authorised"); -- café'
        d['nodes'][0]['options']['layer']=suspicious
        for n in d['nodes'][1:]: n['options']['layer']=suspicious
        self.assertEqual(plan(d)['nodes'][0]['options']['layer'], suspicious)
        from schemaxis.adaptors.aseprite.native_source import WORKER
        self.assertNotIn(suspicious, WORKER)
        self.assertNotIn('loadstring', WORKER)
        d['nodes'][0]['options']['layer']='bad\0name'
        self.rejects(d, 'INVALID_ARGUMENT')

    def test_run_preflight(self):
        with tempfile.TemporaryDirectory() as temp:
            for timeout in [True, 0, -1, float('inf'), 601]:
                with self.assertRaises(SchemaxisError) as caught: run(example(), Path(temp)/'new', '/bin/true', timeout)
                self.assertEqual(caught.exception.fault.code, 'INVALID_ARGUMENT')
            with self.assertRaises(SchemaxisError) as caught: run(example(),temp,'/bin/true')
            self.assertEqual(caught.exception.fault.code,'OUTPUT_EXISTS')
            with self.assertRaises(SchemaxisError) as caught: run(example(),Path(temp)/'new','relative')
            self.assertEqual(caught.exception.fault.code,'INTERPRETER_NOT_FOUND')
            self.assertFalse((Path(temp)/'new').exists())

    def test_exit_zero_is_not_success(self):
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/'new'
            with self.assertRaises(SchemaxisError): run(example(), output, '/bin/true')
            result=json.loads((output/'result.json').read_text())
            self.assertEqual(result['status'],'failed')
            self.assertFalse(result['verified'])

    def test_timeout_and_nonzero(self):
        for code in ('RUNNER_TIMED_OUT', 'RUNNER_FAILED', 'RUNNER_CANCELLED'):
            with tempfile.TemporaryDirectory() as temp:
                error = SchemaxisError(Fault(code, 'injected runner failure', '$', 'execution'))
                with patch('schemaxis.adaptors.aseprite.adaptor.SubprocessRunner') as runner:
                    runner.return_value.side_effect = error
                    with self.assertRaises(SchemaxisError) as caught: run(example(),Path(temp)/'new','/bin/true')
                    self.assertEqual(caught.exception.fault.code,code)
                    self.assertIn('os.execv(', runner.return_value.call_args.args[0])
                    result = json.loads((Path(temp)/'new'/'result.json').read_text())
                    self.assertEqual(result['fault']['code'], code)
                    self.assertFalse(result['verified'])

    def test_cancel_before_launch_starts_no_process(self):
        with tempfile.TemporaryDirectory() as temp:
            cancel = threading.Event(); cancel.set()
            with allocation({}, cancel), patch('schemaxis.dispatch.subprocess.Popen') as process:
                with self.assertRaises(SchemaxisError) as caught:
                    run(example(), Path(temp)/'cancelled', '/bin/true')
                self.assertEqual(caught.exception.fault.code, 'RUNNER_CANCELLED')
                process.assert_not_called()

    def fake_executable(self, directory, hanging=True):
        path = directory/'fake aseprite'
        source = ('#!'+sys.executable+'\n'
                  'import json, os, pathlib, subprocess, sys, time\n'
                  'print("stage="+str(sys.argv), flush=True)\n')
        if hanging:
            source += ('child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])\n'
                       'pathlib.Path("pids.json").write_text(json.dumps([os.getpid(),child.pid]))\n'
                       'time.sleep(30)\n')
        path.write_text(source)
        path.chmod(0o700)
        return path

    def assert_process_stopped(self, pid):
        def stopped():
            try:
                return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0] in ('Z', 'X')
            except FileNotFoundError:
                return True
        deadline = time.monotonic()+2
        while not stopped() and time.monotonic() < deadline: time.sleep(.01)
        self.assertTrue(stopped(), f'owned process {pid} is still running')

    def test_active_cancel_terminates_host_fixture_and_child(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); executable = self.fake_executable(root)
            output = root/'output'; cancel = threading.Event(); observed = threading.Event()
            def request_cancel():
                deadline = time.monotonic()+3
                while time.monotonic() < deadline:
                    if (output/'pids.json').exists():
                        observed.set(); break
                    time.sleep(.01)
                cancel.set()
            monitor = threading.Thread(target=request_cancel)
            monitor.start()
            try:
                with allocation({'threads': 1, 'ranks': 1}, cancel):
                    with self.assertRaises(SchemaxisError) as caught: run(example(),output,str(executable),timeout=5)
                self.assertEqual(caught.exception.fault.code, 'RUNNER_CANCELLED')
            finally:
                monitor.join(timeout=4)
            self.assertTrue(observed.is_set(), 'fixture never reached the running stage')
            for pid in json.loads((output/'pids.json').read_text()): self.assert_process_stopped(pid)
            metrics = [json.loads(p.read_text()) for p in output.glob('replay-*.metrics.json')]
            self.assertEqual(len(metrics), 1)
            self.assertEqual(metrics[0]['fault'], 'RUNNER_CANCELLED')
            self.assertIn('stage=build', (output/'build.log').read_text())
            self.assertFalse((output/'reopen.log').exists())
            self.assertEqual(json.loads((output/'result.json').read_text())['fault']['code'], 'RUNNER_CANCELLED')

    def test_actual_runner_timeout_and_nonzero(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); executable = self.fake_executable(root)
            for label, exe, timeout, code in [('timeout',str(executable),.3,'RUNNER_TIMED_OUT'),
                                               ('failure','/bin/false',5,'RUNNER_FAILED')]:
                with self.subTest(label=label):
                    output = root/label
                    with self.assertRaises(SchemaxisError) as caught: run(example(),output,exe,timeout)
                    self.assertEqual(caught.exception.fault.code, code)
                    if (output/'pids.json').exists():
                        for pid in json.loads((output/'pids.json').read_text()): self.assert_process_stopped(pid)

    def test_cancellation_between_stages_prevents_reopen(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); cancel = threading.Event()
            executable = self.fake_executable(root, hanging=False)
            def factory(*args, **kwargs):
                actual = SubprocessRunner(*args, **kwargs)
                def invoke(source):
                    result = actual(source)
                    cancel.set()
                    return result
                return invoke
            with allocation({},cancel), patch('schemaxis.adaptors.aseprite.adaptor.SubprocessRunner',side_effect=factory):
                with self.assertRaises(SchemaxisError) as caught: run(example(),root/'job',str(executable))
            self.assertEqual(caught.exception.fault.code, 'RUNNER_CANCELLED')
            self.assertTrue((root/'job'/'build-submission.json').is_file())
            self.assertFalse((root/'job'/'reopen-submission.json').exists())
            self.assertEqual(len(list((root/'job').glob('replay-*.metrics.json'))), 1)

    @unittest.skipUnless(os.environ.get('ASEPRITE_EXE'), 'set ASEPRITE_EXE for native CPU acceptance')
    def test_native_empty_and_literal_names(self):
        with tempfile.TemporaryDirectory() as temp:
            d={'version':'schemaxis.aseprite/1', 'nodes':[{'id':'canvas','filter':'sprite',
                'options':{'width':3,'height':2,'layer':'café "quoted" \\ text'}}], 'output':'canvas'}
            self.assertTrue(run(d,Path(temp)/'empty',os.environ['ASEPRITE_EXE'])['verified'])
            d['nodes'].extend([
                {'id':'second','filter':'frame','inputs':{'sprite':'canvas'}},
                {'id':'top','filter':'layer','inputs':{'sprite':'second'},'options':{'name':'top'}},
                {'id':'palette','filter':'palette','inputs':{'sprite':'top'},
                 'options':{'colours':[[10,20,30,255]]}},
                {'id':'point','filter':'circle','inputs':{'sprite':'palette'},
                 'options':{'layer':'top','frame':2,'x':2,'y':1,'radius':0,'colour':[10,20,30,255]}}])
            d['output']='point'
            self.assertTrue(run(d,Path(temp)/'sparse',os.environ['ASEPRITE_EXE'])['verified'])

    @unittest.skipUnless(os.environ.get('ASEPRITE_EXE'), 'set ASEPRITE_EXE for native CPU acceptance')
    def test_native_reopen_tamper_and_tags(self):
        with tempfile.TemporaryDirectory() as temp:
            d=example()
            for direction in ['forward','reverse','pingPongReverse']:
                previous=d['output']; identity=direction+'Tag'
                d['nodes'].append({'id':identity,'filter':'tag','inputs':{'sprite':previous},
                    'options':{'name':direction,'fromFrame':1,'toFrame':2,'direction':direction}})
                d['output']=identity
            output=Path(temp)/'native'
            result=run(d,output,os.environ['ASEPRITE_EXE'])
            self.assertTrue(result['verified']); self.assertTrue(verify(output)['verified'])
            path=output/'verification.json'; original=path.read_bytes()
            receipt=json.loads(original); receipt['native']['durationsMS'][0]+=1
            path.write_text(json.dumps(receipt))
            with self.assertRaises(SchemaxisError): verify(output)
            path.write_bytes(original)
            image=output/'sheet.png'; image.write_bytes(image.read_bytes()+b'tamper')
            with self.assertRaises(SchemaxisError): verify(output)


if __name__ == '__main__': unittest.main()
