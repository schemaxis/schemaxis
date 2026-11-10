"""Native fault classification: unavailable, unsupported and failed stay distinct."""
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptors.cantera import adaptor
from schemaxis.core.faults import Fault, SchemaxisError

ROOT = Path(__file__).resolve().parents[2]


def document():
    return json.loads((ROOT/'examples/schemaxis/cantera-minimal.json').read_text())


def interpreter(temp,name,module):
    """A Python launcher that sees a stand-in `cantera` module and no real native code."""
    package = Path(temp)/(name+'-modules'); package.mkdir()
    (package/'cantera.py').write_text(module)
    launcher = Path(temp)/name
    launcher.write_text(f'#!/bin/sh\nPYTHONPATH={package} exec {sys.executable} "$@"\n')
    launcher.chmod(launcher.stat().st_mode|stat.S_IXUSR)
    return str(launcher)


def run_fault(temp,name,executable):
    directory = Path(temp)/name
    with unittest.TestCase().assertRaises(SchemaxisError) as caught:
        adaptor.run(document(),directory,executable=executable,timeout=60)
    return directory,caught.exception.fault


class CanteraNativeFaultTests(unittest.TestCase):
    def test_interpreter_without_cantera_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temp:
            python = interpreter(temp,'absent',"raise ImportError(\"No module named 'cantera'\")\n")
            directory,fault = run_fault(temp,'run',python)
            self.assertEqual(fault.code,'NATIVE_UNAVAILABLE')
            self.assertIn('--cantera',fault.recovery)
            self.assertEqual(json.loads((directory/'result.json').read_text())['fault']['code'],'NATIVE_UNAVAILABLE')
            self.assertFalse((directory/'results.csv').exists())

    def test_other_cantera_release_is_unsupported_not_failed(self):
        with tempfile.TemporaryDirectory() as temp:
            python = interpreter(temp,'old',"__version__ = '3.1.1'\n")
            directory,fault = run_fault(temp,'run',python)
            self.assertEqual(fault.code,'UNSUPPORTED_RUNTIME')
            self.assertEqual(fault.observed['version'],'3.1.1')
            self.assertIn('3.2',fault.recovery)

    def test_broken_import_is_not_reported_as_absent(self):
        with tempfile.TemporaryDirectory() as temp:
            python = interpreter(temp,'broken',"raise RuntimeError('shared library mismatch')\n")
            _,fault = run_fault(temp,'run',python)
            self.assertEqual(fault.code,'NATIVE_EXECUTION_FAILED')
            self.assertIn('shared library mismatch',fault.message)
            self.assertIn('build.stderr',fault.recovery)

    def record_fault(self,temp,content):
        def fake(command,directory,stage,timeout,environment=None):
            Path(directory,'native-fault.json').write_text(content)
            raise SchemaxisError(Fault('RUNNER_FAILED','worker exited',stage,'pipeline'))
        with patch.object(adaptor,'execute',fake):
            return run_fault(temp,'run','/bin/true' if os.path.isfile('/bin/true') else sys.executable)[1]

    def test_worker_fault_record_is_validated(self):
        with tempfile.TemporaryDirectory() as temp:
            honest = self.record_fault(temp,json.dumps({'code':'UNSUPPORTED_STATE','message':'too hot'}))
            self.assertEqual((honest.code,honest.message),('UNSUPPORTED_STATE','too hot'))
            self.assertIn('dilute',honest.recovery)
        for name,content in (('unknown',json.dumps({'code':'ARBITRARY_CODE','message':'x'})),
                             ('malformed','{not json'),('list','[]'),
                             ('message',json.dumps({'code':'UNSUPPORTED_STATE','message':3}))):
            with self.subTest(name),tempfile.TemporaryDirectory() as temp:
                fault = self.record_fault(temp,content)
                self.assertEqual(fault.code,'NATIVE_EXECUTION_FAILED')
                self.assertIn('malformed',fault.message)
                self.assertIn('build.stderr',fault.recovery)

    def test_unqualified_runtime_still_cannot_verify(self):
        with tempfile.TemporaryDirectory() as temp:
            run_fault(temp,'run',interpreter(temp,'old',"__version__ = '3.1.1'\n"))
            with self.assertRaises(SchemaxisError) as caught: adaptor.verify(Path(temp)/'run')
            self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')


if __name__ == '__main__': unittest.main()
