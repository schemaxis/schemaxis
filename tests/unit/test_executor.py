# Copyright (C) 2026 David L F Gaden
import json
from pathlib import Path
import sys
import types
import unittest

from schemaxis.core.catalogue import CapabilityRecord, Catalogue
from schemaxis.core.contracts import Artifact, DataHandle, LogicalType, Reference, Representation
from schemaxis.core.executor import (
    CLOSED_HANDLE, NOT_YET_PRODUCED, TYPE_MISMATCH, UNKNOWN_REFERENCE,
    NO_EXECUTED_WORK, ExecutionRegistry, ExecutionState, Executor, ProviderResult,
)
from schemaxis.core.faults import SchemaxisError


RASTER = Representation(LogicalType("raster", {"elementType": "float32"}))
VECTOR = Representation(LogicalType("vector"))


def record(binding="test_executor_provider:FakeProvider"):
    document = {"inputs": {}, "arguments": {}, "outputs": {}}
    return CapabilityRecord(
        "fixture.copy", "0.1", "fixture", "1.0", "transform", binding,
        Path("fixture.json"), document,
    )


class RegistryTests(unittest.TestCase):
    def test_resolution_faults_are_distinct(self):
        registry = ExecutionRegistry("run-1")
        with self.assertRaises(SchemaxisError) as caught:
            registry.resolve("steps.unknown.outputs.data")
        self.assertEqual(caught.exception.fault.code, UNKNOWN_REFERENCE)

        registry.declare("steps.pending.outputs.data", RASTER)
        with self.assertRaises(SchemaxisError) as caught:
            registry.resolve("steps.pending.outputs.data")
        self.assertEqual(caught.exception.fault.code, NOT_YET_PRODUCED)
        self.assertTrue(caught.exception.fault.retryable)

        handle = DataHandle("h1", "fixture", object(), RASTER)
        registry.publish("steps.pending.outputs.data", handle)
        with self.assertRaises(SchemaxisError) as caught:
            registry.resolve("steps.pending.outputs.data", VECTOR)
        self.assertEqual(caught.exception.fault.code, TYPE_MISMATCH)

        registry.close(Reference("steps.pending.outputs.data"))
        with self.assertRaises(SchemaxisError) as caught:
            registry.resolve("steps.pending.outputs.data")
        self.assertEqual(caught.exception.fault.code, CLOSED_HANDLE)

    def test_publish_can_introduce_provider_output(self):
        registry = ExecutionRegistry("run-1")
        handle = DataHandle("h1", "fixture", 42, RASTER)
        registry.publish("steps.read.outputs.data", handle)
        self.assertIs(registry.resolve("steps.read.outputs.data"), handle)


class FakeProvider:
    calls = []

    def execute(self, request, context):
        self.calls.append((request, context))
        if request.inputs:
            value = request.inputs["source"].value
        else:
            value = request.arguments.get("value", 1)
        return ProviderResult(
            {"data": DataHandle(f"{context.step_id}-data", "fixture", value, RASTER)},
            {"value": value},
            (Artifact(context.step_id, f"memory://{context.step_id}", "application/x.fixture"),),
        )


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        FakeProvider.calls.clear()
        self.module = types.ModuleType("test_executor_provider")
        self.module.FakeProvider = FakeProvider
        sys.modules[self.module.__name__] = self.module

    def tearDown(self):
        sys.modules.pop(self.module.__name__, None)

    def test_binding_is_imported_only_during_execution(self):
        executor = Executor(Catalogue([record()]))
        sys.modules.pop(self.module.__name__)
        result = executor.execute({"steps": [{
            "id": "read", "capability": "fixture.copy", "arguments": {"value": 7}
        }]})
        self.assertEqual(result.state, ExecutionState.FAILED)
        self.assertEqual(result.faults[0].code, "PROVIDER_LOAD_FAILED")

    def test_plan_passes_live_handles_between_steps_and_returns_json_envelope(self):
        executor = Executor(Catalogue([record()]))
        result = executor.execute({"steps": [
            {"id": "read", "capability": "fixture.copy", "arguments": {"value": 7}},
            {"id": "copy", "capability": "fixture.copy", "inputs": {
                "source": {"ref": "steps.read.outputs.data"}
            }},
        ]}, execution_id="run-7")
        self.assertEqual(result.state, ExecutionState.SUCCEEDED)
        self.assertEqual(FakeProvider.calls[1][0].inputs["source"].value, 7)
        envelope = result.to_dict()
        self.assertEqual(envelope["executionId"], "run-7")
        self.assertEqual(envelope["steps"][1]["outputs"]["data"],
                         "steps.copy.outputs.data")
        json.dumps(envelope)

    def test_resolution_failure_stops_execution_with_structured_fault(self):
        result = Executor(Catalogue([record()])).execute({"steps": [{
            "id": "copy", "capability": "fixture.copy",
            "inputs": {"source": {"ref": "steps.missing.outputs.data"}},
        }]})
        self.assertEqual(result.state, ExecutionState.FAILED)
        self.assertEqual(result.faults[0].code, UNKNOWN_REFERENCE)
        self.assertEqual(len(FakeProvider.calls), 0)

    def test_an_execution_that_ran_nothing_is_never_reported_as_success(self):
        executor = Executor(Catalogue([record()]))
        for plan in ({}, {"nodes": []}, {"steps": []}, {"stages": [{"id": "read"}]}):
            with self.subTest(plan=plan):
                result = executor.execute(plan)
                self.assertEqual(result.state, ExecutionState.FAILED)
                self.assertEqual(result.faults[0].code, NO_EXECUTED_WORK)
                self.assertEqual(result.steps, ())
        self.assertEqual(len(FakeProvider.calls), 0)

    def test_resolved_plan_nodes_publish_under_their_own_section(self):
        executor = Executor(Catalogue([record()]))
        result = executor.execute({"nodes": [
            {"id": "elevation", "section": "resources", "capability": "fixture.copy",
             "arguments": {"value": 3}},
            {"id": "copy", "section": "steps", "capability": "fixture.copy",
             "inputs": {"source": {"ref": "resources.elevation.outputs.data"}}},
        ]})
        self.assertEqual(result.state, ExecutionState.SUCCEEDED)
        self.assertEqual(result.steps[0].output_refs["data"], "resources.elevation.outputs.data")
        self.assertEqual(FakeProvider.calls[1][0].inputs["source"].value, 3)


if __name__ == "__main__":
    unittest.main()
