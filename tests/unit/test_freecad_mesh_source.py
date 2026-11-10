"""Kernel-independent STL topology and material integrals before native calls."""
import math,struct,unittest
from schemaxis.adaptors.freecad import mesh_source
from schemaxis.core.faults import SchemaxisError


def box(length=10,width=20,height=30,origin=(0,0,0)):
    points=[(0,0,0),(length,0,0),(length,width,0),(0,width,0),(0,0,height),(length,0,height),(length,width,height),(0,width,height)]
    points=[tuple(p[i]+origin[i] for i in range(3)) for p in points]
    faces=[(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),(1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]
    return [tuple(points[i] for i in face) for face in faces]


def binary(triangles,header=b'solid binary header'):
    return header.ljust(80,b' ')+struct.pack('<I',len(triangles))+b''.join(struct.pack('<12fH',0,0,0,*[x for p in t for x in p],0) for t in triangles)


def ascii_stl(triangles):
    lines=['solid test']
    for triangle in triangles:
        lines+=['facet normal 0 0 0','outer loop',*['vertex '+' '.join(map(str,p)) for p in triangle],'endloop','endfacet']
    return ('\n'.join([*lines,'endsolid test'])+'\n').encode()


class MeshSources(unittest.TestCase):
    def rejected(self,data,**options):
        with self.assertRaises(SchemaxisError) as caught:mesh_source.admit(data,'mesh',**options)
        self.assertEqual(caught.exception.fault.code,'INVALID_MESH')

    def test_binary_ascii_and_large_translation_use_local_material_integrals(self):
        for make in (binary,ascii_stl):
            for origin in [(0,0,0),(4000,5000,6000)]:
                record,vertices,faces=mesh_source.admit(make(box(origin=origin)),'mesh')
                self.assertEqual(record['facets'],12);self.assertEqual(record['vertices'],8)
                self.assertAlmostEqual(record['volume'],6000);self.assertAlmostEqual(record['area'],2200)
                self.assertEqual(record['centreOfMass'],[origin[i]+x for i,x in enumerate([5,10,15])])
                self.assertEqual(len(vertices),8);self.assertTrue(all(0<=i<8 for face in faces for i in face))
        data=ascii_stl(box()).replace(b'\n',b'\r\n')
        self.assertEqual(mesh_source.admit(b'\xef\xbb\xbf'+data,'mesh')[0]['volume'],6000)

    def test_explicit_unit_scaling_and_global_winding_reversal(self):
        raw=box();inverted=[(a,c,b) for a,b,c in raw]
        self.rejected(binary(inverted))
        actual=mesh_source.admit(binary(inverted),'mesh',scale=25.4,reverse=True)[0]
        self.assertTrue(math.isclose(actual['volume'],6000*25.4**3,rel_tol=1e-14))
        self.assertTrue(math.isclose(actual['area'],2200*25.4**2,rel_tol=1e-14))
        for value in [False,float('nan'),float('inf'),10**1000,-1,0]:self.rejected(binary(raw),scale=value)
        self.rejected(binary(raw),reverse=1)

    def test_closed_hollow_shells_preserve_signed_cavity_material(self):
        raw=box(20,20,20,(-10,-10,-10))+[(a,c,b) for a,b,c in box(10,10,10,(-5,-5,-5))]
        facts,_,_=mesh_source.admit(binary(raw),'mesh')
        self.assertEqual(facts['vertices'],16);self.assertAlmostEqual(facts['volume'],7000)
        self.assertEqual(facts['centreOfMass'],[0,0,0])

    def test_open_repeated_collinear_inconsistent_and_pinched_topology_refused(self):
        raw=box()
        for triangles in [raw[:-1],raw+[raw[0]],raw+[(raw[0][0],raw[0][2],raw[0][1])],
                          [(raw[0][0],raw[0][2],raw[0][1]),*raw[1:]],
                          [((0,0,0),(1,0,0),(2,0,0)),*raw[1:]],
                          box(1,1,1)+box(1,1,1,(-1,-1,-1))]:
            with self.subTest(triangles=len(triangles)):self.rejected(binary(triangles))

    def test_nonfinite_malformed_oversized_and_foreign_ascii_data_refused(self):
        raw=binary(box())
        corrupt=bytearray(raw);struct.pack_into('<f',corrupt,84,float('nan'));self.rejected(bytes(corrupt))
        for data in [raw[:-1],raw+b'x',b'',b'not STL',ascii_stl(box()).replace(b'endloop',b'unknown',1),
                     ascii_stl(box()).replace(b'vertex 0 0 0',b'vertex __import__(x) 0 0',1),
                     ascii_stl(box())+b'Python payload\n']:
            with self.subTest(bytes=len(data)):self.rejected(data)
        self.rejected(b'x'*(mesh_source.MAX_BYTES+1))
        self.rejected(b'x'*80+struct.pack('<I',mesh_source.MAX_FACETS+1)+b'\0'*50*(mesh_source.MAX_FACETS+1))
