"""Fresh mesh-BREP inventory must retain each source facet and winding."""
import copy,math,unittest
from schemaxis.adaptors.freecad.mesh_geometry import verify_inventory
from schemaxis.adaptors.freecad.mesh_source import admit
from schemaxis.core.faults import SchemaxisError
from test_freecad_mesh_source import binary,box


def measured(points,faces):
    result=[]
    for face in faces:
        a,b,c=[points[i] for i in face];u=[b[k]-a[k] for k in range(3)];v=[c[k]-a[k] for k in range(3)]
        cross=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
        normal=[x/math.hypot(*cross) for x in cross]
        result.append({'vertices':list(face),'normal':normal,'planar':True,'straight':True,'edges':3,'wires':1})
    return {'vertices':[list(p) for p in points],'faces':result}


class MeshGeometry(unittest.TestCase):
    def setUp(self):
        _,self.points,self.faces=admit(binary(box(origin=(4000,5000,6000))),'mesh')
        self.inventory=measured(self.points,self.faces)

    def check(self,inventory):verify_inventory(inventory,self.points,self.faces,'mesh')

    def test_topological_order_is_free_but_each_facet_and_outward_normal_is_bound(self):
        self.check(self.inventory)
        other=copy.deepcopy(self.inventory);count=len(self.points)
        other['vertices'].reverse();other['faces'].reverse()
        for face in other['faces']:face['vertices']=[count-1-i for i in reversed(face['vertices'])]
        self.check(other)
        other['faces'][0]['normal']=[-x for x in other['faces'][0]['normal']]
        with self.assertRaises(SchemaxisError):self.check(other)

    def test_only_binary_coordinate_serialization_roundoff_is_admitted(self):
        other=copy.deepcopy(self.inventory)
        other['vertices'][0][0]+=32*math.ulp(other['vertices'][0][0]);self.check(other)
        other['vertices'][0][0]+=64*math.ulp(other['vertices'][0][0])
        with self.assertRaises(SchemaxisError):self.check(other)

    def test_same_counts_and_plausible_geometry_do_not_admit_different_facets_or_curves(self):
        changes=[lambda r:r['faces'][0].update(vertices=r['faces'][1]['vertices']),
                 lambda r:r['faces'][0].update(planar=False),lambda r:r['faces'][0].update(straight=False),
                 lambda r:r['faces'][0].update(wires=2),lambda r:r['faces'][0].update(edges=True),
                 lambda r:r['vertices'].__setitem__(0,r['vertices'][1]),
                 lambda r:r['faces'][0].update(vertices=[True,1,2]),lambda r:r['faces'][0].update(normal=[0,0,0]),
                 lambda r:r['vertices'][0].__setitem__(0,float('nan'))]
        for change in changes:
            other=copy.deepcopy(self.inventory);change(other)
            with self.assertRaises(SchemaxisError):self.check(other)

    def test_saved_brep_top_level_location_is_bound_before_local_geometry(self):
        from schemaxis.adaptors.freecad.mesh_geometry import verify_placement
        expected=[1,0,0,120,0,1,0,-25,0,0,1,16]
        verify_placement(expected,expected,'mesh')
        changed=list(expected);changed[3]+=1
        with self.assertRaises(SchemaxisError):verify_placement(changed,expected,'mesh')
        changed=list(expected);changed[3]=float('nan')
        with self.assertRaises(SchemaxisError):verify_placement(changed,expected,'mesh')
