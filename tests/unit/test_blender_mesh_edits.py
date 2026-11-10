"""Independent geometry invariants for the finite mesh edit replay contract."""
import math
import unittest
from schemaxis.adaptors.blender import mesh_edits as e
from schemaxis.errors import SchemaxisError


def recipe(*steps):
    return e.validate([{'object':'part','steps':[{'id':str(i),**step} for i,step in enumerate(steps)]}],{'part':'mesh'})[0]['steps']


def step(kind,selection=None,**values):
    return {'kind':kind,'selection':selection or {'kind':'all'},**values}


def volume(m):
    total=0
    for f in m['faces']:
        a=m['vertices'][f[0]]
        for i in range(1,len(f)-1):
            b=m['vertices'][f[i]];c=m['vertices'][f[i+1]]
            total+=(a[0]*(b[1]*c[2]-b[2]*c[1])+a[1]*(b[2]*c[0]-b[0]*c[2])+a[2]*(b[0]*c[1]-b[1]*c[0]))/6
    return total


class MeshEdits(unittest.TestCase):
    def panel(self):return e.mesh([[0,0,0],[2,0,0],[2,2,0],[0,2,0]],[[0,1,2,3]])

    def test_enclosure_extrusion_inset_then_extrusion_has_literal_volume(self):
        top={'kind':'normal','direction':[0,0,1]}
        inner={'kind':'box','minimum':[.5,.5,2],'maximum':[1.5,1.5,2]}
        m,history=e.replay(self.panel(),recipe(step('extrudeFaces',offset=[0,0,2],keepBase=True),step('insetFaces',top,distance=.25),step('extrudeFaces',inner,offset=[0,0,1])))
        self.assertEqual((len(m['vertices']),len(m['faces'])),(16,14));self.assertAlmostEqual(volume(m),10.25)
        self.assertEqual([r['selected'] for r in history],[1,1,1])
        self.assertEqual(max(p[2] for p in m['vertices']),3)

    def test_concave_polygon_triangulation_preserves_literal_area(self):
        m=e.mesh([[0,0,0],[2,0,0],[2,2,0],[1,1,0],[0,2,0]],[[0,1,2,3,4]])
        m,_=e.replay(m,recipe(step('triangulate')))
        self.assertEqual(len(m['faces']),3)
        area=0
        for a,b,c in m['faces']:
            p,q,r=[m['vertices'][v] for v in (a,b,c)];area+=abs((q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0]))/2
        self.assertEqual(area,3)

    def test_crossing_and_nonadjacent_touching_polygon_boundaries_refuse(self):
        outlines=[[[0,0,0],[2,2,0],[0,2,0],[2,0,0],[3,1,0]],[[0,0,0],[2,0,0],[2,2,0],[1,0,0],[0,2,0]]]
        for points in outlines:
            with self.subTest(points=points),self.assertRaises(SchemaxisError) as caught:
                e.replay(e.mesh(points,[list(range(5))]),recipe(step('triangulate')))
            self.assertEqual(caught.exception.fault.code,'INVALID_MESH_EDIT')

    def test_domain_defaults_match_typed_operation_and_selector(self):
        for operation,selection,expected in [('mergeVertices',{'kind':'all'},'POINT'),('bridgeLoops',{'kind':'boundary'},'EDGE'),('transform',{'kind':'boundary'},'EDGE'),('shade',{'kind':'normal'},'FACE')]:
            self.assertEqual(recipe(step(operation,selection))[0]['selection']['domain'],expected)

    def test_coordinate_comparison_uses_shape_span_and_exact_topology(self):
        import copy
        base=e.mesh([[1000000,0,0],[1000000,2,0],[1000000,0,2]],[[0,1,2]])
        changed=copy.deepcopy(base);changed['vertices'][0][0]+=.001
        self.assertFalse(e.geometry_matches(changed,base))
        changed=copy.deepcopy(base);changed['vertices'][0][1]+=1e-7
        self.assertTrue(e.geometry_matches(changed,base))
        changed['faces'][0].reverse();self.assertFalse(e.geometry_matches(changed,base))

    def test_canonical_edge_selection_and_nonuniform_transform(self):
        selected={'kind':'indices','domain':'EDGE','indices':[0]}
        m,h=e.replay(self.panel(),recipe(step('transform',selected,pivot=[0,0,0],scale=[2,3,1],rotation=[0,0,math.pi/2],translation=[1,2,3])))
        for actual,expected in zip(m['vertices'][:2],[[1,2,3],[1,6,3]]):
            for a,b in zip(actual,expected):self.assertAlmostEqual(a,b)
        self.assertEqual(m['vertices'][2:],[[2,2,0],[0,2,0]]);self.assertEqual(h[0]['selected'],1)

    def test_weld_and_split_preserve_materials_and_face_geometry(self):
        m=e.mesh([[0,0,0],[1,0,0],[1,1,0],[0,1,0],[1,0,0],[2,0,0],[2,1,0],[1,1,0]],[[0,1,2,3],[4,5,6,7]],materials=[0,2])
        merged,_=e.replay(m,recipe(step('mergeVertices',{'kind':'all','domain':'POINT'},distance=.001)))
        self.assertEqual(len(merged['vertices']),6);self.assertEqual(merged['materials'],[0,2]);self.assertEqual(len(e.all_edges(merged)),7)
        split,_=e.replay(merged,recipe(step('splitFaces',{'kind':'material','slots':[2]})))
        self.assertEqual(len(split['vertices']),10);self.assertEqual(split['materials'],[0,2])

    def test_outward_normals_repair_reversed_closed_surface(self):
        closed,_=e.replay(self.panel(),recipe(step('extrudeFaces',offset=[0,0,2],keepBase=True)))
        closed['faces']=[list(reversed(f)) for f in closed['faces']]
        fixed,_=e.replay(closed,recipe(step('normals',mode='outward')))
        self.assertAlmostEqual(volume(fixed),8)

    def test_collapsed_inset_and_empty_or_invalid_selection_refuse(self):
        cases=[step('insetFaces',distance=2),step('transform',{'kind':'indices','domain':'POINT','indices':[10]}),step('shade',{'kind':'box','minimum':[8,8,8],'maximum':[9,9,9]})]
        for case in cases:
            with self.subTest(case=case),self.assertRaises(SchemaxisError):e.replay(self.panel(),recipe(case))
        with self.assertRaises(SchemaxisError):recipe(step('extrudeFaces',{'kind':'all','domain':'POINT'}))

    def test_growth_budget_refuses_before_allocating_extruded_vertices(self):
        base=e.mesh([[0,0,0],[1,0,0],[0,1,0]],[[0,1,2]]*20000)
        with self.assertRaises(SchemaxisError) as caught:e.replay(base,recipe(step('extrudeFaces')))
        self.assertEqual(caught.exception.fault.code,'RESOURCE_BUDGET_EXCEEDED');self.assertEqual(len(base['vertices']),3)

    def cube(self):
        return e.mesh([[0,0,0],[2,0,0],[2,2,0],[0,2,0],[0,0,2],[2,0,2],[2,2,2],[0,2,2]],[[0,3,2,1],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]])

    def test_bridge_two_oriented_caps_produces_literal_closed_cube(self):
        m=self.cube();m['faces']=m['faces'][:2];m['materials']=m['materials'][:2];m['smooth']=m['smooth'][:2]
        m,h=e.replay(m,recipe(step('bridgeLoops',{'kind':'boundary','domain':'EDGE'})))
        self.assertEqual((len(m['vertices']),len(m['faces'])),(8,6));self.assertAlmostEqual(volume(m),8);self.assertEqual(h[0]['selected'],8)

    def test_plane_cut_caps_both_halfspaces_with_literal_half_volume(self):
        for side,z in [('positive',[1,2]),('negative',[0,1])]:
            m,_=e.replay(self.cube(),recipe(step('bisect',point=[0,0,1],side=side)))
            self.assertEqual((len(m['vertices']),len(m['faces'])),(8,6));self.assertAlmostEqual(volume(m),4)
            self.assertEqual([min(p[2] for p in m['vertices']),max(p[2] for p in m['vertices'])],z)

    def test_uncapped_cut_and_tangent_degenerate_cap_controls(self):
        m,_=e.replay(self.cube(),recipe(step('bisect',point=[0,0,1],cap=False)))
        self.assertEqual(len(m['faces']),5)
        with self.assertRaises(SchemaxisError):e.replay(self.cube(),recipe(step('bisect',point=[0,0,0],side='negative')))
        with self.assertRaises(SchemaxisError):e.replay(self.panel(),recipe(step('bisect',point=[0,0,0])))
