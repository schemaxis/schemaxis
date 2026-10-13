from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from schemaxis.core.catalogue import Catalogue
from schemaxis.core.contracts import DataHandle, LogicalType, Representation
from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.fixture_geo.provider import CAPABILITIES, Provider, create_provider


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PACKAGE = REPOSITORY_ROOT / "src" / "schemaxis/adaptors/fixture_geo"
EXAMPLE_ROOT = REPOSITORY_ROOT / "examples" / "terrain-products"


@dataclass
class Context:
    execution_id: str
    resource_root: Path
    output_root: Path


class FixtureProviderConformanceTests(unittest.TestCase):
    def test_static_manifest_and_binding_capabilities_agree(self) -> None:
        catalogue = Catalogue.from_roots([FIXTURE_PACKAGE])
        self.assertEqual({record.id for record in catalogue}, CAPABILITIES)
        self.assertTrue(all(record.provider == Provider.id for record in catalogue))
        self.assertTrue(all(record.provider_version == Provider.version for record in catalogue))

    def test_open_slope_contours_and_write_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_root = Path(temporary_directory)
            context = Context("run-1", EXAMPLE_ROOT, output_root)
            provider = create_provider()

            opened = provider.execute(
                "fixture.geo.open", {}, {"uri": "elevation.fixture.json"}, context
            )
            raster = opened.outputs["dataset"]
            self.assertEqual(raster.representation.logical.kind, "geo.raster-dataset")
            self.assertEqual(opened.observations["inspection"]["crs"], "EPSG:26914")

            slope = provider.execute("fixture.geo.slope", {"dataset": raster}, {}, context)
            contours = provider.execute("fixture.geo.contours", {"dataset": raster}, {}, context)
            self.assertEqual(slope.outputs["dataset"].value["product"]["unit"], "degrees")
            self.assertEqual(contours.outputs["dataset"].value["product"]["interval"], 10)
            self.assertEqual(contours.outputs["dataset"].representation.logical.kind, "geo.vector-dataset")

            written = provider.execute(
                "fixture.geo.write", {"dataset": contours.outputs["dataset"]},
                {"uri": "contours.json"}, context,
            )
            artifact = written.artifacts[0]
            artifact_bytes = Path(artifact.uri).read_bytes()
            self.assertEqual(artifact.digest, f"sha256:{hashlib.sha256(artifact_bytes).hexdigest()}")
            self.assertEqual(
                written.verification,
                {"logicalType": True, "crs": True, "extent": True, "sha256": True},
            )

            persisted = json.loads(artifact_bytes)
            self.assertEqual(persisted["logicalType"], "geo.vector-dataset")
            self.assertEqual(persisted["dataset"]["crs"], raster.value["crs"])
            self.assertEqual(persisted["dataset"]["extent"], raster.value["extent"])

            second_root = output_root / "second"
            second = provider.execute(
                "fixture.geo.write", {"dataset": contours.outputs["dataset"]},
                {"uri": "contours.json"}, Context("run-2", EXAMPLE_ROOT, second_root),
            )
            self.assertEqual(second.artifacts[0].digest, artifact.digest)

    def test_wrong_logical_type_is_a_structured_fault(self) -> None:
        wrong = DataHandle(
            id="wrong", provider="test", value={},
            representation=Representation(LogicalType("geo.vector-dataset")),
        )
        context = Context("run", EXAMPLE_ROOT, Path("unused"))
        with self.assertRaises(SchemaxisError) as caught:
            Provider().execute("fixture.geo.slope", {"dataset": wrong}, {}, context)
        self.assertEqual(caught.exception.fault.code, "TYPE_MISMATCH")
        self.assertEqual(caught.exception.fault.phase, "connect")

    def test_missing_resource_is_a_structured_fault(self) -> None:
        context = Context("run", EXAMPLE_ROOT, Path("unused"))
        with self.assertRaises(SchemaxisError) as caught:
            Provider().execute("fixture.geo.open", {}, {"uri": "missing.json"}, context)
        self.assertEqual(caught.exception.fault.code, "RESOURCE_NOT_FOUND")
        self.assertEqual(caught.exception.fault.phase, "execute")


if __name__ == "__main__":
    unittest.main()
