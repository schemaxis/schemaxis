# Copyright (C) 2026 David L F Gaden
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

from schemaxis.core.faults import SchemaxisError
from schemaxis.core.replay import ReplayScript, ReplayStatus
from schemaxis.core.runners import (
    ROOTS_VARIABLE, Interpreter, SubprocessRunner, find_paraview, require_paraview,
)


HOST = Interpreter("python", sys.executable, None)


class SubmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name) / "replays"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def runner(self, **keywords) -> SubprocessRunner:
        return SubprocessRunner(HOST, self.workspace, **keywords)

    def test_the_retained_script_is_exactly_what_was_submitted(self) -> None:
        source = "print('hello')\n"
        report = self.runner()(source)
        self.assertEqual(report.exit_code, 0)
        self.assertEqual(Path(report.script_path).read_text(encoding="utf-8"), source)
        self.assertEqual(report.stdout.strip(), "hello")

    def test_identical_source_names_the_same_script(self) -> None:
        first = self.runner()("print(1)\n")
        second = self.runner()("print(1)\n")
        self.assertEqual(first.script_path, second.script_path)
        self.assertNotEqual(first.script_path, self.runner()("print(2)\n").script_path)

    def test_a_nonzero_exit_is_a_fault_carrying_the_output_and_the_script(self) -> None:
        with self.assertRaises(SchemaxisError) as caught:
            self.runner()("import sys\nsys.stderr.write('boom')\nsys.exit(3)\n")
        fault = caught.exception.fault
        self.assertEqual(fault.code, "RUNNER_FAILED")
        self.assertEqual(fault.observed["exitCode"], 3)
        self.assertIn("boom", fault.observed["stderr"])
        self.assertTrue(Path(fault.location).is_file())

    def test_a_timeout_is_a_distinct_retryable_fault(self) -> None:
        with self.assertRaises(SchemaxisError) as caught:
            self.runner(timeout=0.5)("import time\ntime.sleep(30)\n")
        self.assertEqual(caught.exception.fault.code, "RUNNER_TIMED_OUT")
        self.assertTrue(caught.exception.fault.retryable)

    def test_timeout_with_output_remains_json_safe(self) -> None:
        import json
        with self.assertRaises(SchemaxisError) as caught:
            self.runner(timeout=0.5)("import time\nprint('started', flush=True)\ntime.sleep(30)\n")
        fault = caught.exception.fault
        self.assertEqual(fault.code, "RUNNER_TIMED_OUT")
        self.assertIn("started", fault.observed["stdout"])
        json.dumps(fault.to_dict())

    def test_an_unusable_executable_is_reported_before_anything_runs(self) -> None:
        broken = SubprocessRunner(Interpreter("python", "/no/such/interpreter"), self.workspace)
        with self.assertRaises(SchemaxisError) as caught:
            broken("print(1)\n")
        self.assertEqual(caught.exception.fault.code, "INTERPRETER_UNUSABLE")

    def test_the_environment_may_be_extended(self) -> None:
        report = self.runner(environment={"SCHEMAXIS_TEST_MARKER": "present"})(
            "import os\nprint(os.environ['SCHEMAXIS_TEST_MARKER'])\n"
        )
        self.assertEqual(report.stdout.strip(), "present")

    def test_the_report_is_json_safe(self) -> None:
        import json
        envelope = self.runner()("print('x')\n").to_dict()
        self.assertEqual(json.loads(json.dumps(envelope)), envelope)


class ReplayIntegrationTests(unittest.TestCase):
    """The runner is what ReplayScript.execute was designed to be given."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def script(self, function: str) -> ReplayScript:
        replay = ReplayScript()
        replay.record_call("json", function, {"obj": [1, 2], "separators": [",", ":"]},
                           "steps.encode.outputs.text")
        return replay

    def test_emitted_source_runs_in_a_real_interpreter(self) -> None:
        outcome = self.script("dumps").execute(SubprocessRunner(HOST, self.workspace))
        self.assertEqual(outcome.status, ReplayStatus.SUCCEEDED)
        self.assertEqual(outcome.runner_result.exit_code, 0)
        self.assertEqual(
            Path(outcome.runner_result.script_path).read_text(encoding="utf-8"),
            outcome.submitted_source,
        )

    def test_a_failing_interpreter_keeps_the_structured_fault(self) -> None:
        outcome = self.script("no_such_function").execute(SubprocessRunner(HOST, self.workspace))
        self.assertEqual(outcome.status, ReplayStatus.FAILED)
        self.assertIsNotNone(outcome.fault)
        self.assertEqual(outcome.fault.code, "RUNNER_FAILED")
        self.assertIn("AttributeError", outcome.fault.observed["stderr"])
        self.assertTrue(outcome.submitted)


class DiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.previous = os.environ.pop(ROOTS_VARIABLE, None)

    def tearDown(self) -> None:
        if self.previous is None:
            os.environ.pop(ROOTS_VARIABLE, None)
        else:
            os.environ[ROOTS_VARIABLE] = self.previous
        self.temporary.cleanup()

    def plant(self, relative: str) -> Path:
        executable = self.root / relative
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
        return executable

    def test_an_installation_and_a_superbuild_are_both_found(self) -> None:
        installed = self.plant("install-a/bin/pvbatch")
        built = self.plant("source-b/build-v5.13.3/install/bin/pvbatch")
        found = find_paraview([self.root / "install-a", self.root / "source-b"], search_path=False)
        self.assertEqual(
            sorted(item.executable for item in found),
            sorted([str(installed), str(built)]),
        )

    def test_roots_may_come_from_the_environment(self) -> None:
        planted = self.plant("install-a/bin/pvbatch")
        os.environ[ROOTS_VARIABLE] = str(self.root / "install-a")
        self.assertEqual(find_paraview(search_path=False)[0].executable, str(planted))

    def test_the_same_executable_is_not_reported_twice(self) -> None:
        self.plant("install-a/bin/pvbatch")
        root = self.root / "install-a"
        self.assertEqual(len(find_paraview([root, root, root / "bin" / "pvbatch"], search_path=False)), 1)

    def test_a_non_executable_file_is_not_an_interpreter(self) -> None:
        planted = self.plant("install-a/bin/pvbatch")
        planted.chmod(0o644)
        self.assertEqual(find_paraview([self.root / "install-a"], search_path=False), ())

    def test_a_missing_interpreter_says_where_it_looked(self) -> None:
        with self.assertRaises(SchemaxisError) as caught:
            require_paraview([self.root / "nowhere"], probe=False)
        fault = caught.exception.fault
        self.assertEqual(fault.code, "INTERPRETER_NOT_FOUND")
        self.assertIn(ROOTS_VARIABLE, fault.recovery)

    def test_an_interpreter_that_reports_no_version_is_unusable(self) -> None:
        self.plant("install-a/bin/pvbatch")
        with self.assertRaises(SchemaxisError) as caught:
            require_paraview([self.root / "install-a"])
        self.assertEqual(caught.exception.fault.code, "INTERPRETER_UNUSABLE")


if __name__ == "__main__":
    unittest.main()
