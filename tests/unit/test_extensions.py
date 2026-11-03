# Copyright (C) 2026 David L F Gaden
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

from schemaxis.core.extensions import ExtensionError, ExtensionRegistry


MODULE_SOURCE = '''
from schemaxis.core.extensions import Extension

class SampleExtension(Extension):
    declaration = {
        "id": "sample.scale",
        "arguments": {
            "count": {"type": "integer", "required": True},
            "mode": {"type": "enum", "values": ["fast", "careful"], "default": "careful"},
            "enabled": {"type": "boolean", "default": True},
        },
    }

    cli_contributed = False

    @classmethod
    def contribute_cli_arguments(cls, parser):
        cls.cli_contributed = True
        return super().contribute_cli_arguments(parser)

    def configure(self, config):
        self.config = dict(config)
        with open(CONFIGURED_MARKER, "a", encoding="utf-8") as stream:
            stream.write(self.declaration["id"] + "\\n")
'''


class ExtensionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.module_name = "temporary_schemaxis_extension"
        self.marker = self.root / "configured.txt"
        module = MODULE_SOURCE.replace("CONFIGURED_MARKER", repr(str(self.marker)))
        (self.root / f"{self.module_name}.py").write_text(module, encoding="utf-8")
        self.index = self.root / "extensions.json"
        self.index.write_text(
            json.dumps({"sample.scale": f"{self.module_name}:SampleExtension"}), encoding="utf-8"
        )
        sys.path.insert(0, str(self.root))
        sys.modules.pop(self.module_name, None)

    def tearDown(self) -> None:
        sys.modules.pop(self.module_name, None)
        sys.path.remove(str(self.root))
        self.temporary.cleanup()

    def test_new_indexed_derived_class_needs_no_core_edit_and_discovery_does_not_import(self) -> None:
        registry = ExtensionRegistry.from_indexes([self.index])
        self.assertEqual(
            [(item.id, item.binding) for item in registry.list_extensions()],
            [("sample.scale", f"{self.module_name}:SampleExtension")],
        )
        self.assertNotIn(self.module_name, sys.modules)
        self.assertFalse(self.marker.exists())

        extension_class = registry.load_class("sample.scale")
        self.assertEqual(extension_class.declaration["id"], "sample.scale")
        self.assertIn(self.module_name, sys.modules)
        self.assertFalse(self.marker.exists())

    def test_cli_and_document_use_identical_validated_configuration(self) -> None:
        registry = ExtensionRegistry.from_indexes([self.index])
        document = registry.configure_document("sample.scale", {"count": 3})
        cli = registry.configure_cli("sample.scale", ["--sample.scale.count", "3"])
        self.assertEqual(document.config, cli.config)
        self.assertEqual(document.config, {"count": 3, "mode": "careful", "enabled": True})
        self.assertTrue(type(cli).cli_contributed)

    def test_unknown_document_and_cli_arguments_fail(self) -> None:
        registry = ExtensionRegistry.from_indexes([self.index])
        with self.assertRaises(ExtensionError) as caught:
            registry.configure_document("sample.scale", {"count": 3, "mystery": 1})
        self.assertEqual(caught.exception.code, "UNKNOWN_ARGUMENT")
        with self.assertRaises(ExtensionError) as caught:
            registry.configure_cli("sample.scale", ["--sample.scale.mystery", "1"])
        self.assertEqual(caught.exception.code, "INVALID_CLI")

    def test_duplicate_ids_are_rejected_within_or_across_indexes(self) -> None:
        duplicate_keys = self.root / "duplicate-keys.json"
        duplicate_keys.write_text(
            '{"same.id":"one:Class","same.id":"two:Class"}', encoding="utf-8"
        )
        with self.assertRaises(ExtensionError) as caught:
            ExtensionRegistry.from_indexes([duplicate_keys])
        self.assertEqual(caught.exception.code, "DUPLICATE_EXTENSION")

        other = self.root / "other.json"
        other.write_text(self.index.read_text(encoding="utf-8"), encoding="utf-8")
        with self.assertRaises(ExtensionError) as caught:
            ExtensionRegistry.from_indexes([self.index, other])
        self.assertEqual(caught.exception.code, "DUPLICATE_EXTENSION")

    def test_configure_hook_runs_only_for_selected_class(self) -> None:
        second_name = "temporary_second_extension"
        (self.root / f"{second_name}.py").write_text(
            MODULE_SOURCE.replace("sample.scale", "sample.other").replace(
                "CONFIGURED_MARKER", repr(str(self.marker))
            ),
            encoding="utf-8",
        )
        self.index.write_text(json.dumps({
            "sample.scale": f"{self.module_name}:SampleExtension",
            "sample.other": f"{second_name}:SampleExtension",
        }), encoding="utf-8")
        sys.modules.pop(second_name, None)
        try:
            registry = ExtensionRegistry.from_indexes([self.index])
            registry.configure_document("sample.scale", {"count": 2})
            self.assertNotIn(second_name, sys.modules)
            self.assertEqual(self.marker.read_text(encoding="utf-8"), "sample.scale\n")
        finally:
            sys.modules.pop(second_name, None)

    def test_declaration_must_conform_to_index_id(self) -> None:
        self.index.write_text(
            json.dumps({"different.id": f"{self.module_name}:SampleExtension"}), encoding="utf-8"
        )
        with self.assertRaises(ExtensionError) as caught:
            ExtensionRegistry.from_indexes([self.index]).load_class("different.id")
        self.assertEqual(caught.exception.code, "DECLARATION_ID_MISMATCH")


COMPOSITE_SOURCE = '''
from schemaxis.core.extensions import Extension

class SliceSeries(Extension):
    declaration = {
        "id": "visualisation.slice-series",
        "arguments": {
            "axes": {
                "type": "array",
                "required": True,
                "items": {"type": "enum", "values": ["x", "y", "z"]},
                "summary": "Axes to sweep",
            },
            "fields": {
                "type": "array",
                "items": {"type": "string"},
                "default": ["p"],
            },
            "colouring": {
                "type": "object",
                "properties": {
                    "legend": {"type": "boolean", "default": True},
                    "range": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                },
                "default": {},
            },
        },
    }

    def configure(self, config):
        self.config = dict(config)
'''


class CompositeExtensionTests(unittest.TestCase):
    """A composite declaration must behave identically from CLI and document."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.module_name = "temporary_composite_extension"
        (self.root / f"{self.module_name}.py").write_text(COMPOSITE_SOURCE, encoding="utf-8")
        self.index = self.root / "extensions.json"
        self.index.write_text(
            json.dumps({"visualisation.slice-series": f"{self.module_name}:SliceSeries"}),
            encoding="utf-8",
        )
        sys.path.insert(0, str(self.root))
        sys.modules.pop(self.module_name, None)
        self.registry = ExtensionRegistry.from_indexes([self.index])

    def tearDown(self) -> None:
        sys.modules.pop(self.module_name, None)
        sys.path.remove(str(self.root))
        self.temporary.cleanup()

    def test_cli_json_and_document_values_agree(self) -> None:
        document = self.registry.configure_document(
            "visualisation.slice-series",
            {"axes": ["x", "z"], "colouring": {"range": [0, 1]}},
        )
        cli = self.registry.configure_cli("visualisation.slice-series", [
            "--visualisation.slice-series.axes", '["x", "z"]',
            "--visualisation.slice-series.colouring", '{"range": [0, 1]}',
        ])
        self.assertEqual(document.config, cli.config)
        self.assertEqual(document.config, {
            "axes": ["x", "z"],
            "fields": ["p"],
            "colouring": {"legend": True, "range": [0, 1]},
        })

    def test_nested_faults_are_located_from_either_source(self) -> None:
        with self.assertRaises(ExtensionError) as caught:
            self.registry.configure_document(
                "visualisation.slice-series", {"axes": ["x"], "colouring": {"range": [0]}}
            )
        self.assertEqual(caught.exception.code, "INVALID_ARGUMENT")
        self.assertEqual(caught.exception.location, "visualisation.slice-series.colouring.range")

        with self.assertRaises(ExtensionError) as caught:
            self.registry.configure_cli("visualisation.slice-series", [
                "--visualisation.slice-series.axes", '["w"]',
            ])
        self.assertEqual(caught.exception.location, "visualisation.slice-series.axes[0]")

    def test_malformed_cli_json_is_reported_against_the_option(self) -> None:
        with self.assertRaises(ExtensionError) as caught:
            self.registry.configure_cli("visualisation.slice-series", [
                "--visualisation.slice-series.axes", "x,z",
            ])
        self.assertEqual(caught.exception.code, "INVALID_ARGUMENT")
        self.assertEqual(caught.exception.fault.observed["option"], "--visualisation.slice-series.axes")

    def test_declaration_exports_as_canonical_json(self) -> None:
        description = self.registry.load_class("visualisation.slice-series").describe()
        self.assertEqual(description["id"], "visualisation.slice-series")
        self.assertEqual(list(description["arguments"]), ["axes", "colouring", "fields"])
        self.assertEqual(json.loads(json.dumps(description)), description)


if __name__ == "__main__":
    unittest.main()
