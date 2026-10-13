"""Packaged Studio starter documents and filled snippets remain plannable offline."""
import copy
import json
from pathlib import Path
import unittest

from schemaxis.adaptors import registry
from schemaxis.studio_library import load_library, instantiate_item


ROOT = Path(__file__).resolve().parents[2] / 'src' / 'schemaxis' / 'adaptors'
APPLICATIONS = ('paraview', 'freecad', 'blender', 'gmsh', 'calc')


class StudioTemplatesTest(unittest.TestCase):
    def test_paraview_starter_supports_the_single_state_live_preview_contract(self):
        from schemaxis.adaptors.paraview.live_native import Worker
        document = json.loads((ROOT / 'paraview' / 'templates' / 'slice-sweep.json').read_text())
        prepared = Worker().prepare(document)
        self.assertEqual(len(prepared[3]), 5)

    def test_starters_plan_without_mutating_the_authored_library(self):
        # The generated catalogue test covers every snippet against its declared
        # context; unrelated templates need not support every contextual insert.
        for application in APPLICATIONS:
            with self.subTest(application=application):
                metadata = load_library(application)
                self.assertEqual(metadata['version'], 'schemaxis.studio-adaptor/2')
                self.assertTrue(metadata['templates'])
                self.assertTrue(metadata['viewers'])
                before = copy.deepcopy(metadata)
                for entry in metadata['templates']:
                    document = instantiate_item(metadata, entry, provider=application)
                    self.assertIsNotNone(registry.plan(document))
                self.assertEqual(metadata, before, 'Instantiation must not modify the library')

    def test_snippets_and_starters_have_distinct_identifiers(self):
        for application in APPLICATIONS:
            metadata = json.loads((ROOT / application / 'studio.json').read_text())
            for collection in ('templates', 'snippets'):
                ids = [entry['id'] for entry in metadata[collection]]
                self.assertEqual(len(ids), len(set(ids)))
            self.assertLessEqual(set(metadata['viewers']), {'3d', 'image', 'table', 'text'})


if __name__ == '__main__':
    unittest.main()
