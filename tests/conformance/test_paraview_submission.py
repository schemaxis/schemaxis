"""Evidence that emitted replay source runs in a real ParaView.

This test is skipped unless a ParaView is discoverable, so the suite keeps its
no-dependency property. When one is present it proves the whole submission
path: emitted source, a connected pipeline, an offscreen render, and files on
disk. It does not verify that the image is correct; existence is not proof.

Point it at an installation with SCHEMAXIS_PARAVIEW_ROOTS, or put pvbatch on PATH.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from schemaxis.core.replay import ReplayScript, ReplayStatus, connect
from schemaxis.core.runners import PARAVIEW_OFFSCREEN, SubprocessRunner, find_paraview


def _paraview():
    for interpreter in find_paraview():
        try:
            return interpreter.probe()
        except Exception:  # An install that cannot start is not a usable one.
            continue
    return None


PARAVIEW = _paraview()


@unittest.skipIf(PARAVIEW is None, "no ParaView interpreter discoverable")
class ParaViewSubmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def runner(self) -> SubprocessRunner:
        return SubprocessRunner(
            PARAVIEW, self.workspace, arguments=PARAVIEW_OFFSCREEN, timeout=600
        )

    def test_a_connected_pipeline_produces_geometry_and_an_image(self) -> None:
        geometry = self.workspace / "isosurface.vtp"
        image = self.workspace / "contour.png"

        replay = ReplayScript()
        replay.record_call("paraview.simple", "Wavelet", {}, "steps.source.outputs.data")
        replay.record_call("paraview.simple", "Contour", {
            "Input": connect("steps.source.outputs.data"),
            "ContourBy": ["POINTS", "RTData"],
            "Isosurfaces": [100.0, 150.0],
        }, "steps.isosurface.outputs.data")
        replay.record_call("paraview.simple", "SaveData", {
            "filename": str(geometry), "proxy": connect("steps.isosurface.outputs.data"),
        }, "steps.write-geometry.outputs.artifact")
        replay.record_call("paraview.simple", "GetActiveViewOrCreate", {
            "viewtype": "RenderView"}, "steps.view.outputs.view")
        replay.record_call("paraview.simple", "Show", {
            "proxy": connect("steps.isosurface.outputs.data"),
            "view": connect("steps.view.outputs.view"),
        }, "steps.display.outputs.display")
        replay.record_call("paraview.simple", "ColorBy", {
            "rep": connect("steps.display.outputs.display"),
            "value": ["POINTS", "RTData"],
        }, "steps.colour.outputs.applied")
        replay.record_call("paraview.simple", "ResetCamera", {}, "steps.camera.outputs.applied")
        replay.record_call("paraview.simple", "SaveScreenshot", {
            "filename": str(image),
            "viewOrLayout": connect("steps.view.outputs.view"),
            "ImageResolution": [800, 600],
        }, "steps.write-image.outputs.artifact")

        outcome = replay.execute(self.runner())
        self.assertEqual(
            outcome.status, ReplayStatus.SUCCEEDED,
            msg=None if outcome.fault is None else outcome.fault.observed.get("stderr", ""),
        )
        report = outcome.runner_result
        self.assertEqual(report.exit_code, 0)
        # The retained script is the artifact that makes the run reproducible.
        self.assertEqual(
            Path(report.script_path).read_text(encoding="utf-8"), outcome.submitted_source
        )
        self.assertTrue(geometry.is_file(), "no geometry was written")
        self.assertTrue(image.is_file(), "no image was written")
        self.assertGreater(image.stat().st_size, 1024)
        self.assertEqual(image.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_nested_slice_properties_can_be_reassigned(self) -> None:
        replay = ReplayScript()
        replay.add("paraview.simple", "Wavelet", {}, "steps.source.outputs.data")
        replay.add("paraview.simple", "Slice", {
            "Input": connect("steps.source.outputs.data")}, "steps.slice.outputs.data")
        target = connect("steps.slice.outputs.data")
        replay.record_assignment(target, "SliceType", "Plane")
        for index, x in enumerate([-5.0, 5.0]):
            replay.record_assignment(target, "SliceType.Origin", [x, 0.0, 0.0])
            replay.record_assignment(target, "SliceType.Normal", [1.0, 0.0, 0.0])
            replay.add("paraview.simple", "UpdatePipeline", {"proxy": target},
                       f"steps.update{index}.outputs.done")
            replay.add("paraview.simple", "SaveData", {
                "filename": str(self.workspace / f"slice{index}.vtp"), "proxy": target},
                f"steps.write{index}.outputs.done")
        outcome = replay.execute(self.runner())
        self.assertTrue(outcome.succeeded, outcome.failure_message)
        for index in range(2):
            self.assertTrue((self.workspace / f"slice{index}.vtp").is_file())

    def test_a_failing_call_returns_the_interpreter_diagnosis_as_a_fault(self) -> None:
        replay = ReplayScript()
        replay.record_call(
            "paraview.simple", "NoSuchFilter", {}, "steps.broken.outputs.data"
        )
        outcome = replay.execute(self.runner())
        self.assertEqual(outcome.status, ReplayStatus.FAILED)
        self.assertEqual(outcome.fault.code, "RUNNER_FAILED")
        self.assertIn("NoSuchFilter", outcome.fault.observed["stderr"])
        self.assertTrue(Path(outcome.fault.location).is_file())

    def test_a_connection_to_an_unproduced_result_fails_before_submission(self) -> None:
        from schemaxis.core.replay import ReplayValidationError

        replay = ReplayScript()
        with self.assertRaises(ReplayValidationError):
            replay.record_call("paraview.simple", "Slice", {
                "Input": connect("steps.never-made.outputs.data")
            }, "steps.slice.outputs.data")


if __name__ == "__main__":
    unittest.main()
