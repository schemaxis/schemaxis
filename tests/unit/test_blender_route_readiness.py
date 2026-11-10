"""Every Blender readiness route exercises its own literal schema and planner."""
import unittest
from schemaxis.adaptor_conformance import host
from schemaxis.adaptor_conformance import route_materials


class BlenderRouteReadiness(unittest.TestCase):
    def test_all_three_routes_keep_meaningful_schema_and_planner_acceptance(self):
        for version in ('schemaxis.blender/1','schemaxis.blender.render/1','schemaxis.blender.production/1'):
            with self.subTest(version=version):
                result=host(version)
                self.assertTrue(result['verified'])
                self.assertIn('baseline and held-out case produce distinct effective plans',result['checks'])

    def test_production_examples_remain_in_the_production_route(self):
        _,_,entry=route_materials('schemaxis.blender.production/1')
        ids={example['id'] for example in entry['examples']}
        self.assertTrue({'geometry-resources','mesh-editing','editable-splines','technical-render','image-preview'}<=ids)
