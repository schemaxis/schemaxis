# Copyright (C) 2026 David L F Gaden
"""A bounded, real ParaView operation authored through an in-source dictionary."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from schemaxis.core.capabilities import CapabilityExtension
from schemaxis.core.contracts import Artifact
from schemaxis.core.executor import ProviderContext, ProviderRequest, ProviderResult
from schemaxis.core.extensions import validate_config
from schemaxis.core.faults import SchemaxisError, Fault
from schemaxis.core.replay import ReplayScript, connect
from schemaxis.core.series import SERIES_ARGUMENT, resolve_series
from schemaxis.adaptors.paraview.mvp.runners import PARAVIEW_OFFSCREEN, require_paraview
from schemaxis.core.runners import SubprocessRunner
from .slice_options import SLICE_OPTIONS, SLICE_COVERAGE
from .foam_options import FOAM_ARGUMENT


class SliceExport(CapabilityExtension):
    declaration = {
        "id": "paraview.slice_export",
        "contractVersion": "schemaxis.capability/0.1",
        "provider": "paraview",
        "kind": "action",
        "summary": "Slice a Wavelet or decomposed OpenFOAM case with reused geometry and verified publications",
        "inputs": {},
        "upstream": {"application": "ParaView", "reviewedVersion": "5.13.3",
                     "metadata": "native/slice-5.13.3.json", "notice": "native/ParaView-Copyright.txt"},
        "nativeProperties": SLICE_COVERAGE,
        "arguments": {
            "case": FOAM_ARGUMENT,
            **{name: option["argument"] for name, option in SLICE_OPTIONS.items()},
            "origin": {
                "type": "array", "items": {"type": "number"},
                "minItems": 3, "maxItems": 3, "default": [0.0, 0.0, 0.0],
                "summary": "A point on the slicing plane",
            },
            "normal": {
                "type": "array", "items": {"type": "number"},
                "minItems": 3, "maxItems": 3, "default": [1.0, 0.0, 0.0],
                "summary": "Nonzero plane normal; normalised with the effective value reported",
            },
            "sweep": {
                **SERIES_ARGUMENT,
                "summary": "Signed offsets from origin along the unit normal; declare a complete series (bounds are not inferred)",
            },
            "maxSlices": {
                "type": "integer", "minimum": 1, "maximum": 10000, "default": 1000,
                "summary": "Maximum sweep positions, checked before expansion and execution",
            },
            "outputDirectory": {
                "type": "string", "minLength": 1, "required": True,
                "summary": "New output directory; its parent must exist; existing paths are refused",
            },
            "timeout": {
                "type": "number", "minimum": 1, "default": 120.0,
                "summary": "Maximum execution time in seconds",
            },
        },
        "outputs": {},
        "effects": ["starts ParaView", "creates output directory", "writes geometry, replay and verification"],
        "faults": ["OUTPUT_EXISTS", "INVALID_OUTPUT_PATH", "INVALID_NORMAL", "EMPTY_GEOMETRY",
                   "DATA_NOT_READY", "VERIFICATION_FAILED", "DECLARATION_MISMATCH", "UNSUPPORTED_NATIVE_OPTION",
                   "INTERPRETER_NOT_FOUND", "INTERPRETER_UNUSABLE", "RUNNER_FAILED", "RUNNER_TIMED_OUT",
                   "EXPANSION_TOO_LARGE", "UNDER_SPECIFIED_SERIES", "OVER_SPECIFIED_SERIES",
                   "INCONSISTENT_SERIES", "INVALID_SLICE_POSITION", "MISSING_FIELD",
                   "INVALID_CASE", "INVALID_CAMERA", "INVALID_CASE_OPTIONS", "TIME_OUT_OF_TOLERANCE"],
    }

    def configure(self, config: Mapping[str, Any]) -> None:
        self.config = dict(config)
        normal = self.config["normal"]
        scale = max(abs(value) for value in normal)
        if scale == 0:
            raise SchemaxisError(Fault(
                "INVALID_NORMAL", "a plane normal cannot be zero", "paraview.slice_export.normal",
                "validation", observed={"value": normal}, recovery="supply a nonzero three-component vector",
            ))
        scaled = [value / scale for value in normal]
        length = math.sqrt(sum(value * value for value in scaled))
        self.normal = [value / length for value in scaled]
        self.sweep = None
        self.origins = []
        if "sweep" in self.config:
            self.sweep = resolve_series(self.config["sweep"],
                                        location="paraview.slice_export.sweep",
                                        limit=self.config["maxSlices"])
            self.origins = [[self.config["origin"][axis] + offset * self.normal[axis]
                             for axis in range(3)] for offset in self.sweep.positions]
            if not all(math.isfinite(value) for origin in self.origins for value in origin):
                raise SchemaxisError(Fault("INVALID_SLICE_POSITION", "resolved slice origins must be finite",
                                     "paraview.slice_export.sweep", "value-resolution",
                                     recovery="reduce the origin or sweep extent"))

    def execute(self, request: ProviderRequest, context: ProviderContext) -> ProviderResult:
        self.check_manifest(request.capability.document)
        operation = type(self)()
        operation.configure(validate_config(self.declaration, request.arguments))
        return operation.run(context.step_id)

    def run(self, step_id: str = "slice") -> ProviderResult:
        if "case" in self.config:
            from .foam_export import run_case
            return run_case(self.config, self.normal, step_id)
        directory = Path(self.config["outputDirectory"]).expanduser().absolute()
        # The entire publication directory is exclusive, including failed runs.
        # Never overwrite evidence from an earlier attempt.
        if directory.exists() or directory.is_symlink():
            raise SchemaxisError(Fault(
                "OUTPUT_EXISTS", "output directory already exists", str(directory), "execution",
                recovery="choose a new output directory; previous evidence is retained",
            ))
        interpreter = require_paraview()
        try:
            directory.mkdir(exist_ok=False)
        except OSError as error:
            raise SchemaxisError(Fault(
                "OUTPUT_EXISTS" if isinstance(error, FileExistsError) else "INVALID_OUTPUT_PATH",
                str(error), str(directory), "execution",
                recovery="choose a new directory under an existing writable parent",
            )) from error
        replay = ReplayScript()
        replay.add("paraview.simple", "Wavelet", {}, "steps.source.outputs.data")
        replay.add("paraview.simple", "Slice", {
            "Input": connect("steps.source.outputs.data")}, "steps.slice.outputs.data")
        target = connect("steps.slice.outputs.data")
        replay.record_assignment(target, "SliceType", "Plane")
        replay.record_assignment(target, "SliceType.Origin", self.config["origin"])
        replay.record_assignment(target, "SliceType.Normal", self.normal)
        native_options = {option["pythonName"]: (option["values"][self.config[name]]
                          if "values" in option else int(self.config[name]))
                          for name, option in SLICE_OPTIONS.items()}
        replay.add("__main__", "check_native_options", {"proxy": target,
                   "properties": native_options, "directory": str(directory)},
                   "steps.options.outputs.checked")
        for name, option in SLICE_OPTIONS.items():
            value = self.config[name]
            native_value = option["values"][value] if "values" in option else int(value)
            replay.record_assignment(target, option["pythonName"], native_value)
        publication_arguments = {
            "proxy": target, "normal": self.normal,
            "directory": str(directory), "source_proxy": connect("steps.source.outputs.data"),
            "options": {name: self.config[name] for name in SLICE_OPTIONS}}
        if self.sweep is None:
            publication_arguments["origin"] = self.config["origin"]
            function = "export_verified_slice"
        else:
            publication_arguments.update(origins=self.origins, resolution=self.sweep.to_dict())
            function = "export_verified_sweep"
        replay.add("__main__", function, publication_arguments, "steps.export.outputs.evidence")
        source = Path(__file__).with_name("runtime.py").read_text(encoding="utf-8") + "\n" + replay.emit()
        runner = SubprocessRunner(interpreter, directory, PARAVIEW_OFFSCREEN, self.config["timeout"])
        try:
            report = runner(source)
        except SchemaxisError as error:
            receipt = directory / "verification.json"
            if receipt.is_file():
                evidence = json.loads(receipt.read_text(encoding="utf-8"))
                if "fault" in evidence:
                    fault = evidence["fault"]
                    raise SchemaxisError(Fault(
                        fault["code"], fault["message"], str(receipt), "verification",
                        observed={**fault["observed"], "submission": error.fault.to_dict()},
                        recovery="inspect the requested plane and retained replay; an empty slice need not indicate corruption",
                    )) from error
            raise
        receipt = directory / "verification.json"
        if not receipt.is_file():
            raise SchemaxisError(Fault("VERIFICATION_FAILED", "ParaView returned no verification receipt",
                                 str(receipt), "verification"))
        evidence = json.loads(receipt.read_text(encoding="utf-8"))
        if evidence.get("verified") is not True:
            raise SchemaxisError(Fault("VERIFICATION_FAILED", "geometry verification did not succeed",
                                 str(receipt), "verification", observed=evidence))
        artifacts = []
        extension = "vtu" if self.config["crinkle"] else "vtp"
        geometry_directories = [("geometry", directory)] if self.sweep is None else [
            (f"geometry-{index:04d}", directory / f"slice-{index:04d}")
            for index in range(len(self.origins))]
        if self.sweep is not None and (
            evidence.get("completed") != len(self.origins) or
            len(evidence.get("slices", [])) != len(self.origins) or
            any(item.get("verified") is not True for item in evidence.get("slices", []))
        ):
            raise SchemaxisError(Fault("VERIFICATION_FAILED", "the sweep receipt is incomplete",
                                 str(receipt), "verification", observed=evidence))
        publications = [(name, root / f"slice.{extension}", f"application/vnd.vtk.{extension}", "output")
                        for name, root in geometry_directories]
        if self.sweep is not None:
            publications += [(f"verification-{index:04d}", root / "verification.json", "application/json", "verification")
                             for index, (_, root) in enumerate(geometry_directories)]
        publications += [
            ("replay", Path(report.script_path), "text/x-python", "replay"),
            ("verification", receipt, "application/json", "verification"),
        ]
        from schemaxis.publication_metadata import finalise, publish_artifacts, receipt_artifacts
        finalise(directory)
        # Native geometry and explicitly returned replay/evidence outputs all have companions.
        native = receipt_artifacts(directory)
        publish_artifacts(directory, native + [{'file': str(path), 'kind': role}
                                              for _, path, _, role in publications if role != 'output'])
        for name, path, media_type, role in publications:
            artifacts.append(Artifact(
                f"{step_id}-{name}", path.as_uri(), media_type, role,
                hashlib.sha256(path.read_bytes()).hexdigest(), step_id,
            ))
        return ProviderResult(observations={"verification": evidence, "submission": report.to_dict()},
                              artifacts=tuple(artifacts))
