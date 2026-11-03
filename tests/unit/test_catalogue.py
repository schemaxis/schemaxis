# Copyright (C) 2026 David L F Gaden
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

from schemaxis.core.catalogue import Catalogue, CatalogueError


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PACKAGE = REPOSITORY_ROOT / "src" / "schemaxis/adaptors/fixture_geo"


class CatalogueTests(unittest.TestCase):
    def test_discovers_fixture_capabilities_in_identifier_order(self) -> None:
        before = set(sys.modules)
        catalogue = Catalogue.from_roots([FIXTURE_PACKAGE])

        self.assertEqual(
            [record.id for record in catalogue.list_capabilities()],
            [
                "fixture.geo.contours",
                "fixture.geo.open",
                "fixture.geo.slope",
                "fixture.geo.write",
            ],
        )
        self.assertEqual(catalogue.describe("fixture.geo.open").kind, "reader")
        imported = set(sys.modules) - before
        self.assertNotIn("schemaxis.adaptors.fixture_geo.provider", imported)

    def test_document_is_a_defensive_copy(self) -> None:
        record = Catalogue.from_roots([FIXTURE_PACKAGE]).describe("fixture.geo.contours")
        first = record.document
        first["arguments"]["interval"]["default"] = 99
        self.assertEqual(record.document["arguments"]["interval"]["default"], 10)

    def test_duplicate_capability_identifier_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._write_package(root / "one", "shared.capability")
            self._write_package(root / "two", "shared.capability")

            with self.assertRaises(CatalogueError) as caught:
                Catalogue.from_roots([root])

        self.assertEqual(caught.exception.code, "DUPLICATE_CAPABILITY")
        self.assertIn("shared.capability", str(caught.exception))

    def test_provider_binding_is_not_executed_during_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_root = Path(temporary_directory) / "provider"
            self._write_package(package_root, "safe.capability", binding="does_not_exist:factory")
            catalogue = Catalogue.from_roots([package_root])

        self.assertEqual(catalogue.describe("safe.capability").binding, "does_not_exist:factory")

    @staticmethod
    def _write_package(root: Path, capability_id: str, *, binding: str = "provider:factory") -> None:
        capabilities = root / "capabilities"
        capabilities.mkdir(parents=True)
        (root / "package.json").write_text(
            json.dumps(
                {
                    "packageVersion": "schemaxis.package/0.1",
                    "provider": {"id": "test.provider", "version": "0.1.0"},
                    "binding": binding,
                    "capabilities": ["capabilities/capability.json"],
                }
            ),
            encoding="utf-8",
        )
        (capabilities / "capability.json").write_text(
            json.dumps(
                {
                    "id": capability_id,
                    "contractVersion": "0.1",
                    "provider": "test.provider",
                    "kind": "transform",
                    "inputs": {},
                    "arguments": {},
                    "outputs": {},
                }
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
