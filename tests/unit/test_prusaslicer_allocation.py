"""Host checks that PrusaSlicer stages are gated before the slice is launched.

A fake console executable stands in for the native application; these tests
exercise the adaptor's stage ordering and faults, not native slicing.
"""
import json
from pathlib import Path
import tempfile
import unittest

from schemaxis.adaptors.prusaslicer import adaptor
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
BOX = ROOT/'examples/schemaxis/prusaslicer-box.stl'

SCRIPT = """#!/bin/sh
echo "$@" >> '{log}'
case " $* " in
  *" --help "*) echo '{identity}'; exit 0;;
  *" --info "*) cat <<'INFO'
{info}
INFO
    exit 0;;
  *) exit 0;;
esac
"""
# Matches the independent analysis of the 24 x 16 x 10 mm fixture box.
GOOD_INFO = """[model.stl]
size_x = 24.000000
size_y = 16.000000
size_z = 10.000000
min_x = 0.000000
min_y = 0.000000
min_z = 0.000000
max_x = 24.000000
max_y = 16.000000
max_z = 10.000000
number_of_facets = 12
manifold = yes
number_of_parts = 1
volume = 3840.000000"""


def document():
    value = json.loads((ROOT/'examples/schemaxis/prusaslicer-pla.json').read_text())
    value['model']['file'] = str(BOX)
    return value


class StageGateTests(unittest.TestCase):
    def fake(self, directory, identity, info=GOOD_INFO):
        log = Path(directory)/'invocations.log'
        executable = Path(directory)/'prusa-slicer'
        executable.write_text(SCRIPT.format(log=log, identity=identity, info=info))
        executable.chmod(0o755)
        return executable, log

    def attempt(self, directory, executable):
        target = Path(directory)/'attempt'
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.run(document(), target, executable=str(executable), timeout=60)
        return target, caught.exception.fault

    def calls(self, log):
        return log.read_text().splitlines() if log.exists() else []

    def test_unsupported_runtime_is_refused_before_any_other_native_stage(self):
        with tempfile.TemporaryDirectory() as temporary:
            executable, log = self.fake(temporary, 'PrusaSlicer-2.10.0 based on Slic3r')
            target, fault = self.attempt(temporary, executable)
            self.assertEqual(fault.code, 'UNSUPPORTED_RUNTIME', fault.to_dict())
            self.assertEqual(fault.observed.get('stage'), 'version')
            self.assertEqual(self.calls(log), ['--help'])
            result = json.loads((target/'result.json').read_text())
            self.assertEqual((result['status'], result['verified'], result['fault']['code']),
                             ('failed', False, 'UNSUPPORTED_RUNTIME'))
            self.assertFalse((target/'model.gcode').exists())
            self.assertFalse((target/'info.stdout').exists())

    def test_non_slicer_output_is_unsupported_not_a_runner_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            executable, log = self.fake(temporary, 'usage: something else')
            _, fault = self.attempt(temporary, executable)
            self.assertEqual(fault.code, 'UNSUPPORTED_RUNTIME', fault.to_dict())
            self.assertEqual(len(self.calls(log)), 1)

    def test_native_model_readback_mismatch_stops_before_slicing(self):
        with tempfile.TemporaryDirectory() as temporary:
            executable, log = self.fake(temporary, 'PrusaSlicer-2.9.6+UNKNOWN based on Slic3r',
                                        GOOD_INFO.replace('size_x = 24.000000', 'size_x = 99.000000'))
            target, fault = self.attempt(temporary, executable)
            self.assertEqual(fault.code, 'VERIFICATION_FAILED', fault.to_dict())
            self.assertEqual(fault.observed.get('stage'), 'info')
            calls = self.calls(log)
            self.assertEqual(len(calls), 2, calls)
            self.assertFalse(any('--export-gcode' in call for call in calls))
            self.assertFalse((target/'model.gcode').exists())

    def test_matching_runtime_and_readback_proceed_to_the_slice_stage(self):
        with tempfile.TemporaryDirectory() as temporary:
            executable, log = self.fake(temporary, 'PrusaSlicer-2.9.6+UNKNOWN based on Slic3r')
            _, fault = self.attempt(temporary, executable)
            # The fake writes no G-code: the exit-0 refusal remains its own fault.
            self.assertEqual(fault.code, 'NATIVE_EXECUTION_FAILED', fault.to_dict())
            self.assertEqual(fault.observed.get('stage'), 'slice')
            self.assertTrue(any('--export-gcode' in call for call in self.calls(log)))


if __name__ == '__main__':
    unittest.main()
