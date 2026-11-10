"""Physical sweep reduction preserves exact tool/centre/depth distinctions."""
import unittest
from schemaxis.adaptors.freecad.cam_tracks3 import tracks
from schemaxis.core.faults import SchemaxisError

TOOLS=[{'id':'a','kind':'flatEndmill'},{'id':'b','kind':'flatEndmill'},{'id':'point','kind':'drill'}]

def move(a,b,tool='a',code=1):return {'from':a,'to':b,'tool':tool,'code':code}


class Tracks(unittest.TestCase):
    def test_same_centre_deepest_reduction_requires_same_physical_tool(self):
        _,vertical=tracks({'motions':[move([2,3,0],[2,3,-2]),move([2,3,-2],[2,3,-8]),move([2,3,0],[2,3,-1],tool='b')]},TOOLS)
        self.assertEqual(vertical,{('a',2,3):-8,('b',2,3):-1})

    def test_nearby_centres_are_distinct_not_epsilon_merged(self):
        _,vertical=tracks({'motions':[move([0,0,0],[0,0,-2]),move([1e-7,0,0],[1e-7,0,-8])]},TOOLS)
        self.assertEqual(len(vertical),2)

    def test_actual_tiny_lateral_or_vertical_change_never_becomes_vertical_or_planar(self):
        for motion in (move([0,0,0],[1e-7,0,-2]),move([0,0,-2],[1,0,-2+1e-8]),move([0,0,-2],[1,0,-2],tool='point')):
            with self.subTest(motion=motion),self.assertRaises(SchemaxisError):tracks({'motions':[motion]},TOOLS)

    def test_reversed_line_is_same_footprint_but_another_tool_is_not(self):
        paths,vertical=tracks({'motions':[move([0,0,-2],[1,0,-2]),move([1,0,-8],[0,0,-8]),move([0,0,-1],[1,0,-1],tool='b')]},TOOLS)
        self.assertFalse(vertical);self.assertEqual(sorted(v[0] for v in paths.values()),[-8,-1])

    def test_rapid_never_earns_material_credit_and_aggregate_limit_refuses(self):
        self.assertEqual(tracks({'motions':[move([0,0,0],[0,0,-8],code=0)]},TOOLS),({},{}))
        motions=[move([i,0,0],[i,0,-2]) for i in range(513)]
        with self.assertRaises(SchemaxisError):tracks({'motions':motions},TOOLS)
