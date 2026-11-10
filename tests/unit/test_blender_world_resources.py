"""Reusable World schema, source references and aggregate resources."""
import copy
import unittest
from jsonschema import Draft202012Validator
from schemaxis.errors import SchemaxisError
from schemaxis.schema import arguments_schema
from schemaxis.adaptors.blender import world_resources as worlds


class WorldResources(unittest.TestCase):
    def test_defaults_are_detached_idempotent_and_match_authored_schema(self):
        value = [{'id': 'studio'}];before = copy.deepcopy(value)
        result = worlds.validate(value, images={})
        self.assertEqual(value, before)
        self.assertEqual(result[0]['lighting'], {'kind': 'colour', 'colour': [.05]*3, 'strength': 1})
        self.assertEqual(worlds.validate(result, images={}), result)
        self.assertEqual(list(Draft202012Validator(arguments_schema(worlds.OPTIONS)).iter_errors({'worlds': value})), [])
        self.assertTrue(all(result[0]['visibility'].values()))

    def test_environment_is_bound_to_declared_image_and_scene_reference(self):
        value = [{'id': 'studio', 'lighting': {'kind': 'environment', 'image': 'hdri', 'rotation': [0, 0, 1.2]}}]
        result = worlds.validate(value, images={'hdri'}, scene_world='studio')
        self.assertEqual(result[0]['lighting']['projection'], 'equirectangular')
        with self.assertRaises(SchemaxisError):worlds.validate(value, images={})
        with self.assertRaises(SchemaxisError):worlds.validate(value, images={'hdri'}, scene_world='missing')
        with self.assertRaises(SchemaxisError):worlds.validate(value*2, images={'hdri'})

    def test_importance_maps_have_one_aggregate_working_bound(self):
        value = [{'id': 'large', 'samplingResolution': 8192}]
        worlds.validate(value, images={})  # exactly256MiB, not a per-World-only cap
        with self.assertRaises(SchemaxisError) as error:
            worlds.validate(value + [{'id': 'extra'}], images={})
        self.assertEqual(error.exception.fault.code, 'RESOURCE_BUDGET_EXCEEDED')
        worlds.validate([{**value[0], 'sampling': 'none'},
                         {'id': 'secondLarge', 'samplingResolution': 8192, 'sampling': 'none'}], images={})

    def test_per_ray_visibility_is_not_silently_ignored_by_other_engines(self):
        spec = worlds.validate([{'id': 'studio', 'visibility': {'camera': False}}], images={})
        worlds.validate_engine(spec, 'cycles')
        for engine in ('eevee', 'workbench'):
            with self.assertRaises(SchemaxisError):worlds.validate_engine(spec, engine)
        worlds.validate_engine(worlds.validate([{'id': 'studio'}], images={}), 'eevee')

    def test_unknown_native_properties_and_nonpositive_mist_ranges_refuse(self):
        for value in ([{'id': 'studio', 'rna': 'free.property'}],
                      [{'id': 'studio', 'mist': {'kind': 'distance', 'depth': 0}}],
                      [{'id': 'studio', 'mist': {'kind': 'distance', 'height': 101}}]):
            with self.assertRaises(SchemaxisError):worlds.validate(value, images={})


if __name__ == '__main__':unittest.main()
