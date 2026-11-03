# Copyright (C) 2026 David L F Gaden
from __future__ import annotations

import unittest

from schemaxis.core.replay import ReplayScript, ReplayStatus, ReplayValidationError
from schemaxis.core.references import ParsedReference


class ReplayTests(unittest.TestCase):
    def test_emits_ordered_imports_calls_and_symbolic_assignments(self) -> None:
        replay = ReplayScript()
        replay.record_call(
            "paraview.simple", "OpenDataFile",
            {"filename": "a 'quote'\nand \\ slash.vtk"},
            "resources.input.outputs.dataset",
        )
        replay.record_call(
            "paraview.simple", "Contour",
            {"Input": "source", "Isosurfaces": 3, "ComputeNormals": True},
            {"ref": "steps.contour.outputs.dataset"},
        )

        self.assertEqual(
            replay.emit(),
            "import paraview.simple\n"
            "\n"
            "schemaxis_results = {}\n"
            "schemaxis_results['resources.input.outputs.dataset'] = "
            "paraview.simple.OpenDataFile(filename=\"a 'quote'\\nand \\\\ slash.vtk\")\n"
            "schemaxis_results['steps.contour.outputs.dataset'] = "
            "paraview.simple.Contour(Input='source', Isosurfaces=3, ComputeNormals=True)\n",
        )

    def test_executes_exact_emitted_source_through_injected_runner(self) -> None:
        replay = ReplayScript()
        replay.record_call("fake.application", "make", {"label": "line 1\nline 2"},
                           "steps.make.outputs.value")
        expected = replay.emit()
        submitted = []

        def runner(source: str) -> str:
            submitted.append(source)
            return "runner evidence"

        outcome = replay.execute(runner)
        self.assertEqual(submitted, [expected])
        self.assertEqual(outcome.submitted_source, expected)
        self.assertEqual(outcome.events, (ReplayStatus.SUBMITTED, ReplayStatus.SUCCEEDED))
        self.assertTrue(outcome.succeeded)
        self.assertEqual(outcome.runner_result, "runner evidence")

    def test_runner_failure_is_retained_and_not_reported_as_success(self) -> None:
        replay = ReplayScript()
        replay.record_call("fake.application", "fail", {}, "steps.fail.outputs.value")

        def runner(source: str) -> None:
            raise RuntimeError("application unavailable")

        outcome = replay.execute(runner)
        self.assertTrue(outcome.submitted)
        self.assertEqual(outcome.status, ReplayStatus.FAILED)
        self.assertEqual(outcome.events, (ReplayStatus.SUBMITTED, ReplayStatus.FAILED))
        self.assertEqual(outcome.failure_type, "RuntimeError")
        self.assertEqual(outcome.failure_message, "application unavailable")
        self.assertIsNone(outcome.runner_result)

    def test_rejects_identifiers_references_and_nonprimitive_values(self) -> None:
        invalid = [
            ("os;system", "call", {}, "steps.x.outputs.value"),
            ("safe.module", "thing.value", {}, "steps.x.outputs.value"),
            ("safe.module", "call", {"bad-name": 1}, "steps.x.outputs.value"),
            ("safe.module", "call", {"value": {1, 2}}, "steps.x.outputs.value"),
            ("safe.module", "call", {"value": {1: "a"}}, "steps.x.outputs.value"),
            ("safe.module", "call", {"value": [[[[[[[[[1]]]]]]]]]}, "steps.x.outputs.value"),
            ("safe.module", "call", {"value": [1, object()]}, "steps.x.outputs.value"),
            ("safe.module", "call", {"value": float("nan")}, "steps.x.outputs.value"),
            ("safe.module", "call", {}, "steps.x.__class__.value"),
            ("safe.class", "call", {}, "steps.x.outputs.value"),
            ("safe.module", "import", {}, "steps.x.outputs.value"),
            ("safe.module", "call", {"class": 1}, "steps.x.outputs.value"),
        ]
        for module, function, arguments, result in invalid:
            with self.subTest(module=module, function=function, result=result):
                with self.assertRaises(ReplayValidationError):
                    ReplayScript().record_call(module, function, arguments, result)


    def test_renders_lists_and_dictionaries_an_application_needs(self) -> None:
        # A point, a colour and an image size are all lists in ParaView's API.
        replay = ReplayScript()
        replay.record_call(
            "app", "place",
            {"origin": [1, 2.5, -3], "size": [800, 600], "options": {"legend": True}},
            "steps.slice.outputs.view",
        )
        self.assertIn(
            "app.place(origin=[1, 2.5, -3], size=[800, 600], options={'legend': True})",
            replay.emit(),
        )

    def test_rejects_hostile_primitive_subclasses(self) -> None:
        class HostileInt(int):
            def __str__(self) -> str:
                return "0); dangerous_call("

        class HostileString(str):
            def __repr__(self) -> str:
                return "dangerous_call()"

        for value in (HostileInt(1), HostileString("safe")):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(ReplayValidationError):
                    ReplayScript().record_call(
                        "safe.module", "call", {"value": value},
                        "steps.x.outputs.value",
                    )

    def test_revalidates_direct_parsed_reference(self) -> None:
        forged = ParsedReference("steps", "x", "value; dangerous_call()")
        with self.assertRaises(ReplayValidationError):
            ReplayScript().record_call("safe.module", "call", {}, forged)

    def test_normal_return_is_not_scientific_verification(self) -> None:
        replay = ReplayScript()
        replay.record_call("safe.module", "call", {}, "steps.x.outputs.value")
        outcome = replay.execute(lambda source: 3)
        self.assertEqual(outcome.status, ReplayStatus.SUCCEEDED)
        self.assertEqual(outcome.runner_result, 3)


class PropertyAssignmentTests(unittest.TestCase):
    def test_assignments_preserve_order_and_execute_on_nested_objects(self):
        from types import SimpleNamespace
        from schemaxis.core.replay import connect
        replay = ReplayScript()
        replay.add("types", "SimpleNamespace", {}, "steps.slice.outputs.data")
        replay.add("types", "SimpleNamespace", {}, "steps.plane.outputs.data")
        replay.record_assignment(connect("steps.slice.outputs.data"), "SliceType",
                                 connect("steps.plane.outputs.data"))
        origin = [1, 2, 3]
        replay.record_assignment(connect("steps.slice.outputs.data"), "SliceType.Origin", origin)
        origin[0] = 99
        namespace = {}
        exec(replay.emit(), namespace)
        self.assertEqual(namespace["schemaxis_results"]["steps.slice.outputs.data"].SliceType.Origin, [1, 2, 3])

    def test_invalid_paths_and_missing_targets_are_rejected(self):
        from schemaxis.core.replay import connect
        replay = ReplayScript()
        replay.add("types", "SimpleNamespace", {}, "steps.slice.outputs.data")
        for path in ("__dict__", "a[0]", "a()", "a..b", "a.b.c.d.e", "a.class"):
            with self.subTest(path=path), self.assertRaises(ReplayValidationError):
                replay.record_assignment(connect("steps.slice.outputs.data"), path, 1)
        with self.assertRaises(ReplayValidationError):
            replay.record_assignment(connect("steps.missing.outputs.data"), "Origin", [0, 0, 0])


if __name__ == "__main__":
    unittest.main()
