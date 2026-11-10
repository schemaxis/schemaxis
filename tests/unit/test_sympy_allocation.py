"""Native-unavailable boundary of SymPy real-root isolation; the host never imports SymPy."""
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

from schemaxis.adaptors.sympy import adaptor as a
from schemaxis.core.faults import SchemaxisError

DOCUMENT = {'version': a.VERSION, 'operation': a.OPERATION, 'coefficients': ['1', '0', '-2'], 'maximumIntervalWidth': '1/1000'}


def launcher_without_site(directory):
    """An executable running this Python with `-S`, so that site-packages (and any SymPy) is not importable."""
    path = Path(directory) / 'python-without-site'
    path.write_text('#!/bin/sh\nexec "%s" -S "$@"\n' % sys.executable)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@unittest.skipUnless(os.name == 'posix', 'qualified SymPy process caps require POSIX')
class UnavailableRuntimeTests(unittest.TestCase):
    def run_without_sympy(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'run'
            with self.assertRaises(SchemaxisError) as caught:
                a.run(DOCUMENT, target, executable=str(launcher_without_site(directory)), timeout=30)
            record = json.loads((target / 'result.json').read_text())
            return caught.exception.fault, record, sorted(p.name for p in target.iterdir()), \
                (json.loads((target / 'compute-fault.json').read_text()) if (target / 'compute-fault.json').exists() else None)

    def test_missing_sympy_is_a_structured_unavailable_fault_not_a_generic_runner_failure(self):
        fault, record, _, native = self.run_without_sympy()
        self.assertEqual(fault.code, 'SYMPY_RUNTIME_UNAVAILABLE')
        self.assertEqual(fault.location, '$.runtime')
        self.assertIn('SymPy ' + a.REQUIRED, fault.recovery)
        self.assertEqual(record['status'], 'failed')
        self.assertIs(record['verified'], False)
        self.assertEqual(record['fault']['code'], 'SYMPY_RUNTIME_UNAVAILABLE')
        self.assertEqual(native['code'], 'SYMPY_RUNTIME_UNAVAILABLE')

    def test_unavailable_is_distinct_from_unsupported_and_leaks_no_workstation_path(self):
        fault, record, _, _ = self.run_without_sympy()
        self.assertNotEqual(fault.code, 'SYMPY_UNSUPPORTED_RUNTIME')
        self.assertNotIn(tempfile.gettempdir(), json.dumps(fault.to_dict()))
        self.assertNotIn('Traceback', json.dumps(record))

    def test_no_verified_publication_is_left_behind(self):
        _, _, names, _ = self.run_without_sympy()
        for name in ('real-roots.csv', 'roots-summary.json', 'roots-verification.json', 'verification.json'):
            self.assertNotIn(name, names)


class RefusalRecoveryTests(unittest.TestCase):
    def refuse(self, code, location='$.coefficients'):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            (directory / 'compute-fault.json').write_text(json.dumps(
                {'code': code, 'message': 'native said so', 'location': location, 'details': {}, 'pid': 1}))
            with self.assertRaises(SchemaxisError) as caught:
                a.native_refusal(directory, 'compute', SchemaxisError(a.oracle.Fault('RUNNER_FAILED', 'x', 'y', 'pipeline')))
            return caught.exception.fault

    def test_every_accepted_native_refusal_has_a_stable_code_and_actionable_recovery(self):
        for code in ('SYMPY_UNSUPPORTED_RUNTIME', 'SYMPY_RUNTIME_UNAVAILABLE', 'SYMPY_NATIVE_RESULT_INVALID'):
            fault = self.refuse(code)
            self.assertEqual(fault.code, code)
            self.assertTrue(fault.recovery, code)

    def test_host_accepted_input_refused_by_native_is_a_verification_failure(self):
        for code in ('SYMPY_INVALID_CONTRACT', 'SYMPY_RESOURCE_LIMIT'):
            self.assertEqual(self.refuse(code).code, 'VERIFICATION_FAILED')

    def test_unknown_native_refusal_code_is_malformed_not_trusted(self):
        self.assertEqual(self.refuse('SYMPY_MADE_UP').code, 'VERIFICATION_FAILED')


if __name__ == '__main__':
    unittest.main()
