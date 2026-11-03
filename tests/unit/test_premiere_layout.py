# Copyright (C) 2026 David L F Gaden
"""Independent literal layout fixtures; Node doubles do not qualify Premiere."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from schemaxis.adaptors.premiere import adaptor, layout
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
OBSERVER = ROOT / 'src/schemaxis/adaptors/premiere/uxp/observer.js'
DOUBLE = ROOT / 'tests/fixtures/premiere-layout-double.cjs'


def document(variant=False):
    return json.loads((ROOT / ('examples/schemaxis/premiere-layout' + ('-variant' if variant else '') + '.json')).read_text())


class LayoutTests(unittest.TestCase):
    def test_plan_independent_ticks_defaults_immutable_and_composition(self):
        from schemaxis.adaptors import registry
        authored = document(); before = copy.deepcopy(authored)
        prepared = adaptor.plan(authored)
        self.assertEqual(authored, before)
        self.assertEqual(prepared['endTicks'], '101606400000')
        self.assertEqual(prepared['tracks'][1]['clips'][0]['startTicks'], '30481920000')
        self.assertEqual(prepared['tracks'][2]['clips'], [])
        self.assertEqual(prepared['options']['requirements'][0]['minimumActiveTracks'], 1)
        authored['definitions'] = {'duration': 10}
        authored['endFrame'] = {'$document': '/definitions/duration'}
        self.assertEqual(registry.plan(authored), prepared)

    def test_semantic_faults_and_boundary_touching(self):
        probes = [
            (lambda d: d['tracks'][0]['clips'][1].update(timelineFrame=3), 'INVALID_LAYOUT'),
            (lambda d: d['tracks'][0]['clips'][1].update(frameCount=5), 'INVALID_LAYOUT'),
            (lambda d: d.update(endFrame=11), 'INVALID_LAYOUT'),
            (lambda d: d['tracks'][1].update(name='Base'), 'INVALID_SELECTION'),
            (lambda d: d['requirements'][0].update(tracks=['Absent']), 'INVALID_SELECTION'),
            (lambda d: d['requirements'][0].update(tracks=['Base','Base']), 'INVALID_SELECTION'),
            (lambda d: d['requirements'][0].update(minimumActiveTracks=3), 'INVALID_LAYOUT'),
            (lambda d: d['requirements'][0].update(frameCount=11), 'INVALID_LAYOUT'),
            (lambda d: d.update(fps=29), 'INVALID_RATE'),
        ]
        for edit, code in probes:
            with self.subTest(code=code):
                value=document(); edit(value)
                with self.assertRaises(SchemaxisError) as raised: adaptor.plan(value)
                self.assertEqual(raised.exception.fault.code,code)
        for edit in (lambda d:d['tracks'][0]['clips'][0].update(frameCount=0),
                     lambda d:d['tracks'][0]['clips'][0].update(timelineFrame=True),
                     lambda d:d.update(clips=[]),
                     lambda d:d['requirements'][0].update(frameCount=0)):
            value=document();edit(value)
            with self.assertRaises(SchemaxisError): adaptor.plan(value)
        value=document();value['tracks'][0]['clips'][0]['frameCount']=6
        self.assertEqual(adaptor.plan(value)['tracks'][0]['clips'][0]['endTicks'],'60963840000')

    def test_literal_and_authored_schema_parity(self):
        import jsonschema
        from schemaxis.schema import export_schema
        for value in (document(),document(True)):
            jsonschema.validate(value,adaptor.schema())
            jsonschema.validate(value,export_schema('premiere',authored=True))
        value=document();value['definitions']={'frames':10};value['endFrame']={'$document':'/definitions/frames'}
        jsonschema.validate(value,export_schema('premiere',authored=True))
        for edit in (lambda d:d.update(clips=[]),lambda d:d['tracks'][0]['clips'][0].update(frameCount=0),lambda d:d.pop('tracks')):
            value=document();edit(value)
            with self.assertRaises(jsonschema.ValidationError):jsonschema.validate(value,adaptor.schema())

    @unittest.skipUnless(shutil.which('node'), 'Node is needed for host-only actual UXP companion mapping')
    def test_companion_and_independent_coverage(self):
        with tempfile.TemporaryDirectory() as temporary:
            for mode in ('valid','variant','changed-request','changed-sequence','oversized-track','stale-response','muted','disabled'):
                target=Path(temporary)/mode;target.mkdir()
                authored=document(mode=='variant');prepared=adaptor.plan(authored)
                request=adaptor._request(prepared,'a'*32,int((time.time()+30)*1000))
                raw=adaptor._encode(request);(target/'request.json').write_bytes(raw)
                result=subprocess.run(['node',str(DOUBLE),str(OBSERVER),str(target),mode],capture_output=True,timeout=10)
                if mode in ('changed-request','changed-sequence','oversized-track','stale-response'):
                    self.assertNotEqual(result.returncode,0,mode);continue
                self.assertEqual(result.returncode,0,result.stderr.decode())
                response=json.loads(result.stdout)
                if mode in ('muted','disabled'):
                    with self.assertRaises(SchemaxisError):adaptor._response(response,request,raw)
                    continue
                observed=adaptor._response(response,request,raw)
                report=layout.coverage(observed,authored)
                self.assertEqual(report['tracks'][0],{'name':'Base','occupiedFrames':8,'gaps':[{'startFrame':4,'endFrame':6}]})
                self.assertEqual(report['tracks'][2],{'name':'Reserved','occupiedFrames':0,'gaps':[{'startFrame':0,'endFrame':10}]})
                self.assertEqual(report['tracks'][1]['occupiedFrames'],2 if mode=='variant' else 4)
                self.assertTrue(all(item['passed'] for item in report['requirements']))
                gap=copy.deepcopy(authored);gap['requirements'][0]['tracks']=['Base']
                self.assertEqual(layout.coverage(observed,gap)['requirements'][0]['uncoveredFrames'],[4,5])
                for field, ticks in [('startTicks','1'),('endTicks','0'),('durationTicks','1'),('outTicks','50803200000')]:
                    bad=copy.deepcopy(observed);bad['tracks'][0]['clips'][0][field]=ticks
                    with self.assertRaises(SchemaxisError):layout.coverage(bad,authored)
                bad=copy.deepcopy(observed);bad['tracks'][0]['clips'][1]['startTicks']='30481920000'
                with self.assertRaises(SchemaxisError):adaptor._observation(bad,prepared)

    @unittest.skipUnless(shutil.which('node'), 'Node is needed for host-only actual UXP companion transport')
    def test_real_host_run_verify_report_tamper_and_failed_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for identity in ('baseline','variant','failed-gate'):
                authored=document(identity=='variant')
                if identity=='failed-gate':authored['requirements'][0]['tracks']=['Base']
                bridge=root/(identity+'-bridge');bridge.mkdir();target=root/identity;errors=[]
                def worker():
                    try:
                        deadline=time.monotonic()+5
                        while time.monotonic()<deadline:
                            jobs=list(bridge.glob('schemaxis-premiere-*'))
                            if jobs and (jobs[0]/'request.json').exists():
                                subprocess.run(['node',str(DOUBLE),str(OBSERVER),str(jobs[0]),'variant' if identity=='variant' else 'valid'],capture_output=True,timeout=10,check=True);return
                            time.sleep(.01)
                        raise AssertionError('No host job arrived')
                    except Exception as error: errors.append(error)
                thread=threading.Thread(target=worker);thread.start()
                try:
                    with patch.object(adaptor.sys,'platform','darwin'):
                        if identity=='failed-gate':
                            with self.assertRaises(SchemaxisError) as raised:adaptor.run(authored,target,bridge=bridge,timeout=5)
                            self.assertEqual(raised.exception.fault.code,'REQUIREMENT_FAILED')
                        else:
                            self.assertEqual(adaptor.run(authored,target,bridge=bridge,timeout=5)['artifacts'],2)
                finally:thread.join(timeout=12)
                self.assertFalse(thread.is_alive());self.assertFalse(errors,errors)
                if identity=='failed-gate':
                    self.assertEqual(json.loads((target/'layout.json').read_text())['requirements'][0]['uncoveredFrames'],[4,5])
                    self.assertEqual(json.loads((target/'result.json').read_text())['status'],'failed')
                    with self.assertRaises(SchemaxisError):adaptor.verify(target)
                    continue
                self.assertTrue(adaptor.verify(target)['verified'])
                for filename in ('layout.json','observation.json','response.json','plan.json','authored.json'):
                    path=target/filename;original=path.read_bytes()
                    try:
                        path.write_text('{}')
                        with self.assertRaises(SchemaxisError):adaptor.verify(target)
                    finally:path.write_bytes(original)
                self.assertTrue(adaptor.verify(target)['verified'])

    def test_real_native_unavailable_records_failure(self):
        import sys
        if sys.platform in ('darwin','win32'):self.skipTest('Requires Linux limitation probe')
        with tempfile.TemporaryDirectory() as temporary:
            target=Path(temporary)/'attempt'
            with self.assertRaises(SchemaxisError) as raised:adaptor.run(document(),target)
            self.assertEqual(raised.exception.fault.code,'NATIVE_ENVIRONMENT_UNAVAILABLE')
            self.assertFalse(json.loads((target/'result.json').read_text())['verified'])
