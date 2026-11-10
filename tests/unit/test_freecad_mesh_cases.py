"""Independent block-volume oracles cross-check the published STL fixtures."""
import sys,unittest
from pathlib import Path
from schemaxis.adaptors.freecad.mesh_source import admit
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from freecad_mesh_cases import voxel_bracket,stl,bracket_oracle,cavity_triangles,cavity_oracle,dense_box


class MeshCases(unittest.TestCase):
    def test_voxel_boundary_has_three_analytic_material_regions(self):
        for variant in (False,True):
            dimensions=(7,5,6) if variant else (6,4,5)
            facts,_,_=admit(stl(voxel_bracket(*dimensions)),'mesh')
            self.assertAlmostEqual(facts['volume'],bracket_oracle(variant=variant)['sourceVolume'])
            self.assertEqual(facts['bounds'],[0,6*dimensions[0],0,4*dimensions[1],0,4*dimensions[2]])

    def test_binary_centimetre_offset_cavity_has_independent_material_volume(self):
        facts,_,_=admit(stl(cavity_triangles(),binary=True),'mesh',scale=10,reverse=True)
        self.assertAlmostEqual(facts['volume'],cavity_oracle()['volume'],delta=.0001)
        self.assertEqual(facts['facets'],24)

    def test_prospective_conversion_ceiling_is_a_closed_exact_facet_inventory(self):
        facts,_,_=admit(stl(dense_box()),'mesh')
        self.assertEqual(facts['facets'],20000);self.assertAlmostEqual(facts['volume'],6000)
