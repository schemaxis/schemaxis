"""Host-only contract checks. Node doubles never qualify native Premiere."""
import copy
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from schemaxis.adaptors.premiere import adaptor
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
OBSERVER = ROOT / 'src/schemaxis/adaptors/premiere/uxp/observer.js'
DOUBLE = ROOT / 'tests/fixtures/premiere-contract-double.cjs'


class PremiereTests(unittest.TestCase):
    def document(self): return json.loads((ROOT / 'examples/schemaxis/premiere-sequence.json').read_text())

    def test_plan_exact_ticks_and_preserves_document(self):
        document = self.document(); before = copy.deepcopy(document)
        prepared = adaptor.plan(document)
        self.assertEqual(document, before)
        self.assertEqual(prepared['timebaseTicks'], '10160640000')
        self.assertEqual(prepared['endTicks'], '50803200000')
        self.assertEqual(prepared['clips'][0]['outTicks'], '60963840000')
        document['clips'][0]['startFrame'] = 1000000
        self.assertEqual(adaptor.plan(document)['clips'][0]['inTicks'], '10160640000000000')

    def test_declared_composition_matches_current_common_host_planning(self):
        from schemaxis.adaptors import registry
        document=self.document();baseline=registry.plan(document)
        self.assertTrue(registry.resolve(document)[1]['compose'])
        document['definitions']={'rate':25}
        document['fps']={'$document':'/definitions/rate'}
        self.assertEqual(registry.plan(document),baseline)
        document['dimensions']={'variant':{'$analytic':{'type':'values','values':[1,2]}}}
        self.assertEqual(registry.plan(document)['states'],2)

    def test_release_policy_captures_stable_application_patches_not_beta_or_uxp(self):
        metadata=json.loads((ROOT/'src/schemaxis/adaptors/premiere/upstream.json').read_text())
        pattern=metadata['source']['pattern']
        self.assertEqual(re.findall(pattern,'<h2>September 2026 (version 26.5.2)</h2>'),['26.5.2'])
        self.assertEqual(re.findall(pattern,'<h2 id="release">September 2026 (version 26.5)</h2>'),['26.5'])
        self.assertFalse(re.findall(pattern,'<h2>September 2026 (version 27.0 Beta)</h2>'))
        self.assertFalse(re.findall(pattern,'<h2>UXP v9.3.0</h2>'))
        self.assertIsNone(metadata['absorbedVersion'])

    def test_bounds_paths_unknown_fields_and_fractional_rates(self):
        for edit in (lambda d:d.update(fps=29),lambda d:d.update(fps=True),lambda d:d.update(extra='native code'),
                     lambda d:d.update(projectPath='relative.prproj'),lambda d:d['clips'][0].update(sourcePath='/a\x00.mkv'),
                     lambda d:d['clips'][0].update(frameCount=600),lambda d:d['clips'][0].update(frameCount=0)):
            document=self.document(); edit(document)
            with self.assertRaises(SchemaxisError): adaptor.plan(document)
        document=self.document();document['projectPath']='C:\\Projects\\colours.prproj'
        adaptor.plan(document)

    def test_escaped_request_byte_budget_is_admitted_before_bridge_launch(self):
        for source in ('/'+'x'*4095, '/'+'\u00e9'*4095):
            document=self.document()
            document['clips']=[{'sourcePath':source,'frameCount':1} for _ in range(128)]
            with self.assertRaises(SchemaxisError) as raised:adaptor.plan(document)
            self.assertEqual(raised.exception.fault.code,'RESOURCE_LIMIT')

    def request(self,directory,high_precision=False):
        document=self.document()
        if high_precision:document['clips'][0]['startFrame']=1000000
        prepared=adaptor.plan(document)
        request=adaptor._request(prepared,'f'*32,int((time.time()+30)*1000))
        (directory/'request.json').write_bytes(adaptor._encode(request))
        return request

    @unittest.skipUnless(shutil.which('node'), 'optional Node runs actual companion with host-only contract doubles')
    def test_actual_companion_nonce_hash_exact_native_strings_and_changed_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for mode in ('valid','high-precision','changed-request','changed-sequence','oversized-track','imprecise-ticks','stale-response'):
                directory=root/mode;directory.mkdir();request=self.request(directory,high_precision=mode=='high-precision')
                result=subprocess.run(['node',str(DOUBLE),str(OBSERVER),str(directory),mode],capture_output=True,timeout=10)
                if mode in ('valid','high-precision'):
                    self.assertEqual(result.returncode,0,result.stderr.decode())
                    response=json.loads(result.stdout)
                    self.assertEqual(response['nonce'],request['nonce'])
                    self.assertEqual(response['requestSHA256'],hashlib.sha256((directory/'request.json').read_bytes()).hexdigest())
                    adaptor._response(response,request,(directory/'request.json').read_bytes())
                    self.assertEqual(response['observation']['clips'][0]['inTicks'],'10160640000000000' if mode=='high-precision' else '30481920000')
                else:
                    self.assertNotEqual(result.returncode,0,mode)

    @unittest.skipUnless(shutil.which('node'), 'optional Node executes supplied companion in host-only transport tests')
    def test_full_host_transport_and_offline_integrity_explicit_contract_double(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); bridge=root/'bridge';bridge.mkdir(); errors=[]
            def worker():
                try:
                    deadline=time.monotonic()+5
                    while time.monotonic()<deadline:
                        jobs=list(bridge.glob('schemaxis-premiere-*'))
                        if jobs and (jobs[0]/'request.json').exists():
                            subprocess.run(['node',str(DOUBLE),str(OBSERVER),str(jobs[0]),'valid'],capture_output=True,timeout=10,check=True);return
                        time.sleep(.01)
                    raise AssertionError('host double did not receive job')
                except Exception as error:errors.append(error)
            thread=threading.Thread(target=worker);thread.start()
            with patch.object(adaptor.sys,'platform','darwin'):
                result=adaptor.run(self.document(),root/'attempt',bridge=bridge,timeout=5)
            thread.join(timeout=12);self.assertFalse(thread.is_alive());self.assertFalse(errors,errors)
            self.assertTrue(result['verified']);adaptor.verify(root/'attempt')
            job=next(bridge.iterdir())
            if os.name == 'posix': self.assertEqual(job.stat().st_mode&0o777,0o700)
            response=json.loads((root/'attempt/response.json').read_text())
            original=copy.deepcopy(response)
            for edit in (lambda r:r.update(nonce='e'*32),lambda r:r.update(requestSHA256='0'*64),
                         lambda r:r['observation']['sequence'].update(timebaseTicks=10160640000),
                         lambda r:r['observation']['clips'][0].update(disabled=True),
                         lambda r:r['observation']['runtime'].update(hostName='photoshop'),
                         lambda r:r['observation']['runtime'].update(hostVersion='26.4.0')):
                response=copy.deepcopy(original);edit(response)
                with self.assertRaises(SchemaxisError):adaptor._response(response,json.loads((root/'attempt/request.json').read_text()),(root/'attempt/request.json').read_bytes())
            (root/'attempt/observation.json').write_text('{}')
            with self.assertRaises(SchemaxisError):adaptor.verify(root/'attempt')

    def test_linux_unavailable_without_fake_native_and_bounded_timeout_cancel(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);bridge=root/'bridge';bridge.mkdir()
            with patch.object(adaptor.sys,'platform','linux'):
                with self.assertRaises(SchemaxisError) as raised:adaptor.run(self.document(),root/'linux',bridge=bridge)
                self.assertEqual(raised.exception.fault.code,'NATIVE_ENVIRONMENT_UNAVAILABLE')
            for label,timeout,cancel,code in [('timeout',.03,False,'RUNNER_TIMED_OUT'),('cancel',5,True,'RUNNER_CANCELLED')]:
                with patch.object(adaptor.sys,'platform','darwin'),patch.object(adaptor,'cancellation_requested',return_value=cancel):
                    with self.assertRaises(SchemaxisError) as raised:adaptor.run(self.document(),root/label,bridge=bridge,timeout=timeout)
                    self.assertEqual(raised.exception.fault.code,code)
            requests=[json.loads((job/'request.json').read_text()) for job in bridge.iterdir()]
            self.assertEqual(len({r['nonce'] for r in requests}),2)

    def test_nonregular_symlink_and_oversized_evidence_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            files=[root]
            if hasattr(os, 'mkfifo'):
                fifo=root/'fifo';os.mkfifo(fifo);files.append(fifo)
            for file in files:
                with self.assertRaises(SchemaxisError):adaptor._bytes(file)
            target=root/'target';target.write_bytes(b'abc');link=root/'link'
            try: link.symlink_to(target)
            except (OSError, NotImplementedError): pass  # Windows may require developer mode/privileges.
            else:
                with self.assertRaises(SchemaxisError):adaptor._bytes(link)
            with patch.object(adaptor,'MAX_BYTES',2):
                with self.assertRaises(SchemaxisError):adaptor._bytes(target)

    def test_public_verify_malformed_result_and_existing_attempt_are_structured(self):
        from schemaxis.adaptors import registry
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/'authored.json').write_text(json.dumps(self.document()))
            (root/'plan.json').write_text(json.dumps(adaptor.plan(self.document())))
            (root/'result.json').write_text('null')
            with self.assertRaises(SchemaxisError) as raised:registry.verify(root)
            self.assertEqual(raised.exception.fault.code,'VERIFICATION_FAILED')
            with self.assertRaises(SchemaxisError) as raised:adaptor.run(self.document(),root)
            self.assertEqual(raised.exception.fault.code,'OUTPUT_EXISTS')


if __name__=='__main__':unittest.main()
