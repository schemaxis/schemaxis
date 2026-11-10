"""Route ownership and reusable artist-library authoring must agree with schemas."""
import json,unittest
from pathlib import Path
from jsonschema import Draft202012Validator
from schemaxis.schema_authoring import version_schema
from schemaxis.studio_library import load_library,instantiate_item,plan_item
from schemaxis.adaptors.blender.adaptor import plan

ROOT=Path(__file__).resolve().parents[2]


class SurfaceDelivery(unittest.TestCase):
    def test_readiness_examples_keep_actual_route_and_literal_schema(self):
        readiness=json.loads((ROOT/'src/schemaxis/adaptors/blender/readiness.json').read_text())
        selected={'layered-surfaces','pbr-enclosure','surface-gallery'};seen=set()
        for route,metadata in readiness['routes'].items():
            for example in metadata['examples']:
                if example['id'] not in selected:continue
                document=json.loads((ROOT/example['reference']).read_text())
                self.assertEqual(document['version'],route)
                self.assertEqual(list(Draft202012Validator(version_schema(route)).iter_errors(document)),[])
                plan(document);seen.add(example['id'])
        self.assertEqual(seen,selected)

    def test_artist_starters_and_reusable_role_snippets_plan(self):
        library=load_library('blender')
        selected={'layered-surfaces','textured-pbr-enclosure','surface-gallery','layered-surface','stored-finish-uv'};seen=set()
        for kind in ('templates','snippets'):
            for item in library[kind]:
                if item['id'] not in selected:continue
                with self.subTest(id=item['id']):
                    document=instantiate_item(library,item,provider='blender')
                    self.assertEqual(list(Draft202012Validator(version_schema(document['version'])).iter_errors(document)),[])
                    plan_item(document);seen.add(item['id'])
        self.assertEqual(seen,selected)


if __name__=='__main__':unittest.main()
