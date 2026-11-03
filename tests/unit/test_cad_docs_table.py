# Copyright (C) 2026 David L F Gaden
"""The hand-written FreeCAD family table must list every declared operation."""
from pathlib import Path
import unittest

from schemaxis.adaptors import registry

DOC = Path(__file__).resolve().parents[2] / 'docs/cad-and-mesh-workflows.md'


class CadDocsTableTests(unittest.TestCase):
    def test_every_freecad_operation_is_in_the_family_table(self):
        text = DOC.read_text()
        section = text.split('## FreeCAD', 1)[1].split('\n\n', 2)[1]
        for operation in registry.declarations('freecad'):
            with self.subTest(operation=operation):
                self.assertIn('`%s`' % operation, section)

    def test_sketch_constraint_claim_matches_the_sketch_code(self):
        text = DOC.read_text()
        self.assertNotIn('not fully dimension-constrained', text)
        self.assertIn('rectangle and circle', text)
