"""Primitive semantics and independent analytic checks, without native imports."""
import copy
import json
import math
from pathlib import Path
import unittest

from schemaxis.adaptors.gmsh import adaptor, geometry
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]


def document(kind):
    return json.loads((ROOT/'examples/schemaxis'/('gmsh-'+kind.replace('hollowCylinder','hollow-cylinder')+'.json')).read_text())


class PrimitiveTests(unittest.TestCase):
    def test_schema_and_immutable_defaults_for_all_primitive_sources(self):
        from jsonschema import Draft202012Validator
        validator = Draft202012Validator(adaptor.schema())
        for kind in ('cylinder','hollowCylinder','sphere'):
            d = document(kind); d['nodes'][0]['options'] = {}
            before = copy.deepcopy(d)
            self.assertTrue(validator.is_valid(d))
            first = adaptor.plan(d)
            self.assertEqual(first,adaptor.plan(d)); self.assertEqual(d,before)
            self.assertEqual(first['nodes'][0]['options']['radius'],5)
            self.assertEqual(first['nodes'][1]['options']['algorithm'],'delaunay' if kind!='hollowCylinder' else 'hxt')

    def test_exact_faults_before_native_assignment(self):
        for kind,field,value,code in (
            ('hollowCylinder','innerRadius',4,'INVALID_ARGUMENT'),
            ('hollowCylinder','innerRadius',3.9995,'INVALID_ARGUMENT'),
            ('cylinder','axis','negative-z','INVALID_ARGUMENT'),
            ('sphere','radius',0,'INVALID_ARGUMENT'),
            ('sphere','radius',float('nan'),'INVALID_ARGUMENT')):
            d=document(kind);d['nodes'][0]['options'][field]=value
            with self.subTest(kind=kind,field=field,value=value), self.assertRaises(SchemaxisError) as caught:
                adaptor.plan(d)
            self.assertEqual(caught.exception.fault.code,code)
            if field=='innerRadius': self.assertEqual(caught.exception.fault.location,'solid.options.innerRadius')
        d=document('sphere');d['nodes'][1]['options']['size']=0.001
        with self.assertRaises(SchemaxisError) as caught: adaptor.plan(d)
        self.assertEqual(caught.exception.fault.code,'RESOURCE_LIMIT')

    def test_area_budget_and_meshing_choices_are_typed_and_bounded(self):
        for field,value in [('algorithm','frontal'),('optimise',1),('optimise','false')]:
            d=document('cylinder');d['nodes'][1]['options'][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(SchemaxisError):adaptor.plan(d)
        for value in (0,0.02001,float('nan')):
            d=document('cylinder');d['nodes'][1]['options']['faceGroups'][0]['areaTolerance']=value
            with self.subTest(value=value),self.assertRaises(SchemaxisError):adaptor.plan(d)
        d=document('cylinder');del d['nodes'][1]['options']['faceGroups'][0]['areaTolerance']
        g=adaptor.plan(d)['nodes'][1]['options']['faceGroups'][0]
        self.assertEqual(g['areaTolerance'],1e-10);self.assertEqual(g['tolerance'],1e-6)

    def test_analytic_volume_bounds_cap_areas_and_radial_containment(self):
        literals={'cylinder':(226.1946710584651,[-1,-4,3,5,2,11],28.274333882308138),
                  'hollowCylinder':(301.59289474462014,[0,-4,-4,8,4,4],37.69911184307752),
                  'sphere':(113.09733552923255,[-2,-1,0,4,5,6],None)}
        for kind,(volume,bounds,area) in literals.items():
            source=adaptor.plan(document(kind))['nodes'][0]
            self.assertAlmostEqual(geometry.measures(source)[0],volume)
            self.assertEqual(geometry.measures(source)[1],bounds)
            if area:self.assertAlmostEqual(geometry.face_area(source,adaptor.plan(document(kind))['nodes'][1]['options']['faceGroups'][0]),area)
            cad={'volume':volume,'bounds':bounds}
            good = {'cylinder':[2,-1,4],'hollowCylinder':[4,3,0],'sphere':[1,2,3]}[kind]
            geometry.verify(source,cad,{'nodes':{1:good}})
            bad = {'cylinder':[-1,-4,4],'hollowCylinder':[4,0,0],'sphere':[-2,-1,0]}[kind]
            with self.subTest(kind=kind),self.assertRaises(SchemaxisError):geometry.verify(source,cad,{'nodes':{1:bad}})
            with self.assertRaises(SchemaxisError):geometry.verify(source,dict(cad,volume=volume*1.01),{'nodes':{1:good}})
            with self.assertRaises(SchemaxisError):geometry.verify(source,dict(cad,bounds=[v+0.01 for v in bounds]),{'nodes':{1:good}})

    def test_boundary_dents_inside_the_envelope_are_independently_refused(self):
        for kind,points in (
            ('sphere',[[4,2,3],[1,5,3],[1,2,5.99]]),
            ('cylinder',[[5,-1,4],[2,2,4],[4.99,-1,5]]),
            ('hollowCylinder',[[4,4,0],[4,0,4],[5,3.99,0]])):
            source=adaptor.plan(document(kind))['nodes'][0]
            volume,bounds=geometry.measures(source);cad={'volume':volume,'bounds':bounds}
            data={'nodes':dict(enumerate(points,1))}
            geometry.verify(source,cad,data)  # Every vertex lies inside the envelope.
            data['cells']=[(2,2,(1,2,3))]
            with self.subTest(kind=kind),self.assertRaises(SchemaxisError) as caught:
                geometry.verify(source,cad,data)
            self.assertIn('analytic primitive surface',caught.exception.fault.message)

    def test_axis_selection_changes_exact_dimensions_and_cap_areas(self):
        for axis in 'xyz':
            d=document('cylinder');d['nodes'][0]['options'].update(origin=[0,0,0],axis=axis,radius=2,height=7)
            source=adaptor.plan(d)['nodes'][0];volume,bounds=geometry.measures(source)
            self.assertAlmostEqual(volume,28*math.pi)
            i='xyz'.index(axis);self.assertEqual(bounds[i],0);self.assertEqual(bounds[i+3],7)
            self.assertAlmostEqual(geometry.face_area(source,{'axis':axis,'coordinate':7,'tolerance':1e-6}),4*math.pi)


if __name__=='__main__':unittest.main()
