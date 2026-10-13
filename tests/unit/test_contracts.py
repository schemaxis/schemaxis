import json
import pickle
import unittest

from schemaxis.core.contracts import (
    Artifact, DataHandle, Encoding, LogicalType, PhysicalLayout, Port, Reference,
    Representation, Resource, json_value,
)
from schemaxis.core.faults import SchemaxisError, Fault


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.representation = Representation(
            LogicalType("raster", {"elementType": "float32", "shape": [None, None]}),
            PhysicalLayout("tiled", {"tileShape": [256, 256]}),
            Encoding("image/tiff", {"compression": "deflate"}),
        )

    def test_contracts_are_json_safe_and_detached(self):
        source = {"labels": ["elevation"]}
        resource = Resource("dem", "file:///data/dem.tif", "dataset", metadata=source)
        source["labels"].append("changed")
        self.assertEqual(resource.to_dict()["metadata"], {"labels": ["elevation"]})
        json.dumps(resource.to_dict())
        json.dumps(self.representation.to_dict())

    def test_nested_contract_shape_keeps_meaning_layout_and_encoding_separate(self):
        value = self.representation.to_dict()
        self.assertEqual(value["logical"]["kind"], "raster")
        self.assertEqual(value["layout"]["kind"], "tiled")
        self.assertEqual(value["encoding"]["mediaType"], "image/tiff")

    def test_reference_port_and_artifact_serialization(self):
        self.assertEqual(Reference("steps.slope.outputs.raster").to_dict(), {
            "ref": "steps.slope.outputs.raster"
        })
        port = Port("raster", self.representation, streaming=True)
        self.assertTrue(port.to_dict()["streaming"])
        artifact = Artifact("slope", "file:///out/slope.tif", "image/tiff",
                            digest="sha256:abc", produced_by="slope_writer")
        self.assertEqual(artifact.to_dict()["producedBy"], "slope_writer")

    def test_values_are_immutable_and_validated(self):
        logical = LogicalType("table", {"columns": ["a"]})
        with self.assertRaises(TypeError):
            logical.details["columns"] = []
        with self.assertRaises(ValueError):
            Reference(" ")
        with self.assertRaises(ValueError):
            Port("x", self.representation, cardinality="sometimes")
        with self.assertRaises(TypeError):
            json_value({1: "not a JSON object"})
        with self.assertRaises(TypeError):
            json_value({"bad": object()})

    def test_data_handle_is_live_and_nonserializable(self):
        payload = object()
        handle = DataHandle("h1", "gdal", payload, self.representation)
        self.assertIs(handle.value, payload)
        self.assertFalse(hasattr(handle, "to_dict"))
        with self.assertRaises(TypeError):
            pickle.dumps(handle)
        with self.assertRaises(TypeError):
            json.dumps(handle)


class FaultTests(unittest.TestCase):
    def test_fault_contains_required_agent_actionability(self):
        fault = Fault(
            "reference_unresolved", "Output port does not exist",
            "/steps/2/inputs/raster", "reference-resolution", retryable=False,
            observed={"ref": "steps.missing.outputs.raster", "available": ["dem"]},
            recovery="Choose one of the available ports.",
        )
        value = fault.to_dict()
        json.dumps(value)
        self.assertEqual(value["location"], "/steps/2/inputs/raster")
        self.assertEqual(value["observed"]["available"], ["dem"])

    def test_schemaxis_error_preserves_fault(self):
        fault = Fault("bad_input", "Input is invalid", "/resources/dem", "validation")
        error = SchemaxisError(fault)
        self.assertIs(error.fault, fault)
        self.assertEqual(str(error), "Input is invalid")
        self.assertEqual(error.to_dict(), {"fault": fault.to_dict()})

    def test_fault_rejects_non_json_observations(self):
        with self.assertRaises(TypeError):
            Fault("bad", "Bad", "/", "validation", observed={"value": object()})


if __name__ == "__main__":
    unittest.main()
