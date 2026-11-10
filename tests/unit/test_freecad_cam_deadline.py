"""CAM verification preserves caller cancellation and whole-operation deadlines."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from schemaxis.adaptors.freecad import cam_verify
from schemaxis.core.faults import SchemaxisError,Fault
from schemaxis.dispatch import execution_deadline


class CAMDeadlineTests(unittest.TestCase):
    def setUp(self):
        # These runner-boundary tests supply a valid finite plan. Native source
        # admission is independently covered; /unused is deliberately no file.
        plan=patch('schemaxis.adaptors.freecad.cam_evidence2.read',
                   return_value={'version':'schemaxis.freecad.cam.plan/2'})
        plan.start();self.addCleanup(plan.stop)

    def test_native_lifecycle_faults_keep_their_public_identity(self):
        for code in ('RUNNER_CANCELLED','RUNNER_TIMED_OUT','NATIVE_EXECUTION_FAILED'):
            error=SchemaxisError(Fault(code,'native boundary control','$','runner'))
            with self.subTest(code=code),patch.object(cam_verify,'executable',return_value='/native/freecadcmd'),patch.object(cam_verify,'runtime_archive',return_value=b'trusted'),patch.object(cam_verify,'SubprocessRunner') as worker:
                worker.return_value.side_effect=error
                with self.assertRaises(SchemaxisError) as caught:cam_verify.fresh_material(Path('/unused'))
                if code.startswith('RUNNER_'):self.assertIs(caught.exception,error)
                else:self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')

    def test_structured_native_lifecycle_receipt_is_preserved(self):
        for code in ('RUNNER_CANCELLED','RUNNER_TIMED_OUT'):
            class Native:
                def __init__(self,interpreter,workspace,timeout):self.workspace=workspace
                def __call__(self,source):
                    (self.workspace/'native-fault.json').write_text(json.dumps(Fault(code,'worker control','$','native').to_dict()))
            with self.subTest(code=code),patch.object(cam_verify,'executable',return_value='/native/freecadcmd'),patch.object(cam_verify,'runtime_archive',return_value=b'trusted'),patch.object(cam_verify,'SubprocessRunner',Native):
                with self.assertRaises(SchemaxisError) as caught:cam_verify.fresh_material(Path('/unused'))
                self.assertEqual(caught.exception.fault.code,code)

    def test_final_observation_cannot_publish_after_outer_deadline(self):
        clock=[100.]
        class Native:
            def __init__(self,interpreter,workspace,timeout):self.workspace=workspace
            def __call__(self,source):
                (self.workspace/'material.json').write_text('{"verified":true}')
                clock[0]+=2
        with patch('schemaxis.dispatch._clock',side_effect=lambda:clock[0]),patch.object(cam_verify,'executable',return_value='/native/freecadcmd'),patch.object(cam_verify,'runtime_archive',return_value=b'trusted'),patch.object(cam_verify,'SubprocessRunner',Native),execution_deadline(1):
            with self.assertRaises(SchemaxisError) as caught:cam_verify.fresh_material(Path('/unused'))
        self.assertEqual(caught.exception.fault.code,'RUNNER_TIMED_OUT')


if __name__=='__main__':unittest.main()
