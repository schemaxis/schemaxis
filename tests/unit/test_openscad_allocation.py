"""Exact-boundary clearance semantics for OpenSCAD planning, without native code."""
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch
import struct
from schemaxis.adaptors.openscad import adaptor as a, geometry as g
from schemaxis.core.faults import SchemaxisError
ROOT=Path(__file__).resolve().parents[2]


def plate(holes,width=20,depth=20):
    return {'version':a.VERSION,'operation':'plate','units':'mm','plate':{'width':width,'depth':depth,'height':2,'holes':holes}}


def annulus(outer,bore,height,n):
    # Independent construction of the exact faceted annulus, outward-oriented.
    ring=lambda r,z:[(r*math.cos(2*math.pi*k/n),r*math.sin(2*math.pi*k/n),z) for k in range(n)]
    O0,O1,B0,B1=ring(outer/2,0),ring(outer/2,height),ring(bore/2,0),ring(bore/2,height)
    triangles=[]
    def add(tri,want):
        normal=g.cross(g.sub(tri[1],tri[0]),g.sub(tri[2],tri[0]))
        triangles.append(tri if g.dot(normal,want)>0 else [tri[0],tri[2],tri[1]])
    for k in range(n):
        j=(k+1)%n;mid=lambda a,b:((a[0]+b[0])/2,(a[1]+b[1])/2,0)
        add([O0[k],O0[j],O1[j]],mid(O0[k],O0[j]));add([O0[k],O1[j],O1[k]],mid(O0[k],O0[j]))
        inward=tuple(-c for c in mid(B0[k],B0[j]))
        add([B0[k],B0[j],B1[j]],inward);add([B0[k],B1[j],B1[k]],inward)
        add([O1[k],O1[j],B1[j]],(0,0,1));add([O1[k],B1[j],B1[k]],(0,0,1))
        add([O0[k],O0[j],B0[j]],(0,0,-1));add([O0[k],B0[j],B0[k]],(0,0,-1))
    data=bytearray(b'independent annulus'.ljust(80,b'\0')+struct.pack('<I',len(triangles)))
    for tri in triangles:
        normal=g.cross(g.sub(tri[1],tri[0]),g.sub(tri[2],tri[0]));length=math.sqrt(g.dot(normal,normal))
        data.extend(struct.pack('<12fH',*(c/length for c in normal),*(c for v in tri for c in v),0))
    return bytes(data)


def spacer(outer,bore):
    return {'version':a.VERSION,'operation':'spacer','units':'mm','spacer':{'outerDiameter':outer,'boreDiameter':bore,'height':2}}


class OpenSCADBoundaryClearance(unittest.TestCase):
    def fault(self,document):
        with self.assertRaises(SchemaxisError) as caught:a.plan(document)
        self.assertEqual(caught.exception.fault.code,'INVALID_CAD_CLEARANCE',caught.exception.fault.to_dict())
        return caught.exception.fault
    def test_exact_decimal_spacer_wall_is_accepted(self):
        # Each pair differs by exactly 1 mm as typed; binary subtraction does not.
        for outer,bore in [(3.3,2.3),(4.6,3.6),(8.2,7.2),(10.3,9.3)]:
            with self.subTest(outer=outer,bore=bore):
                with patch.object(a,'execute',side_effect=AssertionError('native called')):p=a.plan(spacer(outer,bore))
                self.assertEqual(p['spacer']['boreDiameter'],bore)
    def test_exact_decimal_hole_edge_clearance_is_accepted(self):
        a.plan(plate([{'centre':[.95,10],'diameter':.9}]))
        a.plan(plate([{'centre':[1.4,10],'diameter':1.8}]))
        # Upper edges: width-0.5-radius from the opposite corner.
        a.plan(plate([{'centre':[11.55,10],'diameter':1.3}],width=12.7))
        a.plan(plate([{'centre':[10,11.55],'diameter':1.3}],depth=12.7))
    def test_exact_decimal_hole_separation_is_accepted(self):
        a.plan(plate([{'centre':[5,10],'diameter':1.1},{'centre':[6.6,10],'diameter':1.1}]))
        a.plan(plate([{'centre':[5,10],'diameter':1.3},{'centre':[6.8,10],'diameter':1.3}]))
    def test_genuine_violations_still_fault_with_measurements(self):
        f=self.fault(spacer(4.6,3.6001));self.assertEqual(f.location,'$.spacer.boreDiameter')
        self.assertEqual(f.observed['required'],1);self.assertAlmostEqual(f.observed['measured'],.9999,9)
        f=self.fault(plate([{'centre':[.9499,10],'diameter':.9}]));self.assertEqual(f.location,'$.plate.holes[0]')
        self.assertEqual(f.observed['required'],.5);self.assertAlmostEqual(f.observed['measured'],.4999,9)
        f=self.fault(plate([{'centre':[5,10],'diameter':1.1},{'centre':[6.5999,10],'diameter':1.1}]))
        self.assertEqual(f.location,'$.plate.holes[1]');self.assertAlmostEqual(f.observed['measured'],.4999,9)
        self.fault(plate([{'centre':[5,10],'diameter':1.1},{'centre':[5.2,10],'diameter':1.1}]))
    def test_boundary_documents_generate_only_numeric_source(self):
        p=a.plan(spacer(4.6,3.6));source=a.scad(p)
        self.assertIn('cylinder(h=2,d=4.6,$fn=64)',source);self.assertIn('d=3.6,$fn=64',source)
        self.assertNotIn('e-',source)
    def test_verifier_accepts_the_exact_minimum_wall_that_planning_now_admits(self):
        # Planning must not admit a boundary the independent geometry check cannot
        # verify: 4.6/3.6 mm is a 0.5 mm nominal radial wall.
        p=a.plan(spacer(4.6,3.6));result=g.inspect(annulus(4.6,3.6,2,p['segments']),p)
        self.assertEqual(result['eulerCharacteristic'],0);self.assertTrue(result['closedOriented'])
        self.assertAlmostEqual(result['volume'],result['expectedFacetedVolume'],4)
    def test_published_example_fixtures_unchanged(self):
        invalid=json.loads((ROOT/'examples/schemaxis/openscad-clearance-invalid.json').read_text())
        self.assertEqual(self.fault(invalid).location,'$.plate.holes[0]')
        a.plan(json.loads((ROOT/'examples/schemaxis/openscad-plate.json').read_text()))

if __name__=='__main__':unittest.main()
