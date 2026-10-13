from __future__ import annotations

import unittest

from schemaxis.core.references import ReferenceSyntaxError, parse_reference


class ReferenceTests(unittest.TestCase):
    def test_parses_the_closed_reference_grammar(self) -> None:
        parsed = parse_reference({"ref": "steps.local-terrain_2.outputs.dataset"})
        self.assertEqual(parsed.namespace, "steps")
        self.assertEqual(parsed.identifier, "local-terrain_2")
        self.assertEqual(parsed.port, "dataset")
        self.assertEqual(parsed.to_dict(), {"ref": "steps.local-terrain_2.outputs.dataset"})

    def test_rejects_traversal_and_reflection_shapes(self) -> None:
        invalid = [
            "steps.x.__class__.dataset", "steps.x.outputs.dataset.value",
            "steps..outputs.dataset", "outputs.x.outputs.dataset",
            "steps.1x.outputs.dataset", "steps.x.outputs._private",
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ReferenceSyntaxError):
                parse_reference(value)

    def test_reference_envelope_rejects_extra_fields(self) -> None:
        with self.assertRaises(ReferenceSyntaxError):
            parse_reference({"ref": "resources.source.outputs.dataset", "attribute": "value"})


if __name__ == "__main__":
    unittest.main()
