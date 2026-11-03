# Copyright (C) 2026 David L F Gaden
from __future__ import annotations

from pathlib import Path
import unittest

from schemaxis.core.catalogue import Catalogue
from schemaxis.core.planner import Planner, PlanningError


ROOT = Path(__file__).resolve().parents[2]


def workflow() -> dict:
    return {
        "documentVersion": "schemaxis.workflow/0.1",
        "resources": {
            "elevation": {
                "source": {"kind": "file", "uri": "fixture.json"},
                "reader": "fixture.geo.open",
            }
        },
        "steps": [
            {
                "id": "slope",
                "use": "fixture.geo.slope",
                "inputs": {"dataset": {"ref": "resources.elevation.outputs.dataset"}},
            },
            {
                "id": "contours",
                "use": "fixture.geo.contours",
                "inputs": {"dataset": {"ref": "resources.elevation.outputs.dataset"}},
                "arguments": {"interval": 5},
            },
        ],
        "outputs": {
            "slope-file": {
                "writer": "fixture.geo.write",
                "input": {"ref": "steps.slope.outputs.dataset"},
                "destination": {"kind": "file", "uri": "slope.json"},
            },
            "contour-file": {
                "writer": "fixture.geo.write",
                "input": {"ref": "steps.contours.outputs.dataset"},
                "destination": {"kind": "file", "uri": "contours.json"},
            },
        },
    }


class PlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = Planner(Catalogue.from_roots([ROOT / "src" / "schemaxis/adaptors/fixture_geo"]))

    def test_resolves_defaults_dag_union_ports_and_stable_digest(self) -> None:
        first = self.planner.resolve(workflow())
        second = self.planner.resolve(workflow())
        by_key = {node.key: node for node in first.nodes}
        self.assertEqual(by_key["steps.slope"].arguments["unit"], "degrees")
        self.assertEqual(by_key["steps.contours"].arguments["interval"], 5)
        self.assertLess(first.topological_order.index("resources.elevation"), first.topological_order.index("steps.slope"))
        self.assertLess(first.topological_order.index("steps.slope"), first.topological_order.index("outputs.slope-file"))
        self.assertEqual(first.digest, second.digest)
        self.assertEqual(len(first.digest), 64)

    def test_rejects_wrong_port_type(self) -> None:
        value = workflow()
        value["steps"].append({
            "id": "bad-slope", "use": "fixture.geo.slope",
            "inputs": {"dataset": {"ref": "steps.contours.outputs.dataset"}},
        })
        with self.assertRaises(PlanningError) as caught:
            self.planner.resolve(value)
        self.assertEqual(caught.exception.code, "INCOMPATIBLE_PORT_TYPE")

    def test_detects_cycle(self) -> None:
        value = workflow()
        value["steps"] = [
            {"id": "one", "use": "fixture.geo.slope", "inputs": {"dataset": {"ref": "steps.two.outputs.dataset"}}},
            {"id": "two", "use": "fixture.geo.slope", "inputs": {"dataset": {"ref": "steps.one.outputs.dataset"}}},
        ]
        value["outputs"] = {}
        with self.assertRaises(PlanningError) as caught:
            self.planner.resolve(value)
        self.assertEqual(caught.exception.code, "WORKFLOW_CYCLE")

    def test_rejects_reference_to_unknown_port(self) -> None:
        value = workflow()
        value["steps"][0]["inputs"]["dataset"] = {"ref": "resources.elevation.outputs.missing"}
        with self.assertRaises(PlanningError) as caught:
            self.planner.resolve(value)
        self.assertEqual(caught.exception.code, "UNKNOWN_PORT")


if __name__ == "__main__":
    unittest.main()
